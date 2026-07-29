"""Make every deployment version usable, or remove it.

Three classes of defect, all from the first import pass:

1. EMPTY-STEP PLACEHOLDERS — the era versions created before the procedures
   were reverse-engineered. Superseded, zero runs → deleted.
2. "unmatched" BERRYWARE ERAS — 4 reports whose downloaded file sizes matched
   no release (they are truncated/partial downloads; the per-run sizes stay in
   each run's `results.downloaded`). The INTENDED deployment is the era whose
   date range contains the run, so the runs move there and the placeholder
   version goes.
3. AQUA WITH NO BERRYWARE — device files are project-scoped and the Aqua units
   live in their own project, so nothing was pinned. Their 2024-07 era is
   release-0.0.1, now imported into that project → pin it.
"""
from datetime import datetime, timezone
from app.db import SessionLocal
from app import models as M
from app.services.flasher import bundle, validate

db = SessionLocal()
deleted, moved, pinned = [], 0, []

def runs_of(v):
    return db.query(M.ProgrammingRun).filter(M.ProgrammingRun.deployment_version_id == v.id)

# --- 3. Aqua: pin the era's berryware (do this first, it makes v1 valid) ----
aqua_files = {}
for df in db.query(M.DeviceFile).filter(M.DeviceFile.project_id == 3):
    pub = [v for v in df.versions if v.status == "published"]
    if pub:
        aqua_files[df.filename] = pub[-1]
for dep in db.query(M.Deployment).filter(M.Deployment.project_id == 3):
    if "config" not in dep.name:
        continue
    for v in dep.versions:
        if v.files or not any(s.get("op") == "download_files" for s in (v.steps or [])):
            continue
        if not runs_of(v).count():
            continue  # an unused variant — handled as a placeholder below
        ordered = sorted(aqua_files.items(), key=lambda kv: (kv[0] == "autoexec.be", kv[0]))
        for pos, (name, fv) in enumerate(ordered):
            db.add(M.DeploymentFile(deployment_version_id=v.id,
                                    device_file_version_id=fv.id, position=pos))
        v.files_label = "release-0.0.1"
        db.flush()
        db.refresh(v)
        bundle.stamp(db, v)
        pinned.append(f"{dep.name} v{v.version_no} ({len(ordered)} files)")
db.commit()

# --- 2. unmatched eras: move the runs to the era that owns their date --------
def era_for(dep, when):
    """The sibling version whose runs bracket this date and which pins files."""
    best, best_gap = None, None
    for cand in dep.versions:
        if not cand.files:
            continue
        rows = runs_of(cand).all()
        stamps = [r.started_at for r in rows if r.started_at]
        if not stamps:
            continue
        lo, hi = min(stamps), max(stamps)
        if lo <= when <= hi:
            return cand
        gap = min(abs((when - lo).total_seconds()), abs((when - hi).total_seconds()))
        if best_gap is None or gap < best_gap:
            best, best_gap = cand, gap
    return best

for dep in db.query(M.Deployment).all():
    for v in list(dep.versions):
        if v.files or not any(s.get("op") == "download_files" for s in (v.steps or [])):
            continue
        rows = runs_of(v).all()
        if not rows:
            continue
        for r in rows:
            target = era_for(dep, r.started_at or datetime.now(timezone.utc))
            if target is None:
                continue
            r.deployment_version_id = target.id
            r.firmware_fingerprint = target.firmware_fingerprint
            r.files_fingerprint = target.files_fingerprint
            note = dict(r.results or {})
            note["retro_note"] = (
                "berryware set unidentifiable (partial download: the recorded file sizes match "
                f"no release); attributed to the era version v{target.version_no} by date")
            r.results = note
            moved += 1
db.commit()

# --- 1. anything with zero runs that cannot validate: remove ----------------
for dep in db.query(M.Deployment).all():
    for v in list(dep.versions):
        if runs_of(v).count():
            continue
        if validate.check(db, v)["ok"]:
            continue
        deleted.append(f"{dep.name} v{v.version_no} (id {v.id})")
        if dep.current_version_id == v.id:
            live = [x for x in dep.versions
                    if x.id != v.id and x.status == "published"]
            dep.current_version_id = live[-1].id if live else None
        for ch in db.query(M.DeploymentChannel).filter(
                M.DeploymentChannel.deployment_version_id == v.id):
            ch.deployment_version_id = None
        db.delete(v)
db.commit()

print(f"berryware pinned: {pinned}")
print(f"runs moved to their era version: {moved}")
print(f"unusable versions deleted: {len(deleted)}")
for d in deleted:
    print(f"   - {d}")

# --- report --------------------------------------------------------------
print("\nfinal audit:")
bad = 0
for dep in db.query(M.Deployment).order_by(M.Deployment.id):
    for v in sorted(dep.versions, key=lambda x: x.version_no):
        res = validate.check(db, v)
        runs = runs_of(v).count()
        if not res["ok"]:
            bad += 1
            print(f"  BAD {dep.name} v{v.version_no}: {res['errors'][:1]}")
    print(f"  {dep.name}: {len(dep.versions)} versions, "
          f"{sum(runs_of(v).count() for v in dep.versions)} runs")
print(f"unusable versions remaining: {bad}")
db.close()
