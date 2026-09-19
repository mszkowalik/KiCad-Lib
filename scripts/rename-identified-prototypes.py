"""Give the identified prototypes their real serial, from the broker's topic.

Follow-up to `identify-prototype-dongles.py`, which filled the MAC and the topic
onto 14 `PROTO-xxxx` rows but left the placeholder serial in place.

The convention is not a guess. Across the 4,575 units that carry a MAC,
`tasmota_id = 'dongle_' || serial` holds for **4,561** of them, and `serial` is
the MAC without separators in whichever spelling the topic uses — the full 12
hex digits (2,280 units) or the last three bytes (2,281). These 14 devices
publish under the 6-hex topic, so their serial is that suffix.

The old placeholder number is kept in `notes`. It is what the 2026-09-18
reconciliation (decision 0036) and its document call these rows, and the
renaming must not make that document unreadable.

ONE-TIME. Run it through STDIN, never as a file:

    docker compose exec -T api python - < scripts/rename-identified-prototypes.py
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
ACTOR = "prototype-identification-2026-09-19"

NOTE = ("Identified {date} from the fleet broker: the device's own "
        "tasmota/discovery announcement reported MAC {mac} under topic {topic}. "
        "Recorded as {old} by the 2026-09-18 reconciliation (decision 0036).")
DATE = "2026-09-19"


def main():
    db = SessionLocal()
    try:
        rows = list(db.scalars(
            select(M.DeviceUnit)
            .where(M.DeviceUnit.serial.like("PROTO-%"),
                   M.DeviceUnit.mac.isnot(None), M.DeviceUnit.mac != "")
            .order_by(M.DeviceUnit.serial)))
        assert rows, "nothing to rename — has identify-prototype-dongles.py run?"

        plan = []
        for u in rows:
            assert u.tasmota_id.startswith("dongle_"), f"{u.serial}: odd topic {u.tasmota_id!r}"
            new = u.tasmota_id.split("_", 1)[1].upper()
            # The serial must still describe the MAC: the topic suffix is the
            # last three bytes, so it has to be a suffix of the address.
            flat = (u.mac or "").replace(":", "").upper()
            assert flat.endswith(new), f"{u.serial}: {new} is not a suffix of {u.mac}"
            clash = db.scalar(select(M.DeviceUnit).where(
                M.DeviceUnit.serial == new, M.DeviceUnit.id != u.id))
            assert clash is None, f"serial {new} already on device {clash.id}"
            plan.append((u, new))

        for u, new in plan:
            print(f"  {u.serial:<12} -> {new:<14} {u.mac}  ({u.tasmota_id})")
        print(f"\n{len(plan)} rows")

        if not WRITE:
            print("dry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        for u, new in plan:
            old = u.serial
            u.serial = new
            note = NOTE.format(date=DATE, mac=u.mac, topic=u.tasmota_id, old=old)
            u.notes = f"{u.notes.rstrip()}\n{note}" if u.notes else note
            db.add(M.AuditLog(
                action="device.rename", entity_type="device_unit", entity_id=str(u.id),
                actor=ACTOR, details={"from": old, "to": new, "mac": u.mac,
                                      "topic": u.tasmota_id,
                                      "source": "tasmota/discovery.mac"}))
        db.flush()

        # --- verify -------------------------------------------------------
        for u, new in plan:
            assert u.serial == new
            assert u.tasmota_id == f"dongle_{u.serial}", (
                f"{u.id}: topic {u.tasmota_id} no longer matches serial {u.serial}")
        left = db.query(M.DeviceUnit).filter(
            M.DeviceUnit.serial.like("PROTO-%")).count()
        print(f"renamed {len(plan)}; PROTO-xxxx rows left: {left} (expected 31)")
        assert left == 31, f"expected 31 unidentified prototypes, found {left}"

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print("\nAPPLIED.")
    finally:
        db.close()


main()
