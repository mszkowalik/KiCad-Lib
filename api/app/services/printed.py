"""A supplier document's printed invoice (decisions 0084, 0085).

`RunCostDocument.body` holds the invoice as printed, in the shape of
`SalesInvoice.body` (the KSeF FA(3) structure). Two readers write it:

* **KSeF** (`ksef.sync.apply_fiscal`): the XML is the binding invoice.
* **The document's own original file** (`from_original`, decision 0085): a
  reader (an agent or a person, through the API) transcribes the attached PDF,
  and the transcription is checked against itself and against the document
  before it is stored. It names the file it was read from.

The tax layer moves no money: costs read the net and the positions, never
these columns. So `from_original` writes on the document of a closed batch
too, and it never changes the net, the positions, the currency, the date or
the pinned rate. A printed figure that differs from what the document says is
a PROBLEM: the write needs a reason, and the problems and the reason are kept
with the page, so the difference stays visible instead of being corrected
silently.
"""
from __future__ import annotations

import re
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from .invoicing.amounts import d2

#: How far a printed sum may be from the sum of its parts (rounding per
#: position), and a printed net from the document's net.
TOLERANCE = Decimal("0.05")


def _dec(v) -> Decimal:
    return Decimal(str(v if v not in (None, "") else 0))


def tax_fields(parsed: dict) -> dict:
    """The document columns a printed invoice states: the page itself, its
    sale and due dates, its VAT, the VAT in PLN of an invoice in another
    currency, and the payment day when it says it was paid. `parsed` is the
    shape `ksef.parse.parse` returns."""
    b = parsed["body"]
    t = b.get("totals") or {}
    pay = b.get("payment") or {}
    foreign = (parsed.get("currency") or "PLN").upper() != "PLN"
    return {
        "body": b,
        "sale_date": parsed.get("sale_date") or parsed.get("issue_date") or "",
        "due_date": pay.get("due_date") or "",
        "vat": d2(t["vat"]) if t.get("vat") not in (None, "") else None,
        "tax_amount_pln": d2(t["vat_pln"]) if foreign and t.get("vat_pln") not in (None, "") else None,
        "paid_date": pay.get("paid_date") if pay.get("paid") and pay.get("paid_date") else "",
    }


def assign(doc: M.RunCostDocument, want: dict) -> list[str]:
    """Set the columns that differ; return their names. An amount compares by
    value, so 98.2 and Decimal("98.20") are the same figure."""
    changed = []
    for k, v in want.items():
        old = getattr(doc, k)
        if isinstance(v, (Decimal, float)) and old is not None and v is not None and d2(old) == d2(v):
            continue
        if old != v:
            setattr(doc, k, v)
            changed.append(k)
    return changed


def _number_key(n: str) -> str:
    """An invoice number with case, spaces and leading zeros dropped (the
    rule `ksef.sync.possible_duplicates` matches hand-typed numbers by)."""
    return re.sub(r"(?<!\d)0+(?=\d)", "", re.sub(r"\s+", "", (n or "").upper()))


def problems(doc: M.RunCostDocument, parsed: dict) -> list[dict]:
    """Where a transcription does not add up, or does not agree with the
    document. Each is `{code, text}`; an empty list means none."""
    b = parsed["body"]
    t = b["totals"]
    out: list[dict] = []

    def say(code: str, text: str) -> None:
        out.append({"code": code, "text": text})

    net, vat, gross = _dec(t.get("net")), _dec(t.get("vat")), _dec(t.get("gross"))
    lines = b.get("lines") or []
    if lines:
        s = sum((_dec(ln.get("net")) for ln in lines), Decimal(0))
        if abs(s - net) > TOLERANCE:
            say("positions", f"the positions add up to net {d2(s)}, the page states {d2(net)}")
    rates = t.get("rates") or {}
    if rates:
        rn = sum((_dec(r.get("net")) for r in rates.values()), Decimal(0))
        rv = sum((_dec(r.get("vat")) for r in rates.values()), Decimal(0))
        if abs(rn - net) > TOLERANCE or abs(rv - vat) > TOLERANCE:
            say("rates", f"the rates add up to net {d2(rn)} and VAT {d2(rv)}, the page states {d2(net)} and {d2(vat)}")
    if abs(net + vat - gross) > TOLERANCE:
        say("gross", f"net {d2(net)} + VAT {d2(vat)} is not the gross {d2(gross)}")

    cur = (parsed.get("currency") or "").upper()
    if cur and cur != (doc.currency or "").upper():
        say("currency", f"the page is in {cur}, the document in {doc.currency}")
    if doc.doc_number and _number_key(parsed.get("number") or "") != _number_key(doc.doc_number):
        say("number", f"the page is number {parsed.get('number')!r}, the document {doc.doc_number!r}")
    if doc.doc_date and (parsed.get("issue_date") or "")[:10] != doc.doc_date[:10]:
        say("date", f"the page is dated {parsed.get('issue_date')}, the document {doc.doc_date}")
    if doc.total_amount is not None and abs(net - _dec(doc.total_amount)) > TOLERANCE:
        say("net", f"the page states net {d2(net)}, the document {d2(doc.total_amount)}")
    if doc.tax_amount is not None and abs(vat - _dec(doc.tax_amount)) > Decimal("0.02"):
        say("vat", f"the page states VAT {d2(vat)}, the document {d2(doc.tax_amount)}")
    return out


def from_original(db: Session, doc: M.RunCostDocument, attachment: M.RunAttachment, parsed: dict, *,
                  reason: str = "", actor: str = "") -> dict:
    """Store a transcription of the document's own original as its printed
    invoice, and the tax columns it states (decision 0085).

    Refused for an in-house transfer (it has no invoice), for a document KSeF
    holds (its XML is the invoice), and for a file of another document. A
    transcription with problems needs a `reason`; without one the answer is
    409 with the problems, and nothing is written. The printed VAT replaces
    the typed `tax_amount`; the net and the positions are never touched."""
    if (doc.doc_type or "") == "transfer":
        raise HTTPException(422, "an in-house transfer has no printed invoice")
    if attachment.document_id != doc.id:
        raise HTTPException(422, f"file {attachment.id} is not one of this document's originals")
    held = db.query(M.KsefInvoice).filter(M.KsefInvoice.document_id == doc.id).first()
    if held is not None:
        raise HTTPException(409, {"error": f"KSeF holds this invoice ({held.ksef_number}): its XML is the invoice, "
                                           "and POST /api/ksef/fill-documents reads it",
                                  "document_id": doc.id})
    found = problems(doc, parsed)
    reason = (reason or "").strip()[:500]
    if found and not reason:
        raise HTTPException(409, {"error": "the transcription has problems; give a reason to store it anyway: "
                                           + "; ".join(p["text"] for p in found),
                                  "problems": found, "document_id": doc.id})
    f = tax_fields(parsed)
    want = {
        "body": {**f["body"], "source": {"kind": "file", "attachment_id": attachment.id,
                                         "filename": attachment.filename, "actor": actor[:100],
                                         "read_on": utcnow().date().isoformat(),
                                         "problems": found, "reason": reason}},
        "sale_date": f["sale_date"],
        "due_date": f["due_date"],
        "tax_amount": float(f["vat"]) if f["vat"] is not None else doc.tax_amount,
        "tax_amount_pln": f["tax_amount_pln"],
    }
    if not doc.paid_at and f["paid_date"]:
        want["paid_at"] = f["paid_date"]
    before = {k: getattr(doc, k) for k in want if k != "body"}
    changed = assign(doc, want)
    db.flush()
    return {"changed": changed, "problems": found,
            "before": {k: (str(v) if isinstance(v, Decimal) else v) for k, v in before.items() if k in changed}}
