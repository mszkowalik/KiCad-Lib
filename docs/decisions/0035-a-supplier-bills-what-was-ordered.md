---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# Bill a supplier's per-board rate on what was ORDERED, and keep per-device cost dividing by what passed

## Context and Problem Statement

[0030](0030-good-units-are-counted-not-typed.md) made every per-device figure
divide by the device records a batch holds, instead of by the boards ordered
from JLC. That is right for COST: a batch that lost boards to test must charge
their cost to the units that survived.

`effective_qty` applied the same figure to a supplier's invoice. A
`basis='per_device'` line states a rate per board — LIFTECH's "5 PLN/board ×
350" — and the reconciliation multiplied it by `good_units` to compare against
the printed total.

Those are different quantities. Batch 2 holds **349** device records against
**350** boards LIFTECH assembled and invoiced. So the line reconciled to 1745
PLN against a printed 1750, and the $1.31 difference exceeded `IDENTITY_EPS`.
`_assert_identities` checks the identities absolutely, so **every `jlc_apply`
write path refused**, on one board's assembly fee, from the morning 0030
landed. The decision recorded for `SMT026080463762` could not have been applied
even if somebody had tried.

The user's rule, stated 2026-09-18: **"we ordered x units and will pay for x
units"**.

## Decision Drivers

* An assembler is paid for the boards they assembled. Our yield loss is ours,
  and billing it back to them by arithmetic is simply a wrong number.
* One figure was answering two questions. Whichever question it got right, it
  was wrong about the other.
* A conservation check that reads the whole database turns any such wrongness
  into a total outage of the import path, silently.

## Considered Options

* Two named functions: `planned_units` to bill, `good_units` to cost.
* Widen `IDENTITY_EPS` so small mismatches stop blocking.
* Type the real quantity onto the line and drop `per_device`.

## Decision Outcome

Chosen option: "Two named functions".

1. **`run_actuals.planned_units(run)` = `plan_qty or qty`** — what was ordered,
   and what a supplier bills for. `effective_qty` uses it for every
   `per_device` line.
2. **`good_units` is untouched and still owns cost.** Per-device actuals, the
   invoice register's per-run quantity, the BOM draw and the revenue fallback
   all keep dividing by the devices that passed, exactly as
   [0030](0030-good-units-are-counted-not-typed.md) says.
3. **A merged assembler invoice is SPLIT, never guessed.** Subcontractors bill
   several batches on one document. `POST /api/run-cost-lines/{id}/split` already
   makes one printed position into children charged to different runs, each
   inheriting `basis`, so a `per_device` child scales by its OWN batch.
   `effective_qty` never tries to work out which batches a line covers.
4. **Attrition is recorded per batch where it happens**, on the batch's
   Materials tab, as a `ComponentStockAdjustment` with `charge_run_id` set, so
   the loss lands in that batch's per-device figure. The Stock page keeps the
   same power for anything the batch view cannot express.

### Consequences

* Good, because the register's conservation identity holds again ($1.3363 →
  $0.0272) and the JLC import path works.
* Good, because the two questions now have two names, and a reader choosing
  between them has to choose deliberately.
* Neutral, because only ONE line in the platform has `basis='per_device'`, so
  nothing else moves.
* Bad, because `planned_units` reads `qty`, documented as "boards ORDERED from
  JLC", and an assembler's count can differ from JLC's. When it does, the line
  is split or given a flat quantity — it must not be papered over by changing
  what `qty` means.

### Confirmation

`api/tests/costs/test_uncharged_draws.py::test_a_per_device_line_is_billed_on_what_was_ordered`:
a 350-board run with a "5 PLN/board" line reconciles to the printed 1750 PLN,
and adding a device record — which moves `good_units` — leaves the bill at 350.

## Pros and Cons of the Options

### Two named functions

* Good, because the distinction survives in the code rather than in a comment.
* Bad, because a third caller could still pick the wrong one.

### Widen the tolerance

* Good, because it is one constant.
* Bad, because it hides the class of error the identity exists to catch, and the
  number here was RIGHT to be refused — it was a wrong figure, not rounding.

### Type the quantity and drop `per_device`

* Good, because a stated quantity cannot drift.
* Bad, because the rate is the fact on the invoice, and a typed product of it
  goes stale the moment a batch quantity is corrected.

## More Information

* [0030](0030-good-units-are-counted-not-typed.md) — the record this narrows.
  Its cost rule is unchanged; only the supplier-billing multiplier moves.
* [0034](0034-stock-moves-when-the-supplier-says-so.md) — the same shape on the
  stock side: what the supplier reports and what we conclude are separate facts.
* [production-economics.md](../reference/production-economics.md) — splitting a
  merged invoice, and which figure each per-device divisor uses.
