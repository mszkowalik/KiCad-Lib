"""A draw takes the cost of the lots it is bound to, oldest first (decision 0073).

What these pin down:

- the picker takes the oldest lot first and splits a draw across lots, each
  at its own landed cost;
- while `lot_pricing` is on, every writer binds its draws that way — a step,
  a BOM draw, a hand draw, the used-quantity screen, a JLC warehouse pick and
  an in-house transfer — and refuses a draw the lots cannot cover;
- a smaller used quantity gives back the newest binding first;
- the history job binds in date order, re-prices a closed batch and freezes
  its twin share again, and lists (and leaves) what no lot covers;
- the switch turns on only when every live draw is bound;
- the register's identities hold before and after the history job;
- with the switch off nothing changes.

The refusals need a stock the pool holds and the lots do not. That is a draw
of the OTHER company bound to this company's lots before any transfer (what
JLC reports for an order the other company paid), so those tests turn stock
per company on.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_lot_pricing.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.config import settings
from app.db import engine
from app.services import appconfig, jlc_ledger
from app.services import companies as C
from app.services import lots as L
from app.services import process as P
from app.services import run_actuals as ra
from app.services import transfers as TR
from app.services import twins as T

PART, LCSC = "LP-BOX-1", "CLPBOX1"


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
def lp(monkeypatch):
    monkeypatch.setattr(settings, "lot_pricing", True)


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(settings, "lot_pricing", False)


@pytest.fixture
def split(monkeypatch):
    monkeypatch.setattr(settings, "stock_per_company", True)


@pytest.fixture
def world(db):
    """7Sigma bought the same box twice: lot A, 10 at $1.00 on 2025-01-01, and
    lot B, 10 at $2.00 on 2025-01-10. A plain 7Sigma batch and a 9Sigma one."""
    s7, s9 = C.by_key(db, "7sigma"), C.by_key(db, "9sigma")
    p = M.Project(name="test-lot-pricing", git_url="https://example.invalid/lp.git")
    db.add(p)
    db.flush()
    db.add(M.ProjectOwnership(project_id=p.id, company_id=s7.id, from_date="2024-01-01"))
    box = M.Component(name="test-lp-box", in_library=False)
    db.add(box)
    db.flush()
    lots = []
    for n, (day, price) in enumerate((("2025-01-01", 1.0), ("2025-01-10", 2.0)), start=1):
        doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number=f"LP-{n}", doc_date=day,
                                currency="USD", total_amount=10 * price, company_id=s7.id)
        db.add(doc)
        db.flush()
        li = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled", component_id=box.id,
                           mpn=PART, lcsc=LCSC, qty=10, unit_price=price, currency="USD", position=0)
        db.add(li)
        db.flush()
        lots.append(li)
    r7 = M.ProductionRun(project_id=p.id, label="LP7", run_date="2025-02-01", qty=15, company_id=s7.id)
    r9 = M.ProductionRun(project_id=p.id, label="LP9", run_date="2025-02-01", qty=15, company_id=s9.id)
    db.add_all([r7, r9])
    db.flush()
    return SimpleNamespace(s7=s7, s9=s9, p=p, box=box, a=lots[0], b=lots[1], r7=r7, r9=r9)


def _starve(db, w, qty, day="2025-01-20"):
    """A 9Sigma draw JLC bound to 7Sigma's lots, oldest first, with no transfer
    yet: 7Sigma's stock still holds the units, its lots do not."""
    c = M.ComponentConsumption(run_id=None, component_id=w.box.id, mpn=PART, lcsc=LCSC, qty=qty,
                               unit_cost_usd=1.0, basis="measured", consumed_at=day, company_id=w.s9.id,
                               import_ref=f"jlc:LPX:SMT-LP-{qty}:{LCSC}")
    db.add(c)
    db.flush()
    picked = L.FifoPicker(db, w.s7.id).pick(w.box.id, PART, LCSC, qty, day)
    assert picked["uncovered"] == 0
    L.bind(db, c, picked, source="reported")
    return c


def _bindings(db, c):
    """`[(lot key, qty, unit)]` of one draw, oldest binding first."""
    rows = (db.query(M.ComponentConsumptionLot).filter_by(consumption_id=c.id)
            .order_by(M.ComponentConsumptionLot.id).all())
    return [(f"L{b.lot_line_id}" if b.lot_line_id else f"A{b.lot_adjustment_id}", b.qty, b.unit_cost_usd)
            for b in rows]


def _draw(db, run, qty, day, unit=1.5, **kw):
    c = M.ComponentConsumption(run_id=run.id if run else None, component_id=kw.pop("component_id", None),
                               mpn=kw.pop("mpn", PART), lcsc=kw.pop("lcsc", LCSC), qty=qty, unit_cost_usd=unit,
                               basis=kw.pop("basis", "manual"), consumed_at=day, **kw)
    db.add(c)
    db.flush()
    return c


def _process_run(db, w, label="LPC", qty=20):
    """A crafted 7Sigma batch whose `pack` step takes one box per unit, with
    `qty` boards received into one stack."""
    graph = {
        "steps": [
            {"key": "assembly", "label": "Assembly", "kind": "assembly", "required": True},
            {"key": "receive", "label": "Receive", "kind": "receive", "required": True},
            {"key": "pack", "label": "Pack", "kind": "step", "required": True, "needs": ["receive"],
             "inputs": [{"component_id": w.box.id, "qty": 1}]},
            {"key": "program", "label": "Program", "kind": "program", "required": True, "needs": ["receive"]},
            {"key": "finish", "label": "Finished", "kind": "finish"},
        ],
        "route": ["assembly", "receive", "pack", "program", "finish"],
        "prepared": [],
    }
    if not P.current_version(db, w.p.id):
        v = P.compose(db, w.p.id, actor="test", graph=graph)
        P.publish(db, v, actor="test", comment="lot pricing test")
    v = P.current_version(db, w.p.id)
    run = M.ProductionRun(project_id=w.p.id, label=label, run_date="2025-02-01", status="completed",
                          process_version_id=v.id, qty=qty, company_id=w.s7.id)
    db.add(run)
    db.flush()
    stack = T.receive(db, run, qty=qty, made_at="2025-02-01", dry_run=False)["stack"]
    return run, stack


# ------------------------------------------------------------------ the picker

def test_the_oldest_lot_goes_first_and_a_draw_splits_across_lots(db, world):
    picker = L.FifoPicker(db, world.s7.id)
    p = picker.pick(world.box.id, PART, LCSC, 15, "2025-02-01")
    assert [(b["lot"], b["qty"], b["unit_cost_usd"]) for b in p["bindings"]] == \
        [(f"L{world.a.id}", 10, 1.0), (f"L{world.b.id}", 5, 2.0)]
    assert p["unit_cost_usd"] == pytest.approx(20 / 15)
    # the same picker never hands out a unit twice
    assert picker.pick(world.box.id, PART, LCSC, 6, "2025-02-01")["uncovered"] == pytest.approx(1)
    # a lot bought after the draw cannot have fed it
    early = L.FifoPicker(db, world.s7.id).pick(world.box.id, PART, LCSC, 15, "2025-01-05")
    assert (early["covered"], early["uncovered"]) == (10, 5)
    # the other company's picker does not see 7Sigma's lots
    assert L.FifoPicker(db, world.s9.id).pick(world.box.id, PART, LCSC, 1, "2025-02-01")["covered"] == 0


# ------------------------------------------------------------------ the writers

def test_a_step_draw_is_bound_oldest_first_at_the_lots_cost(db, world, lp):
    run, stack = _process_run(db, world)
    plan = T.apply_step(db, run, step_key="pack", stack=stack, qty=15, made_at="2025-02-01", dry_run=False)
    assert plan["value_usd"] == pytest.approx(20.0)
    c = db.query(M.ComponentConsumption).filter_by(step_run_id=plan["step_run_id"]).one()
    assert c.unit_cost_usd == pytest.approx(20 / 15)
    assert _bindings(db, c) == [(f"L{world.a.id}", 10, 1.0), (f"L{world.b.id}", 5, 2.0)]


def test_a_step_draw_the_lots_cannot_cover_is_refused(db, world, lp, split):
    run, stack = _process_run(db, world)
    _starve(db, world, 18)
    plan = T.apply_step(db, run, step_key="pack", stack=stack, qty=5, made_at="2025-02-01", dry_run=True)
    assert plan["shortages"] == []          # the stock holds them ...
    assert plan["problems"][0]["uncovered"] == pytest.approx(3)   # ... the lots do not
    with pytest.raises(HTTPException) as e:
        T.apply_step(db, run, step_key="pack", stack=stack, qty=5, made_at="2025-02-01", dry_run=False)
    assert e.value.status_code == 409


def _bom_run(db, w):
    snap = M.ProjectSnapshot(project_id=w.p.id, status="ready", sha="1" * 40,
                             created_at=datetime(2025, 1, 1, tzinfo=UTC))
    db.add(snap)
    db.flush()
    db.add(M.SnapshotBomLine(snapshot_id=snap.id, board="B1", variant="", position=1, refs="U1", qty=1,
                             lcsc=LCSC, mpn=PART, component_id=w.box.id))
    run = M.ProductionRun(project_id=w.p.id, label="LPB", board="B1", variant="", run_date="2025-02-01",
                          status="completed", qty=15, snapshot_id=snap.id, company_id=w.s7.id)
    db.add(run)
    db.flush()
    return run


def test_a_bom_draw_is_bound_oldest_first(db, world, lp):
    run = _bom_run(db, world)
    res = ra.consume_from_bom(db, run)
    assert res.get("error") is None, res
    c = db.query(M.ComponentConsumption).filter_by(run_id=run.id).one()
    assert c.unit_cost_usd == pytest.approx(20 / 15)
    assert [b[1] for b in _bindings(db, c)] == [10, 5]


def test_a_bom_draw_the_lots_cannot_cover_is_refused(db, world, lp, split):
    run = _bom_run(db, world)
    _starve(db, world, 10)
    res = ra.consume_from_bom(db, run)
    assert res["created"] == 0 and res["uncovered"][0]["uncovered"] == pytest.approx(5)
    assert db.query(M.ComponentConsumption).filter_by(run_id=run.id).count() == 0


def test_a_hand_draw_takes_the_lots_cost_not_a_typed_price(db, world, lp):
    from app.routers import run_costs as rc

    out = rc.add_consumption(world.r7.id, rc.ConsumptionIn(component_id=world.box.id, qty=15, unit_cost_usd=9.99,
                                                           consumed_at="2025-02-01"), db=db)
    assert out["unit_cost_usd"] == pytest.approx(20 / 15)
    assert [b[1] for b in _bindings(db, db.get(M.ComponentConsumption, out["id"]))] == [10, 5]


def test_a_hand_draw_the_lots_cannot_cover_is_refused(db, world, lp, split):
    from app.routers import run_costs as rc

    _starve(db, world, 18)
    with pytest.raises(HTTPException) as e:
        rc.add_consumption(world.r7.id, rc.ConsumptionIn(component_id=world.box.id, qty=5,
                                                         consumed_at="2025-02-01"), db=db)
    assert e.value.status_code == 409 and "not in any lot" in e.value.detail["error"]


def test_a_smaller_used_qty_gives_back_the_newest_binding_first(db, world, lp):
    from app.routers import run_costs as rc

    def used(q):
        return rc.set_used_qty(world.r7.id, rc.ConsumptionIn(component_id=world.box.id, qty=q,
                                                             consumed_at="2025-02-01"), db=db)

    c = db.get(M.ComponentConsumption, used(15)["id"])
    assert _bindings(db, c) == [(f"L{world.a.id}", 10, 1.0), (f"L{world.b.id}", 5, 2.0)]
    used(12)
    assert _bindings(db, c) == [(f"L{world.a.id}", 10, 1.0), (f"L{world.b.id}", 2, 2.0)]
    assert c.unit_cost_usd == pytest.approx(14 / 12)
    used(8)
    assert _bindings(db, c) == [(f"L{world.a.id}", 8, 1.0)]
    assert c.unit_cost_usd == pytest.approx(1.0)
    used(14)   # more takes the next lots oldest first again
    assert _bindings(db, c) == [(f"L{world.a.id}", 8, 1.0), (f"L{world.a.id}", 2, 1.0),
                                (f"L{world.b.id}", 4, 2.0)]
    assert c.unit_cost_usd == pytest.approx(18 / 14)


def test_a_used_qty_increase_the_lots_cannot_cover_is_refused(db, world, lp, split):
    from app.routers import run_costs as rc

    rc.set_used_qty(world.r7.id, rc.ConsumptionIn(component_id=world.box.id, qty=5,
                                                  consumed_at="2025-02-01"), db=db)
    _starve(db, world, 15)
    with pytest.raises(HTTPException) as e:
        rc.set_used_qty(world.r7.id, rc.ConsumptionIn(component_id=world.box.id, qty=8,
                                                      consumed_at="2025-02-01"), db=db)
    assert e.value.status_code == 409 and e.value.detail["uncovered"][0]["uncovered"] == pytest.approx(3)


def _pick(db, key, qty, when="2025-02-03"):
    db.add(M.JlcStockChange(change_key_id=key, stock_key_id=1, lcsc=LCSC, mpn=PART,
                            changed_at=datetime.fromisoformat(when).replace(tzinfo=UTC), qty_before=0,
                            change_qty=-qty, qty_after=0, paid_usd=0.0, business_code=f"T{key}",
                            business_type=jlc_ledger.BT_WAREHOUSE, change_type=1, change_status=2,
                            remark="pick up to complete SMT order", raw={}))
    db.flush()


def test_a_warehouse_pick_takes_its_lots_oldest_first(db, world, lp, split):
    _pick(db, 990073001, 15)
    res = jlc_ledger.book(db, [990073001], dry_run=False, company_id=world.s7.id)
    assert res["refused"] == []
    w = res["written"][0]
    assert w["unit_cost_usd"] == pytest.approx(20 / 15) and w["usd"] == pytest.approx(20.0)
    assert [b[1] for b in _bindings(db, db.get(M.ComponentConsumption, w["consumption_id"]))] == [10, 5]


def test_a_warehouse_pick_the_lots_cannot_cover_is_refused(db, world, lp, split):
    _starve(db, world, 18)
    _pick(db, 990073002, 5)
    _pick(db, 990073003, 2, when="2025-02-04")
    res = jlc_ledger.book(db, [990073002, 990073003], dry_run=False, company_id=world.s7.id)
    assert [r["change_key_id"] for r in res["refused"]] == [990073002]
    assert "in no lot" in res["refused"][0]["why"]
    # the refused pick gave back what it reserved: the next one is covered
    assert [w["change_key_id"] for w in res["written"]] == [990073003]


def test_a_transfer_moves_the_sender_s_lots_oldest_first(db, world, lp, split):
    res = TR.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                    lines=[{"component_id": world.box.id, "qty": 15}], run_id=world.r9.id, dry_run=False)
    x = res["lines"][0]
    assert x["unit_cost_usd"] == pytest.approx(20 / 15)
    assert "lots, oldest first" in x["price_source"]
    sender = db.get(M.ComponentConsumption, x["sender_draw_id"])
    assert _bindings(db, sender) == [(f"L{world.a.id}", 10, 1.0), (f"L{world.b.id}", 5, 2.0)]
    pos = db.get(M.RunCostLine, x["line_id"])
    assert pos.unit_price == pytest.approx(20 / 15)
    # the position is 9Sigma's lot now, at the cost the units left 7Sigma with
    p9 = L.FifoPicker(db, world.s9.id).pick(world.box.id, PART, LCSC, 15, "2025-02-01")
    assert [b["lot"] for b in p9["bindings"]] == [f"L{pos.id}"] and p9["uncovered"] == 0
    assert L.check_lot_capacity(db, []) == []
    reg = ra.invoice_register(db)
    assert reg["summary"]["gap_usd"] == pytest.approx(0.0)


def test_a_transfer_the_sender_s_lots_cannot_cover_is_refused(db, world, lp, split):
    _starve(db, world, 18)
    plan = TR.plan(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-25",
                   lines=[{"component_id": world.box.id, "qty": 5}])
    assert plan["shortages"] == []
    assert plan["problems"][0]["uncovered"] == pytest.approx(3) and "in no lot" in plan["problems"][0]["problem"]
    with pytest.raises(HTTPException) as e:
        TR.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-25",
                  lines=[{"component_id": world.box.id, "qty": 5}], dry_run=False)
    assert e.value.status_code == 409


def test_a_named_lot_is_taken_before_the_lines_that_name_none(db, world, lp):
    plan = TR.plan(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                   lines=[{"component_id": world.box.id, "qty": 5},
                          {"component_id": world.box.id, "qty": 10, "lot_line_id": world.a.id}])
    assert plan["problems"] == [] and plan["lot_capacity"] == []
    free = plan["lines"][0]
    assert [(b["lot"], b["qty"]) for b in free["bindings"]] == [(f"L{world.b.id}", 5)]
    assert free["unit_cost_usd"] == pytest.approx(2.0)


def test_a_draw_about_to_move_gives_its_lots_back_to_the_picker(db, world, lp):
    d = _draw(db, world.r7, 10, "2025-01-15", unit=1.0, component_id=world.box.id)
    L.bind(db, d, L.FifoPicker(db, world.s7.id).pick(world.box.id, PART, LCSC, 10, "2025-01-15"))
    lines = [{"component_id": world.box.id, "qty": 15}]
    held = TR.plan(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20", lines=lines)
    assert held["problems"] and held["problems"][0]["uncovered"] == pytest.approx(5)
    moving = TR.plan(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20", lines=lines,
                     exclude_draw_ids=[d.id])
    assert moving["problems"] == []
    assert [(b["lot"], b["qty"]) for b in moving["lines"][0]["bindings"]] == \
        [(f"L{world.a.id}", 10), (f"L{world.b.id}", 5)]


def test_a_charge_still_moves_the_other_company_s_lot(db, world, lp, split):
    """A JLC order drew 7Sigma's lot for a 9Sigma batch: the charge writes the
    lot transfer as before, and the lot ledger counts the units once."""
    from app.services import jlc_apply

    c = _draw(db, None, 10, "2025-02-01", unit=1.0, component_id=world.box.id, basis="measured",
              company_id=world.s7.id, import_ref=f"jlc:BLP1:SMT-LP-1:{LCSC}")
    db.add(M.ComponentConsumptionLot(consumption_id=c.id, lot_line_id=world.a.id, qty=10, unit_cost_usd=1.0,
                                     source="reported"))
    db.flush()
    res = jlc_apply.charge_draws(db, {"smt_order_code": "SMT-LP-1", "batch_num": "BLP1"}, world.r9.id,
                                 dry_run=False)
    assert len(res["cover"]["written"]) == 1
    db.refresh(c)
    assert c.company_id == world.s9.id
    assert L.check_lot_capacity(db, []) == []
    state = L.lot_state(db)["lots"]
    assert state[f"L{world.a.id}"]["qty_remaining"] == pytest.approx(0.0)


# ------------------------------------------------------------------ the history

def test_the_history_binds_in_date_order_and_refreezes_a_closed_batch(db, world, off):
    late = _draw(db, world.r7, 10, "2025-03-01", component_id=world.box.id)   # written first
    run, _stack = _process_run(db, world, qty=10)
    early = _draw(db, run, 10, "2025-02-01", component_id=world.box.id, basis="measured")
    cost, units = ra.close_snapshot(db, run)
    run.closed_twin_share_usd = T.freeze_share(db, run)
    run.closed_at, run.closed_by, run.closed_cost_usd, run.closed_units = M.utcnow(), "test", cost, units
    db.flush()
    share = run.closed_twin_share_usd
    assert share is not None

    dry = L.bind_history(db, dry_run=True)
    mine = {b["run_id"]: b for b in dry["batches"] if b["run_id"] in (run.id, world.r7.id)}
    assert mine[run.id]["change_usd"] == pytest.approx(-5.0) and mine[run.id]["closed"]
    assert mine[run.id]["closed_cost_usd"] == pytest.approx(cost)
    assert mine[world.r7.id]["change_usd"] == pytest.approx(5.0) and not mine[world.r7.id]["closed"]
    assert _bindings(db, early) == [] and early.unit_cost_usd == pytest.approx(1.5)   # a dry run writes nothing

    L.bind_history(db, dry_run=False)
    assert _bindings(db, early) == [(f"L{world.a.id}", 10, 1.0)]    # the earlier draw takes the earlier lot
    assert _bindings(db, late) == [(f"L{world.b.id}", 10, 2.0)]
    assert (early.unit_cost_usd, late.unit_cost_usd) == (pytest.approx(1.0), pytest.approx(2.0))
    db.refresh(run)
    assert run.closed_twin_share_usd == pytest.approx(share - 0.5)   # $5 less over 10 twins
    assert run.closed_cost_usd == pytest.approx(cost)                # the change reads as a variance


def test_the_history_lists_a_draw_no_lot_covers_and_leaves_it(db, world, off):
    big = _draw(db, world.r7, 25, "2025-02-01", component_id=world.box.id)
    small = _draw(db, world.r7, 5, "2025-03-01", component_id=world.box.id)
    stray = _draw(db, world.r7, 3, "2025-02-01", unit=0.5, mpn="LP-NO-LOT", lcsc="")
    res = L.bind_history(db, dry_run=False)
    left = {u["consumption_id"]: u for u in res["uncovered"]}
    assert left[big.id]["uncovered"] == pytest.approx(5) and left[stray.id]["uncovered"] == pytest.approx(3)
    assert _bindings(db, big) == [] and big.unit_cost_usd == pytest.approx(1.5)
    assert _bindings(db, stray) == [] and stray.unit_cost_usd == pytest.approx(0.5)
    # what the uncovered draw reserved went back: the later draw takes lot A
    assert _bindings(db, small) == [(f"L{world.a.id}", 5, 1.0)]


def test_the_switch_waits_until_every_draw_is_bound(db, world):
    knob = appconfig.BY_KEY["lot_pricing"]
    d = _draw(db, world.r7, 10, "2025-02-01", component_id=world.box.id)
    with pytest.raises(ValueError):
        appconfig.validate(knob, True, db)
    appconfig.validate(knob, False, db)      # turning it off is always allowed
    L.bind_history(db, dry_run=False)
    assert d.id not in {c.id for c, _rest in L.untraced(db)}
    # Draws of the dev database no lot covers are not this test's subject:
    # void them in this transaction, which is rolled back.
    for c, _rest in L.untraced(db):
        c.voided_at = M.utcnow()
    db.flush()
    appconfig.validate(knob, True, db)


def test_the_register_identities_hold_before_and_after_the_history(db, world, off):
    _draw(db, world.r7, 10, "2025-02-01", component_id=world.box.id)
    _draw(db, world.r7, 5, "2025-03-01", component_id=world.box.id)
    before = ra.invoice_register(db)
    assert before["summary"]["gap_usd"] == pytest.approx(0.0, abs=0.01)
    assert before["pool"]["balanced"]
    L.bind_history(db, dry_run=False)
    after = ra.invoice_register(db)
    assert after["summary"]["gap_usd"] == pytest.approx(0.0, abs=0.01)
    assert after["pool"]["balanced"]


# ------------------------------------------------------------------ switch off

def test_with_the_switch_off_a_step_draw_takes_the_average(db, world, off):
    run, stack = _process_run(db, world)
    plan = T.apply_step(db, run, step_key="pack", stack=stack, qty=15, made_at="2025-02-01", dry_run=False)
    c = db.query(M.ComponentConsumption).filter_by(step_run_id=plan["step_run_id"]).one()
    assert c.unit_cost_usd == pytest.approx(1.5)
    assert _bindings(db, c) == []


# ----------------------------------------- an undo or a redo takes stock too (0073)

def test_a_redo_that_would_overdraw_a_lot_is_refused(db, world, lp, split):
    """Loop-until-dry round 3: the first transfer is undone, a second one
    takes lot A, and the redo of the first would bind lot A again. The part's
    stock holds it (lot B is open), the lot does not."""
    from app.services import journal as J

    with J.batch(db, kind="transfer.create") as h:
        TR.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                  lines=[{"component_id": world.box.id, "qty": 10}], run_id=world.r9.id, dry_run=False)
    undo = J.reverse(db, h["batch_id"], dry_run=False)
    TR.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-21",
              lines=[{"component_id": world.box.id, "qty": 10}], run_id=world.r9.id, dry_run=False)
    redo = J.reverse(db, undo["reverse_batch_id"])
    assert redo["status"] == "refused"
    assert any(f"lot L{world.a.id}" in b and "overdrawn by 10" in b for b in redo["blockers"])


def test_an_undo_that_makes_a_voided_draw_live_again_checks_the_stock(db, world, off):
    from app.services import journal as J

    d0 = _draw(db, world.r7, 15, "2025-01-15", component_id=world.box.id)
    with J.batch(db, kind="test.void") as h:
        d0.voided_at = datetime.now(UTC)
        db.flush()
    _draw(db, world.r7, 15, "2025-01-16", component_id=world.box.id)
    res = J.reverse(db, h["batch_id"])
    assert res["status"] == "refused"
    assert any("no longer holds" in b and "short 10" in b for b in res["blockers"])


def test_a_redo_that_voids_what_it_replaces_is_not_refused(db, world, off):
    """The redo puts the new draw back AND voids the old one again: one net
    change, which the stock holds."""
    from app.services import journal as J

    d0 = _draw(db, world.r7, 15, "2025-01-15", component_id=world.box.id)
    with J.batch(db, kind="test.replace") as h:
        d0.voided_at = datetime.now(UTC)
        _draw(db, world.r7, 15, "2025-01-15", component_id=world.box.id, basis="measured")
    undo = J.reverse(db, h["batch_id"], dry_run=False)
    redo = J.reverse(db, undo["reverse_batch_id"])
    assert redo["status"] == "would_reverse", redo["blockers"]


def test_an_undone_void_takes_back_its_lots_and_is_checked(db, world, lp):
    """Loop-until-dry round 4: a void keeps the draw's bindings and frees its
    lots; a later draw takes lot A; the undo would bind lot A twice. The part
    holds it (lot B), the lot does not."""
    from app.services import journal as J

    d0 = _draw(db, world.r7, 10, "2025-01-15", component_id=world.box.id)
    L.bind(db, d0, L.FifoPicker(db).pick(world.box.id, PART, LCSC, 10, "2025-01-15"))
    with J.batch(db, kind="test.void") as h:
        d0.voided_at = datetime.now(UTC)
        db.flush()
    d2 = _draw(db, world.r7, 10, "2025-01-16", component_id=world.box.id)
    L.bind(db, d2, L.FifoPicker(db).pick(world.box.id, PART, LCSC, 10, "2025-01-16"))
    assert _bindings(db, d2) == [(f"L{world.a.id}", 10, 1.0)]
    res = J.reverse(db, h["batch_id"])
    assert res["status"] == "refused"
    assert any(f"lot L{world.a.id}" in b and "overdrawn by 10" in b for b in res["blockers"])


def test_a_redo_that_collides_with_a_record_written_again_names_it(db, world, off):
    """Loop-until-dry round 5: the import is undone and written again; the
    redo would put the first one back beside it."""
    from app.services import journal as J

    with J.batch(db, kind="test.book") as h:
        _draw(db, world.r7, 2, "2025-01-15", component_id=world.box.id, import_ref="jlc:TEST:COLLIDE")
    undo = J.reverse(db, h["batch_id"], dry_run=False)
    _draw(db, world.r7, 2, "2025-01-15", component_id=world.box.id, import_ref="jlc:TEST:COLLIDE")
    redo = J.reverse(db, undo["reverse_batch_id"])
    assert redo["status"] == "refused"
    assert any("collides with the present data" in b and "uq_consumption_import" in b for b in redo["blockers"])


def test_a_lot_priced_draw_that_shrinks_keeps_its_lots_price_with_the_switch_off(db, world, off):
    """Loop-until-dry round 6: the history job priced the draw at its lots;
    a smaller used quantity gives back the newer lot, and the draw takes the
    price of the lot it still holds. The switch is not on yet."""
    from app.routers import run_costs as rc

    def used(q):
        return rc.set_used_qty(world.r7.id, rc.ConsumptionIn(component_id=world.box.id, qty=q,
                                                             consumed_at="2025-02-01"), db=db)

    c = db.get(M.ComponentConsumption, used(15)["id"])
    L.bind_history(db, dry_run=False)
    assert c.unit_cost_usd == pytest.approx(20 / 15)
    used(8)
    assert _bindings(db, c) == [(f"L{world.a.id}", 8, 1.0)]
    assert c.unit_cost_usd == pytest.approx(1.0)


def test_an_undo_that_takes_a_lot_away_under_a_live_draw_is_refused(db, world, off):
    """Loop-until-dry round 6: the purchase is undone while a later draw is
    still bound to it; the other lots keep the part's stock above zero."""
    from app.services import journal as J

    with J.batch(db, kind="test.purchase") as h:
        doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="LP-C", doc_date="2025-01-12",
                                currency="USD", total_amount=150.0, company_id=world.s7.id)
        db.add(doc)
        db.flush()
        lot_c = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled",
                              component_id=world.box.id, mpn=PART, lcsc=LCSC, qty=50, unit_price=3.0,
                              currency="USD", position=0)
        db.add(lot_c)
        db.flush()
    d = _draw(db, world.r7, 15, "2025-01-20", component_id=world.box.id)
    L.bind(db, d, {"bindings": [{"lot_line_id": lot_c.id, "lot_adjustment_id": None, "qty": 15,
                                 "unit_cost_usd": 3.0}]})
    res = J.reverse(db, h["batch_id"])
    assert res["status"] == "refused"
    assert any(f"lot L{lot_c.id}" in b and f"#{d.id}" in b and "taken away" in b for b in res["blockers"])


def test_a_transfer_is_reversed_on_its_document_not_on_the_write_log(db, world, lp, split):
    from app.routers import ledger as lg
    from app.services import journal as J

    with J.batch(db, kind="transfer.create") as h:
        TR.create(db, sender_id=world.s7.id, receiver_id=world.s9.id, day="2025-01-20",
                  lines=[{"component_id": world.box.id, "qty": 5}], run_id=world.r9.id, dry_run=False)
    with pytest.raises(HTTPException) as e:
        lg.reverse_batch(h["batch_id"], dry_run=True, db=db)
    assert e.value.status_code == 409 and "Transfers" in str(e.value.detail)


# ------------------------------------------------ loop-until-dry round 7

def test_a_lot_priced_draw_corrected_back_takes_its_lots_again_with_the_switch_off(db, world, off):
    from app.routers import run_costs as rc

    def used(q):
        return rc.set_used_qty(world.r7.id, rc.ConsumptionIn(component_id=world.box.id, qty=q,
                                                             consumed_at="2025-02-01"), db=db)

    c = db.get(M.ComponentConsumption, used(15)["id"])
    L.bind_history(db, dry_run=False)
    used(8)
    used(15)
    assert _bindings(db, c) == [(f"L{world.a.id}", 8, 1.0), (f"L{world.a.id}", 2, 1.0), (f"L{world.b.id}", 5, 2.0)]
    assert c.unit_cost_usd * c.qty == pytest.approx(20.0)
    assert L.untraced(db) == [] or all(x[0].id != c.id for x in L.untraced(db))


def test_an_invoice_edit_that_takes_a_lot_from_its_draws_is_refused(db, world, off):
    from app.routers import run_costs as rc

    d = _draw(db, world.r7, 15, "2025-01-20", component_id=world.box.id)
    L.bind(db, d, L.FifoPicker(db).pick(world.box.id, PART, LCSC, 15, "2025-01-20"))   # A 10, B 5
    doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="LP-C", doc_date="2025-01-05",
                            currency="USD", total_amount=150.0, company_id=world.s7.id)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled", component_id=world.box.id,
                         mpn=PART, lcsc=LCSC, qty=50, unit_price=3.0, currency="USD", position=0))
    db.flush()                                           # the pool holds the part without lot A
    for call in (lambda: rc.void_line(world.a.id, db=db),
                 lambda: rc.update_line(world.a.id, rc.LinePatch(qty=4), db=db),
                 lambda: rc.split_line_core(world.a.id, rc.SplitIn(allow_parts=True, children=[
                     rc.ChildIn(label=x, qty=q, unit_price=1.0, component_id=world.box.id, mpn=PART, lcsc=LCSC,
                                plan_key="parts:pool", allocate="pooled") for x, q in (("x", 6), ("y", 4))]), db)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409 and f"#{d.id}" in str(e.value.detail), e.value.detail
    assert db.get(M.RunCostLine, world.a.id).voided_at is None and db.get(M.RunCostLine, world.a.id).qty == 10


def test_deleting_an_adjustment_its_draws_hold_is_refused(db, world, off):
    from app.routers import run_costs as rc

    a = M.ComponentStockAdjustment(component_id=world.box.id, mpn=PART, lcsc=LCSC, qty_delta=20, unit_cost_usd=0.5,
                                   reason="opening_balance", adjusted_at="2025-01-02", company_id=world.s7.id)
    db.add(a)
    db.flush()
    d = _draw(db, world.r7, 5, "2025-01-20", component_id=world.box.id)
    L.bind(db, d, {"bindings": [{"lot_line_id": None, "lot_adjustment_id": a.id, "qty": 5, "unit_cost_usd": 0.5}]})
    with pytest.raises(HTTPException) as e:
        rc.delete_adjustment(a.id, db=db)
    assert e.value.status_code == 409 and f"#{d.id}" in str(e.value.detail)
    free = M.ComponentStockAdjustment(component_id=world.box.id, mpn=PART, lcsc=LCSC, qty_delta=30,
                                      unit_cost_usd=0.5, reason="opening_balance", adjusted_at="2025-01-02",
                                      company_id=world.s7.id)
    db.add(free)
    db.flush()
    _draw(db, world.r7, 40, "2025-01-25", component_id=world.box.id)   # the pool needs that stock now
    with pytest.raises(HTTPException) as e:
        rc.delete_adjustment(free.id, db=db)
    assert e.value.status_code == 409 and "no purchase behind" in str(e.value.detail)


# ------------------------------------------------ loop-until-dry round 8

def _bound_draw(db, world):
    d = _draw(db, world.r7, 15, "2025-02-05", component_id=world.box.id)
    L.bind(db, d, L.FifoPicker(db).pick(world.box.id, PART, LCSC, 15, "2025-02-05"))   # A 10, B 5
    return d


def test_an_edit_that_moves_a_lot_away_from_its_draws_is_refused_whatever_field_moves_it(db, world, off):
    """A step that is no stock, a proforma, a later date: each takes lot A
    from the draw bound to it, and the edit is refused with nothing kept."""
    from app.routers import run_costs as rc

    d = _bound_draw(db, world)
    doc_a = db.get(M.RunCostDocument, world.a.document_id)
    for call in (lambda: rc.update_line(world.a.id, rc.LinePatch(plan_key="logistics:inbound", allocate="by_value"),
                                        db=db),
                 lambda: rc.update_document(doc_a.id, rc.DocumentPatch(doc_type="proforma"), db=db),
                 lambda: rc.update_document(doc_a.id, rc.DocumentPatch(doc_date="2025-06-01"), db=db)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409 and f"#{d.id}" in str(e.value.detail), e.value.detail
    db.expire_all()
    assert (doc_a.doc_type, doc_a.doc_date, db.get(M.RunCostLine, world.a.id).plan_key) == \
        ("invoice", "2025-01-01", "parts:pool")


def test_a_re_split_that_voids_a_bound_child_is_refused(db, world, off):
    from app.routers import run_costs as rc

    def child(label, q, cid=None):
        return rc.ChildIn(id=cid, label=label, qty=q, unit_price=1.0, component_id=world.box.id, mpn=PART,
                          lcsc=LCSC, plan_key="parts:pool", allocate="pooled")

    rc.split_line_core(world.a.id, rc.SplitIn(allow_parts=True, children=[child("c1", 6), child("c2", 4)]), db)
    c1, c2 = (db.query(M.RunCostLine).filter_by(parent_line_id=world.a.id, label=x).one() for x in ("c1", "c2"))
    d = _draw(db, world.r7, 5, "2025-02-05", component_id=world.box.id)
    L.bind(db, d, {"bindings": [{"lot_line_id": c1.id, "lot_adjustment_id": None, "qty": 5, "unit_cost_usd": 1.0}]})
    with pytest.raises(HTTPException) as e:
        rc.split_line_core(world.a.id, rc.SplitIn(allow_parts=True, replace=True,
                                                  children=[child("c2", 4, c2.id), child("c3", 6)]), db)
    assert e.value.status_code == 409 and f"#{d.id}" in str(e.value.detail)
    assert db.get(M.RunCostLine, c1.id).voided_at is None


def test_a_new_buyer_cannot_take_a_lot_from_the_old_buyer_s_draws(db, world, off, split):
    from app.routers import run_costs as rc

    d = _draw(db, world.r7, 5, "2025-02-05", component_id=world.box.id, company_id=world.s7.id)
    L.bind(db, d, L.FifoPicker(db, world.s7.id).pick(world.box.id, PART, LCSC, 5, "2025-02-05"))
    with pytest.raises(HTTPException) as e:
        rc.update_document(world.a.document_id, rc.DocumentPatch(company_id=world.s9.id), db=db)
    assert e.value.status_code == 409 and "another company" in str(e.value.detail)


def test_an_mpn_written_another_way_on_a_bound_lot_is_no_re_key(db, world, off):
    """The MPN without its dash is the same pool key: the lot check lets it."""
    d = _draw(db, world.r7, 5, "2025-02-05", mpn=PART, lcsc=LCSC)
    L.bind(db, d, L.FifoPicker(db).pick(None, PART, LCSC, 5, "2025-02-05"))
    snap = L.bound_snapshot(db, [world.a.id])
    world.a.mpn = PART.replace("-", "")
    db.flush()
    assert L.bound_problems(db, snap) == []


def test_a_jlc_refresh_ignores_the_lots_of_a_voided_draw(db, world, off):
    from app.services import jlc_apply as JA

    doc = M.RunCostDocument(doc_type="invoice", supplier=JA.SUPPLIER, doc_number="J8-1", external_id="POBTESTJ8",
                            doc_date="2025-01-03", currency="USD", total_amount=10.0, company_id=world.s7.id)
    db.add(doc)
    db.flush()
    lot = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled", component_id=world.box.id,
                        mpn=PART, lcsc=LCSC, qty=10, unit_price=1.0, currency="USD", position=0,
                        label="J8 box", lot_ref="testj8-1", notes="lot testj8-1")
    db.add(lot)
    db.flush()
    d = _draw(db, world.r7, 5, "2025-02-05", component_id=world.box.id)
    L.bind(db, d, {"bindings": [{"lot_line_id": lot.id, "lot_adjustment_id": None, "qty": 5, "unit_cost_usd": 1.0}]})
    d.voided_at = datetime.now(UTC)
    db.flush()
    base = {"lot_ref": "testj8-1", "plan_key": "parts:pool", "label": "J8 box", "unit_price": 1.0, "lcsc": LCSC,
            "mpn": PART, "notes": "lot testj8-1", "allocate": "pooled", "exclude_reason": ""}
    res = JA.refresh_parts_document(db, {"external_id": "POBTESTJ8", "doc_number": "J8-1", "total_amount": 8.0,
                                         "refunded": [], "lines": [dict(base, qty=8)]}, dry_run=True)
    assert not res.get("blockers"), res


# ------------------------------------------------ loop-until-dry round 9

def test_a_credit_that_leaves_draws_without_stock_is_refused_wherever_it_is_entered(db, world, off):
    """A credit is a negative stock line (decision 0044). On a correction, a
    new credit note, a new position or a line re-keyed into the pool, it is
    checked like a cut of the purchase."""
    from app.routers import run_costs as rc

    _bound_draw(db, world)                                # 15 of the 20 drawn
    doc_b = db.get(M.RunCostDocument, world.b.document_id)
    credit = {"plan_key": "parts:pool", "allocate": "pooled", "component_id": world.box.id, "mpn": PART,
              "lcsc": LCSC, "qty": -10, "unit_price": 2.0, "currency": "USD", "label": "credit"}
    corr = rc.create_correction(doc_b.id, rc.CorrectionIn(doc_number="LP-B-K1", doc_date="2025-02-06"), db=db)
    for call in (lambda: rc.edit_lines(corr["id"], rc.LinesBatchIn(creates=[rc.LineIn(**credit)]), db=db),
                 lambda: rc.add_line(doc_b.id, rc.LineIn(**credit), db=db),
                 lambda: rc.create_shared_document(rc.DocumentIn(doc_type="credit_note", supplier="TESTCO",
                                                                 doc_number="LP-CN1", doc_date="2025-02-06",
                                                                 currency="USD", company_id=world.s7.id,
                                                                 lines=[rc.LineIn(**credit)]), db=db)):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == 409 and "short 5" in str(e.value.detail), e.value.detail
    other = M.RunCostLine(document_id=doc_b.id, plan_key="other:misc", qty=-10, unit_price=2.0, currency="USD",
                          label="credit typed as something else", position=5)
    db.add(other)
    db.flush()
    with pytest.raises(HTTPException) as e:
        rc.update_line(other.id, rc.LinePatch(plan_key="parts:pool", allocate="pooled", component_id=world.box.id,
                                              mpn=PART, lcsc=LCSC), db=db)
    assert e.value.status_code == 409 and "short 5" in str(e.value.detail)


# ------------------------------------------------ loop-until-dry round 10

def test_a_split_credit_and_a_re_keyed_share_are_checked_like_a_new_position(db, world, off):
    from app.routers import run_costs as rc

    other = M.Component(name="test-lp-other", in_library=False)
    db.add(other)
    db.flush()
    doc = M.RunCostDocument(doc_type="credit_note", supplier="TESTCO", doc_number="LP-CN2", doc_date="2025-03-01",
                            currency="USD", total_amount=-8.0, company_id=world.s7.id)
    db.add(doc)
    db.flush()
    lump = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled", qty=1, unit_price=-8.0,
                         currency="USD", position=0, label="credit for parts")
    db.add(lump)
    db.flush()

    def share(cid, mpn, sid=None):
        return rc.ChildIn(id=sid, label="credit share", qty=-4, unit_price=2.0, component_id=cid, mpn=mpn,
                          plan_key="parts:pool", allocate="pooled")

    with pytest.raises(HTTPException) as e:          # the other part was never bought
        rc.split_line_core(lump.id, rc.SplitIn(allow_parts=True, children=[share(other.id, "LP-OTHER")]), db)
    assert e.value.status_code == 409 and "short 4" in str(e.value.detail)
    rc.split_line_core(lump.id, rc.SplitIn(allow_parts=True, children=[share(world.box.id, PART)]), db)
    kid = db.query(M.RunCostLine).filter_by(parent_line_id=lump.id).one()
    with pytest.raises(HTTPException) as e:          # the same share, re-keyed in place
        rc.split_line_core(lump.id, rc.SplitIn(allow_parts=True, replace=True,
                                               children=[share(other.id, "LP-OTHER", kid.id)]), db)
    assert e.value.status_code == 409 and "short 4" in str(e.value.detail)
    assert db.get(M.RunCostLine, kid.id).component_id == world.box.id


def test_a_new_buyer_cannot_take_a_credit_it_cannot_cover(db, world, off, split):
    from app.routers import run_costs as rc

    credit = rc.LineIn(plan_key="parts:pool", allocate="pooled", component_id=world.box.id, mpn=PART, lcsc=LCSC,
                       qty=-5, unit_price=1.0, currency="USD", label="credit")
    cn = rc.create_shared_document(rc.DocumentIn(doc_type="credit_note", supplier="TESTCO", doc_number="LP-CN3",
                                                 doc_date="2025-03-01", currency="USD", company_id=world.s7.id,
                                                 lines=[credit]), db=db)
    with pytest.raises(HTTPException) as e:          # 9Sigma holds none of the part
        rc.update_document(cn["id"], rc.DocumentPatch(company_id=world.s9.id), db=db)
    assert e.value.status_code == 409 and "short 5" in str(e.value.detail)
    assert db.get(M.RunCostDocument, cn["id"]).company_id == world.s7.id


# ------------------------------------------------ the final fixes (decision 0073)

def test_a_credit_on_a_part_bought_under_two_names_is_checked_as_the_part(db, world, off):
    """The part was bought once by its MPN and once by its LCSC, and drawn by
    all its names: a credit or a cut the part covers passes. A second
    component that shares the LCSC is another part."""
    from app.routers import run_costs as rc

    x, y = M.Component(name="test-lp-x", in_library=False), M.Component(name="test-lp-y", in_library=False)
    db.add_all([x, y])
    db.flush()
    lots_ = []
    for n, (cid, mpn, lcsc, qty) in enumerate(((x.id, "LPX-MPN", "", 100), (x.id, "", "CLPX1", 100),
                                               (y.id, "", "CLPX1", 50)), start=1):
        doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number=f"LPX-{n}", doc_date="2025-01-05",
                                currency="USD", total_amount=qty, company_id=world.s7.id)
        db.add(doc)
        db.flush()
        li = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled", component_id=cid,
                           mpn=mpn, lcsc=lcsc, qty=qty, unit_price=1.0, currency="USD", position=0)
        db.add(li)
        db.flush()
        lots_.append(li)
    _draw(db, world.r7, 150, "2025-02-05", component_id=x.id, mpn="LPX-MPN", lcsc="CLPX1")
    for cid, lcsc in ((x.id, "CLPX1"), (y.id, "CLPX1")):
        rc.create_shared_document(rc.DocumentIn(
            doc_type="credit_note", supplier="TESTCO", doc_number=f"LPX-CN-{cid}", doc_date="2025-03-01",
            currency="USD", company_id=world.s7.id,
            lines=[rc.LineIn(plan_key="parts:pool", allocate="pooled", component_id=cid, lcsc=lcsc, qty=-10,
                             unit_price=1.0, currency="USD", label="credit")]), db=db)
    rc.update_line(lots_[1].id, rc.LinePatch(qty=95), db=db)
    with pytest.raises(HTTPException) as e:          # x holds 50 - 10 - 5 = 35: a credit of 40 is too much
        rc.add_line(lots_[1].document_id, rc.LineIn(plan_key="parts:pool", allocate="pooled", component_id=x.id,
                                                    lcsc="CLPX1", qty=-40, unit_price=1.0, currency="USD"), db=db)
    assert e.value.status_code == 409 and str(e.value.detail).count("short") == 1, e.value.detail


def test_a_jlc_refresh_that_cuts_a_lot_under_unbound_draws_is_refused(db, world, off):
    from app.services import jlc_apply as JA

    doc = M.RunCostDocument(doc_type="invoice", supplier=JA.SUPPLIER, doc_number="J9-1", external_id="POBTESTJ9",
                            doc_date="2025-01-03", currency="USD", total_amount=10.0, company_id=world.s7.id)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled", component_id=world.box.id,
                         mpn=PART, lcsc=LCSC, qty=10, unit_price=1.0, currency="USD", position=0,
                         label="J9 box", lot_ref="testj9-1", notes="lot testj9-1"))
    db.flush()
    _draw(db, world.r7, 25, "2025-02-05", component_id=world.box.id)     # 30 bought, no binding
    base = {"lot_ref": "testj9-1", "plan_key": "parts:pool", "label": "J9 box", "unit_price": 1.0, "lcsc": LCSC,
            "mpn": PART, "notes": "lot testj9-1", "allocate": "pooled", "exclude_reason": ""}
    res = JA.refresh_parts_document(db, {"external_id": "POBTESTJ9", "doc_number": "J9-1", "total_amount": 2.0,
                                         "refunded": [], "lines": [dict(base, qty=2)]}, dry_run=True)
    assert res["status"] == "refused" and "short 3" in res["blockers"][0], res
