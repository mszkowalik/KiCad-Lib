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
  device events and NOTHING ELSE — there is no quantity on a shipment line
  (decision [0049](../decisions/0049-a-delivery-names-its-devices-and-nothing-else.md)).
  `DeviceEvent` is append-only and its newest row IS the
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
    counts a batch from its DEVICE RECORDS and from nothing else: the typed run
    quantity is `qty_recorded` for a tooltip and never reaches the shelf. A
    batch with no device records is built 0 — the fallback to its typed
    quantity was the last place a unit was counted without being named, and it
    went with the shipments that drew from it (2026-09-21). Record the devices,
    as placeholders if they were never serialised (decision
    [0039](../decisions/0039-a-prototype-is-counted-without-being-named.md)).
    A device whose newest run did not pass has no
    `produced` event and is not stock; several flash cycles of one MAC are one
    device with several runs, never several devices. Known gap: the engine's
    first-pass rule keeps `produced` when a later run fails — add a
    failed-after-pass event before relying on live runs for stock.
  - **NO batch has units without a serial** (decision
    [0031](../decisions/0031-a-batch-that-records-its-devices-has-no-anonymous-units.md),
    completed by [0049](../decisions/0049-a-delivery-names-its-devices-and-nothing-else.md)).
    0031 refused an anonymous unit on a batch that had device records; there is
    no way to write one at all now. `shipment_lines` is DROPPED,
    `ShipmentLineIn` forbids extra fields so `qty`, `qty_unserialized`,
    `run_ids` and `source_run_id` are refused by name with 422, and
    `create_shipment` refuses a line that moves no device. `check_unserialized_source`,
    `reconcile_shelf` and `PATCH /api/shipment-lines/{id}` are gone with it.
  - **Good units are COUNTED, never typed** (`run_actuals.good_units`, decision
    [0030](../decisions/0030-good-units-are-counted-not-typed.md)): every
    per-device divisor — per-device actuals, the register's per-run quantity
    and so `per_device_cost_usd`, a `per_device` invoice line scaled to the
    batch, the BOM draw, the revenue fallback under `qty_sold` — divides by the
    device records of that batch. `qty_good` is a fallback for a batch that has
    NO device records, and `qty` under it is **boards ordered from JLC**, which
    is neither what arrived nor what passed. `run_stock`'s `qty_recorded` stays
    the typed quantity on purpose: it is printed beside `built` so the two can
    be compared.
  - **Demand is derived, never stored** (`project_demand`, `GET /api/demand`):
    open = unshipped order-line quantity, supply = shelf stock + devices
    ALLOCATED to those same open lines + the quantity of every run still
    `planned`. The allocated term is easy to leave out and wrong to: such a
    device is on the shelf, `run_stock` excludes it (see §9 above), and the
    line holding it still counts its open quantity — so without it a boxed
    device reads as one to build. A planned batch is not yet linked to the
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
  - **A FIFO pick is a guess, and two things correct it.** A RETURN
    (`return_device`): the returned device takes the place of a FIFO-picked
    device on the same line, which goes back to stock or inherits the returned
    device's old slot. The STOCK COUNT that used to be the second correction
    (`reconcile_shelf`, decision
    [0027](../decisions/0027-a-stock-count-corrects-a-fifo-guess.md)) is GONE
    with decision [0032](../decisions/0032-a-shipment-names-its-devices.md): a
    mechanism that removes guesses by writing new ones is not a correction. No
    NEW pick is a guess either — `create_shipment` never picks, so every
    `shipped` event it writes carries `auto = false`. The `auto` flag survives
    on the historical events it describes, which is why the shipment row still
    prints "picked FIFO" on some of them.
  - **An `unshipped` event does not delete the `shipped` event it reverses**,
    because the log is append-only. Every fulfilment and cost figure therefore
    reads `live_shipped_events` (per line) or `live_shipped_of` (per device),
    which pair the two per device and shipment. A new rule that reads
    `DeviceEvent.kind == "shipped"` directly will treat a reversed delivery as
    a real one — that mistake has now been made twice, once in the fulfilment
    counts and once in `create_shipment`'s self-replacement rule (decision
    [0028](../decisions/0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md)).
  - **A shipment recorded in error is REVERSED, not deleted**
    (`reverse_shipment`, `POST /api/shipments/{id}/reverse`): every delivery on
    it gets an `unshipped` event; the header and the events stay. A shipment the customer RECEIVED comes back
    through `return_device` instead.
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
- **A CANCELLED parts lot is a fee, never stock.** JLC settles one with
  `orderStatus=40` and still reports a non-zero `settlePresaleNumber` —
  lot `754166` said 3,470 LEDs settled at $19.78 and not one arrived.
  `_lot_from_goods` sets `fee_only` from `cancelled` (status 40, or status 30
  with nothing settled), not from the quantity alone; the money still lands so
  the document reconciles. Testing the quantity alone booked 3,470 phantom
  pieces and produced the platform's largest stock gap.
- **A parts lot is stock only once JLC COMPLETES it (`orderStatus=30`).** A
  `buy` lot JLC is still sourcing is paid at an advance price and already
  reports `settlePresaleNumber` equal to the order, with `inStorageNumber=0`
  and `orderStatus=20` — lot 2182682 (4,000 TMUX1208RSVR) and lot 2182699
  (300 EG915U at $0.80 against $8.30 on the stock lot), 2026-09-24. Any status
  other than 30 or 40 imports as ONE line, step `other:awaiting_delivery`,
  `excluded` with reason `awaiting_delivery`, no `lcsc`/`mpn`: the money
  reconciles and nothing enters the pool. The Refresh button on the parts order
  turns it into the lot once JLC completes it.
- **A parts lot costs what JLC SETTLED, and its draws move with it**
  ([0052](../decisions/0052-a-jlc-lot-costs-what-jlc-settled.md)). The cost is
  the sub-order's `settlePaidMoney / settlePresaleNumber`, never the advance
  (`goodsPaidMoney`). A parts refresh re-prices the lot and moves every draw
  bound to it by the difference, and refuses when one charges a closed batch.
  The Parts orders list says "changed at JLC — refresh" when a document total
  differs from JLC's settled total.
- **A parts line is stock because of its STEP.** The importer writes
  `plan_key="parts:pool"` and `allocate="pooled"` on every lot, and
  `other:cancelled` / `excluded` / `cancelled_by_supplier` on a cancelled one.
  A line written without a step lands as unassigned money with nothing added
  to the pool (decision 0047) — the parts importer did exactly that from
  2026-09-19 to 2026-09-24.
- **JLC's own LEDGER is synced, and it is what a disagreement is settled
  against.** `myLibrary/selectComponentChanges` returns every movement for one
  part with the balance before and after, the document that caused it, and JLC's
  own wording. Invoices show what was billed; the ledger shows what the shelf
  did, including picks JLC makes outside any BOM (*"pick 3 pcs of C778132 & 8
  pcs of C965790 up to complete SMT order"*) and work no order mentions at all
  (*"used 20pcs in 2nd Process"*). Stored in `jlc_stock_changes`, UPSERTED by
  `customerPresaleStockChangeKeyId` because a row is immutable at JLC — unlike
  `jlc_stock_items`, which is a balance and is replaced. Full reasoning in
  [0037](../decisions/0037-the-supplier-keeps-the-receipts.md).
- **The ledger is keyed by `customerPresaleStockKeyId`, which only the WEB stock
  list carries.** Not the official OpenAPI library the platform already syncs,
  which is why the ledger went unnoticed. A request keyed by the LCSC code
  answers HTTP 200 with an internal 500. `POST /api/jlc/stock/sync` fetches both,
  best effort on the ledger — the balance must not fail because the browser
  session lapsed.
- **`changeStatus=3` is a movement that DID NOT HAPPEN** — a ship-out request
  JLC cancelled. It still states a quantity and a before/after pair. Excluding
  it, all 67 parts replay to the balance JLC reports; including it, two do not
  (C157472, C62102). A part that does not replay is a FETCH problem, never a
  disagreement about stock.
- **A pair of ledger rows netting to zero is not a disagreement.** JLC draws an
  order's parts and returns them when it is cancelled — 44 such rows today under
  `SMT026061460600` alone. `jlc_ledger.unexplained` nets by document code first.
- **A ledger row is booked as an UNCHARGED DRAW, and only when a person says
  so.** `jlc_ledger.book` uses JLC's quantity, date and wording,
  `basis='measured'`, `import_ref='jlcledger:<changeKeyId>'` so re-booking is a
  no-op. A row that names a document is NOT bookable — importing that document
  is the fix, and doing both would take the same stock out twice.
- **A part FITTED where the design specifies another is a row on the BATCH**,
  `run_substitutions`, keyed by (run, board, variant, designator) — never by
  BOM line id, which belongs to one snapshot and stops matching the next time
  the BOM is exported. The snapshot is never rewritten: it records what was
  specified, the row records what went on the board. Full reasoning in
  [0038](../decisions/0038-a-substitution-belongs-to-the-batch.md).
- **Substitutions are detected from JLC's BOM against JLC's OWN PREVIOUS BOM,
  per board.** Their stored BOM keeps the board's pre-KiCad reference numbering
  (`C1` for the schematic's `C2`, `USB2` for `J1`), so matching their
  designators to ours fails; comparing their orders to each other needs no
  mapping, and the design's own designator is recovered by looking the
  superseded part up in the snapshot. Compared globally rather than per board,
  `U3` on one project is compared with `U3` on another and every board reports
  substitutions it never made. `matchType == "update"` is JLC saying a HUMAN
  changed the line; `"auto"` is their matcher resolving the code we uploaded.
- **Every later batch that keeps the substitute is its own row.** A
  substitution is per batch, and reporting only the transition left the next
  batch — built identically — looking as though it followed the design.
- **`design_updated=false` is a standing finding, and it is the point.** While
  the schematic still names the superseded part, the Stock page says so and
  reports how many are still held. Without it, 476 pieces of `C110548` were
  bought on 2026-08-06 at $1.2296 against a historic $0.336, three months after
  the position moved to `C7223` — purchasing read the design, and the design
  still asked for it.
- **A substituted part is ONE row on the Materials tab.** The planned side is
  the design's part, the used side is the draws of the part really fitted, and
  the value delta is then the true cost of the substitution (+$74.54 on batch
  7). It is a DISPLAY merge: the draw stays on the part that really left the
  pool, because that is what stock control is about. Merged only when the
  substitution covers every position on the line — one LED of six replaced
  means both parts were genuinely used.
- **`supplied_by` says whose shelf the fitted part came off, and it is STORED,
  never inferred.** Read from JLC's `componentSource`: `shop` -> `supplier`
  (billed inside the assembly fee, so no pool draw can exist), `preSale` ->
  `pool`, `preSaleAndShop` -> `both`. Inferring it from a missing draw is wrong
  in both directions — a part we supplied and never drew IS a missing draw, and
  reading it as supplier-supplied hides it.
- **A part the supplier provided may be named without a library component.**
  The component picker offers free text only when the supply side says so: a
  part off our own shelf was bought, so it has an invoice line and a pool entry,
  and keying it by a typed string would split that part into two pool entries.
- **A planned part in neither the supplier's BOM nor any draw did not go on the
  board**, and the Materials row says so. Only answerable when JLC's BOM for
  the batch is cached — without it the absence of a part means nothing. Matched
  on the LCSC code and on the library component behind it, never the
  designator. A part that was DRAWN is never flagged: that is what keeps a
  carton, which no SMT BOM carries, from being reported on every batch.
- **A substituted row's Used quantity is derived, never typed.** With draws, it
  is those draws. Supplier-supplied and therefore drawless, it is the design's
  planned quantity with the money left blank — the position WAS populated, and
  its cost sits in the assembly fee where it cannot be split out. Recorded as
  empty, it is zero on both sides. The cell is read-only in all three: typed,
  it would write a draw against the part that did not go on the board.
- **A substitution of quantity ZERO with nothing named means the position was
  left empty.** The early batches shipped without cartons; that is history, and
  it silences the flag with an author, a reason and an undo. It replaces the
  `drop` override for this case, which nothing in the UI could show.
- **Substituting is done from the part's row on the batch's Materials tab**,
  scoped to one designator or to every position the part sits at — a BOM row
  already groups them, and `RunSubstitution` splits a multi-reference
  designator, so either answer is ONE row rather than a row per reference.
- **An imported parts order can still take a correction.**
  `POST /api/jlc/import/parts/{pob}/refresh` re-plans an existing document from
  what JLC says today and updates lines matched on `presaleGoodsKeyId`. It
  decides before it mutates, preserves anything appended to a line's note after
  " | ", and refuses when a lot has vanished or when shrinking a line would
  contradict draws bound to it. It moves a line's `allocate` and
  `exclude_reason` only when the line's step changes (a lot arrived, or was
  cancelled); otherwise a destination somebody chose survives the refresh. The importer itself refuses a document it
  already holds, and rightly — a second document doubles the purchase.
- **JLC states a batch's status; do not infer it.** The order listing
  `sync_stage` fetches carries `batchStatus` (`shipped` | `inProduction` |
  `cancelled` | `waitPay` | `waitReview`), stored on `jlc_imports.jlc_status`
  and refreshed every sync. It is NOT our `status` column, which is the
  staged -> imported lifecycle. A cancelled batch is never invoiced — and
  neither is one still in production — so `payload == {}` cannot distinguish
  them, which is how three batches sat in "not imported" with nothing to import.
  A cancelled batch is skipped by the sync rather than re-fetched forever.
- **A draw is priced by identity OVERLAP, never by `_key`.**
  `run_actuals.resolve_pool_identity` finds the pool entry a part belongs to and
  the caller ADOPTS its `component_id` / `mpn` / `lcsc` before writing. `_key`
  alone cannot do this: it PREFERS `component_id`, so a caller who knows only an
  MPN produces `m<MPN>` while the purchases sit under `c<id>` — the lookup
  misses, the draw is priced at ZERO, and the part splits into a second pool
  entry with its own average. Measured 2026-09-18: enclosure `35.0207000.BL` is
  `c323`, and a draw entered by MPN alone priced at $0.00 against a real $3.55.
  `check_shortages` already matched on overlap, so the stock guard passed and
  only the money was wrong. Both write paths (`add_consumption`,
  `PUT /runs/{id}/consumption/for-part`) go through the resolver.
- **Material usage for parts JLC never sees is TYPED, not derived.** The batch's
  Materials tab has an editable Used quantity per row
  (`PUT /api/runs/{run_id}/consumption/for-part`): absolute, idempotent, one
  draw per part. Correcting a figure later is the same call, so a mistake never
  needs a compensating adjustment — which is what attrition adjustments were
  being used for. The seven parts concerned (enclosures, antennas, cartons) are
  half the pool's value and no supplier reports their consumption; `basis='bom'`
  rows are estimates of exactly this, and typing over one replaces it. A part
  JLC reported itself (`basis='measured'`) is read-only: that is the supplier's
  measurement of its own consigned stock, not ours to retype.
- **Two quantities, two names, and picking the wrong one takes the whole import
  path down** (decision
  [0035](../decisions/0035-a-supplier-bills-what-was-ordered.md)).
  `run_actuals.good_units(db, run)` is what PASSED and is the divisor for
  per-device COST. `run_actuals.planned_units(run)` is `plan_qty or qty` — what
  was ORDERED — and is the multiplier for a supplier's per-board rate in
  `effective_qty`. An assembler is paid for the boards they assembled; our yield
  loss is ours. Using the first where the second belongs made LIFTECH's "5
  PLN/board x 350" reconcile to 349 boards, and because `_assert_identities`
  checks the register gap ABSOLUTELY, that $1.31 refused every `jlc_apply` write
  for the rest of the day.
- **A merged supplier invoice is SPLIT, never inferred.** Subcontractors bill
  several batches on one document. `POST /api/run-cost-lines/{id}/split` makes
  one printed position into children charged to different runs; a child inherits
  `basis`, so a `per_device` child scales by its own batch. Nothing tries to work
  out which batches a line covers.
- **Attrition belongs to the batch that lost it.** The batch's Materials tab
  writes a `ComponentStockAdjustment` with `charge_run_id` set, so the loss lands
  in that batch's per-device figure instead of floating at project level. The
  Stock page keeps the same power for anything the batch view cannot express.
- **`lost` and `external` are different axes.** `pool_state` counts an
  `external_project` adjustment — another project's assembly order — on
  `external`, never on `lost`. Attrition is a defect signal here, and consumption
  by a project the platform does not track is not a defect. Together they read
  1,094 written-off pieces on 2026-09-18 when the true attrition was ZERO. Since
  [0034](../decisions/0034-stock-moves-when-the-supplier-says-so.md) the same
  fact is written as an uncharged draw, so no new adjustments of this kind
  appear and the 27 historical rows keep their own column.
- **A draw has TWO facts with two sources, written at two times** (decision
  [0034](../decisions/0034-stock-moves-when-the-supplier-says-so.md)). The
  QUANTITY is reported: a JLC manufacturing invoice itemises every consigned lot
  each assembly order consumed (`presaleDetailResultVOList`), and
  `jlc_invoice.parse` checks those rows sum to the invoice's prepaid total. WHO
  PAYS is inferred later by `plan_orders` and confirmed by a human.
  `ComponentConsumption.run_id` is therefore **nullable**: NULL means the stock
  left and no run has been charged.
  - Importing a manufacturing document writes its draws uncharged
    (`jlc_apply.draw_stock_for_invoice`, from `jlc_import.stock_plans` — which
    deliberately bypasses the planner, because the stock side needs none of it).
  - A decision then calls `jlc_apply.charge_draws`, which UPDATES `run_id` and
    writes no new row, so a judgement about cost can never restate a supplier's
    measurement. It refuses an order already charged to another run.
  - `external` writes nothing for stock — it already left, charged to nobody.
    `external_stock_movements` survives as a reader for 27 historical rows and
    is skipped when draws exist, so stock cannot leave twice.
  - `invoice_register` reports the uncharged value as `pool.uncharged_drawn_usd`
    instead of filing it under a `None` run. A balance that stops being
    transient means orders are not being decided.
- **Compare against JLC's stock count at the MOMENT IT WAS TAKEN, in JLC's
  calendar.** `JlcStockItem` is a snapshot; the pool runs to today. `parts_stock`
  therefore computes `remaining_at_sync_qty` with `pool_state(as_of=...)` and
  reports `delta_qty` against that, with `totals.compared_as_of` and
  `totals.events_since_sync` saying how stale it is. Two traps, both measured
  2026-09-18:
  - Comparing today's pool against an August snapshot reported **33,246 pieces**
    of phantom gap — almost all of it one batch's draw four weeks later — and
    buried a real 3,866-piece one.
  - The cutoff must be the **China-time** date (`run_actuals._jlc_date`). JLC
    dates orders, invoices and settlements in UTC+8. Parts order
    `20146320202608060318425` was placed at 03:18 China time, and the stock was
    fetched 4m44s later at 19:23 UTC *on the 5th* — so a snapshot whose UTC date
    is the 5th already contains an order dated the 6th. Cutting on the UTC date
    put 13 parts out by exactly their last purchase.
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
- **A run's snapshot can be ATTACHED, re-pointed and DETACHED** (`RunPatch
  .snapshot_id`). Re-pointing is needed when a part moves INTO the schematic,
  since the planned BOM comes from the run's snapshot and would otherwise never
  see it (the Dongle enclosure became `ENC1` in commit a92e8973). Attaching is
  needed because a batch is routinely opened before its design is committed —
  CE_Dongle_V3 Batch 1 (run 2164) was created on 2026-09-19 with its notes
  saying "no snapshot yet", and until 2026-09-22 nothing on any screen could
  give it one: `RunDetail`'s selector was rendered only when the run already had
  a snapshot. An explicit `null` detaches; `exclude_unset` tells that apart from
  "field not sent", so `snapshot_id: None` in a patch body is NOT "leave alone".
  Attaching also imports the repo's `production/` dir at that snapshot, exactly
  as `create_run` does, and only when the batch has no file set yet.
  Three refusals: the snapshot must be `ready` and belong to the run's project,
  it must build the run's `board`, and the patch 409s while the run carries
  `b<bom line id>` overrides — those ids belong to the old snapshot's lines, so
  moving or detaching would quietly stop applying them.
  **Runs whose components are charged directly from a turnkey invoice (Dongle
  V2 Batch 1, `snapshot_id` NULL) must still STAY snapshot-less** — giving them
  a BOM invites `consume_from_bom` to draw parts the invoice already paid for.
  That is now a judgement the operator makes, not something the screen enforces
  by hiding the control.
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
