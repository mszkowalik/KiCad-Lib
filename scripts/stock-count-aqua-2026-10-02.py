"""Apply the CE_Aqua_V2 stock count of 2026-10-02 to the device records.

Decision 0057. The facts, the evidence and the user's decisions are in
docs/reference/stock-count-2026-10.md; the raw readout and the platform state
before this script are in reports/stock-count-2026-10-02/ (gitignored).

What it writes, all through services/orders.py:

  1. UNSHIP the 18 units found on the shelf that two deliveries list
     (2 on shipment #19, 16 on shipment #24). They go back to stock.
  2. UNSHIP 3 more members of shipment #24 that the broker has never heard
     from — the three lowest device ids among them. They make room for the
     units below that ARE proven at the customer.
  3. SHIP the 19 units proven at the customer (18 online on the broker since
     2026-09-18, plus 84:1f:e8:35:0d:a4 from the user's report) on a
     correction delivery of order ZAL 00001/09/2025. It is dated 2026-01-18:
     11 of them were programmed that evening, so that is the earliest day the
     delivery can have left. The true date is unknown.
  4. ADD 2 `unidentified` placeholders (no MAC, Batch 1) to shipment #19, for
     the 2 places no known unit can fill. A placeholder cannot pass
     create_shipment, which ships only `ok` units, so it is written with
     `_ship_device` onto the existing shipment — the shape decision 0039 gave
     the prototype placeholders.
  5. MARK MISSING the 20 absent units nobody can place, and the 3 from step 2.
  6. Set device 2273 (f8:b3:b7:42:ba:1c) to condition `incomplete`: it is a
     bare programmed PCB with no enclosure and no antenna, and the user said
     it must not be sellable (2026-10-02).

Every order keeps its invoiced quantity. Every precondition is checked against
the 2026-10-02 snapshot first, and the script stops if anything has moved.

ONE-TIME. Run it through STDIN, never as a file (api/CLAUDE.md):

    docker compose exec -T api python - < scripts/stock-count-aqua-2026-10-02.py
    docker compose exec -T -e REHEARSE=1 api python - < scripts/…
    docker compose exec -T -e APPLY=1 api python - < scripts/…
"""
import os

from sqlalchemy import select

from app import models as M
from app.db import SessionLocal
from app.services import mqtt_monitor
from app.services import orders as osvc

assert M.__file__ == "/srv/app/models.py", f"stale app package: {M.__file__}"

APPLY = os.environ.get("APPLY") == "1"
REHEARSE = os.environ.get("REHEARSE") == "1"
WRITE = APPLY or REHEARSE
ACTOR = "stock-count-2026-10-02"
DATE = "2026-10-02"
PROJECT = "CE_Aqua_V2"
REF = "docs/reference/stock-count-2026-10.md"

ORDER_24, SHIP_24 = "ZAL 00001/09/2025", 24     # the late Aqua delivery
ORDER_19, SHIP_19 = "FV 1/10/2024", 19
PLACEHOLDER_RUN = 12                            # Batch 1, the batch of the 2 units they stand in for
CORRECTION_DATE = "2026-01-18"

# 1. On the shelf, recorded on a delivery: device id -> the shipment it never left on.
UNSHIP = {745: 19, 822: 19,
          2258: 24, 2261: 24, 2273: 24, 2285: 24, 2286: 24, 2293: 24, 2294: 24, 2303: 24,
          2317: 24, 2323: 24, 2333: 24, 2346: 24, 2358: 24, 2368: 24, 2380: 24, 2383: 24}
# 3. Absent, and proven at the customer.
PROVEN = [2319, 2347, 2359, 2364, 2375, 2384, 2387,
          4453, 4457, 4459, 4465, 4467, 4468, 4469, 4473, 4484, 4485, 4496, 28523]
# 5. Absent, and nobody can place them.
UNKNOWN = [2264, 2275, 2310, 2335, 2344, 2371, 2381, 2388, 2389,
           4452, 4454, 4456, 4458, 4460, 4462, 4464, 4466, 4472, 4474, 4483]


def heard(db, d) -> bool:
    """Any presence row at all — the same match the device page uses."""
    if mqtt_monitor.presence_rows(db, d):
        return True
    return bool(d.tasmota_id) and db.scalar(
        select(M.DevicePresence).where(M.DevicePresence.topic == d.tasmota_id)) is not None


def aqua_line(order, project_id):
    lines = [li for li in order.lines if li.project_id == project_id]
    assert len(lines) == 1, f"{order.order_ref}: {len(lines)} Aqua lines"
    return lines[0]


def main():
    db = SessionLocal()
    try:
        project = db.scalar(select(M.Project).where(M.Project.name == PROJECT))
        assert project is not None
        o24 = db.scalar(select(M.SalesOrder).where(M.SalesOrder.order_ref == ORDER_24))
        o19 = db.scalar(select(M.SalesOrder).where(M.SalesOrder.order_ref == ORDER_19))
        assert o24 is not None and o19 is not None, "order not found — stop"
        sh24, sh19 = db.get(M.Shipment, SHIP_24), db.get(M.Shipment, SHIP_19)
        assert sh24.order_id == o24.id and sh19.order_id == o19.id, "shipment/order mismatch — stop"
        li24, li19 = aqua_line(o24, project.id), aqua_line(o19, project.id)
        prun = db.get(M.ProductionRun, PLACEHOLDER_RUN)
        assert prun.project_id == project.id and prun.label.startswith("Batch 1"), prun.label

        dev = {i: db.get(M.DeviceUnit, i) for i in list(UNSHIP) + PROVEN + UNKNOWN}
        for i, d in dev.items():
            assert d is not None and d.project_id == project.id, f"device {i} is not a {PROJECT} unit — stop"
        for i, sid in UNSHIP.items():
            live = [e.shipment_id for e in osvc.live_shipped_of(dev[i])]
            assert dev[i].state == "shipped" and live == [sid], (
                f"device {i}: state {dev[i].state}, live deliveries {live}, expected [{sid}] — stop")
        for i in PROVEN + UNKNOWN:
            assert (dev[i].state, dev[i].condition) == ("in_stock", "ok"), (
                f"device {i} is {dev[i].state}/{dev[i].condition}, expected in_stock/ok — stop")

        before = {"#24 line": osvc.line_shipped(li24), "#19 line": osvc.line_shipped(li19),
                  "aqua in stock": db.query(M.DeviceUnit).filter_by(project_id=project.id,
                                                                    state="in_stock").count(),
                  "aqua missing": db.query(M.DeviceUnit).filter_by(project_id=project.id,
                                                                   state="missing").count()}
        assert before["#24 line"] == li24.qty_ordered and before["#19 line"] == li19.qty_ordered, before

        # 2. Three #24 members nobody has heard from, lowest id first.
        members = sorted({e.device_id for e in db.query(M.DeviceEvent).filter(
            M.DeviceEvent.shipment_id == SHIP_24, M.DeviceEvent.kind == "shipped",
            M.DeviceEvent.order_line_id == li24.id)})
        swap = []
        for i in members:
            if i in UNSHIP or i in PROVEN:
                continue
            d = db.get(M.DeviceUnit, i)
            if d.state != "shipped" or [e.shipment_id for e in osvc.live_shipped_of(d)] != [SHIP_24]:
                continue
            if not heard(db, d):
                swap.append(d)
            if len(swap) == 3:
                break
        assert len(swap) == 3, f"found {len(swap)} unheard members of #24 — stop"

        print(f"order {ORDER_24} Aqua line {li24.id}: {before['#24 line']}/{li24.qty_ordered} shipped")
        print(f"order {ORDER_19} Aqua line {li19.id}: {before['#19 line']}/{li19.qty_ordered} shipped")
        print(f"1. unship {len(UNSHIP)} found on the shelf")
        print("2. unship 3 unheard #24 members:",
              ", ".join(f"#{d.id} {d.mac or d.tasmota_id}" for d in swap))
        print(f"3. ship {len(PROVEN)} proven units on a correction delivery of {ORDER_24}, "
              f"dated {CORRECTION_DATE}")
        print(f"4. add 2 unidentified placeholders (run {prun.label}) to shipment #{SHIP_19}")
        print(f"5. mark {len(UNKNOWN) + len(swap)} missing")
        print("6. device 2273 (bare PCB) -> condition incomplete")
        if not WRITE:
            print("\ndry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        # 1 + 2 ----------------------------------------------------------------
        for i, sid in UNSHIP.items():
            osvc.unship_device(db, dev[i], shipment_id=sid, actor=ACTOR, dry_run=False,
                               note=f"[{DATE}] on the shelf at the stock count: this delivery never "
                                    f"carried it (user: no Aqua ever came back). See {REF}")
        for d in swap:
            osvc.unship_device(db, d, shipment_id=SHIP_24, actor=ACTOR, dry_run=False,
                               note=f"[{DATE}] replaced on this delivery by a unit proven at the "
                                    "customer on the fleet broker; never heard on the broker itself. "
                                    f"See {REF}")
        db.flush()

        # 3 ----------------------------------------------------------------------
        db.refresh(o24)
        corr = osvc.create_shipment(
            db, o24, shipped_at=CORRECTION_DATE, actor=ACTOR,
            delivery_note=f"Correction at the stock count of {DATE}",
            notes=(f"The units of {ORDER_24} that the count proved at the customer (online on the "
                   "fleet broker since 2026-09-18, one by user report). The true date is unknown: "
                   f"{CORRECTION_DATE} is the earliest, because 11 of them were programmed that "
                   f"evening. Decision 0057, {REF}"),
            lines=[{"order_line_id": li24.id, "device_ids": PROVEN,
                    "note": f"[{DATE}] proven at the customer at the stock count"}])
        db.flush()

        # 4 ----------------------------------------------------------------------
        note = (f"[{DATE}] Placeholder: one of 2 units that shipment #{SHIP_19} ({ORDER_19}) "
                "delivered and that no known device can fill — the 2 it listed were on the shelf. "
                "Fill it when the broker or the customer names the real unit. "
                f"Decision 0057, {REF}")
        at19 = osvc._date_at("2024-10-16")
        placeholders = []
        for _ in range(2):
            p = M.DeviceUnit(project_id=project.id, mac=None, serial="", chip="", tasmota_id="",
                             last_status="", notes=note, condition="unidentified")
            db.add(p)
            db.flush()
            osvc.record_event(db, p, "produced", at=at19, actor=ACTOR, production_run_id=PLACEHOLDER_RUN,
                              note="placeholder for an unidentified delivered unit")
            osvc._ship_device(db, sh19, li19, p, at=at19, actor=ACTOR, note=note)
            placeholders.append(p)
        db.flush()

        # 5 ----------------------------------------------------------------------
        for i in UNKNOWN:
            osvc.mark_missing(db, dev[i], counted_at=DATE, actor=ACTOR,
                              note=f"[{DATE}] recorded in stock, not on the shelf, never online on the "
                                   f"broker. May be at the customer. See {REF}")
        for d in swap:
            osvc.mark_missing(db, d, counted_at=DATE, actor=ACTOR,
                              note=f"[{DATE}] taken off shipment #{SHIP_24} for a proven unit; not on "
                                   f"the shelf and never online. May be at the customer. See {REF}")

        # 6 ----------------------------------------------------------------------
        bare = dev[2273]
        bare.condition = "incomplete"
        bare.notes = ((bare.notes + "\n") if bare.notes else "") + (
            f"[{DATE}] Bare programmed PCB, no enclosure, no antenna: condition incomplete, "
            f"not sellable until it is finished (user decision). See {REF}")
        db.flush()
        osvc.refresh_order_status(o24)
        osvc.refresh_order_status(o19)

        db.add(M.AuditLog(
            action="stock.count", entity_type="project", entity_id=str(project.id), actor=ACTOR,
            details={"date": DATE, "decision": "0057", "reference": REF,
                     "unshipped_found_on_shelf": sorted(UNSHIP),
                     "unshipped_unheard_from_24": [d.id for d in swap],
                     "correction_shipment_id": corr.id, "shipped_proven": PROVEN,
                     "placeholders_on_19": [p.id for p in placeholders],
                     "missing": UNKNOWN + [d.id for d in swap],
                     "incomplete": [2273]}))
        db.flush()

        # verify through the platform's own read paths ---------------------------
        after = {"#24 line": osvc.line_shipped(li24), "#19 line": osvc.line_shipped(li19),
                 "aqua in stock": db.query(M.DeviceUnit).filter_by(project_id=project.id,
                                                                   state="in_stock").count(),
                 "aqua missing": db.query(M.DeviceUnit).filter_by(project_id=project.id,
                                                                  state="missing").count()}
        for k in before:
            print(f"{k}: {before[k]} -> {after[k]}")
        assert after["#24 line"] == li24.qty_ordered, "order 24 no longer balances"
        assert after["#19 line"] == li19.qty_ordered, "order 19 no longer balances"
        assert after["aqua in stock"] == before["aqua in stock"] - len(PROVEN) - len(UNKNOWN) + len(UNSHIP)
        assert after["aqua missing"] == before["aqua missing"] + len(UNKNOWN) + len(swap)
        for i in UNSHIP:
            assert dev[i].state == "in_stock"
        assert (dev[2273].state, dev[2273].condition) == ("in_stock", "incomplete")
        for i in PROVEN:
            assert dev[i].state == "shipped"
        print(f"correction shipment id {corr.id}; placeholders {[p.id for p in placeholders]}")

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print("\nAPPLIED.")
    finally:
        db.close()


main()
