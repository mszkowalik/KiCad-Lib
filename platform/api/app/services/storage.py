"""MinIO object storage — project snapshot archives, cached renders and
production-run attachments.

Key layout (single bucket, settings.minio_bucket):
    projects/{project_id}/snapshots/{sha}/source.tar.gz
    projects/{project_id}/renders/{sha}/{board}/layers/{layer}.svg
    projects/{project_id}/renders/{sha}/{board}/board.glb | board.step
    projects/{project_id}/renders/{sha}/{board}/sch/{variant|_default}/{page}.svg
    projects/{project_id}/renders/{sha}/{board}/sch/{variant|_default}/index.json
    projects/{project_id}/renders/{sha}/{board}/erc.json | drc.json
    projects/{project_id}/renders/{sha}/{board}/fab.zip
    projects/{project_id}/runs/{run_id}/{uuid}-{filename}

Renders are keyed by commit sha — immutable, so cached objects never need
invalidation. Deleting a project/run deletes its prefix.
"""
from __future__ import annotations

import io
import threading

from minio import Minio
from minio.deleteobjects import DeleteObject
from minio.error import S3Error

from ..config import settings

_client: Minio | None = None
_lock = threading.Lock()


def client() -> Minio:
    global _client
    with _lock:
        if _client is None:
            _client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=settings.minio_secure,
            )
            if not _client.bucket_exists(settings.minio_bucket):
                _client.make_bucket(settings.minio_bucket)
        return _client


def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    client().put_object(
        settings.minio_bucket, key, io.BytesIO(data), length=len(data), content_type=content_type
    )


def get_bytes(key: str) -> bytes | None:
    try:
        resp = client().get_object(settings.minio_bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()
    except S3Error as e:
        if e.code in ("NoSuchKey", "NoSuchBucket"):
            return None
        raise


def exists(key: str) -> bool:
    try:
        client().stat_object(settings.minio_bucket, key)
        return True
    except S3Error as e:
        if e.code in ("NoSuchKey", "NoSuchBucket"):
            return False
        raise


def list_keys(prefix: str) -> list[str]:
    return [
        o.object_name
        for o in client().list_objects(settings.minio_bucket, prefix=prefix, recursive=True)
    ]


def delete_prefix(prefix: str) -> int:
    keys = list_keys(prefix)
    if not keys:
        return 0
    errors = client().remove_objects(
        settings.minio_bucket, [DeleteObject(k) for k in keys]
    )
    # remove_objects is lazy — drain the iterator to actually delete
    for _ in errors:
        pass
    return len(keys)
