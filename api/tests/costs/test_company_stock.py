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


# ------------------------------------------------- review fixes of 2026-10-04

def _key_of(mpn="CS-PART-1"):
    return ra._key(SimpleNamespace(component_id=None, mpn=mpn, lcsc=""))


def _bound_draw(db, run, qty, line_id=None, adj_id=None, day="2025-02-01", company_id=None, **kw):
    c = M.ComponentConsumption(run_id=run.id if run else None, mpn="CS-PART-1", qty=qty, unit_cost_usd=0.1,
                               basis="measured", consumed_at=day, company_id=company_id, **kw)
    db.add(c)
    db.flush()
    b = M.ComponentConsumptionLot(consumption_id=c.id, lot_line_id=line_id, lot_adjustment_id=adj_id,
                                  qty=qty, unit_cost_usd=0.1, source="reported")
    db.add(b)
    db.flush()
    return c, b


def test_a_manual_lot_transfer_takes_the_receiver_s_draws_with_it(db, world):
    """A transfer naming a lot moves the receiver's draws bound to it onto its
    position, so the history plan does not move the same lot again."""
    line = world.doc.lines[0]
    _c, b = _bound_draw(db, world.r9, 25, line_id=line.id)
    res = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                   lines=[{"mpn": "CS-PART-1", "qty": 25, "lot_line_id": line.id}], dry_run=False)
    db.refresh(b)
    assert b.lot_line_id == res["lines"][0]["line_id"]
    from app.services import lots as Lmod
    assert Lmod.check_lot_capacity(db, []) == []
    plan = T.plan_history(db)
    assert not [t for t in plan["transfers"] if t["run_id"] == world.r9.id], plan["transfers"]


def test_a_partial_lot_transfer_splits_the_binding(db, world):
    line = world.doc.lines[0]
    c, _b = _bound_draw(db, world.r9, 25, line_id=line.id)
    res = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                   lines=[{"mpn": "CS-PART-1", "qty": 10, "lot_line_id": line.id}], dry_run=False)
    rows = db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id).all()
    assert sorted((r.lot_line_id == line.id, r.qty) for r in rows) == [(False, 10), (True, 15)]
    assert res["lines"][0]["rebind"][0]["qty"] == pytest.approx(10)


def test_the_history_counts_a_lot_move_once(db, world):
    """9Sigma drew 25 bound to 7Sigma's lot and later 10 with no lot. The lot
    move covers the 25 only, so the 10 still needs a balance transfer."""
    line = world.doc.lines[0]
    _bound_draw(db, world.r9, 25, line_id=line.id)
    db.add(M.ComponentConsumption(run_id=world.r9.id, mpn="CS-PART-1", qty=10, unit_cost_usd=0.1,
                                  consumed_at="2025-03-01"))
    db.flush()
    plan = T.plan_history(db)
    mine = [t for t in plan["transfers"] if t["run_id"] == world.r9.id]
    assert sorted((t["evidence"], sum(ln["qty"] for ln in t["lines"])) for t in mine) == \
        [("balance", 10.0), ("lot", 25.0)]


def test_a_lot_that_is_an_adjustment_moves_with_its_draws(db, world, split):
    a = M.ComponentStockAdjustment(mpn="CS-PART-1", qty_delta=50, unit_cost_usd=0.2, reason="opening_balance",
                                   adjusted_at="2025-01-05", company_id=world.s7.id)
    db.add(a)
    db.flush()
    _c, b = _bound_draw(db, world.r9, 20, adj_id=a.id, company_id=world.s9.id)
    res = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                   lines=[{"mpn": "CS-PART-1", "qty": 20, "lot_adjustment_id": a.id}], dry_run=False)
    assert res["lot_capacity"] == []
    db.refresh(b)
    assert b.lot_adjustment_id is None and b.lot_line_id == res["lines"][0]["line_id"]


def test_one_pool_ignores_a_transfer(db, world):
    """With one pool a transfer moves nothing: the combined average and
    quantity stay what they were."""
    d9 = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="CS-9", doc_date="2025-01-02",
                           currency="USD", total_amount=30.0, company_id=world.s9.id)
    db.add(d9)
    db.flush()
    db.add(M.RunCostLine(document_id=d9.id, plan_key="parts:pool", allocate="pooled", mpn="CS-PART-1",
                         qty=100, unit_price=0.3, position=0))
    db.flush()
    before = ra.pool_state(db)[_key_of()]
    T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-15",
             lines=[{"mpn": "CS-PART-1", "qty": 40}], dry_run=False)
    after = ra.pool_state(db)[_key_of()]
    assert (after["qty"], round(after["avg_usd"], 6)) == (before["qty"], round(before["avg_usd"], 6)) == (200.0, 0.2)
    assert ra.invoice_register(db)["pool"]["balanced"]


def test_charging_an_order_moves_the_other_company_s_lots_first(db, world, split):
    """The order drew 7Sigma's lot for a 9Sigma batch: the charge writes the
    transfer, takes the binding with it and stamps the draws 9Sigma."""
    from app.services import jlc_apply

    line = world.doc.lines[0]
    c, b = _bound_draw(db, None, 30, line_id=line.id, company_id=world.s7.id,
                       import_ref="jlc:BCS1:SMT-CS-1:CS-PART-1")
    plan = {"smt_order_code": "SMT-CS-1", "batch_num": "BCS1"}
    dry = jlc_apply.charge_draws(db, plan, world.r9.id, dry_run=True)
    assert dry["cover"]["shortages"] == [] and len(dry["cover"]["transfers"]) == 1
    res = jlc_apply.charge_draws(db, plan, world.r9.id, dry_run=False)
    db.refresh(c)
    db.refresh(b)
    assert (c.run_id, c.company_id) == (world.r9.id, world.s9.id)
    assert db.get(M.RunCostDocument, db.get(M.RunCostLine, b.lot_line_id).document_id).doc_type == "transfer"
    assert len(res["cover"]["written"]) == 1
    assert ra.pool_state(db, company_id=world.s9.id)[_key_of()]["qty"] == pytest.approx(0.0)


def test_charging_with_one_pool_stamps_the_batch_s_company(db, world):
    from app.services import jlc_apply

    c = M.ComponentConsumption(run_id=None, mpn="CS-PART-1", qty=5, unit_cost_usd=0.1, basis="measured",
                               consumed_at="2025-02-01", company_id=world.s7.id,
                               import_ref="jlc:BCS1:SMT-CS-1:CS-PART-1")
    db.add(c)
    db.flush()
    jlc_apply.charge_draws(db, {"smt_order_code": "SMT-CS-1", "batch_num": "BCS1"}, world.r9.id, dry_run=False)
    db.refresh(c)
    assert c.company_id == world.s9.id


def test_a_transfer_s_draw_is_not_deleted_alone(db, world, split):
    from app.routers import run_costs as rc

    res = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-15",
                   lines=[{"mpn": "CS-PART-1", "qty": 4}], dry_run=False)
    with pytest.raises(HTTPException) as e:
        rc.delete_consumption(res["lines"][0]["sender_draw_id"], db=db)
    assert e.value.status_code == 409


def test_a_moved_batch_takes_its_draws_and_losses(db, world, split):
    from app.routers import production_runs as pr

    c = M.ComponentConsumption(run_id=world.r9.id, mpn="CS-PART-1", qty=30, unit_cost_usd=0.1,
                               consumed_at="2025-02-01")
    a = M.ComponentStockAdjustment(project_id=world.p.id, mpn="CS-PART-1", qty_delta=-5, reason="attrition",
                                   charge_run_id=world.r9.id, adjusted_at="2025-02-02", unit_cost_usd=0.1)
    db.add_all([c, a])
    db.flush()
    assert (c.company_id, a.company_id) == (world.s9.id, world.s9.id)
    pr.update_run(world.r9.id, pr.RunPatch(company_id=world.s7.id), db=db)
    db.refresh(c)
    db.refresh(a)
    assert (c.company_id, a.company_id) == (world.s7.id, world.s7.id)
    # 7Sigma held 100: 65 remain after the batch's 30 and its 5 lost
    assert ra.pool_state(db, company_id=world.s7.id)[_key_of()]["qty"] == pytest.approx(65.0)


def test_a_batch_moves_only_to_a_company_that_holds_its_stock(db, world, split):
    from app.routers import production_runs as pr

    db.add(M.ComponentConsumption(run_id=world.r7.id, mpn="CS-PART-1", qty=30, unit_cost_usd=0.1,
                                  consumed_at="2025-02-01"))
    db.flush()
    with pytest.raises(HTTPException) as e:
        pr.update_run(world.r7.id, pr.RunPatch(company_id=world.s9.id), db=db)
    assert e.value.status_code == 409


def test_an_uncharged_draw_is_given_its_company(db, world, split):
    from app.routers import run_costs as rc

    c = M.ComponentConsumption(run_id=None, mpn="CS-PART-1", qty=3, unit_cost_usd=0.1, basis="measured",
                               consumed_at="2025-02-01", import_ref="jlcledger:999001")
    db.add(c)
    db.flush()
    assert c.company_id is None
    rc.set_draw_company(c.id, rc.DrawCompanyIn(company_id=world.s7.id, dry_run=False), db=db)
    db.refresh(c)
    assert c.company_id == world.s7.id
    charged = M.ComponentConsumption(run_id=world.r7.id, mpn="CS-PART-1", qty=1, consumed_at="2025-02-01")
    db.add(charged)
    db.flush()
    with pytest.raises(HTTPException):
        rc.set_draw_company(charged.id, rc.DrawCompanyIn(company_id=world.s9.id, dry_run=False), db=db)


def test_the_backfill_reads_a_pick_s_company_from_its_lot(db, world):
    from app.services import company_backfill as CB

    line = world.doc.lines[0]
    c, _b = _bound_draw(db, None, 3, line_id=line.id, import_ref="jlcledger:999002")
    assert c.company_id is None
    out = CB.backfill(db, dry_run=False)
    db.refresh(c)
    assert c.company_id == world.s7.id
    assert c.id not in {d["id"] for d in out["unresolved_draws"]}


def test_a_loss_charged_to_a_batch_is_its_company_s(db, world):
    from app.routers import run_costs as rc

    with pytest.raises(HTTPException) as e:
        rc.add_adjustment(world.p.id, rc.AdjustmentIn(company_id=world.s7.id, mpn="CS-PART-1", qty_delta=-1,
                                                      charge_run_id=world.r9.id, adjusted_at="2025-02-01"), db=db)
    assert e.value.status_code == 422


def test_a_correction_has_its_original_s_buyer(db, world):
    from app.routers import run_costs as rc

    out = rc.create_correction(world.doc.id, rc.CorrectionIn(), db=db)
    corr = db.get(M.RunCostDocument, out["id"])
    assert (corr.company_id, corr.company_source) == (world.s7.id, "the corrected document")
    with pytest.raises(HTTPException):
        rc.create_shared_document(rc.DocumentIn(supplier="X", doc_number="CS-C-2", doc_type="correction",
                                                corrects_document_id=world.doc.id,
                                                company_id=world.s9.id), db=db)


def test_a_transfer_is_never_typed_by_hand(db, world):
    from app.routers import run_costs as rc

    with pytest.raises(HTTPException) as e:
        rc.create_shared_document(rc.DocumentIn(supplier="X", doc_number="CS-T-1", doc_type="transfer"), db=db)
    assert e.value.status_code == 422
    with pytest.raises(HTTPException):
        rc.update_document(world.doc.id, rc.DocumentPatch(doc_type="transfer"), db=db)


def test_a_batch_is_planned_from_its_company_s_stock(db, world, split):
    from datetime import UTC, datetime

    from app.services import project_bom as PB

    comp = M.Component(name="test-cs-component")
    db.add(comp)
    db.flush()
    db.add(M.RunCostLine(document_id=world.doc.id, plan_key="parts:pool", allocate="pooled",
                         component_id=comp.id, mpn="CS-COMP", qty=10, unit_price=0.5, position=1))
    db.flush()
    at = datetime(2025, 2, 1, tzinfo=UTC)
    points7 = PB._component_data(db, {comp.id}, at=at, project_id=world.p.id, run=world.r7)[0]
    points9 = PB._component_data(db, {comp.id}, at=at, project_id=world.p.id, run=world.r9)[0]
    assert points7[comp.id][0].source == "Pool average (invoices)"
    assert comp.id not in points9 or points9[comp.id][0].source != "Pool average (invoices)"


# ------------------------------------------- verification round of 2026-10-04

def test_a_charge_uses_a_transfer_already_typed_in(db, world, split):
    """A person moved 30 on the Transfers page (no lot). The JLC order then
    drew 30 of 7Sigma's lot for a 9Sigma batch: the charge writes no second
    transfer, the binding moves onto the typed one, and that one takes the lot."""
    from app.services import jlc_apply
    from app.services import lots as Lmod

    typed = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                     lines=[{"mpn": "CS-PART-1", "qty": 30}], dry_run=False)
    line = world.doc.lines[0]
    _c, b = _bound_draw(db, None, 30, line_id=line.id, company_id=world.s7.id,
                        import_ref="jlc:BCS2:SMT-CS-2:CS-PART-1")
    res = jlc_apply.charge_draws(db, {"smt_order_code": "SMT-CS-2", "batch_num": "BCS2"}, world.r9.id,
                                 dry_run=False)
    assert res["cover"]["written"] == [] and len(res["cover"]["absorbed"]) == 1
    db.refresh(b)
    assert b.lot_line_id == typed["lines"][0]["line_id"]
    assert ra.pool_state(db, company_id=world.s7.id)[_key_of()]["qty"] == pytest.approx(70.0)
    assert ra.pool_state(db, company_id=world.s9.id)[_key_of()]["qty"] == pytest.approx(0.0)
    assert Lmod.check_lot_capacity(db, []) == []
    state = Lmod.lot_state(db)["lots"]
    assert state[f"L{line.id}"]["qty_remaining"] == pytest.approx(70.0)


def test_a_refused_charge_names_the_sender_s_short_parts(db, world, split):
    from app.services import jlc_apply

    line = world.doc.lines[0]
    # 7Sigma's own batch takes 90 of the 100 first
    db.add(M.ComponentConsumption(run_id=world.r7.id, mpn="CS-PART-1", qty=90, unit_cost_usd=0.1,
                                  consumed_at="2025-01-10"))
    _bound_draw(db, None, 30, line_id=line.id, company_id=world.s7.id, import_ref="jlc:BCS3:SMT-CS-3:CS-PART-1")
    with pytest.raises(jlc_apply.ApplyRefused) as e:
        jlc_apply.charge_draws(db, {"smt_order_code": "SMT-CS-3", "batch_num": "BCS3"}, world.r9.id,
                               dry_run=False)
    assert "7Sigma does not hold" in str(e.value) and "CS-PART-1" in str(e.value)


def test_the_history_uses_a_transfer_typed_without_a_lot(db, world):
    line = world.doc.lines[0]
    _c, b = _bound_draw(db, world.r9, 25, line_id=line.id)
    typed = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                     lines=[{"mpn": "CS-PART-1", "qty": 25}], dry_run=False)
    plan = T.plan_history(db)
    assert not [t for t in plan["transfers"] if t["run_id"] == world.r9.id], plan["transfers"]
    assert [r["binding_id"] for r in plan["rebinds"]] == [b.id]
    res = T.apply_history(db, dry_run=False)
    assert res["rebound"] == 1 and not [w for w in res["written"] if w["batch"] == world.r9.label]
    db.refresh(b)
    assert b.lot_line_id == typed["lines"][0]["line_id"]
    from app.services import lots as Lmod
    assert Lmod.check_lot_capacity(db, []) == []
    assert ra.pool_state(db, company_id=world.s7.id)[_key_of()]["qty"] == pytest.approx(75.0)


def test_a_moved_batch_s_loss_is_checked_in_the_new_company(db, world, split):
    from app.routers import production_runs as pr

    a = M.ComponentStockAdjustment(project_id=world.p.id, mpn="CS-PART-1", qty_delta=-5, reason="attrition",
                                   charge_run_id=world.r7.id, adjusted_at="2025-02-02", unit_cost_usd=0.1)
    db.add(a)
    db.flush()
    with pytest.raises(HTTPException) as e:
        pr.update_run(world.r7.id, pr.RunPatch(company_id=world.s9.id), db=db)
    assert e.value.status_code == 409


def test_a_batch_move_is_not_reversed_from_the_ledger(db, world, split):
    from app.routers import ledger
    from app.routers import production_runs as pr

    db.add(M.ComponentConsumption(run_id=world.r9.id, mpn="CS-PART-1", qty=3, unit_cost_usd=0.1,
                                  consumed_at="2025-02-01"))
    db.flush()
    pr.update_run(world.r9.id, pr.RunPatch(company_id=world.s7.id), db=db)
    wb = db.query(M.WriteBatch).filter_by(kind="run.company").order_by(M.WriteBatch.id.desc()).first()
    assert wb is not None
    with pytest.raises(HTTPException) as e:
        ledger.reverse_batch(wb.id, dry_run=True, db=db)
    assert e.value.status_code == 409


def test_a_lot_is_named_once_in_a_transfer(db, world, split):
    line = world.doc.lines[0]
    p = T.plan(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
               lines=[{"mpn": "CS-PART-1", "qty": 50, "lot_line_id": line.id},
                      {"mpn": "CS-PART-1", "qty": 50, "lot_line_id": line.id}])
    assert any("name each lot once" in pr["problem"] for pr in p["problems"])


def test_found_stock_on_a_moving_batch_counts_the_batch_s_own_draws_leaving(db, world, split):
    """7Sigma: 100 bought, X7 drew 100, +5 found charged to X7, another 7Sigma
    batch used those 5. Moving X7 to 9Sigma (which holds 200) leaves 7Sigma
    with 95 — no refusal."""
    from app.routers import production_runs as pr

    d9 = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="CS-9B", doc_date="2025-01-02",
                           currency="USD", total_amount=20.0, company_id=world.s9.id)
    db.add(d9)
    db.flush()
    db.add(M.RunCostLine(document_id=d9.id, plan_key="parts:pool", allocate="pooled", mpn="CS-PART-1",
                         qty=200, unit_price=0.1, position=0))
    r7b = M.ProductionRun(project_id=world.p.id, label="CS7B", run_date="2025-02-10", qty=5, company_id=world.s7.id)
    db.add(r7b)
    db.flush()
    db.add_all([
        M.ComponentConsumption(run_id=world.r7.id, mpn="CS-PART-1", qty=100, unit_cost_usd=0.1,
                               consumed_at="2025-02-01"),
        M.ComponentStockAdjustment(project_id=world.p.id, mpn="CS-PART-1", qty_delta=5, reason="found",
                                   charge_run_id=world.r7.id, adjusted_at="2025-02-05", unit_cost_usd=0.1),
        M.ComponentConsumption(run_id=r7b.id, mpn="CS-PART-1", qty=5, unit_cost_usd=0.1, consumed_at="2025-02-10"),
    ])
    db.flush()
    pr.update_run(world.r7.id, pr.RunPatch(company_id=world.s9.id), db=db)
    assert ra.pool_state(db, company_id=world.s7.id)[_key_of()]["qty"] == pytest.approx(95.0)


def test_a_transfer_is_never_corrected(db, world, split):
    from app.routers import run_costs as rc

    res = T.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-15",
                   lines=[{"mpn": "CS-PART-1", "qty": 4}], dry_run=False)
    with pytest.raises(HTTPException) as e:
        rc.create_correction(res["document_id"], rc.CorrectionIn(), db=db)
    assert e.value.status_code == 409


def test_a_correction_keeps_its_original_s_buyer(db, world):
    from app.routers import run_costs as rc

    out = rc.create_correction(world.doc.id, rc.CorrectionIn(), db=db)
    with pytest.raises(HTTPException) as e:
        rc.update_document(out["id"], rc.DocumentPatch(company_id=world.s9.id), db=db)
    assert e.value.status_code == 422
