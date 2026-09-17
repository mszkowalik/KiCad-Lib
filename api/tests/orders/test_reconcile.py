"""`reconcile_shelf` against a scratch order, in a transaction that is rolled back.

Decision record: docs/decisions/0027-a-stock-count-corrects-a-fifo-guess.md.

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
    """Two batches of five devices, an order for ten, one shipment that took
    all ten FIFO. Batch A is older, so FIFO emptied it first."""
    proj = M.Project(name="test-reconcile", git_url="https://example.invalid/test.git")
    db.add(proj)
    db.flush()
    runs = []
    for n, label in ((1, "A"), (2, "B")):
        r = M.ProductionRun(project_id=proj.id, label=label, run_date=f"2026-0{n}-01",
                            status="completed", qty_good=5)
        db.add(r)
        runs.append(r)
    db.flush()
    devs = {}
    for r, label in zip(runs, "AB"):
        devs[label] = []
        for i in range(5):
            d = M.DeviceUnit(project_id=proj.id, serial=f"{label}{i}", mac=f"00:00:00:00:0{r.id}:0{i}",
                             first_seen=datetime(2026, int(r.run_date[5:7]), 1, 10, i, tzinfo=UTC))
            db.add(d)
            db.flush()
            svc.record_event(db, d, "produced", production_run_id=r.id)
            devs[label].append(d)
    cust = svc.get_customer(db, "test-reconcile-customer")
    order = M.SalesOrder(customer_id=cust.id, order_ref="TEST/1", order_date="2026-03-01")
    db.add(order)
    db.flush()
    line = M.SalesOrderLine(order_id=order.id, project_id=proj.id, product="thing",
                            qty_ordered=10, unit_price=100.0)
    db.add(line)
    db.flush()
    db.refresh(order)
    svc.create_shipment(db, order, shipped_at="2026-03-05",
                        lines=[{"order_line_id": line.id, "qty": 10,
                                "run_ids": [r.id for r in runs]}], actor="test")
    db.flush()
    return {"db": db, "proj": proj, "runs": runs, "devs": devs, "order": order, "line": line}


def test_fifo_took_everything(world):
    line = world["line"]
    assert svc.line_shipped(line) == 10
    assert all(d.state == "shipped" for ds in world["devs"].values() for d in ds)


def test_a_count_frees_the_guess_and_refills_it(world):
    """Three devices turn up on the shelf. They were FIFO guesses, so they go
    back to stock and three others take their slots — the count is untouched."""
    db, line = world["db"], world["line"]
    # Put three devices back in stock so there is something to refill WITH.
    spare = world["devs"]["B"][2:]
    for d in spare:
        svc.record_event(db, d, "unshipped", shipment_id=None)
    db.flush()
    counted = world["devs"]["A"][:3]
    plan = svc.reconcile_shelf(db, counted, refill="any_batch", actor="test", dry_run=False)
    assert len(plan["freed"]) == 3
    assert len(plan["refilled"]) == 3
    assert plan["unfilled"] == []
    assert all(d.state == "in_stock" for d in counted)
    assert {r["by_device_id"] for r in plan["refilled"]} == {d.id for d in spare}
    assert svc.line_shipped(line) == 10


def test_same_batch_refill_will_not_cross_batches(world):
    """A 2024 slot is not filled by a 2026 device just because one is free."""
    db = world["db"]
    spare = world["devs"]["B"][2:]
    for d in spare:
        svc.record_event(db, d, "unshipped", shipment_id=None)
    db.flush()
    counted = world["devs"]["A"][:3]
    plan = svc.reconcile_shelf(db, counted, refill="same_batch", actor="test", dry_run=True)
    assert plan["refilled"] == []
    assert len(plan["unfilled"]) == 3


def test_nothing_to_refill_with_drops_the_count(world):
    db, line = world["db"], world["line"]
    counted = world["devs"]["A"][:3]
    plan = svc.reconcile_shelf(db, counted, refill="any_batch", keep_count=False,
                               actor="test", dry_run=False)
    assert len(plan["unfilled"]) == 3
    assert svc.line_shipped(line) == 7
    assert plan["lines"][0]["qty_shipped_after"] == 7
    assert world["order"].status == "partial"


def test_keep_count_turns_the_slot_anonymous(world):
    db, line = world["db"], world["line"]
    counted = world["devs"]["A"][:3]
    plan = svc.reconcile_shelf(db, counted, refill="any_batch", keep_count=True,
                               actor="test", dry_run=False)
    assert len(plan["unfilled"]) == 3
    assert sum(u["qty"] for u in plan["unserialized"]) == 3
    assert svc.line_shipped(line) == 10
    assert world["order"].status == "fulfilled"


def test_a_typed_shipment_is_never_overruled(world):
    """Somebody named this device by hand. A count says where it is, not who
    is wrong about it."""
    from fastapi import HTTPException

    db = world["db"]
    d = world["devs"]["A"][0]
    svc.last_event(d, "shipped").auto = False
    db.flush()
    with pytest.raises(HTTPException) as e:
        svc.reconcile_shelf(db, [d], actor="test", dry_run=True)
    assert e.value.status_code == 409
    assert d.serial in e.value.detail["devices"]


def test_dry_run_writes_nothing(world):
    db, line = world["db"], world["line"]
    counted = world["devs"]["A"][:3]
    before = svc.line_shipped(line)
    svc.reconcile_shelf(db, counted, refill="any_batch", actor="test", dry_run=True)
    assert svc.line_shipped(line) == before
    assert all(d.state == "shipped" for d in counted)


def test_a_swap_on_a_return_does_not_count_twice(world):
    """The regression `live_shipped_events` exists for: a return that corrects
    a FIFO guess reverses one delivery and makes another. Ten devices went out,
    and ten is what the line must still say afterwards."""
    db, line, proj = world["db"], world["line"], world["proj"]
    spare = M.DeviceUnit(project_id=proj.id, serial="B9", mac="00:00:00:00:09:09",
                         first_seen=datetime(2026, 2, 1, 11, 0, tzinfo=UTC))
    db.add(spare)
    db.flush()
    svc.record_event(db, spare, "produced", production_run_id=world["runs"][1].id)
    db.flush()
    assert svc.line_shipped(line) == 10
    svc.return_device(db, spare, order_line=line, reason="fault", returned_at="2026-04-01",
                      actor="test")
    db.flush()
    assert svc.line_shipped(line) == 10
    assert sum(1 for e in spare.events if e.kind == "shipped") == 1


class _Req:
    """Enough of a Request for `actor_of`."""

    class state:
        user = None


def test_the_endpoint_resolves_serials_and_defaults_to_a_dry_run(world):
    """A scan sheet carries serials, and sending one must not write anything
    until the caller has seen the plan and asked again."""
    from app.routers import orders as router

    db, line = world["db"], world["line"]
    counted = world["devs"]["A"][:2]
    body = router.ReconcileIn(serials=[d.serial for d in counted], refill="any_batch")
    assert body.dry_run is True
    plan = router.reconcile_stock(body, _Req(), db=db)
    assert {f["serial"] for f in plan["freed"]} == {d.serial for d in counted}
    assert all(d.state == "shipped" for d in counted)
    assert svc.line_shipped(line) == 10


def test_the_endpoint_rejects_a_serial_nothing_carries(world):
    from fastapi import HTTPException

    from app.routers import orders as router

    body = router.ReconcileIn(serials=["NOPE"])
    with pytest.raises(HTTPException) as e:
        router.reconcile_stock(body, _Req(), db=world["db"])
    assert e.value.status_code == 404
    assert e.value.detail["serials"] == ["NOPE"]
