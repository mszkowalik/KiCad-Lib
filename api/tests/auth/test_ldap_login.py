"""The home LDAP sign-in (decision 0114).

Runs against the dev database inside a transaction that is rolled back. The
directory itself is not reached: `ldap_login.check` is replaced, except in the
tests that prove it refuses before any network call.
"""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from app import models as M
from app.config import settings
from app.db import engine
from app.routers import auth as auth_router
from app.routers import users as users_router
from app.services import auth, ldap_login

LOCAL = "local-password-123"


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
def ldap_on(monkeypatch):
    monkeypatch.setattr(settings, "ldap_url", "ldap://directory.invalid:3890")
    monkeypatch.setattr(settings, "ldap_bind_dn", "uid=svc,ou=people,dc=x")
    monkeypatch.setattr(settings, "ldap_user_base", "ou=people,dc=x")
    seen = []

    def fake_check(uid, password):
        seen.append(uid)
        return uid == "ldap-test-mateusz" and password == "directory-pass"

    monkeypatch.setattr(ldap_login, "check", fake_check)
    return seen


def _user(db, name="ldap-test@example.com", uid="ldap-test-mateusz", active=True):
    u = M.User(username=name, password_hash=auth.hash_password(LOCAL), ldap_uid=uid, active=active)
    db.add(u)
    db.flush()
    return u


def _login(db, username, password):
    req = Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)})
    return auth_router.login(auth_router.LoginIn(username=username, password=password), req, Response(), db)


def _last_via(db, user):
    row = (db.query(M.AuditLog).filter(M.AuditLog.action == "auth.login", M.AuditLog.entity_id == str(user.id))
           .order_by(M.AuditLog.id.desc()).first())
    return (row.details or {}).get("via")


def test_directory_password_with_the_uid(db, ldap_on):
    u = _user(db)
    assert _login(db, "LDAP-Test-Mateusz", "directory-pass")["id"] == u.id
    assert _last_via(db, u) == "ldap"


def test_directory_password_with_the_henry_username(db, ldap_on):
    u = _user(db)
    assert _login(db, "ldap-test@example.com", "directory-pass")["id"] == u.id


def test_local_password_still_works(db, ldap_on):
    u = _user(db)
    assert _login(db, "ldap-test-mateusz", LOCAL)["id"] == u.id
    assert _last_via(db, u) == "password"


def test_wrong_password_is_refused(db, ldap_on):
    _user(db)
    with pytest.raises(HTTPException) as exc:
        _login(db, "ldap-test-mateusz", "wrong-password-1")
    assert exc.value.status_code == 401


def test_an_unlinked_account_never_asks_the_directory(db, ldap_on):
    _user(db, uid=None)
    with pytest.raises(HTTPException):
        _login(db, "ldap-test@example.com", "directory-pass")
    assert ldap_on == []


def test_a_deactivated_account_is_refused(db, ldap_on):
    _user(db, active=False)
    with pytest.raises(HTTPException) as exc:
        _login(db, "ldap-test-mateusz", "directory-pass")
    assert exc.value.status_code == 401
    assert ldap_on == []


def test_the_uid_is_not_a_login_name_while_ldap_is_off(db, monkeypatch):
    monkeypatch.setattr(settings, "ldap_url", "")
    _user(db)
    with pytest.raises(HTTPException):
        _login(db, "ldap-test-mateusz", LOCAL)


def test_failures_count_against_the_account_whichever_name(db, ldap_on, monkeypatch):
    monkeypatch.setattr(settings, "login_max_failures", 2)
    _user(db)
    for name in ("ldap-test-mateusz", "ldap-test@example.com"):
        with pytest.raises(HTTPException):
            _login(db, name, "wrong-password-1")
    with pytest.raises(HTTPException) as exc:
        _login(db, "ldap-test-mateusz", "directory-pass")
    assert exc.value.status_code == 429


def test_check_refuses_an_empty_password_before_the_network(monkeypatch):
    # An LDAP simple bind with a DN and no password is an unauthenticated bind,
    # which a server may report as success (RFC 4513 §5.1.2).
    monkeypatch.setattr(settings, "ldap_url", "ldap://directory.invalid:3890")
    monkeypatch.setattr(settings, "ldap_bind_dn", "uid=svc,ou=people,dc=x")
    monkeypatch.setattr(settings, "ldap_user_base", "ou=people,dc=x")
    assert ldap_login.check("mateusz", "") is False
    assert ldap_login.check("", "x") is False


def test_check_is_off_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "ldap_url", "")
    assert ldap_login.check("mateusz", "anything") is False


def test_uid_is_cleaned_and_unique(db):
    _user(db)
    assert users_router._ldap_uid(db, "  Kuba ", None) == "kuba"
    assert users_router._ldap_uid(db, "", None) is None
    with pytest.raises(HTTPException) as exc:
        users_router._ldap_uid(db, "a)(uid=*", None)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        users_router._ldap_uid(db, "LDAP-test-mateusz", None)
    assert exc.value.status_code == 409
