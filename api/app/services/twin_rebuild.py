"""Rebuild a batch made before twins into twins (decision 0060).

An old batch has its devices, its draws and its invoice positions, but no
twins, so each of its devices costs the batch's average (decision 0043) and has
no history of steps. This module gives the batch one twin per device it
produced, plus unnamed twins for spares a stock count found, records the
process steps its records prove, and points its draws and positions at those
steps. From then on the batch reads like a crafted one.

Four rules:

1. **Nothing is invented.** A step that adds parts is recorded only when the
   batch drew those parts. A step without parts (a laser mark, a label) is
   recorded only when the caller says it happened (`assume`): that is a
   person's statement, and the click's note says so. Programming comes from
   each device's own `produced` event. Every click says `chosen="rebuilt"`.
2. **No money moves between batches.** Draws and positions keep their batch
   and their value; the rebuild only links them to clicks. The one thing it
   adds is the draws of a step a person states happened when the batch never
   drew its parts (labels, decision 0061), priced from the pool at the batch's
   date. Before anything is kept, the twins' prices must add up to the
   batch's total in the register.
3. **A twin's status comes from its device's record:** disposed → scrapped,
   faulty or incomplete → active (not finished), anything else → finished. A
   rebuilt finish may lack a required step that has no record; the click's
   note names those steps.
4. **It can be undone** (`undo`) while no live step was added on top.
"""
from __future__ import annotations

from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from . import cost_steps, jlc_import, run_actuals
from . import process as P
from . import twins as T

CHOSEN = "rebuilt"
#: Device conditions whose twin stays active: built, but not sellable as it is.
NOT_FINISHED = ("faulty", "incomplete")
#: How far the twins' prices may stray from the register's batch total, in USD.
TOTAL_EPS = 0.05


def _key_of_input(inp: dict) -> tuple[str, object]:
    cid, mpn = P.input_ref(inp)
    return ("c", cid) if cid else ("m", run_actuals._strip(mpn))


def _key_of_draw(c: M.ComponentConsumption) -> tuple[str, object]:
    return ("c", c.component_id) if c.component_id else ("m", run_actuals._strip(c.mpn or ""))


def _input_owner(graph: dict) -> dict[tuple[str, object], str]:
    """Part key → the step that adds it, directly or as an input of a prepared
    part that step adds (the antenna glued into an enclosure before it meets
    the board is the enclosure step's part)."""
    owner: dict[tuple[str, object], str] = {}
    recipes = {int(r["output_component_id"]): r for r in graph.get("prepared") or []
               if r.get("output_component_id")}
    for s in graph.get("steps") or []:
        if (s.get("kind") or "step") in P.NO_INPUT_KINDS:
            continue
        for inp in s.get("inputs") or []:
            owner.setdefault(_key_of_input(inp), s["key"])
            cid, _m = P.input_ref(inp)
            for rin in (recipes.get(cid) or {}).get("inputs") or []:
                owner.setdefault(_key_of_input(rin), s["key"])
    return owner


def _status(d: M.DeviceUnit) -> str:
    if d.state == "disposed":
        return "scrapped"
    if (d.condition or "ok") in NOT_FINISHED:
        return "active"
    return "finished"


def _produced(db: Session, device_ids: list[int]) -> dict[int, M.DeviceEvent]:
    out: dict[int, M.DeviceEvent] = {}
    for ev in (db.query(M.DeviceEvent).filter(M.DeviceEvent.device_id.in_(device_ids or [-1]),
                                              M.DeviceEvent.kind == "produced").all()):
        out.setdefault(ev.device_id, ev)
    return out


def rebuild(db: Session, run: M.ProductionRun, *, version_id: int | None = None,
            assume: list[str] | None = None, draw: list[str] | None = None,
            since: dict[str, str] | None = None,
            costs: dict[str, list[str] | str] | None = None,
            spares: list[dict] | None = None, actor: str = "", dry_run: bool = True) -> dict:
    """Give `run` its twins from its records. Dry run by default: everything is
    written inside a savepoint and rolled back, so the plan is what the real
    write would do.

    `assume`: step keys that happened to every device though no record proves
    it — a person's statement. `draw`: the stated steps whose parts came from
    OUR stock, so the batch never drew them; their draws are written, priced
    from the pool at the batch's date (decision 0061). A stated step not in
    `draw` used someone else's parts — the final assembler's labels, billed in
    its invoice — and draws nothing. `since`: step key → ISO date, for a
    stated step that only the devices programmed on or after that date got
    (the instruction leaflet, since 2025-04-15). `costs`: plan key → the step keys a position paid for,
    other than the assembly (`{"final:device": ["program", "enclosure",
    "laser", "label"]}`); one position can pay for several steps, and their
    twins share it. Positions not named stay in the origin batch cost.
    `spares`: `[{"qty", "done", "note"}]` — unnamed units on the shelf and the
    steps they went through."""
    assume = list(assume or [])
    draw = list(draw or [])
    since = dict(since or {})
    costs = {k: ([v] if isinstance(v, str) else list(v)) for k, v in (costs or {}).items()}
    spares = list(spares or [])
    if run.closed_at is not None:
        raise HTTPException(409, f"batch {run.label} is closed — reopen it before rebuilding it")
    v = db.get(M.ProcessVersion, version_id) if version_id else P.current_version(db, run.project_id)
    if v is None or v.project_id != run.project_id or v.status != "published":
        raise HTTPException(422, "rebuild needs a published process version of this project")
    graph = P._graph(v)
    smap = P.step_map(graph)
    for kind in ("assembly", "receive", "program", "finish"):
        if P.step_of_kind(graph, kind) is None:
            raise HTTPException(422, f"the process has no {kind!r} step")
    bad = [k for k in assume + draw if k not in smap] + [k for ks in costs.values() for k in ks if k not in smap]
    bad += [f"{k} (draw needs it stated)" for k in draw if k not in assume]
    bad += [f"{k} (since needs it stated)" for k in since if k not in assume]
    bad += [k for sp in spares for k in sp.get("done") or [] if k not in smap]
    if bad:
        raise HTTPException(422, f"no step {bad[0]!r} in process version {v.version_no}")
    if run.process_version_id not in (None, v.id):
        raise HTTPException(409, f"batch {run.label} already runs another process version")
    if db.query(M.Twin).filter(M.Twin.origin_run_id == run.id, M.Twin.found.is_(False)).count():
        raise HTTPException(409, f"batch {run.label} already has twins — undo the rebuild first")
    if db.query(M.StepRun).filter_by(run_id=run.id).count():
        raise HTTPException(409, f"batch {run.label} already has process steps")

    sp = db.begin_nested()
    try:
        plan = _rebuild(db, run, v, graph, smap, assume, draw, since, costs, spares, actor)
    except Exception:
        sp.rollback()
        raise
    plan["dry_run"] = dry_run
    if dry_run:
        sp.rollback()
        db.expire_all()
    else:
        sp.commit()
    return plan


def _rebuild(db, run, v, graph, smap, assume, draw, since, costs, spares, actor) -> dict:
    reg_before = run_actuals.invoice_register(db)
    total = float((reg_before["by_run_usd"].get(str(run.id)) or {}).get("total_usd") or 0.0)
    produced_count = run_actuals.produced_counts(db, [run.id]).get(run.id, 0)
    devices = (db.query(M.DeviceUnit).filter_by(production_run_id=run.id)
               .order_by(M.DeviceUnit.id).all())
    has_twin = {d for (d,) in db.query(M.Twin.device_unit_id)
                .filter(M.Twin.device_unit_id.in_([d.id for d in devices] or [-1])).all()}
    skipped = [d.serial or d.mac or str(d.id) for d in devices if d.id in has_twin]
    devices = [d for d in devices if d.id not in has_twin]
    events = _produced(db, [d.id for d in devices])
    run.process_version_id = v.id

    named = [M.Twin(project_id=run.project_id, origin_run_id=run.id, run_id=run.id,
                    process_version_id=v.id, device_unit_id=d.id, status=_status(d),
                    named_at=(events[d.id].at if d.id in events else utcnow()),
                    note="rebuilt from the batch records")
             for d in devices]
    shelf: list[tuple[M.Twin, set[str]]] = []
    for spare in spares:
        for _ in range(int(spare.get("qty") or 0)):
            shelf.append((M.Twin(project_id=run.project_id, origin_run_id=run.id, run_id=run.id,
                                 process_version_id=v.id, status="active",
                                 note=(spare.get("note") or "spare found at a stock count")[:500]),
                          set(spare.get("done") or [])))
    db.add_all(named + [tw for tw, _d in shelf])
    db.flush()
    everyone = named + [tw for tw, _d in shelf]
    done: dict[int, set[str]] = defaultdict(set)

    # ---- where the money goes
    owner = _input_owner(graph)
    akey = P.step_of_kind(graph, "assembly")["key"]
    draws_for: dict[str, list[M.ComponentConsumption]] = defaultdict(list)
    loose_draws: list[M.ComponentConsumption] = []
    for c in (run_actuals.live_consumption(db, run_id=run.id)
              .filter(M.ComponentConsumption.step_run_id.is_(None)).all()):
        if c.basis == "measured":
            draws_for[akey].append(c)
        elif _key_of_draw(c) in owner:
            draws_for[owner[_key_of_draw(c)]].append(c)
        else:
            loose_draws.append(c)
    # Each position names the step keys it paid for; it is linked to every
    # click of those steps once they exist (decision 0061).
    line_steps: list[tuple[M.RunCostLine, list[str]]] = []
    loose_lines: list[M.RunCostLine] = []
    for li in T.charged_lines(db, run, unlinked_only=True):
        if cost_steps.stage_of(li.plan_key) in T.ASSEMBLY_STAGES:
            line_steps.append((li, [akey]))
        elif li.plan_key in costs:
            line_steps.append((li, costs[li.plan_key]))
        else:
            loose_lines.append(li)
    lines_for: dict[str, list[M.RunCostLine]] = defaultdict(list)
    for li, keys in line_steps:
        for k in keys:
            lines_for[k].append(li)
    clicks_of: dict[str, list[M.StepRun]] = defaultdict(list)
    added_draws: list[dict] = []

    def click(step: dict, twins: list[M.Twin], made_at: str, note: str) -> M.StepRun | None:
        if not twins:
            return None
        sr = T._new_run(db, run, v, step, len(twins), CHOSEN, made_at or run.run_date or T._today(),
                        actor, note)
        T._link(db, twins, sr)
        for tw in twins:
            done[tw.id].add(step["key"])
        for c in draws_for.get(step["key"], []):
            c.step_run_id = sr.id
        clicks_of[step["key"]].append(sr)
        return sr

    def draw_stated(step: dict, sr: M.StepRun | None) -> None:
        """A stated step adds parts the batch never drew: write its draws, at
        the pool's price on the batch's date, refused when the pool did not
        hold them then (decision 0061)."""
        if sr is None or not step.get("inputs") or draws_for.get(step["key"]):
            return
        planned, problems, _tok = T._plan_draws(db, run, step, sr.qty, sr.made_at, None)
        if problems:
            raise HTTPException(409, f"{run.label}: {step.get('label') or step['key']!r} cannot draw its "
                                     f"parts: {problems[0]['problem']} — nothing was kept")
        short = run_actuals.check_shortages(db, [
            {"component_id": d["component_id"], "mpn": d.get("mpn", ""), "lcsc": "", "qty": d["qty"],
             "date": sr.made_at, "label": d["name"]} for d in planned],
            company_id=run_actuals.run_scope(db, run))
        if short:
            raise HTTPException(409, {"error": f"{run.label}: the pool did not hold the parts of "
                                               f"{step.get('label') or step['key']!r} on {sr.made_at} — "
                                               "book the purchase first; nothing was kept",
                                      "shortages": short})
        T.write_draws(db, run, sr, planned, f"rebuilt: {sr.step_label} x {sr.qty}, stated by the user")
        for d in planned:
            added_draws.append({"step": step["key"], "part": d["name"], "qty": d["qty"],
                                "usd": d["value_usd"]})

    recorded: list[dict] = []
    not_recorded: list[dict] = []
    doc_dates = sorted(d for d in (db.get(M.RunCostDocument, li.document_id).doc_date
                                   for li in lines_for.get(akey, [])) if d)
    orders = T.assembly_orders(db, run)

    def produced_on(tw: M.Twin) -> str:
        ev = events.get(tw.device_unit_id)
        return ev.at.date().isoformat() if ev is not None and ev.at else ""

    def took(key: str) -> list[M.Twin]:
        if key in since:
            # Only the devices programmed on or after the stated date got it.
            return [tw for tw in named if produced_on(tw) and produced_on(tw) >= since[key]]
        return named + [tw for tw, ds in shelf if key in ds]

    for s in graph["steps"]:
        if s.get("kind") == "assembly":
            # An old batch's invoice can be dated after its boards arrived (a
            # re-invoice): the assembly happened by the earlier of the two.
            when = min(d for d in (doc_dates[0] if doc_dates else "", run.run_date or "") if d) \
                if (doc_dates or run.run_date) else ""
            evidence = ("invoices" if lines_for.get(akey) else
                        "the supplier's measured draws" if draws_for.get(akey) else "the batch")
            click(s, everyone, when, f"rebuilt: assembly order {', '.join(orders)}" if orders
                  else "rebuilt: the batch's board and assembly invoices")
            recorded.append({"step": s["key"], "units": len(everyone), "evidence": evidence})
    rstep = P.step_of_kind(graph, "receive")
    click(rstep, everyone, run.run_date, "rebuilt: the batch's records")
    recorded.append({"step": rstep["key"], "units": len(everyone), "evidence": "the batch"})

    route = [k for k in graph["route"] if k in smap] + [k for k in smap if k not in graph["route"]]
    for key in route:
        s = smap[key]
        kind = s.get("kind") or "step"
        if kind in ("assembly", "receive", "finish"):
            continue
        if kind == "program":
            by_day: dict[str, list[M.Twin]] = defaultdict(list)
            for tw in named:
                ev = events.get(tw.device_unit_id)
                if ev is not None:
                    by_day[ev.at.date().isoformat() if ev.at else run.run_date].append(tw)
            for day in sorted(by_day):
                click(s, by_day[day], day, "rebuilt: the devices' produced events")
            recorded.append({"step": key, "units": sum(len(x) for x in by_day.values()),
                             "evidence": "produced events", "days": len(by_day)})
            continue
        evidence = None
        if draws_for.get(key):
            evidence = "draws"
        elif lines_for.get(key):
            evidence = "invoices"
        elif key in assume:
            evidence = "stated by the user"
        if key in since:
            evidence = f"stated by the user, devices programmed since {since[key]}"
        units = took(key) if evidence else [tw for tw, ds in shelf if key in ds]
        if not evidence and not units:
            not_recorded.append({"step": key, "label": s.get("label") or key,
                                 "why": "no draw, no invoice, and not stated"})
            continue
        if not units:
            not_recorded.append({"step": key, "label": s.get("label") or key,
                                 "why": f"no device of the batch was programmed since {since.get(key)}"})
            continue
        # The batch's date, not the draws': a draw is often entered, or
        # repriced, long after the work it records. A step stated since a date
        # is dated by the first device that got it.
        when = (min(produced_on(tw) for tw in units) if key in since else run.run_date)
        sr = click(s, units, when, f"rebuilt: {evidence or 'the stock count'}")
        if key in draw:
            # Stated to have happened with OUR parts: what it adds left our
            # stock, whatever else records the step (an invoice that paid for it).
            draw_stated(s, sr)
        recorded.append({"step": key, "units": len(units), "evidence": evidence or "stock count"})

    # finish and scrap, from the device records
    fstep = P.step_of_kind(graph, "finish")
    finished = [tw for tw in named if tw.status == "finished"]
    lacking = sorted({t for t in P.required_terms(graph)
                      for tw in finished
                      if t not in done[tw.id] and not any(m in done[tw.id]
                                                          for m in P.groups_of(graph).get(t, []))})
    last_day = max((ev.at.date().isoformat() for ev in events.values() if ev.at), default=run.run_date)
    # Finished on the day it was programmed, as far as the records tell: one
    # click per day, like programming, so each twin keeps its own date.
    fin_day: dict[str, list[M.Twin]] = defaultdict(list)
    for tw in finished:
        ev = events.get(tw.device_unit_id)
        fin_day[ev.at.date().isoformat() if ev is not None and ev.at else last_day].append(tw)
    for day in sorted(fin_day):
        click(fstep, fin_day[day], day,
              "rebuilt: finished per the device record"
              + (f"; no record of {', '.join(lacking)}" if lacking else ""))
    for tw in finished:
        ev = events.get(tw.device_unit_id)
        tw.finished_at = ev.at if ev is not None and ev.at else None
    scrapped = [tw for tw in named if tw.status == "scrapped"]
    if scrapped:
        click({"key": "scrap", "label": "Scrapped", "kind": "scrap"}, scrapped, last_day,
              "rebuilt: disposed per the device record")
        for tw in scrapped:
            tw.scrapped_at = utcnow()  # the device record keeps no disposal date of its own here
    for tw in everyone:
        tw.stack_key = "|".join(sorted(done[tw.id] - {"scrap"}))
    unpaid: list[dict] = []
    for li, keys in line_steps:
        clicks = [c for k in keys for c in clicks_of.get(k, [])]
        if clicks:
            T.link_line(db, li, clicks)
        else:
            loose_lines.append(li)
            unpaid.append({"line_id": li.id, "label": li.label, "steps": keys})
    db.flush()

    # ---- the check: the twins carry exactly the batch's money
    alive = [tw for tw in everyone if tw.status != "scrapped"]
    reg = run_actuals.invoice_register(db)
    pr = T.prices(db, alive, reg)
    carried = round(sum(p["total_usd"] for p in pr.values()), 4)
    # The batch's total moved by the stated draws and by nothing else.
    added = sum(d["usd"] for d in added_draws)
    total_after = float((reg["by_run_usd"].get(str(run.id)) or {}).get("total_usd") or 0.0)
    if abs(total_after - total - added) > TOTAL_EPS:
        raise HTTPException(409, f"rebuilding {run.label} moved {round(total_after - total, 4)} USD, "
                                 f"and only the {round(added, 4)} USD of stated draws may move — "
                                 "nothing was kept")
    total = total_after
    # Each price is rounded to 4 decimals, so the sum may stray by half a unit
    # of the last place per twin on top of the fixed tolerance.
    if alive and abs(carried - total) > TOTAL_EPS + 0.00005 * len(alive):
        raise HTTPException(409, f"the rebuilt twins of {run.label} carry {carried} USD, the batch "
                                 f"cost {round(total, 4)} USD — nothing was kept")
    panels = jlc_import.effective_panels(db)
    boards = sum((panels.get(code) or {}).get("devices") or 0 for code in orders)
    unit_prices = sorted({p["total_usd"] for tw, p in ((tw, pr[tw.id]) for tw in alive)
                          if tw.device_unit_id})
    return {
        "run_id": run.id, "batch": run.label, "process_version": v.version_no,
        "twins": len(everyone), "named": len(named), "spares": len(shelf),
        "finished": len(finished), "scrapped": len(scrapped),
        "active": sum(1 for tw in named if tw.status == "active"),
        "devices_with_a_twin_already": skipped,
        "boards_from_orders": boards or None,
        "more_units_than_boards": (len(everyone) - boards) if boards and len(everyone) > boards else 0,
        "recorded": recorded, "not_recorded": not_recorded,
        "finish_lacks": lacking,
        "no_assembly_invoice": not lines_for.get(akey),
        "draws_linked": {k: len(v_) for k, v_ in draws_for.items()},
        "lines_linked": {k: len(v_) for k, v_ in lines_for.items()},
        "draws_added": added_draws,
        "lines_whose_steps_were_not_recorded": unpaid,
        "left_in_origin": {
            "lines": [{"line_id": li.id, "label": li.label, "plan_key": li.plan_key} for li in loose_lines],
            "draws": [{"consumption_id": c.id, "mpn": c.mpn, "component_id": c.component_id,
                       "basis": c.basis} for c in loose_draws]},
        "total_usd": round(total, 4), "carried_usd": carried,
        "device_cost_before_usd": round(total / produced_count, 4) if produced_count else None,
        "device_cost_after_usd": unit_prices[0] if len(unit_prices) == 1 else unit_prices[:1] + unit_prices[-1:],
        "origin": T.origin_shares(db, [run.id], reg).get(run.id),
    }


def undo(db: Session, run: M.ProductionRun, *, actor: str = "", dry_run: bool = True) -> dict:
    """Take a rebuild back: its twins, its clicks and its links. Refused while a
    live step (not rebuilt) touches one of its twins."""
    T._refuse_closed(run)   # its shares are frozen, and its draws are in closed books
    clicks = db.query(M.StepRun).filter_by(run_id=run.id, chosen=CHOSEN).all()
    ids = [c.id for c in clicks]
    twins = (db.query(M.Twin).join(M.TwinStep, M.TwinStep.twin_id == M.Twin.id)
             .filter(M.TwinStep.step_run_id.in_(ids or [-1]), M.Twin.found.is_(False)).distinct().all())
    tids = [tw.id for tw in twins]
    live = (db.query(M.StepRun.step_label).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
            .filter(M.TwinStep.twin_id.in_(tids or [-1]), M.StepRun.chosen != CHOSEN).distinct().all())
    if live:
        raise HTTPException(409, f"live steps were recorded on rebuilt twins since "
                                 f"({', '.join(x for (x,) in live)}) — undo is refused")
    plan = {"dry_run": dry_run, "run_id": run.id, "clicks": len(ids), "twins": len(tids)}
    if dry_run:
        return plan
    for c in db.query(M.ComponentConsumption).filter(M.ComponentConsumption.step_run_id.in_(ids or [-1])):
        if c.basis == T.BASIS_STEP and (c.note or "").startswith("rebuilt:"):
            db.delete(c)       # a draw the rebuild wrote for a stated step goes with it
        else:
            c.step_run_id = None
    db.query(M.CostLineStep).filter(M.CostLineStep.step_run_id.in_(ids or [-1])).delete(
        synchronize_session=False)
    db.query(M.TwinStep).filter(M.TwinStep.step_run_id.in_(ids or [-1])).delete(synchronize_session=False)
    for tw in twins:
        db.delete(tw)
    for c in clicks:
        db.delete(c)
    db.flush()
    if not db.query(M.StepRun).filter_by(run_id=run.id).count():
        run.process_version_id = None
    db.flush()
    return plan
