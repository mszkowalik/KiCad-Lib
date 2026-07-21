# Project Management Platform

Postgres-backed web platform for the 7Sigma KiCad component library: browse and
edit components with full version history, live part catalog inside KiCad via
an HTTP library, SVG previews rendered by `kicad-cli`, and (coming phases) an
approval-gated agent — **Jaravis** — for adding and fixing components.

This directory is a **fresh codebase** — it copies logic from `kicad_lib/` but
never imports or modifies it. The existing YAML pipeline in the repo root keeps
working unchanged while both systems coexist.

## Quick start (Docker)

```bash
cd platform
cp .env.example .env          # optional: change HTTPLIB_TOKEN
docker compose up --build
```

| Service | URL | What |
|---|---|---|
| web | http://localhost:5173 | Browse UI (React) |
| api | http://localhost:8020 | REST API + docs at `/docs` |
| api mirror | http://localhost:8020/files/ | Published-state file mirror (static) |
| KiCad HTTP lib | http://localhost:8020/kicad/v1/ | Token-authenticated part catalog |
| render | http://localhost:8100 | kicad-cli render service (previews + project exports) |
| db | localhost:5434 | Postgres 16 (user/pass/db: `kicadlib`) — 5433 is taken by the ze_router_ztp deployment |
| minio | localhost:9000 (console :9001) | Object storage: project snapshots, cached renders, run attachments |

Then open the web UI → **Import** → type `IMPORT` → run. This **wipes the
database** and reloads everything from the repo working tree (mounted read-only
at `/repo`): `Sources/*.yaml`, base symbols, footprints, 3D models, plus rules
(seeded from the validator) and Jaravis skills (the convention docs in
`api/app/seed_skills/`).
Re-run whenever you want a fresh copy — there is never a merge. The last import
you ever run is the clean cutover from the YAML repo.

## Dev mode (API on the Mac, no containers except db)

```bash
cd platform && docker compose up -d db
cd api && python3 -m venv .venv && .venv/bin/pip install -e .
REPO_DIR=../.. DATA_DIR=./data RENDER_MODE=local \
  .venv/bin/uvicorn app.main:app --reload --port 8020
```

`RENDER_MODE=local` uses the desktop KiCad's `kicad-cli` directly
(`KICAD_CLI`, default `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`).

Frontend: `cd web && npm install && npm run dev`.

## Hooking up KiCad

1. **Plugin install (recommended)** — the platform serves a **PCM repository**
   (`/api/kicad/pcm/repository.json`, built by `services/pcm.py` from the file
   mirror). Add the URL in KiCad → Plugin and Content Manager → Manage
   Repositories, then install **7Sigma Library** (the DEDUPLICATED
   `7Sigma_Base.kicad_sym` — only the unique base drawings — plus footprints;
   registered as `PCM_7Sigma_Base` / `PCM_7Sigma`), **7Sigma 3D Models** and
   **7Sigma Library Sync** (an IPC action plugin — source in
   `services/pcm_plugin/` — that adds a toolbar button to the PCB AND
   schematic editors which pulls updates in place; changed 3D models come as
   an LZMA delta via `POST /api/kicad/pcm/models-delta`, never the full
   package; note KiCad requires `requirements.txt` in python plugins). The
   packages are rewritten to be self-consistent (footprint refs →
   `PCM_7Sigma:`, 3D paths →
   `${KICAD10_3RD_PARTY}/3dmodels/com_sevensigma_models3d/`). Each package is
   versioned from its own content, so adding components changes NOTHING here
   — parts flow through the live catalog.
2. **Live catalog** — add `clients/7Sigma.kicad_httplib` to your KiCad symbol
   library table (Preferences → Manage Symbol Libraries → add, type will be
   detected from the file). Token must match `HTTPLIB_TOKEN` (default
   `dev-token`). Parts become searchable in the chooser with live fields;
   each part's `symbolIdStr` references its BASE drawing
   (`PCM_7Sigma_Base:<base>`, override lib nickname via `HTTPLIB_SYMBOL_LIB`)
   and footprints are remapped to `FOOTPRINT_LIB_NICKNAME` (default
   `PCM_7Sigma`). This is THE way to place parts — new components appear here
   instantly with no client-side update at all.
3. **CLI sync (alternative)** — `python3 kicadlib.py sync` mirrors
   `http://localhost:8020/files/` (`Symbols/*.kicad_sym` +
   `Footprints/7Sigma.pretty/` + `3DModels/`) locally with unprefixed
   nicknames; see the KiCad page in the web UI for the steps.

## Configuration (env)

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://kicadlib:kicadlib@127.0.0.1:5434/kicadlib` | Postgres |
| `REPO_DIR` | `/repo` | Library repo root (import source) |
| `DATA_DIR` | `./data` | Mirror + render cache |
| `RENDER_MODE` | `http` | `http` (render container) / `local` (kicad-cli) |
| `RENDER_URL` | `http://localhost:8100` | Render service |
| `KICAD_CLI` | mac app path | Used when `RENDER_MODE=local` |
| `HTTPLIB_TOKEN` | `dev-token` | KiCad HTTP library auth token |
| `SYMBOL_LIB_NICKNAME_TEMPLATE` | `{category}` | How `symbolIdStr` is built |
| `MINIO_ENDPOINT` | `127.0.0.1:9000` | MinIO (compose: `minio:9000`) |
| `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` | `kicadlib` / `kicadlib-secret` | MinIO credentials |
| `MINIO_BUCKET` | `kicadlib` | Bucket for project artifacts |
| `SECRET_KEY` | `dev-secret-change-me` | Encrypts stored git tokens (change it; changing later invalidates stored tokens) |
| `DEFAULT_CURRENCY` | `USD` | Display currency when a project has no override |
| `FX_AUTOFETCH` | `true` | Daily ECB exchange-rate refresh |
| `PRICE_LADDER_AUTOFETCH` | `true` | Refresh stale LCSC ladders on startup |
| `PRICE_LADDER_MAX_AGE_DAYS` | `30` | Ladder staleness threshold |
| `JLC_APP_ID` / `JLC_ACCESS_KEY` / `JLC_SECRET_KEY` | — | JLCPCB OpenAPI credentials (private parts library) |

## Architecture notes

- **DB is the source of truth**; the file mirror (`DATA_DIR/mirror`, served at
  `/files`) is a disposable, rebuildable projection of published state.
- **Versioning**: symbols, footprints and component data version independently
  (immutable rows); a component version pins exact symbol/footprint version
  FKs. Categories are a tree; a component's category is part of its versioned
  data. Top-level categories map 1:1 to generated `.kicad_sym` files.
- **kiutils + KiCad 10**: the stock fork can't parse KiCad-10-saved symbols
  (`(in_pos_files ...)`, `(hide yes)`, `(duplicate_pin_numbers_are_jumpers ...)`).
  The KiCad-10-patched kiutils is **vendored** at `api/kiutils/` (copied from
  the repo venv where the root-CLAUDE.md patch was applied), so Docker builds
  and reinstalls can never lose the fix.
- **Templates**: `{Property}` values resolve via safe substitution
  (`app/services/templates.py`) — replaces the legacy raw-eval f-strings.
- **Prices & datasheets are not properties**: they live in their own tables
  (`component_prices`, `datasheets` — auto-managed/component-scoped, multiple
  datasheets per part with optional locally stored copies) and are re-injected
  into generated symbols and the HTTP catalog, so KiCad output is unchanged.
- **Previews**: symbols render with the `Skyline-7S` theme, footprints with
  KiCad Default (both dark); the theme JSON is baked into the render image
  from `render/themes/`. Footprint 3D is a server-rendered board GLB shown
  with `<model-viewer>`. **Project renders follow the same settings**:
  schematic pages use `SYMBOL_THEME`, board layer SVGs use `FOOTPRINT_THEME`
  — the theme is part of the MinIO cache key, so changing a theme re-renders
  instead of serving stale colors.
- **File viewer** (`/view?src=…&name=…`): opens datasheet/model files the
  browser can't render natively. STEP/IGES parse in-browser via
  occt-import-js wasm (copied to `web/public/occt/` by
  `web/scripts/copy-occt.mjs`, gitignored), 3MF/WRL via three.js loaders —
  all with a structure tree whose checkboxes toggle subelement visibility.
  DXF renders with `dxf-viewer` (per-layer visibility toggles; Roboto in
  `web/public/fonts/` supplies text outlines). DWG is converted server-side
  by LibreDWG's `dwg2dxf` (`/api/view/dwg2dxf`; capability reported by
  `/api/view/capabilities` — `brew install libredwg` for dev, the Docker
  image builds it from source). PDFs keep plain links (native browser
  viewer); unknown types get a download card. Links route through
  `web/src/viewkind.ts:fileHref`, which only sends same-origin files to the
  viewer.
- **File uploads**: any file can be attached to a component from the
  "Datasheets & files" card — "＋ Add file…" creates a new labeled row from a
  local file (`POST /api/components/{id}/files`) and bumps the component
  version so the file is pinned from that version on; per-row "Upload"
  replaces a stored copy (`POST /api/datasheets/{id}/upload`), versioning on
  content change exactly like fetched PDFs (uploads are deliberate, so
  non-PDF content is versioned too — the unstable-web-page guard applies only
  to fetches). Uploaded rows have no source URL; generated symbols link their
  local `/api/datasheets/{id}/file` copy.

## Jaravis

The library agent runs on the Anthropic SDK tool runner (`claude-sonnet-5` by
default — set `JARAVIS_MODEL=claude-opus-4-8` for harder tasks; adaptive
thinking) inside the api service. **Activate it by setting
`ANTHROPIC_API_KEY` in `platform/.env`** (compose passes it through; dev mode:
export it before starting uvicorn). Claude subscription plans include monthly
Agent SDK credits tied to your account's API key.

The gate is structural: Jaravis's write tools can only create **drafts** —
component versions, symbol/footprint geometry versions, and skill updates.
Nothing is published until you approve it in the Proposals view
(symbol/footprint proposals show a rendered before/after preview there).

Jaravis has **full read access** to everything the platform stores: the
library (including pin/pad tables and raw symbol/footprint sources), the
archived datasheet PDFs (returned as text + page images, so it can visually
verify pinouts and package drawings), price history, stock, projects, BOMs,
production-run economics, notes and the audit log. It also has **internet
access**: Anthropic-hosted web search + web fetch (reads PDFs, cites sources),
JLCPCB parts-catalog search, the official JLC detail API, and LCSC lookup —
plus `refresh_supply` for a live re-check of one part's prices/stock.

Jaravis's prompt is two layers. Its **operating manual** — identity, the tools
it has, that it reads the DB in-process (not over HTTP), the draft-only gate,
and what it cannot do (no shell/scripts, no 3D-model editing) — lives in code
(`_build_system` in `services/jaravis.py`), so it always matches the actual
tools. The **skills** carry only editable *conventions*.

**Skills** (the Skills page): on every chat Jaravis's system prompt appends the
*current version* of every skill — the convention documents `conventions-library`
/ `conventions-footprints` / `conventions-symbols`, seeded from
`api/app/seed_skills/`. These are written for the agent (its tools and the
proposal gate), not the old terminal pipeline, so they never reference scripts
Jaravis can't run. Edit them in the web UI to change Jaravis's rules
immediately; every edit is a new immutable version with history and restore.
**Skills and component notes survive wipe-imports** — imports only seed skills
that don't exist yet and re-attach notes by component name; the DB versions are
the source of truth for agent knowledge. Jaravis can also propose skill updates
itself (get_skill / propose_skill_update) — drafts that require your approval in
Proposals.

## Projects (design tracking)

The platform also tracks your own KiCad **design projects** from their git
repositories (Projects in the top nav). Works with GitHub / GitLab / Gitea /
any HTTPS remote — plain `git` with an optional access token, stored encrypted
(`SECRET_KEY`), never returned by the API and never written to disk.

Per project:

- **Fetch** keeps a bare mirror clone; every **tag + the default-branch head**
  is auto-ingested and pre-rendered; any other commit can be ingested from the
  History tab. A snapshot is immutable (keyed by commit sha) and holds the
  discovered boards (a repo may contain several `.kicad_pro`), their **layer
  stacks** and **assembly variants** (KiCad 10 `schematic.variants`; KiCad 9
  projects fall back to a single default variant with DNP handling).
- **BOM** — extracted per board × variant by `kicad-cli sch export bom`
  (hierarchy/DNP/variants resolved by KiCad itself), matched to library
  components via `${SYMBOL_NAME}` then `LCSC Part`. Priced at any production
  volume from **full LCSC price ladders** (`component_price_points`: every
  tier with its own currency + refresh date, plus manual points for parts
  without LCSC). Includes MOQ-rounded order quantities, a **cost-vs-volume
  curve**, **LCSC stock checks**, and **BOM diff** between two snapshots.
- **Board** — 2D per-layer SVG stack with visibility toggles, 3D GLB viewer,
  STEP download, fab bundle (gerbers + drill + position). **Schematic** —
  per-page SVGs, variant-aware. ERC/DRC reports per snapshot. All renders are
  produced by the render container and **cached in MinIO keyed by sha**
  (immutable → rendered at most once; tags + head are pre-warmed on fetch).
- **Costs** — free-form manufacturing cost items (label, price, currency,
  company, MPN; **per device** or **per production run**, amortized) and
  **extra BOM items** (parts outside the schematic — linked to a component or
  freehand-priced, qty per device). Components can be **BOM-only**
  (`in_library=false`): priceable, usable in BOMs, never emitted into the
  KiCad libraries or the HTTP catalog.
- **Production runs** — qty, status, date, notes, file attachments (serial
  lists, invoices → MinIO), a serial-number registry, and economics computed
  on demand from **historical pricing at the run date** (append-only price +
  FX history; the closest recorded snapshot wins) with per-line
  **final-price overrides** and extra lines (e.g. shipping).
- **Production files live on runs** (not snapshots), as **versioned sets**:
  on run creation the repo's `production/` directory (JLCPCB Fabrication
  Toolkit output, `backups/` excluded) is auto-imported when committed;
  uploads and kicad-cli fab bundles (gerbers/drill/pos) create new versions —
  history is kept, the highest version is current. The JLC `bom.csv` is
  parsed as **assembly info** (which designators JLC places — never the total
  BOM); gerber zips are stored extracted too, feeding a **gerber viewer**
  (gerbv in the render image composites selected layers server-side).
- **Interactive viewers**: components are clickable on both the schematic
  and the 2D board view (info + link to the library component), and
  schematic **sub-sheet frames navigate** between pages. Hotspots come from
  a per-snapshot click-map parsed out of the sch/pcb sources
  (`services/project_map.py`) — cached in MinIO like the renders.
- **Nothing is hidden by the selected revision**: notes, runs, costs and
  history always show everything for the whole project; runs and notes just
  record which commit they were based on.
- **Notes** per project; **where-used** on components (which projects use a
  part); Jaravis gained read tools (`list_projects`, `get_project_bom`,
  `component_where_used`).
- **Currencies**: every price keeps its own currency; totals convert to the
  project's display currency (default USD) via daily ECB rates
  (frankfurter.app, auto-refreshed; manual per-currency overrides via
  `PUT /api/fx`).
- **JLC private stock** (JLC Stock in the nav): syncs the user's PRIVATE
  JLCPCB parts library (components JLC holds on consignment) via the
  official JLCPCB OpenAPI (`open.jlcpcb.com`, HMAC-signed "JOP" auth —
  apply at api.jlcpcb.com and set `JLC_APP_ID`/`JLC_ACCESS_KEY`/
  `JLC_SECRET_KEY`). Shows held quantities and their **value at current
  LCSC pricing**, plus where held parts are used across projects. Project
  **stock checks consume private stock first**: a line is covered when the
  private library holds enough; only the remainder is checked against LCSC
  market stock (JLC pills in the BOM stock column).


## Phase status (see design doc for the full plan)

- [x] Phase 00 — scaffold, compose, HTTP-library endpoints
- [x] Phase 01 — import station (wipe & reload), browse UI, previews, version rail
- [ ] Phase 02 — `kicadlib sync` CLI (mirror + manifest exist; CLI pending)
- [~] Phase 03 — proposals & approval gate (draft/approve/reject live for agent
      writes and in-place edit versioning; `kicadlib push` + batch bumps pending)
- [~] Phase 04 — Jaravis (chat + Q&A + propose new/edit live; needs API key;
      streaming + LCSC auto-import of symbols/footprints pending)
- [x] Phase 05a — projects module (git-tracked designs, priced BOMs, renders,
      production runs) — see "Projects" above
- [ ] Phase 05 — rules engine + nightly checks + pass/fail board
- [ ] Phase 06 — server move (auth, TLS), simple online editor
