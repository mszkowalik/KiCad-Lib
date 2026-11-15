# The remote MCP endpoint and its sign-in

Code: `api/app/services/mcp_remote.py`. Decision: [0111](../decisions/0111-a-remote-mcp-endpoint-signs-in-with-google.md). The stdio server it reuses: `api/app/services/mcp_server/CLAUDE.md`.

Claude on a phone runs no local process, so henry-api also serves the tools
at `https://henry.disfunction.cc/mcp` (Streamable HTTP, stateless, JSON
responses), with Henry as its own OAuth server. The rules, and why:

- **The remote server runs the stdio server's handlers** (`mcp_server/server.py`). It sets `server.CALLER` to
  the caller's token and an in-process `httpx.ASGITransport`, then calls
  `list_tools` / `call_tool`. So a remote call goes through `/api/agent/tools`
  and the gate exactly as a stdio call does — role checks, company scope, the
  `mcp` client tag, undo. Never give the remote server its own tool code or
  its own permission check. That is also why `_get`, `_post` and `api_request`
  build their client with `_client()`: a new HTTP call here must too, or it
  silently goes to `API_URL` with no token when it runs remotely.
- **`upload_model3d` and `attach_invoice_file` hand out an upload ticket
  remotely** (decision
  [0112](../decisions/0112-a-remote-agent-uploads-a-file-with-a-one-use-ticket.md)).
  The file is on the agent's computer, so the tool returns a `curl` command
  with a `7u_` ticket: one request, one method and path, ten minutes, as the
  user. The agent's shell sends it to the normal route. The remote versions
  are `REMOTE_DISK_TOOLS`; the stdio ones still read the file themselves.
  A ticket goes in the `Authorization` header only, never in a query string.
- **An OAuth access token is a Henry credential.** `auth.resolve_token` falls
  back to `oauth_tokens`, so the in-process call carries the same bearer.
  Access 1 h, refresh 90 days, rotated on use, both stored as SHA-256.
  Deactivating a user, a password reset, "Sign out" and a changed e-mail all
  revoke them.
- **Sign-in is Google, and the e-mail must match `users.email`**, set on
  Admin → Users. An unknown e-mail is refused and nothing is created —
  accounts are made by an admin. The Google client is `GOOGLE_CLIENT_ID` /
  `GOOGLE_CLIENT_SECRET`; its redirect URI is
  `<PUBLIC_BASE_URL>/oauth/google/callback`.
- **The SDK owns the root paths** `/authorize`, `/token`, `/register`,
  `/revoke`, `/.well-known/oauth-*`; the sign-in pages are `/oauth/*`. Three
  lists name them and must agree: `mcp_remote.PATHS` with `authgate._OPEN_PREFIXES`,
  `web/default.conf.template`, and `apiPaths` in `web/vite.config.ts`. The
  gate lists them as OPEN because the SDK refuses `/mcp` itself, with the
  RFC 9728 `WWW-Authenticate` header a connector needs to find the sign-in.
- **Registration accepts only the Claude apps' redirect URIs and loopback.**
  A public client (`token_endpoint_auth_method: none`) is accepted.
- **`/revoke` does not work for a public client** (mcp 2.3.0 asks it for a
  `client_secret`; verified 2026-11-15). Disconnecting a connector therefore
  leaves its refresh token alive until it expires or the user is signed out
  everywhere on Admin → Users.
- **A request that names no RFC 8707 `resource` gets a token for `/mcp`**, so
  `validate_token_resource=True` still holds for it.
