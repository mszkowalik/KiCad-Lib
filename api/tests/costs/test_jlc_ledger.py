"""JLCPCB's own inventory ledger is the receipt our books are checked against.

Decision record: docs/decisions/0037-the-supplier-keeps-the-receipts.md.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import cost_steps, jlc_apply, jlc_import, jlc_ledger as L


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
def part(db: Session):
    """A scratch part with 1,000 pieces bought on one parts order.

    Every ledger row in these tests belongs to it, and the account's real 648
    rows are cleared so an assertion about "what is unexplained" is about this
    part and not about whatever the dev database last synced.
    """
    db.query(M.JlcStockChange).delete()
    doc = M.RunCostDocument(doc_type="invoice", supplier="JLCPCB",
                            external_id="POBTEST0001", doc_number="LEDGER-1",
                            doc_date="2026-02-01", currency="USD", total_amount=100.0)
    db.add(doc)
    db.flush()
    line = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", label="scratch",
                         lcsc="CLEDGER01", mpn="LEDGER-PART-1", qty=1000,
                         unit_price=0.1, currency="USD", allocate="none",
                         lot_ref="900001")
    db.add(line)
    db.flush()
    return {"doc": doc, "line": line}


def _row(db, *, qty, when="2026-03-01", code="", bt=L.BT_WAREHOUSE, status=2,
         key=None, remark="a movement", lcsc="CLEDGER01"):
    row = M.JlcStockChange(
        change_key_id=key or (abs(hash((qty, when, code, remark))) % 10**9),
        stock_key_id=1, lcsc=lcsc, mpn="LEDGER-PART-1",
        changed_at=datetime.fromisoformat(when).replace(tzinfo=UTC),
        qty_before=0, change_qty=qty, qty_after=qty, paid_usd=0.0,
        business_code=code, business_type=bt, change_type=1, change_status=status,
        remark=remark, raw={})
    db.add(row)
    db.flush()
    return row


# ------------------------------------------------------------------ the rules

def test_a_movement_jlc_cancelled_is_not_a_movement(db, part):
    """`changeStatus=3` states a quantity and moves nothing.

    Two parts in the real account (C157472, C62102) carry such rows, and reading
    them as movements reported a balance JLC does not agree with.
    """
    _row(db, qty=-20, code="T1", status=L.STATUS_VOID, key=900101)
    assert L.bookable(db) == []
    assert L.unexplained(db)["totals"]["unexplained_rows"] == 0


def test_a_warehouse_pick_is_bookable(db, part):
    """A `bussinessType=10` row is on no invoice and in no BOM, so nothing but
    the ledger can ever report it."""
    _row(db, qty=-8, code="T241022013", key=900102,
         remark="pick 8 pcs up to complete SMT order")
    assert [b["qty"] for b in L.bookable(db)] == [8]


def test_a_row_with_no_business_code_is_bookable(db, part):
    """The other shape, found on C157472: no code at all, the reason in prose.
    Twenty pieces "used in 2nd Process", which was that part's whole gap."""
    _row(db, qty=-20, code="", bt=L.BT_PARTS_ORDER, key=900103,
         remark="...-Y20 used 20pcs in 2nd Process")
    assert [b["qty"] for b in L.bookable(db)] == [20]


def test_a_documented_movement_is_never_booked_from_the_ledger(db, part):
    """An SMT order's draw belongs to its invoice. Writing it from the ledger as
    well would take the same stock out twice."""
    _row(db, qty=-40, code="SMT0001", bt=L.BT_SMT_ORDER, key=900104)
    assert L.bookable(db) == []
    assert L.unexplained(db)["totals"]["unexplained_rows"] == 1


def test_a_draw_jlc_gave_back_is_not_a_disagreement(db, part):
    """SMT026061460600 took 20 parts and returned every one the next day — 44
    rows netting to zero. They are noise, not stock that moved."""
    _row(db, qty=-90, code="SMT0002", bt=L.BT_SMT_ORDER, when="2026-06-14", key=900105)
    _row(db, qty=90, code="SMT0002", bt=L.BT_SMT_ORDER, when="2026-06-15", key=900106)
    t = L.unexplained(db)["totals"]
    assert t["unexplained_rows"] == 0
    assert t["netted_out_rows"] == 2


def test_a_purchase_the_ledger_never_received_is_reported(db, part):
    """The cancelled-lot shape: we booked 1,000 pieces, JLC's ledger records no
    receipt for them.

    The part has to be one JLC holds — a row of its ledger says so. A part with
    no ledger at all is simply not consigned, and reporting our own purchase of
    it as unconfirmed would flag every part we buy ourselves.
    """
    _row(db, qty=-40, code="SMT0009", bt=L.BT_SMT_ORDER, key=900112)
    out = L.unexplained(db)["our_lines_jlc_never_received"]
    assert len(out) == 1
    assert out[0]["parts_order"] == "POBTEST0001"
    assert out[0]["missing_qty"] == 1000


def test_a_receipt_the_ledger_confirms_is_not_reported(db, part):
    _row(db, qty=1000, code="POBTEST0001", bt=L.BT_PARTS_ORDER, when="2026-02-01",
         key=900107)
    _row(db, qty=-40, code="SMT0009", bt=L.BT_SMT_ORDER, key=900113)
    assert L.unexplained(db)["our_lines_jlc_never_received"] == []


# ---------------------------------------------------------------- booking

def test_booking_writes_one_uncharged_measured_draw(db, part):
    """Uncharged, because who pays is a separate question (0034). Measured,
    because JLC measured it — which also stops the end-of-production screen
    retyping it."""
    r = _row(db, qty=-8, code="T241022013", when="2026-03-05", key=900108,
             remark="pick 8 pcs up to complete SMT order")
    res = L.book(db, [r.change_key_id], dry_run=False)
    assert res["totals"] == {"rows": 1, "qty": 8, "usd": 0.8}
    row = db.get(M.ComponentConsumption, res["written"][0]["consumption_id"])
    assert row.run_id is None
    assert row.basis == "measured"
    assert row.qty == 8
    assert row.consumed_at == "2026-03-05"
    assert "pick 8 pcs" in row.note
    assert row.import_ref == f"jlcledger:{r.change_key_id}"


def test_booking_the_same_row_twice_is_a_no_op(db, part):
    r = _row(db, qty=-8, code="T2", key=900109)
    L.book(db, [r.change_key_id], dry_run=False)
    again = L.book(db, [r.change_key_id], dry_run=False)
    assert again["written"] == []
    assert again["not_bookable"] == [r.change_key_id]


def test_a_dry_run_writes_nothing(db, part):
    r = _row(db, qty=-8, code="T3", key=900110)
    before = db.query(M.ComponentConsumption).count()
    res = L.book(db, [r.change_key_id], dry_run=True)
    assert res["totals"]["rows"] == 1
    assert db.query(M.ComponentConsumption).count() == before


def test_booking_refuses_more_than_the_pool_holds(db, part):
    """JLC cannot have taken what we never bought — that is a different defect,
    and inventing the stock to satisfy the draw would hide it."""
    r = _row(db, qty=-5000, code="T4", key=900111)
    res = L.book(db, [r.change_key_id], dry_run=True)
    assert res["written"] == []
    assert "does not hold" in res["refused"][0]["why"]


# ------------------------------------------------------- refreshing a purchase

def _lot(**kw):
    base = {"presaleGoodsKeyId": "900001", "componentCode": "CLEDGER01",
            "componentModel": "LEDGER-PART-1", "settlePresaleNumber": 1000,
            "presaleNumber": 1000, "goodsPaidMoney": 100.0, "goodsMoney": 100.0,
            "goodsPrice": 0.1}
    base.update(kw)
    return base


def _plan(status=jlc_import.ORDER_COMPLETE, **kw):
    lots = [jlc_import._lot_from_goods(_lot(**kw), "POBTEST0001",
                                       {"presaleOrderNo": "PF1"}, "buy", status)]
    return jlc_import.plan_parts_document("POBTEST0001", lots,
                                          {"invoiceNo": "LEDGER-1"})


def test_refresh_rewrites_a_cancelled_lot_as_a_fee(db, part):
    """Lot 754166 settled 3,470 LEDs and was then cancelled and refunded. The
    importer refuses a document it already holds, so without this the correction
    could only be made by hand."""
    res = jlc_apply.refresh_parts_document(db, _plan(status=40), dry_run=False)
    assert res["status"] == "refreshed"
    line = db.get(M.RunCostLine, part["line"].id)
    # No longer stock: the STEP says so (decision 0047), and the coarse bucket
    # derives from it.
    assert not cost_steps.is_stock_step(line.plan_key or "")
    assert line.qty == 1
    assert line.unit_price == 100.0
    assert line.lcsc == ""
    assert "CANCELLED" in line.notes


def test_refresh_is_a_no_op_when_jlc_says_the_same_thing(db, part):
    """Applying the same answer twice must change nothing — otherwise every
    refresh writes a journal batch and the history fills with noise."""
    assert jlc_apply.refresh_parts_document(db, _plan(), dry_run=False)["status"] == "refreshed"
    assert jlc_apply.refresh_parts_document(db, _plan(), dry_run=True)["status"] == "unchanged"


def test_refresh_keeps_a_hand_written_annotation(db, part):
    """Line 874 carries the record of why its component was restored to TS3625A.
    Regenerating the note would delete the reason a substitution exists."""
    line = db.get(M.RunCostLine, part["line"].id)
    line.notes = "lot 900001 from PF1 (buy); paid $1 for 1 = $1/pc | component_id restored to 7"
    db.flush()
    jlc_apply.refresh_parts_document(db, _plan(), dry_run=False)
    assert "component_id restored to 7" in db.get(M.RunCostLine, part["line"].id).notes


def test_refresh_refuses_to_shrink_a_line_draws_are_bound_to(db, part):
    """JLC saying the parts never arrived and the platform saying they were used
    is a contradiction a human settles, not an UPDATE."""
    draw = M.ComponentConsumption(run_id=None, lcsc="CLEDGER01", mpn="LEDGER-PART-1",
                                  qty=10, unit_cost_usd=0.1, basis="measured",
                                  consumed_at="2026-03-01")
    db.add(draw)
    db.flush()
    db.add(M.ComponentConsumptionLot(consumption_id=draw.id, lot_line_id=part["line"].id,
                                     qty=10, unit_cost_usd=0.1, source="test"))
    db.flush()
    res = jlc_apply.refresh_parts_document(db, _plan(status=40), dry_run=True)
    assert res["status"] == "refused"
    assert "draw(s) are bound to it" in res["blockers"][0]


def test_refresh_refuses_a_lot_jlc_no_longer_reports(db, part):
    """A key mismatch, not a deletion — and deleting a purchase silently is how
    a pool loses stock it really has."""
    plan = _plan()
    plan["lines"][0]["lot_ref"] = "900999"
    res = jlc_apply.refresh_parts_document(db, plan, dry_run=True)
    assert res["status"] == "refused"
    assert any("no longer reports" in b for b in res["blockers"])


# ------------------------------------------- a lot JLC is still sourcing

def _awaiting_plan(pob="POBTEST0002", key="900002"):
    """POB0202609230016917 lot 2182682 as JLC reported it on 2026-09-24: paid,
    `settlePresaleNumber` already equal to the order, nothing in storage."""
    goods = {"presaleGoodsKeyId": key, "componentCode": "CLEDGER02",
             "componentModel": "LEDGER-PART-2", "settlePresaleNumber": 4000,
             "presaleNumber": 4000, "goodsPaidMoney": 2384.0, "goodsMoney": 2384.0,
             "goodsPrice": 0.596, "inStorageNumber": 0}
    return goods, [jlc_import._lot_from_goods(goods, pob, {"presaleOrderNo": "PF2"}, "buy", 20)]


def test_a_lot_still_being_sourced_is_money_not_stock(db):
    _goods, lots = _awaiting_plan()
    assert lots[0]["awaiting"] is True
    assert lots[0]["cancelled"] is False and lots[0]["fee_only"] is False
    plan = jlc_import.plan_parts_document("POBTEST0002", lots, {"invoiceNo": "AW-1"})
    [line] = plan["lines"]
    assert line["plan_key"] == jlc_import.STEP_AWAITING
    assert not cost_steps.is_stock_step(line["plan_key"])
    assert line["allocate"] == "excluded" and line["exclude_reason"] == "awaiting_delivery"
    assert line["lcsc"] == "" and line["qty"] == 1 and line["unit_price"] == 2384.0
    # the document still reconciles to what left the bank
    assert plan["total_amount"] == 2384.0 and plan["lot_count"] == 0
    assert plan["awaiting_count"] == 1


def test_an_imported_lot_is_pool_stock(db):
    """The importer wrote no `plan_key` from 2026-09-19 (decision 0047) until
    2026-09-24, so a whole parts order landed as unassigned money."""
    lots = [jlc_import._lot_from_goods(_lot(presaleGoodsKeyId="900003"), "POBTEST0003",
                                       {"presaleOrderNo": "PF3"}, "stock",
                                       jlc_import.ORDER_COMPLETE)]
    plan = jlc_import.plan_parts_document("POBTEST0003", lots, {"invoiceNo": "AW-3"})
    before = jlc_apply.identity_snapshot(db)
    res = jlc_apply.apply_parts_document(db, plan)
    assert res["status"] == "created"
    line = db.query(M.RunCostLine).filter_by(document_id=res["document_id"]).one()
    assert line.plan_key == "parts:pool" and line.allocate == "pooled"
    after = res["identities"]
    assert round(after["pool_purchased_usd"] - before["pool_purchased_usd"], 4) == 100.0
    assert round(after["unassigned_usd"] - before["unassigned_usd"], 4) == 0.0


def test_a_refresh_turns_an_arrived_lot_into_stock(db):
    goods, lots = _awaiting_plan()
    plan = jlc_import.plan_parts_document("POBTEST0002", lots, {"invoiceNo": "AW-1"})
    before = jlc_apply.identity_snapshot(db)
    doc_id = jlc_apply.apply_parts_document(db, plan)["document_id"]
    mid = jlc_apply.identity_snapshot(db)
    assert round(mid["pool_purchased_usd"] - before["pool_purchased_usd"], 4) == 0.0

    arrived = {**goods, "inStorageNumber": 4000}
    lots = [jlc_import._lot_from_goods(arrived, "POBTEST0002", {"presaleOrderNo": "PF2"},
                                       "buy", jlc_import.ORDER_COMPLETE)]
    plan = jlc_import.plan_parts_document("POBTEST0002", lots, {"invoiceNo": "AW-1"})
    res = jlc_apply.refresh_parts_document(db, plan, dry_run=False)
    assert res["status"] == "refreshed"
    line = db.query(M.RunCostLine).filter_by(document_id=doc_id).one()
    assert line.plan_key == "parts:pool" and line.allocate == "pooled"
    assert line.exclude_reason == ""
    assert line.lcsc == "CLEDGER02" and line.qty == 4000
    assert round(res["identities"]["pool_purchased_usd"] - mid["pool_purchased_usd"], 4) == 2384.0


def test_a_refresh_leaves_a_hand_set_destination_alone(db, part):
    """Only a lot that changed what it IS moves its money. A line a person
    charged somewhere keeps that choice across a refresh."""
    line = db.get(M.RunCostLine, part["line"].id)
    line.allocate = "excluded"
    line.exclude_reason = "external_project"
    db.flush()
    jlc_apply.refresh_parts_document(db, _plan(), dry_run=False)
    line = db.get(M.RunCostLine, part["line"].id)
    assert line.allocate == "excluded" and line.exclude_reason == "external_project"
    assert line.plan_key == "parts:pool"


# ------------------------------------------------- how many boards JLC built

def _person(paste, patched, patch_type, panel=(1, 1)):
    return {"unionOrderInfoVOList": [
        {"orderCode": "SMTX", "myOrdersRecord": {"detail": {"smtDetail": {
            "smtOrderCode": "SMTX", "produceOrderCode": "PX", "pasteNumber": paste,
            "allPatchNum": patched, "patchType": patch_type}}}},
        {"orderCode": "PX", "myOrdersRecord": {"detail": {"pcbDetail": {
            "panelX": panel[0], "panelY": panel[1]}}}},
    ]}


def test_devices_are_the_boards_assembled_not_fabricated():
    """SMT026092263197: 75 boards fabricated, 60 populated. The invoice bills 60
    and the order drew exactly 60 of every once-per-board part."""
    from app.services import jlc_web
    info = jlc_web.panel_factors(_person(75, 60, "no"))["SMTX"]
    assert info["devices"] == 60 and info["panels"] == 60
    assert info["panels_fabricated"] == 75 and info["partial_assembly"] is True
    assert info["panels_source"] == "allPatchNum"
    # a panelised order multiplies the ASSEMBLED count
    assert jlc_web.panel_factors(_person(250, 250, "all", (2, 2)))["SMTX"]["devices"] == 1000


def test_repair_adds_a_missing_lot_the_way_the_importer_would(db, part):
    """`reprice_from_jlc` adds lots no line records. It wrote its own line and
    no step, so an added lot would have been unassigned money, and a lot JLC
    was still sourcing would have become stock."""
    _goods, lots = _awaiting_plan(pob="POBTEST0001", key="900004")
    fine = jlc_import._lot_from_goods(_lot(), "POBTEST0001", {"presaleOrderNo": "PF1"},
                                      "buy", jlc_import.ORDER_COMPLETE)
    res = jlc_apply.reprice_from_jlc(db, {"900001": fine, "900004": lots[0]}, dry_run=True)
    # the lot the document already records, correctly, is NOT added again
    [added] = res["added_lines"]
    assert added["plan_key"] == jlc_import.STEP_AWAITING and added["awaiting"] is True



def test_a_sub_cent_rounding_gap_still_closes_the_line():
    """SMT026092263197 printed 60 x 28.0097 = 1680.582 against fees summing to
    1680.5845. Without a delta child the children sat $0.0025 over the parent."""
    inv = {"lines": [{"stage": "pcba", "total": 1680.582, "presale": 1218.98,
                      "order_code": "SMTX-P50", "smt_order_code": "SMTX"}]}
    fees = {"SMTX": {"kind": "smt", "dummy": 461.6045, "extra": 0,
                     "spi": {"padMoney": 461.6045}}}
    kids = jlc_import.fee_children_plan(inv, fees)["SMTX-P50"]
    assert round(sum(k["amount"] for k in kids), 4) == round(1680.582 - 1218.98, 4)
    [delta] = [k for k in kids if k["slug"] == "delta"]
    assert delta["amount"] == -0.0025 and "Rounding" in delta["label"]
