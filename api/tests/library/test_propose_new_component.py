"""A refused propose_new_component leaves nothing behind.

The tool archives the datasheet BEFORE it publishes, and the archive commits.
A refusal raised inside the publish therefore came after the commit: on
2026-10-02 a 642-character comment left RT0402BRD0712K4L as a component with
only a draft v1, its name taken, and no write tool able to reach it.

The tool opens its own session and commits, so these tests cannot roll back.
They pass by writing nothing; the cleanup only runs if the bug comes back.

Run from `api/`, with the dev database up:
    python -m pytest tests/library -q
"""
import json
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest

from app import models as M
from app.db import SessionLocal
from app.services import jaravis
from app.services.publish import CHANGE_COMMENT_LIMIT

PROPS = json.dumps([
    {"key": "Value", "value": "1K"},
    {"key": "Footprint", "value": "7Sigma:R_0402_1005Metric"},
])


@pytest.fixture
def name():
    """A unique name, and the clean-up of whatever a regression leaves under it."""
    n = f"TEST-ORPHAN-{uuid.uuid4().hex[:8]}"
    yield n
    db = SessionLocal()
    try:
        comp = db.query(M.Component).filter_by(name=n).first()
        if comp is not None:
            for cv in db.query(M.ComponentVersion).filter_by(component_id=comp.id):
                db.query(M.ComponentProperty).filter_by(component_version_id=cv.id).delete()
                db.delete(cv)
            db.query(M.Datasheet).filter_by(component_id=comp.id).delete()
            db.delete(comp)
            db.commit()
    finally:
        db.close()


@pytest.fixture
def archive_commits(monkeypatch):
    """Stand in for the real archive: no network, but the same commit."""
    def fake(db, ds):
        db.commit()
        return {"archived": False, "reason": "test stand-in"}
    monkeypatch.setattr(jaravis, "_archive_datasheet", fake)


@pytest.fixture
def library_ready():
    """The path only reaches the archive when the rest of the input is valid."""
    db = SessionLocal()
    try:
        if db.query(M.Symbol).filter_by(name="R").first() is None or \
                db.query(M.Footprint).filter_by(name="R_0402_1005Metric").first() is None or \
                db.query(M.Category).filter_by(name="Resistor").first() is None:
            pytest.skip("dev database lacks the R symbol, the 0402 land or the Resistor category")
    finally:
        db.close()


def test_an_over_long_comment_is_refused_before_any_row_exists(name, archive_commits, library_ready):
    out = json.loads(jaravis.propose_new_component.func(
        name=name, category="Resistor", base_component="R", properties_json=PROPS,
        datasheet_url="https://example.invalid/datasheet.pdf",
        comment="x" * (CHANGE_COMMENT_LIMIT + 1),
    ))

    assert "error" in out
    assert str(CHANGE_COMMENT_LIMIT) in out["error"]
    db = SessionLocal()
    try:
        assert db.query(M.Component).filter_by(name=name).first() is None
    finally:
        db.close()
