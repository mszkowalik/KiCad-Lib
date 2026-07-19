"""Project render dispatch + MinIO caching.

Same dual-mode pattern as render.py: RENDER_MODE=http POSTs to the render
container's /render-project (which sees the checkouts on the shared volume);
RENDER_MODE=local runs kicad-cli directly (dev on the Mac).

Everything is cached in MinIO keyed by commit sha — immutable, rendered at
most once. Per-key locks stop a double render when two requests race.
"""
from __future__ import annotations

import os
import tempfile
import threading

import httpx

from ..config import settings
from . import storage
from .project_ops import MEDIA, run_op

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def run_project_op(op: str, rel_src: str, *, variant: str = "", layer: str = "", theme: str = "",
                   files: list | None = None) -> tuple[bytes, str]:
    """rel_src is relative to DATA_DIR (== /data in the containers)."""
    if settings.render_mode == "local":
        with tempfile.TemporaryDirectory() as td:
            env = {**os.environ, "SEVENSIGMA_DIR": str(settings.mirror_dir.resolve())}
            return run_op(
                settings.kicad_cli, op, settings.data_dir / rel_src, td,
                variant=variant, layer=layer, theme=theme, files=files, env=env,
            )
    resp = httpx.post(
        f"{settings.render_url}/render-project",
        json={"op": op, "path": rel_src, "variant": variant, "layer": layer, "theme": theme,
              "files": files},
        timeout=900,
    )
    if resp.status_code != 200:
        detail = ""
        try:
            detail = resp.json().get("detail", "")
        except Exception:
            detail = resp.text[:500]
        raise RuntimeError(f"render service failed ({resp.status_code}): {detail}")
    return resp.content, resp.headers.get("content-type", MEDIA.get(op, "application/octet-stream"))


def cached_op(cache_key: str, op: str, rel_src: str, *, variant: str = "", layer: str = "",
              theme: str = "", files: list | None = None) -> tuple[bytes, str]:
    """MinIO-backed cache around run_project_op."""
    data = storage.get_bytes(cache_key)
    if data is not None:
        return data, MEDIA.get(op, "application/octet-stream")
    with _lock_for(cache_key):
        data = storage.get_bytes(cache_key)
        if data is not None:
            return data, MEDIA.get(op, "application/octet-stream")
        data, media = run_project_op(op, rel_src, variant=variant, layer=layer, theme=theme, files=files)
        storage.put_bytes(cache_key, data, media)
        return data, media


def rel_checkout(project_id: int, sha: str, file_rel: str) -> str:
    """Path of a checked-out project file relative to DATA_DIR (the render
    container's /data)."""
    return f"checkouts/{project_id}/{sha}/{file_rel}"


def render_key(project_id: int, sha: str, board: str, artifact: str) -> str:
    return f"projects/{project_id}/renders/{sha}/{board}/{artifact}"


# Themed artifacts — projects reuse the component-preview themes so boards
# match footprint previews and schematics match symbol previews. The theme
# is part of the cache key: changing a theme re-renders instead of serving
# stale colors.

def board_layer(project_id: int, sha: str, board: str, rel_pcb: str, layer: str) -> tuple[bytes, str]:
    theme = settings.footprint_theme
    safe = layer.replace("/", "_")
    key = render_key(project_id, sha, board, f"layers/{theme or 'default'}/{safe}.svg")
    return cached_op(key, "board_layer_svg", rel_pcb, layer=layer, theme=theme)


def sch_pages_zip(project_id: int, sha: str, board: str, rel_sch: str, variant: str) -> bytes:
    theme = settings.symbol_theme
    vdir = variant or "_default"
    key = render_key(project_id, sha, board, f"sch/{vdir}/{theme or 'default'}/pages.zip")
    data, _media = cached_op(key, "sch_svg", rel_sch, variant=variant, theme=theme)
    return data
