"""SVG preview rendering via kicad-cli — pixel-exact KiCad output.

Two modes (config RENDER_MODE):
  http   — POST to the render container (compose default)
  local  — invoke kicad-cli directly (dev on the Mac, KICAD_CLI path)
Results are cached on disk keyed by content hash.

A SYMBOL render also answers "how many units?". kicad-cli plots one file per
unit and nothing here can merge them, so the caller has to be able to ask for
unit 3 and to know that there are ten — see `svg_units.py`, and the
`X-Unit-Count` header the routers put it in.
"""
from __future__ import annotations

import hashlib
import subprocess
import tempfile
from pathlib import Path

import httpx

from ..config import settings
from .svg_units import select_unit


def render_svg(kind: str, name: str, source_text: str, unit: int | None = None) -> bytes:
    """kind: symbol | footprint (SVG) | footprint3d (binary GLB board view)."""
    return render_svg_units(kind, name, source_text, unit)[0]


def render_svg_units(kind: str, name: str, source_text: str,
                     unit: int | None = None) -> tuple[bytes, int]:
    """The render, and how many units the symbol has (1 for anything else).

    The count comes back beside the bytes because only the renderer ever sees
    it: it is how many files kicad-cli wrote, and nothing in the stored source
    is a reliable substitute — a `(symbol "X_2_1")` entry may be an empty
    alternate body style. It is cached with the drawing so a page flip costs
    the same 2 ms a re-render of unit 1 does.
    """
    assert kind in ("symbol", "footprint", "footprint3d")
    theme = settings.symbol_theme if kind == "symbol" else settings.footprint_theme
    ext = "glb" if kind == "footprint3d" else "svg"
    # The unit joins the key for a SYMBOL only: two units of one symbol are two
    # pictures of the same source, and a cache that ignored it would serve
    # whichever was asked for first for every unit after it. A footprint keeps
    # the original key so the ~400 ms cold render of every land pattern in the
    # library is not thrown away for a field that can never apply to it.
    unit_key = f"unit{unit or 1}\x00" if kind == "symbol" else ""
    digest = hashlib.sha256(
        f"{kind}\x00{name}\x00{theme}\x00{unit_key}{source_text}".encode()
    ).hexdigest()
    cache_file = settings.render_cache_dir / f"{digest}.{ext}"
    count_file = cache_file.with_suffix(".units")
    if cache_file.exists() and (kind != "symbol" or count_file.exists()):
        count = int(count_file.read_text()) if kind == "symbol" else 1
        return cache_file.read_bytes(), count

    if settings.render_mode == "local":
        data, count = render_local(kind, name, source_text, settings.kicad_cli, theme,
                                   models_root=str(settings.mirror_dir), unit=unit)
    else:
        resp = httpx.post(
            f"{settings.render_url}/render",
            json={"kind": kind, "name": name, "source_text": source_text,
                  "theme": theme, "unit": unit},
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.content
        count = int(resp.headers.get("X-Unit-Count", "1") or 1)

    settings.render_cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(data)
    if kind == "symbol":
        count_file.write_text(str(count))
    return data, count


def render_local(kind: str, name: str, source_text: str, kicad_cli: str, theme: str = "",
                 models_root: str = "", unit: int | None = None) -> tuple[bytes, int]:
    """Shared by the API's local mode and the render container (same logic).

    Returns the bytes and the symbol's unit count (1 for a footprint).

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
        # `sym export svg` writes NAME_unit1.svg, NAME_unit2.svg, … and has no
        # switch to write one file, so the file list IS the unit count.
        if kind == "symbol":
            return select_unit(outputs, unit)
        return outputs[0].read_bytes(), 1
