"""The customs document of an import: the paper that gives the import VAT
(decision 0087).

For an import the input VAT comes from the customs document the importer
received (art. 86 ust. 2 pkt 2 lit. a of the VAT act), never from an invoice,
and not before the month it was received (art. 86 ust. 10b pkt 1). The tax
point is the day the customs debt arose (art. 19a ust. 9).

A courier (DHL Express, UPS) clears a parcel as our representative and mails
the certified declaration (Poświadczone zgłoszenie celne, PZC) to the importer
as XML, in one of three formats:

* ``ZC299`` — AIS/IMPORT, a full declaration, the data in attributes;
* ``ZC299H7`` — AIS/IMPORT, the H7 declaration of a low-value parcel;
* ``ZC429`` — AIS/IMPORT PLUS (from 2025), the data in elements.

The same courier also mails a customs-debt notice (ZC291, ZCX91) and a release
notice (PW229, PW429). The release notice is about the earlier procedure and
carries no money. The debt notice repeats the amounts, but the declaration is
the document, so only a PZC is read and anything else is refused.

The VAT and the duty are the PAYABLE amounts (``Kwota`` /
``payableTaxAmount``), which customs rounds to whole złoty, not the
calculated ones.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from .. import models as M
from ..routers.util import audit
from . import document_files

#: The root element of a certified declaration -> what it is.
FORMATS = {"ZC299": "AIS/IMPORT", "ZC299H7": "AIS/IMPORT H7", "ZC429": "AIS/IMPORT PLUS"}
#: Messages a courier sends beside the declaration, refused with a reason.
NOT_THE_DECLARATION = {
    "ZC291": "a customs-debt notice", "ZCX91": "a customs-debt notice",
    "PW229": "a release notice", "PW429": "a release notice", "PW215": "a release notice",
}


class CustomsError(ValueError):
    pass


@dataclass
class Declaration:
    message: str                 # ZC299 | ZC299H7 | ZC429
    mrn: str
    accepted: str                # YYYY-MM-DD, the acceptance of the declaration
    created: str                 # YYYY-MM-DD, the day customs wrote the message
    importer_id: str             # EORI, e.g. PL851326291000000
    importer_name: str = ""
    exporter: str = ""
    seller: str = ""
    declarant: str = ""          # the courier, by name or EORI
    office: str = ""             # the customs office of the declaration
    invoices: list[str] = field(default_factory=list)   # N935: the commercial invoice numbers
    awbs: list[str] = field(default_factory=list)       # N703: the air waybill numbers
    invoice_currency: str = ""
    invoice_amount: Decimal | None = None
    vat: Decimal = Decimal(0)    # B00, payable
    duty: Decimal = Decimal(0)   # A00, payable
    other: dict[str, Decimal] = field(default_factory=dict)

    @property
    def importer_nip(self) -> str:
        """The NIP inside a Polish EORI (PL + NIP + a branch suffix)."""
        e = (self.importer_id or "").upper()
        return e[2:12] if e.startswith("PL") and e[2:12].isdigit() else ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _amount(v: str | None) -> Decimal:
    try:
        return Decimal((v or "0").strip() or "0")
    except InvalidOperation as e:
        raise CustomsError(f"not an amount: {v!r}") from e


def _day(v: str | None) -> str:
    return (v or "").strip()[:10]


def _unique(values) -> list[str]:
    out: list[str] = []
    for v in values:
        v = (v or "").strip()
        if v and v not in out:
            out.append(v)
    return out


def _add_tax(d: Declaration, kind: str, amount: Decimal) -> None:
    if kind == "B00":
        d.vat += amount
    elif kind == "A00":
        d.duty += amount
    elif kind:
        d.other[kind] = d.other.get(kind, Decimal(0)) + amount


def _attribute_format(root: ET.Element, message: str) -> Declaration:
    """ZC299 and ZC299H7: one element per fact, the data in its attributes."""
    els: dict[str, list[ET.Element]] = {}
    for el in root.iter():
        els.setdefault(_local(el.tag), []).append(el)

    def first(tag: str) -> dict:
        return els[tag][0].attrib if els.get(tag) else {}

    head = first("PoswiadczoneZgloszenie")
    if not head.get("MRN"):
        raise CustomsError(f"{message} without an MRN")
    # The importer is PGImporter in H7 and the consignee (PGOdbiorca) in a
    # full declaration.
    importer = first("PGImporter") or first("PGOdbiorca")
    exporter = first("Eksporter") or first("PGNadawca")
    declarant = first("PGZglaszajacy") or first("PGPrzedstawiciel")
    required = [e.attrib for e in els.get("DokumentWymagany", [])]
    d = Declaration(
        message=message, mrn=head["MRN"], accepted=_day(head.get("DataPrzyjecia")),
        created=_day(root.attrib.get("DataUtworzenia")),
        importer_id=(importer.get("EORI") or "").strip(), importer_name=(importer.get("Nazwa") or "").strip(),
        exporter=(exporter.get("Nazwa") or "").strip(), seller=(first("PGSprzedajacy").get("Nazwa") or "").strip(),
        declarant=(declarant.get("Nazwa") or declarant.get("EORI") or "").strip(),
        office=(head.get("UCZgloszenia") or "").strip(),
        invoices=_unique(r.get("Numer") for r in required if r.get("Kod") == "N935"),
        awbs=_unique(r.get("Numer") for r in required if r.get("Kod") == "N703"),
    )
    if message == "ZC299H7":
        value = first("Wartosc")
        d.invoice_currency = (value.get("Waluta") or "").strip()
        d.invoice_amount = _amount(value.get("Wartosc")) if value.get("Wartosc") else None
    else:
        d.invoice_currency = (first("Transakcja").get("WalutaFaktur") or "").strip()
        d.invoice_amount = _amount(head.get("OgolnaWartoscFaktur")) if head.get("OgolnaWartoscFaktur") else None
    for o in els.get("Oplata", []):
        _add_tax(d, (o.attrib.get("TypOplaty") or "").strip(), _amount(o.attrib.get("Kwota")))
    return d


def _element_format(root: ET.Element) -> Declaration:
    """ZC429: the data in child elements, under Declaration."""
    decl = next((c for c in root if _local(c.tag) == "Declaration"), None)
    if decl is None:
        raise CustomsError("ZC429 without a Declaration")

    def child(el: ET.Element | None, *path: str) -> ET.Element | None:
        for name in path:
            if el is None:
                return None
            el = next((c for c in el if _local(c.tag) == name), None)
        return el

    def text(el: ET.Element | None, *path: str) -> str:
        found = child(el, *path) if path else el
        return (found.text or "").strip() if found is not None else ""

    def children(el: ET.Element | None, name: str) -> list[ET.Element]:
        return [c for c in el if _local(c.tag) == name] if el is not None else []

    mrn = text(decl, "mrn")
    if not mrn:
        raise CustomsError("ZC429 without an MRN")
    shipments = children(decl, "GoodsShipments")
    items = [i for s in shipments for i in children(s, "GoodsItem")]
    docs = [(text(x, "type"), text(x, "referenceNumber"))
            for i in items for x in children(i, "SupportingDocument") + children(i, "TransportDocument")]
    docs += [(text(x, "type"), text(x, "referenceNumber"))
             for s in shipments for x in children(s, "SupportingDocument") + children(s, "TransportDocument")]
    d = Declaration(
        message="ZC429", mrn=mrn, accepted=_day(text(decl, "declarationAcceptanceDate")),
        created=_day(text(root, "preparationDateAndTime")),
        importer_id=text(decl, "Importer", "identificationNumber"),
        importer_name=text(decl, "Importer", "name"),
        exporter=next((text(s, "Exporter", "name") for s in shipments if text(s, "Exporter", "name")), ""),
        seller=next((text(s, "Seller", "name") for s in shipments if text(s, "Seller", "name")), ""),
        declarant=text(decl, "Declarant", "name") or text(decl, "Declarant", "identificationNumber"),
        office=text(decl, "CustomsOfficeOfDeclaration", "referenceNumber"),
        invoices=_unique(n for t, n in docs if t == "N935"),
        awbs=_unique(n for t, n in docs if t == "N703"),
    )
    if shipments:
        d.invoice_currency = text(shipments[0], "invoiceCurrency")
        amounts = [text(s, "totalAmountInvoiced") for s in shipments if text(s, "totalAmountInvoiced")]
        d.invoice_amount = sum((_amount(a) for a in amounts), Decimal(0)) if amounts else None
    for i in items:
        for t in children(i, "DutiesAndTaxes"):
            _add_tax(d, text(t, "taxType"), _amount(text(t, "payableTaxAmount")))
    return d


def parse(data: bytes) -> Declaration:
    """Read one certified declaration. Raises CustomsError for anything that
    is not one, naming what it is when it is a known courier message."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise CustomsError(f"not XML: {e}") from e
    message = _local(root.tag)
    if message in NOT_THE_DECLARATION:
        raise CustomsError(f"{message} is {NOT_THE_DECLARATION[message]}, not the certified declaration "
                           "(PZC: ZC299, ZC299H7 or ZC429), which is the customs document")
    if message not in FORMATS:
        raise CustomsError(f"{message} is not a certified customs declaration (ZC299, ZC299H7 or ZC429)")
    d = _element_format(root) if message == "ZC429" else _attribute_format(root, message)
    if not d.accepted:
        raise CustomsError(f"{d.message} {d.mrn} without an acceptance date")
    return d


def notes(d: Declaration, filename: str, actor: str) -> str:
    parts = [f"Certified customs declaration {d.message} ({FORMATS[d.message]}), MRN {d.mrn}, "
             f"accepted {d.accepted}. Import VAT (B00) {d.vat} PLN, duty (A00) {d.duty} PLN, as payable."]
    if d.other:
        parts.append("Other charges: " + ", ".join(f"{k} {v} PLN" for k, v in sorted(d.other.items())) + ".")
    who = [f"exporter {d.exporter}" if d.exporter else "",
           f"seller {d.seller}" if d.seller and d.seller != d.exporter else "",
           f"declarant {d.declarant}" if d.declarant else ""]
    if any(who):
        parts.append("; ".join(w for w in who if w).capitalize() + ".")
    if d.invoices:
        parts.append("Commercial invoice " + ", ".join(d.invoices) + ".")
    if d.awbs:
        parts.append("Air waybill " + ", ".join(d.awbs) + ".")
    if d.invoice_amount is not None:
        parts.append(f"Invoice value {d.invoice_amount} {d.invoice_currency}.")
    parts.append(f"Read from {filename or 'the XML'} by {actor or 'unknown'}. The money of the goods is on the "
                 "supplier's invoice; this document carries only the import VAT.")
    return " ".join(parts)


def record(db: Session, data: bytes, *, filename: str = "", received_date: str = "",
           actor: str = "") -> tuple[M.RunCostDocument, bool]:
    """File one certified declaration as a supplier document of kind
    `customs_document` (decision 0087), with the XML as its evidence.

    The document carries the import VAT and no money: `total_amount` is 0,
    because the goods are on the supplier's invoice and the courier's charges
    on the courier's. The MRN is its number and its external id, so the same
    declaration filed twice (one copy per forward) finds the first. The
    company is the importer's. `received_date` is the day the importer got the
    document, the earliest month of the deduction; empty means the day customs
    wrote the message. Returns (document, created). The caller commits."""
    from fastapi import HTTPException

    from . import access

    try:
        d = parse(data)
    except CustomsError as e:
        raise HTTPException(422, str(e)) from e
    if received_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", received_date):
        raise HTTPException(422, "received_date is YYYY-MM-DD")
    company = db.query(M.Company).filter(M.Company.nip == d.importer_nip).first() if d.importer_nip else None
    if company is None:
        raise HTTPException(422, f"the importer {d.importer_id or '(none)'} of {d.mrn} is none of the companies")
    access.require(db, {company.id})
    existing = (db.query(M.RunCostDocument)
                .filter(M.RunCostDocument.external_id == d.mrn, M.RunCostDocument.kind == "customs_document")
                .first())
    if existing is not None:
        return existing, False
    doc = M.RunCostDocument(
        project_id=None, run_id=None, doc_type="invoice", kind="customs_document",
        supplier=f"Urząd celny {d.office}".strip(), doc_number=d.mrn, external_id=d.mrn,
        doc_date=d.accepted, sale_date=d.accepted, received_date=received_date or d.created,
        currency="PLN", total_amount=0.0, tax_amount=float(d.vat),
        company_id=company.id, company_source="customs",
        notes=notes(d, filename, actor), created_by=(actor or "")[:100])
    db.add(doc)
    db.flush()
    a = document_files.add(db, doc, filename or f"{d.message}_{d.mrn}.xml", "application/xml", data)
    audit(db, "customs.document", "run_cost_document", doc.id,
          {"mrn": d.mrn, "message": d.message, "company_id": company.id, "vat": str(d.vat), "duty": str(d.duty),
           "received_date": doc.received_date, "attachment_id": a.id}, actor=actor or "user")
    return doc, True
