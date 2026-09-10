"""Commit-anchored versioning of a board's impedance work.

Which stackup a board is built on, and which impedance profiles it carries, travel
with the repository the same way the manual cost data does (`cost_state`): a
revision created at commit X applies from X forward, an edit made while viewing
commit Y copies what is visible at Y into a new revision anchored at Y, and earlier
commits keep what they had. Assignments therefore follow later commits by
themselves until somebody deliberately changes them.

Two rules specific to this module:

* **Changing the stackup never deletes a profile.** The profiles are copied onto the
  new revision with their results intact; each one records the stackup it was solved
  against, so `is_outdated` can say plainly that a result no longer describes the
  board rather than the result quietly disappearing.
* **A stored result holds numbers, not fields.** Summary, sweep, C/L and the geometry
  outline are kept; the solved mesh is not, because it is tens of megabytes per
  frequency frame. Reopening a profile shows every figure at once; only the field
  picture needs a re-solve.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M

_FLOOR = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _sort_key(rev: M.ProjectFieldRevision) -> tuple:
    return (rev.effective_committed_at or _FLOOR, rev.id)


def stackup_sha(stackup: dict | None) -> str:
    """Fingerprint of the stackup a result was computed against.

    Layers, coating and finish only — the name and the provenance text do not change
    a field. Renaming a stackup must not invalidate anybody's numbers.
    """
    if not stackup:
        return ""
    body = {
        "layers": stackup.get("layers"),
        "soldermask": stackup.get("soldermask"),
        "finish": stackup.get("finish"),
        "mask_geom": stackup.get("mask_geom"),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def revision_for(
    db: Session, project_id: int, board: str = "", snapshot: M.ProjectSnapshot | None = None
) -> M.ProjectFieldRevision | None:
    """The revision in effect at `snapshot` (None = the current one)."""
    revs = db.query(M.ProjectFieldRevision).filter_by(project_id=project_id, board=board).all()
    if not revs:
        return None
    if snapshot is not None and snapshot.committed_at is not None:
        revs = [
            r for r in revs
            if r.effective_committed_at is None or r.effective_committed_at <= snapshot.committed_at
        ]
        if not revs:
            return None            # strictly before the first anchored revision
    return max(revs, key=_sort_key)


def profiles_of(db: Session, rev: M.ProjectFieldRevision) -> list[M.ProjectFieldProfile]:
    return (
        db.query(M.ProjectFieldProfile)
        .filter_by(revision_id=rev.id)
        .order_by(M.ProjectFieldProfile.position, M.ProjectFieldProfile.id)
        .all()
    )


def state_for(
    db: Session, project_id: int, board: str = "", snapshot: M.ProjectSnapshot | None = None
) -> tuple[M.ProjectFieldRevision | None, list[M.ProjectFieldProfile]]:
    rev = revision_for(db, project_id, board, snapshot)
    return (rev, profiles_of(db, rev) if rev else [])


def revision_for_edit(
    db: Session,
    project_id: int,
    board: str = "",
    snapshot: M.ProjectSnapshot | None = None,
) -> tuple[M.ProjectFieldRevision, dict[int, M.ProjectFieldProfile]]:
    """Revision an edit at `snapshot` may mutate, copy-on-write.

    Returns (revision, {old profile id: its copy}) — the map is empty when the
    revision was already anchored here and may be mutated in place. Flushes, never
    commits.
    """
    if snapshot is not None and snapshot.committed_at is None:
        snapshot = None                          # cannot be ordered: treat as no context
    base = revision_for(db, project_id, board, snapshot)
    anchor_sha = snapshot.sha if snapshot is not None else (base.effective_sha if base else "")

    if base is not None and base.effective_sha == anchor_sha:
        return base, {}

    rev = M.ProjectFieldRevision(
        project_id=project_id,
        board=board,
        effective_sha=anchor_sha,
        effective_ref=snapshot.ref_name if snapshot is not None else "",
        effective_committed_at=snapshot.committed_at if snapshot is not None else None,
        stackup_key=base.stackup_key if base else "",
    )
    db.add(rev)
    db.flush()

    copies: dict[int, M.ProjectFieldProfile] = {}
    if base is not None:
        for p in profiles_of(db, base):
            # the result travels with the profile: changing the stackup must not
            # throw away work, it must mark it outdated
            copy = M.ProjectFieldProfile(
                revision_id=rev.id, position=p.position, name=p.name,
                config=p.config, result=p.result, solved_at=p.solved_at,
                stackup_key=p.stackup_key, stackup_sha=p.stackup_sha,
                created_by=p.created_by,
            )
            db.add(copy)
            copies[p.id] = copy
        db.flush()
    return rev, copies


def is_outdated(profile: M.ProjectFieldProfile, current_sha: str, current_key: str) -> bool:
    """True when the stored result no longer describes the board it is attached to."""
    if not profile.result:
        return False
    if profile.stackup_sha and current_sha:
        return profile.stackup_sha != current_sha
    return bool(profile.stackup_key and current_key and profile.stackup_key != current_key)


def revision_json(rev: M.ProjectFieldRevision | None) -> dict | None:
    if rev is None:
        return None
    return {
        "id": rev.id,
        "board": rev.board,
        "stackup_key": rev.stackup_key,
        "anchor_sha": rev.effective_sha,
        "anchor_ref": rev.effective_ref,
        "anchor_committed_at": (
            rev.effective_committed_at.isoformat() if rev.effective_committed_at else None
        ),
    }


def profile_json(p: M.ProjectFieldProfile, outdated: bool) -> dict:
    return {
        "id": p.id,
        "position": p.position,
        "name": p.name,
        "config": p.config,
        "result": p.result,
        "solved_at": p.solved_at.isoformat() if p.solved_at else None,
        "stackup_key": p.stackup_key,
        "outdated": outdated,
        "created_by": p.created_by,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }




# ------------------------------------------------- what the board file itself says
# A fab stackup and a `.kicad_pcb` describe the same physical board in two different
# vocabularies, so neither side is compared field by field. Both are first reduced to
# the same normal form — the ordered copper layers, and the dielectric GAP between
# each neighbouring pair — and the comparison runs on that. Three reasons it has to
# work this way:
#
# * **KiCad allows only `copper - 1` dielectric layers.** A fab that lists three
#   prepreg sheets in one gap (JLC06121H-3313A lists 7628 x3 between L3 and L4)
#   becomes one KiCad dielectric carrying three SUB-layers, written `addsublayer`.
#   Counting `(layer …)` nodes would therefore never agree with the fab's own table.
# * **What a field actually sees is the gap**, not the sheet count: total thickness
#   and permittivity between a trace and its reference. Sheets are compared when both
#   sides list the same number of them, and the gap total plus a thickness-weighted Dk
#   when they do not.
# * **A board is allowed to disagree** (user decision 2026-08-31). The platform says
#   so plainly and refuses nothing — the numbers are solved against the ASSIGNED
#   stackup, which is what the fab builds.

# How close counts as the same. Copper is a plating tolerance, dielectric a lamination
# one; Dk and tand are compared against the published datasheet point, which carries a
# frequency the board file does not record (see `_board_eps` below).
TOLERANCE = {
    "copper_mm": 0.005,
    "dielectric_mm": 0.02,
    "eps_r": 0.05,
    "tand": 0.002,
}

_COPPER_RE = re.compile(r"^(F\.Cu|B\.Cu|In\d+\.Cu)$")
_SKIP_RE = re.compile(r"\.(SilkS|Paste)$")


def _sublayers(layer) -> list[dict]:
    """The sub-layers of one KiCad stackup `(layer …)` node, in order.

    KiCad writes a multi-sheet dielectric as one layer whose property groups are
    separated by a bare `addsublayer` atom, so the groups cannot be read with
    `node_value` — it would return the first sheet and silently lose the rest.
    """
    from ..util.sexpr import _norm

    groups: list[dict] = [{}]
    for child in layer[2:]:
        if not isinstance(child, list):
            if _norm(child) == "addsublayer":
                groups.append({})
            continue
        if not child:
            continue
        tag = _norm(child[0])
        if tag == "addsublayer":
            groups.append({})
            continue
        if len(child) > 1:
            groups[-1][tag] = _norm(child[1])
    return groups


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _sheet(group: dict, kind: str) -> dict:
    return {
        "type": kind,
        "label": group.get("material") or kind,
        "thickness_mm": round(_f(group.get("thickness")), 6),
        "eps_r": _f(group.get("epsilon_r"), None) if "epsilon_r" in group else None,
        "tand": _f(group.get("loss_tangent"), None) if "loss_tangent" in group else None,
    }


def _build(copper: list[dict], gaps: list[list[dict]]) -> list[dict]:
    """Pair each dielectric gap with the two copper layers that bound it."""
    out = []
    for i, sheets in enumerate(gaps):
        out.append({
            "above": copper[i]["name"] if i < len(copper) else "",
            "below": copper[i + 1]["name"] if i + 1 < len(copper) else "",
            "thickness_mm": round(sum(s["thickness_mm"] for s in sheets), 6),
            "sheets": sheets,
        })
    return out


def board_stackup(pcb_path) -> dict | None:
    """The stackup declared inside a `.kicad_pcb`, or None when it declares none.

    KiCad only writes a `(stackup …)` block once somebody has filled the board setup
    in, so "no stackup" is the common case and is not a fault.

    `total_mm` is the copper-plus-dielectric build, which is what a fab stackup
    states; the solder mask is reported separately as `mask_mm` because the two sides
    describe it differently (KiCad one thickness per side, a fab three coating
    geometries and a Dk).
    """
    from ..util.sexpr import find_node, iter_nodes, node_value, parse_sexpr

    try:
        tree = parse_sexpr(pcb_path.read_text(errors="ignore"))
    except Exception:
        return None
    setup = find_node(tree, "setup")
    stack = find_node(setup, "stackup") if setup is not None else None
    if stack is None:
        return None

    layers: list[dict] = []          # flat, as written, for display
    copper: list[dict] = []
    gaps: list[list[dict]] = []
    pending: list[dict] = []
    mask_mm = 0.0
    total = 0.0
    for layer in iter_nodes(stack, "layer"):
        name = str(layer[1]).strip('"') if len(layer) > 1 else ""
        kind = (node_value(layer, "type", "") or "").strip()
        if _SKIP_RE.search(name):
            continue
        groups = _sublayers(layer)
        if _COPPER_RE.match(name):
            t = round(_f(groups[0].get("thickness")), 6)
            total += t
            copper.append({"name": name, "thickness_mm": t})
            layers.append({"name": name, "type": kind, "thickness_mm": t})
            if len(copper) > 1:
                gaps.append(pending)
            pending = []
            continue
        if name.endswith(".Mask"):
            mask_mm += _f(groups[0].get("thickness"))
            layers.append({"name": name, "type": kind,
                           "thickness_mm": round(_f(groups[0].get("thickness")), 6)})
            continue
        sheets = [_sheet(g, kind or "dielectric") for g in groups]
        for s in sheets:
            total += s["thickness_mm"]
        pending.extend(sheets)
        layers.append({"name": name, "type": kind,
                       "thickness_mm": round(sum(s["thickness_mm"] for s in sheets), 6),
                       "sheets": sheets})
    return {
        "copper_layers": len(copper),
        "total_mm": round(total, 4),
        "mask_mm": round(mask_mm, 4),
        "finish": node_value(stack, "copper_finish", "") or "",
        "layers": layers,
        "copper": copper,
        "gaps": _build(copper, gaps),
    }


def _library_eps(material_id: str, f_hz: float = 1e9) -> tuple[float | None, float | None]:
    """The PUBLISHED (dk, tand) point of a library material nearest `f_hz`.

    The datasheet point, not the Djordjevic-Sarkar value the solver uses: a
    `.kicad_pcb` records one `epsilon_r` with no frequency attached, so the only
    honest thing to compare it against is the figure the fab published.
    """
    from .fieldsolver.materials import LIB

    try:
        p = LIB.get(material_id).reference_point(f_hz)
    except (KeyError, ValueError):
        return None, None
    return p.get("dk"), p.get("tand")


def library_build(stackup: dict | None) -> dict | None:
    """The assigned stackup in the same normal form as `board_stackup`."""
    if not stackup:
        return None
    copper: list[dict] = []
    gaps: list[list[dict]] = []
    pending: list[dict] = []
    for l in stackup.get("layers", []):
        t = round(_f(l.get("thickness_mm")), 6)
        if l.get("type") == "copper":
            copper.append({"name": l.get("name", ""), "thickness_mm": t})
            if len(copper) > 1:
                gaps.append(pending)
            pending = []
            continue
        dk, tand = _library_eps(l.get("material", ""))
        pending.append({"type": l.get("label") or "dielectric", "label": l.get("label") or l.get("material", ""),
                        "material": l.get("material", ""), "thickness_mm": t,
                        "eps_r": dk, "tand": tand})
    return {
        "copper_layers": len(copper),
        "total_mm": round(float(stackup.get("total_mm") or 0), 4),
        "copper": copper,
        "gaps": _build(copper, gaps),
        "finish": (stackup.get("finish") or {}).get("type", ""),
    }


def _near(a, b, tol: float) -> bool | None:
    """True/False within `tol`, or None when either side does not state a value."""
    if a is None or b is None:
        return None
    return abs(float(a) - float(b)) <= tol


def _row(what: str, board, lib, ok, unit: str = "") -> dict:
    return {"what": what, "board": board, "stackup": lib, "ok": ok, "unit": unit}


def _weighted_dk(sheets: list[dict]) -> float | None:
    num = sum(s["thickness_mm"] for s in sheets if s.get("eps_r") is not None)
    if num <= 0:
        return None
    return round(sum(s["thickness_mm"] * s["eps_r"] for s in sheets if s.get("eps_r") is not None) / num, 4)


def compare_stackup_detail(board: dict | None, library: dict | None) -> dict:
    """Layer-by-layer comparison of a `.kicad_pcb` against the assigned stackup.

    Returns a verdict, the plain-language differences, and a row per thing compared
    so the project page can show WHERE the two disagree rather than only that they
    do. `notes` holds facts that are worth seeing but are not part of "same layer
    structure" — the surface finish and the solder mask, which the two sides state in
    different terms.
    """
    lib = library_build(library)
    if not board or not lib:
        return {"verdict": "unknown", "differences": [], "rows": [], "notes": [],
                "tolerance": TOLERANCE}

    diffs: list[str] = []
    notes: list[str] = []
    rows: list[dict] = []

    # 1. copper layer count — everything else is only meaningful when it agrees
    same_count = board["copper_layers"] == lib["copper_layers"]
    rows.append(_row("Copper layers", board["copper_layers"], lib["copper_layers"], same_count))
    if not same_count:
        diffs.append(f"the board file declares {board['copper_layers']} copper layers, "
                     f"the assigned stackup has {lib['copper_layers']}")

    # 2. total build (copper + dielectric, mask excluded on both sides)
    ok_total = _near(board["total_mm"], lib["total_mm"], TOLERANCE["dielectric_mm"])
    rows.append(_row("Total build", board["total_mm"], lib["total_mm"], ok_total, "mm"))
    if ok_total is False:
        diffs.append(f"board build {board['total_mm']:.4f} mm against "
                     f"{lib['total_mm']:.4f} mm for the assigned stackup")

    # 3. copper layer by copper layer
    for i in range(min(len(board["copper"]), len(lib["copper"]))):
        b, s = board["copper"][i], lib["copper"][i]
        ok = _near(b["thickness_mm"], s["thickness_mm"], TOLERANCE["copper_mm"])
        rows.append(_row(f"Copper {b['name']} / {s['name']}", b["thickness_mm"],
                         s["thickness_mm"], ok, "mm"))
        if ok is False:
            diffs.append(f"{b['name']} is {b['thickness_mm']:.4f} mm in the board file, "
                         f"{s['thickness_mm']:.4f} mm ({s['name']}) in the stackup")

    # 4. gap by gap: total thickness, then the sheets inside it
    for i in range(min(len(board["gaps"]), len(lib["gaps"]))):
        bg, sg = board["gaps"][i], lib["gaps"][i]
        where = f"{bg['above'] or '?'}–{bg['below'] or '?'}"
        ok = _near(bg["thickness_mm"], sg["thickness_mm"], TOLERANCE["dielectric_mm"])
        rows.append(_row(f"Dielectric {where}", bg["thickness_mm"], sg["thickness_mm"], ok, "mm"))
        if ok is False:
            diffs.append(f"the dielectric between {where} is {bg['thickness_mm']:.4f} mm in the "
                         f"board file, {sg['thickness_mm']:.4f} mm in the stackup")
        if len(bg["sheets"]) == len(sg["sheets"]):
            for j, (bs, ss) in enumerate(zip(bg["sheets"], sg["sheets"])):
                tag = f"{where} sheet {j + 1}" if len(bg["sheets"]) > 1 else where
                if len(bg["sheets"]) > 1:
                    okt = _near(bs["thickness_mm"], ss["thickness_mm"], TOLERANCE["dielectric_mm"])
                    rows.append(_row(f"  {tag} thickness", bs["thickness_mm"],
                                     ss["thickness_mm"], okt, "mm"))
                    if okt is False:
                        diffs.append(f"sheet {j + 1} between {where} is {bs['thickness_mm']:.4f} mm "
                                     f"in the board file, {ss['thickness_mm']:.4f} mm in the stackup")
                oke = _near(bs["eps_r"], ss["eps_r"], TOLERANCE["eps_r"])
                rows.append(_row(f"  {tag} Dk", bs["eps_r"], ss["eps_r"], oke))
                if oke is False:
                    diffs.append(f"Dk between {where} is {bs['eps_r']} in the board file, "
                                 f"{ss['eps_r']} ({ss.get('label')}) in the stackup")
                elif oke is None:
                    notes.append(f"Dk between {where} is not stated on both sides, so it was not compared.")
                okl = _near(bs["tand"], ss["tand"], TOLERANCE["tand"])
                rows.append(_row(f"  {tag} loss tangent", bs["tand"], ss["tand"], okl))
                if okl is False:
                    diffs.append(f"loss tangent between {where} is {bs['tand']} in the board file, "
                                 f"{ss['tand']} in the stackup")
        else:
            rows.append(_row(f"  {where} sheets", len(bg["sheets"]), len(sg["sheets"]), False))
            diffs.append(f"the dielectric between {where} is {len(bg['sheets'])} sheet(s) in the "
                         f"board file and {len(sg['sheets'])} in the stackup")
            bdk, sdk = _weighted_dk(bg["sheets"]), _weighted_dk(sg["sheets"])
            rows.append(_row(f"  {where} Dk (thickness weighted)", bdk, sdk,
                             _near(bdk, sdk, TOLERANCE["eps_r"])))

    # not part of "same layer structure", worth seeing anyway
    if board.get("finish") or lib.get("finish"):
        notes.append(f"Surface finish: the board file says “{board.get('finish') or 'nothing'}”, "
                     f"the stackup “{lib.get('finish') or 'nothing'}”. The solver grows the copper "
                     f"inside the mask opening by the stackup's finish, not the board file's.")
    if board.get("mask_mm"):
        notes.append(f"Solder mask: the board file states {board['mask_mm']:.3f} mm over both sides "
                     f"together. A fab states it as three coating geometries and a Dk, so the two "
                     f"are not compared.")
    notes.append("Dk and loss tangent are compared against the figure the fab published, which "
                 "carries a frequency; a `.kicad_pcb` records one value with no frequency.")

    return {
        "verdict": "differs" if diffs else "match",
        "differences": diffs,
        "rows": rows,
        "notes": notes,
        "tolerance": TOLERANCE,
    }


def compare_stackup(board: dict | None, library: dict | None) -> list[str]:
    """Plain-language differences only — the shape the agent tool and the page header
    have always had. `compare_stackup_detail` carries the per-layer table."""
    return compare_stackup_detail(board, library)["differences"]
