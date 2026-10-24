"""Select Similar is the fourth package of the PCM repository (decision 0100).

What must hold: the zip carries every file KiCad runs and none of the files
written for people; the package entry declares the IPC runtime; adding the
package carried the three old packages over with their versions; and an index
built before the package existed still renders for a stale client.

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
    write_manifest(mirror, "2026-10-01T10:00:00", files)
    return tmp_path


def write_manifest(mirror, generated_at, files):
    entries = [{"path": rel, "sha256": str(hash(text))} for rel, text in files.items()]
    (mirror / "manifest.json").write_text(json.dumps({"generated_at": generated_at, "files": entries}))


def entry(document, identifier):
    return next(p for p in document["packages"] if p["identifier"] == identifier)


def test_the_zip_ships_what_kicad_runs_and_nothing_else(data_dir):
    meta = pcm.ensure_built()
    with zipfile.ZipFile(data_dir / "pcm" / meta["packages"]["similar"]["zip"]) as zf:
        names = set(zf.namelist())
    src = pcm._SIMILAR_SRC
    manifest = json.loads((src / "plugin.json").read_text())
    needed = {"plugins/plugin.json", "plugins/requirements.txt", "resources/icon.png"}
    for action in manifest["actions"]:
        needed.add(f"plugins/{action['entrypoint']}")
        needed.update(f"plugins/{icon}" for icon in action["icons-light"] + action["icons-dark"])
    # every module, or the entrypoint's imports fail on the user's machine
    needed.update(f"plugins/{f.name}" for f in src.glob("*.py"))
    assert needed <= names
    assert not {"plugins/README.md", "plugins/CLAUDE.md", "plugins/icon-pcm.png"} & names
    assert not any(n.startswith("plugins/tests/") for n in names)


def test_the_entry_declares_the_ipc_runtime_and_kicad_10(data_dir):
    meta = pcm.ensure_built()
    similar = entry(pcm._packages_document(meta["packages"]), pcm.SIMILAR_ID)
    version = similar["versions"][0]
    assert (similar["type"], version["version"], version["runtime"], version["kicad_version"]) == \
        ("plugin", pcm.SIMILAR_VERSION, "ipc", "10.0")
    # the other packages advertise no runtime, exactly as before
    assert "runtime" not in entry(pcm._packages_document(meta["packages"]), pcm.PLUGIN_ID)["versions"][0]


def test_a_personal_index_puts_the_token_on_the_shared_zip(data_dir):
    meta = pcm.ensure_built()
    document = json.loads(pcm.personal_packages(meta, "tok123"))
    version = entry(document, pcm.SIMILAR_ID)["versions"][0]
    assert version["download_url"].endswith(f"/{meta['packages']['similar']['zip']}?t=tok123")
    # not personalised: the bytes, and so the sha, are every user's
    assert version["download_sha256"] == meta["packages"]["similar"]["sha256"]


def test_an_index_from_before_the_package_still_renders(data_dir):
    meta = pcm.ensure_built()
    old = dict(meta["packages"])
    del old["similar"]
    identifiers = [p["identifier"] for p in pcm._packages_document(old)["packages"]]
    assert identifiers == [pcm.LIB_ID, pcm.MODELS_ID, pcm.PLUGIN_ID]


def test_a_select_similar_change_keeps_the_content_versions(data_dir, monkeypatch):
    """The mirror moved on (a new timestamp, the same files) and the Select
    Similar sources changed, so the tag moved. The content packages must keep
    their version and zip, or PCM offers every user a 260 MB update."""
    first = pcm.ensure_built()
    manifest_path = data_dir / "mirror" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["generated_at"] = "2026-10-24T16:00:00"
    manifest_path.write_text(json.dumps(manifest))
    shipped = pcm._similar_files()
    monkeypatch.setattr(pcm, "_similar_files", lambda: shipped + [("plugins/new.py", b"x = 1\n")])
    second = pcm.ensure_built()
    assert second["packages_file"] != first["packages_file"]
    for key in ("library", "models", "plugin"):
        assert second["packages"][key]["version"] == first["packages"][key]["version"]
        assert second["packages"][key]["zip"] == first["packages"][key]["zip"]
    assert second["packages"]["similar"]["zip"] != first["packages"]["similar"]["zip"]
