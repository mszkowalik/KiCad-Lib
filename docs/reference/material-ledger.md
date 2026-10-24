# Material ledger: the storage of stock, work and units

Decision [0097](../decisions/0097-keep-stock-work-and-units-in-one-material-ledger.md)
chose the model; decision
[0098](../decisions/0098-switch-to-the-material-ledger-in-one-cut-over.md)
made it the only storage, in one cut-over. The design is in
[../material-ledger/design.md](../material-ledger/design.md), the cut-over
plan and its conventions in [../material-ledger/cutover.md](../material-ledger/cutover.md).

| Table | Classes | Holds |
|---|---|---|
| `material_items` | `MaterialItem` | What a thing is: one row per pool identity (`c<id>`, `m<MPN>`, `l<LCSC>`) and `p<project>` for a product |
| `material_lots` | `MaterialLot`, `Unit` | A stored lot (kind `stock`, made by a positive adjustment: a count, found units, a make's output) or a unit (kind `unit`, a twin) |
| `material_events` | `MaterialEvent`, `Click`, `Make` | One operation: a click (`step`), a transformation (`make`), anything else on stock (`stock`) |
| `material_moves` | `MaterialMove`, `Draw`, `Adjustment` | One change of one item's quantity in one event, SIGNED |
| `material_move_lots` | `MaterialMoveLot` | Which lots a move took from |
| `material_event_lots` | `MaterialEventLot` | The units a click acted on |
| `material_cost_aims` | `MaterialCostAim`, `ClickCost`, `StepCost` | An invoice position aimed at a click or at a whole step |
| `material_state_maps`, `material_links`, `material_properties` | | States, bundles and facts of lots (0097 phase 4) |

Code: `services/material_ledger/core.py` (the writing helpers),
`services/material_ledger/cutover.py` (the one-time migration). The readers
live with their topics: `run_actuals` (the pool), `lots` (the lot ledger),
`twins` (units, clicks, prices).

## Rules

1. **A purchase lot is its invoice line** (`L<line id>`) and has no lot row.
   The line is the one truth of what was bought; a copy could drift from the
   money (0073). A stored lot is `A<lot id>`.
2. **Every move has an event.** A click's draws belong to the click, a make's
   inputs and output to the make, an in-house transfer's draws to one event
   per transfer, and anything else to a `stock` event of its own. Write moves
   with `core.draw`, `core.adjustment` and `core.bind`: they make the item, the
   event and the stored lot.
3. **A move's `qty` is signed.** A draw is negative; read `Draw.taken` (a
   hybrid, also in SQL) for the quantity it took. Every replay adds the signed
   quantities as they are: a purchase line adds, a draw takes, an adjustment
   either.
4. **"A draw of a click" is a test on its event** (`twins.of_click()`, or a
   join on `M.Click`), not a nullable column. Every draw has an event.
5. **The API keeps the old field names.** `lot_adjustment_id` and
   `adjustment_id` name a stored lot, `step_run_id` a click, `twin_id` a unit,
   `consumption_id` a draw, `transformation_id` a make, `consumed_at` and
   `qty_delta` a move's `at` and `qty`. The web was not changed. The columns
   `run_cost_lines.transformation_id` and `run_substitutions.step_run_id` keep
   their names and name a make and a click.
6. **The nine old tables are `legacy_<name>`, read only**, with no journal
   trigger. A Write-log batch, a request undo or a rebuild undo whose rows name
   one of them was written before the switch and is refused
   (`journal.LEGACY_TABLES`).
7. **One table holds several kinds.** The journal and the request undo read a
   row's `kind` from its image; `journal._model_for` returns a table's BASE
   class, so a lookup by id finds every kind, and a row put back is built as
   its own kind.

## The migration

`cutover.run` runs at startup, once, when `component_consumptions` still
exists and `material_moves` is empty, in one transaction outside the startup
block that swallows errors. It keeps every id that does not collide (on the
production copy of 2026-10-23 only the 32 whole-step cost links got new ids)
and renames the old tables. A failure stops the start. `GET
/api/health/schema` reports `ledger.cutover`.

## The proof

`scripts/ledger-golden.py capture` saves 13,777 read answers; `compare`
classifies each difference as `order` (the same values in another order: a
same-day list is in id order now), `expected` (a click written before the
switch has no Undo), `same_day` (the parts ledger's running balance between
same-day events) or `real`. The switch is right when no difference is `real`.
On the production copy of 2026-10-23 none was.
