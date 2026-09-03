"""Production runs: batches priced on demand from historical pricing at the
run's date (project_bom.run_effective), with price overrides, file
attachments (MinIO) and a serial-number registry."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import orders, production, project_bom, run_actuals, storage
from .util import audit

router = APIRouter(prefix="/api", tags=["production-runs"])

MAX_ATTACHMENT_MB = 100


def _run(db: Session, run_id: int) -> M.ProductionRun:
    r = db.get(M.ProductionRun, run_id)
    if r is None:
        raise HTTPException(404, "run not found")
    return r


def _pset_count(r: M.ProductionRun) -> int:
    from sqlalchemy.orm import object_session

    sess = object_session(r)
    if sess is None:
        return 0
    return sess.query(M.ProductionFileSet).filter_by(run_id=r.id).count()


def _run_snapshot_board(db: Session, r: M.ProductionRun) -> tuple[M.ProjectSnapshot | None, dict | None]:
    snap = db.get(M.ProjectSnapshot, r.snapshot_id) if r.snapshot_id else None
    if snap is None:
        return None, None
    board = next((b for b in snap.boards or [] if b["name"] == r.board), None)
    if board is None and snap.boards:
        board = snap.boards[0]
    return snap, board


def _run_json(r: M.ProductionRun, db: Session | None = None, with_detail: bool = False) -> dict:
    out = {
        "id": r.id,
        "project_id": r.project_id,
        "label": r.label,
        "snapshot_id": r.snapshot_id,
        "board": r.board,
        "variant": r.variant,
        "qty": r.qty,
        "status": r.status,
        "run_date": r.run_date,
        "notes": r.notes,
        "qty_good": r.qty_good,
        "qty_sold": r.qty_sold,
        "sale_unit_price": r.sale_unit_price,
        "sale_currency": r.sale_currency,
        "customer": r.customer,
        "order_ref": r.order_ref,
        "order_date": r.order_date,
        "created_at": r.created_at.isoformat(),
        "attachment_count": len(r.attachments),
        "device_count": len(r.devices),
        "production_set_count": _pset_count(r),
    }
    if with_detail and db is not None:
        # computed on demand from price history at the run's date — never stored
        out["effective"] = project_bom.run_effective(db, r)
        out["overrides"] = r.overrides or {}
        out["attachments"] = [
            {
                "id": a.id, "filename": a.filename, "content_type": a.content_type,
                "size_bytes": a.size_bytes, "uploaded_at": a.uploaded_at.isoformat(),
            }
            for a in r.attachments
        ]
        out["devices"] = [
            {"id": d.id, "serial": d.serial, "note": d.note, "created_at": d.created_at.isoformat()}
            for d in sorted(r.devices, key=lambda d: d.serial)
        ]
        # Decision 0003 §9: the orders this batch's units went to, `qty_sold`
        # derived from shipments, and what is still on the shelf.
        out["sales"] = orders.run_sales_json(db, r)
    return out


class RunIn(BaseModel):
    label: str
    snapshot_id: int | None = None
    board: str = ""
    variant: str = ""
    qty: int = 1
    status: str = "planned"
    run_date: str = ""
    notes: str = ""
    # the sale side — price PER DEVICE, so a quantity correction cannot silently
    # rewrite the revenue; empty currency inherits the project's display currency
    sale_unit_price: float | None = None
    sale_currency: str = ""
    qty_sold: int | None = None
    qty_good: int | None = None
    customer: str = ""
    order_ref: str = ""
    order_date: str = ""
    # explicit confirmation of the design-review warning (never stored) —
    # see the gate in create_run
    ack_review: bool = False


class RunPatch(BaseModel):
    label: str | None = None
    qty: int | None = None
    status: str | None = None
    run_date: str | None = None
    notes: str | None = None
    overrides: dict | None = None
    # Re-point a run at a newer design commit. Needed when a part moves INTO the
    # schematic (the Dongle enclosure became ENC1), because the run's planned BOM
    # comes from its snapshot and would otherwise never see it.
    snapshot_id: int | None = None
    sale_unit_price: float | None = None
    sale_currency: str | None = None
    qty_sold: int | None = None
    qty_good: int | None = None
    customer: str | None = None
    order_ref: str | None = None
    order_date: str | None = None


@router.get("/projects/{project_id}/runs")
def list_runs(project_id: int, db: Session = Depends(get_db)):
    if db.get(M.Project, project_id) is None:
        raise HTTPException(404, "project not found")
    runs = (
        db.query(M.ProductionRun).filter_by(project_id=project_id)
        .order_by(M.ProductionRun.created_at.desc()).all()
    )
    return [_run_json(r) for r in runs]


@router.post("/projects/{project_id}/runs")
def create_run(project_id: int, body: RunIn, db: Session = Depends(get_db)):
    project = db.get(M.Project, project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if body.qty < 1:
        raise HTTPException(422, "qty must be >= 1")
    if body.snapshot_id is not None:
        snap = db.get(M.ProjectSnapshot, body.snapshot_id)
        if snap is None or snap.project_id != project_id:
            raise HTTPException(404, "snapshot not found in this project")
        if snap.status != "ready":
            raise HTTPException(409, f"snapshot is {snap.status}")
        if body.board and body.board not in [b["name"] for b in snap.boards or []]:
            raise HTTPException(404, "board not in snapshot")
        # The design-review warning gate (user decision 2026-08-23): a run from
        # a snapshot with unsigned / unreviewed / deprecated components, or one
        # whose review was never completed, needs an EXPLICIT confirmation.
        # 409 + the issue list; the client re-posts with ack_review=true and
        # the acknowledgement is audited. Warning only — never a hard block.
        from .reviews import snapshot_review_issues

        issues = snapshot_review_issues(db, snap)
        problems = {
            "unsigned": issues["unsigned"],
            "unreviewed": issues["unreviewed"],
            "deprecated": issues["deprecated"],
            "changed_since_review": issues["changed_since_review"],
            "review_completed": issues["reviewed"],
        }
        needs_ack = (issues["unsigned"] or issues["unreviewed"] or issues["deprecated"]
                     or issues["changed_since_review"] or not issues["reviewed"])
        if needs_ack and not body.ack_review:
            raise HTTPException(409, {"review_warning": True, **problems})
        if needs_ack:
            audit(db, "production.review_ack", "project_snapshot", snap.id,
                  {"project_id": project_id, "label": body.label, **problems})
    data = body.model_dump()
    data.pop("ack_review", None)  # gate flag, not a run column
    r = M.ProductionRun(project_id=project_id, **data)
    db.add(r)
    db.flush()
    # economics are not stored — they resolve from price history at the
    # run's date whenever the run is read
    audit(db, "run.create", "production_run", r.id, {"project_id": project_id, "qty": r.qty})
    db.commit()
    # default production info: the repo's production/ dir (JLCPCB exporter
    # output) at the run's snapshot, when present
    snap, board = _run_snapshot_board(db, r)
    if snap is not None and board is not None:
        try:
            production.import_from_repo(db, r, snap, board)
        except Exception:
            db.rollback()
    return _run_json(r, db, with_detail=True)


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db)):
    return _run_json(_run(db, run_id), db, with_detail=True)


@router.patch("/runs/{run_id}")
def update_run(run_id: int, body: RunPatch, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    if body.label is not None and body.label.strip():
        r.label = body.label.strip()
    if body.qty is not None:
        if body.qty < 1:
            raise HTTPException(422, "qty must be >= 1")
        r.qty = body.qty
    if body.status is not None:
        r.status = body.status.strip()
    if body.run_date is not None:
        r.run_date = body.run_date.strip()
    if body.notes is not None:
        r.notes = body.notes
    if body.overrides is not None:
        r.overrides = body.overrides
    if body.snapshot_id is not None:
        snap = db.get(M.ProjectSnapshot, body.snapshot_id)
        if snap is None:
            raise HTTPException(404, "snapshot not found")
        if snap.project_id != r.project_id:
            raise HTTPException(422, f"snapshot {snap.id} belongs to project "
                                     f"{snap.project_id}, not {r.project_id}")
        # `overrides` keyed `b<snapshot_bom_line id>` point at the OLD snapshot's
        # line ids; a different snapshot has different ones, so a silent re-point
        # would quietly stop applying them.
        stale = [k for k in (r.overrides or {}) if k.startswith("b")]
        if stale and snap.id != r.snapshot_id:
            raise HTTPException(409, "this run has BOM-line overrides "
                                     f"({', '.join(sorted(stale))}) keyed to snapshot "
                                     f"{r.snapshot_id}; re-key or clear them before "
                                     "moving it to another snapshot")
        r.snapshot_id = snap.id
    # Sale side + yield. Applied only when explicitly present, so a PATCH that
    # touches the label can never blank out a price.
    sale = body.model_dump(exclude_unset=True)
    before = {}
    for field in ("sale_unit_price", "sale_currency", "qty_sold", "qty_good",
                  "customer", "order_ref", "order_date"):
        if field not in sale:
            continue
        value = sale[field]
        if isinstance(value, str):
            value = value.strip()
        if getattr(r, field) != value:
            before[field] = getattr(r, field)
            setattr(r, field, value)
    audit(db, "run.update", "production_run", r.id, before or None)
    db.commit()
    return _run_json(r, db, with_detail=True)


@router.delete("/runs/{run_id}")
def delete_run(run_id: int, db: Session = Depends(get_db)):
    import shutil

    from ..config import settings

    r = _run(db, run_id)
    # Financial records reference the run; deleting it would either violate the
    # FK or destroy cost history. Refuse and say what is in the way.
    blockers = {
        "cost documents": db.query(M.RunCostDocument).filter_by(run_id=run_id).count(),
        "cost lines": db.query(M.RunCostLine).filter_by(run_id=run_id).count(),
        "component draws": run_actuals.live_consumption(db, run_id=run_id).count(),
        "stock adjustments": db.query(M.ComponentStockAdjustment).filter_by(charge_run_id=run_id).count(),
    }
    held = {k: v for k, v in blockers.items() if v}
    if held:
        detail = ", ".join(f"{v} {k}" for k, v in held.items())
        raise HTTPException(409, f"run has financial records attached ({detail}) — remove or reassign them first")
    project_id = r.project_id
    for pset in db.query(M.ProductionFileSet).filter_by(run_id=run_id).all():
        shutil.rmtree(settings.data_dir / f"gerber-work/{pset.id}", ignore_errors=True)
        db.delete(pset)
    db.delete(r)
    audit(db, "run.delete", "production_run", run_id)
    db.commit()
    storage.delete_prefix(f"projects/{project_id}/runs/{run_id}/")
    return {"deleted": run_id}


# -------------------------------------------------------------- attachments

@router.post("/runs/{run_id}/attachments")
async def upload_attachment(run_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    r = _run(db, run_id)
    data = await file.read()
    if len(data) > MAX_ATTACHMENT_MB * 1024 * 1024:
        raise HTTPException(413, f"attachment larger than {MAX_ATTACHMENT_MB} MB")
    filename = file.filename or "file"
    key = f"projects/{r.project_id}/runs/{r.id}/{uuid.uuid4().hex[:12]}-{filename}"
    storage.put_bytes(key, data, file.content_type or "application/octet-stream")
    a = M.RunAttachment(
        run_id=r.id, filename=filename,
        content_type=file.content_type or "application/octet-stream",
        size_bytes=len(data), minio_key=key,
    )
    db.add(a)
    db.flush()
    audit(db, "run.attachment.add", "run_attachment", a.id, {"run_id": r.id, "filename": filename})
    db.commit()
    return {"id": a.id, "filename": a.filename, "size_bytes": a.size_bytes}


@router.get("/run-attachments/{attachment_id}")
def download_attachment(attachment_id: int, inline: bool = False,
                        db: Session = Depends(get_db)):
    """`inline=true` serves the bytes for display instead of download, so a
    scanned invoice opens in the browser's PDF viewer (the same treatment
    `datasheets.file` gives a datasheet) rather than landing in Downloads."""
    a = db.get(M.RunAttachment, attachment_id)
    if a is None:
        raise HTTPException(404, "attachment not found")
    data = storage.get_bytes(a.minio_key)
    if data is None:
        raise HTTPException(410, "attachment bytes missing from storage")
    disposition = "inline" if inline else "attachment"
    return Response(
        content=data,
        media_type=a.content_type,
        headers={"Content-Disposition": f'{disposition}; filename="{a.filename}"'},
    )


@router.delete("/run-attachments/{attachment_id}")
def delete_attachment(attachment_id: int, db: Session = Depends(get_db)):
    a = db.get(M.RunAttachment, attachment_id)
    if a is None:
        raise HTTPException(404, "attachment not found")
    key = a.minio_key
    db.delete(a)
    db.commit()
    storage.delete_prefix(key)
    return {"deleted": attachment_id}


# --------------------------------------------------------- production files

@router.get("/runs/{run_id}/production")
def run_production(run_id: int, db: Session = Depends(get_db)):
    """All production set versions + JLC assembly info from the current set
    + whether the repo offers a production/ dir to (re-)import."""
    r = _run(db, run_id)
    snap, board = _run_snapshot_board(db, r)
    return production.production_info(db, r, snap, board)


@router.post("/runs/{run_id}/production/import-repo")
def production_import_repo(run_id: int, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    snap, board = _run_snapshot_board(db, r)
    if snap is None or board is None:
        raise HTTPException(409, "run has no snapshot — upload files instead")
    pset = production.import_from_repo(db, r, snap, board)
    if pset is None:
        raise HTTPException(404, "no production/ directory in the repo at this snapshot")
    audit(db, "run.production.import", "production_set", pset.id, {"run_id": r.id})
    db.commit()
    return production.set_json(pset)


@router.post("/runs/{run_id}/production/upload")
async def production_upload(run_id: int, files: list[UploadFile] = File(...),
                            db: Session = Depends(get_db)):
    """User-provided production files (always allowed — overrides the repo
    version as a NEW set version; history is kept)."""
    r = _run(db, run_id)
    payload: list[tuple[str, bytes]] = []
    for f in files:
        data = await f.read()
        if len(data) > MAX_ATTACHMENT_MB * 1024 * 1024:
            raise HTTPException(413, f"{f.filename}: larger than {MAX_ATTACHMENT_MB} MB")
        if data:
            payload.append((f.filename or "file", data))
    if not payload:
        raise HTTPException(422, "no files uploaded")
    pset = production.create_set(db, r, "upload", payload, comment="manual upload")
    audit(db, "run.production.upload", "production_set", pset.id,
          {"run_id": r.id, "files": len(payload)})
    db.commit()
    return production.set_json(pset)


@router.post("/runs/{run_id}/production/generate")
def production_generate(run_id: int, db: Session = Depends(get_db)):
    """kicad-cli fab bundle (gerbers/drill/pos) as a new production set —
    for boards without a JLCPCB-exporter output."""
    r = _run(db, run_id)
    snap, board = _run_snapshot_board(db, r)
    if snap is None or board is None:
        raise HTTPException(409, "run has no snapshot to generate from")
    try:
        pset = production.generate_fab(db, r, snap, board)
    except Exception as e:
        raise HTTPException(502, f"fab generation failed: {e}") from e
    audit(db, "run.production.generate", "production_set", pset.id, {"run_id": r.id})
    db.commit()
    return production.set_json(pset)


@router.get("/production-files/{file_id}")
def production_file(file_id: int, db: Session = Depends(get_db)):
    f = db.get(M.ProductionFile, file_id)
    if f is None:
        raise HTTPException(404, "file not found")
    data = storage.get_bytes(f.minio_key)
    if data is None:
        raise HTTPException(410, "file bytes missing from storage")
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{f.filename}"'},
    )


@router.delete("/production-sets/{set_id}")
def delete_production_set(set_id: int, db: Session = Depends(get_db)):
    import shutil

    from ..config import settings

    pset = db.get(M.ProductionFileSet, set_id)
    if pset is None:
        raise HTTPException(404, "set not found")
    run = db.get(M.ProductionRun, pset.run_id)
    prefix = f"projects/{run.project_id}/runs/{run.id}/production/v{pset.version_no}/"
    shutil.rmtree(settings.data_dir / f"gerber-work/{pset.id}", ignore_errors=True)
    db.delete(pset)
    audit(db, "run.production.delete", "production_set", set_id, {"run_id": pset.run_id})
    db.commit()
    storage.delete_prefix(prefix)
    return {"deleted": set_id}


class GerberRenderIn(BaseModel):
    """Layer selection for the gerber viewer: filenames must be gerber/drill
    members of the set; colors are #RRGGBB(AA)."""

    files: list[dict]


@router.post("/production-sets/{set_id}/render")
def render_gerbers(set_id: int, body: GerberRenderIn, db: Session = Depends(get_db)):
    pset = db.get(M.ProductionFileSet, set_id)
    if pset is None:
        raise HTTPException(404, "set not found")
    run = db.get(M.ProductionRun, pset.run_id)
    valid = {f.filename for f in pset.files if f.kind in ("gerber", "drill")}
    selection = []
    for entry in body.files:
        name = str(entry.get("file", ""))
        if name not in valid:
            raise HTTPException(422, f"{name}: not a viewable gerber/drill file of this set")
        selection.append({"file": name, "color": str(entry.get("color", "#c83434"))})
    if not selection:
        raise HTTPException(422, "select at least one layer")
    try:
        data = production.render_gerber_svg(pset, run, selection)
    except Exception as e:
        raise HTTPException(502, f"gerber render failed: {e}") from e
    return Response(content=data, media_type="image/svg+xml")


# ------------------------------------------------------------------ devices

class DevicesIn(BaseModel):
    """Bulk add: one serial per line in `serials`, or a structured list."""

    serials: str = ""
    items: list[dict] | None = None


@router.post("/runs/{run_id}/devices")
def add_devices(run_id: int, body: DevicesIn, db: Session = Depends(get_db)):
    r = _run(db, run_id)
    existing = {d.serial for d in r.devices}
    to_add: list[tuple[str, str]] = []
    for line in (body.serials or "").splitlines():
        serial = line.strip()
        if serial:
            to_add.append((serial, ""))
    for item in body.items or []:
        serial = str(item.get("serial", "")).strip()
        if serial:
            to_add.append((serial, str(item.get("note", ""))))
    added = skipped = 0
    for serial, note in to_add:
        if serial in existing:
            skipped += 1
            continue
        db.add(M.RunDevice(run_id=r.id, serial=serial, note=note))
        existing.add(serial)
        added += 1
    audit(db, "run.devices.add", "production_run", r.id, {"added": added, "skipped": skipped})
    db.commit()
    return {"added": added, "skipped_duplicates": skipped, "total": len(existing)}


@router.delete("/run-devices/{device_id}")
def delete_device(device_id: int, db: Session = Depends(get_db)):
    d = db.get(M.RunDevice, device_id)
    if d is None:
        raise HTTPException(404, "device not found")
    db.delete(d)
    db.commit()
    return {"deleted": device_id}
