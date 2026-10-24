"""plugin.json validates against the schema KiCad ships. The PCM package itself
is built and tested by the platform (api/tests/pcm). Needs jsonschema (in the
plugin's venv, as a kicad-python dependency) and an installed KiCad; skips
without either."""
import json
import os
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent

SCHEMAS = [Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/schemas"),
           Path("/usr/share/kicad/schemas"),
           Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "KiCad/10.0/share/kicad/schemas"]
SCHEMA_DIR = next((p for p in SCHEMAS if (p / "api.v1.schema.json").is_file()), None)

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None


@unittest.skipIf(jsonschema is None or SCHEMA_DIR is None, "jsonschema or KiCad schemas missing")
class Manifest(unittest.TestCase):
    def test_plugin_manifest(self):
        schema = json.loads((SCHEMA_DIR / "api.v1.schema.json").read_text())
        jsonschema.validate(json.loads((HERE / "plugin.json").read_text()), schema)


if __name__ == "__main__":
    unittest.main()
