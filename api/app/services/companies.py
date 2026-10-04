"""Two companies in one platform (decision 0063).

7Sigma (a sole proprietorship) and 9SIGMA (a limited company, from
2024-07-22) are both the user's. A PROJECT belongs to one company over time:
`ProjectOwnership` rows, each from a date, and the owner on a day is the row
with the latest `from_date` on or before it. A move adds a row and edits none,
so the books can always answer "who owned this project when that invoice was
issued".

A BATCH, a SALES ORDER and a SUPPLIER INVOICE each name their own company.
History does not follow one rule: a batch made before 9Sigma existed belongs to
7Sigma whoever owns its project now, and an order belongs to the company that
sold it. A batch takes its project's owner on its date when it is created, and
keeps it.

Visibility: a user sees the companies they belong to (`UserCompany`); an admin
sees every company. The company switcher in the web header narrows a view to
one of them, or shows all (`X-Company` header, `scope_ids`).
"""
from __future__ import annotations

from datetime import date

from fastapi import HTTPException, Request
from sqlalchemy import event
from sqlalchemy.orm import Session

from .. import models as M


def _today() -> str:
    return date.today().isoformat()


def company_json(c: M.Company, *, full: bool = False) -> dict:
    out = {"id": c.id, "key": c.key, "name": c.name, "nip": c.nip,
           "issues_invoices": bool(c.issues_invoices)}
    if full:
        out.update({
            "legal_name": c.legal_name, "address_l1": c.address_l1, "address_l2": c.address_l2,
            "country": c.country, "email": c.email, "place_of_issue": c.place_of_issue,
            "issuer_name": c.issuer_name, "bank_name": c.bank_name, "bank_account": c.bank_account,
            "swift": c.swift, "payment_terms_days": c.payment_terms_days, "started_on": c.started_on,
        })
    return out


def all_companies(db: Session) -> list[M.Company]:
    return db.query(M.Company).order_by(M.Company.id).all()


def by_key(db: Session, key: str) -> M.Company:
    c = db.query(M.Company).filter_by(key=key).first()
    if c is None:
        raise HTTPException(404, f"no company {key!r}")
    return c


def get(db: Session, company_id: int | None) -> M.Company:
    c = db.get(M.Company, company_id) if company_id else None
    if c is None:
        raise HTTPException(404, "no such company")
    return c


# ================================================================ ownership

def ownership(db: Session, project_id: int) -> list[M.ProjectOwnership]:
    return (db.query(M.ProjectOwnership).filter_by(project_id=project_id)
            .order_by(M.ProjectOwnership.from_date).all())


def owner_on(db: Session, project_id: int, on: str | None = None) -> M.Company | None:
    """The company that owned the project on `on` (ISO date; default today).
    Before the first period, the first owner answers: a project's history
    starts with whoever created it."""
    rows = ownership(db, project_id)
    if not rows:
        return None
    day = (on or _today())[:10]
    pick = rows[0]
    for r in rows:
        if r.from_date <= day:
            pick = r
    return db.get(M.Company, pick.company_id)


def ownership_json(db: Session, project_id: int) -> list[dict]:
    names = {c.id: c.name for c in all_companies(db)}
    rows = ownership(db, project_id)
    out = []
    for i, r in enumerate(rows):
        out.append({"id": r.id, "company_id": r.company_id, "company": names.get(r.company_id),
                    "from_date": r.from_date,
                    "to_date": rows[i + 1].from_date if i + 1 < len(rows) else None,
                    "note": r.note, "created_by": r.created_by})
    return out


def move_project(db: Session, project: M.Project, company: M.Company, from_date: str, *,
                 note: str = "", actor: str = "") -> M.ProjectOwnership:
    """The project belongs to `company` from `from_date`. A new period only:
    it starts after the current one, and a company cannot own anything from
    before it existed."""
    day = (from_date or "")[:10]
    try:
        date.fromisoformat(day)
    except ValueError as e:
        raise HTTPException(422, "from_date must be an ISO date (YYYY-MM-DD)") from e
    if company.started_on and day < company.started_on:
        raise HTTPException(422, f"{company.name} exists from {company.started_on}, not {day}")
    rows = ownership(db, project.id)
    if rows and day <= rows[-1].from_date:
        raise HTTPException(409, f"{project.name} already has an ownership period from "
                                 f"{rows[-1].from_date}; a move starts after it")
    if rows and rows[-1].company_id == company.id:
        raise HTTPException(409, f"{project.name} already belongs to {company.name}")
    r = M.ProjectOwnership(project_id=project.id, company_id=company.id, from_date=day,
                           note=(note or "")[:500], created_by=actor[:100])
    db.add(r)
    db.flush()
    return r


def default_run_company(db: Session, run: M.ProductionRun) -> M.Company | None:
    """The company a new batch belongs to: its project's owner on its date."""
    return owner_on(db, run.project_id, run.run_date or _today())


# =============================================================== visibility

def visible_ids(db: Session, user: M.User | None) -> list[int]:
    """The companies a user may see: their memberships, or every company for
    an admin (and for the dev posture with no signed-in user)."""
    if user is None or getattr(user, "role", "") == "admin":
        return [c.id for c in all_companies(db)]
    return [cid for (cid,) in db.query(M.UserCompany.company_id).filter_by(user_id=user.id).all()]


def scope_ids(db: Session, request: Request | None) -> list[int]:
    """The companies a view shows: the one the header switcher selected
    (`X-Company: <id>`), or all the user may see (`all`, or no header). A
    company the user may not see is never in it."""
    user = getattr(request.state, "user", None) if request is not None else None
    allowed = visible_ids(db, user)
    raw = (request.headers.get("x-company") if request is not None else "") or "all"
    if raw == "all":
        return allowed
    try:
        cid = int(raw)
    except ValueError:
        return allowed
    return [cid] if cid in allowed else allowed


def narrows(db: Session, scope: list[int]) -> bool:
    """Whether a scope leaves any company out, so a list must be filtered."""
    return set(scope) != {c.id for c in all_companies(db)}


def projects_owned_by(db: Session, scope: list[int], on: str | None = None) -> set[int]:
    """The projects whose owner on `on` (default today) is in the scope."""
    out = set()
    for p in db.query(M.Project.id).all():
        owner = owner_on(db, p[0], on)
        if owner is not None and owner.id in scope:
            out.add(p[0])
    return out


def set_memberships(db: Session, user: M.User, company_ids: list[int]) -> list[int]:
    known = {c.id for c in all_companies(db)}
    bad = [cid for cid in company_ids if cid not in known]
    if bad:
        raise HTTPException(404, f"no company {bad[0]}")
    db.query(M.UserCompany).filter_by(user_id=user.id).delete(synchronize_session=False)
    for cid in sorted(set(company_ids)):
        db.add(M.UserCompany(user_id=user.id, company_id=cid))
    db.flush()
    return sorted(set(company_ids))


def memberships(db: Session, user: M.User) -> list[int]:
    return sorted(cid for (cid,) in db.query(M.UserCompany.company_id).filter_by(user_id=user.id).all())


# ================================================================= backfill

#: The user's assignment of 2026-10-04: every dongle and Aqua project belongs to
#: 9Sigma, every other project to 7Sigma. The dongle V2 and the Aqua were
#: 7Sigma's until 9Sigma existed (their prototypes and Batch 1 were made by
#: 7Sigma), and 9Sigma's from its first day.
NINE_SIGMA_PROJECTS = ("CE_Dongle_V2", "CE_Aqua_V2", "CE_Dongle_V3")
MOVED_ON_9SIGMA_START = ("CE_Dongle_V2", "CE_Aqua_V2")


def _seller_of_order(db: Session, order: M.SalesOrder, companies: dict[str, M.Company]) -> M.Company | None:
    """The company that sold an order, read off its invoices: each invoice note
    starts with the issuing company ("7Sigma; …", "9Sigma; …")."""
    sellers = set()
    for inv in order.invoices:
        head = (inv.notes or "").split(";", 1)[0].strip().lower()
        if head in ("7sigma", "9sigma"):
            sellers.add(head)
    if len(sellers) == 1:
        return companies[sellers.pop()]
    return None


def backfill(db: Session, *, actor: str = "", dry_run: bool = True) -> dict:
    """Give the existing data its companies (decision 0063). Idempotent: rows
    that already have a company are left alone. Dry run by default."""
    companies = {c.key: c for c in all_companies(db)}
    s7, s9 = companies["7sigma"], companies["9sigma"]
    out: dict = {"dry_run": dry_run, "ownership": [], "runs": [], "orders": [], "memberships": [],
                 "unresolved": []}
    for p in db.query(M.Project).order_by(M.Project.id).all():
        if ownership(db, p.id):
            continue
        first = (p.created_at.date().isoformat() if p.created_at else _today())
        runs = [r.run_date for r in db.query(M.ProductionRun).filter_by(project_id=p.id).all() if r.run_date]
        start = min([first, *runs])
        if p.name in MOVED_ON_9SIGMA_START:
            plan = [(s7, start, "made by 7Sigma until 9Sigma existed (user, 2026-10-04)"),
                    (s9, s9.started_on, "9Sigma owns every dongle and Aqua project (user, 2026-10-04)")]
        elif p.name in NINE_SIGMA_PROJECTS:
            plan = [(s9, max(start, s9.started_on), "9Sigma owns every dongle and Aqua project (user, 2026-10-04)")]
        else:
            plan = [(s7, start, "every project that is not a dongle or an Aqua is 7Sigma's (user, 2026-10-04)")]
        for comp, day, why in plan:
            out["ownership"].append({"project": p.name, "company": comp.name, "from": day})
            if not dry_run:
                db.add(M.ProjectOwnership(project_id=p.id, company_id=comp.id, from_date=day, note=why,
                                          created_by=actor[:100]))
        if not dry_run:
            db.flush()

    # A batch: the company that sold its devices, where its devices' orders say
    # so with one voice; else its project's owner on its date.
    if not dry_run:
        db.flush()
    for r in db.query(M.ProductionRun).filter(M.ProductionRun.company_id.is_(None)).order_by(M.ProductionRun.id):
        sold_by = _seller_of_devices(db, r, companies)
        comp = sold_by or owner_on(db, r.project_id, r.run_date or None)
        if comp is None and dry_run:
            # The ownership rows are not written on a dry run: read the plan.
            comp = _planned_owner(out["ownership"], db.get(M.Project, r.project_id).name,
                                  r.run_date or _today(), companies)
        if comp is None:
            out["unresolved"].append({"run": r.label, "why": "no owner and no seller"})
            continue
        out["runs"].append({"run_id": r.id, "run": r.label, "date": r.run_date, "company": comp.name,
                            "evidence": "the company that sold its devices" if sold_by else
                            "its project's owner on its date"})
        if not dry_run:
            r.company_id = comp.id

    for o in db.query(M.SalesOrder).filter(M.SalesOrder.company_id.is_(None)).order_by(M.SalesOrder.id):
        comp = _seller_of_order(db, o, companies)
        evidence = "its invoices name the seller"
        if comp is None:
            proj = next((ln.project_id for ln in o.lines), None)
            comp = owner_on(db, proj, o.order_date or None) if proj else None
            if comp is None and dry_run and proj:
                comp = _planned_owner(out["ownership"], db.get(M.Project, proj).name,
                                      o.order_date or _today(), companies)
            evidence = "its project's owner on its date"
        if comp is None:
            out["unresolved"].append({"order_id": o.id, "why": "no invoice names the seller and no project"})
            continue
        out["orders"].append({"order_id": o.id, "ref": o.order_ref, "company": comp.name, "evidence": evidence})
        if not dry_run:
            o.company_id = comp.id

    # Nobody loses sight of anything: every user starts in both companies, and
    # an admin narrows it (decision 0063, rollout).
    for u in db.query(M.User).all():
        if memberships(db, u):
            continue
        out["memberships"].append({"user": u.username, "companies": [s7.name, s9.name]})
        if not dry_run:
            set_memberships(db, u, [s7.id, s9.id])
    if not dry_run:
        db.flush()
    return out


def _planned_owner(plan: list[dict], project: str, day: str, companies: dict[str, M.Company]) -> M.Company | None:
    rows = sorted((r for r in plan if r["project"] == project), key=lambda r: r["from"])
    if not rows:
        return None
    pick = rows[0]
    for r in rows:
        if r["from"] <= day[:10]:
            pick = r
    return next(c for c in companies.values() if c.name == pick["company"])


def _seller_of_devices(db: Session, run: M.ProductionRun, companies: dict[str, M.Company]) -> M.Company | None:
    """The company whose orders shipped this batch's devices, when one company
    shipped more than nine in ten of them."""
    from collections import Counter

    # One row per shipped device (a column query is not de-duplicated).
    rows = (db.query(M.SalesOrderLine.order_id, M.DeviceUnit.id)
            .join(M.DeviceEvent, M.DeviceEvent.order_line_id == M.SalesOrderLine.id)
            .join(M.DeviceUnit, M.DeviceUnit.id == M.DeviceEvent.device_id)
            .filter(M.DeviceUnit.production_run_id == run.id, M.DeviceEvent.kind == "shipped")
            .all())
    sellers: dict[int, M.Company | None] = {}
    votes: Counter = Counter()
    for order_id, _dev in rows:
        if order_id not in sellers:
            sellers[order_id] = _seller_of_order(db, db.get(M.SalesOrder, order_id), companies)
        if sellers[order_id] is not None:
            votes[sellers[order_id].key] += 1
    if not votes:
        return None
    key, n = votes.most_common(1)[0]
    return companies[key] if n >= 0.9 * sum(votes.values()) else None


# ===================================================== stock per company (0064)

def transformation_company(db: Session, t: M.ProcessTransformation | None) -> int | None:
    """The company a process transformation worked for: the batch it was done
    for, else its project's owner on the day."""
    if t is None:
        return None
    if t.production_run_id:
        run = db.get(M.ProductionRun, t.production_run_id)
        if run is not None and run.company_id:
            return run.company_id
    owner = owner_on(db, t.project_id, t.made_at or None)
    return owner.id if owner else None


def stock_company_for(db: Session, row) -> int | None:
    """The company whose stock a draw or an adjustment moves, from what it is
    linked to. None when nothing says (an uncharged draw, a free-standing
    adjustment): the writer, or the backfill, must name it."""
    def run_company(run_id):
        run = db.get(M.ProductionRun, run_id) if run_id else None
        return run.company_id if run is not None else None

    if isinstance(row, M.ComponentConsumption):
        if row.run_id:
            return run_company(row.run_id)
        if row.step_run_id:
            sr = db.get(M.StepRun, row.step_run_id)
            return run_company(sr.run_id) if sr is not None else None
        if row.transformation_id:
            return transformation_company(db, db.get(M.ProcessTransformation, row.transformation_id))
        return None
    if isinstance(row, M.ComponentStockAdjustment):
        if row.charge_run_id:
            return run_company(row.charge_run_id)
        if row.transformation_id:
            return transformation_company(db, db.get(M.ProcessTransformation, row.transformation_id))
        if row.project_id:
            owner = owner_on(db, row.project_id, row.adjusted_at or None)
            return owner.id if owner else None
    return None


@event.listens_for(Session, "before_flush")
def stamp_stock(session: Session, flush_context, instances) -> None:
    """Every NEW draw and adjustment gets its company, whichever of the eleven
    writers made it. A writer that knows better sets `company_id` itself and is
    left alone."""
    for obj in list(session.new):
        if isinstance(obj, (M.ComponentConsumption, M.ComponentStockAdjustment)) \
                and obj.company_id is None:
            with session.no_autoflush:
                obj.company_id = stock_company_for(session, obj)


def stock_without_company(db: Session) -> dict[str, int]:
    """Live stock records that name no company. `stock_per_company` cannot be
    turned on while any remain: a record with no company belongs to no stock."""
    from . import run_actuals as RA

    docs = (db.query(M.RunCostDocument.id)
            .filter(M.RunCostDocument.company_id.is_(None),
                    M.RunCostDocument.doc_type != "proforma").all())
    doc_ids = {d for (d,) in docs}
    pooled = 0
    if doc_ids:
        pooled = (db.query(M.RunCostLine.document_id)
                  .filter(M.RunCostLine.document_id.in_(doc_ids), RA.IS_STOCK,
                          M.RunCostLine.voided_at.is_(None)).distinct().count())
    draws = RA.live_consumption(db).filter(M.ComponentConsumption.company_id.is_(None)).count()
    adjs = (db.query(M.ComponentStockAdjustment)
            .filter(M.ComponentStockAdjustment.company_id.is_(None)).count())
    return {"documents with parts": pooled, "draws": draws, "adjustments": adjs}
