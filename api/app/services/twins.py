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
`assembly` step, done at the supplier. It is recorded from the batch's
assembly order when the boards are received: the order's measured draws and
every board and assembly position charged to the batch (`fab:*`, `pcba:*`)
point at it. Any other position can be linked to the click it paid for
(`link_costs`) — the final assembler's invoice, a print service.

The money paths need nothing new: a click's draws and positions stay charged
to the batch where the step was done, so run figures and the register see them
as before. A link only says which twins carry the money.
"""
from __future__ import annotations

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


def needs_met(graph: dict, step: dict, done: set[str]) -> list[str]:
    """Why `step` cannot run on a unit that has done `done`; [] when it can."""
    smap = P.step_map(graph)
    groups = P.groups_of(graph)
    label = {k: (s.get("label") or k) for k, s in smap.items()}
    why: list[str] = []
    key = step.get("key")
    if key in done:
        why.append(f"{label.get(key, key)!r} is already done")
    g = step.get("group")
    if g:
        other = [m for m in groups.get(g, []) if m != key and m in done]
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
        if any(m in done for m in members):
            why.append(f"must come before {label.get(ref, ref)!r}")
    return why


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
    return sr


def _link(db, twins: list[M.Twin], sr: M.StepRun) -> None:
    for tw in twins:
        db.add(M.TwinStep(twin_id=tw.id, step_run_id=sr.id))
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


def _twins_of_devices(db: Session, run: M.ProductionRun, devices: list[M.DeviceUnit]) -> list[M.Twin]:
    twins = []
    for d in devices:
        tw = db.query(M.Twin).filter_by(device_unit_id=d.id).first()
        if tw is None:
            raise HTTPException(409, f"{d.serial or d.mac} has no twin — merge it first")
        if tw.run_id != run.id:
            other = db.get(M.ProductionRun, tw.run_id)
            raise HTTPException(409, f"{d.serial or d.mac} is in {other.label if other else tw.run_id}, "
                                     f"not in {run.label}")
        if tw.status != "active":
            raise HTTPException(409, f"{d.serial or d.mac} is {tw.status}")
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
    if P.step_of_kind(graph, "assembly") is not None:
        plan["assembly"] = record_assembly(db, run, actor=actor)
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
        if d.get("lot_adjustment_id"):
            db.add(M.ComponentConsumptionLot(consumption_id=c.id, lot_adjustment_id=d["lot_adjustment_id"],
                                             qty=d["qty"], unit_cost_usd=d["unit_cost_usd"],
                                             source="manual", note=f"step click #{sr.id}"))
    db.flush()


def apply_step(db: Session, run: M.ProductionRun, *, step_key: str, stack: str = "",
               qty: int = 0, device_ids: list[int] | None = None, codes: list[str] | None = None,
               chosen: str = "", made_at: str = "", lots: dict | None = None, note: str = "",
               actor: str = "", dry_run: bool = True) -> dict:
    """Run one step on N units: from a stack (unnamed) or on devices (named).

    Dry run by default: the plan says which units qualify, every draw with its
    price, and any shortage. Programming and marking are refused here — their
    benches read the device and record them (0059 §5)."""
    v = crafted_version(db, run)
    graph = P._graph(v)
    step = _step(graph, step_key)
    kind = step.get("kind") or "step"
    if kind != "step":
        where = P.KINDS.get(kind, "batch").replace("_", " ")
        raise HTTPException(422, f"{step.get('label') or step_key!r} is a {kind!r} step — "
                                 + ("use receive" if kind == "receive" else
                                    "use finish" if kind == "finish" else
                                    "it is recorded from the batch's assembly order when the boards "
                                    "are received" if kind == "assembly" else f"it is done at the {where}"))
    made_at = made_at or _today()
    if stack:
        twins = _take_stack(db, run.project_id, stack, qty)
        if twins[0].run_id != run.id:
            raise HTTPException(409, "that stack belongs to another batch; craft it there")
        chosen = "stack"
        refusals = needs_met(graph, step, done_of_key(twins[0].stack_key))
        refused = {tw.id: refusals for tw in twins} if refusals else {}
    else:
        if chosen not in ("scanned", "list"):
            raise HTTPException(422, "say how the devices were chosen: scanned or list")
        devices = _resolve_devices(db, run, device_ids, codes)
        twins = _twins_of_devices(db, run, devices)
        done = done_steps(db, [tw.id for tw in twins])
        refused = {tw.id: why for tw in twins if (why := needs_met(graph, step, done[tw.id]))}
    n = len(twins)
    draws, problems, tokens = _plan_draws(db, run, step, n, made_at, lots)
    shortages = run_actuals.check_shortages(db, [
        {"component_id": d["component_id"], "mpn": d.get("mpn", ""), "lcsc": "", "qty": d["qty"],
         "date": made_at, "label": d["name"]} for d in draws if not d["internal"]],
        company_id=run_actuals.run_scope(db, run))
    dev_name = {}
    if not stack:
        dev_name = {tw.id: (db.get(M.DeviceUnit, tw.device_unit_id).serial
                            or db.get(M.DeviceUnit, tw.device_unit_id).mac) for tw in twins}
    plan = {
        "dry_run": dry_run, "step": step_key, "label": step.get("label") or step_key,
        "units": n, "chosen": chosen, "made_at": made_at,
        "refused": [{"unit": dev_name.get(tid) or "stack", "why": why} for tid, why in refused.items()],
        "draws": draws, "value_usd": round(sum(d["value_usd"] for d in draws), 4),
        "per_unit_usd": round(sum(d["value_usd"] for d in draws) / n, 6) if n else 0.0,
        "shortages": shortages, "problems": problems,
    }
    if dry_run:
        return plan
    if refused or shortages or problems:
        raise HTTPException(409, {"error": "the step cannot run on these units — see the plan",
                                  "plan": plan})
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
    plan = {"dry_run": dry_run, "units": len(twins), "chosen": chosen}
    if dry_run:
        return plan
    sr = _new_run(db, run, v, {"key": "scrap", "label": "Scrapped", "kind": "scrap"},
                  len(twins), chosen, "", actor, reason)
    _link(db, twins, sr)
    now = utcnow()
    for tw in twins:
        tw.status = "scrapped"
        tw.scrapped_at = now
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
    names = {d.id: d.serial or d.mac for d in devices}
    refused = [{"unit": names.get(tw.device_unit_id), "why": why}
               for tw in twins if (why := needs_met(graph, step, done[tw.id]))]
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
    return {lid for (lid,) in db.query(M.CostLineStep.line_id)
            .join(M.StepRun, M.StepRun.id == M.CostLineStep.step_run_id)
            .filter(M.StepRun.run_id == run_id).distinct().all()}


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
    """Point `line` at `clicks`, replacing any link it had (decision 0061)."""
    db.query(M.CostLineStep).filter_by(line_id=line.id).delete(synchronize_session=False)
    for sr in {c.id: c for c in clicks}.values():
        db.add(M.CostLineStep(line_id=line.id, step_run_id=sr.id))
    db.flush()


def record_assembly(db: Session, run: M.ProductionRun, *, actor: str = "", chosen: str = "supplier",
                    made_at: str = "", note: str = "") -> dict:
    """Record the board's assembly at the supplier on the batch's twins (0060).

    One click per batch. It takes every twin received in the batch (not the
    found ones, which entered at zero), the assembly order's measured draws,
    and every board and assembly position charged to the batch that no click
    claims yet. Safe to call again: twins received later, and positions
    imported later, join the same click. Nothing is linked while the batch
    has no twins, because a cost on a click with no units would be carried by
    nobody."""
    v = crafted_version(db, run)
    step = P.step_of_kind(P._graph(v), "assembly")
    if step is None:
        return {"status": "no_assembly_step"}
    _refuse_closed(run)
    twins = (db.query(M.Twin).filter(M.Twin.origin_run_id == run.id, M.Twin.found.is_(False))
             .order_by(M.Twin.id).all())
    if not twins:
        return {"status": "no_twins", "orders": assembly_orders(db, run)}
    lines = [li for li in charged_lines(db, run, unlinked_only=True)
             if cost_steps.stage_of(li.plan_key) in ASSEMBLY_STAGES]
    draws = (run_actuals.live_consumption(db, run_id=run.id)
             .filter(M.ComponentConsumption.basis == "measured",
                     M.ComponentConsumption.step_run_id.is_(None)).all())
    sr = assembly_click(db, run)
    created = sr is None
    orders = assembly_orders(db, run)
    if sr is None:
        dates = sorted(d for d in (db.get(M.RunCostDocument, li.document_id).doc_date
                                   for li in lines) if d)
        sr = _new_run(db, run, v, step, 0, chosen, made_at or (dates[0] if dates else "")
                      or run.run_date or _today(), actor,
                      note or (f"assembly order {', '.join(orders)}" if orders else "assembly"))
    have = {tid for (tid,) in db.query(M.TwinStep.twin_id).filter_by(step_run_id=sr.id).all()}
    new = [tw for tw in twins if tw.id not in have]
    _link(db, new, sr)
    for tw in new:
        tw.stack_key = _add_token(tw.stack_key, step["key"])
    sr.qty = len(have) + len(new)
    for li in lines:
        link_line(db, li, [sr])   # replaces a stale link to another batch's click
    for c in draws:
        c.step_run_id = sr.id
    db.flush()
    return {"status": "recorded" if created else "extended", "step_run_id": sr.id,
            "orders": orders, "twins_added": len(new), "units": sr.qty,
            "lines_linked": len(lines), "draws_linked": len(draws)}


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
        if not clicks:
            raise HTTPException(422, "select at least one step click")
    lines: list[M.RunCostLine] = []
    seen: set[int] = set()
    for lid in line_ids or []:
        li = db.get(M.RunCostLine, int(lid))
        if li is None:
            raise HTTPException(404, f"no position {lid}")
        kids = (db.query(M.RunCostLine)
                .filter(M.RunCostLine.parent_line_id == li.id, M.RunCostLine.voided_at.is_(None)).all())
        for x in (kids or [li]):
            if x.id not in seen:
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
    plan = {"dry_run": dry_run, "step_run_ids": [] if unlink else [c.id for c in clicks],
            "unlink": unlink,
            "lines": [{"line_id": li.id, "label": li.label, "plan_key": li.plan_key,
                       "from_step_run_ids": sorted(before.get(li.id, []))} for li in lines],
            "refused": refused}
    if dry_run:
        return plan
    if refused:
        raise HTTPException(409, {"error": "some positions cannot be linked — see the plan",
                                  "plan": plan})
    for li in lines:
        link_line(db, li, [] if unlink else clicks)
    return plan


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


def bench_stack_left(db: Session, run: M.ProductionRun) -> int | None:
    """Units left in the batch's selected stack; None when none is selected."""
    if not run.bench_stack:
        return None
    rid, key = parse_stack(run.bench_stack)
    return (db.query(func.count(M.Twin.id))
            .filter(M.Twin.project_id == run.project_id, M.Twin.run_id == rid,
                    M.Twin.stack_key == key, M.Twin.device_unit_id.is_(None),
                    M.Twin.status == "active").scalar() or 0)


def _name(db, tw: M.Twin, device: M.DeviceUnit, batch: M.ProductionRun, chosen: str,
          made_at: str, actor: str) -> None:
    v = db.get(M.ProcessVersion, batch.process_version_id) or db.get(M.ProcessVersion, tw.process_version_id)
    prog = P.step_of_kind(P._graph(v), "program") or {"key": "program", "label": "Programmed",
                                                       "kind": "program"}
    tw.device_unit_id = device.id
    tw.run_id = batch.id
    tw.named_at = utcnow()
    tw.stack_key = _add_token(tw.stack_key, prog["key"])
    sr = _new_run(db, batch, v, prog, 1, chosen, made_at, actor,
                  f"named {device.serial or device.mac}")
    _link(db, [tw], sr)
    _draw_or_note(db, batch, sr, prog, 1)


def name_at_bench(db: Session, device: M.DeviceUnit, event: M.DeviceEvent,
                  batch: M.ProductionRun | None) -> M.Twin | None:
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
                  M.Twin.stack_key == key, M.Twin.device_unit_id.is_(None),
                  M.Twin.status == "active")
          .order_by(M.Twin.id).with_for_update(skip_locked=True).first())
    if tw is None:
        return None
    at = event.at.date().isoformat() if event is not None and event.at else _today()
    _name(db, tw, device, batch, "bench", at, event.actor if event is not None else "")
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
        _name(db, tw, d, run, "merge", "", actor)
    db.flush()
    plan["caught_up"] = catch_up(db, twins)
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
        what = ", ".join(sorted({x.get("label") or x.get("name") or "?" for x in (short or problems)}))
        sr.note = f"{sr.note} — not drawn, the pool held none: {what}"[:500]
        return
    write_draws(db, run, sr, draws, f"{sr.step_label} x {sr.qty} (bench, click #{sr.id})")


def _bench_step(db: Session, run: M.ProductionRun, v: M.ProcessVersion, step: dict, tw: M.Twin,
                note: str, *, actor: str = "", factor: float = 1, made_at: str = "") -> M.StepRun:
    """A bench recorded `step` on one twin: one click, and what the step adds
    drawn from the pool (decision 0061)."""
    sr = _new_run(db, run, v, step, 1, "bench", made_at, actor, note)
    _link(db, [tw], sr)
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
                   made_at: str = "", note: str = "") -> list[str]:
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
        if needs_met(graph, step, done_steps(db, [tw.id])[tw.id]):
            continue
        _bench_step(db, run, v, step, tw, note or f"{device.serial or device.mac}", actor=actor,
                    factor=copies if kind == "label" else 1, made_at=made_at)
        out.append(step["key"])
    db.flush()
    return out


def record_test(db: Session, device: M.DeviceUnit, *, deployment_id: int | None = None,
                actor: str = "", made_at: str = "", note: str = "") -> list[str]:
    """A test procedure passed on `device`: record the process's test step on
    its twin, where its needs are met (decision 0061). The step is the one that
    names the run's deployment, else one that names none."""
    tw, run, v = _twin_process(db, device)
    if v is None:
        return []
    graph = P._graph(v)
    step = P.step_for_deployment(graph, "test", deployment_id)
    if step is None or needs_met(graph, step, done_steps(db, [tw.id])[tw.id]):
        return []
    _bench_step(db, run, v, step, tw, note or f"{device.serial or device.mac}: test passed",
                actor=actor, made_at=made_at)
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
                                      copies=int(res.get("label_copies") or 1), made_at=when, note=why)
            if r.status == "pass" and dep is not None and (dep.kind or "") == "test":
                got += record_test(db, device, deployment_id=dep.id, actor=r.operator or "",
                                   made_at=when, note=why)
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
    return None


def follow_rebatch(db: Session, device: M.DeviceUnit, to_run_id: int) -> None:
    """A rebatched device's twin is in the batch that built it (decision 0029).
    Its origin batch never moves."""
    tw = db.query(M.Twin).filter_by(device_unit_id=device.id).first()
    if tw is not None:
        tw.run_id = to_run_id


def refuse_unfinished(db: Session, device: M.DeviceUnit) -> None:
    """Only a finished device ships (0059 §9). A device with no twin — made
    before twins existed — ships as before."""
    tw = db.query(M.Twin).filter_by(device_unit_id=device.id).first()
    if tw is not None and tw.status != "finished":
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
    lines = (db.query(M.RunCostLine)
             .filter(M.RunCostLine.id.in_(list(clicks_of)), M.RunCostLine.voided_at.is_(None)).all())
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
        out[rid] = {"origin_cost_usd": round(origin, 4), "scrap_carried_usd": round(carried, 4),
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
                   "costs_usd": round(sum(c["usd"] for c in costs_by_click.get(sr.id, [])), 4)}
                  for sr in sorted(rows, key=lambda r: (order.get(r.kind, 2), r.id))],
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
    pr = prices(db, named) if named else {}
    devs = {d.id: d for d in db.query(M.DeviceUnit)
            .filter(M.DeviceUnit.id.in_([tw.device_unit_id for tw in named] or [-1])).all()}
    devices = []
    for tw in named:
        d = devs.get(tw.device_unit_id)
        devices.append({"device_id": tw.device_unit_id, "serial": d.serial if d else None,
                        "mac": d.mac if d else None, "status": tw.status,
                        "origin_run_id": tw.origin_run_id, "done": in_route_order(done[tw.id]),
                        "missing": needs_met(graph, P.step_of_kind(graph, "finish") or {}, done[tw.id])
                        if tw.status == "active" else [],
                        "price_usd": pr.get(tw.id, {}).get("total_usd")})
    counts = defaultdict(int)
    for tw in db.query(M.Twin).filter(M.Twin.origin_run_id == run.id).all():
        counts[tw.status] += 1
    share = origin_shares(db, [run.id]).get(run.id)
    line_click = click_costs(line_shares(db, [run.id]))
    draw_click, _ = _step_draw_values(db, [run.id])
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
                    "parts_usd": round(draw_click.get(sr.id, 0.0), 4)}
                   for sr in db.query(M.StepRun).filter_by(run_id=run.id)
                   .order_by(M.StepRun.id.desc()).limit(200).all()],
        "assembly": _assembly_view(db, run),
        "unlinked": unlinked(db, run),
    }


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
    lines = (db.query(func.count(M.CostLineStep.id)).filter(M.CostLineStep.step_run_id == sr.id)
             .scalar() or 0)
    return {"recorded": True, "orders": orders, "step_run_id": sr.id, "made_at": sr.made_at,
            "units": sr.qty, "chosen": sr.chosen, "draws": draws, "lines": lines}
