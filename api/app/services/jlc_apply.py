"""Apply a JLC import plan — the ONLY module here that writes money.

Kept separate from `jlc_import` on purpose: planning is pure and re-runnable,
applying is not. Everything below assumes the plan was already inspected.

Three safety properties, in order of importance:

1. **One transaction per document, verified before it is kept.** Every write path
   re-runs `invoice_register`'s two identities afterwards and ROLLS BACK on any
   regression. The identities are `total == runs + projects + pool + excluded +
   unassigned + residual` (`summary.gap_usd`) and the pool's own
   `purchased +/- adjustments - drawn == on_hand` (`pool.balanced`). They are
   cheap relative to an import and they are the only mechanical detector of a
   double count this codebase has.

2. **Idempotency is enforced by the database, not by care.** Documents key on
   `(supplier, external_id)` via `uq_run_cost_doc_external`; draws key on
   `import_ref` via `uq_consumption_import`. Re-running an import is a no-op
   rather than an addition, which is the specific failure that double-drew
   components 324/325 across five runs.

3. **Never overwrite hand work.** A plan whose document already exists with split
   children or run allocations is refused, not merged. The user's manual
   decomposition is richer than the vendor's and, as verified on 2026-07-28, MORE
   CORRECT than the invoice in at least two places (a $40.60 and an $8.40
   settlement correction). Retro-keying the header is the safe operation;
   regenerating the lines is not.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from ..routers.util import audit
from . import lots, run_actuals

log = logging.getLogger(__name__)

SUPPLIER = "JLCPCB"
IDENTITY_EPS = 0.5


class ApplyRefused(RuntimeError):
    """The plan was not applied, and nothing was written."""


# ------------------------------------------------------------- verification
def identity_snapshot(db: Session) -> dict:
    """The two conservation identities, plus the totals they are derived from."""
    reg = run_actuals.invoice_register(db)
    return {
        "gap_usd": reg["summary"]["gap_usd"],
        "pool_balanced": reg["pool"]["balanced"],
        "total_usd": reg["summary"]["total_usd"],
        "to_runs_usd": reg["summary"]["to_runs_usd"],
        "to_pool_usd": reg["summary"]["to_pool_usd"],
        "unassigned_usd": reg["summary"]["unassigned_usd"],
        "pool_purchased_usd": reg["pool"]["purchased_usd"],
        "pool_drawn_usd": reg["pool"]["drawn_usd"],
        "pool_adjustments_usd": reg["pool"]["adjustments_usd"],
        "pool_on_hand_usd": reg["pool"]["on_hand_usd"],
    }


def _assert_identities(db: Session, before: dict, what: str) -> dict:
    """Refuse to keep a write that broke conservation.

    Note this checks the identities ABSOLUTELY, not relative to `before`: a gap
    that was already non-zero is a pre-existing bug, and importing on top of it
    would make the cause impossible to find. `before` is carried only so the
    error can say whether we caused it.
    """
    after = identity_snapshot(db)
    problems = []
    if abs(after["gap_usd"]) > IDENTITY_EPS:
        problems.append(
            f"register gap is ${after['gap_usd']} (was ${before['gap_usd']})"
        )
    if not after["pool_balanced"]:
        problems.append(
            f"pool does not balance: purchased {after['pool_purchased_usd']} "
            f"+ adj {after['pool_adjustments_usd']} - drawn {after['pool_drawn_usd']} "
            f"!= on hand {after['pool_on_hand_usd']}"
        )
    if problems:
        raise ApplyRefused(
            f"{what} broke conservation and was rolled back: " + "; ".join(problems)
        )
    return after


# --------------------------------------------------------------- documents
def _norm_ref(v: str) -> str:
    """Normalise a supplier reference for NEAR-match detection only.

    Real hand-entered values in this database include `POB00202510222305546`
    (a doubled zero) for `POB0202510222305546`, `w2024091801471067` in lowercase,
    and blanks. Case-folding plus stripping leading zeros off the numeric tail
    collapses the observed typos.
    """
    s = (v or "").strip().upper()
    for prefix in ("POB", "W"):
        if s.startswith(prefix):
            return prefix + s[len(prefix):].lstrip("0")
    return s


def find_document(db: Session, external_id: str, doc_number: str) -> M.RunCostDocument | None:
    """Exact match only — `external_id`, then `doc_number`."""
    q = db.query(M.RunCostDocument).filter(M.RunCostDocument.supplier == SUPPLIER)
    if external_id:
        hit = q.filter(M.RunCostDocument.external_id == external_id).first()
        if hit:
            return hit
    if doc_number:
        return q.filter(M.RunCostDocument.doc_number == doc_number).first()
    return None


def find_near_duplicate(db: Session, external_id: str,
                        total: float | None = None) -> M.RunCostDocument | None:
    """A document that is probably the same purchase under a mistyped reference.

    Deliberately NOT merged automatically: a fuzzy key must never silently join
    two financial records. The caller refuses and asks, because the alternative
    is worse — `POB0202510222305546` exists as `POB00202510222305546`, so an
    exact-match-only importer creates a SECOND document for a purchase already
    recorded, doubling it in the pool.
    """
    if not external_id:
        return None
    want = _norm_ref(external_id)
    for d in db.query(M.RunCostDocument).filter(M.RunCostDocument.supplier == SUPPLIER).all():
        if d.external_id and _norm_ref(d.external_id) == want:
            return d
        # A blank external_id with the reference embedded in the doc number is
        # the other observed shape (doc 9 holds 20146320202410172302255).
        if not d.external_id and d.doc_number and want.lstrip("POBW") in (d.doc_number or ""):
            return d
    return None


def apply_parts_document(db: Session, plan: dict, actor: str = "jlc-import",
                         dry_run: bool = False) -> dict:
    """Create one POB purchase document whose part lines ARE the lots.

    Shared (no project): a parts purchase is stockpile replenishment that several
    products draw from, which is this codebase's existing shared-document
    semantics. Every line carries `lot_ref` so a draw can bind to it.

    `dry_run=True` does EVERYTHING — including the conservation checks, which is
    the point — and then rolls back. That makes the preview trustworthy in a way
    a re-implementation of the mapping never could be: the numbers shown are the
    numbers the real write would produce, because it is the same code path.
    """
    before = identity_snapshot(db)
    existing = find_document(db, plan["external_id"], plan.get("doc_number") or "")
    if existing is not None:
        return {"status": "exists", "document_id": existing.id,
                "note": f"already imported as document {existing.id}"}

    near = find_near_duplicate(db, plan["external_id"], plan.get("total_amount"))
    if near is not None:
        # Refuse rather than guess. Creating a second document for a purchase
        # already recorded would double it in the pool, and a fuzzy key is not
        # grounds for merging two financial records without a human.
        return {
            "status": "probable_duplicate",
            "document_id": near.id,
            "note": (
                f"document {near.id} looks like the same purchase under a different "
                f"reference (its external_id={near.external_id!r}, doc_number="
                f"{near.doc_number!r}, total=${near.total_amount}; this plan is "
                f"{plan['external_id']!r} at ${plan['total_amount']}). Nothing was "
                "written — correct the existing reference or confirm they are distinct."
            ),
        }

    doc = M.RunCostDocument(
        project_id=None,
        run_id=None,
        doc_type="invoice",
        supplier=SUPPLIER,
        doc_number=plan.get("doc_number") or "",
        external_id=plan["external_id"],
        doc_date=plan["doc_date"].isoformat() if plan.get("doc_date") else "",
        currency="USD",
        fx_rate_usd=1.0,
        total_amount=plan["total_amount"],
        notes=(
            f"Imported from the JLCPCB web API. Lot costs are "
            f"goodsPaidMoney/settlePresaleNumber (what was actually paid), NOT goodsMoney "
            f"— the two differ by JLC's sourcing fee on presaleType='buy' sub-orders. "
            f"This document carries ${plan.get('sourcing_fee_usd', 0)} of such fee."
        ),
    )
    db.add(doc)
    db.flush()

    for pos, li in enumerate(plan["lines"], start=1):
        db.add(M.RunCostLine(
            document_id=doc.id,
            run_id=None,
            position=pos,
            kind=li["kind"],
            basis="per_run",
            label=li["label"][:300],
            qty=li["qty"],
            unit_price=li["unit_price"] or 0.0,
            currency="USD",
            allocate=li["allocate"],
            lcsc=li["lcsc"],
            mpn=li["mpn"][:200],
            notes=li["notes"],
            lot_ref=li.get("lot_ref") or "",
        ))
    db.flush()
    run_actuals.resolve_part_lines(db, doc.id)
    try:
        after = _assert_identities(db, before, f"parts document {plan['external_id']}")
    except ApplyRefused:
        db.rollback()
        raise
    if dry_run:
        db.rollback()
        return {"status": "dry_run", "document_id": None,
                "would_create_lines": len(plan["lines"]),
                "identities_before": before, "identities_after": after}
    _write_audit(db, "jlc.import.parts", doc.id, plan, actor)
    # NOT committed here. The caller owns the transaction boundary, because it
    # wraps this in `journal.batch(...)` and the journal header must land in the
    # SAME transaction as the rows it describes — otherwise a crash between the
    # two leaves money moved with no way to reverse it.
    return {"status": "created", "document_id": doc.id,
            "lines": len(plan["lines"]), "identities": after}


def apply_manufacturing_document(db: Session, plan: dict, actor: str = "jlc-import",
                                 dry_run: bool = False) -> dict:
    """Create one W batch document with its top-level lines and their children.

    Refuses a plan that does not reconcile: the planner asserts
    `total == product + freight + tariff + service - discount` and puts anything
    unexplained in a visible residual line, so a non-reconciling plan means the
    payload was not understood. Writing it would put a wrong number in the
    register, which is the one thing the identities exist to prevent.
    """
    before = identity_snapshot(db)
    if not plan.get("reconciles"):
        raise ApplyRefused(
            f"{plan['external_id']} does not reconcile: ${plan['residual_usd']} of "
            f"${plan['total_amount']} is unexplained — refusing to import a document "
            "whose structure we cannot account for"
        )

    existing = find_document(db, plan["external_id"], plan.get("doc_number") or "")
    if existing is not None:
        return {"status": "exists", "document_id": existing.id,
                "note": f"already imported as document {existing.id}"}
    near = find_near_duplicate(db, plan["external_id"])
    if near is not None:
        return {"status": "probable_duplicate", "document_id": near.id,
                "note": (f"document {near.id} (external_id={near.external_id!r}, "
                         f"doc_number={near.doc_number!r}) looks like the same batch; "
                         "nothing written")}

    doc = M.RunCostDocument(
        project_id=None, run_id=None, doc_type="invoice", supplier=SUPPLIER,
        doc_number=plan.get("doc_number") or "",
        external_id=plan["external_id"],
        doc_date=plan["doc_date"].isoformat() if plan.get("doc_date") else "",
        currency=plan.get("currency") or "USD",
        fx_rate_usd=1.0,
        total_amount=plan["total_amount"],
        notes=(
            "Imported from the JLCPCB web API. Reconciles as product + freight + "
            "tariff + service charge - discount. An assembly line's printed total "
            "INCLUDES its prepaid components; that portion is carved out as an "
            "`excluded` child, so the parent keeps the printed figure."
        ),
    )
    db.add(doc)
    db.flush()

    pos = 0
    made_lines = made_children = 0
    for li in plan["lines"]:
        pos += 1
        parent = M.RunCostLine(
            document_id=doc.id,
            run_id=li.get("run_id"),
            position=pos,
            kind=li["kind"],
            basis="per_run",
            label=li["label"][:300],
            qty=li["qty"],
            unit_price=li["unit_price"],
            currency="USD",
            allocate=li["allocate"],
            # The supplier's own identity for this charge — for JLC the
            # `smtOrderCode` it belongs to. The planner has always computed this
            # and the applier always threw it away, so the line -> order join
            # survived only as text inside `label` and had to be recovered by
            # `fix_alloc.py` and `mark_external.py`. Stored, a decision can
            # reclassify exactly its own lines by key.
            external_line_id=(li.get("external_line_id") or "")[:120],
            exclude_reason=(li.get("exclude_reason") or "")[:40],
            plan_key=li.get("plan_key") or "",
            notes=li.get("notes") or "",
        )
        db.add(parent)
        db.flush()
        made_lines += 1
        for ch in li.get("children") or []:
            pos += 1
            db.add(M.RunCostLine(
                document_id=doc.id,
                parent_line_id=parent.id,
                run_id=ch.get("run_id"),
                position=pos,
                kind=ch["kind"],
                basis="per_run",
                label=ch["label"][:300],
                qty=ch["qty"],
                unit_price=ch["unit_price"],
                currency="USD",
                allocate=ch["allocate"],
                external_line_id=(ch.get("external_line_id") or "")[:120],
                exclude_reason=(ch.get("exclude_reason") or "")[:40],
                plan_key=ch.get("plan_key") or "",
                notes=ch.get("notes") or "",
            ))
            made_children += 1
    db.flush()

    try:
        after = _assert_identities(db, before, f"manufacturing document {plan['external_id']}")
    except ApplyRefused:
        db.rollback()
        raise
    if dry_run:
        db.rollback()
        return {"status": "dry_run", "document_id": None,
                "would_create_lines": made_lines, "would_create_children": made_children,
                "identities_before": before, "identities_after": after}
    _write_audit(db, "jlc.import.manufacturing", doc.id, plan, actor)
    # NOT committed here. The caller owns the transaction boundary, because it
    # wraps this in `journal.batch(...)` and the journal header must land in the
    # SAME transaction as the rows it describes — otherwise a crash between the
    # two leaves money moved with no way to reverse it.
    return {"status": "created", "document_id": doc.id,
            "lines": made_lines, "children": made_children, "identities": after}


# ------------------------------------------------------------- adjustments
def apply_external_movements(db: Session, order_plan: dict, movements: list[dict],
                             actor: str = "jlc-import", dry_run: bool = False) -> dict:
    """Book an assembly order that belongs to a project outside the platform.

    Stock leaves, value leaves the pool, NOTHING is charged to a run. The
    invoice-allocation identity is untouched (the money was booked `to_pool` when
    the purchase was entered); the pool identity absorbs it through its
    adjustments leg.
    """
    before = identity_snapshot(db)
    tag = f"jlc:external:{order_plan['smt_order_code']}"

    _by_lcsc, _by_mpn = _component_index(db)
    written = unresolved = skipped = 0
    for m in movements:
        # Per-movement idempotency on `import_ref`, backed by `uq_stock_adj_import`.
        # This replaces a `note LIKE '%code%'` scan over the whole table, which was
        # both a text search standing in for a constraint AND all-or-nothing: one
        # movement already present made the whole order look booked, so an order
        # that failed halfway could never be completed.
        ref = (m.get("import_ref") or "")[:120]
        if ref and db.query(M.ComponentStockAdjustment).filter_by(import_ref=ref).first():
            skipped += 1
            continue
        cid = resolve_component(_by_lcsc, _by_mpn, m["lcsc"], m.get("mpn") or "")
        db.add(M.ComponentStockAdjustment(
            component_id=cid,
            mpn=m["mpn"][:200],
            lcsc=m["lcsc"],
            qty_delta=m["qty_delta"],
            unit_cost_usd=m["unit_cost_usd"],
            reason=m["reason"],
            charge_run_id=None,
            adjusted_at=m["adjusted_at"],
            import_ref=ref,
            actor=actor,
            note=m["note"][:500],
        ))
        written += 1
        if cid is None:
            unresolved += 1
    if not written:
        return {"status": "exists", "skipped": skipped,
                "note": f"all {skipped} movement(s) already booked"}
    db.flush()
    try:
        after = _assert_identities(
            db, before, f"external movements for {order_plan['smt_order_code']}")
    except ApplyRefused:
        db.rollback()
        raise
    if dry_run:
        db.rollback()
        return {"status": "dry_run", "would_write_movements": written,
                "already_booked": skipped, "unresolved_components": unresolved,
                "identities_before": before, "identities_after": after}
    _write_audit(db, "jlc.import.external", None,
                 {"tag": tag, "movements": written, "unresolved": unresolved,
                  "already_booked": skipped}, actor)
    return {"status": "created", "movements": written, "already_booked": skipped,
            "unresolved_components": unresolved, "identities": after}


def reprice_from_jlc(db: Session, lots_by_key: dict[str, dict],
                     actor: str = "jlc-import", dry_run: bool = True) -> dict:
    """Correct existing JLC part lines to what was ACTUALLY paid, and stamp each
    with its supplier lot key.

    Two independent defects in the hand/OCR-entered data, both verified:

    1. **Price** — lines were recorded from `goodsMoney` (goods value) rather
       than `goodsPaidMoney` (what left the bank). The two differ by JLC's
       sourcing fee on `presaleType='buy'` sub-orders, understating the pool by
       $1,623.23 across $29,639 of spend. The ESP32 reads $2.2146 where every
       other purchase of the same part sits between $2.79 and $3.02 — the
       outlier is the error, not the price.
    2. **Identity** — no line carries `lot_ref`, so no draw can ever cite WHICH
       purchase it consumed. Stamping it is what makes `source='reported'`
       reachable at all.

    Matching is on `(POB order, componentCode)` and then on quantity, never on
    price — price is the thing under correction, so it cannot also be the key.
    A quantity that matches no JLC row is left ALONE and reported: it may be a
    hand-split line, and silently rewriting one would destroy real work.
    """
    before = identity_snapshot(db)
    def _mpn_key(v: str) -> str:
        return "".join(ch for ch in (v or "").upper() if ch.isalnum())

    # Index by LCSC and, separately, by normalised MPN. The MPN fallback is not
    # laziness — two real cases need it and neither is rare:
    #   * lines entered with a BLANK lcsc (the G6K relay, $2,309 across two
    #     documents) would otherwise look like purchases we never recorded;
    #   * the documented XL-1005SURC alias, where JLC's purchase rows say
    #     C965790 while the platform recorded C25503345 for the same physical
    #     part — matching on code alone reports 9,465 LEDs as missing.
    by_pob: dict[tuple[str, str], list[dict]] = {}
    by_pob_mpn: dict[tuple[str, str], list[dict]] = {}
    for lot in lots_by_key.values():
        by_pob.setdefault((lot["purchase_batch_no"], lot["lcsc"]), []).append(lot)
        by_pob_mpn.setdefault(
            (lot["purchase_batch_no"], _mpn_key(lot["mpn"])), []).append(lot)

    docs = {
        d.id: d for d in db.query(M.RunCostDocument)
        .filter(M.RunCostDocument.supplier == SUPPLIER).all()
    }
    changes: list[dict] = []
    unmatched: list[dict] = []

    for line in (
        db.query(M.RunCostLine)
        .filter(M.RunCostLine.kind == "part", M.RunCostLine.voided_at.is_(None))
        .all()
    ):
        doc = docs.get(line.document_id)
        if doc is None:
            continue
        pob = (doc.external_id or "").strip()
        if not pob.startswith("POB"):
            continue
        cands = list(by_pob.get((pob, line.lcsc)) or []) if line.lcsc else []
        if not cands:
            cands = list(by_pob_mpn.get((pob, _mpn_key(line.mpn))) or [])
        # Quantity, never price — price is the thing being corrected, so it
        # cannot also be the key.
        hit = next((c for c in cands if abs((c["qty"] or 0) - (line.qty or 0)) < 0.5), None)
        if hit is None:
            if cands:
                unmatched.append({"line_id": line.id, "pob": pob, "lcsc": line.lcsc,
                                  "our_qty": line.qty,
                                  "jlc_qtys": [c["qty"] for c in cands]})
            continue
        new_unit = hit["unit_cost_usd"]
        if new_unit is None:
            continue
        old_unit = line.unit_price or 0.0
        delta = round((new_unit - old_unit) * (line.qty or 0), 4)
        needs_price = abs(new_unit - old_unit) > 1e-6
        needs_ref = (getattr(line, "lot_ref", "") or "") != hit["lot_key"]
        if not (needs_price or needs_ref):
            continue
        changes.append({
            "line_id": line.id, "pob": pob, "lcsc": line.lcsc, "mpn": line.mpn,
            "qty": line.qty, "old_unit": old_unit, "new_unit": new_unit,
            "delta_usd": delta, "lot_ref": hit["lot_key"],
            "fee_usd": hit["sourcing_fee_usd"], "presale_type": hit["presale_type"],
        })
        if not dry_run:
            if needs_price:
                line.unit_price = new_unit
                line.notes = (
                    (line.notes or "") +
                    f" | repriced {old_unit} -> {new_unit} on 2026-07-28 from the settled "
                    f"JLC order ({hit['presale_type']}): paid ${hit['paid_usd']} for "
                    f"{hit['qty']:g}. goodsMoney would say "
                    f"{round((hit['goods_usd'] / hit['qty']), 6) if hit['qty'] else '-'} "
                    f"and excludes ${hit['sourcing_fee_usd']} of sourcing fee."
                )[:8000]
            line.lot_ref = hit["lot_key"]

    # Lots JLC billed that no line records. Two kinds, both real money:
    #   * FEE-ONLY — a cancelled sub-order that was still paid for ($376.96 across
    #     four rows, one of them $349.39). Quantity settled to zero, so it must be
    #     a fee against no lot: dividing by the settled quantity is a division by
    #     zero and using the ordered quantity invents stock that never arrived.
    #   * genuinely never entered.
    # Without these the document total (corrected to what was paid) exceeds the
    # sum of its lines, and the register refuses the whole correction — which is
    # exactly how they were found.
    matched_keys = {c["lot_ref"] for c in changes}
    added: list[dict] = []
    for lot in lots_by_key.values():
        if lot["lot_key"] in matched_keys or not lot["paid_usd"]:
            continue
        doc = next((d for d in docs.values()
                    if (d.external_id or "").strip() == lot["purchase_batch_no"]), None)
        if doc is None:
            continue  # its document is not imported; not this function's job
        fee_only = lot["fee_only"]
        added.append({"document_id": doc.id, "pob": lot["purchase_batch_no"],
                      "lcsc": lot["lcsc"], "mpn": lot["mpn"], "qty": lot["qty"],
                      "paid_usd": lot["paid_usd"], "fee_only": fee_only})
        if not dry_run:
            db.add(M.RunCostLine(
                document_id=doc.id, run_id=None,
                position=9000 + len(added),
                kind="other" if fee_only else "part",
                basis="per_run",
                label=(f"Cancelled: {lot['mpn'] or lot['lcsc']}" if fee_only
                       else (lot["mpn"] or lot["lcsc"])[:300]),
                qty=1 if fee_only else lot["qty"],
                unit_price=lot["paid_usd"] if fee_only else (lot["unit_cost_usd"] or 0.0),
                currency="USD", allocate="none",
                lcsc="" if fee_only else lot["lcsc"],
                mpn="" if fee_only else (lot["mpn"] or "")[:200],
                lot_ref="" if fee_only else lot["lot_key"],
                notes=(
                    f"added 2026-07-28 from the settled JLC order {lot['purchase_order_no']}: "
                    + (f"paid ${lot['paid_usd']} but {lot['qty_ordered']:g} ordered and NONE "
                       f"settled (status {lot['order_status']}) — real money, no parts"
                       if fee_only else
                       f"paid ${lot['paid_usd']} for {lot['qty']:g} = "
                       f"${lot['unit_cost_usd']}/pc; never recorded by the original import")
                )[:8000],
            ))

    # The DOCUMENT total must move with its lines. Verified: the platform's POB
    # totals match JLC's `goodsMoney` to within rounding and sit $1,638.99 under
    # what was actually paid — they were entered from the same wrong figure as
    # the lines. Repricing lines alone breaks the register by exactly the delta,
    # which is how the conservation gate caught this: an invoice's printed total
    # is a fact, so if the lines are right and it disagrees, IT is wrong too.
    doc_changes: list[dict] = []
    paid_by_pob: dict[str, float] = {}
    for lot in lots_by_key.values():
        paid_by_pob[lot["purchase_batch_no"]] = (
            paid_by_pob.get(lot["purchase_batch_no"], 0.0) + lot["paid_usd"])
    for doc in docs.values():
        pob = (doc.external_id or "").strip()
        if not pob.startswith("POB") or pob not in paid_by_pob:
            continue
        paid = round(paid_by_pob[pob], 2)
        old = round(doc.total_amount or 0.0, 2)
        if abs(paid - old) < 0.005:
            continue
        doc_changes.append({"document_id": doc.id, "pob": pob,
                            "old_total": old, "new_total": paid,
                            "delta_usd": round(paid - old, 2)})
        if not dry_run:
            doc.total_amount = paid
            doc.notes = ((doc.notes or "") +
                         f" | total corrected {old} -> {paid} on 2026-07-28: the "
                         "original figure was JLC's goodsMoney (goods value), not "
                         "goodsPaidMoney (what was actually paid, including the "
                         "sourcing fee on 'buy' sub-orders).")[:8000]

    total_delta = round(sum(c["delta_usd"] for c in changes), 2)
    doc_delta = round(sum(c["delta_usd"] for c in doc_changes), 2)
    if dry_run:
        db.rollback()
        return {"status": "dry_run", "changes": changes, "unmatched": unmatched,
                "line_count": len(changes), "total_delta_usd": total_delta,
                "document_changes": doc_changes, "document_delta_usd": doc_delta,
                "added_lines": added, "added_usd": round(sum(a["paid_usd"] for a in added), 2),
                "identities_before": before}

    db.flush()
    try:
        after = _assert_identities(db, before, "repricing JLC part lines")
    except ApplyRefused:
        db.rollback()
        raise
    audit(db, "jlc.import.reprice", "run_cost_line", None,
          details={"lines": len(changes), "delta_usd": total_delta,
                   "documents": len(doc_changes), "document_delta_usd": doc_delta},
          actor=actor)
    # NOT committed here. The caller owns the transaction boundary, because it
    # wraps this in `journal.batch(...)` and the journal header must land in the
    # SAME transaction as the rows it describes — otherwise a crash between the
    # two leaves money moved with no way to reverse it.
    return {"status": "applied", "line_count": len(changes),
            "total_delta_usd": total_delta, "unmatched": unmatched,
            "document_changes": doc_changes, "document_delta_usd": doc_delta,
            "added_lines": added, "added_usd": round(sum(a["paid_usd"] for a in added), 2),
            "identities": after, "changes": changes}


def reclassify_order_lines(db: Session, code: str, outcome: str,
                           run_id: int | None, actor: str = "jlc-import",
                           dry_run: bool = False) -> dict:
    """Point one assembly order's invoice lines at whoever now owns them.

    This is what `fix_alloc.py` and `mark_external.py` did by hand, and the reason
    they were needed: the importer wrote every manufacturing line with
    `run_id=NULL` because the decision had not been made yet, and there was no way
    to revisit them afterwards. All 115 landed in `excluded` — $14,443 charged to
    nobody, with the register reading `gap_usd 0.0272` and `pool balanced`, because
    `excluded` is a legal bucket in the identity.

    Matched on `external_line_id`, never on `label` text. A prepaid child keeps its
    `excluded` bucket in both outcomes: that money was already booked to the pool
    by the POB purchase, so charging it to the run as well would double it.
    """
    lines = (db.query(M.RunCostLine)
             .filter(M.RunCostLine.voided_at.is_(None),
                     M.RunCostLine.external_line_id.like(f"{code}%"))
             .order_by(M.RunCostLine.id).all())
    changes = []
    for li in lines:
        prepaid = li.external_line_id.endswith(":prepaid")
        if prepaid:
            want_alloc, want_reason, want_run = "excluded", "prepaid_components", None
        elif outcome == "external":
            want_alloc, want_reason, want_run = "excluded", "external_project", None
        else:
            # A header worth zero (a parent carved up by children) must not also
            # carry the run, or the run is charged the parent AND its children.
            has_children = db.query(M.RunCostLine).filter(
                M.RunCostLine.parent_line_id == li.id,
                M.RunCostLine.voided_at.is_(None)).count() > 0
            want_alloc, want_reason = "none", ""
            want_run = None if has_children else run_id
        if (li.allocate, li.exclude_reason, li.run_id) == (want_alloc, want_reason, want_run):
            continue
        changes.append({"line_id": li.id, "label": li.label[:60],
                        "external_line_id": li.external_line_id,
                        "amount_usd": round((li.qty or 0) * (li.unit_price or 0), 2),
                        "from": {"allocate": li.allocate, "exclude_reason": li.exclude_reason,
                                 "run_id": li.run_id},
                        "to": {"allocate": want_alloc, "exclude_reason": want_reason,
                               "run_id": want_run}})
        if not dry_run:
            li.allocate, li.exclude_reason, li.run_id = want_alloc, want_reason, want_run
    # Separated deliberately. A change of `exclude_reason` alone moves NO money —
    # the bucket is the same — while a change of `allocate` or `run_id` moves all of
    # it. Reporting one figure for both would put "$321.96 moved" in front of an
    # operator when nothing did, and this codebase's central lesson is that a
    # number which overstates what happened is as dangerous as one that understates.
    rebucketed = [c for c in changes
                  if c["from"]["allocate"] != c["to"]["allocate"]
                  or c["from"]["run_id"] != c["to"]["run_id"]]
    return {"lines_seen": len(lines), "changes": changes,
            "rebucketed_count": len(rebucketed),
            "rebucketed_value_usd": round(sum(c["amount_usd"] for c in rebucketed), 2),
            "reason_only_count": len(changes) - len(rebucketed)}


def lot_line_index(db: Session) -> dict[str, int]:
    """`lot_ref` -> purchase-line id, for every live lot the platform holds.

    `apply_draws` has always required this mapping and NOTHING produced it — the
    backfill built it inline in a throwaway script. Without it every JLC-reported
    binding silently falls through to `source='unallocated'` priced at JLC's
    quoted figure instead of the lot's landed cost, which is the difference
    `reprice_from_jlc` measured at $1,623.23 across $29,639 of spend.

    A lot IS a leaf part line with no run, so this is a query, not a table.
    Newest line wins a duplicate `lot_ref`: re-importing a corrected POB document
    leaves the superseded lines voided, and a draw must bind to the live one.
    """
    rows = (db.query(M.RunCostLine)
            .filter(M.RunCostLine.lot_ref != "",
                    M.RunCostLine.kind == "part",
                    M.RunCostLine.voided_at.is_(None))
            .order_by(M.RunCostLine.id).all())
    return {li.lot_ref: li.id for li in rows}


def apply_draws(db: Session, order_plan: dict, run_id: int, lot_lines: dict[str, int],
                actor: str = "jlc-import", dry_run: bool = True) -> dict:
    """Write MEASURED, lot-bound draws for one assembly order and retire the
    BOM forecasts they replace.

    Shape: one `ComponentConsumption` per (run, part) carrying the qty-weighted
    average, with one `ComponentConsumptionLot` child per JLC row. That keeps
    the parent row count equal to the part count — which the costs UI assumes —
    while preserving which purchase each slice came from. The two views total
    the same figure by construction, so the advanced toggle can never change a
    number.

    Superseding is scoped to (run, part identity) PRESENT IN JLC'S LIST. A
    forecast draw for a part JLC did not report is left alone: locally-bought
    enclosures and antennas never pass through the private library, and voiding
    them would silently un-cost them. Conversely a part JLC reports but which we
    never bought is the C15195 case — BOM-inferred consumption of a part JLC
    supplied itself, which SHOULD disappear.
    """
    before = identity_snapshot(db)
    code = order_plan["smt_order_code"]
    consumption = order_plan.get("consumption") or []
    if not consumption:
        return {"status": "nothing_to_draw", "smt_order_code": code}

    # group JLC rows by part; each row is one lot slice
    by_part: dict[str, list[dict]] = {}
    for c in consumption:
        by_part.setdefault(c["lcsc"] or f"mpn:{c['mpn']}", []).append(c)

    by_lcsc, by_mpn = _component_index(db)
    when = (order_plan["invoice_date"].isoformat()
            if order_plan.get("invoice_date") else "")

    planned_bindings: list[dict] = []
    made = skipped = unresolved = 0
    parts_touched: set[str] = set()

    # Capacity is checked BEFORE anything is written. Checking afterwards is
    # self-defeating: `lot_state` reads `component_consumption_lots`, so a
    # post-flush check sees the very bindings it is validating and counts them
    # twice — every order then looks like it overdraws by exactly its own size.
    # Skip parts already imported, or a re-run double-counts its own previous
    # bindings and refuses work it already did.
    _pre = []
    for rows in by_part.values():
        first = rows[0]
        ref = f"jlc:{order_plan['batch_num']}:{code}:{first['lcsc'] or first['mpn']}"
        # Deliberately NOT filtered on `voided_at`, here and at the twin check
        # below. `uq_consumption_import` constrains voided rows too, so a
        # re-import after a deliberate void must stay a no-op — resurrecting a
        # draw someone chose to retire would be the import silently overruling
        # the operator. Voiding is undone by reversing its batch, not by syncing.
        if db.query(M.ComponentConsumption).filter_by(import_ref=ref).first():
            continue
        for r in rows:
            lid = lot_lines.get(r.get("lot_key") or "")
            if lid:
                _pre.append({"lot_line_id": lid, "qty": r["qty"]})
    capacity = lots.check_lot_capacity(db, _pre)
    if capacity:
        raise ApplyRefused(
            f"{code}: would overdraw {len(capacity)} lot(s): {capacity[:3]}")

    for rows in by_part.values():
        lcsc = rows[0]["lcsc"]
        mpn = rows[0]["mpn"]
        cid = resolve_component(by_lcsc, by_mpn, lcsc, mpn)
        qty = sum(r["qty"] for r in rows)
        if qty <= 0:
            continue
        import_ref = f"jlc:{order_plan['batch_num']}:{code}:{lcsc or mpn}"
        if db.query(M.ComponentConsumption).filter_by(import_ref=import_ref).first():
            skipped += 1
            continue
        if cid is None:
            unresolved += 1
        parts_touched.add(lcsc or mpn)

        # bind each JLC row to the purchase line it names
        children = []
        for r in rows:
            line_id = lot_lines.get(r.get("lot_key") or "")
            children.append({
                "lot_line_id": line_id,
                "qty": r["qty"],
                # The LOT's landed cost, not JLC's quoted component price.
                "unit_cost_usd": _lot_unit(db, line_id) if line_id else r["unit_price"],
                "source": "reported" if line_id else "unallocated",
                "ext_ref": r.get("lot_key") or "",
            })
        planned_bindings.extend(children)
        value = sum(ch["qty"] * (ch["unit_cost_usd"] or 0) for ch in children)
        unit = round(value / qty, 8) if qty else 0.0

        if not dry_run:
            cons = M.ComponentConsumption(
                run_id=run_id, component_id=cid, mpn=(mpn or "")[:200], lcsc=lcsc,
                qty=qty, unit_cost_usd=unit, basis="measured", consumed_at=when,
                import_ref=import_ref,
                note=(f"JLC assembly order {code} (batch {order_plan['batch_num']}) drew "
                      f"{qty:g} across {len(children)} lot(s); prices are the lots' landed "
                      "cost, not JLC's quoted component price"),
            )
            db.add(cons)
            db.flush()
            for ch in children:
                db.add(M.ComponentConsumptionLot(
                    consumption_id=cons.id, lot_line_id=ch["lot_line_id"],
                    qty=ch["qty"], unit_cost_usd=ch["unit_cost_usd"] or 0.0,
                    source=ch["source"], ext_ref=ch["ext_ref"]))
        made += 1

    # Retire the forecasts these measurements replace. VOID, never delete: this
    # is the row the reversal has to put back, and `void_shop.py` /
    # `void_absent.py` deleted 10 draws during the backfill that could then only
    # be recovered from a database dump. Un-voiding is one UPDATE.
    voided = 0
    if not dry_run and parts_touched:
        for old in (run_actuals.live_consumption(db, run_id=run_id)
                    .filter(M.ComponentConsumption.import_ref == "",
                            M.ComponentConsumption.basis.in_(("bom", "manual", "allocated")))
                    .all()):
            if (old.lcsc or old.mpn) in parts_touched:
                old.voided_at = utcnow()
                old.void_reason = "superseded_by_measured"
                voided += 1

    if not dry_run:
        db.flush()
    try:
        after = _assert_identities(db, before, f"draws for {code}")
    except ApplyRefused:
        db.rollback()
        raise
    if dry_run:
        db.rollback()
        return {"status": "dry_run", "smt_order_code": code, "run_id": run_id,
                "would_write_draws": made, "would_bind_lots": len(planned_bindings),
                "already_present": skipped, "unresolved_components": unresolved,
                "reported_bindings": sum(1 for b in planned_bindings if b["lot_line_id"]),
                "identities_after": after}
    _write_audit(db, "jlc.import.draws", None,
                 {"order": code, "run_id": run_id, "draws": made, "voided": voided}, actor)
    # NOT committed here. The caller owns the transaction boundary, because it
    # wraps this in `journal.batch(...)` and the journal header must land in the
    # SAME transaction as the rows it describes — otherwise a crash between the
    # two leaves money moved with no way to reverse it.
    return {"status": "applied", "smt_order_code": code, "run_id": run_id,
            "draws": made, "lot_bindings": len(planned_bindings),
            "voided_forecasts": voided, "unresolved_components": unresolved,
            "identities": after}


def _lot_unit(db: Session, line_id: int) -> float:
    """A purchase line's landed unit cost, from the lot ledger."""
    state = lots.lot_state(db)
    lot = state["lots"].get(f"L{line_id}")
    return lot["unit_cost_usd"] if lot else 0.0


# -------------------------------------------------------------- utilities
def _norm_mpn(v: str) -> str:
    return "".join(ch for ch in (v or "").upper() if ch.isalnum())


def _component_index(db: Session) -> tuple[dict[str, int], dict[str, int]]:
    """(LCSC -> component id, normalised-MPN -> component id).

    The MPN half is NOT a nicety. JLC lists one manufacturer part under several
    LCSC codes, and its consumption rows cite ITS code while the library records
    another — `XL-1005SURC` is `C25503345` to JLC and `C965790` here. Resolving
    on LCSC alone left 21,512 LEDs drawn against `component_id = NULL`, which
    reads as a 21,512-piece shortage of a part that was fully stocked. The
    purchase-side resolver already falls back to MPN; this must match it or
    draws and purchases land on different identities.

    A linked row always beats an unlinked one, per the documented case where
    first-write-wins once costed 16,800 LEDs at zero.
    """
    by_lcsc: dict[str, int] = {}
    by_mpn: dict[str, int] = {}
    for item in db.query(M.JlcStockItem).all():
        if item.component_id:
            if item.lcsc:
                by_lcsc[item.lcsc] = item.component_id
            if item.mpn:
                by_mpn.setdefault(_norm_mpn(item.mpn), item.component_id)
    for comp in db.query(M.Component).all():
        if comp.name:
            by_mpn.setdefault(_norm_mpn(comp.name), comp.id)
    for cv, prop in (
        db.query(M.ComponentVersion, M.ComponentProperty)
        .join(M.ComponentProperty, M.ComponentProperty.component_version_id == M.ComponentVersion.id)
        .filter(M.ComponentProperty.key == "LCSC Part")
        .all()
    ):
        comp = db.get(M.Component, cv.component_id)
        if comp is not None and comp.current_version_id == cv.id and prop.value:
            by_lcsc.setdefault(prop.value.strip(), cv.component_id)
    return by_lcsc, by_mpn


def resolve_component(by_lcsc: dict[str, int], by_mpn: dict[str, int],
                      lcsc: str, mpn: str) -> int | None:
    """LCSC first, then MPN — the same order the purchase side uses."""
    return by_lcsc.get(lcsc) or by_mpn.get(_norm_mpn(mpn))


def _write_audit(db: Session, action: str, entity_id: int | None,
                 details: dict, actor: str) -> None:
    """Reuse the canonical writer (`routers/util.audit`) rather than building
    AuditLog rows by hand — it stringifies `entity_id`, which is `String(100)`
    and not an integer. Services importing that helper is an existing pattern
    (`importer.py`, `jaravis.py`)."""
    audit(db, action, "run_cost_document", entity_id,
          details=_jsonable(details), actor=actor)


def _jsonable(d: dict) -> dict:
    """Audit details must survive JSON serialisation — plans carry `date`s."""
    out = {}
    for k, v in d.items():
        if k in ("lines", "consumption"):
            out[k] = len(v) if isinstance(v, list) else v
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
