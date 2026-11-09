"""One part's ledger is the same timeline whichever identity asks for it.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_part_ledger.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import run_actuals as ra
from app.services.material_ledger import core as ledger


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


@pytest.fixture
def part(db: Session):
    """A library part bought by component and MPN, and drawn by a process step
    that names the component only — the shape of enclosure 35.0207000.BL."""
    comp = M.Component(name="test-ledger-enclosure", in_library=False)
    db.add(comp)
    db.flush()
    doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="PL-0001",
                            doc_date="2026-02-01", currency="USD", total_amount=100.0)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", description="enclosure",
                         component_id=comp.id, mpn="TEST-ENCL-1", qty=100, unit_price=1.0,
                         currency="USD", allocate="pooled"))
    db.flush()
    ledger.draw(db, component_id=comp.id, mpn="", taken=40, unit_cost_usd=1.0,
                basis="step", at="2026-03-01")
    db.flush()
    return comp


def _summary(out: dict) -> tuple:
    return len(out["events"]), out["balance"]


def test_an_mpn_lookup_shows_the_draws_a_step_made_by_component(db, part):
    by_component = ra.component_ledger(db, component_id=part.id)
    by_mpn = ra.component_ledger(db, mpn="TEST-ENCL-1")
    assert _summary(by_component) == (2, 60)
    assert _summary(by_mpn) == _summary(by_component)


def test_an_mpn_two_components_share_adopts_neither(db, part):
    """Two components under one code are two parts: the lookup stays on the code."""
    other = M.Component(name="test-ledger-other", in_library=False)
    db.add(other)
    db.flush()
    doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="PL-0002",
                            doc_date="2026-02-02", currency="USD", total_amount=5.0)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", description="other",
                         component_id=other.id, mpn="TEST-ENCL-1", qty=5, unit_price=1.0,
                         currency="USD", allocate="pooled"))
    db.flush()
    n, balance = _summary(ra.component_ledger(db, mpn="TEST-ENCL-1"))
    assert (n, balance) == (2, 105)
