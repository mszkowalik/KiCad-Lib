"""Whether the accountant has a document, and what is left to send (decisions 0079, 0080).

The accountant reads KSeF, so a document that came from KSeF (a purchase
imported from the inbox, a sales invoice with a KSeF number) is HER document
without any row. Everything else is sent by the user, by the 10th of the next
month, and the platform records when (`accountant_sent_at`, `_via`, `_ref`):
`kpir` when the accountant booked it, `mail` when a mail to her carried it,
`history` for a document issued elsewhere, `manual` for a click.

`not_sent` is the opposite record: the user decided this one will never reach
her (lost, private, too late), the date is the decision and `_ref` the reason.
It takes the record off the list and out of the company books
(`company_books.year`), and nothing else: batch, project and stock costs do
not read it (decision 0080).

A document nobody pays for needs no sending: a proforma, an in-house
transfer, and a cancelled or draft sales invoice. EXCLUDED positions do not
make a document one of those: `excluded` says who bears a cost, not whether
the accountant has the invoice, and most fully-excluded JLC orders did reach
her (decision 0080 overrides item 3 of 0079).
"""
from __future__ import annotations

import re
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M

VIAS = ("ksef", "kpir", "mail", "manual", "history", "not_sent")
NOT_SENT = "not_sent"
_KSEF = re.compile(r"^\d{10}-\d{8}-[0-9A-F]{6,}-[0-9A-F]{2}$")


def _from_ksef(doc: M.RunCostDocument, linked: bool = False) -> bool:
    """Imported from KSeF, or typed by hand and later linked to a KSeF row
    (`ksef_invoices.document_id`): the accountant reads it in KSeF either way."""
    return linked or doc.company_source == "ksef" or bool(_KSEF.match(doc.external_id or ""))


def ksef_linked_ids(db: Session, company_id: int | None = None) -> set[int]:
    q = db.query(M.KsefInvoice.document_id).filter(M.KsefInvoice.document_id.isnot(None),
                                                   M.KsefInvoice.status == "imported")
    if company_id is not None:
        q = q.filter(M.KsefInvoice.company_id == company_id)
    return {r[0] for r in q.all()}


def ignored(doc: M.RunCostDocument) -> bool:
    """Needs no sending by its nature: a proforma, an in-house transfer."""
    return doc.doc_type in ("proforma", "transfer")


def kept_from_accountant(row: M.RunCostDocument | M.SalesInvoice) -> bool:
    """The user decided the accountant never gets it (decision 0080)."""
    return bool(row.accountant_sent_at) and row.accountant_sent_via == NOT_SENT


def _recorded(row: M.RunCostDocument | M.SalesInvoice) -> dict:
    if row.accountant_sent_via == NOT_SENT:
        return {"sent": False, "via": NOT_SENT, "at": row.accountant_sent_at, "ref": row.accountant_sent_ref,
                "ignored": True}
    return {"sent": True, "via": row.accountant_sent_via, "at": row.accountant_sent_at,
            "ref": row.accountant_sent_ref, "ignored": False}


def state(doc: M.RunCostDocument, db: Session | None = None, linked: set[int] | None = None) -> dict:
    """{sent, via, at, ref, ignored} of a supplier document. `linked` is the
    set of KSeF-linked document ids, else one query through `db`."""
    if linked is None and db is not None:
        linked = {r[0] for r in db.query(M.KsefInvoice.document_id)
                  .filter(M.KsefInvoice.document_id == doc.id, M.KsefInvoice.status == "imported").all()}
    if _from_ksef(doc, bool(linked) and doc.id in linked):
        return {"sent": True, "via": "ksef", "at": doc.doc_date or "", "ref": doc.external_id or "", "ignored": False}
    if doc.accountant_sent_at:
        return _recorded(doc)
    return {"sent": False, "via": "", "at": "", "ref": "", "ignored": ignored(doc)}


def sales_state(inv: M.SalesInvoice) -> dict:
    if inv.ksef_number:
        return {"sent": True, "via": "ksef", "at": inv.issue_date, "ref": inv.ksef_number, "ignored": False}
    if inv.accountant_sent_at:
        return _recorded(inv)
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
    linked = ksef_linked_ids(db, company_id)
    for d in (db.query(M.RunCostDocument).filter(M.RunCostDocument.company_id == company_id).all()):
        st = state(d, linked=linked)
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
    """Record that the accountant got these documents, or with `via="not_sent"`
    that she never will (`ref` then says why). An empty `sent_at` clears the
    record either way (the document is to send again)."""
    if via not in VIAS or via == "ksef":
        raise HTTPException(422, f"via is one of {', '.join(v for v in VIAS if v != 'ksef')}")
    if sent_at:
        try:
            sent_at = date.fromisoformat(sent_at[:10]).isoformat()
        except ValueError as e:
            raise HTTPException(422, "sent_at must be an ISO date") from e
    keep_from = bool(sent_at) and via == NOT_SENT
    if keep_from and not (ref or "").strip():
        raise HTTPException(422, "say why the accountant will not get it: lost, private, too late, or any reason")
    rows = []
    linked = ksef_linked_ids(db, company_id) if keep_from else set()
    for model, ids in ((M.RunCostDocument, document_ids), (M.SalesInvoice, sales_invoice_ids)):
        for i in ids or []:
            row = db.get(model, int(i))
            if row is None or row.company_id != company_id:
                raise HTTPException(404, f"no document {i} of this company")
            in_ksef = (row.ksef_number if model is M.SalesInvoice else _from_ksef(row, row.id in linked))
            if keep_from and in_ksef:
                raise HTTPException(422, f"document {i} is in KSeF: the accountant reads it there whatever is marked here")
            rows.append(row)
    for row in rows:
        row.accountant_sent_at = sent_at
        row.accountant_sent_via = via if sent_at else ""
        row.accountant_sent_ref = (ref or "").strip()[:200] if sent_at else ""
    db.flush()
    return len(rows)
