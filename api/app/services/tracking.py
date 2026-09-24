"""Who did it: the request context, and the audit rows built from it.

Decision 0050. Every change made through the API or the UI is traced to the
signed-in person who made it, WITHOUT relying on each endpoint to remember.
There is ONE log, `audit_log`, and `request_id` groups its rows by request.
Three kinds of row land in it:

1. **`action="request"`** — one per write call (POST/PUT/PATCH/DELETE),
   written by `authgate.AuthGate` after the response. It exists even when the
   endpoint writes nothing else, and it records a REFUSED write (403, 409) too.
2. **The call sites' own rows** (`run.document.update`, `comment.add` …) —
   stamped here with `user_id` and `request_id`. An `actor` of `"user"` (the
   placeholder 73 call sites pass) becomes the person's name; a robot label
   (`"jaravis"`, `"review"`) is kept, and `user_id` says who set it going.
3. **`action="row.insert|row.update|row.delete"`** — every ORM row changed
   during a request, captured by flush hooks on EVERY session. No endpoint
   opts in. `entity_type` is the TABLE name, `details` the values.

**The context is a `ContextVar` set by the gate**, not `request.state`, because
the services that write audit rows never see the request. Starlette runs a sync
endpoint through `anyio.to_thread.run_sync`, which copies the context into the
worker thread, so a sync route sees it too. A thread a route starts ITSELF
(`threading.Thread`) does not — its work is attributed by the `request` row
that started it, and nothing else.

**Nothing here may break a write.** A tracking failure is logged and swallowed:
losing one row is bad, refusing the user's invoice because the tracker tripped
is worse.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, insert, inspect
from sqlalchemy.orm import Mapper, Session

from .. import models as M

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestActor:
    request_id: str
    user_id: int | None
    username: str
    # What to write into a who-column: the display name, else the username.
    name: str
    auth_via: str  # session | token | legacy | none


_current: contextvars.ContextVar[RequestActor | None] = contextvars.ContextVar(
    "request_actor", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def bind(actor: RequestActor) -> contextvars.Token:
    return _current.set(actor)


def unbind(token: contextvars.Token) -> None:
    _current.reset(token)


def current() -> RequestActor | None:
    """The person behind the request being served, or None outside a request."""
    return _current.get()


def actor_label(ctx: RequestActor) -> str:
    """What `actor` says on a row this module writes: the person, or what
    authenticated when nobody did."""
    if ctx.name:
        return ctx.name[:100]
    return "legacy token" if ctx.auth_via == "legacy" else PLACEHOLDER


def actor_for(user, request_id: str, auth_via: str) -> RequestActor:
    if user is None:
        return RequestActor(request_id, None, "", "", auth_via)
    username = (getattr(user, "username", "") or "").strip()
    name = (getattr(user, "display_name", "") or "").strip() or username
    return RequestActor(request_id, getattr(user, "id", None), username, name, auth_via)


# ------------------------------------------------------------- who-columns

# Columns that name the person who did something. When one of them carries the
# placeholder "user" — the default ~20 models declare and the value many call
# sites hardcode — it is replaced with the signed-in person's name.
#
# ONLY the placeholder is replaced. A robot label ("import", "jaravis",
# "auto", "seed") is a true statement about who acted and stays; NULL in a
# nullable column means "not yet" (`approved_by`, `revoked_by`) and stays.
WHO_COLUMNS = frozenset({
    "actor", "author", "created_by", "updated_by", "approved_by", "signed_by",
    "revoked_by", "reviewed_by", "requested_by", "done_by", "decided_by",
    "closed_by", "uploaded_by",
})
PLACEHOLDER = "user"


def _fill_who(obj, ctx: RequestActor, inserting: bool) -> None:
    state = inspect(obj)
    for col_attr in state.mapper.column_attrs:
        key = col_attr.key
        if key not in WHO_COLUMNS:
            continue
        if inserting:
            value = state.dict.get(key)
            if value == PLACEHOLDER:
                setattr(obj, key, ctx.name[:100])
            elif value is None:
                # Unset on insert: the column default applies at INSERT time and
                # is invisible here. Fill it only where that default IS the
                # placeholder — a nullable `approved_by` stays NULL.
                default = getattr(col_attr.columns[0].default, "arg", None)
                if default == PLACEHOLDER:
                    setattr(obj, key, ctx.name[:100])
        else:
            # An UPDATE touches the column only when this flush writes the
            # placeholder into it. An old row that already says "user" is
            # history, and editing another field must not rename its author.
            hist = state.attrs[key].history
            if hist.added and hist.added[0] == PLACEHOLDER:
                setattr(obj, key, ctx.name[:100])


def _before_insert(mapper: Mapper, connection, target) -> None:
    """Stamp an audit row with the person and the request. Runs for rows added
    by any path, including one added after `before_flush` had already run."""
    ctx = current()
    if ctx is None or not isinstance(target, M.AuditLog):
        return
    if target.user_id is None:
        target.user_id = ctx.user_id
    if target.request_id is None:
        target.request_id = ctx.request_id
    if (target.actor in (None, "", PLACEHOLDER)) and ctx.name:
        target.actor = ctx.name[:100]


# ------------------------------------------------------------ change capture

# Actions this module writes. Readers that want the HUMAN-scale log (the
# agent's `get_audit_log`, the Changes feed) leave these out.
REQUEST_ACTION = "request"
ROW_ACTION_PREFIX = "row."

# Tables whose rows are never copied as `row.*`. The log itself (a row about a
# row would recurse); the Write log's own tables, which already hold every row
# they describe and are linked by `request_id`; and the tables whose rows ARE
# credentials: a session id is the browser cookie, and a login attempt row
# exists only to count failures.
SKIP_TABLES = frozenset({"audit_log", "write_batches", "write_batch_rows",
                         "user_sessions", "login_attempts"})

REDACTED = "<redacted>"

# Columns that hold a secret wherever they appear.
_SECRET_NAMES = frozenset({"password_hash", "token_hash", "token_enc", "git_token_enc",
                           "secrets_enc", "cookies_enc"})


def _secret_knobs() -> frozenset[str]:
    try:
        from .appconfig import KNOBS
        return frozenset(k.key for k in KNOBS if getattr(k, "secret", False))
    except Exception:  # noqa: BLE001 — tracking never breaks a write
        return frozenset()


def _is_secret(table: str, key: str, obj) -> bool:
    if key in _SECRET_NAMES or key.endswith("_enc") or "password" in key:
        return True
    if table == "device_config_values" and key == "value":
        return bool(getattr(obj, "is_secret", False))
    if table == "app_settings" and key == "value":
        return getattr(obj, "key", None) in _secret_knobs()
    return False


# A value longer than this is stored as its length and digest. The versioned
# tables (symbol source, footprint source, skill text) keep the full text, so
# the row needs to prove WHICH text, not repeat it.
MAX_INLINE = 1000


def _digest(raw: bytes) -> dict:
    return {"len": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _plain(value):
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return _digest(bytes(value))
    if isinstance(value, str):
        return value if len(value) <= MAX_INLINE else _digest(value.encode())
    try:
        text = json.dumps(value, default=str, sort_keys=True)
    except Exception:  # noqa: BLE001 — tracking never breaks a write
        text = str(value)
    if len(text) <= MAX_INLINE:
        return json.loads(text) if text[:1] in "[{" else text
    return _digest(text.encode())


def _value(table: str, key: str, obj, value):
    return REDACTED if _is_secret(table, key, obj) else _plain(value)


def _row_id(mapper: Mapper, obj) -> str:
    try:
        ident = mapper.primary_key_from_instance(obj)
    except Exception:  # noqa: BLE001 — tracking never breaks a write
        return "?"
    return ",".join("" if v is None else str(v) for v in ident)[:100]


def _loaded_columns(state, mapper: Mapper):
    """Column attributes whose value is in memory. Reading an unloaded one would
    fire a SELECT inside the flush — and a deferred blob would come with it."""
    for col_attr in mapper.column_attrs:
        if col_attr.key in state.dict:
            yield col_attr.key, state.dict[col_attr.key]


def _collect(session: Session) -> list[dict]:
    rows: list[dict] = []
    for op, objs in (("insert", session.new), ("update", session.dirty), ("delete", session.deleted)):
        for obj in objs:
            state = inspect(obj)
            mapper = state.mapper
            table = getattr(mapper.local_table, "name", None) or ""
            if not table or table in SKIP_TABLES:
                continue
            if op == "update":
                changes = {}
                for col_attr in mapper.column_attrs:
                    hist = state.attrs[col_attr.key].history
                    if not hist.has_changes():
                        continue
                    old = hist.deleted[0] if hist.deleted else None
                    new = hist.added[0] if hist.added else None
                    changes[col_attr.key] = [_value(table, col_attr.key, obj, old),
                                             _value(table, col_attr.key, obj, new)]
                if not changes:
                    continue  # dirty by a relationship only; no column moved
            else:
                changes = {k: _value(table, k, obj, v) for k, v in _loaded_columns(state, mapper)}
            rows.append({"op": op, "table": table, "mapper": mapper, "obj": obj, "changes": changes})
    return rows


def _before_flush(session: Session, flush_context, instances) -> None:
    # History is read BEFORE the flush: after it, an updated attribute's old
    # value is gone. Row ids of new rows are filled in after the flush.
    ctx = current()
    if ctx is None:
        return
    # Who-columns first, so the `row.*` entry records the name that is stored.
    if ctx.name:
        for inserting, objs in ((True, list(session.new)), (False, list(session.dirty))):
            for obj in objs:
                try:
                    _fill_who(obj, ctx, inserting)
                except Exception:
                    log.exception("tracking: filling who-columns failed on %s", type(obj).__name__)
    try:
        pending = session.info.setdefault("_tracking_pending", [])
        pending.extend(_collect(session))
    except Exception:
        log.exception("tracking: change capture failed before flush")


def _after_flush(session: Session, flush_context) -> None:
    ctx = current()
    pending = session.info.pop("_tracking_pending", None)
    if ctx is None or not pending:
        return
    try:
        now = M.utcnow()
        values = [{
            "ts": now,
            "actor": actor_label(ctx),
            "action": ROW_ACTION_PREFIX + p["op"],
            "entity_type": p["table"][:50],
            "entity_id": _row_id(p["mapper"], p["obj"]),
            "details": p["changes"],
            "user_id": ctx.user_id,
            "request_id": ctx.request_id,
        } for p in pending]
        # Core insert on the flush's own connection: same transaction, so a
        # rollback takes these rows with it, and no second flush is needed. It
        # also bypasses the ORM, so it cannot re-enter these hooks.
        session.connection().execute(insert(M.AuditLog), values)
    except Exception:
        log.exception("tracking: writing row entries failed")


def _after_rollback(session: Session) -> None:
    session.info.pop("_tracking_pending", None)


_installed = False


def install() -> None:
    """Register the hooks once, on every mapped class and every session."""
    global _installed
    if _installed:
        return
    event.listen(M.AuditLog, "before_insert", _before_insert)
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_soft_rollback", lambda s, prev: _after_rollback(s))
    _installed = True


# ------------------------------------------------------------- request log

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def scrub_query(raw: str) -> str:
    """The query string without `t=`: a token must never be stored."""
    if not raw:
        return ""
    return "&".join(p for p in raw.split("&") if p and not p.startswith("t="))[:1000]


def write_request_row(ctx: RequestActor, method: str, path: str, query: str,
                      status: int | None, duration_ms: int, ip: str, user_agent: str) -> None:
    """The `request` row. Runs in a worker thread after the response, in its
    own session, with the context already unbound — so every field is set here
    rather than left to the insert hook. The body is never stored: it can
    carry passwords, tokens and whole files."""
    from ..db import SessionLocal

    db = SessionLocal()
    try:
        db.add(M.AuditLog(
            actor=actor_label(ctx), action=REQUEST_ACTION, entity_type="http",
            entity_id=path[:100], user_id=ctx.user_id, request_id=ctx.request_id,
            details={"method": method, "path": path[:500], "query": query[:1000],
                     "status": status, "duration_ms": duration_ms, "ip": ip[:60],
                     "user_agent": user_agent[:300], "auth_via": ctx.auth_via,
                     "username": ctx.username},
        ))
        db.commit()
    except Exception:
        log.exception("tracking: writing the request row failed")
        db.rollback()
    finally:
        db.close()
