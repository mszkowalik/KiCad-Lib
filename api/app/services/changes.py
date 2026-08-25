"""The change feed: what moved in the library lately, and who moved it.

One time-ordered stream over six sources that all mean "something changed" —
component, symbol, footprint and skill versions, 3D model uploads, and the
lifecycle/review events in the audit log.

Two rules shape this module.

**The list is cheap, the diff is not.** A feed row carries only what one line
prints: when, who, which kind, which name, which version. Every diff — the
property table, the before/after renders, the text diff — is a SECOND request
against `detail()`. There are ~18k events in this database and rendering a
symbol costs a kicad-cli invocation, so a feed that computed diffs eagerly
would be unusable at any page size.

**Pagination is keyset, never offset.** The feed is append-mostly and a reader
scrolls it while new versions land underneath. `OFFSET 100` after three
publishes silently repeats three rows and skips none of the ones you wanted;
the cursor here is the last row's `(ts, src, row_id)` triple, which is exactly
the sort key, so "strictly older than this row" is one row-value comparison
that cannot drift.
"""
from __future__ import annotations

import difflib
from datetime import datetime
from typing import Any

from sqlalchemy import String, and_, cast, literal, or_, select, tuple_, union_all
from sqlalchemy.orm import Session, aliased

from .. import models as M

# The kinds a caller may ask for. `event` is the audit-log lane; the other five
# are version/upload rows that can be diffed against a predecessor.
KINDS = ("component", "symbol", "footprint", "skill", "model3d", "event")

# Audit actions that count as a change worth a line in the feed.
#
# `publish`, `proposal.create` and `proposal.approve` are deliberately ABSENT:
# those rows describe the very version rows the other five lanes already
# report, and they report them with a diff attached. Including both would
# double every publish in the timeline. Money, production-run and flasher
# bookkeeping is out of scope too — this is the library's feed.
EVENT_PREFIXES = (
    "review.", "signoff.", "lifecycle.", "component.", "footprint.",
    "symbol.", "skill.", "datasheet.", "model3d.", "category.", "checklist.",
)
EVENT_EXCLUDED_ACTIONS = ("publish", "proposal.create", "proposal.approve")

# Where an audit row's subject name hides. `details` is free-form JSONB written
# by ~40 call sites; these are the keys they actually use for the human name.
_SUBJECT_KEYS = ("component", "subject", "name", "footprint", "symbol", "skill")

_PARENT_OF = {"component": M.Component, "symbol": M.Symbol, "footprint": M.Footprint}
_VERSION_OF = {
    "component": M.ComponentVersion,
    "symbol": M.SymbolVersion,
    "footprint": M.FootprintVersion,
    "skill": M.SkillVersion,
}


# --------------------------------------------------------------------- feed
def _legs():
    """The six SELECTs of the union, projected onto one common row shape.

    Every leg must produce the same columns in the same order and the same
    types, so `entity_id` is cast to text everywhere — the audit log's is
    already a string and the rest are integers.
    """
    cv, sv, fv, kv, m, a = (
        M.ComponentVersion, M.SymbolVersion, M.FootprintVersion,
        M.SkillVersion, M.Model3D, M.AuditLog,
    )
    # The 3D models table has no `created_by` — the uploader is only recorded
    # in the audit row the upload wrote. Join it back so the feed can answer
    # "by whom" for the models that have one; the ~4.7k rows the retired YAML
    # import created legitimately have nobody, and read as "import".
    ma = aliased(M.AuditLog)

    return [
        select(
            cv.created_at.label("ts"),
            literal("component").label("src"),
            cv.id.label("row_id"),
            cast(M.Component.id, String).label("entity_id"),
            M.Component.name.label("name"),
            cv.created_by.label("actor"),
            cv.version_no.label("version_no"),
            cv.comment.label("comment"),
        ).join(M.Component, M.Component.id == cv.component_id),

        select(
            sv.created_at, literal("symbol"), sv.id,
            cast(M.Symbol.id, String), M.Symbol.name, sv.created_by,
            sv.version_no, sv.comment,
        ).join(M.Symbol, M.Symbol.id == sv.symbol_id),

        select(
            fv.created_at, literal("footprint"), fv.id,
            cast(M.Footprint.id, String), M.Footprint.name, fv.created_by,
            fv.version_no, fv.comment,
        ).join(M.Footprint, M.Footprint.id == fv.footprint_id),

        select(
            kv.created_at, literal("skill"), kv.id,
            cast(M.Skill.id, String), M.Skill.name, kv.created_by,
            kv.version_no, kv.comment,
        ).join(M.Skill, M.Skill.id == kv.skill_id),

        # Never select Model3D.data here — it is a LargeBinary and the feed
        # would drag every mesh through Postgres to print a filename.
        select(
            m.created_at, literal("model3d"), m.id,
            cast(m.id, String), m.rel_path,
            ma.actor, literal(None), literal(None),
        ).outerjoin(ma, and_(ma.entity_type == "model3d",
                             ma.action == "model3d.create",
                             ma.entity_id == cast(m.id, String))),

        select(
            a.ts, literal("event"), a.id,
            a.entity_id, a.action, a.actor,
            literal(None), literal(None),
        ).where(
            or_(*[a.action.startswith(p) for p in EVENT_PREFIXES]),
            a.action.notin_(EVENT_EXCLUDED_ACTIONS),
        ),
    ]


def _cursor_of(row) -> str:
    return f"{row.ts.isoformat()}|{row.src}|{row.row_id}"


def _parse_cursor(cursor: str) -> tuple[datetime, str, int] | None:
    """`None` for anything unparseable — a bad cursor means "start at the top",
    never a 500. The cursor is opaque to the client and only ever comes back
    from us, so a malformed one is a bookmark from an older shape."""
    try:
        ts_s, src, row_s = cursor.split("|")
        return datetime.fromisoformat(ts_s), src, int(row_s)
    except (ValueError, AttributeError):
        return None


def feed(db: Session, *, limit: int = 50, cursor: str | None = None,
         kinds: list[str] | None = None, actor: str = "", q: str = "") -> dict:
    """One page of the feed, newest first, plus the cursor for the next page."""
    u = union_all(*_legs()).subquery("feed")
    stmt = select(u)

    wanted = [k for k in (kinds or []) if k in KINDS]
    if wanted:
        stmt = stmt.where(u.c.src.in_(wanted))
    if actor.strip():
        stmt = stmt.where(u.c.actor.ilike(f"%{actor.strip()}%"))
    if q.strip():
        stmt = stmt.where(u.c.name.ilike(f"%{q.strip()}%"))

    parsed = _parse_cursor(cursor) if cursor else None
    if parsed is not None:
        stmt = stmt.where(tuple_(u.c.ts, u.c.src, u.c.row_id) < tuple_(*parsed))

    # One row over the page size is how we know a next page exists without a
    # second COUNT over the whole union.
    stmt = stmt.order_by(u.c.ts.desc(), u.c.src.desc(), u.c.row_id.desc()).limit(limit + 1)
    rows = db.execute(stmt).all()

    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [_row_json(db, r) for r in rows],
        "next_cursor": _cursor_of(rows[-1]) if rows and has_more else None,
        "has_more": has_more,
    }


def _row_json(db: Session, r) -> dict:
    label, subject = _event_label(db, r) if r.src == "event" else (None, None)
    return {
        "key": f"{r.src}:{r.row_id}",
        "kind": r.src,
        "id": r.row_id,
        "entity_id": r.entity_id,
        # For an event the union's `name` slot carries the action; the printed
        # name is the subject the action touched.
        "name": subject if r.src == "event" else r.name,
        "action": r.name if r.src == "event" else ("added" if r.src == "model3d" else "published"),
        "action_label": label,
        "actor": r.actor or ("import" if r.src == "model3d" else "unknown"),
        "ts": r.ts.isoformat(),
        "version_no": r.version_no,
        "comment": r.comment,
        # A first version has nothing to diff against, and the UI says so
        # instead of unfolding an empty panel.
        "diffable": r.src in ("component", "symbol", "footprint", "skill"),
    }


def _event_label(db: Session, r) -> tuple[str, str]:
    """A human action and subject for an audit row.

    Both are best-effort: `details` is free-form and 40 call sites write it.
    Falling back to the raw action and the entity type is always truthful,
    just terse.
    """
    action = r.name
    label = action.replace(".", " ").replace("_", " ")
    row = db.get(M.AuditLog, r.row_id)
    details = (row.details if row else None) or {}
    subject = ""
    for key in _SUBJECT_KEYS:
        val = details.get(key)
        if isinstance(val, str) and val.strip():
            subject = val.strip()
            break
    if not subject and row is not None:
        subject = _subject_from_entity(db, row)
    return label, subject or (row.entity_type if row else "")


def _subject_from_entity(db: Session, row: M.AuditLog) -> str:
    """Resolve `entity_type`/`entity_id` to a name. Version entity types point
    at a version row, whose parent carries the name."""
    try:
        eid = int(row.entity_id or "")
    except (TypeError, ValueError):
        return ""
    kind = row.entity_type.removesuffix("_version")
    if row.entity_type.endswith("_version"):
        ver = db.get(_VERSION_OF.get(kind, M.ComponentVersion), eid)
        parent = _PARENT_OF.get(kind)
        if ver is None or parent is None:
            return ""
        owner = db.get(parent, getattr(ver, f"{kind}_id", 0))
        return owner.name if owner else ""
    model = _PARENT_OF.get(row.entity_type) or {"skill": M.Skill, "model3d": M.Model3D,
                                                "category": M.Category}.get(row.entity_type)
    if model is None:
        return ""
    obj = db.get(model, eid)
    if obj is None:
        return ""
    return getattr(obj, "name", None) or getattr(obj, "rel_path", "") or ""


# ------------------------------------------------------------------- detail
def detail(db: Session, kind: str, row_id: int) -> dict | None:
    """The unfolded diff for one feed row. `None` when the row is gone."""
    if kind == "component":
        return _component_detail(db, row_id)
    if kind in ("symbol", "footprint"):
        return _geometry_detail(db, kind, row_id)
    if kind == "skill":
        return _skill_detail(db, row_id)
    if kind == "model3d":
        return _model_detail(db, row_id)
    if kind == "event":
        return _event_detail(db, row_id)
    return None


def _previous(db: Session, model, owner_col: str, owner_id: int, version_no: int):
    """The version immediately before this one.

    Ordered by `version_no`, not by id: an id ordering would be wrong the
    moment a version row is ever backfilled out of sequence, and version_no is
    the number the UI prints anyway.
    """
    return (db.query(model)
            .filter(getattr(model, owner_col) == owner_id, model.version_no < version_no)
            .order_by(model.version_no.desc())
            .first())


def _meta(ver, owner, kind: str, prev) -> dict:
    return {
        "kind": kind,
        "id": owner.id,
        "name": getattr(owner, "name", ""),
        "version_no": ver.version_no,
        "version_id": ver.id,
        "prev_version_no": prev.version_no if prev else None,
        "prev_version_id": prev.id if prev else None,
        "created_at": ver.created_at.isoformat(),
        "created_by": ver.created_by,
        "comment": ver.comment,
        "first_version": prev is None,
    }


# ---------------------------------------------------------------- component
def _props(cv: M.ComponentVersion) -> dict[str, str | None]:
    """Key → value, with an explicit NULL kept distinct from an empty string:
    `is_null` is the YAML `~` that means "N/A on purpose", and flattening it to
    "" would report a change that never happened."""
    return {p.key: (None if p.is_null else p.value) for p in cv.properties}


def _shown(value: str | None) -> str:
    return "— N/A —" if value is None else value


def _component_detail(db: Session, version_id: int) -> dict | None:
    cv = db.get(M.ComponentVersion, version_id)
    if cv is None:
        return None
    comp = db.get(M.Component, cv.component_id)
    if comp is None:
        return None
    prev = _previous(db, M.ComponentVersion, "component_id", cv.component_id, cv.version_no)

    now, before = _props(cv), _props(prev) if prev else {}
    added = [{"key": k, "after": _shown(v)} for k, v in now.items() if k not in before]
    removed = [{"key": k, "before": _shown(v)} for k, v in before.items() if k not in now]
    changed = [{"key": k, "before": _shown(before[k]), "after": _shown(v)}
               for k, v in now.items() if k in before and before[k] != v]
    unchanged = sum(1 for k, v in now.items() if k in before and before[k] == v)

    fields = []

    def _field(label: str, was, now_):
        if prev is not None and was != now_:
            fields.append({"label": label, "before": str(was or "—"), "after": str(now_ or "—")})

    from ..routers.util import category_path

    _field("Base symbol", prev.base_component if prev else "", cv.base_component)
    _field("Category",
           category_path(prev.category) if prev and prev.category else "",
           category_path(cv.category) if cv.category else "")
    _field("Pinned symbol version", prev.symbol_version_id if prev else None, cv.symbol_version_id)
    _field("Pinned footprint version", prev.footprint_version_id if prev else None,
           cv.footprint_version_id)
    _field("Removed properties",
           ", ".join(prev.removed_properties or []) if prev else "",
           ", ".join(cv.removed_properties or []))

    return {
        **_meta(cv, comp, "component", prev),
        "fields": fields,
        "properties": {
            "added": sorted(added, key=lambda r: r["key"]),
            "removed": sorted(removed, key=lambda r: r["key"]),
            "changed": sorted(changed, key=lambda r: r["key"]),
            "unchanged": unchanged,
        },
    }


# ------------------------------------------------------- symbol / footprint
def _pin_rows(parsed: dict | None) -> dict[str, dict]:
    """Symbol pins keyed by pin NUMBER — the stable identity. Names and types
    are what a review cares about, and both can change while the number does
    not."""
    out: dict[str, dict] = {}
    for p in (parsed or {}).get("pins", []) or []:
        out[str(p.get("number", ""))] = {"name": p.get("name", ""), "type": p.get("type", "")}
    return out


def _pad_rows(parsed: dict | None) -> dict[str, dict]:
    """Footprint pads keyed by pad number. Unnumbered pads (mechanical holes,
    NPTH) share the empty key, so they are counted rather than diffed."""
    out: dict[str, dict] = {}
    blanks = 0
    for p in (parsed or {}).get("pads", []) or []:
        num = str(p.get("number", "") or "")
        if not num:
            blanks += 1
            num = f"(unnumbered {blanks})"
        size = p.get("size") or []
        out[num] = {
            "size": " x ".join(str(s) for s in size) if size else "",
            "drill": str(p.get("drill") or ""),
            "shape": p.get("shape", ""),
            "type": p.get("type", ""),
        }
    return out


def _row_diff(before: dict[str, dict], after: dict[str, dict], label: str) -> dict:
    added = [{"id": k, "after": v} for k, v in after.items() if k not in before]
    removed = [{"id": k, "before": v} for k, v in before.items() if k not in after]
    changed = [{"id": k, "before": before[k], "after": v}
               for k, v in after.items() if k in before and before[k] != v]
    return {
        "label": label,
        "added": added,
        "removed": removed,
        "changed": changed,
        "unchanged": sum(1 for k, v in after.items() if k in before and before[k] == v),
    }


def _geometry_detail(db: Session, kind: str, version_id: int) -> dict | None:
    model = _VERSION_OF[kind]
    ver = db.get(model, version_id)
    if ver is None:
        return None
    owner = db.get(_PARENT_OF[kind], getattr(ver, f"{kind}_id"))
    if owner is None:
        return None
    prev = _previous(db, model, f"{kind}_id", owner.id, ver.version_no)

    base = f"/api/{kind}s/{owner.id}/versions"
    if kind == "symbol":
        rows = _row_diff(_pin_rows(prev.parsed) if prev else {}, _pin_rows(ver.parsed), "Pins")
    else:
        rows = _row_diff(_pad_rows(prev.parsed) if prev else {}, _pad_rows(ver.parsed), "Pads")

    return {
        **_meta(ver, owner, kind, prev),
        # Version-addressed renders: a version's source never changes, so these
        # URLs are immutable and the browser may hold them forever.
        "after_svg": f"{base}/{ver.version_no}/preview.svg",
        "before_svg": f"{base}/{prev.version_no}/preview.svg" if prev else None,
        "rows": rows,
        # The fingerprint over the electrically material part only (pins for a
        # symbol; pads, drills, layers and courtyard for a footprint). Equal
        # means the change was cosmetic and no verification was invalidated.
        "material_changed": bool(prev and prev.material_sha and ver.material_sha
                                 and prev.material_sha != ver.material_sha),
        "recheck_required": ver.recheck_required,
    }


# ------------------------------------------------------------------- skill
def _skill_detail(db: Session, version_id: int) -> dict | None:
    ver = db.get(M.SkillVersion, version_id)
    if ver is None:
        return None
    owner = db.get(M.Skill, ver.skill_id)
    if owner is None:
        return None
    prev = _previous(db, M.SkillVersion, "skill_id", owner.id, ver.version_no)
    before = (prev.content if prev else "").splitlines()
    after = (ver.content or "").splitlines()
    diff = list(difflib.unified_diff(before, after, lineterm="", n=3,
                                     fromfile=f"v{prev.version_no}" if prev else "new",
                                     tofile=f"v{ver.version_no}"))
    return {
        **_meta(ver, owner, "skill", prev),
        # Trimmed: a whole-document rewrite would otherwise ship thousands of
        # lines into a panel nobody scrolls to the end of.
        "diff": diff[:600],
        "diff_truncated": len(diff) > 600,
        "added_lines": sum(1 for line in diff if line.startswith("+") and not line.startswith("+++")),
        "removed_lines": sum(1 for line in diff if line.startswith("-") and not line.startswith("---")),
    }


# ---------------------------------------------------------- model3d / event
def _model_detail(db: Session, model_id: int) -> dict | None:
    m = db.get(M.Model3D, model_id)
    if m is None:
        return None
    return {
        "kind": "model3d",
        "id": m.id,
        "name": m.rel_path,
        "created_at": m.created_at.isoformat(),
        "sha256": m.sha256,
        "size_bytes": m.size_bytes,
        "first_version": True,
    }


def _event_detail(db: Session, audit_id: int) -> dict | None:
    row = db.get(M.AuditLog, audit_id)
    if row is None:
        return None
    details = row.details or {}
    return {
        "kind": "event",
        "id": row.id,
        "name": _subject_from_entity(db, row) or row.entity_type,
        "action": row.action,
        "actor": row.actor,
        "created_at": row.ts.isoformat(),
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        # Scalars render as a key/value table; anything nested is shown as JSON
        # rather than silently dropped.
        "details": [{"key": k, "value": v if isinstance(v, (str, int, float, bool, type(None)))
                     else _compact(v)}
                    for k, v in sorted(details.items())],
    }


def _compact(value: Any) -> str:
    import json

    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 400 else text[:400] + "…"
