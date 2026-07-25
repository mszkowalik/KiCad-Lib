"""Versioned datasheet storage.

- Downloads are immutable DatasheetVersion rows; a NEW version is created only
  when the downloaded content's sha256 differs from the current one.
- When content changes on a datasheet of a component that has a published
  current version, the component is AUTO-BUMPED to a new published version
  (auto-managed lane — audited, created_by "system") so "which PDF was used in
  which component version" is always answerable via the pin table.
- A background worker fetches all missing (or all) datasheets.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from .. import models as M
from ..db import SessionLocal

log = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "curl/8.1"}  # some suppliers 403 unusual UAs

FETCH_STATE: dict = {"running": False, "mode": None, "done": 0, "total": 0,
                     "new_versions": 0, "unchanged": 0, "not_modified": 0, "errors": 0,
                     "started_at": None, "finished_at": None, "last_error": None,
                     "trigger": None, "next_nightly_at": None, "last_nightly_at": None}
_lock = threading.Lock()
_nightly_started = False


def _filename_from(resp: httpx.Response, url: str, fallback: str) -> str:
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r'filename\*?="?([^";]+)"?', cd)
    if m:
        return m.group(1).strip()
    tail = url.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return tail or fallback


def current_version(ds: M.Datasheet) -> M.DatasheetVersion | None:
    return next((v for v in ds.versions if v.id == ds.current_version_id), None)


def pin_datasheets(db: Session, cv: M.ComponentVersion) -> None:
    """Record which datasheet versions (PDF contents) this component version
    uses. Called on every component-version creation/approval."""
    sheets = (
        db.query(M.Datasheet)
        .filter_by(component_id=cv.component_id, archived=False)
        .all()
    )
    existing = {
        link.datasheet_id: link
        for link in db.query(M.ComponentVersionDatasheet).filter_by(component_version_id=cv.id)
    }
    for ds in sheets:
        link = existing.get(ds.id)
        if link is None:
            db.add(M.ComponentVersionDatasheet(
                component_version_id=cv.id, datasheet_id=ds.id,
                datasheet_version_id=ds.current_version_id,
            ))
        elif link.datasheet_version_id is None and ds.current_version_id is not None:
            link.datasheet_version_id = ds.current_version_id


def _bump_component_version(
    db: Session,
    ds: M.Datasheet,
    new_dv: M.DatasheetVersion,
    comment: str | None = None,
    created_by: str = "system",
) -> int | None:
    """Auto-create a new published component version recording the changed PDF."""
    comp = db.get(M.Component, ds.component_id)
    if comp is None or comp.current_version_id is None:
        return None
    cur = db.get(M.ComponentVersion, comp.current_version_id)
    if cur is None or cur.status != "published":
        return None
    new_no = max(v.version_no for v in comp.versions) + 1
    cv = M.ComponentVersion(
        component_id=comp.id, version_no=new_no,
        base_component=cur.base_component,
        symbol_version_id=cur.symbol_version_id,
        footprint_version_id=cur.footprint_version_id,
        category_id=cur.category_id,
        removed_properties=cur.removed_properties,
        status="published", created_by=created_by, approved_by="auto",
        comment=comment
        or f"Datasheet '{ds.label}' content changed → PDF v{new_dv.version_no}",
    )
    db.add(cv)
    db.flush()
    for p in cur.properties:
        db.add(M.ComponentProperty(
            component_version_id=cv.id, position=p.position, key=p.key,
            value=p.value, is_null=p.is_null, hide=p.hide,
            show_name=p.show_name, layout=p.layout,
        ))
    comp.current_version_id = cv.id
    pin_datasheets(db, cv)
    db.add(M.AuditLog(actor="system", action="component.datasheet_bump", entity_type="component",
                      entity_id=str(comp.id),
                      details={"component": comp.name, "version_no": new_no,
                               "datasheet_id": ds.id, "pdf_version": new_dv.version_no}))
    return new_no


def fetch_datasheet(db: Session, ds: M.Datasheet, conditional: bool = True) -> dict:
    """Download ds.source_url; create a new version only on content change.
    Returns a result dict; raises httpx.HTTPError on network failure.

    `conditional` replays the stored ETag / Last-Modified so a server that
    still has the same document answers 304 and we skip the download
    entirely — that is what makes a nightly re-check of every datasheet
    cheap. Pass False to force a full download (the manual "re-fetch"
    button), since a supplier can swap file content without touching the
    validators."""
    if not ds.source_url:
        return {"id": ds.id, "result": "no_url"}
    cur = current_version(ds)
    headers = dict(_HEADERS)
    if conditional and cur is not None:
        if cur.etag:
            headers["If-None-Match"] = cur.etag
        if cur.last_modified:
            headers["If-Modified-Since"] = cur.last_modified
    resp = httpx.get(ds.source_url, headers=headers, follow_redirects=True, timeout=60)
    if resp.status_code == 304:
        # The supplier confirms the document we hold is still current. A 304
        # carries no body, so never fall through to the download path — a
        # server that answers 304 unconditionally would otherwise store an
        # empty "new version".
        if cur is None:
            return {"id": ds.id, "result": "not_modified_no_copy"}
        cur.fetched_at = datetime.now(timezone.utc)
        db.commit()
        return {"id": ds.id, "result": "unchanged", "version_no": cur.version_no,
                "not_modified": True}
    resp.raise_for_status()
    data = resp.content
    sha = hashlib.sha256(data).hexdigest()
    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip() or None
    filename = _filename_from(resp, str(resp.url), f"{ds.label}.pdf")

    new_is_pdf = (content_type == "application/pdf") or data[:5] == b"%PDF-"
    etag = (resp.headers.get("etag") or "").strip() or None
    last_modified = (resp.headers.get("last-modified") or "").strip() or None

    if cur is not None and cur.sha256 == sha:
        cur.fetched_at = datetime.now(timezone.utc)  # bookkeeping: last verified
        # Learn validators the stored copy didn't have yet (or that rotated),
        # so the next nightly pass can settle this datasheet with a 304.
        cur.etag, cur.last_modified = etag, last_modified
        db.commit()
        return {"id": ds.id, "result": "unchanged", "version_no": cur.version_no}

    # Non-PDF sources (LCSC product pages etc.) serve dynamic HTML that
    # differs on EVERY download — versioning that would churn endlessly and
    # spam component bumps. Keep exactly one local copy for those; real
    # content versioning applies to PDFs (or when a page turns into a PDF).
    if cur is not None and not new_is_pdf:
        cur.fetched_at = datetime.now(timezone.utc)
        cur.etag, cur.last_modified = etag, last_modified
        db.commit()
        return {"id": ds.id, "result": "skipped_unstable_non_pdf", "version_no": cur.version_no,
                "looks_like_pdf": False}

    new_no = (cur.version_no if cur else 0) + 1
    dv = M.DatasheetVersion(
        datasheet_id=ds.id, version_no=new_no, filename=filename,
        content_type=content_type, size_bytes=len(data), sha256=sha, data=data,
        etag=etag, last_modified=last_modified,
    )
    db.add(dv)
    db.flush()
    ds.current_version_id = dv.id

    bumped = None
    if cur is None:
        # first local copy — not a content *change*; attach to the current
        # component version without bumping
        comp = db.get(M.Component, ds.component_id)
        if comp is not None and comp.current_version_id is not None:
            cv = db.get(M.ComponentVersion, comp.current_version_id)
            if cv is not None:
                pin_datasheets(db, cv)
    else:
        bumped = _bump_component_version(db, ds, dv)

    db.add(M.AuditLog(actor="system", action="datasheet.fetch", entity_type="datasheet",
                      entity_id=str(ds.id),
                      details={"url": ds.source_url, "pdf_version": new_no, "size": len(data),
                               "content_type": content_type,
                               "component_bumped_to": bumped}))
    db.commit()
    is_pdf = (content_type == "application/pdf") or filename.lower().endswith(".pdf")
    return {"id": ds.id, "result": "new_version", "version_no": new_no,
            "looks_like_pdf": is_pdf, "component_bumped_to": bumped}


def store_upload(
    db: Session, ds: M.Datasheet, data: bytes, filename: str | None, content_type: str | None
) -> dict:
    """Store user-uploaded bytes as a new version of `ds`. Unlike fetch, an
    upload is a deliberate act on known content, so non-PDF files (DXF, STEP,
    3MF, …) are versioned too — the unstable-web-page guard does not apply.
    Content changes bump the component version exactly like fetched PDFs."""
    sha = hashlib.sha256(data).hexdigest()
    cur = current_version(ds)
    if cur is not None and cur.sha256 == sha:
        cur.fetched_at = datetime.now(timezone.utc)
        db.commit()
        return {"id": ds.id, "result": "unchanged", "version_no": cur.version_no}

    new_no = (cur.version_no if cur else 0) + 1
    dv = M.DatasheetVersion(
        datasheet_id=ds.id, version_no=new_no, filename=filename or f"{ds.label}.bin",
        content_type=content_type, size_bytes=len(data), sha256=sha, data=data,
    )
    db.add(dv)
    db.flush()
    ds.current_version_id = dv.id

    bumped = None
    if cur is None:
        # first local copy — attach to the current version without bumping
        comp = db.get(M.Component, ds.component_id)
        if comp is not None and comp.current_version_id is not None:
            cv = db.get(M.ComponentVersion, comp.current_version_id)
            if cv is not None:
                pin_datasheets(db, cv)
    else:
        bumped = _bump_component_version(
            db, ds, dv,
            comment=f"File '{ds.label}' replaced by upload → v{new_no}",
            created_by="user",
        )

    db.add(M.AuditLog(actor="user", action="datasheet.upload", entity_type="datasheet",
                      entity_id=str(ds.id),
                      details={"filename": filename, "file_version": new_no, "size": len(data),
                               "content_type": content_type,
                               "component_bumped_to": bumped}))
    db.commit()
    is_pdf = (content_type == "application/pdf") or (filename or "").lower().endswith(".pdf")
    return {"id": ds.id, "result": "new_version", "version_no": new_no,
            "looks_like_pdf": is_pdf, "component_bumped_to": bumped}


def add_component_file(
    db: Session, comp: M.Component, label: str,
    data: bytes, filename: str | None, content_type: str | None,
) -> dict:
    """Attach an uploaded file to a component as a new datasheet-style row
    (no source URL) and bump the component version so the file's existence is
    pinned to a version — the row set itself is versioned component data."""
    rows = (
        db.query(M.Datasheet)
        .filter_by(component_id=comp.id, archived=False)
        .order_by(M.Datasheet.position)
        .all()
    )
    position = (max((r.position or 0) for r in rows) + 1) if rows else 0
    ds = M.Datasheet(component_id=comp.id, position=position, label=label, source_url=None)
    db.add(ds)
    db.flush()

    sha = hashlib.sha256(data).hexdigest()
    dv = M.DatasheetVersion(
        datasheet_id=ds.id, version_no=1, filename=filename or f"{label}.bin",
        content_type=content_type, size_bytes=len(data), sha256=sha, data=data,
    )
    db.add(dv)
    db.flush()
    ds.current_version_id = dv.id

    bumped = _bump_component_version(
        db, ds, dv,
        comment=f"Added file '{label}'" + (f" ({filename})" if filename else ""),
        created_by="user",
    )

    db.add(M.AuditLog(actor="user", action="datasheet.add_file", entity_type="datasheet",
                      entity_id=str(ds.id),
                      details={"component": comp.name, "label": label, "filename": filename,
                               "size": len(data), "content_type": content_type,
                               "component_bumped_to": bumped}))
    db.commit()
    return {"id": ds.id, "result": "created", "version_no": 1,
            "component_bumped_to": bumped}


def start_fetch_all(mode: str = "missing", trigger: str = "manual") -> bool:
    """Background fetch of every non-archived datasheet with a source URL.
    mode 'missing': only those without a local copy; 'all': re-check everything
    (content-change detection)."""
    with _lock:
        if FETCH_STATE["running"]:
            return False
        FETCH_STATE.update(running=True, mode=mode, trigger=trigger, done=0, total=0,
                           new_versions=0, unchanged=0, not_modified=0, errors=0, last_error=None,
                           started_at=datetime.now(timezone.utc).isoformat(), finished_at=None)
    threading.Thread(target=_fetch_all_worker, args=(mode,), daemon=True).start()
    return True


def _next_nightly(hour: int, now: datetime | None = None) -> datetime:
    """Next occurrence of `hour`:00 in server local time, always in the future."""
    now = now or datetime.now().astimezone()
    run_at = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if run_at <= now:
        run_at += timedelta(days=1)
    return run_at


def start_nightly_recheck(hour: int = 3) -> None:
    """Re-check EVERY datasheet source URL once a night at `hour` local time.

    Conditional GETs make this cheap: unchanged documents answer 304 and are
    never downloaded. A document that really changed becomes a new
    DatasheetVersion and auto-bumps the component version, exactly like a
    manual re-fetch. Idempotent — only the first call arms the timer."""
    global _nightly_started
    if _nightly_started:
        return
    _nightly_started = True

    def tick() -> None:
        FETCH_STATE["last_nightly_at"] = datetime.now(timezone.utc).isoformat()
        try:
            if not start_fetch_all("all", trigger="nightly"):
                log.warning("nightly datasheet re-check skipped: a fetch run is already active")
        except Exception as e:  # never let a bad night kill the schedule
            log.warning(f"nightly datasheet re-check failed to start: {e}")
        arm()

    def arm() -> None:
        run_at = _next_nightly(hour)
        FETCH_STATE["next_nightly_at"] = run_at.isoformat()
        t = threading.Timer(max((run_at - datetime.now().astimezone()).total_seconds(), 60.0), tick)
        t.daemon = True
        t.start()

    arm()


def _fetch_all_worker(mode: str) -> None:
    db = SessionLocal()
    try:
        q = db.query(M.Datasheet).filter(M.Datasheet.archived.is_(False),
                                         M.Datasheet.source_url.isnot(None))
        if mode == "missing":
            q = q.filter(M.Datasheet.current_version_id.is_(None))
        ids = [ds.id for ds in q.all()]
        FETCH_STATE["total"] = len(ids)
        for ds_id in ids:
            ds = db.get(M.Datasheet, ds_id)
            if ds is None:
                continue
            try:
                r = fetch_datasheet(db, ds)
                if r["result"] == "new_version":
                    FETCH_STATE["new_versions"] += 1
                elif r["result"] == "unchanged":
                    FETCH_STATE["unchanged"] += 1
                    if r.get("not_modified"):
                        FETCH_STATE["not_modified"] += 1
            except Exception as e:
                db.rollback()
                FETCH_STATE["errors"] += 1
                FETCH_STATE["last_error"] = f"datasheet {ds_id}: {e}"
            FETCH_STATE["done"] += 1
            time.sleep(0.3)  # be polite to supplier servers
        # Newly local PDF copies change the generated Datasheet links —
        # refresh all mirror symbol libraries once at the end of the run.
        if FETCH_STATE["new_versions"]:
            try:
                from ..config import settings
                from .mirror import update_mirror_symbols

                tops = {c.name for c in db.query(M.Category).filter(M.Category.parent_id.is_(None))}
                update_mirror_symbols(db, settings, tops)
            except Exception as e:
                FETCH_STATE["last_error"] = f"mirror refresh: {e}"
    finally:
        db.close()
        FETCH_STATE["running"] = False
        FETCH_STATE["finished_at"] = datetime.now(timezone.utc).isoformat()
