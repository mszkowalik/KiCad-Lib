"""Category tree — browse + light editing (create/rename/move/delete).

Tree edits are lightweight and audited; MOVING A COMPONENT between categories
is a versioned change and lives in the components router (Phase 03 proposals).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from .util import audit

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryCreate(BaseModel):
    name: str
    parent_id: int | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None
    position: int | None = None


def _component_counts(db: Session) -> dict[int, int]:
    """Direct count of components whose CURRENT version sits in each category."""
    rows = db.execute(
        select(M.ComponentVersion.category_id, func.count())
        .join(M.Component, M.Component.current_version_id == M.ComponentVersion.id)
        .group_by(M.ComponentVersion.category_id)
    ).all()
    return {cid: n for cid, n in rows}


@router.get("")
def tree(db: Session = Depends(get_db)):
    cats = db.query(M.Category).order_by(M.Category.position, M.Category.name).all()
    counts = _component_counts(db)

    def node(cat: M.Category) -> dict:
        kids = [node(c) for c in sorted(
            (x for x in cats if x.parent_id == cat.id), key=lambda x: (x.position, x.name)
        )]
        direct = counts.get(cat.id, 0)
        return {
            "id": cat.id,
            "name": cat.name,
            "parent_id": cat.parent_id,
            "component_count": direct,
            "total_count": direct + sum(k["total_count"] for k in kids),
            "has_defaults": bool(cat.defaults),
            "children": kids,
        }

    return [node(c) for c in cats if c.parent_id is None]


@router.post("")
def create(body: CategoryCreate, db: Session = Depends(get_db)):
    if body.parent_id is not None and db.get(M.Category, body.parent_id) is None:
        raise HTTPException(404, "parent category not found")
    dup = db.query(M.Category).filter_by(parent_id=body.parent_id, name=body.name).first()
    if dup:
        raise HTTPException(409, "a sibling category with this name already exists")
    cat = M.Category(name=body.name, parent_id=body.parent_id)
    db.add(cat)
    db.flush()
    audit(db, "category.create", "category", cat.id, {"name": body.name, "parent_id": body.parent_id})
    db.commit()
    return {"id": cat.id, "name": cat.name, "parent_id": cat.parent_id}


@router.patch("/{cat_id}")
def update(cat_id: int, body: CategoryUpdate, db: Session = Depends(get_db)):
    cat = db.get(M.Category, cat_id)
    if cat is None:
        raise HTTPException(404, "category not found")
    changes: dict = {}
    if body.parent_id is not None or "parent_id" in body.model_fields_set:
        # cycle check: new parent must not be the category itself or a descendant
        node = db.get(M.Category, body.parent_id) if body.parent_id is not None else None
        probe = node
        while probe is not None:
            if probe.id == cat.id:
                raise HTTPException(409, "cannot move a category under its own descendant")
            probe = probe.parent
        changes["parent_id"] = [cat.parent_id, body.parent_id]
        cat.parent_id = body.parent_id
    if body.name is not None:
        changes["name"] = [cat.name, body.name]
        cat.name = body.name
    if body.position is not None:
        changes["position"] = [cat.position, body.position]
        cat.position = body.position
    audit(db, "category.update", "category", cat.id, changes)
    db.commit()
    return {"id": cat.id, "name": cat.name, "parent_id": cat.parent_id, "position": cat.position}


@router.delete("/{cat_id}")
def delete(cat_id: int, db: Session = Depends(get_db)):
    cat = db.get(M.Category, cat_id)
    if cat is None:
        raise HTTPException(404, "category not found")
    if db.query(M.Category).filter_by(parent_id=cat_id).first():
        raise HTTPException(409, "category has subcategories — move or delete them first")
    if db.query(M.ComponentVersion).filter_by(category_id=cat_id).first():
        raise HTTPException(409, "category is referenced by component versions — move the components first")
    db.delete(cat)
    audit(db, "category.delete", "category", cat_id, {"name": cat.name})
    db.commit()
    return {"deleted": cat_id}
