"""Auto-repoint: keep components pointing at the current symbol/footprint.

A `ComponentVersion` PINS the exact geometry it was drawn against
(`symbol_version_id`, `footprint_version_id`). Publishing a new symbol or
footprint version moves only the template's own `current_version_id` and
rebuilds the mirror — it used to leave every component pinned to the superseded
drawing. A pin-1 sweep on 2026-08-03 published 105 new footprint versions and
left 185 of 327 components pinned to the version before it.

**Since auto-publish (2026-08-23) the repoint PUBLISHES directly.** Each
geometry publish files one published component version per affected part —
properties cloned in full fidelity, pins moved — through
`publish.publish_component_version`, so the sign-off carry, the review-record
carry and the machine validation all run exactly as for any other publish. A
repoint that moves onto an identical drawing therefore keeps both the
production sign-off and the verification record; a real change strips them and
the part shows up in the review queue.

Invariants kept from the draft era:

- **A pending human/agent DRAFT is skipped, never rewritten** — repointing a
  proposal under review would silently rewrite somebody's edit. Reported in
  `skipped`.
- **A leftover auto-DRAFT from the draft era is refreshed and published** in
  place of minting a second version.
- **Never read `comp.versions` inside this module** — the session is
  `expire_on_commit=False` and rows added here are not appended to loaded
  relationships. Use `_versions(db, comp)`.
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
    the moment anything in this module has added a version. Reading it made the
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
    """Publish one repoint version per component using this geometry.

    Commits nothing — the caller owns the transaction (it runs inside the
    geometry publish). Returns a summary the caller hands back to the UI.
    """
    from .publish import publish_component_version

    what = "footprint" if kind == "footprint" else "symbol"
    published: list[str] = []
    skipped: list[dict] = []

    for comp in _affected(db, kind, parent):
        live = _current(comp)
        if live is None:
            continue
        sym_id, fp_id = _pins_now(db, live)

        human = next((v for v in _versions(db, comp)
                      if v.status == "draft" and v.created_by != AUTO_ACTOR), None)
        if human is not None:
            # Someone is mid-edit. Repointing their draft would rewrite a
            # proposal under review; a parallel publish would collide with it
            # on approval. Report it and let the user resolve it.
            skipped.append({"component": comp.name, "reason": "an edit is already pending review"})
            continue

        stale_draft = _open_auto_draft(db, comp)
        if stale_draft is not None:
            # A leftover from the draft era: refresh its pins and publish it
            # instead of minting a parallel version.
            stale_draft.symbol_version_id = sym_id
            stale_draft.footprint_version_id = fp_id
            stale_draft.comment = _COMMENT.format(what="symbol and footprint")
            publish_component_version(db, comp, stale_draft, actor=AUTO_ACTOR)
            published.append(comp.name)
            continue

        if (live.symbol_version_id, live.footprint_version_id) == (sym_id, fp_id):
            continue  # already current — nothing to do

        cv = M.ComponentVersion(
            component_id=comp.id,
            version_no=max(v.version_no for v in _versions(db, comp)) + 1,
            base_component=live.base_component,
            symbol_version_id=sym_id,
            footprint_version_id=fp_id,
            category_id=live.category_id,
            removed_properties=live.removed_properties,
            status="published",
            created_by=AUTO_ACTOR,
            comment=_COMMENT.format(what=what),
        )
        db.add(cv)
        db.flush()
        _clone_properties(db, live, cv)
        publish_component_version(db, comp, cv, actor=AUTO_ACTOR)
        published.append(comp.name)

    return {"published": published, "skipped": skipped, "total": len(published),
            # kept for older UI code that reads these keys
            "created": published, "refreshed": []}
