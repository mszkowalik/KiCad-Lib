"""A supplier document's printed invoice, read from its own original file
(decision 0085).

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_printed_invoice.py -q
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
from app.routers import run_costs as RC
from app.services import companies as C
from app.services import run_actuals


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
def doc(db):
    c = C.by_key(db, "7sigma")
    d = M.RunCostDocument(doc_type="invoice", supplier="TEST-PRINTED", doc_number="FV 0012/2049",
                          doc_date="2049-05-10", currency="PLN", company_id=c.id, total_amount=120.0)
    db.add(d)
    db.flush()
    db.add(M.RunCostLine(document_id=d.id, position=0, label="Usługa", qty=1, unit_price=120.0))
    a = M.RunAttachment(document_id=d.id, filename="FV-12.pdf", content_type="application/pdf",
                        minio_key="documents/x/FV-12.pdf")
    db.add(a)
    db.flush()
    db.refresh(d)
    d.att = a
    return d


def _page(att_id, *, net="120.00", vat="27.60", gross="147.60", number="FV 12/2049", currency="PLN",
          rate_vat_pln=None, reason=""):
    rate = {"net": net, "vat": vat, **({"vat_pln": rate_vat_pln} if rate_vat_pln else {})}
    return RC.PrintedIn(
        attachment_id=att_id, number=number, issue_date="2049-05-10", sale_date="2049-05-08",
        currency=currency, reason=reason,
        body={"seller": {"name": "DOSTAWCA SP. Z O.O.", "nip": "5213545223"},
              "buyer": {"name": "7Sigma Mateusz Kowalik", "nip": "8513262910"},
              "lines": [{"position": 1, "name": "Usługa", "qty": "1", "unit": "szt.", "unit_net": net,
                         "net": net, "vat_rate": "23", "vat": vat, "gross": gross}],
              "totals": {"net": net, "vat": vat, "gross": gross, "rates": {"23": rate},
                         **({"vat_pln": rate_vat_pln} if rate_vat_pln else {})},
              "payment": {"due_date": "2049-05-24", "method": "przelew"}})


def test_a_page_read_from_the_original_stores_its_tax_data(db, doc):
    out = RC.put_printed_invoice(doc.id, _page(doc.att.id), db=db)
    assert out["problems"] == []
    assert (doc.sale_date, doc.due_date, doc.tax_amount) == ("2049-05-08", "2049-05-24", pytest.approx(27.6))
    src = doc.body["source"]
    assert (src["kind"], src["attachment_id"], src["filename"]) == ("file", doc.att.id, "FV-12.pdf")
    assert doc.body["lines"][0]["vat_rate"] == "23" and doc.body["totals"]["gross"] == "147.60"
    # The money stays: the net, the positions and the date are the document's.
    assert (doc.total_amount, doc.doc_date, len(doc.lines)) == (pytest.approx(120.0), "2049-05-10", 1)
    assert db.query(M.AuditLog).filter_by(action="run.document.printed", entity_id=str(doc.id)).count() == 1


def test_a_page_that_disagrees_needs_a_reason_and_keeps_it(db, doc):
    doc.tax_amount = 20.0
    with pytest.raises(HTTPException) as e:
        RC.put_printed_invoice(doc.id, _page(doc.att.id, net="100.00", vat="23.00", gross="123.00"), db=db)
    codes = {p["code"] for p in e.value.detail["problems"]}
    assert e.value.status_code == 409 and codes == {"net", "vat"} and doc.body is None
    RC.put_printed_invoice(doc.id, _page(doc.att.id, net="100.00", vat="23.00", gross="123.00",
                                         reason="20 PLN of the page is private, typed out of the cost"), db=db)
    assert doc.tax_amount == pytest.approx(23.0) and doc.total_amount == pytest.approx(120.0)
    assert {p["code"] for p in doc.body["source"]["problems"]} == {"net", "vat"}
    assert doc.body["source"]["reason"].startswith("20 PLN")


def test_a_page_that_does_not_add_up_is_refused(db, doc):
    with pytest.raises(HTTPException) as e:
        RC.put_printed_invoice(doc.id, _page(doc.att.id, gross="150.00"), db=db)
    assert {p["code"] for p in e.value.detail["problems"]} == {"gross"}


def test_a_foreign_currency_page_keeps_its_vat_in_pln(db, doc):
    doc.currency = "EUR"
    RC.put_printed_invoice(doc.id, _page(doc.att.id, currency="EUR", rate_vat_pln="117.30"), db=db)
    assert doc.tax_amount_pln == Decimal("117.30")


def test_the_tax_layer_is_written_on_a_closed_batch_s_document(db, doc, monkeypatch):
    """The lock of decision 0044 covers money; the printed page moves none."""
    monkeypatch.setattr(run_actuals, "closed_lock", lambda db_, d, closed=None: [
        {"run_id": 1, "label": "Batch 1", "closed_at": "2049-06-01", "closed_by": "x"}])
    with pytest.raises(HTTPException):
        RC.update_document(doc.id, RC.DocumentPatch(sale_date="2049-05-08"), db=db)
    assert RC.put_printed_invoice(doc.id, _page(doc.att.id), db=db)["problems"] == []


def test_ksef_s_invoice_and_another_document_s_file_are_refused(db, doc):
    other = M.RunAttachment(document_id=None, filename="x.pdf", minio_key="x")
    db.add(other)
    db.flush()
    with pytest.raises(HTTPException) as e:
        RC.put_printed_invoice(doc.id, _page(other.id), db=db)
    assert e.value.status_code == 422
    db.add(M.KsefInvoice(company_id=doc.company_id, side="purchase", ksef_number="5213545223-20490510-AA",
                         document_id=doc.id, status="imported"))
    db.flush()
    with pytest.raises(HTTPException) as e:
        RC.put_printed_invoice(doc.id, _page(doc.att.id), db=db)
    assert e.value.status_code == 409 and "KSeF holds" in e.value.detail["error"]
