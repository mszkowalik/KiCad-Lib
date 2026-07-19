"""KiCad HTTP Library endpoints (REST API v1).

Spec: https://dev-docs.kicad.org/en/apis-and-binding/http-libraries/
 - GET {root}/v1/                      -> {"categories": "", "parts": ""}
 - GET {root}/v1/categories.json      -> [{id, name, description?}]
 - GET {root}/v1/parts/category/{id}.json
 - GET {root}/v1/parts/{id}.json
All values must be strings; auth header is "Authorization: Token <token>".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.generator import injected_props
from ..services.mirror import top_level_of
from .util import category_path, current_version, props_dict, resolved_value

router = APIRouter(prefix="/kicad/v1", tags=["kicad-http-library"])


def require_token(authorization: str = Header(default="")):
    if authorization != f"Token {settings.httplib_token}":
        raise HTTPException(401, "invalid or missing token")


@router.get("", dependencies=[Depends(require_token)])
@router.get("/", dependencies=[Depends(require_token)])
def root():
    return {"categories": "", "parts": ""}


@router.get("/categories.json", dependencies=[Depends(require_token)])
def categories(db: Session = Depends(get_db)):
    cats = db.query(M.Category).order_by(M.Category.position, M.Category.name).all()
    return [{"id": str(c.id), "name": category_path(c)} for c in cats]


@router.get("/parts/category/{cat_id}.json", dependencies=[Depends(require_token)])
def parts_in_category(cat_id: int, db: Session = Depends(get_db)):
    comps = (
        db.query(M.Component)
        .options(selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties))
        .order_by(M.Component.name)
        .all()
    )
    out = []
    for comp in comps:
        if not comp.in_library:
            continue  # BOM-only part — not offered to KiCad
        cv = current_version(comp)
        if cv is None or cv.category_id != cat_id:
            continue
        props = props_dict(cv)
        out.append(
            {
                "id": str(comp.id),
                "name": comp.name,
                "description": resolved_value(props.get("ki_description"), props),
            }
        )
    return out


@router.get("/parts/{part_id}.json", dependencies=[Depends(require_token)])
def part_detail(part_id: int, db: Session = Depends(get_db)):
    comp = (
        db.query(M.Component)
        .options(
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties),
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.category),
        )
        .filter(M.Component.id == part_id)
        .first()
    )
    if comp is None or not comp.in_library:
        raise HTTPException(404, "part not found")
    cv = current_version(comp)
    if cv is None:
        raise HTTPException(404, "part has no published version")

    props = props_dict(cv)
    top = top_level_of(cv.category)
    nickname = settings.symbol_lib_nickname_template.format(category=top.name)

    price = db.query(M.ComponentPrice).filter_by(component_id=comp.id).first()
    sheets = db.query(M.Datasheet).filter_by(component_id=comp.id).order_by(M.Datasheet.position).all()

    # user properties + injected auto-managed fields (prices, datasheets)
    entries = [(p.key, resolved_value(None if p.is_null else p.value, props), p.hide) for p in cv.properties]
    entries += [(d["key"], d["value"], True) for d in injected_props(price, sheets)]

    description = ""
    keywords = ""
    fields: dict[str, dict] = {}
    for key, val, hide in entries:
        if key == "ki_description":
            description = val
        elif key == "ki_keywords":
            keywords = val
        elif key == "ki_fp_filters":
            continue  # not part of the fields payload
        elif key == "Footprint":
            fields["footprint"] = {"value": val, "visible": "false"}
        elif key == "Datasheet":
            fields["datasheet"] = {"value": val, "visible": "false"}
        elif key == "Value":
            fields["value"] = {"value": val, "visible": "true"}
        else:
            fields[key] = {"value": val, "visible": "false" if hide else "true"}

    return {
        "id": str(comp.id),
        "name": comp.name,
        "symbolIdStr": f"{nickname}:{comp.name}",
        "description": description,
        "keywords": keywords,
        "fields": fields,
    }
