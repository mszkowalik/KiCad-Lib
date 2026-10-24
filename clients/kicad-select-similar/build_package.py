"""Build the Plugin and Content Manager archive: dist/<identifier>-<version>.zip.

Install it in KiCad with Plugin and Content Manager > Install from File.

    python3 build_package.py
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

VERSION = "1.0.0"
HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / "plugin.json").read_text())

# Everything KiCad runs or reads. requirements.txt is not optional: without it
# KiCad abandons the plugin's Python environment and the button never appears.
PLUGIN_FILES = ["plugin.json", "requirements.txt", "select_similar.py", "similar_board.py",
                "similar_engine.py", "similar_panel.py", "icon-light-24.png", "icon-light-48.png",
                "icon-dark-24.png", "icon-dark-48.png"]


def metadata() -> dict:
    return {
        "$schema": "https://go.kicad.org/pcm/schemas/v1",
        "name": MANIFEST["name"],
        "description": "Altium-style Find Similar Objects for the PCB editor",
        "description_full": MANIFEST["description"],
        "identifier": MANIFEST["identifier"],
        "type": "plugin",
        "author": {"name": "7Sigma", "contact": {"web": "https://disfunction.cc/lib"}},
        "license": "unrestricted",
        "resources": {},
        "versions": [{
            "version": VERSION,
            "status": "stable",
            # IPC plugins arrived in 9.0; the schema assumes SWIG when absent
            "runtime": "ipc",
            "kicad_version": "10.0",
        }],
    }


def build() -> Path:
    out = HERE / "dist" / f"{MANIFEST['identifier']}-{VERSION}.zip"
    out.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("metadata.json", json.dumps(metadata(), indent=2))
        for name in PLUGIN_FILES:
            zf.write(HERE / name, f"plugins/{name}")
        zf.write(HERE / "icon-pcm.png", "resources/icon.png")
    return out


if __name__ == "__main__":
    print(build())
