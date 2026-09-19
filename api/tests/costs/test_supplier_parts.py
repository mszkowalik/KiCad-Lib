"""The supplier's parts lump is a small BOM, and coverage is checkable.

Decision record:
docs/decisions/0041-the-supplier-parts-lump-is-a-small-bom.md.

Every constant here was measured on the 46 cached JLC BOMs on 2026-09-19, not
assumed. The three that matter:

* `extPrice == unitPrice * shopStock` on 1021 of 1021 priced rows;
* `componentSource` has THREE values — the mixed one carries most of the money;
* `componentNum` is per PANEL and must never be used as a piece count.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import supplier_parts as sp


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


def row(**kw):
    """One JLC BOM row with the fields this module reads."""
    base = {"componentCode": "C1", "componentModelEn": "PART-1", "designator": "R1",
            "componentSource": "shop", "componentNum": 0, "componentRealCount": 0,
            "presaleStock": 0, "shopStock": 0, "unitPrice": 0.0, "extPrice": 0.0,
            "lossNumber": 0}
    base.update(kw)
    return base


# ------------------------------------------------------------ the three sources

def test_a_presale_position_is_not_billed_and_is_left_out():
    """Nothing was charged for it, so a zero-value child would be noise."""
    bom = [row(componentSource="preSale", componentRealCount=1610,
               presaleStock=1610, unitPrice=0.0, extPrice=0.0)]
    assert sp.supplier_lines_from_bom(bom) == []


def test_a_mixed_position_is_billed_on_the_shop_portion_only():
    """The real C319148 on SMT026090162303: 800 needed, 500 ours, 300 theirs,
    78.72 charged — which is 0.2624 x 300, not x 800."""
    bom = [row(componentCode="C319148", componentModelEn="U262-161N-4BVC11",
               componentSource="preSaleAndShop", componentNum=200,
               componentRealCount=800, presaleStock=500, shopStock=300,
               unitPrice=0.2624, extPrice=78.72)]
    c, = sp.supplier_lines_from_bom(bom)
    assert c["qty_supplied"] == 300
    assert c["qty_from_pool"] == 500
    assert c["amount"] == pytest.approx(78.72)
    assert c["price_checks"] is True


def test_the_mixed_source_is_not_skipped():
    """It carried 1796.16 of a 2097.28 lump. Treating the lump as shop-only
    would have missed six sevenths of it."""
    bom = [row(componentSource="preSaleAndShop", shopStock=10,
               componentRealCount=10, unitPrice=1.0, extPrice=10.0)]
    assert len(sp.supplier_lines_from_bom(bom)) == 1


def test_component_num_is_never_used_as_a_quantity():
    """It is per PANEL: 200 on a position that really needs 800 pieces."""
    bom = [row(componentSource="preSaleAndShop", componentNum=200,
               componentRealCount=800, presaleStock=500, shopStock=300,
               unitPrice=0.2624, extPrice=78.72)]
    c, = sp.supplier_lines_from_bom(bom)
    assert 200 not in (c["qty_supplied"], c["qty_from_pool"], c["qty_total"])


def test_a_price_that_does_not_match_the_shop_quantity_is_flagged():
    """The rule held on every priced row in the account; a break means JLC
    changed how it bills, and that must surface rather than be absorbed."""
    bom = [row(shopStock=10, componentRealCount=10, unitPrice=1.0, extPrice=99.0)]
    c, = sp.supplier_lines_from_bom(bom)
    assert c["price_checks"] is False


def test_supplier_numbers_that_disagree_are_flagged_not_reconciled():
    """103 real rows across 8 orders do this, and freeStock does not close it."""
    bom = [row(componentRealCount=44, presaleStock=0, shopStock=22, lossNumber=10,
               unitPrice=1.0, extPrice=22.0)]
    c, = sp.supplier_lines_from_bom(bom)
    assert c["supplier_mismatch"] is True
    assert c["price_checks"] is True      # the MONEY is still exact


# ------------------------------------------------------------------- coverage

@pytest.fixture
def world(db: Session):
    """One run, one linked order, three positions: ours, theirs, and mixed."""
    proj = M.Project(name="test-supply", git_url="https://example.invalid/s.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="S1", run_date="2026-03-01",
                          status="completed", qty=100)
    db.add(run)
    db.flush()
    bom = [
        row(componentCode="CPOOL", componentSource="preSale",
            componentRealCount=100, presaleStock=100),
        row(componentCode="CSHOP", componentSource="shop",
            componentRealCount=100, shopStock=100, unitPrice=1.0, extPrice=100.0),
        row(componentCode="CBOTH", componentSource="preSaleAndShop",
            componentRealCount=100, presaleStock=60, shopStock=40,
            unitPrice=1.0, extPrice=40.0),
    ]
    db.add(M.JlcImport(kind="assembly", external_id="WTEST1",
                       bom_info={"SMTTEST1": bom}))
    db.add(M.JlcOrderDecision(smt_order_code="SMTTEST1", outcome="link_run",
                              run_id=run.id))
    db.flush()
    return {"run": run}


def _draw(db, run, lcsc, qty):
    db.add(M.ComponentConsumption(run_id=run.id, mpn="", lcsc=lcsc, qty=qty,
                                  unit_cost_usd=1.0, basis="bom",
                                  consumed_at="2026-03-01"))
    db.flush()


def test_every_position_covered_once_reads_ok(db: Session, world):
    run = world["run"]
    _draw(db, run, "CPOOL", 100)
    _draw(db, run, "CBOTH", 60)          # only our share of the mixed position
    out = sp.coverage(db, run)
    assert out["counts"] == {"ok": 3}


def test_a_draw_for_a_supplier_supplied_part_is_the_double_charge(db: Session, world):
    """Exactly what `void_shop_draws` was written to undo by hand."""
    run = world["run"]
    _draw(db, run, "CPOOL", 100)
    _draw(db, run, "CBOTH", 60)
    _draw(db, run, "CSHOP", 100)
    out = sp.coverage(db, run)
    verdicts = {r["lcsc"]: r["verdict"] for r in out["rows"]}
    assert verdicts["CSHOP"] == "drawn_but_supplier_supplied"


def test_our_share_of_a_mixed_position_must_still_be_drawn(db: Session, world):
    """Drawing the WHOLE position charges us for the supplier's share too."""
    run = world["run"]
    _draw(db, run, "CPOOL", 100)
    _draw(db, run, "CBOTH", 100)
    verdicts = {r["lcsc"]: r["verdict"] for r in sp.coverage(db, run)["rows"]}
    assert verdicts["CBOTH"] == "over_drawn"


def test_a_position_we_supplied_and_never_drew_is_reported(db: Session, world):
    run = world["run"]
    _draw(db, run, "CBOTH", 60)
    verdicts = {r["lcsc"]: r["verdict"] for r in sp.coverage(db, run)["rows"]}
    assert verdicts["CPOOL"] == "no_draw"


def test_a_run_with_no_cached_bom_says_so_instead_of_guessing(db: Session):
    proj = M.Project(name="test-supply-2", git_url="https://example.invalid/t.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="S2", run_date="2026-03-01",
                          status="completed", qty=10)
    db.add(run)
    db.flush()
    out = sp.coverage(db, run)
    assert out["known"] is False and out["rows"] == []


def test_a_draw_the_supplier_bom_never_mentions_is_reported_not_judged(db: Session, world):
    """Packaging, an off-board part, or a draw on the wrong batch — the platform
    surfaces it and leaves the verdict to a person."""
    run = world["run"]
    _draw(db, run, "CPOOL", 100)
    _draw(db, run, "CBOTH", 60)
    _draw(db, run, "CKARTON", 50)
    out = sp.coverage(db, run)
    assert out["unexpected_draws"] == [{"lcsc": "CKARTON", "drawn": 50.0}]


# ------------------------------------------- the supplier's parts are not OUR stock

def test_a_run_charged_part_is_not_a_purchase_against_jlcs_warehouse(db: Session):
    """The ledger reconciler compares what we booked as BOUGHT against what JLC
    says it received into our consigned stock. A part the factory sourced itself
    never went into that stock, so counting it there reports a phantom shortfall.

    It really happened: itemising batch 8's parts position put 20 lines carrying
    LCSC codes on the books, and the Stock page immediately announced "17,647
    pieces we booked as bought that JLC never received" (user report
    2026-09-19). The lines were right; the query was counting lines that never
    claimed to be stock.
    """
    from app.services import jlc_ledger

    proj = M.Project(name="test-ledger-scope", git_url="https://example.invalid/l.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="L1", run_date="2026-03-01",
                          status="completed", qty=10)
    db.add(run)
    db.flush()
    doc = M.RunCostDocument(project_id=proj.id, doc_type="invoice", supplier="JLCPCB",
                            doc_number="L-1", external_id="POBLEDGERTEST",
                            doc_date="2026-02-01", currency="USD", total_amount=30.0)
    db.add(doc)
    db.flush()
    pooled = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", lcsc="CPOOLED",
                           mpn="POOLED-1", qty=10, unit_price=1.0, position=0)
    supplied = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", lcsc="CSUPPLIED",
                             mpn="SUPPLIED-1", qty=3300, unit_price=0.001,
                             run_id=run.id, position=1)
    carved = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", lcsc="CEXCLUDED",
                           mpn="EXCLUDED-1", qty=500, unit_price=0.001,
                           allocate="excluded", position=2)
    db.add_all([pooled, supplied, carved])
    db.flush()

    _draws, purchases = jlc_ledger._local_index(db)
    claimed = {key[0] for key in purchases}
    assert "CPOOLED" in claimed, "a pooled purchase IS a claim on JLC's warehouse"
    assert "CSUPPLIED" not in claimed, "a part the factory supplied never entered our stock"
    assert "CEXCLUDED" not in claimed, "an excluded carve-out is not a purchase"


# ------------------------------- double supply, with no supplier BOM to lean on

@pytest.fixture
def hand_entered(db: Session):
    """A batch that bought a part directly, on a document with NO supplier BOM.

    This is the shape nothing guarded: the supplier half of `coverage` needs a
    cached BOM, and a hand-entered invoice has none. Assume every function gets
    used through the UI (user 2026-09-19) — so the check that catches a double
    charge must not depend on the supplier publishing anything.
    """
    proj = M.Project(name="test-hand", git_url="https://example.invalid/h.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="H1", run_date="2026-03-01",
                          status="completed", qty=100)
    db.add(run)
    db.flush()
    doc = M.RunCostDocument(project_id=proj.id, doc_type="invoice", supplier="HANDCO",
                            doc_number="H-1", doc_date="2026-02-01", currency="USD",
                            total_amount=50.0)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", lcsc="CHAND", mpn="HAND-1",
                         qty=500, unit_price=0.1, run_id=run.id, position=0))
    db.flush()
    return {"run": run}


def test_a_part_bought_for_the_batch_and_also_drawn_is_caught(db: Session, hand_entered):
    run = hand_entered["run"]
    _draw(db, run, "CHAND", 500)
    out = sp.coverage(db, run)
    assert out["known"] is False, "there is no supplier BOM here"
    assert out["checked_without_bom"] is True, "the double-supply half still ran"
    verdicts = {r["lcsc"]: r["verdict"] for r in out["rows"]}
    assert verdicts["CHAND"] == "bought_for_batch_and_drawn"


def test_bought_for_the_batch_and_never_drawn_is_fine(db: Session, hand_entered):
    """The batch paid for it directly. No draw is the CORRECT state."""
    out = sp.coverage(db, hand_entered["run"])
    assert [r for r in out["rows"] if r["verdict"] != "ok"] == []


def test_a_batch_bought_part_is_not_also_an_unexpected_draw(db: Session, hand_entered):
    """It would otherwise be reported twice — once as paid for twice, once as a
    draw nobody can explain."""
    run = hand_entered["run"]
    _draw(db, run, "CHAND", 500)
    out = sp.coverage(db, run)
    assert out["unexpected_draws"] == []
