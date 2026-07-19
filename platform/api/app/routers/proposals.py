"""Proposals — draft component versions awaiting user approval.

Jaravis (and future fix jobs) can only create drafts; nothing becomes part of
the published library until the user approves it here."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.mirror import top_level_of, update_mirror_symbols
from .util import audit, category_path

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


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
    out.sort(key=lambda x: x["created_at"], reverse=True)
    return out


@router.post("/{cv_id}/approve")
def approve(cv_id: int, db: Session = Depends(get_db)):
    cv = db.get(M.ComponentVersion, cv_id)
    if cv is None or cv.status != "draft":
        raise HTTPException(404, "draft proposal not found")
    comp = db.get(M.Component, cv.component_id)

    tops = {top_level_of(cv.category).name}
    if comp.current_version_id is not None:
        old = db.get(M.ComponentVersion, comp.current_version_id)
        if old is not None:
            tops.add(top_level_of(old.category).name)

    cv.status = "published"
    cv.approved_by = "user"
    comp.current_version_id = cv.id
    from ..services.datasheet_store import pin_datasheets

    pin_datasheets(db, cv)  # record the PDF versions this approved version uses
    audit(db, "proposal.approve", "component_version", cv.id, {"component": comp.name})
    db.commit()

    db.expire_all()
    mirror = update_mirror_symbols(db, settings, tops)
    return {**_summary(cv, comp), "mirror": {k: v for k, v in mirror.items() if k != "warnings"},
            "mirror_warnings": mirror["warnings"]}


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
