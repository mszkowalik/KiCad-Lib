"""Sales orders, invoices, shipments, finished-goods stock and device history.

Decision record 0003. Thin handlers: every rule lives in `services/orders.py`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import companies as company_svc
from ..services import orders as svc
from .util import actor_of, audit

router = APIRouter(prefix="/api", tags=["sales-orders"])


def _order(db: Session, order_id: int) -> M.SalesOrder:
    o = db.get(M.SalesOrder, order_id)
    if o is None:
        raise HTTPException(404, "order not found")
    return o


def _by_serial(db: Session, serials: list[str]) -> list[M.DeviceUnit]:
    """Resolve the serials a scanner read. A scan sheet names devices by the
    string on the label, never by our row id, so every path a sheet reaches —
    a shipment, a stock count — takes both."""
    wanted = [s.strip() for s in serials if s and s.strip()]
    if not wanted:
        return []
    found = {d.serial: d for d in db.query(M.DeviceUnit)
             .filter(M.DeviceUnit.serial.in_(wanted)).all()}
    missing = [s for s in wanted if s not in found]
    if missing:
        raise HTTPException(404, {"error": "no device carries these serials", "serials": missing})
    out, seen = [], set()
    for s in wanted:
        if found[s].id not in seen:
            out.append(found[s])
            seen.add(found[s].id)
    return out


def _device(db: Session, device_id: int) -> M.DeviceUnit:
    d = db.get(M.DeviceUnit, device_id)
    if d is None:
        raise HTTPException(404, "no such device")
    return d


# --------------------------------------------------------------- customers


class CustomerIn(BaseModel):
    name: str
    tax_id: str = ""
    address: str = ""
    payment_terms_days: int = 14
    notes: str = ""


class CustomerPatch(BaseModel):
    name: str | None = None
    tax_id: str | None = None
    address: str | None = None
    payment_terms_days: int | None = None
    notes: str | None = None


@router.get("/customers")
def list_customers(db: Session = Depends(get_db)):
    return [svc.customer_json(c) for c in db.query(M.Customer).order_by(M.Customer.name).all()]


@router.post("/customers")
def create_customer(body: CustomerIn, request: Request, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "a customer needs a name")
    if db.query(M.Customer).filter(M.Customer.name == name).first():
        raise HTTPException(409, f"customer {name!r} already exists")
    c = M.Customer(name=name, tax_id=body.tax_id.strip(), address=body.address,
                   payment_terms_days=body.payment_terms_days, notes=body.notes)
    db.add(c)
    db.flush()
    audit(db, "customer.create", "customer", c.id, {"name": name}, actor=actor_of(request))
    db.commit()
    return svc.customer_json(c)


@router.patch("/customers/{customer_id}")
def update_customer(customer_id: int, body: CustomerPatch, request: Request, db: Session = Depends(get_db)):
    c = db.get(M.Customer, customer_id)
    if c is None:
        raise HTTPException(404, "customer not found")
    before = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if isinstance(v, str):
            v = v.strip() if k != "address" else v
        if k == "name" and not v:
            raise HTTPException(422, "a customer needs a name")
        if getattr(c, k) != v:
            before[k] = getattr(c, k)
            setattr(c, k, v)
    audit(db, "customer.update", "customer", c.id, before or None, actor=actor_of(request))
    db.commit()
    return svc.customer_json(c)


# ------------------------------------------------------------------ orders


class LineIn(BaseModel):
    project_id: int
    board: str = ""
    variant: str = ""
    product: str = ""
    qty_ordered: int
    unit_price: float


class OrderIn(BaseModel):
    # Decision 0063: the company that sells. Default: the caller's only company,
    # else the owner of the first line's project on the order date.
    company_id: int | None = None
    customer_id: int | None = None
    customer: str = ""  # create-or-find by name when no id
    order_ref: str = ""
    order_date: str = ""
    currency: str = "PLN"
    vat_pct: float = 23.0
    notes: str = ""
    lines: list[LineIn] = []


class OrderPatch(BaseModel):
    customer_id: int | None = None
    customer: str | None = None  # create-or-find by name when no id, as on create
    order_ref: str | None = None
    order_date: str | None = None
    currency: str | None = None
    vat_pct: float | None = None
    notes: str | None = None
    cancelled: bool | None = None
    company_id: int | None = None


@router.get("/orders")
def list_orders(request: Request = None, customer_id: int | None = None, project_id: int | None = None,
                db: Session = Depends(get_db)):
    q = db.query(M.SalesOrder)
    scope = company_svc.scope_ids(db, request)   # the header switcher (decision 0063)
    q = q.filter(M.SalesOrder.company_id.in_(scope) | M.SalesOrder.company_id.is_(None))
    if customer_id:
        q = q.filter(M.SalesOrder.customer_id == customer_id)
    if project_id:
        q = q.filter(M.SalesOrder.lines.any(M.SalesOrderLine.project_id == project_id))
    projects = {p.id: p.name for p in db.query(M.Project).all()}
    rows = q.order_by(M.SalesOrder.order_date.desc(), M.SalesOrder.id.desc()).all()
    return [svc.order_json(db, o, projects=projects) for o in rows]


@router.post("/orders")
def create_order(body: OrderIn, request: Request, db: Session = Depends(get_db)):
    if body.customer_id:
        cust = db.get(M.Customer, body.customer_id)
        if cust is None:
            raise HTTPException(404, "customer not found")
    else:
        cust = svc.get_customer(db, body.customer)
    o = M.SalesOrder(customer_id=cust.id, order_ref=body.order_ref.strip(), order_date=body.order_date.strip(),
                     currency=(body.currency or "PLN").upper(), vat_pct=body.vat_pct, notes=body.notes)
    db.add(o)
    db.flush()
    for i, li in enumerate(body.lines):
        _add_line(db, o, li, i)
    db.flush()
    o.company_id = _seller(db, request, body, o).id
    db.expire(o, ["lines"])
    svc.refresh_order_status(o)
    audit(db, "order.create", "sales_order", o.id, {"customer": cust.name, "order_ref": o.order_ref},
          actor=actor_of(request))
    db.commit()
    return svc.order_json(db, o, with_detail=True)


def _seller(db: Session, request: Request, body: OrderIn, o: M.SalesOrder) -> M.Company:
    """The company that sells an order (decision 0063)."""
    if body.company_id:
        return company_svc.get(db, body.company_id)
    mine = company_svc.visible_ids(db, getattr(request.state, "user", None))
    if len(mine) == 1:
        return company_svc.get(db, mine[0])
    if body.lines:
        owner = company_svc.owner_on(db, body.lines[0].project_id, o.order_date or None)
        if owner is not None:
            return owner
    raise HTTPException(422, "say which company sells this order (company_id)")


def _add_line(db: Session, o: M.SalesOrder, li: LineIn, position: int) -> M.SalesOrderLine:
    if db.get(M.Project, li.project_id) is None:
        raise HTTPException(404, f"project {li.project_id} not found")
    if li.qty_ordered < 1:
        raise HTTPException(422, "qty_ordered must be >= 1")
    row = M.SalesOrderLine(order_id=o.id, project_id=li.project_id, board=li.board.strip(),
                           variant=li.variant.strip(), product=li.product.strip(),
                           qty_ordered=li.qty_ordered, unit_price=li.unit_price, position=position)
    db.add(row)
    return row


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    return svc.order_json(db, _order(db, order_id), with_detail=True)


@router.patch("/orders/{order_id}")
def update_order(order_id: int, body: OrderPatch, request: Request, db: Session = Depends(get_db)):
    o = _order(db, order_id)
    before = {}
    fields = body.model_dump(exclude_unset=True)
    name = (fields.pop("customer", None) or "").strip()
    if name and not fields.get("customer_id"):
        fields["customer_id"] = svc.get_customer(db, name).id
    for k, v in fields.items():
        if k == "customer_id":
            if v is None or db.get(M.Customer, v) is None:
                raise HTTPException(404, "customer not found")
        if k == "company_id":
            v = company_svc.get(db, v).id
        if k == "currency":
            v = (v or "").strip().upper()
            if not v:
                raise HTTPException(422, "an order needs a currency")
        if k == "vat_pct" and (v is None or v < 0):
            raise HTTPException(422, "vat_pct must be >= 0")
        if isinstance(v, str) and k != "notes":
            v = v.strip()
        if getattr(o, k) != v:
            before[k] = getattr(o, k)
            setattr(o, k, v)
    svc.refresh_order_status(o)
    audit(db, "order.update", "sales_order", o.id, before or None, actor=actor_of(request))
    db.commit()
    return svc.order_json(db, o, with_detail=True)


@router.delete("/orders/{order_id}")
def delete_order(order_id: int, request: Request, db: Session = Depends(get_db)):
    o = _order(db, order_id)
    n = (db.query(M.DeviceEvent).filter(M.DeviceEvent.order_line_id.in_([li.id for li in o.lines] or [-1]))
         .count())
    if n:
        raise HTTPException(409, f"{n} device events name this order; it cannot be deleted")
    audit(db, "order.delete", "sales_order", o.id, {"order_ref": o.order_ref}, actor=actor_of(request))
    db.delete(o)
    db.commit()
    return {"deleted": order_id}


@router.post("/orders/{order_id}/lines")
def add_line(order_id: int, body: LineIn, request: Request, db: Session = Depends(get_db)):
    o = _order(db, order_id)
    row = _add_line(db, o, body, len(o.lines))
    db.flush()
    db.expire(o, ["lines"])
    svc.refresh_order_status(o)
    audit(db, "order.line.add", "sales_order", o.id, {"line_id": row.id}, actor=actor_of(request))
    db.commit()
    return svc.order_json(db, o, with_detail=True)


class LinePatch(BaseModel):
    product: str | None = None
    board: str | None = None
    variant: str | None = None
    qty_ordered: int | None = None
    unit_price: float | None = None


@router.patch("/order-lines/{line_id}")
def update_line(line_id: int, body: LinePatch, request: Request, db: Session = Depends(get_db)):
    li = db.get(M.SalesOrderLine, line_id)
    if li is None:
        raise HTTPException(404, "order line not found")
    before = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "qty_ordered" and (v is None or v < 1):
            raise HTTPException(422, "qty_ordered must be >= 1")
        if isinstance(v, str):
            v = v.strip()
        if getattr(li, k) != v:
            before[k] = getattr(li, k)
            setattr(li, k, v)
    svc.refresh_order_status(li.order)
    audit(db, "order.line.update", "sales_order", li.order_id, before or None, actor=actor_of(request))
    db.commit()
    return svc.order_json(db, li.order, with_detail=True)


@router.delete("/order-lines/{line_id}")
def delete_line(line_id: int, request: Request, db: Session = Depends(get_db)):
    li = db.get(M.SalesOrderLine, line_id)
    if li is None:
        raise HTTPException(404, "order line not found")
    if db.query(M.DeviceEvent).filter(M.DeviceEvent.order_line_id == li.id).count():
        raise HTTPException(409, "devices were shipped against this line")
    o = li.order
    audit(db, "order.line.delete", "sales_order", o.id, {"line_id": li.id}, actor=actor_of(request))
    db.delete(li)
    db.flush()
    db.expire(o, ["lines"])
    svc.refresh_order_status(o)
    db.commit()
    return svc.order_json(db, o, with_detail=True)


# ---------------------------------------------------------------- invoices


class InvoiceIn(BaseModel):
    kind: str = "final"
    number: str
    issue_date: str
    due_date: str = ""  # empty = issue + the customer's terms
    net_amount: float
    currency: str = ""
    paid_at: str = ""
    notes: str = ""


class InvoicePatch(BaseModel):
    kind: str | None = None
    number: str | None = None
    issue_date: str | None = None
    due_date: str | None = None
    net_amount: float | None = None
    currency: str | None = None
    paid_at: str | None = None
    attachment_id: int | None = None
    notes: str | None = None


@router.post("/orders/{order_id}/invoices")
def add_invoice(order_id: int, body: InvoiceIn, request: Request, db: Session = Depends(get_db)):
    o = _order(db, order_id)
    if body.kind not in svc.INVOICE_KINDS:
        raise HTTPException(422, f"kind must be one of {', '.join(svc.INVOICE_KINDS)}")
    if not body.number.strip():
        raise HTTPException(422, "an invoice needs a number")
    inv = M.OrderInvoice(order_id=o.id, kind=body.kind, number=body.number.strip(),
                         issue_date=body.issue_date.strip(),
                         due_date=body.due_date.strip() or svc.invoice_due_date(o, body.issue_date.strip()),
                         net_amount=body.net_amount, currency=(body.currency or "").upper(),
                         paid_at=body.paid_at.strip(), notes=body.notes)
    db.add(inv)
    db.flush()
    audit(db, "order.invoice.add", "sales_order", o.id, {"number": inv.number, "kind": inv.kind},
          actor=actor_of(request))
    db.commit()
    db.expire(o, ["invoices"])
    return svc.order_json(db, o, with_detail=True)


@router.patch("/order-invoices/{invoice_id}")
def update_invoice(invoice_id: int, body: InvoicePatch, request: Request, db: Session = Depends(get_db)):
    inv = db.get(M.OrderInvoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    before = {}
    for k, v in body.model_dump(exclude_unset=True).items():
        if k == "kind" and v not in svc.INVOICE_KINDS:
            raise HTTPException(422, f"kind must be one of {', '.join(svc.INVOICE_KINDS)}")
        if k == "currency" and v:
            v = v.upper()
        if isinstance(v, str) and k != "notes":
            v = v.strip()
        if getattr(inv, k) != v:
            before[k] = getattr(inv, k)
            setattr(inv, k, v)
    audit(db, "order.invoice.update", "sales_order", inv.order_id, before or None, actor=actor_of(request))
    db.commit()
    return svc.order_json(db, inv.order, with_detail=True)


@router.delete("/order-invoices/{invoice_id}")
def delete_invoice(invoice_id: int, request: Request, db: Session = Depends(get_db)):
    inv = db.get(M.OrderInvoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    o = inv.order
    audit(db, "order.invoice.delete", "sales_order", o.id, {"number": inv.number}, actor=actor_of(request))
    db.delete(inv)
    db.commit()
    db.expire(o, ["invoices"])
    return svc.order_json(db, o, with_detail=True)


# --------------------------------------------------------------- shipments


class ShipmentLineIn(BaseModel):
    """One order line's worth of a delivery: the DEVICES that left, by id or by
    scanned serial.

    **THERE IS NO QUANTITY FIELD.** Not `qty`, not `qty_unserialized`. A shipment
    is a set of serials (decisions 0032, 0049), so a quantity is never a valid
    input — and a parameter that is never valid should not be on the schema, in
    the OpenAPI document, or in a generated client. `extra="forbid"` refuses one
    and names it; `additionalProperties: false` says so to anything reading the
    schema.

    `forbid` is doing real work here. Without it pydantic DROPS an unknown key
    silently, so a caller sending `qty: 20` would get a shipment of nothing and
    no hint why — which is the only argument for declaring the field, and it is
    answered better this way.
    """

    model_config = ConfigDict(extra="forbid")

    order_line_id: int
    device_ids: list[int] = []
    serials: list[str] = []  # resolved to device ids; a scan sheet has these
    replaces_device_id: int | None = None
    note: str = ""


class ShipmentIn(BaseModel):
    shipped_at: str = ""
    delivery_note: str = ""
    tracking: str = ""
    notes: str = ""
    lines: list[ShipmentLineIn]


@router.get("/orders/{order_id}/stock-options")
def stock_options(order_id: int, db: Session = Depends(get_db)):
    """What the Ship dialog offers per line: the batches of that project with
    anything left, both counting paths."""
    o = _order(db, order_id)
    out = {}
    for li in o.lines:
        out[str(li.id)] = [s for s in svc.run_stock(db, li.project_id) if s["stock"] > 0]
    return out


@router.post("/orders/{order_id}/shipments")
def create_shipment(order_id: int, body: ShipmentIn, request: Request, db: Session = Depends(get_db)):
    o = _order(db, order_id)
    actor = actor_of(request)
    lines = []
    for ln in body.lines:
        spec = ln.model_dump()
        spec.pop("serials", None)
        ids = [*(spec.get("device_ids") or []), *(d.id for d in _by_serial(db, ln.serials))]
        spec["device_ids"] = list(dict.fromkeys(ids))
        lines.append(spec)
    sh = svc.create_shipment(db, o, shipped_at=body.shipped_at, delivery_note=body.delivery_note,
                             tracking=body.tracking, notes=body.notes,
                             lines=lines, actor=actor)
    audit(db, "order.ship", "sales_order", o.id, {"shipment_id": sh.id}, actor=actor)
    db.commit()
    db.expire(o, ["shipments", "lines"])
    return svc.order_json(db, o, with_detail=True)


@router.delete("/shipments/{shipment_id}")
def delete_shipment(shipment_id: int, request: Request, db: Session = Depends(get_db)):
    """Only a shipment nothing named can go: device events are history."""
    sh = db.get(M.Shipment, shipment_id)
    if sh is None:
        raise HTTPException(404, "shipment not found")
    if db.query(M.DeviceEvent).filter(M.DeviceEvent.shipment_id == sh.id).count():
        raise HTTPException(409, "devices are recorded on this shipment; their history cannot be deleted")
    o = sh.order
    audit(db, "order.shipment.delete", "sales_order", o.id, {"shipment_id": sh.id}, actor=actor_of(request))
    db.delete(sh)
    db.flush()
    db.expire(o, ["shipments"])
    svc.refresh_order_status(o)
    db.commit()
    return svc.order_json(db, o, with_detail=True)


class ReverseShipmentIn(BaseModel):
    note: str = ""
    dry_run: bool = True


# `PATCH /shipment-lines/{id}` is GONE (user decision 2026-09-20). Its whole
# purpose was to name the batch behind a shipment's UNSERIALISED units, and a
# shipment has none any more: `create_shipment` refuses a quantity whether or
# not a batch stands behind it, and the three that existed were replaced by the
# serials they stood for. Keeping an endpoint to curate an artefact nothing can
# create is how the artefact comes back.


@router.post("/shipments/{shipment_id}/reverse")
def reverse_shipment(shipment_id: int, body: ReverseShipmentIn, request: Request,
                     db: Session = Depends(get_db)):
    """Take back a shipment recorded in error: every delivery on it is reversed
    and its devices go back to stock. A shipment the customer RECEIVED comes
    back through `POST /api/devices/{id}/return`, not this.
    """
    sh = db.get(M.Shipment, shipment_id)
    if sh is None:
        raise HTTPException(404, "shipment not found")
    if sh.kind != "delivery":
        raise HTTPException(422, "that shipment is a return, not a delivery")
    if (sh.status or "sent") != "sent":
        raise HTTPException(409, f"shipment {sh.id} is {sh.status}; only a sent shipment can be taken back")
    actor = actor_of(request)
    plan = svc.reverse_shipment(db, sh, actor=actor, note=body.note, dry_run=body.dry_run)
    if body.dry_run:
        return plan
    audit(db, "order.shipment.reverse", "sales_order", sh.order_id,
          {"shipment_id": sh.id, "devices": len(plan["devices"]), "note": body.note}, actor=actor)
    db.commit()
    return plan


# ------------------------------------------------ open shipments (0053)
#
# Production -> Shipments: open a box for one order, pack devices into it as
# they are scanned, send it. `POST /orders/{id}/shipments` above stays the
# one-step path for a delivery whose serials are all to hand.


def _shipment(db: Session, shipment_id: int) -> M.Shipment:
    sh = db.get(M.Shipment, shipment_id)
    if sh is None:
        raise HTTPException(404, "shipment not found")
    return sh


def _shipment_detail(db: Session, sh: M.Shipment) -> dict:
    out = svc.shipment_json(db, sh)
    out["order"] = svc.order_json(db, sh.order)
    return out


class ShipmentOpenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: int
    delivery_note: str = ""
    tracking: str = ""
    notes: str = ""


class ShipmentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delivery_note: str | None = None
    tracking: str | None = None
    notes: str | None = None


class ShipmentCheckIn(BaseModel):
    codes: list[str]
    order_line_id: int | None = None


class ShipmentPackIn(BaseModel):
    """Devices by id — the scan check has already resolved every code, and a
    pack names exactly the rows the user moved."""

    model_config = ConfigDict(extra="forbid")

    device_ids: list[int]
    order_line_id: int | None = None


class ShipmentUnpackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    device_ids: list[int]


class ShipmentSendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shipped_at: str = ""
    delivery_note: str | None = None
    tracking: str | None = None


@router.get("/shipments")
def list_shipments(status: str = "", request: Request = None, db: Session = Depends(get_db)):
    """Every delivery, newest first; `status` narrows to open, sent or cancelled."""
    q = db.query(M.Shipment).filter(M.Shipment.kind == "delivery")
    scope = company_svc.scope_ids(db, request)   # the header switcher (decision 0063)
    if company_svc.narrows(db, scope):
        q = (q.join(M.SalesOrder, M.SalesOrder.id == M.Shipment.order_id)
             .filter(M.SalesOrder.company_id.in_(scope) | M.SalesOrder.company_id.is_(None)))
    if status:
        if status not in svc.SHIPMENT_STATUSES:
            raise HTTPException(422, f"status must be one of {', '.join(svc.SHIPMENT_STATUSES)}")
        q = q.filter(M.Shipment.status == status)
    projects = {p.id: p.name for p in db.query(M.Project).all()}
    return [svc.shipment_list_json(db, sh, projects)
            for sh in q.order_by(M.Shipment.created_at.desc(), M.Shipment.id.desc()).all()]


@router.post("/shipments")
def open_shipment(body: ShipmentOpenIn, request: Request, db: Session = Depends(get_db)):
    o = _order(db, body.order_id)
    actor = actor_of(request)
    sh = svc.open_shipment(db, o, delivery_note=body.delivery_note.strip(), tracking=body.tracking.strip(),
                           notes=body.notes.strip())
    audit(db, "shipment.open", "sales_order", o.id, {"shipment_id": sh.id}, actor=actor)
    db.commit()
    return _shipment_detail(db, sh)


@router.get("/shipments/{shipment_id}")
def get_shipment(shipment_id: int, db: Session = Depends(get_db)):
    return _shipment_detail(db, _shipment(db, shipment_id))


@router.patch("/shipments/{shipment_id}")
def patch_shipment(shipment_id: int, body: ShipmentPatch, request: Request, db: Session = Depends(get_db)):
    """Header fields of an OPEN box. A sent delivery is a permanent record
    (decision 0032 §4) and is not edited."""
    sh = _shipment(db, shipment_id)
    if (sh.status or "sent") != "open":
        raise HTTPException(409, f"shipment {sh.id} is {sh.status}; only an open shipment is edited")
    changes = {k: v.strip() for k, v in body.model_dump(exclude_none=True).items()}
    for k, v in changes.items():
        setattr(sh, k, v)
    audit(db, "shipment.edit", "sales_order", sh.order_id, {"shipment_id": sh.id, **changes},
          actor=actor_of(request))
    db.commit()
    return _shipment_detail(db, sh)


@router.post("/shipments/{shipment_id}/check")
def check_shipment_codes(shipment_id: int, body: ShipmentCheckIn, db: Session = Depends(get_db)):
    """Whether each scanned code may go into this box. Writes nothing."""
    sh = _shipment(db, shipment_id)
    return [svc.check_device(db, sh, c, body.order_line_id) for c in body.codes]


@router.post("/shipments/{shipment_id}/pack")
def pack_shipment(shipment_id: int, body: ShipmentPackIn, request: Request, db: Session = Depends(get_db)):
    sh = _shipment(db, shipment_id)
    actor = actor_of(request)
    n = svc.pack_devices(db, sh, body.device_ids, order_line_id=body.order_line_id, actor=actor)
    audit(db, "shipment.pack", "sales_order", sh.order_id, {"shipment_id": sh.id, "devices": n}, actor=actor)
    db.commit()
    return _shipment_detail(db, sh)


@router.post("/shipments/{shipment_id}/unpack")
def unpack_shipment(shipment_id: int, body: ShipmentUnpackIn, request: Request, db: Session = Depends(get_db)):
    sh = _shipment(db, shipment_id)
    actor = actor_of(request)
    n = svc.unpack_devices(db, sh, body.device_ids, actor=actor)
    audit(db, "shipment.unpack", "sales_order", sh.order_id, {"shipment_id": sh.id, "devices": n}, actor=actor)
    db.commit()
    return _shipment_detail(db, sh)


@router.post("/shipments/{shipment_id}/send")
def send_shipment(shipment_id: int, body: ShipmentSendIn, request: Request, db: Session = Depends(get_db)):
    sh = _shipment(db, shipment_id)
    actor = actor_of(request)
    svc.send_shipment(db, sh, shipped_at=body.shipped_at.strip(),
                      delivery_note=body.delivery_note.strip() if body.delivery_note is not None else None,
                      tracking=body.tracking.strip() if body.tracking is not None else None, actor=actor)
    audit(db, "order.ship", "sales_order", sh.order_id, {"shipment_id": sh.id}, actor=actor)
    db.commit()
    db.expire(sh.order, ["shipments", "lines"])
    return _shipment_detail(db, sh)


@router.post("/shipments/{shipment_id}/cancel")
def cancel_shipment(shipment_id: int, request: Request, db: Session = Depends(get_db)):
    """Give up on an open box. Its devices go back to stock; the header stays,
    because their history names it. An open box nothing was ever packed into
    can simply be deleted (`DELETE /shipments/{id}`)."""
    sh = _shipment(db, shipment_id)
    actor = actor_of(request)
    n = svc.cancel_shipment(db, sh, actor=actor)
    audit(db, "shipment.cancel", "sales_order", sh.order_id, {"shipment_id": sh.id, "devices": n}, actor=actor)
    db.commit()
    return _shipment_detail(db, sh)


# ----------------------------------------------------------------- devices


class ReturnIn(BaseModel):
    order_line_id: int | None = None
    reason: str = ""
    returned_at: str = ""
    shipment_id: int | None = None
    note: str = ""


class RepairCostIn(BaseModel):
    kind: str = "material"
    amount: float = 0.0
    currency: str = "PLN"
    component_id: int | None = None
    qty: float = 1.0
    note: str = ""


class RepairIn(BaseModel):
    outcome: str = "to_stock"  # to_stock | dispose
    repaired_at: str = ""
    cost_lines: list[RepairCostIn] = []
    note: str = ""


class DisposeIn(BaseModel):
    reason: str = ""
    disposed_at: str = ""
    note: str = ""


class MissingIn(BaseModel):
    counted_at: str = ""
    note: str = ""


class FoundIn(BaseModel):
    found_at: str = ""
    note: str = ""


class UnshipIn(BaseModel):
    shipment_id: int | None = None
    note: str = ""
    dry_run: bool = True


class AllocateIn(BaseModel):
    order_line_id: int
    device_ids: list[int]


class ProducedIn(BaseModel):
    device_ids: list[int]


@router.get("/devices/{device_id}/history")
def device_history(device_id: int, db: Session = Depends(get_db)):
    return svc.device_history_json(db, _device(db, device_id))


@router.post("/devices/{device_id}/return")
def return_device(device_id: int, body: ReturnIn, request: Request, db: Session = Depends(get_db)):
    d = _device(db, device_id)
    line = db.get(M.SalesOrderLine, body.order_line_id) if body.order_line_id else None
    if body.order_line_id and line is None:
        raise HTTPException(404, "order line not found")
    sh = db.get(M.Shipment, body.shipment_id) if body.shipment_id else None
    if sh is not None and sh.kind != "return":
        raise HTTPException(422, "that shipment is a delivery, not a return")
    actor = actor_of(request)
    res = svc.return_device(db, d, order_line=line, reason=body.reason, returned_at=body.returned_at,
                            shipment=sh, actor=actor, note=body.note)
    audit(db, "device.return", "device_unit", d.id, res, actor=actor)
    db.commit()
    db.expire(d)  # `events` was loaded before the write; the log must show it
    return svc.device_history_json(db, d)


@router.post("/devices/{device_id}/repair")
def repair_device(device_id: int, body: RepairIn, request: Request, db: Session = Depends(get_db)):
    d = _device(db, device_id)
    actor = actor_of(request)
    svc.repair_device(db, d, outcome=body.outcome, cost_lines=[c.model_dump() for c in body.cost_lines],
                      repaired_at=body.repaired_at, actor=actor, note=body.note)
    audit(db, "device.repair", "device_unit", d.id, {"outcome": body.outcome}, actor=actor)
    db.commit()
    db.expire(d)  # `events` was loaded before the write; the log must show it
    return svc.device_history_json(db, d)


@router.post("/devices/{device_id}/dispose")
def dispose_device(device_id: int, body: DisposeIn, request: Request, db: Session = Depends(get_db)):
    d = _device(db, device_id)
    actor = actor_of(request)
    svc.dispose_device(db, d, reason=body.reason, disposed_at=body.disposed_at, actor=actor, note=body.note)
    audit(db, "device.dispose", "device_unit", d.id, {"reason": body.reason}, actor=actor)
    db.commit()
    db.expire(d)  # `events` was loaded before the write; the log must show it
    return svc.device_history_json(db, d)


@router.post("/devices/{device_id}/missing")
def mark_missing(device_id: int, body: MissingIn, request: Request, db: Session = Depends(get_db)):
    """A stock count did not find this in-stock unit (decision 0057)."""
    d = _device(db, device_id)
    actor = actor_of(request)
    svc.mark_missing(db, d, counted_at=body.counted_at, actor=actor, note=body.note)
    audit(db, "device.missing", "device_unit", d.id, {"counted_at": body.counted_at, "note": body.note},
          actor=actor)
    db.commit()
    db.expire(d)
    return svc.device_history_json(db, d)


@router.post("/devices/{device_id}/found")
def mark_found(device_id: int, body: FoundIn, request: Request, db: Session = Depends(get_db)):
    """A missing unit turned up on our side; it goes back to stock."""
    d = _device(db, device_id)
    actor = actor_of(request)
    svc.mark_found(db, d, found_at=body.found_at, actor=actor, note=body.note)
    audit(db, "device.found", "device_unit", d.id, {"found_at": body.found_at, "note": body.note},
          actor=actor)
    db.commit()
    db.expire(d)
    return svc.device_history_json(db, d)


@router.post("/devices/{device_id}/unship")
def unship_device(device_id: int, body: UnshipIn, request: Request, db: Session = Depends(get_db)):
    """Take one device off one delivery it never left on. `dry_run` is the
    default; the rest of the shipment stays as it was (decision 0057)."""
    d = _device(db, device_id)
    actor = actor_of(request)
    plan = svc.unship_device(db, d, shipment_id=body.shipment_id, actor=actor, note=body.note,
                             dry_run=body.dry_run)
    if body.dry_run:
        return plan
    audit(db, "device.unship", "device_unit", d.id, {**plan, "note": body.note}, actor=actor)
    db.commit()
    db.expire(d)
    return svc.device_history_json(db, d)


@router.post("/orders/{order_id}/allocate")
def allocate(order_id: int, body: AllocateIn, request: Request, db: Session = Depends(get_db)):
    o = _order(db, order_id)
    line = next((li for li in o.lines if li.id == body.order_line_id), None)
    if line is None:
        raise HTTPException(404, "order line not found on this order")
    actor = actor_of(request)
    n = svc.allocate_devices(db, line, body.device_ids, actor=actor)
    audit(db, "order.allocate", "sales_order", o.id, {"line_id": line.id, "devices": n}, actor=actor)
    db.commit()
    return svc.order_json(db, o, with_detail=True)


@router.post("/runs/{run_id}/produced")
def link_produced(run_id: int, body: ProducedIn, request: Request, db: Session = Depends(get_db)):
    """Retro-link legacy devices to their batch (one `produced` event each)."""
    run = db.get(M.ProductionRun, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    actor = actor_of(request)
    res = svc.link_devices_to_run(db, run, body.device_ids, actor=actor)
    audit(db, "run.link_devices", "production_run", run.id, {"linked": res["linked"]}, actor=actor)
    db.commit()
    return res


# ------------------------------------------------------------------- stock


# ------------------------------------------------------------ stock count


class RebatchIn(BaseModel):
    """Devices filed against the wrong batch, by id or by scanned serial."""

    device_ids: list[int] = []
    serials: list[str] = []
    note: str = ""
    dry_run: bool = True


@router.post("/runs/{run_id}/rebatch")
def rebatch(run_id: int, body: RebatchIn, request: Request, db: Session = Depends(get_db)):
    """Move devices into this batch from the one they were filed against.

    For a bench that had the wrong batch selected. `dry_run` is the default.
    A device with no `produced` event is not moved here — link it with
    `POST /api/runs/{id}/produced` instead.
    """
    run = db.get(M.ProductionRun, run_id)
    if run is None:
        raise HTTPException(404, "no such production run")
    ids = [*body.device_ids, *(d.id for d in _by_serial(db, body.serials))]
    actor = actor_of(request)
    plan = svc.rebatch_devices(db, run, list(dict.fromkeys(ids)), actor=actor, note=body.note,
                               dry_run=body.dry_run)
    if body.dry_run:
        return plan
    audit(db, "run.rebatch", "production_run", run.id,
          {"moved": len(plan["moved"]), "from": sorted({m["from_run_id"] for m in plan["moved"]}),
           "attempts": sum(m["attempts"] for m in plan["moved"]),
           "note": body.note}, actor=actor)
    db.commit()
    return plan


@router.get("/demand")
def demand(project_id: int | None = None, db: Session = Depends(get_db)):
    """Open order quantity against shelf stock and planned batches, per project."""
    return svc.project_demand(db, project_id)


@router.get("/finished-products")
def finished_products(db: Session = Depends(get_db)):
    """The shelf per PRODUCT, counted from the device records — including the
    devices that name no batch, which every per-batch figure is blind to."""
    return {"products": svc.product_stock(db)}


@router.get("/finished-stock")
def finished_stock(project_id: int | None = None, db: Session = Depends(get_db)):
    rows = svc.run_stock(db, project_id)
    unit_cost = svc.per_device_cost_usd(db)
    for r in rows:
        r["unit_cost_usd"] = svc._round(unit_cost.get(r["run_id"]))
        r["stock_value_usd"] = svc._round(r["stock"] * unit_cost[r["run_id"]]) if r["run_id"] in unit_cost else None
    # `no_batch` is what this endpoint CANNOT see: it counts per batch, so a
    # device naming none is invisible to every row above. Reporting the number
    # here stops the two shelf cards printing different totals with nothing to
    # explain the difference (93 against 106 on 2026-09-21).
    no_batch = sum(p["no_batch"] for p in svc.product_stock(db)
                   if project_id is None or p["project_id"] == project_id)
    return {"runs": rows,
            "totals": {"stock": sum(r["stock"] for r in rows),
                       "devices_in_stock": sum(r["devices_in_stock"] for r in rows),
                       "devices_missing": sum(r["devices_missing"] for r in rows),
                       "no_batch": no_batch,
                       "stock_value_usd": svc._round(sum(r["stock_value_usd"] or 0 for r in rows))}}
