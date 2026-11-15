"""The remote MCP endpoint at `/mcp`, with its OAuth sign-in (decision 0111).

Claude on a phone runs no local process, so it cannot start the stdio server
in `mcp_server/server.py`. This module serves the SAME tools over Streamable
HTTP from henry-api, and is its own OAuth 2.1 authorization server:

- The MCP SDK serves `/authorize`, `/token`, `/register`, `/revoke` and the two
  `/.well-known/` documents. This module stores clients, requests, codes and
  tokens in the `oauth_*` tables, hashed, and adds the sign-in pages under
  `/oauth/`.
- `/authorize` sends the browser to `/oauth/login`, which sends it to Google
  (OpenID Connect, code flow, PKCE, nonce). The verified Google e-mail must be
  the `users.email` an admin wrote on an ACTIVE account. An unknown e-mail is
  refused and nothing is created: accounts are made by an admin.
- An access token is a Henry credential (`auth.resolve_token` accepts it), so
  a tool call goes through the normal API in process, through the same gate,
  role checks, company scope, audit rows and undo records as a personal token.
  The handlers are the stdio server's own, run with `server.CALLER` set.
- The two tools that send a file from the user's disk hand out a one-use
  upload ticket instead (decision 0112), which the agent's shell sends.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import logging
import secrets
import time
import urllib.parse
from datetime import timedelta

import anyio
import httpx
from mcp import types
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    ProviderTokenVerifier,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
from mcp.server.lowlevel import Server
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from .. import models as M
from ..config import settings
from ..db import SessionLocal
from . import auth
from .mcp_server import server as stdio

log = logging.getLogger(__name__)

SCOPE = "henry"
ACCESS_TTL = 3600
REFRESH_TTL = 90 * 86400
CODE_TTL = 300
REQUEST_TTL = 900
# A token is only ever delivered to the Claude apps or to a client on the
# user's own computer.
CLAUDE_REDIRECTS = ("https://claude.ai/api/mcp/auth_callback", "https://claude.com/api/mcp/auth_callback")
DISK_TOOLS = frozenset({"upload_model3d", "attach_invoice_file"})

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")


def _base() -> str:
    return settings.public_base_url.rstrip("/")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def redirect_allowed(uri) -> bool:
    u = str(uri)
    if u in CLAUDE_REDIRECTS:
        return True
    p = urllib.parse.urlsplit(u)
    return p.scheme == "http" and p.hostname in ("localhost", "127.0.0.1", "::1")


def _db(fn):
    """Run `fn(db)` in a worker thread with its own session, committed."""
    def run():
        db = SessionLocal()
        try:
            out = fn(db)
            db.commit()
            return out
        finally:
            db.close()
    return anyio.to_thread.run_sync(run)


def _active_user(db, user_id) -> M.User | None:
    user = db.get(M.User, int(user_id)) if str(user_id or "").isdigit() else None
    return user if user is not None and user.active else None


# --------------------------------------------------------------- the provider

class Provider:
    """The SDK's `OAuthAuthorizationServerProvider`, stored in Postgres. The
    `subject` of every code and token is the Henry user id as a string."""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = await _db(lambda db: db.get(M.OAuthClient, client_id))
        return OAuthClientInformationFull.model_validate(row.info) if row else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        bad = [str(u) for u in (client_info.redirect_uris or []) if not redirect_allowed(u)]
        if bad or not client_info.redirect_uris:
            raise RegistrationError("invalid_redirect_uri",
                                    f"redirect URI not allowed: {', '.join(bad) or 'none given'}")
        info = json.loads(client_info.model_dump_json())

        def put(db):
            row = db.get(M.OAuthClient, client_info.client_id)
            if row is None:
                db.add(M.OAuthClient(client_id=client_info.client_id, info=info))
            else:
                row.info = info
        await _db(put)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if not redirect_allowed(params.redirect_uri):
            raise AuthorizeError("invalid_request", "redirect URI not allowed")
        rid = secrets.token_urlsafe(24)
        data = json.loads(params.model_dump_json())
        await _db(lambda db: db.add(M.OAuthRequest(id=rid, client_id=client.client_id, params=data)))
        return f"{_base()}/oauth/login?{urllib.parse.urlencode({'req': rid})}"

    async def load_authorization_code(self, client, authorization_code: str) -> AuthorizationCode | None:
        def get(db):
            row = db.get(M.OAuthCode, _digest(authorization_code))
            if row is None or row.client_id != client.client_id or row.used_at is not None:
                return None
            if auth._aware(row.expires_at) <= auth.utcnow():
                return None
            return row.data
        data = await _db(get)
        return AuthorizationCode.model_validate(data) if data else None

    def _issue(self, db, client_id: str, scopes: list[str], resource, user_id) -> OAuthToken:
        if _active_user(db, user_id) is None:
            raise TokenError("invalid_grant", "the account is not active")
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        ha, hr = _digest(access), _digest(refresh)
        now = auth.utcnow()
        for h, kind, pair, ttl in ((ha, "access", hr, ACCESS_TTL), (hr, "refresh", ha, REFRESH_TTL)):
            db.add(M.OAuthToken(token_hash=h, kind=kind, client_id=client_id, user_id=int(user_id),
                                scopes=list(scopes), resource=str(resource) if resource else None,
                                pair=pair, expires_at=now + timedelta(seconds=ttl)))
        return OAuthToken(access_token=access, expires_in=ACCESS_TTL, scope=" ".join(scopes),
                          refresh_token=refresh)

    async def exchange_authorization_code(self, client, authorization_code: AuthorizationCode) -> OAuthToken:
        def run(db):
            row = db.get(M.OAuthCode, _digest(authorization_code.code), with_for_update=True)
            if row is None or row.used_at is not None:
                raise TokenError("invalid_grant", "the code was already used")
            row.used_at = auth.utcnow()
            return self._issue(db, client.client_id, authorization_code.scopes, authorization_code.resource,
                               row.user_id)
        return await _db(run)

    async def load_refresh_token(self, client, refresh_token: str) -> RefreshToken | None:
        def get(db):
            row = db.get(M.OAuthToken, _digest(refresh_token))
            if (row is None or row.kind != "refresh" or row.client_id != client.client_id
                    or row.revoked_at is not None or auth._aware(row.expires_at) <= auth.utcnow()):
                return None
            return RefreshToken(token=refresh_token, client_id=client.client_id, scopes=list(row.scopes or []),
                                expires_at=int(auth._aware(row.expires_at).timestamp()),
                                resource=row.resource, subject=str(row.user_id))
        return await _db(get)

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        def run(db):
            row = db.get(M.OAuthToken, _digest(refresh_token.token), with_for_update=True)
            if row is None or row.kind != "refresh" or row.revoked_at is not None:
                raise TokenError("invalid_grant", "the refresh token is not valid")
            now = auth.utcnow()
            row.revoked_at = now
            pair = db.get(M.OAuthToken, row.pair)
            if pair is not None and pair.revoked_at is None:
                pair.revoked_at = now
            return self._issue(db, client.client_id, scopes or refresh_token.scopes, refresh_token.resource,
                               row.user_id)
        return await _db(run)

    async def load_access_token(self, token: str) -> AccessToken | None:
        def get(db):
            row = db.get(M.OAuthToken, _digest(token))
            if (row is None or row.kind != "access" or row.revoked_at is not None
                    or auth._aware(row.expires_at) <= auth.utcnow() or _active_user(db, row.user_id) is None):
                return None
            return AccessToken(token=token, client_id=row.client_id, scopes=list(row.scopes or []),
                               expires_at=int(auth._aware(row.expires_at).timestamp()),
                               resource=row.resource, subject=str(row.user_id))
        return await _db(get)

    async def revoke_token(self, token) -> None:
        def run(db):
            row = db.get(M.OAuthToken, _digest(token.token))
            if row is None:
                return
            now = auth.utcnow()
            row.revoked_at = row.revoked_at or now
            pair = db.get(M.OAuthToken, row.pair) if row.pair else None
            if pair is not None:
                pair.revoked_at = pair.revoked_at or now
        await _db(run)

    async def exchange_identity_assertion(self, *args, **kwargs):
        raise TokenError("unsupported_grant_type", "not supported")


PROVIDER = Provider()


def grant(db, rid: str, user: M.User) -> str | None:
    """The user signed in: turn the waiting request into a code. Returns the
    URL to send the browser back to, or None when the request is gone."""
    req = db.get(M.OAuthRequest, rid, with_for_update=True)
    if req is None or req.used_at is not None or _expired(req):
        return None
    req.used_at = auth.utcnow()
    p = AuthorizationParams.model_validate(req.params)
    code = secrets.token_urlsafe(32)
    ac = AuthorizationCode(code=code, scopes=p.scopes or [SCOPE], expires_at=time.time() + CODE_TTL,
                           client_id=req.client_id, code_challenge=p.code_challenge, redirect_uri=p.redirect_uri,
                           redirect_uri_provided_explicitly=p.redirect_uri_provided_explicitly,
                           # A client that names no resource (RFC 8707) gets a token for this
                           # one, the only resource here, so the audience check still holds.
                           resource=p.resource or f"{_base()}/mcp", subject=str(user.id))
    db.add(M.OAuthCode(code_hash=_digest(code), client_id=req.client_id, user_id=user.id,
                       data=json.loads(ac.model_dump_json()),
                       expires_at=auth.utcnow() + timedelta(seconds=CODE_TTL)))
    return construct_redirect_uri(str(p.redirect_uri), code=code, state=p.state)


def _expired(req: M.OAuthRequest) -> bool:
    return auth.utcnow() - auth._aware(req.created_at) > timedelta(seconds=REQUEST_TTL)


def user_for_email(db, email: str) -> M.User | None:
    """The ACTIVE account whose e-mail an admin set to this one, or None."""
    e = (email or "").strip().lower()
    if not e:
        return None
    from sqlalchemy import func
    user = db.query(M.User).filter(func.lower(M.User.email) == e).first()
    return user if user is not None and user.active else None


# --------------------------------------------------------------- Google sign-in

_JWKS = None


def verify_id_token(token: str, client_id: str, nonce: str) -> dict:
    """The claims of a Google ID token, checked as Google documents it.
    Raises ValueError (or a PyJWT error) when any check fails."""
    import jwt

    global _JWKS
    if _JWKS is None:
        _JWKS = jwt.PyJWKClient(GOOGLE_JWKS, cache_keys=True, lifespan=6 * 3600)
    key = _JWKS.get_signing_key_from_jwt(token)
    claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=client_id,
                        options={"require": ["exp", "iss", "aud"]})
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise ValueError("wrong token issuer")
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise ValueError("nonce does not match")
    if claims.get("email_verified") is not True or not claims.get("email"):
        raise ValueError("Google has not verified this e-mail")
    return claims


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


_STYLE = """<style>
:root{--bg:#f6f7f9;--card:#fff;--fg:#14171c;--muted:#5b6472;--line:#d5dae1;--accent:#1f6feb;--accent-fg:#fff;--bad:#b42318}
@media (prefers-color-scheme: dark){:root{--bg:#0d1015;--card:#161a21;--fg:#e7eaee;--muted:#9aa3b1;--line:#2c323c;
--accent:#4c8dff;--accent-fg:#0d1015;--bad:#ff7b72}}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--fg);
font:16px/1.45 system-ui,sans-serif}
.box{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:24px;
width:min(380px,calc(100vw - 32px));box-sizing:border-box;display:flex;flex-direction:column;gap:12px}
h1{font-size:1.15rem;margin:0}p{margin:0;color:var(--muted);font-size:.92rem}
a.btn{display:block;text-align:center;border-radius:8px;padding:10px;font-weight:600;text-decoration:none}
.ok{background:var(--accent);color:var(--accent-fg)}.no{color:var(--muted);border:1px solid var(--line)}
.bad{color:var(--bad)}</style>"""


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
        f'content="width=device-width, initial-scale=1"><title>{html.escape(title)}</title>{_STYLE}</head>'
        f'<body><div class="box"><h1>{html.escape(title)}</h1>{body}</div></body></html>',
        status_code=status, headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"})


_EXPIRED = "<p>Start connecting again in the Claude app.</p>"


def _callback() -> str:
    return f"{_base()}/oauth/google/callback"


async def login(request: Request) -> Response:
    rid = request.query_params.get("req", "")

    def get(db):
        req = db.get(M.OAuthRequest, rid) if rid else None
        if req is None or req.used_at is not None or _expired(req):
            return None
        client = db.get(M.OAuthClient, req.client_id)
        return (client.info or {}).get("client_name") if client else None, True
    found = await _db(get)
    if not found:
        return _page("The request has expired", _EXPIRED, 400)
    if not (settings.google_client_id and settings.google_client_secret):
        return _page("Sign-in is not set up",
                     '<p class="bad">GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are not set on this server.</p>', 503)
    name = html.escape(found[0] or "An application")
    q = urllib.parse.quote(rid)
    return _page("Connect to Henry",
                 f"<p><b>{name}</b> asks to use Henry's agent tools as you. Sign in with the Google "
                 f"account an administrator linked to your Henry account.</p>"
                 f'<a class="btn ok" href="/oauth/google/start?req={q}">Sign in with Google</a>'
                 f'<a class="btn no" href="/oauth/deny?req={q}">Deny</a>')


async def deny(request: Request) -> Response:
    rid = request.query_params.get("req", "")

    def run(db):
        req = db.get(M.OAuthRequest, rid, with_for_update=True) if rid else None
        if req is None or req.used_at is not None:
            return None
        req.used_at = auth.utcnow()
        p = AuthorizationParams.model_validate(req.params)
        return construct_redirect_uri(str(p.redirect_uri), error="access_denied", state=p.state)
    url = await _db(run)
    return RedirectResponse(url, 303) if url else _page("The request has expired", _EXPIRED, 400)


async def google_start(request: Request) -> Response:
    rid = request.query_params.get("req", "")
    if not (settings.google_client_id and settings.google_client_secret):
        return _page("Sign-in is not set up", "<p>Ask an administrator.</p>", 503)
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)

    def run(db):
        req = db.get(M.OAuthRequest, rid, with_for_update=True) if rid else None
        if req is None or req.used_at is not None or _expired(req):
            return False
        req.google_state, req.google_nonce, req.google_verifier = state, nonce, verifier
        return True
    if not await _db(run):
        return _page("The request has expired", _EXPIRED, 400)
    q = dict(client_id=settings.google_client_id, redirect_uri=_callback(), response_type="code",
             scope="openid email", state=state, nonce=nonce, prompt="select_account",
             code_challenge=_b64u(hashlib.sha256(verifier.encode()).digest()), code_challenge_method="S256")
    return RedirectResponse(f"{GOOGLE_AUTH}?{urllib.parse.urlencode(q)}", 303)


async def google_callback(request: Request) -> Response:
    state, code = request.query_params.get("state", ""), request.query_params.get("code", "")

    def take(db):
        req = (db.query(M.OAuthRequest).filter(M.OAuthRequest.google_state == state).with_for_update().first()
               if state else None)
        if req is None or req.used_at is not None or _expired(req):
            return None
        out = (req.id, req.google_nonce, req.google_verifier)
        req.google_state = None  # the Google leg is used once
        return out
    flow = await _db(take)
    if not flow or not code:
        return _page("Sign-in was interrupted", _EXPIRED, 400)
    rid, nonce, verifier = flow
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(GOOGLE_TOKEN, data=dict(
                code=code, client_id=settings.google_client_id, client_secret=settings.google_client_secret,
                redirect_uri=_callback(), grant_type="authorization_code", code_verifier=verifier))
            r.raise_for_status()
        claims = await anyio.to_thread.run_sync(verify_id_token, r.json()["id_token"],
                                                settings.google_client_id, nonce)
    except Exception as e:  # noqa: BLE001 — any failure of the Google leg ends the sign-in, with its reason
        log.warning("remote MCP Google sign-in failed: %r", e)
        return _page("Sign-in failed", f'<p class="bad">{html.escape(type(e).__name__)}: '
                                       f'{html.escape(str(e))[:200]}</p>', 400)
    email = str(claims["email"]).strip().lower()

    def finish(db):
        user = user_for_email(db, email)
        if user is None:
            return None, False
        return grant(db, rid, user), True
    url, known = await _db(finish)
    if not known:
        return _page("No Henry account", f"<p>{html.escape(email)}</p><p>No active Henry account carries this "
                                         "e-mail. An administrator sets it on Admin → Users.</p>", 403)
    return RedirectResponse(url, 303) if url else _page("The request has expired", _EXPIRED, 400)


# --------------------------------------------------------------- the MCP server

def _transport() -> httpx.AsyncBaseTransport:
    from ..main import app  # this module is imported by main.py
    return httpx.ASGITransport(app=app)


def _as_caller():
    tok = get_access_token()
    return stdio.CALLER.set((tok.token if tok else "", _transport()))


# --------------------------------------------- the disk tools, remotely (0112)
#
# The stdio server reads the file itself. Here the file is on the agent's
# computer and the server cannot reach it, so the tool hands out a one-use
# upload ticket (`auth.mint_upload_ticket`) and the exact `curl` command the
# agent runs in its own shell. The upload then goes through the normal route,
# gate and audit as the user. An agent with no shell (a phone) cannot use it.

_SHELL_NOTE = ("Run the command in your own shell, with the file path filled in, within 10 minutes. The ticket "
               "works once and only for this upload. Without a shell (Claude on a phone), upload the file in "
               "the Henry web app instead.")

REMOTE_UPLOAD_MODEL3D = types.Tool(
    name="upload_model3d",
    description=(
        "Store a 3D model (STEP/WRL) in the library, so a footprint can reference it as "
        "${SEVENSIGMA_DIR}/3DModels/<rel_path>. Use it before proposing a footprint whose (model ...) points "
        "anywhere else. Re-uploading the same rel_path REPLACES the file. This remote tool does not read the "
        "file: it returns a one-use `curl` command that uploads it from your computer, and the ready "
        "(model ...) node. " + _SHELL_NOTE),
    inputSchema={
        "type": "object",
        "properties": {
            "filename": {"type": "string", "description": "The file's name, e.g. 'SOIC-8.step'."},
            "rel_path": {"type": "string",
                         "description": "Where it goes under 3DModels/, e.g. "
                                        "'Package_SO.3dshapes/SOIC-8_3.9x4.9mm_P1.27mm.step'. Defaults to "
                                        f"'{stdio.HOUSE_DIR}/<filename>'. Use the source folder's name when "
                                        "the file sits in a *.3dshapes folder."},
        },
        "required": ["filename"],
        "additionalProperties": False,
    },
)

REMOTE_ATTACH_INVOICE_FILE = types.Tool(
    name="attach_invoice_file",
    description=(
        "File the original of a supplier invoice (PDF, KSeF XML or a scan) with its supplier document, so the "
        "money and its evidence sit together. Use it after create_supplier_invoice or import_ksef_invoice. "
        "This remote tool does not read the file: it returns a one-use `curl` command that uploads it from "
        "your computer. " + _SHELL_NOTE),
    inputSchema={
        "type": "object",
        "properties": {"document_id": {"type": "integer", "description": "The supplier document's id."}},
        "required": ["document_id"],
        "additionalProperties": False,
    },
)


def _ticket(user_id: int, method: str, path: str) -> str:
    def run(db):
        user = _active_user(db, user_id)
        if user is None:
            raise PermissionError("the account is not active")
        return auth.mint_upload_ticket(db, user, method, path)
    return run


def _curl(ticket: str, url: str) -> str:
    return (f"curl -sS -H 'Authorization: Bearer {ticket}' -H 'X-Kicad-Client: mcp' "
            f"-F 'file=@<PATH TO THE FILE>' '{url}'")


async def _remote_upload_model3d(user_id: int, args: dict) -> str:
    filename = str(args.get("filename") or "").strip().rsplit("/", 1)[-1]
    if not filename:
        return "filename is required."
    if not filename.lower().endswith(stdio.MODEL_SUFFIXES):
        return f"{filename}: a 3D model must be one of {', '.join(stdio.MODEL_SUFFIXES)}."
    rel = str(args.get("rel_path") or "").strip().lstrip("/") or f"{stdio.HOUSE_DIR}/{filename}"
    if ".." in rel.split("/") or "'" in rel:
        return f"rel_path {rel!r} must not contain '..' or a quote."
    path = "/api/models3d/upload"
    ticket = await _db(_ticket(user_id, "POST", path))
    url = f"{_base()}{path}?{urllib.parse.urlencode({'rel_path': rel})}"
    return json.dumps({
        "command": _curl(ticket, url),
        "rel_path": rel,
        "model_node": (f'(model "${{SEVENSIGMA_DIR}}/3DModels/{rel}"\n  (offset (xyz 0 0 0))\n'
                       "  (scale (xyz 1 1 1))\n  (rotate (xyz 0 0 0))\n)"),
        "note": _SHELL_NOTE,
    }, indent=1)


async def _remote_attach_invoice_file(user_id: int, args: dict) -> str:
    try:
        doc = int(args.get("document_id") or 0)
    except (TypeError, ValueError):
        doc = 0
    if doc <= 0:
        return "document_id is required."
    path = f"/api/run-documents/{doc}/attachment"
    ticket = await _db(_ticket(user_id, "POST", path))
    return json.dumps({
        "command": _curl(ticket, _base() + path),
        "accepts": list(stdio.ATTACH_SUFFIXES),
        "note": _SHELL_NOTE,
    }, indent=1)


REMOTE_DISK_TOOLS = {REMOTE_UPLOAD_MODEL3D.name: (REMOTE_UPLOAD_MODEL3D, _remote_upload_model3d),
                     REMOTE_ATTACH_INVOICE_FILE.name: (REMOTE_ATTACH_INVOICE_FILE, _remote_attach_invoice_file)}
assert set(REMOTE_DISK_TOOLS) == DISK_TOOLS


async def list_tools(ctx, params) -> types.ListToolsResult:
    reset = _as_caller()
    try:
        result = await stdio.list_tools(ctx, params)
    finally:
        stdio.CALLER.reset(reset)
    return types.ListToolsResult(tools=[t for t in result.tools if t.name not in DISK_TOOLS]
                                 + [tool for tool, _fn in REMOTE_DISK_TOOLS.values()])


async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
    if params.name in REMOTE_DISK_TOOLS:
        tok = get_access_token()
        if tok is None or not str(tok.subject or "").isdigit():
            return stdio._error("no signed-in user on this request")
        _tool, fn = REMOTE_DISK_TOOLS[params.name]
        try:
            text = await fn(int(tok.subject), params.arguments or {})
        except Exception as e:  # noqa: BLE001 — an inactive account, the database
            return stdio._error(f"Error calling {params.name!r}: {e!r}")
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)])
    reset = _as_caller()
    try:
        return await stdio.call_tool(ctx, params)
    finally:
        stdio.CALLER.reset(reset)


SERVER = Server("henry", version=stdio.SERVER_VERSION, title="Henry",
                instructions="The agent tools of the Henry platform (7Sigma's component library, production "
                             "and orders). Every write is live and recorded under your account.",
                on_list_tools=list_tools, on_call_tool=call_tool)

# The paths this app answers. `authgate._OPEN_PREFIXES` lists them, because
# the SDK refuses /mcp itself, with the RFC 9728 header a client needs.
PATHS = ("/mcp", "/.well-known/oauth-", "/authorize", "/token", "/register", "/revoke", "/oauth/")


def build_app():
    """The Starlette app with /mcp, the SDK's OAuth routes and the sign-in pages."""
    base = _base()
    host = urllib.parse.urlsplit(base).netloc
    hosts = sorted({host, "localhost:*", "127.0.0.1:*", "api:*", "henry-api:*"})
    return SERVER.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=hosts,
            allowed_origins=[base, "https://claude.ai", "https://claude.com"]),
        auth=AuthSettings(
            issuer_url=base, resource_server_url=f"{base}/mcp", required_scopes=[SCOPE],
            validate_token_resource=True,
            client_registration_options=ClientRegistrationOptions(enabled=True, valid_scopes=[SCOPE],
                                                                  default_scopes=[SCOPE]),
            revocation_options=RevocationOptions(enabled=True)),
        token_verifier=ProviderTokenVerifier(PROVIDER),
        auth_server_provider=PROVIDER,
        custom_starlette_routes=[
            Route("/oauth/login", login, methods=["GET"]),
            Route("/oauth/deny", deny, methods=["GET"]),
            Route("/oauth/google/start", google_start, methods=["GET"]),
            Route("/oauth/google/callback", google_callback, methods=["GET"]),
        ],
    )
