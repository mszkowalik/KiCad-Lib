"""The default-deny authentication gate.

ONE place decides whether a request may proceed. That is not a style choice:
the API is 25 routers plus a static mount, it can approve proposals, rewrite
production cost records and drive the agent, and it is reachable from the
internet. A per-route dependency would eventually miss a route, and the miss
would be silent.

**Pure ASGI, not `BaseHTTPMiddleware`**, for two reasons:

1. It sees the `websocket` scope, so the flasher run socket
   (`/api/flasher/ws/{run}`) is gated here instead of needing its own check.
   `BaseHTTPMiddleware` never runs for a WebSocket.
2. Jaravis streams turns as long-lived NDJSON responses and the flasher engine
   holds a socket open for minutes. `BaseHTTPMiddleware` wraps every response
   in an anyio task pair, which is exactly the shape that has historically
   broken streaming and cancellation.

It also covers `app.mount("/files", StaticFiles(...))`, which router-level
dependencies cannot reach at all — that mount is the file mirror, and it was
publicly readable before this landed.

Credentials, in the order tried:

1. `Cookie: <session_cookie_name>` — the browser.
2. `Authorization: Bearer <token>` — the MCP server and the sync plugin.
3. `Authorization: Token <token>` — KiCad's HTTP library, whose header format
   is fixed by KiCad and is not Bearer.
4. `?t=<token>` — **only** on the paths in `_QUERY_TOKEN_PATHS`. KiCad's Plugin
   and Content Manager sends no headers at all, so a personal repository URL is
   the only way to authenticate it. A token in a query string reaches the nginx
   and Cloudflare access logs, which is why the exception is a short list and
   not a global fallback.
"""
from __future__ import annotations

import logging

from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import settings
from .db import SessionLocal
from .services import auth

log = logging.getLogger(__name__)

# Reachable with no credential at all. Keep this list short and justified.
_OPEN_PATHS = (
    "/api/health",            # liveness — also /api/health/schema
    "/api/auth/login",        # the way in
    "/api/auth/logout",       # must work with a dead cookie
    "/api/auth/me",           # the SPA asks "am I signed in?" and gets user: null
)

# Deliberately unauthenticated, documented in api/CLAUDE.md: the DEVICE fetches
# these with Tasmota's `UrlFetch`, which sends no auth headers. Published
# versions only, and the handler enforces that.
_OPEN_PREFIXES = (
    "/api/flasher/files/",
)

# Paths where `?t=<token>` is accepted, because the client cannot send headers.
_QUERY_TOKEN_PATHS = (
    "/api/kicad/pcm/",         # PCM repository.json, packages.json, the zips
    "/api/kicad/httplib-file",  # the .kicad_httplib download link
    "/files/",                 # the file mirror the sync plugin reads
)

# What each PRE-AUTH shared secret may still reach while `auth_legacy_tokens`
# is on. Scoped to exactly what it opened before per-user tokens existed — a
# global grant would have turned the KiCad library token into a master key.
_LEGACY_SCOPES = (
    ("httplib_token", ("/kicad/v1", "/files/", "/api/kicad/")),
    ("mcp_token", ("/api/agent/",)),
)


def _is_open(path: str) -> bool:
    # startswith on the exact paths too, so /api/health/schema rides along with
    # /api/health without needing its own entry.
    return path.startswith(_OPEN_PATHS) or path.startswith(_OPEN_PREFIXES)


def _query_token_allowed(path: str) -> bool:
    return path.startswith(_QUERY_TOKEN_PATHS)


def _bearer(headers: Headers) -> str:
    """The token out of an Authorization header, either scheme, or ""."""
    value = headers.get("authorization", "")
    for scheme in ("Bearer ", "Token "):
        if value.startswith(scheme):
            return value[len(scheme):].strip()
    return ""


def _query_param(scope: Scope, name: str) -> str:
    raw = scope.get("query_string", b"").decode("latin-1")
    for part in raw.split("&"):
        key, _, value = part.partition("=")
        if key == name:
            from urllib.parse import unquote_plus

            return unquote_plus(value)
    return ""


def _legacy_grants(token: str, path: str) -> bool:
    if not settings.auth_legacy_tokens or not token:
        return False
    for field, prefixes in _LEGACY_SCOPES:
        configured = getattr(settings, field, "")
        if configured and token == configured and path.startswith(prefixes):
            return True
    return False


def _resolve(path: str, cookie_token: str, header_token: str, query_token: str):
    """Runs in a worker thread — every branch here touches the database.

    Returns `(user, allowed)`. A legacy shared token yields `(None, True)`: it
    authenticates a machine, never a person, so it carries no admin rights and
    nothing can attribute a write to it.
    """
    db = SessionLocal()
    try:
        if cookie_token:
            user = auth.resolve_session(db, cookie_token)
            if user is not None:
                return user, True
        for candidate in (header_token, query_token):
            if not candidate:
                continue
            user = auth.resolve_token(db, candidate)
            if user is not None:
                return user, True
            if _legacy_grants(candidate, path):
                return None, True
        return None, False
    finally:
        db.close()


class AuthGate:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        state = scope.setdefault("state", {})
        state["user"] = None

        if not settings.auth_enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "")

        # CORS preflight carries no credentials by definition; refusing it
        # would turn every cross-origin call into an opaque browser error
        # instead of the 401 the client can act on.
        if method == "OPTIONS":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        cookies = headers.get("cookie", "")
        cookie_token = ""
        for chunk in cookies.split(";"):
            name, _, value = chunk.strip().partition("=")
            if name == settings.session_cookie_name:
                cookie_token = value
                break

        header_token = _bearer(headers)
        query_token = _query_param(scope, "t") if _query_token_allowed(path) else ""

        open_path = _is_open(path)
        if not (cookie_token or header_token or query_token):
            # Nothing to check. An open path proceeds anonymously; anything else
            # is refused without touching the database, which is what keeps a
            # liveness probe and an unauthenticated flood off Postgres.
            if open_path:
                await self.app(scope, receive, send)
                return
            await self._refuse(scope, receive, send, path)
            return

        user, allowed = await run_in_threadpool(
            _resolve, path, cookie_token, header_token, query_token
        )
        # An open path is never refused, but it still gets the identity when one
        # is presented — `/api/auth/me` is exactly that case: reachable while
        # signed out, and it must answer "who am I" when signed in.
        if not allowed and not open_path:
            await self._refuse(scope, receive, send, path)
            return

        state["user"] = user
        await self.app(scope, receive, send)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send, path: str) -> None:
        if scope["type"] == "websocket":
            # 1008 = policy violation. The socket must be refused before the
            # handler accepts it, or the client sees a connection that opens
            # and then dies for no stated reason.
            await send({"type": "websocket.close", "code": 1008})
            return
        response = JSONResponse(
            {"detail": "authentication required"},
            status_code=401,
            # Tells a CLI client which schemes exist. KiCad ignores it.
            headers={"WWW-Authenticate": "Bearer"},
        )
        await response(scope, receive, send)
