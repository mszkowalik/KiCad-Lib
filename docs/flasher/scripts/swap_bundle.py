"""Point every version that used the ambiguous "release" set at release-1.3.11,
then delete the old bundle.

The sets differ only in DEYE_LP3.json's formatting (identical parsed JSON), and
the user's call (2026-07-30) is to treat the served copy as 1.3.11. Each
affected version gets a note recording the substitution — the per-run logs keep
the byte sizes the devices actually reported, so nothing is lost.
"""
from app.db import SessionLocal
from app import models as M
from app.services.flasher import bundle

db = SessionLocal()
NOTE = (" [berryware set normalised to release-1.3.11: the served /berry/release copy "
        "differed only in DEYE_LP3.json formatting]")

for project_id in (2, 3):
    new = (
        db.query(M.BerryBundle)
        .filter(M.BerryBundle.project_id == project_id, M.BerryBundle.label == "release-1.3.11")
        .one_or_none()
    )
    old = (
        db.query(M.BerryBundle)
        .filter(M.BerryBundle.project_id == project_id,
                M.BerryBundle.label.like("release-1.3.11 (current)%"))
        .one_or_none()
    )
    if new is None or old is None:
        print(f"p{project_id}: nothing to do (new={bool(new)}, old={bool(old)})")
        continue
    new_ids = [link.device_file_version_id for link in sorted(new.files, key=lambda x: x.position)]
    users = db.query(M.DeploymentVersion).filter(M.DeploymentVersion.berry_bundle_id == old.id).all()
    for v in users:
        dep = db.get(M.Deployment, v.deployment_id)
        for link in list(v.files):
            db.delete(link)
        db.flush()
        for pos, fv_id in enumerate(new_ids):
            db.add(M.DeploymentFile(deployment_version_id=v.id,
                                    device_file_version_id=fv_id, position=pos))
        db.flush()
        db.refresh(v)
        bundle.stamp(db, v)
        bundle.link_bundle(db, v)
        if NOTE.strip("[] ") not in (v.comment or ""):
            v.comment = ((v.comment or "") + NOTE)[:500]
        print(f"p{project_id}: {dep.name} v{v.version_no} -> bundle '{v.files_label}'")
    db.flush()
    label = old.label
    db.delete(old)
    db.commit()
    print(f"p{project_id}: deleted '{label}'")

print()
for b in db.query(M.BerryBundle).order_by(M.BerryBundle.project_id, M.BerryBundle.id):
    used = db.query(M.DeploymentVersion).filter(M.DeploymentVersion.berry_bundle_id == b.id).count()
    print(f"  p{b.project_id} {b.label:20} {len(b.files):>2} files, used by {used}")
db.close()
