"""Interactive click-maps for the schematic and board viewers.

The kicad-cli SVG exports are plain drawings (no element ids), so hit areas
are computed from the source files instead: symbol/footprint anchor + an
approximate bounding box, in the same mm coordinate space as the exported
SVG's viewBox. The frontend overlays transparent hotspots scaled by the
page/board size — a click shows the matched BOM line and links to the
library component; sub-sheet rectangles navigate between schematic pages.

Coordinates are approximate by design (rotation/mirror conventions and pad
shapes are simplified to conservative boxes); hotspots only need to cover
the part. Cached in MinIO per commit sha (bump MAP_VERSION on format change).
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path, PurePosixPath

from sqlalchemy.orm import Session

from .. import models as M
from ..util.sexpr import find_node, iter_nodes, node_value, parse_sexpr, walk_nodes
from . import gitrepo, project_render, storage

log = logging.getLogger(__name__)

MAP_VERSION = 1

# (paper "A4") sizes in mm, landscape; a (portrait) token swaps them.
PAPER_MM = {
    "A0": (1189.0, 841.0), "A1": (841.0, 594.0), "A2": (594.0, 420.0),
    "A3": (420.0, 297.0), "A4": (297.0, 210.0), "A5": (210.0, 148.0),
    "A": (279.4, 215.9), "B": (431.8, 279.4), "C": (558.8, 431.8),
    "Letter": (279.4, 215.9), "Legal": (355.6, 215.9), "Tabloid": (431.8, 279.4),
    "USLetter": (279.4, 215.9), "USLegal": (355.6, 215.9), "USLedger": (431.8, 279.4),
}


def _floats(node, count: int) -> list[float] | None:
    try:
        return [float(str(v)) for v in node[1 : 1 + count]]
    except (TypeError, ValueError, IndexError):
        return None


def _at(node) -> tuple[float, float, float]:
    at = find_node(node, "at")
    if at is None:
        return 0.0, 0.0, 0.0
    vals = []
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


class _BBox:
    def __init__(self):
        self.x1 = self.y1 = math.inf
        self.x2 = self.y2 = -math.inf

    def add(self, x: float, y: float):
        self.x1 = min(self.x1, x)
        self.y1 = min(self.y1, y)
        self.x2 = max(self.x2, x)
        self.y2 = max(self.y2, y)

    def ok(self) -> bool:
        return self.x1 <= self.x2

    def pad(self, m: float) -> list[float]:
        return [self.x1 - m, self.y1 - m, self.x2 + m, self.y2 + m]


def _shape_points(shape) -> list[tuple[float, float]]:
    """Coordinate points of a graphic item (enough for a bbox)."""
    pts: list[tuple[float, float]] = []
    for tag in ("start", "end", "mid", "center"):
        node = find_node(shape, tag)
        if node is not None:
            v = _floats(node, 2)
            if v:
                pts.append((v[0], v[1]))
    pts_node = find_node(shape, "pts")
    if pts_node is not None:
        for xy in iter_nodes(pts_node, "xy"):
            v = _floats(xy, 2)
            if v:
                pts.append((v[0], v[1]))
    # circle: center ± radius (radius = |center-end|, end already collected)
    center = find_node(shape, "center")
    end = find_node(shape, "end")
    if center is not None and end is not None:
        c, e = _floats(center, 2), _floats(end, 2)
        if c and e:
            r = math.hypot(e[0] - c[0], e[1] - c[1])
            pts += [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
    return pts


def _rot(px: float, py: float, deg: float) -> tuple[float, float]:
    rad = math.radians(deg)
    c, s = math.cos(rad), math.sin(rad)
    return px * c + py * s, -px * s + py * c


# ---------------------------------------------------------------- schematic

def _lib_bboxes(root) -> dict[str, list[float]]:
    """lib_id -> bbox in symbol coords (y-up) from the embedded lib_symbols."""
    out: dict[str, list[float]] = {}
    lib = find_node(root, "lib_symbols")
    if lib is None:
        return out
    for sym in iter_nodes(lib, "symbol"):
        lib_id = str(sym[1]).strip('"')
        box = _BBox()
        for tag in ("rectangle", "polyline", "circle", "arc"):
            for shape in walk_nodes(sym, tag):
                for x, y in _shape_points(shape):
                    box.add(x, y)
        for pin in walk_nodes(sym, "pin"):
            at = find_node(pin, "at")
            if at is None:
                continue
            v = _floats(at, 2)
            if not v:
                continue
            box.add(v[0], v[1])
            try:
                length = float(node_value(pin, "length", 0) or 0)
                rot = float(str(at[3])) if len(at) > 3 else 0.0
            except (TypeError, ValueError):
                length, rot = 0.0, 0.0
            box.add(v[0] + length * math.cos(math.radians(rot)),
                    v[1] + length * math.sin(math.radians(rot)))
        if box.ok():
            out[lib_id] = [box.x1, box.y1, box.x2, box.y2]
    return out


def _paper_size(root) -> list[float]:
    paper = find_node(root, "paper")
    if paper is None:
        return [297.0, 210.0]
    name = str(paper[1]).strip('"') if len(paper) > 1 else "A4"
    if name == "User":
        try:  # (paper "User" w h)
            return [float(str(paper[2])), float(str(paper[3]))]
        except (TypeError, ValueError, IndexError):
            return [297.0, 210.0]
    w, h = PAPER_MM.get(name, (297.0, 210.0))
    if any(str(tok) == "portrait" for tok in paper):
        w, h = h, w
    return [w, h]


def parse_schematic_sheet(text: str) -> dict:
    """One .kicad_sch file -> {size, symbols, subsheets}."""
    root = parse_sexpr(text)
    lib_boxes = _lib_bboxes(root)
    symbols = []
    for sym in iter_nodes(root, "symbol"):
        lib_id = node_value(sym, "lib_id", "") or ""
        ref = _property(sym, "Reference")
        if not ref or ref.startswith("#") or lib_id.startswith("power:"):
            continue
        x, y, rot = _at(sym)
        mirror = node_value(sym, "mirror", "") or ""
        box = _BBox()
        lb = lib_boxes.get(lib_id)
        corners = (
            [(lb[0], lb[1]), (lb[0], lb[3]), (lb[2], lb[1]), (lb[2], lb[3])]
            if lb else [(-2.54, -2.54), (2.54, 2.54), (-2.54, 2.54), (2.54, -2.54)]
        )
        for px, py in corners:
            py = -py  # lib coords are y-up; sheet coords are y-down
            if "x" in mirror:
                py = -py
            if "y" in mirror:
                px = -px
            rx, ry = _rot(px, py, rot)
            box.add(x + rx, y + ry)
        symbols.append({
            "ref": ref,
            "value": _property(sym, "Value"),
            "lib_id": lib_id,
            "at": [x, y],
            "bbox": box.pad(0.7),
        })
    subsheets = []
    for sheet in iter_nodes(root, "sheet"):
        at = find_node(sheet, "at")
        size = find_node(sheet, "size")
        if at is None or size is None:
            continue
        a, s = _floats(at, 2), _floats(size, 2)
        if not a or not s:
            continue
        subsheets.append({
            "name": _property(sheet, "Sheetname", "Sheet name"),
            "file": _property(sheet, "Sheetfile", "Sheet file"),
            "at": a,
            "size": s,
        })
    return {"size": _paper_size(root), "symbols": symbols, "subsheets": subsheets}


# -------------------------------------------------------------------- board

_EDGE_TAGS = ("gr_line", "gr_rect", "gr_arc", "gr_circle", "gr_poly",
              "fp_line", "fp_rect", "fp_arc", "fp_circle", "fp_poly")


def parse_board(text: str) -> dict:
    root = parse_sexpr(text)
    edges = _BBox()
    for tag in _EDGE_TAGS:
        for shape in walk_nodes(root, tag):
            if node_value(shape, "layer", "") != "Edge.Cuts":
                continue
            for x, y in _shape_points(shape):
                edges.add(x, y)
    footprints = []
    for fp in iter_nodes(root, "footprint"):
        ref = _property(fp, "Reference")
        if not ref:
            continue
        x, y, rot = _at(fp)
        side = "B" if (node_value(fp, "layer", "") or "").startswith("B.") else "F"
        box = _BBox()
        for pad in iter_nodes(fp, "pad"):
            pat = find_node(pad, "at")
            psize = find_node(pad, "size")
            pv = _floats(pat, 2) if pat is not None else None
            sv = _floats(psize, 2) if psize is not None else None
            if not pv:
                continue
            half = max(sv) / 2 if sv else 0.5
            # conservative square around the pad center — rotation/mirror safe
            for cx, cy in ((pv[0] - half, pv[1] - half), (pv[0] + half, pv[1] + half),
                           (pv[0] - half, pv[1] + half), (pv[0] + half, pv[1] - half)):
                rx, ry = _rot(cx, cy, rot)
                box.add(x + rx, y + ry)
        if not box.ok():
            box.add(x - 1, y - 1)
            box.add(x + 1, y + 1)
        footprints.append({
            "ref": ref,
            "value": _property(fp, "Value"),
            "at": [x, y],
            "side": side,
            "bbox": box.pad(0.3),
        })
    origin = [edges.x1, edges.y1] if edges.ok() else [0.0, 0.0]
    size = [edges.x2 - edges.x1, edges.y2 - edges.y1] if edges.ok() else [100.0, 100.0]
    return {"origin": origin, "size": size, "footprints": footprints}


# ---------------------------------------------------------------- assembly

def _bom_lookup(db: Session, snapshot: M.ProjectSnapshot, board_name: str) -> dict[str, dict]:
    """reference -> BOM line info (default variant). Handles both explicit
    ref lists and legacy `C7-C9` ranges from older snapshots."""
    import re

    out: dict[str, dict] = {}
    lines = (
        db.query(M.SnapshotBomLine)
        .filter_by(snapshot_id=snapshot.id, board=board_name, variant="")
        .all()
    )
    range_re = re.compile(r"^([A-Za-z_]+)(\d+)-([A-Za-z_]+)?(\d+)$")
    for li in lines:
        info = {
            "component_id": li.component_id,
            "lcsc": li.lcsc,
            "value": li.value,
            "footprint": li.footprint,
            "mpn": li.mpn,
            "dnp": li.dnp,
        }
        for token in li.refs.split(","):
            token = token.strip()
            if not token:
                continue
            m = range_re.match(token)
            if m and (m.group(3) is None or m.group(3) == m.group(1)):
                prefix, lo, hi = m.group(1), int(m.group(2)), int(m.group(4))
                for n in range(lo, hi + 1):
                    out[f"{prefix}{n}"] = info
            else:
                out[token] = info
    return out


def build_map(db: Session, snapshot: M.ProjectSnapshot, board: dict) -> dict:
    """Full interactive map for one board of a snapshot; MinIO-cached."""
    key = project_render.render_key(
        snapshot.project_id, snapshot.sha, board["name"], f"map-v{MAP_VERSION}.json"
    )
    cached = storage.get_bytes(key)
    if cached is not None:
        return json.loads(cached)

    checkout = gitrepo.materialize(snapshot.project_id, snapshot.sha)
    result: dict = {"pcb": None, "sheets": {}}

    if board.get("pcb"):
        try:
            result["pcb"] = parse_board((checkout / board["pcb"]).read_text(encoding="utf-8"))
        except Exception as e:
            log.warning(f"pcb map failed for {board['name']}: {e}")

    if board.get("sch"):
        root_rel = PurePosixPath(board["sch"])
        board_name = board["name"]
        # svg page name -> sch file, walking the sheet tree breadth-first
        todo: list[tuple[str, PurePosixPath]] = [(f"{board_name}.svg", root_rel)]
        seen: set[str] = set()
        while todo:
            svg_name, rel = todo.pop(0)
            if svg_name in seen:
                continue
            seen.add(svg_name)
            path = checkout / rel
            if not path.is_file():
                continue
            try:
                sheet = parse_schematic_sheet(path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"schematic map failed for {rel}: {e}")
                continue
            for sub in sheet["subsheets"]:
                target = f"{board_name}-{sub['name']}.svg"
                sub["target_svg"] = target
                sub_rel = (rel.parent / sub["file"]) if sub.get("file") else None
                if sub_rel is not None:
                    todo.append((target, PurePosixPath(Path(*sub_rel.parts))))
            result["sheets"][svg_name] = sheet

    # enrich symbols/footprints with the matched BOM line
    bom = _bom_lookup(db, snapshot, board["name"])
    comp_names: dict[int, str] = {}
    ids = {v["component_id"] for v in bom.values() if v["component_id"]}
    if ids:
        for c in db.query(M.Component).filter(M.Component.id.in_(ids)).all():
            comp_names[c.id] = c.name
    def enrich(entry: dict):
        info = bom.get(entry["ref"])
        if info:
            entry["bom"] = {**info, "component_name": comp_names.get(info["component_id"] or -1)}
    if result["pcb"]:
        for fp in result["pcb"]["footprints"]:
            enrich(fp)
    for sheet in result["sheets"].values():
        for sym in sheet["symbols"]:
            enrich(sym)

    storage.put_bytes(key, json.dumps(result).encode(), "application/json")
    return result
