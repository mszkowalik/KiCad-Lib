"""Company overhead and the company books (decision 0068).

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_company_books.py -q
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
from app.services import companies as C
from app.services import company_books as B
from app.services import run_actuals as ra
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
def world(db):
    c = C.by_key(db, "7sigma")
    c.issues_invoices, c.tax_form = True, "pit_linear"
    cust = M.Customer(name="TEST-BOOKS-BUYER", legal_name="BOOKS BUYER", tax_id="5213545223",
                      address_l1="a", address_l2="b")
    db.add(cust)
    db.flush()
    return SimpleNamespace(c=c, cust=cust)


def _doc(db, company, day, lines, tax=None):
    doc = M.RunCostDocument(doc_type="invoice", supplier="TEST-BOOKS-SUPPLIER", doc_number=f"B-{day}",
                            doc_date=day, currency="PLN", company_id=company.id, tax_amount=tax,
                            total_amount=sum(q * p for q, p, _a, _c in lines))
    db.add(doc)
    db.flush()
    for i, (q, p, allocate, cat) in enumerate(lines):
        db.add(M.RunCostLine(document_id=doc.id, position=i, label=f"l{i}", qty=q, unit_price=p,
                             allocate=allocate, overhead_category=cat,
                             plan_key="parts:pool" if allocate == "pooled" else ""))
    db.flush()
    db.refresh(doc)
    return doc


def test_an_overhead_position_is_the_company_s_and_keeps_the_register_closed(db, world):
    doc = _doc(db, world.c, "2049-02-10", [(1, 300.0, "overhead", "leasing"), (1, 50.0, "none", "")])
    li = next(li for li in doc.lines if li.allocate == "overhead")
    assert ra.line_destination(li, doc) == ("overhead", None)
    a = ra.document_json(doc, db=db)["assignment"]
    assert a["overhead"] == pytest.approx(300.0) and a["unassigned"] == pytest.approx(50.0)
    assert ra.invoice_register(db)["summary"]["gap_usd"] == pytest.approx(0.0)


def test_the_books_count_revenue_costs_vat_and_a_linear_tax(db, world):
    lines = [{"name": "Usługa", "qty": 1, "unit_net": "10000", "vat_rate": "23"}]
    inv = S.create(db, company_id=world.c.id, kind="vat", customer_id=world.cust.id, issue_date="2049-01-31",
                   lines=lines)
    inv.status = "issued"
    adv = S.create(db, company_id=world.c.id, kind="advance", customer_id=world.cust.id, issue_date="2049-01-20",
                   order_lines=lines, advance_gross="1230.00")
    adv.status = "issued"
    _doc(db, world.c, "2049-01-15", [(1, 2000.0, "overhead", "telecom"), (10, 100.0, "pooled", "")], tax=690.0)
    db.flush()
    y = B.year(db, world.c.id, 2049)
    jan = y["months"][0]
    assert jan["revenue_net"] == "10000.00"            # the advance is no revenue
    assert jan["advances_net"] == "1000.00"
    assert jan["costs_net"] == "3000.00" and jan["costs"]["overhead"] == "2000.00" and jan["costs"]["stock"] == "1000.00"
    assert jan["income"] == "7000.00"
    assert jan["sales_vat"] == "2530.00"               # the advance's VAT counts
    assert jan["vat_estimate"] == "1840.00"
    assert jan["income_tax_estimate"] == "1330.00"     # 19 % of 7000
    assert y["overhead"] == {"telecom": "2000.00"}
    feb = y["months"][1]
    assert feb["income_tax_estimate"] == "0.00"        # nothing new year-to-date


def test_a_correction_counts_its_difference(db, world):
    inv = S.create(db, company_id=world.c.id, kind="vat", customer_id=world.cust.id, issue_date="2049-03-01",
                   lines=[{"name": "U", "qty": 1, "unit_net": "1000", "vat_rate": "23"}])
    inv.status = "issued"
    kor = S.correct(db, inv, issue_date="2049-03-05", reason="cena")
    S.update(db, kor, {"lines": [{"name": "U", "qty": 1, "unit_net": "800", "vat_rate": "23"}]})
    kor.status = "issued"
    db.flush()
    mar = B.year(db, world.c.id, 2049)["months"][2]
    assert mar["revenue_net"] == "800.00" and mar["sales_vat"] == "184.00"


def test_the_accountant_s_figure_replaces_the_last_one(db, world):
    B.set_entry(db, world.c.id, period="2049-01", kind="vat", amount="1800", status="estimated")
    B.set_entry(db, world.c.id, period="2049-01", kind="vat", amount="1840", status="final")
    jan = B.year(db, world.c.id, 2049)["months"][0]
    assert jan["accountant"]["vat"]["amount"] == "1840.00" and jan["accountant"]["vat"]["status"] == "final"
    with pytest.raises(HTTPException):
        B.set_entry(db, world.c.id, period="2049-13", kind="vat", amount="1")
    with pytest.raises(HTTPException):
        B.set_entry(db, world.c.id, period="2049-01", kind="beer", amount="1")


def test_the_scale_and_the_lump_sum():
    assert B._income_tax("pit_scale", Decimal(0), Decimal(30000), Decimal(0)) == Decimal("0.00")
    assert B._income_tax("pit_scale", Decimal(0), Decimal(100000), Decimal(0)) == Decimal("8400.00")
    assert B._income_tax("pit_scale", Decimal(0), Decimal(130000), Decimal(0)) == Decimal("14000.00")
    assert B._income_tax("lump", Decimal("8.5"), Decimal(0), Decimal(10000)) == Decimal("850.00")
    assert B._income_tax("", Decimal(0), Decimal(1), Decimal(1)) is None
