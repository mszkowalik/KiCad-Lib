"""Jaravis — the library agent.

Runs on the Anthropic SDK's beta tool runner (custom DB tools, we host the
loop). THE GATE IS STRUCTURAL: Jaravis's write tools can only create DRAFT
component versions (proposals); publishing requires explicit user approval in
the proposals UI. Read tools answer questions about the library directly.

Auth: the anthropic client resolves credentials from the environment
(ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile).
"""
from __future__ import annotations

import json
import os

import anthropic
from anthropic import beta_tool

from .. import models as M
from ..config import settings
from ..db import SessionLocal
from ..routers.util import category_path, current_version, props_dict, resolved_value
from ..services.generator import PRICE_KEY_TO_COL
from ..services.lcsc import fetch_metadata

MODEL = settings.jaravis_model  # user preference: Sonnet; Opus via JARAVIS_MODEL
MAX_TOKENS = 16000

# Proposals created during the current chat call (single-user app).
LAST_PROPOSALS: list[dict] = []


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ------------------------------------------------------------------ read tools
@beta_tool
def search_components(query: str = "", category: str = "") -> str:
    """Search the component library. Returns a compact JSON list of matching
    components (max 50) with name, description, value, footprint and category.

    Args:
        query: Case-insensitive text matched against names and property values. Empty = all.
        category: Optional category name filter (e.g. "Resistor", "Diodes").
    """
    db = SessionLocal()
    try:
        out = []
        for comp in db.query(M.Component).order_by(M.Component.name):
            cv = current_version(comp)
            if cv is None:
                continue
            path = category_path(cv.category)
            if category and category.lower() not in path.lower():
                continue
            props = props_dict(cv)
            hay = comp.name.lower() + " " + " ".join((v or "").lower() for v in props.values())
            if query and query.lower() not in hay:
                continue
            out.append({
                "name": comp.name,
                "description": resolved_value(props.get("ki_description"), props),
                "value": props.get("Value") or "",
                "footprint": props.get("Footprint") or "",
                "category": path,
            })
            if len(out) >= 50:
                break
        return json.dumps({"count": len(out), "components": out})
    finally:
        db.close()


@beta_tool
def get_component(name: str) -> str:
    """Get full details of one component by exact name: ordered properties,
    base symbol, footprint, category, prices, datasheets and version history.

    Args:
        name: Exact component name (use search_components to find it first).
    """
    db = SessionLocal()
    try:
        comp = db.query(M.Component).filter_by(name=name).first()
        if comp is None:
            return json.dumps({"error": f"component {name!r} not found"})
        cv = current_version(comp)
        if cv is None:
            drafts = [v.version_no for v in comp.versions if v.status == "draft"]
            return json.dumps({"error": f"{name!r} has no published version", "draft_versions": drafts})
        price = db.query(M.ComponentPrice).filter_by(component_id=comp.id).first()
        points = (db.query(M.ComponentPricePoint).filter_by(component_id=comp.id)
                  .order_by(M.ComponentPricePoint.qty_from).all())
        supply = db.query(M.ComponentSupply).filter_by(component_id=comp.id).first()
        private = db.query(M.JlcStockItem).filter_by(component_id=comp.id).first()
        sheets = (db.query(M.Datasheet)
                  .filter_by(component_id=comp.id, archived=False)
                  .order_by(M.Datasheet.position).all())
        return json.dumps({
            "name": comp.name,
            "category": category_path(cv.category),
            "base_component": cv.base_component,
            "properties": [
                {"key": p.key, "value": None if p.is_null else p.value} for p in cv.properties
            ],
            "removed_properties": cv.removed_properties or [],
            "prices": None if price is None else {
                "@1": price.price_1, "@100": price.price_100, "@bulk": price.price_bulk,
                "bulk_qty": price.bulk_qty, "source": price.source, "updated": price.updated,
            },
            "price_ladder": [
                {"source": p.source, "qty_from": p.qty_from, "unit_price": p.unit_price,
                 "currency": p.currency}
                for p in points
            ],
            "stock": {
                "lcsc_retail": supply.stock if supply else None,
                "jlcpcb_assembly": supply.jlc_stock if supply else None,
                "private_jlc_library": private.qty if private else 0,
                "moq": supply.moq if supply else None,
                "checked_at": (supply.checked_at.isoformat()
                               if supply and supply.checked_at else None),
            },
            "datasheets": [
                {"label": d.label, "url": d.source_url,
                 "has_local_copy": d.current_version_id is not None}
                for d in sheets
            ],
            "versions": [
                {"version_no": v.version_no, "status": v.status, "created_by": v.created_by,
                 "comment": v.comment}
                for v in comp.versions
            ],
            "user_notes": [
                {"author": c.author, "date": c.created_at.date().isoformat(), "note": c.body}
                for c in db.query(M.ComponentComment).filter_by(component_id=comp.id)
                .order_by(M.ComponentComment.created_at)
            ],
        })
    finally:
        db.close()


@beta_tool
def list_categories() -> str:
    """List the category tree (id, full path, component count per category)."""
    db = SessionLocal()
    try:
        cats = db.query(M.Category).order_by(M.Category.position, M.Category.name).all()
        return json.dumps([{"id": c.id, "path": category_path(c)} for c in cats])
    finally:
        db.close()


@beta_tool
def list_base_symbols(query: str = "") -> str:
    """List available base symbols (graphical templates) with pin counts.

    Args:
        query: Optional case-insensitive name filter.
    """
    db = SessionLocal()
    try:
        out = []
        for s in db.query(M.Symbol).order_by(M.Symbol.name):
            if query and query.lower() not in s.name.lower():
                continue
            cur = next((v for v in s.versions if v.id == s.current_version_id), None)
            out.append({"name": s.name, "pins": (cur.parsed or {}).get("pin_count") if cur else None})
        return json.dumps(out[:150])
    finally:
        db.close()


@beta_tool
def list_footprints(query: str = "") -> str:
    """List available footprints (7Sigma library) with pad counts.

    Args:
        query: Optional case-insensitive name filter.
    """
    db = SessionLocal()
    try:
        out = []
        for f in db.query(M.Footprint).order_by(M.Footprint.name):
            if query and query.lower() not in f.name.lower():
                continue
            cur = next((v for v in f.versions if v.id == f.current_version_id), None)
            out.append({"name": f.name, "pads": (cur.parsed or {}).get("pad_count") if cur else None})
        return json.dumps(out[:150])
    finally:
        db.close()


@beta_tool
def get_skill(name: str) -> str:
    """Read the CURRENT content of one of your skill documents by name
    (e.g. "conventions-library", "conventions-footprints"). Use before proposing
    an update — propose_skill_update replaces the full content.

    Args:
        name: Exact skill name.
    """
    db = SessionLocal()
    try:
        s = db.query(M.Skill).filter_by(name=name.strip()).first()
        if s is None:
            names = [x.name for x in db.query(M.Skill).order_by(M.Skill.name)]
            return json.dumps({"error": f"skill {name!r} not found", "available": names})
        cur = next((v for v in s.versions if v.id == s.current_version_id), None)
        return json.dumps({"name": s.name, "version_no": cur.version_no if cur else None,
                           "content": cur.content if cur else ""})
    finally:
        db.close()


@beta_tool
def propose_skill_update(skill_name: str, content: str, comment: str) -> str:
    """Propose an update to one of your skill documents as a DRAFT — the user
    must approve it in the Proposals view before it takes effect. Use this
    when the user asks you to remember a rule/convention, or when you learn a
    lasting lesson worth recording. content REPLACES the whole document —
    call get_skill first and edit the returned content.

    Args:
        skill_name: Exact skill name to update.
        content: The complete new markdown content of the skill.
        comment: What changed and why (shown in the proposal review).
    """
    db = SessionLocal()
    try:
        s = db.query(M.Skill).filter_by(name=skill_name.strip()).first()
        if s is None:
            return json.dumps({"error": f"skill {skill_name!r} not found (use get_skill / see system prompt)"})
        if not content.strip():
            return json.dumps({"error": "content must not be empty"})
        new_no = max((v.version_no for v in s.versions), default=0) + 1
        sv = M.SkillVersion(skill_id=s.id, version_no=new_no, content=content,
                            status="draft", created_by="jaravis", comment=comment or None)
        db.add(sv)
        db.flush()
        db.add(M.AuditLog(actor="jaravis", action="proposal.create", entity_type="skill_version",
                          entity_id=str(sv.id), details={"skill": s.name}))
        db.commit()
        LAST_PROPOSALS.append({"proposal_id": sv.id, "component": s.name, "kind": "skill",
                               "version_no": new_no})
        return json.dumps({"ok": True, "proposal_id": sv.id, "skill": s.name, "version_no": new_no,
                           "status": "draft — awaiting user approval in the Proposals view"})
    finally:
        db.close()


@beta_tool
def lcsc_lookup(lcsc_id: str) -> str:
    """Fetch component metadata from LCSC by part number (e.g. C25905):
    manufacturer, MPN, description, datasheet URL, category, package.

    Args:
        lcsc_id: LCSC part number, format C followed by digits.
    """
    meta = fetch_metadata(lcsc_id.strip())
    if meta is None:
        return json.dumps({"error": f"LCSC lookup failed for {lcsc_id!r}"})
    return json.dumps(meta)


# ---------------------------------------------------------------- project tools
def _find_project(db, name: str) -> M.Project | None:
    needle = name.strip().lower()
    for p in db.query(M.Project).all():
        if p.name.lower() == needle:
            return p
    return None


def _latest_ready(db, project_id: int) -> M.ProjectSnapshot | None:
    return (
        db.query(M.ProjectSnapshot)
        .filter_by(project_id=project_id, status="ready")
        .order_by(M.ProjectSnapshot.created_at.desc())
        .first()
    )


@beta_tool
def list_projects() -> str:
    """List the tracked KiCad projects: name, git URL, latest ingested
    snapshot (ref + boards), production-run count."""
    db = SessionLocal()
    try:
        out = []
        for p in db.query(M.Project).order_by(M.Project.name):
            latest = _latest_ready(db, p.id)
            out.append({
                "name": p.name,
                "git_url": p.git_url,
                "description": p.description,
                "latest_snapshot": {
                    "ref": latest.ref_name,
                    "sha": latest.sha[:10],
                    "boards": [b["name"] for b in latest.boards or []],
                    "variants": {b["name"]: [v["name"] for v in b.get("variants", [])]
                                 for b in latest.boards or []},
                } if latest else None,
                "runs": db.query(M.ProductionRun).filter_by(project_id=p.id).count(),
            })
        return json.dumps({"count": len(out), "projects": out})
    finally:
        db.close()


@beta_tool
def get_project_bom(project: str, board: str = "", variant: str = "", volume: int = 1) -> str:
    """Priced BOM of a project's latest ingested snapshot at a production
    volume: per-line unit prices from current LCSC ladders, manual cost
    items, and per-device / per-run totals in the project's display currency.

    Args:
        project: Project name (exact, case-insensitive).
        board: Board name inside the project; empty = the first board.
        variant: Assembly variant name; empty = the default variant.
        volume: Production volume (number of devices) to price at.
    """
    from . import project_bom

    db = SessionLocal()
    try:
        p = _find_project(db, project)
        if p is None:
            return json.dumps({"error": f"project {project!r} not found"})
        snap = _latest_ready(db, p.id)
        if snap is None:
            return json.dumps({"error": "project has no ingested snapshot yet"})
        boards = [b["name"] for b in snap.boards or []]
        if not boards:
            return json.dumps({"error": "snapshot has no KiCad boards"})
        board_name = board or boards[0]
        if board_name not in boards:
            return json.dumps({"error": f"board {board!r} not found", "boards": boards})
        bom = project_bom.priced_bom(db, p, snap, board_name, variant, max(volume, 1))
        lines = [
            {"refs": li["refs"], "value": li["value"], "qty_per": li["qty_per"],
             "lcsc": li["lcsc"], "component": li["component_name"],
             "unit_price": li["unit_price"], "line_total": li["line_total"],
             "dnp": li["dnp"], "excluded": li["excluded"]}
            for li in bom["lines"]
        ]
        return json.dumps({
            "project": p.name, "ref": snap.ref_name, "board": board_name,
            "variant": variant or "(default)", "volume": bom["volume"],
            "currency": bom["currency"], "totals": bom["totals"],
            "lines": lines,
            "extra_items": [{"label": x["label"], "qty_per": x["qty_per"],
                             "unit_price": x["unit_price"]} for x in bom["extra"]],
            "cost_items": [{"label": c["label"], "basis": c["basis"],
                            "per_device": c["per_device"]} for c in bom["costs"]],
        })
    finally:
        db.close()


@beta_tool
def component_where_used(component_name: str) -> str:
    """Which tracked projects use a library component (searched in each
    project's latest ingested snapshot), with refs, quantity and DNP state.

    Args:
        component_name: Exact component name from the library.
    """
    db = SessionLocal()
    try:
        comp = db.query(M.Component).filter_by(name=component_name.strip()).first()
        if comp is None:
            return json.dumps({"error": f"component {component_name!r} not found"})
        out = []
        for p in db.query(M.Project).order_by(M.Project.name):
            latest = _latest_ready(db, p.id)
            if latest is None:
                continue
            lines = db.query(M.SnapshotBomLine).filter_by(
                snapshot_id=latest.id, component_id=comp.id).all()
            if lines:
                out.append({
                    "project": p.name, "ref": latest.ref_name,
                    "usages": [{"board": li.board, "variant": li.variant or "(default)",
                                "refs": li.refs, "qty": li.qty, "dnp": li.dnp}
                               for li in lines],
                })
        return json.dumps({"component": comp.name, "used_in": out})
    finally:
        db.close()


# ----------------------------------------------------------------- write tools
def _resolve_category(db, path: str) -> M.Category | None:
    needle = path.strip().lower()
    for c in db.query(M.Category).all():
        if category_path(c).lower() == needle or c.name.lower() == needle:
            return c
    return None


def _parse_properties(properties_json: str) -> tuple[list[dict] | None, str | None]:
    try:
        props = json.loads(properties_json)
        assert isinstance(props, list)
    except Exception:
        return None, "properties_json must be a JSON array of {key, value} objects"
    for p in props:
        key = str(p.get("key", "")).strip()
        if not key:
            return None, "every property needs a non-empty key"
        if key in PRICE_KEY_TO_COL or key == "Datasheet" or key.startswith("Datasheet "):
            return None, (f"{key!r} is auto-managed — prices are refreshed automatically; "
                          "pass datasheets via datasheet_url")
    keys = [str(p["key"]).strip() for p in props]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        return None, f"duplicate property keys: {sorted(dupes)}"
    return props, None


@beta_tool
def propose_new_component(
    name: str,
    category: str,
    base_component: str,
    properties_json: str,
    datasheet_url: str = "",
    comment: str = "",
) -> str:
    """Propose a NEW component as a DRAFT. It will NOT be published — the user
    must review and approve it in the Proposals view. Follow library
    conventions: include a Footprint property with the 7Sigma: prefix,
    ki_description, Value where applicable, Manufacturer 1 / Manufacturer Part
    Number 1 / Supplier 1 / Supplier Part Number 1 / LCSC Part when known.
    Do NOT include price keys or Datasheet as properties.

    Args:
        name: Globally unique component name (usually the MPN).
        category: Category name or full path (e.g. "Resistor" or "ICs / LDO").
        base_component: Base symbol name (check with list_base_symbols).
        properties_json: JSON array of {"key": ..., "value": ...} in display order.
        datasheet_url: Optional datasheet URL.
        comment: Short note shown to the user in the proposal review.
    """
    db = SessionLocal()
    try:
        if db.query(M.Component).filter_by(name=name.strip()).first():
            return json.dumps({"error": f"component {name!r} already exists — use propose_component_edit"})
        cat = _resolve_category(db, category)
        if cat is None:
            return json.dumps({"error": f"category {category!r} not found (see list_categories)"})
        base = db.query(M.Symbol).filter_by(name=base_component.strip()).first()
        if base is None or base.current_version_id is None:
            return json.dumps({"error": f"base component {base_component!r} not found (see list_base_symbols)"})
        props, err = _parse_properties(properties_json)
        if err:
            return json.dumps({"error": err})

        fp_version_id = None
        fp_value = next((str(p.get("value") or "") for p in props if str(p.get("key")).strip() == "Footprint"), "")
        if fp_value.startswith("7Sigma:"):
            fp = db.query(M.Footprint).filter_by(name=fp_value.split(":", 1)[1]).first()
            if fp is None:
                return json.dumps({"error": f"footprint {fp_value!r} not found (see list_footprints)"})
            fp_version_id = fp.current_version_id
        elif fp_value:
            return json.dumps({"error": f"footprint {fp_value!r} must use the 7Sigma: namespace"})

        comp = M.Component(name=name.strip())  # current_version_id stays None until approved
        db.add(comp)
        db.flush()
        cv = M.ComponentVersion(
            component_id=comp.id, version_no=1, base_component=base.name,
            symbol_version_id=base.current_version_id, footprint_version_id=fp_version_id,
            category_id=cat.id, status="draft", created_by="jaravis", comment=comment or None,
        )
        db.add(cv)
        db.flush()
        for pos, p in enumerate(props):
            raw = p.get("value")
            db.add(M.ComponentProperty(
                component_version_id=cv.id, position=pos, key=str(p["key"]).strip(),
                value=None if raw is None else str(raw), is_null=raw is None,
            ))
        if datasheet_url.strip():
            db.add(M.Datasheet(component_id=comp.id, position=0, label="Datasheet",
                               source_url=datasheet_url.strip()))
        db.add(M.AuditLog(actor="jaravis", action="proposal.create", entity_type="component_version",
                          entity_id=str(cv.id), details={"component": comp.name, "new": True}))
        db.commit()
        LAST_PROPOSALS.append({"proposal_id": cv.id, "component": comp.name, "kind": "new"})
        return json.dumps({"ok": True, "proposal_id": cv.id, "component": comp.name,
                           "status": "draft — awaiting user approval in the Proposals view"})
    finally:
        db.close()


@beta_tool
def propose_component_edit(
    name: str,
    properties_json: str,
    comment: str,
    base_component: str = "",
    category: str = "",
) -> str:
    """Propose an EDIT to an existing component as a DRAFT new version. The
    current version stays live until the user approves the proposal.
    properties_json REPLACES the full property list — call get_component
    first, take its properties array, modify it, and pass the complete list.

    Args:
        name: Exact name of the existing component.
        properties_json: COMPLETE JSON array of {"key": ..., "value": ...} in display order.
        comment: What changed and why (shown in the proposal review).
        base_component: Optional new base symbol; empty = keep current.
        category: Optional new category name/path (moves the component); empty = keep current.
    """
    db = SessionLocal()
    try:
        comp = db.query(M.Component).filter_by(name=name.strip()).first()
        if comp is None:
            return json.dumps({"error": f"component {name!r} not found"})
        cur = current_version(comp)
        if cur is None:
            return json.dumps({"error": f"{name!r} has no published version to edit"})
        props, err = _parse_properties(properties_json)
        if err:
            return json.dumps({"error": err})

        base_name = base_component.strip() or cur.base_component
        base = db.query(M.Symbol).filter_by(name=base_name).first()
        if base is None or base.current_version_id is None:
            return json.dumps({"error": f"base component {base_name!r} not found"})
        cat = _resolve_category(db, category) if category.strip() else cur.category
        if cat is None:
            return json.dumps({"error": f"category {category!r} not found"})

        fp_version_id = None
        fp_value = next((str(p.get("value") or "") for p in props if str(p.get("key")).strip() == "Footprint"), "")
        if fp_value.startswith("7Sigma:"):
            fp = db.query(M.Footprint).filter_by(name=fp_value.split(":", 1)[1]).first()
            if fp is None:
                return json.dumps({"error": f"footprint {fp_value!r} not found"})
            fp_version_id = fp.current_version_id
        elif fp_value:
            return json.dumps({"error": f"footprint {fp_value!r} must use the 7Sigma: namespace"})

        new_no = max(v.version_no for v in comp.versions) + 1
        cv = M.ComponentVersion(
            component_id=comp.id, version_no=new_no, base_component=base.name,
            symbol_version_id=base.current_version_id, footprint_version_id=fp_version_id,
            category_id=cat.id, removed_properties=cur.removed_properties,
            status="draft", created_by="jaravis", comment=comment or None,
        )
        db.add(cv)
        db.flush()
        for pos, p in enumerate(props):
            raw = p.get("value")
            db.add(M.ComponentProperty(
                component_version_id=cv.id, position=pos, key=str(p["key"]).strip(),
                value=None if raw is None else str(raw), is_null=raw is None,
            ))
        db.add(M.AuditLog(actor="jaravis", action="proposal.create", entity_type="component_version",
                          entity_id=str(cv.id), details={"component": comp.name, "new": False}))
        db.commit()
        LAST_PROPOSALS.append({"proposal_id": cv.id, "component": comp.name, "kind": "edit",
                               "version_no": new_no})
        return json.dumps({"ok": True, "proposal_id": cv.id, "component": comp.name,
                           "version_no": new_no,
                           "status": "draft — awaiting user approval in the Proposals view"})
    finally:
        db.close()


TOOLS = [
    search_components, get_component, list_categories, list_base_symbols,
    list_footprints, lcsc_lookup, propose_new_component, propose_component_edit,
    get_skill, propose_skill_update,
    list_projects, get_project_bom, component_where_used,
]


def _build_system(db) -> str:
    skills = []
    for skill in db.query(M.Skill).order_by(M.Skill.name):
        cur = next((v for v in skill.versions if v.id == skill.current_version_id), None)
        if cur is not None:
            skills.append(f"### Skill: {skill.name}\n{cur.content}")
    skills_text = "\n\n".join(skills) if skills else "(no skill documents are currently defined)"
    return f"""You are Jaravis, the librarian agent of the 7Sigma KiCad component library platform.

## Your role
You help the user browse the component library, answer questions about it, and draft new
components or edits to existing ones. You are a specialist librarian, not a general
assistant: you act ONLY through the tools below.

## How you access the library
You run *inside* the platform's API service. Your tools query the platform's Postgres
database directly, in-process — there is no HTTP request, no file access, and no shell
between you and the data. The database is the library's source of truth.

Read / browse (use these to answer questions directly):
- search_components(query, category) — find components by text and/or category
- get_component(name) — full detail of one component: ordered properties, base symbol,
  footprint, category, prices, price ladder, stock, datasheets, version history and the
  user's notes. Stock has THREE separate pools that routinely disagree: `lcsc_retail`
  (the lcsc.com webshop — what the platform's "LCSC stock" label shows), `jlcpcb_assembly`
  (JLCPCB's parts library for SMT assembly at jlcpcb.com/parts — often stocked when LCSC
  retail is sold out), and `private_jlc_library` (parts the user personally holds on
  consignment at JLC). Never treat one pool's zero as "unavailable" without checking the
  other two, and always say which pool a number came from.
- list_categories() — the category tree with per-category counts
- list_base_symbols(query) — base symbols (graphical templates) that exist, with pin counts
- list_footprints(query) — 7Sigma footprints that exist, with pad counts
- get_skill(name) — read the current text of one of your skill documents

External lookup:
- lcsc_lookup(lcsc_id) — fetch part metadata from LCSC (manufacturer, MPN, description,
  datasheet URL, category, package). This is your only source of data outside the library.

Projects (read-only — the platform also tracks the user's KiCad design projects):
- list_projects() — tracked projects with their latest ingested git snapshot, boards,
  variants and production-run count
- get_project_bom(project, board, variant, volume) — the priced BOM of a project's latest
  snapshot at a given production volume: unit prices from current LCSC price ladders, the
  project's manual cost items, per-device and per-run totals
- component_where_used(component_name) — which projects use a library component (refs,
  quantity, DNP state). Check this before recommending edits to a part that is in use.

Propose (each creates a DRAFT the user must approve — see the gate):
- propose_new_component(...) — draft a brand-new component
- propose_component_edit(...) — draft a new version of an existing component
- propose_skill_update(skill_name, content, comment) — draft an update to one of your own
  skill documents (call get_skill first; content replaces the whole document)

## What you cannot do
- You have no shell, no Python, and no filesystem. The previous file-based workflow — a
  command-line generation-and-validation pipeline and CLI import tools — is not available
  to you. Never tell the user to run it, and never claim to have run anything yourself.
- You cannot draw or edit footprints, base symbols, or 3D models. You can only *reference*
  ones that already exist (find them with list_footprints / list_base_symbols). If a part
  needs a footprint or base symbol that does not exist yet, say so and stop — ask the user
  to add it. Do not invent a name; the propose_* tools reject references to things that
  do not exist.
- You cannot publish. Everything you write is a draft.

## The approval gate (structural)
Your propose_* tools can only create DRAFTS. Nothing changes the live library until the
user reviews and approves it in the Proposals view. After proposing, ALWAYS tell the user
you created a draft awaiting their approval. Prices are auto-managed (refreshed from LCSC)
— never set price properties. Datasheets are managed separately — pass a URL via
datasheet_url, never as a "Datasheet" property.

## Adding a component (typical flow)
1. Given an LCSC number, call lcsc_lookup first for real metadata — never guess values.
2. Pick the category (list_categories) and an existing base symbol (list_base_symbols) and
   footprint (list_footprints) that match the part's package and pin count.
3. Open a similar existing component in the same category with get_component and mirror its
   property set and order.
4. Call propose_new_component (or propose_component_edit), then tell the user the draft is
   awaiting approval.

## Your skill documents
Below are your editable convention guides — naming, properties, and how to choose
footprints and base symbols. They are the current version from the Skills page; the user
can edit them, and you can propose updates with propose_skill_update when you learn a
lasting rule. Follow their conventions.

{skills_text}"""


def run_chat(messages: list[dict]) -> dict:
    """Run one Jaravis turn over the provided conversation. Blocking."""
    LAST_PROPOSALS.clear()
    db = SessionLocal()
    try:
        system = _build_system(db)
    finally:
        db.close()

    client = anthropic.Anthropic()
    runner = client.beta.messages.tool_runner(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        thinking={"type": "adaptive"},
        system=system,
        tools=TOOLS,
        messages=messages,
    )
    trace: list[dict] = []
    final = None
    for message in runner:
        final = message
        for block in message.content:
            if block.type == "tool_use":
                trace.append({"tool": block.name, "input": block.input})
    reply = ""
    if final is not None:
        reply = "\n".join(b.text for b in final.content if b.type == "text")
    return {"reply": reply, "trace": trace, "proposals": list(LAST_PROPOSALS)}
