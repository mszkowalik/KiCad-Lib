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
    warnings = _refresh_mirror(db) if refresh else ["mirror refresh deferred by caller"]
    return {"ok": True, "model": name, "version_no": new_no, "is_new_model": is_new,
            "kind": model.kind, "ports": parsed["ports"],
            "params": parsed["params"], "status": "published",
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
        db.add(M.AuditLog(actor=actor, action="sim_link.remove", entity_type="symbol",
                          entity_id=str(sym.id), details={"symbol": sym.name}))
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
