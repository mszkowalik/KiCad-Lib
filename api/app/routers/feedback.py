"""Bug reports and feature requests about the platform itself.

Anyone signed in files a report and reads every report, in the web app
(User menu → Feedback) or through their agent (`report_feedback`,
`list_feedback`). An administrator sets the status and writes the answer.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import tracking
from .users import require_admin
from .util import acting_name, audit, col_cap

router = APIRouter(prefix="/api/feedback", tags=["feedback"])

KINDS = ("bug", "feature")
STATUSES = ("open", "planned", "done", "declined")


def report_json(r: M.FeedbackReport) -> dict:
    return {
        "id": r.id, "kind": r.kind, "title": r.title, "body": r.body, "page": r.page,
        "status": r.status, "response": r.response, "created_by": r.created_by, "client": r.client,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "updated_at": r.updated_at.isoformat() if r.updated_at else None,
    }


@router.get("", openapi_extra={"x-agent-tool": "list_feedback"})
def list_feedback(status: str = "", kind: str = "", db: Session = Depends(get_db)):
    """Every bug report and feature request about the Henry platform, newest
    first, with the administrator's status (open, planned, done, declined) and
    answer. Filter with `status` and `kind` (bug or feature). Read this before
    filing, so the same report is not filed twice."""
    q = db.query(M.FeedbackReport)
    if status:
        q = q.filter(M.FeedbackReport.status == status)
    if kind:
        q = q.filter(M.FeedbackReport.kind == kind)
    return [report_json(r) for r in q.order_by(M.FeedbackReport.id.desc()).all()]


class ReportIn(BaseModel):
    kind: Literal["bug", "feature"]
    title: str = Field(min_length=3, max_length=col_cap(M.FeedbackReport, "title"))
    body: str = Field(default="", max_length=20000)
    page: str = Field(default="", max_length=col_cap(M.FeedbackReport, "page"))


@router.post("", openapi_extra={"x-agent-tool": "report_feedback"})
def report_feedback(body: ReportIn, db: Session = Depends(get_db)):
    """File a bug report (`kind: bug`) or a feature request (`kind: feature`)
    about the Henry platform or its agent tools, under the signed-in user's
    name. Say what you did, what happened and what you expected; for a tool,
    put its name in `page`. Call list_feedback first to avoid a duplicate.
    Only file what the user asked for or agreed to."""
    ctx = tracking.current()
    r = M.FeedbackReport(
        kind=body.kind, title=body.title.strip(), body=body.body.strip(), page=body.page.strip(),
        created_by=acting_name(), user_id=getattr(ctx, "user_id", None),
        client=(getattr(ctx, "client", "") or "")[:20],
    )
    db.add(r)
    db.flush()
    audit(db, "feedback.create", "feedback", r.id, {"kind": r.kind, "title": r.title})
    db.commit()
    return report_json(r)


class ReportPatch(BaseModel):
    status: Literal["open", "planned", "done", "declined"] | None = None
    response: str | None = Field(default=None, max_length=20000)


@router.patch("/{report_id}")
def triage_feedback(report_id: int, body: ReportPatch, db: Session = Depends(get_db),
                    admin: M.User = Depends(require_admin)):
    """Set a report's status and the answer. Administrators only."""
    r = db.get(M.FeedbackReport, report_id)
    if r is None:
        raise HTTPException(404, "no such report")
    changed = {}
    if body.status is not None and body.status != r.status:
        changed["status"] = f"{r.status} -> {body.status}"
        r.status = body.status
    if body.response is not None and body.response.strip() != r.response:
        r.response = body.response.strip()
        changed["response"] = "(edited)"
    if changed:
        r.updated_at = M.utcnow()
        audit(db, "feedback.triage", "feedback", r.id, changed)
        db.commit()
    return report_json(r)
