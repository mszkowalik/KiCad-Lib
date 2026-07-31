"""Users, browser sessions and machine tokens.

The platform is reachable from the internet, and its API can approve
proposals, rewrite production cost records and drive the agent. So the gate is
DEFAULT-DENY and lives in one place (`main.py::auth_middleware`); this module
owns everything that gate needs to decide.

Two credential families, deliberately different:

- **Browser session** — an opaque random id in an HttpOnly cookie, backed by a
  `user_sessions` row. Server-side state costs one indexed lookup per request
  and buys immediate revocation: deactivating a user or clicking Log out ends
  the session now, not at the next expiry.
- **API token** — 32 random bytes shown as `7s_<43 chars>`, carried by KiCad,
  the sync plugin and the MCP server. Verified against a SHA-256 digest, NOT a
  password hash: the secret has 256 bits of entropy so there is nothing to
  brute-force, and this check sits on the KiCad symbol chooser's critical path
  (one request per category, every chooser open) where argon2 would add ~100 ms
  a call. Passwords, which are low-entropy, get argon2id.

See `models.py::ApiToken` for why the token is also stored encrypted.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from . import crypto

TOKEN_PREFIX = "7s_"
# Touch `last_used_at` at most this often per token. Without it the KiCad
# catalog would write a row on every category request.
_TOUCH_INTERVAL = timedelta(minutes=5)

_hasher = PasswordHasher()
# A real argon2id hash of a value nothing can present, for the equal-time path
# in `verify_nobody`. Computed once at import — hashing costs ~100 ms.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(32))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    """Postgres returns tz-aware datetimes, SQLite and defaults may not."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------- passwords
def normalize_username(name: str) -> str:
    return name.strip().lower()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(user: M.User, password: str) -> bool:
    try:
        return _hasher.verify(user.password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def verify_nobody(password: str) -> None:
    """Burn one argon2 verification against a fixed hash.

    Called when the username does not exist, so an unknown account costs the
    same wall-clock time as a wrong password and the login endpoint cannot be
    used to enumerate usernames.
    """
    try:
        _hasher.verify(_DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        pass


def password_problem(password: str) -> str | None:
    """Why this password is unacceptable, or None. Deliberately minimal — an
    admin sets these by hand for a handful of people."""
    if len(password) < 10:
        return "password must be at least 10 characters"
    return None


# ------------------------------------------------------------------ tokens
def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def mint_token(db: Session, user: M.User, label: str = "") -> tuple[M.ApiToken, str]:
    """Create a token for `user`. Returns the row and the CLEARTEXT value.

    The caller commits. Nothing else in the codebase generates a token — the
    prefix, the digest and the ciphertext must always be written together.
    """
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    tok = M.ApiToken(
        user_id=user.id,
        label=label or "KiCad + MCP",
        prefix=raw[:12],
        token_hash=_digest(raw),
        token_enc=crypto.encrypt_token(raw),
    )
    db.add(tok)
    return tok, raw


def token_cleartext(tok: M.ApiToken) -> str:
    """The token's value, for display and for baking into a personal URL.

    Returns "" when SECRET_KEY changed since the token was minted — the row is
    then only verifiable, not readable, and the fix is to rotate it.
    """
    if not tok.token_enc:
        return ""
    try:
        return crypto.decrypt_token(tok.token_enc)
    except ValueError:
        return ""


def resolve_token(db: Session, raw: str) -> M.User | None:
    """The active user behind a token string, or None.

    Personal tokens only. The pre-auth SHARED secrets are a separate question
    with no identity behind them — see `is_legacy_token`, which the middleware
    checks after this returns None.
    """
    if not raw:
        return None
    tok = (
        db.query(M.ApiToken)
        .filter(M.ApiToken.token_hash == _digest(raw), M.ApiToken.revoked_at.is_(None))
        .first()
    )
    if tok is None:
        return None
    user = db.get(M.User, tok.user_id)
    if user is None or not user.active:
        return None
    now = utcnow()
    last = _aware(tok.last_used_at)
    if last is None or now - last > _TOUCH_INTERVAL:
        tok.last_used_at = now
        db.commit()
    return user


def is_legacy_token(raw: str) -> bool:
    """A pre-auth shared secret from the environment. Never an identity."""
    if not settings.auth_legacy_tokens or not raw:
        return False
    return raw in {t for t in (settings.httplib_token, settings.mcp_token) if t}


# ---------------------------------------------------------------- sessions
def create_session(db: Session, user: M.User, user_agent: str = "", ip: str = "") -> M.UserSession:
    row = M.UserSession(
        id=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=utcnow() + timedelta(days=settings.session_lifetime_days),
        user_agent=user_agent[:300],
        ip=ip[:60],
    )
    db.add(row)
    return row


def resolve_session(db: Session, sid: str) -> M.User | None:
    """The active user behind a session cookie, or None.

    Expired, idle and orphaned sessions are DELETED here rather than merely
    refused, so the table cannot grow without bound and a stale cookie stops
    costing a lookup.
    """
    if not sid:
        return None
    row = db.get(M.UserSession, sid)
    if row is None:
        return None
    now = utcnow()
    idle_cutoff = now - timedelta(days=settings.session_idle_days)
    if (_aware(row.expires_at) or now) <= now or (_aware(row.last_seen_at) or now) < idle_cutoff:
        db.delete(row)
        db.commit()
        return None
    user = db.get(M.User, row.user_id)
    if user is None or not user.active:
        db.delete(row)
        db.commit()
        return None
    # Same rate limit as the token touch — one write per request would double
    # the cost of every page load.
    last = _aware(row.last_seen_at)
    if last is None or now - last > _TOUCH_INTERVAL:
        row.last_seen_at = now
        db.commit()
    return user


def end_session(db: Session, sid: str) -> None:
    row = db.get(M.UserSession, sid)
    if row is not None:
        db.delete(row)


def end_all_sessions(db: Session, user_id: int) -> int:
    """Sign a user out everywhere. Used on deactivate, delete and password
    change — a changed password that leaves live sessions is not a change."""
    rows = db.query(M.UserSession).filter(M.UserSession.user_id == user_id).all()
    for row in rows:
        db.delete(row)
    return len(rows)


# ----------------------------------------------------------------- lockout
def lockout_remaining(db: Session, username: str) -> int:
    """Seconds this username stays locked, 0 when it is not."""
    row = db.get(M.LoginAttempt, normalize_username(username))
    if row is None or row.locked_until is None:
        return 0
    left = (_aware(row.locked_until) - utcnow()).total_seconds()
    return max(0, int(left))


def record_failure(db: Session, username: str) -> None:
    name = normalize_username(username)
    row = db.get(M.LoginAttempt, name)
    if row is None:
        row = M.LoginAttempt(username=name, failures=0)
        db.add(row)
    row.failures += 1
    row.last_failed_at = utcnow()
    if row.failures >= settings.login_max_failures:
        row.locked_until = utcnow() + timedelta(minutes=settings.login_lockout_minutes)
        row.failures = 0
    db.commit()


def clear_failures(db: Session, username: str) -> None:
    row = db.get(M.LoginAttempt, normalize_username(username))
    if row is not None:
        db.delete(row)


# --------------------------------------------------------------- bootstrap
def bootstrap_admin(db: Session) -> str | None:
    """Create the first admin when the users table is empty.

    Returns a message for the startup log, or None when nothing was done.
    Deliberately a one-shot: once ANY user exists this is a no-op, so leaving
    ADMIN_PASSWORD in the environment can never reset a live account or
    resurrect a deleted one.
    """
    if db.query(M.User.id).first() is not None:
        return None
    if not settings.admin_password:
        return ("auth: no users exist and ADMIN_PASSWORD is unset — nobody can sign in. "
                "Set ADMIN_USERNAME/ADMIN_PASSWORD and restart.")
    problem = password_problem(settings.admin_password)
    if problem:
        return f"auth: refusing to create the first admin — {problem}"
    user = M.User(
        username=normalize_username(settings.admin_username),
        password_hash=hash_password(settings.admin_password),
        display_name="Administrator",
        role="admin",
    )
    db.add(user)
    db.flush()
    mint_token(db, user, label="KiCad + MCP")
    db.commit()
    return f"auth: created the first admin {user.username!r} from the environment"
