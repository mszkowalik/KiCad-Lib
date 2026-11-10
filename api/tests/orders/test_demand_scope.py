"""The demand card follows the header's company (decision 0063).

What is being protected: `project_demand` counted every company's orders,
devices and batches whatever the switcher said, so the 7Sigma view of the
Orders page showed 9Sigma's open orders and its 5,600 planned dongles
(2026-11-09). An order counts for the company that sold it, a batch for its own
company, and a device for its batch's company, else its project's owner.

Run from `api/`, with the dev database up:
    python -m pytest tests/orders/test_demand_scope.py -q
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
from app.services import orders as svc


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
    """A project 7Sigma made first and 9Sigma owns now: one 7Sigma batch with
    one device, one 9Sigma batch with two, a device that names no batch, a
    planned 9Sigma batch, and one open order from each company."""
    s7, s9 = C.by_key(db, "7sigma"), C.by_key(db, "9sigma")
    proj = M.Project(name="test-demand-scope", git_url="https://example.invalid/ds.git")
    db.add(proj)
    db.flush()
    db.add(M.ProjectOwnership(project_id=proj.id, company_id=s7.id, from_date="2024-01-01"))
    db.add(M.ProjectOwnership(project_id=proj.id, company_id=s9.id, from_date="2024-07-22"))
    run7 = M.ProductionRun(project_id=proj.id, label="DS7", run_date="2024-05-01", status="completed",
                           qty=1, company_id=s7.id)
    run9 = M.ProductionRun(project_id=proj.id, label="DS9", run_date="2025-05-01", status="completed",
                           qty=2, company_id=s9.id)
    plan9 = M.ProductionRun(project_id=proj.id, label="DS9-plan", run_date="2027-01-01", status="planned",
                            qty=100, company_id=s9.id)
    db.add_all([run7, run9, plan9])
    db.flush()
    for i, run_id in enumerate([run7.id, run9.id, run9.id, None]):
        d = M.DeviceUnit(project_id=proj.id, serial=f"DS{i}", mac=f"00:00:00:00:d5:{i:02x}",
                         first_seen=datetime(2025, 5, 1, 12, i, tzinfo=UTC))
        db.add(d)
        db.flush()
        svc.record_event(db, d, "produced", production_run_id=run_id)
    cust = svc.get_customer(db, "test-demand-scope-customer")
    for company, ref, qty in [(s7, "TEST/DS7", 5), (s9, "TEST/DS9", 7)]:
        o = M.SalesOrder(customer_id=cust.id, order_ref=ref, order_date="2026-03-02", company_id=company.id)
        db.add(o)
        db.flush()
        db.add(M.SalesOrderLine(order_id=o.id, project_id=proj.id, product="thing", qty_ordered=qty,
                                unit_price=1.0))
    db.flush()
    return SimpleNamespace(s7=s7, s9=s9, proj=proj)


def _row(db: Session, world, scope) -> dict:
    rows = svc.project_demand(db, world.proj.id, scope)
    assert len(rows) == 1
    return rows[0]


def test_one_company_sees_only_its_own_orders_devices_and_batches(db, world):
    r7 = _row(db, world, [world.s7.id])
    assert (r7["open"], r7["open_orders"], r7["on_shelf"], r7["planned"]) == (5, 1, 1, 0)
    assert r7["planned_runs"] == []

    # The device that names no batch is the project's CURRENT owner's.
    r9 = _row(db, world, [world.s9.id])
    assert (r9["open"], r9["open_orders"], r9["on_shelf"], r9["planned"]) == (7, 1, 3, 100)


def test_every_company_or_no_scope_counts_everything(db, world):
    for scope in (None, [world.s7.id, world.s9.id]):
        r = _row(db, world, scope)
        assert (r["open"], r["open_orders"], r["on_shelf"], r["planned"]) == (12, 2, 4, 100)


def test_the_two_companies_add_up_to_the_whole(db, world):
    """No row is lost or counted twice by the split."""
    r7, r9, whole = (_row(db, world, s) for s in ([world.s7.id], [world.s9.id], None))
    for key in ("open", "on_shelf", "planned", "in_work"):
        assert r7[key] + r9[key] == whole[key], key


# ------------------------------------------------- the Finished devices page


def _request(company_id):
    """What the web sends: an admin (sees every company) and the switcher."""
    admin = SimpleNamespace(role="admin", username="test-scope-admin")
    return SimpleNamespace(state=SimpleNamespace(user=admin),
                           headers={"x-company": str(company_id) if company_id else "all"})


def test_the_shelf_cards_follow_the_switcher(db, world):
    from app.routers import orders as routes

    def products(company_id):
        out = routes.finished_products(request=_request(company_id), db=db)["products"]
        return next((p["in_stock"] for p in out if p["project_id"] == world.proj.id), 0)

    def batches(company_id):
        out = routes.finished_stock(request=_request(company_id), project_id=world.proj.id, db=db)
        return sorted(r["label"] for r in out["runs"]), out["totals"]["no_batch"]

    assert (products(world.s7.id), products(world.s9.id), products(None)) == (1, 3, 4)
    assert batches(world.s7.id) == (["DS7"], 0)
    # The device naming no batch is the project's current owner's: 9Sigma.
    assert batches(world.s9.id) == (["DS9", "DS9-plan"], 1)
    assert batches(None) == (["DS7", "DS9", "DS9-plan"], 1)
