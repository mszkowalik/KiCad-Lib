"""A per-session memo for reads that are expensive and repeated within one
request: the exchange-rate history and the invoice register.

Measured on production 2026-10-12: `fx.rates_at` read all 2,270 rate history
rows on each of its 45-126 calls per request, and the batch Process tab built
the company-wide invoice register twice. Both read data that does not change
while the request only reads.

The memo lives in `session.info` and is dropped whenever the session may have
changed what it read: before a flush that writes, when any transaction or
savepoint ends (a rolled-back dry run must not leave its view behind), and
after any statement that is not a SELECT. A caller must treat a memoised value
as read-only. A write through `db.connection().execute(...)` passes none of
these events: write through the session.
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause

KEY = "_session_memo"


def get(db: Session, key, build):
    """`build()` once per session state, then the same object."""
    memo = db.info.setdefault(KEY, {})
    if key not in memo:
        memo[key] = build()
    return memo[key]


def clear(db: Session) -> None:
    db.info.pop(KEY, None)


def _before_flush(session: Session, flush_context, instances) -> None:
    if session.new or session.dirty or session.deleted:
        clear(session)


def _after_transaction_end(session: Session, transaction) -> None:
    clear(session)


def _do_orm_execute(state) -> None:
    if state.is_select:
        return
    st = state.statement
    if isinstance(st, TextClause) and str(st).lstrip()[:6].lower() == "select":
        return
    clear(state.session)


_installed = False


def install() -> None:
    global _installed
    if not _installed:
        event.listen(Session, "before_flush", _before_flush)
        event.listen(Session, "after_transaction_end", _after_transaction_end)
        event.listen(Session, "do_orm_execute", _do_orm_execute)
        _installed = True


install()
