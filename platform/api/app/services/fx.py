"""Exchange rates — daily ECB rates via frankfurter.app (no API key), with
manual per-currency overrides that the auto-refresh never touches.

Every stored rate is "1 unit of currency = rate_usd USD"; conversions
always go through USD. Unknown currencies convert 1:1 with a warning flag
so totals never silently drop lines.
"""
from __future__ import annotations

import logging
import threading

import httpx
from sqlalchemy.orm import Session

from .. import models as M
from ..db import SessionLocal
from ..models import utcnow

log = logging.getLogger(__name__)

FRANKFURTER_URL = "https://api.frankfurter.app/latest?base=USD"


def get_rates(db: Session) -> dict[str, float]:
    rates = {"USD": 1.0}
    for row in db.query(M.ExchangeRate).all():
        rates[row.currency.upper()] = row.rate_usd
    return rates


def record_rate_history(db: Session, currency: str, rate_usd: float) -> bool:
    """Append an ExchangeRateHistory row if the rate changed since the last
    recorded one. No commit. Returns True when appended."""
    cur = currency.upper()
    last = (
        db.query(M.ExchangeRateHistory).filter_by(currency=cur)
        .order_by(M.ExchangeRateHistory.recorded_at.desc(), M.ExchangeRateHistory.id.desc())
        .first()
    )
    if last is not None and last.rate_usd == rate_usd:
        return False
    db.add(M.ExchangeRateHistory(currency=cur, rate_usd=rate_usd, recorded_at=utcnow()))
    return True


def rates_at(db: Session, at) -> dict[str, float]:
    """Rates AS OF `at` from history — per currency the latest row
    at-or-before `at`, else the earliest after it. Currencies with no history
    fall back to the current live rate (better than dropping the line)."""
    rates = get_rates(db)
    rows = (
        db.query(M.ExchangeRateHistory)
        .order_by(M.ExchangeRateHistory.recorded_at, M.ExchangeRateHistory.id)
        .all()
    )
    by_cur: dict[str, list[M.ExchangeRateHistory]] = {}
    for r in rows:
        by_cur.setdefault(r.currency.upper(), []).append(r)
    for cur, hist in by_cur.items():
        chosen = hist[0]
        for r in hist:
            if r.recorded_at <= at:
                chosen = r
        rates[cur] = chosen.rate_usd
    rates["USD"] = 1.0
    return rates


def convert(amount: float, currency: str, target: str, rates: dict[str, float]) -> tuple[float, bool]:
    """Returns (converted_amount, rate_known). Falls back to 1:1 when a
    currency has no stored rate."""
    cur, tgt = currency.upper() or "USD", target.upper() or "USD"
    if cur == tgt:
        return amount, True
    src_rate, tgt_rate = rates.get(cur), rates.get(tgt)
    if src_rate is None or tgt_rate is None or tgt_rate == 0:
        return amount, False
    return amount * src_rate / tgt_rate, True


def refresh_rates(db: Session) -> dict:
    """Upsert auto rates for all frankfurter currencies. Manual rows are
    left untouched."""
    resp = httpx.get(FRANKFURTER_URL, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    data = resp.json().get("rates") or {}
    existing = {r.currency.upper(): r for r in db.query(M.ExchangeRate).all()}
    updated = 0
    for currency, per_usd in data.items():
        if not per_usd:
            continue
        rate_usd = 1.0 / float(per_usd)  # frankfurter: 1 USD = per_usd <currency>
        row = existing.get(currency.upper())
        if row is None:
            db.add(M.ExchangeRate(currency=currency.upper(), rate_usd=rate_usd, source="auto"))
            record_rate_history(db, currency, rate_usd)
            updated += 1
        elif row.source != "manual":
            row.rate_usd = rate_usd
            row.updated_at = utcnow()
            record_rate_history(db, currency, rate_usd)
            updated += 1
    db.commit()
    return {"updated": updated, "currencies": len(data)}


_timer: threading.Timer | None = None


def start_auto_refresh(interval_h: float = 24.0) -> None:
    """Refresh now (background) and re-arm daily. Failures are logged and
    retried at the next interval — stale rates beat no rates."""

    def tick():
        global _timer
        db = SessionLocal()
        try:
            refresh_rates(db)
        except Exception as e:
            log.warning(f"fx refresh failed: {e}")
        finally:
            db.close()
        _timer = threading.Timer(interval_h * 3600, tick)
        _timer.daemon = True
        _timer.start()

    threading.Thread(target=tick, daemon=True).start()
