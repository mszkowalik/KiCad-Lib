"""A record of another company does not exist for the caller (decision 0065).

Two halves:

* the INVENTORY: every path parameter of every mounted route is classified in
  `services/access.py`, either as company data with a resolver or as data both
  companies share. A new route with a new parameter fails here until somebody
  decides which it is — the direction that matters, because an unclassified
  parameter is an ungated one;
* the GATE: a user of one company cannot open the other company's project,
  batch, order or invoice, and an admin can open everything.

Run from `api/`, with the dev database up:
    python -m pytest tests/auth/test_company_access.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.main import app
from app.services import access as A
from app.services import companies as C


def _walk(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        inner = getattr(route, "original_router", None)
        yield from _walk(getattr(inner, "routes", None) or getattr(route, "routes", ()))


def test_every_route_parameter_is_classified():
    missing = sorted({f"{prefix}{{{param}}}"
                      for r in _walk(app.routes)
                      for prefix, param in A.route_params(r.path)
                      if not A.classify(prefix, param)})
    assert not missing, ("classify these in services/access.py (RESOLVERS for company "
                         f"data, NOT_COMPANY_DATA for shared data): {missing}")


def test_the_gate_is_an_app_dependency():
    """On the APP, so every included router gets it. FastAPI 0.141 applies an
    app dependency to included routes at request time, not in their
    `dependant` — checked against a two-route app when this was written."""
    assert any(d.dependency is A.require_company_access for d in app.router.dependencies)


def test_an_app_dependency_reaches_an_included_route():
    from fastapi import APIRouter, Depends, FastAPI, Request
    from fastapi.testclient import TestClient

    seen = []

    def gate(request: Request):
        seen.append(request.scope["route"].path)

    r = APIRouter(prefix="/api")

    @r.get("/x/{x_id}")
    def x(x_id: int):
        return {"x": x_id}

    mini = FastAPI(dependencies=[Depends(gate)])
    mini.include_router(r)
    assert TestClient(mini).get("/api/x/5").status_code == 200
    assert seen == ["/api/x/{x_id}"]


@pytest.fixture
def db():
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
def world(db):
    s7, s9 = C.by_key(db, "7sigma"), C.by_key(db, "9sigma")
    p7 = M.Project(name="test-access-7", git_url="https://example.invalid/a7.git")
    p9 = M.Project(name="test-access-9", git_url="https://example.invalid/a9.git")
    db.add_all([p7, p9])
    db.flush()
    db.add_all([M.ProjectOwnership(project_id=p7.id, company_id=s7.id, from_date="2024-01-01"),
                M.ProjectOwnership(project_id=p9.id, company_id=s9.id, from_date="2024-08-01")])
    r7 = M.ProductionRun(project_id=p7.id, label="A7", run_date="2025-01-01", company_id=s7.id)
    doc7 = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="ACC-1",
                             doc_date="2025-01-01", company_id=s7.id)
    u9 = M.User(username="test-access-9sigma", role="user", password_hash="x")
    admin = M.User(username="test-access-admin", role="admin", password_hash="x")
    db.add_all([r7, doc7, u9, admin])
    db.flush()
    C.set_memberships(db, u9, [s9.id])
    return SimpleNamespace(s7=s7, s9=s9, p7=p7, p9=p9, r7=r7, doc7=doc7, u9=u9, admin=admin)


def test_a_user_cannot_open_the_other_company_s_records(db, world):
    u = world.u9
    assert A.may_open(db, u, "/api/projects/{project_id}", {"project_id": str(world.p9.id)})
    assert not A.may_open(db, u, "/api/projects/{project_id}", {"project_id": str(world.p7.id)})
    assert not A.may_open(db, u, "/api/runs/{run_id}", {"run_id": str(world.r7.id)})
    assert not A.may_open(db, u, "/api/run-documents/{doc_id}", {"doc_id": str(world.doc7.id)})


def test_an_admin_opens_everything(db, world):
    assert A.may_open(db, world.admin, "/api/runs/{run_id}", {"run_id": str(world.r7.id)})


def test_a_project_s_former_company_still_opens_its_history(db, world):
    """7Sigma made the project's early batches; after the move to 9Sigma a
    7Sigma-only user still opens the project they belong to the history of."""
    u7 = M.User(username="test-access-7sigma", role="user", password_hash="x")
    db.add(u7)
    db.flush()
    C.set_memberships(db, u7, [world.s7.id])
    C.move_project(db, world.p7, world.s9, "2025-06-01")
    assert A.may_open(db, u7, "/api/projects/{project_id}", {"project_id": str(world.p7.id)})


def test_a_missing_record_is_left_to_the_route(db, world):
    assert A.may_open(db, world.u9, "/api/runs/{run_id}", {"run_id": "999999999"})
