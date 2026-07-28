"""Plan a JLCPCB import — decide what WOULD be written, and write nothing.

This module is deliberately split from the applier. A plan is a plain dict that
can be diffed against the platform's current state, shown to a human, and
re-derived from a cached payload forever. Nothing here opens a write
transaction, and `services/jlc_web.py` reads are already side-effect free, so a
sync can never move money as a consequence of looking.

Facts this encodes, all verified against the live account on 2026-07-28. Each was
a trap that a naive importer falls into:

1. **A lot's cost is `goodsPaidMoney / settlePresaleNumber`, not `goodsMoney`.**
   Every JLC purchase row carries both, and they differ by JLC's sourcing fee on
   `presaleType='buy'` sub-orders (never on `'stock'`). Using `goodsMoney`
   under-costs the existing data by $1,623.23 over $29,639 of spend — the ESP32
   reads 2.2146 against 2.82 actually paid.

2. **`settlePresaleNumber` is the lot size, and it can be 0 with money paid.**
   Two real rows paid $349.39 and $16.01 for zero delivered parts (cancelled
   sub-orders, `orderStatus=40`). Dividing by the settled quantity is a division
   by zero; using `presaleNumber` instead invents stock that never arrived. Such
   rows become a FEE against no lot.

3. **`presaleGoodsKeyId` joins consumption to purchase.** Verified 50/50 on
   W2026051200251365, with `componentCode` agreeing on all 50. This is what makes
   a draw's lot assignment REPORTED rather than inferred; FIFO is the fallback
   for a supplier who tells us nothing, and the distinction must survive into the
   data.

4. **`number` on an assembly line is PANELS when the order was panelised**, and
   there is no panelisation field anywhere in JLC's payloads. It must never be
   read as a device count. The factor is instead DERIVED from the run's BOM —
   every part votes `consumed / (number x bom_per_device)` and the votes are
   unanimous when the run is right (19/19 returned k=4 on the verified invoice),
   which is why run proposal and panel detection are one step, not two.

5. **The ORDER page, not the invoice, is settled truth.** A refund or
   re-settlement after invoicing is normal (a real $8.40 refund, and a
   0.0234 -> 0.0031 correction). So lot quantity and price come from
   `selectPresaleOrderList`; the invoice supplies only document identity and the
   printed total, and a divergence is reported rather than silently resolved.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime

from sqlalchemy.orm import Session

from .. import models as M
from . import jlc_invoice

log = logging.getLogger(__name__)

SUPPLIER = "JLCPCB"

# Document match tolerances (tier 3 only — tiers 1 and 2 are exact).
AMOUNT_EPS = 0.01
DATE_DAYS = 7

# A panel-factor vote is accepted when this share of BOM-resolvable parts agree.
PANEL_VOTE_SHARE = 0.8
# How far an assembly order's invoice may sit from the run's own date before a
# quantity match is treated as coincidence rather than evidence. Generous,
# because JLC invoices weeks after production and a batch can be re-invoiced.
MAX_DATE_GAP_DAYS = 120
# Per-part tolerance on the implied factor. JLC's setup overage is a fixed
# absolute surplus (a few pieces), so the fractional part is small but nonzero.
PANEL_FRAC_TOL = 0.08


# ---------------------------------------------------------------- purchases
def index_parts_orders(raw_list: dict) -> dict:
    """Flatten `selectPresaleOrderList` into lots keyed by `presaleGoodsKeyId`.

    Sub-orders arrive split across four parallel lists by fulfilment type and
    ALL must be read — `stockList` alone silently drops every part JLC sourced
    for us, which is exactly the set carrying a fee.
    """
    lots: dict[str, dict] = {}
    for batch in (raw_list.get("list") or []):
        pob = str(batch.get("orderBatchNo") or "")
        for bucket in ("stockList", "buyList", "overseasShopList", "idleOrderList"):
            for so in (batch.get(bucket) or []):
                presale_type = str(so.get("presaleType") or "")
                status = so.get("orderStatus")
                for g in (so.get("presaleGoodsRecords") or []):
                    key = g.get("presaleGoodsKeyId")
                    if key is None:
                        continue
                    lots[str(key)] = _lot_from_goods(g, pob, so, presale_type, status)
    return lots


def _lot_from_goods(g: dict, pob: str, so: dict, presale_type: str, status) -> dict:
    """One purchase lot. `cost_source` records WHY the unit cost is what it is,
    so a reader never has to guess which of JLC's two amounts was used."""
    settled = jlc_invoice._f(g.get("settlePresaleNumber"))
    ordered = jlc_invoice._f(g.get("presaleNumber"))
    paid = jlc_invoice._f(g.get("goodsPaidMoney"))
    goods = jlc_invoice._f(g.get("goodsMoney"))
    quoted = jlc_invoice._f(g.get("goodsPrice"))

    # Landed unit = what we actually paid, spread over what actually arrived.
    unit = round(paid / settled, 8) if settled > 0 else None
    fee = round(paid - goods, 4)

    return {
        "lot_key": str(g.get("presaleGoodsKeyId")),
        "purchase_batch_no": pob,
        "purchase_order_no": str(so.get("presaleOrderNo") or ""),
        "presale_type": presale_type,
        "order_status": status,
        "cancelled": status == 40 or settled <= 0,
        "lcsc": str(g.get("componentCode") or ""),
        "mpn": str(g.get("componentModel") or ""),
        "description": str(g.get("description") or "")[:500],
        "qty_ordered": ordered,
        "qty": settled,
        "unit_cost_usd": unit,
        "paid_usd": paid,
        "goods_usd": goods,
        "quoted_unit": quoted,
        "sourcing_fee_usd": fee,
        "cost_source": "goodsPaidMoney/settlePresaleNumber",
        # A cancelled row still cost money — it must land as a fee, never as a lot.
        "fee_only": settled <= 0 and paid > 0,
    }


def plan_parts_document(pob: str, lots: list[dict], invoice_raw: dict | None) -> dict:
    """One POB purchase order -> one shared cost document whose part lines ARE
    the lots. `project_id` is None on purpose: a parts purchase is stockpile
    replenishment shared across products, which is the codebase's existing
    shared-document semantics."""
    real = [lot for lot in lots if not lot["fee_only"]]
    fees = [lot for lot in lots if lot["fee_only"]]
    lines = [
        {
            "kind": "part",
            "run_id": None,
            "allocate": "none",
            "label": lot["mpn"] or lot["lcsc"],
            "lcsc": lot["lcsc"],
            "mpn": lot["mpn"],
            "qty": lot["qty"],
            "unit_price": lot["unit_cost_usd"],
            "lot_ref": lot["lot_key"],
            "supplier_order_ref": lot["purchase_batch_no"],
            "notes": (
                f"lot {lot['lot_key']} from {lot['purchase_order_no']} "
                f"({lot['presale_type']}); paid ${lot['paid_usd']} for {lot['qty']:g} "
                f"= ${lot['unit_cost_usd']}/pc"
                + (f"; includes ${lot['sourcing_fee_usd']} sourcing fee"
                   if lot["sourcing_fee_usd"] > 0.005 else "")
            ),
        }
        for lot in real
    ]
    for lot in fees:
        lines.append({
            # "fee" is NOT a valid RunCostLine.kind (see run_costs.KINDS);
            # "other" is the honest bucket for money paid against no goods.
            "kind": "other",
            "run_id": None,
            "allocate": "none",
            "label": f"Cancelled: {lot['mpn'] or lot['lcsc']}",
            "lcsc": "",
            "mpn": "",
            "qty": 1,
            "unit_price": lot["paid_usd"],
            "lot_ref": "",
            "supplier_order_ref": lot["purchase_batch_no"],
            "notes": (
                f"paid ${lot['paid_usd']} but {lot['qty_ordered']:g} ordered and NONE settled "
                f"(order status {lot['order_status']}) — real money, no parts, so it is a fee "
                "rather than a lot"
            ),
        })

    inv = invoice_raw or {}
    return {
        "kind": "parts",
        "external_id": pob,
        "doc_number": str(inv.get("invoiceNo") or ""),
        "doc_date": jlc_invoice.parse_invoice_date(inv.get("invoiceDate")),
        "currency": "USD",
        "total_amount": round(sum(lot["paid_usd"] for lot in lots), 2),
        "invoice_total": jlc_invoice._f(inv.get("totalPayment")) if inv else None,
        "lines": lines,
        "lot_count": len(real),
        "fee_count": len(fees),
        "sourcing_fee_usd": round(sum(lot["sourcing_fee_usd"] for lot in real), 2),
    }


def plan_manufacturing_document(inv: dict, decisions: dict[str, dict] | None = None) -> dict:
    """One W batch -> one cost document.

    The invoice arithmetic, DERIVED from the real payloads rather than assumed
    (verified on all 35 invoices in the account):

        totalMoney = productMoney + carriageMoney + tariffChargesMoney
                     + serviceCharges - discount

    and `productMoney == sum(invoiceListResponseList[].totalMoney)`. Two
    consequences shape the mapping:

    1. **`presaleMoney` is INSIDE the line total, not additional to it.** The
       assembly line reading $7,038.51 already contains $5,896.42 of prepaid
       components; the remaining $1,142.09 is the assembly work. Adding the
       prepaid amount as its own top-level line double-counts it — which is
       exactly what an earlier version of this function did, inflating one
       invoice by $5,726.80. So the prepaid portion becomes an `excluded` CHILD
       that carves the line up, and the parent keeps what the invoice printed.
    2. **Freight, tariff, service charge and discount are HEADER figures.** The
       per-line freight does NOT sum to the header value (251.88 vs 264.42 on a
       real invoice), so taking them per line loses money.

    Freight and tariff are direct run costs, not `by_value` carriers: a carrier
    spreads over poolable part lines in the same document and a manufacturing
    invoice has none — its components arrived through their own POB purchase.
    """
    decisions = decisions or {}
    lines: list[dict] = []
    t = inv["totals"]

    for li in inv["lines"]:
        if not li["total"]:
            continue
        code = li["smt_order_code"] or li["order_code"]
        dec = decisions.get(code) or {}
        run_id = dec.get("run_id")
        stage = li["stage"]
        kind, step = {
            "pcba": ("assembly", "pcba:general"),
            "stencil": ("tooling", "pcba:stencil"),
            "fab": ("fab", "fab:pcb"),
        }.get(stage, ("other", ""))

        note = (
            f"{li['qty']:g} x {li['unit_price']} per JLC. NOTE: JLC's quantity is PANELS "
            f"when the order was panelised, never a device count."
            + (f" File: {li['file_name']}." if li["file_name"] else "")
        )
        parent = {
            "kind": kind, "plan_key": step, "allocate": "none",
            "run_id": None if li["presale"] else run_id,
            "label": f"{li['order_type_raw'][:60]} - {li['order_code']}",
            "qty": 1, "unit_price": li["total"],
            "external_line_id": li["order_code"],
            "notes": note,
            "children": [],
        }
        if li["presale"]:
            # A line with live children is a header worth zero, so the money must
            # live entirely in the children — the excluded prepaid slice plus the
            # assembly work that is actually chargeable to the run.
            parent["children"] = [
                {
                    "kind": "part", "plan_key": "parts:prepaid", "allocate": "excluded",
                    # An exclusion without a stated reason is invisible: `excluded`
                    # is a legal bucket in the conservation identity, which is how
                    # $14,443 sat charged to nobody with every check green.
                    "exclude_reason": "prepaid_components",
                    "run_id": None,
                    "label": f"Prepaid components - {li['order_code']}",
                    "qty": 1, "unit_price": li["presale"],
                    "external_line_id": f"{li['order_code']}:prepaid",
                    "notes": ("Already paid via the POB parts order and already in the "
                              "pool. Recorded so the document reconciles; charged to "
                              "nobody on purpose."),
                },
                {
                    "kind": kind, "plan_key": step, "allocate": "none", "run_id": run_id,
                    "label": f"Assembly work - {li['order_code']}",
                    "qty": 1, "unit_price": round(li["total"] - li["presale"], 4),
                    "external_line_id": f"{li['order_code']}:work",
                    "notes": (f"line total ${li['total']} minus ${li['presale']} of prepaid "
                              "components already in the pool"),
                },
            ]
        lines.append(parent)

    # Header-level charges. Any run attribution is left to the operator: freight
    # on a multi-order batch is not divisible by any rule the invoice supports.
    for amount, kind, step, label in (
        (t["freight"], "freight", "logistics:inbound", "Freight (whole batch)"),
        (t["tariff"], "tax", "logistics:duty", "Import tax / customs (whole batch)"),
        (t.get("service_charge", 0.0), "other", "", "Payment service charge"),
        (-t["discount"], "other", "other:discount", "Supplier discount"),
    ):
        if amount:
            lines.append({
                "kind": kind, "plan_key": step, "allocate": "none", "run_id": None,
                "label": label, "qty": 1, "unit_price": round(amount, 4),
                "external_line_id": f"header:{step or kind}", "notes": "",
                "children": [],
            })

    explained = round(sum(li["unit_price"] for li in lines), 2)
    total = t["total"]
    residual = round(total - explained, 2)
    if abs(residual) > 0.01:
        # Never hide it: a residual is either a real charge we have not named or a
        # misread structure, and both must be visible rather than absorbed.
        lines.append({
            "kind": "other", "plan_key": "", "allocate": "none", "run_id": None,
            "label": "Unexplained document remainder",
            "qty": 1, "unit_price": residual,
            "external_line_id": "header:residual",
            "notes": (f"printed total ${total} minus ${explained} explained by "
                      "product lines + freight + tariff + service charge - discount"),
            "children": [],
        })

    return {
        "kind": "assembly",
        "external_id": inv["batch_num"],
        "doc_number": inv["invoice_no"],
        "doc_date": inv["invoice_date"],
        "currency": inv["currency"],
        "settle_rate": inv["settle_rate"],
        "total_amount": total,
        "lines": lines,
        "explained_usd": explained,
        "residual_usd": residual,
        "reconciles": abs(residual) <= 0.01,
    }


# ------------------------------------------------------------ run proposal
# A run's recorded quantity is GOOD units; JLC's device count is units BUILT.
# Some of a batch fails test, so built >= good, and a match must tolerate that
# in one direction only. 12% is generous for electronics assembly; a bigger gap
# means it is a different batch, not a bad yield.
YIELD_TOL = 0.12


def propose_run_from_devices(devices: int, candidates: list[M.ProductionRun],
                             as_of=None) -> dict:
    """Match a run when the device count is KNOWN from JLC's panelisation.

    Stronger than BOM voting and available for every order — including those
    whose parts are not in the library and runs with no snapshot BOM. The BOM
    vote is kept as a cross-check, not as the primary signal.

    Quantity is compared asymmetrically on purpose: `ProductionRun.qty` records
    GOOD units while JLC reports units BUILT, so built-slightly-more is a normal
    yield loss (1000 built -> 945 good) while built-fewer-than-good is
    impossible and must not match.
    """
    scored = []
    for run in candidates:
        rq = run.qty or run.plan_qty or 0
        if not rq:
            continue
        gap = _date_gap(as_of, run.run_date)
        exact = devices == rq
        loss = (devices - rq) / devices if devices else 1.0
        plausible = exact or (0 <= loss <= YIELD_TOL)
        if not plausible:
            continue
        scored.append({
            "run_id": run.id, "run_label": run.label, "run_qty": rq,
            "implied_devices": devices, "qty_delta": devices - rq,
            "exact": exact, "yield_loss": round(loss, 4),
            "date_gap_days": gap, "qty_matches": True,
            "panel_factor": None, "agree": 0, "voted": 0, "share": 1.0,
            "mean_frac": None,
        })
    if not scored:
        return {"run_id": None, "confidence": "no_run_matches",
                "reason": f"JLC says {devices} devices; no run has a matching quantity",
                "candidates": []}

    # Exact quantity first, then nearest in time. Date is decisive between two
    # batches of the same size — two orders four months apart both derived 600
    # devices and both matched the only 600-piece batch.
    scored.sort(key=lambda s: (
        not s["exact"],
        s["date_gap_days"] if s["date_gap_days"] is not None else 10_000,
        s["yield_loss"],
    ))
    best = scored[0]
    near = best["date_gap_days"] is None or best["date_gap_days"] <= MAX_DATE_GAP_DAYS
    tied = [s for s in scored
            if s["exact"] == best["exact"]
            and s["date_gap_days"] == best["date_gap_days"]]
    if len(tied) > 1:
        conf = "ambiguous"
    elif near:
        conf = "high"
    else:
        conf = "date_conflict"
    return {
        "run_id": best["run_id"] if conf == "high" else None,
        "confidence": conf,
        "reason": (
            f"JLC states {devices} devices; run {best['run_id']} recorded "
            f"{best['run_qty']}"
            + ("" if best["exact"] else
               f" ({best['qty_delta']:+d}, {best['yield_loss'] * 100:.1f}% yield loss)")
            + (f", {best['date_gap_days']}d apart" if best["date_gap_days"] is not None else "")
            + ("" if near else " — TOO FAR APART to be the same batch")
        ),
        "candidates": scored[:5],
    }


def propose_run(db: Session, order: dict, consumption: list[dict],
                candidates: list[M.ProductionRun], as_of=None) -> dict:
    """Derive the panel factor and the run together.

    For each candidate run, every consumed part votes
    `consumed_qty / (jlc_number x bom_qty_per_device)`. The right run makes the
    votes agree on one integer; a wrong one scatters them. This is strictly
    stronger than comparing quantities, because a wrong run may coincidentally
    share a quantity but cannot coincidentally make N parts agree.
    """
    number = order.get("qty") or 0
    if number <= 0 or not consumption:
        return {"run_id": None, "panel_factor": None, "confidence": "none",
                "reason": "no assembly quantity or no consumption to test against",
                "candidates": []}

    consumed: dict[str, float] = {}
    for c in consumption:
        if c["lcsc"]:
            consumed[c["lcsc"]] = consumed.get(c["lcsc"], 0.0) + c["qty"]

    scored = []
    for run in candidates:
        bom = _bom_per_device(db, run)
        if not bom:
            continue
        votes: Counter = Counter()
        fracs = []
        for lcsc, qty in consumed.items():
            per = bom.get(lcsc)
            if not per:
                continue
            k = qty / (number * per)
            if k <= 0:
                continue
            votes[round(k)] += 1
            fracs.append(min(k % 1, 1 - (k % 1)))
        if not votes:
            continue
        k, n = votes.most_common(1)[0]
        total = sum(votes.values())
        implied = int(number * k)
        scored.append({
            "run_id": run.id,
            "run_label": run.label,
            "run_qty": run.qty,
            "panel_factor": k,
            "agree": n,
            "voted": total,
            "share": round(n / total, 3),
            "mean_frac": round(sum(fracs) / len(fracs), 4) if fracs else None,
            "implied_devices": implied,
            # THE discriminator. The BOM votes derive k, but they CANNOT tell two
            # runs of the same design apart — every Dongle batch shares snapshot
            # 8, so all five score identically (19/19, k=4). Only the run's own
            # quantity distinguishes them, so it must be part of the ranking and
            # not a check applied after sorting.
            "qty_matches": bool(run.qty and abs(implied - run.qty) <= 1),
            "qty_delta": (implied - run.qty) if run.qty else None,
            # Quantity alone is not enough: two assembly orders four months
            # apart both derived 600 devices and both matched run 8 (the only
            # 600-piece batch), each seeing itself as a unique hit. Date is what
            # separates them, so it ranks alongside quantity rather than being
            # left to the reader.
            "date_gap_days": _date_gap(as_of, run.run_date),
        })

    if not scored:
        return {"run_id": None, "panel_factor": None, "confidence": "none",
                "reason": "no candidate run has a snapshot BOM to compare against",
                "candidates": []}

    # Rank: quantity agreement first, then DATE proximity, then unanimity, then
    # tightness. Date has to be in the key — without it two orders months apart
    # both proposing the same batch each look like a unique match.
    scored.sort(key=lambda s: (
        not s["qty_matches"],
        s["date_gap_days"] if s["date_gap_days"] is not None else 10_000,
        -s["share"],
        s["mean_frac"] if s["mean_frac"] is not None else 9,
    ))
    best = scored[0]
    unanimous = best["share"] >= PANEL_VOTE_SHARE
    tight = (best["mean_frac"] is not None and best["mean_frac"] <= PANEL_FRAC_TOL)

    # Ambiguity must be detected, not sorted away: if several runs match on
    # quantity too, no proposal is safe.
    qty_hits = [s for s in scored if s["qty_matches"]]
    if len(qty_hits) > 1:
        return {
            "run_id": None, "panel_factor": best["panel_factor"],
            "confidence": "ambiguous",
            "reason": (
                f"{len(qty_hits)} runs are consistent with {best['implied_devices']} devices "
                f"({', '.join(str(s['run_id']) for s in qty_hits)}) — a human must choose"
            ),
            "candidates": scored[:5],
        }

    # A batch is assembled within weeks of its invoice. A gap of many months
    # means the quantity match is a coincidence, so it cannot be "high".
    near_in_time = best["date_gap_days"] is None or best["date_gap_days"] <= MAX_DATE_GAP_DAYS

    if unanimous and tight and best["qty_matches"] and near_in_time:
        conf = "high"
    elif unanimous and tight and best["qty_matches"]:
        conf = "date_conflict"
    elif unanimous and tight:
        # The BOM agrees but NO run has a matching quantity. That is a real
        # signal, not a near miss: the batch may be split across several
        # assembly orders, or the run's quantity may be wrong.
        conf = "low"
    else:
        conf = "low"
    return {
        # Only a HIGH-confidence proposal names a run. The panel factor is
        # reported regardless, because it is derived from the BOM and is useful
        # even when the run is unknown.
        "run_id": best["run_id"] if conf == "high" else None,
        "panel_factor": best["panel_factor"],
        "confidence": conf,
        "reason": (
            f"{best['agree']}/{best['voted']} parts agree on k={best['panel_factor']} "
            f"(mean fractional {best['mean_frac']}), implying {best['implied_devices']} devices "
            f"vs run qty {best['run_qty']}"
            + ("" if best["qty_matches"] else " — NO run quantity matches")
        ),
        "candidates": scored[:5],
    }


# What the importer intends to do with one assembly order.
OUTCOME_LINK = "link_run"        # charge it to a production run
OUTCOME_EXTERNAL = "external"    # a project outside the platform: stock only, no owner
OUTCOME_HUMAN = "needs_human"    # a real signal exists but is not conclusive


def plan_orders(db: Session, invoices: list[dict],
                runs: list[M.ProductionRun] | None = None) -> list[dict]:
    """Decide every assembly order TOGETHER, because some conclusions are only
    visible across orders.

    A per-order proposal cannot see that two different orders both claim the same
    run: each is a unique quantity match in isolation. Real case — run 8 (the only
    600-piece batch) was claimed by `SMT025031861942` (Mar 2025) and
    `SMT025072962223` (Jul 2025), four months apart. So collisions are resolved
    here: the nearest in time keeps the run, every rival is demoted to a human
    decision rather than silently losing.

    Orders with no plausible run default to OUTCOME_EXTERNAL — JLC also built
    projects that never existed in this platform, and forcing those onto a run
    would fabricate costs. Their consumption still moves stock (see
    `external_stock_movements`), it just has no owner.
    """
    if runs is None:
        runs = db.query(M.ProductionRun).all()

    # Panelisation JLC STATES, cached at sync time from `selectPersonOrder`.
    panels: dict[str, dict] = {}
    for row in db.query(M.JlcImport).filter_by(kind="assembly").all():
        for code, info in (row.panel_info or {}).items():
            panels[code] = info

    planned: list[dict] = []
    for inv in invoices:
        for order in inv.get("assembly_orders") or []:
            code = order.get("smt_order_code") or ""
            stated = panels.get(code) or {}
            devices = stated.get("devices")
            as_of = inv.get("invoice_date")
            bom_prop = propose_run(db, order, order.get("consumption") or [], runs,
                                   as_of=as_of)
            if devices:
                # JLC's own panelisation wins: it is stated rather than inferred,
                # and it is known for every order. The BOM vote is demoted to a
                # CROSS-CHECK — when both produce a factor and they disagree, the
                # run link is suspect and a human should look.
                prop = propose_run_from_devices(devices, runs, as_of=as_of)
                prop["panel_factor"] = stated.get("panel_factor")
                prop["panel_source"] = stated.get("source") or "jlc_panelisation"
                prop["bom_vote"] = {
                    "panel_factor": bom_prop.get("panel_factor"),
                    "confidence": bom_prop.get("confidence"),
                    "run_id": bom_prop.get("run_id"),
                }
                bk = bom_prop.get("panel_factor")
                if bk and stated.get("panel_factor") and bk != stated["panel_factor"]:
                    prop["confidence"] = "factor_conflict"
                    prop["run_id"] = None
                    prop["reason"] = (
                        f"JLC states a {stated['panel_factor']}-up panel but the BOM implies "
                        f"{bk} — one of them is wrong, so the run link cannot be trusted"
                    )
            else:
                prop = bom_prop
                prop["panel_source"] = "bom_vote"
            planned.append({
                "batch_num": inv.get("batch_num"),
                "invoice_no": inv.get("invoice_no"),
                "invoice_date": inv.get("invoice_date"),
                "smt_order_code": order.get("smt_order_code"),
                "board_codes": order.get("board_codes") or [],
                "jlc_number": order.get("qty"),
                "money_usd": order.get("money"),
                "presale_usd": order.get("presale"),
                "consumption": order.get("consumption") or [],
                "lot_count": order.get("lot_count"),
                "proposal": prop,
            })

    # --- cross-order pass: several orders may JOINTLY build one run
    #
    # Confirmed by the user 2026-07-28: Aqua Batch 1 (315 good) was assembled as
    # 125 in June plus 200 in July 2024 — 325 built. An earlier version treated
    # the second order as a collision and demoted it, which was simply wrong
    # about how production works.
    #
    # So a second claimant is only a problem when the orders TOGETHER overshoot
    # the run, and it is worth reporting when they undershoot (an order is
    # probably missing). Matching a run exactly, or overshooting within the
    # yield tolerance, is the normal healthy case.
    claims: dict[int, list[dict]] = {}
    for p in planned:
        rid = p["proposal"].get("run_id")
        if rid:
            claims.setdefault(rid, []).append(p)

    for rid, group in claims.items():
        if len(group) < 2:
            continue
        run = next((r for r in runs if r.id == rid), None)
        recorded = (run.qty or run.plan_qty or 0) if run else 0
        total = sum(_devices_of(p) for p in group)
        codes = ", ".join(p["smt_order_code"] for p in group)
        loss = (total - recorded) / total if total else 1.0
        if recorded and 0 <= loss <= YIELD_TOL:
            # They add up: the batch was genuinely built across several orders.
            # Keep every one linked and show the arithmetic.
            for p in group:
                p["proposal"]["collision_note"] = (
                    f"built jointly with {len(group) - 1} other order(s) — {codes} "
                    f"= {total} devices against {recorded} recorded "
                    f"({loss * 100:.1f}% yield loss)"
                )
            continue

        # They do not add up. Do NOT withdraw every proposal: each of these
        # matched this run on its own, and one of them is probably right while
        # the others belong to a LARGER batch they only partly fill — a 200-piece
        # order is a partial fill of a 315-piece run, which a per-order match
        # cannot see. Optimal assignment here is a subset-sum problem and is not
        # worth solving: keep the nearest in time, flag the rest with the
        # arithmetic, and let the operator place them.
        group.sort(key=lambda p: (
            p["proposal"]["candidates"][0]["date_gap_days"]
            if p["proposal"].get("candidates")
            and p["proposal"]["candidates"][0]["date_gap_days"] is not None
            else 10_000
        ))
        keeper, others = group[0], group[1:]
        keeper["proposal"]["collision_note"] = (
            f"also matched by {', '.join(p['smt_order_code'] for p in others)}; kept as "
            f"the nearest in time. Together they are {total} devices against {recorded} "
            f"recorded, so the others likely belong to a different batch."
        )
        for p in others:
            gap = (p["proposal"]["candidates"][0]["date_gap_days"]
                   if p["proposal"].get("candidates") else None)
            p["proposal"]["run_id"] = None
            p["proposal"]["confidence"] = "partial_fill"
            p["proposal"]["collision_note"] = (
                f"matches run {rid} on quantity, but {keeper['smt_order_code']} is nearer "
                f"({gap}d vs its own) and together they would be {total} devices against "
                f"{recorded} recorded. This order is probably PART of a larger batch — "
                "pick the run it belongs to, or book it as external."
            )

    for p in planned:
        p["outcome"] = _outcome_for(p)
    return planned


def _devices_of(p: dict) -> int:
    """Device count for an order, preferring JLC's stated panelisation."""
    prop = p.get("proposal") or {}
    for c in (prop.get("candidates") or []):
        if c.get("implied_devices"):
            return int(c["implied_devices"])
    k = prop.get("panel_factor")
    return int((p.get("jlc_number") or 0) * k) if k else 0


def _outcome_for(p: dict) -> str:
    """Default intent. Deliberately conservative: only HIGH confidence links a
    run, and anything with no usable signal is proposed as external rather than
    parked forever — but every one of these is a PROPOSAL a human confirms."""
    conf = p["proposal"].get("confidence")
    if conf == "high" and p["proposal"].get("run_id"):
        return OUTCOME_LINK
    # No consumption at all means nothing was drawn from our stock: JLC supplied
    # every part from their own. There is nothing to attribute and no stock to
    # move, so it is external by definition.
    if conf == "none":
        return OUTCOME_EXTERNAL
    return OUTCOME_HUMAN


def staged_invoices(db: Session) -> list[dict]:
    """Every staged assembly payload, parsed. One place, because a payload without
    `invoiceNo` is a fetch that failed and must not reach a planner."""
    out = []
    for row in db.query(M.JlcImport).filter_by(kind="assembly").all():
        if row.payload and "invoiceNo" in row.payload:
            out.append(jlc_invoice.parse(row.payload))
    return out


def lots_by_key(db: Session) -> dict[str, dict]:
    """`lot_ref` -> what that lot cost, read from the platform's OWN purchase lines.

    `external_stock_movements` needs a per-lot unit cost so value leaves the pool at
    what was actually paid rather than at the running average. Sourcing it from the
    imported lines instead of re-fetching JLC means booking an external order needs
    no live session — and uses the figure the ledger actually holds, so the pool
    identity closes by construction.
    """
    rows = (db.query(M.RunCostLine)
            .filter(M.RunCostLine.lot_ref != "",
                    M.RunCostLine.kind == "part",
                    M.RunCostLine.voided_at.is_(None))
            .order_by(M.RunCostLine.id).all())
    return {li.lot_ref: {"unit_cost_usd": li.unit_price, "line_id": li.id,
                         "qty": li.qty} for li in rows}


def order_plan_for(db: Session, code: str) -> dict | None:
    """The cross-order plan entry for ONE assembly order.

    Deliberately routed through the full `plan_orders` pass rather than planning
    the single order in isolation: collision detection only exists across orders.
    Run 8 was claimed by two orders in different batches four months apart, and
    each looked like a clean unique match on its own.
    """
    invoices = staged_invoices(db)
    if not invoices:
        return None
    for p in plan_orders(db, invoices):
        if p["smt_order_code"] == code:
            return p
    return None


def external_stock_movements(order_plan: dict, lots: dict[str, dict]) -> list[dict]:
    """Stock movements for an order charged to NOBODY.

    Negative `ComponentStockAdjustment` rows with `charge_run_id` NULL: the stock
    and its value leave the pool, no run is charged, and both register identities
    still close (the invoice-allocation identity never saw a stock event; the pool
    identity counts adjustments as a first-class leg).

    `reason='external_project'` is load-bearing — a bare negative adjustment reads
    as attrition, and attrition is a defect signal in this codebase. Consumption
    by another project is not loss, and conflating them would inflate the apparent
    attrition rate while hiding real losses.

    `unit_cost_usd` is set explicitly from the lot so the value leaves at what was
    actually paid; `pool_state` would otherwise fall back to the running average.
    """
    out = []
    for c in order_plan.get("consumption") or []:
        lot = lots.get(c.get("lot_key") or "")
        unit = lot["unit_cost_usd"] if lot and lot.get("unit_cost_usd") is not None else None
        out.append({
            "lcsc": c["lcsc"],
            "mpn": c["mpn"],
            "qty_delta": -abs(c["qty"]),
            "unit_cost_usd": unit,
            "reason": "external_project",
            "charge_run_id": None,
            # Idempotency as a CONSTRAINT (`uq_stock_adj_import`) rather than the
            # `note LIKE '%code%'` text scan this used to rely on.
            "import_ref": (f"jlc:ext:{order_plan['smt_order_code']}:"
                           f"{c['lcsc'] or c['mpn']}")[:120],
            "adjusted_at": (order_plan["invoice_date"].isoformat()
                            if order_plan.get("invoice_date") else ""),
            "note": (
                f"consumed by JLC assembly order {order_plan['smt_order_code']} "
                f"(batch {order_plan['batch_num']}), which builds a project not tracked "
                f"in this platform — stock only, charged to no run"
                + (f"; lot {c['lot_key']}" if c.get("lot_key") else "")
            ),
        })
    return out


# --------------------------------------------------------- staging + queue
def sync_stage(db: Session, limit_pages: int = 4) -> dict:
    """Fetch order batches and their invoices into `jlc_imports`. No money moves.

    Deliberately fetch-and-stage only. Auto-applying on sync would mean a scrape
    could write to the ledger unattended, and JLC's API is undocumented and
    unversioned — a shape change must surface as a staged payload a human looks
    at, not as a silent document.

    Guards against the silent-empty failure mode: a broken read returns zero
    batches, which is byte-identical to "nothing new". So the visible batch count
    is compared against the highest previously seen, and a DROP is reported as an
    error rather than treated as an empty queue.
    """
    from . import jlc_web  # local: jlc_web reads the session table, this does not

    seen: dict[str, dict] = {}
    for page in range(1, limit_pages + 1):
        data = jlc_web.list_order_batches(db, page=page, page_size=25)
        rows = data.get("list") or []
        if not rows:
            break
        for b in rows:
            bn = str(b.get("batchNum") or "")
            if bn:
                seen[bn] = b

    prior = db.query(M.JlcImport).filter_by(kind="assembly").count()
    if prior and len(seen) < prior:
        return {"error": (f"JLC reported {len(seen)} batches but {prior} were already "
                          "staged — refusing to treat a shrinking list as 'nothing new'. "
                          "Check the session."),
                "batches_visible": len(seen), "previously_staged": prior}

    fetched = refreshed = failed = 0
    for bn in sorted(seen):
        row = db.query(M.JlcImport).filter_by(kind="assembly", external_id=bn).first()
        if row is not None and row.payload:
            refreshed += 1
            continue
        try:
            raw = jlc_web.get_manufacturing_invoice(db, bn)
        except jlc_web.JlcWebError as e:
            log.warning(f"could not fetch invoice for {bn}: {e}")
            failed += 1
            continue
        parsed = jlc_invoice.parse(raw) if raw.get("invoiceNo") else None
        if row is None:
            row = M.JlcImport(kind="assembly", external_id=bn)
            db.add(row)
        row.payload = raw
        row.invoice_no = (parsed or {}).get("invoice_no") or ""
        row.doc_date = (parsed["invoice_date"].isoformat()
                        if parsed and parsed.get("invoice_date") else "")
        row.total_amount = (parsed or {}).get("totals", {}).get("total")
        row.presale_amount = (parsed or {}).get("totals", {}).get("presale")
        # Panelisation lives on a DIFFERENT endpoint and is the only
        # authoritative device count, so it is fetched and cached alongside.
        try:
            row.panel_info = jlc_web.panel_factors(jlc_web.get_person_order(db, bn))
        except jlc_web.JlcWebError as e:
            log.warning(f"no panelisation for {bn}: {e}")
        row.fetched_at = M.utcnow()
        fetched += 1
    db.commit()
    return {"batches_visible": len(seen), "fetched": fetched,
            "already_staged": refreshed, "failed": failed}


def decision_queue(db: Session) -> list[dict]:
    """Every assembly order with the evidence a human needs to decide it.

    Includes the per-device breakdown deliberately: "11 caps and 1 ESP32 per
    dongle" is verifiable at a glance in a way that "confidence: high" is not, and
    the panel factor is a derived conclusion that deserves to be checkable rather
    than trusted.
    """
    staged = db.query(M.JlcImport).filter_by(kind="assembly").all()
    invoices = []
    for row in staged:
        if not row.payload or "invoiceNo" not in row.payload:
            continue
        invoices.append(jlc_invoice.parse(row.payload))
    if not invoices:
        return []

    runs = db.query(M.ProductionRun).all()
    run_names = {r.id: f"{r.label}" for r in runs}
    decided = {d.smt_order_code: d for d in db.query(M.JlcOrderDecision).all()}
    planned = plan_orders(db, invoices, runs)
    panels: dict[str, dict] = {}
    for row in staged:
        for code, info in (row.panel_info or {}).items():
            panels[code] = info

    out = []
    for p in planned:
        code = p["smt_order_code"]
        prop = p["proposal"]
        cons = p["consumption"]
        existing = decided.get(code)
        k = prop.get("panel_factor")
        stated = panels.get(code) or {}
        # Prefer JLC's own device count. It is derived from `pasteNumber` (what
        # went through the assembly line), which is NOT the invoice's `number`
        # (what was billed) — a real invoice bills 45 boards against 50 pasted,
        # and 187 against 200. Computing devices from the invoice number would
        # therefore show a figure that contradicts the proposal's own reasoning.
        devices = stated.get("devices")
        if devices is None and k:
            devices = int((p["jlc_number"] or 0) * k)
        out.append({
            "smt_order_code": code,
            "batch_num": p["batch_num"],
            "invoice_no": p["invoice_no"],
            "invoice_date": p["invoice_date"].isoformat() if p["invoice_date"] else "",
            "board_codes": p["board_codes"],
            "jlc_number": p["jlc_number"],
            "panel_factor": k,
            "implied_devices": devices,
            "panels_assembled": stated.get("panels"),
            "panel_source": prop.get("panel_source", ""),
            "bom_vote": prop.get("bom_vote"),
            "money_usd": p["money_usd"],
            "presale_usd": p["presale_usd"],
            "consumed_value_usd": round(sum(c["money"] for c in cons), 2),
            "lot_count": p["lot_count"],
            "part_count": len({c["lcsc"] for c in cons if c["lcsc"]}),
            "proposed_outcome": p["outcome"],
            "confidence": prop["confidence"],
            "proposed_run_id": prop.get("run_id"),
            "proposed_run_label": run_names.get(prop.get("run_id") or -1, ""),
            "reason": prop.get("reason", ""),
            "collision_note": prop.get("collision_note", ""),
            "candidates": [
                {**c, "run_label": run_names.get(c["run_id"], "")}
                for c in (prop.get("candidates") or [])
            ],
            "per_device": _per_device_preview(cons, devices),
            "decision": ({
                "outcome": existing.outcome, "run_id": existing.run_id,
                "panel_factor": existing.panel_factor,
                "decided_by": existing.decided_by, "note": existing.note,
                "applied_at": existing.applied_at.isoformat() if existing.applied_at else None,
            } if existing else None),
        })
    return out


def _per_device_preview(consumption: list[dict], devices: int | None,
                        top: int = 8) -> list[dict]:
    """The biggest consumed parts expressed per device — the sanity check a human
    can actually perform. Without a device count the raw totals are shown."""
    by: dict[str, dict] = {}
    for c in consumption:
        key = c["lcsc"] or c["mpn"]
        e = by.setdefault(key, {"lcsc": c["lcsc"], "mpn": c["mpn"], "qty": 0.0, "money": 0.0})
        e["qty"] += c["qty"]
        e["money"] += c["money"]
    rows = sorted(by.values(), key=lambda e: -e["money"])[:top]
    for e in rows:
        e["qty"] = round(e["qty"], 2)
        e["money"] = round(e["money"], 2)
        e["per_device"] = round(e["qty"] / devices, 3) if devices else None
    return rows


def _as_date(v) -> date | None:
    """Coerce whatever a date-ish field holds into a `date`.

    Necessary because `ProductionRun.run_date` and `RunCostDocument.doc_date` are
    `String(20)` ISO TEXT, not date columns — subtracting a real `date` from them
    raises TypeError, which is how the date gap silently read as unknown
    everywhere and why the amount+date match tier would have thrown the first
    time it was reached.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _date_gap(as_of, run_date) -> int | None:
    """Days between the invoice and the run. None when either is unknown, which
    must NOT be read as 'close' — the ranking sends unknowns to the back."""
    a, b = _as_date(as_of), _as_date(run_date)
    if a is None or b is None:
        return None
    return abs((a - b).days)


def _bom_per_device(db: Session, run: M.ProductionRun) -> dict[str, float]:
    """Per-device quantity by LCSC from the run's snapshot BOM. Excludes DNP and
    BOM-excluded lines, and the base variant only — the same filters the plan
    itself uses, or the votes compare different populations."""
    if not run.snapshot_id:
        return {}
    rows = (
        db.query(M.SnapshotBomLine)
        .filter(
            M.SnapshotBomLine.snapshot_id == run.snapshot_id,
            M.SnapshotBomLine.variant == "",
            M.SnapshotBomLine.lcsc != "",
            M.SnapshotBomLine.dnp.is_(False),
            M.SnapshotBomLine.exclude_from_bom.is_(False),
        )
        .all()
    )
    out: dict[str, float] = {}
    for r in rows:
        out[r.lcsc] = out.get(r.lcsc, 0.0) + (r.qty or 0)
    return out


# --------------------------------------------------------- document match
def match_document(db: Session, external_id: str, doc_number: str,
                   total: float, doc_date) -> dict:
    """Three tiers, each requiring a UNIQUE hit.

    Tier order matters: `external_id` is empty on 7 of the 27 existing JLCPCB
    documents, lowercase on one and typo'd on another, so it cannot stand alone —
    but `doc_number` already holds JLC's own `invoiceNo` on all 27 and matched
    the API to the cent, which makes it the reliable key.
    """
    docs = db.query(M.RunCostDocument).filter(M.RunCostDocument.supplier == SUPPLIER).all()

    hits = [d for d in docs if (d.external_id or "").lower() == external_id.lower()
            and external_id]
    if len(hits) == 1:
        return {"tier": "external_id", "document_id": hits[0].id}
    if len(hits) > 1:
        return {"tier": "ambiguous", "document_id": None,
                "note": f"{len(hits)} documents share external_id {external_id}"}

    hits = [d for d in docs if doc_number and (d.doc_number or "") == doc_number]
    if len(hits) == 1:
        return {"tier": "doc_number", "document_id": hits[0].id}
    if len(hits) > 1:
        return {"tier": "ambiguous", "document_id": None,
                "note": f"{len(hits)} documents share doc_number {doc_number}"}

    want = _as_date(doc_date)
    if want is not None:
        hits = []
        for d in docs:
            if abs((d.total_amount or 0) - total) > AMOUNT_EPS:
                continue
            got = _as_date(d.doc_date)
            if got is not None and abs((got - want).days) <= DATE_DAYS:
                hits.append(d)
        if len(hits) == 1:
            return {"tier": "amount_date", "document_id": hits[0].id}
        if len(hits) > 1:
            return {"tier": "ambiguous", "document_id": None,
                    "note": f"{len(hits)} documents match on amount+date"}
    return {"tier": "none", "document_id": None}


def document_blockers(db: Session, document_id: int) -> list[str]:
    """Why an existing document cannot simply be overwritten. Hand work is
    richer than the vendor's decomposition, so it is kept and enriched, never
    regenerated."""
    lines = (
        db.query(M.RunCostLine)
        .filter(M.RunCostLine.document_id == document_id,
                M.RunCostLine.voided_at.is_(None))
        .all()
    )
    out = []
    children = [ln for ln in lines if ln.parent_line_id is not None]
    allocated = [ln for ln in lines if ln.run_id is not None or ln.project_id is not None]
    if children:
        out.append(f"{len(children)} split children")
    if allocated:
        out.append(f"{len(allocated)} lines allocated to a run or project")
    return out
