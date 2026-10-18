---
status: "accepted"
date: 2026-10-18
decision-makers: Mateusz Kowalik
---

# Let a procedure require that the broker heard the unit

## Context and Problem Statement

CE_Dongle_V3 deployment 1 version 6 proves MQTT only by the broker LOGIN: the
device's own `MqttCount` goes up. Nothing proves that a message the unit
publishes reaches the broker and comes back to the platform, which is what the
customer depends on (item 9 of
[ce-dongle-v3-bench-gaps.md](../ce-dongle-v3-bench-gaps.md)). The platform
already watches the broker: `device_presence.last_seen_at` moves on every live
message on a topic.

Decision [0033](0033-the-broker-observes-devices-it-never-commands.md) keeps
presence away from the bench's evidence, for one reason: "Merging the two would
let a network outage look like a hardware failure." A bench step that fails a
run when the broker heard nothing is that merge.

## Decision Drivers

* An end-to-end MQTT proof is wanted on the bench, and only the broker can give
  it.
* A run's check history is evidence that must not change afterwards. A missing
  message caused by the platform (the monitor off, a broker outage) must not be
  recorded as a fault of the unit without saying so.
* The platform never publishes to the broker (0033, rule 2), so it cannot ask
  the unit for a message. The device has to send one.

## Considered Options

* A procedure step, `broker_heard`, that fails the run when the broker monitor
  heard nothing from the unit in time
* The same step, recording its check but never failing the run
* No broker check on the bench

## Decision Outcome

Chosen option: "a procedure step that fails the run", because the author of a
procedure decides to require it, the rest of the platform is unaffected, and
the failure text names the platform as a possible cause. This narrows the
decision driver of 0033 quoted above: presence may decide a bench result, but
ONLY through this step, and only in a procedure that names it.

1. **`broker_heard` reads `device_presence.last_seen_at` for the unit's topic**
   (`{topic}` by default) and passes when the broker heard a LIVE message after
   the run's flash, or after the run started when it flashes nothing. With
   `fresh`, only a message after the step began counts. A retained replay never
   moves `last_seen_at` (decision
   [0056](0056-a-unit-owns-every-topic-it-was-given.md)), so it never passes the
   step.
2. **Its failure names the monitor**: the broker heard nothing in N seconds, when
   it last heard the topic, and that the monitor must be connected (Admin →
   Fleet broker). A reader of the run can tell "the platform was not listening"
   from "the unit did not speak" by that line and the monitor's own status.
3. **Nothing else reads presence to decide a result.** The bench check
   `online_elsewhere` stays a warning (decision
   [0037](0037-the-bench-says-what-it-already-knows.md)), and the device grid
   still never shows presence.
4. **The step publishes nothing.** It waits for what the device sends: put it
   after the step that brings MQTT up.

### Consequences

* Good, because a unit whose MQTT path is broken past the login fails on the
  bench, not at the customer.
* Good, because a procedure without the step behaves exactly as before.
* Bad, because a monitor outage during a run fails units that work. The failure
  text says so, and the unit must be tested again.
* Bad, because Tasmota sends telemetry every `TelePeriod` (300 s by default) and
  this firmware publishes a trimmed `STATE`, so the step relies on the messages
  a fresh MQTT connection sends. Which messages these builds send on connect has
  not been measured on a V3 unit.

### Confirmation

`tests/flasher/test_bench_gaps.py::test_the_broker_check_waits_for_a_live_message_after_the_flash`:
a presence row heard before the flash fails the step, a row heard after it
passes, and the time is recorded in the run's results. Not yet run on a bench:
that needs this change deployed and a procedure version with the step.

## Pros and Cons of the Options

### A step that fails the run

* Good, because the run's verdict carries the proof, so `checks.verdict` and the
  `produced` event need nothing new.
* Bad, because it lets a platform outage fail a unit, which is what 0033 warned
  about.

### A step that records its check and never fails the run

* Good, because a platform outage could never fail a unit.
* Bad, because a unit with a broken MQTT path would still read as programmed,
  and nobody looks at a grey or red cell on a unit that passed.

### No broker check

* Good, because 0033 stays as it is.
* Bad, because MQTT is proven only by the login, and item 9 stays open.

## More Information

The step is declared in the four places a new op needs (engine, validator,
`STEP_OPS`, `stepSchema.ts`); see `api/app/services/flasher/CLAUDE.md`. The
presence model is in [mqtt-presence.md](../reference/mqtt-presence.md).
Revisit this record if the monitor gets a health history that a run can be
checked against: then the step could tell an outage from a fault by itself.
