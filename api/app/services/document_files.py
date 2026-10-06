"""The files a supplier document keeps as its evidence: `RunAttachment` rows.

Stored under the `documents/` prefix, never the run's: `delete_run` wipes the
run prefix, and the evidence for a money row has to outlive the run. A file is
added, never replaced: the newest becomes the document's headline attachment
and the older ones stay reachable through the list, so a corrected scan never
destroys the first.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .. import models as M
from . import storage


def add(db: Session, doc: M.RunCostDocument, filename: str, content_type: str, data: bytes) -> M.RunAttachment:
    name = (filename or "document").replace("/", "_")
    content_type = content_type or "application/octet-stream"
    key = f"documents/{doc.id}/{uuid.uuid4().hex[:12]}-{name}"
    storage.put_bytes(key, data, content_type)
    a = M.RunAttachment(document_id=doc.id, filename=name, content_type=content_type,
                        size_bytes=len(data), minio_key=key)
    db.add(a)
    db.flush()
    doc.attachment_id = a.id
    return a


def has_pdf(db: Session, doc_id: int) -> bool:
    return db.query(M.RunAttachment.id).filter(
        M.RunAttachment.document_id == doc_id, M.RunAttachment.filename.ilike("%.pdf")).first() is not None
