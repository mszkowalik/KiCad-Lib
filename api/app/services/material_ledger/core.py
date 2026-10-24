"""The material ledger's writing helpers (decisions 0097, 0098).

Every writer of stock or work goes through here: an item for a part or a
product, an event for an operation, a draw or an adjustment for a change of
quantity, a stock lot for what a positive adjustment brings in. The readers
(the pool replay, the lot ledger, unit prices) live with their topics:
`run_actuals`, `lots`, `twins`.

Two rules this module keeps:

* **Every move names its item.** `item_id` is the pool identity
  (`run_actuals._key`) of the part as the writer named it, so the replay that
  groups by item and the old grouping by key cannot disagree.
* **Every move belongs to an event.** A draw a click made belongs to the
  click, a make's inputs and output to the make, an in-house transfer's draw
  to the transfer. Anything else gets an event of kind `stock` of its own.
"""
from __future__ import annotations

from types import SimpleNamespace

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from ... import models as M


def item_key(component_id: int | None, mpn: str = "", lcsc: str = "") -> str:
    """The pool identity: component id when known, else MPN, else LCSC. It IS
    `run_actuals._key`, so an item and a pool entry are always the same thing."""
    from ..run_actuals import _key

    return _key(SimpleNamespace(component_id=component_id, mpn=mpn or "", lcsc=lcsc or ""))


def item(db: Session, component_id: int | None = None, mpn: str = "", lcsc: str = "") -> M.MaterialItem:
    """The item of a part, made the first time something names it."""
    key = item_key(component_id, mpn, lcsc)
    it = db.query(M.MaterialItem).filter_by(key=key).first()
    if it is None:
        it = M.MaterialItem(key=key, kind="part", component_id=component_id or None,
                            mpn=(mpn or "")[:200], lcsc=(lcsc or "")[:50])
        db.add(it)
        db.flush()
    return it


def product_item(db: Session, project_id: int) -> M.MaterialItem:
    """The item of a project's product unit."""
    key = f"p{project_id}"
    it = db.query(M.MaterialItem).filter_by(key=key).first()
    if it is None:
        it = M.MaterialItem(key=key, kind="product", project_id=project_id, tracking="serial")
        db.add(it)
        db.flush()
    return it


def stock_event(db: Session, *, at: str = "", actor: str = "", company_id: int | None = None,
                run_id: int | None = None, project_id: int | None = None, note: str = "") -> M.MaterialEvent:
    """An operation on stock that no click or make holds: a reported or a hand
    draw, a BOM draw, a transfer, a count, a write-off."""
    ev = M.MaterialEvent(kind="stock", at=at or "", actor=actor or "", company_id=company_id, run_id=run_id,
                         project_id=project_id, note=(note or "")[:500])
    db.add(ev)
    db.flush()
    return ev


def draw(db: Session, *, event: M.MaterialEvent | None = None, component_id: int | None = None,
         mpn: str = "", lcsc: str = "", taken: float, unit_cost_usd: float | None, at: str = "",
         run_id: int | None = None, company_id: int | None = None, basis: str = "manual",
         import_ref: str = "", note: str = "", transfer_line_id: int | None = None,
         actor: str = "") -> M.Draw:
    """A quantity that LEFT stock (`taken` > 0), charged to `run_id` or to
    nobody. Without an event it gets a `stock` event of its own."""
    if event is None:
        event = stock_event(db, at=at, actor=actor, company_id=company_id, run_id=run_id, note=note)
    it = item(db, component_id, mpn, lcsc)
    d = M.Draw(event_id=event.id, item_id=it.id, component_id=component_id or None, mpn=mpn or "",
               lcsc=lcsc or "", qty=-(taken or 0.0), unit_cost_usd=unit_cost_usd, at=at or event.at or "",
               run_id=run_id, company_id=company_id, basis=basis or "", import_ref=import_ref or "",
               note=(note or "")[:500], transfer_line_id=transfer_line_id, actor=actor or "")
    db.add(d)
    db.flush()
    return d


def adjustment(db: Session, *, event: M.MaterialEvent | None = None, component_id: int | None = None,
               mpn: str = "", lcsc: str = "", qty: float, unit_cost_usd: float | None, at: str = "",
               reason: str = "attrition", run_id: int | None = None, project_id: int | None = None,
               company_id: int | None = None, import_ref: str = "", note: str = "",
               actor: str = "") -> M.Adjustment:
    """A correction of stock, signed. A positive one makes a stock lot: an
    opening balance, found units, a make's output."""
    if event is None:
        event = stock_event(db, at=at, actor=actor, company_id=company_id, run_id=run_id,
                            project_id=project_id, note=note)
    it = item(db, component_id, mpn, lcsc)
    a = M.Adjustment(event_id=event.id, item_id=it.id, component_id=component_id or None, mpn=mpn or "",
                     lcsc=lcsc or "", qty=qty or 0.0, unit_cost_usd=unit_cost_usd, at=at or event.at or "",
                     reason=reason or "", run_id=run_id, project_id=project_id, company_id=company_id,
                     import_ref=import_ref or "", note=(note or "")[:500], actor=actor or "")
    db.add(a)
    db.flush()
    if (qty or 0.0) > 0:
        lot = M.MaterialLot(kind="stock", item_id=it.id, company_id=a.company_id, at=a.at,
                            created_event_id=event.id)
        db.add(lot)
        db.flush()
        lot.label = f"A{lot.id}"
        a.lot_id = lot.id
        db.flush()
    return a


def bind(db: Session, move: M.MaterialMove, *, qty: float, unit_cost_usd: float, lot_line_id: int | None = None,
         lot_id: int | None = None, source: str = "fifo", ext_ref: str = "", note: str = "") -> M.MaterialMoveLot:
    """Name a lot a move took from."""
    b = M.MaterialMoveLot(move_id=move.id, lot_line_id=lot_line_id, lot_id=lot_id, qty=qty,
                          unit_cost_usd=unit_cost_usd or 0.0, source=source, ext_ref=ext_ref or "",
                          note=(note or "")[:500])
    db.add(b)
    return b


def event_kinds(db: Session, event_ids) -> dict[int, str]:
    """`event id -> kind` for these events."""
    ids = {e for e in event_ids if e}
    if not ids:
        return {}
    return dict(db.query(M.MaterialEvent.id, M.MaterialEvent.kind).filter(M.MaterialEvent.id.in_(ids)).all())


_IDENTITY = ("component_id", "mpn", "lcsc")


@event.listens_for(Session, "before_flush")
def keep_item(session: Session, flush_context, instances) -> None:
    """A move's item follows the part it names, whichever writer named or
    renamed it: a new move, or one whose component id, MPN or LCSC changed
    (a part resolved to the library, a draw re-keyed). The item is found or
    made with plain SQL, because a flush cannot run inside a flush."""
    moves = [o for o in session.new if isinstance(o, M.MaterialMove)]
    for o in session.dirty:
        if isinstance(o, M.MaterialMove):
            st = inspect(o)
            if any(st.attrs[c].history.has_changes() for c in _IDENTITY):
                moves.append(o)
    if not moves:
        return
    conn = session.connection()
    for o in moves:
        key = item_key(o.component_id, o.mpn or "", o.lcsc or "")
        iid = conn.execute(text("SELECT id FROM material_items WHERE key = :k"), {"k": key}).scalar()
        if iid is None:
            iid = conn.execute(text(
                "INSERT INTO material_items (key, kind, component_id, mpn, lcsc, uom, tracking, identifier_kind, "
                "created_at) VALUES (:k, 'part', :c, :m, :l, 'pcs', 'count', '', now()) RETURNING id"),
                {"k": key, "c": o.component_id or None, "m": (o.mpn or "")[:200],
                 "l": (o.lcsc or "")[:50]}).scalar()
        if o.item_id != iid:
            o.item_id = iid

