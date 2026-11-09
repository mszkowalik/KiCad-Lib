"""A contract's plan (decision 0107): the calendar, the date nodes, draft
orders, the balance of a part, proposals, reservations and deleting a plan.

Run from `api/`, with the dev database up:
    python -m pytest tests/plans -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import orders as order_svc
from app.services import planning as PL
from app.services import plans as svc

TODAY = date(2026, 11, 9)


class _Req:
    state = SimpleNamespace(user=None)


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


# ---------------------------------------------------------------- calendar


def test_polish_holidays():
    h26, h27 = PL.holidays(2026), PL.holidays(2027)
    assert date(2026, 11, 11) in h26
    assert date(2026, 12, 24) in h26          # a holiday from 2025
    assert date(2027, 3, 28) in h27 and date(2027, 3, 29) in h27   # Easter 2027 and its Monday
    assert date(2027, 5, 27) in h27           # Corpus Christi, Easter + 60
    assert not PL.is_workday(date(2026, 12, 24))
    assert PL.add_workdays(date(2026, 12, 23), 1) == date(2026, 12, 28)


def test_add_months_keeps_the_end_of_the_month():
    assert PL.add_months(date(2026, 12, 31), 2) == date(2027, 2, 28)
    assert PL.add_months(date(2026, 11, 12), 2) == date(2027, 1, 12)


# ---------------------------------------------------------------- nodes


def _n(i, **kw):
    base = dict(id=i, plan_id=1, kind="milestone", mode="fixed", day="", after=None, lag=0, lag_unit="days",
                snap_weekday=None, party="ours", done_on="")
    base.update(kw)
    return M.PlanNode(**base)


def test_a_fixed_date_never_moves_and_reports_a_conflict():
    nodes = {1: _n(1, day="2026-12-10"), 2: _n(2, mode="fixed", day="2026-12-12", after=["n:1"], lag=5)}
    D = PL.Dates(TODAY, nodes, {}, {})
    x = D.node(2)
    assert x.day == date(2026, 12, 12)
    assert "2026-12-15" in x.conflict


def test_an_after_date_follows_its_latest_predecessor_and_snaps():
    nodes = {1: _n(1, day="2026-12-01"), 2: _n(2, day="2026-12-20"),
             3: _n(3, mode="after", after=["n:1", "n:2"], lag=2, snap_weekday=3)}
    x = PL.Dates(TODAY, nodes, {}, {}).node(3)
    assert x.day == date(2026, 12, 24)   # 22 Dec + to the next Thursday


def test_a_late_task_of_ours_counts_from_today_and_a_customer_date_does_not():
    nodes = {1: _n(1, day="2026-11-06"), 2: _n(2, mode="after", after=["n:1"], lag=14),
             3: _n(3, day="2026-11-04", party="customer")}
    D = PL.Dates(TODAY, nodes, {}, {})
    assert D.node(1).day == TODAY and D.node(1).late_days == 3
    assert D.node(2).day == date(2026, 11, 23)
    assert D.node(3).day == date(2026, 11, 4)


def test_a_done_node_is_its_fact():
    nodes = {1: _n(1, day="2026-11-01", done_on="2026-11-02"), 2: _n(2, mode="after", after=["n:1"], lag=1)}
    D = PL.Dates(TODAY, nodes, {}, {})
    assert D.node(1).day == date(2026, 11, 2) and D.node(1).done
    assert D.node(2).day == TODAY      # 3 Nov is past and open: from today


def test_a_cycle_is_refused():
    nodes = {1: _n(1, mode="after", after=["n:2"]), 2: _n(2, mode="after", after=["n:1"])}
    with pytest.raises(PL.CycleError):
        PL.Dates(TODAY, nodes, {}, {}).node(1)


# ---------------------------------------------------------------- a plan


@pytest.fixture
def world(db: Session):
    cust = M.Customer(name="test-plan-customer", payment_terms_days=14)
    proj = M.Project(name="test-plan-project", git_url="https://example.invalid/plan.git")
    db.add_all([cust, proj])
    db.flush()
    snap = M.ProjectSnapshot(project_id=proj.id, sha="a" * 40, ref_name="v1", is_tag=True, status="ready",
                             boards=[{"name": "B", "kind": "board"}])
    db.add(snap)
    db.flush()
    comp = M.Component(name="test-plan-part-X")
    db.add(comp)
    db.flush()
    db.add(M.SnapshotBomLine(snapshot_id=snap.id, board="B", variant="", refs="U1, U2", qty=2, component_id=comp.id,
                             value="X"))
    plan = M.Plan(name="test plan", customer_id=cust.id, advance_days=14, final_days=14, min_lead_months=2,
                  advance_limit_net=106000, delivery_weekday=3, build_lead_days=7, attrition_pct=0)
    db.add(plan)
    db.flush()
    svc.set_projects(db, plan, [{"project_id": proj.id, "snapshot_mode": "fixed", "snapshot_id": snap.id}])
    return SimpleNamespace(cust=cust, proj=proj, snap=snap, comp=comp, plan=plan)


def _order(db, w, key, od, deliveries, qty=300, price=450.0):
    return svc.add_order(db, w.plan, {"plan_key": key, "order_date": od, "lines": [
        {"project_id": w.proj.id, "qty_ordered": qty, "unit_price": price, "deliveries": deliveries}]}, "test")


def test_a_draft_order_counts_in_no_demand_and_takes_no_shipment(db, world):
    o = _order(db, world, "V3-1", "2026-11-12", [{"qty": 300, "after": None, "day": "2027-01-14"}])
    assert o.draft and o.status == "draft"
    dem = order_svc.project_demand(db, world.proj.id)
    assert all(r["open"] == 0 for r in dem)
    with pytest.raises(HTTPException) as e:
        order_svc.open_shipment(db, o)
    assert e.value.status_code == 409


def test_moving_the_order_date_moves_the_deliveries_that_follow_its_advance(db, world):
    o = _order(db, world, "V3-1", "2026-11-12",
               [{"qty": 200, "after": [], "mode": "after", "lag": 49}, {"qty": 100, "mode": "after", "lag": 56}])
    s = PL.schedule(db, world.plan, TODAY)
    row = s["orders"][0]
    assert row["advance_due"] == "2026-11-26"
    assert [d["day"] for d in row["lines"][0]["deliveries"]] == ["2027-01-14", "2027-01-21"]
    assert row["advance_net"] == 81000.0 and row["advance_gross"] == 99630.0
    assert row["final_day"] == "2027-01-21" and row["final_due"] == "2027-02-04"
    o.order_date = "2026-11-19"
    db.flush()
    row = PL.schedule(db, world.plan, TODAY)["orders"][0]
    assert [d["day"] for d in row["lines"][0]["deliveries"]] == ["2027-01-21", "2027-01-28"]


def test_contract_checks(db, world):
    _order(db, world, "A", "2026-11-04", [{"qty": 100, "day": "2027-01-28"}, {"qty": 200, "day": "2027-02-04"}])
    _order(db, world, "B", "2026-11-04", [{"qty": 300, "day": "2026-12-31"}])
    s = PL.schedule(db, world.plan, TODAY)
    flags = {o["key"]: {f["code"] for f in o["flags"]} for o in s["orders"]}
    assert {"order_past", "one_month"} <= flags["A"]
    assert "two_month" in flags["B"]
    assert s["over_limit"] and s["over_limit"][0]["net"] == 162000.0
    sev = {b["title"].split(" ")[0] for b in s["blockers"] if b["severity"] == "block"}
    assert sev


def test_a_part_balance_finds_the_shortage_and_the_proposal_says_when(db, world):
    _order(db, world, "V3-1", "2026-12-01", [{"qty": 100, "day": "2027-02-11"}], qty=100)
    run = svc.add_batch(db, world.plan, {"project_id": world.proj.id, "qty": 100, "label": "B1",
                                         "order": {"day": "2026-12-15"}})
    db.flush()
    sup = M.Supplier(name="test-plan-supplier")
    db.add(sup)
    db.flush()
    db.add(M.ComponentSupplier(component_id=world.comp.id, supplier_id=sup.id, lead_days=60))
    db.flush()
    s = PL.schedule(db, world.plan, TODAY)
    part = next(p for p in s["parts"] if p["component_id"] == world.comp.id)
    assert part["need"] == 200 and part["status"] == "short" and part["first_short"] == "2026-12-15"
    pr = next(p for p in s["proposals"] if p["component_id"] == world.comp.id)
    assert pr["supplier"] == "test-plan-supplier" and pr["qty"] == 200
    assert pr["order_day"] == "2026-11-09" and pr["arrival_day"] == "2027-01-08" and pr["late"]
    assert any("cannot arrive in time" in b["title"] for b in s["blockers"])
    # a reservation covers part of it, and the need falls by as much
    svc.add_reservations(db, world.plan, [{"component_id": world.comp.id, "qty": 50}], "test")
    s = PL.schedule(db, world.plan, TODAY)
    part = next(p for p in s["parts"] if p["component_id"] == world.comp.id)
    # nothing is on hand, so the reservation is broken and counts nothing
    assert part["reserved"] == 0 and part["reserved_broken"] == 50
    assert run.status == "planned"


def test_an_accepted_proposal_becomes_a_draft_that_goes_out_of_date(db, world):
    _order(db, world, "V3-1", "2026-12-01", [{"qty": 100, "day": "2027-03-11"}], qty=100)
    svc.add_batch(db, world.plan, {"project_id": world.proj.id, "qty": 100, "order": {"day": "2027-02-01"}})
    sup = M.Supplier(name="test-plan-supplier-2")
    db.add(sup)
    db.flush()
    db.add(M.ComponentSupplier(component_id=world.comp.id, supplier_id=sup.id, lead_days=10))
    db.flush()
    s = PL.schedule(db, world.plan, TODAY)
    key = next(p["key"] for p in s["proposals"] if p["component_id"] == world.comp.id)
    pos = svc.accept_proposals(db, world.plan, [key], "test")
    db.flush()
    s = PL.schedule(db, world.plan, TODAY)
    po = next(x for x in s["purchase_orders"] if x["id"] == pos[0].id)
    assert po["status"] == "draft" and po["out_of_date"] == ""
    assert not any(p["status"] == "short" for p in s["parts"] if p["component_id"] == world.comp.id)
    # the batch grows: the plan now proposes more, and the draft says so
    run = db.query(M.ProductionRun).filter(M.ProductionRun.plan_id == world.plan.id).one()
    run.qty = 150
    db.flush()
    s = PL.schedule(db, world.plan, TODAY)
    po = next(x for x in s["purchase_orders"] if x["id"] == pos[0].id)
    assert po["lines"][0]["qty"] == 200
    assert next(p for p in s["parts"] if p["component_id"] == world.comp.id)["short"] == 100
    assert "100 more" in po["out_of_date"] and po["suggested_qty"] == 300


def test_an_ordered_batch_is_frozen_and_a_branch_follows_the_newest_snapshot(db, world):
    run = svc.add_batch(db, world.plan, {"project_id": world.proj.id, "qty": 10, "order": {"day": "2026-12-01"}})
    newer = M.ProjectSnapshot(project_id=world.proj.id, sha="b" * 40, ref_name="main", is_tag=False, status="ready",
                              boards=[{"name": "B", "kind": "board"}])
    db.add(newer)
    db.flush()
    pp = world.plan.projects[0]
    pp.snapshot_mode, pp.branch, pp.snapshot_id = "branch", "main", None
    db.flush()
    assert PL.resolve_snapshot(db, pp).id == newer.id
    svc.order_batch(db, world.plan, run, "2026-12-02")
    assert run.status == "in production" and run.snapshot_id == newer.id and run.run_date == "2026-12-02"


def test_a_node_outside_the_plan_is_refused(db, world):
    other = M.Plan(name="other plan")
    db.add(other)
    db.flush()
    foreign = svc.new_node(db, other, "milestone", None, {"label": "x", "day": "2026-12-01"})
    with pytest.raises(HTTPException) as e:
        svc.new_node(db, world.plan, "milestone", None, {"label": "y", "mode": "after", "after": [f"n:{foreign.id}"]})
    assert e.value.status_code == 422


def test_deleting_a_plan_removes_what_it_owns_and_lets_go_of_the_rest(db, world):
    draft = _order(db, world, "D", "2026-12-01", [{"qty": 300, "day": "2027-02-04"}])
    real = _order(db, world, "R", "2026-12-01", [{"qty": 300, "mode": "after", "lag": 60}])
    real.draft = False
    order_svc.refresh_order_status(real)
    run = svc.add_batch(db, world.plan, {"project_id": world.proj.id, "qty": 10, "order": {"day": "2026-12-01"}})
    svc.add_reservations(db, world.plan, [{"component_id": world.comp.id, "qty": 5}], "test")
    db.flush()
    owned = svc.plan_owned(db, world.plan)
    assert [o["id"] for o in owned["delete"]["draft_orders"]] == [draft.id]
    assert [o["id"] for o in owned["keep"]["orders"]] == [real.id]
    run_id, draft_id = run.id, draft.id
    svc.delete_plan(db, world.plan)
    db.flush()
    assert db.get(M.SalesOrder, draft_id) is None and db.get(M.ProductionRun, run_id) is None
    db.refresh(real)
    assert real.plan_id is None
    dv = db.query(M.SalesOrderDelivery).filter(
        M.SalesOrderDelivery.order_line_id == real.lines[0].id).one()
    node = db.get(M.PlanNode, dv.node_id)
    assert node.mode == "fixed" and node.day and node.plan_id is None
    assert db.query(M.PlanReservation).filter(M.PlanReservation.plan_id == world.plan.id).count() == 0


def test_a_jlc_part_that_jlc_must_buy_in_takes_its_slowest_measured_receipt(db, world):
    from datetime import UTC, datetime

    line = db.query(M.SnapshotBomLine).filter_by(snapshot_id=world.snap.id).one()
    line.lcsc = "C99999901"
    jlc = db.query(M.Supplier).filter_by(name="JLCPCB").first()
    if jlc is None:
        db.add(M.Supplier(name="JLCPCB"))
    for i, (code, got) in enumerate((("POB0202609230016917", datetime(2026, 10, 9, tzinfo=UTC)),
                                     ("COB202611051831177", datetime(2026, 11, 5, tzinfo=UTC)))):
        db.add(M.JlcStockChange(change_key_id=9_900_000_000 + i, stock_key_id=9_900_000_000, lcsc="C99999901",
                                changed_at=got, change_qty=100, qty_after=100, business_code=code, business_type=5))
    db.flush()
    m = PL.jlc_measured_leads(db)["C99999901"]
    assert (m["min"], m["max"], m["last"]) == (0, 16, 0)
    _order(db, world, "V3-1", "2026-12-01", [{"qty": 100, "day": "2027-02-11"}], qty=100)
    svc.add_batch(db, world.plan, {"project_id": world.proj.id, "qty": 100, "order": {"day": "2027-01-15"}})
    db.flush()
    s = PL.schedule(db, world.plan, TODAY)
    pr = next(p for p in s["proposals"] if p["component_id"] == world.comp.id)
    assert pr["supplier"] == "JLCPCB" and pr["lead_days"] == 16 and "slowest" in pr["lead_source"]


def test_a_part_measured_only_in_stock_has_no_presale_lead(db, world):
    from datetime import UTC, datetime

    line = db.query(M.SnapshotBomLine).filter_by(snapshot_id=world.snap.id).one()
    line.lcsc = "C99999902"
    db.add(M.JlcStockChange(change_key_id=9_900_000_010, stock_key_id=9_900_000_010, lcsc="C99999902",
                            changed_at=datetime(2026, 11, 5, tzinfo=UTC), change_qty=10, qty_after=10,
                            business_code="COB202611051831177", business_type=5))
    _order(db, world, "V3-1", "2026-12-01", [{"qty": 100, "day": "2027-02-11"}], qty=100)
    svc.add_batch(db, world.plan, {"project_id": world.proj.id, "qty": 100, "order": {"day": "2027-01-15"}})
    db.flush()
    s = PL.schedule(db, world.plan, TODAY)
    pr = next(p for p in s["proposals"] if p["component_id"] == world.comp.id)
    assert pr["no_lead"] and pr["lead_days"] is None
