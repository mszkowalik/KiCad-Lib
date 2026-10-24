"""The production agent tools (decision 0088), called as an agent calls them:
batch crafting, process versions, shipments, devices and stock.

What these pin down:

- `get_batch` reports the bench stack, device states and what active devices
  still need, and lists the devices asked for;
- `batch_step` records a step on named devices, refuses a mixed selection
  unless told to skip, and never records a step twice;
- `batch_units` scraps units of a stack and refuses an unknown action;
- `find_device` finds a unit by serial, MAC or a longer id ending in the MAC,
  and `set_device_note` adds dated lines;
- `edit_process` publishes a new process version and `move_batch_process`
  plans the move to it;
- `shipment_devices` packs and unpacks an open shipment, which `get_shipment`
  and `list_shipments` then show;
- `get_stock` lists a project's pool, MPN-keyed parts included.

Each tool opens its own session. Here those sessions join the test's one
transaction, which is rolled back: the dev database is left untouched.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_production_tools.py -q
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from datetime import UTC, datetime

import pytest
import test_twins
from sqlalchemy.orm import Session
from test_twins import _crafted_devices, _received

from app import models as M
from app.db import engine
from app.services import agent_tools as A
from app.services import orders as osvc

world = test_twins.world  # the crafted product fixture; its `db` is this module's


@pytest.fixture
def db(monkeypatch):
    """One transaction, never committed; every tool session joins it."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    monkeypatch.setattr(A, "SessionLocal", lambda: Session(
        bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False))
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def call(tool: str, **kw) -> dict:
    return json.loads(getattr(A, tool).func(**kw))


def test_get_batch_shows_the_bench_and_what_devices_need(db, world):
    _crafted_devices(db, world, 61, 2)
    out = call("get_batch", run_id=world["b1"].id, devices="all")
    assert out["devices_by_state"] == {"active": 2}
    assert {d["serial"] for d in out["devices"]} == {"TW0061", "TW0062"}
    assert out["bench_stack"] and out["bench_left"] == 0
    assert any("Laser mark" in k for k in out["active_devices_need"])
    one = call("get_batch", run_id=world["b1"].id, devices="TW0062")
    assert [d["serial"] for d in one["devices"]] == ["TW0062"]
    assert "error" in call("get_batch", run_id=999999999)


def test_batch_step_skips_only_when_told_and_never_twice(db, world):
    _crafted_devices(db, world, 71, 2)
    b1 = world["b1"].id
    assert call("batch_step", run_id=b1, step_key="carton", devices="TW0071", dry_run=False)["units"] == 1
    plan = call("batch_step", run_id=b1, step_key="carton", devices="TW0071, TW0072")
    assert (plan["units"], plan["selected"], [r["unit"] for r in plan["refused"]]) == (1, 2, ["TW0071"])
    assert "error" in call("batch_step", run_id=b1, step_key="carton", devices="TW0071 TW0072", dry_run=False)
    done = call("batch_step", run_id=b1, step_key="carton", devices="TW0071 TW0072",
                skip_refused=True, dry_run=False)
    assert done["units"] == 1
    again = call("batch_step", run_id=b1, step_key="carton", devices="TW0072")
    assert again["refused"][0]["why"] == ["'Carton' is already done"]


def test_batch_units_scraps_from_a_stack(db, world):
    stack = _received(db, world, 3)
    b1 = world["b1"].id
    out = call("batch_units", run_id=b1, action="scrap", stack=stack, qty=1, reason="dropped", dry_run=False)
    assert out["units"] == 1
    assert db.query(M.Unit).filter_by(run_id=b1, status="scrapped").count() == 1
    assert "error" in call("batch_units", run_id=b1, action="explode")


def test_find_device_and_its_notes(db, world):
    (d,) = _crafted_devices(db, world, 81, 1)
    out = call("find_device", code="TW0081")
    assert out["twin"]["status"] == "active" and "program" in out["twin"]["done"]
    assert call("find_device", code=d.mac)["device_id"] == d.id
    assert call("find_device", code="142547" + d.mac.replace(":", "").upper())["device_id"] == d.id
    call("set_device_note", code="TW0081", note="held for a check")
    notes = call("set_device_note", code="TW0081", note="released")["notes"].splitlines()
    assert len(notes) == 2 and notes[0].endswith("held for a check") and notes[1].endswith("released")
    assert "error" in call("find_device", code="NO-SUCH-DEVICE")


def test_a_process_edit_publishes_and_a_batch_can_move_to_it(db, world):
    out = call("get_process", project="test-twins")
    assert out["current_version_id"] == world["v"].id
    steps = out["steps"]
    for s in steps:
        if s["key"] == "leaflet":
            s["required"] = True
    graph = {"steps": steps, "route": out["route"], "prepared": out["prepared"]}
    res = call("edit_process", project="test-twins", graph_json=json.dumps(graph),
               comment="the leaflet is required", publish=True)
    assert res["status"] == "published" and res["id"] != world["v"].id
    assert call("get_process", project="test-twins")["current_version_id"] == res["id"]
    plan = call("move_batch_process", run_id=world["b1"].id, process_version_id=res["id"])
    assert plan["dry_run"] and plan["to_version"] == res["version_no"]
    assert "error" in call("edit_process", project="test-twins", graph_json="{", comment="x")


def test_shipment_tools_pack_unpack_and_report(db, world):
    proj = world["project"]
    run = M.ProductionRun(project_id=proj.id, label="TSHIP", run_date="2026-01-01", status="completed")
    db.add(run)
    db.flush()
    for i in range(2):
        d = M.DeviceUnit(project_id=proj.id, serial=f"SHIPTOOL{i:04d}", mac=f"00:00:0f:00:00:{i:02x}",
                         first_seen=datetime(2026, 1, 1, 10, i, tzinfo=UTC))
        db.add(d)
        db.flush()
        osvc.record_event(db, d, "produced", production_run_id=run.id)
    cust = osvc.get_customer(db, "test-production-tools-customer")
    order = M.SalesOrder(customer_id=cust.id, order_ref="TEST/TOOLS", order_date="2026-03-01")
    db.add(order)
    db.flush()
    db.add(M.SalesOrderLine(order_id=order.id, project_id=proj.id, product="thing", qty_ordered=2,
                            unit_price=1.0))
    db.flush()
    db.refresh(order)
    sh = osvc.open_shipment(db, order)
    db.flush()
    assert call("shipment_devices", shipment_id=sh.id, action="pack", devices="SHIPTOOL0000 SHIPTOOL0001")["qty"] == 2
    out = call("get_shipment", shipment_id=sh.id)
    assert sorted(x["serial"] for x in out["devices"]) == ["SHIPTOOL0000", "SHIPTOOL0001"]
    assert sorted(out["devices_without_twin"]) == ["SHIPTOOL0000", "SHIPTOOL0001"]
    assert sh.id in [x["id"] for x in call("list_shipments", status="open", limit=500)]
    assert call("shipment_devices", shipment_id=sh.id, action="unpack", devices="SHIPTOOL0000")["qty"] == 1
    assert "error" in call("shipment_devices", shipment_id=sh.id, action="pack", devices="NO-SUCH")


def test_get_stock_lists_mpn_keyed_parts(db, world):
    out = call("get_stock", project="test-twins", part="TEST-TWIN-KARTON")
    assert [(p["mpn"], p["bought"]) for p in out["parts"]] == [("TEST-TWIN-KARTON", 100.0)]
