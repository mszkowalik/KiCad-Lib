"""JLC pick-and-place: the rotation and position JLCPCB needs for every part.

Decision 0110. JLCPCB places a part with ITS land and model for the LCSC part
number, and its 0 degrees is that part's own orientation, not KiCad's. So the
correction belongs to the PART, and it lives on the component as two
properties, which the generator emits as symbol fields like any other:

    FT Rotation Offset   degrees, counter-clockwise, the FULL correction
    FT Position Offset   "x,y" in mm, footprint frame, y pointing UP

Both are read by the Fabrication Toolkit plugin (with "Auto Translate" OFF, so
its own name-keyed table is not added on top) and by this module, which writes
the platform's own JLC BOM and CPL. Both keys are non-material
(`signoff.NON_MATERIAL_KEYS`): writing one keeps the sign-off and the review
record.

The formulas below were confirmed in JLC's placement preview on EVSE_20_CTRL
(2026-11-13), top AND bottom side:

    top:     rotation = board angle + offset
    bottom:  rotation = 180 - board angle + offset
"""
from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .. import models as M
from ..util.sexpr import _norm, find_node, iter_nodes, parse_sexpr

ROTATION_KEY = "FT Rotation Offset"
POSITION_KEY = "FT Position Offset"


@dataclass
class Placement:
    """One footprint as placed on the board, in KiCad's frame (y DOWN)."""

    ref: str
    x: float
    y: float
    angle: float
    side: str          # "top" | "bottom"
    smd: bool
    dnp: bool
    excluded: bool     # exclude_from_pos_files


# ------------------------------------------------------------------ the board
def board_placements(pcb_text: str) -> dict[str, Placement]:
    """Every footprint on a `.kicad_pcb`, keyed by reference."""
    tree = parse_sexpr(pcb_text)
    root = tree if tree and _norm(tree[0]) == "kicad_pcb" else (find_node(tree, "kicad_pcb") or tree)
    out: dict[str, Placement] = {}
    for fp in iter_nodes(root, "footprint"):
        ref = ""
        for prop in iter_nodes(fp, "property"):
            if len(prop) > 2 and _norm(prop[1]) == "Reference":
                ref = _norm(prop[2])
                break
        if not ref:
            continue
        at = find_node(fp, "at")
        if at is None or len(at) < 3:
            continue
        layer = find_node(fp, "layer")
        side = "bottom" if layer is not None and len(layer) > 1 and _norm(layer[1]).startswith("B.") else "top"
        attrs: set[str] = set()
        for node in iter_nodes(fp, "attr"):
            attrs.update(_norm(a) for a in node[1:])
        x, y = float(at[1]), float(at[2])
        angle = float(at[3]) if len(at) > 3 else 0.0
        smd = "smd" in attrs
        if not smd:
            # The Fabrication Toolkit places a non-SMD part at the centre of its
            # pads' bounding box, not at the anchor. Do the same, so this CPL and
            # the plugin's agree and one `FT Position Offset` means one thing.
            pts = []
            for pad in iter_nodes(fp, "pad"):
                pat = find_node(pad, "at")
                if pat is not None and len(pat) >= 3:
                    pts.append((float(pat[1]), float(pat[2])))
            if pts:
                cx = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
                cy = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
                dx, dy = _rot(cx, cy, angle)
                x, y = x + dx, y + dy
        out[ref] = Placement(
            ref=ref, x=x, y=y, angle=angle, side=side,
            smd=smd, dnp="dnp" in attrs,
            excluded="exclude_from_pos_files" in attrs,
        )
    return out


# ---------------------------------------------------------------- the formulas
def parse_rotation(value: str | None) -> float | None:
    """The `FT Rotation Offset` value as degrees, or None when unset/unreadable."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def parse_position(value: str | None) -> tuple[float, float] | None:
    """The `FT Position Offset` value "x,y" as mm, or None."""
    if value is None or "," not in str(value):
        return None
    try:
        x, y = (float(v) for v in str(value).split(",", 1))
    except ValueError:
        return None
    return x, y


def _norm_deg(value: float) -> float:
    v = round(value % 360.0, 3)
    return 0.0 if v == 360.0 else v


def cpl_rotation(angle: float, side: str, offset: float | None) -> float:
    """The CPL rotation for a part placed at `angle` on `side`."""
    off = offset or 0.0
    if side == "bottom":
        return _norm_deg(180.0 - angle + off)
    return _norm_deg(angle + off)


def cpl_position(p: Placement, offset_xy: tuple[float, float] | None) -> tuple[float, float]:
    """Mid X / Mid Y in the CPL frame (y UP), with the position offset applied.

    The offset is in the footprint frame with y up, turned by the board angle,
    as the Fabrication Toolkit applies it. On the bottom side the footprint is
    mirrored, so the offset's x flips first. The bottom-side position formula
    is NOT yet confirmed in a JLC preview (the rotation formula is).
    """
    mid_x, mid_y = p.x, -p.y
    if offset_xy is None:
        return round(mid_x, 4), round(mid_y, 4)
    ox, oy = offset_xy
    if p.side == "bottom":
        ox = -ox
    t = math.radians(p.angle)
    mid_x += ox * math.cos(t) - oy * math.sin(t)
    mid_y += ox * math.sin(t) + oy * math.cos(t)
    return round(mid_x, 4), round(mid_y, 4)


# ------------------------------------------------------------- the snapshot BOM
def _bom_lines(db: Session, snapshot_id: int, board: str, variant: str) -> list[M.SnapshotBomLine]:
    return (
        db.query(M.SnapshotBomLine)
        .filter(M.SnapshotBomLine.snapshot_id == snapshot_id,
                M.SnapshotBomLine.board == board,
                M.SnapshotBomLine.variant == (variant or ""))
        .order_by(M.SnapshotBomLine.position).all()
    )


def _component_offsets(db: Session, component_ids: set[int]) -> dict[int, dict[str, str | None]]:
    """`{component_id: {ROTATION_KEY: …, POSITION_KEY: …}}` from the LIVE versions."""
    if not component_ids:
        return {}
    out: dict[int, dict[str, str | None]] = {cid: {} for cid in component_ids}
    rows = (
        db.query(M.Component.id, M.ComponentProperty.key, M.ComponentProperty.value)
        .join(M.ComponentVersion, M.ComponentVersion.id == M.Component.current_version_id)
        .join(M.ComponentProperty, M.ComponentProperty.component_version_id == M.ComponentVersion.id)
        .filter(M.Component.id.in_(component_ids),
                M.ComponentProperty.key.in_((ROTATION_KEY, POSITION_KEY)))
    )
    for cid, key, value in rows:
        out[cid][key] = value
    return out


def expected_placements(db: Session, snapshot_id: int, board: str, variant: str,
                        pcb_text: str) -> dict:
    """What a correct JLC export of this board says, part by part.

    `rows` is one dict per placed reference that JLC assembles (a BOM line with
    an LCSC code, not DNP, not excluded), with the CPL rotation and position.
    `no_offset` lists the references whose component carries no rotation field
    yet: they are exported with the board angle alone, which is right only when
    the part needs no correction.
    """
    placements = board_placements(pcb_text)
    lines = _bom_lines(db, snapshot_id, board, variant)
    offsets = _component_offsets(db, {ln.component_id for ln in lines if ln.component_id})
    rows: list[dict] = []
    bom: list[list[str]] = []
    no_offset: list[str] = []
    not_on_board: list[str] = []
    for ln in lines:
        if ln.dnp or ln.exclude_from_bom or ln.exclude_from_board or not ln.lcsc:
            continue
        refs = [r.strip() for r in (ln.refs or "").split(",") if r.strip()]
        placed: list[str] = []
        props = offsets.get(ln.component_id or -1, {})
        rot_off = parse_rotation(props.get(ROTATION_KEY))
        pos_off = parse_position(props.get(POSITION_KEY))
        for ref in refs:
            p = placements.get(ref)
            if p is None:
                not_on_board.append(ref)
                continue
            if p.dnp or p.excluded:
                continue
            mid_x, mid_y = cpl_position(p, pos_off)
            rows.append({
                "ref": ref, "mid_x": mid_x, "mid_y": mid_y,
                "layer": "Bottom" if p.side == "bottom" else "Top",
                "rotation": cpl_rotation(p.angle, p.side, rot_off),
                "board_angle": p.angle, "offset": rot_off,
                "component_id": ln.component_id, "lcsc": ln.lcsc,
            })
            placed.append(ref)
            if rot_off is None:
                no_offset.append(ref)
        if placed:
            fp_name = (ln.footprint or "").split(":")[-1]
            bom.append([ln.value or "", ",".join(placed), fp_name, ln.lcsc])
    rows.sort(key=lambda r: r["ref"])
    return {"rows": rows, "bom": bom, "no_offset": sorted(no_offset),
            "not_on_board": sorted(not_on_board)}


def jlc_files(expected: dict) -> tuple[bytes, bytes]:
    """The JLC BOM and CPL as CSV bytes, in JLC's own column names."""
    bom = io.StringIO()
    w = csv.writer(bom)
    w.writerow(["Comment", "Designator", "Footprint", "LCSC Part #"])
    w.writerows(expected["bom"])
    cpl = io.StringIO()
    w = csv.writer(cpl)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
    for r in expected["rows"]:
        w.writerow([r["ref"], f"{r['mid_x']:.4f}mm", f"{r['mid_y']:.4f}mm", r["layer"], f"{r['rotation']:g}"])
    return bom.getvalue().encode(), cpl.getvalue().encode()


# ------------------------------------------------------------- checking a CPL
def _col(header: list[str], *names: str) -> int | None:
    low = [h.strip().lower() for h in header]
    for n in names:
        if n in low:
            return low.index(n)
    return None


def check_cpl(expected: dict, cpl_bytes: bytes) -> dict:
    """Compare a CPL file (for example the Fabrication Toolkit's
    `production/positions.csv`) with what a correct export says.

    Only the ROTATION is compared, and only for references both sides list:
    the position needs the board's origin choice, which the file does not say.
    """
    text = cpl_bytes.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return {"checked": 0, "mismatches": []}
    di = _col(rows[0], "designator", "ref")
    ri = _col(rows[0], "rotation", "rot")
    if di is None or ri is None:
        return {"checked": 0, "mismatches": [], "error": "no Designator/Rotation column"}
    want = {r["ref"]: r for r in expected["rows"]}
    mismatches: list[dict] = []
    checked = 0
    for row in rows[1:]:
        if di >= len(row) or ri >= len(row):
            continue
        ref = row[di].strip()
        exp = want.get(ref)
        if exp is None or exp["offset"] is None:
            continue
        try:
            got = _norm_deg(float(row[ri]))
        except ValueError:
            continue
        checked += 1
        if abs(((got - exp["rotation"]) + 180) % 360 - 180) > 0.5:
            mismatches.append({"ref": ref, "file": got, "expected": exp["rotation"],
                               "lcsc": exp["lcsc"], "component_id": exp.get("component_id")})
    return {"checked": checked, "mismatches": mismatches}


# ------------------------------------------------- measuring a correction
def _pad_number(raw) -> str:
    """A pad number as text. easyeda2kicad writes `(pad 1 …)` unquoted, which
    the parser reads as the NUMBER 1.0, while our footprints say `(pad "1" …)`.
    Without this, no pad of a JLC land matched ours (found 2026-11-13)."""
    s = "" if raw is None else str(raw).strip().strip('"')
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f.is_integer() else s


def _pad_centres(kicad_mod_text: str) -> dict[str, tuple[float, float]]:
    """Numbered pad centres of a footprint, one point per number (the mean
    when a number repeats, as an exposed pad split into parts does)."""
    from .material import footprint_material

    acc: dict[str, list[tuple[float, float]]] = {}
    for pad in footprint_material(kicad_mod_text)["pads"]:
        num = _pad_number(pad.get("number"))
        at = pad.get("at") or []
        if not num or len(at) < 2:
            continue
        acc.setdefault(num, []).append((float(at[0]), float(at[1])))
    return {n: (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            for n, pts in acc.items()}


def _rot(x: float, y: float, deg: float) -> tuple[float, float]:
    """Turn (x, y) counter-clockwise AS SEEN, in KiCad's y-down frame."""
    t = math.radians(deg)
    return x * math.cos(t) + y * math.sin(t), -x * math.sin(t) + y * math.cos(t)


def measure(ours_text: str, jlc_text: str) -> dict:
    """The correction that turns our land into JLC's land for the same part.

    `jlc_text` is JLC's land as a `.kicad_mod` (easyeda2kicad writes one).
    Pads are matched BY NUMBER. For each quarter turn R the best translation is
    the mean difference, and the residual says how well the copper matches.
    The correction is `-R`: if JLC's land is ours turned by R, JLC's 0 degrees
    is R away from ours. `position` is JLC's land origin in our footprint frame,
    y up, which is what `FT Position Offset` holds.

    The result is a PROPOSAL. The EasyEDA land is a good guide to JLC's 0
    degrees but not proof (U.FL C411563 and DSHP08TS C3293147 are known
    misses); confirm in JLC's placement preview before relying on it.
    """
    ours = _pad_centres(ours_text)
    theirs = _pad_centres(jlc_text)
    common = sorted(set(ours) & set(theirs))
    result: dict = {"matched_pads": len(common), "our_pads": len(ours), "jlc_pads": len(theirs)}
    if len(common) < 2 or set(ours) != set(theirs):
        result["error"] = ("pad numbers differ between the two lands; match them by hand"
                           if len(common) >= 2 else "fewer than two pads in common")
        if len(common) < 2:
            return result
    fits = []
    for r in (0.0, 90.0, 180.0, 270.0):
        rotated = {n: _rot(*ours[n], r) for n in common}
        tx = sum(theirs[n][0] - rotated[n][0] for n in common) / len(common)
        ty = sum(theirs[n][1] - rotated[n][1] for n in common) / len(common)
        resid = max(math.hypot(rotated[n][0] + tx - theirs[n][0],
                               rotated[n][1] + ty - theirs[n][1]) for n in common)
        fits.append((resid, r, tx, ty))
    fits.sort()
    resid, r, tx, ty = fits[0]
    second = fits[1][0]
    # JLC's origin (0, 0) expressed in our frame: undo the translation, then the turn.
    ox, oy = _rot(-tx, -ty, -r)
    result.update({
        "rotation_offset": _norm_deg(-r),
        "position_offset": [round(ox, 3), round(-oy, 3)],
        "residual_mm": round(resid, 3),
        "second_best_mm": round(second, 3),
        # Two orientations that fit almost equally well (a symmetric land, a
        # 2-pad chip) cannot be told apart from copper alone.
        "confidence": ("high" if resid < 0.3 and second > 3 * max(resid, 0.1)
                       else "low"),
    })
    return result
