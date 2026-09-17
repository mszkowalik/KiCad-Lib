#!/bin/sh
# Rebuild api/app/services/bench_agent/vendor.zip — the pure-Python esptool the
# bench agent programs devices with (decision 0023).
#
# Pinned versions, pruned to what flashing needs, and checked for compiled
# code: a .so in here would tie the download to one machine. Run from the repo
# root with any Python 3; the result is byte-stable apart from timestamps.
set -eu
HERE=$(cd "$(dirname "$0")/.." && pwd)
OUT="$HERE/api/app/services/bench_agent/vendor.zip"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

python3 -m venv "$WORK/venv" >/dev/null
"$WORK/venv/bin/pip" -q install --target "$WORK/vendor" --no-deps --no-compile \
  esptool==4.8.1 pyserial==3.5 bitstring==4.3.1 ecdsa==0.19.1 intelhex==2.3.0 \
  reedsolo==1.7.0 PyYAML==6.0.2

cd "$WORK/vendor"
# Only what esptool's write_flash / erase_flash / chip_id paths import.
rm -rf bin ./*.dist-info espefuse espsecure esp_rfc2217_server _yaml
find . -name "__pycache__" -type d -prune -exec rm -rf {} +
find . -name "*.so" -delete      # PyYAML's optional accelerator; yaml runs pure
if find . -name "*.so" -o -name "*.dylib" -o -name "*.pyd" | grep -q .; then
  echo "compiled code in the vendor tree — refusing to ship it" >&2; exit 1
fi
rm -f "$OUT"
zip -qr -X "$OUT" . -x "*/__pycache__/*"

python3 - "$OUT" <<'PY'
import sys, zipfile, tempfile
z = zipfile.ZipFile(sys.argv[1]); d = tempfile.mkdtemp(); z.extractall(d); sys.path.insert(0, d)
import esptool, serial
stubs = sum(1 for n in z.namelist() if "stub_flasher" in n and n.endswith(".json"))
print(f"vendor.zip: esptool {esptool.__version__}, pyserial {serial.__version__}, {stubs} stub flashers, {len(z.namelist())} entries")
PY
