"""The JLC placement keys keep a part's review state (decision 0110).

Two side effects of writing `FT Rotation Offset` on the project parts,
measured on production 2026-11-13: `cmp.electrical` began to apply to parts
with no electrical data (10 fell to `partial`), and exceptions pinned to the
component's data digest lapsed (4 parts). Both are covered here.
"""
import pathlib
import sys

import pytest
from sqlalchemy.orm import Session

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from app import models as M
from app.db import engine
from app.services import checklists, exceptions, publish
from app.services.checklists import _property_sha


@pytest.fixture
def db():
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


def _cv(comp, no, props):
    cv = M.ComponentVersion(component_id=comp.id, version_no=no, base_component="R",
                            category_id=comp._cat, removed_properties=[], status="published")
    cv.properties = [M.ComponentProperty(position=i, key=k, value=v, is_null=False)
                     for i, (k, v) in enumerate(props)]
    return cv


@pytest.fixture
def comp(db):
    c = M.Component(name="__test_jlc_placement__")
    db.add(c)
    db.flush()
    c._cat = db.query(M.Category.id).order_by(M.Category.id).first()[0]
    return c


BASE = [("Value", "10k"), ("LCSC Part", "C25744"), ("Manufacturer 1", "Yageo")]


def test_a_rotation_is_not_an_electrical_value(db, comp):
    cv = _cv(comp, 1, BASE + [("FT Rotation Offset", "270"), ("FT Position Offset", "0,0")])
    db.add(cv)
    db.flush()
    assert checklists._derived_providers(db, cv)["$electrical_props"]() == "0"


def test_a_placement_edit_repins_the_exceptions(db, comp):
    old = _cv(comp, 1, BASE)
    new = _cv(comp, 2, BASE + [("FT Rotation Offset", "180")])
    db.add_all([old, new])
    db.flush()
    exc = exceptions.grant(db, "component", comp, "cmp.description", reason="kind_exempt",
                           note="free text by decision", actor="test", actor_type="agent",
                           depends_on={"$property_sha": _property_sha(old)})
    assert publish._repin_for_placement_edit(db, comp, old, new, "test") == 1
    live = exceptions.live_for(db, "component", comp.id)
    (now,) = live.values()
    assert now.id != exc.id and exc.revoked_at is not None
    assert now.depends_on["$property_sha"] == _property_sha(new)
    assert now.reason == "kind_exempt" and now.actor_type == "agent"


def test_any_other_change_lets_the_exception_lapse(db, comp):
    old = _cv(comp, 1, BASE)
    new = _cv(comp, 2, [("Value", "12k"), ("LCSC Part", "C25744"), ("Manufacturer 1", "Yageo"),
                        ("FT Rotation Offset", "180")])
    db.add_all([old, new])
    db.flush()
    exceptions.grant(db, "component", comp, "cmp.description", reason="kind_exempt",
                     note="free text by decision", actor="test", actor_type="agent",
                     depends_on={"$property_sha": _property_sha(old)})
    assert publish._repin_for_placement_edit(db, comp, old, new, "test") == 0
