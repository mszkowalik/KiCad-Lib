"""KiCad HTTP Library endpoints (REST API v1).

Spec: https://dev-docs.kicad.org/en/apis-and-binding/http-libraries/
 - GET {root}/v1/                      -> {"categories": "", "parts": ""}
 - GET {root}/v1/categories.json      -> [{id, name, description?}]
 - GET {root}/v1/parts/category/{id}.json
 - GET {root}/v1/parts/{id}.json
All values must be strings; auth header is "Authorization: Token <token>".

The two parts endpoints return the SAME body per part (`part_payload`). The
spec allows a category listing to carry only {id, name, description}, but
KiCad treats a `fields` object as "this record is complete" and then never
issues the per-part request — which is the difference between 15 requests and
400+ to open the symbol chooser.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Query, Session, contains_eager, defer, joinedload, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.generator import base_hidden_maps, injected_props, schematic_field_visibility, sim_props, version_prop
from ..services.mirror import HIDDEN_LIFECYCLE, resolve_sim_links
from ..services.pcm import SIM_LIB_INSTALLED
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
            # deprecated/obsolete parts are platform-only (mirror.HIDDEN_LIFECYCLE)
            M.Component.lifecycle_state.notin_(HIDDEN_LIFECYCLE),
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
            # version_no only feeds the injected "7S Version" field — the
            # heavy columns must stay out of the chooser's critical path.
            joinedload(M.ComponentVersion.symbol_version).options(
                defer(M.SymbolVersion.source_text),
                defer(M.SymbolVersion.parsed),
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


def datasheets_by_component(db: Session, comp_ids) -> dict[int, list[M.Datasheet]]:
    """Every component's datasheet rows, one query, WITHOUT the stored PDFs.

    `injected_props` reads only `content_type` and `filename` off the current
    version, but `DatasheetVersion.data` holds the whole document — lazy-loading
    the relationship pulled a component's PDFs (megabytes) into memory just to
    decide whether a link should point at the local copy.
    """
    comp_ids = list(comp_ids)
    if not comp_ids:
        return {}
    rows = (
        db.query(M.Datasheet)
        .filter(M.Datasheet.component_id.in_(comp_ids))
        .options(selectinload(M.Datasheet.versions).defer(M.DatasheetVersion.data))
        .order_by(M.Datasheet.component_id, M.Datasheet.position)
        .all()
    )
    out: dict[int, list[M.Datasheet]] = {}
    for d in rows:
        out.setdefault(d.component_id, []).append(d)
    return out


def part_payload(cv, sheets: list[M.Datasheet], visible: dict[str, bool], sim_link: dict | None = None) -> dict:
    """One part in KiCad's part shape — the SAME body for the per-part endpoint
    and for each entry of a category listing.

    KiCad's `SelectAll` calls `setPartExtendedData` on every item it parses and
    takes a `fields` object as "this record is complete" (`detailsLoaded`), so a
    listing that carries this body costs the symbol chooser ZERO per-part
    requests. Serving the short {id, name, description} form instead made the
    chooser fetch `parts/{id}.json` once per part — 400+ serial round trips,
    minutes of waiting to open the dialog. Keep the two shapes identical.
    """
    props = props_dict(cv)
    # Link-derived Sim.* fields FIRST, so a component's own rows overwrite
    # them in the fields dict below — same override order as the generated
    # mirror symbols. Sim.Library is rewritten from the mirror-canonical
    # value to the PCM-installed path, the only one the client can resolve.
    entries = [
        (d["key"], SIM_LIB_INSTALLED if d["key"] == "Sim.Library" else d["value"])
        for d in sim_props(sim_link)
    ]
    # user properties + injected datasheet links (prices stay on the platform)
    entries += [(p.key, resolved_value(None if p.is_null else p.value, props)) for p in cv.properties]
    # Emit the footprint-derived name too, unless the component has its own row.
    if not any(p.key == "Footprint_Name" for p in cv.properties) and props.get("Footprint_Name"):
        entries.append(("Footprint_Name", props["Footprint_Name"]))
    entries += [(d["key"], d["value"]) for d in injected_props(sheets)]
    # Same "7S Version" field the generated mirror symbols carry — which
    # library versions a placed part was drawn with.
    entries += [(d["key"], d["value"]) for d in version_prop(
        cv.version_no,
        cv.symbol_version.version_no if cv.symbol_version else None,
        cv.footprint_version.version_no if cv.footprint_version else None,
    )]

    description = ""
    keywords = ""
    fields: dict[str, dict] = {}
    for key, val in entries:
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
            fields["value"] = {"value": val, "visible": "true" if visible.get(key) else "false"}
        else:
            fields[key] = {"value": val, "visible": "true" if visible.get(key) else "false"}

    return {
        "id": str(cv.component_id),
        "name": cv.component.name,
        # the component's BASE drawing — all components sharing a template
        # reuse one symbol, so the local library never needs per-part updates
        "symbolIdStr": f"{settings.httplib_symbol_lib}:{cv.base_component}",
        "description": description,
        "keywords": keywords,
        "fields": fields,
    }


def part_payloads(db: Session, versions: list) -> list[dict]:
    """`part_payload` for a whole page, with the two per-row lookups batched."""
    sheets = datasheets_by_component(db, {cv.component_id for cv in versions})
    # Field visibility MUST match the generated mirror symbols: base-symbol
    # effects plus the component's layout override. Keys absent from the map
    # (injected datasheet links, the derived Footprint_Name) are hidden, the
    # same default `apply_properties` gives a key the base symbol lacks.
    bases = base_hidden_maps(db, {cv.base_component for cv in versions})
    sim_links = resolve_sim_links(db, [])  # warnings surface on mirror writes, not here
    return [
        part_payload(
            cv,
            sheets.get(cv.component_id, []),
            schematic_field_visibility(db, cv, bases.get(cv.base_component) or {}),
            sim_links.get(cv.symbol_version.symbol_id) if cv.symbol_version else None,
        )
        for cv in versions
    ]


@router.get("/parts/category/{cat_id}.json", dependencies=[Depends(require_token)])
def parts_in_category(cat_id: int, db: Session = Depends(get_db)):
    versions = (
        library_versions(db)
        .filter(M.ComponentVersion.category_id == cat_id)
        .order_by(M.Component.name)
        .all()
    )
    return part_payloads(db, versions)


@router.get("/parts/{part_id}.json", dependencies=[Depends(require_token)])
def part_detail(part_id: int, db: Session = Depends(get_db)):
    comp = db.get(M.Component, part_id)
    if comp is None or not comp.in_library or comp.lifecycle_state in HIDDEN_LIFECYCLE:
        raise HTTPException(404, "part not found")
    cv = library_versions(db).filter(M.Component.id == part_id).first()
    if cv is None:
        raise HTTPException(404, "part has no published version")
    return part_payloads(db, [cv])[0]
