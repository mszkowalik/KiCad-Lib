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
- **Approving geometry AUTO-FILES the component repoints** (`services/repoint.py`,
  user decision 2026-08-04; supersedes the 2026-07-30 "offer, never automatic"
  decision). The two facts above pull apart: the mirror and the HTTP catalog jump
  to the new geometry while every linked `ComponentVersion` still names the
  previous `footprint_version_id`, so the library and the components silently
  disagree about which land pattern is current. Measured on 2026-08-03: a pin-1
  sweep published 105 footprint versions and left 185 of 327 components pinned to
  the superseded drawing. So `approve_symbol` / `approve_footprint` now call
  `repoint_for`, in the SAME transaction as the publish, and return the result as
  `repointed`. It is still draft-gated — it mints drafts, never publishes — so an
  old run's component version keeps the geometry it was built against until
  somebody approves the follow-up. `AUTO_REPOINT_COMPONENTS=false` turns it off.
  Four invariants live in that module:
  - **One open auto-draft per component, refreshed — never a second.** This is
    the whole reason the module is not a loop in the router. A batch touching a
    symbol AND a footprint used by the same part would file two drafts against
    the same published parent, each carrying one pin; approving both applies the
    first and then overwrites it with the second, so the component ends with one
    change applied and a history claiming two. `created_by == AUTO_ACTOR`
    identifies a draft that may be refolded.
  - **A pending human/agent draft is skipped, not rewritten**, and reported in
    `repointed.skipped`. Repointing a proposal under review would silently
    rewrite somebody's edit; a parallel auto-draft would collide on approval.
  - **Properties are cloned in FULL fidelity** — `hide`, `show_name` and `layout`
    included. `propose_component_edit` writes only key/value/is_null and lets the
    rest default, which is fine when a caller is restating properties on purpose,
    but here the component is not being edited and `hide` drives KiCad field
    visibility.
  - **Never read `comp.versions` inside this module.** The session is
    `expire_on_commit=False` and rows added here are not appended to a loaded
    relationship, so it goes stale the moment a draft is added — that made the
    coalescing miss its own draft and open a second one. Use `_versions(db, comp)`.

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
- **The prune must never delete a library file the plugin did not write.** It
  is either a local edit or a footprint drawn here and not yet pushed; the old
  rule deleted anything absent from the package, which destroyed new work
  before Push could send it. Models are exempt — they carry no per-file record,
  so they prune as before.
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
  after an upgrade.
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
