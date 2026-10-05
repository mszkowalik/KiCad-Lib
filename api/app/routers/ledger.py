"""The write journal: what moved money, and how to put it back.

Thin over `services/journal.py`. This is the surface that replaces "ask Claude
to write a script" for the case where an import was applied and should not have
been — which, before it existed, meant raw SQL against a live ledger.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import access, jlc_apply, journal
from .util import acting_name, audit

router = APIRouter(prefix="/api/ledger", tags=["ledger"])


@router.get("/batches")
def list_batches(kind: str = "", limit: int = 50, include_reversed: bool = True,
                 db: Session = Depends(get_db)):
    q = db.query(M.WriteBatch)
    if kind:
        q = q.filter(M.WriteBatch.kind == kind)
    if not include_reversed:
        q = q.filter(M.WriteBatch.reversed_at.is_(None))
    mine = access.allowed_companies(db)
    if mine is None:
        rows = q.order_by(M.WriteBatch.id.desc()).limit(min(limit, 200)).all()
        return {"batches": [journal.batch_json(b) for b in rows], "total": q.count()}
    # A batch belongs to the companies of the rows it touched (decision 0065).
    rows = [b for b in q.order_by(M.WriteBatch.id.desc()).all()
            if access.write_batch_companies(db, b.id) & mine]
    return {"batches": [journal.batch_json(b) for b in rows[:min(limit, 200)]], "total": len(rows)}


@router.get("/batches/{batch_id}")
def get_batch(batch_id: int, db: Session = Depends(get_db)):
    wb = db.get(M.WriteBatch, batch_id)
    if wb is None:
        raise HTTPException(404, f"no write batch {batch_id}")
    out = journal.batch_json(wb, rows=True)
    out["check"] = journal.check_reversible(db, wb)   # once: its stock check is a trial reversal
    out["reversible"] = not out["check"]["blockers"]
    if _owned_elsewhere(db, wb):
        # Read and write agree: what `reverse_batch` refuses reads as refused.
        out["check"]["blockers"] = [*out["check"]["blockers"], _owned_elsewhere(db, wb)]
        out["reversible"] = False
    return out


def _owned_elsewhere(db, wb: M.WriteBatch) -> str | None:
    """Why another screen, not the Write log, undoes this batch."""
    fwd = wb
    while fwd is not None and fwd.kind == "reverse":   # a redo, or an undo of one
        fwd = db.get(M.WriteBatch, (fwd.summary or {}).get("reverses") or 0)
    if wb.kind == "reverse" and fwd is not None and (fwd.kind or "").startswith("craft.") \
            and fwd.kind != "craft.rebuild":
        # Redone from here, a click would skip every check its screen runs: the
        # stock, its needs, the whole-step links and the device's event order
        # as they stand now (decision 0074).
        return "a crafting click is not redone here — do it again on the batch's Process screen"
    if fwd is not None and fwd.kind == "craft.rebuild":
        # The rebuild pins the batch's process version, which is no journalled
        # row: reversed here, the batch would keep it with no twins, and every
        # device would become a gap (decision 0075).
        return "a rebuild is undone with \"Undo rebuild\" (POST /runs/{id}/rebuild/undo), not reversed here"
    if fwd is not None and fwd.kind == "transfer.create":
        # The transfer's own reversal refuses while the receiver uses what it
        # got (decision 0064); the Write log would skip that check.
        return "a transfer is reversed on its document (Transfers → Reverse), not here"
    if wb.kind == "run.company":
        # The batch's own company is not a journalled row (decision 0069), so a
        # reversal would put its stock back and leave the batch in the new
        # company. Moving it back runs the same checks the other way.
        return "a batch moved to another company is moved back on its page (Batch → Made by), not reversed here"
    return None


@router.post("/batches/{batch_id}/reverse")
def reverse_batch(batch_id: int, dry_run: bool = True, db: Session = Depends(get_db)):
    """Undo one batch. `dry_run=true` (the default) reports what it would do and
    every reason it might refuse, without touching anything. A batch that
    touched another company's rows is reversed only by a caller who sees that
    company too."""
    access.require_every(db, access.write_batch_companies(db, batch_id))
    wb = db.get(M.WriteBatch, batch_id)
    why = _owned_elsewhere(db, wb) if wb is not None else None
    if why:
        raise HTTPException(409, why)
    actor = acting_name()
    try:
        res = journal.reverse(db, batch_id, actor=actor, dry_run=dry_run)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except jlc_apply.ApplyRefused as e:
        raise HTTPException(409, str(e)) from e
    except IntegrityError as e:
        # A row the undo puts back collides with what stands now: refuse with
        # the reason, never a 500 (decision 0074).
        db.rollback()
        raise HTTPException(409, f"cannot reverse batch {batch_id}: a row it puts back collides with the "
                                 f"present data ({str(e.orig).splitlines()[0] if e.orig else e})") from e
    if res["status"] == "refused":
        # 409, not 200-with-a-flag: a refusal is the answer to the request, and a
        # UI that has to inspect a field to notice will eventually not.
        # `detail.error` is the whole message the browser shows (web/CLAUDE.md),
        # so it names the reasons itself.
        reasons = "; ".join(str(b.get("reason") or b.get("why") or b) if isinstance(b, dict) else str(b)
                            for b in (res["blockers"] or [])[:5])
        later = ", ".join(str(x) for x in (res["blocking_batches"] or [])[:5])
        raise HTTPException(409, {"error": "cannot reverse this batch"
                                           + (f": {reasons}" if reasons else "")
                                           + (f" — reverse the later batch(es) {later} first" if later else ""),
                                  "blockers": res["blockers"],
                                  "blocking_batches": res["blocking_batches"]})
    if not dry_run:
        audit(db, "ledger.batch.reverse", "write_batch", batch_id,
              details={"reverse_batch_id": res.get("reverse_batch_id"),
                       "kind": res["kind"], "source_ref": res["source_ref"]},
              actor=actor)
        db.commit()
    return res
