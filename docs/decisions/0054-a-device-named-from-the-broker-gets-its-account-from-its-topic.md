---
status: "accepted"
date: 2026-09-29
decision-makers: Mateusz Kowalik
consulted: Claude (analysis of the unlinked broker topics against programming history)
---

# Name the last broker discoveries, and give every named device the account its topic derives

## Context and Problem Statement

[0046](0046-the-broker-names-a-device-the-platform-already-counted.md) left
open 10 `08:d1:f9` Aqua devices, a V3 device, a customer dev kit,
`cedonglev3ppp` and a second topic of unit 81. A new V3 topic,
`dongle_ACEBE6D34698`, appeared on 2026-09-29.

A second problem: 29 devices that 0046 named from the broker had no MQTT
account in the platform. No programming run of theirs is on record, so no
password was ever stored. The broker password file is generated from the
platform (`GET /api/flasher/mosquitto`). A file regenerated from the platform
alone would lock these devices out.

## Decision Drivers

* A device that is already counted must not be counted again (0046).
* The broker file must hold an account for every device we own, or a
  regenerated file disconnects it.
* The password is `base64(sha512(topic + salt))[:20]` with one fleet salt, and
  was always made this way (user, 2026-09-29). Checked: all 5,757 stored
  accounts equal the password derived from their own topic.

## Considered Options

* Aqua: fill 10 of the 20 shipped placeholder rows of run 10733.
* Aqua: create 10 new units.
* V3: create a new unit in run 2164, in stock.
* V3: fill a blank row of run 20.
* Accounts: derive the password from the topic.
* Accounts: import them from the broker's current password file.

## Decision Outcome

Chosen (user decisions 2026-09-29):

1. **The 10 Aqua devices fill shipped placeholder rows 28296–28305 of run
   10733**, the Aqua half of the 2024-02 prototype build. Order line 17 still
   reports 20 shipped.
2. **`dongle_ACEBE6D34698` is a new unit (28521) in run 2164**, "Batch 1 — 50
   pcs", with a `produced` event, so it is in stock. It was programmed on
   2026-09-29 outside the platform, so it has no programming run.
3. **Every device linked to a broker topic gets an account derived from that
   topic.** 41 accounts were added: 29 from 0046, the 10 Aqua, the new V3,
   and unit 81's second name. Each is stored as the programming engine stores
   one, with `set_by_run_id` NULL and an `AuditLog` row
   (`device.credentials_derived`).
4. **`dongle_405038` (a customer's ESP32 dev kit) and `cedonglev3ppp` are not
   ours.** They stay unlinked and get no account.
5. **`dongle_C82E189E4F38` is unit 81.** The topic is unit 81's MAC. It has
   an account (`current = false`, because the unit's programmed name stays
   `dongle_9E4F38`), but NO presence link yet. The device page, the project
   device list and the bench checks each assume one presence row per unit. A
   second row would list unit 81 twice and fail the bench check.

### Consequences

* Good, because the broker file now holds an account for every broker topic
  the platform links to a device. The export grew from 5,730 to 5,771 lines.
  Only the two topics that are not ours have none.
* Good, because unlinked topics fell from 41 to 30. The 30 are 27 old names of
  reflashed devices, unit 81's second name, and the two topics that are not
  ours.
* Neutral, because which placeholder row takes which Aqua MAC is arbitrary, as
  in 0046. `condition` stays `ok`, as the rows had it.
* Neutral, because unit 28521's `first_seen` is the broker's first sighting,
  not a bench reading. It is the first unit filed against run 2164.
* Bad, because a derived account proves only what the scheme gives, not what
  the broker holds today. The check against all 5,757 stored accounts is the
  evidence that the two agree.

### Confirmation

`scripts/identify-broker-devices-2026-09-29.py` ran as a dry run, then with
`REHEARSE=1` (rolled back), then with `APPLY=1`, after a `pg_dump` of the five
tables it touches. It verifies through the platform's own read paths:
`orders._line_counts` for line 17 before and after, the naming invariant
`tasmota_id = 'dongle_' || serial`, the new unit's state from its event, no
unit with two presence rows, the unlinked count, the line count of
`_mosquitto_file`, and the list of broker topics that have no account.

## Pros and Cons of the Options

### Fill run 10733's placeholder rows

* Good, because the count does not move, which is the 0046 method.
* Good, because the fit is strong. The Dongle half of the same order runs
  `CE_Dongle_v1` on Tasmota 13.3.0.2, and 5 of the Aqua devices run
  `CE_Aqua_v1` on 13.3.0.2. No production batch runs below 13.4.0. All 10 MACs
  lie within 100 addresses, and no other unit carries the `08:d1:f9` OUI.

### Create 10 new Aqua units

* Bad, because order line 17 already holds 20 shipped rows, so the new units
  would read as an over-delivery.

### Fill a blank row of run 20 for the V3 device

* Bad, because the device is from the latest batch (user), and run 20's blank
  rows are shipped prototypes.

### Import the accounts from the broker's password file

* Neutral, because it gives the same result as the derivation, which is proved
  for the whole history. It needs a file the platform does not hold.

## More Information

* The 27 old names are not unknown devices. Each is a topic that a device used
  before a bench reflash wrote the 12-hex name (2025-12-23, 2026-01-18,
  2026-09-17). The broker keeps the old topic's retained messages. See
  [mqtt-presence.md](../reference/mqtt-presence.md).
* Still open: linking a second topic to a unit (the 27 old names and unit
  81), which needs the one-row assumption removed from the code first.
