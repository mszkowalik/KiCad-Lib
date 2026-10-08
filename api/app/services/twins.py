"""Twins: one record per unit from its first step (decision 0059).

A batch with a process is CRAFTED. "Receive" creates one twin per board; every
later step is a CLICK (`StepRun`) on N twins, which draws N x each input part
and links each twin to the click (`TwinStep`). Programming names a twin with
the device's MAC. "Finish" is the last step, done by a person.

Three rules hold everything up:

1. **An unnamed twin is never addressed by its id.** Before programming, units
   are taken as "N from this stack" and the platform picks which twins. A
   STACK is the unnamed active twins of one batch with the same `stack_key`
   (the steps done, and the prepared-part lots used). Twins of a stack are
   identical by construction, so naming any one of them is not a guess.
2. **Each fact says how the unit was chosen** (`StepRun.chosen`): from a stack,
   scanned, picked from a list, at a bench, by a merge, or entered as found.
3. **A twin's price is its own costs plus a share of its origin batch.** Its
   own costs are the draws of its clicks and the invoice positions that paid
   for them (decision 0060), 1/N each. The origin batch cost is everything
   charged to the batch it was received in that no click claims, split over
   that batch's twins that are not scrapped; scrapped twins' own costs are
   spread the same way. A closed batch's share is frozen.

**The board's assembly is a step too** (decision 0060). The process has one
`assembly` step, done at the supplier. The person records it from the
pre-filled "Record assembly" form (decision 0072): the ticked measured draws
and board and assembly positions (`fab:*`, `pcba:*`) point at it. Any other position can be linked to the click it paid for
(`link_costs`) — the final assembler's invoice, a print service.

The money paths need nothing new: a click's draws and positions stay charged
to the batch where the step was done, so run figures and the register see them
as before. A link only says which twins carry the money.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from . import cost_steps, run_actuals
from . import process as P

BASIS_STEP = "step"
EPS = 1e-6


def _today() -> str:
    return date.today().isoformat()


# ================================================================== plumbing

def crafted_version(db: Session, run: M.ProductionRun) -> M.ProcessVersion:
    """The process version a crafted batch runs. A batch without one is not
    crafted, and nothing in this module applies to it."""
    v = db.get(M.ProcessVersion, run.process_version_id) if run.process_version_id else None
    if v is None:
        raise HTTPException(409, f"batch {run.label} has no process, so it is not crafted")
    return v


def _tokens(key: str) -> list[str]:
    return [x for x in (key or "").split("|") if x]


FOUND = "found"


def done_of_key(key: str) -> set[str]:
    """Step keys done, read off a stack key ("antenna|enclosure@A785|receive").
    A `found@<batch>` token is no step: it marks units entered at a count."""
    return {tok.split("@", 1)[0] for tok in _tokens(key) if not tok.startswith(f"{FOUND}@")}


def _add_token(key: str, token: str) -> str:
    return "|".join(sorted(set(_tokens(key)) | {token}))


def stack_id(run_id: int, key: str) -> str:
    return f"{run_id}:{key}"


def parse_stack(stack: str) -> tuple[int, str]:
    run_part, _, key = (stack or "").partition(":")
    if not run_part.isdigit():
        raise HTTPException(422, f"not a stack: {stack!r}")
    return int(run_part), key


def done_steps(db: Session, twin_ids: list[int]) -> dict[int, set[str]]:
    """Step keys each twin has taken part in — its history, from the links."""
    out: dict[int, set[str]] = defaultdict(set)
    if not twin_ids:
        return out
    for tid, key in (db.query(M.TwinStep.twin_id, M.StepRun.step_key)
                     .join(M.StepRun, M.StepRun.id == M.TwinStep.step_run_id)
                     .filter(M.TwinStep.twin_id.in_(twin_ids)).all()):
        out[tid].add(key)
    return out


def needs_met(graph: dict, step: dict, done: set[str], since: set[str] | None = None) -> list[str]:
    """Why `step` cannot run on a unit that has done `done`; [] when it can.
    `since`: for a unit reopened for rework, what it did after the latest
    reopen (decision 0074) — a step done before may be done again, and the
    needs still read the whole history."""
    smap = P.step_map(graph)
    groups = P.groups_of(graph)
    label = {k: (s.get("label") or k) for k, s in smap.items()}
    why: list[str] = []
    key = step.get("key")
    fresh = done if since is None else since
    if key in fresh:
        why.append(f"{label.get(key, key)!r} is already done")
    g = step.get("group")
    if g:
        other = [m for m in groups.get(g, []) if m != key and m in fresh]
        if other:
            why.append(f"{label.get(other[0], other[0])!r} is already done — another option of {g!r}")
    needs = P.required_terms(graph) if step.get("kind") == "finish" else (step.get("needs") or [])
    for ref in needs:
        members = groups.get(ref)
        if members is not None:
            if not any(m in done for m in members):
                why.append(f"needs one of {g_label(members, label)}")
        elif ref not in done:
            why.append(f"needs {label.get(ref, ref)!r}")
    for ref in step.get("needs_not") or []:
        members = groups.get(ref, [ref])
        if any(m in fresh for m in members):
            why.append(f"must come before {label.get(ref, ref)!r}")
    return why


def since_reopen(db: Session, twin_ids: list[int]) -> dict[int, set[str]]:
    """For each twin reopened for rework: the step keys it did after its
    latest reopen. A twin never reopened is absent (decision 0074)."""
    rows = (db.query(M.TwinStep.twin_id, M.TwinStep.id, M.StepRun.step_key, M.StepRun.kind)
            .join(M.StepRun, M.StepRun.id == M.TwinStep.step_run_id)
            .filter(M.TwinStep.twin_id.in_(twin_ids or [-1])).order_by(M.TwinStep.id).all())
    last = {tid: lid for tid, lid, _k, kind in rows if kind == "reopen"}
    out: dict[int, set[str]] = {tid: set() for tid in last}
    for tid, lid, key, _kind in rows:
        if tid in last and lid > last[tid]:
            out[tid].add(key)
    return out


def g_label(keys: list[str], label: dict) -> str:
    return " / ".join(repr(label.get(k, k)) for k in keys)


def _step(graph: dict, key: str) -> dict:
    s = P.step_map(graph).get(key)
    if s is None:
        raise HTTPException(404, f"no step {key!r} in this process version")
    return s


def _new_run(db, run, v, step, qty, chosen, made_at, actor, note) -> M.StepRun:
    sr = M.StepRun(project_id=run.project_id, run_id=run.id, process_version_id=v.id,
                   step_key=step["key"], step_label=(step.get("label") or step["key"])[:200],
                   kind=step.get("kind") or "step", qty=qty, chosen=chosen,
                   made_at=made_at or _today(), actor=actor, note=(note or "")[:500])
    db.add(sr)
    db.flush()
    _link_step_keys(db, run, sr)
    return sr


def _link_step_keys(db: Session, run: M.ProductionRun, sr: M.StepRun) -> None:
    """A position linked to this whole step pays for this click too (decision
    0074) — while it is still charged to this batch: a link counts only inside
    its batch."""
    if not sr.qty or sr.kind == "scrap" or sr.chosen == "found":
        return
    keyed = {lid for (lid,) in db.query(M.CostLineStepKey.line_id)
             .filter(M.CostLineStepKey.run_id == run.id, M.CostLineStepKey.step_key == sr.step_key).all()}
    if not keyed:
        return
    mine = {li.id for li in charged_lines(db, run)}
    # A split position's header is linked too: it is valued at zero, so its
    # links move no money, and it stays the whole source for a later split or
    # for the line it becomes again when its children are voided.
    for lid in (run_actuals.header_ids(db) & keyed) - mine:
        li = db.get(M.RunCostLine, lid)
        doc = db.get(M.RunCostDocument, li.document_id) if li is not None else None
        if li is not None and li.voided_at is None and doc is not None \
                and run_actuals.line_destination(li, doc) == ("run", run.id):
            mine.add(lid)
    have = {lid for (lid,) in db.query(M.CostLineStep.line_id).filter_by(step_run_id=sr.id).all()}
    for lid in sorted((keyed & mine) - have):
        db.add(M.CostLineStep(line_id=lid, step_run_id=sr.id))
    db.flush()


def _link(db, twins: list[M.Twin], sr: M.StepRun, *, programming_run_id: int | None = None,
          deployment_version_id: int | None = None) -> None:
    for tw in twins:
        db.add(M.TwinStep(twin_id=tw.id, step_run_id=sr.id, programming_run_id=programming_run_id,
                          deployment_version_id=deployment_version_id))
    db.flush()


# ==================================================================== stacks

def stacks(db: Session, project_id: int, *, run_id: int | None = None) -> list[dict]:
    """Unnamed active twins grouped into stacks, with what they have done."""
    q = (db.query(M.Twin.run_id, M.Twin.stack_key, func.count(M.Twin.id))
         .filter(M.Twin.project_id == project_id, M.Twin.device_unit_id.is_(None),
                 M.Twin.status == "active"))
    if run_id is not None:
        q = q.filter(M.Twin.run_id == run_id)
    rows = q.group_by(M.Twin.run_id, M.Twin.stack_key).all()
    origins = {int(tok.split("@", 1)[1]) for _r, k, _n in rows for tok in _tokens(k)
               if tok.startswith(f"{FOUND}@") and tok.split("@", 1)[1].isdigit()}
    labels = {r.id: r.label for r in db.query(M.ProductionRun)
              .filter(M.ProductionRun.id.in_({r for r, _k, _n in rows} | origins or {-1})).all()}
    out = []
    for rid, key, n in sorted(rows, key=lambda x: (x[0], x[1])):
        found = next((tok.split("@", 1)[1] for tok in _tokens(key) if tok.startswith(f"{FOUND}@")), None)
        out.append({"stack": stack_id(rid, key), "run_id": rid, "run_label": labels.get(rid),
                    "key": key, "done": sorted(done_of_key(key)),
                    "lots": sorted(tok.split("@", 1)[1] for tok in _tokens(key)
                                   if "@" in tok and not tok.startswith(f"{FOUND}@")),
                    "found_from": labels.get(int(found)) if found and found.isdigit() and int(found) in labels
                    else (found and f"batch {found}"),
                    "count": n})
    return out


def _take_stack(db: Session, project_id: int, stack: str, qty: int) -> list[M.Twin]:
    rid, key = parse_stack(stack)
    if qty <= 0:
        raise HTTPException(422, "take at least one unit")
    # Locked, so two clicks at the same moment cannot take the same units.
    twins = (db.query(M.Twin)
             .filter(M.Twin.project_id == project_id, M.Twin.run_id == rid,
                     M.Twin.stack_key == key, M.Twin.device_unit_id.is_(None),
                     M.Twin.status == "active")
             .order_by(M.Twin.id).limit(qty).with_for_update(skip_locked=True).all())
    if len(twins) < qty:
        raise HTTPException(409, f"that stack holds {len(twins)} units, not {qty}")
    return twins


def _resolve_devices(db: Session, run: M.ProductionRun, device_ids: list[int] | None,
                     codes: list[str] | None) -> list[M.DeviceUnit]:
    from .orders import find_device

    devices: list[M.DeviceUnit] = []
    missing: list[str] = []
    for did in device_ids or []:
        d = db.get(M.DeviceUnit, int(did))
        if d is None:
            missing.append(str(did))
        else:
            devices.append(d)
    for code in codes or []:
        d = find_device(db, code)
        if d is None:
            d = (db.query(M.DeviceUnit)
                 .filter(func.lower(M.DeviceUnit.mac) == (code or "").strip().lower()).first())
        if d is None:
            missing.append(code)
        else:
            devices.append(d)
    if missing:
        raise HTTPException(404, f"no device for {', '.join(missing)}")
    seen: set[int] = set()
    out = []
    for d in devices:
        if d.id in seen:
            continue
        seen.add(d.id)
        if d.project_id != run.project_id:
            raise HTTPException(422, f"{d.serial or d.mac} belongs to another project")
        out.append(d)
    if not out:
        raise HTTPException(422, "select at least one device")
    return out


def _twin_of_device(db: Session, run: M.ProductionRun, d: M.DeviceUnit) -> tuple[M.Twin | None, str]:
    """The device's twin, if the batch screen may craft it; else why not."""
    tw = db.query(M.Twin).filter_by(device_unit_id=d.id).first()
    if tw is None:
        return None, "has no twin — merge it first"
    if tw.run_id != run.id:
        other = db.get(M.ProductionRun, tw.run_id)
        return None, f"is in {other.label if other else tw.run_id}, not in {run.label}"
    if tw.status != "active":
        return None, f"is {tw.status}"
    return tw, ""


def _twins_of_devices(db: Session, run: M.ProductionRun, devices: list[M.DeviceUnit]) -> list[M.Twin]:
    twins = []
    for d in devices:
        tw, why = _twin_of_device(db, run, d)
        if why:
            raise HTTPException(409, f"{d.serial or d.mac} {why}")
        twins.append(tw)
    return twins


# ================================================================== crafting

def receive(db: Session, run: M.ProductionRun, *, qty: int, made_at: str = "", note: str = "",
            actor: str = "", dry_run: bool = True) -> dict:
    """The first step: one twin per board the batch's assembly order delivered."""
    v = crafted_version(db, run)
    graph = P._graph(v)
    step = P.step_of_kind(graph, "receive")
    if step is None:
        raise HTTPException(409, "this process has no receive step")
    if qty <= 0:
        raise HTTPException(422, "receive at least one board")
    _refuse_closed(run)
    have = (db.query(func.count(M.Twin.id)).filter(M.Twin.origin_run_id == run.id,
                                                   M.Twin.found.is_(False)).scalar() or 0)
    plan = {"dry_run": dry_run, "step": step["key"], "qty": qty, "received_before": have,
            "ordered": run.qty, "over_order": have + qty > (run.qty or 0),
            "assembly_orders": assembly_orders(db, run)}
    if dry_run:
        return plan
    key = step["key"]
    twins = [M.Twin(project_id=run.project_id, origin_run_id=run.id, run_id=run.id,
                    process_version_id=v.id, stack_key=key) for _ in range(qty)]
    db.add_all(twins)
    db.flush()
    sr = _new_run(db, run, v, step, qty, "stack", made_at, actor, note)
    _link(db, twins, sr)
    plan["step_run_id"] = sr.id
    # The assembly step is the person's to record, from the pre-filled form
    # on the batch screen (decision 0072): receiving only counts the boards.
    plan["stack"] = stack_id(run.id, twins[0].stack_key)
    return plan


def _plan_draws(db: Session, run: M.ProductionRun, step: dict, n: int, made_at: str,
                lots: dict | None) -> tuple[list[dict], list[dict], list[str]]:
    """The draws one click makes: N x each input. A prepared part takes ONE lot,
    so the twins that get it stay one physical pile (0059 §2). Everything comes
    from the batch company's stock (decision 0064)."""
    scope = run_actuals.run_scope(db, run)
    pool = run_actuals.pool_state(db, run.project_id, as_of=made_at, company_id=scope)
    names = P._part_names(db, {c for c, _m in map(P.input_ref, step.get("inputs") or []) if c})
    draws: list[dict] = []
    problems: list[dict] = []
    tokens: list[str] = []
    for inp in step.get("inputs") or []:
        cid, mpn = P.input_ref(inp)
        need = float(inp.get("qty") or 0) * n
        comp = db.get(M.Component, cid) if cid else None
        name = P.input_label(inp, names)
        if comp is not None and comp.internal:
            # A lot made after the click's date cannot have fed it.
            open_lots = [lt for lt in P.prepared_lots(db, {cid}, open_only=True, company_id=scope)
                         if not made_at or not lt.get("date") or str(lt["date"])[:10] <= made_at]
            want = (lots or {}).get(str(cid)) or (lots or {}).get(cid)
            lot = None
            if want:
                lot = next((lt for lt in open_lots if lt["adjustment_id"] == int(want)), None)
                if lot is None:
                    problems.append({"component_id": cid, "name": name,
                                     "problem": f"lot A{want} is not an open lot of this part"})
                    continue
            else:
                lot = next((lt for lt in open_lots if lt["remaining"] + EPS >= need), None)
            if lot is None or lot["remaining"] + EPS < need:
                problems.append({"component_id": cid, "name": name, "needed": need,
                                 "problem": "no single lot holds enough — split the step, one lot "
                                            "per click"})
                continue
            draws.append({"component_id": cid, "name": name, "qty": need,
                          "unit_cost_usd": lot["unit_cost_usd"],
                          "value_usd": round(need * lot["unit_cost_usd"], 4),
                          "lot_adjustment_id": lot["adjustment_id"], "internal": True})
            tokens.append(f"A{lot['adjustment_id']}")
        else:
            # The draw lands on the pool entry its purchases sit under, found by
            # identity OVERLAP as `check_shortages` finds it: a part named by MPN
            # whose purchases now carry a component id would otherwise be priced
            # at zero under a new key (`run_actuals.resolve_pool_identity`).
            hit = run_actuals.resolve_pool_identity(db, cid, "" if cid else mpn, "", as_of=made_at,
                                                    company_id=scope)
            if hit is not None:
                cid = hit.get("component_id") or cid
                mpn = "" if cid else (hit.get("mpn") or mpn)
                avg = hit.get("avg_usd") or 0.0
            else:
                probe = type("P", (), {"component_id": cid, "mpn": "" if cid else mpn, "lcsc": ""})()
                avg = pool.get(run_actuals._key(probe), {}).get("avg_usd", 0.0) or 0.0
            draws.append({"component_id": cid, "mpn": "" if cid else mpn, "name": name, "qty": need,
                          "unit_cost_usd": round(avg, 8), "value_usd": round(need * avg, 4),
                          "lot_adjustment_id": None, "internal": False})
    # Decision 0073: a bought part is taken from its lots, oldest first, at
    # their cost; what no lot holds is refused with the other problems.
    from . import lots as _lots

    problems += _lots.fifo_price(db, [d for d in draws if not d["internal"]], as_of=made_at, company_id=scope)
    return draws, problems, tokens


def write_draws(db: Session, run: M.ProductionRun, sr: M.StepRun, draws: list[dict], note: str) -> None:
    """The one writer of a click's draws: each charged to the batch of the
    click, and a prepared part bound to the lot it was taken from, so the lot
    closes (decision 0058 §3). Every path that draws for a step goes through
    here — the batch screen, the benches, a rebuild."""
    for d in draws:
        c = M.ComponentConsumption(
            run_id=run.id, component_id=d["component_id"], mpn=d.get("mpn", ""), lcsc="", qty=d["qty"],
            unit_cost_usd=d["unit_cost_usd"], basis=BASIS_STEP, consumed_at=sr.made_at,
            step_run_id=sr.id, note=note[:500])
        db.add(c)
        db.flush()
        if d.get("bindings"):
            from . import lots as _lots

            _lots.bind(db, c, d)
        if d.get("lot_adjustment_id"):
            db.add(M.ComponentConsumptionLot(consumption_id=c.id, lot_adjustment_id=d["lot_adjustment_id"],
                                             qty=d["qty"], unit_cost_usd=d["unit_cost_usd"],
                                             source="manual", note=f"step click #{sr.id}"))
    db.flush()


#: Bench steps a person may STATE on named devices when no platform bench run
#: records them (decision 0074): marked or tested elsewhere, a label replaced
#: by hand. Programming is never stated — the bench names the twin.
STATABLE_KINDS = ("test", "mark_laser", "label")


def _skipped_note(note: str, names: list[str], selected: int) -> str:
    """The click's note when refused units were skipped: how many, and as many
    of their names as fit in `StepRun.note` (500). The audit row lists all."""
    head = f"skipped {len(names)} of {selected} (refused): "
    tail = f" — {note}" if note else ""
    for k in range(len(names), -1, -1):
        more = f" +{len(names) - k} more" if k < len(names) else ""
        text = head + ", ".join(names[:k]) + more + tail
        if len(text) <= 500:
            return text
    return text[:500]


def apply_step(db: Session, run: M.ProductionRun, *, step_key: str, stack: str = "",
               qty: int = 0, device_ids: list[int] | None = None, codes: list[str] | None = None,
               chosen: str = "", made_at: str = "", lots: dict | None = None, note: str = "",
               actor: str = "", dry_run: bool = True, stated: str = "",
               skip_refused: bool = False) -> dict:
    """Run one step on N units: from a stack (unnamed) or on devices (named).

    Dry run by default: the plan says which units qualify, every draw with its
    price, and any shortage. Programming and marking are refused here — their
    benches read the device and record them (0059 §5) — unless a person STATES
    a test, mark or label step on named devices, with the reason (`stated`).

    On named devices each unit is judged on its own, and the plan counts and
    draws only the units that can take the step (`units` of `selected`). A
    refused unit (step already done, a need not met, finished, in another
    batch, no twin) refuses the whole click unless `skip_refused`: then the
    others take it, and the click's note names the skipped ones. A step is
    never recorded twice."""
    v = crafted_version(db, run)
    graph = P._graph(v)
    step = _step(graph, step_key)
    kind = step.get("kind") or "step"
    stated = (stated or "").strip()
    if stated and kind not in STATABLE_KINDS:
        raise HTTPException(422, f"only a test, laser mark or label step is stated; "
                                 f"{step.get('label') or step_key!r} is a {kind!r} step")
    if stated and stack:
        raise HTTPException(422, "a stated bench step names its devices — scan or pick them")
    if kind != "step" and not stated:
        where = P.KINDS.get(kind, "batch").replace("_", " ")
        raise HTTPException(422, f"{step.get('label') or step_key!r} is a {kind!r} step — "
                                 + ("use receive" if kind == "receive" else
                                    "use finish" if kind == "finish" else
                                    "it is recorded with \"Record assembly\" on the batch's Process tab "
                                    "(decision 0072)" if kind == "assembly" else
                                    f"it is done at the {where}" + (", or stated on named devices with the reason"
                                                                     if kind in STATABLE_KINDS else "")))
    made_at = made_at or _today()
    if stack:
        twins = _take_stack(db, run.project_id, stack, qty)
        if twins[0].run_id != run.id:
            raise HTTPException(409, "that stack belongs to another batch; craft it there")
        chosen = "stack"
        refusals = needs_met(graph, step, done_of_key(twins[0].stack_key))
        refused = [{"unit": "stack", "why": refusals} for _tw in twins] if refusals else []
        selected = len(twins)
    else:
        if chosen not in ("scanned", "list"):
            raise HTTPException(422, "say how the devices were chosen: scanned or list")
        devices = _resolve_devices(db, run, device_ids, codes)
        selected = len(devices)
        # A stack is one pile, refused whole; named devices are judged one by
        # one, so a finished unit or one that already has the step is named.
        refused, ready = [], []
        for d in devices:
            tw, why = _twin_of_device(db, run, d)
            if why:
                refused.append({"unit": d.serial or d.mac, "why": [f"it {why}"]})
            else:
                ready.append((d, tw))
        done = done_steps(db, [tw.id for _d, tw in ready])
        again = since_reopen(db, [tw.id for _d, tw in ready])
        twins = []
        for d, tw in ready:
            if why := needs_met(graph, step, done[tw.id], again.get(tw.id)):
                refused.append({"unit": d.serial or d.mac, "why": why})
            else:
                twins.append(tw)
    n = len(twins)
    draws, problems, tokens = _plan_draws(db, run, step, n, made_at, lots)
    shortages = run_actuals.check_shortages(db, [
        {"component_id": d["component_id"], "mpn": d.get("mpn", ""), "lcsc": "", "qty": d["qty"],
         "date": made_at, "label": d["name"]} for d in draws if not d["internal"]],
        company_id=run_actuals.run_scope(db, run))
    plan = {
        "dry_run": dry_run, "step": step_key, "label": step.get("label") or step_key,
        "units": n, "selected": selected, "chosen": chosen, "made_at": made_at,
        "refused": refused,
        "draws": draws, "value_usd": round(sum(d["value_usd"] for d in draws), 4),
        "per_unit_usd": round(sum(d["value_usd"] for d in draws) / n, 6) if n else 0.0,
        "shortages": shortages, "problems": problems,
    }
    if dry_run:
        return plan
    skipping = bool(refused) and skip_refused and not stack
    if (refused and not skipping) or shortages or problems:
        raise HTTPException(409, {"error": "the step cannot run on these units — see the plan",
                                  "plan": plan})
    if not twins:
        raise HTTPException(409, {"error": "none of these units can take the step — see the plan",
                                  "plan": plan})
    if stated:
        # A person's statement, not a bench record: the click says so.
        chosen, note = "stated", f"stated: {stated}" + (f" — {note}" if note else "")
    if skipping:
        note = _skipped_note(note, [r["unit"] for r in refused], selected)
    sr = _new_run(db, run, v, step, n, chosen, made_at, actor, note)
    write_draws(db, run, sr, draws, f"{sr.step_label} x {n} (step click #{sr.id})")
    _link(db, twins, sr)
    token = step_key + (f"@{','.join(tokens)}" if tokens else "")
    for tw in twins:
        tw.stack_key = _add_token(tw.stack_key, token)
    db.flush()
    plan["step_run_id"] = sr.id
    if stack:
        plan["stack"] = stack_id(run.id, twins[0].stack_key)
    else:
        # A bench step a device did before this step met its needs (a laser
        # mark before the enclosure) is recorded now, from the bench's own run.
        plan["caught_up"] = catch_up(db, twins)
    return plan


def scrap(db: Session, run: M.ProductionRun, *, stack: str = "", qty: int = 0,
          device_ids: list[int] | None = None, codes: list[str] | None = None, chosen: str = "",
          reason: str = "", actor: str = "", dry_run: bool = True) -> dict:
    """Units that broke. Their price is carried by the other twins of their
    origin batch (0059 §11), until that batch is closed."""
    v = crafted_version(db, run)
    if not (reason or "").strip():
        raise HTTPException(422, "say why these units are scrapped")
    if stack:
        twins = _take_stack(db, run.project_id, stack, qty)
        if twins[0].run_id != run.id:
            raise HTTPException(409, "that stack belongs to another batch; scrap it there")
        chosen = "stack"
    else:
        if chosen not in ("scanned", "list"):
            raise HTTPException(422, "say how the devices were chosen: scanned or list")
        twins = _twins_of_devices(db, run, _resolve_devices(db, run, device_ids, codes))
    # A scrapped named unit is disposed of too (decision 0074), so the shelf
    # and the twin say the same thing.
    devices = [db.get(M.DeviceUnit, tw.device_unit_id) for tw in twins if tw.device_unit_id]
    held = [d for d in devices if d.state not in ("returned", "in_stock", "missing", "")]
    plan = {"dry_run": dry_run, "units": len(twins), "chosen": chosen,
            "disposed": len([d for d in devices if d.state]) - len(held),
            "refused": [{"unit": d.serial or d.mac, "why": [f"it is {d.state or 'unrecorded'}"]} for d in held]}
    if dry_run:
        return plan
    if held:
        raise HTTPException(409, {"error": "only a unit we hold can be scrapped — see the plan", "plan": plan})
    sr = _new_run(db, run, v, {"key": "scrap", "label": "Scrapped", "kind": "scrap"},
                  len(twins), chosen, "", actor, reason)
    _link(db, twins, sr)
    now = utcnow()
    for tw in twins:
        tw.status = "scrapped"
        tw.scrapped_at = now
    from .orders import dispose_device

    for d in devices:
        if d.state:   # a device with no recorded state has no shelf to leave
            dispose_device(db, d, reason=reason, actor=actor,
                           note=f"scrapped on the batch screen, click #{sr.id}", scrap_twin=False)
    db.flush()
    plan["step_run_id"] = sr.id
    return plan


def scrap_disposed(db: Session, device: M.DeviceUnit, *, reason: str = "", actor: str = "") -> None:
    """A device disposed of on its own page takes its twin with it (decision
    0074), finished or not: its cost then falls on the good units of its
    origin batch (0059 §11) until that batch is closed, and after the close it
    is a loss against the frozen share."""
    tw = db.query(M.Twin).filter_by(device_unit_id=device.id).first()
    if tw is None or tw.status == "scrapped":
        return
    run = db.get(M.ProductionRun, tw.run_id)
    v = (db.get(M.ProcessVersion, run.process_version_id) if run is not None and run.process_version_id
         else db.get(M.ProcessVersion, tw.process_version_id))
    if run is not None and v is not None:
        # The note keeps the status it had: "Undo rebuild" puts it back.
        sr = _new_run(db, run, v, {"key": "scrap", "label": "Scrapped", "kind": "scrap"}, 1, "list", "", actor,
                      (f"disposed of: {reason}" if reason else "disposed of") + f" (was {tw.status})")
        _link(db, [tw], sr)
    tw.status = "scrapped"
    tw.scrapped_at = utcnow()
    db.flush()


def reopen(db: Session, run: M.ProductionRun, *, device_ids: list[int] | None = None,
           codes: list[str] | None = None, chosen: str = "", reason: str = "", actor: str = "",
           dry_run: bool = True) -> dict:
    """Finished units go back into work (decision 0074): a new label, a new
    enclosure, a unit back from a customer. The twin is active again, can take
    steps, and ships only after a new finish."""
    crafted_version(db, run)
    _refuse_closed(run)
    if not (reason or "").strip():
        raise HTTPException(422, "say why these units are reopened")
    if chosen not in ("scanned", "list"):
        raise HTTPException(422, "say how the devices were chosen: scanned or list")
    devices = _resolve_devices(db, run, device_ids, codes)
    twins, refused = [], []
    for d in devices:
        tw = db.query(M.Twin).filter_by(device_unit_id=d.id).first()
        why = ("it has no twin" if tw is None else
               "it is in another batch" if tw.run_id != run.id else
               f"it is {tw.status}, not finished" if tw.status != "finished" else
               f"it is {d.state or 'unrecorded'}, not here" if d.state not in ("in_stock", "returned") else None)
        if why:
            refused.append({"unit": d.serial or d.mac, "why": [why]})
        else:
            twins.append(tw)
    plan = {"dry_run": dry_run, "units": len(twins), "chosen": chosen, "refused": refused}
    if dry_run:
        return plan
    if refused:
        raise HTTPException(409, {"error": "these units cannot be reopened — see the plan", "plan": plan})
    sr = _new_run(db, run, crafted_version(db, run),
                  {"key": "reopen", "label": "Reopened for rework", "kind": "reopen"},
                  len(twins), chosen, "", actor, reason)
    _link(db, twins, sr)
    for tw in twins:
        tw.status = "active"
        tw.finished_at = None
    db.flush()
    plan["step_run_id"] = sr.id
    return plan


def finish(db: Session, run: M.ProductionRun, *, device_ids: list[int] | None = None,
           codes: list[str] | None = None, chosen: str = "", note: str = "", actor: str = "",
           dry_run: bool = True) -> dict:
    """The last step, done by a person on devices chosen by name, MAC or barcode.
    A device that misses a required step is refused, and the refusal names it."""
    v = crafted_version(db, run)
    graph = P._graph(v)
    step = P.step_of_kind(graph, "finish")
    if step is None:
        raise HTTPException(409, "this process has no finish step")
    if chosen not in ("scanned", "list"):
        raise HTTPException(422, "say how the devices were chosen: scanned or list")
    devices = _resolve_devices(db, run, device_ids, codes)
    twins = _twins_of_devices(db, run, devices)
    done = done_steps(db, [tw.id for tw in twins])
    again = since_reopen(db, [tw.id for tw in twins])
    names = {d.id: d.serial or d.mac for d in devices}
    refused = [{"unit": names.get(tw.device_unit_id), "why": why}
               for tw in twins if (why := needs_met(graph, step, done[tw.id], again.get(tw.id)))]
    plan = {"dry_run": dry_run, "units": len(twins), "chosen": chosen, "refused": refused}
    if dry_run:
        return plan
    if refused:
        raise HTTPException(409, {"error": "these devices miss a required step — see the plan",
                                  "plan": plan})
    sr = _new_run(db, run, v, step, len(twins), chosen, "", actor, note)
    _link(db, twins, sr)
    now = utcnow()
    for tw in twins:
        tw.status = "finished"
        tw.finished_at = now
    db.flush()
    plan["step_run_id"] = sr.id
    return plan


def enter_found(db: Session, run: M.ProductionRun, *, qty: int = 0, done: list[str],
                origin_run_id: int, device_ids: list[int] | None = None, note: str = "",
                actor: str = "", dry_run: bool = True) -> dict:
    """Units that exist but have no twin — the stock count's spares, or devices
    made before twins. They enter at ZERO value with the steps they have
    already been through; their cost sits in the books of `origin_run_id`
    (0059 §15). Unnamed units go into a stack of `run`; devices are named twins."""
    v = crafted_version(db, run)
    graph = P._graph(v)
    smap = P.step_map(graph)
    origin = db.get(M.ProductionRun, origin_run_id)
    if origin is None or origin.project_id != run.project_id:
        raise HTTPException(404, "no such origin batch in this project")
    if not (note or "").strip():
        raise HTTPException(422, "say where these units came from")
    # One path for counted spares (decision 0075): units the origin batch
    # already holds unnamed are its spares, not found units.
    own = (db.query(func.count(M.Twin.id)).filter(M.Twin.origin_run_id == origin.id, M.Twin.found.is_(False),
                                                  M.Twin.device_unit_id.is_(None), M.Twin.status == "active")
           .scalar() or 0)
    if own and not device_ids:
        raise HTTPException(409, f"{origin.label} already holds {own} unnamed unit(s) of its own (its rebuilt "
                                 "spares or received boards) — take them from its stacks, or undo them, rather "
                                 "than entering the same units as found")
    bad = [k for k in done if k not in smap]
    if bad:
        raise HTTPException(422, f"no step {bad[0]!r} in this process version")
    for kind in ("receive", "assembly"):
        k = (P.step_of_kind(graph, kind) or {}).get("key")
        if k and k not in done:
            done = [k, *done]
    devices = _resolve_devices(db, run, device_ids, None) if device_ids else []
    for d in devices:
        if db.query(M.Twin).filter_by(device_unit_id=d.id).first() is not None:
            raise HTTPException(409, f"{d.serial or d.mac} already has a twin")
        if d.production_run_id is not None:
            # Its batch already counts it and carries its cost (0043): entered
            # at zero it would drop that cost out of every order. Rebuild the
            # batch instead (decision 0060 §7).
            other = db.get(M.ProductionRun, d.production_run_id)
            raise HTTPException(409, f"{d.serial or d.mac} was produced in "
                                     f"{other.label if other else d.production_run_id} — rebuild that "
                                     "batch into twins instead of entering it as found")
    n = len(devices) if devices else qty
    if n <= 0:
        raise HTTPException(422, "enter at least one unit")
    plan = {"dry_run": dry_run, "units": n, "done": done, "origin_run_id": origin.id,
            "named": bool(devices)}
    if dry_run:
        return plan
    # Found units are their own pile: a token names where they came from, so
    # the bench never names one in place of a board the batch received.
    key = "|".join(sorted(set(done) | {f"{FOUND}@{origin.id}"}))
    twins = [M.Twin(project_id=run.project_id, origin_run_id=origin.id, run_id=run.id,
                    process_version_id=v.id, stack_key=key, found=True, note=note[:500],
                    device_unit_id=(devices[i].id if devices else None),
                    named_at=(utcnow() if devices else None))
             for i in range(n)]
    db.add_all(twins)
    db.flush()
    for k in done:
        sr = _new_run(db, run, v, smap[k], n, "found", "", actor,
                      f"already done when found: {note}")
        _link(db, twins, sr)
    plan["stack"] = None if devices else stack_id(run.id, key)
    return plan


# ======================================================= assembly and costs

#: Stages whose positions are the board's own manufacture: the bare PCB and
#: its assembly (decision 0060). On a crafted batch they all belong to the
#: one assembly order, so they all pay for its assembly step.
ASSEMBLY_STAGES = ("fab", "pcba")


def repin(db: Session, run: M.ProductionRun, version_id: int, *, dry_run: bool = True) -> dict:
    """Move a batch to another published version of its process (decision
    0074): a version published with an error, or the version that really
    describes how its devices were made. Refused on a closed batch, and when
    a twin of the batch has done a step the target version does not have —
    its history would then name steps its process does not know. The clicks
    keep the version they ran under. Undo is a re-pin back."""
    _refuse_closed(run)
    v = db.get(M.ProcessVersion, version_id)
    if v is None or v.project_id != run.project_id or v.status != "published":
        raise HTTPException(404, "no such published process version in this project")
    old = db.get(M.ProcessVersion, run.process_version_id) if run.process_version_id else None
    if old is None:
        raise HTTPException(409, f"batch {run.label} has no process — rebuild it into twins instead")
    smap = P.step_map(P._graph(v))
    twins = db.query(M.Twin).filter(M.Twin.run_id == run.id).all()
    done = done_steps(db, [tw.id for tw in twins])
    missing: dict[str, int] = defaultdict(int)
    for tw in twins:
        for k in (done[tw.id] | done_of_key(tw.stack_key)) - {"scrap", "reopen"}:
            if k not in smap:
                missing[k] += 1
    for (k,) in (db.query(M.StepRun.step_key).filter(M.StepRun.run_id == run.id,
                                                      M.StepRun.kind.notin_(("scrap", "reopen")))
                 .distinct().all()):
        if k not in smap and k not in missing:
            missing[k] = 0   # a click of the batch, its assembly first among them
    bench = sorted(done_of_key(parse_stack(run.bench_stack)[1]) - set(smap)) if run.bench_stack else []
    prog = P.step_of_kind(P._graph(v), "program")
    stale = bool(run.bench_stack and not bench and prog is not None and needs_met(
        P._graph(v), prog, done_of_key(parse_stack(run.bench_stack)[1])))
    old_keys = set(P.step_map(P._graph(old)))
    plan = {"dry_run": dry_run, "run_id": run.id, "from_version": old.version_no, "to_version": v.version_no,
            "twins": len(twins), "added_steps": sorted(set(smap) - old_keys),
            "removed_steps": sorted(old_keys - set(smap)),
            "missing": [{"step": k, "twins": n} for k, n in sorted(missing.items())],
            "bench_stack_missing": bench, "bench_stack_cleared": stale}
    if missing or bench:
        named = [f"{k} ({n} twin(s))" if n else f"{k} (a click of the batch)" for k, n in sorted(missing.items())]
        named += [f"{k} (the bench stack)" for k in bench]
        raise HTTPException(409, {"error": f"process version {v.version_no} lacks steps the batch's twins "
                                           f"have done: {', '.join(named)}", "plan": plan})
    if dry_run or old.id == v.id:
        return plan
    run.process_version_id = v.id
    if stale:
        # The target's program step needs more than that pile has done: the
        # bench says "no stack selected" until a person picks one (0037).
        run.bench_stack = ""
    db.flush()
    return plan


def assembly_orders(db: Session, run: M.ProductionRun) -> list[str]:
    """The supplier assembly orders linked to `run` (JLC SMT order codes)."""
    return sorted(d.smt_order_code for d in db.query(M.JlcOrderDecision)
                  .filter_by(run_id=run.id, outcome="link_run").all())


def assembly_click(db: Session, run: M.ProductionRun) -> M.StepRun | None:
    """The batch's one assembly click, if it is recorded."""
    return (db.query(M.StepRun).filter(M.StepRun.run_id == run.id, M.StepRun.kind == "assembly",
                                       M.StepRun.chosen != "found")
            .order_by(M.StepRun.id).first())


def _linked_ids(db: Session, run_id: int) -> set[int]:
    """Lines linked to clicks of `run_id`. A link to another batch's click does
    not count: the line was re-charged since, and its new batch must see it."""
    clicks = {lid for (lid,) in db.query(M.CostLineStep.line_id)
              .join(M.StepRun, M.StepRun.id == M.CostLineStep.step_run_id)
              .filter(M.StepRun.run_id == run_id).distinct().all()}
    # A position linked to a whole step with no click yet is linked too: it
    # waits for the clicks (decision 0074).
    return clicks | {lid for (lid,) in db.query(M.CostLineStepKey.line_id)
                     .filter(M.CostLineStepKey.run_id == run_id).distinct().all()}


def charged_lines(db: Session, run: M.ProductionRun, *, unlinked_only: bool = False
                  ) -> list[M.RunCostLine]:
    """Leaf positions whose money goes to `run`, as the register sends it there
    (`run_actuals.line_destination`). Headers, voided lines and pro-formas are
    not money and are left out."""
    q = (db.query(M.RunCostLine)
         .join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
         .filter(M.RunCostLine.voided_at.is_(None),
                 (M.RunCostLine.run_id == run.id)
                 | (M.RunCostLine.run_id.is_(None) & (M.RunCostDocument.run_id == run.id))))
    hdrs = run_actuals.header_ids(db)
    linked = _linked_ids(db, run.id) if unlinked_only else set()
    out = []
    for li in q.order_by(M.RunCostLine.id).all():
        doc = db.get(M.RunCostDocument, li.document_id)
        if li.id in hdrs or li.id in linked or (doc.doc_type or "invoice") == "proforma":
            continue
        if run_actuals.line_destination(li, doc) == ("run", run.id):
            out.append(li)
    return out


def _refuse_closed(run: M.ProductionRun) -> None:
    if run.closed_at is not None:
        raise HTTPException(409, f"batch {run.label} is closed — its twins' shares are frozen "
                                 "(decision 0044); reopen it first")


def link_line(db: Session, line: M.RunCostLine, clicks: list[M.StepRun]) -> None:
    """Point `line` at `clicks`, replacing any link it had (decision 0061).

    Row by row, never a bulk delete: the write journal sees each removed link,
    so an undo puts it back, and a link that already points at a wanted click
    is left alone (decision 0072)."""
    want = {c.id for c in clicks}
    rows = db.query(M.CostLineStep).filter_by(line_id=line.id).all()
    for r in rows:
        if r.step_run_id not in want:
            db.delete(r)
    have = {r.step_run_id for r in rows}
    for sid in sorted(want - have):
        db.add(M.CostLineStep(line_id=line.id, step_run_id=sid))
    db.flush()


def _assembly_twins(db: Session, run: M.ProductionRun) -> list[M.Twin]:
    """The twins an assembly step is about: every board received in the batch.
    The found ones entered at zero and never saw the supplier."""
    return (db.query(M.Twin).filter(M.Twin.origin_run_id == run.id, M.Twin.found.is_(False))
            .order_by(M.Twin.id).all())


def _line_row(db: Session, li: M.RunCostLine) -> dict:
    doc = db.get(M.RunCostDocument, li.document_id)
    return {"line_id": li.id, "label": li.label or li.description or "", "plan_key": li.plan_key or "",
            "stage": cost_steps.stage_of(li.plan_key) or "",
            "amount": round(run_actuals.effective_qty(li, doc, db) * (li.unit_price or 0), 4),
            "currency": li.currency or (doc.currency if doc else "") or "USD",
            "doc_id": li.document_id, "doc_number": doc.doc_number if doc else "",
            "supplier": doc.supplier if doc else "", "doc_date": doc.doc_date if doc else ""}


def _draw_row(db: Session, c: M.ComponentConsumption, names: dict[int, str]) -> dict:
    lots = [{"lot": (f"L{b.lot_line_id}" if b.lot_line_id else f"A{b.lot_adjustment_id}"), "qty": b.qty}
            for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id).all()
            if b.lot_line_id or b.lot_adjustment_id]
    ref = c.import_ref or ""
    return {"consumption_id": c.id, "component_id": c.component_id,
            "name": names.get(c.component_id or 0, ""), "mpn": c.mpn or "", "lcsc": c.lcsc or "",
            "qty": c.qty, "unit_cost_usd": c.unit_cost_usd,
            "value_usd": round((c.qty or 0) * (c.unit_cost_usd or 0), 4),
            "order": ref.split(":")[2] if ref.startswith("jlc:") and ref.count(":") >= 3 else "",
            "lots": lots}


def _line_kind(db: Session, li: M.RunCostLine) -> str:
    """A parts total not split yet (`parts_lump`), one part the assembler
    bought — a child of a split parts total (`supplied_part`) — or any other
    position. A JLC parts total is itself a child of the order's fee split
    (`pcba:general`), so the parent's step decides, not whether it has one."""
    if (li.plan_key or "") != "pcba:parts":
        return "position"
    parent = db.get(M.RunCostLine, li.parent_line_id) if li.parent_line_id else None
    return "supplied_part" if parent is not None and (parent.plan_key or "") == "pcba:parts" else "parts_lump"


def is_parts_lump(db: Session, li: M.RunCostLine) -> bool:
    return _line_kind(db, li) == "parts_lump" and li.id not in run_actuals.header_ids(db, li.document_id)


def _names(db: Session, ids) -> dict[int, str]:
    ids = {i for i in ids if i}
    return {c.id: c.name for c in db.query(M.Component).filter(M.Component.id.in_(ids)).all()} if ids else {}


def assembly_draft(db: Session, run: M.ProductionRun) -> dict:
    """What "Record assembly" opens with (decision 0072): the step as it
    stands, and every row that is not in it yet, read from the batch's records
    and the JLC data. Nothing is written. Each row starts ticked; the person
    decides."""
    from . import jlc_import, substitutions, supplier_parts

    v = crafted_version(db, run)
    step = P.step_of_kind(P._graph(v), "assembly")
    out: dict = {"run_id": run.id, "label": run.label, "closed": run.closed_at is not None,
                 "step": ({"key": step["key"], "label": step.get("label") or step["key"]} if step else None),
                 "recorded": None, "lines": [], "parts_from_stock": [], "parts_supplied": [],
                 "parts_lumps": [], "replacements": [], "bom_suggestion": []}
    if step is None:
        return {**out, "status": "no_assembly_step", "header": {}}
    twins = _assembly_twins(db, run)
    sr = assembly_click(db, run)
    in_step = ({tid for (tid,) in db.query(M.TwinStep.twin_id).filter_by(step_run_id=sr.id).all()}
               if sr is not None else set())
    orders = assembly_orders(db, run)
    panels = jlc_import.effective_panels(db) if orders else {}
    devices = [(panels.get(o) or {}).get("devices") for o in orders]
    lines = charged_lines(db, run, unlinked_only=True)
    cand_lines = [li for li in lines if cost_steps.stage_of(li.plan_key) in ASSEMBLY_STAGES]
    dates = sorted(d for d in (db.get(M.RunCostDocument, li.document_id).doc_date for li in cand_lines) if d)
    out["header"] = {
        "assembler": "JLCPCB" if orders else "", "orders": orders, "reference": ", ".join(orders),
        "made_at": (sr.made_at if sr is not None else (dates[0] if dates else "") or run.run_date or _today()),
        "boards_jlc": (int(sum(devices)) if devices and all(isinstance(x, (int, float)) for x in devices)
                       else None),
        "twins": len(twins), "twins_not_in_step": len([t for t in twins if t.id not in in_step])}
    hdrs = run_actuals.header_ids(db)
    out["lines"] = [_line_row(db, li) | {"kind": _line_kind(db, li), "is_parts_lump": _line_kind(db, li) == "parts_lump"}
                    for li in cand_lines]
    draws = (run_actuals.live_consumption(db, run_id=run.id)
             .filter(M.ComponentConsumption.basis == "measured",
                     M.ComponentConsumption.step_run_id.is_(None)).order_by(M.ComponentConsumption.id).all())
    names = _names(db, [c.component_id for c in draws])
    out["parts_from_stock"] = [_draw_row(db, c, names) for c in draws]
    # The parts the assembler bought: each parts total charged to the batch
    # that is not split yet, broken down from the supplier's BOM when it has
    # one. A total split before (the invoice's "supplier" button) is a list of
    # positions already, offered above as `supplied_part` lines.
    for li in lines:   # not in a step yet: a total linked whole is the step's already
        if li.id in hdrs or _line_kind(db, li) != "parts_lump":
            continue
        plan = supplier_parts.itemise(db, li)
        out["parts_lumps"].append({"line_id": li.id, "label": li.label or "", "amount": _line_row(db, li)["amount"],
                                   "currency": li.currency or "USD", "order": plan.get("smt_order_code") or "",
                                   "residual": plan.get("residual"), "reconciles": plan.get("reconciles"),
                                   "reason": "" if plan.get("ok") else plan.get("reason", "")})
        for ch in plan.get("children") or []:
            out["parts_supplied"].append({"parent_line_id": li.id, "order": plan.get("smt_order_code") or "",
                                          "lcsc": ch["lcsc"], "mpn": ch["mpn"], "designator": ch["designator"],
                                          "qty": ch["qty_supplied"], "unit_price": ch["unit_price"],
                                          "amount": ch["amount"], "source": ch["source"]})
    have = {(s.designator or "").strip() for s in substitutions.for_run(db, run.id)}
    out["replacements"] = [
        {k: c.get(k) for k in ("designator", "supplier_designator", "specified_lcsc", "specified_mpn",
                               "specified_component_id", "fitted_lcsc", "fitted_mpn", "supplied_by",
                               "supplier_source", "match_type", "board", "variant", "order", "evidence")}
        for c in substitutions.detect(db) if c["run_id"] == run.id and c["designator"] not in have]
    if not orders and run.snapshot_id:
        bom = (db.query(M.SnapshotBomLine)
               .filter_by(snapshot_id=run.snapshot_id, board=run.board or "", variant=run.variant or "")
               .filter(M.SnapshotBomLine.dnp.is_(False), M.SnapshotBomLine.exclude_from_bom.is_(False))
               .order_by(M.SnapshotBomLine.position).all())
        bnames = _names(db, [li.component_id for li in bom])
        boards = len(twins)
        # Less what the step drew already, so "Add to assembly" offers the rest.
        drawn: dict = defaultdict(float)
        if sr is not None:
            for c in run_actuals.live_consumption(db).filter(M.ComponentConsumption.step_run_id == sr.id):
                drawn[c.component_id or (c.mpn or "")] += c.qty or 0.0
        rows = []
        for li in bom:
            want = (li.qty or 0) * boards
            key = li.component_id or (li.mpn or "")
            take = min(want, drawn.get(key, 0.0))
            drawn[key] = drawn.get(key, 0.0) - take
            if want - take > 0:
                rows.append({"component_id": li.component_id, "name": bnames.get(li.component_id or 0, ""),
                             "mpn": li.mpn or "", "lcsc": li.lcsc or "", "designator": li.refs or "",
                             "qty_per_board": li.qty, "qty": want - take})
        out["bom_suggestion"] = rows
    if sr is not None:
        linked = [db.get(M.RunCostLine, lid) for (lid,) in
                  db.query(M.CostLineStep.line_id).filter_by(step_run_id=sr.id).all()]
        sdraws = (run_actuals.live_consumption(db).filter(M.ComponentConsumption.step_run_id == sr.id)
                  .order_by(M.ComponentConsumption.id).all())
        snames = _names(db, [c.component_id for c in sdraws])
        out["recorded"] = {
            "step_run_id": sr.id, "made_at": sr.made_at, "assembler": sr.assembler or "",
            "reference": sr.reference or "", "note": sr.note or "", "units": sr.qty, "chosen": sr.chosen,
            "lines": [_line_row(db, li) | {"kind": _line_kind(db, li)} for li in linked
                      if li is not None and li.id not in hdrs and li.voided_at is None],
            "draws": [_draw_row(db, c, snames) for c in sdraws],
            "replacements": [{"id": x.id, "designator": x.designator, "specified_lcsc": x.specified_lcsc,
                              "fitted_lcsc": x.fitted_lcsc, "fitted_mpn": x.fitted_mpn,
                              "supplied_by": x.supplied_by}
                             for x in db.query(M.RunSubstitution).filter_by(step_run_id=sr.id).all()],
            # A closed batch's step is undone only after it is reopened.
            "batch_ids": [] if run.closed_at is not None else [wb.id for wb in db.query(M.WriteBatch)
                          .filter(M.WriteBatch.kind == "craft.assembly",
                                  M.WriteBatch.source_ref == f"run:{run.id}",
                                  M.WriteBatch.reversed_at.is_(None))
                          .order_by(M.WriteBatch.id.desc()).all()]}
    out["status"] = "no_twins" if not twins else ("recorded" if sr is not None else "open")
    return out


def apply_assembly(db: Session, run: M.ProductionRun, *, made_at: str = "", assembler: str = "",
                   reference: str = "", note: str = "", line_ids: list[int] | None = None,
                   draw_ids: list[int] | None = None, parts: list[dict] | None = None,
                   actor: str = "") -> tuple[M.StepRun, dict]:
    """Record, or add to, the board's assembly step with what the person
    ticked in "Record assembly" (decision 0072). It joins every received twin
    not in the step yet, links the chosen positions and measured draws, and
    writes the draws of the parts from our stock that another assembly house
    used (`parts`), from the batch company's stock at its average on the day.
    It writes, never commits: the caller wraps it in one journal batch, or
    rolls it back for a dry run. Returns the click and the counts."""
    v = crafted_version(db, run)
    step = P.step_of_kind(P._graph(v), "assembly")
    if step is None:
        raise HTTPException(409, "this process has no assembly step")
    _refuse_closed(run)
    # One writer at a time per batch: two records racing would each make a click.
    db.query(M.ProductionRun).filter_by(id=run.id).with_for_update().one()
    line_ids = list(dict.fromkeys(line_ids or []))
    draw_ids = list(dict.fromkeys(draw_ids or []))
    twins = _assembly_twins(db, run)
    if not twins:
        raise HTTPException(409, f"{run.label}: receive the boards first — the assembly step is "
                                 "recorded on the twins the receive makes")
    offered = {li.id: li for li in charged_lines(db, run, unlinked_only=True)}
    bad = [lid for lid in (line_ids or []) if lid not in offered]
    if bad:
        raise HTTPException(422, f"position(s) {bad} are not charged to {run.label}, or are in a step already")
    free = {c.id: c for c in run_actuals.live_consumption(db, run_id=run.id)
            .filter(M.ComponentConsumption.basis == "measured", M.ComponentConsumption.step_run_id.is_(None))}
    bad = [did for did in (draw_ids or []) if did not in free]
    if bad:
        raise HTTPException(422, f"draw(s) {bad} are not measured draws of {run.label} outside a step")
    sr = assembly_click(db, run)
    created = sr is None
    orders = assembly_orders(db, run)
    asked = (made_at or "").strip()[:10]
    if sr is not None and asked and asked != sr.made_at:
        # Its draws are dated with the step: priced and checked on any other
        # day they would take stock the pool did not hold then.
        raise HTTPException(422, f"the assembly of {run.label} is recorded on {sr.made_at}; "
                                 "what is added to it takes that date")
    day = (sr.made_at if sr is not None else "") or asked or run.run_date or _today()
    # The parts from our stock another house used: priced and checked first, so
    # nothing is written when the batch company does not hold them.
    scope = run_actuals.run_scope(db, run)
    planned, problems = [], []
    for i, p in enumerate(parts or []):
        qty = float(p.get("qty") or 0)
        if qty <= 0:
            continue
        entry = run_actuals.resolve_pool_identity(db, p.get("component_id"), p.get("mpn") or "",
                                                  p.get("lcsc") or "", as_of=day, company_id=scope)
        if entry is None:
            problems.append(p.get("mpn") or p.get("lcsc") or f"row {i + 1}")
            continue
        planned.append({"component_id": entry.get("component_id"), "mpn": entry.get("mpn") or p.get("mpn") or "",
                        "lcsc": entry.get("lcsc") or p.get("lcsc") or "", "qty": qty,
                        "unit_cost_usd": float(entry.get("avg_usd") or 0.0),
                        "name": p.get("name") or entry.get("mpn") or ""})
    if problems:
        raise HTTPException(422, f"no stock ever held of: {', '.join(map(str, problems))}")
    from . import lots as _lots

    uncovered = _lots.fifo_price(db, planned, as_of=day, company_id=scope)
    if uncovered:
        raise HTTPException(409, {"error": "these parts are in no lot on " + day + ": "
                                           + "; ".join(f"{u['label']} {u['problem']}" for u in uncovered[:6]),
                                  "uncovered": uncovered})
    short = run_actuals.check_shortages(db, [
        {"component_id": d["component_id"], "mpn": d["mpn"], "lcsc": d["lcsc"], "qty": d["qty"],
         "date": day, "label": d["name"]} for d in planned], company_id=scope)
    if short:
        named = ", ".join(f"{x.get('label') or x.get('mpn')} short {x.get('short')}" for x in short[:6])
        raise HTTPException(409, {"error": f"the stock does not hold these parts on {day}: {named}",
                                  "shortages": short})
    if sr is not None and sr.step_key != step["key"]:
        # The batch moved to a version whose assembly step has another key:
        # one click must not carry two keys (decision 0074).
        raise HTTPException(409, f"the assembly of {run.label} is recorded as step {sr.step_key!r}, and its "
                                 f"process now calls it {step['key']!r} — move the batch back, or undo the "
                                 "assembly first")
    if sr is None:
        sr = _new_run(db, run, v, step, 0, "supplier" if orders else "manual", day, actor,
                      note or (f"assembly order {', '.join(orders)}" if orders else "assembly"))
    if assembler.strip() or created:
        sr.assembler = assembler.strip()[:120]
    if reference.strip() or created:
        sr.reference = reference.strip()[:200]
    if note.strip() and not created:
        sr.note = f"{sr.note or ''}\n{note.strip()}"[:500]
    have = {tid for (tid,) in db.query(M.TwinStep.twin_id).filter_by(step_run_id=sr.id).all()}
    new = [tw for tw in twins if tw.id not in have]
    _link(db, new, sr)
    for tw in new:
        tw.stack_key = _add_token(tw.stack_key, step["key"])
    sr.qty = len(have) + len(new)
    if created:
        _link_step_keys(db, run, sr)
    for lid in line_ids or []:
        link_line(db, offered[lid], [sr])
        # Ticked onto this batch's assembly: a whole-step link it kept from
        # another batch says nothing true any more.
        for k in db.query(M.CostLineStepKey).filter(M.CostLineStepKey.line_id == lid,
                                                    M.CostLineStepKey.run_id != run.id).all():
            db.delete(k)
    for did in draw_ids or []:
        free[did].step_run_id = sr.id
    if planned:
        write_draws(db, run, sr, planned, f"assembly at {sr.assembler or 'the assembler'}: our stock")
    db.flush()
    line_usd = run_actuals.leaf_line_usd(db, [offered[lid] for lid in line_ids or []])
    return sr, {"status": "recorded" if created else "extended", "step_run_id": sr.id, "units": sr.qty,
                "twins_added": len(new), "lines_linked": len(line_ids or []),
                "draws_linked": len(draw_ids or []), "draws_written": len(planned),
                "value_usd": {"lines": round(sum(v[0] for v in line_usd.values()), 4),
                              "draws": round(sum((free[d].qty or 0) * (free[d].unit_cost_usd or 0)
                                                 for d in draw_ids or []), 4),
                              "parts": round(sum(d["qty"] * d["unit_cost_usd"] for d in planned), 4)}}


def link_costs(db: Session, run: M.ProductionRun, *, step_run_ids: list[int] | None,
               line_ids: list[int], step_keys: list[str] | None = None, unlink: bool = False,
               actor: str = "", dry_run: bool = True) -> dict:
    """Say which step clicks an invoice position paid for (decisions 0060, 0061).

    One position can pay for several clicks — the final assembler's invoice
    covers programming, the enclosure, the laser mark and the label — and the
    twins of all of them share it equally. The position must be charged to this
    batch: the link moves no money between batches, it only says which twins
    carry it. A header stands for its children. Unlinking puts the money back
    into the origin batch cost."""
    crafted_version(db, run)
    _refuse_closed(run)
    clicks: list[M.StepRun] = []
    if not unlink:
        # A whole step: every click of it in this batch, however many there are
        # (programming is one click per device).
        for sr in (db.query(M.StepRun).filter(M.StepRun.run_id == run.id,
                                              M.StepRun.step_key.in_(step_keys or []),
                                              M.StepRun.kind != "scrap", M.StepRun.chosen != "found",
                                              M.StepRun.qty > 0).all()
                   if step_keys else []):
            clicks.append(sr)
        for cid in step_run_ids or []:
            sr = db.get(M.StepRun, int(cid))
            if sr is None or sr.run_id != run.id:
                raise HTTPException(404, f"no step click {cid} in this batch")
            if not sr.qty or sr.kind == "scrap" or sr.chosen == "found":
                raise HTTPException(409, f"step click {cid} cannot carry a cost: it has no units, is a "
                                         "scrap, or records units entered at zero")
            clicks.append(sr)
        smap = P.step_map(P._graph(crafted_version(db, run)))
        bad = [k for k in step_keys or [] if k not in smap]
        if bad:
            raise HTTPException(422, f"no step {bad[0]!r} in this batch's process")
        # A whole step may have no click yet: the link waits for them (0074).
        if not clicks and not step_keys:
            raise HTTPException(422, "select at least one step click")
    lines: list[M.RunCostLine] = []
    headers: list[M.RunCostLine] = []
    seen: set[int] = set()
    for lid in line_ids or []:
        li = db.get(M.RunCostLine, int(lid))
        if li is None:
            raise HTTPException(404, f"no position {lid}")
        # A header stands for its live leaves, at any depth; every header on
        # the way follows them (decision 0074).
        frontier = [li]
        while frontier:
            x = frontier.pop()
            kids = (db.query(M.RunCostLine)
                    .filter(M.RunCostLine.parent_line_id == x.id, M.RunCostLine.voided_at.is_(None)).all())
            if kids:
                if x.id not in {h.id for h in headers}:
                    headers.append(x)
                frontier.extend(kids)
            elif x.id not in seen:
                seen.add(x.id)
                lines.append(x)
    if not lines:
        raise HTTPException(422, "select at least one position")
    charged = {li.id for li in charged_lines(db, run)}
    refused = [{"line_id": li.id, "label": li.label, "why": "it is not charged to this batch"}
               for li in lines if li.id not in charged]
    before = defaultdict(list)
    for lid, srid in (db.query(M.CostLineStep.line_id, M.CostLineStep.step_run_id)
                      .filter(M.CostLineStep.line_id.in_([li.id for li in lines])).all()):
        before[lid].append(srid)
    keys_before = defaultdict(list)
    for lid, k in (db.query(M.CostLineStepKey.line_id, M.CostLineStepKey.step_key)
                   .filter(M.CostLineStepKey.line_id.in_([li.id for li in lines])).all()):
        keys_before[lid].append(k)
    plan = {"dry_run": dry_run, "step_run_ids": [] if unlink else [c.id for c in clicks],
            "unlink": unlink,
            "lines": [{"line_id": li.id, "label": li.label, "plan_key": li.plan_key,
                       "from_step_run_ids": sorted(before.get(li.id, [])),
                       "from_step_keys": sorted(keys_before.get(li.id, []))} for li in lines],
            "refused": refused}
    if dry_run:
        return plan
    if refused:
        what = "unlinked" if unlink else "linked"
        raise HTTPException(409, {"error": f"some positions cannot be {what}: "
                                           + "; ".join(f"{r['label']} — {r['why']}" for r in refused[:4])
                                           + (" — unlink this batch's own share instead" if unlink else ""),
                                  "plan": plan})
    # A header follows its children (decision 0074): it is the source a later
    # split copies, and valued at zero, so its links move no money.
    for li in lines + headers:
        link_line(db, li, [] if unlink else clicks)
        link_keys(db, li, run, [] if unlink else list(step_keys or []))
    # A link replaces what the lines said before, so the headers above them
    # lose what no leaf holds any more, as after an unlink.
    _unlink_around(db, run, [li.id for li in lines], [int(x) for x in line_ids or []], relink=not unlink)
    return plan


def _unlink_around(db: Session, run: M.ProductionRun, leaf_ids: list[int], named: list[int], *,
                   relink: bool = False) -> None:
    """An unlink leaves no link of this batch where a later split could copy
    it back (decision 0074): not on a voided line below what was named, and
    not on a header above it unless another leaf of this batch below that
    header holds the same link. After a link (`relink`), the leaves just
    linked hold their new links, and the voided lines are left as they are."""
    mine_clicks = {sid for (sid,) in db.query(M.StepRun.id).filter_by(run_id=run.id).all()}

    def clear(line_id: int) -> None:
        for k in db.query(M.CostLineStepKey).filter_by(line_id=line_id, run_id=run.id).all():
            db.delete(k)
        for x in db.query(M.CostLineStep).filter(M.CostLineStep.line_id == line_id,
                                                 M.CostLineStep.step_run_id.in_(mine_clicks or {-1})).all():
            db.delete(x)

    seen, frontier = set(named), [] if relink else list(named)
    while frontier:                       # every line below, voided ones too
        kids = db.query(M.RunCostLine).filter(M.RunCostLine.parent_line_id.in_(frontier)).all()
        frontier = []
        for k in kids:
            if k.id not in seen:
                seen.add(k.id)
                frontier.append(k.id)
                if k.voided_at is not None:
                    clear(k.id)
    charged = {li.id for li in charged_lines(db, run)}
    done: set[int] = set()
    for lid in leaf_ids:                  # every header above, link by link
        li = db.get(M.RunCostLine, lid)
        while li is not None and li.parent_line_id:
            parent = db.get(M.RunCostLine, li.parent_line_id)
            if parent is None:
                break
            if parent.id not in done:
                done.add(parent.id)
                stack, leaves = [parent.id], set()
                while stack:
                    x = stack.pop()
                    ks = [k for (k,) in db.query(M.RunCostLine.id).filter(M.RunCostLine.parent_line_id == x,
                                                                          M.RunCostLine.voided_at.is_(None)).all()]
                    stack.extend(ks)
                    if not ks:
                        leaves.add(x)
                others = ((leaves & charged) - (set() if relink else set(leaf_ids))) or {-1}
                held_keys = {k for (k,) in db.query(M.CostLineStepKey.step_key).filter(
                    M.CostLineStepKey.line_id.in_(others), M.CostLineStepKey.run_id == run.id).all()}
                held_clicks = {s for (s,) in db.query(M.CostLineStep.step_run_id).filter(
                    M.CostLineStep.line_id.in_(others), M.CostLineStep.step_run_id.in_(mine_clicks or {-1})).all()}
                for k in db.query(M.CostLineStepKey).filter_by(line_id=parent.id, run_id=run.id).all():
                    if k.step_key not in held_keys:
                        db.delete(k)
                for x in db.query(M.CostLineStep).filter(M.CostLineStep.line_id == parent.id,
                                                         M.CostLineStep.step_run_id.in_(mine_clicks or {-1})).all():
                    if x.step_run_id not in held_clicks:
                        db.delete(x)
            li = parent
    db.flush()


def step_clicks(db: Session, run_id: int, step_key: str) -> list[int]:
    """Every click of a step in a batch that can carry a cost: what a
    whole-step link means (decisions 0061, 0074)."""
    return [sid for (sid,) in db.query(M.StepRun.id).filter(
        M.StepRun.run_id == run_id, M.StepRun.step_key == step_key, M.StepRun.qty > 0,
        M.StepRun.kind != "scrap", M.StepRun.chosen != "found").all()]


def link_keys(db: Session, line: M.RunCostLine, run: M.ProductionRun, keys: list[str]) -> None:
    """Say that `line` pays for these whole steps of `run`, replacing what it
    said before (decision 0074). Row by row, so the journal sees each one."""
    rows = db.query(M.CostLineStepKey).filter_by(line_id=line.id).all()
    want = {(run.id, k) for k in keys}
    for r in rows:
        if (r.run_id, r.step_key) not in want:
            db.delete(r)
    have = {(r.run_id, r.step_key) for r in rows}
    for rid, k in sorted(want - have):
        db.add(M.CostLineStepKey(line_id=line.id, run_id=rid, step_key=k))
    db.flush()


def unlinked(db: Session, run: M.ProductionRun) -> dict:
    """Money charged to the batch that no step claims: it stays in the origin
    batch cost. Shown on the crafting screen so it is a choice, not an
    oversight."""
    free = charged_lines(db, run, unlinked_only=True)
    vals = run_actuals.leaf_line_usd(db, free)
    lines = [{"line_id": li.id, "label": li.label, "plan_key": li.plan_key,
              "usd": round(vals[li.id][0], 4)} for li in free]
    draws = [{"consumption_id": c.id, "component_id": c.component_id, "mpn": c.mpn,
              "basis": c.basis, "qty": c.qty,
              "usd": round((c.qty or 0) * (c.unit_cost_usd or 0), 4)}
             for c in run_actuals.live_consumption(db, run_id=run.id)
             .filter(M.ComponentConsumption.step_run_id.is_(None)).all()]
    return {"lines": lines, "draws": draws,
            "usd": round(sum(x["usd"] for x in lines) + sum(x["usd"] for x in draws), 4)}


# ===================================================================== bench

def bench_stacks(db: Session, run: M.ProductionRun) -> list[dict]:
    """Stacks of the project that may go on the programming bench: their units
    meet the program step's needs. They may belong to any batch (0059 §12)."""
    if not run.process_version_id:
        return []
    graph = P._graph(crafted_version(db, run))
    prog = P.step_of_kind(graph, "program")
    if prog is None:
        return []
    return [s for s in stacks(db, run.project_id)
            if not needs_met(graph, prog, set(s["done"]))]


def set_bench_stack(db: Session, run: M.ProductionRun, stack: str | None) -> dict:
    if not stack:
        run.bench_stack = ""
        db.flush()
        return {"run_id": run.id, "stack": None}
    if not any(s["stack"] == stack for s in bench_stacks(db, run)):
        raise HTTPException(422, "that stack is not ready for programming in this project")
    run.bench_stack = stack
    db.flush()
    return {"run_id": run.id, "stack": stack, "left": bench_stack_left(db, run)}


def _bench_keys(db: Session, rid: int, key: str) -> list[str]:
    """The stack keys one selected bench stack stands for. Recording or
    undoing the assembly (decision 0072) adds or takes away its token on every
    board of a batch without touching the pile, so the selection names the same
    boards with or without it."""
    batch = db.get(M.ProductionRun, rid)
    v = db.get(M.ProcessVersion, batch.process_version_id) if batch is not None and batch.process_version_id else None
    step = P.step_of_kind(P._graph(v), "assembly") if v is not None else None
    if step is None:
        return [key]
    toks = set(_tokens(key))
    return sorted({key, "|".join(sorted(toks | {step["key"]})), "|".join(sorted(toks - {step["key"]}))} - {""})


def bench_stack_left(db: Session, run: M.ProductionRun) -> int | None:
    """Units left in the batch's selected stack; None when none is selected."""
    if not run.bench_stack:
        return None
    rid, key = parse_stack(run.bench_stack)
    return (db.query(func.count(M.Twin.id))
            .filter(M.Twin.project_id == run.project_id, M.Twin.run_id == rid,
                    M.Twin.stack_key.in_(_bench_keys(db, rid, key)), M.Twin.device_unit_id.is_(None),
                    M.Twin.status == "active").scalar() or 0)


def _name(db, tw: M.Twin, device: M.DeviceUnit, batch: M.ProductionRun, chosen: str,
          made_at: str, actor: str, programming_run: M.ProgrammingRun | None = None) -> None:
    v = db.get(M.ProcessVersion, batch.process_version_id) or db.get(M.ProcessVersion, tw.process_version_id)
    prog = P.step_of_kind(P._graph(v), "program") or {"key": "program", "label": "Programmed",
                                                       "kind": "program"}
    tw.device_unit_id = device.id
    tw.run_id = batch.id
    tw.named_at = utcnow()
    tw.stack_key = _add_token(tw.stack_key, prog["key"])
    sr = _new_run(db, batch, v, prog, 1, chosen, made_at, actor,
                  f"named {device.serial or device.mac}"
                  + (f" by programming run #{programming_run.id}" if programming_run is not None else ""))
    _link(db, [tw], sr, programming_run_id=programming_run.id if programming_run is not None else None,
          deployment_version_id=programming_run.deployment_version_id if programming_run is not None else None)
    _draw_or_note(db, batch, sr, prog, 1)


def name_at_bench(db: Session, device: M.DeviceUnit, event: M.DeviceEvent,
                  batch: M.ProductionRun | None, programming_run: M.ProgrammingRun | None = None
                  ) -> M.Twin | None:
    """A NEW `produced` event names one twin of the batch's selected stack.

    Called by the bench engine only when `mark_produced` wrote a new event.
    Nothing selected, or the stack used up: no twin is invented, and the device
    shows as a gap on its batch until a merge (0059 §7, §8)."""
    if batch is None or not batch.process_version_id or not batch.bench_stack:
        return None
    if db.query(M.Twin).filter_by(device_unit_id=device.id).first() is not None:
        return None
    rid, key = parse_stack(batch.bench_stack)
    # Locked and skipping locked rows: two stations finishing at the same
    # moment must not name the same twin.
    tw = (db.query(M.Twin)
          .filter(M.Twin.project_id == batch.project_id, M.Twin.run_id == rid,
                  M.Twin.stack_key.in_(_bench_keys(db, rid, key)), M.Twin.device_unit_id.is_(None),
                  M.Twin.status == "active")
          .order_by(M.Twin.id).with_for_update(skip_locked=True).first())
    if tw is None:
        return None
    at = event.at.date().isoformat() if event is not None and event.at else _today()
    _name(db, tw, device, batch, "bench", at, event.actor if event is not None else "",
          programming_run=programming_run)
    db.flush()
    return tw


def gaps(db: Session, run: M.ProductionRun) -> list[M.DeviceUnit]:
    """Devices this crafted batch produced that have no twin behind them."""
    if not run.process_version_id:
        return []
    named = {d for (d,) in db.query(M.Twin.device_unit_id)
             .filter(M.Twin.device_unit_id.isnot(None)).all()}
    return [d for d in db.query(M.DeviceUnit).filter_by(production_run_id=run.id)
            .order_by(M.DeviceUnit.id).all() if d.id not in named]


def merge(db: Session, run: M.ProductionRun, *, stack: str, device_ids: list[int] | None = None,
          codes: list[str] | None = None, chosen: str = "", actor: str = "",
          dry_run: bool = True) -> dict:
    """Close gaps: each chosen gap device takes a twin from `stack` (0059 §8)."""
    crafted_version(db, run)
    if chosen not in ("scanned", "list"):
        raise HTTPException(422, "say how the devices were chosen: scanned or list")
    devices = _resolve_devices(db, run, device_ids, codes)
    gap_ids = {d.id for d in gaps(db, run)}
    not_gaps = [d.serial or d.mac for d in devices if d.id not in gap_ids]
    if not_gaps:
        raise HTTPException(409, f"not gaps of {run.label}: {', '.join(not_gaps)}")
    if not any(s["stack"] == stack for s in bench_stacks(db, run)):
        raise HTTPException(422, "that stack is not ready for programming in this project")
    twins = _take_stack(db, run.project_id, stack, len(devices))
    plan = {"dry_run": dry_run, "units": len(devices), "stack": stack}
    if dry_run:
        return plan
    for tw, d in zip(twins, devices):
        # The run that programmed the board names it, with its deployment
        # version (decision 0074): it is no reflash.
        _name(db, tw, d, run, "merge", "", actor, programming_run=production_pass(db, d.id))
    db.flush()
    plan["caught_up"] = catch_up(db, twins)
    return plan


def _drop_token(key: str, step_key: str) -> str:
    return "|".join(t for t in _tokens(key) if t.split("@", 1)[0] != step_key)


def _one_device(db: Session, run: M.ProductionRun, device_ids, codes) -> M.DeviceUnit:
    devices = _resolve_devices(db, run, device_ids, codes)
    if len(devices) != 1:
        raise HTTPException(422, "name exactly one device")
    return devices[0]


def _home_run(db: Session, tw: M.Twin) -> int:
    """The batch whose pile an unnamed twin lies in: its origin, or for a
    found unit the batch it was entered into."""
    if not tw.found:
        return tw.origin_run_id
    hit = (db.query(M.StepRun.run_id).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
           .filter(M.TwinStep.twin_id == tw.id, M.StepRun.chosen == "found").order_by(M.StepRun.id).first())
    return hit[0] if hit is not None else tw.run_id


def _is_flash_program(db: Session, r: M.ProgrammingRun) -> bool:
    """A programming pass: action `program` with a flash deployment (a run with
    no deployment version is a hand-typed record, not one)."""
    if (r.action or "program") != "program" or not r.deployment_version_id:
        return False
    dv = db.get(M.DeploymentVersion, r.deployment_version_id)
    dep = db.get(M.Deployment, dv.deployment_id) if dv is not None else None
    return dep is not None and (dep.kind or "flash") == "flash"


_RUN_NOTE = re.compile(r"programming run #(\d+)")


def pick_production_pass(passes: list, event=None) -> object | None:
    """Of a device's passing programming runs (oldest first), the one that
    produced it (decision 0074). The bench names it in the `produced` event's
    note ("passed programming run #N"); without that, the latest that started
    at or before the event, else the first of the event's batch, else the
    first. A trial before it, and a reflash after it, are not it. The event
    is stamped with the device's FIRST sighting, which can be a trial's, so
    the note goes first."""
    if not passes:
        return None
    if event is None:
        return passes[0]
    m = _RUN_NOTE.search(event.note or "")
    named = next((r for r in passes if m and r.id == int(m.group(1))), None)
    if named is not None:
        return named
    before = [r for r in passes if r.started_at is not None and event.at is not None and r.started_at <= event.at]
    if before:
        return before[-1]
    mine = [r for r in passes if event.production_run_id and r.production_run_id == event.production_run_id]
    return (mine or passes)[0]


def production_pass(db: Session, device_id: int) -> M.ProgrammingRun | None:
    """The programming run that produced `device_id` (`pick_production_pass`)."""
    passes = [r for r in (db.query(M.ProgrammingRun)
                          .filter(M.ProgrammingRun.device_unit_id == device_id, M.ProgrammingRun.status == "pass",
                                  M.ProgrammingRun.draft_run.is_(False))
                          .order_by(M.ProgrammingRun.started_at, M.ProgrammingRun.id).all())
              if _is_flash_program(db, r)]
    ev = (db.query(M.DeviceEvent).filter_by(device_id=device_id, kind="produced")
          .order_by(M.DeviceEvent.at).first())
    return pick_production_pass(passes, ev)


def swap_twin(db: Session, run: M.ProductionRun, *, device_ids: list[int] | None = None,
              codes: list[str] | None = None, stack: str = "", actor: str = "", dry_run: bool = True) -> dict:
    """The bench named the device from the wrong pile (decision 0074): the
    device takes a twin of `stack`, and its old twin goes back to its own
    stack, unnamed. The programming click moves with the device, draws
    included. Refused while the old twin has a step recorded after it was
    named — undo those first, or they would follow the wrong board. The
    board's own assembly stays with the board."""
    graph = P._graph(crafted_version(db, run))
    _refuse_closed(run)
    prog = P.step_of_kind(graph, "program") or {"key": "program"}
    d = _one_device(db, run, device_ids, codes)
    old = db.query(M.Twin).filter_by(device_unit_id=d.id).first()
    if old is None:
        raise HTTPException(409, f"{d.serial or d.mac} has no twin — merge it instead")
    if old.run_id != run.id or old.status != "active":
        raise HTTPException(409, f"{d.serial or d.mac} is {old.status} in batch {old.run_id}, not active here")
    if not any(s["stack"] == stack for s in bench_stacks(db, run)):
        raise HTTPException(422, "that stack is not ready for programming in this project")
    links = (db.query(M.TwinStep, M.StepRun).join(M.StepRun, M.StepRun.id == M.TwinStep.step_run_id)
             .filter(M.TwinStep.twin_id == old.id).order_by(M.TwinStep.id).all())
    named = [ts for ts, sr in links if sr.kind == "program"]
    if not named:
        raise HTTPException(409, f"{d.serial or d.mac} has no programming step to move — it was entered "
                                 "as found without programming")
    later = [sr.step_label or sr.step_key for ts, sr in links
             if ts.id > named[0].id and sr.kind not in ("program", "assembly")]
    new = _take_stack(db, run.project_id, stack, 1)[0]
    home = _home_run(db, old)
    plan = {"dry_run": dry_run, "device": d.serial or d.mac, "from_twin": old.id, "to_twin": new.id,
            "back_to_stack": stack_id(home, _drop_token(old.stack_key, prog["key"])), "later_steps": later}
    if later:
        raise HTTPException(409, {"error": f"{d.serial or d.mac} has steps after it was named: {', '.join(later)} "
                                           "— undo them first", "plan": plan})
    if dry_run:
        return plan
    named_at = old.named_at or utcnow()
    # Release the device first: one device names one twin, and the database
    # checks that row by row.
    old.device_unit_id, old.named_at = None, None
    old.stack_key = _drop_token(old.stack_key, prog["key"])
    old.run_id = home
    db.flush()
    new.device_unit_id, new.run_id, new.named_at = d.id, run.id, named_at
    new.stack_key = _add_token(new.stack_key, prog["key"])
    for ts in named:
        ts.twin_id = new.id
    db.flush()
    return plan


def relink_run(db: Session, run: M.ProductionRun, *, programming_run_id: int,
               device_ids: list[int] | None = None, codes: list[str] | None = None,
               dry_run: bool = True) -> dict:
    """A bench run was filed against the wrong device (decision 0074): it moves
    to the right one, with the steps it recorded. A run that NAMED a twin is
    that twin's identity — use "swap twin" for it."""
    pr = db.get(M.ProgrammingRun, int(programming_run_id))
    if pr is None:
        raise HTTPException(404, "no such programming run")
    _refuse_closed(run)
    d = _one_device(db, run, device_ids, codes)
    if pr.device_unit_id == d.id:
        raise HTTPException(422, "the run is already on that device")
    old_dev = db.get(M.DeviceUnit, pr.device_unit_id) if pr.device_unit_id else None
    links = (db.query(M.TwinStep, M.StepRun).join(M.StepRun, M.StepRun.id == M.TwinStep.step_run_id)
             .filter(M.TwinStep.programming_run_id == pr.id).order_by(M.TwinStep.id).all())
    batch = db.get(M.ProductionRun, pr.production_run_id) if pr.production_run_id else None
    dv = db.get(M.DeploymentVersion, pr.deployment_version_id) if pr.deployment_version_id else None
    dep = db.get(M.Deployment, dv.deployment_id) if dv is not None else None
    owners = {x.project_id for x in (batch, dep, old_dev) if x is not None} | {sr.project_id for _ts, sr in links}
    if owners - {run.project_id}:
        raise HTTPException(409, "that bench run belongs to another project")
    made = production_pass(db, old_dev.id) if old_dev is not None else None
    if made is not None and made.id == pr.id and any(e.kind == "produced" for e in old_dev.events):
        # A passing programming run is its device's production record: moving
        # it would leave a device with no run behind its "produced".
        raise HTTPException(409, "this is the run that programmed its device — use merge or \"swap twin\"")
    if any(sr.kind == "program" for _ts, sr in links):
        raise HTTPException(409, "this run named its twin — use \"swap twin\" to move the device to the right board")
    for ts, _sr in links:
        src = db.get(M.Twin, ts.twin_id)
        src_run = db.get(M.ProductionRun, src.run_id) if src is not None else None
        if src is None or src.status != "active" or (src_run is not None and src_run.closed_at is not None):
            what = (old_dev.serial or old_dev.mac) if old_dev is not None else f"twin {ts.twin_id}"
            raise HTTPException(409, f"{what} is {src.status if src else 'gone'}"
                                     f"{' in a closed batch' if src_run is not None and src_run.closed_at else ''}"
                                     " — reopen it first, so the steps it loses are asked for again")
    new = db.query(M.Twin).filter_by(device_unit_id=d.id).first()
    if links and (new is None or new.run_id != run.id or new.status != "active"):
        raise HTTPException(409, f"{d.serial or d.mac} has no active twin in {run.label} to take the steps")
    graph = P._graph(crafted_version(db, run))
    smap = P.step_map(graph)
    have = done_steps(db, [new.id])[new.id] if new is not None else set()
    again = since_reopen(db, [new.id]).get(new.id) if new is not None else None
    refused, moving = [], set(have)
    for _ts, sr in links:
        step = smap.get(sr.step_key)
        why = ([f"no step {sr.step_key!r} in {run.label}'s process"] if step is None
               else needs_met(graph, step, moving, again))
        if why:
            refused.append({"step": sr.step_label or sr.step_key, "why": why})
        moving.add(sr.step_key)
        if again is not None:
            again = again | {sr.step_key}
    plan = {"dry_run": dry_run, "programming_run_id": pr.id,
            "from_device": (old_dev.serial or old_dev.mac) if old_dev else None, "to_device": d.serial or d.mac,
            "steps": sorted(sr.step_label or sr.step_key for _ts, sr in links), "refused": refused}
    if refused:
        raise HTTPException(409, {"error": f"{d.serial or d.mac} cannot take these steps: "
                                           + "; ".join(f"{r['step']} — {', '.join(r['why'])}" for r in refused),
                                  "plan": plan})
    if dry_run:
        return plan
    pr.device_unit_id = d.id
    for ts, sr in links:
        old = db.get(M.Twin, ts.twin_id)
        ts.twin_id = new.id
        db.flush()
        if sr.step_key not in done_steps(db, [old.id])[old.id]:
            old.stack_key = _drop_token(old.stack_key, sr.step_key)
        new.stack_key = _add_token(new.stack_key, sr.step_key)
    db.flush()
    return plan


def _draw_or_note(db: Session, run: M.ProductionRun, sr: M.StepRun, step: dict, factor: float) -> None:
    """Draw what a bench-recorded step adds — a label for the label step, an
    input of the program step — `factor` times per unit (the copies a label run
    printed). The bench is never blocked (decision 0037): when the pool cannot
    give the parts, the step stays recorded, because it happened, and its note
    names what was not drawn."""
    if not step.get("inputs"):
        return
    draws, problems, _tok = _plan_draws(db, run, step, sr.qty * max(factor, 1), sr.made_at, None)
    short = run_actuals.check_shortages(db, [
        {"component_id": d["component_id"], "mpn": d.get("mpn", ""), "lcsc": "", "qty": d["qty"],
         "date": sr.made_at, "label": d["name"]} for d in draws if not d["internal"]],
        company_id=run_actuals.run_scope(db, run))
    if problems or short:
        what = "; ".join(sorted({(x.get("label") or x.get("name") or "?")
                                 + (f" ({x['problem']})" if x.get("problem") else " (not in stock)")
                                 for x in (short or problems)}))
        sr.note = f"{sr.note} — not drawn: {what}"[:500]
        return
    write_draws(db, run, sr, draws, f"{sr.step_label} x {sr.qty} (bench, click #{sr.id})")


def _bench_step(db: Session, run: M.ProductionRun, v: M.ProcessVersion, step: dict, tw: M.Twin,
                note: str, *, actor: str = "", factor: float = 1, made_at: str = "",
                programming_run_id: int | None = None, deployment_version_id: int | None = None) -> M.StepRun:
    """A bench recorded `step` on one twin: one click, and what the step adds
    drawn from the pool (decision 0061). The bench run and its deployment
    version go on the twin's step (decision 0074)."""
    sr = _new_run(db, run, v, step, 1, "bench", made_at, actor, note)
    _link(db, [tw], sr, programming_run_id=programming_run_id, deployment_version_id=deployment_version_id)
    tw.stack_key = _add_token(tw.stack_key, step["key"])
    _draw_or_note(db, run, sr, step, factor)
    return sr


def _twin_process(db: Session, device: M.DeviceUnit):
    tw = db.query(M.Twin).filter_by(device_unit_id=device.id).first()
    if tw is None or tw.status != "active":
        return None, None, None
    run = db.get(M.ProductionRun, tw.run_id)
    v = db.get(M.ProcessVersion, run.process_version_id) if run and run.process_version_id else None
    return tw, run, v


def record_marking(db: Session, device: M.DeviceUnit, *, laser: bool, label: bool,
                   deployment_id: int | None = None, actor: str = "", copies: int = 1,
                   made_at: str = "", note: str = "", programming_run_id: int | None = None,
                   deployment_version_id: int | None = None) -> list[str]:
    """The marking bench engraved or labelled `device`: record the matching
    steps on its twin, where its process has them and their needs are met, and
    draw what they add (one label per copy printed).

    The step is the one that names the run's deployment, else one that names
    none (decision 0060); a step that names another deployment is not done by
    this run."""
    tw, run, v = _twin_process(db, device)
    if v is None:
        return []
    graph = P._graph(v)
    out = []
    for kind, did in (("mark_laser", laser), ("label", label)):
        step = P.step_for_deployment(graph, kind, deployment_id)
        if not did or step is None:
            continue
        if needs_met(graph, step, done_steps(db, [tw.id])[tw.id], since_reopen(db, [tw.id]).get(tw.id)):
            continue
        _bench_step(db, run, v, step, tw, note or f"{device.serial or device.mac}", actor=actor,
                    factor=copies if kind == "label" else 1, made_at=made_at,
                    programming_run_id=programming_run_id, deployment_version_id=deployment_version_id)
        out.append(step["key"])
    db.flush()
    return out


def record_test(db: Session, device: M.DeviceUnit, *, deployment_id: int | None = None,
                actor: str = "", made_at: str = "", note: str = "", programming_run_id: int | None = None,
                deployment_version_id: int | None = None) -> list[str]:
    """A test procedure passed on `device`: record the process's test step on
    its twin, where its needs are met (decision 0061). The step is the one that
    names the run's deployment, else one that names none."""
    tw, run, v = _twin_process(db, device)
    if v is None:
        return []
    graph = P._graph(v)
    step = P.step_for_deployment(graph, "test", deployment_id)
    if step is None or needs_met(graph, step, done_steps(db, [tw.id])[tw.id], since_reopen(db, [tw.id]).get(tw.id)):
        return []
    _bench_step(db, run, v, step, tw, note or f"{device.serial or device.mac}: test passed",
                actor=actor, made_at=made_at, programming_run_id=programming_run_id,
                deployment_version_id=deployment_version_id)
    db.flush()
    return [step["key"]]


def catch_up(db: Session, twins: list[M.Twin]) -> list[dict]:
    """Record the bench steps a device did before their needs were met.

    The marking bench marks a unit whatever its state, and records the step
    only when its needs are met (a laser mark needs the enclosure). Once a
    later step meets them, the bench's own run is the evidence: a marking run
    whose results say `marked` or `printed`, or a passing test run. Nothing is
    recorded without such a run."""
    out = []
    for tw in twins:
        if not tw.device_unit_id or tw.status != "active":
            continue
        runs = (db.query(M.ProgrammingRun)
                .filter(M.ProgrammingRun.device_unit_id == tw.device_unit_id,
                        M.ProgrammingRun.draft_run.is_(False))
                .order_by(M.ProgrammingRun.id).all())
        device = db.get(M.DeviceUnit, tw.device_unit_id)
        # A run from before the twin's latest reopen is no evidence of the
        # work done since (decision 0074).
        # One run can record a step now and another later (a label now, the
        # laser once the enclosure is on), so a run behind one step stays a
        # source; "already done" stops it recording a step twice.
        reopened = (db.query(func.max(M.StepRun.created_at)).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
                    .filter(M.TwinStep.twin_id == tw.id, M.StepRun.kind == "reopen").scalar())
        runs = [r for r in runs if not (reopened and r.started_at and r.started_at < reopened)]
        for r in runs:
            res = r.results or {}
            dv = db.get(M.DeploymentVersion, r.deployment_version_id) if r.deployment_version_id else None
            dep = db.get(M.Deployment, dv.deployment_id) if dv is not None else None
            when = r.started_at.date().isoformat() if r.started_at else ""
            why = f"{device.serial or device.mac}: recorded later from bench run #{r.id}"
            got: list[str] = []
            if res.get("marked") or res.get("printed"):
                got += record_marking(db, device, laser=bool(res.get("marked")), label=bool(res.get("printed")),
                                      deployment_id=dep.id if dep else None, actor=r.operator or "",
                                      copies=int(res.get("label_copies") or 1), made_at=when, note=why,
                                      programming_run_id=r.id, deployment_version_id=r.deployment_version_id)
            if r.status == "pass" and dep is not None and (dep.kind or "") == "test":
                got += record_test(db, device, deployment_id=dep.id, actor=r.operator or "",
                                   made_at=when, note=why, programming_run_id=r.id,
                                   deployment_version_id=r.deployment_version_id)
            if got:
                out.append({"device_id": device.id, "run_id": r.id, "steps": got})
    return out


def refuse_rebatch(db: Session, device: M.DeviceUnit, to_run: M.ProductionRun) -> str | None:
    """Why `device` cannot follow a rebatch into `to_run`, or None. A device
    with a twin needs a batch with a process: elsewhere it could never be
    finished, and an unfinished device never ships (0059 §9)."""
    tw = db.query(M.Twin).filter_by(device_unit_id=device.id).first()
    if tw is not None and not to_run.process_version_id:
        return (f"{device.serial or device.mac} has a twin and {to_run.label} has no process — "
                "rebuild that batch into twins first")
    if tw is not None:
        # Its origin and its rebuilt steps come from the records of the batch
        # it was rebuilt in (decision 0075): moving it would leave both behind.
        hit = (db.query(M.StepRun.run_id).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
               .filter(M.TwinStep.twin_id == tw.id, M.StepRun.chosen == "rebuilt").first())
        if hit is not None:
            src = db.get(M.ProductionRun, hit[0])
            return (f"{device.serial or device.mac}'s twin was rebuilt from the records of "
                    f"{src.label if src else hit[0]} — undo that rebuild, rebatch, then rebuild "
                    "(name the batch of its boards in origins)")
    return None


def follow_rebatch(db: Session, device: M.DeviceUnit, to_run_id: int) -> None:
    """A rebatched device's twin is in the batch that built it (decision 0029).
    Its origin batch never moves."""
    tw = db.query(M.Twin).filter_by(device_unit_id=device.id).first()
    if tw is not None:
        tw.run_id = to_run_id


def refuse_unfinished(db: Session, device: M.DeviceUnit) -> None:
    """Only a finished device ships (0059 §9). A device with no twin ships as
    before only when its batch is not crafted: in a crafted batch it is a gap
    (decision 0074), the board behind it is still an unnamed twin, and a merge
    must name it first."""
    tw = db.query(M.Twin).filter_by(device_unit_id=device.id).first()
    if tw is None:
        run = db.get(M.ProductionRun, device.production_run_id) if device.production_run_id else None
        if run is not None and run.process_version_id:
            raise HTTPException(409, {
                "error": f"device {device.serial or device.id} is a gap of {run.label}: it was programmed "
                         "with no twin behind it — merge it on the batch's process screen first",
                "device_id": device.id, "status": "gap"})
        return
    if tw.status != "finished":
        raise HTTPException(409, {
            "error": f"device {device.serial or device.id} is not finished — mark it finished on "
                     "its batch's process screen first",
            "device_id": device.id, "status": tw.status})


# ==================================================================== prices

def _step_draw_values(db: Session, run_ids: list[int] | None = None) -> tuple[dict, dict]:
    """(value per step click, value of step draws per batch) — live draws only."""
    q = (db.query(M.ComponentConsumption.step_run_id, M.ComponentConsumption.run_id,
                  func.sum(M.ComponentConsumption.qty * M.ComponentConsumption.unit_cost_usd))
         .filter(M.ComponentConsumption.step_run_id.isnot(None),
                 M.ComponentConsumption.voided_at.is_(None)))
    if run_ids is not None:
        q = q.filter(M.ComponentConsumption.run_id.in_(run_ids or [-1]))
    by_click: dict[int, float] = defaultdict(float)
    by_run: dict[int, float] = defaultdict(float)
    for srid, rid, v in q.group_by(M.ComponentConsumption.step_run_id,
                                   M.ComponentConsumption.run_id).all():
        by_click[srid] += float(v or 0)
        by_run[rid] += float(v or 0)
    return by_click, by_run


def line_shares(db: Session, run_ids: list[int] | None = None) -> list[dict]:
    """Every invoice position linked to step clicks, with the twins that carry
    it (decisions 0060, 0061): the twins of all its clicks, each carrying an
    equal share. Valued by `run_actuals.leaf_line_usd`, as the register values
    it.

    A link counts only while the position is charged to the batch of its
    clicks. A position re-charged elsewhere since keeps its money where the
    register now puts it, and `unlinked` shows it again."""
    links = db.query(M.CostLineStep.line_id, M.CostLineStep.step_run_id).all()
    if not links:
        return []
    clicks_of: dict[int, set[int]] = defaultdict(set)
    for lid, srid in links:
        clicks_of[lid].add(srid)
    click_run: dict[int, int] = {}
    click_label: dict[int, str] = {}
    for sr_id, rid, lab in (db.query(M.StepRun.id, M.StepRun.run_id, M.StepRun.step_label)
                            .filter(M.StepRun.id.in_({srid for _l, srid in links})).all()):
        click_run[sr_id] = rid
        click_label[sr_id] = lab
    # A header's links are the source for a later split, not money: its
    # children carry it (decision 0074).
    hdrs = run_actuals.header_ids(db)
    lines = (db.query(M.RunCostLine)
             .filter(M.RunCostLine.id.in_(list(set(clicks_of) - hdrs)), M.RunCostLine.voided_at.is_(None)).all())
    vals = run_actuals.leaf_line_usd(db, lines)
    keep = []
    for li in lines:
        usd, dest, ref = vals[li.id]
        runs = {click_run.get(c) for c in clicks_of[li.id]}
        if dest != "run" or runs != {ref} or (run_ids is not None and ref not in run_ids):
            continue
        keep.append((li, usd, ref))
    if not keep:
        return []
    want = {c for li, _u, _r in keep for c in clicks_of[li.id]}
    twins_of: dict[int, set[int]] = defaultdict(set)
    for tid, srid in (db.query(M.TwinStep.twin_id, M.TwinStep.step_run_id)
                      .filter(M.TwinStep.step_run_id.in_(want)).all()):
        twins_of[srid].add(tid)
    out = []
    for li, usd, rid in keep:
        clicks = sorted(clicks_of[li.id])
        twins = set().union(*(twins_of[c] for c in clicks))
        out.append({"line": li, "usd": usd, "run_id": rid, "clicks": clicks, "twins": twins,
                    "click_twins": {c: twins_of[c] for c in clicks},
                    "steps": sorted({click_label.get(c) or "" for c in clicks})})
    return out


def _by_run(shares: list[dict]) -> dict[int, float]:
    out: dict[int, float] = defaultdict(float)
    for sh in shares:
        if sh["twins"]:
            out[sh["run_id"]] += sh["usd"]
    return out


def _own(db: Session, twin_ids: list[int], by_click: dict[int, float]) -> dict[int, float]:
    """Each twin's 1/N of every click value in `by_click` it took part in."""
    if not twin_ids or not by_click:
        return {}
    links = (db.query(M.TwinStep.twin_id, M.TwinStep.step_run_id)
             .filter(M.TwinStep.twin_id.in_(twin_ids)).all())
    qty = {sr.id: sr.qty for sr in db.query(M.StepRun).filter(
        M.StepRun.id.in_({srid for _t, srid in links if srid in by_click} or {-1})).all()}
    out: dict[int, float] = defaultdict(float)
    for tid, srid in links:
        if qty.get(srid):
            out[tid] += by_click.get(srid, 0.0) / qty[srid]
    return dict(out)


def own_parts(db: Session, twin_ids: list[int]) -> dict[int, float]:
    """Each twin's own parts: 1/N of the draws of every click it took part in."""
    return _own(db, twin_ids, _step_draw_values(db)[0])


def own_step_costs(db: Session, twin_ids: list[int], shares: list[dict] | None = None
                   ) -> dict[int, float]:
    """Each twin's own step costs: an equal share of every position that paid
    for a click it took part in."""
    want = set(twin_ids)
    out: dict[int, float] = defaultdict(float)
    for sh in (line_shares(db) if shares is None else shares):
        n = len(sh["twins"])
        for tid in sh["twins"] & want:
            out[tid] += sh["usd"] / n
    return dict(out)


def origin_shares(db: Session, origin_run_ids: list[int], register: dict | None = None,
                  shares: list[dict] | None = None) -> dict[int, dict]:
    """Per origin batch: its origin batch cost, the scrapped twins' own costs it
    carries, how many twins share it, and the share per twin (0059 §11, §13).

    The origin batch cost is the batch's total (`invoice_register.by_run_usd`,
    the figure `per_device_cost_usd` divides today) minus every step draw and
    every step-linked position charged to it — those belong to particular
    twins (decisions 0060, 0061). A closed batch answers its frozen share."""
    if not origin_run_ids:
        return {}
    runs = {r.id: r for r in db.query(M.ProductionRun)
            .filter(M.ProductionRun.id.in_(origin_run_ids)).all()}
    # Always the register: a closed batch answers its frozen share, but its
    # origin batch cost is still reported, and is wrong without the total.
    reg = register or run_actuals.invoice_register(db)
    by_run_usd = reg.get("by_run_usd") or {}
    _, step_by_run = _step_draw_values(db, list(runs))
    shares = line_shares(db) if shares is None else shares
    lines_by_run = _by_run(shares)
    out: dict[int, dict] = {}
    for rid, r in runs.items():
        twins = (db.query(M.Twin).filter(M.Twin.origin_run_id == rid, M.Twin.found.is_(False)).all())
        alive = [tw for tw in twins if tw.status != "scrapped"]
        scrapped = [tw for tw in twins if tw.status == "scrapped"]
        # A scrapped FOUND unit entered at zero, but what this batch drew for
        # it was charged here: the good units carry that too.
        found_scrapped = (db.query(M.Twin).filter(M.Twin.run_id == rid, M.Twin.found.is_(True),
                                                  M.Twin.status == "scrapped").all())
        carried = 0.0
        if scrapped or found_scrapped:
            ids = [tw.id for tw in scrapped + found_scrapped]
            carried = sum(own_parts(db, ids).values()) + sum(own_step_costs(db, ids, shares).values())
        total = float((by_run_usd.get(str(rid)) or {}).get("total_usd") or 0.0)
        origin = total - step_by_run.get(rid, 0.0) - lines_by_run.get(rid, 0.0)
        share = (r.closed_twin_share_usd if r.closed_twin_share_usd is not None
                 else ((origin + carried) / len(alive) if alive else None))
        # No twin of its own alive (its units came from another batch, or all
        # broke): the money is carried by no device, and says so (0074).
        uncarried = origin + carried if not alive and r.closed_twin_share_usd is None else 0.0
        out[rid] = {"origin_cost_usd": round(origin, 4), "scrap_carried_usd": round(carried, 4),
                    "uncarried_usd": round(uncarried, 4),
                    "step_costs_usd": round(lines_by_run.get(rid, 0.0), 4),
                    "twins": len(alive), "scrapped": len(scrapped),
                    "share_usd": round(share, 6) if share is not None else None,
                    "frozen": r.closed_twin_share_usd is not None}
    return out


def prices(db: Session, twins: list[M.Twin], register: dict | None = None) -> dict[int, dict]:
    """Each twin's price: its own parts and step costs plus its origin share
    (zero for a found unit)."""
    ids = [tw.id for tw in twins]
    shares = line_shares(db)
    own = own_parts(db, ids)
    fees = own_step_costs(db, ids, shares)
    origin = origin_shares(db, sorted({tw.origin_run_id for tw in twins if not tw.found}), register, shares)
    out = {}
    for tw in twins:
        share = 0.0 if tw.found else ((origin.get(tw.origin_run_id) or {}).get("share_usd") or 0.0)
        o, f = own.get(tw.id, 0.0), fees.get(tw.id, 0.0)
        out[tw.id] = {"own_parts_usd": round(o, 4), "step_costs_usd": round(f, 4),
                      "origin_share_usd": round(share, 4),
                      "total_usd": round(o + f + share, 4)}
    return out


def click_costs(shares: list[dict]) -> dict[int, float]:
    """A position's money spread over its clicks by their units, so a column of
    clicks adds up to what the positions cost. A display figure: the price of a
    twin does not depend on it."""
    out: dict[int, float] = defaultdict(float)
    for sh in shares:
        n = sum(len(t) for t in sh["click_twins"].values())
        for c, t in sh["click_twins"].items():
            if n:
                out[c] += sh["usd"] * len(t) / n
    return out


def device_costs(db: Session, register: dict | None = None) -> dict[int, float]:
    """Cost of every NAMED twin's device: what orders charge for it (0059 §13)."""
    twins = db.query(M.Twin).filter(M.Twin.device_unit_id.isnot(None)).all()
    if not twins:
        return {}
    pr = prices(db, twins, register)
    # A scrapped twin's money is already inside the shares of its batch's good
    # units (0059 §11). Charging its device as well — one that shipped, came
    # back and was disposed — would count it twice.
    return {tw.device_unit_id: (0.0 if tw.status == "scrapped" else pr[tw.id]["total_usd"]) for tw in twins}


def freeze_share(db: Session, run: M.ProductionRun) -> float | None:
    """The share to freeze when `run` closes; None when it has no twins."""
    run.closed_twin_share_usd = None
    s = origin_shares(db, [run.id]).get(run.id) or {}
    return s.get("share_usd") if s.get("twins") else None


# ================================================================= read side

def twin_json(db: Session, tw: M.Twin, price: dict | None = None) -> dict:
    """A twin's history in the words each step had then, and its price."""
    rows = (db.query(M.StepRun).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
            .filter(M.TwinStep.twin_id == tw.id).order_by(M.StepRun.id).all())
    by_click, _ = _step_draw_values(db)
    draws_by_click: dict[int, list[dict]] = defaultdict(list)
    ids = [sr.id for sr in rows]
    if ids:
        names: dict[int, str] = {}
        for c in (db.query(M.ComponentConsumption)
                  .filter(M.ComponentConsumption.step_run_id.in_(ids),
                          M.ComponentConsumption.voided_at.is_(None)).all()):
            if c.component_id not in names:
                names[c.component_id] = ((P._part_names(db, {c.component_id}).get(c.component_id)
                                          or {}).get("name") if c.component_id else None) \
                    or c.mpn or str(c.component_id)
            lot = (db.query(M.ComponentConsumptionLot.lot_adjustment_id)
                   .filter_by(consumption_id=c.id).first())
            sr = next(s for s in rows if s.id == c.step_run_id)
            draws_by_click[c.step_run_id].append({
                "component_id": c.component_id,
                "name": names[c.component_id] if c.component_id else (c.mpn or "?"),
                "qty": round((c.qty or 0) / (sr.qty or 1), 6),
                "unit_cost_usd": c.unit_cost_usd,
                "lot": f"A{lot[0]}" if lot and lot[0] else None})
    # The positions that paid for this twin's clicks. A position shared by
    # several clicks shows on each, its per-twin share split evenly over the
    # ones this twin took part in, so the steps add up to the twin's price.
    costs_by_click: dict[int, list[dict]] = defaultdict(list)
    mine = set(ids)
    for sh in line_shares(db):
        if tw.id not in sh["twins"]:
            continue
        took = [c for c in sh["clicks"] if c in mine and tw.id in sh["click_twins"][c]]
        if not took:
            continue
        li = sh["line"]
        doc = db.get(M.RunCostDocument, li.document_id)
        per = sh["usd"] / len(sh["twins"]) / len(took)
        others = sh["steps"]
        for c in took:
            costs_by_click[c].append({
                "line_id": li.id, "label": li.label, "plan_key": li.plan_key,
                "step_name": cost_steps.STEPS.get(li.plan_key, (li.plan_key or "", ""))[0],
                "supplier": doc.supplier if doc else "", "doc_number": doc.doc_number if doc else "",
                "shared_by": others if len(others) > 1 else [],
                "usd": round(per, 6)})
    runs = {r.id: r.label for r in db.query(M.ProductionRun)
            .filter(M.ProductionRun.id.in_({tw.origin_run_id, tw.run_id} | {s.run_id for s in rows})).all()}
    price = price or prices(db, [tw])[tw.id]
    order = {"assembly": 0, "receive": 1}
    # Decision 0074: which bench run did each step on this unit, under which
    # deployment version; and every later programming pass (a reflash).
    links = {ts.step_run_id: ts for ts in db.query(M.TwinStep).filter_by(twin_id=tw.id).all()}
    dv_ids = {ts.deployment_version_id for ts in links.values() if ts.deployment_version_id}
    reflashes: list[dict] = []
    if tw.device_unit_id:
        on_steps = {ts.programming_run_id for ts in links.values() if ts.programming_run_id}
        made = production_pass(db, tw.device_unit_id)
        if made is not None:
            on_steps.add(made.id)
        for r in (db.query(M.ProgrammingRun)
                  .filter(M.ProgrammingRun.device_unit_id == tw.device_unit_id,
                          M.ProgrammingRun.status == "pass", M.ProgrammingRun.draft_run.is_(False))
                  .order_by(M.ProgrammingRun.id).all()):
            # A reflash comes after the run that produced the device; a trial
            # before it is no reflash (decision 0074).
            if (_is_flash_program(db, r) and r.id not in on_steps
                    and not (made is not None and made.started_at and r.started_at
                             and r.started_at <= made.started_at)):
                reflashes.append({"programming_run_id": r.id, "deployment_version_id": r.deployment_version_id,
                                  "at": r.started_at.isoformat() if r.started_at else None})
                if r.deployment_version_id:
                    dv_ids.add(r.deployment_version_id)
    dv_label = {}
    for dv in (db.query(M.DeploymentVersion).filter(M.DeploymentVersion.id.in_(dv_ids)).all() if dv_ids else []):
        dep = db.get(M.Deployment, dv.deployment_id)
        dv_label[dv.id] = f"{dep.name if dep else 'deployment'} v{dv.version_no}"
    for x in reflashes:
        x["deployment_version"] = dv_label.get(x["deployment_version_id"])
    return {
        "origin_run_id": tw.origin_run_id, "origin_run": runs.get(tw.origin_run_id),
        "run_id": tw.run_id, "run": runs.get(tw.run_id), "status": tw.status,
        "found": tw.found, "note": tw.note,
        "named_at": tw.named_at.isoformat() if tw.named_at else None,
        "finished_at": tw.finished_at.isoformat() if tw.finished_at else None,
        "price": price,
        "steps": [{"step": sr.step_key, "label": sr.step_label, "kind": sr.kind,
                   "process_version_id": sr.process_version_id, "batch": runs.get(sr.run_id),
                   "chosen": sr.chosen, "made_at": sr.made_at, "actor": sr.actor, "note": sr.note,
                   "parts": draws_by_click.get(sr.id, []),
                   "parts_usd": round(by_click.get(sr.id, 0.0) / (sr.qty or 1), 4),
                   "costs": sorted(costs_by_click.get(sr.id, []), key=lambda c: c["line_id"]),
                   "costs_usd": round(sum(c["usd"] for c in costs_by_click.get(sr.id, [])), 4),
                   "programming_run_id": links[sr.id].programming_run_id if sr.id in links else None,
                   "deployment_version_id": links[sr.id].deployment_version_id if sr.id in links else None,
                   "deployment_version": (dv_label.get(links[sr.id].deployment_version_id)
                                          if sr.id in links else None)}
                  for sr in sorted(rows, key=lambda r: (order.get(r.kind, 2), r.id))],
        "reflashes": reflashes,
        "fitted": fitted(db, tw.origin_run_id),
    }


def fitted(db: Session, origin_run_id: int) -> list[dict]:
    """What the supplier fitted on the boards of a batch, from ITS OWN BOM of the
    assembly order (`jlc_imports.bom_info`): each position, its part, and who
    supplied it — our stock at the supplier, the supplier itself, or both.

    JLC keeps the board's original reference numbering, which can differ from
    the schematic (`services/substitutions.py`), so the designators are the
    supplier's. Empty when the batch has no assembly order with a fetched BOM."""
    from . import supplier_parts

    run = db.get(M.ProductionRun, origin_run_id)
    if run is None:
        return []
    src = {supplier_parts.SOURCE_POOL: "our stock", supplier_parts.SOURCE_SUPPLIER: "supplier",
           supplier_parts.SOURCE_BOTH: "both"}
    out: list[dict] = []
    for code in assembly_orders(db, run):
        for b in supplier_parts.bom_for_order(db, code) or []:
            refs = [r for r in str(b.get("designator") or "").replace(";", ",").split(",") if r.strip()]
            out.append({"order": code, "designator": ",".join(r.strip() for r in refs),
                        "per_board": len(refs),
                        "lcsc": str(b.get("componentCode") or "").strip(),
                        "mpn": str(b.get("componentModelEn") or b.get("componentModel") or "").strip(),
                        "source": src.get(str(b.get("componentSource") or ""), "unknown")})
    return out


def craft_view(db: Session, run: M.ProductionRun) -> dict:
    """Everything the batch's crafting screen draws."""
    v = crafted_version(db, run)
    graph = P._graph(v)
    smap = P.step_map(graph)
    order = {k: i for i, k in enumerate(graph["route"])}

    def in_route_order(keys) -> list[str]:
        return sorted(keys, key=lambda k: (order.get(k, len(order)), k))

    st = stacks(db, run.project_id, run_id=run.id)
    for s in st:
        s["done"] = in_route_order(s["done"])
        # what the route offers next, wherever it is done (a bench step too)
        s["next"] = [k for k in graph["route"] if k in smap and smap[k].get("kind") not in ("receive", "assembly")
                     and not needs_met(graph, smap[k], set(s["done"]))][:2]
        s["can"] = [k for k, sp in smap.items() if sp.get("kind") == "step"
                    and not needs_met(graph, sp, set(s["done"]))]
    named = (db.query(M.Twin).filter(M.Twin.run_id == run.id, M.Twin.device_unit_id.isnot(None))
             .order_by(M.Twin.id).all())
    done = done_steps(db, [tw.id for tw in named])
    again = since_reopen(db, [tw.id for tw in named])
    pr = prices(db, named) if named else {}
    devs = {d.id: d for d in db.query(M.DeviceUnit)
            .filter(M.DeviceUnit.id.in_([tw.device_unit_id for tw in named] or [-1])).all()}
    devices = []
    for tw in named:
        d = devs.get(tw.device_unit_id)
        devices.append({"device_id": tw.device_unit_id, "serial": d.serial if d else None,
                        "mac": d.mac if d else None, "status": tw.status,
                        "origin_run_id": tw.origin_run_id, "done": in_route_order(done[tw.id]),
                        "missing": needs_met(graph, P.step_of_kind(graph, "finish") or {}, done[tw.id], again.get(tw.id))
                        if tw.status == "active" else [],
                        "price_usd": pr.get(tw.id, {}).get("total_usd")})
    counts = defaultdict(int)
    for tw in db.query(M.Twin).filter(M.Twin.origin_run_id == run.id).all():
        counts[tw.status] += 1
    share = origin_shares(db, [run.id]).get(run.id)
    line_click = click_costs(line_shares(db, [run.id]))
    draw_click, _ = _step_draw_values(db, [run.id])
    recent = (db.query(M.StepRun).filter_by(run_id=run.id)
              .order_by(M.StepRun.id.desc()).limit(200).all())
    undo = click_batches(db, run, [sr.id for sr in recent])
    return {
        "run_id": run.id, "process_version_id": v.id, "version_no": v.version_no,
        "graph": graph, "parts": {str(k): p for k, p in P._part_names(db, {
            c for s in graph["steps"] for c, _m in map(P.input_ref, s.get("inputs") or []) if c}).items()},
        "stacks": st, "devices": devices,
        "gaps": [{"device_id": d.id, "serial": d.serial, "mac": d.mac} for d in gaps(db, run)],
        "bench_stack": run.bench_stack or None, "bench_left": bench_stack_left(db, run),
        "bench_stacks": bench_stacks(db, run),
        "origin": {**(share or {}), "received": counts["active"] + counts["finished"] + counts["scrapped"],
                   "finished": counts["finished"]},
        "clicks": [{"id": sr.id, "step": sr.step_key, "label": sr.step_label, "kind": sr.kind,
                    "qty": sr.qty, "chosen": sr.chosen, "made_at": sr.made_at, "actor": sr.actor,
                    "note": sr.note, "costs_usd": round(line_click.get(sr.id, 0.0), 4),
                    "parts_usd": round(draw_click.get(sr.id, 0.0), 4), "batch_id": undo.get(sr.id)}
                   for sr in recent],
        "assembly": _assembly_view(db, run),
        "unlinked": unlinked(db, run),
        "linked": linked_positions(db, run),
    }


def click_batches(db: Session, run: M.ProductionRun, click_ids: list[int]) -> dict[int, int]:
    """The journal batch that wrote each click, while it can still be undone
    (decision 0074). A bench click and a click from before the journal have
    none; neither has a click of a closed batch."""
    if run.closed_at is not None or not click_ids:
        return {}
    # A rebuild is one batch for all its clicks: it is undone whole, by
    # "Undo rebuild" (decision 0075), never from one of its clicks.
    return {rid: bid for rid, bid in (
        db.query(M.WriteBatchRow.row_id, M.WriteBatch.id)
        .join(M.WriteBatch, M.WriteBatch.id == M.WriteBatchRow.batch_id)
        .filter(M.WriteBatchRow.table_name == "step_runs", M.WriteBatchRow.op == "insert",
                M.WriteBatchRow.row_id.in_(click_ids), M.WriteBatch.reversed_at.is_(None),
                M.WriteBatch.kind != "craft.rebuild").all())}


def linked_positions(db: Session, run: M.ProductionRun) -> list[dict]:
    """The positions linked to this batch's steps, for the "Unlink…" control
    (decision 0074). A split one is listed once, by its header, which an
    unlink takes with all its children."""
    hdrs = run_actuals.header_ids(db)
    mine = {li.id for li in charged_lines(db, run)}

    def leaves(line_id: int) -> set[int]:
        out_, frontier = set(), [line_id]
        while frontier:
            x = frontier.pop()
            kids = [k for (k,) in db.query(M.RunCostLine.id).filter(M.RunCostLine.parent_line_id == x,
                                                                    M.RunCostLine.voided_at.is_(None)).all()]
            if kids:
                frontier.extend(kids)
            else:
                out_.add(x)
        return out_

    def top_of(li: M.RunCostLine) -> M.RunCostLine:
        # Up over a header only while every live leaf below it is this
        # batch's: an unlink by that header must not reach another batch's.
        top = li
        while top.parent_line_id and top.parent_line_id in hdrs:
            parent = db.get(M.RunCostLine, top.parent_line_id)
            if parent is None or parent.voided_at is not None or not leaves(parent.id) <= mine:
                break
            top = parent
        return top

    labels = {k: (s.get("label") or k) for k, s in P.step_map(P._graph(crafted_version(db, run))).items()}
    out: dict[int, dict] = {}

    def row_of(top: M.RunCostLine) -> dict:
        return out.setdefault(top.id, {"line_id": top.id, "label": top.label or "", "usd": 0.0, "steps": set(),
                                       "whole_steps": sorted({k for (k,) in db.query(M.CostLineStepKey.step_key)
                                                              .filter_by(line_id=top.id, run_id=run.id).all()})})

    for sh in line_shares(db, [run.id]):
        row = row_of(top_of(sh["line"]))
        row["usd"] += sh["usd"]
        row["steps"] |= set(sh["steps"])
    # A whole-step link that waits for its first click is a link too. A key on
    # a header whose leaves are not all this batch's is listed by its leaves
    # of this batch that hold the same step, which an unlink can reach; by
    # all of them only when none does.
    for lid, key in db.query(M.CostLineStepKey.line_id, M.CostLineStepKey.step_key).filter_by(run_id=run.id).all():
        li = db.get(M.RunCostLine, lid)
        if li is None or li.voided_at is not None:
            continue
        below = leaves(li.id)
        targets = [li.id]
        if not below <= mine:
            ours = below & mine or {-1}
            holds = {x for (x,) in db.query(M.CostLineStepKey.line_id).filter(
                M.CostLineStepKey.line_id.in_(ours), M.CostLineStepKey.run_id == run.id,
                M.CostLineStepKey.step_key == key).all()}
            holds |= {x for (x,) in db.query(M.CostLineStep.line_id).join(
                M.StepRun, M.StepRun.id == M.CostLineStep.step_run_id).filter(
                M.CostLineStep.line_id.in_(ours), M.StepRun.run_id == run.id, M.StepRun.step_key == key).all()}
            targets = sorted(holds or (ours - {-1}))
        for leaf_id in targets:
            row = row_of(top_of(db.get(M.RunCostLine, leaf_id)))
            row["steps"].add(labels.get(key, key))
    return [{**r, "usd": round(r["usd"], 4), "steps": sorted(r["steps"])}
            for r in sorted(out.values(), key=lambda r: r["line_id"])]


def cost_by_step(db: Session, run: M.ProductionRun, register: dict | None = None) -> dict:
    """What the batch cost, step by step (decisions 0060, 0061): for each step
    done in it, the parts its clicks drew and the invoice positions that paid
    for it alone; then one row per invoice that paid for SEVERAL steps at once
    (the final assembler's), never split by a guess; then the origin batch cost
    no step claims. The board and its assembly are the assembly step's figures.

    The rows add up to the batch's total in the register."""
    reg = register or run_actuals.invoice_register(db)
    total = float((reg.get("by_run_usd", {}).get(str(run.id)) or {}).get("total_usd") or 0.0)
    clicks = db.query(M.StepRun).filter_by(run_id=run.id).order_by(M.StepRun.id).all()
    click_of = {c.id: c for c in clicks}
    draw_click, _ = _step_draw_values(db, [run.id])
    order = {"assembly": 0, "receive": 1}
    rows: dict[str, dict] = {}
    for c in clicks:
        if c.chosen == "found":
            continue   # history of units entered at zero, not work this batch paid for
        r = rows.setdefault(c.step_key, {"key": c.step_key, "step": c.step_key, "label": c.step_label,
                                         "kind": c.kind, "units": 0, "parts_usd": 0.0,
                                         "invoices_usd": 0.0, "by_key": defaultdict(float),
                                         "first": c.id, "twins": set()})
        r["units"] += c.qty or 0
        r["parts_usd"] += draw_click.get(c.id, 0.0)
    shared: dict[tuple, dict] = {}
    for sh in line_shares(db, [run.id]):
        keys = sorted({click_of[c].step_key for c in sh["clicks"] if c in click_of
                       and click_of[c].step_key in rows}, key=lambda k: rows[k]["first"])
        if not keys:
            continue
        li = sh["line"]
        if len(keys) == 1:
            r = rows[keys[0]]
            r["invoices_usd"] += sh["usd"]
            r["by_key"][li.plan_key or "—"] += sh["usd"]
            continue
        g = shared.setdefault(tuple(keys), {
            "key": "+".join(keys), "step": "+".join(keys),
            "label": " + ".join(rows[k]["label"] for k in keys) + " (one invoice for these steps)",
            "kind": "shared", "units": 0, "parts_usd": 0.0, "invoices_usd": 0.0,
            "by_key": defaultdict(float), "first": min(rows[k]["first"] for k in keys), "twins": set()})
        g["invoices_usd"] += sh["usd"]
        g["by_key"][li.plan_key or "—"] += sh["usd"]
        g["twins"] |= sh["twins"]
    for g in shared.values():
        g["units"] = len(g["twins"])

    def shape(r: dict) -> dict:
        money = r["parts_usd"] + r["invoices_usd"]
        return {"key": r["key"], "step": r["step"], "label": r["label"], "kind": r["kind"],
                "units": r["units"], "parts_usd": round(r["parts_usd"], 4),
                "invoices_usd": round(r["invoices_usd"], 4), "total_usd": round(money, 4),
                # A step clicked several times (programming, one click a day)
                # counts each unit once per click; per unit is per unit that took it.
                "per_unit_usd": round(money / r["units"], 4) if r["units"] else None,
                "invoices": [{"plan_key": k, "name": cost_steps.STEPS.get(k, (k, ""))[0], "usd": round(v, 4)}
                             for k, v in sorted(r["by_key"].items())]}

    out_rows = [shape(r) for r in sorted(rows.values(), key=lambda r: (order.get(r["kind"], 2), r["first"]))
                if r["parts_usd"] or r["invoices_usd"] or r["kind"] in ("assembly", "receive")]
    out_rows += [shape(g) for g in sorted(shared.values(), key=lambda g: g["first"])]
    share = origin_shares(db, [run.id], reg).get(run.id) or {}
    claimed = sum(r["total_usd"] for r in out_rows)
    free = unlinked(db, run)
    assembly = next((r for r in out_rows if r["kind"] == "assembly"), None)
    return {"run_id": run.id, "total_usd": round(total, 4), "steps": out_rows,
            "origin": {"usd": round(total - claimed, 4), "share_usd": share.get("share_usd"),
                       "twins": share.get("twins"), "lines": free["lines"], "draws": free["draws"]},
            "board_and_assembly_usd": assembly["total_usd"] if assembly else None,
            "board_and_assembly_per_unit_usd": assembly["per_unit_usd"] if assembly else None}


def _assembly_view(db: Session, run: M.ProductionRun) -> dict:
    sr = assembly_click(db, run)
    orders = assembly_orders(db, run)
    if sr is None:
        return {"recorded": False, "orders": orders}
    draws = (db.query(func.count(M.ComponentConsumption.id))
             .filter(M.ComponentConsumption.step_run_id == sr.id,
                     M.ComponentConsumption.voided_at.is_(None)).scalar() or 0)
    hdrs = run_actuals.header_ids(db)
    lines = sum(1 for (lid,) in db.query(M.CostLineStep.line_id)
                .join(M.RunCostLine, M.RunCostLine.id == M.CostLineStep.line_id)
                .filter(M.CostLineStep.step_run_id == sr.id, M.RunCostLine.voided_at.is_(None)).all()
                if lid not in hdrs)
    return {"recorded": True, "orders": orders, "step_run_id": sr.id, "made_at": sr.made_at,
            "units": sr.qty, "chosen": sr.chosen, "draws": draws, "lines": lines,
            "assembler": sr.assembler or "", "reference": sr.reference or ""}
