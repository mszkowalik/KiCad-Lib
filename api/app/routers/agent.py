"""Agent tool surface — the HTTP entry point the external MCP server (Claude
Code) drives.

Every capability an agent has is a callable in ``services/agent_tools.py::TOOLS``.
The platform runs no agent of its own (decision 0062). This router does NOT
reimplement any of them — it dispatches by name:

    GET  /api/agent/tools          -> the tool catalog (name, description, JSON schema)
    POST /api/agent/tools/{name}   -> run one tool with a JSON object of arguments
    GET  /api/agent/mcp-server     -> the stdio MCP server script an agent installs

The MCP server fetches the catalog once and proxies each call here, so the tool
logic and the JSON responses are reused exactly (reuse first — never
reinvent). An agent brings its own web tools.

Auth: a personal API token (``Authorization: Bearer 7s_…``), resolved by
``authgate.AuthGate`` like every other route. ``_require_auth`` below only keeps
the legacy shared ``mcp_token`` and the auth-disabled dev posture.
"""
import json
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..services import agent_tools
from .util import content_disposition

router = APIRouter(prefix="/api/agent")

# name -> BetaFunctionTool. The object is callable and also carries
# .name / .description / .input_schema / .to_dict() / .func (the raw function).
_TOOLS = {t.name: t for t in agent_tools.TOOLS}


def _require_auth(request: Request, authorization: str | None) -> None:
    """Accept a PERSONAL token, or the legacy shared `MCP_TOKEN`.

    `authgate.AuthGate` gates this router already when `auth_enabled` is on, so
    a user's own token arrives resolved. What survives here is the pre-auth
    shared secret — which is also the only check when auth is switched off.
    """
    if getattr(request.state, "user", None) is not None:
        return
    if not settings.mcp_token:
        # Historic posture: an unset MCP_TOKEN left these endpoints open. That
        # is now only reachable with auth_enabled=False, i.e. localhost dev.
        return
    if settings.auth_legacy_tokens and authorization == f"Bearer {settings.mcp_token}":
        return
    raise HTTPException(status_code=401, detail="invalid or missing bearer token")


_MCP_SERVER = Path(__file__).resolve().parent.parent / "services" / "mcp_server" / "server.py"


@router.get("/mcp-server")
def mcp_server_script(request: Request, authorization: str | None = Header(default=None)):
    """The stdio MCP server, for an agent setting itself up from the Account
    page's prompt. Same gate as the tools it proxies: the agent downloads it
    with the token the user just saved, so a 200 here also proves the token."""
    _require_auth(request, authorization)
    return Response(
        content=_MCP_SERVER.read_text(encoding="utf-8"),
        media_type="text/x-python",
        headers={"Content-Disposition": content_disposition("attachment", "kicad_library_mcp.py")},
    )


@router.get("/tools")
def list_tools(request: Request, authorization: str | None = Header(default=None)) -> list[dict]:
    """Catalog of every library tool: {name, description, input_schema}. The MCP
    server calls this once to generate its own tool list."""
    _require_auth(request, authorization)
    return [t.to_dict() for t in agent_tools.TOOLS]


@router.post("/tools/{name}")
async def call_tool(
    name: str,
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Run one tool with the JSON object of arguments in the request body (an
    empty body means no arguments). Returns ``{"result": <str | list-of-content
    -blocks>}``. Most tools return a JSON string; ``read_datasheet`` returns a
    list of text/image content blocks. A tool that raises is surfaced as an
    error result (``is_error: true``) rather than a 500, mirroring how the agent
    normally sees tool failures."""
    _require_auth(request, authorization)
    tool = _TOOLS.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown tool {name!r}")

    raw = await request.body()
    ctype = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if raw and ctype and not (ctype == "application/json" or ctype.endswith("+json")):
        # The company gate reads a form as a form (decision 0070): a JSON body
        # sent under another type would reach the tool unread by the gate.
        raise HTTPException(status_code=415, detail="send the arguments as application/json")
    args: object = {}
    if raw:
        try:
            args = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"body must be JSON: {e}") from e
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object of arguments")

    try:
        # Tools are synchronous and block on the DB / network — run them off the
        # event loop so one slow call can't stall the API.
        result = await run_in_threadpool(tool.func, **args)
    except TypeError as e:  # unexpected / missing argument names
        raise HTTPException(status_code=400, detail=f"bad arguments for {name!r}: {e}") from e
    except Exception as e:  # noqa: BLE001 — hand back to the agent, don't 500
        return {"result": json.dumps({"error": f"{type(e).__name__}: {e}"}), "is_error": True}
    return {"result": result}
