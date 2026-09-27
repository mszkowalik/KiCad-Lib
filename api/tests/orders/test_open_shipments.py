"""An OPEN shipment: a box packed device by device, then sent (decision 0053).

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
    """One batch of four devices (the last one faulty), an order for three."""
    proj = M.Project(name="test-open-shipment", git_url="https://example.invalid/test.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="A", run_date="2026-01-01", status="completed")
    db.add(run)
    db.flush()
    devs = []
    for i in range(4):
        d = M.DeviceUnit(project_id=proj.id, serial=f"OPENSHIP{i:04d}",
                         mac=f"00:00:0e:{run.id // 256 % 256:02x}:{run.id % 256:02x}:{i:02x}",
                         first_seen=datetime(2026, 1, 1, 10, i, tzinfo=UTC))
        db.add(d)
        db.flush()
        svc.record_event(db, d, "produced", production_run_id=run.id)
        devs.append(d)
    devs[3].condition = "faulty"
    cust = svc.get_customer(db, "test-open-shipment-customer")
    order = M.SalesOrder(customer_id=cust.id, order_ref="TEST/OPEN", order_date="2026-03-01")
    db.add(order)
    db.flush()
    line = M.SalesOrderLine(order_id=order.id, project_id=proj.id, product="thing",
                            qty_ordered=3, unit_price=100.0)
    db.add(line)
    db.flush()
    db.refresh(order)
    return {"db": db, "devs": devs, "order": order, "line": line}


def test_packing_reserves_and_sending_ships(world):
    db, devs, order, line = world["db"], world["devs"], world["order"], world["line"]
    sh = svc.open_shipment(db, order)
    assert sh.status == "open"
    assert svc.pack_devices(db, sh, [devs[0].id, devs[1].id], actor="test") == 2
    assert {d.state for d in devs[:2]} == {"allocated"}
    # Packed is not shipped: the order has not moved.
    assert svc.line_shipped(line) == 0
    assert svc.shipment_json(db, sh)["qty"] == 2

    svc.send_shipment(db, sh, shipped_at="2026-03-10", actor="test")
    assert sh.status == "sent"
    assert {d.state for d in devs[:2]} == {"shipped"}
    assert svc.line_shipped(line) == 2
    assert order.status == "partial"
    assert [e.kind for e in devs[0].events] == ["produced", "allocated", "shipped"]


def test_unpacking_writes_history_and_returns_to_stock(world):
    db, devs, order = world["db"], world["devs"], world["order"]
    sh = svc.open_shipment(db, order)
    svc.pack_devices(db, sh, [devs[0].id], actor="test")
    svc.unpack_devices(db, sh, [devs[0].id], actor="test")
    assert devs[0].state == "in_stock"
    assert [e.kind for e in devs[0].events] == ["produced", "allocated", "unallocated"]
    assert svc.packed_devices(db, sh) == []
    # Its history names the box, so the box can no longer be deleted.
    assert svc.shipment_json(db, sh)["deletable"] is False


def test_check_names_every_refusal(world):
    db, devs, order = world["db"], world["devs"], world["order"]
    sh = svc.open_shipment(db, order)
    other = svc.open_shipment(db, order)
    svc.pack_devices(db, other, [devs[1].id], actor="test")
    svc.pack_devices(db, sh, [devs[2].id], actor="test")
    by = {c["code"]: c for c in (svc.check_device(db, sh, code) for code in
                                 ("openship0000", "OPENSHIP0001", "OPENSHIP0002", "OPENSHIP0003", "NOPE"))}
    assert by["openship0000"]["ok"] is True  # case is normalised
    assert by["OPENSHIP0001"]["reason"] == f"packed in open shipment {other.id}"
    assert by["OPENSHIP0002"]["reason"] == "already in this shipment"
    assert "faulty" in by["OPENSHIP0003"]["reason"]
    assert by["NOPE"]["reason"] == "no device carries this serial"


def test_pack_is_all_or_nothing(world):
    db, devs, order = world["db"], world["devs"], world["order"]
    sh = svc.open_shipment(db, order)
    with pytest.raises(HTTPException) as e:
        svc.pack_devices(db, sh, [devs[0].id, devs[3].id], actor="test")
    assert e.value.status_code == 409
    assert devs[0].state == "in_stock"


def test_a_packed_device_cannot_leave_on_another_shipment(world):
    db, devs, order, line = world["db"], world["devs"], world["order"], world["line"]
    sh = svc.open_shipment(db, order)
    svc.pack_devices(db, sh, [devs[0].id], actor="test")
    with pytest.raises(HTTPException) as e:
        svc.create_shipment(db, order, lines=[{"order_line_id": line.id, "device_ids": [devs[0].id]}])
    assert e.value.status_code == 409


def test_cancel_releases_everything_and_keeps_the_header(world):
    db, devs, order = world["db"], world["devs"], world["order"]
    sh = svc.open_shipment(db, order)
    svc.pack_devices(db, sh, [devs[0].id, devs[1].id], actor="test")
    assert svc.cancel_shipment(db, sh, actor="test") == 2
    assert sh.status == "cancelled"
    assert {d.state for d in devs[:2]} == {"in_stock"}
    with pytest.raises(HTTPException):
        svc.pack_devices(db, sh, [devs[2].id], actor="test")


def test_an_empty_box_cannot_be_sent(world):
    db, order = world["db"], world["order"]
    sh = svc.open_shipment(db, order)
    with pytest.raises(HTTPException) as e:
        svc.send_shipment(db, sh, actor="test")
    assert e.value.status_code == 422
