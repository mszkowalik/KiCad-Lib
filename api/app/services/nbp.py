"""NBP (Narodowy Bank Polski) exchange rates — the authority for converting
supplier invoices (user decision 2026-07-27: **NBP data, invoice date as the
exchange date**).

Table A holds the mid rate ("kurs średni") published each working day, as PLN
per unit of foreign currency. The platform's own convention is the opposite —
`ExchangeRate.rate_usd` is USD per unit of currency, pivoting through USD
(`fx.convert`) — so everything here is converted before it is stored:

    PLN : rate_usd = 1 / USDPLN
    EUR : rate_usd = EURPLN / USDPLN
    USD : 1.0

NBP publishes nothing on weekends and holidays (HTTP 404 "Brak danych"), so a
lookup walks back to the previous publication and reports which date it actually
used — a silent substitution would be a lie about a money figure.

Rates fetched for an invoice date are appended to `exchange_rate_history` with
`recorded_at` set to that date, which is what makes historical runs price
correctly: `fx.rates_at` resolves the latest row at-or-before a date, and the
platform's own history only starts 2026-07-19.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from .. import models as M

BASE = "https://api.nbp.pl/api/exchangerates/rates/a"
MAX_BACKTRACK = 10  # working-day gaps: long weekends, Christmas, Easter
TIMEOUT = 10.0


class NbpError(RuntimeError):
    pass


def _parse_date(value: str | date) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError) as exc:
        raise NbpError(f"not an ISO date: {value!r}") from exc


def mid_rate(currency: str, on: str | date) -> tuple[float, str]:
    """PLN per 1 unit of `currency` from table A.

    Returns (mid, effective_date). Walks back to the previous publication when
    the requested day has none, so the caller can see the date actually used.
    """
    cur = currency.upper()
    if cur == "PLN":
        return 1.0, _parse_date(on).isoformat()
    day = _parse_date(on)
    with httpx.Client(timeout=TIMEOUT) as client:
        for back in range(MAX_BACKTRACK + 1):
            d = (day - timedelta(days=back)).isoformat()
            r = client.get(f"{BASE}/{cur.lower()}/{d}/", params={"format": "json"})
            if r.status_code == 404:
                continue  # weekend / holiday / not yet published
            if r.status_code != 200:
                raise NbpError(f"NBP returned {r.status_code} for {cur} {d}")
            rate = r.json()["rates"][0]
            return float(rate["mid"]), rate["effectiveDate"]
    raise NbpError(f"no NBP table A publication for {cur} within {MAX_BACKTRACK} days before {day}")


def rate_usd(currency: str, on: str | date) -> tuple[float, str, dict]:
    """USD per 1 unit of `currency` on `on`, in the platform's convention.

    Returns (rate_usd, effective_date, detail) where detail carries the raw NBP
    numbers so a stored figure can always be traced back to a publication.
    """
    cur = (currency or "USD").upper()
    if cur == "USD":
        return 1.0, _parse_date(on).isoformat(), {"source": "identity"}
    usd_pln, usd_day = mid_rate("USD", on)
    if cur == "PLN":
        return 1.0 / usd_pln, usd_day, {"USDPLN": usd_pln, "effective": usd_day}
    cur_pln, cur_day = mid_rate(cur, on)
    return (
        cur_pln / usd_pln,
        cur_day,
        {f"{cur}PLN": cur_pln, "USDPLN": usd_pln, "effective": cur_day},
    )


def _as_utc(day: str) -> datetime:
    return datetime.fromisoformat(day).replace(tzinfo=timezone.utc)


def record_history(db: Session, currency: str, rate: float, on: str) -> bool:
    """Append an ExchangeRateHistory row dated `on` (the invoice date), unless an
    identical one already exists. No commit.

    Historical insertion is deliberate: `fx.rates_at` picks the latest row
    at-or-before a date, so backfilling an invoice's rate makes every run priced
    around that date resolve correctly instead of falling back to 2026 rates.
    """
    cur = currency.upper()
    at = _as_utc(on)
    existing = (
        db.query(M.ExchangeRateHistory)
        .filter(M.ExchangeRateHistory.currency == cur,
                M.ExchangeRateHistory.recorded_at == at)
        .first()
    )
    if existing is not None:
        if abs((existing.rate_usd or 0) - rate) > 1e-9:
            existing.rate_usd = rate
            return True
        return False
    db.add(M.ExchangeRateHistory(currency=cur, rate_usd=rate, recorded_at=at))
    return True


def resolve_for_document(db: Session, currency: str, doc_date: str) -> dict:
    """Rate for a supplier document, sourced from NBP at its own date.

    Records the rate into the platform's FX history as a side effect (no
    commit). Returns a payload the caller can pin onto the document and show to
    a human: rate, the publication date actually used, and the raw NBP numbers.
    """
    cur = (currency or "USD").upper()
    if cur == "USD" or not doc_date:
        return {"rate_usd": 1.0 if cur == "USD" else None, "effective_date": doc_date,
                "detail": {"source": "identity" if cur == "USD" else "no document date"}}
    rate, eff, detail = rate_usd(cur, doc_date)
    record_history(db, cur, rate, eff)
    if cur != "PLN":  # the USD/PLN leg is worth keeping too
        usd_pln = detail.get("USDPLN")
        if usd_pln:
            record_history(db, "PLN", 1.0 / usd_pln, eff)
    return {"rate_usd": rate, "effective_date": eff, "detail": detail}
