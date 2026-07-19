"""Private JLCPCB parts library (consigned stock): cached inventory,
manual sync from the JLCPCB OpenAPI, and valuation totals."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import fx, jlc
from .util import audit

router = APIRouter(prefix="/api/jlc", tags=["jlc-stock"])


@router.get("/stock")
def stock(currency: str | None = None, db: Session = Depends(get_db)):
    cur = (currency or settings.default_currency).upper()
    rates = fx.get_rates(db)
    items = db.query(M.JlcStockItem).order_by(M.JlcStockItem.lcsc).all()
    comp_names: dict[int, str] = {}
    ids = {i.component_id for i in items if i.component_id}
    if ids:
        for c in db.query(M.Component).filter(M.Component.id.in_(ids)).all():
            comp_names[c.id] = c.name
    out = []
    total_usd = 0.0
    total_qty = 0
    unvalued = 0
    for i in items:
        value_usd = (i.unit_price_usd or 0) * i.qty if i.unit_price_usd is not None else None
        if value_usd is None:
            unvalued += 1
        else:
            total_usd += value_usd
        total_qty += i.qty
        value_disp, _known = fx.convert(value_usd, "USD", cur, rates) if value_usd is not None else (None, True)
        out.append(
            {
                "id": i.id,
                "lcsc": i.lcsc,
                "description": i.description,
                "mpn": i.mpn,
                "manufacturer": i.manufacturer,
                "package": i.package,
                "qty": i.qty,
                "unit_price_usd": i.unit_price_usd,
                "value": round(value_disp, 4) if value_disp is not None else None,
                "component_id": i.component_id,
                "component_name": comp_names.get(i.component_id or -1),
            }
        )
    total_disp, _known = fx.convert(total_usd, "USD", cur, rates)
    last = max((i.updated_at for i in items), default=None)
    return {
        "available": jlc.available(),
        "items": out,
        "currency": cur,
        "totals": {
            "parts": len(items),
            "quantity": total_qty,
            "value": round(total_disp, 2),
            "value_usd": round(total_usd, 2),
            "unvalued_parts": unvalued,
        },
        "last_sync": last.isoformat() if last else None,
    }


@router.post("/stock/sync")
def sync(db: Session = Depends(get_db)):
    if not jlc.available():
        raise HTTPException(
            409,
            "JLC API credentials not configured — set JLC_APP_ID / JLC_ACCESS_KEY / "
            "JLC_SECRET_KEY in platform/.env (apply at https://api.jlcpcb.com)",
        )
    try:
        report = jlc.sync(db)
    except jlc.JlcError as e:
        raise HTTPException(502, str(e)) from e
    audit(db, "jlc.stock.sync", "jlc_stock", None, report)
    db.commit()
    return report


@router.get("/stock/item/{item_id}/raw")
def raw_item(item_id: int, db: Session = Depends(get_db)):
    """Untouched API payload — for diagnosing field-mapping gaps."""
    i = db.get(M.JlcStockItem, item_id)
    if i is None:
        raise HTTPException(404, "item not found")
    return i.raw or {}


@router.get("/stock/usage")
def stock_usage(db: Session = Depends(get_db)):
    """Where held parts are used: latest ready snapshot of every project."""
    private = jlc.private_stock_map(db)
    if not private:
        return []
    out = []
    for p in db.query(M.Project).order_by(M.Project.name).all():
        latest = (
            db.query(M.ProjectSnapshot)
            .filter_by(project_id=p.id, status="ready")
            .order_by(M.ProjectSnapshot.created_at.desc())
            .first()
        )
        if latest is None:
            continue
        lines = (
            db.query(M.SnapshotBomLine)
            .filter(
                M.SnapshotBomLine.snapshot_id == latest.id,
                M.SnapshotBomLine.lcsc.in_(list(private.keys())),
                M.SnapshotBomLine.variant == "",
            )
            .all()
        )
        if lines:
            out.append(
                {
                    "project_id": p.id,
                    "project_name": p.name,
                    "parts": [
                        {"lcsc": li.lcsc, "refs": li.refs, "qty_per_device": li.qty,
                         "board": li.board, "held": private.get(li.lcsc, 0)}
                        for li in lines
                    ],
                }
            )
    return out
