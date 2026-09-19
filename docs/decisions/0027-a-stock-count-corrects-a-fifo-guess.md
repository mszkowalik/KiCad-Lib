---
status: "superseded by 0032"
date: 2026-09-17
decision-makers: Mateusz Kowalik
---

# Let a stock count reverse a FIFO guess, and net the reversal out of every fulfilment figure

## Context and Problem Statement

[0003](0003-orders-shipments-and-device-history.md) §6 lets a shipment draw
devices FIFO from the batches an operator ticks, and says plainly that the
result is a guess: "which device is at which customer" is only right if the
operator ticked the right batches. It gave the guess exactly one correction
path — a customer returns a device the platform never sent, and
`_swap_into_line` swaps the returned device for one FIFO pick on the same line.

A shelf count is the other kind of evidence, and the platform could not read
it. On 2026-09-17 a count of 131 CE_Dongle_V2 units found 78 of them recorded
as delivered, every one by an `auto` FIFO pick. `create_shipment` refuses a
device that is not in stock, `delete_shipment` refuses a shipment that carries
device events, and `PATCH /api/flasher/devices/{id}` writes notes. There was no
way to record what was physically true.

The count also exposed a second problem. `DeviceEvent` is append-only, so an
`unshipped` event lands AFTER the `shipped` event it reverses and does not
remove it. Every fulfilment figure counted raw `shipped` rows, so a reversal
added a delivery instead of removing one.

## Decision Drivers

* A physical count is the best evidence the platform will ever get about where
  a device is. It must be able to enter.
* A guess and a statement are not the same thing. The operator who typed a
  serial said something; a FIFO pick did not.
* A shipment's quantity is what the customer was invoiced for. Correcting an
  identity must not silently change a quantity.
* The history is append-only and stays that way. Nothing is deleted.

## Considered Options

* Let a stock count reverse the `auto` FIFO picks it contradicts, and refill
  the slots they held.
* Direct SQL on the production database, no platform change.
* Widen the return path so an operator can "return" a device that never left.
* Leave it, and accept that device identity drifts from reality until a
  customer returns something.

## Decision Outcome

Chosen option: "Let a stock count reverse the `auto` FIFO picks it
contradicts", via `POST /api/stock/reconcile` and
`services/orders.py::reconcile_shelf`.

1. **A count names devices, by id or by the serial a scanner read.** One
   project per call.
2. **A device the count found, that the platform believes is at a customer,
   has its newest `shipped` event reversed with an `unshipped` event.** The
   original row stays; both are visible in the device's history.
3. **A `shipped` event with `auto = false` is never reversed.** A person named
   that device. The call fails and lists them. A count says where a device is,
   not who is wrong about it.
4. **The slot the reversal frees is refilled from stock**, oldest produced
   first — the order `fifo_candidates` uses, so the refill picks the device the
   original shipment would have picked. `refill` is `same_batch` (the default),
   `any_batch` or `none`. A device the count just found is never used as a
   refill: it is on the shelf.
5. **When no device is left to refill a slot, `keep_count` chooses between two
   true statements.** `true` turns the slot into one anonymous unit on that
   shipment (§8 of [0003](0003-orders-shipments-and-device-history.md)) and the
   invoiced quantity stands. `false` lets the quantity fall and the order show
   the shortfall. There is no third option where both stay comfortable.
6. **`dry_run` is the default.** The answer is the plan — what would be freed,
   what would refill it, what would not, and each order line's quantity before
   and after. Nothing is written until the same call arrives with
   `dry_run: false`.
7. **Every fulfilment and cost figure nets a reversal out**, through
   `live_shipped_events`, which pairs each `unshipped` with the most recent
   `shipped` for the same device and shipment. `line_shipped`, `_line_counts`
   and `order_economics` all read it.

### Consequences

* Good, because the one kind of evidence the platform sees most often — a
  person counting a shelf — can finally correct the record.
* Good, because the correction is events, like everything else in
  [0003](0003-orders-shipments-and-device-history.md). The guess and its
  reversal both stay readable in the device's history.
* Good, because the reversal fixes a defect that was already there: before
  this, the swap in `_swap_into_line` inflated a line's `qty_shipped` by one
  for every correction it made. No production order had a return yet, so no
  recorded figure changes.
* Bad, because a count that is itself wrong now writes history. `dry_run` and
  the refusal to touch a typed `shipped` event are the whole of the protection.
* Bad, because there is no UI. The endpoint is driven by an agent or by curl,
  and a scan sheet has to reach it by hand.
* Neutral, because `keep_count: true` can push a batch `overdrawn` in
  `run_stock` — more units shipped from it than it is recorded to hold. That
  reading is correct and the flag is the point.

### Confirmation

`api/tests/orders/test_reconcile.py`, against the dev database, in a
transaction that is rolled back. Ten devices go out FIFO, a count finds three
of them on the shelf, and the tests check each outcome: refilled and the count
holds at ten; nothing to refill with and the line falls to seven; nothing to
refill with under `keep_count` and the line holds at ten with three anonymous
units; `same_batch` refusing to cross a batch; a typed `shipped` event
rejected with 409; a dry run writing nothing. One more test covers the
regression `live_shipped_events` exists for — a return that swaps for a FIFO
guess must leave the line at ten, not eleven.

## Pros and Cons of the Options

### Let a stock count reverse the `auto` FIFO picks it contradicts

* Good, because it uses the vocabulary
  [0003](0003-orders-shipments-and-device-history.md) already defined:
  `unshipped` existed and meant exactly this.
* Good, because it is repeatable. The next count runs the same call.
* Bad, because it is a second writer of `unshipped`, so anything that reads
  `shipped` events has to net the pair — a rule that is easy to forget in a
  new query.

### Direct SQL on the production database

* Good, because it needs no code and fixes the data today.
* Bad, because it bypasses `record_event`, so the `at` monotonicity rule, the
  `state` cache and the audit row all depend on remembering them by hand.
* Bad, because the next count starts from nothing again.

### Widen the return path

* Good, because `_swap_into_line` already frees a guess and refills the slot.
* Bad, because it would record a `returned` event for a device that never
  left, and `qty_returned` is a warranty figure people read.

### Leave it

* Bad, because the platform would keep saying 91 dongles are in stock while 131
  sit on the shelf, and 37 units would stay recorded as delivered that never
  left the building.

## More Information

* [0003](0003-orders-shipments-and-device-history.md) — the order, shipment
  and device-history model this extends. §6 defines the FIFO guess; §8 defines
  the anonymous unit `keep_count` writes.
* [0007](0007-built-means-finished-and-passed.md) — why a batch is counted from
  its devices, which is what makes an anonymous unit impossible on a modern
  batch and forces `keep_count` to flag the batch overdrawn.
* [docs/reference/production-economics.md](../reference/production-economics.md)
  — where stock and fulfilment are computed.
* Revisit this if a stock count ever needs to correct a device somebody named
  by hand. That needs a second kind of evidence, not a wider count.
