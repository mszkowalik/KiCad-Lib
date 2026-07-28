"""Row-level undo for money writes.

The audit log records that something happened. This records enough to put it
back. That distinction is the entire reason the 2026-07 JLC backfill needed
eleven one-off scripts and a run of raw `UPDATE`s: every applier in
`jlc_apply.py` is gated, idempotent and refuses correctly, and not one of them
had a way back. A mistake could only be corrected by another script.

**How it works.** A write endpoint wraps its work in `batch(...)`. Two SQLAlchemy
session listeners — inert unless a batch is open on that session — capture, for
every row the unit of work touches, the state it was in BEFORE
(`write_batch_rows.before`) and a hash of the state it ended in
(`after_hash`). `reverse()` replays that backwards.

**Why a journal and not draft rows.** The alternative considered was a `draft`
state on documents, promoted on approval. It was rejected because "live" would
then have to be filtered in nine separate replayer call sites across
`run_actuals.py` and `lots.py`; missing one produces a draft line inflating a
run's cost while both conservation identities still pass — a new instance of
precisely the failure class this design exists to remove. The journal touches no
replayer.

**Hard rule: no bulk `query(...).delete()` or `.update()` inside a batch.** They
bypass the unit of work, so the listeners never see them and the rows silently
become irreversible. Load the rows and mutate them.
"""
from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow

log = logging.getLogger("uvicorn.error")

# Tables whose rows are worth journalling: everything a money write can touch.
# Deliberately a allow-list — a batch that also happens to write an audit row or
# a cached price should not carry those into its reversal.
JOURNALLED = {
    "run_cost_documents",
    "run_cost_lines",
    "component_consumptions",
    "component_consumption_lots",
    "component_stock_adjustments",
    "jlc_order_decisions",
    "jlc_imports",
    "run_attachments",
}


def _jsonable(v, col=None):
    """JSON-safe, and NORMALISED TO THE COLUMN'S TYPE.

    The normalisation is not cosmetic. `after_hash` is computed from the
    in-memory object just after the flush, and re-computed later from a row read
    back out of Postgres; the two must agree or every reversal is refused as
    "edited since". They do not agree by default: a caller who passes `qty=50`
    leaves a Python `int` on the attribute, which serialises as `50`, while the
    same column read back from a `double precision` gives `50.0`. Verified
    2026-07-28 — this made every `run_cost_lines` insert un-reversible while
    documents, whose amounts happened to be written as floats, reversed fine.
    """
    if v is None:
        return None
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    if col is not None and not isinstance(v, bool):
        if isinstance(col.type, sa.Float):
            return float(v)
        if isinstance(col.type, sa.Integer):
            return int(v)
    return v


def _row_dict(obj) -> dict:
    """Every mapped column of `obj`, JSON-safe. Relationships are excluded — a
    reversal restores columns, and the relationships follow from the FKs."""
    out = {}
    for c in inspect(obj).mapper.column_attrs:
        out[c.key] = _jsonable(getattr(obj, c.key), c.columns[0])
    return out


def _hash(d: dict) -> str:
    return hashlib.sha256(
        json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()


def _table(obj) -> str:
    return obj.__table__.name


# --------------------------------------------------------------- listeners
# Registered once, on the Session class. They cost one `db.info` lookup per
# flush when no batch is open, which is every request that is not a money write.

@event.listens_for(Session, "before_flush")
def _capture_before(session: Session, flush_context, instances) -> None:
    buf = session.info.get("wb_rows")
    if buf is None:
        return
    for obj in session.deleted:
        if _table(obj) not in JOURNALLED:
            continue
        pk = getattr(obj, "id", None)
        if pk is None:
            continue
        buf.setdefault(("delete", _table(obj), pk), {
            "op": "delete", "table_name": _table(obj), "row_id": pk,
            "before": _row_dict(obj), "obj": None,
        })
    for obj in session.dirty:
        if _table(obj) not in JOURNALLED or not session.is_modified(obj):
            continue
        pk = getattr(obj, "id", None)
        if pk is None:
            continue
        key = ("update", _table(obj), pk)
        if key in buf or ("insert", _table(obj), pk) in buf:
            # Already captured: keep the EARLIEST `before` in this batch, and
            # let the exit-time re-hash pick up the final state. A row updated
            # twice must reverse to how it looked when the batch started, not to
            # its intermediate value.
            continue
        state = inspect(obj)
        before = {}
        for c in state.mapper.column_attrs:
            hist = state.attrs[c.key].history
            before[c.key] = _jsonable(
                hist.deleted[0] if hist.deleted else getattr(obj, c.key), c.columns[0])
        buf[key] = {"op": "update", "table_name": _table(obj), "row_id": pk,
                    "before": before, "obj": obj}


@event.listens_for(Session, "after_flush")
def _capture_after(session: Session, flush_context) -> None:
    buf = session.info.get("wb_rows")
    if buf is None:
        return
    for obj in session.new:
        if _table(obj) not in JOURNALLED:
            continue
        pk = getattr(obj, "id", None)
        if pk is None:  # no surrogate id — nothing to reverse against
            continue
        buf.setdefault(("insert", _table(obj), pk), {
            "op": "insert", "table_name": _table(obj), "row_id": pk,
            "before": None, "obj": obj,
        })


# ------------------------------------------------------------------- batch
@contextmanager
def batch(db: Session, kind: str, source_ref: str = "", actor: str = "",
          summary: dict | None = None, identity_before: dict | None = None):
    """Wrap one endpoint's writes in a reversible batch.

    Writes NOTHING on an exception — including `jlc_apply`'s own
    `ApplyRefused` after it has rolled back — so a refused apply leaves no trace
    at all, and no empty batch for an operator to wonder about. Writes nothing
    when the body touched no journalled row either: an import that turned out to
    be a no-op ("already imported as document 41") is not an event.

    `identity_before` may be passed in when the caller already took a snapshot,
    to avoid computing the register twice.
    """
    if db.info.get("wb_rows") is not None:
        raise RuntimeError("a write batch is already open on this session")
    from . import jlc_apply  # local import: jlc_apply imports run_actuals, not this

    db.info["wb_rows"] = {}
    holder: dict = {"batch_id": None}
    before = identity_before if identity_before is not None else jlc_apply.identity_snapshot(db)
    try:
        yield holder
        db.flush()
    except Exception:
        db.info.pop("wb_rows", None)
        raise

    buf = db.info.pop("wb_rows", {})
    if not buf:
        return

    wb = M.WriteBatch(
        kind=kind, source_ref=source_ref[:200], actor=actor[:100],
        summary=summary or {}, identity_before=before,
        identity_after=jlc_apply.identity_snapshot(db))
    db.add(wb)
    db.flush()
    holder["batch_id"] = wb.id

    for rec in buf.values():
        obj = rec.pop("obj", None)
        # Re-hash at exit rather than at flush time: a row inserted and then
        # updated inside one batch must record the state it actually ended in.
        after_hash = None
        if rec["op"] in ("insert", "update") and obj is not None:
            try:
                after_hash = _hash(_row_dict(obj))
            except Exception as e:  # noqa: BLE001 — a missing hash blocks reversal, safely
                log.warning(f"could not hash {rec['table_name']}#{rec['row_id']}: {e}")
        db.add(M.WriteBatchRow(batch_id=wb.id, after_hash=after_hash, **rec))
    db.flush()


# ----------------------------------------------------------------- reading
def _model_for(table_name: str):
    for mapper in M.Base.registry.mappers:
        if mapper.class_.__table__.name == table_name:
            return mapper.class_
    return None


def batch_json(wb: M.WriteBatch, db: Session | None = None, rows: bool = False) -> dict:
    out = {
        "id": wb.id, "kind": wb.kind, "source_ref": wb.source_ref,
        "actor": wb.actor, "summary": wb.summary or {},
        "identity_before": wb.identity_before, "identity_after": wb.identity_after,
        "created_at": wb.created_at.isoformat() if wb.created_at else None,
        "reversed_at": wb.reversed_at.isoformat() if wb.reversed_at else None,
        "reversed_by_batch_id": wb.reversed_by_batch_id,
        "row_count": len(wb.rows),
        "by_op": {},
    }
    for r in wb.rows:
        out["by_op"][r.op] = out["by_op"].get(r.op, 0) + 1
    if rows:
        out["rows"] = [
            {"id": r.id, "table": r.table_name, "row_id": r.row_id, "op": r.op,
             "before": r.before, "after_hash": r.after_hash}
            for r in sorted(wb.rows, key=lambda x: x.id)
        ]
    if db is not None:
        out["reversible"] = not check_reversible(db, wb)["blockers"]
    return out


def check_reversible(db: Session, wb: M.WriteBatch) -> dict:
    """Everything standing between this batch and a clean undo, named.

    Three gates, and each refusal is specific enough to act on. The hash gate is
    the important one: silently discarding a later hand correction in order to
    satisfy an undo is exactly how the `C2837531` substitution link was
    destroyed twice during the backfill.
    """
    blockers: list[str] = []
    if wb.reversed_at is not None:
        # Return here rather than collecting the rest. Once a batch is reversed,
        # the rows it inserted are gone and its reversal batch references them —
        # so the hash and dependency gates both fire as a matter of course. Three
        # blockers where one is true reads like three problems.
        return {"blockers": [f"already reversed at {wb.reversed_at.isoformat()}"
                             f" by batch {wb.reversed_by_batch_id}"],
                "edited": [], "missing": [], "blocking_batches": []}

    edited: list[str] = []
    missing: list[str] = []
    for r in wb.rows:
        if r.op == "delete" or r.after_hash is None:
            continue
        model = _model_for(r.table_name)
        if model is None:
            continue
        obj = db.get(model, r.row_id)
        if obj is None:
            missing.append(f"{r.table_name}#{r.row_id}")
            continue
        if _hash(_row_dict(obj)) != r.after_hash:
            edited.append(f"{r.table_name}#{r.row_id}")
    if edited:
        blockers.append(
            f"{len(edited)} row(s) were edited after this batch: {edited[:8]}"
            " — reversing would silently discard that later work")
    if missing:
        blockers.append(
            f"{len(missing)} row(s) this batch wrote no longer exist: {missing[:8]}"
            " — something removed them outside the journal")

    # A row this batch INSERTED that a LATER batch then touched: undoing this one
    # would pull the ground out from under that one. Name the batch to reverse first.
    inserted = [(r.table_name, r.row_id) for r in wb.rows if r.op == "insert"]
    later: set[int] = set()
    if inserted:
        for tbl, rid in inserted:
            for other in (db.query(M.WriteBatchRow)
                          .filter(M.WriteBatchRow.table_name == tbl,
                                  M.WriteBatchRow.row_id == rid,
                                  M.WriteBatchRow.batch_id != wb.id).all()):
                if other.batch_id > wb.id:
                    ob = db.get(M.WriteBatch, other.batch_id)
                    if ob is not None and ob.reversed_at is None:
                        later.add(other.batch_id)
    if later:
        blockers.append(
            f"later batch(es) {sorted(later)} depend on rows this one created"
            f" — reverse {max(later)} first")
    return {"blockers": blockers, "edited": edited, "missing": missing,
            "blocking_batches": sorted(later)}


# --------------------------------------------------------------- reversing
def reverse(db: Session, batch_id: int, actor: str = "user",
            dry_run: bool = True) -> dict:
    """Put a batch back, or say precisely why it cannot be.

    The identity re-assertion at the end compares against THIS batch's
    `identity_before` rather than absolutely, which is the one place a reversal
    must differ from an apply. `jlc_apply._assert_identities` checks absolutely
    and deliberately (right for a forward write, since importing on top of a
    pre-existing gap hides its cause) — but applied to an undo it would make
    every batch permanently irreversible for as long as any gap exists, which
    today is always: the register carries a standing $0.0272.
    """
    from . import jlc_apply

    wb = db.get(M.WriteBatch, batch_id)
    if wb is None:
        raise LookupError(f"no write batch {batch_id}")

    state = check_reversible(db, wb)
    plan = {"batch_id": batch_id, "kind": wb.kind, "source_ref": wb.source_ref,
            "blockers": state["blockers"], "blocking_batches": state["blocking_batches"],
            "would": {"delete": 0, "restore": 0, "reinsert": 0}}
    for r in wb.rows:
        plan["would"]["delete" if r.op == "insert" else
                      "restore" if r.op == "update" else "reinsert"] += 1
    if state["blockers"]:
        plan["status"] = "refused"
        return plan
    if dry_run:
        plan["status"] = "would_reverse"
        plan["identity_target"] = wb.identity_before
        return plan

    before_now = jlc_apply.identity_snapshot(db)
    with batch(db, kind="reverse", source_ref=f"batch:{batch_id}", actor=actor,
               summary={"reverses": batch_id, "of_kind": wb.kind,
                        "source_ref": wb.source_ref},
               identity_before=before_now) as holder:
        # Newest row first. Inserts happen parents-then-children, so undoing in
        # reverse id order deletes children before the parents they point at.
        for r in sorted(wb.rows, key=lambda x: x.id, reverse=True):
            model = _model_for(r.table_name)
            if model is None:
                continue
            if r.op == "insert":
                obj = db.get(model, r.row_id)
                if obj is not None:
                    db.delete(obj)
            elif r.op == "update":
                obj = db.get(model, r.row_id)
                if obj is None:
                    continue
                for k, v in (r.before or {}).items():
                    if k == "id":
                        continue
                    setattr(obj, k, _coerce(model, k, v))
            elif r.op == "delete":
                data = {k: _coerce(model, k, v) for k, v in (r.before or {}).items()}
                db.add(model(**data))
        db.flush()

        after = jlc_apply.identity_snapshot(db)
        target = wb.identity_before or {}
        drift = []
        for key in ("gap_usd", "to_runs_usd", "to_pool_usd", "pool_purchased_usd",
                    "pool_drawn_usd"):
            if key in target and abs((after.get(key) or 0) - (target[key] or 0)) > 0.01:
                drift.append(f"{key}: {after.get(key)} != {target[key]} (target)")
        if not after["pool_balanced"]:
            drift.append("pool does not balance after the reversal")
        if drift:
            db.rollback()
            raise jlc_apply.ApplyRefused(
                f"reversing batch {batch_id} did not restore the register and was "
                "rolled back: " + "; ".join(drift))

        wb.reversed_at = utcnow()
    wb.reversed_by_batch_id = holder["batch_id"]
    plan["status"] = "reversed"
    plan["reverse_batch_id"] = holder["batch_id"]
    plan["identity_after"] = jlc_apply.identity_snapshot(db)
    return plan


def _coerce(model, column: str, value):
    """Turn a JSON scalar back into what the column expects. Only datetimes need
    it — everything else round-trips, and a date column is `String(20)` here."""
    if value is None:
        return None
    col = model.__table__.columns.get(column)
    if col is None:
        return value
    if str(col.type).startswith(("TIMESTAMP", "DATETIME")) and isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value
