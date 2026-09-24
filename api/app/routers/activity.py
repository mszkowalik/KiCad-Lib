"""Who did what: the whole audit log, with the tracker's rows (decision 0050).

Admin-only. The `row.*` rows copy values out of every table — orders, prices,
accounts — so reading this is reading everybody's work at once, and the role
model (decision 0045) puts "other people's" data behind the admin gate. The
human-scale feeds over the same table (`/api/changes`, the agent's
`get_audit_log`) leave the tracker's rows out and stay open.

Three kinds of row, told apart by `action` (see `services/tracking.py`):
`request` (one per write call), `row.*` (one per database row changed), and
everything else — the `event` the endpoint itself wrote.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import and_, func, not_, or_
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services.tracking import REQUEST_ACTION, ROW_ACTION_PREFIX
from .users import require_admin

router = APIRouter(prefix="/api/activity", tags=["activity"])

KINDS = ("request", "event", "row")


def _kind_of(action: str) -> str:
    if action == REQUEST_ACTION:
        return "request"
    if action.startswith(ROW_ACTION_PREFIX):
        return "row"
    return "event"


def _kind_filter(kind: str):
    if kind == "request":
        return M.AuditLog.action == REQUEST_ACTION
    if kind == "row":
        return M.AuditLog.action.startswith(ROW_ACTION_PREFIX)
    return and_(M.AuditLog.action != REQUEST_ACTION,
                not_(M.AuditLog.action.startswith(ROW_ACTION_PREFIX)))


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def _json(a: M.AuditLog, users: dict[int, M.User]) -> dict:
    u = users.get(a.user_id) if a.user_id else None
    return {
        "id": a.id, "ts": _iso(a.ts), "kind": _kind_of(a.action or ""),
        "actor": a.actor, "user_id": a.user_id,
        "username": u.username if u else "", "user_display": (u.display_name or u.username) if u else "",
        "action": a.action, "entity_type": a.entity_type, "entity_id": a.entity_id,
        "request_id": a.request_id, "details": a.details,
    }


def _users(db: Session, rows: list[M.AuditLog]) -> dict[int, M.User]:
    ids = {r.user_id for r in rows if r.user_id}
    if not ids:
        return {}
    return {u.id: u for u in db.query(M.User).filter(M.User.id.in_(ids)).all()}


@router.get("")
def list_activity(kind: str = "request,event", user_id: int | None = None, who: str = "", q: str = "",
                  request_id: str = "",
                  entity_type: str = "", entity_id: str = "", since: str = "", until: str = "",
                  before_id: int | None = None, limit: int = 100,
                  db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """The log, newest first.

    `kind` is a comma list of `request`, `event` and `row`. The default leaves
    `row` out: one invoice save writes a dozen of them, and they are what
    `GET /requests/{request_id}` is for. `before_id` pages — pass the
    `next_before_id` of the previous answer. `who` matches the actor, or the
    username or display name of the signed-in person behind the row; `q`
    matches the action, the table or kind of subject, its id, or the path.
    """
    wanted = [k for k in (p.strip() for p in kind.split(",")) if k in KINDS] or list(KINDS)
    limit = max(1, min(limit, 500))
    qry = db.query(M.AuditLog)
    if len(wanted) < len(KINDS):
        qry = qry.filter(or_(*[_kind_filter(k) for k in wanted]))
    if user_id is not None:
        qry = qry.filter(M.AuditLog.user_id == user_id)
    if request_id:
        qry = qry.filter(M.AuditLog.request_id == request_id)
    if entity_type:
        qry = qry.filter(M.AuditLog.entity_type == entity_type)
    if entity_id:
        qry = qry.filter(M.AuditLog.entity_id == entity_id)
    if who.strip():
        like = f"%{who.strip()}%"
        ids = [u.id for u in db.query(M.User.id).filter(
            or_(M.User.username.ilike(like), M.User.display_name.ilike(like))).all()]
        qry = qry.filter(or_(M.AuditLog.actor.ilike(like), M.AuditLog.user_id.in_(ids or [-1])))
    if q.strip():
        needle = f"%{q.strip()}%"
        qry = qry.filter(or_(M.AuditLog.action.ilike(needle), M.AuditLog.entity_type.ilike(needle),
                             M.AuditLog.entity_id.ilike(needle)))
    if since:
        qry = qry.filter(M.AuditLog.ts >= since)
    if until:
        qry = qry.filter(M.AuditLog.ts < until)
    if before_id is not None:
        qry = qry.filter(M.AuditLog.id < before_id)
    rows = qry.order_by(M.AuditLog.id.desc()).limit(limit).all()

    # How much each listed request did, so a row can say "6 rows changed".
    req_ids = [r.request_id for r in rows if r.action == REQUEST_ACTION and r.request_id]
    counts: dict[str, dict[str, int]] = {}
    if req_ids:
        for rid, action, n in (
            db.query(M.AuditLog.request_id, M.AuditLog.action, func.count())
            .filter(M.AuditLog.request_id.in_(req_ids), M.AuditLog.action != REQUEST_ACTION)
            .group_by(M.AuditLog.request_id, M.AuditLog.action).all()
        ):
            bucket = "rows" if action.startswith(ROW_ACTION_PREFIX) else "events"
            counts.setdefault(rid, {"rows": 0, "events": 0})[bucket] += n
    users = _users(db, rows)
    out = []
    for r in rows:
        item = _json(r, users)
        if r.action == REQUEST_ACTION:
            item["counts"] = counts.get(r.request_id or "", {"rows": 0, "events": 0})
        out.append(item)
    return {"rows": out, "next_before_id": rows[-1].id if len(rows) == limit else None}


@router.get("/requests/{request_id}")
def request_detail(request_id: str, db: Session = Depends(get_db), _admin=Depends(require_admin)):
    """Everything one request wrote, in the order it was written, and the
    undoable write batch it ran, if any (Production → Write log)."""
    rows = (db.query(M.AuditLog).filter(M.AuditLog.request_id == request_id)
            .order_by(M.AuditLog.id).all())
    batches = (db.query(M.WriteBatch).filter(M.WriteBatch.request_id == request_id)
               .order_by(M.WriteBatch.id).all())
    if not rows and not batches:
        raise HTTPException(404, "no record of that request")
    users = _users(db, rows)
    return {
        "rows": [_json(r, users) for r in rows],
        "write_batches": [{"id": b.id, "kind": b.kind, "source_ref": b.source_ref,
                           "reversed_at": _iso(b.reversed_at),
                           "reversed_by_batch_id": b.reversed_by_batch_id} for b in batches],
    }
