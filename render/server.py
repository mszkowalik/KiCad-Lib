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
import os
import re
import subprocess
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from project_ops import OpError, run_op
from pydantic import BaseModel

KICAD_CLI = os.environ.get("KICAD_CLI", "kicad-cli")
NGSPICE = os.environ.get("NGSPICE", "ngspice")
BOARD_TEMPLATE = Path(__file__).parent / "board_template.kicad_pcb"
# Project checkouts arrive on the shared (read-only) api data volume.
DATA_ROOT = Path(os.environ.get("DATA_ROOT", "/data"))

app = FastAPI(title="kicad-render")

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
