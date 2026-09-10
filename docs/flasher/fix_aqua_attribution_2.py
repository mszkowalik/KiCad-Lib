#!/usr/bin/env python3
"""Sales / finished-stock clean-up, 2026-09-10.

Findings this fixes (see the session report):
  1. 347 devices in CE_Dongle_V2 report Tasmota Module "CE_Aqua" in their own
     serial log -> they are Aqua units. Move them (device, config runs) to
     CE_Aqua_V2 on the mirror config versions the July fix created.
  2. 77 Aqua boards were flashed twice: as dongle_<6 hex> in 2025-04 and as
     dongle_<12 hex> in 2025-12/2026-01 (firmware built 2025-11-05 names by
     the full MAC). Merge each pair into the older record.
  3. Orders 20 and 21 (no reference, no invoice, 315 + 200 Aqua at 320 PLN)
     were migrated from the runs' sale columns and duplicate the real Aqua
     invoices. Delete them and blank the sale columns on runs 12/13 so the
     startup migration does not recreate them.
  4. Run sale columns disagree with the order lines (runs 5, 6, 11). Align them.
  5. Every shipped device was a FIFO guess; after 1-3 the guesses are wrong.
     Delete every `shipped` event of projects 2/3 and the Aqua unserialized
     shipment lines drawn from runs, then re-pick oldest-first per shipment
     with the same quantities per (shipment, order line).
  6. Devices with no batch are linked to the batch whose flash window is
     nearest (same rule as the existing links).

Usage (inside the api container):  python cleanup.py [--apply]
Without --apply everything is rolled back.
"""
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import text

from app import models as M
from app.db import SessionLocal
from app.services import orders as svc

APPLY = "--apply" in sys.argv
ACTOR = "cleanup 2026-09-10 (Claude, on Mateusz's instruction)"
DONGLE, AQUA = 2, 3
MIRROR = {16: 31, 17: 32, 22: 35}  # Dongle config version id -> Aqua mirror
DUP_ORDERS = (20, 21)
RUN_SALE = {  # run id -> (sale_unit_price, qty_sold, order_ref, order_date, customer)
    6: (240.0, 500, "ZAL 01/04/2024", "2024-03-29", "Columbus Energy"),
    5: (240.0, 300, "FV 1/10/2024", "2024-09-13", "Columbus Energy"),
    11: (220.0, 1000, "ZAL 00001/03/2026 + ZAL 00001/04/2026", "2026-03-13", "Columbus Energy"),
    14: (320.0, 100, "ZAL 00001/10/2024", "2024-10-08", "Columbus Energy"),
    15: (320.0, 100, "ZAL 00001/03/2025", "2025-03-11", "Columbus Energy"),
    16: (320.0, 250, "ZAL 00001/09/2025", "2025-09-29", "Columbus Energy"),
    12: (None, None, "", "", ""),
    13: (None, None, "", "", ""),
}

db = SessionLocal()
q = lambda s, **kw: db.execute(text(s), kw)


def audit(action, etype, eid, details):
    db.add(M.AuditLog(actor=ACTOR, action=action, entity_type=etype, entity_id=str(eid), details=details))


def say(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ inputs
move_ids = [int(r["device_id"]) for r in csv.DictReader(open("/tmp/aqua_in_dongle_project.csv"))]
twins = [(t["name_12hex"], t["name_6hex"]) for t in csv.DictReader(open("/tmp/reflashed_twins.csv"))
         if t["name_12hex"] != "dongle_78421C8BD26C"]  # different OUI: a real suffix collision, two boards
say(f"inputs: {len(move_ids)} devices to move, {len(twins)} twin pairs to merge")

# ------------------------------------------------- 0. remember the shipments
# (shipment id, order line id) -> units it delivered (devices + unserialized from a run)
targets: dict[tuple[int, int], int] = defaultdict(int)
for sid, lid, n in q("""SELECT e.shipment_id, e.order_line_id, count(*) FROM device_events e
    JOIN device_units d ON d.id = e.device_id
    WHERE e.kind = 'shipped' AND d.project_id IN (2, 3) GROUP BY 1, 2"""):
    targets[(sid, lid)] += n
unser_rows = q("""SELECT sl.id, sl.shipment_id, sl.order_line_id, sl.qty_unserialized, sl.source_run_id
    FROM shipment_lines sl JOIN sales_order_lines li ON li.id = sl.order_line_id
    WHERE li.project_id IN (2, 3) AND sl.source_run_id IS NOT NULL
      AND li.order_id <> ALL(:dup)""", dup=list(DUP_ORDERS)).fetchall()
for _, sid, lid, n, _ in unser_rows:
    targets[(sid, lid)] += n
say("shipment targets (shipment, line) -> units:", sorted(targets.items()))

# --------------------------------------------- 1. duplicate sales orders
for oid in DUP_ORDERS:
    o = db.get(M.SalesOrder, oid)
    if o is None:
        say(f"order {oid}: already gone")
        continue
    say(f"delete order {oid} {o.order_ref!r} {o.order_date} lines={[(l.id, l.qty_ordered, l.unit_price) for l in o.lines]} "
        f"shipments={[s.id for s in o.shipments]} invoices={len(o.invoices)}")
    audit("order.delete", "sales_order", oid, {"order_ref": o.order_ref, "reason": "duplicate of the invoiced Aqua sales; migrated from run sale columns"})
    assert not o.invoices
    q("DELETE FROM shipment_lines WHERE shipment_id IN (SELECT id FROM shipments WHERE order_id = :o)", o=oid)
    q("DELETE FROM shipments WHERE order_id = :o", o=oid)
    q("DELETE FROM sales_order_lines WHERE order_id = :o", o=oid)
    q("DELETE FROM sales_orders WHERE id = :o", o=oid)
    db.expunge(o)
db.flush()

# --------------------------------------------- 2. run sale columns
for rid, (price, qty, ref, date, cust) in RUN_SALE.items():
    r = db.get(M.ProductionRun, rid)
    before = (r.sale_unit_price, r.qty_sold, r.order_ref, r.order_date, r.customer)
    after = (price, qty, ref, date, cust)
    if before != after:
        say(f"run {rid} {r.label!r}: sale {before} -> {after}")
        r.sale_unit_price, r.qty_sold, r.order_ref, r.order_date, r.customer = after
        audit("run.update", "production_run", rid, {"sale_before": before, "sale_after": after})
db.flush()

# ------------------------------ 3. drop every FIFO guess of projects 2/3
n = q("""DELETE FROM device_events e USING device_units d
    WHERE d.id = e.device_id AND d.project_id IN (2, 3) AND e.kind = 'shipped'""").rowcount
say(f"deleted {n} shipped events (all were FIFO auto-picks)")
assert q("SELECT count(*) FROM device_events e JOIN device_units d ON d.id=e.device_id WHERE d.project_id IN (2,3) AND e.kind <> 'produced'").scalar() == 0
for slid, sid, lid, qty, src in unser_rows:
    say(f"delete unserialized shipment line {slid}: shipment {sid} line {lid} qty {qty} from run {src}")
    q("DELETE FROM shipment_lines WHERE id = :i", i=slid)

# ---------------------------------------- 4. move the 347 Aqua units
res = q("UPDATE device_units SET project_id = :p WHERE id = ANY(:ids) AND project_id = :d",
        p=AQUA, ids=move_ids, d=DONGLE)
say(f"moved {res.rowcount} devices to CE_Aqua_V2")
for src, dst in MIRROR.items():
    r = q("""UPDATE programming_runs SET deployment_version_id = :dst
        WHERE device_unit_id = ANY(:ids) AND deployment_version_id = :src""", dst=dst, src=src, ids=move_ids)
    say(f"  config runs {src} -> {dst}: {r.rowcount}")
left = q("""SELECT count(*) FROM programming_runs r JOIN deployment_versions v ON v.id = r.deployment_version_id
    JOIN deployments dp ON dp.id = v.deployment_id WHERE r.device_unit_id = ANY(:ids) AND dp.project_id <> :p""",
         ids=move_ids, p=AQUA).scalar()
assert left == 0, f"{left} runs of moved devices still on Dongle versions"
q("""UPDATE programming_runs r SET firmware_fingerprint = v.firmware_fingerprint, files_fingerprint = v.files_fingerprint
    FROM deployment_versions v WHERE v.id = r.deployment_version_id AND r.device_unit_id = ANY(:ids)""", ids=move_ids)
# their produced events point at Dongle batches; unlink, step 6 re-links by window
q("DELETE FROM device_events WHERE device_id = ANY(:ids) AND kind = 'produced'", ids=move_ids)
q("UPDATE device_units SET production_run_id = NULL, state = '', notes = notes || :n WHERE id = ANY(:ids)",
  ids=move_ids, n="\n[2026-09-10] Moved from CE_Dongle_V2: the device's own serial log reports Module CE_Aqua.")
for did in move_ids:
    audit("device.move_project", "device_unit", did, {"from": DONGLE, "to": AQUA, "reason": "serialLog Module=CE_Aqua"})

# ---------------------------------------------- 5. merge the twins
merged = 0
for long_name, short_name in twins:
    keep = db.query(M.DeviceUnit).filter_by(tasmota_id=short_name).one()
    drop = db.query(M.DeviceUnit).filter_by(tasmota_id=long_name).one()
    assert keep.serial.upper() == drop.serial[-6:].upper()
    for tbl, col in (("programming_runs", "device_unit_id"), ("run_checks", "device_unit_id"),
                     ("device_config_values", "device_unit_id")):
        q(f"UPDATE {tbl} SET {col} = :k WHERE {col} = :d", k=keep.id, d=drop.id)
    # one current value per key: the later flash wins
    q("""UPDATE device_config_values v SET current = false WHERE v.device_unit_id = :k AND v.current
        AND EXISTS (SELECT 1 FROM device_config_values w WHERE w.device_unit_id = :k AND w.key = v.key AND w.set_at > v.set_at)""",
      k=keep.id)
    q("DELETE FROM device_events WHERE device_id = :d OR replaces_device_id = :d", d=drop.id)
    note = (f"\n[2026-09-10] Merged with record #{drop.id} ({long_name}): the same board, re-flashed "
            f"{drop.first_seen:%Y-%m-%d} under the full-MAC name.")
    d_tas, d_mac, d_ser, d_seen, d_status, d_notes, d_id = (drop.tasmota_id, drop.mac, drop.serial, drop.last_seen,
                                                            drop.last_status, drop.notes, drop.id)
    # the MAC is unique: the absorbed row must go before the kept row takes it
    q("DELETE FROM device_units WHERE id = :d", d=d_id)
    db.expunge(drop)
    db.flush()
    keep.tasmota_id, keep.mac, keep.serial = d_tas, d_mac, d_ser
    keep.last_seen = max(keep.last_seen, d_seen)
    keep.last_status = d_status or keep.last_status
    keep.notes = (keep.notes or "") + (("\n" + d_notes) if d_notes else "") + note
    keep.project_id = AQUA
    audit("device.merge", "device_unit", keep.id, {"absorbed": d_id, "name": long_name})
    db.flush()
    merged += 1
db.flush()
say(f"merged {merged} twin pairs")

# ------------------------------------- 6. link every unlinked device
db.expire_all()
windows: dict[int, list] = {}
for pid in (DONGLE, AQUA):
    rows = q("""SELECT d.production_run_id, r.run_date, min(d.first_seen), max(d.first_seen), r.qty, r.label
        FROM device_units d JOIN production_runs r ON r.id = d.production_run_id
        WHERE d.project_id = :p GROUP BY 1, 2, 5, 6 ORDER BY 2""", p=pid).fetchall()
    windows[pid] = rows
    say(f"project {pid} windows:", [(r[0], r[5][:7], str(r[2].date()), str(r[3].date())) for r in rows])


def nearest_run(pid, when):
    best, dist = None, None
    for rid, _, lo, hi, _, _ in windows[pid]:
        d = timedelta(0) if lo <= when <= hi else (lo - when if when < lo else when - hi)
        if dist is None or d < dist:
            best, dist = rid, d
    return best


linked = Counter()
for d in (db.query(M.DeviceUnit).filter(M.DeviceUnit.project_id.in_((DONGLE, AQUA)),
                                        M.DeviceUnit.production_run_id.is_(None))
          .order_by(M.DeviceUnit.first_seen, M.DeviceUnit.id).all()):
    rid = nearest_run(d.project_id, d.first_seen)
    db.expire(d, ["events"])
    ev = svc.mark_produced(db, d, rid, actor=ACTOR, note="linked to batch after the fact (nearest flash window, 2026-09-10 clean-up)")
    assert ev is not None
    linked[(d.project_id, rid)] += 1
db.flush()
say("linked to batches (project, run) -> n:", sorted(linked.items()))
# every device of 2/3 is now in_stock with exactly one produced event
q("UPDATE device_units SET state = 'in_stock' WHERE project_id IN (2, 3)")
bad = q("""SELECT count(*) FROM device_units d WHERE d.project_id IN (2,3) AND
    (SELECT count(*) FROM device_events e WHERE e.device_id = d.id AND e.kind='produced') <> 1""").scalar()
assert bad == 0, f"{bad} devices without exactly one produced event"

# ---------------------------------------------------- 7. FIFO re-pick
db.expire_all()
avail_from = {r[0]: r[1] for r in q("""SELECT d.id, GREATEST(d.first_seen, max(r.started_at))
    FROM device_units d LEFT JOIN programming_runs r ON r.device_unit_id = d.id
    WHERE d.project_id IN (2, 3) GROUP BY d.id, d.first_seen""")}
pools = {}
for pid in (DONGLE, AQUA):
    devs = db.query(M.DeviceUnit).filter(M.DeviceUnit.project_id == pid).all()
    pools[pid] = sorted(devs, key=lambda d: (avail_from[d.id], d.first_seen, d.id))
    say(f"project {pid}: {len(devs)} devices available for picking")
shipments = (db.query(M.Shipment).filter(M.Shipment.kind == "delivery")
             .order_by(M.Shipment.shipped_at, M.Shipment.id).all())
picked_total = Counter()
warn = 0
for sh in shipments:
    lines = [li for li in sh.order.lines if li.project_id in (DONGLE, AQUA) and targets.get((sh.id, li.id))]
    for li in lines:
        want = targets[(sh.id, li.id)]
        pool = pools[li.project_id]
        take = [d for d in pool if d.state == "in_stock"][:want]
        assert len(take) == want, f"shipment {sh.id} line {li.id}: only {len(take)} of {want} devices"
        at = svc._date_at(sh.shipped_at)
        late = [d for d in take if avail_from[d.id].date() > at.date()]
        if late:
            warn += 1
            say(f"  WARNING shipment {sh.id} ({sh.shipped_at}, {sh.order.order_ref!r}) line {li.id}: "
                f"{len(late)} of {want} picked devices were flashed after the shipment date "
                f"(first {late[0].tasmota_id} {avail_from[late[0].id]:%Y-%m-%d}, last {late[-1].tasmota_id} {avail_from[late[-1].id]:%Y-%m-%d})")
        for d in take:
            svc.record_event(db, d, "shipped", at=at, actor=ACTOR, auto=True, order_line_id=li.id,
                             shipment_id=sh.id, note="oldest-first re-pick, 2026-09-10 clean-up")
        picked_total[(sh.id, li.id)] = want
        batches = Counter(d.production_run_id for d in take)
        say(f"shipment {sh.id} {sh.shipped_at} {sh.order.order_ref!r} line {li.id} ({li.product}): {want} devices from batches {sorted(batches.items())}")
db.flush()
assert picked_total == targets, "re-pick does not reproduce the shipment quantities"
for o in db.query(M.SalesOrder).all():
    db.expire(o, ["lines", "shipments"])
    svc.refresh_order_status(o)
db.flush()

# ------------------------------------------------------------ 8. report
say("\n== finished stock after ==")
for r in svc.run_stock(db):
    if r["project_id"] in (DONGLE, AQUA):
        say(f"  {r['project']:12} {r['label']:22} built {r['built']:5} produced {r['devices_produced']:5} "
            f"in_stock {r['devices_in_stock']:4} shipped {r['devices_shipped']:5} unser {r['unserialized_shipped']:4} "
            f"legacy {r['legacy_stock']:4} overdrawn {r['overdrawn']:4} stock {r['stock']:4}")
say("== demand ==")
for d in svc.project_demand(db):
    say("  ", d)
say("== orders ==")
for o in db.query(M.SalesOrder).order_by(M.SalesOrder.order_date).all():
    say(f"  {o.id:3} {o.order_ref!r:40} {o.order_date} {o.status:10} " +
        ", ".join(f"{li.product} {svc.line_shipped(li)}/{li.qty_ordered}" for li in o.lines))
say(f"warnings: {warn}")
if APPLY:
    db.commit()
    say("COMMITTED")
else:
    db.rollback()
    say("DRY RUN — rolled back")
