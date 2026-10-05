"""Rebuilding an old batch from each device's own records (decision 0060, the
2026-10-05 review of the rebuild).

What these pin down:

- a test, a laser mark and a label come from the device's own bench runs, one
  click per day and deployment version, each twin naming its run; a statement
  covers only devices with no bench record, and a failed test is a record;
- an invoice position is money, never proof that a step happened on a unit;
- a statement names a device list or a programmed date range;
- units still in progress stay active and take later bench steps;
- each step carries its own date, and a scrapped twin the disposal's;
- drawn parts are compared with units x quantity, and every difference is
  settled: a deficit drawn or recorded short, a surplus returned (its lots
  given back) or kept as a loss in the origin batch cost;
- devices that join a rebuilt batch later are appended, and the undo takes back
  the live clicks on rebuilt twins (journalled and bench) and then the rebuild;
- devices built on another batch's boards keep that batch as their origin, and
  the money check runs over both batches;
- found units that name the batch are reported, and counted spares enter once;
- the link job links an old bench run only to the one device its topic names;
- the route's dry run keeps the caller's transaction, and a write is one
  journal batch.

Run from `api/`, with the dev database up:
    python -m pytest tests/costs/test_twin_rebuild_evidence.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models as M
from app.config import settings
from app.db import engine
from app.services import bench_links
from app.services import lots as L
from app.services import orders as osvc
from app.services import process as P
from app.services import run_actuals as ra
from app.services import twin_rebuild as R
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


def _part(db, name):
    c = M.Component(name=name, in_library=False)
    db.add(c)
    db.flush()
    return c


def _deployment(db, proj, name, kind):
    d = M.Deployment(project_id=proj.id, name=name, kind=kind)
    db.add(d)
    db.flush()
    vs = [M.DeploymentVersion(deployment_id=d.id, version_no=n, status="published", steps=[]) for n in (1, 2)]
    db.add_all(vs)
    db.flush()
    return d, vs


@pytest.fixture
def w(db: Session):
    """A dongle-like product: assembly → receive → antenna → enclosure →
    program → test → laser + label → carton (→ optional leaflet) → finish.
    Each bench step names its deployment; the label step uses a label, the
    carton a carton, both bought by MPN on 2025-01-01."""
    proj = M.Project(name="test-rebuild-evidence", git_url="https://example.invalid/r.git")
    db.add(proj)
    db.flush()
    ant, enc = _part(db, "test-rb-antenna"), _part(db, "test-rb-enclosure")
    doc = M.RunCostDocument(project_id=proj.id, doc_type="invoice", supplier="TESTCO", doc_number="RB-0001",
                            doc_date="2025-01-01", currency="USD", total_amount=0.0)
    db.add(doc)
    db.flush()
    for i, (cid, mpn, price) in enumerate(((ant.id, "", 1.0), (enc.id, "", 2.0), (None, "TEST-RB-LABEL", 0.1),
                                           (None, "TEST-RB-KARTON", 0.5))):
        db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=cid, mpn=mpn, lcsc="",
                             qty=100, unit_price=price, position=i))
    db.flush()
    flash, flash_v = _deployment(db, proj, "rb-flash", "flash")
    test, test_v = _deployment(db, proj, "rb-test", "test")
    mark, mark_v = _deployment(db, proj, "rb-mark", "mark")
    graph = {
        "steps": [
            {"key": "assembly", "label": "Board from the assembler", "kind": "assembly", "required": True},
            {"key": "receive", "label": "Receive PCBA", "kind": "receive", "required": True},
            {"key": "antenna", "label": "Add antenna", "kind": "step", "required": True, "needs": ["receive"],
             "inputs": [{"component_id": ant.id, "qty": 1}]},
            {"key": "enclosure", "label": "Enclose", "kind": "step", "required": True, "needs": ["antenna"],
             "inputs": [{"component_id": enc.id, "qty": 1}]},
            {"key": "program", "label": "Program", "kind": "program", "required": True,
             "needs": ["receive", "antenna"], "deployment_id": flash.id},
            {"key": "test", "label": "Function test", "kind": "test", "required": True, "needs": ["program"],
             "deployment_id": test.id},
            {"key": "laser", "label": "Laser mark", "kind": "mark_laser", "required": True,
             "needs": ["enclosure", "program"], "deployment_id": mark.id},
            {"key": "label", "label": "Barcode label", "kind": "label", "required": True, "needs": ["program"],
             "deployment_id": mark.id, "inputs": [{"mpn": "TEST-RB-LABEL", "qty": 1}]},
            {"key": "carton", "label": "Carton", "kind": "step", "required": True, "needs": ["enclosure", "program"],
             "inputs": [{"mpn": "TEST-RB-KARTON", "qty": 1}]},
            {"key": "leaflet", "label": "Leaflet", "kind": "step", "required": False, "needs": ["program"]},
            {"key": "finish", "label": "Finished", "kind": "finish"},
        ],
        "route": ["assembly", "receive", "antenna", "enclosure", "program", "test", "laser", "label", "carton",
                  "leaflet", "finish"],
        "prepared": [],
    }
    v = P.compose(db, proj.id, actor="test", graph=graph)
    P.publish(db, v, actor="test", comment="rebuild evidence")
    return {"project": proj, "v": v, "ant": ant, "enc": enc, "flash": flash, "flash_v": flash_v,
            "test": test, "test_v": test_v, "mark": mark, "mark_v": mark_v, "n": [0]}


def _at(day: str, hour: int = 12) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)


def _old(db, w, days, run_date="2025-03-01", *, ant=None, enc=None, carton=None, label="TBO"):
    """A batch made before twins: one device per programming day in `days`,
    each with its passing flash run, BOM draws of the antenna, enclosure and
    carton (by default one per device), an assembly invoice, the final
    assembler's invoice and freight."""
    proj = w["project"]
    run = M.ProductionRun(project_id=proj.id, label=f"{label}{w['n'][0]}", run_date=run_date,
                          status="completed", qty=len(days))
    db.add(run)
    db.flush()
    devices = []
    for day in days:
        w["n"][0] += 1
        n = w["n"][0]
        d = M.DeviceUnit(project_id=proj.id, serial=f"RB{n:010d}", mac=f"00:00:00:rb:{n // 256:02x}:{n % 256:02x}",
                         tasmota_id=f"dongle_RB{n:010d}", first_seen=_at(day, 9))
        db.add(d)
        db.flush()
        osvc.mark_produced(db, d, run.id, at=_at(day), actor="test")
        db.add(M.ProgrammingRun(device_unit_id=d.id, production_run_id=run.id, status="pass",
                                deployment_version_id=w["flash_v"][0].id, started_at=_at(day, 10)))
        devices.append(d)
    n = len(days)
    for cid, mpn, qty, price in ((w["ant"].id, "", ant, 1.0), (w["enc"].id, "", enc, 2.0),
                                 (None, "TEST-RB-KARTON", carton, 0.5)):
        db.add(M.ComponentConsumption(run_id=run.id, component_id=cid, mpn=mpn, lcsc="",
                                      qty=n if qty is None else qty, unit_cost_usd=price, basis="bom",
                                      consumed_at=run_date))
    doc = M.RunCostDocument(project_id=proj.id, run_id=run.id, doc_type="invoice", supplier="ASSY",
                            doc_number=f"RB-{run.id}", doc_date=run_date, currency="USD", total_amount=70.0)
    db.add(doc)
    db.flush()
    for i, (key, amount, text) in enumerate((("pcba:populated", 40.0, "populated boards"),
                                             ("final:device", 20.0, "device assembly"),
                                             ("logistics:inbound", 10.0, "freight"))):
        db.add(M.RunCostLine(document_id=doc.id, plan_key=key, qty=1, unit_price=amount, label=text, position=i))
    db.flush()
    return run, devices


def _bench_run(db, w, kind, device, day, *, status="pass", results=None, version=0, ops=None):
    """A bench run as the engine leaves it: a marking run names no device and
    keeps the topic it read."""
    dv = w[f"{kind}_v"][version]
    r = M.ProgrammingRun(device_unit_id=device.id if device is not None and kind != "mark" else None,
                         status=status, deployment_version_id=dv.id, started_at=_at(day, 14),
                         results=results or {})
    db.add(r)
    db.flush()
    for i, op in enumerate(ops or []):
        db.add(M.ProgrammingStep(run_id=r.id, idx=i, op=op, status="pass"))
    db.flush()
    return r


def _total(db, run):
    return ra.invoice_register(db)["by_run_usd"][str(run.id)]["total_usd"]


def _twin(db, d):
    return db.query(M.Twin).filter_by(device_unit_id=d.id).one()


def _links(db, tw, key):
    return (db.query(M.TwinStep, M.StepRun).join(M.StepRun, M.StepRun.id == M.TwinStep.step_run_id)
            .filter(M.TwinStep.twin_id == tw.id, M.StepRun.step_key == key).all())


def _alive_prices(db, *runs):
    twins = db.query(M.Twin).filter(M.Twin.origin_run_id.in_([r.id for r in runs]), M.Twin.found.is_(False),
                                    M.Twin.status != "scrapped").all()
    return sum(p["total_usd"] for p in T.prices(db, twins).values())


# ------------------------------------------------- evidence per device (hole 4)

def test_bench_runs_are_the_evidence_of_test_mark_and_label(db, w):
    run, (d0, d1, d2, d3) = _old(db, w, ["2025-03-01"] * 4)
    t0 = _bench_run(db, w, "test", d0, "2025-03-05")
    _bench_run(db, w, "test", d1, "2025-03-05", status="fail")     # a record: the test did not pass
    t3 = _bench_run(db, w, "test", d3, "2025-03-06", version=1)
    mk = _bench_run(db, w, "mark", d0, "2025-03-10", ops=["mark_laser", "print_label"],
                    results={"topic": d0.tasmota_id, "marked": d0.serial, "printed": d0.serial, "label_copies": 2})
    # the marking run reads no MAC: the link job finds its unit by the topic
    assert bench_links.link_by_topic(db, w["project"].id, dry_run=True)["linked"][0]["device_id"] == d0.id
    assert db.get(M.ProgrammingRun, mk.id).device_unit_id is None
    bench_links.link_by_topic(db, w["project"].id, dry_run=False)
    assert db.get(M.ProgrammingRun, mk.id).device_unit_id == d0.id
    before = _total(db, run)

    plan = R.rebuild(db, run, version_id=w["v"].id, assume={"test": {}, "laser": {"device_ids": [d2.id]}},
                     dry_run=False)
    assert plan["can_write"] and plan["batch_id"]
    tested = {d.id for d in (d0, d1, d2, d3) if _links(db, _twin(db, d), "test")}
    assert tested == {d0.id, d2.id, d3.id}              # d1 failed: a statement does not override it
    assert plan["bench_says_not_done"]["test"]["devices"] == 1
    # one click per day and deployment version, each twin naming its own run
    (ts0, sr0), = _links(db, _twin(db, d0), "test")
    (ts3, sr3), = _links(db, _twin(db, d3), "test")
    assert (ts0.programming_run_id, ts0.deployment_version_id, sr0.made_at) == (t0.id, w["test_v"][0].id, "2025-03-05")
    assert (ts3.programming_run_id, sr3.made_at) == (t3.id, "2025-03-06") and sr0.id != sr3.id
    (ts2, sr2), = _links(db, _twin(db, d2), "test")
    assert ts2.programming_run_id is None and sr2.made_at == "2025-03-01"   # stated: its programming day
    # the laser: the bench for d0, the statement for d2 only; the label: the bench for d0 only
    assert {d.id for d in (d0, d1, d2, d3) if _links(db, _twin(db, d), "laser")} == {d0.id, d2.id}
    (tl, label_click), = _links(db, _twin(db, d0), "label")
    assert tl.programming_run_id == mk.id and not _links(db, _twin(db, d1), "label")
    # the label step draws one label per copy printed, on the bench's day
    drawn = db.query(M.ComponentConsumption).filter_by(step_run_id=label_click.id).one()
    assert (drawn.qty, drawn.consumed_at) == (2, "2025-03-10")
    assert plan["check"]["ok"] and _total(db, run) == pytest.approx(before + 0.2, abs=1e-6)
    assert _alive_prices(db, run) == pytest.approx(before + 0.2, abs=0.01)
    # the per-device plan says where each step came from
    row = next(x for x in plan["devices"] if x["device_id"] == d0.id)
    assert row["steps"]["label"]["copies"] == 2 and row["steps"]["test"]["run"] == t0.id
    assert row["steps"]["test"]["version"] == "rb-test v1"
    assert next(x for x in plan["devices"] if x["device_id"] == d1.id)["bench_says_not_done"]


def test_an_invoice_pays_but_proves_nothing(db, w):
    run, _devices = _old(db, w, ["2025-03-01"] * 2)
    plan = R.rebuild(db, run, version_id=w["v"].id, costs={"final:device": ["leaflet"]})
    assert "leaflet" in {r["step"] for r in plan["not_recorded"]}
    assert [x["steps"] for x in plan["lines_whose_steps_were_not_recorded"]] == [["leaflet"]]
    assert "final:device" in [x["plan_key"] for x in plan["left_in_origin"]["lines"]]
    assert plan["check"]["ok"]


def test_a_statement_names_a_device_list_or_a_date_range(db, w):
    run, devices = _old(db, w, ["2025-03-01", "2025-03-10", "2025-03-20", "2025-03-30"])
    plan = R.rebuild(db, run, version_id=w["v"].id,
                     assume={"leaflet": {"since": "2025-03-05", "until": "2025-03-25"}})
    got = {x["device_id"] for x in plan["devices"] if "leaflet" in x["steps"]}
    assert got == {devices[1].id, devices[2].id}
    plan = R.rebuild(db, run, version_id=w["v"].id, assume={"leaflet": {"codes": [devices[0].serial]}})
    assert {x["device_id"] for x in plan["devices"] if "leaflet" in x["steps"]} == {devices[0].id}
    # the short form still works: since a date, every device programmed on or after it
    plan = R.rebuild(db, run, version_id=w["v"].id, assume=["leaflet"], until={"leaflet": "2025-03-10"})
    assert {x["device_id"] for x in plan["devices"] if "leaflet" in x["steps"]} == {devices[0].id, devices[1].id}
    _other, foreign = _old(db, w, ["2025-03-01"])
    with pytest.raises(HTTPException) as e:
        R.rebuild(db, run, version_id=w["v"].id, assume={"leaflet": {"device_ids": [foreign[0].id]}})
    assert e.value.status_code == 422 and "not produced in this batch" in str(e.value.detail)
    with pytest.raises(HTTPException):
        R.rebuild(db, run, version_id=w["v"].id, assume={"leaflet": {"since": "2025-04-01", "until": "2025-03-01"}})


def test_units_in_progress_stay_active_and_take_later_bench_steps(db, w):
    run, (d0, d1, d2) = _old(db, w, ["2025-03-01", "2025-03-10", "2025-03-20"])
    plan = R.rebuild(db, run, version_id=w["v"].id, active={"since": "2025-03-10"}, dry_run=False)
    assert (plan["finished"], plan["active"]) == (1, 2)
    assert [_twin(db, d).status for d in (d0, d1, d2)] == ["finished", "active", "active"]
    # an active rebuilt twin takes a later bench step; a finished one never would
    assert T.record_marking(db, d2, laser=True, label=False, deployment_id=w["mark"].id) == ["laser"]
    assert T.record_marking(db, d0, laser=True, label=False, deployment_id=w["mark"].id) == []


# ------------------------------------------------------------ dates (hole 9)

def test_each_step_carries_its_own_date(db, w):
    run, (d0, _d1, d2) = _old(db, w, ["2025-03-01", "2025-03-10", "2025-03-10"], run_date="2025-03-05")
    osvc.record_event(db, d2, "disposed", at=_at("2025-04-02"), actor="test", reason="cracked")
    d2.state = "disposed"
    db.flush()
    plan = R.rebuild(db, run, version_id=w["v"].id, dry_run=False)
    assert plan["dates"]["before_programming"] == "2025-03-01"   # the first programming came first
    clicks = {(sr.step_key, sr.made_at): sr for sr in db.query(M.StepRun).filter_by(run_id=run.id)}
    assert ("receive", "2025-03-01") in clicks and ("enclosure", "2025-03-01") in clicks
    # after programming: one click a day, on each device's own day
    assert sorted(day for k, day in clicks if k == "carton") == ["2025-03-01", "2025-03-10"]
    assert sorted(day for k, day in clicks if k == "program") == ["2025-03-01", "2025-03-10"]
    # the carton draw was split, a piece per click, and its value is whole
    cartons = (ra.live_consumption(db, run_id=run.id).filter(M.ComponentConsumption.mpn == "TEST-RB-KARTON").all())
    assert sorted(c.qty for c in cartons) == [1, 2] and sum(c.qty * c.unit_cost_usd for c in cartons) == 1.5
    assert all(c.step_run_id for c in cartons)
    tw2 = _twin(db, d2)
    assert tw2.status == "scrapped" and tw2.scrapped_at.date().isoformat() == "2025-04-02"
    assert ("scrap", "2025-04-02") in clicks
    assert _twin(db, d0).finished_at.date().isoformat() == "2025-03-01"


# ------------------------------------------------------- parts vs units (hole 5)

def test_draws_that_do_not_match_the_units_must_be_settled(db, w):
    run, _devices = _old(db, w, ["2025-03-01"] * 3, enc=5, carton=2)
    before = _total(db, run)
    dry = R.rebuild(db, run, version_id=w["v"].id)
    bad = {(r["step"], r["part"]): r for r in dry["unsettled"]}
    assert set(bad) == {("enclosure", f"c{w['enc'].id}"), ("carton", "mTESTRBKARTON")}
    assert (bad[("enclosure", f"c{w['enc'].id}")]["surplus"], bad[("carton", "mTESTRBKARTON")]["deficit"]) == (2, 1)
    assert not dry["can_write"]
    with pytest.raises(HTTPException) as e:
        R.rebuild(db, run, version_id=w["v"].id, dry_run=False)
    assert e.value.status_code == 409 and "no statement" in str(e.value.detail)
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    # within the tolerance nothing needs saying
    assert R.rebuild(db, run, version_id=w["v"].id, tolerance=2)["can_write"]
    plan = R.rebuild(db, run, version_id=w["v"].id, dry_run=False,
                     settle=[{"step": "enclosure", "part": f"c{w['enc'].id}", "how": "loss"},
                             {"step": "carton", "how": "draw"}])
    assert plan["can_write"] and plan["check"]["ok"]
    assert [(x["step"], x["qty"]) for x in plan["left_in_origin"]["loss"]] == [("enclosure", 2)]
    assert [(d["step"], d["qty"]) for d in plan["draws_added"]] == [("carton", 1)]
    assert _total(db, run) == pytest.approx(before + 0.5, abs=1e-6)
    # each twin carries one enclosure; the two left over sit in the origin share
    per = {p["own_parts_usd"] for p in T.prices(db, db.query(M.Twin).filter_by(origin_run_id=run.id).all()).values()}
    assert per == {3.5}          # antenna $1 + enclosure $2 + carton $0.50
    assert _alive_prices(db, run) == pytest.approx(before + 0.5, abs=0.01)
    # short: the step is recorded without the missing carton
    run2, _d = _old(db, w, ["2025-03-01"] * 3, carton=2)
    plan2 = R.rebuild(db, run2, version_id=w["v"].id, settle=[{"step": "carton", "how": "short"}])
    assert plan2["can_write"] and plan2["draws_added"] == []


def test_a_returned_surplus_gives_its_lots_back_and_the_undo_restores_it(db, w, monkeypatch):
    run, _devices = _old(db, w, ["2025-03-01"] * 3, enc=5)
    enc = ra.live_consumption(db, run_id=run.id).filter(M.ComponentConsumption.component_id == w["enc"].id).one()
    L.bind(db, enc, L.FifoPicker(db).pick(w["enc"].id, "", "", 5, "2025-03-01"))
    monkeypatch.setattr(settings, "lot_pricing", True)
    before = _total(db, run)
    plan = R.rebuild(db, run, version_id=w["v"].id, dry_run=False,
                     settle=[{"step": "enclosure", "how": "return"}])
    assert plan["check"]["ok"] and [(x["qty"], x["usd"]) for x in plan["draws_returned"]] == [(2, 4.0)]
    db.expire_all()
    left = ra.live_consumption(db, run_id=run.id).filter(M.ComponentConsumption.component_id == w["enc"].id).all()
    bound = db.query(M.ComponentConsumptionLot).filter(
        M.ComponentConsumptionLot.consumption_id.in_([c.id for c in left])).all()
    assert sum(c.qty for c in left) == 3 and sum(b.qty for b in bound) == pytest.approx(3)
    assert _total(db, run) == pytest.approx(before - 4.0, abs=1e-6)
    R.undo(db, run, dry_run=False)
    db.expire_all()
    back = db.get(M.ComponentConsumption, enc.id)
    assert back.qty == 5 and back.step_run_id is None
    assert sum(b.qty for b in db.query(M.ComponentConsumptionLot).filter_by(consumption_id=enc.id)) == pytest.approx(5)
    assert _total(db, run) == pytest.approx(before, abs=1e-6)


# ------------------------------------------------ append and undo (hole 6)

def test_devices_that_join_later_are_appended(db, w):
    run, _ds = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, run, version_id=w["v"].id, costs={"final:device": ["carton"]}, dry_run=False)
    with pytest.raises(HTTPException):
        R.rebuild(db, run, version_id=w["v"].id, dry_run=False)      # one-shot without append
    # a device found later to belong to the batch
    d2 = M.DeviceUnit(project_id=w["project"].id, serial="RBLATE000001", mac="00:00:00:rb:ff:01",
                      first_seen=_at("2025-03-03", 9))
    db.add(d2)
    db.flush()
    osvc.mark_produced(db, d2, run.id, at=_at("2025-03-03"), actor="test")
    dry = R.rebuild(db, run, append=True)
    assert {r["step"] for r in dry["unsettled"]} == {"antenna", "enclosure", "carton"}   # all drawn parts are used
    plan = R.rebuild(db, run, append=True, settle=[{"step": k, "how": "draw"} for k in ("antenna", "enclosure",
                                                                                         "carton")], dry_run=False)
    assert (plan["named"], plan["devices_with_a_twin_already"]) == (1, 2) and plan["check"]["ok"]
    asm = R._rebuilt_click(db, run, "assembly")
    assert asm.qty == 3 and _links(db, _twin(db, d2), "assembly")
    # the final assembler's invoice pays for the new carton click too: three twins share it
    li = db.query(M.RunCostLine).filter_by(label="device assembly").join(
        M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id).filter(
        M.RunCostDocument.run_id == run.id).one()
    shared = next(sh for sh in T.line_shares(db, [run.id]) if sh["line"].id == li.id)
    assert len(shared["twins"]) == 3
    assert _alive_prices(db, run) == pytest.approx(_total(db, run), abs=0.01)
    undone = R.undo(db, run, dry_run=False)
    assert len(undone["rebuild_batches"]) == 2
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0 and run.process_version_id is None


def test_the_undo_takes_back_the_live_clicks_on_rebuilt_twins(db, w):
    from app.routers import process as pr

    run, (d0, d1) = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, run, version_id=w["v"].id, active={}, dry_run=False)    # the whole batch in progress
    leaflet = pr.craft_step(run.id, pr.StepIn(step_key="leaflet", device_ids=[d0.id], chosen="list",
                                              dry_run=False), db=db)
    assert T.record_marking(db, d1, laser=True, label=False, deployment_id=w["mark"].id) == ["laser"]
    dry = R.undo(db, run)
    kinds = sorted((x["kind"], (x.get("step") or x["clicks"][0]["step"])) for x in dry["takes_back"])
    assert kinds == [("bench", "laser"), ("journal", "leaflet")] and not dry["refused"]
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 2      # a dry run keeps everything
    R.undo(db, run, dry_run=False)
    db.expire_all()
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    assert db.get(M.StepRun, leaflet["step_run_id"]) is None
    assert db.query(M.StepRun).filter_by(run_id=run.id).count() == 0


# ---------------------------------------------------- the origin batch (hole 7)

def test_devices_built_on_another_batch_s_boards_keep_its_origin(db, w):
    x, _xd = _old(db, w, ["2025-02-01"] * 2, run_date="2025-02-01", label="TBX")
    run, (_d0, _d1, d2) = _old(db, w, ["2025-03-01"] * 3, label="TBY")
    origins = [{"from_run_id": x.id, "device_ids": [d2.id]}]
    with pytest.raises(HTTPException) as e:
        R.rebuild(db, run, version_id=w["v"].id, origins=origins)
    assert e.value.status_code == 409 and f"rebuild {x.label} first" in str(e.value.detail)
    R.rebuild(db, x, version_id=w["v"].id, dry_run=False)
    share_before = T.origin_shares(db, [x.id])[x.id]["share_usd"]
    plan = R.rebuild(db, run, version_id=w["v"].id, origins=origins, dry_run=False)
    assert plan["check"]["ok"] and plan["check"]["batches"] == sorted([x.id, run.id])
    tw2 = _twin(db, d2)
    assert (tw2.origin_run_id, tw2.run_id) == (x.id, run.id) and x.label in tw2.note
    assert R._rebuilt_click(db, x, "assembly").qty == 3 and R._rebuilt_click(db, run, "assembly").qty == 2
    # X's boards now spread over three twins; the money of both batches is carried whole
    assert T.origin_shares(db, [x.id])[x.id]["share_usd"] < share_before
    assert _alive_prices(db, run, x) == pytest.approx(_total(db, run) + _total(db, x), abs=0.01)
    # X cannot be undone while the batch built on its boards stands
    with pytest.raises(HTTPException) as e:
        R.undo(db, x, dry_run=False)
    assert "undo it first" in str(e.value.detail)
    # a source batch nobody knows is written on the twin
    other, (u0,) = _old(db, w, ["2025-03-01"], label="TBU")
    R.rebuild(db, other, version_id=w["v"].id, origins=[{"from_run_id": None, "device_ids": [u0.id]}],
              dry_run=False)
    assert "source batch unknown" in _twin(db, u0).note


# --------------------------------------------- found units and spares (hole 8)

def test_found_units_naming_the_batch_are_reported_and_spares_enter_once(db, w):
    run, _devices = _old(db, w, ["2025-03-01"] * 2)
    crafted = M.ProductionRun(project_id=w["project"].id, label="TB-live", run_date="2025-05-01",
                              status="completed", process_version_id=w["v"].id, qty=1)
    db.add(crafted)
    db.flush()
    T.enter_found(db, crafted, qty=2, done=[], origin_run_id=run.id, note="count", dry_run=False)
    plan = R.rebuild(db, run, version_id=w["v"].id)
    assert plan["found_naming_this_batch"]["unnamed_active"] == 2 and plan["can_write"]
    plan = R.rebuild(db, run, version_id=w["v"].id, spares=[{"qty": 2, "done": [], "note": "shelf"}])
    assert not plan["can_write"] and "enter counted spares one way" in plan["refusals"][0]["message"]


# --------------------------------------------------------- the link job (hole 4)

def test_the_link_job_takes_only_a_single_match(db, w):
    _run, (d0, d1, d2) = _old(db, w, ["2025-03-01"] * 3)
    d2.tasmota_id = d1.tasmota_id         # two devices answer one topic
    db.flush()
    one = _bench_run(db, w, "mark", None, "2025-03-10", results={"topic": d0.tasmota_id, "marked": "x"})
    two = _bench_run(db, w, "mark", None, "2025-03-10", results={"topic": d1.tasmota_id, "marked": "x"})
    none = _bench_run(db, w, "mark", None, "2025-03-10", results={"topic": "dongle_NOBODY000000"})
    blank = _bench_run(db, w, "mark", None, "2025-03-10", results={})
    res = bench_links.link_by_topic(db, w["project"].id, dry_run=False)
    assert [x["run_id"] for x in res["linked"]] == [one.id]
    assert ([x["run_id"] for x in res["ambiguous"]], [x["run_id"] for x in res["unmatched"]],
            [x["run_id"] for x in res["no_topic"]]) == ([two.id], [none.id], [blank.id])
    assert (db.get(M.ProgrammingRun, one.id).device_unit_id, db.get(M.ProgrammingRun, two.id).device_unit_id) == (
        d0.id, None)


# ------------------------------------------------------------------ the route

def test_the_route_dry_run_keeps_the_transaction_and_a_write_is_one_journal_batch(db, w):
    from app.routers import process as pr

    run, _devices = _old(db, w, ["2025-03-01"] * 2)
    dry = pr.rebuild_batch(run.id, pr.RebuildIn(version_id=w["v"].id, assume={"leaflet": pr.DevicesIn()}), db=db)
    assert dry["dry_run"] and db.get(M.Project, w["project"].id) is not None     # the fixture survives
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    res = pr.rebuild_batch(run.id, pr.RebuildIn(version_id=w["v"].id, dry_run=False), db=db)
    wb = db.get(M.WriteBatch, res["batch_id"])
    assert (wb.kind, wb.source_ref) == ("craft.rebuild", f"run:{run.id}")
    assert pr.undo_rebuild(run.id, pr.UndoIn(), db=db)["rebuild_batches"] == [wb.id]
    pr.undo_rebuild(run.id, pr.UndoIn(dry_run=False), db=db)
    db.expire_all()
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    assert db.get(M.WriteBatch, wb.id).reversed_at is not None


# ---------------------------------------- second review regressions (0074, 0075)


def test_the_program_step_names_the_first_passing_program_run_of_the_device(db, w):
    """R2-2: the old flasher wrote no batch on the pass that produced the
    device. A reflash in the batch weeks later must not take its place, and an
    erase that passed first is no programming."""
    run, (d0,) = _old(db, w, ["2025-03-01"])
    first = db.query(M.ProgrammingRun).filter_by(device_unit_id=d0.id).one()
    first.production_run_id = None
    erase = M.ProgrammingRun(device_unit_id=d0.id, action="erase", status="pass",
                             deployment_version_id=w["flash_v"][0].id, started_at=_at("2025-03-01", 8))
    reflash = M.ProgrammingRun(device_unit_id=d0.id, production_run_id=run.id, action="program", status="pass",
                               deployment_version_id=w["flash_v"][1].id, started_at=_at("2025-03-20", 10))
    db.add_all([erase, reflash])
    db.flush()
    plan = R.rebuild(db, run, version_id=w["v"].id, dry_run=False)
    assert plan["can_write"]
    (ts, sr), = _links(db, _twin(db, d0), "program")
    assert (ts.programming_run_id, ts.deployment_version_id, sr.made_at) == (first.id, w["flash_v"][0].id,
                                                                             "2025-03-01")
    row = next(x for x in plan["devices"] if x["device_id"] == d0.id)
    assert (row["steps"]["program"]["run"], row["steps"]["program"]["version"]) == (first.id, "rb-flash v1")
    # the later pass is a reflash on the twin card, not the programming
    assert [r["programming_run_id"] for r in T.twin_json(db, _twin(db, d0))["reflashes"]] == [reflash.id]


def test_a_unit_that_left_us_stays_finished(db, w):
    """R2-3: shipped or missing, the unit is finished even when `active` names
    it or its condition is faulty; only a unit we hold stays active."""
    run, (d_ship, d_miss, d_here, d_back) = _old(db, w, ["2025-03-01"] * 4)
    osvc.record_event(db, d_ship, "shipped", at=_at("2025-04-01"), actor="test")
    osvc.record_event(db, d_miss, "missing", at=_at("2025-04-01"), actor="test")
    d_miss.condition = "faulty"
    osvc.record_event(db, d_back, "shipped", at=_at("2025-04-01"), actor="test")
    osvc.record_event(db, d_back, "returned", at=_at("2025-04-05"), actor="test")
    d_back.condition = "faulty"
    db.flush()
    plan = R.rebuild(db, run, version_id=w["v"].id, active={"device_ids": [d_ship.id, d_here.id]}, dry_run=False)
    assert plan["can_write"] and (plan["finished"], plan["active"]) == (2, 2)
    assert [_twin(db, d).status for d in (d_ship, d_miss, d_here, d_back)] == ["finished", "finished", "active",
                                                                               "active"]
    assert _links(db, _twin(db, d_ship), "finish") and not _links(db, _twin(db, d_here), "finish")


def test_a_spare_carries_no_bench_step_and_no_step_whose_needs_it_lacks(db, w):
    """R2-5: the bench records programming, a test, a mark and a label on the
    device later; a spare's other steps must have their needs met."""
    run, _devices = _old(db, w, ["2025-03-01"] * 2)
    for done, why in ((["program"], "a spare carries no bench step"), (["test"], "a spare carries no bench step"),
                      (["laser"], "a spare carries no bench step"), (["label"], "a spare carries no bench step"),
                      (["enclosure"], "needs 'Add antenna'"), (["antenna", "enclosure", "carton"], "needs 'Program'")):
        with pytest.raises(HTTPException) as e:
            R.rebuild(db, run, version_id=w["v"].id, spares=[{"qty": 1, "done": done}])
        assert e.value.status_code == 422 and why in str(e.value.detail), done
    plan = R.rebuild(db, run, version_id=w["v"].id, spares=[{"qty": 1, "done": ["antenna", "enclosure"]}],
                     settle=[{"step": "antenna", "how": "short"}, {"step": "enclosure", "how": "short"}])
    assert plan["can_write"] and plan["spares"] == 1


def test_parts_meet_by_pool_identity(db, w):
    """R2-8: a draw carrying a component id meets an input named by its MPN,
    and a draw naming the MPN meets an input naming the component; the plan
    and `settle` use the pool's key, and the matching ends with the rebuild."""
    import copy

    ant, enc = w["ant"], w["enc"]
    for li in db.query(M.RunCostLine).filter(M.RunCostLine.component_id.in_([ant.id, enc.id])).all():
        li.mpn = "TEST-RB-ANT" if li.component_id == ant.id else "TEST-RB-ENC"     # the pool knows both names
    g = copy.deepcopy(P._graph(w["v"]))
    next(s for s in g["steps"] if s["key"] == "antenna")["inputs"] = [{"mpn": "TEST-RB-ANT", "qty": 1}]
    v2 = P.compose(db, w["project"].id, actor="test", graph=g)
    P.publish(db, v2, actor="test", comment="antenna by MPN")
    run, _devices = _old(db, w, ["2025-03-01"] * 3, ant=5)          # the antenna draw carries the component id
    enc_draw = ra.live_consumption(db, run_id=run.id).filter(M.ComponentConsumption.component_id == enc.id).one()
    enc_draw.component_id, enc_draw.mpn = None, "TEST-RB-ENC"       # the enclosure draw names its MPN only
    db.flush()
    dry = R.rebuild(db, run, version_id=v2.id)
    rows = {r["step"]: r for r in dry["parts"]}
    assert (rows["antenna"]["part"], rows["antenna"]["drawn"], rows["antenna"]["surplus"]) == (f"c{ant.id}", 5, 2)
    assert (rows["enclosure"]["part"], rows["enclosure"]["drawn"], rows["enclosure"]["need"]) == (f"c{enc.id}", 3, 3)
    assert dry["left_in_origin"]["draws"] == [] and {"antenna", "enclosure"} <= {r["step"] for r in dry["recorded"]}
    assert [(r["step"], r["part"]) for r in dry["unsettled"]] == [("antenna", f"c{ant.id}")]
    assert R._CANON.get() is None
    with pytest.raises(HTTPException) as e:
        R.rebuild(db, run, version_id=v2.id, dry_run=False)          # refused: the surplus has no statement
    assert e.value.status_code == 409 and R._CANON.get() is None
    plan = R.rebuild(db, run, version_id=v2.id, dry_run=False,
                     settle=[{"step": "antenna", "part": f"c{ant.id}", "how": "loss"}])
    assert plan["can_write"] and plan["check"]["ok"] and R._CANON.get() is None
    assert [(x["step"], x["part"], x["qty"]) for x in plan["left_in_origin"]["loss"]] == [("antenna", f"c{ant.id}", 2)]
    assert db.get(M.ComponentConsumption, enc_draw.id).step_run_id is not None


def test_the_undo_takes_back_a_disposal_from_the_device_page(db, w):
    run, (d0, _d1) = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, run, version_id=w["v"].id, dry_run=False)
    osvc.dispose_device(db, d0, reason="cracked", actor="test")
    scrap = db.query(M.StepRun).filter_by(run_id=run.id, kind="scrap", chosen="list").one()
    assert _twin(db, d0).status == "scrapped" and scrap.note == "disposed of: cracked (was finished)"
    dry = R.undo(db, run)
    assert not dry["refused"]
    assert [(x["kind"], x["step"]) for x in dry["takes_back"]] == [("bench", "scrap")]
    R.undo(db, run, dry_run=False)
    db.expire_all()
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    assert db.query(M.StepRun).filter_by(run_id=run.id).count() == 0
    assert db.get(M.DeviceUnit, d0.id).state == "disposed"
    # the device keeps its disposal, so a new rebuild scraps the twin again
    again = R.rebuild(db, db.get(M.ProductionRun, run.id), version_id=w["v"].id, dry_run=False)
    assert again["scrapped"] == 1 and _twin(db, d0).status == "scrapped"


def test_the_undo_refuses_while_the_returned_surplus_is_drawn_again(db, w, monkeypatch):
    run, _devices = _old(db, w, ["2025-03-01"] * 3, enc=5)
    enc = ra.live_consumption(db, run_id=run.id).filter(M.ComponentConsumption.component_id == w["enc"].id).one()
    L.bind(db, enc, L.FifoPicker(db).pick(w["enc"].id, "", "", 5, "2025-03-01"))
    monkeypatch.setattr(settings, "lot_pricing", True)
    R.rebuild(db, run, version_id=w["v"].id, dry_run=False, settle=[{"step": "enclosure", "how": "return"}])
    other = M.ProductionRun(project_id=w["project"].id, label="TB-drain", run_date="2025-04-01",
                            status="completed", qty=1)
    db.add(other)
    db.flush()
    # 100 bought, 3 kept: the 2 returned are drawn again by another batch
    drain = M.ComponentConsumption(run_id=other.id, component_id=w["enc"].id, mpn="", lcsc="", qty=97,
                                   unit_cost_usd=2.0, basis="bom", consumed_at="2025-04-01")
    db.add(drain)
    db.flush()
    dry = R.undo(db, run)
    assert len(dry["refused"]) == 1 and "drawn again since" in dry["refused"][0] and "short 2" in dry["refused"][0]
    with pytest.raises(HTTPException) as e:
        R.undo(db, run, dry_run=False)
    assert e.value.status_code == 409
    assert db.get(M.ComponentConsumption, enc.id).qty == 3      # nothing was kept
    drain.qty = 95                                               # the pool holds the 2 again
    db.flush()
    assert not R.undo(db, run)["refused"]


def test_the_undo_takes_back_the_links_its_whole_step_key_made_since(db, w):
    from app.routers import process as pr

    a, _ad = _old(db, w, ["2025-02-01"] * 2, run_date="2025-02-01", label="TBA")
    R.rebuild(db, a, version_id=w["v"].id, costs={"final:device": ["program"]}, dry_run=False)
    li = (db.query(M.RunCostLine).join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
          .filter(M.RunCostDocument.run_id == a.id, M.RunCostLine.plan_key == "final:device").one())
    # a live batch's board is programmed at A's bench: the whole-step key links that click
    c = M.ProductionRun(project_id=w["project"].id, label="TB-C", run_date="2025-06-01", status="in_progress",
                        process_version_id=w["v"].id, qty=1)
    db.add(c)
    db.flush()
    pr.craft_receive(c.id, pr.ReceiveIn(qty=1, made_at="2025-06-01", dry_run=False), db=db)
    pile = db.query(M.Twin).filter_by(run_id=c.id).one()
    pr.craft_step(c.id, pr.StepIn(step_key="antenna", stack=T.stack_id(c.id, pile.stack_key), qty=1,
                                  chosen="stack", made_at="2025-06-01", dry_run=False), db=db)
    db.refresh(pile)
    a.bench_stack = T.stack_id(c.id, pile.stack_key)
    d = M.DeviceUnit(project_id=w["project"].id, serial="RBLIVEC00001", mac="00:00:00:rb:ec:01")
    db.add(d)
    db.flush()
    ev = osvc.mark_produced(db, d, a.id, at=_at("2025-06-02"), actor="test")
    assert T.name_at_bench(db, d, ev, a).id == pile.id
    bench = db.query(M.StepRun).filter_by(run_id=a.id, chosen="bench").one()
    assert db.query(M.CostLineStep).filter_by(step_run_id=bench.id, line_id=li.id).count() == 1
    dry = R.undo(db, a)
    assert not dry["refused"]
    assert [(x["kind"], x["click_id"]) for x in dry["takes_back"]] == [("link", bench.id)]
    R.undo(db, a, dry_run=False)
    db.expire_all()
    assert db.query(M.Twin).filter_by(origin_run_id=a.id).count() == 0
    # the click and the live twin stay; the position pays for nothing any more
    assert db.get(M.StepRun, bench.id) is not None and db.get(M.Twin, pile.id).device_unit_id == d.id
    assert db.query(M.CostLineStep).filter_by(line_id=li.id).count() == 0
    assert db.query(M.CostLineStepKey).filter_by(line_id=li.id).count() == 0


def test_the_undo_refuses_while_a_batch_it_touched_is_closed(db, w):
    from app.routers import production_runs as prr

    a, _ad = _old(db, w, ["2025-02-01"] * 2, run_date="2025-02-01", label="TBA")
    b, bd = _old(db, w, ["2025-03-01"] * 3, label="TBB")
    R.rebuild(db, a, version_id=w["v"].id, dry_run=False)
    R.rebuild(db, b, version_id=w["v"].id, origins=[{"from_run_id": a.id, "device_ids": [bd[2].id]}], dry_run=False)
    prr.close_run(a.id, db=db)
    dry = R.undo(db, b)
    assert dry["refused"] == [f"batch {a.label} is closed, and this rebuild changed its clicks or twins — reopen it first"]
    with pytest.raises(HTTPException) as e:
        R.undo(db, b, dry_run=False)
    assert e.value.status_code == 409
    db.expire_all()
    # A's frozen clicks keep the twin built on its boards
    assert R._rebuilt_click(db, a, "assembly").qty == 3 and _twin(db, bd[2]).origin_run_id == a.id


def test_the_undo_refuses_a_bench_click_in_another_closed_batch(db, w):
    from app.routers import production_runs as prr

    a, _ad = _old(db, w, ["2025-02-01"] * 2, run_date="2025-02-01", label="TBA", ant=3, enc=3)
    R.rebuild(db, a, version_id=w["v"].id, spares=[{"qty": 1, "done": ["antenna", "enclosure"]}], dry_run=False)
    spare = db.query(M.Twin).filter(M.Twin.origin_run_id == a.id, M.Twin.device_unit_id.is_(None)).one()
    b = M.ProductionRun(project_id=w["project"].id, label="TB-live", run_date="2025-06-01", status="in_progress",
                        process_version_id=w["v"].id, qty=1, bench_stack=T.stack_id(a.id, spare.stack_key))
    d = M.DeviceUnit(project_id=w["project"].id, serial="RBLIVE000001", mac="00:00:00:rb:ee:01")
    db.add_all([b, d])
    db.flush()
    ev = osvc.mark_produced(db, d, b.id, at=_at("2025-06-02"), actor="test")
    assert T.name_at_bench(db, d, ev, b).id == spare.id
    assert T.record_marking(db, d, laser=False, label=True, deployment_id=w["mark"].id) == ["label"]
    prr.close_run(b.id, db=db)
    clicks = db.query(M.StepRun).filter_by(run_id=b.id, chosen="bench").all()
    dry = R.undo(db, a)
    assert sorted(dry["refused"]) == sorted(f"click #{sr.id} ({sr.step_label}) is in closed batch TB-live — reopen it first"
                                            for sr in clicks)
    with pytest.raises(HTTPException):
        R.undo(db, a, dry_run=False)
    db.expire_all()
    # the closed batch keeps its clicks and the label it drew
    assert db.query(M.StepRun).filter_by(run_id=b.id).count() == 2
    assert _total(db, db.get(M.ProductionRun, b.id)) == pytest.approx(0.1, abs=1e-6)


def test_the_undo_reverses_an_append_that_wrote_no_click(db, w):
    run, _ds = _old(db, w, ["2025-03-01", "2025-03-02"])
    first = R.rebuild(db, run, version_id=w["v"].id, dry_run=False)
    more = R.rebuild(db, run, append=True, spares=[{"qty": 2, "done": []}], dry_run=False)
    wb = db.get(M.WriteBatch, more["batch_id"])
    assert not [r for r in wb.rows if r.table_name == "step_runs" and r.op == "insert"]
    dry = R.undo(db, run)
    assert not dry["refused"] and dry["rebuild_batches"] == [more["batch_id"], first["batch_id"]]
    R.undo(db, run, dry_run=False)
    db.expire_all()
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    assert all(db.get(M.WriteBatch, b).reversed_at is not None for b in (first["batch_id"], more["batch_id"]))


def test_an_append_waits_while_another_rebuild_joined_the_batch(db, w):
    a, _ad = _old(db, w, ["2025-02-01"] * 2, run_date="2025-02-01", label="TBA", ant=3, enc=3, carton=3)
    b, bd = _old(db, w, ["2025-03-01"] * 3, label="TBB")
    R.rebuild(db, a, version_id=w["v"].id, dry_run=False,
              settle=[{"step": k, "how": "loss"} for k in ("antenna", "enclosure", "carton")])
    R.rebuild(db, b, version_id=w["v"].id, origins=[{"from_run_id": a.id, "device_ids": [bd[2].id]}], dry_run=False)
    late = M.DeviceUnit(project_id=w["project"].id, serial="RBLATEA00001", mac="00:00:00:rb:fe:01")
    db.add(late)
    db.flush()
    osvc.mark_produced(db, late, a.id, at=_at("2025-02-03"), actor="test")
    settle = [{"step": k, "how": "draw"} for k in ("antenna", "enclosure", "carton")]
    for dry_run in (True, False):
        with pytest.raises(HTTPException) as e:
            R.rebuild(db, a, append=True, settle=settle, dry_run=dry_run)
        assert e.value.status_code == 409
        assert f"the rebuild of {b.label} joined {a.label}'s rebuilt assembly" in str(e.value.detail)
    # both rebuilds stay undoable: B first, then A
    assert not R.undo(db, b)["refused"]
    R.undo(db, b, dry_run=False)
    assert not R.undo(db, a)["refused"]


def test_taking_back_a_bench_click_keeps_a_step_another_click_holds(db, w):
    from app.routers import process as pr

    run, (d0, _d1) = _old(db, w, ["2025-03-01", "2025-03-02"])
    db.add(M.ProgrammingRun(device_unit_id=d0.id, status="pass", deployment_version_id=w["mark_v"][0].id,
                            started_at=_at("2025-03-05", 14), results={"printed": True}))
    db.flush()
    R.rebuild(db, run, version_id=w["v"].id, dry_run=False)
    assert _links(db, _twin(db, d0), "label")          # the rebuilt label click, from the marking run
    pr.craft_reopen(run.id, pr.ReopenIn(device_ids=[d0.id], chosen="list", reason="new label", dry_run=False), db=db)
    assert T.record_marking(db, d0, laser=False, label=True, deployment_id=w["mark"].id) == ["label"]
    dry = R.undo(db, run)
    assert not dry["refused"]
    assert [(x["kind"], x.get("step") or x["clicks"][0]["step"]) for x in dry["takes_back"]] == [
        ("bench", "label"), ("journal", "reopen")]
    R.undo(db, run, dry_run=False)
    db.expire_all()
    assert db.query(M.Twin).filter_by(origin_run_id=run.id).count() == 0
    assert db.query(M.StepRun).filter_by(run_id=run.id).count() == 0


def test_the_undo_puts_back_the_version_the_batch_had_pinned(db, w):
    run, _ds = _old(db, w, ["2025-03-01", "2025-03-02"])
    run.process_version_id = w["v"].id          # as creating a batch pins the current version
    db.flush()
    plan = R.rebuild(db, run, dry_run=False)
    assert db.get(M.WriteBatch, plan["batch_id"]).summary["pinned_before"] == w["v"].id
    late = M.DeviceUnit(project_id=w["project"].id, serial="RBLATE000009", mac="00:00:00:rb:ff:09")
    db.add(late)
    db.flush()
    osvc.mark_produced(db, late, run.id, at=_at("2025-03-03"), actor="test")
    more = R.rebuild(db, run, append=True, dry_run=False,
                     settle=[{"step": k, "how": "draw"} for k in ("antenna", "enclosure", "carton")])
    assert db.get(M.WriteBatch, more["batch_id"]).summary["pinned_before"] is None   # an append names none
    R.undo(db, run, dry_run=False)
    db.expire_all()
    assert db.get(M.ProductionRun, run.id).process_version_id == w["v"].id     # from the oldest batch
    # a batch that had pinned nothing goes back to nothing
    other, _od = _old(db, w, ["2025-03-01"])
    R.rebuild(db, other, version_id=w["v"].id, dry_run=False)
    R.undo(db, other, dry_run=False)
    assert db.get(M.ProductionRun, other.id).process_version_id is None


def test_a_deficit_the_pool_already_had_does_not_stop_the_undo(db, w, monkeypatch):
    """The final check (decision 0075): another batch overdrew the enclosures
    BEFORE the rebuild returned the surplus, and nothing was drawn since. The
    undo puts back exactly what was there, so it is no reason to refuse."""
    run, _devices = _old(db, w, ["2025-03-01"] * 3, enc=5)
    enc = ra.live_consumption(db, run_id=run.id).filter(M.ComponentConsumption.component_id == w["enc"].id).one()
    other = M.ProductionRun(project_id=w["project"].id, label="TB-early", run_date="2025-02-15",
                            status="completed", qty=1)
    db.add(other)
    db.flush()
    db.add(M.ComponentConsumption(run_id=other.id, component_id=w["enc"].id, mpn="", lcsc="", qty=120,
                                  unit_cost_usd=2.0, basis="bom", consumed_at="2025-02-15"))
    db.flush()
    R.rebuild(db, run, version_id=w["v"].id, dry_run=False, settle=[{"step": "enclosure", "how": "return"}])
    assert db.get(M.ComponentConsumption, enc.id).qty == 3
    assert not R.undo(db, run)["refused"]
    R.undo(db, run, dry_run=False)
    assert db.get(M.ComponentConsumption, enc.id).qty == 5


def test_a_draw_raised_after_the_return_stops_the_undo(db, w, monkeypatch):
    """The dry round (decision 0075): the returned units are taken by RAISING
    an older draw of another batch, not by a new row; the stored floor sees it."""
    from app.routers import run_costs as rc

    run, _devices = _old(db, w, ["2025-03-01"] * 3, enc=5)
    other = M.ProductionRun(project_id=w["project"].id, label="TB-raise", run_date="2025-02-01",
                            status="completed", qty=1)
    db.add(other)
    db.flush()
    db.add(M.ComponentConsumption(run_id=other.id, component_id=w["enc"].id, mpn="", lcsc="", qty=95,
                                  unit_cost_usd=2.0, basis="bom", consumed_at="2025-02-01"))
    db.flush()
    R.rebuild(db, run, version_id=w["v"].id, dry_run=False, settle=[{"step": "enclosure", "how": "return"}])
    rc.set_used_qty(other.id, rc.ConsumptionIn(component_id=w["enc"].id, qty=97, consumed_at="2025-02-01"), db=db)
    refused = R.undo(db, run)["refused"]
    assert len(refused) == 1 and "short 2" in refused[0]


def test_a_dip_on_the_batch_s_own_date_hides_no_later_shortfall(db, w):
    """Loop-until-dry round 2 (decision 0075): the pool dips below zero on the
    batch's own date (a draw booked before its invoice); the returned units
    taken on a LATER date are still seen, day by day."""
    run, _devices = _old(db, w, ["2025-03-01"] * 3, enc=5)
    early = M.ProductionRun(project_id=w["project"].id, label="TB-dip", run_date="2025-03-01",
                            status="completed", qty=1)
    db.add(early)
    db.flush()
    db.add(M.ComponentConsumption(run_id=early.id, component_id=w["enc"].id, mpn="", lcsc="", qty=100,
                                  unit_cost_usd=2.0, basis="bom", consumed_at="2025-03-01"))
    doc = M.RunCostDocument(project_id=w["project"].id, doc_type="invoice", supplier="T", doc_number="DIP-1",
                            doc_date="2025-03-05", currency="USD", total_amount=200.0)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=w["enc"].id, mpn="", lcsc="",
                         qty=100, unit_price=2.0, position=0))
    db.flush()
    R.rebuild(db, run, version_id=w["v"].id, dry_run=False, settle=[{"step": "enclosure", "how": "return"}])
    later = M.ProductionRun(project_id=w["project"].id, label="TB-later", run_date="2025-04-01",
                            status="completed", qty=1)
    db.add(later)
    db.flush()
    pool_now = ra.pool_state(db)
    held = next(v["qty"] for v in pool_now.values() if v.get("component_id") == w["enc"].id)
    db.add(M.ComponentConsumption(run_id=later.id, component_id=w["enc"].id, mpn="", lcsc="", qty=held,
                                  unit_cost_usd=2.0, basis="bom", consumed_at="2025-04-01"))
    db.flush()
    refused = R.undo(db, run)["refused"]
    assert refused and "drawn again since" in refused[0]


def test_the_undo_refuses_while_a_lot_it_gave_back_is_bound_again(db, w, monkeypatch):
    """Loop-until-dry round 3 (decisions 0073, 0075): the returned units sit
    in the oldest lot, a later draw binds them, and a newer lot keeps the
    pool above zero. The undo would bind the old lot twice."""
    run, _devices = _old(db, w, ["2025-03-01"] * 3, enc=5)
    enc = ra.live_consumption(db, run_id=run.id).filter(M.ComponentConsumption.component_id == w["enc"].id).one()
    other = M.ProductionRun(project_id=w["project"].id, label="TB-lots", run_date="2025-02-01",
                            status="completed", qty=1)
    db.add(other)
    db.flush()
    first = M.ComponentConsumption(run_id=other.id, component_id=w["enc"].id, mpn="", lcsc="", qty=95,
                                   unit_cost_usd=2.0, basis="bom", consumed_at="2025-02-01")
    db.add(first)
    db.flush()
    L.bind(db, first, L.FifoPicker(db).pick(w["enc"].id, "", "", 95, "2025-02-01"))
    L.bind(db, enc, L.FifoPicker(db).pick(w["enc"].id, "", "", 5, "2025-03-01"))
    doc = M.RunCostDocument(project_id=w["project"].id, doc_type="invoice", supplier="T", doc_number="LOT-2",
                            doc_date="2025-03-15", currency="USD", total_amount=150.0)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=w["enc"].id, mpn="", lcsc="",
                         qty=50, unit_price=3.0, position=0))
    db.flush()
    monkeypatch.setattr(settings, "lot_pricing", True)
    R.rebuild(db, run, version_id=w["v"].id, dry_run=False, settle=[{"step": "enclosure", "how": "return"}])
    later = M.ProductionRun(project_id=w["project"].id, label="TB-late", run_date="2025-04-01",
                            status="completed", qty=1)
    db.add(later)
    db.flush()
    late = M.ComponentConsumption(run_id=later.id, component_id=w["enc"].id, mpn="", lcsc="", qty=10,
                                  unit_cost_usd=2.0, basis="bom", consumed_at="2025-04-01")
    db.add(late)
    db.flush()
    L.bind(db, late, L.FifoPicker(db).pick(w["enc"].id, "", "", 10, "2025-04-01"))
    refused = R.undo(db, run)["refused"]
    assert len(refused) == 1 and "overdrawn by 2" in refused[0]
    with pytest.raises(HTTPException):
        R.undo(db, run, dry_run=False)
    assert db.get(M.ComponentConsumption, enc.id).qty == 3      # nothing was kept


def test_a_lot_overdrawn_before_the_rebuild_does_not_stop_the_undo(db, w, monkeypatch):
    """Loop-until-dry round 4 (decisions 0073, 0075): the oldest lot was cut
    below what its draws hold before the rebuild; the undo puts it back where
    it was, which is no reason to refuse."""
    run, _devices = _old(db, w, ["2025-03-01"] * 3, enc=5)
    enc = ra.live_consumption(db, run_id=run.id).filter(M.ComponentConsumption.component_id == w["enc"].id).one()
    other = M.ProductionRun(project_id=w["project"].id, label="TB-cut", run_date="2025-02-01",
                            status="completed", qty=1)
    db.add(other)
    db.flush()
    first = M.ComponentConsumption(run_id=other.id, component_id=w["enc"].id, mpn="", lcsc="", qty=95,
                                   unit_cost_usd=2.0, basis="bom", consumed_at="2025-02-01")
    db.add(first)
    db.flush()
    L.bind(db, first, L.FifoPicker(db).pick(w["enc"].id, "", "", 95, "2025-02-01"))
    L.bind(db, enc, L.FifoPicker(db).pick(w["enc"].id, "", "", 5, "2025-03-01"))
    doc = M.RunCostDocument(project_id=w["project"].id, doc_type="invoice", supplier="T", doc_number="LOT-3",
                            doc_date="2025-03-15", currency="USD", total_amount=150.0)
    db.add(doc)
    db.flush()
    db.add(M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=w["enc"].id, mpn="", lcsc="",
                         qty=50, unit_price=3.0, position=0))
    old_lot = db.query(M.RunCostLine).filter(M.RunCostLine.component_id == w["enc"].id,
                                             M.RunCostLine.qty == 100).one()
    old_lot.qty = 98                                             # the lot holds 2 fewer than its draws
    db.flush()
    monkeypatch.setattr(settings, "lot_pricing", True)
    R.rebuild(db, run, version_id=w["v"].id, dry_run=False, settle=[{"step": "enclosure", "how": "return"}])
    assert L.lot_state(db)["lots"][f"L{old_lot.id}"]["qty_remaining"] == pytest.approx(0)
    assert not R.undo(db, run)["refused"]
    R.undo(db, run, dry_run=False)
    assert L.lot_state(db)["lots"][f"L{old_lot.id}"]["qty_remaining"] == pytest.approx(-2)


def test_a_lot_the_return_left_alone_keeps_the_undo_s_own_floor(db, w, monkeypatch):
    """Loop-until-dry round 5 (decisions 0073, 0075): the batch's draw spans
    two lots and the return gives back only the newer one's units. A cut of
    the older lot's purchase since is no reason to refuse the undo."""
    old_lot = db.query(M.RunCostLine).filter(M.RunCostLine.component_id == w["enc"].id,
                                             M.RunCostLine.qty == 100).one()
    doc = M.RunCostDocument(project_id=w["project"].id, doc_type="invoice", supplier="T", doc_number="LOT-4",
                            doc_date="2025-02-15", currency="USD", total_amount=150.0)
    db.add(doc)
    db.flush()
    new_lot = M.RunCostLine(document_id=doc.id, plan_key="parts:pool", component_id=w["enc"].id, mpn="", lcsc="",
                            qty=50, unit_price=3.0, position=0)
    db.add(new_lot)
    other = M.ProductionRun(project_id=w["project"].id, label="TB-span", run_date="2025-02-01",
                            status="completed", qty=1)
    db.add(other)
    db.flush()
    first = M.ComponentConsumption(run_id=other.id, component_id=w["enc"].id, mpn="", lcsc="", qty=96,
                                   unit_cost_usd=2.0, basis="bom", consumed_at="2025-02-01")
    db.add(first)
    db.flush()
    L.bind(db, first, L.FifoPicker(db).pick(w["enc"].id, "", "", 96, "2025-02-01"))
    run, _devices = _old(db, w, ["2025-03-01", "2025-03-01", "2025-03-02"], ant=4, enc=6)
    for c in ra.live_consumption(db, run_id=run.id).all():
        if c.component_id in (w["ant"].id, w["enc"].id):
            L.bind(db, c, L.FifoPicker(db).pick(c.component_id, "", "", c.qty, "2025-03-01"))
    monkeypatch.setattr(settings, "lot_pricing", True)
    plan = R.rebuild(db, run, version_id=w["v"].id, dry_run=False,
                     spares=[{"qty": 1, "done": ["antenna", "enclosure"]}],
                     settle=[{"step": "enclosure", "how": "return"}])
    assert f"L{new_lot.id}" in plan["returned_lots"] and f"L{old_lot.id}" not in plan["returned_lots"]
    old_lot.qty = 97                                             # cut since: the old lot is 3 short
    db.flush()
    assert not R.undo(db, run)["refused"]


@pytest.mark.parametrize("unlink", [False, True])
def test_a_whole_step_link_between_the_rebuild_and_an_append_is_undone_too(db, w, unlink):
    """Loop-until-dry round 6 (decisions 0074, 0075): a whole-step link made
    after the rebuild and before an append, which linked the late device's
    click. "Undo rebuild" undoes newest first, the append before the link,
    and a link an unlink took away is taken back too."""
    from app.routers import process as pr

    b, _devices = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, costs={"final:device": ["program"]}, dry_run=False)
    freight = (db.query(M.RunCostLine).join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
               .filter(M.RunCostDocument.run_id == b.id, M.RunCostLine.plan_key == "logistics:inbound").one())
    pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], step_keys=["carton"], dry_run=False), db=db)
    w["n"][0] += 1
    late = M.DeviceUnit(project_id=w["project"].id, serial=f"RBLATE{w['n'][0]:06d}", mac="00:00:00:rb:fe:01",
                        tasmota_id=f"dongle_RBLATE{w['n'][0]:06d}")
    db.add(late)
    db.flush()
    osvc.mark_produced(db, late, b.id, at=_at("2025-03-04"), actor="test")
    db.add(M.ProgrammingRun(device_unit_id=late.id, production_run_id=b.id, status="pass",
                            deployment_version_id=w["flash_v"][0].id, started_at=_at("2025-03-04", 10)))
    db.flush()
    R.rebuild(db, b, append=True, dry_run=False,
              settle=[{"step": s, "how": "draw"} for s in ("antenna", "enclosure", "carton")])
    if unlink:
        pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], unlink=True, dry_run=False), db=db)
    assert not R.undo(db, b)["refused"]
    R.undo(db, b, dry_run=False)
    assert db.query(M.StepRun).filter_by(run_id=b.id).count() == 0
    assert db.query(M.CostLineStepKey).filter_by(line_id=freight.id).count() == 0


# ------------------------------------------------ loop-until-dry round 7

def test_a_unit_the_rebuild_left_active_finished_and_shipped_does_not_stop_the_undo(db, w):
    """The rebuild left the unit active; the bench and the batch screen
    finished it and it shipped. Its twin goes with the rebuild."""
    from app.routers import process as pr

    b, (_d0, d1) = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, active={"device_ids": [d1.id]}, dry_run=False)
    T.record_test(db, d1, deployment_id=w["test"].id)
    T.record_marking(db, d1, laser=True, label=True, deployment_id=w["mark"].id)
    pr.craft_finish(b.id, pr.FinishIn(device_ids=[d1.id], chosen="list", dry_run=False), db=db)
    assert _twin(db, d1).status == "finished"
    osvc.record_event(db, db.get(M.DeviceUnit, d1.id), "shipped", actor="test")
    db.flush()
    assert not R.undo(db, b)["refused"]
    R.undo(db, b, dry_run=False)
    assert db.query(M.Twin).filter_by(origin_run_id=b.id).count() == 0


def test_the_undo_takes_back_the_keys_a_split_copied_from_the_rebuild(db, w):
    """A position the rebuild linked to whole steps was split into shares of
    the same batch: the split's copies go with the rebuild, the split stays."""
    from app.routers import run_costs as rc

    b, _devices = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, costs={"final:device": ["program", "carton"]}, dry_run=False)
    fee = (db.query(M.RunCostLine).join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
           .filter(M.RunCostDocument.run_id == b.id, M.RunCostLine.plan_key == "final:device").one())
    rc.split_line_core(fee.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=12, plan_key="final:device", run_id=b.id),
        rc.ChildIn(label="b", amount=8, plan_key="final:device", run_id=b.id)]), db)
    kids = [li.id for li in db.query(M.RunCostLine).filter_by(parent_line_id=fee.id)]
    assert db.query(M.CostLineStepKey).filter(M.CostLineStepKey.line_id.in_(kids)).count() == 4
    assert not R.undo(db, b)["refused"]
    R.undo(db, b, dry_run=False)
    assert db.query(M.CostLineStepKey).filter_by(run_id=b.id).count() == 0
    assert db.query(M.RunCostLine).filter(M.RunCostLine.id.in_(kids), M.RunCostLine.voided_at.is_(None)).count() == 2


def test_the_undo_takes_back_a_whole_step_link_that_waits_for_its_first_click(db, w):
    """A link made since on a step with no click yet: the undo unpins the
    batch, so the link goes too."""
    from app.routers import process as pr

    b, _devices = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, costs={"final:device": ["program"]}, dry_run=False)
    freight = (db.query(M.RunCostLine).join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
               .filter(M.RunCostDocument.run_id == b.id, M.RunCostLine.plan_key == "logistics:inbound").one())
    pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], step_keys=["leaflet"], dry_run=False), db=db)
    plan = R.undo(db, b)
    assert not plan["refused"] and any(x.get("kind") == "journal" for x in plan["takes_back"])
    R.undo(db, b, dry_run=False)
    assert db.query(M.CostLineStepKey).filter_by(run_id=b.id).count() == 0
    assert db.get(M.ProductionRun, b.id).process_version_id is None


# ------------------------------------------------ loop-until-dry round 8

def _line_of(db, b, key):
    return (db.query(M.RunCostLine).join(M.RunCostDocument, M.RunCostDocument.id == M.RunCostLine.document_id)
            .filter(M.RunCostDocument.run_id == b.id, M.RunCostLine.plan_key == key,
                    M.RunCostLine.parent_line_id.is_(None)).one())


def _name_from_another_pile(db, w, b):
    """A device programmed under batch `b` from another batch's pile: its
    programming click is outside any rebuild of `b`."""
    from app.routers import process as pr

    pile_run = M.ProductionRun(project_id=w["project"].id, label=f"TB-pile{w['n'][0]}", run_date="2025-06-01",
                               status="in_progress", process_version_id=w["v"].id, qty=1)
    db.add(pile_run)
    db.flush()
    pr.craft_receive(pile_run.id, pr.ReceiveIn(qty=1, made_at="2025-06-01", dry_run=False), db=db)
    pile = db.query(M.Twin).filter_by(run_id=pile_run.id).one()
    pr.craft_step(pile_run.id, pr.StepIn(step_key="antenna", stack=T.stack_id(pile_run.id, pile.stack_key), qty=1,
                                         chosen="stack", made_at="2025-06-01", dry_run=False), db=db)
    pr.set_bench_stack(b.id, pr.BenchStackIn(stack=T.stack_id(pile_run.id, pile.stack_key)), db=db)
    w["n"][0] += 1
    d = M.DeviceUnit(project_id=w["project"].id, serial=f"RBLIVE{w['n'][0]:06d}",
                     mac=f"00:00:00:rf:fe:{w['n'][0] % 256:02x}")
    db.add(d)
    db.flush()
    T.name_at_bench(db, d, osvc.mark_produced(db, d, b.id, at=_at("2025-06-02"), actor="test"), b)
    return pile


def test_the_undo_takes_back_a_split_child_s_link_to_a_click_named_later(db, w):
    """The split's children carry the rebuild's whole-step link; a twin named
    at the bench later is linked through them. The undo takes those links
    back with the rebuild's own."""
    from app.routers import run_costs as rc

    b, _devices = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, costs={"final:device": ["program"]}, dry_run=False)
    fd = _line_of(db, b, "final:device")
    rc.split_line_core(fd.id, rc.SplitIn(children=[
        rc.ChildIn(label="a", amount=12, plan_key="final:device", run_id=b.id),
        rc.ChildIn(label="b", amount=8, plan_key="final:device", run_id=b.id)]), db)
    _name_from_another_pile(db, w, b)
    lines = [fd.id] + [li.id for li in db.query(M.RunCostLine).filter_by(parent_line_id=fd.id)]
    assert db.query(M.CostLineStep).filter(M.CostLineStep.line_id.in_(lines)).count() > 0
    assert not R.undo(db, b)["refused"]
    R.undo(db, b, dry_run=False)
    assert db.query(M.CostLineStep).filter(M.CostLineStep.line_id.in_(lines)).count() == 0


@pytest.mark.parametrize("link_first", [False, True])
def test_a_cost_link_on_a_bench_click_is_undone_with_it(db, w, link_first):
    """A whole-step link made after (or before) a bench test on a rebuilt
    twin: the undo reverses the link's write, whatever the order."""
    from app.routers import process as pr

    b, (_d0, d1) = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, active={"device_ids": [d1.id]}, dry_run=False)
    freight = _line_of(db, b, "logistics:inbound")
    if link_first:
        pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], step_keys=["test"], dry_run=False), db=db)
    T.record_test(db, d1, deployment_id=w["test"].id)
    if not link_first:
        pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], step_keys=["test"], dry_run=False), db=db)
    assert not R.undo(db, b)["refused"]
    R.undo(db, b, dry_run=False)
    assert db.query(M.CostLineStepKey).filter_by(run_id=b.id).count() == 0


def test_a_link_whose_unlink_was_undone_is_taken_back_by_its_own_write(db, w):
    from app.routers import ledger as lg
    from app.routers import process as pr

    b, _devices = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, costs={"final:device": ["program"]}, dry_run=False)
    freight = _line_of(db, b, "logistics:inbound")
    link = pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], step_keys=["leaflet"], dry_run=False), db=db)
    u = pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], unlink=True, dry_run=False), db=db)
    lg.reverse_batch(u["batch_id"], dry_run=False, db=db)
    plan = R.undo(db, b)
    assert not plan["refused"] and any(x.get("batch_id") == link["batch_id"] for x in plan["takes_back"]), plan
    R.undo(db, b, dry_run=False)
    assert db.query(M.CostLineStepKey).filter_by(run_id=b.id).count() == 0


# ------------------------------------------------ loop-until-dry round 9

@pytest.mark.parametrize("then", ["unlink", "unlink_undone", "relink"])
def test_a_link_the_rebuild_s_key_made_outside_it_goes_whatever_the_person_did_since(db, w, then):
    """The rebuild's whole-step link paid for a click on another batch's
    pile; the person then unlinked (and undid it on the Write log) or
    relinked the position. The undo takes the link back after the reversal
    of the unlink has put it back."""
    from app.routers import ledger as lg
    from app.routers import process as pr

    b, _devices = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, costs={"final:device": ["program"]}, dry_run=False)
    fd = _line_of(db, b, "final:device")
    _name_from_another_pile(db, w, b)
    if then == "relink":
        pr.craft_costs(b.id, pr.CostsIn(line_ids=[fd.id], step_keys=["carton"], dry_run=False), db=db)
    else:
        u = pr.craft_costs(b.id, pr.CostsIn(line_ids=[fd.id], unlink=True, dry_run=False), db=db)
        if then == "unlink_undone":
            lg.reverse_batch(u["batch_id"], dry_run=False, db=db)
    dry = R.undo(db, b)
    assert not dry["refused"], dry["refused"]
    real = R.undo(db, b, dry_run=False)
    assert [x.get("kind") for x in real["takes_back"]] == [x.get("kind") for x in dry["takes_back"]]
    assert db.query(M.CostLineStep).filter_by(line_id=fd.id).count() == 0
    assert db.query(M.CostLineStepKey).filter_by(run_id=b.id).count() == 0


# ------------------------------------------------ loop-until-dry round 10

@pytest.mark.parametrize("unlink_undone", [False, True])
def test_a_person_s_link_undone_and_put_back_on_the_write_log_stays_with_the_undo(db, w, unlink_undone):
    """The person linked freight to the test step and to a click on another
    batch's pile, and the bench tested a rebuilt unit. An Unlink undone on
    the Write log must leave the same result as no Unlink at all: the
    person's link to the pile click and the test key stay, the bench test
    goes with the rebuild."""
    from app.routers import ledger as lg
    from app.routers import process as pr

    b, (_d0, d1) = _old(db, w, ["2025-03-01", "2025-03-02"])
    R.rebuild(db, b, version_id=w["v"].id, active={"device_ids": [d1.id]}, dry_run=False)
    pile = _name_from_another_pile(db, w, b)
    click = (db.query(M.StepRun).join(M.TwinStep, M.TwinStep.step_run_id == M.StepRun.id)
             .filter(M.TwinStep.twin_id == pile.id, M.StepRun.run_id == b.id).one())
    freight = _line_of(db, b, "logistics:inbound")
    pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], step_keys=["test"], step_run_ids=[click.id],
                                    dry_run=False), db=db)
    T.record_test(db, d1, deployment_id=w["test"].id)
    if unlink_undone:
        u = pr.craft_costs(b.id, pr.CostsIn(line_ids=[freight.id], unlink=True, dry_run=False), db=db)
        lg.reverse_batch(u["batch_id"], dry_run=False, db=db)
    dry = R.undo(db, b)
    assert not dry["refused"], dry["refused"]
    R.undo(db, b, dry_run=False)
    assert [x.step_run_id for x in db.query(M.CostLineStep).filter_by(line_id=freight.id)] == [click.id]
    assert [k.step_key for k in db.query(M.CostLineStepKey).filter_by(line_id=freight.id)] == ["test"]
