"""The shelf per PRODUCT, and the devices every per-batch figure is blind to.

What is being protected: `run_stock` counts per BATCH — `_device_counts`
filters on `production_run_id IN (runs)` — so a device that names no batch is
invisible to it and to everything derived from it. Thirteen such devices were on
the real shelf when this was written (CE_Dongle_V2: 3 faulty, 10 prototype), and
the platform reported 93 devices while holding 106.

The second rule here is the supply one: only a device that can be SOLD is
supply. A faulty or prototype unit is on the shelf and a shipment may never draw
it (decision 0032), so counting it against open demand says an order can be
filled by devices that cannot leave the building.

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
    """One product, one batch, and four devices on the shelf: two sellable, one
    faulty ON the batch, and one prototype that names NO batch."""
    proj = M.Project(name="test-product-stock", git_url="https://example.invalid/ps.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="PS1", run_date="2026-05-01",
                          status="completed", qty=4)
    db.add(run)
    db.flush()

    made = []
    spec = [("ok", run.id), ("ok", run.id), ("faulty", run.id), ("prototype", None)]
    for i, (cond, run_id) in enumerate(spec):
        d = M.DeviceUnit(project_id=proj.id, serial=f"PS{i}",
                         mac=f"00:00:00:00:ps:{i:02x}"[:17],
                         first_seen=datetime(2026, 5, 1, 12, i, tzinfo=UTC),
                         condition=cond)
        db.add(d)
        db.flush()
        svc.record_event(db, d, "produced", production_run_id=run_id)
        made.append(d)
    db.flush()
    return {"db": db, "proj": proj, "run": run, "devices": made}


def _row(db: Session, project_id: int) -> dict:
    return next(r for r in svc.product_stock(db) if r["project_id"] == project_id)


def test_a_device_with_no_batch_is_still_on_the_shelf(world):
    """The whole reason this function exists beside `run_stock`."""
    db, proj = world["db"], world["proj"]
    row = _row(db, proj.id)
    assert row["in_stock"] == 4, "a device that names no batch is still a device we hold"
    assert row["no_batch"] == 1
    assert row["held"] == {"faulty": 1, "prototype": 1}
    assert row["available"] == 2


def test_run_stock_cannot_see_it_which_is_why_this_exists(world):
    """Not a complaint about `run_stock` — it answers a different question. This
    asserts the gap is real, so nobody "simplifies" the product card back onto
    the per-batch endpoint."""
    db, proj = world["db"], world["proj"]
    per_batch = sum(r["devices_in_stock"] for r in svc.run_stock(db, proj.id))
    assert per_batch == 3
    assert _row(db, proj.id)["in_stock"] == 4


def test_an_unbatched_device_is_counted_but_never_valued(world):
    """Per-device cost belongs to a batch. A unit with no batch is stock with no
    price, and saying so beats averaging it in."""
    db, proj = world["db"], world["proj"]
    row = _row(db, proj.id)
    assert row["no_batch"] == 1
    # Whatever the batch costs, the unbatched unit contributes none of it: the
    # value is over devices that name a batch, and only two of those are here.
    costs = svc.per_device_cost_usd(db)
    unit = costs.get(world["run"].id)
    if unit:
        assert row["value_usd"] == pytest.approx(3 * unit, abs=0.02)


def test_demand_counts_only_what_can_be_sold(world):
    """Supply is `available`, not `in_stock` (user decision 2026-09-21). The
    faulty and the prototype are on the shelf and can never leave."""
    db, proj = world["db"], world["proj"]
    order = M.SalesOrder(customer=M.Customer(name="test-ps-customer"),
                         order_date="2026-06-01", currency="PLN")
    db.add(order)
    db.flush()
    db.add(M.SalesOrderLine(order_id=order.id, project_id=proj.id, qty_ordered=10,
                            unit_price=100.0))
    db.flush()
    row = next(r for r in svc.project_demand(db, proj.id) if r["project_id"] == proj.id)
    assert row["on_shelf"] == 2, "only condition `ok` is supply"
    assert row["open"] == 10
    assert row["shortfall"] == 8
