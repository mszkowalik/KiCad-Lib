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
        "mask_color": rev.mask_color or "",
        "silk_color": rev.silk_color or "",
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
    "mask_mm": 0.002,
    "eps_r": 0.05,
    "tand": 0.002,
}

_COPPER_RE = re.compile(r"^(F\.Cu|B\.Cu|In\d+\.Cu)$")
_SILK_RE = re.compile(r"\.SilkS$")
_SKIP_RE = re.compile(r"\.Paste$")


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
    mask_top = None
    mask_bot = None
    mask_dk = None
    silk_top = False
    silk_bot = False
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
            t = _f(groups[0].get("thickness"))
            mask_mm += t
            if "epsilon_r" in groups[0]:
                mask_dk = _f(groups[0]["epsilon_r"], None)
            if name.startswith("F."):
                mask_top = round(t, 6)
            else:
                mask_bot = round(t, 6)
            layers.append({"name": name, "type": kind, "thickness_mm": round(t, 6)})
            continue
        if _SILK_RE.search(name):
            silk_top = silk_top or name.startswith("F.")
            silk_bot = silk_bot or name.startswith("B.")
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
        "mask_top_mm": mask_top,
        "mask_bot_mm": mask_bot,
        "mask_dk": mask_dk,
        "silk_top": silk_top,
        "silk_bot": silk_bot,
        "finish": node_value(stack, "copper_finish", "") or "",
        "layers": layers,
        "copper": copper,
        "gaps": _build(copper, gaps),
    }


def _material_name(material_id: str) -> str:
    """The material's display name, or its id when the library does not know it.

    A raw id (`jlc_pp_3313`) in a Material column is a database key on a page a person
    reads; the library already carries "Prepreg 3313 (FR-4)".
    """
    from .fieldsolver.materials import LIB

    try:
        return LIB.get(material_id).name
    except KeyError:
        return material_id or ""


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
            copper.append({"name": l.get("name", ""), "thickness_mm": t,
                           "weight": str(l.get("weight") or "")})
            if len(copper) > 1:
                gaps.append(pending)
            pending = []
            continue
        dk, tand = _library_eps(l.get("material", ""))
        pending.append({"type": l.get("label") or "dielectric", "label": l.get("label") or l.get("material", ""),
                        "material": l.get("material", ""), "thickness_mm": t,
                        "eps_r": dk, "tand": tand})
    fin = stackup.get("finish") or {}
    return {
        "copper_layers": len(copper),
        "total_mm": round(float(stackup.get("total_mm") or 0), 4),
        "copper": copper,
        "gaps": _build(copper, gaps),
        "faces": stackup.get("faces") or {},
        "soldermask": stackup.get("soldermask") or "",
        "mask_dk": _library_eps(stackup.get("soldermask") or "")[0],
        "mask_thickness_mm": stackup.get("mask_thickness_mm"),
        "mask_thickness_is_minimum": bool(stackup.get("mask_thickness_is_minimum")),
        "mask_source": stackup.get("mask_source", ""),
        "silkscreen": bool((stackup.get("silkscreen") or {}).get("present")),
        "finish": fin.get("type", ""),
        "finish_um": fin.get("thickness_um"),
    }


def _near(a, b, tol: float) -> bool | None:
    """True/False within `tol`, or None when either side does not state a value."""
    if a is None or b is None:
        return None
    return abs(float(a) - float(b)) <= tol


def _at_least(value, minimum, tol: float) -> bool | None:
    """True when `value` clears `minimum`, or None when either side is silent.

    A fab that publishes ">= 10 um" of mask ink is not contradicted by a board that
    declares 25 um, so this is the honest test for a published minimum.
    """
    if value is None or minimum is None:
        return None
    return float(value) >= float(minimum) - tol


def _row(what: str, board, lib, ok, unit: str = "") -> dict:
    return {"what": what, "board": board, "stackup": lib, "ok": ok, "unit": unit}


def _weighted_dk(sheets: list[dict]) -> float | None:
    num = sum(s["thickness_mm"] for s in sheets if s.get("eps_r") is not None)
    if num <= 0:
        return None
    return round(sum(s["thickness_mm"] * s["eps_r"] for s in sheets if s.get("eps_r") is not None) / num, 4)


# The row kinds the visualiser colours. A fab and a `.kicad_pcb` name their layers
# differently ("prepreg" / "Prepreg", "core" / "Core", "Top Solder Mask"), so the
# kind is decided here once and the page only paints it.
_KIND_WORDS = (
    ("mask", "mask"),
    ("silk", "overlay"),
    ("overlay", "overlay"),
    ("paste", "paste"),
    ("prepreg", "prepreg"),
    ("core", "core"),
)


def _kind_of(text: str, default: str = "dielectric") -> str:
    low = (text or "").lower()
    for word, kind in _KIND_WORDS:
        if word in low:
            return kind
    return default


def _face(name: str = "", material: str = "", thickness_mm=None, dk=None, tand=None,
          weight: str = "", type_text: str = "") -> dict:
    """One side of a stack row — what the board file says, or what the stackup says."""
    return {"name": name, "material": material, "thickness_mm": thickness_mm,
            "dk": dk, "tand": tand, "weight": weight, "type": type_text}


def _stack_row(kind: str, index=None, board=None, stackup=None, ok=None, note: str = "",
               advisory=None) -> dict:
    """One drawable row.

    `ok` holds the checks that decide the verdict. `advisory` holds checks that are
    shown and deliberately do NOT decide it — the surface finish is the case: it is a
    separate order option at the fab, the stackup's own finish is an assumed default,
    and "same layer structure" does not include it. Painting such a row red under a
    green verdict would say something the platform does not mean, and hiding it would
    lose a difference the user should see. It gets its own state instead.
    """
    ok = ok or {}
    advisory = advisory or {}
    checks = [v for v in ok.values() if v is not None]
    row_ok = all(checks) if checks else None
    adv = [v for v in advisory.values() if v is not None]
    if row_ok is False:
        severity = "differs"
    elif adv and not all(adv):
        severity = "note"
    elif row_ok is True:
        severity = "match"
    else:
        severity = "none"
    return {
        "kind": kind,
        "index": index,
        "board": board,
        "stackup": stackup,
        "ok": ok,
        "advisory": advisory,
        # the row's own verdict: False when any compared property differs, None when
        # nothing on the row could be compared at all
        "row_ok": row_ok,
        "severity": severity,
        "note": note,
    }


def _sheet_faces(sheets: list[dict], from_library: bool) -> list[dict]:
    out = []
    for sh in sheets:
        label = sh.get("label") or sh.get("material") or "dielectric"
        out.append(_face(
            name=label,
            material=_material_name(sh.get("material") or "") if from_library else label,
            thickness_mm=sh.get("thickness_mm"),
            dk=sh.get("eps_r"),
            tand=sh.get("tand"),
            type_text=_kind_of(str(sh.get("type") or ""), "dielectric"),
        ))
    return out


def _lib_face(lib: dict | None, side: str, key: str):
    """One face's outer layer from the library build, falling back to the whole-board
    value for a stackup written before faces existed."""
    if not lib:
        return None
    faces = lib.get("faces") or {}
    face = faces.get(side.lower()) or {}
    if key in face:
        return face[key]
    return {"soldermask": lib.get("soldermask"), "silkscreen": lib.get("silkscreen"),
            "finish": lib.get("finish")}.get(key)


def stack_rows(board: dict | None, lib: dict | None) -> list[dict]:
    """The two sides aligned into one top-to-bottom list, ready to be drawn.

    The same list serves three views, which is the point of building it here: a board
    file on its own, a library stackup on its own, and the two compared. A row carries
    whichever sides exist; the page paints `kind` and reads `row_ok`.

    Alignment follows the normal form — copper i against copper i, gap i against gap i,
    sheet j against sheet j — so the picture can never disagree with the verdict. When a
    gap holds a different NUMBER of sheets on the two sides, the extra sheets are drawn
    as rows with one side empty, because that difference is the thing worth seeing.
    """
    rows: list[dict] = []
    both = bool(board) and bool(lib)

    def _overlay(side: str, present_b: bool) -> dict | None:
        """Presence only. A fab publishes that it prints a legend and publishes its
        line width and text height, but no ink thickness — so there is a real check
        here (does the board expect one at all) and nothing to measure."""
        fb = _face(f"{side} Overlay", "legend ink", type_text="silkscreen") if (board and present_b) else None
        silk = _lib_face(lib, side, "silkscreen")
        present_l = bool(silk.get("present")) if isinstance(silk, dict) else bool(silk)
        fl = _face(f"{side} Overlay", "legend ink", type_text="silkscreen") if present_l else None
        if not fb and not fl:
            return None
        ok = {}
        note = "The fab prints a legend and publishes no ink thickness, so only its presence is checked."
        if both:
            ok = {"present": bool(fb) == bool(fl)}
            if not ok["present"]:
                note = ("The board file declares a silkscreen and the stackup does not model one."
                        if fb else "The stackup prints a legend and the board file declares no silkscreen layer.")
        return _stack_row("overlay", board=fb, stackup=fl, ok=ok, note=note)

    def _mask(side: str, t_b) -> dict | None:
        """Ink thickness and Dk.

        The fab's figure is a MINIMUM (">= 10 um"), so a board declaring more is not a
        conflict and the check is `board >= minimum`, not equality. It is a different
        quantity from `mask_geom`, which is the coating PROFILE the solver builds —
        those three numbers are not compared against anything in the board file,
        because KiCad does not record them.
        """
        fb = _face(f"{side} Solder", "solder mask", t_b, dk=(board or {}).get("mask_dk"),
                   type_text="solder mask") if board else None
        fl = None
        mask_id = _lib_face(lib, side, "soldermask")
        if mask_id:
            fl = _face(f"{side} Solder", _material_name(str(mask_id)),
                       lib.get("mask_thickness_mm"), dk=_library_eps(str(mask_id))[0], type_text="solder mask")
        if not fb and not fl:
            return None
        ok: dict = {}
        notes: list[str] = []
        if both:
            ok["present"] = bool(fb) == bool(fl)
            if not ok["present"]:
                notes.append("The board file declares a solder mask and the stackup does not."
                             if fb else "The stackup carries a solder mask and the board file declares none.")
        if fb and fl:
            if lib.get("mask_thickness_is_minimum"):
                ok["thickness"] = _at_least(fb["thickness_mm"], fl["thickness_mm"], TOLERANCE["mask_mm"])
                notes.append(f"The fab states the ink thickness as a minimum of {fl['thickness_mm']} mm, "
                             "so the board is checked for at least that, not for the same.")
            else:
                ok["thickness"] = _near(fb["thickness_mm"], fl["thickness_mm"], TOLERANCE["mask_mm"])
            ok["dk"] = _near(fb["dk"], fl["dk"], TOLERANCE["eps_r"])
            if fb["dk"] is None:
                notes.append("The board file states no mask Dk. KiCad can carry one on the mask layer "
                             f"(Board Setup -> Physical Stackup); the fab publishes {fl['dk']}.")
        notes.append("The coating PROFILE the solver builds (above substrate, above trace, between traces) "
                     "has no counterpart in a .kicad_pcb and is not compared.")
        return _stack_row("mask", board=fb, stackup=fl, ok=ok, note=" ".join(notes))

    def _finish(side: str) -> dict | None:
        """The finish sits on exposed copper on BOTH outer layers, so it is drawn on
        both — one row near the top read as though the bottom had none."""
        fb = _face(str((board or {}).get("finish") or ""), type_text="surface finish") \
            if (board and board.get("finish")) else None
        fl = None
        fin = _lib_face(lib, side, "finish")
        if isinstance(fin, dict) and fin.get("type"):
            fl = _face(str(fin["type"]), type_text="surface finish",
                       thickness_mm=(float(fin["thickness_um"]) / 1000.0 if fin.get("thickness_um") else None))
        elif fin:
            fl = _face(str(fin), type_text="surface finish")
        if not fb and not fl:
            return None
        same = None
        if fb and fl and fb["name"] and fl["name"]:
            same = fb["name"].strip().lower() == fl["name"].strip().lower()
        note = (f"On exposed copper, both outer layers — this row is drawn on each of them. The solver grows "
                f"the copper inside the {side.lower()} mask opening by the stackup's finish, not the board file's.")
        if same is False:
            note = (f"The board file asks for {fb['name']} and the stackup carries {fl['name']}. "
                    "The finish is a separate order option at the fab and the stackup's is an assumed "
                    "default, so it is shown but does not decide the verdict. " + note)
        return _stack_row("finish", board=fb, stackup=fl, advisory={"finish": same}, note=note)

    # ---- above the first copper layer
    for row in (_overlay("Top", (board or {}).get("silk_top", False)),
                _mask("Top", (board or {}).get("mask_top_mm")),
                _finish("Top")):
        if row:
            rows.append(row)

    # ---- the copper layers and the gaps between them
    bc = (board or {}).get("copper", [])
    lc = (lib or {}).get("copper", [])
    bg = (board or {}).get("gaps", [])
    lg = (lib or {}).get("gaps", [])
    for i in range(max(len(bc), len(lc))):
        b = bc[i] if i < len(bc) else None
        l = lc[i] if i < len(lc) else None
        fb = _face(b["name"], "copper", b["thickness_mm"], weight=b.get("weight", ""), type_text="copper") if b else None
        fl = _face(l["name"], "copper", l["thickness_mm"], weight=l.get("weight", ""), type_text="copper") if l else None
        if b and l:
            ok = {"thickness": _near(b["thickness_mm"], l["thickness_mm"], TOLERANCE["copper_mm"])}
            note = ""
        elif both:
            # one side has a copper layer the other does not: that is a difference,
            # not an absence of one, so the row must read red rather than "—"
            ok = {"present": False}
            note = ("The board file has this copper layer and the assigned stackup does not."
                    if b else "The stackup has this copper layer and the board file does not.")
        else:
            ok, note = {}, ""
        rows.append(_stack_row("copper", index=i + 1, board=fb, stackup=fl, ok=ok, note=note))

        gb = bg[i] if i < len(bg) else None
        gl = lg[i] if i < len(lg) else None
        if gb is None and gl is None:
            continue
        sb = _sheet_faces(gb["sheets"], False) if gb else []
        sl = _sheet_faces(gl["sheets"], True) if gl else []
        split = both and gb and gl and len(sb) != len(sl)
        for j in range(max(len(sb), len(sl))):
            fb = sb[j] if j < len(sb) else None
            fl = sl[j] if j < len(sl) else None
            ok = {}
            if fb and fl:
                ok = {
                    "thickness": _near(fb["thickness_mm"], fl["thickness_mm"], TOLERANCE["dielectric_mm"]),
                    "dk": _near(fb["dk"], fl["dk"], TOLERANCE["eps_r"]),
                    "tand": _near(fb["tand"], fl["tand"], TOLERANCE["tand"]),
                }
            elif both:
                ok = {"present": False}
            kind = _kind_of((fb or fl or {}).get("type", ""), "dielectric")
            note = ""
            if both and not (fb and fl):
                note = ("The board file has this sheet and the assigned stackup does not."
                        if fb else "The stackup has this sheet and the board file does not.")
            if split:
                nb = len(sb) if gb else 0
                ns = len(sl) if gl else 0
                note = (f"{note} This gap is {nb} sheet(s) in the board file and {ns} in the stackup.").strip()
            rows.append(_stack_row(kind, board=fb, stackup=fl, ok=ok, note=note))

    # ---- below the last copper layer, mirroring the top
    for row in (_finish("Bottom"),
                _mask("Bottom", (board or {}).get("mask_bot_mm")),
                _overlay("Bottom", (board or {}).get("silk_bot", False))):
        if row:
            rows.append(row)
    return rows


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
        # one side alone still draws: the visualiser takes the same row list
        return {"verdict": "unknown", "differences": [], "rows": [],
                "stack": stack_rows(board, lib), "notes": [], "tolerance": TOLERANCE}

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
        # the same comparison drawn as a stackup, top to bottom
        "stack": stack_rows(board, lib),
        "notes": notes,
        "tolerance": TOLERANCE,
    }


def compare_stackup(board: dict | None, library: dict | None) -> list[str]:
    """Plain-language differences only — the shape the agent tool and the page header
    have always had. `compare_stackup_detail` carries the per-layer table."""
    return compare_stackup_detail(board, library)["differences"]
