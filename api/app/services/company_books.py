"""A company's books, month by month: an ESTIMATE beside the accountant's
figures (decision 0068).

What the page computes, in PLN, by month:

* **Revenue** — the net of the company's issued sales invoices (VAT,
  corrections, settlements) by issue date. An ADVANCE invoice counts for VAT,
  not for income: a received advance is not revenue for income tax until the
  delivery (art. 14 ust. 3 pkt 1 of the PIT act).
* **Costs** — the net of the supplier documents billed to the company, by
  document date, split by where the money went: stock bought, batch costs,
  project costs, prepared parts, company overhead (by category) and money not
  assigned yet. Excluded positions (reclaimable VAT, prepaid parts already in
  stock) and in-house transfers are no cost. A purchase of stock is a cost when
  bought, as in a KPIR, without the year-end stock count.
* **VAT** — the VAT of the sales invoices, advances included, minus the VAT on
  the supplier documents. A foreign purchase under reverse charge adds as much
  as it takes away and is left out.
* **Income tax** — only when the company's tax form is stated, from the
  year-to-date figures: linear 19 %, the scale (12 % to 120 000 with the 3 600
  reduction, 32 % above), the lump sum on revenue, or CIT 9 % / 19 %. ZUS and
  the health contribution are not deducted.

Every figure here is an estimate. The accountant's numbers (`CompanyTaxEntry`)
are entered beside it, the way a batch has a planned and an actual cost.

Amounts in another currency are converted with the platform's rate history at
the document's own date (decision 2026-07-27: NBP, the invoice date).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy.orm import Session

from .. import models as M
from . import companies as C
from . import fx
from .invoicing.amounts import d2
from .run_actuals import OVERHEAD_CATEGORIES, document_json, header_ids, line_destination

TAX_FORMS = ("pit_linear", "pit_scale", "lump", "cit_9", "cit_19")
ENTRY_KINDS = ("vat", "pit", "cit", "zus", "health", "other")
COST_BUCKETS = ("stock", "batches", "projects", "prepared", "overhead", "unassigned")
_BUCKET = {"pool": "stock", "run": "batches", "project": "projects", "transformation": "prepared",
           "overhead": "overhead", "unassigned": "unassigned"}


def _day(iso: str) -> datetime:
    try:
        return datetime.fromisoformat((iso or "")[:10]).replace(tzinfo=UTC)
    except ValueError:
        return datetime.now(UTC)


class _Pln:
    """Converts to PLN with one rate table per date."""

    def __init__(self, db: Session):
        self.db = db
        self.cache: dict[str, dict] = {}

    def __call__(self, amount, currency: str, day: str, usd_rate: float | None = None) -> Decimal:
        cur = (currency or "PLN").upper()
        a = Decimal(str(amount or 0))
        if cur == "PLN" or not a:
            return a
        if day not in self.cache:
            self.cache[day] = fx.rates_at(self.db, _day(day))
        rates = self.cache[day]
        usd = a * Decimal(str(usd_rate)) if usd_rate else None
        if usd is None:
            value, _known = fx.convert(float(a), cur, "USD", rates)
            usd = Decimal(str(value))
        pln = rates.get("PLN")
        return usd / Decimal(str(pln)) if pln else usd


def _income_tax(form: str, lump_rate: Decimal, ytd_income: Decimal, ytd_revenue: Decimal) -> Decimal | None:
    if form == "pit_linear":
        return d2(max(ytd_income, Decimal(0)) * Decimal("0.19"))
    if form == "pit_scale":
        inc = max(ytd_income, Decimal(0))
        if inc <= 30000:
            return Decimal("0.00")
        low = min(inc, Decimal(120000)) * Decimal("0.12") - Decimal(3600)
        high = max(inc - Decimal(120000), Decimal(0)) * Decimal("0.32")
        return d2(max(low, Decimal(0)) + high)
    if form == "lump":
        return d2(max(ytd_revenue, Decimal(0)) * lump_rate / 100)
    if form in ("cit_9", "cit_19"):
        rate = Decimal("0.09") if form == "cit_9" else Decimal("0.19")
        return d2(max(ytd_income, Decimal(0)) * rate)
    return None


def year(db: Session, company_id: int, year: int) -> dict:
    company = C.get(db, company_id)
    pln = _Pln(db)
    months = {f"{year}-{m:02d}": {"month": f"{year}-{m:02d}", "revenue_net": Decimal(0),
                                  "advances_net": Decimal(0), "sales_vat": Decimal(0),
                                  "costs": {b: Decimal(0) for b in COST_BUCKETS},
                                  "purchase_vat": Decimal(0)}
              for m in range(1, 13)}
    overhead: dict[str, Decimal] = defaultdict(Decimal)

    for inv in (db.query(M.SalesInvoice)
                .filter(M.SalesInvoice.company_id == company.id, M.SalesInvoice.status.in_(("issued", "error")),
                        M.SalesInvoice.kind != "proforma", M.SalesInvoice.issue_date.like(f"{year}-%")).all()):
        mo = months.get(inv.issue_date[:7])
        if mo is None:
            continue
        net = pln(inv.net_total, inv.currency, inv.issue_date)
        vat = pln(inv.vat_total, inv.currency, inv.issue_date)
        mo["sales_vat"] += vat
        if inv.kind == "advance":
            mo["advances_net"] += net
        elif inv.kind == "correction" and (inv.body or {}).get("correction", {}).get("before_totals"):
            before = inv.body["correction"]["before_totals"]
            mo["revenue_net"] += net - pln(before.get("net") or 0, inv.currency, inv.issue_date)
            mo["sales_vat"] -= pln(before.get("vat") or 0, inv.currency, inv.issue_date)
        else:
            mo["revenue_net"] += net

    hdrs = header_ids(db)
    for doc in (db.query(M.RunCostDocument)
                .filter(M.RunCostDocument.company_id == company.id,
                        M.RunCostDocument.doc_type.notin_(("proforma", "transfer")),
                        M.RunCostDocument.doc_date.like(f"{year}-%")).all()):
        mo = months.get((doc.doc_date or "")[:7])
        if mo is None:
            continue
        a = document_json(doc, with_lines=False, db=db)["assignment"]
        for dest, bucket in _BUCKET.items():
            amount = (a.get(dest) or 0) + ((a.get("residual") or 0) if dest == "unassigned" else 0)
            if amount:
                mo["costs"][bucket] += pln(amount, doc.currency, doc.doc_date, doc.fx_rate_usd)
        if (a.get("overhead") or 0):
            for li in doc.lines:
                if li.voided_at is not None or li.id in hdrs:
                    continue
                if line_destination(li, doc)[0] == "overhead":
                    overhead[li.overhead_category or "other"] += pln(
                        (li.qty or 0) * (li.unit_price or 0), li.currency or doc.currency, doc.doc_date,
                        doc.fx_rate_usd)
        if doc.tax_amount and (doc.currency or "PLN").upper() == "PLN":
            mo["purchase_vat"] += Decimal(str(doc.tax_amount))

    entries: dict[str, dict] = defaultdict(dict)
    for e in (db.query(M.CompanyTaxEntry)
              .filter(M.CompanyTaxEntry.company_id == company.id,
                      M.CompanyTaxEntry.period.like(f"{year}-%")).all()):
        entries[e.period][e.kind] = {"id": e.id, "amount": str(e.amount), "status": e.status,
                                     "due_date": e.due_date, "paid_date": e.paid_date, "note": e.note}

    out_months, ytd_inc, ytd_rev, prev_tax = [], Decimal(0), Decimal(0), Decimal(0)
    for key in sorted(months):
        mo = months[key]
        costs = sum(mo["costs"].values(), Decimal(0))
        income = mo["revenue_net"] - costs
        ytd_inc += income
        ytd_rev += mo["revenue_net"]
        ytd_tax = _income_tax(company.tax_form or "", Decimal(str(company.lump_rate or 0)), ytd_inc, ytd_rev)
        tax = None if ytd_tax is None else d2(max(ytd_tax - prev_tax, Decimal(0)))
        if ytd_tax is not None:
            prev_tax = max(prev_tax, ytd_tax)
        out_months.append({
            "month": key, "revenue_net": str(d2(mo["revenue_net"])), "advances_net": str(d2(mo["advances_net"])),
            "costs_net": str(d2(costs)), "costs": {b: str(d2(v)) for b, v in mo["costs"].items()},
            "income": str(d2(income)), "sales_vat": str(d2(mo["sales_vat"])),
            "purchase_vat": str(d2(mo["purchase_vat"])),
            "vat_estimate": str(d2(mo["sales_vat"] - mo["purchase_vat"])),
            "income_tax_estimate": None if tax is None else str(tax),
            "accountant": entries.get(key, {}),
        })

    def total(field: str) -> str:
        return str(d2(sum((Decimal(m[field]) for m in out_months), Decimal(0))))

    return {"company_id": company.id, "company": company.name, "year": year,
            "tax_form": company.tax_form or "", "lump_rate": str(company.lump_rate or 0),
            "months": out_months,
            "totals": {f: total(f) for f in ("revenue_net", "advances_net", "costs_net", "income", "sales_vat",
                                             "purchase_vat", "vat_estimate")},
            "overhead": {k: str(d2(v)) for k, v in sorted(overhead.items(), key=lambda kv: -kv[1])},
            "overhead_labels": OVERHEAD_CATEGORIES}


def set_entry(db: Session, company_id: int, *, period: str, kind: str, amount, status: str = "final",
              due_date: str = "", paid_date: str = "", note: str = "", actor: str = "") -> M.CompanyTaxEntry:
    from fastapi import HTTPException

    C.get(db, company_id)
    if kind not in ENTRY_KINDS:
        raise HTTPException(422, f"kind is one of {', '.join(ENTRY_KINDS)}")
    if status not in ("estimated", "final"):
        raise HTTPException(422, "status is estimated or final")
    import re

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period or ""):
        raise HTTPException(422, "period is YYYY-MM")
    row = db.query(M.CompanyTaxEntry).filter_by(company_id=company_id, period=period, kind=kind).first()
    if row is None:
        row = M.CompanyTaxEntry(company_id=company_id, period=period, kind=kind)
        db.add(row)
    row.amount, row.status = d2(amount), status
    row.due_date, row.paid_date, row.note = due_date[:10], paid_date[:10], note[:500]
    row.entered_by = actor[:100]
    db.flush()
    return row
