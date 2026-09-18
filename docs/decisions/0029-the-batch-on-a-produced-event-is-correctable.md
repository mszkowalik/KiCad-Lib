---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# Let a later correction move the batch on a `produced` event, and nothing else in a device's history

## Context and Problem Statement

`mark_produced` is idempotent and refuses to file a device against a second
batch: "a device is produced once"
([0003](0003-orders-shipments-and-device-history.md) §5). The batch it records
is whatever the bench had selected when the first device of a shift passed.

On 2026-09-17 a shift was programmed with **Batch 8** selected, a batch on which
no board had been built. Thirty-one devices were filed against it, five of them
shipped to a customer before anybody noticed. Nothing in the platform could say
otherwise: `POST /api/runs/{id}/produced` calls `mark_produced`, which answers
409, and the `produced` event carries no reversal the way a delivery carries
`unshipped` ([0027](0027-a-stock-count-corrects-a-fifo-guess.md)).

The consequence is not cosmetic. A batch's device count is its `built` figure,
its stock, and the per-device cost every shipped device carries onto its order.
Thirty-one devices against an empty batch made Batch 8 report stock it never
held and left Batch 7 short of the units it actually produced.

## Decision Drivers

* A device's history records what HAPPENED. The batch on a `produced` event
  records a CHOICE somebody made from a list, which is a different kind of fact.
* Picking the wrong row from a dropdown is the most ordinary mistake on the
  bench, and it was the one mistake the platform made permanent.
* The append-only log is worth keeping. Whatever this allows must not become a
  general licence to edit history.

## Considered Options

* Let a correction move the batch on the `produced` event, and nothing else.
* A `rebatched` event kind appended to the log.
* Leave it, and correct the batch quantities instead.

## Decision Outcome

Chosen option: "Let a correction move the batch on the `produced` event", via
`POST /api/runs/{id}/rebatch` and `services/orders.py::rebatch_devices`.

1. **`production_run_id` on a `produced` event is the ONE reference in a
   device's history a later correction may rewrite.** It records a choice made
   at the bench before the fact, not an event.
2. **The event is not replaced and nothing is reversed.** Its
   `production_run_id` moves, its note keeps the batch it came from, the
   device's cached `production_run_id` follows, and the audit row names who
   moved it and from where.
3. **Everything else stays append-only.** A delivery is undone by `unshipped`
   ([0027](0027-a-stock-count-corrects-a-fifo-guess.md)), a shipment by
   `reverse_shipment` ([0028](0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md)),
   a device's state by the next event. None of those is an edit, and this
   record is not a precedent for making them one.
4. **A device with no `produced` event is not moved here.** It is linked with
   `POST /api/runs/{id}/produced`, which already exists for legacy units.
5. **`dry_run` is the default**, as on every other correction endpoint, and the
   plan names each device with the batch it would leave.

### Consequences

* Good, because the most ordinary bench mistake stops being permanent, and it
  can be corrected after the devices have shipped — which is usually when
  anybody notices.
* Good, because the batch's `built`, its stock and the per-device cost its
  units carry onto their orders all follow the corrected event, with no second
  path to keep in step.
* Bad, because one field in an append-only log is now mutable, and the reason
  it is allowed — "it records a choice, not an event" — is a distinction a
  later reader could stretch. Rule 3 exists to stop that.
* Neutral, because moving devices into a batch can push its `built` above the
  quantity typed on the run. That is `overbuilt()` on the Orders page and it
  is a true statement about a wrong run quantity, which is corrected on the
  run, not here.

### Confirmation

`api/tests/orders/test_reconcile.py`: a dry run moves nothing; a real move
changes the event, the device cache and both batches' `devices_produced`, and
leaves the origin batch in the event's note; a device already in the batch, one
that does not exist, and one from another project are each skipped with a
reason.

## Pros and Cons of the Options

### Move the batch on the `produced` event

* Good, because one field changes and every figure derived from it follows at
  once.
* Bad, because the event's history of itself is only its note and the audit row.

### A `rebatched` event kind

* Good, because it keeps the log strictly append-only.
* Bad, because `STATE_AFTER` maps every kind to a device state and this one
  changes no state, so it would be the first kind that does not fit the model.
* Bad, because every reader of `production_run_id` — stock, cost, FIFO — would
  have to learn to walk the log for the newest `rebatched` event, which is the
  mistake `live_shipped_events` had to be written to undo elsewhere.

### Leave it and correct the batch quantities

* Good, because it needs no code.
* Bad, because it makes the numbers agree by moving the wrong one: the devices
  really were built in another batch, and their cost belongs to it.

## More Information

* [0003](0003-orders-shipments-and-device-history.md) §5 — the event kinds and
  the "produced once" rule this narrows.
* [0007](0007-built-means-finished-and-passed.md) — why a batch is counted from
  its devices, which is what makes a mis-filed device change three figures.
* Revisit this if a second field in the log turns out to record a choice rather
  than an event. Two such fields is a pattern and wants a shape, not a second
  exception.
