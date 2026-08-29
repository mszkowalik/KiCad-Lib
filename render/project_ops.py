"""kicad-cli operations on a full project checkout (board + schematic).

This file exists TWICE and the two copies must stay byte-identical: the render
container runs one at render/project_ops.py, and the API imports the other at
api/app/services/project_ops.py for its RENDER_MODE=local path. The images
workflow fails the build when they diverge, so edit both in the same change.

Ops (src = .kicad_pcb or .kicad_sch inside a materialized checkout):
    board_layer_svg  pcb  one layer -> SVG (board-area page, aligned stack)
    board_glb        pcb  -> binary GLB (web 3D viewer)
    board_step       pcb  -> STEP (CAD download)
    sch_svg          sch  -> zip of per-page SVGs (variant-aware)
    bom_csv          sch  -> grouped BOM CSV (variant-aware)
    erc              sch  -> JSON report
    drc              pcb  -> JSON report
    fab              pcb  -> zip: gerbers + drill + position files
    sch_spice        sch  -> SPICE netlist text (flattened, Sim.* resolved)
    sch_kicadxml     sch  -> KiCad XML netlist (nets with their member pins)
    sim_run          sch  -> ngspice run of that netlist, as a 7SIM payload
"""
from __future__ import annotations

import io
import subprocess
import tempfile
import zipfile
from pathlib import Path

# The render container runs these as flat modules in /srv; the API imports
# them as a package. Both copies of this file must stay byte-identical, so
# the import has to work either way.
try:
    from . import sim_spice
except ImportError:  # pragma: no cover - render container
    import sim_spice


class OpError(RuntimeError):
    pass


# Field/label pairs for BOM extraction. SYMBOL_NAME matches the platform's
# component names (library symbols are named after the component); LCSC Part
# is the fallback match key. Grouping keeps distinct symbols/DNP states on
# separate lines.
BOM_FIELDS = (
    "Reference,Value,Footprint,LCSC Part,Manufacturer Part,Manufacturer,"
    "${QUANTITY},${DNP},${EXCLUDE_FROM_BOM},${EXCLUDE_FROM_BOARD},${SYMBOL_NAME},${SYMBOL_LIBRARY},"
    "7S Version"
)
BOM_LABELS = (
    "Reference,Value,Footprint,LCSC,MPN,Manufacturer,"
    "Quantity,DNP,ExcludeBOM,ExcludeBoard,SymbolName,SymbolLibrary,LibVersion"
)
BOM_GROUP = "Value,Footprint,LCSC Part,${SYMBOL_NAME},${DNP}"

MEDIA = {
    "board_layer_svg": "image/svg+xml",
    "board_glb": "model/gltf-binary",
    "board_step": "application/step",
    "sch_svg": "application/zip",
    "bom_csv": "text/csv",
    "erc": "application/json",
    "drc": "application/json",
    "fab": "application/zip",
    "gerber_svg": "image/svg+xml",
    "sch_spice": "text/plain",
    "sch_kicadxml": "application/xml",
    "sim_run": "application/octet-stream",
}


def _run(cmd: list[str], timeout: int = 600, env: dict | None = None,
         cwd: str | Path | None = None) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd)
    if proc.returncode != 0:
        raise OpError(proc.stderr.strip() or proc.stdout.strip() or "kicad-cli failed")


def _zip_dir(d: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(d.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(d).as_posix())
    return buf.getvalue()


def run_op(
    kicad_cli: str,
    op: str,
    src: str | Path,
    out_dir: str | Path,
    *,
    variant: str = "",
    layer: str = "",
    theme: str = "",
    files: list | None = None,
    env: dict | None = None,
    control: str | None = None,
    analysis: str = "",
    ngspice: str = "ngspice",
    timeout: int = 60,
) -> tuple[bytes, str]:
    """Returns (bytes, media_type). out_dir must be a writable temp dir.
    gerber_svg: src is a DIRECTORY; files = [{file, color}] selects layers.
    sim_run: control/analysis override the schematic's own directives (see
    sim_spice.prepare_netlist), ngspice is the binary, timeout is its cap."""
    src = Path(src)
    out = Path(out_dir)
    if not src.exists():
        raise OpError(f"source file not found: {src}")
    var_args = ["--variant", variant] if variant else []
    theme_args = ["-t", theme] if theme else []

    if op == "gerber_svg":
        # One gerbv call composites all selected layers into a single SVG,
        # so they stay aligned (per-file exports would each autoscale).
        if not files:
            raise OpError("gerber_svg needs a non-empty files list")
        dest = out / "gerbers.svg"
        args = []
        for entry in files:
            name = str(entry.get("file", ""))
            gpath = (src / name).resolve()
            if not str(gpath).startswith(str(src.resolve())) or not gpath.is_file():
                raise OpError(f"gerber file not found: {name}")
            color = str(entry.get("color", "#c83434"))
            args += [f"--foreground={color}", str(gpath)]
        _run(["gerbv", "--export=svg", "--output", str(dest), *args], env=env)
        return dest.read_bytes(), MEDIA[op]

    if op == "board_layer_svg":
        if not layer:
            raise OpError("board_layer_svg needs a layer")
        dest = out / "layer.svg"
        _run(
            [
                kicad_cli, "pcb", "export", "svg",
                "--mode-single", "--layers", layer,
                "--page-size-mode", "2", "--exclude-drawing-sheet",
                *theme_args, *var_args,
                "-o", str(dest), str(src),
            ],
            env=env,
        )
        return dest.read_bytes(), MEDIA[op]

    if op == "board_glb":
        dest = out / "board.glb"
        _run(
            [
                kicad_cli, "pcb", "export", "glb",
                "--subst-models", "--include-tracks", "--include-pads", "--include-zones",
                "--include-silkscreen", "--include-soldermask", "--force",
                "-o", str(dest), str(src),
            ],
            env=env,
        )
        return dest.read_bytes(), MEDIA[op]

    if op == "board_step":
        dest = out / "board.step"
        _run(
            [kicad_cli, "pcb", "export", "step", "--subst-models", "--force", "-o", str(dest), str(src)],
            env=env,
        )
        return dest.read_bytes(), MEDIA[op]

    if op == "sch_svg":
        pages = out / "pages"
        pages.mkdir()
        _run(
            [kicad_cli, "sch", "export", "svg", *theme_args, *var_args, "-o", str(pages), str(src)],
            env=env,
        )
        if not any(pages.glob("*.svg")):
            raise OpError("schematic export produced no pages")
        return _zip_dir(pages), MEDIA[op]

    if op == "bom_csv":
        dest = out / "bom.csv"
        _run(
            [
                kicad_cli, "sch", "export", "bom",
                "--fields", BOM_FIELDS, "--labels", BOM_LABELS, "--group-by", BOM_GROUP,
                # no C7-C9 ranges — refs stay explicit so they can be matched
                # one-by-one (interactive maps, JLC designator lists)
                "--ref-range-delimiter", "",
                *var_args,
                "-o", str(dest), str(src),
            ],
            env=env,
        )
        return dest.read_bytes(), MEDIA[op]

    if op in ("erc", "drc"):
        dest = out / f"{op}.json"
        tool = ["sch", "erc"] if op == "erc" else ["pcb", "drc"]
        _run(
            [kicad_cli, *tool, "--format", "json", "--severity-all", "-o", str(dest), str(src)],
            env=env,
        )
        return dest.read_bytes(), MEDIA[op]

    if op == "fab":
        fabdir = out / "fab"
        gerbers = fabdir / "gerbers"
        gerbers.mkdir(parents=True)
        _run([kicad_cli, "pcb", "export", "gerbers", "-o", str(gerbers) + "/", str(src)], env=env)
        _run([kicad_cli, "pcb", "export", "drill", "-o", str(gerbers) + "/", str(src)], env=env)
        _run(
            [
                kicad_cli, "pcb", "export", "pos",
                "--format", "csv", "--units", "mm", "--side", "both",
                "-o", str(fabdir / "position.csv"), str(src),
            ],
            env=env,
        )
        return _zip_dir(fabdir), MEDIA[op]

    if op in ("sch_spice", "sch_kicadxml"):
        # kicad-cli flattens the hierarchy, resolves ${SEVENSIGMA_DIR} in
        # Sim.Library from the environment (verified — docs/simulator/design.md
        # §2.1), and copies the schematic's directive text items verbatim.
        fmt = "spice" if op == "sch_spice" else "kicadxml"
        dest = out / ("netlist.cir" if fmt == "spice" else "netlist.xml")
        # cwd = the schematic's own directory. A relative Sim.Library (a
        # model file the design keeps next to its sheets) otherwise resolves
        # against whatever directory the server happens to be in — measured,
        # not assumed. Absolute and ${SEVENSIGMA_DIR} paths are unaffected.
        _run(
            [kicad_cli, "sch", "export", "netlist", "--format", fmt, *var_args,
             "-o", str(dest), str(src.resolve())],
            env=env, cwd=src.resolve().parent,
        )
        if not dest.exists():
            raise OpError("netlist export produced no file")
        return dest.read_bytes(), MEDIA[op]

    if op == "sim_run":
        netlist_text, _ = run_op(kicad_cli, "sch_spice", src, out_dir, variant=variant, env=env)
        try:
            # prepare_netlist refuses a control block that reaches outside the
            # simulation, and that refusal is a message for the user — it has
            # to travel as an OpError like every other failure here, or the
            # render service answers a bare 500 with nothing in it.
            prepared, info = sim_spice.prepare_netlist(
                netlist_text.decode("utf-8", "replace"), control=control, analysis=analysis,
            )
            with tempfile.TemporaryDirectory() as sim_dir:
                raw, log = sim_spice.run_ngspice(
                    prepared, sim_dir, ngspice=ngspice, timeout=timeout, env=env,
                )
                plots = sim_spice.parse_raw(raw)
        except sim_spice.SimError as e:
            raise OpError(str(e)) from e
        return sim_spice.encode_payload(plots, info=info, log=log), MEDIA[op]

    raise OpError(f"unknown op: {op}")
