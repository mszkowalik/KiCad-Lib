"""KiCad client integrations: the PCM repository (install the library from
KiCad's Plugin and Content Manager), the .kicad_httplib config (built from
the configured public URL + token) and the legacy kicadlib sync CLI."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ..config import settings
from ..services import pcm

router = APIRouter(prefix="/api/kicad", tags=["kicad"])

_CLI_PATH = Path(__file__).parents[2] / "cli" / "kicadlib.py"


@router.get("/config")
def config():
    """What the UI shows on the KiCad page."""
    return {
        "public_base_url": settings.public_base_url,
        "httplib_root_url": f"{settings.public_base_url}/kicad/",
        "mirror_url": f"{settings.public_base_url}/files/",
        "pcm_repo_url": f"{settings.public_base_url}/api/kicad/pcm/repository.json",
        "token_hint": settings.httplib_token[:4] + "…" if settings.httplib_token else "",
    }


# ------------------------------------------------------------ PCM repository

@router.get("/pcm/repository.json")
def pcm_repository():
    """KiCad PCM repository descriptor — paste this URL into Preferences >
    Plugin and Content Manager > Manage Repositories. Unauthenticated, like
    the file mirror (PCM cannot send tokens)."""
    meta = pcm.ensure_built()
    if meta is None:
        raise HTTPException(503, "file mirror not built yet — run an import first")
    return meta["repository"]


class ModelsDeltaIn(BaseModel):
    """Mirror-relative 3D model paths (as listed in /files/manifest.json)."""

    paths: list[str]


DELTA_MAX_FILES = 500
DELTA_MAX_BYTES = 400 * (1 << 20)


@router.post("/pcm/models-delta")
def pcm_models_delta(body: ModelsDeltaIn):
    """Incremental updates for the sync plugin: a compressed batch of just
    the requested 3D model files (LZMA — ~2x smaller than deflate on STEP
    text), so adding one model never re-downloads the 300+ MB full package.
    Oversized deltas get 413 — the plugin falls back to the full zip."""
    if not body.paths:
        raise HTTPException(422, "no paths requested")
    if len(body.paths) > DELTA_MAX_FILES:
        raise HTTPException(413, "delta too large — download the full models package")
    root = settings.mirror_dir
    buf = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_LZMA) as zf:
        for rel in body.paths:
            if not rel.startswith("3DModels/") or ".." in rel:
                raise HTTPException(422, f"invalid path: {rel}")
            f = root / rel
            if not f.is_file():
                raise HTTPException(404, f"not in mirror: {rel}")
            total += f.stat().st_size
            if total > DELTA_MAX_BYTES:
                raise HTTPException(413, "delta too large — download the full models package")
            zf.write(f, rel)
    return Response(content=buf.getvalue(), media_type="application/zip")


@router.get("/pcm/{filename}")
def pcm_artifact(filename: str):
    """Package index + zips referenced by repository.json."""
    meta = pcm.ensure_built()
    if meta is None:
        raise HTTPException(503, "file mirror not built yet — run an import first")
    path = pcm.artifact_path(filename)
    if path is None:
        raise HTTPException(404, "no such PCM artifact (repository may have been rebuilt — refresh)")
    media = "application/json" if path.suffix == ".json" else "application/zip"
    return FileResponse(path, media_type=media, filename=path.name)


@router.get("/httplib-file")
def httplib_file():
    """The ready-to-use KiCad HTTP library config. Add it in KiCad under
    Preferences > Manage Symbol Libraries. root_url follows PUBLIC_BASE_URL
    (localhost now, e.g. https://disfunction.cc/lib later)."""
    payload = {
        "meta": {"version": 1.0},
        "name": "7Sigma Library (platform)",
        "description": "Live part catalog from the Project Management Platform. "
                       "Symbols/footprints must be synced locally (kicadlib sync).",
        "source": {
            "type": "REST_API",
            "api_version": "v1",
            "root_url": f"{settings.public_base_url}/kicad/",
            "token": settings.httplib_token,
        },
    }
    return Response(
        content=json.dumps(payload, indent=4),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="7Sigma.kicad_httplib"'},
    )


@router.get("/sync-script")
def sync_script():
    return Response(
        content=_CLI_PATH.read_text(encoding="utf-8"),
        media_type="text/x-python",
        headers={"Content-Disposition": 'attachment; filename="kicadlib.py"'},
    )
