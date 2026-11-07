"""The parts in the office organizers: which box holds what (decision 0104).

The organizers are shared by both companies. What a box holds belongs to one
company, so a balance is keyed `(box, item, company)` and is the sum of its
`OrganizerMove` rows.

**A box says where the pieces are. The material ledger says what they cost.**
Three rules connect the two, and `set_count` and `take` own them:

* **A take is a draw.** It leaves the box and the pool together, priced like any
  other draw. Purpose `research` is a cost no batch pays (`Draw.basis`
  "research"). Purpose `batch` charges the batch, except a crafted batch: its
  process steps draw the parts (decision 0060), so its take moves the box only.
* **A count that finds pieces uses the pool first.** Pieces the pool holds that
  are neither at JLC nor in a box are "somewhere", and a count has just found
  them. Only what is left over enters the pool, as a lot at zero value: nobody
  knows what it cost, and its cost is in closed books or in no book.
* **A count that loses pieces writes them off** (`miscount`). No batch pays.

The Stock page subtracts the boxes from the pool before it compares with JLC
(`house_index`, read by `run_actuals.parts_stock`).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from . import jlc_apply, run_actuals
from .material_ledger import core as ledger

PURPOSES = ("research", "batch")
#: A use no batch pays: R&D, or a project the platform does not track.
NO_BATCH = ("research", "external")
#: Pieces that are gone and that no batch and no R&D work pays: a loss of the
#: company that bought them.
LOSS = "loss"
#: A row with nothing in it stays on the list after these only if the last move
#: was not one of them: the box still "belongs" to a part it ran out of.
_GONE = ("move", "clear")


def _today() -> str:
    return date.today().isoformat()


def _keys(it: M.MaterialItem) -> list[str]:
    return run_actuals._identity_keys(it.component_id, it.mpn or "", it.lcsc or "")


def part_item(db: Session, component_id: int | None, mpn: str, lcsc: str,
              index: tuple[dict, dict] | None = None) -> M.MaterialItem:
    """The ledger item of a named part. A typed MPN or LCSC code that the library
    knows becomes that component, by the rule the purchase side uses."""
    mpn = (mpn or "").strip()
    lcsc = (lcsc or "").strip().upper()
    if not component_id and not mpn and not lcsc:
        raise HTTPException(422, "name the part: a library component, an MPN or an LCSC code")
    if not component_id:
        by_lcsc, by_mpn = index or jlc_apply._component_index(db)
        component_id = jlc_apply.resolve_component(by_lcsc, by_mpn, lcsc, mpn)
    return ledger.item(db, component_id, mpn, lcsc)


def _moves(db: Session, *, as_of: str | None = None, box_id: int | None = None,
           item_id: int | None = None, company_ids: list[int] | None = None):
    q = db.query(M.OrganizerMove)
    if box_id is not None:
        q = q.filter(M.OrganizerMove.box_id == box_id)
    if item_id is not None:
        q = q.filter(M.OrganizerMove.item_id == item_id)
    if company_ids is not None:
        q = q.filter(M.OrganizerMove.company_id.in_(company_ids))
    if as_of:
        q = q.filter(M.OrganizerMove.at <= as_of)
    return q


def balance(db: Session, box_id: int, item_id: int, company_id: int) -> float:
    return sum(m.qty or 0.0 for m in _moves(db, box_id=box_id, item_id=item_id, company_ids=[company_id]))


def house_index(db: Session, as_of: str | None = None, company_id: int | None = None) -> dict[str, list[dict]]:
    """Every identity key -> what the boxes hold under it, for a Stock page row
    to match by identity OVERLAP, the way it matches JLC's rows. One entry per
    (item, box); an item with several keys appears under each, so `house_of`
    removes the repeats."""
    moves = _moves(db, as_of=as_of, company_ids=[company_id] if company_id is not None else None).all()
    held: dict[tuple[int, int], float] = defaultdict(float)
    for m in moves:
        held[(m.item_id, m.box_id)] += m.qty or 0.0
    held = {k: v for k, v in held.items() if abs(v) > 1e-9}
    if not held:
        return {}
    items = {i.id: i for i in db.query(M.MaterialItem).filter(
        M.MaterialItem.id.in_({k[0] for k in held})).all()}
    boxes = {b.id: b for b in db.query(M.OrganizerBox).filter(
        M.OrganizerBox.id.in_({k[1] for k in held})).all()}
    out: dict[str, list[dict]] = defaultdict(list)
    for (item_id, box_id), qty in held.items():
        entry = {"item_id": item_id, "box_id": box_id, "code": boxes[box_id].code, "qty": qty}
        for k in _keys(items[item_id]):
            out[k].append(entry)
    return dict(out)


def house_of(index: dict[str, list[dict]], keys) -> tuple[float, list[dict]]:
    """What the boxes hold of a part named by these keys: the total and the boxes."""
    found = {(e["item_id"], e["box_id"]): e for k in keys for e in index.get(k, [])}
    boxes = sorted(found.values(), key=lambda e: e["code"])
    return sum(e["qty"] for e in boxes), [{"code": e["code"], "qty": e["qty"]} for e in boxes]


class _Stock:
    """The pool, JLC's shelf and the boxes, read once for one write. The pool is
    a replay of everything, so an import of 128 rows must not run one per row."""

    def __init__(self, db: Session):
        self.pool: dict[str, list[dict]] = defaultdict(list)
        for p in run_actuals.pool_state(db).values():
            for k in run_actuals._identity_keys(p.get("component_id"), p.get("mpn") or "", p.get("lcsc") or ""):
                self.pool[k].append(p)
        self.jlc: dict[str, list[M.JlcStockItem]] = defaultdict(list)
        for it in db.query(M.JlcStockItem).all():
            for k in run_actuals._identity_keys(it.component_id, it.mpn or "", it.lcsc or ""):
                self.jlc[k].append(it)
        self.house = house_index(db)

    def pool_qty(self, keys) -> float:
        return sum(p["qty"] for p in {id(p): p for k in keys for p in self.pool.get(k, [])}.values())

    def jlc_qty(self, keys) -> float:
        return sum(i.qty or 0 for i in {i.id: i for k in keys for i in self.jlc.get(k, [])}.values())

    def free(self, keys) -> float:
        """Pieces the pool holds that are neither at JLC nor in a box."""
        return max(0.0, self.pool_qty(keys) - self.jlc_qty(keys) - house_of(self.house, keys)[0])

    def wrote(self, it: M.MaterialItem, box_id: int, code: str, delta: float, in_pool: float) -> None:
        entry = {"item_id": it.id, "box_id": box_id, "code": code, "qty": delta}
        keys = _keys(it)
        shared = None
        for k in keys:
            for e in self.house.get(k, []):
                if e["item_id"] == it.id and e["box_id"] == box_id:
                    shared = e
        if shared is not None:
            shared["qty"] += delta
        else:
            for k in keys:
                self.house.setdefault(k, []).append(entry)
        entries = {id(p): p for k in keys for p in self.pool.get(k, [])}
        if entries:
            next(iter(entries.values()))["qty"] += in_pool
        elif in_pool:
            row = {"qty": in_pool}
            for k in keys:
                self.pool[k].append(row)


def set_count(db: Session, box: M.OrganizerBox, it: M.MaterialItem, company_id: int, qty: float, *,
              at: str = "", note: str = "", actor: str = "", opening: bool = False,
              stock: _Stock | None = None) -> dict:
    """State what a box holds of a part, as an ABSOLUTE number. The caller is
    reading it off the box, not off the screen, so a delta would make them do
    arithmetic, and sending the same number twice changes nothing."""
    if qty < 0:
        raise HTTPException(422, "a box cannot hold fewer than 0 pieces")
    at = at or _today()
    stock = stock or _Stock(db)
    had = balance(db, box.id, it.id, company_id)
    delta = qty - had
    seen = _moves(db, box_id=box.id, item_id=it.id, company_ids=[company_id]).first() is not None
    if abs(delta) < 1e-9 and seen:
        return {"changed": False, "qty": had, "delta": 0.0, "found": 0.0, "written_off": 0.0}
    keys = _keys(it)
    found = written_off = 0.0
    ledger_move = None
    if delta > 0:
        found = max(0.0, delta - stock.free(keys))
        if found > 0:
            ledger_move = ledger.adjustment(
                db, component_id=it.component_id, mpn=it.mpn, lcsc=it.lcsc, qty=found, unit_cost_usd=0.0,
                reason="opening_balance" if opening else "found", company_id=company_id, at=at, actor=actor,
                note=(f"Counted in box {box.code}: no purchase in the pool covers these pieces, "
                      f"so they enter at zero value. {note}")[:500])
    elif delta < 0:
        written_off = min(-delta, max(stock.pool_qty(keys), 0.0))
        if written_off > 0:
            ledger_move = ledger.adjustment(
                db, component_id=it.component_id, mpn=it.mpn, lcsc=it.lcsc, qty=-written_off, unit_cost_usd=None,
                reason="miscount", company_id=company_id, at=at, actor=actor,
                note=f"Counted in box {box.code}: {had:g} expected, {qty:g} there. {note}"[:500])
    db.add(M.OrganizerMove(box_id=box.id, item_id=it.id, company_id=company_id, qty=delta,
                           kind="opening" if opening else "count", at=at,
                           material_move_id=ledger_move.id if ledger_move is not None else None,
                           note=(note or "")[:500], actor=actor or ""))
    db.flush()
    stock.wrote(it, box.id, box.code, delta, found - written_off)
    return {"changed": True, "qty": qty, "delta": delta, "found": found, "written_off": written_off}


def _company_in_box(db: Session, box: M.OrganizerBox, it: M.MaterialItem, company_id: int | None,
                    allowed: list[int] | None) -> tuple[int, float]:
    """Whose pieces leave, and how many of them are in the box. Asked only when
    both companies hold this part in this box (user decision 2026-11-07)."""
    held: dict[int, float] = defaultdict(float)
    for m in _moves(db, box_id=box.id, item_id=it.id, company_ids=allowed):
        held[m.company_id] += m.qty or 0.0
    held = {c: q for c, q in held.items() if q > 1e-9}
    if company_id is not None:
        return company_id, held.get(company_id, 0.0)
    if not held:
        raise HTTPException(409, f"box {box.code} holds none of this part")
    if len(held) > 1:
        raise HTTPException(422, f"both companies hold this part in box {box.code}: say whose pieces leave")
    return next(iter(held.items()))


def take(db: Session, box: M.OrganizerBox, it: M.MaterialItem, qty: float, purpose: str, *,
         company_id: int | None = None, run_id: int | None = None, at: str = "", note: str = "",
         actor: str = "", allowed: list[int] | None = None) -> dict:
    """Pieces leave a box for R&D or for a batch: the box and the pool go down
    together, and the draw is the cost."""
    if qty <= 0:
        raise HTTPException(422, "take at least 1 piece")
    if purpose not in PURPOSES:
        raise HTTPException(422, f"purpose must be one of {PURPOSES}")
    if purpose == "research" and not (note or "").strip():
        raise HTTPException(422, "say what the R&D work is: this note is the only record of why this cost exists")
    if purpose == "batch" and run_id is None:
        raise HTTPException(422, "name the batch that uses these pieces")
    if purpose == "research":
        run_id = None
    company_id, held = _company_in_box(db, box, it, company_id, allowed)
    if qty > held + 1e-9:
        raise HTTPException(409, f"box {box.code} holds {held:g} of this part for this company, not {qty:g}")
    at = at or _today()
    run = db.get(M.ProductionRun, run_id) if run_id is not None else None
    if run_id is not None and run is None:
        raise HTTPException(404, "no such batch")
    if run is not None and run.closed_at:
        # A closed batch's cost has gone out on orders (decision 0044).
        raise HTTPException(409, f"the books of {run.label} are closed: a take cannot charge it")
    if run is not None and run.company_id and run.company_id != company_id:
        raise HTTPException(422, f"{run.label} draws from its own company's stock: these pieces belong to the other "
                                 "company. Transfer them first (Stock → Transfers)")
    draw = None
    unit = None
    # A crafted batch takes parts only through its process steps (decision
    # 0060). Those clicks draw from the pool, so a draw here would count the
    # pieces twice. The take moves the box only.
    if run is None or not run.process_version_id:
        draw, unit = _draw(db, box, it, qty, company_id, run_id, purpose, at, note, actor)
    db.add(M.OrganizerMove(box_id=box.id, item_id=it.id, company_id=company_id, qty=-qty, kind="take",
                           purpose=purpose, at=at, material_move_id=draw.id if draw is not None else None,
                           run_id=run_id, note=(note or "")[:500], actor=actor or ""))
    db.flush()
    return {"company_id": company_id, "qty": qty, "draw_id": draw.id if draw is not None else None,
            "unit_cost_usd": unit, "value_usd": round(qty * unit, 4) if unit is not None else None,
            "left": round(held - qty, 6)}


def _draw(db: Session, box: M.OrganizerBox | None, it: M.MaterialItem, qty: float, company_id: int,
          run_id: int | None, purpose: str, at: str, note: str, actor: str) -> tuple[M.Draw, float]:
    """The draw of a take, under the rules `add_consumption` keeps: never more
    than the pool held on the day, and priced at the average of that day. A
    shortage names the way out, because the pieces are in the box."""
    scope = run_actuals.stock_scope(db, company_id)
    pool = run_actuals.resolve_pool_identity(db, it.component_id, it.mpn or "", it.lcsc or "",
                                             as_of=at, company_id=scope)
    who = {"component_id": (pool or {}).get("component_id") or it.component_id,
           "mpn": (pool or {}).get("mpn") or it.mpn or "", "lcsc": (pool or {}).get("lcsc") or it.lcsc or ""}
    short = run_actuals.check_shortages(db, [{**who, "qty": qty, "date": at}], company_id=scope)
    if short:
        where = f"box {box.code} holds these pieces, but the stock records" if box is not None else "the stock records"
        fix = "Count the box again, or enter" if box is not None else "Enter"
        raise HTTPException(409, {"error": f"{where} hold too few on {at}. {fix} the missing purchase",
                                  "shortages": short})
    unit = float((pool or {}).get("avg_usd") or 0.0)
    source = f", from box {box.code}" if box is not None else ""
    why = (f"R&D{source}: {note}" if purpose == "research"
           else f"Outside the platform: {note}" if purpose == "external"
           else f"From box {box.code}. {note}".strip())
    draw = ledger.draw(db, run_id=run_id, taken=qty, unit_cost_usd=unit, company_id=company_id, at=at,
                       basis=purpose if purpose in NO_BATCH else "manual", note=why, actor=actor, **who)
    return draw, unit


def research_use(db: Session, it: M.MaterialItem, qty: float, company_id: int, *, at: str = "", note: str = "",
                 actor: str = "", purpose: str = "research") -> dict:
    """Pieces that left and are in no box: what the pool still counts of an
    invoice whose parts were used before Henry knew about them (decision 0104).
    `external` is a project the platform does not track, and it reads as an
    uncharged draw in the register, as such an order always has (decision 0034)."""
    if qty <= 0:
        raise HTTPException(422, "use at least 1 piece")
    if purpose not in NO_BATCH:
        raise HTTPException(422, f"purpose must be one of {NO_BATCH}")
    if not (note or "").strip():
        raise HTTPException(422, "say what the work is: this note is the only record of why this cost exists")
    at = at or _today()
    draw, unit = _draw(db, None, it, qty, company_id, None, purpose, at, note, actor)
    return {"draw_id": draw.id, "qty": qty, "unit_cost_usd": unit, "value_usd": round(qty * unit, 4)}


def write_off(db: Session, it: M.MaterialItem, qty: float, company_id: int, *, at: str = "", note: str = "",
              actor: str = "") -> dict:
    """Pieces that are gone, in no box, and that nothing should pay for: a scrap
    adjustment of the company that bought them, at the average of the day. It
    names no project and no batch, so no other company's records change."""
    if qty <= 0:
        raise HTTPException(422, "write off at least 1 piece")
    if not (note or "").strip():
        raise HTTPException(422, "say why these pieces are gone: this note is the only record of the loss")
    at = at or _today()
    scope = run_actuals.stock_scope(db, company_id)
    pool = run_actuals.resolve_pool_identity(db, it.component_id, it.mpn or "", it.lcsc or "",
                                             as_of=at, company_id=scope)
    who = {"component_id": (pool or {}).get("component_id") or it.component_id,
           "mpn": (pool or {}).get("mpn") or it.mpn or "", "lcsc": (pool or {}).get("lcsc") or it.lcsc or ""}
    short = run_actuals.check_shortages(db, [{**who, "qty": qty, "date": at}], company_id=scope)
    if short:
        raise HTTPException(409, {"error": f"the stock records hold too few on {at}", "shortages": short})
    unit = float((pool or {}).get("avg_usd") or 0.0)
    row = ledger.adjustment(db, qty=-qty, unit_cost_usd=unit, reason="scrap", company_id=company_id, at=at,
                            note=note[:500], actor=actor, **who)
    return {"adjustment_id": row.id, "qty": qty, "unit_cost_usd": unit, "value_usd": round(qty * unit, 4)}


def research_list(db: Session, company_ids: list[int] | None = None, limit: int = 500) -> list[dict]:
    """Everything used for R&D, newest first. It reads the draws, because a piece
    can go to R&D with no box behind it."""
    q = run_actuals.live_consumption(db).filter(M.Draw.basis == "research")
    if company_ids is not None:
        q = q.filter(M.Draw.company_id.in_(company_ids))
    rows = q.order_by(M.Draw.at.desc(), M.Draw.id.desc()).limit(limit).all()
    boxes = {m.material_move_id: m.box_id for m in db.query(M.OrganizerMove).filter(
        M.OrganizerMove.material_move_id.in_([c.id for c in rows] or [0])).all()}
    codes = dict(db.query(M.OrganizerBox.id, M.OrganizerBox.code).filter(
        M.OrganizerBox.id.in_(set(boxes.values()) or {0})).all())
    names = dict(db.query(M.Component.id, M.Component.name).filter(
        M.Component.id.in_({c.component_id for c in rows if c.component_id} or {0})).all())
    company_names = dict(db.query(M.Company.id, M.Company.name).all())
    return [{"id": c.id, "at": c.at, "name": names.get(c.component_id) or c.mpn or c.lcsc,
             "box": codes.get(boxes.get(c.id), ""), "qty": c.taken, "unit_cost_usd": c.unit_cost_usd,
             "value_usd": round(c.taken * (c.unit_cost_usd or 0.0), 4), "company_id": c.company_id,
             "company": company_names.get(c.company_id, ""), "note": c.note, "actor": c.actor}
            for c in rows]


def move(db: Session, box: M.OrganizerBox, to: M.OrganizerBox, it: M.MaterialItem, qty: float, *,
         company_id: int | None = None, at: str = "", note: str = "", actor: str = "",
         allowed: list[int] | None = None) -> dict:
    """Pieces change box. The pool does not move: they are the same pieces."""
    if qty <= 0:
        raise HTTPException(422, "move at least 1 piece")
    if to.id == box.id:
        raise HTTPException(422, "the pieces are in that box already")
    company_id, held = _company_in_box(db, box, it, company_id, allowed)
    if qty > held + 1e-9:
        raise HTTPException(409, f"box {box.code} holds {held:g} of this part for this company, not {qty:g}")
    at = at or _today()
    for b, q, text in ((box, -qty, f"To box {to.code}. {note}"), (to, qty, f"From box {box.code}. {note}")):
        db.add(M.OrganizerMove(box_id=b.id, item_id=it.id, company_id=company_id, qty=q, kind="move", at=at,
                               note=text.strip()[:500], actor=actor or ""))
    db.flush()
    return {"company_id": company_id, "qty": qty, "left": round(held - qty, 6)}


def clear(db: Session, box: M.OrganizerBox, it: M.MaterialItem, actor: str = "") -> None:
    """Take an empty part's row off a box. Refused while the box holds any."""
    held: dict[int, float] = defaultdict(float)
    for m in _moves(db, box_id=box.id, item_id=it.id):
        held[m.company_id] += m.qty or 0.0
    if any(abs(q) > 1e-9 for q in held.values()):
        raise HTTPException(409, f"box {box.code} still holds this part: count it to 0 or take it first")
    for company_id in held:
        db.add(M.OrganizerMove(box_id=box.id, item_id=it.id, company_id=company_id, qty=0.0, kind="clear",
                               at=_today(), actor=actor or ""))
    db.flush()


def make_boxes(db: Session, organizer: str, codes: list[str], actor: str = "") -> list[M.OrganizerBox]:
    """The boxes that do not exist yet. An existing code is kept as it is."""
    organizer = (organizer or "").strip()
    if not organizer:
        raise HTTPException(422, "name the organizer")
    have = {b.code for b in db.query(M.OrganizerBox).filter_by(organizer=organizer).all()}
    made = []
    for raw in codes:
        code = (raw or "").strip()
        if code and code not in have:
            have.add(code)
            box = M.OrganizerBox(organizer=organizer, code=code, created_by=actor or "")
            db.add(box)
            made.append(box)
    db.flush()
    return made


def overview(db: Session, company_ids: list[int] | None = None) -> dict:
    """Every box, and what it holds of the companies in scope. Empty boxes stay
    in the answer: "where is there room" is a question this page answers."""
    boxes = db.query(M.OrganizerBox).all()
    moves = _moves(db, company_ids=company_ids).order_by(M.OrganizerMove.id).all()
    items = {i.id: i for i in db.query(M.MaterialItem).filter(
        M.MaterialItem.id.in_({m.item_id for m in moves} or {0})).all()}
    names = dict(db.query(M.Component.id, M.Component.name).filter(
        M.Component.id.in_({i.component_id for i in items.values() if i.component_id} or {0})).all())
    company_names = dict(db.query(M.Company.id, M.Company.name).all())

    rows: dict[tuple[int, int], dict] = {}
    for m in moves:
        r = rows.setdefault((m.box_id, m.item_id), {"by_company": defaultdict(float), "note": "", "last": None})
        r["by_company"][m.company_id] += m.qty or 0.0
        if m.note and m.kind == "opening":
            r["note"] = m.note
        r["last"] = m

    by_box: dict[int, list[dict]] = defaultdict(list)
    for (box_id, item_id), r in rows.items():
        qty = sum(r["by_company"].values())
        if abs(qty) < 1e-9 and r["last"].kind in _GONE:
            continue
        it = items[item_id]
        by_box[box_id].append({
            "item_id": item_id, "component_id": it.component_id,
            "name": names.get(it.component_id) or it.mpn or it.lcsc,
            "in_library": it.component_id in names, "mpn": it.mpn or "", "lcsc": it.lcsc or "",
            "qty": qty, "note": r["note"],
            "companies": [{"id": c, "name": company_names.get(c, ""), "qty": q}
                          for c, q in sorted(r["by_company"].items()) if abs(q) > 1e-9],
            "last_at": r["last"].at, "last_actor": r["last"].actor,
        })
    out_boxes = []
    per_org: dict[str, dict] = defaultdict(lambda: {"boxes": 0, "filled": 0, "pieces": 0.0})
    for b in boxes:
        parts = sorted(by_box.get(b.id, []), key=lambda p: p["name"])
        o = per_org[b.organizer]
        o["boxes"] += 1
        o["filled"] += 1 if any(p["qty"] > 0 for p in parts) else 0
        o["pieces"] += sum(p["qty"] for p in parts)
        out_boxes.append({"id": b.id, "organizer": b.organizer, "code": b.code, "note": b.note, "parts": parts})
    return {
        "boxes": out_boxes,
        "organizers": [{"name": n, **v} for n, v in sorted(per_org.items())],
        "totals": {"boxes": len(boxes), "filled": sum(v["filled"] for v in per_org.values()),
                   "pieces": sum(v["pieces"] for v in per_org.values()),
                   "parts": len({p["item_id"] for parts in by_box.values() for p in parts if p["qty"] > 0})},
    }


def history(db: Session, *, box_id: int | None = None, item_id: int | None = None,
            purpose: str = "", company_ids: list[int] | None = None, limit: int = 200) -> list[dict]:
    """The moves, newest first, with what a take cost."""
    q = _moves(db, box_id=box_id, item_id=item_id, company_ids=company_ids)
    if purpose:
        q = q.filter(M.OrganizerMove.purpose == purpose)
    rows = q.order_by(M.OrganizerMove.id.desc()).limit(limit).all()
    boxes = {b.id: b for b in db.query(M.OrganizerBox).filter(
        M.OrganizerBox.id.in_({m.box_id for m in rows} or {0})).all()}
    items = {i.id: i for i in db.query(M.MaterialItem).filter(
        M.MaterialItem.id.in_({m.item_id for m in rows} or {0})).all()}
    names = dict(db.query(M.Component.id, M.Component.name).filter(
        M.Component.id.in_({i.component_id for i in items.values() if i.component_id} or {0})).all())
    company_names = dict(db.query(M.Company.id, M.Company.name).all())
    runs = dict(db.query(M.ProductionRun.id, M.ProductionRun.label).filter(
        M.ProductionRun.id.in_({m.run_id for m in rows if m.run_id} or {0})).all())
    draws = {d.id: d for d in db.query(M.MaterialMove).filter(
        M.MaterialMove.id.in_({m.material_move_id for m in rows if m.material_move_id} or {0})).all()}
    out = []
    for m in rows:
        d = draws.get(m.material_move_id)
        it = items[m.item_id]
        unit = d.unit_cost_usd if d is not None else None
        out.append({
            "id": m.id, "at": m.at, "kind": m.kind, "purpose": m.purpose, "qty": m.qty,
            "box_id": m.box_id, "box": boxes[m.box_id].code, "organizer": boxes[m.box_id].organizer,
            "item_id": m.item_id, "name": names.get(it.component_id) or it.mpn or it.lcsc,
            "company_id": m.company_id, "company": company_names.get(m.company_id, ""),
            "run_id": m.run_id, "run_label": runs.get(m.run_id) if m.run_id else None,
            "note": m.note, "actor": m.actor, "unit_cost_usd": unit,
            "value_usd": round(-m.qty * unit, 4) if m.kind == "take" and unit is not None else None,
        })
    return out


def import_rows(db: Session, rows: list[dict], *, at: str, actor: str = "") -> dict:
    """Load a list of boxes and their contents, once. A row with no part makes an
    empty box. A row whose opening is already written is left alone, so a second
    run changes nothing. `run_import` of the router wraps this in a journal batch."""
    stock = _Stock(db)
    index = jlc_apply._component_index(db)
    plan = []
    for n, r in enumerate(rows, 1):
        if not str(r.get("organizer") or "").strip() or not str(r.get("code") or "").strip():
            raise HTTPException(422, f"row {n} has no organizer or no box code")
        made = make_boxes(db, r["organizer"], [r["code"]], actor)
        box = made[0] if made else (db.query(M.OrganizerBox)
                                    .filter_by(organizer=r["organizer"].strip(), code=r["code"].strip()).one())
        entry = {"organizer": box.organizer, "code": box.code, "new_box": bool(made)}
        if not (r.get("component_id") or (r.get("mpn") or "").strip() or (r.get("lcsc") or "").strip()):
            plan.append({**entry, "status": "empty_box"})
            continue
        it = part_item(db, r.get("component_id"), r.get("mpn") or "", r.get("lcsc") or "", index)
        keys = _keys(it)
        qty = float(r.get("qty") or 0)
        entry.update(part=(r.get("mpn") or "").strip() or it.mpn or it.lcsc, company_id=r["company_id"], qty=qty,
                     in_library=bool(it.component_id), pool_before=round(stock.pool_qty(keys), 4),
                     jlc=stock.jlc_qty(keys), free_before=round(stock.free(keys), 4))
        if (db.query(M.OrganizerMove.id)
              .filter_by(box_id=box.id, item_id=it.id, company_id=r["company_id"], kind="opening").first()):
            plan.append({**entry, "status": "already_imported"})
            continue
        res = set_count(db, box, it, r["company_id"], qty, at=at, note=r.get("note") or "", actor=actor,
                        opening=True, stock=stock)
        plan.append({**entry, "status": "written", "found_at_zero": res["found"]})
    written = [p for p in plan if p["status"] == "written"]
    return {
        "rows": plan,
        "totals": {"rows": len(plan), "boxes_made": sum(1 for p in plan if p["new_box"]),
                   "written": len(written), "already_imported": sum(1 for p in plan if p["status"] == "already_imported"),
                   "pieces": sum(p["qty"] for p in written),
                   "found_rows": sum(1 for p in written if p["found_at_zero"] > 0),
                   "found_pieces": sum(p["found_at_zero"] for p in written)},
    }
