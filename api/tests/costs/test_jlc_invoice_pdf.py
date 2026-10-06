"""JLCPCB's parts invoice drawn from its own data (decision 0082): the SM2 fields
decrypt, the PDF carries what JLCPCB's page prints, and the file lands on its
document only when the response is that order's invoice.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_jlc_invoice_pdf.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import base64

import fitz
import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import jlc_invoice_pdf as P
from app.services import jlc_web, sm2

POB = "POB0204901010000001"


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


def _secret(text: str, public_hex: str) -> str:
    return "{secret}" + sm2.encrypt(base64.b64encode(text.encode()), public_hex)


def _invoice(rows=2, **over) -> dict:
    goods = [{"componentModel": f"PART-{i}", "description": "-55℃~+155℃ 10kΩ 0402 Thick Film Resistor、ROHS",
              "settlePresaleNumber": 1000 + i, "settleGoodsPrice": 0.0012, "settleGoodsPaidMoney": 1.2}
             for i in range(rows)]
    data = {"invoiceNo": "20146320204901010000001", "invoiceDate": "01/01/2049", "orderBatchNo": POB,
            "companyName": "9Sigma sp. z o.o.", "firstName": "Jan", "lastName": "Nowak", "countryName": "POLAND",
            "stateName": "Zachodniopomorskie", "cityName": "Przęsocin", "streetAddress": "Szczecińska 2G",
            "buildingNo": "2G", "postalCode": "72-010", "email": "x@example.com", "mobileNumber": None,
            "eoriNumber": "PL8513315635", "totalPayment": 1.2 * rows, "totalOtherFee": 0.0,
            "totalDiscountProductFee": 0, "paidMoney": 1.2 * rows, "estimateInvoiceFlag": False,
            "componentGoodsVOList": goods,
            "settleCurrencyInfoVO": {"settleCurrency": "USD", "settleCurrencySymbol": "$"}}
    data.update(over)
    return data


def _text(pdf: bytes) -> str:
    return "\n".join(page.get_text() for page in fitz.open(stream=pdf))


# ------------------------------------------------------------------ SM2
def test_an_sm2_field_decrypts_with_its_key_and_refuses_another():
    priv, pub = sm2.keypair()
    other, _ = sm2.keypair()
    cipher = sm2.encrypt("Szczecińska 2G".encode(), pub)
    assert sm2.decrypt(cipher, priv).decode() == "Szczecińska 2G"
    with pytest.raises(sm2.SM2Error):
        sm2.decrypt(cipher, other)


def test_reveal_decrypts_every_secret_and_keeps_what_it_cannot_read():
    priv, pub = sm2.keypair()
    other, _ = sm2.keypair()
    data = {"streetAddress": _secret("Szczecińska 2G", pub), "nested": [{"email": _secret("x@example.com", pub)}],
            "cityName": "Przęsocin"}
    out = jlc_web.reveal_secrets(data, priv)
    assert out == {"streetAddress": "Szczecińska 2G", "nested": [{"email": "x@example.com"}], "cityName": "Przęsocin"}
    assert jlc_web.reveal_secrets(data, other)["streetAddress"] == data["streetAddress"]


# ------------------------------------------------------------- the drawing
def test_the_pdf_prints_what_jlcpcb_prints():
    text = _text(P.render(_invoice()))
    for expected in ("INVOICE", "JiaLiChuang (HongKong) Co., Limited", "Invoice No.:", "20146320204901010000001",
                     POB, "9Sigma sp. z o.o.", "JanNowak", "POLAND,Zachodniopomorskie,Przęsocin,Szczecińska 2G,2G",
                     "VAT No:PL8513315635", "PART-0", "1001", "USD $0.0012", "USD $1.20", "Subtotal",
                     "Grand Total:", "USD $2.40"):
        assert expected in text, expected
    assert "℃" in text and "、" in text
    assert "Proforma" not in text and "Others" not in text


def test_a_cell_breaks_at_the_character_that_no_longer_fits():
    lines = P.break_all("GRM155R61H105KE05D", P.CELL, 46.5)
    assert lines == ["GRM155R61H105KE", "05D"]
    assert P.break_all("", P.CELL, 46.5) == [""]


def test_a_long_order_continues_on_a_second_page_and_an_estimate_says_so():
    pdf = P.render(_invoice(rows=60, estimateInvoiceFlag=True, totalOtherFee=5))
    doc = fitz.open(stream=pdf)
    assert doc.page_count >= 2
    text = _text(pdf)
    assert "Proforma Invoice" in text and "Others" in text and "USD $5.00" in text
    assert "for reference only prior to payment" in text
    assert all(f"PART-{i}\n" in text for i in range(60))


# ----------------------------------------------------------- the attachment
@pytest.fixture
def store(monkeypatch):
    files = {}
    monkeypatch.setattr("app.services.storage.put_bytes", lambda k, d, ct="": files.__setitem__(k, d))
    return files


def _doc(db, **over) -> M.RunCostDocument:
    doc = M.RunCostDocument(supplier="JLCPCB", external_id=POB, doc_number="20146320204901010000001",
                            doc_date="2049-01-01", currency="USD", total_amount=2.4, **over)
    db.add(doc)
    db.flush()
    return doc


def test_the_drawn_invoice_is_filed_with_its_document_once(db, store, monkeypatch):
    monkeypatch.setattr(jlc_web, "get_parts_invoice", lambda db, pob, reveal=False: _invoice())
    doc = _doc(db)
    out = P.attach(db, doc)
    assert out["status"] == "attached" and out["warnings"] == [] and out["buyer"] == "9Sigma sp. z o.o."
    a = db.get(M.RunAttachment, out["attachment_id"])
    assert doc.attachment_id == a.id and a.content_type == "application/pdf"
    assert a.filename == f"2049-01-01-JLCPCB-componentInovice-{POB}.pdf"
    assert POB in _text(store[a.minio_key])
    assert P.attach(db, doc)["status"] == "skipped"
    assert P.attach(db, doc, force=True)["status"] == "attached"


def test_a_proforma_is_named_so_and_the_final_invoice_follows_it(db, store, monkeypatch):
    goods = [dict(g, orderStatus=30) for g in _invoice()["componentGoodsVOList"]]
    goods[1]["orderStatus"] = 20
    answer = {"data": _invoice(estimateInvoiceFlag=True, componentGoodsVOList=goods)}
    monkeypatch.setattr(jlc_web, "get_parts_invoice", lambda db, pob, reveal=False: answer["data"])
    doc = _doc(db)
    first = P.attach(db, doc)
    assert first["status"] == "attached" and first["proforma"] is True
    assert first["filename"] == f"2049-01-01-JLCPCB-Proforma-Invoice-{POB}.pdf"
    assert first["warnings"][0].startswith("proforma: JLCPCB is still sourcing 1 lot(s)")
    assert "Proforma Invoice" in _text(store[db.get(M.RunAttachment, first["attachment_id"]).minio_key])

    again = P.attach(db, doc)
    assert again["status"] == "skipped" and again["proforma"] is True

    goods[1]["orderStatus"] = 30
    answer["data"] = _invoice(componentGoodsVOList=goods)
    final = P.attach(db, doc)
    assert final["status"] == "attached" and final["proforma"] is False
    assert final["filename"] == f"2049-01-01-JLCPCB-componentInovice-{POB}.pdf"
    assert doc.attachment_id == final["attachment_id"]
    assert P.attach(db, doc)["status"] == "skipped"


def test_a_disagreeing_total_is_a_warning_not_a_refusal(db, store, monkeypatch):
    monkeypatch.setattr(jlc_web, "get_parts_invoice", lambda db, pob, reveal=False: _invoice(paidMoney=2.5))
    out = P.attach(db, _doc(db))
    assert out["status"] == "attached" and out["warnings"] == ["total: the document says 2.4, JLCPCB 2.5"]


@pytest.mark.parametrize("over, words", [
    ({"orderBatchNo": "POB0204901010000002"}, "not " + POB),
    ({"componentGoodsVOList": []}, "no positions"),
    ({"email": "{secret}04abcd"}, "could not decrypt email"),
])
def test_a_response_that_is_not_this_invoice_attaches_nothing(db, store, monkeypatch, over, words):
    monkeypatch.setattr(jlc_web, "get_parts_invoice", lambda db, pob, reveal=False: _invoice(**over))
    doc = _doc(db)
    with pytest.raises(P.InvoicePdfError, match=words):
        P.attach(db, doc)
    assert store == {} and doc.attachment_id is None


def test_only_a_parts_order_gets_one(db, store):
    doc = _doc(db)
    doc.external_id = "W2049010100001"
    with pytest.raises(P.InvoicePdfError, match="not a JLCPCB parts order"):
        P.attach(db, doc)
