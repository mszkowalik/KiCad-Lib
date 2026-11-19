"""A draft older than the live version does not block the repoint.

`repoint_for` skips a component that has a human/agent draft, because
repointing it would rewrite an edit under review. Since 2026-08-23 nothing can
approve or discard a draft, so a v1 draft that `propose_new_component` left
behind before v2 was published blocked every later repoint: TCA6408ARGTR stayed
on QFN-16 v8 through the v9 and v10 publishes (found 2026-11-19). Only a draft
NEWER than the live version is an edit in progress.

Each test builds its own footprint (a copy of the 0402 land under a new name)
and component, on a connection whose outer transaction is rolled back, so
nothing reaches the dev database and no real part is repointed.

Run from `api/`, with the dev database up:
    python -m pytest tests/library -q
"""
import pathlib
import sys
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import repoint


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        sym = s.query(M.Symbol).filter_by(name="R").first()
        src_fp = s.query(M.Footprint).filter_by(name="R_0402_1005Metric").first()
        cat = s.query(M.Category).filter_by(name="Resistor").first()
        if sym is None or src_fp is None or cat is None or src_fp.current_version_id is None:
            pytest.skip("dev database lacks the R symbol, the 0402 land or the Resistor category")
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _setup(db, draft_version_no):
    """A component live at v2 on footprint v1, a footprint v2 just published,
    and a `jaravis` draft numbered `draft_version_no`."""
    sym = db.query(M.Symbol).filter_by(name="R").first()
    cat = db.query(M.Category).filter_by(name="Resistor").first()
    src = db.get(M.FootprintVersion, db.query(M.Footprint).filter_by(name="R_0402_1005Metric").first()
                 .current_version_id)

    tag = uuid.uuid4().hex[:8]
    fp = M.Footprint(name=f"TEST_FP_{tag}")
    db.add(fp)
    db.flush()
    fv1 = M.FootprintVersion(footprint_id=fp.id, version_no=1, source_text=src.source_text,
                             parsed=src.parsed, models=src.models)
    db.add(fv1)
    db.flush()

    comp = M.Component(name=f"TEST-{tag}")
    db.add(comp)
    db.flush()

    def cv(no, status):
        row = M.ComponentVersion(component_id=comp.id, version_no=no, base_component="R",
                                 symbol_version_id=sym.current_version_id, footprint_version_id=fv1.id,
                                 category_id=cat.id, status=status, created_by="jaravis", comment="test")
        db.add(row)
        db.flush()
        db.add(M.ComponentProperty(component_version_id=row.id, position=0, key="Value", value="1K"))
        db.add(M.ComponentProperty(component_version_id=row.id, position=1, key="Footprint",
                                   value=f"7Sigma:{fp.name}"))
        return row

    rows = {no: cv(no, "draft" if no == draft_version_no else "published")
            for no in sorted({1, 2, draft_version_no})}
    comp.current_version_id = rows[2].id

    fv2 = M.FootprintVersion(footprint_id=fp.id, version_no=2, source_text=src.source_text,
                             parsed=src.parsed, models=src.models)
    db.add(fv2)
    db.flush()
    fp.current_version_id = fv2.id
    db.flush()
    return comp, fp, fv2


def test_a_draft_older_than_the_live_version_does_not_block(db):
    comp, fp, fv2 = _setup(db, draft_version_no=1)

    out = repoint.repoint_for(db, "footprint", fp)

    assert out["skipped"] == []
    assert out["published"] == [comp.name]
    live = db.get(M.ComponentVersion, comp.current_version_id)
    assert (live.version_no, live.footprint_version_id, live.created_by) == (3, fv2.id, repoint.AUTO_ACTOR)
    # The leftover is reported elsewhere, not touched here.
    v1 = db.query(M.ComponentVersion).filter_by(component_id=comp.id, version_no=1).one()
    assert v1.status == "draft"


def test_a_draft_newer_than_the_live_version_still_blocks(db):
    comp, fp, _ = _setup(db, draft_version_no=3)
    live_before = comp.current_version_id

    out = repoint.repoint_for(db, "footprint", fp)

    assert out["published"] == []
    assert out["skipped"] == [{"component": comp.name, "reason": "an edit is already pending review"}]
    assert comp.current_version_id == live_before
