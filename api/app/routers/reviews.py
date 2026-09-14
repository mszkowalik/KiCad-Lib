"""Review-axis endpoints: verification records, checklists, lifecycle,
the review queue, and the per-project design review.

The meaning of a record and every derivation lives in `services/review.py`;
this router resolves subjects, names actors, audits and commits. Like
sign-offs, nothing here blocks anything — the one warning gate (production-run
creation) lives in `routers/production_runs.py` and only ever asks for an
explicit confirmation.
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import checklists as checklists_svc
from ..services import conformance as conformance_svc
from ..services import exceptions as exceptions_svc
from ..services import review as review_svc
from ..services import signoff
from ..services import validator
from ..services.mirror import HIDDEN_LIFECYCLE, top_level_of, update_mirror_symbols
from .util import (actor_of, audit, category_and_descendant_ids, category_path,
                   components_with_current)

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
def _facts_of(state: dict) -> dict:
    """The three facts a list row prints beside its one-word state.

    `conforms` is what the code can see, `judged`/`judged_of` is what a person
    has confirmed, and `excused` is what somebody decided is not the question.
    `conforms: None` means "not evaluated" and must never read as "conforms".
    """
    return {
        "conforms": state.get("conforms"),
        "judged": state.get("answered", 0),
        "judged_of": state.get("total", 0),
        "excused": state.get("excused", 0),
        "warnings": state.get("warnings", 0),
    }


def _detail(db: Session, kind: str, parent) -> dict:
    version_id = parent.current_version_id
    rows = review_svc.records_for(db, kind, parent.id)
    record = review_svc.effective_record(rows, version_id)
    cat_id = review_svc._category_of(db, kind, parent)
    facts = checklists_svc.subject_facts(db, kind, parent, version_id)
    resolved = checklists_svc.resolve(db, kind, cat_id, facts)
    # The STATE comes from the effective record; the per-item answers may have
    # to come from an earlier one. A one-click "Mark checked" is stored with no
    # item breakdown by design, and reading the answers off it alone blanked the
    # card — see `itemised_record` for why the two must stay separate.
    items_record = (
        record if (record is not None and record.items is not None)
        else review_svc.itemised_record(rows, version_id)
    )
    answered = {i["key"]: i for i in (items_record.items or [])} if items_record else {}
    # True when the answers on show were recorded BEFORE the record that set the
    # state. The card says so rather than crediting them to whoever confirmed.
    items_carried = (
        items_record is not None and record is not None and items_record.id != record.id
    )

    # Conformance is computed on read; judgment answers come from the record.
    # The two are merged for DISPLAY only — nothing here writes anything.
    version = next((v for v in parent.versions if v.id == version_id), None)
    conf_items, excused_items = ((([], [])) if version is None
                                else conformance_svc.get(db, kind, parent, version))
    conf = {i["key"]: i for i in conf_items}
    # Judgment items a standing exception closes. Computed, never recorded —
    # see `conformance.evaluate`. They overlay the record's own answer the same
    # way an exception overlays a machine finding, and what they replaced rides
    # along in `superseded`.
    excused = {i["key"]: i for i in excused_items}

    items = []
    for item in resolved["items"]:
        merged = dict(item)
        prev = answered.get(item["key"]) if not item.get("machine") else None
        machine = conf.get(item["key"])
        if machine is not None:
            merged["answered"] = {
                "result": machine["result"], "note": machine.get("note"),
                "actor": "validator", "actor_type": "machine",
                "at": None, "severity": machine.get("severity"),
                "reason": machine.get("reason"),
                "exception_id": machine.get("exception_id"),
                "superseded": machine.get("superseded"),
            }
        elif prev:
            # `superseded` rides along: it is what the current answer replaced,
            # and dropping it here is what made accepting a flag look like the
            # flag had never existed.
            # A FIXED key list here is exactly what hid `superseded` the first
            # time (review-axis.md). `severity` is the second thing it would
            # have hidden: without it the card cannot tell a warning-level
            # failure from a defect. Add the key when you add the field.
            merged["answered"] = {k: prev.get(k) for k in
                                  ("result", "note", "actor", "actor_type", "at",
                                   "severity", "reason", "exception_id", "superseded")}
        exc = excused.get(item["key"])
        if exc is not None:
            was = merged.get("answered")
            merged["answered"] = {k: v for k, v in exc.items()
                                  if k not in ("key", "variant", "text")}
            keep = review_svc._notable(was, (was or {}).get("superseded"))
            if keep is not None:
                merged["answered"]["superseded"] = keep
        items.append(merged)
    # A switched-off key is not an extra item somebody has to look at — the
    # owner decided it does not apply here. Its stored answer lives until the
    # next record drops it (`review.record_check`), so hide it from the card
    # rather than showing a finding nobody is expected to act on.
    switched_off = {i["key"] for i in resolved["disabled"]}
    extras = [i for k, i in answered.items()
              if k not in {it["key"] for it in resolved["items"]}
              and k not in switched_off]

    state = review_svc.state_from_record(
        record, resolved["items"], list(conf.values()), excused_items)
    return {
        "kind": kind,
        "id": parent.id,
        "name": parent.name,
        "version_id": version_id,
        "checklist_version_id": resolved["checklist_version_id"],
        **state,
        "state_detail": state,
        "items": items,
        "items_carried": items_carried,
        "extra_items": extras,
        "switched_off": [{"key": i["key"], "text": i.get("text", ""),
                          "machine": bool(i.get("machine"))}
                         for i in resolved["disabled"]],
        # Standing decisions on this subject. Reported even when stale, with the
        # reason — an exception that has quietly stopped applying is exactly
        # what somebody needs to see.
        "exceptions": [exceptions_svc.json_of(e, facts)
                       for e in exceptions_svc.rows_for(db, kind, parent.id)
                       if e.revoked_at is None],
        # Not switched off — not ABOUT parts like this one. A different
        # statement, and the card must not print one where it means the other.
        "inapplicable": [{"key": i["key"], "text": i.get("text", ""),
                          "when": i.get("when") or {}}
                         for i in resolved["inapplicable"]],
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
    try:
        res = review_svc.record_check(db, kind, parent, parent.current_version_id,
                                      actor=actor, actor_type="human",
                                      items=body.items, note=body.note)
    except ValueError as e:
        raise HTTPException(422, {"error": str(e)}) from e
    db.commit()
    return {**_detail(db, kind, parent), "blocked_items": res["blocked"]}


class ExceptionIn(BaseModel):
    """Grant a standing exception.

    `scope` is the safety question, so it is asked rather than inferred:
    `drawing` pins `$material_sha` and dies when the copper moves; `always` pins
    nothing and is a decision about the part itself. `pin` overrides both with
    an explicit list of facts, for the case neither preset fits.
    """

    key: str
    variant: str = ""
    reason: str = "waived"
    note: str
    evidence: str = ""
    scope: str = "drawing"
    pin: list[str] | None = None


@router.get("/reviews/failing/{kind}/{key}")
def failing_subjects(kind: str, key: str, db: Session = Depends(get_db)):
    """Every subject one check currently fails, with its note.

    The health panel groups failures by KEY because that is the work plan —
    "fp.model3d failing on 61 footprints" is one job and "218 failed parts" is a
    wall — but the numbers were dead text until 2026-09-14. This is what a
    number opens.

    Read from the conformance CACHE, never re-evaluated: 212 footprints at 20 ms
    each is four seconds for a list. A cold row is simply absent, which is the
    same thing the health count does.
    """
    if kind not in _PARENT:
        raise HTTPException(422, "kind must be component, symbol or footprint")
    model = _PARENT[kind]
    parents = {p.current_version_id: p for p in
               db.query(model).filter(model.current_version_id.isnot(None))}
    rows = (db.query(M.Conformance)
            .filter(M.Conformance.subject_kind == kind,
                    M.Conformance.subject_version_id.in_(parents))
            if parents else [])
    out = []
    for row in rows:
        parent = parents.get(row.subject_version_id)
        if parent is None:
            continue
        for item in row.items or []:
            if item.get("key") != key or item.get("result") != "failed":
                continue
            out.append({"id": parent.id, "name": getattr(parent, "name", ""),
                        "kind": kind, "note": item.get("note"),
                        "severity": item.get("severity", "error"),
                        "text": item.get("text", key),
                        "variant": item.get("variant")})
    # Flagged JUDGMENT answers live in records, not in conformance, so a
    # judgment key would otherwise report nothing at all.
    if not out:
        for parent in parents.values():
            rec = review_svc.effective_record(
                review_svc.records_for(db, kind, parent.id), parent.current_version_id)
            for item in (rec.items if rec is not None else None) or []:
                if item.get("key") == key and item.get("result") in ("failed", "flagged"):
                    out.append({"id": parent.id, "name": getattr(parent, "name", ""),
                                "kind": kind, "note": item.get("note"),
                                "severity": item.get("severity", "error"),
                                "text": item.get("text", key), "variant": None})
    out.sort(key=lambda r: r["name"])
    return {"kind": kind, "key": key, "subjects": out}


@router.get("/reviews/exceptions")
def all_exceptions(include_revoked: bool = False, db: Session = Depends(get_db)):
    """Every standing decision in the library, in one list.

    An exception was visible only on its own subject's review card until
    2026-09-14, so nothing could answer "what have we excused, and does it still
    hold". Decision 0016 calls an `always`-scoped one "a real loaded gun"; a
    register is what lets somebody see the guns.

    Liveness is judged per subject, and the cost is bounded by the number of
    EXCEPTIONS rather than by the size of the library — `subject_facts` runs
    once per distinct subject that has one, and its derived facts stay lazy, so
    only the facts an exception actually pinned are ever computed.
    """
    rows = db.query(M.ReviewException).order_by(M.ReviewException.id.desc()).all()
    if not include_revoked:
        rows = [e for e in rows if e.revoked_at is None]

    parents: dict[tuple[str, int], object] = {}
    facts: dict[tuple[str, int], dict] = {}
    out = []
    for exc in rows:
        ident = (exc.subject_kind, exc.subject_id)
        if ident not in parents:
            model = _PARENT.get(exc.subject_kind)
            parents[ident] = db.get(model, exc.subject_id) if model else None
        parent = parents[ident]
        if parent is None:
            # The subject is gone. Report the row rather than dropping it: a
            # decision with nothing left to apply to is exactly what a register
            # exists to surface.
            out.append({**exceptions_svc.json_of(exc), "subject_name": None,
                        "subject_gone": True})
            continue
        if ident not in facts:
            facts[ident] = checklists_svc.subject_facts(
                db, exc.subject_kind, parent, parent.current_version_id)
        out.append({**exceptions_svc.json_of(exc, facts[ident]),
                    "subject_name": getattr(parent, "name", ""),
                    "subject_gone": False})
    return out


@router.get("/reviews/{kind}/{parent_id}/exceptions")
def list_exceptions(kind: str, parent_id: int, db: Session = Depends(get_db)):
    parent = _parent_or_404(db, kind, parent_id)
    facts = checklists_svc.subject_facts(db, kind, parent, parent.current_version_id)
    return [exceptions_svc.json_of(e, facts)
            for e in exceptions_svc.rows_for(db, kind, parent.id)]


@router.post("/reviews/{kind}/{parent_id}/exceptions")
def grant_exception(kind: str, parent_id: int, body: ExceptionIn, request: Request,
                    db: Session = Depends(get_db)):
    """Record that one check does not apply to this subject, and keep it.

    This is the durable half of an `na` answer. Answering `na` closes the item
    on ONE version; an exception closes it until somebody revokes it or the
    facts it named change.
    """
    parent = _parent_or_404(db, kind, parent_id)
    if body.reason not in review_svc.NA_REASONS:
        raise HTTPException(422, f"reason must be one of {', '.join(review_svc.NA_REASONS)}")
    if not body.note.strip():
        raise HTTPException(422, "an exception needs a note saying why — it is the only "
                                 "place that reason will ever live")
    facts = checklists_svc.subject_facts(db, kind, parent, parent.current_version_id)

    if body.pin is not None:
        unknown = [f for f in body.pin if f.startswith("$")
                   and f not in checklists_svc.ALL_FACTS]
        if unknown:
            raise HTTPException(422, {
                "error": f"cannot pin {', '.join(unknown)} — not facts a subject carries. "
                         f"Facts: {', '.join(checklists_svc.ALL_FACTS)}",
                "key": body.key})
        pin = list(body.pin)
    elif body.scope == "always":
        pin = []
    elif body.scope == "drawing":
        pin = list(exceptions_svc.DRAWING_SCOPE)
    else:
        raise HTTPException(422, "scope must be 'drawing' or 'always', or pass `pin`")

    depends_on = {f: facts.get(f) for f in pin}
    missing = [f for f, v in depends_on.items() if v is None]
    if missing:
        # Pinning a fact the subject has not got would make the exception stale
        # the instant it was written, which reads as "it did not work".
        raise HTTPException(422, {
            "error": f"this {kind} carries no {', '.join(missing)}, so an exception cannot "
                     f"be pinned to it. Use scope 'always' if the decision is about the "
                     f"part rather than the drawing.",
            "key": body.key})

    actor = actor_of(request)
    try:
        exc = exceptions_svc.grant(
            db, kind, parent, body.key.strip(), reason=body.reason, note=body.note,
            actor=actor, actor_type="human", variant=body.variant.strip(),
            evidence=body.evidence, depends_on=depends_on)
    except ValueError as e:
        raise HTTPException(422, {"error": str(e), "key": body.key}) from e
    # Nothing to re-record: conformance is computed on read and the exception is
    # an OVERLAY on it (decision 0017), so it is in force the moment this
    # returns. Before that it had to be written at the machine tier here, which
    # is why revoking one used to leave the item unanswered.
    db.commit()
    db.expire_all()
    return {"exception": exceptions_svc.json_of(exc, facts), **_detail(db, kind, parent)}


@router.delete("/reviews/{kind}/{parent_id}/exceptions/{exc_id}")
def revoke_exception(kind: str, parent_id: int, exc_id: int, request: Request,
                     reason: str = "", db: Session = Depends(get_db)):
    parent = _parent_or_404(db, kind, parent_id)
    exc = db.get(M.ReviewException, exc_id)
    if exc is None or exc.subject_kind != kind or exc.subject_id != parent.id:
        raise HTTPException(404, "exception not found on this subject")
    if exc.revoked_at is not None:
        raise HTTPException(409, "already revoked")
    try:
        exceptions_svc.revoke(db, exc, actor_of(request), reason)
    except ValueError as e:
        raise HTTPException(422, {"error": str(e), "key": exc.key}) from e
    # The check is back immediately: the exception was an overlay on computed
    # conformance, so withdrawing it changes the next read with nothing to undo.
    db.commit()
    db.expire_all()
    return _detail(db, kind, parent)


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
def checklist_meta(db: Session = Depends(get_db)):
    """What the checklist editor needs to be honest about `machine: true`.

    A machine item is answered by `services/validator.py` — but only for the
    keys that module implements. Marking any other key `machine` produces an
    item nobody ever answers, which pins the subject at "partial" for ever. The
    editor greys the flag out for unknown keys, and `_validate_items` refuses
    it outright.

    It also carries the FACT VOCABULARY, per subject kind. The editor used to
    hold its own copy of the list, which is how a fact could exist in the
    backend and be unselectable in the UI — and how a fact the backend had
    renamed could still be offered.
    """
    return {"subject_kinds": list(_PARENT),
            "machine_keys": {k: list(v) for k, v in validator.MACHINE_KEYS.items()},
            # The full catalogue — key, text and hint — so the editor can render
            # every automatic check as a read-only row with an on/off switch
            # instead of a free-text row somebody has to keep in step by hand.
            "machine_checks": {k: [dict(c) for c in v]
                               for k, v in validator.machine_checks(db).items()},
            # Which facts each subject kind actually carries. A predicate naming
            # a fact the subject has not got never matches — the honest outcome,
            # but the editor can say so before somebody saves a rule that can
            # match nothing.
            "facts": {k: checklists_svc.facts_for_kind(k) for k in _PARENT},
            "assertions": list(validator.ASSERTIONS)}


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
            "items": [{**i, "from": sources.get(i["key"], "")} for i in resolved["items"]],
            # Switched off somewhere on the path. Shown, not hidden: "why does
            # this part not get the pad-shape check" has to be answerable from
            # the same screen that switched it off.
            "disabled": [{**i, "from": sources.get(i["key"], "")}
                         for i in resolved["disabled"]]}


def _inherited_for(db: Session, kind: str, category_id: int | None) -> list[dict]:
    """What a category-scoped list inherits: every list ABOVE it on the path,
    merged the way `checklists.resolve` merges them (base first, most specific
    last), each item tagged with the list it came from.

    The editor needs this to be editable-looking rather than resolved: a
    category list is a set of MODIFICATIONS to what it inherits, so the screen
    has to show the inherited wording next to the override that replaces it.
    Returns [] for a base list, which inherits nothing. Takes a SCOPE rather
    than a checklist, because a category the user has just picked in the editor
    may have no row yet and still inherits everything above it.
    """
    if category_id is None:
        return []
    path_ids: list[int] = []
    cat = db.get(M.Category, category_id)
    while cat is not None:
        path_ids.append(cat.id)
        cat = cat.parent
    above = [c for c in db.query(M.Checklist)
             .filter(M.Checklist.subject_kind == kind,
                     M.Checklist.category_id.in_(path_ids[1:])).all()] if len(path_ids) > 1 else []
    base = db.query(M.Checklist).filter_by(subject_kind=kind, category_id=None).first()
    ordered = ([base] if base is not None else []) + sorted(
        above, key=lambda c: path_ids.index(c.category_id), reverse=True)

    merged: dict[str, dict] = {}
    for src in ordered:
        cur = next((v for v in src.versions if v.id == src.current_version_id), None)
        for item in (cur.items if cur else []) or []:
            merged[item["key"]] = {**item, "from": src.name}
    return list(merged.values())


class ScopeSaveIn(BaseModel):
    kind: str
    category_id: int | None = None
    items: list[dict]
    comment: str | None = None
    description: str | None = None


def _scope_payload(db: Session, kind: str, category_id: int | None) -> dict:
    """One editing SCOPE, whether or not a checklist row exists for it yet.

    The editor addresses a checklist by (kind, category) rather than by id: the
    sidebar is three entries and a category picker, so picking a category that
    has never stated anything must show what it inherits and let the user state
    something — creating the row on the first save, not before. A row created by
    opening a dropdown would litter the list with empty checklists.
    """
    cl = db.query(M.Checklist).filter_by(subject_kind=kind, category_id=category_id).first()
    cv = next((v for v in cl.versions if v.id == cl.current_version_id), None) if cl else None
    cat = db.get(M.Category, category_id) if category_id is not None else None
    return {
        "id": cl.id if cl else None,
        "name": cl.name if cl else (f"{cat.name} rules" if cat else f"{kind} base checklist"),
        "subject_kind": kind,
        "category_id": category_id,
        "category_path": category_path(cat) if cat else None,
        "description": cl.description if cl else "",
        "version_no": cv.version_no if cv else None,
        "items": list(cv.items or []) if cv else [],
        "inherited": _inherited_for(db, kind, category_id),
        "exists": cl is not None,
        "history": [{"version_no": v.version_no, "created_at": v.created_at.isoformat(),
                     "created_by": v.created_by, "comment": v.comment,
                     "item_count": len(v.items or [])}
                    for v in reversed(cl.versions)] if cl else [],
    }


@router.get("/checklists/all")
def all_checklists(db: Session = Depends(get_db)):
    """Every scope with its stated items, for the one-table editor.

    Rows are what a scope actually STATES, not the cross product of every check
    with every scope: 16 component checks against 19 scopes would be 300 rows of
    mostly nothing, and a table that mostly says "not stated" is a table nobody
    reads. The base lists state everything, so the catalogue is covered; a
    category contributes only what it changes, which is also the answer to
    "what does this category do differently".
    """
    out = []
    for cl in db.query(M.Checklist).order_by(M.Checklist.subject_kind, M.Checklist.id).all():
        cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
        cat = db.get(M.Category, cl.category_id) if cl.category_id else None
        out.append({
            "id": cl.id,
            "name": cl.name,
            "subject_kind": cl.subject_kind,
            "category_id": cl.category_id,
            "category_path": category_path(cat) if cat else None,
            "version_no": cv.version_no if cv else None,
            "items": list(cv.items or []) if cv else [],
        })
    return {"scopes": out}


@router.get("/checklists/coverage")
def checklist_coverage(kind: str, key: str, category_id: int | None = None,
                       db: Session = Depends(get_db)):
    """How the live parts in a scope fall across one key's variants.

    This is the mitigation for the one hazard variants cannot design away: a
    variant keyed on a PROPERTY is only as reliable as that property. A category
    is a row; `comp_type` is free text, and this library already carries
    `ZENNER` with an extra "n". A misspelled value makes a part fall silently
    through to the fallback, or out of the check altogether — no failure, no
    warning, nothing to notice.

    Counting turns that into a number on the screen. **A non-zero "no match" on
    a settled category means the discriminator is not reliable**, and that
    category wants a subcategory rather than a predicate.
    """
    if kind not in _PARENT:
        raise HTTPException(422, "kind must be component, symbol or footprint")
    if kind != "component":
        return {"key": key, "counts": [], "note": f"a {kind} has no category to count over"}
    in_scope = category_and_descendant_ids(db, category_id) if category_id is not None else None

    comps, live = components_with_current(db)
    counts: dict[str, int] = {}
    no_match = 0
    total = 0
    for comp in comps:
        cv = live.get(comp.id)
        if cv is None or (in_scope is not None and cv.category_id not in in_scope):
            continue
        resolved = checklists_svc.resolve(
            db, kind, cv.category_id,
            checklists_svc.subject_facts(db, kind, comp, cv.id))
        total += 1
        item = next((i for i in resolved["items"] if i["key"] == key), None)
        if item is None:
            no_match += 1
            continue
        counts[item.get("variant") or "(the only one)"] = \
            counts.get(item.get("variant") or "(the only one)", 0) + 1
    return {"key": key, "category_id": category_id, "total": total,
            "counts": [{"variant": v, "count": n} for v, n in sorted(counts.items())],
            "no_match": no_match}


@router.get("/checklists/scope")
def get_checklist_scope(kind: str, category_id: int | None = None,
                        db: Session = Depends(get_db)):
    if kind not in _PARENT:
        raise HTTPException(422, "kind must be component, symbol or footprint")
    if category_id is not None and db.get(M.Category, category_id) is None:
        raise HTTPException(422, "category not found")
    return _scope_payload(db, kind, category_id)


@router.put("/checklists/scope")
def save_checklist_scope(body: ScopeSaveIn, request: Request, db: Session = Depends(get_db)):
    """Publish a version of the checklist for one scope, creating it if this is
    the first thing that scope has ever stated.

    Saving an EMPTY item list on a category deletes the row rather than leaving
    a checklist that states nothing: "this category adds nothing" and "this
    category has a list that happens to be empty" must not be two different
    states, or the sidebar fills with rows nobody can tell apart.
    """
    if body.kind not in _PARENT:
        raise HTTPException(422, "kind must be component, symbol or footprint")
    if body.category_id is not None:
        cat = db.get(M.Category, body.category_id)
        if cat is None:
            raise HTTPException(422, "category not found")
        if body.kind != "component":
            raise HTTPException(422, {
                "error": f"a {body.kind} carries no category, so its checks cannot be "
                         f"scoped to one — edit the base {body.kind} checklist"})
    items = _validate_items(db, body.items, body.kind)
    actor = actor_of(request)
    cl = db.query(M.Checklist).filter_by(
        subject_kind=body.kind, category_id=body.category_id).first()

    if not items and body.category_id is not None:
        if cl is not None:
            audit(db, "checklist.delete", "checklist", cl.id, {"checklist": cl.name},
                  actor=actor)
            db.query(M.ChecklistVersion).filter_by(checklist_id=cl.id).delete()
            db.delete(cl)
            db.commit()
        db.expire_all()
        return _scope_payload(db, body.kind, body.category_id)

    if cl is None:
        if body.category_id is None:
            raise HTTPException(422, f"no base checklist for a {body.kind}")
        name = f"{cat.name} rules"
        if db.query(M.Checklist).filter_by(name=name).first():
            name = f"{name} ({body.category_id})"
        cl = M.Checklist(name=name, subject_kind=body.kind, category_id=body.category_id,
                         description=(body.description or "").strip()
                         or f"Checks for {category_path(cat)}")
        db.add(cl)
        db.flush()
        audit(db, "checklist.create", "checklist", cl.id,
              {"checklist": cl.name, "subject_kind": cl.subject_kind}, actor=actor)

    numbers = [n for (n,) in db.query(M.ChecklistVersion.version_no)
               .filter_by(checklist_id=cl.id)]
    cv = M.ChecklistVersion(checklist_id=cl.id, version_no=max(numbers, default=0) + 1,
                            items=items, status="published", created_by=actor,
                            comment=(body.comment or "").strip() or None)
    db.add(cv)
    db.flush()
    cl.current_version_id = cv.id
    if body.description is not None:
        cl.description = body.description.strip()
    audit(db, "checklist.publish", "checklist", cl.id,
          {"checklist": cl.name, "version_no": cv.version_no, "items": len(items)}, actor=actor)
    db.commit()
    # `expire_on_commit=False`: without this the response describes the
    # checklist as it was BEFORE the save. Same trap as `services/repoint.py`.
    db.expire_all()
    return _scope_payload(db, body.kind, body.category_id)


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
        "inherited": _inherited_for(db, cl.subject_kind, cl.category_id),
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


def _clean_assert(key: str, given) -> dict:
    """A declarative check: ONE fact, ONE assertion.

    The vocabulary is closed and refused here rather than ignored at run time.
    The ceiling — one assertion, no booleans, no arithmetic between facts — is
    the design, not an omission: the first time this needs `any_of`, it has
    become a rules language, which is what `models.Rule` was and what this
    platform spent 2026-09-14 deleting.
    """
    if given is None:
        return {}
    if not isinstance(given, dict):
        raise HTTPException(422, f"{key}: `assert` must be an object")
    fact = str(given.get("fact") or "").strip()
    if not fact:
        raise HTTPException(422, f"{key}: `assert` needs a fact to read")
    if fact.startswith("$") and fact not in checklists_svc.ALL_FACTS:
        raise HTTPException(422, {
            "error": f"{key}: {fact!r} is not a fact a check can read. "
                     f"Facts: {', '.join(checklists_svc.ALL_FACTS)}. "
                     f"A property is written without the $.",
            "key": key})
    used = [a for a in validator.ASSERTIONS if a in given]
    if len(used) != 1:
        raise HTTPException(422, {
            "error": f"{key}: `assert` makes exactly ONE assertion about {fact!r}, "
                     f"not {len(used)}. One of: {', '.join(validator.ASSERTIONS)}. "
                     f"A rule needing two belongs in two checks.",
            "key": key})
    name = used[0]
    value = given[name]
    out: dict = {"fact": fact}
    if name == "one_of":
        if not isinstance(value, list) or not value:
            raise HTTPException(422, f"{key}: `one_of` needs a non-empty list")
        out["one_of"] = [str(v).strip() for v in value if str(v).strip()]
    elif name == "matches":
        try:
            re.compile(str(value))
        except re.error as e:
            raise HTTPException(422, f"{key}: {value!r} is not a valid regular "
                                     f"expression — {e}") from None
        out["matches"] = str(value)
    elif name in ("at_least", "at_most"):
        try:
            out[name] = float(value)
        except (TypeError, ValueError):
            raise HTTPException(422, f"{key}: `{name}` needs a number") from None
    elif name == "equals":
        out["equals"] = str(value)
    else:
        out["present"] = True
    return out


def _clean_when(key: str, given) -> dict:
    """An item's `when` predicate: which subjects the check is ABOUT.

    Every entry must match for the check to apply, and each value is a regular
    expression over one fact. A bare name is a component property; a `$` name is
    a structural fact from `checklists.WHEN_FACTS`, and a misspelled one is
    refused HERE — a property name cannot be validated (any string is legal),
    but a fact name can, and a predicate that silently matches nothing is a
    check that silently stops running.
    """
    if given is None:
        return {}
    if not isinstance(given, dict):
        raise HTTPException(422, f"{key}: `when` must map a field to a pattern")
    out: dict[str, str] = {}
    for field, pattern in given.items():
        field = str(field).strip()
        if not field:
            raise HTTPException(422, f"{key}: a `when` entry needs a field name")
        # ALL_FACTS, not WHEN_FACTS: a predicate and an assertion read the same
        # vocabulary, which is the point of having one. Restricting `when` to
        # the cheap half would have made `$symbol_on_board` unusable in exactly
        # the place it is most useful — narrowing a symbol check to board parts.
        if field.startswith("$") and field not in checklists_svc.ALL_FACTS:
            raise HTTPException(422, {
                "error": f"{key}: {field!r} is not a fact a predicate can read. "
                         f"Facts: {', '.join(checklists_svc.ALL_FACTS)}. "
                         f"A property is written without the $.",
                "key": key})
        try:
            re.compile(str(pattern))
        except re.error as e:
            raise HTTPException(
                422, f"{key}: {field} is not a valid regular expression — {e}") from None
        out[field] = str(pattern)
    return out


def _clean_params(subject_kind: str, key: str, given) -> dict:
    """One automatic check's numbers, checked against the names it declares.

    A threshold is validated here rather than where it is used: a non-numeric or
    non-positive one would make its check compare against nonsense and PASS
    silently, which is the one failure mode a validator must not have.
    """
    spec = next((c for c in validator._CHECK_SPECS.get(subject_kind, ())
                 if c["key"] == key), None)
    known = dict((spec or {}).get("params") or {})
    if not isinstance(given, dict) or not given:
        return dict(known)
    out = dict(known)
    for name, value in given.items():
        if name not in known:
            raise HTTPException(422, {
                "error": f"{key} has no parameter {name!r}. "
                         f"It takes: {', '.join(sorted(known)) or 'none'}",
                "key": key})
        want = known[name]
        # The DEFAULT's type is the parameter's type. A threshold is a positive
        # number, a property set is a list of names, a pattern map is
        # property -> regular expression, and a switch is a switch.
        if isinstance(want, bool):
            out[name] = bool(value)
        elif isinstance(want, (int, float)):
            try:
                number = float(value)
            except (TypeError, ValueError):
                raise HTTPException(422, f"{key}.{name} must be a number") from None
            if not number > 0:
                raise HTTPException(422, f"{key}.{name} must be above zero")
            out[name] = number
        elif isinstance(want, list):
            if not isinstance(value, list):
                raise HTTPException(422, f"{key}.{name} must be a list of property names")
            names = [str(v).strip() for v in value if str(v).strip()]
            if len(set(names)) != len(names):
                raise HTTPException(422, f"{key}.{name} repeats a property name")
            out[name] = names
        elif isinstance(want, dict):
            if not isinstance(value, dict):
                raise HTTPException(422, f"{key}.{name} must map a property to a pattern")
            patterns: dict[str, str] = {}
            for prop, expr in value.items():
                prop = str(prop).strip()
                if not prop:
                    raise HTTPException(422, f"{key}.{name}: a pattern needs a property name")
                try:
                    re.compile(str(expr))
                except re.error as e:
                    # Refused here rather than at the point of use: a pattern
                    # that does not compile would fail every part carrying the
                    # property and name no cause anybody could act on.
                    raise HTTPException(
                        422, f"{key}.{name}: {prop} is not a valid regular "
                             f"expression — {e}") from None
                patterns[prop] = str(expr)
            out[name] = patterns
        else:
            text = str(value).strip()
            if not text:
                raise HTTPException(422, f"{key}.{name} must not be empty")
            out[name] = text
    return out


def _validate_items(db: Session, items: list[dict], subject_kind: str) -> list[dict]:
    """Clean one checklist's items, and refuse the two shapes that cannot work.

    A duplicate key would silently drop an item (the resolver is keyed by key),
    and a `machine: true` flag on a key `services/validator.py` does not answer
    would create an item nobody can ever answer — the subject would sit at
    "partial" for ever with no way to clear it. Both are refused here rather
    than discovered months later on a part nobody can finish reviewing.

    An automatic item's TEXT and HINT are not accepted from the client: they
    are rewritten from `validator.machine_checks`, which is the one place an
    automatic check is described. Its `params` ARE accepted — they are the
    numbers that check compares against, and they live on the item so they
    version with the checklist, sit beside the switch that turns the check on,
    and land in the review record's `checklist_items` snapshot. Each item is
    then re-worded with its OWN numbers, because the sentence a reviewer reads
    and the comparison the code makes have to be the same fact.
    """
    machine_keys = set(validator.MACHINE_KEYS.get(subject_kind, ()))
    clean = []
    seen: set[tuple[str, str]] = set()
    for i in items:
        key = str(i.get("key", "")).strip()
        text = str(i.get("text", "")).strip()
        if not key:
            raise HTTPException(422, "every item needs a key")
        variant = str(i.get("variant") or "").strip()
        if (key, variant) in seen:
            raise HTTPException(422, {
                "error": f"{key!r} is stated twice"
                         + (f" for variant {variant!r}" if variant else " with no variant")
                         + ". Several items may share a key only as distinct named "
                           "variants — give each one a `variant`.",
                "key": key})
        seen.add((key, variant))
        spec = _clean_assert(key, i.get("assert"))
        if spec and i.get("machine"):
            # A declarative check's key is author-chosen, so it is not in
            # MACHINE_KEYS — this is the second door to `machine: true`,
            # guaranteeing the same thing (something answers it) another way.
            # Its text is GENERATED, for the reason a parameterised check's is:
            # a sentence typed beside a rule can disagree with it.
            item = {"key": key, "text": validator.describe_assert(spec),
                    "machine": True, "assert": spec}
        elif i.get("machine"):
            entry = validator.machine_check(db, subject_kind, key)
            if entry is None:
                raise HTTPException(422, {
                    "error": f"{key!r} is marked machine-checked, but the validator does not "
                             f"answer it — the item would stay unanswered for ever. "
                             f"Machine keys for a {subject_kind}: "
                             + ", ".join(sorted(machine_keys)),
                    "key": key})
            params = _clean_params(subject_kind, key, i.get("params"))
            entry = validator.machine_check(db, subject_kind, key,
                                            {key: {"params": params}}) or entry
            item = {"key": key, "text": entry["text"], "machine": True}
            if entry.get("hint"):
                item["hint"] = entry["hint"]
            if params:
                item["params"] = params
        else:
            if spec:
                raise HTTPException(422, {
                    "error": f"{key}: an `assert` is answered by the validator, so the "
                             f"item has to be marked automatic.",
                    "key": key})
            if not text:
                raise HTTPException(422, "every judgment item needs a text")
            item = {"key": key, "text": text}
            if str(i.get("hint", "")).strip():
                item["hint"] = str(i["hint"]).strip()
        when = _clean_when(key, i.get("when"))
        if when:
            item["when"] = when
        if variant:
            item["variant"] = variant
        # What a FAILURE of this check means, and — at `ignore` — whether it
        # runs here at all. One control with three values, not a switch beside a
        # severity. `disabled: true` is the retired spelling and is converted
        # here, so nothing writes it again. See `checklists.SEVERITIES`.
        severity = str(i.get("severity") or "").strip()
        if not severity and i.get("disabled"):
            severity = "ignore"
        if severity and severity not in checklists_svc.SEVERITIES:
            raise HTTPException(422, {
                "error": f"{key}: severity must be one of "
                         f"{', '.join(checklists_svc.SEVERITIES)}",
                "key": key})
        if severity and severity != checklists_svc.DEFAULT_SEVERITY:
            item["severity"] = severity
        clean.append(item)
    _check_variant_groups(clean)
    return clean


#: A pattern that matches everything, so a variant carrying it is a fallback in
#: all but name and shadows every variant after it.
_TOTAL_PATTERNS = frozenset({"", ".*", "^.*$", "^", "$", "^$|.*"})


def _check_variant_groups(items: list[dict]) -> None:
    """A key with SEVERAL variants must discriminate on one field, with distinct
    literal values, plus at most one variant with no `when` — the fallback.

    That constraint is what lets `checklists.pick` avoid an ordering rule
    altogether: at most one literal can match, and the fallback is last by rule
    rather than by position. Without it, precedence would be positional, and a
    SORTED table would show variants in an order that contradicts the effective
    one — a screen lying about which rule a part gets.

    It also makes "is this variant reachable" decidable, which best-effort
    shadow detection over arbitrary regexes is not. The price is that a variant
    cannot carry a compound predicate; a single-item key still can, and a
    genuinely special case is a separate key — which is now enforced rather than
    merely advised.
    """
    groups: dict[str, list[dict]] = {}
    for item in items:
        groups.setdefault(item["key"], []).append(item)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        unnamed = [g for g in group if not g.get("variant")]
        if unnamed:
            raise HTTPException(422, {
                "error": f"{key!r} has {len(group)} variants, so each one needs a `variant` "
                         f"name — it is the variant's identity and its label.",
                "key": key})
        fallbacks = [g for g in group if not g.get("when")]
        if len(fallbacks) > 1:
            raise HTTPException(422, {
                "error": f"{key!r} has {len(fallbacks)} variants with no condition. "
                         f"One is the fallback; the rest could never be reached.",
                "key": key})
        fields = {f for g in group if g.get("when") for f in g["when"]}
        if len(fields) > 1:
            raise HTTPException(422, {
                "error": f"{key!r} splits on {len(fields)} different fields "
                         f"({', '.join(sorted(fields))}). Variants of one key must "
                         f"discriminate on ONE field — otherwise two could match the same "
                         f"part and nothing decides which wins. Use a separate key for a "
                         f"rule that needs a different condition.",
                "key": key})
        for g in group:
            when = g.get("when") or {}
            if len(when) > 1:
                raise HTTPException(422, {
                    "error": f"{key!r} variant {g['variant']!r} has {len(when)} conditions. "
                             f"A variant carries one, on the field its group splits on. "
                             f"A compound condition belongs on a key of its own.",
                    "key": key})
        seen_patterns: dict[str, str] = {}
        for g in group:
            when = g.get("when") or {}
            if not when:
                continue
            pattern = next(iter(when.values()))
            if pattern in _TOTAL_PATTERNS:
                raise HTTPException(422, {
                    "error": f"{key!r} variant {g['variant']!r} matches everything, so every "
                             f"other variant is unreachable. Leave its condition off to make "
                             f"it the fallback instead.",
                    "key": key})
            if pattern in seen_patterns:
                raise HTTPException(422, {
                    "error": f"{key!r} variants {seen_patterns[pattern]!r} and "
                             f"{g['variant']!r} share the condition {pattern!r}, so the "
                             f"second can never be reached.",
                    "key": key})
            seen_patterns[pattern] = g["variant"]


@router.put("/checklists/{cl_id}")
def save_checklist(cl_id: int, body: ChecklistSaveIn, request: Request,
                   db: Session = Depends(get_db)):
    """Publish a new checklist version. A human save publishes directly —
    same rationale as the component in-place save (the user saving IS the
    approval); the agent has no checklist write tool."""
    cl = db.get(M.Checklist, cl_id)
    if cl is None:
        raise HTTPException(404, "checklist not found")
    items = _validate_items(db, body.items, cl.subject_kind)
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
    items = _validate_items(db, body.items, body.subject_kind)
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
    # One conformance query for the lot — the cache, not a re-evaluation.
    vids = {p.current_version_id for p in parents if p.current_version_id}
    conf = {r.subject_version_id: (list(r.items or []), list(r.excused or []))
            for r in db.query(M.Conformance).filter(
                M.Conformance.subject_kind == kind,
                M.Conformance.subject_version_id.in_(vids))} if vids else {}
    out = {}
    for p in parents:
        rec = review_svc.effective_record(by_parent.get(p.id, []), p.current_version_id)
        items, excused = conf.get(p.current_version_id, (None, []))
        out[p.id] = review_svc.state_from_record(
            rec, review_svc._checklist_items_of(db, rec), items, excused)
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
    # Live versions only. Loading every component's whole history here cost as
    # much as it did on the browse list — see `components_with_current`.
    comps, live = components_with_current(db)

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

    review_states = review_svc.states_for_components(db, comps, cvs=live)
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
        cv = live.get(c.id)
        if cv is None:
            continue
        if cv.base_component:
            sym_users[cv.base_component] = sym_users.get(cv.base_component, 0) + 1
        fp_id = fp_parent_of.get(cv.footprint_version_id) if cv.footprint_version_id else None
        if fp_id is not None:
            fp_users[fp_id] = fp_users.get(fp_id, 0) + 1

    comp_rows = []
    for c in comps:
        cv = live.get(c.id)
        rs = review_states[c.id]
        comp_rows.append({
            "id": c.id, "name": c.name,
            "version_no": cv.version_no if cv else None,
            "category_path": category_path(cv.category) if cv else "",
            "review_state": rs["state"],
            "provenance": rs.get("provenance"),
            "blockers": rs.get("blockers", []),
            # The two facts under the one word. `partial` meant "nobody has
            # looked", "a question was added last week" and "one item is open"
            # all at once; a list that cannot tell them apart cannot be
            # prioritised. A component's are its OWN — a pinned drawing's state
            # already reaches the row through `blockers`.
            **_facts_of(rs.get("parts", {}).get("component", rs)),
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
                         # the preview URL's cache key (libraries._preview)
                         "version_id": p.current_version_id,
                         "review_state": s["state"], "provenance": s.get("provenance"),
                         "skipped": s["skipped"], "failed": s["failed"],
                         "unanswered": len(s["unanswered"]),
                         **_facts_of(s),
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
    comps, live = components_with_current(db)
    review_states = review_svc.states_for_components(db, comps, cvs=live)
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
    # `na_counts`/`na_reasons` replaced the skip pair on 2026-09-13 when
    # `skipped` was retired (decision 0011). The retired value is still counted,
    # under `legacy_skipped`, because 138 rows carry it and reporting them as
    # nothing would hide work that is still open.
    na_counts: dict[str, int] = {}
    na_reasons: dict[str, int] = {}
    legacy_skipped: dict[str, int] = {}
    # SUBJECT IDS per key, not a running count. One subject can carry the same
    # finding twice — an agent's `flagged` in its record AND the machine's
    # `failed` in conformance — and adding the two reported `cmp.datasheet_text`
    # on 47 components when 27 actually carry it (measured 2026-09-14). A set
    # cannot double-count, and the number is the size of the work.
    fail_ids: dict[str, dict[str, set[int]]] = {"component": {}, "symbol": {},
                                                "footprint": {}}

    def _failing(kind: str, key: str, subject_id: int) -> None:
        fail_ids[kind].setdefault(key, set()).add(subject_id)

    version_owner: dict[str, dict[int, int]] = {}
    for kind, model in (("component", M.Component), ("symbol", M.Symbol),
                        ("footprint", M.Footprint)):
        parents = {p.id: p for p in
                   db.query(model).filter(model.current_version_id.isnot(None))}
        version_owner[kind] = {p.current_version_id: pid for pid, p in parents.items()}
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
                if res == "na":
                    na_counts[key] = na_counts.get(key, 0) + 1
                    reason = item.get("reason") or "unstated"
                    na_reasons[reason] = na_reasons.get(reason, 0) + 1
                elif res == "skipped":
                    legacy_skipped[key] = legacy_skipped.get(key, 0) + 1
                elif res in ("failed", "flagged"):
                    _failing(kind, key, pid)

    # Machine failures come from CONFORMANCE, not from records. They stopped
    # being written on 2026-09-14 (decision 0017), so counting records alone
    # would report the failures of a library that no longer exists and miss
    # every one found since. The cache is read as-is: this is a dashboard, and
    # a warm row is a better number than a nine-second page.
    #
    # `version_owner` keeps this to CURRENT versions. `Conformance` holds a row
    # for every version it has ever evaluated, so an unfiltered sweep counts a
    # defect once per historical version too.
    for row in db.query(M.Conformance):
        owner = version_owner.get(row.subject_kind, {}).get(row.subject_version_id)
        if owner is None:
            continue
        for item in row.items or []:
            if item.get("result") == "failed" and item.get("severity", "error") != "warning":
                _failing(row.subject_kind, item.get("key", "?"), owner)
        # A standing exception is where "does not apply" lives now, so it is
        # where the na numbers have to be read from. An `na` in a record is a
        # row written before the change.
        for item in row.excused or []:
            k = item.get("key", "?")
            na_counts[k] = na_counts.get(k, 0) + 1
            r = item.get("reason") or "unstated"
            na_reasons[r] = na_reasons.get(r, 0) + 1
    fail_keys = {kind: {k: len(v) for k, v in keys.items()}
                 for kind, keys in fail_ids.items()}
    top_na = sorted(na_counts.items(), key=lambda kv: -kv[1])[:10]
    top_legacy = sorted(legacy_skipped.items(), key=lambda kv: -kv[1])[:10]

    return {
        "components": {"total": len(comps), "review": review_counts,
                       "signoff": signoff_counts, "lifecycle": lifecycle_counts},
        "used_not_signed": sorted(used_not_signed),
        "used_deprecated": sorted(used_deprecated),
        "top_na_items": [{"key": k, "count": n} for k, n in top_na],
        "na_reasons": [{"reason": k, "count": n}
                       for k, n in sorted(na_reasons.items(), key=lambda kv: -kv[1])],
        # Retired 2026-09-13; read as unanswered, still reported so the backlog
        # of items nobody has actually answered stays visible.
        "legacy_skipped_items": [{"key": k, "count": n} for k, n in top_legacy],
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
