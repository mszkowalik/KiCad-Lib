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
cost of the lot the units came from when that is known. Either way the two
sides carry the same value, so the companies' totals together stay what they
were before the transfer. The register keeps transfers out of every money
total (`run_actuals.invoice_register`).

Transfers ignore the `stock_per_company` switch: they are the records that
make the switch possible, so they always replay each company on its own.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

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


def _lot_unit(db: Session, lot_line_id: int | None, lot_adjustment_id: int | None) -> float | None:
    if not lot_line_id and not lot_adjustment_id:
        return None
    key = f"L{lot_line_id}" if lot_line_id else f"A{lot_adjustment_id}"
    lot = L.lot_state(db)["lots"].get(key)
    return lot["unit_cost_usd"] if lot else None


def plan(db: Session, *, sender_id: int, receiver_id: int, day: str, lines: list[dict]) -> dict:
    """Price and check a transfer. Each line is `{component_id?, mpn?, lcsc?,
    qty, unit_cost_usd?, lot_line_id?, lot_adjustment_id?, rebind_ids?}`;
    `rebind_ids` are lot bindings of the receiver's draws that move from the
    sender's lot onto the new position (a draw that took the other company's
    lot before the transfer existed)."""
    if sender_id == receiver_id:
        raise HTTPException(422, "a transfer goes from one company to the OTHER")
    sender, receiver = C.get(db, sender_id), C.get(db, receiver_id)
    day = (day or _today())[:10]
    out_lines, problems = [], []
    for i, ln in enumerate(lines):
        qty = float(ln.get("qty") or 0)
        if qty <= 0:
            problems.append({"line": i, "problem": "move at least one unit"})
            continue
        unit = ln.get("unit_cost_usd")
        source = "stated"
        if unit is None:
            unit = _lot_unit(db, ln.get("lot_line_id"), ln.get("lot_adjustment_id"))
            source = "the lot's landed cost"
        entry = RA.resolve_pool_identity(db, ln.get("component_id"), ln.get("mpn") or "",
                                         ln.get("lcsc") or "", as_of=day, company_id=sender.id)
        if unit is None:
            unit = (entry or {}).get("avg_usd")
            source = f"{sender.name}'s average on {day}"
        if entry is None and not ln.get("lot_line_id") and not ln.get("lot_adjustment_id"):
            problems.append({"line": i, "problem": f"{sender.name} never held this part",
                             "mpn": ln.get("mpn"), "component_id": ln.get("component_id")})
            continue
        out_lines.append({
            "component_id": (entry or {}).get("component_id") or ln.get("component_id"),
            "mpn": (entry or {}).get("mpn") or ln.get("mpn") or "",
            "lcsc": (entry or {}).get("lcsc") or ln.get("lcsc") or "",
            "qty": qty, "unit_cost_usd": round(float(unit or 0.0), 8), "price_source": source,
            "value_usd": round(qty * float(unit or 0.0), 4),
            "lot_line_id": ln.get("lot_line_id"), "lot_adjustment_id": ln.get("lot_adjustment_id"),
            "rebind_ids": list(ln.get("rebind_ids") or []), "label": ln.get("label") or "",
        })
    shortages = RA.check_shortages(db, [
        {"component_id": x["component_id"], "mpn": x["mpn"], "lcsc": x["lcsc"], "qty": x["qty"],
         "date": day, "label": x["label"] or x["mpn"]} for x in out_lines], company_id=sender.id)
    # A lot the sender's draw binds to must hold it — less what the receiver's
    # draws already took from it and now move onto the new position.
    rebound: dict[int, float] = defaultdict(float)
    for x in out_lines:
        for bid in x["rebind_ids"]:
            b = db.get(M.ComponentConsumptionLot, bid)
            if b is not None and b.lot_line_id:
                rebound[b.lot_line_id] += b.qty or 0.0
    capacity = L.check_lot_capacity(db, [
        {"lot_line_id": x["lot_line_id"], "lot_adjustment_id": x["lot_adjustment_id"],
         "qty": x["qty"] - rebound.get(x["lot_line_id"] or 0, 0.0)}
        for x in out_lines if (x["lot_line_id"] or x["lot_adjustment_id"])
        and x["qty"] - rebound.get(x["lot_line_id"] or 0, 0.0) > EPS])
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
        for bid in x["rebind_ids"]:
            b = db.get(M.ComponentConsumptionLot, bid)
            if b is not None:
                b.lot_line_id, b.lot_adjustment_id = li.id, None
                b.note = f"{b.note or ''} → {doc.doc_number}"[:500]
        x["line_id"] = li.id
        x["sender_draw_id"] = out.id
    db.flush()
    p["document_id"] = doc.id
    p["doc_number"] = doc.doc_number
    return p


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
             .filter(M.ComponentConsumptionLot.lot_line_id.in_(ids or [0])).all())
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

    Each company's stock is replayed on its own. A batch draw the batch
    company's stock could not cover is a unit that came from the other company.
    Two kinds of evidence, strongest first:

    1. **The lot the draw is bound to** (JLC names the purchase each assembly
       order consumed). A lot billed to the other company is moved, at its
       landed cost, and the draw's binding moves onto the transfer's position.
    2. **The other company's stock on the draw's date**, at its average, for
       a draw no lot explains.

    One transfer per receiving batch and date. A shortfall neither company
    covers stays short: it was short in the one shared pool too.
    """
    companies = C.all_companies(db)
    names = {c.id: c.name for c in companies}
    docs = {d.id: d for d in db.query(M.RunCostDocument).all()}
    lines = {li.id: li for li in db.query(M.RunCostLine)
             .filter(M.RunCostLine.voided_at.is_(None)).all()}
    adjs = {a.id: a for a in db.query(M.ComponentStockAdjustment).all()}

    def lot_company(b: M.ComponentConsumptionLot) -> int | None:
        if b.lot_line_id and b.lot_line_id in lines:
            d = docs.get(lines[b.lot_line_id].document_id)
            return d.company_id if d else None
        if b.lot_adjustment_id and b.lot_adjustment_id in adjs:
            return adjs[b.lot_adjustment_id].company_id
        return None

    # 1. Lot evidence: a batch draw bound to the other company's lot.
    by_key: dict[tuple, dict] = {}
    covered: dict[int, float] = defaultdict(float)   # consumption id -> qty explained
    runs = {r.id: r for r in db.query(M.ProductionRun).all()}
    draws = {c.id: c for c in RA.live_consumption(db).all()}
    undated: list[dict] = []
    for b in db.query(M.ComponentConsumptionLot).all():
        c = draws.get(b.consumption_id)
        if c is None or c.company_id is None or c.transfer_line_id:
            continue
        src = lot_company(b)
        if src is None or src == c.company_id:
            continue
        if not c.consumed_at:
            # A transfer must be dated on or before its draw; with no date
            # there is nothing to date it by, so a person decides.
            undated.append(c)
            continue
        key = (src, c.company_id, c.run_id, c.consumed_at or "")
        t = by_key.setdefault(key, {"sender_id": src, "receiver_id": c.company_id, "run_id": c.run_id,
                                    "date": c.consumed_at or "", "lines": [], "evidence": "lot"})
        t["lines"].append({"component_id": c.component_id, "mpn": c.mpn or "", "lcsc": c.lcsc or "",
                           "qty": b.qty or 0.0, "unit_cost_usd": b.unit_cost_usd,
                           "lot_line_id": b.lot_line_id, "lot_adjustment_id": b.lot_adjustment_id,
                           "rebind_ids": [b.id], "label": c.lcsc or c.mpn or "",
                           "consumption_id": c.id})
        covered[c.id] += b.qty or 0.0

    # 2. Balance evidence: replay each company, net of the lot transfers above.
    moved: dict[tuple, list] = defaultdict(list)   # (company, identity) -> [(date, +in/-out)]
    for t in by_key.values():
        for ln in t["lines"]:
            ident = RA._key(type("P", (), ln)())
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
            if kind == "use":
                q += covered.get(row.id, 0.0)   # the part a lot transfer already explains
            timeline.append(((d or "9999"), kind, RA._key(row), q, row if kind == "use" else None))
        for (cid, ident), v in moved.items():
            if cid == comp.id:
                for d, q in v:
                    timeline.append(((d or "9999"), "buy" if q > 0 else "use", ident, q, None))
        timeline.sort(key=lambda e: (e[0], e[1]))
        bal: dict[str, float] = defaultdict(float)
        for day, kind, ident, q, row in timeline:
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
                           "label": row.lcsc or row.mpn or "", "consumption_id": row.id})

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
            "totals": {"transfers": len(transfers),
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
    return {"dry_run": False, "written": written, "refused": refused,
            "unexplained": proposal["unexplained"], "totals": proposal["totals"]}
