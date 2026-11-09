"""A contract's plan, computed on read (decision 0107).

A plan owns drafts of real records: draft sales orders (`sales_orders.draft`),
planned batches (`production_runs.status == "planned"`), draft purchase orders,
machining lots, reservations, and the date nodes that place them in time. This
module reads them and computes everything the plan page shows: the dates, the
invoices that do not exist yet, the deliveries per week, the balance of every
part, the purchase proposals, the cash, the checks and the blockers.

Nothing here writes. A proposal is never stored (decision 0107 item 16), and a
figure the server can compute is never typed.

The rules are in docs/reference/planning.md.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy.orm import Session

from .. import models as M

# ---------------------------------------------------------------- calendar


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (the anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return date(year, month, day + 1)


_HOLIDAYS: dict[int, frozenset[date]] = {}


def holidays(year: int) -> frozenset[date]:
    """Polish public holidays (Dz.U. 1951 nr 4 poz. 28 as amended). 24 December
    is a holiday from 2025 (Dz.U. 2024 poz. 1965)."""
    if year not in _HOLIDAYS:
        e = _easter(year)
        days = {date(year, 1, 1), date(year, 1, 6), e, e + timedelta(days=1), date(year, 5, 1),
                date(year, 5, 3), e + timedelta(days=49), e + timedelta(days=60), date(year, 8, 15),
                date(year, 11, 1), date(year, 11, 11), date(year, 12, 25), date(year, 12, 26)}
        if year >= 2025:
            days.add(date(year, 12, 24))
        _HOLIDAYS[year] = frozenset(days)
    return _HOLIDAYS[year]


def is_workday(d: date) -> bool:
    return d.weekday() < 5 and d not in holidays(d.year)


def add_workdays(d: date, n: int) -> date:
    """`n` working days after `d` (0 = `d` itself, moved to a working day)."""
    while not is_workday(d):
        d += timedelta(days=1)
    while n > 0:
        d += timedelta(days=1)
        if is_workday(d):
            n -= 1
    return d


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    last = (date(y + (m // 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def add_lag(d: date, lag: int, unit: str) -> date:
    if unit == "workdays":
        return add_workdays(d, lag) if lag >= 0 else d - timedelta(days=-lag)
    if unit == "weeks":
        return d + timedelta(weeks=lag)
    if unit == "months":
        return add_months(d, lag)
    return d + timedelta(days=lag)


def snap(d: date, weekday: int | None) -> date:
    if weekday is None:
        return d
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def workdays_between(a: date, b: date) -> int:
    """Working days in [a, b]."""
    n, d = 0, a
    while d <= b:
        if is_workday(d):
            n += 1
        d += timedelta(days=1)
    return n


def parse_day(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def iso(d: date | None) -> str:
    return d.isoformat() if d else ""


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ---------------------------------------------------------------- nodes

NODE_KINDS = ("delivery", "batch_order", "batch_arrival", "po_order", "po_arrival", "lot", "milestone", "closure")
MODES = ("fixed", "after")
LAG_UNITS = ("days", "workdays", "weeks", "months")
PARTIES = ("ours", "customer", "supplier")
SOURCES = ("", "estimate", "measured", "confirmed")


class CycleError(ValueError):
    pass


@dataclass
class NodeDay:
    day: date | None
    planned: date | None = None      # before today's push, when it moved
    late_days: int = 0               # an open node of ours (or a supplier's) whose date passed
    done: bool = False
    conflict: str = ""               # a fixed node earlier than what it must follow
    unresolved: str = ""             # a reference that names nothing


class Dates:
    """The forward pass over one plan's nodes (decision 0107 item 5).

    `order:<id>` is an order's date, `advance:<id>` its advance: the day it was
    paid, else the day it falls due — today when that has passed unpaid, so a
    late payment moves what follows it. A node of ours or a supplier's that is
    still open and dated before today counts from today (item 6). A customer
    date in the past is not moved: the plan reports it."""

    def __init__(self, today: date, nodes: dict[int, M.PlanNode], order_day: dict[int, date | None],
                 advance_day: dict[int, date | None]):
        self.today = today
        self.nodes = nodes
        self.order_day = order_day
        self.advance_day = advance_day
        self.memo: dict[int, NodeDay] = {}
        self._stack: set[int] = set()

    def ref(self, ref: str) -> date | None:
        kind, _, ident = str(ref).partition(":")
        try:
            n = int(ident)
        except ValueError:
            return None
        if kind == "n":
            return self.node(n).day if n in self.nodes else None
        if kind == "order":
            return self.order_day.get(n)
        if kind == "advance":
            return self.advance_day.get(n)
        return None

    def node(self, node_id: int) -> NodeDay:
        if node_id in self.memo:
            return self.memo[node_id]
        if node_id in self._stack:
            raise CycleError(f"node {node_id} depends on itself")
        self._stack.add(node_id)
        try:
            out = self._compute(self.nodes[node_id])
        finally:
            self._stack.discard(node_id)
        self.memo[node_id] = out
        return out

    def _compute(self, n: M.PlanNode) -> NodeDay:
        if n.done_on:
            return NodeDay(parse_day(n.done_on), done=True)
        refs = list(n.after or [])
        bases, missing = [], []
        for r in refs:
            d = self.ref(r)
            (bases if d else missing).append(d or r)
        base = max(bases) if bases else None
        earliest = None
        if base is not None:
            earliest = snap(add_lag(base, n.lag or 0, n.lag_unit or "days"), n.snap_weekday)
        out = NodeDay(None, unresolved=", ".join(str(m) for m in missing))
        if n.mode == "fixed":
            out.day = parse_day(n.day)
            if out.day and earliest and out.day < earliest:
                out.conflict = f"fixed on {iso(out.day)}, but what it follows allows {iso(earliest)} at the earliest"
        else:
            out.day = earliest if earliest else parse_day(n.day)
        if out.day and out.day < self.today and n.party in ("ours", "supplier") and n.kind != "closure":
            out.planned, out.late_days, out.day = out.day, (self.today - out.day).days, self.today
        return out


# ---------------------------------------------------------------- loading


@dataclass
class Loaded:
    plan: M.Plan
    orders: list[M.SalesOrder]
    deliveries: dict[int, list[M.SalesOrderDelivery]]      # order line id ->
    nodes: dict[int, M.PlanNode]
    runs: list[M.ProductionRun]
    pos: list[M.PurchaseOrder]
    lots: list[M.PlanLot]
    reservations: list[M.PlanReservation]
    customer_parts: list[M.PlanCustomerPart]
    projects: dict[int, M.Project] = field(default_factory=dict)


def load(db: Session, plan: M.Plan) -> Loaded:
    orders = (db.query(M.SalesOrder).filter(M.SalesOrder.plan_id == plan.id)
              .order_by(M.SalesOrder.order_date, M.SalesOrder.id).all())
    line_ids = [li.id for o in orders for li in o.lines]
    dels: dict[int, list[M.SalesOrderDelivery]] = defaultdict(list)
    if line_ids:
        for d in (db.query(M.SalesOrderDelivery).filter(M.SalesOrderDelivery.order_line_id.in_(line_ids))
                  .order_by(M.SalesOrderDelivery.position, M.SalesOrderDelivery.id)):
            dels[d.order_line_id].append(d)
    nodes = {n.id: n for n in db.query(M.PlanNode).filter(M.PlanNode.plan_id == plan.id)}
    # A delivery node of the plan's orders always belongs to the plan, but a
    # node a delivery names is read even if its plan_id was left empty.
    want = {d.node_id for ds in dels.values() for d in ds if d.node_id and d.node_id not in nodes}
    if want:
        for n in db.query(M.PlanNode).filter(M.PlanNode.id.in_(want)):
            nodes[n.id] = n
    runs = (db.query(M.ProductionRun).filter(M.ProductionRun.plan_id == plan.id)
            .order_by(M.ProductionRun.id).all())
    pos = (db.query(M.PurchaseOrder).filter(M.PurchaseOrder.plan_id == plan.id)
           .order_by(M.PurchaseOrder.id).all())
    lots = db.query(M.PlanLot).filter(M.PlanLot.plan_id == plan.id).order_by(M.PlanLot.position, M.PlanLot.id).all()
    res = db.query(M.PlanReservation).filter(M.PlanReservation.plan_id == plan.id).order_by(M.PlanReservation.id).all()
    cps = (db.query(M.PlanCustomerPart).filter(M.PlanCustomerPart.plan_id == plan.id)
           .order_by(M.PlanCustomerPart.id).all())
    pids = {li.project_id for o in orders for li in o.lines} | {r.project_id for r in runs} | \
        {pp.project_id for pp in plan.projects} | {lt.project_id for lt in lots}
    projects = {p.id: p for p in db.query(M.Project).filter(M.Project.id.in_(pids))} if pids else {}
    return Loaded(plan, orders, dels, nodes, runs, pos, lots, res, cps, projects)


def nodes_by_subject(nodes: dict[int, M.PlanNode]) -> dict[tuple[str, int], M.PlanNode]:
    return {(n.kind, n.subject_id): n for n in nodes.values() if n.subject_id is not None}


# ---------------------------------------------------------------- money


def _r2(x: float) -> float:
    return round(x + 0.0, 2)


def _invoices_of(db: Session, order_ids: list[int]) -> dict[int, dict]:
    """The real invoices of each order, by kind: the advance (paid on, due on,
    net) and the final. Both registers count: the platform's own sales
    invoices (decision 0066) and the older order invoices (decision 0003)."""
    out: dict[int, dict] = defaultdict(lambda: {"advance": [], "final": []})
    if not order_ids:
        return out
    for si in (db.query(M.SalesInvoice).filter(M.SalesInvoice.order_id.in_(order_ids),
                                               M.SalesInvoice.status.in_(("issued", "error")))):
        kind = "advance" if si.kind == "advance" else ("final" if si.kind in ("vat", "settlement") else "")
        if kind:
            out[si.order_id][kind].append({"number": si.number, "issue_date": si.issue_date, "due_date": si.due_date,
                                           "paid": bool(si.paid), "paid_date": si.paid_date or "",
                                           "net": float(si.net_total or 0), "gross": float(si.gross_total or 0),
                                           "sales_invoice_id": si.id})
    for oi in db.query(M.OrderInvoice).filter(M.OrderInvoice.order_id.in_(order_ids)):
        kind = "advance" if oi.kind == "advance" else ("final" if oi.kind == "final" else "")
        if kind and not any(x["number"] == oi.number and oi.number for x in out[oi.order_id][kind]):
            out[oi.order_id][kind].append({"number": oi.number, "issue_date": oi.issue_date, "due_date": oi.due_date,
                                           "paid": bool(oi.paid_at), "paid_date": oi.paid_at or "",
                                           "net": float(oi.net_amount or 0), "gross": None,
                                           "order_invoice_id": oi.id})
    return out


def _pln_rate(db: Session) -> dict[str, float]:
    from . import fx

    rates = fx.get_rates(db)
    return rates


def to_pln(amount: float, currency: str, rates: dict[str, float]) -> float | None:
    from . import fx

    if not currency or currency.upper() == "PLN":
        return amount
    v, ok = fx.convert(amount, currency.upper(), "PLN", rates)
    return v if ok else None


# ---------------------------------------------------------------- designs


def resolve_snapshot(db: Session, pp: M.PlanProject) -> M.ProjectSnapshot | None:
    """The snapshot a plan builds a project from (decision 0107 item 10)."""
    if pp.snapshot_mode == "branch":
        q = (db.query(M.ProjectSnapshot)
             .filter(M.ProjectSnapshot.project_id == pp.project_id, M.ProjectSnapshot.status == "ready",
                     M.ProjectSnapshot.ref_name == (pp.branch or "main"), M.ProjectSnapshot.is_tag.is_(False))
             .order_by(M.ProjectSnapshot.committed_at.desc().nullslast(), M.ProjectSnapshot.id.desc()))
        return q.first()
    return db.get(M.ProjectSnapshot, pp.snapshot_id) if pp.snapshot_id else None


def board_of(snap: M.ProjectSnapshot | None, pp: M.PlanProject) -> str:
    if pp.board:
        return pp.board
    for b in (snap.boards or []) if snap else []:
        if (b.get("kind") or "board") == "board":
            return b.get("name") or ""
    return ""


def _part_key(component_id: int | None, mpn: str, lcsc: str) -> str:
    if component_id:
        return f"c{component_id}"
    if mpn:
        return f"m{mpn.strip().upper()}"
    return f"l{(lcsc or '').strip().upper()}"


@dataclass
class Design:
    project_id: int
    snapshot: M.ProjectSnapshot | None
    board: str
    variant: str
    version: M.ProcessVersion | None
    graph: dict
    bom: list[dict]           # per board: {key, component_id, mpn, lcsc, name, qty, refs}
    step_inputs: list[dict]   # per unit: {key, component_id, mpn, name, qty, step, prepared}
    recipes: dict[str, dict]  # recipe key -> recipe (with output_component_id, inputs, rate_per_day)
    warnings: list[str]


def design_of(db: Session, pp: M.PlanProject) -> Design:
    from . import process as P
    from . import project_bom

    snap = resolve_snapshot(db, pp)
    board = board_of(snap, pp)
    v = P.current_version(db, pp.project_id)
    graph = P._graph(v)
    warnings: list[str] = []
    bom: list[dict] = []
    if snap is None:
        warnings.append("no snapshot: " + ("no ready snapshot on branch " + (pp.branch or "main")
                                           if pp.snapshot_mode == "branch" else "none chosen"))
    else:
        lines = (db.query(M.SnapshotBomLine)
                 .filter_by(snapshot_id=snap.id, board=board, variant=pp.variant or "")
                 .order_by(M.SnapshotBomLine.position).all())
        virtual = project_bom.virtual_component_ids(db, {li.component_id for li in lines if li.component_id})
        active = [li for li in lines if not (li.dnp or li.exclude_from_bom or li.component_id in virtual)]
        owned = P.bom_lines_owned(graph, active)["by_line"] if v else {}
        for li in active:
            if li.id in owned or li.exclude_from_board:
                continue
            bom.append({"key": _part_key(li.component_id, li.mpn, li.lcsc), "component_id": li.component_id,
                        "mpn": li.mpn or "", "lcsc": li.lcsc or "", "name": li.value or li.mpn or li.refs,
                        "qty": float(li.qty or 0), "refs": li.refs})
    recipes = {r.get("key"): r for r in (graph.get("prepared") or []) if r.get("key")}
    prepared_out = {int(r["output_component_id"]) for r in recipes.values() if r.get("output_component_id")}
    steps = P.step_map(graph)
    inputs: list[dict] = []
    for key in graph.get("route") or []:
        st = steps.get(key)
        if not st:
            continue
        for inp in st.get("inputs") or []:
            cid, mpn = P.input_ref(inp)
            inputs.append({"key": _part_key(cid, mpn, ""), "component_id": cid, "mpn": mpn or "",
                           "lcsc": "", "qty": float(inp.get("qty") or 0), "step": st.get("label") or key,
                           "prepared": bool(cid and cid in prepared_out)})
    return Design(pp.project_id, snap, board, pp.variant or "", v, graph, bom, inputs, recipes, warnings)


# ---------------------------------------------------------------- the schedule


def schedule(db: Session, plan: M.Plan, today: date | None = None, *, with_parts: bool = True) -> dict:
    """Everything the plan page shows, computed now."""
    today = today or date.today()
    L = load(db, plan)
    by_subject = nodes_by_subject(L.nodes)
    vat = 1 + (plan.vat_pct or 0) / 100.0
    pct = (plan.advance_pct or 0) / 100.0

    # --- orders: dates and money
    inv = _invoices_of(db, [o.id for o in L.orders])
    order_day: dict[int, date | None] = {}
    advance_day: dict[int, date | None] = {}
    adv_info: dict[int, dict] = {}
    for o in L.orders:
        od = parse_day(o.order_date)
        order_day[o.id] = od
        due = parse_day(o.advance_due) or (od + timedelta(days=plan.advance_days or 0) if od else None)
        real = inv[o.id]["advance"]
        paid = [parse_day(x["paid_date"]) for x in real if x["paid"] and x["paid_date"]]
        real_due = [parse_day(x["due_date"]) for x in real if x["due_date"]]
        due = min(real_due) if real_due else due
        if paid:
            eff, state = min(paid), "paid"
        elif due and due < today and not o.draft:
            eff, state = today, "late"
        else:
            eff, state = due, "due"
        advance_day[o.id] = eff
        adv_info[o.id] = {"due": due, "paid_on": min(paid) if paid else None, "state": state, "real": real}
    D = Dates(today, L.nodes, order_day, advance_day)
    try:
        for nid in L.nodes:
            D.node(nid)
        cycle = ""
    except CycleError as e:
        cycle = str(e)

    def nd(node_id: int | None) -> NodeDay:
        if not node_id or node_id not in L.nodes:
            return NodeDay(None)
        try:
            return D.node(node_id)
        except CycleError:
            return NodeDay(None, unresolved="cycle")

    projects = {p.id: p.name for p in L.projects.values()}
    orders_out = []
    deliveries_by_project: dict[int, list[tuple[date, int, str]]] = defaultdict(list)
    week_rows: dict[date, dict] = {}
    for o in L.orders:
        lines = []
        dels_all = []
        net = 0.0
        for li in o.lines:
            net += (li.qty_ordered or 0) * (li.unit_price or 0)
            dl = []
            for dv in L.deliveries.get(li.id, []):
                x = nd(dv.node_id)
                node = L.nodes.get(dv.node_id) if dv.node_id else None
                dl.append({"id": dv.id, "qty": dv.qty, "node_id": dv.node_id, "day": iso(x.day),
                           "planned": iso(x.planned), "late_days": x.late_days, "conflict": x.conflict,
                           "mode": node.mode if node else "", "done": x.done})
                if x.day:
                    dels_all.append(x.day)
                    deliveries_by_project[li.project_id].append((x.day, dv.qty, o.plan_key or o.order_ref or f"#{o.id}"))
                    w = week_rows.setdefault(x.day, {"day": iso(x.day), "by_project": defaultdict(int), "orders": []})
                    w["by_project"][li.project_id] += dv.qty
                    w["orders"].append({"order_id": o.id, "key": o.plan_key or o.order_ref, "qty": dv.qty,
                                        "project_id": li.project_id})
            planned = sum(d["qty"] for d in dl)
            lines.append({"id": li.id, "project_id": li.project_id, "project": projects.get(li.project_id, ""),
                          "product": li.product, "qty": li.qty_ordered, "unit_price": li.unit_price,
                          "deliveries": dl, "planned_qty": planned,
                          "mismatch": planned != (li.qty_ordered or 0) and bool(dl)})
        first = min(dels_all) if dels_all else None
        last = max(dels_all) if dels_all else None
        adv_net = _r2(net * pct)
        fin_net = _r2(net - adv_net)
        a = adv_info[o.id]
        real_fin = inv[o.id]["final"]
        fin_day = last
        fin_due = last + timedelta(days=plan.final_days or 0) if last else None
        if real_fin:
            fin_day = parse_day(real_fin[0]["issue_date"]) or fin_day
            fin_due = parse_day(real_fin[0]["due_date"]) or fin_due
        od = order_day[o.id]
        flags = []
        if o.draft and od and od < today:
            flags.append({"code": "order_past", "text": "The order date has passed and the customer has not ordered."})
        earliest = add_months(a["due"], plan.min_lead_months or 0) if a["due"] else None
        if first and earliest and first < earliest:
            flags.append({"code": "two_month", "text": f"The first delivery is before {iso(earliest)}, "
                                                         f"the advance due date plus {plan.min_lead_months} months."})
        if first and last and (first.year, first.month) != (last.year, last.month):
            flags.append({"code": "one_month", "text": "The deliveries fall in two months, so the final invoice "
                                                       "misses the VAT deadline."})
        if a["state"] == "late":
            flags.append({"code": "advance_late", "text": f"The advance was due on {iso(a['due'])} and is not paid."})
        if any(li["mismatch"] for li in lines):
            flags.append({"code": "qty", "text": "The planned deliveries do not add up to the ordered quantity."})
        orders_out.append({
            "id": o.id, "key": o.plan_key or o.order_ref or f"#{o.id}", "order_ref": o.order_ref, "draft": o.draft,
            "status": o.status, "order_date": iso(od), "advance_due": iso(a["due"]),
            "advance_due_override": o.advance_due, "advance_paid_on": iso(a["paid_on"]),
            "advance_state": a["state"], "advance_effective": iso(advance_day[o.id]),
            "earliest_delivery": iso(earliest),
            "net": _r2(net), "advance_net": adv_net, "advance_gross": _r2(adv_net * vat),
            "final_net": fin_net, "final_gross": _r2(fin_net * vat), "final_day": iso(fin_day),
            "final_due": iso(fin_due), "first_delivery": iso(first), "last_delivery": iso(last),
            "real_invoices": {"advance": a["real"], "final": real_fin},
            "lines": lines, "flags": flags,
        })

    # --- the advance limit per due date
    adv_by_day: dict[date, dict] = {}
    for o in orders_out:
        d = parse_day(o["advance_due"])
        if d:
            e = adv_by_day.setdefault(d, {"day": iso(d), "net": 0.0, "orders": []})
            e["net"] = _r2(e["net"] + o["advance_net"])
            e["orders"].append(o["key"])
    advances = [adv_by_day[k] for k in sorted(adv_by_day)]
    over_limit = [a for a in advances if plan.advance_limit_net and a["net"] > plan.advance_limit_net + 0.005]

    # --- weekly deliveries
    weeks = []
    for d in sorted(week_rows):
        w = week_rows[d]
        weeks.append({"day": w["day"], "by_project": {str(k): v for k, v in w["by_project"].items()},
                      "total": sum(w["by_project"].values()), "orders": w["orders"]})

    # --- batches
    closures = [n for n in L.nodes.values() if n.kind == "closure"]
    batches = []
    for r in L.runs:
        on = by_subject.get(("batch_order", r.id))
        an = by_subject.get(("batch_arrival", r.id))
        o_d, a_d = nd(on.id if on else None), nd(an.id if an else None)
        clash = []
        for c in closures:
            c0, c1 = parse_day(c.day), parse_day(c.end_day) or parse_day(c.day)
            if c0 and o_d.day and a_d.day and o_d.day <= c1 and c0 <= a_d.day:
                clash.append(c.label or "closure")
        batches.append({"id": r.id, "label": r.label, "project_id": r.project_id,
                        "project": projects.get(r.project_id, ""), "qty": r.qty or 0, "status": r.status,
                        "planned": (r.status or "") == "planned",
                        "order_node_id": on.id if on else None, "arrival_node_id": an.id if an else None,
                        "order_day": iso(o_d.day), "arrival_day": iso(a_d.day),
                        "order_late_days": o_d.late_days, "arrival_late_days": a_d.late_days,
                        "order_planned": iso(o_d.planned), "conflict": o_d.conflict or a_d.conflict,
                        "closures": clash,
                        "cost": (on.amount if on else None), "cost_currency": (on.currency if on else "PLN")})

    # --- boards against builds, per project
    lead = timedelta(days=plan.build_lead_days or 0)
    coverage = []
    for pid, dl in deliveries_by_project.items():
        dl.sort()
        arrivals = sorted((parse_day(b["arrival_day"]), b["qty"], b["label"]) for b in batches
                          if b["project_id"] == pid and b["arrival_day"])
        cum, short = 0, []
        for day, qty, key in dl:
            cum += qty
            need_day = day - lead
            have = sum(q for a_, q, _ in arrivals if a_ and a_ <= need_day)
            if have < cum:
                short.append({"delivery": iso(day), "need_day": iso(need_day), "need": cum, "have": have,
                              "short": min(qty, cum - have), "order": key})
        rate = next((pp.line_rate_week for pp in plan.projects if pp.project_id == pid), None)
        by_week: dict[date, int] = defaultdict(int)
        for day, qty, _ in dl:
            by_week[week_start(day - lead)] += qty
        over = [{"week": iso(w), "units": n} for w, n in sorted(by_week.items()) if rate and n > rate]
        coverage.append({"project_id": pid, "project": projects.get(pid, ""), "short": short,
                         "line_rate_week": rate, "over_rate": over,
                         "units": sum(q for _, q, _ in dl)})

    # --- purchase orders
    rates = _pln_rate(db)
    pos_out = []
    for po in L.pos:
        o_d, a_d = nd(po.order_node_id), nd(po.arrival_node_id)
        order_on = o_d.day or parse_day(po.ordered_on)
        arrive_on = parse_day(po.received_on) if po.status == "received" else (a_d.day or parse_day(po.expected_on))
        amount = sum((ln.qty or 0) * (ln.unit_price or 0) for ln in po.lines)
        pos_out.append({"id": po.id, "supplier": po.supplier, "supplier_id": po.supplier_id, "status": po.status,
                        "reference": po.reference, "currency": po.currency,
                        "order_node_id": po.order_node_id, "arrival_node_id": po.arrival_node_id,
                        "order_day": iso(order_on), "arrival_day": iso(arrive_on),
                        "order_late_days": o_d.late_days if po.status == "draft" else 0,
                        "arrival_late_days": a_d.late_days if po.status in ("draft", "ordered") else 0,
                        "amount": _r2(amount), "amount_pln": _r2(to_pln(amount, po.currency, rates) or 0),
                        "proposal_key": po.proposal_key, "proposal": po.proposal,
                        "lines": [{"id": ln.id, "component_id": ln.component_id, "mpn": ln.mpn, "lcsc": ln.lcsc,
                                   "name": ln.name, "qty": ln.qty, "unit_price": ln.unit_price,
                                   "key": _part_key(ln.component_id, ln.mpn, ln.lcsc)} for ln in po.lines]})

    # --- machining lots and milestones
    designs: dict[int, Design] = {}
    if with_parts:
        for pp in plan.projects:
            designs[pp.project_id] = design_of(db, pp)
    lots_out = []
    for lt in L.lots:
        s = nd(lt.start_node_id)
        dsg = designs.get(lt.project_id)
        if dsg is None and with_parts is False:
            dsg = None
        recipe = (dsg.recipes.get(lt.recipe_key) if dsg else None) or _recipe_of(db, lt)
        rate = lt.rate_per_day or (float(recipe.get("rate_per_day") or 0) if recipe else 0) or None
        days = lt.duration_days or (math.ceil((lt.qty or 0) / rate) if rate else None)
        end = add_workdays(s.day, max(days - 1, 0)) if (s.day and days) else None
        lots_out.append({"id": lt.id, "project_id": lt.project_id, "recipe_key": lt.recipe_key,
                         "label": lt.label or (recipe or {}).get("label") or lt.recipe_key, "qty": lt.qty,
                         "rate_per_day": rate, "workdays": days, "start_node_id": lt.start_node_id,
                         "start_day": iso(s.day), "end_day": iso(end), "late_days": s.late_days,
                         "output_component_id": int(recipe["output_component_id"])
                         if recipe and recipe.get("output_component_id") else None,
                         "inputs": [{"component_id": i.get("component_id"), "mpn": i.get("mpn") or "",
                                     "qty": float(i.get("qty") or 0)} for i in (recipe or {}).get("inputs") or []],
                         "unknown_recipe": recipe is None})
    milestones = []
    for n in sorted((n for n in L.nodes.values() if n.kind in ("milestone", "closure")),
                    key=lambda n: (n.position, n.id)):
        x = nd(n.id)
        end = None
        if n.kind == "closure":
            end = parse_day(n.end_day) or x.day
        elif x.day and n.duration_days:
            end = x.day + timedelta(days=n.duration_days)
        milestones.append({"id": n.id, "kind": n.kind, "label": n.label, "day": iso(x.day), "end_day": iso(end),
                           "planned": iso(x.planned), "late_days": x.late_days, "done": x.done,
                           "conflict": x.conflict, "party": n.party, "source": n.source,
                           "source_text": n.source_text})

    # --- parts
    parts = _parts(db, L, plan, designs, batches, lots_out, pos_out, deliveries_by_project, today) \
        if with_parts else {"parts": [], "proposals": [], "reservations": [], "inputs": []}

    # --- cash
    cash = _cash(plan, orders_out, pos_out, batches, L.nodes, nd, rates, today)

    # --- customer-supplied parts
    customer_parts = []
    for cp in L.customer_parts:
        dl = sorted(x for pid, xs in deliveries_by_project.items()
                    if cp.project_id is None or pid == cp.project_id for x in xs)
        cum, rows = 0.0, []
        for day, qty, _ in dl:
            cum += qty * (cp.per_unit or 0)
            rows.append({"need_day": iso(day - lead), "cumulative": cum})
        first_short = next((r for r in rows if r["cumulative"] > (cp.received or 0)), None)
        customer_parts.append({"id": cp.id, "name": cp.name, "project_id": cp.project_id, "per_unit": cp.per_unit,
                               "received": cp.received, "confirmed": cp.confirmed, "note": cp.note,
                               "needs": rows, "next_need": first_short})

    # --- inputs since the last review
    changes = _input_changes(db, plan, designs) if with_parts else []

    # --- progress: shipped and built against the plan, by today
    progress = _progress(db, L, deliveries_by_project, today)

    out = {
        "today": iso(today), "cycle": cycle,
        "orders": orders_out, "advances": advances, "over_limit": over_limit, "weeks": weeks,
        "batches": batches, "coverage": coverage, "purchase_orders": pos_out, "lots": lots_out,
        "milestones": milestones, "parts": parts["parts"], "proposals": parts["proposals"],
        "reservations": parts["reservations"], "cash": cash, "customer_parts": customer_parts,
        "changes": changes, "progress": progress,
        "designs": [{"project_id": d.project_id, "project": projects.get(d.project_id, ""),
                     "snapshot_id": d.snapshot.id if d.snapshot else None,
                     "snapshot_ref": d.snapshot.ref_name if d.snapshot else "",
                     "snapshot_sha": (d.snapshot.sha or "")[:10] if d.snapshot else "",
                     "board": d.board, "variant": d.variant,
                     "process_version_id": d.version.id if d.version else None,
                     "process_version_no": d.version.version_no if d.version else None,
                     "bom_lines": len(d.bom), "step_inputs": len(d.step_inputs),
                     "recipes": [{"key": k, "label": r.get("label") or k, "rate_per_day": r.get("rate_per_day"),
                                  "output_component_id": r.get("output_component_id")}
                                 for k, r in d.recipes.items()],
                     "warnings": d.warnings} for d in designs.values()],
    }
    out["checks"] = _checks(plan, out)
    out["blockers"] = _blockers(plan, out, today)
    out["agenda"] = _agenda(plan, out, today)
    return out


def _recipe_of(db: Session, lt: M.PlanLot) -> dict | None:
    from . import process as P

    v = P.current_version(db, lt.project_id)
    for r in (P._graph(v).get("prepared") or []):
        if r.get("key") == lt.recipe_key:
            return r
    return None


# ---------------------------------------------------------------- parts


def _pool(db: Session, company_id: int | None, today: date) -> dict:
    from . import run_actuals

    return run_actuals.pool_state(db, as_of=iso(today), company_id=run_actuals.stock_scope(db, company_id))


def _keys_of(component_id, mpn, lcsc) -> set[str]:
    from . import run_actuals

    return set(run_actuals._identity_keys(component_id, mpn or "", lcsc or ""))


def _in_work_needs(db: Session, plan_run_ids: set[int], pool: dict) -> dict[str, float]:
    """What the batches in work that are NOT this plan's still take from stock
    through their steps: still to do times per unit, by input key. Other demand
    sees the free remainder only, and these batches are other demand."""
    from . import twins

    out: dict[str, float] = defaultdict(float)
    runs = (db.query(M.ProductionRun)
            .filter(M.ProductionRun.process_version_id.isnot(None),
                    M.ProductionRun.status.notin_(tuple(twins.BATCH_OVER) + ("planned",))).all())
    for r in runs:
        if r.id in plan_run_ids or r.closed_at:
            continue
        try:
            rows = twins.board(db, r, pool=pool)
        except Exception:
            import logging

            logging.getLogger(__name__).warning("plan: the board of batch %s could not be read", r.id, exc_info=True)
            continue
        for st in rows:
            for inp in st.get("inputs") or []:
                out[inp["key"]] += max(float(st.get("still_to_do") or 0), 0.0) * float(inp.get("per_unit") or 0)
    return out


def _parts(db: Session, L: Loaded, plan: M.Plan, designs: dict[int, Design], batches: list[dict],
           lots: list[dict], pos: list[dict], deliveries_by_project: dict, today: date) -> dict:
    """The balance of every part the plan needs (decision 0107 item 14), the
    reservations, and the purchase proposals (item 16)."""
    att = 1 + (plan.attrition_pct or 0) / 100.0
    lead = timedelta(days=plan.build_lead_days or 0)
    pool = _pool(db, plan.company_id, today)
    # identity -> pool entry
    pool_by_key: dict[str, dict] = {}
    for p in pool.values():
        for k in _keys_of(p.get("component_id"), p.get("mpn"), p.get("lcsc")):
            pool_by_key.setdefault(k, p)

    parts: dict[str, dict] = {}

    def part(cid, mpn, lcsc, name) -> dict:
        key = _part_key(cid, mpn, lcsc)
        p = parts.get(key)
        if p is None:
            p = parts[key] = {"key": key, "component_id": cid, "mpn": mpn or "", "lcsc": lcsc or "", "name": name,
                              "needs": [], "supplies": [], "reserved": 0.0, "free": 0.0, "on_hand": 0.0,
                              "other_reserved": 0.0, "in_work_other": 0.0, "prepared": False}
        else:
            p["lcsc"] = p["lcsc"] or (lcsc or "")
            p["mpn"] = p["mpn"] or (mpn or "")
            if not p["name"] and name:
                p["name"] = name
        return p

    # needs: board BOMs of the planned batches, at the batch order date
    for b in batches:
        if not b["planned"]:
            continue
        dsg = designs.get(b["project_id"])
        day = parse_day(b["order_day"])
        if not dsg or not day:
            continue
        for li in dsg.bom:
            p = part(li["component_id"], li["mpn"], li["lcsc"], li["name"])
            p["needs"].append({"day": day, "qty": li["qty"] * b["qty"] * att, "why": f"{b['label']} (BOM {li['refs']})",
                               "jlc": True})
    # needs: step inputs of every unit the plan delivers, on its build day
    for pid, dl in deliveries_by_project.items():
        dsg = designs.get(pid)
        if not dsg:
            continue
        for day, qty, key in dl:
            for inp in dsg.step_inputs:
                p = part(inp["component_id"], inp["mpn"], "", "")
                p["prepared"] = p["prepared"] or inp["prepared"]
                p["needs"].append({"day": day - lead, "qty": inp["qty"] * qty * att,
                                   "why": f"{key}: {inp['step']}", "jlc": False})
    # machining lots: output of the prepared part, input of its recipe
    for lt in lots:
        start, end = parse_day(lt["start_day"]), parse_day(lt["end_day"])
        if not start or not lt["output_component_id"]:
            continue
        out = part(lt["output_component_id"], "", "", "")
        out["prepared"] = True
        rate = lt["rate_per_day"] or ((lt["qty"] or 0) / max(lt["workdays"] or 1, 1))
        left, d = float(lt["qty"] or 0), start
        while left > 0 and end and d <= end:
            if is_workday(d):
                q = min(rate, left)
                out["supplies"].append({"day": d, "qty": q, "tier": "lot", "why": lt["label"], "lot_id": lt["id"]})
                left -= q
            d += timedelta(days=1)
        for i in lt["inputs"]:
            p = part(i["component_id"], i["mpn"], "", "")
            p["needs"].append({"day": start, "qty": i["qty"] * (lt["qty"] or 0), "why": lt["label"], "jlc": False})
    # supplies: the plan's purchase orders that are not received
    for po in pos:
        if po["status"] not in ("draft", "ordered"):
            continue
        day = parse_day(po["arrival_day"])
        for ln in po["lines"]:
            p = part(ln["component_id"], ln["mpn"], ln["lcsc"], ln["name"])
            p["supplies"].append({"day": day, "qty": float(ln["qty"] or 0), "tier": f"po_{po['status']}",
                                  "why": f"{po['supplier']} {po['reference'] or '#' + str(po['id'])}",
                                  "po_id": po["id"], "unknown_day": day is None})

    # stock: reserved for this plan, reserved for others, free
    plan_runs = {r.id for r in L.runs}
    all_res = db.query(M.PlanReservation).all()
    drawn = _plan_draws(db, plan_runs)
    reservations_out = []
    res_by_key: dict[str, float] = defaultdict(float)
    other_by_key: dict[str, float] = defaultdict(float)
    for rv in all_res:
        k = _part_key(rv.component_id, rv.mpn, rv.lcsc)
        if rv.plan_id == plan.id:
            used = sum(q for kk, q in drawn.items() if kk in _keys_of(rv.component_id, rv.mpn, rv.lcsc))
            left = max(float(rv.qty or 0) - used, 0.0)
            res_by_key[k] += left
            reservations_out.append({"id": rv.id, "key": k, "component_id": rv.component_id, "mpn": rv.mpn,
                                     "lcsc": rv.lcsc, "qty": rv.qty, "remaining": left,
                                     "source_line_id": rv.source_line_id, "note": rv.note,
                                     "created_by": rv.created_by, "created_at": iso(rv.created_at.date())
                                     if rv.created_at else ""})
        else:
            other_by_key[k] += float(rv.qty or 0)
    in_work = _in_work_needs(db, plan_runs, pool)
    for k, q in res_by_key.items():
        if k not in parts:
            rv = next(r for r in reservations_out if r["key"] == k)
            part(rv["component_id"], rv["mpn"], rv["lcsc"], "")
    supply_rows = {}
    for p in parts.values():
        keys = _keys_of(p["component_id"], p["mpn"], p["lcsc"])
        ent = next((pool_by_key[k] for k in keys if k in pool_by_key), None)
        on_hand = max(float(ent.get("qty") or 0), 0.0) if ent else 0.0
        reserved = sum(q for k, q in res_by_key.items() if k in keys or k == p["key"])
        other = sum(q for k, q in other_by_key.items() if k in keys or k == p["key"])
        work = sum(q for k, q in in_work.items() if k in keys)
        p.update(on_hand=on_hand, reserved=min(reserved, on_hand), other_reserved=other, in_work_other=work,
                 reserved_broken=max(reserved - on_hand, 0.0),
                 free=max(on_hand - reserved - other - work, 0.0),
                 avg_usd=float(ent.get("avg_usd") or 0) if ent else None)
        supply_rows[p["key"]] = p
    # JLC public stock
    cids = [p["component_id"] for p in parts.values() if p["component_id"]]
    public = {s.component_id: s.jlc_stock for s in db.query(M.ComponentSupply)
              .filter(M.ComponentSupply.component_id.in_(cids))} if cids else {}
    names = {c.id: c for c in db.query(M.Component).filter(M.Component.id.in_(cids))} if cids else {}
    sources = _sources(db, cids)

    rates = _pln_rate(db)
    usd_pln = to_pln(1.0, "USD", rates) or None
    measured = jlc_measured_leads(db)
    jlc = db.query(M.Supplier).filter(M.Supplier.name == "JLCPCB").first()
    out_parts, proposals = [], []
    for p in parts.values():
        comp = names.get(p["component_id"]) if p["component_id"] else None
        if comp is not None:
            p["name"] = p["name"] or comp.name
            p["internal"] = bool(getattr(comp, "internal", False))
        p["name"] = p["name"] or p["mpn"] or p["lcsc"] or p["key"]
        start = p["reserved"] + p["free"]
        events = [(n["day"], -n["qty"], "need", n) for n in p["needs"] if n["day"]]
        events += [(s["day"], s["qty"], "supply", s) for s in p["supplies"] if s["day"]]
        events.sort(key=lambda e: (e[0], 0 if e[2] == "supply" else 1))
        bal, low, first_short, short_qty, first_need = start, start, None, 0.0, None
        points = [{"day": iso(today), "balance": round(bal, 3)}]
        need_total = sum(n["qty"] for n in p["needs"])
        jlc_need = sum(n["qty"] for n in p["needs"] if n.get("jlc"))
        for day, q, kind, ev in events:
            bal += q
            if kind == "need" and first_need is None:
                first_need = day
            if bal < -1e-6 and first_short is None:
                first_short = day
            low = min(low, bal)
            points.append({"day": iso(day), "balance": round(bal, 3)})
        short_qty = max(-low, 0.0)
        pub = public.get(p["component_id"]) if p["component_id"] else None
        status = "ok"
        if short_qty > 1e-6:
            status = "short"
            if jlc_need >= short_qty - 1e-6 and pub is not None and pub >= short_qty:
                status = "public"   # JLC's public stock covers it at the batch order — not reserved
        unknown_days = [s for s in p["supplies"] if s.get("unknown_day")]
        row = {"key": p["key"], "component_id": p["component_id"], "mpn": p["mpn"], "lcsc": p["lcsc"],
               "name": p["name"], "prepared": p["prepared"], "internal": p.get("internal", False),
               "need": round(need_total, 3), "on_hand": round(p["on_hand"], 3), "reserved": round(p["reserved"], 3),
               "reserved_broken": round(p.get("reserved_broken", 0.0), 3),
               "other_reserved": round(p["other_reserved"], 3), "in_work_other": round(p["in_work_other"], 3),
               "free": round(p["free"], 3), "jlc_public": pub,
               "incoming": round(sum(s["qty"] for s in p["supplies"] if s["tier"].startswith("po_")), 3),
               "from_lots": round(sum(s["qty"] for s in p["supplies"] if s["tier"] == "lot"), 3),
               "status": status, "first_need": iso(first_need), "first_short": iso(first_short),
               "short": round(short_qty, 3), "end_balance": round(bal, 3),
               "points": _thin(points), "unknown_arrivals": len(unknown_days),
               "needs": [{"day": iso(n["day"]), "qty": round(n["qty"], 3), "why": n["why"]} for n in
                         sorted(p["needs"], key=lambda n: n["day"])][:200],
               "supplies": [{"day": iso(s["day"]), "qty": round(s["qty"], 3), "tier": s["tier"], "why": s["why"]}
                            for s in sorted(p["supplies"], key=lambda s: s["day"] or date.max)][:200]}
        out_parts.append(row)
        srcs = list(sources.get(p["component_id"]) or [])
        lc = (p["lcsc"] or "").strip().upper()
        if lc and lc in measured:
            m = measured[lc]
            row["jlc_measured"] = m
            typed = next((x for x in srcs if x["supplier"] == "JLCPCB"), None)
            # JLC's public stock decides which past receipt predicts the next one:
            # a part JLC holds arrives as fast as the fastest receipt; a part it
            # must buy in (a presale lot) as slowly as the slowest.
            in_stock = pub is not None and pub >= short_qty
            lead = m["min"] if in_stock else m["max"]
            text = (f"measured from {m['n']} JLC receipts: {m['min']} to {m['max']} days; "
                    + (f"JLC holds {pub:,}, so the fastest" if in_stock else
                       f"JLC holds {pub or 0:,} of {short_qty:,.0f}, so the slowest ({m['max_code']})"))
            if typed is None:
                srcs.append({"supplier_id": jlc.id if jlc else None, "supplier": "JLCPCB", "link_id": None,
                             "part_number": lc, "lead_days": lead, "qty_at_once": None,
                             "lead_source": text, "lead_as_of": m["last_on"]})
            elif typed.get("lead_days") is None:
                typed.update(lead_days=lead, lead_source=text, lead_as_of=m["last_on"])
        if status == "short" and not p["prepared"]:
            proposals.extend(_propose(plan, row, p, srcs, first_short, today, usd_pln))
    out_parts.sort(key=lambda r: (0 if r["status"] == "short" else 1 if r["status"] == "public" else 2,
                                  r["first_short"] or "9999", r["name"]))
    # a draft purchase order compared with what the plan needs now (item 17).
    # The draft already counts as supply, so a proposal left for its part is
    # what is still MISSING beside it, and an end balance above the free stock
    # is what it brings too much of.
    end_by_key = {r["key"]: r for r in out_parts}
    for po in pos:
        if po["status"] != "draft" or not po["proposal_key"] or not po["lines"]:
            continue
        ln = po["lines"][0]
        r = end_by_key.get(ln["key"])
        more = sum(pr["qty"] for pr in proposals if pr["part_key"] == ln["key"])
        extra = max((r["end_balance"] - r["free"]) if r else 0.0, 0.0)
        qty = float(ln["qty"] or 0)
        if r is None:
            po["out_of_date"], po["suggested_qty"] = "The plan no longer needs this part.", 0.0
        elif more > 1e-6:
            po["out_of_date"] = f"The plan needs {more:g} more of this part (this draft: {qty:g})."
            po["suggested_qty"] = round(qty + more, 3)
            for pr in proposals:
                if pr["part_key"] == ln["key"]:
                    pr["covered_by_po_id"] = po["id"]
        elif extra > 1e-6:
            po["out_of_date"] = f"The plan needs {min(extra, qty):g} fewer of this part (this draft: {qty:g})."
            po["suggested_qty"] = round(max(qty - extra, 0.0), 3)
        else:
            po["out_of_date"], po["suggested_qty"] = "", qty
    # an ordered purchase the plan no longer needs (item 17)
    for po in pos:
        if po["status"] != "ordered":
            continue
        surplus = []
        for ln in po["lines"]:
            r = end_by_key.get(ln["key"])
            if r and r["end_balance"] - r["free"] > 1e-6:
                q = min(float(ln["qty"] or 0), r["end_balance"] - r["free"])
                surplus.append({"key": ln["key"], "name": ln["name"] or r["name"], "qty": round(q, 3),
                                "value": _r2(q * (ln["unit_price"] or 0))})
        po["surplus"] = surplus
    return {"parts": out_parts, "proposals": proposals, "reservations": reservations_out}


def _thin(points: list[dict]) -> list[dict]:
    """One point per day, the last balance of the day."""
    by: dict[str, float] = {}
    for p in points:
        by[p["day"]] = p["balance"]
    return [{"day": d, "balance": b} for d, b in sorted(by.items())]


def _plan_draws(db: Session, run_ids: set[int]) -> dict[str, float]:
    """What the plan's batches drew, by identity key."""
    if not run_ids:
        return {}
    out: dict[str, float] = defaultdict(float)
    for dr in db.query(M.Draw).filter(M.Draw.run_id.in_(run_ids)):
        for k in _keys_of(dr.component_id, dr.mpn or "", dr.lcsc or ""):
            out[k] += float(dr.taken or 0)
    return out


def _sources(db: Session, component_ids: list[int]) -> dict[int, list[dict]]:
    """A part's supply sources (decision 0107 item 15), in the part's own order."""
    if not component_ids:
        return {}
    rows = (db.query(M.ComponentSupplier, M.Supplier)
            .join(M.Supplier, M.Supplier.id == M.ComponentSupplier.supplier_id)
            .filter(M.ComponentSupplier.component_id.in_(component_ids)).all())
    out: dict[int, list[dict]] = defaultdict(list)
    for link, sup in sorted(rows, key=lambda r: (r[0].position if r[0].position is not None else 999,
                                                 r[1].position or 0)):
        out[link.component_id].append({"supplier_id": sup.id, "supplier": sup.name, "link_id": link.id,
                                       "part_number": link.part_number, "lead_days": link.lead_days,
                                       "qty_at_once": link.qty_at_once, "lead_source": link.lead_source,
                                       "lead_as_of": link.lead_as_of})
    return out


_ORDER_DAY = __import__("re").compile(r"^[A-Z]+?0?(20\d{2})(\d{2})(\d{2})")


def jlc_measured_leads(db: Session) -> dict[str, dict]:
    """How long JLCPCB took to put each part into the private inventory, by
    LCSC number (decision 0107 item 15). A parts order's number carries its
    order day (`COB20261105…`, `POB020241009…`), and JLC's own ledger dates the
    receipt (`jlc_stock_changes`, business type 5). The last receipt is the
    figure; the median and the count say how steady it is."""
    rows = (db.query(M.JlcStockChange.lcsc, M.JlcStockChange.business_code, M.JlcStockChange.changed_at)
            .filter(M.JlcStockChange.business_type == 5, M.JlcStockChange.change_qty > 0,
                    M.JlcStockChange.change_status != 3).all())
    by: dict[str, list[tuple[date, int, str]]] = defaultdict(list)
    for lcsc, code, at in rows:
        m = _ORDER_DAY.match(code or "")
        if not (lcsc and m and at):
            continue
        try:
            ordered = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        got = at.date()
        if got >= ordered:
            by[lcsc.strip().upper()].append((got, (got - ordered).days, code))
    out = {}
    for lcsc, xs in by.items():
        xs.sort()
        leads = sorted(x[1] for x in xs)
        last = xs[-1]
        out[lcsc] = {"last": last[1], "last_code": last[2], "last_on": iso(last[0]),
                     "median": leads[len(leads) // 2], "n": len(leads), "min": leads[0], "max": leads[-1],
                     "max_code": max(xs, key=lambda x: x[1])[2]}
    return out


def _propose(plan: M.Plan, row: dict, p: dict, sources: list[dict], first_short: date | None, today: date,
             usd_pln: float | None) -> list[dict]:
    """Proposals for one short part: first the sources that can send at once,
    then the first source with a lead time for the rest (decision 0107
    item 16). A part with no source with a lead time gets one proposal that
    says so."""
    need_day = first_short or today
    left = row["short"]
    out = []
    unit_pln = (p.get("avg_usd") or 0) * usd_pln if (p.get("avg_usd") and usd_pln) else None

    def add(src: dict | None, qty: float, lead: int | None):
        order_day = max(today, need_day - timedelta(days=lead)) if lead is not None else today
        arrival = order_day + timedelta(days=lead) if lead is not None else None
        sup = src["supplier"] if src else ""
        out.append({"key": f"{plan.id}:{sup or '-'}:{row['key']}", "part_key": row["key"],
                    "component_id": row["component_id"], "mpn": row["mpn"], "lcsc": row["lcsc"],
                    "name": row["name"], "supplier": sup, "supplier_id": src["supplier_id"] if src else None,
                    "qty": round(qty, 3), "order_day": iso(order_day), "arrival_day": iso(arrival),
                    "need_day": iso(need_day), "lead_days": lead,
                    "lead_source": (src or {}).get("lead_source") or "",
                    "late": bool(arrival and arrival > need_day),
                    "no_lead": lead is None,
                    "unit_price_pln": round(unit_pln, 4) if unit_pln else None,
                    "amount_pln": _r2(unit_pln * qty) if unit_pln else None})

    for src in sources:
        if left <= 1e-6:
            break
        if src.get("qty_at_once"):
            q = min(left, float(src["qty_at_once"]))
            add(src, q, src.get("lead_days") or 0)
            left -= q
    if left > 1e-6:
        timed = next((s for s in sources if s.get("lead_days") is not None and not s.get("qty_at_once")), None) \
            or next((s for s in sources if s.get("lead_days") is not None), None)
        add(timed, left, timed.get("lead_days") if timed else None)
    return out


# ---------------------------------------------------------------- cash


def _cash(plan: M.Plan, orders: list[dict], pos: list[dict], batches: list[dict], nodes: dict[int, M.PlanNode],
          nd, rates: dict, today: date) -> dict:
    """The funding rule (decision 0107 item 20): purchases, added up over
    time, stay within the advances received. Advances count on the day they
    were paid, else on the day they fall due."""
    inflows = []
    for o in orders:
        d = parse_day(o["advance_paid_on"]) or parse_day(o["advance_due"])
        if d:
            inflows.append({"day": d, "net": o["advance_net"], "key": o["key"], "paid": bool(o["advance_paid_on"])})
    outflows = []
    for po in pos:
        if po["status"] == "cancelled":
            continue
        d = parse_day(po["order_day"])
        if d and po["amount_pln"]:
            outflows.append({"day": d, "net": po["amount_pln"], "label": f"{po['supplier']} "
                             f"{po['reference'] or '#' + str(po['id'])}", "kind": "purchase"})
    for n in nodes.values():
        if n.amount and n.kind not in ("po_order", "po_arrival"):
            x = nd(n.id)
            v = to_pln(n.amount, n.currency or "PLN", rates)
            if x.day and v:
                label = n.label or n.kind
                if n.kind == "batch_order":
                    b = next((b for b in batches if b["order_node_id"] == n.id), None)
                    label = f"Batch {b['label']}" if b else label
                outflows.append({"day": x.day, "net": _r2(v), "label": label, "kind": n.kind})
    inflows.sort(key=lambda x: x["day"])
    outflows.sort(key=lambda x: x["day"])
    steps, cum_out = [], 0.0
    by_day: dict[date, float] = defaultdict(float)
    for o in outflows:
        by_day[o["day"]] += o["net"]
    for d in sorted(by_day):
        cum_out += by_day[d]
        cum_in = sum(i["net"] for i in inflows if i["day"] <= d)
        steps.append({"day": iso(d), "out": _r2(by_day[d]), "cum_out": _r2(cum_out), "cum_in": _r2(cum_in),
                      "margin": _r2(cum_in - cum_out)})
    low = min(steps, key=lambda s: s["margin"]) if steps else None
    vat = 1 + (plan.vat_pct or 0) / 100.0
    months: dict[str, dict] = {}
    for o in orders:
        for day, gross, part in ((o["advance_due"], o["advance_gross"], "advance"),
                                 (o["final_due"], o["final_gross"], "final")):
            if not day:
                continue
            m = day[:7]
            e = months.setdefault(m, {"month": m, "by_project": defaultdict(float), "advance": 0.0, "final": 0.0})
            e[part] = _r2(e[part] + gross)
            # per project, by the line value share
            tot = sum((li["qty"] or 0) * (li["unit_price"] or 0) for li in o["lines"]) or 1.0
            for li in o["lines"]:
                e["by_project"][str(li["project_id"])] = _r2(
                    e["by_project"][str(li["project_id"])] + gross * (li["qty"] or 0) * (li["unit_price"] or 0) / tot)
    month_rows = [{"month": k, "advance": v["advance"], "final": v["final"], "total": _r2(v["advance"] + v["final"]),
                   "by_project": dict(v["by_project"])} for k, v in sorted(months.items())]
    return {"inflows": [{**i, "day": iso(i["day"])} for i in inflows],
            "outflows": [{**o, "day": iso(o["day"])} for o in outflows],
            "steps": steps, "lowest": low, "months": month_rows,
            "total_gross": _r2(sum(m["total"] for m in month_rows)),
            "total_net": _r2(sum(o["net"] for o in orders)), "vat_factor": vat}


# ---------------------------------------------------------------- input changes


def _input_changes(db: Session, plan: M.Plan, designs: dict[int, Design]) -> list[dict]:
    """The designs that moved since a person last reviewed the plan (decision
    0107 item 12)."""
    from . import project_bom

    seen = plan.reviewed or {}
    out = []
    for pid, d in designs.items():
        then = seen.get(str(pid)) or {}
        now_snap = d.snapshot.id if d.snapshot else None
        now_ver = d.version.id if d.version else None
        if not then:
            out.append({"project_id": pid, "first": True, "snapshot_from": None, "snapshot_to": now_snap,
                        "process_from": None, "process_to": now_ver, "bom": None})
            continue
        if then.get("snapshot_id") == now_snap and then.get("process_version_id") == now_ver:
            continue
        diff = None
        if then.get("snapshot_id") and now_snap and then.get("snapshot_id") != now_snap:
            a = db.get(M.ProjectSnapshot, then["snapshot_id"])
            if a is not None and d.snapshot is not None:
                full = project_bom.bom_diff(db, a, d.snapshot, d.board, d.variant)
                diff = {"added": full["added"][:50], "removed": full["removed"][:50], "changed": full["changed"][:50],
                        "counts": {k: len(full[k]) for k in ("added", "removed", "changed")}}
        out.append({"project_id": pid, "first": False, "snapshot_from": then.get("snapshot_id"),
                    "snapshot_to": now_snap, "process_from": then.get("process_version_id"),
                    "process_to": now_ver, "bom": diff})
    return out


# ---------------------------------------------------------------- progress


def _progress(db: Session, L: Loaded, deliveries_by_project: dict, today: date) -> list[dict]:
    """Shipped against planned, by today, per order; and built against the
    units the line must have finished by today, per project."""
    from . import orders as order_svc

    out = []
    for o in L.orders:
        if o.draft:
            continue
        planned = 0
        for li in o.lines:
            for dv in L.deliveries.get(li.id, []):
                n = L.nodes.get(dv.node_id) if dv.node_id else None
                d = parse_day(n.done_on or n.day) if n else None
                if n and n.mode == "after" and not n.done_on:
                    d = None  # computed later by the caller's dates; keep the conservative fixed reading
                if d and d <= today:
                    planned += dv.qty
        shipped = sum(order_svc.line_shipped(li) for li in o.lines)
        out.append({"order_id": o.id, "key": o.plan_key or o.order_ref, "planned_by_today": planned,
                    "shipped": shipped, "behind": max(planned - shipped, 0)})
    return out


# ---------------------------------------------------------------- checks, blockers, agenda


def _checks(plan: M.Plan, s: dict) -> list[dict]:
    orders = s["orders"]
    has = lambda code: [o["key"] for o in orders if any(f["code"] == code for f in o["flags"])]
    lowest = (s["cash"]["lowest"] or {}).get("margin")
    return [
        {"key": "order_past", "label": "No draft order is dated in the past", "ok": not has("order_past"),
         "items": has("order_past")},
        {"key": "two_month", "label": f"First delivery at least {plan.min_lead_months} months after the advance "
                                      "falls due", "ok": not has("two_month"), "items": has("two_month")},
        {"key": "limit", "label": "Advances per due date within the limit", "ok": not s["over_limit"],
         "items": [a["day"] for a in s["over_limit"]], "skipped": not plan.advance_limit_net},
        {"key": "one_month", "label": "Each order delivered in one calendar month", "ok": not has("one_month"),
         "items": has("one_month")},
        {"key": "funding", "label": "Purchases within the advances received", "ok": lowest is None or lowest >= 0,
         "items": []},
        {"key": "closures", "label": "No batch in production over a supplier closure",
         "ok": not any(b["closures"] for b in s["batches"]), "items": [b["label"] for b in s["batches"] if b["closures"]]},
        {"key": "boards", "label": "Boards cover each build", "ok": not any(c["short"] for c in s["coverage"]),
         "items": [c["project"] for c in s["coverage"] if c["short"]]},
        {"key": "parts", "label": "Every part covers its needs", "ok": not any(p["status"] == "short" for p in s["parts"]),
         "items": [p["name"] for p in s["parts"] if p["status"] == "short"][:20]},
        {"key": "conflicts", "label": "No date in conflict", "ok": not _conflicts(s), "items": [c["label"] for c in _conflicts(s)]},
    ]


def _conflicts(s: dict) -> list[dict]:
    out = []
    for o in s["orders"]:
        for li in o["lines"]:
            for d in li["deliveries"]:
                if d["conflict"]:
                    out.append({"label": f"{o['key']} delivery {d['day']}", "text": d["conflict"]})
    for b in s["batches"]:
        if b["conflict"]:
            out.append({"label": b["label"], "text": b["conflict"]})
    for m in s["milestones"]:
        if m["conflict"]:
            out.append({"label": m["label"], "text": m["conflict"]})
    return out


def _blk(sev, title, text, stops, action, by, source="", link="") -> dict:
    return {"severity": sev, "title": title, "text": text, "stops": stops, "action": action,
            "by": iso(by) if isinstance(by, date) else (by or ""), "source": source, "link": link}


def _blockers(plan: M.Plan, s: dict, today: date) -> list[dict]:
    B: list[dict] = []
    orders = s["orders"]
    past = [o for o in orders if any(f["code"] == "order_past" for f in o["flags"])]
    if past:
        B.append(_blk("block", f"{len(past)} draft orders are dated in the past",
                      ", ".join(f"{o['key']} ({o['order_date']})" for o in past) + ". The customer has not placed them.",
                      "Every date after them is a guess until the customer orders.",
                      "Move their order dates, or confirm the orders when the customer places them.", today,
                      "the plan's draft orders"))
    late_adv = [o for o in orders if o["advance_state"] == "late"]
    if late_adv:
        B.append(_blk("block", f"{len(late_adv)} advances are late",
                      ", ".join(f"{o['key']} (due {o['advance_due']})" for o in late_adv) + ".",
                      "The deliveries that follow these advances move one day for each day of delay.",
                      "Record the payment, or ask the customer.", today, "sales invoices"))
    for code, title, act in (("two_month", "delivered too soon after the advance", "Move the first delivery."),
                             ("one_month", "delivered across two months", "Move a delivery into one month, or split "
                                                                          "the order.")):
        hit = [o for o in orders if any(f["code"] == code for f in o["flags"])]
        if hit:
            B.append(_blk("block", f"{len(hit)} orders are {title}", ", ".join(o["key"] for o in hit) + ".",
                          "The contract terms." if code == "two_month" else
                          "Their final invoices miss the VAT deadline (the 15th of the next month).",
                          act, min(parse_day(o["order_date"]) or today for o in hit), "plan parameters"))
    if s["over_limit"]:
        B.append(_blk("block", "Advances above the limit",
                      ", ".join(f"{a['day']}: {a['net']:,.2f}" for a in s["over_limit"]) + ".",
                      "The customer's weekly limit.", "Move an order to the next week.",
                      parse_day(s["over_limit"][0]["day"]), "plan parameters"))
    for c in _conflicts(s):
        B.append(_blk("block", f"Date conflict: {c['label']}", c["text"] + ".", "This date.",
                      "Move the fixed date, or change what it follows.", today, "the node"))
    for b in s["batches"]:
        if b["closures"]:
            B.append(_blk("block", f"{b['label']} is in production over {', '.join(b['closures'])}",
                          f"{b['label']} runs {b['order_day']} to {b['arrival_day']}.",
                          "The deliveries this batch covers.", "Order it earlier, or split it.",
                          parse_day(b["order_day"]), "closures"))
        if b["planned"] and b["order_late_days"]:
            B.append(_blk("block", f"{b['label']} is not ordered, {b['order_late_days']} days late",
                          f"It was planned for {b['order_planned']}. The plan now counts it from today.",
                          "Its boards and everything after them.", "Order the batch, or mark the order done.",
                          today, "batches"))
    for c in s["coverage"]:
        if c["short"]:
            f = c["short"][0]
            B.append(_blk("block", f"{c['project']}: boards run out at the delivery of {f['delivery']}",
                          f"{f['have']:,} boards are in house on {f['need_day']} and {f['need']:,} are needed.",
                          f"{len(c['short'])} deliveries, {c['short'][0]['delivery']} to {c['short'][-1]['delivery']}.",
                          "Move a batch earlier, or move the deliveries.", parse_day(f["need_day"]), "batches"))
        if c["over_rate"]:
            w = c["over_rate"][0]
            B.append(_blk("risk", f"{c['project']}: more units a week than the line makes",
                          f"{len(c['over_rate'])} weeks over {c['line_rate_week']} a week, the first {w['week']} "
                          f"({w['units']}).", "The deliveries of those weeks.",
                          "Spread the deliveries, or raise the line rate.", parse_day(w["week"]), "plan projects"))
    shorts = [p for p in s["parts"] if p["status"] == "short"]
    public = [p for p in s["parts"] if p["status"] == "public"]
    shown = {p["key"] for p in sorted(shorts, key=lambda p: p["first_short"] or "9999")[:8]}
    if len(shorts) > len(shown):
        rest = [p for p in shorts if p["key"] not in shown]
        B.append(_blk("block", f"{len(rest)} more parts are short",
                      ", ".join(f"{p['name']} ({p['short']:,.0f})" for p in rest[:12]) + (" …" if len(rest) > 12 else "")
                      + ".", "The batches and builds that need them.", "Open the Parts tab.",
                      min(parse_day(p["first_short"]) or today for p in rest), "parts", link="parts"))
    if public:
        B.append(_blk("risk", f"{len(public)} parts are covered only by JLC public stock",
                      ", ".join(p["name"] for p in public[:12]) + (" …" if len(public) > 12 else "")
                      + ". JLC holds them for anyone; nothing reserves them for this plan.",
                      "The batches that order them.", "Buy the scarce ones into the private inventory.",
                      min(parse_day(p["first_short"]) or today for p in public), "parts", link="parts"))
    for p in s["parts"]:
        if p["status"] == "short" and p["key"] in shown:
            hint = (" Plan a machining lot of its recipe." if p["prepared"] else "")
            B.append(_blk("block", f"{p['name']}: {p['short']:,.0f} short from {p['first_short']}",
                          f"Need {p['need']:,.0f}. Reserved {p['reserved']:,.0f}, free {p['free']:,.0f}, "
                          f"incoming {p['incoming']:,.0f}, from machining {p['from_lots']:,.0f}." + hint,
                          "The builds and batches from that day.",
                          "Accept a purchase proposal, or reserve stock." if not p["prepared"] else
                          "Plan a machining lot.", parse_day(p["first_short"]), "parts",
                          link=f"part:{p['key']}"))
        if p["reserved_broken"] > 1e-6:
            B.append(_blk("block", f"{p['name']}: reservation {p['reserved_broken']:,.0f} short",
                          "Stock reserved for this plan is no longer on hand. A draw the supplier reported took it.",
                          "The builds that count on the reservation.", "Reserve again, or buy the difference.", today,
                          "reservations", link=f"part:{p['key']}"))
    no_lead = [pr for pr in s["proposals"] if pr["no_lead"]]
    if no_lead:
        B.append(_blk("risk", f"{len(no_lead)} short parts have no source with a lead time",
                      ", ".join(pr["name"] for pr in no_lead[:12]) + (" …" if len(no_lead) > 12 else "")
                      + ". The plan cannot say when they can arrive.", "The builds that need them.",
                      "Add the lead time to each part's supplier link.",
                      min(parse_day(pr["need_day"]) or today for pr in no_lead), "suppliers", link="parts"))
    for pr in s["proposals"]:
        if pr["no_lead"]:
            continue
        if pr["late"]:
            B.append(_blk("block", f"{pr['name']}: cannot arrive in time",
                          f"{pr['supplier']} takes {pr['lead_days']} days, so {pr['qty']:,.0f} arrive "
                          f"{pr['arrival_day']} at the earliest. They are needed {pr['need_day']}.",
                          "The builds until they arrive.", "Find a faster source, or move the deliveries.",
                          parse_day(pr["order_day"]), "proposals", link=f"part:{pr['part_key']}"))
    for po in s["purchase_orders"]:
        if po.get("out_of_date"):
            B.append(_blk("decide", f"Purchase draft #{po['id']} is out of date", po["out_of_date"],
                          "Its quantity or date.", "Take the new proposal, or delete the draft.", today,
                          "purchase orders", link=f"po:{po['id']}"))
        if po.get("surplus"):
            tot = sum(x["value"] for x in po["surplus"])
            B.append(_blk("risk", f"Ordered purchase {po['reference'] or '#' + str(po['id'])} is more than the plan "
                                  "needs",
                          ", ".join(f"{x['name']} {x['qty']:,.0f}" for x in po["surplus"]) +
                          f". Value {tot:,.2f} {po['currency']}.", "Money held in stock.",
                          "Keep it for a later order, or sell it on.", None, "purchase orders",
                          link=f"po:{po['id']}"))
        if po["status"] == "draft" and po["order_late_days"]:
            B.append(_blk("block", f"Purchase draft #{po['id']} ({po['supplier']}) is {po['order_late_days']} days "
                                   "late", "Its order date has passed.", "What it supplies.",
                          "Place the order and mark it ordered.", today, "purchase orders", link=f"po:{po['id']}"))
        if po["status"] == "ordered" and po["arrival_late_days"]:
            B.append(_blk("risk", f"{po['supplier']} {po['reference']} has not arrived",
                          f"It was expected {po['arrival_late_days']} days ago.", "What it supplies.",
                          "Ask the supplier, then set the new date.", today, "purchase orders",
                          link=f"po:{po['id']}"))
    for m in s["milestones"]:
        if m["kind"] == "milestone" and m["late_days"]:
            B.append(_blk("block", f"{m['label']} is {m['late_days']} days late",
                          f"It was planned for {m['planned']}. The plan counts it from today, and the dates after "
                          "it move.", "Everything that follows it.", "Do it, then mark it done.", today, "milestones"))
    low = s["cash"]["lowest"]
    if low and low["margin"] < 0:
        B.append(_blk("block", "Purchases exceed the advances received",
                      f"On {low['day']} the purchases pass the advances by {-low['margin']:,.2f}.", "The funding rule.",
                      "Move the purchase after the next advance.", parse_day(low["day"]), "cash"))
    elif low and low["margin"] < 5000:
        B.append(_blk("risk", f"Funding margin of {low['margin']:,.2f} on {low['day']}",
                      "One advance paid a day late moves the purchases of that day.", "The purchases of that day.",
                      "Check the bank receipt before each purchase.", parse_day(low["day"]), "cash"))
    for cp in s["customer_parts"]:
        if not cp["confirmed"] and cp["needs"]:
            first = cp["needs"][0]
            B.append(_blk("risk", f"The customer has not confirmed the {cp['name']} dates",
                          f"{first['cumulative']:,.0f} are needed by {first['need_day']}, "
                          f"{cp['needs'][-1]['cumulative']:,.0f} by {cp['needs'][-1]['need_day']}.",
                          "Every delivery.", "Agree the dates with the customer.", parse_day(first["need_day"]),
                          "customer parts"))
    for ch in s["changes"]:
        if not ch["first"]:
            B.append(_blk("decide", "A design input changed since the last review",
                          f"Project {ch['project_id']}: snapshot {ch['snapshot_from']} to {ch['snapshot_to']}, "
                          f"process version {ch['process_from']} to {ch['process_to']}.",
                          "The needs of the planned batches.", "Read the difference, then mark it reviewed.", today,
                          "designs"))
    for pg in s["progress"]:
        if pg["behind"]:
            B.append(_blk("block", f"{pg['key']} is {pg['behind']} units behind",
                          f"{pg['planned_by_today']} were planned by today, {pg['shipped']} are shipped.",
                          "The customer's dates.", "Ship them, or agree new dates.", today, "orders"))
    if plan.status == "draft" and orders:
        B.append(_blk("decide", "Send the plan to the customer", "The plan is a draft. The customer has not agreed "
                      "the dates.", "Every customer date stays a proposal.", "Mark the plan sent, then agreed.",
                      min((parse_day(o["order_date"]) for o in orders if o["order_date"]), default=today), "plan"))
    if s["cycle"]:
        B.append(_blk("block", "The dates go round in a circle", s["cycle"], "Every date in the circle.",
                      "Remove one of the links.", today, "nodes"))
    order = {"block": 0, "risk": 1, "decide": 2}
    B.sort(key=lambda b: (order[b["severity"]], b["by"] or "9999"))
    return B


def _agenda(plan: M.Plan, s: dict, today: date) -> list[dict]:
    """Every dated step, for the week-by-week list."""
    E: list[dict] = []

    def ev(day, party, kind, text, amount=None, status="planned", project_id=None, problem=False, ref=""):
        if day:
            E.append({"day": day, "party": party, "kind": kind, "text": text, "amount": amount, "status": status,
                      "project_id": project_id, "problem": problem, "ref": ref})
    for o in s["orders"]:
        pid = o["lines"][0]["project_id"] if o["lines"] else None
        bad = bool(o["flags"])
        if o["draft"]:
            ev(o["order_date"], "customer", "order", f"The customer places {o['key']}. We issue the advance invoice.",
               o["advance_gross"], "late" if any(f["code"] == "order_past" for f in o["flags"]) else "planned", pid,
               any(f["code"] == "order_past" for f in o["flags"]), f"order:{o['id']}")
        ev(o["advance_paid_on"] or o["advance_due"], "customer", "advance",
           f"The customer pays the {o['key']} advance", o["advance_gross"],
           "done" if o["advance_paid_on"] else ("late" if o["advance_state"] == "late" else "planned"), pid,
           o["advance_state"] == "late", f"order:{o['id']}")
        ev(o["final_day"], "ours", "invoice", f"Issue the final invoice for {o['key']}", o["final_gross"],
           "planned", pid, bad, f"order:{o['id']}")
        ev(o["final_due"], "customer", "payment", f"The customer pays the {o['key']} final invoice", o["final_gross"],
           "planned", pid, False, f"order:{o['id']}")
    short_days = {x["delivery"] for c in s["coverage"] for x in c["short"]}
    for w in s["weeks"]:
        parts = ", ".join(f"{x['key']} {x['qty']}" for x in w["orders"])
        ev(w["day"], "ours", "delivery", f"Deliver {w['total']} units ({parts})", None,
           "blocked" if w["day"] in short_days else "planned", None, w["day"] in short_days)
    for b in s["batches"]:
        if b["planned"]:
            ev(b["order_day"], "ours", "batch", f"Order {b['label']}: {b['qty']:,} boards", b["cost"],
               "late" if b["order_late_days"] else "planned", b["project_id"], bool(b["order_late_days"] or b["closures"]),
               f"run:{b['id']}")
        ev(b["arrival_day"], "supplier", "arrival", f"{b['label']} boards arrive", None,
           "blocked" if b["closures"] else "planned", b["project_id"], bool(b["closures"]), f"run:{b['id']}")
    for po in s["purchase_orders"]:
        names = ", ".join((ln["name"] or ln["mpn"] or ln["lcsc"]) for ln in po["lines"][:3])
        if po["status"] == "draft":
            ev(po["order_day"], "ours", "purchase", f"Order from {po['supplier']}: {names}", po["amount_pln"],
               "late" if po["order_late_days"] else "planned", None, bool(po["order_late_days"]), f"po:{po['id']}")
        if po["status"] in ("draft", "ordered"):
            ev(po["arrival_day"], "supplier", "arrival", f"{po['supplier']} delivers: {names}", None,
               "late" if po["arrival_late_days"] else "planned", None, bool(po["arrival_late_days"]), f"po:{po['id']}")
    for pr in s["proposals"]:
        if not pr.get("covered_by_po_id"):
            ev(pr["order_day"], "ours", "proposal", f"Proposed: order {pr['qty']:,.0f} × {pr['name']}"
               + (f" from {pr['supplier']}" if pr["supplier"] else ""), pr["amount_pln"],
               "proposal", None, pr["late"] or pr["no_lead"], f"part:{pr['part_key']}")
    for lt in s["lots"]:
        ev(lt["start_day"], "ours", "machining", f"Start {lt['label']}: {lt['qty']:,.0f}"
           + (f" at {lt['rate_per_day']:g} a working day" if lt["rate_per_day"] else ""), None,
           "late" if lt["late_days"] else "planned", lt["project_id"], bool(lt["late_days"]))
        ev(lt["end_day"], "ours", "machining", f"{lt['label']} ends", None, "planned", lt["project_id"])
    for m in s["milestones"]:
        if m["kind"] == "closure":
            ev(m["day"], "supplier", "closure", f"{m['label']} begins" + (f" (to {m['end_day']})" if m["end_day"] else ""),
               None, "fixed")
        else:
            ev(m["day"], "ours" if m["party"] == "ours" else m["party"], "milestone", m["label"], None,
               "done" if m["done"] else ("late" if m["late_days"] else "planned"), None, bool(m["late_days"]))
    for cp in s["customer_parts"]:
        for r in cp["needs"][:: max(len(cp["needs"]) // 6, 1)]:
            ev(r["need_day"], "customer", "customer part",
               f"The customer supplies {cp['name']}: {r['cumulative']:,.0f} in total"
               + ("" if cp["confirmed"] else " (not confirmed)"), None, "planned", cp["project_id"])
    party = {"customer": 1, "ours": 2, "supplier": 3}
    E.sort(key=lambda e: (e["day"], party.get(e["party"], 0)))
    return E


# ---------------------------------------------------------------- attention (Home)


def attention(db: Session, plans: list[M.Plan], today: date | None = None) -> list[dict]:
    """Each plan's blockers in short, for Home."""
    out = []
    for p in plans:
        try:
            s = schedule(db, p, today)
        except Exception as e:
            out.append({"plan_id": p.id, "name": p.name, "error": str(e)[:300], "counts": {}, "top": []})
            continue
        counts = defaultdict(int)
        for b in s["blockers"]:
            counts[b["severity"]] += 1
        week_end = (today or date.today()) + timedelta(days=7)
        to_place = [pr for pr in s["proposals"] if not pr.get("covered_by_po_id") and pr["order_day"]
                    and parse_day(pr["order_day"]) <= week_end]
        to_place += [po for po in s["purchase_orders"] if po["status"] == "draft" and po["order_day"]
                     and parse_day(po["order_day"]) <= week_end]
        out.append({"plan_id": p.id, "name": p.name, "counts": dict(counts),
                    "top": [b for b in s["blockers"] if b["severity"] == "block"][:5],
                    "purchases_this_week": len(to_place),
                    "late_advances": sum(1 for o in s["orders"] if o["advance_state"] == "late"),
                    "conflicts": len(_conflicts(s)),
                    "shortages": sum(1 for x in s["parts"] if x["status"] == "short"),
                    "broken_reservations": sum(1 for x in s["parts"] if x["reserved_broken"] > 1e-6),
                    "public_only": sum(1 for x in s["parts"] if x["status"] == "public")})
    return out
