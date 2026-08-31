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

import asyncio
import json

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import SessionLocal, get_db
from ..services import gitrepo, sch_lib, sim_example, sim_run
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
    """A run has no sheet: it is always the whole simulation project, from its
    root, harness included. See sim_run.run."""

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


# --------------------------------------------------------------- scenarios

@router.get("/snapshot/{snapshot_id}/{board}/scenarios")
def snapshot_scenarios(snapshot_id: int, board: str, db: Session = Depends(get_db)):
    return _scenarios(_snapshot_source(db, snapshot_id, board))


@router.get("/upload/{upload_id}/scenarios")
def upload_scenarios(upload_id: str):
    return _scenarios(_upload_source(upload_id))


def _scenarios(src: SimSource) -> dict:
    """The runs this harness offers, read off its own text items.

    A harness writes its scenario as SPICE text beside the circuit. Listed as
    a menu it is a set of runs; left as a wall of text it is something the
    user is asked to take on faith before pressing Run."""
    try:
        return sim_run.scenarios(src)
    except SimSourceError as e:
        raise HTTPException(422, str(e)) from e
    except (OSError, OpError) as e:
        raise HTTPException(502, f"could not read the harness: {e}") from e


# ------------------------------------------------------------------ drawing

class SketchRequest(BaseModel):
    """A schematic drawn in the browser. Deliberately loose: the writer is the
    thing that decides what is valid, and it says so by name."""

    name: str = "sketch"
    uuid: str = ""
    paper: str = "A4"
    symbols: list[dict] = []
    wires: list[dict] = []
    labels: list[dict] = []
    texts: list[dict] = []
    junctions: list[list[float]] = []


@router.get("/palette")
def palette():
    """The parts a schematic drawn from scratch starts with, with the graphics
    to draw each one. They are real KiCad symbol definitions, so the file the
    editor saves opens in KiCad."""
    return sch_lib.palette()


@router.post("/sketch")
def save_sketch(body: SketchRequest, id: str = ""):
    """Save a drawn schematic as a real `.kicad_sch` and make it runnable.

    The answer is an upload id, which is the source kind the rest of the
    simulator already understands — so a circuit drawn here runs through
    exactly the same pipeline as one drawn in KiCad. Pass `id` to rewrite a
    sketch in place: the editor saves on every pause in typing, and a new
    source per keystroke would fill the disk."""
    try:
        return sim_run.store_sketch(body.model_dump(), upload_id=id)
    except SimSourceError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/example")
def save_example():
    """A worked circuit, saved as a sketch and returned like any other.

    An empty sheet teaches nothing, and the parts that carry a model — the
    op-amp, the inverters, the gate, the flip-flop — are the ones nobody
    guesses how to wire. This is that circuit, and it is an ORDINARY sketch:
    the user edits and re-runs it in place, and nothing downstream knows it
    came from here."""
    try:
        return sim_run.store_sketch(sim_example.document())
    except SimSourceError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/upload/{upload_id}/sketch")
def get_sketch(upload_id: str):
    """The document a sketch was drawn from, for reopening it in the editor."""
    doc = sim_run.read_sketch(upload_id)
    if doc is None:
        raise HTTPException(404, "this source was not drawn in the editor")
    return doc


# -------------------------------------------------------------------- theme

@router.get("/theme")
def theme():
    """The schematic palette. The browser draws schematics itself, and this is
    the same theme file kicad-cli renders the project's schematic tab with, so
    both views show one colour scheme."""
    return sim_run.schematic_theme()


# ------------------------------------------------------------------ projects

@router.get("/snapshot/{snapshot_id}/projects")
def snapshot_projects(snapshot_id: int, db: Session = Depends(get_db)):
    """Which KiCad projects this commit holds, and which of them are
    simulation harnesses. A design repository keeps one `_sim` project per
    block it exercises, so this is the list a simulator page opens with."""
    snap = db.get(M.ProjectSnapshot, snapshot_id)
    if snap is None:
        raise HTTPException(404, "snapshot not found")
    try:
        gitrepo.materialize(snap.project_id, snap.sha)
    except (OSError, gitrepo.GitError):
        pass  # the name-based hint still works without a checkout
    return {"projects": sim_run.snapshot_projects(snap)}


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


# --------------------------------------------------------------------- live

@router.websocket("/live")
async def sim_live(ws: WebSocket):
    """Relay to the render container's live session.

    The API owns the gate and the source lookup; the render container owns the
    solver. Nothing here reads the simulation — it moves frames, so a change
    to what a frame carries needs no edit on this side.

    The first message names the source the way the REST calls do
    (`{"kind":"snapshot","snapshot_id":13,"board":"SAFETY_sim", …}`); it is
    replaced with a server-resolved path before it reaches the render service,
    so a client can never point a session at an arbitrary file.
    """
    await ws.accept()
    try:
        start = json.loads(await ws.receive_text())
    except (ValueError, WebSocketDisconnect):
        await ws.close(code=1003)
        return

    db = SessionLocal()
    try:
        if start.get("kind") == "upload":
            src = sim_run.upload_source(str(start.get("upload_id", "")))
        else:
            snap = db.get(M.ProjectSnapshot, int(start.get("snapshot_id", 0)))
            board = next(
                (b for b in (snap.boards or []) if b.get("name") == start.get("board")),
                None,
            ) if snap else None
            if board is None:
                raise SimSourceError("no such snapshot or board")
            src = sim_run.snapshot_source(snap, board)
        path = sim_run.live_target(src)
    except (SimSourceError, ValueError, TypeError) as e:
        await ws.send_text(json.dumps({"ev": "error", "message": str(e)}))
        await ws.close()
        return
    finally:
        db.close()

    url = settings.render_url.replace("http://", "ws://").replace("https://", "wss://")
    try:
        import websockets  # noqa: PLC0415 - only this route needs it

        async with websockets.connect(f"{url}/sim/live", max_size=None) as upstream:
            await upstream.send(json.dumps({**start, "path": path}))

            async def down() -> None:
                async for frame in upstream:
                    if isinstance(frame, bytes):
                        await ws.send_bytes(frame)
                    else:
                        await ws.send_text(frame)

            async def up() -> None:
                while True:
                    await upstream.send(await ws.receive_text())

            done, pending = await asyncio.wait(
                [asyncio.create_task(down()), asyncio.create_task(up())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001 - the socket must close cleanly whatever happens
        try:
            await ws.send_text(json.dumps({"ev": "error", "message": f"{type(e).__name__}: {e}"}))
        except RuntimeError:
            pass
    finally:
        try:
            await ws.close()
        except RuntimeError:
            pass


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
            src, control=body.control, analysis=body.analysis, timeout=body.timeout,
        )
    except SimSourceError as e:
        raise HTTPException(422, str(e)) from e
    except (OpError, RuntimeError) as e:
        # A refused control block, a circuit ngspice cannot parse and a
        # timeout all land here. The message is the ngspice log tail, which is
        # the only thing that says which line was wrong.
        raise HTTPException(422, f"simulation failed: {e}") from e
    return Response(content=data, media_type="application/octet-stream")
