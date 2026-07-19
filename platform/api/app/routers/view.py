"""File-viewer support endpoints.

The web viewer renders PDF/STEP/3MF/WRL/DXF entirely in the browser; DWG is
the one format with no browser-side parser, so it is converted to DXF here
with LibreDWG's dwg2dxf (optional dependency — capability is reported so the
UI can fall back to a download link with instructions).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.datasheet_store import current_version

router = APIRouter(prefix="/api/view", tags=["view"])

_DS_FILE_RE = re.compile(r"^/api/datasheets/(\d+)/file$")
_DS_VERSION_FILE_RE = re.compile(r"^/api/datasheets/(\d+)/versions/(\d+)/file$")
_MIRROR_RE = re.compile(r"^/files/(.+)$")


def _dwg2dxf_bin() -> str | None:
    return shutil.which("dwg2dxf")


@router.get("/capabilities")
def capabilities():
    return {"dwg_convert": _dwg2dxf_bin() is not None}


def _load_bytes(src: str, db: Session) -> bytes:
    """Resolve a same-origin path to its bytes. Only our own datasheet-file
    endpoints and the /files mirror are accepted — no external URLs."""
    m = _DS_FILE_RE.match(src)
    if m:
        ds = db.get(M.Datasheet, int(m.group(1)))
        cur = current_version(ds) if ds else None
        if cur is None:
            raise HTTPException(404, "datasheet file not found")
        return cur.data
    m = _DS_VERSION_FILE_RE.match(src)
    if m:
        ds = db.get(M.Datasheet, int(m.group(1)))
        v = None
        if ds is not None:
            no = int(m.group(2))
            v = next((x for x in ds.versions if x.version_no == no), None)
        if v is None:
            raise HTTPException(404, "datasheet version not found")
        return v.data
    m = _MIRROR_RE.match(src)
    if m:
        root = Path(settings.mirror_dir).resolve()
        target = (root / m.group(1)).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise HTTPException(404, "mirror file not found")
        return target.read_bytes()
    raise HTTPException(422, "src must be a same-origin /api/datasheets/... or /files/... path")


@router.get("/dwg2dxf")
def dwg_to_dxf(src: str, db: Session = Depends(get_db)):
    """Convert a stored DWG to DXF for the browser viewer."""
    data = _load_bytes(src, db)
    binpath = _dwg2dxf_bin()
    if binpath is None:
        raise HTTPException(
            501,
            "DWG conversion unavailable — install LibreDWG "
            "(macOS: brew install libredwg; Docker image builds it in)",
        )
    with tempfile.TemporaryDirectory() as td:
        infile = Path(td) / "in.dwg"
        outfile = Path(td) / "out.dxf"
        infile.write_bytes(data)
        proc = subprocess.run(
            [binpath, "-y", "-o", str(outfile), str(infile)],
            capture_output=True,
            timeout=120,
        )
        if not outfile.is_file() or outfile.stat().st_size == 0:
            detail = proc.stderr.decode(errors="replace")[:400] or f"exit code {proc.returncode}"
            raise HTTPException(422, f"dwg2dxf failed: {detail}")
        return Response(
            content=outfile.read_bytes(),
            media_type="image/vnd.dxf",
            headers={"Content-Disposition": 'inline; filename="converted.dxf"'},
        )
