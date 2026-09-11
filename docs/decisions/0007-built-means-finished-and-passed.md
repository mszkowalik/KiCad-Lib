---
status: "accepted"
date: 2026-09-10
decision-makers: Mateusz Kowalik
consulted: —
informed: —
---

# Count a batch by the devices that passed, not by the quantity typed on it

## Context and Problem Statement

Decision 0003 item 8 defined stock per run as
`devices in stock + (qty_good − devices ever produced − unserialized shipped)`.
The second term was written for runs from before the flasher recorded MACs: a
batch nobody had serialised still had to be counted somehow, so the quantity
typed on the run stood in for the devices.

Applied to a batch that DOES have device records, that term is a claim about
boards nobody has seen. Measured on production on 2026-09-10: the shelf carried
118 units that exist in no record, worth $1,700 at cost — four on Dongle Batch 1
against 521 real devices, 44 on Batch 3, 67 on Aqua Batch 5. Two batches showed
the opposite sign, 113 and 47 units "overdrawn", because more devices had been
programmed than the run said were built.

The retro import had the matching hole in the other direction: it wrote a
`produced` event for every imported device, including 82 whose newest
programming or test run failed. A board that never passed sat on the shelf and
could be picked for a shipment.

The user's rule, stated on 2026-09-10: **a built device is one that is finished
and programmed or tested.** A failed programming loop does not build anything,
and several flash cycles of one MAC are one device with several runs.

## Decision Drivers

* The shelf must not hold units nobody can pick up. A number that cannot be
  walked to a shelf and counted is worse than no number.
* The typed run quantity is still needed: it is what was ordered from the
  assembler, it drives the BOM draw and the per-device cost, and when it
  disagrees with the device count that disagreement is the finding.
* Prototype runs from before device records exist must keep working. They are
  the one honest use of an unserialized unit.
* A rule about stock is read by the shipment guard, the demand figure, the Ship
  dialog and the register. It has to hold in all of them or none.

## Considered Options

* **Keep the typed quantity as the basis and fix the run quantities by hand.**
  Every batch would need its number corrected whenever yield changed, and the
  shelf would still be a claim rather than a count.
* **Count only devices, everywhere, and drop the unserialized path.** The V3
  prototype runs and the pre-flasher dongle batches would lose their history.
* **Count a batch from its devices as soon as it has any, and from its quantity
  only when it has none.** Chosen.

## Decision Outcome

Chosen option: count from the devices as soon as the batch has any.

1. **Built means finished and passed.** A device enters the shelf on a
   `produced` event, which the flasher writes on the first pass. A device whose
   newest run did not pass has no `produced` event, is not stock, and cannot be
   picked. A later pass puts it back.
2. **A batch with any device record is counted from its devices and nothing
   else.** `run_stock` sets the legacy pool to zero for such a batch. This
   overrides the second term of decision 0003 item 8 for those batches; the
   rest of 0003 stands unchanged.
3. **The typed quantity survives as `qty_recorded`** on every row of
   `GET /api/finished-stock`, so the number the assembler was given stays
   visible beside the number that passed.
4. **Only a batch with no device records at all is counted from its quantity.**
   That is the sole remaining source of an unserialized unit, and it is what the
   V3 prototype runs use.
5. **More devices than the recorded quantity is impossible and is marked.**
   Fewer is ordinary attrition and is not. The shelf card renders the first in
   red; it used to surface as an "overdrawn" count, which the new arithmetic can
   no longer produce for a device-tracked batch.
6. **A batch stays on the shelf card after its last device ships.** Selecting
   rows by what is left on them deleted six of seven dongle batches from the
   card the day this rule landed, and took the quantity mismatch with them. The
   card filters planned batches out and keeps the rest.

### Consequences

* Good, because the shelf is now a count of devices somebody can pick up:
  production fell from 306 units and $5,464 to 110 units and $1,821 on the day
  this was applied, and the 199 "overdrawn" units went to zero.
* Good, because a wrong run quantity is now visible as itself — Dongle Batch 5
  is recorded as 455 boards and has 568 devices, Batch 6 as 945 against 992 —
  instead of hiding inside a stock figure.
* Bad, because a batch mid-production under-reports: the moment its first device
  is programmed it stops counting the boards waiting at the station. A batch is
  either device-tracked or it is not, and that is the price of not mixing the
  two counting paths in one row.
* Bad, because the typed quantity still drives the BOM draw and the per-device
  cost while no longer driving stock. Dongle Batches 5 and 6 carry 455 and 945
  against run notes that say 600 and 1000 were built, so their parts draw and
  unit cost are still wrong until the quantities are corrected.
* Known gap: `engine.mark_produced` writes `produced` on the FIRST pass and
  never removes it, so a device that passes programming and later fails a test
  keeps its shelf entry. Live runs cannot be trusted for stock until a
  failed-after-pass event exists.

### Confirmation

`GET /api/finished-stock` on production: `legacy_stock` and `overdrawn` are zero
for every batch that has device records, and `stock` equals
`devices_in_stock`. Every device of a device-tracked project has exactly one
`produced` event and `last_status = "pass"`.

The migration that brought production to this state is
`docs/flasher/fix_built_is_passed.py` (dry-run by default). It refuses to finish
unless the re-picked shipments reproduce the original quantity of every
(shipment, order line) pair.
