"""Where a position's money goes, and the two states that used to share a spelling.

Decision record:
docs/decisions/0045-a-position-says-where-its-money-goes.md.

`allocate="none"` on a line naming no run and no project meant two different
things, decided by a field nobody was being asked about:

  * `plan_key="parts:pool"`   -> the shared pool. Correct, and invisible.
  * anything else   -> `unassigned`. Money nobody pays for, and a defect.

`POOLED` is the first one said outright. These tests pin both halves: that a
`pooled` line reaches the pool from any kind, and that a line which has decided
nothing is still reported rather than quietly absorbed.

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


@pytest.fixture
def world(db: Session):
    proj = M.Project(name="test-line-dest", git_url="https://example.invalid/d.git")
    db.add(proj)
    db.flush()
    run = M.ProductionRun(project_id=proj.id, label="D1", run_date="2026-03-01",
                          status="completed", qty=10)
    db.add(run)
    db.flush()
    shared = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="DESTCO",
                              doc_number="D-0001", doc_date="2026-01-01",
                              currency="USD", total_amount=100.0)
    db.add(shared)
    db.flush()
    return {"proj": proj, "run": run, "doc": shared}


def _line(db, doc, **kw) -> M.RunCostLine:
    kw.setdefault("qty", 1)
    kw.setdefault("unit_price", 10.0)
    kw.setdefault("position", 0)
    li = M.RunCostLine(document_id=doc.id, **kw)
    db.add(li)
    db.flush()
    return li


# ------------------------------------------------- the two states, told apart

def test_a_pooled_part_reaches_the_pool_because_it_says_so(db: Session, world):
    """Stock is STATED, not inferred from `kind` — the value is what makes the
    difference between "it goes to the pool" and "nobody has decided"."""
    li = _line(db, world["doc"], plan_key="parts:pool", allocate=ra.POOLED)
    assert ra.line_destination(li, world["doc"]) == ("pool", None)


def test_only_a_stock_step_may_be_marked_pooled(db: Session, world):
    """`_pool_events` treats only a STOCK STEP as a purchase, so a `pooled` line
    on any other step would sit in the register's `pool` bucket and never appear
    in `pool.purchased_usd` — two pool figures, quietly disagreeing. The router
    refuses it; money that belongs on the stock rides there as landed cost."""
    from fastapi import HTTPException

    from app.routers.run_costs import _check_allocate

    _check_allocate("parts:pool", ra.POOLED)            # fine
    _check_allocate("pcba:parts", ra.POOLED)            # fine — supplier-sourced
    _check_allocate("logistics:inbound", "by_value")    # fine — landed cost
    for step in ("other:discount", "final:shipping_prep", "logistics:inbound"):
        with pytest.raises(HTTPException) as exc:
            _check_allocate(step, ra.POOLED)
        assert exc.value.status_code == 422


def test_an_undecided_non_part_is_still_unassigned(db: Session, world):
    """The defect detector must survive: `none` on a line naming nothing is
    money nobody pays for, and it has to keep being reported."""
    li = _line(db, world["doc"], plan_key="other:discount", allocate="none")
    assert ra.line_destination(li, world["doc"]) == ("unassigned", None)


def test_a_legacy_part_line_still_reaches_the_pool(db: Session, world):
    """~600 rows predate `pooled`. They must not move."""
    li = _line(db, world["doc"], plan_key="parts:pool", allocate="none")
    assert ra.line_destination(li, world["doc"]) == ("pool", None)


# ------------------------------------------------------------ precedence

def test_pooled_beats_the_documents_own_destination(db: Session, world):
    """A parts invoice filed against a batch can still carry plain stock, and
    saying so on the line is the only way to express it."""
    doc = M.RunCostDocument(project_id=world["proj"].id, run_id=world["run"].id,
                            doc_type="invoice", supplier="DESTCO", doc_number="D-0002",
                            doc_date="2026-01-02", currency="USD")
    db.add(doc)
    db.flush()
    stated = _line(db, doc, plan_key="parts:pool", allocate=ra.POOLED)
    assert ra.line_destination(stated, doc) == ("pool", None)
    # Without the marker, the document's own batch claims it — unchanged.
    silent = _line(db, doc, plan_key="fab:pcb", allocate="none")
    assert ra.line_destination(silent, doc) == ("run", world["run"].id)


def test_a_named_run_beats_pooled(db: Session, world):
    """Charging a position to a batch is the most specific thing you can say."""
    li = _line(db, world["doc"], plan_key="parts:pool", allocate=ra.POOLED, run_id=world["run"].id)
    assert ra.line_destination(li, world["doc"]) == ("run", world["run"].id)


def test_excluded_still_beats_everything(db: Session, world):
    """Unchanged, and the reason the UI must CLEAR `allocate` when a position
    moves onto a batch: the old editor only ever added `excluded` and never took
    it off, so the line kept reading as charged to nobody."""
    li = _line(db, world["doc"], plan_key="fab:pcb", allocate=ra.EXCLUDED, run_id=world["run"].id)
    assert ra.line_destination(li, world["doc"]) == ("excluded", None)


# ---------------------------------------------------- pooled behaves as none

def test_a_pooled_part_is_a_real_purchase(db: Session, world):
    """`pooled` must pass every "is this a purchase" test that `none` passed, or
    the backfill would have taken 264 lines out of the pool."""
    li = _line(db, world["doc"], plan_key="parts:pool", mpn="DEST-PART-1", qty=100,
               unit_price=0.5, allocate=ra.POOLED)
    assert ra.pooled_part_lines(db, [li]) == [li]
    pool = ra.pool_state(db)
    entry = ra.resolve_pool_identity(db, None, "DEST-PART-1", "")
    assert entry is not None and entry["qty"] == pytest.approx(100.0)
    assert pool  # the replay ran


def test_the_register_identity_holds_with_pooled_lines(db: Session, world):
    """`invoiced == runs + projects + pool + excluded + unassigned + residual`.
    A new `allocate` value that any bucket missed would show up here as a gap.

    Measured as a DELTA against the database's own baseline rather than against
    a fixed number: the dev database carries a pre-existing gap of its own, and
    a test that hard-codes it fails for the wrong reason the day it is fixed.
    """
    before = ra.invoice_register(db)["summary"]["gap_usd"] or 0.0
    doc = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="DESTCO",
                            doc_number="D-0003", doc_date="2026-01-03",
                            currency="USD", total_amount=15.0)
    db.add(doc)
    db.flush()
    _line(db, doc, plan_key="parts:pool", mpn="DEST-PART-2", qty=10,
          unit_price=1.0, allocate=ra.POOLED)
    _line(db, doc, plan_key="logistics:inbound", label="carriage", qty=1,
          unit_price=5.0, allocate="by_value", position=1)
    after = ra.invoice_register(db)["summary"]["gap_usd"] or 0.0
    assert after == pytest.approx(before, abs=0.005), \
        "a pooled line left money in no bucket at all"


# ------------------------------------- the step must survive a plan link

def test_linking_a_cost_item_does_not_replace_the_step(db: Session, world):
    """The near-miss (2026-09-19, caught by the user asking whether the Invoices
    UI had been updated).

    `PlanLinkDialog` wrote the cost item's id into `plan_key`. That was harmless
    while `kind` was a separate field; once the STEP says what a position is, it
    replaces `parts:pool` with an integer — which is not in `PART_STEPS`, so the
    line silently stops being a purchase and a real stock position leaves the
    pool. The link has its own column now, and a non-step `plan_key` is refused.
    """
    from fastapi import HTTPException

    from app.routers.run_costs import _check_line, LinePatch

    li = _line(db, world["doc"], plan_key="parts:pool", allocate=ra.POOLED,
               mpn="DEST-PART-3", qty=5, unit_price=2.0)
    assert ra.is_stock(li)

    # What the dialog used to send.
    with pytest.raises(HTTPException) as exc:
        _check_line(LinePatch(plan_kind="cost", plan_key="1234"))
    assert exc.value.status_code == 422

    # What it sends now: the link lands beside the step, not on top of it.
    li.plan_kind, li.plan_item_id = "cost", 1234
    db.flush()
    assert li.plan_key == "parts:pool"
    assert ra.is_stock(li), "a linked position is still a purchase"
    assert ra.line_destination(li, world["doc"]) == ("pool", None)


def test_a_cancelled_position_may_not_be_charged_to_anyone(db: Session, world):
    """User decision 2026-09-19: the supplier printed the line, nothing was
    delivered, nobody pays. A rule, not a suggestion — the UI forces it even over
    an answer already given, and the server refuses anything else."""
    from fastapi import HTTPException

    from app.routers.run_costs import _check_cancelled

    _check_cancelled("other:cancelled", ra.EXCLUDED, None, None)   # the only legal shape
    _check_cancelled("other:discount", "none", world["run"].id, None)  # unaffected
    for allocate, run_id, project_id in (
        ("none", None, None),                         # undecided
        (ra.EXCLUDED, world["run"].id, None),         # charged to a batch
        (ra.EXCLUDED, None, world["proj"].id),        # charged to a project
        (ra.POOLED, None, None),                      # claimed as stock
    ):
        with pytest.raises(HTTPException) as exc:
            _check_cancelled("other:cancelled", allocate, run_id, project_id)
        assert exc.value.status_code == 422


# --------------------------------------------- the register's own arithmetic

def test_the_register_identity_closes_exactly(db: Session, world):
    """`lines == runs + projects + pool + excluded + unassigned + residual
    - overallocated`, to the cent and beyond.

    It used to be measured against the PRINTED total, which made it permanently
    0.0271 on the real database — five documents whose lines miss what the
    supplier printed by a cent or two. That is bad DATA, not a bug, so the bug
    detector could never read zero; and the production overview printed a green
    "0" for anything under 0.05, so the number nobody could fix was also the
    number nobody could see (decision 0048).
    """
    s = ra.invoice_register(db)["summary"]
    buckets = (s["to_runs_usd"] + s["to_projects_usd"] + s["to_pool_usd"]
               + s["excluded_usd"] + s["unassigned_usd"] + s["residual_usd"]
               - (s["overallocated_usd"] or 0.0))
    assert s["lines_total_usd"] == pytest.approx(buckets, abs=0.0005)
    assert s["gap_usd"] == pytest.approx(0.0, abs=0.0005), \
        "a non-zero gap is a bug in run_actuals, not bad data"


def test_over_allocated_children_are_reported_not_clamped(db: Session, world):
    """A header whose children claim MORE than it holds. `residual` clamps at
    zero because a header cannot owe a negative amount — so the overshoot had to
    get its own name, or it stayed in the leaves and out of the identity. Four
    JLCPCB documents overshoot by 0.0001-0.0002 and kept the gap from closing."""
    doc = M.RunCostDocument(project_id=None, doc_type="invoice", supplier="DESTCO",
                            doc_number="D-0004", doc_date="2026-01-04",
                            currency="USD", total_amount=100.0)
    db.add(doc)
    db.flush()
    parent = _line(db, doc, plan_key="pcba:general", qty=1, unit_price=100.0)
    child = M.RunCostLine(document_id=doc.id, parent_line_id=parent.id, position=1,
                          plan_key="pcba:general", qty=1, unit_price=100.02,
                          run_id=world["run"].id)
    db.add(child)
    db.flush()
    j = ra.document_json(doc, db=db)
    assert j["assignment"]["residual"] == pytest.approx(0.0)
    assert j["assignment"]["overallocated"] == pytest.approx(0.02, abs=0.0005)
    leaves = j["assignment"]["run"] or 0.0
    assert leaves - j["assignment"]["overallocated"] == pytest.approx(100.0, abs=0.0005)


# ------------------------------------------------ an exclusion states its reason

def test_an_exclusion_must_say_what_for():
    """`excluded` is a legal bucket in the conservation identity, so an excluded
    position passes EVERY other check the register has: the gap still closes and
    nothing reads as unassigned. The reason is the only thing that makes it
    auditable, and 44 positions reached production without one.

    The guard is on the schemas rather than on one endpoint, because the hole
    was the SPLIT path: `ChildIn` had no `exclude_reason` field at all until
    2026-09-21, so JLC's prepaid component shares could not state a reason even
    when the operator wanted to (decision 0048).
    """
    from fastapi import HTTPException

    from app.routers.run_costs import ChildIn, LineIn, _check_excluded

    assert "exclude_reason" in ChildIn.model_fields, \
        "a split share must be able to say why it is charged to nobody"

    for allocate, reason in (("excluded", ""), ("excluded", "   ")):
        with pytest.raises(HTTPException) as e:
            _check_excluded(allocate, reason)
        assert e.value.status_code == 422
        assert "why" in str(e.value.detail).lower()

    # A stated reason passes, and so does every other destination: `excluded` is
    # the only one that answers to nobody.
    _check_excluded("excluded", "reclaimable_vat")
    for allocate in ("none", "pooled", "by_value", "by_qty", None):
        _check_excluded(allocate, "")

    # The field is on the ordinary line schema too, so the two write paths agree.
    assert "exclude_reason" in LineIn.model_fields


# ------------------------------------------------ a split balances exactly

def _header(db, world, qty, unit, step="pcba:general"):
    li = M.RunCostLine(document_id=world["doc"].id, plan_key=step, label="header",
                       qty=qty, unit_price=unit, currency="USD", allocate="none",
                       basis="per_run", run_id=world["run"].id)
    db.add(li)
    db.flush()
    return li


def test_a_split_refuses_any_overshoot(db, world):
    """It allowed half a cent, and the register counts any excess as
    over-allocated money: five JLC documents sat $0.0005 over for months."""
    from fastapi import HTTPException

    from app.routers.run_costs import ChildIn, SplitIn, split_line
    h = _header(db, world, 190, 11.173684)          # 2122.99996, as JLC's was stored
    with pytest.raises(HTTPException) as e:
        split_line(h.id, SplitIn(children=[ChildIn(amount=2000.0, run_id=world["run"].id),
                                           ChildIn(amount=123.0, run_id=world["run"].id)]), db)
    assert e.value.status_code == 409 and "balance the last share" in str(e.value.detail)
    ok = split_line(h.id, SplitIn(children=[ChildIn(amount=2000.0, run_id=world["run"].id),
                                            ChildIn(amount=122.9999, run_id=world["run"].id)]), db)
    assert 0 <= ok["residual"] <= 0.0001   # 0.00006, reported to 4 decimals


def test_a_split_edits_its_existing_shares_in_place(db, world):
    """Re-creating a share lost what only the original row carries — here the
    importer's `external_line_id` — so adding ONE rounding share rewrote all."""
    from app.routers.run_costs import ChildIn, SplitIn, split_line
    h = _header(db, world, 1, 100.0)
    kid = M.RunCostLine(document_id=world["doc"].id, parent_line_id=h.id, plan_key="pcba:smt",
                        label="SMT", qty=1, unit_price=60.0, currency="USD", allocate="none",
                        basis="per_run", run_id=world["run"].id, external_line_id="X:fee:padMoney")
    gone = M.RunCostLine(document_id=world["doc"].id, parent_line_id=h.id, plan_key="pcba:setup",
                         label="Setup", qty=1, unit_price=10.0, currency="USD", allocate="none",
                         basis="per_run", run_id=world["run"].id)
    db.add_all([kid, gone])
    db.flush()
    split_line(h.id, SplitIn(replace=True, children=[
        ChildIn(id=kid.id, label="SMT placement", amount=60.0, plan_key="pcba:smt",
                run_id=world["run"].id),
        ChildIn(label="Rounding", amount=-0.0025, plan_key="pcba:other", run_id=world["run"].id),
    ]), db)
    db.refresh(kid)
    assert kid.voided_at is None and kid.external_line_id == "X:fee:padMoney"
    assert kid.label == "SMT placement"
    assert db.get(M.RunCostLine, gone.id).voided_at is not None
    live = db.query(M.RunCostLine).filter(M.RunCostLine.parent_line_id == h.id,
                                          M.RunCostLine.voided_at.is_(None)).count()
    assert live == 2


def test_a_supplier_parts_lump_closes_on_its_own_rounding():
    """JLC bills the lump rounded to the cent while its parts keep four
    decimals: SMT026090162303's parts sum to 2097.2801 against 2097.28."""
    from types import SimpleNamespace

    from app.services import supplier_parts as sp
    bom = [{"componentCode": "C1", "componentSource": "shop", "shopStock": 301,
            "unitPrice": 0.5889, "extPrice": 177.2589, "componentRealCount": 301},
           {"componentCode": "C2", "componentSource": "shop", "shopStock": 1,
            "unitPrice": 1.0, "extPrice": 1.0, "componentRealCount": 1}]
    line = SimpleNamespace(external_line_id="SMTX:fee:materialMoney", unit_price=178.2588,
                           qty=1, basis="per_run", run_id=None, document_id=None)
    orig = sp.bom_for_order, sp.run_actuals.effective_qty
    sp.bom_for_order = lambda db, code: bom
    sp.run_actuals.effective_qty = lambda li, doc, db: 1
    try:
        plan = sp.itemise(None, line)
    finally:
        sp.bom_for_order, sp.run_actuals.effective_qty = orig
    [rounding] = [c for c in plan["children"] if c["source"] == "rounding"]
    assert rounding["amount"] == -0.0001 and plan["reconciles"]
