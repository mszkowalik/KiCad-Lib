"""Every row change is recorded and a request can be undone (decision 0089).

What these pin down:

- every table but the listed ones carries the trigger;
- a delete keeps the whole row, and an undo puts it back with its id;
- an update is undone only while the row reads as the request left it, and
  the refusal names the later request;
- an insert is undone by removing the row, and an undo is itself undone (redo);
- a cascade Postgres runs itself is recorded and put back with its parent;
- a secret column is never stored, so a deleted account is not brought back;
- a user undoes only their own requests, an administrator anybody's;
- an undo that touches stock goes through the Write log's stock check, and is
  refused where it would take a part below zero.

Each test runs in one transaction that is rolled back.

Run from `api/`, with the dev database up:
    python -m pytest tests/auth/test_row_changes.py -q
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import row_changes as rc
from app.services import tracking
from app.services.material_ledger import core as ledger


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    ctx = tracking._current.set(None)   # `act` binds a request; never leak it to later tests
    try:
        yield s
    finally:
        tracking._current.reset(ctx)
        s.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def people(db):
    admin = M.User(username="rc-test-admin", password_hash="x", role="admin")
    alice = M.User(username="rc-test-alice", password_hash="x", role="user")
    bob = M.User(username="rc-test-bob", password_hash="x", role="user")
    db.add_all([admin, alice, bob])
    db.flush()
    return {"admin": admin, "alice": alice, "bob": bob}


def act(db, key: str, user: M.User | None):
    """Make the next writes belong to request `key` by `user`, as the gate and
    the session tag do for a real request."""
    tracking.bind(tracking.RequestActor(key, user.id if user else None, user.username if user else "",
                                        user.username if user else "", "token" if user else "none", "token"))
    db.execute(text("SELECT set_config('app.row_ctx', :v, true)"), {"v": json.dumps(rc.context())})


def test_every_table_carries_the_trigger():
    with engine.connect() as conn:
        assert rc.missing_triggers(conn) == []


def test_a_deleted_row_comes_back_with_its_id(db, people):
    act(db, "rc-t1-create", people["alice"])
    c = M.Comment(target_type="component", target_id=1, author="a", body="keep me")
    db.add(c)
    db.flush()
    cid = c.id
    act(db, "rc-t1-delete", people["alice"])
    db.delete(c)
    db.flush()
    got = db.query(M.RowChange).filter_by(group_key="rc-t1-delete").one()
    assert (got.op, got.old["body"], got.new) == ("D", "keep me", None)
    act(db, "rc-t1-undo", people["alice"])
    plan = rc.undo(db, "rc-t1-delete")
    assert plan["refused"] == [] and plan["actions"] == [{"do": "insert", "table": "comments", "pk": {"id": cid}}]
    rc.undo(db, "rc-t1-delete", dry_run=False)
    db.expire_all()
    assert db.get(M.Comment, cid).body == "keep me"
    assert rc.summary(db, "rc-t1-delete")["undone_by"] == "rc-t1-undo"


def test_an_update_is_undone_only_as_the_request_left_it(db, people):
    act(db, "rc-t2-create", people["alice"])
    c = M.Comment(target_type="component", target_id=1, author="a", body="one")
    db.add(c)
    db.flush()
    act(db, "rc-t2-first", people["alice"])
    c.body = "two"
    db.flush()
    act(db, "rc-t2-second", people["alice"])
    c.body = "three"
    db.flush()
    first = db.query(M.RowChange).filter_by(group_key="rc-t2-first").one()
    assert (first.op, first.old, first.new) == ("U", {"body": "one"}, {"body": "two"})
    refused = rc.undo(db, "rc-t2-first")["refused"]
    assert refused and "rc-t2-second" in refused[0]["why"]
    act(db, "rc-t2-undo2", people["alice"])
    rc.undo(db, "rc-t2-second", dry_run=False)
    act(db, "rc-t2-undo1", people["alice"])
    rc.undo(db, "rc-t2-first", dry_run=False)
    db.expire_all()
    assert db.get(M.Comment, c.id).body == "one"


def test_an_insert_is_removed_and_the_undo_can_be_undone(db, people):
    act(db, "rc-t3-create", people["alice"])
    c = M.Comment(target_type="component", target_id=1, author="a", body="new")
    db.add(c)
    db.flush()
    cid = c.id
    act(db, "rc-t3-undo", people["alice"])
    rc.undo(db, "rc-t3-create", dry_run=False)
    db.expire_all()
    assert db.get(M.Comment, cid) is None
    act(db, "rc-t3-redo", people["alice"])
    rc.undo(db, "rc-t3-undo", dry_run=False)
    db.expire_all()
    assert db.get(M.Comment, cid).body == "new"


def test_a_database_cascade_is_recorded_and_put_back(db, people):
    act(db, "rc-t4-setup", people["alice"])
    proj = M.Project(name="rc-test-project", git_url="https://example.invalid/rc.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="RC", run_date="2026-10-12", status="planned")
    db.add(run)
    db.flush()
    sub = M.RunSubstitution(run_id=run.id, designator="C2", specified_mpn="A", fitted_mpn="B")
    db.add(sub)
    db.flush()
    rid, sid = run.id, sub.id
    act(db, "rc-t4-delete", people["alice"])
    # Postgres removes the substitution itself (ON DELETE CASCADE), not the ORM.
    db.execute(text("DELETE FROM production_runs WHERE id = :i"), {"i": rid})
    tables = {r.table_name for r in db.query(M.RowChange).filter_by(group_key="rc-t4-delete")}
    assert tables == {"production_runs", "run_substitutions"}
    act(db, "rc-t4-undo", people["alice"])
    rc.undo(db, "rc-t4-delete", dry_run=False)
    db.expire_all()
    assert db.get(M.ProductionRun, rid).label == "RC"
    assert db.get(M.RunSubstitution, sid).fitted_mpn == "B"


def test_a_secret_is_never_kept_so_an_account_does_not_come_back(db, people):
    act(db, "rc-t5-create", people["admin"])
    u = M.User(username="rc-test-carol", password_hash="secret-hash", role="user")
    db.add(u)
    db.flush()
    made = db.query(M.RowChange).filter_by(group_key="rc-t5-create", table_name="users").one()
    assert "password_hash" not in made.new and made.new["username"] == "rc-test-carol"
    act(db, "rc-t5-delete", people["admin"])
    db.delete(u)
    db.flush()
    refused = rc.undo(db, "rc-t5-delete")["refused"]
    assert refused and "credential" in refused[0]["why"]


def test_a_user_undoes_their_own_requests_and_an_admin_anybodys(db, people):
    act(db, "rc-t6-create", people["alice"])
    db.add(M.Comment(target_type="component", target_id=1, author="a", body="alice's"))
    db.flush()
    act(db, "rc-t6-bob", people["bob"])
    with pytest.raises(HTTPException) as e:
        rc.undo(db, "rc-t6-create")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException):
        rc.detail(db, "rc-t6-create")
    assert "rc-t6-create" not in [g["key"] for g in rc.list_groups(db, everyone=True, limit=200)]
    act(db, "rc-t6-admin", people["admin"])
    assert rc.undo(db, "rc-t6-create")["refused"] == []
    assert "rc-t6-create" in [g["key"] for g in rc.list_groups(db, everyone=True, limit=200)]


def test_an_undo_that_would_take_stock_below_zero_is_refused(db, people):
    act(db, "rc-t7-buy", people["alice"])
    ledger.adjustment(db, mpn="RC-TEST-PART", qty=5, unit_cost_usd=None, reason="opening_balance",
                      at="2026-10-01", actor="a")
    assert rc.undo(db, "rc-t7-buy")["refused"] == []      # nothing drew it yet
    act(db, "rc-t7-draw", people["alice"])
    ledger.adjustment(db, mpn="RC-TEST-PART", qty=-5, unit_cost_usd=None, reason="scrap",
                      at="2026-10-02", actor="a")
    refused = rc.undo(db, "rc-t7-buy")["refused"]
    assert refused, "taking the purchase away would leave the part at -5"


def test_a_token_that_names_nobody_sees_no_change(db, people):
    act(db, "rc-t8-job", None)
    db.add(M.Comment(target_type="component", target_id=1, author="job", body="by a job"))
    db.flush()
    tracking.bind(tracking.RequestActor("rc-t8-legacy", None, "", "", "legacy", "legacy"))
    assert rc.list_groups(db, everyone=True) == []
    assert rc.row_history(db, "comments", {"id": 1}) == []
    with pytest.raises(HTTPException):
        rc.detail(db, "rc-t8-job")
