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
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from . import tracking

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
    "run_substitutions",
    "process_transformations",
    "cost_line_steps",
    "cost_line_step_keys",
    # "Record assembly" is one reversible write (decision 0072): its click,
    # the twins it joins and their stack tokens.
    "step_runs",
    "twin_steps",
    "twins",
    # A scrap on the batch screen disposes of the named units with their twins
    # (decision 0074), so undoing it must give both back.
    "device_units",
    "device_events",
    # "Relink run" moves a bench run to another device (decision 0074).
    "programming_runs",
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


#: Columns added to a journalled table after rows of it were journalled, with
#: the value an older row reads back. **A new column on a journalled table goes
#: here**, or every batch written before the migration reads as "edited since"
#: and can never be undone: its `after_hash` was taken without the column.
LATE_COLUMNS: dict[str, dict[str, object]] = {
    # decisions 0058-0068: production journalled these tables before them
    "run_cost_documents": {"company_id": None, "company_source": "", "counterparty_company_id": None,
                           "seller_tax_id": ""},
    "run_cost_lines": {"transformation_id": None, "overhead_category": ""},
    "component_consumptions": {"transformation_id": None, "step_run_id": None, "company_id": None,
                               "transfer_line_id": None},
    "component_stock_adjustments": {"transformation_id": None, "company_id": None},
    "step_runs": {"assembler": "", "reference": ""},            # decision 0072
    "run_substitutions": {"step_run_id": None},                 # decision 0072
    "twin_steps": {"programming_run_id": None, "deployment_version_id": None},   # decision 0074
}


#: A journalled table other writers keep moving: only these columns are
#: guarded and put back. The bench writes a device's `last_seen`,
#: `last_status`, `chip`, its topic and modem data on every read; a scrap
#: writes only its state, batch and condition, so an undo of a scrap guards
#: and restores those alone (decision 0074).
HASH_ONLY: dict[str, set[str]] = {"device_units": {"id", "state", "production_run_id", "condition"}}


def _hash_row(table: str, d: dict) -> str:
    only = HASH_ONLY.get(table)
    return _hash({k: v for k, v in d.items() if k in only} if only else d)


def _unchanged(table: str, d: dict, after_hash: str) -> bool:
    """Does the row read back as the batch left it? Compared with and without
    the late columns that still hold their default."""
    only = HASH_ONLY.get(table)
    if only:
        d = {k: v for k, v in d.items() if k in only}
    if _hash(d) == after_hash:
        return True
    late = LATE_COLUMNS.get(table) or {}
    trimmed = {k: v for k, v in d.items() if not (k in late and v == late[k])}
    return len(trimmed) < len(d) and _hash(trimmed) == after_hash


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
        if buf.pop(("insert", _table(obj), pk), None) is not None:
            # Written and removed inside this batch: it never existed outside
            # it, so there is nothing to put back and nothing to check.
            buf.pop(("update", _table(obj), pk), None)
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

    **`actor` is only a fallback.** Inside a request the batch records the
    signed-in person, their `user_id` and the `request_id` (decision 0050). The
    argument is used only where nobody is signed in — dev, or a script.
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

    ctx = tracking.current()
    wb = M.WriteBatch(
        kind=kind, source_ref=source_ref[:200],
        actor=(ctx.name if ctx is not None and ctx.name else actor or "user")[:100],
        user_id=ctx.user_id if ctx is not None else None,
        request_id=ctx.request_id if ctx is not None else None,
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
                after_hash = _hash_row(rec["table_name"], _row_dict(obj))
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
        "actor": wb.actor, "user_id": wb.user_id, "request_id": wb.request_id,
        "summary": wb.summary or {},
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


def check_reversible(db: Session, wb: M.WriteBatch, *, stock: bool = True,
                     leaving_twins: frozenset = frozenset()) -> dict:
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
        if not _unchanged(r.table_name, _row_dict(obj), r.after_hash):
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
    # A click this batch inserted that rows OUTSIDE it still point at (soft
    # pointers the rows-of-this-batch gate cannot see: a later "Add to
    # assembly" links draws and positions to the same click). Undoing it would
    # leave them pointing at nothing (decision 0072).
    # A twin this batch inserted is the same: a bench step links it outside
    # the journal (decision 0074).
    own = {(r.table_name, r.row_id) for r in wb.rows}
    pointers = {
        "step_runs": ((M.ComponentConsumption, "component_consumptions", M.ComponentConsumption.step_run_id),
                      (M.RunSubstitution, "run_substitutions", M.RunSubstitution.step_run_id),
                      (M.CostLineStep, "cost_line_steps", M.CostLineStep.step_run_id),
                      (M.TwinStep, "twin_steps", M.TwinStep.step_run_id)),
        "twins": ((M.TwinStep, "twin_steps", M.TwinStep.twin_id),),
    }
    stray = 0
    for tbl, sid in inserted:
        for model, table, col in pointers.get(tbl, ()):
            for (oid,) in db.query(model.id).filter(col == sid).all():
                if (table, oid) in own:
                    continue
                writers = [b for (b,) in db.query(M.WriteBatchRow.batch_id)
                           .filter(M.WriteBatchRow.table_name == table, M.WriteBatchRow.row_id == oid,
                                   M.WriteBatchRow.batch_id > wb.id).all()]
                live = [b for b in writers if (db.get(M.WriteBatch, b) or wb).reversed_at is None]
                if live:
                    later.update(live)
                elif table != "cost_line_steps":
                    # A link no journal wrote (a split's copy, a bench click's
                    # whole-step link) goes with its click: the database
                    # deletes it on cascade, so it is in nobody's way.
                    stray += 1
    if stray:
        blockers.append(f"{stray} row(s) outside the journal point at a step or twin this batch recorded"
                        " — take them off it first")
    # A whole-step link this batch made has since linked bench clicks of its
    # own (decision 0074); an undo would leave those behind.
    grown = 0
    for tbl, kid in inserted:
        if tbl != "cost_line_step_keys":
            continue
        k = db.get(M.CostLineStepKey, kid)
        if k is None:
            continue
        for (cid,) in (db.query(M.CostLineStep.id).join(M.StepRun, M.StepRun.id == M.CostLineStep.step_run_id)
                       .filter(M.CostLineStep.line_id == k.line_id, M.StepRun.run_id == k.run_id,
                               M.StepRun.step_key == k.step_key,
                               M.CostLineStep.created_at > wb.created_at).all()):
            if ("cost_line_steps", cid) not in own:
                grown += 1
    # A position split after the link copied the key to its children, outside
    # the journal: an undo would take it off the header alone (decision 0074).
    for tbl, kid in inserted:
        k = db.get(M.CostLineStepKey, kid) if tbl == "cost_line_step_keys" else None
        if k is None:
            continue
        frontier, seen_lines = [k.line_id], {k.line_id}
        while frontier:
            kids = [i for (i,) in db.query(M.RunCostLine.id).filter(M.RunCostLine.parent_line_id.in_(frontier),
                                                                    M.RunCostLine.voided_at.is_(None)).all()
                    if i not in seen_lines]
            seen_lines.update(kids)
            frontier = kids
        theirs = [kid2 for (kid2,) in db.query(M.CostLineStepKey.id).filter(
            M.CostLineStepKey.line_id.in_(seen_lines - {k.line_id}), M.CostLineStepKey.run_id == k.run_id,
            M.CostLineStepKey.step_key == k.step_key).all() if ("cost_line_step_keys", kid2) not in own]
        if theirs:
            blockers.append("the position was split since — unlink it with \"Unlink…\" under Cost by step on "
                            "the batch screen instead")
    if grown:
        blockers.append(f"the step link this batch made has linked {grown} later click(s) since"
                        " — unlink it with \"Unlink…\" under Cost by step on the batch screen instead")
    # What this batch DELETED is put back: a unique row made since in its place
    # would collide, and a whole-step link put back would skip the clicks of
    # its step recorded while it was gone (decision 0074).
    restores = {((r.before or {}).get("line_id"), (r.before or {}).get("step_run_id"))
                for r in wb.rows if r.table_name == "cost_line_steps" and r.op == "delete"}
    comes_back = {(r.table_name, r.row_id) for r in wb.rows if r.op == "delete"}
    for r in wb.rows:
        if r.op != "delete" or not r.before:
            continue
        b = r.before
        # A row put back must point at what still exists (decision 0074).
        for col, model in (("step_run_id", M.StepRun), ("twin_id", M.Twin), ("line_id", M.RunCostLine),
                           ("consumption_id", M.ComponentConsumption)):
            if col in b and b[col] is not None and r.table_name in (
                    "cost_line_steps", "cost_line_step_keys", "twin_steps", "component_consumptions",
                    "run_substitutions", "component_consumption_lots") and db.get(model, b[col]) is None \
                    and (model.__tablename__, b[col]) not in comes_back:
                blockers.append(f"{r.table_name}#{r.row_id} pointed at {model.__tablename__}#{b[col]}, "
                                "which no longer exists")
        if r.table_name == "cost_line_steps":
            twin = (db.query(M.CostLineStep.id).filter_by(line_id=b.get("line_id"),
                                                          step_run_id=b.get("step_run_id")).first())
        elif r.table_name == "cost_line_step_keys":
            twin = (db.query(M.CostLineStepKey.id).filter_by(line_id=b.get("line_id"), run_id=b.get("run_id"),
                                                             step_key=b.get("step_key")).first())
            gap = sum(1 for (sid,) in db.query(M.StepRun.id)
                      .filter(M.StepRun.run_id == b.get("run_id"), M.StepRun.step_key == b.get("step_key"),
                              M.StepRun.qty > 0, M.StepRun.kind != "scrap", M.StepRun.chosen != "found",
                              M.StepRun.created_at > wb.created_at,
                              ~M.StepRun.id.in_(db.query(M.CostLineStep.step_run_id)
                                                .filter(M.CostLineStep.line_id == b.get("line_id")))).all()
                      if (b.get("line_id"), sid) not in restores)
            if gap and twin is None:
                blockers.append(f"{gap} click(s) of step {b.get('step_key')!r} were recorded while the position "
                                "was unlinked — link it to the whole step again instead")
        else:
            continue
        if twin is not None:
            writers = [x for (x,) in db.query(M.WriteBatchRow.batch_id)
                       .filter(M.WriteBatchRow.table_name == r.table_name, M.WriteBatchRow.row_id == twin[0],
                               M.WriteBatchRow.op == "insert", M.WriteBatchRow.batch_id > wb.id).all()]
            if writers:
                later.update(writers)
            else:
                blockers.append(f"{r.table_name}#{twin[0]} now stands where this batch removed a link"
                                " — take it away first")
    # An undo of a finish must not make a unit that has left us unfinished:
    # nothing could finish it again (decision 0074).
    for r in wb.rows:
        if r.table_name != "twins" or r.op != "update" or (r.before or {}).get("status") == "finished":
            continue
        tw = db.get(M.Twin, r.row_id)
        if tw is None or tw.status != "finished" or not tw.device_unit_id or tw.id in leaving_twins:
            continue   # a twin the same undo deletes ("Undo rebuild") is no unit made unfinished
        dev = db.get(M.DeviceUnit, tw.device_unit_id)
        if dev is not None and dev.state not in ("in_stock", "returned"):
            blockers.append(f"{dev.serial or dev.mac} is {dev.state or 'unrecorded'} — a unit that left us "
                            "stays finished")
    # A later batch that was itself undone, and the batch that undid it, cancel
    # out: neither is in the way any more. Only an UNDO cancels: a chain of
    # reverses ending at a forward batch after this one, an odd number of hops
    # long. A redo (an even number) puts the rows back, and they stand.
    for b in sorted(later):
        cur, hops = db.get(M.WriteBatch, b), 0
        while cur is not None and cur.kind == "reverse":
            t = (cur.summary or {}).get("reverses")
            cur, hops = (db.get(M.WriteBatch, t) if t else None), hops + 1
        if cur is not None and hops % 2 == 1 and cur.id > wb.id:
            later.discard(b)
    if later:
        blockers.append(
            f"later batch(es) {sorted(later)} depend on rows this one created"
            f" — reverse {max(later)} first")
    # A step recorded on a batch whose books are closed carries frozen twin
    # prices (decision 0044): it is undone only after the batch is reopened.
    # A redo of a crafting click is a crafting write too.
    fwd = wb
    while fwd is not None and fwd.kind == "reverse":
        t = (fwd.summary or {}).get("reverses")
        fwd = db.get(M.WriteBatch, t) if t else None
    kind, ref = (fwd.kind or "", fwd.source_ref or "") if fwd is not None else ("", "")
    if kind.startswith("craft.") and ref.startswith("run:"):
        run = db.get(M.ProductionRun, int(ref.split(":", 1)[1] or 0))
        if run is not None and run.closed_at is not None:
            blockers.append(f"batch {run.label} is closed — its twins' shares are frozen"
                            " (decision 0044); reopen it first")
    # What the reversal takes from the stock, as a draw or a lot binding would
    # take it (decision 0073). Last, and only when nothing else refuses: it
    # runs the reversal in a savepoint.
    if stock and not blockers:
        blockers += stock_blockers(db, wb)
    return {"blockers": blockers, "edited": edited, "missing": missing,
            "blocking_batches": sorted(later)}


class _Trial(Exception):
    """Rolls a trial reversal back."""


#: Tables whose rows move part stock or a lot's capacity.
STOCK_TABLES = {"component_consumptions", "component_stock_adjustments", "run_cost_lines",
                "run_cost_documents", "component_consumption_lots"}


def stock_blockers(db: Session, wb: M.WriteBatch) -> list[str]:
    """Would reversing `wb` leave a part's stock, or a lot, below zero and
    below where it stands now, on any day? (decision 0073.)

    The reversal runs in a savepoint and is rolled back, so the comparison is
    of the stock the reversal really leaves: a draw it puts back, voids again
    or moves to the other company, a purchase it takes away, a binding it puts
    back — together, as one net change. A deficit the stock already had is no
    reason to refuse. The journal records nothing of the trial."""
    from . import lots, run_actuals

    rows = [r for r in wb.rows if r.table_name in STOCK_TABLES]
    if not rows:
        return []
    entries: list[tuple] = []           # what `run_actuals.stock_targets` reads
    lot_keys: set[str] = set()

    def part(d: dict, scope_company) -> None:
        entries.append((run_actuals.stock_scope(db, scope_company), d.get("component_id"), d.get("mpn") or "",
                        d.get("lcsc") or "", d.get("mpn") or d.get("lcsc") or ""))

    def doc_company(doc_id) -> int | None:
        doc = db.get(M.RunCostDocument, doc_id) if doc_id else None
        return doc.company_id if doc is not None else None

    for r in rows:
        model = _model_for(r.table_name)
        cur = db.get(model, r.row_id) if model is not None else None
        if r.table_name == "component_consumptions":
            # A draw made live again takes back the lots it is still bound to.
            for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=r.row_id).all():
                lot_keys.add(lots._lot_key("L", b.lot_line_id) if b.lot_line_id
                             else lots._lot_key("A", b.lot_adjustment_id))
        states = [st for st in ((r.before if r.op != "insert" else None),
                                (_row_dict(cur) if cur is not None else None)) if st]
        for st in states:
            if r.table_name in ("component_consumptions", "component_stock_adjustments"):
                part(st, st.get("company_id"))
                if r.table_name == "component_stock_adjustments":
                    lot_keys.add(lots._lot_key("A", r.row_id))
            elif r.table_name == "run_cost_lines":
                part(st, doc_company(st.get("document_id")))
                lot_keys.add(lots._lot_key("L", r.row_id))
            elif r.table_name == "run_cost_documents":
                for li in db.query(M.RunCostLine).filter_by(document_id=r.row_id).all():
                    part(_row_dict(li), st.get("company_id"))
                    lot_keys.add(lots._lot_key("L", li.id))
            elif r.table_name == "component_consumption_lots":
                if st.get("lot_line_id"):
                    lot_keys.add(lots._lot_key("L", st["lot_line_id"]))
                if st.get("lot_adjustment_id"):
                    lot_keys.add(lots._lot_key("A", st["lot_adjustment_id"]))
    targets, names = run_actuals.stock_targets(db, entries)
    want_lots = any(r.table_name == "component_consumption_lots" for r in rows) or bool(
        lot_keys and db.query(M.ComponentConsumptionLot.id).first())

    def view() -> tuple[dict, dict]:
        pools = run_actuals.stock_view(db, targets)
        if not want_lots:
            return pools, {}
        state = lots.lot_state(db)["lots"]
        out = {k: state[k] for k in lot_keys if k in state}
        # A lot that is gone while live draws are still bound to it holds
        # minus what they hold: `lot_state` lists no such lot.
        for k in lot_keys - set(out):
            col = M.ComponentConsumptionLot.lot_line_id if k.startswith("L") else \
                M.ComponentConsumptionLot.lot_adjustment_id
            held = (db.query(M.ComponentConsumptionLot.qty, M.ComponentConsumption)
                    .join(M.ComponentConsumption, M.ComponentConsumption.id == M.ComponentConsumptionLot.consumption_id)
                    .filter(col == int(k[1:]), M.ComponentConsumption.voided_at.is_(None)).all())
            if held:
                c0 = held[0][1]
                out[k] = {"qty_remaining": -sum(q or 0.0 for q, _c in held), "mpn": c0.mpn, "lcsc": c0.lcsc,
                          "date": "", "gone": True, "draws": sorted({c.id for _q, c in held})}
        return pools, out

    pools_now, lots_now = view()
    held = db.info.pop("wb_rows", None)  # a trial is no write: nothing to journal
    trial: dict = {}
    try:
        with db.begin_nested():          # rolled back by the exception below, always
            _reverse_rows(db, wb)
            trial["pools"], trial["lots"] = view()
            raise _Trial
    except _Trial:
        pass
    except sa.exc.IntegrityError as e:
        # The same words as the Ledger's own collision refusal (decision 0074).
        why = str(e.orig).splitlines()[0] if e.orig else str(e)
        return [(f"a row it puts back collides with the present data ({why}) — the same record was written "
                 "again since; undo that write first")]
    except sa.exc.SQLAlchemyError as e:
        return [f"the reversal itself fails: {(str(e.orig or e).splitlines() or [e.__class__.__name__])[0]}"]
    finally:
        if held is not None:
            db.info["wb_rows"] = held
        db.expire_all()
    pools_after, lots_after = trial["pools"], trial["lots"]
    out = [f"the stock no longer holds what this takes: {x} — undo or correct the later draw first"
           for x in run_actuals.stock_worse(pools_now, pools_after, names)]
    for key, lot in lots_after.items():
        was = (lots_now.get(key) or {}).get("qty_remaining", 0.0)
        gap = min(0.0, was) - (lot.get("qty_remaining") or 0.0)
        if gap > lots.CLOSED_EPS * 100 and lot.get("gone"):
            out.append(f"lot {key} ({lot.get('mpn') or lot.get('lcsc') or '?'}) is taken away while draw(s) "
                       f"{', '.join(f'#{d}' for d in lot['draws'][:5])} are still bound to it — undo or correct "
                       "that draw first")
        elif gap > lots.CLOSED_EPS * 100:
            out.append(f"lot {key} ({lot.get('mpn') or lot.get('lcsc') or '?'}, {lot.get('date')}) would be "
                       f"overdrawn by {round(gap, 4):g} — a later draw took it; undo or correct that draw first")
    return out


# --------------------------------------------------------------- reversing
def reverse(db: Session, batch_id: int, actor: str = "user",
            dry_run: bool = True, stock: bool = True, leaving_twins: frozenset = frozenset()) -> dict:
    """Put a batch back, or say precisely why it cannot be.

    The identity re-assertion at the end checks that the undo moved each figure
    by exactly what the batch moved it (`identity_after - identity_before`),
    rather than absolutely, which is the one place a reversal must differ from
    an apply: later writes by other batches stay where they are. `jlc_apply._assert_identities` checks absolutely
    and deliberately (right for a forward write, since importing on top of a
    pre-existing gap hides its cause) — but applied to an undo it would make
    every batch permanently irreversible for as long as any gap exists, which
    today is always: the register carries a standing $0.0272.
    """
    from . import jlc_apply

    wb = db.get(M.WriteBatch, batch_id)
    if wb is None:
        raise LookupError(f"no write batch {batch_id}")

    state = check_reversible(db, wb, stock=stock, leaving_twins=leaving_twins)
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
        _reverse_rows(db, wb)

        after = jlc_apply.identity_snapshot(db)
        target = wb.identity_before or {}
        made = wb.identity_after or {}
        drift = []
        for key in ("gap_usd", "to_runs_usd", "to_pool_usd", "pool_purchased_usd",
                    "pool_drawn_usd"):
            if key not in target:
                continue
            if key in made:
                # The undo must take away exactly what the batch added. Writes
                # made since, by other batches, stay where they are: comparing
                # with the absolute figure refused every undo after any later
                # money write on the platform.
                undone = (after.get(key) or 0) - (before_now.get(key) or 0)
                added = (made[key] or 0) - (target[key] or 0)
                if abs(undone + added) > 0.01:
                    drift.append(f"{key}: the undo moved {round(undone, 4)}, the batch had moved "
                                 f"{round(added, 4)}")
            elif abs((after.get(key) or 0) - (target[key] or 0)) > 0.01:
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


def _reverse_rows(db: Session, wb: M.WriteBatch) -> None:
    """Put the rows of `wb` back as they were before it: the reversal itself,
    without its journal batch or its checks."""
    # One device names one twin, and the database checks it row by row: a
    # swap's undo must release the device before the other twin takes it.
    mine = {r.row_id for r in wb.rows if r.table_name == "twins"}
    for r in wb.rows:
        if r.table_name == "twins" and r.op == "update" and (r.before or {}).get("device_unit_id") is not None:
            for tw in db.query(M.Twin).filter(M.Twin.device_unit_id == r.before["device_unit_id"],
                                              M.Twin.id != r.row_id, M.Twin.id.in_(mine)).all():
                tw.device_unit_id = None
    db.flush()
    # A click's links no journal wrote (a split's copies, a bench click's
    # whole-step link) are deleted HERE, through the session, so this
    # reversal journals them and a redo puts them back (decision 0074);
    # left to the cascade, a redo would lose them.
    own_rows = {(r.table_name, r.row_id) for r in wb.rows}
    for r in wb.rows:
        if r.table_name == "step_runs" and r.op == "insert":
            for x in db.query(M.CostLineStep).filter(M.CostLineStep.step_run_id == r.row_id).all():
                if ("cost_line_steps", x.id) not in own_rows:
                    db.delete(x)
    db.flush()
    # Newest row first. Inserts happen parents-then-children, so undoing in
    # reverse id order deletes children before the parents they point at.
    back: dict[str, list] = defaultdict(list)
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
            only = HASH_ONLY.get(r.table_name)
            for k, v in (r.before or {}).items():
                if k == "id" or (only and k not in only):
                    continue
                setattr(obj, k, _coerce(model, k, v))
        elif r.op == "delete":
            back[r.table_name].append(model(**{k: _coerce(model, k, v) for k, v in (r.before or {}).items()}))
    db.flush()
    # What the batch deleted comes back parents first, one table at a time:
    # a link has no ORM relationship to its click or its position, so one
    # flush could insert it before them.
    order = {t.name: i for i, t in enumerate(M.Base.metadata.sorted_tables)}
    for table in sorted(back, key=lambda t: order.get(t, 0)):
        db.add_all(back[table])
        db.flush()


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
