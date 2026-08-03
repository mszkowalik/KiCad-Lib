"""Auto-repoint: keep components pointing at the current symbol/footprint.

A `ComponentVersion` PINS the exact geometry it was drawn against
(`symbol_version_id`, `footprint_version_id`). Approving a new symbol or
footprint version moves only the template's own `current_version_id` and
rebuilds the mirror — it used to leave every component pinned to the superseded
drawing. A pin-1 sweep on 2026-08-03 published 105 new footprint versions and
left 185 of 327 components pinned to the version before it.

So each geometry approval now files a component draft per affected part. The
user still approves it: this creates proposals, it never publishes.

**One open auto-draft per component, refreshed — never a second one.** That is
the whole design, and it exists because a batch that touches BOTH a symbol and
a footprint would otherwise file two drafts against the same published parent.
Each would carry one of the two changes, and approving both would apply the
first, then overwrite it with the second — the component ends with one change
applied and two versions of history claiming otherwise. Refreshing a single
draft collapses that into one version carrying both new pins, in any approval
order. If the user approves the component draft BETWEEN the two geometry
approvals, the second approval opens a fresh draft, which is correct: two real
steps, each complete.

`created_by == AUTO_ACTOR` is the discriminator. A draft a human or an agent is
editing is NEVER touched — repointing it would silently rewrite a proposal
under review.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models as M

AUTO_ACTOR = "auto-repoint"

_COMMENT = (
    "Automatic: repoint to the current {what}. Properties are unchanged — this "
    "version exists only to move the pinned geometry off a superseded drawing."
)


def _current(parent) -> object | None:
    """The live version row of a Component / Symbol / Footprint."""
    if parent is None or parent.current_version_id is None:
        return None
    return next((v for v in parent.versions if v.id == parent.current_version_id), None)


def _clone_properties(db: Session, src: M.ComponentVersion, dst: M.ComponentVersion) -> None:
    """Copy the property rows in full fidelity.

    `hide`, `show_name` and `layout` are copied deliberately. The agent tool
    `propose_component_edit` writes only key/value/is_null and lets the rest
    fall back to model defaults, which is acceptable there because the caller
    is restating the properties on purpose. Here the component is NOT being
    edited, so anything dropped would be silent damage — `hide` drives KiCad
    field visibility.
    """
    for p in sorted(src.properties, key=lambda r: r.position):
        db.add(M.ComponentProperty(
            component_version_id=dst.id, position=p.position, key=p.key,
            value=p.value, is_null=p.is_null, hide=p.hide,
            show_name=p.show_name, layout=p.layout,
        ))


def _versions(db: Session, comp: M.Component) -> list[M.ComponentVersion]:
    """Query the version rows instead of reading `comp.versions`.

    The session runs `expire_on_commit=False` and rows added here are not
    appended to an already-loaded relationship, so `comp.versions` can be stale
    the moment anything in this module has added a draft. Reading it made the
    coalescing miss its own draft and open a second one.
    """
    return db.query(M.ComponentVersion).filter_by(component_id=comp.id).all()


def _open_auto_draft(db: Session, comp: M.Component) -> M.ComponentVersion | None:
    return next((v for v in _versions(db, comp)
                 if v.status == "draft" and v.created_by == AUTO_ACTOR), None)


def _pins_now(db: Session, cv: M.ComponentVersion) -> tuple[int | None, int | None]:
    """What this component version SHOULD pin, given what is published now."""
    sym = db.query(M.Symbol).filter_by(name=cv.base_component).first()
    sym_id = sym.current_version_id if sym is not None else cv.symbol_version_id

    fp_id = cv.footprint_version_id
    fv = db.get(M.FootprintVersion, cv.footprint_version_id) if cv.footprint_version_id else None
    if fv is not None:
        fp = db.get(M.Footprint, fv.footprint_id)
        if fp is not None and fp.current_version_id is not None:
            fp_id = fp.current_version_id
    return sym_id, fp_id


def _affected(db: Session, kind: str, parent) -> list[M.Component]:
    """Components whose LIVE version uses this symbol / footprint."""
    out = []
    for comp in db.query(M.Component).all():
        cv = _current(comp)
        if cv is None:
            continue
        if kind == "symbol":
            if cv.base_component == parent.name:
                out.append(comp)
        else:
            fv = db.get(M.FootprintVersion, cv.footprint_version_id) if cv.footprint_version_id else None
            if fv is not None and fv.footprint_id == parent.id:
                out.append(comp)
    return out


def repoint_for(db: Session, kind: str, parent) -> dict:
    """Create or refresh one auto-draft per component using this geometry.

    Commits nothing — the caller owns the transaction. Returns a summary the
    approve endpoint can hand back to the UI so the user sees what was filed.
    """
    what = "footprint" if kind == "footprint" else "symbol"
    created: list[str] = []
    refreshed: list[str] = []
    skipped: list[dict] = []

    for comp in _affected(db, kind, parent):
        live = _current(comp)
        if live is None:
            continue
        sym_id, fp_id = _pins_now(db, live)

        draft = _open_auto_draft(db, comp)
        if draft is not None:
            # Fold this change into the pending draft rather than opening a
            # second one against the same parent.
            draft.symbol_version_id = sym_id
            draft.footprint_version_id = fp_id
            draft.comment = _COMMENT.format(what="symbol and footprint")
            refreshed.append(comp.name)
            continue

        human = next((v for v in _versions(db, comp)
                      if v.status == "draft" and v.created_by != AUTO_ACTOR), None)
        if human is not None:
            # Someone is mid-edit. Repointing their draft would rewrite a
            # proposal under review; a parallel auto-draft would collide with
            # it on approval. Report it and let the user resolve it.
            skipped.append({"component": comp.name, "reason": "an edit is already pending review"})
            continue

        if (live.symbol_version_id, live.footprint_version_id) == (sym_id, fp_id):
            continue  # already current — nothing to propose

        cv = M.ComponentVersion(
            component_id=comp.id,
            version_no=max(v.version_no for v in _versions(db, comp)) + 1,
            base_component=live.base_component,
            symbol_version_id=sym_id,
            footprint_version_id=fp_id,
            category_id=live.category_id,
            removed_properties=live.removed_properties,
            status="draft",
            created_by=AUTO_ACTOR,
            comment=_COMMENT.format(what=what),
        )
        db.add(cv)
        db.flush()
        _clone_properties(db, live, cv)
        db.add(M.AuditLog(
            actor=AUTO_ACTOR, action="proposal.create", entity_type="component_version",
            entity_id=str(cv.id),
            details={"component": comp.name, "new": False, "reason": f"{what} repoint",
                     "trigger": f"{what}:{parent.name}"},
        ))
        created.append(comp.name)

    return {"created": created, "refreshed": refreshed, "skipped": skipped,
            "total": len(created) + len(refreshed)}
