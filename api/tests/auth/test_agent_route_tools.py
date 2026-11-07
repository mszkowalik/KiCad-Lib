"""A route tagged `x-agent-tool` is an agent tool (decision 0106).

Two halves. The CATALOG: a tagged route has a docstring and a name of its own, and
its arguments are classified for the company gate. The CALL: it goes through the
whole app, so the real gate answers, with the caller's own client header.

Run from `api/`, with the dev database up:
    python -m pytest tests/auth/test_agent_route_tools.py -q
"""
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from app import authgate
from app.main import app
from app.services import access as A
from app.services import agent_routes as R
from app.services import agent_tools as T

ADMIN = SimpleNamespace(id=-1, username="agent-admin", name="Agent Admin", display_name="Agent Admin", role="admin",
                        is_active=True, active=True, theme="dark")
PERSON = SimpleNamespace(id=-2, username="agent-person", name="Agent Person", display_name="Agent Person", role="user",
                         is_active=True, active=True, theme="dark")


def _tools():
    return R.build(app.openapi())


def test_a_route_tool_has_a_name_of_its_own_and_a_description():
    tools = _tools()
    assert tools, "no route carries x-agent-tool"
    assert not {t.name for t in T.TOOLS} & set(tools)
    for tool in tools.values():
        assert tool.description.strip()


def test_every_id_a_route_tool_takes_is_classified():
    """The tool call's own body passes the company gate first, as a written tool's
    does, so an id in it needs a class as well as the route's own."""
    missing = sorted(
        f"{tool.name} {key}" for tool in _tools().values() for key in (*tool.query_params, *tool.body_params)
        if key.endswith(("_id", "_ids")) and not A.classify_field("/api/agent/tools/{name}", key)
    )
    assert not missing, f"classify these in services/access.py: {missing}"


def test_a_tag_on_a_route_with_a_clash_is_refused():
    spec = {"paths": {"/api/x/{a}": {"post": {
        "x-agent-tool": "x", "description": "d",
        "parameters": [{"name": "a", "in": "path", "required": True, "schema": {"type": "string"}}],
        "requestBody": {"content": {"application/json": {"schema": {"properties": {"a": {"type": "string"}}}}}},
    }}}}
    with pytest.raises(ValueError, match="two arguments"):
        R.build(spec)


def test_a_tag_on_a_route_with_no_docstring_is_refused():
    with pytest.raises(ValueError, match="docstring"):
        R.build({"paths": {"/api/x": {"get": {"x-agent-tool": "x"}}}})


def test_the_arguments_land_in_the_path_the_query_and_the_body():
    tool = R.build({"paths": {"/api/x/{a}": {"post": {
        "x-agent-tool": "x", "description": "d",
        "parameters": [{"name": "a", "in": "path", "required": True, "schema": {"type": "string"}},
                       {"name": "b", "in": "query", "schema": {"type": "string"}}],
        "requestBody": {"content": {"application/json": {"schema": {"properties": {"c": {"type": "string"}}}}}},
    }}}})["x"]
    assert R.split(tool, {"a": "1/2", "b": "q", "c": "v", "max_chars": 5}) == ("/api/x/1%2F2", {"b": "q"}, {"c": "v"}, 5)
    with pytest.raises(ValueError, match="no argument"):
        R.split(tool, {"a": "1", "nope": 1})
    with pytest.raises(ValueError, match="required"):
        R.split(tool, {"b": "q"})


def test_a_delete_needs_confirm():
    tool = R.build({"paths": {"/api/x": {"delete": {"x-agent-tool": "x", "description": "d"}}}})["x"]
    with pytest.raises(ValueError, match="confirm"):
        R.split(tool, {})
    assert R.split(tool, {"confirm": True})[0] == "/api/x"


@pytest.fixture
def gated(monkeypatch):
    """The real app behind the real gate, with only the token lookup and the
    request log faked. `caller` says who the token is."""
    who = {"user": PERSON}
    logged: list[tuple] = []
    monkeypatch.setattr(authgate.settings, "auth_enabled", True)
    monkeypatch.setattr(authgate, "_resolve", lambda *a: (who["user"], True, "token"))
    monkeypatch.setattr(authgate.tracking, "write_request_row", lambda *a: logged.append(a))
    return TestClient(app), who, logged


AUTH = {"Authorization": "Bearer x", "X-Kicad-Client": "mcp"}


def test_the_catalog_lists_both_kinds(gated):
    client, _, _ = gated
    names = {t["name"] for t in client.get("/api/agent/tools", headers=AUTH).json()}
    assert "get_parts_stock" in names and "search_components" in names


def test_the_role_gate_answers_for_a_route_tool(gated):
    """`get_settings` is admin-only, so this proves the inner call met the gate."""
    client, who, _ = gated
    refused = client.post("/api/agent/tools/get_settings", json={}, headers=AUTH).json()
    assert refused["is_error"] and '"status": 403' in refused["result"]
    who["user"] = ADMIN
    assert not client.post("/api/agent/tools/get_settings", json={}, headers=AUTH).json().get("is_error")


def test_a_bad_argument_is_named(gated):
    client, _, _ = gated
    r = client.post("/api/agent/tools/list_exchange_rates", json={"nope": 1}, headers=AUTH)
    assert r.status_code == 400 and "nope" in r.json()["detail"]


def test_an_unknown_tool_is_a_404(gated):
    client, _, _ = gated
    assert client.post("/api/agent/tools/no_such_tool", json={}, headers=AUTH).status_code == 404


def test_a_write_through_a_route_tool_names_the_client_and_the_real_path(gated):
    """The undo list groups an agent's changes by client (decision 0089), so the
    inner request must carry it. A box that does not exist writes nothing."""
    client, who, logged = gated
    who["user"] = ADMIN
    r = client.post("/api/agent/tools/organizer_take", json={"box_id": 0, "qty": 1, "purpose": "research", "note": "t"},
                    headers=AUTH).json()
    assert r["is_error"] and '"status": 404' in r["result"]
    inner = [row for row in logged if row[2] == "/api/organizers/boxes/0/take"]
    assert inner and inner[0][0].client == "mcp"


def test_a_long_answer_is_cut(gated):
    client, who, _ = gated
    who["user"] = ADMIN
    text = client.post("/api/agent/tools/get_settings", json={"max_chars": 20}, headers=AUTH).json()["result"]
    assert "cut at 20 of" in text
