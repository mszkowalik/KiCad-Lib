# Material ledger, phase 1: the shadow and its parity checks

Decision [0097](../decisions/0097-keep-stock-work-and-units-in-one-material-ledger.md)
puts stock, work and units in one model. The design and the five phases are in
[../material-ledger/design.md](../material-ledger/design.md). This page states
what phase 1 built.

Phase 1 is a SHADOW. The old tables stay the truth. The shadow proves that the
new model holds the same stock and cost.

| Part | Where |
|---|---|
| Tables | `material_items`, `material_state_maps`, `material_events`, `material_lots`, `material_moves`, `material_event_lots`, `material_links`, `material_properties`, `material_cost_aims` (`models.py`) |
| Projector | `services/material_ledger/project.py` (`rebuild`) |
| Readers | `services/material_ledger/state.py`: `item_state` (as `pool_state`), `lot_state` (as `lots.lot_state`), `Units` (as `twins.prices`) |
| Checks | `services/material_ledger/parity.py` (`check`) |
| Endpoints, admin only | `GET /api/material-ledger/summary`, `POST /api/material-ledger/rebuild`, `POST /api/material-ledger/parity`, `GET` and `PUT /api/material-ledger/state-maps`, `DELETE /api/material-ledger/state-maps/{comp_id}` |
| Tests | `api/tests/costs/test_material_ledger.py` |

## Rules

1. **Nothing reads the shadow for a decision.** Stock, lots, prices and
   shortages come from the old functions until phase 3. Only `state`,
   `parity` and the router read the shadow.
2. **A rebuild empties seven tables and builds them again.** It keeps
   `material_items` and `material_state_maps`, because they hold what a person
   decided: a tracking level, or "this internal part is a state of that item".
3. **The projector walks the pool's own event list**
   (`run_actuals._pool_events(with_transfers=True)`) and writes the moves in
   its order. A reader replays `ORDER BY at, rank, id` and gets the pool's
   order, same-day ties included. Do not build stock events from the tables
   in a second place.
4. **A draw is one move for each lot binding, plus one move with no lot for
   what no binding covers.** Each of these moves names the draw
   (`source_kind = consumption`, `source_id`). A reader takes them back
   together as one draw, because the pool's moving average takes a draw as
   one event.
5. **A move carries two values.** `value_usd` is what the draw was charged
   (the moving average while `lot_pricing` is off). `lot_value_usd` is what the
   lot gave up at its own price. The pool reads the first, the lot ledger the
   second.
6. **`pool_key` is the identity the pool files a move under.** It equals the
   item's key, except on a lot that a state map moved to another item. The
   stock checks compare by `pool_key`.
7. **The pool as one leaves an in-house transfer out on both sides.** The
   reader drops moves of `transfer` events for the one pool, and keeps them
   for each company, as `_pool_events` does.
8. **The shadow carries no journal trigger** (`row_changes.SKIP`), because a
   rebuild rewrites it from journalled tables. The items and the state maps
   carry the trigger. Phase 2 takes the shadow out of `SKIP`.
9. **Phase 1 projects no links and no shipments.** History records what a
   click drew, not where each piece went. A unit's lot gets +1 at its first
   click and −1 at a scrap.

## The parity checks

`parity.check` rebuilds the shadow unless it is told not to, then compares:

| Check | Old answer | Tolerance |
|---|---|---|
| Quantity, value, lowest balance and first short day of each part, for the one pool and for each company | `run_actuals.pool_state` | 1e-6 pieces, 0.01 USD |
| What each lot got and what is left, in quantity and value | `lots.lot_state` | 1e-6 pieces, 0.01 USD |
| The parts of each click, the step draws and origin cost of each batch | `twins._step_draw_values`, `twins.origin_shares` | 0.01 USD |
| The status and the price of each unit | `twins.Twin.status`, `twins.prices` | 0.01 USD |
| The cost of each named unit's device | `twins.device_costs` | 0.01 USD |

**A change to one of those old functions fails `test_material_ledger.py`**
until the matching reader in `state.py` changes with it. That is on purpose:
the two models must stay equal until phase 3 removes the old reader.

## What the projector reports

`rebuild` returns `findings`, rows the projection could place but that look
wrong in the old tables:

| Finding | Meaning |
|---|---|
| `draws_bound_beyond_their_quantity` | A draw's bindings hold more than the draw. The ledger adds a move with no lot (`over_bound`) so that the item's balance equals the pool's |
| `draws_bound_to_a_lot_of_another_identity` | A draw filed under one pool identity is bound to a lot filed under another |
| `draws_naming_a_missing_click` | A draw's `step_run_id` names no click. The draw gets an event of its own |
| `twin_steps_without_click` | A twin's step names no click |

`lots.lot_state` values a positive adjustment with no price at 0, and
`pool_state` values it at the moving average. The ledger keeps both
(`lot_value_usd` and `value_usd`). Production held no such adjustment on
2026-10-23.
