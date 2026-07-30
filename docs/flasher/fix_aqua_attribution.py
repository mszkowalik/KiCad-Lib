#!/usr/bin/env python3
"""Re-attribute the Aqua production history to the Aqua project.

The import put every report under CE_Dongle_V2 because the report filenames
and the Tasmota topic are `dongle_*` for BOTH products — and the boot banner
says "Project dongle" on an Aqua too (verified: neither binary contains the
string "aqua"). Two signals do identify an Aqua unit:

  1. the test ran `CE_Aqua` (test.py's only real test — the CE_Dongle_V2
     method logs and returns), measuring 3 relays against Switch7/8/9 plus a
     DS18B20; 816 of 819 test reports are this, and 614 read a temperature;
  2. the gen-B config pushed the `CE_Aqua` GPIO template (122 reports), and
     the 2024-09-15 session configured 190 units of which 186 were Aqua-tested,
     so that whole session is Aqua.

718 distinct units. This script moves their devices, config runs and test runs
to project 3, mirroring each Dongle config version with an Aqua one that pins
the AQUA firmware. Idempotent: re-running finds nothing left to move.

Run inside the api container; expects /tmp/aqua_serials.txt.
"""
import sys
from pathlib import Path

from sqlalchemy import text

from app import models as M
from app.db import SessionLocal
from app.services.flasher import bundle

AQUA_PROJECT = 3
AQUA_FW = {  # dongle firmware build label -> the matching Aqua asset
    "13.4.0": 7,
    "14.2.0": 8,
}


def main() -> int:
    serials = {s.strip().upper() for s in Path("/tmp/aqua_serials.txt").read_text().split() if s.strip()}
    db = SessionLocal()
    print(f"Aqua serials to re-attribute: {len(serials)}")

    devices = db.query(M.DeviceUnit).filter(M.DeviceUnit.serial.in_(serials)).all()
    print(f"matched device rows: {len(devices)}")
    dev_ids = [d.id for d in devices]

    # ---- 1. the Aqua test deployment (the real relay + sensor procedure) ----
    sys.path.insert(0, "/tmp")
    import v2_procedures as V  # noqa: E402 — shipped alongside this script

    test_dep = (
        db.query(M.Deployment)
        .filter(M.Deployment.project_id == AQUA_PROJECT,
                M.Deployment.name == "Aqua_V2 test (retroactive)")
        .one_or_none()
    )
    if test_dep is None:
        test_dep = M.Deployment(
            project_id=AQUA_PROJECT, name="Aqua_V2 test (retroactive)", chip="esp32",
            description="The CE_Aqua functional test as it ran in production: relay matrix "
                        "against Switch7/8/9 plus DS18B20, with the test template applied and "
                        "the original restored. Flashes nothing.")
        db.add(test_dep)
        db.flush()
    test_ver = next((v for v in test_dep.versions if v.status == "published"), None)
    if test_ver is None:
        test_ver = M.DeploymentVersion(
            deployment_id=test_dep.id, version_no=1, status="published",
            created_by="retro-import", approved_by="retro-import",
            comment="RETRO: test.py::CE_Aqua — 816 runs, 2024-08-16..2026-07-08",
            transport_profile="uart_bridge", monitor_baud=115200,
            steps=V.test_aqua(), files_label="")
        db.add(test_ver)
        db.flush()
        bundle.stamp(db, test_ver)
        test_dep.current_version_id = test_ver.id
    print(f"Aqua test deployment {test_dep.id}, version {test_ver.id}")

    # ---- 2. mirror each Dongle config version with an Aqua one -------------
    cfg_dep = (
        db.query(M.Deployment)
        .filter(M.Deployment.project_id == AQUA_PROJECT,
                M.Deployment.name == "Aqua_V2 config (retroactive)")
        .one()
    )
    # Which Dongle config versions do the Aqua units' config runs sit on?
    rows = db.execute(text("""
        SELECT r.deployment_version_id AS ver, count(*) AS n
        FROM programming_runs r
        WHERE r.device_unit_id = ANY(:ids)
          AND r.results->>'retro_source' LIKE '%%_config.json'
        GROUP BY 1 ORDER BY 1
    """), {"ids": dev_ids}).fetchall()
    print("Aqua config runs currently on:", {r.ver: r.n for r in rows})

    mirror: dict[int, int] = {}
    next_no = max((v.version_no for v in cfg_dep.versions), default=0)
    for row in rows:
        src = db.get(M.DeploymentVersion, row.ver)
        if src.deployment_id == cfg_dep.id:
            mirror[src.id] = src.id  # already an Aqua version (the 122)
            continue
        # Reuse an equivalent Aqua version if a previous run made one.
        tag = f"mirrors Dongle config v{src.version_no}"
        existing = next((v for v in cfg_dep.versions if tag in (v.comment or "")), None)
        if existing is None:
            fw_label = next((k for k in AQUA_FW if k in (
                src.images[0].asset.build_label if src.images else "")), None)
            aqua_asset = AQUA_FW.get(fw_label)
            next_no += 1
            v = M.DeploymentVersion(
                deployment_id=cfg_dep.id,
                version_no=next_no,
                status="published", created_by="retro-import", approved_by="retro-import",
                comment=f"RETRO Aqua config, {tag} (same procedure and berryware, "
                        f"CE_AQUA firmware)",
                transport_profile=src.transport_profile, monitor_baud=src.monitor_baud,
                flash_config=src.flash_config, steps=src.steps,
                param_set_id=(db.query(M.ParamSet)
                              .filter(M.ParamSet.project_id == AQUA_PROJECT).first() or
                              type("x", (), {"id": None})).id,
                files_label=src.files_label)
            db.add(v)
            db.flush()
            if aqua_asset:
                db.add(M.DeploymentImage(deployment_version_id=v.id,
                                         firmware_asset_id=aqua_asset, address="0x0", position=0))
            # The berryware set is the same content; pin the Aqua project's own
            # file versions where they exist, else carry the dongle ones (same
            # bytes, and a run only records what was downloaded).
            for pos, link in enumerate(sorted(src.files, key=lambda f: f.position)):
                fname = link.file_version.file.filename
                sha = link.file_version.sha256
                own = (db.query(M.DeviceFileVersion)
                       .join(M.DeviceFile, M.DeviceFile.id == M.DeviceFileVersion.device_file_id)
                       .filter(M.DeviceFile.project_id == AQUA_PROJECT,
                               M.DeviceFile.filename == fname,
                               M.DeviceFileVersion.sha256 == sha)
                       .first())
                db.add(M.DeploymentFile(deployment_version_id=v.id,
                                        device_file_version_id=(own.id if own
                                                                else link.device_file_version_id),
                                        position=pos))
            db.flush()
            bundle.stamp(db, v)
            existing = v
            print(f"  created Aqua config v{v.version_no} (id {v.id}) {tag}, "
                  f"{len(v.images)} image(s), {len(v.files)} files")
        mirror[src.id] = existing.id
    db.flush()
    cfg_dep.current_version_id = db.execute(text(
        "SELECT id FROM deployment_versions WHERE deployment_id = :d AND status = 'published' "
        "ORDER BY version_no DESC LIMIT 1"), {"d": cfg_dep.id}).scalar()
    db.commit()

    # ---- 3. move the runs ---------------------------------------------------
    moved_cfg = 0
    for src_id, dst_id in mirror.items():
        if src_id == dst_id:
            continue
        res = db.execute(text("""
            UPDATE programming_runs SET deployment_version_id = :dst
            WHERE device_unit_id = ANY(:ids)
              AND deployment_version_id = :src
              AND results->>'retro_source' LIKE '%%_config.json'
        """), {"dst": dst_id, "src": src_id, "ids": dev_ids})
        moved_cfg += res.rowcount
    res = db.execute(text("""
        UPDATE programming_runs SET deployment_version_id = :dst
        WHERE results->>'retro_source' LIKE '%%_test.json'
          AND results->>'test_result' IS NOT NULL
    """), {"dst": test_ver.id})
    moved_test = res.rowcount
    # ---- 4. the devices belong to the Aqua project -------------------------
    res = db.execute(text("UPDATE device_units SET project_id = :p WHERE id = ANY(:ids) "
                          "AND project_id <> :p"), {"p": AQUA_PROJECT, "ids": dev_ids})
    moved_dev = res.rowcount
    # Fingerprints on the moved runs follow their new version.
    db.execute(text("""
        UPDATE programming_runs r
        SET firmware_fingerprint = v.firmware_fingerprint,
            files_fingerprint = v.files_fingerprint
        FROM deployment_versions v WHERE v.id = r.deployment_version_id
    """))
    db.commit()
    print(f"\nmoved: {moved_cfg} config runs, {moved_test} test runs, {moved_dev} devices")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
