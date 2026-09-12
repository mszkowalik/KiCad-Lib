# Platform API (`api`)

FastAPI backend for the Project Management Platform. Postgres is the **source of
truth**; the file mirror under `DATA_DIR/mirror` (served at `/files`) is a
disposable projection. This codebase originally copied logic from the YAML
pipeline's `kicad_lib/` (now retired to the `archive/yaml-library` branch)
but never imports it.

## Reuse first — do not reinvent

Before adding a helper, model, status string, or endpoint pattern, **find the
existing one and reuse it**. This codebase already has a settled vocabulary;
new parallel implementations are the main thing to avoid.

| Need | Reuse (don't recreate) |
|---|---|
| Category full path / descendant ids | `routers/util.py` → `category_path`, `category_and_descendant_ids` |
| A component's live version | `routers/util.py` → `current_version(comp)` |
| Properties as a dict | `routers/util.py` → `props_dict(cv)` |
| Resolve a `{Template}` value | `routers/util.py` → `resolved_value(value, props)` (wraps `services/templates.py`) |
| Write an audit row | `routers/util.py` → `audit(db, action, entity_type, entity_id, details=…, actor=…)` |
| DB session in a route | `Depends(get_db)` from `db.py` |
| Price key → column map | `services/generator.py` → `PRICE_KEY_TO_COL` |
| Create a draft proposal | the pattern in `services/jaravis.py` (`propose_new_component` / `propose_component_edit`) |
| Expose an agent capability over HTTP | `routers/agent.py` dispatches `services/jaravis.py::TOOLS` by name — add a tool there and it's exposed to the MCP server automatically; never hand-write a per-tool agent route |
| S-expr parsing / symbol+footprint parse cache | `util/sexpr.py`, `services/parse_cache.py` |
| Free-form notes on ANY entity | the generic `comments` table (`M.Comment`, `target_type`+`target_id`) via `routers/comments.py` — never add a per-entity comment table |

If a helper is *almost* right, extend it in place rather than forking a near-copy.

## Layout

| Path | Role | Its own rules |
|---|---|---|
| `app/main.py` | App factory, router registration, startup (datasheet autofetch) | — |
| `app/config.py` | `Settings` (pydantic-settings) — everything env-overridable; import `settings` | — |
| `app/db.py` | `Base`, `engine`, `SessionLocal`, `get_db` | — |
| `app/models.py` | SQLAlchemy models — the versioned schema | — |
| `app/routers/*.py` | HTTP endpoints — one `APIRouter(prefix="/api/…")` per file | `app/routers/CLAUDE.md` |
| `app/routers/util.py` | Shared router helpers (see the table above) | — |
| `app/services/*.py` | Business logic (importer, generator, mirror, render, lcsc, jaravis, …) | `app/services/CLAUDE.md` |
| `app/services/fieldsolver/` | 2D quasi-TEM field solver | `app/services/fieldsolver/CLAUDE.md` |
| `app/services/flasher/` | Production programming | `app/services/flasher/CLAUDE.md` |
| `app/services/pcm_plugin/` | Source of the KiCad sync plugin | `app/services/pcm_plugin/CLAUDE.md` |
| `app/seed_skills/*.md` | Jaravis's seed convention docs | — |
| `kiutils/` | **Vendored** KiCad-10-patched kiutils — never `pip install` a different one | — |

Routers stay thin (parse request → call a service/helper → shape the response).
Non-trivial logic and anything with side effects lives in `services/`.

**The deep rules live beside the code they govern.** A CLAUDE.md in a
subdirectory is read when you open a file in it, so this file holds only what
applies to the whole backend. `app/services/CLAUDE.md` carries the publish
invariant and a table that routes every backend topic — datasheets, production
economics, the review axis, projects, simulation models — to its document under
[docs/reference/](../docs/reference/).

**The one invariant to know before you touch anything versioned**: every publish
goes through `services/publish.py`, and a path that bypasses it silently loses
the datasheet pins, the sign-off carry, the review-record carry and the machine
check. `app/services/CLAUDE.md` states it in full.


## Conventions

- **Never run a script inside the api container as a *file*.** The image does
  `pip install .`, so a **stale copy of the whole `app` package** sits in
  `site-packages` (`kicadlib_platform_api-0.1.0.dist-info`), frozen at image
  build time. Running `docker compose exec api python /tmp/x.py` puts the
  script's own directory on `sys.path` — `/srv` is not on it — so `import app`
  resolves to that stale copy, silently executing yesterday's code against
  today's database. Verified 2026-07-28: the installed `models.py` was 1345
  lines against the live 1550, missing `JlcOrderDecision` entirely. It fails
  loudly on a *missing* attribute and silently on a *changed* one.
  Pipe via stdin instead — `docker compose exec -T api python - <<'PY'` — which
  sets `sys.path[0] = ''` and picks up the live mount at `/srv/app`. Assert it
  when the script writes money: `assert M.__file__ == "/srv/app/models.py"`.
- **Config**: read via `from ..config import settings`; add new knobs to
  `Settings` with an env-overridable default. Don't hardcode paths/URLs.
- **New seed-skill files** (`app/seed_skills/*.md`) must be listed in
  `[tool.setuptools.package-data]` in `pyproject.toml` so they ship in the
  non-editable Docker install.
- **`Footprint_Name` belongs to the footprint, not the component.**
  `Footprint.display_name` (unversioned) holds the short package name;
  `generator.footprint_name_props()` injects it **ahead of** the component's own
  properties, so a component that still carries its own row overrides it. Never
  re-add it as a per-component property. Because the name is baked into generated
  `ki_description` values, changing it rebuilds the symbol libraries of every
  category using that footprint — not the `.kicad_mod`.

  Three doors, one body in `services/publish.py::set_footprint_package_name`:
  `PATCH /api/footprints/{id}` (Templates browser), the
  `set_footprint_package_name` agent tool, and the Templates UI itself. Keep them
  going through the service — the audit row records `previous` as well as the new
  value, and it is the ONLY revert path for an unversioned field.

  **A brand-new footprint has no `display_name`**, so the first component to
  reference it publishes with an `unresolved template {Footprint_Name}` mirror
  warning. That is the default outcome of pairing a new component with a new
  footprint, not an edge case — which is why the agent tool exists.
- **Template resolution is order-independent.** `apply_properties` resolves
  `{Key}` against the *final* property set. It used to resolve against the
  properties applied so far, so a `ki_description` positioned before the
  property it referenced emitted a spurious "unresolved template" warning. Only
  safe while no property value references another property that is itself a
  template — check before introducing nesting.
- **`Skill.description` is unversioned** — it is a when-to-use label on the
  skill, not part of the document, so it lives on `Skill` (not `SkillVersion`)
  and is written through `PATCH /api/skills/{id}`, which never mints a version.
  Keep it a single line: it is what an agent reads to decide whether to open the
  document (Jaravis's system prompt header, and the `description` frontmatter of
  the mirrored Claude Code skill — see the root `CLAUDE.md`).
- **Lint**: Ruff, line length 120, target py311 (`[tool.ruff]` in `pyproject.toml`).
- **kiutils**: always the vendored `api/kiutils/` (KiCad-10 patch). Never depend
  on an upstream build.
- **Comments are one generic table** (`M.Comment`: `target_type` ∈
  {`component`,`symbol`,`footprint`} + `target_id`), NOT per-entity. Component,
  symbol and footprint notes all flow through `routers/comments.py`
  (`GET/POST /api/{components|symbols|footprints}/{id}/comments`, generic
  `DELETE /api/comments/{id}`). The legacy `component_comments` table is drained
  into `comments` by a one-time idempotent startup migration in `main.py` and is
  never written again. When a new commentable entity appears, add a
  `target_type` + URL pair — don't fork a table. Jaravis surfaces these as
  `user_notes` (via `_user_notes(db, target_type, id)`) on every read tool
  (full-read policy), so new comment targets get a matching read.
- When a non-obvious backend convention or workaround emerges, record it here.


## Authentication — default deny, one gate

The platform is reachable from the internet. Before this landed it was
**publicly readable and writable**: `https://disfunction.cc/lib/` answered for
anyone, including `/api/settings`, `/api/proposals`, `/api/invoices` and the
whole `/files` mirror. The compose comment claiming "LAN only" was wrong —
the published port restricts direct LAN access, but `cloudflared` reaches
`kicadlib-web` by container name on the shared docker network.

- **`app/authgate.py::AuthGate` is the ONE gate, and it denies by default.**
  Adding a router does not require thinking about auth — it is covered the
  moment it is mounted. Never re-open a hole with a per-route exemption; the
  only exemptions live in `_OPEN_PATHS` / `_OPEN_PREFIXES` there, and each one
  carries its reason.
- **It is pure ASGI, not `BaseHTTPMiddleware`, and that is load-bearing.**
  `BaseHTTPMiddleware` never runs for a WebSocket, so the flasher run socket
  would have been left open; and it wraps responses in an anyio task pair,
  which is the shape that breaks Jaravis's long NDJSON streams. Pure ASGI also
  covers `app.mount("/files", StaticFiles(...))`, which a router dependency
  cannot reach at all — that mount is exactly what was publicly readable.
- **Middleware order is the reverse of reading order.** `add_middleware`
  prepends, so CORS is registered AFTER the gate to end up OUTSIDE it. Get this
  backwards and the gate's 401 leaves the stack with no CORS headers, and a
  cross-origin dev browser reports an opaque network failure instead of the 401
  it can act on.
- **Four credentials, and `?t=` is scoped on purpose.** Session cookie,
  `Authorization: Bearer`, `Authorization: Token` (KiCad's fixed format), and a
  `t` query parameter allowed ONLY on `_QUERY_TOKEN_PATHS`. KiCad's Plugin and
  Content Manager sends no headers of any kind, so a query parameter is the only
  credential it can carry — and a token in a URL lands in the nginx and
  Cloudflare access logs, which is why the list is three entries and not a
  global fallback.
- **An open path still resolves identity.** `/api/auth/me` must be reachable
  signed out AND report who you are when signed in. The gate therefore refuses
  only non-open paths, rather than skipping resolution for open ones — the first
  version skipped it and `me` reported `user: null` for a signed-in browser.
  It still short-circuits when NO credential is present, so a liveness probe
  never touches Postgres.
- **Tokens are verified against a SHA-256 digest, not a password hash.** The
  secret is 32 random bytes, so there is nothing to brute-force, and this check
  sits on the KiCad symbol chooser's critical path (one request per category on
  every chooser open) where argon2 would add ~100 ms a call. Passwords, which
  are low-entropy, get argon2id. Do not "harmonise" these.
- **`ApiToken` stores the secret TWICE and both copies are needed.**
  `token_hash` verifies; `token_enc` (Fernet, `services/crypto.py`) lets the
  Setup page show a user their token again months later. User decision
  2026-07-31: the token is baked into a personal PCM repository URL, so
  show-once would mean a rotation and a KiCad re-install every time somebody
  loses the link. Consequence to keep in mind: a database dump plus SECRET_KEY
  yields every token, and changing SECRET_KEY makes them unreadable (still
  verifiable — the fix is a rotation).
- **Legacy shared tokens are SCOPED, not global.** `httplib_token` still opens
  `/kicad/v1`, `/files/` and `/api/kicad/`; `mcp_token` still opens
  `/api/agent/`. Granting either globally would have turned the KiCad library
  token — which lives in the clear in every user's `.kicad_httplib` — into a
  master key. Turn both off with `AUTH_LEGACY_TOKENS=false` once every client
  carries a personal token.
- **`require_token` / `_require_auth` in `kicad_http.py` and `agent.py` are
  now fallbacks, not the gate.** They accept `request.state.user` first. Do not
  tighten either back to an equality test against the shared token: that is
  precisely what rejected every per-user `.kicad_httplib`.
- **The first admin comes from `ADMIN_PASSWORD`, and only into an EMPTY users
  table** (`auth.bootstrap_admin`). It must run, or a fresh deployment can
  never be signed into; it must never run twice, or the environment could
  silently reset a live account. A deployment with auth on and no admin logs a
  warning naming the problem.
- **No registration endpoint and no password-reset endpoint exist** (user
  decision 2026-07-31). An admin creates accounts and resets passwords in
  `routers/users.py`. Do not add either — the login page has no link to them, so
  an endpoint would be a way in that the UI does not admit to.
- **A password change or reset ends every session** for that user, and
  deactivating or deleting one does the same. A reset that leaves live sessions
  has not reset anything.
- **Two self-lockout guards in `routers/users.py`**: an admin cannot remove
  their own admin role, deactivate themselves, or delete themselves, and the
  last active admin cannot be demoted or deactivated by anyone. Either would
  leave the platform recoverable only by editing the database.

