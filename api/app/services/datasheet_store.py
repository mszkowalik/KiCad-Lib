"""Versioned datasheet storage.

- Bytes are stored ONCE per distinct content in `Document`, addressed by
  sha256. A DatasheetVersion is a history entry on a datasheet row that
  points at a document; two components that fetched the same PDF share one
  document (user decision 2026-09-10: "don't duplicate files, just relink").
- A NEW version is created only when the fetched document's TEXT differs
  from the current one — or its bytes, for files that have no text. A vendor
  re-signing the same PDF (TI stamps a new ModDate about every two days)
  refreshes the current version's validators and stores nothing.
- When the content changes on a datasheet of a component that has a published
  current version, the component is AUTO-BUMPED to a new published version
  through the shared publish path (`services/publish.py`), so the sign-off
  and review carry rules run: the review record does NOT carry across a
  datasheet revision (`datasheet_carries`), and a review request is opened so
  the change reaches the worklist. "Which PDF was used in which component
  version" stays answerable via the pin table.
- A background worker fetches all missing (or all) datasheets. No single
  request shape works at every supplier, so the fetcher tries two user agents
  and remembers per host which one worked (`FetchHost`).
"""
from __future__ import annotations

import collections
import hashlib
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from .. import models as M
from ..db import SessionLocal
from . import memory

log = logging.getLogger(__name__)

# Two request shapes, because suppliers disagree (measured 2026-09-10 on the
# direct PDF URLs): Infineon answers a WAF challenge with 0 bytes and Nexperia
# a 403 to the curl string and both serve the browser string; onsemi serves
# curl and 403s the browser. Diodes, Renesas, Rohm, Espressif, TI take either.
UA_CURL = "curl/8.1"
UA_BROWSER = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
_REFUSAL_CODES = {401, 403, 406, 429, 503}
# 429 is in the set so it is REPORTED as a refusal, but `_get` never retries
# it: a rate limit is not a bot check and a second request makes it worse.

FETCH_STATE: dict = {"running": False, "mode": None, "done": 0, "total": 0,
                     "new_versions": 0, "unchanged": 0, "not_modified": 0, "restamped": 0,
                     "relinked": 0, "errors": 0, "rejected": 0,
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


# ------------------------------------------------------------ host strategy
def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _refused(resp: httpx.Response) -> str | None:
    """Why this response is a refusal rather than the document, or None."""
    if resp.status_code in _REFUSAL_CODES:
        return f"HTTP {resp.status_code}"
    if resp.headers.get("x-amzn-waf-action"):
        return "WAF challenge"
    if resp.status_code == 200 and not resp.content:
        return "empty body"
    return None


def _get(db: Session, url: str, extra_headers: dict) -> tuple[httpx.Response, str]:
    """GET with the user agent this host is known to accept, falling back to
    the other one on refusal. Records what worked. Raises httpx.HTTPError on
    network failure, returns the last response otherwise (the caller judges
    the status)."""
    host = _host_of(url)
    row = db.get(M.FetchHost, host) if host else None
    first = row.user_agent if row and row.user_agent in (UA_CURL, UA_BROWSER) else UA_CURL
    order = [first, UA_BROWSER if first == UA_CURL else UA_CURL]

    def remember(ua: str, error: str | None) -> None:
        """Keep the row even on a total refusal — a host that turns us away is
        exactly what the table is for."""
        nonlocal row
        if not host:
            return
        if row is None:
            row = M.FetchHost(host=host, user_agent=ua)
            db.add(row)
        if error is None:
            row.user_agent = ua
            row.last_ok_at = datetime.now(timezone.utc)
        row.last_error = error
        row.updated_at = datetime.now(timezone.utc)

    last, last_why = None, "no response"
    for ua in order:
        resp = httpx.get(url, headers={**extra_headers, "User-Agent": ua},
                         follow_redirects=True, timeout=60)
        why = _refused(resp)
        if why is None:
            remember(ua, None)
            return resp, ua
        log.info(f"{host} refused {ua!r}: {why}")
        last, last_why = resp, why
        if resp.status_code == 429:
            break  # a rate limit is not a bot check; another agent cannot help
    remember(order[0], f"{last_why} (tried {len(order)} user agents)")
    if last is None:  # unreachable while `order` has entries; never return None
        raise httpx.RequestError(f"no response from {host}", request=None)  # type: ignore[arg-type]
    return last, order[-1]


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

# Revision labels, in order of trust. Informational only — the text hash
# decides whether a document changed; the label says what to call it.
_REV_IN_TITLE = re.compile(r"\(\s*Rev(?:ision|\.)?\s*([A-Z0-9][A-Z0-9.]{0,5})\s*\)", re.I)
_REV_IN_TEXT = re.compile(
    r"\bRev(?:ision)?\.?\s*[:#]?\s*([A-Z]{1,2}(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w.])", re.I)
_REVISED_DATE = re.compile(r"\bRevised\s+([A-Z][a-z]+\s+\d{4})\b", re.I)
# TI literature number with its revision letter: SLVSF14B, SBOS561D, SLUSC65A.
# Only trusted when the document says it is a TI document — the shape also
# matches "STM32H7".
_TI_LIT = re.compile(r"\bS[A-Z]{3}[A-Z0-9]{3}[A-Z]?\b")


def parse_revision(meta: dict, first_page: str, last_page: str) -> str | None:
    """The revision label a human would quote, or None.

    Reads, in order: the PDF Title ("... datasheet (Rev. B)"), the Keywords
    (TI puts the literature number there), page 1, then the last page (many
    vendors end with the revision history). Heuristic by nature; it goes in
    notes and the UI and never decides anything."""
    title = str(meta.get("title") or "")
    keywords = str(meta.get("keywords") or "")
    author = str(meta.get("author") or "")
    is_ti = "texas instruments" in (author + title + first_page[:600]).lower()

    m = _REV_IN_TITLE.search(title)
    if m:
        return f"Rev. {m.group(1).upper()}"[:120]
    if is_ti:
        m = _TI_LIT.fullmatch(keywords.strip()) or _TI_LIT.search(first_page[:1500])
        if m:
            return m.group(0)[:120]
    for txt in (first_page, last_page):
        m = _REV_IN_TEXT.search(txt)
        if m:
            return f"Rev. {m.group(1).upper()}"[:120]
        m = _REVISED_DATE.search(txt)
        if m:
            return f"Revised {m.group(1).title()}"[:120]
    return None


class BadDocument(ValueError):
    """A file that must not be archived. Carries the reason, in words a user
    reads in the upload dialog — the callers turn it into a 422."""


def _norm(text: str) -> str:
    return " ".join(text.split())


# TI generates the tail of every datasheet AT DOWNLOAD TIME. Measured
# 2026-09-10 over the 14 stored fetches of one TPS7A20 Rev. H and the 32 of
# one TPS61023 Rev. B, all of them the same published revision:
#
#   * every tail page carries the day's date in its header;
#   * "PACKAGE MATERIALS INFORMATION" is a live logistics table — reel
#     diameters and widths drift between fetches (178.0/8.4 one day,
#     180.0/9.5 the next) and its rows reorder;
#   * "PACKAGE OPTION ADDENDUM" is a live catalog table. Its rows reorder,
#     and the lead-finish cell flips back and forth between fetches
#     ("NIPDAU | SN" -> "SN" -> "NIPDAU | SN", "SN | SPOT AG (TOP SIDE)" ->
#     "SPOT AG (TOP SIDE) | SN"). What is STABLE on it, across all 14
#     fetches, is the set of orderable part numbers and their lifecycle
#     status — and that set is worth watching: it caught TI adding
#     TPS7A20125PYCKR and TPS7A2029PYCKR;
#   * the per-package outline / board-layout / stencil sections come out in a
#     different ORDER from one download to the next, and a whole package
#     section can be dropped (TXS0104E lost three TSSOP pages).
#
# The body — everything before the first generated page — is identical text
# every time. So a page plays one of four roles in the identity:
#
#   body       hashed in order; any change is a change.
#   addendum   the orderable-part table. Reduced to its (part, status) pairs
#              for the WHOLE document, so a reorder or a lead-finish flip is
#              nothing and a new part or an NRND is a change. Every addendum
#              page carries the same document-level digest.
#   unordered  the drawings and the notice: hashed as a SET, so a reordered
#              package section is nothing and an added, removed or edited
#              drawing is a change.
#   volatile   the materials tables: excluded outright.
_TI_STAMP = re.compile(r"www\.ti\.com\s+\d{1,2}-[A-Z][a-z]{2}-\d{4}")
_TAIL_START = ("PACKAGE OPTION ADDENDUM", "PACKAGE MATERIALS INFORMATION")
_ADDENDUM = "PACKAGE OPTION ADDENDUM"
_VOLATILE = "PACKAGE MATERIALS INFORMATION"
# "TPS7A2012PDBVR Active Production SOT-23 (DBV) | 5 3000 | ..." — the part
# number and the lifecycle word beside it. TI's own status vocabulary.
_PART_STATUS = re.compile(
    r"\b([A-Z][A-Z0-9][A-Z0-9._/-]{3,})\s+"
    r"(Active|NRND|Obsolete|Preview|Lifebuy|Last Time Buy)\b")

ROLE_BODY, ROLE_ADDENDUM, ROLE_UNORDERED, ROLE_VOLATILE = "b:", "a:", "u:", "v"


def _addendum_digest(pairs: set[tuple[str, str]]) -> str:
    return hashlib.sha256(
        "\n".join(f"{p} {s}" for p, s in sorted(pairs)).encode()).hexdigest()[:16]


def page_identity(texts: list[str]) -> tuple[list[str], str]:
    """One role-tagged hash per page, and the document's text hash.

    The page list is what `changed_pages` diffs; the text hash is what decides
    whether a fetch is a new revision. See the block comment above for why the
    roles exist."""
    in_tail = False
    roles: list[str] = []          # (role, normalised text) per page
    pairs: set[tuple[str, str]] = set()
    for txt in texts:
        stamped = bool(_TI_STAMP.search(txt))
        norm = _TI_STAMP.sub("", txt).strip()
        if stamped and norm.startswith(_TAIL_START):
            in_tail = True
        if not in_tail:
            roles.append((ROLE_BODY, norm))
        elif stamped and norm.startswith(_VOLATILE):
            roles.append((ROLE_VOLATILE, ""))
        elif stamped and norm.startswith(_ADDENDUM):
            pairs.update(_PART_STATUS.findall(norm))
            roles.append((ROLE_ADDENDUM, ""))
        else:
            roles.append((ROLE_UNORDERED, norm))

    digest = _addendum_digest(pairs)
    hashes: list[str] = []
    body: list[str] = []
    unordered: list[str] = []
    for role, norm in roles:
        if role == ROLE_VOLATILE:
            hashes.append(ROLE_VOLATILE)
            continue
        if role == ROLE_ADDENDUM:
            hashes.append(ROLE_ADDENDUM + digest)
            continue
        h = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
        hashes.append(role + h)
        (body if role == ROLE_BODY else unordered).append(h)

    text_sha = hashlib.sha256("\n".join([
        *body, "#", *sorted(unordered), "#", digest if pairs else "",
    ]).encode()).hexdigest()
    return hashes, text_sha


def inspect_document(
    data: bytes, content_type: str | None = None, filename: str | None = None
) -> tuple[dict, str | None]:
    """One pass over a file: its classification columns, and the reason it must
    be REFUSED (or None if it may be stored).

    The dict carries the `Document` columns that describe the bytes:
    ``text_layer``, ``page_count``, ``text_pages``, and the two identities
    (``text_sha256``, ``page_hashes``, ``doc_revision``). Both answers come
    from the same PDF open, so the gate on the way in costs nothing beyond the
    classification that happens anyway. Only PDFs are gated — an archived web
    page, a DXF or a STEP file has no text layer to have and is refused only
    when it is empty.

    Refusing at the door is the point: a stored file nothing can open is worse
    than no stored file at all. It hides the fact that the component has no
    usable datasheet, it makes `read_datasheet` fail on a part that looks
    documented, and the Fetch button can always try again."""
    blank = {"text_sha256": None, "page_hashes": None, "doc_revision": None}
    empty = {"text_layer": "error", "page_count": None, "text_pages": None, **blank}
    if not data:
        return empty, "the file is empty (0 bytes)"

    # The LEADING BYTES decide, and only when they say nothing do the labels
    # get a vote. LCSC serves its "document not available" page as
    # `C10425.pdf` with `Content-Type: text/html`, so the filename rule alone
    # called 186 stored HTML pages PDFs; pymupdf then opened them into a
    # textless document and they were filed as `scan`, which reads as "we hold
    # a datasheet nobody can search" instead of "we hold no datasheet".
    head = data[:512].lstrip()[:64].lower()
    if data[:5] == b"%PDF-":
        is_pdf = True
    elif head.startswith((b"<!doctype", b"<html", b"<?xml")):
        is_pdf = False
    else:
        is_pdf = (
            "pdf" in (content_type or "").lower()
            or (filename or "").lower().endswith(".pdf")
        )
    if not is_pdf:
        return {"text_layer": "none", "page_count": None, "text_pages": None, **blank}, None

    try:
        import pymupdf

        doc = pymupdf.open(stream=data, filetype="pdf")
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
            return {"text_layer": "error", "page_count": 0, "text_pages": 0, **blank}, (
                "the PDF contains no pages")
        hits = 0
        texts: list[str] = []
        for page in doc:
            txt = _norm(page.get_text("text"))
            if len(txt.replace(" ", "")) >= _TEXT_MIN_CHARS:
                hits += 1
            texts.append(txt)
        first_text, last_text = texts[0], texts[-1]
        page_hashes, text_sha = page_identity(texts)
        meta = doc.metadata or {}
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
    # A scan carries no text to hash: its bytes are its only identity.
    if not hits:
        text_sha = None
    # A scan is NOT refused. It is a real document, it is just not searchable —
    # the tag and the `cmp.datasheet_text` validator item exist to get it
    # replaced, and refusing it would leave the part with nothing at all.
    return {"text_layer": layer, "page_count": pages, "text_pages": hits,
            "text_sha256": text_sha, "page_hashes": page_hashes if hits else None,
            "doc_revision": parse_revision(meta, first_text, last_text)}, None


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

    Returns the `Document` classification columns. ``text_layer`` is one of:

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


# ------------------------------------------------------------- documents
def find_document(db: Session, sha256: str) -> M.Document | None:
    return db.query(M.Document).filter_by(sha256=sha256).first()


def _new_document(db: Session, data: bytes, sha256: str, content_type: str | None,
                  classification: dict) -> M.Document:
    doc = M.Document(sha256=sha256, size_bytes=len(data), content_type=content_type,
                     data=data, **classification)
    db.add(doc)
    db.flush()
    return doc


def same_content(cur_doc: M.Document | None, new_sha: str, new_cls: dict) -> bool:
    """Is the fetched file the same DOCUMENT as the one we hold?

    Same bytes: yes. Same text on every page: yes — that is a re-signed PDF,
    not a revision. Anything else, including two scans with different bytes,
    is a change."""
    if cur_doc is None:
        return False
    if cur_doc.sha256 == new_sha:
        return True
    new_text = new_cls.get("text_sha256")
    return bool(new_text) and cur_doc.text_sha256 == new_text


def changed_pages(old_doc: M.Document | None, new_cls: dict) -> dict:
    """What differs between the held document and the new one, read off the
    stored per-page hashes.

    ``pages`` is the pages of the NEW document that are new or edited.
    ``removed`` counts drawings the new document no longer has — a page that
    is gone has no number to report, and TXS0104E dropping three TSSOP pages
    would otherwise read as "nothing changed". ``parts_table`` says the
    orderable-part/lifecycle set moved. Every value is ``None`` when the
    answer is not available (a scan, or a document stored before page hashes
    existed)."""
    old = old_doc.page_hashes if old_doc is not None else None
    new = new_cls.get("page_hashes")
    blank = {"pages": None, "removed": None, "parts_table": None,
             "old_count": len(old) if old else None,
             "new_count": len(new) if new else None}
    if not old or not new:
        return blank
    # Body pages compare by position, unordered pages by membership (so a
    # reordered package section is nothing), the addendum by its one digest,
    # volatile pages not at all. See `page_identity`.
    old_unordered = collections.Counter(h for h in old if h.startswith(ROLE_UNORDERED))
    new_unordered = collections.Counter(h for h in new if h.startswith(ROLE_UNORDERED))
    old_addendum = next((h for h in old if h.startswith(ROLE_ADDENDUM)), None)
    new_addendum = next((h for h in new if h.startswith(ROLE_ADDENDUM)), None)
    parts_table = old_addendum is not None and new_addendum != old_addendum
    seen: collections.Counter = collections.Counter()
    pages, addendum_reported = [], False
    for i, h in enumerate(new):
        if h == ROLE_VOLATILE:
            continue
        if h.startswith(ROLE_ADDENDUM):
            # The digest repeats on every addendum page; report it once.
            if parts_table and not addendum_reported:
                pages.append(i + 1)
                addendum_reported = True
            continue
        if h.startswith(ROLE_UNORDERED):
            seen[h] += 1
            if seen[h] > old_unordered.get(h, 0):
                pages.append(i + 1)
            continue
        if i >= len(old) or old[i] != h:
            pages.append(i + 1)
    removed = sum(max(0, n - new_unordered.get(h, 0)) for h, n in old_unordered.items())
    return {"pages": pages, "removed": removed, "parts_table": parts_table,
            "old_count": len(old), "new_count": len(new)}


def _index_pages(document_id: int) -> None:
    """Kick off per-page extraction for a freshly stored document.

    Fire-and-forget in a daemon thread: a 642-page document is minutes of work
    and must never sit inside the upload or fetch request. The startup sweep
    catches anything a crash loses, because the document's `pages_indexed_at`
    stays NULL. Imported lazily — `datasheet_pages` imports this module."""
    try:
        from .datasheet_pages import index_one

        index_one(document_id)
    except Exception as e:  # noqa: BLE001 — a derived cache must never fail a store
        log.warning(f"could not start page indexing for document {document_id}: {e}")


def shared_with(db: Session, document_id: int, except_component_id: int | None = None) -> list[str]:
    """Names of the other components whose CURRENT copy is this document."""
    rows = (
        db.query(M.Component.name)
        .join(M.Datasheet, M.Datasheet.component_id == M.Component.id)
        .join(M.DatasheetVersion, M.DatasheetVersion.id == M.Datasheet.current_version_id)
        .filter(M.DatasheetVersion.document_id == document_id,
                M.Datasheet.archived.is_(False))
        .distinct()
        .all()
    )
    names = sorted({r[0] for r in rows})
    if except_component_id is not None:
        me = db.get(M.Component, except_component_id)
        if me is not None:
            names = [n for n in names if n != me.name]
    return names


# ------------------------------------------------------------------ pins
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


def datasheet_carries(db: Session, old_cv: M.ComponentVersion,
                      new_cv: M.ComponentVersion) -> tuple[bool, str]:
    """Did every datasheet the old version was verified against survive
    unchanged into the new one?

    The review record says "the drawing matches the documentation". When the
    documentation itself moved to a new revision, that statement is stale
    however untouched the properties are — so the carry must refuse. The
    first local copy of a document (old pin NULL, new pin set) is not a
    change: nothing was verified against nothing."""
    old = {l.datasheet_id: l.datasheet_version_id
           for l in db.query(M.ComponentVersionDatasheet).filter_by(component_version_id=old_cv.id)}
    new = {l.datasheet_id: l.datasheet_version_id
           for l in db.query(M.ComponentVersionDatasheet).filter_by(component_version_id=new_cv.id)}
    for ds_id, old_vid in old.items():
        new_vid = new.get(ds_id)
        if old_vid is None or new_vid is None or old_vid == new_vid:
            continue
        a = db.get(M.DatasheetVersion, old_vid)
        b = db.get(M.DatasheetVersion, new_vid)
        if a is None or b is None or a.document_id == b.document_id:
            continue
        if a.text_sha256 and a.text_sha256 == b.text_sha256:
            continue
        ds = db.get(M.Datasheet, ds_id)
        label = ds.label if ds else f"datasheet {ds_id}"
        return False, (f"datasheet {label!r} changed"
                       f" ({a.doc_revision or f'v{a.version_no}'}"
                       f" to {b.doc_revision or f'v{b.version_no}'})")
    return True, ""


def _bump_component_version(
    db: Session,
    ds: M.Datasheet,
    new_dv: M.DatasheetVersion,
    comment: str | None = None,
    created_by: str = "system",
    change: dict | None = None,
) -> int | None:
    """Auto-create a new published component version recording the changed
    document, through the shared publish path so every carry rule runs, and
    open a review request so the change reaches the worklist."""
    comp = db.get(M.Component, ds.component_id)
    if comp is None or comp.current_version_id is None:
        return None
    cur = db.get(M.ComponentVersion, comp.current_version_id)
    if cur is None or cur.status != "published":
        return None
    from .publish import publish_component_version

    numbers = [n for (n,) in db.query(M.ComponentVersion.version_no).filter_by(component_id=comp.id)]
    new_no = max(numbers, default=0) + 1
    cv = M.ComponentVersion(
        component_id=comp.id, version_no=new_no,
        base_component=cur.base_component,
        symbol_version_id=cur.symbol_version_id,
        footprint_version_id=cur.footprint_version_id,
        category_id=cur.category_id,
        removed_properties=cur.removed_properties,
        status="published", created_by=created_by,
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
    publish_component_version(db, comp, cv, actor=created_by, approved_by="auto")

    # The worklist pointer. One open request per subject is enough.
    open_req = (db.query(M.ReviewRequest)
                .filter_by(subject_kind="component", subject_id=comp.id, done_at=None)
                .first())
    if open_req is None and change is not None:
        db.add(M.ReviewRequest(subject_kind="component", subject_id=comp.id,
                               requested_by=created_by, note=change.get("note")))

    db.add(M.AuditLog(actor=created_by, action="component.datasheet_bump", entity_type="component",
                      entity_id=str(comp.id),
                      details={"component": comp.name, "version_no": new_no,
                               "datasheet_id": ds.id, "pdf_version": new_dv.version_no,
                               **(change or {})}))
    return new_no


def _change_note(ds: M.Datasheet, old_doc: M.Document | None, new_cls: dict,
                 new_no: int) -> dict:
    """What to tell the reviewer about a content change."""
    diff = changed_pages(old_doc, new_cls)
    old_rev = old_doc.doc_revision if old_doc else None
    new_rev = new_cls.get("doc_revision")
    parts = [f"Datasheet {ds.label!r} changed"]
    if old_rev or new_rev:
        parts.append(f"revision {old_rev or '?'} → {new_rev or '?'}")
        if old_rev and old_rev == new_rev:
            parts.append("same revision label, text changed")
    if diff["pages"] is not None:
        shown = ", ".join(str(p) for p in diff["pages"][:20])
        more = f" (+{len(diff['pages']) - 20} more)" if len(diff["pages"]) > 20 else ""
        parts.append(f"pages new or edited: {shown or 'none'}{more}")
        if diff["removed"]:
            parts.append(f"{diff['removed']} page(s) removed")
        if diff["parts_table"]:
            parts.append("the orderable-part/lifecycle table changed")
        if diff["old_count"] != diff["new_count"]:
            parts.append(f"page count {diff['old_count']} → {diff['new_count']}")
    else:
        parts.append("page-level diff not available")
    return {"note": "; ".join(parts), "old_revision": old_rev, "new_revision": new_rev,
            "changed_pages": diff["pages"], "removed_pages": diff["removed"],
            "parts_table_changed": diff["parts_table"], "pdf_version": new_no}


def _attach_first_copy(db: Session, ds: M.Datasheet) -> None:
    """First local copy — not a content *change*; attach to the current
    component version without bumping."""
    comp = db.get(M.Component, ds.component_id)
    if comp is not None and comp.current_version_id is not None:
        cv = db.get(M.ComponentVersion, comp.current_version_id)
        if cv is not None:
            pin_datasheets(db, cv)


# ------------------------------------------------------------------ fetch
def fetch_datasheet(db: Session, ds: M.Datasheet, conditional: bool = True) -> dict:
    """Download ds.source_url; create a new version only on content change.
    Returns a result dict; raises httpx.HTTPError on network failure.

    The decision ladder, first answer wins:

    1. 304 → unchanged.
    2. same bytes as the current document → unchanged, validators refreshed.
    3. same page text (a re-signed PDF) → "restamped": validators refreshed,
       nothing stored.
    4. bytes already held as some OTHER document (another component fetched
       them first) → "relinked": a new version pointing at that document.
    5. otherwise a new document and a new version.
    A new version on a published component bumps it (see the module doc).

    `conditional` replays the stored ETag / Last-Modified so a server that
    still has the same document answers 304 and we skip the download
    entirely — that is what makes a nightly re-check of every datasheet
    cheap. Pass False to force a full download (the manual "re-fetch"
    button), since a supplier can swap file content without touching the
    validators."""
    if not ds.source_url:
        return {"id": ds.id, "result": "no_url"}
    cur = current_version(ds)
    cur_doc = cur.document if cur is not None else None
    headers: dict = {}
    if conditional and cur is not None:
        if cur.etag:
            headers["If-None-Match"] = cur.etag
        if cur.last_modified:
            headers["If-Modified-Since"] = cur.last_modified
    resp, _ua = _get(db, ds.source_url, headers)
    if resp.status_code == 304:
        # The supplier confirms the document we hold is still current. A 304
        # carries no body, so never fall through to the download path — a
        # server that answers 304 unconditionally would otherwise store an
        # empty "new version".
        if cur is None:
            db.commit()
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
    # identity comparison: a supplier that starts serving an error page under
    # the old URL must read as "rejected", not as "unchanged". Any copy we
    # already hold survives untouched, which is the right outcome.
    classification, reject = inspect_document(data, content_type, filename)
    if reject is not None:
        db.add(M.AuditLog(actor="system", action="datasheet.rejected",
                          entity_type="datasheet", entity_id=str(ds.id),
                          details={"url": ds.source_url, "reason": reject,
                                   "size": len(data), "content_type": content_type}))
        db.commit()
        return {"id": ds.id, "result": "rejected", "reason": reject,
                "version_no": cur.version_no if cur else None}

    if cur is not None and same_content(cur_doc, sha, classification):
        restamped = cur_doc.sha256 != sha
        cur.fetched_at = datetime.now(timezone.utc)  # bookkeeping: last verified
        # Learn validators the stored copy didn't have yet (or that rotated),
        # so the next nightly pass can settle this datasheet with a 304.
        cur.etag, cur.last_modified = etag, last_modified
        if restamped:
            # Same text, new bytes: the vendor re-signed the file. Not a
            # revision, so nothing is stored — but say so, because this is
            # exactly the pattern that used to produce 32 copies of one PDF.
            db.add(M.AuditLog(actor="system", action="datasheet.restamped",
                              entity_type="datasheet", entity_id=str(ds.id),
                              details={"url": ds.source_url, "held_sha": cur_doc.sha256[:12],
                                       "served_sha": sha[:12], "size": len(data)}))
        db.commit()
        return {"id": ds.id, "result": "restamped" if restamped else "unchanged",
                "version_no": cur.version_no, "doc_revision": cur_doc.doc_revision}

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

    doc = find_document(db, sha)
    relinked = doc is not None
    if doc is None:
        doc = _new_document(db, data, sha, content_type, classification)

    new_no = (cur.version_no if cur else 0) + 1
    dv = M.DatasheetVersion(
        datasheet_id=ds.id, document_id=doc.id, version_no=new_no, filename=filename,
        etag=etag, last_modified=last_modified,
    )
    db.add(dv)
    db.flush()
    ds.current_version_id = dv.id

    bumped = None
    change = None
    if cur is None:
        _attach_first_copy(db, ds)
    else:
        change = _change_note(ds, cur_doc, classification, new_no)
        bumped = _bump_component_version(db, ds, dv, change=change)

    db.add(M.AuditLog(actor="system", action="datasheet.fetch", entity_type="datasheet",
                      entity_id=str(ds.id),
                      details={"url": ds.source_url, "pdf_version": new_no, "size": len(data),
                               "content_type": content_type, "document_id": doc.id,
                               "relinked": relinked, "doc_revision": doc.doc_revision,
                               "component_bumped_to": bumped}))
    db.commit()
    if not relinked or doc.pages_indexed_at is None:
        _index_pages(doc.id)
    is_pdf = (content_type == "application/pdf") or filename.lower().endswith(".pdf")
    return {"id": ds.id, "result": "new_version", "version_no": new_no,
            "looks_like_pdf": is_pdf, "component_bumped_to": bumped,
            "relinked": relinked, "doc_revision": doc.doc_revision,
            "change": change}


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
    cur_doc = cur.document if cur is not None else None
    if cur is not None and same_content(cur_doc, sha, classification):
        cur.fetched_at = datetime.now(timezone.utc)
        db.commit()
        return {"id": ds.id, "result": "unchanged", "version_no": cur.version_no}

    doc = find_document(db, sha)
    relinked = doc is not None
    if doc is None:
        doc = _new_document(db, data, sha, content_type, classification)

    new_no = (cur.version_no if cur else 0) + 1
    dv = M.DatasheetVersion(
        datasheet_id=ds.id, document_id=doc.id, version_no=new_no,
        filename=filename or f"{ds.label}.bin",
    )
    db.add(dv)
    db.flush()
    ds.current_version_id = dv.id

    bumped = None
    if cur is None:
        _attach_first_copy(db, ds)
    else:
        change = _change_note(ds, cur_doc, classification, new_no)
        bumped = _bump_component_version(
            db, ds, dv,
            comment=f"File '{ds.label}' replaced by upload → v{new_no}",
            created_by="user", change=change,
        )

    db.add(M.AuditLog(actor="user", action="datasheet.upload", entity_type="datasheet",
                      entity_id=str(ds.id),
                      details={"filename": filename, "file_version": new_no, "size": len(data),
                               "content_type": content_type, "document_id": doc.id,
                               "relinked": relinked, "component_bumped_to": bumped}))
    db.commit()
    if not relinked or doc.pages_indexed_at is None:
        _index_pages(doc.id)
    is_pdf = (content_type == "application/pdf") or (filename or "").lower().endswith(".pdf")
    return {"id": ds.id, "result": "new_version", "version_no": new_no,
            "looks_like_pdf": is_pdf, "component_bumped_to": bumped,
            "relinked": relinked, "doc_revision": doc.doc_revision}


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
    doc = find_document(db, sha)
    relinked = doc is not None
    if doc is None:
        doc = _new_document(db, data, sha, content_type, classification)
    dv = M.DatasheetVersion(
        datasheet_id=ds.id, document_id=doc.id, version_no=1,
        filename=filename or f"{label}.bin",
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
                               "document_id": doc.id, "relinked": relinked,
                               "component_bumped_to": bumped}))
    db.commit()
    if not relinked or doc.pages_indexed_at is None:
        _index_pages(doc.id)
    return {"id": ds.id, "result": "created", "version_no": 1,
            "component_bumped_to": bumped, "relinked": relinked}


# ------------------------------------------------------------- workers
def start_fetch_all(mode: str = "missing", trigger: str = "manual") -> bool:
    """Background fetch of every non-archived datasheet with a source URL.
    mode 'missing': only those without a local copy; 'all': re-check everything
    (content-change detection)."""
    with _lock:
        if FETCH_STATE["running"]:
            return False
        FETCH_STATE.update(running=True, mode=mode, trigger=trigger, done=0, total=0,
                           new_versions=0, unchanged=0, not_modified=0, restamped=0,
                           relinked=0, errors=0, rejected=0, last_error=None,
                           started_at=datetime.now(timezone.utc).isoformat(), finished_at=None)
    threading.Thread(target=_fetch_all_worker, args=(mode, None), daemon=True).start()
    return True


def start_fetch_component(component_id: int) -> None:
    """Fetch the rows of ONE component that have no local copy yet, right
    after a publish that added or changed a URL, so a new part has its PDF
    within seconds instead of at 03:00. Independent of the global run: it
    holds no state and never blocks on the fetch-all lock."""
    threading.Thread(target=_fetch_all_worker, args=("missing", component_id),
                     daemon=True).start()


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


def _fetch_all_worker(mode: str, component_id: int | None) -> None:
    scoped = component_id is not None  # a per-component run reports nowhere
    db = SessionLocal()
    try:
        q = db.query(M.Datasheet).filter(M.Datasheet.archived.is_(False),
                                         M.Datasheet.source_url.isnot(None))
        if mode == "missing":
            q = q.filter(M.Datasheet.current_version_id.is_(None))
        if scoped:
            q = q.filter(M.Datasheet.component_id == component_id)
        ids = [ds.id for ds in q.all()]
        if not scoped:
            FETCH_STATE["total"] = len(ids)
        new_versions = 0
        for ds_id in ids:
            ds = db.get(M.Datasheet, ds_id)
            if ds is None:
                continue
            try:
                r = fetch_datasheet(db, ds)
                res = r["result"]
                if res == "new_version":
                    new_versions += 1
                    if not scoped:
                        FETCH_STATE["new_versions"] += 1
                        if r.get("relinked"):
                            FETCH_STATE["relinked"] += 1
                elif not scoped and res == "unchanged":
                    FETCH_STATE["unchanged"] += 1
                    if r.get("not_modified"):
                        FETCH_STATE["not_modified"] += 1
                elif not scoped and res == "restamped":
                    FETCH_STATE["restamped"] += 1
                elif not scoped and res == "rejected":
                    # Not an error: the download arrived and was refused on
                    # purpose. Counted separately so a supplier that starts
                    # serving junk is visible instead of looking like a network
                    # problem.
                    FETCH_STATE["rejected"] += 1
                    FETCH_STATE["last_error"] = f"datasheet {ds_id} refused: {r['reason']}"
            except Exception as e:
                db.rollback()
                if scoped:
                    log.warning(f"fetch for component {component_id}, datasheet {ds_id}: {e}")
                else:
                    FETCH_STATE["errors"] += 1
                    FETCH_STATE["last_error"] = f"datasheet {ds_id}: {e}"
            if not scoped:
                FETCH_STATE["done"] += 1
            memory.trim()  # a downloaded document was just freed — see services/memory
            time.sleep(0.3)  # be polite to supplier servers
        # Newly local PDF copies change the generated Datasheet links —
        # refresh all mirror symbol libraries once at the end of the run.
        if new_versions:
            try:
                from ..config import settings
                from .mirror import update_mirror_symbols

                tops = {c.name for c in db.query(M.Category).filter(M.Category.parent_id.is_(None))}
                update_mirror_symbols(db, settings, tops)
            except Exception as e:
                if not scoped:
                    FETCH_STATE["last_error"] = f"mirror refresh: {e}"
                else:
                    log.warning(f"mirror refresh after component fetch: {e}")
    finally:
        db.close()
        if not scoped:
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

    rows = (db.query(M.Document.text_layer, func.count())
            .group_by(M.Document.text_layer).all())
    return {(cls or "unclassified"): n for cls, n in rows}


def _needs_classification(q):
    """Documents the classifier has not seen in its current form: never
    classified, or classified before the text hash existed (searchable PDFs
    with no `text_sha256`), which the revision ladder needs."""
    return q.filter(
        (M.Document.text_layer == "")
        | (M.Document.text_layer.in_(("text", "mixed")) & M.Document.text_sha256.is_(None))
    )


def start_text_layer_classify(mode: str = "missing") -> bool:
    """Classify stored documents in the background.

    mode 'missing': only rows the classifier has never seen in its current
    form — this is what runs at startup, so documents archived before the
    columns existed get their tags and their text hash. mode 'all':
    re-classify everything, for when the thresholds change.

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
    session before taking the next. A `query(Document).all()` here would pull
    the whole library into the API container's memory."""
    db = SessionLocal()
    try:
        q = db.query(M.Document.id).order_by(M.Document.id)
        if mode == "missing":
            q = _needs_classification(q)
        ids = [row[0] for row in q.all()]
        CLASSIFY_STATE["total"] = len(ids)
        for doc_id in ids:
            try:
                doc = db.get(M.Document, doc_id)
                if doc is not None:
                    # The filename lives on the version rows (it is per fetch);
                    # a `.pdf` name is one of the three ways a file counts as a
                    # PDF, so a document served as octet-stream with junk
                    # before `%PDF-` would flip to "none" without it.
                    name = next((v.filename for v in doc.versions if v.filename), None)
                    for k, v in classify_text_layer(
                        doc.data, doc.content_type, name
                    ).items():
                        setattr(doc, k, v)
                    db.commit()
                    db.expunge(doc)
            except Exception as e:  # noqa: BLE001 — one bad PDF must not stop the sweep
                db.rollback()
                CLASSIFY_STATE["last_error"] = f"document {doc_id}: {e}"
                log.warning(f"text-layer classification of document {doc_id} failed: {e}")
            CLASSIFY_STATE["done"] += 1
            memory.trim()  # give the freed blob back to the OS, not to the arena
            time.sleep(0.02)  # leave the API responsive during the startup sweep
    finally:
        db.close()
        CLASSIFY_STATE["running"] = False
        CLASSIFY_STATE["finished_at"] = datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------- broken-file cleanup
def _version_rows_json(db: Session, dv: M.DatasheetVersion) -> dict:
    ds = db.get(M.Datasheet, dv.datasheet_id)
    comp = db.get(M.Component, ds.component_id) if ds is not None else None
    siblings = [v for v in (ds.versions if ds is not None else []) if v.id != dv.id]
    pins = (db.query(M.ComponentVersionDatasheet)
            .filter_by(datasheet_version_id=dv.id).count())
    return {
        "version_id": dv.id,
        "datasheet_id": dv.datasheet_id,
        "component_id": comp.id if comp else None,
        "component": comp.name if comp else None,
        "label": ds.label if ds else None,
        "version_no": dv.version_no,
        "filename": dv.filename,
        "is_current": ds is not None and ds.current_version_id == dv.id,
        # What the row falls back to once this version is gone.
        "falls_back_to": (max(siblings, key=lambda v: v.version_no).version_no
                          if siblings else None),
        "source_url": ds.source_url if ds else None,
        "pinned_by_versions": pins,
    }


def find_broken(db: Session) -> list[dict]:
    """Stored versions whose document nothing can open: empty files, and PDFs
    that fail to parse or are password-locked (`text_layer = "error"`).

    A `scan` is NOT broken. It opens, it is a real document, it is only
    unsearchable — that is what the tag and `cmp.datasheet_text` are for."""
    rows = (
        db.query(M.DatasheetVersion)
        .join(M.Document, M.Document.id == M.DatasheetVersion.document_id)
        .filter((M.Document.text_layer == "error") | (M.Document.size_bytes == 0))
        .order_by(M.DatasheetVersion.id)
        .all()
    )
    out = []
    for dv in rows:
        doc = dv.document
        out.append({
            **_version_rows_json(db, dv),
            "document_id": doc.id,
            "content_type": doc.content_type,
            "size_bytes": doc.size_bytes,
            "text_layer": doc.text_layer,
        })
    return out


def _drop_orphan_documents(db: Session) -> int:
    """Delete documents no version points at any more (their pages first)."""
    from sqlalchemy import delete, select

    orphans = [d for (d,) in db.execute(
        select(M.Document.id).where(
            ~select(M.DatasheetVersion.id).where(
                M.DatasheetVersion.document_id == M.Document.id).exists())).all()]
    if orphans:
        db.execute(delete(M.DatasheetPage).where(M.DatasheetPage.document_id.in_(orphans)))
        db.execute(delete(M.Document).where(M.Document.id.in_(orphans)))
    return len(orphans)


def _refresh_mirror_for(db: Session, component_ids: set[int]) -> list[str]:
    try:
        from ..config import settings

        from .mirror import top_level_of, update_mirror_symbols

        tops = set()
        for comp_id in component_ids:
            comp = db.get(M.Component, comp_id)
            if comp is None or comp.current_version_id is None:
                continue
            cv = db.get(M.ComponentVersion, comp.current_version_id)
            if cv is not None:
                tops.add(top_level_of(cv.category).name)
        if tops:
            update_mirror_symbols(db, settings, tops)
        return sorted(tops)
    except Exception as e:  # noqa: BLE001 — the data change already landed
        log.warning(f"mirror refresh failed: {e}")
        return []


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
    The document itself goes once nothing points at it.
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
    db.flush()
    dropped = _drop_orphan_documents(db)
    db.commit()
    refreshed = _refresh_mirror_for(db, touched_components)
    return {"removed": len(found), "documents_dropped": dropped, "items": found,
            "categories_refreshed": refreshed}


# ---------------------------------------------------------- restamp collapse
def _content_key(dv: M.DatasheetVersion) -> str:
    """What makes two versions the same document: the text hash when there is
    text, the bytes otherwise."""
    doc = dv.document
    return f"t:{doc.text_sha256}" if doc.text_sha256 else f"b:{doc.id}"


def find_restamps(db: Session) -> list[dict]:
    """Versions that carry the same document as the version before them —
    the history the byte-identity rule wrote before the text hash existed
    (TPS61023: 32 versions of one Rev. B). Each is listed with the version it
    collapses into. Requires the classification backfill to have run: a
    document with no text hash yet compares by bytes and never matches."""
    out: list[dict] = []
    sheets = db.query(M.Datasheet).order_by(M.Datasheet.id).all()
    for ds in sheets:
        versions = sorted(ds.versions, key=lambda v: v.version_no)
        survivor: M.DatasheetVersion | None = None
        for v in versions:
            if survivor is not None and _content_key(v) == _content_key(survivor):
                pins = (db.query(M.ComponentVersionDatasheet)
                        .filter_by(datasheet_version_id=v.id).count())
                out.append({"datasheet_id": ds.id, "label": ds.label,
                            "component_id": ds.component_id,
                            "version_id": v.id, "version_no": v.version_no,
                            "into_version_no": survivor.version_no,
                            "into_version_id": survivor.id,
                            "document_id": v.document_id,
                            "doc_revision": v.document.doc_revision,
                            "is_current": ds.current_version_id == v.id,
                            "pinned_by_versions": pins})
            else:
                survivor = v
    return out


def collapse_restamps(db: Session, actor: str = "system") -> dict:
    """Fold every restamped version into the version it repeats.

    Pins move to the survivor (the same text, so every statement made against
    the folded version holds against it), the survivor takes the newest
    validators and fetch time so the next nightly pass still settles with a
    304, and `current_version_id` follows. Documents nothing points at any
    more are deleted with their pages. Component versions created by the old
    bumps are history and stay."""
    found = find_restamps(db)
    if not found:
        return {"removed": 0, "documents_dropped": 0, "items": []}
    touched: set[int] = set()
    for row in found:
        v = db.get(M.DatasheetVersion, row["version_id"])
        into = db.get(M.DatasheetVersion, row["into_version_id"])
        if v is None or into is None:
            continue
        ds = db.get(M.Datasheet, v.datasheet_id)
        db.query(M.ComponentVersionDatasheet).filter_by(
            datasheet_version_id=v.id
        ).update({"datasheet_version_id": into.id}, synchronize_session=False)
        if v.fetched_at and (into.fetched_at is None or v.fetched_at > into.fetched_at):
            into.fetched_at = v.fetched_at
            into.etag, into.last_modified = v.etag, v.last_modified
        if ds is not None and ds.current_version_id == v.id:
            ds.current_version_id = into.id
            touched.add(ds.component_id)
        db.delete(v)
        db.add(M.AuditLog(
            actor=actor, action="datasheet.collapse_restamp", entity_type="datasheet",
            entity_id=str(row["datasheet_id"]),
            details={k: row[k] for k in ("label", "version_no", "into_version_no",
                                         "doc_revision", "is_current", "pinned_by_versions")}))
    db.flush()
    dropped = _drop_orphan_documents(db)
    db.commit()
    refreshed = _refresh_mirror_for(db, touched)
    return {"removed": len(found), "documents_dropped": dropped, "items": found,
            "categories_refreshed": refreshed}


def storage_stats(db: Session) -> dict:
    """The numbers that show the dedupe is holding."""
    from sqlalchemy import func

    docs, doc_bytes = db.query(func.count(M.Document.id),
                               func.coalesce(func.sum(M.Document.size_bytes), 0)).one()
    versions = db.query(func.count(M.DatasheetVersion.id)).scalar()
    shared = (db.query(M.DatasheetVersion.document_id)
              .group_by(M.DatasheetVersion.document_id)
              .having(func.count(func.distinct(M.DatasheetVersion.datasheet_id)) > 1)
              .count())
    hosts = db.query(M.FetchHost).count()
    return {"documents": docs, "document_bytes": int(doc_bytes), "versions": versions,
            "documents_shared_by_several_datasheets": shared, "hosts_learned": hosts}
