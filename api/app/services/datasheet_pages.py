"""Per-page datasheet extraction, and full-text search over the result.

Why this exists: the only way an agent could read an archived datasheet was
`read_datasheet`, which returns at most 6 pages chosen by GUESSING a page
number. RP2040 is 642 pages. Nothing in the platform could search datasheet
text at all, so "which page shows the land pattern" had no cheap answer.

What it is: one `DatasheetPage` row per page, holding layout-aware markdown,
extracted with `pymupdf4llm` (the same MuPDF engine `pymupdf` already uses —
no ML models, no GPU, no network). Measured on the live corpus: 0.25 s per
page, ~40 minutes for all ~9400 pages, 16.4 MB of text.

What it is NOT: an authority. See the `DatasheetPage` docstring — the
extractor shreds text that wraps inside a merged cell and reorders multi-line
pin labels. These rows FIND a page. The page image settles a number.

Three rules hold this module up:

1. **One PDF blob in memory at a time.** The corpus is ~900 MB and single
   documents pass 30 MB, so the worker selects ids, loads each version on its
   own and expunges it before taking the next — the same shape as
   `datasheet_store._classify_worker`. A `query(DatasheetVersion).all()` here
   would pull the whole library into the API container.
2. **An empty page always says why.** `extract_kind` is never blank on a
   written row. The extractor returns zero characters on a scanned page in
   0.08 s and raises nothing, so silence would read as "this page is blank".
3. **Extraction is idempotent per version.** Re-indexing deletes that
   version's rows first. Version rows are immutable, so re-running only ever
   reproduces the same pages or improves them after an extractor change.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from sqlalchemy import delete, func, text as sa_text
from sqlalchemy.orm import Session

from .. import models as M
from ..db import SessionLocal
from . import memory
from .datasheet_store import _TEXT_MIN_CHARS

log = logging.getLogger(__name__)

# Pages per `to_markdown` call. The extractor holds every requested page's
# result in memory and a 642-page document in one call is ~160 s of work with
# no progress and no interruption point. Batching bounds both.
_BATCH_PAGES = 25

# The extractor fences text it recovered from inside a drawing. A mechanical
# drawing's dimension callouts arrive this way and are genuinely useful
# ("6X (0.67)", "4X (0.5)"), but a page whose ONLY text came from a picture is
# a drawing, not prose, and a reader deserves to be told which it got.
_PIC_OPEN = "<!-- Start of picture text -->"
_PIC_CLOSE = "<!-- End of picture text -->"

INDEX_STATE: dict = {"running": False, "mode": None, "done": 0, "total": 0,
                     "pages": 0, "errors": 0, "started_at": None, "finished_at": None,
                     "last_error": None, "cancelled": False}
_lock = threading.Lock()


def stop_index() -> bool:
    """Ask a running sweep to stop at the next version boundary.

    A full backfill is ~40 minutes of background CPU on a machine that may be
    serving KiCad clients, so it needs a stop button. It stops BETWEEN
    versions, never mid-document: a half-extracted document would look
    complete, because `pages_indexed_at` is stamped by `extract_version`
    itself. Returns False when nothing was running."""
    with _lock:
        if not INDEX_STATE["running"]:
            return False
        INDEX_STATE["cancelled"] = True
        return True


# ------------------------------------------------------------------ extraction
def _strip_picture_text(md: str) -> str:
    """The markdown with every picture-text block removed."""
    out, rest = [], md
    while True:
        i = rest.find(_PIC_OPEN)
        if i < 0:
            out.append(rest)
            return "".join(out)
        out.append(rest[:i])
        j = rest.find(_PIC_CLOSE, i)
        if j < 0:
            return "".join(out)
        rest = rest[j + len(_PIC_CLOSE):]


def _drop_surrogates(md: str) -> str:
    """Text Postgres can actually store.

    pymupdf4llm returns lone UTF-16 surrogates for some malformed CID fonts
    (mathematical alphanumerics, U+D835 and friends). Python holds them
    happily, psycopg
    cannot encode them, and the error lands on the flush at the END of a
    25-page batch — outside `extract_version`'s per-document guard, so
    `pages_indexed_at` never gets stamped and the document is re-extracted on
    every boot for ever. Versions 367 and 368 did exactly that. A lone
    surrogate carries no text either way, so dropping it loses nothing."""
    if not md.isascii() and any("\ud800" <= c <= "\udfff" for c in md):
        return "".join(c for c in md if not "\ud800" <= c <= "\udfff")
    return md


def _classify_page(md: str, doc_layer: str) -> str:
    """Which kind of page content this is. Never returns "" — see rule 2."""
    if len("".join(md.split())) < _TEXT_MIN_CHARS:
        # No usable text. On a document we already know has no text layer this
        # is expected and is not a defect; anywhere else it is a real failure.
        return "empty_scan" if doc_layer in ("scan", "mixed") else "failed"
    if len("".join(_strip_picture_text(md).split())) < _TEXT_MIN_CHARS:
        return "picture_text"
    return "text"


def _section_tracker():
    """Follow the PDF outline while walking pages in order.

    `pymupdf4llm` reports the outline entries that START on a page. To answer
    "which section is this page IN" the deepest entry has to be carried
    forward, and a shallower entry has to drop everything below it — hence a
    level stack rather than a last-seen string."""
    stack: list[tuple[int, str]] = []

    def feed(toc_items) -> str | None:
        for item in toc_items or []:
            try:
                lvl, title = int(item[0]), str(item[1]).strip()
            except (TypeError, ValueError, IndexError):
                continue
            if not title:
                continue
            while stack and stack[-1][0] >= lvl:
                stack.pop()
            stack.append((lvl, title))
        return " / ".join(t for _, t in stack) or None

    return feed


def extract_version(db: Session, dv: M.DatasheetVersion) -> dict:
    """(Re)build the page rows for one datasheet version.

    Never raises on a bad document: it stamps `pages_indexed_at` and reports
    the failure, because a document that cannot be indexed must not be retried
    on every sweep for ever."""
    import pymupdf
    import pymupdf4llm

    result = {"version_id": dv.id, "pages": 0, "kinds": {}}
    db.execute(delete(M.DatasheetPage).where(M.DatasheetPage.datasheet_version_id == dv.id))

    if dv.text_layer == "none":
        # Not a PDF at all (an archived product page). Nothing to page through.
        dv.pages_indexed_at = datetime.now(timezone.utc)
        db.commit()
        result["skipped"] = "not a pdf"
        return result
    try:
        doc = pymupdf.open(stream=dv.data, filetype="pdf")
    except Exception as e:  # noqa: BLE001 — see the docstring
        dv.pages_indexed_at = datetime.now(timezone.utc)
        db.commit()
        result["error"] = f"cannot open: {e}"
        return result

    feed = _section_tracker()
    try:
        n = doc.page_count
        for start in range(0, n, _BATCH_PAGES):
            idxs = list(range(start, min(start + _BATCH_PAGES, n)))
            try:
                chunks = pymupdf4llm.to_markdown(doc, page_chunks=True, pages=idxs)
                kind_of = None
            except Exception as e:  # noqa: BLE001 — one bad page must not lose the document
                log.warning(f"layout extraction failed on version {dv.id} pages {idxs}: {e}")
                chunks = [{"text": doc[i].get_text("text"), "toc_items": []} for i in idxs]
                kind_of = "fallback_text"
            for i, chunk in zip(idxs, chunks):
                md = _drop_surrogates(chunk.get("text") or "")
                kind = kind_of or _classify_page(md, dv.text_layer)
                section = feed(chunk.get("toc_items"))
                db.add(M.DatasheetPage(
                    datasheet_version_id=dv.id, page_no=i + 1,
                    content=md, chars=len(md), extract_kind=kind,
                    section=section, has_table="|---" in md,
                ))
                result["kinds"][kind] = result["kinds"].get(kind, 0) + 1
                result["pages"] += 1
            db.flush()
    finally:
        doc.close()

    dv.pages_indexed_at = datetime.now(timezone.utc)
    db.commit()
    return result


# --------------------------------------------------------------------- sweeps
def index_counts(db: Session) -> dict:
    """Coverage, and the page mix — the two numbers that say whether the
    index is complete and whether it is worth trusting on a given page."""
    total = db.query(M.DatasheetVersion).count()
    done = db.query(M.DatasheetVersion).filter(
        M.DatasheetVersion.pages_indexed_at.isnot(None)).count()
    kinds = dict(db.query(M.DatasheetPage.extract_kind, func.count())
                 .group_by(M.DatasheetPage.extract_kind).all())
    # `pages_total` and NOT `pages`: the status endpoint merges this dict over
    # INDEX_STATE, and a shared key would hide the running sweep's own counter.
    return {"versions_total": total, "versions_indexed": done,
            "pages_total": sum(kinds.values()), "page_kinds": kinds}


def start_index(mode: str = "missing", version_id: int | None = None) -> bool:
    """Extract pages in the background.

    mode "missing": versions never indexed (`pages_indexed_at IS NULL`) — the
    retroactive backfill, and what runs at startup. mode "current": only the
    versions a datasheet actually serves, for a fast first pass. mode "all":
    re-extract everything, for when the extractor improves.

    Returns False if a run is already going."""
    if mode not in ("missing", "current", "all"):
        raise ValueError("mode must be 'missing', 'current' or 'all'")
    with _lock:
        if INDEX_STATE["running"]:
            return False
        INDEX_STATE.update(running=True, mode=mode, done=0, total=0, pages=0, errors=0,
                           last_error=None, finished_at=None, cancelled=False,
                           started_at=datetime.now(timezone.utc).isoformat())
    threading.Thread(target=_index_worker, args=(mode, version_id), daemon=True).start()
    return True


# One extraction at a time, process-wide. `index_one` is fire-and-forget per
# STORED version, so a bulk fetch — the nightly `start_fetch_all("all")` walks
# all 678 datasheets — used to spawn one unbounded thread per changed document.
# A single pymupdf4llm extraction was measured at 400-450 MB peak even on a
# 10-page, 1.6 MB PDF, so a dozen at once is ~6 GB: the API was OOM-killed four
# times in August on a 8 GB host, each time at 6.9-7.5 GB anon-rss, and because
# no container carried a memory limit the kernel picked its victim host-wide.
# Serialising costs nothing on a 2-core box: extraction is CPU-bound, so the
# threads were never really running in parallel, only holding memory at once.
_EXTRACT_SLOT = threading.BoundedSemaphore(1)


def index_one(version_id: int) -> None:
    """Index a single version in a daemon thread. Called after a document is
    stored: a 642-page document is minutes of work and must never sit inside
    the upload request.

    The thread waits its turn on `_EXTRACT_SLOT`, so a bulk fetch queues
    instead of running every document at once."""
    def run() -> None:
        with _EXTRACT_SLOT:
            db = SessionLocal()
            try:
                dv = db.get(M.DatasheetVersion, version_id)
                if dv is not None:
                    extract_version(db, dv)
            except Exception as e:  # noqa: BLE001 — indexing must never break a store
                log.warning(f"page indexing of version {version_id} failed: {e}")
            finally:
                db.close()
                memory.trim()

    threading.Thread(target=run, daemon=True).start()


def _index_worker(mode: str, version_id: int | None) -> None:
    db = SessionLocal()
    try:
        if version_id is not None:
            ids = [version_id]
        else:
            q = db.query(M.DatasheetVersion.id)
            if mode == "missing":
                q = q.filter(M.DatasheetVersion.pages_indexed_at.is_(None))
            elif mode == "current":
                q = q.join(M.Datasheet, M.Datasheet.id == M.DatasheetVersion.datasheet_id).filter(
                    M.Datasheet.current_version_id == M.DatasheetVersion.id,
                    M.Datasheet.archived.is_(False),
                )
            ids = [row[0] for row in q.order_by(M.DatasheetVersion.id).all()]
        INDEX_STATE["total"] = len(ids)
        for dv_id in ids:
            if INDEX_STATE["cancelled"]:
                INDEX_STATE["last_error"] = (
                    f"stopped by request after {INDEX_STATE['done']}/{len(ids)} versions"
                )
                break
            try:
                dv = db.get(M.DatasheetVersion, dv_id)
                # The id list is snapshotted when the sweep starts, so a
                # version indexed since then (by a store, or by hand) is stale
                # work. Re-extraction is harmless but a 642-page document is
                # three minutes of it.
                if dv is not None and mode == "missing" and dv.pages_indexed_at is not None:
                    INDEX_STATE["done"] += 1
                    db.expunge(dv)
                    continue
                if dv is not None:
                    with _EXTRACT_SLOT:
                        res = extract_version(db, dv)
                    INDEX_STATE["pages"] += res["pages"]
                    if res.get("error"):
                        INDEX_STATE["errors"] += 1
                        INDEX_STATE["last_error"] = f"version {dv_id}: {res['error']}"
                    db.expunge(dv)
            except Exception as e:  # noqa: BLE001 — one bad PDF must not stop the sweep
                db.rollback()
                INDEX_STATE["errors"] += 1
                INDEX_STATE["last_error"] = f"version {dv_id}: {e}"
                log.warning(f"page indexing of version {dv_id} failed: {e}")
            INDEX_STATE["done"] += 1
            # A 31 MB PDF plus its pymupdf render buffers has just been freed
            # into this thread's arena, where it would stay. See services/memory.
            memory.trim()
            time.sleep(0.02)  # leave the API responsive during the backfill
    finally:
        db.close()
        INDEX_STATE["running"] = False
        INDEX_STATE["finished_at"] = datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------- search
# `simple` and NOT `english`, and the config must match the generated `tsv`
# column in main.py's DDL or the GIN index is silently unused. Datasheet
# tokens are part numbers, package codes and dimensions ("DRL0006A", "VOS1",
# "0.65"); English stemming damages them and buys nothing.
_TSCONFIG = "simple"

_SEARCH_SQL = """
SELECT c.id           AS component_id,
       c.name         AS component,
       d.id           AS datasheet_id,
       d.label        AS label,
       p.page_no      AS page_no,
       p.section      AS section,
       p.extract_kind AS extract_kind,
       p.has_table    AS has_table,
       dv.page_count  AS page_count,
       ts_headline(:cfg, p.content, q.query,
                   'MaxFragments=2,MaxWords=28,MinWords=8,ShortWord=2') AS snippet,
       ts_rank_cd(p.tsv, q.query) AS rank
  FROM datasheet_pages p
  JOIN datasheet_versions dv ON dv.id = p.datasheet_version_id
  JOIN datasheets d          ON d.id = dv.datasheet_id
  JOIN components c          ON c.id = d.component_id
  CROSS JOIN websearch_to_tsquery(:cfg, :q) AS q(query)
 WHERE p.tsv @@ q.query
   AND d.archived = false
   {current_only}
   {component_filter}
 ORDER BY rank DESC, c.name, p.page_no
 LIMIT :limit
"""


def search(db: Session, query: str, limit: int = 20, component: str = "",
           include_superseded: bool = False) -> dict:
    """Full-text search across archived datasheet pages.

    Superseded PDF versions are excluded by default: they are the same document
    a version or two back, so including them returns the same hit several times
    and points the reader at a page the library no longer serves."""
    q = (query or "").strip()
    if not q:
        return {"query": q, "hits": [], "error": "empty query"}
    sql = _SEARCH_SQL.format(
        current_only="" if include_superseded else "AND d.current_version_id = dv.id",
        component_filter="AND c.name ILIKE :comp" if component.strip() else "",
    )
    params = {"cfg": _TSCONFIG, "q": q, "limit": max(1, min(int(limit), 100))}
    if component.strip():
        params["comp"] = f"%{component.strip()}%"
    rows = db.execute(sa_text(sql), params).mappings().all()
    hits = []
    for r in rows:
        hits.append({
            "component": r["component"],
            "datasheet": r["label"],
            "page": r["page_no"],
            "page_count": r["page_count"],
            "section": r["section"],
            "extract_kind": r["extract_kind"],
            "has_table": r["has_table"],
            "snippet": (r["snippet"] or "").replace("\n", " ").strip(),
            # One string that addresses the page for an agent AND opens it for a
            # human: #page=N is the standard PDF open parameter.
            "uri": f"/api/datasheets/{r['datasheet_id']}/file#page={r['page_no']}",
            "read": {"component": r["component"], "datasheet_label": r["label"],
                     "pages": str(r["page_no"])},
        })
    return {"query": q, "hits": hits, "count": len(hits)}


def page_text(db: Session, datasheet_id: int, page_no: int) -> dict | None:
    """One extracted page, by datasheet and printed page number."""
    ds = db.get(M.Datasheet, datasheet_id)
    if ds is None or ds.current_version_id is None:
        return None
    row = (db.query(M.DatasheetPage)
           .filter_by(datasheet_version_id=ds.current_version_id, page_no=page_no)
           .first())
    if row is None:
        return None
    return {"datasheet": ds.label, "page": row.page_no, "section": row.section,
            "extract_kind": row.extract_kind, "has_table": row.has_table,
            "chars": row.chars, "content": row.content}


def outline(db: Session, datasheet_id: int) -> dict | None:
    """The document's section map: every page that starts a new section, plus
    the page kinds. This is what replaces guessing a page number."""
    ds = db.get(M.Datasheet, datasheet_id)
    if ds is None or ds.current_version_id is None:
        return None
    dv = db.get(M.DatasheetVersion, ds.current_version_id)
    rows = (db.query(M.DatasheetPage)
            .filter_by(datasheet_version_id=ds.current_version_id)
            .order_by(M.DatasheetPage.page_no).all())
    sections, last = [], None
    for r in rows:
        if r.section and r.section != last:
            sections.append({"page": r.page_no, "section": r.section})
            last = r.section
    return {
        "datasheet": ds.label, "page_count": dv.page_count if dv else None,
        "text_layer": dv.text_layer if dv else None,
        "indexed_pages": len(rows),
        "sections": sections,
        "table_pages": [r.page_no for r in rows if r.has_table],
        "drawing_pages": [r.page_no for r in rows if r.extract_kind == "picture_text"],
        "unreadable_pages": [r.page_no for r in rows
                             if r.extract_kind in ("empty_scan", "failed")],
    }
