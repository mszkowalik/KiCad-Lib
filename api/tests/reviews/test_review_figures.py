"""The review figures: each count has one definition, and the list it opens
holds the same rows.

An audit of production on 2026-11-07 found the same question answered with
different numbers on different screens:

- the project Review tab and the batch warning counted `unreviewed` and
  `failed` as "not verified" and left `partial` out (EVSE_20_CTRL: 41 against
  57 parts that were not checked);
- the review queue and the health panel counted components with no published
  version as review work (508 against the library's 503);
- the health panel's "failing" count added stored record answers that the
  list it opens did not show (`cmp.required_props` 13 against 10);
- the retired-skip chip summed the top 10 keys only.

The routes are called as plain functions on one transaction that is rolled
back, so nothing reaches the dev data.

Run from `api/`, with the dev database up:
    python -m pytest tests/reviews -q
"""
import pathlib
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import reviews


@pytest.fixture
def db():
    """One transaction, never committed: the dev database is left untouched."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _row(name, review, signoff="signed", lifecycle="released"):
    return {"board": "B", "refs": name, "qty": 1, "value": "", "footprint": "", "lcsc": "",
            "mpn": "", "lib_version": "", "component_id": hash(name) % 100000,
            "component_name": name, "current_version_no": 1, "review_state": review,
            "review_blockers": [], "signoff_state": signoff, "lifecycle": lifecycle,
            "matched": True}


# ------------------------------------------------------------ finding 1
def test_a_partial_part_is_not_verified(db, monkeypatch):
    """Every state except `checked` is open work, the way the queue counts it."""
    rows = [_row("A", "checked"), _row("B", "partial"), _row("C", "failed"),
            _row("D", "unreviewed"), _row("E", "partial")]
    monkeypatch.setattr(reviews, "snapshot_review_rows", lambda db, snap: rows)

    out = reviews.snapshot_review_issues(db, SimpleNamespace(id=-1))

    assert out["not_verified"] == ["B", "C", "D", "E"]
    assert out["partial"] == ["B", "E"]
    assert out["clean"] is False


def test_only_partial_parts_still_make_the_snapshot_unclean(db, monkeypatch):
    rows = [_row("A", "checked"), _row("B", "partial")]
    monkeypatch.setattr(reviews, "snapshot_review_rows", lambda db, snap: rows)

    out = reviews.snapshot_review_issues(db, SimpleNamespace(id=-1))

    assert out["clean"] is False, "a part with open items read as verified"
