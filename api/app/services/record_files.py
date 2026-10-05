"""Files kept as the evidence of a sales invoice or a tax entry (decision 0077).

A supplier document keeps its originals as `RunAttachment` rows; these are the
same thing for the records a company writes itself or is told by its
accountant. A file is added and read, never replaced: a second scan is a second
file, so the first one survives.
"""
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .. import models as M
from . import storage

MAX_MB = 25

#: owner_kind -> the model it points at
OWNERS = {"sales_invoice": M.SalesInvoice, "tax_entry": M.CompanyTaxEntry}


def file_json(f: M.RecordFile) -> dict:
    return {"id": f.id, "owner_kind": f.owner_kind, "owner_id": f.owner_id, "filename": f.filename,
            "content_type": f.content_type, "size_bytes": f.size_bytes, "note": f.note,
            "uploaded_by": f.uploaded_by, "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None}


def add(db: Session, owner_kind: str, owner, filename: str, content_type: str, data: bytes,
        actor: str, note: str = "") -> M.RecordFile:
    if owner_kind not in OWNERS:
        raise HTTPException(422, f"owner_kind is one of {', '.join(sorted(OWNERS))}")
    if not data:
        raise HTTPException(422, "the file is empty")
    if len(data) > MAX_MB * 1024 * 1024:
        raise HTTPException(413, f"file larger than {MAX_MB} MB")
    name = (filename or "file").replace("/", "_")[-200:]
    key = f"record-files/{owner_kind}/{owner.id}/{uuid.uuid4().hex[:12]}-{name}"
    storage.put_bytes(key, data, content_type or "application/octet-stream")
    row = M.RecordFile(company_id=owner.company_id, owner_kind=owner_kind, owner_id=owner.id, filename=name,
                       content_type=content_type or "application/octet-stream", size_bytes=len(data),
                       minio_key=key, note=(note or "")[:500], uploaded_by=actor[:100])
    db.add(row)
    db.flush()
    return row


def listed(db: Session, owner_kind: str, owner_id: int) -> list[M.RecordFile]:
    return (db.query(M.RecordFile).filter_by(owner_kind=owner_kind, owner_id=owner_id)
            .order_by(M.RecordFile.id).all())


def one(db: Session, owner_kind: str, owner_id: int, file_id: int) -> M.RecordFile:
    """The file, only under the owner it belongs to: a file id under another
    record answers 404, as a missing one does."""
    f = db.get(M.RecordFile, file_id)
    if f is None or f.owner_kind != owner_kind or f.owner_id != owner_id:
        raise HTTPException(404, "file not found")
    return f


def content(f: M.RecordFile) -> bytes:
    data = storage.get_bytes(f.minio_key)
    if data is None:
        raise HTTPException(404, "the file's bytes are missing from storage")
    return data
