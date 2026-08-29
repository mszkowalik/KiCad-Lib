"""SPICE netlist preparation and ngspice rawfile decoding.

This file exists TWICE and the two copies must stay byte-identical: the render
container runs one at render/sim_spice.py, and the API imports the other at
api/app/services/sim_spice.py for its RENDER_MODE=local path. The images
workflow fails the build when they diverge, so edit both in the same change.

Split from project_ops.py because that file is about kicad-cli and this one is
about SPICE: preparing a netlist kicad-cli produced (§prepare_netlist), running
ngspice on it, and turning the rawfile into the compact binary the browser
plots (§encode_payload). No KiCad, no HTTP, no DB — importable from the live
session worker too.

Verified against ngspice-47 and kicad-cli 10.0.5 (docs/simulator/design.md §2).
"""
from __future__ import annotations

import json
import re
import struct
import subprocess
from pathlib import Path

MAGIC = b"7SIM"
FORMAT_VERSION = 1

# Above this many points per vector the payload is bucketed to a min/max
# envelope (same idea as Falstad's scope columns). 50k float32 per vector is
# ~200 kB, which is still comfortable for a dozen traces.
MAX_POINTS = 50_000


class SimError(RuntimeError):
    pass


# ---------------------------------------------------------------- netlist

# A symbol with no sim model netlists as `REF __REF` — KiCad's placeholder for
# "this part has no Sim.Device". ngspice warns and ignores the line, so the
# circuit silently loses the part. We strip them ourselves and report the refs:
# a missing part is a wrong circuit, and the UI has to say so.
_UNMODELLED_RE = re.compile(r"^\s*(\S+)\s+__\1\s*$", re.IGNORECASE)

# Directives that start an analysis. A `.control` block may run its own
# analyses instead; both forms are normal.
_ANALYSIS_RE = re.compile(r"^\s*\.(tran|ac|dc|op|noise|tf|pz|sens|four|disto)\b", re.IGNORECASE)

# Control commands that touch the filesystem or the shell. A scenario block
# comes from a schematic file, which is user content from a git repo — it may
# compute and print, but it may not write or execute.
#
# Keep this list to commands that actually reach outside the simulation.
# `quit` was in it once and cost a working block: RESET_sim ends its control
# section with `quit`, which is how a batch run says it is finished — it
# reads nothing and writes nothing. Refusing the harmless ones does not make
# the sandbox tighter, it just breaks scenarios that were already correct.
BANNED_CONTROL = frozenset({
    "shell", "system", "source", "cd", "write", "wrdata", "wrs2p", "wrnodev",
    "edit", "aspice", "rspice", "hardcopy", "gnuplot", "load",
})


def find_control(text: str) -> tuple[str, str]:
    """Split `.control ... .endc` out of a netlist.

    Returns (netlist_without_control, control_body). The body excludes the
    `.control`/`.endc` lines themselves. Only the first block is taken —
    kicad-cli concatenates the schematic's directive text items in sheet
    order, and more than one block is a schematic bug, not a feature.
    """
    lines = text.splitlines()
    start = end = -1
    for i, line in enumerate(lines):
        low = line.strip().lower()
        if start < 0 and low.startswith(".control"):
            start = i
        elif start >= 0 and low.startswith(".endc"):
            end = i
            break
    if start < 0 or end < 0:
        return text, ""
    body = "\n".join(lines[start + 1 : end])
    rest = lines[:start] + lines[end + 1 :]
    return "\n".join(rest), body


def check_control(control: str) -> None:
    """Raise SimError if the control block would write files or run programs."""
    for raw in control.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        cmd = re.split(r"[\s(]", line, maxsplit=1)[0].lower()
        if cmd in BANNED_CONTROL:
            raise SimError(f"control command not allowed here: {cmd}")


def unmodelled_refs(text: str) -> list[str]:
    """Refs that netlisted as placeholders because they carry no sim model."""
    return [m.group(1) for line in text.splitlines() if (m := _UNMODELLED_RE.match(line))]


def prepare_netlist(
    text: str,
    *,
    control: str | None = None,
    analysis: str = "",
    savecurrents: bool = True,
) -> tuple[str, dict]:
    """kicad-cli's netlist -> what ngspice actually runs.

    control:  None keeps the schematic's own block, "" drops it, any other
              string replaces it (the UI's scenario editor).
    analysis: replaces every top-level analysis directive (live mode asks for
              one endless `.tran`); "" keeps the schematic's directives.

    Returns (netlist_text, info) where info carries what the UI must show:
    the refs that were dropped and the control block that ran.
    """
    body, own_control = find_control(text)
    ctl = own_control if control is None else control
    if ctl:
        check_control(ctl)

    dropped = unmodelled_refs(body)
    lines = [ln for ln in body.splitlines() if not _UNMODELLED_RE.match(ln)]

    if analysis:
        lines = [ln for ln in lines if not _ANALYSIS_RE.match(ln)]

    # `.end` must stay last, and the injected directives must sit before it.
    tail: list[str] = []
    while lines and (not lines[-1].strip() or lines[-1].strip().lower() == ".end"):
        tail.insert(0, lines.pop())
    if not any(ln.strip().lower() == ".end" for ln in tail):
        tail.append(".end")

    inject: list[str] = []
    if savecurrents:
        inject.append(".options savecurrents")
    if analysis:
        inject.append(analysis)
    if ctl:
        inject += [".control", *ctl.splitlines(), ".endc"]

    out = "\n".join([*lines, *inject, *tail]).strip() + "\n"
    return out, {"unmodelled": dropped, "control": ctl}


def run_ngspice(netlist: str, work_dir: str | Path, *, ngspice: str = "ngspice",
                timeout: int = 60, env: dict | None = None) -> tuple[bytes, str]:
    """Batch run. Returns (rawfile bytes, ngspice log). Raises on no output."""
    work = Path(work_dir)
    cir = work / "sim.cir"
    raw = work / "sim.raw"
    cir.write_text(netlist, encoding="utf-8")
    try:
        proc = subprocess.run(
            [ngspice, "-b", "-r", str(raw), str(cir)],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise SimError(f"ngspice did not finish within {timeout}s") from e
    log = (proc.stdout or "") + (proc.stderr or "")
    if not raw.exists() or raw.stat().st_size == 0:
        raise SimError(f"ngspice produced no data (rc={proc.returncode}): {log.strip()[-800:]}")
    return raw.read_bytes(), log


# ---------------------------------------------------------------- rawfile

_HEADER_KEYS = ("title", "date", "plotname", "flags", "no. variables", "no. points")


def parse_raw(data: bytes) -> list[dict]:
    """Decode a binary ngspice rawfile into plots.

    One rawfile may hold several plots (a control block that runs more than
    one analysis). Each plot is
    {name, flags, complex, n, vectors: [{name, type}], values: [[float]]}
    where values[i] is vector i over the whole sweep. Complex plots keep
    real/imag interleaved (2 floats per point).
    """
    plots: list[dict] = []
    pos = 0
    while pos < len(data):
        head_end = data.find(b"Binary:\n", pos)
        if head_end < 0:
            if data.find(b"Values:", pos) >= 0:
                raise SimError("ASCII rawfiles are not supported — run ngspice with binary output")
            break
        header = data[pos:head_end].decode("latin-1")
        meta: dict[str, str] = {}
        names: list[tuple[str, str]] = []
        in_vars = False
        for line in header.splitlines():
            if in_vars:
                parts = line.split()
                if len(parts) >= 3 and parts[0].isdigit():
                    names.append((parts[1], parts[2]))
                    continue
                in_vars = False
            low = line.split(":", 1)[0].strip().lower()
            if low == "variables":
                in_vars = True
            elif low in _HEADER_KEYS:
                meta[low] = line.split(":", 1)[1].strip()

        n_vars = int(meta.get("no. variables", len(names)) or len(names))
        n_pts = int(meta.get("no. points", 0) or 0)
        is_complex = "complex" in meta.get("flags", "").lower()
        per_value = 2 if is_complex else 1
        start = head_end + len(b"Binary:\n")
        size = n_vars * n_pts * per_value * 8
        blob = data[start : start + size]
        if len(blob) < size:
            raise SimError("rawfile truncated — the run was cut short")

        floats = struct.unpack(f"<{n_vars * n_pts * per_value}d", blob)
        values: list[list[float]] = [[] for _ in range(n_vars)]
        stride = n_vars * per_value
        for p in range(n_pts):
            base = p * stride
            for v in range(n_vars):
                off = base + v * per_value
                values[v].append(floats[off])
                if is_complex:
                    values[v].append(floats[off + 1])
        plots.append({
            "name": meta.get("plotname", ""),
            "flags": meta.get("flags", ""),
            "complex": is_complex,
            "n": n_pts,
            "vectors": [{"name": nm, "type": ty} for nm, ty in names[:n_vars]],
            "values": values,
        })
        pos = start + size
    if not plots:
        raise SimError("no plot found in the rawfile")
    return plots


# ---------------------------------------------------------------- filtering

# What a caller gets to see. `v(x)` where x is a real net, `i(@r1[i])` device
# currents and `i(v1)` source currents. Everything else in a `savecurrents`
# run is subcircuit internals (v(xu1.53), @q.xu1.q4[ic]) — 40 of the 91
# vectors on the reference circuit, and meaningless outside the model.
_V_RE = re.compile(r"^v\((.+)\)$", re.IGNORECASE)
_I_DEV_RE = re.compile(r"^i\(@([^.\[]+)\[i\]\)$", re.IGNORECASE)
_I_SRC_RE = re.compile(r"^i\(([a-z][a-z0-9_]*)\)$", re.IGNORECASE)
_SCALE_TYPES = frozenset({"time", "frequency", "voltage"})


def classify(name: str, nets: set[str] | None) -> dict | None:
    """Top-level vector -> {kind, key}; None for subcircuit internals."""
    low = name.strip().lower()
    if m := _V_RE.match(low):
        net = m.group(1)
        if "." in net:  # xu1.53 — inside a subcircuit
            return None
        if nets is not None and net not in nets:
            return None
        return {"kind": "v", "key": net}
    if m := _I_DEV_RE.match(low):
        return {"kind": "i", "key": m.group(1)}
    if m := _I_SRC_RE.match(low):
        return {"kind": "i", "key": m.group(1)}
    return None


def _decimate(scale: list[float], series: list[list[float]], limit: int
              ) -> tuple[list[float], list[list[float]], bool]:
    """Bucket to a min/max envelope, two samples per bucket, shared buckets so
    every vector keeps the same time base."""
    n = len(scale)
    if n <= limit:
        return scale, series, False
    buckets = max(1, limit // 2)
    step = n / buckets
    out_scale: list[float] = []
    out: list[list[float]] = [[] for _ in series]
    for b in range(buckets):
        lo = int(b * step)
        hi = min(n, max(lo + 1, int((b + 1) * step)))
        out_scale.append(scale[lo])
        out_scale.append(scale[hi - 1])
        for i, vals in enumerate(series):
            window = vals[lo:hi]
            out[i].append(min(window))
            out[i].append(max(window))
    return out_scale, out, True


def encode_payload(plots: list[dict], *, nets: set[str] | None = None,
                   info: dict | None = None, log: str = "",
                   max_points: int = MAX_POINTS) -> bytes:
    """Plots -> the binary the browser reads.

    Layout: b"7SIM" | uint32 header length | UTF-8 JSON header | float32 blob.
    The header is space-padded so the blob starts 4-byte aligned (see below).
    Every vector in the header carries a byte offset and length into the blob.
    float32 is deliberate: plots are drawn at screen resolution, and halving
    the payload matters more than the last six digits of a double.
    """
    header: dict = {
        "version": FORMAT_VERSION,
        "plots": [],
        "unmodelled": (info or {}).get("unmodelled", []),
        "control": (info or {}).get("control", ""),
        "log": log[-4000:],
    }
    blob = bytearray()
    for plot in plots:
        vecs = plot["vectors"]
        if not vecs:
            continue
        scale_vals = plot["values"][0]
        if plot["complex"]:
            scale_vals = scale_vals[0::2]
        keep: list[tuple[dict, dict]] = []
        for idx, vec in enumerate(vecs):
            if idx == 0:
                continue
            cls = classify(vec["name"], nets)
            if cls:
                keep.append((vec, {**cls, "index": idx}))

        series = []
        for _vec, cls in keep:
            vals = plot["values"][cls["index"]]
            series.append(vals)

        if plot["complex"]:
            scale_out, series_out, decimated = scale_vals, series, False
        else:
            scale_out, series_out, decimated = _decimate(scale_vals, series, max_points)

        entry = {
            "name": plot["name"],
            "complex": plot["complex"],
            "decimated": decimated,
            "n": len(scale_out),
            "scale": {"name": vecs[0]["name"], "type": vecs[0]["type"]},
            "vectors": [],
        }
        off = len(blob)
        blob += struct.pack(f"<{len(scale_out)}f", *scale_out)
        entry["scale"]["offset"] = off
        entry["scale"]["len"] = len(scale_out)
        for (vec, cls), vals in zip(keep, series_out, strict=True):
            off = len(blob)
            blob += struct.pack(f"<{len(vals)}f", *vals)
            entry["vectors"].append({
                "name": vec["name"], "unit": vec["type"], "kind": cls["kind"],
                "key": cls["key"], "offset": off, "len": len(vals),
            })
        header["plots"].append(entry)

    head = json.dumps(header, separators=(",", ":")).encode("utf-8")
    # Pad the header to a 4-byte boundary. The reader maps the blob with
    # Float32Array views, and a typed array may only start on a multiple of
    # its element size — an odd header length makes every view throw. Trailing
    # spaces are still valid JSON.
    head += b" " * (-len(head) % 4)
    return MAGIC + struct.pack("<I", len(head)) + head + bytes(blob)


def decode_header(payload: bytes) -> dict:
    """Header of an encode_payload result — for tests and for the API's own
    checks. The float blob is left alone."""
    if payload[:4] != MAGIC:
        raise SimError("not a 7SIM payload")
    (length,) = struct.unpack("<I", payload[4:8])
    return json.loads(payload[8 : 8 + length].decode("utf-8"))
