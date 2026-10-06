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

What a correction and an advance AMOUNT to is read in one place each, because
three sources write them differently: `correction_difference` and
`advance_amounts`. The books and the amount due use nothing else.
"""
from __future__ import annotations

import base64
import calendar
import copy
import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
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


def _alnum(s: str | None) -> str:
    return re.sub(r"[^0-9A-Za-z+*]", "", s or "").upper()


def party_ids(country: str | None, nip: str | None = "", vat_eu: str | None = "") -> dict:
    """A buyer's tax identity the way FA(3) wants it.

    * A Polish buyer: the NIP, digits only ("PL 521-354-52-23" is 5213545223).
    * A buyer in another EU country: the VAT number WITHOUT its country prefix,
      letters kept (`NrVatUE`; the prefix is `KodUE`): "DE123456789" is
      `vat_eu` "123456789", "ATU12345678" is "U12345678".
    * Anybody else: the tax number as written, letters kept (`NrID`).
    """
    country = (country or "PL").strip().upper() or "PL"
    if country == "PL":
        return {"country": "PL", "nip": re.sub(r"\D", "", nip or vat_eu or ""), "vat_eu": ""}
    prefix = fa3.eu_prefix(country)
    if prefix in fa3.EU:
        num = _alnum(vat_eu) or _alnum(nip)
        return {"country": country, "nip": "", "vat_eu": num.removeprefix(prefix)}
    return {"country": country, "nip": _alnum(nip) or _alnum(vat_eu), "vat_eu": ""}


def buyer_of(cust: M.Customer) -> dict:
    return {"name": cust.legal_name or cust.name, "address_l1": cust.address_l1,
            "address_l2": cust.address_l2, **party_ids(cust.country, cust.tax_id)}


def correction_difference(inv: M.SalesInvoice) -> dict:
    """What a correction changes, after minus before, as totals per rate.

    * A platform correction keeps the state before (`correction.before_totals`)
      and after (`totals`), and so does a script correction that printed both.
    * A correction read from KSeF states the difference itself: FA(3) P_13_x
      and P_15 of a KOR are the difference (`correction.states_difference`).
    * A script correction that printed no amounts before changed text only
      (1/KOR/08/2021): it changes no amount.
    """
    b = inv.body or {}
    cor = b.get("correction") or {}
    totals = b.get("totals") or {}
    if cor.get("before_totals"):
        return A.combine(totals, cor["before_totals"], -1)
    if cor.get("states_difference") or (inv.source or "") == "ksef":
        return A.combine(totals, None)
    return A.combine(None, None)


def corrects_advance(db: Session, inv: M.SalesInvoice) -> bool:
    """Whether a correction corrects an advance invoice (KOR_ZAL)."""
    cor = (inv.body or {}).get("correction") or {}
    if cor.get("of_kind"):
        return cor["of_kind"] == "advance"
    orig = db.get(M.SalesInvoice, inv.corrects_id) if inv.corrects_id else None
    return orig is not None and orig.kind == "advance"


def advance_amounts(inv: M.SalesInvoice) -> dict:
    """The advance itself, net, VAT and gross per rate, whatever wrote it.

    A platform advance keeps the order (`body.order`) apart from the advance
    (`totals`), and FA(3) states the advance in P_13_x and P_15, so an advance
    read from KSeF has it in `totals` too. An advance imported from 7Sigma's
    script printed the ORDER as its positions and totals, and the advance as the
    amount to pay. The import keeps that figure as `body.advance_gross`, apart
    from `amount_due`, which a recorded payment may change; the net and VAT are
    taken from that gross over the order's rates (art. 106f ust. 1 pkt 3), as a
    new advance is computed."""
    b = inv.body or {}
    totals = b.get("totals") or {}
    if b.get("order") or not (inv.source or "").startswith("script"):
        return totals
    printed = b.get("advance_gross")
    gross = Decimal(str(printed if printed not in (None, "") else (inv.amount_due or 0)))
    if gross <= 0 or not totals.get("rates") or gross == Decimal(str(totals.get("gross") or 0)):
        return totals
    try:
        return fa3.advance_totals(totals, gross)
    except (ValueError, ArithmeticError):
        return totals


def _columns(inv: M.SalesInvoice) -> None:
    """Copy the figures lists and the books read out of the document."""
    b = inv.body or {}
    t = b.get("totals") or {}
    inv.net_total = A.d2(t.get("net") or 0)
    inv.vat_total = A.d2(t.get("vat") or 0)
    inv.gross_total = A.d2(t.get("gross") or 0)
    buyer = b.get("buyer") or {}
    inv.buyer_nip = re.sub(r"\D", "", buyer.get("nip") or buyer.get("vat_eu") or "")
    inv.buyer_name = (buyer.get("name") or "")[:512]
    pay = b.get("payment") or {}
    inv.due_date = pay.get("due_date") or ""
    if inv.kind == "correction":
        inv.amount_due = A.d2(correction_difference(inv)["gross"])
    elif pay.get("paid") or inv.paid:
        # A payment recorded on the platform (`mark_paid`) leaves the document
        # alone, so `inv.paid` counts as much as the document's own payment.
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
                             **party_ids(buyer.get("country"), buyer.get("nip"), buyer.get("vat_eu"))}
    cust = db.get(M.Customer, customer_id) if customer_id else None
    if cust is None:
        raise HTTPException(422, "name the buyer: a customer, or the buyer's name and address")
    return cust.id, buyer_of(cust)


def _exemption(basis: str | None) -> dict | None:
    """The legal basis of a VAT exemption, printed in FA(3) P_19A."""
    basis = (basis or "").strip()
    return {"basis": basis[:240], "law": "A"} if basis else None


def _insert(db: Session, inv: M.SalesInvoice, renumber=None) -> None:
    """Write a new numbered document. Two writers can compute the same next
    number at once; the unique index refuses the second (decision 0066). An
    automatic number (`renumber` given) is then taken again, a typed one is
    refused."""
    for attempt in range(3):
        try:
            with db.begin_nested():
                db.add(inv)
                db.flush()
            return
        except IntegrityError:
            if renumber is None or attempt == 2:
                raise HTTPException(409, f"number {inv.number} is already used in this series") from None
            inv.number = renumber()


def create(db: Session, *, company_id: int, kind: str, customer_id: int | None = None,
           buyer: dict | None = None, issue_date: str = "", sale_date: str = "",
           lines: list[dict] | None = None, payment: dict | None = None,
           extra_info: list[str] | None = None, place: str = "", title: str = "",
           number: str = "", split_payment: bool = False, order_lines: list[dict] | None = None,
           advance_gross=None, template_key: str = "", template_month: str = "",
           exemption_basis: str = "", actor: str = "") -> M.SalesInvoice:
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
    typed = (number or "").strip()
    num = typed or numbering.next_number(db, c.id, kind, day)
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
    if _exemption(exemption_basis):
        body["exemption"] = _exemption(exemption_basis)
    if template_month:
        # The month a recurring invoice was written for, whatever its date
        # becomes later (`generate` refuses a second draft for it).
        body["template_month"] = template_month
    inv = M.SalesInvoice(company_id=c.id, kind=kind, status="issued" if kind == "proforma" else "draft",
                         number=num, issue_date=issue, sale_date=(sale_date or issue)[:10],
                         customer_id=customer_id, currency="PLN", body=body, source="platform",
                         template_key=template_key, created_by=actor[:100])
    _columns(inv)
    if pay.get("paid"):
        inv.paid, inv.paid_date = True, pay.get("paid_date") or ""
    _insert(db, inv, None if typed else (lambda: numbering.next_number(db, c.id, kind, day)))
    return inv


def _terms(db: Session, inv: M.SalesInvoice) -> int:
    cust = db.get(M.Customer, inv.customer_id) if inv.customer_id else None
    if cust is not None and cust.payment_terms_days:
        return cust.payment_terms_days
    comp = db.get(M.Company, inv.company_id)
    return (comp.payment_terms_days if comp is not None else 0) or 14


def update(db: Session, inv: M.SalesInvoice, fields: dict) -> M.SalesInvoice:
    """Change a draft (or a proforma, which is informational). An issued
    invoice changes only by a correction.

    * **A new issue date in another month renumbers a draft**: its number
      names the month, and the next one of the new month replaces it. A typed
      `number` wins over that.
    * **The sale date of a VAT draft follows its issue date** when it was the
      same day and no sale date is given. A correction keeps the sale date of
      the invoice it corrects, and an advance the day the money came.
    * **A payment recorded with `mark_paid` stays** unless `payment` is sent.
    """
    if not (inv.status == "draft" or inv.kind == "proforma"):
        raise HTTPException(409, f"{inv.number} is {inv.status}: an issued invoice is changed by a "
                                 "correction, never in place")
    b = copy.deepcopy(inv.body or {})
    cor = b.get("correction") or {}
    advance_like = inv.kind == "advance" or (inv.kind == "correction" and cor.get("of_kind") == "advance")
    old_issue = inv.issue_date
    renumber = False
    try:
        if fields.get("issue_date"):
            new_issue = date.fromisoformat(fields["issue_date"][:10]).isoformat()
            if new_issue != old_issue:
                inv.issue_date = new_issue
                if not fields.get("sale_date") and inv.kind in ("vat", "proforma") and inv.sale_date == old_issue:
                    inv.sale_date = new_issue
                renumber = inv.status == "draft" and new_issue[:7] != (old_issue or "")[:7]
        if fields.get("sale_date"):
            inv.sale_date = date.fromisoformat(fields["sale_date"][:10]).isoformat()
        typed = (fields.get("number") or "").strip()
        if typed and typed != inv.number:
            if numbering.taken(db, inv.company_id, inv.kind, typed, exclude_id=inv.id):
                raise HTTPException(409, f"number {typed} is already used in this series")
            inv.number = typed
        elif renumber:
            inv.number = numbering.next_number(db, inv.company_id, inv.kind,
                                               date.fromisoformat(inv.issue_date), exclude_id=inv.id)
        if fields.get("customer_id") or fields.get("buyer"):
            inv.customer_id, b["buyer"] = _buyer(db, fields.get("customer_id"), fields.get("buyer"))
        if "lines" in fields and not advance_like:
            b["lines"] = A.lines(fields["lines"])
            if not b["lines"]:
                raise ValueError("an invoice has at least one position")
            b["totals"] = A.totals(b["lines"])
        if advance_like and ("order_lines" in fields or "advance_gross" in fields):
            olines = A.lines(fields.get("order_lines") or (b.get("order") or {}).get("lines") or [])
            if not olines:
                raise ValueError("an advance names the order it is paid against (order_lines)")
            otot = A.totals(olines)
            gross = fields.get("advance_gross")
            if gross is None:
                gross = (b.get("totals") or {}).get("gross")
            b["order"] = {"lines": olines, "totals": otot}
            b["totals"] = fa3.advance_totals(otot, gross)
        if "payment" in fields:
            b["payment"] = _payment(fields["payment"], inv.issue_date, _terms(db, inv))
        for k in ("extra_info", "place", "title", "split_payment"):
            if k in fields:
                b[k] = fields[k]
        if "exemption_basis" in fields:
            if _exemption(fields["exemption_basis"]):
                b["exemption"] = _exemption(fields["exemption_basis"])
            else:
                b.pop("exemption", None)
        if inv.kind == "correction" and "correction" in fields:
            cor = dict(b.get("correction") or {})
            for k in ("reason", "text_before", "text_after"):
                if k in fields["correction"]:
                    cor[k] = fields["correction"][k]
            b["correction"] = cor
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    inv.body = b
    if "payment" in fields:
        inv.paid = bool(b["payment"].get("paid"))
        inv.paid_date = b["payment"].get("paid_date") or ""
    _columns(inv)
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        raise HTTPException(409, f"number {inv.number} was just taken by another invoice; try again") from None
    return inv


def cancel(db: Session, inv: M.SalesInvoice) -> None:
    if inv.status != "draft":
        raise HTTPException(409, f"{inv.number} is {inv.status}; only a draft never sent to KSeF is cancelled")
    inv.status = "cancelled"
    db.flush()


KSEF_NUMBER = re.compile(r"(\d{10})-\d{8}-[0-9A-F]{12}-[0-9A-F]{2}")


def issue(db: Session, inv: M.SalesInvoice, *, ksef_number: str, xml: bytes | None = None,
          received_at: str = "") -> M.SalesInvoice:
    """KSeF accepted the draft: record its KSeF number, and with the official
    XML its hash, which prints the verification QR code.

    Refused: a KSeF number of another seller (its first part is the seller's
    NIP), a file that is another invoice (its P_2 or seller NIP differ), a
    file whose hash is not the one KSeF stated, and a second KSeF number over
    one already recorded."""
    from .. import storage
    from ..ksef.parse import parse

    if inv.kind == "proforma":
        raise HTTPException(422, "a proforma never goes to KSeF")
    if inv.status not in ("draft", "issued"):
        raise HTTPException(409, f"{inv.number} is {inv.status}")
    num = (ksef_number or "").strip()
    m = KSEF_NUMBER.fullmatch(num)
    if m is None:
        raise HTTPException(422, "a KSeF number looks like 8513262910-20261004-0123456789AB-CD")
    seller_nip = re.sub(r"\D", "", ((inv.body or {}).get("seller") or {}).get("nip") or "") \
        or re.sub(r"\D", "", C.get(db, inv.company_id).nip or "")
    if m.group(1) != seller_nip:
        raise HTTPException(422, f"KSeF number {num} was given to seller NIP {m.group(1)}; "
                                 f"this invoice's seller is NIP {seller_nip}")
    if inv.ksef_number and inv.ksef_number != num:
        raise HTTPException(409, f"{inv.number} is already in KSeF as {inv.ksef_number}; another KSeF "
                                 "number is never recorded over it")
    if xml:
        try:
            p = parse(xml)
        except Exception as e:  # any unreadable file is the caller's mistake
            raise HTTPException(422, f"the file is not an FA(3) invoice: {e}") from e
        if numbering.norm(p["number"]) != numbering.norm(inv.number):
            raise HTTPException(422, f"the XML is invoice {p['number']!r}, not {inv.number!r}")
        xml_nip = re.sub(r"\D", "", (p["body"].get("seller") or {}).get("nip") or "")
        if xml_nip != seller_nip:
            raise HTTPException(422, f"the XML's seller is NIP {xml_nip}, not {seller_nip}")
        if inv.ksef_hash and inv.ksef_number == num and ksef_hash(xml) != inv.ksef_hash:
            raise HTTPException(422, f"this is not the file KSeF holds for {num}: its hash differs")
    inv.ksef_number = num
    inv.ksef_received_at = received_at or inv.ksef_received_at or ""
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
    document does not change. An invoice already paid is refused, and a
    document imported from the script keeps the amount due it printed."""
    try:
        day = date.fromisoformat((paid_date or "")[:10]).isoformat()
    except ValueError as e:
        raise HTTPException(422, "paid_date must be an ISO date") from e
    if inv.paid:
        raise HTTPException(409, f"{inv.number} is already paid ({inv.paid_date or 'date not recorded'})")
    inv.paid, inv.paid_date = True, day
    if not (inv.source or "").startswith("script"):
        inv.amount_due = A.d2(0)
    db.flush()
    return inv


def corrections_of(db: Session, inv: M.SalesInvoice) -> list[M.SalesInvoice]:
    """The corrections of an invoice that are not cancelled, oldest first."""
    return (db.query(M.SalesInvoice)
            .filter(M.SalesInvoice.corrects_id == inv.id, M.SalesInvoice.kind == "correction",
                    M.SalesInvoice.status != "cancelled")
            .order_by(M.SalesInvoice.issue_date, M.SalesInvoice.id).all())


def _full_state(kor: M.SalesInvoice) -> bool:
    """Whether a correction holds the state after it whole (its positions and
    totals), not only a difference or a text."""
    cor = (kor.body or {}).get("correction") or {}
    return bool(cor.get("before_totals")) and not cor.get("states_difference")


def correct(db: Session, inv: M.SalesInvoice, *, issue_date: str = "", reason: str = "",
            actor: str = "") -> M.SalesInvoice:
    """A correction draft of an issued invoice: its state before, and a copy of
    it to change. A correction of an ADVANCE copies the order and the advance
    instead (KOR_ZAL): it is changed with `order_lines` and `advance_gross`,
    like the advance itself.

    The state before is the invoice AS CORRECTED so far: its totals plus the
    difference of every issued correction of it, and the positions (or the
    order) of the latest one. Refused while a draft correction of the invoice
    is open, and when the latest correction states only a difference or a text
    (read from KSeF, or imported), because its positions after are unknown."""
    if inv.status not in ("issued", "error") or inv.kind not in ("vat", "advance"):
        raise HTTPException(409, "only an issued VAT or advance invoice is corrected")
    c = issuing_company(db, inv.company_id)
    issue = (issue_date or _today())[:10]
    try:
        day = date.fromisoformat(issue)
    except ValueError as e:
        raise HTTPException(422, "issue_date must be an ISO date") from e
    prior = corrections_of(db, inv)
    open_draft = next((k for k in prior if k.status == "draft"), None)
    if open_draft is not None:
        raise HTTPException(409, f"{inv.number} already has the draft correction {open_draft.number}; "
                                 "issue or cancel it first")
    issued = [k for k in prior if k.status in ("issued", "error")]
    latest = issued[-1] if issued else None
    if latest is not None and not _full_state(latest):
        raise HTTPException(409, f"the latest correction of {inv.number}, {latest.number}, states only a "
                                 "difference or a text, so the positions after it are unknown here; write "
                                 "the next correction in the KSeF application")
    b = copy.deepcopy(inv.body or {})
    lb = copy.deepcopy(latest.body or {}) if latest is not None else {}
    cor = {"of_id": inv.id, "of_number": inv.number, "of_date": inv.issue_date, "of_ksef": inv.ksef_number,
           "of_kind": inv.kind, "reason": reason}
    extra: dict = {}
    if inv.kind == "advance":
        before = advance_amounts(inv)
        order = lb.get("order") or b.get("order") or {"lines": b.get("lines") or [], "totals": b.get("totals") or {}}
    else:
        before = b.get("totals") or A.totals(b.get("lines") or [])
        before_lines = (lb.get("lines") if latest is not None else b.get("lines")) or []
    for k in issued:
        before = A.combine(before, correction_difference(k))
    if inv.kind == "advance":
        cor.update(before_lines=[], before_totals=before, before_order=copy.deepcopy(order))
        lines, totals, extra["order"] = [], before, copy.deepcopy(order)
    else:
        cor.update(before_lines=before_lines, before_totals=before)
        lines, totals = [dict(p) for p in before_lines], before
    body = {"title": "FAKTURA KORYGUJĄCA", "place": b.get("place") or c.place_of_issue,
            "seller": seller_of(c), "buyer": b.get("buyer") or {}, "lines": lines, "totals": totals,
            "payment": {"due_date": (day + timedelta(days=c.payment_terms_days or 14)).isoformat(),
                        "method": "przelew", "paid": False, "paid_date": None, "note": ""},
            "bank": bank_of(c), "extra_info": [], "issued_by": c.issuer_name, "notes": [],
            "correction": cor, **extra}
    if b.get("exemption"):
        body["exemption"] = b["exemption"]
    kor = M.SalesInvoice(company_id=c.id, kind="correction", status="draft",
                         number=numbering.next_number(db, c.id, "correction", day), issue_date=issue,
                         sale_date=inv.sale_date, customer_id=inv.customer_id, currency=inv.currency,
                         corrects_id=inv.id, body=body, source="platform", created_by=actor[:100])
    _columns(kor)
    _insert(db, kor, lambda: numbering.next_number(db, c.id, "correction", day))
    return kor


def generate(db: Session, tpl: M.SalesInvoiceTemplate, month: str, actor: str = "") -> M.SalesInvoice:
    """The month's draft of a recurring invoice, dated the template's day, once
    per month. The month a document was written FOR (`body.template_month`)
    decides: a draft written for April and re-dated into May is April's, and
    May is still free. A document without it (the imported history) counts for
    the month of its issue date."""
    try:
        y, m = (int(x) for x in month.split("-"))
        day = date(y, m, calendar.monthrange(y, m)[1] if tpl.day == "last" else int(tpl.day))
    except ValueError as e:
        raise HTTPException(422, "month is YYYY-MM") from e
    if not tpl.active:
        raise HTTPException(409, f"the recurring invoice {tpl.key!r} is not active")
    ym = f"{y:04d}-{m:02d}"
    # One writer per template: a second click waits here and then sees the first draft.
    db.query(M.SalesInvoiceTemplate).filter(M.SalesInvoiceTemplate.id == tpl.id).with_for_update().one()
    written_for = M.SalesInvoice.body["template_month"].astext
    dup = (db.query(M.SalesInvoice)
           .filter(M.SalesInvoice.company_id == tpl.company_id, M.SalesInvoice.template_key == tpl.key,
                   M.SalesInvoice.status != "cancelled",
                   or_(written_for == ym,
                       and_(or_(written_for.is_(None), written_for == ""),
                            M.SalesInvoice.issue_date.like(f"{ym}-%")))).first())
    if dup is not None:
        raise HTTPException(409, f"{tpl.key} for {month} is already {dup.number} ({dup.status})")
    return create(db, company_id=tpl.company_id, kind="vat", customer_id=tpl.customer_id,
                  issue_date=day.isoformat(), sale_date=day.isoformat(), lines=tpl.lines or [],
                  payment={"terms_days": tpl.payment_terms_days}, extra_info=tpl.extra_info or [],
                  template_key=tpl.key, template_month=ym, actor=actor)


def _accountant_state(inv: M.SalesInvoice) -> dict:
    from .. import accountant

    return accountant.sales_state(inv)


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
           "accountant": _accountant_state(inv),
           "overdue": bool(not inv.paid and inv.due_date and inv.due_date < _today()
                           and inv.status == "issued" and inv.kind != "proforma")}
    if full:
        out["body"] = inv.body
        out["corrected_by"] = [{"id": k.id, "number": k.number, "status": k.status}
                               for k in db.query(M.SalesInvoice)
                               .filter(M.SalesInvoice.corrects_id == inv.id).all()]
        out["files"] = [{"id": f.id, "filename": f.filename, "size_bytes": f.size_bytes, "content_type": f.content_type}
                        for f in db.query(M.RecordFile).filter_by(owner_kind="sales_invoice", owner_id=inv.id)
                        .order_by(M.RecordFile.id).all()]
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
        if inv.kind == "advance":
            # The advance itself: the script printed the ORDER as the totals.
            inv.body = {**body, "advance_gross": str(inv.amount_due)}
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


# ================================================================ history

HISTORY_KINDS = ("vat", "advance", "settlement", "correction", "proforma")


def record_history(db: Session, *, company_id: int, kind: str, number: str, issue_date: str, sale_date: str,
                   due_date: str, buyer: dict, currency: str, lines: list[dict], totals: dict,
                   advance_numbers: list[str], corrects_number: str, paid: bool, paid_date: str,
                   order_id: int | None, note: str, actor: str) -> M.SalesInvoice:
    """A sales document a company ISSUED somewhere else, before the platform or
    KSeF wrote its invoices (decision 0077), kept as it was printed.

    Any company may have history, also one that does not issue on the
    platform: recording is not issuing. The record is `issued` from the start,
    never goes to KSeF and takes no number from the series. Its figures are the
    document's, as `from_register` keeps the script's:

    * an advance: `totals` is the advance (FA(3) P_13/P_15), the positions are
      the order (`body.order`), so `advance_amounts` reads the advance;
    * a settlement: the positions are the whole order, `totals` what is left
      to pay after the advances (`advance_numbers`), as FA(3) ROZ states it.
    """
    if kind not in HISTORY_KINDS:
        raise HTTPException(422, f"kind is one of {', '.join(HISTORY_KINDS)}")
    if not number.strip() or not issue_date:
        raise HTTPException(422, "a recorded document needs its number and its issue date")
    company = C.get(db, company_id)
    dup = (db.query(M.SalesInvoice)
           .filter(M.SalesInvoice.company_id == company.id, M.SalesInvoice.kind == kind,
                   M.SalesInvoice.status != "cancelled").all())
    if any(re.sub(r"\s+", "", i.number) == re.sub(r"\s+", "", number) for i in dup):
        raise HTTPException(409, f"{company.name} already has a {kind} document numbered {number}")
    rows = [{"position": i + 1, "name": ln.get("name") or "", "unit": ln.get("unit") or "",
             "qty": str(ln.get("qty") if ln.get("qty") is not None else ""),
             "unit_net": str(ln.get("unit_net") if ln.get("unit_net") is not None else ""),
             "net": str(ln.get("net") or 0), "vat_rate": str(ln.get("vat_rate") or ""),
             "vat": str(ln.get("vat") or 0),
             "gross": str(A.d2(Decimal(str(ln.get("net") or 0)) + Decimal(str(ln.get("vat") or 0))))}
            for i, ln in enumerate(lines)]
    tot = {"net": str(A.d2(totals.get("net") or 0)), "vat": str(A.d2(totals.get("vat") or 0)),
           "gross": str(A.d2(totals.get("gross") or 0)), "rates": totals.get("rates") or {}}
    body = {"title": "", "place": "", "seller": seller_of(company),
            "buyer": {"name": buyer.get("name") or "", "address_l1": buyer.get("address_l1") or "",
                      "address_l2": buyer.get("address_l2") or "", "nip": re.sub(r"\D", "", buyer.get("nip") or ""),
                      "country": buyer.get("country") or "PL"},
            "lines": [] if kind == "advance" else rows, "totals": tot,
            "payment": {"due_date": due_date or None, "method": "", "paid": bool(paid), "paid_date": paid_date or None,
                        "note": "", "partial": []},
            "bank": {}, "extra_info": [], "notes": [n for n in [note] if n], "files": {}}
    if kind == "advance":
        rates: dict[str, dict] = {}
        for r in rows:
            k = rates.setdefault(r["vat_rate"], {"net": Decimal(0), "vat": Decimal(0)})
            k["net"] += Decimal(r["net"]); k["vat"] += Decimal(r["vat"])
        onet = sum((k["net"] for k in rates.values()), Decimal(0))
        ovat = sum((k["vat"] for k in rates.values()), Decimal(0))
        body["order"] = {"lines": rows, "totals": {
            "net": str(A.d2(onet)), "vat": str(A.d2(ovat)), "gross": str(A.d2(onet + ovat)),
            "rates": {r: {"net": str(A.d2(k["net"])), "vat": str(A.d2(k["vat"]))} for r, k in rates.items()}}}
        body["advance_gross"] = tot["gross"]
    if kind == "settlement" and advance_numbers:
        body["advance_refs"] = [{"ksef": "", "number": n} for n in advance_numbers]
    inv = M.SalesInvoice(company_id=company.id, kind=kind, status="issued", number=number.strip(),
                         issue_date=issue_date[:10], sale_date=(sale_date or issue_date)[:10],
                         currency=(currency or "PLN")[:3], order_id=order_id, source="import: document",
                         body=body, created_by=actor)
    _columns(inv)
    inv.amount_due = A.d2(tot["gross"])
    inv.due_date = due_date or ""
    inv.paid, inv.paid_date = bool(paid), paid_date or ""
    nip = inv.buyer_nip
    inv.customer_id = next((c.id for c in db.query(M.Customer).all()
                            if nip and re.sub(r"\D", "", c.tax_id or "") == nip), None)
    if kind == "correction" and corrects_number:
        want = re.sub(r"\s+", "", corrects_number)
        inv.corrects_id = next((i.id for i in db.query(M.SalesInvoice).filter_by(company_id=company.id).all()
                                if re.sub(r"\s+", "", i.number) == want and i.kind != "correction"), None)
    db.add(inv)
    db.flush()
    return inv
