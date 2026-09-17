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

VERIFIED 2026-09-17 with the M4 attached and marking: `STATUS` answers `!` for
every poll while a job runs and `OK` when it ends, so wait_for_idle() measures
the real engraving time rather than assuming one. It stays true that an EMPTY
bench answers OK at once — that is the absent laser, not a finished job.

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
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

# The UDP client and its guards live in agent.py — the file that must stand
# alone on a bench with nothing installed. This is the command-line tool on top
# of it, so the protocol has one implementation.
from agent import (  # noqa: F401  (re-exported for anything importing mark)
    DEFAULT_PLACEHOLDERS,
    DialogBlocked,
    LightBurn,
    Log,
    MarkError,
)



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
