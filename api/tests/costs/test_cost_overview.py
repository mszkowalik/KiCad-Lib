"""Finance → Cost overview: one company's view, and the figures its tiles add up.

What is being protected:

1. **A one-company view shows its own batches, each at its whole cost.** The
   register took the scoped company's documents and every company's draws, so
   in the 7Sigma view 9Sigma's Batch 8 read 7,558.29 USD (its draws without its
   invoices) where it cost 12,167.05. A batch's cost is one figure: its devices
   carry it onto orders (decision 0043), and the batch list follows the scope
   by the batch's company (decision 0065 §4).
2. **"Boards ordered" is the typed quantity.** The register's `qty` is what
   passed, with the typed quantity as its fallback, and the tile summed it:
   7,147 where the batches were ordered at 7,086.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_cost_overview.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import companies as C
from app.services import orders as osvc
from app.services import run_actuals as RA
from app.services.material_ledger import core as ledger


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


def _doc(db, company, run, amount, number):
    doc = M.RunCostDocument(doc_type="invoice", supplier="TEST-OVERVIEW", doc_number=number,
                            doc_date="2026-04-01", currency="USD", total_amount=amount,
                            company_id=company.id)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="pcba:general", label="assembly",
                         qty=1, unit_price=amount, currency="USD", run_id=run.id))
    db.flush()
    return doc


@pytest.fixture
def world(db: Session):
    """A 9Sigma batch billed 100 by 9Sigma and 20 by 7Sigma, with 50 of draws, and
    a 7Sigma batch billed 30 by 7Sigma."""
    s7, s9 = C.by_key(db, "7sigma"), C.by_key(db, "9sigma")
    p = M.Project(name="test-cost-overview", git_url="https://example.invalid/co.git")
    db.add(p)
    db.flush()
    r9 = M.ProductionRun(project_id=p.id, label="CO9", run_date="2026-04-01", status="completed",
                         qty=12, company_id=s9.id)
    r7 = M.ProductionRun(project_id=p.id, label="CO7", run_date="2026-04-01", status="completed",
                         qty=5, company_id=s7.id)
    db.add_all([r9, r7])
    db.flush()
    _doc(db, s9, r9, 100.0, "CO-9-1")
    _doc(db, s7, r9, 20.0, "CO-7-9")
    _doc(db, s7, r7, 30.0, "CO-7-7")
    ledger.draw(db, run_id=r9.id, mpn="TEST-CO-PART", taken=10, unit_cost_usd=5.0, at="2026-04-02",
                company_id=s9.id, basis="manual")
    for i in range(3):
        d = M.DeviceUnit(project_id=p.id, serial=f"CO{i}", mac=f"00:00:00:00:c0:{i:02x}",
                         first_seen=datetime(2026, 4, 3, 12, i, tzinfo=UTC), condition="ok")
        db.add(d)
        db.flush()
        osvc.record_event(db, d, "produced", production_run_id=r9.id)
    db.flush()
    return SimpleNamespace(s7=s7, s9=s9, r9=r9, r7=r7)


def _cost(reg, run):
    return (reg["by_run_usd"].get(str(run.id)) or {}).get("total_usd")


def test_the_whole_view_shows_every_batch_at_its_whole_cost(db, world):
    reg = RA.invoice_register(db, accountant=False)
    assert _cost(reg, world.r9) == pytest.approx(170.0)
    assert _cost(reg, world.r7) == pytest.approx(30.0)


def test_a_company_view_shows_its_batches_at_their_whole_cost(db, world):
    """9Sigma's batch is 9Sigma's, whoever paid its invoices. It read 150 here:
    the 7Sigma invoice that charges it was out of the view."""
    reg = RA.invoice_register(db, [world.s9.id], accountant=False)
    assert _cost(reg, world.r9) == pytest.approx(170.0)
    assert str(world.r7.id) not in reg["by_run_usd"], "a 7Sigma batch is not in the 9Sigma view"
    numbers = {d["doc_number"] for d in reg["documents"]}
    assert "CO-7-9" not in numbers, "the other company's document stays out of the list"


def test_the_other_company_view_does_not_show_a_batch_by_its_draws(db, world):
    """In the 7Sigma view the 9Sigma batch read 70: its draws and 7Sigma's own
    invoice, as if that were what the batch cost."""
    reg = RA.invoice_register(db, [world.s7.id], accountant=False)
    assert str(world.r9.id) not in reg["by_run_usd"]
    assert _cost(reg, world.r7) == pytest.approx(30.0)


def test_boards_ordered_is_the_typed_quantity(db, world):
    run = RA.invoice_register(db, accountant=False)["runs"][str(world.r9.id)]
    assert run["qty"] == 3, "what passed"
    assert run["qty_ordered"] == 12, "what was ordered"
