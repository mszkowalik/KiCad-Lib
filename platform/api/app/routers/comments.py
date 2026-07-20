"""Comments — free-form notes on any entity (component, symbol, footprint).
Facebook-style: not versioned; deletable; Jaravis reads them as context.

One generic `comments` table (`target_type` + `target_id`); each entity family
gets its own list/add URL so callers stay explicit about what they annotate."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from .util import audit

router = APIRouter(prefix="/api", tags=["comments"])

# target_type -> parent model, for existence checks.
_TARGETS: dict[str, type] = {
    "component": M.Component,
    "symbol": M.Symbol,
    "footprint": M.Footprint,
}


class CommentIn(BaseModel):
    body: str
    author: str = "user"


def _json(c: M.Comment) -> dict:
    return {
        "id": c.id,
        "target_type": c.target_type,
        "target_id": c.target_id,
        "author": c.author,
        "body": c.body,
        "created_at": c.created_at.isoformat(),
    }


def _require_target(db: Session, target_type: str, target_id: int) -> None:
    model = _TARGETS[target_type]
    if db.get(model, target_id) is None:
        raise HTTPException(404, f"{target_type} not found")


def _list(db: Session, target_type: str, target_id: int) -> list[dict]:
    _require_target(db, target_type, target_id)
    rows = (
        db.query(M.Comment)
        .filter_by(target_type=target_type, target_id=target_id)
        .order_by(M.Comment.created_at)
        .all()
    )
    return [_json(c) for c in rows]


def _add(db: Session, target_type: str, target_id: int, body: CommentIn) -> dict:
    _require_target(db, target_type, target_id)
    text = body.body.strip()
    if not text:
        raise HTTPException(422, "comment must not be empty")
    c = M.Comment(
        target_type=target_type,
        target_id=target_id,
        author=body.author.strip() or "user",
        body=text,
    )
    db.add(c)
    db.flush()
    audit(db, "comment.add", "comment", c.id, {"target_type": target_type, "target_id": target_id})
    db.commit()
    return _json(c)


# ---- component -------------------------------------------------------------
@router.get("/components/{comp_id}/comments")
def list_component_comments(comp_id: int, db: Session = Depends(get_db)):
    return _list(db, "component", comp_id)


@router.post("/components/{comp_id}/comments")
def add_component_comment(comp_id: int, body: CommentIn, db: Session = Depends(get_db)):
    return _add(db, "component", comp_id, body)


# ---- symbol ----------------------------------------------------------------
@router.get("/symbols/{sym_id}/comments")
def list_symbol_comments(sym_id: int, db: Session = Depends(get_db)):
    return _list(db, "symbol", sym_id)


@router.post("/symbols/{sym_id}/comments")
def add_symbol_comment(sym_id: int, body: CommentIn, db: Session = Depends(get_db)):
    return _add(db, "symbol", sym_id, body)


# ---- footprint -------------------------------------------------------------
@router.get("/footprints/{fp_id}/comments")
def list_footprint_comments(fp_id: int, db: Session = Depends(get_db)):
    return _list(db, "footprint", fp_id)


@router.post("/footprints/{fp_id}/comments")
def add_footprint_comment(fp_id: int, body: CommentIn, db: Session = Depends(get_db)):
    return _add(db, "footprint", fp_id, body)


# ---- delete (generic) ------------------------------------------------------
@router.delete("/comments/{comment_id}")
def delete_comment(comment_id: int, db: Session = Depends(get_db)):
    c = db.get(M.Comment, comment_id)
    if c is None:
        raise HTTPException(404, "comment not found")
    db.delete(c)
    audit(db, "comment.delete", "comment", comment_id,
          {"target_type": c.target_type, "target_id": c.target_id})
    db.commit()
    return {"deleted": comment_id}
