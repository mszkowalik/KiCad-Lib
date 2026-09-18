---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# Count the devices that passed instead of typing how many a batch yielded

## Context and Problem Statement

Every per-device figure in the register divides by
`run.qty_good or run.plan_qty or run.qty`.

`qty_good` is documented on the model as *"units that actually passed. Actual
per-device cost divides by THIS"*. It is **NULL on every production run in the
platform**, and so is `plan_qty`. So every figure falls through to `qty` —
**boards ORDERED FROM JLC**.

That is not what a batch produced, and the gap is not small. JLC ships panel
overage, and boards fail test:

| Batch | Ordered | Passed |
|---|---|---|
| CE_Dongle_V2 Batch 5 | 455 | 568 |
| CE_Dongle_V2 Batch 3 | 450 | 406 |
| CE_Aqua_V2 Batch 5 | 250 | 183 |

[0007](0007-built-means-finished-and-passed.md) already settled this for stock:
`built` counts the devices that passed, from their `produced` events. The
register never followed, so one platform answered the same question two ways —
and the cost side was answering it with a purchase order.

The number was also wrong in a way nobody could see. A batch's `qty` is printed
in its own label (`Batch 7 — 1000 pcs`), which reads like a count of what
exists. On 2026-09-17 that reading made 32 delivered units look impossible and
sent a whole investigation down the wrong path.

## Decision Drivers

* The flasher already records what passed. A second, typed copy of the same
  fact can only drift from it.
* It DID drift, to NULL, on every run ever created — a field nobody fills is a
  field that does not work.
* [0029](0029-the-batch-on-a-produced-event-is-correctable.md) lets devices move
  between batches. A stored yield would need retyping after every move.
* A number this wrong should not be quiet. A 250-board batch that yielded 183
  must charge its cost to 183 units.

## Considered Options

* Derive good units from the device records; keep the field only as a legacy
  fallback.
* Fill `qty_good` from the programming runs with a job or a button.
* Type it per run by hand from the JLC delivery note.

## Decision Outcome

Chosen option: "Derive good units from the device records", via
`run_actuals.good_units(db, run)`.

1. **A batch with device records divides by the count of them.** A `produced`
   event is written on a device's first pass
   ([0003](0003-orders-shipments-and-device-history.md) §5), so counting those
   records IS what passed.
2. **`qty_good` survives as a fallback for a batch with NO device records** —
   the legacy runs from before the flasher. `qty` (boards ordered) is the last
   resort under that, not the answer.
3. **Every per-device divisor goes through the one function**: per-device
   actuals, the invoice register's per-run quantity (and so
   `per_device_cost_usd`, which every shipped device carries onto its order),
   a `per_device` invoice line scaled to the batch, the BOM draw in
   `consume_from_bom`, and the revenue fallback under `qty_sold`.
4. **`qty_recorded` in `run_stock` stays the TYPED quantity.** It is what the
   run says, printed beside `built` so the two can be compared. Deriving it
   would delete the comparison.
5. **The API reports the derived figure as `qty_good`**, with
   `qty_good_source` (`devices` | `typed`) beside it, and the run editor
   disables the box for a batch the flasher recorded.

### Consequences

* Good, because the cost side and the stock side finally answer "how many did
  this batch make" the same way.
* Good, because it needs no maintenance: a device added, or moved by
  [0029](0029-the-batch-on-a-produced-event-is-correctable.md), changes the
  denominator the moment it lands.
* Bad, because **twelve batches change their unit cost the day this deploys**,
  some by a lot: CE_Aqua_V2 Batch 5 $19.81 → $27.06 (+37 %), CE_Aqua_V2 Batch 3
  $19.80 → $15.09 (−24 %), CE_Dongle_V2 Batch 5 $16.33 → $13.08 (−20 %). Order
  margins move with them. The new figures are the correct ones, and any margin
  quoted from the old ones was quoted against a purchase order.
* Neutral, because a batch that lost boards to test now charges their cost to
  the units that survived, which is what a yield loss means.

### Confirmation

`api/tests/orders/test_reconcile.py`: a run whose `qty` says three, with five
devices recorded, answers five; a batch with no devices falls back to
`qty_good`, then to `qty`; and moving two devices between batches with
`rebatch_devices` moves the denominator from 5/5 to 3/7 with nothing retyped.

## Pros and Cons of the Options

### Derive it from the device records

* Good, because there is one fact and one place it is counted.
* Bad, because a batch programmed under the wrong batch id counts against the
  wrong denominator until somebody rebatches it — which is exactly what
  happened on 2026-09-17 and is why
  [0029](0029-the-batch-on-a-produced-event-is-correctable.md) exists.

### Fill `qty_good` from the programming runs

* Good, because it keeps one number in one column, which is easy to read.
* Bad, because it is a cache with no invalidation: every device added, failed,
  disposed or rebatched makes it stale, silently.

### Type it per run by hand

* Good, because the JLC delivery note is a document and the device records are
  an inference.
* Bad, because the field already exists for this and is NULL on every run in
  the platform. Two years of evidence that it does not get filled.

## More Information

* [0007](0007-built-means-finished-and-passed.md) — the same decision for
  stock, which this finally applies to cost.
* [0029](0029-the-batch-on-a-produced-event-is-correctable.md) — devices move
  between batches, which is why the denominator cannot be stored.
* [glossary.md](../reference/glossary.md) — `qty`, `plan_qty`, `qty_good` and
  `qty_sold` side by side, and why "Batch 7 — 1000 pcs" is a purchase order.
* Revisit this if a batch is ever built whose units are deliberately not
  programmed, so that passing devices stop being the measure of what it made.
