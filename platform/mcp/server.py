# /// script
# requires-python = ">=3.11"
# dependencies = ["mcp>=1.2", "httpx>=0.27", "anyio>=4"]
# ///
"""KiCad library MCP server.

A thin, stateless client over the platform's ``/api/agent`` surface. It does NOT
touch the database or import any app code — it only speaks HTTP to the running
platform API. On start it fetches the tool catalog from ``GET /api/agent/tools``
and exposes each entry as an MCP tool; every call is proxied to
``POST /api/agent/tools/{name}``. Because the catalog and the tool logic live in
the API, this server automatically tracks whatever tools the platform offers.

Transport: stdio (Claude Code spawns this process).

Environment:
  KICAD_API_URL    base URL of the platform API   (default: http://localhost:8020)
  KICAD_MCP_TOKEN  bearer token, if the API requires one (default: none / open)

Run standalone:  uv run --script platform/mcp/server.py
"""
from __future__ import annotations

import json
import os
import sys

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
    ]


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
