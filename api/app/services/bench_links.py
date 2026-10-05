"""Link old bench runs to their device by the topic they captured (decision 0061).

A marking or a test procedure talks to the firmware and reads only the topic
(`dongle_<serial>`), never a MAC, so until 2026-10-04 none of the marking runs
was linked to a device. The live engine now finds the unit by the topic
(`engine._register_by_topic`). This one-off job does the same for the runs
recorded before that, so a rebuild can read each device's own bench runs.

It takes the engine's rule and nothing looser: only an existing device of the
run's project, found by `engine.devices_by_topic`, and only when exactly one
matches. It writes nothing but `device_unit_id` and `attempt_no` on the run,
and records no step: a rebuild, or `twins.catch_up` on a live twin, reads the
run as evidence.
"""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from .. import models as M
from .flasher.engine import devices_by_topic

#: Deployment kinds whose runs read no MAC.
KINDS = ("mark", "test")


def link_by_topic(db: Session, project_id: int, *, dry_run: bool = True) -> dict:
    """Every run of the project's marking and test deployments that names no
    device: linked when its captured topic names exactly one device of the
    project. Dry run by default; the answer lists every run and what it found."""
    rows = (db.query(M.ProgrammingRun, M.Deployment)
            .join(M.DeploymentVersion, M.DeploymentVersion.id == M.ProgrammingRun.deployment_version_id)
            .join(M.Deployment, M.Deployment.id == M.DeploymentVersion.deployment_id)
            .filter(M.Deployment.project_id == project_id, M.Deployment.kind.in_(KINDS),
                    M.ProgrammingRun.device_unit_id.is_(None), M.ProgrammingRun.draft_run.is_(False))
            .order_by(M.ProgrammingRun.started_at, M.ProgrammingRun.id).all())
    linked, ambiguous, unmatched, no_topic = [], [], [], []
    attempts: dict[int, int] = defaultdict(int)
    batches: dict[str, int] = defaultdict(int)
    for r, dep in rows:
        topic = str((r.results or {}).get("topic") or "").strip()
        if not topic:
            no_topic.append({"run_id": r.id, "kind": dep.kind, "started_at": _at(r)})
            continue
        hits = devices_by_topic(db, project_id, topic)
        if len(hits) != 1:
            (ambiguous if hits else unmatched).append(
                {"run_id": r.id, "kind": dep.kind, "topic": topic, "started_at": _at(r),
                 "devices": [d.id for d in hits][:10]})
            continue
        d = hits[0]
        if d.id not in attempts:
            attempts[d.id] = (db.query(M.ProgrammingRun)
                              .filter(M.ProgrammingRun.device_unit_id == d.id,
                                      M.ProgrammingRun.started_at < r.started_at).count()
                              if r.started_at else db.query(M.ProgrammingRun).filter_by(device_unit_id=d.id).count())
        attempts[d.id] += 1
        batch = db.get(M.ProductionRun, d.production_run_id) if d.production_run_id else None
        batches[batch.label if batch else "no batch"] += 1
        linked.append({"run_id": r.id, "kind": dep.kind, "topic": topic, "device_id": d.id,
                       "serial": d.serial or None, "batch": batch.label if batch else None,
                       "started_at": _at(r), "status": r.status,
                       "marked": bool((r.results or {}).get("marked")),
                       "printed": bool((r.results or {}).get("printed"))})
        if not dry_run:
            r.device_unit_id = d.id
            r.attempt_no = attempts[d.id]
    if not dry_run:
        db.flush()
    twins = ({tw.device_unit_id: tw.status for tw in db.query(M.Twin)
              .filter(M.Twin.device_unit_id.in_({x["device_id"] for x in linked})).all()} if linked else {})
    return {"dry_run": dry_run, "project_id": project_id, "runs": len(rows), "linked": linked,
            "by_batch": dict(sorted(batches.items())),
            "devices_with_an_active_twin": sorted({did for did, st in twins.items() if st == "active"}),
            "ambiguous": ambiguous, "unmatched": unmatched, "no_topic": no_topic}


def _at(r: M.ProgrammingRun) -> str | None:
    return r.started_at.isoformat() if r.started_at else None
