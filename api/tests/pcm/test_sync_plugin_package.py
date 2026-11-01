"""The sync plugin zip carries every file KiCad runs and none of the files
written for people.

Until 2026-11-01 `_plugin_files` packed every file in `pcm_plugin/`, so the
folder's CLAUDE.md reached every user's KiCad plugins folder. Select Similar
had the same guard already (`test_select_similar_package.py`).

No database: the mirror is a few files in a temporary DATA_DIR.

Run from `api/`:
    python -m pytest tests/pcm -q
"""
import json
import pathlib
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import pytest

from app.config import settings
from app.services import pcm


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A mirror with one base symbol, one footprint and one model."""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    mirror = tmp_path / "mirror"
    files = {
        f"Symbols/{pcm.BASE_LIB_FILE}": "(kicad_symbol_lib)\n",
        "Footprints/7Sigma.pretty/R_0603.kicad_mod": '(footprint "R_0603")\n',
        "3DModels/R_0603.step": "ISO-10303-21;\n",
    }
    for rel, text in files.items():
        (mirror / rel).parent.mkdir(parents=True, exist_ok=True)
        (mirror / rel).write_text(text)
    entries = [{"path": rel, "sha256": str(hash(text))} for rel, text in files.items()]
    (mirror / "manifest.json").write_text(
        json.dumps({"generated_at": "2026-10-01T10:00:00", "files": entries}))
    return tmp_path


def test_the_zip_ships_what_kicad_runs_and_nothing_else(data_dir):
    meta = pcm.ensure_built()
    with zipfile.ZipFile(data_dir / "pcm" / meta["packages"]["plugin"]["zip"]) as zf:
        names = set(zf.namelist())
    src = pcm._PLUGIN_SRC
    manifest = json.loads((src / "plugin.json.tmpl").read_text())
    needed = {"plugins/plugin.json", "plugins/requirements.txt", "resources/icon.png"}
    for action in manifest["actions"]:
        needed.add(f"plugins/{action['entrypoint']}")
        needed.update(f"plugins/{icon}" for icon in action["icons-light"] + action["icons-dark"])
    # every module and every rendered template, or an import fails in KiCad
    needed.update(f"plugins/{f.name}" for f in src.glob("*.py"))
    needed.update(f"plugins/{f.name[:-5]}" for f in src.glob("*.tmpl"))
    assert needed <= names
    assert not {"plugins/CLAUDE.md", "plugins/README.md", "plugins/icon-pcm.png"} & names
    assert not any(n.endswith(".tmpl") for n in names)


def test_editing_the_folder_notes_does_not_rebuild_the_plugin(data_dir, monkeypatch, tmp_path):
    """A document in the folder is not part of the plugin, so it must not move
    the plugin hash that names the zip and feeds the repository tag."""
    before = pcm._plugin_files()
    src = tmp_path / "plugin_src"
    src.mkdir()
    for f in pcm._PLUGIN_SRC.iterdir():
        if f.is_file():
            (src / f.name).write_bytes(f.read_bytes())
    (src / "CLAUDE.md").write_text("an edited note\n")
    monkeypatch.setattr(pcm, "_PLUGIN_SRC", src)
    assert pcm._plugin_files() == before
