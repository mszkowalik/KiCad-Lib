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
from . import pcm, storage
from . import sim_spice
from .project_ops import MEDIA, run_op

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(key: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(key, threading.Lock())


def sim_progress(job: str) -> dict:
    """How far a named sim_run has got, from whichever process is running it.

    The progress store lives in the process that owns the ngspice child. In
    `RENDER_MODE=http` that is the render container, and this is a second HTTP
    call made WHILE the run's own request is still blocking — both endpoints
    are sync `def`s, so FastAPI answers them on its threadpool and the run does
    not hold the loop. An unreachable container or an unknown job is no news,
    not a failure: the browser polls this and must not turn a hiccup into an
    error banner over a run that is fine.
    """
    if not job:
        return {}
    if settings.render_mode == "local":
        return sim_spice.get_progress(job)
    try:
        resp = httpx.get(f"{settings.render_url}/sim/progress/{job}", timeout=5)
    except httpx.HTTPError:
        return {}
    if resp.status_code != 200:
        return {}
    try:
        return resp.json() or {}
    except ValueError:
        return {}


def run_project_op(op: str, rel_src: str, *, variant: str = "", layer: str = "", theme: str = "",
                   files: list | None = None, control: str | None = None, analysis: str = "",
                   timeout: int = 60, job: str = "") -> tuple[bytes, str]:
    """rel_src is relative to DATA_DIR (== /data in the containers).
    control/analysis/timeout/job only mean anything to the sim_run op; `job`
    names the run in the progress store of whichever process runs ngspice."""
    # Cheap and idempotent, and it must happen on THIS side: in http mode the
    # render container reads the volume read-only and cannot create it.
    pcm.server_pcm_root()
    if settings.render_mode == "local":
        with tempfile.TemporaryDirectory() as td:
            env = {
                **os.environ,
                "SEVENSIGMA_DIR": str(settings.mirror_dir.resolve()),
                # Schematics drawn against the PCM install spell Sim.Library
                # the installed way; see pcm.server_pcm_root.
                "KICAD10_3RD_PARTY": str((settings.data_dir / pcm.SERVER_PCM_ROOT).resolve()),
            }
            if settings.spice_lib_dir:
                # A Homebrew ngspice does not find its own spinit, and without
                # it every XSPICE (poly) model in a subcircuit fails to load.
                env["SPICE_LIB_DIR"] = settings.spice_lib_dir
            return run_op(
                settings.kicad_cli, op, settings.data_dir / rel_src, td,
                variant=variant, layer=layer, theme=theme, files=files, env=env,
                control=control, analysis=analysis, ngspice=settings.ngspice_bin,
                timeout=timeout, job=job,
            )
    try:
        resp = httpx.post(
            f"{settings.render_url}/render-project",
            json={"op": op, "path": rel_src, "variant": variant, "layer": layer, "theme": theme,
                  "files": files, "control": control, "analysis": analysis, "timeout": timeout,
                  "job": job},
            timeout=900,
        )
    except httpx.HTTPError as e:
        # A render container that is down, or a request that outlived its
        # timeout. Not a RuntimeError subclass, so without this every sim
        # route died in ASGI with a bare 500 and no message.
        raise RuntimeError(f"render service unreachable: {type(e).__name__}: {e}") from e
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
