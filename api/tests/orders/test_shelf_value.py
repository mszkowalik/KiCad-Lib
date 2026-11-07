"""The shelf prices each unit as an order does, and counts every unbatched device.

Two things are protected here.

1. **A crafted batch's units are worth their twins' prices, and a gap nothing.**
   The shelf valued every unit at its batch's AVERAGE. A crafted batch's twins
   carry the whole batch, so the average counted the batch twice over its gap:
   Batch 8 read 172 x 15.21 = 2,615.92 USD while its 171 shelf twins carry
   2,572.92, and the shipped twins plus the shelf came to 12,210.05 against a
   batch cost of 12,167.05.
2. **`no_batch` counts every state.** It counted the shelf only, so 51
   CE_Dongle_V2 devices with no batch (40 shipped, 11 missing) made the product
   card read 5,130 shipped and 15 missing against 5,090 and 4 on the per-batch
   card, while both said "no batch: 0".

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
from app.routers import orders as orders_router
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


def _device(db, proj, i, run_id=None):
    d = M.DeviceUnit(project_id=proj.id, serial=f"SV{i:02d}", mac=f"00:00:00:00:5e:{i:02x}",
                     first_seen=datetime(2026, 5, 1, 12, i, tzinfo=UTC), condition="ok")
    db.add(d)
    db.flush()
    svc.record_event(db, d, "produced", production_run_id=run_id)
    return d


@pytest.fixture
def world(db: Session):
    """A crafted batch with three units on the shelf: two with twins, one gap. And
    three devices that name no batch: one on the shelf, one shipped, one missing."""
    proj = M.Project(name="test-shelf-value", git_url="https://example.invalid/sv.git")
    db.add(proj)
    db.flush()
    # `process_version_id` is a soft pointer: any value makes the batch crafted.
    run = M.ProductionRun(project_id=proj.id, label="SV1", run_date="2026-05-01", status="completed",
                          qty=3, process_version_id=987654321)
    db.add(run)
    db.flush()
    crafted = [_device(db, proj, i, run.id) for i in range(3)]
    loose = [_device(db, proj, 10 + i) for i in range(3)]
    svc.record_event(db, loose[1], "shipped")
    svc.record_event(db, loose[2], "missing")
    db.flush()
    return {"proj": proj, "run": run, "crafted": crafted, "loose": loose}


def test_a_crafted_unit_is_worth_its_twin_and_a_gap_nothing(db, world):
    run, (a, b, _gap) = world["run"], world["crafted"]
    unit_cost = {run.id: 10.0}
    twin_cost = {a.id: 4.0, b.id: 6.0}
    g = svc.shelf_values(db, unit_cost, twin_cost)[(world["proj"].id, run.id)]
    assert (g["n"], g["uncosted"]) == (3, 1)
    assert g["usd"] == pytest.approx(10.0), "the batch average would read 30.0"
    row = next(r for r in svc.product_stock(db, unit_cost, twin_cost) if r["project_id"] == world["proj"].id)
    assert row["value_usd"] == pytest.approx(10.0)
    assert row["uncosted"] == 2, "the gap, and the shelf device that names no batch"


def test_a_device_of_an_ordinary_batch_keeps_the_batch_average(db, world):
    proj = world["proj"]
    run = M.ProductionRun(project_id=proj.id, label="SV2", run_date="2026-05-02", status="completed", qty=2)
    db.add(run)
    db.flush()
    _device(db, proj, 20, run.id)
    _device(db, proj, 21, run.id)
    g = svc.shelf_values(db, {run.id: 7.5}, {})[(proj.id, run.id)]
    assert (g["n"], g["uncosted"], g["usd"]) == (2, 0, pytest.approx(15.0))


def test_no_batch_counts_every_state(db, world):
    row = next(r for r in svc.product_stock(db) if r["project_id"] == world["proj"].id)
    assert row["no_batch"] == 3
    assert row["no_batch_states"] == {"in_stock": 1, "shipped": 1, "missing": 1}
    out = orders_router.finished_stock(project_id=world["proj"].id, db=db)
    assert out["totals"]["no_batch"] == 3, "the per-batch card must say how many it cannot see"
    assert out["totals"]["no_batch_states"] == {"in_stock": 1, "shipped": 1, "missing": 1}
