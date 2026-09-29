"""The supplier order decides which source prices a part — and a run keeps the
order of its own date.

Decision record:
docs/decisions/0055-a-component-links-to-suppliers-in-a-register.md.

The rule that matters most here is the dated one. Prices reach money: a
production run's planned side prices every part not yet bought from invoices
through `ladder.history_points_at`, so a reorder made today must not move a run
priced yesterday. Before the register, the rule was "a JLCPCB ladder hides the
LCSC one, everything else mixes in"; a snapshot written then carries no ranks
and must still resolve that way.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs -q
"""
import pathlib
import sys
from datetime import timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import ladder, signoff, suppliers


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


def pt(source, qty, price, rank=None, currency="USD"):
    p = M.ComponentPricePoint(source=source, qty_from=qty, unit_price=price, currency=currency)
    p.rank = rank
    return p


def supplier(db, name, connector=""):
    s = suppliers.by_name(db, name)
    if s is None:
        s = suppliers.create(db, name, actor="test")
        s.connector = connector
    return s


@pytest.fixture
def comp(db):
    """A bare component: the price code needs an id, nothing else."""
    for name, connector in (("JLCPCB", "jlcpcb"), ("LCSC", "lcsc"), ("TestDist", "")):
        supplier(db, name, connector)
    c = M.Component(name="__test_supplier_order__")
    db.add(c)
    db.flush()
    return c


def add_points(db, cid, source, tiers):
    for q, p in tiers:
        db.add(M.ComponentPricePoint(component_id=cid, source=source, qty_from=q, unit_price=p,
                                     currency="USD", updated_at=M.utcnow()))
    db.flush()


# ------------------------------------------------------------------ resolution
def test_ranked_points_take_one_source_whole():
    pts = [pt("JLCPCB", 1, 1.0, 0), pt("JLCPCB", 100, 0.5, 0), pt("LCSC", 1, 0.9, 1),
           pt("LCSC", 10, 0.1, 1)]
    assert {p.source for p in ladder.effective_points(pts)} == {"JLCPCB"}
    # LCSC's cheaper 10-break does not leak into the JLCPCB ladder
    assert ladder.price_at(pts, 50).unit_price == 1.0


def test_an_override_puts_the_other_source_first():
    pts = [pt("JLCPCB", 1, 1.0, 1), pt("LCSC", 1, 0.9, 0)]
    assert ladder.price_at(pts, 1).source == "LCSC"


def test_an_unranked_snapshot_keeps_the_old_rule():
    """A price-history row written before the register has no ranks: JLCPCB
    hides LCSC, and a hand-entered price mixes in, as it did then."""
    pts = [pt("JLCPCB", 1, 1.0), pt("LCSC", 1, 0.9), pt("Manual", 500, 0.2)]
    eff = ladder.effective_points(pts)
    assert {p.source for p in eff} == {"JLCPCB", "Manual"}
    assert ladder.price_at(pts, 1000).source == "Manual"
    assert ladder.price_at(pts, 1).source == "JLCPCB"


def test_a_legacy_price_ranks_before_every_supplier(db, comp):
    add_points(db, comp.id, "JLCPCB", [(1, 1.0)])
    add_points(db, comp.id, "Manual", [(1, 2.0)])
    pts = ladder.live_points(db, [comp.id])[comp.id]
    assert ladder.price_at(pts, 1).source == "Manual"


# ---------------------------------------------------------------- the order
def test_own_order_comes_before_the_library_order(db, comp):
    lib = [s.name for s in suppliers.ordered(db)]
    assert lib.index("JLCPCB") < lib.index("LCSC")
    lcsc = supplier(db, "LCSC")
    row = suppliers.link(db, comp.id, lcsc, part_number="C1", origin="lcsc_part")
    suppliers.set_component_order(db, comp.id, [row.id])
    r = suppliers.ranks(db, [comp.id])[comp.id]
    assert r["LCSC"] < r["JLCPCB"]
    suppliers.set_component_order(db, comp.id, None)
    r = suppliers.ranks(db, [comp.id])[comp.id]
    assert r["JLCPCB"] < r["LCSC"]


def test_first_typed_price_moves_the_link_to_the_top(db, comp):
    add_points(db, comp.id, "JLCPCB", [(1, 1.0)])
    dist = supplier(db, "TestDist")
    row = suppliers.link(db, comp.id, dist, part_number="TD-1")
    assert ladder.price_at(ladder.live_points(db, [comp.id])[comp.id], 1).source == "JLCPCB"
    suppliers.set_link_prices(db, row, [(1, 3.0, "EUR"), (100, 2.5, "EUR")])
    pts = ladder.live_points(db, [comp.id])[comp.id]
    won = ladder.price_at(pts, 100)
    assert (won.source, won.unit_price, won.currency) == ("TestDist", 2.5, "EUR")
    # the user moves it down again; typing new prices does not move it back up
    jlc_link = suppliers.link(db, comp.id, supplier(db, "JLCPCB"), part_number="C1", origin="lcsc_part")
    suppliers.set_component_order(db, comp.id, [jlc_link.id, row.id])
    suppliers.set_link_prices(db, row, [(1, 2.0, "EUR")])
    assert ladder.price_at(ladder.live_points(db, [comp.id])[comp.id], 1).source == "JLCPCB"


def test_a_robot_supplier_takes_no_typed_price(db, comp):
    row = suppliers.link(db, comp.id, supplier(db, "JLCPCB"), part_number="C1", origin="lcsc_part")
    with pytest.raises(suppliers.SupplierError):
        suppliers.set_link_prices(db, row, [(1, 1.0, "USD")])


def test_attributing_a_manual_price_keeps_every_figure(db, comp):
    add_points(db, comp.id, "Manual", [(1, 4.78), (500, 4.57)])
    row = suppliers.link(db, comp.id, supplier(db, "TestDist"), part_number="TKC-1")
    assert suppliers.attribute_legacy(db, row, "Manual") == 2
    pts = ladder.live_points(db, [comp.id])[comp.id]
    assert sorted((p.source, p.qty_from, p.unit_price) for p in pts) == [
        ("TestDist", 1, 4.78), ("TestDist", 500, 4.57)]


# ------------------------------------------------------------ the dated order
def test_a_reorder_does_not_reprice_an_earlier_date(db, comp):
    """The run-date guarantee: history carries the order of its own date."""
    add_points(db, comp.id, "JLCPCB", [(1, 1.0)])
    add_points(db, comp.id, "LCSC", [(1, 0.5)])
    ladder.record_price_history(db, comp.id)
    first = db.query(M.ComponentPriceHistory).filter_by(component_id=comp.id).one()
    first.recorded_at = M.utcnow() - timedelta(days=10)
    run_date = M.utcnow() - timedelta(days=5)

    lcsc = suppliers.link(db, comp.id, supplier(db, "LCSC"), part_number="C1", origin="lcsc_part")
    suppliers.set_component_order(db, comp.id, [lcsc.id])  # records a new snapshot, dated now

    then = ladder.history_points_at(db, {comp.id}, run_date)[comp.id]
    assert ladder.price_at(then, 1).source == "JLCPCB"
    now = ladder.history_points_at(db, {comp.id}, M.utcnow() + timedelta(seconds=1))[comp.id]
    assert ladder.price_at(now, 1).source == "LCSC"


# --------------------------------------------------------------- the carry
def _cv(props):
    cv = M.ComponentVersion(base_component="R", category_id=1, removed_properties=[])
    cv.properties = [M.ComponentProperty(position=i, key=k, value=v, is_null=False)
                     for i, (k, v) in enumerate(props)]
    return cv


def test_removing_supplier_fields_keeps_the_verification():
    old = _cv([("Value", "10k"), ("LCSC Part", "C25804"), ("Supplier 1", "LCSC"),
               ("Supplier Part Number 1", "C25804"), ("Supplier 2", "Mouser")])
    new = _cv([("Value", "10k"), ("LCSC Part", "C25804")])
    assert signoff.data_carries(old, new) == (True, "")


def test_the_lcsc_part_stays_material():
    old = _cv([("Value", "10k"), ("LCSC Part", "C25804")])
    new = _cv([("Value", "10k"), ("LCSC Part", "C25805")])
    ok, why = signoff.data_carries(old, new)
    assert not ok and "LCSC Part" in why


@pytest.mark.parametrize("key,expected", [
    ("Supplier 1", True), ("Supplier Part Number 12", True), ("Supplier", False),
    ("LCSC Part", False), ("Supplier Notes", False),
])
def test_is_supplier_key(key, expected):
    assert suppliers.is_supplier_key(key) is expected
