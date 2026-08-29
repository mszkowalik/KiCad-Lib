"""Simulation models and symbol↔model links — the REST face of
`services/sim_store.py` for the web UI (Templates → Sim models tab, and the
link editor on a symbol template page).

Same auto-publish contract as geometry: a propose PUBLISHES, the Preview-less
equivalent of GeometryPaste. Validation errors come back as
`HTTPException(400, detail={"error": ..., ...context})` so `request()` renders
the self-contained message and a machine caller keeps the context.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..db import get_db
from ..services import material
from ..services.simcompose import (
    COMPOSED_KIND,
    compose,
    wrapper_name,
    wrapper_params,
)
from ..services.simmodel import (
    NC,
    link_material_sha,
    model_material_sha,
    parse_subckt,
    sim_pins_value,
)
from ..services.sim_store import (
    block_catalog,
    composed_stale_reasons,
    delete_sim_model,
    propose_sim_model_version,
    set_symbol_sim_composition,
    set_symbol_sim_link,
)

router = APIRouter(prefix="/api", tags=["sim-models"])


def _current(model: M.SimModel) -> M.SimModelVersion | None:
    return next((v for v in model.versions if v.id == model.current_version_id), None)


def _link_counts(db: Session) -> dict[int, int]:
    rows = db.query(M.SymbolSimLink.sim_model_id).all()
    out: dict[int, int] = {}
    for (mid,) in rows:
        out[mid] = out.get(mid, 0) + 1
    return out


# ---------------------------------------------------------------- models
@router.get("/sim-models")
def list_sim_models(db: Session = Depends(get_db)):
    models = (
        db.query(M.SimModel)
        .options(selectinload(M.SimModel.versions))
        .order_by(M.SimModel.name)
        .all()
    )
    counts = _link_counts(db)
    out = []
    for m in models:
        cur = _current(m)
        parsed = (cur.parsed or {}) if cur else {}
        out.append({
            "id": m.id,
            "name": m.name,
            "kind": m.kind,
            "version_no": cur.version_no if cur else None,
            "ports": parsed.get("ports") or [],
            "params": parsed.get("params") or {},
            "linked_symbols": counts.get(m.id, 0),
        })
    return out


@router.get("/sim-models/{model_id}")
def get_sim_model(model_id: int, db: Session = Depends(get_db)):
    m = db.get(M.SimModel, model_id)
    if m is None:
        raise HTTPException(404, "sim model not found")
    cur = _current(m)
    parsed = (cur.parsed or {}) if cur else {}
    links = (
        db.query(M.Symbol.id, M.Symbol.name)
        .join(M.SymbolSimLink, M.SymbolSimLink.symbol_id == M.Symbol.id)
        .filter(M.SymbolSimLink.sim_model_id == m.id)
        .order_by(M.Symbol.name)
        .all()
    )
    return {
        "id": m.id,
        "name": m.name,
        "kind": m.kind,
        "version_no": cur.version_no if cur else None,
        "created_at": cur.created_at.isoformat() if cur else None,
        "created_by": cur.created_by if cur else None,
        "comment": cur.comment if cur else None,
        "ports": parsed.get("ports") or [],
        "params": parsed.get("params") or {},
        "instantiates": parsed.get("instantiates") or [],
        "source_text": cur.source_text if cur else None,
        "linked_symbols": [{"id": sid, "name": name} for sid, name in links],
        "versions": [
            {"version_no": v.version_no, "created_at": v.created_at.isoformat(),
             "created_by": v.created_by, "comment": v.comment}
            for v in sorted(m.versions, key=lambda v: v.version_no, reverse=True)
        ],
    }


class SimModelProposal(BaseModel):
    source_text: str
    comment: str
    kind: str | None = None  # primitive | part; None keeps/creates default


@router.post("/sim-models/propose")
def propose_new_sim_model(body: SimModelProposal, db: Session = Depends(get_db)):
    """Create a brand-new model. The name is READ OUT of the `.subckt` line —
    there is no name field for the same reason GeometryPaste has none."""
    try:
        name = parse_subckt(body.source_text)["name"]
    except ValueError as e:
        raise HTTPException(400, detail={"error": f"not a usable subcircuit: {e}"})
    if db.query(M.SimModel).filter_by(name=name).first() is not None:
        raise HTTPException(400, detail={
            "error": f"sim model {name!r} already exists — open it and propose an edit there"})
    res = propose_sim_model_version(db, name, body.source_text, body.comment,
                                    actor="user", kind=body.kind)
    if "error" in res:
        raise HTTPException(400, detail=res)
    return res


@router.post("/sim-models/{model_id}/propose")
def propose_sim_model_edit(model_id: int, body: SimModelProposal, db: Session = Depends(get_db)):
    m = db.get(M.SimModel, model_id)
    if m is None:
        raise HTTPException(404, "sim model not found")
    # The row name is the reference every link and Sim.Name resolves — a paste
    # that renames the subckt is a different model, not a new version of this
    # one. sim_store enforces text-name == row-name; this call pins the row's.
    res = propose_sim_model_version(db, m.name, body.source_text, body.comment,
                                    actor="user", kind=body.kind)
    if "error" in res:
        raise HTTPException(400, detail=res)
    return res


# ---------------------------------------------------------------- symbol link
def _stale_reasons(db: Session, link: M.SymbolSimLink, pins: list[dict],
                   mv: M.SimModelVersion | None) -> list[str]:
    if mv is None:
        return ["the model has no published version"]
    if link.mode == COMPOSED_KIND:
        # Derived, so there is no stamp to compare — the question is whether
        # the design still builds. Same call the mirror makes, so the editor
        # and the library can never disagree about whether a link is usable.
        return composed_stale_reasons(link.symbol.name, link.composition or {}, pins,
                                      mv.source_text, block_catalog(db))
    reasons = []
    if link.symbol_material_sha != link_material_sha(pins):
        reasons.append("the symbol's pins changed since this map was authored")
    if link.model_material_sha != model_material_sha(mv.source_text):
        reasons.append("the model's port list changed since this map was authored")
    return reasons


@router.get("/symbols/{sym_id}/sim-link")
def get_symbol_sim_link(sym_id: int, db: Session = Depends(get_db)):
    """Everything the link editor needs in one round trip: the current link
    (with staleness), the symbol's live pins, and every linkable model."""
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    sv = next((v for v in s.versions if v.id == s.current_version_id), None)
    pins: list[dict] = []
    if sv is not None:
        try:
            pins = material.symbol_material(sv.source_text)["pins"]
        except Exception:  # noqa: BLE001 — an unparsable symbol still gets a page
            pins = []
    link = db.query(M.SymbolSimLink).filter_by(symbol_id=s.id).first()
    link_out = None
    if link is not None:
        mv = _current(link.sim_model)
        link_out = {
            "model_id": link.sim_model.id,
            "model_name": link.sim_model.name,
            "pin_map": link.pin_map,
            "mode": link.mode,
            "composition": link.composition,
            "updated_at": link.updated_at.isoformat() if link.updated_at else None,
            "updated_by": link.updated_by,
            "stale": _stale_reasons(db, link, pins, mv),
        }
    # ALL models, primitives included: a symbol whose part IS the primitive
    # (a diode, a switch, an opamp in a 5-pin package) links to it directly —
    # the seed did exactly that, so a part-only filter would hide most of the
    # working links from their own editor.
    models = (
        db.query(M.SimModel)
        .options(selectinload(M.SimModel.versions))
        .order_by(M.SimModel.name)
        .all()
    )
    return {
        "symbol": {"id": s.id, "name": s.name},
        "pins": [{"number": p.get("number"), "name": p.get("name"),
                  "type": p.get("type"), "hide": bool(p.get("hide"))} for p in pins],
        "link": link_out,
        "models": [
            {"id": m.id, "name": m.name, "kind": m.kind,
             "ports": ((_current(m).parsed or {}).get("ports") if _current(m) else None) or [],
             "params": ((_current(m).parsed or {}).get("params") if _current(m) else None) or {}}
            for m in models
        ],
        # What a composition may use as a block. Narrower than `models`: a
        # generated wrapper is package-shaped and belongs to one symbol, so it
        # is never a building block for another.
        "blocks": [
            {"name": name, "kind": spec["kind"], "ports": spec["ports"],
             "params": spec["params"]}
            for name, spec in sorted(block_catalog(db).items())
        ],
        "wrapper_name": wrapper_name(s.name),
        "nc": NC,
    }


class SimLinkBody(BaseModel):
    model_name: str
    pin_map: dict[str, str]


@router.put("/symbols/{sym_id}/sim-link")
def put_symbol_sim_link(sym_id: int, body: SimLinkBody, db: Session = Depends(get_db)):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    if not body.model_name.strip():
        raise HTTPException(400, detail={"error": "model_name must not be empty — "
                                                  "use DELETE to remove the link"})
    res = set_symbol_sim_link(db, s.name, body.model_name, body.pin_map, actor="user")
    if "error" in res:
        # request() renders detail.error alone, so the message must carry the
        # facts itself — the sibling keys are for machine callers.
        if res.get("problems"):
            res = {**res, "error": f"{res['error']}: {'; '.join(res['problems'])}"}
        raise HTTPException(400, detail=res)
    return res


@router.delete("/symbols/{sym_id}/sim-link")
def delete_symbol_sim_link(sym_id: int, db: Session = Depends(get_db)):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    res = set_symbol_sim_link(db, s.name, "", {}, actor="user")
    if "error" in res:
        raise HTTPException(400, detail=res)
    return res


# ---------------------------------------------------------------- composition
class CompositionBody(BaseModel):
    """The authored half of a composed link.

    `blocks[].nodes` is `{model port: node}`, where a node is a symbol PIN
    NUMBER or an internal net written `@name`. `blocks[].params` is
    `{model param: binding}` — `$shared` (the default, and what every
    hand-written dual-gate wrapper in this library already does), `$shared:NAME`
    to share under another name, `$own` for one wrapper parameter per block, or
    a literal SPICE value. `unmodelled` is the composed form of the `-`
    sentinel: pins left out ON PURPOSE, stated rather than forgotten.
    """
    blocks: list[dict] = []
    resistors: list[dict] = []
    unmodelled: list[str] = []
    # Wrapper parameter defaults that differ from the block model's own. A
    # component with no Sim.Params row runs on these, so they are part of the
    # part's behaviour, not decoration.
    defaults: dict[str, str] = {}
    comment: str = ""

    def as_composition(self) -> dict:
        return {"blocks": self.blocks, "resistors": self.resistors,
                "unmodelled": self.unmodelled, "defaults": self.defaults}


def _symbol_pins(db: Session, sym_id: int):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    sv = next((v for v in s.versions if v.id == s.current_version_id), None)
    if sv is None:
        raise HTTPException(400, detail={"error": "symbol has no published version"})
    try:
        return s, material.symbol_material(sv.source_text)["pins"]
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, detail={"error": f"symbol source does not parse: {e}"})


@router.post("/symbols/{sym_id}/sim-composition/preview")
def preview_sim_composition(sym_id: int, body: CompositionBody, db: Session = Depends(get_db)):
    """The `.subckt` this composition would publish, without publishing it.

    Generation without a visible artifact is the whole risk of composing, so
    the editor shows the text live and the reviewer reads what will actually
    run — not a description of it.
    """
    s, pins = _symbol_pins(db, sym_id)
    catalog = block_catalog(db)
    composition = body.as_composition()
    built = compose(s.name, composition, pins, catalog)
    declared, _ = wrapper_params(composition, catalog)
    return {
        "name": wrapper_name(s.name),
        # The wrapper's own parameter list, so the editor can offer a default
        # for each without parsing the generated text back out.
        "params": declared,
        "source_text": built["source_text"],
        "ports": built["ports"],
        "pin_map": built["pin_map"],
        "sim_pins": sim_pins_value(built["pin_map"]),
        "errors": [p["text"] for p in built["problems"] if p["severity"] == "error"],
        "warnings": [p["text"] for p in built["problems"] if p["severity"] == "warning"],
    }


@router.put("/symbols/{sym_id}/sim-composition")
def put_sim_composition(sym_id: int, body: CompositionBody, db: Session = Depends(get_db)):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    res = set_symbol_sim_composition(db, s.name, body.as_composition(),
                                     actor="user", comment=body.comment)
    if "error" in res:
        if res.get("problems"):
            res = {**res, "error": f"{res['error']}: {'; '.join(res['problems'])}"}
        raise HTTPException(400, detail=res)
    return res


@router.delete("/sim-models/{model_id}")
def remove_sim_model(model_id: int, db: Session = Depends(get_db)):
    m = db.get(M.SimModel, model_id)
    if m is None:
        raise HTTPException(404, "sim model not found")
    res = delete_sim_model(db, m.name, actor="user")
    if "error" in res:
        raise HTTPException(400, detail=res)
    return res
