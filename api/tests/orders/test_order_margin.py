"""The margin of an order sets the shipped units' revenue against their cost.

What is being protected: `order_economics` took the revenue of the WHOLE order
(its invoices, else its line totals) and the cost of the devices shipped SO
FAR. Order 1574 on production read 55,000 PLN for 250 units against the cost of
the 120 shipped, a margin of 87.3 %, where the 120 earn 26,400 PLN and 73.6 %.
An order with nothing shipped read 100 %.

Run from `api/`, with the dev database up:
    python -m pytest tests/orders -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
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
    """One batch of 12 devices at 10 USD each, and an order for 10 at 100 PLN net."""
    proj = M.Project(name="test-order-margin", git_url="https://example.invalid/om.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="OM1", run_date="2026-05-01", status="completed", qty=12)
    db.add(run)
    db.flush()
    devices = []
    for i in range(12):
        d = M.DeviceUnit(project_id=proj.id, serial=f"OM{i:02d}", mac=f"00:00:00:00:0e:{i:02x}",
                         first_seen=datetime(2026, 5, 1, 12, i, tzinfo=UTC), condition="ok")
        db.add(d)
        db.flush()
        svc.record_event(db, d, "produced", production_run_id=run.id)
        devices.append(d)
    order = M.SalesOrder(customer=M.Customer(name="test-om-customer"), order_date="2026-06-01", currency="PLN")
    db.add(order)
    db.flush()
    line = M.SalesOrderLine(order_id=order.id, project_id=proj.id, qty_ordered=10, unit_price=100.0)
    db.add(line)
    db.flush()
    db.refresh(order)
    return {"run": run, "devices": devices, "order": order, "line": line}


def _ship(db, world, n, start=0):
    for d in world["devices"][start:start + n]:
        svc.record_event(db, d, "shipped", order_line_id=world["line"].id)
    db.flush()
    db.refresh(world["order"])


def _econ(db, world):
    return svc.order_economics(db, world["order"], {world["run"].id: 10.0}, {})


def test_a_part_shipped_order_earns_only_what_it_shipped(db, world):
    """4 of 10 shipped: they earn 400 PLN, not the order's 1,000."""
    _ship(db, world, 4)
    e = _econ(db, world)
    assert e["revenue_net"] == 1000.0, "the order's own revenue is still reported"
    assert (e["shipped_units"], e["ordered_units"]) == (4, 10)
    assert e["shipped_revenue_net"] == 400.0
    assert (e["to_ship_units"], e["to_ship_net"]) == (6, 600.0)
    assert e["margin_pln"] == pytest.approx(400.0 - e["cost_pln"], abs=0.01)
    assert e["margin_pct"] == pytest.approx((400.0 - e["cost_pln"]) / 400.0 * 100, abs=0.01)


def test_an_order_with_nothing_shipped_has_no_margin(db, world):
    """It read 100 %: the whole revenue against no cost at all."""
    e = _econ(db, world)
    assert e["shipped_units"] == 0
    assert (e["margin_pln"], e["margin_usd"], e["margin_pct"]) == (None, None, None)


def test_a_unit_above_the_ordered_quantity_earns_nothing(db, world):
    """12 shipped on a line of 10: the customer pays for 10, the 12 still cost."""
    _ship(db, world, 12)
    e = _econ(db, world)
    assert e["shipped_units"] == 10
    assert e["shipped_devices"] == 12
    assert e["shipped_revenue_net"] == 1000.0
    assert e["to_ship_units"] == 0


def test_a_fully_shipped_order_earns_what_it_invoiced(db, world):
    """Once every line is shipped the margin is the order's own: a correction
    invoice that gave a discount counts."""
    _ship(db, world, 10)
    db.add(M.OrderInvoice(order_id=world["order"].id, kind="final", number="T/OM/1",
                          issue_date="2026-06-02", net_amount=1000.0, currency="PLN"))
    db.add(M.OrderInvoice(order_id=world["order"].id, kind="correction", number="T/OM/1K",
                          issue_date="2026-06-03", net_amount=-50.0, currency="PLN"))
    db.flush()
    db.refresh(world["order"])
    e = _econ(db, world)
    assert e["revenue_basis"] == "invoices"
    assert e["shipped_revenue_net"] == 950.0
    assert e["margin_pln"] == pytest.approx(950.0 - e["cost_pln"], abs=0.01)
