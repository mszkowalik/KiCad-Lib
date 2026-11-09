"""Approved alternates of a library part, and the projects that refuse one
(decision 0108). Library work: open to any signed-in user, like a supplier link."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import alternates as svc
from .util import acting_name, audit

router = APIRouter(prefix="/api", tags=["alternates"])


class AlternateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alternate_id: int
    buy: bool = False
    note: str = Field(default="", max_length=500)


class AlternatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    buy: bool | None = None
    note: str | None = Field(default=None, max_length=500)


class BlockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component_id: int
    alternate_id: int
    refs: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=500)


def _refuse(e: svc.AlternateError):
    raise HTTPException(e.status, str(e)) from e


def _row(db: Session, comp_id: int, row_id: int) -> M.ComponentAlternate:
    row = db.get(M.ComponentAlternate, row_id)
    if row is None or row.component_id != comp_id:
        raise HTTPException(404, "no such approved alternate of this part")
    return row


@router.get("/components/{comp_id}/alternates", openapi_extra={"x-agent-tool": "get_component_alternates"})
def list_alternates(comp_id: int, db: Session = Depends(get_db)):
    """The part's approved alternates, the parts it may stand in for, and the
    projects that refuse either."""
    if db.get(M.Component, comp_id) is None:
        raise HTTPException(404, "component not found")
    return svc.for_component(db, comp_id)


@router.post("/components/{comp_id}/alternates", openapi_extra={"x-agent-tool": "approve_alternate"})
def approve(comp_id: int, body: AlternateIn, db: Session = Depends(get_db)):
    """Approve `alternate_id` as a part that may replace this one, in every
    project unless a project refuses it. One direction only."""
    try:
        row = svc.add(db, comp_id, body.alternate_id, buy=body.buy, note=body.note, actor=acting_name())
    except svc.AlternateError as e:
        _refuse(e)
    audit(db, "component.alternate.add", "component", comp_id,
          {"alternate_id": body.alternate_id, "buy": body.buy, "note": body.note, "row_id": row.id})
    db.commit()
    return svc.for_component(db, comp_id)


@router.patch("/components/{comp_id}/alternates/{row_id}")
def update(comp_id: int, row_id: int, body: AlternatePatch, db: Session = Depends(get_db)):
    row = _row(db, comp_id, row_id)
    before = {"buy": row.buy, "note": row.note}
    if body.buy is not None:
        svc.set_buy(db, row, body.buy)
    if body.note is not None:
        row.note = body.note[:500]
    audit(db, "component.alternate.update", "component", comp_id,
          {"row_id": row.id, "before": before, "after": {"buy": row.buy, "note": row.note}})
    db.commit()
    return svc.for_component(db, comp_id)


@router.delete("/components/{comp_id}/alternates/{row_id}")
def remove(comp_id: int, row_id: int, db: Session = Depends(get_db)):
    """Withdraw the approval, and every project refusal of it with it."""
    row = _row(db, comp_id, row_id)
    info = {"row_id": row.id, "alternate_id": row.alternate_id, "buy": row.buy, "note": row.note}
    db.query(M.ProjectAlternateBlock).filter_by(component_id=row.component_id,
                                                alternate_id=row.alternate_id).delete()
    db.delete(row)
    audit(db, "component.alternate.remove", "component", comp_id, info)
    db.commit()
    return svc.for_component(db, comp_id)


@router.post("/projects/{project_id}/alternate-blocks")
def block(project_id: int, body: BlockIn, db: Session = Depends(get_db)):
    """The project refuses an approved alternate: everywhere, or at `refs`."""
    try:
        row = svc.add_block(db, project_id, body.component_id, body.alternate_id, refs=body.refs,
                            note=body.note, actor=acting_name())
    except svc.AlternateError as e:
        _refuse(e)
    audit(db, "project.alternate_block.add", "project", project_id,
          {"block_id": row.id, "component_id": row.component_id, "alternate_id": row.alternate_id,
           "refs": row.refs, "note": row.note})
    db.commit()
    return svc.for_component(db, body.component_id)


@router.delete("/projects/{project_id}/alternate-blocks/{block_id}")
def unblock(project_id: int, block_id: int, db: Session = Depends(get_db)):
    row = db.get(M.ProjectAlternateBlock, block_id)
    if row is None or row.project_id != project_id:
        raise HTTPException(404, "no such refusal in this project")
    comp = row.component_id
    audit(db, "project.alternate_block.remove", "project", project_id,
          {"block_id": row.id, "component_id": row.component_id, "alternate_id": row.alternate_id,
           "refs": row.refs})
    db.delete(row)
    db.commit()
    return svc.for_component(db, comp)
