"""Agent tool surface — the HTTP entry point the external MCP server (Claude
Code) drives.

Every library capability the agent has is a callable already defined for the
in-process Jaravis agent (``services/jaravis.py::TOOLS``). This router does NOT
reimplement any of them — it dispatches by name:

    GET  /api/agent/tools          -> the tool catalog (name, description, JSON schema)
    POST /api/agent/tools/{name}   -> run one tool with a JSON object of arguments

The MCP server fetches the catalog once and proxies each call here, so the tool
logic, the LLM-shaped JSON responses, and the draft-only write gate are all
reused exactly (reuse first — never reinvent). Anthropic server tools
(``web_search`` / ``web_fetch``) are intentionally NOT exposed — Claude Code
brings its own web tools.

Auth: when ``settings.mcp_token`` is set, an ``Authorization: Bearer <token>``
header is required. Empty token = open (fine on localhost); set it before the
platform is reachable remotely, since these endpoints can create drafts.
"""
import json

from fastapi import APIRouter, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..config import settings
from ..services import jaravis

router = APIRouter(prefix="/api/agent")

# name -> BetaFunctionTool. The object is callable and also carries
# .name / .description / .input_schema / .to_dict() / .func (the raw function).
_TOOLS = {t.name: t for t in jaravis.TOOLS}


def _require_auth(authorization: str | None) -> None:
    if not settings.mcp_token:
        return
    if authorization != f"Bearer {settings.mcp_token}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


@router.get("/tools")
def list_tools(authorization: str | None = Header(default=None)) -> list[dict]:
    """Catalog of every library tool: {name, description, input_schema}. The MCP
    server calls this once to generate its own tool list."""
    _require_auth(authorization)
    return [t.to_dict() for t in jaravis.TOOLS]


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
    _require_auth(authorization)
    tool = _TOOLS.get(name)
    if tool is None:
        raise HTTPException(status_code=404, detail=f"unknown tool {name!r}")

    raw = await request.body()
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
