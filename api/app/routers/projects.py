"""Projects: git-tracked KiCad designs — CRUD, fetch/history, snapshot
ingest, priced BOMs, renders (board layers / 3D / schematic), checks,
fab bundles, cost & extra-BOM items, notes, diffs, stock checks, FX."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..models import utcnow
from ..services import cost_state, fx, gitrepo, ladder, project_bom, project_ingest, project_render, storage
from ..services.crypto import decrypt_token, encrypt_token
from .util import audit

router = APIRouter(prefix="/api", tags=["projects"])


# ------------------------------------------------------------------ helpers

def _project(db: Session, project_id: int) -> M.Project:
    p = db.get(M.Project, project_id)
    if p is None:
        raise HTTPException(404, "project not found")
    return p


def _snapshot(db: Session, snapshot_id: int) -> M.ProjectSnapshot:
    s = db.get(M.ProjectSnapshot, snapshot_id)
    if s is None:
        raise HTTPException(404, "snapshot not found")
    return s


def _token(p: M.Project) -> str | None:
    if not p.git_token_enc:
        return None
    try:
        return decrypt_token(p.git_token_enc)
    except ValueError as e:
        raise HTTPException(500, str(e)) from e


def _board(snap: M.ProjectSnapshot, board_name: str) -> dict:
    for b in snap.boards or []:
        if b["name"] == board_name:
            return b
    raise HTTPException(404, f"board '{board_name}' not in snapshot")


def _snap_json(s: M.ProjectSnapshot, stage: str | None = None) -> dict:
    return {
        "id": s.id,
        "project_id": s.project_id,
        "sha": s.sha,
        "ref_name": s.ref_name,
        "is_tag": s.is_tag,
        "commit_message": s.commit_message,
        "committed_at": s.committed_at.isoformat() if s.committed_at else None,
        "status": s.status,
        "stage": stage if stage is not None else project_ingest.active_stage(s.id),
        "error": s.error,
        "boards": s.boards or [],
        "report": s.report,
        "created_at": s.created_at.isoformat(),
    }


def _project_json(db: Session, p: M.Project) -> dict:
    latest = (
        db.query(M.ProjectSnapshot)
        .filter_by(project_id=p.id, status="ready")
        .order_by(M.ProjectSnapshot.created_at.desc())
        .first()
    )
    run_count = db.query(M.ProductionRun).filter_by(project_id=p.id).count()
    return {
        "id": p.id,
        "name": p.name,
        "git_url": p.git_url,
        "has_token": bool(p.git_token_enc),
        "default_branch": p.default_branch,
        "display_currency": p.display_currency,
        "effective_currency": project_bom.display_currency(p),
        "description": p.description,
        "created_at": p.created_at.isoformat(),
        "has_mirror": gitrepo.has_mirror(p.id),
        "latest_snapshot": _snap_json(latest) if latest else None,
        "run_count": run_count,
    }


# --------------------------------------------------------------------- CRUD

class ProjectIn(BaseModel):
    name: str
    git_url: str
    git_token: str | None = None
    default_branch: str = "main"
    display_currency: str | None = None
    description: str = ""


class ProjectPatch(BaseModel):
    name: str | None = None
    git_url: str | None = None
    # "" clears the stored token; None leaves it unchanged
    git_token: str | None = None
    default_branch: str | None = None
    display_currency: str | None = None
    description: str | None = None


@router.get("/projects")
def list_projects(db: Session = Depends(get_db)):
    return [_project_json(db, p) for p in db.query(M.Project).order_by(M.Project.name).all()]


@router.post("/projects")
def create_project(body: ProjectIn, db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name or not body.git_url.strip():
        raise HTTPException(422, "name and git_url are required")
    if db.query(M.Project).filter_by(name=name).first():
        raise HTTPException(409, f"project '{name}' already exists")
    p = M.Project(
        name=name,
        git_url=body.git_url.strip(),
        git_token_enc=encrypt_token(body.git_token) if body.git_token else None,
        default_branch=body.default_branch.strip() or "main",
        display_currency=(body.display_currency or "").upper() or None,
        description=body.description,
    )
    db.add(p)
    db.flush()
    audit(db, "project.create", "project", p.id, {"name": name})
    db.commit()
    return _project_json(db, p)


@router.get("/projects/{project_id}")
def get_project(project_id: int, db: Session = Depends(get_db)):
    return _project_json(db, _project(db, project_id))


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectPatch, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    if body.name is not None and body.name.strip() and body.name.strip() != p.name:
        if db.query(M.Project).filter_by(name=body.name.strip()).first():
            raise HTTPException(409, "name already in use")
        p.name = body.name.strip()
    if body.git_url is not None and body.git_url.strip():
        p.git_url = body.git_url.strip()
    if body.git_token is not None:
        p.git_token_enc = encrypt_token(body.git_token) if body.git_token else None
    if body.default_branch is not None and body.default_branch.strip():
        p.default_branch = body.default_branch.strip()
    if body.display_currency is not None:
        p.display_currency = body.display_currency.upper() or None
    if body.description is not None:
        p.description = body.description
    audit(db, "project.update", "project", p.id)
    db.commit()
    return _project_json(db, p)


@router.delete("/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    for snap in db.query(M.ProjectSnapshot).filter_by(project_id=project_id).all():
        db.delete(snap)
    for model in (M.ProjectExtraBomItem, M.ProjectCostItem, M.ProjectNote):
        db.query(model).filter_by(project_id=project_id).delete()
    for run in db.query(M.ProductionRun).filter_by(project_id=project_id).all():
        db.delete(run)
    db.delete(p)
    audit(db, "project.delete", "project", project_id, {"name": p.name})
    db.commit()
    storage.delete_prefix(f"projects/{project_id}/")
    import shutil

    shutil.rmtree(gitrepo.mirror_path(project_id), ignore_errors=True)
    shutil.rmtree(settings.checkouts_dir / str(project_id), ignore_errors=True)
    return {"deleted": project_id}


# ------------------------------------------------------------ git / history

@router.post("/projects/{project_id}/fetch")
def fetch_project(project_id: int, db: Session = Depends(get_db)):
    """Update the mirror; auto-ingest (and pre-render) new tags + head."""
    p = _project(db, project_id)
    try:
        result = project_ingest.fetch_and_autoingest(p.id, p.git_url, _token(p), p.default_branch)
    except gitrepo.GitError as e:
        raise HTTPException(502, f"git fetch failed: {e}") from e
    audit(db, "project.fetch", "project", p.id, result)
    db.commit()
    return result


@router.get("/projects/{project_id}/history")
def project_history(project_id: int, ref: str = "", limit: int = Query(100, le=500),
                    db: Session = Depends(get_db)):
    p = _project(db, project_id)
    if not gitrepo.has_mirror(p.id):
        raise HTTPException(409, "repository not fetched yet — run fetch first")
    try:
        commits = gitrepo.log(p.id, ref or p.default_branch or "HEAD", limit)
    except gitrepo.GitError as e:
        raise HTTPException(502, str(e)) from e
    snaps = {
        s.sha: s
        for s in db.query(M.ProjectSnapshot).filter_by(project_id=p.id).all()
    }
    for c in commits:
        s = snaps.get(c["sha"])
        c["snapshot"] = {"id": s.id, "status": s.status} if s else None
    return {
        "branch": ref or p.default_branch,
        "branches": gitrepo.branches(p.id),
        "tags": gitrepo.tags(p.id),
        "commits": commits,
    }


@router.get("/projects/{project_id}/files")
def project_files(project_id: int, sha: str, db: Session = Depends(get_db)):
    _project(db, project_id)
    try:
        return gitrepo.list_files(project_id, sha)
    except gitrepo.GitError as e:
        raise HTTPException(404, str(e)) from e


@router.get("/projects/{project_id}/file")
def project_file(project_id: int, sha: str, path: str, db: Session = Depends(get_db)):
    _project(db, project_id)
    try:
        data = gitrepo.show_file(project_id, sha, path)
    except gitrepo.GitError as e:
        raise HTTPException(404, str(e)) from e
    media = "text/plain; charset=utf-8"
    lower = path.lower()
    for ext, m in ((".pdf", "application/pdf"), (".png", "image/png"), (".jpg", "image/jpeg"),
                   (".svg", "image/svg+xml"), (".step", "application/step"), (".zip", "application/zip")):
        if lower.endswith(ext):
            media = m
    return Response(content=data, media_type=media)


# ---------------------------------------------------------------- snapshots

class IngestIn(BaseModel):
    ref: str  # sha, tag or branch


@router.get("/projects/{project_id}/snapshots")
def list_snapshots(project_id: int, db: Session = Depends(get_db)):
    _project(db, project_id)
    snaps = (
        db.query(M.ProjectSnapshot)
        .filter_by(project_id=project_id)
        .order_by(M.ProjectSnapshot.created_at.desc())
        .all()
    )
    return [_snap_json(s) for s in snaps]


@router.post("/projects/{project_id}/snapshots")
def ingest_snapshot(project_id: int, body: IngestIn, db: Session = Depends(get_db)):
    p = _project(db, project_id)
    if not gitrepo.has_mirror(p.id):
        raise HTTPException(409, "repository not fetched yet — run fetch first")
    ref = body.ref.strip()
    try:
        sha = gitrepo.rev_parse(p.id, ref)
    except gitrepo.GitError as e:
        raise HTTPException(404, f"unknown ref: {e}") from e
    tag_names = {t["name"]: t["sha"] for t in gitrepo.tags(p.id)}
    is_tag = ref in tag_names
    project_ingest.start_ingest(p.id, sha, ref_name=ref, is_tag=is_tag)
    audit(db, "project.ingest", "project", p.id, {"ref": ref, "sha": sha})
    db.commit()
    return {"status": "started", "sha": sha}


@router.get("/snapshots/{snapshot_id}")
def get_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    return _snap_json(_snapshot(db, snapshot_id))


@router.delete("/snapshots/{snapshot_id}")
def delete_snapshot(snapshot_id: int, db: Session = Depends(get_db)):
    s = _snapshot(db, snapshot_id)
    project_id, sha = s.project_id, s.sha
    db.delete(s)
    audit(db, "snapshot.delete", "project_snapshot", snapshot_id)
    db.commit()
    storage.delete_prefix(f"projects/{project_id}/renders/{sha}/")
    storage.delete_prefix(f"projects/{project_id}/snapshots/{sha}/")
    return {"deleted": snapshot_id}


# ----------------------------------------------------------------- BOM/costs

@router.get("/snapshots/{snapshot_id}/bom")
def snapshot_bom(snapshot_id: int, board: str, variant: str = "", volume: int = 1,
                 currency: str | None = None, db: Session = Depends(get_db)):
    s = _snapshot(db, snapshot_id)
    if s.status != "ready":
        raise HTTPException(409, f"snapshot is {s.status}")
    _board(s, board)
    p = _project(db, s.project_id)
    return project_bom.priced_bom(db, p, s, board, variant, volume, currency)


@router.get("/snapshots/{snapshot_id}/bom/curve")
def snapshot_bom_curve(snapshot_id: int, board: str, variant: str = "",
                       volumes: str = "1,10,100,1000", currency: str | None = None,
                       db: Session = Depends(get_db)):
    s = _snapshot(db, snapshot_id)
    _board(s, board)
    p = _project(db, s.project_id)
    try:
        vols = sorted({max(1, int(v)) for v in volumes.split(",") if v.strip()})
    except ValueError:
        raise HTTPException(422, "volumes must be a comma-separated list of integers") from None
    if len(vols) > 12:
        raise HTTPException(422, "at most 12 volumes")
    return project_bom.cost_curve(db, p, s, board, variant, vols, currency)


@router.get("/projects/{project_id}/bom-diff")
def bom_diff(project_id: int, from_snapshot: int, to_snapshot: int, board: str,
             variant: str = "", db: Session = Depends(get_db)):
    _project(db, project_id)
    a, b = _snapshot(db, from_snapshot), _snapshot(db, to_snapshot)
    if a.project_id != project_id or b.project_id != project_id:
        raise HTTPException(422, "snapshots belong to another project")
    return project_bom.bom_diff(db, a, b, board, variant)


@router.post("/snapshots/{snapshot_id}/stock-check")
def stock_check(snapshot_id: int, board: str, variant: str = "", volume: int = 1,
                refresh: bool = True, db: Session = Depends(get_db)):
    s = _snapshot(db, snapshot_id)
    _board(s, board)
    return project_bom.stock_check(db, s, board, variant, volume, refresh)


# ------------------------------------------------------------------ renders

def _render_or_404(key: str, op: str, rel_src: str, **kw) -> Response:
    try:
        data, media = project_render.cached_op(key, op, rel_src, **kw)
    except Exception as e:
        raise HTTPException(502, f"render failed: {e}") from e
    return Response(content=data, media_type=media)


def _rel_src(db: Session, snapshot_id: int, board: str, kind: str) -> tuple[M.ProjectSnapshot, dict, str]:
    s = _snapshot(db, snapshot_id)
    b = _board(s, board)
    if not b.get(kind):
        raise HTTPException(404, f"board has no {kind} file")
    gitrepo.materialize(s.project_id, s.sha)  # re-create checkout if pruned
    return s, b, project_render.rel_checkout(s.project_id, s.sha, b[kind])


@router.get("/snapshots/{snapshot_id}/boards/{board}/layers")
def board_layers(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    s = _snapshot(db, snapshot_id)
    b = _board(s, board)
    return {"layers": b.get("layers") or [], "variants": b.get("variants") or []}


@router.get("/snapshots/{snapshot_id}/boards/{board}/layer.svg")
def board_layer_svg(snapshot_id: int, board: str, layer: str, db: Session = Depends(get_db)):
    s, b, rel = _rel_src(db, snapshot_id, board, "pcb")
    if layer not in [ly["name"] for ly in b.get("layers") or []]:
        raise HTTPException(404, f"unknown layer '{layer}'")
    try:
        data, media = project_render.board_layer(s.project_id, s.sha, board, rel, layer)
    except Exception as e:
        raise HTTPException(502, f"render failed: {e}") from e
    return Response(content=data, media_type=media)


@router.get("/snapshots/{snapshot_id}/boards/{board}/board.glb")
def board_glb(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    s, _, rel = _rel_src(db, snapshot_id, board, "pcb")
    key = project_render.render_key(s.project_id, s.sha, board, "board.glb")
    return _render_or_404(key, "board_glb", rel)


@router.get("/snapshots/{snapshot_id}/boards/{board}/board.step")
def board_step(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    s, _, rel = _rel_src(db, snapshot_id, board, "pcb")
    key = project_render.render_key(s.project_id, s.sha, board, "board.step")
    return _render_or_404(key, "board_step", rel)


@router.get("/snapshots/{snapshot_id}/boards/{board}/schematic")
def schematic_pages(snapshot_id: int, board: str, variant: str = "", db: Session = Depends(get_db)):
    """Renders (cached) and lists the page SVGs for a board's schematic."""
    import io
    import zipfile

    s, _, rel = _rel_src(db, snapshot_id, board, "sch")
    try:
        data = project_render.sch_pages_zip(s.project_id, s.sha, board, rel, variant)
    except Exception as e:
        raise HTTPException(502, f"render failed: {e}") from e
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        pages = sorted(n for n in z.namelist() if n.endswith(".svg"))
    return {"variant": variant, "pages": pages}


@router.get("/snapshots/{snapshot_id}/boards/{board}/schematic/page")
def schematic_page(snapshot_id: int, board: str, page: str, variant: str = "",
                   db: Session = Depends(get_db)):
    import io
    import zipfile

    s, _, rel = _rel_src(db, snapshot_id, board, "sch")
    try:
        data = project_render.sch_pages_zip(s.project_id, s.sha, board, rel, variant)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if page not in z.namelist():
                raise HTTPException(404, "page not found")
            return Response(content=z.read(page), media_type="image/svg+xml")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"render failed: {e}") from e


@router.get("/snapshots/{snapshot_id}/boards/{board}/map")
def board_map(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    """Interactive click-map: footprint/symbol hotspots (mm, same coordinate
    space as the SVG viewBox) enriched with matched BOM lines, plus sub-sheet
    rectangles for schematic navigation. Cached by sha."""
    from ..services import project_map

    s = _snapshot(db, snapshot_id)
    b = _board(s, board)
    try:
        return project_map.build_map(db, s, b)
    except Exception as e:
        raise HTTPException(502, f"map extraction failed: {e}") from e


@router.get("/snapshots/{snapshot_id}/boards/{board}/checks")
def board_checks(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    """ERC + DRC JSON summaries (rendered on demand, cached by sha)."""
    import json

    s = _snapshot(db, snapshot_id)
    b = _board(s, board)
    out: dict = {}
    for op, kind in (("erc", "sch"), ("drc", "pcb")):
        if not b.get(kind):
            out[op] = None
            continue
        gitrepo.materialize(s.project_id, s.sha)
        rel = project_render.rel_checkout(s.project_id, s.sha, b[kind])
        key = project_render.render_key(s.project_id, s.sha, board, f"{op}.json")
        try:
            data, _media = project_render.cached_op(key, op, rel)
            out[op] = json.loads(data)
        except Exception as e:
            out[op] = {"error": str(e)}
    return out


@router.get("/snapshots/{snapshot_id}/boards/{board}/fab.zip")
def fab_bundle(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    s, _, rel = _rel_src(db, snapshot_id, board, "pcb")
    key = project_render.render_key(s.project_id, s.sha, board, "fab.zip")
    resp = _render_or_404(key, "fab", rel)
    resp.headers["Content-Disposition"] = f'attachment; filename="{board}-{s.ref_name or s.sha[:10]}-fab.zip"'
    return resp


# ------------------------------------------------- extra BOM items / costs

class ExtraItemIn(BaseModel):
    label: str
    qty: float = 1.0
    component_id: int | None = None
    manufacturer: str = ""
    mpn: str = ""
    unit_price: float | None = None
    currency: str = "USD"
    notes: str = ""
    position: int = 0


def _extra_json(x: M.ProjectExtraBomItem) -> dict:
    return {
        "id": x.id, "project_id": x.project_id, "position": x.position, "label": x.label,
        "qty": x.qty, "component_id": x.component_id, "manufacturer": x.manufacturer,
        "mpn": x.mpn, "unit_price": x.unit_price, "currency": x.currency, "notes": x.notes,
    }


def _cost_snapshot(db: Session, project_id: int, snapshot_id: int | None) -> M.ProjectSnapshot | None:
    """Resolve the commit context of a cost-list read/edit (None = current)."""
    if snapshot_id is None:
        return None
    snap = db.get(M.ProjectSnapshot, snapshot_id)
    if snap is None or snap.project_id != project_id:
        raise HTTPException(404, "snapshot not found in this project")
    return snap


_STALE_LIST = (
    "item does not belong to the cost list in effect at this commit — reload the list"
)


@router.get("/projects/{project_id}/extra-items")
def list_extra_items(project_id: int, snapshot_id: int | None = None,
                     db: Session = Depends(get_db)):
    _project(db, project_id)
    snap = _cost_snapshot(db, project_id, snapshot_id)
    extras, _, rev = cost_state.items_for(db, project_id, snap)
    return {"items": [_extra_json(x) for x in extras],
            "revision": cost_state.revision_json(rev)}


@router.post("/projects/{project_id}/extra-items")
def add_extra_item(project_id: int, body: ExtraItemIn, snapshot_id: int | None = None,
                   db: Session = Depends(get_db)):
    _project(db, project_id)
    if body.component_id is not None and db.get(M.Component, body.component_id) is None:
        raise HTTPException(404, "linked component not found")
    snap = _cost_snapshot(db, project_id, snapshot_id)
    rev, _, _ = cost_state.revision_for_edit(db, project_id, snap)
    x = M.ProjectExtraBomItem(project_id=project_id, revision_id=rev.id, **body.model_dump())
    db.add(x)
    db.flush()
    audit(db, "project.extra_item.add", "project_extra_bom_item", x.id,
          {"project_id": project_id, "revision_id": rev.id, "anchor_sha": rev.effective_sha})
    db.commit()
    return _extra_json(x)


@router.patch("/extra-items/{item_id}")
def update_extra_item(item_id: int, body: ExtraItemIn, snapshot_id: int | None = None,
                      db: Session = Depends(get_db)):
    x = db.get(M.ProjectExtraBomItem, item_id)
    if x is None:
        raise HTTPException(404, "item not found")
    snap = _cost_snapshot(db, x.project_id, snapshot_id)
    rev, extra_map, _ = cost_state.revision_for_edit(db, x.project_id, snap)
    target = x if x.revision_id == rev.id else extra_map.get(x.id)
    if target is None:
        raise HTTPException(409, _STALE_LIST)
    for k, v in body.model_dump().items():
        setattr(target, k, v)
    db.commit()
    return _extra_json(target)


@router.delete("/extra-items/{item_id}")
def delete_extra_item(item_id: int, snapshot_id: int | None = None,
                      db: Session = Depends(get_db)):
    x = db.get(M.ProjectExtraBomItem, item_id)
    if x is None:
        raise HTTPException(404, "item not found")
    snap = _cost_snapshot(db, x.project_id, snapshot_id)
    rev, extra_map, _ = cost_state.revision_for_edit(db, x.project_id, snap)
    target = x if x.revision_id == rev.id else extra_map.get(x.id)
    if target is None:
        raise HTTPException(409, _STALE_LIST)
    db.delete(target)
    db.commit()
    return {"deleted": item_id}


class CostStepIn(BaseModel):
    qty_from: int
    price: float


class CostItemIn(BaseModel):
    label: str
    basis: str = "per_device"
    price: float = 0.0
    # Quantity breaks (same currency as `price`); `price` is the qty-1 tier.
    steps: list[CostStepIn] | None = None
    currency: str = "USD"
    company: str = ""
    mpn: str = ""
    # production-step identity from services/cost_steps.py; "" = free-form item
    step_key: str = ""
    notes: str = ""
    position: int = 0


def _norm_steps(steps: list[CostStepIn] | None) -> list[dict] | None:
    """Sorted, deduplicated (last wins per qty_from), qty_from >= 2 — the
    qty-1 tier is the item's base price."""
    if not steps:
        return None
    by_qty: dict[int, float] = {}
    for s in steps:
        if s.qty_from < 2:
            raise HTTPException(422, "step qty_from must be >= 2 (the base price is the qty-1 tier)")
        if s.price < 0:
            raise HTTPException(422, "step price must be >= 0")
        by_qty[s.qty_from] = s.price
    return [{"qty_from": q, "price": by_qty[q]} for q in sorted(by_qty)]


def _cost_json(c: M.ProjectCostItem) -> dict:
    return {
        "id": c.id, "project_id": c.project_id, "position": c.position, "label": c.label,
        "basis": c.basis, "price": c.price, "steps": c.steps or [], "currency": c.currency,
        "company": c.company, "mpn": c.mpn, "step_key": c.step_key, "notes": c.notes,
    }


@router.get("/projects/{project_id}/cost-items")
def list_cost_items(project_id: int, snapshot_id: int | None = None,
                    db: Session = Depends(get_db)):
    _project(db, project_id)
    snap = _cost_snapshot(db, project_id, snapshot_id)
    _, costs, rev = cost_state.items_for(db, project_id, snap)
    return {"items": [_cost_json(c) for c in costs],
            "revision": cost_state.revision_json(rev)}


@router.post("/projects/{project_id}/cost-items")
def add_cost_item(project_id: int, body: CostItemIn, snapshot_id: int | None = None,
                  db: Session = Depends(get_db)):
    _project(db, project_id)
    if body.basis not in ("per_device", "per_run"):
        raise HTTPException(422, "basis must be per_device or per_run")
    snap = _cost_snapshot(db, project_id, snapshot_id)
    rev, _, _ = cost_state.revision_for_edit(db, project_id, snap)
    data = body.model_dump()
    data["steps"] = _norm_steps(body.steps)
    c = M.ProjectCostItem(project_id=project_id, revision_id=rev.id, **data)
    db.add(c)
    db.flush()
    audit(db, "project.cost_item.add", "project_cost_item", c.id,
          {"project_id": project_id, "revision_id": rev.id, "anchor_sha": rev.effective_sha})
    db.commit()
    return _cost_json(c)


@router.patch("/cost-items/{item_id}")
def update_cost_item(item_id: int, body: CostItemIn, snapshot_id: int | None = None,
                     db: Session = Depends(get_db)):
    c = db.get(M.ProjectCostItem, item_id)
    if c is None:
        raise HTTPException(404, "item not found")
    if body.basis not in ("per_device", "per_run"):
        raise HTTPException(422, "basis must be per_device or per_run")
    snap = _cost_snapshot(db, c.project_id, snapshot_id)
    rev, _, cost_map = cost_state.revision_for_edit(db, c.project_id, snap)
    target = c if c.revision_id == rev.id else cost_map.get(c.id)
    if target is None:
        raise HTTPException(409, _STALE_LIST)
    data = body.model_dump()
    data["steps"] = _norm_steps(body.steps)
    for k, v in data.items():
        setattr(target, k, v)
    db.commit()
    return _cost_json(target)


@router.delete("/cost-items/{item_id}")
def delete_cost_item(item_id: int, snapshot_id: int | None = None,
                     db: Session = Depends(get_db)):
    c = db.get(M.ProjectCostItem, item_id)
    if c is None:
        raise HTTPException(404, "item not found")
    snap = _cost_snapshot(db, c.project_id, snapshot_id)
    rev, _, cost_map = cost_state.revision_for_edit(db, c.project_id, snap)
    target = c if c.revision_id == rev.id else cost_map.get(c.id)
    if target is None:
        raise HTTPException(409, _STALE_LIST)
    db.delete(target)
    db.commit()
    return {"deleted": item_id}


# -------------------------------------------------------------------- notes
# Notes are project-scoped and ALWAYS all returned — never filtered by the
# selected revision. snapshot_id at creation only records the commit context.

class NoteIn(BaseModel):
    body: str
    author: str = "user"
    snapshot_id: int | None = None


def _note_json(n: M.ProjectNote) -> dict:
    return {
        "id": n.id, "author": n.author, "body": n.body,
        "sha": n.sha, "ref_name": n.ref_name,
        "created_at": n.created_at.isoformat(),
    }


@router.get("/projects/{project_id}/notes")
def list_notes(project_id: int, db: Session = Depends(get_db)):
    _project(db, project_id)
    rows = (
        db.query(M.ProjectNote).filter_by(project_id=project_id)
        .order_by(M.ProjectNote.created_at).all()
    )
    return [_note_json(n) for n in rows]


@router.post("/projects/{project_id}/notes")
def add_note(project_id: int, body: NoteIn, db: Session = Depends(get_db)):
    _project(db, project_id)
    text = body.body.strip()
    if not text:
        raise HTTPException(422, "note must not be empty")
    sha = ref_name = ""
    if body.snapshot_id is not None:
        snap = db.get(M.ProjectSnapshot, body.snapshot_id)
        if snap is not None and snap.project_id == project_id:
            sha, ref_name = snap.sha, snap.ref_name
    n = M.ProjectNote(project_id=project_id, author=body.author.strip() or "user",
                      body=text, sha=sha, ref_name=ref_name)
    db.add(n)
    db.flush()
    audit(db, "project.note.add", "project_note", n.id, {"project_id": project_id})
    db.commit()
    return _note_json(n)


@router.delete("/project-notes/{note_id}")
def delete_note(note_id: int, db: Session = Depends(get_db)):
    n = db.get(M.ProjectNote, note_id)
    if n is None:
        raise HTTPException(404, "note not found")
    db.delete(n)
    db.commit()
    return {"deleted": note_id}


# --------------------------------------------------------------- where-used

@router.get("/components/{comp_id}/where-used")
def where_used(comp_id: int, db: Session = Depends(get_db)):
    """Projects whose latest ready snapshot uses this component."""
    if db.get(M.Component, comp_id) is None:
        raise HTTPException(404, "component not found")
    out = []
    for p in db.query(M.Project).order_by(M.Project.name).all():
        latest = (
            db.query(M.ProjectSnapshot)
            .filter_by(project_id=p.id, status="ready")
            .order_by(M.ProjectSnapshot.created_at.desc())
            .first()
        )
        if latest is None:
            continue
        lines = (
            db.query(M.SnapshotBomLine)
            .filter_by(snapshot_id=latest.id, component_id=comp_id)
            .all()
        )
        if not lines:
            continue
        out.append(
            {
                "project_id": p.id,
                "project_name": p.name,
                "snapshot_id": latest.id,
                "ref": latest.ref_name,
                "sha": latest.sha,
                "usages": [
                    {"board": li.board, "variant": li.variant, "refs": li.refs,
                     "qty": li.qty, "dnp": li.dnp}
                    for li in lines
                ],
            }
        )
    return out


# ---------------------------------------------------------------------- FX

class RateIn(BaseModel):
    currency: str
    rate_usd: float
    # "manual" pins the rate; "auto" hands it back to the daily refresh
    source: str = "manual"


@router.get("/fx")
def list_rates(db: Session = Depends(get_db)):
    rows = db.query(M.ExchangeRate).order_by(M.ExchangeRate.currency).all()
    return [
        {"currency": r.currency, "rate_usd": r.rate_usd, "source": r.source,
         "updated_at": r.updated_at.isoformat()}
        for r in rows
    ]


@router.post("/fx/refresh")
def refresh_rates(db: Session = Depends(get_db)):
    try:
        return fx.refresh_rates(db)
    except Exception as e:
        raise HTTPException(502, f"rate fetch failed: {e}") from e


@router.put("/fx")
def set_rate(body: RateIn, db: Session = Depends(get_db)):
    cur = body.currency.strip().upper()
    if not cur or body.rate_usd <= 0:
        raise HTTPException(422, "currency and a positive rate_usd are required")
    if body.source not in ("manual", "auto"):
        raise HTTPException(422, "source must be manual or auto")
    row = db.query(M.ExchangeRate).filter_by(currency=cur).first()
    if row is None:
        row = M.ExchangeRate(currency=cur, rate_usd=body.rate_usd, source=body.source)
        db.add(row)
    else:
        row.rate_usd = body.rate_usd
        row.source = body.source
        row.updated_at = utcnow()
    fx.record_rate_history(db, cur, body.rate_usd)
    db.commit()
    return {"currency": cur, "rate_usd": body.rate_usd, "source": body.source}


# ------------------------------------------------------------ price ladders

@router.get("/components/{comp_id}/price-points")
def list_price_points(comp_id: int, db: Session = Depends(get_db)):
    if db.get(M.Component, comp_id) is None:
        raise HTTPException(404, "component not found")
    rows = (
        db.query(M.ComponentPricePoint).filter_by(component_id=comp_id)
        .order_by(M.ComponentPricePoint.qty_from).all()
    )
    supply = db.query(M.ComponentSupply).filter_by(component_id=comp_id).first()
    private = db.query(M.JlcStockItem).filter_by(component_id=comp_id).first()
    return {
        "points": [
            {"id": p.id, "source": p.source, "qty_from": p.qty_from, "unit_price": p.unit_price,
             "currency": p.currency, "updated_at": p.updated_at.isoformat()}
            for p in rows
        ],
        # Three DISTINCT pools: stock = LCSC retail, jlc_stock = JLCPCB
        # assembly parts, private_qty = the user's own JLC library.
        "supply": {
            "stock": supply.stock, "jlc_stock": supply.jlc_stock,
            "moq": supply.moq, "order_multiple": supply.order_multiple,
            "checked_at": supply.checked_at.isoformat() if supply.checked_at else None,
        } if supply else None,
        "private_qty": private.qty if private else 0,
    }


class PricePointIn(BaseModel):
    qty_from: int
    unit_price: float
    currency: str = "USD"
    source: str = "Manual"


@router.put("/components/{comp_id}/price-points")
def set_price_points(comp_id: int, points: list[PricePointIn], db: Session = Depends(get_db)):
    """Replaces all user-owned points (manual ladder) — JLCPCB and LCSC rows
    stay robot-managed."""
    if db.get(M.Component, comp_id) is None:
        raise HTTPException(404, "component not found")
    # capture the pre-change state first (no-op when already recorded) so the
    # history timeline keeps what was in effect before this edit
    ladder.record_price_history(db, comp_id)
    db.query(M.ComponentPricePoint).filter(
        M.ComponentPricePoint.component_id == comp_id,
        M.ComponentPricePoint.source.notin_(ladder.AUTO_SOURCES),
    ).delete(synchronize_session=False)
    for pt in points:
        if pt.source.strip() in ladder.AUTO_SOURCES:
            raise HTTPException(422, f"source {pt.source.strip()} is reserved for the auto-refresher")
        if pt.qty_from < 1 or pt.unit_price < 0:
            raise HTTPException(422, "qty_from must be >=1 and unit_price >=0")
        db.add(
            M.ComponentPricePoint(
                component_id=comp_id, source=pt.source.strip() or "Manual",
                qty_from=pt.qty_from, unit_price=pt.unit_price,
                currency=pt.currency.strip().upper() or "USD", updated_at=utcnow(),
            )
        )
    ladder.record_price_history(db, comp_id)
    db.commit()
    return list_price_points(comp_id, db)


@router.post("/components/{comp_id}/price-points/refresh")
def refresh_price_points(comp_id: int, db: Session = Depends(get_db)):
    comp = db.get(M.Component, comp_id)
    if comp is None:
        raise HTTPException(404, "component not found")
    cv = next((v for v in comp.versions if v.id == comp.current_version_id), None)
    lcsc = ladder.lcsc_part_of(cv) if cv else ""
    if not lcsc:
        raise HTTPException(422, "component has no LCSC Part")
    if not ladder.refresh_component(db, comp_id, lcsc):
        raise HTTPException(502, "neither JLCPCB nor LCSC returned a price ladder")
    return list_price_points(comp_id, db)
