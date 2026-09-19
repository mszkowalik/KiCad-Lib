"""Where a position's money goes, and the two states that used to share a spelling.

Decision record:
docs/decisions/0045-a-position-says-where-its-money-goes.md.

`allocate="none"` on a line naming no run and no project meant two different
things, decided by a field nobody was being asked about:

  * `plan_key="parts:pool"`   -> the shared pool. Correct, and invisible.
  * anything else   -> `unassigned`. Money nobody pays for, and a defect.

`POOLED` is the first one said outright. These tests pin both halves: that a
`pooled` line reaches the pool from any kind, and that a line which has decided
nothing is still reported rather than quietly absorbed.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import run_actuals as ra


@pytest.fixture
def db():
    """One transaction, never committed: the dev database is left untouched."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def world(db: Session):
    proj = M.Project(name="test-line-dest", git_url="https://example.invalid/d.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="D1", run_date="2026-03-01",
                          status="completed", qty=10)
    db.add(run)
    db.flush()
    shared = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="DESTCO",
                              doc_number="D-0001", doc_date="2026-01-01",
                              currency="USD", total_amount=100.0)
    db.add(shared)
    db.flush()
    return {"proj": proj, "run": run, "doc": shared}


def _line(db, doc, **kw) -> M.RunCostLine:
    kw.setdefault("qty", 1)
    kw.setdefault("unit_price", 10.0)
    kw.setdefault("position", 0)
    li = M.RunCostLine(document_id=doc.id, **kw)
    db.add(li)
    db.flush()
    return li


# ------------------------------------------------- the two states, told apart

def test_a_pooled_part_reaches_the_pool_because_it_says_so(db: Session, world):
    """Stock is STATED, not inferred from `kind` — the value is what makes the
    difference between "it goes to the pool" and "nobody has decided"."""
    li = _line(db, world["doc"], plan_key="parts:pool", allocate=ra.POOLED)
    assert ra.line_destination(li, world["doc"]) == ("pool", None)


def test_only_a_stock_step_may_be_marked_pooled(db: Session, world):
    """`_pool_events` treats only a STOCK STEP as a purchase, so a `pooled` line
    on any other step would sit in the register's `pool` bucket and never appear
    in `pool.purchased_usd` — two pool figures, quietly disagreeing. The router
    refuses it; money that belongs on the stock rides there as landed cost."""
    from fastapi import HTTPException

    from app.routers.run_costs import _check_allocate

    _check_allocate("parts:pool", ra.POOLED)            # fine
    _check_allocate("pcba:parts", ra.POOLED)            # fine — supplier-sourced
    _check_allocate("logistics:inbound", "by_value")    # fine — landed cost
    for step in ("other:discount", "final:shipping_prep", "logistics:inbound"):
        with pytest.raises(HTTPException) as exc:
            _check_allocate(step, ra.POOLED)
        assert exc.value.status_code == 422


def test_an_undecided_non_part_is_still_unassigned(db: Session, world):
    """The defect detector must survive: `none` on a line naming nothing is
    money nobody pays for, and it has to keep being reported."""
    li = _line(db, world["doc"], plan_key="other:discount", allocate="none")
    assert ra.line_destination(li, world["doc"]) == ("unassigned", None)


def test_a_legacy_part_line_still_reaches_the_pool(db: Session, world):
    """~600 rows predate `pooled`. They must not move."""
    li = _line(db, world["doc"], plan_key="parts:pool", allocate="none")
    assert ra.line_destination(li, world["doc"]) == ("pool", None)


# ------------------------------------------------------------ precedence

def test_pooled_beats_the_documents_own_destination(db: Session, world):
    """A parts invoice filed against a batch can still carry plain stock, and
    saying so on the line is the only way to express it."""
    doc = M.RunCostDocument(project_id=world["proj"].id, run_id=world["run"].id,
                            doc_type="invoice", supplier="DESTCO", doc_number="D-0002",
                            doc_date="2026-01-02", currency="USD")
    db.add(doc)
    db.flush()
    stated = _line(db, doc, plan_key="parts:pool", allocate=ra.POOLED)
    assert ra.line_destination(stated, doc) == ("pool", None)
    # Without the marker, the document's own batch claims it — unchanged.
    silent = _line(db, doc, plan_key="fab:pcb", allocate="none")
    assert ra.line_destination(silent, doc) == ("run", world["run"].id)


def test_a_named_run_beats_pooled(db: Session, world):
    """Charging a position to a batch is the most specific thing you can say."""
    li = _line(db, world["doc"], plan_key="parts:pool", allocate=ra.POOLED, run_id=world["run"].id)
    assert ra.line_destination(li, world["doc"]) == ("run", world["run"].id)


def test_excluded_still_beats_everything(db: Session, world):
    """Unchanged, and the reason the UI must CLEAR `allocate` when a position
    moves onto a batch: the old editor only ever added `excluded` and never took
    it off, so the line kept reading as charged to nobody."""
    li = _line(db, world["doc"], plan_key="fab:pcb", allocate=ra.EXCLUDED, run_id=world["run"].id)
    assert ra.line_destination(li, world["doc"]) == ("excluded", None)


# ---------------------------------------------------- pooled behaves as none

def test_a_pooled_part_is_a_real_purchase(db: Session, world):
    """`pooled` must pass every "is this a purchase" test that `none` passed, or
    the backfill would have taken 264 lines out of the pool."""
    li = _line(db, world["doc"], plan_key="parts:pool", mpn="DEST-PART-1", qty=100,
               unit_price=0.5, allocate=ra.POOLED)
    assert ra.pooled_part_lines(db, [li]) == [li]
    pool = ra.pool_state(db)
    entry = ra.resolve_pool_identity(db, None, "DEST-PART-1", "")
    assert entry is not None and entry["qty"] == pytest.approx(100.0)
    assert pool  # the replay ran


def test_the_register_identity_holds_with_pooled_lines(db: Session, world):
    """`invoiced == runs + projects + pool + excluded + unassigned + residual`.
    A new `allocate` value that any bucket missed would show up here as a gap.

    Measured as a DELTA against the database's own baseline rather than against
    a fixed number: the dev database carries a pre-existing gap of its own, and
    a test that hard-codes it fails for the wrong reason the day it is fixed.
    """
    before = ra.invoice_register(db)["summary"]["gap_usd"] or 0.0
    doc = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="DESTCO",
                            doc_number="D-0003", doc_date="2026-01-03",
                            currency="USD", total_amount=15.0)
    db.add(doc)
    db.flush()
    _line(db, doc, plan_key="parts:pool", mpn="DEST-PART-2", qty=10,
          unit_price=1.0, allocate=ra.POOLED)
    _line(db, doc, plan_key="logistics:inbound", label="carriage", qty=1,
          unit_price=5.0, allocate="by_value", position=1)
    after = ra.invoice_register(db)["summary"]["gap_usd"] or 0.0
    assert after == pytest.approx(before, abs=0.005), \
        "a pooled line left money in no bucket at all"
