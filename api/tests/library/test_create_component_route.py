"""POST /api/components publishes v1 in one transaction, or writes nothing.

Found 2026-10-02: `create_component` still called `create_version(comp.id,
body, db)` after `create_version` gained a `request` parameter, so every create
from the New Component page failed with a 500. It had also committed the
component row first, so each failure would have left a component with no
version whose name blocked the next attempt.

The routes are called as plain functions on a session whose commits are
savepoints inside a rolled-back transaction, so nothing reaches the dev data.
The mirror WRITE is stubbed for the same reason, one level below
`refresh_mirror_for_component`, because that function's `db.expire_all()` is
part of what the route relies on.

Run from `api/`, with the dev database up:
    python -m pytest tests/library -q
"""
import pathlib
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import components
from app.services import publish
from app.services.publish import CHANGE_COMMENT_LIMIT

REQUEST = SimpleNamespace(state=SimpleNamespace(user=None))  # what dev (auth off) carries


@pytest.fixture
def db(monkeypatch):
    conn = engine.connect()
    trans = conn.begin()
    monkeypatch.setattr(publish, "update_mirror_symbols", lambda *a, **k: {"warnings": []})
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        if s.query(M.Symbol).filter_by(name="R").first() is None or \
                s.query(M.Category).filter_by(name="Resistor").first() is None:
            pytest.skip("dev database lacks the R symbol or the Resistor category")
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def body(db, name, comment="test", in_library=True):
    return components.ComponentCreate(
        name=name, base_component="R" if in_library else "", in_library=in_library,
        category_id=db.query(M.Category).filter_by(name="Resistor").first().id,
        properties=[components.PropertyIn(key="Value", value="1K")],
        comment=comment,
    )


def test_a_new_component_is_published_as_v1(db):
    name = f"TEST-{uuid.uuid4().hex[:8]}"
    out = components.create_component(body(db, name), REQUEST, db)

    assert out["component_name"] == name
    comp = db.query(M.Component).filter_by(name=name).one()
    live = next(v for v in comp.versions if v.id == comp.current_version_id)
    assert (live.version_no, live.status) == (1, "published")


def test_a_bom_only_component_is_published_as_v1(db):
    """in_library=False skips the mirror refresh, and with it the expire_all."""
    name = f"TEST-{uuid.uuid4().hex[:8]}"
    out = components.create_component(body(db, name, in_library=False), REQUEST, db)

    assert out["component_name"] == name
    assert db.query(M.Component).filter_by(name=name).one().current_version_id is not None


def test_a_bom_only_edit_is_published_as_v2(db):
    name = f"TEST-{uuid.uuid4().hex[:8]}"
    comp_id = components.create_component(body(db, name, in_library=False), REQUEST, db)["component_id"]
    out = components.create_version(comp_id, body(db, name, in_library=False), REQUEST, db)

    assert out["version_no"] == 2


def test_a_refused_create_answers_422_and_leaves_no_shell(db):
    name = f"TEST-{uuid.uuid4().hex[:8]}"
    with pytest.raises(HTTPException) as exc:
        components.create_component(body(db, name, comment="x" * (CHANGE_COMMENT_LIMIT + 1)), REQUEST, db)

    assert exc.value.status_code == 422
    db.rollback()  # what get_db's close does to an uncommitted request
    assert db.query(M.Component).filter_by(name=name).first() is None
