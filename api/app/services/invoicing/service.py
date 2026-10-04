"""Writing, issuing, correcting and importing sales invoices (decision 0066).

The flow is 7Sigma's script's, with the platform as the register:

1. A VAT, correction or advance invoice starts as a `draft` with the next
   number of its series. Its FA(3) XML is checked against the schema when it
   is downloaded.
2. Somebody uploads the XML in the KSeF Taxpayer Application on the invoice's
   date (later, and KSeF marks it offline).
3. The invoice is `issued` when KSeF has it: the KSeF number is recorded — by
   the KSeF read-out once that runs for the company, or by a person — with the
   hash of the official XML, which puts the verification QR code on the PDF.

A proforma never goes to KSeF and is issued when it is written.

Only a company with `issues_invoices` gets invoices written here. 9SIGMA has
its own invoicing system (user, 2026-10-04).
"""
from __future__ import annotations

import base64
import calendar
import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ... import models as M
from .. import companies as C
from . import amounts as A
from . import fa3, numbering

KINDS = ("vat", "proforma", "correction", "advance")
EDITABLE = ("draft",)


def _today() -> str:
    return date.today().isoformat()


def ksef_hash(xml: bytes) -> str:
    """SHA-256 of the invoice file in base64url without padding: the last part
    of the KSeF verification link."""
    return base64.urlsafe_b64encode(hashlib.sha256(xml).digest()).decode().rstrip("=")


def issuing_company(db: Session, company_id: int) -> M.Company:
    c = C.get(db, company_id)
    if not c.issues_invoices:
        raise HTTPException(409, f"{c.name} does not issue its invoices on this platform "
                                 "(it has its own system); its invoices are only read from KSeF")
    return c


def seller_of(c: M.Company) -> dict:
    return {"name": c.legal_name or c.name, "address_l1": c.address_l1, "address_l2": c.address_l2,
            "nip": c.nip, "country": c.country or "PL", "issuer": c.issuer_name}


def bank_of(c: M.Company) -> dict:
    return {"name": c.bank_name, "address": "", "account": c.bank_account, "swift": c.swift}


def buyer_of(cust: M.Customer) -> dict:
    return {"name": cust.legal_name or cust.name, "address_l1": cust.address_l1,
            "address_l2": cust.address_l2, "nip": re.sub(r"\D", "", cust.tax_id or ""),
            "country": cust.country or "PL"}


def _columns(inv: M.SalesInvoice) -> None:
    """Copy the figures lists and the books read out of the document."""
    b = inv.body or {}
    t = b.get("totals") or {}
    inv.net_total = A.d2(t.get("net") or 0)
    inv.vat_total = A.d2(t.get("vat") or 0)
    inv.gross_total = A.d2(t.get("gross") or 0)
    buyer = b.get("buyer") or {}
    inv.buyer_nip = re.sub(r"\D", "", buyer.get("nip") or "")
    inv.buyer_name = (buyer.get("name") or "")[:512]
    pay = b.get("payment") or {}
    inv.due_date = pay.get("due_date") or ""
    if inv.kind == "correction":
        before = (b.get("correction") or {}).get("before_totals") or {"gross": "0"}
        inv.amount_due = A.d2(Decimal(t.get("gross") or 0) - Decimal(before.get("gross") or 0))
    elif pay.get("paid"):
        inv.amount_due = A.d2(0)
    else:
        inv.amount_due = inv.gross_total


def _payment(raw: dict | None, issue: str, terms_days: int) -> dict:
    raw = raw or {}
    paid = bool(raw.get("paid"))
    due = raw.get("due_date")
    if not paid and not due:
        due = (date.fromisoformat(issue) + timedelta(days=int(raw.get("terms_days") or terms_days))).isoformat()
    return {"due_date": None if paid else due, "method": raw.get("method") or "przelew", "paid": paid,
            "paid_date": (raw.get("paid_date") or issue) if paid else None, "note": raw.get("note") or ""}


def _buyer(db: Session, customer_id: int | None, buyer: dict | None) -> tuple[int | None, dict]:
    if buyer and (buyer.get("name") or "").strip():
        return customer_id, {"name": buyer["name"].strip(), "address_l1": buyer.get("address_l1") or "",
                             "address_l2": buyer.get("address_l2") or "",
                             "nip": re.sub(r"\D", "", buyer.get("nip") or ""),
                             "country": (buyer.get("country") or "PL").upper(),
                             "vat_eu": buyer.get("vat_eu") or ""}
    cust = db.get(M.Customer, customer_id) if customer_id else None
    if cust is None:
        raise HTTPException(422, "name the buyer: a customer, or the buyer's name and address")
    return cust.id, buyer_of(cust)


def create(db: Session, *, company_id: int, kind: str, customer_id: int | None = None,
           buyer: dict | None = None, issue_date: str = "", sale_date: str = "",
           lines: list[dict] | None = None, payment: dict | None = None,
           extra_info: list[str] | None = None, place: str = "", title: str = "",
           number: str = "", split_payment: bool = False, order_lines: list[dict] | None = None,
           advance_gross=None, template_key: str = "", actor: str = "") -> M.SalesInvoice:
    """A new invoice: a draft (VAT, correction, advance) or an issued proforma."""
    if kind not in ("vat", "proforma", "advance"):
        raise HTTPException(422, "a new invoice is a vat, proforma or advance invoice; a correction "
                                 "is made from the invoice it corrects")
    c = issuing_company(db, company_id)
    issue = (issue_date or _today())[:10]
    try:
        day = date.fromisoformat(issue)
    except ValueError as e:
        raise HTTPException(422, "issue_date must be an ISO date") from e
    customer_id, buyer_s = _buyer(db, customer_id, buyer)
    terms = (db.get(M.Customer, customer_id).payment_terms_days if customer_id
             and db.get(M.Customer, customer_id) else c.payment_terms_days) or 14
    try:
        positions = A.lines(lines or [])
        order = None
        if kind == "advance":
            olines = A.lines(order_lines or [])
            if not olines:
                raise ValueError("an advance invoice names the order it is paid against (order_lines)")
            otot = A.totals(olines)
            if advance_gross is None:
                raise ValueError("an advance invoice states the advance received (advance_gross)")
            totals = fa3.advance_totals(otot, advance_gross)
            order = {"lines": olines, "totals": otot}
            positions = []
        else:
            if not positions:
                raise ValueError("an invoice has at least one position")
            totals = A.totals(positions)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    num = (number or "").strip() or numbering.next_number(db, c.id, kind, day)
    if numbering.taken(db, c.id, kind, num):
        raise HTTPException(409, f"number {num} is already used in this series")
    pay = _payment(payment, issue, terms)
    if kind == "advance":
        pay["paid"] = True
        pay["paid_date"] = pay["paid_date"] or (sale_date or issue)
        pay["due_date"] = None
    body = {"title": title or {"proforma": "FAKTURA PROFORMA", "advance": "FAKTURA ZALICZKOWA"}.get(kind, "FAKTURA VAT"),
            "place": place or c.place_of_issue, "seller": seller_of(c), "buyer": buyer_s,
            "lines": positions, "totals": totals, "payment": pay, "bank": bank_of(c),
            "extra_info": [x for x in (extra_info or []) if (x or "").strip()],
            "split_payment": bool(split_payment), "issued_by": c.issuer_name, "notes": []}
    if order:
        body["order"] = order
    inv = M.SalesInvoice(company_id=c.id, kind=kind, status="issued" if kind == "proforma" else "draft",
                         number=num, issue_date=issue, sale_date=(sale_date or issue)[:10],
                         customer_id=customer_id, currency="PLN", body=body, source="platform",
                         template_key=template_key, created_by=actor[:100])
    _columns(inv)
    if pay.get("paid"):
        inv.paid, inv.paid_date = True, pay.get("paid_date") or ""
    db.add(inv)
    db.flush()
    return inv


def update(db: Session, inv: M.SalesInvoice, fields: dict) -> M.SalesInvoice:
    """Change a draft (or a proforma, which is informational). An issued
    invoice changes only by a correction."""
    if not (inv.status == "draft" or inv.kind == "proforma"):
        raise HTTPException(409, f"{inv.number} is {inv.status}: an issued invoice is changed by a "
                                 "correction, never in place")
    b = dict(inv.body or {})
    try:
        if fields.get("issue_date"):
            date.fromisoformat(fields["issue_date"][:10])
            inv.issue_date = fields["issue_date"][:10]
        if fields.get("sale_date"):
            inv.sale_date = fields["sale_date"][:10]
        if "number" in fields and fields["number"] and fields["number"] != inv.number:
            if numbering.taken(db, inv.company_id, inv.kind, fields["number"], exclude_id=inv.id):
                raise HTTPException(409, f"number {fields['number']} is already used in this series")
            inv.number = fields["number"].strip()
        if fields.get("customer_id") or fields.get("buyer"):
            inv.customer_id, b["buyer"] = _buyer(db, fields.get("customer_id"), fields.get("buyer"))
        if "lines" in fields and inv.kind != "advance":
            b["lines"] = A.lines(fields["lines"])
            if not b["lines"]:
                raise ValueError("an invoice has at least one position")
            b["totals"] = A.totals(b["lines"])
        if inv.kind == "advance" and ("order_lines" in fields or "advance_gross" in fields):
            olines = A.lines(fields.get("order_lines") or (b.get("order") or {}).get("lines") or [])
            otot = A.totals(olines)
            gross = fields.get("advance_gross", (b.get("totals") or {}).get("gross"))
            b["order"] = {"lines": olines, "totals": otot}
            b["totals"] = fa3.advance_totals(otot, gross)
        if "payment" in fields:
            terms = 14
            b["payment"] = _payment(fields["payment"], inv.issue_date, terms)
        for k in ("extra_info", "place", "title", "split_payment"):
            if k in fields:
                b[k] = fields[k]
        if inv.kind == "correction" and "correction" in fields:
            cor = dict(b.get("correction") or {})
            for k in ("reason", "text_before", "text_after"):
                if k in fields["correction"]:
                    cor[k] = fields["correction"][k]
            b["correction"] = cor
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    inv.body = b
    _columns(inv)
    inv.paid = bool((b.get("payment") or {}).get("paid"))
    inv.paid_date = (b.get("payment") or {}).get("paid_date") or ""
    db.flush()
    return inv


def cancel(db: Session, inv: M.SalesInvoice) -> None:
    if inv.status != "draft":
        raise HTTPException(409, f"{inv.number} is {inv.status}; only a draft never sent to KSeF is cancelled")
    inv.status = "cancelled"
    db.flush()


def issue(db: Session, inv: M.SalesInvoice, *, ksef_number: str, xml: bytes | None = None,
          received_at: str = "") -> M.SalesInvoice:
    """KSeF accepted the draft: record its KSeF number, and with the official
    XML its hash, which prints the verification QR code."""
    from .. import storage

    if inv.kind == "proforma":
        raise HTTPException(422, "a proforma never goes to KSeF")
    if inv.status not in ("draft", "issued"):
        raise HTTPException(409, f"{inv.number} is {inv.status}")
    num = (ksef_number or "").strip()
    if not re.fullmatch(r"\d{10}-\d{8}-[0-9A-F]{12}-[0-9A-F]{2}", num):
        raise HTTPException(422, "a KSeF number looks like 8513262910-20261004-0123456789AB-CD")
    inv.ksef_number = num
    inv.ksef_received_at = received_at or ""
    if xml:
        inv.ksef_hash = ksef_hash(xml)
        key = f"sales-invoices/{inv.company_id}/{inv.id}/ksef-{num}.xml"
        storage.put_bytes(key, xml, "application/xml")
        inv.official_xml_key = key
    inv.status = "issued"
    db.flush()
    return inv


def mark_paid(db: Session, inv: M.SalesInvoice, paid_date: str) -> M.SalesInvoice:
    """The money arrived. Bookkeeping on the platform's record; the issued
    document does not change."""
    date.fromisoformat(paid_date[:10])
    inv.paid, inv.paid_date = True, paid_date[:10]
    inv.amount_due = A.d2(0)
    db.flush()
    return inv


def correct(db: Session, inv: M.SalesInvoice, *, issue_date: str = "", reason: str = "",
            actor: str = "") -> M.SalesInvoice:
    """A correction draft of an issued invoice: its positions before, and a copy
    of them to change."""
    if inv.status not in ("issued", "error") or inv.kind not in ("vat", "advance"):
        raise HTTPException(409, "only an issued VAT or advance invoice is corrected")
    c = issuing_company(db, inv.company_id)
    issue = (issue_date or _today())[:10]
    day = date.fromisoformat(issue)
    b = inv.body or {}
    before = b.get("lines") or []
    body = {"title": "FAKTURA KORYGUJĄCA", "place": b.get("place") or c.place_of_issue,
            "seller": seller_of(c), "buyer": b.get("buyer") or {},
            "lines": [dict(p) for p in before], "totals": b.get("totals") or A.totals(before),
            "payment": {"due_date": (day + timedelta(days=c.payment_terms_days or 14)).isoformat(),
                        "method": "przelew", "paid": False, "paid_date": None, "note": ""},
            "bank": bank_of(c), "extra_info": [], "issued_by": c.issuer_name, "notes": [],
            "correction": {"of_id": inv.id, "of_number": inv.number, "of_date": inv.issue_date,
                           "of_ksef": inv.ksef_number, "reason": reason, "before_lines": before,
                           "before_totals": b.get("totals") or A.totals(before)}}
    kor = M.SalesInvoice(company_id=c.id, kind="correction", status="draft",
                         number=numbering.next_number(db, c.id, "correction", day), issue_date=issue,
                         sale_date=inv.sale_date, customer_id=inv.customer_id, currency=inv.currency,
                         corrects_id=inv.id, body=body, source="platform", created_by=actor[:100])
    _columns(kor)
    db.add(kor)
    db.flush()
    return kor


def generate(db: Session, tpl: M.SalesInvoiceTemplate, month: str, actor: str = "") -> M.SalesInvoice:
    """The month's draft of a recurring invoice, dated the template's day."""
    try:
        y, m = (int(x) for x in month.split("-"))
        day = date(y, m, calendar.monthrange(y, m)[1] if tpl.day == "last" else int(tpl.day))
    except ValueError as e:
        raise HTTPException(422, "month is YYYY-MM") from e
    if not tpl.active:
        raise HTTPException(409, f"the recurring invoice {tpl.key!r} is not active")
    dup = (db.query(M.SalesInvoice)
           .filter(M.SalesInvoice.company_id == tpl.company_id, M.SalesInvoice.template_key == tpl.key,
                   M.SalesInvoice.issue_date == day.isoformat(), M.SalesInvoice.status != "cancelled").first())
    if dup is not None:
        raise HTTPException(409, f"{tpl.key} for {month} is already {dup.number} ({dup.status})")
    return create(db, company_id=tpl.company_id, kind="vat", customer_id=tpl.customer_id,
                  issue_date=day.isoformat(), sale_date=day.isoformat(), lines=tpl.lines or [],
                  payment={"terms_days": tpl.payment_terms_days}, extra_info=tpl.extra_info or [],
                  template_key=tpl.key, actor=actor)


def invoice_json(db: Session, inv: M.SalesInvoice, full: bool = False) -> dict:
    out = {"id": inv.id, "company_id": inv.company_id, "kind": inv.kind, "status": inv.status,
           "number": inv.number, "issue_date": inv.issue_date, "sale_date": inv.sale_date,
           "customer_id": inv.customer_id, "buyer_nip": inv.buyer_nip, "buyer_name": inv.buyer_name,
           "currency": inv.currency, "net_total": str(inv.net_total), "vat_total": str(inv.vat_total),
           "gross_total": str(inv.gross_total), "amount_due": str(inv.amount_due),
           "due_date": inv.due_date, "paid": inv.paid, "paid_date": inv.paid_date,
           "corrects_id": inv.corrects_id, "template_key": inv.template_key,
           "ksef_number": inv.ksef_number, "has_qr": bool(inv.ksef_number and inv.ksef_hash),
           "source": inv.source, "created_by": inv.created_by,
           "overdue": bool(not inv.paid and inv.due_date and inv.due_date < _today()
                           and inv.status == "issued" and inv.kind != "proforma")}
    if full:
        out["body"] = inv.body
        out["corrected_by"] = [{"id": k.id, "number": k.number, "status": k.status}
                               for k in db.query(M.SalesInvoice)
                               .filter(M.SalesInvoice.corrects_id == inv.id).all()]
    return out


# ================================================================ import

_KIND = {"vat": "vat", "proforma": "proforma", "korekta": "correction", "zaliczka": "advance"}
_STATUS = {"wystawiona": "issued", "szkic": "draft", "błędna": "error"}


def _party_from(p: dict | None) -> dict:
    p = p or {}
    return {"name": p.get("nazwa") or "", "address_l1": p.get("adres1") or "",
            "address_l2": p.get("adres2") or "", "nip": re.sub(r"\D", "", p.get("nip") or ""),
            "country": "PL"}


def _line_from(p: dict) -> dict:
    """A position exactly as the document printed it."""
    r = p.get("vat_proc")
    try:
        rate = A.rate(r) if r is not None else ""
    except ValueError:
        rate = str(r)
    return {"position": p.get("lp"), "name": p.get("nazwa") or "", "unit": p.get("jm") or "",
            "qty": str(p.get("ilosc") if p.get("ilosc") is not None else ""),
            "unit_net": str(p.get("cena_netto") if p.get("cena_netto") is not None else ""),
            "net": str(p.get("netto") if p.get("netto") is not None else "0"),
            "vat_rate": rate, "vat": str(p.get("vat") if p.get("vat") is not None else "0"),
            "gross": str(p.get("brutto") if p.get("brutto") is not None else "0")}


def _totals_from(s: dict | None) -> dict:
    s = s or {}
    rates = {}
    for r, v in (s.get("stawki") or {}).items():
        try:
            key = A.rate(r)
        except ValueError:
            key = str(r)
        rates[key] = {"net": str(v.get("netto") or 0), "vat": str(v.get("vat") or 0)}
    return {"net": str(s.get("netto") or 0), "vat": str(s.get("vat") or 0),
            "gross": str(s.get("brutto") or 0), "rates": rates}


def from_register(d: dict, company_id: int) -> M.SalesInvoice:
    """One document of 7Sigma's `rejestr.json`, kept as it was issued."""
    pay = d.get("platnosc") or {}
    rb = d.get("rachunek") or {}
    kor = d.get("korekta") or None
    body = {
        "title": d.get("tytul") or "", "place": d.get("miejsce") or "",
        "seller": _party_from(d.get("sprzedawca")), "buyer": _party_from(d.get("nabywca")),
        "lines": [_line_from(p) for p in d.get("pozycje") or []],
        "totals": _totals_from(d.get("sumy")),
        "payment": {"due_date": pay.get("termin"), "method": pay.get("forma") or "",
                    "paid": bool(pay.get("zaplacono")), "paid_date": pay.get("data_zaplaty"),
                    "note": pay.get("opis") or "",
                    "partial": [{"amount": str(z.get("kwota")), "date": z.get("data"), "method": z.get("forma")}
                                for z in pay.get("zaplaty_czesciowe") or []]},
        "bank": {"name": rb.get("bank") or "", "address": rb.get("adres") or "", "account": rb.get("numer") or ""},
        "extra_info": d.get("dodatkowe_informacje") or [], "issued_by": d.get("wystawil") or "",
        "notes": d.get("uwagi") or [], "files": d.get("pliki") or {}, "customer_key": d.get("klient") or "",
    }
    if kor:
        body["correction"] = {"of_number": kor.get("do_faktury") or "", "of_date": kor.get("data_korygowanej") or "",
                              "of_ksef": "", "reason": kor.get("przyczyna") or "",
                              "before_lines": [_line_from(p) for p in kor.get("przed") or []],
                              "before_totals": _totals_from(kor.get("sumy_przed")) if kor.get("sumy_przed") else None,
                              "text_before": kor.get("tresc_przed") or [], "text_after": kor.get("tresc_po") or []}
    if d.get("zaliczki"):
        body["advances"] = [{"number": z.get("numer"), "net": str(z.get("netto")), "vat": str(z.get("vat")),
                             "gross": str(z.get("brutto"))} for z in d["zaliczki"]]
    ks = d.get("ksef") or {}
    inv = M.SalesInvoice(
        company_id=company_id, kind=_KIND.get(d.get("typ"), "vat"),
        status=_STATUS.get(d.get("status"), "issued"), number=d.get("numer") or "",
        issue_date=(d.get("data_wystawienia") or "")[:10], sale_date=(d.get("data_sprzedazy") or "")[:10],
        currency="PLN", ksef_number=ks.get("numer") or "", ksef_hash=ks.get("skrot") or "",
        ksef_received_at=ks.get("data_przyjecia") or "", template_key=d.get("cykliczna") or "",
        source=f"script: {d.get('zrodlo') or ''}"[:40], body=body, created_by="7sigma.py")
    _columns(inv)
    # Amounts stay as printed, the amount due included.
    if d.get("do_zaplaty") is not None:
        inv.amount_due = A.d2(d["do_zaplaty"])
    inv.paid = bool(pay.get("zaplacono"))
    inv.paid_date = pay.get("data_zaplaty") or ""
    return inv


def import_register(db: Session, company_id: int, register: dict | None = None,
                    clients: dict | None = None, recurring: dict | None = None,
                    products: dict | None = None, dry_run: bool = True) -> dict:
    """7Sigma's script files into the platform, once: its buyers, its price list,
    its recurring invoices and every document of its register. Idempotent: a
    document already here (same series, number and date) is skipped, a buyer
    is matched by NIP."""
    issuing_company(db, company_id)
    out: dict = {"dry_run": dry_run, "customers": {"matched": [], "created": []},
                 "documents": {"created": 0, "skipped": 0}, "templates": [], "products": []}
    by_key: dict[str, int] = {}
    for key, k in (clients or {}).items():
        nip = re.sub(r"\D", "", k.get("nip") or "")
        cust = None
        if nip:
            cust = next((c for c in db.query(M.Customer).all()
                         if re.sub(r"\D", "", c.tax_id or "") == nip), None)
        if cust is None:
            name = (k.get("nazwa") or key).strip()
            cust = db.query(M.Customer).filter(M.Customer.name == name).first()
        if cust is None:
            out["customers"]["created"].append(key)
            if dry_run:
                continue
            cust = M.Customer(name=(k.get("nazwa") or key).strip()[:200])
            db.add(cust)
        else:
            out["customers"]["matched"].append({"key": key, "customer": cust.name})
        if not dry_run:
            cust.key = cust.key or key
            cust.legal_name = cust.legal_name or (k.get("nazwa") or "")
            cust.tax_id = cust.tax_id or nip
            cust.address_l1 = cust.address_l1 or (k.get("adres1") or "")
            cust.address_l2 = cust.address_l2 or (k.get("adres2") or "")
            db.flush()
            by_key[key] = cust.id
    seen = {(i.kind, i.number, i.issue_date)
            for i in db.query(M.SalesInvoice).filter_by(company_id=company_id).all()}
    for d in (register or {}).get("dokumenty") or []:
        inv = from_register(d, company_id)
        if (inv.kind, inv.number, inv.issue_date) in seen:
            out["documents"]["skipped"] += 1
            continue
        seen.add((inv.kind, inv.number, inv.issue_date))
        out["documents"]["created"] += 1
        if not dry_run:
            key = (inv.body or {}).get("customer_key")
            inv.customer_id = by_key.get(key) if key else None
            if inv.customer_id is None and inv.buyer_nip:
                inv.customer_id = next((c.id for c in db.query(M.Customer).all()
                                        if re.sub(r"\D", "", c.tax_id or "") == inv.buyer_nip), None)
            db.add(inv)
    for key, t in (recurring or {}).items():
        out["templates"].append(key)
        if dry_run or db.query(M.SalesInvoiceTemplate).filter_by(company_id=company_id, key=key).first():
            continue
        db.add(M.SalesInvoiceTemplate(
            company_id=company_id, key=key, description=t.get("opis") or "",
            customer_id=by_key.get(t.get("klient")), day=str(t.get("dzien") or "last").replace("ostatni", "last"),
            payment_terms_days=int(t.get("termin_dni") or 14),
            lines=[{"name": p["nazwa"], "qty": p.get("ilosc", 1), "unit_net": str(p["cena_netto"]),
                    "vat_rate": str(p.get("vat_proc", 23)), "unit": p.get("jm") or "szt."}
                   for p in t.get("pozycje") or []],
            extra_info=t.get("uwagi") or [],
            # The script marks a retired one in its description only.
            active="NIEAKTYWNA" not in (t.get("opis") or "")))
    for name, p in (products or {}).items():
        out["products"].append(name)
        if dry_run or db.query(M.SalesProduct).filter_by(company_id=company_id, name=name).first():
            continue
        db.add(M.SalesProduct(company_id=company_id, name=name, unit_net=A.d2(p.get("cena_netto") or 0),
                              vat_rate=A.rate(p.get("vat_proc", 23)), unit=p.get("jm") or "szt.",
                              source=p.get("zrodlo") or ""))
    if not dry_run:
        db.flush()
    return out
