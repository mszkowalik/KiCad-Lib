"""3D model file storage: content-addressed STEP/WRL blobs referenced by
footprints' `(model "${SEVENSIGMA_DIR}/3DModels/<rel_path>" ...)` entries.

Unlike components/symbols/footprints, `models3d` carries no version/draft
gate -- it is static asset content, the same treatment the old YAML importer
gave it (see services/importer.py). A successful upload here is therefore
live immediately: no approval step, matching how list_models3d has always
been read-only-but-ungated for Jaravis. See services/mirror.py for how a row
reaches the file mirror.
"""
from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import models as M
from ..config import settings
from ..db import get_db
from ..services.mirror import update_mirror_model3d
from .util import audit

router = APIRouter(prefix="/api/models3d", tags=["models3d"])

MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # sanity cap, not a real limit on CAD file size
ALLOWED_SUFFIXES = (".step", ".stp", ".wrl")


@router.get("")
def list_models3d(query: str = "", limit: int = 100, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 300))
    q = db.query(M.Model3D)
    if query:
        q = q.filter(M.Model3D.rel_path.ilike(f"%{query}%"))
    rows = q.order_by(M.Model3D.rel_path).limit(limit).all()
    return {"total_matching": q.count(),
            "models": [{"rel_path": r.rel_path, "size_bytes": r.size_bytes, "sha256": r.sha256}
                       for r in rows]}


@router.post("/upload")
async def upload_model3d(rel_path: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Create or replace a 3D model, content-addressed by `rel_path` (mirrors
    3DModels/<rel_path> exactly, matching what a footprint's `(model ...)`
    node references). Re-uploading the same rel_path replaces its content --
    that is how a corrected STEP file gets fixed, not a new row."""
    rel_path = rel_path.strip().lstrip("/")
    if not rel_path:
        raise HTTPException(422, "rel_path is required")
    if ".." in rel_path.split("/"):
        raise HTTPException(422, "rel_path must not contain '..'")
    if not rel_path.lower().endswith(ALLOWED_SUFFIXES):
        raise HTTPException(422, f"rel_path must end in one of {ALLOWED_SUFFIXES}")

    data = await file.read()
    if not data:
        raise HTTPException(422, "uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file exceeds {MAX_UPLOAD_BYTES} bytes")

    sha = hashlib.sha256(data).hexdigest()
    existing = db.query(M.Model3D).filter_by(rel_path=rel_path).first()
    if existing is None:
        m = M.Model3D(rel_path=rel_path, sha256=sha, size_bytes=len(data), data=data)
        db.add(m)
        action = "model3d.create"
    else:
        existing.sha256 = sha
        existing.size_bytes = len(data)
        existing.data = data
        m = existing
        action = "model3d.replace"
    db.flush()
    audit(db, action, "model3d", m.id, details={"rel_path": rel_path, "size_bytes": len(data)})
    db.commit()

    mirror_result = update_mirror_model3d(settings, m)
    return {"ok": True, "rel_path": m.rel_path, "sha256": m.sha256, "size_bytes": m.size_bytes,
            "mirror": mirror_result}
