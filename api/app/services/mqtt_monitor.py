"""Watch the fleet's MQTT broker and keep `device_presence` current.

One long-lived subscriber, in a daemon thread, armed at startup when
`mqtt_monitor_enabled` is on. It answers three questions the platform could not
answer before: is this device online, when was it last online, and what is it
actually plugged into.

Read [docs/reference/mqtt-presence.md](../../../docs/reference/mqtt-presence.md)
before changing the topic list — the traffic budget is the whole design, and
the broker is a production system serving real customer inverters.

## The four rules this module exists to keep

1. **Subscribe to LEAVES, never to a subtree.** `tele/+/LWT` matches one topic
   per device. `tele/+/#` or `tele/#` matches METRICS, ADDONS and RESULT too,
   which on this broker is a Modbus poll every two seconds per device — about
   2500 messages/second across the fleet, for data we do not want. The `+`
   here is cheap precisely because a fixed leaf follows it. Every topic in
   `TOPICS` must name a leaf. See `_assert_leaf_topics`.

2. **Never publish.** This is a read-only observer, permanently. Publishing to
   `cmnd/…` sends a command to a customer's live inverter dongle, and the
   broker and the devices are Columbus's. There is no case to weigh: the
   client is constructed with no publish path, and nothing here should grow
   one. The MAC that a `cmnd/<id>/Status 5` would have fetched now arrives
   free and retained from `tasmota/discovery` — see the MAC section.

3. **Buffer, then flush.** ~5000 devices publishing SENSOR and STATE is tens of
   writes a second. Messages land in an in-memory dict keyed by topic and are
   flushed in one transaction every `flush_s`. The DB sees a handful of
   statements a minute instead of a sustained write load, and a burst of
   retained messages on reconnect collapses into a single upsert per device.

4. **Retained first.** `LWT` and `PERSIST_SAVE` are retained, so a fresh
   subscriber is handed the current state of every device on the broker within
   seconds of connecting, offline ones included. That is what makes a restart
   cheap and what makes this table disposable.

## What the broker actually carries

Confirmed by sniffing a live dongle (2026-09-18), NOT assumed from Tasmota's
defaults — these are custom builds and they publish a trimmed `STATE`:

| Topic | Retained | Payload |
|---|---|---|
| `tele/<id>/LWT` | yes | `Online` / `Offline`, bare string |
| `tele/<id>/PERSIST_SAVE` | yes | `{"persist":{"monitoring":{…},"dongle_setup":{…},"read_once":{…}}}` |
| `tele/<id>/SENSOR` | no | `{"Time":…,"ESP32":{"Temperature":56.7},"TempUnit":"C"}` |
| `tele/<id>/STATE` | no | `{"Time":…,"Wifi":{"Ping":150}}` — no MAC, no uptime, no version |
| `stat/<id>/STATUS5` | no | network status; only published when something ASKS a device |
| `tasmota/discovery/<MAC>/config` | **yes** | `{"mac","t","md","sw","ip",…}` — the full MAC, the device's topic, the hardware model |
| `tele/<id>/METRICS`, `ADDONS`, `RESULT`, `stat/<id>/RESULT` | no | live PV/Modbus data, high volume — NOT subscribed |

**The MAC comes from the retained discovery announcement** (user, 2026-09-18).
It is the good source: retained, so one arrives per device on connect and then
nothing, and it carries the full MAC ALONGSIDE the device's own topic (`t`), so
it resolves the 6-hex V2-era topics that can never yield a MAC by themselves.

Two weaker sources remain, in descending strength after it: `stat/<id>/STATUS5`
(`StatusNET.Mac` — the device answering somebody else's query), and the 12-hex
topic suffix (`dongle_D4E9F4F48380` -> `d4:e9:f4:f4:83:80`, via
`mac_from_topic`). A 6-hex topic carries only the last three bytes and is never
reported as a MAC.

None of it EVER overwrites a MAC that programming recorded — see the MAC
section further down.
"""
from __future__ import annotations

import json
import logging
import re
import ssl
import threading
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as M
from ..db import SessionLocal
from . import mqtt_config

log = logging.getLogger(__name__)

# Topic leaves this module subscribes to, and the parser for each. A `+` is
# only ever the device-id level, and a fixed leaf always follows it — see rule 1.
TOPICS: tuple[str, ...] = (
    "tele/+/LWT",
    "tele/+/PERSIST_SAVE",
    "tele/+/SENSOR",
    "tele/+/STATE",
    # A FALLBACK, and a free one. Tasmota publishes this only in answer to
    # somebody's `cmnd/<id>/Status 5` — never ours — so it carries no traffic
    # of its own and catches a MAC if another tool on the network asks a
    # device. `tasmota/discovery` below has supplied every MAC so far, so
    # expect this to stay empty; it costs nothing to leave in.
    "stat/+/STATUS5",
    # THE MAC, WITHOUT ASKING (user, 2026-09-18). Tasmota's discovery
    # announcement is RETAINED, so one arrives per device on connect and then
    # nothing — the same near-free shape as LWT. It is the only source that
    # resolves the 6-hex V2-era topics, because it carries the FULL MAC and the
    # device's own topic in one payload. It also carries the hardware model and
    # the Tasmota version. See `_parse_discovery`.
    "tasmota/discovery/+/config",
)

# "<tele|stat>/<id>/<LEAF>" — the id may not contain a slash, so this is exact.
_TOPIC_RE = re.compile(r"^(?:tele|stat)/([^/]+)/(LWT|PERSIST_SAVE|SENSOR|STATE|STATUS5)$")
# "tasmota/discovery/<MAC>/config". The MAC is in the topic AND the payload,
# but the payload is what says which device TOPIC it belongs to, so the topic
# segment is not parsed — see `_parse_discovery`.
_DISCOVERY_RE = re.compile(r"^tasmota/discovery/[^/]+/config$")

# A MAC is six colon-separated hex pairs and nothing else on these devices
# looks like one (an IP is a dotted quad). Matching the SHAPE rather than a
# field name is deliberate: this parser must not depend on a remembered
# Tasmota schema, and it keeps working if the key is renamed or moved.
_MAC_RE = re.compile(r"^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _find_mac(obj, path: str = "") -> tuple[str, str]:
    """Depth-first hunt for a MAC-shaped string. Returns (mac, where) or ("","").

    `where` is the dotted path it was found at, stored so the schema this
    actually saw is recorded rather than assumed.
    """
    if isinstance(obj, dict):
        for key, value in obj.items():
            found = _find_mac(value, f"{path}.{key}" if path else key)
            if found[0]:
                return found
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found = _find_mac(value, f"{path}[{i}]")
            if found[0]:
                return found
    elif isinstance(obj, str) and _MAC_RE.match(obj):
        return obj.lower(), path
    return "", ""

# State shown on the Setup page, and by `GET /api/flasher/mqtt/status`.
STATE: dict[str, Any] = {
    "enabled": False,
    "connected": False,
    "host": "",
    "started_at": None,
    "connected_at": None,
    "last_message_at": None,
    "last_flush_at": None,
    "messages": 0,
    "flushed": 0,
    "errors": 0,
    "last_error": "",
    "subscriptions": [],
}

_started = False
_lock = threading.Lock()
# topic -> partial update accumulated since the last flush.
_pending: dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _assert_leaf_topics(topics: tuple[str, ...]) -> None:
    """Rule 1, enforced rather than documented.

    A `#` anywhere, or a `+` that is not followed by a fixed leaf, would turn
    this observer into a firehose against a production broker. That is a bug
    worth refusing to start for, not one worth logging.
    """
    for t in topics:
        if "#" in t:
            raise ValueError(
                f"mqtt_monitor: refusing to subscribe to a subtree ({t!r}). "
                "Subscribe to explicit leaves — see rule 1 in this module."
            )
        leaf = t.rsplit("/", 1)[-1]
        # The leaf must be LITERAL. Anything else means the `+` is not the last
        # wildcard and the subscription can widen without anyone noticing.
        # (Tested for wildcards, not for letters: `PERSIST_SAVE` is a perfectly
        # good literal leaf and an `isalpha()` check rejects it.)
        if not leaf or "+" in leaf:
            raise ValueError(
                f"mqtt_monitor: {t!r} does not end in a fixed leaf. "
                "A '+' is only safe when a literal topic name follows it."
            )


def mac_from_topic(topic_id: str) -> str:
    """`dongle_D4E9F4F48380` -> `d4:e9:f4:f4:83:80`; anything else -> "".

    Only a full 12-hex suffix is a MAC. The 6-hex topics of the V2 era are the
    MAC's last three bytes and are deliberately NOT expanded into a fake one —
    half a MAC that looks like a whole one is worse than no MAC.

    LOWERCASE WITH COLONS, because that is what `device_units.mac` already
    holds (`20:e7:c8:92:b6:10`). Returning the upper-case spelling would make
    every backfilled row differ in case from every programmed one, and the
    mismatch check would then have to remember to fold case forever.
    """
    suffix = topic_id.rsplit("_", 1)[-1]
    if len(suffix) != 12 or not all(c in "0123456789abcdefABCDEF" for c in suffix):
        return ""
    s = suffix.lower()
    return ":".join(s[i:i + 2] for i in range(0, 12, 2))


def _parse_discovery(payload: bytes) -> tuple[str, dict]:
    """Tasmota's retained discovery announcement -> (device topic, update).

    Returns ("", {}) for anything it cannot place. The payload is keyed by the
    DEVICE'S OWN TOPIC (`t`), not by the MAC in the MQTT topic segment: every
    other row in this table is keyed by the device topic, and a second key
    would split one device across two rows.

    Real payload, captured 2026-09-18 — abbreviated keys are Tasmota's:

        {"mac":"08F9E09EF6D4", "t":"dongle_9EF6D4", "md":"CE_Dongle_v1",
         "sw":"13.3.0.2", "hn":"dongle-9EF6D4-5844", "ip":"10.10.12.24", …}

    This is the source that resolves the V2-era fleet: `t` is the 6-hex topic
    that can never yield a MAC on its own, and `mac` is the whole address.
    """
    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return "", {}
    if not isinstance(data, dict):
        return "", {}
    topic = data.get("t")
    if not isinstance(topic, str) or not topic:
        return "", {}

    now = _now()
    out: dict[str, Any] = {"last_seen_at": now}
    raw = data.get("mac")
    if isinstance(raw, str):
        hexonly = raw.replace(":", "").replace("-", "").strip()
        if len(hexonly) == 12 and all(c in "0123456789abcdefABCDEF" for c in hexonly):
            s = hexonly.lower()
            out["reported_mac"] = ":".join(s[i:i + 2] for i in range(0, 12, 2))
            out["reported_mac_field"] = "tasmota/discovery.mac"
            out["reported_mac_at"] = now
    if isinstance(data.get("md"), str):
        out["hw_model"] = data["md"][:60]
    if isinstance(data.get("sw"), str):
        out["tasmota_version"] = data["sw"][:40]
    if isinstance(data.get("ip"), str):
        out["ip_address"] = data["ip"][:45]
    return topic, out


def _parse(leaf: str, payload: bytes) -> dict:
    """One message -> the columns it updates. Never raises: the payload is the
    dongle firmware's, it changes without telling us, and a malformed one must
    cost a single skipped update rather than the subscriber."""
    now = _now()
    out: dict[str, Any] = {"last_seen_at": now}

    if leaf == "LWT":
        text = payload.decode("utf-8", "replace").strip()
        out["lwt"] = text[:20]
        if text.lower() == "online":
            out["online"] = True
            out["last_online_at"] = now
        elif text.lower() == "offline":
            out["online"] = False
            out["last_offline_at"] = now
        else:
            out["online"] = None
        return out

    try:
        data = json.loads(payload.decode("utf-8", "replace"))
    except (ValueError, UnicodeDecodeError):
        return out
    if not isinstance(data, dict):
        return out

    if leaf == "STATUS5":
        mac, where = _find_mac(data)
        if mac:
            out["reported_mac"] = mac
            out["reported_mac_field"] = where[:120]
            out["reported_mac_at"] = now
    elif leaf == "SENSOR":
        esp = data.get("ESP32")
        if isinstance(esp, dict) and isinstance(esp.get("Temperature"), (int, float)):
            out["temperature_c"] = float(esp["Temperature"])
            out["temperature_at"] = now
    elif leaf == "STATE":
        wifi = data.get("Wifi")
        if isinstance(wifi, dict) and isinstance(wifi.get("Ping"), (int, float)):
            out["wifi_ping_ms"] = int(wifi["Ping"])
    elif leaf == "PERSIST_SAVE":
        out["persist"] = data
        out["persist_at"] = now
        p = data.get("persist") if isinstance(data.get("persist"), dict) else {}
        mon = p.get("monitoring") if isinstance(p.get("monitoring"), dict) else {}
        setup = p.get("dongle_setup") if isinstance(p.get("dongle_setup"), dict) else {}
        if isinstance(mon.get("inverter"), str):
            out["inverter"] = mon["inverter"][:60]
        if isinstance(mon.get("inverter_sn"), (str, int)):
            out["inverter_sn"] = str(mon["inverter_sn"])[:60]
        # Firmware version. `dongle_version` is authoritative, but on older
        # builds it carries the FAMILY ("1.3.x") while the exact build sits in
        # `dongle_version_hardcoded`; on newer ones it is the exact build
        # ("1.4.0") and the hardcoded one is the family. So prefer whichever is
        # specific, and keep the family if that is genuinely all there is.
        #
        # `json_version` is deliberately NOT a fallback: it versions the
        # payload SCHEMA ("2.0.24"), not the firmware, and showing it in a
        # firmware column would be a confident lie.
        candidates = [setup.get(k) for k in ("dongle_version", "dongle_version_hardcoded")]
        exact = [v for v in candidates
                 if isinstance(v, str) and v and not v.endswith(".x")]
        family = [v for v in candidates if isinstance(v, str) and v]
        if exact:
            out["dongle_version"] = exact[0][:40]
        elif family:
            out["dongle_version"] = family[0][:40]
    return out


# ------------------------------------------------------------------- flushing
def _flush(db: Session) -> int:
    """Write the buffer out in one transaction. Returns rows touched."""
    with _lock:
        if not _pending:
            return 0
        batch = dict(_pending)
        _pending.clear()

    topics = list(batch)
    rows = {
        r.topic: r
        for r in db.scalars(
            select(M.DevicePresence).where(M.DevicePresence.topic.in_(topics))
        )
    }
    # One lookup for the devices these topics belong to, rather than one per
    # row. An unmatched topic keeps device_unit_id NULL — that is the discovery
    # signal, not an error.
    unknown = [t for t in topics if t not in rows]
    linked: dict[str, int] = {}
    if unknown:
        linked = {
            d.tasmota_id: d.id
            for d in db.scalars(
                select(M.DeviceUnit).where(M.DeviceUnit.tasmota_id.in_(unknown))
            )
        }

    now = _now()
    for topic, update in batch.items():
        row = rows.get(topic)
        if row is None:
            row = M.DevicePresence(topic=topic, first_seen_at=now,
                                   device_unit_id=linked.get(topic))
            db.add(row)
        for key, value in update.items():
            setattr(row, key, value)
        row.updated_at = now
    db.commit()
    STATE["flushed"] += len(batch)
    STATE["last_flush_at"] = now.isoformat()
    return len(batch)


def link_devices(db: Session) -> int:
    """Attach presence rows to device units that appeared after the row did.

    Cheap and idempotent; run on startup and after any device import. This is
    the other half of keying on the topic: a device discovered on the broker
    first and imported into the platform later keeps the history it already
    accumulated.
    """
    orphans = list(db.scalars(
        select(M.DevicePresence).where(M.DevicePresence.device_unit_id.is_(None))
    ))
    if not orphans:
        return 0
    by_topic = {
        d.tasmota_id: d.id
        for d in db.scalars(
            select(M.DeviceUnit).where(
                M.DeviceUnit.tasmota_id.in_([o.topic for o in orphans])
            )
        )
    }
    n = 0
    for row in orphans:
        if row.topic in by_topic:
            row.device_unit_id = by_topic[row.topic]
            n += 1
    if n:
        db.commit()
    return n


# ------------------------------------------------------------------- the MAC
# THE BROKER MAY FILL A MISSING MAC. IT MAY NEVER CHANGE ONE.
#
# The MAC recorded during programming is read off the chip by esptool, seconds
# into the run and before any firmware boots. That is the strongest identity
# evidence the platform ever gets, and the MQTT topic is not in the same class:
# a topic is a STRING the firmware was configured with, it can be copied onto a
# replacement board by a restored config backup, and it survives a re-flash
# that moved the device to different hardware.
#
# So the policy is exactly two rules (user decision 2026-09-18):
#
#   1. `mac` empty  -> fill it from the topic, if the topic carries a full one.
#      The V2-era devices were imported from reports that never held a MAC, so
#      this is the only way most of them will ever get one.
#   2. `mac` set and DIFFERENT -> never write. Report it to an admin.
#
# A mismatch is a real-world event worth a human look — a swapped board, a
# cloned config, a topic typed by hand — and silently trusting either side
# would destroy the evidence that the two disagree.

def broker_mac(presence: M.DevicePresence) -> tuple[str, str]:
    """The best MAC the broker offers for one device, and where it came from.

    The DEVICE'S OWN report wins over the topic. `stat/<id>/STATUS5` is the
    hardware answering a question; the topic is a configured string that a
    restored backup can carry onto different hardware. Returns ("", "") when
    the broker offers nothing usable.
    """
    if presence.reported_mac:
        return presence.reported_mac.lower(), "device_report"
    topic_mac = mac_from_topic(presence.topic)
    return (topic_mac, "mqtt_topic") if topic_mac else ("", "")


def mac_mismatches(db: Session) -> list[dict]:
    """Devices whose programmed MAC disagrees with what the broker says.

    Never repaired automatically. This is the admin's queue, not a migration —
    see the policy note above.
    """
    rows = db.execute(
        select(M.DevicePresence, M.DeviceUnit)
        .join(M.DeviceUnit, M.DevicePresence.device_unit_id == M.DeviceUnit.id)
        .where(M.DeviceUnit.mac.isnot(None), M.DeviceUnit.mac != "")
    ).all()
    out = []
    for presence, device in rows:
        mac, source = broker_mac(presence)
        if mac and mac != (device.mac or "").lower():
            out.append({
                "device_id": device.id,
                "topic": presence.topic,
                "programmed_mac": device.mac,
                "broker_mac": mac,
                "source": source,
                "reported_mac_field": presence.reported_mac_field,
                "online": presence.online,
                "last_seen_at": (
                    presence.last_seen_at.isoformat() if presence.last_seen_at else None),
            })
    return out


def backfill_macs(db: Session, actor: str = "mqtt-monitor") -> int:
    """Fill a MISSING MAC from the topic. Never overwrites. Returns rows filled.

    Two guards beyond "is it empty":

      * the topic must carry a FULL 12-hex MAC (`mac_from_topic`), so a V2-era
        6-hex topic contributes nothing rather than half an address;
      * no OTHER device may already hold that MAC. `device_units` has a UNIQUE
        constraint on it, so a duplicate would raise and take the whole flush
        down with it — and a duplicate means two rows for one physical device,
        which is a merge a human has to decide, not a write to force through.
    """
    rows = db.execute(
        select(M.DevicePresence, M.DeviceUnit)
        .join(M.DeviceUnit, M.DevicePresence.device_unit_id == M.DeviceUnit.id)
        .where((M.DeviceUnit.mac.is_(None)) | (M.DeviceUnit.mac == ""))
    ).all()
    if not rows:
        return 0

    candidates: list[tuple[M.DeviceUnit, str, str]] = []
    for presence, device in rows:
        mac, source = broker_mac(presence)
        if mac:
            candidates.append((device, mac, source))
    if not candidates:
        return 0

    taken = {
        m.lower()
        for (m,) in db.execute(
            select(M.DeviceUnit.mac).where(
                M.DeviceUnit.mac.in_([m for _, m, _ in candidates]))
        )
        if m
    }

    filled = 0
    for device, mac, source in candidates:
        if mac in taken:
            log.warning(
                "mqtt_monitor: not filling device %s — MAC %s is already on another "
                "device", device.id, mac)
            continue
        device.mac = mac
        taken.add(mac)
        # Provenance, so nobody later mistakes a broker-derived MAC for one
        # esptool read off the chip. A plain audit row on purpose: identity
        # history proper is being built separately, and a second bespoke
        # history here would be one more thing to reconcile with it.
        db.add(M.AuditLog(
            actor=actor, action="mac_backfill", entity_type="device_unit",
            entity_id=str(device.id),
            details={"mac": mac, "source": source,
                     "note": "device had no MAC; filled from the MQTT broker"},
        ))
        filled += 1
    if filled:
        db.commit()
        log.info("mqtt_monitor: filled %d missing device MAC(s) from MQTT topics", filled)
    return filled


# ------------------------------------------------------------------ the thread
def _run(cfg: mqtt_config.MqttSettings) -> None:
    try:
        import paho.mqtt.client as mqtt
    except ImportError:  # pragma: no cover - the image always has it
        STATE["last_error"] = "paho-mqtt is not installed"
        log.warning("mqtt_monitor: paho-mqtt is not installed; monitor not started")
        return

    host, port = cfg.host, cfg.port
    STATE["host"] = f"{host}:{port}"
    STATE["started_at"] = _now().isoformat()

    def on_connect(client, userdata, flags, rc, properties=None):
        if rc == 0:
            STATE["connected"] = True
            STATE["connected_at"] = _now().isoformat()
            for topic in TOPICS:
                client.subscribe(topic, qos=0)
            STATE["subscriptions"] = list(TOPICS)
            log.info("mqtt_monitor: connected to %s, watching %s",
                     STATE["host"], ", ".join(TOPICS))
        else:
            STATE["connected"] = False
            STATE["last_error"] = f"connack rc={rc}"
            log.warning("mqtt_monitor: connection refused, rc=%s", rc)

    def on_disconnect(client, userdata, rc, properties=None, reason=None):
        STATE["connected"] = False
        log.warning("mqtt_monitor: disconnected (rc=%s); paho will retry", rc)

    def on_message(client, userdata, msg):
        try:
            if _DISCOVERY_RE.match(msg.topic):
                topic_id, update = _parse_discovery(msg.payload)
                if not topic_id:
                    return
            else:
                m = _TOPIC_RE.match(msg.topic)
                if m is None:
                    return
                topic_id = m.group(1)
                update = _parse(m.group(2), msg.payload)
        except Exception:  # noqa: BLE001 — a bad payload never kills the loop
            STATE["errors"] += 1
            return
        with _lock:
            _pending.setdefault(topic_id, {}).update(update)
        STATE["messages"] += 1
        STATE["last_message_at"] = update["last_seen_at"].isoformat()

    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION1,
        client_id=f"{cfg.client_id}-{int(time.time())}",
        clean_session=True,
    )
    if cfg.username:
        client.username_pw_set(cfg.username, cfg.password)
    if cfg.tls:
        # The broker's Let's Encrypt certificate is allowed to be expired: the
        # dongles pin a fingerprint (`MqttFingerprint1/2`) and validate no
        # chain, so nobody renews it on our account. We are an observer on a
        # host we already trust by name, and refusing to connect would make the
        # platform blind every ninety days. Verification is off DELIBERATELY —
        # see docs/reference/mqtt-presence.md.
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    # Paho's own reconnect backoff; the loop below never has to re-dial.
    client.reconnect_delay_set(min_delay=5, max_delay=300)

    try:
        client.connect(host, port, keepalive=cfg.keepalive_s)
    except Exception as e:  # noqa: BLE001
        STATE["errors"] += 1
        STATE["last_error"] = f"{type(e).__name__}: {e}"
        log.warning("mqtt_monitor: first connect failed (%s); retrying in background", e)
        client.loop_start()
    else:
        client.loop_start()

    flush_s = max(5, cfg.flush_s)
    # Linking and MAC backfill run on a SLOW cadence, not every flush: both
    # scan presence rows joined to devices, and neither changes on the
    # timescale a flush runs at. Devices trickle in as the broker mentions
    # them, so this has to repeat — it cannot be a startup-only pass.
    every = max(1, 300 // flush_s)
    tick = 0
    while True:
        time.sleep(flush_s)
        tick += 1
        try:
            db = SessionLocal()
            try:
                _flush(db)
                if tick % every == 0:
                    link_devices(db)
                    backfill_macs(db)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001 — a bad flush never kills the thread
            STATE["errors"] += 1
            STATE["last_error"] = f"{type(e).__name__}: {e}"
            log.warning("mqtt_monitor: flush failed: %s", e)


def start(db: Session | None = None) -> bool:
    """Arm the subscriber from the stored admin configuration.

    Idempotent; returns True only if it started here. The credential is read
    ONCE, here, and handed to the thread — it is never read again from a
    request path and never reaches a log line.
    """
    global _started
    if _started:
        return False

    own_session = db is None
    db = db or SessionLocal()
    try:
        cfg = mqtt_config.load(db)
    finally:
        if own_session:
            db.close()

    if not cfg.usable:
        log.info("mqtt_monitor: not configured or disabled; monitor not started")
        return False
    _assert_leaf_topics(TOPICS)
    _started = True
    STATE["enabled"] = True
    threading.Thread(target=_run, args=(cfg,), name="mqtt-monitor", daemon=True).start()
    return True
