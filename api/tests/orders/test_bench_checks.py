"""What the bench says before it programs the board in front of it.

Decision record: docs/decisions/0037-the-bench-says-what-it-already-knows.md.

Run from `api/`, with the dev database up:
    python -m pytest tests/orders -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import orders as svc
from app.services.flasher import bench_checks


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
    """One project, a batch that has already built ten units, and an empty one."""
    proj = M.Project(name="test-bench-checks", git_url="https://example.invalid/bc.git")
    other = M.Project(name="test-bench-checks-other", git_url="https://example.invalid/bc2.git")
    db.add_all([proj, other])
    db.flush()
    built = M.ProductionRun(project_id=proj.id, label="Built", run_date="2026-09-01",
                            status="completed", plan_qty=100)
    empty = M.ProductionRun(project_id=proj.id, label="Empty", run_date="2026-09-10",
                            status="planned", plan_qty=800)
    db.add_all([built, empty])
    db.flush()
    devs = []
    for i in range(10):
        d = M.DeviceUnit(project_id=proj.id, serial=f"BC{i}", mac=f"00:00:00:00:bc:0{i}",
                         first_seen=datetime(2026, 9, 1, 10, i, tzinfo=UTC))
        db.add(d)
        db.flush()
        svc.record_event(db, d, "produced", at=datetime(2026, 9, 1, 10, i, tzinfo=UTC),
                         production_run_id=built.id)
        devs.append(d)
    db.flush()
    return {"project": proj, "other": other, "built": built, "empty": empty, "devices": devs}


def _run(db: Session, batch: M.ProductionRun | None) -> M.ProgrammingRun:
    r = M.ProgrammingRun(production_run_id=batch.id if batch else None, status="running")
    db.add(r)
    db.flush()
    return r


def _codes(out):
    return [n["code"] for n in out]


def test_a_new_board_in_a_running_batch_says_nothing(db: Session, world):
    """The ordinary case must be silent, or every notice gets clicked through."""
    d = M.DeviceUnit(project_id=world["project"].id, serial="BCNEW", mac="00:00:00:00:bc:ff")
    db.add(d)
    db.flush()
    out = bench_checks.for_device(db, _run(db, world["built"]), d,
                                  created=True, project_id=world["project"].id)
    assert _codes(out) == []


def test_another_projects_device_blocks_and_stops_there(db: Session, world):
    d = M.DeviceUnit(project_id=world["other"].id, serial="XX0", mac="00:00:00:00:xx:00")
    db.add(d)
    db.flush()
    out = bench_checks.for_device(db, _run(db, world["built"]), d,
                                  created=False, project_id=world["project"].id)
    # Nothing else is reported: once it is the wrong device, the rest is noise.
    assert _codes(out) == ["wrong_project"]
    assert out[0]["level"] == "block"


def test_the_first_unit_of_a_batch_is_flagged(db: Session, world):
    """2026-09-17: the bench had a batch selected whose boards had not arrived,
    and 31 units were filed against it. This fires on unit one."""
    d = M.DeviceUnit(project_id=world["project"].id, serial="BCNEW", mac="00:00:00:00:bc:fe")
    db.add(d)
    db.flush()
    out = bench_checks.for_device(db, _run(db, world["empty"]), d,
                                  created=True, project_id=world["project"].id)
    assert _codes(out) == ["first_unit_of_batch"]
    assert out[0]["level"] == "warn"


def test_a_reflash_of_an_older_batchs_unit_is_a_notice_not_a_block(db: Session, world):
    d = world["devices"][0]
    out = bench_checks.for_device(db, _run(db, world["empty"]), d,
                                  created=False, project_id=world["project"].id)
    assert "built_in_another_batch" in _codes(out)
    assert all(n["level"] == "warn" for n in out)


def test_a_unit_at_a_customer_warns_and_never_blocks(db: Session, world):
    d = world["devices"][1]
    d.state = "shipped"
    db.flush()
    out = bench_checks.for_device(db, _run(db, world["built"]), d,
                                  created=False, project_id=world["project"].id)
    assert "not_in_stock" in _codes(out)
    assert all(n["level"] == "warn" for n in out)


def test_a_faulty_unit_is_flagged(db: Session, world):
    d = world["devices"][2]
    d.condition = "faulty"
    db.flush()
    out = bench_checks.for_device(db, _run(db, world["built"]), d,
                                  created=False, project_id=world["project"].id)
    assert "condition_not_ok" in _codes(out)


def test_a_full_batch_is_flagged_for_a_new_unit(db: Session, world):
    """Ten built against ten planned; the eleventh asks."""
    world["built"].plan_qty = 10
    d = M.DeviceUnit(project_id=world["project"].id, serial="BC11", mac="00:00:00:00:bc:11")
    db.add(d)
    db.flush()
    out = bench_checks.for_device(db, _run(db, world["built"]), d,
                                  created=True, project_id=world["project"].id)
    assert "batch_full" in _codes(out)


def test_a_settled_batch_warns_that_its_cost_will_be_re_divided(db: Session, world):
    old = world["built"]
    for e in db.query(M.DeviceEvent).filter_by(kind="produced", production_run_id=old.id):
        e.at = datetime.now(UTC) - timedelta(days=200)
    db.flush()
    d = M.DeviceUnit(project_id=world["project"].id, serial="BCLATE", mac="00:00:00:00:bc:la")
    db.add(d)
    db.flush()
    out = bench_checks.for_device(db, _run(db, old), d,
                                  created=True, project_id=world["project"].id)
    assert "settled_batch" in _codes(out)


def test_a_bench_trial_with_no_batch_reports_only_device_facts(db: Session, world):
    d = world["devices"][3]
    d.state = "shipped"
    db.flush()
    out = bench_checks.for_device(db, _run(db, None), d,
                                  created=False, project_id=world["project"].id)
    assert _codes(out) == ["not_in_stock"]


def test_a_reused_modem_identity_is_flagged(db: Session, world):
    a, b = world["devices"][4], world["devices"][5]
    a.imei = "350000000000001"
    db.flush()
    out = bench_checks.for_identity(db, b, {"imei": "350000000000001"})
    assert _codes(out) == ["duplicate_imei"]
    assert out[0]["data"]["other_device_id"] == a.id


def test_an_identity_only_on_this_device_is_not_a_duplicate(db: Session, world):
    a = world["devices"][6]
    a.imei = "350000000000002"
    db.flush()
    assert bench_checks.for_identity(db, a, {"imei": "350000000000002"}) == []
