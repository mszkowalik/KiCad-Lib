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


# --- review fixes of 2026-10-04 -------------------------------------------------

LINES_10K = [{"name": "Usługa", "qty": 1, "unit_net": "10000", "vat_rate": "23"}]


@pytest.fixture
def batch(db, world):
    proj = M.Project(name="test-books-overhead", git_url="https://example.invalid/oh.git", display_currency="USD")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="OH1", run_date="2049-01-01", status="completed", qty=10,
                          company_id=world.c.id)
    db.add(run)
    db.flush()
    return SimpleNamespace(proj=proj, run=run)


def test_an_overhead_position_on_a_batch_document_is_charged_once(db, world, batch):
    from app.routers import run_costs as R

    out = R._create_document(batch.proj.id, R.DocumentIn(
        run_id=batch.run.id, supplier="TEST-OH", doc_number="OH-1", doc_date="2049-01-10", currency="USD",
        total_amount=150.0, company_id=world.c.id,
        lines=[R.LineIn(label="leasing", qty=1, unit_price=100.0, allocate="overhead", overhead_category="leasing",
                        run_id=batch.run.id, basis="per_device"),
               R.LineIn(label="assembly", qty=1, unit_price=50.0)]), db)
    li = db.query(M.RunCostLine).filter_by(document_id=out["id"], allocate="overhead").one()
    assert (li.run_id, li.project_id, li.basis) == (None, None, "per_run")
    # An older row that kept its batch is still the company's, never the batch's.
    db.add(M.RunCostLine(document_id=out["id"], position=9, label="old", qty=1, unit_price=7.0,
                         allocate="overhead", overhead_category="other", run_id=batch.run.id))
    db.flush()
    assert ra.run_actuals(db, batch.run)["direct"] == pytest.approx(50.0)
    added = R.add_line(out["id"], R.LineIn(label="phone", qty=1, unit_price=10.0, allocate="overhead",
                                           overhead_category="telecom", run_id=batch.run.id), db=db)
    assert added["run_id"] is None
    # Sending the position to the batch takes it off the overhead.
    R.update_line(li.id, R.LinePatch(run_id=batch.run.id), db=db)
    db.refresh(li)
    assert (li.allocate, li.run_id, li.overhead_category) == ("none", batch.run.id, "")


def test_a_split_share_can_be_company_overhead(db, world):
    from app.routers import run_costs as R

    doc = _doc(db, world.c, "2049-02-11", [(1, 300.0, "none", "")])
    parent = doc.lines[0]
    R.split_line(parent.id, R.SplitIn(children=[
        R.ChildIn(label="phone", amount=100.0, allocate="overhead", overhead_category="telecom"),
        R.ChildIn(label="lease", amount=200.0, allocate="overhead", overhead_category="leasing")]), db=db)
    kids = db.query(M.RunCostLine).filter_by(parent_line_id=parent.id).all()
    assert sorted(k.overhead_category for k in kids) == ["leasing", "telecom"]


def test_an_overhead_logistics_position_is_not_unspread_transport(db, world):
    doc = _doc(db, world.c, "2049-02-12", [(10, 5.0, "pooled", ""), (1, 20.0, "overhead", "travel")])
    for li in doc.lines:
        if li.allocate == "overhead":
            li.plan_key = "logistics:inbound"
    db.flush()
    reg = ra.invoice_register(db)
    assert not [u for u in reg["issues"]["unspread_transport"] if u["document_id"] == doc.id]


def test_imported_documents_count_as_printed(db, world):
    """A script advance printed the ORDER and the advance as the amount to pay;
    a script correction that printed no amounts before changed text only."""
    pos = [{"lp": 1, "nazwa": "Zamówienie", "jm": "szt.", "ilosc": 1, "cena_netto": 10000.0, "netto": 10000.0,
            "vat_proc": 23, "vat": 2300.0, "brutto": 12300.0}]
    sums = {"netto": 10000.0, "vat": 2300.0, "brutto": 12300.0, "stawki": {"23": {"netto": 10000.0, "vat": 2300.0}}}
    adv = S.from_register({"typ": "zaliczka", "status": "wystawiona", "numer": "ZAL 01/03/2049",
                           "data_wystawienia": "2049-03-10", "pozycje": pos, "sumy": sums,
                           "platnosc": {"zaplacono": True}, "do_zaplaty": 3690.0}, world.c.id)
    kor = S.from_register({"typ": "korekta", "status": "wystawiona", "numer": "1/KOR/03/2049",
                           "data_wystawienia": "2049-03-15", "pozycje": pos, "sumy": sums,
                           "korekta": {"przyczyna": "adres", "tresc_przed": ["a"], "tresc_po": ["b"]}}, world.c.id)
    db.add_all([adv, kor])
    db.flush()
    mar = B.year(db, world.c.id, 2049)["months"][2]
    assert (mar["revenue_net"], mar["advances_net"], mar["sales_vat"]) == ("0.00", "3000.00", "690.00")


def test_a_correction_of_an_advance_is_no_revenue(db, world):
    adv = S.create(db, company_id=world.c.id, kind="advance", customer_id=world.cust.id, issue_date="2049-04-10",
                   order_lines=LINES_10K, advance_gross="1230.00")
    adv.status = "issued"
    kor = S.correct(db, adv, issue_date="2049-04-20")
    S.update(db, kor, {"advance_gross": "615.00"})
    kor.status = "issued"
    db.flush()
    apr = B.year(db, world.c.id, 2049)["months"][3]
    assert (apr["revenue_net"], apr["advances_net"], apr["sales_vat"]) == ("0.00", "500.00", "115.00")


def test_a_settlement_brings_the_advances_into_revenue(db, world):
    adv = S.create(db, company_id=world.c.id, kind="advance", customer_id=world.cust.id, issue_date="2049-05-10",
                   order_lines=LINES_10K, advance_gross="1230.00")
    adv.status = "issued"
    # ROZ as the KSeF parser reads it: positions at full order value, P_13 what is left.
    roz = M.SalesInvoice(company_id=world.c.id, kind="settlement", status="issued", number="03/06/2049",
                         issue_date="2049-06-10", sale_date="2049-06-10", currency="PLN", source="ksef",
                         body={"lines": [{"name": "Usługa", "qty": "1", "unit_net": "10000.00", "net": "10000.00",
                                          "vat_rate": "23", "vat": "2300.00", "gross": "12300.00", "before": False}],
                               "totals": {"net": "9000.00", "vat": "2070.00", "gross": "11070.00",
                                          "rates": {"23": {"net": "9000.00", "vat": "2070.00"}}},
                               "payment": {}, "buyer": {"name": "B", "nip": "5213545223"}})
    S._columns(roz)
    db.add(roz)
    db.flush()
    y = B.year(db, world.c.id, 2049)
    may, jun = y["months"][4], y["months"][5]
    assert (may["revenue_net"], may["advances_net"]) == ("0.00", "1000.00")
    assert (jun["revenue_net"], jun["sales_vat"]) == ("10000.00", "2070.00")


def test_a_recorded_payment_never_changes_an_imported_advance(db, world):
    """The advance a script document printed is kept apart from its amount
    due, so marking it paid cannot turn it into the order total."""
    pos = [{"lp": 1, "nazwa": "Zamówienie", "jm": "szt.", "ilosc": 1, "cena_netto": 10000.0, "netto": 10000.0,
            "vat_proc": 23, "vat": 2300.0, "brutto": 12300.0}]
    sums = {"netto": 10000.0, "vat": 2300.0, "brutto": 12300.0, "stawki": {"23": {"netto": 10000.0, "vat": 2300.0}}}
    adv = S.from_register({"typ": "zaliczka", "status": "wystawiona", "numer": "ZAL 01/08/2049",
                           "data_wystawienia": "2049-08-10", "pozycje": pos, "sumy": sums,
                           "platnosc": {"zaplacono": False}, "do_zaplaty": 3690.0}, world.c.id)
    db.add(adv)
    db.flush()
    assert adv.body["advance_gross"] == "3690.00"
    S.mark_paid(db, adv, "2049-08-20")
    assert adv.paid and adv.amount_due == Decimal("3690.00")       # as printed
    aug = B.year(db, world.c.id, 2049)["months"][7]
    assert (aug["advances_net"], aug["sales_vat"]) == ("3000.00", "690.00")
    with pytest.raises(HTTPException) as e:
        S.mark_paid(db, adv, "2049-08-21")
    assert e.value.status_code == 409


def test_a_second_correction_starts_from_the_first(db, world):
    """1000 -> KOR1 800 -> KOR2 700: the second correction's state before is
    800, so its difference is -100 and the books end at 700."""
    from app.services.invoicing import fa3

    def u(price):
        return [{"name": "U", "qty": 1, "unit_net": price, "vat_rate": "23"}]

    inv = S.create(db, company_id=world.c.id, kind="vat", customer_id=world.cust.id, issue_date="2049-09-01",
                   lines=u("1000"))
    inv.status = "issued"
    k1 = S.correct(db, inv, issue_date="2049-09-05", reason="cena")
    S.update(db, k1, {"lines": u("800")})
    with pytest.raises(HTTPException) as e:          # one open draft correction at a time
        S.correct(db, inv, issue_date="2049-09-06")
    assert e.value.status_code == 409
    k1.status = "issued"
    k2 = S.correct(db, inv, issue_date="2049-09-10", reason="cena 2")
    assert k2.body["correction"]["before_totals"]["net"] == "800.00"
    S.update(db, k2, {"lines": u("700")})
    k2.status = "issued"
    db.flush()
    xml = fa3.build(k2)
    assert fa3.validate(xml) == []
    assert b"<P_13_1>-100.00</P_13_1>" in xml and b"<P_11>800.00</P_11>" in xml and b"<P_11>1000.00</P_11>" not in xml
    assert B.year(db, world.c.id, 2049)["months"][8]["revenue_net"] == "700.00"
    # A correction read from KSeF states only a difference: the next one cannot start from it.
    db.add(M.SalesInvoice(company_id=world.c.id, kind="correction", status="issued", number="KOR 09/09/2049",
                          issue_date="2049-09-20", corrects_id=inv.id, source="ksef",
                          body={"totals": {"net": "-50.00", "vat": "-11.50", "gross": "-61.50", "rates": {}},
                                "correction": {"states_difference": True}}))
    db.flush()
    with pytest.raises(HTTPException) as e:
        S.correct(db, inv, issue_date="2049-09-25")
    assert e.value.status_code == 409 and "KOR 09/09/2049" in e.value.detail


def test_a_second_correction_of_an_advance_starts_from_the_first(db, world):
    adv = S.create(db, company_id=world.c.id, kind="advance", customer_id=world.cust.id, issue_date="2049-10-10",
                   order_lines=LINES_10K, advance_gross="1230.00")
    adv.status = "issued"
    k1 = S.correct(db, adv, issue_date="2049-10-12")
    S.update(db, k1, {"advance_gross": "615.00"})
    k1.status = "issued"
    k2 = S.correct(db, adv, issue_date="2049-10-15")
    assert k2.body["correction"]["before_totals"]["gross"] == "615.00"
    S.update(db, k2, {"advance_gross": "369.00"})
    k2.status = "issued"
    db.flush()
    assert S.correction_difference(k2)["net"] == "-200.00"
    assert B.year(db, world.c.id, 2049)["months"][9]["advances_net"] == "300.00"


def test_purchase_vat_is_in_pln_in_the_first_month_it_can_be_deducted(db, world):
    """Decision 0084: a document in another currency counts the VAT in PLN its
    invoice states, and a purchase's VAT waits for the month it was received
    (art. 86 ust. 10b pkt 1 of the VAT act)."""
    eur = M.RunCostDocument(doc_type="invoice", supplier="TEST-BOOKS-EUR", doc_number="E-1", doc_date="2049-04-28",
                            currency="EUR", fx_rate_usd=1.1, company_id=world.c.id, total_amount=100.0,
                            tax_amount=23.0, tax_amount_pln=Decimal("98.21"), received_date="2049-05-03")
    late = _doc(db, world.c, "2049-04-10", [(1, 100.0, "overhead", "telecom")], tax=23.0)
    late.sale_date = "2049-06-30"           # the service ends after the invoice: the tax point is June
    bare = M.RunCostDocument(doc_type="invoice", supplier="TEST-BOOKS-USD", doc_number="U-1", doc_date="2049-04-11",
                             currency="USD", company_id=world.c.id, total_amount=10.0, tax_amount=2.3)
    db.add_all([eur, bare])
    db.flush()
    m = B.year(db, world.c.id, 2049)["months"]
    assert (m[3]["purchase_vat"], m[4]["purchase_vat"], m[5]["purchase_vat"]) == ("0.00", "98.21", "23.00")
    assert B.purchase_vat_day(eur) == "2049-05-03" and B.purchase_vat_pln(bare) is None
