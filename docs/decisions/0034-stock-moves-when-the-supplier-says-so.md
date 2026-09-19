---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# Move stock when the supplier reports it, and decide who pays separately

## Context and Problem Statement

Every JLCPCB manufacturing invoice carries `presaleDetailResultVOList`: one row
per consigned lot each assembly order consumed, with quantity, the price
actually paid, and the lot it came from. `jlc_invoice.parse` already checks
those rows sum to the invoice's own prepaid total, and `jlc_import`'s module
docstring records that `presaleGoodsKeyId` joins each draw to its purchase —
verified 50/50 on a real order. **What left the shelf is reported, not
inferred.**

Which production run pays for it is not reported. JLC's `number` on an assembly
line is PANELS when the order was panelised and no field anywhere says so, so
`plan_orders` derives the factor by having every part in the BOM vote, matches
the order to a run on quantity and date, and detects two orders claiming one
run. That is a chain of inference about COST.

The two were welded together. A draw could not exist without a run
(`component_consumptions.run_id` was `NOT NULL`), so the only path that wrote
one was `apply_decision` — which requires a human to have chosen a run, and then
to have pressed apply. A supplier's measurement waited on our bookkeeping.

On 2026-08-25 a decision was recorded for `SMT026080463762` and never applied.
The order's 441 consigned pieces stayed on our books for three weeks. The queue
counted the order as **decided** and stopped listing it, and the "only
undecided" filter hid it, so nothing could surface it. It was found on
2026-09-18 by comparing the pool against JLC's own stock count, part by part.

## Decision Drivers

* A fact the supplier states should not wait on a judgement we have not made.
* Stock control is the point of the pool. A movement that has happened and is
  not recorded is a hole in it, whatever the reason.
* The failure was silent and structural, not a slip: "decided" was treated as a
  synonym for "written", by both the count and the filter.
* Quantity and attribution have different sources, different certainty and
  different correction paths. Anything that stores them as one row, written at
  one moment, has to pick one and be wrong about the other.

## Considered Options

* Split them: write the stock on import, charge it when a run is decided.
* Apply the decision the moment it is recorded, so `applied_at` can never lag.
* Leave the coupling and only fix the queue so a stranded decision is visible.

## Decision Outcome

Chosen option: "Split them".

1. **`component_consumptions.run_id` is NULLABLE.** NULL means the stock left
   and nobody has been charged. It is the only field on a draw a later
   correction may move, for the same reason as `production_run_id` on a
   `produced` event ([0029](0029-the-batch-on-a-produced-event-is-correctable.md)):
   it records a CHOICE, not the event.
2. **Importing a manufacturing document writes its draws, charged to nobody.**
   `jlc_apply.draw_stock_for_invoice` runs inside the same journal batch as the
   document, because that document IS the statement of what left the shelf.
3. **The stock leg does not use the planner.** `jlc_import.stock_plans` reads
   the parsed invoice directly. The planner exists to guess a run and a panel
   factor — questions JLC does not answer — and the stock side needs neither.
4. **A decision charges draws that already exist.** `jlc_apply.charge_draws`
   UPDATES `run_id` and writes no new draw, so a judgement about cost can never
   restate a quantity the supplier reported. It refuses an order already charged
   to a different run rather than re-pointing it silently.
5. **`external` writes an UNCHARGED DRAW, never an adjustment.** In the ordinary
   flow the stock already left when the document was imported and the decision
   reports `already_booked`. When it did not — the document was never imported,
   or the order was deferred for an unresolved lot — `_book_external` writes the
   draw then. `external_stock_movements` and `apply_external_movements` are
   REMOVED: the shape they wrote has no writer left. The 27 rows they already
   wrote stay readable, `pool_state` counts them on `external` apart from
   attrition, and `_stock_already_booked` counts them too — otherwise a re-apply
   would write draws on top and take the same stock out twice. Those 27 rows were
   MIGRATED to uncharged draws on 2026-09-18 via
   `POST /api/jlc/import/adjustments/to-draws`, which refuses unless every row
   reproduces from its order plan; all 72 part balances were unchanged.
6. **An order whose lots cannot all be resolved is DEFERRED, not written
   unallocated.** The parts invoice is imported, then the document applied
   again; `uq_consumption_import` makes the rest a no-op.
7. **"Decided" is no longer a synonym for "written".** The queue counts
   `stranded` separately, and the filter now means *undecided or unapplied*.

### Consequences

* Good, because the platform's stock stops being gated on a decision about
  money. The 441 pieces could not have hidden.
* Good, because the two facts can now be corrected independently: a mis-linked
  run is one UPDATE, journalled and reversible, with the measurement untouched.
* Good, because `charge_draws` refusing a re-point is a real guard — moving
  components off a batch changes a per-device cost someone may have quoted from.
* Bad, because every reader of `ComponentConsumption.run_id` must now handle
  NULL. `invoice_register` reports the uncharged value as
  `pool.uncharged_drawn_usd` rather than filing it under a `None` run.
* Bad, because an uncharged draw is a new state that can accumulate unnoticed if
  nobody watches it. That is what `uncharged_drawn_usd` and the `stranded` count
  are for.
* Neutral, because orders imported before this have no draws at all, so
  `_charge_or_draw` keeps the old write path as a fallback.

### Confirmation

`api/tests/costs/test_uncharged_draws.py`, ten tests. The load-bearing ones: a
draw with no run still leaves the pool and is charged to no run; charging writes
no second row and moves no stock; charging twice is a no-op; an order already
charged to another run is refused; and a BOM forecast is superseded at the
charging step, because a forecast belongs to a run and the measuring step has
not named one.

## Pros and Cons of the Options

### Split them

* Good, because each fact is written when it is known, by whoever knows it.
* Bad, because it is a schema change on the money path and a new nullable state
  to keep an eye on.

### Apply on decide

* Good, because it is small and removes this instance completely.
* Bad, because it fixes the lag and not the coupling: an order nobody has
  decided still holds its stock, and "we have not worked out who pays" is not a
  reason for the shelf to be wrong.

### Only fix the queue

* Good, because it costs nothing.
* Bad, because it makes the hole visible instead of closing it, and the visible
  version still needs a human to act before the books are right.

## More Information

* [0030](0030-good-units-are-counted-not-typed.md) — the same principle on the
  other side: count what is recorded, do not type a number beside it.
* [0029](0029-the-batch-on-a-produced-event-is-correctable.md) — the precedent
  for one mutable field that records a choice rather than an event.
* [production-economics.md](../reference/production-economics.md) — the pool,
  the two legs, and the JLC-calendar rule for comparing against a stock count.
* Revisit this if uncharged draws stop being a transient state — a persistent
  balance in `uncharged_drawn_usd` means orders are not being decided at all,
  which is a process problem this record does not solve.
