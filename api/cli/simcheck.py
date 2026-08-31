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

        # The drawing the browser renders comes from the same parse as the
        # nets, so the two must agree about how many parts there are. They
        # disagreeing is how an overlay ends up on the wrong symbol.
        draw = geom["draw"]
        check(len(draw["symbols"]) == len(geom["symbols"]),
              "the draw document and the geometry agree on the parts",
              f'{len(draw["symbols"])} vs {len(geom["symbols"])}')
        check(all(s["lib_id"] in draw["libs"] for s in draw["symbols"]),
              "every placement has its symbol definition embedded")
        check(len(draw["wires"]) == len(geom["wires"]),
              "the draw document and the geometry agree on the wires")

    print("\ndrawn in the browser:")
    from app.services import sch_lib, sch_write  # noqa: PLC0415 - after the env is set

    # A divider drawn from the editor's own primitives. The point is not that
    # ngspice can solve a divider — it is that a document written by the
    # browser becomes a file KiCad reads, and that the answer is right.
    doc = {
        "name": "divider", "uuid": ROOT_UUID, "paper": "A4",
        "symbols": [
            {"lib_id": "Simulator:V", "at": [80, 100, 0],
             "fields": {"Reference": "V1", "Value": "DC 5"}},
            {"lib_id": "Simulator:R", "at": [120, 85, 0],
             "fields": {"Reference": "R1", "Value": "1k"}},
            {"lib_id": "Simulator:R", "at": [120, 115, 0],
             "fields": {"Reference": "R2", "Value": "3k"}},
            {"lib_id": "Simulator:SW", "at": [100, 76.2, 0], "fields": {"Reference": "SW1"}},
            {"lib_id": "Simulator:GND", "at": [80, 125, 0], "fields": {"Reference": "#PWR01"}},
        ],
        "wires": [
            {"pts": [[80, 94.92], [80, 76.2], [94.92, 76.2]]},
            {"pts": [[105.08, 76.2], [120, 76.2], [120, 81.19]]},
            {"pts": [[120, 88.81], [120, 111.19]]},
            {"pts": [[120, 118.81], [120, 125], [80, 125]]},
            {"pts": [[80, 105.08], [80, 125]]},
        ],
        "labels": [{"text": "MID", "at": [120, 100, 0], "kind": "local"}],
        "texts": [{"at": [30, 60, 0], "text": ".op"}],
        "junctions": [],
    }
    meta = sim_run.store_sketch(doc)
    check(meta["root"].endswith(".kicad_sch"), "the sketch was written as a schematic",
          meta["root"])
    src = sim_run.upload_source(meta["id"])
    sheets = sim_run.sheets(src)
    check(len(sheets) == 1, "the drawn sheet is a sheet tree of one")
    netlist = sim_run.netlist_spice(src)
    # A switch is a resistor with `Sim.Device R`, and KiCad PREFIXES the
    # reference rather than replacing it. `alter sw1` would be accepted and do
    # nothing, so the name matters as much as the value.
    check("rsw1" in netlist.lower(), "the drawn switch netlists as a resistor named RSW1",
          netlist)
    geom = sim_run.geometry(src)
    switch = next((s for s in geom["symbols"] if s["ref"] == "SW1"), None)
    check(switch is not None and switch["spice"] == "rsw1",
          "the geometry names the switch the way `alter` must",
          str(switch and switch["spice"]))
    check(any(w["net"] == "/MID" for w in geom["wires"]),
          "the label the editor placed named a net",
          ", ".join(sorted({str(w["net"]) for w in geom["wires"]})))

    header = sim_spice.decode_header(sim_run.run(src))
    plot = header["plots"][0] if header["plots"] else {}
    keys = {v["key"] for v in plot.get("vectors", [])}
    # An operating point has no sweep axis, so ngspice's first column is an
    # ordinary node. Dropping it the way an axis is dropped loses a reading.
    check("/mid" in keys, "the operating point kept every node, first column included",
          ", ".join(sorted(keys)))
    check(plot.get("n") == 1, "an operating point is one point", str(plot.get("n")))

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
    try:
        sch_write.document_to_sch({"symbols": [{"lib_id": "Nope:Thing", "at": [0, 0, 0]}]})
        check(False, "a sketch naming a part that does not exist is refused")
    except sch_write.WriteError as e:
        check("Nope:Thing" in str(e), "a sketch naming a part that does not exist is refused",
              str(e)[:60])
    check(sch_lib.SWITCH_OPEN in sch_lib.draw_library()
          and sch_lib.SWITCH_CLOSED in sch_lib.draw_library(),
          "both switch states are in the palette library")

    if not args.keep:
        shutil.rmtree(work, ignore_errors=True)
    print("\n" + ("all checks passed" if not failures else f"{failures} check(s) FAILED"))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
