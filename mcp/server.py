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

**One tool runs HERE rather than being proxied: ``upload_model3d``.** A 3D model
is a multi-megabyte STEP file sitting on the user's own disk, and the agent
surface takes JSON — proxying it would mean base64 in a tool call, which the
platform-side agent (which has no access to this machine's filesystem) could not
produce anyway. So this server reads the file locally and posts it as multipart
to ``/api/models3d/upload``. Keep local tools to that shape: something the API
genuinely cannot do because the bytes are here.

Transport: stdio (Claude Code spawns this process).

**`mcp` is pinned below 2.0 on purpose.** 2.0.0 removed the low-level
``Server.list_tools()`` / ``Server.call_tool()`` decorators this file is built
on, so an unpinned ``mcp>=1.2`` resolves to a version where the server dies at
import with ``'Server' object has no attribute 'list_tools'`` — and uv resolves
fresh on any cold start, so it breaks with no local change. Lift the pin only
together with a port to the 2.x API.

Environment:
  KICAD_API_URL    base URL of the platform API   (default: http://localhost:8020)
  KICAD_MCP_TOKEN  bearer token, if the API requires one (default: none / open)

Run standalone:  uv run --script mcp/server.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import anyio
import httpx
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

API_URL = os.environ.get("KICAD_API_URL", "http://localhost:8020").rstrip("/")
TOKEN = os.environ.get("KICAD_MCP_TOKEN", "").strip()

server = Server("kicad-library")


def _log(msg: str) -> None:
    # stdout is the MCP protocol channel — diagnostics MUST go to stderr.
    print(f"[kicad-mcp] {msg}", file=sys.stderr, flush=True)


def _headers() -> dict[str, str]:
    h = {"accept": "application/json"}
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


# name -> (schema, handler). Everything not in here is proxied to the API.
LOCAL_TOOLS = {UPLOAD_MODEL3D.name: (UPLOAD_MODEL3D, lambda a: _upload_model3d(a))}


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    try:
        catalog = await _get("/api/agent/tools")
    except Exception as e:  # noqa: BLE001
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
    _log(f"starting; API_URL={API_URL} auth={'yes' if TOKEN else 'no'}")
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
