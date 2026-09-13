#!/usr/bin/env python3
"""Render one footprint in 3D so its model can be judged by eye.

Builds a minimal board with the footprint placed at the origin, sized to the
footprint, then calls `kicad-cli pcb render` from the front, the right and an
isometric angle. Use it to answer what a bounding box cannot: whether the model
sits on the board, whether its leads land on the pads, and whether an apparent
size error is really the model or really the measurement.

It earns its place. On the CE_Dongle_V3 sweep three models were reported as
defective from measurement alone; rendering them withdrew two. A lightpipe said
to sit flat was at its required z = 1.0 mm, and a tact switch said to be 80 %
oversize was correct. The third, an RJ45 sunk 4.1 mm into the board, was real
and obvious on sight.

    python3 scripts/footprint-render.py <footprint name> [...]

Reads the installed 7Sigma library by default; set FP_LIB to render a directory
of candidate .kicad_mod files instead. Writes PNGs to ./renders/.
"""
import os, subprocess, sys, pathlib

CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
LIB = os.environ.get("FP_LIB", "/Users/mateuszkowalik/Documents/KiCad/10.0/3rdparty/footprints/com_sevensigma_library/7Sigma.pretty")
# kicad-cli resolves ${SEVENSIGMA_DIR}/3DModels/... . The PCM installs the
# models under 3rdparty/3dmodels/com_sevensigma_models3d/, so point
# SEVENSIGMA_DIR at a scratch directory whose 3DModels/ links to it.
MODELS = os.environ.get(
    "SEVENSIGMA_MODELS",
    "/Users/mateuszkowalik/Documents/KiCad/10.0/3rdparty/3dmodels/com_sevensigma_models3d")


def model_root(out: "pathlib.Path") -> str:
    root = out / "_sevensigma"
    root.mkdir(parents=True, exist_ok=True)
    link = root / "3DModels"
    if not link.exists():
        link.symlink_to(MODELS)
    return str(root)

BOARD = '''(kicad_pcb (version 20241229) (generator "hand") (generator_version "10.0")
 (general (thickness 1.6) (legacy_teardrops no))
 (paper "A4")
 (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (9 "F.Adhes" user) (11 "F.Paste" user)
  (13 "F.SilkS" user) (15 "F.Mask" user) (17 "B.Mask" user) (31 "Edge.Cuts" user)
  (35 "Cmts.User" user) (37 "Dwgs.User" user) (39 "F.CrtYd" user) (41 "F.Fab" user))
 (setup (pad_to_mask_clearance 0))
 (gr_rect (start -{h} -{h}) (end {h} {h}) (stroke (width 0.1) (type solid)) (fill no) (layer "Edge.Cuts"))
{fp}
)
'''


def build(name: str, out: pathlib.Path) -> pathlib.Path:
    src = pathlib.Path(LIB, name + ".kicad_mod").read_text()
    # A footprint file becomes a board item by gaining a placement.
    src = src.replace('(footprint "', '(footprint "', 1)
    i = src.index("\n")
    body = src[i:].rstrip()
    assert body.endswith(")")
    placed = f'(footprint "{name}"\n\t(at 0 0){body[:-1]}\n)'
    import re
    xs, ys = [], []
    for m in re.finditer(r"\((?:start|end|center|at)\s+(-?[\d.]+)\s+(-?[\d.]+)", src):
        xs.append(float(m.group(1))); ys.append(float(m.group(2)))
    span = max(max(abs(v) for v in xs + ys), 1.0)
    half = round(span + 1.5, 2)
    pcb = BOARD.format(h=half, fp=placed)
    p = out / (name.replace("/", "_") + ".kicad_pcb")
    p.write_text(pcb)
    return p


def render(pcb: pathlib.Path, side: str, rotate: str = "") -> pathlib.Path:
    png = pcb.with_name(f"{pcb.stem}__{side}{'_iso' if rotate else ''}.png")
    cmd = [CLI, "pcb", "render", "-o", str(png), "--side", side,
           "--quality", "high", "--background", "opaque",
           "-w", "1100", "-h", "850", "--zoom", "1.35",
           "-D", f"SEVENSIGMA_DIR={model_root(pcb.parent)}", str(pcb)]
    if rotate:
        cmd[cmd.index("--side") + 1] = "top"
        cmd += ["--rotate", rotate]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr, file=sys.stderr)
    return png


if __name__ == "__main__":
    out = pathlib.Path("renders"); out.mkdir(exist_ok=True)
    for name in sys.argv[1:]:
        pcb = build(name, out)
        for side in ("front", "right"):
            print(render(pcb, side))
        print(render(pcb, "top", rotate="-60,0,30"))
