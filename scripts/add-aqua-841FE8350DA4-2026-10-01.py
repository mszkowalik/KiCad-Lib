"""Put one hand-reported CE_Aqua_V2 unit on the platform, with its broker account.

User report 2026-10-01: the Aqua `84:1F:E8:35:0D:A4` was shipped to Columbus
Energy at some point, but the platform holds no record of it — no device row,
no programming run, no broker topic since the watcher started. Without a row,
the broker password file (`GET /api/flasher/mosquitto`) has no account for it,
and a regenerated file would lock it out.

User decisions 2026-10-01:

  * A NEW unit in Batch 5 (run 16), the batch of its MAC range, put IN STOCK
    with a `produced` event. It is NOT shipped here, although it was shipped:
    the note says so, and the delivery is cleaned up later.
  * Its account is `dongle_841FE8350DA4`, the 12-hex name every Aqua in the
    84:1f:e8:35 range carries, derived from the topic with the fleet salt —
    the same method and the same three config keys as decision 0054.

ONE-TIME. Run it through STDIN, never as a file:

    docker compose exec -T api python - < scripts/add-aqua-841FE8350DA4-2026-10-01.py
    docker compose exec -T -e REHEARSE=1 api python - < scripts/…
    docker compose exec -T -e APPLY=1 api python - < scripts/…
"""
import os

from sqlalchemy import func, select

from app import models as M
from app.db import SessionLocal
from app.routers.flasher import _mosquitto_file
from app.services import orders as osvc
from app.services.flasher import credentials

APPLY = os.environ.get("APPLY") == "1"
REHEARSE = os.environ.get("REHEARSE") == "1"
WRITE = APPLY or REHEARSE
ACTOR = "manual-device-2026-10-01"
DATE = "2026-10-01"

PROJECT = "CE_Aqua_V2"
RUN = 16
MAC = "84:1f:e8:35:0d:a4"
SERIAL = "841FE8350DA4"
TOPIC = f"dongle_{SERIAL}"

NOTE = (f"[{DATE}] Added by hand from a user report: MAC {MAC.upper()}, topic {TOPIC}. "
        "SHIPPED to Columbus Energy at an unknown date, but NOT recorded as shipped here — "
        "kept in stock on purpose until the delivery is cleaned up (user decision). "
        "Batch 5 is the batch of its MAC range, not a programming record. No programming "
        "run exists, so first_seen is the date of this record. MQTT account derived from "
        "the topic with the fleet salt (decision 0054 method).")


def fleet_salt(db):
    lines = db.scalars(select(M.DeviceConfigValue.value).where(
        M.DeviceConfigValue.key == "mqtt_creds_line")).all()
    salts = {line.partition(":")[2].split("$")[2] for line in lines}
    assert len(salts) == 1, f"{len(salts)} different salts in the stored lines — stop"
    return salts.pop()


def export_body(db):
    return _mosquitto_file(db, None).body.decode()


def run_stock(db):
    return db.query(M.DeviceUnit).filter(
        M.DeviceUnit.production_run_id == RUN, M.DeviceUnit.state == "in_stock",
        M.DeviceUnit.condition == "ok").count()


def main():
    db = SessionLocal()
    try:
        project = db.scalar(select(M.Project).where(M.Project.name == PROJECT))
        assert project is not None, f"no project {PROJECT}"
        run = db.get(M.ProductionRun, RUN)
        assert run is not None and run.project_id == project.id, f"run {RUN} is not a {PROJECT} run"
        assert run.label.startswith("Batch 5"), f"run {RUN} is {run.label!r}, not Batch 5"

        clash = db.scalar(select(M.DeviceUnit).where(
            (func.lower(M.DeviceUnit.mac) == MAC) | (func.upper(M.DeviceUnit.serial) == SERIAL)
            | (func.lower(M.DeviceUnit.tasmota_id) == TOPIC.lower())))
        assert clash is None, f"{MAC} / {TOPIC} already on device {clash.id} — stop"
        taken = db.scalar(select(func.count()).select_from(M.DeviceConfigValue).where(
            M.DeviceConfigValue.key == "mqtt_creds_line",
            func.split_part(M.DeviceConfigValue.value, ":", 1) == TOPIC))
        assert taken == 0, f"an account for {TOPIC} already exists — stop"
        presence = db.scalar(select(M.DevicePresence).where(M.DevicePresence.topic == TOPIC))
        assert presence is None or presence.device_unit_id is None, (
            f"{TOPIC} is linked to device {presence.device_unit_id} — stop")

        salt = fleet_salt(db)
        body = export_body(db)
        before = {"export": body.count("\n"), "stock": run_stock(db)}

        print(f"  NEW unit in run {RUN} ({run.label}), project {PROJECT}: {SERIAL} {MAC}, in stock")
        print(f"  account {TOPIC}, derived; presence row: {'link it' if presence else 'none'}")
        if not WRITE:
            print("dry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        # --- write: the unit, in stock in Batch 5 --------------------------------
        u = M.DeviceUnit(project_id=project.id, mac=MAC, chip="", tasmota_id=TOPIC,
                         serial=SERIAL, last_status="", notes=NOTE, condition="ok")
        db.add(u)
        db.flush()
        osvc.mark_produced(db, u, RUN, actor=ACTOR,
                           note="Added by hand; shipped to Columbus but not recorded as shipped.")
        if presence is not None:
            presence.device_unit_id = u.id
        db.add(M.AuditLog(
            action="device.created_by_hand", entity_type="device_unit", entity_id=str(u.id),
            actor=ACTOR,
            details={"serial": SERIAL, "mac": MAC, "topic": TOPIC, "run_id": RUN,
                     "state": "in_stock", "source": "user report 2026-10-01",
                     "shipped_not_recorded": "Columbus Energy, date unknown"}))

        # --- write: the account, as the engine stores one ------------------------
        username, password, s, final_hash = credentials.derive(TOPIC, "", salt)
        for key, value, secret in (
            ("mqtt_user", username, False),
            ("mqtt_password", password, True),
            ("mqtt_creds_line", credentials.mosquitto_line(username, s, final_hash), True),
        ):
            db.add(M.DeviceConfigValue(device_unit_id=u.id, key=key, value=value,
                                       is_secret=secret, set_by_run_id=None, current=True))
        db.add(M.AuditLog(
            action="device.credentials_derived", entity_type="device_unit", entity_id=str(u.id),
            actor=ACTOR,
            details={"mqtt_user": username, "current": True,
                     "source": "derived from the topic with the fleet salt "
                               "(credentials.derive); no programming run set it",
                     "decision": "0054"}))
        db.flush()

        # --- verify through the platform's own read paths ------------------------
        db.refresh(u)
        assert (u.state, u.production_run_id) == ("in_stock", RUN), (u.state, u.production_run_id)
        assert u.tasmota_id == "dongle_" + u.serial
        after_stock = run_stock(db)
        print(f"run {RUN} in stock (ok): {before['stock']} -> {after_stock}")
        assert after_stock == before["stock"] + 1

        body = export_body(db)
        after_export = body.count("\n")
        print(f"mosquitto export lines: {before['export']} -> {after_export}")
        assert after_export == before["export"] + 1
        assert f"{TOPIC}:{password}\n" in body, f"{TOPIC} is not in the export"
        assert credentials.derive(TOPIC, password, salt)[3] == final_hash
        print(f"{TOPIC} is in the export, and its password checks against its stored hash")

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print(f"\nAPPLIED. New unit id {u.id}.")
    finally:
        db.close()


main()
