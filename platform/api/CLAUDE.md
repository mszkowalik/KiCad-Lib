# Platform API (`platform/api`)

FastAPI backend for the Project Management Platform. Postgres is the **source of
truth**; the file mirror under `DATA_DIR/mirror` (served at `/files`) is a
disposable projection. This directory copies logic from the repo-root
`kicad_lib/` but never imports or modifies it.

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
| S-expr parsing / symbol+footprint parse cache | `util/sexpr.py`, `services/parse_cache.py` |

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
- **`project_ops.py` exists twice** — `api/app/services/` and `platform/render/`
  must stay byte-identical (same pattern as `render.py`/`server.py`).
- **NUL is illegal in argv**: git `--format` separators use `\x1f`, never `\x00`.
- **Price ladders**: `component_price_points` rows with `source="LCSC"` are
  replaced wholesale by the refresher; other sources (`Manual`, …) are never
  touched by robots. The legacy 3-point `ComponentPrice` summary (what gets
  injected into generated KiCad symbols and served to the KiCad HTTP plugin)
  is DERIVED from the ladder on every refresh (`ladder._update_price_summary`,
  same @1/@100/@Bulk rules as `kicad_lib/pricing.py`) — unless its `source`
  is non-LCSC (e.g. `Manual`), which pins it. It has no UI card of its own;
  the component page's single pricing surface is the ladder card.
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
- **Run economics**: `ProductionRun.frozen` (JSONB, written by
  `project_bom.freeze_run` at creation) + `overrides` (per-line, applied by
  `run_effective`). Never recompute a run's costs from live prices — that's
  what freezing is for; `POST /runs/{id}/refreeze` is the explicit exception.
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
- When a non-obvious backend convention or workaround emerges, record it here.
