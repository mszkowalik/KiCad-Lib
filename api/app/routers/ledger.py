"""The write journal: what moved money, and how to put it back.

Thin over `services/journal.py`. This is the surface that replaces "ask Claude
to write a script" for the case where an import was applied and should not have
been — which, before it existed, meant raw SQL against a live ledger.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import jlc_apply, journal
from .util import audit

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("/batches")
def list_batches(kind: str = "", limit: int = 50, include_reversed: bool = True,
                 db: Session = Depends(get_db)):
    q = db.query(M.WriteBatch)
    if kind:
        q = q.filter(M.WriteBatch.kind == kind)
    if not include_reversed:
        q = q.filter(M.WriteBatch.reversed_at.is_(None))
    rows = q.order_by(M.WriteBatch.id.desc()).limit(min(limit, 200)).all()
    return {"batches": [journal.batch_json(b) for b in rows],
            "total": q.count()}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    wb = db.get(M.WriteBatch, batch_id)
    if wb is None:
        raise HTTPException(404, f"no write batch {batch_id}")
    out = journal.batch_json(wb, db=db, rows=True)
    out["check"] = journal.check_reversible(db, wb)
    return out


@router.post("/batches/{batch_id}/reverse")
def reverse_batch(batch_id: int, dry_run: bool = True, actor: str = "user",
                  db: Session = Depends(get_db)):
    """Undo one batch. `dry_run=true` (the default) reports what it would do and
    every reason it might refuse, without touching anything."""
    try:
        res = journal.reverse(db, batch_id, actor=actor, dry_run=dry_run)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except jlc_apply.ApplyRefused as e:
        raise HTTPException(409, str(e)) from e
    if res["status"] == "refused":
        # 409, not 200-with-a-flag: a refusal is the answer to the request, and a
        # UI that has to inspect a field to notice will eventually not.
        raise HTTPException(409, {"error": "cannot reverse this batch",
                                  "blockers": res["blockers"],
                                  "blocking_batches": res["blocking_batches"]})
    if not dry_run:
        audit(db, "ledger.batch.reverse", "write_batch", batch_id,
              details={"reverse_batch_id": res.get("reverse_batch_id"),
                       "kind": res["kind"], "source_ref": res["source_ref"]},
              actor=actor)
        db.commit()
    return res
