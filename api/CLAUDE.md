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

## The versioning + publish model (core invariant)

Read this before touching components, symbols, footprints, or skills.

**AUTO-PUBLISH, EVERYWHERE.** Components, symbols and footprints since
2026-08-23; **skills since 2026-08-24**, which removed the last draft gate in
the platform. What replaced the gate is the **review axis**
(`services/review.py`, section below): every publish records a machine
validation, and verification/sign-off happen afterwards, asynchronously. All
publish doors go through `services/publish.py` —
`publish_component_version` / `publish_geometry_version` /
`publish_skill_version` — which own the datasheet pins, the sign-off carry,
the review-record carry and the machine check. A new publish path that
bypasses them silently loses all four. Mirror refreshes are the
`refresh_mirror_for_*` twins, AFTER the commit.

**Nothing files drafts any more, and there is nowhere to approve one.**
`routers/proposals.py` is DELETED, with the Proposals view, the nav badge and
`RecheckDialog`; `/proposals` redirects to `/reviews`. `POST
/api/import/sync` (the retired YAML diff, the one remaining draft producer)
answers **410** rather than writing rows nothing can act on — the destructive
full import still works, because it writes published rows. Draft and rejected
version rows from before all this stay readable as history: never write a new
one, and never re-introduce an approval queue without reading the review-axis
section first.

- **Immutable version rows.** `ComponentVersion`, `SymbolVersion`,
  `FootprintVersion`, `SkillVersion` are append-only. You never mutate a live
  version in place — you create a new one.
- **`current_version_id`** on the parent (`Component`, `Symbol`, …) is a plain
  `Integer` (deliberately **not** a FK) pointing at the live version. `None`
  means "no published version yet" — now only a leftover from the draft era (a
  creation that was filed and never approved). `current_version(comp)` resolves it.
- **`status` is a `String(20)`**, default `"published"`. Live values:
  - `"published"` — the only status anything writes now.
  - `"draft"` / `"rejected"` — HISTORY. Nothing produces either; both stay
    readable, and the UI labels them as never-published.
  There is **no `"approved"` status**; `approved_by` records who published when
  a person did it through a UI save.
- **`services/publish.py` is the single choke point**: it sets
  `status="published"`, moves `current_version_id`, pins datasheets, carries
  the sign-off and the review record, and runs the machine validation. Call it
  — never hand-roll a publish, and never move `current_version_id` yourself.
- **Prices and datasheets are NOT properties.** They live in `component_prices`
  and `datasheets` (component-scoped, auto-managed). Keep them out of
  `ComponentProperty`; the price keys (`PRICE_KEY_TO_COL`) and `Datasheet*` keys
  are stripped on import and rejected by Jaravis's `_parse_properties`.
  **Prices are never emitted to KiCad** (user decision 2026-07): neither the
  generated mirror symbols nor the HTTP catalog carry `Price *` fields —
  `injected_props(datasheets)` injects datasheet links only. Pricing lives on
  the platform (BOMs, ladders, run economics).
- **The injected datasheet link prefers the LOCAL copy.** `injected_props`
  emits `{public_base_url}/api/datasheets/{id}/file` whenever the current
  `DatasheetVersion` is a real PDF (content-type or `.pdf` filename), or is an
  uploaded file with no `source_url` at all; otherwise it falls back to the
  internet URL. Stored HTML product pages (LCSC etc.) deliberately keep the
  live link — a saved product page is worse than the real one. Applies to both
  emission paths (generated mirror symbols and the KiCad HTTP catalog), so
  `public_base_url` must be the API address as KiCad clients see it, not
  `localhost`, on any non-local deployment.
- **A new component archives its datasheet AT PUBLISH TIME, before the version
  lands.** `jaravis.propose_new_component` adds the `Datasheet` row, flushes,
  then calls `_archive_datasheet` (a best-effort wrapper on `fetch_datasheet`)
  BEFORE `_publish_component`. Order matters both ways: `pin_datasheets` then
  records which PDF version this component version used, and the
  `cmp.datasheet_text` machine item sees a real document instead of answering
  `na — no archived PDF`, which reads as "question does not apply" rather than
  "the file is missing". Before 2026-08-27 the row held only a URL and the PDF
  was fetched lazily on the first `read_datasheet`, so every freshly published
  part was invisible to `search_datasheets`.

  Two things to keep in mind if you touch this. `fetch_datasheet` **commits**,
  so the draft `ComponentVersion` is persisted before the publish — harmless
  only because every row it needs is already built by then. And the wrapper
  never raises: a supplier that is down must not cost the caller a component
  write. It returns `{"archived": ..., "text_layer": ...}` into the tool's
  response, and `text_layer` is the field that matters — an HTML page is
  **stored, not refused**, as `archived: true` with `text_layer: "none"`.
- **Datasheets are re-checked nightly** (`datasheet_store.start_nightly_recheck`,
  armed from `main.py` startup at `settings.datasheet_recheck_hour`, server
  local time — containers are UTC unless `TZ` is set). It runs the existing
  `start_fetch_all("all")` worker, so a changed document flows through the
  normal path: new `DatasheetVersion` → auto-bumped component version → mirror
  rebuild. The re-check is cheap because `fetch_datasheet(..., conditional=True)`
  replays the stored `etag` / `last_modified` (columns added by startup
  migration, learned on any fetch) as `If-None-Match` / `If-Modified-Since`;
  an unchanged document costs one 304 with no body. A 304 NEVER falls through
  to the store path. Manual re-fetch (`POST /api/datasheets/{id}/fetch`)
  deliberately passes `conditional=False` — a supplier can swap file content
  without touching its validators, and clicking re-fetch means "actually look".
- **Every stored document is classified searchable or not, ONCE, at store
  time** (`datasheet_store.classify_text_layer` → the `text_layer`,
  `page_count`, `text_pages` columns on `DatasheetVersion`). It opens the PDF
  with PyMuPDF and counts pages whose extracted text clears
  `_TEXT_MIN_CHARS` (24, above a scanner's stamped page number); ≥
  `_TEXT_RATIO_OK` (0.9) of pages is `text`, none is `scan`, between is
  `mixed`, a non-PDF is `none` and an unopenable file is `error`. Three rules:
  - **Never classify on read.** The corpus is ~900 MB of PDF bytes and single
    documents pass 30 MB. Walking one on every list render is not an option,
    which is the whole reason these are columns and not a computed property.
  - **The classifier never raises.** It runs inside the download path, and a
    document that stores fine must still store when the classifier chokes on
    it. Failures land as `text_layer = "error"`, which is itself a useful
    signal — it caught a 0-byte "PDF" Infineon served as `text/html`.
  - **`""` means "not classified yet"**, and is what
    `start_text_layer_classify("missing")` claims. It is armed unconditionally
    30 s after startup, so it costs nothing on every boot after the first
    sweep. `_classify_worker` loads ONE row at a time and expunges it —
    a `query(DatasheetVersion).all()` here pulls the whole library into
    memory. `POST /api/datasheets/classify` re-runs it (`mode: "all"` after a
    threshold change); `GET /api/datasheets/classify-status` and
    `/fetch-status` both report the per-class counts.

  `mixed` is not noise: a TI datasheet whose last six pages are image plates
  reads 24/30, and those plates are the package-drawing pages a footprint
  check goes looking for. Note the consequence for the agent — `scan` means
  `read_datasheet` returns EMPTY text for every page, so a verification that
  looks like it read the datasheet actually rested on the rendered images.
- **A file nothing can open is refused at the door, on every path.**
  `inspect_document` returns the classification AND the reason to refuse, from
  the same single PDF open; `store_or_raise` turns the reason into
  `BadDocument`. The gate sits in the SERVICE functions (`fetch_datasheet`,
  `store_upload`, `add_component_file`), not in the routers, so the UI upload,
  `POST /api/datasheets/{id}/upload`, the component file-add and the nightly
  fetch are all covered by one rule. Refused: empty files, files that do not
  open as a PDF, password-locked PDFs, and PDFs with zero pages.
  - **A `scan` is NOT refused.** It opens and it is a real document — it is
    only unsearchable. Refusing it would leave the part with nothing at all;
    the tag and `cmp.datasheet_text` exist to get it replaced instead.
  - **`fetch_datasheet` returns `{"result": "rejected", "reason": ...}` rather
    than raising**, so the nightly sweep counts it (`FETCH_STATE["rejected"]`)
    instead of dying. Any copy already held survives untouched — and the gate
    runs BEFORE the sha comparison, so a supplier that starts serving an error
    page reads as "rejected", not as "unchanged".
- **Fixing a component's datasheet: three doors, and only one of them is free.**
  The MCP tool surface has no way to attach a datasheet to an EXISTING
  component, and successive agent passes concluded from that the platform
  cannot do it and recorded `cmp.datasheet` as `skipped` on
  `LC76GPAMD`, `LE310X1-EU/-LA`, `LE910R1-EU` and `MP34DT05TR-A`. That
  conclusion is wrong — it is a gap in the tool surface, not in the API:
  - `POST /api/datasheets/{ds_id}/fetch` — server re-downloads `source_url`.
    No version bump. Use first; the server reaches some hosts the agent cannot.
  - `POST /api/datasheets/{ds_id}/upload` — push a PDF fetched by hand. The
    response says `component_bumped_to: null`, and that is the point: **the
    component version does NOT move, so its verification answers survive.**
    This is the door for a host that 403s the server (verified 2026-08-25 on
    `PESD1CAN,215`, whose Nexperia URL the server cannot reach).
  - `POST /api/components/{id}/versions` with `datasheets: [{label,
    source_url}]` — the only way to create, replace or reorder the ROWS, and
    hence to fix a wrong `source_url`. It **bumps the component version and
    drops every agent answer**, so do it first and re-record afterwards. Pass
    an existing row's `id` to keep its stored PDF; omit a row to archive it.

  Reachability is asymmetric and worth testing rather than assuming: on
  2026-08-25 `ti.com`, `assets.nexperia.com`, `hammfg.com`, `quectel.com`,
  `infineon.com`, `italtronic.com`, `degson.com`, `china-fenghua.com`,
  `samwha.com` and `telit.com` all served real PDFs to the agent's machine,
  while `phoenixcontact.com` (403), `st.com` (timeout) and `renata.com` (500)
  refused both it and the server. A 403 or a login wall arrives as a
  200-status HTML page, so check `file` says `PDF document` before uploading.
- **Datasheets are indexed PER PAGE, and the index is a finding aid — never an
  authority** (`services/datasheet_pages.py`, 2026-08-25). `DatasheetPage`
  holds one row per page of layout-aware markdown from `pymupdf4llm` (same
  MuPDF engine and Artifex licence as the `pymupdf` already used; it pulls
  onnxruntime, MIT). Keyed on the IMMUTABLE `datasheet_version_id`, so a row
  never goes stale — new PDF content is a new version with its own pages.
  Measured on the live corpus: 0.18–0.27 s per page, ~9400 pages on the
  current copies, 16.4 MB of text.
  - **Why it exists**: `read_datasheet` returns at most 6 pages chosen by
    GUESSING a page number, and RP2040 is 642 pages with its absolute maximum
    ratings on page 615. Nothing could search datasheet text at all.
  - **What it may not be trusted for.** The extractor keeps a table's grid and
    recovers the text drawn inside a mechanical figure, both of which plain
    extraction destroys — the TPS61023 land-pattern drawing yields
    `6X (0.67)`, `4X (0.5)`, `(1.48)`, and the STM32H725 LQFP100 pinout figure
    yields a correct pin-number-to-name map for all 100 pins. It ALSO shreds
    text that wraps inside a merged cell ("voltage must be supplied from" →
    "voage mus e suppe rom", STM32H725 p117) and reorders multi-line pin labels
    ("PC15-OSC32_OUT" → "OSC32_OUTPC15-", UFBGA169 ballout), and a unit in a
    merged column lands on one row of the group. So the index FINDS a page and
    the page image settles the value. Do not build a check that reads a
    dimension out of `content`.
  - **`extract_kind` is never blank on a written row.** `text` |
    `picture_text` (all of it came from inside a drawing) | `fallback_text`
    (layout extraction failed, plain extraction used) | `empty_scan` |
    `failed`. The extractor returns zero characters on a scanned page in
    0.08 s and raises NOTHING, so an unmarked empty row would make search
    return nothing and let a reader conclude the page is blank. This is the
    page-level twin of `DatasheetVersion.text_layer`.
  - **`pages_indexed_at` on the version is the coverage marker, not "has any
    page rows"** — a non-PDF legitimately yields zero pages and would
    otherwise be retried on every sweep for ever.
  - **The `tsv` column is GENERATED and the config is `simple`.** It cannot
    disagree with the content beside it, and `datasheet_pages._TSCONFIG` must
    stay identical to the DDL in `main.py` — a query parsed with a different
    config does not match the GIN index and silently falls back to a seq scan.
    `english` was rejected on purpose: datasheet tokens are part numbers,
    package codes and dimensions, which stemming damages.
  - **Search excludes superseded versions by default** (`d.current_version_id
    = dv.id`). Including them returns the same hit several times and points at
    a page the library no longer serves.
  - Sweeps mirror the fetch/classify pair: `POST /api/datasheets/index`
    (`missing` = the retroactive backfill, `current`, `all`),
    `POST /api/datasheets/index/stop` (stops BETWEEN versions — a
    half-extracted document would read as complete, because
    `extract_version` stamps `pages_indexed_at` itself),
    `GET /api/datasheets/index-status`. Startup arms `missing` after 120 s
    unless `DATASHEET_PAGE_INDEX_ON_STARTUP=false`. A store path fires
    `_index_pages` in a daemon thread — a 642-page document is three minutes
    of work and must never sit in the upload request. **In dev, a source edit
    reloads uvicorn and KILLS a running sweep**; the version's NULL
    `pages_indexed_at` is what makes that recoverable.
  - Read surfaces: `GET /api/datasheets/search`, `/{id}/outline`,
    `/{id}/pages/{n}`, and the agent tools `search_datasheets` /
    `datasheet_outline` (34 client tools now — the count in the Jaravis
    section below has been stale since before this).
- **`GET`/`DELETE /api/datasheets/broken`** list and remove documents that were
  archived before the gate existed. `purge_broken` does three things in order,
  and all three are load-bearing: NULL the `ComponentVersionDatasheet` pins (a
  real FK — the delete raises otherwise, and NULL already means "no local copy
  existed"), repoint `Datasheet.current_version_id` to the newest survivor or
  NULL (a dangling pointer makes `has_file` true and every download 404), then
  refresh the mirror for the affected categories (`injected_props` emits the
  LOCAL url whenever a current version exists, so a row falling back to NULL
  must go back to emitting the supplier URL). Run 2026-08-25: removed 2 — a
  truncated 300 kB LCSC PDF whose xref cannot resolve object 1
  (`FPC-05F-24PH20`, still served broken today, so that part now has no local
  copy at all) and a 0-byte `text/html` file Infineon served under a `.pdf`
  name (`BTT60501ERAXUMA1`, history only).
- **`cmp.datasheet_text` is a machine checklist item** answered by
  `validate_component` from the `text_layer` column, so it costs a column read.
  `scan` and `error` fail it; `mixed` passes with the page counts in the note;
  a non-PDF or an unclassified row is `na`. Two things to know before touching
  the machine tier:
  - **Adding a machine key does NOT re-open settled reviews.**
    `state_from_record` measures against the record's OWN pinned checklist
    snapshot (`_checklist_items_of`), so a checklist edit never flips history.
    Verified after publishing component checklist v2: 128 components stayed
    `checked` with zero records carrying the new key.
  - **There is deliberately no bulk re-validate**, and do not add one casually.
    `effective_record` is "newest non-revoked record on this version",
    regardless of actor — so writing a fresh machine record across the library
    would SUPERSEDE every human confirmation it lands on. A new rule therefore
    applies from each component's next publish onward.
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
- **Invoice positions form a tree; only LEAVES carry money.** `RunCostLine`
  rows nest via `parent_line_id` (soft pointer) so one printed position can be
  split — into shares charged to different runs, and into a supplier's own
  sub-fees (JLC prints one "SMT Assembly" figure whose stencil / manual-assembly
  components appear only on their website). **A line with live children is a
  header worth zero.** That rule lives in exactly one place,
  `run_actuals.header_ids`, and every money path filters on it: `document_json`,
  `pool_state`'s purchases, and `run_actuals`'s direct lines. Never re-derive it
  per call site, and never resolve a double count by editing a header's amount —
  the parent must keep what the invoice printed. Related invariants: reconciliation
  compares the printed total against **top-level** lines only (so splitting can
  never make a document read unreconciled); children inherit the parent's
  currency; over-allocation is refused (409) while under-allocation is legal and
  reported as `residual`; document-level `run_id` only claims lines that name no
  destination of their own (an invoice on run A with a line allocated to run B
  used to be charged to both); voiding a line voids its subtree. Percentages are
  a frontend calculator only — the API stores absolute amounts.
- **`allocate` has four values, and `"excluded"` is load-bearing.** `none` |
  `by_value` | `by_qty` | `excluded`. The carrier values spread a
  freight/duty/tax line over the SAME document's part lines (landed cost: value
  added, quantity not), and `line_destination` only claims the pool bucket for
  them when poolable part lines actually exist — `pool_state` cannot spread a
  surcharge over nothing. `excluded` means "entered so the document reconciles
  against its printed total, charged to NOBODY on purpose": reclaimable import
  VAT, and the prepaid-component portion of a JLC populated-board price whose
  components already reached the pool through their own invoice. It is checked
  FIRST in `line_destination`, filtered out of `pool_state`'s purchases (that is
  what prevents the prepaid double count) and skipped in `run_actuals`. Do not
  conflate it with `unassigned`, which means "nobody noticed yet" and is a defect.
- **Attachments can belong to a document, not just a run.**
  `run_attachments.run_id` is nullable and `document_id` is a soft pointer, so a
  supplier's scan is filed with the money it evidences — including on a shared
  document, which has no run. Document attachments live under `documents/<id>/`
  in MinIO, NEVER the run prefix: `delete_run` wipes that prefix, and a financial
  record's evidence must outlive the run (same reasoning as `RunCostDocument`
  being project-owned).
- **The sale side lives on the run** (`sale_unit_price`, `sale_currency`, `qty_sold`,
  `customer`, `order_ref`, `order_date`; startup-migrated). Price is stored PER
  DEVICE, never as a batch total — the total is derived, so a later quantity
  correction cannot silently rewrite revenue. Revenue charges on `qty_sold` (units
  BILLED), falling back to `qty_good` then `plan_qty` then `qty`: a customer is
  invoiced for what shipped, which is routinely neither the planned count nor the
  number that passed test. `run_actuals` returns `revenue`/`margin`/`margin_pct`
  (gross margin over revenue, the figure a price decision is made against) in the
  project's display currency; the register's `by_run_usd` converts both sides to USD
  at the **order date** when set, else the run date — a sale is struck on a day and
  its FX must not drift with today's rate. `RunPatch` applies these only when
  explicitly present (`exclude_unset`), so patching a label can never blank a price.
- **`resolve_part_lines` has THREE outcomes, not two.** `resolved` (linked to a
  library component), `unresolved` (MPN recognised by nothing) and **`unlinked`** —
  the MPN matched a `JlcStockItem` that itself has no `component_id`. An unlinked
  purchase is priced in the pool but can NEVER meet a BOM draw, so it silently
  under-costs every run; it used to be reported as neither, hiding 1750 DIP switches
  and ~$25k of enclosures/antennas. Two related rules: the MPN index prefers an
  entry that carries a `component_id` (JLC lists one manufacturer part under several
  LCSC codes — `XL-1005SURC` exists as both C25503345 unlinked and C965790 linked to
  component 218; first-write-wins costed 16,800 LEDs at zero while their money sat
  unconsumed), and a part bought under two MPNs is one part only if the library says
  so — a substitution (`KH-6X6X5H-STM` -> `TS3625A`) reads as a shortage of the
  second plus dead stock of the first until both map to one component.
- **The pool's moving average has its OWN clamped basis** (`_avg_qty` / `_avg_value`
  in `pool_state`), separate from the reported `qty` / `value_usd`. The reported
  pair are pure algebraic sums and MUST be able to go negative — the register's
  identity depends on it — but deriving the average from them directly is unsafe: a
  run that draws stock the pool never had strips the quantity without any value, and
  the next purchase then averages against a near-zero denominator. That produced a
  $44 average for a $3.73 enclosure. The basis never goes below zero (a draw takes
  `min(qty, on_hand)`), and when nothing is on hand the LAST KNOWN average is
  retained so a later purchase blends against a sane figure. Never "simplify" this
  back to `value_usd / qty`.
- **Draw order is event order, and an unpriced draw is a symptom.** A component
  drawn before any invoice exists for it prices at zero — correct, but it means the
  supplying invoice is missing, not that the part was free. Import the invoice, then
  redraw; snapshotted `unit_cost_usd` is never rewritten retroactively. Repricing is
  therefore a DELETE + re-POST with `unit_cost_usd=None`, run in event-date order so
  each draw blends the average the next one sees — `add_consumption` prices as of
  `consumed_at`, never today.
- **A zero-priced draw also hides duplicates.** `ComponentConsumption` has no
  uniqueness constraint, so a part drawn once by `consume_from_bom` and again by an
  ad-hoc script is simply charged twice — and while both rows price at zero, nothing
  in any total betrays it. Components 324/325 were double-drawn across all five Aqua
  runs for exactly that reason, and it surfaced only when their invoices arrived and
  the pool read 2030 drawn against 1015 devices. Afterwards the only way to tell the
  rows apart is the `note`: `consume_from_bom` writes `BOM x <volume>` (plus
  `(override …)`), so any other wording is hand-made. Before repricing a part, compare
  drawn quantity against units built — a clean multiple of the build volume is the tell.
- **A run's `overrides` apply to ACTUALS too, not just the plan.** `consume_from_bom`
  honours the same keys and the same `drop` flag `project_bom.run_effective` uses —
  `b<snapshot_bom_line id>` and `x<extra_item id>` — plus `component_id` (a
  substitution) and `qty_total`. `{"x6": {"drop": true, "note": "..."}}` records that
  a batch genuinely shipped without a part (the early batches had no carton) instead
  of hand-deleting draw rows, which left no trace of the decision. The response's
  `skipped` array reports what was deliberately left out, so a missing line is never
  mistaken for an oversight. Same mechanism covers DNP corrections and replacements.
- **An invoice's quantity unit is not always a piece.** Pracownia Tektury bills
  cartons in packs of 100, so a printed `10 szt` is 1000 boxes; storing 10 makes a
  per-device draw impossible. Restate into pieces and put the arithmetic in the
  line's notes. A per-device consumable must be `kind="part"` with no project/run so
  it feeds the pool — `packaging` and the other kinds are DIRECT run costs and are
  never drawn per device.
- **`parts_stock` aggregates ALL of a part's stock codes.** JLC lists one
  manufacturer part under several LCSC codes (`XL-1005SURC` is both C25503345 and
  C965790), so a key maps to a LIST of stock items and quantities add. First-match
  wins showed the same LED twice — once holding the pool's money with no stock, once
  with 18,488 pieces and a bogus "no invoice" flag. `jlc_codes` on each row names
  every code found.
- **Stock is event-sourced, and a draw cannot take what was never bought.**
  `_pool_events(db)` is the ONE source of stock events (leaf part purchases,
  draws, adjustments, date-sorted with ties adj < buy < use so a same-day invoice
  covers a same-day run); `pool_state`, `component_ledger` and `check_shortages`
  all replay it — never re-derive the event list per call site.
  `check_shortages` is a FULL-TIMELINE check (inserting a historical draw must
  not push a later balance negative) and matches parts by identity-key overlap,
  not exact key. Both draw paths (`add_consumption`, `consume_from_bom`) hard-
  refuse (409, with the shortage list) when a draw would take stock below zero —
  user decision 2026-07-28. The fix is one of: the missing invoice, a
  **placeholder document** (supplier `PLACEHOLDER (no invoice found)`, quantity =
  the replay's worst dip, price = the nearest real invoice, note saying REPLACE
  when the real one surfaces), a signed stock adjustment, or a run override
  recording the batch shipped without the part. `consume_from_bom` checks the
  whole batch first and refuses atomically, so a failed draw never leaves half a
  run consumed. Pre-existing negatives are grandfathered and surface as
  `issues.negative_stock` in the register; `GET /api/parts-ledger` returns one
  part's full timeline (the Parts stock row drill-down renders it).
- **The moving-average basis loses value at its OWN average, never at a draw's
  snapshotted price.** The snap belongs to run costing; using it in the basis
  leaks the difference, and a long sequence of below-average snaps once drained
  `_avg_qty` to 1 while `_avg_value` kept $125 — repricing every CH340B on the
  next plan at $125.66. A moving average is invariant under draws; only
  purchases and positive adjustments may move it.
- **Run PLANS price pool-first** (user decision 2026-07-28): with `at` set,
  `project_bom._component_data` prices a part from the pool's moving average
  as-of that date (`source="Pool average (invoices)"`) and only falls back to
  the ladder for parts never bought by then — invoices are ground truth, the
  ladder is an estimate. Browsing a snapshot BOM (`at=None`) keeps market
  ladders: that view answers "what would ordering cost", not "what did we pay".
  The import is local (`from . import run_actuals`) because run_actuals imports
  this module.
- **`history_points_at` skips EMPTY snapshots** — see the run-economics bullet.
- **Production steps are vendor-neutral keys, never new kinds** (user design
  2026-07-28, `services/cost_steps.py`). Three stages mirror the pipeline — `fab`,
  `pcba` (what JLCPCB does), `final` (what LIFTECH does) — and each step is a key
  like `pcba:setup` / `final:enclosure_print`. Vendors are wordings on top
  (`VENDOR_ALIASES`, `VENDOR_TEMPLATES` feed the split dialog via
  `GET /api/cost-steps`); `RunCostLine.kind` stays the coarse cross-vendor rollup.
  The step travels in the line's `plan_key` and in `ProjectCostItem.step_key`
  (startup-migrated; copy-on-write clone in `cost_state` must carry it), and
  `run_actuals` emits a per-step planned-vs-billed comparison (`steps` in the
  actuals payload) matched purely on the key. Two distinct coarse keys:
  `<stage>:general` = a position deliberately entered unsplit;
  `<stage>:other` = the remainder AFTER itemizing — the unexplained residual of a
  split must become a `:other` row (a header's residual is visible but worth
  zero, so money left on the header is not charged). The recurring JLCPCB
  per-board shortfall lives under `pcba:other`, which makes it a trackable
  series. Alias ordering matters: 'special components' before 'components',
  'extended components' before both — a substring match on the wrong alias
  misfiles money ($10.50 found in `pcba:parts` on day one).
- **JLC invoices auto-split into fee steps from the ORDER endpoints, never the
  invoice** (2026-07-30). The invoice prints one figure per line and even
  reallocates money between one project's PCB and assembly lines; the itemized
  truth is `selectPersonOrderDetail` — `orderCountTolls` per PCB order,
  `smtPriceInfo` per assembly order — cached verbatim in `JlcImport.fee_info`
  (fetched by sync; `POST /api/jlc/import/fees/refresh` backfills old rows).
  `jlc_import.JLC_SMT_FEE_STEPS` / `JLC_PCB_FEE_STEPS` map raw keys to steps;
  `fee_children_plan` is the ONE derivation both the import planner and the
  retroactive `jlc_apply.backfill_fee_split` (`POST /api/jlc/import/fees/
  backfill`, journalled, idempotent, skips hand-split lines) build children
  from. Traps encoded there: `padPatchMoney` is INSIDE `padMoney` (emitting
  both double counts); assembly-order `paiclMoney` exceeds
  dummy+carriage+tariff by a real unitemized charge (up to $382.74) that must
  become a `pcba:other` child; a `pcba:parts` fee child is written kind
  `assembly`, never `part` — a run-less `part` leaf claims the POOL, and JLC's
  sourced components never enter consigned stock. Fee children's
  `external_line_id` is `<order>:fee:<key>`, which is both the idempotency key
  and what lets a decision reclassify them.
- **`GET /api/invoices` is the money-conservation check.** `invoice_register`
  asserts one identity — invoiced == runs + projects + pool + excluded +
  unassigned + residual (`summary.gap_usd` must be 0) — plus the pool's own
  `purchased + adjustments - drawn == on_hand`. `pool_state` tracks the `value_*`
  legs alongside the quantities specifically so that second identity is exact
  rather than re-estimated. When adding a cost path, make it land in one of those
  buckets or the gap will expose it.

### Flasher (production programming) — the load-bearing rules

Full design: `docs/flasher/design.md` (§14 = the bundle model, §13 = its history).

- **ONE revision binds everything: the DEPLOYMENT VERSION.** It pins firmware
  images (`deployment_images`), berryware (`deployment_files` → exact
  `device_file_versions`), the procedure (`steps`), and the parameter wiring.
  The `Release` entity was folded in and DROPPED (2026-07-29) — its identity
  is now a derived **fingerprint**, so "firmware unchanged since v5" needs no
  second versioned object. Never reintroduce a parallel versioned wrapper
  around firmware; add a fingerprint if you need to compare.
- **Fingerprints are cache, never authority.** `bundle.stamp()` recomputes
  both from the child rows; call it after ANY change to images or files.
  `firmware_fingerprint` is order-sensitive (address+sha), `files_fingerprint`
  is a set (reordering downloads is a procedure change, not a payload change).
  Equal file fingerprints mean the same berryware bundle — that is how every
  historical V2 set recovered its real name by propagation.
- **`validate.check()` is the single gate.** The live composer and the publish
  button call the same function, so the editor can never disagree with the
  refusal. Errors block publishing (unpublished pins, chip/transport mismatch,
  overlapping flash offsets, unresolved `{placeholder}` or assert variable,
  autoexec.be not last, serial op before `serial_open`); warnings inform.
  Publishing also requires a comment. When you add a step op, add its rules
  here in the same change.
- **Device file text is stored LF-normalised** (`_normalise_text`). A CRLF file
  read as bytes hashes differently from the same file read as text, which made
  five V3 files report "changed" on every import when nothing had. Content
  addressing only pays off if the same source always yields the same hash.
- **Deleting an artifact is usage-guarded, and the guard lives in the API.**
  A firmware asset pinned by any deployment version, a bundle used by any
  version, a device file version pinned by a version or a bundle: all refuse
  with 409 and name the users. Programming runs record what they flashed, so
  the pinned artifacts must outlive any tidy-up. `_firmware_usage` /
  `_file_version_usage` are the single source for those answers — reuse them
  rather than re-deriving a join per call site.
- **A bundle's file SET is its identity; only the label is editable.** A
  different set is a different bundle (`ensure_bundle` resolves by fingerprint,
  so the same folder never forks a twin). Renaming one updates
  `files_label` on every version using it, because the version DISPLAYS the
  bundle's name rather than storing its own.
- **Channels are pointers, history is immutable.** `deployment_channels` name a
  version (`production`, `bench`); rolling back moves a channel. A batch pins a
  version or follows a channel; run creation resolves it and records the
  result. Draft versions run ONLY as bench trials (`draft_run=True`, no batch).
- **Functional checks are DERIVED, never authored** (`services/flasher/checks.py`).
  A step names what it proves (`check: "relay.2"`) and its own pass/fail becomes
  the check; imported runs, which have no steps, get the same names from their
  stored evidence. `recompute(db, run)` rebuilds a run's rows from scratch, so
  `POST /api/flasher/checks/recompute` can upgrade all history after you improve
  an extractor — never hand-write a `run_checks` row, and never let a check
  disagree with the run's own log. Add a new name to `CATALOG` (an unknown name
  still records, in "other"). An extractor that re-judges historical
  measurements must reproduce the original rule, inversions included.
- **`GET /api/flasher/files/{version_id}/{filename}` is deliberately
  unauthenticated** — the DEVICE fetches it with Tasmota's `UrlFetch`, which
  sends no auth headers. Published versions only; the URL ends with the
  filename because Tasmota saves by the last path segment. The reachable base
  is `settings.public_base_url` (LAN address, never localhost).
- **The engine (`services/flasher/engine.py`) owns the scenario; the browser
  only executes `action` ops and pipes bytes.** Ops in `BROWSER_OPS` run on
  the bench (esptool phase — latency-sensitive); every other op is Python.
  All DB writes go through `RunEngine._db` (own short-lived session per call,
  in a thread); logs are buffered and bulk-flushed every 0.5 s. A run row is
  created BEFORE step 1 and finalized in a `finally:` — a socket death, an
  engine bug or a failed `_load` must still close the row.
- **Transport rules are measured requirements, not style** (design.md §7): on
  `usb_serial_jtag` (ESP32-C6) the monitor phase never touches DTR/RTS, a
  reset re-enumerates USB, and esptool-js's `after("hard_reset")` alone never
  restarts the chip — the pulse in `web/src/flasher/station.ts` does.
- **`lte_sim_pin` is sent once and NEVER retried** — the firmware driver
  PUK-guards a re-sent rejected PIN (xdrv_128 ~483). Resolution: bench field →
  param-set `sim_pin` → WS prompt. The PIN is masked in the stored log and in
  `params_snapshot` (`SECRET_RE` masks any param whose key matches
  password|pin|salt|secret|token).
- **Captured variables with reserved names update the device row**
  (`IDENTITY_VARS`: topic→tasmota_id, imei, iccid, imsi, modem_model,
  modem_fw). Device identity is the MAC (`device_units.mac` UNIQUE),
  upserted at `esp_connect` ~2 s into a run, so even early failures are
  attributed. `mosquitto` export regenerates the broker file from
  `device_config_values` (`mqtt_creds_line`, `current=True`).
- **Credential derivation (`services/flasher/credentials.py`) is frozen** —
  verified byte-for-byte against real `mosquitto_passwords.txt` pairs. Any
  change strands the deployed fleet.

### Creating a version (the one true pattern)

Mirror `services/jaravis.py`. New component: `Component(name=…)` with
`current_version_id` left `None`; `ComponentVersion(version_no=1,
created_by=<actor>, comment=…)`; `ComponentProperty` rows with `position`; then
**`publish.publish_component_version(db, comp, cv, actor=…)`** and, after the
commit, `refresh_mirror_for_component`. Edit: same, but `version_no =
max(existing)+1` and carry `removed_properties` forward. Geometry: build the
version row and call `publish_geometry_version` + `refresh_mirror_for_geometry`
— or better, go through `services/geometry_proposals.py`, which owns the
parsing, the model-path rules and the repoint. Skills:
`publish.publish_skill_version`.

Never set `status` or move `current_version_id` by hand: those two lines are
what the publish functions exist to own, and a path that writes them itself
skips the datasheet pins, the sign-off carry, the review carry and the machine
validation. Audit actions in use: `publish`, `review.check`, `review.revoke`,
`signoff.*`, `import`. (`proposal.create` / `proposal.approve` /
`proposal.reject` appear in history only.)

## Jaravis capability policy (user directive, 2026-07)

- **Full read access to ALL platform data.** Jaravis must never be blind to
  data the platform holds — components, symbols, footprints, geometry, 3D
  models, datasheets (including archived PDF content), prices + history,
  stock, projects, snapshots, BOMs, production runs, notes, audit log. When a
  new table/service lands, add a matching Jaravis read tool; withholding data
  from it is a bug, not a safety feature.
- **Jaravis may view AND edit symbols, footprints and components — and its
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
- **Geometry proposals live in `services/geometry_proposals.py`, not in the
  tool.** `propose_symbol_version` / `propose_footprint_version` own the
  validation (kiutils/sexpr parse, footprint header must equal the name with NO
  prefix, 3D paths must start `${SEVENSIGMA_DIR}/3DModels/`; note the footprint
  node IS the sexpr tree root — reuse parse_cache's fallback), the draft row and
  the audit entry. New names create the parent row with `current_version_id=None`,
  same as components. **Two callers must never diverge**: the
  `propose_symbol_edit`/`propose_footprint_edit` agent tools (which only add
  `_record_proposal` + `json.dumps`) and `POST /api/{symbols,footprints}/{id}/propose`,
  the web paste box. The route takes the name from the ROW, never the request,
  so a paste can never rename a template.
- **Pasted geometry is normalised before it is parsed.** KiCad's editors put an
  s-expression on the clipboard, but not necessarily the file body: a footprint
  can arrive wrapped in an outer node and a symbol as a bare `(symbol …)` with no
  library. `normalize_footprint_text` / `normalize_symbol_text` reduce both to
  what the parsers expect, via `slice_node` — a hand-rolled balanced scan rather
  than parse-and-serialise, because the result is STORED as the version source
  and must keep the author's formatting byte-for-byte. A payload with no
  footprint/symbol node at all is refused by name ("this is not a whole
  footprint"), because a canvas-only selection otherwise parses fine and then
  fails the header check with a confusing message.
- **The same drawing, spelled differently, is NOT a new version**
  (`geometry_proposals._unchanged`, 2026-08-27). KiCad rewrites the WHOLE
  library file it saves: opening `7Sigma_Base.kicad_sym` in KiCad 10 and
  saving added `(show_name no)` 1284 times and `(do_not_autoplace no)` 1274
  times, re-sorted the pins of 21 symbols and moved custom properties ahead of
  the `ki_*` ones — across 197 symbols, 183 of which nobody had touched. Every
  call to `propose_*_version` bumps `version_no` and `_publish_geometry`
  repoints every component onto the new row, so pushing that file once would
  have written 197 symbol versions, published a component version for each of
  ~420 components, and buried the 14 real edits among them. Both propose
  functions therefore compare the incoming payload against the LIVE version
  first and return `{"ok": true, "unchanged": true, …}` without writing
  anything when they are the same drawing.
  - **It reuses `services/pcm_plugin/kicad_canon.py`, and must keep doing so.**
    That module already answers this exact question for the sync and push
    plugins, which meet the same wall from the client side; a second dialect
    that disagreed with them about what "edited" means would be worse than no
    guard. Measured on the real library: `kicad_canon` absorbs 169 of 197
    entries, and the 28 it still reports are real — 14 edits made on purpose
    and 14 where KiCad genuinely moved a hidden property field to `(at 0 0 0)`.
  - **Do NOT use `material.material_sha` for this.** It answers "does the
    production sign-off still hold" and deliberately ignores the symbol body
    outline, field text and field positions, so it reads a full redraw as no
    change. The two hashes measure different things on purpose.
  - **Never write the canonical form into a library file.** It sorts the
    children of `(symbol …)`, which reorders graphics and so decides which
    fill sits on top. It is a comparison key, exactly as its own docstring
    says. The stored `source_text` stays the author's bytes.
  - `cli/symdiff.py` is the client-side half: it reports which entries of a
    `.kicad_sym` really changed and `--extract`s them as single-symbol
    libraries ready to push. Run it before pushing a file KiCad has re-saved.
- **A clipboard copy has NO name, and the name is rewritten, not enforced.**
  KiCad names a copied item after the pseudo-library it invents for the
  clipboard — `(footprint "clipboard:11d1f418-7567-4c54-…")`. Refusing on a
  header mismatch therefore rejected the primary way text arrives, and deriving
  a name from it would have created a footprint literally called
  `clipboard:<uuid>`. So: `set_footprint_header` / `set_symbol_entry_name`
  rewrite the pasted name to the authoritative one (the row being edited, or
  what the user typed), and `is_placeholder_name` makes `derive_*_name` return
  None for a placeholder so the create form asks instead. A mismatch that is a
  REAL name still lands, with a warning naming both — silence there would let a
  wrong paste overwrite the wrong template unnoticed. Renaming a symbol must
  rewrite its unit entries (`<entry>_<unit>_<style>`) too, or the symbol renders
  empty.
- **Rendering needs the name INSIDE the text to match the name passed to
  kicad-cli.** `_render_source` therefore rewrites both to a safe label when the
  payload is a clipboard copy: the colon in `clipboard:<uuid>` reads as a
  library separator and the symbol lookup fails (502). Pass
  `allow_placeholder=True` to `derive_*_name` when you only need a label.
- **Creation reads the name OUT of the pasted text** (`derive_footprint_name` /
  `derive_symbol_name`), so `POST /api/{symbols,footprints}/propose` has no name
  field: a footprint header must equal the row name anyway, so a second field
  could only ever disagree. That route also REFUSES a name that already exists.
  The agent tool's "new name = create, known name = edit" overload is right for a
  call that states the name, but on a form labelled *new* it would file a version
  against a template the user never opened.
- **Rejecting the only draft of a never-published template deletes the row**
  (`proposals._drop_if_stillborn`). A creation proposal makes the parent up front
  with `current_version_id=None`, so a rejected creation used to leave a
  permanent versionless entry in the Templates browser that no UI could remove.
  Guarded twice: the parent must have no `current_version_id` AND no non-rejected
  version, so rejecting one draft of a published template never touches it.
- **`POST /api/{symbols,footprints}/preview.svg` renders UNSAVED source.** It is
  what the paste box previews before filing. It writes nothing and touches no
  table; `render_svg` is content-addressed, so re-previewing identical text is
  free. It normalises first — the point is to show what WOULD be filed.
- **A structured refusal puts its whole message in `error`.** These return
  `{"error": …, …context}` and the router raises it as the HTTPException detail;
  the web client renders `detail.error` verbatim. Context keys (`offending`,
  `symbols_found`, `header`) are extra for non-browser callers — never the only
  place a fact appears, or the browser shows a bare "400 Bad Request".
- Publishing geometry rebuilds the mirror through
  `publish.refresh_mirror_for_geometry`: a symbol publish rebuilds the base lib
  + the affected top-level libs (`update_mirror_symbols`), a footprint publish
  writes its own `.kicad_mod` AND those symbol libs (the injected "7S Version"
  field moves when a repoint bumps a component version). The PCM packages pick the change up
  lazily via the manifest hash. Components keep their pinned
  `symbol_version_id`/`footprint_version_id`; the KiCad-facing base lib,
  footprint mirror, and HTTP catalog always follow the newest published
  geometry.
- **Publishing geometry AUTO-PUBLISHES the component repoints**
  (`services/repoint.py`, user decision 2026-08-04, publishing since
  2026-08-23). The two facts above pull apart: the mirror and the HTTP catalog
  jump to the new geometry while every linked `ComponentVersion` still names the
  previous `footprint_version_id`, so the library and the components silently
  disagree about which land pattern is current. Measured on 2026-08-03: a pin-1
  sweep published 105 footprint versions and left 185 of 327 components pinned to
  the superseded drawing. So a geometry publish calls `repoint_for` in the SAME
  transaction and returns the result as `repointed`; each affected component
  gets a published version through `publish_component_version`, so the sign-off
  carry, the review carry and the machine check all run.
  `AUTO_REPOINT_COMPONENTS=false` turns it off. What a stale pin looks like to
  a user is `PinnedRef.is_current === false` on the component page ("library
  serves v5") — the state this exists to prevent. Invariants in that module:
  - **A leftover human/agent draft is skipped, not rewritten**, and reported in
    `repointed.skipped`. Nothing files drafts any more, so this only fires on
    rows from before the gate was removed — but rewriting one would still be
    rewriting somebody's unfinished edit.
  - **A leftover auto-draft is refreshed and published** rather than left beside
    a new parallel version.
  - **Properties are cloned in FULL fidelity** — `hide`, `show_name` and `layout`
    included. `propose_component_edit` writes only key/value/is_null and lets the
    rest default, which is fine when a caller is restating properties on purpose,
    but here the component is not being edited and `hide` drives KiCad field
    visibility.
  - **Never read `comp.versions` inside this module.** The session is
    `expire_on_commit=False` and rows added here are not appended to a loaded
    relationship, so it goes stale the moment a version is added — that made the
    coalescing miss its own draft and open a second one. Use `_versions(db, comp)`.
    `publish.publish_skill_version` avoids the same trap by querying the version
    numbers instead of reading `skill.versions`.

### Production sign-off (`services/signoff.py`, `services/material.py`)

A **sign-off** records that a human checked a component's symbol, land pattern
and part number before boards were built (user design, 2026-08-17). It is a
different act from library approval and uses a different word everywhere: a
version's `approved_by` means "this edit was let into the library", and a
published component may never have been checked by anybody. Never merge the two
concepts, and never let a UI print one where it means the other.

- **The row names a `component_version_id`, never just a component.** A
  component version pins its exact `symbol_version_id` and
  `footprint_version_id`, and version rows are immutable, so naming the version
  names the three drawings that were checked and can never come to mean
  something else. Every state is DERIVED from one question — is there a live
  sign-off on `components.current_version_id`? — so nothing is ever swept or
  invalidated. `signed` | `stale` | `revoked` | `unsigned`; `revoked` must never
  render as `unsigned`, because "somebody took this back" is a stronger
  statement than "nobody looked yet".
- **`component_signoffs` is append-only, with no unique constraint.** Revoking
  stamps `revoked_at`; signing again adds a row. The live sign-off of a version
  is the newest row for it with `revoked_at IS NULL` (`live_signoff`).
- **Two publish paths must BOTH carry.** `proposals.approve` and
  `components.create_version` (the in-place save, where the user saving IS the
  approval) each call `signoff.carry_on_publish` in the same transaction as the
  publish. Miss one and editing a description silently unsigns the part. Any
  future third publish path has to call it too.
- **`NON_MATERIAL_KEYS` is an ALLOW-LIST, and the direction is the point.** A
  property key is material — it can make the checked part the wrong part —
  unless it is explicitly listed (`ki_description`, `ki_keywords`,
  `ki_fp_filters`, `ki_locked`, `Datasheet*`, `Footprint_Name`). A new key
  nobody has classified blocks the carry, which is the safe way to be wrong.
- **The material fingerprint is what makes the carry provable.**
  `services/material.py` hashes only what reaches the board: pads (number, type,
  shape, position, rotation, size, drill, layers, margins, primitives), the
  courtyard and the `attr` flags; on symbols, the pin set (number, name,
  electrical type, graphic style, position, length, hidden, alternates, unit).
  Silkscreen, fab, `descr`/`tags`, uuids, 3D models, symbol body graphics and
  field positions are excluded on purpose. Parse with `util/sexpr.py`, never
  kiutils, and never reuse `parse_cache` here — it drops pad and pin POSITIONS,
  which is the single most important thing being compared. **An empty
  `material_sha` means "could not tell" and must NEVER compare equal to another
  empty one.**
- **Precedence in `geometry_carries` is deliberate**: `recheck_required is True`
  wins over everything (an approver who asks for another look has a reason the
  fingerprint cannot see); then an identical fingerprint yields `auto-carried`;
  only then does `recheck_required is False` yield `carried`. A waiver on an
  unchanged drawing is not a waiver — reporting it as one would put a human's
  name on a decision they never made and would make "somebody took
  responsibility for a change" indistinguishable from "nothing changed".
- **Geometry approval asks the question and stores the answer.**
  `POST /api/proposals/{symbols,footprints}/{id}/approve` takes
  `{recheck_required, note}`; `GET …/material-diff` supplies the pre-answer the
  dialog shows. A body-less approval (older client, bulk path) leaves
  `recheck_required` NULL, and the fingerprint comparison then decides — the
  same answer the dialog would have suggested.
- **Nothing is blocked.** No export refuses and no run is gated; the state is a
  badge (user decision). If that ever changes, change it at a call site —
  `services/signoff.py` stays a pure record.
- **`material_sha` is a derived cache**, stamped at version creation
  (`geometry_proposals`, `importer`) and backfilled in a background thread from
  `main.py` startup. It is safe for it to be missing: an un-fingerprinted
  version blocks a carry rather than granting one.
- Jaravis gets READ access only (`list_signoffs`, plus `production_signoff` on
  `get_component`). A production check is a human act and there is no draft to
  gate a robot's version of it.
- **First human sign-off promotes `in_design` -> `released`**
  (`signoffs._promote_on_first_sign`) — the ONE automatic lifecycle
  transition. Deprecated/obsolete are never touched by it.

### The review axis (`services/review.py`, user design 2026-08-23)

Publishing and reviewing are separate axes. Versions publish immediately; the
review axis records who verified each version against its documentation.

- **`review_records`** — append-only, CUMULATIVE, polymorphic
  (`subject_kind` + `subject_version_id`, like `Comment`). Each record stores
  the FULL merged item snapshot; the effective record of a version is simply
  the newest non-revoked one. Items carry per-item provenance
  `{actor, actor_type, at}` with the tier rule machine < agent < human
  enforced at write time (`record_check`) — a lower tier never overwrites a
  higher tier's answer. `items=None` = a one-click human confirmation.
- **States are DERIVED, never stored** (`state_from_record`): `unreviewed` |
  `failed` (a machine item failed) | `partial` (skipped or unanswered items) |
  `checked`. A component's effective state is the WEAKEST of its own record
  and its pinned symbol/footprint records (`component_effective` /
  `states_for_components` — always the bulk variant on list surfaces).
- **Checklists** (`checklists` + `checklist_versions`,
  `services/checklists.py`): seeded from code on first start, resolved per
  subject (base for the kind + category-scoped merges), items keyed stably.
  A human UI save publishes a version directly; the agent never edits
  checklists. The editor is `web/src/pages/Checklists.tsx`
  (`/reviews/checklists`), and four rules hold it up:
  - **`GET /api/{kind}/{id}/preview.svg?v=<version_id>`**: `v` is a CACHE KEY,
    never a selector — it always renders the CURRENT drawing. It exists so the
    URL changes when the drawing does; a matching `v` gets
    `immutable, max-age=1y`, a missing or stale one gets `no-cache`, and
    `X-Version-Id` always reports what was rendered. Before this the URL was
    version-agnostic and a pushed footprint kept showing its old picture.
  - **The agent worklist** (`review_requests`, endpoints under
    `/api/reviews/requests`): the user queues subjects from the Reviews page,
    the agent reads them with the `get_review_worklist` tool, and
    `record_check` marks a subject's open requests done the moment ANY
    verification lands on it — whoever wrote it. Requests gate nothing and
    carry no content; done rows are kept, never pruned ("when did I ask" is
    cheap to answer). `POST /api/reviews/confirm-agent` is the other half:
    one human gesture writing the same one-click confirmation "Mark checked"
    writes, over every subject whose effective state is checked with agent
    provenance — for a component that is its OWN record's provenance, not the
    aggregate, so confirming a part never silently vouches for an unchecked
    footprint.
  - **The queue ranks by leverage.** `GET /api/reviews/queue` returns
    `used_by` per template (live components pinning it) because 18 failed
    symbols were dragging 159 components (measured 2026-08-24) and a
    state-sorted list hid it; `?snapshot_id=` scopes the whole queue to one
    snapshot's BOM and the drawings it pins (review-before-build). Health adds
    `failing_keys` (machine failures + flags grouped by checklist key — the
    work-plan view) and `skip_reasons`, both counted over EFFECTIVE records
    only, so the numbers cannot drift from the queue.
  - **A one-click confirmation stores `items=None`, and the card must not read
    its answers off it.** That sentinel is what makes `state_from_record`
    return a full check without measuring completeness, so it cannot be
    repopulated — a subject with a legitimately skipped item would flip back to
    partial. But `_detail` read the per-item answers from the effective record
    alone, so pressing **Mark checked** blanked the whole checklist and threw
    away the visible evidence of what the machine and the agent had verified
    (user report 2026-08-25). The state still comes from `effective_record`;
    the ITEMS come from `review.itemised_record`, the newest non-revoked record
    that has a breakdown, and `items_carried` tells the card to say so rather
    than crediting those answers to whoever pressed the button.
  - **The WRITE path still has the other half of that bug** (found 2026-08-25,
    not yet fixed). `itemised_record` repaired reading; `record_check` still
    builds its new snapshot by carrying from `effective_record`. So when the
    newest record on a version is a one-click confirmation, writing ONE item
    carries from `items=None`, inherits nothing, and the new record becomes the
    only answer — silently discarding every per-item answer underneath it.
    Reproduced on `PESD1CAN,215`: a single `cmp.datasheet_text` answer took it
    from 12 answered items to 1, with the 12 recoverable only from a snapshot
    taken earlier in the session. `carried_from_id` pointed at the one-click
    record, which is the tell. The fix is for `record_check` to seed from
    `itemised_record` rather than `effective_record`; until then, never record a
    partial item set on a subject whose latest record is a one-click human
    confirm — read the checklist first and re-send every answer it already has.
  - **Adding an item to a base checklist un-answers it on every existing
    subject, and nothing backfills it.** `machine_check_on_publish` is the only
    caller of `validator.validate`, and it runs inside the publish transaction —
    there is no endpoint that re-runs the validator on an already-published
    version. So publishing checklist v2 with `cmp.datasheet_text` (2026-08-25)
    moved all 418 components from checked to partial at once, and the only ways
    out are a mass republish, which would drop every agent answer, or answering
    the item by hand. It was backfilled by hand from the `text_layer` column the
    validator itself reads. Before adding a machine item to a base checklist,
    decide who answers it for the existing rows.
  - **Re-answering an item keeps what it replaced** (`superseded` on the entry).
    Accepting a flag used to mean deleting the only description of the defect,
    so the answer being overwritten is kept on the new entry, and `_notable`
    makes a real finding (`flagged`/`failed`) outlive any number of later
    routine re-checks. `_detail` must include `superseded` in the projection it
    builds for `answered` — a fixed key list there is exactly what hid it the
    first time.
  - **A skip may carry a structured `reason`** (`html_datasheet`,
    `no_document`, …) — `record_check` stores it skip-only, capped at 40
    chars; the ReviewCard offers the presets. Free text stays in `note`.
  - **`machine: true` is a claim about `services/validator.py`, not a wish.**
    `validator.MACHINE_KEYS` is the registry of keys that module answers, per
    kind; `GET /api/checklists/meta` serves it, the editor greys the flag out
    for anything else, and `_validate_items` refuses it. An item flagged
    machine that nothing answers can never be answered by anyone — it pins
    every subject of that kind at "partial" for ever.
  - **A review record snapshots the RESOLVED list it was measured against**
    (`ReviewRecord.checklist_items`, startup-migrated). Before it,
    `checklist_version_id` named the base version alone, so a category-scoped
    item was expected while a check was being written and forgotten on the next
    read — an unanswered one silently upgraded the state from partial to
    checked. `_checklist_items_of` prefers the snapshot and falls back to the
    pinned base version for older rows; the carries copy it. Never re-resolve
    from the current checklists on read, or editing a checklist would rewrite
    the state of every past check.
  - **`GET /api/checklists/resolve?kind=&category_id=`** returns the merged list
    with a `from` per item, which is the only honest way to look at a
    category-scoped list — it MERGES on top of the base one rather than
    replacing it.
  - **Only ONE base list per kind is ever read**, and symbols and footprints
    carry no category — so `create_checklist` accepts a CATEGORY-SCOPED
    COMPONENT list and nothing else, and refuses a second list for a category
    that already has one. Anything else would be created, listed, edited and
    never reach a verification. Deleting is category-scoped for the mirror
    reason: a base checklist would leave its kind with nothing to answer. Past
    verifications are safe either way because of the snapshot above.
  - `save_checklist` / `create_checklist` call `db.expire_all()` before
    re-reading. Without it the response described the checklist as it was
    BEFORE the save (`version_no: null`, zero items, the new row missing from
    the history) while the save itself had landed — the same
    `expire_on_commit=False` trap as `services/repoint.py`.
- **The machine tier** (`services/validator.py`) runs inside every publish
  (`machine_check_on_publish`, never raises): the old YAML validator's
  footprint style/dimension checks, symbol basics, component property rules
  (consuming `M.Rule` global defaults) — plus **`fp.model3d`: a missing 3D
  model FAILS the check** and stays failed until a human/agent marks the item
  `na` in a follow-up. Machine items answer `checked|failed|na`, never
  `skipped`; `failed` is machine-only. Agents/humans additionally have
  **`flagged`** (verified and found WRONG, deliberately not fixed — note
  required, enforced in `record_check`): it ranks like `failed` (state
  "issues") and feeds the second-pass worklist
  (`reviews.flagged_worklist`, surfaced on the health panel). Review-only
  passes use it instead of editing.
- **A check may answer a key the checklist does not define** — a custom item,
  recorded on that ONE subject. The agent could always do it (any key reaches
  `record_check`); the review card can now too, and both must send the item's
  `text`, because the record is the only place that wording will ever live —
  `record_check` blocks a textless unknown key rather than storing a bare key
  nobody can read. Custom items count in the state exactly like checklist items
  (`state_from_record` measures `total` as `max(expected, answered)`), and
  `_detail` returns them as `extra_items`. Adding one does NOT touch the
  checklist document, which is the point: it says "this part needed this
  check", not "every part does".
- **Carries mirror the sign-off carry**: equal `material_sha` or
  `recheck_required=False` (the minor-change waiver, settable at publish time
  via `minor_change` on the geometry tools/paste box) clones the record onto
  the new version as kind `carry`; component data changes are judged by
  `signoff.data_carries`. Repoints therefore keep verifications on
  silk-only edits and strip them on pad moves.
- **`Component.lifecycle_state`** (`in_design|released|deprecated|obsolete`):
  usage fitness, separate from review state. `deprecated`/`obsolete`
  (`mirror.HIDDEN_LIFECYCLE`) are excluded from the generated symbol libs AND
  both `kicad_http` part endpoints — platform-only. Changed via
  `PATCH /api/components/{id}/lifecycle`, which rebuilds the mirror when
  visibility flips.
- **The `7S Version` field** (`generator.version_prop`, "c5 s3 f7") is
  injected into every emitted symbol (mirror + HTTP catalog), lands on placed
  schematic symbols, and is read back at ingest into
  `SnapshotBomLine.lib_version` (BOM export field `7S Version` → label
  `LibVersion` — `project_ops.BOM_FIELDS`, BOTH copies). It answers "which
  library versions was this board drawn with" from the committed source.
- **`snapshot_reviews`** — the end-of-design record
  (`POST /api/projects/{id}/review/complete`), storing per-component states
  at completion so a later run can say "3 components changed since the
  review". `routers/reviews.py::snapshot_review_issues` is the ONE
  implementation both the project Review tab and the run-creation gate use.
- **The run-creation gate WARNS, it never blocks**: `create_run` answers 409
  `{review_warning: true, …}` for a snapshot with unsigned/unreviewed/
  deprecated parts, changes since the last review, or no completed review;
  re-posting with `ack_review=true` proceeds and audits
  `production.review_ack`. Everything else stays reporting-only.

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
- **`alter` does nothing to a RUNNING ngspice transient.** It returns success
  and changes not one value; the live worker therefore wraps every knob in
  `bg_halt` → wait for `ngSpice_running()` → `alter` → `bg_resume`, which does
  take and continues the same transient instead of restarting it
  (`render/sim_worker.py`, measured 2026-08-30). A source with a WAVEFORM
  (PWL, PULSE, SIN) cannot be steered by any spelling of alter — a harness
  that wants a live input drives it from a plain DC source or a control node.
- **A simulation is a PROJECT, not a sheet.** A design repository keeps one
  `_sim` KiCad project per block it exercises (`EVSE_20_CTRL` has six); the
  root sheet includes the real block sheet and adds the harness — supplies,
  PWL stimulus, loads, a `.control` verdict block — as SPICE text. So
  `sim_run.run` ALWAYS netlists the source root, whatever sheet the viewer is
  showing: netlisting the block alone drops the harness and ngspice answers
  `incomplete or empty netlist`.
- **Server-side, `Sim.Library` arrives spelled the INSTALLED way.** A project
  schematic stores `${KICAD10_3RD_PARTY}/symbols/com_sevensigma_library/…`
  (`pcm.SIM_LIB_INSTALLED`), not the mirror's `${SEVENSIGMA_DIR}/Symbols/…`,
  so every real project failed to netlist until `pcm.server_pcm_root()` laid
  out a PCM-shaped directory that symlinks to the mirror and both netlist
  paths exported `KICAD10_3RD_PARTY`. `sch export netlist` has no
  `--define-var`; the environment is the only way in. **Expose the model FILE
  there, never the mirror's `Symbols` folder**: kicad-cli 10.0.5 segfaults
  (rc 139, no message at all) when a `.kicad_sym` sits in the directory a PCM
  symbol library resolves to. Measured — the same schematic exports 512 lines
  with `7Sigma_sim.sp` alone beside it and dies the moment
  `7Sigma_Base.kicad_sym` is copied in next to it.
- **Simulation runs as an OP, not as its own service** (`docs/simulator/design.md`).
  `project_ops.sim_run` netlists a sheet with kicad-cli and runs ngspice on the
  result, so it rides the existing render dispatch: `RENDER_MODE=local`
  simulates on a developer Mac with no container, and MinIO caching came free.
  `services/sim_geom.py` extracts the overlay geometry and takes net NAMES from
  the kicadxml netlist rather than deriving them — KiCad's naming rules
  (hierarchy prefixes, power symbols, `Net-(R1-Pad2)` fallbacks) are its own
  business, and an overlay that guessed them would quietly disagree with the
  simulation. Two facts that cost an afternoon each: `kicad-cli` DOES expand
  `${SEVENSIGMA_DIR}` in `Sim.Library` from the environment, and a symbol's
  stored rotation must be NEGATED once library y-up coordinates are flipped
  into sheet y-down (`sim_geom._place`) or a 270-degree part swaps its pins.
- **The browser DRAWS the schematic; the server only parses it.**
  `services/sch_draw.py` turns a `.kicad_sch` into a draw document — library
  graphics in symbol coordinates plus a placement matrix each — and it is
  attached to the geometry response (`geom["draw"]`) so the two come from ONE
  parse and can never disagree about item order. `sch_draw.placement_matrix`
  must stay identical to `sim_geom._place`: the overlay reads a pin the server
  positioned and the renderer draws it from the matrix. Consequence worth
  knowing: the project's schematic tab no longer renders SVGs through
  kicad-cli, so it needs the CHECKOUT rather than a cached render. A pruned
  checkout is re-materialised from the git mirror; a server with no mirror at
  all now fails where a cached render used to answer.
- **There is no schematic IMAGE any more.** `sch_svg`/`sch_svg_plain`,
  `project_render.sch_pages_zip`, the `/snapshots/…/schematic` endpoints,
  `/api/sim/…/sheet.svg` and the ingest pre-render are gone. Component
  previews (`services/render.py`, symbols and footprints from `.kicad_sym` /
  `.kicad_mod`, cached on disk by content hash) are a DIFFERENT path and are
  untouched. Object storage has no invalidation for a render nobody asks for,
  so the deploy that stopped writing them also removes them:
  `storage.drop_schematic_renders()`, called once on startup in a background
  thread behind the marker object `maintenance/schematic-renders-dropped.v1`.
  Listing the bucket is the slow part — a deploy must not wait for it.
- **The schematic palette and writer** (`services/sch_lib.py`,
  `services/sch_write.py`) are how a circuit drawn in the browser becomes a
  real file. Four things KiCad 10 refuses or mis-reads, all found by it
  refusing to load and saying only "Failed to load schematic":
  - a `lib_symbols` entry is named by the FULL library id (`"Simulator:R"`)
    while its unit sub-symbols keep the bare name (`"R_1_1"`);
  - a `wire` has exactly TWO points — a drawn run of several segments is
    several wires;
  - `junction` and `no_connect` take `(at x y)`, with no angle;
  - `(power global)`, not `(power)`.
  Two more that load fine and then lie: a pin name written `"~"` inside a
  `.kicad_sch` is NOT folded away the way it is in a `.kicad_sym`, so every
  generated net becomes `Net-(R1-~-Pad1)` — write an empty name; and
  `Sim.Device R` on a switch makes KiCad PREFIX the reference rather than
  replace it, so `SW1` netlists as `RSW1` and an `alter sw1` is accepted and
  does nothing (`sim_geom.spice_instance` is what the UI must use).
- **The palette's active parts reference the platform's OWN models.** An
  op-amp, an inverter, an AND gate and a D flip-flop are not built from a
  Value field the way R, C, L and the sources are: each carries the same four
  link fields the mirror puts on a catalogue part (`Sim.Device SUBCKT`,
  `Sim.Name sigma_…`, `Sim.Library`, `Sim.Pins`) pointed at
  `7Sigma_sim.sp`, as `conventions-simulation` requires — never a KiCad
  install file. `sch_lib._ic` derives `Sim.Pins` from the pin order it is
  given, so the map cannot drift from the picture. The path written is
  `pcm.SIM_LIB_INSTALLED`, not the mirror's `${SEVENSIGMA_DIR}` form: both
  resolve on the server, and only that one also resolves in the user's own
  KiCad after they install the library package — which a sheet drawn here is
  meant to be opened in.
- **A diode needs `Sim.Device D` and `Sim.Params`.** Without them KiCad emits
  `D1 __D1` — the reference, a model name, and NO NODES. The part vanishes
  from the circuit and nothing says so, which is the silent-disconnection
  failure `conventions-simulation` warns about. With them KiCad writes a real
  `.model` from the parameters. The same mechanism is what gives a part more
  than one number to set: `sch_lib.PARAM_FORMS` declares what each primitive
  is asked for, and the browser fills the template in.
- **A run that PRINTED is a run that succeeded.** A verdict harness executes
  its analysis inside the `.control` block and echoes a PASS/FAIL table;
  ngspice writes the rawfile for the DECK's analysis, so such a run finishes
  with a result and no vectors. `run_ngspice` used to call that "produced no
  data" and fail — which made every one of `EVSE_20_CTRL`'s six harnesses
  unrunnable from the UI. It now returns an empty rawfile when the log holds
  anything the deck itself printed (`_printed_anything`, which discounts
  ngspice's own banner), and `sim_run` encodes a payload with no plots.
- **A harness that wants waveforms too says `run`, and leaves `.tran` on the
  sheet.** The rule above is about what ngspice DOES, not what a harness must
  settle for: with the analysis inside the control block ngspice writes no
  rawfile at all, but with `.tran` as a sheet directive and `run` as the first
  command in the block, the deck's analysis goes to the rawfile `-r` named AND
  the block still echoes its PASS/FAIL table. One run, waveforms and verdicts
  (measured 2026-08-30; `services/sim_example.py` is built this way). `run`
  also picks up whatever analysis the Scenario panel injects, so the checks
  survive a user asking for a different sweep.
- **`services/sim_example.py` is the worked circuit the Simulator offers when
  there is nothing to open** (`POST /api/sim/example`). It is an ordinary
  sketch — stored by `store_sketch` like any drawing, so it is editable and
  re-runnable the moment it opens, and nothing downstream knows where it came
  from. Every coordinate in it is a multiple of 1.27 mm, because a pin off the
  grid does not connect and nothing says so.
- **`services/sim_scenario.py` reads a harness rather than rewriting it.** The
  text items beside the circuit are classified — `.control` blocks are runs,
  a lone `.tran`/`.ac`/`.dc`/`.op` is the analysis, the rest is stimulus or
  prose — and served by `GET /api/sim/…/scenarios`, which also carries the
  analysis forms the run panel builds a directive from. A `.control` block
  names itself with its first `echo`. The PASS/FAIL table it prints is parsed
  in the BROWSER (`web/src/sim/scenario.ts`), from the log the run already
  carries; a second copy here would be a second thing to keep in step.
- **An operating point has no sweep axis.** `sim_spice.encode_payload` drops
  the first vector as the axis for a transient, an AC sweep or a DC sweep —
  but an `.op` writes an ordinary node voltage first, and dropping it loses a
  reading the user asked for. The axis test is `len(scale) > 1 or the first
  vector is time/frequency`.
- **`project_ops.py`, `sim_spice.py`, `board_template.kicad_pcb` and
  `themes/Skyline-7S.json` exist twice** — `api/app/services/` and `render/`
  must stay byte-identical, and the workflow's `guard` job fails the build
  when they are not (same pattern as `render.py`/`server.py`). The theme is on
  that list because kicad-cli reads it AND the browser's own renderer reads it
  through `GET /api/sim/theme`; two copies would put the simulator and the
  schematic tab back into two colour schemes. `project_ops.py` imports
  `sim_spice` through a `try: from . import … except ImportError: import …`
  pair, because the API loads it as a package and the render container as a
  flat module in `/srv`.
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
  treat a line as procurable when ANY pool covers it. A **fourth** quantity now
  exists and is not a stock pool at all: the cost pool's `remaining_qty`
  (`run_actuals.pool_state`) is a MONEY balance — what was bought minus what runs
  drew minus write-offs — and is explicitly not expected to match any physical
  count. `GET /api/parts-stock` (`run_actuals.parts_stock`, the Parts stock view)
  is the one place the money balance and `JlcStockItem.qty` are shown together,
  because the gap between them is the useful signal: a negative `delta_qty` means
  boards were built without a recorded draw, and a part JLC holds that the pool has
  never seen (`state: "jlc_only"`) means the purchase invoice is missing. Value
  comparisons there price the SAME remainder both ways — never "held at market" vs
  "remainder at cost", which would just restate the quantity gap as money. The legacy 3-point `ComponentPrice` stays authoritative
  for KiCad symbol injection. **Two price stores, one bridge**: the BOM prices
  from the ladder, but when a part has no ladder points it falls back to its
  `ComponentPrice` summary (`project_bom._summary_points`) — that's how a price
  entered manually in the component's Prices editor (which writes the summary,
  not the ladder) reaches the BOM. Parts with neither remain unpriced.
- **BOM-only parts**: `Component.in_library=False` (column added by an
  idempotent `ALTER TABLE` in `main.py` startup — `create_all` never alters
  existing tables). Excluded in `mirror.write_symbol_libs` and both
  `kicad_http` part endpoints; needs no symbol/footprint.
- **Virtual parts**: `Component.purchasable=False` (same startup-migration
  pattern; `PATCH /api/components/{id}/purchasable`) — test points, logos,
  fiducials, mounting holes. They stay in the library and on the board, but
  their BOM lines fold into the existing `excluded` flag
  (`dnp or exclude_from_bom or not_purchasable`), so they leave totals, order
  quantities, the unpriced-line count and `stock_check` untouched. **Never
  infer this from a missing LCSC code or from the category** — real BOM parts
  (enclosures, lightpipes, the LE910R1 modem) also lack LCSC codes and share
  `Mechanical_7S` with the logo and mounting holes. Only the flag decides.
  Lines that matched no library component (`component_id` NULL) can't carry
  it — use KiCad's own "Exclude from BOM" on those symbols.
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
  delete history rows. **Only NON-EMPTY snapshots are candidates**
  (`history_points_at` skips `points == []`): an empty row records that the part
  had no ladder yet, which is not price information, and choosing one is strictly
  worse than having no history at all — `project_bom._component_data` decides
  whether to fall back to live points by testing PRESENCE in the result, so a
  present-but-empty entry silently unprices the line. `record_price_history`
  legitimately writes an empty first row for a part created before it was priced,
  so this shadowed 11 components including every enclosure and antenna: a Dongle
  batch's planned cost showed no enclosure at all while the part was plainly
  priced in the library. A corollary of append-only: a PLACEHOLDER price entered
  today and corrected tomorrow leaves the placeholder as the earliest row, so
  every historical run keeps pricing from it. That is the intended semantics —
  fixing it retroactively means deleting a history row, which is a deliberate
  invariant break and the user's call, not a robot's.
  `ProductionRun.frozen` is a LEGACY blob from the old
  freeze-at-creation model — kept for archival, never written or read.
- **A run can be re-pointed at a newer snapshot** (`RunPatch.snapshot_id`) — needed
  when a part moves INTO the schematic, since the planned BOM comes from the run's
  snapshot and would otherwise never see it (the Dongle enclosure became `ENC1` in
  commit a92e8973). The patch refuses (409) while the run carries `b<bom line id>`
  overrides: those ids belong to the old snapshot's lines, so re-pointing would
  quietly stop applying them. Runs whose components are charged directly from a
  turnkey invoice (Dongle Batch 1, `snapshot_id` NULL) must STAY snapshot-less —
  giving them a BOM invites `consume_from_bom` to draw parts the invoice already paid
  for.
- **An extra-BOM item and a schematic symbol for the same part double-count.** Once
  an enclosure gets a symbol, its `ProjectExtraBomItem` twin must go or both the plan
  and the draws count it twice (the Aqua plan listed components 324/325 once with
  refs `ENC1`/`ENC2` and once with no refs). Delete the twin anchored at the snapshot
  whose BOM *has* the part, so the copy-on-write leaves earlier revisions intact — an
  older snapshot with no enclosure line keeps its extra item and stays costed
  correctly. Note the anchoring renumbers rows: after one delete, the remaining items
  live in a NEW revision with NEW ids, so a second delete by the old id 409s
  ("does not belong to the cost list in effect at this commit") — re-read the list
  between deletes.
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

## The change feed (`services/changes.py`, `routers/changes.py`)

"What moved in the library lately, and who moved it" — one time-ordered stream
over six sources: component, symbol, footprint and skill versions, 3D model
uploads, and the lifecycle/review lane of the audit log.

- **The list is cheap; the diff is not.** A feed row carries only what one
  printed line needs. Every diff — the property table, the before/after
  renders, the text diff — is a SECOND call to `GET /api/changes/{kind}/{id}`,
  made when a row is expanded. There are ~18k events in this database and
  rendering a symbol costs a kicad-cli invocation, so a feed that computed
  diffs eagerly is not a slower feed, it is an unusable one.
- **Pagination is KEYSET, never offset.** The cursor is the last row's
  `(ts, src, row_id)` triple, which is exactly the sort key. The feed is
  append-mostly and is read while new versions land, so `OFFSET 100` silently
  repeats rows. An unparseable cursor means "start at the top", never a 500.
- **`EVENT_PREFIXES` deliberately excludes `publish` / `proposal.*`.** Those
  audit rows describe the very version rows the other five lanes already
  report, and report them WITH a diff. Including both doubles every publish.
- **3D models join the audit log for their actor.** `models3d` has no
  `created_by`; the uploader is only in the `model3d.create` row. The ~4.7k
  rows the retired YAML import created legitimately have nobody and read as
  "import". Never select `Model3D.data` in the feed — it is a `LargeBinary`
  and would drag every mesh through Postgres to print a filename.

### `GET /api/{kind}/{id}/versions/{n}/preview.svg` SELECTS; `?v=` does not

Two preview endpoints per template, and the difference is load-bearing.
`/{kind}/{id}/preview.svg?v=` always renders the CURRENT drawing (`v` is a
cache key — see `_preview`). The version-addressed route renders THAT version,
which is what a before/after pane needs and what "history lives under
`/versions/...`" already promised. Version rows are immutable, so unlike
`_preview` it can always answer `immutable`. `preview.glb` follows the same
pair, so a footprint template page can show the 3D board view that previously
hung only off a component version.

## List surfaces — the two traps that cost a second each

Both were measured on 2026-08-24 against production data (421 components, 2296
version rows, 23509 property rows).

- **`routers/util.components_with_current(db)` is the list loader.**
  `selectinload(Component.versions).selectinload(ComponentVersion.properties)`
  is the obvious way to load a list and the wrong one: it pulls the entire
  HISTORY to print one version each. It also eager-loads `footprint_version`
  with `source_text`/`parsed`/`models` DEFERRED, because `props_dict` reads
  `Footprint_Name` through that relationship and otherwise lazy-loads a whole
  `.kicad_mod` per component — the same trap `kicad_http.library_versions`
  documents. Callers MUST use the returned `{component_id: version}` map:
  `current_version(comp)` reads `comp.versions`, which is unloaded here and
  would lazy-load the history back one component at a time. Pass the map to
  `review.states_for_components(..., cvs=live)` for the same reason.
  `GET /api/components` 1.22s -> 0.21s; `/api/reviews/queue` 1.36s -> 0.22s.
- **The identity map holds WEAK references.** `db.get(ChecklistVersion, id)`
  looked free — the repeat should come from the identity map — but
  `_checklist_items_of` keeps no reference to the object, so it is collected
  and every one of the 857 pre-snapshot review records re-queried. 299 of the
  review queue's 318 SQL round trips were the same three rows. Checklist
  VERSIONS are immutable, so `review._CHECKLIST_ITEMS` memoises them for the
  life of the process. Any other hot `db.get` on an immutable row is suspect
  for the same reason.
- **`GET /api/flasher/devices` pages in SQL** — 5502 rows are 1.98 MB and 2.5s,
  which no rendering trick improves. It returns `{items, total, offset, limit,
  has_more}`, and its filtering and sorting are SERVER-side (`_DEVICE_SORTS`,
  `_DEVICE_FILTERS`, both allow-lists because the column name arrives in a
  query string): a client holding one page cannot honestly answer "no rows
  match". 2.50s / 1.98 MB -> 0.11s / 38 kB.
- **`POST /api/components/{id}/versions` records the real actor.** It hardcoded
  `created_by="user"` (and `actor`/`approved_by`), so every component edit made
  in the browser was anonymous in its own history and in the change feed, while
  symbol and footprint publishes had always passed the signed-in name. Rows
  written before 2026-08-25 keep saying "user"; that history is not
  recoverable.

## A superseded PCM artifact stays downloadable (the "hash does not match" trap)

`ZIP_EPOCH` already handles half of this failure: the same content must always
produce the same bytes. The other half is retention. PCM caches `packages.json`
and refreshes the repository only when asked, so a user can hold a record
naming a build tag the mirror has already moved past — and **every component
publish moves the mirror**. Deleting the superseded zip immediately turned that
stale record into a 404, and KiCad hashes the 80-byte JSON error body like any
other download and reports:

    Downloaded archive hash for package 7Sigma Library does not match
    repository entry.

which reads as corruption and is nothing of the kind (reported 2026-08-25 on
`library-fb1c4c239d2fr10.zip`; the chain served at that moment was perfectly
self-consistent). `ensure_built`'s prune therefore keeps, besides the current
build and this revision's personal plugin zips, any artifact that is
`_within_grace` — under `_GRACE_DAYS` old AND inside its package's
`_GRACE_BYTES` budget, where newer siblings claim the budget first.

**The budget is in bytes, not generations, and the difference matters.** A
generation cap looks equivalent and is not: the library package rebuilds on
every component publish, so "keep the last two" is minutes of cover on a busy
day, while the retention has to span however long a user leaves a pending
update sitting in PCM. Sized per package, the same 14 days buys ~400 library
zips (0.5 MB each) or one extra 3D models zip (260 MB).

**A pending update is pinned in the CLIENT, and no server retention reaches
back past it.** `installed_packages.json` records the download URL and sha of
each version PCM has seen, and an update uses that record rather than
re-reading `packages.json` — so refreshing the repository does not rewrite it.
A user whose recorded version has aged out of the grace window has to uninstall
and reinstall the package.

**A stale `packages-<tag>.json` is served from the build ITS OWN TAG names**,
not from the current one — `pcm.meta_for_packages_file` loads `meta-<tag>.json`
and `pcm_artifact` personalises that. Answering from the current build fails the
hash the client's cached repository record published, and falling through to the
shared file on disk hands KiCad download URLs with no `?t=` on them, so every
zip fetch after it is unauthenticated. Retention is what makes this work: the
grace window keeps the zips an old index names, its personal plugin zip
included.

**Diagnosing this class of report**: fetch `repository.json`, then
`packages.json`, then the zip, and compare the advertised `download_sha256`
against the served bytes. A 404 body, not a hash difference, is the usual
answer — and it means the client is stale, not that the package is broken.

## Each PCM package is versioned from ITS OWN content

A package's version string is what PCM compares to decide "update available",
and the three packages differ in where it comes from: `library` and `models3d`
derive it from the mirror manifest's `generated_at`, `sync` carries the manual
`PLUGIN_VERSION`. **A content package keeps its previous version while its own
subtree hash is unchanged** — `_resolve_package` reuses the whole cached entry,
version included. Only the plugin (`pinned_version=True`) takes the passed-in
version on a cache hit, because that one is authored by hand and a bump with
untouched sources still has to reach the repository.

Getting this wrong is expensive in both directions, and the module has now been
wrong in both:

- Reuse the zip but keep the old version, and a `PLUGIN_VERSION` bump becomes a
  silent no-op — nobody is offered the new plugin.
- Put the version IN the reuse test, and the 260 MB models zip is re-encoded on
  **every mirror regeneration**, because a content package's version follows the
  mirror timestamp and that moves on every component publish. Same content, same
  URL, same bytes (`ZIP_EPOCH`), minutes of CPU — and PCM offered every user a
  260 MB update for an unchanged 3D model tree. Measured 2026-08-25: seven
  rebuilds of `models3d-68a2993fcf88r10.zip` in one morning of footprint edits.

The module docstring has promised per-content versioning since it was written;
until 2026-08-25 the code did not do it. When the reuse rule changes again,
check both failure modes before believing the fix.

## Simulation models (`services/simmodel.py`, `sim_store.py`, `routers/sim_models.py`)

Versioned SPICE subcircuits (`SimModel`/`SimModelVersion`, auto-publish like
everything else) plus ONE link per base symbol (`SymbolSimLink`: model +
`{pin number: port}` map). The mirror emits every model into
`Symbols/7Sigma_sim.sp` and turns each link into four `Sim.*` property rows on
every component of that symbol.

A link has **two modes**, and the switch is permanent rather than a migration
aid:

| `SymbolSimLink.mode` | Authored | Derived |
|---|---|---|
| `model` | the subcircuit text, and the `{pin: port}` map | nothing |
| `composed` | `composition`: blocks, their nodes, ties, unmodelled pins | the `.subckt`, its port list, and the pin map |

Facts that are not obvious from the code:

- **`Sim.*` rows land on COMPONENT instances, never only in `lib_symbols`** —
  KiCad's netlister ignores library-level sim properties. `Sim.Pins` is
  mandatory: without it KiCad falls back to raw pin order, counts hidden
  stacked pins and silently mis-wires.
- **The link is keyed on the Symbol, unversioned** (like
  `Footprint.display_name`), so linking sixty symbols does not bump sixty
  symbol versions. Staleness is two fingerprints: the symbol side hashes pin
  numbers + electrical types ONLY (`simmodel.link_material_sha` — a cosmetic
  pin-length edit must not flag links), the model side hashes the PORT LIST
  only (param/topology edits carry links untouched). A stale link's Sim fields
  are WITHHELD from the mirror, with a warning, until re-confirmed —
  re-saving the map in the UI or via `set_symbol_sim_link` is the confirm.
- **Path rewrite at egress**: the mirror writes the canonical
  `${SEVENSIGMA_DIR}/Symbols/7Sigma_sim.sp`; `kicad_http.part_payload` and the
  PCM library zip substitute the installed path
  (`pcm.SIM_LIB_INSTALLED`, under `${KICAD10_3RD_PARTY}`). The `.sp` file is
  part of the library package's subtree hash — dropping it from that tuple
  makes model edits a silent PCM no-op.
- **A component's own `Sim.Params` row rides on top**: link-derived rows are
  prepended in the generator, so a per-component property with the same key
  wins. Datasheet numbers (GAIN, V_BR at test current, TPD…) belong on
  components as `Sim.Params`; topology belongs in the model.
- **`exclude_from_sim` is DERIVED, never authored** — emitted in THREE places, and
  the HTTP one is the only one an existing schematic ever sees:
  `generator.set_exclude_from_sim` for the base library and the per-category libs,
  and `kicad_http.part_payload` for the catalog record. KiCad places parts by their
  HTTP `lib_id`, and **`Update Symbols from Library` rewrites the instance from the
  HTTP record, not from the base `.kicad_sym`** — with an ABSENT flag read as "not
  excluded", so the payload must state it explicitly. Patching only the `.kicad_sym`
  looks right in the package and changes nothing in anyone's schematic. A generated symbol
  stays simulatable when it has a link, or when its reference prefix is `R`, `C`,
  `L` or `#PWR` — SPICE builds those from the Value field with no model at all
  (`R116 … 100k` is a complete element), and power symbols are net names, not
  devices. Everything else with no link is excluded, because it would otherwise
  emit `U47 __U47` and stop the run. Three consequences:
  - **`_base_symbol_fingerprint` hashes the LINK SET as well as symbol versions.**
    Without that the base library is skipped when only a link moved, and the flag
    lags until some unrelated symbol is edited.
  - **A stale link still counts as linked.** Its Sim fields are withheld, so the
    netlist fails loudly rather than quietly dropping a part that belongs there.
  - **Never exclude a two-pin part in series with a net.** A fuse, polyfuse,
    ferrite bead or NTC that is excluded opens a live rail with NO error, which is
    worse than the loud failure a missing model gives — hence `sigma_fuse`,
    `sigma_ferrite` and `sigma_ntc`, which are one resistor each and exist purely
    to keep the net connected.
- **`in_bom` and `on_board` are DERIVED the same way, from the top-level
  category `Simulation`** — `generator.set_build_exclusions`, applied in
  `mirror.write_symbol_libs` (both the per-category libs and the base lib) and in
  `kicad_http.part_payload`. That category holds parts that exist ONLY to drive a
  simulation: a PT1000 stimulus, a vehicle emulator, a load. A harness sheet lives
  in the same project as the board, so a stimulus part that does not say it is off
  the BOM lands in the purchase order and on the layout. Same must-be-stated
  argument as `exclude_from_sim`: KiCad reads an absent attribute as "included".
  Two details that are easy to miss:
  - **A base symbol has no category.** `set_build_exclusions` is given
    `Simulation` for a template only when EVERY component drawn from it is a
    simulation part. A template shared with a real part stays on the board — the
    per-category library and the HTTP record carry the exact per-component answer,
    and `7Sigma_Base.kicad_sym` is only the fallback drawing.
  - **`_base_symbol_fingerprint` therefore hashes every published component's
    category too**, next to the symbol versions and the link set. Moving the last
    component out of `Simulation` changes the base library with no symbol version
    touched, and without the categories in the hash the flag lags.
- **KiCad's embedded ngspice runs `ngbehavior=ps lt a`** (Compatibility mode
  "PSpice and LTSpice", `schematic.ngspice.model_mode` 4 in the `.kicad_pro`; 0 is
  "User configuration" and applies no flags). In that mode `$` is NOT a comment —
  numparam feeds the text to the expression parser and the model fails to load —
  and an XSPICE `.model … adc_bridge` inside a subcircuit does not resolve. Use
  `;` for in-line comments, and reproduce that parser without KiCad by putting
  `set ngbehavior=pslta` in `<dir>/scripts/spinit` and running
  `SPICE_LIB_DIR=<dir> ngspice -b …`. KiCad's bundled ngspice is 45.2, not
  whatever is on PATH.
- **Model names are the namespace**: `sigma_` prefix enforced
  (`sim_store.NAME_RE`), and the row name must equal the `.subckt` name.
  `kind` is `primitive` (a building block), `part` (a hand-written wrapper for
  one device) or `composed` (generated — see below). A symbol may link to ANY
  of the first two: a diode, a switch or a 5-pin op-amp IS the primitive, and
  a picker that filtered primitives out would hide most working links from
  their own editor (`routers/sim_models.get_symbol_sim_link`). `kind` is
  otherwise cosmetic — it orders `write_sim_lib`'s output and nothing else.

### Composed models (`services/simcompose.py`)

A wrapper whose whole body is instance lines and tie resistors holds no
behaviour, so it is generated rather than typed. `simcompose.compose()` turns a
block design into a `.subckt`; `sim_store.set_symbol_sim_composition` publishes
it as a normal `SimModel` row with `kind="composed"` and name
`sigma_sym_<symbol slug>`. Everything downstream was therefore untouched — the
mirror emits it like any model, `generator.sim_props` points `Sim.Name` at it,
`Sim.Pins` comes off the same derived map.

- **One wrapper port per unique symbol pin, never fewer.** It is tempting to
  alias a power MOSFET's three source pins onto one port and drop the ties. It
  is wrong: the schematic may put those pins on three different nets, and one
  port carries one node. Ties are real resistors inside the subcircuit, which
  is also what `sigma_nmos_pwr8` did by hand. The payoff is that the port list
  is `p1 p2 p4 …` by construction, so **`Sim.Pins` is derived and cannot be
  mis-authored** — the swap `validate_pin_map` openly cannot catch stops being
  possible in this mode.
- **Staleness is computed, not stamped** (`sim_store.composed_stale_reasons`,
  one implementation, three callers: mirror, link editor, validator). A
  composed link is unusable when its design no longer builds against today's
  block models, or when the published wrapper is not what the design builds.
  Both self-heal; a stamped fingerprint never does.
- **A block model's publish REGENERATES its dependents**
  (`sim_store.recompose_dependents`, called from `propose_sim_model_version`
  and guarded on `kind != composed` so a wrapper's own publish cannot recurse).
  Where a hand-written wrapper would go stale and wait for a person, a
  composition is rebuilt — and when it cannot be, the failure names the port
  that lost its node.
- **Generated text must be byte-stable, so parameters are emitted SORTED.**
  `SimModelVersion.parsed` is a JSONB cache and Postgres reorders a jsonb
  object's keys (shortest first, then bytewise), so the same model yields one
  key order in the session that parsed it and another after a round trip.
  Emitting in dict order made every mirror write report the wrapper as behind
  its own design.
- **The wrapper is owned by its link.** Removing the link, or switching back to
  `model` mode, deletes it (`sim_store._drop_generated`). Hand-written wrappers
  had no such owner, which is how `sigma_74hc21` and `sigma_buf2` sat in the
  library linked to nothing.
- **Parameter bindings** are per block: `$shared` (default — every dual-gate
  package here passes one value to both halves, because both halves are one
  die), `$shared:NAME` to share under another name, `$own` for one wrapper
  parameter per block (`G1_TPD`), or a literal. `composition.defaults`
  overrides a wrapper default where it differs from the block model's own —
  `sigma_tvs_bi` declared `VBR=26.7` while its `sigma_tvs_leg` block defaults
  to 13.3, and a component with no `Sim.Params` row runs on whichever the
  wrapper states.
- **`cli/simrecompose.py`** converts the hand-written wrappers, then prunes
  them: `plan`, `apply --verify`, `prune`, `orphans`. The conversion is
  interface-preserving by construction (`$shared:NAME` keeps every parameter
  name, `defaults` keeps every default), so no component's `Sim.Params` row
  moves. `--verify` proves it by diffing the declared interface. `orphans`
  reports building blocks no symbol can reach and never deletes: an unused
  primitive is library surface someone put there on purpose.
- **The rail heuristic has ONE half, and the other was deleted, not widened.**
  What survives is "a rail-shaped port claimed by a pin that is not a power
  pin" (`simmodel.is_rail_port` — a rail stem plus an optional channel number
  or polarity letter, so `vdd1`, `gnd2`, `vinp` and `vs` count, which a flat
  list of eleven names did not). What went was the mirror check, "a `power_in`
  pin on a port that is not rail-shaped": it cannot tell an LDO's `in` from an
  op-amp's `in+`, because the difference lives in the model and not in the
  name, so no widening could fix it. It reported sixteen correctly wired links
  in this library and not one real fault. Nothing is lost — each port takes
  exactly ONE pin, so a supply pin landing on a signal port displaces another
  pin onto the real rail port, and that pin is not a power pin, which is what
  the surviving half tests.
- Validator machine items: `sym.sim_link` (map errors / stale / composition
  errors / the rail warning above) and `cmp.sim_params` (keys must be declared
  by the linked model). Deliberately NOT checklist-seeded — seeding un-answers every
  existing subject (the `cmp.datasheet_text` incident); the user decides.
- **`kiutils` is patched locally**: upstream ran `Sim.Library` values through
  `PureWindowsPath`, turning `/` into `\\` (`api/kiutils/items/common.py`,
  marked with a comment). Keep the patch when vendoring a newer kiutils.
- The UI lives on Templates → "Sim models" (list + new-model paste,
  `pages/SimModelDetail.tsx` — which refuses to hand-edit a generated model and
  offers deletion only while nothing links it) and on each symbol template page
  (`components/SimLinkCard.tsx`). That card carries both modes. The composed
  editor assigns **port → node**, not pin → port: a block has a short list of
  named ports (`a b c d y vcc vee`) while the symbol has twelve unnamed pins,
  and "gate 1 input A comes from pin 1" is the only direction that survives
  past one block. Beside it sits the **pin coverage** panel, the inverse view,
  which is where a missed pin or a crossed rail is visible — and under both,
  the generated netlist itself, because generation nobody reads is generation
  nobody checks.

## The field solver (`services/fieldsolver/`, `routers/field_solver.py`)

A 2D quasi-TEM FEM solver for controlled-impedance geometry — microstrip,
stripline, coplanar and differential, with via fences. `services/fieldsolver/` is
a self-contained package (P1 triangles on a Triangle mesh, scipy sparse solves)
that imports nothing from the platform; the router is the platform half. Design
record: `docs/decisions/0002-field-solver-in-the-platform.md`.

- **Its dependencies are new and one of them is licence-constrained.** numpy,
  scipy, shapely and `triangle`; Triangle is free for personal and research use
  but NOT for commercial distribution, and it publishes an amd64 wheel with no
  sdist that builds on Python 3.12. Hence the `platform_machine == 'x86_64'`
  marker in `pyproject.toml` and the LAZY import in `mesh.py::_tr()` — an arm64
  dev box runs the whole platform and answers 503 for solver calls alone. The
  images are linux/amd64, so production has it.
- **User-defined stackups and rule sets live in Postgres** (`FieldStackup`,
  `FieldRuleSet`), never in JSON beside the code. The solver keeps them in
  module state because it is a pure library, so every request that reads or
  solves calls `_sync_library(db)` first — two small selects. Stackup writes are
  **admin-only** (`require_admin`), because a stackup is a shared fact about how
  boards are made.
- **A board's stackup and profiles are commit-versioned** in
  `services/field_state.py`, which mirrors `services/cost_state.py` exactly:
  `revision_for` selects by commit date, `revision_for_edit` copies on write, and
  the profile COPIES carry their results. Never delete a profile because the
  stackup changed — `is_outdated` compares the stored `stackup_sha` against the
  board's current one and the UI says so.
- **`stackup_sha` hashes layers, coating and finish only.** Renaming a stackup
  must not invalidate anybody's numbers.
- **A stored result holds numbers, not fields.** Summary, sweep, C/L, notes and
  the geometry outline; never the solved mesh (tens of megabytes per frequency
  frame). That is what makes reopening a profile instant and why the field
  picture alone needs a re-solve.
- **Jobs are cancellable and abandoned jobs cancel themselves.** The progress
  callback raises on a cancel flag; `DELETE /api/fieldsolver/jobs/{id}` sets it,
  and a reaper cancels any job whose client has not polled for 20 s. A solve
  holds a core and hundreds of megabytes, so a closed tab must not keep one.
- **The search pool is capped** (`design.WORKERS`, default 4,
  `FIELDSOLVER_WORKERS` to override) and `design.kill_stray_workers()` sweeps
  orphans when nothing is running. An unbounded pool once left 40 GB of workers
  behind and pushed the machine into swap.
- **One factorisation per run.** `fem.Solver(mesh, K, pre)` reuses the
  design-frequency LU as a CG preconditioner for every sweep point, because Dk
  dispersion moves K by only a few percent: a 31-point sweep on a 78k-node mesh
  went from 12.1 s to 4.9 s with results identical to 7e-13 %.
- **The model is floored at 1 MHz** (`F_MIN_HZ`). Below that the
  perfect-conductor assumption stops describing a board. An eddy-current solver
  covering DC through the skin-effect transition was written, validated against
  the analytic DC loop resistance and then removed on purpose — do not
  reintroduce a current-distribution view without reinstating it.
- Physics tests live in `api/tests/fieldsolver/` (`python -m pytest
  tests/fieldsolver -q` from `api/`): a parallel-plate line with exact C, Z0 and
  eps_eff, its analytic conductor loss, plus `validate.py` for the closed-form
  comparisons (microstrip Hammerstad-Jensen, stripline Wheeler, CPWG conformal).

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
- **The KiCad HTTP catalog is on the symbol chooser's critical path — never
  load the whole library per request.** `EnumerateSymbolLib` walks every
  category and calls `parts/category/{id}.json` once each, so one slow handler
  is multiplied by the category count. Both part endpoints therefore go through
  `kicad_http.library_versions(db)`, which expresses `current_version(comp)` +
  `in_library` as a SQL filter (`ComponentVersion.id == Component.current_version_id`)
  instead of loading every component with every version and filtering in Python
  — that cost ~0.3s per category, ~4s per chooser open on 327 components.
  Two traps it also closes: `props_dict` reads `Footprint_Name` through
  `cv.footprint_version`, which lazy-loads a whole `.kicad_mod` body per
  component unless `source_text`/`parsed`/`models` are deferred; and the
  `Component` join needs `contains_eager` or the parent row is re-fetched per
  row. Verified 2026-07-30: 4.14s -> 0.38s wall clock for 15 categories,
  payloads byte-identical.
- **KiCad caches the catalog itself, and its defaults are the reason a fast
  backend still felt slow.** `source.timeout_categories_seconds` (KiCad default
  **600**) and `source.timeout_parts_seconds` (default **30**) live in the
  `.kicad_httplib`; the category one expires the part lists of ALL categories at
  once, so with the default the first "Add Symbol" click in any 10-minute window
  refetches the entire catalog. `routers/kicad_sync.py::httplib_file` now emits
  both from `httplib_timeout_categories_s` / `httplib_timeout_parts_s` (3600 /
  600, editable in Settings). The cache is per KiCad session and always cold on
  startup, so the server-side cost still matters. **The values are baked into
  the downloaded file** — changing the knob needs a re-download, exactly like
  `httplib_token`.
- **KiCad field visibility is curated ON THE BASE SYMBOL — never per
  component** (user decision 2026-08-04). The component only holds values; a
  key the base symbol draws visible (R's Value, C's Voltage/Dielectric, LED's
  Color) is visible on every component using it, any other key is hidden, and
  the dormant per-row `layout` effects are the only override. That is the rule
  `apply_properties` bakes into the mirror symbols, and the HTTP catalog must
  emit the SAME answer — `generator.schematic_field_visibility` (cached per
  base-symbol version id) is the one implementation; never consult
  `ComponentProperty.hide`, which the generator has never read and which is
  True on almost every imported row. Both wrong answers shipped once: forcing
  Value visible showed it on every testpoint; obeying the `hide` column hid it
  on every resistor. The column stays only as a dormant import artifact, and
  the web editor no longer shows it. To make a category display a parameter,
  edit the base symbol's property effects — one symbol proposal.
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
- **The mirror refresh is incrementally cached — keep the guards.**
  `update_mirror_symbols` runs after *every* approval, so `services/mirror.py`
  memoises the two parts that almost never change. (1) `write_manifest` keys
  SHA-256 digests on `(mtime_ns, size)` in `_MANIFEST_HASHES`: the tree carries
  ~1.4 GB of 3D models that a property edit cannot touch, and re-hashing them
  cost ~1.3s per approval. (2) `write_symbol_libs` rebuilds
  `7Sigma_Base.kicad_sym` only when `_base_symbol_fingerprint(db)` (every
  `Symbol.current_version_id`) moves or the file is missing — it ignored
  `only_tops` and re-parsed all ~140 base symbols every time, ~0.7s. Both
  caches are **in-process and advisory**: each is validated against real
  filesystem/DB state on every call, so a restart or a `rebuild_mirror` wipe
  costs one full rebuild and never a stale artifact. If you add a mirror
  artifact with its own rebuild cost, follow the same shape — cache keyed on
  observable state, never on "we think nothing changed". The manifest's JSON
  format is public (PCM builder, sync clients); don't add cache fields to it.
- **`db.expire_all()` before any post-commit mirror refresh.** The session uses
  `expire_on_commit=False`, and services create new versions via `db.add()`
  without appending to already-loaded relationships — so after calling a
  service that commits (e.g. `add_component_file`), a preloaded `comp.versions`
  is stale and `current_version(comp)` returns None, silently skipping
  `update_mirror_symbols`. Precedents: `create_version`, `proposals.approve`,
  `components.add_file`.
- **IPC plugin buttons appear in the PCB EDITOR ONLY.** `api.v1.schema.json`
  accepts five scopes (`pcb`, `schematic`, `footprint`, `symbol`,
  `project_manager`), but KiCad implements the IPC plugin system in the PCB
  editor alone — the other editors are "planned" (dev-docs, *For Add-on
  Developers*). The enum being permissive is not a capability; do not read it
  as one, and do not promise a button in the footprint or symbol editor.
  Verified against KiCad 10 on 2026-07-31: both actions declare all four
  scopes, and both render in the PCB editor only. The extra scopes are
  harmless — the plugin still loads — so they stay as forward compatibility.
  This costs the push plugin nothing: it reads the SAVED library files off
  disk, so the focused editor is irrelevant. Edit in the footprint editor,
  save, push from the PCB editor.
- **"Did I edit this?" is a CANONICAL comparison, never a byte hash**
  (`services/pcm_plugin/kicad_canon.py`, shared by both entrypoints). KiCad
  rewrites the WHOLE file it saves and writes tokens the platform's generator
  omits — every `(property …)` gains `(show_name no)` and
  `(do_not_autoplace no)`, every symbol gains
  `(duplicate_pin_numbers_are_jumpers no)` and `(in_pos_files yes)`, pins come
  back sorted, and every footprint pad and graphic gets a fresh `(uuid …)`.
  Measured 2026-08-20: editing ONE symbol changed the text of all 183 entries
  in `7Sigma_Base.kicad_sym`, Push offered to propose every one of them, and
  Sync froze the whole library. The canonical form drops default-valued tokens
  and uuids, normalises numbers and sorts the unordered children of
  `(symbol …)` / `(footprint …)`. It is a COMPARISON KEY: it is never written
  to a library file. Extend `DEFAULTS` when a KiCad release starts printing
  another default — the symptom is "everything is suddenly edited" right after
  a KiCad upgrade.
- **The unit of protection is the drawing, not the file.** Every base symbol
  lives in one generated `.kicad_sym`, so "never overwrite a file edited here"
  meant one edited symbol blocked updates to the other 182.
  `_conflicting_entries` finds the edited ENTRIES and `_merge_symbols` keeps
  only the ones the user chose; the entries it keeps must NOT be re-recorded
  (`_record_written(..., skip=…)`), or the next sync overwrites the unsent edit
  and Push forgets it exists.
- **A conflict row is ONE ITEM in EVERY path, including the orphan path.** The
  rule above covered the normal case and missed the other one: a library file
  the upstream package no longer carries (a rename upstream, a stale duplicate)
  was emitted as a single row, hardcoded `"kind": "footprint"` — so a
  `.kicad_sym` appeared as one line under the "Footprints" header whose "server"
  answer deleted all 196 symbols at once. Reported 2026-08-24. `_scan_conflicts`
  now splits it per entry, and the matching prune in `_apply_package` rewrites
  the file with `kicad_canon.drop_symbols` instead of unlinking it, removing it
  only when every entry was released. Two things follow: the prune must clear
  `_LOCAL` for the entries it drops and the file-level record when it rewrites
  (the kept entries keep their own records, which is what Push reads), and it
  must name only the entries that HAD a row in `kept_local` — the unedited rest
  are stale copies of upstream drawings, and reporting them made one notify list
  195 symbols.
- **3D models carry per-file records too, since plugin 1.3.0, and their check is
  stat-first.** Models used to bypass the conflict window entirely, and not
  merely coarsely: `_sync_models_delta` compared the upstream sha against the
  RECORDED sha in `models_state.json`, never against the bytes on disk, so a
  model edited here read as current, was never re-fetched, was never asked
  about, and was overwritten in silence by the next full-zip fallback.
  `local_state.json` held zero model keys. What blocked the fix was cost — 4745
  models, about 1.4 GB, is not hashable on every sync. So each record is now
  `{"s": sha, "m": mtime, "z": size}` and `_model_edits` stats the tree and
  hashes ONLY the files whose size or mtime moved (measured: 3 reads for 3 edits
  out of 50 files). A bare-string record is pre-1.3.0 and adopts the current
  stat at the sha it already asserted, so the upgrade reports no edits rather
  than a wave of false ones. Consequences to keep: `_sync_models_delta` is split
  into `_scan_models_delta` (read-only, returns a plan plus rows) and
  `_apply_models_delta`, because the single-dialog rule below forbids asking
  mid-write; a model the user KEEPS must not be re-recorded, so the record
  cleanup keys on what is still ON DISK rather than on `upstream`; and the
  full-zip path must WRITE the records it builds — it used to delete
  `models_state.json`, which would now leave the next sync unable to tell an
  edit from a write.
- **A two-way clash is a QUESTION, not a policy.** When a drawing changed here
  AND on the platform, the old rule kept the local copy silently and for ever,
  so an approved fix could never come back down — the only escape was deleting
  the file by hand (reported 2026-08-23, the mirrored KSZ8864 footprint).
  Sync now runs in two passes: `_fetch_package` + `_scan_conflicts` gather every
  clash across EVERY package without writing anything, `conflict_ui.resolve`
  asks once in one window, then `_apply_package` writes. Keep the passes
  separate — asking per package would put three dialogs in front of one sync,
  and asking mid-write would leave a half-applied package if the user cancels.
  `_members()` is deliberately shared by both passes: if the scan and the write
  disagreed on which zip entries are in play, the dialog would ask about a file
  that never gets touched.
- **Every failure path in the conflict UI resolves to "mine".** Cancel, a closed
  window, no wx, no osascript, an absurd conflict count — all keep the local
  copy, which is what the plugin did before the dialog existed. Refusing an
  update is recoverable; destroying an unsent drawing is not. `resolve()` always
  returns a decision for every key so no caller has to handle a gap. wxPython
  ships inside KiCad (4.2.2 on the 3.9 runtime), with the AppleScript list Push
  already uses as the fallback.
- **Reconcile, or an approved edit stays pending for ever.** A sync that
  refuses to clobber a local edit must still notice when that edit IS the
  platform's copy now — pushed, approved and come back. Without it the baseline
  keeps the pre-edit hash, the file is "edited" for ever, and Push keeps
  offering to propose it again (reported 2026-08-20, five footprints). Push
  carries the same belt-and-braces check: it verifies the FLAGGED items against
  the live mirror and corrects the baseline, so a wrong state file self-heals.
  A failed fetch leaves the item flagged — offering an edit twice is annoying,
  losing one is not recoverable.
- **The prune must never delete a library file the plugin did not write** —
  unless the user asked for it in the window. It is either a local edit or a
  footprint drawn here and not yet pushed; the old rule deleted anything absent
  from the package, which destroyed new work before Push could send it. **Models
  are no longer exempt** (they were, while they carried no record): a model with
  no record was placed here by hand and a model whose record is dirty was edited
  here, and both now survive a prune unless the dialog released them. A model the
  plugin wrote and nothing touched still prunes silently — that is a genuine
  upstream deletion, not work.
- **Every local change is offered back, not just the two-way clashes.** A
  drawing edited here while the platform's copy stayed put is not a conflict,
  but "throw my edit away and take the platform's copy" is still something only
  this window can do — otherwise the answer is "delete the file by hand". So
  `_scan_conflicts` emits three kinds of row, each labelled with its `note`:
  changed on both sides, changed only here, and exists only here (where the
  server side means DELETE). The cost is that a package with no upstream change
  is fetched anyway while any local edit is outstanding (`_has_local_edits`
  forces it) — 0.5 MB for the library package, and the only way the window can
  show what the platform would give back. Every failure path still resolves to
  "mine".
- **Push carries the 3D model, or the footprint cannot be pushed at all.** A
  footprint drawn here points its `(model …)` wherever the file actually sits —
  ~/Downloads, KiCad's own `3dmodels/` tree, a project folder — and
  `geometry_proposals` refuses any path outside `${SEVENSIGMA_DIR}/3DModels/`.
  So `push.py` resolves each off-library reference on disk
  (`model_paths.resolve`, expanding `${KICAD*_3RD_PARTY}` and
  `${KICAD*_3DMODEL_DIR}` from the install layout — KiCad does not export its
  path variables to a plugin), asks where each one goes (`model_ui`, suggested
  path editable), uploads them to `/api/models3d/upload` FIRST, then rewrites
  the reference and sends the footprint. A reference whose file is missing
  blocks that footprint with a named error rather than letting the platform
  answer with a validation refusal.
  - **The local file is repointed at the installed copy afterwards, and its
    baseline is deliberately NOT re-recorded.** Repointing stops the model
    vanishing when ~/Downloads is cleared and stops the next push re-uploading
    it; leaving the baseline alone means the next sync settles the file by
    comparing drawings, which is the one path that cannot lose an edit if the
    mirror is still rebuilding. The rewritten path uses `THIRD_PARTY_VAR`,
    baked into the template by `_plugin_files` as `__THIRD_PARTY_VAR__` — the
    same constant the library zip's rewrite uses, so `to_platform_text` undoes
    exactly what was written and the round trip is byte-stable.
  - **The suggested folder follows what the library already does**: the
    footprint's current model folder, else the source file's own `*.3dshapes`
    folder (a model adopted from KiCad keeps KiCad's category), else
    `7Sigma.3dshapes/`. Nineteen hand-uploaded files sit loose at the root of
    `3DModels/` from before that rule existed.
- **A missing baseline means "unknown", and Push must FLAG an unknown item.**
  The two rules above combine into a trap: Sync withholds a record for an entry
  it kept back, so a drawing edited before the first sync that protected it
  never gets a baseline, and no later sync writes one. Push treated "no record"
  as "cannot judge", listed the item in a footnote and offered it to nobody —
  a moved pin on BTS723GW was unpushable and Push reported "no local changes"
  (2026-08-21). `_changed` now flags an unrecorded item and lets `_drop_settled`
  settle it against the live mirror, which is the only test that can tell an
  unrecorded edit from an unrecorded untouched file. Never re-introduce a
  branch that answers "unknown" with silence.
- **`local_state.json` records both hashes** (`{"r": raw, "c": canonical}`) and
  still reads a bare string as a pre-1.1.0 raw-only record. Dropping that
  fallback would make every installed file read as edited on the first run
  after an upgrade. `models_state.json` follows the same shape for the same
  reason — `{"s","m","z"}` now, a bare sha before 1.3.0 — and it is PRIVATE to
  `sync.py`: nothing else reads it, which is what made the format change safe.
- **The dialog has two row ceilings, not one.** Answers are per item now, so a
  single sync can legitimately raise hundreds of rows and collapsing them all to
  "kept everything" is the worse answer. `conflict_ui._WX_MAX_ROWS` (600) is the
  give-up point; `_SANE_ROWS` (200) now gates only the AppleScript backend,
  whose `choose from list` cannot be scrolled sensibly. Notifications that list
  names go through `_names()`, which caps at 8 plus a count — a macOS
  notification truncates anyway.
- **Two constants gate whether a plugin change reaches anyone, and both are
  manual.** `PLUGIN_VERSION` is what PCM compares to decide "update
  available", so shipping plugin source without bumping it is a silent no-op.
  And `ensure_built()` short-circuits on `meta-<tag>.json`, where `tag` hashes
  the mirror digest plus the plugin FILE contents — NOT `pcm.py` — so a
  `PLUGIN_VERSION` bump on its own never rebuilds the repository either. Any
  `pcm.py` edit that changes what a package advertises needs `BUILDER_REV`
  bumped too. Both were missed in sequence on 2026-07-31 and the repository
  kept advertising 1.0.4 through four deploys.
- **KiCad PCM/plugin gotchas** (`services/pcm.py`, `services/pcm_plugin/`):
  package identifiers allow NO underscores (dots/dashes only) but KiCad
  replaces dots with underscores for install directories; `license` must be
  a value from the schema enum (`unrestricted` for in-house); python-runtime
  IPC plugins REQUIRE a `requirements.txt` or env setup silently aborts and
  the toolbar button never appears; **KiCad's bundled Python has NO usable CA
  store on macOS** (its compiled-in cafile path does not exist inside the app
  bundle), so every `urlopen` of an https URL fails with
  CERTIFICATE_VERIFY_FAILED — first hit when the platform moved to
  `https://disfunction.cc` (2026-08-03, plugin 1.0.8). Both templates build an
  SSL context from certifi (in the plugin venv via `requirements.txt`) with
  `/etc/ssl/cert.pem` as the stdlib-only fallback; never disable verification
  — the push plugin carries a write credential; validate generated metadata against
  `go.kicad.org/pcm/schemas/v1` and the plugin manifest against KiCad's
  shipped `api.v1.schema.json` before shipping. The library package ships
  ONLY the deduplicated `7Sigma_Base.kicad_sym` (written by
  `mirror.write_symbol_libs`) + footprints — HTTP-catalog parts reference
  base drawings (`symbolIdStr = HTTPLIB_SYMBOL_LIB:<base_component>`), so
  adding components must never bump the library package. 3D model updates
  flow as LZMA deltas (`POST /api/kicad/pcm/models-delta`).
- **The sync plugin sweeps the install directory on EVERY run, before it
  fetches anything** (`_sweep_strays` + `_repair_lib_tables` in
  `pcm_plugin/sync.py.tmpl`). The KiCad user directory usually sits in iCloud
  Drive (`~/Documents/KiCad/<ver>`), and the file provider uniquifies a
  colliding folder name: the PCM extracts `7Sigma.pretty` over a copy iCloud
  still holds and an EMPTY `7Sigma 2.pretty` appears beside it. KiCad's PCM
  registers every `*.pretty` in a package, empty or not, so the user gets a
  second, broken footprint library row. Two rules follow. The sweep cannot live
  in the apply path — the install that creates a stray also records the package
  as current, so apply is the one path that never runs again (seen 2026-08-25:
  the prune at the end of `_apply_package` had been there all along and the
  stray survived it). And deleting the folder is only half the repair: the row
  the PCM already wrote into the global `fp-lib-table` must go too, or KiCad
  reports a missing library forever. The table edit is deliberately narrow — a
  row goes only when its URI resolves inside a `com_sevensigma*` install
  directory AND that path is gone — and it asks for a KiCad restart, because
  KiCad holds the tables in memory and can write them back on exit.
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

### The personal PCM repository (how a token reaches KiCad)

One URL per user — `…/api/kicad/pcm/repository.json?t=<token>` — installs the
library, the 3D models AND a sync plugin with that token already inside it. The
user pastes once and never types a credential.

- **The three documents are chained by hash, so all three are per-token.**
  Personalising a `download_url` changes `packages.json`, which changes the
  sha256 that `repository.json` publishes. `pcm.personal_repository` /
  `personal_packages` generate them per request (they are small and
  deterministic for a given (meta, token), so the hash a client verifies always
  matches the bytes it later fetches). Never cache one without the other.
- **`_plugin_files(token="")` must stay the default for the repository tag.**
  `ensure_built` hashes the plugin files to decide whether to rebuild, so if
  personalisation moved that hash, every user's first install would look like a
  library change and rebuild the 1.4 GB models package.
- **A personalised plugin zip needs its sha256 RECOMPUTED** — PCM verifies the
  download against `packages.json`, and a zip with a different token is a
  different file. `pcm.personal_plugin` builds it lazily under a
  `psync-<hash>.zip` name keyed on the plugin content hash AND the token, writes
  it via a `.part` rename (a half-written zip would fail PCM's check and read as
  a server fault), and lets `ensure_built`'s prune treat it as the cache it is.
- **The plugin sends its token as a HEADER, never `?t=`.** Only PCM itself is
  forced into the query string. Both templates fall back to `token.json` beside
  the plugin, which is the recovery path after a rotation, and turn a 401 into
  an instruction rather than a stack trace.
- **`BUILDER_REV` and `PLUGIN_VERSION` both had to move for this.** See the
  rule above about them: `pcm.py` changing what a package advertises needs
  `BUILDER_REV`, and plugin source changes need `PLUGIN_VERSION`.
- **Every client through the tunnel MUST send its own `User-Agent`.**
  Cloudflare's browser-integrity check answers the bare `Python-urllib/3.x`
  signature with **403 and error code 1010** before the request ever reaches
  nginx — it is not an API refusal, and the body is Cloudflare's HTML, so it
  surfaces as an unexplained failure. Verified 2026-07-31: `Python-urllib/3.11`
  403s while `sevensigma-sync/1.0`, `curl/8.7.1` and `KiCad/9.0` all pass. Both
  plugin templates and `cli/kicadlib.py` already set one on every request
  (`_headers()`), so keep it that way — a new request path that forgets the
  header works on the LAN and fails only from the internet.

## Agent tool surface + MCP server (Claude Code)

The library agent is reachable two ways over the **same** tool set
(`services/jaravis.py::TOOLS` — one list; `GET /api/agent/tools` is the live count):

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

**Auth:** a **personal API token** (`Authorization: Bearer <token>`), minted per
user in the Setup page's Users card. The shared `settings.mcp_token` still works
while `AUTH_LEGACY_TOKENS` is on, scoped to `/api/agent/` only — see the
authentication section above. Empty `mcp_token` plus `AUTH_ENABLED=false` is the
localhost-dev posture and nothing else.

**MCP server (`mcp/server.py`):** a stateless stdio client run via
`uv run --script` (self-contained PEP 723 deps: `mcp`, `httpx`). It imports NO
app code — it fetches the catalog from `/api/agent/tools` and proxies each call
to `/api/agent/tools/{name}`, needing only `KICAD_API_URL`
(default `http://localhost:8020`) + optional `KICAD_MCP_TOKEN`.
`read_datasheet`'s list-of-content-blocks return (text + base64 PNG pages) is
converted to MCP image content; every other tool returns a JSON string as text.

- **`mcp` is pinned `>=1.2,<2`, and the pin is load-bearing.** mcp 2.0.0
  removed the low-level `Server.list_tools()` / `Server.call_tool()`
  decorators this file is built on, so the unpinned spec resolved to a version
  that died at import with `'Server' object has no attribute 'list_tools'`.
  `uv` resolves fresh on a cold start, so it would have broken with no local
  change (caught 2026-08-24). Lift the pin only with a port to the 2.x API.
- **One tool is LOCAL, not proxied: `upload_model3d`** (`LOCAL_TOOLS`, merged
  into the catalog in `list_tools` and dispatched before the proxy). A 3D model
  is a multi-megabyte file on the user's own disk; proxying it would mean
  base64 through a tool call, and the platform-side agent cannot read that
  filesystem at all. It reads the file locally and posts multipart to
  `/api/models3d/upload`, then returns the ready `(model …)` node. Its default
  `rel_path` rule duplicates `services/pcm_plugin/model_paths.suggest_rel_path`
  (this script imports no app code) — change both together. Keep local tools to
  that shape: something the API genuinely cannot do because the bytes are here.

**Claude Code wiring (`.mcp.json` at repo root):** a project-scoped stdio entry
`kicad-library` that runs the server via `uv`, with `KICAD_API_URL` /
`KICAD_MCP_TOKEN` from env (`${VAR:-default}` expansion keeps them out of git).
`KICAD_API_URL` defaults to the PUBLIC address, so the server works away from
the LAN as well as on it. **`KICAD_MCP_TOKEN` must now be set** — the agent
surface is behind the auth gate, and an unset token gets 401 on every call.
**Both values live in `.claude/settings.local.json` under `env`** — it is
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
