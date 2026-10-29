"""A JLC invoice's `taxAdvanceFee` is part of its total: the document closes with
it, and it is booked as a payment fee, not as reclaimable tax.

Header figures of invoice 2014632A2026102820395051 (batch W2026102820395051,
read 2026-10-29): productMoney 10059.23, carriageMoney 510.05,
tariffChargesMoney 2424.25, taxAdvanceFee 48.48, discount 9.00,
totalMoney 13033.01. JLC's order page names the fee "Duty & Tax Disbursement
Fee". The consumption is reduced to one lot of the same value.

Run from `api/`:
    python -m pytest tests/costs/test_jlc_tax_advance_fee.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app.services import jlc_import, jlc_invoice

RAW = {
    "batchNum": "W2026102820395051", "invoiceNo": "2014632A2026102820395051",
    "invoiceDate": "29/10/2026",
    "settleCurrencyInfoVO": {"settleCurrency": "USD", "settleExchangeRate": 1.0},
    "productMoney": 10059.23, "carriageMoney": "510.05", "tariffChargesMoney": 2424.25,
    "taxAdvanceFee": 48.48, "serviceCharges": 0, "discount": 9.0,
    "presaleMoney": 9103.75, "subTotalMoney": "10560.28", "totalMoney": "13033.01",
    "invoiceListResponseList": [{
        "orderCode": "SMT026102862842-P50", "orderType": "Circuit Board Assembly Module",
        "number": 300, "unitMoney": 33.5308, "totalMoney": 10059.23,
        "presaleMoney": 9103.75, "orderFileName": "CE_Dongle_V3(Reorder)_P50",
    }],
    "presaleDetailResultVOList": [{
        "smtOrderCode": "SMT026102862842", "componentCode": "C1", "componentModel": "TEST",
        "componentNum": 1000, "settleGoodsPrice": 9.10375, "componentMoney": 9103.75,
    }],
}


def test_the_parser_reads_the_fee():
    assert jlc_invoice.parse(RAW)["totals"]["tax_advance_fee"] == 48.48


def test_the_document_closes_with_the_fee():
    plan = jlc_import.plan_manufacturing_document(jlc_invoice.parse(RAW))
    assert plan["reconciles"]
    assert plan["residual_usd"] == 0
    assert not any(li["external_line_id"] == "header:residual" for li in plan["lines"])


def test_the_fee_is_a_payment_fee_and_not_tax():
    plan = jlc_import.plan_manufacturing_document(jlc_invoice.parse(RAW))
    fee = [li for li in plan["lines"] if li["plan_key"] == "other:payment_fee"]
    assert len(fee) == 1 and fee[0]["unit_price"] == 48.48
    duty = [li for li in plan["lines"] if li["plan_key"] == "logistics:duty"]
    assert [li["unit_price"] for li in duty] == [2424.25]


def test_an_invoice_without_the_fee_has_no_fee_line():
    raw = {**RAW, "totalMoney": "12984.53"}
    del raw["taxAdvanceFee"]
    plan = jlc_import.plan_manufacturing_document(jlc_invoice.parse(raw))
    assert plan["reconciles"]
    assert not any(li["plan_key"] == "other:payment_fee" for li in plan["lines"])
