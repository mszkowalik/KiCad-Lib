"""Sales invoices (decision 0066): exact amounts, the monthly series, the FA(3)
XML the schema accepts, the flow from draft to issued, corrections, advances,
recurring invoices and the PDF.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_sales_invoices.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import companies as C
from app.services.invoicing import amounts as A
from app.services.invoicing import fa3, numbering
from app.services.invoicing import pdf as P
from app.services.invoicing import service as S


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
def seller(db):
    c = C.by_key(db, "7sigma")
    c.issues_invoices = True
    c.place_of_issue = c.place_of_issue or "Kraków"
    c.bank_name, c.bank_account = "TEST BANK", "00 0000 0000 0000 0000 0000 0000"
    # A year no real invoice uses, so the series start empty.
    return c


@pytest.fixture
def buyer(db):
    cust = M.Customer(name="TEST-SALES-BUYER", legal_name="TEST BUYER SP. Z O.O.", tax_id="521-354-52-23",
                      address_l1="ul. Testowa 1", address_l2="00-001 Warszawa", payment_terms_days=14)
    db.add(cust)
    db.flush()
    return cust


LINES = [{"name": "Usługa konsultacyjna", "qty": 1, "unit_net": "3400", "vat_rate": "23"},
         {"name": "Moduł", "qty": "3", "unit_net": "0.10", "vat_rate": "8"}]


def test_amounts_are_exact_and_vat_is_per_position():
    lines = A.lines(LINES)
    assert lines[1]["net"] == "0.30" and lines[1]["vat"] == "0.02"
    t = A.totals(lines)
    assert t == {"net": "3400.30", "vat": "782.02", "gross": "4182.32",
                 "rates": {"23": {"net": "3400.00", "vat": "782.00"}, "8": {"net": "0.30", "vat": "0.02"}}}
    assert A.rate("0") == "0 KR" and A.rate("np") == "np I" and A.rate("23%") == "23"
    with pytest.raises(ValueError):
        A.rate("19")


def test_the_amount_in_words():
    assert A.in_words(Decimal("3690.00")) == "trzy tysiące sześćset dziewięćdziesiąt złotych 0/100"
    assert A.in_words("1001.01") == "tysiąc jeden złotych 1/100"
    assert A.in_words("29105.49") == "dwadzieścia dziewięć tysięcy sto pięć złotych 49/100"


def test_each_series_counts_on_its_own_and_restarts_monthly(db, seller, buyer):
    day = "2049-03-15"
    a = S.create(db, company_id=seller.id, kind="vat", customer_id=buyer.id, issue_date=day, lines=LINES)
    b = S.create(db, company_id=seller.id, kind="vat", customer_id=buyer.id, issue_date=day, lines=LINES)
    p = S.create(db, company_id=seller.id, kind="proforma", customer_id=buyer.id, issue_date=day, lines=LINES)
    assert (a.number, b.number, p.number) == ("01/03/2049", "02/03/2049", "PROF 01/03/2049")
    assert (a.status, p.status) == ("draft", "issued")
    assert numbering.next_number(db, seller.id, "vat", date(2049, 4, 1)) == "01/04/2049"
    with pytest.raises(HTTPException):
        S.create(db, company_id=seller.id, kind="vat", customer_id=buyer.id, issue_date=day,
                 lines=LINES, number="1/03/2049")   # the same number without its leading zero


def test_a_company_with_its_own_system_gets_no_invoices(db, buyer):
    nine = C.by_key(db, "9sigma")
    nine.issues_invoices = False
    with pytest.raises(HTTPException):
        S.create(db, company_id=nine.id, kind="vat", customer_id=buyer.id, lines=LINES)


def test_a_vat_draft_writes_xml_the_schema_accepts_and_is_issued_by_ksef(db, seller, buyer, monkeypatch):
    inv = S.create(db, company_id=seller.id, kind="vat", customer_id=buyer.id, issue_date="2049-05-02",
                   lines=LINES, extra_info=["Zamówienie 12/2049"])
    xml = fa3.build(inv)
    assert fa3.validate(xml) == []
    assert b"<RodzajFaktury>VAT</RodzajFaktury>" in xml and b"<P_13_2>0.30</P_13_2>" in xml
    stored = {}
    monkeypatch.setattr("app.services.storage.put_bytes", lambda k, d, ct="": stored.__setitem__(k, d))
    S.issue(db, inv, ksef_number="8513262910-20490502-0123456789AB-CD", xml=xml)
    assert inv.status == "issued" and inv.ksef_hash == S.ksef_hash(xml) and stored
    with pytest.raises(HTTPException):
        S.update(db, inv, {"lines": LINES[:1]})   # an issued invoice changes only by a correction
    with pytest.raises(HTTPException):
        S.issue(db, inv, ksef_number="not-a-ksef-number")


def test_the_schema_check_catches_a_broken_document(db, seller, buyer):
    inv = S.create(db, company_id=seller.id, kind="vat", customer_id=buyer.id, issue_date="2049-05-03",
                   lines=LINES)
    xml = fa3.build(inv).replace(b"<P_15>", b"<P_15X>").replace(b"</P_15>", b"</P_15X>")
    assert fa3.validate(xml)


def test_a_correction_states_the_difference(db, seller, buyer):
    inv = S.create(db, company_id=seller.id, kind="vat", customer_id=buyer.id, issue_date="2049-06-01",
                   lines=LINES[:1])
    inv.status = "issued"
    kor = S.correct(db, inv, issue_date="2049-06-05", reason="błędna cena")
    S.update(db, kor, {"lines": [{"name": "Usługa konsultacyjna", "qty": 1, "unit_net": "3000", "vat_rate": "23"}]})
    assert kor.number == "KOR 01/06/2049" and kor.corrects_id == inv.id
    assert kor.amount_due == Decimal("-492.00")
    xml = fa3.build(kor)
    assert fa3.validate(xml) == []
    assert b"<P_13_1>-400.00</P_13_1>" in xml and b"<StanPrzed>1</StanPrzed>" in xml
    assert b"<NrKSeFN>1</NrKSeFN>" in xml   # the corrected invoice had no KSeF number


def test_an_advance_takes_its_vat_from_the_gross(db, seller, buyer):
    adv = S.create(db, company_id=seller.id, kind="advance", customer_id=buyer.id, issue_date="2049-07-28",
                   order_lines=[{"name": "CE-DONGLE V3", "qty": 250, "unit_net": "450", "vat_rate": "23"}],
                   advance_gross="83025.00")
    assert adv.number == "ZAL 01/07/2049" and adv.paid
    assert (adv.net_total, adv.vat_total, adv.gross_total) == (Decimal("67500.00"), Decimal("15525.00"),
                                                               Decimal("83025.00"))
    xml = fa3.build(adv)
    assert fa3.validate(xml) == [] and b"<RodzajFaktury>ZAL</RodzajFaktury>" in xml


def test_a_recurring_invoice_is_dated_the_last_day_and_only_once(db, seller, buyer):
    tpl = M.SalesInvoiceTemplate(company_id=seller.id, key="test-monthly", customer_id=buyer.id, day="last",
                                 lines=[LINES[0]], active=True)
    db.add(tpl)
    db.flush()
    inv = S.generate(db, tpl, "2049-02")
    assert inv.issue_date == "2049-02-28" and inv.template_key == "test-monthly"
    with pytest.raises(HTTPException):
        S.generate(db, tpl, "2049-02")


def test_the_pdf_prints_the_qr_code_once_ksef_has_the_invoice(db, seller, buyer):
    inv = S.create(db, company_id=seller.id, kind="vat", customer_id=buyer.id, issue_date="2049-08-01",
                   lines=LINES)
    page, images = P.build_html(inv, preview=True)
    assert "PODGLĄD" in page and not images
    inv.status, inv.ksef_number, inv.ksef_hash = "issued", "8513262910-20490801-0123456789AB-CD", "abc"
    page, images = P.build_html(inv, preview=False)
    assert "qr.png" in images and "8513262910-20490801-0123456789AB-CD" in page
    assert P.qr_url("8513262910", "2049-08-01", "abc") == "https://qr.ksef.mf.gov.pl/invoice/8513262910/01-08-2049/abc"
    pdf = P.render(inv)
    assert pdf.startswith(b"%PDF")


def test_the_old_register_is_imported_as_printed():
    doc = {"typ": "korekta", "status": "wystawiona", "numer": "KOR 01/01/2049", "tytul": "FAKTURA VAT - KOREKTA",
           "data_wystawienia": "2049-01-31", "data_sprzedazy": "2049-01-31", "miejsce": "Kraków",
           "sprzedawca": {"nazwa": "S", "adres1": "a", "adres2": "b", "nip": "8513262910"},
           "nabywca": {"nazwa": "B", "adres1": "c", "adres2": "d", "nip": "521-354-52-23"},
           "pozycje": [{"lp": 1, "nazwa": "X", "jm": "szt.", "ilosc": 1.0, "cena_netto": 10.0, "netto": 10.0,
                        "vat_proc": 23, "vat": 2.3, "brutto": 12.3}],
           "sumy": {"netto": 10.0, "vat": 2.3, "brutto": 12.3, "stawki": {"23": {"netto": 10.0, "vat": 2.3}}},
           "platnosc": {"termin": "2049-02-14", "zaplacono": False}, "do_zaplaty": 12.31,
           "korekta": {"przyczyna": "zmiana", "tresc_przed": ["a"], "tresc_po": ["b"]},
           "uwagi": ["kwota na dokumencie"], "zrodlo": "import: PDF", "pliki": {}}
    inv = S.from_register(doc, 1)
    assert (inv.kind, inv.status, inv.buyer_nip) == ("correction", "issued", "5213545223")
    assert inv.amount_due == Decimal("12.31")      # as printed, not recomputed
    assert inv.body["correction"]["reason"] == "zmiana"
