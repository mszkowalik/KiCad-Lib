"""Undo any change (decision 0089): what each request changed, and the way back.

Open to every signed-in user. A user sees and undoes their own requests; an
administrator, anybody's. The rows are what the database trigger recorded
(`services/row_changes.py`), so they cover every route, the cascades Postgres
runs itself, and the work of agents.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import row_changes as svc

router = APIRouter(prefix="/api/undo", tags=["undo"])


@router.get("/requests")
def list_requests(everyone: bool = False, user_id: int | None = None, client: str = "", table: str = "",
                  before: int | None = None, limit: int = 30, db: Session = Depends(get_db)):
    """Requests that changed rows, newest first. `everyone` and `user_id`
    need an administrator. `client` narrows to browser, token, mcp or job;
    `before` pages by the `last_id` of the previous page."""
    return svc.list_groups(db, everyone=everyone, user_id=user_id, client=client, table=table,
                           before=before, limit=limit)


@router.get("/requests/{key}")
def get_request(key: str, limit: int = 200, db: Session = Depends(get_db)):
    """One request's recorded rows: the values before and after each change."""
    return svc.detail(db, key, limit=limit)


class UndoIn(BaseModel):
    dry_run: bool = True


@router.post("/requests/{key}")
def undo_request(key: str, body: UndoIn, db: Session = Depends(get_db)):
    """Undo one request. The dry run (the default) lists what would be
    written and anything that refuses it; repeat with dry_run false."""
    return svc.undo(db, key, dry_run=body.dry_run)


@router.get("/rows/{table}")
def row_history(table: str, id: int | None = None, pk: str = "", db: Session = Depends(get_db)):
    """Every recorded change of one row, newest first: `id`, or `pk` as JSON
    for a table keyed otherwise. A non-administrator sees only rows their own
    requests changed."""
    key = {"id": id} if id is not None else (json.loads(pk) if pk else None)
    if not key:
        raise HTTPException(422, "give `id`, or `pk` as JSON")
    return svc.row_history(db, table, key)
