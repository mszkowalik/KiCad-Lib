"""A company's issued history and the files kept with a record (decision 0077).

A sales document issued elsewhere is recorded as printed, also for a company
that does not issue on the platform; the books read its advance and its
settlement the way they read KSeF's. A file is kept with its invoice or tax
entry and is never reached under another record.

Run from `api/`, with the dev database and MinIO up:
    python -m pytest tests/costs/test_record_history_and_files.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import companies as company_routes
from app.services import companies as C
from app.services import company_books as B
from app.services import record_files as RF
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
def nine(db):
    c = C.by_key(db, "9sigma")
    c.issues_invoices = False
    db.flush()
    return c


ORDER = [{"name": "CE_AQUA_V2", "qty": "100", "unit": "szt.", "unit_net": "320", "vat_rate": "23",
          "net": "32000", "vat": "7360"},
         {"name": "CE_DONGLE_V2", "qty": "420", "unit": "szt.", "unit_net": "220", "vat_rate": "23",
          "net": "92400", "vat": "21252"}]


def _record(db, company, kind, number, day, totals, advances=()):
    return S.record_history(db, company_id=company.id, kind=kind, number=number, issue_date=day, sale_date=day,
                            due_date="", buyer={"name": "TEST-HISTORY-BUYER", "nip": "9492163154"},
                            currency="PLN", lines=ORDER, totals=totals, advance_numbers=list(advances),
                            corrects_number="", paid=False, paid_date="", order_id=None, note="test", actor="test")


def test_a_company_that_does_not_issue_here_has_its_history_and_the_books_read_it(db, nine):
    with pytest.raises(HTTPException):
        S.issuing_company(db, nine.id)                       # it still issues nothing here
    adv = _record(db, nine, "advance", "ZAL 00001/10/2049", "2049-10-08",
                  {"net": "80000", "vat": "18400", "gross": "98400", "rates": {"23": {"net": "80000", "vat": "18400"}}})
    fin = _record(db, nine, "settlement", "FV 00001/11/2049", "2049-11-30",
                  {"net": "44400", "vat": "10212", "gross": "54612", "rates": {"23": {"net": "44400", "vat": "10212"}}},
                  advances=["ZAL 00001/10/2049"])
    assert adv.status == fin.status == "issued" and adv.source == fin.source == "import: document"
    assert S.advance_amounts(adv)["net"] == "80000.00"       # the advance, never the order
    assert B._sales_effect(db, adv) == {"revenue": 0, "advance": Decimal("80000.00"), "vat": Decimal("18400.00")}
    assert B._sales_effect(db, fin)["revenue"] == Decimal("124400")   # the whole order at the delivery
    assert adv.body["order"]["totals"]["net"] == "124400.00"
    assert fin.body["advance_refs"] == [{"ksef": "", "number": "ZAL 00001/10/2049"}]


def test_a_number_is_recorded_once(db, nine):
    t = {"net": "1", "vat": "0.23", "gross": "1.23"}
    _record(db, nine, "vat", "FV 00009/01/2049", "2049-01-31", t)
    with pytest.raises(HTTPException) as e:
        _record(db, nine, "vat", "FV  00009/01/2049", "2049-01-31", t)
    assert e.value.status_code == 409


def test_a_file_belongs_to_its_record_only(db, nine):
    t = {"net": "1", "vat": "0.23", "gross": "1.23"}
    a = _record(db, nine, "vat", "FV 00010/01/2049", "2049-01-31", t)
    b = _record(db, nine, "vat", "FV 00011/01/2049", "2049-01-31", t)
    f = RF.add(db, "sales_invoice", a, "FV-10.pdf", "application/pdf", b"%PDF-1.4 test", actor="test")
    assert f.company_id == nine.id and RF.content(RF.one(db, "sales_invoice", a.id, f.id)) == b"%PDF-1.4 test"
    with pytest.raises(HTTPException) as e:
        RF.one(db, "sales_invoice", b.id, f.id)
    assert e.value.status_code == 404
    assert [x["id"] for x in S.invoice_json(db, a, full=True)["files"]] == [f.id]
    with pytest.raises(HTTPException):
        RF.add(db, "sales_invoice", a, "empty.pdf", "application/pdf", b"", actor="test")


def test_a_tax_entry_file_is_reached_under_its_own_company(db, nine):
    seven = C.by_key(db, "7sigma")
    e = B.set_entry(db, nine.id, period="2049-03", kind="vat", amount="10", actor="test")
    f = RF.add(db, "tax_entry", e, "VAT-7.pdf", "application/pdf", b"%PDF notice", actor="test")
    assert company_routes._entry(db, nine.id, e.id) is e
    with pytest.raises(HTTPException):
        company_routes._entry(db, seven.id, e.id)
    assert B.year(db, nine.id, 2049)["months"][2]["accountant"]["vat"]["files"] == 1
    assert isinstance(f, M.RecordFile)


def test_a_sales_document_counts_in_the_month_of_its_service(db, nine):
    t = {"net": "100", "vat": "23", "gross": "123", "rates": {"23": {"net": "100", "vat": "23"}}}
    inv = S.record_history(db, company_id=nine.id, kind="vat", number="FV 00012/05/2049", issue_date="2049-05-05",
                           sale_date="2049-04-30", due_date="", buyer={"name": "TEST-HISTORY-BUYER"}, currency="PLN",
                           lines=[], totals=t, advance_numbers=[], corrects_number="", paid=False, paid_date="",
                           order_id=None, note="", actor="test")
    assert B.book_date(inv) == "2049-04-30"           # an April service invoiced on 5 May is April's
    months = {m["month"]: m for m in B.year(db, nine.id, 2049)["months"]}
    assert Decimal(months["2049-04"]["revenue_net"]) == Decimal("100") and Decimal(months["2049-05"]["revenue_net"]) == 0
    inv.sale_date = "2049-05-20"                      # issued before the service: the issue date counts
    assert B.book_date(inv) == "2049-05-05"


def test_a_final_advance_completes_its_order(db, nine):
    """Two advances pay the whole order and the last says so: no settlement
    follows, so the books count the order as revenue at the last one."""
    t1 = {"net": "80000", "vat": "18400", "gross": "98400", "rates": {"23": {"net": "80000", "vat": "18400"}}}
    t2 = {"net": "44400", "vat": "10212", "gross": "54612", "rates": {"23": {"net": "44400", "vat": "10212"}}}
    first = _record(db, nine, "advance", "ZAL 00001/03/2049", "2049-03-10", t1)
    last = _record(db, nine, "advance", "ZAL 00002/04/2049", "2049-04-10", t2)
    assert not S.is_final_advance(last)
    assert B._sales_effect(db, last) == {"revenue": 0, "advance": Decimal("44400.00"), "vat": Decimal("10212.00")}
    last.body = {**last.body, "final_advance": True}
    db.flush()
    assert S.is_final_advance(last) and not S.is_final_advance(first)
    assert B._sales_effect(db, last) == {"revenue": Decimal("124400.00"), "advance": 0, "vat": Decimal("10212.00")}
    months = {m["month"]: m for m in B.year(db, nine.id, 2049)["months"]}
    assert Decimal(months["2049-03"]["advances_net"]) >= 80000 and Decimal(months["2049-04"]["revenue_net"]) >= 124400


def test_an_imported_final_advance_is_read_from_its_title():
    inv = M.SalesInvoice(kind="advance", body={"title": "FAKTURA VAT ZALICZKOWA KOŃCOWA",
                                                  "totals": {"net": "120000.0"}})
    assert S.is_final_advance(inv) and S.order_net(inv) == Decimal("120000.0")
    inv.body = {"title": "FAKTURA VAT ZALICZKOWA", "totals": {"net": "120000.0"}}
    assert not S.is_final_advance(inv)
