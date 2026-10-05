"""In-house stock transfers between our two companies (decision 0064).

A transfer is how stock that one company bought reaches a batch of the other.
It is an internal record, never filed with any office (user, 2026-10-04): no
invoice is issued and no money moves. Two rows say it:

* a **document** with `doc_type="transfer"`, billed to the RECEIVER
  (`company_id`) and naming the SENDER (`counterparty_company_id`). Its stock
  positions are ordinary purchases in the receiver's stock — each is a lot;
* one **draw** per position from the SENDER's stock, charged to no batch and
  pointing at the position (`transfer_line_id`).

The price is the sender's moving average on the transfer date, or the landed
cost of the lot the units came from when that is known. While `lot_pricing`
is on (decision 0073) a line that names no lot takes the sender's lots oldest
first: its sender draw is bound to them and the position carries their
weighted cost, and a line the lots cannot cover is refused. Either way the two
sides carry the same value, so the companies' totals together stay what they
were before the transfer. The register keeps transfers out of every money
total (`run_actuals.invoice_register`).

Transfers ignore the `stock_per_company` switch: they are the records that
make the switch possible, so they always replay each company on its own. In
the one shared pool (switch off, or the "all companies" view) a transfer moves
nothing, and `run_actuals._pool_events` leaves both sides out.

A transfer that names a LOT also moves the receiver's draws bound to that lot
onto its own position (a "rebind"): those draws took the sender's purchase
before the transfer existed, and leaving them bound to it would count the lot
twice. `cover_draws` is the same move for draws that are about to become a
batch's: units bound to another company's lot reach the batch's company by
transfer first.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from . import companies as C
from . import lots as L
from . import run_actuals as RA

BASIS_TRANSFER = "transfer"
STEP = "parts:pool"
EPS = 1e-6


def _today() -> str:
    return date.today().isoformat()


def number_for(db: Session, day: str) -> str:
    """The next in-house number of the year: MM 0001/2026 (MM = a stock move
    between our own stores)."""
    year = (day or _today())[:4]
    n = (db.query(M.RunCostDocument)
         .filter(M.RunCostDocument.doc_type == "transfer",
                 M.RunCostDocument.doc_number.like(f"MM %/{year}")).count())
    return f"MM {n + 1:04d}/{year}"


def _lot_key(lot_line_id: int | None, lot_adjustment_id: int | None) -> str | None:
    if lot_line_id:
        return f"L{lot_line_id}"
    return f"A{lot_adjustment_id}" if lot_adjustment_id else None


def _lot_unit(db: Session, lot_line_id: int | None, lot_adjustment_id: int | None) -> float | None:
    key = _lot_key(lot_line_id, lot_adjustment_id)
    if key is None:
        return None
    lot = L.lot_state(db)["lots"].get(key)
    return lot["unit_cost_usd"] if lot else None


def lot_company(db: Session, lot_line_id: int | None, lot_adjustment_id: int | None) -> int | None:
    """The company whose stock a lot is: the buyer of the purchase, or the
    company stamped on a positive adjustment."""
    if lot_line_id:
        li = db.get(M.RunCostLine, lot_line_id)
        doc = db.get(M.RunCostDocument, li.document_id) if li is not None else None
        return doc.company_id if doc is not None else None
    if lot_adjustment_id:
        a = db.get(M.ComponentStockAdjustment, lot_adjustment_id)
        return a.company_id if a is not None else None
    return None


def _auto_rebind(db: Session, receiver_id: int, day: str, lot_line_id: int | None,
                 lot_adjustment_id: int | None, qty: float) -> list[dict]:
    """The receiver's draws bound to a lot that moves, oldest first, up to the
    moved quantity. Only draws on or after the transfer date: a draw before it
    took the lot while it was still the sender's."""
    q = db.query(M.ComponentConsumptionLot)
    q = (q.filter(M.ComponentConsumptionLot.lot_line_id == lot_line_id) if lot_line_id
         else q.filter(M.ComponentConsumptionLot.lot_adjustment_id == lot_adjustment_id))
    picks, left = [], qty
    found = []
    for b in q.all():
        c = db.get(M.ComponentConsumption, b.consumption_id)
        if (c is None or c.voided_at is not None or c.transfer_line_id is not None
                or c.company_id != receiver_id or (c.consumed_at or "9999") < day):
            continue
        found.append((c.consumed_at or "9999", b.id, b))
    for _d, _id, b in sorted(found, key=lambda e: (e[0], e[1])):
        if left <= EPS:
            break
        take = min(b.qty or 0.0, left)
        if take > EPS:
            picks.append({"binding_id": b.id, "qty": take})
            left -= take
    return picks


def free_positions(db: Session, receiver_id: int, component_id, mpn: str, lcsc: str,
                   lot_key: str | None, day: str) -> list[dict]:
    """Written transfers into `receiver_id` that moved this part on or before
    `day` and that no draw is bound to yet, in full or in part: the stock a
    later draw of the receiver may already have come by. Positions whose
    sender draw took the same lot come first, then positions that named no
    lot (the Transfers page names none), oldest first."""
    want = set(RA._identity_keys(component_id, mpn or "", lcsc or ""))
    if not want:
        return []
    out = []
    docs = (db.query(M.RunCostDocument)
            .filter(M.RunCostDocument.doc_type == "transfer", M.RunCostDocument.company_id == receiver_id,
                    M.RunCostDocument.doc_date <= (day or "9999")).all())
    for doc in docs:
        for li in doc.lines:
            if li.voided_at is not None or not (set(RA._identity_keys(li.component_id, li.mpn or "",
                                                                       li.lcsc or "")) & want):
                continue
            sender = RA.live_consumption(db).filter(M.ComponentConsumption.transfer_line_id == li.id).first()
            if sender is None:
                continue
            sender_lots = {_lot_key(b.lot_line_id, b.lot_adjustment_id)
                           for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=sender.id)}
            if sender_lots and lot_key not in sender_lots:
                continue   # it moved another lot
            bound = sum(b.qty or 0.0 for b in db.query(M.ComponentConsumptionLot).filter_by(lot_line_id=li.id))
            free = (li.qty or 0.0) - bound
            if free > EPS:
                out.append({"line_id": li.id, "free": free, "date": doc.doc_date or "",
                            "doc_number": doc.doc_number, "same_lot": bool(sender_lots),
                            "sender_draw_id": sender.id, "unit_cost_usd": li.unit_price})
    return sorted(out, key=lambda x: (not x["same_lot"], x["date"], x["line_id"]))


def _absorb(db: Session, b: M.ComponentConsumptionLot, c: M.ComponentConsumption, receiver_id: int,
            claimed: dict[int, float]) -> list[dict]:
    """How much of binding `b` (a receiver draw's binding to another company's
    lot) written transfers already moved: `[{line_id, qty, ...}]`. `claimed`
    holds what earlier bindings of the same operation took from each
    position."""
    takes, left = [], b.qty or 0.0
    for pos in free_positions(db, receiver_id, c.component_id, c.mpn, c.lcsc,
                              _lot_key(b.lot_line_id, b.lot_adjustment_id), (c.consumed_at or _today())[:10]):
        if left <= EPS:
            break
        free = pos["free"] - claimed.get(pos["line_id"], 0.0)
        take = min(free, left)
        if take > EPS:
            claimed[pos["line_id"]] = claimed.get(pos["line_id"], 0.0) + take
            takes.append({**pos, "binding_id": b.id, "qty": take})
            left -= take
    return takes


def apply_absorb(db: Session, take: dict) -> None:
    """Move part of a binding onto a written transfer's position. When that
    transfer named no lot, its sender draw takes the lot the binding leaves,
    so the lot ledger counts the units once."""
    b = db.get(M.ComponentConsumptionLot, take["binding_id"])
    if b is None:
        return
    qty = min(take["qty"], b.qty or 0.0)
    lot_line_id, lot_adjustment_id = b.lot_line_id, b.lot_adjustment_id
    if (b.qty or 0.0) - qty > EPS:
        db.add(M.ComponentConsumptionLot(consumption_id=b.consumption_id, lot_line_id=take["line_id"], qty=qty,
                                         unit_cost_usd=b.unit_cost_usd, source=b.source or "manual",
                                         note=f"{b.note or ''} → {take['doc_number']}"[:500]))
        b.qty = (b.qty or 0.0) - qty
    else:
        b.lot_line_id, b.lot_adjustment_id = take["line_id"], None
        b.note = f"{b.note or ''} → {take['doc_number']}"[:500]
    if not take["same_lot"]:
        db.add(M.ComponentConsumptionLot(consumption_id=take["sender_draw_id"], lot_line_id=lot_line_id,
                                         lot_adjustment_id=lot_adjustment_id, qty=qty,
                                         unit_cost_usd=take["unit_cost_usd"], source="manual",
                                         note=f"{take['doc_number']}: the lot it moved"[:500]))
    db.flush()


def _sender_picker(db: Session, sender_id: int, out_lines: list[dict], exclude_draw_ids=()) -> L.FifoPicker:
    """The sender's lots for the lines that name none (decision 0073).

    The bindings of the draws about to move (`exclude_draw_ids`) go back to
    their lots, as `check_shortages` leaves those draws out. Every lot a line
    of this transfer names is then taken first: its full quantity, less the
    bindings of draws that stay and move onto the new position — the same net
    figure the lot capacity check uses."""
    state = L.lot_state(db)
    excl = {int(i) for i in exclude_draw_ids or ()}
    if excl:
        for b in db.query(M.ComponentConsumptionLot).filter(M.ComponentConsumptionLot.consumption_id.in_(excl)):
            lot = state["lots"].get(_lot_key(b.lot_line_id, b.lot_adjustment_id))
            if lot is not None:
                lot["qty_remaining"] = lot["qty_remaining"] + (b.qty or 0.0)
    picker = L.FifoPicker(db, sender_id, state=state)
    for x in out_lines:
        key = _lot_key(x["lot_line_id"], x["lot_adjustment_id"])
        if key is None:
            continue
        stay = 0.0
        for r in x["rebind"]:
            b = db.get(M.ComponentConsumptionLot, r["binding_id"])
            if b is not None and r.get("lot") == key and b.consumption_id not in excl:
                stay += r["qty"] or 0.0
        picker.taken[key] += max(x["qty"] - stay, 0.0)
    return picker


def _rebinds(ln: dict) -> list[dict]:
    """A line's rebinds as `{binding_id, qty}`; `qty` None = the whole binding."""
    out = [{"binding_id": int(bid), "qty": None} for bid in ln.get("rebind_ids") or []]
    out += [{"binding_id": int(r["binding_id"]), "qty": r.get("qty")} for r in ln.get("rebind") or []]
    return out


def plan(db: Session, *, sender_id: int, receiver_id: int, day: str, lines: list[dict],
         exclude_draw_ids=()) -> dict:
    """Price and check a transfer. Each line is `{component_id?, mpn?, lcsc?,
    qty, unit_cost_usd?, lot_line_id?, lot_adjustment_id?, rebind_ids?,
    rebind?}`. `rebind_ids` (whole bindings) and `rebind` (`{binding_id, qty}`)
    are lot bindings of the receiver's draws that move from the sender's lot
    onto the new position. A line that names a lot and gives neither gets them
    found: the receiver's draws bound to that lot from the transfer date on.

    `exclude_draw_ids` are draws about to move to the receiver
    (`cover_draws`): the sender's stock is checked without them.

    While `lot_pricing` is on, a line that names no lot takes the sender's
    lots oldest first (decision 0073): it gets `bindings`, and its price is
    their weighted cost, whatever price the caller stated. A line the lots
    cannot cover in full is a problem."""
    if sender_id == receiver_id:
        raise HTTPException(422, "a transfer goes from one company to the OTHER")
    sender, receiver = C.get(db, sender_id), C.get(db, receiver_id)
    day = (day or _today())[:10]
    out_lines, problems = [], []
    fifo_lines: list[tuple[int, dict]] = []   # (input line, its entry) priced from the lots below
    lots_named: set[str] = set()
    claimed: dict[int, float] = defaultdict(float)   # binding -> qty rebound by earlier lines
    for i, ln in enumerate(lines):
        qty = float(ln.get("qty") or 0)
        if qty <= 0:
            problems.append({"line": i, "problem": "move at least one unit"})
            continue
        lot_line_id, lot_adjustment_id = ln.get("lot_line_id"), ln.get("lot_adjustment_id")
        if lot_line_id and lot_adjustment_id:
            problems.append({"line": i, "problem": "name one lot, a purchase line or an adjustment"})
            continue
        if _lot_key(lot_line_id, lot_adjustment_id):
            owner = lot_company(db, lot_line_id, lot_adjustment_id)
            if owner is not None and owner != sender.id:
                problems.append({"line": i, "problem": f"that lot is not {sender.name}'s stock"})
                continue
            if _lot_key(lot_line_id, lot_adjustment_id) in lots_named:
                problems.append({"line": i, "problem": "name each lot once in a transfer"})
                continue
            lots_named.add(_lot_key(lot_line_id, lot_adjustment_id))
        unit = ln.get("unit_cost_usd")
        source = "stated"
        if unit is None:
            unit = _lot_unit(db, lot_line_id, lot_adjustment_id)
            source = "the lot's landed cost"
        entry = RA.resolve_pool_identity(db, ln.get("component_id"), ln.get("mpn") or "",
                                         ln.get("lcsc") or "", as_of=day, company_id=sender.id)
        if unit is None:
            unit = (entry or {}).get("avg_usd")
            source = f"{sender.name}'s average on {day}"
        if entry is None and not lot_line_id and not lot_adjustment_id:
            problems.append({"line": i, "problem": f"{sender.name} never held this part",
                             "mpn": ln.get("mpn"), "component_id": ln.get("component_id")})
            continue
        rebind = _rebinds(ln)
        if (not rebind and "rebind_ids" not in ln and "rebind" not in ln
                and _lot_key(lot_line_id, lot_adjustment_id)):
            rebind = _auto_rebind(db, receiver.id, day, lot_line_id, lot_adjustment_id, qty)
        for r in rebind:
            b = db.get(M.ComponentConsumptionLot, r["binding_id"])
            if b is None:
                problems.append({"line": i, "problem": f"no lot binding {r['binding_id']}"})
                continue
            if r["qty"] is None:
                r["qty"] = b.qty or 0.0
            r["lot"] = _lot_key(b.lot_line_id, b.lot_adjustment_id)
            claimed[b.id] += r["qty"]
            if claimed[b.id] > (b.qty or 0.0) + EPS:
                problems.append({"line": i, "problem": f"binding {b.id} holds {b.qty}, "
                                                        f"not {round(claimed[b.id], 6)}"})
        if sum(r["qty"] or 0.0 for r in rebind) > qty + EPS:
            problems.append({"line": i, "problem": "more draws rebound than units moved"})
        out_lines.append({
            "component_id": (entry or {}).get("component_id") or ln.get("component_id"),
            "mpn": (entry or {}).get("mpn") or ln.get("mpn") or "",
            "lcsc": (entry or {}).get("lcsc") or ln.get("lcsc") or "",
            "qty": qty, "unit_cost_usd": round(float(unit or 0.0), 8), "price_source": source,
            "value_usd": round(qty * float(unit or 0.0), 4),
            "lot_line_id": lot_line_id, "lot_adjustment_id": lot_adjustment_id,
            "rebind": rebind, "label": ln.get("label") or "",
        })
        if L.lot_pricing_on() and not _lot_key(lot_line_id, lot_adjustment_id):
            fifo_lines.append((i, out_lines[-1]))
    if fifo_lines:
        # Decision 0073: after every named lot is taken, the lines that name
        # none take the sender's lots oldest first, sharing one picker.
        picker = _sender_picker(db, sender.id, out_lines, exclude_draw_ids)
        for i, x in fifo_lines:
            uncovered = L.fifo_price(db, [x], as_of=day, company_id=sender.id, picker=picker)
            if uncovered:
                out_lines[:] = [y for y in out_lines if y is not x]
                problems.append({"line": i, "mpn": x["mpn"], "component_id": x["component_id"],
                                 "uncovered": uncovered[0]["uncovered"],
                                 "problem": f"{x['label'] or x['mpn'] or x['lcsc']}: {uncovered[0]['uncovered']:g} "
                                            f"of {x['qty']:g} are in no lot of {sender.name} on {day} — enter the "
                                            "purchase first (decision 0073)"})
                continue
            x["unit_cost_usd"] = round(float(x["unit_cost_usd"] or 0.0), 8)
            x["price_source"] = f"{sender.name}'s lots, oldest first"
    shortages = RA.check_shortages(db, [
        {"component_id": x["component_id"], "mpn": x["mpn"], "lcsc": x["lcsc"], "qty": x["qty"],
         "date": day, "label": x["label"] or x["mpn"]} for x in out_lines], company_id=sender.id,
        exclude_draw_ids=exclude_draw_ids)
    # A lot the sender's draw binds to must hold it — less what the receiver's
    # draws already took from THAT lot and now move onto the new position.
    capacity_want = []
    for x in out_lines:
        key = _lot_key(x["lot_line_id"], x["lot_adjustment_id"])
        if key is None:
            continue
        need = x["qty"] - sum(r["qty"] or 0.0 for r in x["rebind"] if r.get("lot") == key)
        if need > EPS:
            capacity_want.append({"lot_line_id": x["lot_line_id"],
                                  "lot_adjustment_id": x["lot_adjustment_id"], "qty": need})
    capacity = L.check_lot_capacity(db, capacity_want)
    return {"sender_id": sender.id, "sender": sender.name, "receiver_id": receiver.id,
            "receiver": receiver.name, "date": day, "lines": out_lines,
            "value_usd": round(sum(x["value_usd"] for x in out_lines), 4),
            "shortages": shortages, "lot_capacity": capacity, "problems": problems}


def create(db: Session, *, sender_id: int, receiver_id: int, day: str, lines: list[dict],
           run_id: int | None = None, note: str = "", actor: str = "",
           dry_run: bool = True) -> dict:
    """Write one transfer: the receiver's document and the sender's draws.
    Dry run by default; refused while the sender does not hold the stock."""
    p = plan(db, sender_id=sender_id, receiver_id=receiver_id, day=day, lines=lines)
    p["dry_run"] = dry_run
    if run_id is not None:
        run = db.get(M.ProductionRun, run_id)
        if run is None:
            raise HTTPException(404, "no such batch")
        if run.company_id and run.company_id != receiver_id:
            raise HTTPException(422, f"{run.label} belongs to the other company, not the receiver")
    if dry_run:
        return p
    if p["problems"] or p["shortages"] or p["lot_capacity"]:
        raise HTTPException(409, {"error": f"{p['sender']} does not hold this stock on {p['date']} "
                                           "— enter the missing purchase or move fewer units",
                                  "plan": p})
    if not p["lines"]:
        raise HTTPException(422, "nothing to move")
    doc = M.RunCostDocument(
        doc_type="transfer", supplier=p["sender"], doc_number=number_for(db, p["date"]),
        doc_date=p["date"], currency="USD", total_amount=p["value_usd"],
        company_id=receiver_id, company_source="transfer", counterparty_company_id=sender_id,
        run_id=run_id,
        notes=(f"In-house transfer {p['sender']} → {p['receiver']}, never filed (decision 0064). "
               + (note or ""))[:2000])
    db.add(doc)
    db.flush()
    for pos, x in enumerate(p["lines"]):
        li = M.RunCostLine(document_id=doc.id, plan_key=STEP, allocate=RA.POOLED,
                           component_id=x["component_id"], mpn=x["mpn"], lcsc=x["lcsc"],
                           label=x["label"] or x["mpn"] or x["lcsc"], qty=x["qty"],
                           unit_price=x["unit_cost_usd"], currency="USD", position=pos,
                           notes=f"price: {x['price_source']}")
        db.add(li)
        db.flush()
        out = M.ComponentConsumption(
            run_id=None, component_id=x["component_id"], mpn=x["mpn"], lcsc=x["lcsc"],
            qty=x["qty"], unit_cost_usd=x["unit_cost_usd"], basis=BASIS_TRANSFER,
            consumed_at=p["date"], company_id=sender_id, transfer_line_id=li.id,
            note=f"sent to {p['receiver']} on {doc.doc_number}"[:500])
        db.add(out)
        db.flush()
        if x["lot_line_id"] or x["lot_adjustment_id"]:
            db.add(M.ComponentConsumptionLot(
                consumption_id=out.id, lot_line_id=x["lot_line_id"],
                lot_adjustment_id=x["lot_adjustment_id"], qty=x["qty"],
                unit_cost_usd=x["unit_cost_usd"], source="manual", note=doc.doc_number))
        elif x.get("bindings"):
            # The sender's lots the line took, oldest first (decision 0073).
            L.bind(db, out, x)
        for r in x["rebind"]:
            b = db.get(M.ComponentConsumptionLot, r["binding_id"])
            if b is None:
                continue
            take = r["qty"] if r["qty"] is not None else (b.qty or 0.0)
            if take > (b.qty or 0.0) + EPS:
                raise HTTPException(409, f"binding {b.id} holds {b.qty}, not {take}")
            if (b.qty or 0.0) - take > EPS:
                # Part of the binding moves: the rest stays on the sender's lot.
                db.add(M.ComponentConsumptionLot(
                    consumption_id=b.consumption_id, lot_line_id=li.id, qty=take,
                    unit_cost_usd=b.unit_cost_usd, source=b.source or "manual",
                    note=f"{b.note or ''} → {doc.doc_number}"[:500]))
                b.qty = (b.qty or 0.0) - take
            else:
                b.lot_line_id, b.lot_adjustment_id = li.id, None
                b.note = f"{b.note or ''} → {doc.doc_number}"[:500]
        x["line_id"] = li.id
        x["sender_draw_id"] = out.id
    db.flush()
    p["document_id"] = doc.id
    p["doc_number"] = doc.doc_number
    return p


def _short_text(rows: list[dict]) -> str:
    return ", ".join(f"{x.get('label') or x.get('lcsc') or x.get('mpn') or x.get('component_id')} "
                     f"short {x.get('short')}" for x in rows[:6]) + (" …" if len(rows) > 6 else "")


def cover_draws(db: Session, draws: list[M.ComponentConsumption], receiver_id: int, *,
                actor: str = "", note: str = "", dry_run: bool = True,
                extra: list[dict] | None = None) -> dict:
    """Make `draws` movements of the receiver's stock (decision 0064).

    A unit bound to another company's lot reaches the receiver by in-house
    transfer — a written one first (`free_positions`: its binding moves onto
    that position), else a new one at the lot's cost, dated with the draw,
    with the binding moved onto its position. Every other unit, and every unit
    a written transfer already gave, must be in the receiver's stock on the
    draw's date. Then each draw is stamped with the receiver. Refused (409),
    naming each short part and whose stock it is, when either side does not
    hold the stock.

    The charge of a JLC order to a batch (`jlc_apply.charge_draws`), the move of
    a batch to the other company (`move_batch_stock`) and a hand-named draw end
    here. `extra` are more takings from the receiver's stock checked in the
    same replay (the losses charged to a moving batch).
    """
    receiver = C.get(db, receiver_id)
    ids = [c.id for c in draws]
    groups: dict[tuple, list] = defaultdict(list)
    remainder, absorbed = [], []
    claimed: dict[int, float] = {}
    for c in draws:
        moved = 0.0
        day = (c.consumed_at or _today())[:10]
        for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id).all():
            src = lot_company(db, b.lot_line_id, b.lot_adjustment_id)
            if src is None or src == receiver.id or (b.qty or 0.0) <= EPS:
                continue
            takes = _absorb(db, b, c, receiver.id, claimed)
            absorbed += takes
            rest = (b.qty or 0.0) - sum(t["qty"] for t in takes)
            if rest > EPS:
                line = {"component_id": c.component_id, "mpn": c.mpn or "", "lcsc": c.lcsc or "",
                        "qty": rest, "unit_cost_usd": b.unit_cost_usd, "lot_line_id": b.lot_line_id,
                        "lot_adjustment_id": b.lot_adjustment_id, "label": c.lcsc or c.mpn or ""}
                if takes:
                    line["rebind"] = [{"binding_id": b.id, "qty": rest}]
                else:
                    line["rebind_ids"] = [b.id]
                groups[(src, day)].append(line)
                moved += rest
        # what a written transfer gave is in the receiver's stock already
        rest = (c.qty or 0.0) - moved
        if rest > EPS:
            remainder.append({"component_id": c.component_id, "mpn": c.mpn or "", "lcsc": c.lcsc or "",
                              "qty": rest, "date": c.consumed_at or "", "label": c.lcsc or c.mpn or ""})
    shortages = RA.check_shortages(db, remainder + list(extra or []), company_id=receiver.id,
                                   exclude_draw_ids=ids)
    plans = [plan(db, sender_id=src, receiver_id=receiver.id, day=day, lines=lines, exclude_draw_ids=ids)
             for (src, day), lines in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0]))]
    out = {"receiver_id": receiver.id, "receiver": receiver.name, "draws": len(draws),
           "transfers": plans, "absorbed": [{k: t[k] for k in ("binding_id", "qty", "doc_number")}
                                            for t in absorbed],
           "shortages": shortages, "dry_run": dry_run}
    blocked = [p for p in plans if p["problems"] or p["shortages"] or p["lot_capacity"]]
    if shortages or blocked:
        parts = []
        if shortages:
            parts.append(f"{receiver.name} does not hold {_short_text(shortages)}")
        for p in blocked:
            if p["shortages"]:
                parts.append(f"{p['sender']} does not hold {_short_text(p['shortages'])} on {p['date']}")
            for pr in p["problems"]:
                parts.append(f"{p['sender']}: {pr.get('problem')}")
            for lc in p["lot_capacity"]:
                parts.append(f"lot {lc.get('lot')} {lc.get('problem')} ({lc.get('wanted')} wanted)")
        out["error"] = "; ".join(parts) + " — enter the missing purchase or an in-house transfer first"
    if dry_run:
        return out
    if out.get("error"):
        raise HTTPException(409, {"error": out["error"], "plan": out})
    for c in draws:
        c.company_id = receiver.id
    db.flush()
    for t in absorbed:
        apply_absorb(db, t)
    out["written"] = []
    for (src, day), lines in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        res = create(db, sender_id=src, receiver_id=receiver.id, day=day, lines=lines,
                     actor=actor, note=note, dry_run=False)
        out["written"].append({"document_id": res["document_id"], "doc_number": res["doc_number"],
                               "value_usd": res["value_usd"]})
    return out


def move_batch_stock(db: Session, run: M.ProductionRun, company_id: int, *, actor: str = "") -> dict:
    """The stock side of moving a batch to the other company (decision 0064).

    Its draws, its process steps' draws and the losses charged to it become
    the new company's. While each company keeps its own stock that is
    `cover_draws` — the new company must hold what the batch took, and units of
    the old company's lots move by in-house transfer — and a FOUND unit charged
    to the batch leaves the old company's stock, which must not strand a draw."""
    step_ids = [sid for (sid,) in db.query(M.StepRun.id).filter(M.StepRun.run_id == run.id).all()]
    q = RA.live_consumption(db)
    draws = [c for c in q.all() if c.run_id == run.id or (c.step_run_id and c.step_run_id in step_ids)]
    adjs = db.query(M.ComponentStockAdjustment).filter_by(charge_run_id=run.id).all()
    out = {"draws": len(draws), "adjustments": len(adjs), "transfers": []}
    if RA.stock_scope(db, company_id) is not None:
        def cand(a, qty, cid=None):
            return {"component_id": a.component_id, "mpn": a.mpn or "", "lcsc": a.lcsc or "", "qty": qty,
                    "date": a.adjusted_at or "", "label": a.lcsc or a.mpn or "", "company_id": cid}
        found = [cand(a, a.qty_delta, run.company_id) for a in adjs if (a.qty_delta or 0) > 0 and run.company_id]
        # The old company loses the found units — and the batch's own draws
        # and losses, which leave with it, so they are not in its replay.
        stranded = RA.check_shortages(db, found, exclude_draw_ids=[c.id for c in draws],
                                      exclude_adjustment_ids=[a.id for a in adjs if (a.qty_delta or 0) < 0])
        if stranded:
            raise HTTPException(409, {"error": f"{run.label}'s found stock would leave its company's stock "
                                               "under draws that need it", "shortages": stranded})
        res = cover_draws(db, draws, company_id, actor=actor, note=f"{run.label} moved to the other company",
                          dry_run=False,
                          extra=[cand(a, -(a.qty_delta or 0), company_id) for a in adjs
                                 if (a.qty_delta or 0) < 0])
        out["transfers"] = res.get("written", [])
    for x in [*draws, *adjs]:
        x.company_id = company_id
    db.flush()
    return out


def reverse(db: Session, doc: M.RunCostDocument, *, reason: str, actor: str = "",
            dry_run: bool = True) -> dict:
    """Undo a transfer: its positions leave the receiver's stock and the
    sender's draws are voided. Refused while the receiver used what it got."""
    if doc.doc_type != "transfer":
        raise HTTPException(422, "that document is not an in-house transfer")
    if not (reason or "").strip():
        raise HTTPException(422, "say why the transfer is reversed")
    live = [li for li in doc.lines if li.voided_at is None]
    ids = [li.id for li in live]
    bound = (db.query(M.ComponentConsumptionLot)
             .join(M.ComponentConsumption, M.ComponentConsumption.id == M.ComponentConsumptionLot.consumption_id)
             .filter(M.ComponentConsumptionLot.lot_line_id.in_(ids or [0]),
                     M.ComponentConsumption.voided_at.is_(None)).all())
    sender_draws = {c.id for c in RA.live_consumption(db)
                    .filter(M.ComponentConsumption.transfer_line_id.in_(ids or [0])).all()}
    used = [b for b in bound if b.consumption_id not in sender_draws]
    losses = [{"component_id": li.component_id, "mpn": li.mpn or "", "lcsc": li.lcsc or "",
               "qty": li.qty or 0.0, "date": doc.doc_date or "", "label": li.label or li.mpn,
               "company_id": doc.company_id} for li in live]
    short = RA.check_purchase_loss(db, losses)
    out = {"dry_run": dry_run, "document_id": doc.id, "doc_number": doc.doc_number,
           "lines": len(live), "shortages": short,
           "used_by_draws": sorted({b.consumption_id for b in used})}
    if dry_run:
        return out
    if short or used:
        raise HTTPException(409, {"error": f"{doc.doc_number}: the receiver already used this stock "
                                           "— reverse those draws first", "plan": out})
    now = M.utcnow()
    for c in RA.live_consumption(db).filter(M.ComponentConsumption.transfer_line_id.in_(ids or [0])):
        for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id).all():
            db.delete(b)
        c.voided_at, c.void_reason = now, "transfer_reversed"
    for li in live:
        li.voided_at = now
    doc.notes = f"{doc.notes or ''}\nREVERSED {now.date().isoformat()} by {actor}: {reason}"[:2000]
    db.flush()
    return out


def transfer_json(db: Session, doc: M.RunCostDocument) -> dict:
    names = {c.id: c.name for c in C.all_companies(db)}
    live = [li for li in doc.lines if li.voided_at is None]
    return {"id": doc.id, "doc_number": doc.doc_number, "date": doc.doc_date,
            "sender_id": doc.counterparty_company_id, "sender": names.get(doc.counterparty_company_id),
            "receiver_id": doc.company_id, "receiver": names.get(doc.company_id),
            "run_id": doc.run_id, "reversed": not live and bool(doc.lines),
            "value_usd": round(sum((li.qty or 0) * (li.unit_price or 0) for li in live), 4),
            "lines": [{"id": li.id, "component_id": li.component_id, "mpn": li.mpn, "lcsc": li.lcsc,
                       "label": li.label, "qty": li.qty, "unit_cost_usd": li.unit_price,
                       "price": li.notes} for li in live],
            "notes": doc.notes}


def list_transfers(db: Session, company_ids: list[int] | None = None) -> list[dict]:
    q = db.query(M.RunCostDocument).filter(M.RunCostDocument.doc_type == "transfer")
    rows = q.order_by(M.RunCostDocument.doc_date.desc(), M.RunCostDocument.id.desc()).all()
    if company_ids is not None:
        rows = [d for d in rows if d.company_id in company_ids
                or d.counterparty_company_id in company_ids]
    return [transfer_json(db, d) for d in rows]


# ======================================================= the history (0064)

def plan_history(db: Session) -> dict:
    """The transfers the past needs, so each company holds what its batches
    drew. Read only.

    Each company's stock is replayed on its own, existing transfers included.
    Two kinds of evidence, strongest first:

    1. **The lot the draw is bound to** (JLC names the purchase each assembly
       order consumed). A lot of the other company moves at its landed cost,
       dated with the draw, and the draw's binding moves onto the transfer's
       position. A transfer already written that moved the part to the same
       company on or before the draw — the same lot, or no lot at all (the
       Transfers page names none) — and whose position no draw is bound to
       yet, moved it already: the binding moves onto that position
       (`rebinds`), and a transfer that named no lot gets the lot.
    2. **The other company's stock on the draw's date**, at its average, for
       the part of a draw its own company's stock could not give. The replay
       counts the lot moves of step 1 once: as a purchase of the receiver and
       a draw of the sender. The draw itself stays whole.

    One transfer per sender, receiving batch and date. A shortfall neither
    company covers stays short: it was short in the one shared pool too.
    """
    companies = C.all_companies(db)
    names = {c.id: c.name for c in companies}
    runs = {r.id: r for r in db.query(M.ProductionRun).all()}
    draws = {c.id: c for c in RA.live_consumption(db).all()}
    bindings = db.query(M.ComponentConsumptionLot).all()
    owner_cache: dict[str | None, int | None] = {}

    def lot_owner(b) -> int | None:
        key = _lot_key(b.lot_line_id, b.lot_adjustment_id)
        if key not in owner_cache:
            owner_cache[key] = lot_company(db, b.lot_line_id, b.lot_adjustment_id) if key else None
        return owner_cache[key]

    # 1. Lot evidence: a batch draw bound to the other company's lot. A
    # written transfer of that part into the draw's company, on or before the
    # draw, that no draw is bound to yet, moved it already (`free_positions`):
    # the binding is moved onto it, and nothing new is proposed.
    by_key: dict[tuple, dict] = {}
    undated: list = []
    rebinds: list[dict] = []
    claimed: dict[int, float] = {}
    for b in sorted(bindings, key=lambda b: ((draws.get(b.consumption_id) and
                                             draws[b.consumption_id].consumed_at) or "9999", b.id)):
        c = draws.get(b.consumption_id)
        if c is None or c.company_id is None or c.transfer_line_id:
            continue
        src = lot_owner(b)
        if src is None or src == c.company_id:
            continue
        if not c.consumed_at:
            # A transfer must be dated on or before its draw; with no date
            # there is nothing to date it by, so a person decides.
            undated.append(c)
            continue
        takes = _absorb(db, b, c, c.company_id, claimed)
        rebinds += [{**t, "consumption_id": c.id, "run_id": c.run_id} for t in takes]
        qty = (b.qty or 0.0) - sum(t["qty"] for t in takes)
        if qty <= EPS:
            continue
        key = (src, c.company_id, c.run_id, c.consumed_at)
        t = by_key.setdefault(key, {"sender_id": src, "receiver_id": c.company_id, "run_id": c.run_id,
                                    "date": c.consumed_at, "lines": [], "evidence": "lot"})
        line = {"component_id": c.component_id, "mpn": c.mpn or "", "lcsc": c.lcsc or "",
                "qty": qty, "unit_cost_usd": b.unit_cost_usd,
                "lot_line_id": b.lot_line_id, "lot_adjustment_id": b.lot_adjustment_id,
                "label": c.lcsc or c.mpn or "", "consumption_id": c.id}
        if not takes:
            line["rebind_ids"] = [b.id]
        else:
            line["rebind"] = [{"binding_id": b.id, "qty": qty}]
        t["lines"].append(line)

    # 2. Balance evidence: replay each company once, with the moves of step 1.
    moved: dict[tuple, list] = defaultdict(list)   # (company, identity) -> [(date, +in/-out)]
    for t in by_key.values():
        for ln in t["lines"]:
            ident = RA._key(SimpleNamespace(**ln))
            moved[(t["receiver_id"], ident)].append((t["date"], ln["qty"]))
            moved[(t["sender_id"], ident)].append((t["date"], -ln["qty"]))
    shortfalls = []
    for comp in companies:
        events, _docs, _s = RA._pool_events(db, comp.id)
        # (date, kind, identity, signed qty, the draw when it is one)
        timeline = []
        for d, kind, row in events:
            q = (row.qty or 0.0) if kind == "buy" else \
                (-(row.qty or 0.0) if kind == "use" else (row.qty_delta or 0.0))
            timeline.append(((d or "9999"), kind, RA._key(row), q, row if kind == "use" else None))
        for (cid, ident), v in moved.items():
            if cid == comp.id:
                for d, q in v:
                    timeline.append(((d or "9999"), "buy" if q > 0 else "use", ident, q, None))
        timeline.sort(key=lambda e: (e[0], e[1]))
        bal: dict[str, float] = defaultdict(float)
        for day, _kind, ident, q, row in timeline:
            bal[ident] += q
            if (row is not None and bal[ident] < -EPS and row.run_id
                    and not row.transfer_line_id and q < -EPS and day != "9999"):
                # The part of THIS draw its own company could not give.
                need = min(-q, -bal[ident])
                shortfalls.append({"company_id": comp.id, "key": ident, "date": day,
                                   "qty": need, "row": row})
                bal[ident] += need   # it arrives by transfer, if the other company held it

    # Each shortfall from the other company's stock, if it held the part then.
    from_balance: dict[tuple, dict] = {}
    unexplained = []
    taken: dict[tuple, float] = defaultdict(float)   # (sender, identity) -> moved out by step 2
    pools: dict[tuple, dict] = {}

    def pool_at(company_id: int, day: str) -> dict:
        if (company_id, day) not in pools:
            pools[(company_id, day)] = RA.pool_state(db, as_of=day, company_id=company_id)
        return pools[(company_id, day)]

    for sf in shortfalls:
        row = sf["row"]
        other = next((c for c in companies if c.id != sf["company_id"]), None)
        if other is None:
            continue
        p = pool_at(other.id, sf["date"]).get(sf["key"])
        lot_moves = sum(q for d, q in moved.get((other.id, sf["key"]), []) if (d or "") <= sf["date"])
        held = (p or {}).get("qty", 0.0) + lot_moves - taken[(other.id, sf["key"])]
        if p is None or held + EPS < sf["qty"]:
            run = runs.get(row.run_id)
            unexplained.append({"company": names.get(sf["company_id"]), "run_id": row.run_id,
                                "batch": run.label if run else None, "date": sf["date"],
                                "part": row.lcsc or row.mpn or row.component_id,
                                "short": round(sf["qty"], 4),
                                "other_company_held": round(max(held, 0.0), 4)})
            continue
        taken[(other.id, sf["key"])] += sf["qty"]
        key = (other.id, sf["company_id"], row.run_id, sf["date"])
        t = from_balance.setdefault(key, {"sender_id": other.id, "receiver_id": sf["company_id"],
                                          "run_id": row.run_id, "date": sf["date"], "lines": [],
                                          "evidence": "balance"})
        t["lines"].append({"component_id": p.get("component_id") or row.component_id,
                           "mpn": p.get("mpn") or row.mpn or "", "lcsc": p.get("lcsc") or row.lcsc or "",
                           "qty": round(sf["qty"], 6), "unit_cost_usd": round(p.get("avg_usd") or 0.0, 8),
                           "label": row.lcsc or row.mpn or "", "consumption_id": row.id,
                           "rebind_ids": []})

    transfers = sorted(list(by_key.values()) + list(from_balance.values()),
                       key=lambda t: (t["date"], t["run_id"] or 0, t["evidence"]))
    for t in transfers:
        t["sender"], t["receiver"] = names.get(t["sender_id"]), names.get(t["receiver_id"])
        run = runs.get(t["run_id"])
        t["batch"] = run.label if run else None
        t["value_usd"] = round(sum(ln["qty"] * (ln["unit_cost_usd"] or 0) for ln in t["lines"]), 4)
    for c in undated:
        run = runs.get(c.run_id)
        unexplained.append({"company": names.get(c.company_id), "run_id": c.run_id,
                            "batch": run.label if run else None, "date": "",
                            "part": c.lcsc or c.mpn or c.component_id, "short": c.qty,
                            "other_company_held": None, "why": "the draw has no date"})
    return {"transfers": transfers, "unexplained": unexplained,
            "rebinds": [{k: r[k] for k in ("binding_id", "qty", "line_id", "doc_number", "same_lot",
                                           "sender_draw_id", "unit_cost_usd", "consumption_id", "run_id")}
                        for r in rebinds],
            "totals": {"transfers": len(transfers), "rebinds": len(rebinds),
                       "lines": sum(len(t["lines"]) for t in transfers),
                       "from_lots": sum(len(t["lines"]) for t in transfers if t["evidence"] == "lot"),
                       "value_usd": round(sum(t["value_usd"] for t in transfers), 2),
                       "by_direction": _by_direction(transfers),
                       "unexplained": len(unexplained)}}


def _by_direction(transfers: list[dict]) -> dict[str, float]:
    out: dict[str, float] = defaultdict(float)
    for t in transfers:
        out[f"{t['sender']} → {t['receiver']}"] += t["value_usd"]
    return {k: round(v, 2) for k, v in out.items()}


def apply_history(db: Session, *, actor: str = "", dry_run: bool = True) -> dict:
    """Write the transfers `plan_history` proposes, oldest first. Each is
    re-planned and checked as it is written, so one that no longer holds is
    reported, not forced."""
    proposal = plan_history(db)
    if dry_run:
        return {"dry_run": True, **proposal}
    written, refused = [], []
    for r in proposal["rebinds"]:
        apply_absorb(db, r)
    for t in proposal["transfers"]:
        lines = [{k: v for k, v in ln.items() if k != "consumption_id"} for ln in t["lines"]]
        try:
            res = create(db, sender_id=t["sender_id"], receiver_id=t["receiver_id"], day=t["date"],
                         lines=lines, run_id=t["run_id"], actor=actor, dry_run=False,
                         note=f"history (evidence: {t['evidence']})")
            written.append({"document_id": res["document_id"], "doc_number": res["doc_number"],
                            "batch": t["batch"], "value_usd": res["value_usd"]})
        except HTTPException as exc:
            refused.append({"batch": t["batch"], "date": t["date"], "why": exc.detail})
    return {"dry_run": False, "written": written, "refused": refused, "rebound": len(proposal["rebinds"]),
            "unexplained": proposal["unexplained"], "totals": proposal["totals"]}
