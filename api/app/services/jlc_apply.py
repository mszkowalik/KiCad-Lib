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
from . import cost_steps, jlc_import, jlc_invoice, lots, run_actuals

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
            basis="per_run",
            label=li["label"][:300],
            qty=li["qty"],
            unit_price=li["unit_price"] or 0.0,
            currency="USD",
            allocate=li["allocate"],
            exclude_reason=(li.get("exclude_reason") or "")[:40],
            # The step is what makes a lot STOCK (decision 0047). Omitted, every
            # line landed as `plan_key=""` and a whole parts order showed as
            # unassigned money with nothing added to the pool — the state the
            # importer was in from 2026-09-19 to 2026-09-24.
            plan_key=li.get("plan_key") or "",
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


def refresh_parts_document(db: Session, plan: dict, actor: str = "jlc-import",
                           dry_run: bool = True) -> dict:
    """Re-state an ALREADY IMPORTED parts order from JLC's current answer.

    The importer is a one-shot: `apply_parts_document` refuses a document that
    exists, which is right — a second document would double the purchase. But a
    lot can change shape after it was imported, and the platform had no way to
    take the correction except by hand. Lot 754166 was imported as 3,470 pieces
    of stock and was afterwards cancelled and refunded; the importer learned to
    read that (`_lot_from_goods.fee_only`), and this is what lets an existing
    document learn it too.

    Lines are matched by `lot_ref`, which is JLC's `presaleGoodsKeyId` and is
    stable across the change — including on a fee line, which is why
    `plan_parts_document` now keeps it there.

    It REFUSES rather than guesses when:

    * a line the plan no longer knows about exists on the document — that is a
      key mismatch, not a deletion, and deleting a purchase silently is how a
      pool loses stock it really has;
    * a part line whose quantity would drop already has draws bound to it. The
      binding says the parts were consumed. JLC saying they never arrived and the
      platform saying they were used is a contradiction a human must settle.
    """
    before = identity_snapshot(db)
    doc = find_document(db, plan["external_id"], plan.get("doc_number") or "")
    if doc is None:
        return {"status": "not_imported", "document_id": None,
                "note": f"{plan['external_id']} is not in the platform — import it first"}

    existing = {}
    for line in db.query(M.RunCostLine).filter(M.RunCostLine.document_id == doc.id).all():
        if line.lot_ref:
            existing.setdefault(line.lot_ref, []).append(line)

    changes: list[dict] = []
    blockers: list[str] = []
    # Decided before anything is written. A refusal must not need a rollback:
    # rolling back inside a service discards whatever else the caller had in the
    # same transaction, including the journal header that makes a write
    # reversible.
    pending: list[tuple] = []
    for li in plan["lines"]:
        ref = li.get("lot_ref") or ""
        rows = existing.pop(ref, []) if ref else []
        if not ref or not rows:
            blockers.append(f"plan line {li['label']!r} (lot {ref or '-'}) has no line on "
                            f"document {doc.id} — refusing to add money to a document "
                            "that was already reconciled")
            continue
        if len(rows) > 1:
            blockers.append(f"lot {ref} matches {len(rows)} lines on document {doc.id}")
            continue
        row = rows[0]
        fields = [
            # `kind` is gone (decision 0047): the planner's `plan_key` is what
            # the row stores. This used to read a `step` key the parts planner
            # never sets, so every refreshed lot was rewritten to `plan_key=""`
            # and silently left the pool.
            ("plan_key", li.get("plan_key") or ""),
            ("label", li["label"][:300]), ("qty", float(li["qty"])),
            ("unit_price", float(li["unit_price"] or 0.0)), ("lcsc", li["lcsc"]),
            ("mpn", li["mpn"][:200]), ("notes", _keep_annotations(row.notes, li["notes"])),
        ]
        if _differs(row.plan_key, li.get("plan_key") or ""):
            # The lot changed what it IS — delivered, or cancelled — so where
            # its money goes changes with it. Otherwise the destination stays a
            # person's decision and a refresh never overrules it.
            fields += [("allocate", li["allocate"]),
                       ("exclude_reason", (li.get("exclude_reason") or "")[:40])]
        diff = {k: (getattr(row, k), v) for k, v in fields
                if _differs(getattr(row, k), v)}
        if not diff:
            continue
        if float(li["qty"]) < float(row.qty or 0):
            bound = (db.query(M.ComponentConsumptionLot)
                       .filter(M.ComponentConsumptionLot.lot_line_id == row.id).all())
            if bound:
                blockers.append(
                    f"line {row.id} (lot {ref}) would drop from {row.qty:g} to "
                    f"{float(li['qty']):g} but {len(bound)} draw(s) are bound to it — "
                    "JLC says the parts never arrived and the platform says they were "
                    "used; settle that before refreshing")
                continue
        changes.append({"line_id": row.id, "lot_ref": ref,
                        "was": {k: v[0] for k, v in diff.items()},
                        "now": {k: v[1] for k, v in diff.items()}})
        pending.append((row, diff))

    for ref, rows in existing.items():
        blockers.append(f"document {doc.id} carries lot {ref} (line "
                        f"{', '.join(str(r.id) for r in rows)}) that JLC no longer reports")

    if blockers:
        return {"status": "refused", "document_id": doc.id, "blockers": blockers,
                "changes": changes}
    if not changes:
        return {"status": "unchanged", "document_id": doc.id, "changes": []}

    total = round(sum(float(li["qty"]) * float(li["unit_price"] or 0.0)
                      for li in plan["lines"]), 4)
    # A dry run does the whole write and the conservation checks, then undoes it
    # on a SAVEPOINT rather than `db.rollback()`. The preview is only worth
    # having because it is the same code path — but a plain rollback would also
    # discard whatever else the caller holds in the transaction, which is how a
    # preview reached into a test's fixture and undid it.
    sp = db.begin_nested() if dry_run else None
    for row, diff in pending:
        for k, v in diff.items():
            setattr(row, k, v[1])
    doc.total_amount = plan["total_amount"]
    db.flush()
    run_actuals.resolve_part_lines(db, doc.id)
    after = _assert_identities(db, before, f"parts refresh {plan['external_id']}")
    if sp is not None:
        sp.rollback()
        return {"status": "dry_run", "document_id": doc.id, "changes": changes,
                "line_total_usd": total,
                "identities_before": before, "identities_after": after}
    _write_audit(db, "jlc.import.parts.refresh", doc.id, plan, actor)
    return {"status": "refreshed", "document_id": doc.id, "changes": changes,
            "identities": after}


def _keep_annotations(old: str, fresh: str) -> str:
    """Re-generate a line's note WITHOUT dropping what a person added to it.

    The importer writes one sentence and anything after " | " was written by
    hand or by a later correction — line 874 carries the record of why its
    component was restored to TS3625A. A refresh that regenerated the note would
    silently delete that, and the reason a substitution exists is worth more than
    the sentence it follows.
    """
    tail = (old or "").split(" | ")[1:]
    return " | ".join([fresh, *tail]) if tail else fresh


def _differs(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return abs(float(a or 0) - float(b or 0)) > 1e-9
    return (a or "") != (b or "")


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
# `apply_external_movements` has been REMOVED (decision 0034, completed
# 2026-09-18) together with its planner, `jlc_import.external_stock_movements`.
# An external order's stock now leaves as an uncharged draw, which says the same
# thing in the shape everything else uses. See `routers/jlc_import._book_external`.


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
    matched_keys: set[str] = set()

    for line in (
        db.query(M.RunCostLine)
        .filter(run_actuals.IS_STOCK, M.RunCostLine.voided_at.is_(None))
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
        if hit is not None and (hit.get("awaiting") or hit.get("cancelled")):
            # A stock line matched to a lot JLC has not delivered (or cancelled)
            # is a contradiction, not a price to correct. Report it.
            unmatched.append({"line_id": line.id, "pob": pob, "lcsc": line.lcsc,
                              "our_qty": line.qty, "jlc_qtys": [hit["qty"]],
                              "why": "awaiting delivery" if hit.get("awaiting") else "cancelled"})
            continue
        if hit is None:
            if cands:
                unmatched.append({"line_id": line.id, "pob": pob, "lcsc": line.lcsc,
                                  "our_qty": line.qty,
                                  "jlc_qtys": [c["qty"] for c in cands]})
            continue
        # Matched, whether or not it needs a change. Recording only CHANGED
        # lines here let a line that was already right read as a missing lot
        # below, and the repair would have added the purchase a second time.
        matched_keys.add(hit["lot_key"])
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
    added: list[dict] = []
    for lot in lots_by_key.values():
        if lot["lot_key"] in matched_keys or not lot["paid_usd"]:
            continue
        doc = next((d for d in docs.values()
                    if (d.external_id or "").strip() == lot["purchase_batch_no"]), None)
        if doc is None:
            continue  # its document is not imported; not this function's job
        # The line is built by the PARTS PLANNER, not here: it is the one place
        # that knows a lot's step and destination (stock, cancelled, awaiting
        # delivery). A second copy wrote no `plan_key`, so every lot it added
        # would have landed as unassigned money rather than stock.
        [li] = jlc_import.plan_parts_document(lot["purchase_batch_no"], [lot], None)["lines"]
        added.append({"document_id": doc.id, "pob": lot["purchase_batch_no"],
                      "lcsc": lot["lcsc"], "mpn": lot["mpn"], "qty": lot["qty"],
                      "paid_usd": lot["paid_usd"], "plan_key": li["plan_key"],
                      "fee_only": lot["fee_only"], "awaiting": lot.get("awaiting", False)})
        if not dry_run:
            db.add(M.RunCostLine(
                document_id=doc.id, run_id=None,
                position=9000 + len(added),
                basis="per_run",
                label=li["label"][:300],
                qty=li["qty"],
                unit_price=li["unit_price"] or 0.0,
                currency="USD",
                allocate=li["allocate"],
                exclude_reason=(li.get("exclude_reason") or "")[:40],
                plan_key=li["plan_key"],
                lcsc=li["lcsc"],
                mpn=li["mpn"][:200],
                lot_ref=li.get("lot_ref") or "",
                notes=f"added by reprice_from_jlc: {li['notes']}"[:8000],
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


def backfill_fee_split(db: Session, row: M.JlcImport, actor: str = "jlc-import",
                       dry_run: bool = True) -> dict:
    """Attach JLC's per-order fee itemization to an ALREADY-imported batch
    document, as split children under the existing lines.

    Derivation is shared with the import planner (`jlc_import.fee_children_plan`)
    so a retro-split document and a freshly imported one can never disagree.
    The rules that keep this safe:

    * **The parent keeps its printed figure** — children are added, nothing is
      rewritten. Closure against the TARGET line's own amount (not the invoice's)
      via a signed delta child, so a hand-corrected line still closes exactly.
    * **Hand work is never touched.** A line that already has children the
      backfill did not make is skipped and reported — the operator's
      decomposition wins. Presale lines split at import time are handled by
      targeting their ':work' child, which carries the chargeable slice.
    * **Destination is inherited.** Children copy the target's run/project, so
      no money changes owner — the run's total moves by zero (the target
      becomes a header worth zero and the children sum to its amount).
    * **Excluded lines stay unsplit** — money charged to nobody on purpose
      gains nothing from a step breakdown, and prepaid children stay excluded.
    * Idempotent: a target that already carries `:fee:` children is reported as
      `already_split`, never doubled.
    """
    before = identity_snapshot(db)
    if not row.payload or "invoiceNo" not in row.payload:
        return {"status": "no_payload", "external_id": row.external_id}
    fee_orders = (row.fee_info or {}).get("orders") or {}
    if not fee_orders:
        return {"status": "no_fee_info", "external_id": row.external_id}
    doc = db.get(M.RunCostDocument, row.document_id) if row.document_id else None
    if doc is None:
        doc = find_document(db, row.external_id, row.invoice_no or "")
    if doc is None:
        return {"status": "not_imported", "external_id": row.external_id}

    inv = jlc_invoice.parse(row.payload)
    plans = jlc_import.fee_children_plan(inv, fee_orders)
    if not plans:
        return {"status": "nothing_to_split", "external_id": row.external_id,
                "document_id": doc.id}
    stage_by_line = {li["order_code"]: li["stage"] for li in inv["lines"]}

    lines = (db.query(M.RunCostLine)
             .filter(M.RunCostLine.document_id == doc.id,
                     M.RunCostLine.voided_at.is_(None)).all())
    by_ext: dict[str, list[M.RunCostLine]] = {}
    kids_of: dict[int, list[M.RunCostLine]] = {}
    for li in lines:
        if li.external_line_id:
            by_ext.setdefault(li.external_line_id, []).append(li)
        if li.parent_line_id:
            kids_of.setdefault(li.parent_line_id, []).append(li)

    results: list[dict] = []
    made = 0
    value = 0.0
    used_targets: set[int] = set()
    pos = max([li.position for li in lines], default=-1)

    def _amount_match(key: str) -> tuple[M.RunCostLine | None, str]:
        """Fallback for hand-entered documents, whose lines carry NO external
        ids: find the one live LEAF whose amount equals what this order was
        billed. Exact-cent matching (±0.02) plus uniqueness — a document where
        two lines share the amount is left alone and reported, never guessed.

        Returns (line, reason-if-none). Amounts tried, in order: the order's own
        billed product money (dummy+extra — doc 19's hand lines hold exactly
        this), the bare dummy, and for assembly lines the printed invoice slice
        minus prepaid components.
        """
        bare = jlc_invoice.split_assembly_order_code(key)[0]
        fe = fee_orders.get(bare) or fee_orders.get(key)
        if fe is None:
            return None, "no_fee_entry"
        dummy = jlc_invoice._f(fe.get("dummy"))
        extra = jlc_invoice._f(fe.get("extra"))
        expected = [round(dummy + extra, 2), round(dummy, 2)]
        inv_line = next((li for li in inv["lines"] if li["order_code"] == key), None)
        if inv_line is not None:
            expected.append(round(inv_line["total"] - inv_line["presale"], 2))
        cands = []
        header_ids_local = set(kids_of.keys())
        for li in lines:
            if li.parent_line_id or li.id in header_ids_local or li.id in used_targets:
                continue
            # Manufacturing money, not stock and not something already excluded.
            # The bucket is derived from the step now (decision 0047).
            if li.allocate == "excluded" or cost_steps.kind_of(li.plan_key or "") not in (
                    "assembly", "fab", "tooling", "other"):
                continue
            amt = round((li.qty or 0) * (li.unit_price or 0), 2)
            if any(abs(amt - e) <= 0.02 for e in expected):
                cands.append(li)
        if len(cands) == 1:
            return cands[0], ""
        return None, ("ambiguous_amount" if len(cands) > 1 else "no_amount_match")

    # A PCB order whose cost the invoice folded ENTIRELY into the assembly line
    # produces no plan key of its own — but a hand-entered document often
    # carries it as a separate line at the order's true cost (doc 19 held P12's
    # $106.43 that the invoice printed nowhere). Offer every such order to the
    # amount matcher with its full fee list.
    all_plans = dict(plans)
    for code, fe in fee_orders.items():
        if fe.get("kind") == "pcb" and code not in all_plans:
            comps = jlc_import.order_fee_components(fe)
            if comps:
                all_plans[code] = [
                    {**c, "external_line_id": f"{code}:fee:{c['slug']}"} for c in comps]

    for key, kids in sorted(all_plans.items()):
        # Presale lines were split at import time into prepaid + work; the work
        # child carries the chargeable slice, so it is the split target.
        work = by_ext.get(f"{key}:work") or []
        parents = by_ext.get(key) or []
        target = work[0] if len(work) == 1 else (parents[0] if len(parents) == 1 else None)
        matched_by = "external_line_id"
        if target is None:
            target, why = _amount_match(key)
            matched_by = "amount"
            if target is not None:
                # A hand line holds the ORDER's money, not the invoice's printed
                # allocation — so it gets the order's full fee list, and the
                # delta below closes against the line's own amount.
                bare = jlc_invoice.split_assembly_order_code(key)[0]
                fe = fee_orders.get(bare) or fee_orders.get(key)
                kids = [{**c, "external_line_id": f"{key}:fee:{c['slug']}"}
                        for c in jlc_import.order_fee_components(fe)]
        if target is None:
            results.append({"key": key, "status": why or "no_matching_line",
                            "candidates": len(parents) + len(work)})
            continue
        used_targets.add(target.id)
        if target.allocate == "excluded":
            results.append({"key": key, "line_id": target.id, "status": "excluded_skipped"})
            continue
        existing = kids_of.get(target.id) or []
        if any(":fee:" in (c.external_line_id or "") or ":pcbfold:" in (c.external_line_id or "")
               for c in existing):
            results.append({"key": key, "line_id": target.id, "status": "already_split"})
            continue
        if existing:
            results.append({"key": key, "line_id": target.id, "status": "has_hand_children",
                            "children": len(existing)})
            continue

        base_kids = [c for c in kids if c["slug"] != "delta"]
        target_amount = round((target.qty or 0) * (target.unit_price or 0), 4)
        delta = round(target_amount - sum(c["amount"] for c in base_kids), 4)
        if abs(delta) >= 0.01:
            other = "pcba:other" if stage_by_line.get(key) == "pcba" else "fab:other"
            base_kids = base_kids + [{
                "slug": "delta", "step": other, "amount": delta,
                "label": "Invoice line allocation difference vs JLC order totals",
                "external_line_id": f"{key}:fee:delta"}]

        planned = []
        for c in base_kids:
            pos += 1
            planned.append({"label": f"{c['label']} - {key}"[:300], "step": c["step"],
                            "amount": c["amount"], "external_line_id": c["external_line_id"]})
            # Written on a dry run too — the conservation check below then tests
            # the REAL rows, and the rollback discards them (same contract as
            # `apply_parts_document`: the preview runs the real code path).
            db.add(M.RunCostLine(
                document_id=doc.id,
                parent_line_id=target.id,
                run_id=target.run_id,
                project_id=target.project_id,
                position=pos,
                basis="per_run",
                label=f"{c['label']} - {key}"[:300],
                qty=1, unit_price=c["amount"],
                currency=target.currency or doc.currency or "USD",
                allocate="none",
                external_line_id=(c["external_line_id"] or "")[:120],
                plan_key=c["step"],
                notes=("Backfilled from JLC's order fee breakdown "
                       f"(key '{c['slug']}'); destination inherited from the "
                       "line it splits."),
            ))
        made += len(planned)
        value = round(value + sum(c["amount"] for c in base_kids), 2)
        results.append({"key": key, "line_id": target.id, "status": "split",
                        "matched_by": matched_by,
                        "target_amount": target_amount, "delta": delta,
                        "children": planned})

    if made == 0:
        return {"status": "nothing_new", "external_id": row.external_id,
                "document_id": doc.id, "targets": results}
    db.flush()
    try:
        after = _assert_identities(db, before, f"fee backfill for {row.external_id}")
    except ApplyRefused:
        db.rollback()
        raise
    if dry_run:
        db.rollback()
        return {"status": "dry_run", "external_id": row.external_id, "document_id": doc.id,
                "would_create_children": made, "value_split_usd": value,
                "targets": results}
    _write_audit(db, "jlc.import.fee_backfill", doc.id,
                 {"external_id": row.external_id, "children": made,
                  "value_split_usd": value}, actor)
    # NOT committed here — the caller wraps this in `journal.batch(...)`, same
    # contract as every other applier in this module.
    return {"status": "applied", "external_id": row.external_id, "document_id": doc.id,
            "children": made, "value_split_usd": value, "targets": results,
            "identities": after}


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
                    run_actuals.IS_STOCK,
                    M.RunCostLine.voided_at.is_(None))
            .order_by(M.RunCostLine.id).all())
    return {li.lot_ref: li.id for li in rows}


def apply_draws(db: Session, order_plan: dict, run_id: int | None,
                lot_lines: dict[str, int],
                actor: str = "jlc-import", dry_run: bool = True) -> dict:
    """Write MEASURED, lot-bound draws for one assembly order and retire the
    BOM forecasts they replace.

    `run_id=None` writes the STOCK MOVEMENT ALONE, charged to nobody. JLC states
    the consumed lots on the invoice, so the quantity is known the moment the
    document is imported; which batch pays for it is a separate judgement made
    later (`charge_draws`). Nothing is superseded on an uncharged write, because
    a forecast belongs to a run and no run has been named yet.

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
    # Identity is matched on the resolved COMPONENT as well as the supplier's
    # text codes, because neither text field is reliable for this:
    #   * a BOM-derived forecast resolves to `component_id` and leaves `lcsc`
    #     AND `mpn` empty, so `(old.lcsc or old.mpn)` is '' and matches nothing;
    #   * one physical part can carry TWO supplier codes — component 218 is
    #     XL-1005SURC as both C965790 (older purchases, and the BOM) and
    #     C25503345 (what JLC reports today).
    # Either case leaves the forecast un-superseded beside its measurement and
    # charges the run twice. Verified 2026-07-28: 9 such pairs, 20,950 units,
    # $167.95 across 8 runs.
    components_touched: set[int] = set()

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
        if cid is not None:
            components_touched.add(cid)

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
    if not dry_run and run_id is not None:
        voided = _void_superseded(db, run_id, parts_touched, components_touched)

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



def _void_superseded(db: Session, run_id: int, parts: set[str],
                     components: set[int]) -> int:
    """Retire the BOM forecasts a measurement replaces, on ONE run.

    VOID, never delete: this is the row a reversal has to put back, and
    `void_shop.py` / `void_absent.py` deleted 10 draws during the 2026-07
    backfill that could then only be recovered from a database dump.

    Identity is matched on the resolved COMPONENT as well as the supplier's text
    codes, because neither text field is reliable on its own: a BOM forecast
    resolves to `component_id` and leaves `lcsc` and `mpn` empty, and one
    physical part can carry two supplier codes (component 218 is XL-1005SURC as
    both C965790 and C25503345). Either case leaves the forecast un-superseded
    beside its measurement and charges the run twice.
    """
    if not (parts or components):
        return 0
    voided = 0
    for old in (run_actuals.live_consumption(db, run_id=run_id)
                .filter(M.ComponentConsumption.import_ref == "",
                        M.ComponentConsumption.basis.in_(("bom", "manual", "allocated")))
                .all()):
        ident = old.lcsc or old.mpn
        if (ident and ident in parts) or (
                old.component_id is not None and old.component_id in components):
            old.voided_at = utcnow()
            old.void_reason = "superseded_by_measured"
            voided += 1
    return voided


def charge_draws(db: Session, order_plan: dict, run_id: int,
                 actor: str = "jlc-import", dry_run: bool = True) -> dict:
    """Point one assembly order's already-written draws at the run that pays.

    The stock left when the invoice was imported (`apply_draws` with no run).
    This is the second half: the judgement about WHO PAYS, applied to rows that
    already exist. It UPDATES `run_id` and writes no new draw, so the quantity a
    supplier reported can never be restated by a decision about cost.

    Deliberately an update and not a delete-and-reinsert: `journal.batch`
    captures the before-state of every mutated row, so re-pointing is reversible,
    while re-inserting would break `uq_consumption_import` and lose the lot
    bindings underneath.
    """
    code = order_plan["smt_order_code"]
    prefix = f"jlc:{order_plan['batch_num']}:{code}:"
    rows = [c for c in run_actuals.live_consumption(db).all()
            if (c.import_ref or "").startswith(prefix)]
    mine = [c for c in rows if c.run_id is None]
    elsewhere = [c for c in rows if c.run_id is not None and c.run_id != run_id]
    if elsewhere:
        # Already charged to a different batch. Silently re-pointing would move
        # money off a run somebody may have quoted a margin from.
        raise ApplyRefused(
            f"{code}: {len(elsewhere)} draw(s) are already charged to run(s) "
            f"{sorted({c.run_id for c in elsewhere})} — reverse that batch first")
    out = {"smt_order_code": code, "run_id": run_id,
           "uncharged_draws": len(mine),
           "value_usd": round(sum((c.qty or 0) * (c.unit_cost_usd or 0) for c in mine), 2),
           "already_charged": len(rows) - len(mine) - len(elsewhere)}
    if dry_run:
        return {**out, "status": "dry_run"}
    parts = {c.lcsc or c.mpn for c in mine if (c.lcsc or c.mpn)}
    components = {c.component_id for c in mine if c.component_id is not None}
    for c in mine:
        c.run_id = run_id
    out["voided_forecasts"] = _void_superseded(db, run_id, parts, components)
    db.flush()
    _write_audit(db, "jlc.import.draws.charge", None,
                 {"order": code, "run_id": run_id, "charged": len(mine)}, actor)
    return {**out, "status": "charged"}


def draw_stock_for_invoice(db: Session, order_plans: list[dict],
                           actor: str = "jlc-import", dry_run: bool = True) -> dict:
    """Write the stock every assembly order on one invoice consumed, charged
    to nobody.

    Called when the manufacturing document is imported, because that document IS
    the statement of what left the shelf: `presaleDetailResultVOList` itemises
    each consigned lot per order. Waiting for a human to link the order to a
    batch first made a supplier's measurement wait on our bookkeeping, and on
    2026-08-25 that wait became indefinite.

    An order whose lots cannot all be resolved is DEFERRED rather than written
    unallocated, so the purchase invoice can be imported and the draw picked up
    on a re-apply (`uq_consumption_import` makes that a no-op for the rest).
    """
    lot_lines = lot_line_index(db)
    written = deferred = nothing = 0
    detail: list[dict] = []
    for plan in order_plans:
        cons = plan.get("consumption") or []
        if not cons:
            nothing += 1
            continue
        missing = sorted({c.get("lot_key") or "" for c in cons
                          if not lot_lines.get(c.get("lot_key") or "")})
        if missing:
            deferred += 1
            detail.append({"smt_order_code": plan["smt_order_code"],
                           "status": "deferred",
                           "unresolved_lots": len(missing),
                           "hint": "import the JLC parts invoice that supplied these "
                                   "lots, then apply this document again"})
            continue
        res = apply_draws(db, plan, None, lot_lines, actor=actor, dry_run=dry_run)
        written += 1
        detail.append({"smt_order_code": plan["smt_order_code"], **res})
    return {"orders_written": written, "orders_deferred": deferred,
            "orders_without_consumption": nothing, "orders": detail}


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
