"""Read the material ledger (decision 0097, phase 1).

The readers here answer the questions `run_actuals.pool_state`,
`lots.lot_state` and `twins.prices` answer today, from the ledger's rows
only, plus the invoice lines that stay the source of every receipt's money.
Phase 3 makes them the readers; until then `parity` holds them to the old
answers, and a difference is a defect in the projection or in this module.

**The replay is `pool_state`'s, moved.** Same order (day, then adjustments,
purchases, draws, then the pool's own order, which the projector kept as the
move ids), the same moving-average basis that never goes below zero, and a
draw's moves taken back together as the one draw the pool replays. It is the
successor of the old replay, not a second guard beside it: nothing refuses a
write on it.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import models as M
from .. import fx, run_actuals


def receipt_values(db: Session) -> dict[int, float]:
    """Landed USD of every pooled purchase line, valued as the pool values it:
    the line, its share of a freight or duty carrier on the same document, the
    document's pinned rate or the rate of its day. Read on every call, because
    a carrier added later changes it."""
    events, doc_by_id, surcharge = run_actuals._pool_events(db, with_transfers=True)
    rate_cache: dict[str, dict[str, float]] = {}
    out: dict[int, float] = {}
    for when, kind, row in events:
        if kind != "buy":
            continue
        if when not in rate_cache:
            rate_cache[when] = fx.rates_at(db, run_actuals._as_dt(when))
        unit_usd, extra_usd, _known = run_actuals._buy_usd(
            row, doc_by_id[row.document_id], surcharge.get(row.id, 0.0), rate_cache[when])
        out[row.id] = (row.qty or 0.0) * unit_usd + extra_usd
    return out


def _rows(db: Session, company_id: int | None):
    """Part moves of one company's stock, or of the one pool (in-house
    transfers left out on both sides, as `_pool_events` leaves them out),
    in replay order."""
    q = (db.query(M.MaterialMove, M.MaterialEvent.kind)
         .join(M.MaterialEvent, M.MaterialEvent.id == M.MaterialMove.event_id)
         .join(M.MaterialItem, M.MaterialItem.id == M.MaterialMove.item_id)
         .filter(M.MaterialItem.kind == "part"))
    if company_id is not None:
        q = q.filter(M.MaterialMove.company_id == company_id)
    else:
        q = q.filter(M.MaterialEvent.kind != "transfer")
    rows = [m for m, _k in q.all()]
    rows.sort(key=lambda m: (m.at or "9999", m.rank, m.id))
    return rows


def _pool_events(rows: list[M.MaterialMove]):
    """The moves, with the moves of one draw taken back together."""
    out: list[tuple[str, list[M.MaterialMove]]] = []
    for m in rows:
        if (m.source_kind == "consumption" and out and out[-1][0] == "use"
                and out[-1][1][-1].source_kind == "consumption" and out[-1][1][-1].source_id == m.source_id):
            out[-1][1].append(m)
        elif m.source_kind == "consumption":
            out.append(("use", [m]))
        else:
            out.append(("adj" if m.rank == 0 else "buy", [m]))
    return out


def item_state(db: Session, company_id: int | None = None) -> dict[str, dict]:
    """Per pool identity: quantity, value, moving average, the lowest balance
    and the first day it went short. The shape of `pool_state`'s figures."""
    receipts = receipt_values(db)
    extras = run_actuals.conversion_extras_usd(db)
    pool: dict[str, dict] = defaultdict(lambda: {"qty": 0.0, "value_usd": 0.0, "avg_usd": 0.0,
                                                 "_avg_qty": 0.0, "_avg_value": 0.0,
                                                 "min_qty": 0.0, "first_short": None})
    for kind, ms in _pool_events(_rows(db, company_id)):
        p = pool[ms[0].pool_key]
        day = ms[0].at
        if kind == "use":
            q = -sum(m.qty for m in ms)
            v = -sum((m.value_usd if m.value_source != "average" else m.qty * p["avg_usd"]) or 0.0 for m in ms)
            p["qty"] -= q
            p["value_usd"] -= v
            taken = min(q, max(p["_avg_qty"], 0.0))
            basis = p["_avg_value"] / p["_avg_qty"] if p["_avg_qty"] > 0.0001 else 0.0
            p["_avg_qty"] -= taken
            p["_avg_value"] = max(p["_avg_value"] - taken * basis, 0.0)
        else:
            m = ms[0]
            q = m.qty or 0.0
            if m.value_source == "invoice":
                v = receipts.get(m.source_id, 0.0)
            elif m.value_source == "average":
                v = q * p["avg_usd"]
            else:
                v = m.value_usd or 0.0
            if q > 0 and m.value_source in ("adjustment", "average"):
                v += extras.get(m.source_id, 0.0)
            p["qty"] += q
            p["value_usd"] += v
            if q >= 0:
                p["_avg_qty"] += q
                p["_avg_value"] += v
            else:
                taken = min(-q, max(p["_avg_qty"], 0.0))
                basis = p["_avg_value"] / p["_avg_qty"] if p["_avg_qty"] > 0.0001 else 0.0
                p["_avg_qty"] -= taken
                p["_avg_value"] = max(p["_avg_value"] - taken * basis, 0.0)
        if p["_avg_qty"] > 0.0001:
            p["avg_usd"] = p["_avg_value"] / p["_avg_qty"]
        if p["qty"] < p["min_qty"]:
            p["min_qty"] = p["qty"]
            if p["qty"] < -0.0001 and p["first_short"] is None:
                p["first_short"] = day
    return {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in pool.items()}


def lot_state(db: Session) -> dict[str, dict]:
    """Per lot that stands for a purchase line or a positive adjustment
    (`L<id>`, `A<id>`): what it got and what the draws bound to it took, in
    quantity and in the lot's own price. The shape of `lots.lot_state`."""
    receipts = receipt_values(db)
    extras = run_actuals.conversion_extras_usd(db)
    lots = {lot.id: lot for lot in db.query(M.MaterialLot)
            .filter(M.MaterialLot.source_kind.in_(("line", "adjustment"))).all()}
    out = {lot.label: {"qty_bought": 0.0, "value_bought": 0.0, "qty_assigned": 0.0, "value_assigned": 0.0}
           for lot in lots.values()}
    for m in (db.query(M.MaterialMove)
              .filter(M.MaterialMove.lot_id.in_(list(lots) or [-1])).all()):
        o = out[lots[m.lot_id].label]
        if m.qty > 0:
            o["qty_bought"] += m.qty
            o["value_bought"] += (receipts.get(m.source_id, 0.0) if m.value_source == "invoice"
                                  else (m.lot_value_usd or 0.0) + extras.get(m.source_id, 0.0))
        else:
            o["qty_assigned"] += -m.qty
            o["value_assigned"] += -(m.lot_value_usd or 0.0)
    for o in out.values():
        o["qty_remaining"] = o["qty_bought"] - o["qty_assigned"]
        o["value_remaining"] = o["value_bought"] - o["value_assigned"]
    return out


# ================================================================== units

class Units:
    """Every product unit's lot, its status and its price, read from the
    ledger: the rules of 0059 §11, 0060 §5 and 0074 applied to events, event
    lots, moves and cost aims (`twins.prices` is the old reader).

    The batch's total still comes from the invoice register: the ledger aims
    invoice positions at work, it does not hold their money."""

    def __init__(self, db: Session, register: dict | None = None):
        self.db = db
        self.register = register or run_actuals.invoice_register(db, accountant=False)
        self.events = {e.id: e for e in db.query(M.MaterialEvent)
                       .filter(M.MaterialEvent.source_kind == "step_run").all()}
        self.click_value: dict[int, float] = defaultdict(float)
        self.step_by_run: dict[int, float] = defaultdict(float)
        for ev_id, run_id, v in (db.query(M.MaterialMove.event_id, M.MaterialMove.run_id,
                                          func.sum(M.MaterialMove.value_usd))
                                 .filter(M.MaterialMove.event_id.in_(list(self.events) or [-1]),
                                         M.MaterialMove.source_kind == "consumption")
                                 .group_by(M.MaterialMove.event_id, M.MaterialMove.run_id).all()):
            self.click_value[ev_id] += -(v or 0.0)
            self.step_by_run[run_id] += -(v or 0.0)
        self.lots = {lot.id: lot for lot in db.query(M.MaterialLot)
                     .filter(M.MaterialLot.source_kind == "twin").all()}
        self.lots_of_event: dict[int, set[int]] = defaultdict(set)
        self.events_of_lot: dict[int, list[int]] = defaultdict(list)
        for ev_id, lot_id in (db.query(M.MaterialEventLot.event_id, M.MaterialEventLot.lot_id)
                              .order_by(M.MaterialEventLot.event_id, M.MaterialEventLot.id).all()):
            if lot_id in self.lots:
                self.lots_of_event[ev_id].add(lot_id)
                self.events_of_lot[lot_id].append(ev_id)
        self.status = {lid: self._status(lid) for lid in self.lots}
        self.shares = self._shares()

    def _status(self, lot_id: int) -> str:
        """The last finish, scrap or reopen the unit took part in decides."""
        status = "active"
        for ev_id in sorted(self.events_of_lot.get(lot_id, [])):
            kind = self.events[ev_id].step_kind if ev_id in self.events else ""
            status = {"finish": "finished", "scrap": "scrapped", "reopen": "active"}.get(kind, status)
        return status

    def _shares(self) -> list[dict]:
        """Every invoice position aimed at clicks, with the units that carry it
        in equal shares. A position counts only while it is charged to the
        batch of its clicks (as `twins.line_shares`)."""
        clicks_of: dict[int, set[int]] = defaultdict(set)
        for line_id, ev_id in (self.db.query(M.MaterialCostAim.line_id, M.MaterialCostAim.event_id)
                               .filter(M.MaterialCostAim.source_kind == "click").all()):
            clicks_of[line_id].add(ev_id)
        if not clicks_of:
            return []
        hdrs = run_actuals.header_ids(self.db)
        lines = (self.db.query(M.RunCostLine)
                 .filter(M.RunCostLine.id.in_(list(set(clicks_of) - hdrs)),
                         M.RunCostLine.voided_at.is_(None)).all())
        vals = run_actuals.leaf_line_usd(self.db, lines)
        out = []
        for li in lines:
            usd, dest, ref = vals[li.id]
            clicks = clicks_of[li.id]
            if dest != "run" or {self.events[e].run_id for e in clicks} != {ref}:
                continue
            units = set().union(*(self.lots_of_event[e] for e in clicks))
            out.append({"line": li, "usd": usd, "run_id": ref, "clicks": sorted(clicks), "units": units})
        return out

    def own_parts(self, lot_id: int) -> float:
        return sum(self.click_value.get(e, 0.0) / self.events[e].units
                   for e in self.events_of_lot.get(lot_id, []) if self.events[e].units)

    def own_step_costs(self, lot_ids: set[int]) -> dict[int, float]:
        out: dict[int, float] = defaultdict(float)
        for sh in self.shares:
            n = len(sh["units"])
            for lid in sh["units"] & lot_ids:
                out[lid] += sh["usd"] / n
        return out

    def origin(self, run_id: int) -> dict:
        """The origin batch cost, what its scrapped units carry over, and the
        share of each unit of the batch that is neither scrapped nor found."""
        run = self.db.get(M.ProductionRun, run_id)
        mine = [lid for lid, lot in self.lots.items() if lot.origin_run_id == run_id and not lot.found]
        alive = [lid for lid in mine if self.status[lid] != "scrapped"]
        scrapped = [lid for lid in mine if self.status[lid] == "scrapped"]
        # A found unit entered in this batch and scrapped here: what this batch
        # drew for it stays with the batch's good units.
        found_scrapped = [lid for lid, lot in self.lots.items()
                          if lot.found and self.status[lid] == "scrapped"
                          and lot.created_event_id in self.events
                          and self.events[lot.created_event_id].run_id == run_id]
        carried_ids = set(scrapped + found_scrapped)
        fees = self.own_step_costs(carried_ids)
        carried = sum(self.own_parts(lid) for lid in carried_ids) + sum(fees.values())
        total = float((self.register.get("by_run_usd", {}).get(str(run_id)) or {}).get("total_usd") or 0.0)
        lines_by_run = sum(sh["usd"] for sh in self.shares if sh["units"] and sh["run_id"] == run_id)
        origin = total - self.step_by_run.get(run_id, 0.0) - lines_by_run
        frozen = run.closed_twin_share_usd if run is not None else None
        share = frozen if frozen is not None else ((origin + carried) / len(alive) if alive else None)
        return {"origin_cost_usd": origin, "scrap_carried_usd": carried, "units": len(alive),
                "share_usd": share}

    def prices(self) -> dict[int, dict]:
        """Per unit lot: own parts, step costs, origin share and the total."""
        fees = self.own_step_costs(set(self.lots))
        origins = {rid: self.origin(rid) for rid in {lot.origin_run_id for lot in self.lots.values()
                                                     if not lot.found and lot.origin_run_id}}
        out = {}
        for lid, lot in self.lots.items():
            share = 0.0 if lot.found else ((origins.get(lot.origin_run_id) or {}).get("share_usd") or 0.0)
            own, fee = self.own_parts(lid), fees.get(lid, 0.0)
            out[lid] = {"own_parts_usd": own, "step_costs_usd": fee, "origin_share_usd": share,
                        "total_usd": own + fee + share}
        return out
