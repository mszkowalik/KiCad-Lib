"""Fill 4 CE_Dongle_V3 Run #1 (V3.2) prototype placeholders with their MACs.

User facts 2026-10-03: the four record-less V3.2 units on the desk ARE Run #1
builds. They were read over USB on 2026-10-02 (`~/dongles_v3_2.json`, copied
to reports/stock-count-2026-10-02/readouts/): three with an erased flash, one
running Tasmota with the unconfigured default topic. The 0054 pattern: a
discovered identity fills an existing placeholder, never a new record.

The four lowest-id MAC-less placeholders of Run #1 get the MACs. State stays
`in_stock`, condition stays `prototype` (they never ship, decision 0039). No
MQTT accounts: none of these is linked to a broker topic (0054 grants an
account only then).

ONE-TIME. Run through STDIN (api/CLAUDE.md):

    docker compose exec -T api python - < scripts/fill-v3-placeholders-2026-10-03.py
    docker compose exec -T -e REHEARSE=1 api python - < scripts/…
    docker compose exec -T -e APPLY=1 api python - < scripts/…
"""
import os

from sqlalchemy import func, select

from app import models as M
from app.db import SessionLocal

assert M.__file__ == "/srv/app/models.py", f"stale app package: {M.__file__}"

APPLY = os.environ.get("APPLY") == "1"
REHEARSE = os.environ.get("REHEARSE") == "1"
WRITE = APPLY or REHEARSE
ACTOR = "stock-count-2026-10-02"
DATE = "2026-10-03"
RUN_LABEL = "Run #1 - prototypes V3.2"
REF = "docs/reference/stock-count-2026-10.md"

# MAC -> (what the unit showed on 2026-10-02, observed topic or "")
UNITS = {
    "58:8c:81:2e:a4:54": ("erased flash (invalid header: 0xffffffff)", ""),
    "58:8c:81:30:af:ac": ("erased flash (invalid header: 0xffffffff)", ""),
    "58:8c:81:2f:78:8c": ("erased flash (invalid header: 0xffffffff)", ""),
    "58:8c:81:30:af:b0": ("Tasmota, unconfigured default topic", "tasmota_588C8130AFB0"),
}


def main():
    db = SessionLocal()
    try:
        run = db.scalar(select(M.ProductionRun).where(M.ProductionRun.label == RUN_LABEL))
        assert run is not None, f"no run labelled {RUN_LABEL!r}"
        for mac in UNITS:
            clash = db.scalar(select(M.DeviceUnit).where(func.lower(M.DeviceUnit.mac) == mac))
            assert clash is None, f"{mac} already on device {clash.id} — stop"
        holes = db.scalars(
            select(M.DeviceUnit).where(
                M.DeviceUnit.production_run_id == run.id, M.DeviceUnit.mac.is_(None),
                M.DeviceUnit.state == "in_stock", M.DeviceUnit.condition == "prototype")
            .order_by(M.DeviceUnit.id)).all()
        assert len(holes) >= len(UNITS), f"only {len(holes)} open placeholders — stop"

        pairs = list(zip(holes, UNITS.items()))
        for d, (mac, (seen, _topic)) in pairs:
            print(f"  #{d.id} <- {mac}  ({seen})")
        if not WRITE:
            print("dry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        for d, (mac, (seen, topic)) in pairs:
            d.mac = mac
            d.serial = mac.replace(":", "").upper()
            if topic:
                d.tasmota_id = topic
            d.notes = ((d.notes + "\n") if d.notes else "") + (
                f"[{DATE}] Identified at the stock count: MAC read over USB on 2026-10-02, "
                f"the unit showed {seen}. Run #1 build per the user. See {REF}")
            db.add(M.AuditLog(
                action="device.identified", entity_type="device_unit", entity_id=str(d.id),
                actor=ACTOR,
                details={"mac": mac, "serial": d.serial, "seen": seen,
                         "source": "2026-10-02 desk readout + user confirmation 2026-10-03",
                         "pattern": "0054: a discovered identity fills a placeholder"}))
        db.flush()
        for d, (mac, _) in pairs:
            db.refresh(d)
            assert (d.mac, d.state, d.condition) == (mac, "in_stock", "prototype")
        left = db.scalar(select(func.count()).select_from(M.DeviceUnit).where(
            M.DeviceUnit.production_run_id == run.id, M.DeviceUnit.mac.is_(None)))
        print(f"filled {len(pairs)}; {left} placeholders of {RUN_LABEL} remain unnamed")

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print("\nAPPLIED.")
    finally:
        db.close()


main()
