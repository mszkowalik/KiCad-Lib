"""The change feed — what moved in the library lately, and who moved it.

Two endpoints on purpose. The list is a keyset-paginated page of one-line rows;
the diff for any one row is a second call. Everything about why lives in
`services/changes.py` — this router only validates and hands over.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import changes as changes_svc

router = APIRouter(prefix="/api/changes", tags=["changes"])


@router.get("")
def list_changes(
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    kind: list[str] | None = Query(None),
    actor: str = "",
    q: str = "",
    db: Session = Depends(get_db),
):
    """One page, newest first. Pass the returned `next_cursor` back as `cursor`
    for the following page; `null` means the feed is exhausted."""
    return changes_svc.feed(db, limit=limit, cursor=cursor, kinds=kind, actor=actor, q=q)


@router.get("/{kind}/{row_id}")
def change_detail(kind: str, row_id: int, db: Session = Depends(get_db)):
    """The unfolded diff. Called when a row is expanded, never before."""
    if kind not in changes_svc.KINDS:
        raise HTTPException(404, f"kind must be one of {', '.join(changes_svc.KINDS)}")
    out = changes_svc.detail(db, kind, row_id)
    if out is None:
        raise HTTPException(404, "that change no longer exists")
    return out
