"""A unit the stock count cannot find is `missing`, and one device can leave
one delivery — against a scratch order, in a transaction that is rolled back.

Decision record: docs/decisions/0057-a-device-the-count-cannot-find-is-missing.md.

Run from `api/`, with the dev database up:
    python -m pytest tests/orders -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
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
    """One batch of eight devices, an order for four, and one shipment that
    names devices 0-3. Devices 4-7 are on the shelf."""
    proj = M.Project(name="test-missing", git_url="https://example.invalid/test.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="A", run_date="2026-01-01", status="completed")
    db.add(run)
    db.flush()
    devs = []
    for i in range(8):
        d = M.DeviceUnit(project_id=proj.id, serial=f"M{i}",
                         mac=f"00:00:01:{run.id // 256 % 256:02x}:{run.id % 256:02x}:{i:02x}",
                         first_seen=datetime(2026, 1, 1, 10, i, tzinfo=UTC))
        db.add(d)
        db.flush()
        svc.record_event(db, d, "produced", production_run_id=run.id)
        devs.append(d)
    cust = svc.get_customer(db, "test-missing-customer")
    order = M.SalesOrder(customer_id=cust.id, order_ref="TEST/M", order_date="2026-02-01")
    db.add(order)
    db.flush()
    line = M.SalesOrderLine(order_id=order.id, project_id=proj.id, product="thing",
                            qty_ordered=4, unit_price=10.0)
    db.add(line)
    db.flush()
    db.refresh(order)
    sh = svc.create_shipment(db, order, shipped_at="2026-02-05",
                             lines=[{"order_line_id": line.id, "device_ids": [d.id for d in devs[:4]]}],
                             actor="test")
    db.flush()
    return {"db": db, "proj": proj, "run": run, "devs": devs, "order": order, "line": line, "sh": sh}


def _run_row(db, run):
    return next(r for r in svc.run_stock(db, run.project_id) if r["run_id"] == run.id)


def _product_row(db, proj):
    return next(p for p in svc.product_stock(db) if p["project_id"] == proj.id)


def test_a_missing_unit_counts_in_no_stock_figure_but_is_reported(world):
    db, run, proj, d = world["db"], world["run"], world["proj"], world["devs"][4]
    before = _run_row(db, run)
    svc.mark_missing(db, d, counted_at="2026-10-02", actor="test")
    db.flush()
    row = _run_row(db, run)
    assert d.state == "missing"
    assert row["devices_in_stock"] == before["devices_in_stock"] - 1
    assert row["available"] == before["available"] - 1
    assert row["devices_missing"] == 1
    assert row["built"] == before["built"], "a missing unit was still produced: cost is unchanged"
    p = _product_row(db, proj)
    assert p["missing"] == 1 and p["in_stock"] == 3


def test_a_delivery_may_ship_a_missing_unit(world):
    """The broker proves it is at the customer: the delivery is the evidence."""
    db, order, line, d = world["db"], world["order"], world["line"], world["devs"][5]
    svc.mark_missing(db, d, actor="test")
    db.flush()
    db.refresh(order)
    svc.create_shipment(db, order, shipped_at="2026-10-02",
                        lines=[{"order_line_id": line.id, "device_ids": [d.id]}], actor="test")
    db.flush()
    assert d.state == "shipped"
    assert svc.line_shipped(line) == 5, "a delivery may exceed the order"


def test_a_missing_unit_that_is_not_ok_still_cannot_ship(world):
    db, order, line, d = world["db"], world["order"], world["line"], world["devs"][6]
    d.condition = "faulty"
    svc.mark_missing(db, d, actor="test")
    db.flush()
    db.refresh(order)
    with pytest.raises(HTTPException) as e:
        svc.create_shipment(db, order, lines=[{"order_line_id": line.id, "device_ids": [d.id]}],
                            actor="test")
    assert e.value.status_code == 409


def test_found_puts_it_back_in_stock(world):
    db, run, d = world["db"], world["run"], world["devs"][7]
    svc.mark_missing(db, d, actor="test")
    svc.mark_found(db, d, actor="test")
    db.flush()
    assert d.state == "in_stock"
    assert _run_row(db, run)["devices_missing"] == 0


def test_a_missing_unit_can_be_written_off(world):
    db, d = world["db"], world["devs"][4]
    svc.mark_missing(db, d, actor="test")
    svc.dispose_device(db, d, reason="written off after the count", actor="test")
    db.flush()
    assert d.state == "disposed"


@pytest.mark.parametrize("how", ["shipped", "allocated", "disposed"])
def test_only_an_in_stock_unit_can_be_marked_missing(world, how):
    db, order, line, devs = world["db"], world["order"], world["line"], world["devs"]
    d = devs[0] if how == "shipped" else devs[4]
    if how == "allocated":
        svc.allocate_devices(db, line, [d.id], actor="test")
    elif how == "disposed":
        svc.dispose_device(db, d, reason="x", actor="test")
    db.flush()
    with pytest.raises(HTTPException) as e:
        svc.mark_missing(db, d, actor="test")
    assert e.value.status_code == 409


def test_found_refuses_a_unit_that_is_not_missing(world):
    with pytest.raises(HTTPException) as e:
        svc.mark_found(world["db"], world["devs"][4], actor="test")
    assert e.value.status_code == 409


def test_unshipping_one_device_leaves_the_rest_of_its_shipment(world):
    db, line, sh, devs = world["db"], world["line"], world["sh"], world["devs"]
    plan = svc.unship_device(db, devs[1], actor="test")
    assert plan["dry_run"] is True and plan["shipment_id"] == sh.id
    assert devs[1].state == "shipped", "the default is a dry run"
    svc.unship_device(db, devs[1], actor="test", dry_run=False)
    db.flush()
    assert devs[1].state == "in_stock"
    assert [d.state for d in (devs[0], devs[2], devs[3])] == ["shipped"] * 3
    assert svc.line_shipped(line) == 3, "the line drops by exactly one"
    assert world["order"].status == "partial"


def test_unship_refuses_a_device_that_is_not_shipped(world):
    with pytest.raises(HTTPException) as e:
        svc.unship_device(world["db"], world["devs"][4], actor="test", dry_run=False)
    assert e.value.status_code == 409


def test_unship_refuses_a_shipment_the_device_was_not_on(world):
    with pytest.raises(HTTPException) as e:
        svc.unship_device(world["db"], world["devs"][0], shipment_id=world["sh"].id + 10_000,
                          actor="test", dry_run=False)
    assert e.value.status_code == 409


def test_an_unshipped_device_can_go_out_again_and_counts_once(world):
    """The 0028 rule this must not break: a delivery an `unshipped` event
    reversed is not a previous delivery."""
    db, order, line, d = world["db"], world["order"], world["line"], world["devs"][2]
    svc.unship_device(db, d, actor="test", dry_run=False)
    db.flush()
    db.refresh(order)
    svc.create_shipment(db, order, shipped_at="2026-10-02",
                        lines=[{"order_line_id": line.id, "device_ids": [d.id]}], actor="test")
    db.flush()
    assert svc.line_shipped(line) == 4
    assert svc.last_event(d, "shipped").replaces_device_id is None


def test_a_missing_unit_cannot_be_packed_until_it_is_found(world):
    db, order, d = world["db"], world["order"], world["devs"][4]
    svc.mark_missing(db, d, actor="test")
    db.flush()
    box = svc.open_shipment(db, order)
    db.flush()
    _, why = svc._assess(d, box, None)
    assert "found" in why
