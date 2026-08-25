"""Datasheet endpoints: versioned local storage, per-version files, and the
background fetch-all worker. See services/datasheet_store.py for semantics."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.datasheet_pages import (
    INDEX_STATE,
    index_counts,
)
from ..services.datasheet_pages import outline as dp_outline
from ..services.datasheet_pages import page_text as dp_page_text
from ..services.datasheet_pages import search as dp_search
from ..services.datasheet_pages import start_index, stop_index
from ..services.datasheet_store import (
    CLASSIFY_STATE,
    BadDocument,
    FETCH_STATE,
    classify_counts,
    current_version,
    fetch_datasheet,
    find_broken,
    purge_broken,
    start_fetch_all,
    start_text_layer_classify,
    store_upload,
)
from ..services.mirror import top_level_of, update_mirror_symbols
from .util import actor_of

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
    return {**FETCH_STATE, "datasheets_total": total, "datasheets_with_local_copy": with_copy,
            "text_layer_counts": classify_counts(db)}


class ClassifyBody(BaseModel):
    mode: str = "missing"  # "missing" | "all"


@router.post("/classify")
def classify(body: ClassifyBody):
    """Re-run searchable-PDF detection. 'missing' picks up documents stored
    before the classifier existed (the startup sweep does this by itself);
    'all' re-reads every document, for when the thresholds change."""
    if body.mode not in ("missing", "all"):
        raise HTTPException(422, "mode must be 'missing' or 'all'")
    if not start_text_layer_classify(body.mode):
        raise HTTPException(409, "a classification run is already in progress")
    return {"status": "started", "mode": body.mode}


@router.get("/classify-status")
def classify_status(db: Session = Depends(get_db)):
    return {**CLASSIFY_STATE, "counts": classify_counts(db)}


@router.get("/broken")
def broken(db: Session = Depends(get_db)):
    """Every stored document nothing can open — empty files and PDFs that will
    not parse. A dry run: this is exactly what `DELETE /broken` would remove,
    with what each row falls back to afterwards."""
    return {"items": find_broken(db)}


@router.delete("/broken")
def purge(request: Request, db: Session = Depends(get_db)):
    """Remove every document `GET /broken` lists. Audited per row."""
    return purge_broken(db, actor=actor_of(request))


class IndexBody(BaseModel):
    mode: str = "missing"  # "missing" | "current" | "all"


@router.post("/index")
def index_pages(body: IndexBody):
    """Extract per-page text for the archived documents.

    'missing' is the retroactive backfill (versions never indexed) and is what
    startup arms by itself. 'current' does only the versions a datasheet
    actually serves, for a fast first pass. 'all' re-extracts everything, for
    when the extractor improves."""
    if body.mode not in ("missing", "current", "all"):
        raise HTTPException(422, "mode must be 'missing', 'current' or 'all'")
    if not start_index(body.mode):
        raise HTTPException(409, "a page-index run is already in progress")
    return {"status": "started", "mode": body.mode}


@router.post("/index/stop")
def index_stop():
    """Stop a running page-index sweep at the next version boundary. Never
    mid-document — a half-extracted document would read as complete."""
    if not stop_index():
        raise HTTPException(409, "no page-index run is in progress")
    return {"status": "stopping"}


@router.get("/index-status")
def index_status(db: Session = Depends(get_db)):
    return {**INDEX_STATE, **index_counts(db)}


@router.get("/search")
def search_pages(q: str, limit: int = 20, component: str = "",
                 include_superseded: bool = False, db: Session = Depends(get_db)):
    """Full-text search across archived datasheet pages. Returns the component,
    the document, the page number and the section it sits in — the answer to
    "which page do I read", not the page itself."""
    return dp_search(db, q, limit=limit, component=component,
                     include_superseded=include_superseded)


@router.get("/{ds_id}/outline")
def outline(ds_id: int, db: Session = Depends(get_db)):
    """The document's section map, plus which pages carry tables, which are
    drawings, and which cannot be read at all."""
    res = dp_outline(db, ds_id)
    if res is None:
        raise HTTPException(404, "datasheet not found, or it has no local copy")
    return res


@router.get("/{ds_id}/pages/{page_no}")
def page(ds_id: int, page_no: int, db: Session = Depends(get_db)):
    """One extracted page as markdown. A derived cache — see the
    `DatasheetPage` docstring on what it may not be trusted for."""
    res = dp_page_text(db, ds_id, page_no)
    if res is None:
        raise HTTPException(404, "page not indexed — run POST /api/datasheets/index")
    return res


@router.post("/{ds_id}/fetch")
def fetch(ds_id: int, db: Session = Depends(get_db)):
    ds = db.get(M.Datasheet, ds_id)
    if ds is None or ds.archived:
        raise HTTPException(404, "datasheet not found")
    if not ds.source_url:
        raise HTTPException(422, "datasheet has no source URL to fetch")
    try:
        # Explicit user action: download in full rather than trusting the
        # supplier's ETag — that is the point of clicking "re-fetch".
        result = fetch_datasheet(db, ds, conditional=False)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"download failed: {e}") from e
    if result.get("result") == "rejected":
        raise HTTPException(422, f"the downloaded file was refused: {result['reason']}")

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
    try:
        result = store_upload(db, ds, data, file.filename, file.content_type)
    except BadDocument as e:
        raise HTTPException(422, f"this file cannot be stored: {e}") from e

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
