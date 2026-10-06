"""Whether the accountant has a document (decision 0079).

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_accountant.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import accountant as A
from app.services import companies as C


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


def _doc(db, company, number, day, allocate="none", **kw):
    d = M.RunCostDocument(doc_type=kw.pop("doc_type", "invoice"), supplier="TEST-ACC", doc_number=number,
                          doc_date=day, currency="PLN", company_id=company.id, total_amount=10, **kw)
    db.add(d)
    db.flush()
    db.add(M.RunCostLine(document_id=d.id, position=0, label="x", qty=1, unit_price=10, allocate=allocate,
                         exclude_reason="test" if allocate == "excluded" else ""))
    db.flush()
    db.refresh(d)
    return d


def test_ksef_counts_as_sent_and_an_ignored_document_is_not_to_send(db):
    c = C.by_key(db, "9sigma")
    k = _doc(db, c, "K/1", "2049-03-05", external_id="8513315635-20490305-ABCDEF123456-AB")
    e = _doc(db, c, "E/1", "2049-03-06", allocate="excluded")
    p = _doc(db, c, "P/1", "2049-03-07", doc_type="proforma")
    n = _doc(db, c, "N/1", "2049-03-08")
    assert A.state(k)["sent"] and A.state(k)["via"] == "ksef"
    assert A.state(e)["ignored"] and A.state(p)["ignored"] and not A.state(n)["ignored"]
    got = A.to_send(db, c.id, today="2049-04-11")
    month = next(m for m in got["months"] if m["month"] == "2049-03")
    assert [r["number"] for r in month["rows"]] == ["N/1"]
    assert month["deadline"] == "2049-04-10" and month["overdue"]


def test_a_send_is_recorded_and_cleared(db):
    c = C.by_key(db, "9sigma")
    n = _doc(db, c, "N/2", "2049-12-08")
    assert A.deadline("2049-12-08") == "2050-01-10"
    assert A.mark(db, c.id, document_ids=[n.id], sales_invoice_ids=[], sent_at="2050-01-05", via="mail", ref="gm1") == 1
    assert A.state(n) == {"sent": True, "via": "mail", "at": "2050-01-05", "ref": "gm1", "ignored": False}
    A.mark(db, c.id, document_ids=[n.id], sales_invoice_ids=[], sent_at="")
    assert not A.state(n)["sent"]
    with pytest.raises(HTTPException):
        A.mark(db, c.id, document_ids=[n.id], sales_invoice_ids=[], sent_at="2050-01-05", via="ksef")
    seven = C.by_key(db, "7sigma")
    with pytest.raises(HTTPException):
        A.mark(db, seven.id, document_ids=[n.id], sales_invoice_ids=[], sent_at="2050-01-05")
