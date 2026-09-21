"""The cross-project batch list behind Production -> Batches.

What is being protected: the list must cross PROJECT boundaries and carry the
project's name. Before it existed the only cross-project list of batches was the
invoice register's, which is built from documents — so a batch nobody had billed
yet did not appear anywhere outside its own project.

Run from `api/`, with the dev database up:
    python -m pytest tests/orders -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import production_runs as router


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
def two_projects(db: Session):
    made = []
    for n in (1, 2):
        p = M.Project(name=f"test-run-list-{n}", git_url=f"https://example.invalid/r{n}.git")
        db.add(p)
        db.flush()
        r = M.ProductionRun(project_id=p.id, label=f"L{n}", run_date=f"2026-0{n}-01",
                            status="planned", qty=10 * n)
        db.add(r)
        db.flush()
        made.append((p, r))
    return made


def test_the_list_crosses_projects_and_names_them(db: Session, two_projects):
    rows = {r["id"]: r for r in router.list_all_runs(db=db)}
    for project, run in two_projects:
        assert run.id in rows, "a batch is missing from the cross-project list"
        assert rows[run.id]["project"] == project.name, \
            "the list carries the project's NAME — an id is not something to read"


def test_the_same_payload_serves_one_project(db: Session, two_projects):
    """One table component renders both lists, so both must agree on the shape —
    including `project`, which the per-project list did not carry until the
    cross-project one needed it."""
    project, run = two_projects[0]
    other = two_projects[1][1]
    mine = {r["id"]: r for r in router.list_runs(project.id, db=db)}
    assert set(mine) == {run.id}
    assert other.id not in mine
    assert mine[run.id]["project"] == project.name
    assert set(mine[run.id]) == set(router.list_all_runs(db=db)[0])


def test_a_batch_with_no_date_sorts_last(db: Session, two_projects):
    """Newest first is the point of the ordering, and a NULL date must not win
    it: a batch nobody has dated is not the most recent thing that happened."""
    project = two_projects[0][0]
    undated = M.ProductionRun(project_id=project.id, label="no date yet",
                              status="planned", qty=1)
    db.add(undated)
    db.flush()
    ids = [r["id"] for r in router.list_all_runs(db=db)]
    dated = [r["id"] for r in router.list_all_runs(db=db) if r["run_date"]]
    assert ids.index(undated.id) > ids.index(dated[-1])
