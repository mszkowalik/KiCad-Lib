"""The review axis: cumulative checklist verifications on published versions.

Publishing and reviewing are separate axes (user design 2026-08-23). Versions
publish immediately; this module records who has verified each version against
its documentation and derives every state from the records:

- ``unreviewed`` — no record on the version.
- ``failed``     — the newest record carries at least one ``failed`` item
                   (a machine check found a concrete violation).
- ``partial``    — checklist items are still unanswered.
- ``checked``    — every applicable item answered ``checked`` or ``na``.

``skipped`` was RETIRED on 2026-09-13 (owner decision, decision record 0011).
It meant "applies, but I could not verify it", which read to everybody — its
own designer included — as "does not apply", the job ``na`` already does. An
item nobody can verify is now simply left UNMARKED, which produces the same
``partial`` state it always did. Rows written before that date keep the value
and are read here as unanswered; nothing rewrites history. ``na`` carries the
structured reason instead, and now requires one from an agent or a human.

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
from . import checklists, exceptions, signoff

KINDS = ("component", "symbol", "footprint")
# `failed` = a machine rule violation; `flagged` = an agent or human verified
# an item and found it WRONG, recorded without fixing it (the second-pass
# list, user design 2026-08-23). Both read as state "failed" ("issues").
RESULTS = ("checked", "na", "failed", "flagged")
# Accepted on READ so 2026-09-13's retired value still renders; never written.
LEGACY_RESULTS = ("skipped",)
# `na` means "does not apply to this part" and an agent or a human must say
# WHICH way it does not apply, as a code the health tab can count. The machine
# tier is exempt: `services/validator.py` answers `na` in a dozen places ("no
# SMD pads", "no vias") with a free-text note and no code, and requiring one
# there would fail every publish.
NA_REASONS = ("feature_absent", "kind_exempt", "waived", "other")
TIER = {"machine": 0, "agent": 1, "human": 2}

#: How long a written explanation may be, in characters. Enforced where the
#: text is WRITTEN, not where it is shown.
#:
#: Measured 2026-09-14 over 21,064 stored notes:
#:
#: ==========  ======  ========  ======  ======
#: writer      count   median    p90     max
#: ==========  ======  ========  ======  ======
#: human           13       31      115     115
#: machine      1,304       17       27      93
#: agent       19,747      367    1,055   3,316
#: ==========  ======  ========  ======  ======
#:
#: An agent writes twelve times what a person writes, and the tail runs to
#: 3,316 characters — about 500 words on ONE checklist item. Nobody reads that,
#: so the finding inside it is lost exactly as surely as if it had not been
#: written. A limit is the only thing that makes the habit change: 45% of
#: current agent notes exceed `ITEM_NOTE`, which is the point of the number.
#:
#: The item note is the largest because it is where a real finding goes. A pass
#: note is a citation and a revoke reason is one sentence, so both are smaller.
#: A custom item's `text` is a check SENTENCE and has to stay one line.
TEXT_LIMITS = {
    "item_note": 400,      # ~3 sentences. What is wrong, and how it was found.
    "item_text": 200,      # a custom check's question, in one line
    "record_note": 300,    # what documentation this pass used
    "revoke_reason": 300,
}

#: What to write instead. A bare "too long" tells somebody to cut without
#: telling them what to keep, and the second attempt comes back nearly as long.
_ADVICE = {
    "item_note": ("Say what is wrong and how you know, in a few sentences — "
                  "\"pad pitch 0.5 mm, datasheet p4 table 2 says 0.65 mm\"."),
    "item_text": "A check is one question, in one line.",
    "record_note": ("This is a CITATION of what the pass used, not a summary of "
                    "the findings — each of those has its own note."),
    "revoke_reason": "One sentence saying why it is being taken back.",
}


def too_long(value: str | None, limit_key: str) -> str | None:
    """The message to report, or None when the text fits.

    Reports the ACTUAL length beside the limit: "too long" with no number
    leaves the writer guessing how much to cut, and an agent guessing tends to
    resend something nearly as long.
    """
    text = (value or "").strip()
    limit = TEXT_LIMITS[limit_key]
    if len(text) <= limit:
        return None
    return f"{len(text)} characters, and the limit is {limit}. {_ADVICE[limit_key]}"
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


def itemised_record(rows: list[M.ReviewRecord], version_id: int | None) -> M.ReviewRecord | None:
    """The newest non-revoked record on one version that HAS an item breakdown.

    A one-click human confirmation is stored with `items=None` on purpose — it
    means "I vouch for this whole subject", and `state_from_record` reads that
    sentinel as a full check without measuring completeness. The side effect is
    that the effective record then carries no per-item answers, so a review card
    reading `effective_record` alone rendered an EMPTY checklist the moment
    somebody pressed Mark checked, throwing away the visible evidence of what
    the machine and the agent had actually verified (user report 2026-08-25).

    So the state still comes from `effective_record` and only the ITEMS come
    from here. Never merge the two into one record: repopulating `items` on the
    confirmation would make `state_from_record` measure it, and a subject the
    person vouched for while an item was still unanswered would flip from
    checked back to partial.
    """
    if version_id is None:
        return None
    return next(
        (r for r in reversed(rows)
         if r.subject_version_id == version_id and r.revoked_at is None and r.items is not None),
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


def _weakest_actor(entries: list[dict]) -> str | None:
    """The LOWEST tier among these entries, or None for an empty list.

    Weakest, not strongest, because this answers "how much is this subject
    vouched for". One agent decision among ten human ones still means an agent
    closed a question nobody re-read.
    """
    tiers = [TIER[e["actor_type"]] for e in entries if e.get("actor_type") in TIER]
    if not tiers:
        return None
    return next(k for k, v in TIER.items() if v == min(tiers))


def state_from_record(record: M.ReviewRecord | None, checklist_items: list[dict] | None,
                      conformance: list[dict] | None = None,
                      excused: list[dict] | None = None) -> dict:
    """Derive one version's state: the JUDGMENT record, plus computed conformance.

    ``checklist_items`` is the resolved checklist to measure completeness
    against — pass the record's own checklist version items so a later
    checklist edit never silently flips history; the caller separately reports
    how far the current checklist has moved on.

    Two things changed on 2026-09-14 and both are load-bearing:

    **Machine answers stored in the record are IGNORED.** The machine tier is
    computed now (`services/conformance.py`), so a stored one is history — 2,442
    of them, written before the change. Counting both would double-count, and
    the stored copy is the stale one. They are deliberately not deleted: they are
    what a past record said, and rewriting history is the one thing this axis
    never does.

    **Completeness is measured over JUDGMENT items only.** A machine item is
    always answered, by definition, so counting it as "unanswered" was only ever
    an artefact of nobody having published since the check was added. That is
    what moved 418 components to partial in one publish, and it cannot happen
    again.

    ``conformance`` is this version's computed machine answers, or None for a
    caller that has not got them — a list surface reading from cache before the
    cache is warm. None means "not evaluated", never "conforms".

    ``excused`` is the judgment items a standing exception closes, also computed
    (`services/conformance.py`). **They leave the denominator rather than
    counting as answered.** An exception says the question is not about this
    part; it does not say anybody looked. A part whose whole checklist is
    excused must not read like a part somebody judged, which is why `excused`
    is reported as its own number instead of being folded into `answered`.
    """
    from . import conformance as conformance_svc

    conf = conformance_svc.summary(conformance) if conformance is not None else None
    conf_failed = conf["failed"] if conf else 0
    conf_warnings = conf["warnings"] if conf else 0
    excused = list(excused or [])
    excused_keys = {e.get("key") for e in excused}

    if record is None:
        judgment = [i["key"] for i in (checklist_items or [])
                    if not i.get("machine") and i["key"] not in excused_keys]
        # Every judgment item excused and none judged is still a decided
        # subject: an exception carries an actor, a date and a note, so the
        # provenance comes from the weakest of them rather than reading as a
        # verification nobody made.
        prov = _weakest_actor(excused) if (excused and not judgment) else None
        return {"state": "failed" if conf_failed else
                ("unreviewed" if judgment else "checked"),
                "provenance": prov, "record_id": None,
                "answered": 0, "total": len(judgment), "skipped": 0,
                "failed": conf_failed, "flagged": 0, "warnings": conf_warnings,
                "excused": len(excused),
                "conforms": None if conf is None else conf["conforms"],
                "unanswered": judgment}

    if record.items is None:
        # One-click human confirmation: no item breakdown, full check. It
        # vouches for the JUDGMENT, not for conformance — a person cannot
        # confirm away a machine failure, and pretending otherwise would let one
        # click hide a defect the code can still see.
        return {"state": "failed" if conf_failed else "checked",
                "provenance": "human", "record_id": record.id,
                "answered": 0, "total": 0, "skipped": 0,
                "failed": conf_failed, "flagged": 0, "warnings": conf_warnings,
                "excused": len(excused),
                "conforms": None if conf is None else conf["conforms"],
                "unanswered": []}

    # Machine answers in the record are history; conformance is computed.
    by_key = {i.get("key"): i for i in record.items
              if i.get("actor_type") != "machine"}
    # A WARNING-level failure is worth seeing and does not make the subject
    # failed (2026-09-14). Without the split, every check moved out of the
    # convention skills would turn the library red on the day it landed, which
    # is why four of them shipped switched off instead of on.
    # An excused key cannot still be a finding: the decision closed it. Without
    # this an old `flagged` answer would hold the subject at "issues" for ever
    # while the card showed the item as excused.
    broke = [k for k, i in by_key.items()
             if i.get("result") in ("failed", "flagged") and k not in excused_keys]
    failed = [k for k in broke if by_key[k].get("severity", "error") != "warning"]
    warnings = [k for k in broke if by_key[k].get("severity", "error") == "warning"]
    flagged = [k for k, i in by_key.items() if i.get("result") == "flagged"]
    # Pre-2026-09-13 rows only. `skipped` is read as "nobody has answered this
    # yet", which is the state it always produced, so retiring the value moved
    # no subject between states.
    legacy_skipped = [k for k, i in by_key.items() if i.get("result") == "skipped"]
    # An excused item leaves the denominator entirely. It is not open work and
    # it is not an answer — it is a recorded decision that the question is not
    # about this part.
    expected = [i["key"] for i in (checklist_items or [])
                if not i.get("machine") and i["key"] not in excused_keys]
    real = {k for k, i in by_key.items() if i.get("result") in RESULTS}
    # A custom key answered `skipped` is not in `expected`, so it has to be
    # added explicitly or a retired answer on one would read as fully checked.
    unanswered = ([k for k in expected if k not in real]
                  + [k for k in legacy_skipped if k not in expected])
    answered = sum(1 for i in by_key.values()
                   if i.get("result") in ("checked", "na") and i.get("key") not in excused_keys)

    if failed or conf_failed:
        state = "failed"
    elif unanswered:
        state = "partial"
    else:
        state = "checked"
    return {"state": state, "provenance": _provenance(record), "record_id": record.id,
            "answered": answered, "total": max(len(expected), len(by_key)),
            # legacy only: the count of retired `skipped` answers still stored
            "skipped": len(legacy_skipped), "failed": len(failed) + conf_failed,
            "flagged": len(flagged), "warnings": len(warnings) + conf_warnings,
            "excused": len(excused),
            "conforms": None if conf is None else conf["conforms"],
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
    return list(_checklist_version_items(db, record.checklist_version_id))


# Checklist VERSIONS are immutable — a save publishes a new row rather than
# editing one — so their item lists can be memoised for the life of the
# process. This is not a micro-optimisation: `db.get` looked free because the
# identity map should serve the repeat, but that map holds WEAK references and
# `_checklist_items_of` keeps no reference to the object, so every one of the
# 857 pre-snapshot records re-queried. Measured 2026-08-24 on the review queue:
# 299 of its 318 SQL round trips were the same three rows.
_CHECKLIST_ITEMS: dict[int, list[dict]] = {}


def _checklist_version_items(db: Session, version_id: int) -> list[dict]:
    cached = _CHECKLIST_ITEMS.get(version_id)
    if cached is None:
        cv = db.get(M.ChecklistVersion, version_id)
        cached = list(cv.items or []) if cv else []
        _CHECKLIST_ITEMS[version_id] = cached
    return cached


def version_state(db: Session, kind: str, subject_id: int, version_id: int | None,
                  rows: list[M.ReviewRecord] | None = None,
                  conformance: list[dict] | None = None) -> dict:
    """One subject's state. Pass `conformance` when you have it; a caller that
    does not gets the judgment half and `conforms: None`, which reads as "not
    evaluated" and never as "conforms"."""
    from . import conformance as conformance_svc

    rows = records_for(db, kind, subject_id) if rows is None else rows
    record = effective_record(rows, version_id)
    excused: list[dict] = []
    if conformance is None:
        conformance, excused = conformance_svc.cached(db, kind, version_id)
    return state_from_record(record, _checklist_items_of(db, record), conformance, excused)


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


def states_for_components(db: Session, comps: list[M.Component],
                          cvs: dict[int, M.ComponentVersion | None] | None = None) -> dict[int, dict]:
    """`component_effective` over many components with bulk queries.

    List surfaces (browse, queue, project review) call this; per-row loops of
    `db.get` would repeat the kicad_http chooser mistake.

    Pass `cvs` — a `{component_id: live version}` map — when the caller already
    loaded the live versions (`routers/util.components_with_current` returns
    exactly that). Without it this walks `c.versions`, which on a component
    loaded WITHOUT its history lazy-loads the whole history back, one component
    at a time, undoing that loader's entire point.
    """
    if cvs is None:
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

    # Conformance from the CACHE, in one query per kind. Evaluating it here
    # would be ~20 ms per subject — nine seconds for this library — which is the
    # whole reason `models.Conformance` exists. A row the cache has not got
    # yields `conforms: None`, which reads as "not evaluated" and never as
    # "conforms"; the detail view recomputes.
    def _conf(kind: str, version_ids: set[int]) -> dict[int, tuple[list[dict], list[dict]]]:
        if not version_ids:
            return {}
        return {r.subject_version_id: (list(r.items or []), list(r.excused or []))
                for r in db.query(M.Conformance).filter(
                    M.Conformance.subject_kind == kind,
                    M.Conformance.subject_version_id.in_(version_ids))}

    comp_conf = _conf("component", {cv.id for cv in cvs.values() if cv})
    sym_conf = _conf("symbol", sym_ver_ids)
    fp_conf = _conf("footprint", fp_ver_ids)

    out: dict[int, dict] = {}
    for c in comps:
        cv = cvs.get(c.id)
        if cv is None:
            out[c.id] = {"state": "unreviewed", "parts": {}, "blockers": [], "provenance": None}
            continue
        crec = effective_record(comp_rows.get(c.id, []), cv.id)
        c_items, c_exc = comp_conf.get(cv.id, (None, []))
        parts = {"component": state_from_record(
            crec, _checklist_items_of(db, crec), c_items, c_exc)}
        if cv.symbol_version_id and cv.symbol_version_id in sym_parent:
            rec = effective_record(sym_rows.get(sym_parent[cv.symbol_version_id], []),
                                   cv.symbol_version_id)
            s_items, s_exc = sym_conf.get(cv.symbol_version_id, (None, []))
            parts["symbol"] = state_from_record(rec, _checklist_items_of(db, rec),
                                                s_items, s_exc)
        if cv.footprint_version_id and cv.footprint_version_id in fp_parent:
            rec = effective_record(fp_rows.get(fp_parent[cv.footprint_version_id], []),
                                   cv.footprint_version_id)
            f_items, f_exc = fp_conf.get(cv.footprint_version_id, (None, []))
            parts["footprint"] = state_from_record(rec, _checklist_items_of(db, rec),
                                                   f_items, f_exc)
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


# Results worth remembering after they are overwritten: a defect somebody found
# and a check the machine failed. A plain "checked" or "na" is not a finding, so
# it never displaces one.
_NOTABLE_RESULTS = ("flagged", "failed")


def _answer_snapshot(entry: dict) -> dict:
    """The part of an answer worth keeping once it has been replaced."""
    return {k: entry.get(k) for k in ("result", "note", "actor", "actor_type", "at", "reason")
            if entry.get(k) is not None}


def _notable(candidate: dict | None, inherited: dict | None) -> dict | None:
    """Of the answer just replaced and the one it had itself replaced, the one a
    later reader needs to see."""
    for pick in (candidate, inherited):
        if pick is not None and pick.get("result") in _NOTABLE_RESULTS:
            return pick
    return candidate or inherited


def record_check(db: Session, kind: str, parent, version_id: int, actor: str,
                 actor_type: str, items: list[dict] | None, note: str | None = None,
                 record_kind: str = "check", close_requests: bool = True) -> dict:
    """Write a verification record, merged on top of the previous one.

    ``items=None`` with ``actor_type='human'`` is the one-click confirmation.
    Otherwise every item is ``{key, result, note?}`` and the merge enforces the
    tier rule: an answer already given by a HIGHER tier is kept, and the
    refused keys are reported back rather than silently dropped.
    """
    assert kind in KINDS
    rows = records_for(db, kind, parent.id)
    # The pass note is a CITATION — "checked against the SMAJ datasheet, p4" —
    # not a place to restate the findings, which already have their own notes.
    over = too_long(note, "record_note")
    if over is not None:
        raise ValueError(f"the note on this verification is {over}")
    # Seeded from the newest record that HAS an item breakdown, not from the
    # effective one.
    #
    # A one-click "Mark checked" is stored with `items=None` on purpose — it
    # vouches for the whole subject and records no breakdown. Seeding from the
    # effective record meant that the moment somebody pressed it, the NEXT save
    # started from an empty dict and silently discarded every answer underneath.
    # Reproduced on `PESD1CAN,215`: 12 answers down to 1 (2026-08-25).
    #
    # The STATE still comes from `effective_record` — `state_from_record` reads
    # the `items=None` sentinel as a full check. Only the items come from here,
    # which is the same split `_detail` makes for display.
    prev = itemised_record(rows, version_id)
    # Resolved FOR THIS SUBJECT: a `when` predicate is judged against the part
    # in hand, so an item that is not about parts like this one is not expected
    # of it and never reaches the record.
    facts = checklists.subject_facts(db, kind, parent, version_id)
    resolved = checklists.resolve(db, kind, _category_of(db, kind, parent), facts)
    text_by_key = {i["key"]: i.get("text", "") for i in resolved["items"]}
    switched_off = {i["key"] for i in resolved["disabled"]}

    blocked: list[str] = []
    merged: dict[str, dict] | None = None
    if items is not None:
        merged = {i["key"]: dict(i) for i in (prev.items or [])} if prev else {}
        # A check switched OFF in the checklist loses the answer it already had.
        # Records are cumulative, so without this a `failed` answer recorded
        # before somebody switched the check off would be copied forward for
        # ever and hold the subject at "issues" — switching a check off would
        # stop new failures and leave the old one on screen with no way to
        # clear it. The audit trail and the superseded record keep the history.
        for key in switched_off & set(merged):
            del merged[key]
        # LEGACY ONLY. Exceptions stopped writing answers on 2026-09-14 — they
        # are applied by `conformance.evaluate` now — but rows written before
        # that carry `exception_id`, and one whose exception has since been
        # revoked would otherwise be copied forward for ever. Nothing writes a
        # new row of this shape, so this loop empties itself over time.
        live_ids = {e.id for e in exceptions.live_for(db, kind, parent.id, facts).values()}
        for key, entry in list(merged.items()):
            exc_id = entry.get("exception_id")
            if exc_id is not None and exc_id not in live_ids:
                del merged[key]
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
            # Length is checked at the WRITE, for every tier. The machine's own
            # notes are 17 characters and a person's are 31; an agent's median
            # is 367 and its tail is 3,316, which is where this came from.
            over = too_long(item.get("note"), "item_note")
            if over is not None:
                blocked.append(f"{key}: the note is {over}")
                continue
            over = too_long(item.get("text"), "item_text")
            if over is not None:
                blocked.append(f"{key}: the check's own wording is {over}")
                continue
            if key in switched_off:
                # Not a custom item: this key IS on the checklist, switched off
                # for this subject. Storing it anyway would put the check back
                # on screen for one part and make "off" mean nothing.
                blocked.append(f"{key}: switched off in the checklist for this subject")
                continue
            reason = str(item.get("reason") or "").strip()
            if result == "na" and actor_type != "machine":
                # `na` IS a standing exception now, not an answer (2026-09-14).
                #
                # The two said the same thing and only one of them lasted. An
                # `na` answer lived on ONE version, so a pad move refused the
                # carry and took the decision away: measured that day, the
                # library held 314 live `na` answers, 312 of them written by
                # agents, not one with a reason recorded, every one due to
                # expire at the next version bump — while the table built to
                # hold such decisions held ZERO rows.
                #
                # So this path GRANTS one instead of writing an answer. The
                # item leaves the checklist denominator through
                # `conformance.evaluate`, not through a record, which is what
                # makes granting one on an item nobody has answered yet work at
                # all.
                if reason not in NA_REASONS:
                    blocked.append(
                        f"{key}: na needs a reason, one of {', '.join(NA_REASONS)}")
                    continue
                note = str(item.get("note") or "").strip()
                if not note:
                    # The note is the ONLY place the reason will ever live, and
                    # this answer now outlives the version it was written on.
                    blocked.append(
                        f"{key}: na is a standing exception now, so it needs a note "
                        f"saying why — it outlives this version")
                    continue
                over = too_long(note, "item_note")
                if over is not None:
                    blocked.append(f"{key}: the exception note is {over}")
                    continue
                if (key, "") in exceptions.live_for(db, kind, parent.id, facts):
                    continue  # already decided; re-stating it is not a new decision
                pin = exceptions.DEFAULT_PIN.get(kind, ())
                depends_on = {f: facts.get(f) for f in pin if facts.get(f) is not None}
                exceptions.grant(
                    db, kind, parent, key, reason=reason, note=note,
                    actor=actor, actor_type=actor_type, depends_on=depends_on)
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
            # The severity the check carried WHEN IT WAS ANSWERED, stamped on
            # the answer. The state has to distinguish an error from a warning,
            # and re-reading today's checklist to find out would let an edit
            # silently rewrite what a past record means — the same reason the
            # record snapshots the list it was measured against.
            severity = checklists.severity_of(
                next((x for x in resolved["items"] if x["key"] == key), {}))
            entry = {
                "key": key,
                "text": text,
                "result": result,
                "severity": severity,
                "note": (item.get("note") or "").strip() or None,
                "actor": actor,
                "actor_type": actor_type,
                "at": now,
            }
            # Accepting a flag must not erase what was flagged. Re-answering an
            # item overwrote it outright, so the only way to clear a defect was
            # to delete the description of it — and the note IS the record of
            # what somebody found (user report 2026-08-25). The answer being
            # replaced is kept on the entry instead, and a real finding beats a
            # routine re-check when both are candidates, so a flag survives any
            # number of later "checked" answers.
            superseded = _notable(
                _answer_snapshot(old) if old and old.get("result") != result else None,
                (old or {}).get("superseded"),
            )
            if superseded is not None:
                entry["superseded"] = superseded
            # `na` carries the structured reason ("feature_absent",
            # "kind_exempt", …) so the health tab can aggregate WHY items are
            # being closed as inapplicable instead of re-reading free-text
            # notes. Free text stays in `note`; the code is na-only, and it is
            # mandatory above the machine tier (validated above).
            if reason and result == "na":
                entry["reason"] = reason[:40]
            merged[key] = entry

    # ---------------------------------------------------------- exceptions
    # Applied by `conformance.evaluate`, NOT here. Until 2026-09-14 this
    # function wrote an `na` answer for every live exception, which had two
    # consequences worth remembering:
    #
    # 1. Granting one on an item nobody had answered yet did NOTHING until some
    #    unrelated save happened to run this code. Measured: `fp.model_fit`
    #    granted on footprint 117, item still open, 0/6 answered.
    # 2. The answer it wrote had to be dropped BEFORE the incoming merge when
    #    the exception was revoked, because it was written at the human tier
    #    and the tier rule then blocked the machine from replacing it.
    #
    # Both problems are the same mistake: a decision about the PART stored on
    # one VERSION. Computed, it applies the moment it is granted and stops the
    # moment it is revoked, and neither needs a write.
    applied: list[dict] = []

    # A verification — whoever wrote it — answers any open agent request for
    # this subject. Marking rather than deleting keeps "when did I ask" cheap.
    #
    # `close_requests=False` exists for any writer that verifies nothing new —
    # closing a queued request with one would delete somebody's ask and tell
    # them it had been answered. Nothing passes it today; it stays because the
    # next automated writer will need it.
    for req in (db.query(M.ReviewRequest).filter_by(
            subject_kind=kind, subject_id=parent.id, done_at=None)
            if close_requests else []):
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
                 "blocked": blocked or None,
                 "exceptions_applied": applied or None},
    ))
    # The state MUST be read back through conformance: a `na` in this save has
    # just become a standing exception, and the caller has to see the item
    # closed rather than still open. `get` recomputes because the exception id
    # is in the digest.
    from . import conformance as conformance_svc

    version = next((v for v in getattr(parent, "versions", []) if v.id == version_id), None)
    conf_items, excused = conformance_svc.get(db, kind, parent, version)
    state = state_from_record(record, resolved["items"], conf_items, excused)
    return {"record": record_json(record), "state": state, "blocked": blocked}


# `machine_check_on_publish` and `recheck_machine_tier` were DELETED on
# 2026-09-14 (decision 0017). They existed to write the machine tier into a
# record and then to un-stale it afterwards; conformance is computed now
# (`services/conformance.py`), so there is nothing to write and nothing to
# refresh. If you find yourself re-adding either, the question to ask first is
# why a recomputable answer is being stored.


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


def carry_component(db: Session, comp: M.Component, old_cv, new_cv,
                    rename: tuple[str, str, str] | None = None) -> dict | None:
    """Carry a component's own verification record across a data-preserving
    publish (repoints, non-material edits). Uses the sign-off leg rules.

    ``rename`` is passed only by `services/rename.py` — see
    `signoff.data_carries`. A rename changes the NAME of the template the
    component points at and nothing a verification measured, so the record
    carries."""
    if old_cv is None or new_cv is None or old_cv.id == new_cv.id:
        return None
    rows = records_for(db, "component", comp.id)
    prev = effective_record(rows, old_cv.id)
    if prev is None or effective_record(rows, new_cv.id) is not None:
        return None
    ok, why = signoff.data_carries(old_cv, new_cv, rename)
    if not ok:
        return {"carried": False, "reason": f"component data: {why}"}
    # A verification says "the data matches the documentation". Unchanged data
    # against a NEW datasheet revision is not verified — the sign-off (the
    # part is still the same part) carries, the review record does not.
    from .datasheet_store import datasheet_carries

    ok, why = datasheet_carries(db, old_cv, new_cv)
    if not ok:
        return {"carried": False, "reason": why}

    record = M.ReviewRecord(
        subject_kind="component", subject_id=comp.id, subject_version_id=new_cv.id,
        kind="carry", carried_from_id=prev.id,
        checklist_version_id=prev.checklist_version_id,
        checklist_items=prev.checklist_items,  # a carry measures against the same list
        items=prev.items,
        note=(f"Carried from v{old_cv.version_no}: component data unchanged"
              + (f" ({rename[0]} renamed {rename[1]} to {rename[2]})" if rename else "")),
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
