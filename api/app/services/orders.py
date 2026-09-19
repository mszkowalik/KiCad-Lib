"""Sales orders, shipments, finished-goods stock and the per-device history.

Decision record: docs/decisions/0003-orders-shipments-and-device-history.md.

The device is the unit of record. `DeviceEvent` is append-only and the newest
event IS the device's state; `DeviceUnit.state` / `.production_run_id` are
caches of it, rebuilt by `refresh_device_state`. Stock is a count of devices in
`in_stock`; fulfilment is a count of `shipped` events; order cost is the
production cost of every device ever shipped to the order, replacements
included, plus repair cost lines.

Batches from before the flasher recorded MACs have no device rows to move, so
a shipment line may also carry `qty_unserialized` (§8). Every stock and
fulfilment figure here counts BOTH paths, and a real return can convert one
anonymous unit into a named device (`return_device`).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from . import fx, run_actuals

STATE_AFTER = {
    "produced": "in_stock",
    "allocated": "allocated",
    "shipped": "shipped",
    "unshipped": "in_stock",
    "returned": "returned",
    "repaired": "in_stock",
    "disposed": "disposed",
}
INVOICE_KINDS = ("proforma", "advance", "final", "correction")
MONEY_KINDS = ("advance", "final", "correction")  # a proforma is not money
ORDER_STATUSES = ("open", "partial", "fulfilled", "cancelled")


def _round(v: float | None) -> float | None:
    return None if v is None else round(v, 2)


def _as_dt(date_iso: str | None):
    return run_actuals._as_dt(date_iso) if date_iso else None


def _date_at(date_iso: str | None) -> datetime:
    """An event timestamp for a date typed by a person: noon UTC on that day,
    so it sorts after a `produced` event stamped at the device's first_seen
    and before anything typed the next day."""
    if date_iso:
        try:
            return datetime.fromisoformat(date_iso[:10]).replace(hour=12, tzinfo=UTC)
        except ValueError:
            pass
    return utcnow()


# ------------------------------------------------------------------ events


def record_event(db: Session, device: M.DeviceUnit, kind: str, *, at: datetime | None = None,
                 actor: str = "", note: str = "", reason: str = "", auto: bool = False,
                 production_run_id: int | None = None, order_line_id: int | None = None,
                 shipment_id: int | None = None,
                 replaces_device_id: int | None = None) -> M.DeviceEvent:
    if kind not in STATE_AFTER:
        raise HTTPException(422, f"unknown device event kind {kind!r}")
    at = at or utcnow()
    # The log is read in `at` order, so a device's history must be monotonic:
    # a return typed today against a delivery dated tomorrow, or a swap that
    # inherits an older shipment's date, lands one second after what came
    # before it rather than in front of it.
    prev = device.events[-1] if device.events else None
    if prev is not None and prev.at is not None and at <= prev.at:
        at = prev.at + timedelta(seconds=1)
    ev = M.DeviceEvent(
        device_id=device.id, kind=kind, at=at, actor=actor or "", note=note or "",
        reason=reason or "", auto=auto, production_run_id=production_run_id,
        order_line_id=order_line_id, shipment_id=shipment_id, replaces_device_id=replaces_device_id,
    )
    # Appended to the relationship, not merely added to the session, so the
    # next write in the same request sees it.
    device.events.append(ev)
    device.state = STATE_AFTER[kind]
    if kind == "produced":
        device.production_run_id = production_run_id
    return ev


def refresh_device_state(db: Session, device: M.DeviceUnit) -> str:
    """Rebuild the cache from the log. The log is the truth."""
    events = (db.query(M.DeviceEvent).filter_by(device_id=device.id)
              .order_by(M.DeviceEvent.at, M.DeviceEvent.id).all())
    device.state = STATE_AFTER[events[-1].kind] if events else ""
    produced = next((e for e in events if e.kind == "produced"), None)
    device.production_run_id = produced.production_run_id if produced else None
    return device.state


def last_event(device: M.DeviceUnit, kind: str | None = None) -> M.DeviceEvent | None:
    evs = [e for e in device.events if kind is None or e.kind == kind]
    return evs[-1] if evs else None


def mark_produced(db: Session, device: M.DeviceUnit, run_id: int, *, at: datetime | None = None,
                  actor: str = "", note: str = "") -> M.DeviceEvent | None:
    """Idempotent: a device is produced once. Called by the flasher on the first
    `pass` in a batch, and by the retro-link endpoint for legacy units. Returns
    None when the device already has its `produced` event for this run."""
    existing = next((e for e in device.events if e.kind == "produced"), None)
    if existing is not None:
        if existing.production_run_id != run_id:
            raise HTTPException(409, f"device {device.serial or device.id} was already produced in run "
                                     f"{existing.production_run_id}, not {run_id}")
        return None
    if device.events:
        raise HTTPException(409, f"device {device.serial or device.id} has history but no produced event")
    return record_event(db, device, "produced", at=at or device.first_seen, actor=actor, note=note,
                        production_run_id=run_id)


def link_devices_to_run(db: Session, run: M.ProductionRun, device_ids: list[int],
                        actor: str = "") -> dict:
    """Retro-link legacy devices to their batch: one `produced` event each,
    stamped at the device's first_seen so FIFO order is the programming order."""
    linked, skipped = 0, []
    for did in device_ids:
        d = db.get(M.DeviceUnit, did)
        if d is None:
            skipped.append({"id": did, "reason": "no such device"})
            continue
        if d.project_id != run.project_id:
            skipped.append({"id": did, "reason": f"device belongs to project {d.project_id}"})
            continue
        try:
            ev = mark_produced(db, d, run.id, actor=actor, note="linked to batch after the fact")
        except HTTPException as e:
            skipped.append({"id": did, "reason": e.detail})
            continue
        if ev is not None:
            linked += 1
        else:
            skipped.append({"id": did, "reason": "already produced in this run"})
    db.flush()
    return {"linked": linked, "skipped": skipped}


def rebatch_devices(db: Session, run: M.ProductionRun, device_ids: list[int], *,
                    actor: str = "", note: str = "", dry_run: bool = True) -> dict:
    """Move devices to the batch they were really built in (decision 0029).

    The batch on a `produced` event is chosen by whoever was standing at the
    bench, from a list, before the first device of the shift passes. Pick the
    wrong row and every device of that shift is filed against the wrong batch,
    and `mark_produced` refuses to say otherwise ever again — a device is
    produced once.

    This is the ONE reference in the log that a later correction may rewrite,
    because it records a CHOICE MADE AT THE BENCH rather than something that
    happened. The event is not replaced and nothing is reversed: its
    `production_run_id` moves, its note keeps where it came from, and the audit
    row names who moved it. Everything else in a device's history stays
    append-only — a delivery is undone by `unshipped`, never by editing.
    """
    moved, skipped = [], []
    for did in device_ids:
        d = db.get(M.DeviceUnit, did)
        if d is None:
            skipped.append({"device_id": did, "reason": "no such device"})
            continue
        if d.project_id != run.project_id:
            skipped.append({"device_id": did, "serial": d.serial,
                            "reason": f"device belongs to project {d.project_id}, the batch to "
                                      f"{run.project_id}"})
            continue
        ev = next((e for e in d.events if e.kind == "produced"), None)
        if ev is None:
            skipped.append({"device_id": did, "serial": d.serial,
                            "reason": "never produced; link it with POST /api/runs/{id}/produced"})
            continue
        if ev.production_run_id == run.id:
            skipped.append({"device_id": did, "serial": d.serial, "reason": "already in this batch"})
            continue
        was = ev.production_run_id
        # The bench wrote the SAME choice onto every attempt it made for this
        # device, so a correction that moves the produced event and leaves those
        # behind produces two answers to one question. Only the attempts that
        # name the batch we are moving AWAY from are the same mis-selection; an
        # attempt naming some other batch was a different choice and is left
        # alone, and one naming nothing stays nothing (never guess the batch).
        runs = [r for r in d.runs if r.production_run_id == was] if was else []
        moved.append({"device_id": d.id, "serial": d.serial, "from_run_id": was,
                      "to_run_id": run.id, "attempts": len(runs)})
        if not dry_run:
            ev.production_run_id = run.id
            ev.note = ((ev.note + " · ") if ev.note else "") + f"moved from batch {was}" + (
                f": {note}" if note else "")
            d.production_run_id = run.id
            for r in runs:
                r.production_run_id = run.id
    if not dry_run:
        db.flush()
    return {"dry_run": dry_run, "run_id": run.id, "moved": moved, "skipped": skipped}


# ------------------------------------------------------------------- stock


def _run_basis_qty(run: M.ProductionRun) -> int:
    return int(run.qty_good or run.plan_qty or run.qty or 0)


def run_stock(db: Session, project_id: int | None = None) -> list[dict]:
    """Finished devices per batch, both counting paths side by side (§8, §9)."""
    q = db.query(M.ProductionRun)
    if project_id:
        q = q.filter(M.ProductionRun.project_id == project_id)
    runs = q.order_by(M.ProductionRun.project_id, M.ProductionRun.run_date, M.ProductionRun.id).all()
    if not runs:
        return []
    rids = [r.id for r in runs]
    produced: dict[int, int] = defaultdict(int)
    in_stock: dict[int, int] = defaultdict(int)
    available: dict[int, int] = defaultdict(int)
    shipped: dict[int, int] = defaultdict(int)
    held: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for rid, state, cond, n in _device_counts(db, rids):
        produced[rid] += n
        cond = cond or "ok"
        if state == "in_stock":
            in_stock[rid] += n
            if cond == "ok":
                available[rid] += n
            else:
                held[rid][cond] += n
        elif state == "shipped":
            shipped[rid] += n
    unser: dict[int, int] = defaultdict(int)
    unser_returned: dict[int, int] = defaultdict(int)
    for sl, sh in (db.query(M.ShipmentLine, M.Shipment).join(M.Shipment)
                   .filter(M.ShipmentLine.source_run_id.in_(rids)).all()):
        if sh.kind == "delivery":
            unser[sl.source_run_id] += sl.qty_unserialized or 0
        else:
            unser_returned[sl.source_run_id] += sl.qty_unserialized or 0
    projects = {p.id: p.name for p in db.query(M.Project).all()}
    out = []
    for r in runs:
        # A batch that is still planned holds nothing yet: only its devices,
        # of which it has none, count. The planned quantity is a plan.
        typed = 0 if (r.status or "").strip().lower() == "planned" else _run_basis_qty(r)
        # BUILT means finished and passed (user rule, 2026-09-10). A batch that
        # has device records is counted from them and from nothing else: the
        # typed quantity is what was ordered or assembled, and boards that never
        # passed programming are not stock. Only a batch with NO device records
        # (prototypes from before the flasher wrote records) is counted from its
        # quantity, and that is the only place an unserialized unit can come from.
        if produced[r.id]:
            basis, legacy_pool = produced[r.id], 0
        else:
            basis = typed
            legacy_pool = typed  # units never recorded as devices
        legacy_stock = legacy_pool - unser[r.id] + unser_returned[r.id]
        out.append({
            "run_id": r.id, "label": r.label, "project_id": r.project_id,
            "project": projects.get(r.project_id, "?"), "board": r.board, "variant": r.variant,
            "run_date": r.run_date, "status": r.status,
            "built": basis,
            "qty_recorded": typed,
            "devices_produced": produced[r.id],
            "devices_in_stock": in_stock[r.id],
            # AVAILABLE is what a shipment may draw; HELD is present but not
            # sellable, per condition. `devices_in_stock` is their sum, so a
            # faulty unit is never invisible and never shippable.
            "devices_available": available[r.id],
            "devices_held": dict(held[r.id]),
            "devices_shipped": shipped[r.id],
            "unserialized_shipped": unser[r.id],
            "legacy_stock": max(legacy_stock, 0),
            # Negative = more units shipped than the batch is recorded to hold:
            # a quantity on the run is wrong, or a shipment is.
            "overdrawn": -legacy_stock if legacy_stock < 0 else 0,
            "stock": in_stock[r.id] + max(legacy_stock, 0),
            "available": available[r.id] + max(legacy_stock, 0),
        })
    return out


def check_unserialized_source(db: Session, run_id: int | None, qty: int) -> None:
    """Refuse an anonymous unit drawn from a batch that knows its own units.

    A unit with no serial only exists because its batch was made before the
    flasher recorded MACs (decision 0003 §8), and `run_stock` says so in
    arithmetic: a batch with ANY device record has a legacy pool of ZERO. Every
    unit charged to it beyond that is `overdrawn` — a figure that reads as a
    warning about the batch when it is really a contradiction in the shipment.

    Writing them anyway is what put 40 impossible units on two orders on
    2026-09-17. The rule is now enforced where they are written, not reported
    afterwards on a page nobody was looking at (user decision 2026-09-18).
    """
    if not run_id or qty <= 0:
        return
    run = db.get(M.ProductionRun, run_id)
    if run is None:
        raise HTTPException(404, f"no run {run_id}")
    n = (db.query(M.DeviceUnit).filter(M.DeviceUnit.production_run_id == run_id).count())
    if n:
        raise HTTPException(409, {
            "error": "that batch records its devices, so it has no units without a serial",
            "run_id": run_id, "label": run.label, "device_records": n, "requested": qty,
            "hint": "name the devices, or charge the units to a batch the flasher never recorded"})


def _device_counts(db: Session, rids: list[int]):
    """(run, state, condition, n). CONDITION is grouped too, because a unit that
    is present but unsellable is still in stock and must be counted — it is just
    not available. Collapsing the two is what forced 32 faulty units to be filed
    `disposed`, which said they were destroyed."""
    from sqlalchemy import func
    return (db.query(M.DeviceUnit.production_run_id, M.DeviceUnit.state,
                     M.DeviceUnit.condition, func.count(M.DeviceUnit.id))
            .filter(M.DeviceUnit.production_run_id.in_(rids))
            .group_by(M.DeviceUnit.production_run_id, M.DeviceUnit.state,
                      M.DeviceUnit.condition).all())


def refresh_order_status(order: M.SalesOrder) -> str:
    if order.cancelled:
        order.status = "cancelled"
        return order.status
    ordered = sum(li.qty_ordered or 0 for li in order.lines)
    shipped = sum(line_shipped(li) for li in order.lines)
    if ordered and shipped >= ordered:
        order.status = "fulfilled"
    elif shipped > 0:
        order.status = "partial"
    else:
        order.status = "open"
    return order.status


def live_shipped_events(db: Session, line_ids: list[int]) -> list[M.DeviceEvent]:
    """The `shipped` events on these lines that are still true.

    The log is append-only, so reversing a delivery does not delete the
    `shipped` row — an `unshipped` event lands after it (decision 0003 §6 for a
    return that corrects a FIFO guess, decision 0027 for a stock count that
    does). Every fulfilment figure must therefore NET the pair out, or the
    correction reads as a second delivery. The pairing is per device and
    shipment, newest `shipped` first, so a device shipped, reversed and shipped
    again on the same delivery still counts once.
    """
    if not line_ids:
        return []
    wanted = set(line_ids)
    dids = [r[0] for r in db.query(M.DeviceEvent.device_id)
            .filter(M.DeviceEvent.order_line_id.in_(line_ids),
                    M.DeviceEvent.kind == "shipped").distinct()]
    if not dids:
        return []
    open_: dict[tuple[int, int | None], list[M.DeviceEvent]] = defaultdict(list)
    for e in (db.query(M.DeviceEvent)
              .filter(M.DeviceEvent.device_id.in_(dids),
                      M.DeviceEvent.kind.in_(("shipped", "unshipped")))
              .order_by(M.DeviceEvent.device_id, M.DeviceEvent.at, M.DeviceEvent.id).all()):
        key = (e.device_id, e.shipment_id)
        if e.kind == "shipped":
            open_[key].append(e)
        elif open_[key]:
            open_[key].pop()
    return [e for stack in open_.values() for e in stack if e.order_line_id in wanted]


def live_shipped_of(device: M.DeviceUnit) -> list[M.DeviceEvent]:
    """This device's `shipped` events that no `unshipped` has reversed, paired
    the same way `live_shipped_events` pairs them. `DeviceUnit.events` is
    ordered by `at, id`, which is the order the pairing needs."""
    open_: dict[int | None, list[M.DeviceEvent]] = defaultdict(list)
    for e in device.events:
        if e.kind == "shipped":
            open_[e.shipment_id].append(e)
        elif e.kind == "unshipped" and open_[e.shipment_id]:
            open_[e.shipment_id].pop()
    return [e for stack in open_.values() for e in stack]


def line_shipped(li: M.SalesOrderLine) -> int:
    """Fulfilment: `shipped` events with no replaced device that nothing has
    reversed, plus unserialized units on delivery shipments."""
    sess = _session_of(li)
    n = sum(1 for e in live_shipped_events(sess, [li.id]) if e.replaces_device_id is None)
    u = sum(sl.qty_unserialized or 0 for sl, sh in
            sess.query(M.ShipmentLine, M.Shipment).join(M.Shipment)
            .filter(M.ShipmentLine.order_line_id == li.id, M.Shipment.kind == "delivery").all())
    return n + u


def _session_of(obj) -> Session:
    from sqlalchemy.orm import object_session
    s = object_session(obj)
    assert s is not None
    return s


def get_customer(db: Session, name: str, create: bool = True) -> M.Customer:
    name = (name or "").strip() or "(unknown customer)"
    c = db.query(M.Customer).filter(M.Customer.name == name).first()
    if c is None and create:
        c = M.Customer(name=name)
        db.add(c)
        db.flush()
    if c is None:
        raise HTTPException(404, f"no customer named {name!r}")
    return c


def order_total_net(order: M.SalesOrder) -> float:
    return sum((li.qty_ordered or 0) * (li.unit_price or 0) for li in order.lines)


def invoice_due_date(order: M.SalesOrder, issue_date: str) -> str:
    try:
        d = datetime.fromisoformat(issue_date[:10])
    except (ValueError, TypeError):
        return ""
    return (d + timedelta(days=order.customer.payment_terms_days or 14)).date().isoformat()


# --------------------------------------------------------------- shipments


def create_shipment(db: Session, order: M.SalesOrder, *, kind: str = "delivery", shipped_at: str = "",
                    delivery_note: str = "", tracking: str = "", notes: str = "",
                    lines: list[dict], actor: str = "") -> M.Shipment:
    """A delivery. Each entry in `lines` names an order line and ONE of:
    explicit `device_ids`, a `qty` to draw FIFO from `run_ids`, or a legacy
    `qty_unserialized` from `source_run_id`. A `replaces_device_id` marks a
    single-device warranty replacement charged to the order (§7)."""
    if kind != "delivery":
        raise HTTPException(422, "use return_device for returns")
    if order.cancelled:
        raise HTTPException(409, "the order is cancelled")
    by_id = {li.id: li for li in order.lines}
    sh = M.Shipment(order_id=order.id, kind="delivery", shipped_at=shipped_at or "",
                    delivery_note=delivery_note or "", tracking=tracking or "", notes=notes or "")
    db.add(sh)
    db.flush()
    at = _date_at(shipped_at)
    moved = 0
    for spec in lines:
        li = by_id.get(int(spec.get("order_line_id") or 0))
        if li is None:
            raise HTTPException(422, f"order line {spec.get('order_line_id')} is not on this order")
        replaces = spec.get("replaces_device_id")
        device_ids = [int(x) for x in (spec.get("device_ids") or [])]
        qty = int(spec.get("qty") or 0)
        run_ids = [int(x) for x in (spec.get("run_ids") or [])]
        unser = int(spec.get("qty_unserialized") or 0)
        picked: list[tuple[M.DeviceUnit, bool]] = []
        for did in device_ids:
            d = db.get(M.DeviceUnit, did)
            if d is None:
                raise HTTPException(404, f"no device {did}")
            if d.project_id != li.project_id:
                raise HTTPException(422, f"device {d.serial or did} belongs to another project")
            if d.state not in ("in_stock", "allocated"):
                raise HTTPException(409, f"device {d.serial or did} is {d.state or 'unrecorded'}, not in stock")
            # A unit that is HERE but not sellable is still in stock — that is
            # the point of `condition`. Only `ok` may leave on a shipment.
            if (d.condition or "ok") != "ok":
                raise HTTPException(409, {
                    "error": f"device {d.serial or did} is {d.condition}, which cannot be shipped",
                    "device_id": d.id, "serial": d.serial, "condition": d.condition,
                    "hint": "repair it and set its condition to ok, or ship a different device"})
            picked.append((d, False))
        # A SHIPMENT NAMES ITS DEVICES. There is no automatic pick: a quantity
        # with no serials behind it is a guess, and a guess is indistinguishable
        # from an observation once it is written. 4326 of 4427 deliveries in
        # this platform were such guesses, and a physical count was the only
        # thing that could find the wrong ones.
        if qty > 0:
            raise HTTPException(422, {
                "error": "name the devices; a shipment is a set of serials, not a quantity",
                "order_line_id": li.id, "requested": qty,
                "hint": "scan or paste the serials that physically left"})
        if replaces is not None and len(picked) != 1:
            raise HTTPException(422, "a replacement shipment names exactly one device")
        for d, auto in picked:
            rep = int(replaces) if replaces is not None else None
            # Re-shipped after repair: its own replacement, counted once. A
            # delivery an `unshipped` event REVERSED is not a previous
            # delivery, so `live_shipped_of` and not `d.events` — otherwise a
            # device the stock count put back on the shelf ships again as a
            # replacement and never counts (decision 0027).
            if rep is None and any(e.order_line_id == li.id for e in live_shipped_of(d)):
                rep = d.id
            record_event(db, d, "shipped", at=at, actor=actor, auto=auto, order_line_id=li.id,
                         shipment_id=sh.id, replaces_device_id=rep,
                         note=(spec.get("note") or ""))
            moved += 1
        if unser > 0:
            src = spec.get("source_run_id")
            if src:
                check_unserialized_source(db, int(src), unser)
                avail = next((s for s in run_stock(db, li.project_id) if s["run_id"] == int(src)), None)
                if avail is None:
                    raise HTTPException(404, f"no run {src} in project {li.project_id}")
                if avail["legacy_stock"] < unser:
                    raise HTTPException(409, {"error": "not enough unserialized units in that batch",
                                              "available": avail["legacy_stock"], "requested": unser,
                                              "order_line_id": li.id})
            # No source batch = units the platform never built (prototypes from
            # before any run): fulfilment counts them, cost reports them uncosted.
            db.add(M.ShipmentLine(shipment_id=sh.id, order_line_id=li.id,
                                  qty_unserialized=unser, source_run_id=int(src) if src else None))
            moved += unser
    if moved == 0:
        raise HTTPException(422, "the shipment moves nothing")
    db.flush()
    refresh_order_status(order)
    return sh


def reverse_shipment(db: Session, sh: M.Shipment, *, actor: str = "", note: str = "",
                     dry_run: bool = True) -> dict:
    """Take back a shipment that was recorded in error.

    Every delivery it still carries is reversed with an `unshipped` event and
    its anonymous units go to zero, so the shipment counts nothing and its
    devices are back in stock. The header and the events STAY: decision 0003
    keeps device history, and a delivery that was recorded and withdrawn is
    part of it. Reversing a delivery the customer actually received is a
    RETURN, not this.
    """
    dids = {e.device_id for e in db.query(M.DeviceEvent)
            .filter(M.DeviceEvent.shipment_id == sh.id, M.DeviceEvent.kind == "shipped")}
    units = {d.id: d for d in db.query(M.DeviceUnit).filter(M.DeviceUnit.id.in_(dids or [-1])).all()}
    live = [e for d in units.values() for e in live_shipped_of(d) if e.shipment_id == sh.id]
    unser = [sl for sl in sh.lines if (sl.qty_unserialized or 0) > 0]
    plan = {
        "dry_run": dry_run, "shipment_id": sh.id, "order_id": sh.order_id,
        "devices": [{"device_id": e.device_id, "order_line_id": e.order_line_id} for e in live],
        "unserialized": [{"order_line_id": sl.order_line_id, "source_run_id": sl.source_run_id,
                          "qty": sl.qty_unserialized} for sl in unser],
    }
    if dry_run:
        return plan
    for e in live:
        record_event(db, db.get(M.DeviceUnit, e.device_id), "unshipped", actor=actor,
                     shipment_id=sh.id, auto=False,
                     note=note or "the shipment was recorded in error and taken back")
    for sl in unser:
        sl.qty_unserialized = 0
    db.flush()
    db.expire(sh.order, ["shipments", "lines"])
    refresh_order_status(sh.order)
    return plan


def return_device(db: Session, device: M.DeviceUnit, *, order_line: M.SalesOrderLine | None,
                  reason: str = "", returned_at: str = "", shipment: M.Shipment | None = None,
                  actor: str = "", note: str = "") -> dict:
    """A device came back from the customer it was shipped to.

    It must have a live delivery against the line it is returned from. It used
    to be accepted against any line, and the platform would then SWAP: un-ship
    whichever device FIFO had guessed into that slot and put this one there
    instead, or convert an anonymous unit into this device. That was automatic
    data fixing dressed as a normal operation — a return quietly rewrote a
    delivery nobody was looking at.

    A return against a line this device was never shipped to is now an ERROR.
    Either the delivery record is wrong, in which case correct the shipment, or
    the device is not the one that came back.
    """
    if device.state == "disposed":
        raise HTTPException(409, "the device was disposed of")
    live = live_shipped_of(device)
    if order_line is None:
        ev = live[-1] if live else None
        if ev is None:
            raise HTTPException(422, "say which order the device came back from")
        order_line = db.get(M.SalesOrderLine, ev.order_line_id)
    if not any(e.order_line_id == order_line.id for e in live):
        raise HTTPException(409, {
            "error": f"device {device.serial or device.id} was never delivered on that order line, "
                     f"so it cannot come back from it",
            "device_id": device.id, "serial": device.serial,
            "order_line_id": order_line.id, "device_state": device.state,
            "delivered_on": sorted({e.order_line_id for e in live if e.order_line_id}),
            "hint": "correct the shipment that is wrong, then record the return"})
    order = order_line.order
    at = _date_at(returned_at)
    if shipment is None:
        shipment = M.Shipment(order_id=order.id, kind="return", shipped_at=returned_at or "",
                              notes=note or "")
        db.add(shipment)
        db.flush()
    record_event(db, device, "returned", at=at, actor=actor, reason=reason or "", note=note or "",
                 order_line_id=order_line.id, shipment_id=shipment.id)
    db.flush()
    refresh_order_status(order)
    return {"shipment_id": shipment.id}


def repair_device(db: Session, device: M.DeviceUnit, *, outcome: str = "to_stock",
                  cost_lines: list[dict] | None = None, repaired_at: str = "",
                  actor: str = "", note: str = "") -> M.DeviceEvent:
    if device.state != "returned":
        raise HTTPException(409, f"device is {device.state or 'unrecorded'}, not returned")
    if outcome not in ("to_stock", "dispose"):
        raise HTTPException(422, "outcome is to_stock or dispose")
    at = _date_at(repaired_at)
    ev = record_event(db, device, "repaired", at=at, actor=actor, note=note or "")
    db.flush()
    for cl in cost_lines or []:
        kind = (cl.get("kind") or "material").strip()
        if kind not in ("labour", "material"):
            raise HTTPException(422, "repair cost kind is labour or material")
        db.add(M.RepairCostLine(event_id=ev.id, kind=kind, amount=float(cl.get("amount") or 0),
                                currency=(cl.get("currency") or "PLN").upper(),
                                component_id=cl.get("component_id"), qty=float(cl.get("qty") or 1),
                                note=cl.get("note") or ""))
    if outcome == "dispose":
        record_event(db, device, "disposed", at=at + timedelta(seconds=1), actor=actor,
                     reason="unrepairable", note=note or "")
    db.flush()
    return ev


def dispose_device(db: Session, device: M.DeviceUnit, *, reason: str = "", disposed_at: str = "",
                   actor: str = "", note: str = "") -> M.DeviceEvent:
    if device.state not in ("returned", "in_stock"):
        raise HTTPException(409, f"device is {device.state or 'unrecorded'}; only a returned or "
                                 "in-stock device can be disposed of")
    return record_event(db, device, "disposed", at=_date_at(disposed_at), actor=actor,
                        reason=reason or "", note=note or "")


# ------------------------------------------------- correcting a FIFO guess

def allocate_devices(db: Session, line: M.SalesOrderLine, device_ids: list[int], actor: str = "") -> int:
    n = 0
    for did in device_ids:
        d = db.get(M.DeviceUnit, did)
        if d is None or d.state != "in_stock":
            raise HTTPException(409, f"device {did} is not in stock")
        record_event(db, d, "allocated", actor=actor, order_line_id=line.id)
        n += 1
    return n


# ---------------------------------------------------------------- economics


def per_device_cost_usd(db: Session, register: dict | None = None) -> dict[int, float]:
    """Actual production cost per device PRODUCED, per run, in USD — the figure
    a device carries with it onto whatever order ships it.

    **This is the one link between a batch and an order** (user decision
    2026-09-19): a batch computes what one unit cost, a unit carries it, and an
    order's cost is the sum over the units it shipped. Nothing else joins the
    two, which is why a run no longer records a sale of its own.

    The denominator is the count of `produced` events on the batch — devices
    the platform can name. It used to be the run's typed `qty`, the boards
    ORDERED FROM JLC, despite this docstring already claiming otherwise: a batch
    routinely yields a different number from the one ordered (CE_Dongle_V2 Batch
    5, 455 ordered against 568 produced), so the figure was wrong by the yield
    on every batch.

    A batch with no device records yet is ABSENT from the result rather than
    divided by a guess. An order shipping such a device reports it as
    `uncosted`, which is true and visible, where a planned-quantity estimate
    would have been neither.
    """
    reg = register or run_actuals.invoice_register(db)
    counts = run_actuals.produced_counts(db, [int(rid) for rid in (reg.get("by_run_usd") or {})])
    out: dict[int, float] = {}
    for rid, money in (reg.get("by_run_usd") or {}).items():
        made = counts.get(int(rid)) or 0
        if made <= 0:
            continue
        out[int(rid)] = (money.get("total_usd") or 0.0) / made
    return out


def _to_usd(db: Session, amount: float, currency: str, date_iso: str, cache: dict,
            unknown: set[str]) -> float:
    cur = (currency or "USD").upper()
    if cur == "USD" or not amount:
        return amount
    key = date_iso or ""
    if key not in cache:
        cache[key] = fx.rates_at(db, _as_dt(key)) if key else fx.get_rates(db)
    v, known = fx.convert(amount, cur, "USD", cache[key])
    if not known:
        unknown.add(cur)
    return v


def order_economics(db: Session, order: M.SalesOrder, unit_cost: dict[int, float]) -> dict:
    cache: dict = {}
    unknown: set[str] = set()
    cur = (order.currency or "PLN").upper()
    money_invoices = [i for i in order.invoices if i.kind in MONEY_KINDS]
    if money_invoices:
        revenue_net = sum(i.net_amount or 0 for i in money_invoices)
        revenue_usd = sum(_to_usd(db, i.net_amount or 0, i.currency or cur, i.issue_date, cache, unknown)
                          for i in money_invoices)
        basis = "invoices"
    else:
        revenue_net = order_total_net(order)
        revenue_usd = _to_usd(db, revenue_net, cur, order.order_date, cache, unknown)
        basis = "order"
    devices_cost = 0.0
    uncosted = 0
    shipped_devices = 0
    replacements = 0
    line_ids = [li.id for li in order.lines]
    # A delivery an `unshipped` event reversed is not charged to the order:
    # the device never went, so its production cost is still stock.
    live = live_shipped_events(db, line_ids)
    units = {d.id: d for d in db.query(M.DeviceUnit)
             .filter(M.DeviceUnit.id.in_([e.device_id for e in live] or [-1])).all()}
    evs = [(e, units[e.device_id]) for e in live if e.device_id in units]
    for ev, d in evs:
        shipped_devices += 1
        if ev.replaces_device_id is not None:
            replacements += 1
        if d.production_run_id in unit_cost:
            devices_cost += unit_cost[d.production_run_id]
        else:
            uncosted += 1
    unser_units = 0
    for sl, sh in (db.query(M.ShipmentLine, M.Shipment).join(M.Shipment)
                   .filter(M.ShipmentLine.order_line_id.in_(line_ids or [-1]), M.Shipment.kind == "delivery")):
        n = sl.qty_unserialized or 0
        unser_units += n
        if sl.source_run_id in unit_cost:
            devices_cost += n * unit_cost[sl.source_run_id]
        else:
            uncosted += n
    repair_usd = 0.0
    repair_ids = [e.device_id for e, _ in evs]
    if repair_ids:
        for ev in (db.query(M.DeviceEvent).filter(M.DeviceEvent.device_id.in_(repair_ids),
                                                    M.DeviceEvent.kind == "repaired").all()):
            # charged to the order the device was LAST shipped to before the repair
            dev = db.get(M.DeviceUnit, ev.device_id)
            prior = [e for e in dev.events if e.kind == "shipped" and e.at <= ev.at]
            if not prior or prior[-1].order_line_id not in line_ids:
                continue
            for cl in ev.cost_lines:
                repair_usd += _to_usd(db, (cl.amount or 0) * (cl.qty or 1), cl.currency,
                                      ev.at.date().isoformat(), cache, unknown)
    cost_usd = devices_cost + repair_usd
    margin = revenue_usd - cost_usd
    return {
        "currency": cur,
        "revenue_net": _round(revenue_net),
        "revenue_basis": basis,
        "revenue_usd": _round(revenue_usd),
        "devices_cost_usd": _round(devices_cost),
        "repair_cost_usd": _round(repair_usd),
        "cost_usd": _round(cost_usd),
        "margin_usd": _round(margin),
        "margin_pct": _round(margin / revenue_usd * 100) if revenue_usd else None,
        "shipped_devices": shipped_devices,
        "shipped_unserialized": unser_units,
        "replacements": replacements,
        "uncosted_units": uncosted,
        "unknown_currencies": sorted(unknown),
    }


# ------------------------------------------------------------------- JSON


def customer_json(c: M.Customer) -> dict:
    return {"id": c.id, "name": c.name, "tax_id": c.tax_id, "address": c.address,
            "payment_terms_days": c.payment_terms_days, "notes": c.notes,
            "created_at": c.created_at.isoformat() if c.created_at else None}


def invoice_json(i: M.OrderInvoice, order: M.SalesOrder) -> dict:
    return {"id": i.id, "order_id": i.order_id, "kind": i.kind, "number": i.number,
            "issue_date": i.issue_date, "due_date": i.due_date, "net_amount": i.net_amount,
            "currency": i.currency or order.currency, "paid_at": i.paid_at,
            "attachment_id": i.attachment_id, "notes": i.notes}


def _line_counts(db: Session, line_ids: list[int]) -> dict[int, dict]:
    from sqlalchemy import func
    out = {lid: {"shipped": 0, "replacements": 0, "returned": 0, "unserialized": 0, "allocated": 0}
           for lid in line_ids}
    if not line_ids:
        return out
    for e in live_shipped_events(db, line_ids):
        c = out[e.order_line_id]
        c["shipped" if e.replaces_device_id is None else "replacements"] += 1
    for lid, n in (db.query(M.DeviceEvent.order_line_id, func.count(M.DeviceEvent.id))
                   .filter(M.DeviceEvent.order_line_id.in_(line_ids),
                           M.DeviceEvent.kind == "returned")
                   .group_by(M.DeviceEvent.order_line_id).all()):
        out[lid]["returned"] += n
    for lid, n in (db.query(M.ShipmentLine.order_line_id, func.sum(M.ShipmentLine.qty_unserialized))
                   .join(M.Shipment).filter(M.ShipmentLine.order_line_id.in_(line_ids),
                                            M.Shipment.kind == "delivery")
                   .group_by(M.ShipmentLine.order_line_id).all()):
        out[lid]["unserialized"] += int(n or 0)
    # allocated NOW = devices whose state is allocated and whose last allocation names this line
    for d in db.query(M.DeviceUnit).filter(M.DeviceUnit.state == "allocated").all():
        ev = last_event(d, "allocated")
        if ev is not None and ev.order_line_id in out:
            out[ev.order_line_id]["allocated"] += 1
    return out


def order_json(db: Session, order: M.SalesOrder, *, with_detail: bool = False,
               unit_cost: dict[int, float] | None = None, projects: dict[int, str] | None = None) -> dict:
    projects = projects or {p.id: p.name for p in db.query(M.Project).all()}
    counts = _line_counts(db, [li.id for li in order.lines])
    lines = []
    for li in order.lines:
        c = counts[li.id]
        fulfilled = c["shipped"] + c["unserialized"]
        lines.append({
            "id": li.id, "project_id": li.project_id, "project": projects.get(li.project_id, "?"),
            "board": li.board, "variant": li.variant, "product": li.product,
            "qty_ordered": li.qty_ordered, "unit_price": li.unit_price,
            "net_total": _round((li.qty_ordered or 0) * (li.unit_price or 0)),
            "qty_shipped": fulfilled, "qty_open": max((li.qty_ordered or 0) - fulfilled, 0),
            "qty_shipped_devices": c["shipped"], "qty_shipped_unserialized": c["unserialized"],
            "qty_replacements": c["replacements"], "qty_returned": c["returned"],
            "qty_allocated": c["allocated"], "migrated_from_run_id": li.migrated_from_run_id,
        })
    money = [i for i in order.invoices if i.kind in MONEY_KINDS]
    invoiced_net = sum(i.net_amount or 0 for i in money)
    total_net = order_total_net(order)
    out = {
        "id": order.id, "customer_id": order.customer_id, "customer": order.customer.name,
        "order_ref": order.order_ref, "order_date": order.order_date, "currency": order.currency,
        "vat_pct": order.vat_pct, "status": order.status, "cancelled": order.cancelled,
        "notes": order.notes, "created_at": order.created_at.isoformat() if order.created_at else None,
        "lines": lines,
        "qty_ordered": sum(li.qty_ordered or 0 for li in order.lines),
        "qty_shipped": sum(ln["qty_shipped"] for ln in lines),
        "total_net": _round(total_net),
        "invoiced_net": _round(invoiced_net),
        # The sum check (§3): a warning in the UI, never a block.
        "invoice_gap": _round(total_net - invoiced_net),
        "invoice_count": len(order.invoices),
        "unpaid_count": sum(1 for i in money if not i.paid_at),
    }
    if with_detail:
        out["invoices"] = [invoice_json(i, order) for i in order.invoices]
        out["shipments"] = [shipment_json(db, sh) for sh in order.shipments]
        uc = unit_cost if unit_cost is not None else per_device_cost_usd(db)
        out["economics"] = order_economics(db, order, uc)
    return out


def shipment_json(db: Session, sh: M.Shipment) -> dict:
    evs = (db.query(M.DeviceEvent, M.DeviceUnit)
           .join(M.DeviceUnit, M.DeviceEvent.device_id == M.DeviceUnit.id)
           .filter(M.DeviceEvent.shipment_id == sh.id,
                   M.DeviceEvent.kind.in_(("shipped", "returned", "unshipped")))
           .order_by(M.DeviceEvent.at, M.DeviceEvent.id).all())
    live: dict[int, tuple] = {}
    for ev, d in evs:
        if ev.kind == "unshipped":
            live.pop(ev.device_id, None)
        else:
            live[ev.device_id] = (ev, d)
    devices = [{"device_id": d.id, "serial": d.serial, "mac": d.mac or "", "state": d.state,
                "order_line_id": ev.order_line_id, "auto": ev.auto,
                "replaces_device_id": ev.replaces_device_id, "run_id": d.production_run_id}
               for ev, d in live.values()]
    per_line: dict[int, int] = defaultdict(int)
    for dv in devices:
        per_line[dv["order_line_id"]] += 1
    unser = [{"order_line_id": sl.order_line_id, "qty_unserialized": sl.qty_unserialized,
              "source_run_id": sl.source_run_id} for sl in sh.lines]
    for u in unser:
        per_line[u["order_line_id"]] += u["qty_unserialized"] or 0
    # `devices` is what the shipment still carries, so a fully reversed
    # delivery shows none — and would read as deletable, which it is not:
    # `delete_shipment` refuses while ANY event names the shipment, reversed
    # or not. The row says so itself rather than letting the button promise
    # something the API answers 409 to.
    reversed_n = sum(1 for ev, _ in evs if ev.kind == "unshipped")
    return {"id": sh.id, "order_id": sh.order_id, "kind": sh.kind, "shipped_at": sh.shipped_at,
            "delivery_note": sh.delivery_note, "tracking": sh.tracking, "notes": sh.notes,
            "qty": sum(per_line.values()), "per_line": dict(per_line),
            "devices": devices, "unserialized": unser,
            "reversed": reversed_n, "deletable": not evs}


def device_history_json(db: Session, device: M.DeviceUnit) -> dict:
    runs = {r.id: r.label for r in db.query(M.ProductionRun).all()}
    lines = {}
    orders = {}
    events = []
    for ev in device.events:
        li = None
        if ev.order_line_id:
            li = lines.get(ev.order_line_id) or db.get(M.SalesOrderLine, ev.order_line_id)
            lines[ev.order_line_id] = li
            if li is not None and li.order_id not in orders:
                orders[li.order_id] = li.order
        rep = db.get(M.DeviceUnit, ev.replaces_device_id) if ev.replaces_device_id else None
        events.append({
            "id": ev.id, "kind": ev.kind, "at": ev.at.isoformat() if ev.at else None, "actor": ev.actor,
            "note": ev.note, "reason": ev.reason, "auto": ev.auto,
            "production_run_id": ev.production_run_id,
            "production_run": runs.get(ev.production_run_id or 0),
            "order_line_id": ev.order_line_id,
            "order_id": li.order_id if li else None,
            "order_ref": (orders[li.order_id].order_ref if li else None),
            "customer": (orders[li.order_id].customer.name if li else None),
            "product": li.product if li else None,
            "shipment_id": ev.shipment_id,
            "replaces_device_id": ev.replaces_device_id,
            "replaces_serial": rep.serial if rep else None,
            "cost_lines": [{"id": c.id, "kind": c.kind, "amount": c.amount, "currency": c.currency,
                            "component_id": c.component_id, "qty": c.qty, "note": c.note}
                           for c in ev.cost_lines],
        })
    return {"device_id": device.id, "state": device.state, "production_run_id": device.production_run_id,
            "production_run": runs.get(device.production_run_id or 0), "events": events}


# ---------------------------------------------------------------- migration


def run_sales_json(db: Session, run: M.ProductionRun) -> dict:
    """What a run page shows about the sale side now: the order lines its
    units went to, and `qty_sold` DERIVED from shipments (§9)."""
    from sqlalchemy import func
    devices = (db.query(func.count(M.DeviceEvent.id))
               .join(M.DeviceUnit, M.DeviceEvent.device_id == M.DeviceUnit.id)
               .filter(M.DeviceUnit.production_run_id == run.id, M.DeviceEvent.kind == "shipped")
               .scalar() or 0)
    unser = 0
    lines: dict[int, int] = defaultdict(int)
    for sl, sh in (db.query(M.ShipmentLine, M.Shipment).join(M.Shipment)
                   .filter(M.ShipmentLine.source_run_id == run.id, M.Shipment.kind == "delivery")):
        unser += sl.qty_unserialized or 0
        lines[sl.order_line_id] += sl.qty_unserialized or 0
    for lid, n in (db.query(M.DeviceEvent.order_line_id, func.count(M.DeviceEvent.id))
                   .join(M.DeviceUnit, M.DeviceEvent.device_id == M.DeviceUnit.id)
                   .filter(M.DeviceUnit.production_run_id == run.id, M.DeviceEvent.kind == "shipped")
                   .group_by(M.DeviceEvent.order_line_id).all()):
        lines[lid] += n
    orders = []
    for lid, n in lines.items():
        li = db.get(M.SalesOrderLine, lid)
        if li is None:
            continue
        orders.append({"order_id": li.order_id, "order_ref": li.order.order_ref,
                       "customer": li.order.customer.name, "order_line_id": li.id,
                       "product": li.product, "qty_from_run": n})
    stock = next((s for s in run_stock(db, run.project_id) if s["run_id"] == run.id), None)
    return {"qty_sold_derived": devices + unser, "orders": orders, "stock": stock}


def project_demand(db: Session, project_id: int | None = None) -> list[dict]:
    """Open demand against supply, per project — the number the project window
    and the Orders page both ask for. Open demand is the unshipped part of
    every non-cancelled order line; supply is what is on the shelf, plus the
    devices ALLOCATED to those same open lines, plus what planned batches will
    build. Shortfall is what nothing yet covers."""
    q = (db.query(M.SalesOrderLine, M.SalesOrder)
         .join(M.SalesOrder)
         .filter(M.SalesOrder.cancelled.is_(False)))
    if project_id:
        q = q.filter(M.SalesOrderLine.project_id == project_id)
    open_qty: dict[int, int] = defaultdict(int)
    open_orders: dict[int, set[int]] = defaultdict(set)
    open_lines: set[int] = set()
    for li, o in q.all():
        left = max((li.qty_ordered or 0) - line_shipped(li), 0)
        if left:
            open_qty[li.project_id] += left
            open_orders[li.project_id].add(o.id)
            open_lines.add(li.id)
    shelf: dict[int, int] = defaultdict(int)
    planned: dict[int, int] = defaultdict(int)
    planned_runs: dict[int, list[dict]] = defaultdict(list)
    for r in run_stock(db, project_id):
        shelf[r["project_id"]] += r["stock"]
    # An ALLOCATED device is on the shelf, reserved for a line whose open
    # quantity is counted above — `run_stock` leaves it out of stock (decision
    # 0003 §9) and the line still asks to be filled, so without this a boxed
    # device reads as one to build. Only allocations against the lines this
    # demand is measuring count; an allocation to a line already fulfilled is
    # neither demand nor supply here.
    for d in db.query(M.DeviceUnit).filter(M.DeviceUnit.state == "allocated").all():
        ev = last_event(d, "allocated")
        if ev is not None and ev.order_line_id in open_lines:
            shelf[d.project_id] += 1
    rq = db.query(M.ProductionRun).filter(M.ProductionRun.status == "planned")
    if project_id:
        rq = rq.filter(M.ProductionRun.project_id == project_id)
    for r in rq.all():
        planned[r.project_id] += r.qty or 0
        planned_runs[r.project_id].append({"run_id": r.id, "label": r.label, "qty": r.qty or 0,
                                           "run_date": r.run_date or ""})
    projects = {p.id: p.name for p in db.query(M.Project).all()}
    ids = set(open_qty) | set(shelf) | set(planned)
    if project_id:
        ids = {project_id}
    out = []
    for pid in sorted(ids, key=lambda i: projects.get(i, "")):
        o, sh, pl = open_qty.get(pid, 0), shelf.get(pid, 0), planned.get(pid, 0)
        out.append({
            "project_id": pid, "project": projects.get(pid, f"#{pid}"),
            "open": o, "open_orders": len(open_orders.get(pid, ())),
            "on_shelf": sh, "planned": pl,
            "planned_runs": sorted(planned_runs.get(pid, []), key=lambda r: (r["run_date"], r["run_id"])),
            "shortfall": max(o - sh - pl, 0),
            "surplus": max(sh + pl - o, 0),
        })
    return out
