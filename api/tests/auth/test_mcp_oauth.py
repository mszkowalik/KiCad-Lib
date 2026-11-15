"""The remote MCP endpoint's sign-in rules (decision 0111).

Runs against the dev database inside a transaction that is rolled back.
The Google leg itself is not exercised here: `grant` is what it calls once
Google has verified the e-mail.
"""

from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.authgate import _is_open
from app.db import engine
from app.services import auth, mcp_remote


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


def _user(db, name="oauth-test", email="Someone@Example.com", active=True):
    u = M.User(username=name, password_hash="x", email=email, active=active)
    db.add(u)
    db.flush()
    return u


def _token(db, user, kind="access", ttl=3600, raw="tok-" + "a" * 40):
    db.add(M.OAuthToken(token_hash=auth._digest(raw), kind=kind, client_id="c", user_id=user.id,
                        scopes=["henry"], expires_at=auth.utcnow() + timedelta(seconds=ttl)))
    db.flush()
    return raw


def test_only_claude_and_loopback_redirects():
    assert mcp_remote.redirect_allowed("https://claude.ai/api/mcp/auth_callback")
    assert mcp_remote.redirect_allowed("https://claude.com/api/mcp/auth_callback")
    assert mcp_remote.redirect_allowed("http://localhost:53682/callback")
    assert mcp_remote.redirect_allowed("http://127.0.0.1:9/cb")
    assert not mcp_remote.redirect_allowed("https://claude.ai.evil.example/api/mcp/auth_callback")
    assert not mcp_remote.redirect_allowed("https://localhost/cb")
    assert not mcp_remote.redirect_allowed("http://evil.example/cb")


def test_email_must_match_an_active_account(db):
    u = _user(db)
    assert mcp_remote.user_for_email(db, "someone@example.com").id == u.id
    assert mcp_remote.user_for_email(db, " SOMEONE@example.com ").id == u.id
    assert mcp_remote.user_for_email(db, "other@example.com") is None
    assert mcp_remote.user_for_email(db, "") is None
    u.active = False
    db.flush()
    assert mcp_remote.user_for_email(db, "someone@example.com") is None


def test_grant_is_single_use_and_names_the_user(db):
    u = _user(db)
    db.add(M.OAuthRequest(id="req1", client_id="c1", params={
        "state": "s", "scopes": ["henry"], "code_challenge": "x" * 43,
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "redirect_uri_provided_explicitly": True, "resource": None}))
    db.flush()
    url = mcp_remote.grant(db, "req1", u)
    assert url.startswith("https://claude.ai/api/mcp/auth_callback?") and "state=s" in url
    code = db.query(M.OAuthCode).filter(M.OAuthCode.client_id == "c1").one()
    assert code.user_id == u.id
    # The audience is this server even when the client named no resource.
    assert code.data["resource"].endswith("/mcp")
    assert mcp_remote.grant(db, "req1", u) is None


def test_an_expired_request_grants_nothing(db):
    u = _user(db)
    db.add(M.OAuthRequest(id="req2", client_id="c1", params={}, created_at=auth.utcnow() - timedelta(hours=1)))
    db.flush()
    assert mcp_remote.grant(db, "req2", u) is None


def test_an_access_token_is_a_henry_credential(db):
    u = _user(db)
    raw = _token(db, u)
    assert auth.resolve_token(db, raw).id == u.id


def test_refresh_expired_revoked_and_inactive_are_refused(db):
    u = _user(db)
    assert auth.resolve_token(db, _token(db, u, kind="refresh", raw="r" * 40)) is None
    assert auth.resolve_token(db, _token(db, u, ttl=-1, raw="e" * 40)) is None
    raw = _token(db, u, raw="v" * 40)
    db.get(M.OAuthToken, auth._digest(raw)).revoked_at = auth.utcnow()
    db.flush()
    assert auth.resolve_token(db, raw) is None
    raw = _token(db, u, raw="i" * 40)
    u.active = False
    db.flush()
    assert auth.resolve_token(db, raw) is None


def test_signing_out_everywhere_ends_oauth_tokens(db):
    u = _user(db)
    raw = _token(db, u)
    auth.end_all_sessions(db, u.id)
    db.flush()
    db.expire_all()
    assert auth.resolve_token(db, raw) is None


def test_the_gate_opens_the_oauth_paths_only():
    for path in ("/mcp", "/.well-known/oauth-authorization-server", "/.well-known/oauth-protected-resource/mcp",
                 "/authorize", "/token", "/register", "/revoke", "/oauth/login", "/oauth/google/callback"):
        assert _is_open(path), path
    for path in ("/api/agent/tools", "/api/users", "/files/x", "/.well-known/other"):
        assert not _is_open(path), path


def test_the_remote_server_leaves_out_the_disk_tools():
    assert mcp_remote.DISK_TOOLS == {"upload_model3d", "attach_invoice_file"}
