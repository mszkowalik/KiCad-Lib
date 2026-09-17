---
status: "accepted"
date: 2026-09-17
decision-makers: Mateusz Kowalik
---

# Reverse a shipment recorded in error, and never let a reversed delivery count as a previous one

## Context and Problem Statement

[0027](0027-a-stock-count-corrects-a-fifo-guess.md) gave a stock count the
power to reverse a FIFO guess, and the first real use of it exposed two gaps
within the hour.

A count on 2026-09-17 put 67 CE_Dongle_V2 units back on the shelf and they were
then shipped to the order they had been wrongly recorded against. The line
counted 32 deliveries, not 67. `create_shipment` marks a device as its own
replacement when it finds any earlier `shipped` event on the same line — the
rule that stops a repaired device counting twice — and it read the raw event
log, so the 35 deliveries the count had just REVERSED still looked like
previous deliveries.

That left a shipment on an invoiced order recording 35 replacements that were
plain deliveries, and nothing could take it back. `delete_shipment` refuses a
shipment that carries device events, `reconcile_shelf` refuses a `shipped`
event a person typed, and a `return_device` would claim a customer sent
something back.

## Decision Drivers

* A rule that reads the event log has to net reversals out. This is the second
  place that was wrong and it will not be the last.
* Recording a shipment is the write people get wrong most often, and it was the
  one write with no way back.
* Device history is not deleted. [0003](0003-orders-shipments-and-device-history.md)
  is explicit, and a delivery that was recorded and withdrawn is history.

## Considered Options

* Reverse the shipment with `unshipped` events and keep the header.
* Let `delete_shipment` remove a shipment once every delivery on it is
  reversed, taking the paired events with it.
* Correct the wrong `replaces_device_id` values in place.

## Decision Outcome

Chosen option: "Reverse the shipment with `unshipped` events and keep the
header", plus the fix to the rule that caused it.

1. **`create_shipment` reads `live_shipped_of(device)`, never `device.events`,
   when it decides whether a device is its own replacement.** A delivery an
   `unshipped` event reversed is not a previous delivery. A device that really
   was delivered, came back and went out again is still its own replacement and
   still counts once.
2. **`POST /api/shipments/{id}/reverse` takes back a shipment recorded in
   error.** Every delivery it still carries gets an `unshipped` event, its
   anonymous units go to zero, and the devices are back in stock. `dry_run` is
   the default, as in [0027](0027-a-stock-count-corrects-a-fifo-guess.md).
3. **The header and its events stay.** The shipment remains readable, counting
   nothing, with the reversal on every device's history. A shipment the
   customer actually RECEIVED still comes back through
   `POST /api/devices/{id}/return`; this is only for a delivery that was
   written down and did not happen.

### Consequences

* Good, because the write people most often get wrong now has a way back that
  does not invent a customer return.
* Good, because `live_shipped_of` gives the per-device answer that
  `live_shipped_events` gives per line, so the netting rule has one shape.
* Bad, because a reversed shipment stays visible in the order's list and reads
  as clutter. The alternative was deleting device history.
* Neutral, because reversing a shipment and creating the corrected one leaves
  two headers where a person would expect one.

### Confirmation

`api/tests/orders/test_reconcile.py`. Three tests carry this record: a count
that frees three devices, followed by shipping those same three on the same
line, must count ten deliveries and no replacement — the exact production
failure; a device returned, repaired and re-shipped must still be its own
replacement and still count once; and reversing a shipment of ten must take the
line to zero and every device back to stock.

## Pros and Cons of the Options

### Reverse with `unshipped` events, keep the header

* Good, because it reuses the instrument [0027](0027-a-stock-count-corrects-a-fifo-guess.md)
  already established and adds no new event kind.
* Bad, because the empty header stays on the order.

### Let `delete_shipment` remove a fully reversed shipment

* Good, because the order's shipment list would stay clean.
* Bad, because it deletes `device_events` rows, which
  [0003](0003-orders-shipments-and-device-history.md) protects, and the
  judgement of which pairs are safe to delete would live in code nobody reads
  twice.

### Correct `replaces_device_id` in place

* Good, because it is the smallest possible change.
* Bad, because it mutates an event after the fact, which is the one thing the
  log is not allowed to do, and it fixes this occurrence rather than the rule.

## More Information

* [0027](0027-a-stock-count-corrects-a-fifo-guess.md) — the stock count that
  writes the reversals this record had to make safe.
* [0003](0003-orders-shipments-and-device-history.md) §5, §7 — the event kinds,
  and why a replacement carries `replaces_device_id`.
* Revisit this if reversed shipments accumulate enough to make the order page
  hard to read.
