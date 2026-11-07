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
    """`L123` = purchase line 123, `A7` = stored lot 7 (a lot a positive
    adjustment made: a count, found units, a make's output)."""
    return f"{kind}{ident}"


def key_of(lot_line_id: int | None, lot_id: int | None) -> str | None:
    """The key of a binding's lot, or None when it names none."""
    return _lot_key("L", lot_line_id) if lot_line_id else _lot_key("A", lot_id) if lot_id else None


def lot_state(db: Session, as_of: str | None = None) -> dict:
    """Per-lot and per-part state, replayed from the shared event list.

    Returns `{"lots": {key: {...}}, "parts": {identity: {...}}}`.

    A lot is a purchase line, or a stored lot: the one a POSITIVE adjustment
    made, which is real priced stock with no purchase behind it —
    `opening_balance` rows do exactly that, and leaving them out would make every
    draw against opening stock permanently unallocatable.
    """
    # Transfers included: a transfer's position is a lot (decision 0064).
    events, doc_by_id, surcharge = run_actuals._pool_events(db, with_transfers=True)
    # A transformation's output lot also carries its conversion cost (decision
    # 0058 §4), added on read exactly like a purchase's freight share.
    extras = run_actuals.conversion_extras_usd(db)

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
        elif kind == "adj" and (row.qty or 0) > 0 and row.lot_id:
            key = _lot_key("A", row.lot_id)
            qty = row.qty or 0.0
            value = qty * (row.unit_cost_usd or 0.0) + extras.get(row.id, 0.0)
            lots[key] = {
                "key": key, "kind": "stock", "id": row.lot_id, "adjustment_id": row.id,
                "date": when, "lcsc": row.lcsc or "", "mpn": row.mpn or "",
                "component_id": row.component_id,
                "lot_ref": "", "document_id": None,
                "qty_bought": qty,
                "unit_cost_usd": round(value / qty, 8) if qty else 0.0,
                "value_bought": round(value, 6),
                "qty_assigned": 0.0, "value_assigned": 0.0,
                "unknown_rate": False,
                "reason": row.reason or "",
            }

    # Bindings are counted over ALL of them, not just those dated before `as_of`.
    # A lot consumed by a June draw is not available to a February backfill, and
    # windowing the assignments would hand the same stock out twice. A VOIDED
    # draw took nothing — the pool replay skips it — so its bindings free their
    # lots (as `process._bound_rows` reads them).
    for b in (db.query(M.MaterialMoveLot)
              .join(M.Draw, M.Draw.id == M.MaterialMoveLot.move_id)
              .filter(M.Draw.voided_at.is_(None)).all()):
        key = key_of(b.lot_line_id, b.lot_id)
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
    bound = {m for (m,) in db.query(M.MaterialMoveLot.move_id).all()}
    out = []
    for c in run_actuals.live_consumption(db).order_by(M.Draw.id).all():
        if c.id in bound:
            continue
        out.append({
            "id": c.id, "run_id": c.run_id, "lcsc": c.lcsc, "mpn": c.mpn,
            "qty": c.taken, "unit_cost_usd": c.unit_cost_usd,
            "value_usd": round(c.taken * (c.unit_cost_usd or 0), 4),
            "basis": c.basis, "consumed_at": c.at,
        })
    return out


def coverage(db: Session) -> dict:
    """How much of the drawn value is lot-attributed. This is the number that
    tells you whether lot accounting can safely become the pricing authority —
    it should approach 100% before `avg_usd` is switched over."""
    state = lot_state(db)
    total_drawn = 0.0
    for c in run_actuals.live_consumption(db).all():
        total_drawn += c.taken * (c.unit_cost_usd or 0)
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
        key = key_of(b.get("lot_line_id"), b.get("lot_id"))
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


# ======================================== what a draw holds (0073, 0105)


def bound_on(db: Session, *, line_ids=(), lot_ids=()) -> dict[str, tuple[float, list[int]]]:
    """Lot key → (units live draws hold of it, those draws' ids): what a
    change to the lot's purchase or adjustment must leave them (decision 0073)."""
    out: dict[str, tuple[float, list[int]]] = {}
    for col, kind, ids in ((M.MaterialMoveLot.lot_line_id, "L", list(line_ids)),
                           (M.MaterialMoveLot.lot_id, "A", list(lot_ids))):
        if not ids:
            continue
        for lot_id, q, cid in (db.query(col, M.MaterialMoveLot.qty, M.Draw.id)
                               .join(M.Draw, M.Draw.id == M.MaterialMoveLot.move_id)
                               .filter(col.in_(ids), M.Draw.voided_at.is_(None)).all()):
            q0, ds = out.get(_lot_key(kind, lot_id), (0.0, []))
            out[_lot_key(kind, lot_id)] = (q0 + (q or 0.0), sorted({*ds, cid}))
    return out


def lot_line(db: Session, li: M.RunCostLine | None) -> dict | None:
    """The lot an invoice position is, as the draws bound to it need it, or
    None when it is no lot: voided, out of the pool, a split header, or a
    conversion cost (decision 0073)."""
    if li is None or li.voided_at is not None or li.transformation_id is not None \
            or not run_actuals.pooled_part_lines(db, [li]):
        return None
    if db.query(M.RunCostLine.id).filter(M.RunCostLine.parent_line_id == li.id,
                                         M.RunCostLine.voided_at.is_(None)).first():
        return None
    doc = db.get(M.RunCostDocument, li.document_id)
    return {"qty": float(li.qty or 0.0), "date": doc.doc_date or "",
            "scope": run_actuals.stock_scope(db, doc.company_id),
            "keys": set(run_actuals._identity_keys(li.component_id, li.mpn or "", li.lcsc or ""))}


def bound_snapshot(db: Session, line_ids) -> dict[int, dict]:
    """For each of these positions that live draws are bound to: the lot it
    is now and the draws on it. `bound_problems` reads it after a change."""
    out: dict[int, dict] = {}
    rows = (db.query(M.MaterialMoveLot.lot_line_id, M.MaterialMoveLot.qty, M.Draw)
            .join(M.Draw, M.Draw.id == M.MaterialMoveLot.move_id)
            .filter(M.MaterialMoveLot.lot_line_id.in_(list(line_ids) or [-1]),
                    M.Draw.voided_at.is_(None)).all())
    for lid, q, c in rows:
        e = out.setdefault(lid, {"held": 0.0, "draws": {}})
        e["held"] += q or 0.0
        e["draws"][c.id] = {"date": c.at or "", "scope": run_actuals.stock_scope(db, c.company_id),
                            "keys": set(run_actuals._identity_keys(c.component_id, c.mpn or "", c.lcsc or ""))}
    for lid, e in out.items():
        e["lot"] = lot_line(db, db.get(M.RunCostLine, lid))
        e["label"] = (db.get(M.RunCostLine, lid).label or db.get(M.RunCostLine, lid).mpn
                      or db.get(M.RunCostLine, lid).lcsc or f"line {lid}")
    return out


def bound_problems(db: Session, snap: dict[int, dict]) -> list[str]:
    """What a change did to the lots in `snap` that their draws cannot keep:
    the position is no lot any more, keeps fewer units than they hold, is
    dated after them, belongs to another company's stock, or is another part.
    Only what the change made: a problem the lot already had is no reason."""
    out = []
    for lid, e in snap.items():
        was, now = e["lot"], lot_line(db, db.get(M.RunCostLine, lid))
        ids = ", ".join(f"#{d}" for d in sorted(e["draws"])[:4])
        if now is None:
            if was is not None:
                out.append(f"{e['label']} would be no lot any more, and draws {ids} hold {e['held']:g} of it")
            continue
        why = []
        if now["qty"] < e["held"] - CLOSED_EPS and (was is None or was["qty"] >= e["held"] - CLOSED_EPS
                                                    or now["qty"] < was["qty"] - CLOSED_EPS):
            why.append(f"keeps {now['qty']:g} of the {e['held']:g} they hold")
        if any(d["date"] and now["date"] > d["date"] for d in e["draws"].values()) and not (
                was is not None and any(d["date"] and was["date"] > d["date"] for d in e["draws"].values())):
            why.append("is dated after them")
        if any(d["scope"] != now["scope"] for d in e["draws"].values()) and not (
                was is not None and any(d["scope"] != was["scope"] for d in e["draws"].values())):
            why.append("belongs to another company's stock")
        if any(not (d["keys"] & now["keys"]) for d in e["draws"].values()) and not (
                was is not None and any(not (d["keys"] & was["keys"]) for d in e["draws"].values())):
            why.append("is another part")
        if why:
            out.append(f"{e['label']} {' and '.join(why)} — draws {ids} are bound to it")
    return out


def stock_before(db: Session, doc_ids, extra=(), new_company_id: int | None = None) -> dict:
    """What the draws hold of these documents' lots and part pools, before an
    invoice edit; `stock_problems` compares after it (decisions 0040, 0064,
    0073). The field guards check the fields they know; this checks what any
    edit did, whatever moved it — a step, a proforma, a date, a buyer, a
    re-split, a deletion, a JLC refresh. `extra` is `(line, document)` pairs
    for what the edit is about to write — a new line, or a line's new part —
    so a credit (a negative stock line) is compared too. `new_company_id` is a
    new buyer: its pool is compared as well, as the stock a credit enters."""
    lines = db.query(M.RunCostLine).filter(M.RunCostLine.document_id.in_(list(doc_ids) or [-1])).all()
    entries = []
    for li, doc in [(li, db.get(M.RunCostDocument, li.document_id)) for li in lines] + list(extra):
        if not run_actuals.is_stock(li):
            continue
        scopes = {run_actuals.stock_scope(db, doc.company_id if doc else None)}
        if new_company_id:
            scopes.add(run_actuals.stock_scope(db, new_company_id))
        entries += [(sc, li.component_id, li.mpn or "", li.lcsc or "", li.mpn or li.lcsc or "") for sc in scopes]
    targets, names = run_actuals.stock_targets(db, entries)
    return {"lots": bound_snapshot(db, [li.id for li in lines]), "targets": targets, "names": names,
            "pools": run_actuals.stock_view(db, targets) if targets else {}}


def stock_problems(db: Session, before: dict) -> list[str]:
    """What an invoice edit, written but not committed, did that the draws
    cannot keep: a bound lot broken (`bound_problems`), or a part's pool below
    zero and below where it was, on any day (`run_actuals.stock_worse`)."""
    db.flush()
    out = bound_problems(db, before["lots"])
    if before["targets"]:
        out += run_actuals.stock_worse(before["pools"], run_actuals.stock_view(db, before["targets"]),
                                       before["names"])
    return out


def resize_bound(db: Session, c: M.Draw, qty: float) -> None:
    """A draw's quantity is about to change. Less gives back its newest bindings
    first, so no draw holds more lots than units, and a draw whose price is its
    lots' price takes the price of the lots it still holds. More binds nothing:
    the added units come from the pool at its average, and nothing guesses which
    lot they were (decision 0105)."""
    rows = db.query(M.MaterialMoveLot).filter_by(move_id=c.id).order_by(M.MaterialMoveLot.id).all()
    held = [b for b in rows if b.lot_line_id or b.lot_id]
    have = sum(b.qty or 0.0 for b in held)
    if qty >= have - CLOSED_EPS:
        return
    lot_priced = abs(c.taken - have) <= CLOSED_EPS and abs(
        (c.unit_cost_usd or 0.0) - sum((b.qty or 0.0) * (b.unit_cost_usd or 0.0) for b in held) / have) <= 1e-6
    give = have - qty
    for b in reversed(rows):
        if give <= CLOSED_EPS:
            break
        take = min(b.qty or 0.0, give)
        give -= take
        if (b.qty or 0.0) - take <= CLOSED_EPS:
            db.delete(b)
        else:
            b.qty = (b.qty or 0.0) - take
    db.flush()
    if lot_priced:
        live = [b for b in db.query(M.MaterialMoveLot).filter_by(move_id=c.id) if b.lot_line_id or b.lot_id]
        total = sum(b.qty or 0.0 for b in live)
        if total > CLOSED_EPS:
            c.unit_cost_usd = round(sum((b.qty or 0.0) * (b.unit_cost_usd or 0.0) for b in live) / total, 8)
