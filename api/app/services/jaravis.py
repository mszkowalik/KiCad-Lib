"""Jaravis — the library agent.

Runs on the Anthropic SDK's beta tool runner (custom DB tools, we host the
loop). THE GATE IS STRUCTURAL: Jaravis's write tools can only create DRAFT
component versions (proposals); publishing requires explicit user approval in
the proposals UI. Read tools answer questions about the library directly.

Auth: the anthropic client resolves credentials from the environment
(ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile).
"""
from __future__ import annotations

import contextvars
import json
import os
import threading

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

# Proposals created during the CURRENT chat turn. A ContextVar (not a module
# global) so overlapping turns — runs now execute in background threads, and two
# sessions can run at once — never cross-attribute each other's drafts. Set to a
# fresh list at the start of each run_chat_events turn.
_turn_proposals: contextvars.ContextVar[list] = contextvars.ContextVar("jaravis_turn_proposals")


def _record_proposal(entry: dict) -> None:
    try:
        _turn_proposals.get().append(entry)
    except LookupError:
        pass  # proposal created outside a chat turn (e.g. a direct tool call) — ignore


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


# ------------------------------------------------------------------ read tools
def _user_notes(db, target_type: str, target_id: int) -> list:
    """Human comments on any entity (component/symbol/footprint) as context."""
    return [
        {"author": c.author, "date": c.created_at.date().isoformat(), "note": c.body}
        for c in db.query(M.Comment)
        .filter_by(target_type=target_type, target_id=target_id)
        .order_by(M.Comment.created_at)
    ]


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
        from .ladder import effective_points

        price = db.query(M.ComponentPrice).filter_by(component_id=comp.id).first()
        points = effective_points(
            db.query(M.ComponentPricePoint).filter_by(component_id=comp.id)
            .order_by(M.ComponentPricePoint.qty_from).all()
        )
        supply = db.query(M.ComponentSupply).filter_by(component_id=comp.id).first()
        private = db.query(M.JlcStockItem).filter_by(component_id=comp.id).first()
        sheets = (db.query(M.Datasheet)
                  .filter_by(component_id=comp.id, archived=False)
                  .order_by(M.Datasheet.position).all())
        return json.dumps({
            "name": comp.name,
            "category": category_path(cv.category),
            "base_component": cv.base_component,
            # False = virtual part (test point, logo, fiducial, mounting hole):
            # excluded from project BOM totals, orders and stock checks.
            "purchasable": comp.purchasable,
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
            "user_notes": _user_notes(db, "component", comp.id),
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


# ---------------------------------------------------- geometry + archive reads
def _current_of(parent):
    return next((v for v in parent.versions if v.id == parent.current_version_id), None)


@beta_tool
def get_symbol(name: str) -> str:
    """Full detail of one base symbol: pin table (number, name, electrical
    type), unit count, which components use it, version history, and the raw
    .kicad_sym s-expression source (edit it with propose_symbol_edit).

    Args:
        name: Exact base symbol name (find it with list_base_symbols).
    """
    db = SessionLocal()
    try:
        sym = db.query(M.Symbol).filter_by(name=name.strip()).first()
        if sym is None:
            return json.dumps({"error": f"base symbol {name!r} not found"})
        cur = _current_of(sym)
        used_by = []
        for comp in db.query(M.Component).order_by(M.Component.name):
            cv = current_version(comp)
            if cv is not None and cv.base_component == sym.name:
                used_by.append(comp.name)
        parsed = (cur.parsed or {}) if cur else {}
        return json.dumps({
            "name": sym.name,
            "current_version_no": cur.version_no if cur else None,
            "pin_count": parsed.get("pin_count"),
            "pins": parsed.get("pins"),
            "unit_entry_count": parsed.get("unit_entry_count"),
            "used_by_count": len(used_by),
            "used_by_components": used_by[:100],
            "versions": [{"version_no": v.version_no, "status": v.status,
                          "created_by": v.created_by, "comment": v.comment}
                         for v in sym.versions],
            "user_notes": _user_notes(db, "symbol", sym.id),
            "source": cur.source_text if cur else None,
        })
    finally:
        db.close()


@beta_tool
def get_footprint(name: str) -> str:
    """Full detail of one footprint: pad table (number, type, shape, size,
    drill, layers), courtyard/fab presence, referenced 3D models, which
    components use it, version history, and the raw .kicad_mod source (edit it
    with propose_footprint_edit).

    Args:
        name: Exact footprint name WITHOUT the 7Sigma: prefix (see list_footprints).
    """
    db = SessionLocal()
    try:
        fp = db.query(M.Footprint).filter_by(name=name.strip()).first()
        if fp is None:
            return json.dumps({"error": f"footprint {name!r} not found"})
        cur = _current_of(fp)
        fv_ids = {v.id for v in fp.versions}
        used_by = []
        for comp in db.query(M.Component).order_by(M.Component.name):
            cv = current_version(comp)
            if cv is not None and cv.footprint_version_id in fv_ids:
                used_by.append(comp.name)
        parsed = (cur.parsed or {}) if cur else {}
        return json.dumps({
            "name": fp.name,
            "current_version_no": cur.version_no if cur else None,
            "pad_count": parsed.get("pad_count"),
            "smd_pad_count": parsed.get("smd_pad_count"),
            "tht_pad_count": parsed.get("tht_pad_count"),
            "pads": (parsed.get("pads") or [])[:400],
            "has_courtyard": parsed.get("has_courtyard"),
            "has_fab": parsed.get("has_fab"),
            "models_3d": parsed.get("models"),
            "used_by_count": len(used_by),
            "used_by_components": used_by[:100],
            "versions": [{"version_no": v.version_no, "status": v.status,
                          "created_by": v.created_by, "comment": v.comment}
                         for v in fp.versions],
            "user_notes": _user_notes(db, "footprint", fp.id),
            "source": cur.source_text if cur else None,
        })
    finally:
        db.close()


_MAX_DS_PAGES = 6


def _parse_pages(spec: str, page_count: int) -> list[int]:
    """'3,14-15' (1-based) -> unique zero-based indexes, clamped, capped."""
    picked: list[int] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        lo, _, hi = part.partition("-")
        try:
            picked.extend(range(int(lo), int(hi or lo) + 1))
        except ValueError:
            continue
    if not picked:
        picked = [1]
    uniq: list[int] = []
    for p in picked:
        if 1 <= p <= page_count and p not in uniq:
            uniq.append(p)
    return [p - 1 for p in uniq[:_MAX_DS_PAGES]]


@beta_tool
def read_datasheet(component: str, pages: str = "", datasheet_label: str = "") -> list:
    """Open a component's locally archived datasheet PDF: returns the
    requested pages as extracted text AND rendered page images, so pinout
    drawings, package dimensions and tables can be inspected visually.
    First call it without `pages` — that returns page 1 plus the total page
    count — then request the exact pages you need (e.g. "3,14-15").
    Max 6 pages per call. If there is no local copy yet it is fetched from
    the datasheet's source URL first.

    Args:
        component: Exact component name.
        pages: Page selection like "2", "1-3" or "3,14-15" (1-based). Empty = page 1.
        datasheet_label: Which datasheet when the component has several
            (case-insensitive substring of its label). Empty = the primary one.
    """
    import base64

    import fitz  # pymupdf

    db = SessionLocal()
    try:
        comp = db.query(M.Component).filter_by(name=component.strip()).first()
        if comp is None:
            return [{"type": "text", "text": json.dumps({"error": f"component {component!r} not found"})}]
        sheets = (db.query(M.Datasheet)
                  .filter_by(component_id=comp.id, archived=False)
                  .order_by(M.Datasheet.position).all())
        if not sheets:
            return [{"type": "text", "text": json.dumps({"error": f"{component!r} has no datasheets"})}]
        needle = datasheet_label.strip().lower()
        ds = next((d for d in sheets if needle and needle in d.label.lower()), None if needle else sheets[0])
        if ds is None:
            return [{"type": "text", "text": json.dumps(
                {"error": f"no datasheet label matches {datasheet_label!r}",
                 "available": [d.label for d in sheets]})}]
        if ds.current_version_id is None:
            if not (ds.source_url or "").strip():
                return [{"type": "text", "text": json.dumps(
                    {"error": f"datasheet {ds.label!r} has no local copy and no source URL"})}]
            from .datasheet_store import fetch_datasheet
            try:
                fetch_datasheet(db, ds)
            except Exception as e:
                return [{"type": "text", "text": json.dumps(
                    {"error": f"no local copy and fetching failed: {e}",
                     "source_url": ds.source_url,
                     "hint": "try web_fetch on the source URL instead"})}]
            db.refresh(ds)
        dv = next((v for v in ds.versions if v.id == ds.current_version_id), None)
        if dv is None:
            return [{"type": "text", "text": json.dumps({"error": "datasheet has no stored version"})}]
        data = dv.data
        is_pdf = data[:5] == b"%PDF-" or "pdf" in (dv.content_type or "").lower()
        if not is_pdf:
            return [{"type": "text", "text": json.dumps(
                {"error": f"datasheet {ds.label!r} is not a PDF (a web page was archived)",
                 "content_type": dv.content_type, "source_url": ds.source_url,
                 "hint": "use web_fetch on the source URL to read it"})}]

        doc = fitz.open(stream=data, filetype="pdf")
        try:
            idxs = _parse_pages(pages, doc.page_count)
            blocks: list = [{"type": "text", "text": json.dumps({
                "component": comp.name, "datasheet": ds.label, "filename": dv.filename,
                "page_count": doc.page_count,
                "pages_returned": [i + 1 for i in idxs],
                "fetched_at": dv.fetched_at.isoformat(),
            })}]
            for i in idxs:
                page = doc[i]
                text = page.get_text("text")[:4000]
                png = page.get_pixmap(matrix=fitz.Matrix(2, 2)).tobytes("png")
                if len(png) > 4 * 1024 * 1024:  # stay under the API's 5 MB image cap
                    png = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).tobytes("png")
                blocks.append({"type": "image", "source": {
                    "type": "base64", "media_type": "image/png",
                    "data": base64.b64encode(png).decode(),
                }})
                blocks.append({"type": "text",
                               "text": f"--- page {i + 1} extracted text ---\n{text}"})
            return blocks
        finally:
            doc.close()
    finally:
        db.close()


@beta_tool
def get_price_history(component: str, limit: int = 12) -> str:
    """Historical price timeline of a component, newest first. Each entry is
    the COMPLETE set of price points effective at that moment (all sources —
    LCSC ladder tiers + manual levels; empty = prices were deleted).
    Production-run economics resolve prices from this timeline by run date.

    Args:
        component: Exact component name.
        limit: Max history entries to return (default 12, cap 50).
    """
    db = SessionLocal()
    try:
        comp = db.query(M.Component).filter_by(name=component.strip()).first()
        if comp is None:
            return json.dumps({"error": f"component {component!r} not found"})
        rows = (db.query(M.ComponentPriceHistory)
                .filter_by(component_id=comp.id)
                .order_by(M.ComponentPriceHistory.recorded_at.desc())
                .limit(max(1, min(limit, 50))).all())
        return json.dumps({
            "component": comp.name,
            "entries": [{"recorded_at": r.recorded_at.isoformat(), "points": r.points}
                        for r in rows],
        })
    finally:
        db.close()


@beta_tool
def get_audit_log(limit: int = 30, entity_type: str = "", actor: str = "") -> str:
    """Recent platform audit log entries, newest first: who did what when
    (imports, proposals, approvals, edits...).

    Args:
        limit: Max entries (default 30, cap 100).
        entity_type: Optional filter (e.g. "component_version", "symbol_version", "skill_version").
        actor: Optional filter (e.g. "user", "jaravis", "import").
    """
    db = SessionLocal()
    try:
        q = db.query(M.AuditLog).order_by(M.AuditLog.ts.desc())
        if entity_type.strip():
            q = q.filter(M.AuditLog.entity_type == entity_type.strip())
        if actor.strip():
            q = q.filter(M.AuditLog.actor == actor.strip())
        rows = q.limit(max(1, min(limit, 100))).all()
        return json.dumps([
            {"ts": r.ts.isoformat(), "actor": r.actor, "action": r.action,
             "entity_type": r.entity_type, "entity_id": r.entity_id, "details": r.details}
            for r in rows
        ])
    finally:
        db.close()


@beta_tool
def list_models3d(query: str = "", limit: int = 100) -> str:
    """List stored 3D model files (STEP/WRL) by relative path under 3DModels/.

    Args:
        query: Optional case-insensitive path filter.
        limit: Max rows (default 100, cap 300).
    """
    db = SessionLocal()
    try:
        rows = db.query(M.Model3D).order_by(M.Model3D.rel_path).all()
        needle = query.strip().lower()
        out = [{"rel_path": m.rel_path, "size_bytes": m.size_bytes}
               for m in rows if not needle or needle in m.rel_path.lower()]
        return json.dumps({"total_matching": len(out),
                           "models": out[:max(1, min(limit, 300))]})
    finally:
        db.close()


@beta_tool
def list_skills() -> str:
    """List every skill document with its CURRENT version number.

    Use this to check whether a local copy of a skill is still current: compare
    the version_no here with the stamp at the top of the local file
    (`.claude/skills/kicad-<name>/SKILL.md`). Cheap — one call covers all of
    them, and it returns no document bodies. Fetch a stale one with get_skill.
    """
    db = SessionLocal()
    try:
        out = []
        for s in db.query(M.Skill).order_by(M.Skill.name):
            cur = next((v for v in s.versions if v.id == s.current_version_id), None)
            out.append({
                "name": s.name,
                "description": s.description or "",
                "version_no": cur.version_no if cur else None,
                "updated_at": cur.created_at.isoformat() if cur and cur.created_at else None,
                "drafts": sum(1 for v in s.versions if v.status == "draft"),
            })
        return json.dumps({"skills": out})
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
        return json.dumps({"name": s.name, "description": s.description or "",
                           "version_no": cur.version_no if cur else None,
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
        _record_proposal({"proposal_id": sv.id, "component": s.name, "kind": "skill",
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
             "dnp": li["dnp"], "excluded": li["excluded"],
             "not_purchasable": li["not_purchasable"]}
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


@beta_tool
def get_project(name: str) -> str:
    """Full detail of one tracked project: description, git URL, recent
    snapshots with boards/variants, the user's project notes, and its
    production runs (get_production_run for run economics).

    Args:
        name: Project name (exact, case-insensitive).
    """
    from .project_bom import display_currency

    db = SessionLocal()
    try:
        p = _find_project(db, name)
        if p is None:
            return json.dumps({"error": f"project {name!r} not found"})
        snaps = (db.query(M.ProjectSnapshot)
                 .filter_by(project_id=p.id, status="ready")
                 .order_by(M.ProjectSnapshot.created_at.desc()).limit(3).all())
        notes = (db.query(M.ProjectNote).filter_by(project_id=p.id)
                 .order_by(M.ProjectNote.created_at).all())
        runs = (db.query(M.ProductionRun).filter_by(project_id=p.id)
                .order_by(M.ProductionRun.created_at.desc()).all())
        return json.dumps({
            "name": p.name,
            "description": p.description,
            "git_url": p.git_url,
            "display_currency": display_currency(p),
            "snapshots": [{
                "ref": s.ref_name, "sha": s.sha[:10],
                "created_at": s.created_at.isoformat(),
                "boards": [b["name"] for b in s.boards or []],
                "variants": {b["name"]: [v["name"] for v in b.get("variants", [])]
                             for b in s.boards or []},
            } for s in snaps],
            "notes": [{"author": n.author, "date": n.created_at.date().isoformat(),
                       "note": n.body} for n in notes],
            "production_runs": [{
                "id": r.id, "label": r.label, "qty": r.qty, "status": r.status,
                "run_date": r.run_date, "board": r.board, "variant": r.variant or "(default)",
                "created_at": r.created_at.date().isoformat(),
            } for r in runs],
        })
    finally:
        db.close()


@beta_tool
def get_production_run(project: str, run: str) -> str:
    """Economics of one production run, computed from HISTORICAL pricing at
    the run's date (with the user's per-line overrides applied): every line
    with unit price and total, cost items, and run totals.

    Args:
        project: Project name (exact, case-insensitive).
        run: Run label (case-insensitive) or numeric run id (see get_project).
    """
    from .project_bom import run_effective

    db = SessionLocal()
    try:
        p = _find_project(db, project)
        if p is None:
            return json.dumps({"error": f"project {project!r} not found"})
        runs = db.query(M.ProductionRun).filter_by(project_id=p.id).all()
        needle = run.strip().lower()
        r = next((x for x in runs if x.label.lower() == needle
                  or (needle.isdigit() and x.id == int(needle))), None)
        if r is None:
            return json.dumps({"error": f"run {run!r} not found",
                               "available": [{"id": x.id, "label": x.label} for x in runs]})
        eff = run_effective(db, r)
        lines = [{
            "key": li.get("key"), "refs": li.get("refs"), "label": li.get("label"),
            "component": li.get("component_name"), "lcsc": li.get("lcsc"),
            "qty_total": li.get("qty_total"), "unit_price": li.get("unit_price"),
            "line_total": li.get("line_total"), "overridden": li.get("overridden"),
            "dropped": li.get("dropped"), "excluded": li.get("excluded"),
        } for li in eff["lines"]]
        costs = [{
            "label": c.get("label"), "basis": c.get("basis"), "price": c.get("price"),
            "run_cost": c.get("run_cost"), "overridden": c.get("overridden"),
            "dropped": c.get("dropped"),
        } for c in eff["costs"]]
        return json.dumps({
            "project": p.name, "run": r.label, "run_id": r.id, "status": r.status,
            "qty": eff["qty"], "run_date": r.run_date, "notes": r.notes,
            "priced_at": eff["priced_at"], "currency": eff["currency"],
            "totals": eff["totals"], "lines": lines, "costs": costs,
            "added_lines": eff["added"],
        })
    finally:
        db.close()


# ------------------------------------------------------------ external lookup
@beta_tool
def search_jlc_parts(keyword: str, limit: int = 10) -> str:
    """Search the PUBLIC JLCPCB assembly-parts catalog (jlcpcb.com/parts) by
    keyword. Returns LCSC code, MPN, brand, package, description, JLCPCB
    assembly stock and library type (basic parts avoid the extended-part
    setup fee). Quirks: `+` acts as AND between words; the index stores MPNs
    UNHYPHENATED (search "TPS7B6950QDBVRQ1", not "TPS7B69-50..."); results may
    include eval boards whose names merely contain the chip MPN.

    Args:
        keyword: Search keywords (e.g. "TI+TPS7B6950" or "47uF 1210 X7R").
        limit: Max rows (default 10, cap 20).
    """
    from . import jlc

    try:
        rows = jlc.search_parts(keyword, page_size=max(1, min(limit, 20)))
    except jlc.JlcError as e:
        return json.dumps({"error": str(e)})
    out = []
    for r in rows:
        out.append({
            "lcsc": r.get("componentCode"),
            "mpn": r.get("componentModelEn"),
            "brand": r.get("componentBrandEn"),
            "package": r.get("componentSpecificationEn") or r.get("encapStandard"),
            "description": r.get("describe"),
            "jlc_assembly_stock": r.get("stockCount"),
            "library_type": r.get("componentLibraryType"),
            "prices": r.get("componentPrices") or r.get("prices"),
        })
    return json.dumps({"count": len(out), "parts": out})


@beta_tool
def get_jlc_details(lcsc_codes: str) -> str:
    """Batch detail from the OFFICIAL JLCPCB OpenAPI for LCSC part codes:
    JLCPCB assembly stock, JLC price ladder, library type, attributes.
    Requires configured JLC API credentials (returns an error if absent).

    Args:
        lcsc_codes: Comma/space-separated LCSC codes (e.g. "C25905, C5440143").
    """
    from . import jlc

    codes = [c for c in (x.strip() for x in lcsc_codes.replace(",", " ").split()) if c]
    if not codes:
        return json.dumps({"error": "no LCSC codes given"})
    try:
        details = jlc.fetch_component_details(codes[:40])
    except jlc.JlcError as e:
        return json.dumps({"error": str(e)})
    shown_keys = ("componentCode", "componentModelEn", "componentModel", "componentBrandEn",
                  "describe", "componentSpecificationEn", "encapStandard", "stockCount",
                  "componentPrices", "priceList", "priceRanges", "componentLibraryType",
                  "leastNumber", "minPurchaseNum", "lossNumber", "componentTypeEn")
    out = {}
    for code, row in details.items():
        trimmed = {k: row[k] for k in shown_keys if k in row and row[k] not in (None, "")}
        trimmed["other_keys"] = sorted(set(row) - set(shown_keys))
        out[code] = trimmed
    missing = [c for c in codes if c not in details]
    return json.dumps({"found": out, "not_found": missing})


@beta_tool
def refresh_supply(component: str) -> str:
    """Live re-check of a component's supplier data RIGHT NOW: refetches the
    JLCPCB assembly price ladder + stock (the default price source) and the
    LCSC retail ladder + stock (fallback), and records price history. Use when
    a stock/price figure looks stale (check `checked_at` from get_component).
    This data is auto-managed, so no user approval is needed. Manual price
    entries are never touched.

    Args:
        component: Exact component name (must have an LCSC Part property).
    """
    from .ladder import effective_points, lcsc_part_of, refresh_component

    db = SessionLocal()
    try:
        comp = db.query(M.Component).filter_by(name=component.strip()).first()
        if comp is None:
            return json.dumps({"error": f"component {component!r} not found"})
        cv = current_version(comp)
        if cv is None:
            return json.dumps({"error": f"{component!r} has no published version"})
        lcsc = lcsc_part_of(cv)
        if not lcsc:
            return json.dumps({"error": f"{component!r} has no LCSC Part property — nothing to refresh"})
        wrote = refresh_component(db, comp.id, lcsc)
        supply = db.query(M.ComponentSupply).filter_by(component_id=comp.id).first()
        points = effective_points(
            db.query(M.ComponentPricePoint).filter_by(component_id=comp.id)
            .order_by(M.ComponentPricePoint.qty_from).all()
        )
        private = db.query(M.JlcStockItem).filter_by(component_id=comp.id).first()
        return json.dumps({
            "component": comp.name, "lcsc": lcsc, "ladder_updated": wrote,
            "stock": {
                "lcsc_retail": supply.stock if supply else None,
                "jlcpcb_assembly": supply.jlc_stock if supply else None,
                "private_jlc_library": private.qty if private else 0,
                "moq": supply.moq if supply else None,
                "checked_at": (supply.checked_at.isoformat()
                               if supply and supply.checked_at else None),
            },
            "price_ladder": [{"source": p.source, "qty_from": p.qty_from,
                              "unit_price": p.unit_price, "currency": p.currency}
                             for p in points],
        })
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
        _record_proposal({"proposal_id": cv.id, "component": comp.name, "kind": "new"})
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
        _record_proposal({"proposal_id": cv.id, "component": comp.name, "kind": "edit",
                          "version_no": new_no})
        return json.dumps({"ok": True, "proposal_id": cv.id, "component": comp.name,
                           "version_no": new_no,
                           "status": "draft — awaiting user approval in the Proposals view"})
    finally:
        db.close()


@beta_tool
def propose_symbol_edit(name: str, source_text: str, comment: str) -> str:
    """Propose a new version of a base symbol — or a brand-new base symbol —
    as a DRAFT the user must approve in the Proposals view (with a visual
    before/after preview). source_text must be a complete .kicad_sym library
    text containing a symbol named exactly `name`: call get_symbol first,
    take its `source`, and edit that. Follow the symbol conventions from your
    skill documents (pin grouping, grid, electrical types).

    Args:
        name: Base symbol name. Existing name = edit proposal; new name = creation proposal.
        source_text: The complete .kicad_sym file text with the symbol drawing.
        comment: What changed and why (shown in the proposal review).
    """
    from .generator import load_symbol_lib_from_text
    from .parse_cache import symbol_parsed

    name = name.strip()
    if not name or not source_text.strip():
        return json.dumps({"error": "name and source_text must not be empty"})
    try:
        lib = load_symbol_lib_from_text(source_text)
    except Exception as e:
        return json.dumps({"error": f"source_text does not parse as a .kicad_sym library: {e}"})
    entry_names = [s.entryName for s in lib.symbols]
    if name not in entry_names:
        return json.dumps({"error": f"source_text contains no symbol named {name!r}",
                           "symbols_found": entry_names})
    try:
        parsed = symbol_parsed(source_text)
    except Exception as e:
        return json.dumps({"error": f"symbol metadata extraction failed: {e}"})

    db = SessionLocal()
    try:
        sym = db.query(M.Symbol).filter_by(name=name).first()
        is_new = sym is None
        old_pins = None
        if is_new:
            sym = M.Symbol(name=name)  # current_version_id stays None until approved
            db.add(sym)
            db.flush()
        else:
            cur = _current_of(sym)
            old_pins = (cur.parsed or {}).get("pin_count") if cur else None
        new_no = max((v.version_no for v in sym.versions), default=0) + 1
        sv = M.SymbolVersion(symbol_id=sym.id, version_no=new_no, source_text=source_text,
                             parsed=parsed, status="draft", created_by="jaravis",
                             comment=comment or None)
        db.add(sv)
        db.flush()
        db.add(M.AuditLog(actor="jaravis", action="proposal.create", entity_type="symbol_version",
                          entity_id=str(sv.id), details={"symbol": name, "new": is_new}))
        db.commit()
        _record_proposal({"proposal_id": sv.id, "component": name, "kind": "symbol",
                          "version_no": new_no})
        return json.dumps({
            "ok": True, "proposal_id": sv.id, "symbol": name, "version_no": new_no,
            "is_new_symbol": is_new, "pin_count": parsed.get("pin_count"),
            "previous_pin_count": old_pins,
            "status": "draft — awaiting user approval in the Proposals view",
        })
    finally:
        db.close()


@beta_tool
def propose_footprint_edit(name: str, source_text: str, comment: str) -> str:
    """Propose a new version of a footprint — or a brand-new footprint — as a
    DRAFT the user must approve in the Proposals view (with a visual
    before/after preview). source_text must be a complete .kicad_mod text
    whose header reads (footprint "<name>" ...) with NO library prefix: call
    get_footprint first, take its `source`, and edit that. 3D model paths
    must use ${SEVENSIGMA_DIR}/3DModels/... . Follow the footprint
    conventions from your skill documents.

    Args:
        name: Footprint name WITHOUT the 7Sigma: prefix. Existing = edit; new = creation.
        source_text: The complete .kicad_mod file text.
        comment: What changed and why (shown in the proposal review).
    """
    from ..util.sexpr import _norm, find_node, parse_sexpr
    from .parse_cache import footprint_parsed

    name = name.strip()
    if not name or not source_text.strip():
        return json.dumps({"error": "name and source_text must not be empty"})
    try:
        parsed = footprint_parsed(source_text)
        tree = parse_sexpr(source_text)
    except Exception as e:
        return json.dumps({"error": f"source_text does not parse as a .kicad_mod footprint: {e}"})
    # the footprint node may BE the tree root rather than a child (same
    # fallback as parse_cache.footprint_parsed)
    fp_node = find_node(tree, "footprint") or (tree[0] if tree and isinstance(tree[0], list) else tree)
    valid = isinstance(fp_node, list) and len(fp_node) > 1 and _norm(fp_node[0]) == "footprint"
    header = _norm(fp_node[1]) if valid else ""
    if header != name:
        return json.dumps({"error": f"footprint header is {header!r} but must be exactly {name!r} "
                                    "(no easyeda2kicad:/7Sigma: prefix inside the file)"})
    model_prefix = "${SEVENSIGMA_DIR}/3DModels/"
    bad_models = [m for m in parsed.get("models") or [] if not m.startswith(model_prefix)]
    if bad_models:
        return json.dumps({"error": f"3D model paths must start with {model_prefix}",
                           "offending": bad_models})

    db = SessionLocal()
    try:
        warnings = []
        for m in parsed.get("models") or []:
            rel = m[len(model_prefix):]
            if db.query(M.Model3D).filter_by(rel_path=rel).first() is None:
                warnings.append(f"referenced 3D model not in the library: {rel}")
        fp = db.query(M.Footprint).filter_by(name=name).first()
        is_new = fp is None
        old_pads = None
        if is_new:
            fp = M.Footprint(name=name)  # current_version_id stays None until approved
            db.add(fp)
            db.flush()
        else:
            cur = _current_of(fp)
            old_pads = (cur.parsed or {}).get("pad_count") if cur else None
        new_no = max((v.version_no for v in fp.versions), default=0) + 1
        fv = M.FootprintVersion(footprint_id=fp.id, version_no=new_no, source_text=source_text,
                                parsed=parsed, models=parsed.get("models"), status="draft",
                                created_by="jaravis", comment=comment or None)
        db.add(fv)
        db.flush()
        db.add(M.AuditLog(actor="jaravis", action="proposal.create", entity_type="footprint_version",
                          entity_id=str(fv.id), details={"footprint": name, "new": is_new}))
        db.commit()
        _record_proposal({"proposal_id": fv.id, "component": name, "kind": "footprint",
                          "version_no": new_no})
        return json.dumps({
            "ok": True, "proposal_id": fv.id, "footprint": name, "version_no": new_no,
            "is_new_footprint": is_new, "pad_count": parsed.get("pad_count"),
            "previous_pad_count": old_pads, "warnings": warnings,
            "status": "draft — awaiting user approval in the Proposals view",
        })
    finally:
        db.close()


TOOLS = [
    # library reads
    search_components, get_component, list_categories, list_base_symbols,
    list_footprints, get_symbol, get_footprint, read_datasheet,
    get_price_history, get_audit_log, list_models3d, list_skills, get_skill,
    # external lookup
    lcsc_lookup, search_jlc_parts, get_jlc_details, refresh_supply,
    # projects
    list_projects, get_project, get_project_bom, get_production_run,
    component_where_used,
    # proposals (draft-gated writes)
    propose_new_component, propose_component_edit,
    propose_symbol_edit, propose_footprint_edit, propose_skill_update,
]

# Anthropic-hosted server tools — executed on the API side, no local dispatch.
# max_uses caps cost per turn; web_fetch reads PDFs (datasheets) natively.
SERVER_TOOLS = [
    {"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8,
     "max_content_tokens": 40000},
]


def _build_system(db) -> str:
    skills = []
    for skill in db.query(M.Skill).order_by(M.Skill.name):
        cur = next((v for v in skill.versions if v.id == skill.current_version_id), None)
        if cur is not None:
            head = f"### Skill: {skill.name}"
            if skill.description:
                head += f" — {skill.description}"
            skills.append(f"{head}\n{cur.content}")
    skills_text = "\n\n".join(skills) if skills else "(no skill documents are currently defined)"
    return f"""You are Jaravis, the librarian agent of the 7Sigma KiCad component library platform.

## Your role
You help the user browse the component library, answer questions about it, draft new
components or edits (including symbol and footprint geometry), verify parts against their
datasheets, and research parts on the internet. You act through the tools below.

## How you access the library
You run *inside* the platform's API service. Your tools query the platform's Postgres
database directly, in-process. The database is the library's source of truth, and you
have FULL READ ACCESS to everything it holds — components, geometry, archived datasheet
PDFs, prices + history, stock, projects, BOMs, production runs, notes, and the audit log.

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
- list_base_symbols(query) / list_footprints(query) — name lists with pin/pad counts
- get_symbol(name) — one base symbol in full: pin table (number, name, electrical type),
  units, which components use it, version history, raw s-expression source
- get_footprint(name) — one footprint in full: pad table (number, type, shape, size,
  drill, layers), courtyard/fab flags, 3D model refs, users, raw source
- read_datasheet(component, pages, datasheet_label) — the locally archived datasheet PDF
  as extracted text AND rendered page images (you can SEE pinout drawings and package
  dimensions). Call without pages first to learn the page count, then request specific
  pages.
- get_price_history(component) — the append-only price timeline runs are priced from
- get_audit_log(limit, entity_type, actor) — who changed what, when
- list_models3d(query) — stored 3D model files
- get_skill(name) — read the current text of one of your skill documents

Internet access:
- web_search / web_fetch — general web research: manufacturer pages, app notes,
  alternatives, package standards. web_fetch reads PDFs, so it can open datasheets that
  are not archived locally (prefer read_datasheet for archived ones — it is faster and
  returns page images).
- lcsc_lookup(lcsc_id) — LCSC part metadata (manufacturer, MPN, description, datasheet
  URL, category, package)
- search_jlc_parts(keyword) — public JLCPCB assembly-parts catalog search (find
  alternatives that JLC can actually assemble; `+` = AND, MPNs unhyphenated)
- get_jlc_details(lcsc_codes) — official JLC API batch detail (assembly stock, JLC price
  ladder); needs configured credentials
- refresh_supply(component) — live re-fetch of LCSC ladder/stock + JLCPCB assembly stock
  for one component (auto-managed data — allowed without approval)

Projects (the platform also tracks the user's KiCad design projects):
- list_projects() — tracked projects with latest snapshot, boards, variants, run count
- get_project(name) — one project in full: snapshots, notes, production runs
- get_project_bom(project, board, variant, volume) — priced BOM at a production volume
- get_production_run(project, run) — run economics from historical pricing at the run
  date, with the user's overrides applied
- component_where_used(component_name) — which projects use a library component. Check
  this before recommending edits to a part that is in use.

Propose (each creates a DRAFT the user must approve — see the gate):
- propose_new_component(...) — draft a brand-new component
- propose_component_edit(...) — draft a new version of an existing component
- propose_symbol_edit(name, source_text, comment) — draft a new version of a base symbol
  (or a new base symbol). Call get_symbol first and edit its returned source.
- propose_footprint_edit(name, source_text, comment) — draft a new version of a footprint
  (or a new footprint). Call get_footprint first and edit its returned source.
- propose_skill_update(skill_name, content, comment) — draft an update to one of your own
  skill documents (call get_skill first; content replaces the whole document)

## What you cannot do
- You have no shell, no Python interpreter, and no filesystem. The previous file-based
  workflow — a command-line generation-and-validation pipeline and CLI import tools — is
  not available to you. Never tell the user to run it, and never claim to have run
  anything yourself.
- You cannot create or edit 3D models — only reference ones that exist (list_models3d).
- You cannot publish. Everything you write is a draft.

## The approval gate (structural)
Your propose_* tools can only create DRAFTS. Nothing changes the live library until the
user reviews and approves it in the Proposals view (symbol/footprint proposals show a
visual before/after preview there). After proposing, ALWAYS tell the user you created a
draft awaiting their approval. Prices are auto-managed (refreshed from LCSC) — never set
price properties. Datasheets are managed separately — pass a URL via datasheet_url, never
as a "Datasheet" property.

## Adding a component (typical flow)
1. Given an LCSC number, call lcsc_lookup first for real metadata — never guess values.
2. Pick the category (list_categories) and an existing base symbol (list_base_symbols) and
   footprint (list_footprints) that match the part's package and pin count.
3. Open a similar existing component in the same category with get_component and mirror its
   property set and order.
4. If a needed footprint or base symbol does not exist, you may draft one with
   propose_footprint_edit / propose_symbol_edit (new name = creation) — but prefer reusing
   an existing one, and say clearly that the geometry draft needs review.
5. Call propose_new_component (or propose_component_edit), then tell the user the draft is
   awaiting approval.

## Verifying a part against its datasheet (typical flow)
1. read_datasheet for the pinout and package-drawing pages (look at the IMAGES — pin-1
   markers, pad dimensions and pitch are graphical).
2. get_symbol — compare pin numbers, names and electrical types against the pinout.
3. get_footprint — compare pad numbering, pitch, pad sizes and courtyard against the
   package drawing (all dimensions in mm).
4. Report what is confirmed vs. mismatched, citing datasheet page numbers. Propose fixes
   as drafts only when the user asks for them.

## Editing geometry (symbols / footprints)
Symbol and footprint sources are KiCad s-expressions; edit them exactly (grid-aligned
coordinates in mm, matching the conventions in your skill documents). Keep edits minimal —
change what the task needs, preserve everything else. Note: components pin the symbol
drawing version they were generated with; the KiCad-facing base library and HTTP catalog
always use the newest published drawing, so an approved symbol edit takes effect there
immediately.

## Your skill documents
Below are your editable convention guides — naming, properties, and how to choose
footprints and base symbols. They are the current version from the Skills page; the user
can edit them, and you can propose updates with propose_skill_update when you learn a
lasting rule. Follow their conventions.

{skills_text}"""


# Bound on model calls per user turn — a stuck loop must not grind forever.
# When hit, the runner just stops iterating; run_chat_events synthesizes an
# honest "stopped, say continue" reply instead of returning silence.
MAX_ITERATIONS = 80


def run_chat_events(messages: list[dict]):
    """Generator: run one Jaravis turn, yielding progress events as the agent
    loop advances — {"type": "note", text} for interim narration text,
    {"type": "tool", tool, input} the moment a tool call is issued, and one
    final {"type": "done", reply, trace, proposals}. The chat router streams
    these as NDJSON so the UI shows live activity; closing the generator
    (client disconnect / Stop button) ends the run at the next event.

    The server tools (web_search / web_fetch) execute on Anthropic's side; a
    long research turn can stop with stop_reason="pause_turn", which the
    Python tool runner does NOT auto-resume — it would silently truncate the
    answer. So the conversation is mirrored while iterating and the runner is
    restarted with the paused turn appended (bounded)."""
    _turn_proposals.set([])
    db = SessionLocal()
    try:
        system = _build_system(db)
    finally:
        db.close()

    client = anthropic.Anthropic()
    convo: list[dict] = [dict(m) for m in messages]
    trace: list[dict] = []
    final = None
    for _ in range(4):  # initial run + up to 3 pause_turn resumes
        runner = client.beta.messages.tool_runner(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            system=system,
            tools=[*TOOLS, *SERVER_TOOLS],
            messages=convo,
            max_iterations=MAX_ITERATIONS,
        )
        for message in runner:
            final = message
            convo.append({"role": "assistant", "content": message.content})
            for block in message.content:
                if block.type == "text" and block.text.strip():
                    yield {"type": "note", "text": block.text}
                elif block.type in ("tool_use", "server_tool_use"):
                    item = {"tool": block.name, "input": block.input}
                    trace.append(item)
                    yield {"type": "tool", **item}
            # cached by the runner — tools still execute exactly once
            tool_response = runner.generate_tool_call_response()
            if tool_response is not None:
                convo.append(tool_response)
        if final is None or final.stop_reason != "pause_turn":
            break
    reply = ""
    if final is not None:
        reply = "\n".join(b.text for b in final.content if b.type == "text")
    if not reply and final is not None and final.stop_reason == "tool_use":
        reply = (f"(Stopped after {len(trace)} tool calls — the per-message cap of "
                 f"{MAX_ITERATIONS} model iterations was reached. The work done so far is "
                 "saved; say \"continue\" to keep going.)")
    yield {"type": "done", "reply": reply, "trace": trace,
           "proposals": list(_turn_proposals.get([]))}


def run_chat(messages: list[dict]) -> dict:
    """Blocking variant of run_chat_events — drains the events and returns
    only the final result (kept for the non-streaming /chat endpoint)."""
    result = {"reply": "", "trace": [], "proposals": []}
    for ev in run_chat_events(messages):
        if ev["type"] == "done":
            result = {"reply": ev["reply"], "trace": ev["trace"], "proposals": ev["proposals"]}
    return result


# --------------------------------------------------------- persisted sessions
def _title_from(content: str) -> str:
    """Derive a short session title from the first user message."""
    line = next((ln.strip() for ln in content.splitlines() if ln.strip()), "")
    line = line or "New chat"
    return line if len(line) <= 60 else line[:57].rstrip() + "…"


# ------------------------------------------------------- background chat runs
# A Jaravis turn runs in a BACKGROUND THREAD, decoupled from the HTTP client, so
# a page refresh / closed tab does NOT cancel it — the run finishes and the
# assistant reply is persisted regardless. Clients (including one that
# reconnects after a refresh) subscribe to the run's event buffer and replay it
# from the start. The registry is in-process (single uvicorn worker, single-user
# app) and does NOT survive a process restart: a run in flight when the server
# restarts — including a `--reload` triggered by a code edit — is lost, the same
# class of event as any crash. There is at most one active run per session.


class _Run:
    def __init__(self, session_id: int):
        self.session_id = session_id
        self.events: list[dict] = []      # every event emitted so far (replayable)
        self.done = False
        self.cancelled = False
        self.cond = threading.Condition()  # notifies subscribers of new events / done


_RUNS: dict[int, _Run] = {}
_RUNS_LOCK = threading.Lock()


def has_active_run(session_id: int) -> bool:
    with _RUNS_LOCK:
        run = _RUNS.get(session_id)
        return run is not None and not run.done


def _emit(run: _Run, ev: dict) -> None:
    with run.cond:
        run.events.append(ev)
        run.cond.notify_all()


def _run_worker(session_id: int, content: str) -> None:
    run = _RUNS[session_id]
    db = SessionLocal()
    try:
        sess = db.get(M.JaravisSession, session_id)
        if sess is None:
            _emit(run, {"type": "error", "error": f"session {session_id} not found"})
            return
        prior = (db.query(M.JaravisMessage).filter_by(session_id=session_id)
                 .order_by(M.JaravisMessage.id).all())
        convo = [{"role": m.role, "content": m.content} for m in prior]
        convo.append({"role": "user", "content": content})

        # Persist the user message BEFORE the (possibly long) turn.
        db.add(M.JaravisMessage(session_id=session_id, role="user", content=content))
        if not prior and (sess.title or "").strip() in ("", "New chat"):
            sess.title = _title_from(content)
        sess.updated_at = M.utcnow()
        db.commit()
        _emit(run, {"type": "session", "session_id": session_id, "title": sess.title})

        for ev in run_chat_events(convo):
            if run.cancelled:
                break  # closes run_chat_events (GeneratorExit) at this boundary
            if ev.get("type") == "done":
                db.add(M.JaravisMessage(
                    session_id=session_id, role="assistant",
                    content=ev.get("reply") or "",
                    trace=ev.get("trace") or None,
                    proposals=ev.get("proposals") or None,
                ))
                sess.updated_at = M.utcnow()
                db.commit()
            _emit(run, ev)
    except Exception as e:  # a worker must never die silently
        _emit(run, {"type": "error", "error": f"Jaravis run failed: {e}"})
    finally:
        db.close()
        with run.cond:
            run.done = True
            run.cond.notify_all()
        with _RUNS_LOCK:
            # Drop from the registry so has_active_run() flips False at once;
            # subscribers already streaming keep their local ref and drain.
            if _RUNS.get(session_id) is run:
                del _RUNS[session_id]


def start_session_run(session_id: int, content: str) -> bool:
    """Begin a background turn. Returns False if one is already running for the
    session (the caller should attach to it instead of starting a second)."""
    with _RUNS_LOCK:
        existing = _RUNS.get(session_id)
        if existing is not None and not existing.done:
            return False
        _RUNS[session_id] = _Run(session_id)
    threading.Thread(target=_run_worker, args=(session_id, content),
                     name=f"jaravis-run-{session_id}", daemon=True).start()
    return True


def cancel_session_run(session_id: int) -> bool:
    """Signal the session's active run to stop at the next event boundary (the
    server-side equivalent of the old Stop button). No assistant message is
    persisted for a cancelled turn."""
    with _RUNS_LOCK:
        run = _RUNS.get(session_id)
    if run is None or run.done:
        return False
    with run.cond:
        run.cancelled = True
        run.cond.notify_all()
    return True


def stream_run_events(session_id: int):
    """Replay a run's events from the start, blocking for new ones, until the
    run is done AND fully drained. Ends immediately if there is no run. Safe for
    multiple concurrent subscribers; never yields while holding the lock."""
    with _RUNS_LOCK:
        run = _RUNS.get(session_id)
    if run is None:
        return
    idx = 0
    while True:
        with run.cond:
            while idx >= len(run.events) and not run.done:
                run.cond.wait(timeout=30.0)
            batch = run.events[idx:]
            idx += len(batch)
            finished = run.done and idx >= len(run.events)
        for ev in batch:
            yield ev
        if finished:
            return
