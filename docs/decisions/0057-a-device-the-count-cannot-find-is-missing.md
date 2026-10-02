---
status: "accepted"
date: 2026-10-02
decision-makers: Mateusz Kowalik
consulted: Claude (the 2026-10-02 shelf count against the device records and the fleet broker)
---

# A device the stock count cannot find is missing, not disposed

## Context and Problem Statement

On 2026-10-02 every CE_Aqua_V2 unit on the shelf was read out by MAC and
compared with the records. 18 units recorded as shipped were on the shelf: early
deliveries named no serials, and the records are guesses
([0032](0032-a-shipment-names-its-devices.md)). 39 units recorded as in stock
were not on the shelf. 18 of them are online on the fleet broker, so they are at
the customer, and the user reported one more there. For the other 20, nobody
can say where they are.

The platform has no true record for such a unit. `in_stock` says it is on the
shelf. `disposed` says it was destroyed, and it is final: a delivery, a return
and a repair all refuse it. But the customer keeps finding devices that the
books do not show, and the broker keeps naming them
([0046](0046-the-broker-names-a-device-the-platform-already-counted.md),
[0054](0054-a-device-named-from-the-broker-gets-its-account-from-its-topic.md)).
A unit filed as destroyed today can be proven at the customer next month.

A second gap: a device found on the shelf can only leave its delivery by
reversing the WHOLE shipment ([0028](0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md)).
The 18 found units sit in two shipments of 450 and 1250 units that are
otherwise correct.

## Decision Drivers

* The shelf figure must be what is on the shelf.
* A record must not claim more than is known. "Not found at the count" is
  known. "Destroyed" is not.
* When evidence arrives (the broker, the customer), the correction must be an
  ordinary action, not a database fix.
* Nothing corrects stock by itself. Every write names its devices
  ([0032](0032-a-shipment-names-its-devices.md) §3).

## Considered Options

* A new location, `missing`, that a later delivery or a later find can leave.
* `disposed`, with "missing at stock count" as the reason.
* Ship the unfound units to the customer now, beyond the invoiced quantity.
* Keep them `in_stock` with a new condition `missing`.

## Decision Outcome

Chosen option: "a new location, `missing`", because it records exactly what the
count knows and stays correctable.

1. **`missing` is a location**, beside `in_stock`, `shipped`, `returned` and
   `disposed`. A `missing` event moves an `in_stock` device there, with the
   count's date and a note. Only `in_stock`: a packed device is in a box, so a
   count that cannot find it is a question about the box.
2. **A `missing` device can leave by three events.** `found` puts it back in
   stock. A delivery ships it, because the delivery itself is the evidence that
   it left; it still has to be condition `ok`. `disposed` writes it off when
   somebody decides it is gone for good.
3. **`missing` counts in no shelf figure.** It is not `in_stock`, not
   `available`, not `held`. Each batch and each product reports
   `devices_missing` beside them, so a missing unit is never invisible.
4. **One named device can leave one delivery.** A device found on the shelf
   gets an `unshipped` event for that delivery only and returns to stock. This
   is [0028](0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md)'s
   reversal applied to one device instead of one shipment. The rest of the
   shipment stays as it was, and the line's shipped count drops by one.
5. **Each of these is a deliberate call that names its devices**, with
   `dry_run` the default, as in 0028. No endpoint chooses devices, refills a
   freed place, or reacts to the broker by itself.
6. The device page offers "Missing", "Found" and "Unship" beside "Dispose".

### Consequences

* Good, because the shelf is true at once, and a unit the broker later finds
  ships from the UI like any other unit.
* Good, because "we counted and it was not here" stays separate from "it was
  destroyed", so a count can never hide a real write-off, or fake one.
* Good, because a wrong delivery can now be corrected one device at a time,
  without reversing hundreds of correct ones.
* Bad, because a third leaving path joins `shipped` and `disposed`, and every
  stock query has to exclude it on purpose.
* Neutral, because a missing unit keeps its `produced` event, so per-device
  cost ([0030](0030-good-units-are-counted-not-typed.md)) is unchanged.

### Confirmation

Tests in `api/tests/orders/`: a `missing` device counts in no stock figure and
appears in `devices_missing`; a delivery accepts it and refuses it when its
condition is not `ok`; `found` returns it to stock; `missing` is refused for an
allocated, shipped or disposed device; unshipping one device leaves every other
device in its shipment shipped, and drops the line by exactly one. Then a dry
run of the 2026-10-02 Aqua correction against production before it is applied.

## Pros and Cons of the Options

### A new location, `missing`

* Good, because it is the only option that is both true now and reversible
  later.
* Bad, because it adds a location value that every stock query must handle.

### `disposed`, reason "missing at stock count"

* Good, because it needs no code.
* Bad, because it claims destruction, and the precedent is bad: 32 working
  units were once filed `disposed` and stock read zero
  ([0032](0032-a-shipment-names-its-devices.md)).
* Bad, because each later find needs a one-off database correction.

### Ship them now, beyond the invoice

* Good, because a delivery can already exceed the ordered quantity.
* Bad, because none of the 23 units was ever seen online, so it records a
  guess as a delivery — what 0032 removed.

### `in_stock` with condition `missing`

* Good, because the condition axis already exists.
* Bad, because a condition says WHAT a unit is, not WHERE. A held unit counts
  in `devices_in_stock` as present (0032 §2), so the shelf would stay wrong.

## More Information

The 2026-10-02 CE_Aqua_V2 correction is applied once, by a reviewed script, in
the same shape as [0036](0036-the-dongle-device-log-is-rebuilt-from-the-facts.md):
it unships the 18 units found on the shelf, ships the 19 units proven at the
customer on a correction delivery of order ZAL 00001/09/2025 (16 into the freed
places, 3 in place of members never heard on the broker), adds 2 `unidentified`
placeholders ([0039](0039-a-prototype-is-counted-without-being-named.md)'s
shape) for the 2 places on FV 1/10/2024 that no known unit can fill, and marks
the remaining 23 `missing`. The counts and the evidence are in that script's
docstring.

Revisit if `missing` units pile up with no evidence ever arriving: then a rule
for when a count writes them off belongs here, not in a note.
