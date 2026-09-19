"""Closing the books on a batch, and correcting one afterwards.

Decision record:
docs/decisions/0044-a-correction-is-an-event-not-an-edit-to-the-past.md.

What is being protected: a batch's DIRECT costs are recomputed from its invoice
lines on every read, so editing a two-year-old assembly invoice moves the
batch's per-device cost and the cost of every order that shipped one of its
units — silently, and with no record that the figure ever changed. Component
costs were never exposed to this (a draw snapshots its unit cost), which is why
the lock deliberately leaves pool invoices alone.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import timedelta

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
    """A batch with an assembly invoice charged to it, and a parts invoice that
    only feeds the pool the batch draws from."""
    proj = M.Project(name="test-closed-batch", git_url="https://example.invalid/c.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="C1", run_date="2026-03-01",
                          status="completed", qty=100)
    db.add(run)
    db.flush()

    # `created_at` is explicit on every fixture document, because it is what
    # decides the lock: a document written AFTER the books closed is the
    # correction, not the thing being corrected. Leaving it to default to "now"
    # made the tests depend on which side of the same millisecond they landed.
    filed = M.utcnow() - timedelta(days=30)

    # Charged to the batch: this is what a close protects.
    direct = M.RunCostDocument(project_id=proj.id, run_id=run.id, doc_type="invoice",
                               supplier="ASSEMBLYCO", doc_number="C-0001",
                               doc_date="2026-02-01", currency="USD", total_amount=500.0,
                               created_at=filed)
    db.add(direct)
    db.flush()
    db.add(M.RunCostLine(document_id=direct.id, plan_key="pcba:general", label="SMT",
                         qty=1, unit_price=500.0, position=0))

    # Feeds the pool only: never locked, because a draw has already snapshotted
    # what it paid and a later edit cannot move it.
    pooled = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="PARTSCO",
                               doc_number="C-0002", doc_date="2026-01-01",
                               currency="USD", total_amount=100.0, created_at=filed)
    db.add(pooled)
    db.flush()
    db.add(M.RunCostLine(document_id=pooled.id, plan_key="parts:pool", mpn="CLOSE-PART-1",
                         lcsc="CCLOSE01", qty=1000, unit_price=0.1, position=0))
    db.flush()
    return {"proj": proj, "run": run, "direct": direct, "pooled": pooled}


def _close(db: Session, run: M.ProductionRun, when=None) -> None:
    run.closed_at = when or M.utcnow()
    run.closed_by = "tests"
    db.flush()


# ------------------------------------------------------------------ the lock

def test_an_open_batch_locks_nothing(db: Session, world):
    assert ra.closed_lock(db, world["direct"]) == []
    assert ra.closed_lock(db, world["pooled"]) == []


def test_closing_locks_the_document_charged_to_the_batch(db: Session, world):
    _close(db, world["run"])
    locked = ra.closed_lock(db, world["direct"])
    assert [r["run_id"] for r in locked] == [world["run"].id]
    assert locked[0]["closed_by"] == "tests"


def test_a_pool_invoice_is_never_locked(db: Session, world):
    """The batch draws from this stock, but its draws snapshot what they paid.
    Locking it would block ordinary stock corrections and protect nothing."""
    _close(db, world["run"])
    assert ra.closed_lock(db, world["pooled"]) == []


def test_a_line_charged_to_the_batch_locks_a_shared_document(db: Session, world):
    """The lock follows the MONEY, not `document.run_id`. One printed invoice
    covering two products is entered once and split per position."""
    shared = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="FREIGHTCO",
                               doc_number="C-0003", doc_date="2026-02-05",
                               currency="USD", total_amount=80.0,
                               created_at=M.utcnow() - timedelta(days=30))
    db.add(shared)
    db.flush()
    db.add(M.RunCostLine(document_id=shared.id, plan_key="logistics:inbound", label="share",
                         qty=1, unit_price=80.0, run_id=world["run"].id, position=0))
    db.flush()
    assert ra.closed_lock(db, shared) == []
    _close(db, world["run"])
    assert [r["run_id"] for r in ra.closed_lock(db, shared)] == [world["run"].id]


def test_a_voided_line_does_not_lock(db: Session, world):
    """A retired position charges nobody, so it cannot be what holds a document
    read-only."""
    shared = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="GHOSTCO",
                               doc_number="C-0004", doc_date="2026-02-05",
                               currency="USD", total_amount=10.0,
                               created_at=M.utcnow() - timedelta(days=30))
    db.add(shared)
    db.flush()
    db.add(M.RunCostLine(document_id=shared.id, plan_key="other:discount", qty=1, unit_price=10.0,
                         run_id=world["run"].id, voided_at=M.utcnow(), position=0))
    db.flush()
    _close(db, world["run"])
    assert ra.closed_lock(db, shared) == []


# ------------------------------------------------------------- the correction

def test_a_document_written_after_the_close_is_editable(db: Session, world):
    """This is what makes the correction path work with no special case for it:
    a document that postdates the close IS the correction."""
    _close(db, world["run"], when=M.utcnow() - timedelta(days=1))
    later = M.RunCostDocument(project_id=world["proj"].id, run_id=world["run"].id,
                              doc_type="correction", supplier="ASSEMBLYCO",
                              doc_number="C-0001-C1", doc_date="2026-09-19",
                              currency="USD", total_amount=-25.0,
                              corrects_document_id=world["direct"].id)
    db.add(later)
    db.flush()
    assert ra.closed_lock(db, later) == []


def test_a_correction_moves_the_batch_cost_and_the_original_is_untouched(db: Session, world):
    _close(db, world["run"], when=M.utcnow() - timedelta(days=1))
    before = ra.run_actuals(db, world["run"])["total"]
    fix = M.RunCostDocument(project_id=world["proj"].id, run_id=world["run"].id,
                            doc_type="correction", supplier="ASSEMBLYCO",
                            doc_number="C-0001-C1", doc_date="2026-09-19",
                            currency="USD", total_amount=-25.0,
                            corrects_document_id=world["direct"].id)
    db.add(fix)
    db.flush()
    db.add(M.RunCostLine(document_id=fix.id, plan_key="pcba:general", label="overcharge",
                         qty=1, unit_price=-25.0, position=0))
    db.flush()
    after = ra.run_actuals(db, world["run"])["total"]
    assert after == pytest.approx(before - 25.0)
    # The original keeps what it printed — the same rule a split parent follows.
    assert world["direct"].total_amount == 500.0
    assert [li.unit_price for li in world["direct"].lines] == [500.0]


def test_the_document_json_carries_the_lock_and_both_links(db: Session, world):
    """The UI decides what to offer from this payload, so the lock, the back
    pointer and the forward pointer all have to be on it."""
    _close(db, world["run"], when=M.utcnow() - timedelta(days=1))
    fix = M.RunCostDocument(project_id=world["proj"].id, run_id=world["run"].id,
                            doc_type="correction", supplier="ASSEMBLYCO",
                            doc_number="C-0001-C1", doc_date="2026-09-19",
                            currency="USD", corrects_document_id=world["direct"].id)
    db.add(fix)
    db.flush()
    original = ra.document_json(world["direct"], db=db)
    assert [r["run_id"] for r in original["locked"]] == [world["run"].id]
    assert [c["id"] for c in original["corrected_by"]] == [fix.id]
    correction = ra.document_json(fix, db=db)
    assert correction["locked"] == []
    assert correction["corrects_document_id"] == world["direct"].id


# ------------------------------------------------------------- the snapshot

def test_the_close_snapshot_is_what_the_register_says(db: Session, world):
    """`closed_cost_usd` has to be the figure `orders.per_device_cost_usd`
    divides, or the variance the page shows compares two different things."""
    cost, units = ra.close_snapshot(db, world["run"])
    reg = ra.invoice_register(db)
    assert cost == pytest.approx(
        (reg["by_run_usd"][str(world["run"].id)] or {})["total_usd"])
    assert units == ra.produced_counts(db, [world["run"].id]).get(world["run"].id, 0)


# ------------------------------------------------------------ pinned attrition

def test_a_pinned_write_off_is_not_repriced_by_a_later_purchase(db: Session, world):
    """The bug: `unit_cost_usd IS NULL` resolved against the pool average as it
    stands ON EVERY READ, so a write-off kept moving as later invoices arrived."""
    run = world["run"]
    loose = M.ComponentStockAdjustment(
        project_id=world["proj"].id, mpn="CLOSE-PART-1", lcsc="CCLOSE01",
        qty_delta=-100, unit_cost_usd=None, reason="attrition",
        charge_run_id=run.id, adjusted_at="2026-02-01")
    db.add(loose)
    db.flush()
    drifting = ra.run_actuals(db, run)["attrition"]

    # A later, much dearer purchase of the same part.
    dear = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="PARTSCO",
                             doc_number="C-0005", doc_date="2026-06-01",
                             currency="USD", total_amount=9000.0)
    db.add(dear)
    db.flush()
    db.add(M.RunCostLine(document_id=dear.id, plan_key="parts:pool", mpn="CLOSE-PART-1",
                         lcsc="CCLOSE01", qty=1000, unit_price=9.0, position=0))
    db.flush()
    assert ra.run_actuals(db, run)["attrition"] != pytest.approx(drifting), \
        "an unpinned write-off is repriced by a later purchase — the bug 0044 fixes"

    # Pinned at the average on its OWN date, it stays where it was put.
    loose.unit_cost_usd = 0.1
    db.flush()
    pinned = ra.run_actuals(db, run)["attrition"]
    dearer = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="PARTSCO",
                               doc_number="C-0006", doc_date="2026-07-01",
                               currency="USD", total_amount=50000.0)
    db.add(dearer)
    db.flush()
    db.add(M.RunCostLine(document_id=dearer.id, plan_key="parts:pool", mpn="CLOSE-PART-1",
                         lcsc="CCLOSE01", qty=1000, unit_price=50.0, position=0))
    db.flush()
    assert ra.run_actuals(db, run)["attrition"] == pytest.approx(pinned)


def test_resolve_pool_identity_prices_at_the_adjustment_date(db: Session, world):
    """What the write path pins with. The average AT THE DATE, not the average
    after every purchase that has happened since."""
    dear = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="PARTSCO",
                             doc_number="C-0007", doc_date="2026-06-01",
                             currency="USD", total_amount=9000.0)
    db.add(dear)
    db.flush()
    db.add(M.RunCostLine(document_id=dear.id, plan_key="parts:pool", mpn="CLOSE-PART-1",
                         lcsc="CCLOSE01", qty=1000, unit_price=9.0, position=0))
    db.flush()
    at_date = ra.resolve_pool_identity(db, None, "CLOSE-PART-1", "CCLOSE01",
                                       as_of="2026-02-01")
    today = ra.resolve_pool_identity(db, None, "CLOSE-PART-1", "CCLOSE01")
    assert at_date["avg_usd"] == pytest.approx(0.1)
    assert today["avg_usd"] > 0.1
