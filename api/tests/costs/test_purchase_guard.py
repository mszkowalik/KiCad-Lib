"""A purchase cannot be edited out from under the draws priced against it.

The draw side has been guarded since draws existed (`check_shortages`); this is
the purchase side. Decision record:
docs/decisions/0040-a-purchase-cannot-be-removed-from-under-its-draws.md.

The rule is "would this strand a draw", NOT "has this part ever been consumed".
The blunter rule was measured on the real database first and rejected: it locked
260 of 264 pooled part lines.

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
    """Two purchases of 1000 each, and one draw of 1200 against them."""
    proj = M.Project(name="test-purchase-guard", git_url="https://example.invalid/g.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="G1", run_date="2026-03-01",
                          status="completed", qty=1200)
    db.add(run)
    db.flush()
    doc = M.RunCostDocument(project_id=proj.id, doc_type="invoice", supplier="TESTCO",
                            doc_number="G-0001", doc_date="2026-01-01", currency="USD",
                            total_amount=200.0)
    db.add(doc)
    db.flush()
    early = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", mpn="GUARD-PART-1",
                          lcsc="CGUARD01", qty=1000, unit_price=0.1, position=0)
    late = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", mpn="GUARD-PART-1",
                         lcsc="CGUARD01", qty=1000, unit_price=0.1, position=1)
    db.add_all([early, late])
    db.flush()
    db.add(M.ComponentConsumption(run_id=run.id, mpn="GUARD-PART-1", lcsc="CGUARD01",
                                  qty=1200, unit_cost_usd=0.1, basis="bom",
                                  consumed_at="2026-03-01"))
    db.flush()
    return {"doc": doc, "early": early, "late": late, "run": run}


def test_removing_one_of_two_purchases_is_refused(db: Session, world):
    """1000 + 1000 bought, 1200 drawn: losing either purchase strands 200."""
    short = ra.check_purchase_loss(db, [ra.purchase_loss_of(db, world["late"])])
    assert short, "removing 1000 of 2000 against a 1200 draw must be refused"
    assert short[0]["short"] == pytest.approx(200.0)


def test_shrinking_within_cover_is_allowed(db: Session, world):
    """2000 bought, 1200 drawn: 800 of slack may be given back."""
    assert ra.check_purchase_loss(db, [ra.purchase_loss_of(db, world["late"], qty=200)]) == []


def test_shrinking_past_cover_is_refused(db: Session, world):
    assert ra.check_purchase_loss(db, [ra.purchase_loss_of(db, world["late"], qty=100)])


def test_a_rekey_is_a_total_loss_to_the_old_key(db: Session, world):
    """Pointing the line at another part takes the WHOLE purchase off this key,
    however small the quantity edit alongside it looks."""
    loss = ra.purchase_loss_of(db, world["late"], qty=1000, component_id=4242)
    assert loss["qty"] == 1000.0
    assert ra.check_purchase_loss(db, [loss])


def test_an_untouched_part_is_never_locked(db: Session, world):
    """The rejected rule would have locked this line too, because its PART has
    consumption. Nothing draws more than is bought, so nothing is stranded."""
    spare = M.RunCostLine(document_id=world["doc"].id, plan_key="parts:pool", mpn="GUARD-PART-2",
                          lcsc="CGUARD02", qty=50, unit_price=1.0, position=2)
    db.add(spare)
    db.flush()
    assert ra.check_purchase_loss(db, [ra.purchase_loss_of(db, spare)]) == []


def test_zero_and_negative_losses_are_ignored(db: Session, world):
    """A caller may pass a whole document and let the gains fall out."""
    assert ra.check_purchase_loss(db, [
        ra.purchase_loss_of(db, world["late"], qty=1000),   # no change at all
        {"mpn": "GUARD-PART-1", "qty": -5, "date": "2026-01-01"},
    ]) == []


def test_a_proforma_line_is_not_a_purchase(db: Session, world):
    """A proforma feeds no pool, so it has no stock to strand."""
    world["doc"].doc_type = "proforma"
    db.flush()
    assert ra.pooled_part_lines(db, [world["late"]]) == []


def test_a_run_charged_part_is_not_a_purchase(db: Session, world):
    """A part bought FOR one batch never entered the pool."""
    world["late"].run_id = world["run"].id
    db.flush()
    assert ra.pooled_part_lines(db, [world["late"]]) == []


# ---------------------------------------------------------------- batch netting

@pytest.fixture
def swap_world(db: Session):
    """Two purchases on one document, each fully consumed by its own draw.

    Individually neither may move. Swapping them is legal, because each key ends
    the batch holding exactly what it started with.
    """
    proj = M.Project(name="test-swap", git_url="https://example.invalid/s.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="S1", run_date="2026-03-01",
                          status="completed", qty=100)
    db.add(run)
    db.flush()
    doc = M.RunCostDocument(project_id=proj.id, doc_type="invoice", supplier="TESTCO",
                            doc_number="S-0001", doc_date="2026-01-01", currency="USD",
                            total_amount=300.0)
    db.add(doc)
    db.flush()
    a = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", mpn="SWAP-A", lcsc="CSWAPA",
                      qty=100, unit_price=1.0, position=0)
    b = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", mpn="SWAP-B", lcsc="CSWAPB",
                      qty=200, unit_price=1.0, position=1)
    db.add_all([a, b])
    db.flush()
    db.add_all([
        M.ComponentConsumption(run_id=run.id, mpn="SWAP-A", lcsc="CSWAPA", qty=100,
                               unit_cost_usd=1.0, basis="bom", consumed_at="2026-03-01"),
        M.ComponentConsumption(run_id=run.id, mpn="SWAP-B", lcsc="CSWAPB", qty=200,
                               unit_cost_usd=1.0, basis="bom", consumed_at="2026-03-01"),
    ])
    db.flush()
    return {"a": a, "b": b}


def test_half_a_swap_alone_is_refused(db: Session, swap_world):
    """This is why a per-field save cannot express a swap."""
    a, b = swap_world["a"], swap_world["b"]
    assert ra.batch_purchase_losses(db, [
        {"line": a, "mpn": "SWAP-B", "lcsc": "CSWAPB"},
    ])


def test_a_full_swap_of_quantities_nets_to_zero(db: Session, swap_world):
    """A takes B's identity with B's quantity and vice versa: every key ends
    holding what it started with, so the batch is allowed."""
    a, b = swap_world["a"], swap_world["b"]
    assert ra.batch_purchase_losses(db, [
        {"line": a, "mpn": "SWAP-B", "lcsc": "CSWAPB", "qty": 200.0},
        {"line": b, "mpn": "SWAP-A", "lcsc": "CSWAPA", "qty": 100.0},
    ]) == []


def test_a_swap_that_loses_stock_is_still_refused(db: Session, swap_world):
    """Netting is not a loophole: swap the identities but keep the quantities and
    SWAP-A ends with 200 while SWAP-B ends with 100, which is 100 short."""
    a, b = swap_world["a"], swap_world["b"]
    short = ra.batch_purchase_losses(db, [
        {"line": a, "mpn": "SWAP-B", "lcsc": "CSWAPB"},
        {"line": b, "mpn": "SWAP-A", "lcsc": "CSWAPA"},
    ])
    assert short and short[0]["short"] == pytest.approx(100.0)


def test_deleting_both_sides_is_refused(db: Session, swap_world):
    a, b = swap_world["a"], swap_world["b"]
    assert len(ra.batch_purchase_losses(db, [
        {"line": a, "pooled_after": False},
        {"line": b, "pooled_after": False},
    ])) == 2
