"""What the SIGNED-IN user may do to their own account.

Everything here has an admin-gated twin in `routers/users.py`, and that is the
point: `users.py` is administration of OTHER people's accounts, this is a person
acting on their own. Nothing in it takes a user id — the subject is always
`request.state.user`, so no endpoint here can be aimed at somebody else by
changing a number in a URL.

**Changing your own password is NOT here.** `POST /api/auth/password` has done
it since sign-in was built, and it does it better: it re-issues the session
cookie after ending every session, so the person is not signed out of the tab
they are typing in. A second implementation would have been a worse copy.

**No role, no active flag, no delete.** Those are the self-lockout guards
`users.py` documents; the safe way to keep them is to give this router no way to
touch them at all.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import auth
from .users import user_json
from .util import audit

router = APIRouter(prefix="/api/account", tags=["account"])


def _me(request: Request, db: Session) -> M.User:
    """The signed-in user, or a refusal.

    With auth disabled (dev) there is no user at all. The rest of the API takes
    the posture that everything is permitted in that mode, but here there is no
    subject to act on — every endpoint would have to invent one — so this one
    refuses with a message that names the reason instead of 401ing mysteriously.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        if not settings.auth_enabled:
            raise HTTPException(
                409, "authentication is disabled on this deployment, so there is no "
                     "account to manage")
        raise HTTPException(401, "sign in first")
    # RE-LOAD into THIS request's session. `AuthGate` resolves the user with a
    # session of its own and closes it, so the object on `request.state` is
    # detached: reading a loaded column works, and the first lazy load —
    # `user.tokens`, which `user_json` needs — raises DetachedInstanceError.
    # `require_admin` gets away without this because it only reads `.role`.
    fresh = db.get(M.User, user.id)
    if fresh is None:
        raise HTTPException(401, "sign in first")
    return fresh


@router.get("")
def get_account(request: Request, db: Session = Depends(get_db)):
    """Own profile, own tokens IN THE CLEAR, and the personal KiCad URLs.

    Revealing the token here is the same decision `users.py` records: the token
    is baked into a personal PCM repository URL, so show-once would mean a
    rotation and a KiCad re-install every time somebody loses the link.
    """
    return user_json(db, _me(request, db), reveal=True)


class TokenIn(BaseModel):
    label: str = ""


@router.post("/tokens")
def add_own_token(body: TokenIn, request: Request, db: Session = Depends(get_db)):
    user = _me(request, db)
    tok, _raw = auth.mint_token(db, user, label=body.label)
    audit(db, "account.token_create", "user", user.id, details={"prefix": tok.prefix},
          actor=user.username)
    db.commit()
    return user_json(db, user, reveal=True)


@router.delete("/tokens/{token_id}")
def revoke_own_token(token_id: int, request: Request, db: Session = Depends(get_db)):
    """Revoke rather than delete: the row is the record that the credential
    existed and when it was last used."""
    user = _me(request, db)
    tok = db.get(M.ApiToken, token_id)
    # Checking ownership here is what stops a user revoking somebody else's
    # token by guessing an id.
    if tok is None or tok.user_id != user.id:
        raise HTTPException(404, "no such token")
    tok.revoked_at = auth.utcnow()
    audit(db, "account.token_revoke", "user", user.id, details={"prefix": tok.prefix},
          actor=user.username)
    db.commit()
    return user_json(db, user, reveal=True)
