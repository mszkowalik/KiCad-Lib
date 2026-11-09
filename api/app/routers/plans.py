"""Plans of a contract and purchase orders (decision 0107).

Thin handlers: the dates and figures are computed in `services/planning.py`,
the writes live in `services/plans.py`. Every write answers the plan's new
schedule, so the page redraws from one call.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import companies as company_svc
from ..services import orders as order_svc
from ..services import planning as PL
from ..services import plans as svc
from .util import actor_of, audit

router = APIRouter(prefix="/api", tags=["plans"])


# ---------------------------------------------------------------- bodies


class NodeIn(BaseModel):
    kind: str = "milestone"
    label: str = Field(default="", max_length=300)
    mode: str = "fixed"
    day: str = Field(default="", max_length=10)
    after: list[str] | None = None
    lag: int = 0
    lag_unit: str = "days"
    snap_weekday: int | None = None
    end_day: str = Field(default="", max_length=10)
    duration_days: int | None = None
    source: str = ""
    source_text: str = Field(default="", max_length=300)
    party: str = "ours"
    done_on: str = Field(default="", max_length=10)
    amount: float | None = None
    currency: str = "PLN"
    position: int = 0


class NodePatch(BaseModel):
    label: str | None = Field(default=None, max_length=300)
    mode: str | None = None
    day: str | None = Field(default=None, max_length=10)
    after: list[str] | None = None
    lag: int | None = None
    lag_unit: str | None = None
    snap_weekday: int | None = None
    end_day: str | None = Field(default=None, max_length=10)
    duration_days: int | None = None
    source: str | None = None
    source_text: str | None = Field(default=None, max_length=300)
    party: str | None = None
    done_on: str | None = Field(default=None, max_length=10)
    amount: float | None = None
    currency: str | None = None
    position: int | None = None


class PlanIn(BaseModel):
    name: str = Field(max_length=200)
    customer_id: int | None = None
    company_id: int | None = None
    currency: str = "PLN"
    vat_pct: float = 23.0
    advance_pct: float = 60.0
    advance_days: int | None = None
    final_days: int = 14
    min_lead_months: int = 2
    advance_limit_net: float | None = None
    delivery_weekday: int | None = None
    build_lead_days: int = 7
    attrition_pct: float = 2.0
    notes: str = ""


class PlanPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    customer_id: int | None = None
    company_id: int | None = None
    status: str | None = None
    sent_on: str | None = Field(default=None, max_length=10)
    agreed_on: str | None = Field(default=None, max_length=10)
    currency: str | None = None
    vat_pct: float | None = None
    advance_pct: float | None = None
    advance_days: int | None = None
    final_days: int | None = None
    min_lead_months: int | None = None
    advance_limit_net: float | None = None
    delivery_weekday: int | None = None
    build_lead_days: int | None = None
    attrition_pct: float | None = None
    notes: str | None = None


class PlanProjectIn(BaseModel):
    project_id: int
    snapshot_mode: str = "fixed"
    snapshot_id: int | None = None
    branch: str = Field(default="", max_length=100)
    board: str = Field(default="", max_length=200)
    variant: str = Field(default="", max_length=100)
    line_rate_week: int | None = None


class ProjectsIn(BaseModel):
    projects: list[PlanProjectIn]


class DeliveryIn(BaseModel):
    qty: int
    day: str = Field(default="", max_length=10)
    mode: str = ""
    after: list[str] | None = None
    lag: int = 0
    lag_unit: str = "days"
    snap_weekday: int | None = None
    source: str | None = None
    source_text: str | None = Field(default=None, max_length=300)
    done_on: str | None = Field(default=None, max_length=10)


class PlanLineIn(BaseModel):
    project_id: int
    product: str = Field(default="", max_length=200)
    board: str = Field(default="", max_length=200)
    variant: str = Field(default="", max_length=100)
    qty_ordered: int
    unit_price: float = 0.0
    deliveries: list[DeliveryIn] = []


class PlanOrderIn(BaseModel):
    plan_key: str = Field(default="", max_length=40)
    order_ref: str = Field(default="", max_length=200)
    order_date: str = Field(max_length=10)
    advance_due: str = Field(default="", max_length=10)
    customer_id: int | None = None
    company_id: int | None = None
    currency: str = ""
    notes: str = ""
    lines: list[PlanLineIn] = []


class PlanOrderPatch(BaseModel):
    plan_key: str | None = Field(default=None, max_length=40)
    order_date: str | None = Field(default=None, max_length=10)
    advance_due: str | None = Field(default=None, max_length=10)
    notes: str | None = None


class DeliveriesIn(BaseModel):
    deliveries: list[DeliveryIn]


class StepIn(BaseModel):
    mode: str = ""
    day: str = Field(default="", max_length=10)
    after: list[str] | None = None
    lag: int | None = None
    lag_unit: str = "days"
    amount: float | None = None
    currency: str = "PLN"
    source: str = ""
    source_text: str = Field(default="", max_length=300)


class BatchIn(BaseModel):
    project_id: int
    label: str = Field(default="", max_length=200)
    qty: int
    notes: str = ""
    order: StepIn = StepIn()
    arrival: StepIn = StepIn()
    ack_review: bool = False


class OrderedIn(BaseModel):
    ordered_on: str = Field(default="", max_length=10)


class LotIn(BaseModel):
    project_id: int
    recipe_key: str = Field(max_length=80)
    label: str = Field(default="", max_length=200)
    qty: float
    rate_per_day: float | None = None
    duration_days: int | None = None
    start: StepIn = StepIn()


class LotPatch(BaseModel):
    label: str | None = Field(default=None, max_length=200)
    qty: float | None = None
    rate_per_day: float | None = None
    duration_days: int | None = None


class PoLineIn(BaseModel):
    component_id: int | None = None
    mpn: str = Field(default="", max_length=200)
    lcsc: str = Field(default="", max_length=50)
    name: str = Field(default="", max_length=300)
    qty: float
    unit_price: float | None = None


class PoIn(BaseModel):
    plan_id: int | None = None
    company_id: int | None = None
    supplier_id: int | None = None
    supplier: str = Field(default="", max_length=200)
    reference: str = Field(default="", max_length=200)
    currency: str = "PLN"
    notes: str = ""
    expected_on: str = Field(default="", max_length=10)
    lines: list[PoLineIn] = []
    order: StepIn = StepIn()
    arrival: StepIn = StepIn()


class PoPatch(BaseModel):
    supplier_id: int | None = None
    supplier: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(default=None, max_length=200)
    currency: str | None = None
    notes: str | None = None
    status: str | None = None
    status_day: str = Field(default="", max_length=10)
    expected_on: str | None = Field(default=None, max_length=10)
    document_id: int | None = None
    lines: list[PoLineIn] | None = None
    take_proposal: bool = False


class AcceptIn(BaseModel):
    keys: list[str]


class ReservationIn(BaseModel):
    component_id: int | None = None
    mpn: str = Field(default="", max_length=200)
    lcsc: str = Field(default="", max_length=50)
    qty: float = 0
    source_line_id: int | None = None
    note: str = Field(default="", max_length=500)


class ReservationsIn(BaseModel):
    reservations: list[ReservationIn]


class CustomerPartIn(BaseModel):
    project_id: int | None = None
    name: str = Field(max_length=200)
    per_unit: float = 1.0
    received: float = 0.0
    confirmed: bool = False
    note: str = Field(default="", max_length=500)


class CustomerPartPatch(BaseModel):
    name: str | None = Field(default=None, max_length=200)
    per_unit: float | None = None
    received: float | None = None
    confirmed: bool | None = None
    note: str | None = Field(default=None, max_length=500)


class DeleteIn(BaseModel):
    dry_run: bool = True


# ---------------------------------------------------------------- shapes


def _plan_json(db: Session, p: M.Plan) -> dict:
    cust = db.get(M.Customer, p.customer_id) if p.customer_id else None
    names = {x.id: x.name for x in db.query(M.Project).filter(
        M.Project.id.in_([pp.project_id for pp in p.projects] or [-1]))}
    return {
        "id": p.id, "name": p.name, "company_id": p.company_id, "customer_id": p.customer_id,
        "customer": cust.name if cust else "", "status": p.status, "sent_on": p.sent_on, "agreed_on": p.agreed_on,
        "currency": p.currency, "vat_pct": p.vat_pct, "advance_pct": p.advance_pct, "advance_days": p.advance_days,
        "final_days": p.final_days, "min_lead_months": p.min_lead_months, "advance_limit_net": p.advance_limit_net,
        "delivery_weekday": p.delivery_weekday, "build_lead_days": p.build_lead_days,
        "attrition_pct": p.attrition_pct, "notes": p.notes, "reviewed": p.reviewed or {},
        "created_at": p.created_at.isoformat() if p.created_at else None, "created_by": p.created_by,
        "projects": [{"id": pp.id, "project_id": pp.project_id, "project": names.get(pp.project_id, ""),
                      "snapshot_mode": pp.snapshot_mode, "snapshot_id": pp.snapshot_id, "branch": pp.branch,
                      "board": pp.board, "variant": pp.variant, "line_rate_week": pp.line_rate_week}
                     for pp in p.projects],
    }


def _node_json(n: M.PlanNode) -> dict:
    return {k: getattr(n, k) for k in ("id", "plan_id", "kind", "subject_id", "label", "mode", "day", "after", "lag",
                                         "lag_unit", "snap_weekday", "end_day", "duration_days", "source",
                                         "source_text", "party", "done_on", "amount", "currency", "position")}


def _full(db: Session, p: M.Plan) -> dict:
    nodes = db.query(M.PlanNode).filter(M.PlanNode.plan_id == p.id).order_by(M.PlanNode.position, M.PlanNode.id)
    lots = db.query(M.PlanLot).filter(M.PlanLot.plan_id == p.id).order_by(M.PlanLot.position, M.PlanLot.id)
    return {"plan": _plan_json(db, p), "nodes": [_node_json(n) for n in nodes],
            "lots": [{"id": x.id, "project_id": x.project_id, "recipe_key": x.recipe_key, "label": x.label,
                      "qty": x.qty, "rate_per_day": x.rate_per_day, "duration_days": x.duration_days,
                      "start_node_id": x.start_node_id} for x in lots],
            "schedule": PL.schedule(db, p)}


def _done(db: Session, p: M.Plan, action: str, details: dict | None, request: Request) -> dict:
    svc.sync_run_dates(db, p)
    audit(db, action, "plan", p.id, details, actor=actor_of(request))
    db.commit()
    db.expire_all()
    return _full(db, db.get(M.Plan, p.id))


def _node(db: Session, node_id: int) -> tuple[M.PlanNode, M.Plan]:
    n = db.get(M.PlanNode, node_id)
    if n is None or n.plan_id is None:
        raise HTTPException(404, "node not found")
    return n, svc.get_plan(db, n.plan_id)


def _po(db: Session, po_id: int) -> M.PurchaseOrder:
    po = db.get(M.PurchaseOrder, po_id)
    if po is None:
        raise HTTPException(404, "purchase order not found")
    return po


# ---------------------------------------------------------------- plans


@router.get("/plans", openapi_extra={"x-agent-tool": "list_plans"})
def list_plans(request: Request = None, db: Session = Depends(get_db)):
    """The plans in the caller's company scope, with each one's blocker counts."""
    scope = company_svc.scope_ids(db, request)
    rows = (db.query(M.Plan).filter(M.Plan.company_id.in_(scope) | M.Plan.company_id.is_(None))
            .order_by(M.Plan.id.desc()).all())
    att = {a["plan_id"]: a for a in PL.attention(db, rows)}
    out = []
    for p in rows:
        j = _plan_json(db, p)
        j["orders"] = db.query(M.SalesOrder).filter(M.SalesOrder.plan_id == p.id).count()
        j["attention"] = att.get(p.id)
        out.append(j)
    return out


@router.get("/plans/attention")
def plans_attention(request: Request = None, db: Session = Depends(get_db)):
    """Home's lines for the open plans: blockers, purchases to place this week,
    late advances, conflicts, shortages and broken reservations."""
    scope = company_svc.scope_ids(db, request)
    rows = (db.query(M.Plan).filter(M.Plan.company_id.in_(scope) | M.Plan.company_id.is_(None))
            .order_by(M.Plan.id).all())
    return PL.attention(db, rows)


@router.post("/plans")
def create_plan(body: PlanIn, request: Request, db: Session = Depends(get_db)):
    data = body.model_dump()
    if data.get("advance_days") is None:
        cust = db.get(M.Customer, body.customer_id) if body.customer_id else None
        data["advance_days"] = cust.payment_terms_days if cust else 14
    if not data.get("company_id"):
        mine = company_svc.visible_ids(db, getattr(request.state, "user", None))
        data["company_id"] = mine[0] if len(mine) == 1 else None
    p = M.Plan(name="x", created_by=actor_of(request) or "")
    svc.apply_plan(db, p, data)
    db.add(p)
    db.flush()
    return _done(db, p, "plan.create", {"name": p.name}, request)


@router.get("/plans/{plan_id}", openapi_extra={"x-agent-tool": "get_plan"})
def get_plan(plan_id: int, db: Session = Depends(get_db)):
    """One plan: its parameters, designs, nodes and the whole computed schedule
    (orders, deliveries, batches, parts, proposals, cash, checks, blockers)."""
    return _full(db, svc.get_plan(db, plan_id))


@router.patch("/plans/{plan_id}")
def update_plan(plan_id: int, body: PlanPatch, request: Request, db: Session = Depends(get_db)):
    p = svc.get_plan(db, plan_id)
    data = body.model_dump(exclude_unset=True)
    svc.apply_plan(db, p, data)
    return _done(db, p, "plan.update", data, request)


@router.put("/plans/{plan_id}/projects")
def set_plan_projects(plan_id: int, body: ProjectsIn, request: Request, db: Session = Depends(get_db)):
    p = svc.get_plan(db, plan_id)
    svc.set_projects(db, p, [x.model_dump() for x in body.projects])
    return _done(db, p, "plan.projects", {"projects": [x.project_id for x in body.projects]}, request)


@router.post("/plans/{plan_id}/reviewed")
def plan_reviewed(plan_id: int, request: Request, db: Session = Depends(get_db)):
    """A person read the design changes: record the inputs, and move the
    planned batches to them."""
    p = svc.get_plan(db, plan_id)
    res = svc.mark_reviewed(db, p)
    return _done(db, p, "plan.reviewed", res, request)


@router.post("/plans/{plan_id}/delete")
def delete_plan(plan_id: int, body: DeleteIn, request: Request, db: Session = Depends(get_db)):
    """Delete a plan and what it owns (decision 0107 item 19). `dry_run`
    (the default) answers the list of what goes and what stays."""
    p = svc.get_plan(db, plan_id)
    if body.dry_run:
        return {"dry_run": True, **svc.plan_owned(db, p)}
    owned = svc.delete_plan(db, p)
    audit(db, "plan.delete", "plan", plan_id, {"name": p.name, "deleted": owned["delete"]}, actor=actor_of(request))
    db.commit()
    return {"dry_run": False, **owned}


# ---------------------------------------------------------------- orders


@router.post("/plans/{plan_id}/orders")
def add_plan_order(plan_id: int, body: PlanOrderIn, request: Request, db: Session = Depends(get_db)):
    p = svc.get_plan(db, plan_id)
    o = svc.add_order(db, p, body.model_dump(), actor_of(request))
    return _done(db, p, "plan.order.add", {"order_id": o.id, "key": o.plan_key}, request)


@router.patch("/plans/{plan_id}/orders/{order_id}")
def update_plan_order(plan_id: int, order_id: int, body: PlanOrderPatch, request: Request,
                      db: Session = Depends(get_db)):
    p = svc.get_plan(db, plan_id)
    o = db.get(M.SalesOrder, order_id)
    if o is None or o.plan_id != p.id:
        raise HTTPException(404, "order not in this plan")
    data = body.model_dump(exclude_unset=True)
    if "order_date" in data:
        if not o.draft:
            raise HTTPException(409, "a confirmed order keeps its date: the customer placed it")
        o.order_date = svc._day(data["order_date"], "order_date") or o.order_date
    if "advance_due" in data:
        o.advance_due = svc._day(data["advance_due"], "advance_due")
    if "plan_key" in data:
        o.plan_key = (data["plan_key"] or "").strip()
    if "notes" in data:
        o.notes = data["notes"] or ""
    return _done(db, p, "plan.order.update", {"order_id": o.id, **data}, request)


@router.delete("/plans/{plan_id}/orders/{order_id}")
def delete_plan_order(plan_id: int, order_id: int, request: Request, db: Session = Depends(get_db)):
    """Remove a DRAFT order from the plan, with its deliveries."""
    p = svc.get_plan(db, plan_id)
    o = db.get(M.SalesOrder, order_id)
    if o is None or o.plan_id != p.id:
        raise HTTPException(404, "order not in this plan")
    if not o.draft:
        raise HTTPException(409, "only a draft order is deleted from a plan; a confirmed one is the customer's")
    refs = {f"order:{o.id}", f"advance:{o.id}"}
    own_nodes = {d.node_id for li in o.lines for d in db.query(M.SalesOrderDelivery)
                 .filter(M.SalesOrderDelivery.order_line_id == li.id)}
    users = [n.label or n.kind for n in db.query(M.PlanNode).filter(M.PlanNode.plan_id == p.id)
             if n.id not in own_nodes and refs & set(n.after or [])]
    if users:
        raise HTTPException(409, f"other dates follow this order ({', '.join(users[:3])}); change them first")
    svc.delete_order_plan_rows(db, o)
    db.delete(o)
    db.flush()
    return _done(db, p, "plan.order.delete", {"order_id": order_id}, request)


@router.put("/order-lines/{line_id}/deliveries")
def set_line_deliveries(line_id: int, body: DeliveriesIn, request: Request, db: Session = Depends(get_db)):
    """Replace one order line's delivery schedule (decision 0107 item 3)."""
    li = db.get(M.SalesOrderLine, line_id)
    if li is None:
        raise HTTPException(404, "order line not found")
    o = li.order
    if o.plan_id is None:
        raise HTTPException(409, "the order is in no plan; add it to a plan to schedule its deliveries")
    p = svc.get_plan(db, o.plan_id)
    svc.set_deliveries(db, p, o, li, [d.model_dump(exclude_unset=True) | {"qty": d.qty} for d in body.deliveries])
    return _done(db, p, "plan.deliveries", {"order_id": o.id, "line_id": li.id, "n": len(body.deliveries)}, request)


# ---------------------------------------------------------------- nodes


@router.post("/plans/{plan_id}/nodes")
def add_node(plan_id: int, body: NodeIn, request: Request, db: Session = Depends(get_db)):
    """A milestone or a closure, or any other date of the plan."""
    p = svc.get_plan(db, plan_id)
    if body.kind not in ("milestone", "closure"):
        raise HTTPException(422, "add a milestone or a closure here; the other dates come with their record")
    data = body.model_dump()
    kind = data.pop("kind")
    n = svc.new_node(db, p, kind, None, data)
    return _done(db, p, "plan.node.add", {"node_id": n.id, "label": n.label}, request)


@router.patch("/plan-nodes/{node_id}")
def update_node(node_id: int, body: NodePatch, request: Request, db: Session = Depends(get_db)):
    n, p = _node(db, node_id)
    data = body.model_dump(exclude_unset=True)
    svc.update_node(db, p, n, data)
    return _done(db, p, "plan.node.update", {"node_id": n.id, **{k: v for k, v in data.items() if k != "after"}},
                 request)


@router.delete("/plan-nodes/{node_id}")
def delete_node(node_id: int, request: Request, db: Session = Depends(get_db)):
    n, p = _node(db, node_id)
    if n.kind not in ("milestone", "closure"):
        raise HTTPException(409, "this date belongs to its record; delete the record instead")
    users = svc.node_users(db, n)
    if users:
        raise HTTPException(409, f"other dates follow it ({', '.join(users[:3])}); change them first")
    db.delete(n)
    db.flush()
    return _done(db, p, "plan.node.delete", {"node_id": node_id}, request)


# ---------------------------------------------------------------- batches


@router.post("/plans/{plan_id}/batches")
def add_plan_batch(plan_id: int, body: BatchIn, request: Request, db: Session = Depends(get_db)):
    """A planned batch. The design-review warning of a new batch is asked here
    too (409 `review_warning`, then again with `ack_review`)."""
    from .reviews import snapshot_review_issues

    p = svc.get_plan(db, plan_id)
    pp = next((x for x in p.projects if x.project_id == body.project_id), None)
    snap = PL.resolve_snapshot(db, pp) if pp else None
    if snap is not None:
        issues = snapshot_review_issues(db, snap)
        needs = (issues["unsigned"] or issues["not_verified"] or issues["deprecated"]
                 or issues["changed_since_review"] or not issues["reviewed"])
        problems = {"unsigned": issues["unsigned"], "not_verified": issues["not_verified"],
                    "partial": issues["partial"], "deprecated": issues["deprecated"],
                    "changed_since_review": issues["changed_since_review"], "review_completed": issues["reviewed"]}
        if needs and not body.ack_review:
            raise HTTPException(409, {"error": "the design has review warnings; confirm to plan a batch from it",
                                      "review_warning": True, **problems})
        if needs:
            audit(db, "production.review_ack", "project_snapshot", snap.id,
                  {"project_id": body.project_id, "label": body.label, "plan_id": p.id, **problems},
                  actor=actor_of(request))
    data = body.model_dump()
    data["order"] = {k: v for k, v in body.order.model_dump().items() if v not in (None, "")}
    data["arrival"] = {k: v for k, v in body.arrival.model_dump().items() if v not in (None, "")}
    r = svc.add_batch(db, p, data)
    return _done(db, p, "plan.batch.add", {"run_id": r.id, "qty": r.qty}, request)


@router.post("/plans/{plan_id}/batches/{run_id}/ordered")
def plan_batch_ordered(plan_id: int, run_id: int, body: OrderedIn, request: Request, db: Session = Depends(get_db)):
    """The planned batch was ordered: it leaves `planned` and its design is pinned."""
    p = svc.get_plan(db, plan_id)
    r = db.get(M.ProductionRun, run_id)
    if r is None or r.plan_id != p.id:
        raise HTTPException(404, "batch not in this plan")
    svc.order_batch(db, p, r, body.ordered_on)
    return _done(db, p, "plan.batch.ordered", {"run_id": r.id}, request)


@router.delete("/plans/{plan_id}/batches/{run_id}")
def delete_plan_batch(plan_id: int, run_id: int, request: Request, db: Session = Depends(get_db)):
    p = svc.get_plan(db, plan_id)
    r = db.get(M.ProductionRun, run_id)
    if r is None or r.plan_id != p.id:
        raise HTTPException(404, "batch not in this plan")
    svc.delete_batch(db, r)
    return _done(db, p, "plan.batch.delete", {"run_id": run_id}, request)


# ---------------------------------------------------------------- machining lots


@router.post("/plans/{plan_id}/lots")
def add_plan_lot(plan_id: int, body: LotIn, request: Request, db: Session = Depends(get_db)):
    p = svc.get_plan(db, plan_id)
    data = body.model_dump()
    data["start"] = {k: v for k, v in body.start.model_dump().items() if v not in (None, "")}
    lt = svc.add_lot(db, p, data)
    return _done(db, p, "plan.lot.add", {"lot_id": lt.id}, request)


@router.patch("/plan-lots/{lot_id}")
def update_plan_lot(lot_id: int, body: LotPatch, request: Request, db: Session = Depends(get_db)):
    lt = db.get(M.PlanLot, lot_id)
    if lt is None:
        raise HTTPException(404, "machining lot not found")
    p = svc.get_plan(db, lt.plan_id)
    data = body.model_dump(exclude_unset=True)
    svc.apply_lot(db, p, lt, data)
    return _done(db, p, "plan.lot.update", {"lot_id": lt.id, **data}, request)


@router.delete("/plan-lots/{lot_id}")
def delete_plan_lot(lot_id: int, request: Request, db: Session = Depends(get_db)):
    lt = db.get(M.PlanLot, lot_id)
    if lt is None:
        raise HTTPException(404, "machining lot not found")
    p = svc.get_plan(db, lt.plan_id)
    n = db.get(M.PlanNode, lt.start_node_id) if lt.start_node_id else None
    if n is not None:
        users = svc.node_users(db, n)
        if users:
            raise HTTPException(409, f"other dates follow this lot ({', '.join(users[:3])}); change them first")
        db.delete(n)
    db.delete(lt)
    db.flush()
    return _done(db, p, "plan.lot.delete", {"lot_id": lot_id}, request)


# ---------------------------------------------------------------- proposals, reservations, customer parts


@router.post("/plans/{plan_id}/proposals/accept")
def accept_proposals(plan_id: int, body: AcceptIn, request: Request, db: Session = Depends(get_db)):
    """Turn computed purchase proposals into draft purchase orders."""
    p = svc.get_plan(db, plan_id)
    pos = svc.accept_proposals(db, p, body.keys, actor_of(request))
    return _done(db, p, "plan.proposals.accept", {"purchase_orders": [x.id for x in pos]}, request)


@router.post("/plans/{plan_id}/reservations")
def add_reservations(plan_id: int, body: ReservationsIn, request: Request, db: Session = Depends(get_db)):
    """Reserve stock for the plan: by part, or by the purchase position it came from."""
    p = svc.get_plan(db, plan_id)
    rows = svc.add_reservations(db, p, [r.model_dump() for r in body.reservations], actor_of(request))
    return _done(db, p, "plan.reserve", {"reservations": [r.id for r in rows]}, request)


@router.delete("/plan-reservations/{res_id}")
def delete_reservation(res_id: int, request: Request, db: Session = Depends(get_db)):
    rv = db.get(M.PlanReservation, res_id)
    if rv is None:
        raise HTTPException(404, "reservation not found")
    p = svc.get_plan(db, rv.plan_id)
    db.delete(rv)
    db.flush()
    return _done(db, p, "plan.unreserve", {"reservation_id": res_id}, request)


@router.get("/run-documents/{doc_id}/reservable")
def reservable(doc_id: int, db: Session = Depends(get_db)):
    """A purchase document's part positions, and what plans reserved of each."""
    return svc.reservable_lines(db, doc_id)


@router.post("/plans/{plan_id}/customer-parts")
def add_customer_part(plan_id: int, body: CustomerPartIn, request: Request, db: Session = Depends(get_db)):
    p = svc.get_plan(db, plan_id)
    if not body.name.strip():
        raise HTTPException(422, "name the part")
    cp = M.PlanCustomerPart(plan_id=p.id, **body.model_dump())
    db.add(cp)
    db.flush()
    return _done(db, p, "plan.customer_part.add", {"id": cp.id, "name": cp.name}, request)


@router.patch("/plan-customer-parts/{cp_id}")
def update_customer_part(cp_id: int, body: CustomerPartPatch, request: Request, db: Session = Depends(get_db)):
    cp = db.get(M.PlanCustomerPart, cp_id)
    if cp is None:
        raise HTTPException(404, "customer part not found")
    p = svc.get_plan(db, cp.plan_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(cp, k, v)
    return _done(db, p, "plan.customer_part.update", {"id": cp.id, **data}, request)


@router.delete("/plan-customer-parts/{cp_id}")
def delete_customer_part(cp_id: int, request: Request, db: Session = Depends(get_db)):
    cp = db.get(M.PlanCustomerPart, cp_id)
    if cp is None:
        raise HTTPException(404, "customer part not found")
    p = svc.get_plan(db, cp.plan_id)
    db.delete(cp)
    db.flush()
    return _done(db, p, "plan.customer_part.delete", {"id": cp_id}, request)


# ---------------------------------------------------------------- purchase orders


def _po_json(db: Session, po: M.PurchaseOrder) -> dict:
    plan = db.get(M.Plan, po.plan_id) if po.plan_id else None
    order_day = arrival_day = ""
    if plan is not None:
        s = PL.schedule(db, plan, with_parts=False)
        row = next((x for x in s["purchase_orders"] if x["id"] == po.id), None)
        if row:
            order_day, arrival_day = row["order_day"], row["arrival_day"]
    return {"id": po.id, "plan_id": po.plan_id, "plan": plan.name if plan else "", "company_id": po.company_id,
            "supplier_id": po.supplier_id, "supplier": po.supplier, "status": po.status, "reference": po.reference,
            "currency": po.currency, "ordered_on": po.ordered_on, "expected_on": po.expected_on,
            "received_on": po.received_on, "order_day": order_day or po.ordered_on,
            "arrival_day": arrival_day or po.received_on or po.expected_on, "notes": po.notes,
            "document_id": po.document_id, "proposal_key": po.proposal_key, "proposal": po.proposal,
            "order_node_id": po.order_node_id, "arrival_node_id": po.arrival_node_id,
            "created_by": po.created_by, "created_at": po.created_at.isoformat() if po.created_at else None,
            "amount": round(sum((ln.qty or 0) * (ln.unit_price or 0) for ln in po.lines), 2),
            "lines": [{"id": ln.id, "component_id": ln.component_id, "mpn": ln.mpn, "lcsc": ln.lcsc, "name": ln.name,
                       "qty": ln.qty, "unit_price": ln.unit_price} for ln in po.lines]}


@router.get("/purchase-orders", openapi_extra={"x-agent-tool": "list_purchase_orders"})
def list_pos(request: Request = None, status: str = "", plan_id: int | None = None, db: Session = Depends(get_db)):
    """Purchase orders in the caller's company scope, newest first."""
    scope = company_svc.scope_ids(db, request)
    q = db.query(M.PurchaseOrder).filter(M.PurchaseOrder.company_id.in_(scope) | M.PurchaseOrder.company_id.is_(None))
    if status:
        q = q.filter(M.PurchaseOrder.status == status)
    if plan_id:
        q = q.filter(M.PurchaseOrder.plan_id == plan_id)
    plans = {p.id: p for p in db.query(M.Plan).all()}
    scheds = {}
    out = []
    for po in q.order_by(M.PurchaseOrder.id.desc()).all():
        j = {"id": po.id, "plan_id": po.plan_id, "plan": plans[po.plan_id].name if po.plan_id in plans else "",
             "supplier": po.supplier, "supplier_id": po.supplier_id, "status": po.status, "reference": po.reference,
             "currency": po.currency, "lines": len(po.lines),
             "amount": round(sum((ln.qty or 0) * (ln.unit_price or 0) for ln in po.lines), 2),
             "order_day": po.ordered_on, "arrival_day": po.received_on or po.expected_on,
             "names": ", ".join((ln.name or ln.mpn or ln.lcsc) for ln in po.lines[:3])}
        if po.plan_id in plans:
            if po.plan_id not in scheds:
                scheds[po.plan_id] = {x["id"]: x for x in
                                      PL.schedule(db, plans[po.plan_id], with_parts=False)["purchase_orders"]}
            row = scheds[po.plan_id].get(po.id)
            if row:
                j["order_day"], j["arrival_day"] = row["order_day"], row["arrival_day"]
        out.append(j)
    return out


@router.post("/purchase-orders")
def create_po(body: PoIn, request: Request, db: Session = Depends(get_db)):
    p = svc.get_plan(db, body.plan_id) if body.plan_id else None
    data = body.model_dump()
    data["order"] = {k: v for k, v in body.order.model_dump().items() if v not in (None, "")}
    data["arrival"] = {k: v for k, v in body.arrival.model_dump().items() if v not in (None, "")}
    if p is None and not data.get("company_id"):
        mine = company_svc.visible_ids(db, getattr(request.state, "user", None))
        data["company_id"] = mine[0] if len(mine) == 1 else None
    po = svc.add_po(db, p, data, actor_of(request))
    if p is not None:
        svc.sync_run_dates(db, p)
    audit(db, "po.create", "purchase_order", po.id, {"supplier": po.supplier, "plan_id": po.plan_id},
          actor=actor_of(request))
    db.commit()
    return _po_json(db, po)


@router.get("/purchase-orders/{po_id}", openapi_extra={"x-agent-tool": "get_purchase_order"})
def get_po(po_id: int, db: Session = Depends(get_db)):
    """One purchase order with its lines and, in a plan, its computed dates."""
    return _po_json(db, _po(db, po_id))


@router.patch("/purchase-orders/{po_id}")
def update_po(po_id: int, body: PoPatch, request: Request, db: Session = Depends(get_db)):
    po = _po(db, po_id)
    data = body.model_dump(exclude_unset=True)
    if body.take_proposal:
        if po.status != "draft" or not po.plan_id or not po.proposal_key:
            raise HTTPException(409, "only a plan's draft takes the plan's proposal")
        s = PL.schedule(db, svc.get_plan(db, po.plan_id))
        row = next((x for x in s["purchase_orders"] if x["id"] == po.id), None)
        if row is None or not row.get("out_of_date"):
            raise HTTPException(409, "the draft already matches the plan")
        q = float(row.get("suggested_qty") or 0)
        if q <= 0:
            raise HTTPException(409, "the plan no longer needs this purchase: delete the draft")
        if po.lines:
            po.lines[0].qty = q
        po.proposal = {**(po.proposal or {}), "qty": q}
    for k in ("supplier", "reference", "notes"):
        if k in data and data[k] is not None:
            setattr(po, k, data[k].strip() if k != "notes" else data[k])
    if data.get("currency"):
        po.currency = data["currency"].upper()[:3]
    if "supplier_id" in data:
        if data["supplier_id"] and db.get(M.Supplier, data["supplier_id"]) is None:
            raise HTTPException(404, "supplier not found")
        po.supplier_id = data["supplier_id"]
    if "expected_on" in data:
        po.expected_on = svc._day(data["expected_on"], "expected_on")
    if "document_id" in data:
        if data["document_id"] and db.get(M.RunCostDocument, data["document_id"]) is None:
            raise HTTPException(404, "document not found")
        po.document_id = data["document_id"]
    if body.lines is not None:
        if po.status not in ("draft",):
            raise HTTPException(409, "only a draft's lines change; an ordered purchase is the supplier's")
        svc.set_po_lines(po, [ln.model_dump() for ln in body.lines])
    if body.status:
        svc.set_po_status(db, po, body.status, body.status_day)
    db.flush()
    p = db.get(M.Plan, po.plan_id) if po.plan_id else None
    if p is not None:
        svc.sync_run_dates(db, p)
    audit(db, "po.update", "purchase_order", po.id, {k: v for k, v in data.items() if k != "lines"},
          actor=actor_of(request))
    db.commit()
    return _po_json(db, po)


@router.delete("/purchase-orders/{po_id}")
def delete_po(po_id: int, request: Request, db: Session = Depends(get_db)):
    po = _po(db, po_id)
    plan_id = po.plan_id
    svc.delete_po(db, po)
    audit(db, "po.delete", "purchase_order", po_id, {"plan_id": plan_id}, actor=actor_of(request))
    db.commit()
    return {"deleted": po_id}


# ---------------------------------------------------------------- an order's plan view


@router.get("/orders/{order_id}/deliveries")
def order_deliveries(order_id: int, db: Session = Depends(get_db)):
    """An order's planned deliveries with their computed dates, and the plan
    flags of the order (for the order page)."""
    o = db.get(M.SalesOrder, order_id)
    if o is None:
        raise HTTPException(404, "order not found")
    if o.plan_id is None:
        return {"plan_id": None, "order": None}
    p = svc.get_plan(db, o.plan_id)
    s = PL.schedule(db, p, with_parts=False)
    row = next((x for x in s["orders"] if x["id"] == o.id), None)
    shipped = {li.id: order_svc.line_shipped(li) for li in o.lines}
    return {"plan_id": p.id, "plan": p.name, "order": row, "shipped": shipped}
