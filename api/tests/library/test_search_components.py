"""The `search_components` agent tool says how many components match.

Found 2026-11-07: an empty query answered `count: 50` while 503 components
matched, with nothing in the payload to say the list was cut. `_capped` in the
same module exists for exactly this ("never silently"), and this tool did not
use its rule.

Run from `api/`, with the dev database up:
    python -m pytest tests/library -q
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import agent_tools


@pytest.fixture
def db(monkeypatch):
    conn = engine.connect()
    trans = conn.begin()

    def make():
        return Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

    monkeypatch.setattr(agent_tools, "SessionLocal", make)
    s = make()
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def test_an_empty_query_counts_the_whole_library(db):
    published = db.query(M.Component).filter(M.Component.current_version_id.isnot(None)).count()
    if published <= agent_tools.SEARCH_CAP:
        pytest.skip("the dev library is too small to reach the cap")

    out = json.loads(agent_tools.search_components.func(query="", category=""))

    assert out["count"] == published, "count stopped at the cap"
    rows = [r for r in out["components"] if not r.get("_truncated")]
    assert len(rows) == agent_tools.SEARCH_CAP
    note = out["components"][-1]
    assert note.get("_truncated") is True and note["total"] == published


def test_a_narrow_query_is_not_marked_truncated(db):
    out = json.loads(agent_tools.search_components.func(query="zzzz-nothing-matches", category=""))

    assert out == {"count": 0, "components": []}
