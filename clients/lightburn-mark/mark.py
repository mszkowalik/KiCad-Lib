#!/usr/bin/env python3
"""Laser-marking driver for LightBurn — the reusable core of the platform's
`mark_laser` scenario step.

Replaces the marking half of CE_Production_flasher/lightburn.py. Same idea
(patch a serial into an .lbrn2 template, then drive LightBurn over UDP), but
with the failure modes that were measured against LightBurn 1.7.03 on
2026-07-26 actually handled:

  * `PING` answers `OK` only when no modal dialog is up. Silence means a human
    has to click something — the UDP interface is frozen until then. This is the
    single most important guard: probe before AND after every command.
  * `LOADFILE:` with a path that does not exist gets **no reply at all** and
    raises a modal "file could not be found" dialog, which freezes the interface.
    So the file is verified on disk before the command is ever sent.
  * `STATUS` answered `OK` with **no laser connected**, so it means "not busy",
    NOT "laser present and ready". Do not use it as a device check.
  * `START` answered `OK` with no laser connected: it confirms the command was
    accepted, never that a job ran or finished correctly.
  * `LASER:<name>` returned `!` on 1.7.03 — that command needs LightBurn 2.0+.
  * Replies come back to UDP port 19841 on the sender's address, from
    LightBurn's port 19840, over whichever IP stack the request used. The
    listener binds the wildcard address, so a remote host on the LAN can drive
    it (verified against 192.168.200.46, not just loopback).

NOT YET VERIFIED (no laser was connected): that `STATUS` reports `!` while a job
is actually running. The wait_for_idle() loop below assumes it does — that is
the documented behaviour ("`!` if busy") and it is the only completion signal
the interface offers. Confirm it with the laser attached before trusting a run
result, and see the note in wait_for_idle().

Usage:
    python3 mark.py --serial 588C812F7474 \
        --template ~/Projects/CE_Production_flasher/files/AQUA_DONGLE_Side_Info.lbrn2 \
        --out-dir ~/marking --host 127.0.0.1 --json

    python3 mark.py --ping                 # health check only
    python3 mark.py --serial X --template T --out-dir D --no-start   # load, don't fire
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

OUT_PORT = 19840  # LightBurn listens here
IN_PORT = 19841  # LightBurn replies here
OK, FAIL, UNKNOWN_CMD = "OK", "!", "?"

# Placeholder strings used in the CE templates. The first match wins.
DEFAULT_PLACEHOLDERS = ("123456", "123456789011")


class MarkError(RuntimeError):
    pass


class DialogBlocked(MarkError):
    """LightBurn is showing a modal dialog: nothing works until it is dismissed."""


@dataclass
class Log:
    entries: list[dict] = field(default_factory=list)

    def add(self, direction: str, text: str) -> None:
        self.entries.append({"ts": time.time(), "dir": direction, "text": text})
        print(f"  {'>>' if direction == 'tx' else '<<' if direction == 'rx' else '..'} {text}", file=sys.stderr)


class LightBurn:
    """Thin, synchronous client for LightBurn's UDP control interface."""

    def __init__(self, host: str = "127.0.0.1", timeout: float = 3.0, log: Log | None = None):
        self.host = host
        self.timeout = timeout
        self.log = log or Log()
        # Dual-stack socket bound to the documented reply port: LightBurn's
        # listener is IPv6-wildcard, so replies can arrive as IPv6 or as
        # IPv4-mapped depending on how we addressed it.
        self.sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("::", IN_PORT))

    def close(self) -> None:
        self.sock.close()

    def send(self, command: str, timeout: float | None = None) -> str | None:
        """Send one command, return the reply ('OK' / '!' / '?') or None on silence."""
        self.log.add("tx", command)
        self.sock.sendto(command.encode(), (self.host, OUT_PORT))
        self.sock.settimeout(timeout or self.timeout)
        try:
            data, _ = self.sock.recvfrom(2048)
        except socket.timeout:
            self.log.add("rx", "(no reply)")
            return None
        reply = data.decode(errors="replace").strip()
        self.log.add("rx", reply)
        return reply

    # -- health -------------------------------------------------------------

    def ping(self) -> bool:
        return self.send("PING") == OK

    def require_responsive(self, when: str) -> None:
        if not self.ping():
            raise DialogBlocked(
                f"LightBurn is not answering PING {when}. It is almost certainly showing a "
                f"modal dialog (missing file, licence prompt, unsaved changes) — someone has "
                f"to dismiss it on the bench PC."
            )

    def busy(self) -> bool:
        """True when LightBurn reports it is not idle. NOTE: an OK here does NOT
        mean a laser is connected — measured OK with nothing attached."""
        return self.send("STATUS") != OK

    # -- job control --------------------------------------------------------

    def load(self, path: Path, force: bool = True) -> None:
        # Guard the freeze: never hand LightBurn a path it cannot open.
        if not path.is_file():
            raise MarkError(f"refusing to send LOADFILE for a missing file: {path}")
        verb = "FORCELOAD" if force else "LOADFILE"
        reply = self.send(f"{verb}:{path}", timeout=15)
        if reply is None:
            raise DialogBlocked(f"{verb} got no reply — LightBurn most likely opened an error dialog")
        if reply != OK:
            raise MarkError(f"{verb} failed with {reply!r}")
        # A load that "succeeded" can still have raised a dialog behind it.
        self.require_responsive("after loading the job")

    def start(self) -> None:
        reply = self.send("START", timeout=10)
        if reply != OK:
            raise MarkError(f"START failed with {reply!r} (laser off, no device selected, or a dialog is up)")

    def wait_for_idle(self, timeout: float = 300.0, poll: float = 1.0, settle: float = 2.0) -> float:
        """Poll STATUS until the job stops reporting busy.

        UNVERIFIED against a real laser (none was connected when this was
        written): with no device attached STATUS answers OK immediately, so this
        returns at once and proves nothing. With a laser, LightBurn is
        documented to answer '!' while running. Until that is confirmed on the
        bench, treat a completed mark as operator-confirmed, not machine-proven.
        """
        t0 = time.time()
        # Give the job a moment to actually start before believing "idle".
        time.sleep(settle)
        while time.time() - t0 < timeout:
            if not self.busy():
                return time.time() - t0
            time.sleep(poll)
        raise MarkError(f"job still busy after {timeout}s")


def patch_template(template: Path, out_dir: Path, serial: str, placeholders=DEFAULT_PLACEHOLDERS,
                   suffix: str = "") -> Path:
    """Write a copy of the template with the placeholder text replaced by `serial`.

    The filename is unique per call so a stale file can never be picked up (and
    so a browser download cannot collide into "name (1).lbrn2").
    """
    tree = ET.parse(template)
    root = tree.getroot()
    shape = None
    for placeholder in placeholders:
        shape = root.find(f'.//Shape[@Type="Text"][@Str="{placeholder}"]')
        if shape is not None:
            break
    if shape is None:
        raise MarkError(f"no placeholder text shape {placeholders} found in {template.name}")
    shape.set("Str", serial)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"{serial}{('-' + suffix) if suffix else ''}.lbrn2"
    dest = out_dir / name
    tree.write(dest, encoding="utf-8", xml_declaration=True)
    return dest


def mark(serial: str, template: Path, out_dir: Path, host: str = "127.0.0.1",
         start: bool = True, job_timeout: float = 300.0, suffix: str = "") -> dict:
    """Full marking cycle. Returns a report dict ready to store on a flash run."""
    log = Log()
    report: dict = {"serial": serial, "template": str(template), "host": host, "started_at": time.time()}
    lb = LightBurn(host=host, log=log)
    try:
        lb.require_responsive("before starting")
        path = patch_template(template, out_dir, serial, suffix=suffix)
        report["job_file"] = str(path)
        report["job_bytes"] = path.stat().st_size
        log.add("app", f"patched {template.name} -> {path.name} ({report['job_bytes']} B)")
        lb.load(path)
        if start:
            lb.start()
            report["job_seconds"] = lb.wait_for_idle(timeout=job_timeout)
            log.add("app", f"job reported idle after {report['job_seconds']:.1f}s")
        else:
            log.add("app", "loaded only (--no-start)")
        report["status"] = "pass"
    except MarkError as exc:
        report["status"] = "fail"
        report["error"] = str(exc)
        log.add("err", str(exc))
    finally:
        report["finished_at"] = time.time()
        report["log"] = log.entries
        lb.close()
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Mark a device serial with LightBurn.")
    ap.add_argument("--serial", help="serial / EUI to engrave (e.g. 588C812F7474)")
    ap.add_argument("--template", type=Path, help=".lbrn2 template containing the placeholder text")
    ap.add_argument("--out-dir", type=Path, default=Path("./marking"), help="where the patched job is written")
    ap.add_argument("--host", default="127.0.0.1", help="LightBurn host (LAN address works — verified)")
    ap.add_argument("--suffix", default="", help="extra filename suffix, e.g. the flash-run id")
    ap.add_argument("--no-start", action="store_true", help="load the job but do not fire the laser")
    ap.add_argument("--job-timeout", type=float, default=300.0)
    ap.add_argument("--ping", action="store_true", help="health-check LightBurn and exit")
    ap.add_argument("--json", action="store_true", help="print the report as JSON on stdout")
    args = ap.parse_args()

    if args.ping:
        lb = LightBurn(host=args.host)
        alive = lb.ping()
        busy = None if not alive else lb.busy()
        lb.close()
        print(json.dumps({"responsive": alive, "busy": busy}))
        return 0 if alive else 1

    if not args.serial or not args.template:
        ap.error("--serial and --template are required unless --ping is used")

    report = mark(args.serial, args.template.expanduser(), args.out_dir.expanduser(), host=args.host,
                  start=not args.no_start, job_timeout=args.job_timeout, suffix=args.suffix)
    if args.json:
        print(json.dumps(report, indent=2))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
