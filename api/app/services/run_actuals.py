"""Post-factum production costs: what a run ACTUALLY cost, from supplier
documents entered after the fact.

The planned side already exists (`project_bom.run_effective` prices a run's BOM
from historical pricing at the run's date). This module is the other half: real
invoice lines, and the split of component purchases across runs.

Model (user decisions, 2026-07-27):

- Purchases go into a **cost pool**, not onto a run: JLC invoices are stockpile
  replenishment, so a purchase can never be booked straight to a batch. A
  `RunCostLine` with ``kind="part"`` and no ``run_id`` IS the pool; every other
  kind is a direct cost of its run.
- A run pays for what it **drew** from the pool (`ComponentConsumption`), valued
  at a **moving weighted average** — not FIFO, because JLC merges reels and never
  reports which lot went into a build, so lot-picking would be fiction.
- The goal is **splitting invoice cost, not matching JLC's stock counts**.
  Attrition is expected and first-class (`ComponentStockAdjustment`), optionally
  charged to a run so its per-device figure carries the real loss. A residual
  pool balance is normal.
- Everything is computed ON READ from append-only rows, like `run_effective`.
  Nothing here is stored.

Replay order is the EVENT date (`doc_date` / `consumed_at` / `adjusted_at`),
never insertion order — backfilling 2024 invoices in 2026 must not change the
average a 2024 run already paid.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from . import companies as _companies  # also registers `stamp_stock` (decision 0064)
from . import cost_steps, fx
from .project_bom import display_currency, run_pricing_date

# Money that is STOCK is identified by its production STEP, not by a second
# `kind` field typed beside it (decision 0047). `cost_steps.PART_STEPS` is the
# one definition — `parts:pool`, `parts:prepaid`, `parts:attrition` and
# `pcba:parts` — and `IS_STOCK` is how it reads inside a SQLAlchemy filter.
#
# `kind` used to say this, and was free to disagree with the step beside it. It
# did, on 12 rows. The step is the finer of the two and the bucket is derivable
# from it (`cost_steps.kind_of`), so the bucket is derived and the column is
# gone.
IS_STOCK = M.RunCostLine.plan_key.in_(tuple(cost_steps.PART_STEPS))
NOT_STOCK = M.RunCostLine.plan_key.notin_(tuple(cost_steps.PART_STEPS))


def is_stock(li: M.RunCostLine) -> bool:
    """The in-Python twin of `IS_STOCK`, for a row already in hand."""
    return cost_steps.is_stock_step(li.plan_key or "")
# `allocate` values that spread a non-part line over the same document's parts.
# Deliberately NOT gated on `kind`: freight and duty are the common cases, but a
# per-unit surcharge printed as its own position is the same thing — ITALTRONIC
# bills the digital print on an enclosure and its one-off print tooling as
# separate lines, and the MRP (correctly) carries both inside the enclosure's unit
# cost, because neither is stock in its own right. The operator's explicit
# `allocate` choice is the signal; the kind is only a description.
SPREAD = ("by_value", "by_qty")
# `allocate` value meaning "recorded so the document reconciles, charged to nobody
# on purpose". Reclaimable VAT and already-pooled prepaid components.
EXCLUDED = "excluded"
# `allocate` value meaning "this line's money is STOCK — it belongs to the shared
# pool, and somebody said so" (decision 0045).
#
# It behaves exactly like `none` in every money path; the whole of its job is to
# be the difference between the two things `none` used to mean. A line with no
# run, no project and `allocate="none"` resolved to `pool` when its kind happened
# to be `part` and to `unassigned` — money nobody pays for — otherwise. One
# stored value, two outcomes, decided by a field the operator was not being asked
# about. `POOLED` says it outright, so "nobody has decided yet" stops being
# spelled the same way as "it goes to stock".
POOLED = "pooled"
# `allocate` value meaning "a cost of the COMPANY, not of any product"
# (decision 0068): leasing, telephone, software, accounting. The document's
# buyer carries it, under the position's `overhead_category`.
OVERHEAD = "overhead"
OVERHEAD_CATEGORIES = {
    "leasing": "Leasing", "telecom": "Phone and internet", "software": "Software and IT services",
    "accounting": "Accounting", "office": "Office", "travel": "Travel", "car": "Car and fuel",
    "insurance": "Insurance", "bank": "Bank fees", "rent": "Rent", "marketing": "Marketing",
    "training": "Training", "other": "Other",
}


def live_consumption(db: Session, **filters):
    """Every draw that still counts — the ONE place the void filter is written.

    A draw is retired by VOIDING it, never by deleting it, so an import that
    superseded a BOM forecast can be reversed and put the forecast back. That
    only works if every reader agrees on what "live" means: a single missed
    `voided_at IS NULL` produces a run charged for a draw the lot layer has
    already released, and both conservation identities still pass — the exact
    failure class that let $14,443 sit in `excluded` unnoticed.

    So readers call this, not `db.query(M.ComponentConsumption)`. Grepping the
    raw query is then a reliable audit: the only legitimate uses left are writes
    and the void/unvoid paths themselves.
    """
    q = db.query(M.ComponentConsumption).filter(M.ComponentConsumption.voided_at.is_(None))
    return q.filter_by(**filters) if filters else q


def stock_scope(db: Session, company_id: int | None) -> int | None:
    """The company a replay or a stock guard is scoped to (decision 0064).

    `company_id` while each company keeps its own stock, else None: one pool for
    both, as before. Every caller that prices a draw or guards one goes through
    here, so turning `stock_per_company` on is the one switch."""
    return company_id if (company_id and settings.stock_per_company) else None


def run_scope(db: Session, run: M.ProductionRun | None) -> int | None:
    """`stock_scope` for the company that made a batch."""
    return stock_scope(db, run.company_id if run is not None else None)


def project_scope(db: Session, project_id: int | None, on: str | None = None) -> int | None:
    """`stock_scope` for the company that owned a project on a day."""
    if not settings.stock_per_company or not project_id:
        return None
    owner = _companies.owner_on(db, project_id, on)
    return owner.id if owner else None


def event_company(kind: str, row, doc_by_id: dict) -> int | None:
    """Whose stock a pool event moves: the buyer of a purchase, the company
    stamped on a draw or an adjustment."""
    if kind == "buy":
        doc = doc_by_id.get(row.document_id)
        return doc.company_id if doc is not None else None
    return getattr(row, "company_id", None)


def _round(v: float | None) -> float | None:
    return None if v is None else round(v + 0.0, 4)


def _key(row) -> str:
    """Pool identity for a part: component_id when known, else MPN, else LCSC.

    The MPN is normalised to alphanumerics (`_strip`) because distributors punctuate
    the same part differently — Mouser prints Molex `146153-0050`, DigiKey and the
    MRP print `1461530050`. Keying on the raw string would split one antenna into
    two pool entries with two averages, and neither would match a BOM draw.
    """
    if getattr(row, "component_id", None):
        return f"c{row.component_id}"
    if getattr(row, "mpn", ""):
        return f"m{_strip(row.mpn)}"
    if getattr(row, "lcsc", ""):
        return f"l{_strip(row.lcsc)}"
    return "?"


# ------------------------------------------------------------------ payloads

def planned_units(run: M.ProductionRun) -> int:
    """What we ORDERED, and therefore what a supplier bills us for.

    Deliberately NOT `good_units`. The two answer different questions and were
    conflated until 2026-09-18:

    - `good_units` is what PASSED. It is the divisor for per-device cost — how
      much each surviving device cost us
      ([0030](../../../docs/decisions/0030-good-units-are-counted-not-typed.md)).
    - `planned_units` is what we ORDERED. It is the multiplier for a supplier's
      per-board rate. An assembler is paid for the boards they assembled, not
      for the devices that later passed our test — the yield loss is ours.

    Using the first where the second belongs made a LIFTECH invoice for 350
    boards reconcile to 349, opening a $1.31 hole in the register that refused
    every JLC import until it was found (user decision 2026-09-18: "we ordered x
    units and will pay for x units").
    """
    return int(run.plan_qty or run.qty or 0)


def effective_qty(li: M.RunCostLine, doc: M.RunCostDocument | None = None,
                  db: Session | None = None) -> float:
    """Quantity the money is actually charged on.

    A `per_device` line states a rate per board ("5 PLN/board"), so its real
    quantity is `qty x the run's PLANNED units`. Without this, a document whose
    printed total is the batch total looks unreconciled — the reconciliation
    would compare 1750 PLN against a bare 5.0.

    An assembler who bills several batches on one invoice is handled by SPLITTING
    the position (`POST /api/run-cost-lines/{id}/split`), one child per run, each
    scaled by its own batch. Splitting is the mechanism for merged invoices; this
    function never guesses which batches a line covers.
    """
    qty = li.qty or 0.0
    # A company overhead has no units to multiply by (decision 0068).
    if li.basis != "per_device" or li.allocate == OVERHEAD:
        return qty
    run_id = li.run_id or (doc.run_id if doc else None)
    if run_id is None or db is None:
        return qty
    run = db.get(M.ProductionRun, run_id)
    if run is None:
        return qty
    return qty * planned_units(run)


def produced_counts(db: Session, run_ids: list[int]) -> dict[int, int]:
    """Device records per production run — one grouped query, never one per run."""
    from sqlalchemy import func

    if not run_ids:
        return {}
    return {rid: n for rid, n in
            db.query(M.DeviceUnit.production_run_id, func.count(M.DeviceUnit.id))
            .filter(M.DeviceUnit.production_run_id.in_(run_ids))
            .group_by(M.DeviceUnit.production_run_id).all() if rid is not None}


def good_units(db: Session, run: M.ProductionRun, counts: dict[int, int] | None = None) -> int:
    """Units that PASSED — the denominator of every per-device figure.

    DERIVED from the device records (decision 0030). The flasher writes a
    `produced` event on a device's first pass, so counting those records IS
    what passed, and the answer stays right when a device is added or moved
    between batches (decision 0029). Pass `counts` from `produced_counts` when
    resolving many runs.

    The fallbacks are for a batch that has no device records at all — the
    legacy runs from before the flasher. `qty_good` was meant to hold this and
    was never filled on a single run; `qty` is boards ORDERED FROM JLC, which
    is the last resort and not the answer, because a batch routinely yields
    more than were ordered (CE_Dongle_V2 Batch 5: 455 ordered, 568 passed).
    """
    n = (counts if counts is not None else produced_counts(db, [run.id])).get(run.id) or 0
    return n or max(run.qty_good or run.plan_qty or run.qty or 1, 1)


def header_ids(db: Session, document_id: int | None = None) -> set[int]:
    """Ids of lines that have at least one LIVE child.

    Such a line is a header: the children carry its money, so counting the
    header too would double it. Every money path in this module filters on this
    one set — the invariant is not re-derived per call site.
    """
    q = db.query(M.RunCostLine.parent_line_id).filter(
        M.RunCostLine.parent_line_id.isnot(None),
        M.RunCostLine.voided_at.is_(None),
    )
    if document_id is not None:
        # Children always live on their parent's document (enforced when they
        # are created), so a per-document filter is exact.
        q = q.filter(M.RunCostLine.document_id == document_id)
    return {pid for (pid,) in q.all() if pid}


def line_json(li: M.RunCostLine, doc: M.RunCostDocument | None = None,
              db: Session | None = None, kids: dict[int, float] | None = None) -> dict:
    """`kids` maps a header line id -> the summed amount of its live children, in
    the SAME currency (children inherit the parent's). Absent and with a session
    available, it is looked up for this one line."""
    cur = li.currency or (doc.currency if doc else "USD")
    eff = effective_qty(li, doc, db)
    total = _round(eff * (li.unit_price or 0)) or 0.0
    if kids is None and db is not None:
        children = (
            db.query(M.RunCostLine)
            .filter(M.RunCostLine.parent_line_id == li.id, M.RunCostLine.voided_at.is_(None))
            .all()
        )
        kids = ({li.id: sum(effective_qty(c, doc, db) * (c.unit_price or 0) for c in children)}
                if children else {})
    child_total = (kids or {}).get(li.id)
    return {
        "id": li.id,
        "document_id": li.document_id,
        "run_id": li.run_id,
        "project_id": li.project_id,
        # Decision 0058 §4: aimed at a process transformation as its conversion cost.
        "transformation_id": li.transformation_id,
        "parent_line_id": li.parent_line_id,
        # A header's own amount is NOT counted anywhere; its children are.
        "is_header": child_total is not None,
        "children_total": _round(child_total),
        # What is still unallocated on a header. The Aqua share of a shared
        # freight line used to live in a `notes` string — i.e. it was invisible.
        "residual": _round(total - child_total) if child_total is not None else None,
        "position": li.position,
        # DERIVED from the step since decision 0047 — the column is gone. Still
        # emitted because the coarse bucket is what `by_kind` reports and what a
        # reader recognises ("this is assembly money").
        "kind": cost_steps.kind_of(li.plan_key or ""),
        "basis": li.basis,
        "label": li.label,
        "qty": li.qty,
        "qty_effective": eff,
        "unit_price": li.unit_price,
        "line_total": total,
        "currency": cur,
        "allocate": li.allocate,
        # WHY a position is charged to nobody. It has been stored since the
        # `excluded` bucket got a reason column, and emitted nowhere — so the UI
        # could neither show it nor ask for it (decision 0045).
        "exclude_reason": li.exclude_reason or "",
        "overhead_category": li.overhead_category or "",
        "component_id": li.component_id,
        # The library part's name, so the Invoices view can show WHICH part a
        # line is linked to instead of only an id. `db.get` is a primary-key
        # lookup served from the identity map after the first hit, so a document
        # whose lines share a few components costs a few queries, not one a line.
        "component_name": (
            (c.name if (c := db.get(M.Component, li.component_id)) is not None else "")
            if li.component_id and db is not None else ""
        ),
        "mpn": li.mpn,
        "lcsc": li.lcsc,
        "description": li.description,
        "plan_key": li.plan_key,
        "plan_kind": li.plan_kind,
        # The direct link to one planned cost item. Its own field since decision
        # 0047 — it used to be written into `plan_key`, which now says what the
        # position IS.
        "plan_item_id": li.plan_item_id,
        "plan_ref": li.plan_ref,
        "notes": li.notes,
        "ocr_confidence": li.ocr_confidence,
        "voided": li.voided_at is not None,
        "superseded_by_id": li.superseded_by_id,
    }


def line_destination(li: M.RunCostLine, doc: M.RunCostDocument | None) -> tuple[str, int | None]:
    """Where a LEAF line's money ends up, most specific first.

    `"unassigned"` is the money-disappearing detector: a non-part line on a
    shared document that names neither a run nor a project belongs to nobody, and
    silently vanishes from every per-run figure.

    `"excluded"` is its deliberate opposite — money entered so the document
    reconciles against its printed total, but knowingly charged to nobody:
    reclaimable import VAT, and the prepaid-component portion of a populated-board
    price whose components are already in the pool (user decisions 2026-07-27).
    Being explicit is the point: an excluded line is auditable, whereas simply not
    entering it would make the document fail to add up.
    """
    if li.allocate == EXCLUDED:
        return "excluded", None
    if li.allocate == OVERHEAD:
        return "overhead", None
    # A conversion cost (decision 0058 §4) is part of what one transformation's
    # output lot is worth. It comes before the document's own batch, or a
    # document filed against a batch would claim it as a direct cost too.
    if getattr(li, "transformation_id", None):
        return "transformation", li.transformation_id
    if li.run_id:
        return "run", li.run_id
    if li.project_id:
        return "project", li.project_id
    # An explicit "this is stock" beats the DOCUMENT's default destination: a
    # parts invoice filed against a batch can still carry a position that is
    # plain stock, and saying so on the line is the only way to express it.
    if li.allocate == POOLED:
        return "pool", None
    if doc is not None and doc.run_id:
        return "run", doc.run_id
    if is_stock(li):
        # A `parts:*` or `pcba:parts` step IS the statement that this money is
        # stock. `allocate="pooled"` (decision 0045) says the same thing on the
        # destination axis; either is enough.
        return "pool", None  # stockpile: runs reach it through consumption
    if li.allocate in SPREAD:
        # Spread over the same document's parts: landed cost, so the money follows
        # the parts into the pool instead of belonging to nobody.
        # Only when there ARE parts to carry it — `pool_state` cannot spread a
        # surcharge over nothing, and claiming the bucket anyway would lose it.
        if doc is not None and any(
            is_stock(c) and c.run_id is None and c.voided_at is None for c in doc.lines
        ):
            return "pool", None
    if doc is not None and doc.project_id:
        return "project", doc.project_id
    return "unassigned", None


def _accountant_state(doc: M.RunCostDocument, db: Session | None) -> dict:
    from . import accountant

    return accountant.state(doc, db)


def document_json(doc: M.RunCostDocument, with_lines: bool = True,
                  db: Session | None = None,
                  closed: dict[int, M.ProductionRun] | None = None) -> dict:
    live = [li for li in doc.lines if li.voided_at is None]
    kids: dict[int, float] = defaultdict(float)
    for li in live:
        if li.parent_line_id:
            kids[li.parent_line_id] += effective_qty(li, doc, db) * (li.unit_price or 0)
    # Reconciliation compares the printed total against the TOP-LEVEL lines, the
    # ones the invoice actually prints. Splitting a position into children must
    # never disturb it — otherwise every split invoice would read unreconciled.
    lines_total = sum(effective_qty(li, doc, db) * (li.unit_price or 0)
                      for li in live if not li.parent_line_id)
    leaves = [li for li in live if li.id not in kids]
    by_dest: dict[str, float] = defaultdict(float)
    by_run: dict[int, float] = defaultdict(float)
    by_project: dict[int, float] = defaultdict(float)
    for li in leaves:
        amount = effective_qty(li, doc, db) * (li.unit_price or 0)
        dest, ref = line_destination(li, doc)
        by_dest[dest] += amount
        if dest == "run" and ref:
            by_run[ref] += amount
        elif dest == "project" and ref:
            by_project[ref] += amount
    # A header's money that no child claimed. Clamped at zero because a header
    # cannot owe a negative amount — but the clamp DROPS the opposite case, so
    # its twin below reports it instead of losing it.
    residual = sum(
        max(effective_qty(li, doc, db) * (li.unit_price or 0) - kids[li.id], 0.0)
        for li in live if li.id in kids
    )
    # Children totalling MORE than the header they split. `split_line` refuses
    # any over-allocation since 2026-09-24 (it allowed half a cent before), so
    # this should read zero; it is reported rather than lost if it does not.
    overallocated = sum(
        max(kids[li.id] - effective_qty(li, doc, db) * (li.unit_price or 0), 0.0)
        for li in live if li.id in kids
    )
    out = {
        "id": doc.id,
        "project_id": doc.project_id,
        "run_id": doc.run_id,
        "doc_type": doc.doc_type,
        "supplier": doc.supplier,
        "doc_number": doc.doc_number,
        "external_id": doc.external_id,
        "doc_date": doc.doc_date,
        "paid_at": doc.paid_at,
        "currency": doc.currency,
        "fx_rate_usd": doc.fx_rate_usd,
        "display_amount": doc.display_amount,
        "total_amount": doc.total_amount,
        "tax_amount": doc.tax_amount,
        # Decision 0084: the invoice's tax data, in the KSeF structure.
        "sale_date": doc.sale_date or "",
        "due_date": doc.due_date or "",
        "received_date": doc.received_date or "",
        "tax_amount_pln": str(doc.tax_amount_pln) if doc.tax_amount_pln is not None else None,
        "notes": doc.notes,
        "attachment_id": doc.attachment_id,
        # Decisions 0063/0064: the company that was billed, how that was found,
        # and on an in-house transfer the company that sent the stock.
        "company_id": doc.company_id,
        "company_source": doc.company_source or "",
        "counterparty_company_id": doc.counterparty_company_id,
        # Decision 0044. `locked` non-empty means every write path refuses this
        # document, because it charges a batch whose books are closed; the fix is
        # a correction document, which the UI offers in place of the edit switch.
        # Computed, never stored: reopening a batch must make its documents
        # editable again with nothing to un-write.
        "locked": closed_lock(db, doc, closed) if db is not None else [],
        "corrects_document_id": doc.corrects_document_id,
        # Only on the full view. The register renders every document and the
        # back-pointer is not on its row, so this stays off the list path.
        "corrected_by": (
            [{"id": c.id, "doc_number": c.doc_number or "", "doc_date": c.doc_date or ""}
             for c in db.query(M.RunCostDocument)
             .filter(M.RunCostDocument.corrects_document_id == doc.id)
             .order_by(M.RunCostDocument.id).all()]
            if db is not None and with_lines else []
        ),
        # The supplier's original, filed with the money it evidences.
        "attachment_count": (
            db.query(M.RunAttachment).filter(M.RunAttachment.document_id == doc.id).count()
            if db is not None else 0
        ),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        # Decision 0079: whether the accountant has it (KSeF, or a recorded send).
        "accountant": _accountant_state(doc, db),
        "line_count": len(live),
        "lines_total": _round(lines_total),
        # Entered total vs the sum of its lines: the reconciliation an importer
        # (or a human) can get wrong, surfaced instead of hidden.
        # Compares the printed total against the sum of EFFECTIVE line amounts,
        # so a "5 PLN per board" line reconciles against a batch total.
        "reconciled": doc.total_amount is None or abs(lines_total - doc.total_amount) <= 0.05,
        # Where this document's money actually went, leaves only. `unassigned`
        # plus `residual` is what no run and no project is paying for — the
        # "money is not disappearing anywhere" check, per document.
        "assignment": {
            "run": _round(by_dest.get("run", 0.0)),
            "project": _round(by_dest.get("project", 0.0)),
            "pool": _round(by_dest.get("pool", 0.0)),
            # Conversion costs: money in a prepared part's lot, decision 0058 §4.
            "transformation": _round(by_dest.get("transformation", 0.0)),
            "excluded": _round(by_dest.get("excluded", 0.0)),
            # A company cost of no product (decision 0068).
            "overhead": _round(by_dest.get("overhead", 0.0)),
            "unassigned": _round(by_dest.get("unassigned", 0.0)),
            "residual": _round(residual),
            # The opposite of `residual`: children claiming more than the header.
            "overallocated": _round(overallocated),
            "by_run": {str(k): _round(v) for k, v in sorted(by_run.items())},
            "by_project": {str(k): _round(v) for k, v in sorted(by_project.items())},
            "fully_assigned": by_dest.get("unassigned", 0.0) <= 0.005 and residual <= 0.005,
        },
    }
    if with_lines:
        out["lines"] = [line_json(li, doc, db, kids=kids)
                        for li in sorted(doc.lines, key=lambda x: (x.position, x.id))]
        # The printed invoice (decision 0084): on the full view only, the
        # register renders every document and never reads it.
        out["body"] = doc.body
    return out


# OCR-tolerant MPN keys. `jlc._norm_mpn` only drops dashes/underscores/spaces;
# an invoice can also carry stray punctuation ("S$S34") and character
# confusions, so matching needs both a strict and a folded form.
_CONFUSABLE = str.maketrans({"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "B": "8", "Z": "2"})


def _strip(s: str) -> str:
    """Upper-case, alphanumerics only — kills OCR punctuation noise."""
    return "".join(ch for ch in (s or "").upper() if ch.isalnum())


def _fold(s: str) -> str:
    """Additionally fold the character pairs OCR mixes up, for a fallback pass."""
    return _strip(s).translate(_CONFUSABLE)


# ------------------------------------------------- resolving parts to the library

def resolve_part_lines(db: Session, document_id: int | None = None) -> dict:
    """Attach `component_id` (and LCSC) to invoice part lines by matching the MPN.

    JLC component invoices identify parts by **manufacturer part number only** —
    there is no LCSC column on them — while the platform's BOM lines carry LCSC
    codes and component ids. Without this bridge a purchase and a BOM draw key
    on different things (`m<MPN>` vs `c<id>`), the pool never matches the BOM,
    and every component is costed at zero.

    Two sources, best first:
      1. `jlc_stock_items` — the synced private JLC library already pairs
         mpn + lcsc + component_id (matched 21/30 MPNs on real data).
      2. the library's own `Manufacturer Part Number 1` property (16/30).

    Comparison is OCR-tolerant (see `_strip` / `_fold`) and every non-exact
    match is written into the line's notes so a human can audit it.
    """
    q = db.query(M.RunCostLine).filter(
        IS_STOCK,
        M.RunCostLine.voided_at.is_(None),
        M.RunCostLine.component_id.is_(None),
        M.RunCostLine.mpn != "",
    )
    if document_id is not None:
        q = q.filter(M.RunCostLine.document_id == document_id)
    lines = q.all()
    if not lines:
        return {"resolved": 0, "unresolved": [], "checked": 0}

    # index 1: JLC private stock (mpn -> component_id, lcsc)
    by_mpn: dict[str, tuple[int | None, str]] = {}

    def offer(key: str, cid: int | None, lcsc: str) -> None:
        """Index an MPN, PREFERRING an entry that carries a component_id.

        JLC routinely lists the same manufacturer part under several LCSC codes —
        `XL-1005SURC` exists as both C25503345 (unlinked) and C965790 (linked to
        library component 218). A blind `setdefault` let the unlinked one win, so
        the purchase keyed on its MPN while the BOM draw keyed on the component id:
        the two never met and 16,800 LEDs costed at zero while their money sat
        unconsumed in the pool. First-write-wins is wrong here; component_id wins.
        """
        if not key:
            return
        have = by_mpn.get(key)
        if have is None or (have[0] is None and cid is not None):
            by_mpn[key] = (cid, lcsc or (have[1] if have else ""))

    for it in db.query(M.JlcStockItem).filter(M.JlcStockItem.mpn != "").all():
        offer(_strip(it.mpn), it.component_id, it.lcsc or "")
    # index 2: the library's MPN property, with its LCSC alongside
    rows = (
        db.query(M.ComponentProperty.value, M.ComponentVersion.component_id)
        .join(M.ComponentVersion, M.ComponentVersion.id == M.ComponentProperty.component_version_id)
        .filter(M.ComponentProperty.key == "Manufacturer Part Number 1",
                M.ComponentProperty.value != "")
        .all()
    )
    lib_lcsc: dict[int, str] = {
        cid: val for val, cid in (
            db.query(M.ComponentProperty.value, M.ComponentVersion.component_id)
            .join(M.ComponentVersion, M.ComponentVersion.id == M.ComponentProperty.component_version_id)
            .filter(M.ComponentProperty.key == "LCSC Part", M.ComponentProperty.value != "")
            .all()
        )
    }
    for value, cid in rows:
        # the library is authoritative for component_id, so it may upgrade an
        # entry that JLC stock left unlinked
        offer(_strip(value), cid, lib_lcsc.get(cid, ""))

    # OCR of a printed invoice confuses characters and truncates wrapped cells,
    # so matching runs in three tiers, each requiring a UNIQUE hit:
    #   exact  — normalised MPN is identical
    #   folded — 0/O, 1/I, 5/S confusions folded ("O805W8F1200TSE" -> 0805W8F1200T5E)
    #   prefix — the invoice value is a prefix of exactly one library MPN
    #            ("ESP32-WROOM-32UE-" truncated from "…-32UE-N4")
    # A tier that produces several candidates is rejected rather than guessed.
    folded: dict[str, list[str]] = defaultdict(list)
    for key in by_mpn:
        folded[_fold(key)].append(key)

    resolved, unresolved, unlinked = 0, [], []
    tiers: dict[str, int] = defaultdict(int)
    for li in lines:
        norm = _strip(li.mpn)
        hit_key = norm if norm in by_mpn else None
        tier = "exact"
        if hit_key is None:
            cands = folded.get(_fold(norm), [])
            if len(cands) == 1:
                hit_key, tier = cands[0], "folded"
        if hit_key is None and len(norm) >= 6:
            pref = [k for k in by_mpn if k.startswith(norm)]
            if len(pref) == 1:
                hit_key, tier = pref[0], "prefix"
        if hit_key is None:
            unresolved.append(li.mpn)
            continue
        cid, lcsc = by_mpn[hit_key]
        if cid:
            li.component_id = cid
            resolved += 1
            tiers[tier] += 1
            if tier != "exact":
                note = f"MPN matched by {tier} ({li.mpn!r} → {hit_key})"
                li.notes = f"{li.notes}; {note}" if li.notes else note
        else:
            # The MPN was recognised, but the thing it matched has no library
            # component — so this purchase still cannot meet a BOM draw. Reporting
            # it as neither resolved nor unresolved hid real money (1750 DIP
            # switches), so it gets its own bucket.
            unlinked.append(li.mpn)
        if lcsc and not li.lcsc:
            li.lcsc = lcsc
    return {"resolved": resolved, "unresolved": sorted(set(unresolved)),
            # recognised but with no library component behind them: priced in the
            # pool, yet unreachable by any BOM draw until the part is modelled
            "unlinked": sorted(set(unlinked)),
            "checked": len(lines), "by_tier": dict(tiers)}


# --------------------------------------------------------------- the pool

def _to_usd(amount: float, currency: str, rates: dict[str, float]) -> tuple[float, bool]:
    return fx.convert(amount, currency or "USD", "USD", rates)


def _pool_events(db: Session, company_id: int | None = None, *, with_transfers: bool = False
                 ) -> tuple[list[tuple[str, str, object]], dict, dict]:
    """Everything that moves part stock, sorted by event date: leaf part
    purchases (non-proforma, unallocated, not excluded), run draws, and stock
    adjustments — plus the document map and the landed-cost surcharge per
    purchase line. ONE source of events for `pool_state`, `component_ledger`
    and `check_shortages`, so the three can never disagree about what happened.

    `company_id` keeps one company's events only (decision 0064): purchases it
    was billed for, and the draws and adjustments stamped with it. Pass it
    through `stock_scope`, so it is None while both companies share one pool.

    With no company, in-house transfers are left out on BOTH sides — the
    receiver's purchase and the sender's draw. In one pool they move nothing,
    and replaying them would re-price the part: the draw leaves at the pool's
    average and the purchase enters at the sender's. The lot ledger asks
    `with_transfers=True`: a transfer's position is a lot its draws bind to.
    """
    doc_by_id = {d.id: d for d in db.query(M.RunCostDocument).all()}
    headers = header_ids(db)
    carriers: list[M.RunCostLine] = []
    if not doc_by_id:
        purchases: list[M.RunCostLine] = []
    else:
        pool_doc_ids = [d.id for d in doc_by_id.values()
                        if (d.doc_type or "invoice") != "proforma"
                        and (d.company_id == company_id if company_id is not None
                             else with_transfers or (d.doc_type or "invoice") != "transfer")]
        purchases = (
            db.query(M.RunCostLine)
            .filter(
                IS_STOCK,
                # run_id set = bought FOR that run and charged to it directly
                # (see run_actuals); only unallocated purchases are pool stock,
                # otherwise the same money is counted twice.
                M.RunCostLine.run_id.is_(None),
                M.RunCostLine.voided_at.is_(None),
                M.RunCostLine.document_id.in_(pool_doc_ids or [0]),
                # Prepaid components on a populated-board invoice are the SAME
                # money as the component invoice that already fed the pool.
                M.RunCostLine.allocate != EXCLUDED,
                # A conversion cost is value on a prepared part's lot, never stock bought.
                M.RunCostLine.transformation_id.is_(None),
            )
            .all()
        )
        # A split position is carried by its children; the header is worth zero.
        purchases = [li for li in purchases if li.id not in headers]
        carriers = [
            li for li in (
                db.query(M.RunCostLine)
                .filter(
                    NOT_STOCK,
                    M.RunCostLine.allocate.in_(SPREAD),
                    M.RunCostLine.run_id.is_(None),
                    M.RunCostLine.voided_at.is_(None),
                    M.RunCostLine.document_id.in_(pool_doc_ids or [0]),
                    M.RunCostLine.transformation_id.is_(None),
                )
                .all()
            )
            if li.id not in headers
        ]
    # Landed cost: a freight/duty line marked `allocate` is spread over the part
    # lines of the SAME document, in that document's currency. It adds value
    # without adding quantity, so the moving average rises to what the stock
    # really cost to get here. Carrier rows are never consumed themselves.
    surcharge: dict[int, float] = defaultdict(float)
    if carriers:
        parts_by_doc: dict[int, list[M.RunCostLine]] = defaultdict(list)
        for li in purchases:
            parts_by_doc[li.document_id].append(li)
        for c in carriers:
            targets = parts_by_doc.get(c.document_id) or []
            weights = [
                (li, (li.qty or 0.0) if c.allocate == "by_qty" else (li.qty or 0.0) * (li.unit_price or 0.0))
                for li in targets
            ]
            total_w = sum(w for _, w in weights)
            if total_w <= 0:
                # Nothing to spread it over. Leave it alone rather than lose it —
                # `line_destination` keeps such a line out of the pool bucket too,
                # so the register reports it instead of silently absorbing it.
                continue
            amount = (c.qty or 0.0) * (c.unit_price or 0.0)
            for li, w in weights:
                surcharge[li.id] += amount * w / total_w

    events: list[tuple[str, str, object]] = []
    for li in purchases:
        doc = doc_by_id[li.document_id]
        events.append((doc.doc_date or "", "buy", li))
    draws = live_consumption(db)
    adjs = db.query(M.ComponentStockAdjustment)
    if company_id is not None:
        draws = draws.filter(M.ComponentConsumption.company_id == company_id)
        adjs = adjs.filter(M.ComponentStockAdjustment.company_id == company_id)
    elif not with_transfers:
        draws = draws.filter(M.ComponentConsumption.transfer_line_id.is_(None))
    for c in draws.all():
        events.append((c.consumed_at or "", "use", c))
    for a in adjs.all():
        events.append((a.adjusted_at or "", "adj", a))
    # Same-date ties resolve adj < buy < use, so an invoice dated the day of a
    # run counts as available to it.
    events.sort(key=lambda e: (e[0] or "9999", e[1]))
    return events, doc_by_id, surcharge


def _buy_usd(row: M.RunCostLine, doc: M.RunCostDocument, extra: float,
             rates: dict[str, float]) -> tuple[float, float, bool]:
    """A purchase line's unit price and its landed-cost surcharge share, in USD.
    The document's pinned rate wins; else the historical table for the date."""
    cur = row.currency or doc.currency or "USD"
    unit = row.unit_price or 0.0
    if doc.fx_rate_usd and cur.upper() != "USD":
        return unit * doc.fx_rate_usd, extra * doc.fx_rate_usd, True
    unit_usd, known = _to_usd(unit, cur, rates)
    extra_usd, _ = _to_usd(extra, cur, rates)
    return unit_usd, extra_usd, known


def conversion_by_transformation(db: Session) -> dict[int, float]:
    """USD of the invoice positions aimed at each transformation (decision 0058
    §4) — the conversion cost, read on every call and never stored.

    The same filter as a purchase: a live leaf on a document that is not a
    proforma, not excluded. Priced the way a purchase is: the document's pinned
    rate, else the historical rate at its date."""
    lines = (db.query(M.RunCostLine)
             .filter(M.RunCostLine.transformation_id.isnot(None),
                     M.RunCostLine.voided_at.is_(None),
                     M.RunCostLine.allocate != EXCLUDED).all())
    if not lines:
        return {}
    headers = header_ids(db)
    out: dict[int, float] = defaultdict(float)
    rate_cache: dict[str, dict[str, float]] = {}
    for li in lines:
        if li.id in headers:
            continue
        doc = db.get(M.RunCostDocument, li.document_id)
        if doc is None or (doc.doc_type or "invoice") == "proforma":
            continue
        day = doc.doc_date or ""
        if day not in rate_cache:
            rate_cache[day] = fx.rates_at(db, _as_dt(day))
        amount = effective_qty(li, doc, db) * (li.unit_price or 0)
        cur = li.currency or doc.currency or "USD"
        if doc.fx_rate_usd and cur.upper() != "USD":
            usd = amount * doc.fx_rate_usd
        else:
            usd, _known = _to_usd(amount, cur, rate_cache[day])
        out[li.transformation_id] += usd
    return dict(out)


def conversion_extras_usd(db: Session) -> dict[int, float]:
    """The conversion cost per OUTPUT ADJUSTMENT — what the replayers add to a
    transformation's lot, the way `surcharge` adds freight to a purchase."""
    by_t = conversion_by_transformation(db)
    if not by_t:
        return {}
    out: dict[int, float] = {}
    for t in (db.query(M.ProcessTransformation)
              .filter(M.ProcessTransformation.id.in_(list(by_t)),
                      M.ProcessTransformation.voided_at.is_(None)).all()):
        if t.output_adjustment_id:
            out[t.output_adjustment_id] = by_t[t.id]
    return out


def pool_state(db: Session, project_id: int | None = None, as_of: str | None = None,
               company_id: int | None = None) -> dict:
    """Replay purchases, consumptions and adjustments in EVENT DATE order and
    return the per-part COMPANY-WIDE pool: quantity on hand, moving average
    unit cost, value. `company_id` replays one company's stock (decision 0064);
    pass it through `stock_scope`.

    Quantities here exist to apportion money — they are not an inventory record
    and are not expected to match JLCPCB's stock (see the module docstring).
    """
    # `project_id` is accepted for call-site clarity but does NOT scope the
    # balance: stock bought once serves every product, so purchases, draws and
    # write-offs are all company-wide. Scoping purchases while counting all
    # consumption would silently under-report what is on hand.
    events, doc_by_id, surcharge = _pool_events(db, company_id)
    # Conversion costs ride on their transformation's output lot (decision 0058).
    extras = conversion_extras_usd(db)
    if as_of:
        # Historical accuracy: a run dated 2024 must be priced from the pool as
        # it stood THEN. Without this cutoff a purchase made in 2026 would
        # retro-price a 2024 batch, because the replay would run to the end.
        events = [e for e in events if (e[0] or "9999") <= as_of]

    # One rate table per distinct event date keeps the replay honest without a
    # query per row. A document's own pinned rate wins when present.
    rate_cache: dict[str, dict[str, float]] = {}

    def rates_for(date_iso: str) -> dict[str, float]:
        if date_iso not in rate_cache:
            rate_cache[date_iso] = fx.rates_at(db, _as_dt(date_iso))
        return rate_cache[date_iso]

    # `value_*` are the money legs of the same events the quantities track, so
    # `value_bought + value_adj - value_used == value_usd` holds exactly per part.
    # The invoice register asserts that identity company-wide.
    pool: dict[str, dict] = defaultdict(
        lambda: {"qty": 0.0, "value_usd": 0.0, "avg_usd": 0.0, "mpn": "", "lcsc": "",
                 "component_id": None, "bought": 0.0, "used": 0.0, "lost": 0.0,
                 # Stock that left for ANOTHER project's assembly order. Kept
                 # apart from `lost` because attrition is a defect signal in this
                 # codebase and consumption by a project we do not track is not a
                 # defect. Counting them together made "written off" read 1,094
                 # pieces on 2026-09-18 when the true attrition was ZERO.
                 "external": 0.0,
                 "value_bought": 0.0, "value_used": 0.0, "value_adj": 0.0,
                 # Basis for the moving average, kept SEPARATE from the reported
                 # figures and never allowed below zero. `qty`/`value_usd` are the
                 # pure algebraic sums the register's identity depends on, so they
                 # must be able to go negative when more was drawn than bought.
                 # Deriving the average from those directly is what let a run draw
                 # stock the pool never had, strip the quantity without the value,
                 # and make the NEXT purchase average $44 for a $3.73 enclosure.
                 "_avg_qty": 0.0, "_avg_value": 0.0,
                 # Shortage bookkeeping: the lowest the balance ever went and the
                 # date it first dipped below zero — the register's negative-stock
                 # issues read these instead of re-deriving the replay.
                 "min_qty": 0.0, "first_short": None,
                 "unknown_rate": False}
    )
    for date_iso, kind, row in events:
        k = _key(row)
        p = pool[k]
        p["mpn"] = p["mpn"] or getattr(row, "mpn", "") or ""
        p["lcsc"] = p["lcsc"] or getattr(row, "lcsc", "") or ""
        p["component_id"] = p["component_id"] or getattr(row, "component_id", None)
        if kind == "buy":
            doc = doc_by_id[row.document_id]
            extra = surcharge.get(row.id, 0.0)  # freight share, document currency
            unit_usd, extra_usd, known = _buy_usd(row, doc, extra, rates_for(date_iso))
            p["unknown_rate"] = p["unknown_rate"] or not known
            p["qty"] += row.qty or 0.0
            value = (row.qty or 0.0) * unit_usd + extra_usd
            p["value_usd"] += value
            p["value_bought"] += value
            p["bought"] += row.qty or 0.0
            p["_avg_qty"] += row.qty or 0.0
            p["_avg_value"] += value
        elif kind == "use":
            q = row.qty or 0.0
            # The snapshot is the price, INCLUDING zero. A draw from a lot that
            # entered at zero value (found historical WIP, decision 0058) is
            # worth exactly 0, and the register charges its batch 0; reading 0
            # as "unknown, use the average" made the two disagree. No draw on
            # production carried a 0.0 snapshot when this changed (2026-10-03).
            unit = row.unit_cost_usd if row.unit_cost_usd is not None else p["avg_usd"]
            p["qty"] -= q
            p["value_usd"] -= q * unit
            p["value_used"] += q * unit
            p["used"] += q
            # a draw can only take value that is actually there — and it takes it
            # at the BASIS's own average, never the draw's snapshotted price. The
            # snap belongs to run costing; using it here leaks the difference into
            # the basis, and a long sequence of below-average snaps once drained
            # the quantity but not the value, leaving 1 phantom piece "worth"
            # $125.66 that repriced every CH340B on the next plan.
            taken = min(q, max(p["_avg_qty"], 0.0))
            basis_avg = p["_avg_value"] / p["_avg_qty"] if p["_avg_qty"] > 0.0001 else 0.0
            p["_avg_qty"] -= taken
            p["_avg_value"] = max(p["_avg_value"] - taken * basis_avg, 0.0)
        else:  # adjustment: negative delta = attrition / write-off
            q = row.qty_delta or 0.0
            p["qty"] += q
            delta = q * (row.unit_cost_usd if row.unit_cost_usd is not None else p["avg_usd"])
            if q > 0:
                delta += extras.get(row.id, 0.0)
            p["value_usd"] += delta
            p["value_adj"] += delta
            if q >= 0:
                p["_avg_qty"] += q
                p["_avg_value"] += delta
            else:
                # same rule as draws: the basis loses value at its own average
                taken = min(-q, max(p["_avg_qty"], 0.0))
                basis_avg = p["_avg_value"] / p["_avg_qty"] if p["_avg_qty"] > 0.0001 else 0.0
                p["_avg_qty"] -= taken
                p["_avg_value"] = max(p["_avg_value"] - taken * basis_avg, 0.0)
            if q < 0:
                # `external_project` is another project's order consuming stock,
                # recorded as an adjustment because it has no run to charge. Since
                # decision 0034 the same fact is written as an UNCHARGED DRAW, so
                # no new rows of this kind appear; the 27 historical ones are
                # reported on their own axis rather than as loss.
                if (getattr(row, "reason", "") or "") == "external_project":
                    p["external"] += -q
                else:
                    p["lost"] += -q
        # average of what is genuinely on hand; when nothing is, the last known
        # average is retained so a later purchase blends against a sane figure
        if p["_avg_qty"] > 0.0001:
            p["avg_usd"] = p["_avg_value"] / p["_avg_qty"]
        if p["qty"] < p["min_qty"]:
            p["min_qty"] = p["qty"]
            if p["qty"] < -0.0001 and p["first_short"] is None:
                p["first_short"] = date_iso
    return dict(pool)


def pool_states(db: Session, as_of: str | None = None) -> dict[int | None, dict]:
    """The pool of each company, by company id (decision 0064), or `{None: the
    one pool}` while the companies share one. A part is never merged across
    companies: each keeps its own quantity and average."""
    if not settings.stock_per_company:
        return {None: pool_state(db, as_of=as_of)}
    return {c.id: pool_state(db, as_of=as_of, company_id=c.id)
            for c in db.query(M.Company).order_by(M.Company.id).all()}


def component_ledger(db: Session, component_id: int | None = None,
                     mpn: str = "", lcsc: str = "", company_id: int | None = None) -> dict:
    """One part's complete event history with the running balance after every
    event — the audit trail behind a Parts-stock row, and the answer to "what
    was our stock of this on any given date".

    Events match on ANY identity the part is known under (component id, MPN,
    LCSC), so an unlinked purchase and a linked draw appear in one timeline
    instead of two half-stories.
    """
    want = set(_identity_keys(component_id, mpn or "", lcsc or ""))
    events, doc_by_id, surcharge = _pool_events(db, company_id)
    extras = conversion_extras_usd(db)  # conversion costs on prepared-part lots (0058)
    runs = {r.id: r for r in db.query(M.ProductionRun).all()}

    rate_cache: dict[str, dict[str, float]] = {}

    def rates_for(date_iso: str) -> dict[str, float]:
        if date_iso not in rate_cache:
            rate_cache[date_iso] = fx.rates_at(db, _as_dt(date_iso))
        return rate_cache[date_iso]

    rows: list[dict] = []
    bal = val = avg = 0.0
    aq = av = 0.0  # the clamped moving-average basis, same rules as pool_state
    for date_iso, kind, row in events:
        keys = set(_identity_keys(getattr(row, "component_id", None),
                                  getattr(row, "mpn", "") or "",
                                  getattr(row, "lcsc", "") or ""))
        if not (keys & want):
            continue
        if kind == "buy":
            doc = doc_by_id[row.document_id]
            unit_usd, extra_usd, _known = _buy_usd(
                row, doc, surcharge.get(row.id, 0.0), rates_for(date_iso))
            qty_d = row.qty or 0.0
            value_d = qty_d * unit_usd + extra_usd
            aq += qty_d
            av += value_d
            ref = f"{doc.supplier or '?'} {doc.doc_number or ''}".strip()
            detail = row.label or ""
        elif kind == "use":
            qty_d = -(row.qty or 0.0)
            unit = row.unit_cost_usd if row.unit_cost_usd is not None else avg
            value_d = qty_d * unit
            # basis loses value at its OWN average, never the snapped price
            # (same rule as pool_state — see the comment there)
            taken = min(-qty_d, max(aq, 0.0))
            basis_avg = av / aq if aq > 0.0001 else 0.0
            aq -= taken
            av = max(av - taken * basis_avg, 0.0)
            run = runs.get(row.run_id)
            # A draw with no run is UNCHARGED, not a draw against run "None"
            # (0034). It is an ordinary state now — an order that builds someone
            # else's project, or a movement JLC made that no batch asked for.
            ref = (f"into a prepared part (transformation #{row.transformation_id})"
                   if row.run_id is None and row.transformation_id is not None else
                   "sent to the other company (in-house transfer)"
                   if row.run_id is None and row.transformation_id is None
                   and getattr(row, "transfer_line_id", None) else
                   "charged to no batch" if row.run_id is None else
                   f"run {row.run_id}" + (f" — {run.label}" if run else ""))
            detail = row.note or ""
        else:  # adjustment
            qty_d = row.qty_delta or 0.0
            unit = row.unit_cost_usd if row.unit_cost_usd is not None else avg
            value_d = qty_d * unit + (extras.get(row.id, 0.0) if qty_d > 0 else 0.0)
            if qty_d >= 0:
                aq += qty_d
                av += value_d
            else:
                taken = min(-qty_d, max(aq, 0.0))
                basis_avg = av / aq if aq > 0.0001 else 0.0
                aq -= taken
                av = max(av - taken * basis_avg, 0.0)
            ref = f"adjustment — {row.reason or ''}".strip()
            detail = row.note or ""
        bal += qty_d
        val += value_d
        if aq > 0.0001:
            avg = av / aq
        rows.append({
            "date": date_iso, "kind": kind, "ref": ref, "detail": detail,
            "qty_delta": _round(qty_d), "unit_usd": _round(value_d / qty_d) if qty_d else None,
            "value_delta_usd": _round(value_d),
            "balance_after": _round(bal), "avg_usd_after": _round(avg),
            "run_id": getattr(row, "run_id", None) if kind == "use" else None,
            "document_id": getattr(row, "document_id", None) if kind == "buy" else None,
            "company_id": event_company(kind, row, doc_by_id),
            "short": bal < -0.0001,
        })
    return {
        "component_id": component_id, "mpn": mpn, "lcsc": lcsc, "company_id": company_id,
        "events": rows, "balance": _round(bal), "value_usd": _round(val),
        "avg_usd": _round(avg),
        "first_short": next((r["date"] for r in rows if r["short"]), None),
    }


def check_shortages(db: Session, candidates: list[dict],
                    company_id: int | None = None, exclude_draw_ids=(),
                    exclude_adjustment_ids=()) -> list[dict]:
    """Would these draws take stock below zero at ANY point from their date on?

    A full-timeline check, not a point check: inserting a draw at a historical
    date must not push a LATER event's balance negative either. Quantities only
    — no FX — so it is cheap enough to run on every write. Each candidate is
    `{component_id?, mpn?, lcsc?, qty, date, label?, company_id?}`; the return
    value is one entry per short part, empty when everything is covered.

    A candidate is checked against its company's stock (decision 0064): its own
    `company_id`, else the argument. Both come through `stock_scope`, so they are
    None — one pool — while the companies share one.

    `exclude_draw_ids` and `exclude_adjustment_ids` leave existing rows out of
    the replay: a draw or a loss that is about to move to another company's
    stock, checked as a candidate there.
    """
    by_company: dict[int | None, list] = {}
    skip = set(exclude_draw_ids or ())
    skip_adj = set(exclude_adjustment_ids or ())

    def events_of(cid: int | None) -> list:
        if cid not in by_company:
            by_company[cid] = [e for e in _pool_events(db, cid)[0]
                               if not (e[1] == "use" and e[2].id in skip)
                               and not (e[1] == "adj" and e[2].id in skip_adj)]
        return by_company[cid]

    out: list[dict] = []
    # candidates already accepted in THIS batch count against the same stock —
    # two BOM lines drawing one part must not each see the full balance
    accepted: list[tuple[set, str, float, int | None]] = []
    for cand in candidates:
        ccid = cand.get("company_id", company_id)
        events = events_of(ccid)
        want = set(_identity_keys(cand.get("component_id"),
                                  cand.get("mpn") or "", cand.get("lcsc") or ""))
        cdate = cand.get("date") or "9999"
        need = float(cand.get("qty") or 0.0)
        if not want or need <= 0:
            continue
        # this part's timeline, reduced to signed quantities; the candidate is a
        # "use", so on its own date it sorts after adj/buy rows (adj < buy < use)
        # and a same-day invoice covers it. Stable sort keeps it after equal keys.
        entries: list[tuple[tuple[str, str], float, bool]] = []
        for date_iso, kind, row in events:
            keys = set(_identity_keys(getattr(row, "component_id", None),
                                      getattr(row, "mpn", "") or "",
                                      getattr(row, "lcsc", "") or ""))
            if not (keys & want):
                continue
            q = (row.qty or 0.0) if kind == "buy" else \
                (-(row.qty or 0.0) if kind == "use" else (row.qty_delta or 0.0))
            entries.append((((date_iso or "9999"), kind), q, False))
        for pw, pd, pq, pc in accepted:
            if pw & want and pc == ccid:
                entries.append((((pd or "9999"), "use"), -pq, False))
        entries.append(((cdate, "use"), -need, True))
        entries.sort(key=lambda e: e[0])

        bal, on_hand, min_after = 0.0, 0.0, None
        for _k, q, is_cand in entries:
            if is_cand:
                on_hand = bal
            bal += q
            if is_cand:
                min_after = bal
            elif min_after is not None and bal < min_after:
                min_after = bal
        if min_after is not None and min_after < -0.0001:
            out.append({
                "component_id": cand.get("component_id"), "mpn": cand.get("mpn") or "",
                "lcsc": cand.get("lcsc") or "", "label": cand.get("label") or "",
                "date": cand.get("date") or "", "needed": _round(need),
                "on_hand": _round(on_hand), "short": _round(-min_after),
                "company_id": ccid,
            })
        else:
            accepted.append((want, cdate, need, ccid))
    return out


def check_purchase_loss(db: Session, losses: list[dict]) -> list[dict]:
    """Would taking this much OFF a purchase strand draws already made?

    The mirror of `check_shortages`, and it delegates to it: removing X units of
    a purchase dated D lowers the balance from D onward by exactly as much as
    adding a draw of X on D, so one full-timeline replay answers both questions.

    Only the draw side was ever guarded. Nothing stopped a document being
    force-deleted, a quantity being cut or a component link being re-keyed out
    from under the consumptions priced against it — the draws survive the
    purchase (they are their own rows, and `lot_line_id` is a soft pointer), so
    the pool went negative and the run went on paying for stock no invoice
    bought. User decision 2026-09-19: refuse the change that would strand a
    draw, and allow every change that stays covered. The blunter rule — "this
    part has any consumption at all" — was measured first and rejected: it
    locked 260 of 264 pooled part lines, i.e. every parts invoice older than the
    first batch that used it.

    Each entry is `{component_id?, mpn?, lcsc?, qty, date, label?}` where `qty`
    is the amount LOST. Entries at or below zero are ignored, so a caller can
    pass a whole document and let the ones that gain stock fall out.
    """
    return check_shortages(db, [dict(x) for x in losses if float(x.get("qty") or 0) > 0])


def batch_purchase_losses(db: Session, changes: list[dict]) -> list[dict]:
    """The NET stock a set of edits takes off each pool key, as check entries.

    Guarding one line at a time is wrong for a batch, and that is the whole
    reason batch editing exists (user decision 2026-09-19): swapping the
    component mapping of two positions is legal — each key ends with exactly
    what it started with — but the first half of the swap, judged alone, looks
    like a total loss. Netting the batch first is what makes the swap possible.

    Each change is `{line, qty?, component_id?, mpn?, lcsc?, pooled_after?}`:
    the line as it is now, plus the values it is moving to. `qty=None` keeps the
    quantity; `pooled_after=False` says the line stops being pool stock at all
    (deleted, voided, charged to a run, marked excluded).

    The date used for a loss is the EARLIEST document date among the lines that
    caused it, because that is when the balance starts being short.
    """
    delta: dict[tuple, float] = defaultdict(float)
    info: dict[tuple, dict] = {}
    for ch in changes:
        li: M.RunCostLine = ch["line"]
        was_pooled = bool(pooled_part_lines(db, [li]))
        doc = db.get(M.RunCostDocument, li.document_id)
        date_iso = (doc.doc_date if doc else "") or ""
        # The buyer's stock (decision 0064). None while the companies share one.
        cid = stock_scope(db, doc.company_id if doc else None)

        def note(key: tuple, component_id, mpn, lcsc, label):
            cur = info.setdefault(key, {"component_id": component_id, "mpn": mpn or "",
                                        "lcsc": lcsc or "", "date": date_iso, "label": label,
                                        "company_id": key[0]})
            if date_iso and (not cur["date"] or date_iso < cur["date"]):
                cur["date"] = date_iso

        if was_pooled:
            old_key = (cid, _key(li))
            delta[old_key] -= li.qty or 0.0
            note(old_key, li.component_id, li.mpn, li.lcsc, li.label or li.mpn or f"line {li.id}")

        if ch.get("pooled_after", True):
            new_cid = ch["component_id"] if "component_id" in ch else li.component_id
            new_mpn = ch["mpn"] if "mpn" in ch else li.mpn
            new_lcsc = ch["lcsc"] if "lcsc" in ch else li.lcsc
            new_qty = ch["qty"] if ch.get("qty") is not None else (li.qty or 0.0)
            new_part = (f"c{new_cid}" if new_cid else
                        f"m{_strip(new_mpn)}" if new_mpn else
                        f"l{_strip(new_lcsc)}" if new_lcsc else "")
            new_key = (cid, new_part)
            if new_part:
                delta[new_key] += new_qty
                note(new_key, new_cid, new_mpn, new_lcsc,
                     ch.get("label") or li.label or new_mpn or f"line {li.id}")

    losses = [dict(info[k], qty=-d) for k, d in delta.items() if d < -1e-9 and k in info]
    return check_purchase_loss(db, losses)


def pooled_part_lines(db: Session, lines: list[M.RunCostLine]) -> list[M.RunCostLine]:
    """The subset of `lines` that actually feeds the pool, by the SAME test
    `_pool_events` uses — a live, unallocated, non-excluded part leaf whose
    document is not a proforma. A header is excluded by the caller, which
    already knows `header_ids`."""
    out = []
    for li in lines:
        if not is_stock(li) or li.voided_at is not None:
            continue
        if li.run_id is not None or (li.allocate or "none") == EXCLUDED:
            continue
        doc = db.get(M.RunCostDocument, li.document_id)
        if doc is None or (doc.doc_type or "invoice") == "proforma":
            continue
        out.append(li)
    return out


# ------------------------------------------------- closing the books (0044)

def closed_runs(db: Session) -> dict[int, M.ProductionRun]:
    """Every batch whose books are closed, by id. One query — `document_json`
    fetches it once per register and hands it to each document, because the
    register renders ~90 of them and a query apiece is a query apiece."""
    return {r.id: r for r in db.query(M.ProductionRun)
            .filter(M.ProductionRun.closed_at.isnot(None)).all()}


def closed_lock(db: Session, doc: M.RunCostDocument,
                closed: dict[int, M.ProductionRun] | None = None) -> list[dict]:
    """The CLOSED batches this document charges, or `[]` when it is editable.

    Decision 0044. A batch's direct costs are recomputed from its lines on every
    read — `qty x unit_price x fx`, nothing snapshotted — so correcting a typo on
    a 2024 assembly invoice moves that batch's total, its per-device cost, and
    the cost of every order that shipped one of its units. Closing the batch
    stops that: the documents behind it become read-only and the only way to move
    the figure is a CORRECTION document, dated when the correction was made.

    Three rules, and each is load-bearing:

    * **Direct costs only.** A `part` line feeding the pool cannot change a
      closed batch's cost, because its draws snapshotted `unit_cost_usd` at draw
      time. Locking pool invoices would block ordinary stock corrections and
      protect nothing.
    * **A document that POSTDATES the close is not locked.** That is what makes
      the correction path work without a special case for it: a document written
      after the books closed is, by definition, the correction. It also means an
      ordinary invoice that simply arrived late can still be entered and fixed.
    * **The whole document locks**, not the offending line. A document with one
      line on a closed batch and one on an open batch is a single printed page,
      and re-keying its lines is exactly the kind of edit that would move the
      closed figure.
    """
    live = [li for li in doc.lines if li.voided_at is None]
    run_ids = {li.run_id for li in live if li.run_id is not None}
    if doc.run_id is not None:
        run_ids.add(doc.run_id)
    if not run_ids:
        return []
    if closed is None:
        closed = closed_runs(db)
    created = doc.created_at
    out = []
    for run in (closed[rid] for rid in run_ids if rid in closed):
        # A document created after the close is the correction, not the thing
        # being corrected. `created_at` and `closed_at` are both server-side
        # timestamps, so the comparison is on one clock.
        if created is not None and run.closed_at is not None and created > run.closed_at:
            continue
        out.append({"run_id": run.id, "label": run.label,
                    "closed_at": run.closed_at.isoformat() if run.closed_at else None,
                    "closed_by": run.closed_by or ""})
    return sorted(out, key=lambda r: r["run_id"])


def close_snapshot(db: Session, run: M.ProductionRun,
                   register: dict | None = None) -> tuple[float, int]:
    """What this batch costs in USD, and over how many PRODUCED units, right now.

    Recorded on the run when it closes so a later correction reads as a VARIANCE
    against the figure that was quoted, rather than as a number that was always
    this way.

    Read from the invoice register's `by_run_usd` rather than from
    `run_actuals`, for one reason: `by_run_usd` is what `orders.per_device_cost_usd`
    divides, so it is the figure that actually reaches a customer's invoice
    (decision 0043). `run_actuals` returns the same arithmetic in the project's
    DISPLAY currency, which is editable — a snapshot taken in it would mean
    something different after somebody changed the project's currency.
    """
    reg = register if register is not None else invoice_register(db)
    money = ((reg.get("by_run_usd") or {}).get(str(run.id))
             or (reg.get("by_run_usd") or {}).get(run.id) or {})
    made = produced_counts(db, [run.id]).get(run.id, 0)
    return float(money.get("total_usd") or 0.0), made


def purchase_loss_of(db: Session, li: M.RunCostLine, *, qty: float | None = None,
                     component_id: int | None = ..., mpn: str | None = None,
                     lcsc: str | None = None) -> dict:
    """One `check_purchase_loss` entry for taking `li` away, or shrinking it to
    `qty`. Identity defaults to the line's own; pass `component_id`/`mpn`/`lcsc`
    to describe a RE-KEY, which is a total loss to the old key."""
    doc = db.get(M.RunCostDocument, li.document_id)
    rekeyed = (component_id is not ... and component_id != li.component_id) \
        or (mpn is not None and mpn != li.mpn) \
        or (lcsc is not None and lcsc != li.lcsc)
    lost = (li.qty or 0.0) if (qty is None or rekeyed) else max(0.0, (li.qty or 0.0) - qty)
    return {"component_id": li.component_id, "mpn": li.mpn or "", "lcsc": li.lcsc or "",
            "qty": lost, "date": (doc.doc_date if doc else "") or "",
            "label": li.label or li.mpn or f"line {li.id}",
            # The buyer's stock loses it (decision 0064).
            "company_id": stock_scope(db, doc.company_id if doc else None)}


def resolve_pool_identity(db: Session, component_id: int | None, mpn: str, lcsc: str,
                          as_of: str | None = None, company_id: int | None = None) -> dict | None:
    """Find the pool entry a part belongs to, by identity-key OVERLAP.

    A draw must land on the SAME key the purchases did, or the part silently
    splits into two pool entries with two averages — the exact drift `_key`'s
    docstring exists to prevent. `_key` alone cannot do this: it PREFERS
    `component_id`, so a caller who knows only an MPN produces `m<MPN>` while the
    purchases sit under `c<id>`, the lookup misses, and the draw is priced at
    ZERO and filed under a brand-new key.

    Verified 2026-09-18: enclosure 35.0207000.BL is `c323` in the pool, and a
    draw entered by MPN alone priced at $0.00 against a real $3.70 average.
    `check_shortages` already matched on overlap, so the shortage guard passed
    and only the money was wrong — the worst shape for a bug.

    Returns the pool entry (with its `component_id`, `mpn`, `lcsc` and `avg_usd`)
    so the caller can adopt the identity, or None when nothing matches.
    """
    keys = set(_identity_keys(component_id, mpn or "", lcsc or ""))
    if not keys:
        return None
    for p in pool_state(db, as_of=as_of, company_id=company_id).values():
        if keys & set(_identity_keys(p.get("component_id"), p.get("mpn") or "",
                                     p.get("lcsc") or "")):
            return p
    return None


def average_cost(db: Session, project_id: int | None, key: str,
                 company_id: int | None = None) -> float:
    return pool_state(db, project_id, company_id=company_id).get(key, {}).get("avg_usd", 0.0)


def _as_dt(date_iso: str):
    """ISO date -> aware datetime for fx.rates_at; falls back to 'now'."""
    from datetime import datetime, timezone
    if not date_iso:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(date_iso).replace(tzinfo=timezone.utc)
    except ValueError:
        return datetime.now(timezone.utc)


# ------------------------------------------------------------ run actuals

def run_actuals(db: Session, run: M.ProductionRun) -> dict:
    """What this run really cost: components drawn from the pool + direct lines
    + attrition charged to it, in the project's display currency, next to the
    planned figure so the delta is visible."""
    project = db.get(M.Project, run.project_id)
    cur = display_currency(project)
    rates = fx.rates_at(db, run_pricing_date(run))
    unknown: set[str] = set()

    def to_display(amount_usd: float) -> float:
        v, known = fx.convert(amount_usd, "USD", cur, rates)
        if not known:
            unknown.add(cur)
        return v

    # 1. components drawn from the pool
    cons = live_consumption(db, run_id=run.id).all()
    comp_usd = sum((c.qty or 0) * (c.unit_cost_usd or 0) for c in cons)
    by_basis: dict[str, float] = defaultdict(float)
    for c in cons:
        by_basis[c.basis or "manual"] += (c.qty or 0) * (c.unit_cost_usd or 0)

    # 2. direct lines on documents pointing at this run (or lines carrying run_id)
    candidates = (
        db.query(M.RunCostLine)
        .join(M.RunCostDocument, M.RunCostLine.document_id == M.RunCostDocument.id)
        .filter(
            M.RunCostLine.voided_at.is_(None),
            or_(M.RunCostLine.run_id == run.id, M.RunCostDocument.run_id == run.id),
        )
        .all()
    )
    headers = header_ids(db)
    lines = []
    for li in candidates:
        if li.id in headers:
            continue  # split position: its children carry the money
        if li.allocate == EXCLUDED:
            continue  # recorded for reconciliation, charged to nobody on purpose
        if li.allocate == OVERHEAD:
            continue  # a company cost (decision 0068): the overhead bucket holds it, never a batch
        if li.transformation_id:
            continue  # a conversion cost: in a prepared part's lot, paid when a step draws it
        if li.run_id == run.id:
            lines.append(li)
            continue
        # Document-level ownership only claims lines that name no destination of
        # their own. Without this, an invoice assigned to run A with a line
        # allocated to run B is charged to BOTH.
        if li.run_id is None and li.project_id is None:
            lines.append(li)
    by_kind: dict[str, float] = defaultdict(float)
    # actuals per production step ("pcba:setup", ...); lines without a step key
    # bucket under "~<kind>" so coarse invoices still show up in the comparison
    actual_by_step: dict[str, float] = defaultdict(float)
    step_sources: dict[str, dict[int, dict]] = {}
    direct_usd = 0.0
    for li in lines:
        doc = db.get(M.RunCostDocument, li.document_id)
        if is_stock(li) and li.run_id is None:
            continue  # that purchase belongs to the pool, not to this run
        cur_l = li.currency or (doc.currency if doc else "USD")
        # One rule for per_device everywhere (`effective_qty`): charging at
        # plan_qty here while reconciling at qty_good would disagree by the yield.
        amount = effective_qty(li, doc, db) * (li.unit_price or 0)
        if doc and doc.fx_rate_usd and cur_l.upper() != "USD":
            usd = amount * doc.fx_rate_usd
        else:
            usd, known = _to_usd(amount, cur_l, rates)
            if not known:
                unknown.add(cur_l)
        direct_usd += usd
        # The coarse bucket, DERIVED from the step (decision 0047). It used to be
        # a column typed beside the step and free to disagree with it.
        by_kind[cost_steps.kind_of(li.plan_key or "")] += usd
        # Production-step identity (services/cost_steps.py): a line billed
        # under "pcba:setup" is the actual of the planned cost item carrying
        # the same step_key, whatever the vendor called it on paper.
        step = li.plan_key if cost_steps.stage_of(li.plan_key) else ""
        skey = step or f"~{cost_steps.kind_of(li.plan_key or '')}"
        actual_by_step[skey] += usd
        # remember WHICH document the money came from, so the run view can
        # answer "who billed this step" without a second sweep
        src = step_sources.setdefault(skey, {}).setdefault(li.document_id, {
            "document_id": li.document_id,
            "doc_number": (doc.doc_number if doc else "") or "",
            "supplier": (doc.supplier if doc else "") or "",
            "doc_date": (doc.doc_date if doc else "") or "",
            "amount_usd": 0.0,
        })
        src["amount_usd"] += usd

    # 3. attrition explicitly charged to this run
    adjs = db.query(M.ComponentStockAdjustment).filter_by(charge_run_id=run.id).all()
    pool = pool_state(db, run.project_id, company_id=run_scope(db, run))
    attrition_usd = 0.0
    for a in adjs:
        unit = a.unit_cost_usd
        if unit is None:
            unit = pool.get(_key(a), {}).get("avg_usd", 0.0)
        attrition_usd += abs(a.qty_delta or 0) * (unit or 0)

    total_usd = comp_usd + direct_usd + attrition_usd
    qty_plan = max(run.plan_qty or run.qty or 1, 1)
    good = good_units(db, run)

    planned = None
    eff_totals: dict = {}
    try:
        from .project_bom import run_effective
        eff_totals = run_effective(db, run).get("totals") or {}
        planned = eff_totals.get("run_total")
    except Exception:  # noqa: BLE001 — a missing snapshot must not break actuals
        planned = None

    # --- plan-vs-actual per production step (user design 2026-07-28): planned
    # cost items carry `step_key`, invoice lines carry the same key in
    # `plan_key`; matching is on the KEY, so it survives vendors wording the
    # same step differently and works for every cost added to a run or project.
    steps_cmp: list[dict] = []
    try:
        from . import cost_state
        from .project_bom import _cost_price_at
        snap = db.get(M.ProjectSnapshot, run.snapshot_id) if run.snapshot_id else None
        _x, cost_items, _rev = cost_state.items_for(db, run.project_id, snap)
        planned_by_step: dict[str, float] = defaultdict(float)
        for c in cost_items:
            if not c.step_key:
                continue
            price = _cost_price_at(c, good)
            per_run = price * good if c.basis == "per_device" else price
            usd_v, _known = _to_usd(per_run, c.currency or "USD", rates)
            planned_by_step[c.step_key] += usd_v
        for key in sorted(set(planned_by_step) | {k for k in actual_by_step if not k.startswith("~")}):
            info = cost_steps.STEPS.get(key)
            steps_cmp.append({
                "key": key,
                "label": info[0] if info else key,
                "stage": key.split(":", 1)[0],
                "planned_usd": _round(planned_by_step.get(key)),
                "actual_usd": _round(actual_by_step.get(key)),
                "delta_usd": _round((actual_by_step.get(key) or 0)
                                    - (planned_by_step.get(key) or 0)),
                "sources": sorted((dict(v, amount_usd=_round(v["amount_usd"]))
                                   for v in (step_sources.get(key) or {}).values()),
                                  key=lambda x: -(x["amount_usd"] or 0)),
            })
        # STAGE ROLLUP (user design 2026-07-28): a coarse `<stage>:general` bill
        # cannot be compared step-by-step, so its row compares against the SUM of
        # the stage's planned steps instead — minus any steps billed in detail,
        # whose own rows stay. Planned-only step rows inside such a stage are
        # folded into the rollup (their plan is inside the general figure), so
        # the table never double-signals the same money.
        for stage in cost_steps.STAGES:
            gkey = f"{stage}:general"
            gact = actual_by_step.get(gkey)
            if not gact:
                continue
            detailed_billed = {k for k in actual_by_step
                               if k.startswith(stage + ":") and k != gkey}
            remainder_plan = sum(v for k, v in planned_by_step.items()
                                 if k.startswith(stage + ":") and k not in detailed_billed)
            folded = [r for r in steps_cmp
                      if r["stage"] == stage and r["key"] != gkey
                      and r["key"] not in detailed_billed]
            for r in folded:
                steps_cmp.remove(r)
            grow = next((r for r in steps_cmp if r["key"] == gkey), None)
            if grow is None:
                continue
            grow["planned_usd"] = _round(remainder_plan) if remainder_plan else None
            grow["delta_usd"] = (_round(gact - remainder_plan)
                                 if remainder_plan else None)
            grow["rollup"] = True
            grow["label"] = (cost_steps.STEPS[gkey][0] +
                             " — compared against the stage's planned steps summed"
                             + (f" ({len(folded)} folded in)" if folded else ""))

        # Materials rows, so the table covers ALL of a run's money, not just fees:
        # planned = the effective BOM's parts total, actual = the pool draws.
        parts_planned = eff_totals.get("parts_total")
        if parts_planned is not None and cur.upper() != "USD":
            parts_planned, _pk = fx.convert(parts_planned, cur, "USD", rates)
        if (parts_planned is not None) or comp_usd:
            steps_cmp.insert(0, {
                "key": "parts:pool", "label": cost_steps.STEPS["parts:pool"][0],
                "stage": "parts", "planned_usd": _round(parts_planned),
                "actual_usd": _round(comp_usd),
                "delta_usd": _round(comp_usd - parts_planned) if parts_planned is not None else None,
                "sources": [],  # pool draws — the purchase documents live in Parts stock
            })
        if attrition_usd:
            steps_cmp.append({
                "key": "parts:attrition", "label": cost_steps.STEPS["parts:attrition"][0],
                "stage": "parts", "planned_usd": None,
                "actual_usd": _round(attrition_usd), "delta_usd": None,
                "sources": [],
            })
        for key, v in sorted(actual_by_step.items()):
            if key.startswith("~") and v:
                steps_cmp.append({"key": key, "label": f"unclassified ({key[1:]})",
                                  "stage": None, "planned_usd": None,
                                  "actual_usd": _round(v), "delta_usd": None,
                                  "sources": sorted((dict(v, amount_usd=_round(v["amount_usd"]))
                                   for v in (step_sources.get(key) or {}).values()),
                                  key=lambda x: -(x["amount_usd"] or 0)),})
    except Exception:  # noqa: BLE001 — the comparison must never break actuals
        steps_cmp = []

    actual_total = _round(to_display(total_usd))

    # A BATCH HAS NO SALE. It is a production record: what it cost, and how many
    # devices it made. Revenue and margin belong to the ORDER, and the two are
    # joined per UNIT — a device carries its batch's `per_device_cost_usd` onto
    # whatever order ships it (user decision 2026-09-19).
    #
    # The run used to price its own sale from `sale_unit_price` x `qty_sold`.
    # That could not express one batch serving two orders (CE_Dongle_V2 Batch 7
    # named both ZAL 03/2026 and 04/2026 in a free-text field), a batch with no
    # order yet (Batch 8 carried a typed forecast of 176,000 PLN), or a net
    # against a gross price (run 2164 read 553 where its order reads 450 + 23%
    # VAT). Decision 0003 retired it; this removes the last reader.

    return {
        "currency": cur,
        "qty_planned": qty_plan,
        # The DERIVED figure (decision 0030), so every reader divides by what
        # passed. `qty_good_source` says where it came from: "devices" is the
        # count of `produced` events, "typed" is the legacy field or, failing
        # that, the boards ordered from JLC.
        "qty_good": good,
        "qty_good_source": "devices" if produced_counts(db, [run.id]).get(run.id) else "typed",
        "qty_good_typed": run.qty_good,
        # What one device of this batch cost — the figure it carries onto the
        # order that ships it, and the only number a batch contributes to a
        # sale. Null until the batch has device records: a cost divided by a
        # PLANNED quantity is an estimate wearing an actual's clothes.
        "per_device_cost": (
            _round(to_display(total_usd) / produced)
            if (produced := produced_counts(db, [run.id]).get(run.id) or 0) else None
        ),
        "components": _round(to_display(comp_usd)),
        "components_by_basis": {k: _round(to_display(v)) for k, v in sorted(by_basis.items())},
        "direct": _round(to_display(direct_usd)),
        "by_kind": {k: _round(to_display(v)) for k, v in sorted(by_kind.items())},
        # planned-vs-billed per production step, USD (see services/cost_steps.py)
        "steps": steps_cmp,
        "attrition": _round(to_display(attrition_usd)),
        "total": actual_total,
        # The same figure in USD. The display currency is a PROJECT setting and
        # editable, so it cannot be compared against `closed_cost_usd`, which is
        # pinned in USD at the moment the books closed (decision 0044). The batch
        # page reads this one for the variance.
        "total_usd": _round(total_usd),
        "per_device": _round((actual_total or 0) / good) if actual_total is not None else None,
        "planned_total": _round(planned),
        # delta_pct is deliberately null when nothing was planned — a late
        # position has no percentage, only an absolute figure.
        "delta": _round((actual_total or 0) - planned) if planned is not None else None,
        "delta_pct": (
            _round(((actual_total or 0) - planned) / planned * 100)
            if planned not in (None, 0) else None
        ),
        "document_count": len({li.document_id for li in lines}),
        "consumption_count": len(cons),
        "unknown_rates": sorted(unknown),
    }


# ------------------------------------------------------------- parts stock

def _attach_projects(db: Session, rows: list[dict]) -> None:
    """Which projects use each part, from every project's latest READY snapshot.

    Computed here rather than in the browser because the join is by IDENTITY —
    a BOM line carries `component_id`, `lcsc` and `mpn`, and any one of the three
    may be the only one that matches (`_identity_keys`). The older
    `GET /api/jlc/stock/usage` inverted it project-first and matched on the LCSC
    code alone, which silently skipped every part JLC does not hold — the
    enclosures and antennas, which are exactly the ones whose usage nobody else
    reports.

    One entry per project and board, because the same component appears on
    several boards of one project with different reference designators.
    """
    index: dict[str, list[dict]] = {}
    for proj in db.query(M.Project).order_by(M.Project.name).all():
        snap = (db.query(M.ProjectSnapshot)
                  .filter_by(project_id=proj.id, status="ready")
                  .order_by(M.ProjectSnapshot.created_at.desc()).first())
        if snap is None:
            continue
        for li in (db.query(M.SnapshotBomLine)
                     .filter(M.SnapshotBomLine.snapshot_id == snap.id,
                             M.SnapshotBomLine.variant == "").all()):
            entry = {"project_id": proj.id, "project_name": proj.name,
                     "board": li.board or "", "refs": li.refs or "",
                     "qty_per_device": float(li.qty or 0.0)}
            for key in _identity_keys(li.component_id, li.mpn or "", li.lcsc or ""):
                index.setdefault(key, []).append(entry)

    for row in rows:
        seen: dict[tuple, dict] = {}
        for key in _identity_keys(row.get("component_id"), row.get("mpn") or "",
                                  row.get("lcsc") or ""):
            for entry in index.get(key, []):
                # One row per (project, board): a part matched on two of its
                # three keys would otherwise be listed twice.
                seen.setdefault((entry["project_id"], entry["board"]), entry)
        used = sorted(seen.values(),
                      key=lambda e: (e["project_name"], e["board"]))
        row["projects"] = used
        row["project_count"] = len({e["project_id"] for e in used})
        # What one device of everything that uses this part costs in stock, and
        # how many of those JLC's holding covers.
        per_device = sum(e["qty_per_device"] for e in used)
        row["qty_per_device"] = round(per_device, 4)
        # Counted against the stock that can actually be built with: JLC's own
        # count for a consigned part, our remaining pool for one JLC never sees.
        # Using JLC's figure for both reported ZERO coverable enclosures while
        # the shelf held plenty, because JLC has never held an enclosure.
        on_hand = (row.get("held_qty") or 0) if row.get("state") != "pool_only" \
            else (row.get("remaining_qty") or 0)
        row["devices_coverable"] = int(on_hand // per_device) if per_device > 0 else None


def pool_series(events, keys: set[str], since: str, drop: set[int] = frozenset(),
                 extra: list[tuple[str, float]] = (), component_id: int | None = None) -> dict:
    """One part's pool, day by day from `since`: the balance before it
    (`start`) and, for each day with an event, the lowest balance during it
    and the balance at its end. `keys` are every name the part has. With a
    `component_id`, the part is that component: its events, and those with
    no component that share a name, never another component's."""
    entries = []
    for date_iso, kind, row in events:
        if kind == "use" and row.id in drop:
            continue
        rc = getattr(row, "component_id", None)
        named = set(_identity_keys(None, getattr(row, "mpn", "") or "", getattr(row, "lcsc", "") or ""))
        if component_id is None:
            if not (keys & (named | set(_identity_keys(rc, "", "")))):
                continue
        elif rc is not None:
            if rc != component_id:
                continue            # another component, whatever names it shares
        elif not (keys & named):
            continue
        q = (row.qty or 0.0) if kind == "buy" else (-(row.qty or 0.0) if kind == "use" else (row.qty_delta or 0.0))
        entries.append((((date_iso or "9999"), kind), q))
    entries += [(((d or "9999"), "use"), -q) for d, q in extra]
    entries.sort(key=lambda e: e[0])
    bal, start, days = 0.0, None, {}
    for (day, _k), q in entries:
        if day >= (since or "") and start is None:
            start = bal
        bal += q
        if day >= (since or ""):
            lo, _end = days.get(day, (bal, bal))
            days[day] = (min(lo, bal), bal)
    return {"start": bal if start is None else start, "days": sorted([d, lo, end] for d, (lo, end) in days.items())}


def value_on(series: dict, day: str) -> float:
    """The series' balance on `day`: that day's lowest, else the end of the
    last day before it, else its start."""
    out = series["start"]
    for d, lo, end in series["days"]:
        if d == day:
            return lo
        if d > day:
            break
        out = end
    return out


def stock_targets(db: Session, entries) -> tuple[set, dict]:
    """The parts a change touches, as `stock_view` compares them, from
    `(stock scope, component_id, mpn, lcsc, label)` entries. A part with a
    library component is that component's pool, once per scope, whatever
    names its lines carry — as a draw sees it. A part with no component is
    the pool of its names. Returns `(targets, names)`."""
    comp: dict[tuple, set] = defaultdict(set)
    label_of: dict[tuple, str] = {}
    targets: set[tuple] = set()
    names: dict = {}
    for sc, cid, mpn, lcsc, label in entries:
        keys = set(_identity_keys(cid, mpn or "", lcsc or ""))
        if not keys:
            continue
        if cid:
            comp[(sc, cid)] |= keys
            label_of.setdefault((sc, cid), label or mpn or lcsc or f"component #{cid}")
        else:
            targets.add((sc, frozenset(keys), None))
            names.setdefault(frozenset(keys), label or mpn or lcsc or "part")
    for (sc, cid), keys in comp.items():
        targets.add((sc, frozenset(keys), cid))
        names.setdefault(frozenset(keys), label_of[(sc, cid)])
    return targets, names


def stock_view(db: Session, targets: set[tuple]) -> dict:
    """Each `stock_targets` target → its `pool_series` over all time: what
    `stock_worse` compares before and after a change."""
    events = {sc: _pool_events(db, sc)[0] for sc in {t[0] for t in targets}}
    return {t: pool_series(events[t[0]], set(t[1]), "", component_id=t[2]) for t in targets}


def stock_worse(now: dict, after: dict, names: dict) -> list[str]:
    """`<part> short <n> on <day>` for each part whose pool `after` goes below
    zero and below where it is `now`, on any day (decision 0073). A deficit
    the pool already had is no reason to refuse."""
    out = []
    for key, a in after.items():
        n = now.get(key)
        if n is None:
            continue
        worst, when = 0.0, ""
        for day in sorted({d for d, _l, _e in a["days"]} | {d for d, _l, _e in n["days"]}):
            gap = min(0.0, value_on(n, day)) - value_on(a, day)
            if gap > worst + 1e-6:
                worst, when = gap, day
        if worst > 1e-4:
            out.append(f"{names.get(key[1], '?')} short {round(worst, 4):g} on {when}")
    return list(dict.fromkeys(out))      # one part known by two sets of names reads once


def _identity_keys(component_id: int | None, mpn: str, lcsc: str) -> list[str]:
    """Every key a part could be known by, so the two sides of `parts_stock` meet
    even when one of them has not been resolved to a library component yet."""
    keys = []
    if component_id:
        keys.append(f"c{component_id}")
    if mpn:
        keys.append(f"m{_strip(mpn)}")
    if lcsc:
        keys.append(f"l{_strip(lcsc)}")
    return keys


#: JLCPCB dates everything — order numbers, invoices, settlements — in China
#: time. `pool_state` cuts on those same date strings, so a stock snapshot taken
#: at a UTC instant must be converted before it can be used as a cutoff.
#: Measured 2026-09-18: parts order `20146320202608060318425` was placed at
#: 03:18:42 China time and the snapshot fetched 4m44s later, at 19:23:26 UTC on
#: the 5th. Cutting on the UTC date excludes an order the snapshot already
#: counts, which put 13 parts out by exactly their last purchase.
JLC_TZ = timezone(timedelta(hours=8))


def _jlc_date(ts) -> str | None:
    """The JLC-calendar date of an instant, as `pool_state` spells dates."""
    return ts.astimezone(JLC_TZ).date().isoformat() if ts is not None else None


def parts_stock(db: Session, company_id: int | None = None) -> dict:
    """Every part the company has money in, or that JLCPCB physically holds — with
    both measurements side by side.

    These answer different questions about the same parts and are routinely
    different, which is the point of showing them together:

    - **physical** (`JlcStockItem`): how many pieces JLC holds on consignment,
      valued at the cached MARKET unit price;
    - **money** (the cost pool): how much was actually PAID for parts, how much of
      that has been drawn by runs, and what the unconsumed remainder cost.

    The two derived gaps are the useful part:

    - `delta_qty` = held - remaining. Positive means JLC holds more than the
      platform has paid for; negative means the pool still counts parts JLC no
      longer has — boards were built without recording the draw, or stock was lost
      (record it with `ComponentStockAdjustment`).
    - `delta_value_usd` = `(market_unit - paid_unit) x remaining_qty`, i.e. what
      the unconsumed remainder would be worth at today's price versus what it cost.
      Deliberately valued on the SAME quantity — comparing "held at market" against
      "remaining at cost" would just restate the quantity gap as money.

    `state` classifies each row, and `jlc_only` is a **missing-invoice detector**:
    JLC is holding stock the platform has no purchase for. `pool_only` is normal
    for parts bought elsewhere (enclosures, antennas) or fully consumed.

    `company_id` shows one company's money (decision 0064). JLC holds one
    shelf for one account, so its side is always the whole shelf.
    """
    pool = pool_state(db, company_id=company_id)
    items = db.query(M.JlcStockItem).all()

    # THE TWO SIDES MUST BE READ AT THE SAME MOMENT. `JlcStockItem` is a snapshot
    # frozen when someone last pressed sync; the pool runs to today. Subtracting
    # one from the other reports every draw made SINCE the snapshot as stock JLC
    # is holding and we never paid for. On 2026-09-18 that was 33,246 pieces of
    # phantom gap, essentially all of it Batch 8's draw four weeks after the
    # snapshot, and it hid a real 3,866-piece one.
    sync_date = _jlc_date(max((i.updated_at for i in items), default=None))
    pool_at_sync = pool_state(db, as_of=sync_date, company_id=company_id) if sync_date else {}
    # How much has moved since, so the page can say the count is out of date
    # instead of quietly reporting a stale comparison as a discrepancy.
    events_since = sum(1 for d, _k, _r in _pool_events(db, company_id)[0]
                       if sync_date and d > sync_date)

    # index JLC stock under every identity it carries, so an unresolved pool line
    # keyed m<MPN> still meets the JLC row keyed c<component_id>. A key maps to a
    # LIST, not one item: JLC lists the same manufacturer part under several LCSC
    # codes (XL-1005SURC is both C25503345 and C965790), so first-match-wins showed
    # the SAME LED twice — once with the pool's money and no stock, once with 18,488
    # pieces and a bogus "no invoice" flag.
    by_key: dict[str, list[M.JlcStockItem]] = defaultdict(list)
    for it in items:
        for k in _identity_keys(it.component_id, it.mpn or "", it.lcsc or ""):
            by_key[k].append(it)

    comp_names: dict[int, str] = {}
    ids = {it.component_id for it in items if it.component_id}
    ids |= {p["component_id"] for p in pool.values() if p.get("component_id")}
    if ids:
        for c in db.query(M.Component).filter(M.Component.id.in_(ids)).all():
            comp_names[c.id] = c.name

    rows: list[dict] = []
    matched: set[int] = set()
    for key, p in pool.items():
        # every stock item sharing ANY identity with this pool entry, deduplicated
        found: dict[int, M.JlcStockItem] = {}
        for k in _identity_keys(p.get("component_id"), p.get("mpn", ""), p.get("lcsc", "")):
            for cand in by_key.get(k, []):
                found[cand.id] = cand
        matched.update(found)
        it = next(iter(found.values()), None)
        remaining = round(p["qty"], 4)
        # What WE said we had at the moment JLC counted. A part with no events
        # before the cutoff is absent from that replay, which means zero.
        at_sync = round((pool_at_sync.get(key) or {}).get("qty", 0.0), 4)
        paid_value = round(p["value_usd"], 4)
        # quantities ADD across codes — two LCSC codes are two reels of one part
        held = sum(c.qty or 0 for c in found.values())
        market_unit = next((c.unit_price_usd for c in found.values()
                            if c.unit_price_usd is not None), None)
        market_value = round(market_unit * held, 4) if market_unit is not None else None
        # the remainder priced at today's market, so the money delta is like-for-like
        remaining_market = round(market_unit * remaining, 4) if market_unit is not None else None
        rows.append({
            "key": key,
            "component_id": p.get("component_id"),
            "component_name": comp_names.get(p.get("component_id") or -1),
            "mpn": p.get("mpn") or (it.mpn if it is not None else ""),
            "lcsc": p.get("lcsc") or (it.lcsc if it is not None else ""),
            "description": next((c.description for c in found.values() if c.description), ""),
            # when JLC carries the part under more than one code, say so
            "jlc_codes": sorted({c.lcsc for c in found.values() if c.lcsc}),
            "bought": round(p["bought"], 4),
            "drawn": round(p["used"], 4),
            "lost": round(p["lost"], 4),
            "external": round(p["external"], 4),
            "remaining_qty": remaining,
            "remaining_at_sync_qty": at_sync,
            "paid_unit_usd": _round(p["avg_usd"]),
            "paid_value_usd": paid_value,
            "held_qty": held,
            "market_unit_usd": market_unit,
            "market_value_usd": market_value,
            "remaining_at_market_usd": remaining_market,
            # Both sides as they stood when JLC counted. Comparing today's pool
            # against that snapshot measures elapsed time, not disagreement.
            "delta_qty": round(held - at_sync, 4) if it is not None else None,
            "delta_value_usd": (round(remaining_market - paid_value, 4)
                                if remaining_market is not None else None),
            "state": "both" if it is not None else "pool_only",
            "unknown_rate": p.get("unknown_rate", False),
        })

    # JLC holds it, the platform has never paid for it -> the invoice is missing
    for it in items:
        if it.id in matched:
            continue
        if (it.qty or 0) <= 0:
            # An empty library entry holds nothing, so no invoice can be
            # missing for it. TMUX1208RSVR sat here at 0 pieces while JLC was
            # still sourcing a paid lot (2026-09-24) and counted as a missing
            # invoice.
            continue
        market_value = (round((it.unit_price_usd or 0) * it.qty, 4)
                        if it.unit_price_usd is not None else None)
        rows.append({
            "key": f"jlc{it.id}",
            "component_id": it.component_id,
            "component_name": comp_names.get(it.component_id or -1),
            "mpn": it.mpn or "", "lcsc": it.lcsc or "", "description": it.description or "",
            "bought": 0.0, "drawn": 0.0, "lost": 0.0, "external": 0.0,
            "remaining_qty": 0.0,
            "remaining_at_sync_qty": 0.0,
            "paid_unit_usd": None, "paid_value_usd": 0.0,
            "held_qty": it.qty, "market_unit_usd": it.unit_price_usd,
            "market_value_usd": market_value, "remaining_at_market_usd": 0.0,
            "delta_qty": float(it.qty), "delta_value_usd": None,
            "state": "jlc_only", "unknown_rate": False,
        })

    _attach_projects(db, rows)
    rows.sort(key=lambda r: -(r["paid_value_usd"] or 0.0))
    both = [r for r in rows if r["state"] == "both"]
    jlc_only = [r for r in rows if r["state"] == "jlc_only"]
    return {
        "parts": rows,
        "totals": {
            "parts": len(rows),
            "spent_usd": _round(sum(p["value_bought"] for p in pool.values())),
            "drawn_usd": _round(sum(p["value_used"] for p in pool.values())),
            "adjusted_usd": _round(sum(p["value_adj"] for p in pool.values())),
            "remaining_at_cost_usd": _round(sum(p["value_usd"] for p in pool.values())),
            # The SAME remainder priced two ways, over the parts that have both a
            # paid average and a market price — the only honest value comparison.
            "comparable_cost_usd": _round(sum(r["paid_value_usd"] for r in both
                                              if r["remaining_at_market_usd"] is not None)),
            "comparable_market_usd": _round(sum(r["remaining_at_market_usd"] for r in both
                                                if r["remaining_at_market_usd"] is not None)),
            "jlc_held_value_usd": _round(sum(r["market_value_usd"] or 0.0 for r in rows)),
            "jlc_held_qty": sum(r["held_qty"] for r in rows),
            # Pool says unconsumed, JLC no longer holds: unrecorded draws or losses.
            "over_pool_parts": sum(1 for r in both if (r["delta_qty"] or 0) < -0.5),
            "missing_invoice_parts": len(jlc_only),
            "missing_invoice_value_usd": _round(sum(r["market_value_usd"] or 0.0
                                                    for r in jlc_only)),
            "pool_only_parts": sum(1 for r in rows if r["state"] == "pool_only"),
            "unvalued_parts": sum(1 for r in rows if r["market_value_usd"] is None
                                  and r["held_qty"]),
            # Every quantity comparison above is AS OF this date, not today.
            "compared_as_of": sync_date,
            # Stock events after the snapshot. Not a fault — just the reason the
            # comparison is older than the pool, which the page must say out loud.
            "events_since_sync": events_since,
        },
        "last_sync": (last.isoformat()
                      if (last := max((i.updated_at for i in items), default=None)) else None),
    }


# -------------------------------------------------------- the invoice register


def _run_money(db: Session, rid: int, direct_usd: float, components_usd: float,
               rate_cache: dict, run: M.ProductionRun | None) -> dict:
    """What one run COST, in USD so the register compares runs across projects
    on one scale.

    Cost only. A batch earns nothing — an ORDER does, and the two meet per unit
    (`orders.per_device_cost_usd`). The register used to price the run's own
    sale here as well, which is how the same revenue came to exist twice and
    disagree; see the note in `run_actuals` above.
    """
    made = produced_counts(db, [rid]).get(rid) or 0
    cost = direct_usd + components_usd
    return {
        "direct_usd": _round(direct_usd),
        "components_usd": _round(components_usd),
        "total_usd": _round(cost),
        "produced": made,
        # What one device of this batch cost. Null until it has device records:
        # dividing by a PLANNED quantity is an estimate, and this figure is
        # carried onto real orders.
        "unit_cost_usd": _round(cost / made) if made else None,
    }


def doc_usd(db: Session, amount: float, doc: M.RunCostDocument, rate_cache: dict,
            unknown: set[str] | None = None) -> float:
    """An amount in `doc`'s currency, in USD: at the document's pinned rate when
    it has one, else the rate history at its date. The register and the twin
    prices (decision 0060) both convert through here, so a step's share of an
    invoice position is the same figure the register charges its batch."""
    cur = (doc.currency or "USD").upper()
    if cur == "USD" or not amount:
        return amount
    if doc.fx_rate_usd:
        return amount * doc.fx_rate_usd
    key = doc.doc_date or ""
    if key not in rate_cache:
        rate_cache[key] = fx.rates_at(db, _as_dt(key))
    value, known = fx.convert(amount, cur, "USD", rate_cache[key])
    if not known and unknown is not None:
        unknown.add(cur)
    return value


def leaf_line_usd(db: Session, lines: list[M.RunCostLine], rate_cache: dict | None = None
                  ) -> dict[int, tuple[float, str, int | None]]:
    """`line id -> (USD, destination, destination ref)` for LEAF positions, valued
    as the register values them: zero for a header (its children carry it), a
    voided line, or a line on a pro-forma (a quote, not money)."""
    cache = rate_cache if rate_cache is not None else {}
    hdrs = header_ids(db)
    docs: dict[int, M.RunCostDocument | None] = {}
    out: dict[int, tuple[float, str, int | None]] = {}
    for li in lines:
        if li.document_id not in docs:
            docs[li.document_id] = db.get(M.RunCostDocument, li.document_id)
        doc = docs[li.document_id]
        dest, ref = line_destination(li, doc)
        if (li.voided_at is not None or li.id in hdrs or doc is None
                or (doc.doc_type or "invoice") == "proforma"):
            out[li.id] = (0.0, dest, ref)
            continue
        out[li.id] = (doc_usd(db, effective_qty(li, doc, db) * (li.unit_price or 0), doc, cache),
                      dest, ref)
    return out


def invoice_register(db: Session, company_ids: list[int] | None = None) -> dict:
    """Every supplier document, where its money went, and whether any of it is
    unaccounted for.

    This is the "money is not disappearing anywhere" check (user requirement,
    2026-07-27). Three independent questions, answered side by side:

    1. Does each document's own arithmetic hold (`reconciled`)?
    2. Does every position have a destination — a run, a project, or the pool
       (`unassigned` + `residual`)?
    3. Does the pool balance: bought +/- adjustments - drawn == still on hand?

    Amounts roll up in USD, at the document's pinned rate when it has one (see
    `RunCostDocument`), else the rate history at its date.
    """
    docs = (
        db.query(M.RunCostDocument)
        .order_by(M.RunCostDocument.doc_date.desc(), M.RunCostDocument.id.desc())
        .all()
    )
    if company_ids is not None:
        # One company's documents (decision 0063): those it was billed for, the
        # transfers it sent, and the ones no company is named on yet. The
        # identities hold on any set of whole documents.
        docs = [d for d in docs if d.company_id is None or d.company_id in company_ids
                or d.counterparty_company_id in company_ids]
    rate_cache: dict[str, dict[str, float]] = {}
    unknown: set[str] = set()

    def to_usd(amount: float, doc: M.RunCostDocument) -> float:
        return doc_usd(db, amount, doc, rate_cache, unknown)

    projects = {p.id: p.name for p in db.query(M.Project).all()}
    _all_runs = db.query(M.ProductionRun).all()
    _counts = produced_counts(db, [r.id for r in _all_runs])
    runs = {
        r.id: {"label": r.label or f"run {r.id}", "project_id": r.project_id,
               "run_date": r.run_date or "", "qty": good_units(db, r, _counts),
               # sale side, so income sits beside cost in the register
               "qty_sold": r.qty_sold, "sale_unit_price": r.sale_unit_price,
               "sale_currency": r.sale_currency or "", "customer": r.customer,
               "order_ref": r.order_ref, "order_date": r.order_date,
               # Decision 0044: the Invoices view marks a position charged to a
               # closed batch, so it is clear BEFORE the edit is refused.
               "closed_at": r.closed_at.isoformat() if r.closed_at else None}
        for r in _all_runs
    }

    rows: list[dict] = []
    tot = defaultdict(float)
    by_project: dict[int, float] = defaultdict(float)
    by_run: dict[int, float] = defaultdict(float)
    by_supplier: dict[str, float] = defaultdict(float)
    # One lookup of the closed batches for the whole register (decision 0044),
    # instead of one query per document row.
    closed_by_id = {r.id: r for r in _all_runs if r.closed_at is not None}
    untranscribed: list[dict] = []
    excl_reason: dict[str, float] = defaultdict(float)
    for doc in docs:
        j = document_json(doc, with_lines=False, db=db, closed=closed_by_id)
        a = j["assignment"]
        # The printed total is the truth about how much money left the company;
        # `lines_total` is our transcription of it. Show both, trust the printed.
        printed = doc.total_amount if doc.total_amount is not None else (j["lines_total"] or 0.0)
        j["total_usd"] = _round(to_usd(printed, doc))
        j["lines_total_usd"] = _round(to_usd(j["lines_total"] or 0.0, doc))
        j["assignment_usd"] = {k: _round(to_usd(a[k] or 0.0, doc))
                               for k in ("run", "project", "pool", "transformation", "excluded",
                                         "overhead", "unassigned", "residual", "overallocated")}
        j["project_name"] = projects.get(doc.project_id or 0, "")
        j["run_label"] = (runs.get(doc.run_id or 0) or {}).get("label", "")
        rows.append(j)
        if (doc.doc_type or "invoice") == "proforma":
            continue  # not money: a quote that the real invoice supersedes
        if (doc.doc_type or "invoice") == "transfer":
            # Stock moved between our own companies (decision 0064). No money
            # left either company, so it is in no total: the receiver's pool
            # counts it as bought and the sender's as drawn, and they cancel.
            tot["transfer"] += to_usd(j["lines_total"] or 0.0, doc)
            continue
        # ACCUMULATE THE EXACT VALUES, not the per-document rounded ones. The row
        # carries figures rounded to 4dp for display, and adding 86 of those up
        # left the invariant at -0.0005 — an error introduced by the reporting,
        # in the very number whose job is to prove the arithmetic (decision 0048).
        tot["total"] += to_usd(printed, doc)
        # What our LINES say, next to what the supplier PRINTED. The buckets are
        # derived from the lines, so `lines == buckets` is the platform's own
        # arithmetic and must hold exactly; `printed - lines` is a transcription
        # difference and is a fact about the data.
        tot["lines"] += to_usd(j["lines_total"] or 0.0, doc)
        for k in ("run", "project", "pool", "transformation", "excluded", "overhead", "unassigned",
                  "residual", "overallocated"):
            tot[k] += to_usd(a.get(k) or 0.0, doc)
        _slip = to_usd(printed, doc) - to_usd(j["lines_total"] or 0.0, doc)
        if abs(_slip) > 0.0005:
            untranscribed.append({
                "document_id": doc.id, "supplier": doc.supplier or "",
                "doc_number": doc.doc_number or "", "doc_date": doc.doc_date or "",
                "currency": doc.currency or "USD",
                "printed": doc.total_amount, "lines_total": j["lines_total"],
                "difference_usd": _round(_slip),
            })
        if (a.get("excluded") or 0.0) > 0.0 or (a.get("excluded") or 0.0) < 0.0:
            _h = header_ids(db, doc.id)
            for li in doc.lines:
                if li.voided_at is not None or li.id in _h:
                    continue
                if (li.allocate or "none") != EXCLUDED:
                    continue
                excl_reason[li.exclude_reason or "legacy_unstated"] += to_usd(
                    effective_qty(li, doc, db) * (li.unit_price or 0), doc)
        by_supplier[doc.supplier or "(unnamed)"] += j["total_usd"] or 0.0
        for rid, amount in a["by_run"].items():
            by_run[int(rid)] += to_usd(amount or 0.0, doc)
        for pid, amount in a["by_project"].items():
            by_project[int(pid)] += to_usd(amount or 0.0, doc)

    # Components reach a run through the pool, so add the drawn value to each
    # run's figure — otherwise a batch whose only cost is components looks unpaid.
    priced_runs = {r.id for r in db.query(M.ProductionRun)
                   .filter(M.ProductionRun.sale_unit_price.isnot(None)).all()}
    pools = pool_states(db)
    if company_ids is not None and settings.stock_per_company:
        pools = {cid: pl for cid, pl in pools.items() if cid in company_ids}
    pool = {(cid, k): v for cid, pl in pools.items() for k, v in pl.items()}
    drawn_by_run: dict[int, float] = defaultdict(float)
    # An UNCHARGED draw has no run to add to. The stock has left the pool — which
    # `pool_state` already counted — but nobody has been charged, so it belongs
    # in no run's figure. Reported as `uncharged_drawn_usd` below instead of
    # being silently filed under a `None` key.
    uncharged_usd = 0.0
    # Inputs of a process transformation (decision 0058) also carry no run, but
    # they are not waiting for one: their value moved into the output lot,
    # which a batch pays for when it draws it. Counted on their own line.
    into_prepared_usd = 0.0
    # The sender's side of an in-house transfer (decision 0064): drawn, charged
    # to no batch, and not waiting for one — the receiver's pool holds it.
    transferred_out_usd = 0.0
    for c in live_consumption(db).all():
        value = (c.qty or 0) * (c.unit_cost_usd or 0)
        if c.run_id is None and c.transformation_id is not None:
            into_prepared_usd += value
        elif c.run_id is None and c.transfer_line_id is not None:
            transferred_out_usd += value
        elif c.run_id is None:
            uncharged_usd += value
        else:
            drawn_by_run[c.run_id] += value
    purchased = sum(p["value_bought"] for p in pool.values())
    used = sum(p["value_used"] for p in pool.values())
    adjusted = sum(p["value_adj"] for p in pool.values())
    on_hand = sum(p["value_usd"] for p in pool.values())

    # Stock that went below zero at some point in the replay: every one of these
    # is a missing purchase document (real or placeholder), an unrecorded loss,
    # or a batch that genuinely shipped without the part and should say so via a
    # run override. New draws hard-refuse; these are the grandfathered ones.
    neg_names: dict[int, str] = {}
    neg_ids = {p["component_id"] for p in pool.values()
               if p["min_qty"] < -0.0001 and p.get("component_id")}
    if neg_ids:
        for c in db.query(M.Component).filter(M.Component.id.in_(neg_ids)).all():
            neg_names[c.id] = c.name
    negative_stock = sorted(
        ({"key": k, "component_id": p["component_id"],
          "component_name": neg_names.get(p["component_id"] or -1, ""),
          "mpn": p["mpn"], "lcsc": p["lcsc"],
          "first_short": p["first_short"], "min_qty": _round(p["min_qty"]),
          "remaining_qty": _round(p["qty"]),
          # whose stock went short (decision 0064); None = the one shared pool
          "company_id": cid}
         for (cid, k), p in pool.items() if p["min_qty"] < -0.0001),
        key=lambda r: r["min_qty"])

    # Transport on a parts document must land in the part prices (user rule
    # 2026-07-28): a freight/duty leaf naming no destination of its own, on a
    # document whose part lines feed the pool, is money that should be spread.
    hdrs = header_ids(db)
    live_doc_ids = [d.id for d in docs if (d.doc_type or "invoice") != "proforma"]
    pool_doc_ids = {
        li.document_id
        for li in db.query(M.RunCostLine).filter(
            IS_STOCK, M.RunCostLine.run_id.is_(None),
            M.RunCostLine.voided_at.is_(None), M.RunCostLine.allocate != EXCLUDED,
            M.RunCostLine.document_id.in_(live_doc_ids or [0])).all()
        if li.id not in hdrs
    }
    doc_map = {d.id: d for d in docs}
    unspread_transport = [
        {"document_id": li.document_id, "line_id": li.id, "label": li.label,
         "supplier": doc_map[li.document_id].supplier,
         "doc_number": doc_map[li.document_id].doc_number,
         "doc_date": doc_map[li.document_id].doc_date,
         "amount": _round((li.qty or 0) * (li.unit_price or 0)),
         "currency": li.currency or doc_map[li.document_id].currency}
        for li in db.query(M.RunCostLine).filter(
            # Carriage and customs, by step rather than by kind.
            M.RunCostLine.plan_key.in_(("logistics:inbound", "logistics:duty")),
            M.RunCostLine.voided_at.is_(None),
            M.RunCostLine.run_id.is_(None), M.RunCostLine.project_id.is_(None),
            # An overhead logistics line is the company's, not a parts surcharge.
            M.RunCostLine.allocate.notin_((*SPREAD, EXCLUDED, OVERHEAD)),
            M.RunCostLine.document_id.in_(sorted(pool_doc_ids) or [0])).all()
        if li.id not in hdrs
    ]

    return {
        "documents": rows,
        "projects": {str(k): v for k, v in sorted(projects.items())},
        "runs": {str(k): v for k, v in sorted(runs.items())},
        "summary": {
            "document_count": len(rows),
            "total_usd": _round(tot["total"]),
            "to_runs_usd": _round(tot["run"]),
            "to_projects_usd": _round(tot["project"]),
            "to_pool_usd": _round(tot["pool"]),
            # Conversion costs, carried in the lots of production stages
            # (decision 0058 §4) — pool money that no purchase line holds.
            "to_transformations_usd": _round(tot["transformation"]),
            # Recorded so documents reconcile, charged to nobody on purpose:
            # reclaimable import VAT, and prepaid components already in the pool.
            "excluded_usd": _round(tot["excluded"]),
            # Company costs of no product (decision 0068).
            "to_overhead_usd": _round(tot["overhead"]),
            "unassigned_usd": _round(tot["unassigned"]),
            "residual_usd": _round(tot["residual"]),
            # Children claiming more than the header they split. Sub-cent by
            # construction — `split_line` refuses anything larger — but it has to
            # be in the identity or the identity cannot close.
            "overallocated_usd": _round(tot["overallocated"]),
            # WHY the excluded money is excluded, and how much of it says nothing.
            # `excluded` is a legal bucket in the identity, so an exclusion is
            # invisible to every check the platform has — which is how $14,443 of
            # manufacturing sat charged to nobody while the register read clean.
            # `legacy_unstated` is the deploy-day lint: it means the reason was
            # never given, not that there is none (decision 0048).
            "excluded_by_reason_usd": {
                k: _round(v) for k, v in sorted(excl_reason.items(), key=lambda kv: -kv[1])
            },
            "excluded_unstated_usd": _round(
                sum(v for k, v in excl_reason.items() if k in ("", "legacy_unstated"))),
            # What our lines add up to, beside what the suppliers printed.
            "lines_total_usd": _round(tot["lines"]),
            # THE INVARIANT, and it is about the platform's own arithmetic: every
            # bucket is derived from the lines, so the buckets must add back up to
            # them EXACTLY. A non-zero value here is a bug in this module.
            #
            # It used to be measured against the PRINTED total instead, which made
            # it permanently 0.0271 — five documents whose lines miss what the
            # supplier printed by a cent or two. That is bad DATA, not a bug, and
            # mixing the two meant the bug detector could never read zero. Worse,
            # the production overview printed a green "0" for anything under 0.05,
            # so the number nobody could fix was also the number nobody could see
            # (decision 0048).
            "gap_usd": _round(tot["lines"] - tot["run"] - tot["project"] - tot["pool"]
                              - tot["transformation"] - tot["excluded"] - tot["overhead"]
                              - tot["unassigned"] - tot["residual"] + tot["overallocated"]),
            # `printed - lines`, summed: money that left the company and is not on
            # any line. Real, small and NOT fixable by editing a line — JLC prints
            # a rounded total while our unit prices carry more decimals. Reported
            # so it is known, with `issues.untranscribed` naming every document.
            "untranscribed_usd": _round(tot["total"] - tot["lines"]),
            "unknown_rates": sorted(unknown),
            "by_supplier_usd": {k: _round(v) for k, v in sorted(by_supplier.items(),
                                                                key=lambda kv: -kv[1])},
        },
        "by_project_usd": {str(k): _round(v) for k, v in sorted(by_project.items())},
        "by_run_usd": {
            str(rid): _run_money(db, rid, by_run.get(rid, 0.0), drawn_by_run.get(rid, 0.0),
                                 rate_cache, db.get(M.ProductionRun, rid))
            for rid in sorted(set(by_run) | set(drawn_by_run) | set(priced_runs))
        },
        "pool": {
            "purchased_usd": _round(purchased),
            "adjustments_usd": _round(adjusted),
            "drawn_usd": _round(used),
            "on_hand_usd": _round(on_hand),
            "balanced": abs(purchased + adjusted - used - on_hand) <= 0.5,
            "part_count": len(pool),
            # Stock that has left the pool with no run charged: JLC reported the
            # draw on an invoice and nobody has said yet which batch pays (or the
            # order builds a project this platform does not track, and never
            # will). The pool identity above still balances — the value left the
            # pool either way — this only says how much of it landed nowhere.
            "uncharged_drawn_usd": _round(uncharged_usd),
            # Drawn INTO an internal part by a process transformation: the value
            # is still in the pool, as the output lot (decision 0058).
            "into_prepared_usd": _round(into_prepared_usd),
            # Sent to the other company by an in-house transfer (decision 0064).
            "transferred_out_usd": _round(transferred_out_usd),
            # The transfer documents' value. In no money total: it never left us.
            "transfers_usd": _round(tot["transfer"]),
            # Each company's own pool, when each keeps one (decision 0064).
            "by_company": {
                str(cid): {
                    "purchased_usd": _round(sum(p["value_bought"] for p in pl.values())),
                    "adjustments_usd": _round(sum(p["value_adj"] for p in pl.values())),
                    "drawn_usd": _round(sum(p["value_used"] for p in pl.values())),
                    "on_hand_usd": _round(sum(p["value_usd"] for p in pl.values())),
                    "part_count": len(pl),
                }
                for cid, pl in pools.items() if cid is not None
            },
        },
        "issues": {
            # Documents whose lines do not add up to what the supplier printed,
            # by any amount at all. `unreconciled` below uses a 5-cent tolerance
            # and so never names these; they are the whole of `untranscribed_usd`
            # (decision 0048).
            "untranscribed": sorted(untranscribed,
                                    key=lambda u: -abs(u["difference_usd"] or 0.0)),
            "unreconciled": [
                {"id": r["id"], "supplier": r["supplier"], "doc_number": r["doc_number"],
                 "doc_date": r["doc_date"], "total_amount": r["total_amount"],
                 "lines_total": r["lines_total"], "currency": r["currency"]}
                for r in rows if not r["reconciled"]
            ],
            "unassigned": [
                {"id": r["id"], "supplier": r["supplier"], "doc_number": r["doc_number"],
                 "doc_date": r["doc_date"], "amount_usd": r["assignment_usd"]["unassigned"],
                 "residual_usd": r["assignment_usd"]["residual"]}
                for r in rows
                if (r["doc_type"] or "invoice") != "proforma" and not r["assignment"]["fully_assigned"]
            ],
            "negative_stock": negative_stock,
            "unspread_transport": unspread_transport,
        },
    }


def consume_from_bom(db: Session, run: M.ProductionRun, basis: str = "bom",
                     consumed_at: str = "") -> dict:
    """Draw this run's components from the pool using its BOM x built units.

    Priced at the pool's moving average per part, snapshotted onto each row.
    Parts with nothing in the pool are reported as `unpriced` rather than
    silently costed at zero. While `lot_pricing` is on (decision 0073), each
    part comes from its lots oldest first at their cost instead, and a part no
    lot covers refuses the whole batch.
    """
    # A CRAFTED batch (decision 0059 §10) draws its parts step by step; drawing
    # BOM x produced as well would take the same parts twice.
    if run.process_version_id:
        return {"created": 0, "unpriced": [],
                "error": "this batch is crafted: its process steps draw its parts (decision 0059)"}
    if not run.snapshot_id:
        return {"created": 0, "unpriced": [], "error": "run has no snapshot — no BOM to draw from"}
    snap = db.get(M.ProjectSnapshot, run.snapshot_id)
    if snap is None:
        return {"created": 0, "unpriced": [], "error": "snapshot not found"}
    volume = good_units(db, run)
    # Price the draw from the pool AS IT STOOD at the run's date.
    pool = pool_state(db, run.project_id, as_of=(consumed_at or run.run_date or None),
                      company_id=run_scope(db, run))
    bom = (
        db.query(M.SnapshotBomLine)
        .filter_by(snapshot_id=snap.id, board=run.board, variant=run.variant)
        .all()
    )
    created, unpriced, skipped = 0, [], []
    date_iso = consumed_at or (run.run_date or "")
    # Per-run corrections, sharing the SAME key scheme and the SAME `drop` flag the
    # planned side already uses (`project_bom.run_effective`): `b<bom line id>` and
    # `x<extra item id>`. A batch that predates a part, or shipped without it, is a
    # real thing — the early batches went out with no carton — and so is a
    # substitution. Without this the only way to correct a run was to hand-delete
    # draw rows, which leaves no record of the decision.
    #   overrides = {"b12": {"drop": true},                      not used
    #                "b12": {"qty_total": 900}}                   different quantity
    # A SUBSTITUTION is no longer an override. It was `{"component_id": 319}`
    # here and never once used, because the key `b<SnapshotBomLine.id>` belongs
    # to one snapshot and stops matching the next time the BOM is exported —
    # useless for a change meant to carry into the next batch. It is now a
    # `RunSubstitution` row keyed by designator
    # ([0038](../../../docs/decisions/0038-a-substitution-belongs-to-the-batch.md)).
    overrides = run.overrides or {}

    planned: list[dict] = []

    def draw(key: str, component_id: int | None, lcsc: str, mpn: str,
             qty: float, label: str, extra_note: str = "") -> None:
        ov = overrides.get(key) or {}
        if ov.get("drop"):
            skipped.append({"key": key, "label": label, "reason": ov.get("note") or "not used"})
            return
        if ov.get("qty_total") is not None:
            qty = float(ov["qty_total"])
        if not qty:
            return
        note = f"BOM x {volume}"
        if extra_note:
            note += extra_note
        if ov:
            note += f" (override {json.dumps(ov)})"
        planned.append({"component_id": component_id, "lcsc": lcsc, "mpn": mpn,
                        "qty": qty, "label": label, "date": date_iso, "note": note})

    # What was FITTED wins over what the design specifies. A substitution is
    # recorded per batch and per designator
    # ([0038](../../../docs/decisions/0038-a-substitution-belongs-to-the-batch.md)),
    # and keyed that way rather than by BOM line id so it survives the next
    # snapshot — which is what `run.overrides` could not do.
    from . import substitutions as _subs

    subs = _subs.by_designator(db, run)
    for li in bom:
        if li.dnp or li.exclude_from_bom:
            continue
        cid, lcsc, note_sub = li.component_id, li.lcsc or "", ""
        sub = next((subs[r] for r in _subs._refs(li.refs) if r in subs), None)
        if sub is not None:
            cid, lcsc = sub.fitted_component_id, sub.fitted_lcsc or ""
            note_sub = (f" [fitted {sub.fitted_lcsc or sub.fitted_mpn} in place of "
                        f"{sub.specified_lcsc or sub.specified_mpn}]")
        draw(f"b{li.id}", cid, lcsc, "", (li.qty or 0) * volume,
             lcsc or li.refs or str(cid), note_sub)

    # EXTRA BOM items too. `project_bom` already counts them in the PLANNED
    # per-device figure, so leaving them out here made plan and actual asymmetric:
    # an enclosure or antenna would show as expected cost and never be drawn from
    # the pool, so its money sat unconsumed and every run read too cheap. These are
    # exactly the parts that cannot come from the schematic — an ESP32-WROOM-32U
    # takes its antenna on the module's own connector, so nothing is placed on the
    # PCB and no SnapshotBomLine can ever exist for it.
    from . import cost_state

    extras, _costs, _rev = cost_state.items_for(db, run.project_id, snap)
    for x in extras:
        draw(f"x{x.id}", x.component_id, "", x.mpn or "", (x.qty or 0) * volume,
             x.mpn or x.label or f"extra {x.id}")

    # A run cannot draw what was never bought (user decision 2026-07-28): the
    # WHOLE batch is checked first and refused atomically, so a failed draw never
    # leaves half a run consumed. The fix is the missing invoice — real or
    # placeholder — or a signed stock adjustment, or an override marking the part
    # as genuinely not used ("shipped without cartons" is history, not an error).
    shortages = check_shortages(db, planned, company_id=run_scope(db, run))
    if shortages:
        return {"created": 0, "unpriced": [], "volume": volume, "skipped": skipped,
                "shortages": shortages,
                "error": f"{len(shortages)} part(s) short — enter the missing invoice "
                         "(or a placeholder), record a stock adjustment, or mark the "
                         "part not-used via the run's overrides"}

    # Decision 0073: with lot pricing on, each part comes from its lots, oldest
    # first, at their cost — and a part no lot covers refuses the whole batch.
    from . import lots as _lots

    uncovered = _lots.fifo_price(db, planned, as_of=date_iso, company_id=run_scope(db, run))
    if uncovered:
        return {"created": 0, "unpriced": [], "volume": volume, "skipped": skipped,
                "uncovered": uncovered,
                "error": f"{len(uncovered)} part(s) are in no lot on {date_iso}: {_lots.short_text(uncovered)} "
                         "— enter the missing purchase (decision 0073)"}
    for d in planned:
        if d.get("bindings"):
            avg = d["unit_cost_usd"]
        else:
            probe = type("P", (), {"component_id": d["component_id"], "mpn": d["mpn"],
                                   "lcsc": d["lcsc"]})()
            avg = pool.get(_key(probe), {}).get("avg_usd", 0.0)
        if avg <= 0:
            unpriced.append(d["label"])
        c = M.ComponentConsumption(
            run_id=run.id, component_id=d["component_id"], lcsc=d["lcsc"], mpn=d["mpn"],
            qty=d["qty"], unit_cost_usd=avg, basis=basis, consumed_at=d["date"],
            note=d["note"],
        )
        db.add(c)
        if d.get("bindings"):
            db.flush()
            _lots.bind(db, c, d)
        created += 1
    return {"created": created, "unpriced": unpriced, "volume": volume,
            "extras_drawn": len([x for x in extras if (x.qty or 0)]),
            # what the run's overrides deliberately left out, so a missing line is
            # never mistaken for an oversight
            "skipped": skipped}
