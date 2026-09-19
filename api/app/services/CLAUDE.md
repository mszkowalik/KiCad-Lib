# Services (`api/app/services`)

Business logic and everything with a side effect. A router parses a request and
calls into here. Read `api/CLAUDE.md` first for the reuse table and the backend
conventions.

## Where each topic is written down

This directory is flat and holds about 70 modules. The rules for one topic live
in one document. Open the document before you change the module.

| Topic | Modules | Document |
|---|---|---|
| Datasheet identity, fetch, classification, page index | `datasheet_store.py`, `datasheet_pages.py`, `datasheet_migrate.py` | [docs/reference/datasheets.md](../../../docs/reference/datasheets.md) |
| Cost plans, invoices, stock, orders, sales | `cost_state.py`, `material.py`, `stock.py`, `orders.py` | [docs/reference/production-economics.md](../../../docs/reference/production-economics.md) |
| What JLCPCB says moved, and what we booked | `jlc_web.py`, `jlc_import.py`, `jlc_apply.py`, `jlc_ledger.py`, `substitutions.py` | [docs/reference/production-economics.md](../../../docs/reference/production-economics.md) |
| Sign-off, verification, the review record | `signoff.py`, `review.py`, `material.py` | [docs/reference/review-axis.md](../../../docs/reference/review-axis.md) |
| Renaming a footprint or a base symbol | `rename.py` | [docs/decisions/0012](../../../docs/decisions/0012-rename-a-footprint-or-base-symbol-in-place.md) |
| Projects, git mirrors, snapshots, exports | `gitrepo.py`, `project_ops.py`, `git_credential_migrate.py` | [docs/reference/projects-module.md](../../../docs/reference/projects-module.md) |
| Simulation models and composition | `simmodel.py`, `sim_store.py`, `simcompose.py` | [docs/reference/simulation-models.md](../../../docs/reference/simulation-models.md) |
| SPICE runs, netlists, harnesses, the live sketch | `sim_spice.py`, `project_ops.py`, `sch_lib.py`, `sim_scenario.py` | [docs/reference/spice-runs.md](../../../docs/reference/spice-runs.md) |
| What a publish CORRECTS for you, before it parses | `geometry_proposals.py` | [docs/reference/publish-sanitization.md](../../../docs/reference/publish-sanitization.md) |
| The agent tool surface | `jaravis.py` | [docs/reference/jaravis.md](../../../docs/reference/jaravis.md) |
| Device presence from the fleet MQTT broker | `mqtt_monitor.py`, `mqtt_config.py` | [docs/reference/mqtt-presence.md](../../../docs/reference/mqtt-presence.md) |
| PCM package retention and the personal repository | `pcm.py` | [docs/reference/pcm-packaging.md](../../../docs/reference/pcm-packaging.md) |
| The HTTP catalog and KiCad field visibility | `generator.py`, `mirror.py` | [docs/reference/kicad-integration.md](../../../docs/reference/kicad-integration.md) |
| The 2D field solver | `fieldsolver/` | `fieldsolver/CLAUDE.md` |
| Production programming | `flasher/` | `flasher/CLAUDE.md` |
| The KiCad sync plugin this packages | `pcm_plugin/` | `pcm_plugin/CLAUDE.md` |
| Previews, and what a footprint preview ADDS to the source to look like KiCad's editor | `render.py`, `preview_style.py` | the `preview_style.py` docstring |

## The versioning + publish model (core invariant)

Read this before touching components, symbols, footprints, or skills.

**AUTO-PUBLISH, EVERYWHERE.** Components, symbols and footprints since
2026-08-23; **skills since 2026-08-24**, which removed the last draft gate in
the platform. What replaced the gate is the **review axis**
(`services/review.py`, [docs/reference/review-axis.md](../../../docs/reference/review-axis.md)):
every publish records a machine
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

## Creating a version (the one true pattern)

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

**A NAME is a reference, not a label.** `ComponentVersion.base_component` holds
a base symbol's name as a string and a component's `Footprint` property holds
`7Sigma:<footprint name>`. Neither is a foreign key, so a template row's `name`
is never assigned directly — `services/rename.py` owns it, and it moves the
geometry version, every referencing component version, the mirror file and the
stale `categories.defaults` entries in one transaction. It is also the ONE
caller allowed to pass `rename` to `signoff.data_carries`, which is what lets a
rename keep a verification; see the note there on why that is a mapping and not
a new entry in `NON_MATERIAL_KEYS`.

Never set `status` or move `current_version_id` by hand: those two lines are
what the publish functions exist to own, and a path that writes them itself
skips the datasheet pins, the sign-off carry, the review carry and the machine
validation. Audit actions in use: `publish`, `review.check`, `review.revoke`,
`signoff.*`, `import`. (`proposal.create` / `proposal.approve` /
`proposal.reject` appear in history only.)

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
   changed components (reusing the proposal pattern in
   [docs/reference/jaravis.md](../../../docs/reference/jaravis.md)). It never wipes,
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


## The mirror refresh

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

## The pool is guarded on BOTH sides

`check_shortages` refuses a draw that would take a part below zero. Its mirror,
`check_purchase_loss`, refuses an edit that takes stock back off a purchase the
draws depend on — and delegates to it, because removing X units dated D moves
the balance exactly as adding a draw of X on D does. Never write a second
timeline replay; the two would drift.

`routers/run_costs.py` calls it through `_guard_purchase_loss` at five places:
deleting a document, patching a line, voiding one, splitting one, and the batch
line edit. `force=true` waives "this document still has live lines", never this.
The rule is **"would this strand a draw"**, not "has this part been consumed" —
the blunt version was measured at 260 of 264 pooled part lines locked. Reasoning
in
[0040](../../../docs/decisions/0040-a-purchase-cannot-be-removed-from-under-its-draws.md).

## A position SAYS where its money goes — `kind` no longer decides it

`allocate="none"` on a line naming no run and no project meant two different
things: **the shared pool** when `kind` happened to be `part`, and
**`unassigned`** — money nobody pays for, a defect — otherwise. One stored value,
two outcomes, decided by a field the operator was never asked about.

`allocate` now also takes **`pooled`**: "this position IS stock, and somebody
said so". It behaves exactly like `none` in every money path — that is the whole
point, so it needed no new filter anywhere — and its only job is to be the
difference between the two states. `none` on a line naming nothing stays a
defect and is still reported.

Three rules for anyone touching this:

- **`line_destination` is the ONE place the order lives**, and the UI mirrors it
  (`InvoiceLinesTable.goesToOf`). The order matters: `excluded` beats a named
  run, a named run beats `pooled`, and `pooled` beats the DOCUMENT's own
  destination. Drift between the two shows the operator a destination the money
  does not go to.
- **An editor writes all four of `run_id`, `project_id`, `allocate` and `basis`,
  never a subset.** The old one only ever ADDED `allocate: "excluded"`, so moving
  an excluded position onto a batch left it charged to nobody while the screen
  showed the batch.
- **A proforma position is not special.** `line_destination` does not look at
  `doc_type` — a proforma part line reports `pool` like any other, and what makes
  a proforma different is that `_pool_events` skips the whole document.

`basis`, `allocate` and `exclude_reason` are all settable from the browser since
this change; before it they were hard-coded, write-only and unreadable
respectively. Reasoning in
[0045](../../../docs/decisions/0045-a-position-says-where-its-money-goes.md).

## The STEP says what a position is — there is no `kind`

`run_cost_lines.kind` was a coarse second field beside `plan_key`, saying the
same thing at lower resolution and free to disagree with it. It did, on 12 rows.
It is **dropped** (decision 0047). Three rules:

- **`cost_steps.kind_of(plan_key)`** gives the coarse bucket. `line_json` still
  emits `kind` and `by_kind` still reports — both computed, neither stored.
- **"Is this stock?" is `cost_steps.PART_STEPS`**, reached as
  `run_actuals.IS_STOCK` (a SQL expression) or `run_actuals.is_stock(li)` (a
  row). Six modules ask; there is one definition. Never inline the list.
- **A step that means two things must become two steps.** Every one of those 12
  disagreements was a key standing in for two different real things —
  `pcba:general` also carrying JLC's populated-board price, and
  `final:enclosure_print` carrying both the per-unit print and its one-off
  set-up. Adding a step is the fix; re-typing a bucket is not available any more.

The backfill that gave every leaf a step is SQL in `main.py`'s phase-1 list,
immediately before the `DROP COLUMN`, because those statements read `kind` and
the order is what keeps the fill from being separated from the drop.

## A closed batch's documents are read-only, and a correction is a DOCUMENT

A batch's DIRECT costs (`fab`, `assembly`, `freight`, `tooling`, …) are
recomputed from their invoice lines on every read — `qty x unit_price x fx`,
nothing snapshotted — so editing an old invoice moves that batch's per-device
cost and every order that shipped one of its units. Components were never
exposed to this, because a draw snapshots `unit_cost_usd` at draw time.

`run_actuals.closed_lock(db, doc)` is the one place the rule lives, and
`routers/run_costs.py` calls it through `_guard_closed` on all seven write
paths. Three things about it are load-bearing:

- **It covers direct costs only.** A pooled `part` line cannot move a closed
  batch, so locking pool invoices would block stock corrections for nothing.
- **A document created AFTER the close is not locked.** That is what makes the
  correction path work with no special case: a document written after the books
  closed IS the correction. It compares `created_at` against `closed_at`, both
  server clocks — never `doc_date`, which is what the supplier printed.
- **A correction is an ordinary document** with `doc_type="correction"` and
  `corrects_document_id` set. Nothing in any money path special-cases it. It
  inherits the original's pinned FX rate, so a correction in EUR nets against
  the original exactly rather than at today's rate.

`production_runs.py` guards `qty`, `qty_good` and `snapshot_id` on a closed
batch too — a `per_device` line is charged on them through `effective_qty`.
**Charged attrition pins `unit_cost_usd` at write time**, from the average at
the adjustment's own date; NULL means "resolve on every read", which had a 2024
write-off priced at a 2026 average. Reasoning in
[0044](../../../docs/decisions/0044-a-correction-is-an-event-not-an-edit-to-the-past.md).

## Parts the SUPPLIER supplied are itemised, and never pooled

`supplier_parts.py` turns an assembly invoice's one-figure parts lump into a
child per part, and checks that every position a batch used is covered exactly
once. Reasoning in
[0041](../../../docs/decisions/0041-the-supplier-parts-lump-is-a-small-bom.md).

Three facts measured across all 46 cached JLC BOMs, two of which were assumed
wrongly first — read them before touching this:

- **`extPrice == unitPrice * shopStock`** (1021/1021 priced rows). The money is
  billed on the supplier's portion only, never on the whole position.
- **`componentSource` has THREE values.** `preSaleAndShop` is a position the
  factory part-filled from our stock and topped up from its own, and it carried
  1796.16 of batch 8's 2097.28 lump. Filtering on `shop` alone — which
  `void_shop_draws` still does — misses it.
- **`componentNum` is per PANEL, not a piece count.** Use `componentRealCount`,
  split by `presaleStock` / `shopStock`.

The children keep the parent's `run_id` so they stay OUT of the pool: those
parts were never our stock and their price is specific to one order. `itemise`
only returns a plan; `split` applies it, so a hand-typed breakdown and a
supplier-read one are the same rows under the same guards.

**Double supply is checked from OUR rows, not the supplier's.** `coverage` has
two halves: "who supplied each position" needs a cached supplier BOM, and "paid
for twice" — a part charged straight to the batch that was also drawn from the
pool — needs nothing but our own rows. The second runs whatever `known` says,
because a hand-entered invoice has no BOM and is precisely the case the first
half cannot see. Assume every function is reachable from the UI.

**"A part line" is not the same set as "a purchase".** Anything that asks what
we BOUGHT has to exclude a line with a `run_id` and an `excluded` one — the
first was bought for one batch and never entered stock, the second is money
recorded so a document reconciles. `run_actuals.pooled_part_lines` is that test.
`jlc_ledger._local_index` filtered on `kind == "part"` alone and announced
"17,647 pieces we booked as bought that JLC never received" the moment a
supplier-parts position was itemised (2026-09-19). Any new query over part lines
gets the same filter.

## A batch costs, an order earns, and a UNIT joins them

`run_actuals` returns cost, `produced` and `unit_cost_usd` for a batch — never
revenue, never margin. Those belong to the order, and the ONLY thing that joins
the two is the device: `orders.per_device_cost_usd` gives what one unit of a
batch cost, a shipped device carries it, and `order_economics` sums it over the
devices an order shipped. Reasoning in
[0043](../../../docs/decisions/0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md).

- **The denominator is devices PRODUCED**, from `produced_counts`. It used to be
  the run's typed `qty` — the boards ordered from JLC — while the docstring
  already claimed "per GOOD device", so the figure was wrong by the yield on
  every batch (Batch 5: 455 ordered, 568 produced).
- **A batch with no device records has NO unit cost.** It is absent from the map
  and null in the API, and an order shipping such a device counts it
  `uncosted`. Never substitute a planned quantity: this number lands on
  invoices.
- The run's `sale_unit_price` / `qty_sold` / `customer` / `order_ref` columns are
  HISTORY. Nothing reads them. Do not add a reader — that is how the same
  revenue came to exist twice and disagree by 153k on one project.
