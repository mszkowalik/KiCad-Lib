"""The board BOM and the process steps count a part once (decision 0090).

What these pin down:

- a BOM line whose part a step on the main route draws is counted through the
  step only: it is marked with the step, left out of the BOM total, and the
  step's row prices it;
- a prepared part's recipe inputs count as drawn by the step that uses it;
- an off-board BOM line no step draws is not counted, and a warning says so;
- a BOM quantity that differs from the step's is reported, and the step's
  quantity is the one counted;
- a project with no process counts its BOM lines as before;
- "Record assembly" does not offer the parts the steps draw;
- the batch's run economics leave the line out and carry the warnings.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_process_bom.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.services import process as P
from app.services import project_bom
from app.services import twins as T


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


def _part(db, name, price):
    c = M.Component(name=name, in_library=False)
    db.add(c)
    db.flush()
    db.add(M.ComponentPricePoint(component_id=c.id, source="LCSC", qty_from=1, unit_price=price,
                                 currency="USD"))
    db.flush()
    return c


def _line(db, snap, pos, refs, comp, qty, *, off_board=False, value=""):
    li = M.SnapshotBomLine(snapshot_id=snap.id, board="B", variant="", position=pos, refs=refs, qty=qty,
                           value=value or comp.name, component_id=comp.id, exclude_from_board=off_board)
    db.add(li)
    db.flush()
    return li


GRAPH_STEPS = [
    {"key": "assembly", "label": "Board", "kind": "assembly", "required": True},
    {"key": "receive", "label": "Receive", "kind": "receive", "required": True},
    {"key": "program", "label": "Program", "kind": "program", "required": True, "needs": ["receive"]},
    {"key": "finish", "label": "Finished", "kind": "finish"},
]


@pytest.fixture
def world(db: Session):
    """A V3-like board on its hw-v3.3 BOM, built under a process written for
    hw-v3.3.1: the steps draw the enclosure, two pigtails, three lightpipes and
    one antenna, while the BOM still lists one pigtail and the old antenna."""
    proj = M.Project(name="test-process-bom", git_url="https://example.invalid/pb.git")
    db.add(proj)
    db.flush()
    res = _part(db, "test-pb-resistor", 0.01)
    enc = _part(db, "test-pb-enclosure", 4.0)
    pig = _part(db, "test-pb-pigtail", 0.5)
    lp = _part(db, "test-pb-lightpipe", 0.1)
    ant = _part(db, "test-pb-antenna", 1.0)
    old_ant = _part(db, "test-pb-old-antenna", 1.2)
    steps = GRAPH_STEPS[:3] + [
        {"key": "enclosure", "label": "Take enclosure", "kind": "step", "required": True,
         "needs": ["receive"], "inputs": [{"component_id": enc.id, "qty": 1}]},
        {"key": "sma", "label": "Install SMA", "kind": "step", "required": True,
         "needs": ["enclosure"], "inputs": [{"component_id": pig.id, "qty": 2}]},
        {"key": "lightpipes", "label": "Install lightpipes", "kind": "step", "required": False,
         "needs": ["enclosure"], "inputs": [{"component_id": lp.id, "qty": 3}]},
        {"key": "antennas", "label": "Add antennas", "kind": "step", "required": True,
         "needs": ["program"], "inputs": [{"component_id": ant.id, "qty": 1}]},
    ] + GRAPH_STEPS[3:]
    graph = {"steps": steps, "prepared": [],
             "route": ["assembly", "receive", "enclosure", "sma", "lightpipes", "program", "antennas",
                       "finish"]}
    v = P.compose(db, proj.id, actor="test", graph=graph)
    P.publish(db, v, actor="test", comment="process for the BOM tests")
    snap = M.ProjectSnapshot(project_id=proj.id, sha="0" * 40, ref_name="hw-test", status="ready",
                             boards=[{"name": "B"}])
    db.add(snap)
    db.flush()
    lines = {
        "R1": _line(db, snap, 0, "R1", res, 1),
        "ENC1": _line(db, snap, 1, "ENC1", enc, 1),
        "W2": _line(db, snap, 2, "W2", pig, 1, off_board=True),
        "LP": _line(db, snap, 3, "LP1,LP2,LP3", lp, 3),
        "AE2": _line(db, snap, 4, "AE2", ant, 1, off_board=True),
        "AE1": _line(db, snap, 5, "AE1", old_ant, 1, off_board=True),
    }
    run = M.ProductionRun(project_id=proj.id, label="PB1", run_date="2026-10-01", status="planned",
                          process_version_id=v.id, snapshot_id=snap.id, board="B", variant="", qty=10)
    db.add(run)
    db.flush()
    return {"project": proj, "snap": snap, "v": v, "run": run, "lines": lines,
            "parts": {"res": res, "enc": enc, "pig": pig, "lp": lp, "ant": ant, "old_ant": old_ant}}


def _bom(db, world):
    return project_bom.priced_bom(db, world["project"], world["snap"], "B", "", 10)


def _row(bom, refs):
    return next(li for li in bom["lines"] if li["refs"] == refs)


def test_a_part_a_step_draws_is_counted_once_through_the_step(db, world):
    bom = _bom(db, world)
    assert _row(bom, "ENC1")["process_steps"] == ["enclosure"]
    assert _row(bom, "W2")["process_steps"] == ["sma"]
    assert _row(bom, "LP1,LP2,LP3")["process_steps"] == ["lightpipes"]
    assert _row(bom, "AE2")["process_steps"] == ["antennas"]
    for refs in ("ENC1", "W2", "LP1,LP2,LP3", "AE2"):
        assert _row(bom, refs)["excluded"] is True
    assert _row(bom, "R1")["process_steps"] is None
    assert _row(bom, "R1")["excluded"] is False
    # Only the resistor is a BOM cost; the steps price everything else once.
    assert bom["totals"]["bom_per_device"] == pytest.approx(0.01)
    assert bom["totals"]["extra_per_device"] == pytest.approx(4.0 + 2 * 0.5 + 3 * 0.1 + 1.0)


def test_an_off_board_line_no_step_draws_is_not_counted_and_is_reported(db, world):
    bom = _bom(db, world)
    ae1 = _row(bom, "AE1")
    assert ae1["process_steps"] == []
    assert ae1["excluded"] is True
    assert any(w.startswith("AE1 ") and "no step" in w for w in bom["process_warnings"])


def test_a_quantity_the_step_does_not_match_is_reported(db, world):
    warnings = _bom(db, world)["process_warnings"]
    assert any(w.startswith("W2 ") and "lists 1" in w and "draws 2" in w for w in warnings)
    # The lightpipes match (3 on the BOM, 3 per device in the step): no warning.
    assert not any("LP1" in w for w in warnings)


def test_a_dnp_line_is_neither_counted_nor_reported(db, world):
    world["lines"]["AE1"].dnp = True
    db.flush()
    bom = _bom(db, world)
    assert _row(bom, "AE1")["process_steps"] is None
    assert not any(w.startswith("AE1 ") for w in bom["process_warnings"])


def test_a_project_without_a_process_counts_its_bom_lines(db, world):
    proj = M.Project(name="test-process-bom-none", git_url="https://example.invalid/pb2.git")
    db.add(proj)
    db.flush()
    snap = M.ProjectSnapshot(project_id=proj.id, sha="1" * 40, ref_name="x", status="ready",
                             boards=[{"name": "B"}])
    db.add(snap)
    db.flush()
    _line(db, snap, 0, "ENC1", world["parts"]["enc"], 1)
    _line(db, snap, 1, "AE1", world["parts"]["old_ant"], 1, off_board=True)
    bom = project_bom.priced_bom(db, proj, snap, "B", "", 10)
    assert all(li["process_steps"] is None and not li["excluded"] for li in bom["lines"])
    assert bom["process_warnings"] == []
    assert bom["totals"]["bom_per_device"] == pytest.approx(4.0 + 1.2)


def test_a_recipe_input_counts_as_drawn_by_the_step_that_uses_it():
    """A prepared part expands into its recipe, so the enclosure inside a
    drilled-enclosure lot is the enclose step's material."""
    graph = {"steps": GRAPH_STEPS[:2] + [
        {"key": "enclose", "label": "Enclose", "kind": "step", "inputs": [{"component_id": 900, "qty": 1}]},
    ], "route": ["assembly", "receive", "enclose"],
        "prepared": [{"key": "drill", "output_component_id": 900,
                      "inputs": [{"component_id": 901, "qty": 1}, {"mpn": "PRINT-INK", "qty": 0.01}]}]}
    lines = [SimpleNamespace(id=1, refs="ENC1", qty=1, component_id=901, mpn="", lcsc="", value="box",
                             exclude_from_board=False),
             SimpleNamespace(id=2, refs="R1", qty=1, component_id=902, mpn="", lcsc="", value="R",
                             exclude_from_board=False)]
    owned = P.bom_lines_owned(graph, lines)
    assert owned == {"by_line": {1: ["enclose"]}, "warnings": []}


def test_a_step_input_named_by_mpn_matches_the_line_by_mpn():
    graph = {"steps": GRAPH_STEPS[:2] + [
        {"key": "carton", "label": "Carton", "kind": "step", "inputs": [{"mpn": "KARTON-100x50", "qty": 1}]},
    ], "route": ["assembly", "receive", "carton"], "prepared": []}
    lines = [SimpleNamespace(id=7, refs="BOX1", qty=1, component_id=None, mpn="karton 100x50", lcsc="",
                             value="carton", exclude_from_board=True)]
    assert P.bom_lines_owned(graph, lines)["by_line"] == {7: ["carton"]}


def test_record_assembly_does_not_offer_the_parts_the_steps_draw(db, world):
    T.receive(db, world["run"], qty=2, made_at="2026-10-01", dry_run=False)
    offered = T.assembly_draft(db, world["run"])["bom_suggestion"]
    assert [r["designator"] for r in offered] == ["R1"]
    assert offered[0]["qty"] == 2


def test_the_batch_economics_leave_the_line_out_and_carry_the_warnings(db, world):
    eff = project_bom.run_effective(db, world["run"])
    rows = {li.get("refs") or li.get("label"): li for li in eff["lines"]}
    assert rows["ENC1"]["excluded"] is True
    assert any(w.startswith("AE1 ") for w in eff["process_warnings"])
    counted = [li for li in eff["lines"] if li.get("line_total") is not None and not li.get("excluded")]
    # Ten devices: the resistor from the BOM, everything else from the steps.
    assert eff["totals"]["parts_total"] == pytest.approx(sum(li["line_total"] for li in counted))
    assert not any(li.get("refs") == "ENC1" for li in counted)
