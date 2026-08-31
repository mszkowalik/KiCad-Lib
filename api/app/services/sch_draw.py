"""Everything a browser needs to DRAW a `.kicad_sch` itself.

`sim_geom` answers "what is connected to what". This module answers "what does
it look like", and the two share one parse so their ids line up: the wire the
overlay tints as `w7` is the wire this module draws as `w7`.

Why draw it in the browser at all, when `kicad-cli sch export svg` already
produces a picture:

1. **A picture cannot change.** A switch that closes, a relay that pulls in, a
   LED that lights — Falstad's whole feel is the drawing reacting. A raster or
   a flat SVG from a batch tool can only be replaced, and replacing it costs a
   round trip through the render container (about a second).
2. **An editor needs the geometry, not a picture.** Placing, dragging and
   wiring all need to know where things are, which is exactly this document.

Coordinates are the file's own millimetres, y down, matching the SVG viewBox
`sim_geom` documents. Library graphics stay in SYMBOL space (y UP) and each
placement carries the 2x3 matrix that maps them onto the sheet, so one symbol
definition serves every placement of it.

Colours are NOT in here. KiCad stores a colour only where the user overrode
one; the rest come from the active theme, which is the browser's business.
"""
from __future__ import annotations

import math

from ..util.sexpr import find_node, iter_nodes, node_value

# KiCad's own defaults for "0 means default" in stroke widths, millimetres.
DEFAULT_LINE_MM = 0.1524
DEFAULT_TEXT_MM = 1.27

_SHAPE_TAGS = ("rectangle", "polyline", "circle", "arc", "bezier")


# ------------------------------------------------------------------ helpers

def _floats(node, count: int) -> list[float] | None:
    if node is None:
        return None
    try:
        return [float(str(v)) for v in node[1 : 1 + count]]
    except (TypeError, ValueError, IndexError):
        return None


def _num(node, tag: str, default: float = 0.0) -> float:
    try:
        return float(str(node_value(node, tag, default)))
    except (TypeError, ValueError):
        return default


def _text(atom) -> str:
    return str(atom).strip('"') if atom is not None else ""


def _yes(node, tag: str, default: bool = False) -> bool:
    """A KiCad flag. Written `(tag yes)` in current files and bare `(tag)` in
    older ones, so the absence of a value means the flag IS set."""
    child = find_node(node, tag)
    if child is None:
        return default
    if len(child) < 2:
        return True
    return _text(child[1]).lower() in ("yes", "true")


def _at3(node) -> list[float]:
    v = _floats(find_node(node, "at"), 3)
    if v is None:
        v = _floats(find_node(node, "at"), 2)
        return [v[0], v[1], 0.0] if v else [0.0, 0.0, 0.0]
    return v


def _stroke_width(node) -> float:
    stroke = find_node(node, "stroke")
    if stroke is None:
        return 0.0
    return _num(stroke, "width", 0.0)


def _stroke_type(node) -> str:
    stroke = find_node(node, "stroke")
    if stroke is None:
        return "default"
    return _text(node_value(stroke, "type", "default"))


def _fill(node) -> str:
    fill = find_node(node, "fill")
    if fill is None:
        return "none"
    return _text(node_value(fill, "type", "none")) or "none"


def _effects(node) -> dict:
    """Font size, style and justification, flattened.

    `hide` sits on the effects in modern files and on the property in older
    ones, so callers check both.
    """
    eff = find_node(node, "effects")
    out = {"h": DEFAULT_TEXT_MM, "bold": False, "italic": False,
           "just": [], "hide": False}
    if eff is None:
        return out
    font = find_node(eff, "font")
    if font is not None:
        size = _floats(find_node(font, "size"), 2)
        if size:
            # KiCad writes (size height width); the height is what a reader
            # sees as the text size.
            out["h"] = size[0]
        out["bold"] = _yes(font, "bold")
        out["italic"] = _yes(font, "italic")
    just = find_node(eff, "justify")
    if just is not None:
        out["just"] = [_text(v) for v in just[1:]]
    out["hide"] = _yes(eff, "hide")
    return out


def placement_matrix(at: list[float], mirror: str) -> list[float]:
    """Symbol space (y up) -> sheet space (y down), as `matrix(a b c d e f)`.

    This is `sim_geom._place` written as a matrix, and it must stay identical
    to it: the overlay puts a current arrow on a pin whose position came from
    there, and the renderer draws the pin from here. The stored angle is
    NEGATED for the same reason it is negated there — KiCad turns a symbol the
    way the user sees it, and the y flip reverses that sense.
    """
    x, y, rot = (at + [0.0, 0.0, 0.0])[:3]
    sx = -1.0 if "y" in mirror else 1.0
    sy = 1.0 if "x" in mirror else -1.0
    c = math.cos(math.radians(rot))
    s = -math.sin(math.radians(rot))
    return [c * sx, s * sx, -s * sy, c * sy, x, y]


# ------------------------------------------------------- library definitions

def _unit_of(name: str) -> tuple[int, int]:
    """`"R_Small_1_1"` -> (unit 1, body style 1). Unit 0 is drawn for every
    unit; body style 2 is the De Morgan alternate, which we never show."""
    parts = name.rsplit("_", 2)
    if len(parts) == 3:
        try:
            return int(parts[1]), int(parts[2])
        except ValueError:
            pass
    return 0, 1


def _shape(node, tag: str, unit: int, body: int) -> dict | None:
    common = {
        "unit": unit, "body": body,
        "w": _stroke_width(node), "dash": _stroke_type(node), "fill": _fill(node),
    }
    if tag == "rectangle":
        a = _floats(find_node(node, "start"), 2)
        b = _floats(find_node(node, "end"), 2)
        if not a or not b:
            return None
        return {"t": "rect", "a": a, "b": b, **common}
    if tag in ("polyline", "bezier"):
        pts_node = find_node(node, "pts")
        pts = [v for xy in iter_nodes(pts_node, "xy") if (v := _floats(xy, 2))] if pts_node else []
        if len(pts) < 2:
            return None
        return {"t": "poly" if tag == "polyline" else "bezier", "pts": pts, **common}
    if tag == "circle":
        c = _floats(find_node(node, "center"), 2)
        if not c:
            return None
        return {"t": "circle", "c": c, "r": _num(node, "radius", 0.0), **common}
    if tag == "arc":
        a = _floats(find_node(node, "start"), 2)
        m = _floats(find_node(node, "mid"), 2)
        b = _floats(find_node(node, "end"), 2)
        if not a or not m or not b:
            return None
        return {"t": "arc", "a": a, "m": m, "b": b, **common}
    return None


def _lib_pin(pin, unit: int, body: int) -> dict | None:
    at = _at3(pin)
    if at is None:
        return None
    number = find_node(pin, "number")
    name = find_node(pin, "name")
    return {
        "unit": unit, "body": body,
        "n": _text(number[1]) if number is not None and len(number) > 1 else "",
        "name": _text(name[1]) if name is not None and len(name) > 1 else "",
        "type": _text(pin[1]) if len(pin) > 1 else "passive",
        "shape": _text(pin[2]) if len(pin) > 2 else "line",
        "at": at, "len": _num(pin, "length", 0.0),
        "hide": _yes(pin, "hide"),
        "num_h": _effects(number)["h"] if number is not None else DEFAULT_TEXT_MM,
        "name_h": _effects(name)["h"] if name is not None else DEFAULT_TEXT_MM,
    }


def library(root) -> dict[str, dict]:
    """Every symbol definition the sheet embeds, in symbol coordinates.

    A `.kicad_sch` carries the full graphics of every symbol it places, which
    is why the browser needs no library access to draw an existing sheet.
    """
    out: dict[str, dict] = {}
    lib = find_node(root, "lib_symbols")
    if lib is None:
        return out
    for sym in iter_nodes(lib, "symbol"):
        lib_id = _text(sym[1]) if len(sym) > 1 else ""
        if not lib_id:
            continue
        names = find_node(sym, "pin_names")
        numbers = find_node(sym, "pin_numbers")
        shapes: list[dict] = []
        pins: list[dict] = []
        for sub in iter_nodes(sym, "symbol"):
            unit, body = _unit_of(_text(sub[1]) if len(sub) > 1 else "")
            for tag in _SHAPE_TAGS:
                for node in iter_nodes(sub, tag):
                    entry = _shape(node, tag, unit, body)
                    if entry:
                        shapes.append(entry)
            for node in iter_nodes(sub, "text"):
                eff = _effects(node)
                shapes.append({
                    "t": "text", "unit": unit, "body": body,
                    "s": _text(node[1]) if len(node) > 1 else "",
                    "at": _at3(node), "h": eff["h"], "just": eff["just"],
                    "bold": eff["bold"], "italic": eff["italic"],
                })
            for node in iter_nodes(sub, "pin"):
                entry = _lib_pin(node, unit, body)
                if entry:
                    pins.append(entry)
        out[lib_id] = {
            "shapes": shapes,
            "pins": pins,
            # KiCad prints the unit letter after the reference — U46A, U46B —
            # but only when the part HAS several units, and it stores the bare
            # reference. Without the count a renderer cannot tell which.
            "unit_count": max(
                [s["unit"] for s in shapes] + [p["unit"] for p in pins] + [1],
            ),
            # `(pin_names hide)` / `(pin_numbers hide)` suppress the text a
            # renderer would otherwise put beside every pin. Two-pin passives
            # set both, which is why a resistor is a bare box in KiCad too.
            "hide_names": _yes(names, "hide") if names is not None else False,
            "hide_numbers": _yes(numbers, "hide") if numbers is not None else False,
            "name_offset": _num(names, "offset", 0.508) if names is not None else 0.508,
            "power": find_node(sym, "power") is not None,
            # Where the library puts Reference and Value, in SYMBOL space. A
            # newly placed part has no field positions of its own yet, and
            # these are the ones KiCad would give it.
            "props": _fields(sym),
        }
    return out


# ------------------------------------------------------------- sheet content

# Fields worth carrying even when hidden. Reference and Value because an
# editor shows them; `Sim.*` because they decide what the netlister makes of
# the part — a switch is a resistor only because `Sim.Device` says so, and a
# writer that dropped the row would write a part that does something else.
# Everything else (Footprint, Datasheet, MPN, LCSC, ...) is a dozen rows a
# catalogue part drags along and nobody ever draws.
_KEPT_HIDDEN_FIELDS = ("Reference", "Value")


def _keep_hidden(name: str) -> bool:
    return name in _KEPT_HIDDEN_FIELDS or name.startswith("Sim.")


def _fields(node) -> list[dict]:
    out = []
    for prop in iter_nodes(node, "property"):
        if len(prop) < 3:
            continue
        eff = _effects(prop)
        hidden = eff["hide"] or _yes(prop, "hide")
        if hidden and not _keep_hidden(_text(prop[1])):
            continue
        out.append({
            "k": _text(prop[1]), "v": _text(prop[2]),
            "at": _at3(prop), "h": eff["h"], "just": eff["just"],
            "bold": eff["bold"], "italic": eff["italic"],
            "hide": hidden,
        })
    return out


def _line_items(root, tag: str, kind: str) -> list[dict]:
    out = []
    for i, node in enumerate(iter_nodes(root, tag)):
        pts_node = find_node(node, "pts")
        pts = [v for xy in iter_nodes(pts_node, "xy") if (v := _floats(xy, 2))] if pts_node else []
        if len(pts) < 2:
            continue
        out.append({
            "id": f"{kind[0]}{i}", "kind": kind, "pts": pts,
            "w": _stroke_width(node), "dash": _stroke_type(node),
        })
    return out


def sheet_drawing(root) -> dict:
    """The whole sheet as draw instructions. Takes an already-parsed tree so
    that the geometry and the drawing can never disagree about item order."""
    libs = library(root)

    symbols: list[dict] = []
    for idx, sym in enumerate(iter_nodes(root, "symbol")):
        at = _at3(sym)
        mirror = _text(node_value(sym, "mirror", "") or "")
        try:
            unit = int(float(str(node_value(sym, "unit", 1) or 1)))
        except (TypeError, ValueError):
            unit = 1
        try:
            body = int(float(str(node_value(sym, "body_style", 1) or 1)))
        except (TypeError, ValueError):
            body = 1
        symbols.append({
            "index": idx,
            "lib_id": _text(node_value(sym, "lib_id", "") or ""),
            "unit": unit, "body": body,
            "at": at, "mirror": mirror,
            "xf": placement_matrix(at, mirror),
            "dnp": _yes(sym, "dnp"),
            "fields": _fields(sym),
        })

    labels: list[dict] = []
    for tag, kind in (("label", "local"), ("global_label", "global"),
                      ("hierarchical_label", "hier")):
        for i, node in enumerate(iter_nodes(root, tag)):
            eff = _effects(node)
            labels.append({
                "id": f"l{kind}{i}", "kind": kind,
                "text": _text(node[1]) if len(node) > 1 else "",
                "at": _at3(node), "h": eff["h"], "just": eff["just"],
                "shape": _text(node_value(node, "shape", "input")),
            })

    sheets: list[dict] = []
    for node in iter_nodes(root, "sheet"):
        at = _floats(find_node(node, "at"), 2)
        size = _floats(find_node(node, "size"), 2)
        if not at or not size:
            continue
        pins = []
        for pin in iter_nodes(node, "pin"):
            eff = _effects(pin)
            pins.append({
                "name": _text(pin[1]) if len(pin) > 1 else "",
                "shape": _text(pin[2]) if len(pin) > 2 else "input",
                "at": _at3(pin), "h": eff["h"], "just": eff["just"],
            })
        sheets.append({
            "at": at, "size": size, "pins": pins, "fields": _fields(node),
            "w": _stroke_width(node), "fill": _fill(node),
        })

    texts: list[dict] = []
    for node in iter_nodes(root, "text"):
        eff = _effects(node)
        body = _text(node[1]) if len(node) > 1 else ""
        texts.append({
            "at": _at3(node), "h": eff["h"], "just": eff["just"],
            "bold": eff["bold"], "italic": eff["italic"],
            "text": body.replace("\\n", "\n").replace('\\"', '"'),
            "excluded": _yes(node, "exclude_from_sim"),
        })
    for node in iter_nodes(root, "text_box"):
        eff = _effects(node)
        at = _at3(node)
        size = _floats(find_node(node, "size"), 2) or [0.0, 0.0]
        body = _text(node[1]) if len(node) > 1 else ""
        texts.append({
            "at": at, "box": size, "h": eff["h"], "just": eff["just"],
            "bold": eff["bold"], "italic": eff["italic"],
            "text": body.replace("\\n", "\n").replace('\\"', '"'),
            "excluded": _yes(node, "exclude_from_sim"),
        })

    shapes: list[dict] = []
    for tag in _SHAPE_TAGS:
        for node in iter_nodes(root, tag):
            entry = _shape(node, tag, 0, 1)
            if entry:
                shapes.append(entry)

    junctions = []
    for node in iter_nodes(root, "junction"):
        v = _floats(find_node(node, "at"), 2)
        if v:
            junctions.append({"at": v, "d": _num(node, "diameter", 0.0)})

    no_connects = []
    for node in iter_nodes(root, "no_connect"):
        v = _floats(find_node(node, "at"), 2)
        if v:
            no_connects.append({"at": v})

    bus_entries = []
    for node in iter_nodes(root, "bus_entry"):
        v = _floats(find_node(node, "at"), 2)
        size = _floats(find_node(node, "size"), 2)
        if v and size:
            bus_entries.append({"at": v, "size": size})

    return {
        "libs": libs,
        "symbols": symbols,
        # `w0`, `w1`, ... in the same order `sim_geom` numbers them, so the
        # overlay's net colours land on the right polyline.
        "wires": _line_items(root, "wire", "wire"),
        "buses": _line_items(root, "bus", "bus"),
        "bus_entries": bus_entries,
        "junctions": junctions,
        "no_connects": no_connects,
        "labels": labels,
        "sheets": sheets,
        "texts": texts,
        "shapes": shapes,
    }
