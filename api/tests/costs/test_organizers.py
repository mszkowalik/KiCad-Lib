"""What a box in an office organizer holds (decision 0104).

A box says where the pieces are; the material ledger says what they cost.
`test_pieces_in_a_box_are_not_missing_from_jlc` holds the Stock page comparison.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_organizers.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import journal, organizers as O
from app.services import run_actuals as ra

MPN = "TEST-ORG-1"
LCSC = "CORGTEST1"


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


def _company(db, key):
    c = db.query(M.Company).filter_by(key=key).first()
    if c is None:
        c = M.Company(key=key, name=key)
        db.add(c)
        db.flush()
    return c


@pytest.fixture
def world(db):
    """Two companies, one project, one purchase of 300 scratch pieces, one box."""
    seven, nine = _company(db, "7sigma"), _company(db, "9sigma")
    proj = M.Project(name="test-organizers", git_url="https://example.invalid/o.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="O1", run_date="2026-03-01", status="completed", qty=10,
                          company_id=seven.id)
    other = M.ProductionRun(project_id=proj.id, label="O2", run_date="2026-03-01", status="completed", qty=10,
                            company_id=nine.id)
    db.add_all([run, other])
    db.flush()
    doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="O-1", doc_date="2026-02-01",
                            currency="USD", total_amount=30.0, company_id=seven.id)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", description="scratch", lcsc=LCSC, mpn=MPN,
                         qty=300, unit_price=0.1, currency="USD", allocate="none"))
    db.flush()
    box = O.make_boxes(db, "Test", ["T1"])[0]
    other_box = O.make_boxes(db, "Test", ["T2"])[0]
    it = O.part_item(db, None, MPN, LCSC)
    return dict(seven=seven, nine=nine, proj=proj, run=run, other=other, box=box, other_box=other_box, it=it)


def _pool(db, lcsc=LCSC):
    for v in ra.pool_state(db).values():
        if (v.get("lcsc") or "") == lcsc:
            return v
    return None


def _pool_mpn(db, mpn="TEST-ORG-SPLIT"):
    return next(v for v in ra.pool_state(db).values() if (v.get("mpn") or "") == mpn)


def _jlc(db, qty, lcsc=LCSC, mpn=MPN):
    db.add(M.JlcStockItem(lcsc=lcsc, mpn=mpn, qty=qty, raw={}))
    db.flush()


def _row(db, lcsc=LCSC):
    return next(r for r in ra.parts_stock(db)["parts"] if r["lcsc"] == lcsc)


# ------------------------------------------------------------ the JLC comparison


def test_pieces_in_a_box_are_not_missing_from_jlc(db, world):
    """Work list row 54: bought 300, 100 of them in the office, JLC holds 200.
    The comparison must close with no stock adjustment."""
    _jlc(db, 200)
    assert _row(db)["delta_qty"] == -100, "the alert this change removes"
    O.set_count(db, world["box"], world["it"], world["seven"].id, 100)
    row = _row(db)
    assert row["delta_qty"] == 0
    assert row["house_qty"] == 100
    assert row["house_boxes"] == [{"code": "T1", "qty": 100}]
    assert row["expected_at_jlc_qty"] == 200
    assert db.query(M.Adjustment).filter_by(lcsc=LCSC).count() == 0
    assert _pool(db)["qty"] == 300


def test_one_part_under_two_cards_compares_once_with_jlc(db, world):
    """TS3625A and KH-6X6X5H-STM both hold C2837531: 2250 + 3054 = what JLC counted."""
    first, second = (M.Component(name=n) for n in ("TWO-CARDS-A", "TWO-CARDS-B"))
    db.add_all([first, second])
    db.flush()
    doc = M.RunCostDocument(doc_type="invoice", supplier="JLCPCB", doc_date="2026-01-01", currency="USD",
                            fx_rate_usd=1.0, company_id=world["seven"].id, doc_number="TWO-CARDS")
    db.add(doc)
    db.flush()
    for comp, qty in ((first, 2250), (second, 3054)):
        db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", allocate="pooled", basis="per_run", qty=qty,
                             unit_price=0.01, component_id=comp.id, lcsc="C7777777", mpn=""))
    db.add(M.JlcStockItem(lcsc="C7777777", qty=5304, unit_price_usd=0.02, raw={}))
    db.flush()
    report = ra.parts_stock(db)
    rows = [r for r in report["parts"] if r["component_id"] in (first.id, second.id)]
    assert sorted(r["held_qty"] for r in rows) == [2250, 3054]
    assert all(r["delta_qty"] == 0 for r in rows)


def test_a_real_loss_at_jlc_still_shows(db, world):
    _jlc(db, 150)
    O.set_count(db, world["box"], world["it"], world["seven"].id, 100)
    assert _row(db)["delta_qty"] == -50


def test_the_comparison_reads_the_boxes_at_the_jlc_count(db, world):
    """A box dated after JLC's count did not exist when JLC counted."""
    _jlc(db, 200)
    O.set_count(db, world["box"], world["it"], world["seven"].id, 100, at="2099-01-01")
    row = _row(db)
    assert row["house_qty"] == 100
    assert row["delta_qty"] == -100


# ------------------------------------------------------------ a count


def test_a_count_uses_the_pools_pieces_first(db, world):
    """The pool holds 300 and JLC none: a box of 80 found 80 of those 300."""
    res = O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    assert res["found"] == 0
    assert _pool(db)["qty"] == 300


def test_a_count_above_the_pool_enters_at_zero_value(db, world):
    """More pieces than any purchase covers. Nobody knows what they cost."""
    _jlc(db, 250)
    res = O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    assert res["found"] == 30
    adj = db.query(M.Adjustment).filter_by(lcsc=LCSC).one()
    assert (adj.qty, adj.unit_cost_usd, adj.reason, adj.company_id) == (30, 0.0, "found", world["seven"].id)
    assert _pool(db)["qty"] == 330
    assert _row(db)["delta_qty"] == 0


def test_a_part_no_purchase_ever_named_enters_the_pool(db, world):
    it = O.part_item(db, None, "TEST-ORG-NOINVOICE", "")
    res = O.set_count(db, world["box"], it, world["nine"].id, 7, opening=True)
    assert res["found"] == 7
    adj = db.query(M.Adjustment).filter_by(mpn="TEST-ORG-NOINVOICE").one()
    assert (adj.reason, adj.unit_cost_usd) == ("opening_balance", 0.0)


def test_a_lower_count_writes_the_loss_off(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    res = O.set_count(db, world["box"], world["it"], world["seven"].id, 75)
    assert res["written_off"] == 5
    adj = db.query(M.Adjustment).filter_by(lcsc=LCSC).one()
    assert (adj.qty, adj.reason, adj.run_id) == (-5, "miscount", None)
    assert _pool(db)["qty"] == 295


def test_the_same_count_twice_changes_nothing(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    n = db.query(M.OrganizerMove).count()
    assert O.set_count(db, world["box"], world["it"], world["seven"].id, 80)["changed"] is False
    assert db.query(M.OrganizerMove).count() == n


# ------------------------------------------------------------ a take


def test_research_is_a_cost_no_batch_pays(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    res = O.take(db, world["box"], world["it"], 10, "research", note="LNA test board")
    assert res["company_id"] == world["seven"].id, "one company holds it, so nobody is asked"
    assert res["left"] == 70
    assert res["value_usd"] == pytest.approx(1.0)
    draw = db.get(M.Draw, res["draw_id"])
    assert (draw.run_id, draw.basis, draw.company_id) == (None, "research", world["seven"].id)
    assert _pool(db)["qty"] == 290
    assert O.balance(db, world["box"].id, world["it"].id, world["seven"].id) == 70
    pool = ra.invoice_register(db)["pool"]
    assert pool["research_drawn_usd"] >= 1.0


def test_research_does_not_read_as_waiting_for_a_batch(db, world):
    before = ra.invoice_register(db)["pool"]["uncharged_drawn_usd"]
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    O.take(db, world["box"], world["it"], 10, "research", note="x")
    assert ra.invoice_register(db)["pool"]["uncharged_drawn_usd"] == before


def test_research_says_what_it_was(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    with pytest.raises(HTTPException) as e:
        O.take(db, world["box"], world["it"], 1, "research", note="  ")
    assert e.value.status_code == 422


def test_a_take_for_a_batch_charges_it(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    res = O.take(db, world["box"], world["it"], 5, "batch", run_id=world["run"].id)
    draw = db.get(M.Draw, res["draw_id"])
    assert (draw.run_id, draw.basis, draw.taken) == (world["run"].id, "manual", 5)


def test_a_batch_takes_from_its_own_company(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    with pytest.raises(HTTPException) as e:
        O.take(db, world["box"], world["it"], 5, "batch", run_id=world["other"].id)
    assert e.value.status_code == 422
    assert "other company" in e.value.detail


def test_a_closed_batch_cannot_be_charged(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    world["run"].closed_at = M.utcnow()
    db.flush()
    with pytest.raises(HTTPException) as e:
        O.take(db, world["box"], world["it"], 5, "batch", run_id=world["run"].id)
    assert e.value.status_code == 409


def test_a_crafted_batch_is_drawn_by_its_steps_not_twice(db, world):
    """Decision 0060: its process steps draw from the pool. The take moves the box."""
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    world["run"].process_version_id = 999999
    db.flush()
    res = O.take(db, world["box"], world["it"], 5, "batch", run_id=world["run"].id)
    assert res["draw_id"] is None
    assert _pool(db)["qty"] == 300
    assert O.balance(db, world["box"].id, world["it"].id, world["seven"].id) == 75


def test_both_companies_in_one_box_must_be_told_apart(db, world):
    """User decision 2026-11-07: asked only when both hold the part."""
    O.set_count(db, world["box"], world["it"], world["seven"].id, 20)
    O.set_count(db, world["box"], world["it"], world["nine"].id, 10)
    with pytest.raises(HTTPException) as e:
        O.take(db, world["box"], world["it"], 1, "research", note="x")
    assert e.value.status_code == 422
    res = O.take(db, world["box"], world["it"], 1, "research", note="x", company_id=world["nine"].id)
    assert res["company_id"] == world["nine"].id
    assert res["left"] == 9


def test_a_box_gives_only_what_it_holds(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 3)
    with pytest.raises(HTTPException) as e:
        O.take(db, world["box"], world["it"], 4, "research", note="x")
    assert e.value.status_code == 409


def test_a_user_of_one_company_sees_only_its_pieces(db, world):
    O.set_count(db, world["box"], world["it"], world["nine"].id, 10)
    with pytest.raises(HTTPException):
        O.take(db, world["box"], world["it"], 1, "research", note="x", allowed=[world["seven"].id])
    view = O.overview(db, [world["seven"].id])
    assert not [p for b in view["boxes"] if b["id"] == world["box"].id for p in b["parts"]]
    assert world["box"].id in {b["id"] for b in view["boxes"]}, "the box itself is shared"


def test_pieces_used_for_research_with_no_box(db, world):
    res = O.research_use(db, world["it"], 40, world["seven"].id, note="prototype run", at="2026-03-01")
    assert res["value_usd"] == pytest.approx(4.0)
    assert _pool(db)["qty"] == 260
    row = next(r for r in O.research_list(db) if r["id"] == res["draw_id"])
    assert (row["box"], row["qty"], row["company_id"]) == ("", 40, world["seven"].id)
    with pytest.raises(HTTPException):
        O.research_use(db, world["it"], 1, world["seven"].id, note=" ")


def test_a_project_outside_the_platform_reads_as_uncharged_not_as_research(db, world):
    before = ra.invoice_register(db)["pool"]
    res = O.research_use(db, world["it"], 10, world["seven"].id, note="Vumo order", at="2026-03-01", purpose="external")
    assert db.get(M.Draw, res["draw_id"]).basis == "external"
    after = ra.invoice_register(db)["pool"]
    assert after["uncharged_drawn_usd"] == pytest.approx(before["uncharged_drawn_usd"] + 1.0)
    assert after["research_drawn_usd"] == before["research_drawn_usd"]
    assert res["draw_id"] not in {r["id"] for r in O.research_list(db)}


def test_a_loss_is_the_buyers_and_no_batch_or_research_pays_it(db, world):
    before = ra.invoice_register(db)["pool"]
    res = O.write_off(db, world["it"], 10, world["seven"].id, note="Prototypes that left for CE testing", at="2026-03-01")
    row = db.get(M.Adjustment, res["adjustment_id"])
    assert (row.reason, row.qty, row.company_id) == ("scrap", -10, world["seven"].id)
    assert row.run_id is None and row.project_id is None
    after = ra.invoice_register(db)["pool"]
    assert after["research_drawn_usd"] == before["research_drawn_usd"]
    assert after["uncharged_drawn_usd"] == before["uncharged_drawn_usd"]
    assert after["on_hand_usd"] == pytest.approx(before["on_hand_usd"] - 1.0)
    assert after["balanced"]
    with pytest.raises(HTTPException):
        O.write_off(db, world["it"], 1, world["seven"].id, note=" ")


def test_a_skipped_invoice_reaches_the_pool_the_boxes_and_research(db, world):
    """The load of 2026-11: one excluded line becomes its parts and its shipping.
    What a box holds stays, the rest goes to R&D, and the pool ends at the boxes."""
    from app.routers import run_costs as rc

    doc = M.RunCostDocument(doc_type="invoice", supplier="TESTCO", doc_number="O-2", doc_date="2025-05-01",
                            currency="USD", total_amount=25.0, company_id=world["seven"].id)
    db.add(doc)
    db.flush()
    line = M.RunCostLine(document_id=doc.id, plan_key="other:general", description="components", qty=1,
                         unit_price=25.0, currency="USD", allocate="excluded", exclude_reason="external_project")
    db.add(line)
    db.flush()
    rc.split_line_core(line.id, rc.SplitIn(children=[
        rc.ChildIn(mpn="TEST-ORG-SPLIT", qty=20, unit_price=1.0, plan_key="parts:pool", allocate="pooled"),
        rc.ChildIn(label="Shipping", qty=1, unit_price=5.0, plan_key="logistics:inbound", allocate="by_value"),
    ], allow_parts=True), db)
    db.flush()
    part = O.part_item(db, None, "TEST-ORG-SPLIT", "")
    assert _pool_mpn(db)["qty"] == 20
    assert _pool_mpn(db)["value_usd"] == pytest.approx(25.0), "the shipping is in the landed cost"
    assert O.set_count(db, world["box"], part, world["seven"].id, 8, opening=True, at="2026-03-04")["found"] == 0
    O.research_use(db, part, 12, world["seven"].id, note="used before Henry", at="2025-05-01")
    entry = _pool_mpn(db)
    assert entry["qty"] == 8
    assert entry["value_usd"] == pytest.approx(10.0)
    pool = ra.invoice_register(db)["pool"]
    assert pool["balanced"]


# ------------------------------------------------------------ a move


def test_a_move_leaves_the_pool_alone(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    O.move(db, world["box"], world["other_box"], world["it"], 30)
    assert O.balance(db, world["box"].id, world["it"].id, world["seven"].id) == 50
    assert O.balance(db, world["other_box"].id, world["it"].id, world["seven"].id) == 30
    assert _pool(db)["qty"] == 300


def test_a_part_moved_away_leaves_the_list_and_one_used_up_stays(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 2)
    O.take(db, world["box"], world["it"], 2, "research", note="x")
    def parts(box_id):
        return [p for b in O.overview(db)["boxes"] if b["id"] == box_id for p in b["parts"]]
    assert parts(world["box"].id)[0]["qty"] == 0, "the box still belongs to the part it ran out of"
    O.clear(db, world["box"], world["it"])
    assert parts(world["box"].id) == []


def test_a_box_with_pieces_cannot_be_cleared(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 2)
    with pytest.raises(HTTPException):
        O.clear(db, world["box"], world["it"])


# ------------------------------------------------------------ the import


def _rows(world):
    return [
        {"organizer": "Sheet", "code": "1", "mpn": MPN, "lcsc": LCSC, "company_id": world["seven"].id,
         "qty": 100, "note": "Murata"},
        {"organizer": "Sheet", "code": "2", "mpn": "TEST-ORG-OLD", "company_id": world["seven"].id, "qty": 9},
        {"organizer": "Sheet", "code": "3"},
    ]


def test_an_import_reads_and_a_second_run_writes_nothing(db, world):
    res = O.import_rows(db, _rows(world), at="2026-03-04", actor="t")
    assert res["totals"]["written"] == 2
    assert res["totals"]["boxes_made"] == 3
    assert res["totals"]["found_pieces"] == 9
    opening = db.query(M.OrganizerMove).filter_by(kind="opening", item_id=world["it"].id).one()
    assert (opening.at, opening.note) == ("2026-03-04", "Murata")
    n = db.query(M.OrganizerMove).count()
    again = O.import_rows(db, _rows(world), at="2026-03-04", actor="t")
    assert again["totals"]["written"] == 0
    assert again["totals"]["already_imported"] == 2
    assert db.query(M.OrganizerMove).count() == n


def test_an_import_is_one_reversible_write(db, world):
    with journal.batch(db, kind="organizer.import", source_ref="t", actor="t") as h:
        O.import_rows(db, _rows(world), at="2026-03-04", actor="t")
    db.flush()
    assert db.query(M.OrganizerBox).filter_by(organizer="Sheet").count() == 3
    res = journal.reverse(db, h["batch_id"], actor="t", dry_run=False)
    assert res["status"] == "reversed", res["blockers"]
    db.flush()
    assert db.query(M.OrganizerBox).filter_by(organizer="Sheet").count() == 0
    assert db.query(M.Adjustment).filter_by(mpn="TEST-ORG-OLD").count() == 0
    assert _pool(db)["qty"] == 300


def test_a_take_is_one_reversible_write(db, world):
    O.set_count(db, world["box"], world["it"], world["seven"].id, 80)
    with journal.batch(db, kind="organizer.take", source_ref="t", actor="t") as h:
        O.take(db, world["box"], world["it"], 10, "research", note="x")
    db.flush()
    res = journal.reverse(db, h["batch_id"], actor="t", dry_run=False)
    assert res["status"] == "reversed", res["blockers"]
    db.flush()
    assert O.balance(db, world["box"].id, world["it"].id, world["seven"].id) == 80
    assert _pool(db)["qty"] == 300


def test_deleting_a_box_can_be_undone_and_leaves_the_import_reversible(db, world):
    """A delete outside the journal blocked the undo of the import that made the box."""
    from app.routers.organizers import delete_box

    with journal.batch(db, kind="organizer.import", source_ref="t", actor="t") as made:
        O.make_boxes(db, "Sheet", ["Z9"], "t")
    db.flush()
    box = db.query(M.OrganizerBox).filter_by(organizer="Sheet", code="Z9").one()
    before = {b.id for b in db.query(M.WriteBatch).all()}
    delete_box(box.id, db=db)
    deleted = (set(b.id for b in db.query(M.WriteBatch).all()) - before).pop()

    assert journal.reverse(db, deleted, actor="t", dry_run=False)["status"] == "reversed"
    db.flush()
    assert db.query(M.OrganizerBox).filter_by(organizer="Sheet", code="Z9").count() == 1
    res = journal.reverse(db, made["batch_id"], actor="t", dry_run=False)
    assert res["status"] == "reversed", res["blockers"]


def test_an_import_row_with_no_box_code_is_refused_by_name(db, world):
    with pytest.raises(HTTPException) as e:
        O.import_rows(db, [{"organizer": "Sheet", "code": " "}], at="2026-03-04", actor="t")
    assert e.value.status_code == 422 and "row 1" in str(e.value.detail)
