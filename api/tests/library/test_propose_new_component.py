"""propose_new_component never leaves a shell, and can finish one.

The tool archives the datasheet BEFORE it publishes, and the archive commits.
A refusal raised inside the publish therefore came after the commit: on
2026-10-02 a 642-character comment left RT0402BRD0712K4L as a component with
only a draft v1, its name taken, and no write tool able to reach it. The tool
now refuses early, and publishes onto a component that has no published
version instead of refusing the name.

The tool opens its own session and commits. These tests hand it a session on
a connection whose outer transaction is rolled back, so every commit is a
savepoint and nothing reaches the dev database. The mirror refresh is stubbed
for the same reason, and the archive is stubbed with a bare commit so no test
needs the network.

Run from `api/`, with the dev database up:
    python -m pytest tests/library -q
"""
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import agent_tools, publish
from app.services.publish import CHANGE_COMMENT_LIMIT

URL = "https://example.invalid/datasheet.pdf"
PROPS = json.dumps([
    {"key": "Value", "value": "1K"},
    {"key": "Footprint", "value": "7Sigma:R_0402_1005Metric"},
])


@pytest.fixture
def session(monkeypatch):
    """A session factory whose commits all roll back at the end of the test."""
    conn = engine.connect()
    trans = conn.begin()

    def factory():
        return Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

    def archive_commits(db, ds):
        db.commit()
        return {"archived": False, "reason": "test stand-in"}

    monkeypatch.setattr(agent_tools, "SessionLocal", factory)
    monkeypatch.setattr(agent_tools, "_archive_datasheet", archive_commits)
    monkeypatch.setattr(publish, "refresh_mirror_for_component", lambda *a, **k: {"warnings": []})
    try:
        db = factory()
        if db.query(M.Symbol).filter_by(name="R").first() is None or \
                db.query(M.Footprint).filter_by(name="R_0402_1005Metric").first() is None or \
                db.query(M.Category).filter_by(name="Resistor").first() is None:
            pytest.skip("dev database lacks the R symbol, the 0402 land or the Resistor category")
        db.close()
        yield factory
    finally:
        trans.rollback()
        conn.close()


def create(name, comment="test", datasheet_url=URL):
    return json.loads(agent_tools.propose_new_component.func(
        name=name, category="Resistor", base_component="R", properties_json=PROPS,
        datasheet_url=datasheet_url, comment=comment,
    ))


def test_an_over_long_comment_is_refused_before_any_row_exists(session):
    name = f"TEST-{uuid.uuid4().hex[:8]}"
    out = create(name, comment="x" * (CHANGE_COMMENT_LIMIT + 1))

    assert "error" in out
    assert str(CHANGE_COMMENT_LIMIT) in out["error"]
    assert session().query(M.Component).filter_by(name=name).first() is None


def test_a_shell_is_published_as_its_next_version(session):
    """What the 2026-10-02 failure left: a component, a draft v1, a datasheet row."""
    name = f"TEST-{uuid.uuid4().hex[:8]}"
    db = session()
    cat = db.query(M.Category).filter_by(name="Resistor").first()
    sym = db.query(M.Symbol).filter_by(name="R").first()
    comp = M.Component(name=name)
    db.add(comp)
    db.flush()
    db.add(M.ComponentVersion(component_id=comp.id, version_no=1, base_component="R",
                              symbol_version_id=sym.current_version_id, category_id=cat.id,
                              status="draft", created_by="jaravis"))
    db.add(M.Datasheet(component_id=comp.id, position=0, label="Datasheet", source_url=URL))
    db.commit()
    comp_id = comp.id
    db.close()

    out = create(name)

    assert out.get("ok") is True, out
    assert out["version_no"] == 2
    assert "note" in out
    db = session()
    comp = db.get(M.Component, comp_id)
    by_no = {v.version_no: v for v in comp.versions}
    assert comp.current_version_id == by_no[2].id
    assert by_no[1].status == "draft"  # history, untouched
    active = [d for d in db.query(M.Datasheet).filter_by(component_id=comp_id) if d.position is not None]
    assert [d.source_url for d in active] == [URL]  # reused, not duplicated


def test_a_published_component_is_still_refused(session):
    db = session()
    live = db.query(M.Component).filter(M.Component.current_version_id.isnot(None)).first()
    if live is None:
        pytest.skip("dev database has no published component")
    out = create(live.name)

    assert "already exists" in out.get("error", "")
