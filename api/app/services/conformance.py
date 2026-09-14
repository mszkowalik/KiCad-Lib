"""The machine tier, computed on read instead of recorded on publish.

Machine answers used to be written into `ReviewRecord` like any other
verification. Measured 2026-09-14, that single choice explains most of the
review axis's awkwardness:

- **2,442 of 6,819 stored answers** were machine answers — recomputable in
  milliseconds, yet written on every publish;
- **675 carry records** existed largely to move them across version boundaries
  that had not affected them;
- publishing `cmp.datasheet_text` moved **418 components** from checked to
  partial in one go, because a stored answer cannot backfill;
- "Re-run auto checks" and "Apply to existing parts" were built to paper over
  the staleness that follows.

None of it is a verification. Nobody looked at anything — the code did, and it
will say the same thing again on demand. So conformance is DERIVED here, and the
row in `models.Conformance` is a cache in exactly the sense
`FootprintVersion.material_sha` is: safe to be missing, safe to delete, never
carried, never migrated.

**`digest` is what makes the cache honest.** It covers the resolved checklist,
the subject's facts and the live exceptions — everything the answers depend on.
Edit a check and every digest in the library changes, so the next read
recomputes. Nothing has to remember to invalidate anything, and the 418-component
cliff cannot happen again.

**Exceptions are applied here, as an overlay.** They are not written into
anything, which is why revoking one takes effect on the next read rather than
needing a record to be rewritten — and why the old "an answer written by an
exception has to die with it" problem simply does not arise.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M
from . import checklists, exceptions

#: Answers the machine may produce. `flagged` is deliberately absent: it means
#: "a person verified this and found it wrong", which no computation can say.
RESULTS = ("checked", "na", "failed")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _digest(resolved: dict, facts: dict | None, exc_ids: list[int]) -> str:
    """Everything the machine answers depend on, in one string.

    `facts` is read through its own keys rather than wholesale: it is a lazy
    mapping, and iterating it would compute every derived fact on every digest —
    turning a cache key into the expensive thing it exists to avoid.
    """
    used = sorted({f for i in resolved["items"]
                   for f in list((i.get("when") or {})) + ([i["assert"]["fact"]]
                                                           if i.get("assert") else [])})
    payload = {
        "checklist": resolved.get("checklist_version_id"),
        "items": [[i.get("key"), i.get("variant"), i.get("severity"), i.get("params"),
                   i.get("assert"), i.get("when")] for i in resolved["items"]],
        "facts": {f: (facts or {}).get(f) for f in used},
        "exceptions": sorted(exc_ids),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def evaluate(db: Session, kind: str, parent, version) -> tuple[list[dict], list[dict], str]:
    """Everything computed for this version. Returns (items, excused, digest).

    ``items`` is the machine tier. ``excused`` is the JUDGMENT items a standing
    exception closes — computed here rather than written into a record, because
    an exception is a decision about the PART and a record is about one version.
    Writing it meant granting an exception on an open judgment item did nothing
    at all until some unrelated save picked it up (measured 2026-09-14).

    Never raises: a broken validator must not break a page that merely wants to
    show a state. It reports the failure as an item instead, which is visible
    rather than silent.
    """
    from . import validator

    facts = checklists.subject_facts(db, kind, parent, version.id)
    cat = None
    if kind == "component":
        cat = version.category_id
    resolved = checklists.resolve(db, kind, cat, facts)
    by_key = {i["key"]: i for i in resolved["items"]}
    enabled = {k for k, i in by_key.items() if i.get("machine")}
    live = exceptions.live_for(db, kind, parent.id, facts)
    digest = _digest(resolved, facts, [e.id for e in live.values()])

    try:
        comp = parent if kind == "component" else None
        items = validator.validate(db, kind, version, comp,
                                   checklist=by_key, only=enabled, facts=facts)
    except Exception as e:  # noqa: BLE001 — a broken check must not break a read
        items = [{"key": "validator", "result": "failed",
                  "note": f"the validator raised {type(e).__name__}: {e}"}]

    out: list[dict] = []
    for item in items:
        spec = by_key.get(item["key"], {})
        entry = dict(item)
        entry["severity"] = checklists.severity_of(spec)
        entry["text"] = spec.get("text", item["key"])
        # A standing exception is an OVERLAY, never a write. Revoking one takes
        # effect on the next read, and the finding it replaces is kept beside
        # it rather than being lost.
        exc = live.get((item["key"], spec.get("variant") or ""))
        if exc is not None and item["result"] == "failed":
            entry = {**entry, "result": "na", "reason": exc.reason, "note": exc.note,
                     "exception_id": exc.id,
                     "superseded": {"result": item["result"], "note": item.get("note")}}
        out.append(entry)

    # The same overlay, for the items no machine answers. A judgment item an
    # exception closes is not work for anybody, so it leaves the denominator
    # rather than being counted as answered — `state_from_record` reports it
    # separately, and a part closed by exceptions must never read like a part
    # that somebody judged.
    machine_keys = {i["key"] for i in items}
    excused: list[dict] = []
    for spec in resolved["items"]:
        if spec.get("machine") or spec["key"] in machine_keys:
            continue
        exc = live.get((spec["key"], spec.get("variant") or ""))
        if exc is None:
            continue
        excused.append({
            "key": spec["key"], "variant": spec.get("variant") or None,
            "text": spec.get("text", spec["key"]),
            "result": "na", "reason": exc.reason, "note": exc.note,
            "actor": exc.created_by, "actor_type": exc.actor_type,
            "at": exc.created_at.isoformat() if exc.created_at else None,
            "exception_id": exc.id,
            "severity": checklists.severity_of(spec),
        })
    return out, excused, digest


def get(db: Session, kind: str, parent, version) -> tuple[list[dict], list[dict]]:
    """This version's machine answers and excused judgment items, from the cache
    when it is still valid.

    Writes the cache as a side effect. The caller owns the transaction; a read
    surface that never commits simply recomputes next time, which is correct for
    a cache and is why nothing here is careful about committing.
    """
    if version is None:
        return [], []
    row = (db.query(M.Conformance)
           .filter_by(subject_kind=kind, subject_version_id=version.id).first())
    items, excused, digest = evaluate(db, kind, parent, version)
    if row is None:
        db.add(M.Conformance(subject_kind=kind, subject_version_id=version.id,
                             digest=digest, items=items, excused=excused))
    elif row.digest != digest:
        row.digest = digest
        row.items = items
        row.excused = excused
        row.computed_at = _utcnow()
    return items, excused


def cached(db: Session, kind: str, version_id: int | None) -> tuple[list[dict] | None, list[dict]]:
    """Whatever the cache holds, WITHOUT validating the digest.

    For list surfaces, where re-running the validator once per row is the
    difference between a page and a minute. A stale row is still a better answer
    than no answer, and the detail view recomputes.

    Returns ``(items, excused)``. ``items`` is None when the cache has no row —
    which reads as "not evaluated", never as "conforms". ``excused`` is empty in
    that case, which is the safe way to be wrong: an item wrongly counted as
    open is visible work, an item wrongly excused is a question nobody asks.
    """
    if version_id is None:
        return None, []
    row = (db.query(M.Conformance)
           .filter_by(subject_kind=kind, subject_version_id=version_id).first())
    if row is None:
        return None, []
    return list(row.items or []), list(row.excused or [])


def summary(items: list[dict] | None) -> dict:
    """Counts a list surface can print without reading every item."""
    items = items or []
    failed = [i for i in items
              if i.get("result") == "failed" and i.get("severity", "error") != "warning"]
    warned = [i for i in items
              if i.get("result") == "failed" and i.get("severity", "error") == "warning"]
    return {
        "evaluated": bool(items),
        "conforms": not failed,
        "failed": len(failed),
        "warnings": len(warned),
        "failing_keys": [i["key"] for i in failed],
    }


def warm_in_background(kinds: tuple[str, ...] = ("component", "symbol", "footprint")) -> None:
    """Re-evaluate the library on its own thread, after something INVALIDATED it.

    A checklist save changes the digest of every subject it reaches, and a
    granted exception changes one. Until 2026-09-14 nothing acted on that: a
    list surface reads `cached` WITHOUT validating the digest, and a detail read
    recomputed but never committed, so the whole library stayed stale until the
    next restart. Editing a check and seeing nothing change is the opposite of
    what `0017` promises.

    Fire-and-forget, exactly like the startup warm-up: nothing depends on it
    finishing, it is safe to run twice, and a failure leaves a stale cache
    rather than a broken request.
    """
    import threading

    from ..db import SessionLocal

    def _run() -> None:
        db = SessionLocal()
        try:
            warm_all(db, kinds)
        except Exception:  # noqa: BLE001 — a warm-up must never break a request
            pass
        finally:
            db.close()

    threading.Thread(target=_run, daemon=True).start()


def warm_all(db: Session, kinds: tuple[str, ...] = ("component", "symbol", "footprint")) -> dict:
    """Evaluate every live version whose cache is missing or stale.

    Runs in a background thread from startup, for the same reason the
    `material_sha` backfill does: a list surface reads the cache and a cold one
    reports "not evaluated", which is honest but useless. Nothing depends on it
    finishing — every read recomputes what it needs — so it is safe to kill,
    safe to run twice, and safe to fail.
    """
    done = {"component": 0, "symbol": 0, "footprint": 0, "unchanged": 0}
    for kind, model in (("component", M.Component), ("symbol", M.Symbol),
                        ("footprint", M.Footprint)):
        if kind not in kinds:
            continue
        for parent in db.query(model).filter(model.current_version_id.isnot(None)).all():
            version = next((v for v in parent.versions
                            if v.id == parent.current_version_id), None)
            if version is None:
                continue
            row = (db.query(M.Conformance)
                   .filter_by(subject_kind=kind, subject_version_id=version.id).first())
            before = row.digest if row is not None else None
            try:
                get(db, kind, parent, version)
            except Exception:  # noqa: BLE001 — one bad subject must not stop the sweep
                continue
            row = (db.query(M.Conformance)
                   .filter_by(subject_kind=kind, subject_version_id=version.id).first())
            if row is not None and row.digest == before:
                done["unchanged"] += 1
            else:
                done[kind] += 1
        db.commit()
    return done
