"""Parts the SUPPLIER supplied: itemising the lump, and checking the coverage.

An assembly invoice bills one figure for the components the factory sourced
itself (`materialMoney`, "Components sourced by JLC"). That lump is a small BOM,
and until it is itemised the platform cannot say WHICH parts it bought, cannot
meet a BOM position with it, and cannot tell a part that was supplied from one
that was forgotten.

Three facts about JLC's per-part BOM, measured across all 46 cached orders on
2026-09-19 rather than assumed. They are why this module keys on what it does:

1. **`extPrice == unitPrice * shopStock`, in 1021 of 1021 priced rows.** The
   money is billed on the SHOP portion only. Nothing is billed for the portion
   that came out of your own consigned stock.
2. **`componentSource` has THREE values, not two.** `shop`, `preSale`, and
   `preSaleAndShop` — a position JLC part-filled from your stock and topped up
   from its own. On SMT026090162303 the mixed rows are 1796.16 of a 2097.28
   lump, so treating the lump as "shop only" misses most of it.
   `presaleStock` / `shopStock` split such a position exactly.
3. **`componentNum` is NOT a piece count.** It is per PANEL, so a 1-per-board
   part on a 200-panel order reads 200 while `componentRealCount` reads 800.
   Never derive quantities from it — the same trap as JLC's order quantity,
   which is panels whenever the order was panelised.

What is NOT settled, and is reported rather than guessed: on 103 rows across 8
orders `presaleStock + shopStock` does not equal `componentRealCount`, and
`freeStock` does not close the gap. Those rows are flagged `supplier_mismatch`.
The money is unaffected — rule 1 holds on every one of them — so only their
coverage is in doubt.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from .. import models as M
from . import run_actuals

#: JLC's own word for who supplied a position, and what it means for us.
SOURCE_SUPPLIER = "shop"
SOURCE_POOL = "preSale"
SOURCE_BOTH = "preSaleAndShop"
PAID_SOURCES = (SOURCE_SUPPLIER, SOURCE_BOTH)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def bom_for_order(db: Session, smt_order_code: str) -> list[dict] | None:
    """JLC's cached BOM for one assembly order, or None when it was never
    fetched. `fetch-bom` is the only thing that writes it."""
    for row in db.query(M.JlcImport).filter(M.JlcImport.bom_info.isnot(None)).all():
        if smt_order_code in (row.bom_info or {}):
            return row.bom_info[smt_order_code]
    return None


def supplier_lines_from_bom(bom: list[dict]) -> list[dict]:
    """The lump's per-part breakdown: one entry per position the supplier
    charged for, priced exactly as the supplier priced it.

    A `preSale` position is absent, not zero: nothing was billed for it, so a
    zero-value child would only add noise to the document.
    """
    out: list[dict] = []
    for b in bom:
        src = str(b.get("componentSource") or "")
        if src not in PAID_SOURCES:
            continue
        shop = _f(b.get("shopStock"))
        unit = _f(b.get("unitPrice"))
        ext = _f(b.get("extPrice"))
        real = _f(b.get("componentRealCount"))
        pre = _f(b.get("presaleStock"))
        out.append({
            "lcsc": str(b.get("componentCode") or "").strip(),
            "mpn": str(b.get("componentModelEn") or b.get("componentModel") or "").strip(),
            "designator": str(b.get("designator") or "").strip(),
            "source": src,
            # What the supplier BILLED, and what the run therefore pays for.
            "qty_supplied": shop,
            "unit_price": unit,
            "amount": ext,
            # The rest of the position, which our own pool has to cover.
            "qty_from_pool": pre,
            "qty_total": real,
            "loss": _f(b.get("lossNumber")),
            # JLC's own numbers do not always add up; say so instead of
            # silently trusting one of them over the other.
            "supplier_mismatch": abs(pre + shop - real) >= 0.5,
            # Verified on every priced row in the account; a break means JLC
            # changed how it bills and the itemisation must be re-read.
            "price_checks": unit == 0 or abs(ext - unit * shop) < 0.005,
        })
    return out


def itemise(db: Session, line: M.RunCostLine) -> dict:
    """Plan the split of ONE supplier-parts lump into per-part children.

    Returns the plan and never writes: the caller applies it through the normal
    split path, so a hand-typed itemisation and a supplier-read one produce the
    same rows and obey the same guards.
    """
    ref = str(line.external_line_id or "")
    code = ref.split(":", 1)[0] if ":" in ref else ""
    if not code:
        return {"ok": False, "reason": "this line carries no supplier order reference, "
                                       "so its breakdown has to be entered by hand",
                "children": []}
    bom = bom_for_order(db, code)
    if bom is None:
        return {"ok": False, "smt_order_code": code,
                "reason": f"JLC's own BOM for {code} has not been fetched — "
                          f"POST /api/jlc/import/orders/{code}/fetch-bom first",
                "children": []}
    parts = supplier_lines_from_bom(bom)
    printed = round(run_actuals.effective_qty(line, None, db) * (line.unit_price or 0), 4)
    over = round(sum(p["amount"] for p in parts) - printed, 4)
    if 0 < over < 0.01:
        # JLC bills the lump rounded to the cent while each part keeps
        # `unitPrice * shopStock` to four decimals: SMT026090162303's parts sum
        # to 2097.2801 against 2097.28 billed. A signed share closes it, because
        # the split refuses children over their parent by any amount.
        parts.append({"lcsc": "", "mpn": "", "designator": "", "source": "rounding",
                      "qty_supplied": 1.0, "unit_price": -over, "amount": -over,
                      "qty_from_pool": 0.0, "qty_total": 0.0, "loss": 0.0,
                      "supplier_mismatch": False, "price_checks": True})
    total = round(sum(p["amount"] for p in parts), 4)
    return {
        "ok": bool(parts),
        "smt_order_code": code,
        "children": parts,
        "parts_total": total,
        "printed_total": printed,
        # Under-allocation is legal and surfaces as a residual; OVER is always a
        # mistake and the split endpoint refuses it.
        "residual": round(printed - total, 4),
        "reconciles": abs(printed - total) < 0.005,
        "mismatched_rows": [p["lcsc"] for p in parts if p["supplier_mismatch"]],
        "price_check_failed": [p["lcsc"] for p in parts if not p["price_checks"]],
    }


def batch_supply(db: Session, run: M.ProductionRun) -> list[dict]:
    """Parts this batch bought DIRECTLY, outside the shared pool.

    A `part` cost line carrying this run's id: the components the factory
    sourced itself, and anything else bought for one batch. They never enter the
    pool, so no draw reports them and the Materials tab — built from the BOM,
    the draws, the write-offs and the substitutions — could not see them at all.
    A position met this way showed an empty Used column while the batch was
    paying for it (user report 2026-09-19).

    Grouped by identity, because one position can be billed on several lines.
    """
    rows = (db.query(M.RunCostLine)
            .filter(run_actuals.IS_STOCK,
                    M.RunCostLine.run_id == run.id,
                    M.RunCostLine.voided_at.is_(None),
                    M.RunCostLine.allocate != run_actuals.EXCLUDED)
            .all())
    hdrs = run_actuals.header_ids(db)
    out: dict[str, dict] = {}
    for li in rows:
        if li.id in hdrs:          # a header is worth zero; its children carry it
            continue
        doc = db.get(M.RunCostDocument, li.document_id)
        key = (li.lcsc or "").strip().upper() or f"c{li.component_id}" \
            or run_actuals._strip(li.mpn or "") or f"line{li.id}"
        e = out.setdefault(key, {
            "key": key, "lcsc": (li.lcsc or "").strip(), "mpn": li.mpn or "",
            "component_id": li.component_id, "qty": 0.0, "amount": 0.0,
            "amount_usd": 0.0, "currency": (doc.currency if doc else "USD"),
            "suppliers": set(), "lines": [],
        })
        amount = (li.qty or 0.0) * (li.unit_price or 0.0)
        e["qty"] += li.qty or 0.0
        e["amount"] += amount
        # `fx_rate_usd` is pinned on the document at entry, so a historical
        # figure can never drift; 1.0 for a USD document.
        e["amount_usd"] += amount * float((doc.fx_rate_usd if doc else None) or 1.0)
        if doc and doc.supplier:
            e["suppliers"].add(doc.supplier)
        e["lines"].append(li.id)
        if e["component_id"] is None and li.component_id:
            e["component_id"] = li.component_id
    return [{**e, "suppliers": sorted(e["suppliers"]),
             "unit_usd": (e["amount_usd"] / e["qty"]) if e["qty"] else None}
            for e in sorted(out.values(), key=lambda x: x["mpn"] or x["lcsc"])]


def coverage(db: Session, run: M.ProductionRun) -> dict:
    """Is every part this batch used accounted for exactly once?

    Two ways a position can be satisfied, and the supplier states which:

    * out of OUR pool — there must be a `component_consumptions` draw;
    * out of the SUPPLIER's stock — it is inside the assembly fee, and there
      must be NO draw, or the run pays twice.

    The supplier's own BOM is the expectation, per decision 0037: correct our
    books from what the supplier says, not from a figure we derived. A run whose
    orders have no cached BOM gets `known: false` rather than a made-up verdict.
    """
    codes = [d.smt_order_code for d in db.query(M.JlcOrderDecision)
             .filter(M.JlcOrderDecision.run_id == run.id,
                     M.JlcOrderDecision.outcome == "link_run").all()]
    expect: dict[str, dict] = {}
    missing_bom: list[str] = []
    for code in codes:
        bom = bom_for_order(db, code)
        if bom is None:
            missing_bom.append(code)
            continue
        for b in bom:
            key = str(b.get("componentCode") or "").strip().upper()
            if not key:
                continue
            e = expect.setdefault(key, {
                "lcsc": key, "mpn": str(b.get("componentModelEn") or "").strip(),
                "from_pool": 0.0, "from_supplier": 0.0, "total": 0.0,
                "sources": set(), "supplier_mismatch": False, "orders": [],
            })
            e["from_pool"] += _f(b.get("presaleStock"))
            e["from_supplier"] += _f(b.get("shopStock"))
            e["total"] += _f(b.get("componentRealCount"))
            e["sources"].add(str(b.get("componentSource") or ""))
            e["orders"].append(code)
            if abs(_f(b.get("presaleStock")) + _f(b.get("shopStock"))
                   - _f(b.get("componentRealCount"))) >= 0.5:
                e["supplier_mismatch"] = True

    # What the batch bought DIRECTLY. This half needs no supplier BOM, so it is
    # the only double-supply check that works on a hand-entered invoice — and a
    # hand-entered one is the case nothing else guards. A part paid for straight
    # AND drawn out of the pool is paid for twice, whoever typed it.
    bought: dict[str, dict] = {}
    for bs in batch_supply(db, run):
        key = (bs["lcsc"] or "").strip().upper()
        if key:
            bought[key] = bs

    drawn: dict[str, float] = defaultdict(float)
    for c in run_actuals.live_consumption(db, run_id=run.id).all():
        key = (c.lcsc or "").strip().upper()
        if key:
            drawn[key] += c.qty or 0.0

    rows = []
    for key, e in sorted(expect.items()):
        e["bought_for_batch"] = round((bought.get(key) or {}).get("qty", 0.0), 3)
        got = drawn.get(key, 0.0)
        want = e["from_pool"]
        if e["supplier_mismatch"]:
            verdict = "supplier_numbers_disagree"
        elif abs(got - want) < 0.5:
            verdict = "ok"
        elif want == 0 and got > 0:
            # The exact double-charge `void_shop_draws` was written to undo.
            verdict = "drawn_but_supplier_supplied"
        elif got == 0 and want > 0:
            verdict = "no_draw"
        else:
            verdict = "short" if got < want else "over_drawn"
        rows.append({**e, "sources": sorted(e["sources"]), "orders": sorted(set(e["orders"])),
                     "drawn": round(got, 3), "expected_from_pool": round(want, 3),
                     "delta": round(got - want, 3), "verdict": verdict})

    # A part the batch bought directly AND drew from the pool is paid for twice.
    # Checked against OUR OWN rows, so it holds for a hand-entered invoice on a
    # run with no supplier BOM at all — which is every run the supplier half
    # cannot see. Runs regardless of `known`.
    for key, bs in sorted(bought.items()):
        got = drawn.get(key, 0.0)
        if got <= 0:
            continue
        if key in expect:
            continue          # the supplier BOM already judged this one
        rows.append({
            "lcsc": key, "mpn": bs["mpn"], "sources": ["batch"], "orders": [],
            "from_pool": 0.0, "from_supplier": bs["qty"], "total": bs["qty"],
            "supplier_mismatch": False,
            "bought_for_batch": round(bs["qty"], 3),
            "drawn": round(got, 3), "expected_from_pool": 0.0,
            "delta": round(got, 3),
            "verdict": "bought_for_batch_and_drawn",
        })

    # A draw for a part the supplier's BOM never mentions: packaging, an
    # off-board part, or a draw on the wrong batch. Reported, never judged.
    unexpected = [{"lcsc": k, "drawn": round(v, 3)} for k, v in sorted(drawn.items())
                  if k not in expect and k not in bought]
    by_verdict: dict[str, int] = defaultdict(int)
    for r in rows:
        by_verdict[r["verdict"]] += 1
    return {
        "run_id": run.id,
        # The supplier half needs a cached BOM. The double-supply half never
        # does, so a run with no BOM still gets a verdict where one is possible.
        "known": bool(expect),
        "checked_without_bom": bool(bought),
        "orders": codes,
        "orders_without_bom": missing_bom,
        "rows": rows,
        "unexpected_draws": unexpected,
        "counts": dict(by_verdict),
    }
