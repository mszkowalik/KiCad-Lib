"""Library → Datasheets: every figure counts one set, and says what KiCad opens.

Found 2026-11-07 on production:

- the Archive tab read "474 / 470 datasheets stored". The total counted rows
  with a source URL, the stored count counted rows with a copy, uploads with no
  URL included, so more were stored than existed;
- the page said "KiCad reads the archived copy" for every stored document,
  while for a stored web page KiCad keeps the live link;
- Search printed "50 page(s)" whenever 50 or more pages matched, because it
  printed the number of rows it had asked for.

Run from `api/`, with the dev database up:
    python -m pytest tests/library -q
"""
import hashlib
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import datasheets as router
from app.services import datasheet_pages


@pytest.fixture
def db():
    """One transaction, never committed: the dev database is left untouched."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _datasheet(db, comp, position, url, content_type=None, filename=None, archived=False):
    ds = M.Datasheet(component_id=comp.id, position=position,
                     label=f"DS{position}", source_url=url, archived=archived)
    db.add(ds)
    db.flush()
    if content_type is not None:
        body = uuid.uuid4().bytes
        doc = M.Document(sha256=hashlib.sha256(body).hexdigest(), size_bytes=len(body),
                         content_type=content_type, data=body)
        db.add(doc)
        db.flush()
        ver = M.DatasheetVersion(datasheet_id=ds.id, document_id=doc.id, version_no=1,
                                 filename=filename)
        db.add(ver)
        db.flush()
        ds.current_version_id = ver.id
        db.flush()
        return ds, doc
    return ds, None


@pytest.fixture
def component(db):
    comp = M.Component(name=f"TEST-DS-{uuid.uuid4().hex[:8]}")
    db.add(comp)
    db.flush()
    return comp


# ------------------------------------------------------------ finding 5
def test_every_archive_figure_counts_one_set(db, component):
    before = router.archive_counts(db)
    _datasheet(db, component, 0, "https://example.invalid/a.pdf", "application/pdf", "a.pdf")
    _datasheet(db, component, 1, "https://example.invalid/b", "text/html", "b.html")
    _datasheet(db, component, 2, None, "text/html", "upload.html")  # an upload, no URL
    _datasheet(db, component, 3, "https://example.invalid/d.pdf")  # not fetched yet
    _datasheet(db, component, 4, "https://example.invalid/e.pdf", "application/pdf", "e.pdf",
               archived=True)
    after = router.archive_counts(db)
    d = {k: after[k] - before[k] for k in after}

    assert d["datasheets_total"] == 4, "the archived row is not in the set, the upload is"
    assert d["datasheets_with_local_copy"] == 3
    assert d["datasheets_kicad_local"] == 2, "a PDF and an upload open the stored copy"
    assert d["datasheets_kicad_live"] == 1, "a stored web page keeps its live link"
    assert d["datasheets_without_url"] == 1
    assert after["datasheets_with_local_copy"] <= after["datasheets_total"]
