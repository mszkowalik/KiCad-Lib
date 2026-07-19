"""SVG preview rendering via kicad-cli — pixel-exact KiCad output.

Two modes (config RENDER_MODE):
  http   — POST to the render container (compose default)
  local  — invoke kicad-cli directly (dev on the Mac, KICAD_CLI path)
Results are cached on disk keyed by content hash.
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

import httpx

from ..config import settings


def render_svg(kind: str, name: str, source_text: str) -> bytes:
    """kind: symbol | footprint (SVG) | footprint3d (binary GLB board view)."""
    assert kind in ("symbol", "footprint", "footprint3d")
    theme = settings.symbol_theme if kind == "symbol" else settings.footprint_theme
    ext = "glb" if kind == "footprint3d" else "svg"
    digest = hashlib.sha256(f"{kind}\x00{name}\x00{theme}\x00{source_text}".encode()).hexdigest()
    cache_file = settings.render_cache_dir / f"{digest}.{ext}"
    if cache_file.exists():
        return cache_file.read_bytes()

    if settings.render_mode == "local":
        data = render_local(kind, name, source_text, settings.kicad_cli, theme,
                            models_root=str(settings.mirror_dir))
    else:
        resp = httpx.post(
            f"{settings.render_url}/render",
            json={"kind": kind, "name": name, "source_text": source_text, "theme": theme},
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.content

    settings.render_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(data)
    return data


def render_local(kind: str, name: str, source_text: str, kicad_cli: str, theme: str = "",
                 models_root: str = "") -> bytes:
    """Shared by the API's local mode and the render container (same logic).

    models_root: directory containing 3DModels/ — exported as SEVENSIGMA_DIR so
    kicad-cli resolves the footprints' ${SEVENSIGMA_DIR}/3DModels/... paths.
    """
    import os

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        out = tmp / "out"
        out.mkdir()
        theme_args = ["-t", theme] if theme else []
        if kind == "symbol":
            src = tmp / "render.kicad_sym"
            src.write_text(source_text, encoding="utf-8")
            cmd = [kicad_cli, "sym", "export", "svg", "-s", name, *theme_args, "-o", str(out), str(src)]
        elif kind == "footprint":
            pretty = tmp / "render.pretty"
            pretty.mkdir()
            (pretty / f"{name}.kicad_mod").write_text(source_text, encoding="utf-8")
            cmd = [kicad_cli, "fp", "export", "svg", "--fp", name, *theme_args, "-o", str(out), str(pretty)]
        else:  # footprint3d -> GLB board view
            from .board3d import build_board_text

            board = tmp / "render.kicad_pcb"
            board.write_text(build_board_text(source_text), encoding="utf-8")
            glb = out / "render.glb"
            cmd = [
                kicad_cli, "pcb", "export", "glb",
                "--subst-models", "--include-tracks", "--include-pads", "--include-zones",
                "--include-silkscreen", "--include-soldermask", "--force",
                "-o", str(glb), str(board),
            ]
        env = dict(os.environ)
        if models_root:
            env["SEVENSIGMA_DIR"] = models_root
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=150, env=env)
        outputs = sorted(out.glob("*.glb" if kind == "footprint3d" else "*.svg"))
        if proc.returncode != 0 or not outputs:
            raise RuntimeError(
                f"kicad-cli render failed (rc={proc.returncode}): {proc.stderr.strip() or proc.stdout.strip()}"
            )
        return outputs[0].read_bytes()
