"""Production sign-off: the record, its derived state, and the carry rule.

A sign-off says a human checked a component's symbol, land pattern and part
number and is willing to build boards with it. `models.ComponentSignoff`
explains why that is a different thing from `ComponentVersion.approved_by`;
this module is the logic on top.

**Everything is derived from one question: is there a live sign-off row on the
component's CURRENT version?** Because a component version pins its exact
symbol and footprint versions, and every version row is immutable, that one
question is enough. Nothing is recomputed, invalidated or swept.

## The carry rule

Left alone, the derived state would be useless in practice. A silkscreen tweak
publishes a new footprint version, `services/repoint.py` files a draft for
every component using it, and approving those drafts would strip the sign-off
from forty parts that did not change in any way a fab house can see.

So when a component version is published, this module asks whether the sign-off
on the outgoing version still applies. It carries only when EVERY leg carries:

- **Component data** — `base_component`, category, and every property except
  the small `NON_MATERIAL_KEYS` allow-list. Note the direction: a key is
  material unless it is explicitly listed. A new property key that nobody has
  classified blocks the carry, which is the safe way to be wrong.
- **The symbol pin** and **the footprint pin** — unchanged, or the approver
  waived the re-check on the new geometry version, or (nobody was asked) the
  material fingerprints are equal. `services/material.py` defines what
  "material" means and why.

Any leg that does not carry means no row is written at all, and the component
reads `stale` with the blocking leg named. Silence is never the answer: either
the signature moves forward with a note saying why, or the user is told to look
again.

## What deliberately does NOT happen here

Nothing is blocked. No export refuses, no run is gated, no proposal is held up.
The state is reporting only (user decision, 2026-08-17). If that ever changes,
change it at the call site — this module must stay a pure record.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M
from . import material

log = logging.getLogger(__name__)

# Component property keys that may change without costing the sign-off.
#
# This is an ALLOW-LIST, and the direction matters. Everything else — the part
# number, the manufacturer, the LCSC code, Value, tolerance, voltage rating,
# the Footprint reference — is material, because every one of them can make the
# checked part the wrong part. A key nobody has thought about is treated as
# material until somebody decides otherwise.
NON_MATERIAL_KEYS = frozenset({
    "ki_description",   # generated prose
    "ki_keywords",      # search only
    "ki_fp_filters",    # the footprint chooser's filter, not the choice
    "ki_locked",
    "Datasheet",        # injected from the datasheets table, not authored here
    "Footprint_Name",   # the package's display name; belongs to the footprint
})


def _is_non_material(key: str) -> bool:
    # "Datasheet 2", "Reference schematic", ... — the extra datasheet fields are
    # named after their own label, so match the native key and the numbered form.
    return key in NON_MATERIAL_KEYS or key.startswith("Datasheet ")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------- reading state
def _rows(db: Session, component_id: int) -> list[M.ComponentSignoff]:
    return (
        db.query(M.ComponentSignoff)
        .filter(M.ComponentSignoff.component_id == component_id)
        .order_by(M.ComponentSignoff.id)
        .all()
    )


def live_signoff(rows: list[M.ComponentSignoff], version_id: int | None) -> M.ComponentSignoff | None:
    """The newest non-revoked sign-off on one version, if any."""
    if version_id is None:
        return None
    return next(
        (r for r in reversed(rows) if r.component_version_id == version_id and r.revoked_at is None),
        None,
    )


def _material_props(cv: M.ComponentVersion) -> dict[str, tuple[str | None, bool]]:
    return {
        p.key: (p.value, p.is_null)
        for p in cv.properties
        if not _is_non_material(p.key)
    }


def data_carries(old_cv: M.ComponentVersion, new_cv: M.ComponentVersion) -> tuple[bool, str]:
    """Did the component's own data stay the same part?"""
    if old_cv.base_component != new_cv.base_component:
        return False, f"the base symbol changed ({old_cv.base_component} to {new_cv.base_component})"
    if old_cv.category_id != new_cv.category_id:
        return False, "the component moved to another category"

    old_p, new_p = _material_props(old_cv), _material_props(new_cv)
    added = sorted(set(new_p) - set(old_p))
    removed = sorted(set(old_p) - set(new_p))
    changed = sorted(k for k in set(old_p) & set(new_p) if old_p[k] != new_p[k])
    if added or removed or changed:
        parts = []
        if changed:
            parts.append("changed " + ", ".join(changed))
        if added:
            parts.append("added " + ", ".join(added))
        if removed:
            parts.append("removed " + ", ".join(removed))
        return False, "properties " + "; ".join(parts)

    old_rm = {k for k in (old_cv.removed_properties or []) if not _is_non_material(k)}
    new_rm = {k for k in (new_cv.removed_properties or []) if not _is_non_material(k)}
    if old_rm != new_rm:
        return False, "the removed-properties list changed"
    return True, ""


def geometry_carries(db: Session, kind: str, old_id: int | None, new_id: int | None) -> tuple[bool, str, str]:
    """Does a sign-off survive this symbol / footprint move?

    Returns (carries, mode, reason). `mode` is "unchanged" | "identical" |
    "waived" | "" and decides whether the resulting sign-off counts as proven
    (`auto-carried`) or as a human's waiver (`carried`).
    """
    if old_id == new_id:
        return True, "unchanged", f"the {kind} did not change"
    if old_id is None or new_id is None:
        return False, "", f"the component gained or lost its {kind}"

    model = M.SymbolVersion if kind == "symbol" else M.FootprintVersion
    old, new = db.get(model, old_id), db.get(model, new_id)
    if old is None or new is None:
        return False, "", f"the {kind} version could not be read"

    label = f"{kind} v{old.version_no} to v{new.version_no}"
    # An empty fingerprint means "could not tell" (unparseable, or not yet
    # backfilled), and two of those must NEVER compare equal.
    same = bool(old.material_sha) and old.material_sha == new.material_sha

    # "Look again" outranks everything, including an identical drawing: an
    # approver who asks for a re-check has a reason the fingerprint cannot see.
    if new.recheck_required is True:
        return False, "", f"{label}: the approver asked for a new verification"

    # A waiver on an UNCHANGED drawing is not a waiver — there was nothing to
    # waive. Reporting it as one would put a human's name on a decision they
    # never made, and would make `carried` (somebody took responsibility for a
    # change) indistinguishable from `auto-carried` (nothing changed). The
    # fingerprint is checked first for exactly that reason.
    if same:
        return True, "identical", f"{label}: nothing that reaches the board changed"
    if new.recheck_required is False:
        return True, "waived", f"{label}: the approver waived the re-check on a changed drawing"
    # Nobody was asked — every version published before this feature landed.
    return False, "", f"{label}: the drawing changed"


def state_for(db: Session, comp: M.Component, rows: list[M.ComponentSignoff] | None = None,
              detail: bool = True) -> dict:
    """The component's sign-off state, and (with `detail`) why it is that.

    `detail=False` returns the state and nothing derived. Deriving `blockers`
    costs several version loads AND touches `cv.properties`, which lazy-loads a
    property set per version — fine for one component page, ruinous for a list
    of 327. The badge only needs the word.
    """
    rows = _rows(db, comp.id) if rows is None else rows
    cur_id = comp.current_version_id
    bare = {"signoff": None, "signed_version_no": None, "blockers": []}

    if not rows:
        return {**bare, "state": "unsigned"}

    live = live_signoff(rows, cur_id)
    if live is not None:
        return {**bare, "state": "signed", "signoff": signoff_json(live)}

    on_current = [r for r in rows if r.component_version_id == cur_id]
    if on_current:
        # Every sign-off this version had was taken back. That is a stronger
        # statement than "never checked" and must not read the same.
        return {**bare, "state": "revoked", "signoff": signoff_json(on_current[-1])}

    prior = next((r for r in reversed(rows) if r.revoked_at is None), None)
    if prior is None:
        return {**bare, "state": "unsigned", "last_revoked": signoff_json(rows[-1])}

    out = {"state": "stale", "signoff": signoff_json(prior),
           "signed_version_no": None, "blockers": []}
    if not detail:
        return out

    signed_cv = db.get(M.ComponentVersion, prior.component_version_id)
    cur_cv = db.get(M.ComponentVersion, cur_id) if cur_id else None
    blockers: list[str] = []
    if signed_cv is not None and cur_cv is not None:
        ok, why = data_carries(signed_cv, cur_cv)
        if not ok:
            blockers.append(f"component data: {why}")
        for kind, old_id, new_id in (
            ("symbol", signed_cv.symbol_version_id, cur_cv.symbol_version_id),
            ("footprint", signed_cv.footprint_version_id, cur_cv.footprint_version_id),
        ):
            ok, _mode, why = geometry_carries(db, kind, old_id, new_id)
            if not ok:
                blockers.append(why)
    out["signed_version_no"] = signed_cv.version_no if signed_cv else None
    out["blockers"] = blockers
    return out


def states_for(db: Session, comps: list[M.Component], detail: bool = True) -> dict[int, dict]:
    """`state_for` over many components with ONE query for the sign-off rows.

    The browse list renders a badge per component. Calling `state_for` in a loop
    would issue a query per row — the same shape of mistake `kicad_http` had to
    undo when the symbol chooser went quadratic. Pass `detail=False` from any
    list surface: it makes the whole pass one query plus pure Python.
    """
    ids = [c.id for c in comps]
    by_comp: dict[int, list[M.ComponentSignoff]] = {i: [] for i in ids}
    if ids:
        q = (
            db.query(M.ComponentSignoff)
            .filter(M.ComponentSignoff.component_id.in_(ids))
            .order_by(M.ComponentSignoff.id)
        )
        for r in q:
            by_comp.setdefault(r.component_id, []).append(r)
    return {c.id: state_for(db, c, by_comp.get(c.id, []), detail=detail) for c in comps}


def signoff_json(r: M.ComponentSignoff) -> dict:
    return {
        "id": r.id,
        "component_version_id": r.component_version_id,
        "kind": r.kind,
        "carried_from_id": r.carried_from_id,
        "signed_by": r.signed_by,
        "signed_at": r.signed_at.isoformat() if r.signed_at else None,
        "note": r.note,
        "revoked_at": r.revoked_at.isoformat() if r.revoked_at else None,
        "revoked_by": r.revoked_by,
        "revoke_reason": r.revoke_reason,
    }


# --------------------------------------------------------------------- writing
def sign(db: Session, comp: M.Component, actor: str, note: str | None = None) -> M.ComponentSignoff:
    """Sign off the component's current version. Caller owns the transaction."""
    row = M.ComponentSignoff(
        component_id=comp.id,
        component_version_id=comp.current_version_id,
        kind="checked",
        signed_by=actor,
        note=note or None,
    )
    db.add(row)
    db.flush()
    return row


def revoke(db: Session, row: M.ComponentSignoff, actor: str, reason: str) -> M.ComponentSignoff:
    row.revoked_at = _utcnow()
    row.revoked_by = actor
    row.revoke_reason = reason
    return row


def carry_on_publish(db: Session, comp: M.Component, old_cv, new_cv) -> dict | None:
    """Move the sign-off from the outgoing version to the one being published.

    Call this INSIDE the approve transaction, before `current_version_id` is
    repointed or after — it reads `old_cv` and `new_cv` explicitly and never
    the component's pointer. Returns a summary for the approve response, or
    None when there was nothing to carry.
    """
    if old_cv is None or new_cv is None or old_cv.id == new_cv.id:
        return None
    rows = _rows(db, comp.id)
    prior = live_signoff(rows, old_cv.id)
    if prior is None:
        return None
    if live_signoff(rows, new_cv.id) is not None:
        return None  # already signed off in its own right — leave it alone

    reasons: list[str] = []
    modes: list[str] = []

    ok, why = data_carries(old_cv, new_cv)
    if not ok:
        return {"carried": False, "reason": f"component data: {why}"}
    reasons.append("component data unchanged")

    for kind, old_id, new_id in (
        ("symbol", old_cv.symbol_version_id, new_cv.symbol_version_id),
        ("footprint", old_cv.footprint_version_id, new_cv.footprint_version_id),
    ):
        ok, mode, why = geometry_carries(db, kind, old_id, new_id)
        if not ok:
            return {"carried": False, "reason": why}
        modes.append(mode)
        reasons.append(why)

    kind = "carried" if "waived" in modes else "auto-carried"
    note = (
        f"Carried from v{old_cv.version_no} (sign-off #{prior.id} by {prior.signed_by}). "
        + "; ".join(reasons)
        + "."
    )
    row = M.ComponentSignoff(
        component_id=comp.id,
        component_version_id=new_cv.id,
        kind=kind,
        carried_from_id=prior.id,
        signed_by=prior.signed_by,
        note=note,
    )
    db.add(row)
    db.flush()
    db.add(M.AuditLog(
        actor="signoff", action="signoff.carry", entity_type="component_version",
        entity_id=str(new_cv.id),
        details={"component": comp.name, "from_version": old_cv.version_no,
                 "to_version": new_cv.version_no, "kind": kind, "note": note},
    ))
    return {"carried": True, "kind": kind, "note": note, "signoff_id": row.id}


# ------------------------------------------------------- material fingerprints
def ensure_material_sha(version, kind: str) -> str:
    """Compute and store the fingerprint on a version row if it has none.

    Cheap and idempotent, so it is safe to call on any read path. New versions
    get theirs at creation; this is what fills in history.
    """
    if getattr(version, "material_sha", ""):
        return version.material_sha
    version.material_sha = material.material_sha(kind, version.source_text or "")
    return version.material_sha


def backfill_material(db: Session, limit: int | None = None) -> dict:
    """Fill `material_sha` on every geometry version that has none."""
    done = {"symbol": 0, "footprint": 0, "unparseable": 0}
    for kind, model in (("symbol", M.SymbolVersion), ("footprint", M.FootprintVersion)):
        q = db.query(model).filter(model.material_sha == "")
        if limit:
            q = q.limit(limit)
        for v in q.all():
            sha = material.material_sha(kind, v.source_text or "")
            if not sha:
                done["unparseable"] += 1
                continue
            v.material_sha = sha
            done[kind] += 1
    db.commit()
    return done


def start_material_backfill() -> None:
    """Backfill in the background so a cold start is not held up by parsing.

    An un-fingerprinted version simply blocks the carry (see
    `geometry_carries`), which is the safe direction, so nothing is wrong while
    this runs. Unparseable rows keep an empty fingerprint and are retried on
    the next start — they would break the mirror too, so they are loud enough
    elsewhere.
    """
    def _run() -> None:
        from ..db import SessionLocal

        db = SessionLocal()
        try:
            done = backfill_material(db)
            if any(done.values()):
                log.info(f"signoff: material fingerprints backfilled {done}")
        except Exception as e:  # noqa: BLE001 — a cache backfill must never kill startup
            log.warning(f"signoff: material backfill failed: {type(e).__name__}: {e}")
        finally:
            db.close()

    threading.Thread(target=_run, name="material-backfill", daemon=True).start()
