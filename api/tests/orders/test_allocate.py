"""Reserving devices for an order line, by id or by scanned serial (decision 0003).

Run from `api/`, with the dev database up:
    python -m pytest tests/orders/test_allocate.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import orders as router
from app.services import orders as svc


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


def _device(db, proj, run, serial, i):
    d = M.DeviceUnit(project_id=proj.id, serial=serial, mac=f"00:00:0f:{proj.id % 256:02x}:{run.id % 256:02x}:{i:02x}",
                     first_seen=datetime(2026, 1, 1, 10, i, tzinfo=UTC))
    db.add(d)
    db.flush()
    svc.record_event(db, d, "produced", production_run_id=run.id)
    return d


@pytest.fixture
def world(db: Session):
    """Three devices of one project, one of another, and an order for the first."""
    proj = M.Project(name="test-allocate", git_url="https://example.invalid/allocate.git")
    other = M.Project(name="test-allocate-other", git_url="https://example.invalid/allocate-other.git")
    db.add_all([proj, other])
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="A", run_date="2026-01-01", status="completed")
    run2 = M.ProductionRun(project_id=other.id, label="B", run_date="2026-01-01", status="completed")
    db.add_all([run, run2])
    db.flush()
    devs = [_device(db, proj, run, f"ALLOC{i:04d}", i) for i in range(3)]
    foreign = _device(db, other, run2, "ALLOCOTHER", 9)
    cust = svc.get_customer(db, "test-allocate-customer")
    order = M.SalesOrder(customer_id=cust.id, order_ref="TEST/ALLOC", order_date="2026-03-01")
    db.add(order)
    db.flush()
    line = M.SalesOrderLine(order_id=order.id, project_id=proj.id, product="thing", qty_ordered=3, unit_price=100.0)
    db.add(line)
    db.flush()
    db.refresh(order)
    return {"db": db, "devs": devs, "foreign": foreign, "order": order, "line": line, "project": proj, "run": run}


def _allocate(world, **body):
    return router.allocate(world["order"].id, router.AllocateIn(order_line_id=world["line"].id, **body),
                           _Req(), db=world["db"])


def test_a_scanned_serial_reserves_the_device_it_names(world):
    out = _allocate(world, serials=["ALLOC0000", "ALLOC0001"])
    assert [world["devs"][i].state for i in range(3)] == ["allocated", "allocated", "in_stock"]
    assert out["lines"][0]["qty_allocated"] == 2


def test_an_id_and_a_serial_for_one_device_reserve_it_once(world):
    devs = world["devs"]
    _allocate(world, device_ids=[devs[0].id], serials=["ALLOC0000"])
    assert [e.kind for e in devs[0].events] == ["produced", "allocated"]


def test_a_serial_nothing_carries_is_named_and_nothing_is_written(world):
    with pytest.raises(HTTPException) as e:
        _allocate(world, serials=["ALLOC0000", "NOPE-1"])
    assert e.value.status_code == 404 and "NOPE-1" in e.value.detail["error"]
    assert world["devs"][0].state == "in_stock"


def test_a_device_of_another_project_is_refused(world):
    with pytest.raises(HTTPException) as e:
        _allocate(world, serials=["ALLOCOTHER"])
    assert e.value.status_code == 422 and "another project" in e.value.detail


def test_a_device_not_in_stock_is_refused_by_name(world):
    _allocate(world, serials=["ALLOC0000"])
    with pytest.raises(HTTPException) as e:
        _allocate(world, serials=["ALLOC0000"])
    assert e.value.status_code == 409 and "ALLOC0000" in e.value.detail


def test_an_empty_list_is_refused(world):
    with pytest.raises(HTTPException) as e:
        _allocate(world)
    assert e.value.status_code == 422


def _release(world, **body):
    return router.release(world["order"].id, router.AllocateIn(order_line_id=world["line"].id, **body),
                          _Req(), db=world["db"])


def _figures(world) -> dict:
    """Every figure a reservation moves: the line, the shelf and the demand."""
    db, project = world["db"], world["project"]
    line = svc.order_json(db, world["order"], with_detail=True)["lines"][0]
    return {"line": {k: line[k] for k in ("qty_allocated", "qty_open", "qty_shipped", "reserved_devices")},
            "states": [d.state for d in world["devs"]],
            "stock": svc.run_stock(db, project.id),
            "products": [p for p in svc.product_stock(db) if p["project_id"] == project.id],
            "demand": svc.project_demand(db, project.id)}


def _second_order(world):
    """A second order for the same project, with its own line."""
    db = world["db"]
    cust = svc.get_customer(db, "test-allocate-customer")
    order = M.SalesOrder(customer_id=cust.id, order_ref="TEST/ALLOC2", order_date="2026-03-02")
    db.add(order)
    db.flush()
    line = M.SalesOrderLine(order_id=order.id, project_id=world["project"].id, product="thing", qty_ordered=1,
                            unit_price=100.0)
    db.add(line)
    db.flush()
    db.refresh(order)
    return order, line


def test_release_returns_the_device_to_stock(world):
    db, devs = world["db"], world["devs"]
    _allocate(world, serials=["ALLOC0000", "ALLOC0001"])
    out = _release(world, serials=["ALLOC0000"], device_ids=[devs[0].id])
    assert [d.state for d in devs] == ["in_stock", "allocated", "in_stock"]
    # The reservation and its release both stay in the history, once each.
    assert [e.kind for e in devs[0].events] == ["produced", "allocated", "unallocated"]
    ev = devs[0].events[-1]
    assert ev.order_line_id == world["line"].id and ev.shipment_id is None
    assert out["lines"][0]["qty_allocated"] == 1
    assert out["lines"][0]["reserved_devices"] == [{"device_id": devs[1].id, "serial": "ALLOC0001"}]
    row = db.query(M.AuditLog).filter_by(action="order.release", entity_id=str(world["order"].id)).one()
    assert row.details == {"line_id": world["line"].id, "devices": 1}


def test_reserve_then_release_leaves_the_counts_as_they_were(world):
    before = _figures(world)
    _allocate(world, serials=["ALLOC0000", "ALLOC0001"])
    assert _figures(world) != before
    _release(world, serials=["ALLOC0000", "ALLOC0001"])
    assert _figures(world) == before


def test_release_refuses_a_device_of_another_order(world):
    devs = world["devs"]
    other, other_line = _second_order(world)
    router.allocate(other.id, router.AllocateIn(order_line_id=other_line.id, serials=["ALLOC0002"]), _Req(),
                    db=world["db"])
    with pytest.raises(HTTPException) as e:
        _release(world, serials=["ALLOC0002"])
    assert e.value.status_code == 409 and e.value.detail == (
        "device ALLOC0002 is reserved on another order, not on this line")
    assert devs[2].state == "allocated"
    assert devs[2].events[-1].kind == "allocated"


def test_release_refuses_a_device_of_another_line_of_this_order(world):
    db = world["db"]
    line2 = M.SalesOrderLine(order_id=world["order"].id, project_id=world["project"].id, product="other",
                             qty_ordered=1, unit_price=1.0)
    db.add(line2)
    db.flush()
    db.refresh(world["order"])
    router.allocate(world["order"].id, router.AllocateIn(order_line_id=line2.id, serials=["ALLOC0000"]), _Req(), db=db)
    with pytest.raises(HTTPException) as e:
        _release(world, serials=["ALLOC0000"])
    assert "another line of this order" in e.value.detail


def test_release_refuses_a_device_nobody_reserved(world):
    with pytest.raises(HTTPException) as e:
        _release(world, serials=["ALLOC0000"])
    assert e.value.status_code == 409 and e.value.detail == "device ALLOC0000 is in_stock, not reserved"


def test_release_is_all_or_nothing(world):
    devs = world["devs"]
    _allocate(world, serials=["ALLOC0000"])
    with pytest.raises(HTTPException):
        _release(world, serials=["ALLOC0000", "ALLOC0001"])
    assert devs[0].state == "allocated"


def test_release_refuses_a_packed_device_and_names_its_box(world):
    db, devs = world["db"], world["devs"]
    sh = svc.open_shipment(db, world["order"])
    svc.pack_devices(db, sh, [devs[0].id], actor="test")
    with pytest.raises(HTTPException) as e:
        _release(world, serials=["ALLOC0000"])
    assert e.value.status_code == 409 and f"open shipment {sh.id}" in e.value.detail
    assert svc.packed_in(devs[0]) == sh.id
    # It counts as allocated on the line, and the order page cannot release it.
    line = svc.order_json(db, world["order"])["lines"][0]
    assert line["qty_allocated"] == 1 and line["reserved_devices"] == []


def test_release_on_a_cancelled_order(world):
    _allocate(world, serials=["ALLOC0000"])
    world["order"].cancelled = True
    world["db"].flush()
    _release(world, serials=["ALLOC0000"])
    assert world["devs"][0].state == "in_stock"


def test_release_of_nothing_is_refused(world):
    with pytest.raises(HTTPException) as e:
        _release(world)
    assert e.value.status_code == 422


def test_a_device_reserved_on_this_order_goes_into_its_box_on_its_own_line(world):
    """Pack is the only way a delivery is written, so a reservation must reach it."""
    db, devs = world["db"], world["devs"]
    line2 = M.SalesOrderLine(order_id=world["order"].id, project_id=world["project"].id, product="other",
                             qty_ordered=1, unit_price=1.0)
    db.add(line2)
    db.flush()
    db.refresh(world["order"])
    router.allocate(world["order"].id, router.AllocateIn(order_line_id=line2.id, serials=["ALLOC0000"]), _Req(), db=db)
    sh = svc.open_shipment(db, world["order"])
    # Two lines carry this product, and the reservation says which one it goes on.
    assert svc.check_device(db, sh, "ALLOC0000") | {"ok": True, "order_line_id": line2.id} == \
        svc.check_device(db, sh, "ALLOC0000")
    svc.pack_devices(db, sh, [devs[0].id], actor="test")
    svc.send_shipment(db, sh, shipped_at="2026-03-10", actor="test")
    assert devs[0].state == "shipped"
    assert svc.line_shipped(line2) == 1


def test_a_device_reserved_on_another_order_stays_out_of_this_box(world):
    db = world["db"]
    other, other_line = _second_order(world)
    router.allocate(other.id, router.AllocateIn(order_line_id=other_line.id, serials=["ALLOC0000"]), _Req(), db=db)
    sh = svc.open_shipment(db, world["order"])
    got = svc.check_device(db, sh, "ALLOC0000")
    assert got["ok"] is False and got["reason"] == "reserved on another order — release it on that order first"


def test_linking_a_device_to_a_batch_has_a_dry_run(world):
    db = world["db"]
    d = M.DeviceUnit(project_id=world["project"].id, serial="LINK-01", mac="00:00:00:00:aa:01",
                     first_seen=datetime(2026, 2, 5, 10, tzinfo=UTC))
    db.add(d)
    db.flush()
    body = router.ProducedIn(serials=["LINK-01"], dry_run=True)
    assert router.link_produced(world["run"].id, body, _Req(), db=db)["linked"] == 1
    db.expire_all()
    assert db.get(M.DeviceUnit, d.id).production_run_id is None
    with pytest.raises(HTTPException) as e:
        router.link_produced(world["run"].id, router.ProducedIn(), _Req(), db=db)
    assert e.value.status_code == 422


def test_a_snapshot_a_batch_uses_is_not_deleted(world):
    from app.routers import projects as pr

    db = world["db"]
    snap = M.ProjectSnapshot(project_id=world["project"].id, sha="a" * 40, status="ready")
    db.add(snap)
    db.flush()
    world["run"].snapshot_id = snap.id
    db.flush()
    with pytest.raises(HTTPException) as e:
        pr.delete_snapshot(snap.id, db=db)
    assert e.value.status_code == 409 and world["run"].label in e.value.detail


# ------------------------------------------------------- warranty replacements


def _box(world, *devices):
    sh = svc.open_shipment(world["db"], world["order"])
    svc.pack_devices(world["db"], sh, [d.id for d in devices], actor="t")
    return sh


def _delivered(world, device):
    svc.send_shipment(world["db"], _box(world, device), shipped_at="2026-03-02", actor="t")


def test_a_replacement_does_not_count_against_the_ordered_quantity(world):
    db, old, new = world["db"], world["devs"][0], world["devs"][1]
    _delivered(world, old)
    sh = _box(world, new)
    svc.mark_replacement(db, sh, new.id, old.serial, actor="t")
    assert svc.packed_devices(db, sh)[0][0].replaces_device_id == old.id
    svc.send_shipment(db, sh, shipped_at="2026-03-03", actor="t")
    db.flush()
    db.refresh(world["line"])
    line = next(li for li in svc.order_json(db, world["order"], with_detail=True)["lines"] if li["id"] == world["line"].id)
    assert (line["qty_shipped"], line["qty_replacements"]) == (1, 1)
    assert new.events[-1].kind == "shipped" and new.events[-1].replaces_device_id == old.id


def test_a_packed_device_with_no_statement_still_counts(world):
    db, a, b = world["db"], world["devs"][0], world["devs"][1]
    _delivered(world, a)
    sh = _box(world, b)
    svc.mark_replacement(db, sh, b.id, a.serial, actor="t")
    svc.mark_replacement(db, sh, b.id, "", actor="t")
    assert svc.packed_in(b) == sh.id and svc.packed_devices(db, sh)[0][0].replaces_device_id is None
    svc.send_shipment(db, sh, shipped_at="2026-03-03", actor="t")
    assert b.events[-1].replaces_device_id is None


@pytest.mark.parametrize("name,why", [("never", "was not delivered"), ("nobody", "no device"), ("self", "cannot replace itself"),
                                      ("foreign", "another product")])
def test_a_wrong_device_to_replace_is_refused_by_name(world, name, why):
    db, new = world["db"], world["devs"][1]
    code = {"never": world["devs"][2].serial, "nobody": "NO-SUCH-SERIAL", "self": new.serial,
            "foreign": world["foreign"].serial}[name]
    sh = _box(world, new)
    with pytest.raises(HTTPException) as e:
        svc.mark_replacement(db, sh, new.id, code, actor="t")
    assert why in str(e.value.detail)


def test_a_device_is_replaced_once(world):
    db, old, first, second = world["db"], world["devs"][0], world["devs"][1], world["devs"][2]
    _delivered(world, old)
    sh = _box(world, first)
    svc.mark_replacement(db, sh, first.id, old.serial, actor="t")
    svc.send_shipment(db, sh, shipped_at="2026-03-03", actor="t")
    sh2 = _box(world, second)
    with pytest.raises(HTTPException) as e:
        svc.mark_replacement(db, sh2, second.id, old.serial, actor="t")
    assert "already" in str(e.value.detail)


def test_only_a_device_in_this_box_can_be_a_replacement(world):
    db, a, b = world["db"], world["devs"][0], world["devs"][1]
    _delivered(world, a)
    sh = _box(world, a if False else world["devs"][2])
    with pytest.raises(HTTPException) as e:
        svc.mark_replacement(db, sh, b.id, a.serial, actor="t")
    assert e.value.status_code == 409
