"""Apply the CE_Dongle_V2 stock count, and the 2 Aqua prototypes, part A.

Decision 0057. The facts and the evidence are in the CE_Dongle_V2 section of
docs/reference/stock-count-2026-10.md; the production snapshot before this
script is in reports/stock-count-2026-10-02/platform-v2/ (gitignored).

User decisions 2026-10-03 (answers 1, 3 and 4):

  1. #1607 `dongle_84FA58` and #1768 `dongle_84FD94` are ONLINE on the fleet
     broker with inverters, so they are at customers. Their `fail` is an
     import artifact (a `_test` report with no `test_result`). They become
     condition `ok`, move to Batch 3 (every bench neighbour is Batch 3,
     decision 0029), and ship on a correction delivery of ZAL 00001/10/2024
     dated 2024-11-30 (every neighbour went on shipment #20 that day).
     OPTION B: the order keeps its invoiced 420, so the two lowest-id Batch 3
     members of shipment #20 that the broker has never heard come off it and
     are marked missing — the rule of the Aqua correction, held to the batch
     of the units they make room for.
  2. #3221 `dongle_4D90A8`: its only report failed to save, it is not on the
     shelf and never on the broker: missing.
  3. The 12 MAC-less CE_Dongle_V2 prototypes in stock: missing.
  4. The 2 MAC-less CE_Aqua_V2 prototypes in stock (#28316, #28317): missing.

Part B — #3008 `dongle_4D8694` and the unrecorded `dongle_2043A84D8174`, both
read on the shelf — waits for the user's answer on their condition.

ONE-TIME. Run it through STDIN, never as a file (api/CLAUDE.md):

    docker compose exec -T api python - < scripts/stock-count-dongle-v2-2026-10-03.py
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
DATE = "2026-10-03"
REF = "docs/reference/stock-count-2026-10.md"

ORDER_7, SHIP_20, SHIP_20_DATE = "ZAL 00001/10/2024", 20, "2024-11-30"
BATCH_3 = 7
PROVEN = [1607, 1768]                    # online at customers, recorded failed in stock
GONE = [3221]                            # report never saved, absent, never heard
DONGLE_PROTOTYPES = list(range(6593, 6603)) + [28318, 28319]
AQUA_PROTOTYPES = [28316, 28317]


def heard(db, d) -> bool:
    """Any presence row at all — the same match the Aqua correction used."""
    if mqtt_monitor.presence_rows(db, d):
        return True
    return bool(d.tasmota_id) and db.scalar(
        select(M.DevicePresence).where(M.DevicePresence.topic == d.tasmota_id)) is not None


def project(db, name):
    p = db.scalar(select(M.Project).where(M.Project.name == name))
    assert p is not None, f"no project {name}"
    return p


def main():
    db = SessionLocal()
    try:
        dongle, aqua = project(db, "CE_Dongle_V2"), project(db, "CE_Aqua_V2")
        o7 = db.scalar(select(M.SalesOrder).where(M.SalesOrder.order_ref == ORDER_7))
        sh20 = db.get(M.Shipment, SHIP_20)
        assert o7 is not None and sh20 is not None and sh20.order_id == o7.id, "order 7 / shipment 20 — stop"
        lines = [li for li in o7.lines if li.project_id == dongle.id]
        assert len(lines) == 1, f"{ORDER_7}: {len(lines)} dongle lines — stop"
        li7 = lines[0]
        b3 = db.get(M.ProductionRun, BATCH_3)
        assert b3.project_id == dongle.id and b3.label.startswith("Batch 3"), b3.label

        dev = {i: db.get(M.DeviceUnit, i) for i in PROVEN + GONE + DONGLE_PROTOTYPES + AQUA_PROTOTYPES}
        for i in PROVEN + GONE:
            d = dev[i]
            assert d.project_id == dongle.id and (d.state, d.condition, d.production_run_id) == (
                "in_stock", "faulty", None), f"#{i} is {d.state}/{d.condition}/run {d.production_run_id} — stop"
        for i in PROVEN:
            assert heard(db, dev[i]), f"#{i} is no longer on the broker — stop"
        assert not heard(db, dev[3221]), "#3221 is on the broker now — stop"
        for i in DONGLE_PROTOTYPES + AQUA_PROTOTYPES:
            d = dev[i]
            want = dongle.id if i in DONGLE_PROTOTYPES else aqua.id
            assert d.project_id == want and (d.state, d.condition, d.mac) == ("in_stock", "prototype", None), (
                f"#{i} is {d.state}/{d.condition}/{d.mac} — stop")

        before = {"order 7 dongle line": osvc.line_shipped(li7),
                  "dongle in stock": db.query(M.DeviceUnit).filter_by(project_id=dongle.id, state="in_stock").count(),
                  "dongle missing": db.query(M.DeviceUnit).filter_by(project_id=dongle.id, state="missing").count(),
                  "aqua in stock": db.query(M.DeviceUnit).filter_by(project_id=aqua.id, state="in_stock").count(),
                  "aqua missing": db.query(M.DeviceUnit).filter_by(project_id=aqua.id, state="missing").count()}
        assert before["order 7 dongle line"] == li7.qty_ordered, before

        # Option B: the two lowest-id Batch 3 members of #20 nobody has heard.
        members = sorted({e.device_id for e in db.query(M.DeviceEvent).filter(
            M.DeviceEvent.shipment_id == SHIP_20, M.DeviceEvent.kind == "shipped",
            M.DeviceEvent.order_line_id == li7.id)})
        swap = []
        for i in members:
            d = db.get(M.DeviceUnit, i)
            if d.production_run_id != BATCH_3 or d.state != "shipped":
                continue
            if [e.shipment_id for e in osvc.live_shipped_of(d)] != [SHIP_20]:
                continue
            if not heard(db, d):
                swap.append(d)
            if len(swap) == 2:
                break
        assert len(swap) == 2, f"found {len(swap)} unheard Batch 3 members of #20 — stop"

        print(f"{ORDER_7} dongle line {li7.id}: {before['order 7 dongle line']}/{li7.qty_ordered} shipped")
        print("1. #1607, #1768 -> Batch 3, condition ok, shipped on a correction delivery dated", SHIP_20_DATE)
        print("   off shipment #20 and missing:", ", ".join(f"#{d.id} {d.mac or d.tasmota_id}" for d in swap))
        print("2. #3221 missing")
        print(f"3. {len(DONGLE_PROTOTYPES)} dongle prototypes missing: {DONGLE_PROTOTYPES}")
        print(f"4. {len(AQUA_PROTOTYPES)} Aqua prototypes missing: {AQUA_PROTOTYPES}")
        if not WRITE:
            print("\ndry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        # 1 ----------------------------------------------------------------------
        res = osvc.rebatch_devices(db, b3, PROVEN, actor=ACTOR, dry_run=False,
                                   note=f"[{DATE}] every bench neighbour of 2024-11-17/18 is Batch 3. See {REF}")
        assert [m["device_id"] for m in res["moved"]] == PROVEN, res
        for i in PROVEN:
            d = dev[i]
            d.condition = "ok"
            d.notes = ((d.notes + "\n") if d.notes else "") + (
                f"[{DATE}] Online on the fleet broker with an inverter: at a customer. The newest "
                "programming run's `fail` is an import artifact — the `_test` report carries no "
                "`test_result`; the config and test reports both say OK. Condition ok, Batch 3, "
                f"shipped on a correction delivery of {ORDER_7}. See {REF}")
        for d in swap:
            osvc.unship_device(db, d, shipment_id=SHIP_20, actor=ACTOR, dry_run=False,
                               note=f"[{DATE}] replaced on this delivery by a Batch 3 unit proven at "
                                    "the customer on the fleet broker; never heard on the broker "
                                    f"itself. See {REF}")
        db.flush()
        db.refresh(o7)
        corr = osvc.create_shipment(
            db, o7, shipped_at=SHIP_20_DATE, actor=ACTOR,
            delivery_note=f"Correction at the stock count of {DATE}",
            notes=(f"Two Batch 3 units of {ORDER_7} that the count proved at the customer (online "
                   "on the fleet broker with an inverter). Dated with shipment #20, which carried "
                   f"every bench neighbour; the true date is unknown. Decision 0057, {REF}"),
            lines=[{"order_line_id": li7.id, "device_ids": PROVEN,
                    "note": f"[{DATE}] proven at the customer at the stock count"}])
        db.flush()

        # 2-4 + the swapped pair ---------------------------------------------------
        for d in swap:
            osvc.mark_missing(db, d, counted_at=DATE, actor=ACTOR,
                              note=f"[{DATE}] taken off shipment #{SHIP_20} for a proven unit; never "
                                   f"online on the broker. May be at a customer. See {REF}")
        osvc.mark_missing(db, dev[3221], counted_at=DATE, actor=ACTOR,
                          note=f"[{DATE}] recorded failed in stock, but its only bench report failed "
                               "to save, so the result is unknown. Not on the shelf, never on the "
                               f"broker. See {REF}")
        for i in DONGLE_PROTOTYPES + AQUA_PROTOTYPES:
            osvc.mark_missing(db, dev[i], counted_at=DATE, actor=ACTOR,
                              note=f"[{DATE}] MAC-less prototype record; no prototype was on the "
                                   f"shelf at the count (user). See {REF}")
        db.flush()
        osvc.refresh_order_status(o7)

        missing_ids = [d.id for d in swap] + GONE + DONGLE_PROTOTYPES + AQUA_PROTOTYPES
        db.add(M.AuditLog(
            action="stock.count", entity_type="project", entity_id=str(dongle.id), actor=ACTOR,
            details={"date": DATE, "decision": "0057", "reference": REF,
                     "rebatched_to_batch_3_and_shipped": PROVEN, "correction_shipment_id": corr.id,
                     "unshipped_unheard_from_20": [d.id for d in swap],
                     "missing": missing_ids}))
        db.flush()

        # verify through the platform's own read paths ---------------------------
        after = {"order 7 dongle line": osvc.line_shipped(li7),
                 "dongle in stock": db.query(M.DeviceUnit).filter_by(project_id=dongle.id, state="in_stock").count(),
                 "dongle missing": db.query(M.DeviceUnit).filter_by(project_id=dongle.id, state="missing").count(),
                 "aqua in stock": db.query(M.DeviceUnit).filter_by(project_id=aqua.id, state="in_stock").count(),
                 "aqua missing": db.query(M.DeviceUnit).filter_by(project_id=aqua.id, state="missing").count()}
        for k in before:
            print(f"{k}: {before[k]} -> {after[k]}")
        assert after["order 7 dongle line"] == li7.qty_ordered, "order 7 no longer balances"
        n_dongle_missing = len(swap) + len(GONE) + len(DONGLE_PROTOTYPES)
        assert after["dongle in stock"] == before["dongle in stock"] - len(PROVEN) - len(GONE) - len(DONGLE_PROTOTYPES)
        assert after["dongle missing"] == before["dongle missing"] + n_dongle_missing
        assert after["aqua in stock"] == before["aqua in stock"] - len(AQUA_PROTOTYPES)
        assert after["aqua missing"] == before["aqua missing"] + len(AQUA_PROTOTYPES)
        for i in PROVEN:
            assert (dev[i].state, dev[i].condition, dev[i].production_run_id) == ("shipped", "ok", BATCH_3)
        p = next(x for x in osvc.product_stock(db) if x["project_id"] == dongle.id)
        print("CE_Dongle_V2 after:", {k: p[k] for k in ("in_stock", "available", "held", "missing", "no_batch")})
        print(f"correction shipment id {corr.id}")

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print("\nAPPLIED.")
    finally:
        db.close()


main()
