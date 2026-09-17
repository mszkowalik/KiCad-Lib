#!/usr/bin/env python3
"""The 7Sigma bench agent: a local appliance for the jobs a browser cannot do.

WHY THIS EXISTS. LightBurn is controlled over UDP, and a browser cannot send a
datagram, and a printer is reached through CUPS, which is a program on this
machine rather than anything a page can address. Everything else the marking bench needs — reading the device's MAC
over Web Serial, fetching the template, patching the serial into it — the page
does itself. This process exists for exactly one reason: to turn an HTTP
request into `FORCELOAD` and `START`, and to report when the job is idle again.

WHY PLAIN HTTP AND NOT A WEBSOCKET, AND WHY ONE FILE. So that it runs anywhere
with NO INSTALL. Every import below is standard library and nothing is imported
from beside it, which means any Python 3 already on the machine can run this
one downloaded file — no pip, no virtualenv, no build step, nothing to keep in
step with a platform release. That is worth more than live framing: a mark is
one request and a poll for its log.

WHAT IT DELIBERATELY DOES NOT DO. It holds no platform token, makes no outbound
connection, and knows nothing about runs, devices or projects. It never reads
the artwork: the page sends the FINISHED `.lbrn2` and the agent only writes it
down and points LightBurn at it. A bench with an old agent still marks whatever
the platform decides to send it, and the agent has nothing worth stealing.

THE TWO GUARDS THAT MATTER.

  * It listens on 127.0.0.1 only. A laser is not a thing to expose to a LAN.
  * It CHECKS THE ORIGIN of every browser request. Chrome's Local Network
    Access prompt asks the operator once, and after that ANY page they visit
    could reach this port. The allow-list is what stops a random website
    starting the laser. A browser cannot forge `Origin`, so this is a real
    boundary. A request with NO Origin is allowed: it cannot have come from a
    page, and refusing it would only break curl.

Usage:
    python3 agent.py                       # serve for the deployed platform
    python3 agent.py --origin http://localhost:5173
    python3 agent.py --host-lightburn 192.168.200.46   # LightBurn on another box

The API, all on 127.0.0.1:19842:
    GET  /                      the status page — every fact and the log, as HTML
    GET  /hello                 what this is
    GET  /health                PING + STATUS, and whether the laser board is on USB
    GET  /serial-ports          the USB serial nodes, and who holds each
    GET  /lasers                the laser sources LightBurn is configured for
    POST /mark                  {name, lbrn2(base64), start, job_timeout} -> {job}
    GET  /printers              the print queues, and what each one reports
    POST /print                 {value, printer, size, dots, rotate, copies} -> {job}
    POST /esp                   {op: connect|erase|flash|reset, port, chip, baud, images, flash_config} -> {job}
    POST /monitor/open          {port, baud, signals} — the device console, held here
    GET  /monitor?since=<n>&wait=<s>  console lines after `n`; `wait` long-polls
    POST /monitor/write         {text}
    POST /monitor/reset         pulse EN for a normal boot
    POST /monitor/close
    GET  /job/<id>?since=<n>    lines since `n`, and the result once done
"""

from __future__ import annotations

import argparse
import base64
import collections
import glob
import json
import os
import plistlib
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# The LightBurn client lives HERE, not in mark.py, because this file is the one
# that has to stand alone: it is downloaded from the bench page and run on a
# machine with nothing but Python. `mark.py` is the command-line tool and
# imports it back, so there is still one implementation of the UDP protocol and
# of the dialog guards that were measured against a real LightBurn.
# ---------------------------------------------------------------------------

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
                f"LightBurn is not answering PING {when}. Either it is not running, or it is "
                f"showing a modal dialog (missing file, licence prompt, unsaved changes) — the "
                f"two look identical over UDP, and both need someone at the bench machine."
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

    def select(self, name: str) -> None:
        """Choose which LightBurn DEVICE PROFILE marks this job.

        A profile is NOT a laser source. On the AtomStack M4 (1064 nm IR + 450 nm
        diode) both sources hang off one board and one profile can fire either:
        the source is picked PER LAYER inside the artwork ("Use Laser 2"), and
        the profile only carries the galvo calibration for one of them — so the
        right profile is the one whose calibration matches the layer's source
        (measured 2026-09-17, docs/reference/laser-marking.md). `LASER:` needs
        LightBurn 2.0+ — it answered `!` on 1.7.03, which is why the old tool
        never used it — and it VALIDATES the name: a wrong one comes back `!`
        rather than being ignored (measured on 2.1.04, 2026-09-17).
        """
        reply = self.send(f"LASER:{name}", timeout=10)
        if reply is None:
            raise DialogBlocked(f"LASER:{name} got no reply — LightBurn may have opened a dialog")
        if reply != OK:
            raise MarkError(
                f"LightBurn will not switch to {name!r}. The name must match the device exactly "
                f"as LightBurn lists it, and that LightBurn must be 2.0 or newer."
            )
        self.log.add("app", f"laser source: {name}")

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


# ---------------------------------------------------------------------------
# The agent itself.
# ---------------------------------------------------------------------------

PORT = 19842
# What the agent has said, for the window to show. Bounded: a bench runs for
# weeks and nobody scrolls back further than the last job.
LOG_LINES: "collections.deque[str]" = collections.deque(maxlen=400)


# Launched from the app there is no terminal to print to, so a failure leaves no
# trace at all unless it is written down. macOS's own place for this.
LOG_PATH = (Path.home() / "Library" / "Logs" / "7Sigma Agent.log" if sys.platform == "darwin"
            else Path(tempfile.gettempdir()) / "7sigma-agent.log")


def say(text: str) -> None:
    """Report once, to all three faces of this program."""
    stamped = f"{time.strftime('%H:%M:%S')}  {text}"
    LOG_LINES.append(stamped)
    print(text, file=sys.stderr)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d')} {stamped}\n")
    except OSError:
        pass  # a log that cannot be written is not a reason to stop marking

# ---------------------------------------------------------------------------
# Labels. The second thing on this bench that a browser cannot reach.
#
# THE BARCODE AND THE PAGE ARE BUILT HERE, not in the browser, and that is the
# one place this differs from marking. The laser's artwork is a versioned
# `.lbrn2` the platform serves, so the page owns it and the agent never reads
# it. A label has no artwork: its geometry comes out of the PRINTER'S OWN PPD,
# which exists on this machine and nowhere else. Laying it out in the page
# would mean shipping the PPD's numbers to the browser and keeping two copies
# of them in step. So the page sends a value and a roll, and gets a job back.
#
# Measured on a LabelWriter 550 on 2026-09-17, and written down in
# docs/reference/label-printing.md:
#
#   * The page is rasterised to the PRINTABLE area, not the label. Content
#     outside it is scaled to fit and centred, which silently shrinks a barcode.
#   * A bar edge that lands on a whole printer dot rasterises with NO grey
#     pixels at all. 3 dots at 300 dpi is 0.254 mm, the standard minimum module.
#   * `job-impressions-completed` reaches 1 with nothing printed. It counts
#     pages sent. Only `job-state = completed` with no printer state reason
#     means a label came out.
# ---------------------------------------------------------------------------

# Code 128, values 0..106. Transcribed from the published table and checked row
# by row against its own widths column, then proved by a round trip through
# `decode` and by reading a rendered label back out of a CUPS raster.
CODE128 = [
    "11011001100", "11001101100", "11001100110", "10010011000", "10010001100",
    "10001001100", "10011001000", "10011000100", "10001100100", "11001001000",
    "11001000100", "11000100100", "10110011100", "10011011100", "10011001110",
    "10111001100", "10011101100", "10011100110", "11001110010", "11001011100",
    "11001001110", "11011100100", "11001110100", "11101101110", "11101001100",
    "11100101100", "11100100110", "11101100100", "11100110100", "11100110010",
    "11011011000", "11011000110", "11000110110", "10100011000", "10001011000",
    "10001000110", "10110001000", "10001101000", "10001100010", "11010001000",
    "11000101000", "11000100010", "10110111000", "10110001110", "10001101110",
    "10111011000", "10111000110", "10001110110", "11101110110", "11010001110",
    "11000101110", "11011101000", "11011100010", "11011101110", "11101011000",
    "11101000110", "11100010110", "11101101000", "11101100010", "11100011010",
    "11101111010", "11001000010", "11110001010", "10100110000", "10100001100",
    "10010110000", "10010000110", "10000101100", "10000100110", "10110010000",
    "10110000100", "10011010000", "10011000010", "10000110100", "10000110010",
    "11000010010", "11001010000", "11110111010", "11000010100", "10001111010",
    "10100111100", "10010111100", "10010011110", "10111100100", "10011110100",
    "10011110010", "11110100100", "11110010100", "11110010010", "11011011110",
    "11011110110", "11110110110", "10101111000", "10100011110", "10001011110",
    "10111101000", "10111100010", "11110101000", "11110100010", "10111011110",
    "10111101110", "11101011110", "11110101110", "11010000100", "11010010000",
    "11010011100", "11000111010",
]
START_B, STOP_13 = 104, "1100011101011"   # the stop symbol plus its final bar
QUIET = 10        # modules of clear space each side, as the standard requires
DPI = 300         # the LabelWriter 550's only resolution
PT = 72.0
PRINTER_ADVICE = {
    "com.dymo.slot-status-error": "there is no roll in it, the lid is open, or the "
                                  "labels are not DYMO Authentic",
    "media-empty-error": "the roll has run out",
    "media-jam": "a label is jammed",
    "cover-open": "the lid is open",
    "offline-report": "it is switched off or unplugged",
}
# How often the printer is asked what it is doing. Four times a second: the
# whole job is over in about two, so once a second lost half of it.
POLL_SECONDS = 0.25
# CUPS's own words for "the paper is moving". The percentage varies.
PRINTING_RE = re.compile(r"printing page", re.I)
DEFAULT_ROLL = "w72h154"     # 11352, 25 x 54 mm, the roll the bench runs
# Helvetica advance widths /1000, for centring the human-readable line. Only
# the characters a serial can hold: anything else falls back to a safe guess.
HELVETICA = {**{c: 556 for c in "0123456789"}, "-": 333, " ": 278, ".": 278,
             ":": 278, "_": 556, **dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", [
                 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556,
                 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667,
                 667, 611]))}


def code128(text: str) -> str:
    """The value as a string of modules: 1 is a bar, 0 is a space."""
    bad = [c for c in text if not 32 <= ord(c) <= 126]
    if bad:
        raise ValueError(f"a Code 128 label cannot carry {''.join(bad)!r}")
    values = [ord(c) - 32 for c in text]
    check = (START_B + sum((i + 1) * v for i, v in enumerate(values))) % 103
    return "".join(CODE128[v] for v in [START_B] + values + [check]) + STOP_13


def ppd_path(queue: str) -> Path:
    return Path("/etc/cups/ppd") / f"{queue}.ppd"


def rolls(queue: str) -> list:
    """Every page size the queue's own PPD offers, with its printable area.

    Read from the PPD rather than listed here, because the PPD is the printer's
    statement about itself and this file is not.
    """
    try:
        text = ppd_path(queue).read_text(encoding="latin-1")
    except OSError:
        return []
    out = []
    for key, name, box in re.findall(r'^\*ImageableArea (\S+?)/([^:]*): "([^"]+)"', text, re.M):
        dim = re.search(rf'^\*PaperDimension {re.escape(key)}/[^:]*: "([^"]+)"', text, re.M)
        if not dim:
            continue
        l, b, r, t = (float(v) for v in box.split())
        pw, ph = (float(v) for v in dim.group(1).split())
        out.append({"size": key, "name": name.strip(),
                    "label_mm": [round(pw / PT * 25.4, 1), round(ph / PT * 25.4, 1)],
                    "printable_mm": [round((r - l) / PT * 25.4, 1),
                                     round((t - b) / PT * 25.4, 1)]})
    return out


def _geometry(queue: str, size: str) -> dict:
    text = ppd_path(queue).read_text(encoding="latin-1")

    def one(key: str) -> list:
        m = re.search(rf'^\*{key} {re.escape(size)}/[^:]*: "([^"]+)"', text, re.M)
        if not m:
            raise ValueError(f"{queue} has no roll called {size!r}")
        return [float(v) for v in m.group(1).split()]

    (pw, ph), (l, b, r, t) = one("PaperDimension"), one("ImageableArea")
    return {"paper": (pw, ph), "box": (l, b, r, t), "printable": (r - l, t - b)}


def _pdf_text(value: str) -> str:
    """A PDF string literal. The three characters that would end it early."""
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def label_pdf(value: str, queue: str, size: str, dots: int, rotate: bool) -> bytes:
    """One label: the Code 128 symbol, and the value under it in Helvetica.

    Vector, not an image, for the reason measured above: a bar drawn a whole
    number of dots wide rasterises to exactly that many dots with no grey edge
    for the thermal head to halftone into a ragged bar.
    """
    geo = _geometry(queue, size)
    modules = code128(value)
    unit = dots * PT / DPI
    width = (len(modules) + 2 * QUIET) * unit
    across, down = geo["printable"]
    if rotate:
        across, down = down, across
    if width > across:
        raise ValueError(
            f"{value} needs {width / PT * 25.4:.1f} mm of barcode and this roll prints "
            f"{across / PT * 25.4:.1f} mm across — turn the label, or pick a longer roll")
    pad = 1.0 / 25.4 * PT      # 1 mm of air, so a roll tracking off centre cannot clip a bar
    text_pt = min(10.0, (down - 2 * pad) * 0.22)
    gap = text_pt * 0.35
    bars_h = down - 2 * pad - text_pt - gap
    if bars_h <= 0:
        raise ValueError(f"this roll is too narrow to carry a barcode and its text")

    l, b, r, t = geo["box"]
    # Start the quiet zone on a whole dot, so every bar edge lands on one too.
    x0 = round((across - width) / 2 / PT * DPI) * PT / DPI + QUIET * unit
    y0 = pad + text_pt + gap
    ops = ["q", "0 0 0 rg",
           f"0 1 -1 0 {r:.4f} {b:.4f} cm" if rotate else f"1 0 0 1 {l:.4f} {b:.4f} cm"]
    x, i = x0, 0
    while i < len(modules):
        j = i
        while j < len(modules) and modules[j] == modules[i]:
            j += 1
        if modules[i] == "1":
            ops.append(f"{x:.4f} {y0:.4f} {(j - i) * unit:.4f} {bars_h:.4f} re f")
        x += (j - i) * unit
        i = j
    advance = sum(HELVETICA.get(c, 600) for c in value) / 1000 * text_pt
    ops += ["BT", f"/F1 {text_pt:.2f} Tf",
            f"{x0 - QUIET * unit + (width - advance) / 2:.4f} {pad + text_pt * 0.18:.4f} Td",
            f"({_pdf_text(value)}) Tj", "ET", "Q"]
    stream = "\n".join(ops).encode("latin-1")

    pw, ph = geo["paper"]
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        (f"<</Type/Page/Parent 2 0 R/MediaBox[0 0 {pw:.2f} {ph:.2f}]"
         f"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>").encode(),
        b"<</Length %d>>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    body, offsets = b"%PDF-1.4\n", []
    for n, obj in enumerate(objs, 1):
        offsets.append(len(body))
        body += b"%d 0 obj " % n + obj + b" endobj\n"
    start = len(body)
    body += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    body += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    return body + (b"trailer <</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n"
                   % (len(objs) + 1, start))


def _lp(args: list, timeout: int = 15) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


# Reasons CUPS raises in the ordinary course of printing. Measured on
# 2026-09-17: a healthy job spends most of its life under
# `cups-waiting-for-job-completed`, which means "the backend has sent
# everything and is waiting for the printer to finish" — not a fault. Reporting
# it as one put a red line in the log of every good label.
BENIGN_REASONS = ("none", "", "cups-waiting-for-job-completed")


def printer_state(queue: str) -> dict:
    """What the queue says about itself right now.

    Two fields, and they answer different questions. `reasons` says whether
    anything is WRONG — a LabelWriter with no roll answers
    `com.dymo.slot-status-error` here while the job waits. `message` is CUPS's
    running commentary, and it is the only place the printer says it has
    actually started putting ink down ("Printing page 1, 99% complete").
    """
    raw = "unknown"
    for line in _lp(["lpoptions", "-p", queue]).split():
        if line.startswith("printer-state-reasons="):
            raw = line.split("=", 1)[1]
    # CUPS may report several at once, comma separated.
    faults = [r for r in raw.split(",") if r not in BENIGN_REASONS]
    lines = _lp(["lpstat", "-p", queue]).split("\n")
    return {"queue": queue, "reasons": ",".join(faults), "raw": raw,
            "message": lines[1].strip() if len(lines) > 1 else "",
            "sent": "cups-waiting-for-job-completed" in raw,
            "ok": not faults}


# The laser CONTROLLER as it appears on USB. LightBurn cannot say whether it is
# connected — STATUS answers OK on a "Disconnected" profile — but the bus can
# say whether the board is there at all, which is the half of the question a
# powered-off or unplugged machine answers. Measured 2026-09-17: the AtomStack
# M4's BSL board is Cypress 04b4:1004, "SEATHINKING SEA-LASER", no serial number.
LASER_USB = {(0x04B4, 0x1004): "BSL galvo board"}
_laser_cache: "tuple[float, dict]" = (0.0, {})


def laser_usb() -> dict:
    """{present, name, ids} for the laser board on the USB bus, cached 5 s.

    macOS only (ioreg); elsewhere `present` is None, meaning "cannot tell".
    """
    global _laser_cache
    at, cached = _laser_cache
    if time.time() - at < 5:
        return cached
    out: dict = {"present": None, "name": "", "ids": ""}
    if sys.platform == "darwin":
        r = subprocess.run(["ioreg", "-p", "IOUSB", "-l", "-w0"], capture_output=True, text=True)
        # One block per device ("+-o" starts each), so a vendor is paired with
        # ITS product rather than with the next device's.
        found = []
        for block in r.stdout.split("+-o ")[1:]:
            v = re.search(r'"idVendor" = (\d+)', block)
            pr = re.search(r'"idProduct" = (\d+)', block)
            if v and pr and (int(v.group(1)), int(pr.group(1))) in LASER_USB:
                found.append((int(v.group(1)), int(pr.group(1))))
        out["present"] = bool(found)
        if found:
            out["name"] = LASER_USB[found[0]]
            out["ids"] = "%04x:%04x" % found[0]
    _laser_cache = (time.time(), out)
    return out


def list_printers() -> list:
    """Every print queue on this machine, and which one is the default."""
    out, default = [], ""
    for line in _lp(["lpstat", "-p", "-d"]).splitlines():
        if line.startswith("printer "):
            name = line.split()[1]
            out.append({"queue": name, "idle": " is idle" in line,
                        "label_printer": ppd_path(name).exists()
                        and "dymo" in ppd_path(name).read_text(
                            encoding="latin-1", errors="ignore")[:2000].lower()})
        elif line.startswith("system default destination:"):
            default = line.rsplit(":", 1)[1].strip()
    for p in out:
        p["default"] = p["queue"] == default
        p.update({k: v for k, v in printer_state(p["queue"]).items() if k != "queue"})
    return out


# The deployed bench. Dev origins are added with --origin, never assumed: an
# allow-list that quietly includes localhost is an allow-list with a hole in it.
DEFAULT_ORIGINS = ("https://disfunction.cc",)
PROTOCOL_VERSION = 3
# A job's lines and result are kept so a page that reloads mid-mark can still
# read the outcome. Only the last few matter; a bench runs one at a time.
KEEP_JOBS = 20


class Job:
    """One mark, and everything said while it ran."""

    def __init__(self, job_id: int):
        self.id = job_id
        self.lines: list[dict] = []
        self.done = False
        self.result: dict = {}
        self.lock = threading.Lock()

    def add(self, direction: str, text: str) -> None:
        with self.lock:
            self.lines.append({"dir": direction, "text": text})

    def since(self, n: int) -> list[dict]:
        with self.lock:
            return self.lines[n:]


# ---------------------------------------------------------------------------
# Programming an ESP through the vendored esptool.
#
# The agent stays ONE downloadable thing, but not one standard-library file any
# more: `vendor.zip` beside it carries esptool and pyserial (pure Python, no
# compiled code, ~640 KB), extracted once into the user's cache. Decision 0023
# says why the browser gave this job up: a deploy invalidated every open bench
# tab, the CH340 has no serial number for Chrome to remember, and Python's
# esptool changes baud on the open descriptor where esptool-js reopens the port.
# ---------------------------------------------------------------------------

VENDOR_ZIP = Path(__file__).resolve().with_name("vendor.zip")
VENDOR_DIRS = ("esptool", "serial", "bitstring", "ecdsa", "intelhex", "reedsolo.py", "yaml")
ROM_BAUD = 115200
BOOT_WAIT_S = 30.0


def import_vendor() -> "str | None":
    """Make esptool importable; return its version, or None with the reason logged.

    Extracted rather than imported from the zip: esptool opens its stub flasher
    JSON files by path, which zipimport cannot serve. Keyed by the zip's hash so
    a new agent never runs an old esptool.
    """
    import hashlib
    import zipfile
    if not VENDOR_ZIP.is_file():
        say("esptool: vendor.zip is missing beside agent.py — programming through the agent is off")
        return None
    digest = hashlib.sha256(VENDOR_ZIP.read_bytes()).hexdigest()[:12]
    cache = (Path.home() / "Library" / "Caches" / "7Sigma Agent" if sys.platform == "darwin"
             else Path(tempfile.gettempdir()) / "7sigma-agent") / f"vendor-{digest}"
    if not (cache / "esptool").is_dir():
        cache.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(VENDOR_ZIP) as z:
            z.extractall(cache)
    sys.path.insert(0, str(cache))
    try:
        import esptool  # noqa: F401
        import serial  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        say(f"esptool: cannot import the vendored copy: {exc}")
        return None
    return str(getattr(esptool, "__version__", "?"))


class _JobWriter:
    """A file-like sink that turns esptool's prints into job lines.

    esptool reports progress with `\r` and everything else with `\n`; both end
    a line here, so "Writing at 0x1000... (3%)" arrives one line at a time.
    """

    def __init__(self, job: "Job", direction: str = "esptool"):
        self.job, self.direction, self.buf = job, direction, ""

    def isatty(self) -> bool:
        """False, so esptool's `print_overwrite` ends each progress update with
        a newline instead of a carriage return. Either is parsed here, but a
        line is what the page's log and its progress bar expect."""
        return False

    def write(self, text: str) -> int:
        self.buf += text
        while True:
            cut = min((i for i in (self.buf.find("\n"), self.buf.find("\r")) if i >= 0), default=-1)
            if cut < 0:
                break
            line, self.buf = self.buf[:cut].strip(), self.buf[cut + 1:]
            if line:
                self.job.add(self.direction, line)
        return len(text)

    def flush(self) -> None:
        if self.buf.strip():
            self.job.add(self.direction, self.buf.strip())
        self.buf = ""


class EspRun:
    """One ESP operation on one port: connect, erase, flash or reset.

    The connect LADDER is the browser's, rung for rung (station.ts, 2026-09-16),
    because every rung was a real V2: default_reset at the fast baud, then at
    115200, then BOOT held with EN pulsed by us — retried until the operator
    has the button down or the deadline passes.
    """

    def __init__(self, job: "Job", body: dict, job_dir: Path):
        self.job = job
        self.op = str(body.get("op") or "")
        self.port = str(body.get("port") or "")
        self.chip = str(body.get("chip") or "auto").lower().replace("-", "") or "auto"
        self.fast = int(body.get("baud") or 460800)
        self.images = list(body.get("images") or [])
        self.flash_config = dict(body.get("flash_config") or {})
        self.boot_wait = float(body.get("boot_wait") or BOOT_WAIT_S)
        self.job_dir = job_dir
        self.saw_baud_change = False

    # -- esptool as a library, with its stdout caught ---------------------

    def _esptool(self, argv: list) -> list:
        """Run one esptool command line; return its lines; raise on failure."""
        import contextlib
        import esptool
        writer = _JobWriter(self.job)
        start = len(self.job.lines)
        self.job.add("app", "esptool " + " ".join(argv))
        try:
            with contextlib.redirect_stdout(writer):
                esptool.main(argv)
        except SystemExit as exc:  # argparse, or esptool's own exit code
            writer.flush()
            code = exc.code
            del exc
            if code not in (0, None):
                raise MarkError(f"esptool exited with {code}") from None
        except Exception as exc:  # FatalError and friends
            writer.flush()
            # The MESSAGE only. Chaining or keeping `exc` keeps its traceback,
            # and the traceback keeps esptool's loader and its open port alive
            # — which is how the agent came to refuse its own port.
            msg = str(exc)
            del exc
            raise MarkError(msg) from None
        finally:
            writer.flush()
        lines = [l["text"] for l in self.job.lines[start:]]
        if any("Changing baud rate" in l or "Changed." in l for l in lines):
            self.saw_baud_change = True
        return lines

    def _pulse_enable(self) -> None:
        """EN low for 200 ms with IO0 left alone — the operator holds BOOT."""
        import serial
        with serial.Serial(self.port, ROM_BAUD, timeout=0.1) as s:
            s.dtr = False
            s.rts = True
            time.sleep(0.2)
            s.rts = False
            time.sleep(0.4)
        self.job.add("app", "EN pulsed while BOOT is held — chip should be in download mode")

    def _common(self, before: str, baud: int, after: str) -> list:
        return ["--chip", self.chip, "--port", self.port, "--baud", str(baud),
                "--before", before, "--after", after, "--connect-attempts", "3"]

    def _connect_ladder(self, command: list, after: str) -> str:
        """Run `command` under each rung until one works; return the rung's name."""
        rungs = [("default_reset", self.fast, f"{self.fast} baud")]
        if self.fast != ROM_BAUD:
            rungs.append(("default_reset", ROM_BAUD, "115200, no baud change"))
        last = ""
        for before, baud, why in rungs:
            failed = ""
            try:
                self._esptool(self._common(before, baud, after) + command)
                self.job.add("app", f"connected: {why}")
                return why
            except MarkError as exc:
                failed = str(exc)
            # Outside the handler on purpose: inside it the exception — and
            # through its traceback esptool's loader and the OPEN PORT — is
            # still alive, and the next rung found the port busy with itself.
            release_own_port(self.port, self.job)
            last = failed
            # A port that cannot be OPENED is not a rung: holding BOOT will
            # not make a node appear or free it from another process.
            if ("could not open port" in failed or "busy or doesn't exist" in failed) \
                    and not _held_by_me(self.port):
                raise MarkError(f"cannot open {self.port}: unplugged, or held by another program")
            self.job.add("err", f"{failed} — {why} did not work")
        # The BOOT rung keeps trying: the operator has to pick the board up.
        self.job.add("app", "waiting for the BOOT button to be held — retrying until it is")
        deadline = time.time() + self.boot_wait
        baud = self.fast
        for try_no in range(1, 10_000):
            try:
                self._pulse_enable()
                self._esptool(self._common("no_reset", baud, after) + command)
                why = f"BOOT held, no_reset, {baud} baud"
                self.job.add("app", f"connected: {why}, attempt {try_no}")
                return why
            except (MarkError, OSError) as exc:
                last = str(exc)
            # Only reached on failure (success returned above). Outside the
            # handler, so the failed attempt's port is really let go.
            release_own_port(self.port, self.job)
            if baud != ROM_BAUD and self.saw_baud_change:
                baud = ROM_BAUD
                self.job.add("app", f"this board will not hold {self.fast} baud — dropping to {ROM_BAUD}")
            if time.time() > deadline:
                raise MarkError(f"BOOT was not held within {int(self.boot_wait)}s ({last})")
            if try_no % 4 == 0:
                self.job.add("app", f"still waiting for BOOT (attempt {try_no})")
            time.sleep(1.2)
        raise MarkError(last or "could not connect")

    # -- the four operations ------------------------------------------------

    def run(self) -> dict:
        if not self.port:
            raise MarkError("no port: assign this station's socket first")
        release_own_port(self.port, self.job)
        held = "" if _held_by_me(self.port) else _holders([self.port]).get(self.port, "")
        if held:
            raise MarkError(f"{self.port} is held by {held} — close it there first")
        if self.op == "connect":
            mode = self._connect_ladder(["chip_id"], "no_reset")
            chip = mac = ""
            for l in [x["text"] for x in self.job.lines]:
                if l.startswith("Chip is "):
                    chip = l[len("Chip is "):].strip()
                elif l.startswith("MAC:"):
                    mac = l[4:].strip()
            if not mac:
                raise MarkError("esptool reported no MAC")
            return {"chip": chip, "mac": mac, "connect_mode": mode}
        if self.op == "erase":
            mode = self._connect_ladder(["erase_flash"], "no_reset")
            return {"connect_mode": mode}
        if self.op == "flash":
            if not self.images:
                raise MarkError("flash: no images")
            argv = ["write_flash", "--flash_size", str(self.flash_config.get("size") or "detect"),
                    "--flash_mode", str(self.flash_config.get("mode") or "keep"),
                    "--flash_freq", str(self.flash_config.get("freq") or "keep"), "-z"]
            for i, img in enumerate(self.images):
                data = base64.b64decode(img["data"])
                path = self.job_dir / f"fw-{self.job.id}-{i}.bin"
                path.write_bytes(data)
                self.job.add("app", f"image {img.get('name', path.name)} = {len(data)} bytes @ {img['address']}")
                argv += [str(img["address"]), str(path)]
            mode = self._connect_ladder(argv, "hard_reset")
            return {"connect_mode": mode}
        if self.op == "reset":
            import serial
            with serial.Serial(self.port, ROM_BAUD, timeout=0.1) as s:
                s.dtr = False   # IO0 high: a normal boot
                s.rts = True    # EN low
                time.sleep(0.1)
                s.rts = False
            self.job.add("app", "hard reset pulsed")
            return {}
        raise MarkError(f"unknown esp op {self.op!r}")


class Monitor:
    """The device console, held open by the agent instead of by the browser.

    The console phase is the other half of a run: the engine writes a Tasmota
    command and reads the answer, with the bench as a dumb byte pipe. It used
    to be Web Serial in the tab. Here it is one pyserial port and a reader
    thread, and the page polls the lines the way it polls a job — which is what
    lets a bench work with NO serial permission, no port picker and no Chrome
    policy at all (decision 0023).

    Lines are kept in a ring: a boot prints hundreds per second, and the page
    only ever asks for the ones it has not seen.
    """

    def __init__(self, port: str, baud: int, signals: "dict | None"):
        import serial
        self.port, self.baud = port, baud
        self.lines: "collections.deque[dict]" = collections.deque(maxlen=4000)
        self.first = 0  # lines that have already fallen out of the ring
        # A CONDITION, not just a lock: `since()` blocks on it until there is
        # something to say, so the page learns of a line within a round trip
        # instead of within a poll interval. A device dialog is
        # request/response — the engine drains the queue before every command —
        # so a console delivered in 150 ms clumps loses replies that arrive in
        # 3 ms (run 6377, 2026-09-17: SetOption153 answered and was drained).
        self.lock = threading.Condition()
        self.closing = False
        # timeout is the READ deadline, and `read(n)` waits for all n bytes or
        # for it — so a big n plus a long timeout is a latency floor, not a
        # buffer size. Kept short, and `_read` asks for one byte at a time and
        # then drains what is waiting.
        self.ser = serial.Serial(port, baud, timeout=0.05)
        if signals is not None:
            # A profile that says "do not drive these" means exactly that: on
            # the C6's USB-Serial/JTAG a DTR/RTS move resets the chip.
            self.ser.dtr = bool(signals.get("dataTerminalReady"))
            self.ser.rts = bool(signals.get("requestToSend"))
        self.thread = threading.Thread(target=self._read, daemon=True)
        self.thread.start()

    def _add(self, text: str) -> None:
        with self.lock:
            if len(self.lines) == self.lines.maxlen:
                self.first += 1
            self.lines.append({"text": text})
            self.lock.notify_all()

    def _read(self) -> None:
        buf = b""
        while not self.closing:
            try:
                # Block for ONE byte, then take everything already buffered.
                # `read(4096)` waits for the full count or the timeout, which
                # put a 200 ms floor under every device reply (run 6377,
                # 2026-09-17: every command paced at about a second).
                chunk = self.ser.read(1) or b""
                if chunk and self.ser.in_waiting:
                    chunk += self.ser.read(self.ser.in_waiting)
            except Exception as exc:  # noqa: BLE001 — the device left the bus
                if not self.closing:
                    self._add(f"[read error: {exc}]")
                return
            if chunk:
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.rstrip(b"\r").decode("utf-8", "replace")
                    if text.strip():
                        self._add(text)

    def since(self, n: int, wait: float = 0.0) -> "tuple[int, list]":
        """Lines after `n`. With `wait`, block until there is one or it expires.

        Long polling rather than a WebSocket, for the same reason the whole
        agent speaks plain HTTP: no dependency, no install. It costs one held
        request and buys the latency of a local round trip.
        """
        with self.lock:
            if wait > 0 and not self.closing:
                self.lock.wait_for(
                    lambda: self.closing or self.first + len(self.lines) > n, timeout=wait)
            start = max(0, n - self.first)
            out = [dict(x) for x in list(self.lines)[start:]]
            return self.first + len(self.lines), out

    def write(self, text: str) -> None:
        self.ser.write(text.encode())
        self.ser.flush()

    def reset(self) -> None:
        """Pulse EN with IO0 left high: a normal boot, not download mode.

        THE 500 ms BEFORE THE PULSE IS LOAD-BEARING. Tasmota holds a changed
        setting in RAM and flushes it to flash on its own SaveData timer, about
        a second later. Pulling EN low the instant the command is confirmed
        resets the device before the write, and the setting is simply gone —
        which is how a run could confirm `{"Password1":"GeneralKenobi"}` and
        then find `"SSId":["",""]` one step later (run 6382, 2026-09-17). The
        browser implementation had this delay and the agent's first version
        dropped it; the agent is faster, so it lost the race the browser won by
        accident. 500 ms hold, then release, matching what was measured.
        """
        self.ser.dtr = False   # IO0 high: a normal boot, never download mode
        self.ser.rts = False
        time.sleep(0.5)        # let the firmware write its settings first
        self.ser.rts = True    # EN low
        time.sleep(0.5)
        self.ser.rts = False   # EN high: boot

    def close(self) -> None:
        with self.lock:
            self.closing = True
            self.lock.notify_all()  # let a held long poll answer at once
        try:
            self.ser.close()
        except Exception:  # noqa: BLE001
            pass
        self.thread.join(timeout=2)


class Agent:
    def __init__(self, origins: set[str], lb_host: str, job_dir: Path):
        self.origins = origins
        self.lb_host = lb_host
        self.job_dir = job_dir
        self.jobs: dict[int, Job] = {}
        self.next_id = 0
        self.busy = False
        # The LightBurn profile this session is committed to: the first one a
        # job selected. LightBurn only connects the profile it started with, so
        # a later job asking for the other one is refused, not switched. Reset
        # when the agent relaunches LightBurn.
        self.session_profile: str | None = None
        self.probing = False  # one LightBurn probe at a time from the status views
        # Printing has its own flag. `busy` means the LASER is running and
        # health() reports it as such — a label must not make the laser look
        # busy, and the two hardware pieces are independent.
        self.printing = False
        # Programming holds a serial port for a minute; one at a time, like a mark.
        self.flashing = False
        # The console port, held open between steps for the whole dialog phase.
        self.monitor: Monitor | None = None
        self.esptool_version: str | None = None
        self.lock = threading.Lock()
        # One health probe at a time, and its answer kept. Two probes would bind
        # the reply port (19841) twice, and with SO_REUSEADDR either can take
        # the other's datagram.
        self.health_lock = threading.Lock()
        self.last_health: dict = {}
        self.last_health_at = 0.0
        # When a BENCH PAGE last spoke to us. The operator's other half of the
        # picture: the agent can be perfect and the browser still not reaching
        # it, and those are fixed in different places.
        self.last_page_at = 0.0
        # The origins this bench is actually FOR — the one baked into the
        # launcher. `origins` is wider: it always carries the deployed platform
        # so a copy moved between benches still answers. Only these are set up
        # in Chrome, so only these are worth reporting on.
        self.setup_origins: "set[str]" = set()

    # -- LightBurn ----------------------------------------------------------

    def health(self) -> dict:
        """PING + STATUS, except while a job is running.

        The page polls this every couple of seconds, and a mark holds its own
        socket on the reply port (19841) for the whole job. A second socket
        bound there with SO_REUSEADDR can take a reply meant for the first, so a
        poll could steal the STATUS that `wait_for_idle` is waiting for and end
        the job early. While we are marking we already know the answer, so say
        it without touching LightBurn.
        """
        if self.busy:
            return {"responsive": True, "busy": True, "laser_usb": laser_usb()}
        with self.health_lock:
            lb = LightBurn(host=self.lb_host)
            try:
                alive = lb.ping()
                out = {"responsive": alive, "busy": None if not alive else lb.busy(),
                       "laser_usb": laser_usb()}
            finally:
                lb.close()
            self.last_health, self.last_health_at = out, time.time()
            return out

    def start_mark(self, body: dict) -> dict:
        with self.lock:
            if self.busy:
                # By refusal, not by queueing: two marks in flight means two
                # jobs racing for one laser, and the second would silently
                # replace the first in LightBurn.
                return {"error": "the agent is already marking"}
            try:
                data = base64.b64decode(body["lbrn2"], validate=True)
            except (KeyError, ValueError, TypeError) as exc:
                return {"error": f"no usable lbrn2 in the request: {exc}"}
            self.next_id += 1
            job = Job(self.next_id)
            self.jobs[job.id] = job
            for old in sorted(self.jobs)[:-KEEP_JOBS]:
                del self.jobs[old]
            self.busy = True

        name = str(body.get("name") or "job")
        device = str(body.get("device") or "")
        # Anything that could climb out of the job directory is dropped rather
        # than cleaned: this process writes files on the operator's machine.
        safe = "".join(c for c in name if c.isalnum() or c in "-_")[:64] or "job"
        start = bool(body.get("start", True))
        timeout = float(body.get("job_timeout", 300))
        threading.Thread(target=self._run, args=(job, data, safe, start, timeout, device),
                         daemon=True).start()
        return {"job": job.id}

    def _run(self, job: Job, data: bytes, safe: str, start: bool, timeout: float,
             device: str = "") -> None:
        log = Log()
        log.add = job.add  # type: ignore[method-assign]
        result: dict = {"status": "fail"}
        lb = LightBurn(host=self.lb_host, log=log)
        path = self.job_dir / f"{safe}-{int(time.time())}.lbrn2"
        try:
            lb.require_responsive("before starting")
            # Before the file, not after: loading a job under one profile and
            # firing it under another is the mistake this prevents.
            if device:
                # Only the profile LightBurn STARTED with can connect. A switch
                # answers OK, shows "Disconnected", and STATUS still says OK —
                # so the job would "succeed" and mark nothing (measured
                # 2026-09-17, docs/reference/laser-marking.md). Refuse it.
                if self.session_profile and device != self.session_profile:
                    raise MarkError(
                        f"this LightBurn session is on {self.session_profile!r} and cannot switch "
                        f"to {device!r}: LightBurn only connects the profile it started with. "
                        f"Quit LightBurn, start it with {device!r} selected, and run again."
                    )
                lb.select(device)
                self.session_profile = device
            path.write_bytes(data)
            job.add("app", f"wrote {path.name} ({len(data)} B)")
            say(f"marking {safe}")
            lb.load(path)
            if start:
                lb.start()
                result["job_seconds"] = lb.wait_for_idle(timeout=timeout)
                job.add("app", f"job reported idle after {result['job_seconds']:.1f}s")
            else:
                job.add("app", "loaded only, not started")
            result["status"] = "pass"
        except (MarkError, DialogBlocked, OSError) as exc:
            result["error"] = str(exc)
            job.add("err", str(exc))
        finally:
            lb.close()
            result["job_file"] = str(path)
            job.result = result
            job.done = True
            with self.lock:
                self.busy = False


    # -- the printer --------------------------------------------------------

    def start_print(self, body: dict) -> dict:
        """Lay a label out and hand it to CUPS. One at a time, like a mark."""
        value = str(body.get("value") or "").strip()
        if not value:
            return {"error": "nothing to print: the value is empty"}
        queue = str(body.get("printer") or "").strip()
        if not queue:
            found = [p for p in list_printers() if p.get("default")] or list_printers()
            if not found:
                return {"error": "this machine has no printer. Add one in System Settings."}
            queue = found[0]["queue"]
        size = str(body.get("size") or DEFAULT_ROLL)
        dots = max(2, min(8, int(body.get("dots") or 3)))
        try:
            pdf = label_pdf(value, queue, size, dots, bool(body.get("rotate", True)))
        except (ValueError, OSError) as exc:
            # A label that does not fit is the operator's answer to give, not a
            # job to queue and fail later.
            return {"error": str(exc)}
        with self.lock:
            if self.printing:
                return {"error": "the agent is already printing"}
            self.next_id += 1
            job = Job(self.next_id)
            self.jobs[job.id] = job
            for old in sorted(self.jobs)[:-KEEP_JOBS]:
                del self.jobs[old]
            self.printing = True
        threading.Thread(target=self._print, args=(
            job, pdf, value, queue, size, max(1, min(20, int(body.get("copies") or 1))),
            float(body.get("job_timeout", 120))), daemon=True).start()
        return {"job": job.id}

    # -- the device console, so the browser needs no serial at all ----------

    def monitor_open(self, body: dict) -> dict:
        port = str(body.get("port") or "")
        if not port:
            return {"error": "no port: assign this station's socket first"}
        if not self.esptool_version:
            return {"error": "this agent has no pyserial — vendor.zip is missing or broken"}
        with self.lock:
            if self.monitor:
                self.monitor.close()
                self.monitor = None
            release_own_port(port)
            held = "" if _held_by_me(port) else _holders([port]).get(port, "")
            if held:
                return {"error": f"{port} is held by {held} — close it there first"}
            try:
                self.monitor = Monitor(port, int(body.get("baud") or 115200), body.get("signals"))
            except Exception as exc:  # noqa: BLE001
                return {"error": f"could not open {port}: {exc}"}
        say(f"monitor open on {port} @ {body.get('baud')}")
        return {"open": True, "port": port}

    def monitor_lines(self, since: int, wait: float = 0.0) -> dict:
        m = self.monitor
        if not m:
            return {"open": False, "seen": since, "lines": []}
        seen, lines = m.since(since, wait)
        return {"open": True, "seen": seen, "lines": lines}

    def monitor_write(self, body: dict) -> dict:
        m = self.monitor
        if not m:
            return {"error": "the monitor is not open"}
        try:
            m.write(str(body.get("text") or ""))
        except Exception as exc:  # noqa: BLE001
            return {"error": f"write failed: {exc}"}
        return {"ok": True}

    def monitor_reset(self, body: dict) -> dict:
        m = self.monitor
        if not m:
            return {"error": "the monitor is not open"}
        try:
            m.reset()
        except Exception as exc:  # noqa: BLE001
            return {"error": f"reset failed: {exc}"}
        return {"ok": True}

    def monitor_close(self) -> dict:
        with self.lock:
            if self.monitor:
                self.monitor.close()
                self.monitor = None
                say("monitor closed")
        return {"ok": True}

    def start_esp(self, body: dict) -> dict:
        """Connect to, erase, flash or reset an ESP on one of this machine's ports."""
        if not self.esptool_version:
            return {"error": "this agent has no esptool — vendor.zip is missing or broken (see its log)"}
        with self.lock:
            if self.flashing:
                return {"error": "the agent is already programming a device"}
            self.next_id += 1
            job = Job(self.next_id)
            self.jobs[job.id] = job
            for old in sorted(self.jobs)[:-KEEP_JOBS]:
                del self.jobs[old]
            self.flashing = True
        threading.Thread(target=self._esp, args=(job, body), daemon=True).start()
        return {"job": job.id}

    def _esp(self, job: Job, body: dict) -> None:
        result: dict = {"status": "fail"}
        t0 = time.time()
        try:
            info = EspRun(job, body, self.job_dir).run()
            result = {"status": "pass", "info": info, "job_seconds": time.time() - t0}
        except (MarkError, OSError) as exc:
            result["error"] = str(exc)
            job.add("err", str(exc))
        except Exception as exc:  # noqa: BLE001 — a bug must surface in the log, not vanish
            result["error"] = f"{type(exc).__name__}: {exc}"
            job.add("err", result["error"])
        finally:
            with self.lock:
                self.flashing = False
            job.result = result
            job.done = True
            say(f"esp {body.get('op')} on {body.get('port')}: {result['status']}"
                + (f" — {result.get('error')}" if result.get("error") else ""))

    def _print(self, job: Job, pdf: bytes, value: str, queue: str, size: str,
               copies: int, timeout: float) -> None:
        """Send it, then WATCH it. A queued job is not a printed label.

        WHAT COUNTS AS PRINTED, and why it is not `job-state = completed`.
        Measured three times on 2026-09-17: the label is physically out when
        CUPS stops saying "Printing page N" — 1.9 s into a warm job, 4.8 s into
        a cold one — and CUPS then holds the job for a further SEVEN SECONDS
        under `cups-waiting-for-job-completed`, waiting for the printer to
        acknowledge. That tail was 6.97 s and 7.23 s on two runs, so it is a
        fixed timeout in the backend and not the printer working. Waiting for it
        made a two-second step report nine.

        So a label is printed when all three hold: the printer SAID it was
        printing a page, the backend has finished sending, and no fault stands.
        The last one is what makes it safe — with no roll, the standing
        `com.dymo.slot-status-error` fails the test whatever the message says.

        A run that gives up MUST cancel its own job. With no roll the job sits
        in `processing` and RESUMES BY ITSELF the moment a roll goes back in,
        which would print this serial onto whatever unit is in the fixture then.
        """
        result = {"status": "fail"}
        path = self.job_dir / f"{''.join(c for c in value if c.isalnum() or c in '-_')[:64] or 'label'}-{int(time.time())}.pdf"
        started = time.time()
        cups_job = ""
        try:
            path.write_bytes(pdf)
            job.add("app", f"wrote {path.name} ({len(pdf)} B) for {queue}, roll {size}")
            out = _lp(["lp", "-d", queue, "-o", f"PageSize={size}", "-n", str(copies),
                       "-t", value, str(path)])
            # "request id is DYMO_LabelWriter_550-103 (1 file(s))"
            match = re.search(r"request id is (\S+)", out)
            if not match:
                raise MarkError(f"lp did not accept the label: {out.strip() or 'no answer'}")
            cups_job = match.group(1)
            job.add("tx", f"{cups_job} queued, {copies} label(s)")
            say(f"printing {value} on {queue}")
            complained, said, printing = "", "", False
            while time.time() - started < timeout:
                time.sleep(POLL_SECONDS)
                state = printer_state(queue)
                # The printer's own commentary, once each time it changes. A
                # silent gap of several seconds reads as a broken bench.
                if state["message"] and state["message"] != said:
                    said = state["message"]
                    job.add("rx", said)
                if PRINTING_RE.search(state["message"]):
                    printing = True
                done = cups_job in _lp(["lpstat", "-W", "completed", "-o", queue])
                if (printing and state["sent"]) or done:
                    if not state["ok"]:
                        # A fault standing at the end: say so rather than claim
                        # a label came out.
                        raise MarkError(f"the printer reported {state['reasons']} — "
                                        + PRINTER_ADVICE.get(state["reasons"], "check it"))
                    result["job_seconds"] = round(time.time() - started, 1)
                    result["status"] = "pass"
                    job.add("app", f"the label is out after {result['job_seconds']:.1f}s"
                                   + ("" if done else
                                      f" ({cups_job} is still being retired by CUPS,"
                                      " which takes about another 7s and prints nothing)"))
                    break
                if not state["ok"] and state["reasons"] != complained:
                    complained = state["reasons"]
                    job.add("err", f"the printer reports {complained} — "
                                   + PRINTER_ADVICE.get(complained, "check it"))
            else:
                raise MarkError(f"the printer did not finish within {timeout:.0f}s")
        except (MarkError, OSError) as exc:
            result["error"] = str(exc)
            job.add("err", str(exc))
            if cups_job:
                # Never leave it queued. See the docstring.
                _lp(["cancel", cups_job])
                job.add("app", f"cancelled {cups_job} so it cannot print later")
        finally:
            result["printed"] = value if result["status"] == "pass" else ""
            result["cups_job"] = cups_job
            result["job_file"] = str(path)
            job.result = result
            job.done = True
            with self.lock:
                self.printing = False


class Handler(BaseHTTPRequestHandler):
    agent: Agent  # set on the server class below
    protocol_version = "HTTP/1.1"

    # -- plumbing -----------------------------------------------------------

    def log_message(self, fmt: str, *args) -> None:  # noqa: A002
        sys.stderr.write(f"{self.address_string()} {fmt % args}\n")  # noqa: E501

    def allowed_origin(self) -> str | None:
        """The Origin to echo back, or None when this request is refused.

        Returns "" for a request with no Origin — allowed, but nothing to echo.
        """
        origin = self.headers.get("Origin")
        if origin is None:
            return ""
        return origin if origin in self.agent.origins else None

    def note_page(self, origin: str) -> None:
        if origin:
            self.agent.last_page_at = time.time()

    def reply(self, code: int, payload: dict, origin: str = "") -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def refuse(self) -> None:
        say(f"refused a request from {self.headers.get('Origin')}")
        self.reply(403, {"error": "origin not allowed"})

    # -- routes -------------------------------------------------------------

    def do_OPTIONS(self) -> None:  # noqa: N802
        origin = self.allowed_origin()
        if origin is None:
            return self.refuse()
        self.send_response(204)
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Vary", "Origin")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        origin = self.allowed_origin()
        if origin is None:
            return self.refuse()
        self.note_page(origin)
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            body = status_page(self.agent, self.server.server_address[1])
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if url.path == "/hello":
            return self.reply(200, {"agent": "7sigma-agent",
                                    "protocol": PROTOCOL_VERSION,
                                    "lightburn_host": self.agent.lb_host,
                                    "esptool": self.agent.esptool_version}, origin)
        if url.path == "/health":
            return self.reply(200, self.agent.health(), origin)
        if url.path == "/lasers":
            return self.reply(200, {"lasers": list_lasers()}, origin)
        if url.path == "/monitor":
            q = parse_qs(url.query)
            since = int((q.get("since") or ["0"])[0])
            # Held for up to `wait` seconds. Capped well under any browser or
            # proxy idle timeout, and the page simply asks again.
            wait = max(0.0, min(20.0, float((q.get("wait") or ["0"])[0])))
            return self.reply(200, self.agent.monitor_lines(since, wait), origin)
        if url.path == "/serial-ports":
            return self.reply(200, {"ports": list_serial_ports()}, origin)
        if url.path == "/printers":
            queue = (parse_qs(url.query).get("printer") or [""])[0]
            return self.reply(200, {"printers": list_printers(),
                                    "rolls": rolls(queue) if queue else [],
                                    "default_roll": DEFAULT_ROLL}, origin)
        if url.path.startswith("/job/"):
            try:
                job = self.agent.jobs[int(url.path.rsplit("/", 1)[1])]
            except (KeyError, ValueError):
                return self.reply(404, {"error": "no such job"}, origin)
            since = int((parse_qs(url.query).get("since") or ["0"])[0])
            return self.reply(200, {"lines": job.since(since), "done": job.done,
                                    **job.result}, origin)
        return self.reply(404, {"error": "no such path"}, origin)

    def do_POST(self) -> None:  # noqa: N802
        origin = self.allowed_origin()
        if origin is None:
            return self.refuse()
        path = urlparse(self.path).path
        if path not in ("/mark", "/print", "/esp", "/monitor/open", "/monitor/write",
                        "/monitor/reset", "/monitor/close"):
            return self.reply(404, {"error": "no such path"}, origin)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            return self.reply(400, {"error": "not JSON"}, origin)
        if path.startswith("/monitor/"):
            verb = path.rsplit("/", 1)[1]
            out = ({"open": self.agent.monitor_open, "write": self.agent.monitor_write,
                    "reset": self.agent.monitor_reset}[verb](body)
                   if verb != "close" else self.agent.monitor_close())
        else:
            out = (self.agent.start_mark(body) if path == "/mark"
                   else self.agent.start_print(body) if path == "/print"
                   else self.agent.start_esp(body))
        return self.reply(409 if "error" in out else 200, out, origin)


# ---------------------------------------------------------------------------
# Serial ports — the thing a browser is not allowed to see.
# ---------------------------------------------------------------------------

# macOS names a USB serial node after the USB LOCATION, so /dev/cu.usbserial-110
# IS a physical socket: move the cable and the name changes. Web Serial exposes
# only the vendor and product id, which is why a station could never be bound to
# a socket from the page alone (docs/reference/bench-serial-ports.md). A process
# on the machine has no such limit, and this is that process.
SERIAL_GLOBS = (
    "/dev/cu.usbserial*",      # CH340 on Apple's driver — the V2 dongle
    "/dev/cu.wchusbserial*",   # CH340 on WCH's own driver
    "/dev/cu.usbmodem*",       # native USB-Serial/JTAG, e.g. the C6
    "/dev/cu.SLAB_USBtoUART*",  # CP210x
)


def _holders(nodes: list[str]) -> dict[str, str]:
    """Which process holds each node, from lsof. Empty when lsof is absent.

    This is the half that makes MAPPING possible rather than just listing: the
    page can open one port, ask who holds what, and learn which socket the
    browser just opened — a correlation neither side can make on its own.
    """
    if not nodes:
        return {}
    try:
        out = subprocess.run(["lsof", "-F", "cn", "--", *nodes],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    held: dict[str, str] = {}
    command = ""
    for line in out.splitlines():
        if line.startswith("c"):
            command = line[1:]
        elif line.startswith("n"):
            held.setdefault(line[1:], command)
    return held


def _held_by_me(node: str) -> bool:
    """Whether THIS process still has `node` open, from lsof on our own pid."""
    try:
        out = subprocess.run(["lsof", "-a", "-p", str(os.getpid()), "-F", "n", "--", node],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return any(line == f"n{node}" for line in out.splitlines())


def release_own_port(node: str, job: "Job | None" = None) -> None:
    """Drop a port this process is still holding after a failed esptool call.

    esptool opens the port inside its own loader; when a connect fails, the
    exception's traceback keeps that loader — and its open Serial — alive
    for as long as the exception object is referenced. The agent then saw its
    OWN handle in lsof and refused the next run with "held by Python" (bench,
    2026-09-17). The ladder no longer keeps exception objects, and this forces
    the collector as a second line.
    """
    import gc
    if not _held_by_me(node):
        return
    gc.collect()
    time.sleep(0.1)
    if _held_by_me(node):
        msg = f"{node} is still open in this agent after a failed attempt — it will be reopened"
        (job.add("app", msg) if job else say(msg))


def list_lasers() -> "list[str]":
    """The laser sources LightBurn knows, read from its own preferences.

    So the bench can OFFER the names instead of an operator typing one that
    comes back `!`. Read, never written: LightBurn owns that file.
    """
    prefs = (Path.home() / "Library" / "Preferences" / "LightBurn" / "prefs.ini")
    try:
        raw = prefs.read_text()
        i = raw.index("[", raw.index('"DeviceList"'))
    except (OSError, ValueError):
        return []
    depth = 0
    for j in range(i, len(raw)):
        if raw[j] == "[":
            depth += 1
        elif raw[j] == "]":
            depth -= 1
            if depth == 0:
                try:
                    return [d.get("DisplayName", "") for d in json.loads(raw[i:j + 1])]
                except ValueError:
                    return []
    return []


def list_serial_ports() -> list[dict]:
    nodes = sorted({n for pattern in SERIAL_GLOBS for n in glob.glob(pattern)})
    held = _holders(nodes)
    return [{"device": n, "held_by": ("7Sigma agent" if _held_by_me(n) else held.get(n, ""))}
            for n in nodes]


# ---------------------------------------------------------------------------
# Starting LightBurn, so the operator starts one thing and not two.
# ---------------------------------------------------------------------------

# Its bundle id rather than its name: a renamed or relocated copy still opens,
# and Launch Services finds it wherever it is installed.
LIGHTBURN_BUNDLE = "com.LightBurnSoftware.LightBurn"
LIGHTBURN_WAIT_S = 40


def ensure_lightburn(agent: "Agent") -> None:
    """Open LightBurn if it is not already answering, and wait for it.

    Only when it is SILENT: opening an app that is already running would pull
    its window in front of whatever the operator is doing. Only on this machine
    — with `--host-lightburn` pointing elsewhere there is nothing here to start.

    It reports what happened either way. The failure that costs an afternoon is
    LightBurn running but not answering, and "I tried to start it and it still
    will not talk" is the sentence that sends someone to look at the title bar.
    """
    if sys.platform != "darwin" or agent.lb_host not in ("127.0.0.1", "localhost", "::1"):
        return
    if agent.health().get("responsive"):
        say("LightBurn is already answering")
        return
    say("LightBurn is not answering — opening it")
    agent.session_profile = None  # a fresh LightBurn connects whatever profile it opens with
    r = subprocess.run(["open", "-b", LIGHTBURN_BUNDLE], capture_output=True, text=True)
    if r.returncode:
        say(f"could not open LightBurn: {r.stderr.strip() or 'not installed?'}")
        return
    for _ in range(LIGHTBURN_WAIT_S):
        time.sleep(1)
        if agent.health().get("responsive"):
            say("LightBurn is up and answering")
            return
    say(f"LightBurn did not answer within {LIGHTBURN_WAIT_S}s — look for a dialog waiting for a "
        "click, and check the title bar says Pro (Core cannot drive a galvo)")


# ---------------------------------------------------------------------------
# Browser setup, so one download is the whole bench.
# ---------------------------------------------------------------------------

# The USB bridges a bench actually has. A serial permission is DEVICE-scoped in
# Chrome, and these report no USB serial number, so without a standing grant the
# operator picks a port for every unit.
BENCH_BRIDGES = [
    {"vendor_id": 0x1A86, "product_id": 0x7523},  # CH340, the V2 dongle
    {"vendor_id": 0x303A, "product_id": 0x1001},  # Espressif USB-Serial/JTAG
]
CHROME_DOMAIN = "com.google.Chrome"
SERIAL_KEY = "SerialAllowUsbDevicesForUrls"
LOOPBACK_KEY = "LoopbackNetworkAccessAllowedForUrls"


def _defaults_read(domain: str) -> dict:
    out = subprocess.run(["defaults", "export", domain, "-"],
                         capture_output=True).stdout
    try:
        return plistlib.loads(out) if out.strip() else {}
    except Exception:
        return {}


def _defaults_write(domain: str, key: str, value) -> bool:
    r = subprocess.run(["defaults", "write", domain, key, plistlib.dumps(value).decode()],
                       capture_output=True, text=True)
    if r.returncode:
        print(f"  could not set {key}: {r.stderr.strip()}", file=sys.stderr)
    return r.returncode == 0


def chrome_policy_state(origins: "set[str]") -> "tuple[bool, str]":
    """Whether Chrome already carries both grants for the origins we serve.

    Read back rather than remembered: a profile, another tool or the operator
    may have changed it since, and a window that reports what it DID rather
    than what IS true is the kind of status nobody should trust.
    """
    if sys.platform != "darwin":
        return False, "only macOS is automated"

    def missing_in(policy: dict) -> list:
        serial = policy.get(SERIAL_KEY) or []
        loopback = policy.get(LOOPBACK_KEY) or []
        out = []
        for origin in sorted(origins):
            has_serial = any(origin in (r.get("urls") or []) for r in serial if isinstance(r, dict))
            if not (has_serial and origin in loopback):
                out.append(origin)
        return out

    # A managed profile OUTRANKS the user domain, so it is what Chrome actually
    # obeys when one is installed — measured 2026-09-17 on a bench that had
    # both: the agent's grant was correct and Chrome never read it.
    managed = _managed_chrome()
    if managed:
        lacking = missing_in(managed)
        if not lacking:
            return True, "granted by a managed profile (it overrides this agent's own grant)"
        return False, ("Chrome is managed by a profile that lacks " + ", ".join(lacking)
                       + " — this agent's grant is overridden; the administrator has to install it")
    lacking = missing_in(_defaults_read(CHROME_DOMAIN))
    if lacking:
        return False, "missing for " + ", ".join(lacking)
    return True, "serial ports and loopback granted"


def _managed_chrome() -> dict:
    """Chrome policy from /Library/Managed Preferences, user then machine, or {}.

    Readable without root (they are 0644); only writing needs an administrator.
    """
    import os
    merged: dict = {}
    for path in (Path("/Library/Managed Preferences") / os.environ.get("USER", "") / "com.google.Chrome.plist",
                 Path("/Library/Managed Preferences/com.google.Chrome.plist")):
        try:
            with open(path, "rb") as f:
                for k, v in plistlib.load(f).items():
                    merged.setdefault(k, v)
        except (OSError, ValueError):
            continue
    return merged


def install_chrome_policy(origin: str) -> None:
    """Grant this bench the two things a page cannot ask for itself.

    NO ADMINISTRATOR RIGHTS. Chrome on macOS reads policy from the user's own
    `com.google.Chrome` domain as well as from /Library/Managed Preferences, and
    only the second needs root. A profile installed there still wins, so a
    machine already carrying the bench profile is unaffected by this.

    Both grants exist because a web page CANNOT ask for them:

      * serial permission is device-scoped, and the bench bridges report no USB
        serial number, so Chrome forgets the port on every replug;
      * a page on a public origin reaching 127.0.0.1 is blocked by Local Network
        Access, which fails with ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS
        rather than a timeout.

    Existing entries are MERGED, never replaced: another bench origin already in
    the list keeps working.
    """
    if sys.platform != "darwin":
        say("browser setup: only macOS is automated — allow local network access "
            "when Chrome asks")
        return
    current = _defaults_read(CHROME_DOMAIN)
    changed = []

    rules = list(current.get(SERIAL_KEY) or [])
    if not any(origin in (r.get("urls") or []) for r in rules if isinstance(r, dict)):
        rules.append({"devices": BENCH_BRIDGES, "urls": [origin]})
        if _defaults_write(CHROME_DOMAIN, SERIAL_KEY, rules):
            changed.append("serial ports")

    loopback = list(current.get(LOOPBACK_KEY) or [])
    if origin not in loopback:
        loopback.append(origin)
        if _defaults_write(CHROME_DOMAIN, LOOPBACK_KEY, loopback):
            changed.append("local network access")

    if changed:
        say(f"browser setup: granted {origin} {' and '.join(changed)}")
        say("QUIT CHROME COMPLETELY AND REOPEN IT ONCE for this to take effect")
    else:
        say("browser setup: already in place")


def _already_ours(port: int) -> bool:
    """Is the thing holding the port another copy of US?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/hello", timeout=2) as r:
            return json.loads(r.read()).get("agent") == "7sigma-agent"
    except Exception:
        return False


def complain(message: str) -> None:
    """Say something the operator will actually see. A window when there can be
    one, the log and stderr always."""
    say(message.replace("\n\n", " "))
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("7Sigma agent", message)
        root.destroy()
    except Exception:
        pass


def bench_facts(agent: "Agent", port: int) -> "list[tuple[str, str, str]]":
    """(name, state, detail) for each thing that has to be true for a mark to
    happen — this program, LightBurn, the printer, Chrome, the bench page. Each
    is fixed in a different place, so each is its own line. Shared by the window
    and by the status page, so the two never disagree."""
    out = [("Listening", "ok", f"127.0.0.1:{port} — this machine only, nothing on the network")]

    if not agent.probing and time.time() - agent.last_health_at > 4:
        agent.probing = True

        def probe() -> None:
            try:
                agent.health()
            finally:
                agent.probing = False
        threading.Thread(target=probe, daemon=True).start()
    h = agent.last_health
    if not h:
        out.append(("LightBurn", "dim", "asking…"))
    elif h.get("responsive"):
        out.append(("LightBurn", "ok",
                    "answering" + (" — a job is running" if h.get("busy") else "")
                    + (f" — profile {agent.session_profile}" if agent.session_profile else "")))
    else:
        out.append(("LightBurn", "bad", "not answering. It is not started, a dialog is "
                                        "waiting for a click, or the licence is Core — "
                                        "Core cannot drive a galvo."))

    out.append(("Programming", "ok" if agent.esptool_version else "warn",
                f"esptool {agent.esptool_version} ready" if agent.esptool_version
                else "no esptool — vendor.zip missing beside the agent"))

    usb = laser_usb()
    if usb["present"] is None:
        out.append(("Laser", "dim", "cannot see the USB bus on this system"))
    elif usb["present"]:
        out.append(("Laser", "ok", f"{usb['name']} on USB ({usb['ids']})"))
    else:
        out.append(("Laser", "bad", "no laser board on USB — is the marker powered on and plugged in?"))

    printers = list_printers()
    if not printers:
        out.append(("Printer", "warn", "none on this machine — add one in System Settings"))
    else:
        first = [p for p in printers if p.get("default")] or printers
        p = first[0]
        out.append(("Printer", "ok" if p["ok"] else "bad",
                    f"{p['queue']} ready" if p["ok"] else
                    f"{p['queue']}: {p['reasons']} — "
                    + PRINTER_ADVICE.get(p["reasons"], "check it")))

    ok, detail = chrome_policy_state(agent.setup_origins)
    out.append(("Chrome", "ok" if ok else "warn",
                detail if ok else f"{detail}. Quit Chrome completely and reopen it."))

    seen = time.time() - agent.last_page_at
    if not agent.last_page_at:
        out.append(("Bench page", "warn", "none has connected yet — open the bench in Chrome"))
    elif seen < 15:
        out.append(("Bench page", "ok", f"connected, last heard {int(seen)}s ago"))
    else:
        out.append(("Bench page", "warn", f"last heard {int(seen)}s ago — it may be closed"))
    return out


MARK = {"ok": "\u2713", "warn": "!", "bad": "\u2717", "dim": "\u2026"}


def status_page(agent: "Agent", port: int) -> bytes:
    """The status as an HTML page: every fact, and the log under it.

    This is where the TEXT lives, because the window cannot draw any (see
    run_window). Server-rendered and refreshed by a meta tag, so it needs no
    script, no fetch, and therefore no Origin allow-list entry — a browser
    navigation carries no Origin, and that is already allowed."""
    import html
    rows = "".join(
        f'<tr class="{state}"><td>{MARK[state]}</td><th>{html.escape(name)}</th>'
        f'<td>{html.escape(detail)}</td></tr>'
        for name, state, detail in bench_facts(agent, port))
    log = html.escape("\n".join(list(LOG_LINES)[-300:]))
    return f"""<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="2">
<title>7Sigma agent</title>
<style>
 :root{{color-scheme:light dark}} body{{font:14px/1.5 -apple-system,Helvetica,sans-serif;margin:24px;max-width:900px}}
 h1{{font-size:20px;margin:0 0 4px}} p{{color:#888;margin:0 0 16px}}
 table{{border-collapse:collapse;margin-bottom:20px}} td,th{{padding:4px 10px 4px 0;text-align:left;vertical-align:top}}
 th{{font-family:Menlo,monospace;white-space:nowrap}} tr.ok td:first-child{{color:#1a7f37}} tr.warn td:first-child{{color:#9a6700}}
 tr.bad td:first-child{{color:#b42318}} tr.warn td:last-child{{color:#9a6700}} tr.bad td:last-child{{color:#b42318}}
 pre{{font:12px/1.4 Menlo,monospace;background:rgba(127,127,127,.12);padding:12px;border-radius:6px;white-space:pre-wrap}}
 @media (prefers-color-scheme:dark){{tr.ok td:first-child{{color:#4ac26b}} tr.warn td:first-child,tr.warn td:last-child{{color:#e3b341}} tr.bad td:first-child,tr.bad td:last-child{{color:#f85149}}}}
</style>
<h1>7Sigma agent</h1><p>Leave the agent window open while you work. Closing it stops the agent. This page refreshes itself.</p>
<table>{rows}</table>
<pre>{log}</pre>""".encode("utf-8")


def run_window(agent: "Agent", port: int) -> None:
    """A window that answers "is this bench ready?" without being asked.

    IT IS BUILT ONLY FROM NATIVE CONTROLS, AND ITS TEXT IS ELSEWHERE. Measured
    on 2026-09-17 with the Tk that macOS's own Python carries (Tk 8.5, on
    macOS 26): tk.Label, tk.Text, tk.Canvas, tk.Listbox, tk.Message and every
    ttk widget occupy their space and paint NO text — a window built from them
    is blank, in dark and light mode alike. Only the controls Tk hands to the
    OS draw their label: tk.Button, Checkbutton, Radiobutton, Menubutton, and
    the window title. And those draw ONE line each. So:

      * each fact is one flat button with a one-line summary, and clicking it
        opens the status page in the browser, where the full text and the log
        are — `status_page` above renders them, from the same `bench_facts`;
      * the window TITLE carries the verdict, because it is the one piece of
        text that is always visible, in the Dock and in Cmd-Tab too.

    A Text widget was tried first (it came out blank), then explicit colours on
    every Label (blank). Do not go back to either without a screenshot.

    tkinter, because it is in the standard library and macOS's own Python has
    it — the whole point of this file is that it installs nothing. The server
    runs in its thread; Tk owns the main one, and nothing touches a widget from
    anywhere else.
    """
    import tkinter as tk

    root = tk.Tk()
    root.title("7Sigma agent")
    root.geometry("560x360")
    url = f"http://127.0.0.1:{port}/"

    def open_status() -> None:
        subprocess.run(["open", url], capture_output=True)

    def open_log() -> None:
        subprocess.run(["open", str(LOG_PATH)], capture_output=True)

    rows: "list[tk.Button]" = []
    for _ in range(7):
        b = tk.Button(root, text="", relief="flat", anchor="w", command=open_status)
        b.pack(fill="x", padx=14, pady=1)
        rows.append(b)

    foot = tk.Frame(root)
    foot.pack(fill="x", side="bottom", padx=14, pady=12)
    tk.Button(foot, text="Quit", command=root.destroy).pack(side="right")
    tk.Button(foot, text="Open the log", command=open_log).pack(side="left")
    tk.Button(foot, text="Show details in the browser", command=open_status).pack(side="left", padx=8)

    def tick() -> None:
        facts = bench_facts(agent, port)
        for b, (name, state, detail) in zip(rows, facts):
            # One line: a native button clips at the first newline and at its width.
            b.configure(text=f"{MARK[state]}  {name}:  {detail}"[:90],
                        state="disabled" if state == "dim" else "normal")
        bad = [n for n, s, _ in facts if s == "bad"]
        warn = [n for n, s, _ in facts if s == "warn"]
        verdict = ("ready" if not bad and not warn else
                   f"{', '.join(bad)} not working" if bad else f"check {', '.join(warn)}")
        root.title(f"7Sigma agent — {verdict}")
        root.after(1000, tick)

    tick()
    root.mainloop()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--origin", action="append", default=[],
                    help="an extra allowed page origin (repeatable)")
    ap.add_argument("--host-lightburn", default="127.0.0.1",
                    help="where LightBurn runs (default: this machine)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--job-dir", type=Path, default=None,
                    help="where patched jobs are written (default: a temp dir)")
    ap.add_argument("--no-browser-setup", action="store_true",
                    help="do not touch Chrome's policy for this bench")
    ap.add_argument("--terminal", action="store_true",
                    help="no window: run in this terminal and log to it")
    ap.add_argument("--no-open-lightburn", action="store_true",
                    help="do not start LightBurn, only talk to it")
    args = ap.parse_args()

    job_dir = args.job_dir or Path(tempfile.gettempdir()) / "7sigma-marking"
    job_dir.mkdir(parents=True, exist_ok=True)
    agent = Agent(set(DEFAULT_ORIGINS) | set(args.origin), args.host_lightburn, job_dir)

    handler = type("BoundHandler", (Handler,), {"agent": agent})
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as exc:
        # The commonest way this program fails, and it used to fail SILENTLY:
        # launched from the app there is no terminal, so a second copy just
        # vanished on start. Say which it is, on screen if we can.
        mine = _already_ours(args.port)
        if mine:
            complain(f"The 7Sigma agent is already running on port {args.port}.\n\n"
                     "Look for its window, or quit it and open this one again.")
        else:
            complain(f"Port {args.port} is already in use by something else, so the agent "
                     f"cannot start.\n\n{exc}")
        return 1
    say(f"7Sigma agent on http://127.0.0.1:{args.port}")
    say(f"LightBurn at {args.host_lightburn}")
    say(f"jobs in {job_dir}")
    say(f"serving {', '.join(sorted(agent.origins))}")
    agent.setup_origins = set(args.origin) or set(DEFAULT_ORIGINS)
    agent.esptool_version = import_vendor()
    say(f"esptool: {agent.esptool_version or 'unavailable'} (programming through the agent)")
    if not args.no_browser_setup:
        for origin in sorted(agent.setup_origins):
            install_chrome_policy(origin)

    # In the background: the window must appear at once, and LightBurn takes
    # seconds to come up.
    if not args.no_open_lightburn:
        threading.Thread(target=ensure_lightburn, args=(agent,), daemon=True).start()

    if args.terminal:
        say("leave this window open while you mark")
        server.serve_forever()
        return 0
    # A window, with the server behind it. Closing the window ends the process,
    # which is what an operator means by closing it.
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        run_window(agent, args.port)
    except Exception as exc:  # no display, or no Tk: fall back rather than die
        say(f"no window ({exc}) — running in this terminal instead")
        server.serve_forever()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
        sys.exit(0)
