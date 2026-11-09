"""A JLCPCB parts order numbered `COB…` gets what a `POB…` one gets.

JLC numbered the parts orders of 2026-11-05 `COB…`. The parts invoice, the
lots and the ledger answer such a number as they answer a `POB` one (read on
2026-11-09), but every path that asked "is this a parts order" tested `POB`.
Todo row 55.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_jlc_parts_order_numbers.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import jlc_apply, jlc_web

COB = "COB204911051831177"


@pytest.fixture
def db():
    """One transaction, never committed: the dev database is left untouched."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


@pytest.mark.parametrize("ref, yes", [("POB0202608060318425", True), (COB, True), ("cob2049", True),
                                      ("W2026090120190004", False), ("", False), (None, False),
                                      ("WM2510010035", False)])
def test_a_parts_order_is_named_by_either_prefix(ref, yes):
    assert jlc_web.is_parts_order(ref) is yes


def test_a_mistyped_cob_reference_finds_its_document(db: Session):
    """The normaliser stripped the zeros after `POB` and `W` only, so a `COB`
    reference typed with a doubled zero would make a second document."""
    doc = M.RunCostDocument(supplier=jlc_apply.SUPPLIER, external_id=COB, doc_date="2049-11-05",
                            currency="USD", total_amount=1.0)
    db.add(doc)
    db.flush()
    assert jlc_apply.find_near_duplicate(db, "COB0" + COB[3:]) is doc


def test_a_cob_number_embedded_in_a_doc_number_is_found(db: Session):
    """`lstrip("POBW")` stripped by character set, and left a `COB` number whole."""
    doc = M.RunCostDocument(supplier=jlc_apply.SUPPLIER, external_id="", doc_number="2014632" + COB[3:],
                            doc_date="2049-11-05", currency="USD", total_amount=1.0)
    db.add(doc)
    db.flush()
    assert jlc_apply.find_near_duplicate(db, COB) is doc


def test_a_cob_order_takes_its_price_and_total_corrections(db: Session):
    doc = M.RunCostDocument(supplier=jlc_apply.SUPPLIER, external_id=COB, doc_date="2049-11-05",
                            currency="USD", total_amount=10.0)
    db.add(doc)
    db.flush()
    line = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", label="cap", lcsc="CCOBTEST1",
                         mpn="COB-PART-1", qty=1000, unit_price=0.01, currency="USD", allocate="pooled")
    db.add(line)
    db.flush()
    lot = {"lot_key": "990001", "purchase_batch_no": COB, "lcsc": "CCOBTEST1", "mpn": "COB-PART-1",
           "qty": 1000, "unit_cost_usd": 0.012, "paid_usd": 12.0, "sourcing_fee_usd": 0.0,
           "presale_type": "buy", "awaiting": False, "cancelled": False}
    out = jlc_apply.reprice_from_jlc(db, {"990001": lot}, dry_run=True)
    assert [(c["line_id"], c["new_unit"]) for c in out["changes"]] == [(line.id, 0.012)]
    assert [(c["document_id"], c["new_total"]) for c in out["document_changes"]] == [(doc.id, 12.0)]
