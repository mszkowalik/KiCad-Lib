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
- **The injected datasheet link prefers the LOCAL copy.** `injected_props`
  emits `{public_base_url}/api/datasheets/{id}/file` whenever the current
  `DatasheetVersion` is a real PDF (content-type or `.pdf` filename), or is an
  uploaded file with no `source_url` at all; otherwise it falls back to the
  internet URL. Stored HTML product pages (LCSC etc.) deliberately keep the
  live link — a saved product page is worse than the real one. Applies to both
  emission paths (generated mirror symbols and the KiCad HTTP catalog), so
  `public_base_url` must be the API address as KiCad clients see it, not
  `localhost`, on any non-local deployment.
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
- **Channels are pointers, history is immutable.** `deployment_channels` name a
  version (`production`, `bench`); rolling back moves a channel. A batch pins a
  version or follows a channel; run creation resolves it and records the
  result. Draft versions run ONLY as bench trials (`draft_run=True`, no batch).
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
  `Footprint.display_name` (unversioned, `PATCH /api/footprints/{id}`) holds the
  short package name; `generator.footprint_name_props()` injects it **ahead of**
  the component's own properties, so a component that still carries its own row
  overrides it. Never re-add it as a per-component property. Because the name is
  baked into generated `ki_description` values, changing it rebuilds the symbol
  libraries of every category using that footprint — not the `.kicad_mod`.
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
