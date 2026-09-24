"""Every change is traced to the signed-in person who made it.

Decision record: docs/decisions/0050-every-change-names-the-person-who-made-it.md.

Two halves. The ORM hooks (`services/tracking.py`) run against the dev
database inside one transaction that is rolled back. The gate half wraps a tiny
app in `AuthGate` with the credential lookup and the request-log writer
replaced, so it needs no database and no real account.

Run from `api/`, with the dev database up:
    python -m pytest tests/auth -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import authgate
from app import models as M
from app.db import engine
from app.routers.util import acting_name, audit
from app.services import tracking

tracking.install()

ALICE = SimpleNamespace(id=4242, username="alice", display_name="Alice Example", role="user")


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
def as_alice():
    ctx = tracking.actor_for(ALICE, tracking.new_request_id(), "session")
    token = tracking.bind(ctx)
    try:
        yield ctx
    finally:
        tracking.unbind(token)


def _changes(db: Session, ctx, table: str) -> list[M.AuditLog]:
    """The `row.*` entries one request wrote about one table."""
    return (db.query(M.AuditLog)
            .filter(M.AuditLog.request_id == ctx.request_id, M.AuditLog.entity_type == table,
                    M.AuditLog.action.startswith(tracking.ROW_ACTION_PREFIX))
            .order_by(M.AuditLog.id).all())


# ------------------------------------------------------------------ audit log

def test_audit_row_names_the_person_and_the_request(db, as_alice):
    audit(db, "test.thing", "test", 1)  # the call-site default: actor="user"
    audit(db, "test.robot", "test", 2, actor="jaravis")
    db.flush()
    rows = {a.action: a for a in db.query(M.AuditLog).filter_by(request_id=as_alice.request_id)
            if not a.action.startswith(tracking.ROW_ACTION_PREFIX)}
    assert rows["test.thing"].actor == "Alice Example"
    assert rows["test.thing"].user_id == ALICE.id
    # A robot label is a true statement and stays — the person is in user_id.
    assert rows["test.robot"].actor == "jaravis"
    assert rows["test.robot"].user_id == ALICE.id


def test_outside_a_request_nothing_is_attributed(db):
    audit(db, "test.background", "test", 3)
    db.flush()
    a = db.query(M.AuditLog).filter_by(action="test.background").order_by(M.AuditLog.id.desc()).first()
    assert a.actor == "user" and a.user_id is None and a.request_id is None


# -------------------------------------------------------------- who-columns

def test_placeholder_default_becomes_the_person(db, as_alice):
    c = M.Comment(target_type="component", target_id=1, body="x")  # author defaults to "user"
    db.add(c)
    db.flush()
    assert c.author == "Alice Example"


def test_a_robot_label_in_a_who_column_is_kept(db, as_alice):
    c = M.Comment(target_type="component", target_id=1, body="x", author="jaravis")
    db.add(c)
    db.flush()
    assert c.author == "jaravis"


def test_editing_an_old_row_does_not_rename_its_author(db):
    c = M.Comment(target_type="component", target_id=1, body="old", author="user")
    db.add(c)
    db.flush()  # written outside any request, as history is
    ctx = tracking.actor_for(ALICE, tracking.new_request_id(), "session")
    token = tracking.bind(ctx)
    try:
        c.body = "edited"
        db.flush()
    finally:
        tracking.unbind(token)
    assert c.author == "user"


def test_acting_name_ignores_a_claimed_name_when_signed_in(as_alice):
    assert acting_name("mallory") == "Alice Example"


def test_acting_name_uses_the_claim_only_with_nobody_signed_in():
    ctx = tracking.actor_for(None, tracking.new_request_id(), "none")
    token = tracking.bind(ctx)
    try:
        assert acting_name("dev-bob") == "dev-bob"
        assert acting_name("") == "user"
    finally:
        tracking.unbind(token)


# ------------------------------------------------------------ row entries

def test_insert_update_delete_are_recorded_with_old_and_new(db, as_alice):
    c = M.Comment(target_type="component", target_id=1, body="first")
    db.add(c)
    db.flush()
    c.body = "second"
    db.flush()
    db.delete(c)
    db.flush()
    ops = _changes(db, as_alice, "comments")
    assert [o.action for o in ops] == ["row.insert", "row.update", "row.delete"]
    assert all(o.entity_id == str(c.id) and o.user_id == ALICE.id for o in ops)
    assert all(o.actor == "Alice Example" for o in ops)
    assert ops[0].details["body"] == "first"
    assert ops[0].details["author"] == "Alice Example"
    assert ops[1].details == {"body": ["first", "second"]}


def test_secrets_never_reach_the_log(db, as_alice):
    u = M.User(username="tracking-test-user", password_hash="argon2-secret", role="user")
    db.add(u)
    db.flush()
    tok = M.ApiToken(user_id=u.id, prefix="abcd1234", token_hash="h" * 64, token_enc="enc")
    db.add(tok)
    db.flush()
    user_row = _changes(db, as_alice, "users")[0].details
    tok_row = _changes(db, as_alice, "api_tokens")[0].details
    assert user_row["password_hash"] == tracking.REDACTED
    assert tok_row["token_hash"] == tracking.REDACTED
    assert tok_row["token_enc"] == tracking.REDACTED
    assert tok_row["prefix"] == "abcd1234"


def test_a_large_value_is_kept_as_its_digest(db, as_alice):
    c = M.Comment(target_type="component", target_id=1, body="z" * 5000)
    db.add(c)
    db.flush()
    body = _changes(db, as_alice, "comments")[0].details["body"]
    assert body["len"] == 5000 and len(body["sha256"]) == 64


def test_no_row_entries_outside_a_request(db):
    def rows():
        return db.query(M.AuditLog).filter(M.AuditLog.action.startswith(tracking.ROW_ACTION_PREFIX)).count()
    before = rows()
    db.add(M.Comment(target_type="component", target_id=1, body="background"))
    db.flush()
    assert rows() == before


def test_the_request_row_carries_the_call(db, monkeypatch):
    """`write_request_row` opens its own session; point it at the test's."""
    monkeypatch.setattr("app.db.SessionLocal", lambda: _NoClose(db))
    ctx = tracking.actor_for(ALICE, tracking.new_request_id(), "token")
    tracking.write_request_row(ctx, "PATCH", "/api/run-documents/1/lines", "dry_run=true",
                               409, 12, "10.0.0.1", "curl")
    r = db.query(M.AuditLog).filter_by(request_id=ctx.request_id).one()
    assert (r.action, r.entity_type, r.entity_id, r.actor, r.user_id) == (
        "request", "http", "/api/run-documents/1/lines", "Alice Example", ALICE.id)
    assert r.details["status"] == 409 and r.details["method"] == "PATCH"


class _NoClose:
    """The test's session, with commit turned into flush and close into a no-op,
    so the rolled-back transaction still holds everything."""

    def __init__(self, s: Session):
        self._s = s

    def __getattr__(self, name):
        return getattr(self._s, name)

    def commit(self):
        self._s.flush()

    def close(self):
        pass


# ------------------------------------------------------------------ the gate

@pytest.fixture
def gated(monkeypatch):
    """A tiny app behind the real gate, with the lookup and the log faked."""
    logged: list[tuple] = []
    monkeypatch.setattr(authgate.settings, "auth_enabled", True)
    monkeypatch.setattr(authgate, "_resolve", lambda *a: (ALICE, True, "token"))
    monkeypatch.setattr(authgate.tracking, "write_request_row", lambda *a: logged.append(a))

    app = FastAPI()

    @app.get("/api/who")
    def who_sync():  # sync: runs in a worker thread, like most routes here
        ctx = tracking.current()
        return {"user_id": ctx.user_id if ctx else None, "name": ctx.name if ctx else None}

    @app.post("/api/thing")
    async def make_thing():
        return {"name": tracking.current().name}

    app.add_middleware(authgate.AuthGate)
    return TestClient(app), logged


def test_a_sync_route_sees_the_caller(gated):
    client, logged = gated
    r = client.get("/api/who", headers={"Authorization": "Bearer x"})
    assert r.json() == {"user_id": ALICE.id, "name": "Alice Example"}
    assert logged == []  # reads are not logged


def test_a_write_is_logged_with_person_status_and_no_token(gated):
    client, logged = gated
    r = client.post("/api/thing?t=secret-token&dry_run=true", headers={"Authorization": "Bearer x"})
    assert r.json() == {"name": "Alice Example"}
    (ctx, method, path, query, status, _ms, _ip, _ua), = logged
    assert (ctx.user_id, ctx.auth_via, method, path, status) == (ALICE.id, "token", "POST", "/api/thing", 200)
    assert query == "dry_run=true"


def test_the_context_does_not_leak_past_the_request(gated):
    client, _ = gated
    client.post("/api/thing", headers={"Authorization": "Bearer x"})
    assert tracking.current() is None


# ------------------------------------------------------------- the read side

def test_the_activity_list_counts_what_each_request_wrote(db, monkeypatch):
    """The list runs a GROUP BY that Postgres refused once (grouping error on a
    bound `startswith`). Calls the route function directly, past the gate."""
    from app.routers import activity

    monkeypatch.setattr("app.db.SessionLocal", lambda: _NoClose(db))
    ctx = tracking.actor_for(ALICE, tracking.new_request_id(), "session")
    token = tracking.bind(ctx)
    try:
        c = M.Comment(target_type="component", target_id=1, body="counted")
        db.add(c)
        db.flush()
        audit(db, "comment.add", "comment", c.id)
        db.flush()
    finally:
        tracking.unbind(token)
    tracking.write_request_row(ctx, "POST", "/api/components/1/comments", "", 200, 5, "", "")

    page = activity.list_activity(kind="request,event", who="alice", q="", user_id=None,
                                  entity_type="", entity_id="", since="", until="",
                                  before_id=None, limit=50, db=db, _admin=None)
    mine = [r for r in page["rows"] if r["request_id"] == ctx.request_id]
    assert [r["kind"] for r in mine] == ["request", "event"]
    assert mine[0]["counts"] == {"rows": 1, "events": 1}
    detail = activity.request_detail(ctx.request_id, db=db, _admin=None)
    assert [r["action"] for r in detail["rows"]] == ["row.insert", "comment.add", "request"]
    assert detail["write_batches"] == []


def test_a_write_batch_names_the_signed_in_person(db, as_alice):
    """`journal.batch` ignores the actor the caller passed when somebody is
    signed in — the Write log's `?actor=` was a claim anyone could make."""
    from app.services import journal

    proj = M.Project(name="tracking-batch-test", git_url="https://example.invalid/t.git")
    db.add(proj)
    db.flush()
    with journal.batch(db, kind="test.batch", actor="mallory"):
        db.add(M.ComponentStockAdjustment(project_id=proj.id, mpn="X", qty_delta=1, reason="count"))
    wb = db.query(M.WriteBatch).filter_by(kind="test.batch").order_by(M.WriteBatch.id.desc()).first()
    assert (wb.actor, wb.user_id, wb.request_id) == ("Alice Example", ALICE.id, as_alice.request_id)
