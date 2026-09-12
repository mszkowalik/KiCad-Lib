"""MinIO object storage — cached renders and production-run attachments.

Key layout (single bucket, settings.minio_bucket):
    projects/{project_id}/renders/{sha}/{board}/layers/{layer}.svg
    projects/{project_id}/renders/{sha}/{board}/board.glb | board.step
    projects/{project_id}/renders/{sha}/{board}/sim/... (netlists)
    projects/{project_id}/renders/{sha}/{board}/erc.json | drc.json
    projects/{project_id}/renders/{sha}/{board}/fab.zip
    projects/{project_id}/runs/{run_id}/{uuid}-{filename}

Renders are keyed by commit sha — immutable, so cached objects never need
invalidation. Deleting a project/run deletes its prefix.
"""
from __future__ import annotations

import io
import logging
import threading

from minio import Minio
from minio.deleteobjects import DeleteObject
from minio.error import S3Error

from ..config import settings

log = logging.getLogger("uvicorn.error")

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


def drop_schematic_renders() -> int:
    """Delete the cached schematic page images. Returns how many went.

    The browser draws schematics from the file now (`services/sch_draw.py`),
    so nothing reads these — one zip of page SVGs per board per commit, a few
    megabytes each, kept for good because a commit is immutable. There is no
    invalidation path for a render nobody asks for any more, so this is it.
    """
    doomed = [
        key for key in list_keys("projects/")
        if "/renders/" in key
        and ("/sch/" in key or key.endswith(("pages.zip", "pages-plain.zip")))
    ]
    if not doomed:
        return 0
    errors = client().remove_objects(
        settings.minio_bucket, [DeleteObject(k) for k in doomed]
    )
    for _ in errors:
        pass
    return len(doomed)


def drop_snapshot_archives() -> tuple[int, bool]:
    """Delete every stored `source.tar.gz` the git mirror can rebuild.

    Returns (how many went, whether the job is finished).

    Ingest wrote one per commit and nothing ever read it back — the key
    appeared exactly twice in the codebase, at the write and in this module's
    own docstring. The git mirror already holds every commit, so these were a
    second copy of the same bytes at four times the size (847 MB of tarballs
    against 214 MB of mirrors). `gitrepo.archive_tgz` rebuilds any one of them
    on demand. Decision 0009.

    **An archive is only redundant while its mirror is still here.** Measured
    on production 2026-09-12, one project of four was not: project 3 had no
    mirror directory, an empty checkout and a remote that needs a credential
    the platform does not hold, so its stored tarball was the only copy of that
    tree on the server — and it is the project's current snapshot AND pinned by
    a production run. Nothing in the app can reach that state (only deleting a
    project removes a mirror, and that removes the row too), so it arrived from
    outside and can arrive again. This keeps what it cannot rebuild and reports
    it by key.

    Keeping any means the job is NOT finished, so the caller must not write its
    marker: fetching the missing mirror and restarting should then finish it.
    """
    from . import gitrepo

    doomed: list[str] = []
    kept: list[str] = []
    for key in list_keys("projects/"):
        if "/snapshots/" not in key or not key.endswith("source.tar.gz"):
            continue
        parts = key.split("/")  # projects/<id>/snapshots/<sha>/source.tar.gz
        try:
            project_id, sha = int(parts[1]), parts[3]
        except (IndexError, ValueError):
            kept.append(key)  # not a key this platform wrote — leave it alone
            continue
        (doomed if gitrepo.can_rebuild(project_id, sha) else kept).append(key)

    if kept:
        log.warning(
            "storage: keeping %d snapshot archive(s) — no mirror to rebuild them from. "
            "Fetch the project, then restart to finish the purge. Kept: %s",
            len(kept), ", ".join(sorted(kept)))
    if doomed:
        errors = client().remove_objects(
            settings.minio_bucket, [DeleteObject(k) for k in doomed]
        )
        for _ in errors:
            pass
    return len(doomed), not kept


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
