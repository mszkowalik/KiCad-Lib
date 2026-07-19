"""Import station endpoints. POST /api/import is DESTRUCTIVE (wipe & reload)
by explicit design — the UI double-confirms before calling it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import models as M
from ..db import SessionLocal
from ..services.importer import IMPORT_STATE, start_import, start_sync

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("")
def trigger_import():
    if not start_import():
        raise HTTPException(409, "an import is already running")
    return {"status": "started"}


@router.post("/sync")
def trigger_sync():
    """Non-destructive: diff Sources/*.yaml against the DB and create draft
    proposals for new/changed components. Progress polled at /status like import."""
    if not start_sync():
        raise HTTPException(409, "an import or sync is already running")
    return {"status": "started"}


@router.get("/status")
def status():
    last_run = None
    try:
        db = SessionLocal()
        run = db.query(M.ImportRun).order_by(M.ImportRun.id.desc()).first()
        if run is not None:
            last_run = {
                "id": run.id,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                "status": run.status,
                "duration_s": run.duration_s,
                "report": run.report,
            }
        db.close()
    except Exception:
        pass  # table may not exist mid-wipe
    return {
        "running": IMPORT_STATE["running"],
        "stage": IMPORT_STATE["stage"],
        "started_at": IMPORT_STATE["started_at"],
        "error": IMPORT_STATE["error"],
        "report": IMPORT_STATE["report"],
        "last_run": last_run,
    }
