"""The company overhead categories as a list an admin edits (decision 0091).

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_overhead_categories.py -q
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import overhead as O
from app.routers import run_costs as R
from app.services import companies as C
from app.services import company_books as B
from app.services import overhead


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
def company(db):
    c = C.by_key(db, "7sigma")
    c.tax_form = "pit_linear"
    db.flush()
    return c


def _tools(db):
    return O.create_category(O.CategoryIn(label="TEST Tools"), db=db, admin=None)


def _doc(db, company, cat, number="OHC-1"):
    return R._create_document(None, R.DocumentIn(
        supplier="TEST-OHC-SUPPLIER", doc_number=number, doc_date="2049-03-10", currency="PLN", fx_rate_usd=0.25,
        total_amount=120.0, company_id=company.id,
        lines=[R.LineIn(label="drill", qty=1, unit_price=120.0, allocate="overhead", overhead_category=cat)]), db)


def test_the_seed_fills_an_empty_list_only(db):
    db.query(M.OverheadCategory).delete()
    assert overhead.ensure_seeded(db) == len(overhead.SEED)
    assert overhead.ensure_seeded(db) == 0
    assert overhead.labels(db)["telecom"] == "Phone and internet"
    assert list(overhead.labels(db))[-1] == overhead.FALLBACK


def test_a_key_is_derived_from_the_label():
    assert overhead.key_from("Narzędzia i sprzęt") == "narzedzia_i_sprzet"
    assert overhead.key_from("Łódź — biuro") == "lodz_biuro"
    assert overhead.key_from("  Tools / small  ") == "tools_small"


def test_a_new_category_takes_positions_and_reaches_the_books(db, company):
    out = _tools(db)
    assert out["key"] == "test_tools"
    doc = _doc(db, company, "test_tools")
    li = db.query(M.RunCostLine).filter_by(document_id=doc["id"]).one()
    assert (li.allocate, li.overhead_category) == ("overhead", "test_tools")
    books = B.year(db, company.id, 2049)
    assert books["overhead"]["test_tools"] == "120.00"
    assert books["overhead_labels"]["test_tools"] == "TEST Tools"
    row = next(r for r in O.list_categories(db=db) if r["key"] == "test_tools")
    assert (row["positions"], row["registered"]) == (1, True)


def test_a_category_not_on_the_list_is_refused(db, company):
    with pytest.raises(HTTPException) as exc:
        _doc(db, company, "no_such_category")
    assert exc.value.status_code == 422 and "does not exist" in exc.value.detail


def test_a_used_category_is_removed_only_after_its_positions_move(db, company):
    _tools(db)
    doc = _doc(db, company, "test_tools", number="OHC-USED")
    with pytest.raises(HTTPException) as exc:
        O.delete_category("test_tools", db=db, admin=None)
    assert exc.value.status_code == 409
    assert "OHC-USED" in exc.value.detail["error"]
    assert [d["id"] for d in exc.value.detail["documents"]] == [doc["id"]]
    li = db.query(M.RunCostLine).filter_by(document_id=doc["id"]).one()
    R.update_line(li.id, R.LinePatch(allocate="overhead", overhead_category="office"), db=db)
    assert O.delete_category("test_tools", db=db, admin=None) == {"ok": True}
    assert overhead.by_key(db, "test_tools") is None


def test_a_voided_position_does_not_hold_a_category(db, company):
    _tools(db)
    doc = _doc(db, company, "test_tools")
    li = db.query(M.RunCostLine).filter_by(document_id=doc["id"]).one()
    li.voided_at = M.utcnow()
    db.flush()
    assert O.delete_category("test_tools", db=db, admin=None) == {"ok": True}


def test_the_fallback_is_never_removed(db):
    with pytest.raises(HTTPException) as exc:
        O.delete_category(overhead.FALLBACK, db=db, admin=None)
    assert exc.value.status_code == 422


def test_a_key_or_a_label_is_never_taken_twice(db):
    _tools(db)
    for body in (O.CategoryIn(label="TEST Other tools", key="test_tools"),
                 O.CategoryIn(label="test tools", key="test_tools_2"),
                 O.CategoryIn(label="TEST Bad key", key="Bad Key")):
        with pytest.raises(HTTPException) as exc:
            O.create_category(body, db=db, admin=None)
        assert exc.value.status_code == 422


def test_a_relabel_keeps_the_key(db, company):
    _tools(db)
    _doc(db, company, "test_tools")
    assert O.relabel_category("test_tools", O.CategoryPatch(label="TEST Hand tools"), db=db, admin=None) \
        == {"key": "test_tools", "label": "TEST Hand tools"}
    assert db.query(M.RunCostLine).filter_by(overhead_category="test_tools").count() == 1


def test_a_key_in_use_but_not_on_the_list_is_listed(db, company):
    _tools(db)
    doc = _doc(db, company, "test_tools")
    # An undo can put a position back on a category removed since.
    db.query(M.OverheadCategory).filter_by(key="test_tools").delete()
    db.flush()
    row = next(r for r in O.list_categories(db=db) if r["key"] == "test_tools")
    assert (row["registered"], row["positions"]) == (False, 1)
    assert [d["id"] for d in O.category_documents("test_tools", db=db)] == [doc["id"]]


# ------------------------------------------------------------ the agent tools
@pytest.fixture
def tools(db, monkeypatch):
    """The agent tools, each tool session joined to the test's transaction."""
    from app.services import agent_tools as A

    monkeypatch.setattr(A, "SessionLocal", lambda: Session(
        bind=db.connection(), join_transaction_mode="create_savepoint", expire_on_commit=False))
    return lambda name, **kw: json.loads(getattr(A, name).func(**kw))


def test_an_agent_who_is_no_admin_cannot_change_the_list(tools, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "auth_enabled", True)
    out = tools("edit_overhead_category", action="create", label="TEST Tools")
    assert "administrators only" in out["error"]


def test_an_agent_adds_a_category_assigns_it_and_removes_it(tools, db, company, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "auth_enabled", False)  # the dev posture: no user, let through
    assert tools("edit_overhead_category", action="create", label="TEST Tools") == \
        {"key": "test_tools", "label": "TEST Tools"}
    doc = _doc(db, company, "office", number="OHC-AGENT")
    li = db.query(M.RunCostLine).filter_by(document_id=doc["id"]).one()
    out = tools("assign_invoice_line", line_id=li.id, allocate="overhead", overhead_category="test_tools")
    assert out["overhead_category"] == "test_tools"
    listed = tools("list_overhead_categories", category="test_tools")
    assert next(c for c in listed["categories"] if c["key"] == "test_tools")["positions"] == 1
    assert [d["doc_number"] for d in listed["documents"]] == ["OHC-AGENT"]
    refused = tools("edit_overhead_category", action="delete", key="test_tools")
    assert "OHC-AGENT" in refused["error"]["error"]
    tools("assign_invoice_line", line_id=li.id, allocate="overhead", overhead_category="office")
    assert tools("edit_overhead_category", action="delete", key="test_tools") == {"ok": True}
    assert "does not exist" in tools("assign_invoice_line", line_id=li.id, allocate="overhead",
                                     overhead_category="test_tools")["error"]
