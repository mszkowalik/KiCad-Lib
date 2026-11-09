"""Writing a plan (decision 0107): the plan, its draft orders and their
deliveries, its date nodes, planned batches, machining lots, purchase orders,
reservations and customer-supplied parts. `services/planning.py` computes; this
module stores what a person typed or accepted, and checks that a node only
follows what belongs to the same plan.

The rules are in docs/reference/planning.md.
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from . import planning as PL

# ---------------------------------------------------------------- helpers


def get_plan(db: Session, plan_id: int) -> M.Plan:
    p = db.get(M.Plan, plan_id)
    if p is None:
        raise HTTPException(404, "plan not found")
    return p


def _day(value: str | None, field: str) -> str:
    v = (value or "").strip()
    if v and PL.parse_day(v) is None:
        raise HTTPException(422, f"{field} is not a date (YYYY-MM-DD): {v}")
    return v


def check_refs(db: Session, plan: M.Plan, refs: list[str] | None, own_id: int | None = None) -> list[str]:
    """A node follows only what belongs to its plan: a node of the plan, or
    one of the plan's orders."""
    out = []
    for r in refs or []:
        kind, _, ident = str(r).partition(":")
        try:
            n = int(ident)
        except ValueError:
            raise HTTPException(422, f"'{r}' is not a reference (n:<node>, order:<order>, advance:<order>)") from None
        if kind == "n":
            node = db.get(M.PlanNode, n)
            if node is None or node.plan_id != plan.id:
                raise HTTPException(422, f"node {n} is not in this plan")
            if own_id is not None and n == own_id:
                raise HTTPException(422, "a node cannot follow itself")
        elif kind in ("order", "advance"):
            o = db.get(M.SalesOrder, n)
            if o is None or o.plan_id != plan.id:
                raise HTTPException(422, f"order {n} is not in this plan")
        else:
            raise HTTPException(422, f"'{r}' is not a reference (n:<node>, order:<order>, advance:<order>)")
        out.append(f"{kind}:{n}")
    return out


NODE_FIELDS = ("label", "mode", "day", "after", "lag", "lag_unit", "snap_weekday", "end_day", "duration_days",
               "source", "source_text", "party", "done_on", "amount", "currency", "position")


def apply_node(db: Session, plan: M.Plan, node: M.PlanNode, data: dict) -> M.PlanNode:
    for k, v in data.items():
        if k not in NODE_FIELDS:
            continue
        if k == "mode" and v not in PL.MODES:
            raise HTTPException(422, f"mode must be one of {', '.join(PL.MODES)}")
        if k == "lag_unit" and v not in PL.LAG_UNITS:
            raise HTTPException(422, f"lag_unit must be one of {', '.join(PL.LAG_UNITS)}")
        if k == "party" and v not in PL.PARTIES:
            raise HTTPException(422, f"party must be one of {', '.join(PL.PARTIES)}")
        if k == "source" and (v or "") not in PL.SOURCES:
            raise HTTPException(422, f"source must be one of {', '.join(s for s in PL.SOURCES if s)}")
        if k == "snap_weekday" and v is not None and not 0 <= int(v) <= 6:
            raise HTTPException(422, "snap_weekday is 0 (Monday) to 6 (Sunday)")
        if k in ("day", "end_day", "done_on"):
            v = _day(v, k)
        if k == "after":
            v = check_refs(db, plan, v, node.id)
        if k == "currency":
            v = (v or "PLN").upper()[:3]
        setattr(node, k, v)
    if node.mode == "fixed" and not node.day and not node.done_on:
        raise HTTPException(422, "a fixed date needs a day")
    if node.mode == "after" and not node.after:
        raise HTTPException(422, "a date that follows needs at least one reference")
    return node


def new_node(db: Session, plan: M.Plan, kind: str, subject_id: int | None, data: dict) -> M.PlanNode:
    if kind not in PL.NODE_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(PL.NODE_KINDS)}")
    n = M.PlanNode(plan_id=plan.id, kind=kind, subject_id=subject_id)
    db.add(n)
    db.flush()
    apply_node(db, plan, n, data)
    db.flush()
    # A node that closes a circle is refused at once, not on the next read.
    sched_nodes = {x.id: x for x in db.query(M.PlanNode).filter(M.PlanNode.plan_id == plan.id)}
    try:
        PL.Dates(date.today(), sched_nodes, {}, {}).node(n.id)
    except PL.CycleError as e:
        raise HTTPException(422, f"the dates would go round in a circle: {e}") from None
    return n


def update_node(db: Session, plan: M.Plan, node: M.PlanNode, data: dict) -> M.PlanNode:
    apply_node(db, plan, node, data)
    db.flush()
    sched_nodes = {x.id: x for x in db.query(M.PlanNode).filter(M.PlanNode.plan_id == plan.id)}
    try:
        D = PL.Dates(date.today(), sched_nodes, {}, {})
        for nid in sched_nodes:
            D.node(nid)
    except PL.CycleError as e:
        raise HTTPException(422, f"the dates would go round in a circle: {e}") from None
    return node


def node_users(db: Session, node: M.PlanNode) -> list[str]:
    """What still follows a node; a node with followers is not deleted."""
    ref = f"n:{node.id}"
    return [n.label or f"{n.kind} {n.id}" for n in db.query(M.PlanNode).filter(M.PlanNode.plan_id == node.plan_id)
            if ref in (n.after or [])]


# ---------------------------------------------------------------- the plan


PLAN_FIELDS = ("name", "customer_id", "company_id", "status", "sent_on", "agreed_on", "currency", "vat_pct",
               "advance_pct", "advance_days", "final_days", "min_lead_months", "advance_limit_net",
               "delivery_weekday", "build_lead_days", "attrition_pct", "notes")


def apply_plan(db: Session, p: M.Plan, data: dict) -> None:
    for k, v in data.items():
        if k not in PLAN_FIELDS:
            continue
        if k == "status" and v not in ("draft", "sent", "agreed"):
            raise HTTPException(422, "status is draft, sent or agreed")
        if k in ("sent_on", "agreed_on"):
            v = _day(v, k)
        if k == "customer_id" and v is not None and db.get(M.Customer, v) is None:
            raise HTTPException(404, "customer not found")
        if k == "name":
            v = (v or "").strip()
            if not v:
                raise HTTPException(422, "a plan needs a name")
        if k == "delivery_weekday" and v is not None and not 0 <= int(v) <= 6:
            raise HTTPException(422, "delivery_weekday is 0 (Monday) to 6 (Sunday)")
        setattr(p, k, v)
    if p.status == "sent" and not p.sent_on:
        p.sent_on = date.today().isoformat()
    if p.status == "agreed" and not p.agreed_on:
        p.agreed_on = date.today().isoformat()


def set_projects(db: Session, p: M.Plan, rows: list[dict]) -> None:
    """Replace the designs the plan builds from (decision 0107 item 10)."""
    keep = {}
    for r in rows:
        pid = r.get("project_id")
        if db.get(M.Project, pid) is None:
            raise HTTPException(404, f"project {pid} not found")
        mode = r.get("snapshot_mode") or "fixed"
        if mode not in ("fixed", "branch"):
            raise HTTPException(422, "snapshot_mode is fixed or branch")
        sid = r.get("snapshot_id")
        if mode == "fixed":
            snap = db.get(M.ProjectSnapshot, sid) if sid else None
            if snap is None or snap.project_id != pid:
                raise HTTPException(422, f"project {pid}: a fixed design needs a snapshot of that project")
        keep[pid] = r
    for pp in list(p.projects):
        if pp.project_id not in keep:
            p.projects.remove(pp)
    have = {pp.project_id: pp for pp in p.projects}
    for pid, r in keep.items():
        pp = have.get(pid) or M.PlanProject(project_id=pid)
        if pid not in have:
            p.projects.append(pp)
        pp.snapshot_mode = r.get("snapshot_mode") or "fixed"
        pp.snapshot_id = r.get("snapshot_id") if pp.snapshot_mode == "fixed" else None
        pp.branch = (r.get("branch") or ("main" if pp.snapshot_mode == "branch" else "")).strip()
        pp.board = (r.get("board") or "").strip()
        pp.variant = (r.get("variant") or "").strip()
        pp.line_rate_week = r.get("line_rate_week")
    db.flush()


def mark_reviewed(db: Session, p: M.Plan) -> dict:
    """Record the designs a person reviewed, and move the planned batches to
    them (decision 0107 items 11 and 12). An ordered batch keeps its pins."""
    from . import process as P

    seen, moved = {}, []
    for pp in p.projects:
        snap = PL.resolve_snapshot(db, pp)
        v = P.current_version(db, pp.project_id)
        seen[str(pp.project_id)] = {"snapshot_id": snap.id if snap else None,
                                    "process_version_id": v.id if v else None}
        for r in db.query(M.ProductionRun).filter(M.ProductionRun.plan_id == p.id,
                                                  M.ProductionRun.project_id == pp.project_id,
                                                  M.ProductionRun.status == "planned"):
            changed = False
            if snap is not None and r.snapshot_id != snap.id:
                r.snapshot_id, changed = snap.id, True
                r.board = r.board or PL.board_of(snap, pp)
            if v is not None and r.process_version_id != v.id:
                r.process_version_id, changed = v.id, True
            if changed:
                moved.append(r.id)
    p.reviewed = seen
    db.flush()
    return {"reviewed": seen, "moved_batches": moved}


def sync_run_dates(db: Session, p: M.Plan) -> None:
    """A planned batch's `run_date` is the order date its node computes, so the
    batch lists say what the plan says. It is written whenever the plan is
    written, never on a read."""
    runs = db.query(M.ProductionRun).filter(M.ProductionRun.plan_id == p.id,
                                            M.ProductionRun.status == "planned").all()
    if not runs:
        return
    s = PL.schedule(db, p, with_parts=False)
    by_id = {b["id"]: b for b in s["batches"]}
    for r in runs:
        b = by_id.get(r.id)
        if b and b["order_day"] and r.run_date != b["order_day"]:
            r.run_date = b["order_day"]


# ---------------------------------------------------------------- orders


def add_order(db: Session, p: M.Plan, body: dict, actor: str) -> M.SalesOrder:
    """A draft order of the plan, with its lines and their deliveries."""
    from . import companies as company_svc
    from . import orders as order_svc

    cust_id = body.get("customer_id") or p.customer_id
    cust = db.get(M.Customer, cust_id) if cust_id else None
    if cust is None:
        raise HTTPException(422, "the plan or the order needs a customer")
    od = _day(body.get("order_date"), "order_date")
    if not od:
        raise HTTPException(422, "a draft order needs an order date")
    o = M.SalesOrder(customer_id=cust.id, order_ref=(body.get("order_ref") or "").strip(), order_date=od,
                     currency=(body.get("currency") or p.currency or "PLN").upper(), vat_pct=p.vat_pct,
                     notes=body.get("notes") or "", draft=True, plan_id=p.id,
                     plan_key=(body.get("plan_key") or "").strip()[:40],
                     advance_due=_day(body.get("advance_due"), "advance_due"))
    db.add(o)
    db.flush()
    for i, li in enumerate(body.get("lines") or []):
        if db.get(M.Project, li.get("project_id")) is None:
            raise HTTPException(404, f"project {li.get('project_id')} not found")
        if (li.get("qty_ordered") or 0) < 1:
            raise HTTPException(422, "qty_ordered must be >= 1")
        row = M.SalesOrderLine(order_id=o.id, project_id=li["project_id"], board=(li.get("board") or "").strip(),
                               variant=(li.get("variant") or "").strip(), product=(li.get("product") or "").strip(),
                               qty_ordered=li["qty_ordered"], unit_price=li.get("unit_price") or 0.0, position=i)
        db.add(row)
        db.flush()
        set_deliveries(db, p, o, row, li.get("deliveries") or [])
    company = (company_svc.get(db, body["company_id"]) if body.get("company_id")
               else (company_svc.get(db, p.company_id) if p.company_id else None))
    o.company_id = company.id if company else None
    db.expire(o, ["lines"])
    order_svc.refresh_order_status(o)
    return o


def set_deliveries(db: Session, p: M.Plan, o: M.SalesOrder, line: M.SalesOrderLine, rows: list[dict]) -> None:
    """Replace a line's delivery schedule. Each row is a quantity and a date:
    `{"qty", "day"}` (fixed) or `{"qty", "after", "lag", "lag_unit",
    "snap_weekday"}`. `after` defaults to the order's advance."""
    old = db.query(M.SalesOrderDelivery).filter(M.SalesOrderDelivery.order_line_id == line.id).all()
    old_nodes = [d.node_id for d in old if d.node_id]
    for d in old:
        db.delete(d)
    db.flush()
    for nid in old_nodes:
        n = db.get(M.PlanNode, nid)
        if n is not None:
            users = node_users(db, n)
            if users:
                raise HTTPException(409, f"other dates follow a delivery of this line ({', '.join(users[:3])}); "
                                         "change them first")
            db.delete(n)
    db.flush()
    for i, r in enumerate(rows):
        qty = int(r.get("qty") or 0)
        if qty < 1:
            raise HTTPException(422, "a delivery needs a quantity of 1 or more")
        data = {"label": f"{o.plan_key or o.order_ref or 'order'} delivery {i + 1}", "party": "ours",
                "position": i,
                "snap_weekday": r["snap_weekday"] if r.get("snap_weekday") is not None else p.delivery_weekday}
        if r.get("after") or r.get("mode") == "after":
            data.update(mode="after", after=r.get("after") or [f"advance:{o.id}"], lag=int(r.get("lag") or 0),
                        lag_unit=r.get("lag_unit") or "days")
        else:
            data.update(mode="fixed", day=r.get("day") or "")
        for k in ("source", "source_text", "done_on"):
            if r.get(k) is not None:
                data[k] = r[k]
        n = new_node(db, p, "delivery", None, data)
        dv = M.SalesOrderDelivery(order_line_id=line.id, qty=qty, node_id=n.id, position=i)
        db.add(dv)
        db.flush()
        n.subject_id = dv.id
    db.flush()


def delete_order_plan_rows(db: Session, o: M.SalesOrder) -> None:
    """Before an order or a line goes: its deliveries and their nodes."""
    line_ids = [li.id for li in o.lines]
    if not line_ids:
        return
    for d in db.query(M.SalesOrderDelivery).filter(M.SalesOrderDelivery.order_line_id.in_(line_ids)).all():
        nid = d.node_id
        db.delete(d)
        if nid:
            n = db.get(M.PlanNode, nid)
            if n is not None:
                db.delete(n)
    db.flush()


# ---------------------------------------------------------------- batches


def add_batch(db: Session, p: M.Plan, body: dict) -> M.ProductionRun:
    """A planned batch with an order node and an arrival node."""
    from . import companies as company_svc
    from . import process as P

    pid = body.get("project_id")
    if db.get(M.Project, pid) is None:
        raise HTTPException(404, "project not found")
    qty = int(body.get("qty") or 0)
    if qty < 1:
        raise HTTPException(422, "qty must be >= 1")
    pp = next((x for x in p.projects if x.project_id == pid), None)
    if pp is None:
        raise HTTPException(422, "add the project to the plan's designs first")
    snap = PL.resolve_snapshot(db, pp)
    v = P.current_version(db, pid)
    r = M.ProductionRun(project_id=pid, label=(body.get("label") or "").strip() or f"Planned batch — {qty} pcs",
                        snapshot_id=snap.id if snap else None, board=PL.board_of(snap, pp), variant=pp.variant or "",
                        qty=qty, status="planned", notes=body.get("notes") or "", plan_id=p.id,
                        process_version_id=v.id if v else None)
    owner = company_svc.get(db, p.company_id) if p.company_id else company_svc.default_run_company(db, r)
    r.company_id = owner.id if owner else None
    db.add(r)
    db.flush()
    order = body.get("order") or {}
    on = new_node(db, p, "batch_order", r.id, {"label": f"Order {r.label}", "party": "ours",
                                               "mode": order.get("mode") or ("after" if order.get("after") else "fixed"),
                                               "day": order.get("day") or "", "after": order.get("after"),
                                               "lag": order.get("lag") or 0, "lag_unit": order.get("lag_unit") or "days",
                                               "amount": order.get("amount"), "currency": order.get("currency") or "PLN",
                                               "source": order.get("source") or "",
                                               "source_text": order.get("source_text") or ""})
    arr = body.get("arrival") or {}
    after = [f"n:{on.id}"] + list(arr.get("after") or [])
    new_node(db, p, "batch_arrival", r.id, {"label": f"{r.label} arrives", "party": "supplier",
                                            "mode": arr.get("mode") or "after", "day": arr.get("day") or "",
                                            "after": after, "lag": arr.get("lag", 20),
                                            "lag_unit": arr.get("lag_unit") or "days",
                                            "source": arr.get("source") or "estimate",
                                            "source_text": arr.get("source_text") or ""})
    return r


def order_batch(db: Session, p: M.Plan, r: M.ProductionRun, ordered_on: str) -> M.ProductionRun:
    """The planned batch is ordered: it leaves `planned`, its order node is the
    fact, and its snapshot and process version are pinned (decision 0107
    item 11)."""
    from . import process as P

    if r.status != "planned":
        raise HTTPException(409, f"the batch is {r.status}, not planned")
    day = _day(ordered_on, "ordered_on") or date.today().isoformat()
    pp = next((x for x in p.projects if x.project_id == r.project_id), None)
    snap = PL.resolve_snapshot(db, pp) if pp else None
    if snap is not None:
        r.snapshot_id = snap.id
        r.board = r.board or PL.board_of(snap, pp)
    v = P.current_version(db, r.project_id)
    if v is not None:
        r.process_version_id = v.id
    r.status = "in production"
    r.run_date = day
    n = db.query(M.PlanNode).filter(M.PlanNode.kind == "batch_order", M.PlanNode.subject_id == r.id).first()
    if n is not None:
        n.done_on = day
    db.flush()
    return r


def _has_units(db: Session, run_id: int) -> bool:
    """A batch with a twin or a device made in it is no longer only a plan."""
    return bool(db.query(M.Unit.id).filter(M.Unit.run_id == run_id).first()
                or db.query(M.DeviceEvent.id).filter(M.DeviceEvent.production_run_id == run_id).first())


def delete_batch(db: Session, r: M.ProductionRun) -> None:
    if r.status != "planned":
        raise HTTPException(409, "only a planned batch is deleted from the plan")
    if _has_units(db, r.id):
        raise HTTPException(409, "the batch has units")
    for n in db.query(M.PlanNode).filter(M.PlanNode.kind.in_(("batch_order", "batch_arrival")),
                                         M.PlanNode.subject_id == r.id).all():
        db.delete(n)
    db.delete(r)
    db.flush()


# ---------------------------------------------------------------- lots


def apply_lot(db: Session, p: M.Plan, lt: M.PlanLot, data: dict) -> None:
    for k in ("label", "qty", "rate_per_day", "duration_days", "recipe_key", "position"):
        if k in data:
            setattr(lt, k, data[k])
    if (lt.qty or 0) <= 0:
        raise HTTPException(422, "a machining lot needs a quantity")
    if not lt.rate_per_day and not lt.duration_days and PL._recipe_of(db, lt) is None:
        raise HTTPException(422, f"recipe '{lt.recipe_key}' is not in the project's current process")


def add_lot(db: Session, p: M.Plan, body: dict) -> M.PlanLot:
    pid = body.get("project_id")
    if db.get(M.Project, pid) is None:
        raise HTTPException(404, "project not found")
    lt = M.PlanLot(plan_id=p.id, project_id=pid, recipe_key=(body.get("recipe_key") or "").strip())
    if PL._recipe_of(db, lt) is None:
        raise HTTPException(422, f"recipe '{lt.recipe_key}' is not in the project's current process")
    apply_lot(db, p, lt, body)
    db.add(lt)
    db.flush()
    start = body.get("start") or {}
    n = new_node(db, p, "lot", lt.id, {"label": lt.label or lt.recipe_key, "party": "ours",
                                       "mode": start.get("mode") or ("after" if start.get("after") else "fixed"),
                                       "day": start.get("day") or "", "after": start.get("after"),
                                       "lag": start.get("lag") or 0, "lag_unit": start.get("lag_unit") or "workdays",
                                       "source": start.get("source") or "", "source_text": start.get("source_text") or ""})
    lt.start_node_id = n.id
    db.flush()
    return lt


# ---------------------------------------------------------------- purchase orders


def add_po(db: Session, p: M.Plan | None, body: dict, actor: str) -> M.PurchaseOrder:
    po = M.PurchaseOrder(plan_id=p.id if p else None, company_id=(p.company_id if p else body.get("company_id")),
                         supplier_id=body.get("supplier_id"), supplier=(body.get("supplier") or "").strip(),
                         status="draft", reference=(body.get("reference") or "").strip(),
                         currency=(body.get("currency") or "PLN").upper()[:3], notes=body.get("notes") or "",
                         proposal_key=(body.get("proposal_key") or "")[:300], proposal=body.get("proposal"),
                         expected_on=_day(body.get("expected_on"), "expected_on"),
                         created_by=actor)
    if po.supplier_id:
        s = db.get(M.Supplier, po.supplier_id)
        if s is None:
            raise HTTPException(404, "supplier not found")
        po.supplier = po.supplier or s.name
    if not po.supplier:
        raise HTTPException(422, "a purchase order needs a supplier")
    db.add(po)
    db.flush()
    set_po_lines(po, body.get("lines") or [])
    if p is not None:
        order = body.get("order") or {}
        on = new_node(db, p, "po_order", po.id, {"label": f"Order from {po.supplier}", "party": "ours",
                                                 "mode": "fixed", "day": order.get("day") or date.today().isoformat(),
                                                 "source": order.get("source") or ""})
        arr = body.get("arrival") or {}
        an = new_node(db, p, "po_arrival", po.id,
                      {"label": f"{po.supplier} delivers", "party": "supplier",
                       "mode": "fixed" if arr.get("day") else "after", "day": arr.get("day") or "",
                       "after": None if arr.get("day") else [f"n:{on.id}"], "lag": arr.get("lag") or 0,
                       "lag_unit": arr.get("lag_unit") or "days", "source": arr.get("source") or "estimate",
                       "source_text": arr.get("source_text") or ""})
        po.order_node_id, po.arrival_node_id = on.id, an.id
    db.flush()
    return po


def set_po_lines(po: M.PurchaseOrder, rows: list[dict]) -> None:
    po.lines.clear()
    for i, r in enumerate(rows):
        if (r.get("qty") or 0) <= 0:
            raise HTTPException(422, "a purchase line needs a quantity")
        if not (r.get("component_id") or r.get("mpn") or r.get("lcsc")):
            raise HTTPException(422, "a purchase line names a component, an MPN or an LCSC number")
        po.lines.append(M.PurchaseOrderLine(component_id=r.get("component_id"), mpn=(r.get("mpn") or "").strip(),
                                            lcsc=(r.get("lcsc") or "").strip(), name=(r.get("name") or "").strip(),
                                            qty=float(r["qty"]), unit_price=r.get("unit_price"), position=i))


def set_po_status(db: Session, po: M.PurchaseOrder, status: str, day: str = "") -> None:
    if status not in ("draft", "ordered", "received", "cancelled"):
        raise HTTPException(422, "status is draft, ordered, received or cancelled")
    d = _day(day, "day") or date.today().isoformat()
    po.status = status
    if status == "ordered":
        po.ordered_on = d
        if po.order_node_id:
            n = db.get(M.PlanNode, po.order_node_id)
            if n is not None:
                n.done_on = po.ordered_on
    if status == "received":
        po.received_on = d
        if po.arrival_node_id:
            n = db.get(M.PlanNode, po.arrival_node_id)
            if n is not None:
                n.done_on = d
    db.flush()


def delete_po(db: Session, po: M.PurchaseOrder) -> None:
    if po.status not in ("draft", "cancelled"):
        raise HTTPException(409, f"the purchase order is {po.status}; only a draft or a cancelled one is deleted")
    for nid in (po.order_node_id, po.arrival_node_id):
        n = db.get(M.PlanNode, nid) if nid else None
        if n is not None:
            users = [u for u in node_users(db, n) if u]
            others = [u for u in users if not u.endswith("delivers")]
            if others:
                raise HTTPException(409, f"other dates follow this purchase ({', '.join(others[:3])})")
    for nid in (po.arrival_node_id, po.order_node_id):
        n = db.get(M.PlanNode, nid) if nid else None
        if n is not None:
            db.delete(n)
    db.delete(po)
    db.flush()


def accept_proposals(db: Session, p: M.Plan, keys: list[str], actor: str) -> list[M.PurchaseOrder]:
    """Turn computed proposals into draft purchase orders (decision 0107
    item 17). Proposals of one supplier and one order day share one order."""
    s = PL.schedule(db, p)
    wanted = [pr for pr in s["proposals"] if pr["key"] in set(keys) and not pr.get("covered_by_po_id")]
    if not wanted:
        raise HTTPException(409, "none of these proposals is open")
    groups: dict[tuple, list[dict]] = {}
    for pr in wanted:
        groups.setdefault((pr["supplier"] or "", pr["supplier_id"], pr["order_day"]), []).append(pr)
    out = []
    for (sup, sup_id, order_day), prs in groups.items():
        for pr in prs:
            lead = pr["lead_days"]
            po = add_po(db, p, {
                "supplier": sup or "(no supplier yet)", "supplier_id": sup_id, "currency": "PLN",
                "proposal_key": pr["key"], "proposal": {k: pr[k] for k in ("qty", "order_day", "arrival_day",
                                                                            "need_day", "lead_days", "supplier")},
                "lines": [{"component_id": pr["component_id"], "mpn": pr["mpn"], "lcsc": pr["lcsc"],
                           "name": pr["name"], "qty": pr["qty"], "unit_price": pr["unit_price_pln"]}],
                "order": {"day": order_day},
                "arrival": ({"lag": lead, "source": "estimate", "source_text": pr["lead_source"] or ""}
                            if lead is not None else {"day": pr["need_day"], "source": "estimate",
                                                      "source_text": "no lead time: set the date"}),
            }, actor)
            out.append(po)
    return out


# ---------------------------------------------------------------- reservations


def add_reservations(db: Session, p: M.Plan, rows: list[dict], actor: str) -> list[M.PlanReservation]:
    out = []
    for r in rows:
        qty = float(r.get("qty") or 0)
        line_id = r.get("source_line_id")
        cid, mpn, lcsc = r.get("component_id"), (r.get("mpn") or "").strip(), (r.get("lcsc") or "").strip()
        if line_id:
            li = db.get(M.RunCostLine, line_id)
            if li is None:
                raise HTTPException(404, f"purchase position {line_id} not found")
            cid = cid or li.component_id
            mpn = mpn or (li.mpn or "")
            lcsc = lcsc or (li.lcsc or "")
            if qty <= 0:
                qty = float(li.qty or 0)
        if qty <= 0:
            raise HTTPException(422, "a reservation needs a quantity")
        if not (cid or mpn or lcsc):
            raise HTTPException(422, "a reservation names a component, an MPN or an LCSC number")
        rv = M.PlanReservation(plan_id=p.id, company_id=p.company_id, component_id=cid, mpn=mpn, lcsc=lcsc, qty=qty,
                               source_line_id=line_id, note=(r.get("note") or "")[:500], created_by=actor)
        db.add(rv)
        out.append(rv)
    db.flush()
    return out


def reservable_lines(db: Session, doc_id: int) -> dict:
    """The part positions of a purchase document, for "reserve for a plan":
    what each bought, and how much of it plans have reserved already."""
    doc = db.get(M.RunCostDocument, doc_id)
    if doc is None:
        raise HTTPException(404, "document not found")
    lines = (db.query(M.RunCostLine).filter(M.RunCostLine.document_id == doc.id).order_by(M.RunCostLine.id).all())
    from . import run_actuals

    held = {}
    for rv in db.query(M.PlanReservation).filter(M.PlanReservation.source_line_id.in_([li.id for li in lines] or [-1])):
        held.setdefault(rv.source_line_id, []).append({"plan_id": rv.plan_id, "qty": rv.qty})
    rows = []
    for li in lines:
        if not run_actuals.is_stock(li) or not (li.component_id or li.mpn or li.lcsc) or not li.qty:
            continue
        rows.append({"id": li.id, "component_id": li.component_id, "mpn": li.mpn or "", "lcsc": li.lcsc or "",
                     "description": (li.description or "")[:200], "qty": li.qty, "reserved": held.get(li.id, [])})
    return {"document_id": doc.id, "supplier": doc.supplier, "external_id": doc.external_id, "lines": rows}


# ---------------------------------------------------------------- deleting a plan


def plan_owned(db: Session, p: M.Plan) -> dict:
    """What deleting a plan removes, and what it only lets go of (decision
    0107 item 19)."""
    orders = db.query(M.SalesOrder).filter(M.SalesOrder.plan_id == p.id).all()
    runs = db.query(M.ProductionRun).filter(M.ProductionRun.plan_id == p.id).all()
    pos = db.query(M.PurchaseOrder).filter(M.PurchaseOrder.plan_id == p.id).all()
    unit_runs = {r.id for r in runs if _has_units(db, r.id)}
    return {
        "delete": {
            "draft_orders": [{"id": o.id, "key": o.plan_key or o.order_ref} for o in orders if o.draft],
            "planned_batches": [{"id": r.id, "label": r.label} for r in runs
                                if r.status == "planned" and r.id not in unit_runs],
            "draft_purchase_orders": [{"id": po.id, "supplier": po.supplier} for po in pos
                                      if po.status in ("draft", "cancelled")],
            "reservations": db.query(M.PlanReservation).filter(M.PlanReservation.plan_id == p.id).count(),
            "lots": db.query(M.PlanLot).filter(M.PlanLot.plan_id == p.id).count(),
            "nodes": db.query(M.PlanNode).filter(M.PlanNode.plan_id == p.id).count(),
            "customer_parts": db.query(M.PlanCustomerPart).filter(M.PlanCustomerPart.plan_id == p.id).count(),
        },
        "keep": {
            "orders": [{"id": o.id, "key": o.plan_key or o.order_ref} for o in orders if not o.draft],
            "batches": [{"id": r.id, "label": r.label} for r in runs
                        if r.status != "planned" or r.id in unit_runs],
            "purchase_orders": [{"id": po.id, "supplier": po.supplier, "status": po.status} for po in pos
                                if po.status not in ("draft", "cancelled")],
        },
    }


def delete_plan(db: Session, p: M.Plan) -> dict:
    owned = plan_owned(db, p)
    # A kept order keeps its deliveries on the days the plan computed for them.
    computed = {}
    try:
        s = PL.schedule(db, p, with_parts=False)
        for o in s["orders"]:
            for li in o["lines"]:
                for d in li["deliveries"]:
                    if d["node_id"] and d["day"]:
                        computed[d["node_id"]] = d["day"]
    except Exception:
        computed = {}
    keep_orders = {x["id"] for x in owned["keep"]["orders"]}
    for o in db.query(M.SalesOrder).filter(M.SalesOrder.plan_id == p.id).all():
        if o.id in keep_orders:
            o.plan_id = None
            continue
        if db.query(M.DeviceEvent.id).filter(M.DeviceEvent.order_line_id.in_([li.id for li in o.lines] or [-1])).first():
            o.plan_id = None
            continue
        delete_order_plan_rows(db, o)
        db.delete(o)
    db.flush()
    for r in db.query(M.ProductionRun).filter(M.ProductionRun.plan_id == p.id).all():
        if any(x["id"] == r.id for x in owned["delete"]["planned_batches"]):
            delete_batch(db, r)
        else:
            r.plan_id = None
    for po in db.query(M.PurchaseOrder).filter(M.PurchaseOrder.plan_id == p.id).all():
        if po.status in ("draft", "cancelled"):
            db.delete(po)
        else:
            po.plan_id = None
            po.order_node_id = po.arrival_node_id = None
    for model in (M.PlanReservation, M.PlanLot, M.PlanCustomerPart):
        db.query(model).filter(model.plan_id == p.id).delete(synchronize_session=False)
    # Delivery nodes of kept orders stay with their deliveries; the plan's other nodes go.
    kept_delivery_nodes = {d.node_id for d in db.query(M.SalesOrderDelivery).all() if d.node_id}
    for n in db.query(M.PlanNode).filter(M.PlanNode.plan_id == p.id).all():
        if n.id in kept_delivery_nodes:
            n.plan_id = None
            n.mode = "fixed"
            n.day = computed.get(n.id) or n.day
            n.after = None
        else:
            db.delete(n)
    db.flush()
    db.delete(p)
    db.flush()
    return owned
