"""KiCad client integrations: the PCM repository (install the library from
KiCad's Plugin and Content Manager), the .kicad_httplib config (built from
the configured public URL + token) and the legacy kicadlib sync CLI."""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services import auth, pcm

router = APIRouter(prefix="/api/kicad", tags=["kicad"])

_CLI_PATH = Path(__file__).parents[2] / "cli" / "kicadlib.py"


def caller_token(request: Request, db: Session) -> str:
    """The API token this request should be personalised for.

    Two callers, two sources. KiCad arrives with `?t=<token>` and that value is
    used verbatim — it is already what the client holds. A browser arrives with
    a session cookie, and gets the signed-in user's first live token, which is
    what makes the Setup page able to show a copy-paste URL without the user
    ever handling the secret.

    Returns "" when neither applies, and every caller then falls back to the
    shared, unpersonalised artifacts.
    """
    supplied = request.query_params.get("t", "")
    if supplied:
        return supplied
    user = getattr(request.state, "user", None)
    if user is None:
        return ""
    tok = (
        db.query(M.ApiToken)
        .filter(M.ApiToken.user_id == user.id, M.ApiToken.revoked_at.is_(None))
        .order_by(M.ApiToken.id)
        .first()
    )
    return auth.token_cleartext(tok) if tok is not None else ""


@router.get("/config")
def config(request: Request, db: Session = Depends(get_db)):
    """What the UI shows on the Setup page.

    `pcm_repo_url` and `httplib_url` are PERSONAL when a signed-in user has a
    token — they carry it, so the Setup page shows a link the user can paste
    into KiCad directly.
    """
    token = caller_token(request, db)
    base = settings.public_base_url.rstrip("/")
    suffix = f"?t={token}" if token else ""
    return {
        "public_base_url": settings.public_base_url,
        "httplib_root_url": f"{base}/kicad/",
        "mirror_url": f"{base}/files/",
        "pcm_repo_url": f"{base}/api/kicad/pcm/repository.json{suffix}",
        "httplib_url": f"{base}/api/kicad/httplib-file{suffix}",
        "personalised": bool(token),
        "token_hint": (token[:12] + "…") if token else "",
    }


# ------------------------------------------------------------ PCM repository

@router.get("/pcm/repository.json")
def pcm_repository(request: Request, db: Session = Depends(get_db)):
    """KiCad PCM repository descriptor — paste this URL into Preferences >
    Plugin and Content Manager > Manage Repositories.

    Personal: called as `repository.json?t=<token>` it returns a descriptor
    whose every URL carries the same token, and whose plugin package is built
    with that token inside it. One paste installs the library, the models and
    an already-authenticated sync plugin.

    PCM sends no headers, so the query parameter is the only credential it can
    carry. `authgate.AuthGate` allows `?t=` on this path for exactly that
    reason — see `_QUERY_TOKEN_PATHS` there.
    """
    meta = pcm.ensure_built()
    if meta is None:
        raise HTTPException(503, "file mirror not built yet — run an import first")
    # Per-user body, and it publishes the hash of a document that changes on
    # every rebuild — never let anything between here and KiCad hold on to it.
    return JSONResponse(pcm.personal_repository(meta, pcm_token_or_empty(request, db)),
                        headers={"Cache-Control": "no-store"})


def pcm_token_or_empty(request: Request, db: Session) -> str:
    """`caller_token`, but never raises — a malformed token must degrade to the
    shared artifacts rather than 500 a KiCad client mid-install."""
    try:
        return caller_token(request, db)
    except Exception:  # noqa: BLE001 — personalisation is never worth an outage
        return ""


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
def pcm_artifact(filename: str, request: Request, db: Session = Depends(get_db)):
    """Package index + zips referenced by repository.json.

    The package index is served from MEMORY when the request carries a token,
    not from the file on disk: its download URLs and the plugin's sha256 differ
    per user, and the bytes must match the hash `repository.json` just
    published or PCM rejects the whole repository.
    """
    meta = pcm.ensure_built()
    if meta is None:
        raise HTTPException(503, "file mirror not built yet — run an import first")
    token = pcm_token_or_empty(request, db)
    if filename == meta["packages_file"] and token:
        # Per-user body under a shared URL — a cache between here and KiCad
        # must never hand one user's index to another, or reuse it after a
        # rebuild changed the hashes it publishes.
        return Response(content=pcm.personal_packages(meta, token),
                        media_type="application/json",
                        headers={"Cache-Control": "no-store"})
    path = pcm.artifact_path(filename)
    if path is None:
        raise HTTPException(404, "no such PCM artifact (repository may have been rebuilt — refresh)")
    media = "application/json" if path.suffix == ".json" else "application/zip"
    # A zip name carries its content hash and its bytes are reproducible
    # (pcm.ZIP_EPOCH), so the URL is immutable and worth caching at the edge —
    # the models package is ~250 MB. The index is not.
    cache = "public, max-age=31536000, immutable" if path.suffix == ".zip" else "no-store"
    return FileResponse(path, media_type=media, filename=path.name,
                        headers={"Cache-Control": cache})


@router.get("/httplib-file")
def httplib_file(request: Request, db: Session = Depends(get_db)):
    """The ready-to-use KiCad HTTP library config. Add it in KiCad under
    Preferences > Manage Symbol Libraries. root_url follows PUBLIC_BASE_URL
    (localhost now, e.g. https://disfunction.cc/lib later).

    The `token` field is the CALLER'S OWN — the signed-in user's when a browser
    downloads it, the supplied one when the link carries `?t=`. It falls back
    to the shared `httplib_token` only when neither exists, which is the local
    development case.

    KiCad stores this file in the clear. That is accepted: it is a read
    credential for the part catalog on the user's own machine.
    """
    token = pcm_token_or_empty(request, db) or settings.httplib_token
    payload = {
        "meta": {"version": 1.0},
        "name": "7Sigma Library (platform)",
        "description": "Live part catalog from the Project Management Platform. "
                       "Symbols/footprints must be synced locally (kicadlib sync).",
        "source": {
            "type": "REST_API",
            "api_version": "v1",
            "root_url": f"{settings.public_base_url}/kicad/",
            "token": token,
            # KiCad caches the catalog in-process for these many seconds. Its
            # own defaults (600 / 30) expire the category part lists every 10
            # minutes, and re-filling them costs one request per category.
            "timeout_categories_seconds": settings.httplib_timeout_categories_s,
            "timeout_parts_seconds": settings.httplib_timeout_parts_s,
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
