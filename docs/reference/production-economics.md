# Production economics — cost plans, invoices, stock, orders and sales

Backend rules for money and material. The services are `cost_state.py`,
`material.py`, `stock.py`, `orders.py` and `invoice_register`. Decision
[0003](../decisions/0003-orders-shipments-and-device-history.md) covers orders and
shipments, [0005](../decisions/0005-off-board-parts.md) covers off-board parts, and
[0007](../decisions/0007-built-means-finished-and-passed.md) covers the built rule.

The wider design is in [docs/production-costs/design.md](../production-costs/design.md).

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
- **Sales are ORDERS, shipments and a per-device history — decision 0003**
  (`services/orders.py`, `routers/orders.py`, `docs/decisions/0003-…`). A
  `SalesOrder` sits above the project with one line per product; `OrderInvoice`
  rows close it (advance + final + correction should sum to the net total — a
  warning, never a block; a proforma is not money; revenue converts per invoice
  at the invoice date); a `Shipment` is a header whose content is `shipped`
  device events, plus `qty_unserialized` per line for batches that predate
  device records (§8). `DeviceEvent` is append-only and its newest row IS the
  device's state; `DeviceUnit.state` / `.production_run_id` are caches of it.
  Rules that cost something to learn:
  - **A device's log is monotonic.** `record_event` bumps an earlier `at` to
    one second after the previous event, and APPENDS to `device.events` rather
    than `db.add`, so the next write in the same request sees it. Expire the
    device before serialising after a commit — the relationship was loaded
    before the write.
  - **Fulfilment counts `shipped` events with NO `replaces_device_id`**; a
    warranty replacement names the device it replaces, and a device re-shipped
    to the same line after repair names ITSELF, so it is never counted twice.
    Order cost counts every shipped device, replacements included, at its
    batch's per-device actual (`per_device_cost_usd`, from the register).
  - **Built means finished and passed** (user rule, 2026-09-10). `run_stock`
    counts a batch that has ANY device record from its devices only: the typed
    run quantity is `qty_recorded` for a tooltip and never adds "no serial"
    units to the shelf. Only a batch with no device records at all (the V3
    prototypes) is counted from its quantity, and that is the only source of
    an unserialized unit. A device whose newest run did not pass has no
    `produced` event and is not stock; several flash cycles of one MAC are one
    device with several runs, never several devices. Known gap: the engine's
    first-pass rule keeps `produced` when a later run fails — add a
    failed-after-pass event before relying on live runs for stock.
  - **Demand is derived, never stored** (`project_demand`, `GET /api/demand`):
    open = unshipped order-line quantity, supply = shelf stock + the quantity
    of every run still `planned`. A planned batch is not yet linked to the
    order lines it covers; the project tab shows the arithmetic only.
- **A JLC decision outranks JLC's cached panelisation.** `JlcImport.panel_info`
  is what the sync saw; a `JlcOrderDecision` with a `panel_factor` is a person
  saying it was wrong (a re-order assembles boards panelised earlier and JLC
  then reports 1-up). Every reader goes through
  `jlc_import.effective_panels(db)` — the planner, the decision queue and the
  router's run-fill check — and `plan_orders` applies recorded decisions
  AFTER the collision pass, so a decided order restates its decision
  (`confidence: "decided"`) instead of being demoted. The BOM vote counts
  only prepaid parts; the queue names the JLC-sourced material
  (`jlc_sourced_usd`) so a low vote on such an order reads as a floor.
  - **A FIFO pick is a guess and a return corrects it** (`return_device`): the
    returned device takes the place of a FIFO-picked device on the same line,
    which goes back to stock or inherits the returned device's old slot; both
    moves are events. A line fulfilled by unserialized units converts one of
    them into the named device instead.
  - **The flasher writes `produced` on the first PASS in a batch**
    (`engine.py` → `mark_produced`, idempotent; never on a draft run). Legacy
    devices are linked with `POST /api/runs/{id}/produced`.
  - **The startup migration is idempotent through `uq_order_line_migrated_run`**
    and leaves the run's sale columns in place — the register still reads them,
    so its figures cannot move. The run page shows `sales` (derived `qty_sold`,
    the orders its units went to, what is on the shelf) beside them.
- **The sale side ALSO still lives on the run, for the register** (`sale_unit_price`, `sale_currency`, `qty_sold`,
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
