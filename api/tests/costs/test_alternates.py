"""An approved alternate stands in for a part while the schematic stays
(decision 0108).

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_alternates.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import alternates as A
from app.services import planning as PL
from app.services import plans as plan_svc
from app.services import substitutions as S

TODAY = date(2026, 11, 9)


@pytest.fixture
def db():
    """One transaction, never committed: the dev database is left untouched."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    try:
        yield s
    finally:
        s.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def parts(db: Session):
    spec = M.Component(name="test-alt-T491D107K016AT")
    alt = M.Component(name="test-alt-TAJD107K016RNJ")
    other = M.Component(name="test-alt-other")
    db.add_all([spec, alt, other])
    db.flush()
    return SimpleNamespace(spec=spec, alt=alt, other=other)


def test_an_approval_is_one_direction(db, parts):
    A.add(db, parts.spec.id, parts.alt.id, note="same D case, 100 uF 16 V")
    assert A.is_approved(db, parts.spec.id, parts.alt.id)
    assert not A.is_approved(db, parts.alt.id, parts.spec.id)
    with pytest.raises(A.AlternateError):
        A.add(db, parts.spec.id, parts.alt.id)
    with pytest.raises(A.AlternateError):
        A.add(db, parts.spec.id, parts.spec.id)


def test_one_alternate_of_a_part_carries_buy(db, parts):
    a = A.add(db, parts.spec.id, parts.alt.id, buy=True)
    b = A.add(db, parts.spec.id, parts.other.id, buy=True)
    db.refresh(a)
    assert not a.buy and b.buy
    assert A.buy_alternates(db)[parts.spec.id] == parts.other.id


def test_a_project_block_refuses_the_alternate_there_only(db, parts):
    p1 = M.Project(name="test-alt-p1", git_url="https://example.invalid/a1.git")
    p2 = M.Project(name="test-alt-p2", git_url="https://example.invalid/a2.git")
    db.add_all([p1, p2])
    db.flush()
    A.add(db, parts.spec.id, parts.alt.id)
    A.add_block(db, p1.id, parts.spec.id, parts.alt.id, refs="C2")
    assert not A.is_approved(db, parts.spec.id, parts.alt.id, p1.id, "C2")
    assert A.is_approved(db, parts.spec.id, parts.alt.id, p1.id, "C5")
    assert A.is_approved(db, parts.spec.id, parts.alt.id, p2.id, "C2")


def test_an_approved_alternate_ends_the_drift_finding(db, parts):
    """V2 C2: the schematic names C110548, Batch 7 fitted C7223, and the
    schematic stays. Approving C7223 is the answer the drawing would give."""
    proj = M.Project(name="test-alt-drift", git_url="https://example.invalid/d.git")
    db.add(proj)
    db.flush()
    snap = M.ProjectSnapshot(project_id=proj.id, status="ready", sha="0" * 40,
                             created_at=datetime(2026, 1, 1, tzinfo=UTC))
    db.add(snap)
    db.flush()
    db.add(M.SnapshotBomLine(snapshot_id=snap.id, board="B1", variant="", position=1, refs="C2", qty=1,
                             value="100uF", lcsc="CALTSPEC", mpn="SPEC", component_id=parts.spec.id))
    run = M.ProductionRun(project_id=proj.id, label="B7", board="B1", variant="", run_date="2026-05-01",
                          status="completed", qty=10, snapshot_id=snap.id)
    db.add(run)
    db.flush()
    db.add(M.RunSubstitution(run_id=run.id, board="B1", variant="", designator="C2",
                             specified_lcsc="CALTSPEC", specified_component_id=parts.spec.id,
                             fitted_lcsc="CALTFIT", fitted_component_id=parts.alt.id, qty_per_device=1))
    db.flush()

    def mine():
        return [d for d in S.drift(db) if d["run_id"] == run.id]

    assert len(mine()) == 1
    A.add(db, parts.spec.id, parts.alt.id)
    assert mine() == []
    A.add_block(db, proj.id, parts.spec.id, parts.alt.id)   # the circuit cares: the finding is back
    assert len(mine()) == 1


@pytest.fixture
def plan_world(db: Session, parts):
    cust = M.Customer(name="test-alt-customer", payment_terms_days=14)
    proj = M.Project(name="test-alt-plan-project", git_url="https://example.invalid/ap.git")
    db.add_all([cust, proj])
    db.flush()
    snap = M.ProjectSnapshot(project_id=proj.id, sha="b" * 40, ref_name="v1", is_tag=True, status="ready",
                             boards=[{"name": "B", "kind": "board"}])
    db.add(snap)
    db.flush()
    db.add(M.SnapshotBomLine(snapshot_id=snap.id, board="B", variant="", refs="C2", qty=1,
                             component_id=parts.spec.id, value="100uF"))
    plan = M.Plan(name="test alt plan", customer_id=cust.id, advance_days=14, final_days=14, min_lead_months=2,
                  advance_limit_net=106000, delivery_weekday=3, build_lead_days=7, attrition_pct=0)
    db.add(plan)
    db.flush()
    plan_svc.set_projects(db, plan, [{"project_id": proj.id, "snapshot_mode": "fixed", "snapshot_id": snap.id}])
    plan_svc.add_order(db, plan, {"plan_key": "V2-1", "order_date": "2026-12-01", "lines": [
        {"project_id": proj.id, "qty_ordered": 200, "unit_price": 220.0,
         "deliveries": [{"qty": 200, "day": "2027-02-11"}]}]}, "test")
    plan_svc.add_batch(db, plan, {"project_id": proj.id, "qty": 200, "label": "B1", "order": {"day": "2026-12-15"}})
    db.flush()
    return SimpleNamespace(plan=plan, proj=proj)


def _stock(db, comp, qty):
    """Pieces of `comp` in the pool, bought on a parts document."""
    doc = M.RunCostDocument(doc_type="invoice", supplier="test-alt-supplier", external_id=f"ALT-{comp.id}",
                            doc_number=f"ALT-{comp.id}", doc_date="2026-10-01", currency="USD",
                            total_amount=qty * 1.0)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", label=comp.name, component_id=comp.id,
                         mpn=comp.name, qty=qty, unit_price=1.0, currency="USD", allocate="pooled"))
    db.flush()


def _row(s, comp):
    return next(p for p in s["parts"] if p["component_id"] == comp.id)


def test_the_plan_counts_an_approved_alternate_as_the_part(db, parts, plan_world):
    _stock(db, parts.alt, 500)
    s = PL.schedule(db, plan_world.plan, TODAY)
    assert _row(s, parts.spec)["status"] == "short"
    A.add(db, parts.spec.id, parts.alt.id)
    s = PL.schedule(db, plan_world.plan, TODAY)
    r = _row(s, parts.spec)
    assert r["status"] == "ok" and r["on_hand"] == 500
    assert [a["component_id"] for a in r["alternates_on_hand"]] == [parts.alt.id]
    A.add_block(db, plan_world.proj.id, parts.spec.id, parts.alt.id)
    assert _row(PL.schedule(db, plan_world.plan, TODAY), parts.spec)["status"] == "short"


def test_the_proposal_names_the_alternate_to_buy(db, parts, plan_world):
    A.add(db, parts.spec.id, parts.alt.id, buy=True)
    s = PL.schedule(db, plan_world.plan, TODAY)
    props = [p for p in s["proposals"] if p["part_key"] == f"c{parts.spec.id}"]
    assert props and all(p["component_id"] == parts.alt.id for p in props)
    assert props[0]["instead_of"] == _row(s, parts.spec)["name"]
