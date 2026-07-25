"""Symbol & footprint templates — list (edit-UI picker + Templates browser),
per-template detail, and pixel-exact KiCad previews."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.mirror import top_level_of, update_mirror_symbols
from ..services.render import render_svg
from .util import audit

router = APIRouter(prefix="/api", tags=["libraries"])


def _current(parent) -> object | None:
    """The parent's live version object, or None if unpublished."""
    return next((v for v in parent.versions if v.id == parent.current_version_id), None)


def _comment_counts(db: Session, target_type: str) -> dict[int, int]:
    rows = (
        db.query(M.Comment.target_id, func.count(M.Comment.id))
        .filter(M.Comment.target_type == target_type)
        .group_by(M.Comment.target_id)
        .all()
    )
    return {tid: n for tid, n in rows}


def _used_by(db: Session, parent, ver_attr: str) -> list[dict]:
    """Components whose CURRENT version pins one of this template's versions."""
    ver_ids = [v.id for v in parent.versions]
    if not ver_ids:
        return []
    col = getattr(M.ComponentVersion, ver_attr)
    rows = (
        db.query(M.Component.id, M.Component.name)
        .join(M.ComponentVersion, M.ComponentVersion.id == M.Component.current_version_id)
        .filter(col.in_(ver_ids))
        .order_by(M.Component.name)
        .all()
    )
    return [{"id": cid, "name": name} for cid, name in rows]


# ---------------------------------------------------------------- list
@router.get("/symbols")
def list_symbols(db: Session = Depends(get_db)):
    symbols = (
        db.query(M.Symbol).options(selectinload(M.Symbol.versions)).order_by(M.Symbol.name).all()
    )
    counts = _comment_counts(db, "symbol")
    out = []
    for s in symbols:
        cur = _current(s)
        out.append({
            "id": s.id,
            "name": s.name,
            "version_no": cur.version_no if cur else None,
            "pin_count": (cur.parsed or {}).get("pin_count") if cur else None,
            "comment_count": counts.get(s.id, 0),
        })
    return out


@router.get("/footprints")
def list_footprints(db: Session = Depends(get_db)):
    footprints = (
        db.query(M.Footprint).options(selectinload(M.Footprint.versions)).order_by(M.Footprint.name).all()
    )
    counts = _comment_counts(db, "footprint")
    out = []
    for f in footprints:
        cur = _current(f)
        out.append({
            "id": f.id,
            "name": f.name,
            "version_no": cur.version_no if cur else None,
            "pad_count": (cur.parsed or {}).get("pad_count") if cur else None,
            "comment_count": counts.get(f.id, 0),
        })
    return out


# ---------------------------------------------------------------- detail
@router.get("/symbols/{sym_id}")
def get_symbol(sym_id: int, db: Session = Depends(get_db)):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    cur = _current(s)
    return {
        "id": s.id,
        "name": s.name,
        "kind": "symbol",
        "version_no": cur.version_no if cur else None,
        "created_at": cur.created_at.isoformat() if cur else None,
        "created_by": cur.created_by if cur else None,
        "comment": cur.comment if cur else None,
        "parsed": (cur.parsed or {}) if cur else {},
        "source_text": cur.source_text if cur else None,
        "used_by": _used_by(db, s, "symbol_version_id"),
    }


@router.get("/footprints/{fp_id}")
def get_footprint(fp_id: int, db: Session = Depends(get_db)):
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    cur = _current(f)
    return {
        "id": f.id,
        "name": f.name,
        "display_name": f.display_name or "",
        "kind": "footprint",
        "version_no": cur.version_no if cur else None,
        "created_at": cur.created_at.isoformat() if cur else None,
        "created_by": cur.created_by if cur else None,
        "comment": cur.comment if cur else None,
        "parsed": (cur.parsed or {}) if cur else {},
        "source_text": cur.source_text if cur else None,
        "models": (cur.models or []) if cur else [],
        "used_by": _used_by(db, f, "footprint_version_id"),
    }


class FootprintMeta(BaseModel):
    """Unversioned footprint metadata (see the note on M.Footprint)."""

    display_name: str


@router.patch("/footprints/{fp_id}")
def set_footprint_display_name(fp_id: int, body: FootprintMeta, db: Session = Depends(get_db)):
    """Set the short package name that `{Footprint_Name}` templates resolve to.

    Unversioned, so this mints no footprint version — but it does change every
    generated `ki_description` that references it, so the affected symbol
    libraries are rebuilt straight away."""
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    f.display_name = body.display_name.strip()[:200]
    audit(db, "footprint.describe", "footprint", f.id,
          {"name": f.name, "display_name": f.display_name})
    db.commit()

    # The name is baked into every generated ki_description that references
    # {Footprint_Name}, so rebuild the symbol libraries of the categories whose
    # components use this footprint — the .kicad_mod itself is unaffected.
    tops: set[str] = set()
    for comp in db.query(M.Component).options(selectinload(M.Component.versions)).all():
        cv = _current(comp)
        if cv is None or cv.category is None:
            continue
        if any(p.key == "Footprint" and p.value == f"7Sigma:{f.name}" for p in cv.properties):
            tops.add(top_level_of(cv.category).name)
    mirror = update_mirror_symbols(db, settings, tops) if tops else {"warnings": []}
    return {"id": f.id, "name": f.name, "display_name": f.display_name,
            "rebuilt_libraries": sorted(tops),
            "mirror_warnings": mirror.get("warnings", [])}


# ---------------------------------------------------------------- preview
def _preview(kind: str, parent, db: Session) -> Response:
    cur = _current(parent)
    if cur is None:
        raise HTTPException(404, "no published version to preview")
    try:
        svg = render_svg(kind, parent.name, cur.source_text)
    except Exception as e:  # noqa: BLE001 — surface render failures to the UI
        raise HTTPException(502, f"render failed: {e}") from e
    return Response(content=svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "no-cache"})


@router.get("/symbols/{sym_id}/preview.svg")
def symbol_preview(sym_id: int, db: Session = Depends(get_db)):
    s = db.get(M.Symbol, sym_id)
    if s is None:
        raise HTTPException(404, "symbol not found")
    return _preview("symbol", s, db)


@router.get("/footprints/{fp_id}/preview.svg")
def footprint_preview(fp_id: int, db: Session = Depends(get_db)):
    f = db.get(M.Footprint, fp_id)
    if f is None:
        raise HTTPException(404, "footprint not found")
    return _preview("footprint", f, db)
