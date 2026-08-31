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
def board_stackup(pcb_path) -> dict | None:
    """The stackup declared inside a `.kicad_pcb`, or None when it declares none.

    KiCad only writes a `(stackup …)` block once somebody has filled the board setup
    in, so "no stackup" is the common case and is not a fault. What comes back is
    deliberately coarse — copper layer count, total thickness, and the dielectric
    thicknesses — because that is what can be compared honestly against a fab's
    stackup without pretending the two name their layers the same way.
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
    copper = 0
    total = 0.0
    layers: list[dict] = []
    for layer in iter_nodes(stack, "layer"):
        name = str(layer[1]).strip('"') if len(layer) > 1 else ""
        kind = node_value(layer, "type", "") or ""
        thick = node_value(layer, "thickness", None)
        try:
            t = float(thick) if thick is not None else 0.0
        except (TypeError, ValueError):
            t = 0.0
        if "copper" in str(kind).lower():
            copper += 1
        if name.startswith("F.SilkS") or name.startswith("B.SilkS"):
            continue
        total += t
        layers.append({"name": name, "type": str(kind), "thickness_mm": t})
    return {"copper_layers": copper, "total_mm": round(total, 4), "layers": layers}


def compare_stackup(board: dict | None, library: dict | None) -> list[str]:
    """Plain-language differences between the board file and the assigned stackup.

    Informational by design (user decision 2026-08-31): a board is allowed to
    disagree with the stackup it is costed and solved against — the platform says so
    and refuses nothing.
    """
    if not board or not library:
        return []
    out: list[str] = []
    lib_cu = len([x for x in library.get("layers", []) if x.get("type") == "copper"])
    if board["copper_layers"] and lib_cu and board["copper_layers"] != lib_cu:
        out.append(
            f"the board file declares {board['copper_layers']} copper layers, "
            f"the assigned stackup has {lib_cu}"
        )
    lib_total = float(library.get("total_mm") or 0)
    if board["total_mm"] and lib_total and abs(board["total_mm"] - lib_total) > 0.05:
        out.append(
            f"board thickness {board['total_mm']:.3f} mm against "
            f"{lib_total:.3f} mm for the assigned stackup"
        )
    return out
