"""Rename a footprint or a base symbol, and move every reference with it.

A name in this platform is a REFERENCE, not only a label.
`ComponentVersion.base_component` holds a base symbol's name as a string, and a
component's `Footprint` property holds `7Sigma:<footprint name>`. Neither is a
foreign key, so renaming the row alone would leave every component pointing at
a template that no longer exists.

Design and the rejected alternatives:
[docs/decisions/0012](../../../docs/decisions/0012-rename-a-footprint-or-base-symbol-in-place.md).

Three properties this module must keep:

- **History is immutable.** Superseded geometry versions keep the old header
  and superseded component versions keep the old reference string. Those rows
  record what was published at the time, and rewriting them would make the
  database disagree with the git archive and the mirror history.
- **One transaction.** Between the row rename and the reference rewrite the
  library is inconsistent: the generated symbols would name a `.kicad_mod`
  that is no longer there. Everything up to the commit happens here, and the
  mirror is rebuilt once, afterwards. `services/geometry_proposals.py` is
  deliberately NOT reused for the geometry version even though it would parse
  and publish it for us — `_publish_geometry` commits, which would open that
  window.
- **A rename costs no verification.** `services/material.py` fingerprints pads,
  drills, layers and the courtyard for a footprint, and pin numbers and
  electrical types for a symbol. A name is in neither, so the geometry carry is
  automatic. The component side needs the `rename` pair threaded into
  `signoff.data_carries` — see the note there on why it is a mapping and not a
  new entry in `NON_MATERIAL_KEYS`.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from .. import models as M
from ..config import Settings
from . import material
from .geometry_proposals import (
    set_footprint_header,
    set_footprint_value,
    set_symbol_entry_name,
)
from .mirror import top_level_of, update_mirror_footprint, update_mirror_symbols, write_manifest
from .publish import publish_component_version, publish_geometry_version
from .repoint import clone_properties

#: A template name reaches KiCad as a library identifier and as a file name, so
#: it may not carry a path separator, a library separator or a quote.
_BAD_NAME = re.compile(r'[:/\\"\x00-\x1f]')

_COMMENT = "Automatic: the {kind} was renamed from {old} to {new}. Nothing else changed."


class RenameError(ValueError):
    """A guard refused the rename. The message is shown to the user."""


def _current(parent):
    if parent is None or parent.current_version_id is None:
        return None
    return next((v for v in parent.versions if v.id == parent.current_version_id), None)


def _versions(db: Session, comp: M.Component) -> list[M.ComponentVersion]:
    """Query the version rows rather than reading `comp.versions`.

    The session runs `expire_on_commit=False`, so a row added here is not
    appended to an already-loaded relationship — the same trap
    `services/repoint.py` documents.
    """
    return db.query(M.ComponentVersion).filter_by(component_id=comp.id).all()


def _check_name(db: Session, kind: str, parent, new_name: str) -> str:
    new_name = (new_name or "").strip()
    if not new_name:
        raise RenameError("the new name must not be empty")
    if len(new_name) > 200:
        raise RenameError("a name is at most 200 characters")
    if _BAD_NAME.search(new_name):
        raise RenameError(
            "a name may not contain ':', '/', '\\' or a quote — the 7Sigma: prefix is added "
            "by the platform and is not part of the name"
        )
    if new_name.startswith(".") or new_name.endswith("."):
        raise RenameError("a name may not start or end with a dot")
    if new_name == parent.name:
        raise RenameError(f"{parent.name!r} already has that name")
    model = M.Footprint if kind == "footprint" else M.Symbol
    if db.query(model).filter_by(name=new_name).first() is not None:
        raise RenameError(
            f"a {kind} called {new_name!r} already exists — a rename never merges two rows"
        )
    return new_name


def _renamed_source(kind: str, source_text: str, old_name: str, new_name: str) -> str:
    if kind == "footprint":
        return set_footprint_value(set_footprint_header(source_text, new_name), old_name, new_name)
    return set_symbol_entry_name(source_text, new_name)


def _affected(db: Session, kind: str, old_name: str) -> list[tuple[M.Component, M.ComponentVersion]]:
    """Components whose CURRENT version names the template being renamed.

    Selected on the REFERENCE, not on the pinned version id: the reference is
    what this module rewrites, and a component can carry one without pinning
    the geometry (a BOM-only part, or a footprint pinned through an older
    version row).
    """
    out: list[tuple[M.Component, M.ComponentVersion]] = []
    for comp in db.query(M.Component).all():
        cv = _current(comp)
        if cv is None:
            continue
        if kind == "symbol":
            if cv.base_component == old_name:
                out.append((comp, cv))
        else:
            if any(p.key == "Footprint" and p.value == f"7Sigma:{old_name}" for p in cv.properties):
                out.append((comp, cv))
    return out


def _rewrite_category_defaults(db: Session, kind: str, old_name: str, new_name: str) -> list[str]:
    """Move the name on in `categories.defaults`.

    These maps came from the retired YAML pipeline and nothing reads them today
    — only `has_defaults` reaches the UI. They are rewritten anyway, because a
    register that holds a name which no longer exists misleads the next reader,
    and this is the cheapest moment to keep it honest.
    """
    touched: list[str] = []
    for cat in db.query(M.Category).filter(M.Category.parent_id.is_(None)).all():
        d = cat.defaults
        if not isinstance(d, dict):
            continue
        changed = False
        if kind == "symbol":
            if d.get("base_component") == old_name:
                d["base_component"] = new_name
                changed = True
        else:
            fmap = d.get("footprint_map")
            if isinstance(fmap, dict):
                for pkg, ref in list(fmap.items()):
                    if ref == f"7Sigma:{old_name}":
                        fmap[pkg] = f"7Sigma:{new_name}"
                        changed = True
        if changed:
            flag_modified(cat, "defaults")
            touched.append(cat.name)
    return touched


def rename_geometry(db: Session, settings: Settings, kind: str, parent,
                    new_name: str, actor: str = "user", comment: str = "") -> dict:
    """Rename one footprint or base symbol. This function owns the transaction.

    Unlike `services/publish.py`, which leaves the transaction to its caller,
    a rename is the whole operation: the row, its geometry, every reference to
    it and the mirror have to move together or not at all.
    """
    if kind not in ("footprint", "symbol"):
        raise RenameError(f"unknown kind {kind!r}")
    old_name = parent.name
    new_name = _check_name(db, kind, parent, new_name)

    cur = _current(parent)
    if cur is None:
        raise RenameError(
            f"{old_name!r} has no published version — there is nothing to rename it to. "
            "Publish a version first."
        )

    note = (comment or "").strip() or _COMMENT.format(kind=kind, old=old_name, new=new_name)
    rename = (kind, old_name, new_name)

    # ---- 1. the geometry version carrying the new name ---------------------
    source_text = _renamed_source(kind, cur.source_text, old_name, new_name)
    if source_text == cur.source_text:
        raise RenameError(
            f"the {kind} text carries no name to rewrite — it is not a whole "
            f".kicad_{'mod' if kind == 'footprint' else 'sym'}"
        )
    new_no = max(v.version_no for v in _geometry_versions(db, kind, parent)) + 1
    version = _new_version(kind, parent, new_no, source_text, actor, note)
    db.add(version)
    db.flush()
    # recheck_required=False: the drawing is byte-identical apart from its own
    # name, so the material fingerprint cannot have moved and the verification
    # carries. Stating it explicitly puts the actor on the waiver in the audit
    # trail rather than leaving it to the fingerprint comparison.
    geo = publish_geometry_version(db, kind, parent, version, actor,
                                   recheck_required=False, recheck_note=note)

    # ---- 2. the row itself -------------------------------------------------
    # After the publish, so the version's own audit row still names the row as
    # it was when the version was filed.
    parent.name = new_name
    db.flush()

    # ---- 3. every component that references it -----------------------------
    published: list[dict] = []
    for comp, live in _affected(db, kind, old_name):
        cv = M.ComponentVersion(
            component_id=comp.id,
            version_no=max(v.version_no for v in _versions(db, comp)) + 1,
            base_component=new_name if kind == "symbol" else live.base_component,
            symbol_version_id=live.symbol_version_id,
            footprint_version_id=live.footprint_version_id,
            category_id=live.category_id,
            removed_properties=live.removed_properties,
            status="published",
            created_by=actor,
            comment=note,
        )
        db.add(cv)
        db.flush()
        clone_properties(db, live, cv)
        if kind == "footprint":
            for p in cv.properties:
                if p.key == "Footprint" and p.value == f"7Sigma:{old_name}":
                    p.value = f"7Sigma:{new_name}"
        db.flush()
        res = publish_component_version(db, comp, cv, actor=actor, rename=rename)
        published.append({
            "component": comp.name,
            "version_no": cv.version_no,
            "signoff": res["signoff"],
            "review_carry": res["review_carry"],
        })

    # ---- 4. the stale references nothing reads -----------------------------
    categories = _rewrite_category_defaults(db, kind, old_name, new_name)

    # ---- 5. one audit row for the whole operation --------------------------
    # Unversioned in the sense that no single version row records it, so this
    # row is the revert instruction: renaming back is the same call with the
    # names swapped.
    db.add(M.AuditLog(
        actor=actor, action=f"{kind}.rename", entity_type=kind, entity_id=str(parent.id),
        details={"old_name": old_name, "new_name": new_name,
                 "version_no": version.version_no,
                 "components": [p["component"] for p in published],
                 "categories": categories, "note": note},
    ))
    db.commit()

    # ---- 6. the mirror, once, after the commit -----------------------------
    # The generators re-read the database, so this cannot run inside the
    # transaction. `db.expire_all()` for the reason api/app/services/CLAUDE.md
    # gives: rows added above are not in the loaded relationships.
    db.expire_all()
    warnings: list[str] = list(geo.get("warnings") or [])
    removed = False
    if kind == "footprint":
        old_path = settings.mirror_dir / "Footprints" / "7Sigma.pretty" / f"{old_name}.kicad_mod"
        if old_path.exists():
            old_path.unlink()
            removed = True
        fp_mirror = update_mirror_footprint(db, settings, new_name)
        warnings += fp_mirror.get("warnings") or []
    tops: set[str] = set()
    for comp in db.query(M.Component).all():
        cv = _current(comp)
        if cv is None or cv.category is None:
            continue
        if kind == "symbol":
            if cv.base_component == new_name:
                tops.add(top_level_of(cv.category).name)
        elif any(p.key == "Footprint" and p.value == f"7Sigma:{new_name}" for p in cv.properties):
            tops.add(top_level_of(cv.category).name)
    # Always call it, even with no affected category: `write_symbol_libs`
    # rebuilds 7Sigma_Base.kicad_sym whenever `_base_symbol_fingerprint` moved,
    # which a symbol rename always does, and that is the only place a base
    # symbol's entry name reaches KiCad.
    sym_mirror = update_mirror_symbols(db, settings, tops)
    warnings += sym_mirror.get("warnings") or []

    return {
        "ok": True, "kind": kind, "id": parent.id,
        "old_name": old_name, "new_name": new_name,
        "version_no": version.version_no,
        "components": published,
        "categories_updated": categories,
        "mirror_file_removed": removed,
        "rebuilt_libraries": sorted(tops),
        "mirror_warnings": warnings,
        "manifest_files": write_manifest(settings),
    }


def _geometry_versions(db: Session, kind: str, parent):
    model = M.FootprintVersion if kind == "footprint" else M.SymbolVersion
    col = model.footprint_id if kind == "footprint" else model.symbol_id
    return db.query(model).filter(col == parent.id).all()


def _new_version(kind: str, parent, version_no: int, source_text: str, actor: str, comment: str):
    """Build the version row, with the derived caches the publish path expects.

    `parsed` is re-derived rather than copied from the outgoing version: it
    carries the name for a symbol, and re-deriving is what keeps the cache
    honest if a future parser learns to record more.
    """
    from .parse_cache import footprint_parsed, symbol_parsed

    if kind == "footprint":
        parsed = footprint_parsed(source_text)
        return M.FootprintVersion(
            footprint_id=parent.id, version_no=version_no, source_text=source_text,
            parsed=parsed, models=parsed.get("models"), status="draft",
            created_by=actor, comment=comment,
            material_sha=material.material_sha("footprint", source_text),
        )
    return M.SymbolVersion(
        symbol_id=parent.id, version_no=version_no, source_text=source_text,
        parsed=symbol_parsed(source_text), status="draft",
        created_by=actor, comment=comment,
        material_sha=material.material_sha("symbol", source_text),
    )
