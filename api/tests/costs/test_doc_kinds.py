"""What a supplier document is in law, the VAT the books may deduct from it,
and the customs document of an import (decision 0087).

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_doc_kinds.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import run_costs as RC
from app.services import companies as C
from app.services import company_books as B
from app.services import customs, doc_kinds, run_actuals, storage
from app.services.ksef import sync as Y


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def seven(db):
    return C.by_key(db, "7sigma")


@pytest.fixture
def stored(monkeypatch):
    """The XML would go to MinIO, which a rolled-back test must not fill."""
    kept = {}
    monkeypatch.setattr(storage, "put_bytes", lambda key, data, ct: kept.__setitem__(key, data))
    return kept


def _doc(db, company, day, vat, kind="", vat_rule="", net=100.0):
    d = M.RunCostDocument(doc_type="invoice", supplier="TEST-KINDS", doc_number=f"K-{day}-{kind}-{vat_rule}",
                          doc_date=day, currency="PLN", company_id=company.id, total_amount=net, tax_amount=vat,
                          kind=kind, vat_rule=vat_rule)
    db.add(d)
    db.flush()
    db.add(M.RunCostLine(document_id=d.id, position=0, label="x", qty=1, unit_price=net, allocate="overhead",
                         overhead_category="other"))
    db.flush()
    db.refresh(d)
    return d


def test_the_share_follows_the_paper_and_the_limit():
    share = doc_kinds.deductible_share
    assert share("invoice", "") == 1 and share("customs_document", "") == 1 and share("simplified_invoice", "") == 1
    assert share("receipt", "") == 0 and share("debit_note", "") == 0 and share("policy", "") == 0
    assert share("invoice", "car_mixed") == Decimal("0.5")
    assert share("invoice", "accommodation_catering") == 0 and share("receipt", "car_mixed") == 0
    # Nobody decided yet: the VAT counts, as before, so a gap never hides VAT.
    assert share("", "") == 1
    with pytest.raises(ValueError):
        doc_kinds.check("faktura", "")
    with pytest.raises(ValueError):
        doc_kinds.check("invoice", "fuel")


def test_the_books_deduct_only_what_the_law_allows(db, seven):
    _doc(db, seven, "2049-03-05", 23.0, "invoice")
    _doc(db, seven, "2049-03-06", 46.0, "invoice", "car_mixed")
    _doc(db, seven, "2049-03-07", 8.0, "invoice", "accommodation_catering")
    _doc(db, seven, "2049-03-08", 10.0, "receipt")
    _doc(db, seven, "2049-03-09", 5.0)                              # not decided yet
    year = B.year(db, seven.id, 2049)
    march = year["months"][2]
    assert (march["purchase_vat"], march["purchase_vat_excluded"]) == ("51.00", "41.00")
    assert year["totals"]["purchase_vat_excluded"] == "41.00"


def test_a_kind_is_written_on_a_closed_batch_s_document(db, seven, monkeypatch):
    """The lock of decision 0044 covers money; the kind moves none."""
    d = _doc(db, seven, "2049-04-02", 23.0)
    monkeypatch.setattr(run_actuals, "closed_lock", lambda db_, doc, closed=None: [
        {"run_id": 1, "label": "Batch 1", "closed_at": "2049-06-01", "closed_by": "x"}])
    with pytest.raises(HTTPException):
        RC.update_document(d.id, RC.DocumentPatch(kind="debit_note"), db=db)
    out = RC.put_document_kind(d.id, RC.KindIn(kind="debit_note"), db=db)
    assert (d.kind, out["kind"], out["vat_deductible_share"]) == ("debit_note", "debit_note", "0")
    row = db.query(M.AuditLog).filter_by(action="run.document.kind", entity_id=str(d.id)).one()
    assert row.details["before"] == {"kind": "", "vat_rule": ""}


def test_a_kind_outside_the_list_and_a_transfer_s_kind_are_refused(db, seven):
    d = _doc(db, seven, "2049-04-03", 23.0)
    with pytest.raises(HTTPException) as e:
        RC.put_document_kind(d.id, RC.KindIn(kind="faktura"), db=db)
    assert e.value.status_code == 422
    d.doc_type = "transfer"
    with pytest.raises(HTTPException):
        RC.put_document_kind(d.id, RC.KindIn(kind="invoice"), db=db)
    assert RC.put_document_kind(d.id, RC.KindIn(kind="transfer"), db=db)["kind"] == "transfer"


def test_ksef_says_what_the_invoice_is_and_a_choice_stays(db, seven):
    parsed = {"kind": "vat", "number": "FV 1", "issue_date": "2049-02-04", "sale_date": "2049-02-04",
              "currency": "PLN", "body": {"totals": {"net": "100.00", "vat": "23.00", "gross": "123.00"}}}
    fresh = _doc(db, seven, "2049-02-04", 23.0)
    Y.apply_fiscal(fresh, SimpleNamespace(received_at="", ksef_number="K1", invoice_type="Zal"), parsed)
    assert fresh.kind == "advance_invoice"
    chosen = _doc(db, seven, "2049-02-05", 23.0, "simplified_invoice")
    Y.apply_fiscal(chosen, SimpleNamespace(received_at="", ksef_number="K2", invoice_type="Vat"), parsed)
    assert chosen.kind == "simplified_invoice"


def _zc299(nip, mrn="49PL44302A000001R1", vat="677.00"):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ZC299 xmlns="http://www.e-clo.pl/ZEFIR2/eZefir2/xsd/v6_0/ZC299.xsd" DataUtworzenia="2049-02-28T11:25:16">
 <PoswiadczoneZgloszenie MRN="{mrn}" DataPrzyjecia="2049-02-28" OgolnaWartoscFaktur="733.36" UCZgloszenia="PL443020">
  <Transakcja WalutaFaktur="USD" KursWaluty="4.01310"/>
  <Towar NumerPozycji="1">
   <DokumentWymagany Kod="N703" Numer="9557211086"/>
   <DokumentWymagany Kod="N935" Numer="W204902200414673"/>
   <Oplata TypOplaty="A00" Kwota="0.00" PodstawaOplaty="2943.00" Stawka="0.000"/>
   <Oplata TypOplaty="B00" Kwota="{vat}" PodstawaOplaty="2943.00" Stawka="23.000"/>
  </Towar>
  <PGZglaszajacy EORI="PL527002239100000" Nazwa="DHL EXPRESS (POLAND) SP.Z O.O."/>
  <PGNadawca Nazwa="FACTORY CO.,LTD"/>
  <PGOdbiorca EORI="PL{nip}00000" Nazwa="ODBIORCA"/>
  <PGSprzedajacy Nazwa="SELLER (HONGKONG) CO., LIMITED"/>
 </PoswiadczoneZgloszenie>
</ZC299>""".encode()


def _zc299h7(nip):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ZC299H7 DataUtworzenia="2049-11-18T01:05:40">
 <PoswiadczoneZgloszenie MRN="49PL33104B000002R2" DataPrzyjecia="2049-11-18T00:30:21" UCZgloszenia="PL331040">
  <Eksporter Nazwa="EXPORTER LTD"/>
  <PGImporter EORI="PL{nip}00000"/>
  <Towar NrPozycji="1">
   <DokumentWymagany Kod="N703" Numer="4813350684"/>
   <DokumentWymagany Kod="N935" Numer="W204911120044775"/>
   <Oplata Kwota="89" MetodaPlatnosci="R" Stawka="23" TypOplaty="B00"/>
   <Wartosc Waluta="USD" Wartosc="52.1"/>
  </Towar>
  <PGZglaszajacy EORI="PL527002239100000"/>
 </PoswiadczoneZgloszenie>
</ZC299H7>""".encode()


def _zc429(nip):
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<ZC429 xmlns="http://www.mf.gov.pl/xsd/AISP/ZC429">
 <preparationDateAndTime>2049-08-13T21:17:27</preparationDateAndTime>
 <Declaration>
  <mrn>49PL44302D000003R3</mrn>
  <declarationAcceptanceDate>2049-08-13T20:51:00</declarationAcceptanceDate>
  <Importer><identificationNumber>PL{nip}00000</identificationNumber></Importer>
  <Declarant><identificationNumber>PL527002239100000</identificationNumber></Declarant>
  <CustomsOfficeOfDeclaration><referenceNumber>PL443020</referenceNumber></CustomsOfficeOfDeclaration>
  <GoodsShipments>
   <invoiceCurrency>USD</invoiceCurrency>
   <totalAmountInvoiced>4888.53</totalAmountInvoiced>
   <Exporter><name>FACTORY CO.,LTD.</name></Exporter>
   <GoodsItem>
    <SupportingDocument><referenceNumber>W2049073002193524</referenceNumber><type>N935</type></SupportingDocument>
    <TransportDocument><referenceNumber>8580762293</referenceNumber><type>N703</type></TransportDocument>
    <DutiesAndTaxes><taxType>A00</taxType><payableTaxAmount>137.00</payableTaxAmount></DutiesAndTaxes>
    <DutiesAndTaxes><taxType>B00</taxType><payableTaxAmount>3349.00</payableTaxAmount>
     <TaxBase><taxAmount>3348.57</taxAmount></TaxBase></DutiesAndTaxes>
   </GoodsItem>
  </GoodsShipments>
 </Declaration>
</ZC429>""".encode()


def test_the_three_declaration_formats_read_the_same_facts(seven):
    full = customs.parse(_zc299(seven.nip))
    assert (full.message, full.mrn, full.accepted, full.created) == ("ZC299", "49PL44302A000001R1", "2049-02-28",
                                                                     "2049-02-28")
    assert (full.importer_nip, full.vat, full.duty, full.invoices, full.awbs) == (
        seven.nip, Decimal("677.00"), Decimal("0.00"), ["W204902200414673"], ["9557211086"])
    assert (full.exporter, full.seller, full.invoice_amount) == ("FACTORY CO.,LTD", "SELLER (HONGKONG) CO., LIMITED",
                                                                 Decimal("733.36"))
    h7 = customs.parse(_zc299h7(seven.nip))
    assert (h7.accepted, h7.importer_nip, h7.vat, h7.invoice_currency, h7.invoice_amount) == (
        "2049-11-18", seven.nip, Decimal("89"), "USD", Decimal("52.1"))
    plus = customs.parse(_zc429(seven.nip))
    # The PAYABLE amount, rounded by customs, not the calculated one.
    assert (plus.mrn, plus.vat, plus.duty, plus.invoices, plus.awbs) == (
        "49PL44302D000003R3", Decimal("3349.00"), Decimal("137.00"), ["W2049073002193524"], ["8580762293"])


def test_a_debt_or_release_notice_is_not_the_customs_document():
    with pytest.raises(customs.CustomsError, match="customs-debt notice"):
        customs.parse(b'<ZCX91><mrn>49PL44302D000003R3</mrn></ZCX91>')
    with pytest.raises(customs.CustomsError, match="release notice"):
        customs.parse(b'<PW229 MRN="x"/>')
    with pytest.raises(customs.CustomsError, match="not XML"):
        customs.parse(b"\xc6io\x7a not xml")


def test_a_declaration_files_once_and_its_vat_counts_from_the_month_received(db, seven, stored):
    doc, created = customs.record(db, _zc299(seven.nip), filename="ZC299_x.xml", received_date="2049-03-02",
                                  actor="test")
    assert created and (doc.kind, doc.doc_number, doc.external_id) == ("customs_document", "49PL44302A000001R1",
                                                                       "49PL44302A000001R1")
    assert (doc.company_id, doc.currency, doc.total_amount, doc.tax_amount) == (seven.id, "PLN", 0.0, 677.0)
    assert (doc.doc_date, doc.sale_date, doc.received_date) == ("2049-02-28", "2049-02-28", "2049-03-02")
    assert doc.attachment_id and list(stored.values()) == [_zc299(seven.nip)]
    again, created = customs.record(db, _zc299(seven.nip), filename="copy.xml", actor="test")
    assert again.id == doc.id and not created and len(stored) == 1
    # It moves no money, reconciles, and its VAT waits for the month it arrived.
    assert run_actuals.document_json(doc, db=db)["reconciled"]
    months = B.year(db, seven.id, 2049)["months"]
    assert (months[1]["purchase_vat"], months[2]["purchase_vat"]) == ("0.00", "677.00")


def test_a_declaration_of_another_importer_is_refused(db, stored):
    with pytest.raises(HTTPException) as e:
        customs.record(db, _zc299("1111111111"), actor="test")
    assert e.value.status_code == 422 and "none of the companies" in e.value.detail
    with pytest.raises(HTTPException) as e:
        customs.record(db, b'<ZC291 MRN="x"/>', actor="test")
    assert e.value.status_code == 422 and "debt notice" in e.value.detail
