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
  document, or skips it with a reason. The document keeps the invoice's tax
  data beside its cost positions (`apply_fiscal`, decision 0084).
* **An invoice is in the inbox once per company that sees it.** An invoice
  7Sigma issues to 9SIGMA is 7Sigma's sales row and 9SIGMA's purchase row:
  `ksef_number` is unique per company, not across them.

A company's sync resumes `LOOKBACK_DAYS` before the newest issue date it read,
because the query is by ISSUE date and an invoice can reach KSeF days after
it: an offline or emergency-mode invoice is sent later, dated as issued. The
upsert is idempotent, so the overlap costs nothing but a longer list. The
first sync starts when KSeF 2.0 did. A rate limit stops the sync and records
until when; the next sync carries on. A KSeF error keeps what the sync fetched
before it and the error itself: the route commits both before it answers.
"""
from __future__ import annotations

import base64
import re
import xml.etree.ElementTree as ET
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
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
#: Days a sync reads back before the newest issue date it already holds. The
#: query is by issue date, and an invoice sent offline or in KSeF's emergency
#: mode arrives later than its date; 60 days still fit in one 90-day query.
LOOKBACK_DAYS = 60


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
    # Per company: an invoice between our two companies is one row for each.
    row = db.query(M.KsefInvoice).filter_by(company_id=company_id, ksef_number=num).first()
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
                     (date.fromisoformat(read_to) - timedelta(days=LOOKBACK_DAYS)) if read_to else K.KSEF2_START)
            try:
                metas = cl.metadata(side, start, date.today())
            except K.RateLimited as e:
                row.rate_limited_until = _now() + timedelta(seconds=e.seconds)
                out["limit"] = str(e)
                break
            new = 0
            for m in metas:
                existed = (db.query(M.KsefInvoice.id)
                           .filter_by(company_id=company.id, ksef_number=m.get("ksefNumber") or "").first())
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
    KSeF's figures — the invoice in KSeF is the binding one.

    A correction's figures in KSeF are the DIFFERENCE (FA(3) P_13_x, P_15). A
    record that keeps the state before (`correction.before_totals`) takes
    "before + KSeF's difference" as its totals after, so after minus before is
    KSeF's difference and nothing is subtracted twice. A record with no state
    before takes the difference and says so (`states_difference`)."""
    import copy

    from ..invoicing import amounts as IA
    from ..invoicing.service import _columns, correction_difference

    inv.ksef_number = row.ksef_number
    inv.ksef_hash = row.xml_hash or inv.ksef_hash
    inv.ksef_received_at = row.received_at
    if row.xml_key:
        inv.official_xml_key = row.xml_key
    if inv.status == "draft":
        inv.status = "issued"
    if parsed:
        b = copy.deepcopy(inv.body or {})
        pb = parsed["body"]
        is_correction = inv.kind == "correction"
        was = correction_difference(inv)["gross"] if is_correction else (b.get("totals") or {}).get("gross")
        for k in ("seller", "buyer", "lines", "totals", "payment", "bank", "extra_info"):
            if pb.get(k) is not None:
                b[k] = pb[k]
        if is_correction:
            cor = dict(b.get("correction") or {})
            pcor = pb.get("correction") or {}
            if cor.get("before_totals"):
                b["totals"] = IA.combine(cor["before_totals"], pb["totals"])
                cor.pop("states_difference", None)
            else:
                cor["states_difference"] = True
            if pcor.get("before_lines"):
                cor["before_lines"] = pcor["before_lines"]
            if pcor.get("of_kind"):
                cor["of_kind"] = pcor["of_kind"]
            b["correction"] = cor
        notes = list(b.get("notes") or []) + pb.get("notes", [])
        now = pb["totals"]["gross"]
        if was and abs(Decimal(str(was)) - Decimal(now)) > Decimal("0.01"):
            what = "difference" if is_correction else "gross"
            notes.append(f"the draft's {what} {was} differs from KSeF's {now}")
        b["notes"] = notes
        inv.body = b
        _columns(inv)


def _corrected(db: Session, company_id: int, cor: dict) -> int | None:
    """The platform's record of the invoice a correction read from KSeF
    corrects: by its KSeF number, else by its number. A next correction of
    that invoice then starts from the state after this one."""
    q = (db.query(M.SalesInvoice)
         .filter(M.SalesInvoice.company_id == company_id, M.SalesInvoice.status != "cancelled",
                 M.SalesInvoice.kind.in_(("vat", "advance", "settlement"))))
    if cor.get("of_ksef"):
        hit = q.filter(M.SalesInvoice.ksef_number == cor["of_ksef"]).first()
        if hit is not None:
            return hit.id
    want = _norm_number(cor.get("of_number") or "")
    if not want:
        return None
    return next((i.id for i in q.all() if _norm_number(i.number) == want), None)


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
        if inv.kind == "correction":
            inv.corrects_id = _corrected(db, company.id, parsed["body"].get("correction") or {})
        try:
            with db.begin_nested():
                db.add(inv)
                db.flush()
        except IntegrityError:
            # The platform already holds this number for another KSeF invoice.
            out["refused"].append({"number": row.invoice_number, "why": "the platform already has a "
                                   f"{inv.kind} invoice numbered {inv.number} with another KSeF number"})
            continue
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


class Linked(HTTPException):
    """The purchase already IS a supplier document, and the inbox row now
    points at it. A 409 to the caller and a state to keep: the route commits
    before it answers, where an ordinary refusal rolls back."""

    def __init__(self, detail: str):
        super().__init__(409, detail)


#: Words of a company name that say its legal form, not who it is.
_LEGAL_WORDS = {"spółka", "ograniczoną", "odpowiedzialnością", "komandytowa", "jawna", "akcyjna", "cywilna",
                "ltd", "limited", "gmbh", "inc", "corp", "llc", "sro"}


def _name_words(name: str) -> set[str]:
    """The words of a supplier's name that are not a legal form, case folded,
    three letters or more ("sp. z o.o." drops out by its length)."""
    return {w for w in re.findall(r"\w+", (name or "").casefold()) if len(w) >= 3 and w not in _LEGAL_WORDS}


def _number_key(n: str) -> str:
    """An invoice number with case, spaces and leading zeros dropped."""
    return re.sub(r"(?<!\d)0+(?=\d)", "", re.sub(r"\s+", "", (n or "").upper()))


def possible_duplicates(db: Session, row: M.KsefInvoice) -> list[M.RunCostDocument]:
    """Hand-entered supplier documents that may be this purchase.

    A document typed by hand has no seller NIP, so the exact guard (seller NIP
    and number) cannot see it. The rule: a document of the same company (or of
    no company yet) with NO seller tax id, whose number equals the invoice's
    once case, spaces and leading zeros are dropped, AND that has either the
    invoice's issue date or a word of the seller's name (legal forms such as
    "sp. z o.o." left out)."""
    want = _number_key(row.invoice_number)
    if not want:
        return []
    words = _name_words(row.seller_name)
    out = []
    for d in (db.query(M.RunCostDocument)
              .filter(M.RunCostDocument.seller_tax_id == "", M.RunCostDocument.doc_number != "",
                      M.RunCostDocument.doc_type != "transfer",
                      (M.RunCostDocument.company_id == row.company_id) | M.RunCostDocument.company_id.is_(None))
              .order_by(M.RunCostDocument.id).all()):
        if _number_key(d.doc_number) != want:
            continue
        if (d.doc_date or "")[:10] == row.issue_date or (words & _name_words(d.supplier)):
            out.append(d)
    return out


_WARSAW = ZoneInfo("Europe/Warsaw")


def received_day(stamp: str) -> str:
    """The Polish calendar day of KSeF's acquisition timestamp: the day KSeF
    gave the invoice its number, which IS the day the buyer received it (art.
    106na ust. 3 of the VAT act). A stamp just after midnight UTC is the next
    day in Poland. A stamp without a zone is taken as written."""
    s = (stamp or "").strip()
    if not s:
        return ""
    try:
        # KSeF may print 7 fractional digits; Python reads at most 6.
        t = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", s.replace("Z", "+00:00")))
    except ValueError:
        return s[:10]
    return (t.astimezone(_WARSAW) if t.tzinfo is not None else t).date().isoformat()


def apply_fiscal(doc: M.RunCostDocument, row: M.KsefInvoice, parsed: dict) -> list[str]:
    """Give a supplier document the invoice's tax data from its KSeF XML
    (decision 0084): the printed invoice as `body`, its sale, due and receipt
    dates, the VAT in PLN of an invoice in another currency, the VAT itself
    when nobody typed it, and the payment KSeF states when none is recorded.
    The invoice in KSeF is the binding one, so these replace what was typed.
    The net and the positions are never touched: they carry the money paths.
    A correction linked to the invoice it corrects (the same seller and
    number) changes nothing: it states a difference, not the invoice's page.
    Returns the fields that changed."""
    if parsed.get("kind") == "correction" and (doc.doc_type or "") != "correction":
        return []
    b = parsed["body"]
    t = b.get("totals") or {}
    pay = b.get("payment") or {}
    foreign = (parsed.get("currency") or "PLN").upper() != "PLN"
    want = {
        "body": b,
        "sale_date": parsed.get("sale_date") or "",
        "due_date": pay.get("due_date") or "",
        # KSeF states the receipt in its metadata; without it, a typed day stays.
        "received_date": received_day(row.received_at) or doc.received_date or "",
        "tax_amount_pln": A.d2(t["vat_pln"]) if foreign and t.get("vat_pln") else None,
    }
    if doc.tax_amount is None and t.get("vat") is not None:
        want["tax_amount"] = float(t["vat"])
    if not doc.paid_at and pay.get("paid") and pay.get("paid_date"):
        want["paid_at"] = pay["paid_date"]
    changed = []
    for k, v in want.items():
        old = getattr(doc, k)
        if k == "tax_amount_pln" and old is not None and v is not None and A.d2(old) == v:
            continue
        if old != v:
            setattr(doc, k, v)
            changed.append(k)
    return changed


def _link(db: Session, row: M.KsefInvoice, doc: M.RunCostDocument) -> None:
    """The inbox row points at the document that already holds the purchase;
    a hand-entered document learns the seller's NIP, so the exact guard finds
    it next time, and the invoice's tax data when the XML is here."""
    row.status, row.document_id = "imported", doc.id
    if not doc.seller_tax_id and row.seller_nip:
        doc.seller_tax_id = row.seller_nip
    xml = _xml_of(row)
    if xml is not None:
        apply_fiscal(doc, row, parse(xml))
    db.flush()


def import_purchase(db: Session, row: M.KsefInvoice, actor: str = "", client_factory=K.Client, *,
                    force: bool = False, link_to: int | None = None) -> M.RunCostDocument:
    """A purchase from the inbox as a supplier document, billed to the company
    that fetched it. Its positions name no destination yet: the register shows
    them unassigned until a person or an agent says where each one goes.

    * Already a document (its KSeF number, or the same seller NIP and number):
      the row is linked to it and `Linked` (409) is raised.
    * Perhaps a document typed by hand (`possible_duplicates`): 409 with the
      candidates, and nothing changes. `link_to` links the row to one of them;
      `force` imports it anyway.
    * A row whose document was deleted is not imported any more and imports
      again."""
    if row.side != "purchase":
        raise HTTPException(422, "only a purchase is imported as a supplier document")
    if row.status == "imported" and (row.document_id is None
                                     or db.get(M.RunCostDocument, row.document_id) is None):
        row.status, row.document_id = "new", None
    if row.status in ("imported", "skipped"):
        raise HTTPException(409, f"{row.ksef_number} is already {row.status}")
    if link_to is not None:
        target = db.get(M.RunCostDocument, link_to)
        if target is None or target.company_id not in (None, row.company_id):
            raise HTTPException(404, f"no supplier document {link_to} of this company")
        _link(db, row, target)
        return target
    dup = (db.query(M.RunCostDocument)
           .filter((M.RunCostDocument.external_id == row.ksef_number)
                   | ((M.RunCostDocument.seller_tax_id == row.seller_nip)
                      & (M.RunCostDocument.doc_number == row.invoice_number)
                      & (M.RunCostDocument.seller_tax_id != "")
                      & ((M.RunCostDocument.company_id == row.company_id)
                         | M.RunCostDocument.company_id.is_(None)))).first())
    if dup is not None:
        _link(db, row, dup)
        raise Linked(f"{row.invoice_number} is already supplier document {dup.id}; linked to it")
    if not force:
        cands = possible_duplicates(db, row)
        if cands:
            raise HTTPException(409, {
                "error": f"{row.invoice_number} of {row.seller_name or row.seller_nip} may already be "
                         f"entered by hand ({', '.join(f'document {d.id}' for d in cands)}). Link it to that "
                         "document, or import it as a new one.",
                "candidates": [{"id": d.id, "supplier": d.supplier, "doc_number": d.doc_number,
                                "doc_date": d.doc_date, "total_amount": d.total_amount, "currency": d.currency}
                               for d in cands],
                "hint": "document_id=<id> links it; force=true imports it anyway"})
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
    apply_fiscal(doc, row, p)
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


def fill_documents(db: Session) -> dict:
    """Give every supplier document that holds a KSeF purchase the invoice's
    tax data from the XML the inbox stored (decision 0084). Idempotent: a
    document already filled reports no change. The caller commits, or rolls
    back for a dry run."""
    out = {"checked": 0, "filled": [], "no_xml": [], "failed": []}
    rows = (db.query(M.KsefInvoice)
            .filter(M.KsefInvoice.side == "purchase", M.KsefInvoice.document_id.isnot(None))
            .order_by(M.KsefInvoice.id).all())
    for row in rows:
        doc = db.get(M.RunCostDocument, row.document_id)
        if doc is None:
            continue
        out["checked"] += 1
        xml = _xml_of(row)
        if xml is None:
            out["no_xml"].append({"document_id": doc.id, "ksef_number": row.ksef_number})
            continue
        try:
            changed = apply_fiscal(doc, row, parse(xml))
        except (ValueError, ET.ParseError) as e:
            out["failed"].append({"document_id": doc.id, "ksef_number": row.ksef_number, "error": str(e)[:200]})
            continue
        if changed:
            out["filled"].append({"document_id": doc.id, "ksef_number": row.ksef_number, "fields": changed})
    db.flush()
    return out


def inbox_json(row: M.KsefInvoice) -> dict:
    return {"id": row.id, "company_id": row.company_id, "side": row.side, "ksef_number": row.ksef_number,
            "invoice_number": row.invoice_number, "invoice_type": row.invoice_type, "issue_date": row.issue_date,
            "seller_nip": row.seller_nip, "seller_name": row.seller_name, "buyer_nip": row.buyer_nip,
            "buyer_name": row.buyer_name, "net": str(row.net) if row.net is not None else None,
            "vat": str(row.vat) if row.vat is not None else None,
            "gross": str(row.gross) if row.gross is not None else None, "currency": row.currency,
            "has_xml": bool(row.xml_key), "status": row.status, "sales_invoice_id": row.sales_invoice_id,
            "document_id": row.document_id, "note": row.note, "received_at": row.received_at}
