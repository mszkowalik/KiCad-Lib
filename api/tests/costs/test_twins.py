"""Twins: crafting a batch step by step, and each device's price (decision 0059).

What these pin down:

- receiving makes one twin per board, in one stack; a step on a stack draws
  N x each input, charged to the batch, and the stack's key moves on;
- a step whose needs are not met is refused, and a choice allows one option;
- a stack is one physical pile: units enclosed from two lots are two stacks;
- the bench names a twin from the selected stack, never invents one, and a
  device programmed with no stack is a gap until a merge;
- the marking bench records its steps; finish refuses a missing required step,
  and a shipment refuses an unfinished device;
- a twin's price is its own parts plus an equal share of its origin batch
  cost; scrapped twins are carried; a twin programmed in another batch keeps
  its origin share; found units enter at zero; a crafted batch draws no BOM;
- the board's assembly is a step recorded from the batch's assembly order
  (decision 0060): receiving the boards links the order's measured draws and
  every board and assembly position to it, a position imported later joins
  it, any other position can be linked to the click it paid for, and the
  twins' prices still add up to the batch's total.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_twins.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import orders as osvc
from app.services import process as P
from app.services import run_actuals as ra
from app.services import twins as T
from app.services.flasher import bench_checks


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


@pytest.fixture
def world(db: Session):
    """A crafted product: assembly → receive → enclose (prepared part `glued`)
    → program → laser mark + label → sticker OR UV print → carton (→ optional
    leaflet) → finish. Two batches, B1 and B2; B1 has an assembly invoice of
    $100 and a freight position of $20."""
    proj = M.Project(name="test-twins", git_url="https://example.invalid/t.git")
    db.add(proj)
    db.flush()
    enc, ant, carton, sticker, leaflet = (_part(db, f"test-twin-{n}") for n in
                                          ("enclosure", "antenna", "carton", "sticker", "leaflet"))
    glued = _part(db, "test-twin-glued", internal=True)
    doc = M.RunCostDocument(project_id=proj.id, doc_type="invoice", supplier="TESTCO",
                            doc_number="T-0001", doc_date="2026-01-01", currency="USD",
                            total_amount=600.0)
    db.add(doc)
    db.flush()
    for i, (c, price) in enumerate(((enc, 2.0), (ant, 1.0), (sticker, 0.2), (leaflet, 0.1))):
        db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=c.id,
                             mpn="", lcsc="", qty=100, unit_price=price, position=i))
    # The carton is no library part: its purchases are keyed by MPN alone, as
    # the real shipping cartons are.
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=None,
                         mpn="TEST-TWIN-KARTON", lcsc="", qty=100, unit_price=0.5, position=9))
    graph = {
        "steps": [
            {"key": "assembly", "label": "Board from the assembler", "kind": "assembly",
             "required": True},
            {"key": "receive", "label": "Receive PCBA", "kind": "receive", "required": True},
            {"key": "enclose", "label": "Enclose", "kind": "step", "required": True,
             "needs": ["receive"], "inputs": [{"component_id": glued.id, "qty": 1}]},
            {"key": "program", "label": "Program", "kind": "program", "required": True,
             "needs": ["receive"]},
            {"key": "laser", "label": "Laser mark", "kind": "mark_laser", "required": True,
             "needs": ["enclose", "program"]},
            {"key": "label", "label": "Barcode label", "kind": "label", "required": True,
             "needs": ["program"]},
            {"key": "sticker", "label": "Sticker", "kind": "step", "required": True,
             "group": "branding", "needs": ["enclose"], "inputs": [{"component_id": sticker.id, "qty": 1}]},
            {"key": "uvprint", "label": "UV print", "kind": "step", "required": True,
             "group": "branding", "needs": ["enclose"]},
            {"key": "leaflet", "label": "Leaflet", "kind": "step", "required": False,
             "needs": ["program"], "inputs": [{"component_id": leaflet.id, "qty": 1}]},
            {"key": "carton", "label": "Carton", "kind": "step", "required": True,
             "needs": ["enclose", "program"], "inputs": [{"mpn": "TEST-TWIN-KARTON", "qty": 1}]},
            {"key": "finish", "label": "Finished", "kind": "finish"},
        ],
        "route": ["assembly", "receive", "enclose", "program", "laser", "label", "sticker", "carton",
                  "finish"],
        "prepared": [{"key": "glue", "label": "Glue", "output_component_id": glued.id,
                      "inputs": [{"component_id": enc.id, "qty": 1}, {"component_id": ant.id, "qty": 1}]}],
    }
    v = P.compose(db, proj.id, actor="test", graph=graph)
    P.publish(db, v, actor="test", comment="crafted product")
    b1 = M.ProductionRun(project_id=proj.id, label="TB1", run_date="2026-02-01",
                         status="completed", process_version_id=v.id, qty=10)
    b2 = M.ProductionRun(project_id=proj.id, label="TB2", run_date="2026-03-01",
                         status="completed", process_version_id=v.id, qty=10)
    db.add_all([b1, b2])
    db.flush()
    inv = M.RunCostDocument(project_id=proj.id, run_id=b1.id, doc_type="invoice", supplier="ASSY",
                            doc_number="A-1", doc_date="2026-02-01", currency="USD", total_amount=120.0)
    db.add(inv)
    db.flush()
    db.add(M.RunCostLine(document_id=inv.id, plan_key="pcba:smt", qty=1, unit_price=100.0,
                         run_id=b1.id, label="SMT assembly"))
    db.add(M.RunCostLine(document_id=inv.id, plan_key="logistics:inbound", qty=1, unit_price=20.0,
                         run_id=b1.id, label="Freight", position=1))
    db.flush()
    P.transform(db, proj.id, recipe_key="glue", qty=20, made_at="2026-01-15", dry_run=False)
    return {"project": proj, "v": v, "b1": b1, "b2": b2, "glued": glued, "carton": carton,
            "sticker": sticker, "leaflet": leaflet}


def _stack(db, world, run, done):
    key = "|".join(sorted(done))
    for s in T.stacks(db, world["project"].id, run_id=run.id):
        if set(s["done"]) == set(done):
            return s["stack"]
    raise AssertionError(f"no stack {key} in {T.stacks(db, world['project'].id, run_id=run.id)}")


def _device(db, world, n):
    d = M.DeviceUnit(project_id=world["project"].id, serial=f"TW{n:04d}",
                     mac=f"00:00:00:00:tw:{n:02d}", first_seen=datetime(2026, 2, 5, 10, tzinfo=UTC))
    db.add(d)
    db.flush()
    return d


def _program(db, world, batch, n):
    """What the bench engine does on a pass: a new produced event, then naming."""
    d = _device(db, world, n)
    ev = osvc.mark_produced(db, d, batch.id, actor="test")
    db.flush()
    return d, T.name_at_bench(db, d, ev, batch)


def _received(db, world, n=10):
    T.receive(db, world["b1"], qty=n, made_at="2026-02-01", dry_run=False)
    return _stack(db, world, world["b1"], {"assembly", "receive"})


# --------------------------------------------------------------- crafting

def test_receiving_makes_one_twin_per_board_in_one_stack(db, world):
    T.receive(db, world["b1"], qty=10, dry_run=True)
    assert db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).count() == 0
    stack = _received(db, world)
    assert [s["count"] for s in T.stacks(db, world["project"].id, run_id=world["b1"].id)] == [10]
    assert stack.endswith(":assembly|receive")


def test_a_step_on_a_stack_draws_its_parts_charged_to_the_batch(db, world):
    stack = _received(db, world)
    plan = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=4,
                        made_at="2026-02-02", dry_run=False)
    assert plan["units"] == 4
    # 4 glued enclosures from the $3 lot
    assert plan["value_usd"] == pytest.approx(12.0)
    draws = db.query(M.ComponentConsumption).filter_by(step_run_id=plan["step_run_id"]).all()
    assert [(d.qty, d.run_id) for d in draws] == [(4, world["b1"].id)]
    counts = sorted(s["count"] for s in T.stacks(db, world["project"].id, run_id=world["b1"].id))
    assert counts == [4, 6]


def test_a_step_whose_needs_are_not_met_is_refused(db, world):
    stack = _received(db, world)
    plan = T.apply_step(db, world["b1"], step_key="carton", stack=stack, qty=2)
    assert plan["refused"] and "needs 'Enclose'" in plan["refused"][0]["why"]
    with pytest.raises(HTTPException) as e:
        T.apply_step(db, world["b1"], step_key="carton", stack=stack, qty=2, dry_run=False)
    assert e.value.status_code == 409


def test_programming_is_not_a_batch_screen_step(db, world):
    stack = _received(db, world)
    with pytest.raises(HTTPException) as e:
        T.apply_step(db, world["b1"], step_key="program", stack=stack, qty=1)
    assert "programming bench" in str(e.value.detail)


def test_a_stack_is_one_pile_so_two_lots_make_two_stacks(db, world):
    pid = world["project"].id
    P.transform(db, pid, recipe_key="glue", qty=5, made_at="2026-01-20", dry_run=False)
    lots = P.prepared_lots(db, {world["glued"].id}, open_only=True)
    stack = _received(db, world)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=3,
                 lots={str(world["glued"].id): lots[0]["adjustment_id"]}, dry_run=False)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=3,
                 lots={str(world["glued"].id): lots[1]["adjustment_id"]}, dry_run=False)
    enclosed = [s for s in T.stacks(db, pid, run_id=world["b1"].id) if "enclose" in s["done"]]
    assert sorted(s["count"] for s in enclosed) == [3, 3]
    assert len({s["stack"] for s in enclosed}) == 2


# ------------------------------------------------------------------ bench

def test_the_bench_names_a_twin_from_the_selected_stack(db, world):
    stack = _received(db, world, 3)
    T.set_bench_stack(db, world["b1"], stack)
    d, tw = _program(db, world, world["b1"], 1)
    assert tw is not None and tw.device_unit_id == d.id
    assert T.bench_stack_left(db, world["b1"]) == 2


def test_no_stack_means_a_gap_and_a_merge_closes_it(db, world):
    stack = _received(db, world, 2)
    d, tw = _program(db, world, world["b1"], 2)
    assert tw is None
    assert [g.id for g in T.gaps(db, world["b1"])] == [d.id]
    T.merge(db, world["b1"], stack=stack, device_ids=[d.id], chosen="list", dry_run=False)
    assert T.gaps(db, world["b1"]) == []
    assert db.query(M.Twin).filter_by(device_unit_id=d.id).one().origin_run_id == world["b1"].id


def test_the_bench_warns_when_the_stack_is_used_up(db, world):
    stack = _received(db, world, 1)
    T.set_bench_stack(db, world["b1"], stack)
    _program(db, world, world["b1"], 3)
    codes = [n["code"] for n in bench_checks._about_the_batch(db, world["b1"], _device(db, world, 4),
                                                              created=True)]
    assert "stack_empty" in codes


def test_only_a_stack_ready_for_programming_can_be_selected(db, world):
    _received(db, world, 1)
    with pytest.raises(HTTPException):
        T.set_bench_stack(db, world["b1"], f"{world['b1'].id}:nonsense")


# ------------------------------------------------- marking, choices, finish

def _crafted_device(db, world, n=1):
    stack = _received(db, world, 1)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=1, dry_run=False)
    T.set_bench_stack(db, world["b1"], _stack(db, world, world["b1"], {"assembly", "receive", "enclose"}))
    d, tw = _program(db, world, world["b1"], n)
    return d, tw


def test_the_marking_bench_records_its_steps(db, world):
    d, tw = _crafted_device(db, world, 5)
    assert T.record_marking(db, d, laser=True, label=True) == ["laser", "label"]
    assert {"laser", "label"} <= T.done_steps(db, [tw.id])[tw.id]


def test_a_choice_allows_one_option(db, world):
    d, _tw = _crafted_device(db, world, 6)
    T.apply_step(db, world["b1"], step_key="sticker", device_ids=[d.id], chosen="scanned", dry_run=False)
    plan = T.apply_step(db, world["b1"], step_key="uvprint", device_ids=[d.id], chosen="scanned")
    assert plan["refused"] and "another option of 'branding'" in plan["refused"][0]["why"][0]


def test_finish_refuses_a_missing_required_step_and_shipping_waits_for_it(db, world):
    d, _tw = _crafted_device(db, world, 7)
    plan = T.finish(db, world["b1"], device_ids=[d.id], chosen="scanned")
    missing = " ".join(plan["refused"][0]["why"])
    assert "Laser mark" in missing and "Carton" in missing
    assert "one of 'Sticker' / 'UV print'" in missing
    with pytest.raises(HTTPException):
        T.refuse_unfinished(db, d)
    T.record_marking(db, d, laser=True, label=True)
    for step in ("uvprint", "carton"):
        T.apply_step(db, world["b1"], step_key=step, device_ids=[d.id], chosen="list", dry_run=False)
    T.finish(db, world["b1"], device_ids=[d.id], chosen="scanned", dry_run=False)
    T.refuse_unfinished(db, d)  # finished: ships
    assert db.query(M.Twin).filter_by(device_unit_id=d.id).one().status == "finished"


# ------------------------------------------------------------------ prices

def test_a_twin_costs_its_own_parts_plus_its_origin_share(db, world):
    stack = _received(db, world, 10)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=10, dry_run=False)
    twins = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).all()
    pr = T.prices(db, twins)
    # own: one $3 glued enclosure, and 1/10 of the $100 assembly the step
    # recorded; origin: the $20 freight over 10 twins
    assert {p["own_parts_usd"] for p in pr.values()} == {3.0}
    assert {p["step_costs_usd"] for p in pr.values()} == {10.0}
    assert {p["origin_share_usd"] for p in pr.values()} == {2.0}
    sh = T.origin_shares(db, [world["b1"].id])[world["b1"].id]
    assert sh["origin_cost_usd"] == pytest.approx(20.0)


def test_scrapped_twins_are_carried_by_the_others(db, world):
    stack = _received(db, world, 10)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=10, dry_run=False)
    enclosed = _stack(db, world, world["b1"], {"assembly", "receive", "enclose"})
    T.scrap(db, world["b1"], stack=enclosed, qty=2, reason="cracked", dry_run=False)
    sh = T.origin_shares(db, [world["b1"].id])[world["b1"].id]
    # ($20 freight + 2 x ($3 parts + $10 assembly) of the scrapped) over the 8 left
    assert sh["share_usd"] == pytest.approx(46.0 / 8)
    alive = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id, status="active").all()
    total = sum(p["total_usd"] for p in T.prices(db, alive).values())
    assert total == pytest.approx(150.0, abs=0.01)  # $100 + $20 + 10 x $3: nothing lost


def test_a_twin_programmed_in_another_batch_keeps_its_origin(db, world):
    stack = _received(db, world, 2)
    T.set_bench_stack(db, world["b2"], stack)
    d, tw = _program(db, world, world["b2"], 8)
    assert (tw.origin_run_id, tw.run_id) == (world["b1"].id, world["b2"].id)
    assert d.production_run_id == world["b2"].id
    T.apply_step(db, world["b2"], step_key="leaflet", device_ids=[d.id], chosen="scanned", dry_run=False)
    p = T.prices(db, [tw])[tw.id]
    assert p["origin_share_usd"] == pytest.approx(10.0)  # B1's $20 freight over its 2 twins
    assert p["step_costs_usd"] == pytest.approx(50.0)    # B1's $100 assembly, 1/2
    assert p["own_parts_usd"] == pytest.approx(0.1)     # the leaflet, drawn in B2
    # B2's origin cost does not include a step draw that belongs to a twin
    assert T.origin_shares(db, [world["b2"].id])[world["b2"].id]["origin_cost_usd"] == pytest.approx(0.0)


def test_found_units_enter_at_zero(db, world):
    T.enter_found(db, world["b2"], qty=3, done=["enclose"], origin_run_id=world["b1"].id,
                  note="stock count", dry_run=False)
    found = db.query(M.Twin).filter_by(found=True, project_id=world["project"].id).all()
    assert len(found) == 3
    assert all(p["total_usd"] == 0.0 for p in T.prices(db, found).values())
    st = _stack(db, world, world["b2"], {"assembly", "receive", "enclose"})
    assert st.startswith(f"{world['b2'].id}:")


def test_a_crafted_batch_draws_no_bom(db, world):
    res = ra.consume_from_bom(db, world["b1"])
    assert res["created"] == 0 and "crafted" in res["error"]


def test_twin_history_reads_in_the_words_of_the_step(db, world):
    _d, tw = _crafted_device(db, world, 9)
    j = T.twin_json(db, tw)
    assert [s["step"] for s in j["steps"]] == ["assembly", "receive", "enclose", "program"]
    enclose = j["steps"][2]
    assert enclose["parts"][0]["lot"].startswith("A") and enclose["parts_usd"] == pytest.approx(3.0)


def test_a_part_named_by_mpn_is_drawn_from_its_pool_key(db, world):
    d, tw = _crafted_device(db, world, 10)
    plan = T.apply_step(db, world["b1"], step_key="carton", device_ids=[d.id], chosen="scanned",
                        dry_run=False)
    c = db.query(M.ComponentConsumption).filter_by(step_run_id=plan["step_run_id"]).one()
    assert (c.component_id, c.mpn, c.unit_cost_usd) == (None, "TEST-TWIN-KARTON", pytest.approx(0.5))
    assert T.twin_json(db, tw)["steps"][-1]["parts"][0]["name"] == "TEST-TWIN-KARTON"


# ------------------------------------------------- the assembly step (0060)

def _line(db, world, run, plan_key, amount, label):
    doc = M.RunCostDocument(project_id=world["project"].id, run_id=run.id, doc_type="invoice",
                            supplier="LATER", doc_number=f"L-{label}", doc_date="2026-02-10",
                            currency="USD", total_amount=amount)
    db.add(doc)
    db.flush()
    li = M.RunCostLine(document_id=doc.id, plan_key=plan_key, qty=1, unit_price=amount, label=label)
    db.add(li)
    db.flush()
    return li


def test_receiving_records_the_assembly_from_the_order(db, world):
    measured = M.ComponentConsumption(run_id=world["b1"].id, component_id=world["sticker"].id, mpn="",
                                      lcsc="", qty=10, unit_cost_usd=0.2, basis="measured",
                                      consumed_at="2026-01-30", import_ref="jlc:test:SMT-T:x")
    db.add(measured)
    db.flush()
    plan = T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    a = plan["assembly"]
    assert (a["status"], a["units"], a["lines_linked"], a["draws_linked"]) == ("recorded", 10, 1, 1)
    sr = T.assembly_click(db, world["b1"])
    assert measured.step_run_id == sr.id
    freight = db.query(M.RunCostLine).filter_by(label="Freight").one()
    # freight is batch overhead: no step paid for it
    assert db.query(M.CostLineStep).filter_by(line_id=freight.id).count() == 0
    tw = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).first()
    p = T.prices(db, [tw])[tw.id]
    assert (p["own_parts_usd"], p["step_costs_usd"], p["origin_share_usd"]) == (0.2, 10.0, 2.0)


def test_a_position_imported_after_receipt_joins_the_assembly(db, world):
    T.receive(db, world["b1"], qty=5, dry_run=False)
    _line(db, world, world["b1"], "fab:pcb", 50.0, "bare boards")
    res = T.record_assembly(db, world["b1"])
    assert (res["status"], res["lines_linked"], res["twins_added"]) == ("extended", 1, 0)
    tw = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).first()
    assert T.prices(db, [tw])[tw.id]["step_costs_usd"] == pytest.approx(30.0)  # $150 / 5


def test_twins_received_later_join_the_same_assembly_click(db, world):
    T.receive(db, world["b1"], qty=4, dry_run=False)
    T.receive(db, world["b1"], qty=6, dry_run=False)
    clicks = db.query(M.StepRun).filter_by(run_id=world["b1"].id, kind="assembly").all()
    assert [c.qty for c in clicks] == [10]
    twins = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).all()
    assert {p["step_costs_usd"] for p in T.prices(db, twins).values()} == {10.0}


def test_a_position_can_be_linked_to_the_step_it_paid_for(db, world):
    stack = _received(db, world, 10)
    plan = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=10, dry_run=False)
    assy = _line(db, world, world["b1"], "final:device", 30.0, "device assembly")
    T.link_costs(db, world["b1"], step_run_ids=[plan["step_run_id"]], line_ids=[assy.id], dry_run=False)
    twins = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).all()
    pr = T.prices(db, twins)
    assert {p["step_costs_usd"] for p in pr.values()} == {13.0}  # $100 / 10 + $30 / 10
    assert {p["origin_share_usd"] for p in pr.values()} == {2.0}
    total = ra.invoice_register(db)["by_run_usd"][str(world["b1"].id)]["total_usd"]
    assert sum(p["total_usd"] for p in pr.values()) == pytest.approx(total, abs=0.01)
    T.link_costs(db, world["b1"], step_run_ids=None, line_ids=[assy.id], unlink=True, dry_run=False)
    assert {p["origin_share_usd"] for p in T.prices(db, twins).values()} == {5.0}


def test_a_position_charged_to_another_batch_cannot_be_linked(db, world):
    stack = _received(db, world, 2)
    plan = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=2, dry_run=False)
    other = _line(db, world, world["b2"], "final:device", 30.0, "B2 assembly")
    res = T.link_costs(db, world["b1"], step_run_ids=[plan["step_run_id"]], line_ids=[other.id])
    assert res["refused"] and "not charged to this batch" in res["refused"][0]["why"]
    with pytest.raises(HTTPException):
        T.link_costs(db, world["b1"], step_run_ids=[plan["step_run_id"]], line_ids=[other.id],
                     dry_run=False)


def test_a_closed_batch_refuses_new_links(db, world):
    stack = _received(db, world, 2)
    plan = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=2, dry_run=False)
    li = _line(db, world, world["b1"], "final:device", 30.0, "late")
    world["b1"].closed_at = datetime(2026, 3, 1, tzinfo=UTC)
    with pytest.raises(HTTPException) as e:
        T.link_costs(db, world["b1"], step_run_ids=[plan["step_run_id"]], line_ids=[li.id], dry_run=False)
    assert e.value.status_code == 409


def test_the_twin_shows_the_fees_its_assembly_carries(db, world):
    _d, tw = _crafted_device(db, world, 11)
    assembly = T.twin_json(db, tw)["steps"][0]
    assert assembly["kind"] == "assembly"
    assert [(c["label"], c["usd"]) for c in assembly["costs"]] == [("SMT assembly", 100.0)]
    assert assembly["costs_usd"] == pytest.approx(100.0)


def test_a_process_needs_one_assembly_step_without_parts(db, world):
    g = P._graph(world["v"])
    g["steps"] = [s for s in g["steps"] if s["kind"] != "assembly"]
    g["route"] = [k for k in g["route"] if k != "assembly"]
    assert any("exactly one 'assembly'" in e for e in P.check(db, world["project"].id, g)["errors"])
    g = P._graph(world["v"])
    g["steps"][0]["inputs"] = [{"component_id": world["sticker"].id, "qty": 1}]
    assert any("assembly order" in e for e in P.check(db, world["project"].id, g)["errors"])


# ------------------------------------------- rebuilding an old batch (0060)

def _legacy_batch(db, world, n_devices=4, run_date="2025-01-10", first=40):
    """A batch made before twins: devices with produced events, a JLC-style
    measured draw, a BOM draw of the carton, an assembly invoice, a final
    assembler's invoice and freight."""
    from app.services import twin_rebuild  # noqa: F401  (imported where used)

    run = M.ProductionRun(project_id=world["project"].id, label="TB0", run_date=run_date,
                          status="completed", qty=n_devices)
    db.add(run)
    db.flush()
    devices = []
    for i in range(n_devices):
        d = _device(db, world, first + i)
        osvc.mark_produced(db, d, run.id, actor="test")
        devices.append(d)
    db.flush()
    db.add(M.ComponentConsumption(run_id=run.id, component_id=world["sticker"].id, mpn="", lcsc="",
                                  qty=n_devices, unit_cost_usd=0.2, basis="measured",
                                  consumed_at="2025-01-05", import_ref=f"jlc:test:SMT-OLD{first}:x"))
    db.add(M.ComponentConsumption(run_id=run.id, component_id=None, mpn="TEST-TWIN-KARTON", lcsc="",
                                  qty=n_devices, unit_cost_usd=0.5, basis="bom",
                                  consumed_at="2025-01-10"))
    doc = M.RunCostDocument(project_id=world["project"].id, run_id=run.id, doc_type="invoice",
                            supplier="ASSY", doc_number=f"OLD-{first}", doc_date="2025-01-08", currency="USD",
                            total_amount=70.0)
    db.add(doc)
    db.flush()
    for i, (key, amount, label) in enumerate((("pcba:populated", 40.0, "populated boards"),
                                               ("final:device", 20.0, "device assembly"),
                                               ("logistics:inbound", 10.0, "freight"))):
        db.add(M.RunCostLine(document_id=doc.id, plan_key=key, qty=1, unit_price=amount, label=label,
                             position=i))
    db.flush()
    return run, devices


def test_an_old_batch_is_rebuilt_into_twins_from_its_records(db, world):
    from app.services import twin_rebuild as R

    run, devices = _legacy_batch(db, world)
    devices[3].state = "disposed"
    before = ra.invoice_register(db)["by_run_usd"][str(run.id)]["total_usd"]
    dry = R.rebuild(db, run, version_id=world["v"].id, costs={"final:device": "carton"})
    assert dry["dry_run"] and db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    plan = R.rebuild(db, run, version_id=world["v"].id, costs={"final:device": "carton"}, dry_run=False)
    assert (plan["named"], plan["finished"], plan["scrapped"]) == (4, 3, 1)
    assert plan["carried_usd"] == pytest.approx(before, abs=0.01)
    steps = {r["step"]: r["evidence"] for r in plan["recorded"]}
    assert steps["assembly"] == "invoices" and steps["carton"] == "draws"
    assert steps["program"] == "produced events"
    assert {r["step"] for r in plan["not_recorded"]} >= {"laser", "label", "enclose"}
    assert "laser" in plan["finish_lacks"]
    assert [x["plan_key"] for x in plan["left_in_origin"]["lines"]] == ["logistics:inbound"]
    # every surviving device carries a third of the batch: nothing moved
    alive = db.query(M.Twin).filter(M.Twin.origin_run_id == run.id, M.Twin.status != "scrapped").all()
    pr = T.prices(db, alive)
    assert sum(p["total_usd"] for p in pr.values()) == pytest.approx(before, abs=0.01)
    assert all(p["total_usd"] == pytest.approx(before / 3, abs=0.001) for p in pr.values())
    # the device cost orders use now comes from the twin
    assert T.device_costs(db)[devices[0].id] == pytest.approx(before / 3, abs=0.001)


def test_a_rebuild_takes_spares_and_can_be_undone(db, world):
    from app.services import twin_rebuild as R

    run, _devices = _legacy_batch(db, world, 2)
    plan = R.rebuild(db, run, version_id=world["v"].id,
                     spares=[{"qty": 2, "done": [], "note": "bare boards on the shelf"}], dry_run=False)
    assert (plan["named"], plan["spares"]) == (2, 2)
    stacks = T.stacks(db, world["project"].id, run_id=run.id)
    assert [(s["count"], s["done"]) for s in stacks] == [(2, ["assembly", "receive"])]
    with pytest.raises(HTTPException):
        R.rebuild(db, run, version_id=world["v"].id, dry_run=False)
    R.undo(db, run, dry_run=False)
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    assert run.process_version_id is None
    assert db.query(M.ComponentConsumption).filter(M.ComponentConsumption.run_id == run.id,
                                                   M.ComponentConsumption.step_run_id.isnot(None)).count() == 0


# ------------------------------------------ deployments name bench steps (0060)

def _deployment(db, world, name, kind):
    d = M.Deployment(project_id=world["project"].id, name=name, kind=kind)
    db.add(d)
    db.flush()
    return d


def test_a_bench_step_names_a_deployment_of_its_kind(db, world):
    mark = _deployment(db, world, "test-mark", "mark")
    flash = _deployment(db, world, "test-flash", "flash")
    g = P._graph(world["v"])
    smap = P.step_map(g)
    smap["program"]["deployment_id"] = mark.id
    errors = P.check(db, world["project"].id, g)["errors"]
    assert any("'flash' deployment" in e for e in errors)
    smap["program"]["deployment_id"] = flash.id
    smap["laser"]["deployment_id"] = mark.id
    chk = P.check(db, world["project"].id, g)
    assert not chk["errors"]
    assert any("'Barcode label' names no deployment" in w for w in chk["warnings"])
    smap["enclose"]["deployment_id"] = mark.id
    assert any("only a bench step" in e for e in P.check(db, world["project"].id, g)["errors"])


def test_marking_records_the_step_of_the_run_deployment(db, world):
    mark = _deployment(db, world, "test-mark-a", "mark")
    other = _deployment(db, world, "test-mark-b", "mark")
    g = P._graph(world["v"])
    P.step_map(g)["label"]["deployment_id"] = other.id
    v2 = P.compose(db, world["project"].id, actor="test", graph=g)
    P.publish(db, v2, actor="test", comment="label names its procedure")
    world["b1"].process_version_id = v2.id
    d, _tw = _crafted_device(db, world, 12)
    # this run is procedure A: the label step names B, so only the laser step is A's
    assert T.record_marking(db, d, laser=True, label=True, deployment_id=mark.id) == ["laser"]
    assert T.record_marking(db, d, laser=False, label=True, deployment_id=other.id) == ["label"]


def test_the_marking_bench_warns_when_the_unit_is_not_ready(db, world):
    stack = _received(db, world, 1)
    T.set_bench_stack(db, world["b1"], stack)
    d, _tw = _program(db, world, world["b1"], 13)  # programmed, never enclosed
    run = M.ProgrammingRun(device_unit_id=d.id, status="running")
    found = bench_checks._about_the_process(db, run, d, {"mark_laser", "print_label"})
    assert [(n["code"], n["data"]["step"]) for n in found] == [("process_needs", "laser")]
    assert "needs 'Enclose'" in found[0]["text"]
    assert bench_checks._about_the_process(db, run, d, {"print_label"}) == []


# ---------------------------------- materials come only from steps (0060)

def test_a_crafted_batch_takes_no_hand_made_draw(db, world):
    from app.routers import run_costs as rc

    with pytest.raises(HTTPException) as e:
        rc._refuse_crafted(world["b1"])
    assert e.value.status_code == 409 and "process steps" in str(e.value.detail)
    stack = _received(db, world, 1)
    plan = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=1, dry_run=False)
    draw = db.query(M.ComponentConsumption).filter_by(step_run_id=plan["step_run_id"]).one()
    with pytest.raises(HTTPException):
        rc.delete_consumption(draw.id, db)


def test_the_project_materials_are_the_process_inputs(db, world):
    mats = P.process_materials(db, world["project"].id)
    labels = [m.label for m in mats]
    # the glued enclosure is a prepared part: its recipe's inputs are the materials
    assert labels == ["Enclose: test-twin-enclosure", "Enclose: test-twin-antenna",
                      "Sticker: test-twin-sticker", "Carton: TEST-TWIN-KARTON"]
    carton = mats[-1]
    assert (carton.component_id, carton.mpn, carton.unit_price) == (None, "TEST-TWIN-KARTON", pytest.approx(0.5))


def test_the_cost_by_step_adds_up_to_the_batch(db, world):
    stack = _received(db, world, 10)
    plan = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=10, dry_run=False)
    assy = _line(db, world, world["b1"], "final:device", 30.0, "device assembly")
    T.link_costs(db, world["b1"], step_run_ids=[plan["step_run_id"]], line_ids=[assy.id], dry_run=False)
    c = T.cost_by_step(db, world["b1"])
    by = {r["step"]: r for r in c["steps"]}
    assert by["assembly"]["invoices_usd"] == pytest.approx(100.0)
    assert c["board_and_assembly_per_unit_usd"] == pytest.approx(10.0)
    assert by["enclose"]["total_usd"] == pytest.approx(60.0)  # 10 x $3 parts + $30 assembly
    assert c["origin"]["usd"] == pytest.approx(20.0)          # the freight
    assert sum(r["total_usd"] for r in c["steps"]) + c["origin"]["usd"] == pytest.approx(c["total_usd"])



# ------------------------------- one invoice pays for several steps (0061)

def test_one_position_can_pay_for_several_steps(db, world):
    """The final assembler's invoice covers two steps at once: the twins of
    both clicks share it equally, and the cost by step shows it as one row."""
    stack = _received(db, world, 10)
    a = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=6, dry_run=False)
    b = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=4, dry_run=False)
    enclosed = _stack(db, world, world["b1"], {"assembly", "receive", "enclose"})
    c = T.apply_step(db, world["b1"], step_key="sticker", stack=enclosed, qty=10, dry_run=False)
    assy = _line(db, world, world["b1"], "final:device", 50.0, "LIFTECH share")
    T.link_costs(db, world["b1"], step_run_ids=[a["step_run_id"], b["step_run_id"], c["step_run_id"]],
                 line_ids=[assy.id], dry_run=False)
    twins = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).all()
    pr = T.prices(db, twins)
    # $100 assembly / 10 + $50 / the 10 twins of the three clicks
    assert {p["step_costs_usd"] for p in pr.values()} == {15.0}
    total = ra.invoice_register(db)["by_run_usd"][str(world["b1"].id)]["total_usd"]
    assert sum(p["total_usd"] for p in pr.values()) == pytest.approx(total, abs=0.01)
    rows = {r["key"]: r for r in T.cost_by_step(db, world["b1"])["steps"]}
    shared = rows["enclose+sticker"]
    assert (shared["invoices_usd"], shared["units"]) == (50.0, 10)
    assert "one invoice for these steps" in shared["label"]
    tw = twins[0]
    j = T.twin_json(db, tw)
    per_step = {s["step"]: s["costs_usd"] for s in j["steps"]}
    assert per_step["enclose"] + per_step["sticker"] == pytest.approx(5.0)
    assert j["steps"][2]["costs"][0]["shared_by"]


def test_a_rebuild_links_one_invoice_to_several_steps_and_draws_stated_parts(db, world):
    """The final assembler did programming, the enclosure and the label; the
    label step adds a label the old batch never drew, and a person states every
    device got one."""
    from app.services import twin_rebuild as R

    g = P._graph(world["v"])
    P.step_map(g)["label"]["inputs"] = [{"component_id": world["leaflet"].id, "qty": 1}]
    v2 = P.compose(db, world["project"].id, actor="test", graph=g)
    P.publish(db, v2, actor="test", comment="the label step uses a label")
    # The labels were bought on 2026-01-01: a batch made before that cannot
    # have used them, and the rebuild says so instead of inventing stock.
    early, _ = _legacy_batch(db, world, 2)
    with pytest.raises(HTTPException) as e:
        R.rebuild(db, early, version_id=v2.id, assume=["label"], draw=["label"], dry_run=False)
    assert "book the purchase first" in str(e.value.detail)
    run, _devices = _legacy_batch(db, world, 3, run_date="2026-01-20", first=50)
    before = ra.invoice_register(db)["by_run_usd"][str(run.id)]["total_usd"]
    # Stated but not ours: the assembler's labels draw nothing.
    theirs = R.rebuild(db, run, version_id=v2.id, assume=["label", "laser"])
    assert theirs["draws_added"] == []
    plan = R.rebuild(db, run, version_id=v2.id, assume=["label", "laser"], draw=["label"],
                     costs={"final:device": ["program", "label", "carton"]}, dry_run=False)
    assert [(d["step"], d["qty"]) for d in plan["draws_added"]] == [("label", 3.0)]
    assert plan["lines_whose_steps_were_not_recorded"] == []
    li = (db.query(M.RunCostLine).join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
          .filter(M.RunCostLine.label == "device assembly", M.RunCostDocument.run_id == run.id).one())
    linked = {sr.step_key for sr in db.query(M.StepRun).join(
        M.CostLineStep, M.CostLineStep.step_run_id == M.StepRun.id).filter(M.CostLineStep.line_id == li.id)}
    assert linked == {"program", "label", "carton"}
    after = ra.invoice_register(db)["by_run_usd"][str(run.id)]["total_usd"]
    assert after == pytest.approx(before + 3 * 0.1, abs=0.001)  # three $0.10 labels added
    assert plan["carried_usd"] == pytest.approx(after, abs=0.01)
    R.undo(db, run, dry_run=False)
    assert ra.invoice_register(db)["by_run_usd"][str(run.id)]["total_usd"] == pytest.approx(before, abs=0.001)



# ------------------------------- benches: tests, labels, the topic (0061)

def _with(db, world, patch):
    """Publish a version of the world's process changed by `patch(graph)`, and
    craft both batches under it."""
    g = P._graph(world["v"])
    patch(g)
    v = P.compose(db, world["project"].id, actor="test", graph=g)
    P.publish(db, v, actor="test", comment="variant")
    world["b1"].process_version_id = v.id
    world["b2"].process_version_id = v.id
    return v


def test_a_passing_test_records_the_test_step(db, world):
    def add_test(g):
        g["steps"].insert(-1, {"key": "test", "label": "Function test", "kind": "test",
                               "required": True, "needs": ["program"]})
        g["route"].insert(-1, "test")
    _with(db, world, add_test)
    d, tw = _crafted_device(db, world, 14)
    assert T.record_test(db, d) == ["test"]
    assert "test" in T.done_steps(db, [tw.id])[tw.id]
    assert T.record_test(db, d) == []  # done once
    with pytest.raises(HTTPException):
        T.apply_step(db, world["b1"], step_key="test", device_ids=[d.id], chosen="scanned")


def test_the_label_step_draws_a_label_and_says_when_there_is_none(db, world):
    _with(db, world, lambda g: P.step_map(g)["label"].update(
        inputs=[{"component_id": world["leaflet"].id, "qty": 1}]))
    d, tw = _crafted_device(db, world, 15)
    assert T.record_marking(db, d, laser=False, label=True) == ["label"]
    sr = (db.query(M.StepRun).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
          .filter(M.TwinStep.twin_id == tw.id, M.StepRun.step_key == "label").one())
    drawn = db.query(M.ComponentConsumption).filter_by(step_run_id=sr.id).one()
    assert (drawn.component_id, drawn.qty, drawn.run_id) == (world["leaflet"].id, 1, world["b1"].id)
    # the pool runs dry: the step is still recorded, and its note says so
    db.add(M.ComponentConsumption(run_id=world["b2"].id, component_id=world["leaflet"].id, mpn="", lcsc="",
                                  qty=99, unit_cost_usd=0.1, basis="manual", consumed_at="2026-01-02"))
    d2, tw2 = _crafted_device(db, world, 16)
    assert T.record_marking(db, d2, laser=False, label=True) == ["label"]
    sr2 = (db.query(M.StepRun).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
           .filter(M.TwinStep.twin_id == tw2.id, M.StepRun.step_key == "label").one())
    assert "not drawn" in sr2.note
    assert db.query(M.ComponentConsumption).filter_by(step_run_id=sr2.id).count() == 0


def test_a_run_without_a_mac_finds_its_unit_by_the_topic(db, world):
    from app.services.flasher.engine import devices_by_topic

    d = _device(db, world, 17)
    d.serial = "AABBCCDDEE17"
    db.flush()
    pid = world["project"].id
    assert [x.id for x in devices_by_topic(db, pid, "dongle_AABBCCDDEE17")] == [d.id]
    d.tasmota_id = "dongle_custom"
    assert [x.id for x in devices_by_topic(db, pid, "dongle_custom")] == [d.id]
    assert devices_by_topic(db, pid, "dongle_FFFFFFFFFFFF") == []
    assert devices_by_topic(db, pid + 10_000, "dongle_custom") == []



# ------------------------------------------- review fixes (2026-10-04)

def test_found_units_entered_first_never_take_the_assembly(db, world):
    T.enter_found(db, world["b1"], qty=3, done=[], origin_run_id=world["b2"].id, note="count",
                  dry_run=False)
    T.receive(db, world["b1"], qty=10, dry_run=False)
    found = db.query(M.Twin).filter_by(origin_run_id=world["b2"].id, found=True).all()
    received = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id, found=False).all()
    assert {p["total_usd"] for p in T.prices(db, found).values()} == {0.0}
    assert {p["step_costs_usd"] for p in T.prices(db, received).values()} == {10.0}
    # and they are their own pile, named for where they came from
    piles = T.stacks(db, world["project"].id, run_id=world["b1"].id)
    assert sorted(s["count"] for s in piles) == [3, 10]
    assert [s["found_from"] for s in piles if s["count"] == 3] == ["TB2"]


def test_a_recharged_position_is_seen_by_its_new_batch(db, world):
    T.receive(db, world["b1"], qty=2, dry_run=False)
    smt = db.query(M.RunCostLine).filter_by(label="SMT assembly").one()
    smt.run_id = world["b2"].id
    db.flush()
    T.receive(db, world["b2"], qty=5, dry_run=False)
    assert T.assembly_click(db, world["b2"]) is not None
    links = db.query(M.CostLineStep).filter_by(line_id=smt.id).all()
    assert [db.get(M.StepRun, x.step_run_id).run_id for x in links] == [world["b2"].id]


def test_a_split_child_charged_to_the_document_batch_keeps_its_links(db, world):
    from app.routers import run_costs as rc

    T.receive(db, world["b1"], qty=2, dry_run=False)
    doc = M.RunCostDocument(project_id=world["project"].id, run_id=world["b1"].id, doc_type="invoice",
                            supplier="SPLITCO", doc_number="S-1", doc_date="2026-02-02", currency="USD",
                            total_amount=40.0)
    db.add(doc)
    db.flush()
    li = M.RunCostLine(document_id=doc.id, plan_key="pcba:smt", qty=1, unit_price=40.0, label="to split")
    db.add(li)
    db.flush()
    T.record_assembly(db, world["b1"])
    body = rc.SplitIn(children=[rc.ChildIn(label="half", qty=1, unit_price=20.0, plan_key="pcba:smt",
                                           run_id=world["b1"].id),
                                rc.ChildIn(label="other half", qty=1, unit_price=20.0, plan_key="pcba:smt")])
    rc.split_line(li.id, body, db)
    kids = db.query(M.RunCostLine).filter_by(parent_line_id=li.id).all()
    assert all(db.query(M.CostLineStep).filter_by(line_id=k.id).count() == 1 for k in kids)


def test_a_scrapped_device_costs_nothing_on_its_order(db, world):
    from app.services import twin_rebuild as R

    run, devices = _legacy_batch(db, world, 3, first=60)
    devices[0].state = "disposed"
    R.rebuild(db, run, version_id=world["v"].id, dry_run=False)
    costs = T.device_costs(db)
    total = ra.invoice_register(db)["by_run_usd"][str(run.id)]["total_usd"]
    assert costs[devices[0].id] == 0.0
    assert sum(costs[d.id] for d in devices) == pytest.approx(total, abs=0.01)


def test_whole_steps_link_every_click(db, world):
    stack = _received(db, world, 3)
    T.set_bench_stack(db, world["b1"], stack)
    for n in (70, 71, 72):
        _program(db, world, world["b1"], n)
    li = _line(db, world, world["b1"], "final:device", 30.0, "programming service")
    T.link_costs(db, world["b1"], step_run_ids=[], step_keys=["program"], line_ids=[li.id], dry_run=False)
    assert db.query(M.CostLineStep).filter_by(line_id=li.id).count() == 3
    named = db.query(M.Twin).filter(M.Twin.origin_run_id == world["b1"].id,
                                    M.Twin.device_unit_id.isnot(None)).all()
    # $100 assembly / 3 units + the $30 programming service / the 3 programmed units
    assert all(p["step_costs_usd"] == pytest.approx(100 / 3 + 10.0, abs=0.01)
               for p in T.prices(db, named).values())


def test_guards_on_closed_batches_rebatch_and_found_devices(db, world):
    from app.services import twin_rebuild as R

    run, devices = _legacy_batch(db, world, 2, first=80)
    R.rebuild(db, run, version_id=world["v"].id, dry_run=False)
    run.closed_at = datetime(2026, 3, 1, tzinfo=UTC)
    with pytest.raises(HTTPException):
        R.undo(db, run, dry_run=False)
    with pytest.raises(HTTPException):
        T.receive(db, run, qty=1)
    run.closed_at = None
    plain = M.ProductionRun(project_id=world["project"].id, label="TB-plain", run_date="2026-04-01", qty=1)
    db.add(plain)
    db.flush()
    assert "has no process" in (T.refuse_rebatch(db, devices[0], plain) or "")
    _other, kept = _legacy_batch(db, world, 1, first=85)   # produced in a batch, never rebuilt
    with pytest.raises(HTTPException) as e:
        T.enter_found(db, world["b2"], done=[], origin_run_id=world["b1"].id, device_ids=[kept[0].id],
                      note="x", dry_run=False)
    assert "rebuild that batch" in str(e.value.detail)


def test_scrap_refuses_another_batch_stack(db, world):
    stack = _received(db, world, 2)
    with pytest.raises(HTTPException):
        T.scrap(db, world["b2"], stack=stack, qty=1, reason="x", dry_run=False)


def test_label_copies_draw_one_label_each_and_marks_catch_up(db, world):
    _with(db, world, lambda g: P.step_map(g)["label"].update(
        inputs=[{"component_id": world["leaflet"].id, "qty": 1}]))
    stack = _received(db, world, 1)
    T.set_bench_stack(db, world["b1"], stack)
    d, tw = _program(db, world, world["b1"], 90)     # programmed, not enclosed
    # a marking run engraves and prints two copies before the enclosure
    run = M.ProgrammingRun(device_unit_id=d.id, status="pass", operator="tester",
                           results={"marked": "X", "printed": "X", "label_copies": 2},
                           started_at=datetime(2026, 2, 10, tzinfo=UTC))
    db.add(run)
    db.flush()
    assert T.record_marking(db, d, laser=True, label=True, copies=2, actor="tester") == ["label"]
    lab = (db.query(M.StepRun).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
           .filter(M.TwinStep.twin_id == tw.id, M.StepRun.step_key == "label").one())
    assert lab.actor == "tester"
    assert db.query(M.ComponentConsumption).filter_by(step_run_id=lab.id).one().qty == 2
    # the laser mark waits for the enclosure, then the bench's run records it
    plan = T.apply_step(db, world["b1"], step_key="enclose", device_ids=[d.id], chosen="scanned", dry_run=False)
    assert plan["caught_up"] and "laser" in plan["caught_up"][0]["steps"]


def test_a_test_run_never_warns_about_the_bench_stack(db, world):
    dep = _deployment(db, world, "test-tst", "test")
    ver = M.DeploymentVersion(deployment_id=dep.id, version_no=1, status="published", steps=[])
    db.add(ver)
    db.flush()
    d = _device(db, world, 91)
    run = M.ProgrammingRun(device_unit_id=d.id, status="running", deployment_version_id=ver.id,
                           production_run_id=world["b1"].id)
    assert [n["code"] for n in bench_checks._about_the_batch(db, world["b1"], d, created=True, run=run)
            if n["code"] in ("no_stack", "stack_empty")] == []


def test_the_label_is_in_the_project_materials(db, world):
    _with(db, world, lambda g: P.step_map(g)["label"].update(
        inputs=[{"component_id": world["leaflet"].id, "qty": 1}]))
    assert any(m.step == "label" for m in P.process_materials(db, world["project"].id))



def test_a_step_stated_since_a_date_goes_only_on_later_devices(db, world):
    """The leaflet: every device programmed since a date got one, none before."""
    from app.services import twin_rebuild as R

    run, devices = _legacy_batch(db, world, 3, first=95)
    for d, day in zip(devices, (1, 10, 20)):
        ev = next(e for e in d.events if e.kind == "produced")
        ev.at = datetime(2026, 4, day, 12, tzinfo=UTC)
    db.flush()
    plan = R.rebuild(db, run, version_id=world["v"].id, assume=["leaflet"], since={"leaflet": "2026-04-10"},
                     costs={"final:device": ["carton", "leaflet"]}, dry_run=False)
    got = {r["step"]: r["units"] for r in plan["recorded"]}
    assert got["leaflet"] == 2
    with_leaflet = {db.get(M.Twin, ts.twin_id).device_unit_id for ts in db.query(M.TwinStep).join(
        M.StepRun, M.StepRun.id == M.TwinStep.step_run_id).filter(M.StepRun.run_id == run.id,
                                                                    M.StepRun.step_key == "leaflet")}
    assert with_leaflet == {devices[1].id, devices[2].id}
