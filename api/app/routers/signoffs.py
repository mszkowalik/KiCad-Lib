"""Production sign-off endpoints.

The record's meaning and the carry rule live in `services/signoff.py` and
`models.ComponentSignoff`. This router is thin: resolve the component, name the
actor, call the service, audit, commit.

Two things it deliberately does NOT do. It never blocks anything — no export
refuses and no run is gated on sign-off state (user decision, 2026-08-17). And
it never signs on behalf of a robot: `actor_of(request)` is the signed-in
person, because a production check that nobody's name is on is not a check.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..db import get_db
from ..services import signoff
from .util import actor_of, audit

router = APIRouter(prefix="/api", tags=["signoffs"])

STATES = ("signed", "stale", "unsigned", "revoked")


class SignIn(BaseModel):
    note: str | None = None


class RevokeIn(BaseModel):
    reason: str


class BulkIn(BaseModel):
    component_ids: list[int]
    note: str | None = None


def _component(db: Session, comp_id: int) -> M.Component:
    comp = (
        db.query(M.Component)
        .options(selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties))
        .filter(M.Component.id == comp_id)
        .first()
    )
    if comp is None:
        raise HTTPException(404, "component not found")
    return comp


def _geometry_label(db: Session, cv: M.ComponentVersion | None) -> dict:
    """The drawings a component version pins, named for a human."""
    if cv is None:
        return {"symbol": None, "footprint": None}
    sv = db.get(M.SymbolVersion, cv.symbol_version_id) if cv.symbol_version_id else None
    fv = db.get(M.FootprintVersion, cv.footprint_version_id) if cv.footprint_version_id else None
    sym = db.get(M.Symbol, sv.symbol_id) if sv else None
    fp = db.get(M.Footprint, fv.footprint_id) if fv else None
    return {
        "symbol": {"name": sym.name, "version_no": sv.version_no} if sv and sym else None,
        "footprint": {"name": fp.name, "version_no": fv.version_no} if fv and fp else None,
    }


def _detail(db: Session, comp: M.Component) -> dict:
    rows = (
        db.query(M.ComponentSignoff)
        .filter(M.ComponentSignoff.component_id == comp.id)
        .order_by(M.ComponentSignoff.id)
        .all()
    )
    state = signoff.state_for(db, comp, rows)
    cur = db.get(M.ComponentVersion, comp.current_version_id) if comp.current_version_id else None
    signed_cv = None
    if state["signoff"]:
        signed_cv = db.get(M.ComponentVersion, state["signoff"]["component_version_id"])
    return {
        "component_id": comp.id,
        "component_name": comp.name,
        "current_version_no": cur.version_no if cur else None,
        "current": _geometry_label(db, cur),
        "signed": _geometry_label(db, signed_cv),
        **state,
        # AFTER the spread on purpose. `state_for` only fills
        # `signed_version_no` on the `stale` path, where it is the whole point
        # of the message; on every other path it is None and would blank the
        # number resolved here — a revoked card printed "version checked: v?".
        "signed_version_no": signed_cv.version_no if signed_cv else None,
        "history": [signoff.signoff_json(r) for r in reversed(rows)],
    }


@router.get("/components/{comp_id}/signoff")
def get_signoff(comp_id: int, db: Session = Depends(get_db)):
    return _detail(db, _component(db, comp_id))


@router.post("/components/{comp_id}/signoff")
def add_signoff(comp_id: int, body: SignIn, request: Request, db: Session = Depends(get_db)):
    comp = _component(db, comp_id)
    if comp.current_version_id is None:
        raise HTTPException(409, "this component has no published version to sign off")
    rows = (
        db.query(M.ComponentSignoff)
        .filter(M.ComponentSignoff.component_id == comp.id)
        .order_by(M.ComponentSignoff.id)
        .all()
    )
    if signoff.live_signoff(rows, comp.current_version_id) is not None:
        raise HTTPException(409, "this version is already signed off")

    actor = actor_of(request)
    row = signoff.sign(db, comp, actor, body.note)
    audit(db, "signoff.sign", "component_version", comp.current_version_id,
          {"component": comp.name, "note": row.note}, actor=actor)
    db.commit()
    return _detail(db, comp)


@router.post("/components/{comp_id}/signoff/revoke")
def revoke_signoff(comp_id: int, body: RevokeIn, request: Request, db: Session = Depends(get_db)):
    comp = _component(db, comp_id)
    reason = (body.reason or "").strip()
    if not reason:
        # Revoking is how a production defect gets recorded against a part. An
        # unexplained revoke would be worse than none — the next person would
        # have no idea what to look for.
        raise HTTPException(422, "say why the sign-off is being taken back")
    rows = (
        db.query(M.ComponentSignoff)
        .filter(M.ComponentSignoff.component_id == comp.id)
        .order_by(M.ComponentSignoff.id)
        .all()
    )
    live = signoff.live_signoff(rows, comp.current_version_id)
    if live is None:
        raise HTTPException(404, "this version has no live sign-off to revoke")

    actor = actor_of(request)
    signoff.revoke(db, live, actor, reason)
    audit(db, "signoff.revoke", "component_version", live.component_version_id,
          {"component": comp.name, "reason": reason, "signoff_id": live.id}, actor=actor)
    db.commit()
    return _detail(db, comp)


@router.post("/signoffs/bulk")
def bulk_signoff(body: BulkIn, request: Request, db: Session = Depends(get_db)):
    """Sign off many components in one action.

    Reports an outcome per id instead of failing the batch: signing off 47
    parts of a BOM and being refused because one of them was already signed
    would be useless. `skipped` is the normal, boring result for anything
    already current.
    """
    actor = actor_of(request)
    signed: list[str] = []
    skipped: list[dict] = []
    comps = (
        db.query(M.Component)
        .filter(M.Component.id.in_(body.component_ids))
        .all()
        if body.component_ids else []
    )
    found = {c.id for c in comps}
    for missing in sorted(set(body.component_ids) - found):
        skipped.append({"component_id": missing, "reason": "no such component"})

    for comp in comps:
        if comp.current_version_id is None:
            skipped.append({"component_id": comp.id, "component": comp.name,
                            "reason": "no published version"})
            continue
        rows = (
            db.query(M.ComponentSignoff)
            .filter(M.ComponentSignoff.component_id == comp.id)
            .order_by(M.ComponentSignoff.id)
            .all()
        )
        if signoff.live_signoff(rows, comp.current_version_id) is not None:
            skipped.append({"component_id": comp.id, "component": comp.name,
                            "reason": "already signed off"})
            continue
        signoff.sign(db, comp, actor, body.note)
        audit(db, "signoff.sign", "component_version", comp.current_version_id,
              {"component": comp.name, "note": body.note, "bulk": True}, actor=actor)
        signed.append(comp.name)
    db.commit()
    return {"signed": signed, "skipped": skipped, "total": len(signed)}


@router.get("/signoffs")
def list_signoffs(state: str | None = Query(None), db: Session = Depends(get_db)):
    """Every component's sign-off state, optionally filtered to one state."""
    if state is not None and state not in STATES:
        raise HTTPException(422, f"state must be one of {', '.join(STATES)}")
    comps = db.query(M.Component).options(
        selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties)
    ).all()
    states = signoff.states_for(db, comps)
    items = [
        {"component_id": c.id, "component_name": c.name, **states[c.id]}
        for c in comps
        if state is None or states[c.id]["state"] == state
    ]
    counts = {s: sum(1 for v in states.values() if v["state"] == s) for s in STATES}
    return {"counts": counts, "total": len(items), "items": items}
