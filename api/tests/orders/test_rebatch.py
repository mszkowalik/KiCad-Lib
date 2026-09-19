"""`rebatch_devices` moves BOTH copies of the batch a device was built in.

The produced event names the batch (decision 0029). Every programming attempt
the bench made for that device carries a copy of the same choice, written at
run creation. A correction that moved only the event left the copies behind:
on 2026-09-18 fifty of the fifty-four filled rows in the dev database still
named a batch that built nothing.

Run from `api/`, with the dev database up:
    python -m pytest tests/orders -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import orders as svc


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


@pytest.fixture
def world(db: Session):
    """One device produced against batch WRONG, with four attempts on it: two
    naming WRONG, one naming a third batch, one naming nothing."""
    proj = M.Project(name="test-rebatch", git_url="https://example.invalid/rb.git")
    db.add(proj)
    db.flush()
    runs = {}
    for label in ("WRONG", "RIGHT", "OTHER"):
        r = M.ProductionRun(project_id=proj.id, label=label, run_date="2026-01-01",
                            status="completed")
        db.add(r)
        db.flush()
        runs[label] = r
    d = M.DeviceUnit(project_id=proj.id, serial="RB0", mac="00:00:00:00:rb:00",
                     first_seen=datetime(2026, 1, 1, 10, tzinfo=UTC))
    db.add(d)
    db.flush()
    svc.record_event(db, d, "produced", production_run_id=runs["WRONG"].id)
    attempts = {}
    for name, rid in (("a1", runs["WRONG"].id), ("a2", runs["WRONG"].id),
                      ("a3", runs["OTHER"].id), ("a4", None)):
        run = M.ProgrammingRun(device_unit_id=d.id, production_run_id=rid, status="pass")
        db.add(run)
        db.flush()
        attempts[name] = run
    return {"project": proj, "runs": runs, "device": d, "attempts": attempts}


def test_rebatch_moves_the_attempts_that_named_the_old_batch(db: Session, world):
    d, runs, att = world["device"], world["runs"], world["attempts"]
    out = svc.rebatch_devices(db, runs["RIGHT"], [d.id], actor="test", dry_run=False)

    assert len(out["moved"]) == 1
    assert out["moved"][0]["attempts"] == 2

    db.refresh(d)
    assert d.production_run_id == runs["RIGHT"].id
    ev = next(e for e in d.events if e.kind == "produced")
    assert ev.production_run_id == runs["RIGHT"].id

    for name in ("a1", "a2"):
        db.refresh(att[name])
        assert att[name].production_run_id == runs["RIGHT"].id, name
    # A different choice, and no choice: neither is this mis-selection.
    db.refresh(att["a3"])
    assert att["a3"].production_run_id == runs["OTHER"].id
    db.refresh(att["a4"])
    assert att["a4"].production_run_id is None


def test_dry_run_counts_the_attempts_and_writes_nothing(db: Session, world):
    d, runs, att = world["device"], world["runs"], world["attempts"]
    out = svc.rebatch_devices(db, runs["RIGHT"], [d.id], actor="test", dry_run=True)

    assert out["moved"][0]["attempts"] == 2
    assert d.production_run_id == runs["WRONG"].id
    assert att["a1"].production_run_id == runs["WRONG"].id


def test_a_batch_reports_the_attempts_on_its_devices(db: Session, world):
    """What `batch_programming` asks: attempts reached through the DEVICE."""
    from app.routers import flasher

    d, runs = world["device"], world["runs"]
    svc.rebatch_devices(db, runs["RIGHT"], [d.id], actor="test", dry_run=False)
    db.flush()

    out = flasher.batch_programming(runs["RIGHT"].id, db=db)
    # All four attempts, including the one naming OTHER and the one naming
    # nothing — they are attempts on a device this batch built.
    assert len(out["runs"]) == 4
    assert out["programmed_ok"] == 1  # one device, however many attempts
    # The batch it was moved off now owns none of them.
    assert flasher.batch_programming(runs["WRONG"].id, db=db)["runs"] == []
