"""KSeF read-out (decision 0067).

The tokens and the sync are admin work: a token reads every invoice of a
company, and a sync spends KSeF's hourly query limit. Reading the inbox and
importing or skipping a purchase is invoice work, open to the company's users.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import companies as company_svc
from ..services import storage
from ..services.ksef import sync as svc
from .users import require_admin
from .util import acting_name, audit

router = APIRouter(prefix="/api/ksef", tags=["ksef"])


@router.get("/status")
def status(db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """Per company: whether a token is set (never the token) and how the syncs went."""
    return svc.status(db)


class TokenIn(BaseModel):
    token: str = Field(default="", max_length=4000)


@router.put("/credentials/{company_id}")
def put_token(company_id: int, body: TokenIn, db: Session = Depends(get_db),
              admin: M.User = Depends(require_admin)):
    """Set, replace or (empty) clear a company's KSeF token. Write-only."""
    svc.set_token(db, company_id, body.token, acting_name())
    audit(db, "ksef.token", "company", company_id, {"set": bool(body.token.strip())})
    db.commit()
    return next(s for s in svc.status(db) if s["company_id"] == company_id)


class SyncIn(BaseModel):
    company_id: int
    sides: list[str] = ["sales", "purchase"]
    since: str | None = None


@router.post("/sync")
def run_sync(body: SyncIn, db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """Read a company's invoices from KSeF into the inbox. Writes no money."""
    bad = [s for s in body.sides if s not in ("sales", "purchase")]
    if bad:
        raise HTTPException(422, f"sides are sales and purchase, not {bad}")
    try:
        res = svc.sync(db, body.company_id, sides=tuple(body.sides), since=body.since)
    except HTTPException as e:
        if e.status_code == 502:
            # KSeF failed part-way: keep what was fetched before it, and the
            # error (`last_error`), instead of rolling both back.
            audit(db, "ksef.sync", "company", body.company_id, {"error": str(e.detail)[:300]})
            db.commit()
        raise
    audit(db, "ksef.sync", "company", body.company_id,
          {k: res[k] for k in ("fetched", "downloaded", "linked", "recorded", "limit")})
    db.commit()
    return res


@router.post("/fill-documents")
def fill_documents(dry_run: bool = True, db: Session = Depends(get_db), admin: M.User = Depends(require_admin)):
    """Give the supplier documents imported from KSeF before decision 0084
    the invoice's tax data, from the XML each one stored. Dry run by default;
    an archive-wide job, so admin work. Runs again harmlessly."""
    res = svc.fill_documents(db)
    if dry_run:
        db.rollback()
    else:
        audit(db, "ksef.fill_documents", "run_cost_document", 0,
              {"checked": res["checked"], "filled": len(res["filled"]), "no_xml": len(res["no_xml"]),
               "failed": len(res["failed"])})
        db.commit()
    return {"dry_run": dry_run, **res}


@router.get("/inbox")
def inbox(side: str = "", status: str = "", request: Request = None, db: Session = Depends(get_db)):
    """The invoices KSeF holds for the companies in the header scope."""
    scope = company_svc.scope_ids(db, request)
    q = db.query(M.KsefInvoice).filter(M.KsefInvoice.company_id.in_(scope))
    if side:
        q = q.filter(M.KsefInvoice.side == side)
    if status:
        q = q.filter(M.KsefInvoice.status == status)
    return [svc.inbox_json(r) for r in q.order_by(M.KsefInvoice.issue_date.desc(), M.KsefInvoice.id.desc()).all()]


def _row(db: Session, ksef_id: int) -> M.KsefInvoice:
    r = db.get(M.KsefInvoice, ksef_id)
    if r is None:
        raise HTTPException(404, "not in the KSeF inbox")
    return r


@router.get("/inbox/{ksef_id}/xml")
def inbox_xml(ksef_id: int, db: Session = Depends(get_db)):
    r = _row(db, ksef_id)
    data = storage.get_bytes(r.xml_key) if r.xml_key else None
    if not data:
        raise HTTPException(404, "the XML is not downloaded yet")
    return Response(data, media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="KSeF-{r.ksef_number}.xml"'})


@router.post("/inbox/{ksef_id}/import")
def import_purchase(ksef_id: int, force: bool = False, document_id: int | None = None,
                    db: Session = Depends(get_db)):
    """A purchase as a supplier document; its positions wait for destinations.

    A document that already holds it is linked (409, and the link is kept). A
    document typed by hand that may be it answers 409 with the candidates:
    `document_id` links the purchase to one, `force` imports it anyway."""
    r = _row(db, ksef_id)
    try:
        doc = svc.import_purchase(db, r, actor=acting_name(), force=force, link_to=document_id)
    except svc.Linked:
        audit(db, "ksef.link", "ksef_invoice", r.id, {"ksef_number": r.ksef_number, "document_id": r.document_id})
        db.commit()
        raise
    if document_id is not None:
        audit(db, "ksef.link", "ksef_invoice", r.id, {"ksef_number": r.ksef_number, "document_id": doc.id})
    else:
        audit(db, "ksef.import", "run_cost_document", doc.id,
              {"ksef_number": r.ksef_number, "supplier": doc.supplier, "doc_number": doc.doc_number,
               "forced": force})
    db.commit()
    return {"document_id": doc.id, **svc.inbox_json(r)}


class SkipIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/inbox/{ksef_id}/skip")
def skip(ksef_id: int, body: SkipIn, db: Session = Depends(get_db)):
    """A purchase nobody imports, with the reason. A sales invoice is never
    skipped: the numbering counts the numbers KSeF holds, and a skipped row
    would give its number out again."""
    r = _row(db, ksef_id)
    if r.side != "purchase":
        raise HTTPException(422, "only a purchase is skipped; a sales invoice in KSeF stays in the series")
    if r.status == "imported" and (r.document_id is None or db.get(M.RunCostDocument, r.document_id) is None):
        r.status, r.document_id = "new", None     # its document was deleted
    if r.status in ("imported", "linked"):
        raise HTTPException(409, f"{r.ksef_number} is already {r.status}")
    r.status, r.note = "skipped", body.reason
    audit(db, "ksef.skip", "ksef_invoice", r.id, {"ksef_number": r.ksef_number, "reason": body.reason})
    db.commit()
    return svc.inbox_json(r)
