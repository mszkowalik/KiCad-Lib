---
status: "accepted"
date: 2026-10-18
decision-makers: Mateusz Kowalik
---

# Reset the presence stamps that the replay of 2026-09-28 wrote

## Context and Problem Statement

Before decision [0056](0056-a-unit-owns-every-topic-it-was-given.md), a
retained replay moved `last_seen_at`, `last_online_at` and `last_offline_at`
as if the device had spoken. On 2026-09-28 between 20:24:08 and 20:24:29 CEST
one replay did that to 1141 of 4236 `device_presence` rows on production. No
live message reached any of them afterwards, so each still said "last heard
2026-09-28 20:24". 0056 left the reset to a separate decision.

The shipment view of 2026-10-18 counts a unit as heard after it shipped when
`last_seen_at` is later than the shipment. On shipment 24 that counted 144
units that had said nothing since they left.

## Decision Drivers

* "Last heard" must mean a live message, or the shipment count and the device
  page both claim contact that never happened.
* `device_presence` is derived and has no change history (decision 0089 skips
  it), so the database backup is the only way back.

## Considered Options

* Reset the stamps of that replay window
* Leave them and hard-code the replay time in every reader
* Leave them and accept the false counts

## Decision Outcome

Chosen option: "reset the stamps of that replay window", because it fixes the
data once and keeps the readers free of a special date.

1. Rows with `last_seen_at` in 2026-09-28 18:24 UTC: `last_seen_at` becomes
   the row's `temperature_at` when that is earlier (a SENSOR message is never
   retained, so it is live), else NULL. 71 rows kept a SENSOR time, 1070 are
   empty.
2. `last_offline_at` in that minute becomes NULL (1140 rows) and
   `last_online_at` in that minute becomes NULL (4 rows). A replay is not a
   change of state.
3. The state columns (`online`, `lwt`, `persist`, discovery) are not touched.
   They are the broker's current answer.

### Consequences

* Good, because shipment 24 now counts 806 of 1231 units heard since shipping,
  with no replay time among them.
* Bad, because the real last-heard time of the 1070 emptied rows is lost. It
  was lost already: the replay overwrote it.
* Neutral, because a row with an empty `last_seen_at` still exists, so the
  device is "seen once, time unknown", not "never seen".

### Confirmation

Run on production on 2026-10-18 in one transaction, after the backup
`~/kicadlib-backups/before-e65a003-20261018.dump`: 1141 rows reset, 0 stamps
left in that minute in any of the three columns. `GET /api/shipments/24`
reports `heard: 806, of: 1231`.

## Pros and Cons of the Options

### Reset the stamps

* Good, because every reader is right again with no code change.
* Bad, because it rewrites rows that have no change history.

### Hard-code the replay time in the readers

* Good, because no data changes.
* Bad, because every present and future reader must remember one date.

### Accept the false counts

* Good, because nothing changes.
* Bad, because the shipment view would prove installs that did not happen.

## More Information

The presence model is in [mqtt-presence.md](../reference/mqtt-presence.md).
