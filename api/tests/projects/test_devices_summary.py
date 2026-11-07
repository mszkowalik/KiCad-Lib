"""Project → Devices: the presence chips count the devices the list draws.

Found 2026-11-07 on production: CE_Aqua_V2 with `?state=in_stock` listed 27
devices, while the toolbar said "1,015 device(s)" and the chips said online
377, offline 295, never seen 343. A click on "online 377" showed 0 rows. The
summary was counted over the whole project with the batch as its only
narrowing, so `state` and `condition` reached the list and not its chips.

Run from `api/`, with the dev database up:
    python -m pytest tests/projects -q
"""
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import projects as router


@pytest.fixture
def db():
    """One transaction, never committed: the dev database is left untouched."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _devices(db, project_id, rows):
    for state, condition, online in rows:
        tag = uuid.uuid4().hex[:10]
        d = M.DeviceUnit(project_id=project_id, tasmota_id=f"test_{tag}", serial=tag,
                         state=state, condition=condition)
        db.add(d)
        db.flush()
        if online is not None:
            db.add(M.DevicePresence(topic=f"test_{tag}", device_unit_id=d.id, online=online))
    db.flush()


def _call(db, project_id, **kw):
    args = dict(state="", condition="", run_id=None, presence="", q="", limit=500)
    args.update(kw)
    return router.project_devices(project_id=project_id, db=db, **args)


@pytest.fixture
def project(db):
    p = M.Project(name=f"test-devices-{uuid.uuid4().hex[:6]}", git_url="https://example.invalid/d.git")
    db.add(p)
    db.flush()
    _devices(db, p.id, [
        ("in_stock", "ok", None),
        ("in_stock", "ok", False),
        ("in_stock", "faulty", None),
        ("shipped", "ok", True),
        ("shipped", "ok", True),
        ("shipped", "ok", False),
    ])
    return p


def test_the_chips_count_the_state_the_list_shows(db, project):
    out = _call(db, project.id, state="in_stock")

    assert len(out["items"]) == 3
    assert out["summary"] == {"total": 3, "online": 0, "offline": 1, "unknown": 2}, \
        "the chips counted the whole project while the list showed the shelf"


def test_the_chips_count_the_condition_the_list_shows(db, project):
    out = _call(db, project.id, state="in_stock", condition="faulty")

    assert len(out["items"]) == 1
    assert out["summary"]["total"] == 1


def test_a_presence_chip_does_not_narrow_its_own_counts(db, project):
    """The chips ARE the presence split; narrowing them by it would zero two."""
    out = _call(db, project.id, presence="online")

    assert len(out["items"]) == 2
    assert out["summary"] == {"total": 6, "online": 2, "offline": 2, "unknown": 2}
