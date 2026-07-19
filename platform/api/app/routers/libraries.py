"""Symbol & footprint pickers — name lists for the edit UI."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..db import get_db

router = APIRouter(prefix="/api", tags=["libraries"])


@router.get("/symbols")
def list_symbols(db: Session = Depends(get_db)):
    symbols = (
        db.query(M.Symbol).options(selectinload(M.Symbol.versions)).order_by(M.Symbol.name).all()
    )
    out = []
    for s in symbols:
        cur = next((v for v in s.versions if v.id == s.current_version_id), None)
        out.append({
            "name": s.name,
            "version_no": cur.version_no if cur else None,
            "pin_count": (cur.parsed or {}).get("pin_count") if cur else None,
        })
    return out


@router.get("/footprints")
def list_footprints(db: Session = Depends(get_db)):
    footprints = (
        db.query(M.Footprint).options(selectinload(M.Footprint.versions)).order_by(M.Footprint.name).all()
    )
    out = []
    for f in footprints:
        cur = next((v for v in f.versions if v.id == f.current_version_id), None)
        out.append({
            "name": f.name,
            "version_no": cur.version_no if cur else None,
            "pad_count": (cur.parsed or {}).get("pad_count") if cur else None,
        })
    return out
