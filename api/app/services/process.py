"""Production processes: the versioned process document and PREPARED PARTS
(decisions 0058 and 0059).

A project's PROCESS (`ProcessVersion.graph`) is a versioned document:

- **steps** — a library. Each step states its `kind` (assembly, receive,
  step, program, test, mark_laser, label, finish), where it is done, what a unit needs before it
  (`needs` / `needs_not`: step keys or alternative-group names), the parts it
  adds (`inputs`), whether it is `required`, and its alternative `group`
  (a sticker OR a UV print);
- **route** — the usual order, for the map and the batch page's next steps.
  Any step whose needs are met may run in any order (0059 §4);
- **prepared** — recipes for PREPARED PARTS: internal parts made before they
  meet a device (an enclosure drilled and UV printed), held as stock lots.

The units themselves are TWINS (`services/twins.py`). This module owns the
document, its machine check, and the prepared-part stock.

**Nothing here forks the pool.** A prepared-part transformation is written with
the two event kinds every replayer already understands: its inputs are draws
(no run, `transformation_id` set) and its output is one positive
`ComponentStockAdjustment`, which `lots.py` treats as a lot (`A<id>`). The
pool's value identity holds by construction.

**Lots matter only for internal parts.** Bought parts are valued at the moving
average, as everywhere in this platform. A prepared part's lots carry real
differences (printed or stickered, found at zero value or built from today's
purchases), so every draw of one names its lot.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as M
from ..models import utcnow
from . import run_actuals

#: Draw bases written for prepared parts: an input of a recipe, and units of a
#: prepared-part lot that broke or were not found at a count.
BASIS_TRANSFORMATION = "transformation"
BASIS_WRITEOFF = "stage_writeoff"

EPS = 1e-6

#: Step kinds, and the station each one is done at (decision 0059 §5). An
#: `assembly` step is the board's assembly at the SUPPLIER (decision 0060): it
#: is recorded from the batch's assembly order, never clicked through.
KINDS = {"assembly": "supplier", "receive": "batch", "step": "batch",
         "program": "programming_bench", "test": "programming_bench",
         "mark_laser": "marking_bench", "label": "marking_bench", "finish": "batch"}
#: Kinds a process has exactly one of.
SINGLE_KINDS = ("assembly", "receive", "program", "finish")
#: Kinds that add no parts: the supplier's assembly (its parts come from the
#: order), receiving, and finishing. Every other kind may list inputs, and
#: whoever records it draws them (decision 0061).
NO_INPUT_KINDS = ("assembly", "receive", "finish")
#: A bench step names the DEPLOYMENT that says how it is done (decision 0060):
#: the step kind → the deployment kind it may name.
DEPLOYMENT_KIND_FOR = {"program": "flash", "test": "test", "mark_laser": "mark", "label": "mark"}


def _today() -> str:
    return date.today().isoformat()


# ================================================================ the document

def versions(db: Session, project_id: int) -> list[M.ProcessVersion]:
    return (db.query(M.ProcessVersion).filter_by(project_id=project_id)
            .order_by(M.ProcessVersion.version_no.desc()).all())


def current_version(db: Session, project_id: int) -> M.ProcessVersion | None:
    """What a new batch resolves to: the version the project POINTS at
    (decision 0074). Not the highest published one — a version published for
    the history of older devices is never current."""
    p = db.get(M.Project, project_id)
    v = db.get(M.ProcessVersion, p.current_process_version_id) if p and p.current_process_version_id else None
    return v if v is not None and v.project_id == project_id and v.status == "published" else None


def make_current(db: Session, v: M.ProcessVersion) -> M.ProcessVersion:
    """Point the project at a published version. Batches keep the version
    they pinned; only new batches and the project's planned BOM follow."""
    if v.status != "published":
        raise HTTPException(409, "only a published version can be current")
    db.get(M.Project, v.project_id).current_process_version_id = v.id
    db.flush()
    return v


def version_for_run(db: Session, run: M.ProductionRun) -> M.ProcessVersion | None:
    """The version a batch is judged against: the one it resolved at creation,
    else — for a batch created before its project had a process — the current."""
    if run.process_version_id:
        v = db.get(M.ProcessVersion, run.process_version_id)
        if v is not None:
            return v
    return current_version(db, run.project_id)


def _graph(v: M.ProcessVersion | None) -> dict:
    g = (v.graph if v is not None else None) or {}
    return {"steps": list(g.get("steps") or []), "route": list(g.get("route") or []),
            "prepared": list(g.get("prepared") or [])}


def step_map(graph: dict) -> dict[str, dict]:
    return {s.get("key"): s for s in graph.get("steps") or [] if s.get("key")}


def groups_of(graph: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = defaultdict(list)
    for s in graph.get("steps") or []:
        if s.get("group"):
            out[s["group"]].append(s.get("key"))
    return dict(out)


def step_of_kind(graph: dict, kind: str) -> dict | None:
    return next((s for s in graph.get("steps") or [] if s.get("kind") == kind), None)


def prepared_outputs(graph: dict) -> set[int]:
    return {int(r["output_component_id"]) for r in graph.get("prepared") or []
            if r.get("output_component_id")}


def input_ref(inp: dict) -> tuple[int | None, str]:
    """An input names a library part (`component_id`) or, for a part the
    library does not hold — a shipping carton bought by its supplier code —
    the MPN its purchases are keyed by in the pool (`mpn`)."""
    cid = inp.get("component_id")
    return (int(cid) if cid else None), (inp.get("mpn") or "").strip()


def input_label(inp: dict, names: dict) -> str:
    cid, mpn = input_ref(inp)
    return ((names.get(cid) or {}).get("name") if cid else None) or mpn or str(cid)


def required_terms(graph: dict) -> list[str]:
    """What the finish step needs: every required step outside a group, and every
    group that has a required member (one of its options must be done)."""
    out: list[str] = []
    groups = groups_of(graph)
    seen_groups: set[str] = set()
    for s in graph.get("steps") or []:
        if s.get("kind") in ("finish",) or not s.get("required"):
            continue
        g = s.get("group")
        if g:
            if g not in seen_groups and len(groups.get(g, [])) > 1:
                seen_groups.add(g)
                out.append(g)
        else:
            out.append(s.get("key"))
    return out


def check(db: Session, project_id: int, graph: dict) -> dict:
    """The machine check a version must pass to publish (decisions 0058 §2, 0059 §4).

    The live editor and the publish button call THIS function. Errors block
    publishing; warnings do not.
    """
    errors: list[str] = []
    warnings: list[str] = []
    steps = graph.get("steps") or []
    prepared = graph.get("prepared") or []
    route = graph.get("route") or []
    if not steps:
        errors.append("the process has no steps")
    keys = [s.get("key") for s in steps]
    if any(not k for k in keys) or len(set(keys)) != len(keys):
        errors.append("every step needs a unique key")
    by_key = {s.get("key"): s for s in steps}
    label = {k: (s.get("label") or k) for k, s in by_key.items()}

    for kind in SINGLE_KINDS:
        n = sum(1 for s in steps if s.get("kind") == kind)
        if n != 1:
            errors.append(f"a process has exactly one {kind!r} step; this one has {n}")
    for s in steps:
        kind = s.get("kind") or "step"
        if kind not in KINDS:
            errors.append(f"step {label.get(s.get('key'))!r}: unknown kind {kind!r}")
            continue
        station = s.get("station") or KINDS[kind]
        if station != KINDS[kind]:
            errors.append(f"step {label[s['key']]!r}: a {kind!r} step is done at the "
                          f"{KINDS[kind].replace('_', ' ')}, not at {station!r}")
        if kind in SINGLE_KINDS and s.get("group"):
            errors.append(f"step {label[s['key']]!r}: a {kind!r} step cannot be one option of a choice")
        if kind in ("assembly", "receive", "program") and not s.get("required"):
            errors.append(f"step {label[s['key']]!r}: the {kind!r} step is always required")
        if kind in ("assembly", "receive") and (s.get("needs") or s.get("needs_not")):
            errors.append(f"step {label[s['key']]!r}: the board's assembly and its receipt "
                          "are the first steps and need nothing")
        if kind == "assembly" and s.get("inputs"):
            errors.append(f"step {label[s['key']]!r}: the assembly step takes its parts and "
                          "fees from the batch's assembly order, not from the process")
        elif kind in ("receive", "finish") and s.get("inputs"):
            errors.append(f"step {label[s['key']]!r}: a {kind!r} step adds no parts")
        dep_id = s.get("deployment_id")
        if dep_id and kind not in DEPLOYMENT_KIND_FOR:
            errors.append(f"step {label[s['key']]!r}: only a bench step names a deployment")
        elif dep_id:
            d = db.get(M.Deployment, int(dep_id))
            want = DEPLOYMENT_KIND_FOR[kind]
            if d is None or d.project_id != project_id:
                errors.append(f"step {label[s['key']]!r}: deployment {dep_id} is not one of this project")
            elif (d.kind or "flash") != want:
                errors.append(f"step {label[s['key']]!r}: a {kind!r} step is done by a {want!r} "
                              f"deployment, and {d.name!r} is a {d.kind or 'flash'!r} one")
        elif kind in DEPLOYMENT_KIND_FOR:
            warnings.append(f"step {label[s['key']]!r} names no deployment, so the bench runs "
                            "whatever procedure the operator picks")
        # A required bench step the project has no bench for could only ever
        # be stated by hand (decision 0074): make it optional, or a batch step.
        # Programming is exempt: its bench is what names a twin at all.
        if kind in DEPLOYMENT_KIND_FOR and kind != "program" and s.get("required") and not dep_id:
            want = DEPLOYMENT_KIND_FOR[kind]
            if not any((d.kind or "flash") == want for d in
                       db.query(M.Deployment).filter_by(project_id=project_id).all()):
                errors.append(f"step {label[s['key']]!r} is required, and the project has no {want!r} "
                              "deployment to record it — add one, or make the step optional")
        if kind == "finish" and s.get("needs"):
            warnings.append(f"step {label[s['key']]!r}: the finish step needs every required "
                            "step by itself; its own needs list is ignored")

    groups = groups_of(graph)
    for g, members in groups.items():
        if len(members) < 2:
            errors.append(f"choice {g!r} has one option; a choice needs at least two")
        flags = {bool(by_key[m].get("required")) for m in members if m in by_key}
        if len(flags) > 1:
            warnings.append(f"choice {g!r} mixes required and optional options; it is "
                            "treated as required")
    names = set(by_key) | set(groups)
    for s in steps:
        for field in ("needs", "needs_not"):
            for ref in s.get(field) or []:
                if ref not in names:
                    errors.append(f"step {label.get(s.get('key'))!r}: {field} names {ref!r}, "
                                  "which is no step and no choice")
                if ref == s.get("key") or ref == s.get("group"):
                    errors.append(f"step {label.get(s.get('key'))!r} names itself in {field}")

    outputs = prepared_outputs(graph)
    for s in steps:
        for inp in s.get("inputs") or []:
            cid, mpn = input_ref(inp)
            qty = inp.get("qty")
            if cid is None and mpn:
                if not isinstance(qty, (int, float)) or qty <= 0:
                    errors.append(f"step {label.get(s.get('key'))!r}: {mpn} needs a quantity above zero")
                continue
            comp = db.get(M.Component, cid) if cid else None
            if comp is None:
                errors.append(f"step {label.get(s.get('key'))!r}: input part {cid or mpn!r} does not exist")
                continue
            if not isinstance(qty, (int, float)) or qty <= 0:
                errors.append(f"step {label.get(s.get('key'))!r}: {comp.name} needs a quantity "
                              "above zero")
            if comp.internal and comp.id not in outputs:
                errors.append(f"step {label.get(s.get('key'))!r}: {comp.name!r} is an internal "
                              "part that no prepared-part recipe of this process makes")

    # No cycles: a step may not, through its needs, need itself.
    def expand(ref: str) -> list[str]:
        return groups.get(ref, [ref])

    state: dict[str, int] = {}

    def visit(k: str, path: list[str]) -> None:
        if state.get(k) == 2 or k not in by_key:
            return
        if state.get(k) == 1:
            errors.append("the steps need each other in a circle: "
                          + " → ".join(label.get(x, x) for x in path + [k]))
            return
        state[k] = 1
        for ref in by_key[k].get("needs") or []:
            for nxt in expand(ref):
                visit(nxt, path + [k])
        state[k] = 2

    for k in by_key:
        visit(k, [])

    # Two required steps that exclude each other can never both be done.
    req = {k for k, s in by_key.items() if s.get("required") and not s.get("group")}
    for k in req:
        for ref in by_key[k].get("needs_not") or []:
            if set(expand(ref)) & req and ref not in groups:
                errors.append(f"required step {label[k]!r} excludes required step "
                              f"{label.get(ref, ref)!r}, so no device could be finished")

    seen_route: set[str] = set()
    for k in route:
        if k not in by_key:
            errors.append(f"the main route names {k!r}, which is not a step")
        if k in seen_route:
            errors.append(f"the main route names {label.get(k, k)!r} twice")
        seen_route.add(k)
    for k, s in by_key.items():
        if s.get("required") and k not in seen_route:
            warnings.append(f"required step {label[k]!r} is not on the main route")
    head = [by_key.get(k, {}).get("kind") for k in route[:2]]
    if route and head not in (["assembly", "receive"], ["receive", "assembly"]):
        warnings.append("the main route does not start with the board's assembly and its receipt")
    if route and by_key.get(route[-1], {}).get("kind") != "finish":
        warnings.append("the main route does not end with the finish step")

    rkeys = [r.get("key") for r in prepared]
    if any(not k for k in rkeys) or len(set(rkeys)) != len(rkeys):
        errors.append("every prepared-part recipe needs a unique key")
    feeds: dict[int, set[int]] = defaultdict(set)
    for r in prepared:
        rl = r.get("label") or r.get("key")
        out = db.get(M.Component, int(r["output_component_id"])) if r.get("output_component_id") else None
        if out is None:
            errors.append(f"prepared-part recipe {rl!r}: its output part does not exist")
            continue
        if not out.internal:
            errors.append(f"prepared-part recipe {rl!r}: {out.name!r} is a bought part; a "
                          "recipe makes an internal part")
        if not r.get("inputs"):
            errors.append(f"prepared-part recipe {rl!r} has no inputs")
        for inp in r.get("inputs") or []:
            cid, mpn = input_ref(inp)
            qty = inp.get("qty")
            if cid is None and mpn:
                if not isinstance(qty, (int, float)) or qty <= 0:
                    errors.append(f"prepared-part recipe {rl!r}: {mpn} needs a quantity above zero")
                continue
            comp = db.get(M.Component, cid) if cid else None
            if comp is None:
                errors.append(f"prepared-part recipe {rl!r}: input part {cid or mpn!r} does not exist")
                continue
            if not isinstance(qty, (int, float)) or qty <= 0:
                errors.append(f"prepared-part recipe {rl!r}: {comp.name} needs a quantity above zero")
            if comp.id == out.id:
                errors.append(f"prepared-part recipe {rl!r} consumes its own output")
            if comp.internal:
                if comp.id not in outputs:
                    errors.append(f"prepared-part recipe {rl!r}: {comp.name!r} is an internal "
                                  "part that no recipe of this process makes")
                feeds[comp.id].add(out.id)
        scrap = r.get("expected_scrap_pct") or 0
        if not isinstance(scrap, (int, float)) or scrap < 0 or scrap >= 100:
            errors.append(f"prepared-part recipe {rl!r}: expected scrap must be 0–99 %")
    pstate: dict[int, int] = {}

    def pvisit(c: int) -> None:
        if pstate.get(c) == 2:
            return
        if pstate.get(c) == 1:
            errors.append("the prepared-part recipes consume each other in a circle")
            return
        pstate[c] = 1
        for nxt in feeds.get(c, ()):
            pvisit(nxt)
        pstate[c] = 2

    for c in list(feeds):
        pvisit(c)
    used = {c for s in steps for c, _m in map(input_ref, s.get("inputs") or []) if c}
    used |= set(feeds)
    for c in outputs - used:
        comp = db.get(M.Component, c)
        warnings.append(f"prepared part {comp.name if comp else c!r} is made by a recipe but no "
                        "step uses it")

    return {"errors": errors, "warnings": warnings, "ok": not errors}


def _part_names(db: Session, ids: set[int]) -> dict[int, dict]:
    if not ids:
        return {}
    from ..routers.util import part_display_name

    out = {}
    for c in db.query(M.Component).filter(M.Component.id.in_(ids)).all():
        name, _ = part_display_name(db, c.id)
        out[c.id] = {"id": c.id, "name": name or c.name, "internal": bool(c.internal)}
    return out


def version_json(db: Session, v: M.ProcessVersion, *, with_check: bool = False) -> dict:
    g = _graph(v)
    ids = {c for s in g["steps"] for c, _m in map(input_ref, s.get("inputs") or []) if c}
    ids |= prepared_outputs(g) | {c for r in g["prepared"]
                                  for c, _m in map(input_ref, r.get("inputs") or []) if c}
    out = {
        "id": v.id, "project_id": v.project_id, "version_no": v.version_no,
        "status": v.status, "comment": v.comment, "created_by": v.created_by,
        "approved_by": v.approved_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "published_at": v.published_at.isoformat() if v.published_at else None,
        "graph": g, "parts": {str(k): p for k, p in _part_names(db, ids).items()},
        "batches": [{"id": r.id, "label": r.label} for r in db.query(M.ProductionRun)
                    .filter_by(process_version_id=v.id).order_by(M.ProductionRun.id).all()],
        "transformation_count": db.query(func.count(M.ProcessTransformation.id))
                                  .filter_by(process_version_id=v.id).scalar() or 0,
    }
    if with_check:
        out["check"] = check(db, v.project_id, g)
    return out


def compose(db: Session, project_id: int, *, actor: str,
            from_version_id: int | None = None, graph: dict | None = None) -> M.ProcessVersion:
    """A new DRAFT: a copy of `from_version_id` (default: the current version),
    or `graph` when given. A project holds at most one draft at a time, so two
    people cannot edit two diverging drafts of one process."""
    if db.query(M.ProcessVersion).filter_by(project_id=project_id, status="draft").first():
        raise HTTPException(409, "this project already has a draft process — edit it, or delete it")
    base = (db.get(M.ProcessVersion, from_version_id) if from_version_id
            else current_version(db, project_id))
    if from_version_id and (base is None or base.project_id != project_id):
        raise HTTPException(404, "no such process version in this project")
    n = (db.query(func.max(M.ProcessVersion.version_no)).filter_by(project_id=project_id)
         .scalar() or 0)
    v = M.ProcessVersion(project_id=project_id, version_no=n + 1, status="draft",
                         graph=graph if graph is not None else _graph(base),
                         created_by=actor)
    db.add(v)
    db.flush()
    return v


def update_draft(db: Session, v: M.ProcessVersion, *, graph: dict | None = None,
                 comment: str | None = None) -> M.ProcessVersion:
    if v.status != "draft":
        raise HTTPException(409, "published versions are immutable — compose a new draft")
    if graph is not None:
        v.graph = {"steps": list(graph.get("steps") or []),
                   "route": list(graph.get("route") or []),
                   "prepared": list(graph.get("prepared") or [])}
    if comment is not None:
        v.comment = comment[:500]
    db.flush()
    return v


def publish(db: Session, v: M.ProcessVersion, *, actor: str,
            comment: str | None = None, historical: bool = False) -> M.ProcessVersion:
    """Publish a draft and make it current — unless `historical`: a version
    that describes how older devices were made, for their batches to pin."""
    if v.status != "draft":
        raise HTTPException(409, "only a draft can be published")
    if comment is not None:
        v.comment = comment[:500]
    if not (v.comment or "").strip():
        raise HTTPException(422, "publishing needs a comment saying what changed and why")
    res = check(db, v.project_id, _graph(v))
    if not res["ok"]:
        raise HTTPException(422, {"error": "the process does not pass its check",
                                  "check": res})
    v.status = "published"
    v.approved_by = actor
    v.published_at = utcnow()
    if not historical:
        db.get(M.Project, v.project_id).current_process_version_id = v.id
    db.flush()
    return v


def delete_draft(db: Session, v: M.ProcessVersion) -> None:
    if v.status != "draft":
        raise HTTPException(409, "only a draft can be deleted; a published version is history")
    db.delete(v)
    db.flush()


# ============================================================ internal parts

def create_internal_part(db: Session, name: str) -> M.Component:
    """A prepared part: no supplier, no symbol, no published version, never
    in KiCad. It exists so the pool has a key (`c<id>`) to hold its lots under."""
    name = (name or "").strip()
    if not name:
        raise HTTPException(422, "an internal part needs a name")
    if db.query(M.Component).filter_by(name=name).first():
        raise HTTPException(409, f"a part named {name!r} already exists (names are unique)")
    comp = M.Component(name=name, in_library=False, purchasable=True, internal=True)
    db.add(comp)
    db.flush()
    return comp


def internal_parts(db: Session) -> list[M.Component]:
    return db.query(M.Component).filter_by(internal=True).order_by(M.Component.name).all()


# ==================================================================== lots

def _bound_rows(db: Session, adj_ids: list[int]) -> dict[int, tuple[float, float]]:
    """(units, value) bound to each adjustment lot by live draws, over all time —
    the sums `lots.lot_state` subtracts, read straight from the binding rows."""
    if not adj_ids:
        return {}
    rows = (db.query(M.ComponentConsumptionLot.lot_adjustment_id,
                     func.sum(M.ComponentConsumptionLot.qty),
                     func.sum(M.ComponentConsumptionLot.qty * M.ComponentConsumptionLot.unit_cost_usd))
            .join(M.ComponentConsumption,
                  M.ComponentConsumption.id == M.ComponentConsumptionLot.consumption_id)
            .filter(M.ComponentConsumptionLot.lot_adjustment_id.in_(adj_ids),
                    M.ComponentConsumption.voided_at.is_(None))
            .group_by(M.ComponentConsumptionLot.lot_adjustment_id).all())
    return {aid: (float(q or 0), float(v or 0)) for aid, q, v in rows}


def _bound(db: Session, adj_ids: list[int]) -> dict[int, float]:
    return {k: q for k, (q, _v) in _bound_rows(db, adj_ids).items()}


def lot_json(adj: M.ComponentStockAdjustment, bound: tuple[float, float],
             extra_usd: float = 0.0) -> dict:
    """A prepared-part lot. Its value is what it held plus its conversion cost
    (`extra_usd`, decision 0058 §4); what is left is that value MINUS what the
    draws took at their frozen prices — the `lots.py` rule, so a conversion
    invoice that arrives after units were drawn leaves its share visible in the
    lot instead of re-pricing draws that already happened."""
    qty = float(adj.qty_delta or 0)
    value = qty * float(adj.unit_cost_usd or 0) + extra_usd
    bound_qty, bound_value = bound
    remaining = round(qty - bound_qty, 6)
    return {"adjustment_id": adj.id, "key": f"A{adj.id}", "component_id": adj.component_id,
            "date": adj.adjusted_at, "reason": adj.reason, "note": adj.note,
            "transformation_id": adj.transformation_id, "company_id": adj.company_id,
            "qty": qty, "remaining": remaining,
            "unit_cost_usd": round(value / qty, 6) if qty else 0.0,
            "conversion_usd": round(extra_usd, 4),
            "value_remaining_usd": round(value - bound_value, 4),
            "open": remaining > EPS}


def prepared_lots(db: Session, component_ids: set[int], *, open_only: bool = False,
                  company_id: int | None = None) -> list[dict]:
    """The lots of internal parts, oldest first. A lot is a positive stock
    adjustment of the part; its remaining is what it held minus every live
    draw bound to it — exactly `lots.lot_state`'s rule for an `A` lot.
    `company_id` keeps one company's lots (decision 0064; pass it through
    `run_actuals.stock_scope`)."""
    if not component_ids:
        return []
    q = (db.query(M.ComponentStockAdjustment)
         .filter(M.ComponentStockAdjustment.component_id.in_(component_ids),
                 M.ComponentStockAdjustment.qty_delta > 0))
    if company_id is not None:
        q = q.filter(M.ComponentStockAdjustment.company_id == company_id)
    adjs = q.order_by(M.ComponentStockAdjustment.adjusted_at, M.ComponentStockAdjustment.id).all()
    bound = _bound_rows(db, [a.id for a in adjs])
    extras = run_actuals.conversion_extras_usd(db)
    out = [lot_json(a, bound.get(a.id, (0.0, 0.0)), extras.get(a.id, 0.0)) for a in adjs]
    return [lt for lt in out if lt["open"]] if open_only else out


def lot_remaining(db: Session, adj_id: int) -> float:
    adj = db.get(M.ComponentStockAdjustment, adj_id)
    if adj is None or (adj.qty_delta or 0) <= 0:
        return 0.0
    return float(adj.qty_delta or 0) - _bound(db, [adj_id]).get(adj_id, 0.0)


def _pick_lots(db: Session, component_id: int, need: float,
               chosen: list[dict] | None, company_id: int | None = None
               ) -> tuple[list[tuple[int, float, float]], float]:
    """Which lots an internal-part draw takes: `chosen` [{adjustment_id, qty}]
    when given, else oldest open lot first. Returns ([(adj_id, qty, unit)],
    the quantity no lot could cover)."""
    lots = {lt["adjustment_id"]: lt for lt in prepared_lots(db, {component_id}, open_only=True,
                                                            company_id=company_id)}
    picks: list[tuple[int, float, float]] = []
    if chosen:
        for c in chosen:
            aid, q = int(c["adjustment_id"]), float(c.get("qty") or 0)
            lt = lots.get(aid)
            if q <= 0:
                continue
            if lt is None:
                raise HTTPException(422, f"lot A{aid} is not an open lot of this part")
            if q - lt["remaining"] > EPS:
                raise HTTPException(409, f"lot A{aid} holds {lt['remaining']:g}, not {q:g}")
            picks.append((aid, q, lt["unit_cost_usd"]))
        covered = sum(p[1] for p in picks)
        if abs(covered - need) > EPS:
            raise HTTPException(422, f"the chosen lots give {covered:g}, the recipe needs {need:g}")
        return picks, 0.0
    left = need
    for lt in lots.values():
        if left <= EPS:
            break
        take = min(left, lt["remaining"])
        picks.append((lt["adjustment_id"], take, lt["unit_cost_usd"]))
        left -= take
    return picks, max(left, 0.0)


# ========================================================= transformations

def _recipe(graph: dict, key: str) -> dict:
    r = next((x for x in graph.get("prepared") or [] if x.get("key") == key), None)
    if r is None:
        raise HTTPException(404, f"no prepared-part recipe {key!r} in this process version")
    return r


def transform(db: Session, project_id: int, *, recipe_key: str, qty: float, scrap: float = 0.0,
              made_at: str = "", run_id: int | None = None, version_id: int | None = None,
              lots: dict | None = None, note: str = "", actor: str = "",
              dry_run: bool = True) -> dict:
    """Carry out a recipe: draw its inputs for `qty + scrap` units, deposit `qty`.

    Dry run by default. The plan lists every draw with its price, the output
    lot's value, and any shortage; a shortage refuses the write with a 409 —
    the same rule as every other draw in the platform (a run cannot draw what
    was never bought). `lots` maps an internal input's component id to the lots
    it takes ([{adjustment_id, qty}]); without it the oldest open lot goes first.
    """
    if qty <= 0:
        raise HTTPException(422, "make at least one unit")
    if scrap < 0:
        raise HTTPException(422, "scrap cannot be negative")
    run = db.get(M.ProductionRun, run_id) if run_id else None
    if run_id and (run is None or run.project_id != project_id):
        raise HTTPException(404, "no such batch in this project")
    if version_id:
        v = db.get(M.ProcessVersion, version_id)
        if v is None or v.project_id != project_id or v.status != "published":
            raise HTTPException(422, "a transformation runs under a PUBLISHED version of this "
                                     "project's process")
    else:
        v = version_for_run(db, run) if run is not None else current_version(db, project_id)
    if v is None or v.status != "published":
        raise HTTPException(409, "this project has no published process yet")
    graph = _graph(v)
    r = _recipe(graph, recipe_key)
    out_cid = int(r["output_component_id"])
    made_at = made_at or _today()
    units = qty + scrap
    # Whose stock the inputs come from and the output goes to (decision 0064):
    # the batch's company, else the project's owner on the day.
    from . import companies as _co

    owner = _co.owner_on(db, project_id, made_at)
    tcompany = (run.company_id if run is not None and run.company_id else
                owner.id if owner else None)
    scope = run_actuals.stock_scope(db, tcompany)

    pool = run_actuals.pool_state(db, project_id, as_of=made_at, company_id=scope)
    names = _part_names(db, {out_cid} | {c for c, _m in map(input_ref, r.get("inputs") or []) if c})
    draws: list[dict] = []
    problems: list[dict] = []
    for inp in r.get("inputs") or []:
        cid, mpn = input_ref(inp)
        need = float(inp.get("qty") or 0) * units
        comp = db.get(M.Component, cid) if cid else None
        label = input_label(inp, names)
        if comp is not None and comp.internal:
            picks, uncovered = _pick_lots(db, cid, need, (lots or {}).get(str(cid))
                                          or (lots or {}).get(cid), company_id=scope)
            for aid, q, unit in picks:
                draws.append({"component_id": cid, "name": label, "qty": round(q, 6),
                              "unit_cost_usd": unit, "value_usd": round(q * unit, 4),
                              "lot_adjustment_id": aid, "internal": True})
            if uncovered > EPS:
                problems.append({"component_id": cid, "name": label, "needed": round(need, 6),
                                 "short": round(uncovered, 6),
                                 "problem": "not enough of this prepared part in its lots"})
        else:
            probe = type("P", (), {"component_id": cid, "mpn": "" if cid else mpn, "lcsc": ""})()
            avg = pool.get(run_actuals._key(probe), {}).get("avg_usd", 0.0) or 0.0
            draws.append({"component_id": cid, "mpn": "" if cid else mpn, "name": label,
                          "qty": round(need, 6),
                          "unit_cost_usd": round(avg, 8), "value_usd": round(need * avg, 4),
                          "lot_adjustment_id": None, "internal": False})
            if avg <= 0:
                problems.append({"component_id": cid, "name": label, "problem": "unpriced",
                                 "detail": "the pool has no price for this part on that date"})

    # Decision 0073: the bought inputs come from their lots, oldest first, at
    # their cost; the prepared lot's value is then the lots' value.
    from . import lots as _lots

    problems += _lots.fifo_price(db, [d for d in draws if not d["internal"]], as_of=made_at, company_id=scope)
    if _lots.lot_pricing_on():
        problems = [p for p in problems if not (p.get("problem") == "unpriced"
                                                and any(d.get("bindings") and d["component_id"] == p["component_id"]
                                                        for d in draws))]

    shortages = run_actuals.check_shortages(db, [
        {"component_id": d["component_id"], "mpn": d.get("mpn", ""), "lcsc": "", "qty": d["qty"],
         "date": made_at, "label": d["name"]} for d in draws if not d["internal"]],
        company_id=scope)
    input_value = round(sum(d["value_usd"] for d in draws), 6)
    plan = {
        "dry_run": dry_run, "process_version_id": v.id, "version_no": v.version_no,
        "recipe_key": recipe_key, "recipe_label": r.get("label") or recipe_key,
        "output": {"component_id": out_cid, "name": names.get(out_cid, {}).get("name"),
                   "qty": qty, "scrap": scrap,
                   "value_usd": round(input_value, 4),
                   "unit_cost_usd": round(input_value / qty, 6)},
        "made_at": made_at, "run_id": run.id if run else None,
        "draws": draws, "input_value_usd": round(input_value, 4),
        "shortages": shortages,
        "problems": [p for p in problems if p.get("problem") != "unpriced"],
        "unpriced": [p for p in problems if p.get("problem") == "unpriced"],
    }
    if dry_run:
        return plan
    if shortages or plan["problems"]:
        raise HTTPException(409, {"error": "the inputs are not in stock — enter the missing "
                                           "purchase, make the missing prepared part first, or record "
                                           "a stock adjustment", "plan": plan})

    t = M.ProcessTransformation(
        project_id=project_id, process_version_id=v.id, recipe_key=recipe_key,
        recipe_label=(r.get("label") or recipe_key)[:200], output_component_id=out_cid,
        qty=qty, scrap=scrap, production_run_id=run.id if run else None, made_at=made_at,
        input_value_usd=input_value, note=(note or "")[:500],
        actor=actor)
    db.add(t)
    db.flush()
    for d in draws:
        c = M.ComponentConsumption(
            run_id=None, component_id=d["component_id"], mpn=d.get("mpn", ""), lcsc="", qty=d["qty"],
            unit_cost_usd=d["unit_cost_usd"], basis=BASIS_TRANSFORMATION, consumed_at=made_at,
            transformation_id=t.id, company_id=tcompany,
            note=f"input of {t.recipe_label} (transformation #{t.id})"[:500])
        db.add(c)
        db.flush()
        if d.get("bindings"):
            _lots.bind(db, c, d)
        if d["lot_adjustment_id"]:
            db.add(M.ComponentConsumptionLot(
                consumption_id=c.id, lot_adjustment_id=d["lot_adjustment_id"], qty=d["qty"],
                unit_cost_usd=d["unit_cost_usd"], source="manual",
                note=f"transformation #{t.id}"))
    out = M.ComponentStockAdjustment(
        project_id=project_id, component_id=out_cid, mpn="", lcsc="", qty_delta=qty,
        unit_cost_usd=round(input_value / qty, 8), reason="transformation",
        adjusted_at=made_at, actor=actor, transformation_id=t.id, company_id=tcompany,
        note=f"{t.recipe_label}: {qty:g} made" + (f", {scrap:g} scrapped" if scrap else ""))
    db.add(out)
    db.flush()
    t.output_adjustment_id = out.id
    db.flush()
    plan["transformation_id"] = t.id
    plan["output"]["lot_adjustment_id"] = out.id
    return plan


def void_transformation(db: Session, t: M.ProcessTransformation, *, reason: str,
                        actor: str) -> dict:
    """Undo a transformation: void its input draws and remove its output lot.

    Refused once anything drew from the output lot — the inputs cannot be
    removed from under stock somebody already used (decision 0040, carried
    through the prepared part). The output adjustment is DELETED, not
    countered: a negative counter-entry would read as lost stock of the part, and nothing
    references the row once no draw is bound to it. `stock_adjustments` is a
    journalled table, so the deletion stays reversible."""
    if t.voided_at is not None:
        raise HTTPException(409, "already voided")
    if not (reason or "").strip():
        raise HTTPException(422, "say why it is voided")
    if t.output_adjustment_id and _bound(db, [t.output_adjustment_id]).get(
            t.output_adjustment_id, 0.0) > EPS:
        raise HTTPException(409, "units of this transformation's output have been drawn — "
                                 "void those draws (or the later transformation) first")
    aimed = (db.query(M.RunCostLine)
             .filter(M.RunCostLine.transformation_id == t.id,
                     M.RunCostLine.voided_at.is_(None)).count())
    if aimed:
        raise HTTPException(409, f"{aimed} invoice position(s) are aimed at this transformation "
                                 "as its conversion cost — point them elsewhere first")
    now = utcnow()
    for c in db.query(M.ComponentConsumption).filter_by(transformation_id=t.id,
                                                       voided_at=None).all():
        c.voided_at = now
        c.void_reason = "transformation voided"
    out = db.get(M.ComponentStockAdjustment, t.output_adjustment_id) if t.output_adjustment_id else None
    if out is not None:
        db.delete(out)
    t.voided_at = now
    t.void_reason = reason[:200]
    db.flush()
    return {"id": t.id, "voided": True}


def transformation_json(db: Session, t: M.ProcessTransformation, names: dict | None = None,
                        conversion: dict[int, float] | None = None) -> dict:
    names = names if names is not None else _part_names(db, {t.output_component_id})
    conversion = conversion if conversion is not None else run_actuals.conversion_by_transformation(db)
    conv = conversion.get(t.id, 0.0)
    run = db.get(M.ProductionRun, t.production_run_id) if t.production_run_id else None
    return {
        "id": t.id, "process_version_id": t.process_version_id, "recipe_key": t.recipe_key,
        "recipe_label": t.recipe_label, "output_component_id": t.output_component_id,
        "output_name": (names.get(t.output_component_id) or {}).get("name"),
        "qty": t.qty, "scrap": t.scrap, "made_at": t.made_at,
        "run_id": t.production_run_id, "run_label": run.label if run else None,
        "input_value_usd": round(t.input_value_usd or 0, 4),
        "conversion_usd": round(conv, 4),
        "unit_cost_usd": round(((t.input_value_usd or 0) + conv) / t.qty, 6) if t.qty else None,
        "output_adjustment_id": t.output_adjustment_id, "note": t.note, "actor": t.actor,
        "voided": t.voided_at is not None, "void_reason": t.void_reason,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


# ===================================================== banking and stocktake

def _require_prepared(db: Session, project_id: int, component_id: int) -> M.Component:
    comp = db.get(M.Component, component_id)
    if comp is None or not comp.internal:
        raise HTTPException(422, "that part is not an internal part")
    known: set[int] = set()
    for v in versions(db, project_id):
        known |= prepared_outputs(_graph(v))
    if component_id not in known:
        raise HTTPException(422, f"{comp.name!r} is not a prepared part of this project's process")
    return comp


def bank(db: Session, project_id: int, *, component_id: int, qty: float,
         unit_cost_usd: float = 0.0, at: str = "", note: str = "", actor: str = "",
         dry_run: bool = True) -> dict:
    """Enter units of a prepared part that exist but that no transformation
    made — the found historical WIP. A lot, at `unit_cost_usd` (zero by default: its
    component cost already sits in the closed batch that bought it, and closed
    books do not move — decision 0058, More Information). The note must say
    where the units came from."""
    comp = _require_prepared(db, project_id, component_id)
    if qty <= 0:
        raise HTTPException(422, "bank at least one unit")
    if unit_cost_usd < 0:
        raise HTTPException(422, "a value cannot be negative")
    if not (note or "").strip():
        raise HTTPException(422, "say where these units came from (which batch holds their cost)")
    plan = {"dry_run": dry_run, "component_id": comp.id, "name": comp.name, "qty": qty,
            "unit_cost_usd": unit_cost_usd, "value_usd": round(qty * unit_cost_usd, 4),
            "at": at or _today()}
    if dry_run:
        return plan
    a = M.ComponentStockAdjustment(
        project_id=project_id, component_id=comp.id, mpn="", lcsc="", qty_delta=qty,
        unit_cost_usd=unit_cost_usd, reason="opening_balance", adjusted_at=plan["at"],
        actor=actor, note=note[:500])
    db.add(a)
    db.flush()
    plan["lot_adjustment_id"] = a.id
    return plan


def write_off(db: Session, project_id: int, *, lot_adjustment_id: int, qty: float,
              at: str = "", charge_run_id: int | None = None, note: str = "",
              actor: str = "", dry_run: bool = True) -> dict:
    """Units of a prepared-part lot that broke or were not found. A draw bound to the
    lot, so the lot's remaining falls with the pool's quantity; charged to
    `charge_run_id` when a batch is to carry the loss, else to nobody."""
    adj = db.get(M.ComponentStockAdjustment, lot_adjustment_id)
    if adj is None or (adj.qty_delta or 0) <= 0:
        raise HTTPException(404, "no such lot")
    _require_prepared(db, project_id, adj.component_id)
    if qty <= 0:
        raise HTTPException(422, "write off at least one unit")
    left = lot_remaining(db, adj.id)
    if qty - left > EPS:
        raise HTTPException(409, f"lot A{adj.id} holds {left:g}, not {qty:g}")
    run = db.get(M.ProductionRun, charge_run_id) if charge_run_id else None
    if charge_run_id and (run is None or run.project_id != project_id):
        raise HTTPException(404, "no such batch in this project")
    if (run is not None and run_actuals.stock_scope(db, adj.company_id) is not None
            and run.company_id != adj.company_id):
        raise HTTPException(409, f"lot A{adj.id} is another company's stock than {run.label}'s "
                                 "(decision 0064) — transfer it first")
    if not (note or "").strip():
        raise HTTPException(422, "say why these units are written off")
    unit = lot_json(adj, (0.0, 0.0), run_actuals.conversion_extras_usd(db).get(adj.id, 0.0))[
        "unit_cost_usd"]
    plan = {"dry_run": dry_run, "lot_adjustment_id": adj.id, "qty": qty,
            "unit_cost_usd": unit, "value_usd": round(qty * unit, 4),
            "charge_run_id": charge_run_id, "at": at or _today()}
    if dry_run:
        return plan
    c = M.ComponentConsumption(
        run_id=charge_run_id, component_id=adj.component_id, mpn="", lcsc="", qty=qty,
        unit_cost_usd=unit, basis=BASIS_WRITEOFF, consumed_at=plan["at"],
        company_id=adj.company_id,  # the lot's own stock (decision 0064)
        note=f"written off from lot A{adj.id}: {note}"[:500])
    db.add(c)
    db.flush()
    db.add(M.ComponentConsumptionLot(consumption_id=c.id, lot_adjustment_id=adj.id, qty=qty,
                                     unit_cost_usd=unit, source="manual", note="write-off"))
    db.flush()
    plan["consumption_id"] = c.id
    return plan


def stocktake(db: Session, project_id: int, *, component_id: int, counted: float,
              at: str = "", note: str = "", actor: str = "", dry_run: bool = True) -> dict:
    """Count a prepared part's shelf and correct the books to it (decision 0058 §7, the
    shape of 0057): fewer than the books → write the difference off, oldest
    lot first; more → bank the difference as a zero-value lot."""
    comp = _require_prepared(db, project_id, component_id)
    if counted < 0:
        raise HTTPException(422, "a count cannot be negative")
    if not (note or "").strip():
        raise HTTPException(422, "say who counted and how")
    # The shelf of the company that owns the project on the day (decision 0064).
    lots = prepared_lots(db, {comp.id}, open_only=True,
                         company_id=run_actuals.project_scope(db, project_id, at or None))
    on_books = round(sum(lt["remaining"] for lt in lots), 6)
    delta = round(counted - on_books, 6)
    plan: dict = {"dry_run": dry_run, "component_id": comp.id, "name": comp.name,
                  "on_books": on_books, "counted": counted, "delta": delta, "steps": []}
    if abs(delta) <= EPS:
        return plan
    if delta > 0:
        plan["steps"].append(bank(db, project_id, component_id=comp.id, qty=delta, at=at,
                                  note=f"stocktake: {delta:g} more on the shelf than on the "
                                       f"books. {note}", actor=actor, dry_run=dry_run))
        return plan
    left = -delta
    for lt in lots:
        if left <= EPS:
            break
        take = min(left, lt["remaining"])
        plan["steps"].append(write_off(db, project_id, lot_adjustment_id=lt["adjustment_id"],
                                       qty=take, at=at,
                                       note=f"stocktake: not on the shelf. {note}",
                                       actor=actor, dry_run=dry_run))
        left -= take
    return plan


# ================================================================ read side

def prepared_view(db: Session, project_id: int, v: M.ProcessVersion | None) -> dict:
    """The prepared parts of `v`: what is on hand, what it is worth, and its lots
    — plus the pool figures of every bought part a step or a recipe uses."""
    g = _graph(v)
    outs = prepared_outputs(g)
    used = {c for s in g["steps"] for c, _m in map(input_ref, s.get("inputs") or []) if c}
    used |= {c for r in g["prepared"] for c, _m in map(input_ref, r.get("inputs") or []) if c}
    scope = run_actuals.project_scope(db, project_id)   # the owner's stock today (0064)
    pool = run_actuals.pool_state(db, project_id, company_id=scope)
    names = _part_names(db, outs | used)
    lots = prepared_lots(db, outs, company_id=scope)
    by_comp: dict[int, list[dict]] = defaultdict(list)
    for lt in lots:
        by_comp[lt["component_id"]].append(lt)

    def pool_row(cid: int) -> dict:
        p = pool.get(f"c{cid}") or {}
        return {"qty": round(p.get("qty", 0.0), 4), "value_usd": round(p.get("value_usd", 0.0), 4),
                "avg_usd": round(p.get("avg_usd", 0.0), 6)}

    parts = []
    for cid in sorted(outs):
        own = by_comp.get(cid, [])
        parts.append({"component_id": cid, "name": (names.get(cid) or {}).get("name"),
                      "recipes": [r.get("key") for r in g["prepared"]
                                  if int(r.get("output_component_id") or 0) == cid],
                      "on_hand": round(sum(lt["remaining"] for lt in own if lt["open"]), 6),
                      "value_usd": round(sum(lt["value_remaining_usd"] for lt in own
                                             if lt["open"]), 4),
                      "lots": own})
    inputs = {str(cid): {**(names.get(cid) or {"id": cid}), "pool": pool_row(cid)}
              for cid in sorted(used - outs)}
    return {"prepared": parts, "inputs": inputs}


def deployments_for(db: Session, project_id: int) -> list[dict]:
    """The project's deployments a bench step may name (decision 0060)."""
    out = []
    for d in (db.query(M.Deployment).filter_by(project_id=project_id)
              .order_by(M.Deployment.name).all()):
        cur = db.get(M.DeploymentVersion, d.current_version_id) if d.current_version_id else None
        out.append({"id": d.id, "name": d.name, "kind": d.kind or "flash",
                    "current_version_id": d.current_version_id,
                    "current_version_no": cur.version_no if cur else None})
    return out


def step_for_deployment(graph: dict, kind: str, deployment_id: int | None) -> dict | None:
    """The process step of `kind` a bench run of `deployment_id` performs: the
    one that names that deployment, else one that names none. A step that names
    ANOTHER deployment is not this run's step (decision 0060)."""
    steps = [s for s in graph.get("steps") or [] if s.get("kind") == kind]
    if deployment_id:
        named = [s for s in steps if s.get("deployment_id") and int(s["deployment_id"]) == int(deployment_id)]
        if named:
            return named[0]
    return next((s for s in steps if not s.get("deployment_id")), None)


def process_materials(db: Session, project_id: int, as_of: str | None = None,
                      version: M.ProcessVersion | None = None) -> list | None:
    """The materials one device of the project uses, read off its process
    (decisions 0060, 0061): every input of every step on the main route — the
    label of the label step too — a prepared part expanded into its recipe's
    inputs. None when the project has no
    published process — its materials are then the project's extra BOM items.
    `version` is the one a batch pinned; without it, the current one.

    Shaped like `ProjectExtraBomItem` rows, so the BOM pricing reads both the
    same way. A part with no price ladder carries the pool's average price."""
    from types import SimpleNamespace

    v = version or current_version(db, project_id)
    if v is None:
        return None
    graph = _graph(v)
    smap = step_map(graph)
    recipes = {int(r["output_component_id"]): r for r in graph["prepared"] if r.get("output_component_id")}
    pool = run_actuals.pool_state(db, project_id, as_of=as_of,   # priced on the batch's date
                                  company_id=run_actuals.project_scope(db, project_id, as_of))
    cids = {c for s in graph["steps"] for c, _m in map(input_ref, s.get("inputs") or []) if c}
    cids |= {c for r in recipes.values() for c, _m in map(input_ref, r.get("inputs") or []) if c}
    names = _part_names(db, cids)
    out = []
    for key in graph["route"]:
        st = smap.get(key)
        if not st or (st.get("kind") or "step") in NO_INPUT_KINDS:
            continue
        slabel = st.get("label") or key
        for i, inp in enumerate(st.get("inputs") or []):
            cid, _mpn = input_ref(inp)
            qty = float(inp.get("qty") or 0)
            recipe = recipes.get(cid) if cid else None
            parts = ([(rin, qty * float(rin.get("qty") or 0)) for rin in recipe.get("inputs") or []]
                     if recipe else [(inp, qty)])
            for j, (pin, q) in enumerate(parts):
                pcid, pmpn = input_ref(pin)
                probe = SimpleNamespace(component_id=pcid, mpn="" if pcid else pmpn, lcsc="")
                avg = (pool.get(run_actuals._key(probe)) or {}).get("avg_usd")
                out.append(SimpleNamespace(
                    id=None, key=f"p{key}.{i}.{j}", step=key,
                    label=f"{slabel}: {input_label(pin, names)}", qty=q, component_id=pcid,
                    manufacturer="", mpn=pmpn, unit_price=avg, currency="USD",
                    price_source="pool average" if avg is not None else None,
                    notes=(f"process v{v.version_no}, step {slabel!r}"
                           + (f", inside {recipe.get('label') or recipe.get('key')!r}" if recipe else ""))))
    return out
