"""Identify the last two groups the broker found: 7 V3 prototypes, 8 V2 dongles.

Follow-up to `identify-prototype-dongles.py` and `rename-identified-prototypes.py`.
Same shape: fill rows that already exist, never create one, so no count moves.

WHAT THE EVIDENCE IS, AND IS NOT. The MAC and the topic come from each device's
own `tasmota/discovery` announcement, so the identity of the DEVICE is the
device's own word. Which anonymous row it goes into is a JUDGEMENT the user made
(2026-09-19), not something the data proves:

  * The 7 `CE_Dongle_V3_2` devices go into run 20, "Run #2 - prototypes V3.3".
    Their `hw_model` says V3_2, which names run 17, and their addresses span
    Δ138,112 — wider than a 10-piece lot should. User chose run 20 anyway.
  * The 8 `CE_Dongle_v2` devices on Tasmota 14.x go into `PH-0001..0008`, the
    placeholders for the 2026-09-03 delivery. Their OUI `fc:b4:67` appears in NO
    recorded batch, and no unit in the platform matches them under any spelling
    — checked four ways, including the MAC's last three bytes against every
    MAC-less unit's 6-hex id. The delivery is where they PLAUSIBLY came from.

So `condition` is deliberately NOT touched. The 8 stay `unidentified` until a
physical stock check confirms the serials, and the 7 stay `prototype`. `state`
is left alone too: it is a cache of the newest DeviceEvent and must not be
hand-edited — the 7 still read `in_stock` while being deployed, which is a
separate correction needing a real event.

ONE-TIME. Run it through STDIN, never as a file:

    docker compose exec -T api python - < scripts/identify-broker-discoveries.py
    docker compose exec -T -e REHEARSE=1 api python - < scripts/…
    docker compose exec -T -e APPLY=1 api python - < scripts/…
"""
import os

from app.db import SessionLocal
from app import models as M
from sqlalchemy import select

APPLY = os.environ.get("APPLY") == "1"
REHEARSE = os.environ.get("REHEARSE") == "1"
WRITE = APPLY or REHEARSE
ACTOR = "broker-identification-2026-09-19"
DATE = "2026-09-19"
UNLINKED_BEFORE = 55

# 7 x CE_Dongle_V3_2 -> the ten blank prototype rows of run 20
V3 = [
    "dongle_588C812E9428", "dongle_588C812E9CAC", "dongle_588C812EB1E8",
    "dongle_588C812EEDB8", "dongle_588C812F7474", "dongle_588C8130AFA8",
    "dongle_ACEBE6D25990",
]
# 8 x CE_Dongle_v2 on Tasmota 14.x -> PH-0001..PH-0008.
# NOT dongle_A99AF8: that is a topic-spelling mismatch for unit 5529, which
# already holds c0:5d:89:a9:9a:f8. It is Group A and must not be filled here.
V2 = [
    "dongle_86CBD4", "dongle_86DE38", "dongle_86E6B8", "dongle_876BE0",
    "dongle_879AB0", "dongle_87A558", "dongle_881214", "dongle_88159C",
]

NOTE = ("Identified {date} from the fleet broker: the device's own "
        "tasmota/discovery announcement reported MAC {mac} under topic {topic}. "
        "{origin} Serial not yet confirmed by a physical stock check.")


def presence(db, topic):
    p = db.scalar(select(M.DevicePresence).where(M.DevicePresence.topic == topic))
    assert p is not None, f"no presence row for {topic}"
    assert p.device_unit_id is None, f"{topic} already linked to {p.device_unit_id}"
    assert p.reported_mac, f"{topic} has never reported a MAC"
    return p


def main():
    db = SessionLocal()
    try:
        # --- the rows that will receive an identity -----------------------
        v3_rows = list(db.scalars(
            select(M.DeviceUnit)
            .where(M.DeviceUnit.production_run_id == 20, M.DeviceUnit.tasmota_id == "",
                   (M.DeviceUnit.mac.is_(None)) | (M.DeviceUnit.mac == ""))
            .order_by(M.DeviceUnit.id)))
        ph_rows = list(db.scalars(
            select(M.DeviceUnit)
            .where(M.DeviceUnit.serial.like("PH-%"), M.DeviceUnit.tasmota_id == "",
                   (M.DeviceUnit.mac.is_(None)) | (M.DeviceUnit.mac == ""))
            .order_by(M.DeviceUnit.serial)))
        assert len(v3_rows) >= len(V3), f"run 20 has {len(v3_rows)} blank rows, need {len(V3)}"
        assert len(ph_rows) >= len(V2), f"only {len(ph_rows)} PH rows free, need {len(V2)}"

        plan = []
        for topic, u in list(zip(V3, v3_rows)) + list(zip(V2, ph_rows)):
            p = presence(db, topic)
            mac = p.reported_mac.lower()
            clash = db.scalar(select(M.DeviceUnit).where(M.DeviceUnit.mac == mac))
            assert clash is None, f"{mac} already on device {clash.id} — stop"
            new_serial = topic.split("_", 1)[1].upper()
            assert (mac.replace(":", "").upper()).endswith(new_serial), (
                f"{new_serial} is not a suffix of {mac}")
            sclash = db.scalar(select(M.DeviceUnit).where(
                M.DeviceUnit.serial == new_serial, M.DeviceUnit.id != u.id))
            assert sclash is None, f"serial {new_serial} already on device {sclash.id}"
            plan.append((u, p, mac, topic, new_serial))

        for u, p, mac, topic, serial in plan:
            was = u.serial or f"(blank, run {u.production_run_id})"
            print(f"  {was:<22} -> {serial:<14} {mac}  [{p.hw_model}]")
        print(f"\n{len(plan)} rows")
        if not WRITE:
            print("dry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        # --- write --------------------------------------------------------
        for u, p, mac, topic, serial in plan:
            old = u.serial
            origin = (f"Recorded as {old} by the 2026-09-18 reconciliation "
                      f"(decision 0036)." if old else
                      "Filled a blank prototype row of its production run.")
            u.mac = mac
            u.tasmota_id = topic
            u.serial = serial
            note = NOTE.format(date=DATE, mac=mac, topic=topic, origin=origin)
            u.notes = f"{u.notes.rstrip()}\n{note}" if u.notes else note
            db.flush()
            p.device_unit_id = u.id
            db.add(M.AuditLog(
                action="device.identified_from_broker", entity_type="device_unit",
                entity_id=str(u.id), actor=ACTOR,
                details={"from_serial": old, "to_serial": serial, "mac": mac,
                         "topic": topic, "hw_model": p.hw_model,
                         "source": "tasmota/discovery.mac",
                         "run_id": u.production_run_id,
                         "condition_unchanged": u.condition}))
        db.flush()

        # --- verify against the platform's own read paths -----------------
        from app.services import orders as osvc

        # PH-0001..0008 were shipped against order line 22; filling them must
        # not change what that line delivered.
        line_ids = sorted({e.order_line_id for u, *_ in plan
                           for e in u.events if e.order_line_id})
        if line_ids:
            for lid, c in osvc._line_counts(db, line_ids).items():
                print(f"line {lid}: shipped {c['shipped']} + unserialized "
                      f"{c['unserialized']} = {c['shipped'] + c['unserialized']}")

        bad = db.query(M.DeviceUnit).filter(
            M.DeviceUnit.mac.isnot(None), M.DeviceUnit.mac != "",
            M.DeviceUnit.serial != "",
            M.DeviceUnit.tasmota_id != "dongle_" + M.DeviceUnit.serial).count()
        assert bad == 0, f"{bad} units break tasmota_id = 'dongle_' || serial"
        print("naming invariant holds for every unit carrying a MAC")

        unlinked = db.query(M.DevicePresence).filter(
            M.DevicePresence.device_unit_id.is_(None)).count()
        print(f"presence rows still unlinked: {unlinked} (was {UNLINKED_BEFORE})")
        assert unlinked == UNLINKED_BEFORE - len(plan), (
            f"expected {UNLINKED_BEFORE - len(plan)}, got {unlinked}")

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print("\nAPPLIED.")
    finally:
        db.close()


main()
