---
status: "accepted"
date: 2026-09-29
decision-makers: Mateusz Kowalik
consulted: Claude (analysis of the unlinked broker topics against programming history)
---

# A unit owns every broker topic it was given, and a replay is not the device speaking

## Context and Problem Statement

A bench reflash renamed 78 units from a 6-hex topic to a 12-hex one
(`dongle_42AD24` -> `dongle_F8B3B742AD24`). The broker keeps each old topic's
retained messages, so 27 old names sat in the unlinked list as if they were
unknown devices. Presence linked a topic only when it equalled the unit's
current `tasmota_id`, and the readers assumed one presence row per unit.
[0046](0046-the-broker-names-a-device-the-platform-already-counted.md) and
[0054](0054-a-device-named-from-the-broker-gets-its-account-from-its-topic.md)
left the link rule open.

A second defect made the first one hard to read: every retained message moved
`last_seen_at`. On 2026-09-28 one reconnect stamped every offline topic in the
same minute, so "last seen" on an offline row was the watcher's reconnect.

## Decision Drivers

* The broker account of an old name stays valid, because a device running an
  old config still connects with it (user, 2026-09-29). So an old name is a
  real, live possibility, not dead data.
* Evidence, never a guess: `8BD26C` is the 6-hex tail of two different
  devices' MACs.
* The broker may fill a missing fact but never change a recorded one
  ([0033](0033-the-broker-observes-devices-it-never-commands.md)).
* The platform never publishes to the broker (0033), so clearing the old
  retained topics is not available to it.

## Considered Options

* Link by evidence rules, and let a unit own several presence rows.
* Link the old rows by hand, one presence row per unit kept.
* Ask the broker owner to clear the old retained topics.
* Change the unit's `tasmota_id` to whatever name the broker shows.

## Decision Outcome

Chosen option: **link by evidence rules, and let a unit own several rows**.

1. `link_devices()` links an unlinked topic when exactly one unit matches, by
   any of four rules: the unit's current name, the device's own discovery MAC,
   the full MAC a 12-hex topic spells, or a name the unit holds a broker
   account for (`device_config_values.mqtt_user`, history rows included — the
   same list the Mosquitto export writes). Rules that name different units link
   nothing, and `/api/mqtt/unlinked` shows the candidates.
2. A unit's MAIN row is chosen by one ordering (`mqtt_monitor.presence_order`):
   online first, then the newest live message, then the programmed name. The
   device list, the device page and the bench check all use it. The device page
   lists the other topics under "Other names".
3. A retained message updates the state columns, never `last_seen_at`,
   `last_online_at` or `last_offline_at`. `persist_at` and `reported_mac_at`
   are written only while empty.
4. `tasmota_id` stays the programmed name and never follows the broker.

### Consequences

* Good, because the unlinked list holds only devices the platform cannot
  explain. Rehearsed on a copy of production: 30 -> 2, the two topics that are
  not ours. 17 units now own more than one topic.
* Good, because "last heard" on a row means a live message again, once the old
  values are gone.
* Bad, because `last_seen_at` values written before this change are still
  replay times, until someone resets them. The reset is a separate decision.
* Neutral, because a unit that owns only an old name (reflashed, never
  connected since) shows that old name as its main row, with a "not the
  programmed name" marker.

### Confirmation

`api/tests/fleet/test_presence_topics.py`: each link rule, a conflict, the
6-hex suffix that must not link, the main-row choice, the device list counting
a unit once, the bench warning, the MAC backfill that needs agreement, and the
retained flag. On production after the deploy: `GET /api/mqtt/status` reports 2
unlinked topics.

## Pros and Cons of the Options

### Link by evidence rules

* Good, because every link names its rule, and a conflict stays visible.
* Bad, because every reader of presence must pick one row. There are three.

### Link by hand, one row per unit

* Bad, because it cannot work: the unit already has its current row, so a
  second link breaks the one-row readers anyway.

### Clear the old retained topics

* Bad, because the platform never publishes (0033), and a device running its
  old config would publish the topic again.

### Let `tasmota_id` follow the broker

* Bad, because the broker would CHANGE a recorded fact, which 0033 forbids,
  and the name the bench wrote would be lost.

## More Information

* How the old names came about, and the IPv6 evidence that ties 26 of the 27
  to their chip: [mqtt-presence.md](../reference/mqtt-presence.md).
* The retained flag: MQTT 3.1.1 §3.3.1.3 — the broker sets RETAIN only on a
  message sent because of a new subscription. paho 2.1.0 on production exposes
  it as `msg.retain`.
