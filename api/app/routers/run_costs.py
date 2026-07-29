"""Post-factum production costs: supplier documents, actual cost lines,
component draws from the cost pool, and attrition.

Thin, per the api conventions: parse the request, call `services/run_actuals`,
shape the response. Every mutation writes an audit row WITH details — this is
the money path, so "something changed" is not good enough.
"""
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..models import utcnow
from ..services import cost_steps, nbp, run_actuals, storage
from .util import audit

router = APIRouter(prefix="/api", tags=["run-costs"])


# ------------------------------------------------------------------ schemas

class LineIn(BaseModel):
    kind: str = "part"
    basis: str = "per_run"
    label: str = ""
    qty: float = 1.0
    unit_price: float = 0.0
    currency: str = ""
    allocate: str = "none"
    component_id: int | None = None
    mpn: str = ""
    lcsc: str = ""
    description: str = ""
    plan_key: str = ""
    plan_kind: str = ""
    plan_ref: str = ""
    notes: str = ""
    run_id: int | None = None
    project_id: int | None = None
    position: int = 0
    ocr_confidence: float | None = None


class ChildIn(BaseModel):
    """One share of a split position. `kind`/`basis` default to the parent's.

    Amounts are ABSOLUTE. A percentage split is a frontend affordance — the
    browser turns "40%" into a number before it gets here (user decision
    2026-07-27), so a stored figure never has to be re-derived and cannot drift.
    """

    label: str = ""
    kind: str | None = None
    basis: str | None = None
    qty: float = 1.0
    unit_price: float = 0.0
    # Convenience for the common case "this share is worth X": sets qty=1.
    amount: float | None = None
    run_id: int | None = None
    project_id: int | None = None
    component_id: int | None = None
    mpn: str = ""
    lcsc: str = ""
    description: str = ""
    plan_key: str = ""
    plan_kind: str = ""
    plan_ref: str = ""
    notes: str = ""
    # "excluded" marks a share that is recorded but charged to nobody.
    allocate: str | None = None


class SplitIn(BaseModel):
    children: list[ChildIn]
    # Parts belong in the pool, which already splits them by consumption.
    # Splitting them per run by hand double counts, so it takes an explicit flag.
    allow_parts: bool = False
    replace: bool = False  # void the existing children first


class DocumentIn(BaseModel):
    project_id: int | None = None
    run_id: int | None = None
    doc_type: str = "invoice"
    supplier: str = ""
    doc_number: str = ""
    external_id: str = ""
    doc_date: str = ""
    paid_at: str = ""
    currency: str = "USD"
    fx_rate_usd: float | None = None
    total_amount: float | None = None
    tax_amount: float | None = None
    notes: str = ""
    attachment_id: int | None = None
    created_by: str = ""
    lines: list[LineIn] = []


class DocumentPatch(BaseModel):
    doc_type: str | None = None
    supplier: str | None = None
    doc_number: str | None = None
    external_id: str | None = None
    doc_date: str | None = None
    paid_at: str | None = None
    currency: str | None = None
    fx_rate_usd: float | None = None
    total_amount: float | None = None
    tax_amount: float | None = None
    notes: str | None = None
    run_id: int | None = None
    # A document becomes SHARED the moment a second product's lines land on it
    # (one JLC invoice carrying a Dongle panel and an Aqua panel), so its
    # project must be clearable — not only settable at creation.
    project_id: int | None = None
    attachment_id: int | None = None


class LinePatch(BaseModel):
    kind: str | None = None
    basis: str | None = None
    label: str | None = None
    qty: float | None = None
    unit_price: float | None = None
    currency: str | None = None
    allocate: str | None = None
    component_id: int | None = None
    mpn: str | None = None
    lcsc: str | None = None
    description: str | None = None
    plan_key: str | None = None
    plan_kind: str | None = None
    plan_ref: str | None = None
    notes: str | None = None
    run_id: int | None = None
    project_id: int | None = None


class ConsumptionIn(BaseModel):
    component_id: int | None = None
    mpn: str = ""
    lcsc: str = ""
    qty: float
    unit_cost_usd: float | None = None  # None -> pool moving average
    basis: str = "manual"
    consumed_at: str = ""
    note: str = ""


class AdjustmentIn(BaseModel):
    component_id: int | None = None
    mpn: str = ""
    lcsc: str = ""
    qty_delta: float
    unit_cost_usd: float | None = None
    reason: str = "attrition"
    charge_run_id: int | None = None
    adjusted_at: str = ""
    note: str = ""
    actor: str = ""


KINDS = {"part", "fab", "assembly", "tooling", "freight", "duty", "tax",
         "rework", "packaging", "service", "other"}
BASES = {"per_device", "per_run"}
# "excluded" = recorded so the document reconciles, charged to nobody on purpose.
ALLOCATES = {"none", "by_value", "by_qty", "excluded"}
REASONS = {"attrition", "scrap", "miscount", "opening_balance", "correction",
           # Stock consumed by a project outside the platform. Written directly by
           # `jlc_apply.apply_external_movements` since it existed, and REJECTED here
           # with a 422 — so the one movement the importer books routinely could not
           # be booked by hand. A bare negative adjustment reads as attrition, and
           # attrition is a defect signal in this codebase; conflating the two
           # inflates the apparent loss rate while hiding real losses.
           "external_project"}


def _run(db: Session, run_id: int) -> M.ProductionRun:
    r = db.get(M.ProductionRun, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return r


def _doc(db: Session, doc_id: int) -> M.RunCostDocument:
    d = db.get(M.RunCostDocument, doc_id)
    if d is None:
        raise HTTPException(404, "document not found")
    return d


def _check_line(body: LineIn | LinePatch | ChildIn) -> None:
    if body.kind is not None and body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    if body.basis is not None and body.basis not in BASES:
        raise HTTPException(422, f"basis must be one of {sorted(BASES)}")
    allocate = getattr(body, "allocate", None)
    if allocate is not None and allocate not in ALLOCATES:
        raise HTTPException(422, f"allocate must be one of {sorted(ALLOCATES)}")


def _check_destination(db: Session, run_id: int | None, project_id: int | None) -> None:
    """A line may name a run, a project, or neither — but never a run belonging
    to a different project than the one it also names."""
    run = _run(db, run_id) if run_id is not None else None
    if project_id is not None and db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    if run is not None and project_id is not None and run.project_id != project_id:
        raise HTTPException(422, f"run {run_id} belongs to project {run.project_id}, not {project_id}")


def _line(db: Session, line_id: int) -> M.RunCostLine:
    li = db.get(M.RunCostLine, line_id)
    if li is None:
        raise HTTPException(404, "line not found")
    return li


def _descendants(db: Session, line_id: int) -> list[M.RunCostLine]:
    """Every line below this one. Breadth-first with a seen-set, because
    `parent_line_id` is a soft pointer and a cycle must not hang the request."""
    out: list[M.RunCostLine] = []
    frontier, seen = [line_id], {line_id}
    while frontier:
        kids = db.query(M.RunCostLine).filter(M.RunCostLine.parent_line_id.in_(frontier)).all()
        frontier = []
        for k in kids:
            if k.id in seen:
                continue
            seen.add(k.id)
            out.append(k)
            frontier.append(k.id)
    return out


MAX_SPLIT_DEPTH = 4


def _depth(db: Session, li: M.RunCostLine) -> int:
    depth, cur, seen = 0, li.parent_line_id, set()
    while cur and cur not in seen:
        seen.add(cur)
        depth += 1
        parent = db.get(M.RunCostLine, cur)
        cur = parent.parent_line_id if parent else None
    return depth


# ---------------------------------------------------------------- documents

@router.get("/runs/{run_id}/documents")
def list_run_documents(run_id: int, db: Session = Depends(get_db)):
    """Documents relevant to this run: the ones assigned to it, PLUS any
    project-level document that has a line allocated to it — a single invoice
    can be split across several runs, so document ownership alone is not the
    filter. Kept identical to how `run_actuals.run_actuals` sums the money.
    """
    _run(db, run_id)
    line_docs = {
        did for (did,) in db.query(M.RunCostLine.document_id)
        .filter(M.RunCostLine.run_id == run_id, M.RunCostLine.voided_at.is_(None)).all()
    }
    docs = (
        db.query(M.RunCostDocument)
        .filter(or_(M.RunCostDocument.run_id == run_id,
                    M.RunCostDocument.id.in_(line_docs) if line_docs else False))
        .order_by(M.RunCostDocument.doc_date, M.RunCostDocument.id).all()
    )
    return [run_actuals.document_json(d, db=db) for d in docs]


@router.get("/projects/{project_id}/documents")
def list_project_documents(project_id: int, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    docs = (
        db.query(M.RunCostDocument).filter_by(project_id=project_id)
        .order_by(M.RunCostDocument.doc_date, M.RunCostDocument.id).all()
    )
    return [run_actuals.document_json(d, db=db) for d in docs]


@router.get("/documents")
def list_shared_documents(db: Session = Depends(get_db)):
    """Documents that belong to no single project — typically a parts invoice
    whose components feed the company-wide cost pool."""
    docs = (
        db.query(M.RunCostDocument).filter(M.RunCostDocument.project_id.is_(None))
        .order_by(M.RunCostDocument.doc_date, M.RunCostDocument.id).all()
    )
    return [run_actuals.document_json(d, db=db) for d in docs]


@router.get("/run-documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    """One document with its full line tree — what the invoice view expands."""
    return run_actuals.document_json(_doc(db, doc_id), db=db)


@router.post("/documents")
def create_shared_document(body: DocumentIn, db: Session = Depends(get_db)):
    """Create a SHARED document (no project). Its `part` lines go into the pool
    that every project draws from, so an invoice covering two products is
    entered once and split by what each run consumes."""
    return _create_document(None, body, db)


@router.post("/projects/{project_id}/documents")
def create_document(project_id: int, body: DocumentIn, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    return _create_document(project_id, body, db)


def _create_document(project_id: int | None, body: DocumentIn, db: Session):
    # Postgres treats NULLs as distinct, so the partial unique index cannot
    # protect shared documents — guard them here or a re-import doubles the pool.
    if project_id is None and (body.doc_number or body.external_id):
        dup = (
            db.query(M.RunCostDocument)
            .filter(M.RunCostDocument.project_id.is_(None))
            .filter(or_(
                and_(M.RunCostDocument.doc_number == body.doc_number, body.doc_number != ""),
                and_(M.RunCostDocument.external_id == body.external_id, body.external_id != ""),
            ))
            .first()
        )
        if dup is not None:
            raise HTTPException(409, f"shared document already exists (id={dup.id}, "
                                     f"number={dup.doc_number!r}, external_id={dup.external_id!r})")
    if body.run_id is not None:
        r = _run(db, body.run_id)
        if project_id is not None and r.project_id != project_id:
            raise HTTPException(422, "run belongs to a different project")
    for li in body.lines:
        _check_line(li)
    data = body.model_dump(exclude={"lines", "project_id"})
    doc = M.RunCostDocument(project_id=project_id, **data)
    # FX comes from NBP table A at the INVOICE DATE (user decision 2026-07-27).
    # Pinned onto the document so the figure can never drift, and appended to
    # the platform's rate history so runs around that date price correctly.
    fx_note = None
    if doc.fx_rate_usd is None and (doc.currency or "USD").upper() != "USD" and doc.doc_date:
        try:
            res = nbp.resolve_for_document(db, doc.currency, doc.doc_date)
            doc.fx_rate_usd = res["rate_usd"]
            fx_note = res
        except nbp.NbpError as exc:
            raise HTTPException(502, f"could not resolve an NBP rate: {exc}") from exc
    db.add(doc)
    db.flush()
    for i, li in enumerate(body.lines):
        d = li.model_dump()
        d.setdefault("position", i)
        db.add(M.RunCostLine(document_id=doc.id, **d))
    db.flush()
    # Bridge MPN -> library component immediately: a purchase that is not tied to
    # a component can never be matched by a BOM draw.
    resolved = run_actuals.resolve_part_lines(db, doc.id)
    audit(db, "run.document.add", "run_cost_document", doc.id, {
        "project_id": project_id, "run_id": doc.run_id, "supplier": doc.supplier,
        "doc_number": doc.doc_number, "lines": len(body.lines),
        "total_amount": doc.total_amount, "fx": fx_note, "resolved": resolved,
    })
    db.commit()
    out = run_actuals.document_json(doc, db=db)
    if fx_note:
        out["fx_source"] = fx_note
    out["resolved_parts"] = resolved
    return out


@router.post("/run-documents/{doc_id}/resolve-parts")
def resolve_parts(doc_id: int, db: Session = Depends(get_db)):
    """Match this document's part lines to library components by MPN.

    JLC invoices carry no LCSC code, so without this the cost pool and the BOM
    key on different identities and components price at zero.
    """
    _doc(db, doc_id)
    res = run_actuals.resolve_part_lines(db, doc_id)
    audit(db, "run.document.resolve_parts", "run_cost_document", doc_id, res)
    db.commit()
    return res


@router.post("/cost-lines/resolve-parts")
def resolve_parts_all(db: Session = Depends(get_db)):
    """Same, across every unresolved part line (after a library import, say)."""
    res = run_actuals.resolve_part_lines(db, None)
    audit(db, "run.cost_lines.resolve_parts", "run_cost_line", 0, res)
    db.commit()
    return res


@router.patch("/run-documents/{doc_id}")
def update_document(doc_id: int, body: DocumentPatch, db: Session = Depends(get_db)):
    doc = _doc(db, doc_id)
    before, after = {}, {}
    for field, value in body.model_dump(exclude_unset=True).items():
        old = getattr(doc, field)
        if old != value:
            before[field], after[field] = old, value
            setattr(doc, field, value)
    audit(db, "run.document.update", "run_cost_document", doc.id,
          {"before": before, "after": after})
    db.commit()
    return run_actuals.document_json(doc, db=db)


@router.delete("/run-documents/{doc_id}")
def delete_document(doc_id: int, force: bool = False, db: Session = Depends(get_db)):
    """Refuses while the document still has live lines unless ?force=true — a
    financial record should not vanish by accident."""
    doc = _doc(db, doc_id)
    live = [li for li in doc.lines if li.voided_at is None]
    if live and not force:
        raise HTTPException(409, f"document has {len(live)} live lines; pass force=true to delete")
    audit(db, "run.document.delete", "run_cost_document", doc.id,
          {"supplier": doc.supplier, "doc_number": doc.doc_number, "lines": len(doc.lines)})
    db.delete(doc)
    db.commit()
    return {"deleted": doc_id}


# -------------------------------------------------------------------- lines

@router.post("/run-documents/{doc_id}/lines")
def add_line(doc_id: int, body: LineIn, db: Session = Depends(get_db)):
    doc = _doc(db, doc_id)
    _check_line(body)
    pos = body.position or (max([li.position for li in doc.lines], default=-1) + 1)
    d = body.model_dump()
    d["position"] = pos
    li = M.RunCostLine(document_id=doc.id, **d)
    db.add(li)
    db.flush()
    audit(db, "run.cost_line.add", "run_cost_line", li.id, {
        "document_id": doc.id, "kind": li.kind, "label": li.label,
        "qty": li.qty, "unit_price": li.unit_price,
    })
    db.commit()
    return run_actuals.line_json(li, doc, db=db)


@router.post("/run-cost-lines/{line_id}/split")
def split_line(line_id: int, body: SplitIn, db: Session = Depends(get_db)):
    """Split one invoice position into child positions.

    Two uses, one mechanism: shares of a position charged to different runs, and
    a supplier's own sub-breakdown of a single printed figure (JLC prints "SMT
    Assembly $101.04"; stencil / manual assembly / surcharges only appear on
    their website). Children may be split again.

    Guarantees:
      * the parent keeps its printed amount, untouched — a split never rewrites
        what the invoice said;
      * children may not exceed the parent (409) — over-allocation is always a
        mistake, while under-allocation is legitimate and reported as `residual`;
      * a line with live children stops contributing money itself, so nothing is
        counted twice (`run_actuals.header_ids`);
      * children inherit the parent's currency, so the residual is arithmetic on
        one unit.
    """
    parent = _line(db, line_id)
    if parent.voided_at is not None:
        raise HTTPException(409, "line is voided")
    if not body.children:
        raise HTTPException(422, "no children given")
    if _depth(db, parent) + 1 > MAX_SPLIT_DEPTH:
        raise HTTPException(422, f"split depth would exceed {MAX_SPLIT_DEPTH}")
    if parent.kind == run_actuals.PART_KIND and not body.allow_parts:
        raise HTTPException(422, "part lines feed the component pool, which already splits them by "
                                 "consumption — splitting one per run double counts. Pass "
                                 "allow_parts=true only for parts bought for one specific batch.")
    doc = _doc(db, parent.document_id)
    existing = [c for c in db.query(M.RunCostLine)
                .filter(M.RunCostLine.parent_line_id == parent.id,
                        M.RunCostLine.voided_at.is_(None)).all()]
    if existing and body.replace:
        for c in existing:
            c.voided_at = utcnow()
            for d in _descendants(db, c.id):
                d.voided_at = utcnow()
        existing = []

    made: list[M.RunCostLine] = []
    pos = max([li.position for li in doc.lines], default=-1)
    for child in body.children:
        _check_line(child)
        _check_destination(db, child.run_id, child.project_id)
        qty, unit = child.qty, child.unit_price
        if child.amount is not None:
            qty, unit = 1.0, child.amount
        pos += 1
        made.append(M.RunCostLine(
            document_id=doc.id, parent_line_id=parent.id, position=pos,
            kind=child.kind or parent.kind, basis=child.basis or parent.basis,
            label=child.label or parent.label, qty=qty, unit_price=unit,
            currency=parent.currency,  # one currency per family, so residual is exact
            allocate=child.allocate or "none",
            run_id=child.run_id, project_id=child.project_id,
            component_id=child.component_id if child.component_id is not None else parent.component_id,
            mpn=child.mpn or parent.mpn, lcsc=child.lcsc or parent.lcsc,
            description=child.description, plan_key=child.plan_key,
            plan_kind=child.plan_kind, plan_ref=child.plan_ref, notes=child.notes,
        ))

    parent_amount = run_actuals.effective_qty(parent, doc, db) * (parent.unit_price or 0)
    child_amount = sum(run_actuals.effective_qty(c, doc, db) * (c.unit_price or 0)
                       for c in existing + made)
    if child_amount > parent_amount + 0.005:
        raise HTTPException(409, f"children total {child_amount:.4f} exceeds the position's "
                                 f"{parent_amount:.4f} {parent.currency or doc.currency}")
    for c in made:
        db.add(c)
    db.flush()
    audit(db, "run.cost_line.split", "run_cost_line", parent.id, {
        "document_id": doc.id, "label": parent.label, "parent_amount": round(parent_amount, 4),
        "children": [{"id": c.id, "label": c.label, "run_id": c.run_id,
                      "project_id": c.project_id, "amount": round(
                          run_actuals.effective_qty(c, doc, db) * (c.unit_price or 0), 4)}
                     for c in made],
        "replaced": body.replace, "residual": round(parent_amount - child_amount, 4),
    })
    db.commit()
    # `expire_on_commit=False` + children added via `db.add` means `doc.lines` is
    # still the pre-split collection, so the parent would serialize as a leaf.
    db.expire(doc, ["lines"])
    return {
        "parent_id": parent.id,
        "created": len(made),
        "residual": round(parent_amount - child_amount, 4),
        "document": run_actuals.document_json(doc, db=db),
    }


@router.patch("/run-cost-lines/{line_id}")
def update_line(line_id: int, body: LinePatch, db: Session = Depends(get_db)):
    li = _line(db, line_id)
    _check_line(body)
    fields = body.model_dump(exclude_unset=True)
    if "run_id" in fields or "project_id" in fields:
        _check_destination(db,
                           fields.get("run_id", li.run_id),
                           fields.get("project_id", li.project_id))
    before, after = {}, {}
    for field, value in fields.items():
        old = getattr(li, field)
        if old != value:
            before[field], after[field] = old, value
            setattr(li, field, value)
    audit(db, "run.cost_line.update", "run_cost_line", li.id, {"before": before, "after": after})
    db.commit()
    return run_actuals.line_json(li, db.get(M.RunCostDocument, li.document_id), db=db)


@router.delete("/run-cost-lines/{line_id}")
def void_line(line_id: int, db: Session = Depends(get_db)):
    """Voids, never deletes: a money row keeps its history.

    Voids the whole subtree — leaving orphaned children live would charge runs
    for shares of a position that no longer exists.
    """
    li = _line(db, line_id)
    kids = [c for c in _descendants(db, li.id) if c.voided_at is None]
    now = utcnow()
    for row in [li, *kids]:
        row.voided_at = now
    audit(db, "run.cost_line.void", "run_cost_line", li.id,
          {"kind": li.kind, "label": li.label, "qty": li.qty, "unit_price": li.unit_price,
           "children_voided": [c.id for c in kids]})
    db.commit()
    return {"voided": line_id, "children_voided": [c.id for c in kids]}


# ------------------------------------------------------ original documents

MAX_DOC_ATTACHMENT_MB = 25


@router.post("/run-documents/{doc_id}/attachment")
async def upload_doc_attachment(doc_id: int, file: UploadFile = File(...),
                                db: Session = Depends(get_db)):
    """File the supplier's original PDF/scan with the document it evidences.

    Stored under its own `documents/` prefix, never the run's: `delete_run` wipes
    the run prefix, and the evidence for a money row has to outlive the run.
    """
    doc = _doc(db, doc_id)
    data = await file.read()
    if len(data) > MAX_DOC_ATTACHMENT_MB * 1024 * 1024:
        raise HTTPException(413, f"attachment larger than {MAX_DOC_ATTACHMENT_MB} MB")
    filename = file.filename or "document"
    key = f"documents/{doc.id}/{uuid.uuid4().hex[:12]}-{filename}"
    storage.put_bytes(key, data, file.content_type or "application/octet-stream")
    a = M.RunAttachment(
        document_id=doc.id, filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data), minio_key=key,
    )
    db.add(a)
    db.flush()
    # Newest upload becomes the document's headline attachment; older ones stay
    # reachable through the list, so a corrected scan never destroys the first.
    doc.attachment_id = a.id
    audit(db, "run.document.attachment.add", "run_attachment", a.id,
          {"document_id": doc.id, "filename": filename, "size_bytes": len(data)})
    db.commit()
    return {"id": a.id, "document_id": doc.id, "filename": a.filename, "size_bytes": a.size_bytes}


@router.get("/run-documents/{doc_id}/attachments")
def list_doc_attachments(doc_id: int, db: Session = Depends(get_db)):
    _doc(db, doc_id)
    rows = (
        db.query(M.RunAttachment).filter(M.RunAttachment.document_id == doc_id)
        .order_by(M.RunAttachment.id.desc()).all()
    )
    return [
        {"id": a.id, "filename": a.filename, "content_type": a.content_type,
         "size_bytes": a.size_bytes,
         "uploaded_at": a.uploaded_at.isoformat() if a.uploaded_at else None}
        for a in rows
    ]


# --------------------------------------------------------- invoice register

@router.get("/parts-stock")
def parts_stock(db: Session = Depends(get_db)):
    """Every part measured both ways: what JLC physically holds at market price,
    and what the cost pool says was paid for the unconsumed remainder.

    A part JLC holds that the pool has never seen (`state: "jlc_only"`) means the
    purchase invoice is missing.
    """
    return run_actuals.parts_stock(db)


@router.get("/invoices")
def invoice_register(db: Session = Depends(get_db)):
    """Every supplier document with where its money went, plus the company-wide
    reconciliation: unassigned money, documents whose lines don't add up, and
    whether the component pool balances."""
    return run_actuals.invoice_register(db)


# ------------------------------------------------ consumption + attrition

@router.get("/runs/{run_id}/actuals")
def get_actuals(run_id: int, db: Session = Depends(get_db)):
    return run_actuals.run_actuals(db, _run(db, run_id))


@router.get("/runs/{run_id}/consumption")
def list_consumption(run_id: int, db: Session = Depends(get_db)):
    _run(db, run_id)
    rows = run_actuals.live_consumption(db, run_id=run_id).order_by(
        M.ComponentConsumption.id).all()
    # Lot children, so the UI can render one averaged row OR one row per lot from
    # a single fetch. The parent's `unit_cost_usd` is the qty-weighted average of
    # these, so both views total the same figure and switching cannot change a
    # number — which is the whole point of the advanced toggle.
    lots_by_cons: dict[int, list[dict]] = {}
    if rows:
        line_labels = {
            li.id: (li.lot_ref, doc.external_id or doc.doc_number or "")
            for li, doc in db.query(M.RunCostLine, M.RunCostDocument)
            .join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
            .filter(M.RunCostLine.lot_ref != "").all()
        }
        for b in (db.query(M.ComponentConsumptionLot)
                  .filter(M.ComponentConsumptionLot.consumption_id.in_([c.id for c in rows]))
                  .order_by(M.ComponentConsumptionLot.id).all()):
            ref, order = line_labels.get(b.lot_line_id or -1, ("", ""))
            lots_by_cons.setdefault(b.consumption_id, []).append({
                "id": b.id, "qty": b.qty, "unit_cost_usd": b.unit_cost_usd,
                "total_usd": round((b.qty or 0) * (b.unit_cost_usd or 0), 4),
                "source": b.source, "ext_ref": b.ext_ref or ref,
                "lot_line_id": b.lot_line_id, "purchase_order": order,
            })
    return [
        {"id": c.id, "component_id": c.component_id, "mpn": c.mpn, "lcsc": c.lcsc,
         "qty": c.qty, "unit_cost_usd": c.unit_cost_usd, "basis": c.basis,
         "consumed_at": c.consumed_at, "note": c.note,
         "total_usd": round((c.qty or 0) * (c.unit_cost_usd or 0), 4),
         "lots": lots_by_cons.get(c.id, [])}
        for c in rows
    ]


@router.get("/cost-steps")
def get_cost_steps():
    """The vendor-neutral production-step catalog (fab / pcba / final stages).
    One source of truth for the split dialog's templates, plan items and
    reporting — vendors are wordings on top of these keys, never new kinds."""
    return cost_steps.catalog_json()


@router.get("/parts-ledger")
def parts_ledger(component_id: int | None = None, mpn: str = "", lcsc: str = "",
                 db: Session = Depends(get_db)):
    """One part's full event timeline with running balance — how the stock moved,
    verifiable at any point in time (user requirement 2026-07-28)."""
    if component_id is None and not mpn and not lcsc:
        raise HTTPException(422, "give at least one of component_id, mpn, lcsc")
    return run_actuals.component_ledger(db, component_id, mpn, lcsc)


@router.post("/runs/{run_id}/consumption")
def add_consumption(run_id: int, body: ConsumptionIn, db: Session = Depends(get_db)):
    run = _run(db, run_id)
    # A draw cannot take stock the pool never had (user decision 2026-07-28,
    # hard block): the fix is the missing invoice, an adjustment, or an override.
    shortages = run_actuals.check_shortages(db, [{
        "component_id": body.component_id, "mpn": body.mpn, "lcsc": body.lcsc,
        "qty": body.qty, "date": body.consumed_at or run.run_date or "",
    }])
    if shortages:
        raise HTTPException(409, {"error": "insufficient stock for this draw",
                                  "shortages": shortages})
    unit = body.unit_cost_usd
    if unit is None:
        probe = type("P", (), {"component_id": body.component_id, "mpn": body.mpn, "lcsc": body.lcsc})()
        # As of the CONSUMPTION date, never "today": a 2024 draw must not be
        # priced from purchases made in 2026 (same rule as consume_from_bom).
        as_of = body.consumed_at or run.run_date or None
        unit = run_actuals.pool_state(db, run.project_id, as_of=as_of).get(
            run_actuals._key(probe), {}).get("avg_usd", 0.0)
    c = M.ComponentConsumption(
        run_id=run_id, component_id=body.component_id, mpn=body.mpn, lcsc=body.lcsc,
        qty=body.qty, unit_cost_usd=unit, basis=body.basis,
        consumed_at=body.consumed_at or run.run_date or "", note=body.note,
    )
    db.add(c)
    db.flush()
    audit(db, "run.consumption.add", "component_consumption", c.id, {
        "run_id": run_id, "qty": c.qty, "unit_cost_usd": c.unit_cost_usd, "basis": c.basis,
    })
    db.commit()
    return {"id": c.id, "unit_cost_usd": c.unit_cost_usd, "basis": c.basis}


@router.post("/runs/{run_id}/consumption/from-bom")
def consume_bom(run_id: int, db: Session = Depends(get_db)):
    """Draw the run's whole BOM from the pool at the moving average."""
    run = _run(db, run_id)
    res = run_actuals.consume_from_bom(db, run)
    if res.get("error"):
        # shortages ride along so the caller sees WHAT is missing, not just that
        # something is
        raise HTTPException(409, {"error": res["error"],
                                  "shortages": res.get("shortages") or []})
    audit(db, "run.consumption.from_bom", "production_run", run.id, res)
    db.commit()
    return res


@router.delete("/consumption/{cons_id}")
def delete_consumption(cons_id: int, db: Session = Depends(get_db)):
    c = db.get(M.ComponentConsumption, cons_id)
    if c is None:
        raise HTTPException(404, "consumption not found")
    audit(db, "run.consumption.delete", "component_consumption", cons_id,
          {"run_id": c.run_id, "qty": c.qty, "unit_cost_usd": c.unit_cost_usd})
    db.delete(c)
    db.commit()
    return {"deleted": cons_id}


def _adjustment_json(a: M.ComponentStockAdjustment) -> dict:
    return {"id": a.id, "project_id": a.project_id, "component_id": a.component_id,
            "mpn": a.mpn, "lcsc": a.lcsc, "qty_delta": a.qty_delta,
            "unit_cost_usd": a.unit_cost_usd, "reason": a.reason,
            "charge_run_id": a.charge_run_id, "adjusted_at": a.adjusted_at,
            "import_ref": a.import_ref or "", "actor": a.actor or "", "note": a.note}


@router.get("/stock-adjustments")
def list_all_adjustments(reason: str = "", db: Session = Depends(get_db)):
    """EVERY adjustment, including the ones belonging to no project.

    The per-project listing cannot show those, and an adjustment with a NULL
    `project_id` is exactly what a reconciliation pass writes — which is how five
    zero-cost `opening_balance` rows invented 6,368 units of stock and stayed
    invisible until the quantities were compared against JLC's own by hand
    (2026-07-28). An adjustment moves stock without an invoice behind it, so it is
    the least evidenced write in the system and must be the easiest to audit.
    """
    q = db.query(M.ComponentStockAdjustment)
    if reason:
        q = q.filter(M.ComponentStockAdjustment.reason == reason)
    rows = q.order_by(M.ComponentStockAdjustment.id.desc()).all()
    return {
        "adjustments": [_adjustment_json(a) for a in rows],
        "totals": {
            "count": len(rows),
            "qty_added": sum(a.qty_delta for a in rows if (a.qty_delta or 0) > 0),
            "qty_removed": sum(a.qty_delta for a in rows if (a.qty_delta or 0) < 0),
            "by_reason": {r: sum(1 for a in rows if a.reason == r)
                          for r in sorted({a.reason for a in rows})},
            # Stock conjured with no cost attached. Legitimate for a genuine opening
            # balance; otherwise it is quantity with no money behind it, which no
            # value identity can ever notice.
            "zero_cost_positive": sum(1 for a in rows if (a.qty_delta or 0) > 0
                                      and not a.unit_cost_usd),
        },
    }


@router.get("/projects/{project_id}/stock-adjustments")
def list_adjustments(project_id: int, db: Session = Depends(get_db)):
    rows = db.query(M.ComponentStockAdjustment).filter_by(project_id=project_id).order_by(
        M.ComponentStockAdjustment.id).all()
    return [
        {"id": a.id, "component_id": a.component_id, "mpn": a.mpn, "lcsc": a.lcsc,
         "qty_delta": a.qty_delta, "unit_cost_usd": a.unit_cost_usd, "reason": a.reason,
         "charge_run_id": a.charge_run_id, "adjusted_at": a.adjusted_at, "note": a.note}
        for a in rows
    ]


@router.post("/projects/{project_id}/stock-adjustments")
def add_adjustment(project_id: int, body: AdjustmentIn, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    if body.reason not in REASONS:
        raise HTTPException(422, f"reason must be one of {sorted(REASONS)}")
    if body.charge_run_id is not None:
        _run(db, body.charge_run_id)
    a = M.ComponentStockAdjustment(project_id=project_id, **body.model_dump())
    db.add(a)
    db.flush()
    audit(db, "run.stock_adjustment.add", "component_stock_adjustment", a.id, {
        "project_id": project_id, "qty_delta": a.qty_delta, "reason": a.reason,
        "charge_run_id": a.charge_run_id,
    })
    db.commit()
    return {"id": a.id}


@router.delete("/stock-adjustments/{adj_id}")
def delete_adjustment(adj_id: int, db: Session = Depends(get_db)):
    """Adjustments are corrections, and corrections themselves get corrected —
    a reconciliation pass that re-derives opening balances must be able to
    retract its own earlier rows. Audited like every money mutation."""
    a = db.get(M.ComponentStockAdjustment, adj_id)
    if a is None:
        raise HTTPException(404, "adjustment not found")
    audit(db, "run.stock_adjustment.delete", "component_stock_adjustment", adj_id, {
        "project_id": a.project_id, "component_id": a.component_id, "mpn": a.mpn,
        "qty_delta": a.qty_delta, "reason": a.reason, "charge_run_id": a.charge_run_id,
        "note": (a.note or "")[:200],
    })
    db.delete(a)
    db.commit()
    return {"deleted": adj_id}


@router.get("/fx/nbp")
def nbp_rate(currency: str, date: str, db: Session = Depends(get_db)):
    """NBP table A rate for a currency on a date (invoice-date convention).
    Reports the publication date actually used — NBP publishes nothing on
    weekends or holidays, so the lookup walks back to the previous working day.
    """
    try:
        rate, eff, detail = nbp.rate_usd(currency, date)
    except nbp.NbpError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"currency": currency.upper(), "requested_date": date, "effective_date": eff,
            "rate_usd": rate, "detail": detail, "requested_date_used": eff == date[:10]}


# --------------------------------------------------------------- the pool

@router.get("/projects/{project_id}/cost-pool")
def get_pool(project_id: int, as_of: str | None = None, db: Session = Depends(get_db)):
    """Per-part cost pool: bought / used / lost, moving average, value on hand.

    Quantities apportion money AND must agree with JLCPCB's consigned count —
    whatever went in either went out through a run, was written off, or is
    still on the shelf. /api/parts-stock is the check (goal restated
    2026-07-28: everything accounted for, not just a balanced register).
    """
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    pool = run_actuals.pool_state(db, project_id, as_of=as_of)
    rows = []
    for key, p in sorted(pool.items(), key=lambda kv: -abs(kv[1]["value_usd"])):
        rows.append({
            "key": key, "component_id": p["component_id"], "mpn": p["mpn"], "lcsc": p["lcsc"],
            "bought": round(p["bought"], 3), "used": round(p["used"], 3),
            "lost": round(p["lost"], 3), "on_hand": round(p["qty"], 3),
            "avg_unit_usd": round(p["avg_usd"], 6), "value_usd": round(p["value_usd"], 4),
            "unknown_rate": p["unknown_rate"],
        })
    return {
        "parts": rows,
        "as_of": as_of,
        "total_value_usd": round(sum(r["value_usd"] for r in rows), 2),
    }
