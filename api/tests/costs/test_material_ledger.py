"""The material ledger's shadow equals today's figures (decision 0097, phase 1).

What these pin down:

- the rebuild projects purchases, bound, unbound and over-bound draws, priced
  and unpriced adjustments, a transformation with its conversion cost, and an
  in-house transfer, and every parity check passes over the whole database;
- a state map makes a transformation's output a lot of the other item, with
  the map's properties, and parity still passes by the pool's identity;
- the pool as one leaves a transfer out on both sides, each company's stock
  keeps it;
- a person's tracking level survives a rebuild, and a second rebuild gives
  the same ledger;
- a changed ledger row FAILS parity: the checks are not empty.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_material_ledger.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import companies as C
from app.services import run_actuals as ra
from app.services.material_ledger import parity, project, state


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


def _buy(db, comp, qty, price, day, company, n, doc_type="invoice", counterparty=None):
    doc = M.RunCostDocument(doc_type=doc_type, supplier="TESTML", doc_number=f"ML-{n}", doc_date=day,
                            currency="USD", total_amount=qty * price, company_id=company.id,
                            counterparty_company_id=counterparty.id if counterparty else None)
    db.add(doc)
    db.flush()
    li = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled", component_id=comp.id,
                       qty=qty, unit_price=price, currency="USD", position=0)
    db.add(li)
    db.flush()
    return li


def _draw(db, comp, qty, unit, day, company, run=None, **kw):
    c = M.ComponentConsumption(run_id=run.id if run else None, component_id=comp.id, qty=qty, unit_cost_usd=unit,
                               basis=kw.pop("basis", "manual"), consumed_at=day, company_id=company.id, **kw)
    db.add(c)
    db.flush()
    return c


def _bind(db, c, qty, unit, line=None, adj=None, source="fifo"):
    db.add(M.ComponentConsumptionLot(consumption_id=c.id, lot_line_id=line.id if line else None,
                                     lot_adjustment_id=adj.id if adj else None, qty=qty, unit_cost_usd=unit,
                                     source=source))
    db.flush()


def _adj(db, comp, qty, unit, day, company, **kw):
    a = M.ComponentStockAdjustment(component_id=comp.id, qty_delta=qty, unit_cost_usd=unit, adjusted_at=day,
                                   company_id=company.id, reason=kw.pop("reason", "correction"), **kw)
    db.add(a)
    db.flush()
    return a


@pytest.fixture
def world(db):
    """A box bought twice by 7Sigma, drawn bound, unbound and over-bound,
    adjusted up and down, priced and unpriced; four boxes laser cut into an
    internal part with a conversion cost, one of them drawn; three boxes
    moved to 9Sigma by an in-house transfer."""
    s7, s9 = C.by_key(db, "7sigma"), C.by_key(db, "9sigma")
    p = M.Project(name="test-material-ledger", git_url="https://example.invalid/ml.git")
    db.add(p)
    db.flush()
    box = M.Component(name="test-ml-box", in_library=False)
    cut = M.Component(name="test-ml-box cut", in_library=False, internal=True)
    db.add_all([box, cut])
    db.flush()
    run = M.ProductionRun(project_id=p.id, label="ML1", run_date="2025-03-10", qty=5, company_id=s7.id)
    db.add(run)
    db.flush()
    a = _buy(db, box, 10, 1.0, "2025-01-01", s7, 1)
    b = _buy(db, box, 10, 2.0, "2025-01-10", s7, 2)
    _adj(db, box, 5, 3.0, "2025-01-05", s7)
    _adj(db, box, 2, None, "2025-01-06", s7)
    _adj(db, box, -1, None, "2025-01-07", s7, reason="attrition")
    _adj(db, box, -1, 1.25, "2025-01-08", s7, reason="attrition")
    bound = _draw(db, box, 3, 1.2, "2025-01-12", s7, run)
    _bind(db, bound, 3, 1.0, line=a)
    _draw(db, box, 2, 1.4, "2025-01-12", s7, run)  # no lot
    over = _draw(db, box, 1, 1.5, "2025-01-13", s7, run)
    _bind(db, over, 2, 2.0, line=b)  # bound beyond its quantity
    t = M.ProcessTransformation(project_id=p.id, process_version_id=0, recipe_key="cut", recipe_label="Cut box",
                                output_component_id=cut.id, qty=4, made_at="2025-03-01", input_value_usd=4.0)
    db.add(t)
    db.flush()
    inp = _draw(db, box, 4, 1.0, "2025-03-01", s7, basis="transformation", transformation_id=t.id)
    _bind(db, inp, 4, 1.0, line=a)
    out = _adj(db, cut, 4, 1.0, "2025-03-01", s7, reason="transformation", transformation_id=t.id)
    t.output_adjustment_id = out.id
    conv = M.RunCostDocument(doc_type="invoice", supplier="TESTML", doc_number="ML-conv", doc_date="2025-03-01",
                             currency="USD", total_amount=2.0, company_id=s7.id)
    db.add(conv)
    db.flush()
    db.add(M.RunCostLine(document_id=conv.id, plan_key="final:enclosure", allocate="none", qty=1,
                         unit_price=2.0, currency="USD", transformation_id=t.id, position=0))
    use_cut = _draw(db, cut, 1, 1.5, "2025-03-05", s7, run)
    _bind(db, use_cut, 1, 1.5, adj=out, source="manual")
    tr = _buy(db, box, 3, 2.0, "2025-02-01", s9, 3, doc_type="transfer", counterparty=s7)
    send = _draw(db, box, 3, 2.0, "2025-02-01", s7, transfer_line_id=tr.id, basis="transfer")
    _bind(db, send, 3, 2.0, line=b)
    db.flush()
    return SimpleNamespace(s7=s7, s9=s9, p=p, box=box, cut=cut, run=run, a=a, b=b, t=t, out=out, tr=tr)


def _failures(r: dict) -> dict:
    """Every check that failed, with its sample, for a readable assert."""
    out = {}
    for scope, s in r["stock"].items():
        for k in ("quantity", "value", "lowest_balance"):
            if not s[k]["ok"]:
                out[f"{scope}:{k}"] = s[k]["sample"]
    if not r["lots"]["ok"]:
        out["lots"] = r["lots"]["sample"]
    for k in ("clicks", "batches", "status", "prices", "devices"):
        if not r["units"][k]["ok"]:
            out[f"units:{k}"] = r["units"][k]["sample"]
    return out


def test_every_path_projects_and_parity_holds(db, world):
    r = parity.check(db)
    assert _failures(r) == {}
    assert r["ok"]
    assert r["stock"]["pool"]["parts"] >= 2
    found = r["rebuild"]["findings"]
    assert "draws_bound_beyond_their_quantity" in found
    # The draw bound beyond its quantity is two moves: the binding and a
    # correction with no lot, together the one unit the pool takes.
    moves = db.query(M.MaterialMove).filter(M.MaterialMove.source_kind == "consumption").all()
    over = [m for m in moves if m.bind_source == "over_bound"]
    assert len(over) == 1 and over[0].qty == pytest.approx(1.0)


def test_a_transfer_is_out_of_the_pool_and_in_each_company(db, world):
    project.rebuild(db)
    key = f"c{world.box.id}"
    one = state.item_state(db, None)[key]
    s7 = state.item_state(db, world.s7.id)[key]
    s9 = state.item_state(db, world.s9.id)[key]
    assert one["qty"] == pytest.approx(ra.pool_state(db)[key]["qty"])
    assert s9["qty"] == pytest.approx(3.0)
    # 7Sigma's stock lost the three it sent; the pool as one never saw them.
    assert s7["qty"] == pytest.approx(one["qty"] - 3.0)
    ev = db.query(M.MaterialEvent).filter_by(source_kind="document", source_id=world.tr.document_id).one()
    assert ev.kind == "transfer"
    legs = db.query(M.MaterialMove).filter_by(event_id=ev.id).all()
    assert sorted(m.qty for m in legs) == [-3.0, 3.0]


def test_a_state_map_makes_the_output_a_state_of_the_item(db, world):
    db.add(M.MaterialStateMap(component_id=world.cut.id, item_component_id=world.box.id,
                              properties={"cut_top": "v1", "cut_bottom": "v1"}, decided_by="test"))
    db.flush()
    r = parity.check(db)
    assert _failures(r) == {}
    lot = db.query(M.MaterialLot).filter_by(source_kind="adjustment", source_id=world.out.id).one()
    item = db.get(M.MaterialItem, lot.item_id)
    assert item.key == f"c{world.box.id}"
    props = {p.name: p.value for p in db.query(M.MaterialProperty).filter_by(lot_id=lot.id)}
    assert props == {"cut_top": "v1", "cut_bottom": "v1"}
    ev = db.query(M.MaterialEvent).filter_by(source_kind="transformation", source_id=world.t.id).one()
    assert ev.kind == "transform"
    assert {p.event_id for p in db.query(M.MaterialProperty).filter_by(lot_id=lot.id)} == {ev.id}
    # The pool still files it under the internal part.
    moves = db.query(M.MaterialMove).filter_by(lot_id=lot.id).all()
    assert {m.pool_key for m in moves} == {f"c{world.cut.id}"}
    assert state.item_state(db)[f"c{world.cut.id}"]["qty"] == pytest.approx(3.0)


def test_the_conversion_cost_rides_on_the_output_lot(db, world):
    project.rebuild(db)
    lot = state.lot_state(db)[f"A{world.out.id}"]
    assert lot["value_bought"] == pytest.approx(4 * 1.0 + 2.0)
    assert lot["qty_remaining"] == pytest.approx(3.0)
    aim = db.query(M.MaterialCostAim).filter_by(source_kind="transformation").all()
    ev = db.query(M.MaterialEvent).filter_by(source_kind="transformation", source_id=world.t.id).one()
    assert any(a.event_id == ev.id for a in aim)


def test_a_tracking_level_survives_and_a_rebuild_is_repeatable(db, world):
    first = project.rebuild(db)
    item = db.query(M.MaterialItem).filter_by(key=f"c{world.box.id}").one()
    item.tracking = "lot"
    db.flush()
    second = project.rebuild(db)
    assert db.query(M.MaterialItem).filter_by(key=f"c{world.box.id}").one().tracking == "lot"
    for k in ("events", "lots", "moves", "event_lots", "cost_aims"):
        assert first[k] == second[k], k
    assert second["new_items"] == 0


def test_a_changed_ledger_fails_parity(db, world):
    project.rebuild(db)
    m = (db.query(M.MaterialMove)
         .filter_by(pool_key=f"c{world.box.id}", source_kind="consumption").order_by(M.MaterialMove.id).first())
    db.execute(text("UPDATE material_moves SET qty = qty - 1, value_usd = value_usd - 5 WHERE id = :i"),
               {"i": m.id})
    db.expire_all()
    r = parity.check(db, rebuild=False)
    assert not r["ok"]
    bad = _failures(r)
    assert "pool:quantity" in bad and "pool:value" in bad
    assert any(row["key"] == f"c{world.box.id}" for row in bad["pool:quantity"])
