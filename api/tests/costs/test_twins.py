"""Twins: crafting a batch step by step, and each device's price (decision 0059).

What these pin down:

- receiving makes one twin per board, in one stack; a step on a stack draws
  N x each input, charged to the batch, and the stack's key moves on;
- a step whose needs are not met is refused, and a choice allows one option;
- on named devices a refused unit refuses the click, unless the person skips
  it: the others take the step, a step is never recorded twice, and the
  click's note names the skipped units;
- a stack is one physical pile: units enclosed from two lots are two stacks;
- the bench names a twin from the selected stack, never invents one, and a
  device programmed with no stack is a gap until a merge;
- the marking bench records its steps; finish refuses a missing required step,
  and a shipment refuses an unfinished device;
- a twin's price is its own parts plus an equal share of its origin batch
  cost; scrapped twins are carried; a twin programmed in another batch keeps
  its origin share; found units enter at zero; a crafted batch draws no BOM;
- the board's assembly is a step the person records from the pre-filled
  "Record assembly" form (decisions 0060, 0072): receiving the boards does not
  record it, only the ticked positions and draws join it, a position imported
  later waits until it is added, the record is undone whole, any other
  position can be linked to the click it paid for, and the twins' prices still
  add up to the batch's total.

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
    # A required bench step needs a bench of its kind in the project (0074).
    for kind in ("flash", "mark", "test"):
        db.add(M.Deployment(project_id=proj.id, name=f"test-world-{kind}", kind=kind))
    db.flush()
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


def _assemble(db, run, **kw):
    """Record the assembly with every row of its draft ticked (decision 0072)."""
    d = T.assembly_draft(db, run)
    return T.apply_assembly(db, run, line_ids=[x["line_id"] for x in d["lines"]],
                            draw_ids=[x["consumption_id"] for x in d["parts_from_stock"]], **kw)[1]


def _received(db, world, n=10):
    T.receive(db, world["b1"], qty=n, made_at="2026-02-01", dry_run=False)
    _assemble(db, world["b1"])
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


def _crafted_devices(db, world, first, n):
    """`n` programmed devices of B1, enclosed, serials TW<first>…"""
    stack = _received(db, world, n)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=n, dry_run=False)
    T.set_bench_stack(db, world["b1"], _stack(db, world, world["b1"], {"assembly", "receive", "enclose"}))
    return [_program(db, world, world["b1"], first + i)[0] for i in range(n)]


def _carton_links(db, device):
    tw = db.query(M.Twin).filter_by(device_unit_id=device.id).one()
    return (db.query(M.TwinStep).join(M.StepRun, M.StepRun.id == M.TwinStep.step_run_id)
            .filter(M.TwinStep.twin_id == tw.id, M.StepRun.step_key == "carton").count())


def test_a_step_on_named_devices_can_skip_the_units_that_cannot_take_it(db, world):
    d1, d2, d3 = _crafted_devices(db, world, 21, 3)
    T.apply_step(db, world["b1"], step_key="carton", device_ids=[d1.id], chosen="scanned", dry_run=False)
    ids = [d1.id, d2.id, d3.id]
    plan = T.apply_step(db, world["b1"], step_key="carton", device_ids=ids, chosen="scanned")
    # The plan counts and draws for the two that can take it, and names the third.
    assert (plan["units"], plan["selected"]) == (2, 3)
    assert plan["refused"] == [{"unit": "TW0021", "why": ["'Carton' is already done"]}]
    assert [d["qty"] for d in plan["draws"]] == [2]
    with pytest.raises(HTTPException) as e:
        T.apply_step(db, world["b1"], step_key="carton", device_ids=ids, chosen="scanned", dry_run=False)
    assert e.value.status_code == 409
    assert [_carton_links(db, d) for d in (d1, d2, d3)] == [1, 0, 0]
    done = T.apply_step(db, world["b1"], step_key="carton", device_ids=ids, chosen="scanned",
                        skip_refused=True, dry_run=False)
    assert done["units"] == 2
    # Never twice: the unit that had the step keeps one.
    assert [_carton_links(db, d) for d in (d1, d2, d3)] == [1, 1, 1]
    sr = db.get(M.StepRun, done["step_run_id"])
    assert (sr.qty, sr.note) == (2, "skipped 1 of 3 (refused): TW0021")
    draws = db.query(M.ComponentConsumption).filter_by(step_run_id=sr.id).all()
    assert [d.qty for d in draws] == [2]


def test_skipping_refuses_a_click_no_unit_can_take(db, world):
    (d,) = _crafted_devices(db, world, 31, 1)
    T.apply_step(db, world["b1"], step_key="carton", device_ids=[d.id], chosen="list", dry_run=False)
    with pytest.raises(HTTPException) as e:
        T.apply_step(db, world["b1"], step_key="carton", device_ids=[d.id], chosen="list",
                     skip_refused=True, dry_run=False)
    assert e.value.status_code == 409 and "none of these units" in e.value.detail["error"]


def test_a_unit_the_batch_screen_cannot_craft_is_named_not_an_error(db, world):
    d1, d2 = _crafted_devices(db, world, 41, 2)
    T.scrap(db, world["b1"], device_ids=[d1.id], chosen="list", reason="dropped", dry_run=False)
    plan = T.apply_step(db, world["b1"], step_key="carton", device_ids=[d1.id, d2.id], chosen="scanned")
    assert (plan["units"], plan["selected"]) == (1, 2)
    assert plan["refused"] == [{"unit": "TW0041", "why": ["it is scrapped"]}]
    # The paths that act on whole selections keep refusing outright.
    with pytest.raises(HTTPException) as e:
        T.finish(db, world["b1"], device_ids=[d1.id, d2.id], chosen="scanned")
    assert e.value.detail == "TW0041 is scrapped"


def test_the_skipped_note_fits_its_column():
    names = [f"88F1555A{i:04d}" for i in range(60)]
    note = T._skipped_note("packed by Kuba", names, 90)
    assert len(note) <= 500
    assert note.startswith("skipped 60 of 90 (refused): 88F1555A0000, ")
    assert " more — packed by Kuba" in note
    assert T._skipped_note("", ["A", "B"], 5) == "skipped 2 of 5 (refused): A, B"


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


def test_receiving_no_longer_records_the_assembly(db, world):
    """Decision 0072: the person records it from the pre-filled form."""
    plan = T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    assert "assembly" not in plan
    assert T.assembly_click(db, world["b1"]) is None
    d = T.assembly_draft(db, world["b1"])
    assert d["status"] == "open" and d["header"]["twins_not_in_step"] == 10
    assert [x["label"] for x in d["lines"]] == ["SMT assembly"]   # freight is no board position


def test_the_assembly_records_what_the_person_ticked(db, world):
    measured = M.ComponentConsumption(run_id=world["b1"].id, component_id=world["sticker"].id, mpn="",
                                      lcsc="", qty=10, unit_cost_usd=0.2, basis="measured",
                                      consumed_at="2026-01-30", import_ref="jlc:test:SMT-T:x")
    db.add(measured)
    db.flush()
    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    a = _assemble(db, world["b1"], assembler="JLCPCB", reference="SMT-T")
    assert (a["status"], a["units"], a["lines_linked"], a["draws_linked"]) == ("recorded", 10, 1, 1)
    sr = T.assembly_click(db, world["b1"])
    assert (sr.assembler, sr.reference) == ("JLCPCB", "SMT-T")
    assert measured.step_run_id == sr.id
    freight = db.query(M.RunCostLine).filter_by(label="Freight").one()
    # freight is batch overhead: no step paid for it
    assert db.query(M.CostLineStep).filter_by(line_id=freight.id).count() == 0
    tw = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).first()
    p = T.prices(db, [tw])[tw.id]
    assert (p["own_parts_usd"], p["step_costs_usd"], p["origin_share_usd"]) == (0.2, 10.0, 2.0)


def test_a_position_imported_after_receipt_joins_the_assembly(db, world):
    T.receive(db, world["b1"], qty=5, dry_run=False)
    _assemble(db, world["b1"])
    _line(db, world, world["b1"], "fab:pcb", 50.0, "bare boards")
    # it waits outside the step until the person adds it
    assert [x["label"] for x in T.assembly_draft(db, world["b1"])["lines"]] == ["bare boards"]
    res = _assemble(db, world["b1"])
    assert (res["status"], res["lines_linked"], res["twins_added"]) == ("extended", 1, 0)
    tw = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).first()
    assert T.prices(db, [tw])[tw.id]["step_costs_usd"] == pytest.approx(30.0)  # $150 / 5


def test_twins_received_later_join_the_same_assembly_click(db, world):
    T.receive(db, world["b1"], qty=4, dry_run=False)
    _assemble(db, world["b1"])
    T.receive(db, world["b1"], qty=6, dry_run=False)
    assert T.assembly_draft(db, world["b1"])["header"]["twins_not_in_step"] == 6
    _assemble(db, world["b1"])
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
    # Programmed on the batch's date: a rebuild dates each step by the device
    # (decision 0060, the 2026-10-05 review), so an old batch's devices must
    # not read as programmed in 2026.
    at = datetime.fromisoformat(run_date).replace(hour=12, tzinfo=UTC)
    for i in range(n_devices):
        d = _device(db, world, first + i)
        osvc.mark_produced(db, d, run.id, at=at, actor="test")
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
    _assemble(db, world["b1"])
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
    _assemble(db, world["b1"])
    smt = db.query(M.RunCostLine).filter_by(label="SMT assembly").one()
    smt.run_id = world["b2"].id
    db.flush()
    T.receive(db, world["b2"], qty=5, dry_run=False)
    _assemble(db, world["b2"])
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
    _assemble(db, world["b1"])
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


# ---------------------------------------------- "Record assembly" (decision 0072)

def _assembly_body(**kw):
    from app.routers import process as pr

    return pr.AssemblyIn(**kw)


def test_the_assembly_waits_for_the_boards(db, world):
    from app.routers import process as pr

    with pytest.raises(HTTPException) as e:
        pr.craft_assembly(world["b1"].id, _assembly_body(dry_run=True), db=db)
    assert e.value.status_code == 409 and "receive the boards first" in str(e.value.detail)


def test_a_dry_run_writes_nothing_and_a_real_one_is_undone_whole(db, world):
    from app.routers import ledger
    from app.routers import process as pr

    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    smt = db.query(M.RunCostLine).filter_by(label="SMT assembly").one()
    dry = pr.craft_assembly(world["b1"].id, _assembly_body(dry_run=True, line_ids=[smt.id]), db=db)
    assert (dry["dry_run"], dry["units"], dry["lines_linked"]) == (True, 10, 1)
    assert T.assembly_click(db, world["b1"]) is None
    res = pr.craft_assembly(world["b1"].id, _assembly_body(dry_run=False, line_ids=[smt.id],
                                                             assembler="ACME", reference="PO-1"), db=db)
    assert res["batch_id"] and T.assembly_click(db, world["b1"]) is not None
    assert T.assembly_draft(db, world["b1"])["recorded"]["batch_ids"] == [res["batch_id"]]
    ledger.reverse_batch(res["batch_id"], dry_run=False, db=db)
    db.expire_all()
    assert T.assembly_click(db, world["b1"]) is None
    assert db.query(M.CostLineStep).filter_by(line_id=smt.id).count() == 0
    twins = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).all()
    assert {tw.stack_key for tw in twins} == {"receive"}


def test_another_house_draws_our_parts_through_the_step(db, world):
    from app.routers import process as pr

    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    res = pr.craft_assembly(world["b1"].id, _assembly_body(
        dry_run=False, assembler="LOCAL HOUSE",
        parts=[{"component_id": world["sticker"].id, "qty": 10}]), db=db)
    sr = T.assembly_click(db, world["b1"])
    assert (res["draws_written"], sr.chosen) == (1, "manual")
    d = db.query(M.ComponentConsumption).filter_by(step_run_id=sr.id).one()
    assert (d.run_id, d.qty, d.unit_cost_usd) == (world["b1"].id, 10, pytest.approx(0.2))
    with pytest.raises(HTTPException) as e:
        pr.craft_assembly(world["b1"].id, _assembly_body(
            dry_run=True, parts=[{"component_id": world["sticker"].id, "qty": 1000}]), db=db)
    assert e.value.status_code == 409 and "short" in str(e.value.detail)


def test_the_parts_the_assembler_bought_split_their_total_onto_the_step(db, world):
    from app.routers import process as pr

    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    doc = db.query(M.RunCostDocument).filter_by(doc_number="A-1").one()
    lump = M.RunCostLine(document_id=doc.id, plan_key="pcba:parts", qty=1, unit_price=5.0, run_id=world["b1"].id,
                         label="Parts", position=5)
    db.add(lump)
    db.flush()
    assert [x["line_id"] for x in T.assembly_draft(db, world["b1"])["parts_lumps"]] == [lump.id]
    res = pr.craft_assembly(world["b1"].id, _assembly_body(dry_run=False, supplied=[
        {"parent_line_id": lump.id, "lcsc": "C1", "mpn": "R1K", "qty": 100, "unit_price": 0.03},
        {"parent_line_id": lump.id, "lcsc": "C2", "mpn": "C100N", "qty": 100, "unit_price": 0.02}]), db=db)
    assert res["supplied_children"] == 2
    sr = T.assembly_click(db, world["b1"])
    kids = db.query(M.RunCostLine).filter_by(parent_line_id=lump.id).all()
    assert len(kids) == 2 and all(
        db.query(M.CostLineStep).filter_by(line_id=k.id, step_run_id=sr.id).count() == 1 for k in kids)


def test_a_replacement_is_recorded_with_the_step(db, world):
    from app.routers import process as pr

    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    pr.craft_assembly(world["b1"].id, _assembly_body(dry_run=False, replacements=[
        {"designator": "C2", "specified_lcsc": "C110548", "fitted_lcsc": "C7223", "supplied_by": "supplier"}]),
        db=db)
    sr = T.assembly_click(db, world["b1"])
    sub = db.query(M.RunSubstitution).filter_by(run_id=world["b1"].id, designator="C2").one()
    assert (sub.step_run_id, sub.source) == (sr.id, "us")
    assert T.assembly_draft(db, world["b1"])["recorded"]["replacements"][0]["designator"] == "C2"


def test_a_row_not_offered_is_refused(db, world):
    from app.routers import process as pr

    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    freight = db.query(M.RunCostLine).filter_by(label="Freight").one()
    other = _line(db, world, world["b2"], "pcba:smt", 9.0, "another batch")
    with pytest.raises(HTTPException) as e:
        pr.craft_assembly(world["b1"].id, _assembly_body(dry_run=True, line_ids=[other.id]), db=db)
    assert e.value.status_code == 422
    # a position of the batch outside the board stages may still be ticked on purpose
    res = pr.craft_assembly(world["b1"].id, _assembly_body(dry_run=True, line_ids=[freight.id]), db=db)
    assert res["lines_linked"] == 1


# --------------------------------------- "Record assembly": review round (0072)

def _record(db, run, **kw):
    from app.routers import process as pr

    return pr.craft_assembly(run.id, _assembly_body(dry_run=False, **kw), db=db)


def _undo(db, batch_id, dry=False):
    from app.routers import ledger

    return ledger.reverse_batch(batch_id, dry_run=dry, db=db)


def test_an_older_record_waits_for_the_newer_one_to_be_undone(db, world):
    T.receive(db, world["b1"], qty=4, dry_run=False)
    a1 = _record(db, world["b1"])
    T.receive(db, world["b1"], qty=6, dry_run=False)
    smt = db.query(M.RunCostLine).filter_by(label="SMT assembly").one()
    a2 = _record(db, world["b1"], line_ids=[smt.id])
    with pytest.raises(HTTPException) as e:
        _undo(db, a1["batch_id"], dry=True)
    assert str(a2["batch_id"]) in str(e.value.detail)
    _undo(db, a2["batch_id"])
    db.expire_all()
    _undo(db, a1["batch_id"])   # the undone pair is no longer in the way
    db.expire_all()
    assert T.assembly_click(db, world["b1"]) is None


def test_a_total_ticked_and_split_is_still_undone_whole(db, world):
    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    doc = db.query(M.RunCostDocument).filter_by(doc_number="A-1").one()
    lump = M.RunCostLine(document_id=doc.id, plan_key="pcba:parts", qty=1, unit_price=5.0, run_id=world["b1"].id,
                         label="Parts", position=5)
    db.add(lump)
    db.flush()
    res = _record(db, world["b1"], line_ids=[lump.id], supplied=[
        {"parent_line_id": lump.id, "lcsc": "C1", "mpn": "R1K", "qty": 100, "unit_price": 0.03}])
    assert res["supplied_residual"] == [{"line_id": lump.id, "label": "Parts", "residual": 2.0, "currency": "USD"}]
    assert _undo(db, res["batch_id"], dry=True)["status"] == "would_reverse"
    _undo(db, res["batch_id"])
    db.expire_all()
    assert db.query(M.RunCostLine).filter_by(parent_line_id=lump.id, voided_at=None).count() == 0


def test_an_addition_takes_the_step_s_date(db, world):
    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    _record(db, world["b1"], made_at="2026-02-02")
    with pytest.raises(HTTPException) as e:
        _record(db, world["b1"], made_at="2026-03-01", parts=[{"component_id": world["sticker"].id, "qty": 1}])
    assert e.value.status_code == 422 and "2026-02-02" in str(e.value.detail)


def test_a_jlc_parts_total_under_the_fee_split_is_a_total(db, world):
    doc = db.query(M.RunCostDocument).filter_by(doc_number="A-1").one()
    general = M.RunCostLine(document_id=doc.id, plan_key="pcba:general", qty=1, unit_price=0, label="Module", position=6)
    db.add(general)
    db.flush()
    total = M.RunCostLine(document_id=doc.id, parent_line_id=general.id, plan_key="pcba:parts", qty=1, unit_price=9,
                          label="Components sourced by JLC", position=7)
    db.add(total)
    db.flush()
    part = M.RunCostLine(document_id=doc.id, parent_line_id=total.id, plan_key="pcba:parts", qty=1, unit_price=9,
                         label="R1", position=8)
    db.add(part)
    db.flush()
    assert (T._line_kind(db, total), T._line_kind(db, part)) == ("parts_lump", "supplied_part")


def test_an_undo_survives_a_later_unrelated_money_write(db, world):
    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    smt = db.query(M.RunCostLine).filter_by(label="SMT assembly").one()
    res = _record(db, world["b1"], line_ids=[smt.id])
    _line(db, world, world["b2"], "pcba:smt", 7.0, "unrelated")
    assert _undo(db, res["batch_id"])["status"] == "reversed"


def test_a_closed_batch_keeps_its_assembly(db, world):
    from app.routers import production_runs as prr

    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    with pytest.raises(HTTPException) as e:
        prr.close_run(world["b1"].id, db=db)
    assert "record the assembly" in str(e.value.detail)
    res = _record(db, world["b1"])
    prr.close_run(world["b1"].id, db=db)
    assert T.assembly_draft(db, world["b1"])["recorded"]["batch_ids"] == []
    with pytest.raises(HTTPException) as e:
        _undo(db, res["batch_id"], dry=True)
    assert "closed" in str(e.value.detail)


def test_an_undo_puts_back_a_link_the_record_replaced(db, world):
    T.receive(db, world["b1"], qty=2, dry_run=False)
    smt = db.query(M.RunCostLine).filter_by(label="SMT assembly").one()
    _record(db, world["b1"], line_ids=[smt.id])
    first = T.assembly_click(db, world["b1"])
    smt.run_id = world["b2"].id
    db.flush()
    T.receive(db, world["b2"], qty=5, dry_run=False)
    res = _record(db, world["b2"], line_ids=[smt.id])
    _undo(db, res["batch_id"])
    db.expire_all()
    assert [x.step_run_id for x in db.query(M.CostLineStep).filter_by(line_id=smt.id)] == [first.id]


def test_the_bench_stack_survives_recording_the_assembly(db, world):
    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    world["b1"].bench_stack = f"{world['b1'].id}:receive"
    db.flush()
    assert T.bench_stack_left(db, world["b1"]) == 10
    _record(db, world["b1"])
    assert T.bench_stack_left(db, world["b1"]) == 10


def test_an_addition_is_its_batch_s_company_s(db, world):
    from app.services import access as A
    from app.services import companies as C

    world["b1"].company_id = C.by_key(db, "7sigma").id
    db.flush()
    T.receive(db, world["b1"], qty=10, made_at="2026-02-01", dry_run=False)
    _record(db, world["b1"])
    smt = db.query(M.RunCostLine).filter_by(label="SMT assembly").one()
    a2 = _record(db, world["b1"], line_ids=[smt.id])
    assert A.write_batch_companies(db, a2["batch_id"]) == {world["b1"].company_id}


# ------------------------------- versions, undo and bench runs (decision 0074)

def _variant(db, world, *, drop: str = "", carton: float = 1, historical: bool = False):
    import copy

    g = copy.deepcopy(P._graph(world["v"]))   # _graph shares the step dicts with v1
    g["steps"] = [s for s in g["steps"] if s["key"] != drop]
    g["route"] = [k for k in g["route"] if k != drop]
    P.step_map(g)["carton"]["inputs"] = [{"mpn": "TEST-TWIN-KARTON", "qty": carton}]
    v = P.compose(db, world["project"].id, actor="test", graph=g)
    return P.publish(db, v, actor="test", comment="variant", historical=historical)


def test_a_version_published_as_history_is_never_current(db, world):
    old = _variant(db, world, drop="leaflet", historical=True)
    assert P.current_version(db, world["project"].id).id == world["v"].id
    P.make_current(db, old)
    assert P.current_version(db, world["project"].id).id == old.id
    with pytest.raises(HTTPException):
        P.make_current(db, P.compose(db, world["project"].id, actor="test"))   # a draft


def test_a_batch_is_priced_from_the_version_it_pinned(db, world):
    from app.services import project_bom as pb

    _variant(db, world, carton=2)   # now current; B1 keeps v1

    def carton(run):
        rows = pb.priced_bom_costs_only(db, world["project"], 10, run=run)["extra"]
        return next(x["qty_per"] for x in rows if x["mpn"] == "TEST-TWIN-KARTON")

    assert carton(world["b1"]) == 1
    assert carton(None) == 2


def test_a_batch_moves_to_another_version_unless_its_twins_did_a_step_it_lacks(db, world):
    from app.routers import process as pr

    d, _tw = _crafted_device(db, world, 21)
    nolf = _variant(db, world, drop="leaflet", historical=True)
    plan = pr.repin_batch(world["b1"].id, pr.RepinIn(version_id=nolf.id), db=db)
    assert (plan["from_version"], plan["to_version"], plan["removed_steps"]) == (
        world["v"].version_no, nolf.version_no, ["leaflet"])
    assert world["b1"].process_version_id == world["v"].id     # a dry run moves nothing
    T.apply_step(db, world["b1"], step_key="leaflet", device_ids=[d.id], chosen="list", dry_run=False)
    with pytest.raises(HTTPException) as e:
        pr.repin_batch(world["b1"].id, pr.RepinIn(version_id=nolf.id), db=db)
    assert e.value.status_code == 409 and "leaflet (1 twin(s))" in str(e.value.detail)
    pr.repin_batch(world["b2"].id, pr.RepinIn(version_id=nolf.id, dry_run=False), db=db)
    assert world["b2"].process_version_id == nolf.id
    world["b2"].closed_at = datetime.now(UTC)
    with pytest.raises(HTTPException) as e:
        pr.repin_batch(world["b2"].id, pr.RepinIn(version_id=world["v"].id), db=db)
    assert e.value.status_code == 409 and "closed" in str(e.value.detail)


def test_every_crafting_click_is_undone_whole(db, world):
    from app.routers import process as pr

    rec = pr.craft_receive(world["b1"].id, pr.ReceiveIn(qty=3, made_at="2026-02-01", dry_run=False), db=db)
    asm = _record(db, world["b1"])
    stack = _stack(db, world, world["b1"], {"assembly", "receive"})
    dry = pr.craft_step(world["b1"].id, pr.StepIn(step_key="enclose", stack=stack, qty=3), db=db)
    assert dry["units"] == 3 and "batch_id" not in dry
    step = pr.craft_step(world["b1"].id, pr.StepIn(step_key="enclose", stack=stack, qty=3, dry_run=False), db=db)
    clicks = {c["step"]: c["batch_id"] for c in T.craft_view(db, world["b1"])["clicks"]}
    assert (clicks["receive"], clicks["enclose"]) == (rec["batch_id"], step["batch_id"])
    assert db.query(M.ComponentConsumption).filter_by(step_run_id=step["step_run_id"]).count()
    with pytest.raises(HTTPException) as e:   # later clicks stand on its twins
        _undo(db, rec["batch_id"], dry=True)
    assert e.value.status_code == 409
    _undo(db, step["batch_id"])
    db.expire_all()
    assert db.query(M.ComponentConsumption).filter_by(step_run_id=step["step_run_id"]).count() == 0
    twins = db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).all()
    assert {tw.stack_key for tw in twins} == {"assembly|receive"}
    _undo(db, asm["batch_id"])
    _undo(db, rec["batch_id"])
    db.expire_all()
    assert db.query(M.Twin).filter_by(origin_run_id=world["b1"].id).count() == 0


def test_a_click_the_bench_has_built_on_is_not_undone(db, world):
    from app.routers import process as pr

    pr.craft_receive(world["b1"].id, pr.ReceiveIn(qty=2, dry_run=False), db=db)
    asm = _record(db, world["b1"])
    T.set_bench_stack(db, world["b1"], _stack(db, world, world["b1"], {"assembly", "receive"}))
    _program(db, world, world["b1"], 22)
    with pytest.raises(HTTPException) as e:
        _undo(db, asm["batch_id"], dry=True)
    assert e.value.status_code == 409


def test_a_bench_step_keeps_its_run_and_deployment_version(db, world):
    flash = _deployment(db, world, "test-flash-v", "flash")
    dv1, dv2 = (M.DeploymentVersion(deployment_id=flash.id, version_no=n, status="published") for n in (1, 2))
    db.add_all([dv1, dv2])
    db.flush()
    T.set_bench_stack(db, world["b1"], _received(db, world, 1))
    d = _device(db, world, 23)
    first = M.ProgrammingRun(device_unit_id=d.id, status="pass", deployment_version_id=dv1.id,
                             production_run_id=world["b1"].id)
    db.add(first)
    db.flush()
    tw = T.name_at_bench(db, d, osvc.mark_produced(db, d, world["b1"].id, actor="test"), world["b1"],
                         programming_run=first)
    again = M.ProgrammingRun(device_unit_id=d.id, status="pass", deployment_version_id=dv2.id)
    db.add(again)
    db.flush()
    j = T.twin_json(db, tw)
    prog = next(s for s in j["steps"] if s["step"] == "program")
    assert (prog["programming_run_id"], prog["deployment_version"]) == (first.id, "test-flash-v v1")
    assert [(r["programming_run_id"], r["deployment_version"]) for r in j["reflashes"]] == [
        (again.id, "test-flash-v v2")]


def test_a_gap_does_not_ship_is_held_and_is_uncosted(db, world):
    _received(db, world, 2)
    d, tw = _program(db, world, world["b1"], 30)   # no stack selected: a gap
    assert tw is None
    with pytest.raises(HTTPException) as e:
        T.refuse_unfinished(db, d)
    assert e.value.status_code == 409 and e.value.detail["status"] == "gap"
    row = next(r for r in osvc.run_stock(db, world["project"].id) if r["run_id"] == world["b1"].id)
    assert (row["devices_available"], row["devices_held"]) == (0, {"gap": 1})
    cust = osvc.get_customer(db, "test-twin-gap-customer")
    order = M.SalesOrder(customer_id=cust.id, order_ref="TEST/GAP", order_date="2026-03-01")
    db.add(order)
    db.flush()
    line = M.SalesOrderLine(order_id=order.id, project_id=world["project"].id, product="thing",
                            qty_ordered=1, unit_price=100.0)
    db.add(line)
    db.flush()
    osvc.record_event(db, d, "shipped", order_line_id=line.id)   # shipped before the rule
    db.refresh(order)
    econ = osvc.order_economics(db, order, {world["b1"].id: 99.0}, T.device_costs(db))
    assert (econ["uncosted_units"], econ["devices_cost_usd"]) == (1, 0.0)


def test_a_unit_in_work_is_held_and_ships_once_finished(db, world):
    _d, tw = _crafted_device(db, world, 31)

    def row():
        return next(r for r in osvc.run_stock(db, world["project"].id) if r["run_id"] == world["b1"].id)

    assert (row()["devices_available"], row()["devices_held"]) == (0, {"in process": 1})
    tw.status = "finished"
    db.flush()
    assert (row()["devices_available"], row()["devices_held"]) == (1, {})


def test_a_bench_step_can_be_stated_on_named_devices_with_a_reason(db, world):
    d, tw = _crafted_device(db, world, 32)
    with pytest.raises(HTTPException) as e:
        T.apply_step(db, world["b1"], step_key="label", device_ids=[d.id], chosen="list", dry_run=True)
    assert e.value.status_code == 422 and "stated on named devices" in e.value.detail
    with pytest.raises(HTTPException):
        T.apply_step(db, world["b1"], step_key="enclose", device_ids=[d.id], chosen="list",
                     stated="done elsewhere", dry_run=True)
    res = T.apply_step(db, world["b1"], step_key="label", device_ids=[d.id], chosen="scanned",
                       stated="label printed by hand after a jam", dry_run=False)
    sr = db.get(M.StepRun, res["step_run_id"])
    assert (sr.chosen, sr.note) == ("stated", "stated: label printed by hand after a jam")
    assert "label" in T.done_steps(db, [tw.id])[tw.id]


def test_a_required_bench_step_needs_a_bench_of_its_kind(db, world):
    g = P._graph(world["v"])
    for dep in db.query(M.Deployment).filter_by(project_id=world["project"].id, kind="mark").all():
        db.delete(dep)
    db.flush()
    errors = P.check(db, world["project"].id, g)["errors"]
    assert any("'Laser mark' is required, and the project has no 'mark' deployment" in e for e in errors)


def test_scrapping_a_named_unit_disposes_of_it_and_the_undo_gives_it_back(db, world):
    from app.routers import process as pr

    d, tw = _crafted_device(db, world, 33)
    res = pr.craft_scrap(world["b1"].id, pr.ScrapIn(device_ids=[d.id], chosen="list", reason="cracked",
                                                    dry_run=False), db=db)
    assert (d.state, tw.status) == ("disposed", "scrapped")
    _undo(db, res["batch_id"])
    db.expire_all()
    assert (db.get(M.DeviceUnit, d.id).state, db.get(M.Twin, tw.id).status) == ("in_stock", "active")


def test_disposing_of_a_device_scraps_its_finished_twin(db, world):
    d, tw = _crafted_device(db, world, 34)
    tw.status = "finished"
    osvc.dispose_device(db, d, reason="water damage", actor="test")
    assert tw.status == "scrapped"
    assert "scrap" in T.done_steps(db, [tw.id])[tw.id]


def test_a_finished_unit_is_reopened_for_rework_and_finished_again(db, world):
    d, tw = _crafted_device(db, world, 35)
    with pytest.raises(HTTPException) as e:   # still active
        T.reopen(db, world["b1"], device_ids=[d.id], chosen="list", reason="new label", dry_run=False)
    assert e.value.status_code == 409
    tw.status = "finished"
    T.reopen(db, world["b1"], device_ids=[d.id], chosen="list", reason="new label", dry_run=False)
    assert (tw.status, tw.finished_at) == ("active", None)
    with pytest.raises(HTTPException):
        T.refuse_unfinished(db, d)


def test_a_device_named_from_the_wrong_pile_swaps_its_twin(db, world):
    T.receive(db, world["b1"], qty=2, made_at="2026-02-01", dry_run=False)
    _assemble(db, world["b1"])
    T.receive(db, world["b2"], qty=1, made_at="2026-03-01", dry_run=False)
    _assemble(db, world["b2"])
    wrong = _stack(db, world, world["b1"], {"assembly", "receive"})
    right = _stack(db, world, world["b2"], {"assembly", "receive"})
    T.set_bench_stack(db, world["b2"], wrong)
    d, old = _program(db, world, world["b2"], 36)
    assert old.origin_run_id == world["b1"].id
    res = T.swap_twin(db, world["b2"], device_ids=[d.id], stack=right, dry_run=False)
    new = db.get(M.Twin, res["to_twin"])
    assert (new.device_unit_id, new.origin_run_id, "program" in T.done_steps(db, [new.id])[new.id]) == (
        d.id, world["b2"].id, True)
    assert (old.device_unit_id, old.run_id, old.stack_key) == (None, world["b1"].id, "assembly|receive")
    T.record_marking(db, d, laser=False, label=True)
    with pytest.raises(HTTPException) as e:   # a step after naming follows the board
        T.swap_twin(db, world["b2"], device_ids=[d.id], stack=wrong, dry_run=True)
    assert "steps after it was named" in str(e.value.detail)


def test_a_marking_run_on_the_wrong_device_moves_with_its_steps(db, world):
    stack = _received(db, world, 2)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=2, dry_run=False)
    T.set_bench_stack(db, world["b1"], _stack(db, world, world["b1"], {"assembly", "receive", "enclose"}))
    d1, tw1 = _program(db, world, world["b1"], 37)
    d2, tw2 = _program(db, world, world["b1"], 38)
    run = M.ProgrammingRun(device_unit_id=d1.id, status="pass", results={"printed": True})
    db.add(run)
    db.flush()
    T.record_marking(db, d1, laser=False, label=True, programming_run_id=run.id)
    res = T.relink_run(db, world["b1"], programming_run_id=run.id, device_ids=[d2.id], dry_run=False)
    assert res["steps"] == ["Barcode label"] and run.device_unit_id == d2.id
    assert "label" in T.done_steps(db, [tw2.id])[tw2.id]
    assert "label" not in T.done_steps(db, [tw1.id])[tw1.id] and "label" not in tw1.stack_key


def test_the_bench_says_once_that_it_programs_another_batch_s_boards(db, world):
    T.set_bench_stack(db, world["b2"], _received(db, world, 2))
    codes = [n["code"] for n in bench_checks._about_the_batch(db, world["b2"], _device(db, world, 39),
                                                              created=True)]
    assert "stack_of_other_batch" in codes
    _program(db, world, world["b2"], 40)
    codes = [n["code"] for n in bench_checks._about_the_batch(db, world["b2"], _device(db, world, 41),
                                                              created=True)]
    assert "stack_of_other_batch" not in codes


def test_origin_cost_no_twin_carries_blocks_the_close(db, world):
    from app.routers import production_runs as prr

    stack = _received(db, world, 1)
    T.scrap(db, world["b1"], stack=stack, qty=1, reason="dropped", dry_run=False)
    share = T.origin_shares(db, [world["b1"].id])[world["b1"].id]
    assert share["twins"] == 0 and share["uncarried_usd"] == pytest.approx(120.0, abs=0.01)
    with pytest.raises(HTTPException) as e:
        prr.close_run(world["b1"].id, db=db)
    assert e.value.status_code == 409 and "no device carries" in e.value.detail


def test_a_whole_step_link_pays_for_the_clicks_recorded_after_it(db, world):
    from app.routers import process as pr

    stack = _received(db, world, 2)
    T.set_bench_stack(db, world["b1"], stack)
    fee = _line(db, world, world["b1"], "final:device", 20.0, "programming fee")
    res = pr.craft_costs(world["b1"].id, pr.CostsIn(step_keys=["program"], line_ids=[fee.id], dry_run=False),
                         db=db)
    _program(db, world, world["b1"], 42)
    _program(db, world, world["b1"], 43)
    links = (db.query(M.CostLineStep).join(M.StepRun, M.StepRun.id == M.CostLineStep.step_run_id)
             .filter(M.CostLineStep.line_id == fee.id, M.StepRun.step_key == "program").count())
    assert links == 2
    with pytest.raises(HTTPException) as e:
        _undo(db, res["batch_id"], dry=True)
    assert "linked 2 later click(s)" in str(e.value.detail)


def test_a_column_added_later_does_not_block_an_older_undo(db, world):
    from app.services import journal as J

    T.receive(db, world["b1"], qty=2, made_at="2026-02-01", dry_run=False)
    rec = _record(db, world["b1"])
    rows = db.query(M.WriteBatchRow).filter_by(batch_id=rec["batch_id"], table_name="twin_steps").all()
    assert rows
    for r in rows:   # as if the batch were written before the two columns existed
        ts = db.get(M.TwinStep, r.row_id)
        d = {k: v for k, v in J._row_dict(ts).items() if k not in ("programming_run_id", "deployment_version_id")}
        r.after_hash = J._hash(d)
    db.flush()
    assert _undo(db, rec["batch_id"], dry=True)["status"] == "would_reverse"


def test_a_spare_programmed_after_a_rebuild_shares_its_whole_step_position(db, world):
    from app.services import twin_rebuild as R

    run, _devices = _legacy_batch(db, world, 2, first=70)
    R.rebuild(db, run, version_id=world["v"].id, costs={"final:device": ["program"]},
              spares=[{"qty": 1, "done": [], "note": "a bare board on the shelf"}], dry_run=False)
    li = (db.query(M.RunCostLine).join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
          .filter(M.RunCostLine.label == "device assembly", M.RunCostDocument.run_id == run.id).one())
    T.set_bench_stack(db, run, _stack(db, world, run, {"assembly", "receive"}))
    _d, tw = _program(db, world, run, 72)
    assert tw is not None
    clicks = {sid for (sid,) in db.query(M.CostLineStep.step_run_id).filter_by(line_id=li.id)}
    assert any(tw.id in {t for (t,) in db.query(M.TwinStep.twin_id).filter_by(step_run_id=c)} for c in clicks)
    R.undo(db, run, dry_run=False)
    db.expire_all()
    assert db.query(M.CostLineStep).filter_by(line_id=li.id).count() == 0
    assert db.query(M.CostLineStepKey).filter_by(line_id=li.id).count() == 0


# ------------------------------------------------ review fixes (decision 0074)

def _two_piles(db, world):
    """B1 has one received board, B2 two; B2's bench took B1's pile by mistake."""
    T.receive(db, world["b1"], qty=1, made_at="2026-02-01", dry_run=False)
    _assemble(db, world["b1"])
    T.receive(db, world["b2"], qty=2, made_at="2026-03-01", dry_run=False)
    _assemble(db, world["b2"])
    return (_stack(db, world, world["b1"], {"assembly", "receive"}),
            _stack(db, world, world["b2"], {"assembly", "receive"}))


def test_a_swap_to_an_older_pile_and_its_undo_never_collide(db, world):
    from app.routers import process as pr

    b1_pile, b2_pile = _two_piles(db, world)
    T.set_bench_stack(db, world["b1"], b2_pile)   # the newer batch's boards, by mistake
    d, old = _program(db, world, world["b1"], 80)
    res = pr.craft_swap(world["b1"].id, pr.SwapIn(device_ids=[d.id], stack=b1_pile, dry_run=False), db=db)
    new = db.get(M.Twin, res["to_twin"])
    assert new.id < old.id and new.device_unit_id == d.id
    _undo(db, res["batch_id"])
    db.expire_all()
    assert db.get(M.Twin, old.id).device_unit_id == d.id and db.get(M.Twin, new.id).device_unit_id is None


def test_an_undo_never_unfinishes_a_unit_that_left(db, world):
    from app.routers import process as pr

    d, _tw = _crafted_device(db, world, 81)
    for k in ("laser", "label"):
        T.apply_step(db, world["b1"], step_key=k, device_ids=[d.id], chosen="list", stated="test", dry_run=False)
    for k in ("uvprint", "carton"):
        T.apply_step(db, world["b1"], step_key=k, device_ids=[d.id], chosen="list", dry_run=False)
    fin = pr.craft_finish(world["b1"].id, pr.FinishIn(device_ids=[d.id], chosen="list", dry_run=False), db=db)
    osvc.record_event(db, d, "shipped")
    with pytest.raises(HTTPException) as e:
        _undo(db, fin["batch_id"], dry=True)
    assert "stays finished" in str(e.value.detail)


def test_a_reopened_unit_can_take_its_steps_again_and_finish(db, world):
    d, tw = _crafted_device(db, world, 82)
    for k in ("laser", "label"):
        T.apply_step(db, world["b1"], step_key=k, device_ids=[d.id], chosen="list", stated="test", dry_run=False)
    for k in ("uvprint", "carton"):
        T.apply_step(db, world["b1"], step_key=k, device_ids=[d.id], chosen="list", dry_run=False)
    T.finish(db, world["b1"], device_ids=[d.id], chosen="list", dry_run=False)
    T.reopen(db, world["b1"], device_ids=[d.id], chosen="list", reason="new label", dry_run=False)
    T.apply_step(db, world["b1"], step_key="label", device_ids=[d.id], chosen="list", stated="relabelled",
                 dry_run=False)
    assert T.finish(db, world["b1"], device_ids=[d.id], chosen="list", dry_run=False)["units"] == 1
    assert tw.status == "finished"


def test_the_ledger_leaves_a_rebuild_to_undo_rebuild(db, world):
    from app.services import twin_rebuild as R

    run, _devices = _legacy_batch(db, world, 2, first=84)
    R.rebuild(db, run, version_id=world["v"].id, dry_run=False)
    wb = db.query(M.WriteBatch).filter_by(kind="craft.rebuild", source_ref=f"run:{run.id}").one()
    with pytest.raises(HTTPException) as e:
        _undo(db, wb.id, dry=True)
    assert "Undo rebuild" in str(e.value.detail)


def test_an_undone_unlink_that_a_new_link_replaced_waits_for_it(db, world):
    from app.routers import process as pr

    stack = _received(db, world, 2)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=2, dry_run=False)
    fee = _line(db, world, world["b1"], "final:device", 10.0, "enclose fee")
    pr.craft_costs(world["b1"].id, pr.CostsIn(step_keys=["enclose"], line_ids=[fee.id], dry_run=False), db=db)
    off = pr.craft_costs(world["b1"].id, pr.CostsIn(line_ids=[fee.id], unlink=True, dry_run=False), db=db)
    again = pr.craft_costs(world["b1"].id, pr.CostsIn(step_keys=["enclose"], line_ids=[fee.id], dry_run=False),
                           db=db)
    with pytest.raises(HTTPException) as e:
        _undo(db, off["batch_id"], dry=True)
    assert f"reverse {again['batch_id']} first" in str(e.value.detail)


def test_a_whole_step_link_reaches_the_assembly_click_and_stops_at_a_recharge(db, world):
    T.receive(db, world["b1"], qty=2, made_at="2026-02-01", dry_run=False)
    fee = _line(db, world, world["b1"], "final:device", 5.0, "assembly handling")
    T.link_costs(db, world["b1"], step_run_ids=None, step_keys=["assembly"], line_ids=[fee.id], dry_run=False)
    sr, _res = T.apply_assembly(db, world["b1"])
    assert db.query(M.CostLineStep).filter_by(line_id=fee.id, step_run_id=sr.id).count() == 1
    other = _line(db, world, world["b1"], "final:device", 7.0, "program fee")
    T.link_costs(db, world["b1"], step_run_ids=None, step_keys=["program"], line_ids=[other.id], dry_run=False)
    other.run_id = world["b2"].id   # re-charged to another batch
    db.flush()
    T.set_bench_stack(db, world["b1"], _stack(db, world, world["b1"], {"assembly", "receive"}))
    _program(db, world, world["b1"], 85)
    assert db.query(M.CostLineStep).filter_by(line_id=other.id).count() == 0


def test_a_merge_names_the_run_that_programmed_the_board(db, world):
    stack = _received(db, world, 1)
    d, tw = _program(db, world, world["b1"], 86)   # no stack selected: a gap
    flash = _deployment(db, world, "test-merge-flash", "flash")
    dv = M.DeploymentVersion(deployment_id=flash.id, version_no=1, status="published")
    db.add(dv)
    db.flush()
    erase = M.ProgrammingRun(device_unit_id=d.id, status="pass", action="erase", deployment_version_id=dv.id)
    run = M.ProgrammingRun(device_unit_id=d.id, status="pass", deployment_version_id=dv.id,
                           production_run_id=world["b1"].id)
    db.add_all([erase, run])
    db.flush()
    T.merge(db, world["b1"], stack=stack, device_ids=[d.id], chosen="list", dry_run=False)
    tw = db.query(M.Twin).filter_by(device_unit_id=d.id).one()
    j = T.twin_json(db, tw)
    assert next(s for s in j["steps"] if s["step"] == "program")["programming_run_id"] == run.id
    assert j["reflashes"] == []


def test_relink_refuses_a_finished_source_and_another_project(db, world):
    stack = _received(db, world, 2)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=2, dry_run=False)
    T.set_bench_stack(db, world["b1"], _stack(db, world, world["b1"], {"assembly", "receive", "enclose"}))
    d1, tw1 = _program(db, world, world["b1"], 87)
    d2, _tw2 = _program(db, world, world["b1"], 88)
    run = M.ProgrammingRun(device_unit_id=d1.id, status="pass", results={"printed": True})
    db.add(run)
    db.flush()
    T.record_marking(db, d1, laser=False, label=True, programming_run_id=run.id)
    tw1.status = "finished"
    with pytest.raises(HTTPException) as e:
        T.relink_run(db, world["b1"], programming_run_id=run.id, device_ids=[d2.id], dry_run=True)
    assert "reopen it first" in str(e.value.detail)


def test_scrapping_a_named_unit_with_no_recorded_state(db, world):
    d, tw = _crafted_device(db, world, 89)
    d.state = ""
    res = T.scrap(db, world["b1"], device_ids=[d.id], chosen="list", reason="burnt", dry_run=False)
    assert tw.status == "scrapped" and res["disposed"] == 0


# ---------------------------------------- second review regressions (0074, 0075)


def test_a_smaller_draw_gives_back_its_newest_lots_while_lot_pricing_is_off(db, world, monkeypatch):
    """Review R2-7 (decision 0073): with the switch off, a smaller draw still
    gives back its newest bindings, so no draw holds more lots than units, and
    keeps its price; a larger one changes no binding."""
    from app.config import settings
    from app.routers import run_costs as rc
    from app.services import lots as L

    monkeypatch.setattr(settings, "lot_pricing", False)
    st = world["sticker"]
    a = db.query(M.RunCostLine).filter_by(component_id=st.id, unit_price=0.2).one()
    doc = M.RunCostDocument(project_id=world["project"].id, doc_type="invoice", supplier="TESTCO",
                            doc_number="T-0002", doc_date="2026-01-20", currency="USD", total_amount=40.0)
    db.add(doc)
    db.flush()
    b = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=st.id, mpn="", lcsc="",
                      qty=100, unit_price=0.4, position=0)
    db.add(b)
    db.flush()
    plain = M.ProductionRun(project_id=world["project"].id, label="TB-plain", run_date="2026-02-01", qty=1)
    db.add(plain)
    db.flush()

    def used(q):
        return rc.set_used_qty(plain.id, rc.ConsumptionIn(component_id=st.id, qty=q, consumed_at="2026-02-01"),
                               db=db)

    def bound():
        return [(x.lot_line_id, x.qty) for x in db.query(M.ComponentConsumptionLot)
                .filter_by(consumption_id=c.id).order_by(M.ComponentConsumptionLot.id)]

    c = db.get(M.ComponentConsumption, used(120)["id"])
    # bound oldest first, as the history job binds a draw made while the switch is off
    L.bind(db, c, L.FifoPicker(db).pick(st.id, "", "", 120, "2026-02-01"), source="fifo_history")
    unit = c.unit_cost_usd
    assert bound() == [(a.id, 100), (b.id, 20)]
    used(90)
    assert bound() == [(a.id, 90)] and c.unit_cost_usd == pytest.approx(unit)
    lots = L.lot_state(db)["lots"]
    assert (lots[f"L{a.id}"]["qty_remaining"], lots[f"L{b.id}"]["qty_remaining"]) == (
        pytest.approx(10), pytest.approx(100))
    used(110)
    assert bound() == [(a.id, 90)] and c.unit_cost_usd == pytest.approx(unit)


def test_a_reopen_never_reuses_a_bench_run_from_before_it(db, world):
    """Review R2-9 (decision 0074): after a reopen, catch-up takes no run that
    is already behind a step of the twin, nor one started before the reopen."""
    d, tw = _crafted_device(db, world, 93)
    b1 = world["b1"]
    used = M.ProgrammingRun(device_unit_id=d.id, status="pass", operator="tester",
                            results={"marked": "X", "printed": "X"}, started_at=datetime(2026, 2, 10, tzinfo=UTC))
    db.add(used)
    db.flush()
    assert T.record_marking(db, d, laser=True, label=True, programming_run_id=used.id) == ["laser", "label"]
    spare = M.ProgrammingRun(device_unit_id=d.id, status="pass", operator="tester", results={"printed": "Y"},
                             started_at=datetime(2026, 2, 11, tzinfo=UTC))
    db.add(spare)
    db.flush()
    assert T.record_marking(db, d, laser=False, label=True, programming_run_id=spare.id) == []   # already done
    for k in ("uvprint", "carton"):
        T.apply_step(db, b1, step_key=k, device_ids=[d.id], chosen="list", dry_run=False)
    T.finish(db, b1, device_ids=[d.id], chosen="list", dry_run=False)
    T.reopen(db, b1, device_ids=[d.id], chosen="list", reason="new carton", dry_run=False)
    plan = T.apply_step(db, b1, step_key="carton", device_ids=[d.id], chosen="list", dry_run=False)
    assert plan["caught_up"] == []
    marks = (db.query(M.StepRun).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
             .filter(M.TwinStep.twin_id == tw.id, M.StepRun.step_key.in_(["laser", "label"])).count())
    assert marks == 2


def test_a_re_split_keeps_the_step_links_of_the_children_it_adds_to_or_replaces(db, world):
    """Review R2-11 (decision 0074): after the first split the whole-step key
    and the later clicks sit on the children, so a re-split takes them from
    the live siblings too, and the voided children keep no key."""
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 4))
    fee = _line(db, world, b1, "final:device", 100.0, "final assembler")
    T.link_costs(db, b1, step_run_ids=None, step_keys=["program"], line_ids=[fee.id], dry_run=False)
    _program(db, world, b1, 94)

    def child(label, amount):
        return rc.ChildIn(label=label, amount=amount, plan_key="final:device", run_id=b1.id)

    def links(li):
        return ({s for (s,) in db.query(M.CostLineStep.step_run_id).filter_by(line_id=li.id)},
                [k.step_key for k in db.query(M.CostLineStepKey).filter_by(line_id=li.id)])

    def clicks():
        return {sr.id for sr in db.query(M.StepRun).filter_by(run_id=b1.id, step_key="program")}

    rc.split_line_core(fee.id, rc.SplitIn(children=[child("a", 50), child("b", 30)]), db)
    _program(db, world, b1, 95)   # recorded after the split: linked to the children only
    rc.split_line_core(fee.id, rc.SplitIn(children=[child("c", 20)]), db)
    c = db.query(M.RunCostLine).filter_by(parent_line_id=fee.id, label="c").one()
    assert links(c) == (clicks(), ["program"])
    old = [li.id for li in db.query(M.RunCostLine).filter_by(parent_line_id=fee.id)]
    rc.split_line_core(fee.id, rc.SplitIn(replace=True, children=[child("x", 70), child("y", 30)]), db)
    _program(db, world, b1, 96)
    live = db.query(M.RunCostLine).filter(M.RunCostLine.parent_line_id == fee.id,
                                          M.RunCostLine.voided_at.is_(None)).all()
    assert sorted(li.label for li in live) == ["x", "y"] and len(clicks()) == 3
    assert all(links(li) == (clicks(), ["program"]) for li in live)
    assert db.query(M.CostLineStepKey).filter(M.CostLineStepKey.line_id.in_(old)).count() == 0


def test_only_a_flash_pass_names_the_program_step_or_reads_as_a_reflash(db, world):
    """Review R2-12 (decision 0074): an erase, a marking or test run and a
    hand-typed record are no programming pass; at a merge the batch's own
    pass names the program step."""
    pid = world["project"].id
    ver = {k: M.DeploymentVersion(deployment_id=db.query(M.Deployment).filter_by(project_id=pid, kind=k).one().id,
                                  version_no=1, status="published", steps=[]) for k in ("flash", "mark", "test")}
    db.add_all(ver.values())
    db.flush()
    stack = _received(db, world, 2)

    def run(dev, day, *, action="program", kind=None, batch=None):
        r = M.ProgrammingRun(device_unit_id=dev.id, status="pass", action=action,
                             deployment_version_id=ver[kind].id if kind else None,
                             production_run_id=batch.id if batch else None,
                             started_at=datetime(2026, 2, day, 9, tzinfo=UTC))
        db.add(r)
        db.flush()
        return r

    d = _device(db, world, 97)
    run(d, 3, action="erase")
    run(d, 4)                                      # typed by hand: no deployment version
    run(d, 5, kind="mark", batch=world["b1"])
    mine = run(d, 6, kind="flash", batch=world["b1"])
    run(d, 7, kind="test", batch=world["b1"])
    osvc.mark_produced(db, d, world["b1"].id, actor="test")
    e = _device(db, world, 98)
    run(e, 3, kind="flash", batch=world["b2"])     # an older pass on another batch's bench
    ours = run(e, 6, kind="flash", batch=world["b1"])
    # the run that produced it is the latest pass at or before its "produced"
    osvc.mark_produced(db, e, world["b1"].id, at=datetime(2026, 2, 6, 10, tzinfo=UTC), actor="test")
    db.flush()
    T.merge(db, world["b1"], stack=stack, device_ids=[d.id, e.id], chosen="list", dry_run=False)

    def program_run(dev):
        j = T.twin_json(db, db.query(M.Twin).filter_by(device_unit_id=dev.id).one())
        return next(s for s in j["steps"] if s["step"] == "program")["programming_run_id"], j["reflashes"]

    assert program_run(d) == (mine.id, [])
    assert program_run(e)[0] == ours.id
    again = run(d, 20, kind="flash", batch=world["b1"])
    assert [r["programming_run_id"] for r in program_run(d)[1]] == [again.id]


def test_relink_refuses_another_project_s_run_and_a_device_s_programming_pass(db, world):
    """Review R2-13 (decision 0074): a run whose batch, deployment or device
    belongs to another project stays where it is, and so does the passing
    flash run of a device that was produced."""
    b1 = world["b1"]
    stack = _received(db, world, 2)
    T.apply_step(db, b1, step_key="enclose", stack=stack, qty=2, dry_run=False)
    T.set_bench_stack(db, b1, _stack(db, world, b1, {"assembly", "receive", "enclose"}))
    right, _tw = _program(db, world, b1, 99)
    other = M.Project(name="test-twins-other", git_url="https://example.invalid/o.git")
    db.add(other)
    db.flush()
    ob = M.ProductionRun(project_id=other.id, label="TO1", run_date="2026-02-01", status="completed", qty=1)
    odep = M.Deployment(project_id=other.id, name="test-other-flash", kind="flash")
    db.add_all([ob, odep])
    db.flush()
    odv = M.DeploymentVersion(deployment_id=odep.id, version_no=1, status="published")
    odev = M.DeviceUnit(project_id=other.id, serial="TO0001", mac="00:00:00:00:to:01")
    db.add_all([odv, odev])
    db.flush()
    flash = db.query(M.Deployment).filter_by(project_id=world["project"].id, kind="flash").one()
    fv = M.DeploymentVersion(deployment_id=flash.id, version_no=1, status="published")
    db.add(fv)
    db.flush()
    b1.bench_stack = ""
    gap = _device(db, world, 100)
    runs = [M.ProgrammingRun(device_unit_id=None, status="pass", production_run_id=ob.id),
            M.ProgrammingRun(device_unit_id=None, status="pass", deployment_version_id=odv.id),
            M.ProgrammingRun(device_unit_id=odev.id, status="pass", action="erase"),
            M.ProgrammingRun(device_unit_id=gap.id, status="pass", production_run_id=b1.id,
                             deployment_version_id=fv.id)]
    db.add_all(runs)
    db.flush()
    osvc.mark_produced(db, gap, b1.id, actor="test")
    db.flush()
    for pr, why in zip(runs, ["another project"] * 3 + ["programmed its device"]):
        with pytest.raises(HTTPException) as e:
            T.relink_run(db, b1, programming_run_id=pr.id, device_ids=[right.id], dry_run=True)
        assert e.value.status_code == 409 and why in str(e.value.detail)
    assert runs[3].device_unit_id == gap.id and runs[0].device_unit_id is None


def test_a_whole_step_unlink_is_undone_and_a_click_made_while_unlinked_still_blocks(db, world):
    from app.routers import process as pr

    stack = _received(db, world, 3)
    plan = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=2, dry_run=False)
    fee = _line(db, world, world["b1"], "final:device", 10.0, "enclose fee")
    pr.craft_costs(world["b1"].id, pr.CostsIn(step_keys=["enclose"], line_ids=[fee.id], dry_run=False), db=db)
    off = pr.craft_costs(world["b1"].id, pr.CostsIn(line_ids=[fee.id], unlink=True, dry_run=False), db=db)
    assert db.query(M.CostLineStep).filter_by(line_id=fee.id).count() == 0
    # the click whose link this unlink removed is no gap: the undo puts the link back
    assert _undo(db, off["batch_id"], dry=True)["status"] == "would_reverse"
    assert _undo(db, off["batch_id"])["status"] == "reversed"
    db.expire_all()
    assert [x.step_run_id for x in db.query(M.CostLineStep).filter_by(line_id=fee.id)] == [plan["step_run_id"]]
    assert [(k.run_id, k.step_key) for k in db.query(M.CostLineStepKey).filter_by(line_id=fee.id)] == [
        (world["b1"].id, "enclose")]
    # a click recorded while the position is unlinked still is one
    again = pr.craft_costs(world["b1"].id, pr.CostsIn(line_ids=[fee.id], unlink=True, dry_run=False), db=db)
    T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=1, dry_run=False)
    with pytest.raises(HTTPException) as e:
        _undo(db, again["batch_id"], dry=True)
    assert "1 click(s) of step 'enclose' were recorded while the position was unlinked" in str(e.value.detail)


def test_an_undo_of_a_redo_on_a_closed_batch_is_refused(db, world):
    from app.routers import process as pr

    stack = _received(db, world, 2)
    plan = T.apply_step(db, world["b1"], step_key="enclose", stack=stack, qty=2, dry_run=False)
    fee = _line(db, world, world["b1"], "final:device", 10.0, "enclose fee")
    link = pr.craft_costs(world["b1"].id, pr.CostsIn(step_run_ids=[plan["step_run_id"]], line_ids=[fee.id],
                                                     dry_run=False), db=db)
    from app.services import journal as J

    undone = _undo(db, link["batch_id"])
    db.expire_all()
    redone = J.reverse(db, undone["reverse_batch_id"], dry_run=False)   # the service still can
    db.expire_all()
    world["b1"].closed_at = datetime(2026, 3, 1, tzinfo=UTC)
    db.flush()
    blockers = J.check_reversible(db, db.get(M.WriteBatch, redone["reverse_batch_id"]))["blockers"]
    assert any("TB1 is closed" in b for b in blockers)
    assert db.query(M.CostLineStep).filter_by(line_id=fee.id).count() == 1


def test_an_undo_that_would_put_back_a_link_to_a_removed_click_is_refused(db, world):
    from app.routers import process as pr

    stack = _received(db, world, 2)
    step = pr.craft_step(world["b1"].id, pr.StepIn(step_key="enclose", stack=stack, qty=2, dry_run=False), db=db)
    fee = _line(db, world, world["b1"], "final:device", 10.0, "enclose fee")
    pr.craft_costs(world["b1"].id, pr.CostsIn(step_run_ids=[step["step_run_id"]], line_ids=[fee.id], dry_run=False),
                   db=db)
    off = pr.craft_costs(world["b1"].id, pr.CostsIn(line_ids=[fee.id], unlink=True, dry_run=False), db=db)
    _undo(db, step["batch_id"])   # nothing points at the click any more, so it goes
    db.expire_all()
    assert db.get(M.StepRun, step["step_run_id"]) is None
    # the dry run and the real call agree: a 409 naming the missing click, never a 500
    for dry in (True, False):
        with pytest.raises(HTTPException) as e:
            _undo(db, off["batch_id"], dry=dry)
        assert e.value.status_code == 409
        assert f"pointed at step_runs#{step['step_run_id']}, which no longer exists" in str(e.value.detail)


def test_the_ledger_never_redoes_an_undone_rebuild(db, world):
    from app.services import twin_rebuild as R

    run, _devices = _legacy_batch(db, world, 2, first=92)
    R.rebuild(db, run, version_id=world["v"].id, dry_run=False)
    rb = db.query(M.WriteBatch).filter_by(kind="craft.rebuild", source_ref=f"run:{run.id}").one()
    R.undo(db, run, dry_run=False)
    db.expire_all()
    redo = db.query(M.WriteBatch).filter_by(kind="reverse", source_ref=f"batch:{rb.id}").one()
    for dry in (True, False):
        with pytest.raises(HTTPException) as e:
            _undo(db, redo.id, dry=dry)
        assert e.value.status_code == 409 and "Undo rebuild" in str(e.value.detail)
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0


# ------------------------------------------ the final check's regressions (0074)

def test_the_run_named_in_the_produced_note_produced_the_device(db, world):
    flash = db.query(M.Deployment).filter_by(project_id=world["project"].id, kind="flash").one()
    v1, v2 = (M.DeploymentVersion(deployment_id=flash.id, version_no=n, status="published") for n in (1, 2))
    db.add_all([v1, v2])
    db.flush()
    stack = _received(db, world, 1)
    d = _device(db, world, 120)
    trial = M.ProgrammingRun(device_unit_id=d.id, status="pass", deployment_version_id=v2.id,
                             started_at=datetime(2026, 2, 5, 9, tzinfo=UTC))
    ours = M.ProgrammingRun(device_unit_id=d.id, status="pass", deployment_version_id=v1.id,
                            production_run_id=world["b1"].id, started_at=datetime(2026, 2, 5, 11, tzinfo=UTC))
    db.add_all([trial, ours])
    db.flush()
    # as the engine writes it: no `at`, so it is stamped with the first sighting
    osvc.mark_produced(db, d, world["b1"].id, actor="test", note=f"passed programming run #{ours.id}")
    assert T.production_pass(db, d.id).id == ours.id
    T.merge(db, world["b1"], stack=stack, device_ids=[d.id], chosen="list", dry_run=False)
    j = T.twin_json(db, db.query(M.Twin).filter_by(device_unit_id=d.id).one())
    assert next(s for s in j["steps"] if s["step"] == "program")["programming_run_id"] == ours.id
    assert j["reflashes"] == []


def test_a_scrap_is_undone_after_the_bench_read_the_unit_again(db, world):
    from app.routers import process as pr

    d, tw = _crafted_device(db, world, 121)
    res = pr.craft_scrap(world["b1"].id, pr.ScrapIn(device_ids=[d.id], chosen="list", reason="cracked",
                                                    dry_run=False), db=db)
    d.chip, d.last_seen, d.last_status = "ESP32-C6 (rev 0.1)", datetime(2026, 10, 5, 9, tzinfo=UTC), "pass"
    db.flush()
    _undo(db, res["batch_id"])
    db.expire_all()
    d = db.get(M.DeviceUnit, d.id)
    assert (d.state, d.chip, db.get(M.Twin, tw.id).status) == ("in_stock", "ESP32-C6 (rev 0.1)", "active")


def test_a_whole_step_link_split_since_is_unlinked_not_undone(db, world):
    from app.routers import process as pr
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 3))
    fee = _line(db, world, b1, "final:device", 100.0, "final assembler")
    link = pr.craft_costs(b1.id, pr.CostsIn(step_keys=["program"], line_ids=[fee.id], dry_run=False), db=db)
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=60, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="b", amount=40, plan_key="final:device", run_id=b1.id)]), db)
    with pytest.raises(HTTPException) as e:
        _undo(db, link["batch_id"], dry=True)
    assert "split since" in str(e.value.detail)
    # the header follows its children: unlinked on the batch screen, all of it goes
    T.link_costs(db, b1, step_run_ids=None, line_ids=[fee.id], unlink=True, dry_run=False)
    kids = [li.id for li in db.query(M.RunCostLine).filter_by(parent_line_id=fee.id)]
    assert db.query(M.CostLineStepKey).filter(M.CostLineStepKey.line_id.in_(kids + [fee.id])).count() == 0


def test_a_split_header_keeps_every_click_and_carries_no_share(db, world):
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 3))
    fee = _line(db, world, b1, "final:device", 100.0, "final assembler")
    T.link_costs(db, b1, step_run_ids=None, step_keys=["program"], line_ids=[fee.id], dry_run=False)
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=60, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="b", amount=40, plan_key="final:device", run_id=b1.id)]), db)
    _program(db, world, b1, 122)
    _program(db, world, b1, 123)
    clicks = set(T.step_clicks(db, b1.id, "program"))
    header = {s for (s,) in db.query(M.CostLineStep.step_run_id).filter_by(line_id=fee.id)}
    assert len(clicks) == 2 and header == clicks
    kids = {li.id for li in db.query(M.RunCostLine).filter_by(parent_line_id=fee.id)}
    shares = {sh["line"].id: sh["usd"] for sh in T.line_shares(db, [b1.id])}
    assert fee.id not in shares and sum(v for k, v in shares.items() if k in kids) == pytest.approx(100.0)


def test_a_click_undo_survives_a_split_of_the_position_it_paid_for(db, world):
    from app.routers import process as pr
    from app.routers import run_costs as rc

    stack = _received(db, world, 2)
    step = pr.craft_step(world["b1"].id, pr.StepIn(step_key="enclose", stack=stack, qty=2, dry_run=False), db=db)
    fee = _line(db, world, world["b1"], "final:device", 10.0, "enclose fee")
    T.link_costs(db, world["b1"], step_run_ids=[step["step_run_id"]], line_ids=[fee.id], dry_run=False)
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=6, plan_key="final:device", run_id=world["b1"].id),
        rc.ChildIn(label="b", amount=4, plan_key="final:device", run_id=world["b1"].id)]), db)
    # the click's links: the fee's own (not journalled) and the split's copies
    assert _undo(db, step["batch_id"], dry=True)["status"] == "would_reverse"


def test_linking_a_split_position_is_undone_and_listed_once(db, world):
    from app.routers import process as pr
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 2))
    _program(db, world, b1, 124)
    fee = _line(db, world, b1, "final:device", 100.0, "final assembler")
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=60, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="b", amount=40, plan_key="final:device", run_id=b1.id)]), db)
    link = pr.craft_costs(b1.id, pr.CostsIn(step_keys=["program"], line_ids=[fee.id], dry_run=False), db=db)
    rows = [r for r in T.craft_view(db, b1)["linked"] if r["line_id"] == fee.id]
    assert len(rows) == 1 and rows[0]["usd"] == pytest.approx(100.0) and rows[0]["whole_steps"] == ["program"]
    assert _undo(db, link["batch_id"], dry=True)["status"] == "would_reverse"


def test_the_assembly_card_counts_live_positions_only(db, world):
    from app.routers import run_costs as rc

    T.receive(db, world["b1"], qty=2, made_at="2026-02-01", dry_run=False)
    _record(db, world["b1"], line_ids=[db.query(M.RunCostLine).filter_by(label="SMT assembly").one().id])
    smt = db.query(M.RunCostLine).filter_by(label="SMT assembly").one()
    rc.split_line_core(smt.id, rc.SplitIn(children=[
        rc.ChildIn(label="stencil", amount=30, plan_key="pcba:smt", run_id=world["b1"].id),
        rc.ChildIn(label="smt", amount=70, plan_key="pcba:smt", run_id=world["b1"].id)]), db)
    rc.split_line_core(smt.id, rc.SplitIn(replace=True, children=[
        rc.ChildIn(label="all", amount=100, plan_key="pcba:smt", run_id=world["b1"].id)]), db)
    rec = T.assembly_draft(db, world["b1"])["recorded"]
    assert [x["label"] for x in rec["lines"]] == ["all"]
    assert T.craft_view(db, world["b1"])["assembly"]["lines"] == 1


# ------------------------------------------------ the dry round (decision 0074)

def test_a_redo_puts_back_a_keyed_click_and_its_links(db, world):
    from app.routers import process as pr

    stack = _received(db, world, 3)
    fee = _line(db, world, world["b1"], "final:device", 30.0, "enclose fee")
    pr.craft_costs(world["b1"].id, pr.CostsIn(step_keys=["enclose"], line_ids=[fee.id], dry_run=False), db=db)
    step = pr.craft_step(world["b1"].id, pr.StepIn(step_key="enclose", stack=stack, qty=3, dry_run=False), db=db)
    from app.services import journal as J

    undo = _undo(db, step["batch_id"])
    with pytest.raises(HTTPException) as e:      # the Write log never redoes a click
        _undo(db, undo["reverse_batch_id"], dry=True)
    assert "not redone here" in str(e.value.detail)
    J.reverse(db, undo["reverse_batch_id"], dry_run=False)   # the journal itself puts it back, parents first
    db.expire_all()
    assert db.query(M.CostLineStep).filter_by(line_id=fee.id, step_run_id=step["step_run_id"]).count() == 1


def test_a_redo_keeps_the_split_copies_of_a_click_s_links(db, world):
    from app.routers import process as pr
    from app.routers import run_costs as rc

    stack = _received(db, world, 2)
    step = pr.craft_step(world["b1"].id, pr.StepIn(step_key="enclose", stack=stack, qty=2, dry_run=False), db=db)
    fee = _line(db, world, world["b1"], "final:device", 10.0, "enclose fee")
    T.link_costs(db, world["b1"], step_run_ids=[step["step_run_id"]], line_ids=[fee.id], dry_run=False)
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=6, plan_key="final:device", run_id=world["b1"].id),
        rc.ChildIn(label="b", amount=4, plan_key="final:device", run_id=world["b1"].id)]), db)
    from app.services import journal as J

    before = db.query(M.CostLineStep).filter_by(step_run_id=step["step_run_id"]).count()
    undo = _undo(db, step["batch_id"])
    J.reverse(db, undo["reverse_batch_id"], dry_run=False)
    db.expire_all()
    assert db.query(M.CostLineStep).filter_by(step_run_id=step["step_run_id"]).count() == before == 3


def test_unlink_by_the_top_header_reaches_a_two_level_split(db, world):
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 2))
    _program(db, world, b1, 125)
    fee = _line(db, world, b1, "final:device", 100.0, "order")
    T.link_costs(db, b1, step_run_ids=None, step_keys=["program"], line_ids=[fee.id], dry_run=False)
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=60, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="b", amount=40, plan_key="final:device", run_id=b1.id)]), db)
    a = db.query(M.RunCostLine).filter_by(parent_line_id=fee.id, label="a").one()
    rc.split_line_core(a.id, rc.SplitIn(children=[
        rc.ChildIn(label="a1", amount=30, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="a2", amount=30, plan_key="final:device", run_id=b1.id)]), db)
    rows = [r for r in T.craft_view(db, b1)["linked"] if r["line_id"] == fee.id]
    assert len(rows) == 1 and rows[0]["usd"] == pytest.approx(100.0)
    T.link_costs(db, b1, step_run_ids=None, line_ids=[fee.id], unlink=True, dry_run=False)
    tree = [fee.id] + [li.id for li in db.query(M.RunCostLine).filter(M.RunCostLine.document_id == fee.document_id,
                                                                      M.RunCostLine.id > fee.id)]
    assert db.query(M.CostLineStep).filter(M.CostLineStep.line_id.in_(tree)).count() == 0
    assert db.query(M.CostLineStepKey).filter(M.CostLineStepKey.line_id.in_(tree)).count() == 0


def test_a_whole_step_link_with_no_click_yet_is_listed(db, world):
    _received(db, world, 2)
    fee = _line(db, world, world["b1"], "final:device", 50.0, "carton packing")
    T.link_costs(db, world["b1"], step_run_ids=None, step_keys=["carton"], line_ids=[fee.id], dry_run=False)
    rows = [r for r in T.craft_view(db, world["b1"])["linked"] if r["line_id"] == fee.id]
    assert len(rows) == 1 and rows[0]["whole_steps"] == ["carton"] and rows[0]["usd"] == 0


def test_a_split_with_a_share_in_another_batch_is_listed_by_this_batch_s_child(db, world):
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 2))
    _program(db, world, b1, 126)
    fee = _line(db, world, b1, "final:device", 100.0, "shared order")
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="ours", amount=60, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="theirs", amount=40, plan_key="final:device", run_id=world["b2"].id)]), db)
    ours = db.query(M.RunCostLine).filter_by(parent_line_id=fee.id, label="ours").one()
    T.link_costs(db, b1, step_run_ids=None, step_keys=["program"], line_ids=[ours.id], dry_run=False)
    rows = T.craft_view(db, b1)["linked"]
    assert [r["line_id"] for r in rows if r["line_id"] in (fee.id, ours.id)] == [ours.id]
    plan = T.link_costs(db, b1, step_run_ids=None, line_ids=[ours.id], unlink=True, dry_run=True)
    assert plan["refused"] == []


# --------------------------------------------- loop-until-dry round 2 (0074)

def test_a_redo_of_a_draw_the_stock_no_longer_holds_is_refused(db, world):
    from app.services import journal as J

    plain = M.ProductionRun(project_id=world["project"].id, label="TB-redo", run_date="2026-02-01", qty=1)
    db.add(plain)
    db.flush()
    with J.batch(db, kind="test.draw", source_ref=f"run:{plain.id}") as h:
        db.add(M.ComponentConsumption(run_id=plain.id, component_id=world["sticker"].id, mpn="", lcsc="", qty=60,
                                      unit_cost_usd=0.2, basis="hand", consumed_at="2026-02-01"))
    undo = J.reverse(db, h["batch_id"], dry_run=False)
    db.add(M.ComponentConsumption(run_id=plain.id, component_id=world["sticker"].id, mpn="", lcsc="", qty=60,
                                  unit_cost_usd=0.2, basis="hand", consumed_at="2026-02-02"))
    db.flush()
    blockers = J.check_reversible(db, db.get(M.WriteBatch, undo["reverse_batch_id"]))["blockers"]
    assert any("no longer holds" in b for b in blockers)


def test_an_unlink_by_this_batch_s_share_clears_the_header_above_it(db, world):
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 2))
    _program(db, world, b1, 127)
    fee = _line(db, world, b1, "final:device", 100.0, "shared order")
    T.link_costs(db, b1, step_run_ids=None, step_keys=["program"], line_ids=[fee.id], dry_run=False)
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="ours", amount=60, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="theirs", amount=40, plan_key="final:device", run_id=world["b2"].id)]), db)
    ours = db.query(M.RunCostLine).filter_by(parent_line_id=fee.id, label="ours").one()
    rows = {r["line_id"] for r in T.craft_view(db, b1)["linked"]}
    assert fee.id not in rows and ours.id in rows
    T.link_costs(db, b1, step_run_ids=None, line_ids=[ours.id], unlink=True, dry_run=False)
    assert db.query(M.CostLineStepKey).filter_by(line_id=fee.id, run_id=b1.id).count() == 0
    # a child added later gets nothing from the header
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="more", amount=0, plan_key="final:device", run_id=b1.id)]), db)
    more = db.query(M.RunCostLine).filter_by(parent_line_id=fee.id, label="more").one()
    assert db.query(M.CostLineStepKey).filter_by(line_id=more.id).count() == 0


def test_an_unlink_by_the_header_clears_its_voided_children(db, world):
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 2))
    _program(db, world, b1, 128)
    fee = _line(db, world, b1, "final:device", 100.0, "order")
    T.link_costs(db, b1, step_run_ids=None, step_keys=["program"], line_ids=[fee.id], dry_run=False)
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=60, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="b", amount=40, plan_key="final:device", run_id=b1.id)]), db)
    old = [li.id for li in db.query(M.RunCostLine).filter_by(parent_line_id=fee.id)]
    rc.split_line_core(fee.id, rc.SplitIn(replace=True, children=[
        rc.ChildIn(label="all", amount=100, plan_key="final:device", run_id=b1.id)]), db)
    T.link_costs(db, b1, step_run_ids=None, line_ids=[fee.id], unlink=True, dry_run=False)
    assert db.query(M.CostLineStep).filter(M.CostLineStep.line_id.in_(old)).count() == 0


# --------------------------------------------- loop-until-dry round 3 (0074)

def _shared_split(db, world, n):
    from app.routers import run_costs as rc

    b1 = world["b1"]
    T.set_bench_stack(db, b1, _received(db, world, 2))
    _program(db, world, b1, n)
    fee = _line(db, world, b1, "final:device", 100.0, "shared order")
    T.link_costs(db, b1, step_run_ids=None, step_keys=["program"], line_ids=[fee.id], dry_run=False)
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="ours1", amount=40, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="ours2", amount=30, plan_key="final:device", run_id=b1.id),
        rc.ChildIn(label="theirs", amount=30, plan_key="final:device", run_id=world["b2"].id)]), db)
    kid = {li.label: li for li in db.query(M.RunCostLine).filter_by(parent_line_id=fee.id)}
    return b1, fee, kid


def test_an_unlinked_share_leaves_the_unlink_list(db, world):
    b1, _fee, kid = _shared_split(db, world, 129)
    T.link_costs(db, b1, step_run_ids=None, line_ids=[kid["ours1"].id], unlink=True, dry_run=False)
    rows = {r["line_id"]: r for r in T.craft_view(db, b1)["linked"]}
    assert kid["ours1"].id not in rows
    assert rows[kid["ours2"].id]["steps"] == ["Program"]
    T.link_costs(db, b1, step_run_ids=None, step_keys=["enclose"], line_ids=[kid["ours1"].id], dry_run=False)
    rows = {r["line_id"]: r for r in T.craft_view(db, b1)["linked"]}
    assert rows[kid["ours1"].id]["steps"] == ["Enclose"]


def test_a_header_keeps_only_the_links_another_share_still_holds(db, world):
    from app.routers import run_costs as rc

    b1, fee, kid = _shared_split(db, world, 130)
    T.link_costs(db, b1, step_run_ids=None, line_ids=[kid["ours1"].id], unlink=True, dry_run=False)
    T.link_costs(db, b1, step_run_ids=None, step_keys=["enclose"], line_ids=[kid["ours1"].id], dry_run=False)
    T.link_costs(db, b1, step_run_ids=None, line_ids=[kid["ours2"].id], unlink=True, dry_run=False)
    assert db.query(M.CostLineStepKey).filter_by(line_id=fee.id, run_id=b1.id).count() == 0
    assert db.query(M.CostLineStep).filter_by(line_id=fee.id).count() == 0
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="extra", amount=0, plan_key="final:device", run_id=b1.id)]), db)
    extra = db.query(M.RunCostLine).filter_by(parent_line_id=fee.id, label="extra").one()
    assert db.query(M.CostLineStepKey).filter_by(line_id=extra.id).count() == 0
    assert db.query(M.CostLineStep).filter_by(line_id=extra.id).count() == 0


def test_a_relink_without_an_unlink_leaves_the_header_nothing_stale(db, world):
    """Loop-until-dry round 4: the API relinks both shares to another step at
    once; the header above them loses the step no share holds any more."""
    from app.routers import run_costs as rc

    b1, fee, kid = _shared_split(db, world, 131)
    T.link_costs(db, b1, step_run_ids=None, step_keys=["enclose"],
                 line_ids=[kid["ours1"].id, kid["ours2"].id], dry_run=False)
    assert db.query(M.CostLineStepKey).filter_by(line_id=fee.id, run_id=b1.id).count() == 0
    assert db.query(M.CostLineStep).filter_by(line_id=fee.id).count() == 0
    rows = {r["line_id"]: r for r in T.craft_view(db, b1)["linked"]}
    assert rows[kid["ours1"].id]["steps"] == ["Enclose"] and rows[kid["ours2"].id]["steps"] == ["Enclose"]
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="extra", amount=0, plan_key="final:device", run_id=b1.id)]), db)
    extra = db.query(M.RunCostLine).filter_by(parent_line_id=fee.id, label="extra").one()
    assert db.query(M.CostLineStepKey).filter_by(line_id=extra.id).count() == 0
