"""Give every assembled DotConnect board one placeholder unit (decision 0092).

The DC boards (DC_GPS, DC_LIDAR, DC_BMS, DC_Temp) have no MAC and no serial,
and no API creates a device unit. Each assembly batch gets one unit per board
it assembled: `mac` NULL, `serial` empty, `condition` ok, and a `produced`
event at the batch date (0039 items 1, 2 and 4; 0092 item 2). A batch that
already has a unit is refused, so the script cannot run twice.

ONE-TIME. Run it through STDIN (api/CLAUDE.md):

    docker compose -p kicadlib -f docker-compose.kicadlib.yml exec -T kicadlib-api python - < scripts/dc-placeholder-units-2026-10-15.py
    ... exec -T -e REHEARSE=1 kicadlib-api python - < scripts/…   (writes, then rolls back)
    ... exec -T -e APPLY=1 kicadlib-api python - < scripts/…      (commits)
"""
import os
from datetime import UTC, datetime

from sqlalchemy import func, select

from app import models as M
from app.db import SessionLocal
from app.services import orders as osvc

assert M.__file__ == "/srv/app/models.py", f"stale app package: {M.__file__}"

APPLY = os.environ.get("APPLY") == "1"
REHEARSE = os.environ.get("REHEARSE") == "1"
WRITE = APPLY or REHEARSE
ACTOR = "dc-units-2026-10-15"

# run id -> (project, label it must carry, boards assembled)
BATCHES = {
    10740: ("DC_GPS", "V1 hand build 1 — 4 boards", 4),
    10741: ("DC_GPS", "V1 hand build 2 — 5 boards", 5),
    10742: ("DC_GPS", "JLC Y41 — 6 boards", 6),
    10743: ("DC_GPS", "JLC Y58 — 5 boards", 5),
    10744: ("DC_GPS", "JLC Y84 — 10 boards", 10),
    10734: ("DC_LIDAR", "V1 hand build 1 — 16 boards", 16),
    10735: ("DC_LIDAR", "V1 hand build 2 — 10 boards", 10),
    10736: ("DC_LIDAR", "JLC Y21 — 10 boards", 10),
    10737: ("DC_LIDAR", "JLC Y57 — 10 boards", 10),
    10739: ("DC_LIDAR", "JLC Y75 — 15 boards", 15),
    10745: ("DC_BMS", "V1 hand build — 10 boards", 10),
    10754: ("DC_BMS", "JLC Y20 (V1) — 10 boards", 10),
    10746: ("DC_BMS", "JLC Y42 — 7 boards", 7),
    10748: ("DC_BMS", "JLC Y42 reorder — 15 boards", 15),
    10749: ("DC_Temp", "Hand build — 10 boards", 10),
    10750: ("DC_Temp", "JLC P4 — 45 boards", 45),
    10751: ("DC_Temp", "JLC P8 — 127 boards", 127),
    10752: ("DC_Temp", "JLC P10 — 187 boards", 187),
}
NOTE = ("Placeholder unit for one board of an unserialised product (decision 0092): no MAC, "
        "no serial. The units of one batch are interchangeable. Created {date} by {actor}.")


def main():
    db = SessionLocal()
    try:
        plan = []
        for rid, (pname, label, n) in BATCHES.items():
            run = db.get(M.ProductionRun, rid)
            assert run is not None, f"no run {rid}"
            proj = db.get(M.Project, run.project_id)
            assert proj.name == pname, f"run {rid} is in {proj.name}, not {pname}"
            assert run.label == label, f"run {rid} is {run.label!r}, not {label!r}"
            assert run.qty == n, f"run {rid} records {run.qty} boards, not {n}"
            have = db.scalar(select(func.count()).select_from(M.DeviceEvent).where(
                M.DeviceEvent.kind == "produced", M.DeviceEvent.production_run_id == rid))
            assert have == 0, f"run {rid} already has {have} produced units — stop"
            y, m, d = (int(x) for x in run.run_date.split("-"))
            plan.append((run, proj, n, datetime(y, m, d, 12, 0, tzinfo=UTC)))
            print(f"  {pname:9} run {rid:>5} {label:30} +{n:>3} units produced {run.run_date}")
        print(f"  total {sum(p[2] for p in plan)} units")
        if not WRITE:
            print("dry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return
        made = 0
        for run, proj, n, at in plan:
            for _ in range(n):
                u = M.DeviceUnit(project_id=proj.id, mac=None, chip="", serial="", condition="ok",
                                 first_seen=at, last_seen=at,
                                 notes=NOTE.format(date="2026-10-15", actor=ACTOR))
                db.add(u)
                db.flush()
                osvc.mark_produced(db, u, run.id, at=at, actor=ACTOR,
                                   note="Placeholder unit of an unserialised board (decision 0092).")
                made += 1
            db.add(M.AuditLog(action="device.placeholders_created", entity_type="production_run",
                              entity_id=str(run.id), actor=ACTOR,
                              details={"units": n, "decision": "0092", "condition": "ok"}))
        db.flush()
        stock = db.scalar(select(func.count()).select_from(M.DeviceUnit).where(
            M.DeviceUnit.production_run_id.in_(list(BATCHES)), M.DeviceUnit.state == "in_stock"))
        print(f"  created {made}; in stock in these batches now {stock}")
        if APPLY:
            db.commit()
            print("committed")
        else:
            db.rollback()
            print("rehearsal — rolled back")
    finally:
        db.close()


main()
