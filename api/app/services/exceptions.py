"""Standing exceptions: one check, one subject, a decision that outlives the version.

Why this exists, in one measurement: on 2026-09-14 the library held **zero**
`na (waived)` answers, while agents had invented **188 distinct `custom:` keys**,
150 of them used exactly once. Nobody was refusing to record decisions — the
place meant for them did not last. A waiver was an answer on ONE version, so a
pad move refused the carry and took the decision with it, and nobody writes a
waiver they will have to write again next month.

The shape is KiCad's. `drc_exclusions` has shipped for years: an exclusion names
the rule AND the items it fired on, carries a comment, lives with the design,
and survives every edit that does not touch those items.

**`depends_on` is that idea.** It holds `{fact: value}` captured at grant time
from `checklists.subject_facts`, and the exception is live while every one still
holds:

- ``{}``                          — this part, always. A decision about the part.
- ``{"$material_sha": "…"}``      — this drawing only. Dies when the copper moves.
- ``{"comp_type": "TVS", …}``     — anything else worth pinning.

Choosing between them IS the safety question. A blanket waiver that silently
covers a future edit is the failure mode this table exists to avoid, and naming
the dependency is what prevents it — so `grant` never guesses: the caller says
which facts to pin.

Applied in ONE place, `review.record_check`, after the tier merge. That covers
the validator, the agent and the review card with one rule, and the finding it
replaces is kept on the answer's `superseded` so accepting an exception never
erases what was found.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M

#: The facts `grant` pins when the caller asks for the drawing-scoped preset.
#: Deliberately one fact: a drawing-scoped exception is about the drawing, and
#: pinning more only makes it die for reasons that have nothing to do with it.
DRAWING_SCOPE = ("$material_sha",)

#: What an exception pins when NOBODY chose a scope — the `na` answers that
#: arrive through `record_check` from the agent API. Always a pinned scope,
#: never "always": a blanket waiver covering every future version of a part is
#: a decision only a person should be able to make, and the review card asks
#: for it explicitly. A component pins its OWN fields, because its
#: `$material_sha` is the symbol's and the footprint's joined together and says
#: nothing about a Value or a datasheet.
DEFAULT_PIN = {
    "component": ("$property_sha",),
    "symbol": ("$material_sha",),
    "footprint": ("$material_sha",),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def rows_for(db: Session, kind: str, subject_id: int) -> list[M.ReviewException]:
    return (
        db.query(M.ReviewException)
        .filter_by(subject_kind=kind, subject_id=subject_id)
        .order_by(M.ReviewException.id)
        .all()
    )


def stale_reason(exc: M.ReviewException, facts: dict | None) -> str | None:
    """Why this exception no longer applies, or None while it holds.

    A fact that can no longer be READ counts as changed. The alternative — to
    treat "cannot tell" as "unchanged" — would keep an exception alive across
    exactly the edits nobody could verify, which is the wrong way to be wrong.
    """
    for field, was in (exc.depends_on or {}).items():
        now = (facts or {}).get(field)
        if now is None:
            return f"{field} can no longer be read"
        if str(now) != str(was):
            return f"{field} changed from {was!r} to {now!r}"
    return None


def live_for(db: Session, kind: str, subject_id: int, facts: dict | None = None) -> dict:
    """The exceptions in force for one subject, newest per (key, variant).

    Returns ``{(key, variant): exception}``. Pass no facts and the dependency is
    not judged — a screen listing what exists rather than what applies.
    """
    out: dict[tuple[str, str], M.ReviewException] = {}
    for exc in rows_for(db, kind, subject_id):
        if exc.revoked_at is not None:
            continue
        if facts is not None and stale_reason(exc, facts) is not None:
            continue
        out[(exc.key, exc.variant or "")] = exc
    return out


#: How long an exception's written fields may be. Same numbers and the same
#: reason as `review.TEXT_LIMITS`: an explanation nobody reads loses the
#: decision inside it, and an agent writes twelve times what a person writes.
#: `evidence` is larger because it may hold a quoted line from a datasheet.
TEXT_LIMITS = {"note": 400, "evidence": 600, "revoke_reason": 300}


def check_length(value: str | None, field: str) -> None:
    text = (value or "").strip()
    limit = TEXT_LIMITS[field]
    if len(text) > limit:
        raise ValueError(
            f"the {field} is {len(text)} characters, and the limit is {limit}. "
            f"Say why in a few sentences — this is read by the next person who "
            f"meets this part, not filed.")


def grant(db: Session, kind: str, parent, key: str, *, reason: str, note: str,
          actor: str, actor_type: str = "human", variant: str = "",
          evidence: str = "", depends_on: dict | None = None) -> M.ReviewException:
    """Record a standing exception. Caller owns the transaction.

    ``depends_on`` is taken from the caller rather than inferred: "this drawing"
    and "this part, always" are different decisions, and guessing which one
    somebody meant is how a waiver ends up covering an edit nobody reviewed.
    """
    if not note.strip():
        raise ValueError("an exception needs a note saying why")
    check_length(note, "note")
    check_length(evidence, "evidence")
    exc = M.ReviewException(
        subject_kind=kind, subject_id=parent.id, key=key, variant=variant or "",
        reason=reason, note=note.strip(), evidence=(evidence or "").strip(),
        depends_on=dict(depends_on or {}),
        created_by=actor, actor_type=actor_type,
    )
    db.add(exc)
    db.flush()
    db.add(M.AuditLog(
        actor=actor, action="review.exception.grant", entity_type=f"{kind}",
        entity_id=str(parent.id),
        details={"subject": getattr(parent, "name", ""), "key": key, "variant": variant,
                 "reason": reason, "depends_on": exc.depends_on, "id": exc.id}))
    return exc


def revoke(db: Session, exc: M.ReviewException, actor: str, reason: str) -> M.ReviewException:
    check_length(reason, "revoke_reason")
    exc.revoked_at = _utcnow()
    exc.revoked_by = actor
    exc.revoke_reason = (reason or "").strip() or None
    db.add(M.AuditLog(
        actor=actor, action="review.exception.revoke", entity_type=exc.subject_kind,
        entity_id=str(exc.subject_id),
        details={"key": exc.key, "variant": exc.variant, "reason": exc.revoke_reason,
                 "id": exc.id}))
    return exc


#: How a pinned fact reads to a person. An exception scoped to anything other
#: than the drawing used to print "this drawing" regardless, because the label
#: was `if depends_on` rather than a reading of WHAT was pinned — and a scope
#: label that names the wrong thing is worse than none.
_SCOPE_WORDS = {
    "$material_sha": "this drawing",
    "$property_sha": "this component's data",
}


def scope_label(depends_on: dict | None) -> str:
    if not depends_on:
        return "this part, always"
    return " and ".join(_SCOPE_WORDS.get(f, f) for f in sorted(depends_on)) + " only"


def json_of(exc: M.ReviewException, facts: dict | None = None) -> dict:
    return {
        "id": exc.id,
        "subject_kind": exc.subject_kind,
        "subject_id": exc.subject_id,
        "key": exc.key,
        "variant": exc.variant or None,
        "reason": exc.reason,
        "note": exc.note,
        "evidence": exc.evidence or None,
        "depends_on": exc.depends_on or {},
        "scope": scope_label(exc.depends_on),
        "created_by": exc.created_by,
        "actor_type": exc.actor_type,
        "created_at": exc.created_at.isoformat() if exc.created_at else None,
        "revoked_at": exc.revoked_at.isoformat() if exc.revoked_at else None,
        "revoked_by": exc.revoked_by,
        "revoke_reason": exc.revoke_reason,
        "stale_reason": None if facts is None else stale_reason(exc, facts),
    }
