"""Named git account credentials — create, assign, rotate, check.

A credential is one hosting ACCOUNT's token. Projects point at it by id, so a
token exists once no matter how many repositories use it, and rotating it is
one edit rather than one per project. See decision 0010 and the `GitCredential`
docstring for what went wrong when every project kept its own copy.

**The token never comes back out.** Every response says only whether one is
stored and what the provider said about it the last time it was checked, the
same posture as `SettingsCard`'s secrets and `ApiToken`: the field offers
"replace", never "edit".

Gating matches what the project router already allows: any signed-in user, not
admin-only. Setting a raw token on a project has always been open to any signed
in user, so requiring admin here would forbid the safe path while leaving the
unsafe one open. Revisit the pair together, never one of them.
"""
from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..models import utcnow
from ..services import gitrepo
from ..services.crypto import decrypt_token, encrypt_token
from .util import actor_of, audit

router = APIRouter(prefix="/api/git-credentials", tags=["git-credentials"])


def _json(c: M.GitCredential) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "host": c.host,
        "username": c.username,
        "description": c.description,
        # Never the token itself — only that one is stored.
        "has_token": bool(c.token_enc),
        "checked_at": c.checked_at,
        "check_ok": c.check_ok,
        "check_detail": c.check_detail,
        "created_at": c.created_at,
        "created_by": c.created_by,
        "projects": [{"id": p.id, "name": p.name} for p in
                     sorted(c.projects, key=lambda p: p.name)],
    }


def _get(db: Session, cred_id: int) -> M.GitCredential:
    c = db.get(M.GitCredential, cred_id)
    if c is None:
        raise HTTPException(404, "credential not found")
    return c


class CredentialIn(BaseModel):
    name: str
    token: str
    host: str = ""
    username: str = ""
    description: str = ""


class CredentialPatch(BaseModel):
    name: str | None = None
    # None leaves the stored token alone. A non-empty string replaces it.
    # There is no way to clear one: a credential with no token is not a
    # credential, and deleting the row is the honest way to remove it.
    token: str | None = None
    host: str | None = None
    username: str | None = None
    description: str | None = None


@router.get("")
def list_credentials(db: Session = Depends(get_db)):
    return [_json(c) for c in db.query(M.GitCredential).order_by(M.GitCredential.name).all()]


@router.post("")
def create_credential(body: CredentialIn, request: Request, db: Session = Depends(get_db)):
    name = body.name.strip()
    token = body.token.strip()
    if not name:
        raise HTTPException(422, "a credential needs a name — it is how projects pick it")
    if not token:
        raise HTTPException(422, "a credential needs a token")
    if db.query(M.GitCredential).filter_by(name=name).first():
        raise HTTPException(409, f"a credential named '{name}' already exists")
    c = M.GitCredential(
        name=name,
        token_enc=encrypt_token(token),
        host=body.host.strip(),
        username=body.username.strip(),
        description=body.description,
        created_by=actor_of(request),
    )
    db.add(c)
    db.flush()
    audit(db, "git_credential.create", "git_credential", c.id, {"name": name})
    db.commit()
    return _json(c)


@router.patch("/{cred_id}")
def update_credential(cred_id: int, body: CredentialPatch, request: Request,
                      db: Session = Depends(get_db)):
    c = _get(db, cred_id)
    if body.name is not None and body.name.strip() and body.name.strip() != c.name:
        if db.query(M.GitCredential).filter_by(name=body.name.strip()).first():
            raise HTTPException(409, "name already in use")
        c.name = body.name.strip()
    rotated = False
    if body.token is not None and body.token.strip():
        c.token_enc = encrypt_token(body.token.strip())
        # The old verdict described the old secret. Saying nothing is right
        # until somebody checks the new one.
        c.checked_at, c.check_ok, c.check_detail = None, None, ""
        rotated = True
    if body.host is not None:
        c.host = body.host.strip()
    if body.username is not None:
        c.username = body.username.strip()
    if body.description is not None:
        c.description = body.description
    audit(db, "git_credential.update", "git_credential", c.id,
          {"name": c.name, "token": "replaced" if rotated else "unchanged"})
    db.commit()
    return _json(c)


@router.delete("/{cred_id}")
def delete_credential(cred_id: int, request: Request, db: Session = Depends(get_db)):
    c = _get(db, cred_id)
    if c.projects:
        # Refuse and name them, the way the flasher refuses to delete an
        # artifact something still pins. Silently unassigning would leave
        # those projects unable to fetch with nothing on screen to say why.
        names = ", ".join(sorted(p.name for p in c.projects))
        raise HTTPException(409, detail={
            "error": f"'{c.name}' is still used by {len(c.projects)} project(s): {names}. "
                     "Point them at another credential first.",
            "projects": [{"id": p.id, "name": p.name} for p in c.projects],
        })
    name = c.name
    db.delete(c)
    audit(db, "git_credential.delete", "git_credential", cred_id, {"name": name})
    db.commit()
    return {"deleted": cred_id}


@router.post("/{cred_id}/check")
def check_credential(cred_id: int, db: Session = Depends(get_db)):
    """Ask the remote whether this token still works, and record the answer.

    Provider-agnostic on purpose: it runs the same `git ls-remote` through the
    same `_auth_args` that a fetch uses, against the projects assigned to this
    credential. A bespoke GitHub API probe would test a different code path
    from the one that actually fails.

    A credential no project uses cannot be tested — there is no URL to try —
    and the result says so rather than claiming it is fine.
    """
    c = _get(db, cred_id)
    token = decrypt_token(c.token_enc)
    results = []
    for p in sorted(c.projects, key=lambda p: p.name):
        proc = subprocess.run(
            ["git", *gitrepo._auth_args(p.git_url, token), "ls-remote", "--heads", p.git_url],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        err = (proc.stderr or "").strip().splitlines()
        detail = err[-1] if err else ""
        # Never echo the secret back, whatever git chose to print.
        detail = detail.replace(token, "<token>")
        if proc.returncode != 0 and "could not read Username" in detail:
            # git asks for a username when the credential was REFUSED, so the
            # bare message reads like a prompt bug. Say what it means.
            detail = ("the remote refused this token (expired, revoked, or no "
                      "access to this repository)")
        results.append({"project": p.name, "project_id": p.id,
                        "ok": proc.returncode == 0, "detail": detail})

    c.checked_at = utcnow()
    if not results:
        c.check_ok = None
        c.check_detail = "not used by any project yet — assign it to one to test it"
    else:
        c.check_ok = all(r["ok"] for r in results)
        bad = [r for r in results if not r["ok"]]
        c.check_detail = ("ok" if not bad else
                          "; ".join(f"{r['project']}: {r['detail']}" for r in bad))
    db.commit()
    return {**_json(c), "results": results}
