"""What a batch is programmed with, and the attempts no device shows.

A batch names no version of its own: `create_run` needs the version in the request,
and a batch's process says which procedures it runs (decision 0076).

Run from `api/`, with the dev database up:
    python -m pytest tests/flasher/test_batch_procedure.py -q
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
    monkeypatch.setattr(F.validate, "check", lambda _db, _v: {"ok": True, "errors": []})
    proj = M.Project(name="test-batch-procedure", git_url="https://example.invalid/bp.git")
    other = M.Project(name="test-batch-procedure-other", git_url="https://example.invalid/bp2.git")
    db.add_all([proj, other])
    db.flush()

    def procedure(project, name):
        d = M.Deployment(project_id=project.id, name=name, kind="flash")
        db.add(d)
        db.flush()
        pub = M.DeploymentVersion(deployment_id=d.id, version_no=1, status="published", steps=[])
        draft = M.DeploymentVersion(deployment_id=d.id, version_no=2, status="draft", steps=[])
        db.add_all([pub, draft])
        db.flush()
        d.current_version_id = pub.id
        return d, pub, draft

    a, a_pub, a_draft = procedure(proj, "bp-a")
    b, b_pub, _ = procedure(proj, "bp-b")
    _, foreign, _ = procedure(other, "bp-foreign")
    run = M.ProductionRun(project_id=proj.id, label="TB-procedure", run_date="2026-10-01", qty=10)
    db.add(run)
    db.flush()
    return SimpleNamespace(proj=proj, run=run, a=a, a_pub=a_pub, a_draft=a_draft, b=b, b_pub=b_pub, foreign=foreign)


def _create(db, **kw):
    return F.create_run(F.RunCreate(**kw), SimpleNamespace(state=SimpleNamespace(user=None)), db=db)


def test_a_run_that_names_no_version_is_refused(db, w):
    with pytest.raises(HTTPException) as e:
        _create(db, production_run_id=w.run.id)
    assert e.value.status_code == 409 and "named none" in e.value.detail


def test_the_version_named_is_the_version_run(db, w):
    out = _create(db, production_run_id=w.run.id, deployment_version_id=w.a_pub.id)
    assert out["deployment_version_id"] == w.a_pub.id


def test_where_used_names_the_batches_that_ran_the_version(db, w):
    db.add(M.ProgrammingRun(production_run_id=w.run.id, deployment_version_id=w.a_pub.id, status="passed"))
    db.flush()
    assert [b["label"] for b in F.get_deployment_version(w.a_pub.id, db=db)["where_used"]["batches"]] == ["TB-procedure"]


def test_an_attempt_that_named_no_device_is_listed_on_its_own(db, w):
    db.add(M.ProgrammingRun(production_run_id=w.run.id, deployment_version_id=w.a_pub.id, status="fail",
                            error="the agent is already programming a device"))
    db.flush()
    out = F.batch_programming(w.run.id, db=db)
    assert out["unidentified_attempts"] == 1
    assert [r["error"] for r in out["unidentified_runs"]] == ["the agent is already programming a device"]


def test_the_project_s_broker_file_is_named_after_the_project(db, w):
    r = F.mosquitto_export(w.proj.id, db=db)
    assert r.headers["content-disposition"] == 'attachment; filename="mosquitto_passwords_test-batch-procedure.txt"'
    with pytest.raises(HTTPException) as e:
        F.mosquitto_export(-1, db=db)
    assert e.value.status_code == 404


def test_the_bench_downloads_are_built(monkeypatch):
    """Their helpers sit between routes, and nothing else in the suite runs them."""
    from starlette.requests import Request

    req = Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"bench.example")],
                   "server": ("bench.example", 80), "scheme": "http", "query_string": b""})
    assert F.bench_policy(req).body.startswith(b"<?xml")
    assert F.bench_agent(req).body[:2] == b"PK"
