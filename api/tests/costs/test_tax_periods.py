"""The income-tax form by quarter (decision 0078), and interest on a tax figure (decision 0081).

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_tax_periods.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db import engine
from app.services import companies as C
from app.services import company_books as B


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


def test_a_month_takes_the_form_of_the_last_period_that_started_by_its_quarter(db):
    c = C.by_key(db, "7sigma")
    c.tax_form = "pit_scale"
    B.set_tax_period(db, c.id, from_quarter="2048-Q1", form="pit_scale", actor="t")
    B.set_tax_period(db, c.id, from_quarter="2049-Q1", form="pit_linear", rate=12.5, actor="t")
    periods = B.tax_periods(db, c.id)
    assert B.tax_setting(periods, "2047-12", c) == ("pit_scale", None)         # the company's one form
    assert B.tax_setting(periods, "2048-11", c) == ("pit_scale", None)
    assert B.tax_setting(periods, "2049-03", c) == ("pit_linear", Decimal("12.500"))
    assert B.quarter_of("2049-03") == "2049-Q1" and B.quarter_of("2049-10") == "2049-Q4"
    B.set_tax_period(db, c.id, from_quarter="2049-Q1", form="pit_linear", actor="t")   # replaces the row
    assert [(p.from_quarter, p.rate) for p in B.tax_periods(db, c.id) if p.from_quarter >= "2048"] == \
        [("2048-Q1", None), ("2049-Q1", None)]
    with pytest.raises(HTTPException):
        B.set_tax_period(db, c.id, from_quarter="2049-05", form="pit_linear", actor="t")
    with pytest.raises(HTTPException):
        B.set_tax_period(db, c.id, from_quarter="2049-Q2", form="vat", actor="t")


def test_the_scale_follows_the_year_and_a_rate_replaces_the_computation():
    assert B._scale_tax(2021, Decimal(50000)) == Decimal("7974.88")          # 17 % less 525.12
    assert B._scale_tax(2021, Decimal(100000)) == Decimal("18828.93")        # 14 539.76 - 341.87 + 32 % of 14 472
    assert B._scale_tax(2023, Decimal(50000)) == Decimal("2400.00")          # 12 % less 3 600
    assert B._scale_tax(2023, Decimal(150000)) == Decimal("20400.00")        # 10 800 + 32 % of 30 000
    assert B._income_tax("pit_linear", Decimal(0), Decimal(1000), Decimal(5000), 2024, Decimal("5")) == Decimal("50.00")
    assert B._income_tax("lump", Decimal(0), Decimal(1000), Decimal(5000), 2024, Decimal("8.5")) == Decimal("425.00")


def test_interest_is_money_paid_and_never_a_cost(db):
    c = C.by_key(db, "9sigma")

    def month(m):
        return next(x for x in B.year(db, c.id, 2049)["months"] if x["month"] == m)

    before = month("2049-04")
    B.set_entry(db, c.id, period="2049-04", kind="vat", amount=2351, paid_date="2049-08-31", interest=66, actor="t")
    after = month("2049-04")
    assert after["accountant"]["vat"]["interest"] == "66.00" and Decimal(after["interest"]) == Decimal(before["interest"]) + 66
    assert (after["costs_net"], after["income"], after["income_tax_estimate"]) == \
        (before["costs_net"], before["income"], before["income_tax_estimate"])
    assert Decimal(B.year(db, c.id, 2049)["totals"]["interest"]) >= 66
    with pytest.raises(HTTPException):
        B.set_entry(db, c.id, period="2049-05", kind="vat", amount=1, interest=-1, actor="t")


def test_the_health_contribution_is_part_of_zus():
    assert "health" not in B.ENTRY_KINDS and "zus" in B.ENTRY_KINDS
