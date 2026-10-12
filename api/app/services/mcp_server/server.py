# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2,<2", "httpx>=0.27", "anyio>=4"]
# ///
"""KiCad library MCP server.

A thin, stateless client over the platform's ``/api/agent`` surface. It does NOT
touch the database or import any app code — it only speaks HTTP to the running
platform API. On start it fetches the tool catalog from ``GET /api/agent/tools``
and exposes each entry as an MCP tool; every call is proxied to
``POST /api/agent/tools/{name}``. Because the catalog and the tool logic live in
the API, this server automatically tracks whatever tools the platform offers.

**Two tools run HERE rather than being proxied: ``upload_model3d`` and
``attach_invoice_file``.** A 3D model
is a multi-megabyte STEP file sitting on the user's own disk, and the agent
surface takes JSON — proxying it would mean base64 in a tool call, which the
platform-side agent (which has no access to this machine's filesystem) could not
produce anyway. So this server reads the file locally and posts it as multipart
to ``/api/models3d/upload``. Keep local tools to that shape: something the API
genuinely cannot do because the bytes are here.

**Two more run here: ``api_routes`` and ``api_request``** (decision 0088). They
reach every ``/api/`` route the catalog does not cover, as the token's user, so
the platform's own permissions decide what an agent may do. They live here, not
in the catalog, because this server already holds the token and speaks HTTP: on
the platform side the API would have to call itself.

Transport: stdio (Claude Code spawns this process).

**`mcp` is pinned below 2.0 on purpose.** 2.0.0 removed the low-level
``Server.list_tools()`` / ``Server.call_tool()`` decorators this file is built
on, so an unpinned ``mcp>=1.2`` resolves to a version where the server dies at
import with ``'Server' object has no attribute 'list_tools'`` — and uv resolves
fresh on any cold start, so it breaks with no local change. Lift the pin only
together with a port to the 2.x API.

**The token is read from a FILE when the environment does not carry one.**
The setup prompt on the Account page registers this server with no secret in
the agent's config: the user saves the token in ``~/.config/kicad-library/token``
(mode 600) from their own terminal, so it never passes through the agent's chat
or a config file the agent prints. ``KICAD_MCP_TOKEN`` still wins when set,
which keeps the repo's ``.mcp.json`` + ``settings.local.json`` wiring working.

The platform serves this file at ``GET /api/agent/mcp-server`` — that is why it
lives under ``api/app`` and not in a top-level ``mcp/`` directory, which is
not in the api image.

Environment:
  KICAD_API_URL         base URL of the platform API  (default: http://localhost:8020)
  KICAD_MCP_TOKEN       bearer token                  (default: read from the token file)
  KICAD_MCP_TOKEN_FILE  where the token file is       (default: ~/.config/kicad-library/token)

Run standalone:  uv run --script api/app/services/mcp_server/server.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
import httpx
from mcp import types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

API_URL = os.environ.get("KICAD_API_URL", "http://localhost:8020").rstrip("/")
TOKEN_FILE = Path(os.environ.get("KICAD_MCP_TOKEN_FILE")
                  or "~/.config/kicad-library/token").expanduser()


def _read_token() -> tuple[str, str]:
    """The token and where it came from. Never logs the value itself."""
    env = os.environ.get("KICAD_MCP_TOKEN", "").strip()
    if env:
        return env, "KICAD_MCP_TOKEN"
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip(), str(TOKEN_FILE)
    except OSError:
        return "", "none"


TOKEN, TOKEN_SOURCE = _read_token()

server = Server("kicad-library")


def _log(msg: str) -> None:
    # stdout is the MCP protocol channel — diagnostics MUST go to stderr.
    print(f"[kicad-mcp] {msg}", file=sys.stderr, flush=True)


_TOKEN_HELP = (f"save a live token from the platform's Account page in {TOKEN_FILE} "
               "(or set KICAD_MCP_TOKEN), then restart the MCP server")


def _headers() -> dict[str, str]:
    # The platform files an agent's changes under client "mcp" (decision 0089).
    h = {"accept": "application/json", "x-kicad-client": "mcp"}
    if TOKEN:
        h["authorization"] = f"Bearer {TOKEN}"
    return h


async def _get(path: str):
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(API_URL + path, headers=_headers())
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict):
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(
            API_URL + path,
            headers={**_headers(), "content-type": "application/json"},
            json=body,
        )
        r.raise_for_status()
        return r.json()


# --------------------------------------------------------------- local tools

MODEL_SUFFIXES = (".step", ".stp", ".wrl")
HOUSE_DIR = "7Sigma.3dshapes"  # keep in step with services/pcm_plugin/model_paths.py

UPLOAD_MODEL3D = types.Tool(
    name="upload_model3d",
    description=(
        "Store a 3D model file (STEP/WRL) from THIS machine in the library, so a "
        "footprint can reference it as ${SEVENSIGMA_DIR}/3DModels/<rel_path>. Use it "
        "before proposing a footprint whose (model ...) points anywhere else — the "
        "platform refuses a footprint that names a path outside the library, and a "
        "footprint with no model fails the fp.model3d validation item. Re-uploading "
        "the same rel_path REPLACES the file, which is how a corrected model is "
        "fixed. Reads the file locally: pass a path, never file content."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path to the .step/.stp/.wrl file on this machine "
                               "(~ is expanded; a relative path resolves against "
                               "the working directory).",
            },
            "rel_path": {
                "type": "string",
                "description": "Where it goes under 3DModels/, e.g. "
                               "'Package_SO.3dshapes/SOIC-8_3.9x4.9mm_P1.27mm.step'. "
                               f"Defaults to the source folder when that is a "
                               f"*.3dshapes directory, else '{HOUSE_DIR}/<filename>'.",
            },
        },
        "required": ["file_path"],
        "additionalProperties": False,
    },
)



def _suggest_rel_path(src: Path) -> str:
    """Same rule as `services/pcm_plugin/model_paths.suggest_rel_path`, minus the
    "reuse the footprint's current folder" clause — no footprint is named here."""
    if src.parent.name.endswith(".3dshapes"):
        return f"{src.parent.name}/{src.name}"
    return f"{HOUSE_DIR}/{src.name}"


async def _upload_model3d(args: dict) -> str:
    raw = str(args.get("file_path") or "").strip()
    if not raw:
        return "file_path is required."
    src = Path(raw).expanduser()
    if not src.is_file():
        return f"No file at {src} — pass a path on the machine running this MCP server."
    if src.suffix.lower() not in MODEL_SUFFIXES:
        return f"{src.name}: a 3D model must be one of {', '.join(MODEL_SUFFIXES)}."
    rel = str(args.get("rel_path") or "").strip().lstrip("/") or _suggest_rel_path(src)
    if ".." in rel.split("/"):
        return f"rel_path {rel!r} must not contain '..'."

    data = src.read_bytes()
    async with httpx.AsyncClient(timeout=900.0) as client:
        r = await client.post(
            f"{API_URL}/api/models3d/upload",
            params={"rel_path": rel},
            headers=_headers(),
            files={"file": (src.name, data, "application/octet-stream")},
        )
    if r.status_code != 200:
        return f"Upload failed: HTTP {r.status_code} — {r.text[:500]}"
    out = r.json()
    out["model_node"] = (
        f'(model "${{SEVENSIGMA_DIR}}/3DModels/{out["rel_path"]}"\n'
        "  (offset (xyz 0 0 0))\n  (scale (xyz 1 1 1))\n  (rotate (xyz 0 0 0))\n)"
    )
    out["source_file"] = str(src)
    return json.dumps(out, indent=1)


ATTACH_SUFFIXES = (".pdf", ".xml", ".png", ".jpg", ".jpeg")

ATTACH_INVOICE_FILE = types.Tool(
    name="attach_invoice_file",
    description=(
        "File the original of a supplier invoice (PDF, KSeF XML or a scan) from THIS "
        "machine with its supplier document on the platform, so the money and its "
        "evidence sit together. Use it after create_supplier_invoice or "
        "import_ksef_invoice. Reads the file locally: pass a path, never file content."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "document_id": {"type": "integer", "description": "The supplier document's id."},
            "file_path": {"type": "string",
                          "description": "Path to the .pdf/.xml/.png/.jpg on this machine (~ is expanded)."},
        },
        "required": ["document_id", "file_path"],
        "additionalProperties": False,
    },
)


async def _attach_invoice_file(args: dict) -> str:
    src = Path(str(args.get("file_path") or "").strip()).expanduser()
    if not src.is_file():
        return f"No file at {src} — pass a path on the machine running this MCP server."
    if src.suffix.lower() not in ATTACH_SUFFIXES:
        return f"{src.name}: an invoice original is one of {', '.join(ATTACH_SUFFIXES)}."
    doc = int(args.get("document_id") or 0)
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.post(f"{API_URL}/api/run-documents/{doc}/attachment", headers=_headers(),
                              files={"file": (src.name, src.read_bytes(), "application/octet-stream")})
    if r.status_code != 200:
        return f"Upload failed: HTTP {r.status_code} — {r.text[:500]}"
    return json.dumps({**r.json(), "source_file": str(src)}, indent=1)


# ------------------------------------------------ the general API tools (0088)
#
# The catalog covers about a tenth of the API's routes. These two reach the
# rest as the token's user: the API applies the same role gates and company
# scope it applies to the browser, so an agent can do what its user can and
# nothing more. A dedicated tool, when one exists, stays the better path.

_SPEC: dict = {"at": 0.0, "doc": None}
_SPEC_TTL = 600.0  # a deploy adds routes; a long-running server re-reads them
_METHODS = ("get", "post", "put", "patch", "delete")

API_ROUTES = types.Tool(
    name="api_routes",
    description=(
        "Find a platform API route that no other tool covers (batch crafting, process "
        "versions, shipments and orders, stock, devices, the flasher, companies, ...), from "
        "the API's own OpenAPI document. Without `path`: lists the routes whose method, path, "
        "summary or tag contain every word of `filter`, one per line. With `path` and "
        "`method`: that route's parameters, request body schema and description. Then call "
        "it with api_request. Prefer a dedicated tool when one exists."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "filter": {"type": "string",
                       "description": "Words that must all appear, e.g. 'craft step' or 'shipments pack'."},
            "path": {"type": "string",
                     "description": "One route's path exactly as listed, e.g. '/api/runs/{run_id}/craft/step'."},
            "method": {"type": "string", "description": "With `path`: GET, POST, PUT, PATCH or DELETE."},
        },
        "additionalProperties": False,
    },
)

API_REQUEST = types.Tool(
    name="api_request",
    description=(
        "Call any platform API route under /api/ as the token's user, for what no dedicated "
        "tool does. Find the route and its body with api_routes first. The platform applies "
        "the same permissions as in the browser. Many write routes take `dry_run` and default "
        "it to true: send the dry run, read the plan, then repeat with dry_run false. A write "
        "is live at once, so say what you are about to change. A DELETE is refused unless "
        "`confirm` is true: ask the user before you set it. Returns the HTTP status and the "
        "JSON or text body, cut at `max_chars`; a file response is written to `save_to`."
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"]},
            "path": {"type": "string",
                     "description": "The route with its ids filled in, e.g. '/api/runs/19/craft'."},
            "query": {"type": "object", "description": "Query parameters."},
            "body": {"description": "The JSON request body, for POST, PUT and PATCH."},
            "confirm": {"type": "boolean",
                        "description": "Required for DELETE, after the user agreed. Default false."},
            "max_chars": {"type": "integer",
                          "description": "Cut the returned body at this length. Default 40000."},
            "save_to": {"type": "string",
                        "description": "Write the response body to this file on this machine "
                                       "(a PDF, an image, a ZIP) instead of returning it."},
        },
        "required": ["method", "path"],
        "additionalProperties": False,
    },
)


async def _spec() -> dict:
    now = anyio.current_time()
    if _SPEC["doc"] is None or now - _SPEC["at"] > _SPEC_TTL:
        _SPEC["doc"] = await _get("/openapi.json")
        _SPEC["at"] = now
    return _SPEC["doc"]


def _resolve(spec: dict, schema, depth: int = 0):
    """A schema with its `$ref`s replaced, three levels deep — enough for every
    request body here, and a cap for the recursive ones."""
    if isinstance(schema, list):
        return [_resolve(spec, s, depth) for s in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        if depth >= 3:
            return {"$ref": schema["$ref"]}
        name = schema["$ref"].rsplit("/", 1)[-1]
        return _resolve(spec, spec.get("components", {}).get("schemas", {}).get(name, {}), depth + 1)
    return {k: _resolve(spec, v, depth) for k, v in schema.items() if k not in ("title",)}


async def _api_routes(args: dict) -> str:
    spec = await _spec()
    paths = spec.get("paths", {})
    path = str(args.get("path") or "").strip()
    if path:
        method = str(args.get("method") or "").strip().lower()
        ops = paths.get(path)
        if ops is None:
            return f"No route {path!r}. List them with `filter` first; copy the path exactly."
        if method not in ops:
            return f"{path} takes {', '.join(m.upper() for m in ops if m in _METHODS)}, not {method.upper() or '?'}."
        op = ops[method]
        body = (op.get("requestBody") or {}).get("content", {}).get("application/json", {}).get("schema")
        return json.dumps({
            "method": method.upper(), "path": path, "summary": op.get("summary", ""),
            "description": op.get("description", ""),
            "parameters": [{"name": p.get("name"), "in": p.get("in"), "required": p.get("required", False),
                            "schema": _resolve(spec, p.get("schema", {}))} for p in op.get("parameters", [])],
            "body": _resolve(spec, body) if body else None,
        }, indent=1)
    words = str(args.get("filter") or "").lower().split()
    rows = []
    for p, ops in paths.items():
        if not p.startswith("/api/"):
            continue
        for m, op in ops.items():
            if m not in _METHODS:
                continue
            line = f"{m.upper()} {p} — {op.get('summary', '')}"
            hay = f"{line} {' '.join(op.get('tags', []))}".lower()
            if all(w in hay for w in words):
                rows.append(line)
    if not rows:
        return "No route matches. Use fewer or shorter words."
    head = f"{len(rows)} route(s)" + ("" if len(rows) <= 150 else ", the first 150 — add a word to narrow")
    return head + "\n" + "\n".join(rows[:150])


async def _api_request(args: dict) -> str:
    method = str(args.get("method") or "").upper()
    if method not in {m.upper() for m in _METHODS}:
        return f"method must be one of {', '.join(m.upper() for m in _METHODS)}."
    path = "/" + str(args.get("path") or "").strip().lstrip("/")
    if not path.startswith("/api/") or ".." in path.split("/") or "://" in path:
        return f"{path!r}: only a path under /api/ is allowed."
    if method == "DELETE" and args.get("confirm") is not True:
        return ("A DELETE needs confirm=true. Say what it removes, ask the user, and repeat "
                "the call with confirm=true only after they agree.")
    body = args.get("body")
    async with httpx.AsyncClient(timeout=300.0) as client:
        r = await client.request(method, API_URL + path, params=args.get("query") or None,
                                 headers=_headers(), json=body if body is not None else None)
    head = f"HTTP {r.status_code} {method} {path}"
    if r.status_code == 401:
        head += f" — {_TOKEN_HELP}"
    save_to = str(args.get("save_to") or "").strip()
    if save_to:
        dst = Path(save_to).expanduser()
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(r.content)
        return f"{head}\n{r.headers.get('content-type', '')}, {len(r.content)} bytes written to {dst}"
    ctype = r.headers.get("content-type", "")
    if "json" in ctype:
        text = json.dumps(r.json(), ensure_ascii=False, separators=(",", ":"))
    elif ctype.startswith("text/") or not r.content:
        text = r.text
    else:
        return f"{head}\n{ctype}, {len(r.content)} bytes — pass save_to to keep the file."
    limit = int(args.get("max_chars") or 40000)
    if len(text) > limit:
        text = (text[:limit] + f"\n… cut at {limit} of {len(text)} characters. Narrow the request "
                "(a query parameter, one record) or raise max_chars.")
    return f"{head}\n{text}"


# name -> (schema, handler). Everything not in here is proxied to the API.
LOCAL_TOOLS = {UPLOAD_MODEL3D.name: (UPLOAD_MODEL3D, lambda a: _upload_model3d(a)),
               ATTACH_INVOICE_FILE.name: (ATTACH_INVOICE_FILE, lambda a: _attach_invoice_file(a)),
               API_ROUTES.name: (API_ROUTES, lambda a: _api_routes(a)),
               API_REQUEST.name: (API_REQUEST, lambda a: _api_request(a))}


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    try:
        catalog = await _get("/api/agent/tools")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 401:
            # Re-raised with the fix in it: the client shows this message to the
            # agent, and httpx's own text says nothing about where a token goes.
            _log(f"the platform refused the token (401) — {_TOKEN_HELP}")
            raise RuntimeError(f"401 from {API_URL}: {_TOKEN_HELP}") from e
        _log(f"could not fetch tool catalog from {API_URL}: {e!r}")
        raise
    except Exception as e:
        _log(f"could not fetch tool catalog from {API_URL}: {e!r} "
             f"— is the platform API running?")
        raise
    return [
        types.Tool(
            name=t["name"],
            description=t.get("description") or "",
            inputSchema=t["input_schema"],
        )
        for t in catalog
    ] + [tool for tool, _fn in LOCAL_TOOLS.values()]


def _to_content(result) -> list[types.ContentBlock]:
    """Map an agent tool's return value to MCP content. Most tools return a JSON
    string; ``read_datasheet`` returns a list of {text|image} content blocks."""
    if isinstance(result, str):
        return [types.TextContent(type="text", text=result)]
    if isinstance(result, list):
        out: list[types.ContentBlock] = []
        for block in result:
            if not isinstance(block, dict):
                out.append(types.TextContent(type="text", text=str(block)))
                continue
            if block.get("type") == "text":
                out.append(types.TextContent(type="text", text=block.get("text", "")))
            elif block.get("type") == "image":
                src = block.get("source") or {}
                if src.get("type") == "base64":
                    out.append(types.ImageContent(
                        type="image",
                        data=src.get("data", ""),
                        mimeType=src.get("media_type", "image/png"),
                    ))
                else:
                    out.append(types.TextContent(type="text", text=json.dumps(block)))
            else:
                out.append(types.TextContent(type="text", text=json.dumps(block)))
        return out
    return [types.TextContent(type="text", text=json.dumps(result))]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[types.ContentBlock]:
    if name in LOCAL_TOOLS:
        _tool, fn = LOCAL_TOOLS[name]
        try:
            return [types.TextContent(type="text", text=await fn(arguments or {}))]
        except Exception as e:  # noqa: BLE001 — unreadable file, API down, …
            return [types.TextContent(type="text", text=f"Error calling {name!r}: {e!r}")]
    try:
        data = await _post(f"/api/agent/tools/{name}", arguments or {})
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:500]
        if e.response.status_code == 401:
            detail += f" — {_TOKEN_HELP}"
        return [types.TextContent(
            type="text",
            text=f"Error calling {name!r}: HTTP {e.response.status_code} — {detail}",
        )]
    except Exception as e:  # noqa: BLE001 — connection refused, timeout, etc.
        return [types.TextContent(
            type="text",
            text=f"Error calling {name!r}: {e!r}. Is the platform API running at {API_URL}?",
        )]
    return _to_content(data.get("result"))


async def _main() -> None:
    _log(f"starting; API_URL={API_URL} token from {TOKEN_SOURCE}")
    if not TOKEN:
        _log(f"no token — {_TOKEN_HELP}")
    async with stdio_server() as (read, write):
        await server.run(
            read,
            write,
            InitializationOptions(
                server_name="kicad-library",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    anyio.run(_main)
