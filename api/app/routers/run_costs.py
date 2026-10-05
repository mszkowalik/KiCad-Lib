"""Post-factum production costs: supplier documents, actual cost lines,
component draws from the cost pool, and attrition.

Thin, per the api conventions: parse the request, call `services/run_actuals`,
shape the response. Every mutation writes an audit row WITH details — this is
the money path, so "something changed" is not good enough.
"""
import uuid
from types import SimpleNamespace

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..models import utcnow
from ..services import (cost_steps, journal, nbp, run_actuals, storage,
                        substitutions, supplier_parts)
from ..services import companies as company_svc
from .util import acting_name, audit, part_display_name

router = APIRouter(prefix="/api", tags=["run-costs"])


# ------------------------------------------------------------------ schemas

class LineIn(BaseModel):
    # `kind` is GONE (decision 0047): it was a second field saying what a
    # position is, typed beside `plan_key` and free to disagree with it. The
    # coarse bucket is derived from the step by `cost_steps.kind_of`.
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
    plan_item_id: int | None = None
    notes: str = ""
    # Why this position is charged to nobody. Stored since the `excluded` bucket
    # got a reason, writable from nowhere until decision 0045.
    exclude_reason: str = ""
    # Decision 0068: with allocate="overhead", the kind of company cost.
    overhead_category: str = ""
    run_id: int | None = None
    project_id: int | None = None
    # Decision 0058 §4: a conversion cost, aimed at one process transformation.
    transformation_id: int | None = None
    position: int = 0
    ocr_confidence: float | None = None


class ChildIn(BaseModel):
    """One share of a split position. `basis` defaults to the parent's.

    `id` names an EXISTING child to update in place. Re-creating it instead
    loses what only the original row carries — the importer's
    `external_line_id`, a plan link, its history — which is why the dialog
    could not add one rounding share to JLC's fee split without rewriting all
    nineteen (2026-09-24).

    Amounts are ABSOLUTE. A percentage split is a frontend affordance — the
    browser turns "40%" into a number before it gets here (user decision
    2026-07-27), so a stored figure never has to be re-derived and cannot drift.
    """

    id: int | None = None
    label: str = ""
    basis: str | None = None
    qty: float = 1.0
    unit_price: float = 0.0
    # Convenience for the common case "this share is worth X": sets qty=1.
    amount: float | None = None
    run_id: int | None = None
    project_id: int | None = None
    transformation_id: int | None = None
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
    # ...and WHY. This field did not exist until 2026-09-21, so the split path
    # could mark a share excluded and had no way to say what for: every prepaid
    # component share JLC's populated-board invoices produce arrived unlabelled
    # and had to be corrected by hand afterwards (decision 0048).
    exclude_reason: str = ""
    # Decision 0068: with allocate="overhead", the kind of company cost. The
    # split dialog dropped it, so an overhead share came back as "other".
    overhead_category: str = ""


class SplitIn(BaseModel):
    children: list[ChildIn]
    # Parts belong in the pool, which already splits them by consumption.
    # Splitting them per run by hand double counts, so it takes an explicit flag.
    allow_parts: bool = False
    # The children sent ARE the split: existing children not named by `id` are
    # voided. Without it, existing children stay and these are added.
    replace: bool = False


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
    corrects_document_id: int | None = None
    # Decision 0064: the company that was BILLED. Default: the caller's only
    # company; with two, it stays unnamed until a person says.
    company_id: int | None = None
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
    # Decision 0064: the company that was BILLED. Set by a person, it records
    # `company_source="manual"`.
    company_id: int | None = None


class CorrectionIn(BaseModel):
    """What to change about the correction the platform is about to write.

    Every field is optional: with an empty body the endpoint produces an empty
    correction dated today, pointed at the original, ready for its positions.
    """

    doc_date: str = ""          # default: today. A correction is posted WHEN IT IS MADE.
    doc_number: str = ""        # default: "<original>-C<n>"
    notes: str = ""             # appended to the generated provenance line
    total_amount: float | None = None
    #: Resolve FX at the CORRECTION's date instead of inheriting the original's
    #: pinned rate. Off by default, and the default is the important one: a
    #: correction to a EUR invoice is the same purchase transcribed better, so it
    #: has to convert at the rate that invoice was pinned at — otherwise
    #: "1651 EUR was really 1551 EUR" nets to a USD figure that is neither.
    #: Turn it on for money that is genuinely NEW, like a freight bill that
    #: arrived later at its own rate.
    own_fx: bool = False
    lines: list[LineIn] = []


class LinePatch(BaseModel):
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
    plan_item_id: int | None = None
    notes: str | None = None
    exclude_reason: str | None = None
    overhead_category: str | None = None
    run_id: int | None = None
    project_id: int | None = None
    transformation_id: int | None = None


class LineEdit(LinePatch):
    """One line's new values inside a batch. `id` names the row it applies to."""

    id: int


class LinesBatchIn(BaseModel):
    """Everything an operator changed while the document was open, applied as ONE
    transaction.

    Batch editing exists because a per-field save cannot express a SWAP: moving
    the component mapping of position A onto B and B's onto A is legal, but
    either half on its own strands the draws priced against it (user decision
    2026-09-19). So the whole set is guarded on its NET effect and committed
    together, or nothing is written.
    """

    document: DocumentPatch | None = None   # the header fields, changed in the same breath
    updates: list[LineEdit] = []
    creates: list[LineIn] = []
    deletes: list[int] = []   # voided, never hard-deleted — a money row keeps its history


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
    # Decision 0064: whose stock moves. Default: the charged batch's company,
    # else the project's owner on the adjustment date.
    company_id: int | None = None
    component_id: int | None = None
    mpn: str = ""
    lcsc: str = ""
    qty_delta: float
    unit_cost_usd: float | None = None
    reason: str = "attrition"
    charge_run_id: int | None = None
    adjusted_at: str = ""
    note: str = ""


BASES = {"per_device", "per_run"}
# "excluded" = recorded so the document reconciles, charged to nobody on purpose.
# "pooled" = stock, stated outright (decision 0045); "excluded" = recorded and
# charged to nobody on purpose; "none" = nothing has been said, which on a line
# naming no run and no project is a DEFECT the register reports as `unassigned`.
# "overhead" = a company cost of no product, under a category (decision 0068).
ALLOCATES = {"none", "pooled", "by_value", "by_qty", "excluded", "overhead"}
# The types a person or an import may write. "transfer" is written only by
# `services/transfers.py` (decision 0064): typed onto an ordinary document it
# would leave the money totals and re-route its stock.
DOC_TYPES = {"invoice", "proforma", "receipt", "credit_note", "correction"}


def _check_doc_type(doc_type: str | None) -> None:
    if doc_type is not None and doc_type not in DOC_TYPES:
        raise HTTPException(422, f"doc_type is one of {', '.join(sorted(DOC_TYPES))}"
                                 + (" — an in-house transfer is written on the Transfers page"
                                    if doc_type == "transfer" else ""))


def _guard_purchase_loss(db: Session, losses: list[dict], what: str) -> None:
    """Refuse a change that would leave draws with no purchase behind them.

    The draw side has been guarded since draws existed; this is the purchase
    side (user decision 2026-09-19). A change that keeps every part covered goes
    through untouched — the rule is "would this strand a draw", never "has this
    part ever been consumed".
    """
    short = run_actuals.check_purchase_loss(db, losses)
    if short:
        # `detail.error` is what the browser shows, so it has to name the parts
        # itself — the frontend contract forbids leaving a fact only in a
        # sibling key (web/CLAUDE.md, "request() renders a structured refusal").
        named = ", ".join(
            f"{s_.get('label') or s_.get('mpn') or s_.get('component_id')} "
            f"short {s_.get('short'):.0f}" for s_ in short[:3])
        more = f" and {len(short) - 3} more" if len(short) > 3 else ""
        raise HTTPException(409, {
            "error": f"{what} would leave component draws with no purchase behind "
                     f"them: {named}{more}. Remove or reduce those draws first, or "
                     f"record a stock adjustment for the difference.",
            "shortages": short,
        })


def _stock_before(db: Session, doc_ids, extra=(), new_company_id: int | None = None) -> dict:
    """`lots.stock_before`, with the edit in a savepoint: a refusal by
    `_refuse_stock_loss` takes back what the edit wrote."""
    from ..services import lots as lots_svc

    return {**lots_svc.stock_before(db, doc_ids, extra, new_company_id), "sp": db.begin_nested()}


def _refuse_stock_loss(db: Session, before: dict, what: str) -> None:
    """Refuse an edit, written but not committed, that leaves draws without
    the lots or the stock they took (`lots.stock_problems`)."""
    from ..services import lots as lots_svc

    problems = lots_svc.stock_problems(db, before)
    if problems:
        before["sp"].rollback()
        raise HTTPException(409, f"{what} would leave draws without what they took: {'; '.join(problems[:4])}. "
                                 "Reduce or void those draws first, or record a stock adjustment.")
    before["sp"].commit()


def _guard_buyer_change(db: Session, doc: M.RunCostDocument, company_id: int | None) -> bool:
    """Check a new BUYER for a document (decision 0064). Returns whether it
    changes.

    A new buyer moves every pooled position into the other company's stock, so
    the old buyer loses all of it and must not be left with draws it cannot
    cover — the rule of 0040. Nothing moves while the companies share one pool,
    or when the document had no buyer yet."""
    if company_id == doc.company_id:
        return False
    if company_id is None:
        raise HTTPException(422, "a document keeps a buyer once it has one; name the other company")
    company_svc.get(db, company_id)
    if run_actuals.stock_scope(db, doc.company_id) is not None:
        hdrs = run_actuals.header_ids(db, doc.id)
        live = [li for li in doc.lines if li.voided_at is None]
        _guard_purchase_loss(db, [
            run_actuals.purchase_loss_of(db, li)
            for li in run_actuals.pooled_part_lines(db, live) if li.id not in hdrs
        ], "giving this document another buyer")
    return True


def _guard_closed(db: Session, doc: M.RunCostDocument, what: str) -> None:
    """Refuse an in-place edit to a document that charges a CLOSED batch.

    Decision 0044. A batch's direct costs are recomputed from these lines on
    every read, so editing one moves a per-device cost that has already been
    carried onto an order. Closing the batch makes the change an EVENT instead:
    a correction document, dated when the correction was made.

    The refusal names the batches and the way forward, because `detail.error` is
    the whole message the browser shows (web/CLAUDE.md).
    """
    if (doc.doc_type or "") == "transfer":
        # Decision 0064: a transfer changes only as a whole, through
        # Transfers → Reverse, so its two sides can never disagree.
        raise HTTPException(409, {"error": f"{what} is refused: {doc.doc_number} is an in-house "
                                           "transfer. Reverse it and write another.",
                                  "document_id": doc.id})
    locked = run_actuals.closed_lock(db, doc)
    if not locked:
        return
    named = ", ".join(f"{r['label']} (closed {(r['closed_at'] or '')[:10]})" for r in locked)
    raise HTTPException(409, {
        "error": f"{what} is refused: this document charges a batch whose books are "
                 f"closed — {named}. Editing it would move a per-device cost that has "
                 f"already been carried onto orders. Write a CORRECTION document "
                 f"instead, or reopen the batch if it was closed by mistake.",
        "locked": locked,
        "document_id": doc.id,
    })


REASONS = {"attrition", "scrap", "miscount", "opening_balance", "correction",
           # Stock consumed by a project outside the platform. Written directly by
           # `jlc_apply.apply_external_movements` since it existed, and REJECTED here
           # with a 422 — so the one movement the importer books routinely could not
           # be booked by hand. A bare negative adjustment reads as attrition, and
           # attrition is a defect signal in this codebase; conflating the two
           # inflates the apparent loss rate while hiding real losses.
           "external_project"}


class SubstitutionIn(BaseModel):
    designator: str
    fitted_lcsc: str = ""
    fitted_mpn: str = ""
    fitted_component_id: int | None = None
    specified_lcsc: str = ""
    specified_mpn: str = ""
    specified_component_id: int | None = None
    qty_per_device: float = 1.0
    source: str = "supplier"
    supplied_by: str = ""
    supplier_source: str = ""
    supplier_designator: str = ""
    evidence: str = ""
    note: str = ""
    design_updated: bool = False


def _sub_json(s: M.RunSubstitution, db: Session | None = None) -> dict:
    """`*_name` is what a READER should see: the library's manufacturer part
    number when the part is in the library, and otherwise exactly the string
    somebody typed. The raw `*_lcsc` / `*_mpn` stay for matching."""
    named = {}
    if db is not None:
        spec_name, spec_lib = part_display_name(db, s.specified_component_id,
                                                s.specified_lcsc, s.specified_mpn)
        fit_name, fit_lib = part_display_name(db, s.fitted_component_id,
                                              s.fitted_lcsc, s.fitted_mpn)
        named = {
            "specified_name": spec_name, "specified_in_library": spec_lib,
            "fitted_name": fit_name, "fitted_in_library": fit_lib,
        }
    return {
        **named,
        "id": s.id, "run_id": s.run_id, "board": s.board, "variant": s.variant,
        "designator": s.designator, "supplier_designator": s.supplier_designator,
        "specified_lcsc": s.specified_lcsc, "specified_mpn": s.specified_mpn,
        "specified_component_id": s.specified_component_id,
        "fitted_lcsc": s.fitted_lcsc, "fitted_mpn": s.fitted_mpn,
        "fitted_component_id": s.fitted_component_id,
        "qty_per_device": s.qty_per_device, "source": s.source,
        "supplied_by": s.supplied_by, "supplier_source": s.supplier_source,
        "evidence": s.evidence, "note": s.note, "design_updated": s.design_updated,
        "decided_by": s.decided_by,
        "decided_at": s.decided_at.isoformat() if s.decided_at else None,
    }


@router.get("/runs/{run_id}/substitutions")
def list_substitutions(run_id: int, db: Session = Depends(get_db)):
    """What this batch fitted in place of what the design specifies, and what
    it shows no sign of fitting at all.

    `unused` is only meaningful with `has_supplier_bom`: without the supplier's
    own BOM for the batch, the absence of a part says nothing.
    """
    run = _run(db, run_id)
    return {"substitutions": [_sub_json(s, db) for s in substitutions.for_run(db, run_id)],
            **substitutions.unused(db, run)}


@router.post("/runs/{run_id}/substitutions")
def add_substitution(run_id: int, body: SubstitutionIn, db: Session = Depends(get_db)):
    """Record a part fitted in place of the specified one, for THIS batch.

    Journalled, because it changes what a BOM draw takes out of the pool. It
    does NOT rewrite the snapshot: the design keeps saying what was specified,
    which is the whole point of holding the two apart
    ([0038](../../../docs/decisions/0038-a-substitution-belongs-to-the-batch.md)).
    """
    actor = acting_name()
    run = _run(db, run_id)
    with journal.batch(db, kind="run.substitution", source_ref=f"run:{run_id}",
                       actor=actor) as h:
        row = new_substitution(db, run, body, actor)
    audit(db, "run.substitution.add", "run_substitution", row.id,
          {"run_id": run_id, "designator": row.designator,
           "from": row.specified_lcsc, "to": row.fitted_lcsc,
           "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**_sub_json(row, db), "batch_id": h["batch_id"], "reversible": True}


def new_substitution(db: Session, run: M.ProductionRun, body: SubstitutionIn, actor: str,
                     step_run_id: int | None = None) -> M.RunSubstitution:
    """One substitution row, checked, written but NOT committed or journalled —
    the caller owns both ("Record assembly" records its replacements with the
    step, decision 0072)."""
    run_id = run.id
    if not body.designator.strip():
        raise HTTPException(422, "name the position: designator")
    named = bool(body.fitted_lcsc or body.fitted_mpn or body.fitted_component_id)
    # Quantity ZERO is "nothing was fitted here" — the early batches shipped
    # without cartons, and that is history rather than an error. It is the same
    # row because it answers the same question, "why is the design's part not
    # on this board", and it silences the same warning.
    if not named and body.qty_per_device != 0:
        raise HTTPException(422, "name what was fitted, or set qty_per_device to 0 "
                                 "to record that nothing was")
    dup = (db.query(M.RunSubstitution)
             .filter_by(run_id=run_id, board=run.board or "", variant=run.variant or "",
                        designator=body.designator.strip()).first())
    if dup is not None:
        raise HTTPException(409, {"error": f"this batch already records a substitution "
                                           f"at {body.designator.strip()}", "id": dup.id})
    row = M.RunSubstitution(
        run_id=run_id, board=run.board or "", variant=run.variant or "",
        designator=body.designator.strip(),
        supplier_designator=body.supplier_designator.strip(),
        specified_component_id=body.specified_component_id,
        specified_lcsc=body.specified_lcsc, specified_mpn=body.specified_mpn,
        fitted_component_id=body.fitted_component_id,
        fitted_lcsc=body.fitted_lcsc, fitted_mpn=body.fitted_mpn,
        qty_per_device=body.qty_per_device, source=body.source,
        supplied_by=body.supplied_by, supplier_source=body.supplier_source,
        evidence=body.evidence, note=body.note,
        design_updated=body.design_updated, decided_by=actor, step_run_id=step_run_id)
    db.add(row)
    db.flush()
    return row


@router.put("/substitutions/{sub_id}")
def update_substitution(sub_id: int, design_updated: bool | None = None,
                        note: str | None = None, db: Session = Depends(get_db)):
    """Mark the design as caught up, or correct the note.

    `design_updated` is what clears the standing drift finding — it is a claim
    that the schematic now says what the factory fitted, so it is the one flag
    worth setting deliberately.
    """
    actor = acting_name()
    row = db.get(M.RunSubstitution, sub_id)
    if row is None:
        raise HTTPException(404, "substitution not found")
    with journal.batch(db, kind="run.substitution.edit", source_ref=f"sub:{sub_id}",
                       actor=actor) as h:
        if design_updated is not None:
            row.design_updated = design_updated
        if note is not None:
            row.note = note
        db.flush()
    audit(db, "run.substitution.update", "run_substitution", sub_id,
          {"design_updated": row.design_updated, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**_sub_json(row, db), "batch_id": h["batch_id"], "reversible": True}


@router.delete("/substitutions/{sub_id}")
def delete_substitution(sub_id: int, db: Session = Depends(get_db)):
    actor = acting_name()
    row = db.get(M.RunSubstitution, sub_id)
    if row is None:
        raise HTTPException(404, "substitution not found")
    info = {"run_id": row.run_id, "designator": row.designator,
            "from": row.specified_lcsc, "to": row.fitted_lcsc}
    with journal.batch(db, kind="run.substitution.delete", source_ref=f"sub:{sub_id}",
                       actor=actor) as h:
        db.delete(row)
        db.flush()
    audit(db, "run.substitution.delete", "run_substitution", sub_id,
          {**info, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {"status": "deleted", "batch_id": h["batch_id"], "reversible": True}


@router.get("/substitutions/detected")
def detected_substitutions(db: Session = Depends(get_db)):
    """Positions the SUPPLIER's own BOM says changed, and the designs that have
    not caught up with the ones already recorded.

    Candidates only — nothing is written until someone records it.
    """
    return {"candidates": substitutions.detect(db), "drift": substitutions.drift(db)}


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
    step = getattr(body, "plan_key", None)
    # A step that is not in the catalog cannot say what the position IS, and the
    # bucket derived from it would silently be "other". `c<id>` is the older
    # direct link to one cost item and stays valid. "" means undecided, which is
    # a legal state and shows red (decision 0045).
    if step and step not in cost_steps.STEPS:
        # ANY non-step value, not just one containing a colon. `plan_key` used to
        # double as the direct cost-item link (a bare integer); that link has its
        # own column now, and letting an integer back in here would replace what
        # the position IS with what it is compared against (decision 0047).
        raise HTTPException(422, f"unknown production step {step!r} — `plan_key` is "
                                 f"the step catalog key; use `plan_item_id` to link "
                                 f"a position to a planned cost item")
    if body.basis is not None and body.basis not in BASES:
        raise HTTPException(422, f"basis must be one of {sorted(BASES)}")
    allocate = getattr(body, "allocate", None)
    if allocate is not None and allocate not in ALLOCATES:
        raise HTTPException(422, f"allocate must be one of {sorted(ALLOCATES)}")
    cat = getattr(body, "overhead_category", None)
    if cat and cat not in run_actuals.OVERHEAD_CATEGORIES:
        raise HTTPException(422, f"overhead category must be one of {sorted(run_actuals.OVERHEAD_CATEGORIES)}")


def _check_allocate(step: str | None, allocate: str | None) -> None:
    """Only a position on a STOCK step can BE stock (decisions 0045, 0047).

    `pooled` says "this position enters the shared pool". `_pool_events` only
    ever treats a `part` line as a purchase, so a `pooled` line of any other kind
    would be counted in the register's `pool` bucket and never appear in
    `pool.purchased_usd` — two pool figures, quietly disagreeing. Anything else
    that belongs on the stock is landed cost and rides on the parts:
    `by_value` / `by_qty`.
    """
    if allocate == run_actuals.OVERHEAD and step is not None and cost_steps.is_stock_step(step):
        raise HTTPException(422, f"a position on stock step {step!r} is stock, not a company overhead")
    if allocate == run_actuals.POOLED and step is not None \
            and not cost_steps.is_stock_step(step):
        raise HTTPException(422, {
            "error": f"a position on step {step!r} cannot BE stock — only "
                     f"{sorted(cost_steps.PART_STEPS)} can. To put its money onto "
                     f"the stock, spread it over this document's parts with "
                     f"allocate 'by_value' or 'by_qty'.",
            "step": step, "allocate": allocate,
        })


def _check_excluded(allocate: str | None, reason: str | None) -> None:
    """An exclusion has to say WHAT FOR (decision 0048).

    `excluded` is a legal bucket in the register's conservation identity, so an
    excluded position is invisible to every other check the platform has: the
    gap still closes, nothing is unassigned, and USD 14,443 of manufacturing sat
    charged to nobody with every light green. The reason is the only thing that
    makes it auditable rather than merely missing, and it was reachable from
    the line editor but NOT from the split dialog — which is where JLC's prepaid
    component shares are made, and why 26 of them had to be labelled by hand on
    2026-09-21.

    Free text on purpose: the vocabulary in the production-run skill is a
    convention, and a closed list here would refuse the first honest reason
    nobody thought of.
    """
    if allocate == run_actuals.EXCLUDED and not (reason or "").strip():
        raise HTTPException(422, {
            "error": "an excluded position must say why it is charged to nobody",
            "hint": "set `exclude_reason` — e.g. reclaimable_vat, "
                    "prepaid_components, external_project, cancelled_by_supplier, "
                    "payment_fee. `excluded` passes every other check in the "
                    "register, so the reason is what makes it auditable.",
        })


# A step whose money can never be charged to anyone. `other:cancelled` is the
# supplier printing a line for something it did not deliver (user decision
# 2026-09-19): nobody pays for it, so it may not name a batch or a project.
# `other:awaiting_delivery` is money paid for parts that have not arrived: it is
# nobody's cost until a refresh turns it into a pool lot (2026-09-24).
NEVER_CHARGED = {"other:cancelled", "other:awaiting_delivery"}


def _check_cancelled(step: str | None, allocate: str | None,
                     run_id: int | None, project_id: int | None) -> None:
    if step not in NEVER_CHARGED:
        return
    if run_id is not None or project_id is not None or allocate != run_actuals.EXCLUDED:
        raise HTTPException(422, {
            "error": ("a cancelled position has no destination — the supplier printed "
                      "it, nothing was delivered and nobody pays for it. Leave it "
                      "charged to nobody, on purpose." if step == "other:cancelled" else
                      "a position awaiting delivery has no destination — the parts have "
                      "not arrived, so they are nobody's cost yet. Refresh the parts "
                      "order once they arrive; the line then becomes a pool lot."),
            "step": step,
        })


def _check_destination(db: Session, run_id: int | None, project_id: int | None) -> None:
    """A line may name a run, a project, or neither — but never a run belonging
    to a different project than the one it also names."""
    run = _run(db, run_id) if run_id is not None else None
    if project_id is not None and db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    if run is not None and project_id is not None and run.project_id != project_id:
        raise HTTPException(422, f"run {run_id} belongs to project {run.project_id}, not {project_id}")


def _check_transformation(db: Session, step: str | None, transformation_id: int | None,
                          run_id: int | None, project_id: int | None,
                          allocate: str | None) -> None:
    """A conversion cost (decision 0058 §4) goes to exactly one live
    transformation and nowhere else.

    It may not be a STOCK position: stickers bought by the roll are an ordinary
    pooled purchase that the sticker transformation draws, and a stock line
    aimed at a transformation would count once as a purchase and again as the
    lot's conversion value."""
    if transformation_id is None:
        return
    t = db.get(M.ProcessTransformation, transformation_id)
    if t is None:
        raise HTTPException(404, f"no transformation {transformation_id}")
    if t.voided_at is not None:
        raise HTTPException(409, f"transformation {transformation_id} is voided")
    if step and cost_steps.is_stock_step(step):
        raise HTTPException(422, {
            "error": f"a position on stock step {step!r} is a purchase, not a conversion cost — "
                     "buy it into the pool and let the transformation's recipe draw it",
            "step": step,
        })
    if step in NEVER_CHARGED:
        raise HTTPException(422, f"a {step!r} position is charged to nobody")
    if run_id is not None or project_id is not None:
        raise HTTPException(422, "a conversion cost goes to its transformation only — clear the "
                                 "batch and the project")
    if allocate not in (None, "none"):
        raise HTTPException(422, "a conversion cost is not spread, pooled or excluded")


def _one_destination(f: dict, cur: M.RunCostLine | None = None) -> dict:
    """A patch that sends a position to a batch, a project, the pool or nobody
    takes it OFF its transformation, and one aimed at a transformation clears
    the rest — every editor writes the whole destination (decision 0045).

    A company overhead names nothing else on any write path (decision 0068). A
    patch of an overhead position (`cur`) that names a batch, a project or a
    transformation without saying `allocate` takes it OFF the overhead, or the
    batch would be charged money the overhead bucket also holds."""
    if cur is not None and "allocate" not in f and cur.allocate == run_actuals.OVERHEAD:
        if f.get("run_id") is not None or f.get("project_id") is not None \
                or f.get("transformation_id") is not None:
            f["allocate"], f["overhead_category"] = "none", ""
        elif "basis" in f:
            f["basis"] = "per_run"
    if f.get("allocate") == run_actuals.OVERHEAD:
        # A company overhead names no batch, project or transformation, and
        # needs its category (decision 0068).
        f["run_id"], f["project_id"], f["transformation_id"] = None, None, None
        f["basis"] = "per_run"
        cat = (f.get("overhead_category") or "other").strip()
        if cat not in run_actuals.OVERHEAD_CATEGORIES:
            raise HTTPException(422, f"overhead category must be one of {sorted(run_actuals.OVERHEAD_CATEGORIES)}")
        f["overhead_category"] = cat
        return f
    if f.get("allocate") not in (None, run_actuals.OVERHEAD) and "overhead_category" not in f:
        f["overhead_category"] = ""
    if f.get("transformation_id") is not None:
        f["run_id"], f["project_id"] = None, None
        f["allocate"] = "none"
        f["basis"] = "per_run"
    elif "transformation_id" not in f and (
            f.get("run_id") is not None or f.get("project_id") is not None
            or f.get("allocate") not in (None, "none")):
        f["transformation_id"] = None
    return f


def _overhead_whole(li: LineIn) -> LineIn:
    """A NEW overhead position, its destination written whole: no batch, no
    project, no transformation, `per_run`, a category. Every create path runs
    it, as every patch runs `_one_destination`."""
    if li.allocate != run_actuals.OVERHEAD:
        return li
    return LineIn(**_one_destination(li.model_dump()))


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

@router.get("/runs/{run_id}/batch-supply")
def batch_supply(run_id: int, db: Session = Depends(get_db)):
    """Parts this batch bought DIRECTLY, outside the shared pool.

    The Materials tab is built from the BOM, the draws, the write-offs and the
    substitutions — none of which can see a part charged straight to the batch,
    so a position met that way read as empty while the batch paid for it.
    """
    return {"rows": supplier_parts.batch_supply(db, _run(db, run_id))}


@router.get("/runs/{run_id}/supply-coverage")
def supply_coverage(run_id: int, db: Session = Depends(get_db)):
    """Is every part this batch used accounted for exactly ONCE?

    `drawn_but_supplier_supplied` is the double charge `void_shop_draws` was
    written to undo by hand; `no_draw` is its mirror, a part we supplied and
    never booked. Both were previously invisible until somebody went looking.
    """
    return supplier_parts.coverage(db, _run(db, run_id))


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
    _check_doc_type(body.doc_type)
    if body.run_id is not None:
        r = _run(db, body.run_id)
        if project_id is not None and r.project_id != project_id:
            raise HTTPException(422, "run belongs to a different project")
    body.lines = [_overhead_whole(li) for li in body.lines]
    for li in body.lines:
        _check_line(li)
        _check_allocate(li.plan_key, li.allocate)
        _check_excluded(li.allocate, li.exclude_reason)
        _check_cancelled(li.plan_key, li.allocate, li.run_id, li.project_id)
        _check_transformation(db, li.plan_key, li.transformation_id, li.run_id,
                              li.project_id, li.allocate)
    data = body.model_dump(exclude={"lines", "project_id"})
    original = db.get(M.RunCostDocument, body.corrects_document_id) if body.corrects_document_id else None
    if body.corrects_document_id and original is None:
        raise HTTPException(404, f"no document {body.corrects_document_id} to correct")
    if original is not None and original.company_id:
        # A correction is the same purchase, so it has the same buyer: billed
        # to the other company it would move stock the original never bought.
        if data.get("company_id") not in (None, original.company_id):
            raise HTTPException(422, "a correction is billed to the company its original was billed to")
        data["company_id"], data["company_source"] = original.company_id, "the corrected document"
    elif data.get("company_id"):
        company_svc.get(db, data["company_id"])
        data["company_source"] = "manual"
    else:
        from ..services import tracking

        ctx = tracking.current()
        user = db.get(M.User, ctx.user_id) if ctx and ctx.user_id else None
        mine = company_svc.memberships(db, user) if user is not None and user.role != "admin" else []
        if len(mine) == 1:
            data["company_id"], data["company_source"] = mine[0], "the user's only company"
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
    held = _stock_before(db, [doc.id], extra=[(li, doc) for li in body.lines])
    for i, li in enumerate(body.lines):
        d = li.model_dump()
        d.setdefault("position", i)
        db.add(M.RunCostLine(document_id=doc.id, **d))
    db.flush()
    # Bridge MPN -> library component immediately: a purchase that is not tied to
    # a component can never be matched by a BOM draw.
    resolved = run_actuals.resolve_part_lines(db, doc.id)
    _refuse_stock_loss(db, held, "this document")   # a credit is a negative line (decision 0044)
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


@router.post("/run-documents/{doc_id}/correction")
def create_correction(doc_id: int, body: CorrectionIn | None = None,
                      db: Session = Depends(get_db)):
    """Write a CORRECTION of this document — the only way to change what a closed
    batch cost (decision 0044).

    The original is never touched. It keeps the figures it was printed with,
    exactly as a split parent keeps its printed amount, and the correction stands
    beside it carrying what actually changed. A credit is a negative line.

    The correction is an ordinary document in every other respect: it
    reconciles, it assigns, it feeds the pool or a run. Nothing in any money path
    special-cases it, which is the point — a correction has to be as auditable
    as the thing it corrects, and a parallel mechanism would be neither.

    Two things are inherited rather than re-derived:

    * **The supplier, currency, project and batch**, because it is the same
      purchase. Only the numbers are in question.
    * **The pinned FX rate** (unless `own_fx`). See `CorrectionIn.own_fx`.
    """
    src = _doc(db, doc_id)
    if (src.doc_type or "") == "transfer":
        # Decision 0069: a transfer changes only as a whole, so its two sides
        # can never disagree.
        raise HTTPException(409, "a transfer changes only as a whole: reverse it on Production → Transfers")
    body = body or CorrectionIn()
    # A correction of a correction is legal and sometimes necessary, but it
    # points at the document it corrects, never at the root — the chain is the
    # history.
    seq = db.query(M.RunCostDocument).filter(
        M.RunCostDocument.corrects_document_id == src.id).count() + 1
    number = body.doc_number.strip() or f"{src.doc_number or f'doc {src.id}'}-C{seq}"
    provenance = (f"Correction of {src.supplier} {src.doc_number or f'#{src.id}'}"
                  f"{' dated ' + src.doc_date if src.doc_date else ''} (document {src.id}). "
                  f"The original is unchanged and keeps its printed figures.")
    payload = DocumentIn(
        run_id=src.run_id,
        doc_type="correction",
        supplier=src.supplier,
        doc_number=number,
        # NOT the supplier's order id: that is an idempotency key for imports and
        # two documents carrying it would make a re-import ambiguous.
        external_id="",
        doc_date=body.doc_date.strip() or utcnow().date().isoformat(),
        currency=src.currency,
        fx_rate_usd=None if body.own_fx else src.fx_rate_usd,
        total_amount=body.total_amount,
        notes=(provenance + ("\n" + body.notes if body.notes.strip() else "")),
        corrects_document_id=src.id,
        lines=body.lines,
    )
    out = _create_document(src.project_id, payload, db)
    audit(db, "run.document.correction", "run_cost_document", out["id"],
          {"corrects": src.id, "doc_number": number, "lines": len(body.lines)})
    db.commit()
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
    _guard_closed(db, doc, "changing this document")
    fields = body.model_dump(exclude_unset=True)
    _check_doc_type(fields.get("doc_type"))
    original = db.get(M.RunCostDocument, doc.corrects_document_id) if doc.corrects_document_id else None
    if ("company_id" in fields and original is not None and original.company_id
            and fields["company_id"] != original.company_id):
        raise HTTPException(422, "a correction is billed to the company its original was billed to")
    if "company_id" in fields and _guard_buyer_change(db, doc, fields["company_id"]):
        fields["company_source"] = "manual"
    held = _stock_before(db, [doc.id], new_company_id=fields.get("company_id"))
    before, after = {}, {}
    for field, value in fields.items():
        old = getattr(doc, field)
        if old != value:
            before[field], after[field] = old, value
            setattr(doc, field, value)
    _refuse_stock_loss(db, held, "this change")
    audit(db, "run.document.update", "run_cost_document", doc.id,
          {"before": before, "after": after})
    db.commit()
    return run_actuals.document_json(doc, db=db)


@router.delete("/run-documents/{doc_id}")
def delete_document(doc_id: int, force: bool = False, db: Session = Depends(get_db)):
    """Refuses while the document still has live lines unless ?force=true — a
    financial record should not vanish by accident."""
    doc = _doc(db, doc_id)
    _guard_closed(db, doc, "deleting this document")
    live = [li for li in doc.lines if li.voided_at is None]
    if live and not force:
        raise HTTPException(409, f"document has {len(live)} live lines; pass force=true to delete")
    # `force` waives the "it still has lines" guard, never the stock one: the
    # draws priced against these purchases outlive the document.
    hdrs = run_actuals.header_ids(db, doc.id)
    _guard_purchase_loss(db, [
        run_actuals.purchase_loss_of(db, li)
        for li in run_actuals.pooled_part_lines(db, live) if li.id not in hdrs
    ], "deleting this document")
    held = _stock_before(db, [doc.id])
    audit(db, "run.document.delete", "run_cost_document", doc.id,
          {"supplier": doc.supplier, "doc_number": doc.doc_number, "lines": len(doc.lines)})
    # A KSeF purchase imported as this document waits in the inbox again
    # (decision 0067), instead of pointing at a document that is gone.
    db.query(M.KsefInvoice).filter(M.KsefInvoice.document_id == doc.id).update(
        {"status": "new", "document_id": None}, synchronize_session=False)
    db.delete(doc)
    _refuse_stock_loss(db, held, "deleting this document")
    db.commit()
    return {"deleted": doc_id}


# -------------------------------------------------------------------- lines

@router.post("/run-documents/{doc_id}/lines")
def add_line(doc_id: int, body: LineIn, db: Session = Depends(get_db)):
    doc = _doc(db, doc_id)
    _guard_closed(db, doc, "adding a position to this document")
    body = _overhead_whole(body)
    _check_line(body)
    _check_allocate(body.plan_key, body.allocate)
    _check_excluded(body.allocate, body.exclude_reason)
    _check_cancelled(body.plan_key, body.allocate, body.run_id, body.project_id)
    _check_transformation(db, body.plan_key, body.transformation_id, body.run_id,
                          body.project_id, body.allocate)
    pos = body.position or (max([li.position for li in doc.lines], default=-1) + 1)
    held = _stock_before(db, [doc.id], extra=[(body, doc)])
    d = body.model_dump()
    d["position"] = pos
    li = M.RunCostLine(document_id=doc.id, **d)
    db.add(li)
    _refuse_stock_loss(db, held, "this position")
    audit(db, "run.cost_line.add", "run_cost_line", li.id, {
        "document_id": doc.id, "step": li.plan_key, "label": li.label,
        "qty": li.qty, "unit_price": li.unit_price,
    })
    db.commit()
    return run_actuals.line_json(li, doc, db=db)


@router.patch("/run-documents/{doc_id}/lines")
def edit_lines(doc_id: int, body: LinesBatchIn, db: Session = Depends(get_db)):
    """Apply a whole document's line edits at once, or none of them.

    Order matters: everything is validated and the stock guard is run on the
    batch's NET effect BEFORE a single row is touched, so a refusal leaves the
    document exactly as it was.
    """
    doc = _doc(db, doc_id)
    _guard_closed(db, doc, "editing this document")
    by_id = {li.id: li for li in doc.lines if li.voided_at is None}
    held = _stock_before(db, [doc.id], new_company_id=(body.document.model_dump(exclude_unset=True).get("company_id")
                                                        if body.document is not None else None),
                         extra=[(c, doc) for c in body.creates] + [
        (SimpleNamespace(**{k: getattr(e, k, None) if getattr(e, k, None) is not None else getattr(by_id[e.id], k)
                            for k in ("plan_key", "component_id", "mpn", "lcsc")}), doc)
        for e in body.updates if e.id in by_id])
    body.creates = [_overhead_whole(c) for c in body.creates]

    touched = {e.id for e in body.updates} | set(body.deletes)
    missing = sorted(touched - by_id.keys())
    if missing:
        raise HTTPException(404, f"no live line {missing} on this document")

    for e in body.updates:
        _check_line(e)
        # The effective values: a patch may change either half, or neither.
        f = e.model_dump(exclude_unset=True)
        _cur = by_id[e.id]
        _check_allocate(f.get("plan_key", _cur.plan_key), f.get("allocate", _cur.allocate))
        _check_excluded(f.get("allocate", _cur.allocate),
                        f.get("exclude_reason", _cur.exclude_reason))
        _check_cancelled(f.get("plan_key", _cur.plan_key), f.get("allocate", _cur.allocate),
                         f.get("run_id", _cur.run_id), f.get("project_id", _cur.project_id))
        _one_destination(f, _cur)
        _check_transformation(db, f.get("plan_key", _cur.plan_key),
                              f.get("transformation_id", _cur.transformation_id),
                              f.get("run_id", _cur.run_id), f.get("project_id", _cur.project_id),
                              f.get("allocate", _cur.allocate))
    for c in body.creates:
        _check_line(c)
        _check_allocate(c.plan_key, c.allocate)
        _check_excluded(c.allocate, c.exclude_reason)
        _check_cancelled(c.plan_key, c.allocate, c.run_id, c.project_id)
        _check_transformation(db, c.plan_key, c.transformation_id, c.run_id, c.project_id,
                              c.allocate)

    # One netted guard for the batch. A deleted line, or one that leaves the
    # pool, contributes its whole quantity as a loss; a re-key moves stock from
    # one key to another and nets out when something moves the other way.
    changes: list[dict] = []
    for e in body.updates:
        li = by_id[e.id]
        f = e.model_dump(exclude_unset=True)
        leaves = f.get("run_id") is not None or f.get("allocate") == run_actuals.EXCLUDED
        ch: dict = {"line": li, "qty": None if leaves else f.get("qty"),
                    "pooled_after": not leaves}
        for k in ("component_id", "mpn", "lcsc"):
            if k in f:
                ch[k] = f[k]
        changes.append(ch)
    for line_id in body.deletes:
        changes.append({"line": by_id[line_id], "pooled_after": False})
        for kid in _descendants(db, line_id):
            if kid.voided_at is None:
                changes.append({"line": kid, "pooled_after": False})
    short = run_actuals.batch_purchase_losses(db, changes)
    if short:
        named = ", ".join(f"{s_.get('label') or s_.get('mpn')} short {s_.get('short'):.0f}"
                          for s_ in short[:3])
        more = f" and {len(short) - 3} more" if len(short) > 3 else ""
        raise HTTPException(409, {
            "error": f"these edits would leave component draws with no purchase behind "
                     f"them: {named}{more}. Remove or reduce those draws first, or record "
                     f"a stock adjustment for the difference.",
            "shortages": short,
        })
    # A new buyer, checked before anything is written (decision 0064).
    doc_fields = body.document.model_dump(exclude_unset=True) if body.document is not None else {}
    if "company_id" in doc_fields and not _guard_buyer_change(db, doc, doc_fields["company_id"]):
        doc_fields.pop("company_id")

    changed: list[dict] = []
    for e in body.updates:
        li = by_id[e.id]
        f = _one_destination(e.model_dump(exclude_unset=True), li)
        f.pop("id", None)
        if "run_id" in f or "project_id" in f:
            _check_destination(db, f.get("run_id", li.run_id), f.get("project_id", li.project_id))
        before, after = {}, {}
        for field, value in f.items():
            if getattr(li, field) != value:
                before[field], after[field] = getattr(li, field), value
                setattr(li, field, value)
        if after:
            changed.append({"id": li.id, "before": before, "after": after})

    now = utcnow()
    voided: list[int] = []
    for line_id in body.deletes:
        for row in [by_id[line_id], *[k for k in _descendants(db, line_id) if k.voided_at is None]]:
            row.voided_at = now
            voided.append(row.id)

    # The header goes in the SAME transaction as its positions. A supplier or a
    # date corrected in one call and the lines in another leaves a window where
    # the document says one thing and its money another.
    doc_before, doc_after = {}, {}
    if "company_id" in doc_fields:
        doc_fields["company_source"] = "manual"
    if body.document is not None:
        for field, value in doc_fields.items():
            if getattr(doc, field) != value:
                doc_before[field], doc_after[field] = getattr(doc, field), value
                setattr(doc, field, value)
        # A changed currency or date invalidates the pinned rate: it was resolved
        # from NBP table A at the OLD date, so leaving it would price the
        # document at a rate that never applied to it.
        if ("currency" in doc_after or "doc_date" in doc_after) \
                and (doc.currency or "USD").upper() != "USD" and doc.doc_date \
                and "fx_rate_usd" not in doc_after:
            try:
                res = nbp.resolve_for_document(db, doc.currency, doc.doc_date)
                doc_before["fx_rate_usd"], doc_after["fx_rate_usd"] = doc.fx_rate_usd, res["rate_usd"]
                doc.fx_rate_usd = res["rate_usd"]
            except nbp.NbpError as exc:
                raise HTTPException(502, f"could not resolve an NBP rate: {exc}") from exc

    pos = max([li.position for li in doc.lines], default=-1)
    created: list[int] = []
    for c in body.creates:
        pos += 1
        d = c.model_dump()
        d["position"] = d.get("position") or pos
        row = M.RunCostLine(document_id=doc.id, **d)
        db.add(row)
        db.flush()
        created.append(row.id)

    _refuse_stock_loss(db, held, "this edit")
    audit(db, "run.document.lines.batch", "run_cost_document", doc.id,
          {"document": {"before": doc_before, "after": doc_after} if doc_after else None,
           "updated": changed, "voided": voided, "created": created})
    db.commit()
    db.expire(doc, ["lines"])
    return {"updated": len(changed), "voided": len(voided), "created": len(created),
            "header_changed": sorted(doc_after), "document": run_actuals.document_json(doc, db=db)}


@router.get("/run-cost-lines/{line_id}/supplier-breakdown")
def supplier_breakdown(line_id: int, db: Session = Depends(get_db)):
    """What the supplier's own BOM says this parts lump bought.

    A PLAN, never a write. It is loaded into the split dialog and applied
    through the ordinary split, so there is exactly one path that turns a lump
    into positions — a second endpoint that also wrote them would be free to
    drift from the guards `split` carries.
    """
    return supplier_parts.itemise(db, _line(db, line_id))


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
    res = split_line_core(line_id, body, db)
    db.commit()
    # `expire_on_commit=False` + children added via `db.add` means `doc.lines` is
    # still the pre-split collection, so the parent would serialize as a leaf.
    doc = _doc(db, res["document_id"])
    db.expire(doc, ["lines"])
    return {
        "parent_id": res["parent_id"],
        "created": res["created"],
        "residual": res["residual"],
        "document": run_actuals.document_json(doc, db=db),
    }


def split_line_core(line_id: int, body: SplitIn, db: Session) -> dict:
    """The split itself, every guard included, written but NOT committed —
    for a caller that wraps it in a larger write ("Record assembly", decision
    0072). Returns `{parent_id, document_id, created, created_ids, residual}`."""
    parent = _line(db, line_id)
    if parent.voided_at is not None:
        raise HTTPException(409, "line is voided")
    if not body.children:
        raise HTTPException(422, "no children given")
    if _depth(db, parent) + 1 > MAX_SPLIT_DEPTH:
        raise HTTPException(422, f"split depth would exceed {MAX_SPLIT_DEPTH}")
    if run_actuals.is_stock(parent) and not body.allow_parts:
        raise HTTPException(422, "part lines feed the component pool, which already splits them by "
                                 "consumption — splitting one per run double counts. Pass "
                                 "allow_parts=true only for parts bought for one specific batch.")
    doc = _doc(db, parent.document_id)
    _guard_closed(db, doc, "splitting this position")
    existing = [c for c in db.query(M.RunCostLine)
                .filter(M.RunCostLine.parent_line_id == parent.id,
                        M.RunCostLine.voided_at.is_(None)).all()]
    by_id = {c.id: c for c in existing}
    # The part each share will name, as the code below gives it: a credit (a
    # negative share) is compared like a new position (decision 0044).
    held = _stock_before(db, [doc.id], extra=[(SimpleNamespace(
        plan_key=c.plan_key,
        component_id=c.component_id if c.component_id is not None else by_id.get(c.id, parent).component_id,
        mpn=c.mpn or by_id.get(c.id, parent).mpn, lcsc=c.lcsc or by_id.get(c.id, parent).lcsc), doc)
        for c in body.children])
    named = {child.id for child in body.children if child.id is not None}
    unknown = named - set(by_id)
    if unknown:
        raise HTTPException(422, f"line(s) {sorted(unknown)} are not live children of {parent.id}")
    if existing and body.replace:
        for c in existing:
            if c.id in named:
                continue
            c.voided_at = utcnow()
            gone = [c] + list(_descendants(db, c.id))
            for d in gone[1:]:
                d.voided_at = utcnow()
            # A voided line pays for nothing: its whole-step links go with it.
            for k in db.query(M.CostLineStepKey).filter(M.CostLineStepKey.line_id.in_([x.id for x in gone])).all():
                db.delete(k)
        existing = [c for c in existing if c.id in named]

    made: list[M.RunCostLine] = []
    pos = max([li.position for li in doc.lines], default=-1)
    for child in body.children:
        _check_line(child)
        if child.allocate == run_actuals.OVERHEAD:
            # A company overhead share names nothing else (decision 0068).
            child = child.model_copy(update=_one_destination(
                {"allocate": child.allocate, "overhead_category": child.overhead_category}))
        _check_allocate(child.plan_key or parent.plan_key, child.allocate)
        _check_excluded(child.allocate, child.exclude_reason)
        _check_destination(db, child.run_id, child.project_id)
        _check_cancelled(child.plan_key or parent.plan_key, child.allocate, child.run_id,
                         child.project_id)
        _check_transformation(db, child.plan_key or parent.plan_key, child.transformation_id,
                              child.run_id, child.project_id, child.allocate)
        qty, unit = child.qty, child.unit_price
        if child.amount is not None:
            qty, unit = 1.0, child.amount
        if child.id is not None:
            # Update in place: everything the dialog edits, nothing it cannot
            # see (`external_line_id`, the plan link, `position`).
            row = by_id[child.id]
            row.basis = child.basis or row.basis
            row.label = child.label or row.label
            row.qty, row.unit_price = qty, unit
            row.allocate = child.allocate or "none"
            row.run_id, row.project_id = child.run_id, child.project_id
            # The dialog states the whole destination; a client that does not
            # know the field keeps the share's aim unless it sends it elsewhere.
            if "transformation_id" in child.model_fields_set:
                row.transformation_id = child.transformation_id
            elif child.run_id is not None or child.project_id is not None \
                    or (child.allocate or "none") != "none":
                row.transformation_id = None
            if child.component_id is not None:
                row.component_id = child.component_id
            row.mpn, row.lcsc = child.mpn or row.mpn, child.lcsc or row.lcsc
            row.description = child.description or row.description
            row.plan_key = child.plan_key
            row.plan_kind = child.plan_kind or row.plan_kind
            row.plan_ref = child.plan_ref or row.plan_ref
            row.notes = child.notes
            row.exclude_reason = child.exclude_reason
            row.overhead_category = child.overhead_category if row.allocate == run_actuals.OVERHEAD else ""
            continue
        pos += 1
        made.append(M.RunCostLine(
            document_id=doc.id, parent_line_id=parent.id, position=pos,
            basis=child.basis or parent.basis,
            label=child.label or parent.label, qty=qty, unit_price=unit,
            currency=parent.currency,  # one currency per family, so residual is exact
            allocate=child.allocate or "none",
            run_id=child.run_id, project_id=child.project_id,
            transformation_id=child.transformation_id,
            component_id=child.component_id if child.component_id is not None else parent.component_id,
            mpn=child.mpn or parent.mpn, lcsc=child.lcsc or parent.lcsc,
            description=child.description, plan_key=child.plan_key,
            plan_kind=child.plan_kind, plan_ref=child.plan_ref, notes=child.notes,
            exclude_reason=child.exclude_reason,
            overhead_category=child.overhead_category if child.allocate == run_actuals.OVERHEAD else "",
        ))

    # Splitting a PART line moves stock: the parent becomes a header and stops
    # being a purchase, the children become the purchases. Whatever the children
    # do not carry back into the pool — a share charged to a run, an `excluded`
    # share, or simply a smaller quantity — is stock the pool loses.
    if run_actuals.is_stock(parent) and run_actuals.pooled_part_lines(db, [parent]):
        back = sum(c.qty or 0.0 for c in existing + made
                   if run_actuals.is_stock(c) and c.run_id is None
                   and (c.allocate or "none") != run_actuals.EXCLUDED
                   and c.component_id == parent.component_id
                   and (c.mpn or "") == (parent.mpn or ""))
        _guard_purchase_loss(db, [run_actuals.purchase_loss_of(db, parent, qty=back)],
                             "this split")

    parent_amount = run_actuals.effective_qty(parent, doc, db) * (parent.unit_price or 0)
    child_amount = sum(run_actuals.effective_qty(c, doc, db) * (c.unit_price or 0)
                       for c in existing + made)
    # No tolerance beyond float noise. It was half a cent, while the register
    # counts ANY excess as over-allocated money, so splits the API accepted
    # showed up there as $0.0005 nobody could explain (2026-09-24). The dialog
    # rounds its calculated shares DOWN so they never overshoot.
    if child_amount > parent_amount + 1e-6:
        raise HTTPException(409, f"children total {child_amount:.4f} exceeds the position's "
                                 f"{parent_amount:.6f} {parent.currency or doc.currency} by "
                                 f"{child_amount - parent_amount:.6f} — balance the last share")
    for c in made:
        db.add(c)
    db.flush()
    # Decisions 0060/0061: a child keeps the step clicks its parent paid for,
    # unless it is charged to another batch than the parent.
    parent_links = [srid for (srid,) in db.query(M.CostLineStep.step_run_id).filter_by(line_id=parent.id).all()]
    parent_dest = run_actuals.line_destination(parent, doc)
    # So does a whole-step link (decision 0074). The parent keeps its own: a
    # header is valued at zero, so its links move no money, and it stays the
    # one source for a later re-split, at any depth.
    parent_keys = [(k.run_id, k.step_key) for k in db.query(M.CostLineStepKey).filter_by(line_id=parent.id).all()]
    # A whole-step link means every click of the step, the ones recorded since
    # the parent became a header too (a header is no charged line, so it was
    # never linked to them).
    from ..services import twins as _twins

    for rid, key in parent_keys:
        parent_links += _twins.step_clicks(db, rid, key)
    parent_links = sorted(set(parent_links))
    for ch in made:
        if (parent_links or parent_keys) and run_actuals.line_destination(ch, doc) == parent_dest:
            for srid in parent_links:
                db.add(M.CostLineStep(line_id=ch.id, step_run_id=srid))
            for rid, key in parent_keys:
                db.add(M.CostLineStepKey(line_id=ch.id, run_id=rid, step_key=key))
    db.flush()
    audit(db, "run.cost_line.split", "run_cost_line", parent.id, {
        "document_id": doc.id, "label": parent.label, "parent_amount": round(parent_amount, 4),
        "children": [{"id": c.id, "label": c.label, "run_id": c.run_id,
                      "project_id": c.project_id, "amount": round(
                          run_actuals.effective_qty(c, doc, db) * (c.unit_price or 0), 4)}
                     for c in made],
        "updated": sorted(named),
        "replaced": body.replace, "residual": round(parent_amount - child_amount, 4),
    })
    # A re-split may void or cut a child that is a lot, and the parent stops
    # being one (decision 0073).
    _refuse_stock_loss(db, held, "this split")
    return {"parent_id": parent.id, "document_id": doc.id, "created": len(made),
            "created_ids": [c.id for c in made], "residual": round(parent_amount - child_amount, 4)}


@router.patch("/run-cost-lines/{line_id}")
def update_line(line_id: int, body: LinePatch, db: Session = Depends(get_db)):
    li = _line(db, line_id)
    _guard_closed(db, _doc(db, li.document_id), "editing this position")
    _check_line(body)
    fields = body.model_dump(exclude_unset=True)
    _check_allocate(fields.get("plan_key", li.plan_key), fields.get("allocate", li.allocate))
    _check_excluded(fields.get("allocate", li.allocate),
                    fields.get("exclude_reason", li.exclude_reason))
    _check_cancelled(fields.get("plan_key", li.plan_key), fields.get("allocate", li.allocate),
                     fields.get("run_id", li.run_id), fields.get("project_id", li.project_id))
    _one_destination(fields, li)
    _check_transformation(db, fields.get("plan_key", li.plan_key),
                          fields.get("transformation_id", li.transformation_id),
                          fields.get("run_id", li.run_id), fields.get("project_id", li.project_id),
                          fields.get("allocate", li.allocate))
    # A smaller quantity, or a different pool identity, takes stock away from
    # the key this line was feeding. Charging it to a run does too: a part line
    # with a `run_id` leaves the pool entirely.
    if run_actuals.pooled_part_lines(db, [li]) and (
        "qty" in fields or "component_id" in fields or "mpn" in fields
        or "lcsc" in fields or fields.get("run_id") is not None
        or fields.get("allocate") == run_actuals.EXCLUDED
    ):
        loses_all = fields.get("run_id") is not None or fields.get("allocate") == run_actuals.EXCLUDED
        _guard_purchase_loss(db, [run_actuals.purchase_loss_of(
            db, li,
            qty=0.0 if loses_all else fields.get("qty"),
            component_id=fields.get("component_id", ...),
            mpn=fields.get("mpn"), lcsc=fields.get("lcsc"),
        )], "this edit")
    if "run_id" in fields or "project_id" in fields:
        _check_destination(db,
                           fields.get("run_id", li.run_id),
                           fields.get("project_id", li.project_id))
    held = _stock_before(db, [li.document_id], extra=[(SimpleNamespace(
        **{k: fields.get(k, getattr(li, k)) for k in ("plan_key", "component_id", "mpn", "lcsc")}),
        db.get(M.RunCostDocument, li.document_id))])
    before, after = {}, {}
    for field, value in fields.items():
        old = getattr(li, field)
        if old != value:
            before[field], after[field] = old, value
            setattr(li, field, value)
    _refuse_stock_loss(db, held, "this edit")
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
    _guard_closed(db, _doc(db, li.document_id), "voiding this position")
    kids = [c for c in _descendants(db, li.id) if c.voided_at is None]
    hdrs = run_actuals.header_ids(db)
    _guard_purchase_loss(db, [
        run_actuals.purchase_loss_of(db, row)
        for row in run_actuals.pooled_part_lines(db, [li, *kids]) if row.id not in hdrs
    ], "voiding this line")
    held = _stock_before(db, [li.document_id])
    now = utcnow()
    for row in [li, *kids]:
        row.voided_at = now
    _refuse_stock_loss(db, held, "voiding this line")
    audit(db, "run.cost_line.void", "run_cost_line", li.id,
          {"step": li.plan_key, "label": li.label, "qty": li.qty, "unit_price": li.unit_price,
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

def _stock_view(db: Session, request: Request | None) -> int | None:
    """The one company a stock view shows (decision 0064): the header
    switcher's company when it selects exactly one and each company keeps its
    own stock; else None, all stock."""
    scope = company_svc.scope_ids(db, request)
    return run_actuals.stock_scope(db, scope[0]) if len(scope) == 1 else None


@router.get("/parts-stock")
def parts_stock(request: Request = None, db: Session = Depends(get_db)):
    """Every part measured both ways: what JLC physically holds at market price,
    and what the cost pool says was paid for the unconsumed remainder.

    A part JLC holds that the pool has never seen (`state: "jlc_only"`) means the
    purchase invoice is missing.
    """
    return run_actuals.parts_stock(db, company_id=_stock_view(db, request))


@router.get("/invoices")
def invoice_register(request: Request = None, db: Session = Depends(get_db)):
    """Every supplier document with where its money went, plus the company-wide
    reconciliation: unassigned money, documents whose lines don't add up, and
    whether the component pool balances."""
    scope = company_svc.scope_ids(db, request)   # the header switcher (decision 0063)
    return run_actuals.invoice_register(
        db, company_ids=scope if company_svc.narrows(db, scope) else None)


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
         # A step's draw goes with its step, and cannot be removed on its own.
         "step_run_id": c.step_run_id, "transformation_id": c.transformation_id,
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
                 request: Request = None, db: Session = Depends(get_db)):
    """One part's full event timeline with running balance — how the stock moved,
    verifiable at any point in time (user requirement 2026-07-28)."""
    if component_id is None and not mpn and not lcsc:
        raise HTTPException(422, "give at least one of component_id, mpn, lcsc")
    return run_actuals.component_ledger(db, component_id, mpn, lcsc,
                                        company_id=_stock_view(db, request))


def _refuse_crafted(run: M.ProductionRun) -> None:
    """Decision 0060: a crafted batch takes parts only through its process
    steps, so every draw says which step used it. A part draw typed on the
    batch would be a material use no step knows about."""
    if run.process_version_id:
        raise HTTPException(409, f"{run.label} is crafted: its parts are drawn by its process steps "
                                 "(Batch → Process). Add the part as an input of a step in the "
                                 "project's process (decision 0060).")


@router.post("/runs/{run_id}/consumption")
def add_consumption(run_id: int, body: ConsumptionIn, db: Session = Depends(get_db)):
    run = _run(db, run_id)
    _refuse_crafted(run)
    # A draw cannot take stock the pool never had (user decision 2026-07-28,
    # hard block): the fix is the missing invoice, an adjustment, or an override.
    shortages = run_actuals.check_shortages(db, [{
        "component_id": body.component_id, "mpn": body.mpn, "lcsc": body.lcsc,
        "qty": body.qty, "date": body.consumed_at or run.run_date or "",
    }], company_id=run_actuals.run_scope(db, run))
    if shortages:
        raise HTTPException(409, {"error": "insufficient stock for this draw",
                                  "shortages": shortages})
    # As of the CONSUMPTION date, never "today": a 2024 draw must not be priced
    # from purchases made in 2026 (same rule as consume_from_bom). Resolved by
    # identity OVERLAP, not by `_key`, so a caller who knows only an MPN still
    # meets purchases filed under a component id — see `resolve_pool_identity`.
    as_of = body.consumed_at or run.run_date or None
    pool = run_actuals.resolve_pool_identity(
        db, body.component_id, body.mpn, body.lcsc, as_of=as_of,
        company_id=run_actuals.run_scope(db, run))
    unit = body.unit_cost_usd
    if unit is None:
        unit = pool["avg_usd"] if pool else 0.0
    # Decision 0073: with lot pricing on, the draw comes from its lots, oldest
    # first, at their cost — a typed price does not override what was paid.
    from ..services import lots as lots_svc

    want = {"component_id": (pool or {}).get("component_id") or body.component_id,
            "mpn": (pool or {}).get("mpn") or body.mpn, "lcsc": (pool or {}).get("lcsc") or body.lcsc,
            "qty": body.qty, "label": body.mpn or body.lcsc or str(body.component_id)}
    uncovered = lots_svc.fifo_price(db, [want], as_of=body.consumed_at or run.run_date or "",
                                    company_id=run_actuals.run_scope(db, run))
    if uncovered:
        raise HTTPException(409, {"error": f"{lots_svc.short_text(uncovered)} — enter the missing purchase "
                                           "(decision 0073)", "uncovered": uncovered})
    if want.get("bindings"):
        unit = want["unit_cost_usd"]
    c = M.ComponentConsumption(
        run_id=run_id,
        component_id=(pool or {}).get("component_id") or body.component_id,
        mpn=(pool or {}).get("mpn") or body.mpn,
        lcsc=(pool or {}).get("lcsc") or body.lcsc,
        qty=body.qty, unit_cost_usd=unit, basis=body.basis,
        consumed_at=body.consumed_at or run.run_date or "", note=body.note,
    )
    db.add(c)
    if want.get("bindings"):
        db.flush()
        lots_svc.bind(db, c, want)
    db.flush()
    audit(db, "run.consumption.add", "component_consumption", c.id, {
        "run_id": run_id, "qty": c.qty, "unit_cost_usd": c.unit_cost_usd, "basis": c.basis,
    })
    db.commit()
    return {"id": c.id, "unit_cost_usd": c.unit_cost_usd, "basis": c.basis}


@router.put("/runs/{run_id}/consumption/for-part")
def set_used_qty(run_id: int, body: ConsumptionIn, db: Session = Depends(get_db)):
    """Set how much of ONE part this batch used, as an absolute figure.

    The end-of-production workflow: type what was actually consumed against each
    BOM row and the batch is done. Idempotent by design — sending the same
    quantity twice changes nothing, and correcting a number later is the same
    call again, so a mistake never needs a compensating adjustment.

    Why absolute and not a delta: a delta needs the operator to know the current
    value, and the whole point is that they are reading a number off the shelf,
    not off the screen. It EDITS the existing row rather than adding a second
    one, so the part keeps one draw and one lot binding.

    Refuses a part JLC itself reported (`basis='measured'`). That figure is the
    supplier's measurement of its own consigned stock
    ([0034](../../../docs/decisions/0034-stock-moves-when-the-supplier-says-so.md));
    overwriting it by hand would put a guess where an observation is. Parts
    bought elsewhere — enclosures, antennas, cartons — are exactly the ones no
    supplier reports, and are what this is for.
    """
    _refuse_crafted(_run(db, run_id))
    run = _run(db, run_id)
    qty = max(body.qty or 0.0, 0.0)
    keys = set(run_actuals._identity_keys(body.component_id, body.mpn, body.lcsc))
    if not keys:
        raise HTTPException(422, "name the part: component_id, mpn or lcsc")
    live = [c for c in run_actuals.live_consumption(db, run_id=run_id).all()
            if keys & set(run_actuals._identity_keys(c.component_id, c.mpn or "", c.lcsc or ""))]
    measured = [c for c in live if c.basis == "measured"]
    if measured:
        raise HTTPException(409, {
            "error": "JLC reported this draw itself — it is a measurement, not ours to retype",
            "consumption_ids": [c.id for c in measured],
            "qty": sum(c.qty or 0 for c in measured),
            "hint": "correct it by reversing the import that wrote it"})
    mine = [c for c in live if c.basis != "measured"]
    if len(mine) > 1:
        raise HTTPException(409, {
            "error": f"{len(mine)} separate draws exist for this part on this batch, "
                     "so an absolute quantity is ambiguous",
            "consumption_ids": [c.id for c in mine],
            "hint": "delete the extras, then set the quantity once"})

    row = mine[0] if mine else None
    was = row.qty if row else 0.0
    if qty > was:
        # Only the INCREASE can overdraw; shrinking a draw always gives back.
        short = run_actuals.check_shortages(db, [{
            "component_id": body.component_id, "mpn": body.mpn, "lcsc": body.lcsc,
            "qty": qty - was, "date": body.consumed_at or run.run_date or "",
        }], company_id=run_actuals.run_scope(db, run))
        if short:
            raise HTTPException(409, {"error": "insufficient stock for this draw",
                                      "shortages": short})
    if qty <= 0:
        if row is None:
            return {"status": "unchanged", "qty": 0.0}
        audit(db, "run.consumption.delete", "component_consumption", row.id,
              {"run_id": run_id, "qty": row.qty, "reason": "used qty set to zero"})
        db.delete(row)
        db.commit()
        return {"status": "removed", "qty": 0.0}

    if row is None:
        as_of = body.consumed_at or run.run_date or None
        # ADOPT the pool entry's identity. Writing the caller's own spelling
        # would file the draw under a different key from the purchases and split
        # one part into two pool entries with two averages.
        pool = run_actuals.resolve_pool_identity(
            db, body.component_id, body.mpn, body.lcsc, as_of=as_of,
            company_id=run_actuals.run_scope(db, run))
        if pool is None:
            raise HTTPException(409, {
                "error": "no pool entry for that part, so there is nothing to draw from",
                "mpn": body.mpn, "lcsc": body.lcsc,
                "hint": "enter the purchase invoice first, or check the spelling"})
        unit = body.unit_cost_usd if body.unit_cost_usd is not None else pool["avg_usd"]
        from ..services import lots as lots_svc

        want = {"component_id": pool.get("component_id"), "mpn": pool.get("mpn") or body.mpn,
                "lcsc": pool.get("lcsc") or body.lcsc, "qty": qty,
                "label": body.mpn or body.lcsc or str(body.component_id)}
        uncovered = lots_svc.fifo_price(db, [want], as_of=as_of or "", company_id=run_actuals.run_scope(db, run))
        if uncovered:
            raise HTTPException(409, {"error": f"{lots_svc.short_text(uncovered)} — enter the missing purchase "
                                               "(decision 0073)", "uncovered": uncovered})
        if want.get("bindings"):
            unit = want["unit_cost_usd"]
        row = M.ComponentConsumption(
            run_id=run_id, component_id=pool.get("component_id"),
            mpn=pool.get("mpn") or body.mpn, lcsc=pool.get("lcsc") or body.lcsc,
            qty=qty, unit_cost_usd=unit, basis="manual",
            consumed_at=body.consumed_at or run.run_date or "", note=body.note)
        db.add(row)
        db.flush()
        if want.get("bindings"):
            lots_svc.bind(db, row, want)
        audit(db, "run.consumption.add", "component_consumption", row.id,
              {"run_id": run_id, "qty": qty, "unit_cost_usd": row.unit_cost_usd,
               "basis": "manual", "note": "counted at end of production"})
        db.commit()
        return {"status": "created", "id": row.id, "qty": qty,
                "unit_cost_usd": row.unit_cost_usd, "basis": row.basis}

    if abs(was - qty) < 1e-9:
        return {"status": "unchanged", "id": row.id, "qty": qty}
    # The unit cost stays as SNAPSHOTTED. It is what the pool averaged when the
    # draw was priced, and re-pricing on every correction would let a later
    # purchase rewrite what a closed batch paid. While lot pricing is on, or
    # when its price already is its lots' price, the draw is priced over its
    # OWN lots instead, which a later purchase cannot move.
    from ..services import lots as lots_svc

    # Decision 0073: a bound draw that grows takes the next lots oldest first,
    # one that shrinks gives back its newest bindings, and it is priced again.
    uncovered = lots_svc.resize_bound(db, row, qty, as_of=row.consumed_at or run.run_date or "",
                                      company_id=run_actuals.run_scope(db, run))
    if uncovered:
        raise HTTPException(409, {"error": f"{lots_svc.short_text(uncovered)} — enter the missing purchase "
                                           "(decision 0073)", "uncovered": uncovered})
    row.qty = qty
    was_basis = row.basis
    row.basis = "manual"
    if body.note:
        row.note = body.note[:500]
    audit(db, "run.consumption.update", "component_consumption", row.id,
          {"run_id": run_id, "before": {"qty": was, "basis": was_basis},
           "after": {"qty": qty, "basis": row.basis}})
    db.commit()
    return {"status": "updated", "id": row.id, "qty": qty,
            "was": was, "unit_cost_usd": row.unit_cost_usd, "basis": row.basis}


@router.post("/runs/{run_id}/consumption/from-bom")
def consume_bom(run_id: int, db: Session = Depends(get_db)):
    """Draw the run's whole BOM from the pool at the moving average, or from
    its lots oldest first while lot pricing is on (decision 0073)."""
    run = _run(db, run_id)
    res = run_actuals.consume_from_bom(db, run)
    if res.get("error"):
        # shortages ride along so the caller sees WHAT is missing, not just that
        # something is
        raise HTTPException(409, {"error": res["error"],
                                  "shortages": res.get("shortages") or [],
                                  "uncovered": res.get("uncovered") or []})
    audit(db, "run.consumption.from_bom", "production_run", run.id, res)
    db.commit()
    return res


@router.delete("/consumption/{cons_id}")
def delete_consumption(cons_id: int, db: Session = Depends(get_db)):
    c = db.get(M.ComponentConsumption, cons_id)
    if c is None:
        raise HTTPException(404, "consumption not found")
    if c.step_run_id or c.transformation_id:
        # A step that happened is history (decision 0059): its draw goes with it.
        raise HTTPException(409, "this draw belongs to a process step or a prepared part — "
                                 "correct the step, not the draw")
    if c.transfer_line_id:
        # The sender's side of an in-house transfer (decision 0064): alone it
        # would hand the receiver stock the sender never gave.
        raise HTTPException(409, "this draw is the sender's side of an in-house transfer — "
                                 "reverse the transfer on the Transfers page")
    audit(db, "run.consumption.delete", "component_consumption", cons_id,
          {"run_id": c.run_id, "qty": c.qty, "unit_cost_usd": c.unit_cost_usd})
    db.delete(c)
    db.commit()
    return {"deleted": cons_id}


class DrawCompanyIn(BaseModel):
    company_id: int
    dry_run: bool = True


@router.patch("/consumption/{cons_id}/company")
def set_draw_company(cons_id: int, body: DrawCompanyIn, db: Session = Depends(get_db)):
    """Name whose stock an UNCHARGED draw took (decision 0064) — a JLC
    warehouse pick or an external order's stock, which no batch links to a
    company. A charged draw takes its batch's company, and a transfer's draw
    its sender, so neither is set here.

    While each company keeps its own stock this is `transfers.cover_draws`:
    units bound to the other company's lot move by in-house transfer first, and
    the rest must be in the named company's stock on the draw's date."""
    from ..services import transfers

    c = db.get(M.ComponentConsumption, cons_id)
    if c is None or c.voided_at is not None:
        raise HTTPException(404, "consumption not found")
    if c.run_id or c.step_run_id or c.transformation_id or c.transfer_line_id:
        raise HTTPException(409, "only an uncharged draw is given a company by hand — a batch's "
                                 "draw takes the batch's company")
    company_svc.get(db, body.company_id)
    if c.company_id == body.company_id:
        return {"status": "unchanged", "company_id": c.company_id}
    per_company = run_actuals.stock_scope(db, body.company_id) is not None
    if body.dry_run:
        if per_company:
            return transfers.cover_draws(db, [c], body.company_id, dry_run=True)
        return {"dry_run": True, "receiver_id": body.company_id, "transfers": [], "shortages": []}
    actor = acting_name()
    with journal.batch(db, kind="draw.company", source_ref=f"cons:{c.id}", actor=actor) as h:
        if per_company:
            res = transfers.cover_draws(db, [c], body.company_id, actor=actor,
                                        note=f"draw {c.id} named by hand", dry_run=False)
        else:
            c.company_id = body.company_id
            db.flush()
            res = {"dry_run": False, "receiver_id": body.company_id, "transfers": [], "shortages": []}
    audit(db, "run.consumption.company", "component_consumption", c.id,
          {"company_id": body.company_id, "transfers": res.get("written", []), "batch_id": h["batch_id"]})
    db.commit()
    return {**res, "batch_id": h["batch_id"]}


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
         "charge_run_id": a.charge_run_id, "adjusted_at": a.adjusted_at, "note": a.note,
         "company_id": a.company_id}
        for a in rows
    ]


@router.post("/projects/{project_id}/stock-adjustments")
def add_adjustment(project_id: int, body: AdjustmentIn, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    if body.reason not in REASONS:
        raise HTTPException(422, f"reason must be one of {sorted(REASONS)}")
    charged = _run(db, body.charge_run_id) if body.charge_run_id is not None else None
    a = M.ComponentStockAdjustment(project_id=project_id, **body.model_dump())
    a.actor = acting_name()
    # Whose stock moves (decision 0064): stated, else derived — and fixed now,
    # because the pinned price below is read from that company's stock.
    if a.company_id is not None:
        company_svc.get(db, a.company_id)
        if charged is not None and charged.company_id and charged.company_id != a.company_id:
            # A batch's loss is a loss of the stock the batch draws from.
            raise HTTPException(422, f"{charged.label} draws from its own company's stock; "
                                     "a loss charged to it is that company's")
    else:
        a.company_id = company_svc.stock_company_for(db, a)
    # PIN the unit cost when the loss is charged to a batch (decision 0044).
    # NULL means "price it from the pool", and `run_actuals` resolved that
    # against the average as it stands ON EVERY READ — so a write-off kept being
    # re-priced by purchases made after it, and a 2024 attrition row was carrying
    # a 2026 average. The average AT THE ADJUSTMENT'S OWN DATE is what it should
    # always have been, and pinning it is what makes it stay.
    if a.unit_cost_usd is None and a.charge_run_id is not None:
        entry = run_actuals.resolve_pool_identity(
            db, a.component_id, a.mpn or "", a.lcsc or "",
            as_of=a.adjusted_at or None,
            company_id=run_actuals.stock_scope(db, a.company_id))
        a.unit_cost_usd = float((entry or {}).get("avg_usd") or 0.0)
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
    if (a.qty_delta or 0.0) > 0:
        # A positive adjustment is stock and a lot (decision 0073): deleting
        # it is a purchase loss, and the draws bound to it would hold a lot
        # that no longer exists. A transformation's output goes with its void.
        from ..services import lots as lots_svc

        if a.transformation_id or db.query(M.ProcessTransformation.id).filter(
                M.ProcessTransformation.output_adjustment_id == a.id,
                M.ProcessTransformation.voided_at.is_(None)).first():
            raise HTTPException(409, "this adjustment is a transformation's output — void the transformation "
                                     "instead (Stock → Prepared parts)")
        q, draws = lots_svc.bound_on(db, adjustment_ids=[a.id]).get(lots_svc._lot_key("A", a.id), (0.0, []))
        if q > lots_svc.CLOSED_EPS:
            raise HTTPException(409, f"draws {', '.join(f'#{d}' for d in draws[:4])} hold {q:g} of this "
                                     "adjustment's stock — reduce or void those draws first")
        _guard_purchase_loss(db, [{"component_id": a.component_id, "mpn": a.mpn or "", "lcsc": a.lcsc or "",
                                   "qty": a.qty_delta, "date": a.adjusted_at or "",
                                   "label": a.mpn or a.lcsc or f"adjustment {a.id}",
                                   "company_id": run_actuals.stock_scope(db, a.company_id)}],
                             "deleting this adjustment")
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
    # The stock of the company that owned the project on that day (0064).
    owner = company_svc.owner_on(db, project_id, as_of)
    pool = run_actuals.pool_state(db, project_id, as_of=as_of,
                                  company_id=run_actuals.stock_scope(db, owner.id if owner else None))
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
