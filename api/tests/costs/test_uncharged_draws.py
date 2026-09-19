"""A draw can exist before anybody says which batch pays for it.

Decision record: docs/decisions/0034-stock-moves-when-the-supplier-says-so.md.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import jlc_apply, run_actuals as ra


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
def world(db: Session):
    """One project, one batch, one purchase of 1000 pieces of a scratch part."""
    proj = M.Project(name="test-uncharged", git_url="https://example.invalid/u.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="U1", run_date="2026-03-01",
                          status="completed", qty=100)
    other = M.ProductionRun(project_id=proj.id, label="U2", run_date="2026-04-01",
                            status="completed", qty=100)
    db.add_all([run, other])
    db.flush()
    doc = M.RunCostDocument(project_id=proj.id, doc_type="invoice", supplier="TESTCO",
                            doc_number="U-0001", doc_date="2026-02-01", currency="USD",
                            total_amount=100.0)
    db.add(doc)
    db.flush()
    line = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", description="scratch part",
                         lcsc="CTEST001", mpn="TEST-PART-1", qty=1000, unit_price=0.1,
                         currency="USD", allocate="none")
    db.add(line)
    db.flush()
    return {"project": proj, "run": run, "other": other, "doc": doc, "line": line}


def _pool_row(db, lcsc="CTEST001", **kw):
    for v in ra.pool_state(db, **kw).values():
        if (v.get("lcsc") or "") == lcsc:
            return v
    return None


def _draw(db, world, qty=400.0, run_id=None, ref="jlc:WTEST:SMTTEST:CTEST001",
          when="2026-03-05"):
    c = M.ComponentConsumption(
        run_id=run_id, mpn="TEST-PART-1", lcsc="CTEST001", qty=qty,
        unit_cost_usd=0.1, basis="measured", consumed_at=when, import_ref=ref)
    db.add(c)
    db.flush()
    return c


# ---------------------------------------------------------------- the model


def test_a_draw_with_no_run_still_leaves_the_pool(db, world):
    """The whole point. JLC states what an order consumed on its invoice; who
    pays is decided later. The stock must not wait for that decision."""
    assert _pool_row(db)["qty"] == 1000
    _draw(db, world)
    row = _pool_row(db)
    assert row["qty"] == 600, "an uncharged draw must still take stock out"
    assert row["used"] == 400


def test_an_uncharged_draw_is_charged_to_no_run(db, world):
    """It leaves the pool and lands in no run's cost. Both halves matter: the
    first is stock control, the second is that nobody is billed by accident."""
    _draw(db, world)
    reg = ra.invoice_register(db)
    assert reg["pool"]["uncharged_drawn_usd"] >= 40.0
    assert str(world["run"].id) not in reg["by_run_usd"] or (
        reg["by_run_usd"][str(world["run"].id)]["components_usd"] or 0) == 0


# --------------------------------------------------------------- charging


def test_charging_a_draw_writes_no_second_draw(db, world):
    """`charge_draws` is an UPDATE. A decision about cost must never restate a
    quantity the supplier reported — that is how the same stock gets counted
    twice."""
    _draw(db, world)
    before = db.query(M.ComponentConsumption).filter_by(lcsc="CTEST001").count()
    plan = {"smt_order_code": "SMTTEST", "batch_num": "WTEST"}
    res = jlc_apply.charge_draws(db, plan, world["run"].id, dry_run=False)
    db.flush()
    assert res["status"] == "charged"
    assert res["uncharged_draws"] == 1
    assert db.query(M.ComponentConsumption).filter_by(lcsc="CTEST001").count() == before
    assert db.query(M.ComponentConsumption).filter_by(lcsc="CTEST001").one().run_id == world["run"].id
    # and the stock did not move again
    assert _pool_row(db)["qty"] == 600


def test_charging_is_visible_in_the_dry_run_without_writing(db, world):
    _draw(db, world)
    plan = {"smt_order_code": "SMTTEST", "batch_num": "WTEST"}
    res = jlc_apply.charge_draws(db, plan, world["run"].id, dry_run=True)
    assert res["status"] == "dry_run"
    assert res["uncharged_draws"] == 1
    assert res["value_usd"] == 40.0
    assert db.query(M.ComponentConsumption).filter_by(lcsc="CTEST001").one().run_id is None


def test_a_draw_already_charged_elsewhere_is_refused(db, world):
    """Silently re-pointing would move money off a batch someone may have
    quoted a margin from."""
    _draw(db, world, run_id=world["other"].id)
    plan = {"smt_order_code": "SMTTEST", "batch_num": "WTEST"}
    with pytest.raises(jlc_apply.ApplyRefused) as e:
        jlc_apply.charge_draws(db, plan, world["run"].id, dry_run=True)
    assert str(world["other"].id) in str(e.value)


def test_charging_the_same_order_twice_is_a_no_op(db, world):
    _draw(db, world)
    plan = {"smt_order_code": "SMTTEST", "batch_num": "WTEST"}
    jlc_apply.charge_draws(db, plan, world["run"].id, dry_run=False)
    db.flush()
    again = jlc_apply.charge_draws(db, plan, world["run"].id, dry_run=False)
    assert again["uncharged_draws"] == 0
    assert again["already_charged"] == 1
    assert _pool_row(db)["qty"] == 600


def test_charging_supersedes_the_bom_forecast_it_replaces(db, world):
    """A forecast belongs to a run, so it can only be retired once a run is
    named — which is the charging step, not the measuring step."""
    forecast = M.ComponentConsumption(
        run_id=world["run"].id, mpn="TEST-PART-1", lcsc="CTEST001", qty=390,
        unit_cost_usd=0.1, basis="bom", consumed_at="2026-03-01", import_ref="")
    db.add(forecast)
    db.flush()
    _draw(db, world)
    plan = {"smt_order_code": "SMTTEST", "batch_num": "WTEST"}
    res = jlc_apply.charge_draws(db, plan, world["run"].id, dry_run=False)
    db.flush()
    assert res["voided_forecasts"] == 1
    db.refresh(forecast)
    assert forecast.voided_at is not None
    assert forecast.void_reason == "superseded_by_measured"
    assert _pool_row(db)["qty"] == 600, "the forecast must not be counted beside its measurement"


# ------------------------------------------------- comparing against JLC


def test_the_snapshot_date_is_read_in_jlcs_calendar(db):
    """JLC dates everything in China time. A snapshot fetched at 19:23 UTC on
    the 5th is the 6th to them — and an order placed five minutes earlier is
    dated the 6th on its own invoice. Cutting on the UTC date excludes a
    purchase the snapshot already counts."""
    ts = datetime(2026, 8, 5, 19, 23, 26, tzinfo=UTC)
    assert ra._jlc_date(ts) == "2026-08-06"
    assert ra._jlc_date(datetime(2026, 8, 5, 15, 0, tzinfo=UTC)) == "2026-08-05"
    assert ra._jlc_date(None) is None


def test_stock_is_compared_at_the_moment_jlc_counted(db, world):
    """The defect this fixes: `delta_qty` subtracted a pool that runs to today
    from a snapshot frozen weeks ago, so every draw made since read as stock JLC
    was holding and we never paid for."""
    # The cutoff is the NEWEST stock row's timestamp, so the scratch row has to be
    # the only one — otherwise the dev database's real sync date decides the test.
    db.query(M.JlcStockItem).delete()
    counted = datetime.now(UTC) - timedelta(days=30)
    db.add(M.JlcStockItem(lcsc="CTEST001", description="scratch", mpn="TEST-PART-1",
                          manufacturer="TESTCO", package="0402", qty=1000,
                          unit_price_usd=0.1, updated_at=counted))
    db.flush()
    # A draw dated AFTER the count. JLC's figure cannot know about it.
    _draw(db, world, qty=400.0,
          when=(counted + timedelta(days=2)).date().isoformat())
    row = next(r for r in ra.parts_stock(db)["parts"] if r["lcsc"] == "CTEST001")
    assert row["remaining_qty"] == 600, "today's pool has the draw"
    assert row["remaining_at_sync_qty"] == 1000, "the comparison instant does not"
    assert row["delta_qty"] == 0, "so the two measurements agree, which they do"


def test_a_real_disagreement_still_shows(db, world):
    """The fix must not silence the thing the page is for."""
    db.query(M.JlcStockItem).delete()
    counted = datetime.now(UTC)
    db.add(M.JlcStockItem(lcsc="CTEST001", description="scratch", mpn="TEST-PART-1",
                          manufacturer="TESTCO", package="0402", qty=940,
                          unit_price_usd=0.1, updated_at=counted))
    db.flush()
    row = next(r for r in ra.parts_stock(db)["parts"] if r["lcsc"] == "CTEST001")
    assert row["remaining_at_sync_qty"] == 1000
    assert row["delta_qty"] == -60, "JLC is 60 short of what we paid for, and says so"


# ------------------------------------------- what "written off" means


def test_another_projects_order_is_not_attrition(db, world):
    """Attrition is a defect signal. Stock consumed by an assembly order for a
    project this platform does not track is not a defect, and counting the two
    together reported 1,094 written-off pieces on 2026-09-18 when the real
    attrition was zero."""
    db.add(M.ComponentStockAdjustment(
        project_id=world["project"].id, mpn="TEST-PART-1", lcsc="CTEST001",
        qty_delta=-30, unit_cost_usd=0.1, reason="external_project",
        charge_run_id=None, adjusted_at="2026-03-02",
        import_ref="jlc:ext:SMTOTHER:CTEST001", note="another project"))
    db.add(M.ComponentStockAdjustment(
        project_id=world["project"].id, mpn="TEST-PART-1", lcsc="CTEST001",
        qty_delta=-5, unit_cost_usd=0.1, reason="attrition",
        charge_run_id=world["run"].id, adjusted_at="2026-03-03",
        note="lost in production"))
    db.flush()
    row = _pool_row(db)
    assert row["external"] == 30
    assert row["lost"] == 5, "only the real loss counts as written off"
    assert row["qty"] == 965, "both still leave the pool"


def test_a_per_device_line_is_billed_on_what_was_ordered(db, world):
    """An assembler is paid for the boards they assembled, not for the devices
    that later passed our test. Scaling by `good_units` made a LIFTECH invoice
    for 350 boards reconcile to 349 and blocked every JLC import."""
    run = world["run"]
    run.qty = 350
    doc = M.RunCostDocument(project_id=world["project"].id, doc_type="invoice",
                            supplier="ASSEMBLER", doc_number="A-1",
                            doc_date="2026-03-01", currency="PLN", total_amount=1750.0,
                            run_id=run.id)
    db.add(doc)
    db.flush()
    li = M.RunCostLine(document_id=doc.id, plan_key="pcba:general", description="5 PLN/board",
                       qty=1, unit_price=5.0, currency="PLN", basis="per_device",
                       run_id=run.id, allocate="none")
    db.add(li)
    db.flush()
    assert ra.planned_units(run) == 350
    assert ra.effective_qty(li, doc, db) == 350
    assert ra.effective_qty(li, doc, db) * li.unit_price == doc.total_amount

    # One device short of the order changes the per-device COST but not the bill.
    dev = M.DeviceUnit(project_id=world["project"].id, serial="D1", mac="00:00:00:aa:bb:01",
                       first_seen=datetime(2026, 3, 1, tzinfo=UTC),
                       production_run_id=run.id)
    db.add(dev)
    db.flush()
    assert ra.good_units(db, run) == 1, "what passed"
    assert ra.planned_units(run) == 350, "what we pay for"
    assert ra.effective_qty(li, doc, db) == 350


# ----------------------------------------- typing in what a batch used


def _set_used(db, run, qty, mpn="TEST-PART-1", lcsc="", component_id=None):
    from app.routers.run_costs import ConsumptionIn, set_used_qty
    return set_used_qty(run.id, ConsumptionIn(component_id=component_id, mpn=mpn,
                                              lcsc=lcsc, qty=qty,
                                              consumed_at="2026-03-05"), db=db)


def test_typing_a_used_quantity_creates_edits_and_removes_one_draw(db, world):
    """The end-of-production workflow: type what was used, correct it later,
    and never accumulate a second row for the same part."""
    from app import models as M2
    run = world["run"]
    res = _set_used(db, run, 400)
    assert res["status"] == "created"
    assert _pool_row(db)["qty"] == 600

    # correcting it is the SAME action, not a compensating adjustment
    res = _set_used(db, run, 380)
    assert res["status"] == "updated" and res["was"] == 400
    assert db.query(M2.ComponentConsumption).filter_by(run_id=run.id).count() == 1
    assert _pool_row(db)["qty"] == 620

    assert _set_used(db, run, 380)["status"] == "unchanged"

    assert _set_used(db, run, 0)["status"] == "removed"
    assert _pool_row(db)["qty"] == 1000


def test_a_typed_draw_is_priced_from_the_pool_it_draws_from(db, world):
    """The bug this guards: `_key` prefers `component_id`, so a caller who knows
    only an MPN produced a key the purchases were not filed under, priced the
    draw at ZERO and split the part into a second pool entry. Found 2026-09-18
    on enclosure 35.0207000.BL — $0.00 against a real $3.70 average."""
    from app import models as M2
    # File the purchase under a COMPONENT id, and draw by MPN alone.
    world["line"].component_id = 4242
    db.flush()
    res = _set_used(db, world["run"], 100)
    assert res["status"] == "created"
    assert res["unit_cost_usd"] == 0.1, "priced from the pool, not zero"
    row = db.query(M2.ComponentConsumption).filter_by(run_id=world["run"].id).one()
    assert row.component_id == 4242, "the draw adopts the pool's identity"
    # one pool entry, not two
    matches = [v for v in ra.pool_state(db).values() if (v.get("lcsc") or "") == "CTEST001"]
    assert len(matches) == 1
    assert matches[0]["qty"] == 900


def test_a_part_jlc_measured_is_not_retyped(db, world):
    """JLC's invoice figure is a measurement of its own consigned stock."""
    from fastapi import HTTPException
    _draw(db, world, qty=400.0, run_id=world["run"].id)   # basis='measured'
    with pytest.raises(HTTPException) as e:
        _set_used(db, world["run"], 380)
    assert "measurement" in str(e.value.detail["error"])


def test_a_part_with_no_pool_entry_is_refused(db, world):
    """A draw for something never bought would invent a pool entry. The
    shortage guard catches it first, which is the same answer with a better
    message — it names what is missing."""
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        _set_used(db, world["run"], 10, mpn="NOT-A-REAL-PART")
    assert e.value.status_code == 409
    assert "insufficient stock" in str(e.value.detail["error"])


# ------------------------------------- what a NEW external order writes


def test_a_legacy_adjustment_counts_as_already_booked(db, world):
    """The 27 pre-0034 rows still hold real stock out of the pool. An order that
    has them must read as booked, or re-applying its decision would write
    uncharged draws on top and take the same stock out twice."""
    from app.routers.jlc_import import _booked, _stock_already_booked
    plan = {"smt_order_code": "SMTEXT", "batch_num": "WEXT"}
    assert _stock_already_booked(db, plan) is False
    db.add(M.ComponentStockAdjustment(
        project_id=world["project"].id, mpn="TEST-PART-1", lcsc="CTEST001",
        qty_delta=-40, unit_cost_usd=0.1, reason="external_project",
        charge_run_id=None, adjusted_at="2026-03-02",
        import_ref="jlc:ext:SMTEXT:CTEST001", note="another project"))
    db.flush()
    assert _stock_already_booked(db, plan) is True
    b = _booked(db, plan)
    assert b["legacy_adjustments"] == 1 and b["draws"] == 0
    assert b["value_usd"] == 4.0


def test_the_migration_changes_shape_and_not_stock(db, world):
    """Rewriting an `external_project` adjustment as an uncharged draw must move
    the same pieces out of the pool, not different ones. Verified on production
    data 2026-09-18: 27 rows, 72 part balances, ZERO changed."""
    db.add(M.ComponentStockAdjustment(
        project_id=world["project"].id, mpn="TEST-PART-1", lcsc="CTEST001",
        qty_delta=-40, unit_cost_usd=0.1, reason="external_project",
        charge_run_id=None, adjusted_at="2026-03-02",
        import_ref="jlc:ext:SMTEXT:CTEST001", note="another project"))
    db.flush()
    before = _pool_row(db)
    assert before["qty"] == 960 and before["external"] == 40 and before["lost"] == 0

    # the shape the migration writes instead
    db.delete(db.query(M.ComponentStockAdjustment)
              .filter_by(import_ref="jlc:ext:SMTEXT:CTEST001").one())
    db.flush()
    _draw(db, world, qty=40.0, ref="jlc:WEXT:SMTEXT:CTEST001", when="2026-03-02")

    after = _pool_row(db)
    assert after["qty"] == before["qty"], "the same pieces left the pool"
    assert after["external"] == 0 and after["lost"] == 0
    assert after["used"] == before["used"] + 40, "counted as a draw now, not an adjustment"


# ------------------------------------------- a cancelled lot is not stock


def test_a_cancelled_lot_never_becomes_stock(db):
    """JLC settles a CANCELLED sub-order with `orderStatus=40` and still reports
    a non-zero `settlePresaleNumber`. Lot 754166 said 3,470 LEDs settled at
    $19.78 and JLC's inventory history shows no receipt for one of them. Testing
    only `settlePresaleNumber <= 0` imported them as stock — 3,470 of the
    3,478-piece gap on C965790, and the largest disagreement in the platform."""
    from app.services import jlc_import
    goods = {"presaleGoodsKeyId": 754166, "componentCode": "C965790",
             "componentModel": "XL-1005SURC", "settlePresaleNumber": 3470,
             "presaleNumber": 3470, "goodsPaidMoney": 19.78, "goodsMoney": 19.78,
             "goodsPrice": 0.0057, "description": ""}
    lot = jlc_import._lot_from_goods(goods, "POB0202410092313194", {}, "buy", 40)
    assert lot["cancelled"] is True
    assert lot["fee_only"] is True, "a cancelled lot is a FEE, never a lot of stock"

    # the same row settled normally is stock, and the money is unchanged
    good = jlc_import._lot_from_goods(goods, "POB0202410092313194", {}, "buy", 30)
    assert good["cancelled"] is False and good["fee_only"] is False
    assert good["qty"] == 3470 and good["paid_usd"] == 19.78

    # a cancelled row that cost nothing is neither stock nor a fee
    free = jlc_import._lot_from_goods({**goods, "goodsPaidMoney": 0, "goodsMoney": 0},
                                      "POB", {}, "buy", 40)
    assert free["cancelled"] is True and free["fee_only"] is False


def test_a_zero_quantity_lot_is_still_a_fee(db):
    """The original guard, kept: two real rows paid $349.39 and $16.01 for zero
    delivered parts."""
    from app.services import jlc_import
    lot = jlc_import._lot_from_goods(
        {"presaleGoodsKeyId": 1, "componentCode": "CX", "componentModel": "X",
         "settlePresaleNumber": 0, "presaleNumber": 500, "goodsPaidMoney": 349.39,
         "goodsMoney": 349.39, "goodsPrice": 0.7, "description": ""},
        "POB", {}, "buy", 30)
    assert lot["fee_only"] is True and lot["unit_cost_usd"] is None
