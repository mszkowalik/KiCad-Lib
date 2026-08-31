"""2D quasi-TEM field solver for PCB transmission lines.

The solver itself is `app/services/fieldsolver/` — a self-contained FEM package with
no platform dependencies. This router is the platform half: it owns the job queue,
and it keeps user-defined stackups and production rules in Postgres instead of the
JSON files the standalone prototype used.

Jobs follow the house background pattern (module dict + daemon thread + polling),
with two additions the solver needs: a cancel flag the progress callback raises on,
and a reaper that cancels a job whose client stopped polling — a solve holds a core
and hundreds of megabytes, so an abandoned one must not survive its browser tab.
"""
from __future__ import annotations

import dataclasses
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import SessionLocal, get_db
from ..services import field_state
from ..services.fieldsolver import design as design_mod
from ..services.fieldsolver import materials as materials_mod
from ..services.fieldsolver import rules as rules_mod
from ..services.fieldsolver import tools
from ..services.fieldsolver.analysis import SolveOptions, solve
from ..services.fieldsolver.materials import LIB
from ..services.fieldsolver.stackups import STACKS
from ..services.fieldsolver.templates import TEMPLATES, Params, build
from .users import require_admin
from .util import actor_of

router = APIRouter(prefix="/api/fieldsolver", tags=["fieldsolver"])

F_MIN_HZ = 1e6      # below this the perfect-conductor assumption stops describing a board
F_MAX_HZ = 1e10


# --------------------------------------------------------------- persistence
def _sync_library(db: Session) -> None:
    """Push the database's user-defined stackups and rules into the solver library.

    The solver keeps them in module state (it is a pure library), so every request
    that reads or solves refreshes that state from Postgres first. Cheap: two small
    selects against tables that hold a handful of rows.
    """
    STACKS.load_user({r.key: dict(r.data, id=r.key, name=r.name) for r in db.query(M.FieldStackup).all()})
    rules_mod.load_user({r.key: dict(r.data, id=r.key, name=r.name) for r in db.query(M.FieldRuleSet).all()})


@router.get("/materials")
def materials(db: Session = Depends(get_db)):
    _sync_library(db)
    return LIB.to_list()


@router.get("/stackups")
def stackups(db: Session = Depends(get_db)):
    _sync_library(db)
    return STACKS.to_list()


@router.post("/stackups")
def save_stackup(d: dict, request: Request, db: Session = Depends(get_db)):
    """Stackups are the fab's facts about how boards are made, shared by every
    project, so only an administrator writes them (user decision 2026-08-31)."""
    require_admin(request)
    if not d.get("name") or not d.get("layers"):
        raise HTTPException(400, "name and layers required")
    _sync_library(db)
    try:
        st = STACKS.save(d)
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    row = db.query(M.FieldStackup).filter(M.FieldStackup.key == st.id).one_or_none()
    payload = STACKS.user[st.id]
    if row is None:
        db.add(M.FieldStackup(key=st.id, name=st.name, data=payload, created_by=actor_of(request)))
    else:
        row.name, row.data = st.name, payload
    db.commit()
    return st.to_dict()


@router.delete("/stackups/{sid}")
def delete_stackup(sid: str, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    row = db.query(M.FieldStackup).filter(M.FieldStackup.key == sid).one_or_none()
    if row is None:
        raise HTTPException(400, "not a user stackup")
    db.delete(row)
    db.commit()
    _sync_library(db)
    return {"ok": True}


@router.get("/rules")
def rules(db: Session = Depends(get_db)):
    _sync_library(db)
    return [rules_mod.flat(r) for r in rules_mod.RULES.values()]


@router.post("/rules")
def save_rules(f: dict, request: Request, db: Session = Depends(get_db)):
    if not f.get("name"):
        raise HTTPException(400, "name required")
    _sync_library(db)
    r = rules_mod.save(f)
    row = db.query(M.FieldRuleSet).filter(M.FieldRuleSet.key == r["id"]).one_or_none()
    if row is None:
        db.add(M.FieldRuleSet(key=r["id"], name=r["name"], data=r, created_by=actor_of(request)))
    else:
        row.name, row.data = r["name"], r
    db.commit()
    return rules_mod.flat(r)


@router.delete("/rules/{rid}")
def delete_rules(rid: str, db: Session = Depends(get_db)):
    row = db.query(M.FieldRuleSet).filter(M.FieldRuleSet.key == rid).one_or_none()
    if row is None:
        raise HTTPException(400, "not a user rule set")
    db.delete(row)
    db.commit()
    _sync_library(db)
    return {"ok": True}


@router.get("/finishes")
def finishes():
    return STACKS.finish_presets


@router.get("/templates")
def templates():
    return TEMPLATES


# ------------------------------------------------------------------ requests
class ParamsIn(BaseModel):
    template: str = "microstrip"
    stackup: str = "JLC04161H-7628"
    signal_layer: str = "L1"
    reference_layers: list[str] = ["L2"]
    w: float = 0.3
    s: float = 0.2
    gap: float = 0.3
    etch: float = 0.0
    copper_thickness: float | None = None
    soldermask: bool = True
    via_fence: bool = False
    fence_distance: float | None = 0.5
    fence_width: float | None = None
    via_hole: float = 0.30
    via_pad: float = 0.60
    via_plating_um: float = 18.0
    via_drill_oversize: float = 0.10
    via_filled: bool = False
    via_rows: list[float | None] = []
    mask_expansion: float = 0.05
    roughness_um: float = 0.0
    vias: list[dict] = []
    cutout_mode: str = "auto"
    cutout: float = 1.0
    custom_stackup: dict | None = None


class SolveIn(BaseModel):
    params: ParamsIn
    f_design: float = 2.4e9
    f_min: float = F_MIN_HZ
    f_max: float = F_MAX_HZ
    n_freq: int = 21
    eps_model: str = "djordjevic"
    field: bool = True
    material_overrides: dict[str, dict] = {}


class DesignIn(BaseModel):
    params: ParamsIn
    f_design: float = 2.4e9
    target: float = 50.0
    min_w: float = 0.09
    min_gap: float = 0.09


class SearchIn(BaseModel):
    params: ParamsIn
    f_design: float = 2.4e9
    target: float = 50.0
    tolerance_pct: float = 3.0
    ranges: dict[str, list[float]] = {}
    step: float | None = 0.05
    masks: list[bool] = [True, False]


class GoalIn(BaseModel):
    params: ParamsIn
    f_design: float = 2.4e9
    key: str = "Z0"
    target: float = 50.0
    var: str = "w"
    lo: float = 0.05
    hi: float = 3.0


class SweepIn(BaseModel):
    params: ParamsIn
    f_design: float = 2.4e9
    var: str = "w"
    values: list[float]
    keys: list[str] = ["Z0"]


class SensIn(BaseModel):
    params: ParamsIn
    f_design: float = 2.4e9
    key: str = "Z0"
    tol: dict[str, float] = {"w": 0.02, "copper_thickness": 0.005}


class CutoutIn(BaseModel):
    params: ParamsIn
    f_design: float = 2.4e9
    key: str = "Z0"
    tol: float = 0.01


class JobIn(BaseModel):
    kind: str                      # solve | goal-seek | design | search | sweep | tolerance | cutout
    payload: dict


def _params(p: ParamsIn) -> Params:
    d = p.model_dump()
    from_range = d["fence_distance"] is None
    if from_range:
        d["fence_distance"] = 0.5
    q = Params(**d)
    q.fence_from_range = from_range
    return q


def _opts(f_design: float, f_min: float, f_max: float, n: int, model: str, field: bool) -> SolveOptions:
    f_min = max(F_MIN_HZ, min(f_min, F_MAX_HZ))
    f_max = max(f_min * 1.000001, min(f_max, F_MAX_HZ))
    fs = list(np.geomspace(f_min, f_max, max(2, min(int(n), 120))))
    if not any(abs(f - f_design) / f_design < 1e-6 for f in fs):
        fs = sorted(fs + [float(f_design)])       # the design frequency is always solved
    return SolveOptions(f_design=f_design, f_sweep=fs, eps_model=model, return_field=field)


def _apply_overrides(ov: dict[str, dict], f: float) -> None:
    for mid, d in ov.items():
        LIB.get(mid).points = [{"f_hz": f, "dk": float(d["dk"]), "tand": float(d.get("tand", 0.0)), "override": True}]


def _reset_overrides() -> None:
    fresh = materials_mod.Library()
    for mid, m in fresh.materials.items():
        LIB.materials[mid].points = m.points


@router.post("/geometry")
def geometry(p: ParamsIn, db: Session = Depends(get_db)):
    _sync_library(db)
    try:
        return build(_params(p)).to_dict()
    except RuntimeError as e:               # the mesher is not installed on this arch
        raise HTTPException(503, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@router.post("/check")
def check_ep(p: ParamsIn, rule: str = "jlcpcb_standard", db: Session = Depends(get_db)):
    _sync_library(db)
    st = STACKS.custom(p.custom_stackup) if p.custom_stackup else STACKS.get(p.stackup)
    return rules_mod.check(rule, p.model_dump(), len(st.copper()))


# ---------------------------------------------------------------------- jobs
JOBS: dict[str, dict] = {}
JOB_LOCK = threading.Lock()
STALE_AFTER_S = 20.0           # no poll for this long: the browser is gone
KEEP_FINISHED_S = 900.0


class JobCancelled(Exception):
    """Raised inside a solve when the job is cancelled or its client walked away."""


def _run_job(jid: str, kind: str, payload: dict) -> None:
    job = JOBS[jid]

    def progress(msg, frac=None, phase=None):
        if job.get("cancel"):
            raise JobCancelled()
        job["message"] = msg
        if frac is not None:
            job["fraction"] = frac
        if phase is not None:
            job["phase"] = phase

    try:
        if kind == "solve":
            q = SolveIn(**payload)
            with JOB_LOCK:
                _apply_overrides(q.material_overrides, q.f_design)
                try:
                    geo = build(_params(q.params))

                    def on_design(res):
                        res = dict(res, geometry=geo.to_dict())
                        job["partial"] = res
                        job["partial_no"] = job.get("partial_no", 0) + 1

                    def on_frame(fr):
                        job.setdefault("frames", []).append(fr)
                        job["frames_f"] = [x["f"] for x in job["frames"]]

                    r = solve(geo, _opts(q.f_design, q.f_min, q.f_max, q.n_freq, q.eps_model, q.field),
                              progress, on_design, on_frame)
                finally:
                    if q.material_overrides:
                        _reset_overrides()
            r["geometry"] = geo.to_dict()
        elif kind == "goal-seek":
            q = GoalIn(**payload)
            r = tools.goal_seek(_params(q.params), q.f_design, q.key, q.target, q.var, q.lo, q.hi, progress=progress)
        elif kind == "design":
            q = DesignIn(**payload)
            r = design_mod.design(_params(q.params), q.f_design, q.target, q.min_w, q.min_gap, progress=progress)
        elif kind == "search":
            q = SearchIn(**payload)
            r = design_mod.search(_params(q.params), q.f_design, q.target, q.tolerance_pct,
                                  q.ranges, q.step, tuple(q.masks), progress=progress)
        elif kind == "sweep":
            q = SweepIn(**payload)
            r = []
            for k, x in enumerate(q.values):
                progress(f"{q.var} = {x:.3f} ({k + 1}/{len(q.values)})", k / len(q.values), "sweep")
                r += tools.sweep(_params(q.params), q.f_design, q.var, [x], q.keys)
        elif kind == "cutout":
            q = CutoutIn(**payload)
            r = tools.required_cutout(_params(q.params), q.f_design, q.key, q.tol, progress=progress)
        elif kind == "tolerance":
            q = SensIn(**payload)
            progress("central differences", 0.1, "tolerance")
            p = _params(q.params)
            if p.copper_thickness is None and "copper_thickness" in q.tol:
                st = STACKS.custom(p.custom_stackup) if p.custom_stackup else STACKS.get(p.stackup)
                p = dataclasses.replace(p, copper_thickness=st.layer(p.signal_layer)["thickness_mm"])
            r = tools.tolerance(p, q.f_design, q.key, q.tol)
        else:
            raise ValueError(f"unknown job kind {kind}")
        if job.get("cancel"):
            raise JobCancelled()
        job.update(state="done", result=r, fraction=1.0, message="done", finished=time.time())
    except JobCancelled:
        job.update(state="cancelled", message="cancelled", finished=time.time())
    except (ValueError, KeyError, RuntimeError) as e:
        job.update(state="error", error=str(e), finished=time.time())
    except Exception as e:                                  # noqa: BLE001 - reported to the client
        job.update(state="error", error=str(e), trace=traceback.format_exc(), finished=time.time())


def _reap_jobs() -> None:
    """Cancel jobs nobody is listening to, and forget old records."""
    while True:
        now = time.time()
        for j in list(JOBS.values()):
            if j["state"] == "running" and not j.get("cancel") and now - j.get("last_poll", now) > STALE_AFTER_S:
                j["cancel"] = True
                j["message"] = "cancelled: the client stopped listening"
        for jid, j in list(JOBS.items()):
            if j["state"] != "running" and now - j.get("finished", now) > KEEP_FINISHED_S:
                JOBS.pop(jid, None)
        if not any(j["state"] == "running" for j in JOBS.values()):
            design_mod.kill_stray_workers()
        time.sleep(2)


threading.Thread(target=_reap_jobs, daemon=True).start()


@router.post("/jobs")
def start_job(j: JobIn, db: Session = Depends(get_db)):
    _sync_library(db)
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"id": jid, "kind": j.kind, "state": "running", "message": "queued", "fraction": 0.0,
                 "cancel": False, "last_poll": time.time(), "started": time.time()}
    threading.Thread(target=_run_job, args=(jid, j.kind, j.payload), daemon=True).start()
    return {"id": jid}


@router.get("/jobs/{jid}")
def job_status(jid: str, full: bool = False):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    job["last_poll"] = time.time()
    out = {k: v for k, v in job.items() if k not in ("result", "partial", "frames")}
    if job["state"] == "done" and full:
        out["result"] = job["result"]
        out["frames"] = job.get("frames", [])
        JOBS.pop(jid, None)
    return out


@router.get("/jobs/{jid}/partial")
def job_partial(jid: str):
    job = JOBS.get(jid)
    if not job or "partial" not in job:
        raise HTTPException(404, "no partial result")
    return job["partial"]


@router.get("/jobs/{jid}/frames")
def job_frames(jid: str, after: int = 0):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    return {"frames": job.get("frames", [])[after:]}


@router.delete("/jobs/{jid}")
def cancel_job(jid: str):
    job = JOBS.get(jid)
    if not job:
        raise HTTPException(404, "no such job")
    job["cancel"] = True
    job["message"] = "cancelling…"
    return {"id": jid, "state": job["state"], "cancel": True}


# ------------------------------------------------- a board's impedance work
# Which stackup a board is built on, and the impedance profiles it carries, are
# commit-versioned exactly like the manual cost data: assigned at a commit, carried
# forward by later commits until somebody changes them. See services/field_state.py.

class BoardStackupIn(BaseModel):
    stackup_key: str
    board: str = ""
    snapshot_id: int | None = None


class ProfileIn(BaseModel):
    name: str
    config: dict
    result: dict | None = None
    board: str = ""
    snapshot_id: int | None = None
    profile_id: int | None = None


def _snapshot(db: Session, snapshot_id: int | None):
    if snapshot_id is None:
        return None
    s = db.get(M.ProjectSnapshot, snapshot_id)
    if s is None:
        raise HTTPException(404, "snapshot not found")
    return s


def _stackup_dict(key: str) -> dict | None:
    try:
        return STACKS.get(key).to_dict()
    except KeyError:
        return None


def _board_state(db: Session, project_id: int, board: str, snapshot):
    rev, profiles = field_state.state_for(db, project_id, board, snapshot)
    key = rev.stackup_key if rev else ""
    st = _stackup_dict(key) if key else None
    sha = field_state.stackup_sha(st)
    return {
        "revision": field_state.revision_json(rev),
        "stackup": st,
        "profiles": [
            field_state.profile_json(p, field_state.is_outdated(p, sha, key)) for p in profiles
        ],
    }


@router.get("/projects/{project_id}/board")
def board_state(project_id: int, board: str = "", snapshot_id: int | None = None,
                db: Session = Depends(get_db)):
    """The board's assigned stackup and profiles at this commit, plus whatever the
    `.kicad_pcb` says about its own stackup — the two are allowed to disagree, and
    the difference is reported rather than enforced."""
    _sync_library(db)
    snap = _snapshot(db, snapshot_id)
    out = _board_state(db, project_id, board, snap)
    out["board_file"] = None
    out["mismatch"] = []
    if snap is not None:
        try:
            from ..services import gitrepo

            root = gitrepo.materialize(snap.project_id, snap.sha)
            name = board or ((snap.boards or [{}])[0] or {}).get("name", "")
            entry = next((b for b in (snap.boards or []) if b.get("name") == name), None)
            pcb = entry.get("pcb") if entry else None
            if pcb:
                declared = field_state.board_stackup(root / pcb)
                out["board_file"] = declared
                out["mismatch"] = field_state.compare_stackup(declared, out["stackup"])
        except Exception:
            # a pruned checkout or an unreadable board must not break the page
            out["board_file"] = None
    return out


@router.post("/projects/{project_id}/stackup")
def assign_stackup(project_id: int, body: BoardStackupIn, request: Request,
                   db: Session = Depends(get_db)):
    """Assign a stackup to a board, effective at this commit and forward.

    Profiles already on the board are kept — with their results — and any result
    computed against a different stackup is reported as outdated rather than removed.
    """
    _sync_library(db)
    if body.stackup_key and _stackup_dict(body.stackup_key) is None:
        raise HTTPException(400, f"unknown stackup {body.stackup_key}")
    snap = _snapshot(db, body.snapshot_id)
    rev, _ = field_state.revision_for_edit(db, project_id, body.board, snap)
    rev.stackup_key = body.stackup_key
    rev.created_by = rev.created_by or actor_of(request)
    db.commit()
    return _board_state(db, project_id, body.board, snap)


@router.post("/projects/{project_id}/profiles")
def save_profile(project_id: int, body: ProfileIn, request: Request,
                 db: Session = Depends(get_db)):
    """Create or update one impedance profile of a board, results included."""
    _sync_library(db)
    snap = _snapshot(db, body.snapshot_id)
    rev, copies = field_state.revision_for_edit(db, project_id, body.board, snap)
    key = rev.stackup_key
    st = _stackup_dict(key) if key else None
    target = None
    if body.profile_id is not None:
        # the edit may have copied the revision: follow the profile to its copy
        target = copies.get(body.profile_id) or db.get(M.ProjectFieldProfile, body.profile_id)
        if target is not None and target.revision_id != rev.id:
            target = None
    if target is None:
        pos = 1 + max([p.position for p in field_state.profiles_of(db, rev)] or [0])
        target = M.ProjectFieldProfile(revision_id=rev.id, position=pos, name=body.name,
                                       config=body.config, created_by=actor_of(request))
        db.add(target)
    target.name = body.name
    target.config = body.config
    if body.result is not None:
        target.result = body.result
        target.solved_at = datetime.now(timezone.utc)
        target.stackup_key = key
        target.stackup_sha = field_state.stackup_sha(st)
    db.commit()
    return _board_state(db, project_id, body.board, snap)


@router.delete("/projects/{project_id}/profiles/{profile_id}")
def delete_profile(project_id: int, profile_id: int, board: str = "",
                   snapshot_id: int | None = None, db: Session = Depends(get_db)):
    _sync_library(db)
    snap = _snapshot(db, snapshot_id)
    rev, copies = field_state.revision_for_edit(db, project_id, board, snap)
    target = copies.get(profile_id) or db.get(M.ProjectFieldProfile, profile_id)
    if target is None or target.revision_id != rev.id:
        raise HTTPException(404, "profile not in the revision in effect at this commit")
    db.delete(target)
    db.commit()
    return _board_state(db, project_id, board, snap)
