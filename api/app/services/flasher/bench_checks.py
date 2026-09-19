"""What the bench should say out loud before it programs the board in front of it.

The MAC read is the one moment the platform knows BOTH what is on the fixture
and what it already believes about that unit. Until 2026-09-19 it said nothing:
`_register_device` found or created the row in silence, and every disagreement
between the two had to be discovered months later by counting stock.

Two rules shape everything here (user decision 2026-09-19):

1. **Only a check that would WRITE SOMETHING FALSE may block.** Programming a
   unit that is at a customer, or faulty, or built in another batch, is
   ordinary bench work — 5,369 of 5,538 devices in this platform read
   `shipped`, so a rule that stopped on that would stop on almost everything
   and operators would learn to defeat it. Those are notices the operator
   acknowledges, with their name against the acknowledgement and a reason if
   they care to type one.
2. **Only the device's own project blocks.** A Dongle MAC on an Aqua run means
   the wrong fixture or the wrong project, and the run would file the unit
   under a project it does not belong to.

`DevicePresence` is read here but can never block: its own docstring says
nothing in it may gate a business decision. A device the broker heard from
this morning is EVIDENCE that the board on the bench may not be that board, and
evidence goes to the operator, not to a rule.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ... import models as M
from ..orders import utcnow

#: A batch nobody has added to for this long is finished in every sense but the
#: status field, which is free text and set by hand. Adding a unit to it
#: re-divides its whole cost pool, because `good_units` is DERIVED from the
#: device records (decision 0030) and nothing is frozen.
SETTLED_AFTER = timedelta(days=30)

#: States that mean the unit is not on our shelf. `returned` is absent on
#: purpose: a unit booked back in is exactly what a repair bench reprograms.
AWAY_STATES = ("shipped", "allocated", "disposed")


def _notice(level: str, code: str, text: str, hint: str = "", **data) -> dict:
    return {"level": level, "code": code, "text": text, "hint": hint, "data": data}


def for_device(db: Session, run: M.ProgrammingRun, dev: M.DeviceUnit, *,
               created: bool, project_id: int) -> list[dict]:
    """Everything worth saying about this unit, most serious first.

    `created` distinguishes a board the platform has never seen from one it
    has. A new row cannot be in the wrong project or at a customer, and an
    existing one cannot be the first unit of anything.
    """
    out: list[dict] = []
    batch = db.get(M.ProductionRun, run.production_run_id) if run.production_run_id else None

    if dev.project_id != project_id:
        other = db.get(M.Project, dev.project_id)
        out.append(_notice(
            "block", "wrong_project",
            f"{dev.serial or dev.mac} belongs to {other.name if other else dev.project_id}, "
            f"not to the project this run is filed under.",
            "Check the fixture, or start the run from the right project.",
            device_id=dev.id, device_project_id=dev.project_id))
        # Nothing below is meaningful once we know it is the wrong device.
        return out

    if not created:
        out.extend(_about_a_known_unit(db, dev, batch))
    if batch is not None:
        out.extend(_about_the_batch(db, batch, dev, created=created))
    return out


def _about_a_known_unit(db: Session, dev: M.DeviceUnit,
                        batch: M.ProductionRun | None) -> list[dict]:
    out: list[dict] = []

    if (dev.state or "") in AWAY_STATES:
        where = ""
        if dev.state == "shipped":
            ev = next((e for e in reversed(dev.events) if e.kind == "shipped"), None)
            line = db.get(M.SalesOrderLine, ev.order_line_id) if ev and ev.order_line_id else None
            order = db.get(M.SalesOrder, line.order_id) if line else None
            if order is not None:
                where = f" on order {order.order_ref or order.id}"
        out.append(_notice(
            "warn", "not_in_stock",
            f"{dev.serial or dev.mac} is recorded as {dev.state}{where}, not on our shelf.",
            "If it came back, record the return so stock and the order agree. "
            "Programming it does not book it back in.",
            device_id=dev.id, state=dev.state))

    if (dev.condition or "ok") != "ok":
        out.append(_notice(
            "warn", "condition_not_ok",
            f"{dev.serial or dev.mac} is marked {dev.condition}, so it cannot be shipped.",
            "If this is a repair, clear the condition once it passes — otherwise it "
            "stays on the shelf unsellable.",
            device_id=dev.id, condition=dev.condition))

    produced = next((e for e in dev.events if e.kind == "produced"), None)
    if (produced is not None and batch is not None
            and produced.production_run_id not in (None, batch.id)):
        built = db.get(M.ProductionRun, produced.production_run_id)
        out.append(_notice(
            "warn", "built_in_another_batch",
            f"{dev.serial or dev.mac} was built in {built.label if built else produced.production_run_id}. "
            f"This attempt is filed under {batch.label}.",
            "That is fine for a reflash: the unit keeps its original batch for cost, "
            "and this batch keeps the attempt.",
            device_id=dev.id, built_run_id=produced.production_run_id))

    pres = (db.query(M.DevicePresence)
            .filter(M.DevicePresence.device_unit_id == dev.id).one_or_none())
    if pres is not None and pres.online:
        seen = pres.last_seen_at.isoformat(timespec="minutes") if pres.last_seen_at else "recently"
        out.append(_notice(
            "warn", "online_elsewhere",
            f"The broker says {pres.topic} is ONLINE (last heard {seen}).",
            "A board cannot be on this bench and talking to the broker from somewhere "
            "else. Check the MAC — a duplicate means a cloned or refurbished module.",
            device_id=dev.id, topic=pres.topic))

    return out


def _about_the_batch(db: Session, batch: M.ProductionRun, dev: M.DeviceUnit, *,
                     created: bool) -> list[dict]:
    out: list[dict] = []
    n = (db.query(func.count(M.DeviceUnit.id))
         .filter(M.DeviceUnit.production_run_id == batch.id).scalar() or 0)

    # The check that would have stopped 2026-09-17, when the bench had Batch 8
    # selected — a batch whose boards had not been delivered — and 31 units were
    # filed against it before anybody noticed. It fires once, on unit one.
    if n == 0 and created:
        out.append(_notice(
            "warn", "first_unit_of_batch",
            f"This is the FIRST unit ever filed against {batch.label}.",
            "If you are programming boards from a batch that is already running, "
            "the wrong batch is selected.",
            run_id=batch.id, label=batch.label))
        return out

    planned = batch.plan_qty or batch.qty or 0
    if created and planned and n >= planned:
        out.append(_notice(
            "warn", "batch_full",
            f"{batch.label} already holds {n} units against {planned} planned.",
            "A batch does yield over its order, but check the selection before you "
            "add more.",
            run_id=batch.id, produced=n, planned=planned))

    if created and n:
        last = (db.query(func.max(M.DeviceEvent.at))
                .filter(M.DeviceEvent.kind == "produced",
                        M.DeviceEvent.production_run_id == batch.id).scalar())
        if last is not None and utcnow() - last > SETTLED_AFTER:
            out.append(_notice(
                "warn", "settled_batch",
                f"{batch.label} last took a unit on {last.date().isoformat()}.",
                "Adding one now re-divides its cost across one more device, so every "
                "per-device figure quoted from it changes.",
                run_id=batch.id, last_produced=last.date().isoformat()))
    return out


def for_identity(db: Session, dev: M.DeviceUnit, names: dict) -> list[dict]:
    """A modem or SIM identity this platform has already seen on another unit.

    Read after the identity step, not at the MAC: IMEI and ICCID arrive later in
    the run. Nothing in this platform has ever had a duplicate, so this is a
    guard rather than a repair — a swapped modem or a reused SIM would
    otherwise pass unremarked.
    """
    out: list[dict] = []
    for field, label in (("imei", "IMEI"), ("iccid", "ICCID")):
        value = str(names.get(field) or "").strip()
        if not value:
            continue
        col = getattr(M.DeviceUnit, field)
        other = (db.query(M.DeviceUnit)
                 .filter(col == value, M.DeviceUnit.id != dev.id).first())
        if other is not None:
            out.append(_notice(
                "warn", f"duplicate_{field}",
                f"{label} {value} is already recorded on {other.serial or other.mac}.",
                "Two boards cannot hold one modem. One of the two records is wrong.",
                device_id=dev.id, other_device_id=other.id, field=field, value=value))
    return out
