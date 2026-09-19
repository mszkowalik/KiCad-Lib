---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# Refuse a purchase edit that would strand a draw, and allow every one that stays covered

## Context and Problem Statement

`check_shortages` has guarded the DRAW side since draws existed: a consumption
that would take a part's balance below zero at any point from its date onward is
refused. Nothing guarded the PURCHASE side. A document could be force-deleted, a
quantity cut, a line voided or a component link re-keyed out from under the
consumptions priced against it.

The draws survive. They are their own rows in `component_consumptions`, their
`unit_cost_usd` is snapshotted when they are made, and `lot_line_id` is a soft
pointer with no foreign key — so nothing errors. The pool simply goes negative,
the register reports it under `issues.negative_stock`, and the run goes on
paying for stock that no invoice bought.

Demonstrated 2026-09-19 on the Mouser antenna line: unlinking its component
split the pool into `m1461530050` (810 bought, 0 used) and `c326` (4430 bought,
4325 used). Deleting the document instead would have left the batch's 800-piece
draw with 4430 bought against 5125 used.

## Decision Drivers

* Money already charged to a batch must have a purchase behind it.
* The correction has to stay possible. A guard that locks the register is worse
  than no guard, because the next correction then happens in the database.
* A check that already exists and is already trusted beats a second one that can
  disagree with it.

## Considered Options

* Refuse only when the change would take the balance below zero (date-aware).
* Refuse whenever the part has any consumption at all.
* Warn and let it through, leaving `issues.negative_stock` to report it.

## Decision Outcome

Chosen option: "Refuse only when the change would strand a draw", because it
stops exactly the damage and nothing else.

**Both rules were measured on the real database before choosing.** Of 264 pooled
part lines, the blunt rule locks **260** — every parts invoice older than the
first batch that drew from it, including one that could lose its whole quantity
and still cover every draw. The chosen rule locks **195**, and each of those
genuinely cannot give its stock back.

1. **One primitive, no second opinion.** Removing X units of a purchase dated D
   lowers the balance from D onward by exactly as much as adding a draw of X on
   D, so `check_purchase_loss` delegates to `check_shortages`. The two can never
   disagree about a timeline.
2. **Four call sites**, all in `routers/run_costs.py`: deleting a document,
   patching a line, voiding a line and splitting one.
3. **`force=true` does not waive it.** That flag waives "this document still has
   lines", which is about care. This is about arithmetic.
4. **A re-key is a total loss to the old key**, however small the quantity edit
   beside it looks — the purchase leaves that pool entry entirely.
5. **Leaving the pool counts as a loss too**: charging a part line to a run, or
   marking it `excluded`, takes it out of the pool exactly as deleting it would.

### Consequences

* Good, because a run can no longer be charged for stock with no purchase
  behind it, and the failure is refused at the write instead of reported after.
* Good, because the refusal names the short parts and the quantities, so it says
  what to fix.
* Bad, because 195 of 264 lines cannot be corrected in place today. The way out
  is a stock adjustment for the difference, which is a recorded act rather than
  a silent one.
* Neutral, because proforma lines and run-charged parts are untouched: neither
  ever fed the pool.

### Confirmation

`api/tests/costs/test_purchase_guard.py` — eight cases, including the one the
rejected rule would have got wrong (`test_an_untouched_part_is_never_locked`).
Against the live register: unlinking the Mouser antenna line is allowed (4430
left against 4325 used), unlinking CH340B on document 116 is refused (5227
against 5227), and force-deleting document 116 is refused with 30 shortages.

## Pros and Cons of the Options

### Refuse only when it would strand a draw

* Good, because it permits every correction that keeps the books consistent.
* Good, because it reuses the check the draw side already trusts.
* Bad, because "will this be allowed?" cannot be answered by looking at one row.

### Refuse on any consumption

* Good, because the rule fits in a sentence and needs no replay.
* Bad, because it locked 260 of 264 lines when measured — in practice, no parts
  invoice in the platform could be corrected again.

### Warn only

* Good, because nothing is ever blocked.
* Bad, because it is what the platform already did, and it is how the negative
  balance arrived in the first place.

## More Information

Extends [0034](0034-stock-moves-when-the-supplier-says-so.md) and
[0027](0027-a-stock-count-corrects-a-fifo-guess.md), which is the recorded way
to make up a difference this guard refuses to let you take silently.

Revisit if draws gain a hard foreign key to the purchase lot they consumed:
`ComponentConsumptionLot.lot_line_id` is deliberately soft today, and a real
constraint would move part of this guard into the database.
