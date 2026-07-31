"""User administration — the Users card on the Setup page.

Admin only, all of it. Accounts are created here and nowhere else: there is no
registration endpoint and no password-reset endpoint (see `routers/auth.py`).

Every user carries at least one API token, and this is where the client-facing
artifacts built from it live:

- `repository_url` — the personal PCM repository. Pasting it into KiCad's
  Plugin and Content Manager installs the library, the 3D models, and a sync
  plugin with that user's token already baked in. See `routers/kicad_sync.py`.
- `httplib_url` — a `.kicad_httplib` download carrying the same token.

Both are plain URLs with the token in the query string, because PCM sends no
headers. That is a deliberate, scoped exception — see `main.py::_QUERY_TOKEN_PATHS`.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import auth
from .util import audit

router = APIRouter(prefix="/api/users", tags=["users"])


def require_admin(request: Request) -> M.User:
    """The signed-in admin, or a refusal.

    When `auth_enabled` is false (dev) there is no user at all and everything
    is permitted — the same posture the rest of the API takes in that mode.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        if not settings.auth_enabled:
            return None  # type: ignore[return-value]
        raise HTTPException(401, "sign in first")
    if user.role != "admin":
        raise HTTPException(403, "administrator only")
    return user


def _actor(admin: M.User | None) -> str:
    return admin.username if admin is not None else "dev"


def token_json(tok: M.ApiToken, *, reveal: bool) -> dict:
    return {
        "id": tok.id,
        "label": tok.label,
        "prefix": tok.prefix,
        "token": auth.token_cleartext(tok) if reveal else "",
        "created_at": tok.created_at.isoformat() if tok.created_at else None,
        "last_used_at": tok.last_used_at.isoformat() if tok.last_used_at else None,
    }


def _client_urls(token: str) -> dict:
    """The two links a user pastes into KiCad. Empty when the token cannot be
    decrypted (SECRET_KEY changed) — the UI then offers a rotation."""
    if not token:
        return {"repository_url": "", "httplib_url": ""}
    base = settings.public_base_url.rstrip("/")
    return {
        "repository_url": f"{base}/api/kicad/pcm/repository.json?t={token}",
        "httplib_url": f"{base}/api/kicad/httplib-file?t={token}",
    }


def user_json(db: Session, user: M.User, *, reveal: bool = False) -> dict:
    live = [t for t in user.tokens if t.revoked_at is None]
    live.sort(key=lambda t: t.id)
    primary = auth.token_cleartext(live[0]) if live else ""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "active": user.active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        "session_count": db.query(M.UserSession).filter(M.UserSession.user_id == user.id).count(),
        "tokens": [token_json(t, reveal=reveal) for t in live],
        **_client_urls(primary if reveal else ""),
    }


@router.get("")
def list_users(db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """Every account. Token VALUES are withheld here — the list is a table, and
    a secret does not belong in a payload nobody asked to reveal. Fetch one
    user to see them."""
    users = db.query(M.User).order_by(M.User.username).all()
    return [user_json(db, u) for u in users]


@router.get("/{user_id}")
def get_user(user_id: int, db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """One account WITH its token values and personal KiCad URLs."""
    user = db.get(M.User, user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    return user_json(db, user, reveal=True)


class UserIn(BaseModel):
    username: str
    password: str
    display_name: str = ""
    role: str = "user"


@router.post("")
def create_user(body: UserIn, db: Session = Depends(get_db),
                admin: M.User = Depends(require_admin)):
    username = auth.normalize_username(body.username)
    if not username:
        raise HTTPException(422, "username is required")
    if body.role not in ("admin", "user"):
        raise HTTPException(422, "role must be 'admin' or 'user'")
    problem = auth.password_problem(body.password)
    if problem:
        raise HTTPException(422, problem)
    if db.query(M.User).filter(M.User.username == username).first() is not None:
        raise HTTPException(409, f"user {username!r} already exists")
    user = M.User(
        username=username,
        password_hash=auth.hash_password(body.password),
        display_name=body.display_name.strip(),
        role=body.role,
    )
    db.add(user)
    db.flush()
    # Every user gets a token at creation. The point of an account here is to
    # reach KiCad and the MCP server, so an account with no token would be
    # half-made and the admin would have to notice.
    auth.mint_token(db, user, label="KiCad + MCP")
    audit(db, "user.create", "user", user.id,
          details={"username": username, "role": body.role}, actor=_actor(admin))
    db.commit()
    return user_json(db, user, reveal=True)


class UserPatch(BaseModel):
    display_name: str | None = None
    role: str | None = None
    active: bool | None = None
    password: str | None = None


@router.patch("/{user_id}")
def update_user(user_id: int, body: UserPatch, db: Session = Depends(get_db),
                admin: M.User = Depends(require_admin)):
    """Rename, re-role, deactivate, or reset the password.

    Two self-lockout guards: an admin may not drop their own admin role and may
    not deactivate themselves. Either one, done by the last admin, would leave
    the platform with no way back in short of editing the database.
    """
    user = db.get(M.User, user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    changed: dict = {}

    if body.display_name is not None:
        user.display_name = body.display_name.strip()
        changed["display_name"] = user.display_name
    if body.role is not None and body.role != user.role:
        if body.role not in ("admin", "user"):
            raise HTTPException(422, "role must be 'admin' or 'user'")
        if admin is not None and user.id == admin.id and body.role != "admin":
            raise HTTPException(409, "you cannot remove your own administrator role")
        if user.role == "admin" and body.role != "admin" and _admin_count(db) <= 1:
            raise HTTPException(409, "this is the only administrator")
        user.role = body.role
        changed["role"] = body.role
    if body.active is not None and body.active != user.active:
        if admin is not None and user.id == admin.id and not body.active:
            raise HTTPException(409, "you cannot deactivate yourself")
        if user.role == "admin" and not body.active and _admin_count(db) <= 1:
            raise HTTPException(409, "this is the only administrator")
        user.active = body.active
        changed["active"] = body.active
        if not body.active:
            auth.end_all_sessions(db, user.id)
    if body.password is not None:
        problem = auth.password_problem(body.password)
        if problem:
            raise HTTPException(422, problem)
        user.password_hash = auth.hash_password(body.password)
        # A reset that leaves the old sessions alive has not reset anything.
        auth.end_all_sessions(db, user.id)
        auth.clear_failures(db, user.username)
        changed["password"] = "(reset)"

    audit(db, "user.update", "user", user.id, details=changed, actor=_actor(admin))
    db.commit()
    return user_json(db, user, reveal=True)


def _admin_count(db: Session) -> int:
    return db.query(M.User).filter(M.User.role == "admin", M.User.active.is_(True)).count()


@router.delete("/{user_id}")
def delete_user(user_id: int, db: Session = Depends(get_db),
                admin: M.User = Depends(require_admin)):
    user = db.get(M.User, user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    if admin is not None and user.id == admin.id:
        raise HTTPException(409, "you cannot delete yourself")
    if user.role == "admin" and _admin_count(db) <= 1:
        raise HTTPException(409, "this is the only administrator")
    username = user.username
    db.delete(user)  # tokens and sessions cascade
    audit(db, "user.delete", "user", user_id, details={"username": username},
          actor=_actor(admin))
    db.commit()
    return {"ok": True}


@router.post("/{user_id}/sessions/revoke")
def revoke_sessions(user_id: int, db: Session = Depends(get_db),
                    admin: M.User = Depends(require_admin)):
    """Sign this user out of every browser."""
    user = db.get(M.User, user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    n = auth.end_all_sessions(db, user.id)
    audit(db, "user.sessions_revoked", "user", user.id, details={"count": n},
          actor=_actor(admin))
    db.commit()
    return {"ok": True, "revoked": n}


class TokenIn(BaseModel):
    label: str = ""


@router.post("/{user_id}/tokens")
def add_token(user_id: int, body: TokenIn, db: Session = Depends(get_db),
              admin: M.User = Depends(require_admin)):
    user = db.get(M.User, user_id)
    if user is None:
        raise HTTPException(404, "no such user")
    tok, _raw = auth.mint_token(db, user, label=body.label)
    audit(db, "user.token_create", "user", user.id, details={"prefix": tok.prefix},
          actor=_actor(admin))
    db.commit()
    return user_json(db, user, reveal=True)


@router.delete("/{user_id}/tokens/{token_id}")
def revoke_token(user_id: int, token_id: int, db: Session = Depends(get_db),
                 admin: M.User = Depends(require_admin)):
    """Revoke rather than delete: the row is the record that the credential
    existed and when it was last used."""
    tok = db.get(M.ApiToken, token_id)
    if tok is None or tok.user_id != user_id:
        raise HTTPException(404, "no such token")
    tok.revoked_at = auth.utcnow()
    audit(db, "user.token_revoke", "user", user_id, details={"prefix": tok.prefix},
          actor=_actor(admin))
    db.commit()
    user = db.get(M.User, user_id)
    return user_json(db, user, reveal=True)
