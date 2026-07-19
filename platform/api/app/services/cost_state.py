"""Commit-anchored versioning of a project's manual cost data.

ProjectCostItem and ProjectExtraBomItem rows live inside an immutable
ProjectCostRevision (they version together as one list). Semantics the user
asked for: a list created at commit X applies from X forward; editing it at
commit Y (add/remove/change) creates a new revision effective from Y forward
— snapshots before Y keep seeing the X list. Changes never propagate
backward.

Selection rule: for a snapshot S, the applicable revision is the one with
the latest effective_committed_at <= S.committed_at (NULL = -infinity, the
"since forever" anchor used for migrated data). With no snapshot context the
latest revision overall applies (the current list).

Copy-on-write rule: an edit made while viewing snapshot S mutates the
revision anchored exactly at S.sha if it exists, otherwise copies the
revision visible at S into a new one anchored at S.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M

_FLOOR = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _sort_key(rev: M.ProjectCostRevision) -> tuple:
    return (rev.effective_committed_at or _FLOOR, rev.id)


def revision_for(
    db: Session, project_id: int, snapshot: M.ProjectSnapshot | None = None
) -> M.ProjectCostRevision | None:
    """The revision in effect at `snapshot` (None = the current list)."""
    revs = db.query(M.ProjectCostRevision).filter_by(project_id=project_id).all()
    if not revs:
        return None
    if snapshot is not None and snapshot.committed_at is not None:
        revs = [
            r for r in revs
            if r.effective_committed_at is None
            or r.effective_committed_at <= snapshot.committed_at
        ]
        if not revs:
            return None  # strictly before the first anchored revision
    return max(revs, key=_sort_key)


def _extras_of(db: Session, rev: M.ProjectCostRevision) -> list[M.ProjectExtraBomItem]:
    return (
        db.query(M.ProjectExtraBomItem)
        .filter_by(revision_id=rev.id)
        .order_by(M.ProjectExtraBomItem.position, M.ProjectExtraBomItem.id)
        .all()
    )


def _costs_of(db: Session, rev: M.ProjectCostRevision) -> list[M.ProjectCostItem]:
    return (
        db.query(M.ProjectCostItem)
        .filter_by(revision_id=rev.id)
        .order_by(M.ProjectCostItem.position, M.ProjectCostItem.id)
        .all()
    )


def items_for(
    db: Session, project_id: int, snapshot: M.ProjectSnapshot | None = None
) -> tuple[list[M.ProjectExtraBomItem], list[M.ProjectCostItem], M.ProjectCostRevision | None]:
    """(extra BOM items, cost items, revision) in effect at `snapshot`."""
    rev = revision_for(db, project_id, snapshot)
    if rev is None:
        return [], [], None
    return _extras_of(db, rev), _costs_of(db, rev), rev


def revision_json(rev: M.ProjectCostRevision | None) -> dict | None:
    if rev is None:
        return None
    return {
        "id": rev.id,
        "anchor_sha": rev.effective_sha,
        "anchor_ref": rev.effective_ref,
        "anchor_committed_at": (
            rev.effective_committed_at.isoformat() if rev.effective_committed_at else None
        ),
    }


def revision_for_edit(
    db: Session, project_id: int, snapshot: M.ProjectSnapshot | None = None
) -> tuple[M.ProjectCostRevision, dict[int, M.ProjectExtraBomItem], dict[int, M.ProjectCostItem]]:
    """Revision that an edit made at `snapshot` may mutate, copy-on-write.

    Returns (revision, extra_map, cost_map); the maps translate item ids of
    the base revision to their copies (empty when no copy happened — the
    caller may mutate items whose revision_id == revision.id directly).
    Flushes but does not commit."""
    # A snapshot without a commit date can't be ordered — treat as no context.
    if snapshot is not None and snapshot.committed_at is None:
        snapshot = None
    base = revision_for(db, project_id, snapshot)
    anchor_sha = snapshot.sha if snapshot is not None else (base.effective_sha if base else "")

    if base is not None and base.effective_sha == anchor_sha:
        return base, {}, {}

    rev = M.ProjectCostRevision(
        project_id=project_id,
        effective_sha=anchor_sha,
        effective_ref=snapshot.ref_name if snapshot is not None else "",
        effective_committed_at=snapshot.committed_at if snapshot is not None else None,
    )
    db.add(rev)
    db.flush()

    extra_map: dict[int, M.ProjectExtraBomItem] = {}
    cost_map: dict[int, M.ProjectCostItem] = {}
    if base is not None:
        for x in _extras_of(db, base):
            copy = M.ProjectExtraBomItem(
                project_id=x.project_id, revision_id=rev.id, position=x.position,
                label=x.label, qty=x.qty, component_id=x.component_id,
                manufacturer=x.manufacturer, mpn=x.mpn, unit_price=x.unit_price,
                currency=x.currency, notes=x.notes,
            )
            db.add(copy)
            extra_map[x.id] = copy
        for c in _costs_of(db, base):
            copy = M.ProjectCostItem(
                project_id=c.project_id, revision_id=rev.id, position=c.position,
                label=c.label, basis=c.basis, price=c.price,
                steps=list(c.steps) if c.steps else None, currency=c.currency,
                company=c.company, mpn=c.mpn, notes=c.notes,
            )
            db.add(copy)
            cost_map[c.id] = copy
        db.flush()
    return rev, extra_map, cost_map
