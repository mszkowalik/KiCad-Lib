"""Priced project BOMs: volume pricing, currency conversion, MOQ rounding,
cost items, curves, diffs, stock checks and production-run freezing.

Money flow: every price keeps its source currency; display conversion goes
through USD with the stored exchange rates. A production run freezes the
whole computation (lines + rates) into JSONB, then user overrides are
layered on top by line key — so run economics stay reproducible forever.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from . import cost_state, fx, ladder


def display_currency(project: M.Project | None, override: str | None = None) -> str:
    return (override or (project.display_currency if project else None) or settings.default_currency).upper()


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 6)


def _order_qty(needed: int, moq: int | None, multiple: int | None) -> int:
    q = max(needed, moq or 0)
    if multiple and multiple > 0 and q % multiple:
        q = math.ceil(q / multiple) * multiple
    return q


def _price_line(
    points: list[M.ComponentPricePoint],
    supply: M.ComponentSupply | None,
    qty_total: int,
    currency: str,
    rates: dict[str, float],
) -> dict:
    """Ladder pricing for one line at qty_total, converted to `currency`."""
    pt = ladder.price_at(points, max(qty_total, 1))
    out: dict = {
        "unit_price": None, "unit_price_src": None, "price_currency": None,
        "price_qty_from": None, "price_source": None, "price_updated": None,
        "line_total": None, "rate_known": True,
        "moq": supply.moq if supply else None,
        "stock": supply.stock if supply else None,
        "jlc_stock": supply.jlc_stock if supply else None,
        "order_qty": qty_total, "order_excess": 0, "order_total": None,
    }
    if pt is None:
        return out
    unit_disp, known = fx.convert(pt.unit_price, pt.currency, currency, rates)
    out.update(
        unit_price=_round(unit_disp),
        unit_price_src=pt.unit_price,
        price_currency=pt.currency,
        price_qty_from=pt.qty_from,
        price_source=pt.source,
        price_updated=pt.updated_at.isoformat() if pt.updated_at else None,
        line_total=_round(unit_disp * qty_total),
        rate_known=known,
    )
    order_qty = _order_qty(qty_total, out["moq"], supply.order_multiple if supply else None)
    order_pt = ladder.price_at(points, max(order_qty, 1)) or pt
    order_disp, _ = fx.convert(order_pt.unit_price, order_pt.currency, currency, rates)
    out.update(
        order_qty=order_qty,
        order_excess=order_qty - qty_total,
        order_total=_round(order_disp * order_qty),
    )
    if out["stock"] is not None or out["jlc_stock"] is not None:
        # procurable when EITHER pool covers the order (LCSC retail for
        # hand-ordering, JLCPCB assembly parts for JLC-assembled runs)
        out["stock_ok"] = max(out["stock"] or 0, out["jlc_stock"] or 0) >= order_qty
    return out


def _cost_price_at(c: M.ProjectCostItem, volume: int) -> float:
    """Cost item price at a run volume: the step with the largest
    qty_from <= volume wins; `price` is the qty-1 tier."""
    price = c.price
    for step in sorted(c.steps or [], key=lambda s: int(s.get("qty_from", 0))):
        if volume >= int(step.get("qty_from", 0)):
            price = float(step.get("price", price))
    return price


def virtual_component_ids(db: Session, component_ids: set[int]) -> set[int]:
    """Of `component_ids`, the ones flagged non-purchasable — test points,
    logos, fiducials, mounting holes. They are on the board but never bought,
    so their BOM lines are excluded from totals, orders and stock checks."""
    if not component_ids:
        return set()
    return {
        cid
        for (cid,) in db.query(M.Component.id)
        .filter(M.Component.id.in_(component_ids), M.Component.purchasable.is_(False))
        .all()
    }


def _component_data(db: Session, component_ids: set[int], at: datetime | None = None):
    """Points / supply / names / non-purchasable ids per component. With `at`
    set, points come from ComponentPriceHistory resolved at that instant
    (latest snapshot at-or-before, else earliest after); components with no
    history yet fall back to live points — the closest data we have.

    POOL FIRST (user decision 2026-07-28): with `at` set — i.e. pricing a run,
    not browsing a BOM at market prices — a part the company had actually bought
    by that date prices at the pool's moving average as of then, because
    invoices are the ground truth and the ladder is an estimate. The ladder only
    prices parts never (yet) purchased. This also makes plan-vs-actual measure
    what it should: labour, fab and freight, not two price books disagreeing.
    """
    points: dict[int, list[M.ComponentPricePoint]] = {}
    live_ids = set(component_ids)
    if component_ids and at is not None:
        from . import run_actuals  # local import — run_actuals imports this module

        pool = run_actuals.pool_state(db, None, as_of=at.strftime("%Y-%m-%d"))
        for cid in component_ids:
            entry = pool.get(f"c{cid}")
            if entry and entry.get("avg_usd", 0.0) > 0:
                points[cid] = [M.ComponentPricePoint(
                    component_id=cid, source="Pool average (invoices)",
                    qty_from=1, unit_price=round(entry["avg_usd"], 6),
                    currency="USD", updated_at=None,
                )]
        remaining = {cid for cid in component_ids if cid not in points}
        points.update(ladder.history_points_at(db, remaining, at))
        live_ids = {cid for cid in remaining if cid not in points}
    if live_ids:
        for p in db.query(M.ComponentPricePoint).filter(
            M.ComponentPricePoint.component_id.in_(live_ids)
        ).all():
            points.setdefault(p.component_id, []).append(p)
        # Fallback: parts with no ladder fall back to their component_prices
        # summary (which is where manually-entered prices live), so a manual
        # price on a BOM-only part like an enclosure reaches the BOM.
        missing = [cid for cid in live_ids if cid not in points]
        if missing:
            for pr in db.query(M.ComponentPrice).filter(
                M.ComponentPrice.component_id.in_(missing)
            ).all():
                synth = ladder.summary_points(pr)
                if synth:
                    points[pr.component_id] = synth
    supply: dict[int, M.ComponentSupply] = {}
    if component_ids:
        for s in db.query(M.ComponentSupply).filter(
            M.ComponentSupply.component_id.in_(component_ids)
        ).all():
            supply[s.component_id] = s
    names: dict[int, str] = {}
    virtual: set[int] = set()
    if component_ids:
        for c in db.query(M.Component).filter(M.Component.id.in_(component_ids)).all():
            names[c.id] = c.name
            if not c.purchasable:
                virtual.add(c.id)
    return points, supply, names, virtual


def priced_bom(
    db: Session,
    project: M.Project,
    snapshot: M.ProjectSnapshot,
    board: str,
    variant: str,
    volume: int,
    currency: str | None = None,
    at: datetime | None = None,
) -> dict:
    """Priced BOM at a production volume. `at` prices it AS OF that instant
    (historical points + FX); None = current prices."""
    cur = display_currency(project, currency)
    volume = max(int(volume), 1)
    rates = fx.rates_at(db, at) if at is not None else fx.get_rates(db)

    lines = (
        db.query(M.SnapshotBomLine)
        .filter_by(snapshot_id=snapshot.id, board=board, variant=variant)
        .order_by(M.SnapshotBomLine.position)
        .all()
    )
    comp_ids = {li.component_id for li in lines if li.component_id}
    # Manual cost data as of this snapshot's commit (forward-only revisions).
    extras, costs, cost_rev = cost_state.items_for(db, project.id, snapshot)
    comp_ids |= {x.component_id for x in extras if x.component_id}
    points, supply, names, virtual = _component_data(db, comp_ids, at=at)

    out_lines = []
    bom_per_device = 0.0
    order_total_sum = 0.0
    unpriced = 0
    unknown_rates: set[str] = set()

    for li in lines:
        # Virtual parts (test point, logo, fiducial, mounting hole) are on the
        # board but never bought — same treatment as DNP / no-BOM lines.
        not_purchasable = li.component_id in virtual
        excluded = li.dnp or li.exclude_from_bom or not_purchasable
        qty_total = li.qty * volume
        row = {
            "key": f"b{li.id}",
            "refs": li.refs,
            "qty_per": li.qty,
            "qty_total": qty_total,
            "value": li.value,
            "footprint": li.footprint,
            "lcsc": li.lcsc,
            "mpn": li.mpn,
            "manufacturer": li.manufacturer,
            "symbol_name": li.symbol_name,
            "component_id": li.component_id,
            "component_name": names.get(li.component_id or -1),
            "dnp": li.dnp,
            "exclude_from_bom": li.exclude_from_bom,
            "exclude_from_board": li.exclude_from_board,
            "not_purchasable": not_purchasable,
            "excluded": excluded,
        }
        priced = _price_line(
            points.get(li.component_id or -1, []),
            supply.get(li.component_id or -1),
            qty_total, cur, rates,
        )
        row.update(priced)
        if not priced["rate_known"] and priced["price_currency"]:
            unknown_rates.add(priced["price_currency"])
        if not excluded:
            if row["unit_price"] is None:
                unpriced += 1
            else:
                bom_per_device += row["unit_price"] * li.qty
                order_total_sum += row["order_total"] or 0.0
        out_lines.append(row)

    out_extra = []
    extra_per_device = 0.0
    for x in extras:
        qty_total = int(math.ceil(x.qty * volume))
        row = {
            "key": f"x{x.id}",
            "id": x.id,
            "label": x.label,
            "qty_per": x.qty,
            "qty_total": qty_total,
            "component_id": x.component_id,
            "component_name": names.get(x.component_id or -1),
            "manufacturer": x.manufacturer,
            "mpn": x.mpn,
            "notes": x.notes,
        }
        if x.component_id and points.get(x.component_id):
            priced = _price_line(points[x.component_id], supply.get(x.component_id), qty_total, cur, rates)
            row.update(priced)
        else:
            unit_disp, known = (None, True)
            if x.unit_price is not None:
                unit_disp, known = fx.convert(x.unit_price, x.currency, cur, rates)
                if not known:
                    unknown_rates.add(x.currency.upper())
            row.update(
                unit_price=_round(unit_disp),
                unit_price_src=x.unit_price,
                price_currency=x.currency if x.unit_price is not None else None,
                price_qty_from=None, price_source="Manual" if x.unit_price is not None else None,
                price_updated=None, rate_known=known,
                line_total=_round(unit_disp * qty_total) if unit_disp is not None else None,
                moq=None, stock=None, order_qty=qty_total, order_excess=0,
                order_total=_round(unit_disp * qty_total) if unit_disp is not None else None,
            )
        if row["unit_price"] is None:
            unpriced += 1
        else:
            extra_per_device += row["unit_price"] * x.qty
            order_total_sum += row["order_total"] or 0.0
        out_extra.append(row)

    out_costs = []
    cost_per_device = 0.0
    per_run_fixed = 0.0
    for c in costs:
        src_price = _cost_price_at(c, volume)
        price_disp, known = fx.convert(src_price, c.currency, cur, rates)
        if not known:
            unknown_rates.add(c.currency.upper())
        per_device = price_disp if c.basis == "per_device" else price_disp / volume
        out_costs.append(
            {
                "key": f"c{c.id}",
                "id": c.id,
                "label": c.label,
                "basis": c.basis,
                "price_src": src_price,
                "base_price": c.price,
                "steps": c.steps or [],
                "currency": c.currency,
                "price": _round(price_disp),
                "per_device": _round(per_device),
                "company": c.company,
                "mpn": c.mpn,
                "notes": c.notes,
                "rate_known": known,
            }
        )
        cost_per_device += per_device
        if c.basis == "per_run":
            per_run_fixed += price_disp

    device_total = bom_per_device + extra_per_device + cost_per_device
    return {
        "snapshot_id": snapshot.id,
        "sha": snapshot.sha,
        "board": board,
        "variant": variant,
        "volume": volume,
        "currency": cur,
        "rates": rates,
        "lines": out_lines,
        "extra": out_extra,
        "costs": out_costs,
        "cost_revision": cost_state.revision_json(cost_rev),
        "totals": {
            "bom_per_device": _round(bom_per_device),
            "extra_per_device": _round(extra_per_device),
            "cost_per_device": _round(cost_per_device),
            "per_run_fixed": _round(per_run_fixed),
            "device_total": _round(device_total),
            "run_total": _round(device_total * volume),
            "order_parts_total": _round(order_total_sum),
            "unpriced_lines": unpriced,
            "unknown_rates": sorted(unknown_rates),
        },
    }


def cost_curve(db: Session, project, snapshot, board: str, variant: str,
               volumes: list[int], currency: str | None = None) -> list[dict]:
    out = []
    for v in volumes:
        bom = priced_bom(db, project, snapshot, board, variant, v, currency)
        t = bom["totals"]
        out.append(
            {
                "volume": v,
                "device_total": t["device_total"],
                "bom_per_device": t["bom_per_device"],
                "extra_per_device": t["extra_per_device"],
                "cost_per_device": t["cost_per_device"],
                "run_total": t["run_total"],
                "unpriced_lines": t["unpriced_lines"],
            }
        )
    return out


def _diff_key(li: M.SnapshotBomLine) -> str:
    if li.component_id:
        return f"c:{li.component_id}"
    return f"f:{li.symbol_name}|{li.value}|{li.footprint}|{li.lcsc}"


def bom_diff(db: Session, from_snap: M.ProjectSnapshot, to_snap: M.ProjectSnapshot,
             board: str, variant: str) -> dict:
    def load(snap):
        rows = (
            db.query(M.SnapshotBomLine)
            .filter_by(snapshot_id=snap.id, board=board, variant=variant)
            .all()
        )
        # keep excluded lines: DNP changes are exactly what a diff must show
        return {_diff_key(li): li for li in rows}

    a, b = load(from_snap), load(to_snap)
    added, removed, changed = [], [], []

    def as_json(li: M.SnapshotBomLine) -> dict:
        return {
            "refs": li.refs, "qty": li.qty, "value": li.value, "footprint": li.footprint,
            "lcsc": li.lcsc, "symbol_name": li.symbol_name, "component_id": li.component_id,
            "dnp": li.dnp,
        }

    for key, li in b.items():
        if key not in a:
            added.append(as_json(li))
    for key, li in a.items():
        if key not in b:
            removed.append(as_json(li))
    for key in a.keys() & b.keys():
        fa, fb = a[key], b[key]
        if fa.qty != fb.qty or fa.dnp != fb.dnp or fa.refs != fb.refs:
            changed.append({"from": as_json(fa), "to": as_json(fb)})

    return {
        "from": {"snapshot_id": from_snap.id, "sha": from_snap.sha, "ref": from_snap.ref_name},
        "to": {"snapshot_id": to_snap.id, "sha": to_snap.sha, "ref": to_snap.ref_name},
        "board": board,
        "variant": variant,
        "added": added,
        "removed": removed,
        "changed": changed,
    }


def stock_check(db: Session, snapshot: M.ProjectSnapshot, board: str, variant: str,
                volume: int, refresh: bool = True) -> dict:
    """Compare needed order quantities against the user's PRIVATE JLC stock
    (components held on consignment) first, then the market pools for the
    remainder: LCSC retail stock and JLCPCB assembly stock (separate pools —
    either one covering the order counts as procurable). DNP, no-BOM and
    non-purchasable (virtual) lines are skipped. refresh=True refetches live
    LCSC data per distinct part (JLC data in one batch)."""
    from . import jlc

    lines = (
        db.query(M.SnapshotBomLine)
        .filter_by(snapshot_id=snapshot.id, board=board, variant=variant)
        .order_by(M.SnapshotBomLine.position)
        .all()
    )
    private = jlc.private_stock_map(db)
    virtual = virtual_component_ids(db, {li.component_id for li in lines if li.component_id})
    active = [
        li for li in lines
        if not (li.dnp or li.exclude_from_bom or li.component_id in virtual)
    ]
    jlc_rows = ladder._jlc_rows(sorted({li.lcsc for li in active if li.lcsc})) if refresh else {}
    live: dict[str, dict | None] = {}
    results = []
    shortages = 0
    covered_private = 0
    for li in active:
        needed = li.qty * max(volume, 1)
        stock = moq = jlc_stock = None
        if li.component_id and refresh and li.lcsc:
            ladder.refresh_component(db, li.component_id, li.lcsc, jlc_row=jlc_rows.get(li.lcsc))
        if li.component_id:
            s = db.query(M.ComponentSupply).filter_by(component_id=li.component_id).first()
            if s:
                stock, moq, jlc_stock = s.stock, s.moq, s.jlc_stock
        elif li.lcsc:
            if li.lcsc not in live:
                live[li.lcsc] = ladder.fetch_detail(li.lcsc) if refresh else None
            detail = live[li.lcsc]
            if detail:
                stock = detail.get("stockNumber")
                moq = detail.get("minBuyNumber")
            row = jlc_rows.get(li.lcsc)
            if isinstance(row, dict):
                jlc_stock = row.get("stockCount")
        private_qty = private.get(li.lcsc, 0) if li.lcsc else 0
        private_ok = private_qty >= needed
        if private_ok:
            covered_private += 1
        # what still has to be BOUGHT after consuming private stock
        to_buy = max(needed - private_qty, 0)
        order_qty = _order_qty(to_buy, moq if isinstance(moq, int) else None,
                               moq if isinstance(moq, int) else None) if to_buy else 0
        pools = [p for p in (stock, jlc_stock) if isinstance(p, int)]
        market_ok = None if not pools else (max(pools) >= order_qty)
        ok = True if private_ok else market_ok
        if ok is False:
            shortages += 1
        results.append(
            {
                "refs": li.refs, "value": li.value, "lcsc": li.lcsc,
                "component_id": li.component_id, "needed": needed,
                "private_stock": private_qty, "private_ok": private_ok,
                "to_buy": to_buy, "order_qty": order_qty,
                "stock": stock, "jlc_stock": jlc_stock, "moq": moq, "ok": ok,
            }
        )
    return {"volume": volume, "lines": results, "shortages": shortages,
            "covered_by_private": covered_private,
            "private_inventory": len(private),
            "unknown": sum(1 for r in results if r["ok"] is None)}


# ------------------------------------------------------------ production runs

def run_pricing_date(run: M.ProductionRun) -> datetime:
    """The instant a run's prices resolve at: the user-entered run_date (ISO,
    taken as end-of-day UTC so same-day price records count), else the run's
    creation time."""
    s = (run.run_date or "").strip()
    if s:
        try:
            d = datetime.fromisoformat(s)
            if d.tzinfo is None:
                d = d.replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
            return d
        except ValueError:
            pass
    return run.created_at


def priced_bom_costs_only(db: Session, project: M.Project, volume: int,
                          at: datetime | None = None) -> dict:
    """Extra items + cost items without a snapshot (runs not tied to a ref).
    `at` prices as of that instant, like priced_bom."""
    rates = fx.rates_at(db, at) if at is not None else fx.get_rates(db)
    cur = display_currency(project)
    volume = max(int(volume), 1)
    comp_ids = set()
    # No commit context → the current (latest-anchored) cost revision.
    extras, costs, cost_rev = cost_state.items_for(db, project.id, None)
    comp_ids |= {x.component_id for x in extras if x.component_id}
    points, supply, names, _virtual = _component_data(db, comp_ids, at=at)
    out_extra = []
    extra_per_device = 0.0
    for x in extras:
        qty_total = int(math.ceil(x.qty * volume))
        row = {"key": f"x{x.id}", "id": x.id, "label": x.label, "qty_per": x.qty,
               "qty_total": qty_total, "component_id": x.component_id,
               "component_name": names.get(x.component_id or -1),
               "manufacturer": x.manufacturer, "mpn": x.mpn, "notes": x.notes}
        if x.component_id and points.get(x.component_id):
            row.update(_price_line(points[x.component_id], supply.get(x.component_id), qty_total, cur, rates))
        elif x.unit_price is not None:
            unit_disp, known = fx.convert(x.unit_price, x.currency, cur, rates)
            row.update(unit_price=_round(unit_disp), price_currency=x.currency,
                       price_source="Manual", line_total=_round(unit_disp * qty_total),
                       rate_known=known, order_qty=qty_total, order_total=_round(unit_disp * qty_total))
        else:
            row.update(unit_price=None, line_total=None, order_qty=qty_total, order_total=None)
        if row.get("unit_price") is not None:
            extra_per_device += row["unit_price"] * x.qty
        out_extra.append(row)

    out_costs = []
    cost_per_device = 0.0
    per_run_fixed = 0.0
    for c in costs:
        src_price = _cost_price_at(c, volume)
        price_disp, known = fx.convert(src_price, c.currency, cur, rates)
        per_device = price_disp if c.basis == "per_device" else price_disp / volume
        out_costs.append({"key": f"c{c.id}", "id": c.id, "label": c.label, "basis": c.basis,
                          "price_src": src_price, "base_price": c.price, "steps": c.steps or [],
                          "currency": c.currency, "price": _round(price_disp),
                          "per_device": _round(per_device), "company": c.company, "mpn": c.mpn,
                          "notes": c.notes, "rate_known": known})
        cost_per_device += per_device
        if c.basis == "per_run":
            per_run_fixed += price_disp
    device_total = extra_per_device + cost_per_device
    return {
        "extra": out_extra, "costs": out_costs, "rates": rates,
        "cost_revision": cost_state.revision_json(cost_rev),
        "totals": {"bom_per_device": 0.0, "extra_per_device": _round(extra_per_device),
                   "cost_per_device": _round(cost_per_device), "per_run_fixed": _round(per_run_fixed),
                   "device_total": _round(device_total), "run_total": _round(device_total * volume),
                   "order_parts_total": None, "unpriced_lines": 0, "unknown_rates": []},
    }


def run_effective(db: Session, run: M.ProductionRun) -> dict:
    """Run economics computed ON DEMAND from historical pricing at the run's
    date (run_pricing_date), with overrides applied. Overrides:
    {<line key>: {unit_price?, qty_total?, label?, note?, drop?}} plus
    {"added": [{label, qty, unit_price, note}]} — prices in the project's
    display currency."""
    project = db.get(M.Project, run.project_id)
    at = run_pricing_date(run)
    snap = db.get(M.ProjectSnapshot, run.snapshot_id) if run.snapshot_id else None
    if snap is not None:
        bom = priced_bom(db, project, snap, run.board, run.variant, run.qty, at=at)
        bom_lines = bom["lines"]
    else:
        bom = priced_bom_costs_only(db, project, run.qty, at=at)
        bom_lines = []
    base = {"lines": bom_lines, "extra": bom["extra"], "costs": bom["costs"]}
    overrides = run.overrides or {}
    qty = max(run.qty or 1, 1)
    lines = []
    totals_parts = 0.0
    for section in ("lines", "extra"):
        for row in base.get(section, []):
            eff = dict(row)
            ov = overrides.get(row["key"]) or {}
            eff["overridden"] = bool(ov)
            if ov.get("drop"):
                eff["dropped"] = True
                lines.append(eff)
                continue
            if ov.get("unit_price") is not None:
                eff["unit_price"] = float(ov["unit_price"])
            if ov.get("qty_total") is not None:
                eff["qty_total"] = int(ov["qty_total"])
            if ov.get("label"):
                eff["label"] = ov["label"]
            if ov.get("note"):
                eff["override_note"] = ov["note"]
            if eff.get("unit_price") is not None and not eff.get("excluded"):
                eff["line_total"] = _round(eff["unit_price"] * eff["qty_total"])
                totals_parts += eff["line_total"]
            lines.append(eff)
    costs = []
    cost_total = 0.0
    for row in base.get("costs", []):
        eff = dict(row)
        ov = overrides.get(row["key"]) or {}
        eff["overridden"] = bool(ov)
        if ov.get("drop"):
            eff["dropped"] = True
            costs.append(eff)
            continue
        if ov.get("price") is not None:
            eff["price"] = float(ov["price"])
            eff["per_device"] = _round(eff["price"] if eff["basis"] == "per_device" else eff["price"] / qty)
        if ov.get("note"):
            eff["override_note"] = ov["note"]
        total = eff["price"] * (qty if eff["basis"] == "per_device" else 1)
        cost_total += total
        eff["run_cost"] = _round(total)
        costs.append(eff)
    added = []
    for i, ov in enumerate(overrides.get("added", [])):
        try:
            line_qty = float(ov.get("qty", 1))
            unit = float(ov.get("unit_price", 0))
        except (TypeError, ValueError):
            continue
        total = _round(unit * line_qty)
        totals_parts += total or 0.0
        added.append({"key": f"a{i}", "label": ov.get("label", ""), "qty_total": line_qty,
                      "unit_price": unit, "line_total": total, "note": ov.get("note", "")})
    run_total = totals_parts + cost_total
    return {
        "priced_at": at.isoformat(),
        "currency": display_currency(project),
        "cost_revision": bom.get("cost_revision"),
        "qty": qty,
        "lines": lines,
        "costs": costs,
        "added": added,
        "totals": {
            "parts_total": _round(totals_parts),
            "costs_total": _round(cost_total),
            "run_total": _round(run_total),
            "per_device": _round(run_total / qty),
        },
    }
