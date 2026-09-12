"""Fold the per-project git tokens into named `GitCredential` rows.

One-shot and idempotent, run at startup after `create_all`. It only ever looks
at a project that has a token AND no credential, so a second boot is a no-op
and a project whose token was typed in deliberately after the migration is left
alone.

**Grouping is by the DECRYPTED value, which is why this is Python and not SQL.**
Fernet is randomised: encrypting one token twice gives two different
ciphertexts, so `GROUP BY git_token_enc` would make one credential per project
and preserve exactly the duplication the change exists to end. Production held
four projects, three encrypted copies of one live token and one of a revoked
token — two credentials, not four.

Names are provisional on purpose: the host the projects point at, numbered when
one host has several accounts (`github.com`, `github.com (2)`). Nothing offline
can tell which login a token belongs to, so the platform does not guess one —
the Check action fills `username` in from the provider, and the operator
renames the row to something they recognise.
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from .. import models as M
from .crypto import decrypt_token

log = logging.getLogger("uvicorn.error")

RESULT: dict = {"ran": False}


def _host_of(git_url: str) -> str:
    try:
        return (urlparse(git_url).hostname or "").lower()
    except ValueError:
        return ""


def migrate(db: Session) -> dict:
    """Returns {"credentials": n, "projects": n, "undecryptable": n}."""
    pending = (
        db.query(M.Project)
        .filter(M.Project.git_token_enc.isnot(None))
        .filter(M.Project.git_credential_id.is_(None))
        .order_by(M.Project.id)
        .all()
    )
    pending = [p for p in pending if (p.git_token_enc or "").strip()]
    out = {"credentials": 0, "projects": 0, "undecryptable": 0}
    if not pending:
        RESULT.update(out, ran=True)
        return out

    # cleartext -> the credential it belongs to
    by_secret: dict[str, M.GitCredential] = {}
    used_names = {n for (n,) in db.query(M.GitCredential.name).all()}

    for p in pending:
        try:
            secret = decrypt_token(p.git_token_enc)
        except ValueError:
            # SECRET_KEY changed since this was stored: the token is lost
            # either way, but destroying the row would hide that from the
            # operator. Leave it exactly as it is and report the count.
            out["undecryptable"] += 1
            continue

        cred = by_secret.get(secret)
        if cred is None:
            host = _host_of(p.git_url) or "git"
            name = host
            n = 1
            while name in used_names:
                n += 1
                name = f"{host} ({n})"
            used_names.add(name)
            cred = M.GitCredential(
                name=name,
                host=host,
                # Reuse the ciphertext rather than re-encrypting: same key,
                # same plaintext, and it keeps the migration a pure move.
                token_enc=p.git_token_enc,
                description="Imported from the per-project token. Rename it "
                            "after the account it belongs to.",
                created_by="migration",
            )
            db.add(cred)
            db.flush()
            by_secret[secret] = cred
            out["credentials"] += 1

        p.git_credential_id = cred.id
        # Clear the project copy. Leaving it would recreate the very thing
        # this migration removes: two places a token can differ.
        p.git_token_enc = None
        out["projects"] += 1

    db.commit()
    RESULT.update(out, ran=True)
    log.info(
        "git credentials: folded %d project token(s) into %d credential(s)%s",
        out["projects"], out["credentials"],
        f", {out['undecryptable']} undecryptable and left in place" if out["undecryptable"] else "",
    )
    return out
