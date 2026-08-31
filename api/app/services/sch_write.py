"""Write a `.kicad_sch` from the editor's document.

The browser owns the document while it is being drawn; this turns it into the
file. Two rules decide everything else here:

1. **The output is a real KiCad file, not an export.** A circuit drawn in the
   browser is opened in KiCad afterwards — that is the whole point of drawing
   it in this format rather than a private one — so the version token, the
   `instances` blocks and the embedded `lib_symbols` are all written the way
   eeschema writes them. A file KiCad has to repair is a file that lost
   something.
2. **This writes NEW sheets only.** Editing a sheet that came from KiCad is a
   different job: that file carries tokens this module does not model, and
   regenerating it from the document would silently drop them. That path
   patches the parsed tree instead, and does not exist yet.

Coordinates are millimetres on the sheet, exactly as the renderer draws them,
so what the user placed is what is written.
"""
from __future__ import annotations

import uuid as uuidlib

from . import sch_lib

# What KiCad 10.0 writes. Matching it matters: eeschema refuses a file from a
# NEWER version outright, and a stale token makes it run a migration the user
# then has to save past.
VERSION = "20260306"
GENERATOR = "7sigma-web"
GENERATOR_VERSION = "10.0"

PAPER_SIZES = ("A0", "A1", "A2", "A3", "A4", "A5", "USLetter", "USLegal", "USLedger")

# Text items on a simulation sheet ARE the harness (`conventions-simulation`),
# so they are written as simulation-visible text, not notes.
_INDENT = "\t"


class WriteError(ValueError):
    pass


def _esc(text: str) -> str:
    """KiCad quotes every string and escapes with backslashes; a newline in a
    text item is written as the two characters `\\n`, and a raw one would end
    the token and break the file."""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
    )


def _n(value) -> str:
    """A number the way KiCad writes one: no exponent, no trailing zeros."""
    f = float(value)
    if f == int(f):
        return str(int(f))
    return f"{f:.6f}".rstrip("0").rstrip(".")


def _uuid(item: dict, key: str = "uuid") -> str:
    got = str(item.get(key) or "").strip()
    return got if got else str(uuidlib.uuid4())


def _effects(size: float = 1.27, just: list[str] | None = None, hide: bool = False) -> str:
    parts = [f"(font (size {_n(size)} {_n(size)}))"]
    if just:
        parts.append("(justify " + " ".join(just) + ")")
    if hide:
        parts.append("(hide yes)")
    return "(effects " + " ".join(parts) + ")"


def _at(x, y, angle=0) -> str:
    return f"(at {_n(x)} {_n(y)} {_n(angle)})"


def _at2(x, y) -> str:
    """A junction and a no-connect have no angle, and KiCad rejects the whole
    FILE — not the item — when one is written with three numbers."""
    return f"(at {_n(x)} {_n(y)})"


def _property(name: str, value: str, x: float, y: float, angle: float,
              *, hide: bool = False, just: list[str] | None = None) -> str:
    return (
        f'(property "{_esc(name)}" "{_esc(value)}" {_at(x, y, angle)} '
        f"(show_name no) (do_not_autoplace no) {_effects(1.27, just, hide)})"
    )


# ------------------------------------------------------------------ symbols

def _place(px: float, py: float, at: list[float], mirror: str) -> tuple[float, float]:
    """Symbol space to sheet space — the same transform `sch_draw` draws with
    and `sim_geom` connects with. Three copies of this would be three chances
    to disagree, so all three read the same comment: the stored angle is
    negated because the y flip reverses the sense of the turn."""
    import math

    x, y, rot = (list(at) + [0.0, 0.0, 0.0])[:3]
    py = -py
    if "x" in mirror:
        py = -py
    if "y" in mirror:
        px = -px
    r = math.radians(-rot)
    c, s = math.cos(r), math.sin(r)
    return x + (px * c - py * s), y + (px * s + py * c)


def _symbol(item: dict, libs: dict, root_uuid: str, project: str) -> str:
    lib_id = str(item.get("lib_id") or "")
    lib = libs.get(lib_id)
    if lib is None:
        raise WriteError(f"unknown symbol {lib_id!r}")
    at = [float(v) for v in (list(item.get("at") or [0, 0, 0]) + [0, 0, 0])[:3]]
    mirror = str(item.get("mirror") or "")
    unit = int(item.get("unit") or 1)
    fields = dict(item.get("fields") or {})
    reference = fields.get("Reference") or "U?"

    rows = [
        f'(lib_id "{_esc(lib_id)}")',
        _at(*at),
        f"(unit {unit})",
        "(body_style 1)",
        "(exclude_from_sim no)",
        "(in_bom yes)",
        "(on_board yes)",
        "(dnp no)",
        f'(uuid "{_uuid(item)}")',
    ]
    if mirror:
        rows.insert(2, f"(mirror {mirror})")

    # Field positions: the ones the document carries, else the library's own,
    # carried onto the sheet through the placement.
    placed = dict(item.get("field_at") or {})
    for prop in lib.get("props", []):
        name = prop["k"]
        value = fields.get(name, prop["v"])
        if name in placed:
            fx, fy, fa = (list(placed[name]) + [0, 0, 0])[:3]
        else:
            fx, fy = _place(prop["at"][0], prop["at"][1], at, mirror)
            fa = prop["at"][2] + at[2]
        rows.append(_property(name, value, fx, fy, fa % 360,
                              hide=bool(prop.get("hide")), just=prop["just"]))
    for name, value in fields.items():
        if name in ("Reference", "Value"):
            continue
        if any(p["k"] == name for p in lib.get("props", [])):
            continue
        rows.append(_property(name, value, at[0], at[1], 0, hide=True))

    for pin in lib.get("pins", []):
        if pin["unit"] in (0, unit):
            rows.append(f'(pin "{_esc(pin["n"])}" (uuid "{uuidlib.uuid4()}"))')

    rows.append(
        f'(instances (project "{_esc(project)}" '
        f'(path "/{root_uuid}" (reference "{_esc(reference)}") (unit {unit}))))'
    )
    return "(symbol " + " ".join(rows) + ")"


# ------------------------------------------------------------------- sheet

def _wires(item: dict) -> list[str]:
    """A KiCad wire is exactly TWO points. A drawn run of several segments is
    several wires, and writing it as one polyline does not draw a long wire —
    it makes eeschema refuse the whole file."""
    pts = [[float(p[0]), float(p[1])] for p in (item.get("pts") or [])]
    out = []
    for i in range(len(pts) - 1):
        (x1, y1), (x2, y2) = pts[i], pts[i + 1]
        if abs(x1 - x2) < 1e-9 and abs(y1 - y2) < 1e-9:
            continue
        uid = _uuid(item) if i == 0 else str(uuidlib.uuid4())
        out.append(
            f"(wire (pts (xy {_n(x1)} {_n(y1)}) (xy {_n(x2)} {_n(y2)})) "
            f'(stroke (width 0) (type default)) (uuid "{uid}"))'
        )
    return out


_LABEL_TAG = {"local": "label", "global": "global_label", "hier": "hierarchical_label"}


def _label(item: dict) -> str:
    kind = str(item.get("kind") or "local")
    tag = _LABEL_TAG.get(kind, "label")
    at = (list(item.get("at") or [0, 0, 0]) + [0, 0, 0])[:3]
    # A label points along the wire it names, and KiCad stores the
    # justification of the text AS DRAWN — right for a label that runs left.
    just = ["right"] if 90 < (at[2] % 360) < 270 else ["left"]
    shape = f' (shape {item.get("shape") or "input"})' if kind != "local" else ""
    return (
        f'({tag} "{_esc(item.get("text", ""))}"{shape} {_at(*at)} '
        f'{_effects(1.27, just)} (uuid "{_uuid(item)}"))'
    )


def _text(item: dict) -> str:
    at = (list(item.get("at") or [0, 0, 0]) + [0, 0, 0])[:3]
    excluded = "yes" if item.get("excluded") else "no"
    return (
        f'(text "{_esc(item.get("text", ""))}" (exclude_from_sim {excluded}) '
        f'{_at(*at)} {_effects(float(item.get("h") or 1.27), ["left", "top"])} '
        f'(uuid "{_uuid(item)}"))'
    )


def document_to_sch(doc: dict) -> str:
    """The editor's document as a `.kicad_sch` file."""
    libs = sch_lib.draw_library()
    paper = str(doc.get("paper") or "A4")
    if paper not in PAPER_SIZES:
        paper = "A4"
    root_uuid = str(doc.get("uuid") or uuidlib.uuid4())
    project = str(doc.get("name") or "sketch")

    body: list[str] = [
        f"(version {VERSION})",
        f'(generator "{GENERATOR}")',
        f'(generator_version "{GENERATOR_VERSION}")',
        f'(uuid "{root_uuid}")',
        f'(paper "{paper}")',
        sch_lib.lib_symbols_block(),
    ]
    for junction in doc.get("junctions") or []:
        body.append(
            f"(junction {_at2(junction[0], junction[1])} (diameter 0) "
            f'(color 0 0 0 0) (uuid "{uuidlib.uuid4()}"))'
        )
    for nc in doc.get("no_connects") or []:
        body.append(f'(no_connect {_at2(nc[0], nc[1])} (uuid "{uuidlib.uuid4()}"))')
    for wire in doc.get("wires") or []:
        body.extend(_wires(wire))
    for label in doc.get("labels") or []:
        body.append(_label(label))
    for text in doc.get("texts") or []:
        body.append(_text(text))
    for symbol in doc.get("symbols") or []:
        body.append(_symbol(symbol, libs, root_uuid, project))
    body.append('(sheet_instances (path "/" (page "1")))')
    body.append("(embedded_fonts no)")
    return "(kicad_sch\n" + "\n".join(_INDENT + row for row in body) + "\n)\n"


def document_to_pro(doc: dict) -> str:
    """A minimal project file. kicad-cli netlists a `.kicad_sch` without one,
    but KiCad opens a project, not a sheet, and a user who downloads this is
    going to double-click something."""
    import json

    name = str(doc.get("name") or "sketch")
    return json.dumps({
        "board": {"design_settings": {}},
        "meta": {"filename": f"{name}.kicad_pro", "version": 3},
        "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},
        "sheets": [[str(doc.get("uuid") or ""), "Root"]],
    }, indent=2) + "\n"
