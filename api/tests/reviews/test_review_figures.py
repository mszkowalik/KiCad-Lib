"""The review figures: each count has one definition, and the list it opens
holds the same rows.

An audit of production on 2026-11-07 found the same question answered with
different numbers on different screens:

- the project Review tab and the batch warning counted `unreviewed` and
  `failed` as "not verified" and left `partial` out (EVSE_20_CTRL: 41 against
  57 parts that were not checked);
- the review queue and the health panel counted components with no published
  version as review work (508 against the library's 503);
- the health panel's "failing" count added stored record answers that the
  list it opens did not show (`cmp.required_props` 13 against 10);
- the retired-skip chip summed the top 10 keys only.

The routes are called as plain functions on one transaction that is rolled
back, so nothing reaches the dev data.

Run from `api/`, with the dev database up:
    python -m pytest tests/reviews -q
"""
import json
import pathlib
import sys
import uuid
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers import reviews
from app.services import agent_tools


@pytest.fixture
def factory(monkeypatch):
    """Sessions on one transaction that is rolled back at the end. A commit is
    a savepoint, so an agent tool's own session sees what the test wrote."""
    conn = engine.connect()
    trans = conn.begin()

    def make():
        return Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)

    monkeypatch.setattr(agent_tools, "SessionLocal", make)
    try:
        yield make
    finally:
        trans.rollback()
        conn.close()


@pytest.fixture
def db(factory):
    s = factory()
    try:
        yield s
    finally:
        s.close()


def _row(name, review, signoff="signed", lifecycle="released"):
    return {"board": "B", "refs": name, "qty": 1, "value": "", "footprint": "", "lcsc": "",
            "mpn": "", "lib_version": "", "component_id": hash(name) % 100000,
            "component_name": name, "current_version_no": 1, "review_state": review,
            "review_blockers": [], "signoff_state": signoff, "lifecycle": lifecycle,
            "matched": True}


# ------------------------------------------------------------ finding 1
def test_a_partial_part_is_not_verified(db, monkeypatch):
    """Every state except `checked` is open work, the way the queue counts it."""
    rows = [_row("A", "checked"), _row("B", "partial"), _row("C", "failed"),
            _row("D", "unreviewed"), _row("E", "partial")]
    monkeypatch.setattr(reviews, "snapshot_review_rows", lambda db, snap: rows)

    out = reviews.snapshot_review_issues(db, SimpleNamespace(id=-1))

    assert out["not_verified"] == ["B", "C", "D", "E"]
    assert out["partial"] == ["B", "E"]
    assert out["clean"] is False


def test_only_partial_parts_still_make_the_snapshot_unclean(db, monkeypatch):
    rows = [_row("A", "checked"), _row("B", "partial")]
    monkeypatch.setattr(reviews, "snapshot_review_rows", lambda db, snap: rows)

    out = reviews.snapshot_review_issues(db, SimpleNamespace(id=-1))

    assert out["clean"] is False, "a part with open items read as verified"


# ------------------------------------------------------------ finding 4
@pytest.fixture
def versionless(db):
    """A component with no published version, like 78L12 on production."""
    comp = M.Component(name=f"TEST-NOVERSION-{uuid.uuid4().hex[:8]}")
    db.add(comp)
    db.commit()
    return comp


def test_the_queue_leaves_out_a_component_with_no_version(db, versionless):
    names = {r["name"] for r in reviews.review_queue(snapshot_id=None, db=db)["components"]}

    assert versionless.name not in names


def test_health_counts_the_published_library(db, versionless):
    published = db.query(M.Component).filter(M.Component.current_version_id.isnot(None)).count()

    out = reviews.review_health(db=db)["components"]

    assert out["total"] == published
    assert sum(out["review"].values()) == published
    assert sum(out["signoff"].values()) == published


def test_the_agent_lists_leave_out_a_component_with_no_version(db, versionless):
    published = db.query(M.Component).filter(M.Component.current_version_id.isnot(None)).count()
    reviews_out = json.loads(agent_tools.list_reviews.func(state=""))
    # The sign-off list is capped, so its COUNTS are what proves the point.
    signoffs_out = json.loads(agent_tools.list_signoffs.func(state=""))

    assert versionless.name not in {i["component"] for i in reviews_out["items"]}
    assert sum(reviews_out["counts"].values()) == published
    assert sum(signoffs_out["counts"].values()) == published


# ------------------------------------------------------------ finding 6
@pytest.fixture
def symbol_with_findings(db):
    """One symbol with a finding in every place the rules have to decide on."""
    tag = uuid.uuid4().hex[:8]
    sym = M.Symbol(name=f"TEST-FINDINGS-{tag}")
    db.add(sym)
    db.flush()
    ver = M.SymbolVersion(symbol_id=sym.id, version_no=1, source_text="(symbol)")
    db.add(ver)
    db.flush()
    sym.current_version_id = ver.id
    k = {n: f"test.{tag}.{n}" for n in ("machine", "warn", "history", "flag", "both", "excused")}
    db.add(M.Conformance(subject_kind="symbol", subject_version_id=ver.id, digest="test", items=[
        {"key": k["machine"], "result": "failed", "severity": "error"},
        {"key": k["warn"], "result": "failed", "severity": "warning"},
        {"key": k["both"], "result": "failed", "severity": "error"},
    ], excused=[{"key": k["excused"], "reason": "waived"}]))
    db.add(M.ReviewRecord(subject_kind="symbol", subject_id=sym.id, subject_version_id=ver.id,
                          actor_type="agent", created_by="test", items=[
        # a machine answer stored before decision 0017: history, not a finding
        {"key": k["history"], "result": "failed", "actor_type": "machine"},
        {"key": k["flag"], "result": "flagged", "actor_type": "agent", "note": "wrong"},
        {"key": k["both"], "result": "flagged", "actor_type": "agent", "note": "also"},
        {"key": k["excused"], "result": "flagged", "actor_type": "agent", "note": "waived"},
    ]))
    db.commit()
    return sym, k


def test_each_failing_count_is_the_length_of_the_list_it_opens(db, symbol_with_findings):
    sym, k = symbol_with_findings
    counts = {f["key"]: f["count"] for f in reviews.review_health(db=db)["failing_keys"]["symbol"]}

    for key in k.values():
        listed = reviews.failing_subjects("symbol", key, db=db)["subjects"]
        assert counts.get(key, 0) == len(listed), key
        assert len([s for s in listed if s["id"] == sym.id]) <= 1, f"{key}: a subject is listed twice"


def test_a_finding_is_what_the_state_counts(db, symbol_with_findings):
    sym, k = symbol_with_findings
    found = {key for key, rows in reviews.review_svc.failing_by_key(db, "symbol").items()
             if sym.id in rows}

    assert found == {k["machine"], k["warn"], k["flag"], k["both"]}
    assert k["history"] not in found, "a stored machine answer is history (decision 0017)"
    assert k["excused"] not in found, "an excused key is not a finding"
    counts = {f["key"]: f for f in reviews.review_health(db=db)["failing_keys"]["symbol"]}
    assert counts[k["warn"]]["warnings"] == 1


# ------------------------------------------------------------ finding 8
def test_the_retired_skip_total_counts_every_key(db):
    """The chip summed the top 10 keys; twelve fresh keys push some past it."""
    tag = uuid.uuid4().hex[:8]
    sym = M.Symbol(name=f"TEST-SKIPPED-{tag}")
    db.add(sym)
    db.flush()
    ver = M.SymbolVersion(symbol_id=sym.id, version_no=1, source_text="(symbol)")
    db.add(ver)
    db.flush()
    sym.current_version_id = ver.id
    keys = [f"test.{tag}.{i}" for i in range(12)]
    db.add(M.ReviewRecord(subject_kind="symbol", subject_id=sym.id, subject_version_id=ver.id,
                          actor_type="agent", created_by="test",
                          items=[{"key": k, "result": "skipped", "actor_type": "agent"} for k in keys]))
    db.commit()

    out = reviews.review_health(db=db)

    listed = {s["key"] for s in out["legacy_skipped_items"]}
    assert set(keys) <= listed, "a key with open answers is missing from the list"
    assert out["legacy_skipped_total"] == sum(s["count"] for s in out["legacy_skipped_items"])
