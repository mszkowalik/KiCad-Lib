"""In-house stock transfers between our two companies (decision 0064).

Writing or reversing one transfer is production work and open to any
signed-in user, like every other stock write. Writing the HISTORY's transfers
in one go is admin work: it is a one-off migration of the books.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import companies as company_svc
from ..services import journal
from ..services import transfers as svc
from .users import require_admin
from .util import acting_name, audit

router = APIRouter(prefix="/api", tags=["transfers"])


class TransferLineIn(BaseModel):
    component_id: int | None = None
    mpn: str = ""
    lcsc: str = ""
    qty: float
    # Default: the lot's landed cost when a lot is named, else the sender's
    # moving average on the date.
    unit_cost_usd: float | None = None
    lot_line_id: int | None = None
    lot_adjustment_id: int | None = None
    label: str = ""


class TransferIn(BaseModel):
    sender_id: int
    receiver_id: int
    date: str = ""
    lines: list[TransferLineIn]
    run_id: int | None = None   # the receiving batch, for context
    note: str = Field(default="", max_length=1000)
    dry_run: bool = True


class ReverseIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    dry_run: bool = True


@router.get("/transfers")
def list_transfers(request: Request = None, db: Session = Depends(get_db)):
    """Transfers that touch a company in the header scope."""
    return svc.list_transfers(db, company_svc.scope_ids(db, request))


@router.post("/transfers")
def create_transfer(body: TransferIn, db: Session = Depends(get_db)):
    lines = [ln.model_dump() for ln in body.lines]
    if body.dry_run:
        return svc.create(db, sender_id=body.sender_id, receiver_id=body.receiver_id,
                          day=body.date, lines=lines, run_id=body.run_id, dry_run=True)
    actor = acting_name()
    with journal.batch(db, kind="transfer.create", source_ref="", actor=actor) as h:
        res = svc.create(db, sender_id=body.sender_id, receiver_id=body.receiver_id,
                         day=body.date, lines=lines, run_id=body.run_id, note=body.note,
                         actor=actor, dry_run=False)
    audit(db, "transfer.create", "run_cost_document", res["document_id"],
          {"doc_number": res["doc_number"], "sender": res["sender"], "receiver": res["receiver"],
           "value_usd": res["value_usd"], "lines": len(res["lines"]), "batch_id": h["batch_id"]})
    db.commit()
    return {**res, "batch_id": h["batch_id"]}


@router.post("/transfers/{doc_id}/reverse")
def reverse_transfer(doc_id: int, body: ReverseIn, db: Session = Depends(get_db)):
    doc = db.get(M.RunCostDocument, doc_id)
    if doc is None:
        raise HTTPException(404, "transfer not found")
    if body.dry_run:
        return svc.reverse(db, doc, reason=body.reason, dry_run=True)
    actor = acting_name()
    with journal.batch(db, kind="transfer.reverse", source_ref=doc.doc_number or "", actor=actor) as h:
        res = svc.reverse(db, doc, reason=body.reason, actor=actor, dry_run=False)
    audit(db, "transfer.reverse", "run_cost_document", doc.id,
          {"doc_number": doc.doc_number, "reason": body.reason, "batch_id": h["batch_id"]})
    db.commit()
    return {**res, "batch_id": h["batch_id"]}


@router.get("/transfers/history")
def history_plan(db: Session = Depends(get_db)):
    """The transfers the past needs so each company holds what its batches
    drew. Read only."""
    return svc.plan_history(db)


class HistoryIn(BaseModel):
    dry_run: bool = True


@router.post("/transfers/history")
def history_apply(body: HistoryIn, db: Session = Depends(get_db),
                  admin: M.User = Depends(require_admin)):
    if body.dry_run:
        return svc.apply_history(db, dry_run=True)
    actor = acting_name()
    with journal.batch(db, kind="transfer.history", source_ref="", actor=actor) as h:
        res = svc.apply_history(db, actor=actor, dry_run=False)
    audit(db, "transfer.history", "run_cost_document", None,
          {"written": len(res["written"]), "refused": len(res["refused"]),
           "batch_id": h["batch_id"]})
    db.commit()
    return {**res, "batch_id": h["batch_id"]}
