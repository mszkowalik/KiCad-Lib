"""Check a sign-in password against the home LDAP directory (decision 0114).

The directory is lldap on the server (`docker-compose.auth.yml` in the
deployment repository). Henry stays the owner of its accounts: an admin makes
the account, gives the role and links it to ONE directory uid
(`users.ldap_uid`). This module answers one question — "is this the right
password for that uid, and is the uid in the Henry group" — and nothing else.
It never makes or changes an account, a role or a company membership.

Two binds, the usual pattern:

1. Bind as the read-only service account and search
   `(&(uid=<uid>)<ldap_user_filter>)` under `ldap_user_base`. The filter holds
   the group condition, so a uid outside the group is not found.
2. Bind as the DN found, with the password typed. Success is the answer.

An empty password is refused before any network call: an LDAP simple bind with
a DN and NO password is an "unauthenticated bind", which many servers accept
as success (RFC 4513 §5.1.2). That is the classic way an LDAP login lets
anybody in.

`ldap3` is imported inside the call, so a dev container without it starts and
only an LDAP sign-in fails.
"""
from __future__ import annotations

import logging

from ..config import settings

log = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.ldap_url and settings.ldap_bind_dn and settings.ldap_user_base)


def _bind_password() -> str:
    if settings.ldap_bind_password_file:
        try:
            with open(settings.ldap_bind_password_file, encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError as exc:
            log.error("ldap: cannot read the bind password file: %s", exc)
            return ""
    return settings.ldap_bind_password


def check(uid: str, password: str) -> bool:
    """True when `password` is the directory password of `uid` and the uid
    passes `ldap_user_filter`. Any error is a False, and is logged."""
    if not enabled() or not uid or not password:
        return False
    try:
        from ldap3 import NONE, Connection, Server
        from ldap3.utils.conv import escape_filter_chars
    except ImportError:
        log.error("ldap: the ldap3 package is not installed")
        return False

    # ldap3 takes a float connect timeout, but `receive_timeout` must be an int:
    # a float raises "required argument is not an integer" on the first bind
    # (measured against lldap, 2026-11-24).
    timeout = max(1, round(settings.ldap_timeout_s))
    server = Server(settings.ldap_url, get_info=NONE, connect_timeout=timeout)
    flt = f"(&(uid={escape_filter_chars(uid)}){settings.ldap_user_filter})"
    # Explicit bind() and unbind(), never `with Connection(...)`: the context
    # manager binds on entry and RAISES LDAPBindError for a wrong password,
    # which would log every mistyped password as an error.
    svc = person = None
    try:
        svc = Connection(server, user=settings.ldap_bind_dn, password=_bind_password(),
                         receive_timeout=timeout, raise_exceptions=False)
        if not svc.bind():
            log.error("ldap: the service bind failed: %s", svc.result.get("description"))
            return False
        svc.search(settings.ldap_user_base, flt, attributes=[], size_limit=2)
        entries = list(svc.entries)
        if len(entries) != 1:
            # 0: unknown uid or not in the group. 2: a filter that matches too
            # much — refuse rather than guess which person this is.
            return False
        person = Connection(server, user=entries[0].entry_dn, password=password,
                            receive_timeout=timeout, raise_exceptions=False)
        return bool(person.bind())
    except Exception as exc:  # noqa: BLE001 — a directory fault must not 500 the login
        log.error("ldap: %s: %s", type(exc).__name__, exc)
        return False
    finally:
        for conn in (person, svc):
            if conn is not None:
                try:
                    conn.unbind()
                except Exception:  # noqa: BLE001, S110 — closing a dead socket
                    pass
