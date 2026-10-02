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

    python3 scripts/footprint-render.py <footprint name | path/to/file.kicad_mod> [...]

WHERE THE FOOTPRINT COMES FROM, first match wins:
  1. A path to a .kicad_mod file. Use this to render BEFORE you publish.
  2. The platform, when KICAD_API_URL and KICAD_MCP_TOKEN are set. This is the
     published version, so a footprint published a minute ago renders, and a
     stale local copy cannot hide a change.
  3. The installed 7Sigma library (FP_LIB), which lags the platform until the
     KiCad sync button is pressed.

WHERE EACH 3D MODEL COMES FROM, first match wins: next to a .kicad_mod given
as a path (by file name, or by its path under 3DModels/), then the platform's
/files/3DModels/, then the installed models (SEVENSIGMA_MODELS). A model found
nowhere is reported, and the board renders without it.

Writes PNGs to ./renders/.
"""
import gzip, json, os, re, shutil, subprocess, sys, pathlib
import urllib.error, urllib.parse, urllib.request

CLI = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
LIB = os.environ.get("FP_LIB", "/Users/mateuszkowalik/Documents/KiCad/10.0/3rdparty/footprints/com_sevensigma_library/7Sigma.pretty")
# kicad-cli resolves ${SEVENSIGMA_DIR}/3DModels/... . The PCM installs the
# models under 3rdparty/3dmodels/com_sevensigma_models3d/.
MODELS = os.environ.get(
    "SEVENSIGMA_MODELS",
    "/Users/mateuszkowalik/Documents/KiCad/10.0/3rdparty/3dmodels/com_sevensigma_models3d")
API = os.environ.get("KICAD_API_URL", "").rstrip("/")
TOKEN = os.environ.get("KICAD_MCP_TOKEN", "")
MODEL_RE = re.compile(r'\(model\s+"\$\{SEVENSIGMA_DIR\}/3DModels/([^"]+)"')


def _get(path: str, body: dict | None = None) -> bytes:
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {TOKEN}",
                                          "Content-Type": "application/json",
                                          # Cloudflare rejects the Python-urllib user agent.
                                          "User-Agent": "python-httpx/0.27.0"})
    return urllib.request.urlopen(req, timeout=60).read()


def footprint_source(arg: str) -> tuple[str, str, str, "pathlib.Path | None"]:
    """(name, .kicad_mod text, where it came from, directory to search for models)."""
    path = pathlib.Path(arg)
    if path.suffix == ".kicad_mod" and path.is_file():
        return path.stem, path.read_text(), f"file {path}", path.parent
    if API and TOKEN:
        try:
            res = json.loads(json.loads(_get("/api/agent/tools/get_footprint", {"name": arg}))["result"])
            if res.get("source"):
                return arg, res["source"], f"platform v{res.get('current_version_no')}", None
        except (urllib.error.URLError, KeyError, ValueError) as e:
            print(f"{arg}: platform lookup failed ({e}); trying the installed library", file=sys.stderr)
    local = pathlib.Path(LIB, arg + ".kicad_mod")
    if local.is_file():
        return arg, local.read_text(), "installed library", None
    sys.exit(f"{arg}: not a .kicad_mod file, not on the platform, not in {LIB}")


def model_root(src: str, out: pathlib.Path, name: str, near: "pathlib.Path | None") -> str:
    """A SEVENSIGMA_DIR holding exactly the models this footprint references."""
    root = out / f"_sevensigma_{name}"
    shutil.rmtree(root, ignore_errors=True)
    for rel in MODEL_RE.findall(src):
        dst = root / "3DModels" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        local = [near / pathlib.Path(rel).name, near / rel] if near else []
        found = next((p for p in local if p.is_file()), None)
        if found:
            shutil.copyfile(found, dst); print(f"  model {rel}: {found}")
            continue
        if API and TOKEN:
            try:
                raw = _get("/files/3DModels/" + urllib.parse.quote(rel))
                dst.write_bytes(gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw)
                print(f"  model {rel}: platform")
                continue
            except urllib.error.URLError:
                pass
        installed = pathlib.Path(MODELS, rel)
        if installed.is_file():
            shutil.copyfile(installed, dst); print(f"  model {rel}: installed library")
        else:
            print(f"  model {rel}: NOT FOUND - renders without it", file=sys.stderr)
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


def build(name: str, src: str, out: pathlib.Path) -> pathlib.Path:
    # A footprint file becomes a board item by gaining a placement.
    i = src.index("\n")
    body = src[i:].rstrip()
    assert body.endswith(")")
    placed = f'(footprint "{name}"\n\t(at 0 0){body[:-1]}\n)'
    xs, ys = [], []
    for m in re.finditer(r"\((?:start|end|center|at)\s+(-?[\d.]+)\s+(-?[\d.]+)", src):
        xs.append(float(m.group(1))); ys.append(float(m.group(2)))
    span = max(max(abs(v) for v in xs + ys), 1.0)
    half = round(span + 1.5, 2)
    pcb = BOARD.format(h=half, fp=placed)
    p = out / (name.replace("/", "_") + ".kicad_pcb")
    p.write_text(pcb)
    return p


def render(pcb: pathlib.Path, root: str, side: str, rotate: str = "") -> pathlib.Path:
    png = pcb.with_name(f"{pcb.stem}__{side}{'_iso' if rotate else ''}.png")
    cmd = [CLI, "pcb", "render", "-o", str(png), "--side", side,
           "--quality", "high", "--background", "opaque",
           "-w", "1100", "-h", "850", "--zoom", "1.35",
           "-D", f"SEVENSIGMA_DIR={root}", str(pcb)]
    if rotate:
        cmd[cmd.index("--side") + 1] = "top"
        cmd += ["--rotate", rotate]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr, file=sys.stderr)
    return png


if __name__ == "__main__":
    out = pathlib.Path("renders"); out.mkdir(exist_ok=True)
    for arg in sys.argv[1:]:
        name, src, where, near = footprint_source(arg)
        print(f"{name}: footprint from {where}")
        root = model_root(src, out, name, near)
        pcb = build(name, src, out)
        for side in ("front", "right"):
            print(render(pcb, root, side))
        print(render(pcb, root, "top", rotate="-60,0,30"))
