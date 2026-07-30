"""Functional checks — what a run PROVED about one physical device.

A run's log says what happened. A check says what it means: "Relay 2 works",
"the device joined WiFi", "all 16 berryware files landed". The device view is a
grid of these, green or red, newest run wins.

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
}

CATEGORY_ORDER = ["identity", "firmware", "connectivity", "berryware", "hardware", "other"]

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
        SELECT f.filename
        FROM deployment_files df
        JOIN device_file_versions v ON v.id = df.device_file_version_id
        JOIN device_files f ON f.id = v.device_file_id
        WHERE df.deployment_version_id = :v
        ORDER BY df.position
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


def for_device(db: Session, device_id: int) -> list[dict]:
    """The device's grid: for every check ever recorded, the NEWEST run that
    recorded it wins, with how many earlier runs disagreed."""
    rows = db.execute(text("""
        SELECT DISTINCT ON (c.name)
               c.name, c.label, c.category, c.status, c.detail, c.value, c.position,
               c.run_id, c.at
        FROM run_checks c
        JOIN programming_runs r ON r.id = c.run_id
        WHERE c.device_unit_id = :d
        ORDER BY c.name, r.started_at DESC, c.run_id DESC
    """), {"d": device_id}).mappings().all()
    history = db.execute(text("""
        SELECT name, status, count(*) AS n
        FROM run_checks WHERE device_unit_id = :d GROUP BY 1, 2
    """), {"d": device_id}).fetchall()
    tally: dict[str, dict[str, int]] = {}
    for h in history:
        tally.setdefault(h.name, {})[h.status] = h.n
    out = []
    for r in rows:
        d = dict(r)
        d["at"] = d["at"].isoformat() if d["at"] else None
        d["attempts"] = tally.get(d["name"], {})
        out.append(d)
    return _sorted(out)


def counts_for_devices(db: Session, device_ids: list[int]) -> dict[int, dict[str, int]]:
    """pass/fail/unknown per device, newest run per check name — for the list."""
    if not device_ids:
        return {}
    rows = db.execute(text("""
        SELECT device_unit_id AS d, status, count(*) AS n FROM (
            SELECT DISTINCT ON (c.device_unit_id, c.name)
                   c.device_unit_id, c.name, c.status
            FROM run_checks c
            JOIN programming_runs r ON r.id = c.run_id
            WHERE c.device_unit_id = ANY(:ids)
            ORDER BY c.device_unit_id, c.name, r.started_at DESC, c.run_id DESC
        ) latest GROUP BY 1, 2
    """), {"ids": device_ids}).fetchall()
    out: dict[int, dict[str, int]] = {}
    for r in rows:
        out.setdefault(r.d, {})[r.status] = r.n
    return out


def _sorted(rows: list[dict]) -> list[dict]:
    order = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(rows, key=lambda r: (order.get(r["category"], 99), r["position"], r["name"]))
