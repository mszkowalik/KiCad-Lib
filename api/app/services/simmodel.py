"""SPICE subcircuit parsing, fingerprinting and pin-map validation.

The canonical artifact of a `SimModelVersion` is its `.subckt ... .ends` text,
exactly as `SymbolVersion.source_text` is a `.kicad_sym`. Everything here is
derived from that text: the port list, the declared parameters, the primitives
it instantiates, and the fingerprint a stored pin map is checked against.

Why the fingerprint covers the PORT LIST only: a pin map is
`{symbol pin number: port name}`, so it survives any change that leaves the
ports alone — retuning a parameter, adding an ESD clamp, swapping a switch for
a behavioural source. Adding, removing or renaming a port invalidates it.
"""
from __future__ import annotations

import hashlib
import json
import re

# A pin deliberately not wired to the model. Correct for NC pins, and for the
# hidden stacked duplicates the house style uses (KiCad nets those together
# anyway, so the model only needs the visible one).
NC = "-"

# The one generated SPICE library: every published model, primitives and part
# wrappers alike, in a single self-contained file next to the symbol libs.
SIM_LIB_FILE = "7Sigma_sim.sp"

_SUBCKT_RE = re.compile(r"^\s*\.subckt\s+(.*)$", re.IGNORECASE)
_ENDS_RE = re.compile(r"^\s*\.ends\b", re.IGNORECASE)
_MODEL_RE = re.compile(r"^\s*\.model\b", re.IGNORECASE)


def _strip_comment(line: str) -> str:
    """Drop a trailing `$` comment. A `*` only starts a comment at column 1,
    which the caller has already handled, and `*` is multiplication elsewhere.
    """
    cut = line.find("$")
    return line[:cut] if cut >= 0 else line


def _logical_lines(text: str) -> list[str]:
    """SPICE continuation lines start with `+` and belong to the line above."""
    out: list[str] = []
    for raw in text.splitlines():
        line = _strip_comment(raw.rstrip())
        if not line.strip() or line.lstrip().startswith("*"):
            continue
        if line.lstrip().startswith("+") and out:
            out[-1] = out[-1] + " " + line.lstrip()[1:].strip()
        else:
            out.append(line.strip())
    return out


def parse_subckt(source_text: str) -> dict:
    """Derived cache for one model's `source_text`.

    Returns `{"name", "ports", "params", "instantiates"}`. Raises ValueError
    when the text holds no `.subckt`, because a model that declares no
    interface cannot be linked to a symbol.
    """
    lines = _logical_lines(source_text)
    name = ""
    ports: list[str] = []
    params: dict[str, str] = {}
    instantiates: set[str] = set()
    depth = 0

    for line in lines:
        m = _SUBCKT_RE.match(line)
        if m:
            depth += 1
            if depth > 1:  # a nested definition, not this model's interface
                continue
            body = m.group(1)
            # `params:` splits the port list from the defaults. ngspice also
            # accepts `PARAMS:`; anything after it is `name=value`.
            parts = re.split(r"(?i)\bparams:", body, maxsplit=1)
            head, tail = parts[0], (parts[1] if len(parts) > 1 else "")
            tokens = head.split()
            if tokens:
                name, ports = tokens[0], tokens[1:]
            for key, value in re.findall(r"([A-Za-z_][\w]*)\s*=\s*(\{[^}]*\}|\S+)", tail):
                params[key] = value
            continue
        if _ENDS_RE.match(line):
            depth = max(0, depth - 1)
            continue
        # `X...` instance lines name the subcircuit they call. The callee is
        # the last bare token before any `name=value` pairs.
        if depth >= 1 and line[:1].upper() == "X" and not _MODEL_RE.match(line):
            bare = [t for t in line.split()[1:] if "=" not in t]
            if bare:
                instantiates.add(bare[-1].lower())

    if not name:
        raise ValueError("no .subckt definition found")
    return {
        "name": name.lower(),
        "ports": [p.lower() for p in ports],
        "params": params,
        "instantiates": sorted(instantiates),
    }


def model_material_sha(source_text: str) -> str:
    """Fingerprint of the interface. Empty when the text will not parse — an
    unparseable model must never compare EQUAL to another one."""
    try:
        parsed = parse_subckt(source_text)
    except Exception:  # noqa: BLE001 — broken source is "cannot tell", not a crash
        return ""
    blob = json.dumps({"ports": parsed["ports"]}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# Port names that mean "this is a supply rail". A rail port should be claimed
# by a power pin and vice versa — the one cheap semantic check available,
# since a swapped pair is otherwise a perfectly valid permutation.
_RAIL_PORTS = {"vcc", "vdd", "vee", "vss", "gnd", "vbb", "spu", "agnd", "dgnd", "vbat", "vin"}
_POWER_PIN_TYPES = {"power_in", "power_out"}


def link_material_sha(symbol_pins: list[dict]) -> str:
    """The SYMBOL-side fingerprint a stored pin map is stamped with.

    Deliberately much narrower than `material.material_sha("symbol", ...)`:
    that one covers pin positions, lengths and hide flags, so a cosmetic edit
    (SN74HC21 v2 was literally "shortened the pins") would flag every link on
    the symbol as stale. A pin map depends only on which pin NUMBERS exist
    and their electrical types (the type feeds the rail/signal heuristic) —
    so that is all this hashes.

    Hidden stacked duplicates collapse onto their visible pin the same way
    `validate_pin_map` treats them: one entry per number, visible type wins.
    """
    types: dict[str, str] = {}
    for pin in symbol_pins:
        num = pin.get("number", "")
        if num and (num not in types or not pin.get("hide")):
            types[num] = pin.get("type", "")
    blob = json.dumps(sorted(types.items()), separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def validate_pin_map(pin_map: dict, symbol_pins: list[dict], ports: list[str]) -> list[dict]:
    """Problems with one stored map. Each entry is
    `{"severity": "error"|"warning", "text": ...}`; no errors means usable.

    `symbol_pins` is `material.symbol_material()["pins"]`. Nothing downstream
    checks any of this — KiCad emits whatever the map says.

    The errors below are structural: a port with no pin, a port claimed twice,
    a pin that does not exist. They CANNOT catch a swap, because swapping two
    entries is still a valid permutation. The warnings exist for that gap and
    are heuristic on purpose: they compare a pin's electrical type against
    whether its port looks like a supply rail. That is why the map is
    reviewed by a person in the UI rather than merely validated.
    """
    problems: list[dict] = []

    def err(text: str) -> None:
        problems.append({"severity": "error", "text": text})

    def warn(text: str) -> None:
        problems.append({"severity": "warning", "text": text})

    numbers = [p.get("number", "") for p in symbol_pins if p.get("number")]
    # Hidden stacked duplicates share a number with a visible pin; KiCad nets
    # them together, so the map only has to name each NUMBER once.
    unique_numbers = sorted(set(numbers))
    mapped = {str(k): str(v).lower() for k, v in (pin_map or {}).items()}

    unknown = sorted(set(mapped) - set(unique_numbers))
    if unknown:
        err(f"maps pins that the symbol does not have: {', '.join(unknown)}")

    missing = sorted(n for n in unique_numbers if n not in mapped)
    if missing:
        err(
            f"leaves pins unmapped: {', '.join(missing)} "
            f"(use {NC!r} to say a pin is deliberately not modelled)"
        )

    wanted = [p.lower() for p in ports]
    assigned = [v for v in mapped.values() if v != NC]
    for port in wanted:
        hits = assigned.count(port)
        if hits == 0:
            err(f"port {port!r} has no pin")
        elif hits > 1:
            err(f"port {port!r} is claimed by {hits} pins")
    for port in sorted(set(assigned) - set(wanted)):
        err(f"maps to {port!r}, which the model does not declare")

    # Heuristic pass: rails and signals should not trade places.
    types: dict[str, str] = {}
    for pin in symbol_pins:
        num = pin.get("number", "")
        # A visible pin's type wins over a hidden stacked duplicate's, which
        # the house style types `passive` regardless of what it carries.
        if num and (num not in types or not pin.get("hide")):
            types[num] = pin.get("type", "")
    for num, port in mapped.items():
        if port == NC:
            continue
        ptype = types.get(num, "")
        if port in _RAIL_PORTS and ptype not in _POWER_PIN_TYPES:
            warn(f"pin {num} is {ptype or 'untyped'} but maps to rail port {port!r}")
        elif port not in _RAIL_PORTS and ptype == "power_in":
            # `power_out` on a signal port is NOT suspicious: a regulator or a
            # high-side switch output really is a power output on a port
            # called `out`. Only a supply INPUT landing on a signal port is.
            warn(f"pin {num} is power_in but maps to signal port {port!r}")
    return problems


def sim_pins_value(pin_map: dict) -> str:
    """The `Sim.Pins` field: `"1=a1 2=a2 3=common"`.

    Never omitted, even when the map looks like the identity. Without it
    KiCad falls back to raw pin order, counts a hidden stacked duplicate as
    its own node and runs off the end of the port list — silently.
    """
    pairs = [
        (k, v) for k, v in (pin_map or {}).items() if str(v) != NC
    ]

    def sort_key(item: tuple[str, str]) -> tuple[int, str]:
        num = str(item[0])
        return (0, f"{int(num):06d}") if num.isdigit() else (1, num)

    return " ".join(f"{k}={v}" for k, v in sorted(pairs, key=sort_key))
