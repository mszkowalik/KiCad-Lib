"""Hold the material ledger to today's figures (decision 0097, phase 1).

Each check compares one reader of the ledger (`state`) with the function that
answers the same question today, and lists every difference with the rows
that differ. A phase of 0097 ends only when each difference is fixed or
explained (docs/material-ledger/design.md, section 8).

Tolerances: a quantity must agree to 1e-6 pieces, money to 0.01 USD per row.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ... import models as M
from .. import lots as _lots
from .. import run_actuals, twins
from . import project, state

QTY_TOL = 1e-6
USD_TOL = 0.01
SAMPLE = 25


def _diff(rows: list[dict]) -> dict:
    return {"ok": not rows, "differences": len(rows), "sample": rows[:SAMPLE]}


def stock(db: Session, company_id: int | None) -> dict:
    """Checks 1 to 3: quantity, value, lowest balance and first short day of
    each part, for one company's stock or the one pool."""
    old = run_actuals.pool_state(db, company_id=company_id)
    new = state.item_state(db, company_id=company_id)
    qty, value, low = [], [], []
    for key in sorted(set(old) | set(new)):
        o, n = old.get(key) or {}, new.get(key) or {}
        oq, nq = o.get("qty", 0.0), n.get("qty", 0.0)
        if abs(oq - nq) > QTY_TOL:
            qty.append({"key": key, "pool": round(oq, 6), "ledger": round(nq, 6)})
        ov, nv = o.get("value_usd", 0.0), n.get("value_usd", 0.0)
        if abs(ov - nv) > USD_TOL:
            value.append({"key": key, "pool": round(ov, 4), "ledger": round(nv, 4)})
        if (abs(o.get("min_qty", 0.0) - n.get("min_qty", 0.0)) > QTY_TOL
                or o.get("first_short") != n.get("first_short")):
            low.append({"key": key, "pool": [round(o.get("min_qty", 0.0), 6), o.get("first_short")],
                        "ledger": [round(n.get("min_qty", 0.0), 6), n.get("first_short")]})
    return {"parts": len(set(old) | set(new)), "quantity": _diff(qty), "value": _diff(value),
            "lowest_balance": _diff(low)}


def lots(db: Session) -> dict:
    """Check 4: what each lot got and what is left of it, in quantity and in
    the lot's own price."""
    old = _lots.lot_state(db)["lots"]
    new = state.lot_state(db)
    rows = []
    for key in sorted(set(old) | set(new)):
        o, n = old.get(key), new.get(key)
        if o is None or n is None:
            rows.append({"lot": key, "missing_in": "ledger" if n is None else "lot ledger"})
            continue
        bad = {}
        for f, tol in (("qty_bought", QTY_TOL), ("qty_remaining", QTY_TOL),
                       ("value_bought", USD_TOL), ("value_remaining", USD_TOL)):
            if abs((o.get(f) or 0.0) - (n.get(f) or 0.0)) > tol:
                bad[f] = [round(o.get(f) or 0.0, 6), round(n.get(f) or 0.0, 6)]
        if bad:
            rows.append({"lot": key, **bad})
    return {"lots": len(set(old) | set(new)), **_diff(rows)}


def units(db: Session, register: dict | None = None) -> dict:
    """Checks 5 to 7: each click's parts, each batch's step draws and origin
    batch cost (what `twins.cost_by_step` is made of), each unit's status and
    price, and what an order charges for each named unit's device."""
    reg = register or run_actuals.invoice_register(db, accountant=False)
    led = state.Units(db, reg)
    by_click_old, by_run_old = twins._step_draw_values(db)
    click_src = {e.id: e.source_id for e in led.events.values()}
    clicks = []
    for ev_id, sr_id in click_src.items():
        o, n = by_click_old.get(sr_id, 0.0), led.click_value.get(ev_id, 0.0)
        if abs(o - n) > USD_TOL:
            clicks.append({"click": sr_id, "twins": round(o, 4), "ledger": round(n, 4)})
    batches = []
    runs = sorted({lot.origin_run_id for lot in led.lots.values() if lot.origin_run_id})
    old_origin = twins.origin_shares(db, runs, reg)
    for rid in runs:
        o, n = old_origin.get(rid) or {}, led.origin(rid)
        bad = {}
        if abs(by_run_old.get(rid, 0.0) - led.step_by_run.get(rid, 0.0)) > USD_TOL:
            bad["step_draws_usd"] = [round(by_run_old.get(rid, 0.0), 4), round(led.step_by_run.get(rid, 0.0), 4)]
        for f_old, f_new in (("origin_cost_usd", "origin_cost_usd"), ("scrap_carried_usd", "scrap_carried_usd"),
                             ("share_usd", "share_usd")):
            a, b = o.get(f_old), n.get(f_new)
            if (a is None) != (b is None) or (a is not None and abs(a - b) > USD_TOL):
                bad[f_new] = [a, None if b is None else round(b, 6)]
        if o.get("twins") != n.get("units"):
            bad["units"] = [o.get("twins"), n.get("units")]
        if bad:
            batches.append({"batch": rid, **bad})
    tw = db.query(M.Twin).all()
    old_prices = twins.prices(db, tw, reg)
    lot_of_twin = {lot.source_id: lid for lid, lot in led.lots.items()}
    new_prices = led.prices()
    status, prices = [], []
    for t in tw:
        lid = lot_of_twin.get(t.id)
        if lid is None:
            status.append({"twin": t.id, "missing_in": "ledger"})
            continue
        if led.status[lid] != t.status:
            status.append({"twin": t.id, "twins": t.status, "ledger": led.status[lid]})
        o, n = old_prices[t.id], new_prices[lid]
        bad = {f: [o[f], round(n[f], 4)] for f in ("own_parts_usd", "step_costs_usd", "origin_share_usd", "total_usd")
               if abs(o[f] - n[f]) > USD_TOL}
        if bad:
            prices.append({"twin": t.id, **bad})
    old_dev = twins.device_costs(db, reg)
    new_dev = {lot.device_unit_id: (0.0 if led.status[lid] == "scrapped" else new_prices[lid]["total_usd"])
               for lid, lot in led.lots.items() if lot.device_unit_id}
    devices = [{"device": d, "twins": old_dev.get(d), "ledger": None if new_dev.get(d) is None else round(new_dev[d], 4)}
               for d in sorted(set(old_dev) | set(new_dev))
               if old_dev.get(d) is None or new_dev.get(d) is None or abs(old_dev[d] - new_dev[d]) > USD_TOL]
    return {"units": len(tw), "clicks": _diff(clicks), "batches": _diff(batches), "status": _diff(status),
            "prices": _diff(prices), "devices": _diff(devices)}


def check(db: Session, *, rebuild: bool = True) -> dict:
    """Rebuild the shadow (unless told not to) and run every check. The pool
    is checked as one and for each company, whatever `stock_per_company`
    says, because the ledger must hold both views."""
    built = project.rebuild(db) if rebuild else None
    scopes: dict[str, dict] = {"pool": stock(db, None)}
    for c in db.query(M.Company).order_by(M.Company.id).all():
        scopes[f"company {c.id} ({c.key})"] = stock(db, c.id)
    lot = lots(db)
    unit = units(db)
    ok = (lot["ok"] and all(s[k]["ok"] for s in scopes.values() for k in ("quantity", "value", "lowest_balance"))
          and all(unit[k]["ok"] for k in ("clicks", "batches", "status", "prices", "devices")))
    return {"ok": ok, "rebuild": built, "stock": scopes, "lots": lot, "units": unit}
