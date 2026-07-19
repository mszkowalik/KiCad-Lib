"""Datasheet endpoints: versioned local storage, per-version files, and the
background fetch-all worker. See services/datasheet_store.py for semantics."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.datasheet_store import (
    FETCH_STATE,
    current_version,
    fetch_datasheet,
    start_fetch_all,
    store_upload,
)
from ..services.mirror import top_level_of, update_mirror_symbols

router = APIRouter(prefix="/api/datasheets", tags=["datasheets"])


class FetchAllBody(BaseModel):
    mode: str = "missing"  # "missing" | "all"


@router.post("/fetch-all")
def fetch_all(body: FetchAllBody):
    if body.mode not in ("missing", "all"):
        raise HTTPException(422, "mode must be 'missing' or 'all'")
    if not start_fetch_all(body.mode):
        raise HTTPException(409, "a fetch-all run is already in progress")
    return {"status": "started", "mode": body.mode}


@router.get("/fetch-status")
def fetch_status(db: Session = Depends(get_db)):
    total = db.query(M.Datasheet).filter(M.Datasheet.archived.is_(False),
                                         M.Datasheet.source_url.isnot(None)).count()
    with_copy = db.query(M.Datasheet).filter(M.Datasheet.archived.is_(False),
                                             M.Datasheet.current_version_id.isnot(None)).count()
    return {**FETCH_STATE, "datasheets_total": total, "datasheets_with_local_copy": with_copy}


@router.post("/{ds_id}/fetch")
def fetch(ds_id: int, db: Session = Depends(get_db)):
    ds = db.get(M.Datasheet, ds_id)
    if ds is None or ds.archived:
        raise HTTPException(404, "datasheet not found")
    if not ds.source_url:
        raise HTTPException(422, "datasheet has no source URL to fetch")
    try:
        result = fetch_datasheet(db, ds)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"download failed: {e}") from e

    # First local copy switches the generated library link from the internet
    # URL to the local file — refresh the affected mirror library.
    if result.get("result") == "new_version" and result.get("version_no") == 1:
        comp = db.get(M.Component, ds.component_id)
        if comp is not None and comp.current_version_id is not None:
            cv = db.get(M.ComponentVersion, comp.current_version_id)
            if cv is not None:
                update_mirror_symbols(db, settings, {top_level_of(cv.category).name})

    cur = current_version(ds)
    return {
        **result,
        "has_file": cur is not None,
        "filename": cur.filename if cur else None,
        "content_type": cur.content_type if cur else None,
        "size_bytes": cur.size_bytes if cur else None,
        "fetched_at": cur.fetched_at.isoformat() if cur else None,
    }


@router.post("/{ds_id}/upload")
async def upload(ds_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Replace/store this row's file from a local upload (versioned like a
    fetch, but non-PDF content is versioned too — uploads are deliberate)."""
    ds = db.get(M.Datasheet, ds_id)
    if ds is None or ds.archived:
        raise HTTPException(404, "datasheet not found")
    data = await file.read()
    if not data:
        raise HTTPException(422, "uploaded file is empty")
    result = store_upload(db, ds, data, file.filename, file.content_type)

    # First local copy switches the generated library link to the local file.
    if result.get("result") == "new_version" and result.get("version_no") == 1:
        comp = db.get(M.Component, ds.component_id)
        if comp is not None and comp.current_version_id is not None:
            cv = db.get(M.ComponentVersion, comp.current_version_id)
            if cv is not None:
                update_mirror_symbols(db, settings, {top_level_of(cv.category).name})

    cur = current_version(ds)
    return {
        **result,
        "has_file": cur is not None,
        "filename": cur.filename if cur else None,
        "content_type": cur.content_type if cur else None,
        "size_bytes": cur.size_bytes if cur else None,
        "fetched_at": cur.fetched_at.isoformat() if cur else None,
    }


@router.get("/{ds_id}/file")
def file(ds_id: int, db: Session = Depends(get_db)):
    ds = db.get(M.Datasheet, ds_id)
    if ds is None:
        raise HTTPException(404, "datasheet not found")
    cur = current_version(ds)
    if cur is None:
        raise HTTPException(404, "no local copy — fetch it first")
    return _serve(cur)


@router.get("/{ds_id}/versions/{version_no}/file")
def version_file(ds_id: int, version_no: int, db: Session = Depends(get_db)):
    ds = db.get(M.Datasheet, ds_id)
    if ds is None:
        raise HTTPException(404, "datasheet not found")
    v = next((x for x in ds.versions if x.version_no == version_no), None)
    if v is None:
        raise HTTPException(404, "datasheet version not found")
    return _serve(v)


def _serve(v: M.DatasheetVersion) -> Response:
    return Response(
        content=v.data,
        media_type=v.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{v.filename or "datasheet"}"'},
    )
