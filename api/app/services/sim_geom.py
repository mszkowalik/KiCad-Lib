"""Schematic geometry for the web simulator overlay.

One `.kicad_sch` -> the wires, pins, labels and symbol boxes the browser draws
current and voltage on, in millimetres. The coordinates are the ones in the
file, which is also the coordinate space of `kicad-cli sch export svg`
(verified: a wire endpoint at 212.09 mm appears as 212.0900 in the SVG path
data), so the overlay needs no transform — it shares the SVG's viewBox.

Net names are NOT derived here. KiCad's naming rules (hierarchy prefixes,
power symbols, `Net-_R1-Pad2_` fallbacks) are its own business, so this module
only works out WHICH pins each wire reaches, and `assign_nets` reads the names
off the kicadxml netlist by pin membership. Reimplementing the rules would
give an overlay that quietly disagrees with the simulation.

Hierarchy: geometry is per sheet INSTANCE, not per file. One sheet file can be
placed twice (KiCad's own complex_hierarchy demo does), and the two instances
carry different references and different net names, so every call takes the
instance path that `sheet_tree` produced.
"""
from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from ..util.sexpr import find_node, iter_nodes, node_value, parse_sexpr, sanitize_symbol_text, walk_nodes

# Quantum for point identity, in mm. KiCad writes schematic coordinates on a
# 0.01 mm grid at worst; 0.001 mm absorbs float formatting without ever
# merging two points a user could tell apart.
_Q = 1000.0
_EPS = 1e-6

PAPER_MM = {
    "A0": (1189.0, 841.0), "A1": (841.0, 594.0), "A2": (594.0, 420.0),
    "A3": (420.0, 297.0), "A4": (297.0, 210.0), "A5": (210.0, 148.0),
    "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8),
    "D": (863.6, 558.8), "E": (1117.6, 863.6),
    "USLetter": (279.4, 215.9), "USLegal": (355.6, 215.9), "USLedger": (431.8, 279.4),
}

_LABEL_TAGS = {
    "label": "local",
    "global_label": "global",
    "hierarchical_label": "hier",
}


class GeomError(RuntimeError):
    pass


# ------------------------------------------------------------------ helpers

def _floats(node, count: int) -> list[float] | None:
    try:
        return [float(str(v)) for v in node[1 : 1 + count]]
    except (TypeError, ValueError, IndexError):
        return None


def _at(node) -> tuple[float, float, float]:
    at = find_node(node, "at")
    if at is None:
        return 0.0, 0.0, 0.0
    vals: list[float] = []
    for v in at[1:4]:
        try:
            vals.append(float(str(v)))
        except (TypeError, ValueError):
            break
    while len(vals) < 3:
        vals.append(0.0)
    return vals[0], vals[1], vals[2]


def _property(node, *names: str) -> str:
    wanted = {n.lower() for n in names}
    for prop in iter_nodes(node, "property"):
        if len(prop) > 2 and str(prop[1]).strip('"').lower() in wanted:
            return str(prop[2]).strip('"')
    return ""


def _uuid(node) -> str:
    return str(node_value(node, "uuid", "") or "").strip('"')


def _key(x: float, y: float) -> tuple[int, int]:
    return int(round(x * _Q)), int(round(y * _Q))


def _rot(px: float, py: float, deg: float) -> tuple[float, float]:
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    return px * c - py * s, px * s + py * c


def _paper_size(root) -> list[float]:
    paper = find_node(root, "paper")
    if paper is None:
        return [297.0, 210.0]
    name = str(paper[1]).strip('"') if len(paper) > 1 else "A4"
    if name == "User":
        v = _floats(paper[1:], 2)
        return v if v else [297.0, 210.0]
    w, h = PAPER_MM.get(name, (297.0, 210.0))
    if any(str(tok) == "portrait" for tok in paper):
        w, h = h, w
    return [w, h]


class _DSU:
    def __init__(self):
        self.parent: dict = {}

    def find(self, a):
        self.parent.setdefault(a, a)
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def union(self, a, b) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _on_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> bool:
    """True when p lies on segment a-b (endpoints excluded — those already
    share a point key)."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    cross = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
    if abs(cross) > 1e-4:
        return False
    dot = (px - ax) * (bx - ax) + (py - ay) * (by - ay)
    length = (bx - ax) ** 2 + (by - ay) ** 2
    return _EPS < dot < length - _EPS


# --------------------------------------------------------------- lib symbols

def _lib_units(root) -> dict[str, dict]:
    """lib_id -> {"pins": [{number, name, type, at:(x,y,angle), length, unit}],
    "bbox": [x1,y1,x2,y2]} in symbol coordinates (y-up)."""
    out: dict[str, dict] = {}
    lib = find_node(root, "lib_symbols")
    if lib is None:
        return out
    for sym in iter_nodes(lib, "symbol"):
        lib_id = str(sym[1]).strip('"')
        pins: list[dict] = []
        xs: list[float] = []
        ys: list[float] = []
        for sub in iter_nodes(sym, "symbol"):
            # Sub-symbol names are "<name>_<unit>_<bodystyle>"; unit 0 is the
            # part common to every unit.
            m = re.search(r"_(\d+)_(\d+)$", str(sub[1]).strip('"'))
            unit = int(m.group(1)) if m else 0
            for pin in iter_nodes(sub, "pin"):
                at = find_node(pin, "at")
                v = _floats(at, 2) if at is not None else None
                if not v:
                    continue
                try:
                    angle = float(str(at[3])) if len(at) > 3 else 0.0
                except (TypeError, ValueError):
                    angle = 0.0
                try:
                    length = float(node_value(pin, "length", 0) or 0)
                except (TypeError, ValueError):
                    length = 0.0
                num_node = find_node(pin, "number")
                name_node = find_node(pin, "name")
                pins.append({
                    "number": str(num_node[1]).strip('"') if num_node is not None and len(num_node) > 1 else "",
                    "name": str(name_node[1]).strip('"') if name_node is not None and len(name_node) > 1 else "",
                    "type": str(pin[1]) if len(pin) > 1 else "",
                    "at": (v[0], v[1], angle),
                    "length": length,
                    "unit": unit,
                })
                # `at` IS the connection point (the wire end); the stub runs
                # from there towards the symbol body along `angle`.
                ex, ey = v[0] + length * math.cos(math.radians(angle)), v[1] + length * math.sin(math.radians(angle))
                xs += [v[0], ex]
                ys += [v[1], ey]
            for tag in ("rectangle", "polyline", "circle", "arc"):
                for shape in walk_nodes(sub, tag):
                    for pt in ("start", "end", "center", "mid", "xy"):
                        for node in walk_nodes(shape, pt):
                            v = _floats(node, 2)
                            if v:
                                xs.append(v[0])
                                ys.append(v[1])
        out[lib_id] = {
            "pins": pins,
            "bbox": [min(xs), min(ys), max(xs), max(ys)] if xs else [-2.54, -2.54, 2.54, 2.54],
        }
    return out


def _place(px: float, py: float, at: tuple[float, float, float], mirror: str) -> tuple[float, float]:
    """Symbol-local (y-up) -> sheet coordinates (y-down).

    The stored angle is NEGATED: KiCad turns a symbol counter-clockwise as the
    user sees it, and the y-flip into sheet coordinates reverses the sense of
    that turn. Checked against the netlist rather than reasoned about — with
    +angle, a 270-degree resistor hands pin 1 the position of pin 2, and the
    overlay then colours the wrong wire.
    """
    x, y, rot = at
    py = -py  # library coordinates are y-up, the sheet is y-down
    if "x" in mirror:
        py = -py
    if "y" in mirror:
        px = -px
    rx, ry = _rot(px, py, -rot)
    return x + rx, y + ry


# -------------------------------------------------------------- sheet tree

def sheet_tree(root_file: str | Path) -> list[dict]:
    """Walk the hierarchy from the root sheet.

    Returns one entry per sheet INSTANCE, root first:
    {name, file (absolute), path (instance path), page, depth}. A file placed
    twice appears twice, with different paths.
    """
    root_file = Path(root_file).resolve()
    root = parse_sexpr(sanitize_symbol_text(root_file.read_text(encoding="utf-8")))
    root_uuid = _uuid(root)
    out: list[dict] = [{
        "name": root_file.stem, "file": str(root_file), "path": f"/{root_uuid}",
        "page": "1", "depth": 0,
    }]
    seen: set[str] = set()

    def walk(node, base_path: str, folder: Path, depth: int) -> None:
        for sheet in iter_nodes(node, "sheet"):
            uuid = _uuid(sheet)
            name = _property(sheet, "Sheetname", "Sheet name") or "sheet"
            rel = _property(sheet, "Sheetfile", "Sheet file")
            if not rel or not uuid:
                continue
            path = f"{base_path}/{uuid}"
            if path in seen:
                continue
            seen.add(path)
            target = (folder / rel).resolve()
            entry = {"name": name, "file": str(target), "path": path,
                     "page": "", "depth": depth + 1}
            out.append(entry)
            if not target.exists():
                entry["error"] = f"sub-sheet file not found: {rel}"
                continue
            try:
                child = parse_sexpr(sanitize_symbol_text(target.read_text(encoding="utf-8")))
            except (OSError, ValueError) as e:
                entry["error"] = f"cannot read sub-sheet: {e}"
                continue
            walk(child, path, target.parent, depth + 1)

    walk(root, f"/{root_uuid}", root_file.parent, 0)
    return out


# ---------------------------------------------------------------- geometry

def sheet_geometry(text: str, instance_path: str = "") -> dict:
    """One sheet file, one instance -> the overlay's geometry.

    `groups` is the connectivity result: each group lists the pins on it and
    the ids of the wires and labels that belong to it. Net names arrive later
    from `assign_nets`.
    """
    root = parse_sexpr(sanitize_symbol_text(text))
    libs = _lib_units(root)
    dsu = _DSU()
    warnings: list[str] = []

    wires: list[dict] = []
    for i, wire in enumerate(iter_nodes(root, "wire")):
        pts_node = find_node(wire, "pts")
        pts: list[list[float]] = []
        if pts_node is not None:
            for xy in iter_nodes(pts_node, "xy"):
                v = _floats(xy, 2)
                if v:
                    pts.append(v)
        if len(pts) < 2:
            continue
        keys = [_key(*p) for p in pts]
        for a, b in zip(keys, keys[1:], strict=False):
            dsu.union(a, b)
        wires.append({"id": f"w{i}", "pts": pts, "keys": keys, "net": None})

    junctions: list[dict] = []
    for junction in iter_nodes(root, "junction"):
        v = _floats(find_node(junction, "at"), 2) if find_node(junction, "at") else None
        if v:
            junctions.append({"at": v, "net": None})

    labels: list[dict] = []
    for tag, kind in _LABEL_TAGS.items():
        for i, node in enumerate(iter_nodes(root, tag)):
            x, y, rot = _at(node)
            labels.append({
                "id": f"l{kind}{i}", "text": str(node[1]).strip('"') if len(node) > 1 else "",
                "kind": kind, "at": [x, y], "angle": rot, "key": _key(x, y), "net": None,
            })
            dsu.find(_key(x, y))

    # Sub-sheet boxes and their pins. A sheet pin is a connection point on the
    # parent sheet; the wire that reaches it belongs to the child's net.
    subsheets: list[dict] = []
    for sheet in iter_nodes(root, "sheet"):
        at = find_node(sheet, "at")
        size = find_node(sheet, "size")
        a = _floats(at, 2) if at is not None else None
        s = _floats(size, 2) if size is not None else None
        if not a or not s:
            continue
        pins = []
        for pin in iter_nodes(sheet, "pin"):
            px, py, prot = _at(pin)
            pins.append({"name": str(pin[1]).strip('"') if len(pin) > 1 else "",
                         "at": [px, py], "angle": prot, "key": _key(px, py), "net": None})
            dsu.find(_key(px, py))
        subsheets.append({
            "name": _property(sheet, "Sheetname", "Sheet name"),
            "file": _property(sheet, "Sheetfile", "Sheet file"),
            "uuid": _uuid(sheet), "at": a, "size": s, "pins": pins,
        })

    no_connects = []
    for nc in iter_nodes(root, "no_connect"):
        v = _floats(find_node(nc, "at"), 2) if find_node(nc, "at") else None
        if v:
            no_connects.append({"at": v, "key": _key(*v)})

    symbols: list[dict] = []
    pins_out: list[dict] = []
    for idx, sym in enumerate(iter_nodes(root, "symbol")):
        lib_id = node_value(sym, "lib_id", "") or ""
        lib_id = str(lib_id).strip('"')
        at = _at(sym)
        mirror = str(node_value(sym, "mirror", "") or "")
        try:
            unit = int(float(str(node_value(sym, "unit", 1) or 1)))
        except (TypeError, ValueError):
            unit = 1
        ref = _instance_ref(sym, instance_path) or _property(sym, "Reference")
        is_power = lib_id.startswith("power:") or ref.startswith("#")
        lib = libs.get(lib_id)
        box = None
        if lib:
            corners = [(lib["bbox"][0], lib["bbox"][1]), (lib["bbox"][0], lib["bbox"][3]),
                       (lib["bbox"][2], lib["bbox"][1]), (lib["bbox"][2], lib["bbox"][3])]
            placed = [_place(cx, cy, at, mirror) for cx, cy in corners]
            xs = [p[0] for p in placed]
            ys = [p[1] for p in placed]
            box = [min(xs) - 0.7, min(ys) - 0.7, max(xs) + 0.7, max(ys) + 0.7]
            for pin in lib["pins"]:
                if pin["unit"] not in (0, unit):
                    continue
                pax, pay, pangle = pin["at"]
                # Connection point first, then the body end of the stub — the
                # overlay draws current arrows along that direction.
                cx, cy = _place(pax, pay, at, mirror)
                bx = pax + pin["length"] * math.cos(math.radians(pangle))
                by = pay + pin["length"] * math.sin(math.radians(pangle))
                bx, by = _place(bx, by, at, mirror)
                key = _key(cx, cy)
                dsu.find(key)
                pins_out.append({
                    "ref": ref, "pin": pin["number"], "name": pin["name"], "type": pin["type"],
                    "at": [cx, cy], "root": [bx, by], "key": key,
                    "power": is_power, "net": None,
                })
        else:
            warnings.append(f"{ref or lib_id}: symbol is not in the file's lib_symbols")
        symbols.append({
            "ref": ref, "value": _property(sym, "Value"), "lib_id": lib_id,
            "at": [at[0], at[1]], "angle": at[2], "mirror": mirror, "unit": unit,
            "bbox": box, "power": is_power, "index": idx,
            "sim": _sim_props(sym),
        })

    texts: list[dict] = []
    for node in iter_nodes(root, "text"):
        body = str(node[1]).strip('"') if len(node) > 1 else ""
        x, y, _ = _at(node)
        excluded = str(node_value(node, "exclude_from_sim", "no") or "no").strip('"') == "yes"
        decoded = body.replace("\\n", "\n").replace('\\"', '"')
        texts.append({
            "at": [x, y], "text": decoded,
            "directive": (not excluded) and decoded.lstrip().startswith("."),
        })

    # A pin or label that lands in the MIDDLE of a wire is connected — KiCad
    # draws the junction dot for it. Endpoints already share a point key.
    stops = [p["key"] for p in pins_out] + [lb["key"] for lb in labels]
    stops += [sp["key"] for sub in subsheets for sp in sub["pins"]]
    stops += [_key(*j["at"]) for j in junctions]
    for wire in wires:
        for a, b in zip(wire["pts"], wire["pts"][1:], strict=False):
            for key in stops:
                p = (key[0] / _Q, key[1] / _Q)
                if _on_segment(p, (a[0], a[1]), (b[0], b[1])):
                    dsu.union(_key(*a), key)

    groups: dict[str, dict] = {}

    def group_id(key) -> str:
        root_key = dsu.find(key)
        return f"g{root_key[0]}_{root_key[1]}"

    for item, field in ((wires, "keys"), (labels, "key"), (pins_out, "key")):
        for entry in item:
            keys = entry[field] if field == "keys" else [entry[field]]
            gid = group_id(keys[0])
            entry["group"] = gid
            groups.setdefault(gid, {"id": gid, "pins": [], "labels": [], "wires": [], "net": None})
    for wire in wires:
        groups[wire["group"]]["wires"].append(wire["id"])
    for label in labels:
        groups[label["group"]]["labels"].append(label["text"])
    for pin in pins_out:
        groups[pin["group"]]["pins"].append({"ref": pin["ref"], "pin": pin["pin"]})
    for sub in subsheets:
        for sp in sub["pins"]:
            sp["group"] = group_id(sp["key"])
            groups.setdefault(sp["group"], {"id": sp["group"], "pins": [], "labels": [],
                                            "wires": [], "net": None})
            groups[sp["group"]]["labels"].append(sp["name"])
    for junction in junctions:
        junction["group"] = group_id(_key(*junction["at"]))

    if any(True for _ in iter_nodes(root, "bus")) or any(True for _ in iter_nodes(root, "bus_entry")):
        warnings.append("this sheet uses buses — bus members are not traced in the overlay yet")

    for wire in wires:
        wire.pop("keys", None)
    for pin in pins_out:
        pin.pop("key", None)
    for label in labels:
        label.pop("key", None)

    return {
        "size": _paper_size(root), "instance_path": instance_path,
        "wires": wires, "junctions": junctions, "labels": labels, "pins": pins_out,
        "symbols": symbols, "subsheets": subsheets, "no_connects": no_connects,
        "texts": texts, "groups": list(groups.values()), "warnings": warnings,
    }


def _instance_ref(sym, instance_path: str) -> str:
    """Reference this placement carries on the given sheet instance."""
    if not instance_path:
        return ""
    inst = find_node(sym, "instances")
    if inst is None:
        return ""
    for project in iter_nodes(inst, "project"):
        for path in iter_nodes(project, "path"):
            if str(path[1]).strip('"') == instance_path:
                ref = find_node(path, "reference")
                if ref is not None and len(ref) > 1:
                    return str(ref[1]).strip('"')
    return ""


def _sim_props(sym) -> dict:
    """The Sim.* fields on a placement, so the UI knows what the netlister
    will make of the part and which parameters it may offer as sliders."""
    out = {}
    for prop in iter_nodes(sym, "property"):
        if len(prop) > 2:
            key = str(prop[1]).strip('"')
            if key.lower().startswith("sim."):
                out[key[4:].lower()] = str(prop[2]).strip('"')
    return out


# ------------------------------------------------------------- net names

# KiCad turns a net name into a SPICE node name by replacing the parentheses
# of its generated names: `Net-(C1-Pad2)` becomes `Net-_C1-Pad2_`. ngspice
# then lower-cases everything in the rawfile. `GND` never appears as a vector
# because ngspice aliases it to node 0, which is 0 V by definition.
_GROUND_NAMES = frozenset({"gnd", "0", "gnda", "gndd", "gndpwr"})


def spice_node_name(net_name: str) -> str:
    """Net name as it appears in an ngspice rawfile vector."""
    return net_name.replace("(", "_").replace(")", "_").lower()


def is_ground(net_name: str) -> bool:
    return spice_node_name(net_name) in _GROUND_NAMES


def parse_kicadxml(data: bytes | str) -> dict:
    """kicad-cli's kicadxml netlist -> {(ref, pin): net_name} plus the net list."""
    text = data.decode("utf-8", "replace") if isinstance(data, bytes) else data
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise GeomError(f"cannot parse the kicadxml netlist: {e}") from e
    by_pin: dict[tuple[str, str], str] = {}
    nets: list[dict] = []
    for net in root.findall("./nets/net"):
        name = net.get("name") or ""
        members = []
        for node in net.findall("node"):
            ref, pin = node.get("ref") or "", node.get("pin") or ""
            by_pin[(ref, pin)] = name
            members.append({"ref": ref, "pin": pin})
        nets.append({
            "name": name, "code": net.get("code") or "", "pins": members,
            "spice": spice_node_name(name), "ground": is_ground(name),
        })
    return {"by_pin": by_pin, "nets": nets}


def assign_nets(geom: dict, xml_nets: dict) -> dict:
    """Fill in `net` on every group, wire, pin, label and junction.

    A group takes the net of the pins on it. A group with no pin (a stub into
    a sheet pin, a label with nothing attached yet) falls back to its label
    text, which is what the user sees on the drawing — flagged as `derived` so
    the UI never plots it as if it were a simulated node.
    """
    by_pin: dict[tuple[str, str], str] = xml_nets.get("by_pin", {})
    unnamed: list[str] = []
    for group in geom["groups"]:
        names = {by_pin[(p["ref"], p["pin"])] for p in group["pins"] if (p["ref"], p["pin"]) in by_pin}
        if len(names) == 1:
            group["net"] = names.pop()
        elif len(names) > 1:
            group["net"] = sorted(names)[0]
            group["conflict"] = sorted(names)
            geom["warnings"].append(
                f"group {group['id']} touches more than one net ({', '.join(sorted(names))}) — "
                "the overlay's connectivity disagrees with the netlist here"
            )
        elif group["labels"]:
            group["net"] = group["labels"][0]
            group["derived"] = True
        else:
            unnamed.append(group["id"])
    lookup = {g["id"]: g for g in geom["groups"]}
    for kind in ("wires", "labels", "pins", "junctions"):
        for entry in geom[kind]:
            group = lookup.get(entry.get("group"))
            if group:
                entry["net"] = group["net"]
    for sub in geom["subsheets"]:
        for sp in sub["pins"]:
            group = lookup.get(sp.get("group"))
            if group:
                sp["net"] = group["net"]
    if unnamed:
        geom["warnings"].append(f"{len(unnamed)} wire group(s) reach no pin and carry no label")
    for group in geom["groups"]:
        if group["net"]:
            group["spice"] = spice_node_name(group["net"])
            group["ground"] = is_ground(group["net"])
    return geom
