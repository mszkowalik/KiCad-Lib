"""Stock → Parts: every figure on a part's row adds up, and every tile says what it sums.

What is being protected:

1. **A part's row adds up.** `pool_state` gave a figure to purchases, draws and
   losses only, so a part whose stock came from a count, a correction or a make
   did not add up: 39 rows on production (2026-11-07). c326 read bought 4,830 -
   drawn 5,124 and ours 116, with its +410 correction nowhere; c327 read
   "written off 410" for the same 410 antennas, moved and not lost; c579 read
   bought 0, drawn 0 and 500 on hand, the output of a make.
2. **"Drawn by batches" is the batches' share.** The tile printed every draw:
   83,617.96 USD, of which batches drew 79,981.95. The rest was R&D, draws
   waiting for a batch, and the inputs of prepared parts.
3. **A part with two JLC codes is valued code by code.** XL-1005SURC holds
   13,676 under C25503345 at 0.0051 and 387 under C965790 at 0.0091; the first
   code's price for all 14,063 read 127.97 USD where they are worth 73.27.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_parts_stock_figures.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import run_actuals as RA
from app.services.material_ledger import core as ledger

PART = "TEST-PSF-PART"
OTHER = "TEST-PSF-OTHER"
MADE = "TEST-PSF-MADE"


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


def _row(stock, mpn):
    return next(r for r in stock["parts"] if r["key"] == f"m{mpn.replace('-', '')}")


@pytest.fixture
def world(db: Session):
    """100 pieces of PART bought at 1 USD, 50 of OTHER; then every kind of move."""
    p = M.Project(name="test-parts-stock-figures", git_url="https://example.invalid/psf.git")
    db.add(p)
    db.flush()
    run = M.ProductionRun(project_id=p.id, label="PSF1", run_date="2026-04-01", status="completed", qty=10)
    db.add(run)
    db.flush()
    doc = M.RunCostDocument(doc_type="invoice", supplier="TEST-PSF", doc_number="PSF-1",
                            doc_date="2026-03-01", currency="USD", total_amount=150.0)
    db.add(doc)
    db.flush()
    for i, (mpn, qty) in enumerate(((PART, 100), (OTHER, 50))):
        db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", label=mpn, mpn=mpn,
                             qty=qty, unit_price=1.0, currency="USD", allocate="pooled", position=i))
    db.flush()
    ledger.draw(db, run_id=run.id, mpn=PART, taken=30, unit_cost_usd=1.0, at="2026-04-02", basis="manual")
    ledger.draw(db, mpn=PART, taken=5, unit_cost_usd=1.0, at="2026-04-03", basis="research", note="R&D")
    ledger.draw(db, mpn=PART, taken=2, unit_cost_usd=1.0, at="2026-04-04", basis="measured", note="a pick")
    ledger.adjustment(db, mpn=PART, qty=7, unit_cost_usd=0.0, at="2026-04-05", reason="opening_balance")
    ledger.adjustment(db, mpn=PART, qty=-3, unit_cost_usd=1.0, at="2026-04-06", reason="scrap")
    # Ten pieces of OTHER were really PART: a correction, not a loss.
    ledger.adjustment(db, mpn=OTHER, qty=-10, unit_cost_usd=1.0, at="2026-04-07", reason="correction")
    ledger.adjustment(db, mpn=PART, qty=10, unit_cost_usd=1.0, at="2026-04-07", reason="correction")
    ledger.adjustment(db, mpn=MADE, qty=20, unit_cost_usd=0.0, at="2026-04-08", reason="transformation")
    db.flush()
    return run


def test_every_row_adds_up(db, world):
    stock = RA.parts_stock(db)
    part, other, made = _row(stock, PART), _row(stock, OTHER), _row(stock, MADE)
    assert (part["bought"], part["added"], part["corrected"], part["drawn"], part["lost"]) == (100, 7, 10, 37, 3)
    assert part["remaining_qty"] == 77
    assert (other["corrected"], other["lost"], other["remaining_qty"]) == (-10, 0, 40), \
        "a correction moves pieces to another part; it is not written off"
    assert (made["made"], made["remaining_qty"]) == (20, 20)
    for r in stock["parts"]:
        total = (r["bought"] + r["added"] + r["made"] + r["corrected"]
                 - r["drawn"] - r["lost"] - r["external"])
        assert total == pytest.approx(r["remaining_qty"], abs=0.01), r["key"]


def test_every_cost_pool_row_adds_up(db, world):
    """`GET /projects/{id}/cost-pool` gave bought, used and lost only."""
    from app.routers.run_costs import get_pool

    rows = {r["mpn"]: r for r in get_pool(world.project_id, None, db)["parts"]}
    assert (rows[PART]["added"], rows[PART]["corrected"], rows[MADE]["made"]) == (7, 10, 20)
    for r in rows.values():
        total = (r["bought"] + r["added"] + r["made"] + r["corrected"]
                 - r["used"] - r["lost"] - r["external"])
        assert total == pytest.approx(r["on_hand"], abs=0.01), r["mpn"]


def test_drawn_value_is_split_by_who_carries_it(db, world):
    t = RA.parts_stock(db)["totals"]
    by = t["drawn_by_usd"]
    assert sum(v or 0.0 for v in by.values()) == pytest.approx(t["drawn_usd"], abs=0.01)
    reg = RA.invoice_register(db, accountant=False)["pool"]
    assert by["research"] == pytest.approx(reg["research_drawn_usd"], abs=0.01)
    assert by["uncharged"] == pytest.approx(reg["uncharged_drawn_usd"], abs=0.01)
    assert by["into_prepared"] == pytest.approx(reg["into_prepared_usd"], abs=0.01)


def test_two_codes_of_one_part_are_valued_code_by_code(db, world):
    now = datetime(2026, 4, 10, 12, tzinfo=UTC)
    for code, qty, price in (("CPSF0001", 13676, 0.0051), ("CPSF0002", 387, 0.0091)):
        db.add(M.JlcStockItem(lcsc=code, mpn=PART, qty=qty, unit_price_usd=price, updated_at=now))
    db.flush()
    part = _row(RA.parts_stock(db), PART)
    assert part["held_qty"] == 14063
    assert part["market_value_usd"] == pytest.approx(13676 * 0.0051 + 387 * 0.0091, abs=0.001)
    assert part["market_value_usd"] != pytest.approx(14063 * 0.0051, abs=0.01)
