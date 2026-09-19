"""Give the prototype-era dongles found on the MQTT broker their identity.

Source: the broker's own `tasmota/discovery` announcements, cross-checked
against `device_units` on 2026-09-19.

The prototypes were already reconciled by
`rebuild-dongle-device-history.py` (decision 0036): 45 `PROTO-xxxx` rows,
35 of them shipped against the two prototype order lines, 10 unsold. Those
rows carry NO MAC because no records were kept at the time. The broker has
since produced 14 devices that are prototype-era and match no device unit,
so this script fills the identity into rows that already exist. It creates
no device and moves no count.

It also creates the two prototype COST POOLS. The prototype boards were paid
for and no production run ever held that money, so `PROTO-0001..0035` point at
no batch. One run per prototype order gives those costs a denominator without
inventing a single device.

ONE-TIME and not idempotent: a second run finds the MACs already taken and
fails its own assertions.

Run it through STDIN, never as a file — `api/CLAUDE.md` explains why a file
inside the container imports a stale copy of `app`:

    docker compose exec -T api python - < scripts/identify-prototype-dongles.py
    docker compose exec -T -e REHEARSE=1 api python - < scripts/…   # write, verify, roll back
    docker compose exec -T -e APPLY=1 api python - < scripts/…      # commit
"""
import os

from app.db import SessionLocal
from app import models as M
from sqlalchemy import select

APPLY = os.environ.get("APPLY") == "1"
REHEARSE = os.environ.get("REHEARSE") == "1"
WRITE = APPLY or REHEARSE
DONGLE = 2
ACTOR = "prototype-identification-2026-09-19"

# --- the facts ------------------------------------------------------------

# The two prototype orders. `line` is the sales_order_lines id the PROTO rows
# were already shipped against; the run created here is the COST side of the
# same event, never a second delivery.
POOLS = [
    dict(key="A", label="Prototypes 1 — PROFORMA 1/11/2023", qty=15,
         run_date="2023-11-30", line=15, serials=(1, 15)),
    dict(key="B", label="Prototypes 2 — FV 01/02/2024", qty=20,
         run_date="2024-02-16", line=16, serials=(16, 35)),
]

# Broker devices whose firmware predates every recorded batch (Tasmota
# 13.3.0.2, against a 13.4.0 minimum across all 12 runs) and whose MAC has no
# neighbour among recorded units at any distance. hw_model from discovery.
IDENTIFY = {
    # 9 x CE_Dongle_v2 on Tasmota 13.3.0.2 -> the first prototype order
    "A": [
        ("fc:b4:67:86:a4:38", "dongle_86A438"),
        ("fc:b4:67:86:b7:34", "dongle_86B734"),
        ("fc:b4:67:87:2a:00", "dongle_872A00"),
        ("fc:b4:67:87:5c:28", "dongle_875C28"),
        ("fc:b4:67:87:78:b0", "dongle_8778B0"),
        ("fc:b4:67:87:9d:f4", "dongle_879DF4"),
        ("fc:b4:67:87:da:18", "dongle_87DA18"),
        ("fc:b4:67:88:0d:bc", "dongle_880DBC"),
        ("fc:b4:67:88:56:b8", "dongle_8856B8"),
    ],
    # 5 x CE_Dongle_v1 — the earlier build target, 0 linked units anywhere
    "B": [
        ("08:f9:e0:9e:f6:34", "dongle_9EF634"),
        ("08:f9:e0:9e:f6:b8", "dongle_9EF6B8"),
        ("08:f9:e0:9e:f6:d4", "dongle_9EF6D4"),
        ("08:f9:e0:9e:f7:10", "dongle_9EF710"),
        ("08:f9:e0:9e:f9:74", "dongle_9EF974"),
    ],
}


def proto(db, n):
    u = db.scalar(select(M.DeviceUnit).where(
        M.DeviceUnit.project_id == DONGLE, M.DeviceUnit.serial == f"PROTO-{n:04d}"))
    assert u is not None, f"PROTO-{n:04d} missing — is this the right database?"
    return u


def main():
    db = SessionLocal()
    try:
        # --- preconditions ------------------------------------------------
        for mac, topic in [x for v in IDENTIFY.values() for x in v]:
            clash = db.scalar(select(M.DeviceUnit).where(M.DeviceUnit.mac == mac))
            assert clash is None, f"{mac} already on device {clash.id} — stop"
            p = db.scalar(select(M.DevicePresence).where(M.DevicePresence.topic == topic))
            assert p is not None, f"no presence row for {topic}"
            assert p.device_unit_id is None, f"{topic} already linked to {p.device_unit_id}"
            assert (p.reported_mac or "").lower() == mac, (
                f"{topic} reports {p.reported_mac!r}, expected {mac}")

        for pool in POOLS:
            lo, hi = pool["serials"]
            for n in range(lo, hi + 1):
                u = proto(db, n)
                assert not u.mac, f"PROTO-{n:04d} already has MAC {u.mac}"
                assert u.production_run_id is None, (
                    f"PROTO-{n:04d} already in run {u.production_run_id}")

        print(f"preconditions OK  ({sum(len(v) for v in IDENTIFY.values())} devices, "
              f"{sum(p['qty'] for p in POOLS)} prototype rows)")
        if not WRITE:
            for pool in POOLS:
                lo, hi = pool["serials"]
                print(f"  would create run {pool['label']!r} qty={pool['qty']} "
                      f"and point PROTO-{lo:04d}..{hi:04d} at it")
                for i, (mac, topic) in enumerate(IDENTIFY[pool["key"]]):
                    print(f"     PROTO-{lo + i:04d}  <- {mac}  {topic}")
            print("\ndry run — nothing written. REHEARSE=1 to exercise, APPLY=1 to commit.")
            return

        # --- write --------------------------------------------------------
        runs = {}
        for pool in POOLS:
            r = M.ProductionRun(
                project_id=DONGLE, label=pool["label"], qty=pool["qty"],
                status="completed", run_date=pool["run_date"], board="CE_Dongle_V2",
                notes=("Prototype cost pool. The devices were already recorded and "
                       "shipped by the 2026-09-18 reconciliation (decision 0036); "
                       "this run holds the money, not a second delivery."))
            db.add(r)
            db.flush()
            runs[pool["key"]] = r
            print(f"run {r.id}: {r.label} (qty {r.qty})")

        filled = linked = pooled = 0
        for pool in POOLS:
            lo, hi = pool["serials"]
            r = runs[pool["key"]]
            for n in range(lo, hi + 1):
                proto(db, n).production_run_id = r.id
                pooled += 1
            for i, (mac, topic) in enumerate(IDENTIFY[pool["key"]]):
                u = proto(db, lo + i)
                u.mac = mac
                u.tasmota_id = topic
                db.flush()
                p = db.scalar(select(M.DevicePresence).where(M.DevicePresence.topic == topic))
                p.device_unit_id = u.id
                db.add(M.AuditLog(
                    action="prototype_identified", entity_type="device_unit",
                    entity_id=str(u.id), actor=ACTOR,
                    details={"serial": u.serial, "mac": mac, "topic": topic,
                            "source": "tasmota/discovery.mac", "run_id": r.id}))
                filled += 1
                linked += 1
        print(f"filled {filled} identities, linked {linked} presence rows, "
              f"{pooled} rows into cost pools")

        # --- verify against the platform's own read paths -----------------
        db.flush()
        from app.services import orders as osvc

        counts = osvc._line_counts(db, [p["line"] for p in POOLS])
        for pool in POOLS:
            c = counts[pool["line"]]
            got = c["shipped"] + c["unserialized"]
            assert got == pool["qty"], (
                f"line {pool['line']}: delivered {got}, expected {pool['qty']}")
            print(f"line {pool['line']}: delivered {got}/{pool['qty']} — unchanged")

        unlinked = db.query(M.DevicePresence).filter(
            M.DevicePresence.device_unit_id.is_(None)).count()
        print(f"presence rows still unlinked: {unlinked} (was 69)")
        assert unlinked == 69 - linked, f"expected {69 - linked}, got {unlinked}"

        if REHEARSE:
            db.rollback()
            print("\nREHEARSE — rolled back, nothing kept.")
        else:
            db.commit()
            print("\nAPPLIED.")
    finally:
        db.close()


main()
