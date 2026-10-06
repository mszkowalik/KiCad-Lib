"""Whether the accountant has a document, and what is left to send (decision 0079).

The accountant reads KSeF, so a document that came from KSeF (a purchase
imported from the inbox, a sales invoice with a KSeF number) is HER document
without any row. Everything else is sent by the user, by the 10th of the next
month, and the platform records when (`accountant_sent_at`, `_via`, `_ref`):
`kpir` when the accountant booked it, `mail` when a mail to her carried it,
`history` for a document issued elsewhere, `manual` for a click.

A document nobody pays for needs no sending: a proforma, an in-house
transfer, a supplier document whose positions are all charged to nobody, and
a cancelled or draft sales invoice.
"""
from __future__ import annotations

import re
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M

VIAS = ("ksef", "kpir", "mail", "manual", "history")
_KSEF = re.compile(r"^\d{10}-\d{8}-[0-9A-F]{6,}-[0-9A-F]{2}$")


def _from_ksef(doc: M.RunCostDocument) -> bool:
    return doc.company_source == "ksef" or bool(_KSEF.match(doc.external_id or ""))


def ignored(doc: M.RunCostDocument) -> bool:
    if doc.doc_type in ("proforma", "transfer"):
        return True
    live = [li for li in doc.lines if li.voided_at is None]
    return bool(live) and all(li.allocate == "excluded" for li in live)


def state(doc: M.RunCostDocument) -> dict:
    """{sent, via, at, ref, ignored} of a supplier document."""
    if _from_ksef(doc):
        return {"sent": True, "via": "ksef", "at": doc.doc_date or "", "ref": doc.external_id or "", "ignored": False}
    if doc.accountant_sent_at:
        return {"sent": True, "via": doc.accountant_sent_via, "at": doc.accountant_sent_at,
                "ref": doc.accountant_sent_ref, "ignored": False}
    return {"sent": False, "via": "", "at": "", "ref": "", "ignored": ignored(doc)}


def sales_state(inv: M.SalesInvoice) -> dict:
    if inv.ksef_number:
        return {"sent": True, "via": "ksef", "at": inv.issue_date, "ref": inv.ksef_number, "ignored": False}
    if inv.accountant_sent_at:
        return {"sent": True, "via": inv.accountant_sent_via, "at": inv.accountant_sent_at,
                "ref": inv.accountant_sent_ref, "ignored": False}
    return {"sent": False, "via": "", "at": "", "ref": "",
            "ignored": inv.kind == "proforma" or inv.status in ("draft", "cancelled")}


def deadline(day: str) -> str:
    """The 10th of the month after a document's month."""
    y, m = int(day[:4]), int(day[5:7])
    y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return f"{y:04d}-{m:02d}-10"


def to_send(db: Session, company_id: int, today: str | None = None) -> dict:
    """Every document of the company the accountant does not have yet, by month,
    oldest first, with the deadline and whether it has passed."""
    today = today or date.today().isoformat()
    rows = []
    for d in (db.query(M.RunCostDocument).filter(M.RunCostDocument.company_id == company_id).all()):
        st = state(d)
        if st["sent"] or st["ignored"] or not d.doc_date:
            continue
        rows.append({"kind": "document", "id": d.id, "date": d.doc_date[:10], "party": d.supplier or "",
                     "number": d.doc_number or "", "net": d.total_amount, "currency": d.currency or "",
                     "files": db.query(M.RunAttachment).filter(M.RunAttachment.document_id == d.id).count()})
    for i in db.query(M.SalesInvoice).filter(M.SalesInvoice.company_id == company_id).all():
        st = sales_state(i)
        if st["sent"] or st["ignored"] or not i.issue_date:
            continue
        rows.append({"kind": "sales_invoice", "id": i.id, "date": i.issue_date[:10], "party": i.buyer_name or "",
                     "number": i.number, "net": float(i.net_total or 0), "currency": i.currency,
                     "files": db.query(M.RecordFile).filter_by(owner_kind="sales_invoice", owner_id=i.id).count()})
    months: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (r["date"], r["kind"], r["id"])):
        m = r["date"][:7]
        g = months.setdefault(m, {"month": m, "deadline": deadline(r["date"]), "rows": []})
        g["overdue"] = g["deadline"] < today
        g["rows"].append(r)
    return {"company_id": company_id, "today": today, "months": list(months.values()),
            "count": len(rows)}


def mark(db: Session, company_id: int, *, document_ids: list[int], sales_invoice_ids: list[int],
         sent_at: str, via: str = "manual", ref: str = "") -> int:
    """Record that the accountant got these documents. An empty `sent_at`
    clears the record (the document is to send again)."""
    if via not in VIAS or via == "ksef":
        raise HTTPException(422, f"via is one of {', '.join(v for v in VIAS if v != 'ksef')}")
    if sent_at:
        try:
            sent_at = date.fromisoformat(sent_at[:10]).isoformat()
        except ValueError as e:
            raise HTTPException(422, "sent_at must be an ISO date") from e
    n = 0
    for model, ids in ((M.RunCostDocument, document_ids), (M.SalesInvoice, sales_invoice_ids)):
        for i in ids or []:
            row = db.get(model, int(i))
            if row is None or row.company_id != company_id:
                raise HTTPException(404, f"no document {i} of this company")
            row.accountant_sent_at = sent_at
            row.accountant_sent_via = via if sent_at else ""
            row.accountant_sent_ref = (ref or "")[:200] if sent_at else ""
            n += 1
    db.flush()
    return n
