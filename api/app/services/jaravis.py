"""Jaravis — the library agent.

Runs on the Anthropic SDK's beta tool runner (custom DB tools, we host the
loop). Write tools PUBLISH IMMEDIATELY (auto-publish, user design 2026-08-23;
skills followed on 2026-08-24) — accountability lives on the review axis, not
on a gate. Read tools answer questions about the library directly.

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
            # Has a human checked this part for production? See
            # services/signoff.py. NOT the same thing as a version's
            # `approved_by`, which only means the edit was let into the library.
            "production_signoff": _signoff_summary(db, comp),
        })
    finally:
        db.close()


def _signoff_summary(db, comp) -> dict:
    from .signoff import state_for

    s = state_for(db, comp)
    row = s.get("signoff") or {}
    return {
        "state": s["state"],
        "signed_by": row.get("signed_by"),
        "signed_at": row.get("signed_at"),
        "how": row.get("kind"),
        "note": row.get("note"),
        "signed_version_no": s.get("signed_version_no"),
        # Why the sign-off did not follow the component to its current version.
        "needs_recheck_because": s.get("blockers") or [],
    }


@beta_tool
def list_signoffs(state: str = "") -> str:
    """List every component's production sign-off state.

    A sign-off records that a human checked the symbol, the land pattern and
    the part number before boards were built. It is separate from library
    approval: a published component may never have been checked.

    States: `signed` (the current version is checked), `stale` (an older
    version was checked and something material changed since), `revoked` (a
    sign-off was taken back), `unsigned` (never checked).

    Args:
        state: Optional filter — one of signed, stale, revoked, unsigned.
    """
    from .signoff import states_for

    db = SessionLocal()
    try:
        comps = db.query(M.Component).all()
        states = states_for(db, comps)
        counts: dict[str, int] = {}
        for s in states.values():
            counts[s["state"]] = counts.get(s["state"], 0) + 1
        wanted = state.strip().lower()
        items = [
            {"component": c.name, "state": states[c.id]["state"],
             "signed_by": (states[c.id]["signoff"] or {}).get("signed_by"),
             "signed_version_no": states[c.id].get("signed_version_no"),
             "needs_recheck_because": states[c.id].get("blockers") or []}
            for c in comps
            if not wanted or states[c.id]["state"] == wanted
        ]
        return json.dumps({"counts": counts, "total": len(items),
                           "components": _capped(items, "components")})
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


LIST_CAP = 400


def _capped(rows: list, kind: str) -> list:
    """Cap a listing, but NEVER silently.

    The old `out[:150]` dropped the tail with nothing in the payload to say so,
    and an agent cannot tell a short library from a truncated one. A pin-1 audit
    on 2026-08-03 read 150 of 171 footprints and reported the library clean past
    "Texas…" — every VQFN was past the cut. If the cap is hit, the last element
    says so and names the filter that narrows the result.
    """
    if len(rows) <= LIST_CAP:
        return rows
    return rows[:LIST_CAP] + [{
        "_truncated": True,
        "shown": LIST_CAP,
        "total": len(rows),
        "note": f"{len(rows) - LIST_CAP} more {kind} not shown - narrow with the `query` filter",
    }]


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
        return json.dumps(_capped(out, "symbols"))
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
        return json.dumps(_capped(out, "footprints"))
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
                r = fetch_datasheet(db, ds)
                if r.get("result") == "rejected":
                    return [{"type": "text", "text": json.dumps(
                        {"error": f"the datasheet at {ds.label!r} could not be archived: "
                                  f"{r['reason']}",
                         "source_url": ds.source_url,
                         "hint": "the supplier is not serving a readable PDF — "
                                 "try web_fetch on the source URL, or find the "
                                 "manufacturer's own datasheet"})}]
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
def search_datasheets(query: str, component: str = "", limit: int = 20) -> str:
    """Search the TEXT of every archived datasheet and get back the exact pages
    to read. Use this BEFORE read_datasheet: it turns "which page shows the
    land pattern" into one call instead of guessing page numbers six at a time.
    RP2040 alone is 642 pages.

    Each hit names the component, the document, the page number, the section
    that page sits in, and a snippet. Feed the page number straight into
    read_datasheet.

    Two fields decide how far to trust a hit:
    - `extract_kind`: "text" is prose. "picture_text" means the words were
      recovered from INSIDE a drawing (dimension callouts, ballout grids) —
      useful and often exactly what you want, but the reading order is not
      guaranteed. "empty_scan" pages hold no text at all.
    - `has_table`: the page has a table whose grid survived extraction.

    The extracted text is a FINDING AID, never the authority. It preserves
    table grids and recovers text drawn inside figures, but it also shreds text
    that wraps inside a merged cell and can reorder a multi-line pin label. Read
    the page image with read_datasheet before you record any value from it.

    Args:
        query: Words to search for. Quotes force a phrase ("land pattern"),
            OR and - work ("pinout OR ballout", "package -reel").
        component: Optional filter, matched as a substring of the component name.
        limit: Maximum hits (default 20, cap 100).
    """
    from .datasheet_pages import search as _search

    db = SessionLocal()
    try:
        return json.dumps(_search(db, query, limit=limit, component=component))
    finally:
        db.close()


@beta_tool
def datasheet_outline(component: str, datasheet_label: str = "") -> str:
    """The map of one archived datasheet: its sections with the page each one
    starts on, which pages carry tables, which pages are drawings, and which
    pages cannot be read at all.

    Call this first on any document longer than a few pages. It is the cheap
    way to find the pinout, the absolute maximum ratings, the package outline
    and the recommended land pattern without opening pages one by one.

    `sections` comes from the document's own PDF outline and is absent when the
    publisher did not write one — about a quarter of the library's documents
    carry it. When it is empty, fall back to search_datasheets.

    Args:
        component: Exact component name.
        datasheet_label: Which datasheet when the component has several
            (case-insensitive substring of its label). Empty = the primary one.
    """
    from .datasheet_pages import outline as _outline

    db = SessionLocal()
    try:
        comp = db.query(M.Component).filter_by(name=component.strip()).first()
        if comp is None:
            return json.dumps({"error": f"component {component!r} not found"})
        sheets = (db.query(M.Datasheet)
                  .filter_by(component_id=comp.id, archived=False)
                  .order_by(M.Datasheet.position).all())
        if not sheets:
            return json.dumps({"error": f"{component!r} has no datasheets"})
        needle = datasheet_label.strip().lower()
        ds = next((d for d in sheets if needle and needle in d.label.lower()),
                  None if needle else sheets[0])
        if ds is None:
            return json.dumps({"error": f"no datasheet label matches {datasheet_label!r}",
                               "available": [d.label for d in sheets]})
        res = _outline(db, ds.id)
        if res is None:
            return json.dumps({"error": f"datasheet {ds.label!r} has no local copy"})
        return json.dumps({"component": comp.name, **res})
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
    """Update one of your skill documents. The new version is LIVE at once —
    it is what every later agent run reads, so get it right rather than
    filing it and walking away. Use this when the user asks you to remember a
    rule/convention, or when you learn a lasting lesson worth recording.
    content REPLACES the whole document — call get_skill first and edit the
    returned content. To undo, get_skill the previous version's text and
    write it back.

    Args:
        skill_name: Exact skill name to update.
        content: The complete new markdown content of the skill.
        comment: What changed and why (kept in the version history).
    """
    db = SessionLocal()
    try:
        s = db.query(M.Skill).filter_by(name=skill_name.strip()).first()
        if s is None:
            return json.dumps({"error": f"skill {skill_name!r} not found (use get_skill / see system prompt)"})
        from .publish import publish_skill_version

        try:
            sv = publish_skill_version(db, s, content, actor="jaravis", comment=comment)
        except ValueError as e:
            return json.dumps({"error": str(e)})
        db.commit()
        _record_proposal({"proposal_id": sv.id, "component": s.name, "kind": "skill",
                          "version_no": sv.version_no})
        return json.dumps({"ok": True, "skill": s.name, "version_no": sv.version_no,
                           "status": "published — live for every agent run from now on"})
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


def _archive_datasheet(db, ds) -> dict:
    """Download and store a datasheet row's PDF, best effort.

    Returns a small dict the write tools put in their response, so the agent
    learns straight away whether the document is actually readable rather than
    finding out later when search_datasheets comes back empty. Never raises:
    the component write is the caller's real work.
    """
    from .datasheet_store import current_version, fetch_datasheet
    try:
        r = fetch_datasheet(db, ds)
    except Exception as e:  # network, DNS, timeout, malformed response
        return {"archived": False, "reason": f"download failed: {e}",
                "source_url": ds.source_url,
                "hint": "retry with read_datasheet, which fetches on demand, or "
                        "attach the manufacturer's own PDF URL"}
    if r.get("result") == "rejected":
        return {"archived": False, "reason": r.get("reason", "refused"),
                "source_url": ds.source_url,
                "hint": "the supplier served something that is not a readable PDF — "
                        "find the manufacturer's own datasheet"}
    db.refresh(ds)
    dv = current_version(ds)
    if dv is None:
        return {"archived": False, "reason": "nothing stored", "source_url": ds.source_url}
    return {"archived": True, "filename": dv.filename, "size_bytes": dv.size_bytes,
            "page_count": dv.page_count, "text_pages": dv.text_pages,
            "text_layer": dv.text_layer}


@beta_tool
def propose_new_component(
    name: str,
    category: str,
    base_component: str,
    properties_json: str,
    datasheet_url: str = "",
    comment: str = "",
) -> str:
    """Create a NEW component. It PUBLISHES IMMEDIATELY (auto-publish): the
    library, mirror and KiCad catalog update at once, a machine validation
    record is written, and the version starts UNREVIEWED on the review axis —
    verify it afterwards with get_review_checklist + record_verification.
    Follow library conventions: include a Footprint property with the 7Sigma:
    prefix, ki_description, Value where applicable, Manufacturer 1 /
    Manufacturer Part Number 1 / Supplier 1 / Supplier Part Number 1 /
    LCSC Part when known. Do NOT include price keys or Datasheet as properties.

    Args:
        name: Globally unique component name (usually the MPN).
        category: Category name or full path (e.g. "Resistor" or "ICs / LDO").
        base_component: Base symbol name (check with list_base_symbols).
        properties_json: JSON array of {"key": ..., "value": ...} in display order.
        datasheet_url: Optional datasheet URL.
        comment: Short note recorded on the published version.
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
        archive = None
        if datasheet_url.strip():
            ds = M.Datasheet(component_id=comp.id, position=0, label="Datasheet",
                             source_url=datasheet_url.strip())
            db.add(ds)
            db.flush()
            # Archive BEFORE publishing, not after and not lazily on the first
            # read_datasheet. Two things depend on the PDF already being there:
            # pin_datasheets() records WHICH pdf version this component version
            # used, and the cmp.datasheet_text machine item asks whether the
            # archived document is searchable — it used to answer "na — no
            # archived PDF" on every new part, which reads like the question
            # does not apply rather than like the file is simply missing.
            # Best effort: a supplier that is down or serving HTML must not
            # cost the caller the whole component write. Note fetch_datasheet
            # commits, so the draft version is persisted before _publish_component
            # runs — harmless because every row it needs is already built above.
            archive = _archive_datasheet(db, ds)
        db.add(M.AuditLog(actor="jaravis", action="proposal.create", entity_type="component_version",
                          entity_id=str(cv.id), details={"component": comp.name, "new": True}))
        result = _publish_component(db, comp, cv)
        _record_proposal({"proposal_id": cv.id, "component": comp.name, "kind": "new"})
        out = {"ok": True, "proposal_id": cv.id, "component": comp.name, **result}
        if archive is not None:
            out["datasheet_archive"] = archive
        return json.dumps(out)
    finally:
        db.close()


def _publish_component(db, comp, cv) -> dict:
    """Auto-publish tail shared by the two component write tools: publish flow,
    commit, mirror refresh, review state for the response."""
    from ..config import settings
    from .publish import publish_component_version, refresh_mirror_for_component
    from .review import component_effective

    res = publish_component_version(db, comp, cv, actor="jaravis")
    db.commit()
    mirror = refresh_mirror_for_component(db, settings, comp, res["tops"])
    eff = component_effective(db, comp, cv)
    return {
        "status": "published",
        "review_state": eff["state"],
        "review_blockers": eff.get("blockers", []),
        "signoff_carry": res["signoff"],
        "mirror_warnings": mirror.get("warnings", []),
        "next_step": "verify against the datasheet: get_review_checklist + record_verification",
    }


@beta_tool
def propose_component_edit(
    name: str,
    properties_json: str,
    comment: str,
    base_component: str = "",
    category: str = "",
) -> str:
    """EDIT an existing component. The new version PUBLISHES IMMEDIATELY
    (auto-publish) — the library and KiCad catalog update at once, and the
    review carry rules decide whether the previous verification and production
    sign-off survive (they do only when nothing material changed).
    properties_json REPLACES the full property list — call get_component
    first, take its properties array, modify it, and pass the complete list.

    Args:
        name: Exact name of the existing component.
        properties_json: COMPLETE JSON array of {"key": ..., "value": ...} in display order.
        comment: What changed and why (recorded on the published version).
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
        result = _publish_component(db, comp, cv)
        _record_proposal({"proposal_id": cv.id, "component": comp.name, "kind": "edit",
                          "version_no": new_no})
        return json.dumps({"ok": True, "proposal_id": cv.id, "component": comp.name,
                           "version_no": new_no, **result})
    finally:
        db.close()


@beta_tool
def propose_symbol_edit(name: str, source_text: str, comment: str,
                        minor_change: bool = False, force: bool = False) -> str:
    """Create a new version of a base symbol — or a brand-new base symbol.
    It PUBLISHES IMMEDIATELY (auto-publish): the mirror and KiCad libraries
    update at once, a machine validation record is written, affected
    components are repointed automatically, and the version starts UNREVIEWED
    unless nothing material changed (then the previous verification carries).
    source_text must be a complete .kicad_sym library text containing a symbol
    named exactly `name`: call get_symbol first, take its `source`, and edit
    that. Follow the symbol conventions from your skill documents (pin
    grouping, grid, electrical types).

    Args:
        name: Base symbol name. Existing name = edit; new name = creation.
        source_text: The complete .kicad_sym file text with the symbol drawing.
        comment: What changed and why (recorded on the published version).
        minor_change: True ONLY for a change that genuinely needs no
            re-verification (cosmetic cleanup) — it carries verifications and
            production sign-offs across the changed drawing, with your name
            on the waiver. When unsure, leave False.
        force: Publish even when the payload is the SAME DRAWING as the live
            version. Leave False. The default no-op is what stops a KiCad
            re-save — which rewrites every entry in the library file —
            from writing a version per symbol and repointing every
            component. Force only to re-run the machine validation on
            geometry that has not changed.
    """
    from .geometry_proposals import propose_symbol_version

    db = SessionLocal()
    try:
        res = propose_symbol_version(db, name, source_text, comment, actor="jaravis",
                                     minor_change=True if minor_change else None,
                                     force=force)
        if "error" not in res and not res.get("unchanged"):
            _record_proposal({"proposal_id": res["proposal_id"], "component": res["symbol"],
                              "kind": "symbol", "version_no": res["version_no"]})
        return json.dumps(res)
    finally:
        db.close()


@beta_tool
def propose_footprint_edit(name: str, source_text: str, comment: str,
                           minor_change: bool = False, force: bool = False) -> str:
    """Create a new version of a footprint — or a brand-new footprint.
    It PUBLISHES IMMEDIATELY (auto-publish): the mirror and KiCad libraries
    update at once, a machine validation record is written (courtyard, fab,
    silk widths, pad shapes, drill minimums, 3D model presence — a missing 3D
    model FAILS the check), affected components are repointed automatically,
    and the version starts UNREVIEWED unless nothing material changed.
    source_text must be a complete .kicad_mod text whose header reads
    (footprint "<name>" ...) with NO library prefix: call get_footprint
    first, take its `source`, and edit that. 3D model paths must use
    ${SEVENSIGMA_DIR}/3DModels/... . Follow the footprint conventions from
    your skill documents.

    Args:
        name: Footprint name WITHOUT the 7Sigma: prefix. Existing = edit; new = creation.
        source_text: The complete .kicad_mod file text.
        comment: What changed and why (recorded on the published version).
        minor_change: True ONLY for a change that genuinely needs no
            re-verification — it carries verifications and production
            sign-offs across the changed drawing. When unsure, leave False.
        force: Publish even when the payload is the SAME DRAWING as the live
            version. Leave False. The default no-op is what stops a KiCad
            re-save — which rewrites every entry in the library file — from
            writing a version per footprint and repointing every component.
            Force only to re-run the machine validation on geometry that has
            not changed.
    """
    from .geometry_proposals import propose_footprint_version

    db = SessionLocal()
    try:
        res = propose_footprint_version(db, name, source_text, comment, actor="jaravis",
                                        minor_change=True if minor_change else None,
                                        force=force)
        if "error" not in res and not res.get("unchanged"):
            _record_proposal({"proposal_id": res["proposal_id"], "component": res["footprint"],
                              "kind": "footprint", "version_no": res["version_no"]})
        return json.dumps(res)
    finally:
        db.close()


@beta_tool
def set_footprint_package_name(name: str, package_name: str) -> str:
    """Set a footprint's SHORT package name — what `{Footprint_Name}` resolves to
    in a component's ki_description (e.g. "0402", "SOT-23-6", "VQFN-HR-9").

    Call this straight after publishing a BRAND-NEW footprint. A new footprint
    starts with no package name, so the first component that references it
    publishes with an unresolved `{Footprint_Name}` mirror warning. The name
    belongs to the footprint, not to each component using it — never add a
    `Footprint_Name` property to a component to work around a missing one.

    Unversioned: this mints NO footprint version and does not touch the
    .kicad_mod, but it is baked into every generated ki_description that
    references it, so the affected symbol libraries rebuild immediately.

    Args:
        name: Exact footprint name, WITHOUT the 7Sigma: prefix.
        package_name: The short package name. Empty string clears it.
    """
    from ..config import settings
    from .publish import set_footprint_package_name as _set
    db = SessionLocal()
    try:
        fp = db.query(M.Footprint).filter_by(name=name.strip()).first()
        if fp is None:
            return json.dumps({"error": f"footprint {name!r} not found",
                               "hint": "list_footprints() shows the exact names; "
                                       "do not include the 7Sigma: prefix"})
        return json.dumps({"ok": True, **_set(db, settings, fp, package_name, actor="jaravis")})
    finally:
        db.close()


def _review_subject(db, kind: str, name: str):
    """Resolve a review subject (parent row + its current version id)."""
    model = {"component": M.Component, "symbol": M.Symbol, "footprint": M.Footprint}.get(kind)
    if model is None:
        return None, None, f"kind must be component, symbol or footprint (got {kind!r})"
    parent = db.query(model).filter_by(name=name.strip()).first()
    if parent is None:
        return None, None, f"{kind} {name!r} not found"
    if parent.current_version_id is None:
        return None, None, f"{kind} {name!r} has no published version"
    return parent, parent.current_version_id, None


@beta_tool
def get_review_checklist(kind: str, name: str) -> str:
    """The resolved verification checklist for one component, symbol or
    footprint, MERGED with what has already been answered on its current
    version (machine checks run automatically on publish; earlier agent/human
    answers are included with their provenance). Call this BEFORE
    record_verification: answer the unanswered items, re-answer what you can
    improve, and never guess — use result "skipped" with a reason when the
    documentation does not let you verify an item.

    Args:
        kind: "component" | "symbol" | "footprint".
        name: The exact name.
    """
    from . import checklists as checklists_svc
    from . import review as review_svc

    db = SessionLocal()
    try:
        parent, version_id, err = _review_subject(db, kind, name)
        if err:
            return json.dumps({"error": err})
        cat_id = review_svc._category_of(db, kind, parent)
        resolved = checklists_svc.resolve(db, kind, cat_id)
        rows = review_svc.records_for(db, kind, parent.id)
        record = review_svc.effective_record(rows, version_id)
        answered = {i["key"]: i for i in (record.items or [])} if record else {}
        items = []
        for item in resolved["items"]:
            merged = dict(item)
            prev = answered.get(item["key"])
            if prev:
                merged["answered"] = {k: prev.get(k) for k in
                                      ("result", "note", "actor", "actor_type", "at")}
            items.append(merged)
        extras = [i for k, i in answered.items()
                  if k not in {it["key"] for it in resolved["items"]}]
        state = review_svc.state_from_record(record, resolved["items"] if record and
                                             record.items is not None else None)
        return json.dumps({
            "kind": kind, "name": parent.name, "version_id": version_id,
            "state": state["state"], "items": items, "extra_items": extras,
            "results_allowed": ["checked", "na", "skipped", "flagged"],
            "note": "machine items are answered automatically; answer the judgment items. "
                    "'flagged' = verified and found wrong, not fixed (note required). "
                    "Add ad-hoc points with keys like custom:<slug>.",
        })
    finally:
        db.close()


@beta_tool
def record_verification(kind: str, name: str, items_json: str, note: str = "") -> str:
    """Record a documentation verification on the CURRENT version of a
    component, symbol or footprint. Cumulative: your answers merge on top of
    the machine checks and any earlier record; you can NEVER overwrite an item
    a human answered. Every item is {"key", "result", "note"} with result:
    - "checked": verified against the documentation and CORRECT.
    - "na": does not apply to this part — say why.
    - "skipped": applies but could not be verified (missing documentation) —
      say what was missing; the version reads checked-partial.
    - "flagged": verified and found WRONG, deliberately NOT fixed — the note
      MUST describe the exact discrepancy (e.g. "pad pitch 0.5mm, datasheet
      says 0.65mm"). Flagging puts the part on the issues list for a later
      correction pass; use it when the user asked for review without changes,
      or when a fix needs their decision. Do not silently fix AND flag —
      one or the other.
    Verify HONESTLY: read the datasheet first (read_datasheet); never mark
    "checked" on something you did not actually compare.

    A check the checklist does not list is allowed — key it "custom.<slug>"
    and INCLUDE a "text" saying what you checked (an off-checklist key with no
    text is refused, because the record is the only place that wording lives).
    It is recorded on this part alone and does not change the checklist. The
    review card in the web UI adds them the same way.

    Args:
        kind: "component" | "symbol" | "footprint".
        name: The exact name.
        items_json: JSON array of {"key", "result", "note"} answers
            (plus "text" for a custom key).
        note: Optional overall note (what documentation was used).
    """
    from . import review as review_svc

    db = SessionLocal()
    try:
        parent, version_id, err = _review_subject(db, kind, name)
        if err:
            return json.dumps({"error": err})
        try:
            items = json.loads(items_json)
            assert isinstance(items, list) and all(isinstance(i, dict) for i in items)
        except Exception:
            return json.dumps({"error": "items_json must be a JSON array of "
                                        '{"key", "result", "note"} objects'})
        bad = [i for i in items if str(i.get("result", "")) == "failed"]
        if bad:
            return json.dumps({"error": "result 'failed' is reserved for machine checks — "
                                        "use 'flagged' with a note describing the defect "
                                        "(second-pass list), or fix the data and re-publish"})
        res = review_svc.record_check(db, kind, parent, version_id, actor="jaravis",
                                      actor_type="agent", items=items, note=note or None)
        db.commit()
        return json.dumps({"ok": True, "kind": kind, "name": parent.name,
                           "state": res["state"], "blocked_items": res["blocked"]})
    finally:
        db.close()


@beta_tool
def get_review_worklist(limit: int = 20) -> str:
    """Subjects the user QUEUED for you to verify — work these before picking
    parts yourself. Each row names a component, symbol or footprint whose
    current version awaits a documentation check. For each one: read the
    datasheet (read_datasheet), compare with get_symbol / get_footprint /
    get_component, then record_verification — recording ANY verification on
    the subject marks its request done automatically. Requests carry an
    optional note from the user; respect it.

    Args:
        limit: Max rows (default 20, cap 100) — verify a batch, then re-read.
    """
    db = SessionLocal()
    try:
        rows = (db.query(M.ReviewRequest).filter_by(done_at=None)
                .order_by(M.ReviewRequest.id).limit(max(1, min(limit, 100))).all())
        names: dict[tuple[str, int], str] = {}
        for kind, model in (("component", M.Component), ("symbol", M.Symbol),
                            ("footprint", M.Footprint)):
            ids = [r.subject_id for r in rows if r.subject_kind == kind]
            if ids:
                for pid, name in db.query(model.id, model.name).filter(model.id.in_(ids)):
                    names[(kind, pid)] = name
        open_total = db.query(M.ReviewRequest).filter_by(done_at=None).count()
        return json.dumps({
            "open_total": open_total,
            "items": [{"kind": r.subject_kind,
                       "name": names.get((r.subject_kind, r.subject_id), "?"),
                       "note": r.note, "requested_by": r.requested_by,
                       "requested_at": r.requested_at.isoformat()} for r in rows],
        })
    finally:
        db.close()


@beta_tool
def list_reviews(state: str = "") -> str:
    """Review states across the library: every component's effective state
    (its own record AND its pinned symbol/footprint records — the weakest leg
    wins). States: unreviewed, failed (machine check violations), partial
    (skipped/unanswered items), checked. Filter with `state`; empty = all.
    Use this to find what still needs verification.

    Args:
        state: Optional filter — "unreviewed" | "failed" | "partial" | "checked".
    """
    from . import review as review_svc

    db = SessionLocal()
    try:
        from sqlalchemy.orm import selectinload

        comps = db.query(M.Component).options(
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties)
        ).all()
        states = review_svc.states_for_components(db, comps)
        items = [
            {"component": c.name, "state": states[c.id]["state"],
             "provenance": states[c.id].get("provenance"),
             "blockers": states[c.id].get("blockers", []),
             "lifecycle": c.lifecycle_state}
            for c in comps
            if not state or states[c.id]["state"] == state
        ]
        counts: dict[str, int] = {}
        for s in states.values():
            counts[s["state"]] = counts.get(s["state"], 0) + 1
        return json.dumps({"counts": counts, "total": len(items), "items": items})
    finally:
        db.close()


TOOLS = [
    # library reads
    search_components, get_component, list_categories, list_base_symbols,
    list_footprints, get_symbol, get_footprint, read_datasheet,
    search_datasheets, datasheet_outline,
    get_price_history, get_audit_log, list_models3d, list_skills, get_skill,
    list_signoffs,
    # review axis
    get_review_checklist, record_verification, list_reviews, get_review_worklist,
    # external lookup
    lcsc_lookup, search_jlc_parts, get_jlc_details, refresh_supply,
    # projects
    list_projects, get_project, get_project_bom, get_production_run,
    component_where_used,
    # writes — every one of these auto-publishes (skills included, 2026-08-24)
    propose_new_component, propose_component_edit,
    propose_symbol_edit, propose_footprint_edit, propose_skill_update,
    set_footprint_package_name,
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
You help the user browse the component library, answer questions about it, add new
components and edit existing ones (including symbol and footprint geometry), verify parts
against their datasheets, and research parts on the internet. You act through the tools
below.

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
- list_signoffs(state) — production sign-off state of every component. A sign-off means
  a HUMAN checked the symbol, the land pattern and the part number before boards were
  built. It is NOT the same as a version being published: approval only means the edit
  was let into the library. `stale` means an older version was checked and something
  material changed since — `needs_recheck_because` names what. You may READ this and
  report on it; you may never sign anything off, and you must never describe an unsigned
  or stale part as verified.

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

Write (every one of these PUBLISHES IMMEDIATELY — the propose_* names are historical):
- propose_new_component(...) — a brand-new component
- propose_component_edit(...) — a new version of an existing component
- propose_symbol_edit(name, source_text, comment) — a new version of a base symbol
  (or a new base symbol). Call get_symbol first and edit its returned source.
- propose_footprint_edit(name, source_text, comment) — a new version of a footprint
  (or a new footprint). Call get_footprint first and edit its returned source.
- propose_skill_update(skill_name, content, comment) — a new version of one of your own
  skill documents (call get_skill first; content replaces the whole document)
- set_footprint_package_name(name, package_name) — the footprint's SHORT package name
  ("0402", "SOT-23-6", "VQFN-HR-9"), which is what {{Footprint_Name}} resolves to in a
  ki_description. Unversioned: it mints no footprint version. Call it right after
  publishing a BRAND-NEW footprint — a new one has no package name, so the first
  component referencing it publishes with an unresolved {{Footprint_Name}} mirror warning.

## What you cannot do
- You have no shell, no Python interpreter, and no filesystem. The previous file-based
  workflow — a command-line generation-and-validation pipeline and CLI import tools — is
  not available to you. Never tell the user to run it, and never claim to have run
  anything yourself.
- You cannot create or edit 3D models — only reference ones that exist (list_models3d).
- You cannot sign a part off for production. That is a human act.

## There is no approval gate — accountability is the review axis
Nothing you write waits for approval: a write lands in the live library, the mirror and
the KiCad catalog. What replaced the gate is the REVIEW AXIS. Every publish records a
machine validation; you then verify the version against its documentation with
get_review_checklist / record_verification, and a human signs it off for production.
So:
- Say what you CHANGED, not what you proposed, and name the new version number.
- Be honest in a verification: `skipped` when the documentation does not let you check an
  item, `flagged` (note required) when you checked it and found it WRONG but did not fix
  it, never `checked` on a guess.
- Versions are immutable, so the undo is a new version restoring the old content — say so
  plainly instead of implying a change can be withdrawn.
- Check component_where_used before editing a part that is in use, and prefer reusing an
  existing symbol/footprint over adding a near-duplicate.
Prices are auto-managed (refreshed from LCSC) — never set price properties. Datasheets are
managed separately — pass a URL via datasheet_url, never as a "Datasheet" property.

## Adding a component (typical flow)
1. Given an LCSC number, call lcsc_lookup first for real metadata — never guess values.
2. Pick the category (list_categories) and an existing base symbol (list_base_symbols) and
   footprint (list_footprints) that match the part's package and pin count.
3. Open a similar existing component in the same category with get_component and mirror its
   property set and order.
4. If a needed footprint or base symbol does not exist, you may create one with
   propose_footprint_edit / propose_symbol_edit (new name = creation) — but prefer reusing
   an existing one, and say clearly that the new geometry is live and unverified.
5. Call propose_new_component (or propose_component_edit), then tell the user which
   version you published and what still needs verifying.

## Verifying a part against its datasheet (typical flow)
1. read_datasheet for the pinout and package-drawing pages (look at the IMAGES — pin-1
   markers, pad dimensions and pitch are graphical).
2. get_symbol — compare pin numbers, names and electrical types against the pinout.
3. get_footprint — compare pad numbering, pitch, pad sizes and courtyard against the
   package drawing (all dimensions in mm).
4. Report what is confirmed vs. mismatched, citing datasheet page numbers. Record the
   result with record_verification — `flagged` for something you found wrong and left
   alone. Only make the fix itself when the user asks for it: it publishes at once.

## Editing geometry (symbols / footprints)
Symbol and footprint sources are KiCad s-expressions; edit them exactly (grid-aligned
coordinates in mm, matching the conventions in your skill documents). Keep edits minimal —
change what the task needs, preserve everything else. Note: components pin the symbol
drawing version they were generated with; the KiCad-facing base library and HTTP catalog
always use the newest published drawing, so a symbol edit takes effect there immediately,
and the components pinned to the old drawing are repointed automatically.

## Your skill documents
Below are your editable convention guides — naming, properties, and how to choose
footprints and base symbols. They are the current version from the Skills page; the user
can edit them, and you can update them with propose_skill_update when you learn a lasting
rule. That write is live for every later agent run, so make it a rule worth keeping.
Follow their conventions.

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
