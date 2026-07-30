"""JLC import: stage payloads, expose the decision queue, apply one decision.

Split from `jlc_web` (which is transport) and from `jlc_stock` (which runs on the
JOP partner credentials). The shape here is deliberate:

- **Sync only stages.** It never writes a cost row. A scrape of an undocumented,
  unversioned API must not be able to move money unattended; a shape change has
  to surface as a staged payload someone looks at.
- **A decision is stored before it is applied**, keyed on JLC's own
  `smtOrderCode`, so it survives re-fetch, re-import and document deletion.
- **Applying is per-order and idempotent.** Each call is one transaction that
  re-asserts the register identities and rolls back on any regression.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..models import utcnow
from ..services import jlc_apply, jlc_import, jlc_web, journal, run_actuals
from .util import audit

router = APIRouter(prefix="/api/jlc/import", tags=["jlc-import"])

OUTCOMES = {"link_run", "external", "pending"}


class DecisionIn(BaseModel):
    outcome: str
    run_id: int | None = None
    panel_factor: int | None = None
    note: str = ""
    actor: str = "user"


@router.post("/sync")
def sync(limit_pages: int = 4, db: Session = Depends(get_db)):
    """Fetch order batches + invoices into staging. Writes no cost rows."""
    if not jlc_web.available(db):
        raise HTTPException(409, "no JLCPCB browser session stored — paste cookies first")
    try:
        report = jlc_import.sync_stage(db, limit_pages=limit_pages)
    except jlc_web.JlcSessionExpired as e:
        raise HTTPException(401, str(e)) from e
    except jlc_web.JlcWebError as e:
        raise HTTPException(502, str(e)) from e
    if report.get("error"):
        # A shrinking batch list is reported as an error, not an empty queue.
        raise HTTPException(409, report["error"])
    audit(db, "jlc.import.sync", "jlc_import", None, details=report)
    db.commit()
    return report


@router.get("/queue")
def queue(db: Session = Depends(get_db)):
    """Every assembly order with its proposal and the evidence behind it."""
    rows = jlc_import.decision_queue(db)
    pending = [r for r in rows if not r["decision"] or r["decision"]["outcome"] == "pending"]
    return {
        "orders": rows,
        "counts": {
            "total": len(rows),
            "pending": len(pending),
            "decided": len(rows) - len(pending),
            # The invoiced value of orders AWAITING a decision. Deliberately NOT
            # called "unassigned": that word means something precise in
            # `invoice_register` (money no document allocated), and much of this
            # value sits on documents that are already allocated. Conflating the
            # two would make the queue look like a hole in the ledger.
            "pending_invoiced_usd": round(sum(r["money_usd"] or 0 for r in pending), 2),
            # What choosing "external" for every pending order would remove from
            # run costing — the number that must be visible so that decision is
            # deliberate rather than a way to clear a warning.
            "pending_stock_value_usd": round(
                sum(r["consumed_value_usd"] or 0 for r in pending), 2),
        },
    }


@router.get("/staged")
def staged(db: Session = Depends(get_db)):
    """What is in staging — payload sizes only, never the payloads themselves."""
    rows = db.query(M.JlcImport).order_by(M.JlcImport.doc_date.desc()).all()
    return [
        {"id": r.id, "kind": r.kind, "external_id": r.external_id,
         "invoice_no": r.invoice_no, "doc_date": r.doc_date,
         "total_amount": r.total_amount, "presale_amount": r.presale_amount,
         "status": r.status, "document_id": r.document_id,
         "has_payload": bool(r.payload),
         # A fetch that FAILED leaves `payload` NULL; a fetch that SUCCEEDED and
         # found nothing leaves `{}` — JLC has issued no invoice for that batch
         # yet. Both render as "no payload" otherwise, and only one of them is
         # worth re-syncing, so the two are reported apart.
         "payload_empty": r.payload is not None and not r.payload,
         "fetched_at": r.fetched_at.isoformat() if r.fetched_at else None}
        for r in rows
    ]


@router.put("/decision/{smt_order_code}")
def set_decision(smt_order_code: str, body: DecisionIn, db: Session = Depends(get_db)):
    """Record a decision. Does NOT apply it — see /apply."""
    if body.outcome not in OUTCOMES:
        raise HTTPException(422, f"outcome must be one of {sorted(OUTCOMES)}")
    if body.outcome == "link_run":
        if body.run_id is None:
            raise HTTPException(422, "link_run requires a run_id")
        if db.get(M.ProductionRun, body.run_id) is None:
            raise HTTPException(404, f"run {body.run_id} not found")
        # SEVERAL assembly orders may build ONE run — confirmed by the user
        # 2026-07-28: Aqua Batch 1 (315 good) was assembled as 125 in June plus
        # 200 in July 2024, 325 built. An earlier version refused the second
        # order as a collision, which was simply wrong about how production
        # works. So this is allowed, and merely reported.
        siblings = (
            db.query(M.JlcOrderDecision)
            .filter(M.JlcOrderDecision.run_id == body.run_id,
                    M.JlcOrderDecision.outcome == "link_run",
                    M.JlcOrderDecision.smt_order_code != smt_order_code)
            .all()
        )

    row = (db.query(M.JlcOrderDecision)
             .filter_by(smt_order_code=smt_order_code).first())
    if row is None:
        row = M.JlcOrderDecision(smt_order_code=smt_order_code)
        db.add(row)
    row.outcome = body.outcome
    row.run_id = body.run_id if body.outcome == "link_run" else None
    row.panel_factor = body.panel_factor
    row.note = body.note[:500]
    row.decided_by = body.actor[:100]
    audit(db, "jlc.import.decision", "jlc_order_decision", smt_order_code,
          details={"outcome": body.outcome, "run_id": body.run_id,
                   "panel_factor": body.panel_factor}, actor=body.actor)
    db.commit()

    # Report the run's fill so an over-assignment is visible immediately. Not an
    # error — a batch legitimately built across two orders sums to slightly MORE
    # than its recorded quantity, because that quantity counts good units.
    fill = None
    if body.outcome == "link_run" and body.run_id:
        fill = _run_fill(db, body.run_id)
    return {"smt_order_code": smt_order_code, "outcome": row.outcome,
            "run_id": row.run_id, "panel_factor": row.panel_factor,
            "run_fill": fill,
            "sibling_orders": [s.smt_order_code for s in siblings]
            if body.outcome == "link_run" else []}


def _run_fill(db: Session, run_id: int) -> dict:
    """How many devices the orders linked to a run add up to, against what the
    run records. `built >= good` is normal; `built < good` is impossible and
    means an order is missing or mis-assigned."""
    run = db.get(M.ProductionRun, run_id)
    codes = [d.smt_order_code for d in db.query(M.JlcOrderDecision)
             .filter_by(run_id=run_id, outcome="link_run").all()]
    devices = 0
    for row in db.query(M.JlcImport).filter_by(kind="assembly").all():
        for code, info in (row.panel_info or {}).items():
            if code in codes and info.get("devices"):
                devices += info["devices"]
    recorded = (run.qty or run.plan_qty or 0) if run else 0
    return {
        "run_id": run_id, "orders": codes, "devices_built": devices,
        "run_qty": recorded,
        "delta": devices - recorded,
        "yield_loss_pct": (round(100 * (devices - recorded) / devices, 2)
                           if devices else None),
        "short": devices < recorded,
    }


@router.delete("/decision/{smt_order_code}")
def clear_decision(smt_order_code: str, db: Session = Depends(get_db)):
    row = db.query(M.JlcOrderDecision).filter_by(smt_order_code=smt_order_code).first()
    if row is None:
        raise HTTPException(404, "no decision recorded for that order")
    if row.applied_at is not None:
        raise HTTPException(
            409, "that decision has already been applied — reverse the money it "
                 "moved before clearing it, or the ledger and the decision disagree")
    db.delete(row)
    audit(db, "jlc.import.decision.clear", "jlc_order_decision", smt_order_code)
    db.commit()
    return {"cleared": smt_order_code}


def _decisions_map(db: Session) -> dict[str, dict]:
    """Every recorded decision, keyed for the planner.

    The planner has always accepted this and the one live caller never passed it,
    so every imported manufacturing line was written with `run_id=NULL` — the
    single defect that made `fix_alloc.py` necessary.
    """
    return {d.smt_order_code: {"outcome": d.outcome, "run_id": d.run_id,
                               "panel_factor": d.panel_factor}
            for d in db.query(M.JlcOrderDecision).all()}


def _staged(db: Session, external_id: str) -> M.JlcImport:
    row = db.query(M.JlcImport).filter_by(external_id=external_id).first()
    if row is None or not row.payload:
        raise HTTPException(404, f"{external_id} is not staged — run a sync first")
    return row


@router.get("/preview/{external_id}")
def preview(external_id: str, db: Session = Depends(get_db)):
    """What importing this batch WOULD do, run through the real write path and
    rolled back — so the numbers shown are the numbers a real import produces."""
    row = _staged(db, external_id)
    from ..services.jlc_invoice import parse
    inv = parse(row.payload)
    plan = jlc_import.plan_manufacturing_document(inv, _decisions_map(db),
                                                  fee_info=row.fee_info)
    try:
        res = jlc_apply.apply_manufacturing_document(db, plan, dry_run=True)
    except jlc_apply.ApplyRefused as e:
        raise HTTPException(409, str(e)) from e
    return {"plan": {k: v for k, v in plan.items() if k != "lines"},
            "line_count": len(plan["lines"]),
            "lines": plan["lines"], "result": res}


@router.post("/documents/{external_id}/apply")
def apply_document(external_id: str, dry_run: bool = True, actor: str = "user",
                   db: Session = Depends(get_db)):
    """Import ONE staged assembly batch as a cost document.

    Replaces `import_all.py`. Two things it does that the script did not: it
    passes the recorded decisions to the planner, so lines land already pointed at
    their run instead of at nobody; and it runs inside a `journal.batch`, so it
    can be undone from the UI.
    """
    row = _staged(db, external_id)
    from ..services.jlc_invoice import parse
    inv = parse(row.payload)
    plan = jlc_import.plan_manufacturing_document(inv, _decisions_map(db),
                                                  fee_info=row.fee_info)

    if dry_run:
        try:
            return {"dry_run": True, "plan": {k: v for k, v in plan.items() if k != "lines"},
                    "lines": plan["lines"],
                    "result": jlc_apply.apply_manufacturing_document(db, plan, dry_run=True)}
        except jlc_apply.ApplyRefused as e:
            raise HTTPException(409, str(e)) from e

    try:
        with journal.batch(db, kind="jlc.mfg.import", source_ref=external_id, actor=actor,
                           summary={"invoice_no": plan.get("doc_number"),
                                    "total_amount": plan.get("total_amount"),
                                    "lines": len(plan["lines"])}) as h:
            res = jlc_apply.apply_manufacturing_document(db, plan, actor=actor)
            if res.get("status") == "created":
                # Close the staging loop. Left un-stamped by the backfill, which is
                # why all 37 rows still read `status='staged'` with a NULL
                # `document_id` against 24 documents actually imported — the table
                # designed to answer "what is left?" could not.
                row.status = "imported"
                row.document_id = res["document_id"]
    except jlc_apply.ApplyRefused as e:
        raise HTTPException(409, str(e)) from e
    if res.get("status") in ("exists", "probable_duplicate"):
        raise HTTPException(409, {"error": res["status"], **res})
    audit(db, "jlc.import.document.apply", "run_cost_document", res.get("document_id"),
          details={"external_id": external_id, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**res, "batch_id": h["batch_id"], "reversible": True}


@router.get("/parts")
def list_parts_orders(db: Session = Depends(get_db)):
    """Every JLC parts order (POB…) with whether the platform already holds it.

    Live, not staged: `sync` stages assembly batches only. Grouping happens here
    rather than in the browser because `index_parts_orders` keys by
    `presaleGoodsKeyId` — one entry per LOT, 215 across 16 orders — and a client
    re-deriving that would be a second place for the key to be got wrong.
    """
    if not jlc_web.available(db):
        raise HTTPException(409, "no JLCPCB browser session stored — paste cookies first")
    try:
        index = jlc_import.index_parts_orders(jlc_web.list_parts_orders(db))
    except jlc_web.JlcSessionExpired as e:
        raise HTTPException(401, str(e)) from e
    except jlc_web.JlcWebError as e:
        raise HTTPException(502, str(e)) from e

    by_pob: dict[str, list[dict]] = {}
    for lot in index.values():
        by_pob.setdefault(lot["purchase_batch_no"], []).append(lot)

    out = []
    for pob, lots in sorted(by_pob.items()):
        doc = jlc_apply.find_document(db, pob, "")
        near = jlc_apply.find_near_duplicate(db, pob) if doc is None else None
        out.append({
            "pob": pob,
            "lots": len(lots),
            "cancelled_lots": sum(1 for lot in lots if lot.get("cancelled")),
            "paid_usd": round(sum(lot["paid_usd"] for lot in lots), 2),
            "document_id": doc.id if doc else None,
            # A fuzzy reference match is REPORTED, never acted on: `POB0202510222305546`
            # exists in this database as `POB00202510222305546`, and an importer that
            # trusted exact match alone created a second document for a purchase
            # already recorded, doubling it in the pool.
            "near_duplicate_document_id": near.id if near else None,
            "near_duplicate_ref": (near.external_id or near.doc_number) if near else "",
        })
    return {"orders": out,
            "totals": {"orders": len(out), "lots": len(index),
                       "imported": sum(1 for o in out if o["document_id"]),
                       "not_imported_usd": round(
                           sum(o["paid_usd"] for o in out if not o["document_id"]), 2)}}


@router.post("/parts/{pob}/apply")
def apply_parts(pob: str, dry_run: bool = True, actor: str = "user",
                db: Session = Depends(get_db)):
    """Import ONE JLC parts order (POB…) as the purchase document whose lines ARE
    the lots every later draw binds to.

    Fetched live rather than from staging: `sync` stages assembly batches only, and
    a lot's quantity and price come from the ORDER page, never the invoice — the
    invoice understates by JLC's sourcing fee ($1,623.23 across the account).
    """
    if not jlc_web.available(db):
        raise HTTPException(409, "no JLCPCB browser session stored — paste cookies first")
    try:
        raw = jlc_web.list_parts_orders(db)
        # `index_parts_orders` keys by `presaleGoodsKeyId` — one entry per LOT, not
        # per order (215 lots across 16 orders). Group by the order each lot names.
        index = jlc_import.index_parts_orders(raw)
        lots = [lot for lot in index.values() if lot.get("purchase_batch_no") == pob]
        if not lots:
            known = sorted({lot.get("purchase_batch_no") for lot in index.values()})
            raise HTTPException(
                404, f"{pob} is not among your JLC parts orders. Visible: {known}")
        invoice_raw = jlc_web.get_parts_invoice(db, pob)
    except jlc_web.JlcSessionExpired as e:
        raise HTTPException(401, str(e)) from e
    except jlc_web.JlcWebError as e:
        raise HTTPException(502, str(e)) from e

    plan = jlc_import.plan_parts_document(pob, lots, invoice_raw)
    if dry_run:
        return {"dry_run": True, "plan": {k: v for k, v in plan.items() if k != "lines"},
                "lines": plan["lines"],
                "result": jlc_apply.apply_parts_document(db, plan, dry_run=True)}

    with journal.batch(db, kind="jlc.parts.import", source_ref=pob, actor=actor,
                       summary={"total_amount": plan.get("total_amount"),
                                "lots": plan.get("lot_count")}) as h:
        res = jlc_apply.apply_parts_document(db, plan, actor=actor)
    if res.get("status") in ("exists", "probable_duplicate"):
        raise HTTPException(409, {"error": res["status"], **res})
    audit(db, "jlc.import.parts.apply", "run_cost_document", res.get("document_id"),
          details={"pob": pob, "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**res, "batch_id": h["batch_id"], "reversible": True}


@router.post("/orders/{smt_order_code}/fetch-bom")
def fetch_bom(smt_order_code: str, db: Session = Depends(get_db)):
    """Cache JLC's OWN BOM for one assembly order — the only source of
    `componentSource`, i.e. who actually supplied each part.

    Evidence, not money: it writes `jlc_imports.bom_info` and nothing else, so it
    is not journalled. Without it every draw silently assumes the part came out of
    YOUR consigned stock, and the parts JLC supplied and separately charged for
    (`componentSource='shop'`, $6,290.53 across the account) get charged to the
    pool a second time.

    Two hops, because the BOM is keyed on the order's UUID and not on its SMT
    code: the order-centre view maps one to the other.
    """
    if not jlc_web.available(db):
        raise HTTPException(409, "no JLCPCB browser session stored — paste cookies first")
    row = (db.query(M.JlcImport)
           .filter(M.JlcImport.kind == "assembly",
                   M.JlcImport.panel_info.isnot(None)).all())
    batch = next((r for r in row if smt_order_code in (r.panel_info or {})), None)
    if batch is None:
        raise HTTPException(404, f"{smt_order_code} is not in any staged batch — sync first")
    try:
        person = jlc_web.get_person_order(db, batch.external_id)
        nums = jlc_web.smt_order_nums(person)
        uuid = nums.get(smt_order_code)
        if not uuid:
            raise HTTPException(
                404, f"JLC's order-centre view for {batch.external_id} does not list "
                     f"{smt_order_code} — it may belong to a different batch")
        detail = jlc_web.get_smt_order_detail(db, uuid)
    except jlc_web.JlcSessionExpired as e:
        raise HTTPException(401, str(e)) from e
    except jlc_web.JlcWebError as e:
        raise HTTPException(502, str(e)) from e

    bom = detail.get("smtBomResult") or []
    by_source: dict[str, int] = {}
    for b in bom:
        src = str(b.get("componentSource") or "unknown")
        by_source[src] = by_source.get(src, 0) + 1
    # Merge rather than replace: one batch holds several orders and each is fetched
    # on its own, so overwriting would discard the siblings already cached.
    merged = dict(batch.bom_info or {})
    merged[smt_order_code] = bom
    batch.bom_info = merged
    audit(db, "jlc.order.fetch_bom", "jlc_import", batch.id,
          details={"smt_order_code": smt_order_code, "rows": len(bom),
                   "by_source": by_source})
    db.commit()
    return {"smt_order_code": smt_order_code, "batch": batch.external_id,
            "rows": len(bom), "by_component_source": by_source,
            "shop_parts": [
                {"lcsc": b.get("componentCode"), "mpn": b.get("componentModel"),
                 "qty": b.get("componentNum"), "source": b.get("componentSource")}
                for b in bom if str(b.get("componentSource") or "") == "shop"],
            }


@router.post("/decision/{smt_order_code}/void-shop-draws")
def void_shop_draws(smt_order_code: str, dry_run: bool = True, actor: str = "user",
                    db: Session = Depends(get_db)):
    """Void draws for parts JLC supplied ITSELF, so they are not paid for twice.

    A `componentSource='shop'` part was bought by JLC and billed on the assembly
    invoice, which the platform already records. A draw for the same part also
    takes it out of YOUR pool, charging the run a second time from stock that never
    moved. Replaces `void_shop.py` and `void_absent.py`, which between them deleted
    10 rows irreversibly — here they are VOIDED inside a reversible batch.

    Guarded on `lcsc <> ''`: a draw with no LCSC code cannot be matched against
    JLC's list by identity, and `component_id IS NULL` means UNRESOLVED, not
    "never purchased" — treating it as the latter is what deleted the real KARTON
    packaging draws during the backfill.
    """
    dec = db.query(M.JlcOrderDecision).filter_by(smt_order_code=smt_order_code).first()
    if dec is None or dec.outcome != "link_run" or not dec.run_id:
        raise HTTPException(409, "only an order linked to a run can have draws to void")

    bom = None
    for row in db.query(M.JlcImport).filter(M.JlcImport.bom_info.isnot(None)).all():
        if smt_order_code in (row.bom_info or {}):
            bom = row.bom_info[smt_order_code]
            break
    if bom is None:
        raise HTTPException(
            409, f"JLC's own BOM for {smt_order_code} has not been fetched — "
                 f"POST /api/jlc/import/orders/{smt_order_code}/fetch-bom first. "
                 "Without it, which parts JLC supplied is unknown, and guessing "
                 "would either double-charge the run or un-cost a real purchase")

    shop = {str(b.get("componentCode") or "").strip().upper()
            for b in bom if str(b.get("componentSource") or "") == "shop"}
    shop.discard("")
    if not shop:
        return {"smt_order_code": smt_order_code, "status": "nothing_to_void",
                "note": "JLC supplied none of this order's parts itself"}

    victims = [c for c in run_actuals.live_consumption(db, run_id=dec.run_id).all()
               if (c.lcsc or "").strip().upper() in shop]
    plan = [{"consumption_id": c.id, "lcsc": c.lcsc, "mpn": c.mpn, "qty": c.qty,
             "value_usd": round((c.qty or 0) * (c.unit_cost_usd or 0), 2),
             "basis": c.basis} for c in victims]
    out = {"smt_order_code": smt_order_code, "run_id": dec.run_id,
           "shop_parts": sorted(shop), "would_void": plan,
           "value_usd": round(sum(p["value_usd"] for p in plan), 2), "dry_run": dry_run}
    if dry_run or not victims:
        out["status"] = "dry_run" if dry_run else "nothing_to_void"
        return out

    with journal.batch(db, kind="draws.void", source_ref=smt_order_code, actor=actor,
                       summary={"reason": "jlc supplied these parts itself",
                                "count": len(victims),
                                "value_usd": out["value_usd"]}) as h:
        for c in victims:
            c.voided_at = utcnow()
            c.void_reason = "jlc_supplied"
    audit(db, "jlc.draws.void_shop", "jlc_order_decision", smt_order_code,
          details={"voided": len(victims), "value_usd": out["value_usd"],
                   "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    out.update(status="voided", batch_id=h["batch_id"], reversible=True)
    return out


@router.post("/decision/{smt_order_code}/apply")
def apply_decision(smt_order_code: str, dry_run: bool = True, actor: str = "user",
                   db: Session = Depends(get_db)):
    """Move the money a decision implies. Replaces `draws_apply.py`, `fix_alloc.py`,
    `mark_external.py` and `apply_manual.py`.

    `link_run`: point the order's invoice lines at the run, then write measured,
    lot-bound draws. `external`: exclude the lines with a stated reason and book the
    stock out of the pool charged to nobody.

    One transaction, one reversible batch, and `applied_at` stamped — which is what
    makes `DELETE /decision/{code}`'s refusal real rather than dead code.
    """
    dec = (db.query(M.JlcOrderDecision)
             .filter_by(smt_order_code=smt_order_code).first())
    if dec is None or dec.outcome == "pending":
        raise HTTPException(409, "no decision recorded for that order — decide it first")
    if dec.applied_at is not None and not dry_run:
        raise HTTPException(409, {
            "error": "already applied",
            "applied_at": dec.applied_at.isoformat(),
            "hint": "reverse its write batch in /api/ledger/batches before re-applying"})

    plan = jlc_import.order_plan_for(db, smt_order_code)
    if plan is None:
        raise HTTPException(404, f"{smt_order_code} is not in any staged invoice")

    lots_by_key = jlc_import.lots_by_key(db)
    out: dict = {"smt_order_code": smt_order_code, "outcome": dec.outcome,
                 "run_id": dec.run_id, "dry_run": dry_run}
    try:
        if dry_run:
            out["lines"] = jlc_apply.reclassify_order_lines(
                db, smt_order_code, dec.outcome, dec.run_id, dry_run=True)
            if dec.outcome == "link_run":
                out["draws"] = jlc_apply.apply_draws(
                    db, plan, dec.run_id, jlc_apply.lot_line_index(db),
                    actor=actor, dry_run=True)
            else:
                movements = jlc_import.external_stock_movements(plan, lots_by_key)
                out["movements"] = jlc_apply.apply_external_movements(
                    db, plan, movements, actor=actor, dry_run=True)
            return out

        with journal.batch(db, kind="jlc.decision.apply", source_ref=smt_order_code,
                           actor=actor,
                           summary={"outcome": dec.outcome, "run_id": dec.run_id}) as h:
            out["lines"] = jlc_apply.reclassify_order_lines(
                db, smt_order_code, dec.outcome, dec.run_id, actor=actor)
            if dec.outcome == "link_run":
                out["draws"] = jlc_apply.apply_draws(
                    db, plan, dec.run_id, jlc_apply.lot_line_index(db),
                    actor=actor, dry_run=False)
            else:
                movements = jlc_import.external_stock_movements(plan, lots_by_key)
                out["movements"] = jlc_apply.apply_external_movements(
                    db, plan, movements, actor=actor, dry_run=False)
            dec.applied_at = utcnow()
    except jlc_apply.ApplyRefused as e:
        raise HTTPException(409, str(e)) from e

    audit(db, "jlc.import.decision.apply", "jlc_order_decision", smt_order_code,
          details={"outcome": dec.outcome, "run_id": dec.run_id,
                   "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    out["batch_id"] = h["batch_id"]
    out["reversible"] = True
    return out


@router.post("/fees/refresh")
def refresh_fees(force: bool = False, db: Session = Depends(get_db)):
    """Fetch the per-order fee breakdown for staged batches that miss it.

    The fee cache (`fee_info`) was added after the invoice cache, so batches
    staged earlier hold payloads but no breakdown. Evidence only — no money
    moves; the breakdown is what /fees/backfill and fresh imports split from.
    `force=true` re-fetches every batch (a re-settled order changes its tolls).
    """
    if not jlc_web.available(db):
        raise HTTPException(409, "no JLCPCB browser session stored — paste cookies first")
    rows = db.query(M.JlcImport).filter_by(kind="assembly").all()
    fetched = skipped = failed = 0
    for row in rows:
        if not row.payload:
            skipped += 1
            continue
        if row.fee_info is not None and not force:
            skipped += 1
            continue
        try:
            ok = jlc_import._fetch_fee_info(db, row)
        except jlc_web.JlcSessionExpired as e:
            raise HTTPException(401, str(e)) from e
        fetched += 1 if ok else 0
        failed += 0 if ok else 1
    audit(db, "jlc.import.fees.refresh", "jlc_import", None,
          details={"fetched": fetched, "skipped": skipped, "failed": failed})
    db.commit()
    return {"fetched": fetched, "skipped": skipped, "failed": failed}


@router.post("/fees/backfill")
def backfill_fees(external_id: str = "", dry_run: bool = True, actor: str = "user",
                  db: Session = Depends(get_db)):
    """Split ALREADY-imported batch documents into JLC's own fee itemization.

    Each document is one reversible journal batch. Children inherit their
    line's destination, so no money changes owner — only its step grain. Lines
    with hand-made children are skipped and reported, never merged.
    """
    q = db.query(M.JlcImport).filter_by(kind="assembly")
    if external_id:
        q = q.filter_by(external_id=external_id)
    rows = [r for r in q.all() if r.payload]
    if external_id and not rows:
        raise HTTPException(404, f"{external_id} is not staged")

    reports = []
    applied = 0
    for row in sorted(rows, key=lambda r: r.external_id):
        try:
            if dry_run:
                reports.append(jlc_apply.backfill_fee_split(db, row, actor=actor,
                                                            dry_run=True))
                continue
            # `journal.batch` writes NO header when the body touched no
            # journalled row, so a no-op batch leaves no trace by itself.
            with journal.batch(db, kind="jlc.fees.backfill", source_ref=row.external_id,
                               actor=actor,
                               summary={"external_id": row.external_id}) as h:
                res = jlc_apply.backfill_fee_split(db, row, actor=actor, dry_run=False)
            db.commit()
            if res.get("status") == "applied":
                res["batch_id"] = h["batch_id"]
                res["reversible"] = h["batch_id"] is not None
                applied += 1
            reports.append(res)
        except jlc_apply.ApplyRefused as e:
            db.rollback()
            reports.append({"external_id": row.external_id, "status": "refused",
                            "error": str(e)})
    summary = {
        "documents_seen": len(rows),
        "applied": applied,
        "children_created": sum(r.get("children") or r.get("would_create_children") or 0
                                for r in reports),
        "value_split_usd": round(sum(r.get("value_split_usd") or 0 for r in reports), 2),
        "by_status": {},
    }
    for r in reports:
        s = r.get("status") or "?"
        summary["by_status"][s] = summary["by_status"].get(s, 0) + 1
    if not dry_run:
        audit(db, "jlc.import.fees.backfill", "jlc_import", None,
              details=summary, actor=actor)
        db.commit()
    return {"dry_run": dry_run, "summary": summary, "documents": reports}
