"""Skills — the editable convention documents Jaravis's system prompt is built
from (conventions-library / -footprints / -symbols, seeded from
app/seed_skills/). Editing creates a new immutable version and advances the
current pointer; Jaravis rebuilds its prompt from current versions on every
chat call, so edits apply immediately. Since 2026-08-24 the agent's
`propose_skill_update` publishes the same way — skills were the last thing
behind the draft gate, and it is gone."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..db import get_db
from ..services.publish import publish_skill_version
from .util import actor_of, audit

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillEdit(BaseModel):
    content: str
    #: what changed, shown in the version history (the editor leaves it empty)
    comment: str = ""


class SkillCreate(SkillEdit):
    name: str
    description: str = ""


class SkillMeta(BaseModel):
    """Unversioned skill metadata (see the ``description`` note on M.Skill)."""

    description: str


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
            "description": s.description or "",
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
        "description": s.description or "",
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
def edit_skill(skill_id: int, body: SkillEdit, request: Request,
               db: Session = Depends(get_db)):
    """Save the editor's text as the new live version.

    Publishing lives in `services/publish.py::publish_skill_version`, shared
    with the agent's `propose_skill_update` — one place decides what a skill
    publish records."""
    s = db.query(M.Skill).options(selectinload(M.Skill.versions)).filter_by(id=skill_id).first()
    if s is None:
        raise HTTPException(404, "skill not found")
    try:
        v = publish_skill_version(db, s, body.content, actor=actor_of(request),
                                  comment=body.comment)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    db.commit()
    return {"id": s.id, "name": s.name, "current_version_no": v.version_no}


@router.patch("/{skill_id}")
def edit_skill_meta(skill_id: int, body: SkillMeta, db: Session = Depends(get_db)):
    """Update the when-to-use description. Unversioned, so this does NOT mint a
    new content version — the UI saves it independently of the editor text."""
    s = db.query(M.Skill).filter_by(id=skill_id).first()
    if s is None:
        raise HTTPException(404, "skill not found")
    s.description = body.description.strip()[:500]
    audit(db, "skill.describe", "skill", s.id, {"name": s.name, "description": s.description})
    db.commit()
    return {"id": s.id, "name": s.name, "description": s.description}


@router.delete("/{skill_id}")
def delete_skill(skill_id: int, db: Session = Depends(get_db)):
    """Permanently remove a skill and every one of its versions.

    Unlike component/geometry versions, a skill version is a document with no
    published artefact hanging off it — nothing references it once it stops
    being current — so retiring an obsolete skill is a hard delete rather than a
    tombstone. Jaravis rebuilds its prompt without it on the next chat, and the
    Claude Code mirror drops the directory on its next sync."""
    s = db.query(M.Skill).options(selectinload(M.Skill.versions)).filter_by(id=skill_id).first()
    if s is None:
        raise HTTPException(404, "skill not found")
    name, n_versions = s.name, len(s.versions)
    # Clear the pointer first: current_version_id is a plain Integer, so the
    # rows it points at must not be deleted while it still holds their id.
    s.current_version_id = None
    db.flush()
    for v in list(s.versions):
        db.delete(v)
    db.delete(s)
    audit(db, "skill.delete", "skill", skill_id, {"name": name, "versions_removed": n_versions})
    db.commit()
    return {"deleted": skill_id, "name": name, "versions_removed": n_versions}


@router.post("")
def create_skill(body: SkillCreate, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "skill name must not be empty")
    if db.query(M.Skill).filter_by(name=name).first():
        raise HTTPException(409, f"skill {name!r} already exists")
    if not body.content.strip():
        raise HTTPException(422, "skill content must not be empty")
    s = M.Skill(name=name, description=body.description.strip()[:500])
    db.add(s)
    db.flush()
    v = M.SkillVersion(skill_id=s.id, version_no=1, content=body.content, created_by="user")
    db.add(v)
    db.flush()
    s.current_version_id = v.id
    audit(db, "skill.create", "skill", s.id, {"name": name})
    db.commit()
    return {"id": s.id, "name": s.name, "description": s.description, "current_version_no": 1}
