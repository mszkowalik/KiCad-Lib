"""Shared helpers for routers."""
from __future__ import annotations

from sqlalchemy.orm import Session, joinedload, selectinload

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


def components_with_current(db: Session) -> tuple[list[M.Component], dict[int, M.ComponentVersion]]:
    """Every component, and ONLY its live version — the list-surface loader.

    `selectinload(Component.versions).selectinload(ComponentVersion.properties)`
    is the obvious way to write this and it is the wrong one: it loads the
    entire HISTORY to print a list that shows one version each. Measured on
    2026-08-24 against production data — 421 components, 2296 version rows,
    23509 property rows — that pattern was most of a 1.2 s response on
    `GET /api/components` and `GET /api/reviews/queue` alike.

    Three loads happen here, each for a reason:

    - the live versions, filtered by `current_version_id`, with their
      properties and category;
    - `footprint_version` -> `footprint`, with the heavy columns DEFERRED.
      `props_dict` reads `cv.footprint_version.footprint.display_name` to fill
      `{Footprint_Name}`, which lazy-loads a whole `.kicad_mod` body per
      component otherwise — the same trap `kicad_http.library_versions`
      documents;
    - every category, so `category_path`'s walk up `parent` is served from the
      identity map instead of one SELECT per level per row.

    Returns the components and a `{component_id: live version}` map. Callers
    MUST use the map: `current_version(comp)` reads `comp.versions`, which is
    unloaded here and would lazy-load the history back one component at a time.
    """
    comps = db.query(M.Component).order_by(M.Component.name).all()
    live_ids = [c.current_version_id for c in comps if c.current_version_id]
    by_comp: dict[int, M.ComponentVersion] = {}
    if live_ids:
        rows = (
            db.query(M.ComponentVersion)
            .options(
                selectinload(M.ComponentVersion.properties),
                joinedload(M.ComponentVersion.category),
                joinedload(M.ComponentVersion.footprint_version)
                .joinedload(M.FootprintVersion.footprint),
                joinedload(M.ComponentVersion.footprint_version).defer(
                    M.FootprintVersion.source_text
                ),
                joinedload(M.ComponentVersion.footprint_version).defer(
                    M.FootprintVersion.parsed
                ),
                joinedload(M.ComponentVersion.footprint_version).defer(
                    M.FootprintVersion.models
                ),
            )
            .filter(M.ComponentVersion.id.in_(live_ids))
            .all()
        )
        by_comp = {cv.component_id: cv for cv in rows}
    db.query(M.Category).all()  # warm the identity map for category_path
    return comps, by_comp


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


def actor_of(request) -> str:
    """Who is making this request, as a name to store on a record.

    `authgate` resolves every credential onto `request.state.user`, so this is
    the one place a router needs to look. Falls back to `"user"`, which is what
    the older write paths hardcode and what `auth_enabled=False` (dev) means.

    Use this whenever a row records WHO did something a person is accountable
    for — a production sign-off, above all. Do not use it for robot bookkeeping
    that runs with no request at all.
    """
    u = getattr(getattr(request, "state", None), "user", None)
    if u is None:
        return "user"
    return (getattr(u, "display_name", "") or getattr(u, "username", "") or "user").strip() or "user"
