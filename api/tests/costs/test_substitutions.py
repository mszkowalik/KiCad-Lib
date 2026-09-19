"""A part fitted in place of the one the design specifies.

Decision record: docs/decisions/0038-a-substitution-belongs-to-the-batch.md.

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
from app.services import run_actuals as ra, substitutions as S


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
    """A project whose snapshot specifies CSPEC at C2, and two batches."""
    proj = M.Project(name="test-subs", git_url="https://example.invalid/s.git")
    db.add(proj)
    db.flush()
    snap = M.ProjectSnapshot(project_id=proj.id, status="ready", sha="0"*40,
                             created_at=datetime(2026, 1, 1, tzinfo=UTC))
    db.add(snap)
    db.flush()
    db.add(M.SnapshotBomLine(snapshot_id=snap.id, board="B1", variant="", position=1,
                             refs="C2", qty=1, value="100uF", lcsc="CSPEC",
                             mpn="SPEC-PART", component_id=None))
    db.flush()
    runs = []
    for i, when in enumerate(("2026-03-01", "2026-06-01"), start=1):
        r = M.ProductionRun(project_id=proj.id, label=f"S{i}", board="B1", variant="",
                            run_date=when, status="completed", qty=10,
                            snapshot_id=snap.id)
        db.add(r)
        runs.append(r)
    db.flush()
    return {"project": proj, "snap": snap, "runs": runs}


def _order(db, run, order, when, lines, batch="W-TEST"):
    """One cached JLC order BOM, attributed to `run` through a draw's import_ref."""
    db.add(M.JlcImport(external_id=f"{batch}-{order}", doc_date=when,
                       bom_info={order: lines}))
    db.add(M.ComponentConsumption(run_id=run.id, lcsc="CANY", qty=1, unit_cost_usd=0.0,
                                  basis="measured", consumed_at=when,
                                  import_ref=f"jlc:{batch}:{order}:CANY"))
    db.flush()


def _line(ref, code, match="auto", comment="100uF"):
    return {"designator": ref, "componentCode": code, "matchType": match,
            "comment": comment, "describe": f"{comment} part", "componentSource": "preSale"}


def _mine(db, world, rows):
    ids = {r.id for r in world["runs"]}
    return [c for c in rows if c["run_id"] in ids]


# ------------------------------------------------------------------ detection

def test_a_changed_position_is_detected(db, world):
    a, b = world["runs"]
    _order(db, a, "SMT-A", "2026-03-01", [_line("C1", "CSPEC")])
    _order(db, b, "SMT-B", "2026-06-01", [_line("C1", "CNEW", match="update")])
    got = _mine(db, world, S.detect(db))
    assert len(got) == 1
    assert (got[0]["specified_lcsc"], got[0]["fitted_lcsc"]) == ("CSPEC", "CNEW")
    assert got[0]["match_type"] == "update"
    assert got[0]["still_in_design"] is True


def test_the_designs_own_designator_is_recovered(db, world):
    """JLC stores the board's older reference numbering — `C1` where the
    schematic says `C2`. Matching their designators to ours fails on the very
    board this was found on, so the design's reference is looked up through the
    part the design still names."""
    a, b = world["runs"]
    _order(db, a, "SMT-A", "2026-03-01", [_line("C1", "CSPEC")])
    _order(db, b, "SMT-B", "2026-06-01", [_line("C1", "CNEW", match="update")])
    got = _mine(db, world, S.detect(db))[0]
    assert got["supplier_designator"] == "C1"
    assert got["designator"] == "C2"


def test_a_later_batch_that_keeps_the_substitute_is_detected_too(db, world):
    """A substitution is per batch. Reporting only the transition left the next
    batch, built exactly the same way, looking as though it followed the
    design."""
    a, b = world["runs"]
    _order(db, a, "SMT-A", "2026-02-01", [_line("C1", "CSPEC")])
    _order(db, a, "SMT-B", "2026-03-01", [_line("C1", "CNEW", match="update")])
    _order(db, b, "SMT-C", "2026-06-01", [_line("C1", "CNEW", match="update")])
    got = _mine(db, world, S.detect(db))
    assert {c["run_id"] for c in got} == {a.id, b.id}


def test_a_position_that_follows_the_design_is_not_reported(db, world):
    a, b = world["runs"]
    _order(db, a, "SMT-A", "2026-03-01", [_line("C1", "CSPEC")])
    _order(db, b, "SMT-B", "2026-06-01", [_line("C1", "CSPEC")])
    assert _mine(db, world, S.detect(db)) == []


def test_a_designator_on_another_board_is_never_compared(db, world):
    """`U3` on one board is not `U3` on another. Keyed globally, every board in
    the account reported a dozen substitutions it never made."""
    a, _b = world["runs"]
    other = M.Project(name="test-subs-other", git_url="https://example.invalid/o.git")
    db.add(other)
    db.flush()
    r2 = M.ProductionRun(project_id=other.id, label="O1", board="B9", run_date="2026-04-01",
                         status="completed", qty=5)
    db.add(r2)
    db.flush()
    _order(db, a, "SMT-A", "2026-03-01", [_line("C1", "CSPEC")])
    _order(db, r2, "SMT-O", "2026-04-01", [_line("C1", "CWHOLLY-OTHER")], batch="W-OTHER")
    assert [c for c in S.detect(db) if c["run_id"] == r2.id] == []


def test_two_codes_for_one_component_are_not_a_substitution(db, world):
    """JLC lists one manufacturer part under several codes — XL-1005SURC is both
    C25503345 and C965790."""
    a, b = world["runs"]
    comp = M.Component(name="one-part")
    db.add(comp)
    db.flush()
    db.add_all([M.JlcStockItem(lcsc="CSPEC", qty=1, component_id=comp.id),
                M.JlcStockItem(lcsc="CALIAS", qty=1, component_id=comp.id)])
    db.flush()
    _order(db, a, "SMT-A", "2026-03-01", [_line("C1", "CSPEC")])
    _order(db, b, "SMT-B", "2026-06-01", [_line("C1", "CALIAS", match="update")])
    assert _mine(db, world, S.detect(db)) == []


def test_a_recorded_substitution_stops_being_a_candidate(db, world):
    a, b = world["runs"]
    _order(db, a, "SMT-A", "2026-03-01", [_line("C1", "CSPEC")])
    _order(db, b, "SMT-B", "2026-06-01", [_line("C1", "CNEW", match="update")])
    db.add(M.RunSubstitution(run_id=b.id, board="B1", variant="", designator="C2",
                             specified_lcsc="CSPEC", fitted_lcsc="CNEW"))
    db.flush()
    assert _mine(db, world, S.detect(db)) == []


def test_who_supplied_the_part_is_read_from_jlcs_own_word(db, world):
    """`componentSource` says whose shelf it came off, and that decides whether
    a draw can exist at all. It was being inferred from the absence of one,
    which is wrong in both directions."""
    assert S.supplied_by("shop") == "supplier"
    assert S.supplied_by("preSale") == "pool"
    assert S.supplied_by("preSaleAndShop") == "both"
    assert S.supplied_by("") == ""
    assert S.supplied_by("somethingNew") == ""


def test_a_candidate_carries_the_supply_side(db, world):
    a, b = world["runs"]
    _order(db, a, "SMT-A", "2026-03-01", [_line("C1", "CSPEC")])
    line = _line("C1", "CNEW", match="update")
    line["componentSource"] = "shop"
    _order(db, b, "SMT-B", "2026-06-01", [line])
    got = _mine(db, world, S.detect(db))[0]
    assert (got["supplier_source"], got["supplied_by"]) == ("shop", "supplier")


# ------------------------------------------------- what was not fitted at all

def test_nothing_is_unused_without_the_suppliers_bom(db, world):
    """Without JLC's BOM for the batch, the absence of a part says nothing."""
    run = world["runs"][0]
    got = S.unused(db, run)
    assert got == {"has_supplier_bom": False, "unused": []}


def test_a_design_part_the_supplier_never_fitted_is_reported(db, world):
    run = world["runs"][0]
    _order(db, run, "SMT-A", "2026-03-01", [_line("C9", "COTHER")])
    got = S.unused(db, run)
    assert got["has_supplier_bom"] is True
    assert [u["lcsc"] for u in got["unused"]] == ["CSPEC"]


def test_a_part_the_supplier_did_fit_is_not_reported(db, world):
    run = world["runs"][0]
    _order(db, run, "SMT-A", "2026-03-01", [_line("C1", "CSPEC")])
    assert S.unused(db, run)["unused"] == []


def test_the_same_part_under_another_code_counts_as_fitted(db, world):
    """Batch 8 drew XL-1005SURC as C25503345 while the design names C965790;
    matching on the code alone reported the LEDs as never fitted."""
    run = world["runs"][0]
    comp = M.Component(name="two-codes")
    db.add(comp)
    db.flush()
    db.add_all([M.JlcStockItem(lcsc="CSPEC", qty=1, component_id=comp.id),
                M.JlcStockItem(lcsc="CALIAS", qty=1, component_id=comp.id)])
    db.flush()
    _order(db, run, "SMT-A", "2026-03-01", [_line("C1", "CALIAS")])
    assert S.unused(db, run)["unused"] == []


def test_a_part_that_was_drawn_is_not_reported(db, world):
    """A carton is on no SMT BOM and is drawn by hand. Reporting it as unfitted
    on every batch would make the flag worthless."""
    run = world["runs"][0]
    _order(db, run, "SMT-A", "2026-03-01", [_line("C9", "COTHER")])
    db.add(M.ComponentConsumption(run_id=run.id, lcsc="CSPEC", qty=10,
                                  unit_cost_usd=0.1, basis="manual",
                                  consumed_at="2026-03-01"))
    db.flush()
    assert S.unused(db, run)["unused"] == []


def test_a_substituted_position_is_not_reported_as_unfitted(db, world):
    """The substitution IS the answer to why the design's part is absent."""
    run = world["runs"][0]
    _order(db, run, "SMT-A", "2026-03-01", [_line("C1", "CNEW")])
    assert [u["lcsc"] for u in S.unused(db, run)["unused"]] == ["CSPEC"]
    _sub(db, run)
    assert S.unused(db, run)["unused"] == []


def test_recording_that_nothing_was_fitted_also_silences_it(db, world):
    """Quantity zero with nothing named — the early batches shipped without
    cartons, which is history rather than an error."""
    run = world["runs"][0]
    _order(db, run, "SMT-A", "2026-03-01", [_line("C9", "COTHER")])
    _sub(db, run, fitted_lcsc="", qty_per_device=0)
    assert S.unused(db, run)["unused"] == []


# ---------------------------------------------------------------------- drift

def _sub(db, run, **kw):
    kw.setdefault("specified_lcsc", "CSPEC")
    kw.setdefault("fitted_lcsc", "CNEW")
    row = M.RunSubstitution(run_id=run.id, board="B1", variant="", designator="C2",
                            specified_mpn="SPEC-PART", **kw)
    db.add(row)
    db.flush()
    return row


def test_drift_reports_while_the_design_still_asks_for_the_old_part(db, world):
    """The standing finding, and the only thing that would have stopped 476
    pieces of a superseded part being bought three months on."""
    row = _sub(db, world["runs"][0])
    got = [d for d in S.drift(db) if d["substitution_id"] == row.id]
    assert len(got) == 1
    assert got[0]["specified_lcsc"] == "CSPEC"


def test_drift_clears_when_the_design_is_marked_updated(db, world):
    row = _sub(db, world["runs"][0], design_updated=True)
    assert [d for d in S.drift(db) if d["substitution_id"] == row.id] == []


def test_drift_is_silent_once_the_design_no_longer_names_the_part(db, world):
    """Nothing to warn about: the schematic moved on by itself."""
    row = _sub(db, world["runs"][0], specified_lcsc="CGONE")
    assert [d for d in S.drift(db) if d["substitution_id"] == row.id] == []


def test_drift_says_how_much_of_the_dead_part_is_still_held(db, world):
    db.add(M.JlcStockItem(lcsc="CSPEC", qty=500))
    db.flush()
    row = _sub(db, world["runs"][0])
    got = [d for d in S.drift(db) if d["substitution_id"] == row.id][0]
    assert got["specified_still_held"] == 500


# ------------------------------------------------------------- the draw path

def test_a_bom_draw_takes_the_part_that_was_fitted(db, world):
    """The reason this is a row and not a note: `run.overrides` could express it
    but keyed on a snapshot-scoped BOM line id, so it stopped matching the next
    time the BOM was exported."""
    run = world["runs"][0]
    db.add(M.RunCostDocument(doc_type="invoice", supplier="T", doc_number="S-1",
                             doc_date="2026-01-01", currency="USD", total_amount=10.0))
    db.flush()
    doc = db.query(M.RunCostDocument).filter_by(doc_number="S-1").one()
    db.add(M.RunCostLine(document_id=doc.id, kind="part", label="new part",
                         lcsc="CNEW", qty=1000, unit_price=0.01, currency="USD",
                         allocate="none"))
    db.add(M.DeviceUnit(project_id=world["project"].id, production_run_id=run.id,
                        serial="S-0001"))
    _sub(db, run)
    db.flush()
    res = ra.consume_from_bom(db, run, basis="bom", consumed_at="2026-03-01")
    assert res.get("error") is None, res
    drawn = db.query(M.ComponentConsumption).filter_by(run_id=run.id, basis="bom").all()
    assert [c.lcsc for c in drawn] == ["CNEW"]
    assert "in place of CSPEC" in drawn[0].note


def test_a_substitution_matches_any_reference_on_a_multi_part_line(db, world):
    """A BOM line names several positions — "C14, C15, C16" — and a
    substitution recorded against any one of them is the same line."""
    run = world["runs"][0]
    row = _sub(db, run)
    row.designator = "C14, C15, C16"
    db.flush()
    got = S.by_designator(db, run)
    assert set(got) == {"C14", "C15", "C16"}


def test_another_boards_substitution_is_not_applied(db, world):
    run = world["runs"][0]
    row = _sub(db, run)
    row.board = "B9"
    db.flush()
    assert S.by_designator(db, run) == {}
