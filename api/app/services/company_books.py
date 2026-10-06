"""A company's books, month by month: an ESTIMATE beside the accountant's
figures (decision 0068).

What the page computes, in PLN, by month:

* **Revenue** — the net of the company's issued sales invoices by issue date
  (`_sales_effect` holds the rule for each kind). An ADVANCE invoice counts
  for VAT, not for income: a received advance is not revenue for income tax
  until the delivery (art. 14 ust. 3 pkt 1 of the PIT act). A correction of
  an advance is an advance too. A SETTLEMENT invoice (ROZ) is the delivery: it
  counts the whole order, its positions at full value, so the advances reach
  revenue on its date. A correction counts its difference once, whoever wrote
  it (`invoicing.service.correction_difference`).
* **Costs** — the net of the supplier documents billed to the company, by
  document date, split by where the money went: stock bought, batch costs,
  project costs, prepared parts, company overhead (by category) and money not
  assigned yet. Excluded positions (reclaimable VAT, prepaid parts already in
  stock) and in-house transfers are no cost. A purchase of stock is a cost when
  bought, as in a KPIR, without the year-end stock count.
* **VAT** — the VAT of the sales invoices, advances included, minus the VAT on
  the supplier documents. A foreign purchase under reverse charge adds as much
  as it takes away and is left out. A purchase's VAT is in PLN as its invoice
  states it, in the first month the law allows the deduction
  (`purchase_vat_day`, decision 0084), not by the document date.
* **Income tax** — only when the company's tax form is stated, from the
  year-to-date figures: linear 19 %, the scale (12 % to 120 000 with the 3 600
  reduction, 32 % above), the lump sum on revenue, or CIT 9 % / 19 %. ZUS
  (the health contribution included, decision 0081) is not deducted.
* **Interest** — the late-payment interest the accountant's figures carry
  (`CompanyTaxEntry.interest`, decision 0081), summed by month. It is money
  paid and nothing else: never a cost (art. 23 ust. 1 pkt 18 of the PIT act,
  art. 16 ust. 1 of the CIT act) and never in a tax estimate.

A record the user keeps from the accountant (`accountant.kept_from_accountant`,
decision 0080) is in none of these figures: the accountant's tax cannot
include an invoice she never saw. Batch, project and stock costs still count
it; they do not read this module.

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
from .accountant import kept_from_accountant
from .invoicing import service as invoicing
from .invoicing.amounts import d2
from .run_actuals import OVERHEAD_CATEGORIES, document_json, header_ids, line_destination

TAX_FORMS = ("pit_linear", "pit_scale", "lump", "cit_9", "cit_19")
#: What a company is decides which tax its income pays, and so which forms fit.
LEGAL_FORMS = {"sole_trader": ("pit", ("pit_linear", "pit_scale", "lump")),
               "company": ("cit", ("cit_9", "cit_19"))}


def income_tax(company: M.Company) -> str:
    """`pit` or `cit`: from the legal form, else from a stated CIT form."""
    if company.legal_form in LEGAL_FORMS:
        return LEGAL_FORMS[company.legal_form][0]
    return "cit" if (company.tax_form or "").startswith("cit") else "pit"


def check_form(name: str, legal_form: str, form: str) -> None:
    """Refuse a tax form the company's legal form cannot have."""
    from fastapi import HTTPException

    fits = LEGAL_FORMS.get(legal_form or "", (None, TAX_FORMS))[1]
    if form and form not in fits:
        raise HTTPException(422, f"{name} is a {legal_form.replace('_', ' ')}: its tax form is one of {', '.join(fits)}")
ENTRY_KINDS = ("vat", "pit", "cit", "zus", "other")    # health is ZUS (decision 0081)
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


def _scale_tax(year: int, inc: Decimal) -> Decimal:
    """The PIT scale (zasady ogólne) on a year's income, by that year's rules.
    2021 and before: 17 % up to 85 528 with the falling reducing amount, 32 %
    above. 2022 on: 12 % with a 30 000 free amount, 32 % above 120 000 (the
    annual rule; 2022's first-half advances used 17 %, its return 12 %)."""
    inc = max(inc, Decimal(0))
    if year <= 2021:
        if inc <= 8000:
            reduce = Decimal("1360")
        elif inc <= 13000:
            reduce = Decimal("1360") - Decimal("834.88") * (inc - 8000) / 5000
        elif inc <= 85528:
            reduce = Decimal("525.12")
        elif inc <= 127000:
            reduce = Decimal("525.12") - Decimal("525.12") * (inc - 85528) / Decimal("41472")
        else:
            reduce = Decimal(0)
        if inc <= 85528:
            return d2(max(inc * Decimal("0.17") - reduce, Decimal(0)))
        return d2(Decimal("14539.76") - reduce + (inc - 85528) * Decimal("0.32"))
    if inc <= 30000:
        return Decimal("0.00")
    low = min(inc, Decimal(120000)) * Decimal("0.12") - Decimal(3600)
    high = max(inc - Decimal(120000), Decimal(0)) * Decimal("0.32")
    return d2(max(low, Decimal(0)) + high)


def _income_tax(form: str, lump_rate: Decimal, ytd_income: Decimal, ytd_revenue: Decimal,
                year: int = 2026, rate: Decimal | None = None) -> Decimal | None:
    """The year-to-date income tax under a form. `rate` (percent) replaces the
    statutory computation: of revenue for `lump`, of income for every other
    form (decision 0078)."""
    if form and rate is not None:
        base = ytd_revenue if form == "lump" else ytd_income
        return d2(max(base, Decimal(0)) * rate / 100)
    if form == "pit_linear":
        return d2(max(ytd_income, Decimal(0)) * Decimal("0.19"))
    if form == "pit_scale":
        return _scale_tax(year, ytd_income)
    if form == "lump":
        return d2(max(ytd_revenue, Decimal(0)) * lump_rate / 100)
    if form in ("cit_9", "cit_19"):
        rate = Decimal("0.09") if form == "cit_9" else Decimal("0.19")
        return d2(max(ytd_income, Decimal(0)) * rate)
    return None


def book_date(inv: M.SalesInvoice) -> str:
    """The day a sales document enters the books: the day of the delivery or
    service (`sale_date`, "data wykonania usługi"), or the issue date when the
    invoice was issued before it, as the tax point is (art. 14 ust. 1c PIT,
    art. 19a VAT). An invoice for April issued on 5 May is April's. A
    correction counts on its issue date: its sale date is the corrected
    invoice's."""
    if inv.kind == "correction" or not inv.sale_date:
        return inv.issue_date or ""
    return min(inv.sale_date[:10], (inv.issue_date or inv.sale_date)[:10])


def _sales_effect(db: Session, inv: M.SalesInvoice) -> dict[str, Decimal]:
    """What one issued sales document adds to the books, in its currency:
    `revenue` (net income), `advance` (net advances received) and `vat`.

    * VAT invoice: its net is revenue, its VAT is VAT.
    * Advance: the ADVANCE (`invoicing.service.advance_amounts`, never the
      order it is paid against) is an advance, its VAT is VAT.
    * Final advance ("zaliczkowa końcowa", `invoicing.is_final_advance`): the
      order was paid in full by advances and no settlement follows, so it is
      the delivery. Revenue is the whole order (`invoicing.order_net`), the
      VAT is its own advance's VAT, and the earlier advances reach revenue
      here, as they would at a settlement.
    * Correction: its difference (`correction_difference`) — of an advance it
      is an advance, otherwise revenue; a correction that changed text only
      adds nothing.
    * Settlement (ROZ): the delivery. Revenue is the whole order: FA(3) lists
      the positions at full value and states in P_13_x only what is left after
      the advances. The VAT is the VAT it states, the part the advances did
      not carry.
    """
    zero = Decimal(0)
    if inv.kind == "advance":
        a = invoicing.advance_amounts(inv)
        if invoicing.is_final_advance(inv):
            return {"revenue": invoicing.order_net(inv), "advance": zero, "vat": Decimal(str(a.get("vat") or 0))}
        return {"revenue": zero, "advance": Decimal(str(a.get("net") or 0)), "vat": Decimal(str(a.get("vat") or 0))}
    if inv.kind == "correction":
        d = invoicing.correction_difference(inv)
        net, vat = Decimal(d["net"]), Decimal(d["vat"])
        if invoicing.corrects_advance(db, inv):
            return {"revenue": zero, "advance": net, "vat": vat}
        return {"revenue": net, "advance": zero, "vat": vat}
    if inv.kind == "settlement":
        rows = [p for p in (inv.body or {}).get("lines") or [] if not p.get("before")]
        if rows:
            full = sum((Decimal(str(p.get("net") or 0)) for p in rows), zero)
            return {"revenue": full, "advance": zero, "vat": Decimal(str(inv.vat_total or 0))}
    return {"revenue": Decimal(str(inv.net_total or 0)), "advance": zero, "vat": Decimal(str(inv.vat_total or 0))}


def quarter_of(month: str) -> str:
    """'2024-05' -> '2024-Q2'."""
    return f"{month[:4]}-Q{(int(month[5:7]) - 1) // 3 + 1}"


def tax_periods(db: Session, company_id: int) -> list[M.CompanyTaxPeriod]:
    return (db.query(M.CompanyTaxPeriod).filter_by(company_id=company_id)
            .order_by(M.CompanyTaxPeriod.from_quarter).all())


def tax_setting(periods: list[M.CompanyTaxPeriod], month: str, company: M.Company) -> tuple[str, Decimal | None]:
    """The form (and the effective rate, if one is set) a month is taxed under:
    the last period that starts at or before its quarter, else the company's
    one `tax_form` (decision 0078)."""
    q = quarter_of(month)
    row = None
    for p in periods:
        if p.from_quarter <= q:
            row = p
    if row is None:
        return company.tax_form or "", None
    return row.form, (Decimal(str(row.rate)) if row.rate is not None else None)


def set_tax_period(db: Session, company_id: int, *, from_quarter: str, form: str, rate=None, note: str = "",
                   actor: str = "") -> M.CompanyTaxPeriod:
    from fastapi import HTTPException
    import re

    company = C.get(db, company_id)
    if not re.fullmatch(r"\d{4}-Q[1-4]", from_quarter or ""):
        raise HTTPException(422, "from_quarter is YYYY-Qn, for example 2024-Q1")
    if form not in TAX_FORMS:
        raise HTTPException(422, f"form is one of {', '.join(TAX_FORMS)}")
    check_form(company.name, company.legal_form or "", form)
    if rate is not None and not (0 <= float(rate) <= 100):
        raise HTTPException(422, "rate is a percentage from 0 to 100")
    row = db.query(M.CompanyTaxPeriod).filter_by(company_id=company_id, from_quarter=from_quarter).first()
    if row is None:
        row = M.CompanyTaxPeriod(company_id=company_id, from_quarter=from_quarter)
        db.add(row)
    row.form, row.rate, row.note, row.entered_by = form, (Decimal(str(rate)) if rate is not None else None), \
        (note or "")[:500], actor[:100]
    db.flush()
    return row


def tax_period_json(p: M.CompanyTaxPeriod) -> dict:
    return {"id": p.id, "from_quarter": p.from_quarter, "form": p.form,
            "rate": str(p.rate) if p.rate is not None else None, "note": p.note, "entered_by": p.entered_by}


def purchase_vat_day(doc: M.RunCostDocument) -> str:
    """The first day a purchase's VAT can be deducted (decision 0084): the
    period of the supplier's tax point, but not before the period the buyer
    received the invoice (art. 86 ust. 10 and 10b pkt 1 of the VAT act). The
    tax point is read as the sale date, else the issue date; the receipt as
    `received_date` (for a KSeF invoice, the day KSeF numbered it), else the
    issue date. The law lets a deduction wait three more months (art. 86 ust.
    11), so the accountant's figure can be later; it is the one that counts."""
    issued = (doc.doc_date or "")[:10]
    return max((doc.sale_date or issued)[:10], (doc.received_date or issued)[:10])


def purchase_vat_pln(doc: M.RunCostDocument) -> Decimal | None:
    """A purchase's VAT in PLN: `tax_amount` on a PLN document, the VAT in PLN
    the invoice states (`tax_amount_pln`) on one in another currency. None
    when the document states none."""
    if (doc.currency or "PLN").upper() == "PLN":
        return Decimal(str(doc.tax_amount)) if doc.tax_amount else None
    return Decimal(doc.tax_amount_pln) if doc.tax_amount_pln is not None else None


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
                        M.SalesInvoice.kind != "proforma",
                        M.SalesInvoice.issue_date.like(f"{year}-%") | M.SalesInvoice.sale_date.like(f"{year}-%"))
                .all()):
        day = book_date(inv)
        mo = months.get(day[:7])
        if mo is None or kept_from_accountant(inv):
            continue
        eff = _sales_effect(db, inv)
        mo["revenue_net"] += pln(eff["revenue"], inv.currency, day)
        mo["advances_net"] += pln(eff["advance"], inv.currency, day)
        mo["sales_vat"] += pln(eff["vat"], inv.currency, day)

    hdrs = header_ids(db)
    for doc in (db.query(M.RunCostDocument)
                .filter(M.RunCostDocument.company_id == company.id,
                        M.RunCostDocument.doc_type.notin_(("proforma", "transfer")),
                        M.RunCostDocument.doc_date.like(f"{year}-%")).all()):
        mo = months.get((doc.doc_date or "")[:7])
        if mo is None or kept_from_accountant(doc):
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

    # Purchase VAT has its own month, which can be after the document's
    # (decision 0084), so a document of last year can land in this one.
    for doc in (db.query(M.RunCostDocument)
                .filter(M.RunCostDocument.company_id == company.id,
                        M.RunCostDocument.doc_type.notin_(("proforma", "transfer")),
                        M.RunCostDocument.doc_date >= f"{year - 1}-01-01",
                        M.RunCostDocument.doc_date <= f"{year}-12-31").all()):
        vat = purchase_vat_pln(doc)
        mo = months.get(purchase_vat_day(doc)[:7])
        if vat is None or mo is None or kept_from_accountant(doc):
            continue
        mo["purchase_vat"] += vat

    entries: dict[str, dict] = defaultdict(dict)
    rows = (db.query(M.CompanyTaxEntry)
            .filter(M.CompanyTaxEntry.company_id == company.id, M.CompanyTaxEntry.period.like(f"{year}-%")).all())
    files: dict[int, int] = defaultdict(int)      # the accountant's notices filed with an entry (decision 0077)
    for f in (db.query(M.RecordFile.owner_id)
              .filter(M.RecordFile.owner_kind == "tax_entry", M.RecordFile.owner_id.in_([e.id for e in rows] or [0]))):
        files[f.owner_id] += 1
    interest: dict[str, Decimal] = defaultdict(Decimal)
    for e in rows:
        entries[e.period][e.kind] = {"id": e.id, "amount": str(e.amount), "interest": str(d2(e.interest or 0)),
                                     "status": e.status, "due_date": e.due_date, "paid_date": e.paid_date,
                                     "note": e.note, "files": files.get(e.id, 0)}
        interest[e.period] += Decimal(e.interest or 0)

    periods = tax_periods(db, company.id)
    out_months, ytd_inc, ytd_rev, prev_tax = [], Decimal(0), Decimal(0), Decimal(0)
    for key in sorted(months):
        mo = months[key]
        costs = sum(mo["costs"].values(), Decimal(0))
        income = mo["revenue_net"] - costs
        ytd_inc += income
        ytd_rev += mo["revenue_net"]
        form, rate = tax_setting(periods, key, company)
        ytd_tax = _income_tax(form, Decimal(str(company.lump_rate or 0)), ytd_inc, ytd_rev, year, rate)
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
            "tax_form": form, "tax_rate": None if rate is None else str(rate),
            "accountant": entries.get(key, {}),
            "interest": str(d2(interest.get(key, Decimal(0)))),
        })

    def total(field: str) -> str:
        return str(d2(sum((Decimal(m[field]) for m in out_months), Decimal(0))))

    return {"company_id": company.id, "company": company.name, "year": year,
            "tax_form": company.tax_form or "", "lump_rate": str(company.lump_rate or 0),
            "legal_form": company.legal_form or "", "income_tax": income_tax(company),
            "tax_periods": [tax_period_json(p) for p in periods],
            "months": out_months,
            "totals": {f: total(f) for f in ("revenue_net", "advances_net", "costs_net", "income", "sales_vat",
                                             "purchase_vat", "vat_estimate", "interest")},
            "overhead": {k: str(d2(v)) for k, v in sorted(overhead.items(), key=lambda kv: -kv[1])},
            "overhead_labels": OVERHEAD_CATEGORIES}


def set_entry(db: Session, company_id: int, *, period: str, kind: str, amount, status: str = "final",
              due_date: str = "", paid_date: str = "", note: str = "", interest=0,
              actor: str = "") -> M.CompanyTaxEntry:
    from fastapi import HTTPException

    C.get(db, company_id)
    if kind not in ENTRY_KINDS:
        raise HTTPException(422, f"kind is one of {', '.join(ENTRY_KINDS)}")
    if status not in ("estimated", "final"):
        raise HTTPException(422, "status is estimated or final")
    if Decimal(str(interest or 0)) < 0:
        raise HTTPException(422, "interest is what was paid on top of the tax: zero or more")
    import re

    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", period or ""):
        raise HTTPException(422, "period is YYYY-MM")
    row = db.query(M.CompanyTaxEntry).filter_by(company_id=company_id, period=period, kind=kind).first()
    if row is None:
        row = M.CompanyTaxEntry(company_id=company_id, period=period, kind=kind)
        db.add(row)
    row.amount, row.status, row.interest = d2(amount), status, d2(interest or 0)
    row.due_date, row.paid_date, row.note = due_date[:10], paid_date[:10], note[:500]
    row.entered_by = actor[:100]
    db.flush()
    return row
