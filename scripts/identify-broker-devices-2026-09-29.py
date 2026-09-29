"""Name the last broker discoveries, and give every named device a broker account.

Follow-up to `identify-broker-discoveries.py` (decision 0046), which left these
open. User decisions 2026-09-29, recorded in decision 0054:

  * The 10 `08:d1:f9` Aqua devices fill 10 of the 20 SHIPPED placeholder rows
    of run 10733, the Aqua half of the 2024-02 prototype build. Same shape as
    0046: fill rows that already exist, never create one, so order line 17
    still delivers exactly what it delivered.
  * `dongle_ACEBE6D34698` is one device of the latest V3 batch (run 2164),
    programmed on 2026-09-29 outside the platform. It gets a NEW unit, in stock:
    no placeholder stands for it, and a `produced` event is the only way to put
    a unit in stock (`state` is a cache of the newest event).
  * `dongle_405038` (a customer's ESP32 dev kit) and `cedonglev3ppp` are not
    ours. They stay unlinked. Nothing here touches them.
  * `dongle_C82E189E4F38` is a second name of unit 81 (the topic IS unit 81's
    MAC). It gets a broker account here, but NOT a presence link: the device
    page, the project device list and the bench checks all assume one presence
    row per unit, and a second row would list unit 81 twice.

THE ACCOUNTS. 29 devices named from the broker by 0046, and the 11 named here,
connect with passwords the platform never stored, because no programming run
of theirs is on record. The password was always derived the same way (user,
2026-09-29): `credentials.derive(topic, "", fleet salt)`. The salt is read
from the stored lines and must be the single salt every one of them uses. Each
account is written as the programming engine writes one — `mqtt_user`,
`mqtt_password`, `mqtt_creds_line` — with `set_by_run_id` NULL, because no run
set it, and an AuditLog row that says so.

ONE-TIME. Run it through STDIN, never as a file:

    docker compose exec -T api python - < scripts/identify-broker-devices-2026-09-29.py
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
ACTOR = "broker-identification-2026-09-29"
DATE = "2026-09-29"

AQUA_RUN = 10733
AQUA_LINE = 17
AQUA = [
    "dongle_51EDC0", "dongle_51EDC8", "dongle_51EDD0", "dongle_51EDD4",
    "dongle_51EDD8", "dongle_51EDF0", "dongle_51EDF8", "dongle_51EE08",
    "dongle_51EE14", "dongle_51EE24",
]
V3_TOPIC = "dongle_ACEBE6D34698"
V3_RUN = 2164
UNIT81 = 81
UNIT81_TOPIC = "dongle_C82E189E4F38"
NOT_OURS = ("dongle_405038", "cedonglev3ppp")

NOTE = ("Identified {date} from the fleet broker: the device's own "
        "tasmota/discovery announcement reported MAC {mac} under topic {topic}. "
        "{origin} (decision 0054)")


def presence(db, topic):
    p = db.scalar(select(M.DevicePresence).where(M.DevicePresence.topic == topic))
    assert p is not None, f"no presence row for {topic}"
    assert p.device_unit_id is None, f"{topic} already linked to {p.device_unit_id}"
    assert p.reported_mac, f"{topic} has never reported a MAC"
    return p


def check_identity(db, topic, mac, unit_id=None):
    serial = topic.split("_", 1)[1].upper()
    assert mac.replace(":", "").upper().endswith(serial), f"{serial} is not a suffix of {mac}"
    clash = db.scalar(select(M.DeviceUnit).where(M.DeviceUnit.mac == mac))
    assert clash is None, f"{mac} already on device {clash.id} — stop"
    sclash = db.scalar(select(M.DeviceUnit).where(
        (M.DeviceUnit.serial == serial) | (M.DeviceUnit.tasmota_id == topic),
        M.DeviceUnit.id != (unit_id or 0)))
    assert sclash is None, f"{serial} / {topic} already on device {sclash.id}"
    return serial


def fleet_salt(db):
    lines = db.scalars(select(M.DeviceConfigValue.value).where(
        M.DeviceConfigValue.key == "mqtt_creds_line")).all()
    salts = {line.partition(":")[2].split("$")[2] for line in lines}
    assert len(salts) == 1, f"{len(salts)} different salts in the stored lines — stop"
    return salts.pop()


def accounts(db):
    return set(db.scalars(select(func.split_part(M.DeviceConfigValue.value, ":", 1)).where(
        M.DeviceConfigValue.key == "mqtt_creds_line")).all())


def export_lines(db):
    return _mosquitto_file(db, None).body.decode().count("\n")


def counts(db):
    return osvc._line_counts(db, [AQUA_LINE])[AQUA_LINE]


def main():
    db = SessionLocal()
    try:
        salt = fleet_salt(db)
        before = {
            "line": counts(db),
            "export": export_lines(db),
            "unlinked": db.query(M.DevicePresence).filter(
                M.DevicePresence.device_unit_id.is_(None)).count(),
        }

        # --- plan: the 10 Aqua devices into run 10733's shipped blanks -----
        rows = list(db.scalars(
            select(M.DeviceUnit)
            .where(M.DeviceUnit.production_run_id == AQUA_RUN, M.DeviceUnit.tasmota_id == "",
                   M.DeviceUnit.mac.is_(None), M.DeviceUnit.state == "shipped")
            .order_by(M.DeviceUnit.id)))
        assert len(rows) >= len(AQUA), f"run {AQUA_RUN} has {len(rows)} shipped blanks"
        fills = []
        for topic, u in zip(AQUA, rows):
            p = presence(db, topic)
            mac = p.reported_mac.lower()
            assert mac.startswith("08:d1:f9:"), f"{topic} reports {mac}, not the 08:d1:f9 lot"
            fills.append((u, p, mac, topic, check_identity(db, topic, mac, u.id)))

        # --- plan: the new V3 unit ------------------------------------------
        run = db.get(M.ProductionRun, V3_RUN)
        assert run is not None and run.project_id == 1, f"run {V3_RUN} is not a CE_Dongle_V3 run"
        v3p = presence(db, V3_TOPIC)
        v3mac = v3p.reported_mac.lower()
        v3serial = check_identity(db, V3_TOPIC, v3mac)

        # --- plan: unit 81's second name --------------------------------------
        u81 = db.get(M.DeviceUnit, UNIT81)
        assert u81.mac and u81.mac.replace(":", "").upper() == UNIT81_TOPIC.split("_")[1], (
            f"{UNIT81_TOPIC} is not unit 81's MAC")

        for u, p, mac, topic, serial in fills:
            print(f"  unit {u.id} (blank, run {AQUA_RUN}) -> {serial:<14} {mac}  [{p.hw_model}]")
        print(f"  NEW unit in run {V3_RUN} ({run.label})  -> {v3serial} {v3mac}  [{v3p.hw_model}], in stock")
        print(f"  unit 81 keeps {u81.tasmota_id}; account added for {UNIT81_TOPIC}, no presence link")
        if not WRITE:
            print("dry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        # --- write: fills -----------------------------------------------------
        for u, p, mac, topic, serial in fills:
            u.mac, u.tasmota_id, u.serial = mac, topic, serial
            note = NOTE.format(date=DATE, mac=mac, topic=topic,
                               origin=f"Filled a shipped placeholder row of run {AQUA_RUN}.")
            u.notes = f"{u.notes.rstrip()}\n{note}" if u.notes else note
            db.flush()
            p.device_unit_id = u.id
            db.add(M.AuditLog(
                action="device.identified_from_broker", entity_type="device_unit",
                entity_id=str(u.id), actor=ACTOR,
                details={"from_serial": "", "to_serial": serial, "mac": mac, "topic": topic,
                         "hw_model": p.hw_model, "source": "tasmota/discovery.mac",
                         "run_id": AQUA_RUN, "condition_unchanged": u.condition,
                         "decision": "0054"}))

        # --- write: the new V3 unit -------------------------------------------
        note = NOTE.format(date=DATE, mac=v3mac, topic=V3_TOPIC,
                           origin=(f"Programmed {DATE} outside the platform, so no programming "
                                   f"run exists; first_seen is the broker's first sighting."))
        v3 = M.DeviceUnit(project_id=run.project_id, mac=v3mac, chip="", tasmota_id=V3_TOPIC,
                          serial=v3serial, first_seen=v3p.first_seen_at,
                          last_seen=v3p.first_seen_at, last_status="", notes=note,
                          condition="ok")
        db.add(v3)
        db.flush()
        osvc.mark_produced(db, v3, V3_RUN, at=v3p.first_seen_at, actor=ACTOR,
                           note="Named from the fleet broker (decision 0054).")
        v3p.device_unit_id = v3.id
        db.add(M.AuditLog(
            action="device.created_from_broker", entity_type="device_unit",
            entity_id=str(v3.id), actor=ACTOR,
            details={"serial": v3serial, "mac": v3mac, "topic": V3_TOPIC,
                     "hw_model": v3p.hw_model, "source": "tasmota/discovery.mac",
                     "run_id": V3_RUN, "state": "in_stock", "decision": "0054"}))
        db.flush()

        # --- write: an account for every linked device that has none ----------
        have = accounts(db)
        targets = [(p.device_unit_id, p.topic) for p in db.scalars(
            select(M.DevicePresence).where(M.DevicePresence.device_unit_id.isnot(None)))
            if p.topic not in have]
        targets.append((UNIT81, UNIT81_TOPIC))
        for unit_id, topic in targets:
            assert len(topic.split("_")) == 2, f"{topic} is not a dongle_<id> name"
            current = db.scalar(select(func.count()).select_from(M.DeviceConfigValue).where(
                M.DeviceConfigValue.device_unit_id == unit_id,
                M.DeviceConfigValue.key == "mqtt_user",
                M.DeviceConfigValue.current.is_(True))) == 0
            username, password, s, final_hash = credentials.derive(topic, "", salt)
            for key, value, secret in (
                ("mqtt_user", username, False),
                ("mqtt_password", password, True),
                ("mqtt_creds_line", credentials.mosquitto_line(username, s, final_hash), True),
            ):
                db.add(M.DeviceConfigValue(device_unit_id=unit_id, key=key, value=value,
                                           is_secret=secret, set_by_run_id=None,
                                           current=current))
            db.add(M.AuditLog(
                action="device.credentials_derived", entity_type="device_unit",
                entity_id=str(unit_id), actor=ACTOR,
                details={"mqtt_user": username, "current": current,
                         "source": "derived from the topic with the fleet salt "
                                   "(credentials.derive); no programming run set it",
                         "decision": "0054"}))
        db.flush()
        print(f"\n{len(fills)} filled, 1 created, {len(targets)} accounts derived")

        # --- verify through the platform's own read paths -----------------------
        after_line = counts(db)
        print(f"order line {AQUA_LINE}: {before['line']} -> {after_line}")
        assert after_line == before["line"], "order line 17 changed — stop"

        bad = db.query(M.DeviceUnit).filter(
            M.DeviceUnit.mac.isnot(None), M.DeviceUnit.mac != "", M.DeviceUnit.serial != "",
            M.DeviceUnit.tasmota_id != "dongle_" + M.DeviceUnit.serial).count()
        assert bad == 0, f"{bad} units break tasmota_id = 'dongle_' || serial"

        db.refresh(v3)
        assert (v3.state, v3.production_run_id) == ("in_stock", V3_RUN), (v3.state, v3.production_run_id)

        doubled = db.execute(
            select(M.DevicePresence.device_unit_id).where(M.DevicePresence.device_unit_id.isnot(None))
            .group_by(M.DevicePresence.device_unit_id).having(func.count() > 1)).all()
        assert not doubled, f"units with two presence rows: {doubled}"

        unlinked = db.query(M.DevicePresence).filter(
            M.DevicePresence.device_unit_id.is_(None)).count()
        print(f"unlinked presence rows: {before['unlinked']} -> {unlinked}")
        assert unlinked == before["unlinked"] - len(fills) - 1

        after_export = export_lines(db)
        print(f"mosquitto export lines: {before['export']} -> {after_export}")
        assert after_export == before["export"] + len(targets)

        have = accounts(db)
        missing = sorted(p.topic for p in db.scalars(select(M.DevicePresence))
                         if p.topic not in have)
        print(f"broker topics with no account: {missing}")
        assert missing == sorted(NOT_OURS), missing

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print(f"\nAPPLIED. New V3 unit id {v3.id}.")
    finally:
        db.close()


main()
