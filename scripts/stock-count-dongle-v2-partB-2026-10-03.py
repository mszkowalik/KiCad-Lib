"""Apply the CE_Dongle_V2 stock count, part B: two Batch 5 units on the shelf.

Decision 0057. Evidence in the CE_Dongle_V2 section of
docs/reference/stock-count-2026-10.md. Both units were read on the shelf on
2026-10-02 (`dongles_v2.json`, 20:36:59 and 20:39:05) and are fully assembled
with an enclosure (user, 2026-10-03): condition `ok`, sellable.

  1. #3008 `dongle_4D8694` (Batch 5): UNSHIP from shipment #23 (ZAL
     00001/07/2025, 2025-09-29, an oldest-first pick). Back to stock.
  2. One `unidentified` placeholder (no MAC, Batch 5) takes #3008's place on
     shipment #23, so the order keeps its invoiced 455 — the shape of the
     Aqua correction's placeholders on shipment #19.
  3. `20:43:a8:4d:81:74` `dongle_2043A84D8174`: a NEW record in Batch 5 (its
     MAC range, and its first bench attempt of 2025-08-23 sat in the Batch 5
     window), produced at its passing bench run of 2026-09-10 16:12:56, in
     stock. With its broker account, derived from the topic with the fleet
     salt (decision 0054 method). The bench report's password for it hashes to
     REPORT_PW_SHA256 — the script checks the derivation against that.

ONE-TIME. Run it through STDIN, never as a file (api/CLAUDE.md):

    docker compose exec -T api python - < scripts/stock-count-dongle-v2-partB-2026-10-03.py
    docker compose exec -T -e REHEARSE=1 api python - < scripts/…
    docker compose exec -T -e APPLY=1 api python - < scripts/…
"""
import hashlib
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app import models as M
from app.db import SessionLocal
from app.routers.flasher import _mosquitto_file
from app.services import orders as osvc
from app.services.flasher import credentials

assert M.__file__ == "/srv/app/models.py", f"stale app package: {M.__file__}"

APPLY = os.environ.get("APPLY") == "1"
REHEARSE = os.environ.get("REHEARSE") == "1"
WRITE = APPLY or REHEARSE
ACTOR = "stock-count-2026-10-02"
DATE = "2026-10-03"
REF = "docs/reference/stock-count-2026-10.md"

PROJECT = "CE_Dongle_V2"
BATCH_5 = 9
ORDER_9, SHIP_23, SHIP_23_DATE = "ZAL 00001/07/2025", 23, "2025-09-29"
SHELF_UNIT = 3008
MAC, SERIAL = "20:43:a8:4d:81:74", "2043A84D8174"
TOPIC = f"dongle_{SERIAL}"
PASSED_AT = datetime(2026, 9, 10, 16, 12, 56, tzinfo=ZoneInfo("Europe/Warsaw"))
REPORT_PW_SHA256 = "6283e57c7b6358e1368c85174736df5d3106dfdea7841cb4231a40e9e7f19cdb"


def fleet_salt(db):
    lines = db.scalars(select(M.DeviceConfigValue.value).where(
        M.DeviceConfigValue.key == "mqtt_creds_line")).all()
    salts = {line.partition(":")[2].split("$")[2] for line in lines}
    assert len(salts) == 1, f"{len(salts)} different salts in the stored lines — stop"
    return salts.pop()


def main():
    db = SessionLocal()
    try:
        project = db.scalar(select(M.Project).where(M.Project.name == PROJECT))
        assert project is not None
        b5 = db.get(M.ProductionRun, BATCH_5)
        assert b5.project_id == project.id and b5.label.startswith("Batch 5"), b5.label
        o9 = db.scalar(select(M.SalesOrder).where(M.SalesOrder.order_ref == ORDER_9))
        sh23 = db.get(M.Shipment, SHIP_23)
        assert o9 is not None and sh23 is not None and sh23.order_id == o9.id, "order 9 / shipment 23 — stop"
        lines = [li for li in o9.lines if li.project_id == project.id]
        assert len(lines) == 1, f"{ORDER_9}: {len(lines)} dongle lines — stop"
        li9 = lines[0]

        d3008 = db.get(M.DeviceUnit, SHELF_UNIT)
        assert d3008.project_id == project.id and d3008.tasmota_id == "dongle_4D8694"
        assert (d3008.state, d3008.condition, d3008.production_run_id) == ("shipped", "ok", BATCH_5), (
            d3008.state, d3008.condition, d3008.production_run_id)
        assert [e.shipment_id for e in osvc.live_shipped_of(d3008)] == [SHIP_23]

        clash = db.scalar(select(M.DeviceUnit).where(
            (func.lower(M.DeviceUnit.mac) == MAC) | (func.upper(M.DeviceUnit.serial) == SERIAL)
            | (func.lower(M.DeviceUnit.tasmota_id) == TOPIC.lower())))
        assert clash is None, f"{MAC} / {TOPIC} already on device {clash.id} — stop"
        taken = db.scalar(select(func.count()).select_from(M.DeviceConfigValue).where(
            M.DeviceConfigValue.key == "mqtt_creds_line",
            func.split_part(M.DeviceConfigValue.value, ":", 1) == TOPIC))
        assert taken == 0, f"an account for {TOPIC} already exists — stop"
        presence = db.scalar(select(M.DevicePresence).where(M.DevicePresence.topic == TOPIC))
        assert presence is None or presence.device_unit_id is None, presence.device_unit_id

        salt = fleet_salt(db)
        username, password, s, final_hash = credentials.derive(TOPIC, "", salt)
        assert hashlib.sha256(password.encode()).hexdigest() == REPORT_PW_SHA256, (
            "the derived password is not the one the bench programmed — stop")

        def stock():
            p = next(x for x in osvc.product_stock(db) if x["project_id"] == project.id)
            return {k: p[k] for k in ("in_stock", "available", "shipped", "missing")}

        before = {"order 9 dongle line": osvc.line_shipped(li9), **stock(),
                  "export": _mosquitto_file(db, None).body.decode().count("\n")}
        assert before["order 9 dongle line"] == li9.qty_ordered, before

        print(f"{ORDER_9} dongle line {li9.id}: {before['order 9 dongle line']}/{li9.qty_ordered} shipped")
        print(f"1. unship #{SHELF_UNIT} dongle_4D8694 from shipment #{SHIP_23} -> in stock, ok")
        print(f"2. one unidentified Batch 5 placeholder onto shipment #{SHIP_23}, dated {SHIP_23_DATE}")
        print(f"3. new unit {SERIAL} {MAC}, Batch 5, produced {PASSED_AT.isoformat()}, in stock, ok; "
              f"account {TOPIC} (derivation matches the bench report)"
              + ("; link its presence row" if presence else ""))
        if not WRITE:
            print("\ndry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        # 1 ----------------------------------------------------------------------
        osvc.unship_device(db, d3008, shipment_id=SHIP_23, actor=ACTOR, dry_run=False,
                           note=f"[{DATE}] on the shelf at the stock count (read 2026-10-02 20:39:05); "
                                f"this delivery never carried it. See {REF}")
        d3008.notes = ((d3008.notes + "\n") if d3008.notes else "") + (
            f"[{DATE}] On the shelf, fully assembled with an enclosure (user). Was recorded on "
            f"shipment #{SHIP_23} by an oldest-first pick; never heard on the broker. See {REF}")
        db.flush()

        # 2 ----------------------------------------------------------------------
        note = (f"[{DATE}] Placeholder: the unit that shipment #{SHIP_23} ({ORDER_9}) delivered in "
                f"the place of #{SHELF_UNIT} dongle_4D8694, which was on the shelf. Fill it when the "
                f"broker or the customer names the real unit. Decision 0057, {REF}")
        at23 = osvc._date_at(SHIP_23_DATE)
        ph = M.DeviceUnit(project_id=project.id, mac=None, serial="", chip="", tasmota_id="",
                          last_status="", notes=note, condition="unidentified")
        db.add(ph)
        db.flush()
        osvc.record_event(db, ph, "produced", at=at23, actor=ACTOR, production_run_id=BATCH_5,
                          note="placeholder for an unidentified delivered unit")
        osvc._ship_device(db, sh23, li9, ph, at=at23, actor=ACTOR, note=note)
        db.flush()

        # 3 ----------------------------------------------------------------------
        u = M.DeviceUnit(project_id=project.id, mac=MAC, chip="", tasmota_id=TOPIC, serial=SERIAL,
                         last_status="", condition="ok", first_seen=PASSED_AT,
                         notes=(f"[{DATE}] Added at the stock count: read on the shelf 2026-10-02 "
                                "20:36:59, fully assembled with an enclosure (user). The bench "
                                "tried it on 2025-08-23 (report failed to save) and passed it on "
                                "2026-09-10 16:12:56; that report never reached the platform, so no "
                                "programming run is recorded here. Batch 5 = its MAC range and its "
                                "first attempt. Broker account derived from the topic with the fleet "
                                f"salt; it matches the bench report (decision 0054 method). See {REF}"))
        db.add(u)
        db.flush()
        osvc.mark_produced(db, u, BATCH_5, at=PASSED_AT, actor=ACTOR,
                           note="passed on the bench 2026-09-10; report not imported (stock count)")
        if presence is not None:
            presence.device_unit_id = u.id
        for key, value, secret in (
            ("mqtt_user", username, False),
            ("mqtt_password", password, True),
            ("mqtt_creds_line", credentials.mosquitto_line(username, s, final_hash), True),
        ):
            db.add(M.DeviceConfigValue(device_unit_id=u.id, key=key, value=value,
                                       is_secret=secret, set_by_run_id=None, current=True))
        db.add(M.AuditLog(
            action="device.created_by_hand", entity_type="device_unit", entity_id=str(u.id),
            actor=ACTOR,
            details={"serial": SERIAL, "mac": MAC, "topic": TOPIC, "run_id": BATCH_5,
                     "state": "in_stock", "source": "shelf readout 2026-10-02 + bench report 2026-09-10"}))
        db.add(M.AuditLog(
            action="device.credentials_derived", entity_type="device_unit", entity_id=str(u.id),
            actor=ACTOR,
            details={"mqtt_user": username, "current": True, "decision": "0054",
                     "source": "derived from the topic with the fleet salt; equals the bench report"}))
        osvc.refresh_order_status(o9)
        db.add(M.AuditLog(
            action="stock.count", entity_type="project", entity_id=str(project.id), actor=ACTOR,
            details={"date": DATE, "decision": "0057", "reference": REF, "part": "B",
                     "unshipped_found_on_shelf": [SHELF_UNIT], "placeholder_on_23": ph.id,
                     "created": u.id}))
        db.flush()

        # verify through the platform's own read paths ---------------------------
        db.refresh(d3008)
        db.refresh(u)
        body = _mosquitto_file(db, None).body.decode()
        after = {"order 9 dongle line": osvc.line_shipped(li9), **stock(), "export": body.count("\n")}
        for k in before:
            print(f"{k}: {before[k]} -> {after[k]}")
        assert after["order 9 dongle line"] == li9.qty_ordered, "order 9 no longer balances"
        assert after["in_stock"] == before["in_stock"] + 2
        assert after["available"] == before["available"] + 2
        assert after["export"] == before["export"] + 1
        assert f"{TOPIC}:{password}\n" in body, f"{TOPIC} is not in the broker export"
        assert (d3008.state, d3008.condition) == ("in_stock", "ok")
        assert (u.state, u.condition, u.production_run_id) == ("in_stock", "ok", BATCH_5)
        print(f"placeholder id {ph.id}; new unit id {u.id}; {TOPIC} is in the broker export")

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print("\nAPPLIED.")
    finally:
        db.close()


main()
