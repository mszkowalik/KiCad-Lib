"""Production processes (decisions 0058, 0059): the versioned process document,
prepared parts and their transformations, and crafting a batch's twins.

Every write takes `dry_run` (default true) where it moves stock, records the
signed-in person with `acting_name()`, and writes an audit row. The rules live
in `services/process.py`; this file only parses and shapes.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import process as svc
from ..services import twins as twins_svc
from .util import acting_name, audit

router = APIRouter(prefix="/api", tags=["process"])


def _project(db: Session, project_id: int) -> M.Project:
    p = db.get(M.Project, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p


def _version(db: Session, version_id: int) -> M.ProcessVersion:
    v = db.get(M.ProcessVersion, version_id)
    if v is None:
        raise HTTPException(404, "no such process version")
    return v


def _run(db: Session, run_id: int) -> M.ProductionRun:
    r = db.get(M.ProductionRun, run_id)
    if r is None:
        raise HTTPException(404, "batch not found")
    return r


# ------------------------------------------------------------------ the tab

@router.get("/projects/{project_id}/process")
def get_process(project_id: int, version_id: int | None = None, db: Session = Depends(get_db)):
    """Everything the Process tab draws: the versions, the one shown (the
    current published version by default, else the draft), its prepared parts
    with stock and lots, the recent transformations, and the internal parts a
    recipe can make."""
    _project(db, project_id)
    vs = svc.versions(db, project_id)
    if version_id is not None:
        shown = _version(db, version_id)
        if shown.project_id != project_id:
            raise HTTPException(404, "no such process version in this project")
    else:
        shown = svc.current_version(db, project_id) or next(
            (v for v in vs if v.status == "draft"), None)
    ts = (db.query(M.ProcessTransformation).filter_by(project_id=project_id)
          .order_by(M.ProcessTransformation.made_at.desc(), M.ProcessTransformation.id.desc())
          .limit(200).all())
    names = svc._part_names(db, {t.output_component_id for t in ts})
    from ..services import run_actuals

    conversion = run_actuals.conversion_by_transformation(db)
    return {
        "versions": [{"id": v.id, "version_no": v.version_no, "status": v.status,
                      "comment": v.comment, "created_by": v.created_by,
                      "approved_by": v.approved_by,
                      "published_at": v.published_at.isoformat() if v.published_at else None}
                     for v in vs],
        "current_version_id": (svc.current_version(db, project_id) or M.ProcessVersion()).id,
        "shown": svc.version_json(db, shown, with_check=True) if shown else None,
        "stock": svc.prepared_view(db, project_id, shown) if shown else None,
        "transformations": [svc.transformation_json(db, t, names, conversion) for t in ts],
        "internal_parts": [{"id": c.id, "name": c.name} for c in svc.internal_parts(db)],
        "deployments": svc.deployments_for(db, project_id),
    }


# ------------------------------------------------------------- the document

class ComposeIn(BaseModel):
    from_version_id: int | None = None


class DraftPatch(BaseModel):
    graph: dict | None = None
    comment: str | None = Field(default=None, max_length=500)


class PublishIn(BaseModel):
    comment: str | None = Field(default=None, max_length=500)


@router.post("/projects/{project_id}/process/versions")
def compose_version(project_id: int, body: ComposeIn, db: Session = Depends(get_db)):
    _project(db, project_id)
    v = svc.compose(db, project_id, actor=acting_name(), from_version_id=body.from_version_id)
    audit(db, "process.compose", "process_version", v.id,
          {"project_id": project_id, "version_no": v.version_no,
           "from_version_id": body.from_version_id}, actor=acting_name())
    db.commit()
    return svc.version_json(db, v, with_check=True)


@router.get("/process-versions/{version_id}")
def get_version(version_id: int, db: Session = Depends(get_db)):
    return svc.version_json(db, _version(db, version_id), with_check=True)


@router.patch("/process-versions/{version_id}")
def patch_version(version_id: int, body: DraftPatch, db: Session = Depends(get_db)):
    """Edit a draft in place. Every answer carries the machine check, so the
    editor shows exactly what publishing would refuse."""
    v = svc.update_draft(db, _version(db, version_id), graph=body.graph, comment=body.comment)
    db.commit()
    return svc.version_json(db, v, with_check=True)


@router.post("/process-versions/{version_id}/publish")
def publish_version(version_id: int, body: PublishIn, db: Session = Depends(get_db)):
    v = svc.publish(db, _version(db, version_id), actor=acting_name(), comment=body.comment)
    audit(db, "process.publish", "process_version", v.id,
          {"project_id": v.project_id, "version_no": v.version_no, "comment": v.comment},
          actor=acting_name())
    db.commit()
    return svc.version_json(db, v, with_check=True)


@router.delete("/process-versions/{version_id}")
def delete_version(version_id: int, db: Session = Depends(get_db)):
    v = _version(db, version_id)
    info = {"project_id": v.project_id, "version_no": v.version_no}
    svc.delete_draft(db, v)
    audit(db, "process.delete_draft", "process_version", version_id, info, actor=acting_name())
    db.commit()
    return {"deleted": version_id}


# --------------------------------------------------------- internal parts

class InternalPartIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.post("/internal-parts")
def create_internal_part(body: InternalPartIn, db: Session = Depends(get_db)):
    comp = svc.create_internal_part(db, body.name)
    audit(db, "component.create_internal", "component", comp.id, {"name": comp.name},
          actor=acting_name())
    db.commit()
    return {"id": comp.id, "name": comp.name}


# -------------------------------------------------------- transformations

class LotPick(BaseModel):
    adjustment_id: int
    qty: float


class TransformIn(BaseModel):
    recipe_key: str
    qty: float
    scrap: float = 0.0
    made_at: str = ""
    run_id: int | None = None
    version_id: int | None = None
    #: component id (as a string) -> the lots that input takes
    lots: dict[str, list[LotPick]] | None = None
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/projects/{project_id}/process/transform")
def transform(project_id: int, body: TransformIn, db: Session = Depends(get_db)):
    """Carry out a recipe. Dry run by default: the answer is the plan — every
    draw with its price, the output lot's value, and any shortage."""
    _project(db, project_id)
    lots = ({k: [p.model_dump() for p in v] for k, v in body.lots.items()}
            if body.lots else None)
    res = svc.transform(db, project_id, recipe_key=body.recipe_key, qty=body.qty,
                        scrap=body.scrap, made_at=body.made_at, run_id=body.run_id,
                        version_id=body.version_id, lots=lots, note=body.note,
                        actor=acting_name(), dry_run=body.dry_run)
    if not body.dry_run:
        audit(db, "process.transform", "process_transformation", res["transformation_id"],
              {"project_id": project_id, "recipe_key": body.recipe_key, "qty": body.qty,
               "scrap": body.scrap, "run_id": body.run_id,
               "input_value_usd": res["input_value_usd"],
               "output_lot": res["output"].get("lot_adjustment_id")}, actor=acting_name())
        db.commit()
    else:
        db.rollback()
    return res


@router.get("/process-transformations")
def list_transformations(db: Session = Depends(get_db)):
    """Live transformations of every project, newest first — what an invoice
    position can be aimed at as a conversion cost (decision 0058 §4)."""
    ts = (db.query(M.ProcessTransformation).filter(M.ProcessTransformation.voided_at.is_(None))
          .order_by(M.ProcessTransformation.made_at.desc(), M.ProcessTransformation.id.desc())
          .limit(500).all())
    projects = {p.id: p.name for p in db.query(M.Project).all()}
    names = svc._part_names(db, {t.output_component_id for t in ts})
    return [{"id": t.id, "project_id": t.project_id, "project": projects.get(t.project_id, ""),
             "recipe_label": t.recipe_label, "made_at": t.made_at, "qty": t.qty,
             "output_name": (names.get(t.output_component_id) or {}).get("name")} for t in ts]


class VoidIn(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


@router.post("/process-transformations/{transformation_id}/void")
def void_transformation(transformation_id: int, body: VoidIn, db: Session = Depends(get_db)):
    t = db.get(M.ProcessTransformation, transformation_id)
    if t is None:
        raise HTTPException(404, "no such transformation")
    res = svc.void_transformation(db, t, reason=body.reason, actor=acting_name())
    audit(db, "process.void", "process_transformation", t.id,
          {"project_id": t.project_id, "reason": body.reason}, actor=acting_name())
    db.commit()
    return res


# ------------------------------------------------- banking and stocktake

class BankIn(BaseModel):
    component_id: int
    qty: float
    unit_cost_usd: float = 0.0
    at: str = ""
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/projects/{project_id}/process/bank")
def bank(project_id: int, body: BankIn, db: Session = Depends(get_db)):
    """Enter units of a prepared part that exist but that no transformation
    made — found historical work, zero value by default."""
    _project(db, project_id)
    res = svc.bank(db, project_id, component_id=body.component_id, qty=body.qty,
                   unit_cost_usd=body.unit_cost_usd, at=body.at, note=body.note,
                   actor=acting_name(), dry_run=body.dry_run)
    if not body.dry_run:
        audit(db, "process.bank", "component", body.component_id,
              {"project_id": project_id, **{k: res[k] for k in
                                            ("qty", "unit_cost_usd", "at", "lot_adjustment_id")},
               "note": body.note}, actor=acting_name())
        db.commit()
    return res


class StocktakeIn(BaseModel):
    component_id: int
    counted: float
    at: str = ""
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/projects/{project_id}/process/stocktake")
def stocktake(project_id: int, body: StocktakeIn, db: Session = Depends(get_db)):
    _project(db, project_id)
    res = svc.stocktake(db, project_id, component_id=body.component_id, counted=body.counted,
                        at=body.at, note=body.note, actor=acting_name(), dry_run=body.dry_run)
    if not body.dry_run:
        audit(db, "process.stocktake", "component", body.component_id,
              {"project_id": project_id, "on_books": res["on_books"], "counted": body.counted,
               "delta": res["delta"], "note": body.note}, actor=acting_name())
        db.commit()
    return res


class WriteOffIn(BaseModel):
    lot_adjustment_id: int
    qty: float
    at: str = ""
    charge_run_id: int | None = None
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/projects/{project_id}/process/write-off")
def write_off(project_id: int, body: WriteOffIn, db: Session = Depends(get_db)):
    """Units of a prepared-part lot that broke — the bench's "scrap one from the lot",
    charged to the batch when one is named."""
    _project(db, project_id)
    res = svc.write_off(db, project_id, lot_adjustment_id=body.lot_adjustment_id, qty=body.qty,
                        at=body.at, charge_run_id=body.charge_run_id, note=body.note,
                        actor=acting_name(), dry_run=body.dry_run)
    if not body.dry_run:
        audit(db, "process.write_off", "component_stock_adjustment", body.lot_adjustment_id,
              {"project_id": project_id, "qty": body.qty, "charge_run_id": body.charge_run_id,
               "note": body.note}, actor=acting_name())
        db.commit()
    return res


# ------------------------------------------------------- crafting a batch
#
# Decision 0059. Every write takes `dry_run` (default true): the answer is the
# plan. An unnamed twin is never addressed by id — a step takes "N from this
# stack"; a named one is addressed by its DEVICE (id, or a scanned code).


def _commit_or_rollback(db: Session, dry_run: bool, action: str, run_id: int, details: dict) -> None:
    if dry_run:
        db.rollback()
        return
    audit(db, action, "production_run", run_id, details, actor=acting_name())
    db.commit()


@router.get("/runs/{run_id}/craft")
def craft(run_id: int, db: Session = Depends(get_db)):
    """Everything the batch's crafting screen draws: stacks, devices, gaps,
    the bench stack, the origin cost share and the recent clicks."""
    return twins_svc.craft_view(db, _run(db, run_id))


class ReceiveIn(BaseModel):
    qty: int
    made_at: str = ""
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/receive")
def craft_receive(run_id: int, body: ReceiveIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    res = twins_svc.receive(db, r, qty=body.qty, made_at=body.made_at, note=body.note,
                            actor=acting_name(), dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.receive", r.id, {"qty": body.qty})
    return res


class Selection(BaseModel):
    """Which units: a stack and a quantity (before programming), or devices by
    id or scanned code (after), with how they were chosen."""
    stack: str = ""
    qty: int = 0
    device_ids: list[int] | None = None
    codes: list[str] | None = None
    chosen: str = ""


class StepIn(Selection):
    step_key: str
    made_at: str = ""
    #: prepared part component id (as a string) -> the lot (adjustment id) it takes
    lots: dict[str, int] | None = None
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/step")
def craft_step(run_id: int, body: StepIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    res = twins_svc.apply_step(db, r, step_key=body.step_key, stack=body.stack, qty=body.qty,
                               device_ids=body.device_ids, codes=body.codes, chosen=body.chosen,
                               made_at=body.made_at, lots=body.lots, note=body.note,
                               actor=acting_name(), dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.step", r.id,
                        {"step": body.step_key, "units": res["units"], "chosen": res["chosen"],
                         "value_usd": res["value_usd"], "step_run_id": res.get("step_run_id")})
    return res


class ScrapIn(Selection):
    reason: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/scrap")
def craft_scrap(run_id: int, body: ScrapIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    res = twins_svc.scrap(db, r, stack=body.stack, qty=body.qty, device_ids=body.device_ids,
                          codes=body.codes, chosen=body.chosen, reason=body.reason,
                          actor=acting_name(), dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.scrap", r.id,
                        {"units": res["units"], "reason": body.reason})
    return res


class FinishIn(BaseModel):
    device_ids: list[int] | None = None
    codes: list[str] | None = None
    chosen: str = ""
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/finish")
def craft_finish(run_id: int, body: FinishIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    res = twins_svc.finish(db, r, device_ids=body.device_ids, codes=body.codes,
                           chosen=body.chosen, note=body.note, actor=acting_name(),
                           dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.finish", r.id, {"units": res["units"]})
    return res


class MergeIn(BaseModel):
    stack: str
    device_ids: list[int] | None = None
    codes: list[str] | None = None
    chosen: str = ""
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/merge")
def craft_merge(run_id: int, body: MergeIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    res = twins_svc.merge(db, r, stack=body.stack, device_ids=body.device_ids, codes=body.codes,
                          chosen=body.chosen, actor=acting_name(), dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.merge", r.id,
                        {"units": res["units"], "stack": body.stack})
    return res


class FoundIn(BaseModel):
    qty: int = 0
    done: list[str] = []
    origin_run_id: int
    device_ids: list[int] | None = None
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/found")
def craft_found(run_id: int, body: FoundIn, db: Session = Depends(get_db)):
    """Units that exist but have no twin — found at a stock count, or devices
    made before twins. They enter at zero value (0059 §15)."""
    r = _run(db, run_id)
    res = twins_svc.enter_found(db, r, qty=body.qty, done=body.done,
                                origin_run_id=body.origin_run_id, device_ids=body.device_ids,
                                note=body.note, actor=acting_name(), dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.found", r.id,
                        {"units": res["units"], "done": res["done"],
                         "origin_run_id": body.origin_run_id, "note": body.note})
    return res


@router.get("/runs/{run_id}/craft/cost-by-step")
def craft_cost_by_step(run_id: int, db: Session = Depends(get_db)):
    """The batch's cost, step by step, with the board and its assembly read
    from the assembly step (decision 0060)."""
    r = _run(db, run_id)
    twins_svc.crafted_version(db, r)
    return twins_svc.cost_by_step(db, r)


class AssemblyIn(BaseModel):
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/assembly")
def craft_assembly(run_id: int, body: AssemblyIn, db: Session = Depends(get_db)):
    """Record, or extend, the board's assembly step from the batch's assembly
    order (decision 0060). Receiving the boards does this by itself; this is
    for a position imported after the boards were received."""
    r = _run(db, run_id)
    res = twins_svc.record_assembly(db, r, actor=acting_name())
    res["dry_run"] = body.dry_run
    _commit_or_rollback(db, body.dry_run, "craft.assembly", r.id,
                        {k: res.get(k) for k in ("status", "step_run_id", "lines_linked", "draws_linked")})
    return res


class CostsIn(BaseModel):
    step_run_ids: list[int] = []
    step_keys: list[str] = []
    line_ids: list[int]
    unlink: bool = False
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/costs")
def craft_costs(run_id: int, body: CostsIn, db: Session = Depends(get_db)):
    """Say which step clicks an invoice position paid for, or take the link
    away (decisions 0060, 0061). The money stays charged to the batch."""
    r = _run(db, run_id)
    res = twins_svc.link_costs(db, r, step_run_ids=body.step_run_ids, step_keys=body.step_keys,
                               line_ids=body.line_ids, unlink=body.unlink, actor=acting_name(),
                               dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.costs", r.id,
                        {"step_run_ids": body.step_run_ids, "step_keys": body.step_keys,
                         "line_ids": body.line_ids,
                         "unlink": body.unlink})
    return res


class SpareIn(BaseModel):
    qty: int
    done: list[str] = []
    note: str = Field(default="", max_length=500)


class RebuildIn(BaseModel):
    version_id: int | None = None
    assume: list[str] = []
    draw: list[str] = []
    since: dict[str, str] = {}
    costs: dict[str, list[str]] = {}
    spares: list[SpareIn] = []
    dry_run: bool = True


@router.post("/runs/{run_id}/rebuild")
def rebuild_batch(run_id: int, body: RebuildIn, db: Session = Depends(get_db)):
    """Give a batch made before twins its twins, from its records (decision
    0060). Dry run by default; the answer is the plan and the check."""
    from ..services import twin_rebuild

    r = _run(db, run_id)
    res = twin_rebuild.rebuild(db, r, version_id=body.version_id, assume=body.assume,
                               draw=body.draw, since=body.since, costs=body.costs, spares=[s.model_dump() for s in body.spares],
                               actor=acting_name(), dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.rebuild", r.id,
                        {"version": res.get("process_version"), "twins": res.get("twins"),
                         "assume": body.assume, "draw": body.draw, "since": body.since, "costs": body.costs,
                         "spares": [s.model_dump() for s in body.spares]})
    return res


class UndoIn(BaseModel):
    dry_run: bool = True


@router.post("/runs/{run_id}/rebuild/undo")
def undo_rebuild(run_id: int, body: UndoIn, db: Session = Depends(get_db)):
    from ..services import twin_rebuild

    r = _run(db, run_id)
    res = twin_rebuild.undo(db, r, actor=acting_name(), dry_run=body.dry_run)
    _commit_or_rollback(db, body.dry_run, "craft.rebuild.undo", r.id, res)
    return res


@router.get("/runs/{run_id}/bench-stacks")
def bench_stacks(run_id: int, db: Session = Depends(get_db)):
    """The stacks this batch's programming bench may name twins from, and the
    one it uses now. Empty for a batch that is not crafted."""
    r = _run(db, run_id)
    prog = None
    if r.process_version_id:
        v = db.get(M.ProcessVersion, r.process_version_id)
        step = svc.step_of_kind(svc._graph(v), "program") if v else None
        dep = db.get(M.Deployment, int(step["deployment_id"])) if step and step.get("deployment_id") else None
        if dep is not None:
            # Decision 0060: the bench defaults to the procedure the process names.
            prog = {"deployment_id": dep.id, "name": dep.name, "current_version_id": dep.current_version_id}
    return {"run_id": r.id, "crafted": bool(r.process_version_id),
            "selected": r.bench_stack or None, "left": twins_svc.bench_stack_left(db, r),
            "stacks": twins_svc.bench_stacks(db, r), "program_deployment": prog}


class BenchStackIn(BaseModel):
    stack: str | None = None


@router.put("/runs/{run_id}/bench-stack")
def set_bench_stack(run_id: int, body: BenchStackIn, db: Session = Depends(get_db)):
    """The stack the bench programs from — chosen once per tray, and again when
    one is used up. `null` = none: a device programmed then is a gap."""
    r = _run(db, run_id)
    was = r.bench_stack or None
    res = twins_svc.set_bench_stack(db, r, body.stack)
    audit(db, "run.bench_stack", "production_run", r.id, {"from": was, "to": body.stack},
          actor=acting_name())
    db.commit()
    return res


@router.get("/devices/{device_id}/twin")
def device_twin(device_id: int, db: Session = Depends(get_db)):
    """How a device was built: its twin's steps, parts and price. `twin: null`
    for a device made before twins."""
    if db.get(M.DeviceUnit, device_id) is None:
        raise HTTPException(404, "no such device")
    tw = db.query(M.Twin).filter_by(device_unit_id=device_id).first()
    return {"device_id": device_id, "twin": twins_svc.twin_json(db, tw) if tw else None}
