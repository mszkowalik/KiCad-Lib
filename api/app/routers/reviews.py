"""Review-axis endpoints: verification records, checklists, lifecycle,
the review queue, and the per-project design review.

The meaning of a record and every derivation lives in `services/review.py`;
this router resolves subjects, names actors, audits and commits. Like
sign-offs, nothing here blocks anything — the one warning gate (production-run
creation) lives in `routers/production_runs.py` and only ever asks for an
explicit confirmation.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import checklists as checklists_svc
from ..services import review as review_svc
from ..services import signoff
from ..services.mirror import HIDDEN_LIFECYCLE, top_level_of, update_mirror_symbols
from .util import actor_of, audit, category_path

router = APIRouter(prefix="/api", tags=["reviews"])

LIFECYCLE_STATES = ("in_design", "released", "deprecated", "obsolete")

_PARENT = {"component": M.Component, "symbol": M.Symbol, "footprint": M.Footprint}


class CheckIn(BaseModel):
    """A human verification. `items=None` + `one_click=True` is the one-click
    confirmation, recorded without an item breakdown."""

    items: list[dict] | None = None
    note: str | None = None
    one_click: bool = False


class RevokeIn(BaseModel):
    reason: str


class LifecycleIn(BaseModel):
    state: str
    note: str | None = None


class ChecklistSaveIn(BaseModel):
    items: list[dict]
    comment: str | None = None
    description: str | None = None


class ChecklistCreateIn(BaseModel):
    name: str
    subject_kind: str
    category_id: int | None = None
    description: str = ""
    items: list[dict]


class CompleteReviewIn(BaseModel):
    sha: str
    note: str | None = None


def _parent_or_404(db: Session, kind: str, parent_id: int):
    model = _PARENT.get(kind)
    if model is None:
        raise HTTPException(404, "kind must be component, symbol or footprint")
    parent = db.get(model, parent_id)
    if parent is None:
        raise HTTPException(404, f"{kind} not found")
    return parent


# ------------------------------------------------------------- subject detail
def _detail(db: Session, kind: str, parent) -> dict:
    version_id = parent.current_version_id
    rows = review_svc.records_for(db, kind, parent.id)
    record = review_svc.effective_record(rows, version_id)
    cat_id = review_svc._category_of(db, kind, parent)
    resolved = checklists_svc.resolve(db, kind, cat_id)
    answered = {i["key"]: i for i in (record.items or [])} if record else {}

    items = []
    for item in resolved["items"]:
        merged = dict(item)
        prev = answered.get(item["key"])
        if prev:
            merged["answered"] = {k: prev.get(k) for k in
                                  ("result", "note", "actor", "actor_type", "at")}
        items.append(merged)
    extras = [i for k, i in answered.items()
              if k not in {it["key"] for it in resolved["items"]}]

    state = review_svc.state_from_record(
        record, resolved["items"] if record and record.items is not None else None)
    return {
        "kind": kind,
        "id": parent.id,
        "name": parent.name,
        "version_id": version_id,
        "checklist_version_id": resolved["checklist_version_id"],
        **state,
        "state_detail": state,
        "items": items,
        "extra_items": extras,
        "record": review_svc.record_json(record) if record else None,
        "history": [review_svc.record_json(r) for r in reversed(rows)],
    }


@router.get("/reviews/{kind}/{parent_id}")
def review_detail(kind: str, parent_id: int, db: Session = Depends(get_db)):
    parent = _parent_or_404(db, kind, parent_id)
    return _detail(db, kind, parent)


@router.post("/reviews/{kind}/{parent_id}/check")
def record_check(kind: str, parent_id: int, body: CheckIn, request: Request,
                 db: Session = Depends(get_db)):
    parent = _parent_or_404(db, kind, parent_id)
    if parent.current_version_id is None:
        raise HTTPException(409, f"this {kind} has no published version to verify")
    if body.items is None and not body.one_click:
        raise HTTPException(422, "pass items, or one_click=true for a confirmation without them")
    if body.items is not None:
        for i in body.items:
            if str(i.get("result", "")) == "failed":
                raise HTTPException(422, "result 'failed' is reserved for machine checks — "
                                         "fix the data or use 'skipped' with a note")
    actor = actor_of(request)
    res = review_svc.record_check(db, kind, parent, parent.current_version_id,
                                  actor=actor, actor_type="human",
                                  items=body.items, note=body.note)
    db.commit()
    return {**_detail(db, kind, parent), "blocked_items": res["blocked"]}


@router.post("/reviews/{kind}/{parent_id}/revoke")
def revoke_check(kind: str, parent_id: int, body: RevokeIn, request: Request,
                 db: Session = Depends(get_db)):
    parent = _parent_or_404(db, kind, parent_id)
    reason = (body.reason or "").strip()
    if not reason:
        raise HTTPException(422, "say why the verification is being taken back")
    rows = review_svc.records_for(db, kind, parent.id)
    record = review_svc.effective_record(rows, parent.current_version_id)
    if record is None:
        raise HTTPException(404, "no live verification record to revoke")
    actor = actor_of(request)
    review_svc.revoke(db, record, actor, reason)
    audit(db, "review.revoke", f"{kind}_version", record.subject_version_id,
          {"subject": parent.name, "reason": reason, "record_id": record.id}, actor=actor)
    db.commit()
    return _detail(db, kind, parent)


# ------------------------------------------------------------------ lifecycle
@router.patch("/components/{comp_id}/lifecycle")
def set_lifecycle(comp_id: int, body: LifecycleIn, request: Request,
                  db: Session = Depends(get_db)):
    comp = db.get(M.Component, comp_id)
    if comp is None:
        raise HTTPException(404, "component not found")
    state = (body.state or "").strip()
    if state not in LIFECYCLE_STATES:
        raise HTTPException(422, f"state must be one of {', '.join(LIFECYCLE_STATES)}")
    old = comp.lifecycle_state
    if state == old:
        return {"component_id": comp.id, "lifecycle_state": old, "changed": False}
    actor = actor_of(request)
    comp.lifecycle_state = state
    audit(db, "lifecycle.set", "component", comp.id,
          {"component": comp.name, "from": old, "to": state,
           "note": (body.note or "").strip() or None}, actor=actor)
    db.commit()

    # Visibility to KiCad may have flipped — rebuild the component's library.
    mirror_warnings: list[str] = []
    if comp.in_library and ((old in HIDDEN_LIFECYCLE) != (state in HIDDEN_LIFECYCLE)):
        cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
        if cv is not None:
            db.expire_all()
            mirror = update_mirror_symbols(db, settings, {top_level_of(cv.category).name})
            mirror_warnings = mirror["warnings"]
    return {"component_id": comp.id, "lifecycle_state": state, "changed": True,
            "hidden_from_kicad": state in HIDDEN_LIFECYCLE,
            "mirror_warnings": mirror_warnings}


# ----------------------------------------------------------------- checklists
@router.get("/checklists")
def list_checklists(db: Session = Depends(get_db)):
    out = []
    for cl in db.query(M.Checklist).order_by(M.Checklist.subject_kind, M.Checklist.name).all():
        cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
        out.append({
            "id": cl.id, "name": cl.name, "subject_kind": cl.subject_kind,
            "category_id": cl.category_id,
            "category_path": category_path(db.get(M.Category, cl.category_id))
            if cl.category_id else None,
            "description": cl.description,
            "version_no": cv.version_no if cv else None,
            "item_count": len(cv.items or []) if cv else 0,
        })
    return out


@router.get("/checklists/{cl_id}")
def get_checklist(cl_id: int, db: Session = Depends(get_db)):
    cl = db.get(M.Checklist, cl_id)
    if cl is None:
        raise HTTPException(404, "checklist not found")
    cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
    return {
        "id": cl.id, "name": cl.name, "subject_kind": cl.subject_kind,
        "category_id": cl.category_id, "description": cl.description,
        "version_no": cv.version_no if cv else None,
        "items": cv.items if cv else [],
        "history": [{"version_no": v.version_no, "created_at": v.created_at.isoformat(),
                     "created_by": v.created_by, "comment": v.comment,
                     "item_count": len(v.items or [])}
                    for v in reversed(cl.versions)],
    }


def _validate_items(items: list[dict]) -> list[dict]:
    clean = []
    seen: set[str] = set()
    for i in items:
        key = str(i.get("key", "")).strip()
        text = str(i.get("text", "")).strip()
        if not key or not text:
            raise HTTPException(422, "every item needs a key and a text")
        if key in seen:
            raise HTTPException(422, f"duplicate item key {key!r}")
        seen.add(key)
        item = {"key": key, "text": text}
        if str(i.get("hint", "")).strip():
            item["hint"] = str(i["hint"]).strip()
        if i.get("machine"):
            item["machine"] = True
        clean.append(item)
    return clean


@router.put("/checklists/{cl_id}")
def save_checklist(cl_id: int, body: ChecklistSaveIn, request: Request,
                   db: Session = Depends(get_db)):
    """Publish a new checklist version. A human save publishes directly —
    same rationale as the component in-place save (the user saving IS the
    approval); the agent has no checklist write tool."""
    cl = db.get(M.Checklist, cl_id)
    if cl is None:
        raise HTTPException(404, "checklist not found")
    items = _validate_items(body.items)
    actor = actor_of(request)
    new_no = max((v.version_no for v in cl.versions), default=0) + 1
    cv = M.ChecklistVersion(checklist_id=cl.id, version_no=new_no, items=items,
                            status="published", created_by=actor,
                            comment=(body.comment or "").strip() or None)
    db.add(cv)
    db.flush()
    cl.current_version_id = cv.id
    if body.description is not None:
        cl.description = body.description.strip()
    audit(db, "checklist.publish", "checklist", cl.id,
          {"checklist": cl.name, "version_no": new_no, "items": len(items)}, actor=actor)
    db.commit()
    return get_checklist(cl_id, db)


@router.post("/checklists")
def create_checklist(body: ChecklistCreateIn, request: Request, db: Session = Depends(get_db)):
    if body.subject_kind not in _PARENT:
        raise HTTPException(422, "subject_kind must be component, symbol or footprint")
    if db.query(M.Checklist).filter_by(name=body.name.strip()).first():
        raise HTTPException(409, f"checklist {body.name!r} already exists")
    if body.category_id is not None and db.get(M.Category, body.category_id) is None:
        raise HTTPException(422, "category not found")
    items = _validate_items(body.items)
    actor = actor_of(request)
    cl = M.Checklist(name=body.name.strip(), subject_kind=body.subject_kind,
                     category_id=body.category_id, description=body.description.strip())
    db.add(cl)
    db.flush()
    cv = M.ChecklistVersion(checklist_id=cl.id, version_no=1, items=items,
                            status="published", created_by=actor, comment="Created")
    db.add(cv)
    db.flush()
    cl.current_version_id = cv.id
    audit(db, "checklist.create", "checklist", cl.id,
          {"checklist": cl.name, "subject_kind": cl.subject_kind}, actor=actor)
    db.commit()
    return get_checklist(cl.id, db)


# ---------------------------------------------------------------- used-in map
def used_in_projects(db: Session) -> dict[int, list[str]]:
    """component_id -> project names whose LATEST ready snapshot uses it."""
    latest: dict[int, M.ProjectSnapshot] = {}
    for snap in (db.query(M.ProjectSnapshot).filter_by(status="ready")
                 .order_by(M.ProjectSnapshot.created_at)):
        latest[snap.project_id] = snap  # later rows overwrite: newest wins
    if not latest:
        return {}
    names = {p.id: p.name for p in db.query(M.Project).all()}
    out: dict[int, set[str]] = {}
    snap_ids = {s.id: s.project_id for s in latest.values()}
    rows = (
        db.query(M.SnapshotBomLine.snapshot_id, M.SnapshotBomLine.component_id)
        .filter(M.SnapshotBomLine.snapshot_id.in_(list(snap_ids)),
                M.SnapshotBomLine.component_id.isnot(None))
        .distinct()
        .all()
    )
    for snap_id, comp_id in rows:
        pname = names.get(snap_ids[snap_id])
        if pname:
            out.setdefault(comp_id, set()).add(pname)
    return {k: sorted(v) for k, v in out.items()}


def _template_states(db: Session, kind: str, parents: list) -> dict[int, dict]:
    """Bulk `version_state` for symbols/footprints (one records query)."""
    ids = [p.id for p in parents]
    by_parent: dict[int, list[M.ReviewRecord]] = {i: [] for i in ids}
    if ids:
        q = (db.query(M.ReviewRecord)
             .filter(M.ReviewRecord.subject_kind == kind,
                     M.ReviewRecord.subject_id.in_(ids))
             .order_by(M.ReviewRecord.id))
        for r in q:
            by_parent.setdefault(r.subject_id, []).append(r)
    out = {}
    for p in parents:
        rec = review_svc.effective_record(by_parent.get(p.id, []), p.current_version_id)
        out[p.id] = review_svc.state_from_record(rec, review_svc._checklist_items_of(db, rec))
    return out


# ---------------------------------------------------------------- review queue
@router.get("/reviews/queue")
def review_queue(db: Session = Depends(get_db)):
    comps = db.query(M.Component).options(
        selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties)
    ).all()
    review_states = review_svc.states_for_components(db, comps)
    signoff_states = signoff.states_for(db, comps, detail=False)
    used = used_in_projects(db)

    comp_rows = []
    for c in comps:
        cv = next((v for v in c.versions if v.id == c.current_version_id), None)
        rs = review_states[c.id]
        comp_rows.append({
            "id": c.id, "name": c.name,
            "version_no": cv.version_no if cv else None,
            "category_path": category_path(cv.category) if cv else "",
            "review_state": rs["state"],
            "provenance": rs.get("provenance"),
            "blockers": rs.get("blockers", []),
            "signoff_state": signoff_states[c.id]["state"],
            "lifecycle": c.lifecycle_state,
            "used_in": used.get(c.id, []),
        })

    syms = db.query(M.Symbol).order_by(M.Symbol.name).all()
    fps = db.query(M.Footprint).order_by(M.Footprint.name).all()
    sym_states = _template_states(db, "symbol", syms)
    fp_states = _template_states(db, "footprint", fps)

    def _template_rows(kind, parents, states):
        rows = []
        for p in parents:
            if p.current_version_id is None:
                continue
            s = states[p.id]
            rows.append({"id": p.id, "name": p.name, "kind": kind,
                         "review_state": s["state"], "provenance": s.get("provenance"),
                         "skipped": s["skipped"], "failed": s["failed"],
                         "unanswered": len(s["unanswered"])})
        return rows

    # drafts still pending in the old queue (skills + any leftovers)
    draft_counts = {
        "components": db.query(M.ComponentVersion).filter_by(status="draft").count(),
        "skills": db.query(M.SkillVersion).filter_by(status="draft").count(),
        "symbols": db.query(M.SymbolVersion).filter_by(status="draft").count(),
        "footprints": db.query(M.FootprintVersion).filter_by(status="draft").count(),
    }

    return {
        "components": comp_rows,
        "symbols": _template_rows("symbol", syms, sym_states),
        "footprints": _template_rows("footprint", fps, fp_states),
        "drafts": draft_counts,
    }


@router.get("/reviews/health")
def review_health(db: Session = Depends(get_db)):
    """The library-health numbers: state counts, chronic skips, risky usage."""
    comps = db.query(M.Component).options(
        selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties)
    ).all()
    review_states = review_svc.states_for_components(db, comps)
    signoff_states = signoff.states_for(db, comps, detail=False)
    used = used_in_projects(db)

    review_counts: dict[str, int] = {}
    lifecycle_counts: dict[str, int] = {}
    signoff_counts: dict[str, int] = {}
    used_not_signed: list[str] = []
    used_deprecated: list[str] = []
    for c in comps:
        review_counts[review_states[c.id]["state"]] = \
            review_counts.get(review_states[c.id]["state"], 0) + 1
        lifecycle_counts[c.lifecycle_state] = lifecycle_counts.get(c.lifecycle_state, 0) + 1
        st = signoff_states[c.id]["state"]
        signoff_counts[st] = signoff_counts.get(st, 0) + 1
        if used.get(c.id):
            if st != "signed":
                used_not_signed.append(c.name)
            if c.lifecycle_state in HIDDEN_LIFECYCLE:
                used_deprecated.append(c.name)

    # Chronic skips: which checklist items are most often unverifiable.
    skip_counts: dict[str, int] = {}
    for r in (db.query(M.ReviewRecord)
              .filter(M.ReviewRecord.revoked_at.is_(None))
              .order_by(M.ReviewRecord.id)):
        for item in r.items or []:
            if item.get("result") == "skipped":
                skip_counts[item.get("key", "?")] = skip_counts.get(item.get("key", "?"), 0) + 1
    top_skipped = sorted(skip_counts.items(), key=lambda kv: -kv[1])[:10]

    return {
        "components": {"total": len(comps), "review": review_counts,
                       "signoff": signoff_counts, "lifecycle": lifecycle_counts},
        "used_not_signed": sorted(used_not_signed),
        "used_deprecated": sorted(used_deprecated),
        "top_skipped_items": [{"key": k, "count": n} for k, n in top_skipped],
    }


# ------------------------------------------------------- project design review
def snapshot_review_rows(db: Session, snap: M.ProjectSnapshot) -> list[dict]:
    """One row per BOM-matched component of a snapshot, with all three states."""
    lines = (db.query(M.SnapshotBomLine)
             .filter_by(snapshot_id=snap.id)
             .order_by(M.SnapshotBomLine.board, M.SnapshotBomLine.position).all())
    comp_ids = sorted({ln.component_id for ln in lines if ln.component_id})
    comps = (db.query(M.Component)
             .options(selectinload(M.Component.versions)
                      .selectinload(M.ComponentVersion.properties))
             .filter(M.Component.id.in_(comp_ids)).all()) if comp_ids else []
    by_id = {c.id: c for c in comps}
    review_states = review_svc.states_for_components(db, comps)
    signoff_states = signoff.states_for(db, comps, detail=False)

    rows = []
    seen: set[tuple] = set()
    for ln in lines:
        if ln.dnp or ln.exclude_from_bom:
            continue
        key = (ln.board, ln.component_id, ln.value, ln.footprint)
        if key in seen:
            continue
        seen.add(key)
        comp = by_id.get(ln.component_id) if ln.component_id else None
        cv = None
        if comp is not None:
            cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
        rows.append({
            "board": ln.board,
            "refs": ln.refs, "qty": ln.qty, "value": ln.value,
            "footprint": ln.footprint, "lcsc": ln.lcsc, "mpn": ln.mpn,
            "lib_version": ln.lib_version,
            "component_id": comp.id if comp else None,
            "component_name": comp.name if comp else None,
            "current_version_no": cv.version_no if cv else None,
            "review_state": review_states[comp.id]["state"] if comp else None,
            "review_blockers": review_states[comp.id].get("blockers", []) if comp else [],
            "signoff_state": signoff_states[comp.id]["state"] if comp else None,
            "lifecycle": comp.lifecycle_state if comp else None,
            "matched": comp is not None,
        })
    return rows


def snapshot_review_issues(db: Session, snap: M.ProjectSnapshot) -> dict:
    """What stands between this snapshot and a clean production run.

    Used by the run-creation warning gate AND the project review view, so the
    two can never disagree about what is wrong.
    """
    rows = snapshot_review_rows(db, snap)
    unsigned = [r for r in rows if r["matched"] and r["signoff_state"] != "signed"]
    unreviewed = [r for r in rows if r["matched"] and r["review_state"] in
                  ("unreviewed", "failed")]
    deprecated = [r for r in rows if r["matched"] and r["lifecycle"] in HIDDEN_LIFECYCLE]
    unmatched = [r for r in rows if not r["matched"]]

    last = (db.query(M.SnapshotReview).filter_by(snapshot_id=snap.id)
            .order_by(M.SnapshotReview.id.desc()).first())
    changed_since = []
    if last is not None and last.summary:
        then = {c["component_id"]: c for c in last.summary.get("components", [])}
        for r in rows:
            cid = r["component_id"]
            if cid is None:
                continue
            prev = then.get(cid)
            if prev is None or prev.get("version_no") != r["current_version_no"]:
                changed_since.append(r["component_name"])

    return {
        "rows": rows,
        "unsigned": sorted({r["component_name"] for r in unsigned}),
        "unreviewed": sorted({r["component_name"] for r in unreviewed}),
        "deprecated": sorted({r["component_name"] for r in deprecated}),
        "unmatched_lines": len(unmatched),
        "reviewed": last is not None,
        "last_review": {
            "id": last.id, "reviewed_by": last.reviewed_by,
            "reviewed_at": last.reviewed_at.isoformat(), "note": last.note,
            "sha": last.sha,
        } if last else None,
        "changed_since_review": sorted(set(changed_since)),
        "clean": not unsigned and not unreviewed and not deprecated,
    }


def _snapshot_or_404(db: Session, project_id: int, sha: str | None) -> M.ProjectSnapshot:
    q = db.query(M.ProjectSnapshot).filter_by(project_id=project_id, status="ready")
    snap = q.filter_by(sha=sha).first() if sha else \
        q.order_by(M.ProjectSnapshot.created_at.desc()).first()
    if snap is None:
        raise HTTPException(404, "no ready snapshot" + (f" for {sha}" if sha else ""))
    return snap


@router.get("/projects/{project_id}/review")
def project_review(project_id: int, sha: str | None = None, db: Session = Depends(get_db)):
    project = db.get(M.Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    snap = _snapshot_or_404(db, project_id, sha)
    issues = snapshot_review_issues(db, snap)
    reviews = (db.query(M.SnapshotReview).filter_by(project_id=project_id)
               .order_by(M.SnapshotReview.id.desc()).limit(20).all())
    return {
        "project_id": project_id,
        "project_name": project.name,
        "sha": snap.sha,
        "ref_name": snap.ref_name,
        "snapshot_id": snap.id,
        **issues,
        "past_reviews": [{
            "id": r.id, "sha": r.sha, "reviewed_by": r.reviewed_by,
            "reviewed_at": r.reviewed_at.isoformat(), "note": r.note,
            "summary_counts": (r.summary or {}).get("counts"),
        } for r in reviews],
    }


@router.post("/projects/{project_id}/review/complete")
def complete_review(project_id: int, body: CompleteReviewIn, request: Request,
                    db: Session = Depends(get_db)):
    """Record "I finished the design review of this snapshot". Deliberately
    allowed on a non-clean snapshot — the record stores what the states were,
    and the production-run warning still names anything left open."""
    project = db.get(M.Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    snap = _snapshot_or_404(db, project_id, body.sha)
    issues = snapshot_review_issues(db, snap)
    actor = actor_of(request)
    counts = {
        "components": sum(1 for r in issues["rows"] if r["matched"]),
        "unsigned": len(issues["unsigned"]),
        "unreviewed": len(issues["unreviewed"]),
        "deprecated": len(issues["deprecated"]),
    }
    row = M.SnapshotReview(
        project_id=project_id, snapshot_id=snap.id, sha=snap.sha,
        reviewed_by=actor, note=(body.note or "").strip() or None,
        summary={
            "counts": counts,
            "components": [{
                "component_id": r["component_id"],
                "version_no": r["current_version_no"],
                "review_state": r["review_state"],
                "signoff_state": r["signoff_state"],
            } for r in issues["rows"] if r["matched"]],
        },
    )
    db.add(row)
    db.flush()
    audit(db, "review.snapshot_complete", "project_snapshot", snap.id,
          {"project": project.name, "sha": snap.sha, **counts}, actor=actor)
    db.commit()
    return project_review(project_id, snap.sha, db)
