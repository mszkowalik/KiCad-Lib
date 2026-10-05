"""A crafted batch's bench runs what its process lists (decision 0076).

The bench page offers the batch's bench steps in route order, each with the
procedure (deployment) its process names, and the run API accepts only those
procedures for the batch — at their current version, or another one with a
reason. A bench trial (no batch) runs any procedure.

Run from `api/`, with the dev database up:
    python -m pytest tests/flasher -q
"""
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import flasher as F
from app.routers import process as pr
from app.services import process as P


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
def w(db, monkeypatch):
    # The run API validates the version's own steps; that is not what these
    # tests are about, and a two-step stand-in procedure would not pass it.
    monkeypatch.setattr(F.validate, "check", lambda _db, _v: {"ok": True, "errors": []})
    proj = M.Project(name="test-bench-process", git_url="https://example.invalid/bp.git")
    db.add(proj)
    db.flush()
    deps = {}
    for name, kind in (("bp-flash", "flash"), ("bp-test", "test"), ("bp-mark", "mark")):
        d = M.Deployment(project_id=proj.id, name=name, kind=kind)
        db.add(d)
        db.flush()
        vs = [M.DeploymentVersion(deployment_id=d.id, version_no=n, status="published", steps=[]) for n in (1, 2)]
        db.add_all(vs)
        db.flush()
        d.current_version_id = vs[1].id
        deps[kind] = (d, vs)
    graph = {
        "steps": [
            {"key": "assembly", "label": "Board", "kind": "assembly", "required": True},
            {"key": "receive", "label": "Receive", "kind": "receive", "required": True},
            {"key": "label", "label": "Barcode label", "kind": "label", "required": True, "needs": ["program"],
             "deployment_id": deps["mark"][0].id},
            {"key": "program", "label": "Program", "kind": "program", "required": True, "needs": ["receive"],
             "deployment_id": deps["flash"][0].id},
            {"key": "laser", "label": "Laser mark", "kind": "mark_laser", "required": True, "needs": ["program"],
             "deployment_id": deps["mark"][0].id},
            {"key": "finish", "label": "Finished", "kind": "finish"},
        ],
        "route": ["assembly", "receive", "program", "laser", "label", "finish"],
        "prepared": [],
    }
    v = P.compose(db, proj.id, actor="test", graph=graph)
    P.publish(db, v, actor="test", comment="bench process")
    run = M.ProductionRun(project_id=proj.id, label="TB-bench", run_date="2026-10-01", qty=10,
                          process_version_id=v.id)
    db.add(run)
    db.flush()
    return SimpleNamespace(proj=proj, deps=deps, run=run)


def _create(db, **kw):
    return F.create_run(F.RunCreate(**kw), SimpleNamespace(state=SimpleNamespace(user=None)), db=db)


def test_the_bench_is_offered_the_process_s_bench_steps_in_route_order(db, w):
    got = pr.bench_stacks(w.run.id, db=db)["steps"]
    assert [(s["key"], s["kind"], s["place"]) for s in got] == [
        ("program", "program", "programming_bench"), ("laser", "mark_laser", "marking_bench"),
        ("label", "label", "marking_bench")]
    assert got[1]["deployment"] == {"id": w.deps["mark"][0].id, "name": "bp-mark", "kind": "mark",
                                    "current_version_id": w.deps["mark"][1][1].id}


def test_a_crafted_batch_runs_only_the_procedures_its_process_names(db, w):
    flash_v2, test_v2 = w.deps["flash"][1][1], w.deps["test"][1][1]
    assert _create(db, production_run_id=w.run.id, deployment_version_id=flash_v2.id)["run_id"]
    with pytest.raises(HTTPException) as e:
        _create(db, production_run_id=w.run.id, deployment_version_id=test_v2.id)
    assert e.value.status_code == 409 and "names no bench step done by bp-test" in str(e.value.detail)
    assert _create(db, deployment_version_id=test_v2.id)["run_id"]          # a bench trial may


def test_another_version_than_the_current_one_needs_a_reason(db, w):
    flash_v1 = w.deps["flash"][1][0]
    with pytest.raises(HTTPException) as e:
        _create(db, production_run_id=w.run.id, deployment_version_id=flash_v1.id)
    assert e.value.status_code == 409 and "override_reason" in str(e.value.detail)
    made = _create(db, production_run_id=w.run.id, deployment_version_id=flash_v1.id,
                   override_reason="the batch was started on v1")
    assert db.get(M.ProgrammingRun, made["run_id"]).release_override_reason == "the batch was started on v1"
