# Device presence from the fleet MQTT broker

What the platform knows about a device after it leaves the bench: is it online,
when was it last heard, how warm is it, and what inverter is it plugged into.
One read-only subscriber keeps `device_presence` current —
`api/app/services/mqtt_monitor.py`. The decisions behind it are
[0033](../decisions/0033-the-broker-observes-devices-it-never-commands.md).

## What the broker carries

Confirmed by sniffing live dongles on 2026-09-18, NOT taken from Tasmota's
defaults — these are custom builds and they publish a **trimmed `STATE`** with
no MAC, no uptime and no firmware version in it.

| Topic | Retained | Payload | Subscribed |
|---|---|---|---|
| `tele/<id>/LWT` | yes | `Online` / `Offline`, a bare string | yes |
| `tele/<id>/PERSIST_SAVE` | yes | the device's own config: inverter model and serial, smart meter, dongle type and version | yes |
| `tele/<id>/SENSOR` | no | `{"ESP32":{"Temperature":56.7},"TempUnit":"C"}` | yes |
| `tele/<id>/STATE` | no | `{"Time":…,"Wifi":{"Ping":150}}` — nothing else | yes |
| `stat/<id>/STATUS5` | no | network status, and the only place the **MAC** appears | yes |
| `tele/<id>/METRICS` | no | live PV and grid values, every few seconds | **no** |
| `tele/<id>/ADDONS` | no | derived battery/grid values | **no** |
| `tele/<id>/RESULT`, `stat/<id>/RESULT` | no | a Modbus exchange roughly every 2 s per device | **no** |

**The two retained topics are why this design is cheap.** A fresh subscriber is
handed the current `LWT` and `PERSIST_SAVE` of every device on the broker within
seconds of connecting, offline ones included, and then hears from them only when
something changes. That is what makes `device_presence` disposable: truncate it,
restart, and the retained half rebuilds itself.

## The traffic budget is the whole design

`tele/+/LWT` looks like a wildcard and is not the dangerous kind. The `+` is the
device-id level and a **fixed leaf follows it**, so it matches exactly one topic
per device. `tele/#` matches `RESULT` as well, which across ~4,000 devices is
roughly 2,500 messages a second of Modbus chatter nobody asked for.

`mqtt_monitor._assert_leaf_topics` refuses to start if a topic contains `#` or
ends in a `+`. It is a guard, not a comment, because this is the mistake that
would hurt somebody else's production system rather than ours.

Measured on the running fleet, 2026-09-18:

| | |
|---|---|
| Devices on the broker | 3,970 (2,672 online) |
| Messages | ~140 / second |
| Rows written | ~1 per device per flush, not 1 per message |

Nearly all of that rate is `SENSOR` and `STATE`, which are not retained.
Dropping those two topics would leave presence working on almost no traffic at
all, at the cost of the ESP32 temperature and the WiFi ping.

**Buffering, not throttling.** Messages land in an in-memory dict keyed by topic
and flush in one transaction every `flush_s` (default 15 s, minimum 5). Postgres
sees a few statements a minute instead of a sustained write load, and a
reconnect's retained burst collapses into a single upsert per device.

## The rule that is easy to get wrong

**Presence has three states, never two.**

| | Means |
|---|---|
| `online: true` | the broker says the device is connected |
| `online: false` | the broker says it is gone |
| no presence row at all | the platform has never heard of it |

A device with no row was probably never deployed, or the watcher is off.
Collapsing that into "offline" paints every shelf unit as a failure. The API
returns `presence: null` for it and the UI prints "never seen".

Presence is also a **different axis from the check grid**. The checks are what
the bench proved and they cannot change; presence is a live cache that is
allowed to be stale, wrong or missing. A device that is offline is a device the
broker has not heard from — not a claim that anything is broken.

## The MAC

**The broker may FILL a missing MAC. It may never CHANGE one** (user decision
2026-09-18). The MAC recorded during programming is read off the chip by esptool
seconds into the run, before any firmware boots. A topic is a string the firmware
was configured with, and a restored config backup carries it onto different
hardware. The two are not equal evidence.

There are three sources, in descending strength:

1. **`stat/<id>/STATUS5` → `StatusNET.Mac`** — the device itself answering.
   Confirmed live on 2026-09-18 (`dongle_846FA0` → `fc:e8:c0:84:6f:a0`, whose
   last three bytes match its own topic suffix).
2. **The topic suffix**, when it is a full 12 hex characters:
   `dongle_D4E9F4F48380` → `d4:e9:f4:f4:83:80`. The 6-hex V2-era topics are the
   last three bytes only and are deliberately **not** expanded — half a MAC that
   looks like a whole one is worse than none.
3. Nothing. Most devices, most of the time.

`backfill_macs` fills only an empty MAC, only when no other device already holds
that address (`device_units` has a UNIQUE constraint, and a duplicate means two
rows for one physical device — a merge a human decides). Every fill writes an
`AuditLog` row with `action="mac_backfill"` and its source, so a broker-derived
MAC is never mistaken later for one esptool read.

A disagreement goes to `GET /api/mqtt/mac-mismatches` and is shown on the device
page and the Admin card. Nothing is repaired automatically: a mismatch usually
means a swapped board or a cloned configuration, and picking a side would
destroy the evidence that the two disagree.

**The platform never sends `cmnd/<id>/Status 5`, and never will** (user,
2026-09-18). It is not a pending question or a deferred option — polling a
customer's dongle for our own bookkeeping is simply not something this platform
does. The `stat/+/STATUS5` subscription stays because it is free and passive: it
catches a MAC if some OTHER tool on the network queries a device.

Nothing is lost by it. `tasmota/discovery` is retained and has supplied every
MAC the platform holds (3,869 of 3,971 topics); `STATUS5` has supplied none.

## Where it lives

| | |
|---|---|
| `api/app/services/mqtt_monitor.py` | the subscriber, the parsers, the MAC policy |
| `api/app/services/mqtt_config.py` | the one encrypted config row |
| `api/app/routers/mqtt.py` | `/api/mqtt/*` — **admin only, every route** |
| `models.DevicePresence` | one row per TOPIC, `device_unit_id` nullable |
| `models.MqttConfig` | one row, id 1, password Fernet-encrypted |

**`device_presence` is keyed by topic, not by device.** The broker carries
devices this platform never programmed — field replacements, hand-provisioned
units, anything older than the flasher. Keying on the topic means an
unrecognised device still gets a row and appears in `GET /api/mqtt/unlinked`,
which is the point of watching a fleet you do not fully own. 68 such devices
were found on the first run. `link_devices()` resolves the pointer when a
matching `DeviceUnit.tasmota_id` appears later, so a device imported afterwards
adopts the history it already accumulated.

## Configuration

Admin only, on **Admin → Fleet broker**. **Not an environment variable and not
a Configuration knob** — the stored credential reads every customer device on the broker, which
is a different class of secret from the render theme. It is Fernet-encrypted
(`services/crypto.py`), and no endpoint returns it: `GET /api/mqtt/config`
reports `password_set` and nothing more.

The watcher reads the credential **once, at startup**, so a change needs an API
restart and never touches a request path.

Two traps worth knowing:

- **The broker certificate is not verified, on purpose.** The dongles pin a
  fingerprint (`MqttFingerprint1/2`) and validate no chain, so nobody renews it
  — it was already expired when this was built (Let's Encrypt, lapsed
  2026-09-11). Verification is off deliberately; do not "fix" it. Same root
  cause as [0025](../decisions/0025-a-device-fetches-from-its-own-address.md).
- **The client id gets a per-process suffix.** A client id that collided with a
  real device's would disconnect that device — MQTT brokers evict the older
  session on a duplicate id.
