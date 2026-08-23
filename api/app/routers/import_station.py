"""Import station endpoints. POST /api/import is DESTRUCTIVE (wipe & reload)
by explicit design — the UI double-confirms before calling it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import models as M
from ..db import SessionLocal
from ..services.importer import IMPORT_STATE, start_import

router = APIRouter(prefix="/api/import", tags=["import"])


@router.post("")
def trigger_import():
    if not start_import():
        raise HTTPException(409, "an import is already running")
    return {"status": "started"}


@router.post("/sync")
def trigger_sync():
    """RETIRED (2026-08-24). The YAML sync diffs Sources/*.yaml against the DB
    and files DRAFT component versions — and drafts no longer have an approval
    path anywhere: every write in the platform publishes immediately and the
    Proposals view is gone. Running it would leave rows nothing can act on.

    The destructive full import (`POST /api/import`) still works, because it
    writes published rows directly. To re-run either against the old YAML
    sources, check out `archive/yaml-library` in the repo the compose file
    mounts at /repo."""
    raise HTTPException(410, "the YAML sync filed draft proposals, and there is no "
                             "approval path any more — use POST /api/import (destructive, "
                             "writes published rows) or the archive/yaml-library branch")


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
