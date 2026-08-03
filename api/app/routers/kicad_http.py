"""KiCad HTTP Library endpoints (REST API v1).

Spec: https://dev-docs.kicad.org/en/apis-and-binding/http-libraries/
 - GET {root}/v1/                      -> {"categories": "", "parts": ""}
 - GET {root}/v1/categories.json      -> [{id, name, description?}]
 - GET {root}/v1/parts/category/{id}.json
 - GET {root}/v1/parts/{id}.json
All values must be strings; auth header is "Authorization: Token <token>".
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Query, Session, contains_eager, defer, joinedload, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.generator import injected_props
from .util import category_path, props_dict, resolved_value

router = APIRouter(prefix="/kicad/v1", tags=["kicad-http-library"])


def require_token(request: Request, authorization: str = Header(default="")):
    """Accept a PERSONAL token, or the legacy shared one.

    `authgate.AuthGate` has already authenticated anything that reaches here
    when `auth_enabled` is on, and a personal token resolves to a user — so the
    only work left is to keep the pre-auth shared secret working, which is also
    the whole behaviour when auth is switched off for local development.

    Do NOT tighten this back to an equality test against `httplib_token`: that
    is what rejected every per-user `.kicad_httplib`.
    """
    if getattr(request.state, "user", None) is not None:
        return
    if settings.auth_legacy_tokens and settings.httplib_token and \
            authorization == f"Token {settings.httplib_token}":
        return
    raise HTTPException(401, "invalid or missing token")


def library_versions(db: Session) -> Query:
    """The live version of every component KiCad may see, one query.

    This is `current_version(comp)` + the `in_library` filter expressed in SQL
    instead of in Python. It has to be: KiCad's symbol chooser calls
    `parts/category/{id}.json` once per category when it opens, and the loop
    that loaded every component with every version and every property, then
    dropped 95% of them, cost ~0.3s per category — ~4s for 15 categories on
    327 components.

    `props_dict` reads `Footprint_Name` off the footprint, so the footprint
    version is eager-loaded WITHOUT its three heavy columns. `source_text`
    holds a whole `.kicad_mod` body, and lazy-loading one per component pulled
    the entire footprint corpus into every catalog response.
    """
    return (
        db.query(M.ComponentVersion)
        .join(M.Component, M.Component.id == M.ComponentVersion.component_id)
        .filter(
            M.ComponentVersion.id == M.Component.current_version_id,
            M.Component.in_library.is_(True),  # BOM-only part — not offered to KiCad
        )
        .options(
            # the join above is already the parent row — never re-fetch it per version
            contains_eager(M.ComponentVersion.component),
            selectinload(M.ComponentVersion.properties),
            joinedload(M.ComponentVersion.footprint_version).options(
                defer(M.FootprintVersion.source_text),
                defer(M.FootprintVersion.parsed),
                defer(M.FootprintVersion.models),
                joinedload(M.FootprintVersion.footprint),
            ),
        )
    )


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
    versions = (
        library_versions(db)
        .filter(M.ComponentVersion.category_id == cat_id)
        .order_by(M.Component.name)
        .all()
    )
    out = []
    for cv in versions:
        props = props_dict(cv)
        out.append(
            {
                "id": str(cv.component_id),
                "name": cv.component.name,
                "description": resolved_value(props.get("ki_description"), props),
            }
        )
    return out


@router.get("/parts/{part_id}.json", dependencies=[Depends(require_token)])
def part_detail(part_id: int, db: Session = Depends(get_db)):
    comp = db.get(M.Component, part_id)
    if comp is None or not comp.in_library:
        raise HTTPException(404, "part not found")
    cv = library_versions(db).filter(M.Component.id == part_id).first()
    if cv is None:
        raise HTTPException(404, "part has no published version")

    props = props_dict(cv)

    sheets = db.query(M.Datasheet).filter_by(component_id=comp.id).order_by(M.Datasheet.position).all()

    # user properties + injected datasheet links (prices stay on the platform)
    entries = [(p.key, resolved_value(None if p.is_null else p.value, props), p.hide) for p in cv.properties]
    # Emit the footprint-derived name too, unless the component has its own row.
    if not any(p.key == "Footprint_Name" for p in cv.properties) and props.get("Footprint_Name"):
        entries.append(("Footprint_Name", props["Footprint_Name"], True))
    entries += [(d["key"], d["value"], True) for d in injected_props(sheets)]

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
            # remap the repo's footprint-lib nickname to what the client's
            # fp-lib-table actually calls it (PCM installs register the
            # library as PCM_7Sigma — set FOOTPRINT_LIB_NICKNAME accordingly)
            if val and val.startswith("7Sigma:"):
                val = f"{settings.footprint_lib_nickname}:{val.split(':', 1)[1]}"
            fields["footprint"] = {"value": val, "visible": "false"}
        elif key == "Datasheet":
            fields["datasheet"] = {"value": val, "visible": "false"}
        elif key == "Value":
            fields["value"] = {"value": val, "visible": "false" if hide else "true"}
        else:
            fields[key] = {"value": val, "visible": "false" if hide else "true"}

    return {
        "id": str(comp.id),
        "name": comp.name,
        # the component's BASE drawing — all components sharing a template
        # reuse one symbol, so the local library never needs per-part updates
        "symbolIdStr": f"{settings.httplib_symbol_lib}:{cv.base_component}",
        "description": description,
        "keywords": keywords,
        "fields": fields,
    }
