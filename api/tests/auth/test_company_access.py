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


def _model_keys(annotation, depth=0):
    """Field names of a pydantic body model, its nested models and lists of
    them — the keys the gate reads from a JSON body."""
    import typing

    from pydantic import BaseModel

    if depth > 3:
        return
    for arg in typing.get_args(annotation) or ():
        yield from _model_keys(arg, depth + 1)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        for name, f in annotation.model_fields.items():
            yield name
            if _scalar_list(f.annotation):
                yield f"{name}[]"
            yield from _model_keys(f.annotation, depth + 1)


def _scalar_list(annotation) -> bool:
    """A list of ints or strings: the gate reads each item under the key."""
    import typing

    for a in (annotation, *typing.get_args(annotation)):
        if typing.get_origin(a) in (list, set, tuple) and all(x in (int, str) for x in typing.get_args(a)):
            return True
    return False


def _field_keys():
    """(route path, key) for every query parameter and JSON body key named
    `*_id` of every mounted route, and every `*_id` argument of an agent tool."""
    import inspect

    from app.services import agent_tools as T

    def flat(dep):
        yield dep
        for sub in dep.dependencies:
            yield from flat(sub)

    out = set()
    for r in _walk(app.routes):
        for dep in flat(r.dependant):
            for q in dep.query_params:
                out.add((r.path, q.alias or q.name))
            for b in dep.body_params:
                out.add((r.path, b.alias or b.name))
                out.update((r.path, k) for k in _model_keys(b.field_info.annotation))
    for t in T.TOOLS:
        for name in inspect.signature(t.func).parameters:
            out.add(("/api/agent/tools/{name}", name))
    # `*_id` keys, `*_ids` keys and any list of ints or strings (`serials`).
    picked = set()
    for path, k in out:
        if k.endswith("[]"):
            picked.add((path, k[:-2]))
        elif k.endswith(("_id", "_ids")):
            picked.add((path, k))
    return picked


def test_every_query_and_body_id_is_classified():
    missing = sorted(f"{path} {k}" for path, k in _field_keys() if not A.classify_field(path, k))
    assert not missing, ("classify these in services/access.py (FIELD_RESOLVERS for company "
                         f"data, NOT_COMPANY_FIELDS for shared data): {missing}")


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


# --- review fixes of 2026-10-04 -------------------------------------------------

def _as(user, via="token"):
    from app.services import tracking

    return tracking.bind(tracking.RequestActor(request_id="t", user_id=user.id if user else None,
                                               username=user.username if user else "",
                                               name=user.username if user else "", auth_via=via))


def test_an_id_is_parsed_the_way_fastapi_parses_it(db, world):
    """`/api/runs/15371.0` reaches the route as run 15371, so the gate must
    read it as 15371 too — and refuse an id it cannot read, never skip it."""
    u = world.u9
    for spelling in (f"{world.r7.id}.0", f" {world.r7.id} ", f"+{world.r7.id}"):
        assert not A.may_open(db, u, "/api/runs/{run_id}", {"run_id": spelling}), spelling
    assert not A.may_open(db, u, "/api/runs/{run_id}", {"run_id": "seven"})
    assert A.may_open(db, u, "/api/projects/{project_id}", {"project_id": f"{world.p9.id}.0"})


def test_query_and_body_ids_are_gated(db, world):
    """A batch named in a body (`lines[].run_id`) or a query (`?project_id=`)
    is company data exactly as in a path."""
    fields = list(A._fields({"supplier": "X", "lines": [{"run_id": world.r7.id, "qty": 1}]}))
    assert ("run_id", world.r7.id) in fields
    assert A.field_companies(db, "/api/run-documents/{doc_id}/lines", fields) == [{world.s7.id}]
    assert A.field_companies(db, "/api/flasher/mosquitto", [("project_id", str(world.p7.id))]) == [{world.s7.id}]
    assert A.field_companies(db, "/api/orders", [("project_id", "x")]) == [set()]
    tok = _as(world.u9)
    try:
        assert not A._check(db, None, world.u9, "/api/run-cost-lines/{line_id}", {}, fields)
        assert A._check(db, None, world.u9, "/api/orders", {}, [("project_id", str(world.p9.id))])
    finally:
        from app.services import tracking
        tracking.unbind(tok)


def test_the_flasher_s_run_is_a_programming_attempt(db, world):
    """`/api/flasher/runs/{run_id}` names a ProgrammingRun, never a batch."""
    pr = M.ProgrammingRun(production_run_id=world.r7.id, status="pass")
    db.add(pr)
    db.flush()
    assert A.companies_of(db, "/api/flasher/runs/{run_id}", {"run_id": str(pr.id)}) == [{world.s7.id}]
    assert A.companies_of(db, "/api/flasher/ws/{run_id}", {"run_id": str(pr.id)}) == [{world.s7.id}]


def test_a_legacy_token_sees_no_company(db, world):
    from app.services import tracking

    tok = _as(None, via="legacy")
    try:
        assert A.allowed_companies(db) == set()
    finally:
        tracking.unbind(tok)
    tok = _as(world.admin)
    try:
        assert A.allowed_companies(db) is None
    finally:
        tracking.unbind(tok)


def test_the_gate_refuses_a_websocket_of_another_company(db, world):
    import asyncio

    from fastapi import WebSocketException
    from starlette.requests import HTTPConnection

    from app.services import tracking

    pr = M.ProgrammingRun(production_run_id=world.r7.id, status="running")
    db.add(pr)
    db.flush()
    scope = {"type": "websocket", "path": f"/api/flasher/ws/{pr.id}", "query_string": b"", "headers": [],
             "path_params": {"run_id": str(pr.id)}, "route": SimpleNamespace(path="/api/flasher/ws/{run_id}"),
             "state": {"user": world.u9}}
    tok = _as(world.u9)
    try:
        with pytest.raises(WebSocketException):
            asyncio.run(A.require_company_access(HTTPConnection(scope), db))
        scope["state"] = {"user": world.admin}
        asyncio.run(A.require_company_access(HTTPConnection(scope), db))
    finally:
        tracking.unbind(tok)


def test_an_app_dependency_on_the_connection_serves_a_websocket():
    """The gate takes an HTTPConnection, not a Request: a Request-typed app
    dependency fails every WebSocket route."""
    from fastapi import APIRouter, Depends, FastAPI, WebSocket
    from fastapi.testclient import TestClient
    from starlette.requests import HTTPConnection

    seen = []

    def gate(conn: HTTPConnection):
        seen.append(conn.scope["type"])

    r = APIRouter(prefix="/api")

    @r.websocket("/ws/{x_id}")
    async def ws(websocket: WebSocket, x_id: int):
        await websocket.accept()
        await websocket.send_text(str(x_id))
        await websocket.close()

    mini = FastAPI(dependencies=[Depends(gate)])
    mini.include_router(r)
    with TestClient(mini).websocket_connect("/api/ws/5") as sock:
        assert sock.receive_text() == "5"
    assert seen == ["websocket"]


def test_a_journal_batch_belongs_to_the_companies_it_touched(db, world):
    from fastapi import HTTPException

    from app.services import tracking

    wb = M.WriteBatch(kind="test", source_ref="t")
    db.add(wb)
    db.flush()
    db.add(M.WriteBatchRow(batch_id=wb.id, table_name="run_cost_documents", row_id=world.doc7.id, op="insert"))
    db.add(M.WriteBatchRow(batch_id=wb.id, table_name="run_cost_lines", row_id=999999999, op="delete",
                           before={"document_id": world.doc7.id}))
    db.flush()
    db.refresh(wb)
    assert A.write_batch_companies(db, wb.id) == {world.s7.id}
    assert not A.may_open(db, world.u9, "/api/ledger/batches/{batch_id}", {"batch_id": str(wb.id)})
    tok = _as(world.u9)
    try:
        with pytest.raises(HTTPException):
            A.require_every(db, A.write_batch_companies(db, wb.id))
    finally:
        tracking.unbind(tok)


def test_a_tool_that_names_a_project_by_name_follows_the_gate(db, world):
    """`get_project("…")` carries no id the HTTP gate can read, so the tool
    asks the same question itself."""
    from app.services import agent_tools as T
    from app.services import tracking

    tok = _as(world.u9)
    try:
        assert T._visible(db, "project_id", world.p9.id)
        assert not T._visible(db, "project_id", world.p7.id)
        assert not T._visible(db, "run_id", world.r7.id)
    finally:
        tracking.unbind(tok)
    assert T._visible(db, "project_id", world.p7.id)   # no request: an internal call


# --- verification round of 2026-10-04 ---------------------------------------------

def _http(path: str, route_path: str, body: bytes, ctype: str, user, path_params=None):
    from starlette.requests import Request

    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    scope = {"type": "http", "method": "POST", "path": path, "query_string": b"",
             "headers": [(b"content-type", ctype.encode())] if ctype else [],
             "path_params": path_params or {}, "route": SimpleNamespace(path=route_path),
             "state": {"user": user}}
    return Request(scope, receive)


def test_a_json_body_under_any_type_is_read_by_the_gate(db, world):
    """The agent route parses its raw body as JSON whatever the type says, so
    the gate reads every non-form body as JSON."""
    import asyncio
    import json

    from fastapi import HTTPException

    from app.services import tracking

    body = json.dumps({"line_id": 1, "run_id": world.r7.id}).encode()
    tok = _as(world.u9)
    try:
        for ctype in ("application/json", "application/octet-stream", "text/plain", "multipart/mixed", ""):
            req = _http("/api/agent/tools/x", "/api/agent/tools/{name}", body, ctype, world.u9, {"name": "x"})
            with pytest.raises(HTTPException) as e:
                asyncio.run(A.require_company_access(req, db))
            assert e.value.status_code == 404, ctype
    finally:
        tracking.unbind(tok)


def test_the_agent_route_takes_json_only():
    import asyncio

    from fastapi import HTTPException

    from app.routers import agent

    admin = SimpleNamespace(role="admin", id=0, username="t")
    req = _http("/api/agent/tools/list_projects", "/api/agent/tools/{name}", b'{"x": 1}',
                "application/x-www-form-urlencoded", admin, {"name": "list_projects"})
    with pytest.raises(HTTPException) as e:
        asyncio.run(agent.call_tool("list_projects", req, None))
    assert e.value.status_code == 415


def test_a_json_true_is_the_id_one(db, world):
    """Lax parsing reads `true` as 1, so the gate does too, and never skips it."""
    assert A.field_companies(db, "/api/documents", [("company_id", True)]) == [{1}]
    # `false` is company 0, which nobody belongs to: refused, never skipped
    assert A.field_companies(db, "/api/documents", [("company_id", False)]) == [{0}]


def test_a_list_of_device_ids_or_codes_is_read(db, world):
    d7 = M.DeviceUnit(project_id=world.p7.id, serial="TESTACC7", mac="aa:bb:cc:00:00:07",
                      production_run_id=world.r7.id)
    db.add(d7)
    db.flush()
    fields = list(A._fields({"device_ids": [d7.id], "dry_run": False}))
    assert ("device_ids", d7.id) in fields
    assert A.field_companies(db, "/api/runs/{run_id}/rebatch", fields) == [{world.s7.id}]
    assert A.field_companies(db, "/api/orders/{order_id}/allocate", [("serials", "TESTACC7")]) == [{world.s7.id}]
    assert A.field_companies(db, "/api/runs/{run_id}/craft/step", [("codes", "AA:BB:CC:00:00:07")]) == [{world.s7.id}]


def test_a_jlc_decision_is_its_batch_s(db, world):
    db.add(M.JlcOrderDecision(smt_order_code="SMT-TEST-ACC", outcome="link_run", run_id=world.r7.id))
    db.flush()
    path = "/api/jlc/import/decision/{smt_order_code}/apply"
    assert A.companies_of(db, path, {"smt_order_code": "SMT-TEST-ACC"}) == [{world.s7.id}]
    assert not A.may_open(db, world.u9, path, {"smt_order_code": "SMT-TEST-ACC"})


def test_a_snapshot_in_a_socket_message_follows_the_gate(db, world):
    from app.services import tracking

    tok = _as(world.u9)
    try:
        assert A.hides_project(db, world.p7.id)
        assert not A.hides_project(db, world.p9.id)
    finally:
        tracking.unbind(tok)


def test_the_password_export_follows_the_device_rule(db, world):
    """A device of a 9SIGMA batch is 9SIGMA's, though its project was once
    7Sigma's."""
    C.move_project(db, world.p7, world.s9, "2025-06-01")
    r9 = M.ProductionRun(project_id=world.p7.id, label="A9", run_date="2025-07-01", company_id=world.s9.id)
    db.add(r9)
    db.flush()
    d7 = M.DeviceUnit(project_id=world.p7.id, serial="TESTPW7", production_run_id=world.r7.id)
    d9 = M.DeviceUnit(project_id=world.p7.id, serial="TESTPW9", production_run_id=r9.id)
    db.add_all([d7, d9])
    db.flush()
    seven = A.visible_device_ids(db, {world.s7.id})
    nine = A.visible_device_ids(db, {world.s9.id})
    assert d7.id in seven and d9.id not in seven
    assert d9.id in nine and d7.id not in nine


def test_a_socket_gives_its_connection_back():
    import asyncio

    from starlette.requests import HTTPConnection

    from app.db import SessionLocal
    from app.services import tracking

    s = SessionLocal()
    try:
        user = SimpleNamespace(role="user", id=-1, username="nobody")
        scope = {"type": "websocket", "path": "/api/flasher/ws/999999999", "query_string": b"", "headers": [],
                 "path_params": {"run_id": "999999999"}, "route": SimpleNamespace(path="/api/flasher/ws/{run_id}"),
                 "state": {"user": user}}
        tok = tracking.bind(tracking.RequestActor(request_id="t", user_id=None, username="", name="",
                                                  auth_via="token"))
        try:
            asyncio.run(A.require_company_access(HTTPConnection(scope), s))
        finally:
            tracking.unbind(tok)
        assert not s.in_transaction()
    finally:
        s.close()
