"""The CE_Dongle_V3 bench gaps of 2026-10-18 (docs/ce-dongle-v3-bench-gaps.md).

The agent's port retry, identity captured by `berry` and `poll_until`, input longer than its column refused with 422, one parameter
key set or removed without the rest, the operator's yes/no step, the broker
check, the per-delivery MQTT file, the five new check names, and the
`online_elsewhere` notice that a bench run explains.

The engine tests need no database. The rest use the dev database and roll
their transaction back. Run from `api/`:
    python -m pytest tests/flasher -q
"""
import asyncio
import json
import pathlib
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session

from app import main as app_main
from app import models as M
from app.db import engine
from app.routers import flasher as F
from app.services import orders as osvc
from app.services.flasher import bench_checks, checks, credentials
from app.services.flasher import engine as E


class FakeWs:
    def __init__(self):
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()

    async def send_json(self, msg: dict) -> None:
        self.sent.append(msg)

    async def receive_json(self) -> dict:
        return await self.inbox.get()


def _engine() -> tuple[E.RunEngine, FakeWs]:
    ws = FakeWs()
    return E.RunEngine(ws, run_id=0), ws


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


# ------------------------------------------------- 3. identity from berry

async def _answer(eng: E.RunEngine, line: str) -> None:
    await asyncio.sleep(0.05)
    eng.rx_q.put_nowait(line)


def test_a_berry_capture_reaches_the_device_row():
    """Device 28844 kept its ICCID (a `command` step) and lost its IMEI, IMSI
    and modem firmware (three `berry` steps)."""
    async def go():
        eng, _ = _engine()
        stored: list[dict] = []

        async def store(names):
            stored.append(dict(names))

        eng._store_identity = store
        asyncio.create_task(_answer(eng, 'RSL: RESULT = {"Br":"861234567890123"}'))
        await eng._exec({"op": "berry", "code": "return 1", "capture": {"imei": "Br"}, "timeout": 2})
        assert stored == [{"imei": "861234567890123"}]

    asyncio.run(go())


def test_a_poll_until_capture_reaches_the_device_row():
    async def go():
        eng, _ = _engine()
        stored: list[dict] = []

        async def store(names):
            stored.append(dict(names))

        eng._store_identity = store
        asyncio.create_task(_answer(eng, '{"Lte":{"Up":1,"Imsi":"260011234567890"}}'))
        await eng._exec({"op": "poll_until", "cmd": "LteState", "expect_key": "Lte", "path": "Lte.Up",
                         "equals": "1", "capture": {"imsi": "Lte.Imsi"}, "timeout": 2, "every": 1})
        assert stored == [{"imsi": "260011234567890"}]

    asyncio.run(go())


# ------------------------------------------------------- 4. too long = 422

def test_a_comment_longer_than_its_column_is_refused_by_the_body():
    with pytest.raises(ValidationError) as e:
        F.ComposeIn(comment="x" * 501)
    assert "500" in str(e.value)
    with pytest.raises(ValidationError):
        F.BenchRunIn(project_id=1, station="s" * 41)
    F.BenchRunIn(project_id=1, station="s" * 40)


def test_a_value_too_long_anywhere_else_answers_422_not_500(db: Session):
    with pytest.raises(DataError) as e:
        db.add(M.Project(name="x" * 5000, git_url="https://example.invalid/long.git"))
        db.flush()
    resp = app_main._too_long(None, e.value)
    assert resp.status_code == 422
    assert "too long" in json.loads(resp.body)["detail"]


# --------------------------------------------- 5. one parameter at a time

def test_one_key_is_set_and_another_removed_without_sending_the_rest(db: Session):
    proj = M.Project(name="test-param-keys", git_url="https://example.invalid/pk.git")
    db.add(proj)
    db.flush()
    F.put_param_set(proj.id, F.ParamSetIn(values={"creds_salt": "keep-me", "old": "1"}), name="prod", db=db)
    out = F.patch_param_set(proj.id, F.ParamKeysIn(set_keys={"test_mqtt_user": "bench"},
                                                    delete_keys=["old"], note="bench account"),
                            name="prod", db=db)
    ps = db.query(M.ParamSet).filter_by(project_id=proj.id, name="prod").one()
    assert F._param_values(ps) == {"creds_salt": "keep-me", "test_mqtt_user": "bench"}
    rev = db.query(M.ParamSetRevision).filter_by(param_set_id=ps.id, revision_no=out["revision_no"]).one()
    assert rev.keys_added == ["test_mqtt_user"] and rev.keys_removed == ["old"]

    again = F.patch_param_set(proj.id, F.ParamKeysIn(set_keys={"test_mqtt_user": "bench"}), name="prod", db=db)
    assert again.get("unchanged") and again["revision_no"] == out["revision_no"]
    with pytest.raises(HTTPException) as e:
        F.patch_param_set(proj.id, F.ParamKeysIn(delete_keys=["nope"]), name="prod", db=db)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        F.patch_param_set(proj.id, F.ParamKeysIn(set_keys={"a": "1"}, delete_keys=["a"]), name="prod", db=db)
    assert e.value.status_code == 400


# ------------------------------------------------ 6. the operator decides

def _confirm(eng: E.RunEngine, ws: FakeWs, step: dict, answer: str):
    async def go():
        recv = asyncio.create_task(eng._recv_loop())
        task = asyncio.create_task(eng._exec(step))
        while not any(m.get("t") == "prompt" for m in ws.sent):
            await asyncio.sleep(0.01)
        ask = next(m for m in ws.sent if m.get("t") == "prompt")
        await ws.inbox.put({"t": "prompt_result", "id": ask["id"], "value": answer})
        try:
            return ask, await task
        finally:
            recv.cancel()

    return asyncio.run(go())


def test_yes_passes_and_records_who_answered():
    eng, ws = _engine()
    eng.operator = "Mateusz Kowalik"
    ask, _ = _confirm(eng, ws, {"op": "operator_check", "question": "Is LED U17 red?",
                                "hint": "left light pipe"}, "yes")
    assert ask["kind"] == "confirm" and ask["label"] == "Is LED U17 red?" and ask["hint"] == "left light pipe"
    assert eng.results["operator_answers"] == [
        {"question": "Is LED U17 red?", "answer": "yes", "by": "Mateusz Kowalik"}]
    assert eng.last_response["answer"] == "yes"


def test_no_fails_the_step_and_keeps_the_answer():
    eng, ws = _engine()
    with pytest.raises(E.StepFailed) as e:
        _confirm(eng, ws, {"op": "operator_check", "question": "Is LED U18 green?"}, "no")
    assert "answered no" in str(e.value)
    assert eng.last_response == {"question": "Is LED U18 green?", "answer": "no", "by": "operator"}


# ------------------------------------------------ 9. the broker heard it

def test_the_broker_check_waits_for_a_live_message_after_the_flash(db: Session):
    async def go():
        eng, _ = _engine()

        async def same_session(fn):
            return fn(db)

        eng._db = same_session
        eng.vars["topic"] = "test_gaps_topic_1"
        eng.flashed_at = datetime.now(UTC)
        row = M.DevicePresence(topic="test_gaps_topic_1",
                               last_seen_at=eng.flashed_at - timedelta(minutes=1))
        db.add(row)
        db.flush()
        with pytest.raises(E.StepFailed) as e:
            await eng._exec({"op": "broker_heard", "timeout": 0.3, "every": 0.1})
        assert "heard nothing" in str(e.value)       # heard, but before the flash
        row.last_seen_at = datetime.now(UTC)
        db.flush()
        await eng._exec({"op": "broker_heard", "timeout": 1, "every": 0.1})
        assert eng.results["broker_heard_at"] == row.last_seen_at.isoformat()

    asyncio.run(go())


# ------------------------------------------- 12. one delivery's accounts

def _account(db: Session, dev: M.DeviceUnit, username: str, *, current: bool) -> str:
    salt = "c2FsdHNhbHRzYWx0"
    _, password, salt, final_hash = credentials.derive(username, "", salt)
    run = M.ProgrammingRun(device_unit_id=dev.id, status="pass")
    db.add(run)
    db.flush()
    for key, value in (("mqtt_password", password),
                       ("mqtt_creds_line", credentials.mosquitto_line(username, salt, final_hash))):
        db.add(M.DeviceConfigValue(device_unit_id=dev.id, key=key, value=value, is_secret=True,
                                   set_by_run_id=run.id, current=current))
    db.flush()
    return password


def test_a_batch_and_a_shipment_export_only_the_current_account(db: Session):
    proj = M.Project(name="test-mqtt-delivery", git_url="https://example.invalid/md.git")
    db.add(proj)
    db.flush()
    batch = M.ProductionRun(project_id=proj.id, label="TB-mqtt", run_date="2026-10-18")
    db.add(batch)
    db.flush()
    dev = M.DeviceUnit(project_id=proj.id, serial="AABBCCDDEE01", mac="aa:bb:cc:dd:ee:01",
                       production_run_id=batch.id)
    other = M.DeviceUnit(project_id=proj.id, serial="AABBCCDDEE02", mac="aa:bb:cc:dd:ee:02")
    db.add_all([dev, other])
    db.flush()
    _account(db, dev, "dongle_DDEE01", current=False)
    pw = _account(db, dev, "dongle_AABBCCDDEE01", current=True)
    _account(db, other, "dongle_AABBCCDDEE02", current=True)

    body = F.mosquitto_export_batch(batch.id, db=db).body.decode()
    assert body == f"dongle_AABBCCDDEE01:{pw}\n"            # no old name, no other unit
    full = F.mosquitto_export(proj.id, db=db).body.decode()
    assert "dongle_DDEE01:" in full                          # the broker file keeps every name

    cust = M.Customer(name="test-mqtt-delivery-customer")
    db.add(cust)
    db.flush()
    order = M.SalesOrder(customer_id=cust.id, order_ref="TB-MQTT-1", order_date="2026-10-18")
    db.add(order)
    db.flush()
    sh = osvc.open_shipment(db, order)
    db.flush()
    osvc.record_event(db, dev, "allocated", shipment_id=sh.id)
    osvc.record_event(db, other, "allocated", shipment_id=sh.id)
    osvc.record_event(db, other, "unallocated", shipment_id=sh.id)   # taken back out
    db.flush()
    assert F.shipment_device_ids(db, sh.id) == [dev.id]
    assert F.mosquitto_export_shipment(sh.id, db=db).body.decode() == f"dongle_AABBCCDDEE01:{pw}\n"


# ------------------------------------------------------ 15. check names

def test_the_v6_check_names_have_a_label_and_a_category():
    for name in ("firmware.version", "hw.mux", "wifi.cleared", "wifi.radio", "settings.qpc"):
        label, category, _ = checks.describe(name)
        assert category != "other" and label != name, name
        assert category in checks.CATEGORY_ORDER


# --------------------------------------------- 16. online from the bench

def _presence_case(db: Session, *, online_since: timedelta, run_started: timedelta,
                   run_took: timedelta) -> list[str]:
    now = datetime.now(UTC)
    proj = M.Project(name="test-online-bench", git_url="https://example.invalid/ob.git")
    db.add(proj)
    db.flush()
    dev = M.DeviceUnit(project_id=proj.id, serial="AABBCC000016", mac="aa:bb:cc:00:00:16",
                       tasmota_id="dongle_AABBCC000016")
    db.add(dev)
    db.flush()
    db.add(M.ProgrammingRun(device_unit_id=dev.id, status="fail", started_at=now - run_started,
                            finished_at=now - run_started + run_took))
    db.add(M.DevicePresence(topic="dongle_AABBCC000016", device_unit_id=dev.id, lwt="Online",
                            online=True, last_online_at=now - online_since, last_seen_at=now))
    current = M.ProgrammingRun(device_unit_id=dev.id, status="running")
    db.add(current)
    db.flush()
    return [n["code"] for n in bench_checks.for_device(db, current, dev, created=False,
                                                       project_id=proj.id)]


def test_a_unit_the_last_run_brought_online_is_not_online_elsewhere(db: Session):
    """Runs 8866 and 8867: the retry warned about the unit its own previous run
    had put on the broker."""
    assert "online_elsewhere" not in _presence_case(
        db, online_since=timedelta(minutes=6), run_started=timedelta(minutes=10),
        run_took=timedelta(minutes=3))


def test_a_session_older_than_the_bench_run_still_warns(db: Session):
    """A clone elsewhere was online before this unit reached the bench."""
    assert "online_elsewhere" in _presence_case(
        db, online_since=timedelta(days=2), run_started=timedelta(minutes=10),
        run_took=timedelta(minutes=3))


def test_a_session_long_after_the_bench_run_still_warns(db: Session):
    assert "online_elsewhere" in _presence_case(
        db, online_since=timedelta(hours=1), run_started=timedelta(hours=3),
        run_took=timedelta(minutes=3))


# ------------------------------------------ 1. the port comes back after a reset

def test_the_agent_waits_for_a_port_that_is_re_enumerating(monkeypatch):
    """Run 8868: `esp_reset` opened the C6's port once, while it was gone."""
    import types

    from app.services.bench_agent import agent as A

    calls = []

    class SerialException(OSError):
        pass

    def opener(port, baud, timeout):
        calls.append(port)
        if len(calls) < 3:
            raise SerialException(f"[Errno 2] could not open port {port}")
        return types.SimpleNamespace(port=port)

    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(
        Serial=opener, SerialException=SerialException))
    monkeypatch.setattr(A.time, "sleep", lambda _s: None)
    assert A.open_port("/dev/cu.usbmodem101", 115200, 0.1).port == "/dev/cu.usbmodem101"
    assert len(calls) == 3

    calls.clear()
    clock = iter(range(0, 100, 2))
    monkeypatch.setattr(A.time, "time", lambda: next(clock))
    monkeypatch.setitem(sys.modules, "serial", types.SimpleNamespace(
        Serial=lambda *a, **k: (_ for _ in ()).throw(SerialException("could not open port")),
        SerialException=SerialException))
    with pytest.raises(A.MarkError) as e:
        A.open_port("/dev/cu.usbmodem101", 115200, 0.1)
    assert "waited 5s for the port" in str(e.value)


def test_an_identity_longer_than_its_column_is_logged_and_not_written():
    async def go():
        eng, _ = _engine()
        eng.device_unit_id = None            # nothing is written without a unit either way
        await eng._store_identity({"imsi": "2600112345678901234567 OK"})
        assert any("not stored" in r["text"] for r in eng._logbuf)

    asyncio.run(go())


# --------------------------------------- 8. one run lists every defect

def test_a_continued_failure_lets_the_run_go_on_and_still_fails_it(db: Session):
    proj = M.Project(name="test-continue-on-fail", git_url="https://example.invalid/cf.git")
    db.add(proj)
    db.flush()
    dep = M.Deployment(project_id=proj.id, name="cf-test", kind="test")
    db.add(dep)
    db.flush()
    steps = [
        {"op": "assert_equals", "var": "led", "equals": "red", "check": "led.u17", "continue_on_fail": True},
        {"op": "assert_equals", "var": "button", "equals": "pressed", "check": "button.boot"},
    ]
    v = M.DeploymentVersion(deployment_id=dep.id, version_no=1, status="draft", steps=steps)
    db.add(v)
    db.flush()
    run = M.ProgrammingRun(deployment_version_id=v.id, status="running", draft_run=True)
    db.add(run)
    db.flush()

    async def go():
        ws = FakeWs()
        eng = E.RunEngine(ws, run_id=run.id)

        async def same_session(fn):
            return fn(db)

        async def load():
            eng.spec = {"project_id": proj.id, "deployment_name": "cf-test", "deployment_version_no": 1,
                        "draft": True, "chip": "", "transport_profile": "", "transport": {},
                        "monitor_baud": 115200, "flash_config": {}, "images": [], "files": [],
                        "steps": steps, "params": {}}
            eng.vars = {"led": "green", "button": "pressed", "Password1": "bench-wifi-pw"}

        eng._db = same_session
        eng._load = load
        await ws.inbox.put({"t": "hello"})
        await eng.run()
        return ws

    ws = asyncio.run(go())
    db.refresh(run)
    assert run.status == "fail"
    assert run.error.startswith("1 check(s) failed: step 1")
    assert run.params_snapshot["Password1"] == "bench-wifi-pw"     # decision 0094
    assert [s.status for s in sorted(run.steps, key=lambda s: s.idx)] == ["fail", "pass"]
    assert [m["status"] for m in ws.sent if m.get("t") == "state" and m["status"] != "running"] == ["fail", "pass"]


def test_only_a_step_that_checks_something_may_continue(db: Session):
    from app.services.flasher import validate

    dep = M.Deployment(project_id=db.query(M.Project.id).first()[0], name="cf-validate", kind="test")
    db.add(dep)
    db.flush()
    v = M.DeploymentVersion(deployment_id=dep.id, version_no=1, status="draft", steps=[
        {"op": "serial_open", "continue_on_fail": True},
        {"op": "command", "cmd": "Status", "continue_on_fail": True},
        {"op": "command", "cmd": "Status", "check": "identity.name", "continue_on_fail": True},
    ])
    db.add(v)
    db.flush()
    errors = validate.check(db, v)["errors"]
    assert any("step 1 (serial_open) cannot continue" in e for e in errors)
    assert any("step 2 continues on failure but names no check" in e for e in errors)
    assert not any(e.startswith("step 3") for e in errors)


# ------------------------------------------- 17. which commit is the image

def test_an_image_without_a_commit_warns_and_a_bad_commit_is_refused(db: Session):
    from app.services.flasher import validate

    proj = M.Project(name="test-fw-commit", git_url="https://example.invalid/fc.git")
    db.add(proj)
    db.flush()
    asset = M.FirmwareAsset(project_id=proj.id, filename="fw.bin", sha256="ab" * 32, size_bytes=1024,
                            chip="esp32c6", kind="factory", minio_key="test/fw.bin")
    dep = M.Deployment(project_id=proj.id, name="fc-flash", chip="esp32c6")
    db.add_all([asset, dep])
    db.flush()
    v = M.DeploymentVersion(deployment_id=dep.id, version_no=1, status="draft",
                            transport_profile="usb_serial_jtag",
                            steps=[{"op": "esp_connect"}, {"op": "flash"}])
    db.add(v)
    db.flush()
    db.add(M.DeploymentImage(deployment_version_id=v.id, firmware_asset_id=asset.id, address="0x0"))
    db.flush()
    db.refresh(v)

    def commit_warnings():
        return [w for w in validate.check(db, v)["warnings"] if "git commit" in w]

    assert commit_warnings()
    with pytest.raises(HTTPException) as e:
        F.patch_firmware(asset.id, F.FirmwarePatch(git_commit="not-a-sha"), db=db)
    assert e.value.status_code == 400
    out = F.patch_firmware(asset.id, F.FirmwarePatch(git_commit=" EC3F070F9 "), db=db)
    assert out["git_commit"] == "ec3f070f9"
    db.refresh(asset)
    assert not commit_warnings()


# ------------------------------------------- 10. limits per bench station

def test_a_station_value_replaces_the_plain_one_for_that_station_only():
    from app.services.flasher import params as P

    values = {"lte_rsrp_min": -140, "lte_rsrp_min@slot 2": -110, "lte_rsrp_min@slot 3": -100, "x": 1}
    out, applied = P.for_station(values, "Slot 2")
    assert out == {"lte_rsrp_min": -110, "x": 1}
    assert applied and "slot 2" in applied[0]
    assert P.for_station(values, "slot 1")[0] == {"lte_rsrp_min": -140, "x": 1}
    assert P.for_station(values, "")[0] == {"lte_rsrp_min": -140, "x": 1}


def test_a_range_limit_comes_from_a_parameter_and_is_recorded_with_the_value():
    async def go():
        eng, _ = _engine()
        eng.vars.update({"lte_rsrp": -97, "lte_rsrp_min": "-140", "lte_rsrp_max": -44})
        step = {"op": "assert_range", "var": "lte_rsrp", "min": "{lte_rsrp_min}", "max": "{lte_rsrp_max}",
                "check": "lte.signal"}
        await eng._exec(step)
        assert eng.results["limits"]["lte.signal"] == {"value": -97.0, "min": -140.0, "max": -44.0}
        eng.vars["lte_rsrp_min"] = "-90"
        with pytest.raises(E.StepFailed) as e:
            await eng._exec(step)
        assert "-97 outside [-90, -44]" in str(e.value)
        del eng.vars["lte_rsrp_max"]
        with pytest.raises(E.StepFailed) as e:
            await eng._exec(step)
        assert "not both numbers" in str(e.value)

    asyncio.run(go())


def test_a_limit_must_be_a_number_or_one_parameter(db: Session):
    from app.services.flasher import validate

    dep = M.Deployment(project_id=db.query(M.Project.id).first()[0], name="limit-validate", kind="test")
    db.add(dep)
    db.flush()
    v = M.DeploymentVersion(deployment_id=dep.id, version_no=1, status="draft",
                            param_defaults={"rssi_min": 10}, steps=[
        {"op": "assert_range", "var": "operator", "min": "{rssi_min}", "max": 100},
        {"op": "assert_range", "var": "operator", "min": "low", "max": "100"},
        {"op": "assert_range", "var": "operator", "min": 1},
    ])
    db.add(v)
    db.flush()
    errors = validate.check(db, v)["errors"]
    assert not any(e.startswith("step 1 ") for e in errors), errors
    assert any("step 2 (assert_range) min 'low' is neither" in e for e in errors)
    assert any("step 3 (assert_range) has no max" in e for e in errors)


# ----------------------------------------- 11. heard after it was shipped

def test_a_shipped_unit_counts_as_heard_only_after_the_shipment_and_its_last_run(db: Session):
    now = datetime.now(UTC)
    proj = M.Project(name="test-shipment-broker", git_url="https://example.invalid/sb.git")
    cust = M.Customer(name="test-shipment-broker-customer")
    db.add_all([proj, cust])
    db.flush()
    devs = []
    for i in range(3):
        d = M.DeviceUnit(project_id=proj.id, serial=f"AABBCC0011{i:02d}", mac=f"aa:bb:cc:00:11:{i:02d}",
                         tasmota_id=f"dongle_AABBCC0011{i:02d}", state="shipped")
        db.add(d)
        db.flush()
        devs.append(d)
    order = M.SalesOrder(customer_id=cust.id, order_ref="TB-BROKER-1", order_date="2026-10-01")
    db.add(order)
    db.flush()
    sh = M.Shipment(order_id=order.id, kind="delivery", status="sent", shipped_at="2026-10-01")
    db.add(sh)
    db.flush()
    shipped_at = now - timedelta(days=5)
    for d in devs:
        db.add(M.DeviceEvent(device_id=d.id, kind="shipped", at=shipped_at, shipment_id=sh.id))
    # 0: heard after it shipped. 1: heard only before. 2: its last bench run is
    # after the shipment, and the broker heard it during that run only.
    db.add(M.DevicePresence(topic=devs[0].tasmota_id, device_unit_id=devs[0].id, online=True,
                            last_seen_at=now - timedelta(minutes=1), last_online_at=now - timedelta(days=2)))
    db.add(M.DevicePresence(topic=devs[1].tasmota_id, device_unit_id=devs[1].id, online=False,
                            last_seen_at=shipped_at - timedelta(hours=1)))
    db.add(M.ProgrammingRun(device_unit_id=devs[2].id, status="pass", started_at=now - timedelta(days=1),
                            finished_at=now - timedelta(days=1) + timedelta(minutes=4)))
    db.add(M.DevicePresence(topic=devs[2].tasmota_id, device_unit_id=devs[2].id, online=False,
                            last_seen_at=now - timedelta(days=1) + timedelta(minutes=2)))
    db.flush()

    b = osvc.shipment_broker(db, sh)["devices"]
    assert b[devs[0].id]["heard_at"] and b[devs[0].id]["online"] and b[devs[0].id]["online_since"]
    assert b[devs[1].id]["heard_at"] is None
    assert b[devs[2].id]["heard_at"] is None


# -------------------------------------------- the record keeps every value

def test_the_run_record_keeps_secrets_in_clear():
    """User decision 2026-10-18 (decision 0094): the log and the snapshot prove
    what a unit was programmed with."""
    async def go():
        eng, ws = _engine()
        eng.vars["sim_pin"] = "4321"
        asyncio.create_task(_answer(eng, '{"LteSimPin":"4321"}'))
        await eng._exec({"op": "lte_sim_pin", "timeout": 2})
        assert any(r["dir"] == "tx" and r["text"] == "LteSimPin 4321" for r in eng._logbuf)
        assert eng.last_response == {"LteSimPin": "4321"}

    asyncio.run(go())


def test_the_change_history_never_copies_a_runs_snapshot():
    from app.services import tracking

    assert tracking._is_secret("programming_runs", "params_snapshot", None)
    assert not tracking._is_secret("programming_runs", "results", None)
