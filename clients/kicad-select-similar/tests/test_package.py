"""The PCM archive and the plugin manifest validate against the schemas KiCad
ships. Needs jsonschema (in the plugin's venv, as a kicad-python dependency)
and an installed KiCad; skips without either."""
import json
import os
import sys
import unittest
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

SCHEMAS = [Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/schemas"),
           Path("/usr/share/kicad/schemas"),
           Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "KiCad/10.0/share/kicad/schemas"]
SCHEMA_DIR = next((p for p in SCHEMAS if (p / "pcm.v1.schema.json").is_file()), None)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


@unittest.skipIf(jsonschema is None or SCHEMA_DIR is None, "jsonschema or KiCad schemas missing")
class Package(unittest.TestCase):
    def test_plugin_manifest(self):
        schema = json.loads((SCHEMA_DIR / "api.v1.schema.json").read_text())
        jsonschema.validate(json.loads((HERE / "plugin.json").read_text()), schema)

    def test_archive(self):
        import build_package
        path = build_package.build()
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            meta = json.loads(zf.read("metadata.json"))
        schema = json.loads((SCHEMA_DIR / "pcm.v1.schema.json").read_text())
        jsonschema.validate(meta, {**schema, "$ref": "#/definitions/Package"})
        self.assertIn("plugins/plugin.json", names)
        self.assertIn("plugins/requirements.txt", names)
        self.assertIn("resources/icon.png", names)
        # a module added later and forgotten in PLUGIN_FILES breaks the import
        for module in HERE.glob("*.py"):
            if module.name != "build_package.py":
                self.assertIn(f"plugins/{module.name}", names)
        # every icon the manifest names is in the archive
        manifest = json.loads((HERE / "plugin.json").read_text())
        for action in manifest["actions"]:
            for icon in action["icons-light"] + action["icons-dark"]:
                self.assertIn(f"plugins/{icon}", names)
            self.assertIn(f"plugins/{action['entrypoint']}", names)


if __name__ == "__main__":
    unittest.main()
