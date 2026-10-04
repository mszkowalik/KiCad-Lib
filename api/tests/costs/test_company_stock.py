"""Stock per company (decision 0064): each company draws only from its own
stock once `stock_per_company` is on, and nothing changes while it is off.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_company_stock.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.config import settings
from app.db import engine
from app.services import appconfig
from app.services import companies as C
from app.services import run_actuals as ra


@pytest.fixture
def db():
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
def split(monkeypatch):
    monkeypatch.setattr(settings, "stock_per_company", True)


@pytest.fixture
def world(db):
    """7Sigma bought 100 of a part. A 7Sigma batch and a 9Sigma batch."""
    s7, s9 = C.by_key(db, "7sigma"), C.by_key(db, "9sigma")
    p = M.Project(name="test-company-stock", git_url="https://example.invalid/cs.git")
    db.add(p)
    db.flush()
    db.add(M.ProjectOwnership(project_id=p.id, company_id=s7.id, from_date="2024-01-01"))
    r7 = M.ProductionRun(project_id=p.id, label="CS7", run_date="2025-02-01", qty=10,
                         company_id=s7.id)
    r9 = M.ProductionRun(project_id=p.id, label="CS9", run_date="2025-02-01", qty=10,
                         company_id=s9.id)
    doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="CS-1",
                            doc_date="2025-01-01", currency="USD", total_amount=10.0,
                            company_id=s7.id)
    db.add_all([r7, r9, doc])
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled",
                         mpn="CS-PART-1", qty=100, unit_price=0.1, position=0))
    db.flush()
    return SimpleNamespace(s7=s7, s9=s9, p=p, r7=r7, r9=r9, doc=doc)


def _want(qty, run):
    return [{"mpn": "CS-PART-1", "qty": qty, "date": "2025-02-01"}], run


def test_a_draw_gets_its_batch_company(db, world):
    c = M.ComponentConsumption(run_id=world.r9.id, mpn="CS-PART-1", qty=1, consumed_at="2025-02-01")
    a = M.ComponentStockAdjustment(project_id=world.p.id, mpn="CS-PART-1", qty_delta=-1,
                                   adjusted_at="2025-03-01")
    db.add_all([c, a])
    db.flush()
    assert c.company_id == world.s9.id      # the batch's company
    assert a.company_id == world.s7.id      # the project's owner on the day


def test_one_pool_while_the_switch_is_off(db, world):
    cands, run = _want(50, world.r9)
    assert ra.run_scope(db, run) is None
    assert ra.check_shortages(db, cands, company_id=ra.run_scope(db, run)) == []


def test_a_company_cannot_draw_the_other_company_s_stock(db, world, split):
    cands, run = _want(50, world.r9)
    short = ra.check_shortages(db, cands, company_id=ra.run_scope(db, run))
    assert short and short[0]["short"] == pytest.approx(50.0)
    assert short[0]["company_id"] == world.s9.id
    cands, run = _want(50, world.r7)
    assert ra.check_shortages(db, cands, company_id=ra.run_scope(db, run)) == []


def test_each_company_replays_its_own_pool(db, world, split):
    db.add(M.ComponentConsumption(run_id=world.r7.id, mpn="CS-PART-1", qty=30,
                                  unit_cost_usd=0.1, consumed_at="2025-02-01"))
    db.flush()
    p7 = ra.pool_state(db, company_id=world.s7.id)
    p9 = ra.pool_state(db, company_id=world.s9.id)
    key = ra._key(SimpleNamespace(component_id=None, mpn="CS-PART-1", lcsc=""))
    assert p7[key]["qty"] == pytest.approx(70.0)
    assert key not in p9
    states = ra.pool_states(db)
    assert set(states) >= {world.s7.id, world.s9.id}


def test_a_purchase_loss_is_the_buyer_s(db, world, split):
    """Taking the purchase away strands the 7Sigma draw, not a 9Sigma one."""
    db.add(M.ComponentConsumption(run_id=world.r7.id, mpn="CS-PART-1", qty=60,
                                  unit_cost_usd=0.1, consumed_at="2025-02-01"))
    db.flush()
    line = world.doc.lines[0]
    loss = ra.purchase_loss_of(db, line, qty=50)
    assert loss["company_id"] == world.s7.id
    assert ra.check_purchase_loss(db, [loss])


def test_the_switch_waits_for_every_record_to_name_its_company(db, world):
    knob = appconfig.BY_KEY["stock_per_company"]
    db.add(M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="CS-2",
                             doc_date="2025-01-02", currency="USD"))
    db.flush()
    nobody = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="CS-3",
                               doc_date="2025-01-03", currency="USD")
    db.add(nobody)
    db.flush()
    db.add(M.RunCostLine(document_id=nobody.id, plan_key="parts:pool", allocate="pooled",
                         mpn="CS-PART-2", qty=1, unit_price=1.0, position=0))
    db.flush()
    assert C.stock_without_company(db)["documents with parts"] >= 1
    with pytest.raises(ValueError):
        appconfig.validate(knob, True, db)
    appconfig.validate(knob, False, db)   # turning it off is always allowed


# ------------------------------------------------------------ transfers (0064)

from fastapi import HTTPException  # noqa: E402

from app.services import transfers as T  # noqa: E402


def test_a_transfer_moves_stock_at_the_sender_s_average(db, world, split):
    res = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-15",
                   lines=[{"mpn": "CS-PART-1", "qty": 40}], run_id=world.r9.id, dry_run=False)
    assert res["lines"][0]["unit_cost_usd"] == pytest.approx(0.1)
    cands, run = _want(40, world.r9)
    assert ra.check_shortages(db, cands, company_id=ra.run_scope(db, run)) == []
    cands, run = _want(70, world.r7)   # 7Sigma now holds 60
    assert ra.check_shortages(db, cands, company_id=ra.run_scope(db, run))
    reg = ra.invoice_register(db)
    assert reg["pool"]["transfers_usd"] == pytest.approx(4.0)
    assert reg["pool"]["transferred_out_usd"] == pytest.approx(4.0)
    assert reg["summary"]["gap_usd"] == pytest.approx(0.0)


def test_a_transfer_needs_the_sender_to_hold_the_stock(db, world, split):
    with pytest.raises(HTTPException):
        T.create(db, sender_id=world.s9.id, receiver_id=world.s7.id, day="2025-01-15",
                 lines=[{"mpn": "CS-PART-1", "qty": 1}], dry_run=False)


def test_a_used_transfer_cannot_be_reversed(db, world, split):
    res = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-15",
                   lines=[{"mpn": "CS-PART-1", "qty": 40}], dry_run=False)
    doc = db.get(M.RunCostDocument, res["document_id"])
    db.add(M.ComponentConsumption(run_id=world.r9.id, mpn="CS-PART-1", qty=30,
                                  unit_cost_usd=0.1, consumed_at="2025-02-01"))
    db.flush()
    with pytest.raises(HTTPException):
        T.reverse(db, doc, reason="test", dry_run=False)


def test_a_reversal_gives_the_stock_back(db, world, split):
    res = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-15",
                   lines=[{"mpn": "CS-PART-1", "qty": 40}], dry_run=False)
    doc = db.get(M.RunCostDocument, res["document_id"])
    T.reverse(db, doc, reason="entered twice", dry_run=False)
    key = ra._key(SimpleNamespace(component_id=None, mpn="CS-PART-1", lcsc=""))
    assert ra.pool_state(db, company_id=world.s7.id)[key]["qty"] == pytest.approx(100.0)
    assert ra.pool_state(db, company_id=world.s9.id).get(key, {}).get("qty", 0.0) == pytest.approx(0.0)


def test_the_history_moves_what_a_batch_drew_from_the_other_company(db, world):
    """A 9Sigma batch drew 30 that 7Sigma bought: the plan moves 30, at the
    average, dated with the draw."""
    db.add(M.ComponentConsumption(run_id=world.r9.id, mpn="CS-PART-1", qty=30,
                                  unit_cost_usd=0.1, consumed_at="2025-02-01"))
    db.flush()
    plan = T.plan_history(db)
    mine = [t for t in plan["transfers"] if t["run_id"] == world.r9.id]
    assert len(mine) == 1
    t = mine[0]
    assert (t["sender_id"], t["receiver_id"], t["date"]) == (world.s7.id, world.s9.id, "2025-02-01")
    assert sum(ln["qty"] for ln in t["lines"]) == pytest.approx(30.0)
    assert t["value_usd"] == pytest.approx(3.0)


def test_a_draw_bound_to_the_other_company_s_lot_moves_with_that_lot(db, world):
    """JLC said which purchase the 9Sigma order consumed: that lot moves, at its
    landed cost, and the draw's binding moves onto the transfer's position."""
    line = world.doc.lines[0]
    c = M.ComponentConsumption(run_id=world.r9.id, mpn="CS-PART-1", qty=25,
                               unit_cost_usd=0.1, basis="measured", consumed_at="2025-02-01")
    db.add(c)
    db.flush()
    b = M.ComponentConsumptionLot(consumption_id=c.id, lot_line_id=line.id, qty=25,
                                  unit_cost_usd=0.1, source="reported")
    db.add(b)
    db.flush()
    plan = T.plan_history(db)
    mine = [t for t in plan["transfers"] if t["run_id"] == world.r9.id]
    assert [t["evidence"] for t in mine] == ["lot"]
    res = T.apply_history(db, dry_run=False)
    assert not [r for r in res["refused"] if r["batch"] == world.r9.label], res["refused"]
    db.refresh(b)
    moved = db.get(M.RunCostLine, b.lot_line_id)
    assert db.get(M.RunCostDocument, moved.document_id).doc_type == "transfer"
    from app.services import lots as Lmod
    assert Lmod.check_lot_capacity(db, []) == []
    state = Lmod.lot_state(db)["lots"]
    assert state[f"L{line.id}"]["qty_remaining"] == pytest.approx(75.0)
    assert state[f"L{moved.id}"]["qty_remaining"] == pytest.approx(0.0)
