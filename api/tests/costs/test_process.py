"""Production processes: the document check and PREPARED PARTS (decisions 0058, 0059).

What these pin down:

- the machine check a process must pass to publish (a step library with needs,
  alternative groups, one assembly / receive / program / finish step, a main route);
- a prepared-part transformation draws its inputs and deposits a lot WORTH what
  it drew, so the pool's value identity still holds and nothing is charged to
  a batch;
- a lot banked at zero value is drawn at zero (the snapshot is the price);
- a transformation cannot be voided from under a draw of its output;
- a stocktake writes off oldest first and banks a surplus;
- a conversion cost (an invoice position aimed at a transformation) lands in
  the output lot and in its own register bucket, and the register still closes.

The twins themselves are in test_twins.py.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_process.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import process as P
from app.services import run_actuals as ra


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


def _part(db, name, internal=False):
    c = M.Component(name=name, in_library=False, internal=internal)
    db.add(c)
    db.flush()
    return c


def graph_for(enc, ant, glued, carton):
    return {
        "steps": [
            {"key": "assembly", "label": "Board from the assembler", "kind": "assembly",
             "required": True},
            {"key": "receive", "label": "Receive PCBA", "kind": "receive", "required": True},
            {"key": "enclose", "label": "Fit into the glued enclosure", "kind": "step",
             "required": True, "needs": ["receive"], "inputs": [{"component_id": glued.id, "qty": 1}]},
            {"key": "program", "label": "Program", "kind": "program", "required": True,
             "needs": ["receive"]},
            {"key": "sticker", "label": "Sticker", "kind": "step", "required": True,
             "group": "branding", "needs": ["enclose"]},
            {"key": "uvprint", "label": "UV print", "kind": "step", "required": True,
             "group": "branding", "needs": ["enclose"]},
            {"key": "carton", "label": "Carton", "kind": "step", "required": True,
             "needs": ["enclose", "program"], "inputs": [{"component_id": carton.id, "qty": 1}]},
            {"key": "finish", "label": "Finished", "kind": "finish"},
        ],
        "route": ["assembly", "receive", "enclose", "program", "sticker", "carton", "finish"],
        "prepared": [
            {"key": "glue", "label": "Glue antenna into enclosure", "output_component_id": glued.id,
             "inputs": [{"component_id": enc.id, "qty": 1}, {"component_id": ant.id, "qty": 1}],
             "preferred": True},
        ],
    }


@pytest.fixture
def world(db: Session):
    """100 enclosures at $2, 100 antennas at $1 and 100 cartons at $0.5 in the
    pool from 2026-01-01; one prepared part, `glued` = enclosure + antenna."""
    proj = M.Project(name="test-process", git_url="https://example.invalid/p.git")
    db.add(proj)
    db.flush()
    enc, ant, carton = (_part(db, "test-proc-enclosure"), _part(db, "test-proc-antenna"),
                        _part(db, "test-proc-carton"))
    glued = _part(db, "test-proc-glued", internal=True)
    doc = M.RunCostDocument(project_id=proj.id, doc_type="invoice", supplier="TESTCO",
                            doc_number="P-0001", doc_date="2026-01-01", currency="USD",
                            total_amount=350.0)
    db.add(doc)
    db.flush()
    for i, (c, price) in enumerate(((enc, 2.0), (ant, 1.0), (carton, 0.5))):
        db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=c.id,
                             mpn="", lcsc="", qty=100, unit_price=price, position=i))
    db.flush()
    graph = graph_for(enc, ant, glued, carton)
    v = P.compose(db, proj.id, actor="test", graph=graph)
    P.publish(db, v, actor="test", comment="first process")
    run = M.ProductionRun(project_id=proj.id, label="PB1", run_date="2026-02-01",
                          status="completed", process_version_id=v.id)
    db.add(run)
    db.flush()
    return {"project": proj, "enc": enc, "ant": ant, "carton": carton, "glued": glued,
            "version": v, "run": run, "graph": graph}


def _pool(db, comp):
    return ra.pool_state(db).get(f"c{comp.id}", {})


# ------------------------------------------------------------------ check

def _errors(db, world, mutate):
    g = {k: [dict(x) for x in v] if isinstance(v, list) and v and isinstance(v[0], dict) else list(v)
         for k, v in world["graph"].items()}
    mutate(g)
    return " ".join(P.check(db, world["project"].id, g)["errors"])


def test_the_world_process_passes_its_check(db, world):
    res = P.check(db, world["project"].id, world["graph"])
    assert res["ok"], res


def test_check_wants_exactly_one_program_step(db, world):
    def two(g):
        g["steps"].append({"key": "program2", "kind": "program", "required": True})
    assert "exactly one 'program' step" in _errors(db, world, two)


def test_check_refuses_a_choice_with_one_option(db, world):
    def one(g):
        g["steps"] = [s for s in g["steps"] if s["key"] != "uvprint"]
    assert "a choice needs at least two" in _errors(db, world, one)


def test_check_refuses_steps_that_need_each_other(db, world):
    def circle(g):
        for s in g["steps"]:
            if s["key"] == "enclose":
                s["needs"] = ["carton"]
    assert "in a circle" in _errors(db, world, circle)


def test_check_refuses_a_step_at_the_wrong_station(db, world):
    def wrong(g):
        for s in g["steps"]:
            if s["key"] == "program":
                s["station"] = "batch"
    assert "is done at the programming bench" in _errors(db, world, wrong)


def test_publish_needs_a_comment_and_a_clean_check(db, world):
    v = P.compose(db, world["project"].id, actor="test")
    with pytest.raises(HTTPException) as e:
        P.publish(db, v, actor="test")
    assert e.value.status_code == 422
    P.update_draft(db, v, graph={"steps": [], "route": [], "prepared": []})
    with pytest.raises(HTTPException) as e:
        P.publish(db, v, actor="test", comment="broken")
    assert e.value.status_code == 422


def test_a_published_version_is_immutable(db, world):
    with pytest.raises(HTTPException) as e:
        P.update_draft(db, world["version"], comment="edit")
    assert e.value.status_code == 409


# ----------------------------------------------------------- prepared parts

def test_transformation_moves_value_into_the_output_lot(db, world):
    plan = P.transform(db, world["project"].id, recipe_key="glue", qty=10, scrap=2,
                       made_at="2026-02-01", run_id=world["run"].id, dry_run=False)
    # 12 enclosures at $2 and 12 antennas at $1 drawn for 10 good units
    assert plan["input_value_usd"] == pytest.approx(36.0)
    assert plan["output"]["unit_cost_usd"] == pytest.approx(3.6)
    glued = _pool(db, world["glued"])
    assert glued["qty"] == pytest.approx(10)
    assert glued["value_usd"] == pytest.approx(36.0)
    draws = db.query(M.ComponentConsumption).filter_by(transformation_id=plan["transformation_id"]).all()
    assert draws and all(d.run_id is None for d in draws)
    pool = ra.pool_state(db)
    assert abs(sum(p["value_bought"] + p["value_adj"] - p["value_used"] - p["value_usd"]
                   for p in pool.values())) <= 0.5


def test_a_dry_run_writes_nothing(db, world):
    before = db.query(M.ComponentConsumption).count()
    P.transform(db, world["project"].id, recipe_key="glue", qty=5, made_at="2026-02-01")
    assert db.query(M.ComponentConsumption).count() == before


def test_a_shortage_refuses_the_write(db, world):
    with pytest.raises(HTTPException) as e:
        P.transform(db, world["project"].id, recipe_key="glue", qty=150,
                    made_at="2026-02-01", dry_run=False)
    assert e.value.status_code == 409


def test_a_zero_value_lot_is_drawn_at_zero(db, world):
    """The snapshot is the price, including 0: `pool_state` used to read a 0.0
    snapshot as unknown and charge the moving average instead."""
    pid = world["project"].id
    P.bank(db, pid, component_id=world["glued"].id, qty=2, at="2026-01-10", note="found",
           dry_run=False)
    P.transform(db, pid, recipe_key="glue", qty=1, made_at="2026-02-01", dry_run=False)
    lot0 = P.prepared_lots(db, {world["glued"].id})[0]
    P.write_off(db, pid, lot_adjustment_id=lot0["adjustment_id"], qty=1, at="2026-02-03",
                note="broke", dry_run=False)
    p = _pool(db, world["glued"])
    assert p["qty"] == pytest.approx(2)
    assert p["value_usd"] == pytest.approx(3.0)


def test_void_removes_the_output_and_returns_the_inputs(db, world):
    pid = world["project"].id
    plan = P.transform(db, pid, recipe_key="glue", qty=2, made_at="2026-02-01", dry_run=False)
    t = db.get(M.ProcessTransformation, plan["transformation_id"])
    P.void_transformation(db, t, reason="entered twice", actor="test")
    assert _pool(db, world["glued"]).get("qty", 0) == pytest.approx(0)
    assert _pool(db, world["enc"])["qty"] == pytest.approx(100)
    assert db.get(M.ComponentStockAdjustment, plan["output"]["lot_adjustment_id"]) is None


def test_void_is_refused_once_the_output_was_drawn(db, world):
    pid = world["project"].id
    plan = P.transform(db, pid, recipe_key="glue", qty=2, made_at="2026-02-01", dry_run=False)
    P.write_off(db, pid, lot_adjustment_id=plan["output"]["lot_adjustment_id"], qty=1,
                at="2026-02-02", note="broke", dry_run=False)
    t = db.get(M.ProcessTransformation, plan["transformation_id"])
    with pytest.raises(HTTPException) as e:
        P.void_transformation(db, t, reason="typo", actor="test")
    assert e.value.status_code == 409


def test_a_stocktake_writes_off_oldest_first_and_banks_a_surplus(db, world):
    pid, glued = world["project"].id, world["glued"]
    P.bank(db, pid, component_id=glued.id, qty=2, at="2026-01-10", note="a", dry_run=False)
    P.transform(db, pid, recipe_key="glue", qty=3, made_at="2026-02-01", dry_run=False)
    res = P.stocktake(db, pid, component_id=glued.id, counted=4, at="2026-02-10",
                      note="counted by hand", dry_run=False)
    assert res["delta"] == pytest.approx(-1)
    assert [lt["remaining"] for lt in P.prepared_lots(db, {glued.id})] == [1, 3]
    res = P.stocktake(db, pid, component_id=glued.id, counted=6, at="2026-02-11",
                      note="found two more", dry_run=False)
    assert res["delta"] == pytest.approx(2)
    assert sum(lt["remaining"] for lt in P.prepared_lots(db, {glued.id})) == pytest.approx(6)


# ------------------------------------------------------- conversion costs

def _service_invoice(db, world, amount, currency="USD", fx=None):
    doc = M.RunCostDocument(project_id=world["project"].id, doc_type="invoice",
                            supplier="TEST-PRINT", doc_number="UV-1", doc_date="2026-02-02",
                            currency=currency, fx_rate_usd=fx, total_amount=amount)
    db.add(doc)
    db.flush()
    return doc


def test_a_conversion_cost_lands_in_the_output_lot(db, world):
    pid = world["project"].id
    plan = P.transform(db, pid, recipe_key="glue", qty=10, made_at="2026-02-01", dry_run=False)
    doc = _service_invoice(db, world, 40.0, currency="PLN", fx=0.25)
    db.add(M.RunCostLine(document_id=doc.id, plan_key="final:enclosure_print", qty=1,
                         unit_price=40.0, transformation_id=plan["transformation_id"]))
    db.flush()
    # 30 of inputs + 40 PLN at 0.25 = 10 of conversion
    assert _pool(db, world["glued"])["value_usd"] == pytest.approx(40.0)
    lot = P.prepared_lots(db, {world["glued"].id})[0]
    assert lot["unit_cost_usd"] == pytest.approx(4.0)
    assert lot["conversion_usd"] == pytest.approx(10.0)
    j = ra.document_json(doc, db=db)
    assert j["assignment"]["transformation"] == pytest.approx(40.0)
    assert j["assignment"]["unassigned"] == pytest.approx(0.0)
    assert ra.invoice_register(db)["summary"]["gap_usd"] == pytest.approx(0.0, abs=0.0005)


def test_a_conversion_cost_is_refused_on_a_stock_step_and_with_a_batch(db, world):
    from app.routers.run_costs import _check_transformation

    plan = P.transform(db, world["project"].id, recipe_key="glue", qty=1, made_at="2026-02-01",
                       dry_run=False)
    tid = plan["transformation_id"]
    with pytest.raises(HTTPException):
        _check_transformation(db, "parts:pool", tid, None, None, "none")
    with pytest.raises(HTTPException):
        _check_transformation(db, "final:enclosure_print", tid, world["run"].id, None, "none")
    _check_transformation(db, "final:enclosure_print", tid, None, None, "none")


def test_moving_a_position_to_a_batch_takes_it_off_the_transformation(db, world):
    from app.routers.run_costs import _one_destination

    assert _one_destination({"run_id": 5})["transformation_id"] is None
    f = _one_destination({"transformation_id": 7, "run_id": 5, "allocate": "by_value"})
    assert (f["run_id"], f["allocate"]) == (None, "none")


def test_a_transformation_with_a_conversion_cost_cannot_be_voided(db, world):
    plan = P.transform(db, world["project"].id, recipe_key="glue", qty=1, made_at="2026-02-01",
                       dry_run=False)
    doc = _service_invoice(db, world, 1.0)
    db.add(M.RunCostLine(document_id=doc.id, plan_key="final:enclosure_print", qty=1,
                         unit_price=1.0, transformation_id=plan["transformation_id"]))
    db.flush()
    t = db.get(M.ProcessTransformation, plan["transformation_id"])
    with pytest.raises(HTTPException) as e:
        P.void_transformation(db, t, reason="x", actor="test")
    assert e.value.status_code == 409
