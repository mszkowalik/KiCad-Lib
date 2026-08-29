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
import struct
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


def resolve(name: str, index: dict[str, int]) -> str:
    """A vector name as THIS run spells it.

    A live run names its vectors bare — `/lowpass`, `@r1[i]` — while a
    rawfile from a batch run wraps them, `v(/lowpass)`, `i(@r1[i])`. The rest
    of the platform speaks the wrapped form because that is what a finished
    run returns, so the wrapper is peeled here rather than in four callers.
    """
    low = name.strip().lower()
    if low in index:
        return low
    if len(low) > 3 and low[1] == "(" and low.endswith(")"):
        inner = low[2:-1]
        if inner in index:
            return inner
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
        self.set_scopes(config.get("scopes", []))
        # Simulated seconds per wall-clock second. The exponential speed
        # slider lives in the UI; this end just holds the rate it asks for.
        self.speed: float = float(config.get("speed", 1e-3)) or 1e-3
        self.running = True
        self.stopping = False

        self.index: dict[str, int] = {}
        self.snapshot: list[float] = [0.0] * len(self.overlay)
        self.sim_t = 0.0
        self.points = 0
        self.started = time.monotonic()
        self.last_frame = 0.0
        self.last_rate_report = 0.0
        self.points_at_report = 0
        self.lock = threading.Lock()

        self._callbacks = ()  # ctypes frees these if nothing holds them

    def set_scopes(self, scopes: list[dict]) -> None:
        self.scopes = [
            {
                "vec": str(s.get("vec", "")).lower(),
                "span": float(s.get("sim_s_per_px", 0)) or 0.0,
                "min": float("inf"),
                "max": float("-inf"),
                "next_edge": 0.0,
                "closed": [],
            }
            for s in scopes
        ]

    # -------------------------------------------------------------- fold

    def on_init(self, info, ident, user) -> int:
        names = []
        for i in range(info.contents.veccount):
            names.append(info.contents.vecs[i].contents.vecname.decode().lower())
        self.index = {name: i for i, name in enumerate(names)}
        self.overlay = [resolve(v, self.index) for v in self.overlay]
        for scope in self.scopes:
            scope["vec"] = resolve(scope["vec"], self.index)
        send_event(ev="ready", vectors=names,
                   missing=[v for v in self.overlay if v not in self.index])
        return 0

    def on_data(self, all_, count, ident, user) -> int:
        row = all_.contents
        values = {}
        for i in range(row.veccount):
            vec = row.vecsa[i].contents
            values[vec.name.decode().lower()] = vec.creal
        now_sim = values.get("time", self.sim_t)
        self.sim_t = now_sim
        self.points += 1

        with self.lock:
            for i, name in enumerate(self.overlay):
                if name in values:
                    self.snapshot[i] = values[name]
            for scope in self.scopes:
                v = values.get(scope["vec"])
                if v is None:
                    continue
                if v < scope["min"]:
                    scope["min"] = v
                if v > scope["max"]:
                    scope["max"] = v
                if scope["span"] > 0 and now_sim >= scope["next_edge"]:
                    scope["closed"].append((scope["min"], scope["max"]))
                    scope["next_edge"] = now_sim + scope["span"]
                    scope["min"] = float("inf")
                    scope["max"] = float("-inf")

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
            body = bytearray(b"\x01")
            body += struct.pack("<d", self.sim_t)
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

    def start(self) -> None:
        noop_char = SENDCHAR(lambda s, i, u: 0)
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
            session.set_scopes(cmd.get("scopes", []))
        elif op == "halt":
            session.command("bg_halt")
        elif op == "resume":
            session.started = time.monotonic() - session.sim_t / (session.speed or 1e9)
            session.command("bg_resume")
        elif op == "stop":
            break
    session.stop()
    send_event(ev="stopped", sim_t=session.sim_t, points=session.points)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
