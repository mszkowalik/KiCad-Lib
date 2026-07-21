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

| Path | Role |
|---|---|
| `app/main.py` | App factory, router registration, startup (datasheet autofetch) |
| `app/config.py` | `Settings` (pydantic-settings) — everything env-overridable; import `settings` |
| `app/db.py` | `Base`, `engine`, `SessionLocal`, `get_db` |
| `app/models.py` | SQLAlchemy models — the versioned schema |
| `app/routers/*.py` | HTTP endpoints — one `APIRouter(prefix="/api/…")` per file |
| `app/routers/util.py` | Shared router helpers (see table above) |
| `app/services/*.py` | Business logic (importer, generator, mirror, render, lcsc, jaravis, …) |
| `app/seed_skills/*.md` | Jaravis's seed convention docs (see the Jaravis section of the platform README) |
| `kiutils/` | **Vendored** KiCad-10-patched kiutils — never `pip install` a different one |

Routers stay thin (parse request → call a service/helper → shape the response).
Non-trivial logic and anything with side effects lives in `services/`.

## The versioning + proposal model (core invariant)

Read this before touching components, symbols, footprints, or skills.

- **Immutable version rows.** `ComponentVersion`, `SymbolVersion`,
  `FootprintVersion`, `SkillVersion` are append-only. You never mutate a live
  version in place — you create a new one.
- **`current_version_id`** on the parent (`Component`, `Symbol`, …) is a plain
  `Integer` (deliberately **not** a FK) pointing at the live version. `None`
  means "no published version yet" (e.g. a brand-new component that only has a
  draft). `current_version(comp)` resolves it.
- **`status` is a `String(20)`**, default `"published"`. The only live values:
  - `"draft"` — a proposal; **nothing is live**.
  - `"published"` — approved / live (also what the wipe-importer writes directly).
  - `"rejected"` — a killed draft (kept as a tombstone, never deleted).
  There is **no `"approved"` status** — approval flips `draft` → `published` and
  records identity in the separate `approved_by` column.
- **Approval is the single choke point** (`routers/proposals.py::approve`): it
  sets `status="published"`, `approved_by`, points `current_version_id` at the
  version, pins datasheets, and rebuilds the affected mirror libraries. Produce
  a **draft** and you get all of that for free — never hand-roll publishing.
- **Prices and datasheets are NOT properties.** They live in `component_prices`
  and `datasheets` (component-scoped, auto-managed). Keep them out of
  `ComponentProperty`; the price keys (`PRICE_KEY_TO_COL`) and `Datasheet*` keys
  are stripped on import and rejected by Jaravis's `_parse_properties`.
  **Prices are never emitted to KiCad** (user decision 2026-07): neither the
  generated mirror symbols nor the HTTP catalog carry `Price *` fields —
  `injected_props(datasheets)` injects datasheet links only. Pricing lives on
  the platform (BOMs, ladders, run economics).
- **Project manual cost data is commit-versioned** (`services/cost_state.py`).
  `ProjectCostItem` + `ProjectExtraBomItem` rows belong to an immutable
  `ProjectCostRevision` anchored at the git commit (snapshot) where it was
  created; edits made while viewing commit Y copy-on-write a new revision
  effective from Y **forward** — earlier snapshots keep the older list. Never
  query these item tables by `project_id` alone: go through
  `cost_state.items_for(db, project_id, snapshot)` (snapshot `None` = current
  list) and `cost_state.revision_for_edit` for mutations. Anchor sha `""` =
  "since the beginning" (startup-migration backfill of pre-versioning rows).
  Cost items carry optional quantity breaks (`steps` JSONB,
  `[{qty_from, price}]`, qty_from >= 2 — `price` is the qty-1 tier); price at
  a run volume resolves via `project_bom._cost_price_at`, mirroring the
  ComponentPricePoint qty_from convention.

### Creating a proposal (the one true pattern)

Mirror `services/jaravis.py`. New component: `Component(name=…)` with
`current_version_id` left `None`; `ComponentVersion(version_no=1,
status="draft", created_by=<actor>, comment=…)`; `ComponentProperty` rows with
`position`; `AuditLog(action="proposal.create", entity_type="component_version",
…)`. Edit: same, but `version_no = max(existing)+1`, carry
`removed_properties` forward, and **leave `current_version_id` untouched**. The
Proposals list keys purely off `status=="draft"`, so a well-formed draft shows
up in the UI automatically. Audit actions in use: `proposal.create`,
`proposal.approve`, `proposal.reject`, `import`.

## Jaravis capability policy (user directive, 2026-07)

- **Full read access to ALL platform data.** Jaravis must never be blind to
  data the platform holds — components, symbols, footprints, geometry, 3D
  models, datasheets (including archived PDF content), prices + history,
  stock, projects, snapshots, BOMs, production runs, notes, audit log. When a
  new table/service lands, add a matching Jaravis read tool; withholding data
  from it is a bug, not a safety feature.
- **Jaravis may view AND edit symbols and footprints** — not just reference
  them. Edits follow the same structural gate as components: its tools create
  `SymbolVersion`/`FootprintVersion` DRAFTS that the user approves in the
  Proposals view ("with user permission" = the approval gate, never bypassed).
- Writes of any kind stay draft-gated; read access is unrestricted. The only
  robot-owned exception: `refresh_supply` re-fetches auto-managed
  LCSC/JLC data live (same domain the background refresher owns).

### Jaravis implementation notes (`services/jaravis.py`)

- 26 client tools + 2 Anthropic **server tools** (`web_search_20260209`,
  `web_fetch_20260209` — plain dicts appended to the runner's tools list; they
  execute on Anthropic's side, no beta header, `max_uses` caps cost).
- **pause_turn**: the Python tool runner does NOT auto-resume a
  `stop_reason="pause_turn"` from a long server-tool turn — it silently
  truncates. The loop mirrors the conversation while iterating and restarts
  the runner with the paused turn appended (bounded). Keep that loop when
  touching the runner code.
- **The agent loop is a generator** (`run_chat_events`): it yields
  `note`/`tool` progress events per iteration plus a final `done`; long runs
  show live activity and a Stop button (client disconnect closes the generator
  → run ends at the next event). `run_chat` is the blocking drain kept for
  scripts. `MAX_ITERATIONS` (80) bounds model calls per turn — the runner
  stops silently when hit, so `run_chat_events` synthesizes a "stopped, say
  continue" reply.
- **Persisted chat is server-authoritative** (`JaravisSession` +
  `JaravisMessage`; the `messages` relationship cascades on delete). The DB —
  not the browser — holds the conversation, so it survives reloads and the user
  can keep several chats in parallel. Session titles auto-derive from the first
  user message. The stateless `POST /chat` + `POST /chat/stream` (full message
  array, store nothing) stay for scripts.
- **A turn runs in a BACKGROUND THREAD, decoupled from the HTTP client**, so a
  refresh / closed tab does NOT cancel it — this is the whole point of the
  persistence (a request-scoped run is cancelled on disconnect and its answer,
  and tokens, are lost). `start_session_run(sid, content)` spawns
  `_run_worker` (persists the user message BEFORE the long turn, replays only
  role+text to `run_chat_events`, persists the assistant reply — text+trace+
  proposals — the instant `done` is produced) and appends every event to an
  in-process `_Run.events` buffer under a `Condition`. `POST
  /sessions/{id}/chat/stream` starts the run then tails the buffer via
  `stream_run_events` (409 if one is already running); `GET
  /sessions/{id}/run/stream` re-attaches after a reload and replays the buffer
  from the start (204 when nothing is running — stored messages are then
  authoritative); `POST /sessions/{id}/run/cancel` sets `_Run.cancelled` so the
  worker breaks the loop at the next event boundary (the server-side Stop
  button; no assistant message is persisted for a cancelled turn). At most one
  active run per session; `_run_worker` removes itself from `_RUNS` on finish
  (subscribers keep their local ref and drain). The registry is **in-process
  and does NOT survive a restart** — a run in flight when uvicorn restarts
  (including a `--reload` from a code edit) is lost; the reloaded page then sees
  a dangling trailing user message and reconciles. Never yield while holding
  `_Run.cond`.
- **Per-turn proposals use a `ContextVar` (`_turn_proposals`), not a module
  global** — set to a fresh list at the start of each `run_chat_events` turn and
  read into the `done` event; `_record_proposal` appends. This isolates
  overlapping turns (background threads; two sessions at once) so drafts are
  never cross-attributed. Do not reintroduce a shared module-level list.
- `read_datasheet` returns a LIST of content blocks (text + base64 PNG page
  images rendered with **pymupdf**) — tool results may be
  `Iterable[BetaContent]`, not just str. pymupdf is a pyproject dependency.
- Geometry proposals: `propose_symbol_edit` / `propose_footprint_edit` accept
  full source, validate (kiutils/sexpr parse, footprint header must equal the
  name with NO prefix, 3D paths must start `${SEVENSIGMA_DIR}/3DModels/`;
  note the footprint node IS the sexpr tree root — reuse parse_cache's
  fallback). New names create the parent row with `current_version_id=None`,
  same as components.
- Approval lives in `routers/proposals.py`: `/symbols/{id}/approve|reject`,
  `/footprints/{id}/approve|reject`, plus
  `/{kind}s/{id}/preview.svg?which=draft|current` (kicad-cli render via the
  render container) for the before/after review in the Proposals UI. Symbol
  approve rebuilds the base lib + affected top-level libs
  (`update_mirror_symbols`); footprint approve writes the one `.kicad_mod`
  (`mirror.update_mirror_footprint`). The PCM packages pick the change up
  lazily via the manifest hash. Components keep their pinned
  `symbol_version_id`/`footprint_version_id`; the KiCad-facing base lib,
  footprint mirror, and HTTP catalog always follow the newest published
  geometry.

## Importing from YAML — two modes

`services/importer.py` runs as a background daemon thread (`IMPORT_STATE` +
`threading.Lock`; progress via `_stage(name)`; status polled at
`GET /api/import/status`). There are **two** ways to load `Sources/*.yaml`:

1. **Full import (`run_import`, `POST /api/import`)** — DESTRUCTIVE: wipes and
   reloads everything (categories, rules, base symbols, footprints, 3D models,
   components) writing rows directly as `published`. Skills and component notes
   survive. Use for first-time load / clean cutover / refreshing geometry.
   **Do not casually edit or "test" this — it drops the DB and cannot be run
   safely against real data.**
2. **Sync (`run_sync`, `POST /api/import/sync`)** — NON-DESTRUCTIVE: diffs each
   YAML component against the DB and creates **draft proposals** for new and
   changed components (reusing the proposal pattern above). It never wipes,
   never deletes, and touches nothing but the drafts it creates + audit rows.
   Scope and guarantees:
   - Diffs on versioned component data only: `base_component`, footprint
     **name**, `category_id`, `removed_properties`, and the ordered plain
     properties `(key, value, is_null)`. Prices, datasheets, and property
     visibility/layout are intentionally **not** part of the diff.
   - Resolves base symbols, footprints, and categories from what is **already
     in the DB**. A component that references a base symbol / footprint /
     category not present is **skipped and reported**, never invented — run a
     full import first to add geometry.
   - **Idempotent**: components equal to their live version are `unchanged`; if
     a matching draft already exists it is not duplicated. Re-running a sync
     over unchanged YAML must create zero proposals.
   - Components in the DB but absent from YAML are **reported** (`only_in_db`),
     never auto-deleted.

`_build_desired(...)` builds one component's desired state and mirrors
`run_import`'s per-component logic; if you change how a component is built from
YAML, keep both paths consistent.

## Projects module (git-tracked designs)

Services: `gitrepo` (bare mirrors at `DATA_DIR/git/<id>.git`, plain git CLI,
token injected per-invocation via `http.extraheader` — never written to disk),
`storage` (MinIO), `crypto` (Fernet from `SECRET_KEY`), `project_ingest`,
`project_render`, `project_bom`, `fx`, `ladder`. Routers: `projects.py`,
`production_runs.py`.

- **Snapshots are immutable, keyed by commit sha** — MinIO render caches
  (`projects/<id>/renders/<sha>/…`) never invalidate. Checkouts under
  `DATA_DIR/checkouts/<id>/<sha>/` are disposable (`gitrepo.materialize`
  recreates them); the render container sees them read-only at `/data/...`.
- **BOM extraction goes through kicad-cli** (`sch export bom`), never a manual
  schematic parse — KiCad resolves hierarchy, DNP, and variants. Matching:
  `${SYMBOL_NAME}` == `Component.name` first, then `LCSC Part`. Variant list
  comes from `.kicad_pro` → `schematic.variants` (KiCad 10; absent on 9).
- **`project_ops.py` exists twice** — `api/app/services/` and `render/`
  must stay byte-identical (same pattern as `render.py`/`server.py`).
- **NUL is illegal in argv**: git `--format` separators use `\x1f`, never `\x00`.
- **Price ladders — JLCPCB first, LCSC fallback** (user decision 2026-07-21):
  `component_price_points` rows with a source in `ladder.AUTO_SOURCES`
  (`"JLCPCB"`, `"LCSC"`) are replaced wholesale by the refresher — the JLCPCB
  assembly ladder comes from the official OpenAPI (`priceRanges` in the same
  batched `jlc.fetch_component_details` call that feeds `jlc_stock`, so it
  refreshes for every component on every run), the LCSC retail ladder from
  the per-component wmsc detail fetch. Other sources (`Manual`, …) are never
  touched by robots. `ladder.effective_points` DROPS LCSC points whenever the
  component has any JLCPCB points — LCSC appears only in place of a missing
  JLCPCB ladder, never alongside it. This applies to resolution
  (`price_at` — BOMs, run economics, valuations) AND to every display
  surface (the web ladder card, Jaravis/MCP `get_component` and
  `refresh_supply`); both ladders are still STORED, so the fallback stays
  available. Only raw price history shows complete point sets. The legacy 3-point `ComponentPrice` summary (browse-list price
  column + BOM fallback for ladder-less parts; NOT emitted to KiCad) is
  DERIVED from the preferred ladder on every refresh
  (`ladder._update_price_summary`, same @1/@100/@Bulk rules as
  `kicad_lib/pricing.py`; its `source` records which ladder) — unless its
  `source` is non-auto (e.g. `Manual`), which pins it. It has no UI card of
  its own; the component page's single pricing surface is the ladder card.
- **Three stock pools, never conflate them**: `ComponentSupply.stock` = LCSC
  retail (lcsc.com, `wmsc.lcsc.com` detail `stockNumber`);
  `ComponentSupply.jlc_stock` = JLCPCB assembly parts (jlcpcb.com/parts,
  official OpenAPI `getComponentDetailByCode` → `stockCount`, batched in
  `jlc.fetch_component_details`); `JlcStockItem.qty` = the user's private
  consigned JLC library. They routinely disagree (a part can be sold out on
  LCSC retail while JLCPCB holds 100k+ for assembly — e.g. C5440143). Any UI
  or tool surfacing a stock number must label the pool; availability checks
  treat a line as procurable when ANY pool covers it. The legacy 3-point `ComponentPrice` stays authoritative
  for KiCad symbol injection. **Two price stores, one bridge**: the BOM prices
  from the ladder, but when a part has no ladder points it falls back to its
  `ComponentPrice` summary (`project_bom._summary_points`) — that's how a price
  entered manually in the component's Prices editor (which writes the summary,
  not the ladder) reaches the BOM. Parts with neither remain unpriced.
- **BOM-only parts**: `Component.in_library=False` (column added by an
  idempotent `ALTER TABLE` in `main.py` startup — `create_all` never alters
  existing tables). Excluded in `mirror.write_symbol_libs` and both
  `kicad_http` part endpoints; needs no symbol/footprint.
- **Run economics are computed on READ, never stored**: `run_effective(db,
  run)` prices the run's BOM + costs from **historical pricing** at
  `run_pricing_date(run)` (the user-entered `run_date` as end-of-day UTC,
  else `created_at`) and applies `overrides` on top. History lives in
  `component_price_history` (append-only; one row = the component's complete
  point set as JSONB, appended by `ladder.record_price_history` whenever the
  set changes) and `exchange_rate_history` (same pattern, via
  `fx.record_rate_history`). Resolution rule everywhere: latest snapshot
  at-or-before the date, else the earliest after (the closest available);
  components with no history fall back to live points. Never mutate or
  delete history rows. `ProductionRun.frozen` is a LEGACY blob from the old
  freeze-at-creation model — kept for archival, never written or read.
- **Production files belong to RUNS, not snapshots** (`services/production.py`):
  versioned `ProductionFileSet`s (repo | upload | generated), auto-imported
  from the repo's `production/` dir (JLCPCB Fabrication Toolkit; skip
  `backups/`). The JLC `bom.csv` is the assembly SUBSET, never the total BOM.
  Gerber zips are stored extracted so the viewer can address layers; the
  viewer composites via `gerbv` (render image) in ONE call — per-file exports
  would each autoscale and misalign.
- **Click-maps** (`services/project_map.py`): hotspot geometry is parsed from
  the sch/pcb sources with `util/sexpr.py` (never kiutils — it chokes on new
  KiCad tokens), enriched with `SnapshotBomLine` matches, cached in MinIO as
  `map-v{MAP_VERSION}.json`. Bump `MAP_VERSION` on any format change. Bboxes
  are deliberately approximate (conservative corners, mirror-safe).
- **JLC private stock** (`services/jlc.py`): official OpenAPI at
  `open.jlcpcb.com`, endpoint `/overseas/openapi/component/getPrivateComponentLibrary`
  (paginated POST), auth = `JOP` header signed HMAC-SHA256 over
  `METHOD\npath\ntimestamp\nnonce\nbody\n`. Response field names are NOT
  publicly documented — `_parse_item` maps defensively and the raw payload is
  kept in `JlcStockItem.raw` (`GET /api/jlc/stock/item/{id}/raw`); extend the
  key lists there if a sync shows zeros. Sync replaces the table wholesale;
  `project_bom.stock_check` consumes private stock BEFORE market stock.
- **`services/jlc.py` wraps the FULL JLC API surface** (ported from the Vumo
  project's `scripts/jlc_openapi.py` / `scripts/jlcpcb.py`): official signed
  endpoints — `fetch_component_details` (batch detail by LCSC codes; source
  of `jlc_stock`), `get_component_infos`/`iter_component_infos` ("my
  components", lastKey cursor), `get_component_library_list`,
  `get_private_component_library`, `calculate_pcb`, `get_pcb_audit_info`,
  `get_pcb_wip_process`, `get_pcb_order_detail` — plus the anonymous parts
  search `search_parts(keyword)` (`+` = AND, MPNs stored unhyphenated) and
  `find_market_match(mpn, brand)` matching heuristics. Only sync + detail are
  router-wired today; reuse these wrappers instead of re-deriving endpoints.
- **Notes/runs/history are never revision-filtered** — they are project-scoped;
  `ProjectNote.sha`/`ref_name` and `ProductionRun.snapshot_id` only record
  the commit context they were created against.

## Conventions

- **Config**: read via `from ..config import settings`; add new knobs to
  `Settings` with an env-overridable default. Don't hardcode paths/URLs.
- **New seed-skill files** (`app/seed_skills/*.md`) must be listed in
  `[tool.setuptools.package-data]` in `pyproject.toml` so they ship in the
  non-editable Docker install.
- **Lint**: Ruff, line length 120, target py311 (`[tool.ruff]` in `pyproject.toml`).
- **kiutils**: always the vendored `api/kiutils/` (KiCad-10 patch). Never depend
  on an upstream build.
- **`db.expire_all()` before any post-commit mirror refresh.** The session uses
  `expire_on_commit=False`, and services create new versions via `db.add()`
  without appending to already-loaded relationships — so after calling a
  service that commits (e.g. `add_component_file`), a preloaded `comp.versions`
  is stale and `current_version(comp)` returns None, silently skipping
  `update_mirror_symbols`. Precedents: `create_version`, `proposals.approve`,
  `components.add_file`.
- **KiCad PCM/plugin gotchas** (`services/pcm.py`, `services/pcm_plugin/`):
  package identifiers allow NO underscores (dots/dashes only) but KiCad
  replaces dots with underscores for install directories; `license` must be
  a value from the schema enum (`unrestricted` for in-house); python-runtime
  IPC plugins REQUIRE a `requirements.txt` or env setup silently aborts and
  the toolbar button never appears; validate generated metadata against
  `go.kicad.org/pcm/schemas/v1` and the plugin manifest against KiCad's
  shipped `api.v1.schema.json` before shipping. The library package ships
  ONLY the deduplicated `7Sigma_Base.kicad_sym` (written by
  `mirror.write_symbol_libs`) + footprints — HTTP-catalog parts reference
  base drawings (`symbolIdStr = HTTPLIB_SYMBOL_LIB:<base_component>`), so
  adding components must never bump the library package. 3D model updates
  flow as LZMA deltas (`POST /api/kicad/pcm/models-delta`).
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

## Agent tool surface + MCP server (Claude Code)

The library agent is reachable two ways over the **same** tool set
(`services/jaravis.py::TOOLS` — 26 client tools):

1. **In-app Jaravis** — the Anthropic tool-runner chat (`services/jaravis.py`,
   `routers/jaravis.py`). Burns Anthropic API tokens; has the web chat UI.
2. **MCP / Claude Code** — `routers/agent.py` exposes the identical tools over
   HTTP so an external MCP server drives them under a Claude Code subscription
   (no per-token API metering). This is the primary entry point going forward;
   Jaravis's chat loop is kept but superseded (do not delete it yet).

**`routers/agent.py` — dispatch, never reimplement.** `GET /api/agent/tools`
returns `[t.to_dict() for t in jaravis.TOOLS]` (name + description + JSON
schema); `POST /api/agent/tools/{name}` looks the tool up in
`{t.name: t for t in TOOLS}` and runs `t.func(**json_body)` in a threadpool. The
`@beta_tool` objects are callable and carry `.name/.description/.input_schema/
.to_dict()/.func`, so **adding a tool to `TOOLS` exposes it over HTTP and to
Claude Code automatically** — never write per-tool routes. Anthropic server
tools (`web_search`/`web_fetch`, in `SERVER_TOOLS`) are intentionally NOT
exposed — Claude Code brings its own web tools.

**Auth:** `settings.mcp_token` (env `MCP_TOKEN`), checked as
`Authorization: Bearer <token>`. Empty = open (fine on localhost); set it before
the platform is reachable remotely, since these endpoints can create drafts.

**MCP server (`mcp/server.py`):** a stateless stdio client run via
`uv run --script` (self-contained PEP 723 deps: `mcp`, `httpx`). It imports NO
app code — it fetches the catalog from `/api/agent/tools` and proxies each call
to `/api/agent/tools/{name}`, needing only `KICAD_API_URL`
(default `http://localhost:8020`) + optional `KICAD_MCP_TOKEN`.
`read_datasheet`'s list-of-content-blocks return (text + base64 PNG pages) is
converted to MCP image content; every other tool returns a JSON string as text.

**Claude Code wiring (`.mcp.json` at repo root):** a project-scoped stdio entry
`kicad-library` that runs the server via `uv`, with `KICAD_API_URL` /
`KICAD_MCP_TOKEN` from env (`${VAR:-default}` expansion keeps them out of git).
MCP config is OS-user-scoped, **not** tied to a Claude account, so it works
across both logins and survives account switches. (The pre-existing `kicad`
entry is a separate Node KiCad-IPC server — leave it.)

**Run it:** `docker compose up -d db` + the platform API (dev:
`uvicorn app.main:app` from `api`, or `docker compose up -d`), then open
the repo in Claude Code — the `kicad-library` server connects to the running API.
