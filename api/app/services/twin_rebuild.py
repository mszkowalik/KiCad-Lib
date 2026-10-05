"""Rebuild a batch made before twins into twins (decisions 0060, 0074).

An old batch has its devices, its draws, its invoice positions and the runs its
benches kept, but no twins, so each of its devices costs the batch's average
(decision 0043) and has no history of steps. This module gives the batch one
twin per device it produced, plus unnamed twins for spares a stock count
found, records the process steps its records prove, and points its draws and
positions at those steps. From then on the batch reads like a crafted one.

Six rules:

1. **Nothing is invented, and evidence is per device.** Programming comes from
   each device's `produced` event and the run that produced it
   (`twins.pick_production_pass`). A test, a
   laser mark and a label come from the device's own bench runs: a passing
   test run, a marking run whose results say `marked` or `printed`. Their
   clicks are one per day and deployment version, and each twin's step names
   its run. Any other step with parts is recorded when the batch drew those
   parts. A person's statement (`assume`) covers the rest, and only devices
   with no bench record of that step. An invoice position is money, never
   proof that a step happened on a unit. Every click says `chosen="rebuilt"`.
2. **The draws must match the units.** For each step and part the plan shows
   what was drawn against units x quantity. A difference above `tolerance` is
   stated (`settle`): draw the deficit, record it short, return the surplus to
   the stock, or keep the surplus in the origin batch cost as a loss. A draw
   that feeds several clicks is split into pieces, one per click.
3. **No money moves between batches.** Draws and positions keep their batch
   and their value. Only the draws the rebuild writes and the surplus it
   returns move a batch's total, and the twins' prices must add up to the
   totals of every batch involved.
4. **Each step carries the date it happened.** A step before programming: the
   earlier of the batch's date and its first programming. A step after it:
   the bench run's date, else the device's programming date, one click a day.
5. **A twin's status comes from its device's record:** disposed → scrapped (on
   the disposal's date), faulty or incomplete → active, any other → finished,
   unless `active` names the device as still in progress.
6. **It can be extended and undone.** A real write is one journal batch.
   `append` gives devices that joined the batch later their twins. `undo`
   takes back the live clicks that stand on the rebuilt twins, then the
   rebuild.
"""
from __future__ import annotations

import re
from collections import defaultdict
from contextvars import ContextVar
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from . import cost_steps, jlc_import, journal, run_actuals
from . import lots as L
from . import process as P
from . import twins as T

CHOSEN = "rebuilt"
#: Device conditions whose twin stays active: built, but not sellable as it is.
NOT_FINISHED = ("faulty", "incomplete")
#: How far the twins' prices may stray from the register's batch total, in USD.
TOTAL_EPS = 0.05
EPS = 1e-6
#: Step kinds a bench records: their evidence is the device's own bench runs.
BENCH_KINDS = ("test", "mark_laser", "label")
#: What a person may state about a difference between drawn and needed parts.
FOR_DEFICIT = ("draw", "short")
FOR_SURPLUS = ("return", "loss")
SETTLE = FOR_DEFICIT + FOR_SURPLUS
#: The void reason of a draw the rebuild returned to the stock whole.
RETURNED = "rebuild: surplus returned"
#: A marking op → the step kind it performs, and the result that proves it.
MARK_OPS = (("mark_laser", "mark_laser", "marked"), ("label", "print_label", "printed"))
SOURCE_TEXT = {"bench": "bench runs", "stated": "stated by the user", "draws": "draws",
               "stock": "stock count", "produced": "produced events"}
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}")


# ================================================================== helpers

def _iso(s) -> str:
    """An ISO date, or "" — `run_date` is free text."""
    s = str(s or "").strip()[:10]
    return s if _ISO.fullmatch(s) else ""


def _day(dt: datetime | None) -> str:
    return dt.date().isoformat() if dt else ""


#: (pool entries, cache) for one rebuild: parts are matched by pool identity,
#: as a step draw finds them (`resolve_pool_identity`), so a draw carrying a
#: component id meets an input named by its MPN (decision 0075).
_CANON: ContextVar[tuple | None] = ContextVar("rebuild_canon", default=None)


def _canon(cid, mpn: str, lcsc: str = "") -> tuple[str, object]:
    raw = ("c", cid) if cid else ("m", run_actuals._strip(mpn or ""))
    ctx = _CANON.get()
    if ctx is None:
        return raw
    entries, cache = ctx
    k = (cid, run_actuals._strip(mpn or ""), lcsc or "")
    if k not in cache:
        keys = set(run_actuals._identity_keys(cid, "" if cid else (mpn or ""), lcsc or ""))
        hit = next((e for e in entries if keys & set(run_actuals._identity_keys(
            e.get("component_id"), e.get("mpn") or "", e.get("lcsc") or ""))), None) if keys else None
        cache[k] = (raw if hit is None else ("c", hit["component_id"]) if hit.get("component_id")
                    else ("m", run_actuals._strip(hit.get("mpn") or mpn or "")))
    return cache[k]


def _key_of_input(inp: dict) -> tuple[str, object]:
    cid, mpn = P.input_ref(inp)
    return _canon(cid, mpn)


def _key_of_draw(c: M.ComponentConsumption) -> tuple[str, object]:
    return _canon(c.component_id, c.mpn or "", c.lcsc or "")


def _ref(key: tuple[str, object]) -> str:
    """A part as the plan names it and `settle` takes it: `c<id>` or `m<MPN>`,
    the pool's own keys."""
    return f"{key[0]}{key[1]}"


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


def _events(db: Session, device_ids: list[int], kind: str, last: bool = False) -> dict[int, M.DeviceEvent]:
    """Each device's first (or last) event of `kind`."""
    out: dict[int, M.DeviceEvent] = {}
    for ev in (db.query(M.DeviceEvent).filter(M.DeviceEvent.device_id.in_(device_ids or [-1]),
                                              M.DeviceEvent.kind == kind)
               .order_by(M.DeviceEvent.at, M.DeviceEvent.id).all()):
        if last or ev.device_id not in out:
            out[ev.device_id] = ev
    return out


def _before_program(graph: dict) -> set[str]:
    """Steps done before programming: what programming needs, directly or
    through other steps, and the route's steps before it that do not need it."""
    smap = P.step_map(graph)
    groups = P.groups_of(graph)
    prog = P.step_of_kind(graph, "program")["key"]

    def refs(ref: str) -> list[str]:
        return groups.get(ref) or [ref]

    after: set[str] = set()
    changed = True
    while changed:
        changed = False
        for k, s in smap.items():
            if k in after or k == prog:
                continue
            if any(r == prog or r in after for ref in s.get("needs") or [] for r in refs(ref)):
                after.add(k)
                changed = True
    before: set[str] = set()
    todo = [r for ref in smap[prog].get("needs") or [] for r in refs(ref)]
    while todo:
        k = todo.pop()
        if k in before or k not in smap:
            continue
        before.add(k)
        todo += [r for ref in smap[k].get("needs") or [] for r in refs(ref)]
    route = [k for k in graph.get("route") or [] if k in smap]
    if prog in route:
        before |= {k for k in route[:route.index(prog)] if k not in after}
    return before


class _Devices:
    """Which devices a statement names: ids and codes, a programmed date range
    (`since` and `until`, both inclusive), or every device when it names
    nothing."""

    def __init__(self, ids: set[int] | None = None, since: str = "", until: str = ""):
        self.ids, self.since, self.until = ids, since, until

    def takes(self, device_id: int, produced: str) -> bool:
        if self.ids is not None and device_id not in self.ids:
            return False
        if self.since and not (produced and produced >= self.since):
            return False
        return not (self.until and not (produced and produced <= self.until))

    def json(self) -> dict:
        out: dict = {}
        if self.ids is not None:
            out["devices"] = len(self.ids)
        if self.since:
            out["since"] = self.since
        if self.until:
            out["until"] = self.until
        return out or {"devices": "all"}


def _selector(db: Session, raw: dict | None, allowed: set[int], what: str) -> _Devices:
    from .orders import find_device

    raw = raw or {}
    ids: set[int] | None = None
    if raw.get("device_ids") or raw.get("codes"):
        ids, missing = set(), []
        for did in raw.get("device_ids") or []:
            ids.add(int(did))
        for code in raw.get("codes") or []:
            d = find_device(db, str(code)) or (db.query(M.DeviceUnit).filter(
                func.lower(M.DeviceUnit.mac) == str(code).strip().lower()).first())
            if d is None:
                missing.append(str(code))
            else:
                ids.add(d.id)
        if missing:
            raise HTTPException(422, f"{what}: no device for {', '.join(missing[:10])}")
        foreign = sorted(ids - allowed)
        if foreign:
            raise HTTPException(422, f"{what}: device(s) {foreign[:10]} were not produced in this batch")
    since, until = str(raw.get("since") or "").strip(), str(raw.get("until") or "").strip()
    for d in (since, until):
        if d and not _iso(d):
            raise HTTPException(422, f"{what}: {d!r} is not a date (YYYY-MM-DD)")
    if since and until and since > until:
        raise HTTPException(422, f"{what}: 'since' {since} is after 'until' {until}")
    return _Devices(ids, since, until)


def _stated(assume, since: dict, until: dict) -> dict[str, dict]:
    """`assume` as step key → device selection. A list states a step for every
    device; `since` and `until` narrow a stated step to a programmed date range."""
    out: dict[str, dict] = {}
    if isinstance(assume, dict):
        for k, raw in assume.items():
            out[k] = dict(raw or {})
    else:
        for k in assume or []:
            out[k] = {}
    bad = [f"{k} (since needs it stated)" for k in since if k not in out]
    bad += [f"{k} (until needs it stated)" for k in until if k not in out]
    if bad:
        raise HTTPException(422, f"no step {bad[0]!r}")
    for k, d in since.items():
        out[k]["since"] = d
    for k, d in until.items():
        out[k]["until"] = d
    return out


def _bench(db: Session, graph: dict, device_ids: list[int], run: M.ProductionRun) -> dict:
    """What the benches recorded per device: the flash run behind programming,
    the evidence of each bench step (a passing test, a marking run that marked
    or printed), and the bench records that are NOT evidence (a failed test, a
    marking run that tried and did nothing) — a statement does not override
    those."""
    flash: dict[int, dict] = {}
    evidence: dict[tuple[int, str], dict] = {}
    record: dict[tuple[int, str], list[str]] = defaultdict(list)
    if not device_ids:
        return {"flash": flash, "evidence": evidence, "record": record}
    rows = (db.query(M.ProgrammingRun, M.DeploymentVersion.deployment_id, M.Deployment.kind)
            .outerjoin(M.DeploymentVersion, M.DeploymentVersion.id == M.ProgrammingRun.deployment_version_id)
            .outerjoin(M.Deployment, M.Deployment.id == M.DeploymentVersion.deployment_id)
            .filter(M.ProgrammingRun.device_unit_id.in_(device_ids), M.ProgrammingRun.draft_run.is_(False))
            .order_by(M.ProgrammingRun.started_at, M.ProgrammingRun.id).all())
    ops: dict[int, set[str]] = defaultdict(set)
    mark_ids = [r.id for r, _d, k in rows if k == "mark"]
    for rid, op in (db.query(M.ProgrammingStep.run_id, M.ProgrammingStep.op)
                    .filter(M.ProgrammingStep.run_id.in_(mark_ids or [-1])).all()):
        ops[rid].add(op)
    passes: dict[int, list] = defaultdict(list)
    for r, dep_id, kind in rows:
        dev, res, at = r.device_unit_id, r.results or {}, r.started_at
        if kind == "flash" and r.status == "pass" and (r.action or "program") == "program":
            passes[dev].append(r)
        kind = kind or ("flash" if (r.action or "program") == "program" else "")
        found = {"run": r.id, "dv": r.deployment_version_id, "at": at, "on": _day(at), "copies": 1}
        if kind == "flash":
            pass   # chosen below, once every pass of the device is known
        elif kind == "test":
            step = P.step_for_deployment(graph, "test", dep_id)
            if step is not None and (dev, step["key"]) not in evidence:
                if r.status == "pass":
                    evidence[(dev, step["key"])] = found
                else:
                    record[(dev, step["key"])].append(f"test run #{r.id} {r.status}")
        elif kind == "mark":
            for step_kind, op, flag in MARK_OPS:
                step = P.step_for_deployment(graph, step_kind, dep_id)
                if step is None or (dev, step["key"]) in evidence:
                    continue
                if res.get(flag):
                    copies = 1
                    if step_kind == "label":
                        try:
                            copies = max(int(res.get("label_copies") or 1), 1)
                        except (TypeError, ValueError):
                            copies = 1
                    evidence[(dev, step["key"])] = {**found, "copies": copies}
                elif op in ops.get(r.id, set()):
                    record[(dev, step["key"])].append(f"marking run #{r.id} {r.status}, nothing {flag}")
    # The run that PRODUCED the device, by the rule the bench and a merge use
    # (`twins.pick_production_pass`): not a trial before it, not a reflash.
    produced = _events(db, list(passes), "produced")
    for dev, rs in passes.items():
        r = T.pick_production_pass(rs, produced.get(dev))
        flash[dev] = {"run": r.id, "dv": r.deployment_version_id, "at": r.started_at, "on": _day(r.started_at),
                      "copies": 1}
    return {"flash": flash, "evidence": evidence, "record": record}


def _dv_labels(db: Session, ids: set) -> dict[int, str]:
    out = {}
    for dv in (db.query(M.DeploymentVersion).filter(M.DeploymentVersion.id.in_(ids)).all() if ids else []):
        dep = db.get(M.Deployment, dv.deployment_id)
        out[dv.id] = f"{dep.name if dep else 'deployment'} v{dv.version_no}"
    return out


def _total(reg: dict, run_id: int) -> float:
    return float((reg["by_run_usd"].get(str(run_id)) or {}).get("total_usd") or 0.0)


def _carried(db: Session, batch_ids: set[int], reg: dict) -> tuple[float, float, int]:
    """What the twins carry of `batch_ids`' money: the prices of every twin of
    those batches (their origin, or a click done in them), less what those
    prices hold from OTHER batches (a click done elsewhere, another batch's
    origin share). Returns (carried, from other batches, twins carrying)."""
    ids = {tid for (tid,) in db.query(M.Twin.id).filter(M.Twin.origin_run_id.in_(batch_ids),
                                                         M.Twin.found.is_(False)).all()}
    ids |= {tid for (tid,) in db.query(M.TwinStep.twin_id)
            .join(M.StepRun, M.StepRun.id == M.TwinStep.step_run_id)
            .filter(M.StepRun.run_id.in_(batch_ids)).all()}
    twins = db.query(M.Twin).filter(M.Twin.id.in_(ids or {-1})).all()
    alive = [tw for tw in twins if tw.status != "scrapped"]
    pr = T.prices(db, alive, reg)
    carried = sum(p["total_usd"] for p in pr.values())
    # Scrapped twins pass their own costs into their batch's share, so what
    # they took from elsewhere is inside `carried` too.
    carriers = alive + [tw for tw in twins if tw.status == "scrapped"
                        and (tw.origin_run_id in batch_ids if not tw.found else tw.run_id in batch_ids)]
    cids = [tw.id for tw in carriers]
    links = db.query(M.TwinStep.twin_id, M.TwinStep.step_run_id).filter(M.TwinStep.twin_id.in_(cids or [-1])).all()
    click_run = {sid: rid for sid, rid in db.query(M.StepRun.id, M.StepRun.run_id)
                 .filter(M.StepRun.id.in_({s for _t, s in links} or {-1})).all()}
    elsewhere = {s for s, rid in click_run.items() if rid not in batch_ids}
    outside = 0.0
    if elsewhere:
        by_click, _ = T._step_draw_values(db)
        outside += sum(T._own(db, cids, {c: v for c, v in by_click.items() if c in elsewhere}).values())
        mine = set(cids)
        for sh in T.line_shares(db):
            if sh["run_id"] not in batch_ids and sh["twins"]:
                outside += sh["usd"] / len(sh["twins"]) * len(sh["twins"] & mine)
    outside += sum(pr[tw.id]["origin_share_usd"] for tw in alive
                   if not tw.found and tw.origin_run_id not in batch_ids)
    return carried, outside, len(alive)


# ================================================================== rebuild

def rebuild(db: Session, run: M.ProductionRun, *, version_id: int | None = None,
            assume: list[str] | dict[str, dict] | None = None, draw: list[str] | None = None,
            since: dict[str, str] | None = None, until: dict[str, str] | None = None,
            costs: dict[str, list[str] | str] | None = None, spares: list[dict] | None = None,
            settle: list[dict] | None = None, tolerance: float = 0.0, active: dict | None = None,
            origins: list[dict] | None = None, append: bool = False, actor: str = "",
            dry_run: bool = True) -> dict:
    """Give `run` its twins from its records. Dry run by default: everything is
    written inside a savepoint and rolled back, so the plan is what the real
    write would do. A real write is one journal batch (`craft.rebuild`), and
    `undo` reverses it.

    `assume`: the steps that happened though no record proves it — a person's
    statement. A list states a step for every device; a mapping states it for
    some (`{"label": {"device_ids": [..], "codes": [..], "since": "..",
    "until": ".."}}`). A statement covers only devices with no bench record of
    that step. `since` / `until`: step key → ISO date, the short form of a
    programmed date range for a stated step (the leaflet, since 2025-04-15).
    `draw`: the stated steps whose parts came from OUR stock; their missing
    parts are drawn at each click's date. A stated step not in `draw` that the
    batch drew nothing for used someone else's parts and draws nothing.
    `costs`: plan key → the step keys a position paid for, other than the
    assembly; one position can pay for several steps, and their twins share
    it. Positions not named stay in the origin batch cost. `spares`: `[{"qty",
    "done", "note"}]` — unnamed units on the shelf and the steps they took.
    `settle`: `[{"step", "part", "how"}]` — a statement per difference between
    drawn and needed parts (`part` as the plan names it, or `*`; `how`:
    `draw`, `short`, `return`, `loss`). `tolerance`: the difference in pieces
    that needs no statement. `active`: the devices still in progress, whose
    twins stay active. `origins`: `[{"from_run_id", "device_ids" | "codes" |
    "since" / "until"}]` — devices built on another batch's boards (that batch
    rebuilt first), or with `from_run_id` null, devices whose source batch is
    unknown. `append`: give devices that joined a rebuilt batch later their
    twins, with the batch's own process version."""
    stated_raw = _stated(assume, dict(since or {}), dict(until or {}))
    draw = list(draw or [])
    costs = {k: ([v] if isinstance(v, str) else list(v)) for k, v in (costs or {}).items()}
    spares = list(spares or [])
    origins = list(origins or [])
    settle_map: dict[tuple[str, str], str] = {}
    for s in settle or []:
        how = (s.get("how") or "").strip()
        if how not in SETTLE:
            raise HTTPException(422, f"settle: {how!r} is not one of {', '.join(SETTLE)}")
        settle_map[(s.get("step") or "", (s.get("part") or "*").strip() or "*")] = how
    if run.closed_at is not None:
        raise HTTPException(409, f"batch {run.label} is closed — reopen it before rebuilding it")
    if append:
        v = db.get(M.ProcessVersion, run.process_version_id) if run.process_version_id else None
        if v is None:
            raise HTTPException(409, f"batch {run.label} is not rebuilt — rebuild it before appending to it")
        if version_id and version_id != v.id:
            raise HTTPException(409, f"batch {run.label} runs process version {v.version_no}; an append "
                                     "takes the batch's own version")
    else:
        v = db.get(M.ProcessVersion, version_id) if version_id else P.version_for_run(db, run)
    if v is None or v.project_id != run.project_id or v.status != "published":
        raise HTTPException(422, "rebuild needs a published process version of this project")
    graph = P._graph(v)
    smap = P.step_map(graph)
    for kind in ("assembly", "receive", "program", "finish"):
        if P.step_of_kind(graph, kind) is None:
            raise HTTPException(422, f"the process has no {kind!r} step")
    bad = [k for k in list(stated_raw) + draw if k not in smap]
    bad += [k for ks in costs.values() for k in ks if k not in smap]
    bad += [f"{k} (draw needs it stated)" for k in draw if k not in stated_raw]
    bad += [k for sp in spares for k in sp.get("done") or [] if k not in smap]
    # An unnamed spare never carries a bench step or programming: the bench
    # records those on the device later (decision 0075).
    bad += [f"{k} (a spare carries no bench step)" for sp in spares for k in sp.get("done") or []
            if k in smap and (smap[k].get("kind") or "step") in tuple(P.DEPLOYMENT_KIND_FOR)]
    for sp in spares:
        have = {(P.step_of_kind(graph, "assembly") or {}).get("key"), (P.step_of_kind(graph, "receive") or {}).get("key")}
        order = [k for k in graph["route"] if k in (sp.get("done") or [])]
        order += [k for k in sp.get("done") or [] if k not in order and k in smap]
        for k in order:
            # Every spare has the assembly and the receipt; a plan's own
            # `spare_units[].done` names them, and may be sent back as it is.
            if (smap[k].get("kind") or "step") in tuple(P.DEPLOYMENT_KIND_FOR) or k in have:
                continue
            if T.needs_met(graph, smap[k], have):
                bad.append(f"{k} (a spare: {'; '.join(T.needs_met(graph, smap[k], have))})")
            have.add(k)
    bad += [k for k, _p in settle_map if k not in smap]
    if bad:
        raise HTTPException(422, f"no step {bad[0]!r} in process version {v.version_no}")
    if not append:
        if run.process_version_id not in (None, v.id):
            raise HTTPException(409, f"batch {run.label} already runs another process version")
        if db.query(M.Twin).filter(M.Twin.origin_run_id == run.id, M.Twin.found.is_(False)).count():
            raise HTTPException(409, f"batch {run.label} already has twins — undo the rebuild first, "
                                     "or append the devices that joined it since")
        if db.query(M.StepRun).filter_by(run_id=run.id).count():
            raise HTTPException(409, f"batch {run.label} already has process steps")
    else:
        for kind in ("assembly", "receive"):
            sr = _rebuilt_click(db, run, kind)
            if sr is None:
                raise HTTPException(409, f"batch {run.label} has no rebuilt {kind} step — append is for "
                                         "a batch rebuilt into twins")
            # Another batch's rebuild joined these clicks (`origins`): editing
            # them would leave neither rebuild undoable.
            for (src,) in (db.query(M.WriteBatch.source_ref).join(M.WriteBatchRow, M.WriteBatchRow.batch_id == M.WriteBatch.id)
                           .filter(M.WriteBatchRow.table_name == "step_runs", M.WriteBatchRow.row_id == sr.id,
                                   M.WriteBatchRow.op == "update", M.WriteBatch.kind == "craft.rebuild",
                                   M.WriteBatch.reversed_at.is_(None), M.WriteBatch.source_ref != f"run:{run.id}")
                           .distinct().all()):
                other = db.get(M.ProductionRun, int((src or "run:0").split(":", 1)[1] or 0))
                raise HTTPException(409, f"the rebuild of {other.label if other else src} joined {run.label}'s "
                                         f"rebuilt {kind} — undo it first, append, then rebuild it again")

    def build() -> dict:
        sp = db.begin_nested()
        try:
            plan = _Build(db, run, v, graph, stated=stated_raw, draw=draw, costs=costs, spares=spares,
                          settle=settle_map, tolerance=float(tolerance or 0.0), active=active,
                          origins=origins, append=append, actor=actor).execute()
        except Exception:
            if sp.is_active:
                sp.rollback()
            raise
        plan["dry_run"] = dry_run
        if dry_run or plan["refusals"]:
            sp.rollback()
            db.expire_all()
        else:
            sp.commit()
        return plan

    token = _CANON.set((list(run_actuals.pool_state(db).values()), {}))
    try:
        if dry_run:
            return build()
        summary = {"append": append, "process_version": v.version_no,
                   # what "Undo rebuild" puts back (decision 0075)
                   "pinned_before": None if append else run.process_version_id}
        with journal.batch(db, kind="craft.rebuild", source_ref=f"run:{run.id}", actor=actor,
                           summary=summary) as h:
            plan = build()
            summary["returned_low"] = plan.get("returned_low") or {}
            summary["returned_lots"] = plan.get("returned_lots") or {}
            if plan["refusals"]:
                first = plan["refusals"][0]["message"]
                raise HTTPException(409, {"error": f"{first} — nothing was kept", "refusals": plan["refusals"],
                                          "unsettled": plan["unsettled"], "check": plan["check"]})
    finally:
        _CANON.reset(token)
    plan["batch_id"] = h["batch_id"]
    return plan


def _rebuilt_click(db: Session, run: M.ProductionRun, kind: str) -> M.StepRun | None:
    return (db.query(M.StepRun).filter_by(run_id=run.id, kind=kind, chosen=CHOSEN)
            .order_by(M.StepRun.id).first())


class _Build:
    """One rebuild (or append), written inside the caller's savepoint."""

    def __init__(self, db, run, v, graph, *, stated, draw, costs, spares, settle, tolerance,
                 active, origins, append, actor):
        self.db, self.run, self.v, self.graph = db, run, v, graph
        self.smap = P.step_map(graph)
        self.stated_raw, self.draw, self.costs, self.spares_in = stated, draw, costs, spares
        self.settle, self.tol, self.active_raw, self.origins_raw = settle, tolerance, active, origins
        self.append, self.actor = append, actor
        self.akey = P.step_of_kind(graph, "assembly")["key"]
        self.rkey = P.step_of_kind(graph, "receive")["key"]
        self.before = _before_program(graph)
        self.route = ([k for k in graph["route"] if k in self.smap]
                      + [k for k in self.smap if k not in graph["route"]])
        self.done: dict[int, set[str]] = defaultdict(set)
        self.when: dict[int, dict[str, dict]] = defaultdict(dict)
        self.last_at: dict[int, datetime] = {}
        self.new_clicks: dict[str, list[M.StepRun]] = defaultdict(list)
        self.old_clicks: dict[str, list[M.StepRun]] = defaultdict(list)
        self.info: dict[int, dict] = {}
        self.refusals: list[dict] = []
        self.added: list[dict] = []
        self.returned: list[dict] = []
        self.returned_low: dict[str, dict] = {}
        self.returned_lots: dict[str, float] = {}
        self.parts: list[dict] = []
        self.unsettled: list[dict] = []
        self.recorded: list[dict] = []
        self.not_recorded: list[dict] = []
        self.says_not: dict[str, list[str]] = defaultdict(list)

    # ---------------------------------------------------------------- clicks

    def click(self, step: dict, members: list[tuple[M.Twin, dict]], made_at: str, note: str,
              source: str, *, consumes: bool = False, auto: bool = False) -> M.StepRun | None:
        """One rebuilt click. `members`: (twin, {"run", "dv", "at", "factor"}) —
        each twin's own bench run and deployment version (decision 0074)."""
        if not members:
            return None
        db = self.db
        sr = T._new_run(db, self.run, self.v, step, len(members), CHOSEN, made_at or self.d0, self.actor, note)
        db.add_all([M.TwinStep(twin_id=tw.id, step_run_id=sr.id, programming_run_id=x.get("run"),
                               deployment_version_id=x.get("dv")) for tw, x in members])
        for tw, x in members:
            self._did(tw, step["key"], sr.made_at, source, x)
        self.new_clicks[step["key"]].append(sr)
        self.info[sr.id] = {"source": source, "consumes": consumes, "auto": auto,
                            "factor": sum(float(x.get("factor") or 1) for _tw, x in members)}
        return sr

    def join(self, sr: M.StepRun, twins: list[M.Twin], source: str = "batch") -> None:
        """Add twins to an existing rebuilt click (the assembly and receipt of
        the boards they were built on)."""
        if not twins:
            return
        self.db.add_all([M.TwinStep(twin_id=tw.id, step_run_id=sr.id) for tw in twins])
        sr.qty = (sr.qty or 0) + len(twins)
        for tw in twins:
            self._did(tw, sr.step_key, sr.made_at, source, {})

    def _did(self, tw: M.Twin, key: str, on: str, source: str, x: dict) -> None:
        self.done[tw.id].add(key)
        row = {"on": on, "by": SOURCE_TEXT.get(source, source)}
        if x.get("run"):
            row["run"] = x["run"]
        if x.get("dv"):
            row["dv"] = x["dv"]
        if (x.get("factor") or 1) > 1:
            row["copies"] = x["factor"]
        self.when[tw.id][key] = row
        if x.get("at") and (tw.id not in self.last_at or x["at"] > self.last_at[tw.id]):
            self.last_at[tw.id] = x["at"]

    def grouped(self, step: dict, rows: list[tuple[M.Twin, dict, str, str]], note: str) -> int:
        """Clicks for (twin, extra, day, source) rows: one per day, deployment
        version and source. Returns the units recorded."""
        groups: dict[tuple, list] = defaultdict(list)
        for tw, x, day, source in rows:
            groups[(day or self.d0, x.get("dv") or 0, source)].append((tw, x))
        key = step["key"]
        for (day, _dv, source), members in sorted(groups.items(), key=lambda g: (g[0][0], g[0][1], g[0][2])):
            consumes, auto = self._consumes(key, source)
            text = SOURCE_TEXT.get(source, source)
            self.click(step, members, day, f"rebuilt: {text}{note}", source, consumes=consumes, auto=auto)
        return len(rows)

    def _consumes(self, key: str, source: str) -> tuple[bool, bool]:
        """(whether the click used OUR parts, whether its missing parts are
        drawn without a statement). A bench took its parts from our stock; a
        stated step did when it is in `draw`, or when the batch drew its parts."""
        if source in ("bench", "produced"):
            return True, True
        if source == "draws":
            return True, False
        ours = key in self.draw or self.has_draws(key)
        return ours, key in self.draw

    def has_draws(self, key: str) -> bool:
        return bool(self.draws_for.get(key)) or key in self.linked_draw_steps

    # ------------------------------------------------------------------ run

    def execute(self) -> dict:
        db, run = self.db, self.run
        reg_before = run_actuals.invoice_register(db)
        all_devices = (db.query(M.DeviceUnit).filter_by(production_run_id=run.id)
                       .order_by(M.DeviceUnit.id).all())
        allowed = {d.id for d in all_devices}
        produced_ev = _events(db, list(allowed), "produced")
        self.produced_ev = produced_ev
        self.produced = {did: _day(ev.at) for did, ev in produced_ev.items()}
        first = min((p for p in self.produced.values() if p), default="")
        self.d0 = min([x for x in (_iso(run.run_date), first) if x] or [T._today()])
        has_twin = {d for (d,) in db.query(M.Twin.device_unit_id)
                    .filter(M.Twin.device_unit_id.in_(allowed or {-1})).all()}
        skipped = [d for d in all_devices if d.id in has_twin]
        devices = [d for d in all_devices if d.id not in has_twin]
        self.dev = {d.id: d for d in devices}
        self.stated = {k: _selector(db, raw, allowed, f"assume {k!r}") for k, raw in self.stated_raw.items()}
        self.active = (_selector(db, self.active_raw, allowed, "active")
                       if self.active_raw is not None else None)
        self.origins: list[tuple[M.ProductionRun | None, _Devices]] = []
        for i, o in enumerate(self.origins_raw):
            src = None
            if o.get("from_run_id"):
                src = db.get(M.ProductionRun, int(o["from_run_id"]))
                self._check_origin(src, int(o["from_run_id"]))
            self.origins.append((src, _selector(db, o, allowed, f"origins[{i}]")))
        self.batch_ids = {run.id} | {src.id for src, _s in self.origins if src is not None}
        total_before = sum(_total(reg_before, b) for b in self.batch_ids)
        self.bench = _bench(db, self.graph, [d.id for d in devices], run)
        run.process_version_id = self.v.id
        found = self._found_naming_this_batch()

        # ---- twins
        named = []
        for d in devices:
            origin, note = self._origin_of(d)
            ev = produced_ev.get(d.id)
            named.append(M.Twin(project_id=run.project_id, origin_run_id=origin, run_id=run.id,
                                process_version_id=self.v.id, device_unit_id=d.id, status=self._status(d),
                                named_at=(ev.at if ev is not None else utcnow()), note=note[:500]))
        shelf: list[tuple[M.Twin, set[str]]] = []
        for spare in self.spares_in:
            for _ in range(int(spare.get("qty") or 0)):
                shelf.append((M.Twin(project_id=run.project_id, origin_run_id=run.id, run_id=run.id,
                                     process_version_id=self.v.id, status="active",
                                     note=(spare.get("note") or "spare found at a stock count")[:500]),
                              set(spare.get("done") or [])))
        if shelf and found["unnamed_active"]:
            self.refuse(f"{found['unnamed_active']} found unit(s) already name {run.label} as their origin "
                        "(entered at a stock count) — enter counted spares one way: rebuild spares, "
                        "and undo the found entry first", found=found)
        db.add_all(named + [tw for tw, _d in shelf])
        db.flush()
        self.named, self.shelf = named, shelf
        everyone = named + [tw for tw, _d in shelf]

        # ---- the batch's draws and positions
        owner = _input_owner(self.graph)
        self.draws_for: dict[str, list[M.ComponentConsumption]] = defaultdict(list)
        loose_draws: list[M.ComponentConsumption] = []
        for c in (run_actuals.live_consumption(db, run_id=run.id)
                  .filter(M.ComponentConsumption.step_run_id.is_(None)).order_by(M.ComponentConsumption.id).all()):
            if c.basis == "measured":
                self.draws_for[self.akey].append(c)
            elif _key_of_draw(c) in owner:
                self.draws_for[owner[_key_of_draw(c)]].append(c)
            else:
                loose_draws.append(c)
        self.linked_draw_steps: set[str] = set()
        if self.append:
            for sr in db.query(M.StepRun).filter_by(run_id=run.id, chosen=CHOSEN).order_by(M.StepRun.id):
                self.old_clicks[sr.step_key].append(sr)
            linked = {sid for (sid,) in run_actuals.live_consumption(db, run_id=run.id)
                      .filter(M.ComponentConsumption.step_run_id.isnot(None))
                      .with_entities(M.ComponentConsumption.step_run_id).distinct().all()}
            self.linked_draw_steps = {k for k, cs in self.old_clicks.items() if any(c.id in linked for c in cs)}

        # ---- the board's assembly and receipt
        doc_lines = [li for li in T.charged_lines(db, run, unlinked_only=True)
                     if cost_steps.stage_of(li.plan_key) in T.ASSEMBLY_STAGES]
        self._assembly_and_receive(everyone, doc_lines)

        # ---- every other step, in route order
        for key in self.route:
            s = self.smap[key]
            kind = s.get("kind") or "step"
            if kind in ("assembly", "receive", "finish"):
                continue
            if kind == "program":
                self._program(s)
            elif kind in BENCH_KINDS:
                self._bench_step(s)
            else:
                self._plain_step(s)

        # ---- parts against units, then the positions
        self._parts()
        unpaid, loose_lines = self._lines(doc_lines)

        # ---- finish and scrap, from the device records
        lacking = self._finish_and_scrap()
        for tw in everyone:
            tw.stack_key = "|".join(sorted(self.done[tw.id] - {"scrap"}))
        db.flush()

        # ---- the check: the twins carry exactly the batches' money
        check = self._check(total_before)
        orders = T.assembly_orders(db, run)
        panels = jlc_import.effective_panels(db) if orders else {}
        boards = sum((panels.get(code) or {}).get("devices") or 0 for code in orders)
        mine = db.query(func.count(M.Twin.id)).filter(M.Twin.origin_run_id == run.id,
                                                       M.Twin.found.is_(False)).scalar() or 0
        produced_count = run_actuals.produced_counts(db, [run.id]).get(run.id, 0)
        alive_named = [tw for tw in named if tw.status != "scrapped"]
        reg_after = check.pop("_register")
        pr = T.prices(db, alive_named, reg_after) if alive_named else {}
        unit_prices = sorted({p["total_usd"] for p in pr.values()})
        loss = [{"consumption_id": c.id, "step": k, "part": _ref(_key_of_draw(c)), "qty": c.qty,
                 "usd": round((c.qty or 0) * (c.unit_cost_usd or 0), 4)}
                for k, cs in self.draws_for.items() for c in cs
                if c.step_run_id is None and c.voided_at is None and k != self.akey]
        return {
            "run_id": run.id, "batch": run.label, "process_version": self.v.version_no, "append": self.append,
            "twins": len(everyone), "named": len(named), "spares": len(shelf),
            "finished": sum(1 for tw in named if tw.status == "finished"),
            "scrapped": sum(1 for tw in named if tw.status == "scrapped"),
            "active": sum(1 for tw in named if tw.status == "active"),
            "devices_with_a_twin_already": (len(skipped) if self.append
                                            else [d.serial or d.mac or str(d.id) for d in skipped]),
            "boards_from_orders": boards or None,
            "more_units_than_boards": (mine - boards) if boards and mine > boards else 0,
            "found_naming_this_batch": found,
            "origins": [{"from_run_id": src.id if src else None, "from": src.label if src else "unknown",
                         "devices": sel.json(),
                         "twins": sum(1 for tw in named if (src and tw.origin_run_id == src.id))}
                        for src, sel in self.origins],
            "dates": {"before_programming": self.d0, "steps_before_programming": sorted(self.before)},
            "recorded": self.recorded, "not_recorded": self.not_recorded,
            "bench_says_not_done": {k: {"devices": len(v), "first": v[:5]} for k, v in self.says_not.items()},
            "finish_lacks": lacking,
            "no_assembly_invoice": not doc_lines and not self.append,
            "draws_linked": {k: len(v_) for k, v_ in self.draws_for.items()},
            "parts": self.parts, "unsettled": self.unsettled,
            "draws_added": self.added, "draws_returned": self.returned, "returned_low": self.returned_low,
            "returned_lots": self.returned_lots,
            "lines_whose_steps_were_not_recorded": unpaid,
            "left_in_origin": {
                "lines": [{"line_id": li.id, "label": li.label, "plan_key": li.plan_key} for li in loose_lines],
                "draws": [{"consumption_id": c.id, "mpn": c.mpn, "component_id": c.component_id,
                           "basis": c.basis} for c in loose_draws],
                "loss": loss},
            "check": check, "refusals": self.refusals, "can_write": not self.refusals,
            "total_usd": check["total_usd"], "carried_usd": check["carried_usd"],
            "device_cost_before_usd": (round(_total(reg_before, run.id) / produced_count, 4)
                                       if produced_count else None),
            "device_cost_after_usd": (unit_prices[0] if len(unit_prices) == 1
                                      else unit_prices[:1] + unit_prices[-1:]),
            "origin": T.origin_shares(db, [run.id], reg_after).get(run.id),
            "devices": self._device_plan(named, pr),
            "spare_units": [{"qty": int(sp.get("qty") or 0), "done": sorted(set(sp.get("done") or [])
                                                                             | {self.akey, self.rkey}),
                             "note": sp.get("note") or ""} for sp in self.spares_in],
        }

    def refuse(self, message: str, **extra) -> None:
        self.refusals.append({"message": message, **extra})

    def _check_origin(self, src: M.ProductionRun | None, rid: int) -> None:
        run = self.run
        if src is None or src.project_id != run.project_id:
            raise HTTPException(404, f"origins: no batch {rid} in this project")
        if src.id == run.id:
            raise HTTPException(422, "origins: a batch is not its own other batch — leave its devices out")
        if src.closed_at is not None:
            raise HTTPException(409, f"origins: batch {src.label} is closed — its twins' shares are frozen; "
                                     "reopen it first")
        for kind in ("assembly", "receive"):
            if _rebuilt_click(self.db, src, kind) is None:
                raise HTTPException(409, f"origins: batch {src.label} has no rebuilt {kind} step — rebuild "
                                         f"{src.label} first, then {run.label}")

    def _found_naming_this_batch(self) -> dict:
        """Found twins (entered at a stock count, at zero) that name this batch
        as their origin. Counted spares enter one way only."""
        rows = (self.db.query(M.Twin.run_id, M.Twin.status, M.Twin.device_unit_id.is_(None), func.count(M.Twin.id))
                .filter(M.Twin.origin_run_id == self.run.id, M.Twin.found.is_(True))
                .group_by(M.Twin.run_id, M.Twin.status, M.Twin.device_unit_id.is_(None)).all())
        labels = {r.id: r.label for r in self.db.query(M.ProductionRun)
                  .filter(M.ProductionRun.id.in_({r for r, *_x in rows} or {-1})).all()}
        return {"twins": sum(n for *_x, n in rows),
                "unnamed_active": sum(n for _r, st, unnamed, n in rows if unnamed and st == "active"),
                "where": [{"batch": labels.get(rid), "status": st, "named": not unnamed, "count": n}
                          for rid, st, unnamed, n in rows]}

    def _origin_of(self, d: M.DeviceUnit) -> tuple[int, str]:
        for src, sel in self.origins:
            if sel.takes(d.id, self.produced.get(d.id, "")):
                if src is None:
                    return self.run.id, "rebuilt from the batch records; source batch unknown — the origin is set to this batch"
                return src.id, f"rebuilt from the batch records; built on boards of {src.label}"
        return self.run.id, "rebuilt from the batch records"

    def _status(self, d: M.DeviceUnit) -> str:
        if d.state == "disposed":
            return "scrapped"
        if d.state not in ("in_stock", "returned"):
            return "finished"   # a unit that left us stays finished (decision 0074)
        if (d.condition or "ok") in NOT_FINISHED:
            return "active"
        if self.active is not None and self.active.takes(d.id, self.produced.get(d.id, "")):
            return "active"
        return "finished"

    # ------------------------------------------------------------ the steps

    def _assembly_and_receive(self, everyone: list[M.Twin], doc_lines: list) -> None:
        db, run = self.db, self.run
        mine = [tw for tw in everyone if tw.origin_run_id == run.id]
        moved: dict[int, list[M.Twin]] = defaultdict(list)
        for tw in everyone:
            if tw.origin_run_id != run.id:
                moved[tw.origin_run_id].append(tw)
        astep, rstep = self.smap[self.akey], self.smap[self.rkey]
        orders = T.assembly_orders(db, run)
        if self.append:
            asr, rsr = _rebuilt_click(db, run, "assembly"), _rebuilt_click(db, run, "receive")
            self.join(asr, mine)
            self.join(rsr, mine)
            for c in self.draws_for.get(self.akey, []):
                c.step_run_id = asr.id
            self.old_clicks[self.akey] = [asr]
            evidence = "joined the batch's rebuilt assembly"
        else:
            # An old batch's invoice can be dated after its boards arrived (a
            # re-invoice): the assembly happened by the earliest of the three.
            dates = sorted(d for d in (_iso(db.get(M.RunCostDocument, li.document_id).doc_date)
                                       for li in doc_lines) if d)
            when = min([self.d0] + dates[:1])
            asr = self.click(astep, [(tw, {}) for tw in mine], when,
                             f"rebuilt: assembly order {', '.join(orders)}" if orders
                             else "rebuilt: the batch's board and assembly invoices", "batch")
            if asr is not None:
                for c in self.draws_for.get(self.akey, []):
                    c.step_run_id = asr.id
            self.click(rstep, [(tw, {}) for tw in mine], self.d0, "rebuilt: the batch's records", "batch")
            evidence = ("invoices" if doc_lines else
                        "the supplier's measured draws" if self.draws_for.get(self.akey) else "the batch")
        for oid, tws in moved.items():
            src = db.get(M.ProductionRun, oid)
            self.join(_rebuilt_click(db, src, "assembly"), tws)
            self.join(_rebuilt_click(db, src, "receive"), tws)
        self.recorded.append({"step": self.akey, "units": len(everyone), "evidence": evidence,
                              "from_other_batches": sum(len(x) for x in moved.values())})
        self.recorded.append({"step": self.rkey, "units": len(everyone), "evidence": "the batch"})

    def _after_day(self, tw: M.Twin) -> str:
        """The day a step after programming is dated on a device without a
        bench record: its programming day."""
        return self.produced.get(tw.device_unit_id or 0) or self.d0

    def _record(self, s: dict, rows: list, extra: dict | None = None) -> None:
        key = s["key"]
        by: dict[str, int] = defaultdict(int)
        for *_x, source in rows:
            by[SOURCE_TEXT.get(source, source)] += 1
        clicks = self.new_clicks.get(key, [])
        self.recorded.append({"step": key, "label": s.get("label") or key, "units": len(rows),
                              "evidence": " + ".join(sorted(by)), "by": dict(by), "clicks": len(clicks),
                              "days": len({c.made_at for c in clicks}), **(extra or {})})

    def _program(self, s: dict) -> None:
        rows = []
        for tw in self.named:
            did = tw.device_unit_id
            if not self.produced.get(did):
                continue
            fr = self.bench["flash"].get(did) or {}
            rows.append((tw, {"run": fr.get("run"), "dv": fr.get("dv"), "at": self._produced_at(did)},
                         self.produced[did], "produced"))
        self.grouped(s, rows, "")
        missing = sum(1 for tw in self.named if not self.produced.get(tw.device_unit_id))
        self._record(s, rows, {"no_produced_event": missing} if missing else None)

    def _bench_step(self, s: dict) -> None:
        key = s["key"]
        sel = self.stated.get(key)
        rows = []
        for tw in self.named:
            did = tw.device_unit_id
            ev = self.bench["evidence"].get((did, key))
            if ev is not None:
                rows.append((tw, {"run": ev["run"], "dv": ev["dv"], "at": ev["at"], "factor": ev["copies"]},
                             ev["on"], "bench"))
            elif (did, key) in self.bench["record"]:
                d = self.dev[did]
                self.says_not[key].append(f"{d.serial or d.mac or did}: {self.bench['record'][(did, key)][0]}")
            elif sel is not None and sel.takes(did, self.produced.get(did, "")):
                rows.append((tw, {"at": self._produced_at(did)}, self._after_day(tw), "stated"))
        rows += [(tw, {}, self.d0, "stock") for tw, ds in self.shelf if key in ds]
        if not rows:
            self.not_recorded.append({"step": key, "label": s.get("label") or key,
                                      "why": ("no device matches the statement" if sel is not None
                                              else "no bench run proves it, and it is not stated")})
            return
        self.grouped(s, rows, "")
        self._record(s, rows, {"stated": sel.json()} if sel is not None else None)

    def _plain_step(self, s: dict) -> None:
        key = s["key"]
        sel = self.stated.get(key)
        before = key in self.before
        rows = []
        if sel is not None:
            for tw in self.named:
                did = tw.device_unit_id
                if sel.takes(did, self.produced.get(did, "")):
                    rows.append((tw, {"at": None if before else self._produced_at(did)},
                                 self.d0 if before else self._after_day(tw), "stated"))
        elif self.has_draws(key):
            rows = [(tw, {"at": None if before else self._produced_at(tw.device_unit_id)},
                     self.d0 if before else self._after_day(tw), "draws") for tw in self.named]
        rows += [(tw, {}, self.d0, "stock") for tw, ds in self.shelf if key in ds]
        if not rows:
            self.not_recorded.append({"step": key, "label": s.get("label") or key,
                                      "why": ("no device matches the statement" if sel is not None
                                              else "no draw and not stated — an invoice is money, not "
                                                   "proof per unit")})
            return
        self.grouped(s, rows, "")
        self._record(s, rows, {"stated": sel.json()} if sel is not None else None)

    def _produced_at(self, device_id: int | None) -> datetime | None:
        ev = self.produced_ev.get(device_id or 0)
        return ev.at if ev is not None else None

    # ------------------------------------------------------------ the parts

    def _per_unit(self, s: dict, drawn: set) -> tuple[dict, dict]:
        """Part key → what one unit of the step takes, and the input naming it.
        A prepared part the batch never drew counts as its recipe's parts when
        the batch drew those (the old batches drew the enclosure and the
        antenna, not the glued body)."""
        recipes = {int(r["output_component_id"]): r for r in self.graph.get("prepared") or []
                   if r.get("output_component_id")}
        out: dict = defaultdict(float)
        inputs: dict = {}
        if (s.get("kind") or "step") in P.NO_INPUT_KINDS:
            return {}, {}
        for inp in s.get("inputs") or []:
            k, q = _key_of_input(inp), float(inp.get("qty") or 0)
            cid, _m = P.input_ref(inp)
            rec = recipes.get(cid) if cid else None
            if rec and k not in drawn and any(_key_of_input(r) in drawn for r in rec.get("inputs") or []):
                for r in rec.get("inputs") or []:
                    rk = _key_of_input(r)
                    out[rk] += q * float(r.get("qty") or 0)
                    inputs.setdefault(rk, r)
            else:
                out[k] += q
                inputs.setdefault(k, inp)
        return dict(out), inputs

    def _parts(self) -> None:
        """Per step and part: drawn against units x quantity. The batch's draws
        are poured into the step's clicks, oldest draw into the earliest click,
        and a draw that spans two clicks is split. Then each difference is
        settled as the person stated, or reported."""
        missing: dict[int, list[tuple]] = defaultdict(list)
        for key in self.route:
            if key == self.akey:
                continue
            s = self.smap[key]
            rows = self.draws_for.get(key, [])
            per_unit, inputs = self._per_unit(s, {_key_of_draw(c) for c in rows})
            if not per_unit and not rows:
                continue
            by_key: dict = defaultdict(list)
            for c in rows:
                by_key[_key_of_draw(c)].append(c)
            clicks = [sr for sr in self.new_clicks.get(key, []) if self.info[sr.id]["consumes"]]
            for pk in sorted(set(per_unit) | set(by_key), key=str):
                mine = sorted(by_key.get(pk, []), key=lambda c: (c.consumed_at or "", c.id))
                needs = [(sr, self.info[sr.id]["factor"] * per_unit.get(pk, 0.0), self.info[sr.id]["auto"])
                         for sr in clicks]
                drawn = sum(c.qty or 0 for c in mine)
                need = sum(n for _sr, n, _a in needs)
                if drawn <= EPS and need <= EPS:
                    continue
                how = self.settle.get((key, _ref(pk))) or self.settle.get((key, "*"))
                surplus = drawn - need if drawn - need > EPS else 0.0
                returned_usd = 0.0
                if surplus and how == "return":
                    returned_usd = self._return(key, pk, mine, surplus)
                    mine = [c for c in mine if c.voided_at is None]
                rem = self._pour(mine, [sr for sr, _n, _a in needs], [n for _sr, n, _a in needs])
                auto_short = sum(r for (_sr, _n, a), r in zip(needs, rem) if a and r > EPS)
                manual_short = sum(r for (_sr, _n, a), r in zip(needs, rem) if not a and r > EPS)
                to_draw = 0.0
                for (sr, _n, a), r in zip(needs, rem):
                    if r > EPS and ((a and how != "short") or how == "draw"):
                        missing[sr.id].append((s, pk, r, inputs.get(pk)))
                        to_draw += r
                left = sum(c.qty or 0 for c in mine if c.step_run_id is None)
                row = {"step": key, "part": _ref(pk), "name": self._name(pk, inputs.get(pk), mine),
                       "per_unit": per_unit.get(pk, 0.0), "units": sum(self.info[sr.id]["factor"] for sr in clicks),
                       "need": round(need, 6), "drawn": round(drawn, 6), "surplus": round(surplus, 6),
                       "deficit": round(auto_short + manual_short, 6), "settled": how,
                       "drawn_now": round(to_draw, 6), "returned_usd": round(returned_usd, 4),
                       "left_in_origin": round(left, 6)}
                why = []
                if surplus > self.tol + EPS and how not in FOR_SURPLUS:
                    why.append(f"{round(surplus, 6):g} more drawn than {round(need, 6):g} needed — state "
                               "'return' or 'loss'")
                if manual_short > self.tol + EPS and how not in FOR_DEFICIT:
                    why.append(f"{round(manual_short, 6):g} fewer drawn than needed — state 'draw' or 'short'")
                if why:
                    row["why"] = "; ".join(why)
                    self.unsettled.append(row)
                self.parts.append(row)
        if self.unsettled:
            self.refuse(f"{len(self.unsettled)} difference(s) between drawn and needed parts have no "
                        f"statement (first: {self.unsettled[0]['step']} {self.unsettled[0]['part']}: "
                        f"{self.unsettled[0]['why']})")
        for srid, items in missing.items():
            self._draw_missing(self.db.get(M.StepRun, srid), items)

    def _name(self, pk, inp, mine) -> str:
        if pk[0] == "c":
            return (P._part_names(self.db, {pk[1]}).get(pk[1]) or {}).get("name") or _ref(pk)
        return (inp or {}).get("mpn") or (mine[0].mpn if mine else "") or _ref(pk)

    def _pour(self, draws: list[M.ComponentConsumption], clicks: list[M.StepRun],
              needs: list[float]) -> list[float]:
        """Link `draws` to `clicks` in order until each click holds what it
        needs; what is left stays unlinked. Returns what each click still lacks."""
        rem = list(needs)
        i = 0
        for c in draws:
            q = c.qty or 0.0
            while q > EPS and i < len(rem):
                if rem[i] <= EPS:
                    i += 1
                    continue
                if rem[i] >= q - EPS:
                    c.step_run_id = clicks[i].id
                    rem[i] -= q
                    q = 0.0
                else:
                    piece = self._split(c, rem[i])
                    piece.step_run_id = clicks[i].id
                    q -= rem[i]
                    rem[i] = 0.0
        return [max(r, 0.0) for r in rem]

    def _split(self, c: M.ComponentConsumption, qty: float) -> M.ComponentConsumption:
        """A piece of `qty` cut off draw `c`, at the same unit cost, with its
        share of each lot binding: the value of the two adds up to the draw's."""
        db = self.db
        whole = c.qty or 0.0
        piece = M.ComponentConsumption(
            run_id=c.run_id, component_id=c.component_id, mpn=c.mpn or "", lcsc=c.lcsc or "", qty=round(qty, 6),
            unit_cost_usd=c.unit_cost_usd, basis=c.basis, import_ref="", consumed_at=c.consumed_at,
            note=(f"rebuilt: piece of draw #{c.id}" + (f" — {c.note}" if c.note else ""))[:500],
            company_id=c.company_id, transformation_id=c.transformation_id)
        db.add(piece)
        db.flush()
        share = qty / whole if whole else 0.0
        for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id).order_by(
                M.ComponentConsumptionLot.id).all():
            q = round((b.qty or 0.0) * share, 6)
            if q <= 0:
                continue
            db.add(M.ComponentConsumptionLot(consumption_id=piece.id, lot_line_id=b.lot_line_id,
                                             lot_adjustment_id=b.lot_adjustment_id, qty=q,
                                             unit_cost_usd=b.unit_cost_usd, source=b.source, ext_ref=b.ext_ref,
                                             note=b.note))
            b.qty = round((b.qty or 0.0) - q, 6)
        c.qty = round(whole - qty, 6)
        db.flush()
        return piece

    def _return(self, key: str, pk, draws: list[M.ComponentConsumption], surplus: float) -> float:
        """Give the surplus back to the stock, newest draw first: a draw is made
        smaller (its newest lot bindings go back, `lots.resize_bound`, whatever
        the lot pricing switch says), or voided when all of it goes back.
        Returns the value that left the batch."""
        db, run = self.db, self.run
        left, value = surplus, 0.0
        scope = run_actuals.run_scope(db, run)
        # What the pool was before the return, day by day: "Undo rebuild" may
        # take it no lower than that on any day, whatever was drawn, raised or
        # cut since (decision 0075). Every name the part has, so a draw named
        # by its MPN and one by its component id are one part.
        db.flush()
        ref = _ref(pk)
        if ref not in self.returned_low and draws:
            keys = set()
            for d in draws:
                keys |= set(run_actuals._identity_keys(d.component_id, d.mpn or "", d.lcsc or ""))
            ctx = _CANON.get()
            for e in (ctx[0] if ctx else []):
                ek = set(run_actuals._identity_keys(e.get("component_id"), e.get("mpn") or "", e.get("lcsc") or ""))
                if ek & keys:
                    keys |= ek
            cs = run_actuals.stock_scope(db, draws[0].company_id)
            since = min((d.consumed_at or "") for d in draws)
            self.returned_low[ref] = {"keys": sorted(keys), "company": cs, "since": since,
                                      "series": run_actuals.pool_series(run_actuals._pool_events(db, cs)[0], keys, since)}
        # The same for each lot the return gives units back to: the undo may
        # take it no lower than it was (decision 0073). Only those lots: one
        # the return leaves alone keeps the undo's own floor.
        def bound_by_lot() -> dict[str, float]:
            out: dict[str, float] = defaultdict(float)
            for b in db.query(M.ComponentConsumptionLot).filter(
                    M.ComponentConsumptionLot.consumption_id.in_([d.id for d in draws] or [-1])).all():
                out[L._lot_key("L", b.lot_line_id) if b.lot_line_id else L._lot_key("A", b.lot_adjustment_id)] += \
                    b.qty or 0.0
            return out

        held_before = bound_by_lot()
        state_before = L.lot_state(db)["lots"] if set(held_before) - set(self.returned_lots) else {}
        for c in sorted(draws, key=lambda c: (c.consumed_at or "", c.id), reverse=True):
            if left <= EPS:
                break
            take = min(c.qty or 0.0, left)
            before = (c.qty or 0.0) * (c.unit_cost_usd or 0.0)
            new = round((c.qty or 0.0) - take, 6)
            if new <= EPS:
                for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id).all():
                    db.delete(b)
                c.voided_at = utcnow()
                c.void_reason = RETURNED
                after = 0.0
            else:
                problems = L.resize_bound(db, c, new, as_of=c.consumed_at or run.run_date or "", company_id=scope)
                if problems:   # only an increase can fail; this is a decrease
                    raise HTTPException(409, f"{run.label}: returning the surplus failed: {problems[0]['problem']}")
                c.qty = new
                after = new * (c.unit_cost_usd or 0.0)
            value += before - after
            left -= take
            self.returned.append({"step": key, "part": _ref(pk), "consumption_id": c.id, "qty": round(take, 6),
                                  "usd": round(before - after, 4)})
        db.flush()
        held_after = bound_by_lot()
        for k, q in held_before.items():
            if k in state_before and k not in self.returned_lots and held_after.get(k, 0.0) < q - EPS:
                self.returned_lots[k] = state_before[k]["qty_remaining"]
        return value

    def _draw_missing(self, sr: M.StepRun, items: list[tuple]) -> None:
        """Write a click's missing parts from the stock at the click's date,
        bound to lots like every step draw; refused when the stock did not hold
        them then."""
        db, run = self.db, self.run
        s = items[0][0]
        label = s.get("label") or s["key"]
        inputs = []
        for _s, pk, qty, inp in items:
            cid, mpn = P.input_ref(inp or {})
            ref = {"component_id": cid} if cid else {"mpn": mpn or str(pk[1])}
            inputs.append({**ref, "qty": qty})
        pseudo = {"key": s["key"], "label": label, "kind": s.get("kind") or "step", "inputs": inputs}
        planned, problems, _tok = T._plan_draws(db, run, pseudo, 1, sr.made_at, None)
        short = run_actuals.check_shortages(db, [
            {"component_id": d["component_id"], "mpn": d.get("mpn", ""), "lcsc": "", "qty": d["qty"],
             "date": sr.made_at, "label": d["name"]} for d in planned if not d["internal"]],
            company_id=run_actuals.run_scope(db, run))
        if problems or short:
            what = problems[0]["problem"] if problems else ", ".join(
                f"{x.get('label') or x.get('mpn')} short {x.get('short')}" for x in short[:4])
            self.refuse(f"{run.label}: {label!r} cannot draw its parts on {sr.made_at} ({what}) — book the "
                        "purchase first, or state 'short'", step=s["key"], click_date=sr.made_at,
                        shortages=short, problems=problems)
            return
        T.write_draws(db, run, sr, planned, f"rebuilt: {sr.step_label} x {sr.qty}, from our stock")
        for d in planned:
            self.added.append({"step": s["key"], "part": d["name"], "qty": d["qty"], "usd": d["value_usd"],
                               "made_at": sr.made_at})

    # ------------------------------------------------------------ positions

    def _lines(self, doc_lines: list) -> tuple[list[dict], list]:
        db, run = self.db, self.run
        line_steps: list[tuple[M.RunCostLine, list[str]]] = []
        loose: list[M.RunCostLine] = []
        for li in T.charged_lines(db, run, unlinked_only=True):
            if cost_steps.stage_of(li.plan_key) in T.ASSEMBLY_STAGES:
                line_steps.append((li, [self.akey]))
            elif li.plan_key in self.costs:
                line_steps.append((li, self.costs[li.plan_key]))
            else:
                loose.append(li)
        unpaid = []
        for li, keys in line_steps:
            clicks = [c for k in keys for c in self.old_clicks.get(k, []) + self.new_clicks.get(k, [])
                      if c.qty and c.kind != "scrap"]
            if clicks:
                T.link_line(db, li, clicks)
                # A whole step: the clicks of it recorded later pay too (0074).
                T.link_keys(db, li, run, keys)
            else:
                loose.append(li)
                unpaid.append({"line_id": li.id, "label": li.label, "steps": keys})
        if self.append:
            # A position that paid for a step of this batch pays for the new
            # clicks of that step too (decision 0061: every click of the step).
            mine = {sr.id: sr for cs in self.old_clicks.values() for sr in cs}
            for li in T.charged_lines(db, run):
                have = [db.get(M.StepRun, sid) for (sid,) in
                        db.query(M.CostLineStep.step_run_id).filter_by(line_id=li.id).all()]
                keys = {sr.step_key for sr in have if sr is not None and sr.id in mine}
                add = [c for k in keys if k not in (self.akey, self.rkey) for c in self.new_clicks.get(k, [])]
                if add:
                    T.link_line(db, li, [sr for sr in have if sr is not None] + add)
        db.flush()
        return unpaid, loose

    # -------------------------------------------------------- finish, scrap

    def _finish_and_scrap(self) -> list[str]:
        db = self.db
        terms = P.required_terms(self.graph)
        groups = P.groups_of(self.graph)

        def lacks(tw: M.Twin) -> list[str]:
            got = self.done[tw.id]
            return [t for t in terms if t not in got and not any(m in got for m in groups.get(t, []))]

        fstep = P.step_of_kind(self.graph, "finish")
        finished = [tw for tw in self.named if tw.status == "finished"]
        by_day: dict[str, list[M.Twin]] = defaultdict(list)
        for tw in finished:
            days = [x["on"] for x in self.when[tw.id].values() if x.get("on")]
            by_day[max(days + [self.produced.get(tw.device_unit_id, "")]) or self.d0].append(tw)
        all_lacking: set[str] = set()
        for day in sorted(by_day):
            miss = sorted({t for tw in by_day[day] for t in lacks(tw)})
            all_lacking |= set(miss)
            self.click(fstep, [(tw, {}) for tw in by_day[day]], day,
                       "rebuilt: finished per the device record" + (f"; no record of {', '.join(miss)}" if miss else ""),
                       "batch")
        for tw in finished:
            tw.finished_at = self.last_at.get(tw.id) or self._produced_at(tw.device_unit_id)
        scrapped = [tw for tw in self.named if tw.status == "scrapped"]
        disposed = _events(db, [tw.device_unit_id for tw in scrapped], "disposed", last=True)
        by_day = defaultdict(list)
        for tw in scrapped:
            ev = disposed.get(tw.device_unit_id)
            days = [x["on"] for x in self.when[tw.id].values() if x.get("on")]
            by_day[(_day(ev.at) if ev is not None else (max(days) if days else self.d0), ev is None)].append(tw)
            tw.scrapped_at = ev.at if ev is not None else None
        for (day, undated), tws in sorted(by_day.items()):
            self.click({"key": "scrap", "label": "Scrapped", "kind": "scrap"}, [(tw, {}) for tw in tws], day,
                       "rebuilt: disposed per the device record"
                       + ("; the record keeps no disposal date" if undated else ""), "batch")
        self._lacks = {tw.id: lacks(tw) for tw in self.named}
        return sorted(all_lacking)

    # ------------------------------------------------------------ the check

    def _check(self, total_before: float) -> dict:
        db = self.db
        reg = run_actuals.invoice_register(db)
        total_after = sum(_total(reg, b) for b in self.batch_ids)
        added = sum(d["usd"] for d in self.added)
        returned = sum(d["usd"] for d in self.returned)
        moved = total_after - total_before
        carried, outside, n = _carried(db, self.batch_ids, reg)
        out = {"batches": sorted(self.batch_ids), "total_before_usd": round(total_before, 4),
               "total_usd": round(total_after, 4), "moved_usd": round(moved, 4),
               "drawn_usd": round(added, 4), "returned_usd": round(returned, 4),
               "carried_usd": round(carried - outside, 4), "from_other_batches_usd": round(outside, 4),
               "twins": n, "ok": True, "_register": reg}
        # A batch's total moves by the draws the rebuild wrote and the surplus
        # it returned, and by nothing else.
        if abs(moved - added + returned) > TOTAL_EPS:
            out["ok"] = False
            self.refuse(f"rebuilding {self.run.label} moved {round(moved, 4)} USD, and only the "
                        f"{round(added - returned, 4)} USD of written and returned draws may move")
        # Each price is rounded to 4 decimals, so the sum may stray by half a
        # unit of the last place per twin on top of the fixed tolerance.
        elif n and abs(carried - outside - total_after) > TOTAL_EPS + 0.00005 * n:
            out["ok"] = False
            self.refuse(f"the twins of {self.run.label} carry {round(carried - outside, 4)} USD, the "
                        f"batch{'es' if len(self.batch_ids) > 1 else ''} cost {round(total_after, 4)} USD")
        return out

    # -------------------------------------------------------- the per-device plan

    def _device_plan(self, named: list[M.Twin], prices: dict) -> list[dict]:
        dvs = _dv_labels(self.db, {x["dv"] for tw in named for x in self.when[tw.id].values() if x.get("dv")})
        order = {k: i for i, k in enumerate([self.akey, self.rkey] + self.route + ["scrap"])}
        labels = {r.id: r.label for r in self.db.query(M.ProductionRun)
                  .filter(M.ProductionRun.id.in_({tw.origin_run_id for tw in named} or {-1})).all()}
        out = []
        for tw in named:
            d = self.dev[tw.device_unit_id]
            steps = {}
            for k in sorted(self.when[tw.id], key=lambda k: order.get(k, len(order))):
                row = dict(self.when[tw.id][k])
                if row.get("dv"):
                    row["version"] = dvs.get(row["dv"])
                steps[k] = row
            item = {"device_id": d.id, "serial": d.serial or None, "mac": d.mac, "produced": self.produced.get(d.id)
                    or None, "status": tw.status, "origin": labels.get(tw.origin_run_id), "steps": steps,
                    "lacks": self._lacks.get(tw.id, []) if tw.status != "scrapped" else []}
            notes = [f"{k}: {v[0]}" for (did, k), v in self.bench["record"].items()
                     if did == d.id and k not in self.when[tw.id]]
            if notes:
                item["bench_says_not_done"] = notes
            if tw.id in prices:
                item["price_usd"] = prices[tw.id]["total_usd"]
            out.append(item)
        return out


# ===================================================================== undo

def undo(db: Session, run: M.ProductionRun, *, actor: str = "", dry_run: bool = True) -> dict:
    """Take a rebuild back: first the live clicks that stand on its twins
    (newest first — a crafting click by reversing its journal batch, a bench
    click by deleting it with its draws), then the rebuild's own journal
    batches, then a rebuild made before the journal. The dry run is the same
    code path in a savepoint and lists every click it takes back; a click it
    cannot take back is refused by name."""
    from . import jlc_apply

    T._refuse_closed(run)   # its shares are frozen, and its draws are in closed books
    sp = db.begin_nested()
    try:
        plan = _undo(db, run, actor)
    except jlc_apply.ApplyRefused as e:
        # `journal.reverse` rolled the session back already: nothing was kept.
        raise HTTPException(409, f"the rebuild of {run.label} cannot be undone: {e}") from e
    except Exception:
        if sp.is_active:
            sp.rollback()
        raise
    plan["dry_run"] = dry_run
    if dry_run or plan["refused"]:
        sp.rollback()
        db.expire_all()
        if plan["refused"] and not dry_run:
            raise HTTPException(409, {"error": f"the rebuild of {run.label} cannot be undone: "
                                               f"{plan['refused'][0]}", "plan": plan})
    else:
        sp.commit()
    return plan


def _live_batches(db: Session, table: str, row_ids: list[int]) -> dict[int, int]:
    """Row id → the live journal batch that inserted it. A row an undo put
    back has two such batches: the one that wrote it is the one to reverse,
    not the reversal (the Write log redoes no crafting click)."""
    if not row_ids:
        return {}
    out: dict[int, tuple[int, str]] = {}
    for rid, bid, kind in (db.query(M.WriteBatchRow.row_id, M.WriteBatch.id, M.WriteBatch.kind)
                           .join(M.WriteBatch, M.WriteBatch.id == M.WriteBatchRow.batch_id)
                           .filter(M.WriteBatchRow.table_name == table, M.WriteBatchRow.op == "insert",
                                   M.WriteBatchRow.row_id.in_(row_ids), M.WriteBatch.reversed_at.is_(None))
                           .order_by(M.WriteBatch.id).all()):
        cur = out.get(rid)
        if cur is None or (cur[1] == "reverse" and (kind != "reverse" or bid > cur[0])):
            out[rid] = (bid, kind)
    return {rid: bid for rid, (bid, _k) in out.items()}


def _link_undo(db: Session, batch_id: int | None) -> bool:
    """A Write-log undo of a cost link or unlink (only link rows). A row it
    put back is judged by who first wrote it: with no other live writer, the
    rebuild's key wrote it, and "Undo rebuild" takes it away; a person's
    live link stays. Such an undo is never itself redone here: it acts on a
    whole position, not on what stands on the rebuild."""
    wb = db.get(M.WriteBatch, batch_id) if batch_id else None
    if wb is None or wb.kind != "reverse" or any(
            r.table_name not in ("cost_line_steps", "cost_line_step_keys") for r in wb.rows):
        return False
    fwd = wb
    while fwd is not None and fwd.kind == "reverse":
        fwd = db.get(M.WriteBatch, (fwd.summary or {}).get("reverses") or 0)
    return fwd is not None and fwd.kind == "craft.costs"


def _line_and_below(db: Session, line_id: int) -> set[int]:
    """A position and every line under it, voided ones too."""
    out, frontier = {line_id}, [line_id]
    while frontier:
        frontier = [i for (i,) in db.query(M.RunCostLine.id).filter(M.RunCostLine.parent_line_id.in_(frontier))
                    if i not in out]
        out.update(frontier)
    return out


def _undo(db: Session, run: M.ProductionRun, actor: str) -> dict:
    clicks = db.query(M.StepRun).filter_by(run_id=run.id, chosen=CHOSEN).all()
    ids = [c.id for c in clicks]
    twins = (db.query(M.Twin).join(M.TwinStep, M.TwinStep.twin_id == M.Twin.id)
             .filter(M.TwinStep.step_run_id.in_(ids or [-1]), M.Twin.found.is_(False)).distinct().all())
    tids = {tw.id for tw in twins}
    plan: dict = {"run_id": run.id, "clicks": len(ids), "twins": len(tids), "takes_back": [],
                  "rebuild_batches": [], "before_the_journal": False, "refused": []}
    # Its own journal batches, an append that wrote no click included.
    rebuild_batches = sorted((b for (b,) in db.query(M.WriteBatch.id)
                              .filter(M.WriteBatch.kind == "craft.rebuild", M.WriteBatch.source_ref == f"run:{run.id}",
                                      M.WriteBatch.reversed_at.is_(None)).all()), reverse=True)
    plan["rebuild_batches"] = rebuild_batches
    # Every other batch it touched — an `origins` batch's rebuilt clicks, a
    # moved twin's origin — must be open too: their shares are frozen at close.
    touched = {sr.run_id for b in rebuild_batches for r in db.get(M.WriteBatch, b).rows
               if r.table_name == "step_runs" and (sr := db.get(M.StepRun, r.row_id)) is not None}
    touched |= {tw.origin_run_id for tw in twins}
    for rid in sorted(touched - {run.id}):
        other = db.get(M.ProductionRun, rid)
        if other is not None and other.closed_at is not None:
            plan["refused"].append(f"batch {other.label} is closed, and this rebuild changed its clicks or "
                                   "twins — reopen it first")
    # The live clicks on the rebuilt twins: a bench click (no journal batch)
    # and every crafting write that depends on the rebuild.
    live = (db.query(M.StepRun).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
            .filter(M.TwinStep.twin_id.in_(tids or {-1}), M.StepRun.chosen != CHOSEN).distinct().all())
    live_batch = _live_batches(db, "step_runs", [sr.id for sr in live])
    items: list[tuple] = []          # (when, kind, object)
    for sr in live:
        if sr.id in live_batch:
            continue
        home = db.get(M.ProductionRun, sr.run_id)
        if sr.chosen == "bench" or _disposal_scrap(sr):
            if home is not None and home.closed_at is not None and home.id != run.id:
                plan["refused"].append(f"click #{sr.id} ({sr.step_label}) is in closed batch {home.label} "
                                       "— reopen it first")
                continue
            items.append((sr.created_at, "bench", sr))
        else:
            plan["refused"].append(f"click #{sr.id} ({sr.step_label}, {sr.chosen}, {sr.made_at}) is no bench "
                                   "click and has no live journal batch to reverse — take it back first "
                                   "(a scrap from a disposal is one)")
    deps: set[int] = set(live_batch.values())
    todo = list(rebuild_batches) + sorted(deps)
    seen: set[int] = set()
    while todo:
        b = todo.pop()
        if b in seen:
            continue
        seen.add(b)
        wb = db.get(M.WriteBatch, b)
        for later in journal.check_reversible(db, wb, stock=False)["blocking_batches"]:
            if later not in rebuild_batches:
                deps.add(later)
                todo.append(later)
    def dep_refusal(wb: M.WriteBatch) -> str | None:
        if wb.kind == "craft.rebuild":
            other = db.get(M.ProductionRun, int((wb.source_ref or "run:0").split(":", 1)[1] or 0))
            return (f"the rebuild of {other.label if other else wb.source_ref} (journal batch "
                    f"#{wb.id}) took twins built on this batch's boards — undo it first")
        if not (wb.kind or "").startswith("craft."):
            return (f"journal batch #{wb.id} ({wb.kind}, {wb.source_ref}) depends on the rebuild "
                    "and is not a crafting click — reverse it on the Ledger first")
        return None

    for b in deps:
        wb = db.get(M.WriteBatch, b)
        why = dep_refusal(wb)
        if why:
            plan["refused"].append(why)
            continue
        items.append((wb.created_at, "batch", wb))
    # A cost link a crafting write made on a bench click it takes back: that
    # write is reversed first (newest first), not left with its row gone.
    queued = {obj.id for _w, k, obj in items if k == "batch"} | set(rebuild_batches)
    bench_link_ids = [x for (x,) in db.query(M.CostLineStep.id).filter(M.CostLineStep.step_run_id.in_(
        [obj.id for _w, k, obj in items if k == "bench"] or [-1])).all()]
    for b in sorted(set(_live_batches(db, "cost_line_steps", bench_link_ids).values()) - queued):
        if _link_undo(db, b):
            continue   # what it put back on the click goes with the click; it is never redone here
        wb = db.get(M.WriteBatch, b)
        why = dep_refusal(wb)
        if why:
            plan["refused"].append(why)
            continue
        items.append((wb.created_at, "batch", wb))
    taken = {obj.id for _w, k, obj in items if k == "bench"}
    rebuilt_at = min((db.get(M.WriteBatch, b).created_at for b in rebuild_batches), default=None)
    plan["refused"] += _returned_short(db, run, rebuild_batches + [obj.id for _w, k, obj in items if k == "batch"],
                                       taken, rebuilt_at)
    if plan["refused"]:
        return plan
    # The stock is checked once, over the whole undo (`_returned_short` above):
    # each reversal below skips its own check. The lots the undo binds again
    # are checked the same way, at the end.
    reversed_ids = rebuild_batches + [obj.id for _w, k, obj in items if k == "batch"]
    lots_before = _bound_lots(db, reversed_ids)
    own_links = {r.row_id for b in rebuild_batches for r in db.get(M.WriteBatch, b).rows
                 if r.table_name == "cost_line_steps"}
    for b in rebuild_batches:
        wb = db.get(M.WriteBatch, b)
        for r in wb.rows:
            if r.table_name != "cost_line_step_keys" or r.op != "insert":
                continue
            k = db.get(M.CostLineStepKey, r.row_id)
            if k is None:
                continue
            # The position and the children a split gave it: they carry its key.
            for x, sr in (db.query(M.CostLineStep, M.StepRun).join(M.StepRun, M.StepRun.id == M.CostLineStep.step_run_id)
                          .filter(M.CostLineStep.line_id.in_(_line_and_below(db, k.line_id)),
                                  M.StepRun.run_id == k.run_id,
                                  M.StepRun.step_key == k.step_key, M.CostLineStep.created_at > wb.created_at)
                          .order_by(M.CostLineStep.id).all()):
                if sr.id in taken or sr.id in live_batch or x.id in own_links:
                    continue   # the take-back, that click's own undo or the rebuild's reversal removes it
                writer = _live_batches(db, "cost_line_steps", [x.id]).get(x.id)
                if writer is not None and not _link_undo(db, writer):
                    # A journalled click on a twin the rebuild did not make:
                    # deleting its link would leave that click undoable no more.
                    wbx = db.get(M.WriteBatch, writer)
                    plan["refused"].append(f"journal batch #{writer} ({wbx.kind}) linked a click outside the "
                                           f"rebuild to its whole step {sr.step_key!r} — undo it first")
                    continue
                # What `twins._link_step_keys` added on a click outside the
                # rebuild: the key's undo takes it back too (decision 0075).
                plan["takes_back"].append({"kind": "link", "line_id": x.line_id, "click_id": sr.id,
                                           "step": sr.step_key})
                db.delete(x)
    if plan["refused"]:
        return plan
    db.flush()
    # One sequence, newest first, the rebuild's own batches included: an
    # append is undone before a crafting write older than it. A crafting
    # write that turns out to stand on the next batch (a link an unlink took
    # away, back again) is taken back first, the same way.
    done: set[int] = set()
    ours: set[int] = set()           # the reversal batches this undo writes
    # The twins the rebuild made go with it: a finish click on one, then its
    # unit shipped, is no unit this undo leaves unfinished.
    own_twins = frozenset(r.row_id for b in rebuild_batches for r in db.get(M.WriteBatch, b).rows
                          if r.table_name == "twins" and r.op == "insert")

    def take_back_copies(wb: M.WriteBatch) -> None:
        # A split copied the rebuild's whole-step links onto the position's
        # children, outside the journal: they go with the rebuild, and the
        # person's split stays (decisions 0074, 0075).
        own = {(r.table_name, r.row_id) for r in wb.rows}
        for r in wb.rows:
            k = db.get(M.CostLineStepKey, r.row_id) if r.table_name == "cost_line_step_keys" and r.op == "insert" \
                else None
            if k is None:
                continue
            below, frontier = set(), [k.line_id]
            while frontier:
                frontier = [i for (i,) in db.query(M.RunCostLine.id).filter(M.RunCostLine.parent_line_id.in_(frontier))
                            if i not in below]
                below.update(frontier)
            copies = (db.query(M.CostLineStepKey).filter(M.CostLineStepKey.line_id.in_(below or {-1}),
                                                         M.CostLineStepKey.run_id == k.run_id,
                                                         M.CostLineStepKey.step_key == k.step_key)
                      .order_by(M.CostLineStepKey.id).all())
            writers = _live_batches(db, "cost_line_step_keys", [x.id for x in copies])

            def removable(w: int | None) -> bool:
                return w is None or w in ours or _link_undo(db, w)

            for x in copies:
                if ("cost_line_step_keys", x.id) in own or not removable(writers.get(x.id)):
                    continue   # its own row, or a link a person made: the check names it
                plan["takes_back"].append({"kind": "key", "line_id": x.line_id, "step": x.step_key})
                db.delete(x)
            # The links the key made since on clicks this undo leaves, again:
            # a reversed unlink has put them back after the first pass.
            grown = (db.query(M.CostLineStep).join(M.StepRun, M.StepRun.id == M.CostLineStep.step_run_id)
                     .filter(M.CostLineStep.line_id.in_(below | {k.line_id}), M.StepRun.run_id == k.run_id,
                             M.StepRun.step_key == k.step_key, M.CostLineStep.created_at > wb.created_at)
                     .order_by(M.CostLineStep.id).all())
            lwriters = _live_batches(db, "cost_line_steps", [x.id for x in grown])
            for x in grown:
                if ("cost_line_steps", x.id) in own or not removable(lwriters.get(x.id)):
                    continue
                plan["takes_back"].append({"kind": "link", "line_id": x.line_id, "click_id": x.step_run_id,
                                           "step": k.step_key})
                db.delete(x)
        db.flush()

    def reverse_one(wb: M.WriteBatch, depth: int = 0) -> str | None:
        for _attempt in range(8):
            if wb.kind == "craft.rebuild" and wb.id in rebuild_batches:
                take_back_copies(wb)
            res = journal.reverse(db, wb.id, actor=actor or "user", dry_run=False, stock=False,
                                  leaving_twins=own_twins)
            if res["status"] == "reversed":
                done.add(wb.id)
                ours.add(res["reverse_batch_id"])
                return None
            extra = [x for x in res["blocking_batches"]
                     if x not in done and x not in rebuild_batches and x not in ours and not _link_undo(db, x)]
            if not extra or depth >= 4:
                return "; ".join(res["blockers"])
            for x in sorted(extra, reverse=True):
                wx = db.get(M.WriteBatch, x)
                why = dep_refusal(wx)
                if why:
                    return why
                row = _batch_row(db, wx, tids)
                err = reverse_one(wx, depth + 1)
                if err:
                    return f"journal batch #{x} ({wx.kind}) cannot be reversed: {err}"
                plan["takes_back"].append(row)
        return "; ".join(res["blockers"])

    seq = items + [(db.get(M.WriteBatch, b).created_at, "rebuild", db.get(M.WriteBatch, b)) for b in rebuild_batches]
    for _when, kind, obj in sorted(seq, key=lambda x: (x[0], x[2].id), reverse=True):
        if kind == "bench":
            plan["takes_back"].append(_take_back_bench(db, obj, tids))
            continue
        if obj.id in done:
            continue
        row = _batch_row(db, obj, tids) if kind == "batch" else None
        err = reverse_one(obj)
        if err:
            plan["refused"].append(f"journal batch #{obj.id} ({obj.kind}) cannot be reversed: {err}" if row
                                   else f"the rebuild's journal batch #{obj.id} cannot be reversed: {err}")
            return plan
        if row:
            plan["takes_back"].append(row)
    db.flush()
    rest = db.query(M.StepRun).filter_by(run_id=run.id, chosen=CHOSEN).all()
    if rest:
        plan["before_the_journal"] = True
        _undo_before_the_journal(db, run, rest)
    if not db.query(M.StepRun).filter_by(run_id=run.id).count():
        # Nothing crafted is left, so the batch is unpinned: a whole-step link
        # made since on a step with no click yet goes too, or the batch keeps
        # a link no screen can show or remove (decision 0074).
        left = db.query(M.CostLineStepKey).filter_by(run_id=run.id).all()
        writers = _live_batches(db, "cost_line_step_keys", [k.id for k in left])
        for b in sorted({x for x in writers.values() if x not in ours}, reverse=True):
            wx = db.get(M.WriteBatch, b)
            if wx.reversed_at is not None:
                continue
            why = dep_refusal(wx)
            if why:
                plan["refused"].append(why)
                return plan
            row = _batch_row(db, wx, tids)
            err = reverse_one(wx)
            if err:
                plan["refused"].append(f"journal batch #{b} ({wx.kind}) cannot be reversed: {err}")
                return plan
            plan["takes_back"].append(row)
        for k in db.query(M.CostLineStepKey).filter_by(run_id=run.id).all():
            plan["takes_back"].append({"kind": "key", "line_id": k.line_id, "step": k.step_key})
            db.delete(k)
        db.flush()
        oldest = db.get(M.WriteBatch, rebuild_batches[-1]) if rebuild_batches else None
        run.process_version_id = (oldest.summary or {}).get("pinned_before") if oldest is not None else None
    db.flush()
    if lots_before:
        # A lot the rebuild gave units back to may go no lower than it was
        # before the rebuild (the oldest rebuild's record); any other lot, no
        # lower than it was before this undo.
        stored: dict[str, float] = {}
        for b in sorted(rebuild_batches):
            for k, v in ((db.get(M.WriteBatch, b).summary or {}).get("returned_lots") or {}).items():
                stored.setdefault(k, float(v))
        state = L.lot_state(db)["lots"]
        for key, was in sorted(lots_before.items()):
            lot = state.get(key)
            gap = min(0.0, stored.get(key, was)) - (lot["qty_remaining"] if lot is not None else 0.0)
            if lot is not None and gap > L.CLOSED_EPS * 100:
                plan["refused"].append(f"lot {key} ({lot.get('mpn') or lot.get('lcsc') or '?'}, {lot.get('date')}) "
                                       f"would be overdrawn by {round(gap, 4):g}: a draw recorded since took what "
                                       "the rebuild gave back, or the lot was cut — undo or correct that first")
    return plan


def _bound_lots(db: Session, batch_ids: list[int]) -> dict[str, float]:
    """The lots whose bindings these batches changed, with what each has
    left now — empty when they changed none (decision 0073)."""
    keys: set[str] = set()
    for b in batch_ids:
        for r in db.get(M.WriteBatch, b).rows:
            if r.table_name != "component_consumption_lots":
                continue
            cur = db.get(M.ComponentConsumptionLot, r.row_id)
            for st in (r.before or {}, {"lot_line_id": cur.lot_line_id, "lot_adjustment_id": cur.lot_adjustment_id}
                       if cur is not None else {}):
                if st.get("lot_line_id"):
                    keys.add(L._lot_key("L", st["lot_line_id"]))
                if st.get("lot_adjustment_id"):
                    keys.add(L._lot_key("A", st["lot_adjustment_id"]))
    if not keys:
        return {}
    state = L.lot_state(db)["lots"]
    return {k: state[k]["qty_remaining"] for k in keys if k in state}


def _disposal_scrap(sr: M.StepRun) -> bool:
    """The scrap click a disposal on the device page writes
    (`twins.scrap_disposed`): no journal batch, taken back like a bench click.
    The device keeps its disposal, so a new rebuild scraps the twin again."""
    return sr.kind == "scrap" and sr.chosen == "list" and (sr.note or "").startswith("disposed of")


def _returned_short(db: Session, run: M.ProductionRun, batches: list[int], bench_clicks: set[int],
                    rebuilt_at=None) -> list[str]:
    """Undoing a `return` takes the surplus out of the pool again: refused
    when a draw recorded SINCE the rebuild took those units — two batches
    would pay for the same ones (decision 0075). Two dated replays of the
    pool the undo leaves (the draws it deletes — what the rebuild drew, a
    dependent click's draws, a bench click taken back — left out, each draw
    it puts back entered as it was before the rebuild, on its own date): one
    with every draw, one without the draws recorded after the rebuild. The
    undo is refused only on a date where the first goes below zero and below
    the second. A draw split into pieces moves nothing, a give-back dated
    today cannot hide a shortfall in the past, and a deficit the pool already
    had is no reason to refuse."""
    inserted: set[int] = set()
    first_before: dict[int, tuple[int, dict]] = {}
    for b in batches:
        for r in db.get(M.WriteBatch, b).rows:
            if r.table_name != "component_consumptions":
                continue
            if r.op == "insert":
                inserted.add(r.row_id)
            elif r.op == "update" and r.before and (r.row_id not in first_before or b < first_before[r.row_id][0]):
                first_before[r.row_id] = (b, r.before)
    inserted |= {c for (c,) in db.query(M.ComponentConsumption.id)
                 .filter(M.ComponentConsumption.step_run_id.in_(bench_clicks or {-1})).all()}
    restored: dict[int, dict] = {}
    for cid, (_b, before) in first_before.items():
        c = db.get(M.ComponentConsumption, cid)
        if c is None or cid in inserted:
            continue
        was = 0.0 if before.get("voided_at") else float(before.get("qty") or 0)
        now = 0.0 if c.voided_at is not None else float(c.qty or 0)
        if was > now + 1e-9 or (was and (before.get("consumed_at") or c.consumed_at) != c.consumed_at):
            restored[cid] = {"component_id": before.get("component_id"), "mpn": before.get("mpn") or "",
                             "lcsc": before.get("lcsc") or "", "qty": was,
                             "date": before.get("consumed_at") or c.consumed_at,
                             "company": run_actuals.stock_scope(db, c.company_id)}
    if not restored:
        return []
    skip = inserted | set(restored)
    out = []
    by_scope: dict = {}
    stored: dict[str, dict] = {}
    for b in sorted(batches):            # the oldest rebuild's record of a part wins
        for ref, rec in ((db.get(M.WriteBatch, b).summary or {}).get("returned_low") or {}).items():
            if isinstance(rec, dict):
                stored.setdefault(ref, rec)
    covered: set[int] = set()
    for ref, rec in stored.items():
        keys = set(rec.get("keys") or [])
        mates = {cid: x for cid, x in restored.items() if x["company"] == rec.get("company")
                 and keys & set(run_actuals._identity_keys(x["component_id"], x["mpn"], x["lcsc"]))}
        if not mates:
            continue
        covered |= set(mates)
        events = by_scope.setdefault(rec.get("company"), run_actuals._pool_events(db, rec.get("company"))[0])
        after = run_actuals.pool_series(events, keys, rec.get("since") or "", drop=skip,
                             extra=[(x["date"], x["qty"]) for x in mates.values()])
        days = sorted({d for d, _l, _e in after["days"]} | {d for d, _l, _e in rec["series"]["days"]})
        worst = 0.0
        for day in days:
            a, before = run_actuals.value_on(after, day), run_actuals.value_on(rec["series"], day)
            floor = min(0.0, before)
            if a < floor - 1e-4:
                worst = max(worst, floor - a)
        if worst > 1e-4:
            x = next(iter(mates.values()))
            out.append(f"the surplus the rebuild returned is drawn again since: "
                       f"{x['mpn'] or x['lcsc'] or part_name(db, x['component_id'])} short {round(worst, 4):g} "
                       "— undo or correct that draw first")
    for cid, r in restored.items():
        if cid in covered:
            continue
        events = by_scope.setdefault(r["company"], run_actuals._pool_events(db, r["company"])[0])
        want = set(run_actuals._identity_keys(r["component_id"], r["mpn"], r["lcsc"]))
        mates = [x for x in restored.values() if x["company"] == r["company"]
                 and want & set(run_actuals._identity_keys(x["component_id"], x["mpn"], x["lcsc"]))]
        since = min(x["date"] or "9999" for x in mates)

        entries = []
        for date_iso, kind, row in events:
            if kind == "use" and row.id in skip:
                continue
            if not (want & set(run_actuals._identity_keys(getattr(row, "component_id", None),
                                                          getattr(row, "mpn", "") or "",
                                                          getattr(row, "lcsc", "") or ""))):
                continue
            q = (row.qty or 0.0) if kind == "buy" else \
                (-(row.qty or 0.0) if kind == "use" else (row.qty_delta or 0.0))
            # a draw (or a loss) recorded since the rebuild: what can take the units back
            late = (kind == "use" or (kind == "adj" and q < 0)) and rebuilt_at is not None \
                and getattr(row, "created_at", None) is not None and row.created_at > rebuilt_at
            entries.append((((date_iso or "9999"), kind), q, late))
        entries += [(((x["date"] or "9999"), "use"), -x["qty"], False) for x in mates]
        entries.sort(key=lambda e: e[0])
        bal = base = 0.0
        worst = 0.0
        for (day, _k), q, late in entries:
            bal += q
            base += 0.0 if late else q
            if day >= since and bal < -1e-4 and bal < base - 1e-4:
                worst = max(worst, min(-bal, base - bal))   # what is missing, that a later draw took
        if worst > 1e-4:
            out.append(f"the surplus the rebuild returned is drawn again since: "
                       f"{r['mpn'] or r['lcsc'] or part_name(db, r['component_id'])} short {round(worst, 4):g} "
                       "— undo or correct that draw first")
    return sorted(set(out))


def part_name(db: Session, component_id: int | None) -> str:
    c = db.get(M.Component, component_id) if component_id else None
    return c.name if c is not None else str(component_id)


def _batch_row(db: Session, wb: M.WriteBatch, tids: set[int]) -> dict:
    srs = [db.get(M.StepRun, r.row_id) for r in wb.rows if r.table_name == "step_runs" and r.op == "insert"]
    srs = [sr for sr in srs if sr is not None]
    on = {t for (t,) in db.query(M.TwinStep.twin_id).filter(M.TwinStep.step_run_id.in_([sr.id for sr in srs] or [-1]))}
    return {"kind": "journal", "batch_id": wb.id, "write": wb.kind, "source_ref": wb.source_ref,
            "clicks": [{"click_id": sr.id, "step": sr.step_key, "label": sr.step_label, "chosen": sr.chosen,
                        "made_at": sr.made_at, "units": sr.qty} for sr in srs],
            "twins_outside_the_rebuild": len(on - tids)}


def _take_back_bench(db: Session, sr: M.StepRun, tids: set[int]) -> dict:
    """A bench click is not journalled (decision 0074): delete it, its draws
    and their lot bindings, and take its step off each twin's stack key. A
    naming at the bench gives the twin its stack back."""
    devices = []
    draws = 0
    for c in db.query(M.ComponentConsumption).filter_by(step_run_id=sr.id).all():
        for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id).all():
            db.delete(b)
        db.delete(c)
        draws += 1
    for x in db.query(M.CostLineStep).filter_by(step_run_id=sr.id).all():
        db.delete(x)
    for ts in db.query(M.TwinStep).filter_by(step_run_id=sr.id).all():
        tw = db.get(M.Twin, ts.twin_id)
        if tw is not None:
            if tw.device_unit_id:
                d = db.get(M.DeviceUnit, tw.device_unit_id)
                devices.append(d.serial or d.mac if d else tw.device_unit_id)
            # The token goes only when no other click of the twin holds the step.
            still = (db.query(M.TwinStep.id).join(M.StepRun, M.StepRun.id == M.TwinStep.step_run_id)
                     .filter(M.TwinStep.twin_id == tw.id, M.TwinStep.id != ts.id,
                             M.StepRun.step_key == sr.step_key).first())
            if still is None:
                toks = [t for t in (tw.stack_key or "").split("|") if t and t.split("@", 1)[0] != sr.step_key]
                tw.stack_key = "|".join(sorted(toks))
            if _disposal_scrap(sr):
                # Back to how the rebuild left it, which the note keeps.
                was = (sr.note or "").rsplit("(was ", 1)
                tw.status = was[1].rstrip(")") if len(was) == 2 else tw.status
                tw.scrapped_at = None
            if sr.kind == "program" and (sr.note or "").startswith("named "):
                tw.device_unit_id = None
                tw.named_at = None
                tw.run_id = tw.origin_run_id
        db.delete(ts)
    row = {"kind": "bench", "click_id": sr.id, "step": sr.step_key, "label": sr.step_label,
           "batch_run_id": sr.run_id, "made_at": sr.made_at, "devices": devices, "draws": draws}
    db.delete(sr)
    db.flush()
    return row


def _undo_before_the_journal(db: Session, run: M.ProductionRun, clicks: list[M.StepRun]) -> None:
    """A rebuild written before the rebuild was journalled: its draws are
    unlinked (a draw it wrote for a stated step is deleted), its links, twins
    and clicks deleted."""
    ids = [c.id for c in clicks]
    twins = (db.query(M.Twin).join(M.TwinStep, M.TwinStep.twin_id == M.Twin.id)
             .filter(M.TwinStep.step_run_id.in_(ids or [-1]), M.Twin.found.is_(False)).distinct().all())
    tids = [tw.id for tw in twins]
    live = (db.query(M.StepRun.step_label).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
            .filter(M.TwinStep.twin_id.in_(tids or [-1]), M.StepRun.chosen != CHOSEN).distinct().all())
    if live:
        raise HTTPException(409, f"live steps were recorded on rebuilt twins since "
                                 f"({', '.join(x for (x,) in live)}) — undo is refused")
    for c in db.query(M.ComponentConsumption).filter(M.ComponentConsumption.step_run_id.in_(ids or [-1])):
        if c.basis == T.BASIS_STEP and (c.note or "").startswith("rebuilt:"):
            for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id).all():
                db.delete(b)
            db.delete(c)       # a draw the rebuild wrote for a stated step goes with it
        else:
            c.step_run_id = None
    for x in db.query(M.CostLineStep).filter(M.CostLineStep.step_run_id.in_(ids or [-1])).all():
        db.delete(x)
    for x in db.query(M.TwinStep).filter(M.TwinStep.step_run_id.in_(ids or [-1])).all():
        db.delete(x)
    db.flush()
    for tw in twins:
        db.delete(tw)
    for c in clicks:
        db.delete(c)
    db.flush()
