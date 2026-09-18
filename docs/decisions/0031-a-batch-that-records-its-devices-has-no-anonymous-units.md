---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# Refuse an anonymous unit from a batch that records its devices, and drop the option to invent one

## Context and Problem Statement

A shipment line may carry `qty_unserialized` — units that left without naming a
device — charged to a `source_run_id`
([0003](0003-orders-shipments-and-device-history.md) §8). It exists for batches
made before the flasher recorded MACs.

`run_stock` already says, in arithmetic, that such a unit cannot come from a
batch the flasher recorded: a batch with ANY device record gets a legacy pool of
**zero**, so every anonymous unit charged to it is `overdrawn`. That is reported
afterwards, on a page, as a warning about the BATCH — when it is really a
contradiction in the SHIPMENT.

Nothing enforced it at the point of writing. On 2026-09-17 a stock count wrote
**40 such units** — 32 against CE_Dongle_V2 Batch 1, which holds 521 device
records, and 8 against Batch 7, which holds 1025 — under
[0027](0027-a-stock-count-corrects-a-fifo-guess.md) §5's `keep_count`, an option
whose whole purpose was to keep an invoiced quantity whole by inventing the
missing unit. The flag appeared as designed and nobody was looking at it.

The user's rule, stated 2026-09-18: **"if there's no serial number, then there
was no production"**.

## Decision Drivers

* The rule was already true in the arithmetic. It was reported, not enforced,
  and so it was broken.
* A figure that reads as a warning about one thing while being a contradiction
  in another is worse than no figure.
* Stock control is the point. A produced unit the platform cannot name is a
  hole in it.

## Considered Options

* Refuse the write, and drop `keep_count`.
* Warn at the point of writing but allow it.
* Leave it: `overdrawn` already reports it.

## Decision Outcome

Chosen option: "Refuse the write, and drop `keep_count`".

1. **`check_unserialized_source` refuses any anonymous unit charged to a batch
   that has device records**, with 409 naming the batch and how many devices it
   records. It guards `create_shipment`, `reconcile_shelf` and
   `PATCH /api/shipment-lines/{id}` — every path that can write one.
2. **`keep_count` is removed from `reconcile_shelf` and its endpoint and UI.**
   It cannot be honoured under rule 1 and never could have been: the batch it
   would draw from is the freed device's OWN batch, which records that device
   by definition. A parameter that can only ever answer 409 is a trap.
3. **A slot nothing can refill lowers what its order counts as delivered.**
   That is now the only outcome. Either another real device fills it, or the
   quantity falls and the order shows the shortfall.
4. **The reader stays.** `qty_unserialized` is still counted in every stock and
   fulfilment figure, because 110 historical units depend on it. What stops is
   new ones being written against a batch that knows its own devices.

### Consequences

* Good, because the rule is enforced where it is broken instead of reported
  where nobody looks.
* Good, because a stock count can no longer make an order's quantity whole by
  inventing a unit. If the devices are not there, the order says so.
* Bad, because it narrows [0027](0027-a-stock-count-corrects-a-fifo-guess.md)
  §5 to one branch a day after that record was accepted. The option was wrong
  when written.
* Bad, because the 40 units already written are now the only ones of their kind
  and the platform will not let them be rewritten the same way. They have to be
  settled as a commercial fact: either those deliveries happened and the device
  records are incomplete, or the orders are short.

### Confirmation

`api/tests/orders/test_reconcile.py`: a shipment drawing anonymous units from a
batch with five device records is refused with 409 naming the batch; a batch
with none still hands them out and its legacy pool draws down correctly; and a
count whose slots cannot be refilled lowers the line from 10 to 7 with no
`unserialized` key in the plan at all.

## Pros and Cons of the Options

### Refuse the write, drop `keep_count`

* Good, because there is then one way for a unit to leave stock that the
  platform can audit: a device with a serial.
* Bad, because a batch whose device records are genuinely incomplete now has no
  way to ship the remainder except by recording those devices.

### Warn but allow

* Good, because it keeps the escape hatch for incomplete records.
* Bad, because the warning already existed, in the form of `overdrawn`, and it
  did not stop 40 units being written. A second warning in the same place is
  not a different outcome.

### Leave it

* Bad, because the arithmetic disagreeing with what the platform lets you write
  is how this happened in the first place.

## More Information

* [0003](0003-orders-shipments-and-device-history.md) §8 — what an
  unserialised unit is and which batches may hold one.
* [0027](0027-a-stock-count-corrects-a-fifo-guess.md) §5 — the `keep_count`
  option this removes.
* [0030](0030-good-units-are-counted-not-typed.md) — the same principle on the
  cost side: count the devices, do not type a number beside them.
* [glossary.md](../reference/glossary.md) — "without a serial" and "overdrawn".
* Revisit this when the last order fulfilled by unserialised units is closed:
  the reader can go then, and stock becomes devices only.
