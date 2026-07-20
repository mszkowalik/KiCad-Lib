"""Proposals — draft component versions awaiting user approval.

Jaravis (and future fix jobs) can only create drafts; nothing becomes part of
the published library until the user approves it here."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.mirror import top_level_of, update_mirror_footprint, update_mirror_symbols
from ..services.render import render_svg
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
    for kind, ver_model, parent_attr in (("symbol", M.SymbolVersion, "symbol"),
                                         ("footprint", M.FootprintVersion, "footprint")):
        drafts_g = (db.query(ver_model).filter(ver_model.status == "draft")
                    .order_by(ver_model.created_at.desc()).all())
        for v in drafts_g:
            parent = getattr(v, parent_attr)
            out.append({
                "kind": kind,
                "proposal_id": v.id,
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


@router.post("/symbols/{ver_id}/approve")
def approve_symbol(ver_id: int, db: Session = Depends(get_db)):
    sv, sym = _geometry_draft(db, "symbol", ver_id)
    if sv.status != "draft":
        raise HTTPException(404, "draft symbol proposal not found")
    sv.status = "published"
    sym.current_version_id = sv.id
    audit(db, "proposal.approve", "symbol_version", sv.id, {"symbol": sym.name})
    db.commit()

    # Rebuild the KiCad-facing libraries that show this drawing: the base
    # library always (PCM package / HTTP catalog), plus every top-level
    # generated library containing a component that uses this base symbol.
    db.expire_all()
    tops: set[str] = set()
    for comp in db.query(M.Component).all():
        cv = next((x for x in comp.versions if x.id == comp.current_version_id), None)
        if cv is not None and cv.base_component == sym.name:
            tops.add(top_level_of(cv.category).name)
    mirror = update_mirror_symbols(db, settings, tops)
    return {**_geometry_json("symbol", sv, sym),
            "mirror": {k: v for k, v in mirror.items() if k != "warnings"},
            "mirror_warnings": mirror["warnings"]}


@router.post("/symbols/{ver_id}/reject")
def reject_symbol(ver_id: int, db: Session = Depends(get_db)):
    sv, sym = _geometry_draft(db, "symbol", ver_id)
    if sv.status != "draft":
        raise HTTPException(404, "draft symbol proposal not found")
    sv.status = "rejected"
    audit(db, "proposal.reject", "symbol_version", sv.id, {"symbol": sym.name})
    db.commit()
    return _geometry_json("symbol", sv, sym)


@router.post("/footprints/{ver_id}/approve")
def approve_footprint(ver_id: int, db: Session = Depends(get_db)):
    fv, fp = _geometry_draft(db, "footprint", ver_id)
    if fv.status != "draft":
        raise HTTPException(404, "draft footprint proposal not found")
    fv.status = "published"
    fp.current_version_id = fv.id
    audit(db, "proposal.approve", "footprint_version", fv.id, {"footprint": fp.name})
    db.commit()

    db.expire_all()
    mirror = update_mirror_footprint(db, settings, fp.name)
    return {**_geometry_json("footprint", fv, fp),
            "mirror": {k: v for k, v in mirror.items() if k != "warnings"},
            "mirror_warnings": mirror["warnings"]}


@router.post("/footprints/{ver_id}/reject")
def reject_footprint(ver_id: int, db: Session = Depends(get_db)):
    fv, fp = _geometry_draft(db, "footprint", ver_id)
    if fv.status != "draft":
        raise HTTPException(404, "draft footprint proposal not found")
    fv.status = "rejected"
    audit(db, "proposal.reject", "footprint_version", fv.id, {"footprint": fp.name})
    db.commit()
    return _geometry_json("footprint", fv, fp)
