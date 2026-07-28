"""Lot ledger — which purchase each draw consumed, and what remains of each.

Built as a fourth REPLAYER over `run_actuals._pool_events`, never as a fourth
builder of events. That module's docstring calls itself the ONE source of stock
events precisely so `pool_state`, `component_ledger` and `check_shortages` cannot
disagree about what happened; adding a parallel event list here would reintroduce
exactly the drift it exists to prevent.

Two invariants shape everything below.

**Remaining quantity is never stored.** A lot's remaining = what it bought minus
everything bound to it, computed on read. Storing it would be a cached aggregate
that the next backfilled purchase silently invalidates — and this codebase
already computes run economics on read for the same reason.

**Remaining VALUE is `value_bought − Σ(bound value)`, never
`qty_remaining × unit_cost`.** A lot's landed unit is derived on read from its
line plus its share of any carrier (freight/duty) on the same document, so it
CHANGES whenever a carrier line is added — which `invoice_register` actively
nags you to do. Draw prices, by contrast, are frozen at bind time. Multiplying a
current unit by a remaining quantity therefore drifts from the money actually
spent; subtracting what was consumed cannot.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy.orm import Session

from .. import models as M
from . import fx, run_actuals

log = logging.getLogger(__name__)

# A lot whose remaining quantity is at or below this counts as closed.
CLOSED_EPS = 1e-6


def _lot_key(kind: str, ident: int) -> str:
    """`L123` = purchase line 123, `A7` = stock adjustment 7."""
    return f"{kind}{ident}"


def lot_state(db: Session, as_of: str | None = None) -> dict:
    """Per-lot and per-part state, replayed from the shared event list.

    Returns `{"lots": {key: {...}}, "parts": {identity: {...}}}`.

    A lot is a purchase line (or a POSITIVE stock adjustment, which creates real
    priced stock with no purchase behind it — `opening_balance` rows do exactly
    that, and excluding them would make every draw against opening stock
    permanently unallocatable).
    """
    events, doc_by_id, surcharge = run_actuals._pool_events(db)

    # One rate table per distinct event date — the same shape `pool_state` uses,
    # so a lot's landed cost is derived by exactly the code that values the pool.
    rate_cache: dict[str, dict[str, float]] = {}

    def rates_for(date_iso: str) -> dict[str, float]:
        if date_iso not in rate_cache:
            rate_cache[date_iso] = fx.rates_at(db, run_actuals._as_dt(date_iso))
        return rate_cache[date_iso]

    lots: dict[str, dict] = {}
    for when, kind, row in events:
        if as_of and when and when > as_of:
            continue
        if kind == "buy":
            key = _lot_key("L", row.id)
            doc = doc_by_id[row.document_id]
            extra = surcharge.get(row.id, 0.0)  # freight/duty share, doc currency
            unit_usd, extra_usd, known = run_actuals._buy_usd(
                row, doc, extra, rates_for(when))
            qty = row.qty or 0.0
            # LANDED value: the line plus its share of any carrier on the same
            # document. This is why `value_remaining` must be a subtraction —
            # adding a freight line later changes this figure, while the draws
            # already bound against it stay frozen.
            value = qty * unit_usd + extra_usd
            lots[key] = {
                "key": key, "kind": "line", "id": row.id,
                "date": when, "lcsc": row.lcsc or "", "mpn": row.mpn or "",
                "component_id": row.component_id,
                "lot_ref": getattr(row, "lot_ref", "") or "",
                "document_id": row.document_id,
                "qty_bought": qty,
                "unit_cost_usd": round(value / qty, 8) if qty else 0.0,
                "value_bought": round(value, 6),
                "unknown_rate": not known,
                "qty_assigned": 0.0, "value_assigned": 0.0,
            }
        elif kind == "adj" and (row.qty_delta or 0) > 0:
            key = _lot_key("A", row.id)
            qty = row.qty_delta or 0.0
            unit = row.unit_cost_usd or 0.0
            lots[key] = {
                "key": key, "kind": "adjustment", "id": row.id,
                "date": when, "lcsc": row.lcsc or "", "mpn": row.mpn or "",
                "component_id": row.component_id,
                "lot_ref": "", "document_id": None,
                "qty_bought": qty,
                "unit_cost_usd": unit,
                "value_bought": round(qty * unit, 6),
                "qty_assigned": 0.0, "value_assigned": 0.0,
                "unknown_rate": False,
                "reason": row.reason or "",
            }

    # Bindings are counted over ALL of them, not just those dated before `as_of`.
    # A lot consumed by a June draw is not available to a February backfill, and
    # windowing the assignments would hand the same stock out twice.
    for b in db.query(M.ComponentConsumptionLot).all():
        key = (_lot_key("L", b.lot_line_id) if b.lot_line_id
               else _lot_key("A", b.lot_adjustment_id) if b.lot_adjustment_id
               else None)
        if key is None or key not in lots:
            continue
        lots[key]["qty_assigned"] += b.qty or 0.0
        lots[key]["value_assigned"] += (b.qty or 0.0) * (b.unit_cost_usd or 0.0)

    for lot in lots.values():
        lot["qty_remaining"] = round(lot["qty_bought"] - lot["qty_assigned"], 6)
        # See the module docstring: subtract what was consumed, never multiply
        # a current unit by a remaining quantity.
        lot["value_remaining"] = round(lot["value_bought"] - lot["value_assigned"], 6)
        lot["open"] = lot["qty_remaining"] > CLOSED_EPS
        lot["qty_assigned"] = round(lot["qty_assigned"], 6)
        lot["value_assigned"] = round(lot["value_assigned"], 6)

    parts: dict[str, dict] = defaultdict(
        lambda: {"open_qty": 0.0, "open_value_usd": 0.0, "stranded_usd": 0.0,
                 "lot_count": 0, "open_lot_count": 0, "last_lot_usd": None,
                 "last_lot_date": ""}
    )
    for lot in sorted(lots.values(), key=lambda x: (x["date"] or "", x["id"])):
        for ident in run_actuals._identity_keys(lot["component_id"], lot["mpn"], lot["lcsc"]):
            p = parts[ident]
            p["lot_count"] += 1
            if lot["open"]:
                p["open_qty"] += lot["qty_remaining"]
                p["open_value_usd"] += lot["value_remaining"]
                p["open_lot_count"] += 1
            else:
                # Value left in a CLOSED lot: real money that no remaining
                # quantity can carry, typically freight added after the lot was
                # fully drawn. Named rather than floored away, so it can be seen
                # and decided on instead of quietly poisoning an average.
                p["stranded_usd"] += lot["value_remaining"]
            if lot["unit_cost_usd"]:
                p["last_lot_usd"] = lot["unit_cost_usd"]
                p["last_lot_date"] = lot["date"] or ""

    for p in parts.values():
        p["open_qty"] = round(p["open_qty"], 6)
        p["open_value_usd"] = round(p["open_value_usd"], 6)
        p["stranded_usd"] = round(p["stranded_usd"], 6)
        # The average is taken over OPEN lots only, so stranded money in a closed
        # lot can never poison the denominator.
        p["avg_usd_lots"] = (round(p["open_value_usd"] / p["open_qty"], 8)
                             if p["open_qty"] > CLOSED_EPS else None)

    return {"lots": lots, "parts": dict(parts)}


def unallocated_draws(db: Session) -> list[dict]:
    """Draws with no lot binding at all — the honest measure of how much of the
    ledger the lot layer does NOT yet explain."""
    bound = {b.consumption_id for b in db.query(M.ComponentConsumptionLot).all()}
    out = []
    for c in run_actuals.live_consumption(db).all():
        if c.id in bound:
            continue
        out.append({
            "id": c.id, "run_id": c.run_id, "lcsc": c.lcsc, "mpn": c.mpn,
            "qty": c.qty, "unit_cost_usd": c.unit_cost_usd,
            "value_usd": round((c.qty or 0) * (c.unit_cost_usd or 0), 4),
            "basis": c.basis, "consumed_at": c.consumed_at,
        })
    return out


def coverage(db: Session) -> dict:
    """How much of the drawn value is lot-attributed. This is the number that
    tells you whether lot accounting can safely become the pricing authority —
    it should approach 100% before `avg_usd` is switched over."""
    state = lot_state(db)
    total_drawn = 0.0
    for c in run_actuals.live_consumption(db).all():
        total_drawn += (c.qty or 0) * (c.unit_cost_usd or 0)
    unalloc = unallocated_draws(db)
    unalloc_value = sum(u["value_usd"] for u in unalloc)
    lots = state["lots"].values()
    return {
        "lot_count": len(state["lots"]),
        "open_lot_count": sum(1 for lt in lots if lt["open"]),
        "value_bought_usd": round(sum(lt["value_bought"] for lt in lots), 2),
        "value_assigned_usd": round(sum(lt["value_assigned"] for lt in lots), 2),
        "open_value_usd": round(sum(lt["value_remaining"] for lt in lots if lt["open"]), 2),
        "stranded_usd": round(
            sum(lt["value_remaining"] for lt in lots if not lt["open"]), 2),
        "drawn_value_usd": round(total_drawn, 2),
        "unallocated_draw_count": len(unalloc),
        "unallocated_value_usd": round(unalloc_value, 2),
        "coverage_pct": (round(100 * (1 - unalloc_value / total_drawn), 2)
                         if total_drawn else None),
    }


def check_lot_capacity(db: Session, bindings: list[dict]) -> list[dict]:
    """Would these bindings overdraw any lot? Returns the offenders.

    `check_shortages` is part-level and knows nothing about lots, so nothing
    otherwise stops two draws consuming the same lot twice — and a floor-at-zero
    would hide it. Same contract shape as `check_shortages` so the caller can
    raise the identical 409.
    """
    state = lot_state(db)
    want: dict[str, float] = defaultdict(float)
    for b in bindings:
        key = (_lot_key("L", b["lot_line_id"]) if b.get("lot_line_id")
               else _lot_key("A", b["lot_adjustment_id"]) if b.get("lot_adjustment_id")
               else None)
        if key:
            want[key] += b.get("qty") or 0.0
    out = []
    for key, qty in want.items():
        lot = state["lots"].get(key)
        if lot is None:
            out.append({"lot": key, "problem": "lot does not exist", "wanted": qty})
        elif qty - lot["qty_remaining"] > CLOSED_EPS:
            out.append({
                "lot": key, "problem": "would overdraw", "wanted": qty,
                "remaining": lot["qty_remaining"],
                "lcsc": lot["lcsc"], "mpn": lot["mpn"],
            })
    return out
