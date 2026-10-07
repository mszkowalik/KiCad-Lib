# Agent tool surface and MCP server (`api/app/services/mcp_server`)

`server.py` is a stateless stdio client. It exposes the platform's agent
tools to Claude Code and other agents. The tools themselves are
`services/agent_tools.py::TOOLS`, dispatched by `routers/agent.py` —
see [docs/reference/agent-tools.md](../../../../docs/reference/agent-tools.md) for the
implementation. **The platform runs no agent of its own**: the in-app chat was
removed (decision 0062), and MCP is the only way an agent reaches the platform.

## Why it lives under `api/app`, and how an agent gets it

**Because the platform SERVES it**: `GET /api/agent/mcp-server` returns this
file, and the Account page's **Agents (MCP)** card (`web/src/components/McpSetupCard.tsx`)
hands the user a prompt that makes an agent download and register it. A
top-level `mcp/` is not in the api image — same reason as `pcm_plugin/` and
`bench_agent/`. The repo's `.mcp.json` runs this same file in place.

- **The token never enters the prompt or the agent's config.** A prompt is
  pasted into a chat, which the agent's vendor stores. The agent asks the user
  to save the token in `~/.config/kicad-library/token` (mode 600) from their
  own terminal, and `server.py` reads it there when `KICAD_MCP_TOKEN` is unset.
  The path is written in three places — `TOKEN_FILE` here, the card's prompt,
  and every user's disk — so moving it breaks existing installs.
- **Every command in the prompt was run end to end before it shipped** (macOS,
  zsh and bash, a scratch `HOME`, `claude mcp list` → Connected). Change one
  and run it again. Two traps it avoids: the token prompt is wrapped in
  `bash -c` because `read -p` means something else in zsh and fish has no
  subshell parentheses, and `claude mcp add` takes the server NAME before `-e`.
- **Inside this repo `claude mcp list` warns that `kicad-library` is defined
  twice** when the user also ran the prompt: the project entry and the user
  entry. Both reach the same platform with the same token.

## Agent capability policy (user directive, 2026-07)

- **Full read access to ALL platform data.** An agent must never be blind to
  data the platform holds — components, symbols, footprints, geometry, 3D
  models, datasheets (including archived PDF content), prices + history,
  stock, projects, snapshots, BOMs, production runs, notes, audit log. When a
  new table/service lands, add a matching read tool; withholding data
  from it is a bug, not a safety feature. An agent reads as its token's user:
  the audit log needs an admin's token, as Admin → Activity does (decisions
  0050, 0065).
- **An agent may view AND edit symbols, footprints and components — and its
  writes AUTO-PUBLISH** (user design 2026-08-23, superseding the draft gate).
  The `propose_*` tools keep their names but publish immediately through
  `services/publish.py`; accountability moved from the gate to the review
  axis (machine validation on every publish, verification records, the
  review queue). **Skill writes publish too** (2026-08-24): the argument for
  keeping that one gate — a bad skill steers every future agent run — lost to
  the fact that a skill is prose, its versions are immutable, and the undo is
  restoring the previous version from the Skills page. `propose_skill_update`
  says so in its own description, so the agent knows the write is live.
- The agent records verifications with `get_review_checklist` /
  `record_verification` and must be honest there: `skipped` when the
  documentation does not allow a check, `flagged` (note REQUIRED) when it
  verified an item and found it WRONG without fixing it, never `checked` on a
  guess. It can never overwrite an item a human answered, and `failed` is
  machine-only.
- Production sign-off stays human-only; `refresh_supply` re-fetches
  auto-managed LCSC/JLC data live (same domain the background refresher owns).


## The HTTP surface and the MCP server

One tool set (`services/agent_tools.py::TOOLS`; `GET /api/agent/tools` is the
live count), reached one way: `routers/agent.py` exposes it over HTTP and the
MCP server drives it under the agent's own subscription. Do not bring back an
in-platform agent loop — decision 0062 records why.

**`routers/agent.py` — dispatch, never reimplement.** `GET /api/agent/tools`
returns `[t.to_dict() for t in agent_tools.TOOLS]` (name + description + JSON
schema); `POST /api/agent/tools/{name}` looks the tool up in
`{t.name: t for t in TOOLS}` and runs `t.func(**json_body)` in a threadpool. The
`@beta_tool` objects are callable and carry `.name/.description/.input_schema/
.to_dict()/.func`, so **adding a tool to `TOOLS` exposes it over HTTP and to
Claude Code automatically** — never write per-tool routes. An agent brings its
own web tools.

**Auth:** a **personal API token** (`Authorization: Bearer <token>`), minted per
user on their own Account page (or by an admin on Admin → Users). The shared `settings.mcp_token` still works
while `AUTH_LEGACY_TOKENS` is on, scoped to `/api/agent/` only — see
"Authentication — default deny, one gate" in `api/CLAUDE.md`. Empty `mcp_token` plus `AUTH_ENABLED=false` is the
localhost-dev posture and nothing else.

**MCP server (`server.py`):** a stateless stdio client run via
`uv run --script` (self-contained PEP 723 deps: `mcp`, `httpx`). It imports NO
app code — it fetches the catalog from `/api/agent/tools` and proxies each call
to `/api/agent/tools/{name}`, needing only `KICAD_API_URL`
(default `http://localhost:8020`) and a token — `KICAD_MCP_TOKEN`, else the
token file (`KICAD_MCP_TOKEN_FILE` moves it).
`read_datasheet`'s list-of-content-blocks return (text + base64 PNG pages) is
converted to MCP image content; every other tool returns a JSON string as text.

- **`mcp` is pinned `>=1.2,<2`, and the pin is load-bearing.** mcp 2.0.0
  removed the low-level `Server.list_tools()` / `Server.call_tool()`
  decorators this file is built on, so the unpinned spec resolved to a version
  that died at import with `'Server' object has no attribute 'list_tools'`.
  `uv` resolves fresh on a cold start, so it would have broken with no local
  change (caught 2026-08-24). Lift the pin only with a port to the 2.x API.
- **Two tools are LOCAL, not proxied: `upload_model3d`, and
  `attach_invoice_file`, which files an invoice original from this disk with its
  supplier document (`/api/run-documents/{id}/attachment`).** `upload_model3d` (`LOCAL_TOOLS`, merged
  into the catalog in `list_tools` and dispatched before the proxy). A 3D model
  is a multi-megabyte file on the user's own disk; proxying it would mean
  base64 through a tool call, and the platform cannot read that filesystem. It reads the file locally and posts multipart to
  `/api/models3d/upload`, then returns the ready `(model …)` node. Its default
  `rel_path` rule duplicates `services/pcm_plugin/model_paths.suggest_rel_path`
  (this script imports no app code) — change both together. Keep local tools to
  that shape: something the API genuinely cannot do because the bytes are here.

**Claude Code wiring in this repo (`.mcp.json` at repo root):** a project-scoped
stdio entry `kicad-library` that runs this file via `uv`, with `KICAD_API_URL` /
`KICAD_MCP_TOKEN` from env (`${VAR:-default}` expansion keeps them out of git).
`KICAD_API_URL` defaults to the PUBLIC address, so the server works away from
the LAN as well as on it. **A token must reach the server** — the agent
surface is behind the auth gate, and no token gets 401 on every call.
**Here both values live in `.claude/settings.local.json` under `env`** — it is
gitignored and its `env` block reaches the Bash tool, so one file serves the MCP
server and any script. Never put the token in `.mcp.json` or in
`.claude/settings.json`; both are tracked.
- **A personal token starts with `7s_`** (`auth.TOKEN_PREFIX`). The 64-character
  hex secrets are the legacy shared `MCP_TOKEN` / `HTTPLIB_TOKEN`, which
  `_LEGACY_SCOPES` no longer honours on production — one stored in
  `settings.local.json` 401s on every agent call and reads as a dead MCP server
  rather than an expired credential. Check the prefix first.
- **Prefer the public `KICAD_API_URL`.** The LAN address (`http://192.168.200.28
  /lib`) reaches the SAME deployment, so it is not wrong, only fragile — it
  fails silently away from the LAN.
MCP config is OS-user-scoped, **not** tied to a Claude account, so it works
across both logins and survives account switches. (The pre-existing `kicad`
entry is a separate Node KiCad-IPC server — leave it.)

**Run it:** `docker compose up -d db` + the platform API (dev:
`uvicorn app.main:app` from `api`, or `docker compose up -d`), then open
the repo in Claude Code — the `kicad-library` server connects to the running API.
