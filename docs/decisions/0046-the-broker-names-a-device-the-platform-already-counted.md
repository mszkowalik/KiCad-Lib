---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
consulted: Claude (analysis of the broker population against device_units)
---

# Give a counted device its name, do not count it again

## Context and Problem Statement

The fleet MQTT broker ([0033](0033-the-broker-observes-devices-it-never-commands.md))
carries 3,974 topics. 69 of them matched no device unit. The question was
whether those 69 are devices the platform never made, and where they belong.

They are not one thing. 28 are devices the platform already holds under a
different spelling of the topic. 14 are prototype-era hardware that the
2026-09-18 stock reconciliation ([0036](0036-the-dongle-device-log-is-rebuilt-from-the-facts.md))
had already counted, shipped and invoiced as anonymous `PROTO-xxxx` rows,
because no serial was recorded at the time. The rest are still open.

## Decision Drivers

* A device that is already counted must not be counted a second time. Both
  prototype order lines were already full (15/15 and 20/20).
* The broker is weaker evidence than programming, so it may fill a blank but
  never overwrite a recorded fact — the MAC rule from 0033, applied to identity.
* Prototype boards cost real money, and no production run ever held it.

## Considered Options

* Fill the existing `PROTO-xxxx` rows with the MAC and topic the broker reports.
* Create new device units for the 14 discovered devices.
* Create prototype production runs that HOLD the 14 devices.
* Assign discovered devices to whichever batch their MAC sits nearest.

## Decision Outcome

Chosen option: **fill the existing rows, and create the two prototype runs as
cost pools only**, because the rows already exist for exactly this purpose —
"real deliveries; no records were ever kept" — and filling one changes no count
anywhere.

Two runs were created, one per prototype order, and `PROTO-0001..0035` now point
at them through `production_run_id`. The same fill was then applied to two more
groups the broker found (user decision, 2026-09-19): 7 `CE_Dongle_V3_2` devices
into the blank prototype rows of run 20, and 8 `CE_Dongle_v2` devices on Tasmota
14.x into `PH-0001..0008`, the placeholders for the 2026-09-03 delivery. The runs hold the money. They do not hold a
delivery: the devices were already shipped against order lines 15 and 16 by 0036,
and that is still the only shipping event.

### Consequences

* Good, because 14 devices gained a real identity and a live presence row while
  every delivered count stayed exactly where it was. Their placeholder serials
  became real ones (`PROTO-0001` -> `86A438`), which restored the platform's
  naming invariant `tasmota_id = 'dongle_' || serial` to 4,575 of 4,575 units
  carrying a MAC. The old number is kept in `notes`, because decision 0036 and
  its reconciliation document still call these rows `PROTO-xxxx`.
* Good, because prototype cost finally has a denominator, so a supplier invoice
  can be charged to a batch like any other.
* Bad, because the two runs carry no cost documents yet, so they read as
  zero-cost batches until the prototype invoices are found and attached.
* Neutral, because WHICH anonymous row a device goes into is a judgement, not a
  proof. The device's identity is its own `tasmota/discovery` word; its
  provenance is not. So `condition` was left untouched — the 8 stay
  `unidentified` until a physical stock check confirms the serials, and every
  fill writes an `AuditLog` row naming the source, so a stock check that
  disagrees can undo exactly one device.
* Bad, because the 7 V3 devices still read `state = in_stock` while being
  deployed in the field. `state` is a cache of the newest `DeviceEvent` and must
  not be hand-edited; correcting it needs a real event and is not done here.
* Bad, because `PROTO-0036..0045` — 10 unsold prototypes — belong to no run, so
  the pools' denominators are the sold quantities rather than what was built.

### Confirmation

`scripts/identify-prototype-dongles.py` verifies through the platform's own read
path, not its own arithmetic: `orders._line_counts` must still report 15/15 and
20/20 on lines 15 and 16, and `GET /api/mqtt/status` must report exactly 14 fewer
unlinked rows. `scripts/identify-broker-discoveries.py` adds two more checks:
order line 22 must still report 292 shipped (measured before the write, and
again after), and `tasmota_id = 'dongle_' || serial` must hold for every unit
carrying a MAC. All three scripts were rehearsed against production with
`REHEARSE=1` and rolled back before `APPLY=1`.

After applying: unlinked **69 → 40**, runs 10729 and 10730 created, 29 devices
identified.

## Pros and Cons of the Options

### Fill the existing PROTO rows

* Good, because the count does not move — it is the same row, better described.
* Good, because the MAC comes from `tasmota/discovery`, the device's own report.
* Neutral, because which `PROTO` row takes which MAC is arbitrary; the rows were
  never distinguishable from each other in the first place.

### Create new device units

* Bad, because `_line_counts` sums serialized events AND `qty_unserialized`, so a
  new row against a satisfied line reads as an over-delivery.

### Create prototype runs that hold the devices

* Bad, because the same devices would then be delivered twice — once by 0036's
  shipping events and once by the new batch.

### Assign by nearest MAC

* Bad, because it does not work here and is unsafe where it does. Validated
  leave-one-out against 4,510 units with a known batch: 96.4% correct at k=6,
  median gap 4–8 inside a batch. But 39 of the 40 unmatched devices have no
  neighbour at any distance — nearest matches sit at the 46th–65th percentile of
  pure chance. The one device the rule placed confidently (Δ12, 6/6 agreement)
  reports `hw_model` `ESP32-DevKit`: a dev board, not a produced unit. Proximity
  cannot separate a dev board from product hardware, because both came off the
  same reel.

## More Information

* **What discovery cannot fill.** The announcement carries `mac`, `t`, `md`,
  `sw`, `hn` and `ip` and nothing else, so `DeviceUnit.chip` stays empty on these
  14: `md` is the Tasmota module name (`CE_Dongle_v2`), not a chip, and copying
  `ESP32` from the other 5,405 rows would be inference, not evidence.
  `first_seen` and `last_seen` were also left alone — only the programming
  engine writes them, so they mean "seen by the bench", and the broker's own
  timestamps already live on the presence row. Inverter, inverter serial, dongle
  firmware, Tasmota version and IP have no column on `DeviceUnit` at all; they
  belong to `device_presence` and the device page reads them from there.
* `hw_model` from `tasmota/discovery` is stronger provenance than the MAC. It
  names the firmware's build target and separated `CE_Dongle_v1`, `CE_Aqua_v1`
  and `ESP32-DevKit` out of a population the MAC could not split.
* Tasmota version is a second dating signal: the minimum across all 12 recorded
  batches is 13.4.0, and every device identified here runs 13.3.0.2.
* **Group B matches nothing in the platform, checked four ways**: exact topic,
  full MAC equality, unit `tasmota_id` against the 12-hex spelling of the
  device's MAC, and the MAC's last three bytes against every MAC-less unit's
  6-hex id, case-insensitive. Only the 12 Group A rows ever hit, and those
  already carry a MAC. A related correction: the ~863 "placeholders" first
  counted in batches 5–9 and 12–15 are NOT placeholders. 662 of them carry a
  `tasmota_id` — they are named devices missing a MAC, exactly as `models.py`
  describes for V2-era imports. Only **97** rows in the whole platform are
  genuinely anonymous.
* Still open, and deliberately not decided here: 10 `08:d1:f9` Aqua devices,
  whose order line is already satisfied by `qty_unserialized = 20` and for which
  project 3 holds **zero** anonymous rows, so only a conversion could identify
  them; one `ESP32-DevKit`; `cedonglev3ppp`; `dongle_C82E189E4F38`, a second
  topic for device 81; and the linking rule itself — presence still links by
  exact topic string, so the 27 spelling mismatches remain unlinked.
