#!/usr/bin/env python3
"""Does the simulator pipeline still work end to end?

There is no pytest in this repo, and a real check needs both kicad-cli and
ngspice, which the api image carries neither of — so this is a script you run
on a machine that has them (your Mac, or inside the render container).

    cd api && .venv/bin/python cli/simcheck.py            # downloads fixtures
    cd api && .venv/bin/python cli/simcheck.py --keep out/

It builds two circuits from KiCad's own `sallen_key` simulation demo — the
flat one as shipped, and a two-sheet hierarchy that places it as a sub-sheet —
then walks the whole path a browser walks: store the upload, read the sheet
tree, extract the overlay geometry, run ngspice, and check that the geometry
and the run agree about the nets. That last check is the one that matters: an
overlay whose node names do not match the rawfile's draws nothing, or worse,
draws the wrong wire.

The fixtures are fetched from KiCad's repository rather than vendored — they
are KiCad's files, under KiCad's licence, and they change with KiCad.

Exit status is 1 on the first failed check, so it works in a hook.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

DEMO = "https://gitlab.com/kicad/code/kicad/-/raw/master/demos/simulation/sallen_key"
FILES = ("sallen_key.kicad_sch", "sallen_key.kicad_pro", "ad8051.lib")

# Fixed uuids so a re-run produces the same instance paths, and so a failure
# report names something stable.
ROOT_UUID = "10000000-0000-4000-8000-000000000001"
SHEET_UUID = "20000000-0000-4000-8000-000000000002"

ROOT_SHEET = f"""(kicad_sch
\t(version 20250114)
\t(generator "simcheck")
\t(generator_version "9.0")
\t(uuid "{ROOT_UUID}")
\t(paper "A4")
\t(lib_symbols)
\t(sheet
\t\t(at 88.9 76.2)
\t\t(size 50.8 25.4)
\t\t(stroke (width 0.1524) (type solid))
\t\t(fill (color 0 0 0 0.0000))
\t\t(uuid "{SHEET_UUID}")
\t\t(property "Sheetname" "amp" (at 88.9 75.5 0) (effects (font (size 1.27 1.27))))
\t\t(property "Sheetfile" "amp.kicad_sch" (at 88.9 102.1 0) (effects (font (size 1.27 1.27))))
\t\t(instances (project "hier" (path "/{ROOT_UUID}" (page "2"))))
\t)
\t(sheet_instances (path "/" (page "1")))
)
"""

failures = 0


def check(ok: bool, what: str, detail: str = "") -> None:
    global failures
    print(("  ok   " if ok else "  FAIL ") + what + (f" — {detail}" if detail else ""))
    if not ok:
        failures += 1


def fetch(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        target = dest / name
        if target.exists():
            continue
        print(f"  fetching {name}")
        with urllib.request.urlopen(f"{DEMO}/{name}", timeout=60) as resp:
            target.write_bytes(resp.read())


def build_hierarchy(flat: Path, dest: Path) -> None:
    """Place the demo sheet inside a root sheet, rewriting its instance paths
    so its symbols keep their references on the new hierarchy."""
    dest.mkdir(parents=True, exist_ok=True)
    text = (flat / "sallen_key.kicad_sch").read_text(encoding="utf-8")
    old_root = text.split('(uuid "', 1)[1].split('"', 1)[0]
    text = text.replace(f'(path "/{old_root}"', f'(path "/{ROOT_UUID}/{SHEET_UUID}"')
    text = text.replace('(project "sallen_key"', '(project "hier"')
    (dest / "amp.kicad_sch").write_text(text, encoding="utf-8")
    (dest / "hier.kicad_sch").write_text(ROOT_SHEET, encoding="utf-8")
    shutil.copy(flat / "ad8051.lib", dest / "ad8051.lib")


def upload(sim_run, folder: Path, names: list[str]):
    files = [(n, (folder / n).read_bytes()) for n in names]
    return sim_run.upload_source(sim_run.store_upload(files)["id"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", metavar="DIR", help="work in DIR and leave the files there")
    ap.add_argument("--kicad-cli", default=os.environ.get("KICAD_CLI", ""),
                    help="kicad-cli path (default: the KICAD_CLI env var, then the setting)")
    ap.add_argument("--ngspice", default=os.environ.get("NGSPICE_BIN", "ngspice"))
    ap.add_argument("--spice-lib-dir", default=os.environ.get("SPICE_LIB_DIR", ""),
                    help="directory holding scripts/spinit (Homebrew needs "
                         "/opt/homebrew/share/ngspice; the container does not need this)")
    args = ap.parse_args()

    work = Path(args.keep) if args.keep else Path(tempfile.mkdtemp(prefix="simcheck-"))
    # The service reads its paths from settings, so point those at the work
    # directory BEFORE importing the app.
    os.environ["DATA_DIR"] = str(work / "data")
    os.environ["RENDER_MODE"] = "local"
    os.environ["NGSPICE_BIN"] = args.ngspice
    if args.kicad_cli:
        os.environ["KICAD_CLI"] = args.kicad_cli
    if args.spice_lib_dir:
        os.environ["SPICE_LIB_DIR"] = args.spice_lib_dir
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.services import sim_run, sim_spice  # noqa: PLC0415 - after the env is set

    flat, hier = work / "flat", work / "hier"
    print(f"work dir: {work}")
    fetch(flat)
    build_hierarchy(flat, hier)

    for label, folder, names, sheet_count in (
        ("flat", flat, ["sallen_key.kicad_sch", "ad8051.lib"], 1),
        ("hierarchy", hier, ["hier.kicad_sch", "amp.kicad_sch", "ad8051.lib"], 2),
    ):
        print(f"\n{label}:")
        src = upload(sim_run, folder, names)
        sheets = sim_run.sheets(src)
        check(len(sheets) == sheet_count, f"sheet tree has {sheet_count} instance(s)",
              f"got {[s['name'] for s in sheets]}")

        # The drawn sheet is the last one — the root of a hierarchy holds only
        # the sub-sheet box.
        geom = sim_run.geometry(src, sheets[-1]["path"])
        named = [w for w in geom["wires"] if w["net"]]
        check(geom["wires"] and len(named) == len(geom["wires"]),
              "every wire got a net from the netlist",
              f"{len(named)}/{len(geom['wires'])}")
        check(not geom["warnings"], "geometry has no warnings", "; ".join(geom["warnings"]))
        check(any(t["directive"] for t in geom["texts"]),
              "the schematic's simulation directive was found")

        payload = sim_run.run(src, control="", analysis=".tran 10u 5m")
        header = sim_spice.decode_header(payload)
        plot = header["plots"][0] if header["plots"] else {}
        check(plot.get("name") == "Transient Analysis", "the transient override ran",
              str(plot.get("name")))
        check(plot.get("n", 0) > 100, "the run returned points", str(plot.get("n")))

        # The join the overlay depends on: a net the geometry knows must be a
        # vector the run returned. Ground is exempt — ngspice aliases it to
        # node 0 and never emits a vector for it.
        vector_keys = {v["key"] for v in plot.get("vectors", [])}
        wanted = {g["spice"] for g in geom["groups"]
                  if g.get("spice") and not g.get("ground") and not g.get("derived")}
        missing = sorted(wanted - vector_keys)
        check(not missing, "every net on the drawing has a simulated vector", ", ".join(missing))

        refs = {s["ref"] for s in geom["symbols"] if not s["power"]}
        device_keys = {v["key"] for v in plot.get("vectors", []) if v["kind"] == "i"}
        check(device_keys and {r.lower() for r in refs} >= device_keys,
              "device currents name symbols that are on this sheet",
              ", ".join(sorted(device_keys - {r.lower() for r in refs})))

    print("\nrefusals:")
    src = upload(sim_run, flat, ["sallen_key.kicad_sch", "ad8051.lib"])
    try:
        sim_run.run(src, control="shell echo hi")
        check(False, "a control block may not run a shell command")
    except Exception as e:  # noqa: BLE001 - any refusal is a pass here
        check("shell" in str(e), "a control block may not run a shell command", str(e)[:60])
    try:
        sim_run.store_upload([("model.lib", b"* nothing")])
        check(False, "an upload without a schematic is refused")
    except Exception as e:  # noqa: BLE001
        check("kicad_sch" in str(e), "an upload without a schematic is refused", str(e)[:60])

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    print("\n" + ("all checks passed" if not failures else f"{failures} check(s) FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
