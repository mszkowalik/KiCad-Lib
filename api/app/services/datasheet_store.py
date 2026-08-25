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
                     "rejected": 0,
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


# ------------------------------------------------- searchable-PDF detection
# A page carrying nothing but a scanner's stamped page number is still a scan.
# A typeset datasheet page runs to hundreds of characters, so the threshold
# only has to clear that noise floor.
_TEXT_MIN_CHARS = 24
# Datasheets end in image plates — package drawings, tape-and-reel diagrams,
# marking layouts — that legitimately carry no text. A document is searchable
# when nearly all of it is, not only when every last page is.
_TEXT_RATIO_OK = 0.9

TEXT_LAYER_CLASSES = ("text", "mixed", "scan", "none", "error")


class BadDocument(ValueError):
    """A file that must not be archived. Carries the reason, in words a user
    reads in the upload dialog — the callers turn it into a 422."""


def inspect_document(
    data: bytes, content_type: str | None = None, filename: str | None = None
) -> tuple[dict, str | None]:
    """One pass over a file: its classification columns, and the reason it must
    be REFUSED (or None if it may be stored).

    Both answers come from the same PDF open, so the gate on the way in costs
    nothing beyond the classification that happens anyway. Only PDFs are gated
    — an archived web page, a DXF or a STEP file has no text layer to have and
    is refused only when it is empty.

    Refusing at the door is the point: a stored file nothing can open is worse
    than no stored file at all. It hides the fact that the component has no
    usable datasheet, it makes `read_datasheet` fail on a part that looks
    documented, and the Fetch button can always try again."""
    empty = {"text_layer": "error", "page_count": None, "text_pages": None}
    if not data:
        return empty, "the file is empty (0 bytes)"

    is_pdf = (
        data[:5] == b"%PDF-"
        or "pdf" in (content_type or "").lower()
        or (filename or "").lower().endswith(".pdf")
    )
    if not is_pdf:
        return {"text_layer": "none", "page_count": None, "text_pages": None}, None

    try:
        import fitz  # pymupdf

        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:  # noqa: BLE001 — a corrupt file is data, not a crash
        log.warning(f"datasheet rejected, will not open as a PDF: {e}")
        return empty, "the file does not open as a PDF (it is damaged or not really a PDF)"

    try:
        # Encrypted and we hold no password: every page would read as blank,
        # which is indistinguishable from a scan. Say the true reason instead.
        if doc.needs_pass:
            return empty, "the PDF is password-locked, so nothing can read it"
        pages = doc.page_count
        if pages <= 0:
            return {"text_layer": "error", "page_count": 0, "text_pages": 0}, (
                "the PDF contains no pages")
        hits = sum(
            1
            for page in doc
            if len("".join(page.get_text("text").split())) >= _TEXT_MIN_CHARS
        )
    except Exception as e:  # noqa: BLE001
        log.warning(f"datasheet text-layer classification failed mid-document: {e}")
        return empty, None  # it opened; storing it is fine, we just cannot judge it
    finally:
        doc.close()

    if hits == 0:
        layer = "scan"
    elif hits >= pages * _TEXT_RATIO_OK:
        layer = "text"
    else:
        layer = "mixed"
    # A scan is NOT refused. It is a real document, it is just not searchable —
    # the tag and the `cmp.datasheet_text` validator item exist to get it
    # replaced, and refusing it would leave the part with nothing at all.
    return {"text_layer": layer, "page_count": pages, "text_pages": hits}, None


def store_or_raise(
    data: bytes, content_type: str | None = None, filename: str | None = None
) -> dict:
    """The classification columns, or BadDocument if the file must be refused."""
    cls, reject = inspect_document(data, content_type, filename)
    if reject is not None:
        raise BadDocument(reject)
    return cls


def classify_text_layer(
    data: bytes, content_type: str | None = None, filename: str | None = None
) -> dict:
    """Is this a searchable PDF, or are its pages only images?

    Returns ``{"text_layer", "page_count", "text_pages"}`` — the three columns
    on DatasheetVersion. ``text_layer`` is one of:

    ``text``   every page (or all but a plate or two) has an extractable text
               layer. Searchable, and readable by the agent.
    ``mixed``  some pages are text, the rest are images. Search finds part of
               the document and misses the rest, which is the worst case to
               debug — hence its own class rather than being folded into one
               of the two ends.
    ``scan``   no page has a text layer. Nothing can search it and
               ``read_datasheet`` returns empty text for every page.
    ``none``   not a PDF at all (an archived web page, a DXF, a STEP file…).
               Not a defect — these rows simply have nothing to classify.
    ``error``  a PDF that would not open, or one locked with a password.

    NEVER raises: this runs inside the download path, and a datasheet that
    stores fine but classifies badly must still store. Callers that must also
    REFUSE a broken file want `inspect_document` / `store_or_raise` instead —
    same single pass, plus the reason."""
    return inspect_document(data, content_type, filename)[0]


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

    # A download nothing can open is not a datasheet. Refuse it BEFORE the
    # sha comparison: a supplier that starts serving an error page under the
    # old URL must read as "rejected", not as "unchanged". Any copy we already
    # hold survives untouched, which is the right outcome.
    classification, reject = inspect_document(data, content_type, filename)
    if reject is not None:
        db.add(M.AuditLog(actor="system", action="datasheet.rejected",
                          entity_type="datasheet", entity_id=str(ds.id),
                          details={"url": ds.source_url, "reason": reject,
                                   "size": len(data), "content_type": content_type}))
        db.commit()
        return {"id": ds.id, "result": "rejected", "reason": reject,
                "version_no": cur.version_no if cur else None}

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
        **classification,
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
    Content changes bump the component version exactly like fetched PDFs.

    Raises BadDocument on an empty or unopenable file — the deliberateness of
    an upload is no reason to archive something nothing can read."""
    classification = store_or_raise(data, content_type, filename)
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
        **classification,
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
    pinned to a version — the row set itself is versioned component data.

    Raises BadDocument on an empty or unopenable file."""
    classification = store_or_raise(data, content_type, filename)
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
        **classification,
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
                           new_versions=0, unchanged=0, not_modified=0, errors=0, rejected=0,
                           last_error=None,
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
                elif r["result"] == "rejected":
                    # Not an error: the download arrived and was refused on
                    # purpose. Counted separately so a supplier that starts
                    # serving junk is visible instead of looking like a network
                    # problem.
                    FETCH_STATE["rejected"] += 1
                    FETCH_STATE["last_error"] = f"datasheet {ds_id} refused: {r['reason']}"
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


# ------------------------------------------------------ text-layer backfill
CLASSIFY_STATE: dict = {"running": False, "mode": None, "done": 0, "total": 0,
                        "started_at": None, "finished_at": None, "last_error": None}
_classify_lock = threading.Lock()


def classify_counts(db: Session) -> dict:
    """How many stored documents fall in each text-layer class. `""` counts
    the rows the backfill has not reached yet."""
    from sqlalchemy import func

    rows = (db.query(M.DatasheetVersion.text_layer, func.count())
            .group_by(M.DatasheetVersion.text_layer).all())
    return {(cls or "unclassified"): n for cls, n in rows}


def start_text_layer_classify(mode: str = "missing") -> bool:
    """Classify stored datasheet versions in the background.

    mode 'missing': only rows the classifier has never seen (text_layer = '')
    — this is what runs at startup, so documents archived before the column
    existed get their tag. mode 'all': re-classify everything, for when the
    thresholds change.

    Returns False if a run is already going."""
    if mode not in ("missing", "all"):
        raise ValueError("mode must be 'missing' or 'all'")
    with _classify_lock:
        if CLASSIFY_STATE["running"]:
            return False
        CLASSIFY_STATE.update(running=True, mode=mode, done=0, total=0, last_error=None,
                              started_at=datetime.now(timezone.utc).isoformat(),
                              finished_at=None)
    threading.Thread(target=_classify_worker, args=(mode,), daemon=True).start()
    return True


def _classify_worker(mode: str) -> None:
    """One row at a time, expunged straight after.

    The stored corpus is close to a gigabyte of PDF bytes and single documents
    run past 30 MB, so this must never hold more than one `data` blob at once:
    it selects IDs only, loads each row on its own, and drops it from the
    session before taking the next. A `query(DatasheetVersion).all()` here
    would pull the whole library into the API container's memory."""
    db = SessionLocal()
    try:
        q = db.query(M.DatasheetVersion.id).order_by(M.DatasheetVersion.id)
        if mode == "missing":
            q = q.filter(M.DatasheetVersion.text_layer == "")
        ids = [row[0] for row in q.all()]
        CLASSIFY_STATE["total"] = len(ids)
        for dv_id in ids:
            try:
                dv = db.get(M.DatasheetVersion, dv_id)
                if dv is not None:
                    for k, v in classify_text_layer(
                        dv.data, dv.content_type, dv.filename
                    ).items():
                        setattr(dv, k, v)
                    db.commit()
                    db.expunge(dv)
            except Exception as e:  # noqa: BLE001 — one bad PDF must not stop the sweep
                db.rollback()
                CLASSIFY_STATE["last_error"] = f"datasheet version {dv_id}: {e}"
                log.warning(f"text-layer classification of version {dv_id} failed: {e}")
            CLASSIFY_STATE["done"] += 1
            time.sleep(0.02)  # leave the API responsive during the startup sweep
    finally:
        db.close()
        CLASSIFY_STATE["running"] = False
        CLASSIFY_STATE["finished_at"] = datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------- broken-file cleanup
def find_broken(db: Session) -> list[dict]:
    """Stored versions nothing can open: empty files, and PDFs that fail to
    parse or are password-locked (`text_layer = "error"`).

    A `scan` is NOT broken. It opens, it is a real document, it is only
    unsearchable — that is what the tag and `cmp.datasheet_text` are for."""
    rows = (
        db.query(M.DatasheetVersion)
        .filter(
            (M.DatasheetVersion.text_layer == "error") | (M.DatasheetVersion.size_bytes == 0)
        )
        .order_by(M.DatasheetVersion.id)
        .all()
    )
    out = []
    for dv in rows:
        ds = db.get(M.Datasheet, dv.datasheet_id)
        comp = db.get(M.Component, ds.component_id) if ds is not None else None
        siblings = [v for v in (ds.versions if ds is not None else []) if v.id != dv.id]
        pins = (db.query(M.ComponentVersionDatasheet)
                .filter_by(datasheet_version_id=dv.id).count())
        out.append({
            "version_id": dv.id,
            "datasheet_id": dv.datasheet_id,
            "component_id": comp.id if comp else None,
            "component": comp.name if comp else None,
            "label": ds.label if ds else None,
            "version_no": dv.version_no,
            "filename": dv.filename,
            "content_type": dv.content_type,
            "size_bytes": dv.size_bytes,
            "text_layer": dv.text_layer,
            "is_current": ds is not None and ds.current_version_id == dv.id,
            # What the row falls back to once this version is gone.
            "falls_back_to": (max(siblings, key=lambda v: v.version_no).version_no
                              if siblings else None),
            "source_url": ds.source_url if ds else None,
            "pinned_by_versions": pins,
        })
        db.expunge(dv)
    return out


def purge_broken(db: Session, actor: str = "system") -> dict:
    """Delete every version `find_broken` lists, and leave the rows consistent.

    Three things have to happen in the right order or the delete either fails
    or lies:

    1. **Un-pin it.** `ComponentVersionDatasheet.datasheet_version_id` is a real
       FK; deleting under it raises. NULL is also the honest value — it already
       means "no local copy existed for this component version", which is
       nearer the truth than a pin to bytes nothing can open.
    2. **Repoint `current_version_id`** to the newest surviving version, or NULL
       when none survives. A dangling pointer would make `has_file` true and
       every download 404.
    3. **Refresh the mirror** for the affected categories: `injected_props`
       emits the LOCAL file URL whenever a current version exists, so a row
       that falls back to NULL must go back to emitting the supplier URL.
    """
    found = find_broken(db)
    if not found:
        return {"removed": 0, "items": [], "categories_refreshed": []}

    touched_components: set[int] = set()
    for row in found:
        dv = db.get(M.DatasheetVersion, row["version_id"])
        if dv is None:
            continue
        ds = db.get(M.Datasheet, dv.datasheet_id)
        db.query(M.ComponentVersionDatasheet).filter_by(
            datasheet_version_id=dv.id
        ).update({"datasheet_version_id": None}, synchronize_session=False)
        if ds is not None and ds.current_version_id == dv.id:
            survivors = [v for v in ds.versions if v.id != dv.id]
            ds.current_version_id = (
                max(survivors, key=lambda v: v.version_no).id if survivors else None
            )
            touched_components.add(ds.component_id)
        db.delete(dv)
        db.add(M.AuditLog(
            actor=actor, action="datasheet.purge_broken", entity_type="datasheet",
            entity_id=str(row["datasheet_id"]),
            details={k: row[k] for k in
                     ("component", "label", "version_no", "filename", "content_type",
                      "size_bytes", "text_layer", "is_current", "falls_back_to",
                      "pinned_by_versions")}))
    db.commit()

    refreshed: list[str] = []
    try:
        from ..config import settings

        from .mirror import top_level_of, update_mirror_symbols

        tops = set()
        for comp_id in touched_components:
            comp = db.get(M.Component, comp_id)
            if comp is None or comp.current_version_id is None:
                continue
            cv = db.get(M.ComponentVersion, comp.current_version_id)
            if cv is not None:
                tops.add(top_level_of(cv.category).name)
        if tops:
            update_mirror_symbols(db, settings, tops)
            refreshed = sorted(tops)
    except Exception as e:  # noqa: BLE001 — the delete already landed
        log.warning(f"mirror refresh after purge_broken failed: {e}")

    return {"removed": len(found), "items": found, "categories_refreshed": refreshed}
