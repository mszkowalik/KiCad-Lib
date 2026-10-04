"""Sales invoices of a company that issues them (decision 0066).

Writing invoices is work and open to any signed-in user of the company, like
orders and supplier invoices. Importing the old register is a one-off
migration and admin work.
"""
from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import companies as company_svc
from ..services import storage
from ..services.invoicing import amounts as A
from ..services.invoicing import fa3, numbering
from ..services.invoicing import pdf as invoice_pdf
from ..services.invoicing import service as svc
from .users import require_admin
from .util import acting_name, audit

router = APIRouter(prefix="/api", tags=["sales-invoices"])


def _inv(db: Session, invoice_id: int) -> M.SalesInvoice:
    inv = db.get(M.SalesInvoice, invoice_id)
    if inv is None:
        raise HTTPException(404, "invoice not found")
    return inv


class LineIn(BaseModel):
    name: str
    qty: float | str = 1
    unit_net: float | str
    vat_rate: str = "23"
    unit: str = "szt."


class BuyerIn(BaseModel):
    name: str = ""
    address_l1: str = ""
    address_l2: str = ""
    nip: str = ""
    country: str = "PL"
    vat_eu: str = ""


class PaymentIn(BaseModel):
    due_date: str | None = None
    terms_days: int | None = None
    method: str = "przelew"
    paid: bool = False
    paid_date: str | None = None
    note: str = ""


class InvoiceIn(BaseModel):
    company_id: int
    kind: str = "vat"                       # vat | proforma | advance
    customer_id: int | None = None
    buyer: BuyerIn | None = None
    issue_date: str = ""
    sale_date: str = ""
    lines: list[LineIn] = []
    payment: PaymentIn | None = None
    extra_info: list[str] = []
    place: str = ""
    title: str = ""
    number: str = ""
    split_payment: bool = False
    # an advance invoice: the order it is paid against, and the gross received
    order_lines: list[LineIn] = []
    advance_gross: float | str | None = None


class InvoicePatch(BaseModel):
    customer_id: int | None = None
    buyer: BuyerIn | None = None
    issue_date: str | None = None
    sale_date: str | None = None
    number: str | None = None
    lines: list[LineIn] | None = None
    payment: PaymentIn | None = None
    extra_info: list[str] | None = None
    place: str | None = None
    title: str | None = None
    split_payment: bool | None = None
    order_lines: list[LineIn] | None = None
    advance_gross: float | str | None = None
    correction: dict | None = None


@router.get("/sales-invoices")
def list_invoices(kind: str = "", status: str = "", year: str = "", request: Request = None,
                  db: Session = Depends(get_db)):
    """The scope's invoices, newest first."""
    scope = company_svc.scope_ids(db, request)
    q = db.query(M.SalesInvoice).filter(M.SalesInvoice.company_id.in_(scope))
    if kind:
        q = q.filter(M.SalesInvoice.kind == kind)
    if status:
        q = q.filter(M.SalesInvoice.status == status)
    if year:
        q = q.filter(M.SalesInvoice.issue_date.like(f"{year}%"))
    rows = q.order_by(M.SalesInvoice.issue_date.desc(), M.SalesInvoice.id.desc()).all()
    return [svc.invoice_json(db, i) for i in rows]


@router.get("/sales-invoices/next-number")
def next_number(company_id: int, kind: str = "vat", issue_date: str = "", db: Session = Depends(get_db)):
    day = date.fromisoformat(issue_date[:10]) if issue_date else date.today()
    return {"number": numbering.next_number(db, company_id, kind, day)}


@router.get("/sales-invoices/{invoice_id}")
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    return svc.invoice_json(db, _inv(db, invoice_id), full=True)


@router.post("/sales-invoices")
def create_invoice(body: InvoiceIn, db: Session = Depends(get_db)):
    data = body.model_dump()
    inv = svc.create(db, company_id=data["company_id"], kind=data["kind"], customer_id=data["customer_id"],
                     buyer=data["buyer"], issue_date=data["issue_date"], sale_date=data["sale_date"],
                     lines=data["lines"], payment=data["payment"], extra_info=data["extra_info"],
                     place=data["place"], title=data["title"], number=data["number"],
                     split_payment=data["split_payment"], order_lines=data["order_lines"],
                     advance_gross=data["advance_gross"], actor=acting_name())
    audit(db, "sales_invoice.create", "sales_invoice", inv.id,
          {"number": inv.number, "kind": inv.kind, "status": inv.status, "gross": str(inv.gross_total)})
    db.commit()
    return svc.invoice_json(db, inv, full=True)


@router.patch("/sales-invoices/{invoice_id}")
def update_invoice(invoice_id: int, body: InvoicePatch, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    fields = body.model_dump(exclude_unset=True)
    svc.update(db, inv, fields)
    audit(db, "sales_invoice.update", "sales_invoice", inv.id, {"number": inv.number, "fields": sorted(fields)})
    db.commit()
    return svc.invoice_json(db, inv, full=True)


@router.post("/sales-invoices/{invoice_id}/cancel")
def cancel_invoice(invoice_id: int, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    svc.cancel(db, inv)
    audit(db, "sales_invoice.cancel", "sales_invoice", inv.id, {"number": inv.number})
    db.commit()
    return svc.invoice_json(db, inv)


@router.post("/sales-invoices/{invoice_id}/issue")
async def issue_invoice(invoice_id: int, ksef_number: str, received_at: str = "",
                        xml: UploadFile | None = File(default=None), db: Session = Depends(get_db)):
    """KSeF accepted the invoice. With the official XML downloaded from KSeF its
    hash is kept, which prints the verification QR code on the PDF."""
    inv = _inv(db, invoice_id)
    data = await xml.read() if xml is not None else None
    svc.issue(db, inv, ksef_number=ksef_number, xml=data, received_at=received_at)
    audit(db, "sales_invoice.issue", "sales_invoice", inv.id,
          {"number": inv.number, "ksef_number": inv.ksef_number, "with_xml": bool(data)})
    db.commit()
    return svc.invoice_json(db, inv, full=True)


class PaidIn(BaseModel):
    paid_date: str


@router.post("/sales-invoices/{invoice_id}/paid")
def mark_paid(invoice_id: int, body: PaidIn, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    svc.mark_paid(db, inv, body.paid_date)
    audit(db, "sales_invoice.paid", "sales_invoice", inv.id, {"number": inv.number, "paid_date": body.paid_date})
    db.commit()
    return svc.invoice_json(db, inv)


class CorrectIn(BaseModel):
    issue_date: str = ""
    reason: str = Field(default="", max_length=240)


@router.post("/sales-invoices/{invoice_id}/correction")
def correct_invoice(invoice_id: int, body: CorrectIn, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    kor = svc.correct(db, inv, issue_date=body.issue_date, reason=body.reason, actor=acting_name())
    audit(db, "sales_invoice.correction", "sales_invoice", kor.id, {"number": kor.number, "corrects": inv.number})
    db.commit()
    return svc.invoice_json(db, kor, full=True)


@router.get("/sales-invoices/{invoice_id}/xml")
def invoice_xml(invoice_id: int, db: Session = Depends(get_db)):
    """The FA(3) XML to upload to KSeF, refused unless the schema accepts it.
    An issued invoice with the official XML on file returns that file."""
    inv = _inv(db, invoice_id)
    if inv.official_xml_key:
        data = storage.get_bytes(inv.official_xml_key)
        if data:
            return Response(data, media_type="application/xml",
                            headers={"Content-Disposition": f'attachment; filename="{_file(inv)}-KSeF.xml"'})
    try:
        xml = fa3.build(inv)
    except fa3.Refused as e:
        raise HTTPException(422, str(e)) from e
    errors = fa3.validate(xml)
    if errors:
        raise HTTPException(422, {"error": f"the FA(3) schema refuses this invoice: {errors[0]}",
                                  "errors": errors[:20]})
    return Response(xml, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{_file(inv)}.xml"'})


@router.get("/sales-invoices/{invoice_id}/pdf")
def invoice_pdf_file(invoice_id: int, inline: bool = True, db: Session = Depends(get_db)):
    inv = _inv(db, invoice_id)
    data = invoice_pdf.render(inv)
    disp = "inline" if inline else "attachment"
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": f'{disp}; filename="{_file(inv)}.pdf"'})


def _file(inv: M.SalesInvoice) -> str:
    """2026-10-02-ZPUE: the date, the series and the buyer, as the script named files."""
    import re

    stem = re.sub(r"[^A-Za-z0-9]+", "", (inv.buyer_name or "").split(" ")[0])[:20] or "faktura"
    prefix = {"proforma": "PROFORMA-", "correction": "KOR-", "advance": "ZALICZKA-"}.get(inv.kind, "")
    num = re.sub(r"[^0-9]", "", inv.number.split("/")[0]) or "0"
    return f"{inv.issue_date[:7]}-{int(num):02d}-{prefix}{stem}"


# ------------------------------------------------------------ templates

class TemplateIn(BaseModel):
    company_id: int
    key: str = Field(min_length=1, max_length=40)
    description: str = ""
    customer_id: int | None = None
    day: str = "last"
    payment_terms_days: int = 14
    lines: list[LineIn] = []
    extra_info: list[str] = []
    active: bool = True


def _template_json(t: M.SalesInvoiceTemplate) -> dict:
    return {"id": t.id, "company_id": t.company_id, "key": t.key, "description": t.description,
            "customer_id": t.customer_id, "day": t.day, "payment_terms_days": t.payment_terms_days,
            "lines": t.lines or [], "extra_info": t.extra_info or [], "active": t.active}


@router.get("/sales-invoice-templates")
def list_templates(request: Request = None, db: Session = Depends(get_db)):
    scope = company_svc.scope_ids(db, request)
    return [_template_json(t) for t in db.query(M.SalesInvoiceTemplate)
            .filter(M.SalesInvoiceTemplate.company_id.in_(scope)).order_by(M.SalesInvoiceTemplate.key).all()]


@router.post("/sales-invoice-templates")
def create_template(body: TemplateIn, db: Session = Depends(get_db)):
    svc.issuing_company(db, body.company_id)
    try:
        A.lines([ln.model_dump() for ln in body.lines])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    t = M.SalesInvoiceTemplate(**{**body.model_dump(), "lines": [ln.model_dump() for ln in body.lines]})
    db.add(t)
    db.flush()
    audit(db, "sales_template.create", "sales_invoice_template", t.id, {"key": t.key})
    db.commit()
    return _template_json(t)


@router.patch("/sales-invoice-templates/{template_id}")
def update_template(template_id: int, body: dict, db: Session = Depends(get_db)):
    t = db.get(M.SalesInvoiceTemplate, template_id)
    if t is None:
        raise HTTPException(404, "template not found")
    allowed = {"description", "customer_id", "day", "payment_terms_days", "lines", "extra_info", "active"}
    for k, v in body.items():
        if k not in allowed:
            raise HTTPException(422, f"{k} cannot be changed")
        if k == "lines":
            try:
                A.lines(v)
            except ValueError as e:
                raise HTTPException(422, str(e)) from e
        setattr(t, k, v)
    audit(db, "sales_template.update", "sales_invoice_template", t.id, {"key": t.key, "fields": sorted(body)})
    db.commit()
    return _template_json(t)


class GenerateIn(BaseModel):
    month: str


@router.post("/sales-invoice-templates/{template_id}/generate")
def generate(template_id: int, body: GenerateIn, db: Session = Depends(get_db)):
    t = db.get(M.SalesInvoiceTemplate, template_id)
    if t is None:
        raise HTTPException(404, "template not found")
    inv = svc.generate(db, t, body.month, actor=acting_name())
    audit(db, "sales_invoice.create", "sales_invoice", inv.id,
          {"number": inv.number, "template": t.key, "month": body.month})
    db.commit()
    return svc.invoice_json(db, inv, full=True)


@router.get("/sales-products")
def list_products(request: Request = None, db: Session = Depends(get_db)):
    scope = company_svc.scope_ids(db, request)
    return [{"id": p.id, "company_id": p.company_id, "name": p.name, "unit_net": str(p.unit_net),
             "vat_rate": p.vat_rate, "unit": p.unit, "source": p.source}
            for p in db.query(M.SalesProduct).filter(M.SalesProduct.company_id.in_(scope))
            .order_by(M.SalesProduct.name).all()]


# --------------------------------------------------------------- import

@router.post("/sales-invoices/import")
async def import_register(company_id: int, dry_run: bool = True,
                          register_file: UploadFile | None = File(default=None),
                          clients_file: UploadFile | None = File(default=None),
                          recurring_file: UploadFile | None = File(default=None),
                          products_file: UploadFile | None = File(default=None),
                          db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """7Sigma's script files, once: `register_file` = `rejestr.json`,
    `clients_file` = `klienci.json`, `recurring_file` = `cykliczne.json`,
    `products_file` = `produkty.json`. Dry run by default."""
    async def read(f):
        return json.loads(await f.read()) if f is not None else None

    res = svc.import_register(db, company_id, register=await read(register_file),
                              clients=await read(clients_file), recurring=await read(recurring_file),
                              products=await read(products_file), dry_run=dry_run)
    if dry_run:
        db.rollback()
    else:
        audit(db, "sales_invoice.import", "sales_invoice", None,
              {"documents": res["documents"], "customers": len(res["customers"]["created"]),
               "templates": len(res["templates"]), "products": len(res["products"])})
        db.commit()
    return res
