"""Skills — the editable convention documents Jaravis's system prompt is built
from (conventions-library / -footprints / -symbols, seeded from
app/seed_skills/). Editing creates a new immutable version and advances the
current pointer (the user editing IS the approval); Jaravis rebuilds its prompt
from current versions on every chat call, so edits apply immediately."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..db import get_db
from .util import audit

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillEdit(BaseModel):
    content: str


class SkillCreate(SkillEdit):
    name: str


def _current(skill: M.Skill) -> M.SkillVersion | None:
    return next((v for v in skill.versions if v.id == skill.current_version_id), None)


@router.get("")
def list_skills(db: Session = Depends(get_db)):
    skills = db.query(M.Skill).options(selectinload(M.Skill.versions)).order_by(M.Skill.name).all()
    out = []
    for s in skills:
        cur = _current(s)
        out.append({
            "id": s.id,
            "name": s.name,
            "current_version_no": cur.version_no if cur else None,
            "updated_at": cur.created_at.isoformat() if cur else None,
            "size": len(cur.content) if cur else 0,
        })
    return out


@router.get("/{skill_id}")
def skill_detail(skill_id: int, db: Session = Depends(get_db)):
    s = db.query(M.Skill).options(selectinload(M.Skill.versions)).filter_by(id=skill_id).first()
    if s is None:
        raise HTTPException(404, "skill not found")
    cur = _current(s)
    return {
        "id": s.id,
        "name": s.name,
        "current_version_no": cur.version_no if cur else None,
        "content": cur.content if cur else "",
        "versions": [
            {"version_no": v.version_no, "created_at": v.created_at.isoformat(),
             "created_by": v.created_by, "status": v.status, "comment": v.comment,
             "size": len(v.content)}
            for v in s.versions
        ],
    }


@router.get("/{skill_id}/versions/{version_no}")
def skill_version(skill_id: int, version_no: int, db: Session = Depends(get_db)):
    s = db.query(M.Skill).options(selectinload(M.Skill.versions)).filter_by(id=skill_id).first()
    if s is None:
        raise HTTPException(404, "skill not found")
    v = next((x for x in s.versions if x.version_no == version_no), None)
    if v is None:
        raise HTTPException(404, "version not found")
    return {"skill_id": s.id, "name": s.name, "version_no": v.version_no,
            "created_at": v.created_at.isoformat(), "created_by": v.created_by,
            "status": v.status, "comment": v.comment, "content": v.content}


@router.post("/{skill_id}/versions")
def edit_skill(skill_id: int, body: SkillEdit, db: Session = Depends(get_db)):
    s = db.query(M.Skill).options(selectinload(M.Skill.versions)).filter_by(id=skill_id).first()
    if s is None:
        raise HTTPException(404, "skill not found")
    if not body.content.strip():
        raise HTTPException(422, "skill content must not be empty")
    new_no = max((v.version_no for v in s.versions), default=0) + 1
    v = M.SkillVersion(skill_id=s.id, version_no=new_no, content=body.content, created_by="user")
    db.add(v)
    db.flush()
    s.current_version_id = v.id
    audit(db, "skill.edit", "skill", s.id, {"name": s.name, "version_no": new_no})
    db.commit()
    return {"id": s.id, "name": s.name, "current_version_no": new_no}


@router.post("")
def create_skill(body: SkillCreate, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "skill name must not be empty")
    if db.query(M.Skill).filter_by(name=name).first():
        raise HTTPException(409, f"skill {name!r} already exists")
    if not body.content.strip():
        raise HTTPException(422, "skill content must not be empty")
    s = M.Skill(name=name)
    db.add(s)
    db.flush()
    v = M.SkillVersion(skill_id=s.id, version_no=1, content=body.content, created_by="user")
    db.add(v)
    db.flush()
    s.current_version_id = v.id
    audit(db, "skill.create", "skill", s.id, {"name": name})
    db.commit()
    return {"id": s.id, "name": s.name, "current_version_no": 1}
