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
    plan = svc.reconcile_shelf(db, counted, refill="any_batch", actor="test", dry_run=False)
    assert len(plan["unfilled"]) == 3
    assert svc.line_shipped(line) == 7
    assert plan["lines"][0]["qty_shipped_after"] == 7
    assert world["order"].status == "partial"


def test_a_slot_nothing_can_refill_always_lowers_the_count(world):
    """There is no second option. The freed device's own batch records that
    device, so it has no anonymous unit to put in its place (decision 0031)."""
    db, line = world["db"], world["line"]
    counted = world["devs"]["A"][:3]
    plan = svc.reconcile_shelf(db, counted, refill="any_batch", actor="test", dry_run=False)
    assert len(plan["unfilled"]) == 3
    assert "unserialized" not in plan
    assert svc.line_shipped(line) == 7
    assert world["order"].status == "partial"


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


def test_a_reversed_delivery_is_not_a_previous_delivery(world):
    """The bug this pair of fixes exists for. A count puts three devices back on
    the shelf; shipping them again on the SAME line must count three deliveries,
    not three replacements of themselves."""
    db, line, order = world["db"], world["line"], world["order"]
    counted = world["devs"]["A"][:3]
    svc.reconcile_shelf(db, counted, refill="none", actor="test", dry_run=False)
    db.flush()
    assert svc.line_shipped(line) == 7
    db.refresh(order)
    svc.create_shipment(db, order, shipped_at="2026-04-01",
                        lines=[{"order_line_id": line.id,
                                "device_ids": [d.id for d in counted]}], actor="test")
    db.flush()
    assert svc.line_shipped(line) == 10
    assert all(svc.last_event(d, "shipped").replaces_device_id is None for d in counted)


def test_a_repaired_device_re_shipped_is_still_its_own_replacement(world):
    """The rule the fix above must not break: a device that really was
    delivered, came back and went out again counts once, not twice."""
    db, line, order = world["db"], world["line"], world["order"]
    d = world["devs"]["A"][0]
    svc.return_device(db, d, order_line=line, reason="fault", returned_at="2026-04-01", actor="test")
    svc.repair_device(db, d, outcome="to_stock", repaired_at="2026-04-02", actor="test")
    db.flush()
    db.refresh(order)
    before = svc.line_shipped(line)
    svc.create_shipment(db, order, shipped_at="2026-04-03",
                        lines=[{"order_line_id": line.id, "device_ids": [d.id]}], actor="test")
    db.flush()
    assert svc.last_event(d, "shipped").replaces_device_id == d.id
    assert svc.line_shipped(line) == before


def test_a_shipment_recorded_in_error_is_reversed_whole(world):
    db, line, order = world["db"], world["line"], world["order"]
    sh = order.shipments[0]
    plan = svc.reverse_shipment(db, sh, actor="test", dry_run=True)
    assert len(plan["devices"]) == 10
    assert svc.line_shipped(line) == 10
    svc.reverse_shipment(db, sh, actor="test", dry_run=False)
    db.flush()
    assert svc.line_shipped(line) == 0
    assert all(d.state == "in_stock" for ds in world["devs"].values() for d in ds)
    assert order.status == "open"


def test_an_allocated_device_is_supply_for_the_line_it_is_held_for(world):
    """A boxed device is on the shelf and its line still asks to be filled.
    Counting it as demand but not as supply builds it twice."""
    db, line, order = world["db"], world["line"], world["order"]
    sh = order.shipments[0]
    svc.reverse_shipment(db, sh, actor="test", dry_run=False)
    db.flush()
    db.refresh(order)
    proj_id = world["proj"].id
    before = next(r for r in svc.project_demand(db, proj_id) if r["project_id"] == proj_id)
    assert (before["open"], before["on_shelf"]) == (10, 10)
    svc.allocate_devices(db, line, [d.id for d in world["devs"]["A"]], actor="test")
    db.flush()
    after = next(r for r in svc.project_demand(db, proj_id) if r["project_id"] == proj_id)
    assert (after["open"], after["on_shelf"]) == (10, 10)
    assert after["shortfall"] == 0


def test_an_allocation_to_a_closed_line_is_not_supply(world):
    """The line is fulfilled, so neither its demand nor those devices count."""
    db, line, order = world["db"], world["line"], world["order"]
    proj_id = world["proj"].id
    row = next(r for r in svc.project_demand(db, proj_id) if r["project_id"] == proj_id)
    assert (row["open"], row["on_shelf"]) == (0, 0)


def test_a_shipment_can_be_recorded_from_serials(world):
    """A scan sheet names devices by the string on the label."""
    from app.routers import orders as router

    db, line, order = world["db"], world["line"], world["order"]
    sh = order.shipments[0]
    svc.reverse_shipment(db, sh, actor="test", dry_run=False)
    db.flush()
    db.refresh(order)
    body = router.ShipmentIn(shipped_at="2026-04-01",
                             lines=[router.ShipmentLineIn(order_line_id=line.id,
                                                          serials=["A0", "A1", "A2"])])
    router.create_shipment(order.id, body, _Req(), db=db)
    db.flush()
    assert svc.line_shipped(line) == 3


def test_a_reversed_shipment_says_it_cannot_be_deleted(world):
    db, order = world["db"], world["order"]
    sh = order.shipments[0]
    assert svc.shipment_json(db, sh)["deletable"] is False
    svc.reverse_shipment(db, sh, actor="test", dry_run=False)
    db.flush()
    row = svc.shipment_json(db, sh)
    assert row["devices"] == [] and row["qty"] == 0
    assert row["reversed"] == 10
    assert row["deletable"] is False


def test_a_device_moves_to_the_batch_it_was_really_built_in(world):
    """The bench had the wrong batch selected. Decision 0029."""
    db = world["db"]
    a, bnew = world["runs"]
    devs = world["devs"]["A"][:2]
    assert all(d.production_run_id == a.id for d in devs)
    plan = svc.rebatch_devices(db, bnew, [d.id for d in devs], actor="test", dry_run=True)
    assert [m["from_run_id"] for m in plan["moved"]] == [a.id, a.id]
    assert all(d.production_run_id == a.id for d in devs)  # a dry run moves nothing

    svc.rebatch_devices(db, bnew, [d.id for d in devs], actor="test", note="bench picked wrong",
                        dry_run=False)
    db.flush()
    assert all(d.production_run_id == bnew.id for d in devs)
    for d in devs:
        ev = next(e for e in d.events if e.kind == "produced")
        assert ev.production_run_id == bnew.id
        assert f"moved from batch {a.id}" in ev.note
    stock = {r["run_id"]: r for r in svc.run_stock(db, world["proj"].id)}
    assert stock[a.id]["devices_produced"] == 3
    assert stock[bnew.id]["devices_produced"] == 7


def test_rebatch_says_why_it_skipped_a_device(world):
    db = world["db"]
    a, bnew = world["runs"]
    already = world["devs"]["B"][0]
    plan = svc.rebatch_devices(db, bnew, [already.id, 999999], actor="test", dry_run=True)
    assert plan["moved"] == []
    reasons = {s.get("device_id"): s["reason"] for s in plan["skipped"]}
    assert reasons[already.id] == "already in this batch"
    assert reasons[999999] == "no such device"


def test_rebatch_refuses_a_device_from_another_project(world):
    db = world["db"]
    other = M.Project(name="test-reconcile-other", git_url="https://example.invalid/o.git")
    db.add(other)
    db.flush()
    stray = M.DeviceUnit(project_id=other.id, serial="ZZ9", mac="00:00:00:99:99:99",
                         first_seen=datetime(2026, 1, 1, tzinfo=UTC))
    db.add(stray)
    db.flush()
    plan = svc.rebatch_devices(db, world["runs"][1], [stray.id], actor="test", dry_run=True)
    assert plan["moved"] == []
    assert "another" not in plan["skipped"][0]["reason"]
    assert "belongs to project" in plan["skipped"][0]["reason"]


def test_good_units_counts_the_devices_not_the_boards_ordered(world):
    """Decision 0030. `qty` is boards ORDERED from JLC; a batch routinely
    yields a different number, and every per-device figure must divide by what
    passed."""
    from app.services import run_actuals

    db = world["db"]
    a = world["runs"][0]
    a.qty, a.plan_qty, a.qty_good = 3, None, None  # the run says three boards
    db.flush()
    assert run_actuals.good_units(db, a) == 5  # five devices of it are recorded

    counts = run_actuals.produced_counts(db, [r.id for r in world["runs"]])
    assert counts[a.id] == 5
    assert run_actuals.good_units(db, a, counts) == 5


def test_good_units_falls_back_only_for_a_batch_with_no_devices(world):
    from app.services import run_actuals

    db = world["db"]
    legacy = M.ProductionRun(project_id=world["proj"].id, label="legacy", run_date="2023-01-01",
                             status="completed", qty=40)
    db.add(legacy)
    db.flush()
    assert run_actuals.good_units(db, legacy) == 40
    legacy.qty_good = 37
    db.flush()
    assert run_actuals.good_units(db, legacy) == 37


def test_rebatching_moves_the_cost_basis_with_the_device(world):
    """The point of deriving it: 0029 moved a device, so 0030's denominator
    follows without anybody retyping a quantity."""
    from app.services import run_actuals

    db = world["db"]
    a, b = world["runs"]
    assert (run_actuals.good_units(db, a), run_actuals.good_units(db, b)) == (5, 5)
    svc.rebatch_devices(db, b, [d.id for d in world["devs"]["A"][:2]], actor="test", dry_run=False)
    db.flush()
    assert (run_actuals.good_units(db, a), run_actuals.good_units(db, b)) == (3, 7)


def test_naming_the_batch_behind_unserialised_units_draws_them_down(world):
    """A prototype batch reconstructed after the delivery was recorded: until
    the shipment line names it, the batch counts the units as stock it holds."""
    from app.routers import orders as router

    db, line, order = world["db"], world["line"], world["order"]
    proto = M.ProductionRun(project_id=world["proj"].id, label="prototypes", run_date="2023-12-25",
                            status="completed", qty=20)
    db.add(proto)
    db.flush()
    db.refresh(order)
    svc.create_shipment(db, order, shipped_at="2023-12-30",
                        lines=[{"order_line_id": line.id, "qty_unserialized": 20}], actor="test")
    db.flush()
    stock = {r["run_id"]: r for r in svc.run_stock(db, world["proj"].id)}
    assert stock[proto.id]["legacy_stock"] == 20  # nothing has drawn it down yet

    sl = (db.query(M.ShipmentLine)
          .filter(M.ShipmentLine.order_line_id == line.id,
                  M.ShipmentLine.qty_unserialized == 20).one())
    out = router.patch_shipment_line(sl.id, router.ShipmentLinePatch(source_run_id=proto.id),
                                     _Req(), db=db)
    assert out["source_run_id"] == proto.id
    stock = {r["run_id"]: r for r in svc.run_stock(db, world["proj"].id)}
    assert stock[proto.id]["legacy_stock"] == 0
    assert stock[proto.id]["unserialized_shipped"] == 20
    assert stock[proto.id]["overdrawn"] == 0


def test_a_shipment_line_cannot_name_another_project_s_batch(world):
    from fastapi import HTTPException

    from app.routers import orders as router

    db, line, order = world["db"], world["line"], world["order"]
    other = M.Project(name="test-reconcile-other-2", git_url="https://example.invalid/o2.git")
    db.add(other)
    db.flush()
    alien = M.ProductionRun(project_id=other.id, label="alien", run_date="2024-01-01",
                            status="completed", qty=5)
    db.add(alien)
    db.flush()
    db.refresh(order)
    svc.create_shipment(db, order, shipped_at="2024-01-02",
                        lines=[{"order_line_id": line.id, "qty_unserialized": 2}], actor="test")
    db.flush()
    sl = (db.query(M.ShipmentLine)
          .filter(M.ShipmentLine.order_line_id == line.id,
                  M.ShipmentLine.qty_unserialized == 2).one())
    with pytest.raises(HTTPException) as e:
        router.patch_shipment_line(sl.id, router.ShipmentLinePatch(source_run_id=alien.id),
                                   _Req(), db=db)
    assert e.value.status_code == 422


def test_a_batch_that_records_devices_has_no_anonymous_units(world):
    """The guard that would have stopped 40 impossible units on 2026-09-17."""
    from fastapi import HTTPException

    db, line, order = world["db"], world["line"], world["order"]
    real = world["runs"][0]  # five device records
    db.refresh(order)
    with pytest.raises(HTTPException) as e:
        svc.create_shipment(db, order, shipped_at="2026-04-01",
                            lines=[{"order_line_id": line.id, "qty_unserialized": 2,
                                    "source_run_id": real.id}], actor="test")
    assert e.value.status_code == 409
    assert e.value.detail["device_records"] == 5
    assert e.value.detail["label"] == real.label


def test_a_legacy_batch_still_hands_out_anonymous_units(world):
    db, line, order = world["db"], world["line"], world["order"]
    legacy = M.ProductionRun(project_id=world["proj"].id, label="pre-flasher", run_date="2023-01-01",
                             status="completed", qty=9)
    db.add(legacy)
    db.flush()
    db.refresh(order)
    svc.create_shipment(db, order, shipped_at="2023-02-01",
                        lines=[{"order_line_id": line.id, "qty_unserialized": 4,
                                "source_run_id": legacy.id}], actor="test")
    db.flush()
    stock = {r["run_id"]: r for r in svc.run_stock(db, world["proj"].id)}
    assert stock[legacy.id]["legacy_stock"] == 5
    assert stock[legacy.id]["overdrawn"] == 0


def test_a_count_no_longer_offers_to_invent_the_missing_unit(world):
    """`keep_count` invented the unit and left `overdrawn` to report it later.
    It is gone: the count falls instead (decision 0031)."""
    db = world["db"]
    counted = world["devs"]["A"][:2]
    plan = svc.reconcile_shelf(db, counted, refill="none", actor="test", dry_run=True)
    assert len(plan["unfilled"]) == 2
    assert plan["lines"][0]["qty_shipped_after"] == plan["lines"][0]["qty_shipped_before"] - 2
