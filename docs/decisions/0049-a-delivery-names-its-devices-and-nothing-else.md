---
status: "accepted"
date: 2026-09-20
decision-makers: Mateusz Kowalik
---

# A delivery names its devices, and `shipment_lines` is gone

## Context and Problem Statement

[0032](0032-a-shipment-names-its-devices.md) decided that a shipment is a set of
serials. It made `create_shipment` refuse a bare `qty`, removed `fifo_candidates`
and deleted the startup migration that minted anonymous deliveries — calling
`qty_unserialized` in rule 5 *"the exact artefact rules 1 and 2 forbid"*.

It did not close the door. The same function still accepted `qty_unserialized`,
a quantity with a BATCH behind it, and `PATCH /shipment-lines/{id}` existed
purely to curate one. The user found it on 2026-09-20: *"there should be no
possibility to assign 'unserialized' to any batch or order. only per serial
assignments"*.

Three rows survived, 35 units, and **every one was a prototype batch**:

| line | units | batch | its own placeholders |
|---|---:|---|---:|
| 5 | 5 | 18 — V3.1 prototypes | **5, `in_stock`** |
| 6 | 10 | 20 — V3.3 prototypes | **10, `in_stock`** |
| 17 | 20 | Aqua prototypes | **22, `in_stock`** |

Each was double-counted against its own placeholder units — run 18 held 5 units
`in_stock` *and* a line claiming 5 had shipped from run 18 — which is precisely
the shape 0032 was written about ("order 1 carried 468 named devices plus 32
anonymous units that duplicated 32 devices the platform could already name").
`run_stock` netted the two to zero, so nothing looked wrong.

They were all prototypes for one reason: **a `prototype` placeholder cannot
ship.** 0032 rule 2 says only `ok` may leave on a shipment, so a prototype
delivery had nowhere to go but the anonymous count.

## Decision Drivers

* A quantity is a guess, and a batch behind it does not make it an observation.
* The mechanism was unreachable from the UI and reachable from the API, which is
  the worst of both: unused, unmaintained, and able to reappear.
* Removing the ability to make the write is worth more than another report.

## Considered Options

* Delete `shipment_lines` and let a prototype that really shipped be `ok`.
* Let prototypes ship behind an explicit per-shipment flag.
* Keep the table and refuse only new writes.

## Decision Outcome

Chosen option: **"Delete the table"**, with the condition question settled by the
user: a prototype that actually shipped carries `condition = ok`, leaving
`prototype` to mean *never left the building*.

1. **`shipment_lines` is DROPPED.** Its whole content was a quantity and the
   batch behind it; a shipment's real content is the `shipped` events pointing
   at it. The table was empty when it was dropped.
2. **The 35 anonymous units were replaced by the serials they stood for**, on
   the same deliveries, before the drop. Each batch had exactly the placeholders
   needed, so no unit was invented.
3. **A prototype that shipped is `ok`.** 70 device rows changed condition — the
   35 converted, plus 35 on the two Dongle prototype runs that were already
   named on shipments. `prototype` now means a unit that never left.
4. **There is no quantity field at all.** `ShipmentLineIn` sets
   `extra="forbid"`, so the SCHEMA refuses it and names it — and the published
   OpenAPI carries `additionalProperties: false` with the field absent. Keeping
   it declared in order to reject it was the first attempt and was wrong: an
   artefact that exists in order to be refused is still an artefact, on the
   schema, in the docs and in every generated client. Without `forbid` pydantic
   DROPS an unknown key silently, so the caller would get a shipment of nothing
   and no hint why — which is the only reason the field seemed worth keeping.
   `qty` was first kept as the exception, on the grounds that
   [0032](0032-a-shipment-names-its-devices.md) chose to answer it with a
   teaching sentence. The user refused the exception the same day — *"well, if we
   pass exactly qty to the system over API, then why adding it as parameter?"* —
   and was right: the argument against `qty_unserialized` does not weaken when
   the field is spelled `qty`. The sentence is not lost. It moved into the
   schema's docstring, which FastAPI publishes, and into the one guard that
   states the real rule: a line that moves NO DEVICE is refused with *"the
   shipment moves nothing — name the devices that left"*. One rule, one guard,
   no parameter that exists in order to be rejected.
5. **`PATCH /shipment-lines/{id}` is gone**, with `check_unserialized_source`.
   Keeping an endpoint to curate an artefact nothing can create is how the
   artefact comes back.
6. **A batch with no device records holds NOTHING, and is BUILT 0.** It used
   to hold its typed quantity as a pool the anonymous path could draw from
   (`legacy_stock`, `overdrawn`, `unserialized_shipped` — all removed). The
   pool's last survivor was `run_stock`'s `built`, which still fell back to the
   typed quantity: the shelf card went on showing units for which no serial
   could ever be produced, under a column headed **"No serial"**. The user
   caught it the next day — *"in that case why in 'orders' view theres 'no
   serial' column?"* — and the fallback is gone with the column. Record the
   devices, even as placeholders
   ([0039](0039-a-prototype-is-counted-without-being-named.md)), and they count
   like any other. `qty_recorded` stays beside `built` for comparison, labelled
   as boards ordered or assembled rather than as units.
7. **`qty_shipped_devices` is gone from the order payload.** It existed to
   say how much of `qty_shipped` was real when `qty_shipped` was devices PLUS
   anonymous units. Both count the same devices now, and a second name for one
   figure is a second thing to keep in step.
8. **A statement that reads a dropped column is SKIPPED, not failed.** Five
   phase-1 statements read `run_cost_lines.kind`, which
   [0047](0047-the-step-says-what-a-position-is.md) drops, so they failed on
   every boot afterwards and `GET /api/health/schema` was red for ever. A health
   page people are meant to read must not be a page they learn to ignore.

### Consequences

* Good, because one number answers "how many shipped", and it is the devices.
* Good, because the double count is gone rather than netted to zero.
* Good, because order 13 now counts 40 named devices where it counted 20 named
  and 20 anonymous.
* Bad, because `prototype` no longer marks a unit that was a prototype once it
  has shipped. That is the trade the user chose: the two axes stay clean only if
  `condition` describes the unit now.
* Neutral on money: every figure is unchanged.

### Confirmation

`test_a_shipment_refuses_a_quantity_with_a_batch_behind_it` asserts a
`ValidationError` naming `qty`, `qty_unserialized` and `source_run_id`, that none
of them is in `ShipmentLineIn.model_fields`, and that the service still refuses a
line moving nothing; `test_a_batch_with_no_device_records_holds_no_stock` asserts
the legacy pool AND the `built` fallback are gone while `qty_recorded` stays;
`test_the_shelf_payload_carries_no_quantity_counting_path` asserts the route emits
no key from the second counting path — it went on summing `overdrawn` after
`run_stock` stopped emitting it, and would have answered 500;
`test_the_shipment_line_table_is_gone` asserts the model is gone. Measured against
production data: `shipment_lines` DROPPED, orders 12 and 13 report 15 and 40
shipped devices with **0 uncosted**, all five prototype runs carry a per-device
cost, and the register reads gap 0.0 with unassigned 0.0. No non-planned batch
has zero device records, so dropping the `built` fallback moves no figure. 180
tests pass.

## More Information

Finishes [0032](0032-a-shipment-names-its-devices.md), which removed the
automatic path and left the manual one. Depends on
[0039](0039-a-prototype-is-counted-without-being-named.md) for the placeholders
that made the conversion possible at all.
