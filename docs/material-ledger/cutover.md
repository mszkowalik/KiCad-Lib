# Material ledger cut-over: the plan

**Status: in progress on branch `material-ledger-cutover`. Not deployed.**
Decision 0098 (to write) amends item 9 of
[0097](../decisions/0097-keep-stock-work-and-units-in-one-material-ledger.md):
one switch instead of phases 2, 3 and 5. User answers, 2026-10-23/24:

1. Full rewrite: the platform uses only the new tables after one deploy.
2. Rewrite all the code in the new model's terms (not typed views of old names).
3. Prepare the deploy. Deploy nothing until the user says so (devices are being
   programmed).
4. Scope not chosen: "same behaviour first". The abilities of phase 4 come
   after, or before the deploy if the user asks.

## The proof

`scripts/ledger-golden.py` calls 13,777 read routes (stock, lots, batches,
clicks, units, devices, orders, shipments, books, register) and saves every
answer. The cut-over is right when the answers after it equal the answers
before it, on a copy of production. The copy: the backup
`before-37424e3-2026-10-23.dump`, loaded into the local stack
`kicadlib-ledger` (db 127.0.0.1:5435, api 127.0.0.1:8031, auth off).

## Target tables

| New | Replaces | Notes |
|---|---|---|
| `material_items` | (pool keys `c`/`m`/`l`) | One row per pool identity, plus `p<project>` for a product |
| `material_lots` | `twins`, the lot side of a positive `component_stock_adjustments` row | `kind`: `unit` (a twin) or `stock` (a lot that a move made). A purchase lot stays its invoice line (`L<line id>`) and has no row |
| `material_events` | `step_runs`, `process_transformations` | `kind`: `step` (a click), `make` (a transformation), `stock` (a draw or an adjustment that no click or make holds) |
| `material_moves` | `component_consumptions`, `component_stock_adjustments` | `kind`: `draw` or `adjust`. `qty` is SIGNED: a draw is negative. Every move has an event |
| `material_move_lots` | `component_consumption_lots` | `lot_line_id` (a purchase lot) or `lot_id` (a stored lot) |
| `material_event_lots` | `twin_steps` | |
| `material_cost_aims` | `cost_line_steps`, `cost_line_step_keys` | `kind`: `click` or `step` |

`run_cost_lines.transformation_id` names a `make` event. `run_substitutions
.step_run_id` names a `step` event.

## Ids

The migration keeps every old id when the new table has no row with it, so
the answers before and after compare without a translation table. On the
production copy no range overlaps, except `cost_line_step_keys` against
`cost_line_steps`: the step aims get new ids. A lot key stays `L<line id>` or
`A<lot id>`; a stored lot keeps the id of the adjustment that made it.

## The migration

One transaction at startup, before anything reads the tables. It runs only
when the old tables exist and the new ones are empty. It copies, then renames
each old table to `legacy_<name>`. Failure rolls everything back and stops the
start, so the deploy fails visibly and the old image can run again on
untouched tables. The legacy tables carry no journal trigger and nothing
reads them. A Write-log undo of a request made before the switch is refused.

## Conventions for the rewrite

Every module follows these. A fork or a later session reads them before it
edits code.

| Old | New | Notes |
|---|---|---|
| `M.Twin` | `M.Unit` (a `MaterialLot`, kind `unit`) | Same column names. A new unit needs `item_id` (`material_ledger.core.product_item`) and `company_id` (its origin batch's). Set `identifier` (the MAC) wherever `device_unit_id` is set |
| `M.StepRun` | `M.Click` (a `MaterialEvent`, kind `step`) | `qty` → `units`, `made_at` → `at`, `kind` → `step_kind`. Set `company_id` from the batch |
| `M.TwinStep` | `M.MaterialEventLot` | `twin_id` → `lot_id`, `step_run_id` → `event_id` |
| `M.ProcessTransformation` | `M.Make` (a `MaterialEvent`, kind `make`) | `recipe_key/label` → `step_key/label`, `made_at` → `at`, `production_run_id` → `run_id`, `output_adjustment_id` → `output_lot_id` |
| `M.ComponentConsumption` | `M.Draw` (a `MaterialMove`, kind `draw`) | `qty` is NEGATIVE: read `d.taken` (a hybrid, also in SQL), write with `material_ledger.core.draw(taken=…)`. `consumed_at` → `at`. `step_run_id` / `transformation_id` → `event_id` (the click or make). Every draw has an event: "a draw of a click" is `twins.of_click()` or a join on `M.Click` |
| `M.ComponentStockAdjustment` | `M.Adjustment` (a `MaterialMove`, kind `adjust`) | `qty_delta` → `qty` (signed), `adjusted_at` → `at`, `charge_run_id` → `run_id`. Write with `core.adjustment`; a positive one makes a stored lot (`lot_id`) |
| `M.ComponentConsumptionLot` | `M.MaterialMoveLot` | `consumption_id` → `move_id`, `lot_adjustment_id` → `lot_id` (a STORED LOT id; `A<lot id>`) |
| `M.CostLineStep` | `M.ClickCost` | `step_run_id` → `event_id` |
| `M.CostLineStepKey` | `M.StepCost` | same columns |

* **The API keeps its field names.** `lot_adjustment_id`, `adjustment_id`,
  `step_run_id`, `step_run_ids`, `twin_id`, `consumption_id`,
  `transformation_id`, `consumed_at`, `charge_run_id`, `qty_delta` stay in
  request bodies and JSON answers; they now name a stored lot, a click, a
  unit, a draw, a make. The web is not changed. Translate at the boundary.
* **`RunCostLine.transformation_id` and `RunSubstitution.step_run_id` keep
  their names.** They name a make and a click.
* **A stored lot keeps its key `A<id>`**: on the production copy the lot id
  is the old adjustment id.
* **Journal table names** (`WriteBatchRow.table_name`, `RowChange`): the new
  tables are `material_events`, `material_lots`, `material_moves`,
  `material_move_lots`, `material_event_lots`, `material_cost_aims`. One table
  holds several kinds: tell a click from a make by the row's `kind` (the
  `before` image of an update or delete; the live row for an insert). A batch
  that names an old table was written before the switch and is refused.
* **No module keeps a compatibility alias** for an old name.
* `python3 -m py_compile` each file you change. Do not run the test suite
  until the migration and every module are done; the tests are rewritten in
  their own step.

## Work list

- [x] models.py: the new classes; the old ones removed
- [x] main.py: the migration; the phase-1 shadow dropped; old DDL removed
- [x] run_actuals, lots, process, twins, twin_rebuild, journal, row_changes
- [x] transfers, companies, company_backfill, attrition_pin, substitutions,
      supplier_parts, jlc_apply, jlc_ledger, jlc_import, routers (fork A)
- [x] orders, bench_links, flasher, access, agent_tools, routers/process,
      routers/production_runs (fork B)
- [x] material_ledger phase-1 shadow removed (projector, parity, endpoints)
- [x] golden compare on the production copy: no real difference
- [ ] tests rewritten (three forks)
- [x] docs: 0098, material-ledger.md, processes.md, production-economics.md,
      glossary.md, change-tracking.md, CLAUDE.md rows, CHANGELOG
- [ ] deploy runbook run (the user starts it)

## The deploy

Nobody may craft, program or enter invoices while this runs: a capture that
spans a write reads as a difference. The user says when.

1. **Capture the answers before.** On the server, inside the api container,
   with a personal token (the script only reads):
   `docker compose -p kicadlib -f docker-compose.kicadlib.yml exec -T kicadlib-api python - <args>`
   is not usable for a file argument; copy the script in with `docker cp` and
   run `python /tmp/ledger-golden.py capture --base http://localhost:8000
   --token $TOKEN --out /tmp/golden-before`.
2. **Back up the database**: `pg_dump -Fc` into
   `~/kicadlib-backups/before-<sha>-<date>.dump`, with its `.sha256`.
3. **Merge the branch into main and push.** Wait for the image workflow.
4. **Pull and restart the api only** (`pull kicadlib-api`, `up -d
   kicadlib-api`). The web and render images do not change.
5. **Read the start**: the log line `material ledger: cut-over written {...}`,
   `GET /api/health/schema` → `ledger.cutover: ok`, `/api/health` 200, the
   image revision label equal to the pushed commit.
6. **Capture the answers after** the same way, into `/tmp/golden-after`, and
   `compare`. No difference may be `real`.
7. **If the start fails**: nothing was migrated (one transaction). Run the
   previous image again (`KICADLIB_TAG=sha-37424e3`, `up -d kicadlib-api`).
   **If a real difference shows after a migration that succeeded**: fix
   forward if the cause is clear; otherwise restore the backup and run the
   previous image, which loses what was written since step 2.
