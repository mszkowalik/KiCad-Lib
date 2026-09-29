"""One unit, several broker topics — and a replay is not the device speaking.

Decision record:
docs/decisions/0056-a-unit-owns-every-topic-it-was-given.md.

Both facts were measured on production on 2026-09-29, not assumed:

* a bench reflash renamed 78 units (`dongle_42AD24` -> `dongle_F8B3B742AD24`),
  and the broker keeps each old topic's retained messages, so 27 old names sat
  in the unlinked list as if they were unknown devices;
* one reconnect on 2026-09-28 stamped `last_seen_at` on every offline topic in
  the same minute, because a retained replay moved it.

Run from `api/`, with the dev database up:
    python -m pytest tests/fleet -q
"""
import pathlib
import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest
from sqlalchemy.orm import Session

from app import models as M
from app.db import engine
from app.routers.projects import project_devices
from app.services import mqtt_monitor as mm
from app.services import orders as svc
from app.services.flasher import bench_checks

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def db():
    """One transaction, never committed: the dev database is left untouched."""
    conn = engine.connect()
    trans = conn.begin()
    s = Session(bind=conn)
    mm._pending.clear()
    try:
        yield s
    finally:
        mm._pending.clear()
        s.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def project(db: Session):
    p = M.Project(name="test-presence-topics", git_url="https://example.invalid/pt.git")
    db.add(p)
    db.flush()
    return p


def unit(db, project, name, mac=None, accounts=()):
    u = M.DeviceUnit(project_id=project.id, tasmota_id=name, serial=name.split("_", 1)[1],
                     mac=mac, first_seen=T0)
    db.add(u)
    db.flush()
    for i, acct in enumerate(accounts):
        db.add(M.DeviceConfigValue(device_unit_id=u.id, key="mqtt_user", value=acct,
                                   current=(i == len(accounts) - 1)))
    db.flush()
    return u


def topic(db, name, *, unit_id=None, online=None, seen=None, reported_mac=""):
    p = M.DevicePresence(topic=name, device_unit_id=unit_id, lwt="", online=online,
                         last_seen_at=seen, first_seen_at=T0, reported_mac=reported_mac,
                         reported_mac_field="", hw_model="", tasmota_version="",
                         ip_address="", inverter="", inverter_sn="", dongle_version="",
                         updated_at=T0)
    db.add(p)
    db.flush()
    return p


def orphans(db, *names):
    return [db.query(M.DevicePresence).filter_by(topic=n).one() for n in names]


# ------------------------------------------------------------ a replay is not a message

def test_a_retained_replay_keeps_the_state_and_leaves_the_clocks(db: Session):
    """The broker replays LWT on every reconnect; the device said nothing."""
    p = topic(db, "dongle_TPR001", online=True, seen=T0)
    p.last_offline_at = None
    mm._buffer("dongle_TPR001", mm._parse("LWT", b"Offline"), retained=True)
    mm._flush(db)
    db.refresh(p)
    assert p.online is False                       # the state is current
    assert p.last_seen_at == T0                    # the clock did not move
    assert p.last_offline_at is None


def test_a_live_message_moves_the_clocks(db: Session):
    p = topic(db, "dongle_TPR002", online=True, seen=T0)
    mm._buffer("dongle_TPR002", mm._parse("LWT", b"Offline"), retained=False)
    mm._flush(db)
    db.refresh(p)
    assert p.online is False
    assert p.last_seen_at > T0
    assert p.last_offline_at is not None


def test_a_replay_fills_a_first_learned_time_once_and_never_moves_it(db: Session):
    p = topic(db, "dongle_TPR003")
    payload = b'{"persist":{"monitoring":{"inverter":"DEYE_LP3"}}}'
    mm._buffer("dongle_TPR003", mm._parse("PERSIST_SAVE", payload), retained=True)
    mm._flush(db)
    db.refresh(p)
    first = p.persist_at
    assert first is not None and p.inverter == "DEYE_LP3" and p.last_seen_at is None
    mm._buffer("dongle_TPR003", mm._parse("PERSIST_SAVE", payload), retained=True)
    mm._flush(db)
    db.refresh(p)
    assert p.persist_at == first


# ------------------------------------------------------------ the link rules

def test_an_old_name_links_through_the_account_history(db: Session, project):
    u = unit(db, project, "dongle_F8B3B7TP0001", accounts=("dongle_TP0001", "dongle_F8B3B7TP0001"))
    old = topic(db, "dongle_TP0001")
    assert mm.link_candidates(db, [old])[old.id] == [("account", u.id)]
    mm.link_devices(db)
    db.refresh(old)
    assert old.device_unit_id == u.id
    db.refresh(u)
    assert u.tasmota_id == "dongle_F8B3B7TP0001"   # the programmed name never follows the broker


def test_the_devices_own_mac_links_it(db: Session, project):
    u = unit(db, project, "dongle_AAAAAA000001", mac="aa:aa:aa:00:00:01")
    old = topic(db, "dongle_000001", reported_mac="AA:AA:AA:00:00:01")
    assert mm.link_candidates(db, [old])[old.id] == [("device_mac", u.id)]


def test_a_twelve_hex_topic_links_by_the_mac_it_spells(db: Session, project):
    """Unit 81's case: programmed as dongle_9E4F38, seen as dongle_C82E189E4F38."""
    u = unit(db, project, "dongle_BB0002", mac="aa:bb:cc:bb:00:02")
    other = topic(db, "dongle_AABBCCBB0002")
    assert mm.link_candidates(db, [other])[other.id] == [("topic_mac", u.id)]


def test_rules_that_name_different_units_link_nothing(db: Session, project):
    a = unit(db, project, "dongle_AAAAAA000003", mac="aa:aa:aa:00:00:03")
    b = unit(db, project, "dongle_BBBBBB000003", accounts=("dongle_000003",))
    row = topic(db, "dongle_000003", reported_mac="aa:aa:aa:00:00:03")
    assert sorted(uid for _, uid in mm.link_candidates(db, orphans(db, "dongle_000003"))[row.id]) \
        == sorted([a.id, b.id])
    mm.link_devices(db)
    db.refresh(row)
    assert row.device_unit_id is None


def test_a_six_hex_suffix_alone_is_never_evidence(db: Session, project):
    """`8BD26C` ends two different devices' MACs on production.

    Asserts only about its OWN unit: the dev database is a production copy,
    and a real device may carry any 6-hex name."""
    u = unit(db, project, "dongle_CCCCCCFEED01", mac="cc:cc:cc:fe:ed:01")
    row = topic(db, "dongle_FEED01")
    assert u.id not in {uid for _, uid in mm.link_candidates(db, [row]).get(row.id, [])}
    mm.link_devices(db)
    db.refresh(row)
    assert row.device_unit_id != u.id


# ------------------------------------------------------------ one answer per unit

def test_an_online_topic_is_the_main_row(db: Session, project):
    u = unit(db, project, "dongle_F8B3B7TP0004")
    topic(db, "dongle_F8B3B7TP0004", unit_id=u.id, online=False, seen=T0)
    topic(db, "dongle_TP0004", unit_id=u.id, online=True, seen=T0 - timedelta(days=1))
    assert [r.topic for r in mm.presence_rows(db, u)] == ["dongle_TP0004", "dongle_F8B3B7TP0004"]


def test_with_nothing_live_the_programmed_name_is_the_main_row(db: Session, project):
    u = unit(db, project, "dongle_F8B3B7TP0005")
    topic(db, "dongle_TP0005", unit_id=u.id, online=False)
    topic(db, "dongle_F8B3B7TP0005", unit_id=u.id, online=False)
    assert mm.presence_rows(db, u)[0].topic == "dongle_F8B3B7TP0005"


def test_the_device_list_shows_a_unit_once_and_counts_it_once(db: Session, project):
    u = unit(db, project, "dongle_F8B3B7TP0006")
    topic(db, "dongle_F8B3B7TP0006", unit_id=u.id, online=False, seen=T0)
    topic(db, "dongle_TP0006", unit_id=u.id, online=True, seen=T0)
    out = project_devices(project.id, state="", condition="", run_id=None, presence="",
                          q="", limit=500, db=db)
    assert [i["id"] for i in out["items"]] == [u.id]
    assert out["items"][0]["presence"]["online"] is True
    assert out["summary"] == {"total": 1, "online": 1, "offline": 0, "unknown": 0}


def test_the_bench_warns_when_any_topic_of_the_unit_is_online(db: Session, project):
    u = unit(db, project, "dongle_F8B3B7TP0007", mac="f8:b3:b7:00:00:07")
    svc.record_event(db, u, "produced", at=T0)
    topic(db, "dongle_F8B3B7TP0007", unit_id=u.id, online=False)
    topic(db, "dongle_TP0007", unit_id=u.id, online=True, seen=T0)
    run = M.ProgrammingRun(status="running")
    db.add(run)
    db.flush()
    out = bench_checks.for_device(db, run, u, created=False, project_id=project.id)
    warn = [n for n in out if n["code"] == "online_elsewhere"]
    assert warn and "dongle_TP0007" in warn[0]["text"]


# ------------------------------------------------------------ the MAC backfill

def test_a_backfill_needs_every_topic_of_the_unit_to_agree(db: Session, project):
    u = unit(db, project, "dongle_DD0008")
    topic(db, "dongle_DD0008", unit_id=u.id, reported_mac="dd:dd:dd:dd:00:08")
    topic(db, "dongle_EEEEEEEE0008", unit_id=u.id)   # spells a different MAC
    mm.backfill_macs(db)
    db.refresh(u)
    assert u.mac is None
