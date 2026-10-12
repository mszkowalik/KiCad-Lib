"""The per-session memo (`services/session_memo.py`) never serves a stale read.

What these pin down:

- `fx.rates_at` sees a rate written in the same session at once;
- a savepoint that is rolled back leaves no memoised view behind;
- the invoice register is built once per session state, and again after a
  write;
- a raw UPDATE drops the memo, a raw SELECT does not.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_session_memo.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import fx, run_actuals, session_memo

AT = datetime(2031, 1, 1, tzinfo=UTC)   # after any real history row


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def test_a_rate_written_in_the_session_is_seen_at_once(db):
    fx.rates_at(db, AT)                                   # fills the memo
    db.add(M.ExchangeRateHistory(currency="XTS", rate_usd=0.5, recorded_at=datetime(2030, 6, 1, tzinfo=UTC)))
    db.flush()
    assert fx.rates_at(db, AT)["XTS"] == 0.5


def test_a_rolled_back_savepoint_leaves_no_view_behind(db):
    with pytest.raises(RuntimeError):
        with db.begin_nested():
            db.add(M.ExchangeRateHistory(currency="XTS", rate_usd=0.25,
                                         recorded_at=datetime(2030, 6, 1, tzinfo=UTC)))
            db.flush()
            assert fx.rates_at(db, AT)["XTS"] == 0.25    # memoised inside the trial
            raise RuntimeError("roll the trial back")
    assert "XTS" not in fx.rates_at(db, AT)


def test_the_register_is_built_once_per_state(db, monkeypatch):
    built = []
    real = run_actuals._invoice_register
    monkeypatch.setattr(run_actuals, "_invoice_register", lambda *a: built.append(1) or real(*a))
    first = run_actuals.invoice_register(db, accountant=False)
    assert run_actuals.invoice_register(db, accountant=False) is first
    assert len(built) == 1
    db.add(M.Comment(target_type="component", target_id=1, author="t", body="a write"))
    db.flush()
    run_actuals.invoice_register(db, accountant=False)
    assert len(built) == 2


def test_a_raw_update_drops_the_memo_and_a_raw_select_keeps_it(db):
    session_memo.get(db, "probe", lambda: "kept")
    db.execute(text("SELECT 1"))
    assert db.info[session_memo.KEY] == {"probe": "kept"}
    db.execute(text("UPDATE comments SET body = body WHERE id = -1"))
    assert session_memo.KEY not in db.info
