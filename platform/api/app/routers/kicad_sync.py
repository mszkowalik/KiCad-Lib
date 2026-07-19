"""KiCad client downloads: the .kicad_httplib config (built from the
configured public URL + token) and the kicadlib sync CLI."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import Response

from ..config import settings

router = APIRouter(prefix="/api/kicad", tags=["kicad"])

_CLI_PATH = Path(__file__).parents[2] / "cli" / "kicadlib.py"


@router.get("/config")
def config():
    """What the UI shows on the KiCad page."""
    return {
        "public_base_url": settings.public_base_url,
        "httplib_root_url": f"{settings.public_base_url}/kicad/",
        "mirror_url": f"{settings.public_base_url}/files/",
        "token_hint": settings.httplib_token[:4] + "…" if settings.httplib_token else "",
    }


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
