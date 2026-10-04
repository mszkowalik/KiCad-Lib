"""Companies, memberships and project ownership (decision 0063).

Reading the companies is open to every signed-in user (they label every
list). Editing a company's data, moving a project to another company, and the
one-off backfill are admin work: they change what the books say.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import companies as svc
from .users import require_admin
from .util import acting_name, audit

router = APIRouter(prefix="/api", tags=["companies"])


@router.get("/companies")
def list_companies(request: Request, db: Session = Depends(get_db)):
    """The companies the caller may see, with their seller data for an admin."""
    user = getattr(request.state, "user", None)
    allowed = set(svc.visible_ids(db, user))
    admin = user is None or getattr(user, "role", "") == "admin"
    return [svc.company_json(c, full=admin) for c in svc.all_companies(db) if c.id in allowed]


class CompanyPatch(BaseModel):
    name: str | None = None
    legal_name: str | None = None
    address_l1: str | None = None
    address_l2: str | None = None
    country: str | None = None
    email: str | None = None
    place_of_issue: str | None = None
    issuer_name: str | None = None
    bank_name: str | None = None
    bank_account: str | None = None
    swift: str | None = None
    payment_terms_days: int | None = None
    # Decision 0066: whether the platform writes this company's invoices.
    issues_invoices: bool | None = None
    # Decision 0068: how the company page estimates income tax.
    tax_form: str | None = None
    lump_rate: float | None = None


@router.patch("/companies/{company_id}")
def update_company(company_id: int, body: CompanyPatch, db: Session = Depends(get_db),
                   admin: M.User = Depends(require_admin)):
    c = svc.get(db, company_id)
    changed = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    from ..services import company_books

    if "tax_form" in changed and changed["tax_form"] not in ("", *company_books.TAX_FORMS):
        raise HTTPException(422, f"tax_form is one of {', '.join(company_books.TAX_FORMS)} or empty")
    for k, v in changed.items():
        setattr(c, k, v.strip() if isinstance(v, str) else v)
    # The account number is not written to the audit row: the log is readable
    # wider than the company record.
    audit(db, "company.update", "company", c.id,
          {k: ("(changed)" if k == "bank_account" else v) for k, v in changed.items()})
    db.commit()
    return svc.company_json(c, full=True)


class BackfillIn(BaseModel):
    dry_run: bool = True


@router.post("/companies/backfill")
def backfill(body: BackfillIn, db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """Give existing projects, batches, orders and users their companies. Run
    once per deployment; dry run by default."""
    res = svc.backfill(db, actor=acting_name(), dry_run=body.dry_run)
    if body.dry_run:
        db.rollback()
    else:
        audit(db, "company.backfill", "company", None,
              {k: len(v) for k, v in res.items() if isinstance(v, list)})
        db.commit()
    return res


class StockBackfillIn(BaseModel):
    dry_run: bool = True
    # Ask JLC for the billing data of parts orders with no stored payload, through
    # the stored session (a read; user approval 2026-10-04).
    fetch_jlc: bool = False


@router.post("/companies/stock-backfill")
def stock_backfill(body: StockBackfillIn, db: Session = Depends(get_db),
                   admin: M.User = Depends(require_admin)):
    """Name the company of every purchase, draw and adjustment that has none
    (decision 0064). Dry run by default; the report lists what no evidence
    decides, for a person."""
    from ..services import company_backfill

    res = company_backfill.backfill(db, dry_run=body.dry_run, fetch_jlc=body.fetch_jlc,
                                    actor=acting_name())
    if body.dry_run:
        db.rollback()
    else:
        audit(db, "company.stock_backfill", "company", None, res["totals"])
        db.commit()
    res["still_without_company"] = svc.stock_without_company(db)
    return res


@router.get("/companies/{company_id}/books")
def books(company_id: int, year: int, db: Session = Depends(get_db)):
    """The company's month-by-month estimate beside the accountant's figures
    (decision 0068). The company gate keeps it to the company's members."""
    from ..services import company_books

    return company_books.year(db, company_id, year)


class TaxEntryIn(BaseModel):
    period: str
    kind: str
    amount: float
    status: str = "final"
    due_date: str = ""
    paid_date: str = ""
    note: str = Field(default="", max_length=500)


@router.put("/companies/{company_id}/tax-entries")
def put_tax_entry(company_id: int, body: TaxEntryIn, db: Session = Depends(get_db)):
    """The accountant's figure for one month and one tax, replacing the last."""
    from ..services import company_books

    row = company_books.set_entry(db, company_id, actor=acting_name(), **body.model_dump())
    audit(db, "company.tax_entry", "company_tax_entry", row.id,
          {"period": row.period, "kind": row.kind, "amount": str(row.amount), "status": row.status})
    db.commit()
    return {"id": row.id, "period": row.period, "kind": row.kind, "amount": str(row.amount), "status": row.status}


@router.get("/projects/{project_id}/ownership")
def project_ownership(project_id: int, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    return svc.ownership_json(db, project_id)


class MoveIn(BaseModel):
    company_id: int
    from_date: str
    note: str = Field(default="", max_length=500)


@router.post("/projects/{project_id}/ownership")
def move_project(project_id: int, body: MoveIn, db: Session = Depends(get_db),
                 admin: M.User = Depends(require_admin)):
    """The project belongs to another company from a date. Batches already made
    keep their company; new batches take the new owner."""
    p = db.get(M.Project, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    c = svc.get(db, body.company_id)
    r = svc.move_project(db, p, c, body.from_date, note=body.note, actor=acting_name())
    audit(db, "project.move", "project", p.id, {"company": c.name, "from_date": r.from_date, "note": body.note})
    db.commit()
    return svc.ownership_json(db, p.id)
