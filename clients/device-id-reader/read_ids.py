#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyserial>=3.5", "esptool==4.8.1"]
# ///
"""Watch for Dongle V2 / Aqua V2 (CH340) and Dongle V3 (ESP32-C6) units and record each one's MAC and topic.

Plug a unit in. The script reads what it says, and writes the MAC (and the
Tasmota topic, when there is one) to a JSON file keyed by MAC. Unplug it, plug
the next. Several units can be plugged at once: each port gets its own reader.

    uv run clients/device-id-reader/read_ids.py                # ./devices.json
    uv run clients/device-id-reader/read_ids.py -o batch5.json

Two kinds of port, told apart by USB id (the same pairs as the bench agent's
BENCH_BRIDGES):

* CH340 `1A86:7523` — Dongle V2 and Aqua V2. Every unit answers the same id and
  no USB serial number (docs/reference/bench-serial-ports.md), so the MAC comes
  from the chip. The script pulses EN through RTS and reads the boot output at
  once, because the ROM prints before the port can be opened after a plug-in:
    1. `waiting for download` — BOOT is held: esptool reads the MAC with no
       reset of its own. Firmware is NOT checked.
    2. A Tasmota log line or a `Status 0` reply — MAC AND topic.
    3. Anything else (factory ESP-AT, empty flash, 3 s of silence) — esptool
       resets into the ROM. If DTR does not reach IO0 (some bare Aquas,
       measured 2026-10-02) it prints HOLD BOOT and retries for --boot-wait s.
* ESP32-C6 USB-Serial/JTAG `303A:1001` — Dongle V3. NO EN pulse: on this port a
  DTR/RTS move resets the chip and USB re-enumerates, while opening with both
  left asserted never resets it (measured, docs/flasher/design.md). The unit
  boots on plug-in anyway, so the script just asks `Status 0`. No Tasmota
  within 5 s → esptool, whose USB-JTAG reset reaches the ROM with no button.
  The USB serial number is the port's identity across those re-enumerations,
  stored as `usb_serial`. It equalled the MAC on all 11 V3 units read on
  2026-10-02, but the MAC is still taken from the chip, and a mismatch is
  printed.

What the board showed is stored as `firmware_seen`, with the line that proved
it in `boot_evidence` — the observation a later "unprogrammed" record rests on.

The fields read, and their shape, are the ones in the recorded bench output
(clients/flasher-poc/real_lines.json): `Status.Topic` = "dongle_F8B3B742DAF8",
`StatusNET.Mac` = "F8:B3:B7:42:DA:F8", log lines "00:00:00.349 WIF: ...". The
MAC is stored lowercase, the form the platform keeps on `DeviceUnit.mac`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import serial
from serial.tools import list_ports

PORTS = {                       # (vid, pid) -> kind
    (0x1A86, 0x7523): "ch340",      # Dongle V2, Aqua V2
    (0x303A, 0x1001): "usb-jtag",   # ESP32-C6 built-in USB-Serial/JTAG, Dongle V3
}
BAUD = 115200          # the Tasmota console and the ESP32 boot log, both
ASK_EVERY = 1.0        # re-ask `Status 0` until the firmware answers
QUIET = {"ch340": 3.0, "usb-jtag": 5.0}   # no Tasmota line by then: not Tasmota
COOLDOWN = 5.0         # a USB-JTAG unit re-enumerates after esptool resets it
SCAN_EVERY = 0.3

FIELDS = {             # JSON key -> dotted path in the merged Status 0 reply
    "mac": "StatusNET.Mac",
    "topic": "Status.Topic",
    "device_name": "Status.DeviceName",
    "hostname": "StatusNET.Hostname",
    "firmware": "StatusFWR.Version",
}

# Tasmota's log format, as recorded: "00:00:00.349 WIF: WifiManager active ...".
TASMOTA_LOG = re.compile(rb"^\d{2}:\d{2}:\d{2}\.\d{3} [A-Z]{2,4}: ")
# What each classification is stored as.
SEEN = {
    "download": "not checked (BOOT held)",
    "tasmota": "tasmota",
    "tasmota-silent": "tasmota, no Status 0 reply",
    "esp-at": "esp-at (factory)",
    "no-app": "none (no app in flash)",
    "unknown": "no recognised output",
}

print_lock = threading.Lock()


def say(text: str) -> None:
    with print_lock:
        print(f"{datetime.now():%H:%M:%S}  {text}", flush=True)


def dig(obj, path: str):
    """Case-insensitive dotted-path lookup, as `protocol.dig` on the platform."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        hit = next((k for k in cur if k.lower() == part.lower()), None)
        if hit is None:
            return None
        cur = cur[hit]
    return cur


def parse_line(raw: bytes):
    """The JSON object in one console line ("12:34:56 RSL: STATUS5 = {...}"), else None."""
    line = raw.decode("utf-8", "replace")
    brace = line.find("{")
    if brace < 0:
        return None
    try:
        obj = json.loads(line[brace:])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def classify(raw: bytes) -> str | None:
    """A boot-log line that settles what the board is running, else None.

    `at_customize` / `BLUFI` are from a bare Aqua on 2026-10-02 (ESP-AT 2.1.0).
    `invalid header: 0xffffffff` is the ROM's message for an erased flash —
    seen on 6 blank Dongle V3 (C6) units on 2026-10-02, not yet on a CH340
    board. A board that never prints it ends up as "no recognised output",
    which is read the same way.
    """
    if b"waiting for download" in raw or b"DOWNLOAD_BOOT" in raw:
        return "download"
    if b"at_customize" in raw or b"BLUFI" in raw:
        return "esp-at"
    if b"invalid header" in raw:
        return "no-app"
    return None


def probe(port: str, kind: str, baud: int, timeout: float) -> tuple[str, dict | None, str]:
    """Read the board's output and ask `Status 0`. -> (seen, rec, evidence).

    Tasmota 14 answers `Status 0` in one line per section (STATUS, STATUS1 …
    STATUS11); a newer build may answer in one STATUS0 line. Merging the
    top-level keys of every reply handles both. It returns as soon as the MAC
    and the topic are in, so `firmware` is often null: 5 of 6 Tasmota Aquas on
    2026-10-02 came back without STATUS2. Not investigated.
    """
    merged: dict = {}
    buf = b""
    last = ""
    tasmota = False
    with serial.Serial(port, baud, timeout=0.05) as ser:
        if kind == "ch340":
            # EN pulse with IO0 left high, the bench's Monitor.reset() without
            # its settings-flush delay (nothing was changed). A held BOOT button
            # wins over IO0 high, so the ROM comes up in download mode.
            ser.dtr = False
            ser.rts = True
            time.sleep(0.1)
            ser.reset_input_buffer()
            ser.rts = False
            first_ask = 1.0     # past the ROM's first lines, so a listening ROM gets no text
        else:
            first_ask = 0.5     # no reset here: the unit is already booting from the plug-in
        t0 = time.monotonic()
        next_ask = t0 + first_ask
        quiet = QUIET[kind]
        while time.monotonic() < t0 + (timeout if tasmota else min(timeout, quiet)):
            if time.monotonic() >= next_ask:
                ser.write(b"Status 0\n")
                next_ask = time.monotonic() + ASK_EVERY
            buf += ser.read(ser.in_waiting or 1)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                raw = raw.rstrip(b"\r")
                text = raw.decode("utf-8", "replace").strip()
                last = text or last
                seen = classify(raw)
                if seen:
                    return seen, None, text
                if TASMOTA_LOG.match(raw):
                    tasmota = True
                obj = parse_line(raw)
                if obj:
                    merged.update(obj)
            if dig(merged, FIELDS["mac"]) and dig(merged, FIELDS["topic"]):
                rec = {k: dig(merged, p) for k, p in FIELDS.items()}
                rec["mac"] = str(rec["mac"]).strip().lower()
                return "tasmota", rec, "Status 0 reply"
    return ("tasmota-silent" if tasmota else "unknown"), None, last


def read_rom(port: str, before: str = "default_reset", attempts: int = 3,
             timeout: float = 40.0) -> dict:
    """MAC from the ESP32 ROM bootloader, then a hard reset back out of it.

    `chip_id` is the bench agent's command, against the same esptool 4.8.1.
    `default_reset` needs DTR wired to IO0 on a CH340 board, which is not so on
    every bare Aqua (measured 2026-10-02). On the C6's USB-Serial/JTAG esptool
    picks its USB reset by itself (PID 0x1001, `loader.py`).

    THE C6 PRINTS TWO MACs. esptool's `read_mac` prints the EUI-64 as `MAC:`
    when the chip has one (8 bytes, the C6 does) and the 6-byte base MAC as
    `BASE MAC:` (`cmds.read_mac`, `targets/esp32c6.py`). The base MAC is the
    one Tasmota reports and the platform stores, so it wins.
    """
    cmd = [sys.executable, "-m", "esptool", "--chip", "auto", "--port", port,
           "--baud", "115200", "--before", before, "--after", "hard_reset",
           "--connect-attempts", str(attempts), "chip_id"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise TimeoutError(f"esptool did not finish within {timeout:.0f} s") from None
    text = out.stdout + out.stderr
    chip = mac = base = ""
    for line in text.splitlines():
        if line.startswith("Chip is "):
            chip = line[len("Chip is "):].strip()
        elif line.startswith("BASE MAC:"):
            base = line[len("BASE MAC:"):].strip()
        elif line.startswith("MAC:") and not mac:
            mac = line[4:].strip()
    mac = base or mac
    if not mac:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        why = next((l for l in lines if l.startswith("A fatal error occurred")),
                   lines[-1] if lines else "no output")
        raise RuntimeError(f"esptool read no MAC — {why}")
    return {"mac": mac.lower(), "topic": None, "chip": chip}


def pulse_enable(port: str) -> None:
    """EN low for 200 ms with IO0 left alone — the operator holds BOOT.

    The bench agent's `EspRun._pulse_enable`, line for line. RTS drives EN on
    the bare Aqua (measured 2026-10-02: this pulse rebooted it every time).
    CH340 boards only.
    """
    with serial.Serial(port, 115200, timeout=0.1) as s:
        s.dtr = False
        s.rts = True
        time.sleep(0.2)
        s.rts = False
        time.sleep(0.4)


def read_rom_boot_held(port: str, wait: float) -> dict:
    """The bench's third rung: keep trying while the operator holds BOOT.

    Retries rather than asks once, for the bench's reason: the operator is
    still reaching for the board when the first attempt runs.
    """
    say(f"HOLD BOOT on {port} — retrying for {wait:.0f} s\a")
    deadline = time.monotonic() + wait
    last = ""
    while time.monotonic() < deadline:
        try:
            pulse_enable(port)
            return read_rom(port, before="no_reset", attempts=1, timeout=15)
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            if "could not open port" in last:
                break                    # unplugged: holding BOOT will not help
        time.sleep(0.5)
    raise RuntimeError(f"BOOT was not held within {wait:.0f} s ({last})")


class Store:
    """The JSON file, keyed by MAC. Rewritten whole on every read, atomically."""

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data: dict = json.loads(path.read_text()) if path.exists() else {}

    def put(self, rec: dict, port: str) -> tuple[bool, str | None]:
        """Store one read. Returns (new unit?, the topic it had before if that changed)."""
        now = datetime.now().isoformat(timespec="seconds")
        with self.lock:
            old = self.data.get(rec["mac"])
            was = old.get("topic") if old else None
            if old and old.get("firmware_seen") and rec.get("firmware_seen") == SEEN["download"]:
                # BOOT held observes nothing: keep what an earlier read saw.
                rec = {k: v for k, v in rec.items() if k not in ("firmware_seen", "boot_evidence")}
            self.data[rec["mac"]] = {
                **(old or {}),     # a ROM read keeps the topic an earlier firmware read found
                **{k: v for k, v in rec.items() if v is not None or not old},
                "port": port,
                "first_seen": old["first_seen"] if old else now,
                "last_seen": now,
                "reads": (old.get("reads", 0) if old else 0) + 1,
            }
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self.data, indent=2) + "\n")
            os.replace(tmp, self.path)
            return old is None, (was if was and rec["topic"] and was != rec["topic"] else None)

    def __len__(self) -> int:
        with self.lock:
            return len(self.data)


@dataclass
class Port:
    node: str
    kind: str                  # "ch340" | "usb-jtag"
    usb_serial: str = ""
    busy: bool = True
    done_at: float = 0.0


def read_unit(p: Port, baud: int, fw_timeout: float, boot_wait: float) -> dict | None:
    """Everything one unit needs, in order. Returns the record, or None after a FAIL line."""
    port = p.node
    rec = None
    seen, evidence = "unknown", ""
    if fw_timeout > 0:
        try:
            seen, rec, evidence = probe(port, p.kind, baud, fw_timeout)
        except Exception as exc:  # noqa: BLE001 — unplugged or busy
            say(f"FAIL  {port}  {exc}")
            return None
        if rec is not None:
            rec["source"] = "firmware"
        else:
            say(f"      {port}  {SEEN[seen]} — reading the ROM")
    if rec is None and seen == "download":
        try:
            rec = read_rom(port, before="no_reset")
            rec["source"] = "rom, BOOT held at plug-in"
        except Exception as exc:  # noqa: BLE001 — BOOT let go in between: try the ladder
            say(f"      {port}  ROM read in download mode failed ({exc})")
    if rec is None:
        try:
            rec = read_rom(port)
            rec["source"] = "rom"
        except Exception as exc:  # noqa: BLE001
            # The BOOT rung toggles DTR/RTS, which on USB-JTAG is a reset, not
            # a pulse — and esptool's own USB reset needs no button anyway.
            if "could not open port" in str(exc) or boot_wait <= 0 or p.kind != "ch340":
                say(f"FAIL  {port}  {exc}")
                return None
            say(f"      {port}  auto-reset did not reach the ROM ({exc})")
    if rec is None:
        try:
            rec = read_rom_boot_held(port, boot_wait)
            rec["source"] = "rom, BOOT held"
        except Exception as exc:  # noqa: BLE001
            say(f"FAIL  {port}  {exc}")
            return None
    if fw_timeout > 0:
        rec["firmware_seen"] = SEEN[seen]
        rec["boot_evidence"] = evidence[:160]
    rec["bridge"] = p.kind
    if p.usb_serial:
        rec["usb_serial"] = p.usb_serial
    return rec


def worker(p: Port, store: Store, baud: int, fw_timeout: float, boot_wait: float) -> None:
    started = time.monotonic()
    try:
        rec = read_unit(p, baud, fw_timeout, boot_wait)
        if rec is None:
            return
        new, was = store.put(rec, p.node)
        took = time.monotonic() - started
        what = (f"{rec['topic']:<22}  {rec.get('firmware') or '?'}" if rec["topic"]
                else f"{rec.get('firmware_seen', 'firmware not checked'):<26}  {rec.get('chip') or '?'}")
        say(f"{'NEW ' if new else 'SEEN'}  {rec['mac']}  {what}  {p.node}  "
            f"{took:.1f}s  [{len(store)} in file]\a")
        if was:
            say(f"      topic CHANGED for {rec['mac']}: was {was}, now {rec['topic']}")
        hexes = re.sub(r"[^0-9a-f]", "", p.usb_serial.lower())
        if hexes and hexes != rec["mac"].replace(":", ""):
            say(f"      note: USB serial {p.usb_serial!r} is not the MAC {rec['mac']}")
    finally:
        p.busy = False
        p.done_at = time.monotonic()


def esp_ports() -> dict[str, Port]:
    """One entry per physical unit.

    Keyed by the USB serial number when there is one (the C6's survives the
    re-enumeration an esptool reset causes), else by USB location — a CH340
    has no serial number, and its location IS the socket (bench-serial-ports.md).
    """
    out: dict[str, Port] = {}
    for p in list_ports.comports():
        kind = PORTS.get((p.vid, p.pid))
        if kind:
            key = (f"sn:{p.serial_number}" if kind == "usb-jtag" and p.serial_number
                   else p.location or p.device)
            out.setdefault(key, Port(node=p.device, kind=kind, usb_serial=p.serial_number or ""))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("-o", "--out", type=Path, default=Path("devices.json"))
    ap.add_argument("--baud", type=int, default=BAUD)
    ap.add_argument("--fw-timeout", type=float, default=8.0,
                    help="seconds to wait for a Status 0 reply once Tasmota has printed a "
                         "line (default 8; 0 = skip the boot check, ROM only, MAC only)")
    ap.add_argument("--boot-wait", type=float, default=30.0,
                    help="CH340 only: seconds to wait for BOOT to be held when auto-reset "
                         "cannot reach the ROM (default 30; 0 = do not ask)")
    args = ap.parse_args()

    store = Store(args.out)
    ids = ", ".join(f"{v:04X}:{p:04X} ({k})" for (v, p), k in PORTS.items())
    say(f"watching for {ids} — writing {args.out.resolve()} "
        f"({len(store)} units already in it). Ctrl-C to stop.")
    seen: dict[str, Port] = {}         # units still plugged in, or still being read
    for p in esp_ports().values():
        say(f"      {p.node} was already plugged in — reading it too")
    try:
        while True:
            present = esp_ports()
            now = time.monotonic()
            for key in [k for k in seen if k not in present]:
                p = seen[key]
                # A unit that drops off USB mid-read (esptool resetting a C6) or
                # just after it (the hard reset at the end) is the SAME unit
                # coming back: reading it again would loop.
                if p.busy or (p.kind == "usb-jtag" and now - p.done_at < COOLDOWN):
                    continue
                say(f"      {seen.pop(key).node} unplugged")
            for key, p in present.items():
                if key not in seen:
                    seen[key] = p
                    threading.Thread(target=worker, daemon=True,
                                     args=(p, store, args.baud, args.fw_timeout,
                                           args.boot_wait)).start()
            time.sleep(SCAN_EVERY)
    except KeyboardInterrupt:
        say(f"stopped — {len(store)} units in {args.out}")
        sys.exit(0)


if __name__ == "__main__":
    main()
