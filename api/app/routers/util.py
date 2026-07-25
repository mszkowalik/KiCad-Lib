"""Shared helpers for routers."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models as M
from ..services.templates import has_template, resolve_templates


def category_path(cat: M.Category) -> str:
    parts = []
    node = cat
    while node is not None:
        parts.append(node.name)
        node = node.parent
    return " / ".join(reversed(parts))


def category_and_descendant_ids(db: Session, root_id: int) -> set[int]:
    cats = db.query(M.Category).all()
    children: dict[int | None, list[M.Category]] = {}
    for c in cats:
        children.setdefault(c.parent_id, []).append(c)
    ids: set[int] = set()
    stack = [root_id]
    while stack:
        cid = stack.pop()
        ids.add(cid)
        stack.extend(c.id for c in children.get(cid, []))
    return ids


def current_version(comp: M.Component) -> M.ComponentVersion | None:
    return next((v for v in comp.versions if v.id == comp.current_version_id), None)


def props_dict(cv: M.ComponentVersion) -> dict[str, str | None]:
    """A version's properties as a dict, **plus the footprint's package name**.

    `Footprint_Name` lives on the footprint, not on each component (see the
    generator's `footprint_name_props`), so it has to be added back here or every
    `{Footprint_Name}` in a `ki_description` renders literally. Injecting it in
    `props_dict` itself means no resolution site can forget it — this is the one
    helper they all go through. A component that still carries its own row keeps
    it, matching the generator's override semantics.
    """
    out: dict[str, str | None] = {p.key: (None if p.is_null else p.value) for p in cv.properties}
    if not out.get("Footprint_Name"):
        fv = cv.footprint_version
        display = fv.footprint.display_name if fv is not None and fv.footprint else ""
        if display:
            out["Footprint_Name"] = display
    return out


def resolved_value(value: str | None, props: dict[str, str | None]) -> str:
    if value is None:
        return ""
    if has_template(value):
        return resolve_templates(value, props)
    return value


def audit(db: Session, action: str, entity_type: str, entity_id, details: dict | None = None,
          actor: str = "user") -> None:
    db.add(M.AuditLog(actor=actor, action=action, entity_type=entity_type,
                      entity_id=str(entity_id), details=details))
