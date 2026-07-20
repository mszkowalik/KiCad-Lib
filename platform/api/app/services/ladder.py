"""Full LCSC price ladders + supply info (stock / MOQ), per component.

Extends the legacy 3-point ComponentPrice summary (which stays authoritative
for KiCad symbol injection): every ladder tier is stored as its own
ComponentPricePoint row with currency and refresh date, so project BOMs can
price any production volume. Rows with source != "LCSC" (e.g. "Manual",
used for BOM-only parts with quoted prices) are never touched here.
"""
from __future__ import annotations

import logging
import threading
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models as M
from ..config import settings
from ..db import SessionLocal
from ..models import utcnow

log = logging.getLogger(__name__)

DETAIL_URL = "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={}"


def fetch_detail(lcsc_id: str) -> dict | None:
    try:
        resp = httpx.get(
            DETAIL_URL.format(lcsc_id),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
        result = resp.json().get("result")
        return result if isinstance(result, dict) else None
    except Exception as e:
        log.debug(f"LCSC detail fetch failed for {lcsc_id}: {e}")
        return None


def _int_or_none(v) -> int | None:
    try:
        n = int(v)
        return n if n >= 0 else None
    except (TypeError, ValueError):
        return None


def lcsc_part_of(cv: M.ComponentVersion) -> str:
    for p in cv.properties:
        if p.key == "LCSC Part" and not p.is_null and p.value:
            return p.value.strip()
    return ""


def component_lcsc_map(db: Session) -> dict[int, str]:
    """component_id -> LCSC part, from each component's current published
    version. Also the reverse-lookup base for BOM matching."""
    comps = db.execute(
        select(M.Component).options(
            selectinload(M.Component.versions).selectinload(M.ComponentVersion.properties)
        )
    ).scalars().all()
    out: dict[int, str] = {}
    for comp in comps:
        cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
        if cv is None:
            continue
        lcsc = lcsc_part_of(cv)
        if lcsc:
            out[comp.id] = lcsc
    return out


_JLC_UNFETCHED = object()  # sentinel: caller did not prefetch a JLC detail row


def _jlc_rows(codes: list[str]) -> dict[str, dict]:
    """Official-API JLC detail rows keyed by LCSC code; {} when the JLC API
    is not configured or the fetch fails. Imported lazily — jlc.py imports
    this module at load time."""
    from . import jlc

    if not jlc.available():
        return {}
    try:
        return jlc.fetch_component_details(codes)
    except Exception as e:
        log.debug(f"JLC detail fetch failed: {e}")
        return {}


def _update_price_summary(db: Session, component_id: int, tiers: list[tuple[int, float]], now) -> None:
    """Derive the legacy 3-point ComponentPrice summary (injected into
    generated KiCad symbols) from the fresh LCSC ladder, mirroring the repo's
    kicad_lib/pricing.py conventions: @1 / @100 / @Bulk (1000-break, or the
    5000 tier when no tier <= 1000), 4 decimals. A summary whose source is
    anything other than LCSC (e.g. Manual) is pinned — never overwritten."""

    def at(qty: int) -> tuple[int, float]:
        best = None
        for q, p in sorted(tiers):
            if q <= qty:
                best = (q, p)
        return best or sorted(tiers)[0]

    row = db.query(M.ComponentPrice).filter_by(component_id=component_id).first()
    if row is not None and row.source not in (None, "", "LCSC"):
        return
    if row is None:
        row = M.ComponentPrice(component_id=component_id)
        db.add(row)
    bulk_target = 1000 if any(q <= 1000 for q, _ in tiers) else 5000
    _, p1 = at(1)
    _, p100 = at(100)
    bulk_q, p_bulk = at(bulk_target)
    row.price_1 = f"{p1:.4f}"
    row.price_100 = f"{p100:.4f}"
    row.price_bulk = f"{p_bulk:.4f}"
    row.bulk_qty = str(bulk_q)
    row.source = "LCSC"
    row.updated = now.date().isoformat()


def refresh_component(db: Session, component_id: int, lcsc_id: str, jlc_row=_JLC_UNFETCHED) -> bool:
    """Replace the LCSC-sourced ladder + supply info for one component.
    Also refreshes `jlc_stock` (JLCPCB assembly pool) from the official JLC
    API — pass a prefetched `jlc_row` (dict or None) when batching to avoid
    one API call per component. Returns True when data was written."""
    detail = fetch_detail(lcsc_id)
    if not detail:
        return False
    ladder = detail.get("productPriceList") or []
    tiers: list[tuple[int, float]] = []
    for t in ladder:
        try:
            tiers.append((int(t["ladder"]), float(t["usdPrice"])))
        except (KeyError, TypeError, ValueError):
            continue
    now = utcnow()
    if tiers:
        # capture the pre-change state first (no-op when already recorded) so
        # the timeline keeps what prices were in effect before this refresh
        record_price_history(db, component_id)
        db.query(M.ComponentPricePoint).filter_by(component_id=component_id, source="LCSC").delete()
        for qty_from, price in sorted(tiers):
            db.add(
                M.ComponentPricePoint(
                    component_id=component_id,
                    source="LCSC",
                    qty_from=qty_from,
                    unit_price=price,
                    currency="USD",
                    updated_at=now,
                )
            )
        _update_price_summary(db, component_id, tiers, now)
        record_price_history(db, component_id)
    supply = db.query(M.ComponentSupply).filter_by(component_id=component_id).first()
    if supply is None:
        supply = M.ComponentSupply(component_id=component_id)
        db.add(supply)
    supply.stock = _int_or_none(detail.get("stockNumber"))
    moq = _int_or_none(detail.get("minBuyNumber"))
    supply.moq = moq
    # LCSC order quantities step in MOQ increments (cut tape); best estimate.
    supply.order_multiple = moq
    if jlc_row is _JLC_UNFETCHED:
        jlc_row = _jlc_rows([lcsc_id]).get(lcsc_id)
    if isinstance(jlc_row, dict):
        supply.jlc_stock = _int_or_none(jlc_row.get("stockCount"))
    supply.checked_at = now
    db.commit()
    return bool(tiers)


def refresh_stale(max_age_days: int | None = None) -> dict:
    """Refresh ladders for every LCSC-linked component whose points are
    missing or older than max_age_days. Own session — runs in background."""
    max_age = timedelta(days=max_age_days or settings.price_ladder_max_age_days)
    db = SessionLocal()
    try:
        lcsc_by_comp = component_lcsc_map(db)
        newest: dict[int, object] = {}
        for row in db.query(M.ComponentPricePoint).filter_by(source="LCSC").all():
            cur = newest.get(row.component_id)
            if cur is None or row.updated_at > cur:
                newest[row.component_id] = row.updated_at
        now = utcnow()
        # One batched official-API call for JLCPCB assembly stock — cheap
        # enough to refresh for EVERY component, including ladder-fresh ones.
        jlc_rows = _jlc_rows(list(lcsc_by_comp.values()))
        updated = skipped = failed = 0
        for comp_id, lcsc in lcsc_by_comp.items():
            ts = newest.get(comp_id)
            if ts is not None and now - ts < max_age:
                skipped += 1
                row = jlc_rows.get(lcsc)
                if isinstance(row, dict):
                    supply = db.query(M.ComponentSupply).filter_by(component_id=comp_id).first()
                    if supply is None:
                        supply = M.ComponentSupply(component_id=comp_id)
                        db.add(supply)
                    supply.jlc_stock = _int_or_none(row.get("stockCount"))
                continue
            if refresh_component(db, comp_id, lcsc, jlc_row=jlc_rows.get(lcsc)):
                updated += 1
            else:
                failed += 1
        db.commit()
        report = {"updated": updated, "fresh": skipped, "failed": failed, "lcsc_components": len(lcsc_by_comp)}
        log.info(f"price ladder refresh: {report}")
        return report
    finally:
        db.close()


_started = False


def start_background_refresh(delay_s: float = 20.0) -> None:
    """Kick a one-shot stale-ladder refresh shortly after startup."""
    global _started
    if _started:
        return
    _started = True
    t = threading.Timer(delay_s, lambda: refresh_stale())
    t.daemon = True
    t.start()


# ----------------------------------------------------------- price history

def summary_points(pr: M.ComponentPrice) -> list[M.ComponentPricePoint]:
    """Synthesize ladder points from the legacy 3-point `component_prices`
    summary, so a part that has a summary price but no ladder still prices in
    the BOM. Summary values are USD strings. Transient objects: never added
    to the session."""
    def _num(s: str | None) -> float | None:
        try:
            return float(s) if s not in (None, "") else None
        except (TypeError, ValueError):
            return None

    def _qty(s: str | None, default: int) -> int:
        try:
            n = int(float(s))  # type: ignore[arg-type]
            return n if n > 0 else default
        except (TypeError, ValueError):
            return default

    tiers: list[tuple[int, float]] = []
    p1, p100, pbulk = _num(pr.price_1), _num(pr.price_100), _num(pr.price_bulk)
    if p1 is not None:
        tiers.append((1, p1))
    if p100 is not None:
        tiers.append((100, p100))
    if pbulk is not None:
        # only tier present → apply from qty 1; otherwise at the recorded bulk break
        tiers.append((1 if not tiers else _qty(pr.bulk_qty, 1000), pbulk))
    source = pr.source or "Manual"
    return [
        M.ComponentPricePoint(component_id=pr.component_id, source=source,
                              qty_from=qf, unit_price=up, currency="USD", updated_at=None)
        for qf, up in tiers
    ]


def _effective_state(db: Session, component_id: int) -> list[dict]:
    """The component's complete effective point set as plain sorted dicts —
    real ladder points when any exist, else points synthesized from the
    legacy summary. This is the unit of price history."""
    rows = db.query(M.ComponentPricePoint).filter_by(component_id=component_id).all()
    if not rows:
        pr = db.query(M.ComponentPrice).filter_by(component_id=component_id).first()
        rows = summary_points(pr) if pr is not None else []
    state = [
        {"source": p.source, "qty_from": p.qty_from,
         "unit_price": p.unit_price, "currency": p.currency}
        for p in rows
    ]
    state.sort(key=lambda d: (d["source"], d["qty_from"]))
    return state


def record_price_history(db: Session, component_id: int) -> bool:
    """Append a ComponentPriceHistory snapshot if the effective point set
    changed since the last one (an empty set records a deletion). Call after
    ANY price mutation, before commit — does not commit itself. Returns True
    when a row was appended."""
    db.flush()
    state = _effective_state(db, component_id)
    last = (
        db.query(M.ComponentPriceHistory).filter_by(component_id=component_id)
        .order_by(M.ComponentPriceHistory.recorded_at.desc(), M.ComponentPriceHistory.id.desc())
        .first()
    )
    if last is not None and last.points == state:
        return False
    db.add(M.ComponentPriceHistory(component_id=component_id, points=state, recorded_at=utcnow()))
    return True


def history_points_at(db: Session, component_ids: set[int], at) -> dict[int, list[M.ComponentPricePoint]]:
    """Resolve each component's price points AS OF `at` from history: the
    latest snapshot at-or-before `at`, else the earliest one after it (the
    closest available). Components with no history rows are absent from the
    result — callers fall back to live points. Returned points are transient
    objects, never added to the session."""
    out: dict[int, list[M.ComponentPricePoint]] = {}
    if not component_ids:
        return out
    rows = (
        db.query(M.ComponentPriceHistory)
        .filter(M.ComponentPriceHistory.component_id.in_(component_ids))
        .order_by(M.ComponentPriceHistory.recorded_at, M.ComponentPriceHistory.id)
        .all()
    )
    by_comp: dict[int, list[M.ComponentPriceHistory]] = {}
    for r in rows:
        by_comp.setdefault(r.component_id, []).append(r)
    for cid, hist in by_comp.items():
        chosen = hist[0]
        for r in hist:
            if r.recorded_at <= at:
                chosen = r
        out[cid] = [
            M.ComponentPricePoint(
                component_id=cid,
                source=str(p.get("source") or "Manual"),
                qty_from=int(p.get("qty_from") or 1),
                unit_price=float(p.get("unit_price") or 0.0),
                currency=str(p.get("currency") or "USD"),
                updated_at=chosen.recorded_at,
            )
            for p in (chosen.points or [])
        ]
    return out


def price_at(points: list[M.ComponentPricePoint], qty: int) -> M.ComponentPricePoint | None:
    """Best (highest-qty) tier whose qty_from <= qty; smallest tier when the
    qty sits below the ladder. Manual points win over LCSC on equal qty_from."""
    if not points:
        return None
    # ascending qty; on equal qty_from, Manual sorts last so it overwrites
    # the LCSC tier in the scan below
    order = {"Manual": 1}
    ranked = sorted(points, key=lambda p: (p.qty_from, order.get(p.source, 0)))
    best = None
    for p in ranked:
        if p.qty_from <= qty:
            best = p
    return best or ranked[0]
