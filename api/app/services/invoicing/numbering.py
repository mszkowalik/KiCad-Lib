"""The four series and their monthly numbers (decision 0066).

Each series starts again at 01 every month, as 7Sigma's script numbered them:

| Series | Kinds | Format |
|---|---|---|
| VAT | `vat`, `settlement` | `NN/MM/RRRR` |
| Proforma | `proforma` | `PROF NN/MM/RRRR` |
| Correction | `correction` | `KOR NN/MM/RRRR` |
| Advance | `advance` | `ZAL NN/MM/RRRR` |

The next number is one above the highest number of the series in that month,
read from every document of the company that is not a cancelled draft — the
imported history and the invoices KSeF holds included, so a number written
directly in KSeF is never given out twice. A leading zero is optional in the
old numbers ("1/09/2026" and "01/09/2026" are the same number).
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy.orm import Session

from ... import models as M

SERIES = {"vat": "vat", "settlement": "vat", "proforma": "proforma",
          "correction": "correction", "advance": "advance"}
PREFIX = {"vat": "", "proforma": "PROF ", "correction": "KOR ", "advance": "ZAL "}
_PATTERN = {"vat": r"^0?(\d+)/0?{m}/{y}$",
            "proforma": r"^(?:PROF |PROFORMA )?0?(\d+)/0?{m}/{y}$",
            "correction": r"^KOR 0?(\d+)/0?{m}/{y}$",
            "advance": r"^ZAL 0?(\d+)/0?{m}/{y}$"}


def series_of(kind: str) -> str:
    if kind not in SERIES:
        raise ValueError(f"unknown invoice kind {kind!r}")
    return SERIES[kind]


def used_numbers(db: Session, company_id: int, kind: str, day: date,
                 exclude_id: int | None = None) -> list[int]:
    series = series_of(kind)
    rx = re.compile(_PATTERN[series].format(m=day.month, y=day.year))
    kinds = [k for k, s in SERIES.items() if s == series]
    q = (db.query(M.SalesInvoice.number)
         .filter(M.SalesInvoice.company_id == company_id, M.SalesInvoice.kind.in_(kinds),
                 M.SalesInvoice.status != "cancelled"))
    if exclude_id is not None:
        q = q.filter(M.SalesInvoice.id != exclude_id)
    return [int(m.group(1)) for (num,) in q.all() if (m := rx.match((num or "").strip()))]


def next_number(db: Session, company_id: int, kind: str, day: date,
                exclude_id: int | None = None) -> str:
    n = max(used_numbers(db, company_id, kind, day, exclude_id), default=0) + 1
    return f"{PREFIX[series_of(kind)]}{n:02d}/{day.month:02d}/{day.year}"


def taken(db: Session, company_id: int, kind: str, number: str,
          exclude_id: int | None = None) -> bool:
    """Whether a number is already used in the series (leading zeros ignored)."""
    series = series_of(kind)
    kinds = [k for k, s in SERIES.items() if s == series]

    def norm(n: str) -> str:
        return re.sub(r"(^|[ /])0+(\d)", r"\1\2", (n or "").strip())

    q = (db.query(M.SalesInvoice.number)
         .filter(M.SalesInvoice.company_id == company_id, M.SalesInvoice.kind.in_(kinds),
                 M.SalesInvoice.status != "cancelled"))
    if exclude_id is not None:
        q = q.filter(M.SalesInvoice.id != exclude_id)
    want = norm(number)
    return any(norm(n) == want for (n,) in q.all())
