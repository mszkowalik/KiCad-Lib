"""Shipments and the shelf, against a scratch order, in a transaction that is
rolled back.

Decision records: docs/decisions/0032-a-shipment-names-its-devices.md and
docs/decisions/0049-a-delivery-names-its-devices-and-nothing-else.md. The file
was named for `reconcile_shelf`, which decision 0032 removed — a stock count
that removes guesses by writing new ones is not a correction.

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
    """Two batches of five devices, an order for ten, one shipment carrying all
    ten by name, oldest first — batch A before batch B. The delivery used to be
    written as `qty: 10` and let the platform choose; it now names its devices,
    so the fixture spells out the same ten in the same order."""
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
            # A MAC is 17 characters and the column is varchar(20), so the run
            # id must NOT be interpolated raw: this read "00:00:00:00:0{id}:0{i}"
            # and overflowed the moment a run took a four-digit id (2026-09-19).
            # Two bytes of the id, wrapped, keeps it a MAC and keeps it unique.
            d = M.DeviceUnit(project_id=proj.id, serial=f"{label}{i}",
                             mac=f"00:00:00:{r.id // 256 % 256:02x}:{r.id % 256:02x}:{i:02x}",
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
                        lines=[{"order_line_id": line.id,
                                "device_ids": [d.id for d in devs["A"] + devs["B"]]}],
                        actor="test")
    db.flush()
    return {"db": db, "proj": proj, "runs": runs, "devs": devs, "order": order, "line": line}


def test_fifo_took_everything(world):
    line = world["line"]
    assert svc.line_shipped(line) == 10
    assert all(d.state == "shipped" for ds in world["devs"].values() for d in ds)


class _Req:
    """Enough of a Request for `actor_of`."""

    class state:
        user = None


def test_a_reversed_delivery_is_not_a_previous_delivery(world):
    """The bug this pair of fixes exists for. Three deliveries are reversed;
    shipping those same devices again on the SAME line must count three
    deliveries, not three replacements of themselves."""
    db, line, order = world["db"], world["line"], world["order"]
    counted = world["devs"]["A"][:3]
    for d in counted:
        svc.record_event(db, d, "unshipped", actor="test",
                         shipment_id=svc.last_event(d, "shipped").shipment_id, auto=False,
                         note="recorded in error")
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


def test_a_shipment_refuses_a_quantity_with_a_batch_behind_it(world):
    """`qty` was already refused; `qty_unserialized` was the same artefact
    wearing a batch, and it slipped through the same function.

    Decision 0032 removed the migration that MINTED these and left the manual
    write path open. Three survived — all prototype batches, each double-counted
    against its own placeholders: run 18 held 5 units `in_stock` AND a line
    claiming 5 shipped from run 18. A batch behind a number does not make it an
    observation (user decision 2026-09-20, decision 0049).
    """
    from fastapi import HTTPException

    db, line, order = world["db"], world["line"], world["order"]
    legacy = M.ProductionRun(project_id=world["proj"].id, label="pre-flasher",
                             run_date="2023-01-01", status="completed", qty=9)
    db.add(legacy)
    db.flush()
    db.refresh(order)
    # THERE IS NO QUANTITY FIELD. Not `qty`, not `qty_unserialized`. A parameter
    # that is never valid does not belong on the schema, in the OpenAPI document
    # or in a generated client, so the SCHEMA refuses one and names it
    # (decision 0049).
    from pydantic import ValidationError

    from app.routers.orders import ShipmentLineIn

    assert not {"qty", "qty_unserialized", "source_run_id", "run_ids"} \
        & set(ShipmentLineIn.model_fields)
    for bad in ("qty", "qty_unserialized", "source_run_id"):
        with pytest.raises(ValidationError) as ve:
            ShipmentLineIn(order_line_id=line.id, **{bad: 4})
        assert bad in str(ve.value), f"{bad} must be named in the refusal"

    # And the service still refuses to move nothing, which is what a caller that
    # reached past the schema would otherwise get away with.
    with pytest.raises(HTTPException) as exc:
        svc.create_shipment(db, order, shipped_at="2023-02-01",
                            lines=[{"order_line_id": line.id}], actor="test")
    assert exc.value.status_code == 422
    assert "serial" in str(exc.value.detail).lower()


def test_a_batch_with_no_device_records_holds_no_stock(world):
    """It used to hold its typed quantity as a pool an anonymous shipment could
    draw from. That pool is gone: record the devices, even as placeholders
    (decision 0039), and they count like any other.

    `built` was the last survivor of that pool. It fell back to the typed
    quantity, so such a batch still PUT UNITS ON THE SHELF CARD while no serial
    could ever be produced for one of them (user decision 2026-09-21). The typed
    quantity stays visible as `qty_recorded`, beside built, to be compared.
    """
    db = world["db"]
    legacy = M.ProductionRun(project_id=world["proj"].id, label="typed-only",
                             run_date="2023-01-01", status="completed", qty=9)
    db.add(legacy)
    db.flush()
    stock = {r["run_id"]: r for r in svc.run_stock(db, world["proj"].id)}
    row = stock[legacy.id]
    assert row["devices_produced"] == 0
    assert row["built"] == 0
    assert row["qty_recorded"] == 9
    assert row["stock"] == 0 and row["available"] == 0
    assert "legacy_stock" not in row and "unserialized_shipped" not in row


def test_the_shipment_line_table_is_gone(world):
    """It existed only to carry a quantity. Nothing else referenced it — a
    shipment's content is the `shipped` events pointing at it."""
    assert not hasattr(M, "ShipmentLine")
    assert not hasattr(M.Shipment, "lines") or "lines" not in M.Shipment.__mapper__.relationships


def test_a_shipment_will_not_take_a_device_that_is_not_ok(world):
    """Condition is what the device IS; state is where it is. A faulty unit sits
    in stock, is counted there, and cannot leave. Before `condition` existed the
    only way to stop one shipping was to file it `disposed`, which said it had
    been destroyed."""
    from fastapi import HTTPException

    db, proj, order, line = world["db"], world["proj"], world["order"], world["line"]
    bad = M.DeviceUnit(project_id=proj.id, serial="FAULTY1", mac="00:00:00:00:fa:01",
                       first_seen=datetime(2026, 2, 1, 12, 0, tzinfo=UTC), condition="faulty")
    db.add(bad)
    db.flush()
    svc.record_event(db, bad, "produced", production_run_id=world["runs"][1].id)
    db.flush()
    assert bad.state == "in_stock"
    with pytest.raises(HTTPException) as e:
        svc.create_shipment(db, order, shipped_at="2026-05-01",
                            lines=[{"order_line_id": line.id, "device_ids": [bad.id]}],
                            actor="test")
    assert e.value.status_code == 409
    assert e.value.detail["condition"] == "faulty"
    assert bad.state == "in_stock"


def test_a_faulty_unit_is_stock_but_not_available(world):
    """It must stay visible. A unit that cannot be sold but is on the shelf is
    still ours, still counted, and still worth something."""
    db, proj = world["db"], world["proj"]
    run = world["runs"][1]
    bad = M.DeviceUnit(project_id=proj.id, serial="FAULTY2", mac="00:00:00:00:fa:02",
                       first_seen=datetime(2026, 2, 1, 12, 5, tzinfo=UTC), condition="faulty")
    db.add(bad)
    db.flush()
    svc.record_event(db, bad, "produced", production_run_id=run.id)
    db.flush()
    row = next(r for r in svc.run_stock(db, proj.id) if r["run_id"] == run.id)
    assert row["devices_in_stock"] >= 1
    assert row["devices_held"] == {"faulty": 1}
    assert row["devices_available"] == row["devices_in_stock"] - 1


def test_a_quantity_with_no_serials_is_refused(world):
    """A shipment is a set of serials, not a number. A quantity behind which no
    device is named is a guess, and a guess cannot be told from an observation
    once it is written."""
    from fastapi import HTTPException

    db, order, line = world["db"], world["order"], world["line"]
    with pytest.raises(HTTPException) as e:
        svc.create_shipment(db, order, shipped_at="2026-05-02",
                            lines=[{"order_line_id": line.id, "qty": 3,
                                    "run_ids": [r.id for r in world["runs"]]}], actor="test")
    assert e.value.status_code == 422
    assert "name the devices" in e.value.detail["error"]


def test_the_shelf_payload_carries_no_quantity_counting_path(world):
    """What the Orders page reads. Every key that described the second counting
    path is gone — including `overdrawn`, which the route went on summing after
    `run_stock` stopped emitting it and would have answered 500."""
    from app.routers import orders as router

    db, proj = world["db"], world["proj"]
    payload = router.finished_stock(project_id=proj.id, db=db)
    gone = {"legacy_stock", "overdrawn", "unserialized_shipped"}
    assert gone.isdisjoint(payload["totals"])
    for row in payload["runs"]:
        assert gone.isdisjoint(row), f"batch {row['run_id']} still counts without serials"
        assert row["stock"] == row["devices_in_stock"]
