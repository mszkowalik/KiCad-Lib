#!/usr/bin/env python3
"""Built = finished and passed (Mateusz, 2026-09-10).

A device whose NEWEST programming or test run did not pass is not a built
device: it has no `produced` event, no shelf entry, and cannot be picked for a
shipment. The retro link had given every imported device a `produced` event.

Steps: (1) remember what each shipment delivered per order line; (2) drop the
`produced` and `shipped` events of every project-2/3 device with last_status
<> 'pass'; (3) drop every other `shipped` event (all FIFO picks) and re-pick
oldest-first from passed devices only. Dry-run by default, --apply commits.
"""
import sys
from collections import Counter, defaultdict

from sqlalchemy import text

from app import models as M
from app.db import SessionLocal
from app.services import orders as svc

APPLY = "--apply" in sys.argv
ACTOR = "cleanup 2026-09-10 built=passed (Claude, on Mateusz's instruction)"
P = (2, 3)
db = SessionLocal()
q = lambda s, **kw: db.execute(text(s), kw)
say = lambda *a: print(*a, flush=True)

targets: dict[tuple[int, int], int] = defaultdict(int)
for sid, lid, n in q("""SELECT e.shipment_id, e.order_line_id, count(*) FROM device_events e
    JOIN device_units d ON d.id = e.device_id WHERE e.kind = 'shipped' AND d.project_id = ANY(:p) GROUP BY 1, 2""", p=list(P)):
    targets[(sid, lid)] += n
say("targets:", sorted(targets.items()))

failed = [r[0] for r in q("SELECT id FROM device_units WHERE project_id = ANY(:p) AND last_status <> 'pass'", p=list(P))]
say(f"devices whose newest run is not a pass: {len(failed)}")
for st, n in q("SELECT state, count(*) FROM device_units WHERE id = ANY(:ids) GROUP BY 1", ids=failed):
    say(f"  currently {st!r}: {n}")
n = q("DELETE FROM device_events WHERE device_id = ANY(:ids) AND kind IN ('produced', 'shipped')", ids=failed).rowcount
say(f"  removed {n} produced/shipped events")
q("""UPDATE device_units SET state = '', production_run_id = NULL,
    notes = notes || :n WHERE id = ANY(:ids)""", ids=failed,
  n="\n[2026-09-10] Not counted as built: the newest programming/test run did not pass. A later pass puts it on the shelf.")
for did in failed:
    db.add(M.AuditLog(actor=ACTOR, action="device.unbuilt", entity_type="device_unit", entity_id=str(did),
                      details={"reason": "newest run did not pass"}))
n = q("""DELETE FROM device_events e USING device_units d
    WHERE d.id = e.device_id AND d.project_id = ANY(:p) AND e.kind = 'shipped'""", p=list(P)).rowcount
say(f"dropped {n} remaining FIFO picks")
q("UPDATE device_units SET state = 'in_stock' WHERE project_id = ANY(:p) AND production_run_id IS NOT NULL", p=list(P))
assert q("""SELECT count(*) FROM device_units d WHERE d.project_id = ANY(:p) AND d.production_run_id IS NOT NULL AND
    (SELECT count(*) FROM device_events e WHERE e.device_id = d.id AND e.kind = 'produced') <> 1""", p=list(P)).scalar() == 0
db.expire_all()

avail = {r[0]: r[1] for r in q("""SELECT d.id, GREATEST(d.first_seen, max(r.started_at))
    FROM device_units d LEFT JOIN programming_runs r ON r.device_unit_id = d.id
    WHERE d.project_id = ANY(:p) AND d.production_run_id IS NOT NULL GROUP BY d.id, d.first_seen""", p=list(P))}
pools = {}
for pid in P:
    devs = db.query(M.DeviceUnit).filter(M.DeviceUnit.project_id == pid, M.DeviceUnit.production_run_id.isnot(None)).all()
    pools[pid] = sorted(devs, key=lambda d: (avail[d.id], d.first_seen, d.id))
    say(f"project {pid}: {len(devs)} passed devices")
picked = Counter(); warn = 0
for sh in db.query(M.Shipment).filter(M.Shipment.kind == "delivery").order_by(M.Shipment.shipped_at, M.Shipment.id).all():
    for li in sh.order.lines:
        want = targets.get((sh.id, li.id))
        if not want:
            continue
        take = [d for d in pools[li.project_id] if d.state == "in_stock"][:want]
        assert len(take) == want, f"shipment {sh.id} line {li.id}: {len(take)} of {want}"
        at = svc._date_at(sh.shipped_at)
        late = sum(1 for d in take if avail[d.id].date() > at.date())
        if late:
            warn += 1
            say(f"  note: shipment {sh.id} ({sh.shipped_at}) line {li.id}: {late} of {want} devices flashed after the shipment date")
        for d in take:
            svc.record_event(db, d, "shipped", at=at, actor=ACTOR, auto=True, order_line_id=li.id, shipment_id=sh.id,
                             note="oldest-first re-pick from passed devices, 2026-09-10")
        picked[(sh.id, li.id)] = want
        say(f"shipment {sh.id} {sh.shipped_at} {sh.order.order_ref!r} line {li.id}: {want} from {sorted(Counter(d.production_run_id for d in take).items())}")
db.flush()
assert picked == targets
for o in db.query(M.SalesOrder).all():
    db.expire(o, ["lines", "shipments"]); svc.refresh_order_status(o)
db.flush()
say("\n== shelf ==")
for r in svc.run_stock(db):
    if r["project_id"] in P:
        say(f"  {r['project']:12} {r['label']:22} typed {r['built']:5} devices {r['devices_produced']:5} in_stock {r['devices_in_stock']:4} shipped {r['devices_shipped']:5} legacy {r['legacy_stock']:4} overdrawn {r['overdrawn']:4}")
for d in svc.project_demand(db):
    say("  ", d["project"], "open", d["open"], "on_shelf", d["on_shelf"])
if APPLY:
    db.commit(); say("COMMITTED")
else:
    db.rollback(); say("DRY RUN — rolled back")
