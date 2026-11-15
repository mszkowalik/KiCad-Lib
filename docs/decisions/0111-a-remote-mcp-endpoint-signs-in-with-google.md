---
status: accepted
date: 2026-11-15
decision-makers: Mateusz Kowalik
consulted: the RaveAggregator agent session (it built the same sign-in for ra-mcp.disfunction.cc)
---

# Serve a remote MCP endpoint at `/mcp`, and sign it in with Google against an e-mail the admin set

## Context and Problem Statement

The only way an agent reached Henry was the stdio server in
`api/app/services/mcp_server/server.py`, a process on the user's own computer.
Claude on a phone runs no local process, so it could not reach Henry at all. A
remote MCP server is reached over Streamable HTTP and signs the user in with
OAuth 2.1, where the client registers itself (RFC 7591). The question is where
that endpoint runs, who issues its tokens, and how a token maps to a Henry
account.

## Decision Drivers

* The API is default-deny, and one gate decides what a caller may do
  (`authgate.py`, decision 0045). A second permission model drifts from it.
* Accounts are made by an admin. There is no sign-up and no password recovery.
* Every change an agent makes must be attributed to its user and undoable
  (decisions 0050, 0089).
* The user asked for Google sign-in on the phone.

## Considered Options

* A: `/mcp` inside henry-api. Henry is the OAuth authorization server, the
  login page federates to Google, and the Google e-mail must match the e-mail
  an admin wrote on the Henry account.
* B: the same, but the login page is Henry's own username and password.
* C: a separate `henry-mcp` container that proxies to the API, as `rave-mcp`
  does.
* D: point clients at Google as the authorization server directly.

## Decision Outcome

Chosen option: A, because the user chose Google sign-in, and running inside
henry-api keeps one gate and one tool catalog.

1. **`/mcp` is served by henry-api** with the MCP Python SDK's low-level
   `Server` (the same SDK as the stdio server, decision recorded in its
   `CLAUDE.md`). Its tool list is the stdio catalog without the two tools that
   read the user's own disk (`upload_model3d`, `attach_invoice_file`).
2. **A tool call goes through the normal API** at `/api/agent/tools/{name}` (and
   `/api/...` for `api_request`), in process, with the caller's own access
   token. The gate therefore applies the same role gates, company scope, audit
   rows and undo records as for a personal token. The remote server adds no
   permission check of its own.
3. **Henry is the authorization server.** The SDK serves `/authorize`,
   `/token`, `/register`, `/revoke` and the two `/.well-known/` documents at the
   root of `henry.disfunction.cc`. Clients, requests, codes and tokens are rows
   in Postgres (`oauth_*` tables). Tokens are opaque random strings, stored as
   SHA-256. An access token lives one hour. A refresh token lives 90 days and
   rotates on use.
4. **An OAuth access token is a Henry credential.** `auth.resolve_token`
   accepts it beside a personal token, as the user it was issued to, while that
   user is active and the token is neither expired nor revoked. Deactivating a
   user ends it, as it ends a session.
5. **Sign-in is Google OpenID Connect** (code flow, PKCE, nonce, scopes
   `openid email`). The ID token is checked against Google's keys (RS256, `iss`,
   `aud`, `exp`, `nonce`, `email_verified`). The verified e-mail must equal
   `users.email` of an active account. An admin writes that e-mail on
   Admin → Users. **An unknown e-mail is refused**: nothing is created, nobody
   waits for approval, because accounts are made by an admin.
6. **Registration accepts only the Claude apps' redirect URIs and a loopback
   address**, so a token can only be delivered to Claude or to a client on the
   user's own computer.
7. **The Google client ID and secret are environment settings**
   (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`). Without them the sign-in page
   says so and issues nothing. The redirect URI to register in Google Cloud is
   `<PUBLIC_BASE_URL>/oauth/google/callback`.

The stdio server stays. It is still the only way to use the two tools that read
the user's disk, and the desktop can use either.

### Consequences

* Good, because a phone reaches Henry with nothing installed.
* Good, because a remote call is governed, attributed and undone exactly like a
  stdio call.
* Bad, because Henry now depends on Google for this sign-in, and a Google
  outage stops new phone sign-ins (tokens already issued keep working).
* Bad, because the root paths `/authorize`, `/token`, `/register` and `/revoke`
  now belong to the API and not to the web app.
* Bad, because a database dump yields no token, but it yields every client
  registration and the e-mail of every account.

### Confirmation

* `api/tests/auth/test_mcp_oauth.py` covers the redirect-URI rule, the e-mail
  match, refusal of an unknown or inactive user, token expiry and rotation, and
  that an OAuth token reaches the API as its user.
* A real Claude connector completes the sign-in and lists the tools.

## Pros and Cons of the Options

### B: Henry's own login page

* Good, because it needs no Google client and no e-mail on the account.
* Bad, because the user asked for Google sign-in.

### C: a separate container

* Good, because it keeps the SDK's dependencies out of the API image.
* Bad, because there is no dependency conflict to avoid: henry-api runs
  FastAPI on Starlette 1.x, which mcp 2.x needs. RaveAggregator needed a
  container only because its FastAPI pinned Starlette below 0.42.
* Bad, because it adds a container, an nginx block and a second hop.

### D: Google as the authorization server

* Bad, because Google issues no tokens for a third-party resource and supports
  no dynamic client registration, so a Claude connector cannot register.

## More Information

* `api/app/services/mcp_server/CLAUDE.md` holds the rules for both servers.
* The RaveAggregator flow this follows: `~/Projects/RaveAggregator/backend/rave/mcp_auth.py`.
* Revisit when the SDK gains Client ID Metadata Documents and Claude prefers
  them over dynamic registration.
