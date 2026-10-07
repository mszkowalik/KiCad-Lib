"""JLCPCB's assembly invoice drawn from its own data (decision 0086): the PDF
carries JLCPCB's figures, one row per order, with the totals JLCPCB prints; the
file lands on its document only when the response is that order's invoice; the
one route draws a parts order's or an assembly order's invoice by its number.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_jlc_mfg_invoice_pdf.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import fitz
import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import jlc_invoice_pdf, jlc_web
from app.services import jlc_mfg_invoice_pdf as P

W = "W204901010000001"


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


def _invoice(rows=3, **over) -> dict:
    """The shape of `orderCenter/invoiceOrder`, its `{secret}` fields decrypted."""
    orders = [{"specifications": "Rigid Populated printed circuit board", "orderFileName": f"Gerber_TEST_2049_P{i}",
               "orderCode": f"SMT0490101000000{i}-P{i}", "number": 250, "unitMoney": 8.1762, "totalMoney": 2044.05}
              for i in range(rows)]
    data = {"batchNum": W, "invoiceNo": "2014632A204901010000001", "invoiceDate": "01/01/2049",
            "expressNo": "9000000001", "freightModeName": "DHL Express Priority (DDP)", "typeOfTrade": "DDP",
            "companyName": "9Sigma sp. z o.o.", "man": "Jan Nowak", "address": "Szczecińska 2G",
            "province": "Zachodniopomorskie", "city": "Przęsocin", "postCode": "72-010", "country": "PL",
            "companyNameBilling": "9Sigma sp. z o.o.", "manBilling": "Jan Nowak", "addressBilling": "Szczecińska 2G",
            "provinceBilling": "Zachodniopomorskie", "cityBilling": "Przęsocin", "postCodeBilling": "72-010",
            "countryBilling": "POLAND", "email": "x@example.com", "tel": "", "telBilling": "",
            "brazilCpnj": "", "taxVat": "", "brazilCpnjBilling": "", "taxVatBilling": "PL8513315635",
            "productMoney": round(2044.05 * rows, 2), "carriageMoney": "316.79", "discount": 0,
            "subTotalMoney": str(round(2044.05 * rows + 316.79, 2)), "tariffChargesMoney": 962.53, "tariffRate": 23.0,
            "serviceCharges": 0, "totalMoney": str(round(2044.05 * rows + 316.79 + 962.53, 2)),
            "invoiceListResponseList": orders}
    data.update(over)
    return data


def _text(pdf: bytes) -> str:
    return "\n".join(page.get_text() for page in fitz.open(stream=pdf))


def test_the_pdf_prints_jlcpcbs_figures_and_says_it_was_drawn():
    text = _text(P.render(_invoice()))
    for expected in ("JiaLiChuang (HongKong) Co., Limited", "Invoice No.:", "2014632A204901010000001", "01/01/2049",
                     "Reference:", "9000000001", "Batch No.:", W, "DHL Express Priority (DDP)", "Type of Trade:",
                     "Ship To:", "Billing To:", "9Sigma sp. z o.o.", "Zachodniopomorskie Przęsocin 72-010",
                     "VAT No:PL8513315635", "Rigid Populated printed circuit board", "SMT04901010000001-P1",
                     "USD $8.1762", "USD $2044.0500", "Merchandise Total:", "USD $6132.15", "Shipping:",
                     "Subtotal:", "Import Taxes(23%):", "USD $962.53", "Grand Total:", "USD $7411.47",
                     "Drawn by the 7Sigma platform"):
        assert expected in text, expected
    assert "Discount:" not in text and "Service Charge:" not in text


def test_a_discount_and_a_service_charge_are_printed_when_there():
    text = _text(P.render(_invoice(rows=1, discount=8.0, serviceCharges=1.0, tariffChargesMoney=0)))
    assert "Discount:" in text and "USD $-8.00" in text and "Service Charge:" in text and "USD $1.00" in text
    assert "Import Taxes" not in text


def test_a_long_order_continues_on_a_second_page():
    pdf = P.render(_invoice(rows=40))
    assert fitz.open(stream=pdf).page_count >= 2
    text = _text(pdf)
    assert all(f"SMT0490101000000{i}-P{i}" in text for i in range(40)) and "Grand Total:" in text


@pytest.fixture
def store(monkeypatch):
    files = {}
    monkeypatch.setattr("app.services.storage.put_bytes", lambda k, d, ct="": files.__setitem__(k, d))
    return files


def _doc(db, external_id: str = W.lower(), **over) -> M.RunCostDocument:
    doc = M.RunCostDocument(supplier="JLCPCB", external_id=external_id, doc_number="2014632A204901010000001",
                            doc_date="2049-01-01", currency="USD", total_amount=7411.47, **over)
    db.add(doc)
    db.flush()
    return doc


def test_the_drawn_invoice_is_filed_with_its_document_once(db, store, monkeypatch):
    asked = []
    monkeypatch.setattr(jlc_web, "get_manufacturing_invoice",
                        lambda db, batch, reveal=False: asked.append((batch, reveal)) or _invoice())
    doc = _doc(db)                                   # a lower-case W, as some imports stored it
    out = P.attach(db, doc)
    assert out["status"] == "attached" and out["warnings"] == [] and asked == [(W, True)]
    a = db.get(M.RunAttachment, out["attachment_id"])
    assert doc.attachment_id == a.id and a.filename == f"2049-01-01-JLCPCB-invoice-{W}.pdf"
    assert W in _text(store[a.minio_key])
    assert P.attach(db, doc)["status"] == "skipped"
    assert P.attach(db, doc, force=True)["status"] == "attached"


def test_a_disagreeing_total_is_a_warning_not_a_refusal(db, store, monkeypatch):
    monkeypatch.setattr(jlc_web, "get_manufacturing_invoice", lambda db, batch, reveal=False: _invoice(totalMoney="7400.00"))
    out = P.attach(db, _doc(db))
    assert out["status"] == "attached" and out["warnings"] == ["total: the document says 7411.47, JLCPCB 7400.00"]


@pytest.mark.parametrize("over, words", [
    ({"batchNum": "W204901010000002"}, "not w2049"),
    ({"invoiceListResponseList": []}, "no positions"),
    ({"addressBilling": "{secret}04abcd"}, "could not decrypt addressBilling"),
])
def test_a_response_that_is_not_this_invoice_attaches_nothing(db, store, monkeypatch, over, words):
    monkeypatch.setattr(jlc_web, "get_manufacturing_invoice", lambda db, batch, reveal=False: _invoice(**over))
    doc = _doc(db)
    with pytest.raises(P.InvoicePdfError, match=words):
        P.attach(db, doc)
    assert store == {} and doc.attachment_id is None


def test_the_route_draws_each_kind_by_its_order_number(db, monkeypatch):
    from app.routers import jlc_web as R

    calls = []
    monkeypatch.setattr(R, "_guard", lambda db: None)
    monkeypatch.setattr(P, "attach", lambda db, doc, force=False, actor="": calls.append(("assembly", doc.id)) or
                        {"document_id": doc.id, "status": "attached"})
    monkeypatch.setattr(jlc_invoice_pdf, "attach", lambda db, doc, force=False, actor="": calls.append(("parts", doc.id))
                        or {"document_id": doc.id, "status": "attached"})
    monkeypatch.setattr(db, "commit", lambda: None)
    w = _doc(db)
    pob = _doc(db, external_id="POB0204901010000001")
    R.invoice_pdfs(R.InvoicePdfBody(document_ids=[w.id, pob.id]), db=db)
    assert calls == [("assembly", w.id), ("parts", pob.id)]
