---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# Count a prototype batch with unnamed placeholder units, and mark them unsellable

## Context and Problem Statement

The three CE_Dongle_V3 prototype runs had **zero** device units, so every
`device_count` read 0 and no per-device figure could be computed for the
project. The boards exist — JLC assembled 5, 10 and 10 of them — but none was
ever programmed through the platform, and a `DeviceUnit` is only ever created by
the flasher ([flasher.py:1793](../../api/app/routers/flasher.py#L1793),
[engine.py:688](../../api/app/services/flasher/engine.py#L688)), which writes the
MAC it reads out of the chip.

So the count is known and the identities are not. Decision
[0032](0032-a-shipment-names-its-devices.md) removed anonymous units precisely
because they had duplicated 32 real devices, and states the rule "every new
device will be assigned by its serial to a shipment".

## Decision Drivers

* A batch that built boards should not report 0 built.
* [0032](0032-a-shipment-names-its-devices.md) exists because an anonymous unit
  cannot be told from an observation once written. Whatever is written here must
  stay distinguishable forever.
* A prototype is not stock. It must never be picked for a customer shipment.
* `run_devices` is not an answer: it accepts free-text serials but nothing reads
  it, and it "has never held a row in any database"
  ([production_runs.py:88](../../api/app/routers/production_runs.py#L88)).

## Considered Options

* Placeholder `DeviceUnit` rows with no MAC, no serial, `condition="prototype"`.
* Invent serials so every unit is named, satisfying 0032 literally.
* Leave the prototype runs at 0 devices until someone flashes them.

## Decision Outcome

Chosen option: "Placeholder units, unnamed and unsellable", because it records
the one fact that is known — how many boards JLC assembled — without inventing
the facts that are not.

1. **One placeholder unit per board JLC assembled**, taken from the JLC assembly
   order linked to the run, not from the run's typed `qty`.
2. **`mac` is NULL and `serial` is empty.** The model already allows a NULL MAC
   for retroactively imported devices, and NULLs do not collide on the unique
   index. An empty serial is the truthful record of an unknown identity.
3. **`condition` is `prototype`**, the value 45 existing units already carry.
   Only `ok` may ship ([orders.py:476](../../api/app/services/orders.py#L476)),
   so these can never leave on a shipment or count as sellable stock.
4. **Each unit gets a real `produced` event** at the run's date, so
   `production_run_id`, `state` and the `good_units` denominator are computed by
   the same code path as a programmed device — not written by hand.
5. **This exempts prototypes only.** A production unit still enters by being
   programmed, and 0032 is unchanged for every batch that ships.

### Consequences

* Good, because per-device cost becomes computable for the V3 runs.
* Good, because `condition="prototype"` is a standing barrier rather than a note
  someone has to read: the shipment path refuses these units by itself.
* Bad, because 25 rows now exist that no physical scan can confirm. They are
  identifiable as a group — project 1, no MAC, no serial, condition
  `prototype` — and should be replaced, not amended, if the units are ever
  programmed.
* Bad, because the count is only as good as the JLC order. If JLC shipped fewer
  boards than it assembled, nothing here would notice.

### Confirmation

`GET /api/projects/1/runs` reports `device_count` 5, 10 and 10 for runs 18, 17
and 20. Every unit in project 1 reads `condition=prototype`, `state=in_stock`,
NULL MAC and empty serial, and each has exactly one `produced` event stamped at
its run's date.

## Pros and Cons of the Options

### Placeholder units, unnamed and unsellable

* Good, because it separates "how many" from "which ones" instead of faking the
  second to get the first.
* Good, because the units stay findable and deletable as a set.
* Bad, because it writes rows that a shelf count cannot verify.

### Invent serials

* Good, because it satisfies [0032](0032-a-shipment-names-its-devices.md) with
  no exception.
* Bad, because a fabricated serial is indistinguishable from a scanned one,
  which is the exact failure 0032 was written to end.

### Leave the runs at 0 devices

* Good, because nothing unverifiable is written.
* Bad, because every V3 per-device figure stays undefined, and the runs go on
  reporting that they built nothing.

## More Information

Supersedes nothing. Narrows [0032](0032-a-shipment-names-its-devices.md) for
prototype batches only. Related:
[0007](0007-built-means-finished-and-passed.md) and
[0030](0030-good-units-are-counted-not-typed.md) on what a device count is for,
[0029](0029-a-release-is-a-file-set.md) on the batch pointer being the copy that
gets corrected.

Revisit if the V3 prototypes are ever programmed through the bench: the
placeholders should then be deleted and the real units linked with
`POST /api/runs/{id}/produced`, never edited into place.
