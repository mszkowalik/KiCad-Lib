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
        # A project whose published versions are all history has no current
        # one: show the newest, so "Make current" is reachable (decision 0074).
        shown = (svc.current_version(db, project_id) or next((v for v in vs if v.status == "draft"), None)
                 or next((v for v in vs if v.status == "published"), None))
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
    #: How older devices were made: published for their batches to pin, never
    #: current (decision 0074).
    historical: bool = False


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
    v = svc.publish(db, _version(db, version_id), actor=acting_name(), comment=body.comment,
                    historical=body.historical)
    audit(db, "process.publish", "process_version", v.id,
          {"project_id": v.project_id, "version_no": v.version_no, "comment": v.comment,
           "historical": body.historical}, actor=acting_name())
    db.commit()
    return svc.version_json(db, v, with_check=True)


@router.post("/process-versions/{version_id}/make-current")
def make_current(version_id: int, db: Session = Depends(get_db)):
    """Point the project at this published version (decision 0074). Batches
    keep the version they pinned. The audit row names the previous one, which
    is the way back."""
    v = _version(db, version_id)
    prev = svc.current_version(db, v.project_id)
    svc.make_current(db, v)
    audit(db, "process.make_current", "process_version", v.id,
          {"project_id": v.project_id, "version_no": v.version_no,
           "previous_version_id": prev.id if prev else None,
           "previous_version_no": prev.version_no if prev else None}, actor=acting_name())
    db.commit()
    return {"current_version_id": v.id, "version_no": v.version_no,
            "previous_version_id": prev.id if prev else None}


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


def _click(db: Session, r: M.ProductionRun, dry_run: bool, action: str, write, details) -> dict:
    """One crafting click. A real one is one journal batch, so a wrong click
    is undone whole from the batch screen or the ledger (decision 0074): its
    twins, step links, draws and lot bindings. `details(res)` is the audit."""
    from ..services import journal

    if dry_run:
        # A savepoint, not a rollback of the session: only this plan is undone.
        sp = db.begin_nested()
        try:
            return write()
        finally:
            sp.rollback()
    actor = acting_name()
    with journal.batch(db, kind=action, source_ref=f"run:{r.id}", actor=actor) as h:
        res = write()
    audit(db, action, "production_run", r.id, {**details(res), "batch_id": h["batch_id"]}, actor=actor)
    db.commit()
    return {**res, "batch_id": h["batch_id"]}


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
    return _click(db, r, body.dry_run, "craft.receive", lambda: twins_svc.receive(
        db, r, qty=body.qty, made_at=body.made_at, note=body.note, actor=acting_name(), dry_run=body.dry_run),
        lambda res: {"qty": body.qty})


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
    #: why a person states a test, mark or label step no bench run recorded
    #: (decision 0074); empty for an ordinary batch step
    stated: str = Field(default="", max_length=300)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/step")
def craft_step(run_id: int, body: StepIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    return _click(db, r, body.dry_run, "craft.step", lambda: twins_svc.apply_step(
        db, r, step_key=body.step_key, stack=body.stack, qty=body.qty, device_ids=body.device_ids,
        codes=body.codes, chosen=body.chosen, made_at=body.made_at, lots=body.lots, note=body.note,
        actor=acting_name(), dry_run=body.dry_run, stated=body.stated),
        lambda res: {"step": body.step_key, "units": res["units"], "chosen": res["chosen"],
                     "value_usd": res["value_usd"], "step_run_id": res.get("step_run_id"),
                     "stated": body.stated})


class ScrapIn(Selection):
    reason: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/scrap")
def craft_scrap(run_id: int, body: ScrapIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    return _click(db, r, body.dry_run, "craft.scrap", lambda: twins_svc.scrap(
        db, r, stack=body.stack, qty=body.qty, device_ids=body.device_ids, codes=body.codes,
        chosen=body.chosen, reason=body.reason, actor=acting_name(), dry_run=body.dry_run),
        lambda res: {"units": res["units"], "reason": body.reason})


class ReopenIn(BaseModel):
    device_ids: list[int] | None = None
    codes: list[str] | None = None
    chosen: str = ""
    reason: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/reopen")
def craft_reopen(run_id: int, body: ReopenIn, db: Session = Depends(get_db)):
    """Finished units back into work, with the reason (decision 0074). They
    ship again only after a new finish."""
    r = _run(db, run_id)
    return _click(db, r, body.dry_run, "craft.reopen", lambda: twins_svc.reopen(
        db, r, device_ids=body.device_ids, codes=body.codes, chosen=body.chosen, reason=body.reason,
        actor=acting_name(), dry_run=body.dry_run),
        lambda res: {"units": res["units"], "reason": body.reason})


class SwapIn(BaseModel):
    device_ids: list[int] | None = None
    codes: list[str] | None = None
    stack: str
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/swap")
def craft_swap(run_id: int, body: SwapIn, db: Session = Depends(get_db)):
    """The bench named the device from the wrong pile: it takes a twin of
    `stack`, and its old twin goes back unnamed (decision 0074)."""
    r = _run(db, run_id)
    return _click(db, r, body.dry_run, "craft.swap", lambda: twins_svc.swap_twin(
        db, r, device_ids=body.device_ids, codes=body.codes, stack=body.stack, actor=acting_name(),
        dry_run=body.dry_run),
        lambda res: {k: res.get(k) for k in ("device", "from_twin", "to_twin", "back_to_stack")})


class RelinkIn(BaseModel):
    programming_run_id: int
    device_ids: list[int] | None = None
    codes: list[str] | None = None
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/relink")
def craft_relink(run_id: int, body: RelinkIn, db: Session = Depends(get_db)):
    """A bench run filed against the wrong device moves to the right one, with
    the steps it recorded (decision 0074). `run_id` is the batch of the right
    device's twin."""
    r = _run(db, run_id)
    return _click(db, r, body.dry_run, "craft.relink", lambda: twins_svc.relink_run(
        db, r, programming_run_id=body.programming_run_id, device_ids=body.device_ids, codes=body.codes,
        dry_run=body.dry_run),
        lambda res: {k: res.get(k) for k in ("programming_run_id", "from_device", "to_device", "steps")})


class FinishIn(BaseModel):
    device_ids: list[int] | None = None
    codes: list[str] | None = None
    chosen: str = ""
    note: str = Field(default="", max_length=500)
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/finish")
def craft_finish(run_id: int, body: FinishIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    return _click(db, r, body.dry_run, "craft.finish", lambda: twins_svc.finish(
        db, r, device_ids=body.device_ids, codes=body.codes, chosen=body.chosen, note=body.note,
        actor=acting_name(), dry_run=body.dry_run),
        lambda res: {"units": res["units"]})


class MergeIn(BaseModel):
    stack: str
    device_ids: list[int] | None = None
    codes: list[str] | None = None
    chosen: str = ""
    dry_run: bool = True


@router.post("/runs/{run_id}/craft/merge")
def craft_merge(run_id: int, body: MergeIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    return _click(db, r, body.dry_run, "craft.merge", lambda: twins_svc.merge(
        db, r, stack=body.stack, device_ids=body.device_ids, codes=body.codes, chosen=body.chosen,
        actor=acting_name(), dry_run=body.dry_run),
        lambda res: {"units": res["units"], "stack": body.stack})


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
    return _click(db, r, body.dry_run, "craft.found", lambda: twins_svc.enter_found(
        db, r, qty=body.qty, done=body.done, origin_run_id=body.origin_run_id, device_ids=body.device_ids,
        note=body.note, actor=acting_name(), dry_run=body.dry_run),
        lambda res: {"units": res["units"], "done": res["done"], "origin_run_id": body.origin_run_id,
                     "note": body.note})


@router.get("/runs/{run_id}/craft/cost-by-step")
def craft_cost_by_step(run_id: int, db: Session = Depends(get_db)):
    """The batch's cost, step by step, with the board and its assembly read
    from the assembly step (decision 0060)."""
    r = _run(db, run_id)
    twins_svc.crafted_version(db, r)
    return twins_svc.cost_by_step(db, r)


@router.get("/runs/{run_id}/craft/assembly/draft")
def craft_assembly_draft(run_id: int, db: Session = Depends(get_db)):
    """What "Record assembly" opens with: the step as it stands and every row
    not in it yet, pre-filled from the batch's records and the JLC data
    (decision 0072). Writes nothing."""
    return twins_svc.assembly_draft(db, _run(db, run_id))


class AssemblyPart(BaseModel):
    component_id: int | None = None
    mpn: str = ""
    lcsc: str = ""
    name: str = ""
    qty: float


class AssemblySupplied(BaseModel):
    parent_line_id: int
    lcsc: str = ""
    mpn: str = ""
    label: str = ""
    qty: float = 1.0
    unit_price: float = 0.0
    # "rounding": the share that closes a supplier's cent-rounded parts total
    # (supplier_parts.itemise); it goes to `pcba:other`, as the invoice's own
    # "supplier" split puts it.
    source: str = ""


class AssemblyReplacement(BaseModel):
    designator: str
    supplier_designator: str = ""
    specified_lcsc: str = ""
    specified_mpn: str = ""
    specified_component_id: int | None = None
    fitted_lcsc: str = ""
    fitted_mpn: str = ""
    fitted_component_id: int | None = None
    supplied_by: str = ""
    supplier_source: str = ""
    evidence: str = ""
    note: str = ""


class AssemblyIn(BaseModel):
    dry_run: bool = True
    made_at: str = ""
    assembler: str = Field(default="", max_length=120)
    reference: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=500)
    line_ids: list[int] = []
    draw_ids: list[int] = []
    parts: list[AssemblyPart] = []
    supplied: list[AssemblySupplied] = []
    replacements: list[AssemblyReplacement] = []


def _assembly(db: Session, r: M.ProductionRun, body: AssemblyIn, actor: str) -> dict:
    """The whole "Record assembly" write: the step, then the parts lumps split
    into what the assembler bought, then the replacements."""
    from . import run_costs as rc

    sr, res = twins_svc.apply_assembly(
        db, r, made_at=body.made_at, assembler=body.assembler, reference=body.reference, note=body.note,
        line_ids=body.line_ids, draw_ids=body.draw_ids, parts=[p.model_dump() for p in body.parts], actor=actor)
    lumps = {li.id: li for li in twins_svc.charged_lines(db, r) if twins_svc.is_parts_lump(db, li)}
    by_lump: dict[int, list[AssemblySupplied]] = {}
    for row in body.supplied:
        if row.parent_line_id not in lumps:
            raise HTTPException(422, f"position {row.parent_line_id} is not a parts total charged to {r.label}")
        by_lump.setdefault(row.parent_line_id, []).append(row)
    made, residual = 0, []
    for lump_id, rows in by_lump.items():
        lump = lumps[lump_id]
        out = rc.split_line_core(lump_id, rc.SplitIn(children=[
            rc.ChildIn(label="Rounding in the supplier's billed parts total", qty=1, unit_price=x.unit_price * x.qty,
                       plan_key="pcba:other", run_id=r.id, allocate=lump.allocate or "none")
            if x.source == "rounding" else
            rc.ChildIn(label=(x.label or " ".join(t for t in (x.lcsc, x.mpn) if t) or "part")[:300],
                       qty=x.qty, unit_price=x.unit_price, mpn=x.mpn, lcsc=x.lcsc,
                       plan_key=lump.plan_key, run_id=r.id, allocate=lump.allocate or "none")
            # Parts the assembler bought for this one batch (decision 0041):
            # they never enter the pool, so splitting them per part is allowed.
            for x in rows], allow_parts=True), db)
        for cid in out["created_ids"]:
            twins_svc.link_line(db, db.get(M.RunCostLine, cid), [sr])   # a no-op when inherited
        made += out["created"]
        if abs(out["residual"]) > 0.005:
            # What the ticked rows leave of the total is charged to nobody: the
            # register reports it, and so does this answer, before Apply.
            residual.append({"line_id": lump_id, "label": lump.label or "", "residual": out["residual"],
                             "currency": lump.currency or "USD"})
    for x in body.replacements:
        rc.new_substitution(db, r, rc.SubstitutionIn(
            designator=x.designator, supplier_designator=x.supplier_designator,
            specified_lcsc=x.specified_lcsc, specified_mpn=x.specified_mpn,
            specified_component_id=x.specified_component_id, fitted_lcsc=x.fitted_lcsc,
            fitted_mpn=x.fitted_mpn, fitted_component_id=x.fitted_component_id,
            supplied_by=x.supplied_by, supplier_source=x.supplier_source,
            evidence=x.evidence or (f"recorded with the assembly step #{sr.id}"), note=x.note,
            source="supplier" if twins_svc.assembly_orders(db, r) else "us"), actor, step_run_id=sr.id)
    db.flush()
    return {**res, "supplied_children": made, "supplied_residual": residual,
            "replacements_recorded": len(body.replacements)}


@router.post("/runs/{run_id}/craft/assembly")
def craft_assembly(run_id: int, body: AssemblyIn, db: Session = Depends(get_db)):
    """Record, or add to, the board's assembly step with what the person
    ticked in "Record assembly" (decision 0072). Nothing records it on its
    own: not receiving the boards, not applying the JLC order. Dry run by
    default: the figures are exact, then everything is rolled back. A real
    write is one journal batch, so "Undo assembly" reverses it whole."""
    from ..services import journal

    r = _run(db, run_id)
    actor = acting_name()
    if body.dry_run:
        # A savepoint, not a rollback of the session: only this plan is undone.
        sp = db.begin_nested()
        try:
            res = _assembly(db, r, body, actor)
        finally:
            sp.rollback()
        return {**res, "dry_run": True, "batch_id": None}
    with journal.batch(db, kind="craft.assembly", source_ref=f"run:{r.id}", actor=actor,
                       summary={"assembler": body.assembler, "reference": body.reference}) as h:
        res = _assembly(db, r, body, actor)
    audit(db, "craft.assembly", "production_run", r.id,
          {k: res.get(k) for k in ("status", "step_run_id", "units", "lines_linked", "draws_linked",
                                   "draws_written", "supplied_children", "replacements_recorded")}
          | {"batch_id": h["batch_id"], "assembler": body.assembler, "reference": body.reference},
          actor=actor)
    db.commit()
    return {**res, "dry_run": False, "batch_id": h["batch_id"]}


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
    return _click(db, r, body.dry_run, "craft.costs", lambda: twins_svc.link_costs(
        db, r, step_run_ids=body.step_run_ids, step_keys=body.step_keys, line_ids=body.line_ids,
        unlink=body.unlink, actor=acting_name(), dry_run=body.dry_run),
        lambda res: {"step_run_ids": body.step_run_ids, "step_keys": body.step_keys,
                     "line_ids": body.line_ids, "unlink": body.unlink})


class RepinIn(BaseModel):
    version_id: int
    dry_run: bool = True


@router.post("/runs/{run_id}/process-version")
def repin_batch(run_id: int, body: RepinIn, db: Session = Depends(get_db)):
    """Move a batch to another published version of its process (decision
    0074). Refused on a closed batch, and when a twin of the batch has done a
    step the target lacks. The audit row names the previous version, which is
    the way back."""
    r = _run(db, run_id)
    prev = r.process_version_id
    res = twins_svc.repin(db, r, body.version_id, dry_run=body.dry_run)
    if not body.dry_run:
        audit(db, "craft.repin", "production_run", r.id,
              {"from_version_id": prev, "to_version_id": body.version_id,
               "from_version": res["from_version"], "to_version": res["to_version"]}, actor=acting_name())
        db.commit()
    return res


class SpareIn(BaseModel):
    qty: int
    done: list[str] = []
    note: str = Field(default="", max_length=500)


class DevicesIn(BaseModel):
    """Which devices of the batch a statement names: ids, scanned codes, a
    programmed date range (both ends inclusive), or all when it names none."""
    device_ids: list[int] = []
    codes: list[str] = []
    since: str = ""
    until: str = ""


class OriginIn(DevicesIn):
    """These devices were built on boards of `from_run_id` (rebuilt first);
    null: their source batch is unknown, and their twins' notes say so."""
    from_run_id: int | None = None


class SettleIn(BaseModel):
    """A statement about one difference between drawn and needed parts:
    `draw` or `short` for a deficit, `return` or `loss` for a surplus."""
    step: str
    part: str = "*"
    how: str


class RebuildIn(BaseModel):
    version_id: int | None = None
    assume: list[str] | dict[str, DevicesIn] = []
    draw: list[str] = []
    since: dict[str, str] = {}
    until: dict[str, str] = {}
    costs: dict[str, list[str]] = {}
    spares: list[SpareIn] = []
    settle: list[SettleIn] = []
    tolerance: float = Field(default=0.0, ge=0)
    active: DevicesIn | None = None
    origins: list[OriginIn] = []
    append: bool = False
    dry_run: bool = True


@router.post("/runs/{run_id}/rebuild")
def rebuild_batch(run_id: int, body: RebuildIn, db: Session = Depends(get_db)):
    """Give a batch made before twins its twins, from its records (decision
    0060), or with `append` the devices that joined it since. Dry run by
    default: the answer is the per-device plan, the parts against the units
    and the money check. A real write is one journal batch."""
    from ..services import twin_rebuild

    r = _run(db, run_id)
    assume = body.assume if isinstance(body.assume, list) else {k: s.model_dump() for k, s in body.assume.items()}
    res = twin_rebuild.rebuild(
        db, r, version_id=body.version_id, assume=assume, draw=body.draw, since=body.since, until=body.until,
        costs=body.costs, spares=[s.model_dump() for s in body.spares], settle=[s.model_dump() for s in body.settle],
        tolerance=body.tolerance, active=body.active.model_dump() if body.active is not None else None,
        origins=[o.model_dump() for o in body.origins], append=body.append, actor=acting_name(),
        dry_run=body.dry_run)
    if not body.dry_run:
        # The dry run rolled its own savepoint back; nothing else is undone.
        audit(db, "craft.rebuild", "production_run", r.id,
              {"version": res.get("process_version"), "twins": res.get("twins"), "append": body.append,
               "batch_id": res.get("batch_id"), "inputs": body.model_dump(exclude={"dry_run"})},
              actor=acting_name())
        db.commit()
    return res


class UndoIn(BaseModel):
    dry_run: bool = True


@router.post("/runs/{run_id}/rebuild/undo")
def undo_rebuild(run_id: int, body: UndoIn, db: Session = Depends(get_db)):
    """Take a rebuild back, with the live clicks that stand on its twins. The
    dry run lists every click it takes back, or refuses by name."""
    from ..services import twin_rebuild

    r = _run(db, run_id)
    res = twin_rebuild.undo(db, r, actor=acting_name(), dry_run=body.dry_run)
    if not body.dry_run:
        audit(db, "craft.rebuild.undo", "production_run", r.id, res, actor=acting_name())
        db.commit()
    return res


class LinkRunsIn(BaseModel):
    dry_run: bool = True


@router.post("/projects/{project_id}/bench-runs/link-by-topic")
def link_bench_runs(project_id: int, body: LinkRunsIn, db: Session = Depends(get_db)):
    """Link the project's old marking and test runs that read no MAC to their
    device by the topic they captured, where exactly one device matches — the
    evidence a rebuild reads (decision 0061). Dry run by default."""
    from ..services import bench_links

    _project(db, project_id)
    res = bench_links.link_by_topic(db, project_id, dry_run=body.dry_run)
    if not body.dry_run:
        audit(db, "flasher.link_by_topic", "project", project_id,
              {"linked": [[x["run_id"], x["device_id"]] for x in res["linked"]]}, actor=acting_name())
        db.commit()
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
