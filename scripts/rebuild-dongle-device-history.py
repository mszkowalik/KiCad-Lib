"""Rebuild CE_Dongle_V2 device history from the agreed facts.

Source: docs/reference/dongle-stock-reconciliation.md.
Reasoning: docs/decisions/0036-the-dongle-device-log-is-rebuilt-from-the-facts.md.

ONE-TIME. It rewrites CE_Dongle_V2 history from scratch and is not idempotent:
running it twice against an already-rebuilt database would find no `disposed`
devices and fail its own assertions. Run it once per database, against a
baseline that matches the document's figures (4463 devices, Batch 7 at 1025).

Run it through STDIN, never as a file — `api/CLAUDE.md` explains why a file
inside the container imports a stale copy of `app`:

    docker compose exec -T api python - < scripts/rebuild-dongle-device-history.py
    docker compose exec -T -e REHEARSE=1 api python - < scripts/…   # write, verify, roll back
    docker compose exec -T -e APPLY=1 api python - < scripts/…      # commit

Three modes: dry run (default) plans and writes nothing but cannot reach the
device-creation branch; REHEARSE runs the whole write path, verifies, and rolls
back; APPLY commits only if every batch's invariant balances.

Why a script and not the platform's own services: `create_shipment` refuses any
device whose condition is not `ok`, which is correct for every future delivery
and cannot express the 35 prototypes and 40 placeholders this reconstruction has
to record as already delivered. The rows it writes are the exact shape the
services write, so every reader works afterwards — and the verification at the
end uses the platform's own read paths, not the script's arithmetic.
"""
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

from app.db import SessionLocal
from app import models as M

APPLY = os.environ.get("APPLY") == "1"
# Exercise the whole write path, verify, then roll back. The dry run cannot
# reach the device-creation branch, so this is what proves it works.
REHEARSE = os.environ.get("REHEARSE") == "1"
APPLY = APPLY or REHEARSE
DONGLE = 2
ACTOR = "stock-reconciliation-2026-09-18"

# --- the facts, from the document -----------------------------------------

# Deliveries in the order they left. `ship` is the existing header to reuse;
# None means the delivery has no header yet and one is created.
SEQUENCE = [
    (1,  "2024-07-21", 489, 17),
    (1,  "2024-10-09",  11, None),   # "after 2024-10-05", once Batch 2 arrived
    (2,  "2024-10-16", 300, 19),     # header shared with CE_Aqua_V2
    (7,  "2024-11-30", 420, 20),     # shared
    (8,  "2025-04-30", 500, 22),     # shared
    (9,  "2025-09-29", 455, 23),
    (10, "2025-12-30", 1000, 24),    # shared
    (11, "2026-07-09", 500, 25),
    (16, "2026-07-09", 500, 26),
    (17, "2026-09-03", 151, 27),     # + 40 placeholders, written separately
]
SCANNED_SHIPMENTS = (31, 32)   # the only deliveries anybody physically scanned
REVERSED_DUPLICATE = 30        # shipment 30 was reversed and re-recorded as 31

PROTO_DELIVERIES = [(12, 15, "2023-11-30", 15), (13, 16, "2024-02-16", 20)]
PROTO_STOCK = 10
PLACEHOLDERS = 40
PLACEHOLDER_SHIPMENT = 27
PLACEHOLDER_DATE = "2026-09-03"
PLACEHOLDER_NOTE = (
    "Placeholder. 191 devices physically left on 2026-09-03 and only 151 can be "
    "named; this row stands for one of the 40 that cannot. Delivered, never "
    "identified — replace it if the real serial ever surfaces.")
PROTO_NOTE = (
    "Prototype assembled by LCSC before any batch existed. Programmed with a "
    "placeholder serial: no records were kept at the time.")

TARGET = {   # batch label -> (programmed, at customer, in stock, scrapped)
    "Batch 1": (521, 489, 32, 0), "Batch 2": (349, 349, 0, 0),
    "Batch 3": (406, 406, 0, 0),  "Batch 4": (599, 599, 0, 0),
    "Batch 5": (568, 568, 0, 0),  "Batch 6": (992, 992, 0, 0),
    "Batch 7": (1025, 1024, 0, 1),
}


def bname(run):
    return run.label.split("—")[0].strip() if run else "no batch"


def d(iso, h=12):
    return datetime.fromisoformat(iso).replace(hour=h, tzinfo=UTC)


def main():
    db = SessionLocal()
    runs = {r.id: r for r in db.query(M.ProductionRun).all()}
    lines = {l.id: l for l in db.query(M.SalesOrderLine).all()}
    dongle_line = {l.order_id: l.id for l in lines.values() if l.project_id == DONGLE}
    note = []

    # ---------------------------------------------------------------- read
    existing = db.query(M.DeviceUnit).filter_by(project_id=DONGLE).all()
    by_id = {x.id: x for x in existing}
    never = {x.id for x in existing if x.state == "disposed"}
    scrapped_id = next(x.id for x in existing
                       if x.state == "disposed" and x.production_run_id == 11)
    held = sorted(never - {scrapped_id})
    unbatched = [x.id for x in existing if x.production_run_id is None]

    pinned = defaultdict(list)
    for sid in SCANNED_SHIPMENTS:
        for e in db.query(M.DeviceEvent).filter_by(shipment_id=sid, kind="shipped").all():
            pinned[sid].append(e.device_id)
    pinned_ids = {i for v in pinned.values() for i in v}

    pool = [x for x in sorted(existing, key=lambda x: (x.first_seen, x.id))
            if x.state == "shipped" and x.id not in pinned_ids and x.id not in never]

    note.append(f"existing dongle devices: {len(existing)}")
    note.append(f"held (never sent): {len(held)} · scrapped: 1 · unbatched failures: {len(unbatched)}")
    note.append(f"scanned and pinned: {len(pinned_ids)} · pool to allocate: {len(pool)}")

    want = sum(q for _, _, q, _ in SEQUENCE)
    assert len(pool) == want, f"pool {len(pool)} != sequence {want}"

    # -------------------------------------------------------------- delete
    old_events = (db.query(M.DeviceEvent)
                  .filter(M.DeviceEvent.device_id.in_(by_id.keys())).count())
    old_sl = [sl for sl in db.query(M.ShipmentLine).all()
              if lines[sl.order_line_id].project_id == DONGLE]
    note.append(f"to delete: {old_events} dongle events, {len(old_sl)} anonymous "
                f"shipment line(s) ({sum(s.qty_unserialized for s in old_sl)} units), "
                f"shipment {REVERSED_DUPLICATE} (the reversed duplicate)")

    if APPLY:
        db.query(M.DeviceEvent).filter(M.DeviceEvent.device_id.in_(by_id.keys())).delete(
            synchronize_session=False)
        for sl in old_sl:
            db.delete(sl)
        dup = db.get(M.Shipment, REVERSED_DUPLICATE)
        if dup is not None:
            db.delete(dup)
        db.flush()

    # -------------------------------------------------------------- create
    protos, phs = [], []
    if APPLY:
        for n in range(1, 45 + 1):
            u = M.DeviceUnit(project_id=DONGLE, serial=f"PROTO-{n:04d}", mac=None,
                             chip="", tasmota_id="", first_seen=d("2023-11-01"),
                             last_seen=d("2023-11-01"), last_status="pass",
                             notes=PROTO_NOTE, state="", condition="prototype")
            db.add(u)
            protos.append(u)
        for n in range(1, PLACEHOLDERS + 1):
            u = M.DeviceUnit(project_id=DONGLE, serial=f"PH-{n:04d}", mac=None,
                             chip="", tasmota_id="", first_seen=d(PLACEHOLDER_DATE),
                             last_seen=d(PLACEHOLDER_DATE), last_status="pass",
                             notes=PLACEHOLDER_NOTE, state="", condition="unidentified")
            db.add(u)
            phs.append(u)
        db.flush()
    note.append(f"to create: 45 PROTO-0001..0045 (prototype) and "
                f"{PLACEHOLDERS} PH-0001..{PLACEHOLDERS:04d} (unidentified)")

    # --------------------------------------------------------------- write
    ev = []

    def event(dev_id, kind, at, **kw):
        ev.append(dict(device_id=dev_id, kind=kind, at=at, actor=ACTOR, auto=False, **kw))

    # every device was produced, dated when the flasher first saw it
    for x in existing:
        event(x.id, "produced", x.first_seen, production_run_id=x.production_run_id,
              note="rebuilt from the flasher's own records")
    for u in protos:
        event(u.id, "produced", u.first_seen, note=PROTO_NOTE)
    for u in phs:
        event(u.id, "produced", u.first_seen, note=PLACEHOLDER_NOTE)

    # deliveries, oldest first
    i = 0
    plan_rows, ship_new = [], {}
    for order_id, date_iso, qty, ship_id in SEQUENCE:
        take = pool[i:i + qty]
        i += qty
        if ship_id is None and APPLY:
            s = M.Shipment(order_id=order_id, kind="delivery", shipped_at=date_iso,
                           delivery_note="", tracking="",
                           notes="the remainder of order 1, once Batch 2 arrived "
                                 "(reconstruction 2026-09-18)")
            db.add(s)
            db.flush()
            ship_id = s.id
            ship_new[(order_id, date_iso)] = s.id
        for x in take:
            event(x.id, "shipped", d(date_iso), order_line_id=dongle_line[order_id],
                  shipment_id=ship_id, note="rebuilt from the batch->order cascade")
        plan_rows.append((order_id, date_iso, len(take), ship_id,
                          Counter(bname(runs.get(x.production_run_id)) for x in take)))

    # the prototypes that were sold
    off = 0
    for order_id, ship_id, date_iso, qty in PROTO_DELIVERIES:
        for u in protos[off:off + qty]:
            event(u.id, "shipped", d(date_iso), order_line_id=dongle_line[order_id],
                  shipment_id=ship_id, note="prototype delivered; no serial was recorded")
        plan_rows.append((order_id, date_iso, qty, ship_id, Counter({"prototype": qty})))
        off += qty
    # the rest stay on the shelf (off .. 45)

    # the 40 that cannot be named, on the delivery they left with
    for u in phs:
        event(u.id, "shipped", d(PLACEHOLDER_DATE), order_line_id=dongle_line[17],
              shipment_id=PLACEHOLDER_SHIPMENT, note=PLACEHOLDER_NOTE)
    plan_rows.append((17, PLACEHOLDER_DATE, PLACEHOLDERS, PLACEHOLDER_SHIPMENT,
                      Counter({"placeholder": PLACEHOLDERS})))

    # the scanned deliveries, exactly as they were scanned
    for sid in SCANNED_SHIPMENTS:
        s = db.get(M.Shipment, sid)
        for dev_id in pinned[sid]:
            event(dev_id, "shipped", d(s.shipped_at), order_line_id=dongle_line[17],
                  shipment_id=sid, note="scanned out; serial observed, not inferred")
        plan_rows.append((17, s.shipped_at, len(pinned[sid]), sid,
                          Counter(bname(runs.get(by_id[i].production_run_id))
                                  for i in pinned[sid])))

    # the one that was scrapped
    event(scrapped_id, "disposed", d("2026-09-17"), note="dead USB port")

    # ------------------------------------------------------------- persist
    if APPLY:
        # A device's history is read in `at` order, so it must be monotonic. The
        # events are already in the order they HAPPENED (produced, then each
        # delivery oldest first, then disposal) because that is the order they
        # were appended, so the sequence is authoritative and the dates are not:
        # Batch 6 was still being programmed on 2026-01-07 while order 10 went
        # out on 2025-12-30, so 351 devices carry a `produced` date AFTER the
        # delivery they left on. Sorting by date put `produced` last and left
        # them reading `in_stock`.
        #
        # So each event keeps its nominal date unless that would go backwards,
        # in which case it lands one second after the previous one — the same
        # rule `orders.record_event` applies for the same reason.
        prev = {}
        for e in ev:
            at = e["at"]
            last = prev.get(e["device_id"])
            if last is not None and at <= last:
                at = last + timedelta(seconds=1)
            prev[e["device_id"]] = at
            e["at"] = at
            db.add(M.DeviceEvent(**e))
        db.flush()

        for x in existing:
            x.condition = "faulty" if x.id in never or x.id in unbatched else "ok"
        for u in protos:
            u.condition = "prototype"
        for u in phs:
            u.condition = "unidentified"

        # state is DERIVED from the last event, never typed
        last = {}
        for e in db.query(M.DeviceEvent).order_by(M.DeviceEvent.at, M.DeviceEvent.id).all():
            last[e.device_id] = e.kind
        from app.services.orders import STATE_AFTER
        for x in db.query(M.DeviceUnit).filter_by(project_id=DONGLE).all():
            x.state = STATE_AFTER.get(last.get(x.id, ""), "")
        db.flush()

    # ---------------------------------------------------------------- show
    for line in note:
        print("  " + line)
    print(f"\n{'order':>5} {'delivery':<12} {'qty':>5} {'ship':>5}  sourced from")
    for order_id, date_iso, qty, ship_id, by in plan_rows:
        print(f"{order_id:>5} {date_iso:<12} {qty:>5} {str(ship_id or 'new'):>5}  "
              f"{', '.join(f'{k}: {v}' for k, v in sorted(by.items()))}")
    print(f"\nevents to write: {len(ev)}")

    if not APPLY:
        db.rollback()
        print("\nDRY RUN — nothing written")
        return

    # --------------------------------------------------------------- check
    print("\n--- verification, from the platform's own reads ---")
    ok = True
    rows = db.query(M.DeviceUnit).filter_by(project_id=DONGLE).all()
    per = defaultdict(Counter)
    for x in rows:
        per[bname(runs.get(x.production_run_id))][x.state] += 1
    print(f"{'batch':<10} {'made':>6} {'customer':>9} {'stock':>6} {'scrap':>6}  invariant")
    for label, (made, cust, stock, scrap) in TARGET.items():
        c = per[label]
        got = (sum(c.values()), c["shipped"], c["in_stock"], c["disposed"])
        good = got == (made, cust, stock, scrap) and got[0] == got[1] + got[2] + got[3]
        ok &= good
        print(f"{label:<10} {got[0]:>6} {got[1]:>9} {got[2]:>6} {got[3]:>6}  "
              f"{'ok' if good else f'EXPECTED {(made, cust, stock, scrap)}'}")
    nb = per["no batch"]
    # 3 unbatched failures + 45 prototypes + 40 placeholders, none of which
    # belongs to a batch.
    nb_ok = (sum(nb.values()), nb["shipped"], nb["in_stock"]) == (88, 75, 13)
    ok &= nb_ok
    print(f"{'no batch':<10} {sum(nb.values()):>6} {nb['shipped']:>9} {nb['in_stock']:>6} "
          f"{nb['disposed']:>6}  {'ok' if nb_ok else 'EXPECTED (88, 75, 13)'}")

    print(f"\ntotal devices: {len(rows)} (target 4548)")
    ok &= len(rows) == 4548
    cond = Counter((x.state, x.condition) for x in rows)
    for k in sorted(cond):
        print(f"   {k[0] or '(none)':<10} {k[1]:<13} {cond[k]}")

    from app.services import orders as osvc
    print("\norder fulfilment, read through the platform:")
    for oid in (12, 13, 1, 2, 7, 8, 9, 10, 11, 16, 17, 19):
        line_id = dongle_line.get(oid)
        n = db.query(M.DeviceEvent).filter_by(order_line_id=line_id, kind="shipped").count()
        want = lines[line_id].qty_ordered
        flag = "" if n == want else ("  OWED " + str(want - n))
        print(f"   order {oid:>3}: ordered {want:>4}  delivered {n:>4}{flag}")

    if not ok:
        db.rollback()
        raise SystemExit("VERIFICATION FAILED — rolled back, nothing written")
    if REHEARSE:
        db.rollback()
        print("\nREHEARSAL — verified, then rolled back. Nothing written.")
        return
    db.commit()
    print("\nCOMMITTED")


main()
