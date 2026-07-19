"""Build the parsed_json caches from raw KiCad s-expression sources.

The raw text is always the source of truth; these caches exist for search,
rules evaluation and UI display, and are rebuilt on every write.
"""
from __future__ import annotations

from ..util.sexpr import _norm, find_node, node_value, parse_sexpr, sanitize_symbol_text, walk_nodes


def symbol_parsed(source_text: str) -> dict:
    """Extract pins/units metadata from a single-symbol .kicad_sym library text."""
    tree = parse_sexpr(sanitize_symbol_text(source_text))
    pins: list[dict] = []
    unit_names: set[str] = set()

    for sym in walk_nodes(tree, "symbol"):
        name = _norm(sym[1]) if len(sym) > 1 else ""
        if "_" in name:  # unit entries look like NAME_<style>_<unit>
            unit_names.add(name)
        for pin in walk_nodes(sym, "pin"):
            if pin is sym:
                continue
            electrical = _norm(pin[1]) if len(pin) > 1 else ""
            pins.append(
                {
                    "number": node_value(pin, "number", ""),
                    "name": node_value(pin, "name", ""),
                    "type": electrical,
                }
            )

    # Dedup pins that appear in multiple graphical styles of the same unit
    seen: set[str] = set()
    unique_pins = []
    for p in pins:
        if p["number"] not in seen:
            seen.add(p["number"])
            unique_pins.append(p)

    return {
        "pin_count": len(unique_pins),
        "pins": unique_pins,
        "unit_entry_count": len(unit_names),
    }


def footprint_parsed(source_text: str) -> dict:
    """Extract pads/layers/3D metadata from a .kicad_mod text."""
    tree = parse_sexpr(source_text)
    fp = find_node(tree, "footprint") or (tree[0] if tree and isinstance(tree[0], list) else tree)

    pads: list[dict] = []
    for pad in walk_nodes(fp, "pad"):
        entry = {
            "number": _norm(pad[1]) if len(pad) > 1 else "",
            "type": _norm(pad[2]) if len(pad) > 2 else "",
            "shape": _norm(pad[3]) if len(pad) > 3 else "",
        }
        size = find_node(pad, "size")
        if size is not None and len(size) > 2:
            entry["size"] = [float(_norm(size[1])), float(_norm(size[2]))]
        drill = find_node(pad, "drill")
        if drill is not None and len(drill) > 1:
            try:
                entry["drill"] = float(_norm(drill[1]))
            except ValueError:
                pass  # oval drills: (drill oval x y)
        layers = find_node(pad, "layers")
        if layers is not None:
            entry["layers"] = [_norm(x) for x in layers[1:]]
        pads.append(entry)

    models = [node_value([m], "model") or _norm(m[1]) for m in walk_nodes(fp, "model") if len(m) > 1]

    flat = source_text
    return {
        "pad_count": len(pads),
        "pads": pads,
        "models": models,
        "has_courtyard": "F.CrtYd" in flat or "B.CrtYd" in flat,
        "has_fab": "F.Fab" in flat,
        "smd_pad_count": sum(1 for p in pads if p["type"] == "smd"),
        "tht_pad_count": sum(1 for p in pads if p["type"] == "thru_hole"),
    }
