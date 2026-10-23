"""The material ledger's shadow and its parity checks (decision 0097, phase 1).

Admin only: the shadow is rebuilt archive-wide, like the datasheet jobs, and
a state map rewrites how every lot of a part is read. Rules in
docs/reference/material-ledger.md.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services.material_ledger import parity, project
from .users import require_admin
from .util import acting_name, audit, col_cap

router = APIRouter(prefix="/api/material-ledger", tags=["material-ledger"])

_COUNTED = (M.MaterialItem, M.MaterialStateMap, M.MaterialEvent, M.MaterialLot, M.MaterialMove,
            M.MaterialEventLot, M.MaterialLink, M.MaterialProperty, M.MaterialCostAim)


@router.get("/summary")
def summary(db: Session = Depends(get_db), _admin: M.User = Depends(require_admin)):
    """Row counts of the shadow, and the items by tracking level."""
    return {"rows": {m.__tablename__: db.query(func.count(m.id)).scalar() for m in _COUNTED},
            "tracking": dict(db.query(M.MaterialItem.tracking, func.count(M.MaterialItem.id))
                             .group_by(M.MaterialItem.tracking).all())}


@router.post("/rebuild")
def rebuild(db: Session = Depends(get_db), _admin: M.User = Depends(require_admin)):
    """Empty the shadow and project it again from today's tables."""
    out = project.rebuild(db)
    db.commit()
    return out


class ParityIn(BaseModel):
    rebuild: bool = True


@router.post("/parity")
def check(body: ParityIn | None = None, db: Session = Depends(get_db),
          _admin: M.User = Depends(require_admin)):
    """Rebuild the shadow (unless `rebuild` is false) and compare it with
    today's figures: stock, lots, clicks, batches, units, devices."""
    out = parity.check(db, rebuild=(body.rebuild if body else True))
    db.commit()
    return out


@router.get("/state-maps")
def state_maps(db: Session = Depends(get_db), _admin: M.User = Depends(require_admin)):
    names = dict(db.query(M.Component.id, M.Component.name).all())
    return [{"component_id": m.component_id, "component": names.get(m.component_id),
             "item_component_id": m.item_component_id, "item": names.get(m.item_component_id),
             "properties": m.properties or {}, "note": m.note, "decided_by": m.decided_by,
             "created_at": m.created_at} for m in db.query(M.MaterialStateMap).order_by(M.MaterialStateMap.id)]


class StateMapIn(BaseModel):
    component_id: int
    item_component_id: int
    properties: dict = Field(default_factory=dict)
    note: str = Field("", max_length=col_cap(M.MaterialStateMap, "note"))


@router.put("/state-maps")
def put_state_map(body: StateMapIn, db: Session = Depends(get_db), _admin: M.User = Depends(require_admin)):
    """State that an internal part is a state of another item. The next
    rebuild reads its transformations' output lots that way."""
    part = db.get(M.Component, body.component_id)
    item = db.get(M.Component, body.item_component_id)
    if part is None or not part.internal:
        raise HTTPException(422, "component_id must be an internal part")
    if item is None or item.internal:
        raise HTTPException(422, "item_component_id must be a part that is not internal")
    if not body.properties or not all(isinstance(k, str) and k.strip() for k in body.properties):
        raise HTTPException(422, "name at least one property, each with a name")
    who = acting_name()
    m = db.query(M.MaterialStateMap).filter_by(component_id=part.id).first()
    before = None if m is None else {"item_component_id": m.item_component_id, "properties": m.properties}
    if m is None:
        m = M.MaterialStateMap(component_id=part.id)
        db.add(m)
    m.item_component_id, m.properties, m.note, m.decided_by = item.id, body.properties, body.note, who
    db.flush()
    audit(db, "material_ledger.state_map", "component", part.id,
          details={"item_component_id": item.id, "properties": body.properties, "previous": before}, actor=who)
    db.commit()
    return {"component_id": part.id, "item_component_id": item.id, "properties": m.properties}


@router.delete("/state-maps/{comp_id}")
def delete_state_map(comp_id: int, db: Session = Depends(get_db), _admin: M.User = Depends(require_admin)):
    m = db.query(M.MaterialStateMap).filter_by(component_id=comp_id).first()
    if m is None:
        raise HTTPException(404, "no state map for that part")
    who = acting_name()
    audit(db, "material_ledger.state_map_delete", "component", comp_id,
          details={"item_component_id": m.item_component_id, "properties": m.properties}, actor=who)
    db.delete(m)
    db.commit()
    return {"deleted": comp_id}
