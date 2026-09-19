---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# A shipment names its devices, and nothing corrects stock automatically

## Context and Problem Statement

Device stock had two counting paths and three automatic correction mechanisms,
and between them they made a miscount impossible to rule out.

**The platform chose which devices shipped.** A shipment line could carry a
quantity and a set of batches, and `fifo_candidates` picked the oldest units
(decision [0003](0003-orders-shipments-and-device-history.md) §6). Measured on
2026-09-18: **4326 of 4427 deliveries were such guesses, and only 101 were ever
named by a person** — the serials scanned on 17 and 18 September. A guess cannot
be told from an observation once it is written, so the only way to find a wrong
one was to count the shelf physically.

**A delivery could name no device at all.** `qty_unserialized` charged units to
a batch anonymously (§8). Two figures then had to agree about one delivery, and
they did not: order 1 carried 468 named devices plus 32 anonymous units that
duplicated 32 devices the platform could already name.

**Three mechanisms corrected data on their own.** `reconcile_shelf`
([0027](0027-a-stock-count-corrects-a-fifo-guess.md)) reversed guesses a count
contradicted and refilled the freed places from stock — writing new guesses in
the act of removing old ones, and inventing 40 anonymous units on 2026-09-17.
`_swap_into_line` let a return against the wrong line silently un-ship whichever
device FIFO had put there. `create_shipment` decided by itself when a delivery
was a replacement rather than a delivery, and got it wrong twice.

There was also no way to say a device is HERE but must not be sold. `state`
answers location only, so 32 working-but-unsellable units had to be filed
`disposed`, which claimed they had been destroyed and reported stock as zero
when 32 units were on the shelf.

## Decision Drivers

* A count that cannot be reconstructed from physical facts is not a count.
* Every correction instrument in this platform was built AFTER a bad write.
  Removing the ability to make the write is worth more than a fourth instrument.
* The user's rule, stated 2026-09-18: **"every new device will be assigned by
  its serial to a shipment"**, and no automatic stock fixing.

## Considered Options

* Name every device, drop the automatic mechanisms, and add a condition axis.
* Keep FIFO but require a confirmation step.
* Keep everything and add a reconciliation report.

## Decision Outcome

Chosen option: "Name every device, drop the automatic mechanisms".

1. **A shipment is a set of serials.** `create_shipment` refuses a quantity
   with no devices behind it, with 422 saying so. `fifo_candidates` no longer
   feeds it, and the Ship card has no quantity box and no batch picker — the
   batch table is read-only, there to show the shelf while you scan.
2. **`condition` is a second axis on the device**, independent of `state`:
   `ok`, `faulty`, `prototype`, `unidentified`. **Only `ok` may ship**, and
   every stock query filters on it. A unit that cannot be sold stays visible,
   stays counted and stays put. `devices_available` and `devices_held` are
   reported beside `devices_in_stock`, which is their sum.
3. **Nothing corrects stock automatically.** `reconcile_shelf` and
   `POST /api/stock/reconcile` are removed, superseding
   [0027](0027-a-stock-count-corrects-a-fifo-guess.md) entirely.
   `_swap_into_line` is removed: a return against a line the device was never
   delivered on is now a 409 naming the lines it WAS delivered on. A wrong
   delivery is corrected by fixing the shipment, deliberately, not as a side
   effect of recording something else.
4. **A delivery is a permanent record.** Its row is never deleted or edited, so
   an order reports `ordered`, `shipped`, `returned` and `with customer`
   separately. A replacement is +1 shipped and is visible as such; fulfilled
   means *with customer ≥ ordered*, never *shipped ≥ ordered*.
5. **The startup migration that minted deliveries is gone.**
   `_migrate_run_sales` ran on EVERY boot and turned any production run with a
   sale price into a customer, an order, and a `Shipment` carrying
   `qty_unserialized` — the exact artefact rules 1 and 2 forbid, written with no
   audit row, no dry run and no user asking. It was not one-shot: a run priced
   tomorrow became an order and a delivery at the next restart. Removed with
   `migrate_from_runs`, along with the now-dead `fifo_candidates`.
6. **`reverse_shipment` stays.** It is explicit, takes a whole shipment, and is
   the sanctioned way to undo a delivery recorded in error
   ([0028](0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md)).

### Consequences

* Good, because one number answers "how many shipped": the devices on the
  delivery. Two figures can no longer disagree.
* Good, because a device that does not exist, is not in stock, or is not `ok`
  is refused BY NAME instead of quietly skipped or silently swapped.
* Good, because roughly 300 lines of correction machinery are gone, along with
  the bugs that lived in them.
* Good, because the platform no longer writes sales history at startup. An
  order and a delivery are now things a person records.
* Bad, because the 4326 historical guesses stay in the log. They are the best
  record available, and this record does not licence rewriting them silently —
  the one-time reconstruction is a separate, deliberate act.
* Bad, because a shipment can no longer be recorded without the serials to
  hand. That is the point, and it means the scan must happen at packing.

### Confirmation

`api/tests/orders/test_reconcile.py`, 21 tests. Three carry this record: a
shipment given a quantity and no serials is refused with 422; a device whose
condition is `faulty` is refused with 409 naming the condition and stays in
stock; and a faulty unit still counts in `devices_in_stock` while being absent
from `devices_available`.

## Pros and Cons of the Options

### Name every device, drop the automatic mechanisms

* Good, because the invariant `programmed = in_stock + at_customer + returned +
  scrapped` becomes checkable per batch, which nothing could do before.
* Bad, because historical data must be reconstructed once by hand before the
  invariant holds.

### Keep FIFO with a confirmation step

* Good, because it needs almost no change.
* Bad, because a confirmed guess is still a guess. The stock count of
  2026-09-17 was exactly such a confirmation and it wrote 40 impossible units.

### Keep everything, add a reconciliation report

* Bad, because `overdrawn` already was that report. It showed the contradiction
  for two years and nobody looked.

## More Information

* [0003](0003-orders-shipments-and-device-history.md) §6 and §8 — the FIFO pick
  and the anonymous unit, both narrowed to history by this record.
* [0027](0027-a-stock-count-corrects-a-fifo-guess.md) — superseded.
* [0031](0031-a-batch-that-records-its-devices-has-no-anonymous-units.md) — the
  first half of this argument, reached one day earlier.
* [../reference/dongle-stock-reconciliation.md](../reference/dongle-stock-reconciliation.md)
  — the measured state this record was written from, and the one-time
  reconstruction it enables.
* Revisit this when a product is built that is deliberately not programmed, so
  that a serial stops being the thing a shipment can name.
