"""Fetch a company's invoices from KSeF into the inbox, link the sales side
to the platform's record, import a purchase on request (decision 0067).

* **Fetching writes only the inbox** (`ksef_invoices`) and downloads XML to
  MinIO. It never touches money.
* **A sales invoice is linked**: for a company that issues its invoices here,
  to the draft or record of the same series and number — the draft becomes
  issued, with KSeF's number and hash, and the platform's copy takes KSeF's
  figures, because the invoice in KSeF is the binding one. An invoice written
  directly in KSeF becomes a record of its own, so its number is never given
  out again. For a company with its own system (9SIGMA) every sales invoice is
  recorded for reading.
* **A purchase waits** until a person or an agent imports it as a supplier
  document, or skips it with a reason.

A company's sync resumes a week before the newest issue date it read, and the
first one starts when KSeF 2.0 did. A rate limit stops the sync and records
until when; the next sync carries on.
"""
from __future__ import annotations

import base64
import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ... import models as M
from .. import companies as C
from .. import crypto, storage
from ..invoicing import amounts as A
from . import client as K
from .parse import parse

KIND_OF_TYPE = {"Vat": "vat", "Kor": "correction", "Zal": "advance", "Roz": "settlement", "Upr": "vat",
                "KorZal": "correction", "KorRoz": "correction"}
#: XML downloads per sync; the rest waits for the next one (KSeF limits downloads).
DOWNLOADS_PER_SYNC = 60


def _now() -> datetime:
    return datetime.now(UTC)


def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


def _norm_number(n: str) -> str:
    return re.sub(r"(^|[ /])0+(\d)", r"\1\2", (n or "").strip())


def b64_to_b64url(h: str) -> str:
    """KSeF's metadata gives the SHA-256 in base64; the QR link wants base64url."""
    if not h:
        return ""
    return base64.urlsafe_b64encode(base64.b64decode(h)).decode().rstrip("=")


# ------------------------------------------------------------ credentials

def credential(db: Session, company_id: int, create: bool = False) -> M.KsefCredential | None:
    row = db.get(M.KsefCredential, company_id)
    if row is None and create:
        row = M.KsefCredential(company_id=company_id)
        db.add(row)
        db.flush()
    return row


def set_token(db: Session, company_id: int, token: str, actor: str) -> None:
    C.get(db, company_id)
    row = credential(db, company_id, create=True)
    row.token_enc = crypto.encrypt_token(token.strip()) if token.strip() else ""
    row.last_error = ""
    row.updated_by = actor[:100]
    db.flush()


def status(db: Session) -> list[dict]:
    """Per company: whether a token is set — never the token — and how the
    syncs went."""
    out = []
    for c in C.all_companies(db):
        row = credential(db, c.id)
        counts: dict[str, int] = {}
        for side, st, n in (db.query(M.KsefInvoice.side, M.KsefInvoice.status,
                                     M.KsefInvoice.id).filter(M.KsefInvoice.company_id == c.id).all()):
            counts[f"{side}:{st}"] = counts.get(f"{side}:{st}", 0) + 1
        out.append({"company_id": c.id, "company": c.name, "configured": bool(row and row.token_enc),
                    "last_sync_at": row.last_sync_at.isoformat() if row and row.last_sync_at else None,
                    "last_error": row.last_error if row else "",
                    "rate_limited_until": (row.rate_limited_until.isoformat()
                                           if row and row.rate_limited_until else None),
                    "sales_read_to": row.sales_read_to if row else "",
                    "purchases_read_to": row.purchases_read_to if row else "",
                    "counts": counts})
    return out


# ------------------------------------------------------------------ fetch

def _upsert(db: Session, company_id: int, side: str, m: dict) -> M.KsefInvoice | None:
    num = m.get("ksefNumber") or ""
    if not num:
        return None
    row = db.query(M.KsefInvoice).filter_by(ksef_number=num).first()
    seller, buyer = m.get("seller") or {}, m.get("buyer") or {}
    fields = {
        "invoice_number": (m.get("invoiceNumber") or "")[:256], "invoice_type": (m.get("invoiceType") or "")[:20],
        "issue_date": (m.get("issueDate") or "")[:10],
        "seller_nip": _digits(seller.get("nip") or (seller.get("identifier") or {}).get("value")),
        "seller_name": (seller.get("name") or "")[:512],
        "buyer_nip": _digits((buyer.get("identifier") or {}).get("value") or buyer.get("nip")),
        "buyer_name": (buyer.get("name") or "")[:512],
        "net": A.d2(m["netAmount"]) if m.get("netAmount") is not None else None,
        "vat": A.d2(m["vatAmount"]) if m.get("vatAmount") is not None else None,
        "gross": A.d2(m["grossAmount"]) if m.get("grossAmount") is not None else None,
        "currency": (m.get("currency") or "PLN")[:3], "xml_hash": b64_to_b64url(m.get("invoiceHash") or ""),
        "received_at": m.get("acquisitionDate") or m.get("permanentStorageDate") or "", "meta": m,
    }
    if row is None:
        row = M.KsefInvoice(company_id=company_id, side=side, ksef_number=num, **fields)
        db.add(row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)
    return row


def _download(db: Session, cl: K.Client, rows: list[M.KsefInvoice]) -> tuple[int, str]:
    done = 0
    for row in rows[:DOWNLOADS_PER_SYNC]:
        try:
            xml = cl.xml(row.ksef_number)
        except K.RateLimited as e:
            return done, str(e)
        key = f"ksef/{row.company_id}/{row.side}/{row.ksef_number}.xml"
        storage.put_bytes(key, xml, "application/xml")
        row.xml_key = key
        done += 1
    return done, ""


def sync(db: Session, company_id: int, *, sides: tuple[str, ...] = ("sales", "purchase"),
         since: str | None = None, client_factory=K.Client) -> dict:
    """One company's KSeF read-out: metadata, XML downloads, sales links."""
    company = C.get(db, company_id)
    row = credential(db, company_id)
    if row is None or not row.token_enc:
        raise HTTPException(409, f"no KSeF token is set for {company.name} (Admin → Companies)")
    if row.rate_limited_until and row.rate_limited_until > _now():
        raise HTTPException(429, f"KSeF limits {company.name}'s queries until "
                                 f"{row.rate_limited_until.isoformat(timespec='minutes')}")
    try:
        token = crypto.decrypt_token(row.token_enc)
    except Exception as e:  # a key that no longer decrypts is reported, never a 500
        raise HTTPException(409, "the stored KSeF token cannot be decrypted; set it again") from e
    out: dict = {"company": company.name, "fetched": {}, "downloaded": 0, "linked": 0, "recorded": 0,
                 "limit": ""}
    cl = client_factory(token, company.nip)
    try:
        for side in sides:
            read_to = row.sales_read_to if side == "sales" else row.purchases_read_to
            start = (date.fromisoformat(since[:10]) if since else
                     (date.fromisoformat(read_to) - timedelta(days=7)) if read_to else K.KSEF2_START)
            try:
                metas = cl.metadata(side, start, date.today())
            except K.RateLimited as e:
                row.rate_limited_until = _now() + timedelta(seconds=e.seconds)
                out["limit"] = str(e)
                break
            new = 0
            for m in metas:
                existed = db.query(M.KsefInvoice.id).filter_by(ksef_number=m.get("ksefNumber") or "").first()
                if _upsert(db, company.id, side, m) is not None and existed is None:
                    new += 1
            out["fetched"][side] = {"listed": len(metas), "new": new}
            newest = max((m.get("issueDate") or "")[:10] for m in metas) if metas else ""
            if newest:
                if side == "sales":
                    row.sales_read_to = max(row.sales_read_to or "", newest)
                else:
                    row.purchases_read_to = max(row.purchases_read_to or "", newest)
        db.flush()
        missing = (db.query(M.KsefInvoice)
                   .filter(M.KsefInvoice.company_id == company.id, M.KsefInvoice.xml_key == "",
                           M.KsefInvoice.status != "skipped")
                   .order_by(M.KsefInvoice.issue_date).all())
        if not out["limit"]:
            done, limit = _download(db, cl, missing)
            out["downloaded"] = done
            out["limit"] = limit
        res = link_sales(db, company)
        out["linked"], out["recorded"] = res["linked"], res["recorded"]
        out["refused"] = res["refused"]
        row.last_error = out["limit"][:500]
    except K.KsefError as e:
        row.last_error = str(e)[:500]
        raise HTTPException(502, f"KSeF: {e}") from e
    finally:
        cl.close()
        row.last_sync_at = _now()
        db.flush()
    return out


# ------------------------------------------------------------ sales links

def _xml_of(row: M.KsefInvoice) -> bytes | None:
    return storage.get_bytes(row.xml_key) if row.xml_key else None


def _apply_ksef(inv: M.SalesInvoice, row: M.KsefInvoice, parsed: dict | None) -> None:
    """The platform's record takes KSeF's number, hash and, with the XML,
    KSeF's figures — the invoice in KSeF is the binding one."""
    from ..invoicing.service import _columns

    inv.ksef_number = row.ksef_number
    inv.ksef_hash = row.xml_hash or inv.ksef_hash
    inv.ksef_received_at = row.received_at
    if row.xml_key:
        inv.official_xml_key = row.xml_key
    if inv.status == "draft":
        inv.status = "issued"
    if parsed:
        b = dict(inv.body or {})
        before = (b.get("totals") or {}).get("gross")
        for k in ("seller", "buyer", "lines", "totals", "payment", "bank", "extra_info"):
            if parsed["body"].get(k) is not None:
                b[k] = parsed["body"][k]
        notes = list(b.get("notes") or []) + parsed["body"].get("notes", [])
        if before and abs(Decimal(before) - Decimal(parsed["body"]["totals"]["gross"])) > Decimal("0.01"):
            notes.append(f"the draft's gross {before} differs from KSeF's {parsed['body']['totals']['gross']}")
        b["notes"] = notes
        inv.body = b
        _columns(inv)


def link_sales(db: Session, company: M.Company) -> dict:
    out = {"linked": 0, "recorded": 0, "refused": []}
    rows = (db.query(M.KsefInvoice)
            .filter(M.KsefInvoice.company_id == company.id, M.KsefInvoice.side == "sales",
                    M.KsefInvoice.status == "new").order_by(M.KsefInvoice.issue_date).all())
    for row in rows:
        kind = KIND_OF_TYPE.get(row.invoice_type, "vat")
        xml = _xml_of(row)
        parsed = parse(xml) if xml else None
        mine = [i for i in db.query(M.SalesInvoice)
                .filter(M.SalesInvoice.company_id == company.id, M.SalesInvoice.kind == kind,
                        M.SalesInvoice.status != "cancelled").all()
                if _norm_number(i.number) == _norm_number(row.invoice_number)]
        hit = next((i for i in mine if i.ksef_number == row.ksef_number), None) or \
            next((i for i in mine if not i.ksef_number), None)
        if hit is not None and hit.status == "draft" and hit.buyer_nip and row.buyer_nip \
                and hit.buyer_nip != row.buyer_nip:
            out["refused"].append({"number": row.invoice_number, "why": "KSeF holds this number for another "
                                   f"buyer ({row.buyer_name}); give the draft a new number"})
            continue
        if hit is not None:
            _apply_ksef(hit, row, parsed)
            row.status, row.sales_invoice_id = "linked", hit.id
            out["linked"] += 1
            continue
        if parsed is None:
            continue    # recorded once its XML is downloaded
        inv = M.SalesInvoice(company_id=company.id, kind=parsed["kind"], status="issued",
                             number=parsed["number"] or row.invoice_number, issue_date=parsed["issue_date"],
                             sale_date=parsed["sale_date"], currency=parsed["currency"][:3],
                             ksef_number=row.ksef_number, ksef_hash=row.xml_hash,
                             ksef_received_at=row.received_at, official_xml_key=row.xml_key,
                             source="ksef", body=parsed["body"], created_by="ksef")
        from ..invoicing.service import _columns

        _columns(inv)
        inv.paid = bool(parsed["body"]["payment"].get("paid"))
        inv.paid_date = parsed["body"]["payment"].get("paid_date") or ""
        nip = inv.buyer_nip
        inv.customer_id = next((c.id for c in db.query(M.Customer).all()
                                if nip and _digits(c.tax_id) == nip), None)
        db.add(inv)
        db.flush()
        row.status, row.sales_invoice_id = "linked", inv.id
        out["recorded"] += 1
    db.flush()
    return out


# -------------------------------------------------------- purchase import

def _supplier_name(db: Session, nip: str, name: str) -> str:
    """The supplier name the register already uses for this NIP, else KSeF's."""
    if nip:
        d = (db.query(M.RunCostDocument).filter(M.RunCostDocument.seller_tax_id == nip)
             .order_by(M.RunCostDocument.id.desc()).first())
        if d is not None and d.supplier:
            return d.supplier
    return (name or "").strip()[:200]


def import_purchase(db: Session, row: M.KsefInvoice, actor: str = "", client_factory=K.Client) -> M.RunCostDocument:
    """A purchase from the inbox as a supplier document, billed to the company
    that fetched it. Its positions name no destination yet: the register shows
    them unassigned until a person or an agent says where each one goes."""
    if row.side != "purchase":
        raise HTTPException(422, "only a purchase is imported as a supplier document")
    if row.status in ("imported", "skipped"):
        raise HTTPException(409, f"{row.ksef_number} is already {row.status}")
    dup = (db.query(M.RunCostDocument)
           .filter((M.RunCostDocument.external_id == row.ksef_number)
                   | ((M.RunCostDocument.seller_tax_id == row.seller_nip)
                      & (M.RunCostDocument.doc_number == row.invoice_number)
                      & (M.RunCostDocument.seller_tax_id != ""))).first())
    if dup is not None:
        row.status, row.document_id = "imported", dup.id
        db.flush()
        raise HTTPException(409, f"{row.invoice_number} is already supplier document {dup.id}; linked to it")
    xml = _xml_of(row)
    if xml is None:
        raise HTTPException(409, "its XML is not downloaded yet; run the KSeF sync again")
    p = parse(xml)
    b = p["body"]
    doc_type = {"correction": "correction"}.get(p["kind"], "invoice")
    corrects = None
    if p["kind"] == "correction" and (b.get("correction") or {}).get("of_ksef"):
        corrects = (db.query(M.RunCostDocument)
                    .filter(M.RunCostDocument.external_id == b["correction"]["of_ksef"]).first())
    doc = M.RunCostDocument(
        project_id=None, run_id=None, doc_type=doc_type,
        supplier=_supplier_name(db, row.seller_nip, b["seller"]["name"]), seller_tax_id=row.seller_nip,
        doc_number=p["number"][:100], external_id=row.ksef_number, doc_date=p["issue_date"],
        currency=p["currency"][:10], total_amount=float(b["totals"]["net"]),
        tax_amount=float(b["totals"]["vat"]), company_id=row.company_id, company_source="ksef",
        corrects_document_id=corrects.id if corrects else None,
        notes=f"Imported from KSeF {row.ksef_number} by {actor}. The XML in KSeF is the invoice; "
              f"totals are NET, VAT {b['totals']['vat']}, gross {b['totals']['gross']}.")
    if (doc.currency or "PLN").upper() != "USD" and doc.doc_date:
        from .. import nbp

        try:
            doc.fx_rate_usd = nbp.resolve_for_document(db, doc.currency, doc.doc_date)["rate_usd"]
        except nbp.NbpError as e:
            raise HTTPException(502, f"could not resolve an NBP rate: {e}") from e
    db.add(doc)
    db.flush()
    if p["kind"] == "correction":
        # One position per rate, the difference KSeF states: the money of a
        # correction, without re-reading its before and after rows.
        for i, (rate, t) in enumerate((b["totals"].get("rates") or {}).items()):
            db.add(M.RunCostLine(document_id=doc.id, position=i, label=f"Korekta {p['number']} ({rate})",
                                 qty=1.0, unit_price=float(t["net"]), currency=doc.currency))
    else:
        for i, ln in enumerate(b.get("lines") or []):
            db.add(M.RunCostLine(document_id=doc.id, position=i, label=(ln["name"] or "")[:300],
                                 qty=float(ln["qty"]), unit_price=float(ln["unit_net"]), currency=doc.currency,
                                 notes=f"VAT {ln['vat_rate']}"))
    row.status, row.document_id = "imported", doc.id
    storage.put_bytes(f"documents/{doc.id}/ksef-{row.ksef_number}.xml", xml, "application/xml")
    att = M.RunAttachment(document_id=doc.id, filename=f"KSeF-{row.ksef_number}.xml",
                          content_type="application/xml", size_bytes=len(xml),
                          minio_key=f"documents/{doc.id}/ksef-{row.ksef_number}.xml")
    db.add(att)
    db.flush()
    doc.attachment_id = att.id
    db.flush()
    return doc


def inbox_json(row: M.KsefInvoice) -> dict:
    return {"id": row.id, "company_id": row.company_id, "side": row.side, "ksef_number": row.ksef_number,
            "invoice_number": row.invoice_number, "invoice_type": row.invoice_type, "issue_date": row.issue_date,
            "seller_nip": row.seller_nip, "seller_name": row.seller_name, "buyer_nip": row.buyer_nip,
            "buyer_name": row.buyer_name, "net": str(row.net) if row.net is not None else None,
            "vat": str(row.vat) if row.vat is not None else None,
            "gross": str(row.gross) if row.gross is not None else None, "currency": row.currency,
            "has_xml": bool(row.xml_key), "status": row.status, "sales_invoice_id": row.sales_invoice_id,
            "document_id": row.document_id, "note": row.note, "received_at": row.received_at}
