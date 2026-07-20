"""Component browsing + in-place editing: list, detail, per-version data,
SVG previews, and save-as-new-version."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.generator import (
    PRICE_KEY_TO_COL,
    BaseSymbolProvider,
    build_component_symbol,
    build_library_text,
    injected_props,
    load_symbol_lib_from_text,
    property_row_to_dict,
)
from ..services.mirror import top_level_of, update_mirror_symbols
from ..services.render import render_svg
from .util import audit, category_and_descendant_ids, category_path, current_version, props_dict, resolved_value

router = APIRouter(prefix="/api/components", tags=["components"])

def _price_row(db: Session, component_id: int) -> M.ComponentPrice | None:
    return db.query(M.ComponentPrice).filter_by(component_id=component_id).first()


def _datasheet_rows(db: Session, component_id: int) -> list[M.Datasheet]:
    return (
        db.query(M.Datasheet)
        .filter_by(component_id=component_id, archived=False)
        .order_by(M.Datasheet.position)
        .all()
    )


def _prices_json(p: M.ComponentPrice | None) -> dict | None:
    if p is None:
        return None
    return {
        "price_1": p.price_1,
        "price_100": p.price_100,
        "price_bulk": p.price_bulk,
        "bulk_qty": p.bulk_qty,
        "source": p.source,
        "updated": p.updated,
    }


def _datasheets_json(rows: list[M.Datasheet]) -> list[dict]:
    out = []
    for d in rows:
        cur = next((v for v in d.versions if v.id == d.current_version_id), None)
        out.append({
            "id": d.id,
            "position": d.position,
            "label": d.label,
            "source_url": d.source_url,
            "has_file": cur is not None,
            "pdf_version_no": cur.version_no if cur else None,
            "filename": cur.filename if cur else None,
            "content_type": cur.content_type if cur else None,
            "size_bytes": cur.size_bytes if cur else None,
            "fetched_at": cur.fetched_at.isoformat() if cur else None,
            "versions": [
                {"version_no": v.version_no, "fetched_at": v.fetched_at.isoformat(),
                 "size_bytes": v.size_bytes, "sha256": v.sha256[:12]}
                for v in d.versions
            ],
        })
    return out


def _load_components(db: Session) -> list[M.Component]:
    return (
        db.query(M.Component)
        .options(
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties),
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.category),
        )
        .order_by(M.Component.name)
        .all()
    )


@router.get("")
def list_components(
    q: str | None = None,
    category_id: int | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(1000, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    comps = _load_components(db)
    cat_ids = category_and_descendant_ids(db, category_id) if category_id else None
    price_map = {p.component_id: (p.price_bulk, p.bulk_qty) for p in db.query(M.ComponentPrice)}
    ds_map: dict[int, str] = {}
    for d in db.query(M.Datasheet).order_by(M.Datasheet.position.desc()):
        if d.source_url:
            ds_map[d.component_id] = d.source_url  # descending order → position 0 wins

    items = []
    needle = q.lower() if q else None
    for comp in comps:
        cv = current_version(comp)
        if cv is None:
            continue
        if cat_ids is not None and cv.category_id not in cat_ids:
            continue
        props = props_dict(cv)
        if needle and needle not in comp.name.lower() and not any(
            needle in (v or "").lower() for v in props.values()
        ):
            continue
        price_bulk, bulk_qty = price_map.get(comp.id, (None, None))
        items.append(
            {
                "id": comp.id,
                "name": comp.name,
                "in_library": comp.in_library,
                "mfg_pn": props.get("Manufacturer Part Number 1") or "",
                "manufacturer": props.get("Manufacturer 1") or "",
                "version_no": cv.version_no,
                "status": cv.status,
                "category_id": cv.category_id,
                "category_path": category_path(cv.category),
                "base_component": cv.base_component,
                "description": resolved_value(props.get("ki_description"), props),
                "value": props.get("Value") or "",
                "footprint": (props.get("Footprint") or "").removeprefix("7Sigma:"),
                "lcsc": props.get("LCSC Part") or "",
                "price_bulk": price_bulk or "",
                "bulk_qty": bulk_qty or "",
                "datasheet": ds_map.get(comp.id) or "",
            }
        )

    total = len(items)
    start = (page - 1) * page_size
    return {"total": total, "page": page, "page_size": page_size, "items": items[start : start + page_size]}


def _get_component(db: Session, comp_id: int) -> M.Component:
    comp = (
        db.query(M.Component)
        .options(
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties),
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.category),
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.symbol_version),
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.footprint_version),
        )
        .filter(M.Component.id == comp_id)
        .first()
    )
    if comp is None:
        raise HTTPException(404, "component not found")
    return comp


def _version_summary(cv: M.ComponentVersion) -> dict:
    sv, fv = cv.symbol_version, cv.footprint_version
    return {
        "version_no": cv.version_no,
        "status": cv.status,
        "created_at": cv.created_at.isoformat(),
        "created_by": cv.created_by,
        "approved_by": cv.approved_by,
        "comment": cv.comment,
        "category_id": cv.category_id,
        "category_path": category_path(cv.category),
        "base_component": cv.base_component,
        "symbol": {"name": sv.symbol.name, "version_no": sv.version_no} if sv else None,
        "footprint": {"name": fv.footprint.name, "version_no": fv.version_no} if fv else None,
    }


@router.get("/{comp_id}")
def component_detail(comp_id: int, db: Session = Depends(get_db)):
    comp = _get_component(db, comp_id)
    cv = current_version(comp)
    return {
        "id": comp.id,
        "name": comp.name,
        "in_library": comp.in_library,
        "current_version_no": cv.version_no if cv else None,
        "versions": [_version_summary(v) for v in comp.versions],
    }


def _get_version(comp: M.Component, version_no: int) -> M.ComponentVersion:
    cv = next((v for v in comp.versions if v.version_no == version_no), None)
    if cv is None:
        raise HTTPException(404, "version not found")
    return cv


@router.get("/{comp_id}/versions/{version_no}")
def version_detail(comp_id: int, version_no: int, db: Session = Depends(get_db)):
    comp = _get_component(db, comp_id)
    cv = _get_version(comp, version_no)
    props = props_dict(cv)
    return {
        **_version_summary(cv),
        "component_id": comp.id,
        "component_name": comp.name,
        # Component-scoped (identical across versions): auto-managed data.
        "prices": _prices_json(_price_row(db, comp.id)),
        "datasheets": _datasheets_json(_datasheet_rows(db, comp.id)),
        # Version-scoped pins: which exact PDF content THIS version used.
        "datasheet_pins": [
            {"datasheet_id": link.datasheet_id,
             "label": (db.get(M.Datasheet, link.datasheet_id) or M.Datasheet(label="?")).label,
             "pdf_version_no": (
                 db.get(M.DatasheetVersion, link.datasheet_version_id).version_no
                 if link.datasheet_version_id else None
             )}
            for link in db.query(M.ComponentVersionDatasheet).filter_by(component_version_id=cv.id)
        ],
        "removed_properties": cv.removed_properties or [],
        "properties": [
            {
                "position": p.position,
                "key": p.key,
                "value": p.value,
                "is_null": p.is_null,
                "hide": p.hide,
                "show_name": p.show_name,
                "layout": p.layout,
                "resolved_value": resolved_value(None if p.is_null else p.value, props),
            }
            for p in cv.properties
        ],
    }


class PropertyIn(BaseModel):
    key: str
    value: str | None = None
    is_null: bool = False
    hide: bool = True
    show_name: bool = False
    layout: dict | None = None


class DatasheetIn(BaseModel):
    id: int | None = None  # existing row id — keeps the local file if URL unchanged
    label: str = "Datasheet"
    source_url: str | None = None


class VersionCreate(BaseModel):
    base_component: str
    category_id: int
    properties: list[PropertyIn]
    removed_properties: list[str] | None = None
    datasheets: list[DatasheetIn] | None = None  # None = leave unchanged
    comment: str | None = None


@router.post("/{comp_id}/versions")
def create_version(comp_id: int, body: VersionCreate, db: Session = Depends(get_db)):
    """Save an edit as a NEW published version (the user saving IS the
    approval). The previous version stays forever; the current pointer
    advances; only the affected mirror libraries are regenerated."""
    comp = _get_component(db, comp_id)
    old_cv = current_version(comp)

    category = db.get(M.Category, body.category_id)
    if category is None:
        raise HTTPException(422, "category not found")

    # BOM-only parts (in_library=False) need no symbol — they never reach
    # the generated libraries; base_component may be empty.
    base_sym = None
    if comp.in_library or body.base_component.strip():
        base_sym = db.query(M.Symbol).filter_by(name=body.base_component).first()
        if base_sym is None or base_sym.current_version_id is None:
            if comp.in_library:
                raise HTTPException(422, f"base component {body.base_component!r} not found in base library")
            base_sym = None

    keys = [p.key.strip() for p in body.properties]
    if any(not k for k in keys):
        raise HTTPException(422, "property keys must not be empty")
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise HTTPException(422, f"duplicate property keys: {', '.join(sorted(dupes))}")
    managed = [k for k in keys if k in PRICE_KEY_TO_COL or k == "Datasheet" or k.startswith("Datasheet ")]
    if managed:
        raise HTTPException(
            422,
            f"{', '.join(sorted(set(managed)))}: prices and datasheets are managed separately "
            "(use the Prices/Datasheets panels), not as properties",
        )

    # The Footprint property drives the footprint pin, exactly like import.
    fp_version_id = None
    fp_value = next((p.value for p in body.properties if p.key == "Footprint" and not p.is_null), None) or ""
    if fp_value.startswith("7Sigma:"):
        fp = db.query(M.Footprint).filter_by(name=fp_value.split(":", 1)[1]).first()
        if fp is None:
            raise HTTPException(422, f"footprint {fp_value!r} has no footprint in the library")
        fp_version_id = fp.current_version_id
    elif fp_value and comp.in_library:
        raise HTTPException(422, f"footprint {fp_value!r} must use the 7Sigma: namespace")

    new_no = max((v.version_no for v in comp.versions), default=0) + 1
    cv = M.ComponentVersion(
        component_id=comp.id,
        version_no=new_no,
        base_component=body.base_component,
        symbol_version_id=base_sym.current_version_id if base_sym else None,
        footprint_version_id=fp_version_id,
        category_id=body.category_id,
        removed_properties=body.removed_properties or None,
        status="published",
        created_by="user",
        approved_by="user",
        comment=body.comment,
    )
    db.add(cv)
    db.flush()
    for pos, p in enumerate(body.properties):
        is_null = p.is_null or p.value is None
        db.add(M.ComponentProperty(
            component_version_id=cv.id,
            position=pos,
            key=p.key.strip(),
            value=None if is_null else str(p.value),
            is_null=is_null,
            hide=p.hide,
            show_name=p.show_name,
            layout=p.layout,
        ))
    comp.current_version_id = cv.id

    if body.datasheets is not None:
        old_rows = {d.id: d for d in _datasheet_rows(db, comp.id)}
        seen_ids: set[int] = set()
        # park active rows on NULL positions first to avoid unique collisions
        for old in old_rows.values():
            old.position = None
        db.flush()
        for pos, d in enumerate(body.datasheets):
            keep = old_rows.get(d.id) if d.id is not None else None
            if keep is not None:
                seen_ids.add(keep.id)
                keep.position = pos
                keep.label = d.label.strip() or "Datasheet"
                keep.source_url = d.source_url or None  # history (versions) stays either way
                keep.archived = False
            else:
                db.add(M.Datasheet(component_id=comp.id, position=pos,
                                   label=d.label.strip() or "Datasheet",
                                   source_url=d.source_url or None))
        # rows removed in the edit: archive (PDF history + pins preserved)
        for old in old_rows.values():
            if old.id not in seen_ids:
                old.archived = True
                old.position = None

    db.flush()
    from ..services.datasheet_store import pin_datasheets

    pin_datasheets(db, cv)  # record which PDF versions this component version uses
    audit(db, "component.edit", "component", comp.id,
          {"version_no": new_no, "comment": body.comment})
    db.commit()

    if comp.in_library:
        # Incremental mirror update: old top-level lib + new one (may differ on move)
        tops = {top_level_of(category).name}
        if old_cv is not None:
            tops.add(top_level_of(old_cv.category).name)
        # The new version was linked via FK, not via the relationship — expire the
        # session BEFORE the mirror regenerates, or it sees stale collections and
        # silently drops the just-edited component from the library file.
        db.expire_all()
        mirror_result = update_mirror_symbols(db, settings, tops)
    else:
        # BOM-only part — never in the generated libraries, nothing to rebuild
        mirror_result = {"symbol_libs": 0, "components_in_libs": 0, "warnings": []}

    comp = _get_component(db, comp_id)  # reload with relationships
    cv = next(v for v in comp.versions if v.version_no == new_no)
    return {
        **_version_summary(cv),
        "component_id": comp.id,
        "component_name": comp.name,
        "mirror": {k: v for k, v in mirror_result.items() if k != "warnings"},
        "mirror_warnings": mirror_result["warnings"],
    }


@router.get("/{comp_id}/versions/{version_no}/symbol.svg")
def symbol_svg(comp_id: int, version_no: int, db: Session = Depends(get_db)):
    comp = _get_component(db, comp_id)
    cv = _get_version(comp, version_no)
    if cv.symbol_version is None:
        raise HTTPException(404, "this version has no pinned symbol")
    provider = BaseSymbolProvider()
    sv = cv.symbol_version
    template = provider.get(cv.base_component, sv.source_text, cache_key=f"{cv.base_component}@{sv.id}")
    meta_lib = load_symbol_lib_from_text(sv.source_text)
    props = [property_row_to_dict(p) for p in cv.properties] + injected_props(
        _datasheet_rows(db, comp.id)
    )
    sym = build_component_symbol(template, comp.name, props, cv.removed_properties)
    lib_text = build_library_text(meta_lib, [sym])
    svg = render_svg("symbol", comp.name, lib_text)
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "max-age=300"})


@router.get("/{comp_id}/versions/{version_no}/footprint.svg")
def footprint_svg(comp_id: int, version_no: int, db: Session = Depends(get_db)):
    comp = _get_component(db, comp_id)
    cv = _get_version(comp, version_no)
    fv = cv.footprint_version
    if fv is None:
        raise HTTPException(404, "this version has no pinned footprint")
    svg = render_svg("footprint", fv.footprint.name, fv.source_text)
    return Response(content=svg, media_type="image/svg+xml", headers={"Cache-Control": "max-age=300"})


@router.get("/{comp_id}/versions/{version_no}/footprint.glb")
def footprint_glb(comp_id: int, version_no: int, db: Session = Depends(get_db)):
    """3D board view: footprint on a small board slab with copper, mask,
    silkscreen and the placed 3D model — rendered by kicad-cli as GLB."""
    comp = _get_component(db, comp_id)
    cv = _get_version(comp, version_no)
    fv = cv.footprint_version
    if fv is None:
        raise HTTPException(404, "this version has no pinned footprint")
    data = render_svg("footprint3d", fv.footprint.name, fv.source_text)
    return Response(content=data, media_type="model/gltf-binary",
                    headers={"Cache-Control": "max-age=300"})


class ComponentCreate(VersionCreate):
    name: str
    # False = BOM-only part (no symbol/footprint, never in KiCad libraries)
    in_library: bool = True


@router.post("")
def create_component(body: ComponentCreate, db: Session = Depends(get_db)):
    """Manually add a new component (v1 published — the user creating IS the
    approval). Jaravis proposals go through the draft flow instead."""
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "component name must not be empty")
    if db.query(M.Component).filter_by(name=name).first():
        raise HTTPException(409, f"component {name!r} already exists (names are globally unique)")
    comp = M.Component(name=name, in_library=body.in_library)
    db.add(comp)
    db.flush()
    audit(db, "component.create", "component", comp.id,
          {"name": name, "in_library": body.in_library})
    db.commit()
    return create_version(comp.id, body, db)


class InLibraryPatch(BaseModel):
    in_library: bool


@router.patch("/{comp_id}/in-library")
def set_in_library(comp_id: int, body: InLibraryPatch, db: Session = Depends(get_db)):
    """Flip a component between library part and BOM-only part. Turning a
    part back INTO a library part requires a pinned symbol."""
    comp = _get_component(db, comp_id)
    if comp.in_library == body.in_library:
        return {"id": comp.id, "in_library": comp.in_library}
    cv = current_version(comp)
    if body.in_library and (cv is None or cv.symbol_version_id is None):
        raise HTTPException(422, "cannot move to the library: no pinned symbol — edit the "
                                 "component with a base symbol first")
    comp.in_library = body.in_library
    audit(db, "component.in_library", "component", comp.id, {"in_library": body.in_library})
    db.commit()
    if cv is not None:
        update_mirror_symbols(db, settings, {top_level_of(cv.category).name})
    return {"id": comp.id, "in_library": comp.in_library}


@router.post("/{comp_id}/files")
async def add_file(
    comp_id: int,
    label: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Attach an uploaded file (drawing, STEP, extra doc, …) to a component as
    a new datasheet-style row; bumps the component version so the file is
    pinned from this version on."""
    from ..services.datasheet_store import add_component_file

    comp = _get_component(db, comp_id)
    data = await file.read()
    if not data:
        raise HTTPException(422, "uploaded file is empty")
    label = label.strip()
    if not label:
        raise HTTPException(422, "label must not be empty")
    result = add_component_file(db, comp, label, data, file.filename, file.content_type)

    # New row appears in the generated symbol ("Datasheet N" field) — refresh.
    # expire_all first: the session does not expire on commit and the bump adds
    # the new version via db.add(), so the preloaded comp.versions is stale and
    # current_version() would come back None (skipping the mirror silently).
    db.expire_all()
    cv = current_version(comp)
    if cv is not None:
        update_mirror_symbols(db, settings, {top_level_of(cv.category).name})
    return {**result, "datasheets": _datasheets_json(_datasheet_rows(db, comp.id))}


_MODEL_PREFIX_MARKERS = ("${SEVENSIGMA_DIR}/3DModels/", "3DModels/")


@router.get("/{comp_id}/versions/{version_no}/models3d")
def models3d(comp_id: int, version_no: int, db: Session = Depends(get_db)):
    """3D model files referenced by this version's pinned footprint, as URLs
    into the file mirror (/files/3DModels/...) for the browser 3D viewer."""
    comp = _get_component(db, comp_id)
    cv = _get_version(comp, version_no)
    fv = cv.footprint_version
    if fv is None:
        return []
    out = []
    for raw in fv.models or []:
        path = str(raw).replace("\\", "/")
        rel = None
        for marker in _MODEL_PREFIX_MARKERS:
            if marker in path:
                rel = path.split(marker, 1)[1]
                break
        if not rel:
            continue
        m = db.query(M.Model3D).filter_by(rel_path=rel).first()
        if m is None:
            continue
        out.append({
            "name": rel.rsplit("/", 1)[-1],
            "url": f"/files/3DModels/{rel}",
            "size_bytes": m.size_bytes,
        })
    return out
