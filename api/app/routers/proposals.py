"""Proposals — draft component versions awaiting user approval.

Jaravis (and future fix jobs) can only create drafts; nothing becomes part of
the published library until the user approves it here."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import material, signoff
from ..services.publish import (
    publish_component_version,
    publish_geometry_version,
    refresh_mirror_for_component,
    refresh_mirror_for_geometry,
)
from ..services.render import render_svg
from ..services.repoint import repoint_for
from .util import actor_of, audit, category_path

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


class GeometryApproveIn(BaseModel):
    """The approver's answer to "does this change need a new verification?".

    `None` (the default, and what an older client that sends no body produces)
    means nobody was asked. `services/signoff.py::geometry_carries` then falls
    back to comparing material fingerprints, which is the same thing the UI
    would have offered as the default — so an un-answered approval behaves
    exactly like accepting the suggestion.
    """

    recheck_required: bool | None = None
    note: str | None = None


def _summary(cv: M.ComponentVersion, comp: M.Component) -> dict:
    return {
        "proposal_id": cv.id,
        "component_id": comp.id,
        "component_name": comp.name,
        "version_no": cv.version_no,
        "is_new_component": comp.current_version_id is None,
        "base_component": cv.base_component,
        "category_path": category_path(cv.category),
        "created_by": cv.created_by,
        "created_at": cv.created_at.isoformat(),
        "comment": cv.comment,
        "status": cv.status,
    }


@router.get("")
def list_proposals(db: Session = Depends(get_db)):
    drafts = (
        db.query(M.ComponentVersion)
        .options(selectinload(M.ComponentVersion.category))
        .filter(M.ComponentVersion.status == "draft")
        .order_by(M.ComponentVersion.created_at.desc())
        .all()
    )
    out = []
    for cv in drafts:
        comp = db.get(M.Component, cv.component_id)
        out.append({**_summary(cv, comp), "kind": "component"})
    skill_drafts = (
        db.query(M.SkillVersion)
        .filter(M.SkillVersion.status == "draft")
        .order_by(M.SkillVersion.created_at.desc())
        .all()
    )
    for sv in skill_drafts:
        skill = db.get(M.Skill, sv.skill_id)
        out.append({
            "kind": "skill",
            "proposal_id": sv.id,
            "skill_id": skill.id,
            "skill_name": skill.name,
            "component_name": skill.name,  # display name, keeps table simple
            "version_no": sv.version_no,
            "created_by": sv.created_by,
            "created_at": sv.created_at.isoformat(),
            "comment": sv.comment,
            "status": sv.status,
        })
    for kind, ver_model, parent_attr in (("symbol", M.SymbolVersion, "symbol"),
                                         ("footprint", M.FootprintVersion, "footprint")):
        drafts_g = (db.query(ver_model).filter(ver_model.status == "draft")
                    .order_by(ver_model.created_at.desc()).all())
        for v in drafts_g:
            parent = getattr(v, parent_attr)
            out.append({
                "kind": kind,
                "proposal_id": v.id,
                # the parent symbol/footprint id, so the row can link to
                # /library/templates/<kind>s/<id> instead of being plain text
                "template_id": parent.id,
                "component_name": parent.name,  # display name, keeps table simple
                "version_no": v.version_no,
                "is_new_component": parent.current_version_id is None,
                "created_by": v.created_by,
                "created_at": v.created_at.isoformat(),
                "comment": v.comment,
                "status": v.status,
            })
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


# entity_type (audit log) -> proposal kind shown in the history table
_HISTORY_ENTITY = {
    "component_version": "component",
    "skill_version": "skill",
    "symbol_version": "symbol",
    "footprint_version": "footprint",
}


@router.get("/history")
def list_history(limit: int = 200, db: Session = Depends(get_db)):
    """Decided proposals — the audit trail of the approval queue, newest
    decision first. Sourced from the audit log (`proposal.approve` /
    `proposal.reject`) so all four proposal kinds share one uniform history;
    each row is enriched from its still-present version row (append-only /
    tombstoned), falling back to the audit `details` name if it is gone."""
    rows = (
        db.query(M.AuditLog)
        .filter(M.AuditLog.action.in_(("proposal.approve", "proposal.reject")))
        .order_by(M.AuditLog.ts.desc())
        .limit(max(1, min(limit, 1000)))
        .all()
    )
    out = []
    for a in rows:
        kind = _HISTORY_ENTITY.get(a.entity_type)
        if kind is None:
            continue
        details = a.details or {}
        vid = int(a.entity_id) if a.entity_id and a.entity_id.isdigit() else None
        row = {
            "kind": kind,
            "outcome": "approved" if a.action == "proposal.approve" else "rejected",
            "decided_at": a.ts.isoformat(),
            "decided_by": a.actor,
            "proposal_id": vid,
            "component_id": None,
            # parent symbol/footprint id, so a geometry row links to its
            # template page like a component row links to its detail page.
            # Stays None when the template is gone (a rejected creation takes
            # its stillborn row with it) — there is nothing to link to then.
            "template_id": None,
            "component_name": details.get(kind, ""),
            "version_no": None,
            "created_by": None,
            "created_at": None,
            "comment": None,
            "category_path": "",
        }
        if vid is not None:
            if kind == "component":
                cv = db.get(M.ComponentVersion, vid)
                if cv is not None:
                    comp = db.get(M.Component, cv.component_id)
                    row.update(
                        component_id=cv.component_id,
                        component_name=comp.name if comp else row["component_name"],
                        version_no=cv.version_no,
                        created_by=cv.created_by,
                        created_at=cv.created_at.isoformat(),
                        comment=cv.comment,
                        category_path=category_path(cv.category) if cv.category else "",
                    )
            elif kind == "skill":
                sv = db.get(M.SkillVersion, vid)
                if sv is not None:
                    skill = db.get(M.Skill, sv.skill_id)
                    row.update(
                        component_name=skill.name if skill else row["component_name"],
                        version_no=sv.version_no,
                        created_by=sv.created_by,
                        created_at=sv.created_at.isoformat(),
                        comment=sv.comment,
                    )
            else:
                model = M.SymbolVersion if kind == "symbol" else M.FootprintVersion
                v = db.get(model, vid)
                if v is not None:
                    parent = v.symbol if kind == "symbol" else v.footprint
                    row.update(
                        template_id=parent.id if parent else None,
                        component_name=parent.name if parent else row["component_name"],
                        version_no=v.version_no,
                        created_by=v.created_by,
                        created_at=v.created_at.isoformat(),
                        comment=v.comment,
                    )
        out.append(row)
    return out


@router.post("/{cv_id}/approve")
def approve(cv_id: int, db: Session = Depends(get_db)):
    """Approve a leftover draft. Auto-publish made drafts the exception, but
    approving one must do everything a direct publish does — the shared
    `services/publish.py` path keeps the two from diverging."""
    cv = db.get(M.ComponentVersion, cv_id)
    if cv is None or cv.status != "draft":
        raise HTTPException(404, "draft proposal not found")
    comp = db.get(M.Component, cv.component_id)

    res = publish_component_version(db, comp, cv, actor="user", approved_by="user")
    audit(db, "proposal.approve", "component_version", cv.id, {"component": comp.name})
    db.commit()

    mirror = refresh_mirror_for_component(db, settings, comp, res["tops"])
    return {**_summary(cv, comp), "mirror": {k: v for k, v in mirror.items() if k != "warnings"},
            "mirror_warnings": mirror["warnings"], "signoff": res["signoff"]}


@router.post("/skills/{sv_id}/approve")
def approve_skill(sv_id: int, db: Session = Depends(get_db)):
    sv = db.get(M.SkillVersion, sv_id)
    if sv is None or sv.status != "draft":
        raise HTTPException(404, "draft skill proposal not found")
    skill = db.get(M.Skill, sv.skill_id)
    sv.status = "published"
    skill.current_version_id = sv.id
    audit(db, "proposal.approve", "skill_version", sv.id, {"skill": skill.name})
    db.commit()
    return {"kind": "skill", "proposal_id": sv.id, "skill_name": skill.name,
            "version_no": sv.version_no, "status": "published"}


@router.post("/skills/{sv_id}/reject")
def reject_skill(sv_id: int, db: Session = Depends(get_db)):
    sv = db.get(M.SkillVersion, sv_id)
    if sv is None or sv.status != "draft":
        raise HTTPException(404, "draft skill proposal not found")
    skill = db.get(M.Skill, sv.skill_id)
    sv.status = "rejected"
    audit(db, "proposal.reject", "skill_version", sv.id, {"skill": skill.name})
    db.commit()
    return {"kind": "skill", "proposal_id": sv.id, "skill_name": skill.name,
            "version_no": sv.version_no, "status": "rejected"}


@router.post("/{cv_id}/reject")
def reject(cv_id: int, db: Session = Depends(get_db)):
    cv = db.get(M.ComponentVersion, cv_id)
    if cv is None or cv.status != "draft":
        raise HTTPException(404, "draft proposal not found")
    comp = db.get(M.Component, cv.component_id)
    cv.status = "rejected"
    audit(db, "proposal.reject", "component_version", cv.id, {"component": comp.name})
    db.commit()
    return _summary(cv, comp)


# ------------------------------------------------ symbol / footprint proposals
def _geometry_draft(db: Session, kind: str, ver_id: int):
    model = M.SymbolVersion if kind == "symbol" else M.FootprintVersion
    v = db.get(model, ver_id)
    if v is None:
        raise HTTPException(404, f"draft {kind} proposal not found")
    parent = v.symbol if kind == "symbol" else v.footprint
    return v, parent


def _geometry_json(kind: str, v, parent) -> dict:
    return {"kind": kind, "proposal_id": v.id, "component_name": parent.name,
            "version_no": v.version_no, "status": v.status,
            "is_new_component": parent.current_version_id is None or parent.current_version_id == v.id}


@router.get("/{kind}s/{ver_id}/preview.svg")
def geometry_preview(kind: str, ver_id: int, which: str = "draft", db: Session = Depends(get_db)):
    """Visual review of a symbol/footprint proposal: `which=draft` renders the
    proposed source, `which=current` the live published version (404 when the
    proposal creates a brand-new symbol/footprint)."""
    if kind not in ("symbol", "footprint"):
        raise HTTPException(404, "kind must be symbol or footprint")
    v, parent = _geometry_draft(db, kind, ver_id)
    if which == "current":
        cur = next((x for x in parent.versions if x.id == parent.current_version_id), None)
        if cur is None:
            raise HTTPException(404, "no current published version (new proposal)")
        source = cur.source_text
    else:
        source = v.source_text
    try:
        svg = render_svg(kind, parent.name, source)
    except Exception as e:
        raise HTTPException(502, f"render failed: {e}")
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "max-age=300"})


@router.get("/{kind}s/{ver_id}/material-diff")
def geometry_material_diff(kind: str, ver_id: int, db: Session = Depends(get_db)):
    """Does this draft change anything that reaches the board?

    What the approval dialog pre-answers "does this need a new verification?"
    with. `same_material` is provable — it compares the fingerprints defined in
    `services/material.py` — so a silkscreen-only edit can carry forty
    sign-offs on one click, while a moved pad cannot carry any of them by
    accident.
    """
    if kind not in ("symbol", "footprint"):
        raise HTTPException(404, "kind must be symbol or footprint")
    v, parent = _geometry_draft(db, kind, ver_id)
    cur = next((x for x in parent.versions if x.id == parent.current_version_id), None)

    affected = _components_using(db, kind, parent)
    states = signoff.states_for(db, affected, detail=False)
    signed = sum(1 for s in states.values() if s["state"] == "signed")

    if cur is None:
        return {"kind": kind, "name": parent.name, "is_new": True, "same_material": False,
                "changed": ["this is a new template — there is nothing to compare against"],
                "suggest_recheck": True, "affected_components": len(affected),
                "affected_signed": signed}

    old_sha = signoff.ensure_material_sha(cur, kind)
    new_sha = signoff.ensure_material_sha(v, kind)
    if db.dirty or db.new:
        db.commit()  # the fingerprints are a cache; keep what we just computed
    same = bool(old_sha) and bool(new_sha) and old_sha == new_sha
    changed = [] if same else material.describe_changes(kind, cur.source_text, v.source_text)
    if not same and not changed:
        # Fingerprints differ but the describer found nothing nameable. Say so
        # rather than showing an empty list that reads like "no change".
        changed = ["the drawing changed in a way this comparison cannot name"]
    return {
        "kind": kind, "name": parent.name, "is_new": False,
        "from_version": cur.version_no, "to_version": v.version_no,
        "same_material": same,
        "changed": changed,
        "suggest_recheck": not same,
        "affected_components": len(affected),
        "affected_signed": signed,
    }


def _components_using(db: Session, kind: str, parent) -> list[M.Component]:
    """Components whose LIVE version uses this symbol / footprint.

    Same question `repoint._affected` answers, asked here for reporting only.
    Expressed as a join rather than a loop of `db.get`: this runs every time the
    approve dialog opens, and loading a FootprintVersion row per component
    drags its whole `.kicad_mod` body along with it.
    """
    q = (
        db.query(M.Component)
        .join(M.ComponentVersion, M.ComponentVersion.id == M.Component.current_version_id)
    )
    if kind == "symbol":
        return q.filter(M.ComponentVersion.base_component == parent.name).all()
    return (
        q.join(M.FootprintVersion, M.FootprintVersion.id == M.ComponentVersion.footprint_version_id)
        .filter(M.FootprintVersion.footprint_id == parent.id)
        .all()
    )


@router.post("/symbols/{ver_id}/approve")
def approve_symbol(ver_id: int, request: Request, body: GeometryApproveIn | None = None,
                   db: Session = Depends(get_db)):
    sv, sym = _geometry_draft(db, "symbol", ver_id)
    if sv.status != "draft":
        raise HTTPException(404, "draft symbol proposal not found")
    publish_geometry_version(db, "symbol", sym, sv, actor_of(request),
                             recheck_required=body.recheck_required if body else None,
                             recheck_note=body.note if body else None)
    audit(db, "proposal.approve", "symbol_version", sv.id, {"symbol": sym.name})
    # Same transaction as the publish: a crash must not leave the symbol
    # current with its components silently pinned to the old drawing.
    repointed = repoint_for(db, "symbol", sym) if settings.auto_repoint_components else None
    db.commit()

    mirror = refresh_mirror_for_geometry(db, settings, "symbol", sym)
    return {**_geometry_json("symbol", sv, sym),
            "mirror": {k: v for k, v in mirror.items() if k != "warnings"},
            "mirror_warnings": mirror["warnings"],
            "repointed": repointed}


def _drop_if_stillborn(db: Session, parent, kind: str) -> bool:
    """Delete a symbol/footprint row whose ONLY version was just rejected.

    A creation proposal makes the parent row up front with
    `current_version_id=None`, so rejecting it used to leave a permanent
    versionless entry in the Templates browser — nothing pointed at it and no
    UI could remove it. Rejecting the last draft of a template that was never
    published therefore takes the row with it. A template with any published
    history is untouched: rejecting one draft must never delete real versions.
    """
    if parent.current_version_id is not None:
        return False
    if any(v.status != "rejected" for v in parent.versions):
        return False
    audit(db, "proposal.reject", kind, parent.id,
          {"name": parent.name, "removed_stillborn_row": True})
    # notes live in the generic comments table keyed on (target_type, target_id),
    # with no FK to cascade — take them with the row or they outlive their target
    db.query(M.Comment).filter_by(target_type=kind, target_id=parent.id).delete()
    for v in list(parent.versions):
        db.delete(v)
    db.delete(parent)
    return True


@router.post("/symbols/{ver_id}/reject")
def reject_symbol(ver_id: int, db: Session = Depends(get_db)):
    sv, sym = _geometry_draft(db, "symbol", ver_id)
    if sv.status != "draft":
        raise HTTPException(404, "draft symbol proposal not found")
    sv.status = "rejected"
    audit(db, "proposal.reject", "symbol_version", sv.id, {"symbol": sym.name})
    payload = _geometry_json("symbol", sv, sym)
    payload["removed_row"] = _drop_if_stillborn(db, sym, "symbol")
    db.commit()
    return payload


@router.post("/footprints/{ver_id}/approve")
def approve_footprint(ver_id: int, request: Request, body: GeometryApproveIn | None = None,
                      db: Session = Depends(get_db)):
    fv, fp = _geometry_draft(db, "footprint", ver_id)
    if fv.status != "draft":
        raise HTTPException(404, "draft footprint proposal not found")
    publish_geometry_version(db, "footprint", fp, fv, actor_of(request),
                             recheck_required=body.recheck_required if body else None,
                             recheck_note=body.note if body else None)
    audit(db, "proposal.approve", "footprint_version", fv.id, {"footprint": fp.name})
    # Same transaction as the publish: a crash must not leave the footprint
    # current with its components silently pinned to the old drawing.
    repointed = repoint_for(db, "footprint", fp) if settings.auto_repoint_components else None
    db.commit()

    mirror = refresh_mirror_for_geometry(db, settings, "footprint", fp)
    return {**_geometry_json("footprint", fv, fp),
            "mirror": {k: v for k, v in mirror.items() if k != "warnings"},
            "mirror_warnings": mirror["warnings"],
            "repointed": repointed}


@router.post("/footprints/{ver_id}/reject")
def reject_footprint(ver_id: int, db: Session = Depends(get_db)):
    fv, fp = _geometry_draft(db, "footprint", ver_id)
    if fv.status != "draft":
        raise HTTPException(404, "draft footprint proposal not found")
    fv.status = "rejected"
    audit(db, "proposal.reject", "footprint_version", fv.id, {"footprint": fp.name})
    payload = _geometry_json("footprint", fv, fp)
    payload["removed_row"] = _drop_if_stillborn(db, fp, "footprint")
    db.commit()
    return payload
