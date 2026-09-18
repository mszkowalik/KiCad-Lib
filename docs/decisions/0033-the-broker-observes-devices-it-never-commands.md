---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# Watch the fleet MQTT broker read-only, and never let it overwrite an identity

## Context and Problem Statement

The platform knew what it had BUILT and nothing about what those devices were
doing afterwards. A device page could say a unit passed its test in March and
was shipped in April, and had no answer to "is it alive now", "when was it last
online" or "what is it actually plugged into". All of that already exists on the
fleet's MQTT broker, which about 4,000 dongles talk to continuously.

Two things make connecting to it a decision rather than a task. It is a
**production broker carrying real customer inverters**, so a careless subscriber
is a load on somebody else's working system. And the credential that reads it
reads **every customer device**, which is a different class of secret from the
render theme.

The topic map and the traffic measurements are in
[mqtt-presence.md](../reference/mqtt-presence.md); this record holds the
decisions, not the detail.

## Decision Drivers

* The broker is production infrastructure for customers, not our test rig.
* One credential reads the whole fleet — leaking it is not a local problem.
* Presence is a live cache; the bench's check history is evidence. Merging the
  two would let a network outage look like a hardware failure.
* The MAC read off the chip by esptool is the platform's strongest identity
  evidence, and an MQTT topic is not in the same class.

## Considered Options

* Subscribe to a subtree (`tele/#`) and filter in the client
* Subscribe to explicit LEAF topics only
* Poll each device with `cmnd/<id>/Status` on a schedule
* Read the MAC from the retained `tasmota/discovery` announcement
* Keep the credential in the environment, like every other service credential
* Keep the credential in `app_settings`, editable on the Setup page
* Store the credential encrypted in its own admin-only table

## Decision Outcome

Chosen: **leaf-topic subscriptions, no publishing at all, and an admin-only
encrypted credential.** Four rules, each enforced rather than documented:

1. **Subscribe to leaves, never to a subtree.** `tele/+/LWT` is one topic per
   device; `tele/#` also matches a Modbus poll every two seconds per device —
   roughly 2,500 messages/second across the fleet, for data we do not want.
   `mqtt_monitor._assert_leaf_topics` refuses to start on a `#`, so this cannot
   regress quietly.
2. **Never publish.** The watcher is an observer. `cmnd/…` sends a command to a
   customer's inverter dongle, and the platform has no business doing that on a
   timer.
3. **Buffer, then flush.** Messages accumulate in memory keyed by topic and are
   written in one transaction every 15 s, so a burst of retained messages on
   reconnect collapses into one upsert per device.
4. **The broker may FILL a missing MAC. It may never CHANGE one.** A
   disagreement is reported to an admin and left alone.

### Consequences

* Good, because a restart is cheap and self-healing: `LWT` and `PERSIST_SAVE`
  are retained, so a fresh subscriber is handed the current state of every
  device — offline ones included — within seconds.
* Good, because `device_presence` is derived and disposable. Truncate it and a
  reconnect rebuilds the retained half.
* Good, because the discovery is real: 68 devices are live on the broker that
  the platform has no record of, and a `stat/+/STATUS5` subscription costs
  nothing while capturing a device's own MAC whenever anything else asks it.
* Bad, because temperature and WiFi ping are NOT retained, so those two topics
  carry ongoing traffic — measured at ~140 messages/second for the fleet. They
  are in because the ESP32 temperature was wanted; dropping `tele/+/SENSOR` and
  `tele/+/STATE` would cut nearly all of it.
* Good, because the MAC needs no poll after all. `tasmota/discovery/<mac>/config`
  is RETAINED and carries the full MAC beside the device's own topic, so it
  resolves even the 6-hex V2-era topics that encode only three bytes. It filled
  2,281 device records, agreed with 1,537 MACs the flasher had recorded and
  disagreed with none — an independent confirmation of both sources.
* Bad, because the credential now has two homes to keep in step conceptually —
  `device_config_values` (per device, the flasher's) and `mqtt_config` (the
  platform's own copy).

### Confirmation

Against the running platform, 2026-09-18: the watcher connected to
`don.columbusenergy.cloud:8883`, discovered 3,971 topics with ~2,670 online and
0 errors, and `GET /api/mqtt/status` reported its six subscriptions.

**Access.** A non-admin session received 403 on every `/api/mqtt/*` route and an
unauthenticated one 401, verified including the `PUT` that would change the
host. `secrets_enc` was confirmed to be ciphertext with the cleartext password
absent from the row, and no endpoint returns it.

**The MAC policy** was exercised on synthetic rows first: an empty MAC was
filled, a differing one was left untouched and reported, and a 6-hex topic
yielded nothing through `mac_from_topic`. Then on the real fleet — 2,281 empty
MACs filled from `tasmota/discovery`, 1,537 agreements with MACs the flasher had
recorded, **0 disagreements**. The 6-hex V2-era topics are resolved by discovery
even though the topic string alone cannot yield an address.

**Cost**, measured in-process: 1.6 us to parse a message and 0.06 ms to write a
row, so the steady state is about 0.4% of one core. A container with the watcher
running measured LOWER than the same container with it disabled — the difference
is below the noise of the dev image's own file-watching.

## Pros and Cons of the Options

### Subscribe to a subtree and filter client-side

* Good, because one subscription covers everything, including topics added later.
* Bad, because the filtering happens AFTER the broker has already sent it. The
  cost lands on the production broker and the network, not on us.

### Poll each device with `cmnd/<id>/Status`

* Good, because it reads the MAC and the firmware version on demand.
* Bad, because it writes to customer hardware for our own bookkeeping.
  **Rejected permanently** (user, 2026-09-18) — not deferred, and not kept as a
  manual escape hatch. The retained discovery topic supplies the same MAC for
  nothing, so the option buys no capability either.

### Read the MAC from the retained discovery announcement (chosen)

* Good, because it is retained: one message per device on connect, then silence.
  The same near-free shape as `LWT`, and no command is ever sent.
* Good, because it carries the full MAC BESIDE the device's own topic, which is
  the only thing that resolves the 6-hex V2-era fleet, and the hardware model
  and Tasmota version come with it.
* Neutral, because it depends on Tasmota's discovery being enabled on the
  device. 3,869 of 3,971 topics carry one; the rest fall back to the weaker
  sources or stay unknown.

### Credential in the environment

* Good, because it matches every other service credential here.
* Bad, because a compose file, a `.env`, a shell history and a CI secret store
  are each readable by more people than should hold a key to the whole fleet.

### Credential in `app_settings` / the Setup page

* Good, because the knob system already exists and renders itself.
* Bad, because Setup-page knobs are visible to any signed-in user, and this one
  is not that kind of setting.

### Encrypted, admin-only table (chosen)

* Good, because it matches how `ParamSet` and `GitCredential` already treat a
  shared secret, and the password is never returned by any endpoint.
* Bad, because it is a third configuration mechanism in the platform.

## More Information

* [mqtt-presence.md](../reference/mqtt-presence.md) — the topic map, the traffic
  budget, and what each payload carries.
* [0025](0025-a-device-fetches-from-its-own-address.md) — why these devices
  validate no TLS chain, which is why the watcher does not verify the broker
  certificate either.
* Revisit if the fleet outgrows one subscriber, or if the broker gains a
  per-service credential so a device credential is no longer borrowed. **Not**
  for the MAC: publishing to a customer device is settled, and discovery has
  made the question moot anyway.
