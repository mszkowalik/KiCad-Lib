"""DB operations for sim models and symbol↔model links.

Split from `simmodel.py` on purpose: that module is pure text-level (parsing,
fingerprints, map validation) and importable from anywhere; this one owns the
rows, the publish flow and the mirror refresh. Same auto-publish contract as
geometry: every write is live immediately, accountability is the audit log
plus the mirror warnings a stale link keeps emitting until it is fixed.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from . import material
from .simcompose import COMPOSED_KIND, compose, wrapper_name
from .simmodel import (
    NC,
    link_material_sha,
    model_material_sha,
    parse_subckt,
    validate_pin_map,
)

# SPICE subckt names live in one flat global namespace shared with every
# model the user's other libraries load, so ours are namespaced by prefix —
# `7Sigma:` style namespacing is not available (':' is illegal in a name).
NAME_RE = re.compile(r"^sigma_[a-z0-9_]+$")


def _refresh_mirror(db: Session) -> list[str]:
    """Full symbol-lib + sim-lib + manifest rewrite.

    Deliberately not incremental: a model edit can flip links stale, which
    changes emitted Sim fields on components in ANY top-level library, and a
    link edit likewise. Model/link writes are rare (symbol-scoped, not
    component-scoped), so the cost profile matches a geometry publish.
    """
    from .mirror import write_manifest, write_symbol_libs

    result = write_symbol_libs(db, settings)
    write_manifest(settings)
    return result.get("warnings", [])


def _versions(db: Session, model: M.SimModel) -> list[M.SimModelVersion]:
    """Query the version rows instead of reading `model.versions`.

    The session runs `expire_on_commit=False` and a version added here is not
    appended to an already-loaded relationship, so `model.versions` goes stale
    the moment this module adds one. Reading it made `write_sim_lib` — which
    runs in THIS session after the commit — look for `current_version_id` in a
    collection that did not hold it, so the mirror silently omitted whichever
    model was published last. Same trap as `services/repoint.py`.
    """
    return db.query(M.SimModelVersion).filter_by(sim_model_id=model.id).all()


def block_catalog(db: Session) -> dict[str, dict]:
    """Every model a composition may use as a block: `{name: {ports, params}}`.

    Composed wrappers are excluded. They are package-shaped, derived, and owned
    by one symbol — instantiating one inside another would build a cycle nobody
    asked for, and there is no case for it in this library.
    """
    out: dict[str, dict] = {}
    for m in db.query(M.SimModel).all():
        if m.kind == COMPOSED_KIND:
            continue
        mv = next((v for v in _versions(db, m) if v.id == m.current_version_id), None)
        if mv is None or mv.status != "published":
            continue
        parsed = mv.parsed or {}
        out[m.name] = {"kind": m.kind, "ports": parsed.get("ports") or [],
                       "params": parsed.get("params") or {},
                       # the mirror keys its staleness cache on this: a block's
                       # new version can invalidate a composition that has not
                       # itself changed.
                       "version_id": mv.id}
    return out


def composed_stale_reasons(symbol_name: str, composition: dict, pins: list[dict],
                           published_source: str, catalog: dict) -> list[str]:
    """Why a composed link must not reach a netlist, or an empty list.

    Derived state needs no fingerprint. There are exactly two ways a composed
    link can be wrong: the block design no longer builds against today's block
    models, or the wrapper that IS published is not the one the design builds.
    The first self-heals when the block model is fixed, which a stamped
    fingerprint never does.

    One implementation, three callers — the mirror (which withholds the Sim
    fields), the link editor and the validator — because three copies of a
    staleness rule is how they stop agreeing.
    """
    built = compose(symbol_name, composition or {}, pins, catalog)
    reasons = [p["text"] for p in built["problems"] if p["severity"] == "error"]
    if reasons:
        return reasons
    if built["source_text"].strip() != (published_source or "").strip():
        return ["the published wrapper is behind its block design — open the symbol "
                "and save the composition again"]
    return []


def _drop_generated(db: Session, symbol_name: str, keep_id: int | None = None) -> str | None:
    """Delete the wrapper generated for this symbol, if nothing links to it.

    A composed wrapper exists only to serve its own symbol's link. Leaving it
    behind after a switch back to `model` mode is exactly how `sigma_74hc21`
    and `sigma_buf2` ended up in the library linked to nothing.
    """
    name = wrapper_name(symbol_name)
    model = db.query(M.SimModel).filter_by(name=name).first()
    if model is None or model.id == keep_id or model.kind != COMPOSED_KIND:
        return None
    if db.query(M.SymbolSimLink).filter_by(sim_model_id=model.id).count():
        return None
    db.query(M.SimModelVersion).filter_by(sim_model_id=model.id).delete()
    db.delete(model)
    return name


def delete_sim_model(db: Session, name: str, actor: str = "user",
                     refresh: bool = True) -> dict:
    """Remove a model outright. Refuses while anything still needs it.

    Two guards, because a SPICE library that is missing a `.subckt` fails at
    the far end of the pipeline — inside ngspice, on a user's run — and not
    here where the mistake is.
    """
    model = db.query(M.SimModel).filter_by(name=name.strip()).first()
    if model is None:
        return {"error": f"sim model {name!r} not found"}
    linked = (
        db.query(M.Symbol.name)
        .join(M.SymbolSimLink, M.SymbolSimLink.symbol_id == M.Symbol.id)
        .filter(M.SymbolSimLink.sim_model_id == model.id)
        .all()
    )
    if linked:
        return {"error": f"{model.name} is still linked by "
                         f"{', '.join(sorted(n for (n,) in linked))}"}
    users: list[str] = []
    for other in db.query(M.SimModel).filter(M.SimModel.id != model.id).all():
        mv = next((v for v in _versions(db, other) if v.id == other.current_version_id), None)
        if mv is not None and model.name in ((mv.parsed or {}).get("instantiates") or []):
            users.append(other.name)
    if users:
        return {"error": f"{model.name} is instantiated by {', '.join(sorted(users))}"}

    db.query(M.SimModelVersion).filter_by(sim_model_id=model.id).delete()
    db.delete(model)
    db.add(M.AuditLog(actor=actor, action="sim_model.delete", entity_type="sim_model",
                      entity_id=str(model.id), details={"model": model.name,
                                                        "kind": model.kind}))
    db.commit()
    warnings = _refresh_mirror(db) if refresh else []
    return {"ok": True, "model": model.name, "status": "deleted",
            "mirror_warnings": warnings}


def propose_sim_model_version(
    db: Session, name: str, source_text: str, comment: str, actor: str = "jaravis",
    kind: str | None = None, refresh: bool = True,
) -> dict:
    """Create and PUBLISH a `SimModelVersion` (new name = new model).

    `name` must equal the `.subckt` name in the text — the row name IS the
    SPICE name every wrapper and every `Sim.Name` field resolves, so letting
    them differ would publish a model nothing can reference.
    """
    name = name.strip()
    if not name or not source_text.strip():
        return {"error": "name and source_text must not be empty"}
    if not NAME_RE.match(name):
        return {"error": f"model name {name!r} must match {NAME_RE.pattern} — SPICE subckt "
                         "names are global, the sigma_ prefix is the library's namespace"}
    try:
        parsed = parse_subckt(source_text)
    except ValueError as e:
        return {"error": f"source_text is not a usable subcircuit: {e}"}
    if parsed["name"] != name:
        return {"error": f"the text defines .subckt {parsed['name']!r} but the model is "
                         f"named {name!r} — they must match, the name is the reference"}

    model = db.query(M.SimModel).filter_by(name=name).first()
    is_new = model is None
    if is_new:
        model = M.SimModel(name=name, kind=kind or "part")
        db.add(model)
        db.flush()
    elif kind and kind != model.kind:
        model.kind = kind

    existing = _versions(db, model)
    cur = next((v for v in existing if v.id == model.current_version_id), None)
    if cur is not None and cur.source_text == source_text:
        return {"ok": True, "model": name, "version_no": cur.version_no,
                "status": "unchanged — identical to the published version"}

    new_no = max((v.version_no for v in existing), default=0) + 1
    mv = M.SimModelVersion(
        sim_model_id=model.id, version_no=new_no, source_text=source_text,
        parsed=parsed, status="published", created_by=actor, comment=comment or None,
        material_sha=model_material_sha(source_text),
    )
    db.add(mv)
    db.flush()
    model.current_version_id = mv.id
    db.add(M.AuditLog(actor=actor, action="sim_model.publish", entity_type="sim_model_version",
                      entity_id=str(mv.id), details={"model": name, "new": is_new,
                                                     "ports": parsed["ports"]}))
    # Interface change? Every link stamped against the old ports goes stale on
    # the next mirror resolve — surfaced there as warnings, not blocked here:
    # publishing the fixed model FIRST and re-mapping after is the normal flow.
    db.commit()
    # A composed wrapper is DERIVED from its blocks, so a block's new version
    # rebuilds it instead of flagging it stale. Guarded on kind, or a wrapper's
    # own publish would recurse straight back into here.
    regenerated: list[dict] = []
    if model.kind != COMPOSED_KIND:
        regenerated = recompose_dependents(db, name, actor=actor)
    warnings = _refresh_mirror(db) if refresh else ["mirror refresh deferred by caller"]
    return {"ok": True, "model": name, "version_no": new_no, "is_new_model": is_new,
            "kind": model.kind, "ports": parsed["ports"],
            "params": parsed["params"], "status": "published",
            "regenerated": regenerated,
            "mirror_warnings": warnings}


def set_symbol_sim_link(
    db: Session, symbol_name: str, model_name: str, pin_map: dict, actor: str = "jaravis",
    refresh: bool = True,
) -> dict:
    """Create or replace THE link of a base symbol (one per symbol).

    Validates the map against the symbol's live pins and the model's declared
    ports before anything is stored. Errors block; warnings (the rail/signal
    heuristic) are returned for the caller to judge — they are exactly the
    cases a human is supposed to look at.

    Passing `model_name=""` removes the link.
    """
    sym = db.query(M.Symbol).filter_by(name=symbol_name.strip()).first()
    if sym is None:
        return {"error": f"symbol {symbol_name!r} not found"}
    existing = db.query(M.SymbolSimLink).filter_by(symbol_id=sym.id).first()

    if not model_name.strip():
        if existing is None:
            return {"error": f"{symbol_name!r} has no sim link to remove"}
        db.delete(existing)
        db.flush()
        dropped = _drop_generated(db, sym.name)
        db.add(M.AuditLog(actor=actor, action="sim_link.remove", entity_type="symbol",
                          entity_id=str(sym.id), details={"symbol": sym.name,
                                                          "dropped_wrapper": dropped}))
        db.commit()
        warnings = _refresh_mirror(db)
        return {"ok": True, "symbol": sym.name, "status": "link removed",
                "mirror_warnings": warnings}

    model = db.query(M.SimModel).filter_by(name=model_name.strip()).first()
    if model is None:
        return {"error": f"sim model {model_name!r} not found"}
    sv = next((v for v in sym.versions if v.id == sym.current_version_id), None)
    mv = next((v for v in model.versions if v.id == model.current_version_id), None)
    if sv is None:
        return {"error": f"symbol {symbol_name!r} has no published version"}
    if mv is None:
        return {"error": f"sim model {model_name!r} has no published version"}

    try:
        pins = material.symbol_material(sv.source_text)["pins"]
    except Exception as e:  # noqa: BLE001
        return {"error": f"symbol source does not parse: {e}"}
    ports = (mv.parsed or {}).get("ports") or parse_subckt(mv.source_text)["ports"]

    pin_map = {str(k): str(v) for k, v in (pin_map or {}).items()}
    findings = validate_pin_map(pin_map, pins, ports)
    errors = [f["text"] for f in findings if f["severity"] == "error"]
    heuristic = [f["text"] for f in findings if f["severity"] == "warning"]
    if errors:
        return {"error": "pin map rejected", "problems": errors, "heuristic_warnings": heuristic,
                "symbol_pins": [{"number": p.get("number"), "name": p.get("name"),
                                 "type": p.get("type")} for p in pins if not p.get("hide")],
                "model_ports": ports,
                "nc_sentinel": NC}

    if existing is None:
        existing = M.SymbolSimLink(symbol_id=sym.id, sim_model_id=model.id, pin_map=pin_map)
        db.add(existing)
    else:
        existing.sim_model_id = model.id
        existing.pin_map = pin_map
    # Back to a hand-written model: the block design and the wrapper it built
    # are no longer the truth about this symbol, so neither survives.
    existing.mode = "model"
    existing.composition = None
    db.flush()
    _drop_generated(db, sym.name, keep_id=model.id)
    existing.symbol_material_sha = link_material_sha(pins)
    existing.model_material_sha = model_material_sha(mv.source_text)
    existing.updated_by = actor
    existing.updated_at = M.utcnow()

    db.add(M.AuditLog(actor=actor, action="sim_link.set", entity_type="symbol",
                      entity_id=str(sym.id),
                      details={"symbol": sym.name, "model": model.name, "pin_map": pin_map,
                               "heuristic_warnings": heuristic}))
    db.commit()
    warnings = _refresh_mirror(db) if refresh else ["mirror refresh deferred by caller"]
    return {"ok": True, "symbol": sym.name, "model": model.name, "pin_map": pin_map,
            "heuristic_warnings": heuristic, "status": "linked",
            "mirror_warnings": warnings}


def set_symbol_sim_composition(
    db: Session, symbol_name: str, composition: dict, actor: str = "user",
    comment: str = "", refresh: bool = True,
) -> dict:
    """Build this symbol's wrapper from `composition` and link it.

    The composition is the authored artifact. The `.subckt` text, the port
    list and the pin map are all derived from it, republished on every save,
    and regenerated whenever a block model publishes a new version — so the
    three can never drift apart the way a hand-written wrapper and its stored
    map could.

    Errors block. Warnings (the rail heuristic, a shared parameter taking one
    of two defaults) come back for the caller to judge, exactly as the
    hand-written path returns them.
    """
    sym = db.query(M.Symbol).filter_by(name=symbol_name.strip()).first()
    if sym is None:
        return {"error": f"symbol {symbol_name!r} not found"}
    sv = next((v for v in sym.versions if v.id == sym.current_version_id), None)
    if sv is None:
        return {"error": f"symbol {symbol_name!r} has no published version"}
    try:
        pins = material.symbol_material(sv.source_text)["pins"]
    except Exception as e:  # noqa: BLE001
        return {"error": f"symbol source does not parse: {e}"}

    catalog = block_catalog(db)
    built = compose(sym.name, composition, pins, catalog)
    errors = [p["text"] for p in built["problems"] if p["severity"] == "error"]
    heuristic = [p["text"] for p in built["problems"] if p["severity"] == "warning"]
    if errors:
        return {"error": "composition rejected", "problems": errors,
                "heuristic_warnings": heuristic}

    name = wrapper_name(sym.name)
    published = propose_sim_model_version(
        db, name, built["source_text"],
        comment or f"Composed from {len(composition.get('blocks') or [])} block(s) "
                   f"for symbol {sym.name}.",
        actor=actor, kind=COMPOSED_KIND, refresh=False,
    )
    if "error" in published:
        return published

    model = db.query(M.SimModel).filter_by(name=name).first()
    mv = next((v for v in _versions(db, model) if v.id == model.current_version_id), None)
    link = db.query(M.SymbolSimLink).filter_by(symbol_id=sym.id).first()
    if link is None:
        link = M.SymbolSimLink(symbol_id=sym.id, sim_model_id=model.id,
                               pin_map=built["pin_map"])
        db.add(link)
    else:
        link.sim_model_id = model.id
        link.pin_map = built["pin_map"]
    link.mode = "composed"
    link.composition = composition
    link.symbol_material_sha = link_material_sha(pins)
    link.model_material_sha = model_material_sha(mv.source_text)
    link.updated_by = actor
    link.updated_at = M.utcnow()

    db.add(M.AuditLog(actor=actor, action="sim_link.compose", entity_type="symbol",
                      entity_id=str(sym.id),
                      details={"symbol": sym.name, "model": name,
                               "blocks": [b.get("ref") for b in
                                          (composition.get("blocks") or [])],
                               "heuristic_warnings": heuristic}))
    db.commit()
    warnings = _refresh_mirror(db) if refresh else ["mirror refresh deferred by caller"]
    return {"ok": True, "symbol": sym.name, "model": name,
            "version_no": published.get("version_no"),
            "model_status": published.get("status"),
            "ports": built["ports"], "pin_map": built["pin_map"],
            "source_text": built["source_text"],
            "heuristic_warnings": heuristic, "status": "composed",
            "mirror_warnings": warnings}


def recompose_dependents(db: Session, model_name: str, actor: str = "system") -> list[dict]:
    """Rebuild every composed wrapper that uses `model_name` as a block.

    A block model's new version can add, drop or rename a port. A hand-written
    wrapper answers that by going stale and waiting for a person. A composed
    one has no reason to wait: the block design still says where each port
    belongs, so the wrapper is simply rebuilt — and when the design no longer
    fits the new interface, the rebuild FAILS and says which port lost its
    node, which is the same information a staleness warning carries and more
    of it.
    """
    out: list[dict] = []
    links = db.query(M.SymbolSimLink).filter(M.SymbolSimLink.mode == "composed").all()
    for link in links:
        comp = link.composition or {}
        if model_name not in {b.get("model") for b in (comp.get("blocks") or [])}:
            continue
        sym = db.get(M.Symbol, link.symbol_id)
        if sym is None:
            continue
        res = set_symbol_sim_composition(
            db, sym.name, comp, actor=actor,
            comment=f"Regenerated: block model {model_name} published a new version.",
            refresh=False,
        )
        out.append({"symbol": sym.name,
                    **({"error": res["error"], "problems": res.get("problems", [])}
                       if "error" in res else {"status": res["status"]})})
    return out
