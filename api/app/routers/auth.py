"""Sign in, sign out, who am I, change my own password.

`POST /api/auth/login` is one of the few endpoints the default-deny middleware
lets through unauthenticated — see `main.py::_OPEN_PATHS`.

There is no registration endpoint and no password-reset endpoint, by user
decision 2026-07-31. An admin creates accounts and resets passwords in the
Setup page (`routers/users.py`). Do not add either: the login page has no link
to them, so an endpoint would be a way in that the UI does not admit to.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import auth
from .util import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


def user_json(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "is_admin": user.role == "admin",
    }


def _set_cookie(response: Response, sid: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        sid,
        max_age=settings.session_lifetime_days * 86400,
        httponly=True,
        secure=settings.session_cookie_secure,
        # Lax, not Strict: the SPA is entered by following a link or a
        # bookmark, and Strict would drop the cookie on that first navigation
        # and bounce a signed-in user to the login page.
        samesite="lax",
        path="/",
    )


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    username = auth.normalize_username(body.username)
    locked = auth.lockout_remaining(db, username)
    if locked:
        raise HTTPException(429, f"too many failed attempts — try again in {locked // 60 + 1} min")

    user = db.query(M.User).filter(M.User.username == username).first()
    if user is None:
        # Spend the same argon2 time as a real check, so response latency does
        # not tell an attacker which usernames exist.
        auth.verify_nobody(body.password)
        ok = False
    else:
        ok = user.active and auth.verify_password(user, body.password)
    if not ok:
        auth.record_failure(db, username)
        # One message for every failure mode (unknown user, wrong password,
        # deactivated account) so the response cannot enumerate accounts.
        raise HTTPException(401, "wrong username or password")

    auth.clear_failures(db, username)
    user.last_login_at = auth.utcnow()
    session = auth.create_session(
        db, user,
        user_agent=request.headers.get("user-agent", ""),
        ip=request.headers.get("cf-connecting-ip") or (request.client.host if request.client else ""),
    )
    audit(db, "auth.login", "user", user.id, actor=user.username)
    db.commit()
    _set_cookie(response, session.id)
    return user_json(user)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    sid = request.cookies.get(settings.session_cookie_name, "")
    if sid:
        auth.end_session(db, sid)
        db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    """Who the middleware resolved this request to.

    `auth_enabled=False` (dev) yields `{"user": null, "auth_enabled": false}`
    and the SPA then skips the login gate entirely.
    """
    user = getattr(request.state, "user", None)
    return {
        "auth_enabled": settings.auth_enabled,
        "user": user_json(user) if user is not None else None,
    }


class PasswordIn(BaseModel):
    current_password: str
    new_password: str


@router.post("/password")
def change_password(body: PasswordIn, request: Request, response: Response,
                    db: Session = Depends(get_db)):
    """Change your OWN password. An admin resetting somebody else's uses
    `PATCH /api/users/{id}` instead, which needs no current password."""
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(401, "sign in first")
    if not auth.verify_password(user, body.current_password):
        raise HTTPException(403, "current password is wrong")
    problem = auth.password_problem(body.new_password)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash = auth.hash_password(body.new_password)
    # Every other session dies with the old password, including this one; a new
    # cookie is issued below so the caller is not signed out of the tab they
    # are typing in.
    auth.end_all_sessions(db, user.id)
    session = auth.create_session(db, user, user_agent=request.headers.get("user-agent", ""))
    audit(db, "auth.password_change", "user", user.id, actor=user.username)
    db.commit()
    _set_cookie(response, session.id)
    return {"ok": True}
