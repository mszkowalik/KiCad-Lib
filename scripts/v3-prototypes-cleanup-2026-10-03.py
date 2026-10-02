"""Clean up the CE_Dongle_V3 prototype orders: two invented, six real units.

User facts 2026-10-03 (docs/reference/stock-count-2026-10.md):

  * Columbus placed NO V3 order before RA 00001/09/2026 (50 pcs). Orders #5
    (5 x V3.1, 2025-11-03) and #6 (10 x V3.3, 2026-08-03) were made by the
    removed startup migration from typed run sale fields. Neither has an
    invoice. They are not orders.
  * Every V3.1, V3.2 and V3.3 prototype was originally STOCKED.
  * What really left: 5 x V3.2 SENT to Columbus about a month before
    2026-10-03, and 1 x V3.3 GIVEN on Saturday 2026-09-26.
  * Everything else is a prototype in stock, not sellable.

What it writes, through services/orders.py:

  1. Reverse shipments #5 and #6 (decision 0028: reversed, not deleted) and
     cancel orders #5 and #6. An order with device history cannot be deleted.
  2. One new Columbus order, NOT invoiced (0 PLN, no order existed), with two
     deliveries: 5 Run #1 (V3.2) records on 2026-09-03 (approximate), 1 Run #2
     (V3.3) record on 2026-09-26. Which exact boards went is unknown, so the
     shipped records are UNNAMED placeholders — the broker can name them
     later (decision 0054). A prototype that left is condition `ok` (0049).
  3. Every other record of the three prototype runs: in stock, condition
     `prototype` — counted, never sellable.

Batch 1 (the 50-piece production batch) is not touched.

ONE-TIME. Run through STDIN (api/CLAUDE.md):

    docker compose exec -T api python - < scripts/v3-prototypes-cleanup-2026-10-03.py
    docker compose exec -T -e REHEARSE=1 api python - < scripts/…
    docker compose exec -T -e APPLY=1 api python - < scripts/…
"""
import os

from sqlalchemy import func, select

from app import models as M
from app.db import SessionLocal
from app.services import orders as osvc

assert M.__file__ == "/srv/app/models.py", f"stale app package: {M.__file__}"

APPLY = os.environ.get("APPLY") == "1"
REHEARSE = os.environ.get("REHEARSE") == "1"
WRITE = APPLY or REHEARSE
ACTOR = "stock-count-2026-10-02"
DATE = "2026-10-03"
REF = "docs/reference/stock-count-2026-10.md"
PROJECT = "CE_Dongle_V3"
CUSTOMER = "Columbus Energy"

RUN_V31, RUN_V32, RUN_V33 = 18, 17, 20
FAKE = {5: 5, 6: 6}                     # order id -> its one shipment id
V32_SENT_AT, V33_GIVEN_AT = "2026-09-03", "2026-09-26"


def main():
    db = SessionLocal()
    try:
        project = db.scalar(select(M.Project).where(M.Project.name == PROJECT))
        assert project is not None
        runs = {rid: db.get(M.ProductionRun, rid) for rid in (RUN_V31, RUN_V32, RUN_V33)}
        for rid, label in ((RUN_V31, "V3.1"), (RUN_V32, "V3.2"), (RUN_V33, "V3.3")):
            r = runs[rid]
            assert r is not None and r.project_id == project.id and label in r.label, (rid, r and r.label)

        orders = {}
        for oid, sid in FAKE.items():
            o, sh = db.get(M.SalesOrder, oid), db.get(M.Shipment, sid)
            assert o is not None and sh is not None and sh.order_id == oid and sh.status == "sent", (oid, sid)
            assert not o.cancelled, f"order {oid} already cancelled — stop"
            assert o.order_ref == "" and "migrated from the run's sale fields" in (o.notes or ""), (
                f"order {oid} does not look like a migration artifact — stop")
            inv = db.scalar(select(func.count()).select_from(M.OrderInvoice).where(M.OrderInvoice.order_id == oid))
            assert inv == 0, f"order {oid} has {inv} invoices — stop"
            assert all(li.project_id == project.id for li in o.lines), f"order {oid} names another project — stop"
            orders[oid] = (o, sh)

        def devices(rid):
            return db.scalars(select(M.DeviceUnit).where(M.DeviceUnit.production_run_id == rid)
                              .order_by(M.DeviceUnit.id)).all()

        v31, v32, v33 = devices(RUN_V31), devices(RUN_V32), devices(RUN_V33)
        assert len(v31) == 5 and all(d.state == "shipped" for d in v31), [d.state for d in v31]
        assert len(v33) == 10 and all(d.state == "shipped" for d in v33), [d.state for d in v33]
        assert len(v32) == 10 and all(d.state == "in_stock" for d in v32), [d.state for d in v32]
        for d in v31:
            assert [e.shipment_id for e in osvc.live_shipped_of(d)] == [FAKE[5]], d.id
        for d in v33:
            assert [e.shipment_id for e in osvc.live_shipped_of(d)] == [FAKE[6]], d.id
        v32_send = [d for d in v32 if d.mac is None][:5]
        v33_give = [d for d in v33 if d.mac is None][:1]
        assert len(v32_send) == 5 and len(v33_give) == 1, (len(v32_send), len(v33_give))

        print("1. reverse shipments #5, #6 and cancel orders #5, #6")
        print("2. new non-invoiced Columbus order: 5 x V3.2 on", V32_SENT_AT, [d.id for d in v32_send],
              "| 1 x V3.3 on", V33_GIVEN_AT, [d.id for d in v33_give])
        rest = [d for d in v31 + v32 + v33 if d not in v32_send + v33_give]
        print(f"3. {len(rest)} prototype records -> in stock, condition prototype")
        if not WRITE:
            print("\ndry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        # 1 ----------------------------------------------------------------------
        why = (f"[{DATE}] Not a real order: made by the removed startup migration from typed "
               f"run sale fields. Columbus placed no V3 order before RA 00001/09/2026 (user). See {REF}")
        for oid, (o, sh) in orders.items():
            osvc.reverse_shipment(db, sh, actor=ACTOR, dry_run=False,
                                  note=f"[{DATE}] invented delivery: these prototypes never left (user)")
            o.cancelled = True
            o.notes = ((o.notes + "\n") if o.notes else "") + why
            osvc.refresh_order_status(o)
        db.flush()

        # 2 ----------------------------------------------------------------------
        cust = osvc.get_customer(db, CUSTOMER)
        order = M.SalesOrder(customer_id=cust.id, order_ref="", order_date=V32_SENT_AT, currency="PLN",
                             notes=(f"[{DATE}] Prototypes that really left, recorded at the stock count. "
                                    "NO order and NO invoice exist (user): 5 x V3.2 sent about a month "
                                    f"before {DATE} (date approximate), 1 x V3.3 given on {V33_GIVEN_AT}. "
                                    f"Which exact boards went is unknown. See {REF}"))
        db.add(order)
        db.flush()
        line = M.SalesOrderLine(order_id=order.id, project_id=project.id, board="", variant="",
                                product="CE_Dongle_V3 prototypes", qty_ordered=6, unit_price=0.0, position=0)
        db.add(line)
        db.flush()
        db.expire(order, ["lines"])
        for d in v32_send + v33_give:
            d.condition = "ok"
            d.notes = ((d.notes + "\n") if d.notes else "") + (
                f"[{DATE}] This record stands for one of the prototypes that went to Columbus; which "
                f"physical board is unknown. See {REF}")
        db.flush()
        sh_a = osvc.create_shipment(db, order, shipped_at=V32_SENT_AT, actor=ACTOR,
                                    delivery_note="5 x V3.2 prototypes sent (date approximate)",
                                    lines=[{"order_line_id": line.id, "device_ids": [d.id for d in v32_send]}])
        sh_b = osvc.create_shipment(db, order, shipped_at=V33_GIVEN_AT, actor=ACTOR,
                                    delivery_note="1 x V3.3 prototype given",
                                    lines=[{"order_line_id": line.id, "device_ids": [d.id for d in v33_give]}])
        db.flush()

        # 3 ----------------------------------------------------------------------
        for d in rest:
            db.refresh(d)
            assert d.state == "in_stock", (d.id, d.state)
            d.condition = "prototype"
        db.add(M.AuditLog(
            action="stock.count", entity_type="project", entity_id=str(project.id), actor=ACTOR,
            details={"date": DATE, "reference": REF, "cancelled_orders": list(FAKE),
                     "reversed_shipments": list(FAKE.values()), "new_order_id": order.id,
                     "shipments": [sh_a.id, sh_b.id],
                     "shipped_placeholders": [d.id for d in v32_send + v33_give],
                     "to_prototype": [d.id for d in rest]}))
        db.flush()

        # verify -----------------------------------------------------------------
        for oid, (o, _) in orders.items():
            db.refresh(o)
            assert o.cancelled and o.status == "cancelled", (oid, o.status)
            assert sum(osvc.line_shipped(li) for li in o.lines) == 0, oid
        assert osvc.line_shipped(line) == 6
        assert all(d.state == "shipped" and d.condition == "ok" for d in v32_send + v33_give)
        assert all(d.state == "in_stock" and d.condition == "prototype" for d in rest)
        p = next(x for x in osvc.product_stock(db) if x["project_id"] == project.id)
        print("CE_Dongle_V3 after:", {k: p[k] for k in ("in_stock", "available", "held", "shipped", "missing")})
        print(f"new order {order.id}; shipments {sh_a.id}, {sh_b.id}")

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print("\nAPPLIED.")
    finally:
        db.close()


main()
