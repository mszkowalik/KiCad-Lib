"""Private JLCPCB parts library (consigned stock): cached inventory,
manual sync from the JLCPCB OpenAPI, and valuation totals."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import fx, jlc, jlc_ledger, jlc_web, journal
from .util import acting_name, audit

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
            "JLC_SECRET_KEY in .env (apply at https://api.jlcpcb.com)",
        )
    try:
        report = jlc.sync(db)
    except jlc.JlcError as e:
        raise HTTPException(502, str(e)) from e
    # The ledger comes with the balance, not on a second button. A balance alone
    # can only say THAT we disagree; the ledger says why, and a sync that fetched
    # one without the other is how a disagreement sits unexplained for a year.
    # Best effort: the balance is the OpenAPI's and must not fail because the
    # browser session has lapsed.
    if jlc_web.available(db):
        try:
            report["ledger"] = jlc_ledger.sync(db)
        except (jlc_web.JlcWebError, jlc_web.JlcSessionExpired) as e:
            report["ledger"] = {"error": str(e)}
    else:
        report["ledger"] = {"error": "no JLCPCB browser session stored"}
    audit(db, "jlc.stock.sync", "jlc_stock", None, report)
    db.commit()
    return report


@router.post("/stock/ledger/sync")
def sync_ledger(only: str = "", db: Session = Depends(get_db)):
    """Pull JLC's OWN per-part inventory ledger into the platform.

    Separate from `/stock/sync` because it needs the BROWSER session, not the
    OpenAPI credentials: `customerPresaleStockKeyId` — the ledger's only key —
    appears in the web stock list and nowhere else.

    `only` takes a comma-separated list of LCSC codes for a single part's
    history; empty means the whole library (67 parts, 648 rows today).
    """
    if not jlc_web.available(db):
        raise HTTPException(409, "no JLCPCB browser session stored — paste cookies first")
    try:
        report = jlc_ledger.sync(db, [c.strip() for c in only.split(",") if c.strip()])
    except jlc_web.JlcSessionExpired as e:
        raise HTTPException(401, str(e)) from e
    except jlc_web.JlcWebError as e:
        raise HTTPException(502, str(e)) from e
    audit(db, "jlc.stock.ledger.sync", "jlc_stock", None, report)
    db.commit()
    return report


@router.get("/stock/ledger")
def ledger(lcsc: str = "", db: Session = Depends(get_db)):
    """What JLC's ledger and the platform cannot say about each other.

    Both directions, because they are different defects — a movement we never
    recorded, and a purchase we recorded that JLC never received.
    """
    out = jlc_ledger.unexplained(db, lcsc)
    out["bookable"] = jlc_ledger.bookable(db)
    return out


@router.get("/stock/ledger/{lcsc}")
def ledger_for_part(lcsc: str, db: Session = Depends(get_db)):
    """One part's ledger as JLC keeps it, oldest first."""
    rows = (db.query(M.JlcStockChange).filter(M.JlcStockChange.lcsc == lcsc.upper())
              .order_by(M.JlcStockChange.changed_at).all())
    if not rows:
        raise HTTPException(404, f"no ledger synced for {lcsc} — run /stock/ledger/sync")
    return {
        "lcsc": rows[0].lcsc, "mpn": rows[0].mpn,
        "rows": [{
            "changed_at": r.changed_at.astimezone(jlc_ledger.JLC_TZ).isoformat(),
            "change_qty": r.change_qty, "qty_before": r.qty_before,
            "qty_after": r.qty_after, "paid_usd": r.paid_usd,
            "business_code": r.business_code, "business_type": r.business_type,
            "void": r.change_status == jlc_ledger.STATUS_VOID,
            "remark": r.remark,
        } for r in rows],
        "balance": sum(r.change_qty for r in rows
                       if r.change_status != jlc_ledger.STATUS_VOID),
    }


@router.post("/stock/ledger/book")
def book_ledger_rows(change_key_ids: str = "", dry_run: bool = True,
                     db: Session = Depends(get_db)):
    """Write chosen ledger rows as uncharged draws.

    `change_key_ids` is a comma-separated list from `/stock/ledger`; empty means
    every bookable row. The caller chooses — nothing here decides on its own
    that stock should move.
    """
    actor = acting_name()
    ids = [int(x) for x in change_key_ids.replace(" ", "").split(",") if x]
    if dry_run:
        # `book` writes nothing on a dry run — it prices and checks, then
        # reports. There is no rollback to do.
        return jlc_ledger.book(db, ids, actor=actor, dry_run=True)
    with journal.batch(db, kind="jlc.ledger.book", source_ref=change_key_ids or "all",
                       actor=actor) as h:
        res = jlc_ledger.book(db, ids, actor=actor, dry_run=False)
    audit(db, "jlc.stock.ledger.book", "component_consumption", None,
          {**res["totals"], "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**res, "batch_id": h["batch_id"], "reversible": True}


@router.get("/stock/item/{item_id}/raw")
def raw_item(item_id: int, db: Session = Depends(get_db)):
    """Untouched API payload — for diagnosing field-mapping gaps."""
    i = db.get(M.JlcStockItem, item_id)
    if i is None:
        raise HTTPException(404, "item not found")
    return i.raw or {}


