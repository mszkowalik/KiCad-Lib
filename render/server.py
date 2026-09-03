"""Tiny render service: wraps kicad-cli exports behind HTTP.

Runs inside the official KiCad Docker image so previews are pixel-exact
KiCad output.
POST /render {kind: symbol|footprint|footprint3d, name, source_text, theme}
  -> SVG (symbol/footprint) or binary GLB board view (footprint3d).
POST /render-project {op, path, ...} -> any project_ops op on a file under
  the shared /data volume, simulation included (op sim_run runs ngspice).
footprint3d needs SEVENSIGMA_DIR pointing at the mounted mirror (3D models);
so does a netlist whose Sim.Library is ${SEVENSIGMA_DIR}/Symbols/7Sigma_sim.sp.
"""
import asyncio
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import sim_spice
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from project_ops import OpError, run_op
from pydantic import BaseModel

KICAD_CLI = os.environ.get("KICAD_CLI", "kicad-cli")
NGSPICE = os.environ.get("NGSPICE", "ngspice")
BOARD_TEMPLATE = Path(__file__).parent / "board_template.kicad_pcb"
# Project checkouts arrive on the shared (read-only) api data volume.
DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))
# A project schematic stores Sim.Library the way the user's KiCad resolves it,
# `${KICAD10_3RD_PARTY}/symbols/…`. The api lays that directory out on the
# shared volume (services/pcm.py: server_pcm_root); kicad-cli reads the
# variable from the environment, exactly as it reads SEVENSIGMA_DIR.
os.environ.setdefault("KICAD10_3RD_PARTY", str(DATA_ROOT / "pcmroot"))

app = FastAPI(title="kicad-render")

WORKER = Path(__file__).parent / "sim_worker.py"
# One live session is one process holding one circuit, so the cap is a real
# resource limit, not a policy. A halted session still owns its memory.
MAX_LIVE_SESSIONS = int(os.environ.get("SIM_MAX_LIVE_SESSIONS", "4"))
# An endless run left by a closed laptop would otherwise solve for ever.
LIVE_IDLE_TIMEOUT_S = float(os.environ.get("SIM_LIVE_IDLE_S", "900"))
# Simulated seconds a live run may reach before it ends on its own.
LIVE_TSTOP_S = float(os.environ.get("SIM_LIVE_TSTOP_S", "1000"))
_live_lock = threading.Lock()
_live_count = 0

_COORD_RE = re.compile(r"\((?:at|start|end|xy|center|mid)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")
_FOOTPRINT_HEADER_RE = re.compile(r'^(\(footprint\s+"[^"]+")')


def build_board_text(footprint_text: str) -> str:
    """Same board wrapper as the API's board3d.py (kept in sync)."""
    template = BOARD_TEMPLATE.read_text(encoding="utf-8")
    fp = _FOOTPRINT_HEADER_RE.sub(r"\1\n\t(at 0 0)", footprint_text.strip(), count=1)
    xs, ys = [0.0], [0.0]
    for m in _COORD_RE.finditer(footprint_text):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    x1, y1, x2, y2 = min(xs) - 1.5, min(ys) - 1.5, max(xs) + 1.5, max(ys) + 1.5
    edges = "\n".join(
        f'\t(gr_line (start {sx} {sy}) (end {ex} {ey}) '
        f'(stroke (width 0.1) (type solid)) (layer "Edge.Cuts"))'
        for sx, sy, ex, ey in ((x1, y1, x2, y1), (x2, y1, x2, y2), (x2, y2, x1, y2), (x1, y2, x1, y1))
    )
    body = "\t" + "\n\t".join(fp.splitlines()) + "\n" + edges + "\n"
    idx = template.rstrip().rfind(")")
    return template[:idx] + body + template[idx:]


class RenderRequest(BaseModel):
    kind: str  # "symbol" | "footprint" | "footprint3d"
    name: str
    source_text: str
    theme: str = ""  # kicad-cli color theme name; "" = default


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/render")
def render(req: RenderRequest):
    if req.kind not in ("symbol", "footprint", "footprint3d"):
        raise HTTPException(422, "kind must be symbol, footprint or footprint3d")
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out = tmp / "out"
        out.mkdir()
        theme_args = ["-t", req.theme] if req.theme else []
        if req.kind == "symbol":
            src = tmp / "render.kicad_sym"
            src.write_text(req.source_text, encoding="utf-8")
            cmd = [KICAD_CLI, "sym", "export", "svg", "-s", req.name, *theme_args, "-o", str(out), str(src)]
        elif req.kind == "footprint":
            pretty = tmp / "render.pretty"
            pretty.mkdir()
            (pretty / f"{req.name}.kicad_mod").write_text(req.source_text, encoding="utf-8")
            cmd = [KICAD_CLI, "fp", "export", "svg", "--fp", req.name, *theme_args, "-o", str(out), str(pretty)]
        else:
            board = tmp / "render.kicad_pcb"
            board.write_text(build_board_text(req.source_text), encoding="utf-8")
            cmd = [
                KICAD_CLI, "pcb", "export", "glb",
                "--subst-models", "--include-tracks", "--include-pads", "--include-zones",
                "--include-silkscreen", "--include-soldermask", "--force",
                "-o", str(out / "render.glb"), str(board),
            ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        want = "*.glb" if req.kind == "footprint3d" else "*.svg"
        outputs = sorted(out.glob(want))
        if proc.returncode != 0 or not outputs:
            raise HTTPException(
                500, f"kicad-cli failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
            )
        media = "model/gltf-binary" if req.kind == "footprint3d" else "image/svg+xml"
        return Response(content=outputs[0].read_bytes(), media_type=media)


# ------------------------------------------------------------- live session

def _claim_session() -> bool:
    global _live_count
    with _live_lock:
        if _live_count >= MAX_LIVE_SESSIONS:
            return False
        _live_count += 1
        return True


def _release_session() -> None:
    global _live_count
    with _live_lock:
        _live_count = max(0, _live_count - 1)


# The model library, as THIS container resolves it. A browser netlist names it
# by token; a real path from a browser is refused outright.
SIM_LIB_PATH = str(DATA_ROOT / "pcmroot/symbols/com_sevensigma_library/7Sigma_sim.sp")
_INCLUDE_RE = re.compile(r"^\s*\.(include|lib)\b", re.IGNORECASE)


def sanitize_browser_netlist(text: str) -> str:
    """A netlist written by the editor, made safe to run.

    Two rules. No `.control` block — live mode never has one, and the banned
    command list exists for a reason. And no `.include`/`.lib` other than the
    sentinel: an include is a file read with the worker's eyes, and the only
    file a sketch may read is the model library, whose path is ours to know.
    """
    body, control = sim_spice.find_control(text)
    if control.strip():
        raise sim_spice.SimError("a live netlist may not carry a control block")
    out = []
    for line in body.splitlines():
        if _INCLUDE_RE.match(line):
            if "%SIGMA_SIM_LIB%" not in line:
                raise sim_spice.SimError("a browser netlist may only include the model library")
            line = line.replace("%SIGMA_SIM_LIB%", SIM_LIB_PATH)
        out.append(line)
    return "\n".join(out)


@app.websocket("/sim/live")
async def sim_live(ws: WebSocket):
    """An endless transient you can watch and poke at.

    The first message names the schematic and what to stream; everything after
    it steers the run. Frames come back exactly as the worker wrote them —
    this endpoint moves bytes and owns the process, and does not decode the
    simulation at all.
    """
    await ws.accept()
    try:
        start = json.loads(await ws.receive_text())
    except (ValueError, WebSocketDisconnect):
        await ws.close(code=1003)
        return

    # A sketch arrives as the netlist itself — the browser wrote it, and
    # skipping the kicad-cli export is most of what makes editing feel
    # instant. A project sheet still arrives as a path and goes through
    # kicad-cli, because that file is not ours to reinterpret.
    browser_netlist = str(start.get("netlist", "") or "")
    src = (DATA_ROOT / str(start.get("path", ""))).resolve()
    if not browser_netlist and (
            not str(src).startswith(str(DATA_ROOT.resolve())) or not src.exists()):
        await ws.send_text(json.dumps({"ev": "error", "message": "no such schematic"}))
        await ws.close()
        return
    if not _claim_session():
        await ws.send_text(json.dumps({
            "ev": "error",
            "message": f"this server already runs {MAX_LIVE_SESSIONS} live simulations",
        }))
        await ws.close()
        return

    proc = None
    try:
        tstep = float(start.get("tstep", 1e-5)) or 1e-5
        if browser_netlist:
            prepared = sanitize_browser_netlist(browser_netlist)
            info = {"unmodelled": []}
        else:
            with tempfile.TemporaryDirectory() as td:
                netlist_bytes, _ = run_op(KICAD_CLI, "sch_spice", src, td, variant=start.get("variant", ""))
            # The schematic's own directives describe a FINITE run; live mode
            # wants one that never ends and reports every device current.
            # A large stop time, not an absurd one. `1e9` produced a run that
            # reported its vectors and then never emitted a single point;
            # 1000 s is what was measured working, and at any speed a person
            # would watch it is days of wall clock — endless in every sense
            # that matters.
            prepared, info = sim_spice.prepare_netlist(
                netlist_bytes.decode("utf-8", "replace"),
                control="", analysis=f".tran {tstep:g} {LIVE_TSTOP_S:g}",
            )
        await ws.send_text(json.dumps({"ev": "netlist", "unmodelled": info["unmodelled"]}))

        proc = subprocess.Popen(
            [sys.executable, str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        _write_frame(proc, {
            "op": "start", "netlist": prepared,
            "speed": start.get("speed", 1e-3),
            "overlay": start.get("overlay", []),
            "scopes": start.get("scopes", []),
            # The scope pixel pitch, so the worker keeps history for every
            # overlay vector from the FIRST point — a trace opened late is
            # seeded with its own past. Dropping this here silently disabled
            # the whole feature: the browser sent it, the worker never saw it.
            "history_span": start.get("history_span", 0),
        })

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=240)
        threading.Thread(target=_pump_worker, args=(proc, loop, queue), daemon=True).start()
        # A worker that dies says why on stderr. Without this the session just
        # goes quiet, which is how an endless run that never started looks.
        threading.Thread(target=_pump_stderr, args=(proc, loop, queue), daemon=True).start()

        async def to_client() -> None:
            while True:
                frame = await queue.get()
                if frame is None:
                    return
                if frame[:1] == b"{":
                    await ws.send_text(frame.decode("utf-8", "replace"))
                else:
                    await ws.send_bytes(frame)

        async def from_client() -> None:
            while True:
                text = await asyncio.wait_for(ws.receive_text(), timeout=LIVE_IDLE_TIMEOUT_S)
                try:
                    cmd = json.loads(text)
                    # A reload carries a fresh browser netlist. Same gate as
                    # the start frame — the sentinel is resolved here, and
                    # anything else that reads a file is refused.
                    if cmd.get("op") == "reload":
                        try:
                            cmd["netlist"] = sanitize_browser_netlist(str(cmd.get("netlist", "")))
                        except sim_spice.SimError as err:
                            await ws.send_text(json.dumps({"ev": "error", "message": str(err)}))
                            continue
                    _write_frame(proc, cmd)
                except (ValueError, OSError):
                    return

        done, pending = await asyncio.wait(
            [asyncio.create_task(to_client()), asyncio.create_task(from_client())],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
    except (OpError, sim_spice.SimError) as e:
        await ws.send_text(json.dumps({"ev": "error", "message": str(e)}))
    except (WebSocketDisconnect, asyncio.TimeoutError, asyncio.CancelledError):
        pass
    except Exception as e:  # noqa: BLE001 - a live session may never take the server with it
        await ws.send_text(json.dumps({"ev": "error", "message": f"{type(e).__name__}: {e}"}))
    finally:
        if proc and proc.poll() is None:
            try:
                _write_frame(proc, {"op": "stop"})
                proc.wait(timeout=3)
            except Exception:  # noqa: BLE001
                proc.kill()
        _release_session()
        try:
            await ws.close()
        except RuntimeError:
            pass


def _write_frame(proc, obj: dict) -> None:
    body = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    proc.stdin.write(struct.pack("<I", len(body)) + body)
    proc.stdin.flush()


def _pump_stderr(proc, loop, queue: asyncio.Queue) -> None:
    for raw in iter(proc.stderr.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip()
        if not line:
            continue
        print(f"sim_worker: {line}", flush=True)
        asyncio.run_coroutine_threadsafe(
            queue.put(json.dumps({"ev": "log", "message": line[:400]}).encode()), loop
        )


def _pump_worker(proc, loop, queue: asyncio.Queue) -> None:
    """Worker stdout -> the event loop. Blocking reads belong on a thread."""
    try:
        while True:
            head = proc.stdout.read(4)
            if len(head) < 4:
                break
            (length,) = struct.unpack("<I", head)
            body = proc.stdout.read(length)
            if len(body) < length:
                break
            # Drop a frame rather than stall the simulation when a slow client
            # cannot keep up: the next one carries the same state anyway.
            if queue.full() and body[:1] != b"{":
                continue
            asyncio.run_coroutine_threadsafe(queue.put(body), loop)
    finally:
        asyncio.run_coroutine_threadsafe(queue.put(None), loop)


class ProjectRenderRequest(BaseModel):
    """op on a project file under the shared /data volume (path is relative
    to it, e.g. checkouts/3/<sha>/pcb/zenith.kicad_pcb). gerber_svg: path is
    a directory and `files` selects layers [{file, color}]."""

    op: str
    path: str
    variant: str = ""
    layer: str = ""
    theme: str = ""
    files: list[dict] | None = None
    # sim_run only: control=None keeps the schematic's own .control block,
    # "" drops it, anything else replaces it; analysis replaces the
    # schematic's own .tran/.ac/... directives.
    control: str | None = None
    analysis: str = ""
    timeout: int = 60


@app.post("/render-project")
def render_project(req: ProjectRenderRequest):
    src = (DATA_ROOT / req.path).resolve()
    if not str(src).startswith(str(DATA_ROOT.resolve())):
        raise HTTPException(422, "path escapes the data root")
    with tempfile.TemporaryDirectory() as td:
        try:
            data, media = run_op(
                KICAD_CLI, req.op, src, td,
                variant=req.variant, layer=req.layer, theme=req.theme, files=req.files,
                control=req.control, analysis=req.analysis,
                ngspice=NGSPICE, timeout=max(5, min(req.timeout, 300)),
            )
        except OpError as e:
            raise HTTPException(500, str(e)) from e
        return Response(content=data, media_type=media)
