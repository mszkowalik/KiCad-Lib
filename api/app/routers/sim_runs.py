"""Circuit simulation: sheet trees, overlay geometry and scenario runs.

Two source kinds, one pipeline (docs/simulator/design.md). A snapshot source
simulates a board's schematic at an ingested commit, so a reviewer can open a
project, pick a commit and watch the circuit it describes; an upload source
simulates a `.kicad_sch` the user dropped in the browser, which is how a
schematic drawn in KiCad gets here without a repository.

The run itself returns a binary 7SIM payload (see services/sim_spice.py), not
JSON: a transient of a few thousand points across a dozen vectors is a wall of
floats, and float32 arrays are what the plotter wants anyway.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..db import get_db
from ..services import sim_run
from ..services.project_ops import OpError
from ..services.sim_run import SimSource, SimSourceError

router = APIRouter(prefix="/api/sim", tags=["simulation"])


def _snapshot_source(db: Session, snapshot_id: int, board: str) -> SimSource:
    snap = db.get(M.ProjectSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(404, "snapshot not found")
    for b in snap.boards or []:
        if b.get("name") == board:
            try:
                return sim_run.snapshot_source(snap, b)
            except SimSourceError as e:
                raise HTTPException(422, str(e)) from e
    raise HTTPException(404, f"snapshot has no board '{board}'")


def _upload_source(upload_id: str) -> SimSource:
    try:
        return sim_run.upload_source(upload_id)
    except SimSourceError as e:
        raise HTTPException(404, str(e)) from e


class RunRequest(BaseModel):
    # Which sheet is the top of the simulated circuit ("" = the source root).
    sheet: str = ""
    # None keeps the schematic's own .control block, "" drops it, and any
    # other string replaces it — the scenario editor sends the third form.
    control: str | None = None
    # Replaces the schematic's own .tran/.ac/... directives when set.
    analysis: str = ""
    timeout: int = 0


# ------------------------------------------------------------------ uploads

@router.post("/uploads")
async def create_upload(files: list[UploadFile] = File(...), root: str = Form("")):
    """Store a dropped sheet set. Send every sub-sheet and every model file
    the design references relatively, or the netlist will not resolve them."""
    payload = [(f.filename or "", await f.read()) for f in files]
    try:
        meta = sim_run.store_upload(payload, root_name=root)
    except SimSourceError as e:
        raise HTTPException(422, str(e)) from e
    return {"id": meta["id"], "root": meta["root"], "files": meta["files"]}


# ------------------------------------------------------------------- sheets

@router.get("/snapshot/{snapshot_id}/{board}/sheets")
def snapshot_sheets(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    return _sheets(_snapshot_source(db, snapshot_id, board))


@router.get("/upload/{upload_id}/sheets")
def upload_sheets(upload_id: str):
    return _sheets(_upload_source(upload_id))


def _sheets(src: SimSource) -> dict:
    try:
        return {"source": {"kind": src.kind, "label": src.label}, "sheets": sim_run.sheets(src)}
    except (SimSourceError, OSError) as e:
        raise HTTPException(422, str(e)) from e


# --------------------------------------------------------------------- svg

@router.get("/snapshot/{snapshot_id}/{board}/sheet.svg")
def snapshot_sheet_svg(snapshot_id: int, board: str, sheet: str = "", db: Session = Depends(get_db)):
    return _sheet_svg(_snapshot_source(db, snapshot_id, board), sheet)


@router.get("/upload/{upload_id}/sheet.svg")
def upload_sheet_svg(upload_id: str, sheet: str = ""):
    return _sheet_svg(_upload_source(upload_id), sheet)


def _sheet_svg(src: SimSource, sheet: str) -> Response:
    """The drawing itself — kicad-cli's own render, which the overlay sits on
    top of. Its viewBox is in millimetres and shares the geometry's coordinate
    space, so the two line up with no transform."""
    try:
        data = sim_run.sheet_svg(src, sheet)
    except SimSourceError as e:
        raise HTTPException(422, str(e)) from e
    except (OpError, RuntimeError) as e:
        raise HTTPException(502, f"render failed: {e}") from e
    return Response(content=data, media_type="image/svg+xml")


# ----------------------------------------------------------------- geometry

@router.get("/snapshot/{snapshot_id}/{board}/geometry")
def snapshot_geometry(snapshot_id: int, board: str, sheet: str = "", db: Session = Depends(get_db)):
    return _geometry(_snapshot_source(db, snapshot_id, board), sheet)


@router.get("/upload/{upload_id}/geometry")
def upload_geometry(upload_id: str, sheet: str = ""):
    return _geometry(_upload_source(upload_id), sheet)


def _geometry(src: SimSource, sheet: str) -> dict:
    try:
        return sim_run.geometry(src, sheet)
    except SimSourceError as e:
        raise HTTPException(422, str(e)) from e
    except (OpError, RuntimeError) as e:
        raise HTTPException(502, f"netlist failed: {e}") from e


# ------------------------------------------------------------------ netlist

@router.get("/snapshot/{snapshot_id}/{board}/netlist")
def snapshot_netlist(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    return _netlist(_snapshot_source(db, snapshot_id, board))


@router.get("/upload/{upload_id}/netlist")
def upload_netlist(upload_id: str):
    return _netlist(_upload_source(upload_id))


def _netlist(src: SimSource) -> dict:
    """The SPICE netlist as kicad-cli wrote it, plus the net list the overlay
    matches against. Shown in the UI so a wrong simulation can be read rather
    than guessed at."""
    try:
        spice = sim_run.netlist_spice(src)
        nets = sim_run.netlist_xml(src)
    except SimSourceError as e:
        raise HTTPException(422, str(e)) from e
    except (OpError, RuntimeError) as e:
        raise HTTPException(502, f"netlist failed: {e}") from e
    return {"spice": spice, "nets": nets["nets"]}


# ---------------------------------------------------------------------- run

@router.post("/snapshot/{snapshot_id}/{board}/run")
def snapshot_run(snapshot_id: int, board: str, body: RunRequest, db: Session = Depends(get_db)):
    return _run(_snapshot_source(db, snapshot_id, board), body)


@router.post("/upload/{upload_id}/run")
def upload_run(upload_id: str, body: RunRequest):
    return _run(_upload_source(upload_id), body)


def _run(src: SimSource, body: RunRequest) -> Response:
    try:
        data = sim_run.run(
            src, instance_path=body.sheet, control=body.control,
            analysis=body.analysis, timeout=body.timeout,
        )
    except SimSourceError as e:
        raise HTTPException(422, str(e)) from e
    except (OpError, RuntimeError) as e:
        # A refused control block, a circuit ngspice cannot parse and a
        # timeout all land here. The message is the ngspice log tail, which is
        # the only thing that says which line was wrong.
        raise HTTPException(422, f"simulation failed: {e}") from e
    return Response(content=data, media_type="application/octet-stream")
