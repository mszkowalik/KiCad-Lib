"""Material fingerprints for symbol and footprint geometry.

A production sign-off says "I checked this drawing". The question that follows
every geometry edit is whether the new version still deserves that sign-off.
Answering it by hand for 40 components after a silkscreen tweak is waste;
answering it wrongly after a pad move is a scrapped board. So the platform
answers the provable half: **did anything that reaches the board change?**

That is what a material fingerprint is. It hashes the subset of a drawing that
can affect a manufactured part — copper, mask, paste, drill, the physical
envelope, and everything a netlist or a schematic reader depends on — and
nothing else. Two versions with the same fingerprint differ only in decoration,
so a sign-off carries automatically. A different fingerprint means a human
looks again, unless that human explicitly waives it.

What is deliberately EXCLUDED, and why:

- `F.SilkS` / `B.SilkS`, `F.Fab` / `B.Fab`, `*.User` graphics and text. They
  are documentation. A moved reference designator has never shorted a pin.
- `descr`, `tags`, and the footprint's own `property` fields. Metadata.
- `model` — the 3D model. It never reaches the copper. A wrong mesh is a
  rendering defect, not a fabrication defect, and it has its own review path.
- `uuid` / `tstamp` everywhere. KiCad regenerates them on almost every save,
  so including them would make every fingerprint unique and the whole
  mechanism useless.
- On symbols: the body outline, field text, and field positions. Redrawing a
  box does not change what the symbol asserts about the part.

What is INCLUDED on a footprint is anything a fab house acts on: every pad's
number, type, shape, position, rotation, size, drill, layer set and margin
overrides; custom pad primitives; the courtyard outline (it is the clearance
contract with the neighbouring part); and the footprint `attr` flags.

What is INCLUDED on a symbol is the pin set: number, name, electrical type,
graphic style, position, rotation, length, hidden flag, alternate functions,
and which unit each pin belongs to. The graphic style is in on purpose — a pin
turning from `line` to `inverted` changes what the schematic claims about the
part, and that is exactly what a verification is for.

Both parsers use `util/sexpr.py` rather than kiutils, for the same reason the
click-map parser does: kiutils chokes on tokens newer KiCad releases write.
`services/parse_cache.py` cannot be reused here — it drops pad and pin
POSITIONS, which are the single most important thing this module compares.
"""
from __future__ import annotations

import hashlib
import json
import re

from ..util.sexpr import _norm, find_node, iter_nodes, parse_sexpr, sanitize_symbol_text, walk_nodes

# Pad sub-nodes whose single value is copied verbatim. Every one of them
# changes what the fab or the assembler does with the pad.
_PAD_SCALARS = (
    "roundrect_rratio",
    "chamfer_ratio",
    "solder_mask_margin",
    "solder_paste_margin",
    "solder_paste_margin_ratio",
    "clearance",
    "zone_connect",
    "thermal_width",
    "thermal_gap",
    "thermal_bridge_width",
    "thermal_bridge_angle",
    "die_length",
    "property",
)

# Layers a courtyard lives on. The courtyard is the clearance contract with
# whatever sits next to the part, so a change to it is material.
_COURTYARD_LAYERS = ("F.CrtYd", "B.CrtYd")

_GRAPHIC_TAGS = ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_curve")

# Unit entry names look like NAME_<unit>_<style>.
_UNIT_RE = re.compile(r"_(\d+)_(\d+)$")


def _num(atom) -> float:
    """A parsed atom as a stable float. Normalises -0.0 to 0.0 and rounds to
    the nanometre, so a re-save that reprints 0.5 as 0.500000 is not a change."""
    try:
        v = round(float(_norm(atom)), 6)
    except (TypeError, ValueError):
        return 0.0
    return v + 0.0


def _args(node, tag: str) -> list | None:
    """Every argument of a child node `(tag a b c)`, numbers where possible."""
    child = find_node(node, tag)
    if child is None:
        return None
    out = []
    for a in child[1:]:
        if isinstance(a, list):
            out.append(_canonical_list(a))
        else:
            s = _norm(a)
            try:
                out.append(round(float(s), 6) + 0.0)
            except ValueError:
                out.append(s)
    return out


def _canonical_list(node) -> list:
    """A whole subtree reduced to plain strings and numbers, uuids dropped."""
    out: list = []
    for a in node:
        if isinstance(a, list):
            if a and _norm(a[0]) in ("uuid", "tstamp"):
                continue
            out.append(_canonical_list(a))
        else:
            s = _norm(a)
            try:
                out.append(round(float(s), 6) + 0.0)
            except ValueError:
                out.append(s)
    return out


def _sorted_entries(entries: list[dict]) -> list[dict]:
    """Order by content, not by file order. KiCad rewrites pads and pins in
    whatever order its internal containers hold them, and a reordered file is
    not a changed part."""
    return sorted(entries, key=lambda e: json.dumps(e, sort_keys=True))


# ------------------------------------------------------------------ footprint
def footprint_material(source_text: str) -> dict:
    """The material subset of a `.kicad_mod`."""
    tree = parse_sexpr(source_text)
    # The footprint node IS the root of a .kicad_mod, so `find_node` on the
    # parse result misses it — same fallback parse_cache uses.
    fp = find_node(tree, "footprint") or (tree[0] if tree and isinstance(tree[0], list) else tree)

    pads: list[dict] = []
    for pad in walk_nodes(fp, "pad"):
        entry: dict = {
            "number": _norm(pad[1]) if len(pad) > 1 else "",
            "type": _norm(pad[2]) if len(pad) > 2 else "",
            "shape": _norm(pad[3]) if len(pad) > 3 else "",
        }
        for tag in ("at", "size", "drill", "rect_delta", "chamfer", "offset"):
            val = _args(pad, tag)
            if val is not None:
                entry[tag] = val
        layers = find_node(pad, "layers")
        if layers is not None:
            entry["layers"] = sorted(_norm(x) for x in layers[1:])
        for tag in _PAD_SCALARS:
            # `property` legitimately repeats on one pad (heatsink + castellated),
            # so collect every occurrence rather than the first.
            vals = [_canonical_list(n)[1:] for n in iter_nodes(pad, tag)]
            if vals:
                entry[tag] = sorted(vals, key=lambda x: json.dumps(x, sort_keys=True))
        prims = find_node(pad, "primitives")
        if prims is not None:
            entry["primitives"] = _canonical_list(prims)
        pads.append(entry)

    courtyard: list[list] = []
    for tag in _GRAPHIC_TAGS:
        for node in walk_nodes(fp, tag):
            layer = find_node(node, "layer")
            if layer is None or len(layer) < 2:
                continue
            if _norm(layer[1]) not in _COURTYARD_LAYERS:
                continue
            courtyard.append(_canonical_list(node))

    attrs: list[str] = []
    for node in iter_nodes(fp, "attr"):
        attrs.extend(sorted(_norm(a) for a in node[1:]))

    return {
        "pads": _sorted_entries(pads),
        "courtyard": sorted(courtyard, key=lambda x: json.dumps(x, sort_keys=True)),
        "attrs": sorted(attrs),
    }


# --------------------------------------------------------------------- symbol
def _unit_of(entry_name: str) -> list[int]:
    m = _UNIT_RE.search(entry_name)
    return [int(m.group(1)), int(m.group(2))] if m else [0, 0]


def symbol_material(source_text: str) -> dict:
    """The material subset of a single-symbol `.kicad_sym` library text."""
    tree = parse_sexpr(sanitize_symbol_text(source_text))

    pins: list[dict] = []
    units: set[tuple[int, int]] = set()
    for sym in walk_nodes(tree, "symbol"):
        name = _norm(sym[1]) if len(sym) > 1 else ""
        unit = _unit_of(name)
        if unit != [0, 0]:
            units.add((unit[0], unit[1]))
        for pin in iter_nodes(sym, "pin"):
            entry: dict = {
                "unit": unit,
                # (pin <electrical-type> <graphic-style> ...)
                "type": _norm(pin[1]) if len(pin) > 1 else "",
                "style": _norm(pin[2]) if len(pin) > 2 else "",
                "number": "",
                "name": "",
            }
            num = find_node(pin, "number")
            if num is not None and len(num) > 1:
                entry["number"] = _norm(num[1])
            nm = find_node(pin, "name")
            if nm is not None and len(nm) > 1:
                entry["name"] = _norm(nm[1])
            at = find_node(pin, "at")
            if at is not None:
                entry["at"] = [_num(a) for a in at[1:]]
            length = find_node(pin, "length")
            if length is not None and len(length) > 1:
                entry["length"] = _num(length[1])
            # A hidden pin is a real electrical decision (an unconnected or
            # implicit power pin), not decoration. KiCad 6/7 wrote a bare
            # `hide` atom, KiCad 8+ writes `(hide yes)` — read both.
            hide = find_node(pin, "hide")
            if hide is not None:
                entry["hide"] = _norm(hide[1]).lower() in ("yes", "true") if len(hide) > 1 else True
            elif any(not isinstance(a, list) and _norm(a) == "hide" for a in pin[3:]):
                entry["hide"] = True
            alts = [_canonical_list(a) for a in iter_nodes(pin, "alternate")]
            if alts:
                entry["alternates"] = sorted(alts, key=lambda x: json.dumps(x, sort_keys=True))
            pins.append(entry)

    # Unit 0 is the "common to every unit" entry, not a unit of its own.
    real_units = {u for u, _ in units if u > 0}
    return {
        "pins": _sorted_entries(pins),
        "unit_count": len(real_units) or 1,
    }


# ----------------------------------------------------------------- public API
def material(kind: str, source_text: str) -> dict:
    if kind == "symbol":
        return symbol_material(source_text)
    if kind == "footprint":
        return footprint_material(source_text)
    raise ValueError(f"unknown geometry kind {kind!r}")


def material_sha(kind: str, source_text: str) -> str:
    """The fingerprint. Empty string when the source will not parse — an
    unparseable drawing must never silently compare EQUAL to another one."""
    try:
        payload = material(kind, source_text)
    except Exception:  # noqa: BLE001 — a broken source is a "cannot tell", not a crash
        return ""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


def describe_changes(kind: str, old_text: str, new_text: str) -> list[str]:
    """Plain sentences naming what moved, for the approval dialog.

    Best effort and deliberately coarse: the decision is the user's, this only
    has to tell them where to look."""
    try:
        old, new = material(kind, old_text), material(kind, new_text)
    except Exception:  # noqa: BLE001
        return ["the drawing could not be parsed — check it by hand"]

    out: list[str] = []
    if kind == "footprint":
        o_pads = {p.get("number", ""): p for p in old["pads"]}
        n_pads = {p.get("number", ""): p for p in new["pads"]}
        added = sorted(set(n_pads) - set(o_pads))
        removed = sorted(set(o_pads) - set(n_pads))
        moved = sorted(n for n in set(o_pads) & set(n_pads) if o_pads[n] != n_pads[n])
        if added:
            out.append(f"pads added: {', '.join(added)}")
        if removed:
            out.append(f"pads removed: {', '.join(removed)}")
        if moved:
            out.append(f"pads changed: {', '.join(moved)}")
        if old["courtyard"] != new["courtyard"]:
            out.append("the courtyard outline changed")
        if old["attrs"] != new["attrs"]:
            out.append(f"footprint attributes changed: {old['attrs']} to {new['attrs']}")
    else:
        o_pins = {p.get("number", ""): p for p in old["pins"]}
        n_pins = {p.get("number", ""): p for p in new["pins"]}
        added = sorted(set(n_pins) - set(o_pins))
        removed = sorted(set(o_pins) - set(n_pins))
        changed = sorted(n for n in set(o_pins) & set(n_pins) if o_pins[n] != n_pins[n])
        if added:
            out.append(f"pins added: {', '.join(added)}")
        if removed:
            out.append(f"pins removed: {', '.join(removed)}")
        if changed:
            out.append(f"pins changed: {', '.join(changed)}")
        if old["unit_count"] != new["unit_count"]:
            out.append(f"unit count changed: {old['unit_count']} to {new['unit_count']}")
    return out
