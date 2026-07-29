"""Audit every deployment version: does it validate, and is it used?"""
from app.db import SessionLocal
from app import models as M
from app.services.flasher import validate

db = SessionLocal()
for dep in db.query(M.Deployment).order_by(M.Deployment.id):
    print(f"\n=== [{dep.id}] {dep.name} (chip {dep.chip or '?'})")
    for v in sorted(dep.versions, key=lambda x: x.version_no):
        runs = db.query(M.ProgrammingRun).filter(
            M.ProgrammingRun.deployment_version_id == v.id).count()
        res = validate.check(db, v)
        flag = "OK " if res["ok"] else "BAD"
        print(f"  {flag} v{v.version_no:<3} id={v.id:<3} {v.status:9} steps={len(v.steps or []):<3} "
              f"img={len(v.images)} files={len(v.files):<3} runs={runs:<5} {v.files_label or '-'}")
        for e in res["errors"]:
            print(f"        ERR {e[:110]}")
db.close()
