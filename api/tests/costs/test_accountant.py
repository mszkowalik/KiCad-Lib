"""Whether the accountant has a document (decisions 0079, 0080).

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_accountant.py -q
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
from app.services import accountant as A
from app.services import companies as C
from app.services import company_books as B
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


def _doc(db, company, number, day, allocate="none", **kw):
    d = M.RunCostDocument(doc_type=kw.pop("doc_type", "invoice"), supplier="TEST-ACC", doc_number=number,
                          doc_date=day, currency="PLN", company_id=company.id, total_amount=10, **kw)
    db.add(d)
    db.flush()
    db.add(M.RunCostLine(document_id=d.id, position=0, label="x", qty=1, unit_price=10, allocate=allocate,
                         exclude_reason="test" if allocate == "excluded" else "",
                         overhead_category="other" if allocate == "overhead" else ""))
    db.flush()
    db.refresh(d)
    return d


def test_ksef_counts_as_sent_and_a_proforma_is_not_to_send(db):
    c = C.by_key(db, "9sigma")
    k = _doc(db, c, "K/1", "2049-03-05", external_id="8513315635-20490305-ABCDEF123456-AB")
    e = _doc(db, c, "E/1", "2049-03-06", allocate="excluded")
    p = _doc(db, c, "P/1", "2049-03-07", doc_type="proforma")
    n = _doc(db, c, "N/1", "2049-03-08")
    assert A.state(k)["sent"] and A.state(k)["via"] == "ksef"
    assert A.state(p)["ignored"] and not A.state(n)["ignored"]
    # decision 0080: excluded positions say who bears the cost, not whether she has the invoice
    assert not A.state(e)["ignored"]
    got = A.to_send(db, c.id, today="2049-04-11")
    month = next(m for m in got["months"] if m["month"] == "2049-03")
    assert [r["number"] for r in month["rows"]] == ["E/1", "N/1"]
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


def test_a_document_linked_to_a_ksef_row_counts_as_ksef(db):
    c = C.by_key(db, "9sigma")
    d = _doc(db, c, "L/1", "2049-05-05")
    assert not A.state(d, db)["sent"]
    db.add(M.KsefInvoice(company_id=c.id, side="purchase", ksef_number="TEST-ACC-KSEF-1", status="imported",
                         document_id=d.id))
    db.flush()
    assert A.state(d, db)["via"] == "ksef"
    assert all(r["id"] != d.id for m in A.to_send(db, c.id)["months"] for r in m["rows"])


def _cost(db, company, month):
    m = next(m for m in B.year(db, company.id, int(month[:4]))["months"] if m["month"] == month)
    return Decimal(m["costs_net"]), Decimal(m["purchase_vat"])


def test_a_document_kept_from_the_accountant_leaves_the_list_and_the_books(db):
    c = C.by_key(db, "9sigma")
    before = _cost(db, c, "2049-07")
    d = _doc(db, c, "X/1", "2049-07-08", allocate="overhead", tax_amount=2.3)
    assert _cost(db, c, "2049-07") == (before[0] + 10, before[1] + Decimal("2.3"))
    A.mark(db, c.id, document_ids=[d.id], sales_invoice_ids=[], sent_at="2049-10-06", via="not_sent", ref="lost")
    assert A.state(d) == {"sent": False, "via": "not_sent", "at": "2049-10-06", "ref": "lost", "ignored": True}
    assert A.kept_from_accountant(d)
    assert all(r["id"] != d.id for m in A.to_send(db, c.id)["months"] for r in m["rows"])
    assert _cost(db, c, "2049-07") == before
    A.mark(db, c.id, document_ids=[d.id], sales_invoice_ids=[], sent_at="")     # undone: to send again
    assert not A.state(d)["ignored"] and _cost(db, c, "2049-07") == (before[0] + 10, before[1] + Decimal("2.3"))


def test_keeping_one_from_the_accountant_needs_a_reason_and_never_reaches_ksef(db):
    c = C.by_key(db, "9sigma")
    d = _doc(db, c, "X/2", "2049-08-08")
    with pytest.raises(HTTPException):
        A.mark(db, c.id, document_ids=[d.id], sales_invoice_ids=[], sent_at="2049-10-06", via="not_sent", ref=" ")
    k = _doc(db, c, "K/2", "2049-08-09", external_id="8513315635-20490809-ABCDEF123456-AB")
    with pytest.raises(HTTPException):
        A.mark(db, c.id, document_ids=[d.id, k.id], sales_invoice_ids=[], sent_at="2049-10-06", via="not_sent",
               ref="too late")
    assert not d.accountant_sent_at                  # refused as a whole, nothing half-written


def test_a_sales_invoice_kept_from_the_accountant_leaves_the_revenue(db):
    c = C.by_key(db, "9sigma")
    c.issues_invoices = False
    t = {"net": "100", "vat": "23", "gross": "123", "rates": {"23": {"net": "100", "vat": "23"}}}
    inv = S.record_history(db, company_id=c.id, kind="vat", number="FV TEST-ACC/09/2049", issue_date="2049-09-05",
                           sale_date="2049-09-05", due_date="", buyer={"name": "TEST-ACC-BUYER"}, currency="PLN",
                           lines=[], totals=t, advance_numbers=[], corrects_number="", paid=False, paid_date="",
                           order_id=None, note="", actor="test")
    def rev():
        return Decimal(next(m for m in B.year(db, c.id, 2049)["months"] if m["month"] == "2049-09")["revenue_net"])

    before = rev()
    A.mark(db, c.id, document_ids=[], sales_invoice_ids=[inv.id], sent_at="2049-10-06", via="not_sent", ref="private")
    assert A.sales_state(inv)["via"] == "not_sent" and rev() == before - 100


def test_the_list_downloads_as_one_zip_with_the_missing_named(db, monkeypatch):
    import io
    import zipfile

    store = {}
    monkeypatch.setattr("app.services.storage.get_bytes", lambda k: store.get(k))
    c = C.by_key(db, "9sigma")
    with_file = _doc(db, c, "ZIP/1", "2049-05-03")
    for i, name in enumerate(("scan.pdf", "final.PDF")):
        a = M.RunAttachment(document_id=with_file.id, filename=name, content_type="application/pdf",
                            size_bytes=3, minio_key=f"k/zip/{i}")
        db.add(a)
        db.flush()
        store[a.minio_key] = f"bytes-{i}".encode()
    with_file.attachment_id = a.id - 1          # the headline is the first, not the newest
    without = _doc(db, c, "ZIP/2", "2049-05-04")
    other = _doc(db, C.by_key(db, "7sigma"), "ZIP/3", "2049-05-05")
    db.flush()

    data, summary = A.bundle(db, c.id, today="2049-06-11")
    z = zipfile.ZipFile(io.BytesIO(data))
    mine = [n for n in z.namelist() if "TEST-ACC" in n]
    assert mine == ["2049-05/2049-05-03 TEST-ACC ZIP-1.pdf"]
    assert z.read(mine[0]) == b"bytes-0"
    assert "ZIP/2" in z.read(A.MISSING_NAME).decode() and "ZIP/3" not in z.read(A.MISSING_NAME).decode()
    assert summary["missing"] >= 1

    picked, s2 = A.bundle(db, c.id, {("document", without.id), ("document", other.id)}, today="2049-06-11")
    z2 = zipfile.ZipFile(io.BytesIO(picked))
    assert z2.namelist() == [A.MISSING_NAME] and s2 == {"files": 0, "missing": 1}
