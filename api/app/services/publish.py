"""The one publish path (auto-publish era, user design 2026-08-23).

Versions now publish IMMEDIATELY — the review happens afterwards, on the
review axis (`services/review.py`). Every publish, whichever door it came
through (agent tool, web save, web paste box, auto-repoint, or approving a
leftover draft in the old queue), must do the same bookkeeping:

component version publish:
    status -> published, pointer move, datasheet pins, sign-off carry,
    review-record carry, machine validation record, audit.
geometry version publish:
    status -> published, pointer move, material fingerprint, optional
    minor-change waiver (recheck_required=False), sign-off/review carries via
    the repoint that follows, machine validation record, audit.

Neither function commits — the caller owns the transaction, exactly like
`signoff.carry_on_publish`. The mirror rebuild happens after the commit
(`refresh_mirror_for_component` / `refresh_mirror_for_geometry`), because the
generators re-read the DB.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models as M
from ..config import Settings
from . import review, signoff
from .mirror import top_level_of, update_mirror_footprint, update_mirror_symbols


def publish_component_version(db: Session, comp: M.Component, cv: M.ComponentVersion,
                              actor: str, approved_by: str | None = None) -> dict:
    """Publish one component version. Caller owns the transaction.

    Returns {old_cv, tops, signoff, review_carry} for the caller's response
    and mirror refresh.
    """
    old_cv = next((v for v in comp.versions if v.id == comp.current_version_id), None) \
        if comp.current_version_id else None
    if old_cv is None and comp.current_version_id:
        old_cv = db.get(M.ComponentVersion, comp.current_version_id)

    cv.status = "published"
    if approved_by:
        cv.approved_by = approved_by
    comp.current_version_id = cv.id

    from .datasheet_store import pin_datasheets

    pin_datasheets(db, cv)
    db.add(M.AuditLog(actor=actor, action="publish", entity_type="component_version",
                      entity_id=str(cv.id),
                      details={"component": comp.name, "version_no": cv.version_no}))
    carried = signoff.carry_on_publish(db, comp, old_cv, cv)
    review_carry = review.carry_component(db, comp, old_cv, cv)
    # Machine validation AFTER the carry, so its answers merge on top of the
    # carried record instead of replacing it.
    review.machine_check_on_publish(db, "component", comp, cv, comp)

    tops = {top_level_of(cv.category).name}
    if old_cv is not None:
        tops.add(top_level_of(old_cv.category).name)
    return {"old_cv": old_cv, "tops": tops, "signoff": carried, "review_carry": review_carry}


def refresh_mirror_for_component(db: Session, settings: Settings, comp: M.Component,
                                 tops: set[str]) -> dict:
    if not comp.in_library:
        return {"symbol_libs": 0, "components_in_libs": 0, "warnings": []}
    db.expire_all()
    return update_mirror_symbols(db, settings, tops)


def publish_skill_version(db: Session, skill: M.Skill, content: str, actor: str,
                          comment: str | None = None) -> M.SkillVersion:
    """Publish one skill version. Caller owns the transaction.

    **Skills auto-publish too (user decision 2026-08-24).** They were the last
    thing behind the draft gate the 2026-08-23 change left standing, on the
    reasoning that a bad skill steers every future agent run. The gate is gone:
    a skill document is prose, its versions are immutable, and rolling one back
    is opening the previous version and saving it — the same recovery the web
    editor always had. Nothing else in the platform files drafts any more.

    Both doors come here — the web editor (where the user editing IS the
    author) and the agent's `propose_skill_update`. There is no review axis for
    a skill: no material fingerprint, no checklist, nothing to carry. The
    version rows and the audit trail are the whole record.

    `skill.versions` is deliberately NOT read: the session is
    `expire_on_commit=False` and a version added here is not appended to an
    already-loaded relationship, so the numbering would repeat itself (same
    trap as `services/repoint.py`).
    """
    if not content.strip():
        raise ValueError("skill content must not be empty")
    numbers = [n for (n,) in db.query(M.SkillVersion.version_no).filter_by(skill_id=skill.id)]
    sv = M.SkillVersion(skill_id=skill.id, version_no=max(numbers, default=0) + 1,
                        content=content, status="published", created_by=actor,
                        comment=(comment or "").strip() or None)
    db.add(sv)
    db.flush()
    skill.current_version_id = sv.id
    db.add(M.AuditLog(actor=actor, action="publish", entity_type="skill_version",
                      entity_id=str(sv.id),
                      details={"skill": skill.name, "version_no": sv.version_no}))
    return sv


def publish_geometry_version(db: Session, kind: str, parent, version, actor: str,
                             recheck_required: bool | None = None,
                             recheck_note: str | None = None) -> dict:
    """Publish one symbol/footprint version. Caller owns the transaction.

    ``recheck_required``: the minor-change answer. False = "small change, no
    re-verification needed" — carries sign-offs AND review records across the
    changed drawing, with the actor's name in the audit trail. True = force a
    fresh look even on an identical drawing. None = nobody was asked; the
    material fingerprint decides.
    """
    old_version = next((v for v in parent.versions if v.id == parent.current_version_id), None)

    version.status = "published"
    parent.current_version_id = version.id
    signoff.ensure_material_sha(version, kind)
    if recheck_required is not None:
        version.recheck_required = recheck_required
        db.add(M.AuditLog(actor=actor, action="signoff.recheck_decision",
                          entity_type=f"{kind}_version", entity_id=str(version.id),
                          details={kind: parent.name, "recheck_required": recheck_required,
                                   "note": (recheck_note or "").strip() or None}))
    db.add(M.AuditLog(actor=actor, action="publish", entity_type=f"{kind}_version",
                      entity_id=str(version.id),
                      details={kind: parent.name, "version_no": version.version_no}))
    review_carry = review.carry_geometry(db, kind, parent, old_version, version)
    review.machine_check_on_publish(db, kind, parent, version)
    return {"old_version": old_version, "review_carry": review_carry}


def refresh_mirror_for_geometry(db: Session, settings: Settings, kind: str, parent) -> dict:
    """Rebuild everything a geometry publish can touch.

    The injected "7S Version" field means a repointed component's GENERATED
    SYMBOL changes on a footprint publish too — so both kinds rebuild the
    symbol libraries of every affected component, and a footprint publish
    additionally rewrites its own `.kicad_mod`.
    """
    db.expire_all()
    tops: set[str] = set()
    for comp in db.query(M.Component).all():
        cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
        if cv is None:
            continue
        if kind == "symbol":
            if cv.base_component == parent.name:
                tops.add(top_level_of(cv.category).name)
        else:
            fv = db.get(M.FootprintVersion, cv.footprint_version_id) if cv.footprint_version_id else None
            if fv is not None and fv.footprint_id == parent.id:
                tops.add(top_level_of(cv.category).name)

    if kind == "footprint":
        mirror = update_mirror_footprint(db, settings, parent.name)
        if tops:
            sym = update_mirror_symbols(db, settings, tops)
            mirror = {**mirror, **{k: v for k, v in sym.items() if k != "warnings"},
                      "warnings": mirror["warnings"] + sym["warnings"]}
        return mirror
    return update_mirror_symbols(db, settings, tops)


def set_footprint_package_name(db: Session, settings: Settings, fp: M.Footprint,
                               display_name: str, actor: str = "user") -> dict:
    """Set the short package name that `{Footprint_Name}` templates resolve to.

    Unversioned, so this mints no footprint version and the `.kicad_mod` is
    untouched — but it IS baked into every generated `ki_description` that
    references `{Footprint_Name}`, so the symbol libraries of the affected
    categories are rebuilt straight away.

    A brand-new footprint starts with no package name, and the first component
    that uses it then publishes with an unresolved `{Footprint_Name}` mirror
    warning. Naming the footprint is the fix; patching the component is not.
    """
    # `display_name` is unversioned, so the audit row is the ONLY revert path:
    # record the previous value as well as the new one. Without `previous`,
    # undoing a bulk rename pass would mean restoring a whole database dump.
    previous = fp.display_name or ""
    fp.display_name = (display_name or "").strip()[:200]
    if fp.display_name == previous:
        return {"id": fp.id, "name": fp.name, "display_name": fp.display_name,
                "previous": previous, "unchanged": True,
                "rebuilt_libraries": [], "mirror_warnings": []}
    db.add(M.AuditLog(actor=actor, action="footprint.describe", entity_type="footprint",
                      entity_id=str(fp.id),
                      details={"name": fp.name, "display_name": fp.display_name,
                               "previous": previous}))
    db.commit()

    tops: set[str] = set()
    for comp in db.query(M.Component).all():
        cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
        if cv is None or cv.category is None:
            continue
        if any(p.key == "Footprint" and p.value == f"7Sigma:{fp.name}" for p in cv.properties):
            tops.add(top_level_of(cv.category).name)
    mirror = update_mirror_symbols(db, settings, tops) if tops else {"warnings": []}
    return {"id": fp.id, "name": fp.name, "display_name": fp.display_name,
            "previous": previous, "unchanged": False,
            "rebuilt_libraries": sorted(tops),
            "mirror_warnings": mirror.get("warnings", [])}
