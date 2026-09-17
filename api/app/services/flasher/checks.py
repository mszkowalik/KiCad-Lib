"""Functional checks — what a run PROVED about one physical device.

A run's log says what happened. A check says what it means: "Relay 2 works",
"the device joined WiFi", "all 16 berryware files landed". The device view is a
grid of these, green or red, and ONLY THE NEWEST RUN SPEAKS: see `for_device`.

Two rules keep the table honest:

1. **Checks are derived, never authored.** `recompute()` rebuilds every row of a
   run from that run's own steps and results. The table is a cache of an opinion
   about evidence — drop it and it comes back identical, and improving an
   extractor here upgrades all history in one backfill.
2. **A name means one thing.** `CATALOG` is the vocabulary. A procedure names a
   check by putting `check: "relay.2"` on the step that proves it, so the same
   functionality keeps one name across versions, products and eras. An unknown
   name still records — it lands in "other" rather than being dropped.

Live runs feed source 1 (steps). Imported V2 runs have no steps at all, so they
feed source 2: those reports kept the relay snapshots, the WiFi status and the
per-file download sizes, which is enough to recover the same checks from the
evidence that was actually stored.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models as M

# name -> (label, category, position within the category)
CATALOG: dict[str, tuple[str, str, int]] = {
    "identity.name": ("Device name", "identity", 0),
    "identity.mac": ("MAC read", "identity", 1),
    "firmware.flash": ("Firmware written", "firmware", 0),
    "firmware.boot": ("Firmware boots", "firmware", 1),
    "wifi.join": ("WiFi joins", "connectivity", 0),
    "sim.pin": ("SIM PIN accepted", "connectivity", 1),
    "sim.identity": ("SIM identified", "connectivity", 2),
    "lte.attach": ("LTE attaches", "connectivity", 3),
    "lte.failover": ("Works without WiFi", "connectivity", 4),
    "mqtt.config": ("MQTT configured", "connectivity", 5),
    "mqtt.connect": ("MQTT connects on WiFi", "connectivity", 6),
    "mqtt.lte": ("MQTT connects on LTE", "connectivity", 7),
    "berryware.files": ("Berryware files", "berryware", 0),
    "modbus.config": ("Modbus port", "hardware", 0),
    "relay.1": ("Relay 1 (Switch7)", "hardware", 1),
    "relay.2": ("Relay 2 (Switch8)", "hardware", 2),
    "relay.3": ("Relay 3 (Switch9)", "hardware", 3),
    "temp.ds18b20": ("Temp sensor (DS18B20)", "hardware", 4),
    # Marking is its own category: it proves nothing electrical, and a unit can
    # be fully working and unmarked.
    "mark.serial": ("Serial engraved", "marking", 0),
    "mark.label": ("Label printed", "marking", 1),
}

CATEGORY_ORDER = ["identity", "firmware", "connectivity", "berryware", "hardware",
                  "marking", "other"]

# The Aqua test's temperature window, copied from test.py's asserts.
TEMP_MIN, TEMP_MAX = -10.0, 70.0


def describe(name: str) -> tuple[str, str, int]:
    return CATALOG.get(name, (name, "other", 99))


def _row(name: str, status: str, detail: str = "", value: Any = None) -> dict:
    label, category, pos = describe(name)
    return {"name": name, "label": label, "category": category, "position": pos,
            "status": status, "detail": detail,
            "value": value if isinstance(value, (dict, list)) else
                     ({"v": value} if value is not None else None)}


# --------------------------------------------------------------- from steps

def _from_steps(run: M.ProgrammingRun) -> list[dict]:
    """A step that carries a `check` name IS the check: its own outcome, its
    own error message. This is the whole live mechanism — no second engine."""
    out = []
    for s in run.steps:
        if not s.check_name:
            continue
        status = {"pass": "pass", "fail": "fail"}.get(s.status, "unknown")
        detail = s.error or s.label or s.op
        out.append(_row(s.check_name, status, detail, s.response))
    return out


def _declared(db: Session, run: M.ProgrammingRun) -> list[str]:
    """Check names the executed procedure promises. A run that died early leaves
    the rest grey ("not reached") instead of silently absent."""
    v = db.get(M.DeploymentVersion, run.deployment_version_id)
    if v is None:
        return []
    return [str(s["check"]) for s in (v.steps or [])
            if isinstance(s, dict) and s.get("check")]


# ------------------------------------------------------------ from results

def _relay(off: dict, on: dict, switch: str, number: int) -> dict:
    """test.py::_check_relay, byte for byte — including the inversion.

    The relay is wired so that energising it OPENS the sense switch: with the
    relays off the switch reads ON, and with them on it reads OFF. Reproducing
    the original rule is the point; a "nicer" rule would silently re-judge 813
    historical measurements.
    """
    name = f"relay.{number}"
    a, b = off.get(switch), on.get(switch)
    if a is None or b is None:
        return _row(name, "unknown", f"{switch} was never reported")
    val = {"relays_off": a, "relays_on": b}
    if a == "OFF":
        return _row(name, "fail", f"Relay {number} or {switch} is faulty (Not OFF)", val)
    if b == "ON":
        return _row(name, "fail", f"Relay {number} or {switch} is faulty (Not ON)", val)
    if a == b:
        return _row(name, "fail", f"Relay {number} did not change state", val)
    return _row(name, "pass", f"{switch} {a} → {b} — the relay switches", val)


def _temp(sensors: list) -> dict:
    ok, bad = [], []
    for s in sensors if isinstance(sensors, list) else []:
        if not isinstance(s, dict):
            continue
        t = s.get("Temperature")
        sid = s.get("Id") or "no id"
        if s.get("Id") is None or t is None:
            bad.append(f"{sid}: incomplete reading")
        elif not (TEMP_MIN < float(t) < TEMP_MAX):
            bad.append(f"{sid}: {t} °C outside ({TEMP_MIN}, {TEMP_MAX})")
        else:
            ok.append(f"{sid}: {t} °C")
    if not ok and not bad:
        return _row("temp.ds18b20", "unknown", "no DS18B20 reported")
    if bad:
        return _row("temp.ds18b20", "fail", "; ".join(bad), {"sensors": sensors})
    return _row("temp.ds18b20", "pass", "; ".join(ok), {"sensors": sensors})


def _pinned_files(db: Session, run: M.ProgrammingRun) -> list[str]:
    rows = db.execute(text("""
        SELECT e.filename
        FROM deployment_versions v
        JOIN file_set_entries e ON e.file_set_id = v.file_set_id
        WHERE v.id = :v
        ORDER BY e.position
    """), {"v": run.deployment_version_id}).fetchall()
    return [r.filename for r in rows]


def _from_results(db: Session, run: M.ProgrammingRun) -> list[dict]:
    """Read the evidence the run stored. Keyed on WHAT IS THERE, never on which
    deployment it was: a result shape means the same thing whoever produced it.
    """
    res = run.results or {}
    out: list[dict] = []

    if res.get("mac") or run.mac_read:
        out.append(_row("identity.mac", "pass", str(res.get("mac") or run.mac_read)))

    banner = res.get("fw_banner")
    if banner:
        out.append(_row("firmware.boot", "pass", f"answered on the console, {banner}",
                        {"banner": banner}))

    topic = res.get("topic") or res.get("device_name")
    if topic:
        parts = str(topic).split("_")
        ok = len(parts) == 2 and all(parts)
        out.append(_row("identity.name", "pass" if ok else "fail",
                        f'device name "{topic}"' if ok
                        else f'device name "{topic}" is not <project>_<id>',
                        {"topic": topic}))

    ssid = res.get("wifi_ssid")
    if ssid:
        rssi = res.get("wifi_rssi")
        out.append(_row("wifi.join", "pass",
                        f"joined {ssid}" + (f", RSSI {rssi}" if rssi is not None else ""),
                        {"ssid": ssid, "rssi": rssi}))

    got = res.get("downloaded")
    if isinstance(got, dict):
        want = _pinned_files(db, run)
        empty = sorted(k for k, v in got.items() if not isinstance(v, int) or v <= 0)
        missing = [f for f in want if f not in got]
        total = sum(v for v in got.values() if isinstance(v, int))
        value = {"files": got, "expected": len(want), "bytes": total}
        if missing or empty:
            broke = ", ".join(missing + empty)
            out.append(_row("berryware.files", "fail",
                            f"{len(got)} of {len(want) or len(got)} files — missing or empty: {broke}",
                            value))
        else:
            out.append(_row("berryware.files", "pass",
                            f"{len(got)} files, {total} bytes"
                            + (" — the whole pinned bundle" if want else ""), value))

    off, on = res.get("switches_off"), res.get("switches_on")
    if isinstance(off, dict) and isinstance(on, dict):
        for number, switch in ((1, "Switch7"), (2, "Switch8"), (3, "Switch9")):
            out.append(_relay(off, on, switch, number))
        sensors = res.get("temp_sensors")
        if sensors is None:
            sensors = [v for k, v in off.items() if k.startswith("DS18B20")]
        out.append(_temp(sensors))

    return out


# ---------------------------------------------------------------- recompute

def recompute(db: Session, run: M.ProgrammingRun) -> list[M.RunCheck]:
    """Rebuild every check row of one run. Idempotent by construction."""
    db.query(M.RunCheck).filter(M.RunCheck.run_id == run.id).delete(synchronize_session=False)
    rows = _from_steps(run)
    seen = {r["name"] for r in rows}
    for r in _from_results(db, run):
        if r["name"] not in seen:
            rows.append(r)
            seen.add(r["name"])
    for name in _declared(db, run):
        if name not in seen:
            rows.append(_row(name, "unknown", "not reached in this run"))
            seen.add(name)

    at = run.finished_at or run.started_at
    made = []
    for r in rows:
        made.append(M.RunCheck(run_id=run.id, device_unit_id=run.device_unit_id, at=at, **r))
    db.add_all(made)
    return made


# ------------------------------------------------------------------ reading

def for_run(db: Session, run_id: int) -> list[dict]:
    rows = db.execute(text("""
        SELECT name, label, category, status, detail, value, position
        FROM run_checks WHERE run_id = :r
    """), {"r": run_id}).mappings().all()
    return _sorted([dict(r) for r in rows])


# A device's history holds every action that could be pinned to it — a
# programming run, a test sweep, a marking job, an erase — and they do NOT all
# mean the same thing about the unit. Two of them MEASURE (`flash` is the
# config procedure, `test` is the sweep), one WIPES (`erase`), and marking
# never changes whether a device works.
MEASURING_KINDS = ("flash", "test")

_HISTORY_SQL = """
    SELECT r.id, r.status, r.started_at, r.attempt_no, r.action, r.test_required,
           COALESCE(d.kind, 'flash') AS kind, d.name AS deployment_name
    FROM programming_runs r
    LEFT JOIN deployment_versions v ON v.id = r.deployment_version_id
    LEFT JOIN deployments d ON d.id = v.deployment_id
    WHERE r.device_unit_id = :dev
    ORDER BY r.started_at DESC, r.id DESC
"""


def _act(row) -> str:
    """What the run WAS: erase | flash | test | mark. From the deployment's
    kind, never from a name — the rule the bench's Test button already
    follows."""
    return "erase" if row["action"] == "erase" else (row["kind"] or "flash")


def _run_brief(row) -> dict:
    return {"id": row["id"], "status": row["status"], "act": _act(row),
            "attempt_no": row["attempt_no"], "deployment": row["deployment_name"],
            "at": row["started_at"].isoformat() if row["started_at"] else None}


def newest_run(db: Session, device_id: int, kinds: tuple[str, ...] = MEASURING_KINDS):
    """The newest run that MEASURED something — where the grid comes from.

    Not simply the newest row: a marking job proves nothing about a device and
    an erase proves the opposite, so neither may stand in for the run that
    programmed or tested the unit (user decision 2026-09-16).
    """
    for row in db.execute(text(_HISTORY_SQL), {"dev": device_id}).mappings():
        if _act(row) in kinds:
            return row
    return None


def verdict(db: Session, device_id: int) -> dict:
    """IS THIS DEVICE PROGRAMMED — the sentence the device page leads with.

    The rule, in the order it is checked (user decision 2026-09-16):

    1. The newest CONFIG run (`kind="flash"`) must have passed. A later failed,
       aborted or still-running attempt IS the newest one, and therefore the
       answer.
    2. A TEST THAT RAN ALWAYS COUNTS. If any test started after that config
       run, the newest of them must have passed — whether or not the batch
       asked for one. A test that was run and failed is knowledge about the
       device, and no batch setting makes it go away (user decision
       2026-09-16).
    3. A TEST THAT DID NOT RUN counts only when the run says it had to. Each
       programming run copies `test_required` from its batch when it starts, so
       a device is judged by the rule in force when it was programmed: turning
       a test on today does not unverify a tray finished last year, and
       re-flashing a unit sends it back for testing because the newer config
       run carries the newer rule.
    4. No ERASE after whichever of those is newer. A wiped device is not a
       programmed device, however well it tested this morning.

    A MARKING run is never consulted: engraving a case does not change what the
    firmware does.
    """
    acts = [(row, _act(row))
            for row in db.execute(text(_HISTORY_SQL), {"dev": device_id}).mappings()]
    config = next((r for r, a in acts if a == "flash"), None)
    erase = next((r for r, a in acts if a == "erase"), None)

    requires_test = bool(config["test_required"]) if config is not None else False

    # The newest test that can speak about THIS programming. An older pass
    # belongs to the firmware the device carried before.
    test = None
    if config is not None and config["started_at"]:
        test = next((r for r, a in acts
                     if a == "test" and r["started_at"]
                     and r["started_at"] > config["started_at"]), None)

    out = {
        "programmed": False, "requires_test": requires_test,
        "config_run": _run_brief(config) if config is not None else None,
        "test_run": _run_brief(test) if test is not None else None,
        "erased_after": None,
        "reason": "",
    }

    if config is None:
        out["reason"] = "no programming run has ever been recorded for it"
        return out
    if config["status"] != "pass":
        out["reason"] = {
            "running": "its newest programming run is still going",
            "aborted": "its newest programming run was aborted",
        }.get(config["status"], "its newest programming run failed")
        return out
    if test is not None and test["status"] != "pass":
        # A test that ran has the last word, required or not.
        out["reason"] = {
            "running": "its test is still running",
            "aborted": "its test was aborted",
        }.get(test["status"], "it failed the test"
              + ("" if requires_test else " — its batch did not ask for one, but the test ran"))
        return out
    if test is None and requires_test:
        out["reason"] = "it has not been tested since it was last programmed"
        return out

    decided = max([r["started_at"] for r in (config, test)
                   if r is not None and r["started_at"]], default=None)
    if erase is not None and decided and erase["started_at"] and erase["started_at"] > decided:
        out["erased_after"] = _run_brief(erase)
        out["reason"] = "it was erased after it was programmed"
        return out

    out["programmed"] = True
    out["reason"] = (
        "it passed its test after the last programming run" if test is not None
        else "its newest programming run passed, and its batch required no test"
        if requires_test is False else "its newest programming run passed")
    return out


def for_device(db: Session, device_id: int) -> list[dict]:
    """The device's grid: ONLY THE NEWEST MEASURING RUN SPEAKS.

    A check states what the device does NOW, so an older run's green must not
    outlive a newer run that failed, aborted, erased the unit or is still going
    (user decision 2026-09-16). Best-ever-per-check read as "programmed" on a
    device whose newest attempt had not passed. The lifetime tally still rides
    along in `attempts`, so what earlier runs measured is one hover away.
    """
    run = newest_run(db, device_id)
    if run is None:
        return []
    rows = db.execute(text("""
        SELECT name, label, category, status, detail, value, position, run_id, at
        FROM run_checks WHERE run_id = :r
    """), {"r": run["id"]}).mappings().all()
    out = [dict(r) for r in rows]
    if not out and run["status"] == "running":
        # A run writes its rows when it finalizes. Until then the procedure's
        # own promises stand in, grey, so the grid keeps its shape and nothing
        # reads as proven while the attempt is still open.
        live = db.get(M.ProgrammingRun, run["id"])
        out = [dict(_row(name, "unknown", "not measured yet — the run is still going"),
                    run_id=run["id"], at=run["started_at"])
               for name in _declared(db, live)]
    history = db.execute(text("""
        SELECT name, status, count(*) AS n
        FROM run_checks WHERE device_unit_id = :d GROUP BY 1, 2
    """), {"d": device_id}).fetchall()
    tally: dict[str, dict[str, int]] = {}
    for h in history:
        tally.setdefault(h.name, {})[h.status] = h.n
    for d in out:
        d["at"] = d["at"].isoformat() if d["at"] else None
        d["attempts"] = tally.get(d["name"], {})
    return _sorted(out)


def counts_for_devices(db: Session, device_ids: list[int]) -> dict[int, dict[str, int]]:
    """pass/fail/unknown per device, from the newest MEASURING run — for the list.

    Same rule as `for_device`, so the list and the device page never disagree.
    """
    if not device_ids:
        return {}
    rows = db.execute(text("""
        SELECT newest.device_unit_id AS d, c.status, count(*) AS n
        FROM (
            SELECT DISTINCT ON (r.device_unit_id) r.device_unit_id, r.id
            FROM programming_runs r
            JOIN deployment_versions v ON v.id = r.deployment_version_id
            JOIN deployments dep ON dep.id = v.deployment_id
            WHERE r.device_unit_id = ANY(:ids) AND dep.kind IN ('flash', 'test')
            ORDER BY r.device_unit_id, r.started_at DESC, r.id DESC
        ) newest
        JOIN run_checks c ON c.run_id = newest.id
        GROUP BY 1, 2
    """), {"ids": device_ids}).fetchall()
    out: dict[int, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r.d, {})[r.status] = r.n
    return out


def _sorted(rows: list[dict]) -> list[dict]:
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(rows, key=lambda r: (order.get(r["category"], 99), r["position"], r["name"]))
