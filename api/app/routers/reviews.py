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
from ..services import validator
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
                                         "use 'flagged' with a note to record a found defect")
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


@router.get("/checklists/meta")
def checklist_meta():
    """What the checklist editor needs to be honest about `machine: true`.

    A machine item is answered by `services/validator.py` on every publish —
    but only for the keys that module implements. Marking any other key
    `machine` produces an item nobody ever answers, which pins the subject at
    "partial" for ever. The editor greys the flag out for unknown keys, and
    `_validate_items` refuses it outright.
    """
    return {"subject_kinds": list(_PARENT),
            "machine_keys": {k: list(v) for k, v in validator.MACHINE_KEYS.items()}}


@router.get("/checklists/resolve")
def resolve_checklist(kind: str, category_id: int | None = None,
                      db: Session = Depends(get_db)):
    """The merged list a subject of this kind (in this category) is measured
    against: the base checklist plus every category-scoped one on the category
    path, most specific winning a key collision. This is what the review card
    shows and what a check is scored against — the editor previews it so a
    category-scoped list can be seen in context rather than in isolation."""
    if kind not in _PARENT:
        raise HTTPException(422, "kind must be component, symbol or footprint")
    if category_id is not None and db.get(M.Category, category_id) is None:
        raise HTTPException(422, "category not found")
    resolved = checklists_svc.resolve(db, kind, category_id)
    # which checklist each item came from, so the preview can attribute them
    sources: dict[str, str] = {}
    base = db.query(M.Checklist).filter_by(subject_kind=kind, category_id=None).first()
    if base is not None:
        cur = next((v for v in base.versions if v.id == base.current_version_id), None)
        for item in (cur.items if cur else []) or []:
            sources[item["key"]] = base.name
    if category_id is not None:
        cat = db.get(M.Category, category_id)
        path_ids = []
        while cat is not None:
            path_ids.append(cat.id)
            cat = cat.parent
        scoped = (db.query(M.Checklist)
                  .filter(M.Checklist.subject_kind == kind,
                          M.Checklist.category_id.in_(path_ids)).all()) if path_ids else []
        for cl in sorted(scoped, key=lambda c: path_ids.index(c.category_id), reverse=True):
            cur = next((v for v in cl.versions if v.id == cl.current_version_id), None)
            for item in (cur.items if cur else []) or []:
                sources[item["key"]] = cl.name
    return {"kind": kind, "category_id": category_id,
            "items": [{**i, "from": sources.get(i["key"], "")} for i in resolved["items"]]}


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


@router.get("/checklists/{cl_id}/versions/{version_no}")
def get_checklist_version(cl_id: int, version_no: int, db: Session = Depends(get_db)):
    """One past version's items, so the editor can show what a list used to say
    and put it back (saving them republishes as a new version — the history is
    append-only, exactly like a skill)."""
    cl = db.get(M.Checklist, cl_id)
    if cl is None:
        raise HTTPException(404, "checklist not found")
    v = next((x for x in cl.versions if x.version_no == version_no), None)
    if v is None:
        raise HTTPException(404, "version not found")
    return {"id": cl.id, "name": cl.name, "version_no": v.version_no,
            "created_at": v.created_at.isoformat(), "created_by": v.created_by,
            "comment": v.comment, "items": v.items or []}


def _validate_items(items: list[dict], subject_kind: str) -> list[dict]:
    """Clean one checklist's items, and refuse the two shapes that cannot work.

    A duplicate key would silently drop an item (the resolver is keyed by key),
    and a `machine: true` flag on a key `services/validator.py` does not answer
    would create an item nobody can ever answer — the subject would sit at
    "partial" for ever with no way to clear it. Both are refused here rather
    than discovered months later on a part nobody can finish reviewing.
    """
    machine_keys = set(validator.MACHINE_KEYS.get(subject_kind, ()))
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
            if key not in machine_keys:
                raise HTTPException(422, {
                    "error": f"{key!r} is marked machine-checked, but the validator does not "
                             f"answer it — the item would stay unanswered for ever. "
                             f"Machine keys for a {subject_kind}: "
                             + ", ".join(sorted(machine_keys)),
                    "key": key})
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
    items = _validate_items(body.items, cl.subject_kind)
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
    # The session is `expire_on_commit=False` and the version row added above is
    # not appended to the already-loaded `cl.versions`, so re-reading without
    # this returns the checklist as it was BEFORE the save: version_no null,
    # zero items, the new row missing from the history. The save landed; only
    # the answer was wrong. Same trap as `services/repoint.py`.
    db.expire_all()
    return get_checklist(cl_id, db)


@router.post("/checklists")
def create_checklist(body: ChecklistCreateIn, request: Request, db: Session = Depends(get_db)):
    """Create a checklist. A new one is only ever CATEGORY-SCOPED, and only for
    components.

    `checklists.resolve` reads exactly one base list per kind (the first with
    `category_id IS NULL`) and merges category-scoped lists on top of it, so a
    second base list would be created, listed, edited — and never reach a single
    verification. Symbols and footprints carry no category at all, which leaves
    them one list each. Both cases are refused here and named as such, because
    the alternative is a checklist that silently does nothing.
    """
    if body.subject_kind not in _PARENT:
        raise HTTPException(422, "subject_kind must be component, symbol or footprint")
    if db.query(M.Checklist).filter_by(name=body.name.strip()).first():
        raise HTTPException(409, f"checklist {body.name!r} already exists")
    if body.subject_kind != "component":
        raise HTTPException(422, {
            "error": f"a {body.subject_kind} has no category, so it can only ever have one "
                     f"checklist — edit the base {body.subject_kind} checklist instead"})
    if body.category_id is None:
        raise HTTPException(422, {
            "error": "a new checklist must name a category. Only ONE base checklist per kind is "
                     "ever read, so a second one would never reach a verification — add your "
                     "items to the base component checklist, or scope them to a category"})
    if db.get(M.Category, body.category_id) is None:
        raise HTTPException(422, "category not found")
    twin = (db.query(M.Checklist)
            .filter_by(subject_kind=body.subject_kind, category_id=body.category_id).first())
    if twin is not None:
        raise HTTPException(409, {
            "error": f"{twin.name!r} already scopes this category — edit it rather than adding a "
                     "second list for the same one",
            "checklist_id": twin.id})
    items = _validate_items(body.items, body.subject_kind)
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
    db.expire_all()  # see the note in save_checklist
    return get_checklist(cl.id, db)


# ------------------------------------------------------------- agent worklist
class RequestsIn(BaseModel):
    """Subjects to queue for agent verification: [{kind, id}]."""

    items: list[dict]
    note: str | None = None


@router.post("/reviews/requests")
def create_review_requests(body: RequestsIn, request: Request, db: Session = Depends(get_db)):
    """Queue subjects for the agent. Idempotent per open request — re-queuing
    something already waiting is a no-op, not a duplicate. Nothing is gated:
    a request is a pointer the agent reads back with `get_review_worklist`."""
    actor = actor_of(request)
    open_now = {(r.subject_kind, r.subject_id)
                for r in db.query(M.ReviewRequest).filter_by(done_at=None)}
    added, skipped = 0, 0
    for it in body.items:
        kind = str(it.get("kind", ""))
        sid = it.get("id")
        if kind not in _PARENT or not isinstance(sid, int):
            raise HTTPException(422, f"each item needs kind (component|symbol|footprint) and id — got {it!r}")
        if _parent_or_404(db, kind, sid).current_version_id is None:
            skipped += 1  # nothing published to verify
            continue
        if (kind, sid) in open_now:
            skipped += 1
            continue
        db.add(M.ReviewRequest(subject_kind=kind, subject_id=sid,
                               note=(body.note or "").strip() or None, requested_by=actor))
        open_now.add((kind, sid))
        added += 1
    audit(db, "review.request", "review_request", 0,
          {"added": added, "skipped": skipped}, actor=actor)
    db.commit()
    return {"ok": True, "added": added, "already_queued_or_unpublished": skipped,
            "open_total": len(open_now)}


@router.get("/reviews/requests")
def list_review_requests(include_done: bool = False, db: Session = Depends(get_db)):
    q = db.query(M.ReviewRequest).order_by(M.ReviewRequest.id.desc())
    if not include_done:
        q = q.filter(M.ReviewRequest.done_at.is_(None))
    rows = q.limit(500).all()
    names: dict[tuple[str, int], str] = {}
    for kind, model in (("component", M.Component), ("symbol", M.Symbol),
                        ("footprint", M.Footprint)):
        ids = [r.subject_id for r in rows if r.subject_kind == kind]
        if ids:
            for pid, name in db.query(model.id, model.name).filter(model.id.in_(ids)):
                names[(kind, pid)] = name
    return [{"id": r.id, "kind": r.subject_kind, "subject_id": r.subject_id,
             "name": names.get((r.subject_kind, r.subject_id), "?"),
             "note": r.note, "requested_by": r.requested_by,
             "requested_at": r.requested_at.isoformat(),
             "done_at": r.done_at.isoformat() if r.done_at else None,
             "done_by": r.done_by}
            for r in rows]


@router.delete("/reviews/requests/{req_id}")
def withdraw_review_request(req_id: int, request: Request, db: Session = Depends(get_db)):
    r = db.get(M.ReviewRequest, req_id)
    if r is None:
        raise HTTPException(404, "request not found")
    if r.done_at is None:
        r.done_at = review_svc._utcnow()
        r.done_by = f"withdrawn by {actor_of(request)}"
        db.commit()
    return {"ok": True}


@router.post("/reviews/confirm-agent")
def confirm_agent_checks(request: Request, db: Session = Depends(get_db)):
    """One human gesture over every agent-checked subject.

    The tier system makes `checked (agent)` a real state but not the final
    one; confirming each part one page at a time makes trusting the agent more
    work than not using it. This writes the same one-click human confirmation
    the ReviewCard's "Mark checked" button writes, for every subject whose
    effective state is checked with agent provenance — nothing partial, failed
    or human-touched is touched.
    """
    actor = actor_of(request)
    confirmed: dict[str, list[str]] = {"component": [], "symbol": [], "footprint": []}
    for kind, model in (("component", M.Component), ("symbol", M.Symbol),
                        ("footprint", M.Footprint)):
        parents = db.query(model).filter(model.current_version_id.isnot(None)).all()
        states = _template_states(db, kind, parents) if kind != "component" else None
        if kind == "component":
            comp_states = review_svc.states_for_components(db, parents)
        for p in parents:
            if kind == "component":
                # the component's OWN record, not the aggregate — confirming the
                # part must not silently vouch for an unchecked footprint
                s = comp_states[p.id].get("parts", {}).get("component",
                                                           comp_states[p.id])
            else:
                s = states[p.id]
            if s["state"] == "checked" and s.get("provenance") == "agent":
                review_svc.record_check(db, kind, p, p.current_version_id,
                                        actor=actor, actor_type="human", items=None,
                                        note="Bulk confirmation of the agent's verification")
                confirmed[kind].append(p.name)
    total = sum(len(v) for v in confirmed.values())
    audit(db, "review.confirm_agent", "review_record", 0,
          {"confirmed": total}, actor=actor)
    db.commit()
    return {"ok": True, "confirmed": confirmed, "total": total}


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
@router.delete("/checklists/{cl_id}")
def delete_checklist(cl_id: int, request: Request, db: Session = Depends(get_db)):
    """Remove a category-scoped checklist.

    Refused for a BASE checklist (no category): it is what every subject of its
    kind is measured against, and a kind with no checklist reads as "nothing to
    answer". Empty its items instead if that is really the intent.

    Past verifications are NOT harmed by deleting a category checklist: every
    review record snapshots the resolved list it was measured against
    (`ReviewRecord.checklist_items`), so its state keeps comparing against what
    was in force when it was written. Records made before that column existed
    pin the BASE checklist version, which this endpoint never deletes — so
    there is nothing here to guard beyond the base rule above.
    """
    cl = db.get(M.Checklist, cl_id)
    if cl is None:
        raise HTTPException(404, "checklist not found")
    if cl.category_id is None:
        raise HTTPException(409, {
            "error": f"{cl.name!r} is the base checklist for every {cl.subject_kind} — "
                     "edit its items instead of deleting it"})
    name = cl.name
    for v in list(cl.versions):
        db.delete(v)
    db.delete(cl)
    audit(db, "checklist.delete", "checklist", cl_id, {"checklist": name},
          actor=actor_of(request))
    db.commit()
    return {"ok": True, "deleted": name}


@router.get("/reviews/queue")
def review_queue(snapshot_id: int | None = None, db: Session = Depends(get_db)):
    """The review worklist.

    ``snapshot_id`` scopes it to one project snapshot's BOM — the
    review-before-build case the run-creation warning points at. Components
    narrow to that BOM, and the template tabs narrow to the drawings those
    components pin, so "review this batch" is a finite list with an end.
    """
    comps = db.query(M.Component).options(
        selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties)
    ).all()

    scope_note = None
    if snapshot_id is not None:
        snap = db.get(M.ProjectSnapshot, snapshot_id)
        if snap is None:
            raise HTTPException(404, "snapshot not found")
        bom_ids = {cid for (cid,) in db.query(M.SnapshotBomLine.component_id)
                   .filter(M.SnapshotBomLine.snapshot_id == snapshot_id,
                           M.SnapshotBomLine.component_id.isnot(None)).distinct()}
        comps = [c for c in comps if c.id in bom_ids]
        proj = db.get(M.Project, snap.project_id)
        scope_note = {"snapshot_id": snapshot_id, "sha": snap.sha[:10],
                      "project": proj.name if proj else "?", "components": len(comps)}

    review_states = review_svc.states_for_components(db, comps)
    signoff_states = signoff.states_for(db, comps, detail=False)
    used = used_in_projects(db)

    # Which templates each live component pins — the leverage map. 18 failed
    # symbols made 159 components read "failed" (measured 2026-08-24): the
    # queue has to say which drawing unblocks how many parts, or the debt
    # looks 10x wider than it is.
    sym_users: dict[str, int] = {}
    fp_users: dict[int, int] = {}
    fp_parent_of = dict(db.query(M.FootprintVersion.id, M.FootprintVersion.footprint_id))
    for c in comps:
        cv = next((v for v in c.versions if v.id == c.current_version_id), None)
        if cv is None:
            continue
        if cv.base_component:
            sym_users[cv.base_component] = sym_users.get(cv.base_component, 0) + 1
        fp_id = fp_parent_of.get(cv.footprint_version_id) if cv.footprint_version_id else None
        if fp_id is not None:
            fp_users[fp_id] = fp_users.get(fp_id, 0) + 1

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
    if snapshot_id is not None:
        syms = [s for s in syms if sym_users.get(s.name)]
        fps = [f for f in fps if fp_users.get(f.id)]
    sym_states = _template_states(db, "symbol", syms)
    fp_states = _template_states(db, "footprint", fps)

    # open agent requests, so the queue can show what is already handed off
    requested = {(r.subject_kind, r.subject_id)
                 for r in db.query(M.ReviewRequest).filter_by(done_at=None)}

    def _template_rows(kind, parents, states, users):
        rows = []
        for p in parents:
            if p.current_version_id is None:
                continue
            s = states[p.id]
            n = users.get(p.name if kind == "symbol" else p.id, 0)
            rows.append({"id": p.id, "name": p.name, "kind": kind,
                         "review_state": s["state"], "provenance": s.get("provenance"),
                         "skipped": s["skipped"], "failed": s["failed"],
                         "unanswered": len(s["unanswered"]),
                         # live components pinning this drawing; on a non-checked
                         # row this IS the number of parts it is holding down
                         "used_by": n,
                         "agent_requested": (kind, p.id) in requested})
        return rows

    for row in comp_rows:
        row["agent_requested"] = ("component", row["id"]) in requested

    return {
        "components": comp_rows,
        "symbols": _template_rows("symbol", syms, sym_states, sym_users),
        "footprints": _template_rows("footprint", fps, fp_states, fp_users),
        "scope": scope_note,
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

    # Chronic skips and failing keys, counted over EFFECTIVE records only —
    # summing every historical record would count one part once per follow-up
    # and make the numbers drift from the queue. Grouping failures by KEY is
    # the work plan: "fp.model3d failing on 61 footprints" is one job, "218
    # failed parts" is a wall.
    skip_counts: dict[str, int] = {}
    skip_reasons: dict[str, int] = {}
    fail_keys: dict[str, dict[str, int]] = {"component": {}, "symbol": {}, "footprint": {}}
    for kind, model in (("component", M.Component), ("symbol", M.Symbol),
                        ("footprint", M.Footprint)):
        parents = {p.id: p for p in
                   db.query(model).filter(model.current_version_id.isnot(None))}
        by_parent: dict[int, list[M.ReviewRecord]] = {}
        for r in (db.query(M.ReviewRecord)
                  .filter(M.ReviewRecord.subject_kind == kind,
                          M.ReviewRecord.subject_id.in_(parents))
                  .order_by(M.ReviewRecord.id)):
            by_parent.setdefault(r.subject_id, []).append(r)
        for pid, parent in parents.items():
            rec = review_svc.effective_record(by_parent.get(pid, []),
                                              parent.current_version_id)
            if rec is None:
                continue
            for item in rec.items or []:
                key = item.get("key", "?")
                res = item.get("result")
                if res == "skipped":
                    skip_counts[key] = skip_counts.get(key, 0) + 1
                    reason = item.get("reason") or "unstated"
                    skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
                elif res in ("failed", "flagged"):
                    fail_keys[kind][key] = fail_keys[kind].get(key, 0) + 1
    top_skipped = sorted(skip_counts.items(), key=lambda kv: -kv[1])[:10]

    return {
        "components": {"total": len(comps), "review": review_counts,
                       "signoff": signoff_counts, "lifecycle": lifecycle_counts},
        "used_not_signed": sorted(used_not_signed),
        "used_deprecated": sorted(used_deprecated),
        "top_skipped_items": [{"key": k, "count": n} for k, n in top_skipped],
        "skip_reasons": [{"reason": k, "count": n}
                         for k, n in sorted(skip_reasons.items(), key=lambda kv: -kv[1])],
        "failing_keys": {k: [{"key": key, "count": n}
                             for key, n in sorted(v.items(), key=lambda kv: -kv[1])]
                         for k, v in fail_keys.items()},
        "flagged": flagged_worklist(db),
    }


def flagged_worklist(db: Session) -> list[dict]:
    """Every `flagged` item on a CURRENT version — the second-pass list.

    A flag records "verified and found wrong, deliberately not fixed yet"
    (user design 2026-08-23), so this is the answer to "what needs a
    correction pass". Flags on superseded versions are history, not work.
    """
    out: list[dict] = []
    for kind, model in (("component", M.Component), ("symbol", M.Symbol),
                        ("footprint", M.Footprint)):
        parents = db.query(model).filter(model.current_version_id.isnot(None)).all()
        by_parent: dict[int, list[M.ReviewRecord]] = {}
        ids = [p.id for p in parents]
        if not ids:
            continue
        q = (db.query(M.ReviewRecord)
             .filter(M.ReviewRecord.subject_kind == kind,
                     M.ReviewRecord.subject_id.in_(ids))
             .order_by(M.ReviewRecord.id))
        for r in q:
            by_parent.setdefault(r.subject_id, []).append(r)
        for p in parents:
            rec = review_svc.effective_record(by_parent.get(p.id, []), p.current_version_id)
            if rec is None:
                continue
            for item in rec.items or []:
                if item.get("result") == "flagged":
                    out.append({"kind": kind, "id": p.id, "name": p.name,
                                "key": item.get("key"), "note": item.get("note"),
                                "actor": item.get("actor"),
                                "actor_type": item.get("actor_type"),
                                "at": item.get("at")})
    out.sort(key=lambda r: (r["kind"], r["name"], r["key"] or ""))
    return out


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
