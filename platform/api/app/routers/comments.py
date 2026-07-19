"""Component comments — free-form notes under a component, Facebook-style.
Not versioned; deletable; Jaravis reads them as context."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from .util import audit

router = APIRouter(prefix="/api", tags=["comments"])


class CommentIn(BaseModel):
    body: str
    author: str = "user"


def _json(c: M.ComponentComment) -> dict:
    return {
        "id": c.id,
        "component_id": c.component_id,
        "author": c.author,
        "body": c.body,
        "created_at": c.created_at.isoformat(),
    }


@router.get("/components/{comp_id}/comments")
def list_comments(comp_id: int, db: Session = Depends(get_db)):
    if db.get(M.Component, comp_id) is None:
        raise HTTPException(404, "component not found")
    rows = (
        db.query(M.ComponentComment)
        .filter_by(component_id=comp_id)
        .order_by(M.ComponentComment.created_at)
        .all()
    )
    return [_json(c) for c in rows]


@router.post("/components/{comp_id}/comments")
def add_comment(comp_id: int, body: CommentIn, db: Session = Depends(get_db)):
    if db.get(M.Component, comp_id) is None:
        raise HTTPException(404, "component not found")
    text = body.body.strip()
    if not text:
        raise HTTPException(422, "comment must not be empty")
    c = M.ComponentComment(component_id=comp_id, author=body.author.strip() or "user", body=text)
    db.add(c)
    db.flush()
    audit(db, "comment.add", "component_comment", c.id, {"component_id": comp_id})
    db.commit()
    return _json(c)


@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, db: Session = Depends(get_db)):
    c = db.get(M.ComponentComment, comment_id)
    if c is None:
        raise HTTPException(404, "comment not found")
    db.delete(c)
    audit(db, "comment.delete", "component_comment", comment_id, {"component_id": c.component_id})
    db.commit()
    return {"deleted": comment_id}
