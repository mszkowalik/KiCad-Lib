"""Give the stock records their company (decision 0064).

Stock is kept per company only when every purchase, draw and adjustment names
one (`companies.stock_without_company`). New rows are stamped as they are
written (`companies.stamp_stock`). This module fills the rows written before.

**A purchase belongs to the company that was BILLED.** The evidence, strongest
first, and every document keeps the source it was decided by:

1. `jlc_billing` — the JLC payload's `taxVatBilling` (or `brazilCpnjBilling`).
   Never `taxVat`, which is the ship-to: one JLC invoice bills 9Sigma and ships
   to 7Sigma. For a parts order (POB…) with no stored payload, `jlc_web` asks
   JLC for the invoice through the stored session — opt-in (`fetch_jlc`), a
   read, approved by the user on 2026-10-04.
2. `pdf_nip` — exactly one of our two NIPs in the attached PDF's text.
3. `pdf_billto` — both NIPs are printed, and the buyer block names one.
4. `pdf_name` — no NIP of ours (DigiKey prints a third party's VAT number),
   and exactly one company name.
5. `date` — dated before 9Sigma existed, so 7Sigma.

Where two sources disagree the document stays unresolved and the report says
so. The folder a file sits in is never evidence. A person decides the rest
(`PATCH /api/cost-documents/{id}` with `company_id`).
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from .. import models as M
from . import companies as C
from . import run_actuals as RA
from . import storage

log = logging.getLogger(__name__)

SOURCES = ("jlc_billing", "jlc_web", "pdf_nip", "pdf_billto", "pdf_name", "date", "manual")

_BUYER_LABEL = re.compile(r"(?i)(nabywca|bill\s*to|billing\s+address|buyer|invoice\s+to|sold\s+to|"
                          r"customer|kupujący|odbiorca\s+faktury)")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _nips_in(text: str, companies: list[M.Company]) -> set[int]:
    """Which of our companies' NIPs the text prints, in any spelling
    (8513262910, 851-326-29-10, PL 851 326 29 10)."""
    flat = re.sub(r"[\s\-.]", "", text or "")
    return {c.id for c in companies if c.nip and c.nip in flat}


def _names_in(text: str, companies: list[M.Company]) -> set[int]:
    """Which company names the text prints. The short names only: "Mateusz
    Kowalik" is in 7Sigma's legal name AND on 9Sigma's paperwork as its
    contact, so it decides nothing."""
    out = set()
    for c in companies:
        stem = re.escape(c.name.replace("Sigma", "")).strip()   # "7", "9"
        if re.search(rf"(?i)\b{stem}\s*-?\s*sigma\b", text or ""):
            out.add(c.id)
    return out


def pdf_text(db: Session, doc: M.RunCostDocument) -> str:
    """The text layer of every PDF attached to the document. An image-only
    scan has none and gives ''."""
    import fitz  # pymupdf

    atts = db.query(M.RunAttachment).filter_by(document_id=doc.id).all()
    if doc.attachment_id and not any(a.id == doc.attachment_id for a in atts):
        a = db.get(M.RunAttachment, doc.attachment_id)
        if a is not None:
            atts.append(a)
    texts = []
    for a in atts:
        if not (a.filename or "").lower().endswith(".pdf") and "pdf" not in (a.content_type or ""):
            continue
        data = storage.get_bytes(a.minio_key)
        if not data:
            continue
        try:
            with fitz.open(stream=data, filetype="pdf") as pdf:
                texts.append("\n".join(page.get_text() for page in pdf))
        except Exception as exc:  # noqa: BLE001 — a damaged file is no evidence, never a crash
            log.warning("buyer evidence: cannot read attachment %s: %s", a.id, exc)
    return "\n".join(texts)


def _jlc_billing(db: Session, doc: M.RunCostDocument, by_nip: dict[str, int]) -> int | None:
    imp = db.query(M.JlcImport).filter_by(document_id=doc.id).first()
    if imp is None or not imp.payload:
        return None
    for field in ("taxVatBilling", "brazilCpnjBilling"):
        nip = _digits(str(imp.payload.get(field) or ""))
        if nip in by_nip:
            return by_nip[nip]
    return None


def _jlc_web_billing(db: Session, doc: M.RunCostDocument, by_nip: dict[str, int]) -> int | None:
    """The billed VAT number of a JLC parts order, asked of JLC itself."""
    from . import jlc_web

    if not (doc.external_id or "").startswith("POB") or not jlc_web.available(db):
        return None
    try:
        inv = jlc_web.get_parts_invoice(db, doc.external_id)
    except Exception as exc:  # noqa: BLE001 — a dead session is no evidence, never a crash
        log.warning("buyer evidence: JLC parts invoice %s: %s", doc.external_id, exc)
        return None
    for field in ("taxVatBilling", "brazilCpnjBilling"):
        nip = _digits(str((inv or {}).get(field) or ""))
        if nip in by_nip:
            return by_nip[nip]
    return None


def buyer_evidence(db: Session, doc: M.RunCostDocument, companies: list[M.Company],
                   text: str | None = None, fetch_jlc: bool = False) -> dict:
    """Every source's answer for one document, and the decision."""
    by_nip = {c.nip: c.id for c in companies if c.nip}
    found: dict[str, int] = {}
    jlc = _jlc_billing(db, doc, by_nip)
    if jlc:
        found["jlc_billing"] = jlc
    elif fetch_jlc:
        web = _jlc_web_billing(db, doc, by_nip)
        if web:
            found["jlc_web"] = web
    text = pdf_text(db, doc) if text is None else text
    if text:
        nips = _nips_in(text, companies)
        if len(nips) == 1:
            found["pdf_nip"] = next(iter(nips))
        elif len(nips) > 1:
            m = _BUYER_LABEL.search(text)
            if m:
                block = text[m.end():m.end() + 400]
                own = _nips_in(block, companies) or _names_in(block, companies)
                if len(own) == 1:
                    found["pdf_billto"] = next(iter(own))
        else:
            names = _names_in(text, companies)
            if len(names) == 1:
                found["pdf_name"] = next(iter(names))
    nine = next((c for c in companies if c.started_on), None)
    if doc.doc_date and nine is not None and doc.doc_date[:10] < nine.started_on:
        seven = next((c for c in companies if c.id != nine.id), None)
        if seven is not None:
            found["date"] = seven.id
    answers = set(found.values())
    pick = next((s for s in SOURCES if s in found), None)
    return {"document_id": doc.id, "supplier": doc.supplier or "", "doc_number": doc.doc_number or "",
            "doc_date": doc.doc_date or "", "evidence": found, "has_text": bool(text),
            "company_id": found[pick] if pick and len(answers) == 1 else None,
            "source": pick if len(answers) == 1 else ("conflict" if answers else ""),
            }


def backfill(db: Session, *, dry_run: bool = True, fetch_jlc: bool = False,
             actor: str = "") -> dict:
    """Name the company of every document, draw and adjustment that has none.
    Rows that already name one are left alone, so this runs any number of
    times. Dry run by default."""
    companies = C.all_companies(db)
    names = {c.id: c.name for c in companies}
    out: dict = {"dry_run": dry_run, "documents": [], "unresolved_documents": [],
                 "draws": 0, "adjustments": 0, "unresolved_draws": [],
                 "unresolved_adjustments": []}

    # 1. Purchases: the billed company.
    docs = (db.query(M.RunCostDocument)
            .filter(M.RunCostDocument.company_id.is_(None))
            .order_by(M.RunCostDocument.doc_date, M.RunCostDocument.id).all())
    doc_company: dict[int, int] = {}
    for doc in docs:
        ev = buyer_evidence(db, doc, companies, fetch_jlc=fetch_jlc)
        row = {**ev, "company": names.get(ev["company_id"]),
               "evidence": {k: names.get(v) for k, v in ev["evidence"].items()}}
        if ev["company_id"] is None:
            out["unresolved_documents"].append(row)
            continue
        out["documents"].append(row)
        doc_company[doc.id] = ev["company_id"]
        if not dry_run:
            doc.company_id = ev["company_id"]
            doc.company_source = ev["source"]

    def company_of_doc(doc_id: int | None) -> int | None:
        if doc_id is None:
            return None
        if doc_id in doc_company:
            return doc_company[doc_id]
        d = db.get(M.RunCostDocument, doc_id)
        return d.company_id if d is not None else None

    nine = next((c for c in companies if c.started_on), None)
    seven = next((c for c in companies if nine is None or c.id != nine.id), None)

    def by_date(day: str | None) -> int | None:
        if day and nine is not None and seven is not None and day[:10] < nine.started_on:
            return seven.id
        return None

    # 2. Draws: from what they are linked to, else the JLC order's buyer.
    for c in RA.live_consumption(db).filter(M.ComponentConsumption.company_id.is_(None)).all():
        cid = C.stock_company_for(db, c)
        if cid is None and (c.import_ref or "").startswith("jlc:"):
            # an uncharged JLC draw: the company the assembly order billed
            batch = c.import_ref.split(":")[1]
            imp = db.query(M.JlcImport).filter_by(external_id=batch).first()
            cid = company_of_doc(imp.document_id if imp else None)
        if cid is None:
            cid = by_date(c.consumed_at)
        if cid is None:
            out["unresolved_draws"].append({"id": c.id, "mpn": c.mpn, "lcsc": c.lcsc, "qty": c.qty,
                                            "date": c.consumed_at, "import_ref": c.import_ref,
                                            "note": (c.note or "")[:120]})
            continue
        out["draws"] += 1
        if not dry_run:
            c.company_id = cid

    # 3. Adjustments.
    for a in (db.query(M.ComponentStockAdjustment)
              .filter(M.ComponentStockAdjustment.company_id.is_(None)).all()):
        cid = C.stock_company_for(db, a) or by_date(a.adjusted_at)
        if cid is None:
            out["unresolved_adjustments"].append({"id": a.id, "mpn": a.mpn, "qty": a.qty_delta,
                                                  "date": a.adjusted_at, "reason": a.reason})
            continue
        out["adjustments"] += 1
        if not dry_run:
            a.company_id = cid
    if not dry_run:
        db.flush()
    out["totals"] = {"documents": len(out["documents"]),
                     "unresolved_documents": len(out["unresolved_documents"]),
                     "draws": out["draws"], "unresolved_draws": len(out["unresolved_draws"]),
                     "adjustments": out["adjustments"],
                     "unresolved_adjustments": len(out["unresolved_adjustments"]),
                     "by_source": _count(out["documents"])}
    return out


def _count(rows: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        out[r["source"]] = out.get(r["source"], 0) + 1
    return out
