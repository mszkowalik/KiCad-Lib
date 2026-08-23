"""The review axis: cumulative checklist verifications on published versions.

Publishing and reviewing are separate axes (user design 2026-08-23). Versions
publish immediately; this module records who has verified each version against
its documentation and derives every state from the records:

- ``unreviewed`` — no record on the version.
- ``failed``     — the newest record carries at least one ``failed`` item
                   (a machine check found a concrete violation).
- ``partial``    — items were ``skipped`` (applicable but unverifiable) or
                   checklist items are still unanswered.
- ``checked``    — every applicable item answered ``checked`` or ``na``.

Records are append-only and CUMULATIVE: each new record stores the full merged
item list, so a follow-up verification (documentation found later, checklist
grew) starts from everything already answered. Per-item provenance is kept and
enforced: machine < agent < human — a lower tier never overwrites a higher
tier's answer.

The carry rule mirrors the sign-off carry (`services/signoff.py`): a new
version that changes nothing material (equal ``material_sha``), or whose
change was explicitly waived (``recheck_required=False``), inherits the
previous record as a ``carry``. Anything else starts unreviewed again.

Nothing here blocks anything — reporting only, exactly like sign-offs. The one
warning gate (production-run creation) lives at its call site.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M
from . import checklists, signoff

KINDS = ("component", "symbol", "footprint")
# `failed` = a machine rule violation; `flagged` = an agent or human verified
# an item and found it WRONG, recorded without fixing it (the second-pass
# list, user design 2026-08-23). Both read as state "failed" ("issues").
RESULTS = ("checked", "na", "skipped", "failed", "flagged")
TIER = {"machine": 0, "agent": 1, "human": 2}
STATE_RANK = {"failed": 0, "unreviewed": 1, "partial": 2, "checked": 3}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- reading
def records_for(db: Session, kind: str, subject_id: int) -> list[M.ReviewRecord]:
    return (
        db.query(M.ReviewRecord)
        .filter_by(subject_kind=kind, subject_id=subject_id)
        .order_by(M.ReviewRecord.id)
        .all()
    )


def effective_record(rows: list[M.ReviewRecord], version_id: int | None) -> M.ReviewRecord | None:
    """The newest non-revoked record on one version."""
    if version_id is None:
        return None
    return next(
        (r for r in reversed(rows) if r.subject_version_id == version_id and r.revoked_at is None),
        None,
    )


def record_json(r: M.ReviewRecord) -> dict:
    return {
        "id": r.id,
        "subject_kind": r.subject_kind,
        "subject_version_id": r.subject_version_id,
        "kind": r.kind,
        "carried_from_id": r.carried_from_id,
        "checklist_version_id": r.checklist_version_id,
        "items": r.items,
        "note": r.note,
        "created_by": r.created_by,
        "actor_type": r.actor_type,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
        "revoked_by": r.revoked_by,
        "revoke_reason": r.revoke_reason,
    }


def _provenance(record: M.ReviewRecord) -> str:
    """The strongest tier that touched this record's answers."""
    best = record.actor_type if record.actor_type in TIER else "machine"
    for item in record.items or []:
        t = item.get("actor_type", "")
        if t in TIER and TIER[t] > TIER[best]:
            best = t
    return best


def state_from_record(record: M.ReviewRecord | None, checklist_items: list[dict] | None) -> dict:
    """Derive one version's state from its effective record.

    ``checklist_items`` is the resolved checklist to measure completeness
    against — pass the record's own checklist version items so a later
    checklist edit never silently flips history; the caller separately reports
    how far the current checklist has moved on.
    """
    if record is None:
        return {"state": "unreviewed", "provenance": None, "record_id": None,
                "answered": 0, "total": 0, "skipped": 0, "failed": 0, "flagged": 0,
                "unanswered": []}

    if record.items is None:
        # One-click human confirmation: no item breakdown, full check.
        return {"state": "checked", "provenance": "human", "record_id": record.id,
                "answered": 0, "total": 0, "skipped": 0, "failed": 0, "flagged": 0,
                "unanswered": []}

    by_key = {i.get("key"): i for i in record.items}
    failed = [k for k, i in by_key.items() if i.get("result") in ("failed", "flagged")]
    flagged = [k for k, i in by_key.items() if i.get("result") == "flagged"]
    skipped = [k for k, i in by_key.items() if i.get("result") == "skipped"]
    expected = [i["key"] for i in (checklist_items or [])]
    unanswered = [k for k in expected if k not in by_key]
    answered = sum(1 for i in by_key.values() if i.get("result") in ("checked", "na"))

    if failed:
        state = "failed"
    elif skipped or unanswered:
        state = "partial"
    else:
        state = "checked"
    return {"state": state, "provenance": _provenance(record), "record_id": record.id,
            "answered": answered, "total": max(len(expected), len(by_key)),
            "skipped": len(skipped), "failed": len(failed), "flagged": len(flagged),
            "unanswered": unanswered}


def _checklist_items_of(db: Session, record: M.ReviewRecord | None) -> list[dict] | None:
    """What this record was measured against — the snapshot it carries, else
    the base checklist version it pinned (rows written before 2026-08-24).

    Never re-resolve from the current checklists here: an edit to a checklist
    would then rewrite the state of every check ever recorded.
    """
    if record is None:
        return None
    if record.checklist_items is not None:
        return list(record.checklist_items)
    if record.checklist_version_id is None:
        return None
    cv = db.get(M.ChecklistVersion, record.checklist_version_id)
    return list(cv.items or []) if cv else None


def version_state(db: Session, kind: str, subject_id: int, version_id: int | None,
                  rows: list[M.ReviewRecord] | None = None) -> dict:
    rows = records_for(db, kind, subject_id) if rows is None else rows
    record = effective_record(rows, version_id)
    return state_from_record(record, _checklist_items_of(db, record))


# --------------------------------------------------- component aggregate state
def component_effective(db: Session, comp: M.Component,
                        cv: M.ComponentVersion | None = None) -> dict:
    """A component's overall review state: the WEAKEST of its own record and
    the records on its pinned symbol and footprint versions. A checked
    component pinned to an unreviewed footprint is not a checked part."""
    if cv is None:
        cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
    if cv is None:
        return {"state": "unreviewed", "parts": {}}

    parts: dict[str, dict] = {
        "component": version_state(db, "component", comp.id, cv.id),
    }
    if cv.symbol_version_id:
        sv = db.get(M.SymbolVersion, cv.symbol_version_id)
        if sv is not None:
            parts["symbol"] = version_state(db, "symbol", sv.symbol_id, sv.id)
    if cv.footprint_version_id:
        fv = db.get(M.FootprintVersion, cv.footprint_version_id)
        if fv is not None:
            parts["footprint"] = version_state(db, "footprint", fv.footprint_id, fv.id)

    worst = min(parts.values(), key=lambda p: STATE_RANK[p["state"]])
    blockers = [f"{name}: {p['state']}" for name, p in parts.items()
                if p["state"] != "checked"]
    provs = [p["provenance"] for p in parts.values() if p["provenance"]]
    prov = min(provs, key=lambda t: TIER[t]) if provs and worst["state"] == "checked" else \
        (parts["component"].get("provenance"))
    return {"state": worst["state"], "provenance": prov, "parts": parts, "blockers": blockers}


def states_for_components(db: Session, comps: list[M.Component]) -> dict[int, dict]:
    """`component_effective` over many components with bulk queries.

    List surfaces (browse, queue, project review) call this; per-row loops of
    `db.get` would repeat the kicad_http chooser mistake.
    """
    cvs = {c.id: next((v for v in c.versions if v.id == c.current_version_id), None)
           for c in comps}
    sym_ver_ids = {cv.symbol_version_id for cv in cvs.values() if cv and cv.symbol_version_id}
    fp_ver_ids = {cv.footprint_version_id for cv in cvs.values() if cv and cv.footprint_version_id}

    sym_parent = {}
    if sym_ver_ids:
        for vid, pid in db.query(M.SymbolVersion.id, M.SymbolVersion.symbol_id).filter(
                M.SymbolVersion.id.in_(sym_ver_ids)):
            sym_parent[vid] = pid
    fp_parent = {}
    if fp_ver_ids:
        for vid, pid in db.query(M.FootprintVersion.id, M.FootprintVersion.footprint_id).filter(
                M.FootprintVersion.id.in_(fp_ver_ids)):
            fp_parent[vid] = pid

    # One query per kind for every relevant record.
    def _bulk(kind: str, ids: set[int]) -> dict[int, list[M.ReviewRecord]]:
        out: dict[int, list[M.ReviewRecord]] = {i: [] for i in ids}
        if ids:
            q = (db.query(M.ReviewRecord)
                 .filter(M.ReviewRecord.subject_kind == kind,
                         M.ReviewRecord.subject_id.in_(ids))
                 .order_by(M.ReviewRecord.id))
            for r in q:
                out.setdefault(r.subject_id, []).append(r)
        return out

    comp_rows = _bulk("component", {c.id for c in comps})
    sym_rows = _bulk("symbol", set(sym_parent.values()))
    fp_rows = _bulk("footprint", set(fp_parent.values()))

    out: dict[int, dict] = {}
    for c in comps:
        cv = cvs.get(c.id)
        if cv is None:
            out[c.id] = {"state": "unreviewed", "parts": {}, "blockers": [], "provenance": None}
            continue
        parts = {"component": state_from_record(
            effective_record(comp_rows.get(c.id, []), cv.id),
            _checklist_items_of(db, effective_record(comp_rows.get(c.id, []), cv.id)))}
        if cv.symbol_version_id and cv.symbol_version_id in sym_parent:
            rec = effective_record(sym_rows.get(sym_parent[cv.symbol_version_id], []),
                                   cv.symbol_version_id)
            parts["symbol"] = state_from_record(rec, _checklist_items_of(db, rec))
        if cv.footprint_version_id and cv.footprint_version_id in fp_parent:
            rec = effective_record(fp_rows.get(fp_parent[cv.footprint_version_id], []),
                                   cv.footprint_version_id)
            parts["footprint"] = state_from_record(rec, _checklist_items_of(db, rec))
        worst = min(parts.values(), key=lambda p: STATE_RANK[p["state"]])
        blockers = [f"{name}: {p['state']}" for name, p in parts.items() if p["state"] != "checked"]
        provs = [p["provenance"] for p in parts.values() if p["provenance"]]
        prov = min(provs, key=lambda t: TIER[t]) if provs and worst["state"] == "checked" \
            else parts["component"].get("provenance")
        out[c.id] = {"state": worst["state"], "provenance": prov, "parts": parts,
                     "blockers": blockers}
    return out


# ----------------------------------------------------------------- writing
def _category_of(db: Session, kind: str, parent) -> int | None:
    if kind != "component":
        return None
    cv = next((v for v in parent.versions if v.id == parent.current_version_id), None)
    return cv.category_id if cv else None


def record_check(db: Session, kind: str, parent, version_id: int, actor: str,
                 actor_type: str, items: list[dict] | None, note: str | None = None,
                 record_kind: str = "check") -> dict:
    """Write a verification record, merged on top of the previous one.

    ``items=None`` with ``actor_type='human'`` is the one-click confirmation.
    Otherwise every item is ``{key, result, note?}`` and the merge enforces the
    tier rule: an answer already given by a HIGHER tier is kept, and the
    refused keys are reported back rather than silently dropped.
    """
    assert kind in KINDS
    rows = records_for(db, kind, parent.id)
    prev = effective_record(rows, version_id)
    resolved = checklists.resolve(db, kind, _category_of(db, kind, parent))
    text_by_key = {i["key"]: i.get("text", "") for i in resolved["items"]}

    blocked: list[str] = []
    merged: dict[str, dict] | None = None
    if items is not None:
        merged = {i["key"]: dict(i) for i in (prev.items or [])} if prev else {}
        now = _utcnow().isoformat()
        for item in items:
            key = str(item.get("key", "")).strip()
            result = str(item.get("result", "")).strip()
            if not key or result not in RESULTS:
                blocked.append(f"{key or '?'}: bad result {result!r}")
                continue
            if result == "flagged" and not str(item.get("note") or "").strip():
                # A flag IS the second-pass worklist entry — without a note the
                # next person has no idea what to fix.
                blocked.append(f"{key}: flagged needs a note saying what is wrong")
                continue
            old = merged.get(key)
            # A key the checklist does not define is a CUSTOM check — one this
            # part needed and no checklist anticipated. It is legal (both the
            # agent and the review card can add one), but it has to carry its
            # own text: the record is the only place that text will ever live,
            # and without it the item renders as a bare key forever.
            text = str(item.get("text") or text_by_key.get(key)
                       or (old or {}).get("text") or "").strip()
            if not text:
                blocked.append(f"{key}: not on the checklist, so it needs its own text")
                continue
            if old is not None and TIER.get(old.get("actor_type", "machine"), 0) > TIER.get(actor_type, 0):
                blocked.append(f"{key}: already answered by {old.get('actor_type')}")
                continue
            entry = {
                "key": key,
                "text": text,
                "result": result,
                "note": (item.get("note") or "").strip() or None,
                "actor": actor,
                "actor_type": actor_type,
                "at": now,
            }
            # A skip may carry a structured reason ("html_datasheet",
            # "no_land_pattern", …) so the health tab can aggregate WHY things
            # are unverifiable instead of re-reading 84 free-text notes. Free
            # text stays in `note`; the code is optional and skip-only.
            reason = str(item.get("reason") or "").strip()
            if reason and result == "skipped":
                entry["reason"] = reason[:40]
            merged[key] = entry

    # A verification — whoever wrote it — answers any open agent request for
    # this subject. Marking rather than deleting keeps "when did I ask" cheap.
    for req in db.query(M.ReviewRequest).filter_by(
            subject_kind=kind, subject_id=parent.id, done_at=None):
        req.done_at = _utcnow()
        req.done_by = actor

    record = M.ReviewRecord(
        subject_kind=kind,
        subject_id=parent.id,
        subject_version_id=version_id,
        kind=record_kind,
        carried_from_id=prev.id if prev else None,
        checklist_version_id=resolved["checklist_version_id"],
        # The FULL resolved list, category-scoped items included — see the
        # column comment on M.ReviewRecord.checklist_items.
        checklist_items=list(resolved["items"]),
        items=list(merged.values()) if merged is not None else None,
        note=(note or "").strip() or None,
        created_by=actor,
        actor_type=actor_type,
    )
    db.add(record)
    db.flush()
    db.add(M.AuditLog(
        actor=actor, action="review.check", entity_type=f"{kind}_version",
        entity_id=str(version_id),
        details={"subject": getattr(parent, "name", parent.id), "record_id": record.id,
                 "actor_type": actor_type,
                 "items": len(items) if items is not None else None,
                 "blocked": blocked or None},
    ))
    state = state_from_record(record, resolved["items"] if record.items is not None else None)
    return {"record": record_json(record), "state": state, "blocked": blocked}


def machine_check_on_publish(db: Session, kind: str, parent, version,
                             comp: M.Component | None = None) -> dict | None:
    """Run the validator on a just-published version and record the answers.

    Called inside the publish transaction. Never raises — a broken validator
    must not block a publish; it logs into the audit trail instead.
    """
    from . import validator

    try:
        items = validator.validate(db, kind, version, comp)
    except Exception as e:  # noqa: BLE001 — validation must never block a publish
        db.add(M.AuditLog(actor="validator", action="review.machine_error",
                          entity_type=f"{kind}_version", entity_id=str(version.id),
                          details={"error": f"{type(e).__name__}: {e}"}))
        return None
    return record_check(db, kind, parent, version.id, actor="validator",
                        actor_type="machine", items=items, note=None)


def carry_geometry(db: Session, kind: str, parent, old_version, new_version) -> dict | None:
    """Carry the verification record across a geometry publish when nothing
    material changed or the change was waived — same precedence as the
    sign-off carry (`signoff.geometry_carries`)."""
    if old_version is None or new_version is None or old_version.id == new_version.id:
        return None
    rows = records_for(db, kind, parent.id)
    prev = effective_record(rows, old_version.id)
    if prev is None or effective_record(rows, new_version.id) is not None:
        return None
    if new_version.recheck_required is True:
        return {"carried": False, "reason": "the approver asked for a new verification"}
    same = bool(old_version.material_sha) and old_version.material_sha == new_version.material_sha
    if not same and new_version.recheck_required is not False:
        return {"carried": False, "reason": "the drawing changed"}

    record = M.ReviewRecord(
        subject_kind=kind, subject_id=parent.id, subject_version_id=new_version.id,
        kind="carry", carried_from_id=prev.id,
        checklist_version_id=prev.checklist_version_id,
        checklist_items=prev.checklist_items,  # a carry measures against the same list
        items=prev.items, note=(
            f"Carried from v{old_version.version_no}: "
            + ("nothing that reaches the board changed"
               if same else "the change was waived as minor")),
        created_by="review", actor_type=prev.actor_type,
    )
    db.add(record)
    db.flush()
    db.add(M.AuditLog(actor="review", action="review.carry",
                      entity_type=f"{kind}_version", entity_id=str(new_version.id),
                      details={"subject": parent.name, "from_version": old_version.version_no,
                               "to_version": new_version.version_no,
                               "record_id": record.id}))
    return {"carried": True, "record_id": record.id}


def carry_component(db: Session, comp: M.Component, old_cv, new_cv) -> dict | None:
    """Carry a component's own verification record across a data-preserving
    publish (repoints, non-material edits). Uses the sign-off leg rules."""
    if old_cv is None or new_cv is None or old_cv.id == new_cv.id:
        return None
    rows = records_for(db, "component", comp.id)
    prev = effective_record(rows, old_cv.id)
    if prev is None or effective_record(rows, new_cv.id) is not None:
        return None
    ok, why = signoff.data_carries(old_cv, new_cv)
    if not ok:
        return {"carried": False, "reason": f"component data: {why}"}

    record = M.ReviewRecord(
        subject_kind="component", subject_id=comp.id, subject_version_id=new_cv.id,
        kind="carry", carried_from_id=prev.id,
        checklist_version_id=prev.checklist_version_id,
        checklist_items=prev.checklist_items,  # a carry measures against the same list
        items=prev.items,
        note=f"Carried from v{old_cv.version_no}: component data unchanged",
        created_by="review", actor_type=prev.actor_type,
    )
    db.add(record)
    db.flush()
    db.add(M.AuditLog(actor="review", action="review.carry",
                      entity_type="component_version", entity_id=str(new_cv.id),
                      details={"subject": comp.name, "from_version": old_cv.version_no,
                               "to_version": new_cv.version_no, "record_id": record.id}))
    return {"carried": True, "record_id": record.id}


def revoke(db: Session, record: M.ReviewRecord, actor: str, reason: str) -> M.ReviewRecord:
    record.revoked_at = _utcnow()
    record.revoked_by = actor
    record.revoke_reason = reason
    return record
