"""Two companies (decision 0063): project ownership over time, the company of
a batch and an order, memberships and the header scope.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_companies.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
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


@pytest.fixture
def world(db):
    s7, s9 = C.by_key(db, "7sigma"), C.by_key(db, "9sigma")
    p = M.Project(name="test-companies", git_url="https://example.invalid/c.git")
    db.add(p)
    db.flush()
    db.add(M.ProjectOwnership(project_id=p.id, company_id=s7.id, from_date="2024-01-01"))
    db.flush()
    return SimpleNamespace(s7=s7, s9=s9, p=p)


def test_a_project_is_owned_over_time(db, world):
    assert C.owner_on(db, world.p.id, "2024-06-01").key == "7sigma"
    C.move_project(db, world.p, world.s9, "2024-07-22", note="moved", actor="t")
    assert C.owner_on(db, world.p.id, "2024-07-21").key == "7sigma"
    assert C.owner_on(db, world.p.id, "2024-07-22").key == "9sigma"
    hist = C.ownership_json(db, world.p.id)
    assert [(h["company"], h["from_date"], h["to_date"]) for h in hist] == [
        ("7Sigma", "2024-01-01", "2024-07-22"), ("9Sigma", "2024-07-22", None)]


def test_a_move_starts_after_the_last_period_and_after_the_company_existed(db, world):
    with pytest.raises(HTTPException):
        C.move_project(db, world.p, world.s9, "2024-03-01")   # 9Sigma did not exist yet
    C.move_project(db, world.p, world.s9, "2025-01-01")
    with pytest.raises(HTTPException):
        C.move_project(db, world.p, world.s7, "2024-12-01")   # before the current period
    with pytest.raises(HTTPException):
        C.move_project(db, world.p, world.s9, "2025-06-01")   # already its owner


def test_a_batch_takes_its_project_owner_on_its_date(db, world):
    C.move_project(db, world.p, world.s9, "2024-07-22")
    early = M.ProductionRun(project_id=world.p.id, label="early", run_date="2024-05-01")
    late = M.ProductionRun(project_id=world.p.id, label="late", run_date="2025-05-01")
    assert C.default_run_company(db, early).key == "7sigma"
    assert C.default_run_company(db, late).key == "9sigma"


def test_the_header_scope_never_shows_a_company_the_user_may_not_see(db, world):
    u = M.User(username="test-scope-user", role="user", password_hash="x")
    db.add(u)
    db.flush()
    C.set_memberships(db, u, [world.s9.id])

    def req(header):
        return SimpleNamespace(state=SimpleNamespace(user=u),
                               headers={"x-company": header} if header else {})
    assert C.scope_ids(db, req(None)) == [world.s9.id]
    assert C.scope_ids(db, req("all")) == [world.s9.id]
    assert C.scope_ids(db, req(str(world.s7.id))) == [world.s9.id]   # not a member: falls back
    admin = M.User(username="test-scope-admin", role="admin", password_hash="x")
    db.add(admin)
    db.flush()
    r = SimpleNamespace(state=SimpleNamespace(user=admin), headers={"x-company": str(world.s7.id)})
    assert C.scope_ids(db, r) == [world.s7.id]


def test_the_backfill_reads_the_seller_off_the_invoice_notes(db, world):
    cust = M.Customer(name="test-companies-customer")
    db.add(cust)
    db.flush()
    o = M.SalesOrder(customer_id=cust.id, order_ref="T-1", order_date="2025-02-01")
    db.add(o)
    db.flush()
    db.add(M.OrderInvoice(order_id=o.id, kind="final", number="FV T", issue_date="2025-02-01",
                          net_amount=10, notes="9Sigma; test"))
    db.flush()
    db.expire(o, ["invoices"])
    assert C._seller_of_order(db, o, {c.key: c for c in C.all_companies(db)}).key == "9sigma"
