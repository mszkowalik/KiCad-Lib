#!/usr/bin/env python3
"""One live simulation, in its own process.

`libngspice` keeps ONE circuit per process, so a session that runs endlessly
and can be poked at while it runs has to be a process of its own. The render
service spawns one of these per viewer and speaks length-prefixed frames to it
over stdin/stdout.

The loop is Falstad's, verified against his source (docs/simulator/design.md
§2.5): solve at full speed on the simulation thread, but let only two things
leave it — the LATEST state of everything the overlay draws, and a min/max
envelope per scope column. A transient at 1 us resolution produces about
95,000 points a second; a browser needs sixty frames of a few hundred bytes.
Everything else is folded away here rather than shipped and thrown out there.

Protocol, both directions: uint32 length, then the payload. A payload starting
with `{` is JSON; one starting with \\x01 is a data frame:

    \\x01 | float64 sim_t | float32 * len(overlay) | uint16 n_cols
         | { uint16 scope index | float32 min | float32 max } * n_cols

Commands in: start, speed, alter, halt, resume, stop.
Events out: ready, error, rate, stopped.
"""
from __future__ import annotations

import ctypes as C
import json
import os
import re
import struct
from collections import deque
import sys
import threading
import time

# ---------------------------------------------------------------- ngspice

class VecValues(C.Structure):
    _fields_ = [("name", C.c_char_p), ("creal", C.c_double), ("cimag", C.c_double),
                ("is_scale", C.c_bool), ("is_complex", C.c_bool)]


class VecValuesAll(C.Structure):
    _fields_ = [("veccount", C.c_int), ("vecindex", C.c_int),
                ("vecsa", C.POINTER(C.POINTER(VecValues)))]


class VecInfo(C.Structure):
    _fields_ = [("number", C.c_int), ("vecname", C.c_char_p), ("is_real", C.c_bool),
                ("pdvec", C.c_void_p), ("pdvecscale", C.c_void_p)]


class VecInfoAll(C.Structure):
    _fields_ = [("name", C.c_char_p), ("title", C.c_char_p), ("date", C.c_char_p),
                ("type", C.c_char_p), ("veccount", C.c_int),
                ("vecs", C.POINTER(C.POINTER(VecInfo)))]


SENDCHAR = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
SENDSTAT = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
EXITCB = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)
SENDDATA = C.CFUNCTYPE(C.c_int, C.POINTER(VecValuesAll), C.c_int, C.c_int, C.c_void_p)
SENDINIT = C.CFUNCTYPE(C.c_int, C.POINTER(VecInfoAll), C.c_int, C.c_void_p)
BGRUN = C.CFUNCTYPE(C.c_int, C.c_bool, C.c_int, C.c_void_p)

# Where the shared library lives. The Debian package installs the SONAME;
# Homebrew installs a dylib. Both are the same API.
LIB_CANDIDATES = (
    os.environ.get("LIBNGSPICE", ""),
    "libngspice.so.0", "libngspice.so",
    "/opt/homebrew/lib/libngspice.dylib", "/usr/local/lib/libngspice.dylib",
)

# How often a frame goes out.
FRAME_S = 1.0 / 30.0
# How many history columns each overlay vector keeps — one scope width. The
# run has been solving since the session opened, and a trace opened five
# seconds in deserves those five seconds: without history a fresh scope is
# empty until the window rolls past, which reads as a plot taking seconds to
# load. ~400 vectors x 600 columns is a couple of megabytes.
HISTORY_COLS = 600


def resolve(name: str, index: dict[str, int]) -> str:
    """A vector name as THIS run spells it.

    A live run names its vectors bare — `/lowpass`, `@r1[i]` — while a
    rawfile from a batch run wraps them, `v(/lowpass)`, `i(@r1[i])`. The rest
    of the platform speaks the wrapped form because that is what a finished
    run returns, so the wrapper is peeled here rather than in four callers.

    Currents have a third spelling: a SOURCE's branch is `v1#branch` in a
    live run where a batch rawfile says `i(v1)`, and `i(r2)` in a batch is
    `@r2[i]` live (savecurrents). Every request for a current therefore
    tries all three. Missing this left every source current — and every
    wire/pin probe built on one — silently unresolved in live mode: no
    error, just a scope that closed no columns and fell back to a 30 Hz
    reconstruction while the voltage beside it ran at full rate.
    """
    low = name.strip().lower()
    if low in index:
        return low
    if len(low) > 3 and low[1] == "(" and low.endswith(")"):
        inner = low[2:-1]
        for candidate in (inner, f"{inner}#branch", f"@{inner}[i]"):
            if candidate in index:
                return candidate
        if low.startswith("i(") and inner.startswith("@") and inner.endswith("[i]"):
            bare = inner[1:-3]
            if f"{bare}#branch" in index:
                return f"{bare}#branch"
        return inner if inner else low
    # A BARE name that is not a vector may still be a device: scopes given in
    # the START frame are resolved once against an empty index (the run has
    # not initialised yet) and once again in on_init — by then the wrapper is
    # already peeled, so the second pass sees `r2` and must reach `@r2[i]`
    # the same way it would have from `i(r2)`. Measured: without this, a
    # terms-scope opened at start closed 0 columns while one opened mid-run
    # worked.
    for candidate in (f"@{low}[i]", f"{low}#branch"):
        if candidate in index:
            return candidate
    return low


def load_library() -> C.CDLL:
    errors = []
    for name in LIB_CANDIDATES:
        if not name:
            continue
        try:
            return C.CDLL(name)
        except OSError as e:
            errors.append(f"{name}: {e}")
    raise RuntimeError("cannot load libngspice — " + "; ".join(errors))


# ------------------------------------------------------------------ frames

def write_frame(payload: bytes) -> None:
    out = sys.stdout.buffer
    out.write(struct.pack("<I", len(payload)))
    out.write(payload)
    out.flush()


def send_event(**event) -> None:
    write_frame(json.dumps(event, separators=(",", ":")).encode("utf-8"))


def read_frames():
    """Yield decoded JSON commands from stdin until it closes."""
    inp = sys.stdin.buffer
    while True:
        head = inp.read(4)
        if len(head) < 4:
            return
        (length,) = struct.unpack("<I", head)
        body = inp.read(length)
        if len(body) < length:
            return
        try:
            yield json.loads(body.decode("utf-8"))
        except ValueError:
            continue


# ------------------------------------------------------------------ session

class Session:
    def __init__(self, config: dict):
        self.lib = load_library()
        self.netlist: str = config["netlist"]
        self.overlay: list[str] = [v.lower() for v in config.get("overlay", [])]
        # Before set_scopes: it resolves names against `index` and stamps the
        # first column edge from `sim_t`, so both have to exist by then.
        self.index: dict[str, int] = {}
        self.sim_t = 0.0
        self.lock = threading.Lock()
        self.set_scopes(config.get("scopes", []))
        # Simulated seconds per wall-clock second. The exponential speed
        # slider lives in the UI; this end just holds the rate it asks for.
        self.speed: float = float(config.get("speed", 1e-3)) or 1e-3
        self.running = True
        self.stopping = False

        self.snapshot: list[float] = [0.0] * len(self.overlay)
        # The WHOLE latest data point, not just the overlay subset. A reload
        # reads capacitor voltages and inductor currents out of it — the
        # worker is the one holding the numbers when the circuit is swapped.
        self.last: dict[str, float] = {}
        # ngspice's own words, kept so a dying run can say why. stderr in
        # spirit; libngspice speaks only through this callback.
        self.out_ring: deque[str] = deque(maxlen=30)
        # The abort watchdog: one report per arming. Armed by bg_run (start,
        # reload, resume), disarmed while the HALT is deliberate — the user's
        # Hold, an alter's pause, a reload's swap.
        self.watch_armed = False
        self.deliberate_halt = False
        # Rolling min/max history per overlay vector, all the time, so a scope
        # opened late starts FULL. Span comes from the browser (it is the
        # scope pixel pitch, which depends on the speed knob); zero = off.
        self.hist_span = float(config.get("history_span", 0) or 0)
        self.trackers: dict[str, dict] = {}
        # Simulated time is continuous across reloads: each new transient
        # starts its own clock at zero, and the offset keeps the stream's
        # clock from jumping backwards under the scopes.
        self.t_offset = 0.0
        self.raw_t = 0.0
        self.points = 0
        self.started = time.monotonic()
        self.last_frame = 0.0
        self.last_rate_report = 0.0
        self.points_at_report = 0

        self._callbacks = ()  # ctypes frees these if nothing holds them

    def set_scopes(self, scopes: list[dict], history_span: float | None = None) -> None:
        with self.lock:
            self._set_scopes_locked(scopes, history_span)

    def _set_scopes_locked(self, scopes: list[dict], history_span: float | None) -> None:
        if history_span is not None and history_span > 0 and history_span != self.hist_span:
            # A new pixel pitch (the speed knob moved): old history is at the
            # wrong timebase, so it starts over.
            self.hist_span = history_span
            self.trackers = {name: self._tracker()
                             for name in self.overlay if name in self.index}
        self.scopes = [
            {
                # RESOLVE here, not only in on_init. A frame is keyed by the
                # run's own bare names (`/in`) while the rest of the platform
                # speaks the wrapped form (`v(/in)`), so an unresolved name
                # matches nothing and the scope closes no columns at all — no
                # error, just an empty plot. Scopes given at START are resolved
                # again in on_init, once the vector list exists; ones set LATER,
                # when the user opens a trace mid-run, are resolved here and
                # nowhere else.
                "vec": resolve(str(s.get("vec", "")).lower(), self.index),
                # A scope may watch a weighted SUM of vectors instead of one.
                # The current in a WIRE, or in a terminal of a part with more
                # than two legs, is not a vector ngspice has — it is a fixed
                # linear combination of device branch currents, worked out from
                # the topology in the browser. Sending the combination rather
                # than the answer is what lets such a probe be closed at the
                # solver's own rate: reconstructing it a frame at a time
                # instead draws a staircase beside a smooth voltage on the
                # very same net.
                "terms": [
                    (resolve(str(t.get("vec", "")).lower(), self.index), float(t.get("coeff", 0)))
                    for t in (s.get("terms") or [])
                ],
                "span": float(s.get("sim_s_per_px", 0)) or 0.0,
                "min": float("inf"),
                "max": float("-inf"),
                # A scope opened mid-run starts from where the run has got to.
                "next_edge": self.sim_t,
                "closed": [],
            }
            for s in scopes
        ]
        # Seed a NEW scope from history, so it opens FULL instead of empty.
        # `backlog` is the browser saying "I hold no columns for this one" —
        # re-sent scope lists (a speed change, a merge) keep their columns
        # browser-side and must not receive them twice.
        #
        # A terms scope (a wire or a pin probe: a weighted sum of device
        # currents) is seeded by INTERVAL ARITHMETIC over its components'
        # rings: a positive coefficient maps lo->lo, a negative one swaps
        # them. That is conservative — the true envelope of a sum can be
        # narrower — but a column is microseconds of simulated time, the
        # components move together at that scale, and an envelope a hair wide
        # beats a current pane that arrives one window later than the voltage
        # beside it (which is exactly how this looked without it). The rings
        # share one edge grid, so aligning them from the newest end is exact.
        for scope, spec in zip(self.scopes, scopes):
            if not spec.get("backlog") or scope["span"] != self.hist_span:
                continue
            if scope["terms"]:
                rings = []
                for name, coeff in scope["terms"]:
                    tr = self.trackers.get(name)
                    if tr is None:
                        rings = None
                        break
                    rings.append((coeff, list(tr["ring"])))
                if not rings:
                    continue
                n = min(len(r) for _, r in rings)
                edge = max(self.trackers[name]["next_edge"] for name, _ in scope["terms"])
                combined = []
                for i in range(-n, 0):
                    lo = hi = 0.0
                    for coeff, ring in rings:
                        a, b = ring[i]
                        lo += coeff * (a if coeff > 0 else b)
                        hi += coeff * (b if coeff > 0 else a)
                    combined.append((lo, hi))
                scope["closed"].extend(combined)
                scope["next_edge"] = edge
                continue
            tr = self.trackers.get(scope["vec"])
            if tr is None:
                continue
            scope["closed"].extend(tr["ring"])
            scope["min"] = tr["min"]
            scope["max"] = tr["max"]
            scope["next_edge"] = tr["next_edge"]

    # -------------------------------------------------------------- fold

    def on_init(self, info, ident, user) -> int:
        names = []
        for i in range(info.contents.veccount):
            names.append(info.contents.vecs[i].contents.vecname.decode().lower())
        self.index = {name: i for i, name in enumerate(names)}
        self.overlay = [resolve(v, self.index) for v in self.overlay]
        for scope in self.scopes:
            scope["vec"] = resolve(scope["vec"], self.index)
            scope["terms"] = [(resolve(n, self.index), c) for n, c in scope["terms"]]
        if self.hist_span > 0:
            kept = self.trackers
            self.trackers = {
                name: kept.get(name) or self._tracker()
                for name in self.overlay if name in self.index
            }
        send_event(ev="ready", vectors=names,
                   missing=[v for v in self.overlay if v not in self.index])
        return 0

    def _tracker(self) -> dict:
        return {"min": float("inf"), "max": float("-inf"),
                "next_edge": self.sim_t, "ring": deque(maxlen=HISTORY_COLS)}

    def on_data(self, all_, count, ident, user) -> int:
        row = all_.contents
        values = {}
        for i in range(row.veccount):
            vec = row.vecsa[i].contents
            values[vec.name.decode().lower()] = vec.creal
        self.last = values
        self.raw_t = values.get("time", self.raw_t)
        now_sim = self.raw_t + self.t_offset
        self.sim_t = now_sim
        self.points += 1

        with self.lock:
            for i, name in enumerate(self.overlay):
                if name in values:
                    self.snapshot[i] = values[name]
            for scope in self.scopes:
                if scope["terms"]:
                    v = 0.0
                    missing = False
                    for name, coeff in scope["terms"]:
                        term = values.get(name)
                        if term is None:
                            missing = True
                            break
                        v += coeff * term
                    if missing:
                        continue
                else:
                    v = values.get(scope["vec"])
                if v is None:
                    continue
                if v < scope["min"]:
                    scope["min"] = v
                if v > scope["max"]:
                    scope["max"] = v
                if scope["span"] <= 0:
                    continue
                # A jump bigger than any window means the anchor is stale
                # (a scope carried across a reload) — re-anchor instead of
                # closing a million empty columns.
                if now_sim - scope["next_edge"] > scope["span"] * 2000:
                    scope["next_edge"] = now_sim
                # EVERY edge the data point crossed closes a column — a
                # column per pixel of simulated time, not a column per data
                # point. When the solver's step is larger than a pixel the
                # extra columns repeat the last value, which is what a scope
                # showing a signal slower than its beam has always drawn.
                # Closing at most one per point made the window fill at the
                # point rate (measured: 113 of the 150 columns/s the window
                # needs), so every plot crept and any two plots fed by
                # different paths crept DIFFERENTLY.
                while now_sim >= scope["next_edge"]:
                    lo = scope["min"] if scope["min"] != float("inf") else v
                    hi = scope["max"] if scope["max"] != float("-inf") else v
                    scope["closed"].append((lo, hi))
                    scope["next_edge"] += scope["span"]
                    scope["min"] = v
                    scope["max"] = v

            if self.hist_span > 0:
                for name, tr in self.trackers.items():
                    hv = values.get(name)
                    if hv is None:
                        continue
                    if hv < tr["min"]:
                        tr["min"] = hv
                    if hv > tr["max"]:
                        tr["max"] = hv
                    if now_sim - tr["next_edge"] > self.hist_span * 2000:
                        tr["next_edge"] = now_sim
                    while now_sim >= tr["next_edge"]:
                        lo = tr["min"] if tr["min"] != float("inf") else hv
                        hi = tr["max"] if tr["max"] != float("-inf") else hv
                        tr["ring"].append((lo, hi))
                        tr["next_edge"] += self.hist_span
                        tr["min"] = hv
                        tr["max"] = hv

        wall = time.monotonic()
        if wall - self.last_frame >= FRAME_S:
            self.last_frame = wall
            self.emit()

        # Pacing. Sleeping HERE is the throttle: this callback runs on
        # ngspice's own simulation thread, so holding it back holds the solver
        # back, and the run keeps pace with the wall clock instead of racing
        # minutes ahead of the picture.
        if self.speed > 0:
            target = self.started + now_sim / self.speed
            ahead = target - wall
            if ahead > 0:
                time.sleep(min(ahead, 0.05))
        return 0

    def emit(self) -> None:
        with self.lock:
            body = bytearray(b"\x02")
            body += struct.pack("<d", self.sim_t)
            body += struct.pack("<H", len(self.snapshot))
            body += struct.pack(f"<{len(self.snapshot)}f", *self.snapshot)
            columns = []
            for i, scope in enumerate(self.scopes):
                for lo, hi in scope["closed"]:
                    columns.append((i, lo, hi))
                scope["closed"].clear()
            body += struct.pack("<H", len(columns))
            for i, lo, hi in columns:
                body += struct.pack("<Hff", i, lo, hi)
        write_frame(bytes(body))

        wall = time.monotonic()
        if wall - self.last_rate_report >= 1.0:
            done = self.points - self.points_at_report
            self.last_rate_report = wall
            self.points_at_report = self.points
            send_event(ev="rate", sim_t=self.sim_t, points_per_s=done,
                       sim_s_per_s=self.speed)

    # -------------------------------------------------------------- drive

    def _on_char(self, text, ident, user) -> int:
        try:
            line = text.decode(errors="replace")
        except Exception:  # noqa: BLE001
            return 0
        if line.startswith("stdout "):
            line = line[7:]
        elif line.startswith("stderr "):
            line = line[7:]
        if line.strip():
            self.out_ring.append(line.strip())
        return 0

    def _watchdog(self) -> None:
        """A transient that dies must SAY SO. ngspice aborts a background run
        (timestep too small, matrix singular) without any callback the worker
        listens to — the frames just stop, and the page sits at RUNNING
        forever. This thread turns that silence into an error event carrying
        ngspice's own last words."""
        while not self.stopping:
            time.sleep(0.3)
            if not self.watch_armed or self.deliberate_halt or self.stopping:
                continue
            if self.is_running():
                continue
            # Confirm — bg_run's thread can be between restarts for a moment.
            time.sleep(0.2)
            if self.is_running() or self.deliberate_halt or self.stopping:
                continue
            self.watch_armed = False
            tail = [l for l in self.out_ring
                    if "error" in l.lower() or "too small" in l.lower()
                    or "singular" in l.lower() or "aborted" in l.lower()
                    or "convergence" in l.lower()] or list(self.out_ring)[-3:]
            send_event(ev="error",
                       message="the simulation stopped at t = %.6g s — %s"
                               % (self.sim_t, "; ".join(tail[-3:]) or "ngspice gave no reason"))

    def start(self) -> None:
        noop_char = SENDCHAR(self._on_char)
        noop_stat = SENDSTAT(lambda s, i, u: 0)
        exit_cb = EXITCB(self._on_exit)
        data_cb = SENDDATA(self.on_data)
        init_cb = SENDINIT(self.on_init)
        bg_cb = BGRUN(lambda run, i, u: 0)
        self._callbacks = (noop_char, noop_stat, exit_cb, data_cb, init_cb, bg_cb)
        self.lib.ngSpice_Init(noop_char, noop_stat, exit_cb, data_cb, init_cb, bg_cb, None)

        lines = [ln for ln in self.netlist.splitlines() if ln.strip()]
        arr = (C.c_char_p * (len(lines) + 1))(*[ln.encode() for ln in lines], None)
        if self.lib.ngSpice_Circ(arr) != 0:
            send_event(ev="error", message="ngspice refused the netlist")
            return
        self.command("bg_run")
        self.watch_armed = True
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _on_exit(self, status, immediate, quit_exit, ident, user) -> int:
        self.running = False
        return 0

    def command(self, text: str) -> None:
        self.lib.ngSpice_Command(text.encode())

    def is_running(self) -> bool:
        try:
            self.lib.ngSpice_running.restype = C.c_bool
            return bool(self.lib.ngSpice_running())
        except AttributeError:
            return True

    def apply_alter(self, text: str) -> None:
        """Change the circuit, then carry on from where the run had got to.

        `alter` on a RUNNING background transient is accepted and does
        nothing: measured, and it is the trap this whole mode turns on. The
        change lands only if the run is halted first — and `bg_resume` then
        continues the same transient rather than restarting it, so the state
        the circuit had reached survives the edit. That is what makes a knob
        feel live: at any watchable speed the pause is shorter than a frame.
        """
        was_running = self.is_running()
        self.deliberate_halt = True
        if was_running:
            self.command("bg_halt")
            deadline = time.monotonic() + 2.0
            while self.is_running() and time.monotonic() < deadline:
                time.sleep(0.01)
        self.command(text)
        if was_running:
            # Re-anchor the pacing clock, or the run tries to make up the
            # time it spent halted by sprinting.
            self.started = time.monotonic() - self.sim_t / (self.speed or 1e9)
            self.command("bg_resume")
        self.deliberate_halt = False

    def reload(self, cmd: dict) -> None:
        """Swap the running circuit for a new one, carrying component state.

        This is the whole of the Falstad feel: edit the drawing, and the run
        continues with the parts remembering what they were doing. The state
        travels on the COMPONENTS — each `%IC_<ref>%` token in the incoming
        netlist is filled with that part's own last reading (a capacitor's
        voltage across its OLD nodes, an inductor's branch current), so a
        charged cap keeps its charge wherever its wires now go. `.tran uic`
        in the netlist makes ngspice start from those instead of re-solving
        an operating point, which is also what Falstad does.
        """
        netlist = str(cmd.get("netlist", ""))
        for st in cmd.get("state", []):
            ref = str(st.get("ref", "")).lower()
            if st.get("kind") == "l":
                val = self.last.get(f"@{ref}[i]", self.last.get(f"i({ref})", 0.0))
            else:
                a = str(st.get("a", "0")).lower()
                b = str(st.get("b", "0")).lower()
                val = (self.last.get(a, 0.0) if a != "0" else 0.0) - (
                    self.last.get(b, 0.0) if b != "0" else 0.0)
            netlist = netlist.replace(f"%IC_{ref}%", f"{val:.9g}")
        # A part that did not exist in the OLD circuit has a token but no
        # state entry — the browser measures state on the run it is replacing.
        # An unfilled token is not SPICE and ngspice refuses the whole
        # netlist, so every leftover reads 0: a new capacitor arrives
        # uncharged, a new inductor without flux. Exactly what adding a part
        # mid-run means.
        netlist = re.sub(r"%IC_[^%]+%", "0", netlist)

        self.deliberate_halt = True
        self.command("bg_halt")
        deadline = time.monotonic() + 2.0
        while self.is_running() and time.monotonic() < deadline:
            time.sleep(0.005)

        with self.lock:
            self.t_offset += self.raw_t
            self.raw_t = 0.0
            if "overlay" in cmd:
                self.overlay = [str(v).lower() for v in cmd.get("overlay", [])]
                self.snapshot = [0.0] * len(self.overlay)
            if "scopes" in cmd:
                self._set_scopes_locked(cmd.get("scopes", []),
                                        float(cmd.get("history_span", 0) or 0) or None)
            else:
                for scope in self.scopes:
                    scope["min"] = float("inf")
                    scope["max"] = float("-inf")
                    scope["next_edge"] = self.sim_t
            self.index = {}

        # Old plots freed, old circuit dropped, new one in. on_init fires
        # again on bg_run and re-resolves the overlay and scope names.
        self.command("destroy all")
        self.command("remcirc")
        lines = [ln for ln in netlist.splitlines() if ln.strip()]
        arr = (C.c_char_p * (len(lines) + 1))(*[ln.encode() for ln in lines], None)
        if self.lib.ngSpice_Circ(arr) != 0:
            send_event(ev="error", message="ngspice refused the edited netlist")
            return
        self.started = time.monotonic() - self.sim_t / (self.speed or 1e9)
        self.command("bg_run")
        self.watch_armed = True
        self.deliberate_halt = False
        send_event(ev="reloaded", sim_t=self.sim_t)

    def stop(self) -> None:
        self.stopping = True
        try:
            self.command("bg_halt")
        except Exception:  # noqa: BLE001 - the library may already be gone
            pass


def main() -> int:
    commands = read_frames()
    try:
        first = next(commands)
    except StopIteration:
        return 0
    if first.get("op") != "start":
        send_event(ev="error", message="the first command must be start")
        return 2
    try:
        session = Session(first)
    except RuntimeError as e:
        send_event(ev="error", message=str(e))
        return 2

    threading.Thread(target=session.start, daemon=True).start()

    for cmd in commands:
        op = cmd.get("op")
        if op == "speed":
            session.speed = max(0.0, float(cmd.get("value", session.speed)))
            # Re-anchor, or a speed change tries to catch up on the past.
            session.started = time.monotonic() - session.sim_t / (session.speed or 1e9)
        elif op == "alter":
            text = str(cmd.get("cmd", "")).strip()
            head = text.split(" ", 1)[0].lower()
            if head in ("alter", "altermod", "set"):
                session.apply_alter(text)
                send_event(ev="altered", cmd=text)
            else:
                send_event(ev="error", message=f"not an alter command: {text[:60]}")
        elif op == "scopes":
            session.set_scopes(cmd.get("scopes", []),
                               float(cmd.get("history_span", 0) or 0) or None)
        elif op == "reload":
            session.reload(cmd)
        elif op == "halt":
            session.deliberate_halt = True
            session.command("bg_halt")
        elif op == "resume":
            session.started = time.monotonic() - session.sim_t / (session.speed or 1e9)
            session.command("bg_resume")
            session.watch_armed = True
            session.deliberate_halt = False
        elif op == "stop":
            break
    session.stop()
    send_event(ev="stopped", sim_t=session.sim_t, points=session.points)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
