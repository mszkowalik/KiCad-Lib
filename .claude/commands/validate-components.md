Run comprehensive validation on all YAML component definitions, base symbols, footprints, 3D models, and PDF pin assignments.

**Argument:** `$ARGUMENTS` (optional: component name, library name, or leave empty to validate all)

---

## Step 1: Run the Automated Validator

```bash
source .venv/bin/activate
python -m kicad_lib.kicad.validator
```

Or as part of the full pipeline (runs automatically at step 3):
```bash
python main.py
```

### What the automated validator checks

1. **YAML structure** — valid syntax, `library_name` matches filename, `components` list present
2. **Base component references** — every `base_component` exists in `Symbols/base_library.kicad_sym`; component names unique within each library
3. **Component properties** — required properties present, non-empty checks, regex pattern matching per `validation_rules`, property length, manufacturer info present
4. **Footprint files** — every `7Sigma:X` footprint reference has a matching `X.kicad_mod` in `Footprints/7Sigma.pretty/`
5. **Footprint dimensions** — drill holes ≥ 0.3mm, through-hole pads ≥ 0.6mm, vias ≥ 0.3mm (configurable via `tests/test_config.yaml`)
6. **Template expressions** — `{PropertyKey}` references in values resolve to existing properties

### Validation rules per library (in YAML)

```yaml
validation_rules:
  required_properties: ["Value", "Power", "Tolerance", "Footprint"]
  non_empty_properties: ["Value", "Power", "Tolerance"]
  property_patterns:
    "Value": "^[0-9]+(\\.[0-9]+)?[RKMkm][0-9]*$"
    "Power": "^[0-9]+(\\.[0-9]+)?[mµnpkMGT]?W?$"
    "Tolerance": "^[0-9]+(\\.[0-9]+)?%$"
  footprint_required: true   # set false for purely virtual components
  manufacturer_properties: []  # set empty to disable manufacturer check
  conditional_required_properties:
    - base_component: "STM32"
      requirements: ["LCSC Part", "Datasheet"]
```

Global defaults (all libraries): `Footprint` → `^7Sigma:`, `LCSC Part` → `^C\d+$`, `Footprint` and `ki_description` always required.

### Suppressing false positives

Add a text annotation inside the footprint file to suppress specific dimension checks:
```
(fp_text user "validation: ignore_min_pad_size" ...)
```

---

## Step 2: Cross-Library Duplicate Detection

The automated validator only checks uniqueness within a single library. Run this to find duplicates across all libraries:

### Duplicate LCSC Part numbers
```bash
grep -h "value: \"C[0-9]" Sources/*.yaml | sort | uniq -d
```

### Duplicate component names
```bash
grep -h "^  - name:" Sources/*.yaml | sort | uniq -d
```

If duplicates are found: keep the component in the most appropriate library and remove the duplicate. If intentional (same part, different footprint), add a distinguishing suffix to the name.

---

## Step 3: 3D Model File Existence

The automated validator does not check whether 3D model files referenced in footprints actually exist locally. Run this check manually:

```bash
source .venv/bin/activate
python3 - <<'EOF'
import os, re
from pathlib import Path

footprints_dir = Path("Footprints/7Sigma.pretty")
models_root = Path("3DModels")
sevensigma_prefix = "${SEVENSIGMA_DIR}/3DModels/"

missing = []
for fp_file in sorted(footprints_dir.glob("*.kicad_mod")):
    content = fp_file.read_text()
    for match in re.finditer(r'\(model\s+"([^"]+)"', content):
        model_path = match.group(1)
        if model_path.startswith(sevensigma_prefix):
            rel = model_path[len(sevensigma_prefix):]
            local = models_root / rel
            if not local.exists():
                missing.append(f"{fp_file.name}: {rel}")

if missing:
    print(f"Missing 3D models ({len(missing)}):")
    for m in missing: print(f"  {m}")
else:
    print("All 3D models present.")
EOF
```

Fix: download missing models with `easyeda2kicad --lcsc_id=CXXXXXX --3d` and copy to the correct `3DModels/<Category>.3dshapes/` subdirectory.

---

## Step 4: Footprint–Symbol Pin Count Cross-Check

Mismatch between the number of pads in a footprint and pins in its base symbol is a critical error that won't be caught elsewhere. Check for any component you add or modify:

```bash
source .venv/bin/activate
python3 - <<'EOF'
import re
from pathlib import Path

def count_footprint_pads(fp_path):
    content = Path(fp_path).read_text()
    # Count non-fabrication pads (exclude np_thru_hole for mounting holes in some cases)
    pads = re.findall(r'\(pad\s+"?([^"\s)]+)"?\s+(smd|thru_hole|np_thru_hole)', content)
    # Exclude mounting hole pads (np_thru_hole or named "MP")
    return [p for p in pads if p[1] != 'np_thru_hole' and p[0] not in ('""', '')]

def count_symbol_pins(base_lib_content, symbol_name):
    # Find symbol block
    pattern = rf'\(symbol "{re.escape(symbol_name)}".*?(?=\n\(symbol |\Z)'
    match = re.search(pattern, base_lib_content, re.DOTALL)
    if not match:
        return None
    return re.findall(r'\(number\s+"([^"]+)"', match.group())

base_lib = Path("Symbols/base_library.kicad_sym").read_text()

import yaml
for yaml_file in sorted(Path("Sources").glob("*.yaml")):
    data = yaml.safe_load(yaml_file.read_text()) or {}
    for comp in data.get("components", []):
        fp_prop = next((p["value"] for p in comp.get("properties", []) if p.get("key") == "Footprint"), None)
        base = comp.get("base_component")
        if not fp_prop or not base or not fp_prop.startswith("7Sigma:"):
            continue
        fp_name = fp_prop[7:]
        fp_path = Path(f"Footprints/7Sigma.pretty/{fp_name}.kicad_mod")
        if not fp_path.exists():
            continue
        pads = count_footprint_pads(fp_path)
        pins = count_symbol_pins(base_lib, base)
        if pins is None:
            continue
        if len(pads) != len(pins):
            print(f"MISMATCH {comp['name']}: footprint has {len(pads)} pads, symbol '{base}' has {len(pins)} pins")
EOF
```

Any mismatch reported here is a serious error — the footprint and symbol must have exactly the same number of electrically connected pads/pins.

---

## Step 5: Orphan Detection

### Orphaned footprints (in library but not used by any YAML component)

```bash
python3 - <<'EOF'
import yaml
from pathlib import Path

used = set()
for f in Path("Sources").glob("*.yaml"):
    data = yaml.safe_load(f.read_text()) or {}
    for comp in data.get("components", []):
        for prop in comp.get("properties", []):
            if prop.get("key") == "Footprint" and str(prop.get("value","")).startswith("7Sigma:"):
                used.add(prop["value"][7:])

all_fps = {p.stem for p in Path("Footprints/7Sigma.pretty").glob("*.kicad_mod")}
orphans = sorted(all_fps - used)
if orphans:
    print(f"Orphaned footprints ({len(orphans)}):")
    for o in orphans: print(f"  {o}")
else:
    print("No orphaned footprints.")
EOF
```

Orphaned footprints are not errors, but review them — they may be unused assets that should be cleaned up, or footprints awaiting a component entry.

### Orphaned base symbols (in base_library but not referenced by any YAML)

```bash
python3 - <<'EOF'
import re, yaml
from pathlib import Path

used = set()
for f in Path("Sources").glob("*.yaml"):
    data = yaml.safe_load(f.read_text()) or {}
    for comp in data.get("components", []):
        if comp.get("base_component"):
            used.add(comp["base_component"])

base_lib = Path("Symbols/base_library.kicad_sym").read_text()
defined = set(re.findall(r'\(symbol "([^"]+)"', base_lib))
# Remove sub-unit entries (contain underscore + number at end, e.g. "R_0_1")
defined = {s for s in defined if not re.match(r'.+_\d+$', s)}
orphans = sorted(defined - used)
if orphans:
    print(f"Unused base symbols ({len(orphans)}):")
    for o in orphans: print(f"  {o}")
else:
    print("No unused base symbols.")
EOF
```

---

## Step 6: Footprint Quality Checks

For each footprint file, verify it has the required KiCad layers. Missing layers cause DRC errors in KiCad:

```bash
python3 - <<'EOF'
from pathlib import Path

REQUIRED_LAYERS = ["F.CrtYd", "F.Fab", "F.SilkS"]  # B.* acceptable for bottom-only parts

issues = []
for fp_file in sorted(Path("Footprints/7Sigma.pretty").glob("*.kicad_mod")):
    content = fp_file.read_text()
    missing = [l for l in REQUIRED_LAYERS if l not in content and l.replace("F.", "B.") not in content]
    if missing:
        issues.append(f"{fp_file.name}: missing layers {missing}")

if issues:
    print(f"Layer issues ({len(issues)}):")
    for i in issues: print(f"  {i}")
else:
    print("All footprints have required layers.")
EOF
```

| Layer | Purpose |
|---|---|
| `F.CrtYd` / `B.CrtYd` | Courtyard — required for DRC clearance checks |
| `F.Fab` / `B.Fab` | Fabrication layer — component body outline |
| `F.SilkS` / `B.SilkS` | Silkscreen — reference designator and polarity marker |

---

## Step 7: Datasheet URL Check

For components with a `Datasheet` property, verify the URLs are well-formed and accessible:

```bash
source .venv/bin/activate
python3 - <<'EOF'
import yaml, urllib.request, urllib.error
from pathlib import Path

issues = []
for f in sorted(Path("Sources").glob("*.yaml")):
    data = yaml.safe_load(f.read_text()) or {}
    lib = data.get("library_name", f.stem)
    for comp in data.get("components", []):
        name = comp.get("name", "?")
        for prop in comp.get("properties", []):
            if prop.get("key") != "Datasheet":
                continue
            url = str(prop.get("value") or "")
            if not url or url in ("~", "null", "None"):
                continue
            if not url.startswith("http"):
                issues.append(f"[{lib}] {name}: malformed URL: {url}")
                continue
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
                with urllib.request.urlopen(req, timeout=5) as r:
                    if r.status >= 400:
                        issues.append(f"[{lib}] {name}: HTTP {r.status} — {url}")
            except Exception as e:
                issues.append(f"[{lib}] {name}: unreachable — {e}")

if issues:
    print(f"Datasheet issues ({len(issues)}):")
    for i in issues: print(f"  {i}")
else:
    print("All datasheets reachable.")
EOF
```

Note: This makes network requests. Skip for offline environments. A 404 means the datasheet URL is stale — update it from the LCSC API.

---

## Step 8: ki_description Quality Review

`ki_description` that still contains unresolved `{...}` placeholders, or that is too generic, will appear poorly in KiCad's symbol chooser. Check manually:

```bash
grep -h "ki_description" Sources/*.yaml | grep -E "\{[A-Za-z]" | head -20
```

Also flag descriptions that are suspiciously short or generic:
```bash
python3 - <<'EOF'
import yaml
from pathlib import Path
for f in Path("Sources").glob("*.yaml"):
    data = yaml.safe_load(f.read_text()) or {}
    lib = data.get("library_name", f.stem)
    for comp in data.get("components", []):
        for prop in comp.get("properties", []):
            if prop.get("key") == "ki_description":
                v = str(prop.get("value") or "")
                if len(v) < 5 or v in ("~", "None", "null"):
                    print(f"[{lib}] {comp['name']}: empty/short description: '{v}'")
EOF
```

---

## Step 9: PDF Pin Assignment Verification

This step is essential for large ICs (QFN, BGA, LQFP, etc.) where a single wrong pin can silently break a design. It downloads the component's datasheet PDF, extracts the text, and uses AI-assisted analysis to compare the pin table against the base symbol.

**Requires:** `pymupdf` (already in `.venv`), internet access for PDF download.

### 9a. Extract text from the datasheet PDF

Run this for a specific component (replace `COMPONENT_NAME` with the actual name):

```bash
source .venv/bin/activate
python3 - <<'EOF'
import sys, re, yaml, urllib.request
from pathlib import Path
import fitz  # pymupdf

COMPONENT = "COMPONENT_NAME"   # <-- change this

# Find the component's datasheet URL
url = None
for f in Path("Sources").glob("*.yaml"):
    data = yaml.safe_load(f.read_text()) or {}
    for comp in data.get("components", []):
        if comp["name"] != COMPONENT:
            continue
        for prop in comp.get("properties", []):
            if prop.get("key") == "Datasheet":
                url = str(prop.get("value") or "")
        break
    if url:
        break

if not url or not url.startswith("http"):
    print(f"No datasheet URL found for {COMPONENT}")
    sys.exit(1)

print(f"Downloading: {url}")
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as r:
    pdf_bytes = r.read()

doc = fitz.open(stream=pdf_bytes, filetype="pdf")
out = Path(f"_datasheet_{COMPONENT}.txt")
with open(out, "w") as f:
    for i, page in enumerate(doc):
        f.write(f"\n{'='*60}\nPAGE {i+1}\n{'='*60}\n")
        f.write(page.get_text())

print(f"Extracted {len(doc)} pages → {out}")
EOF
```

### 9b. Extract symbol pins from base library

```bash
python3 - <<'EOF'
import re, yaml
from pathlib import Path

COMPONENT = "COMPONENT_NAME"   # <-- change this (use base_component name)

# Find the base_component name from YAML
base_comp = None
for f in Path("Sources").glob("*.yaml"):
    data = yaml.safe_load(f.read_text()) or {}
    for comp in data.get("components", []):
        if comp["name"] == COMPONENT:
            base_comp = comp.get("base_component", COMPONENT)
            break
    if base_comp:
        break

base_comp = base_comp or COMPONENT
base_lib = Path("Symbols/base_library.kicad_sym").read_text()

# Find the symbol block
# KiCad symbols are nested: outer block has pins, inner _n_m blocks are units
pattern = rf'\(symbol "{re.escape(base_comp)}"(.*?)(?=\n  \(symbol "(?!{re.escape(base_comp)}_)|\Z)'
match = re.search(pattern, base_lib, re.DOTALL)
if not match:
    print(f"Symbol '{base_comp}' not found in base_library.kicad_sym")
else:
    pins = re.findall(
        r'\(pin\s+\S+\s+\S+\s*\(at[^)]+\)[^(]*\(name\s+"([^"]*)"[^)]*\)[^(]*\(number\s+"([^"]*)"',
        match.group(0)
    )
    print(f"Symbol: {base_comp} — {len(pins)} pins")
    for name, num in sorted(pins, key=lambda x: (len(x[1]), x[1])):
        print(f"  Pin {num:>4}  {name}")
EOF
```

### 9c. AI-assisted comparison

After running the two scripts above, read both outputs and perform the comparison:

1. **Read the extracted datasheet text** (`_datasheet_<COMPONENT>.txt`). Search for these keywords to locate the pin table:
   - `pin assignment`, `pin description`, `pin configuration`, `pin function`, `pinout`
   - The specific package name (e.g., `QFN-28`, `UFQFPN28`, `LQFP-48`)

2. **Identify the correct package column.** Datasheets often cover multiple packages in the same pin table. Match the `Footprint` property against the table column header:
   - `QFN-*` → look for QFN / UQFN / VQFN / DFN / UFQFPN columns
   - `LQFP-*` → LQFP column
   - `SOIC-*` → SOIC / SOP column
   - `TSSOP-*` → TSSOP column

3. **Build a pin map from the datasheet:** `{pin_number: pin_name}` for the correct package.

4. **Compare against the symbol pins** from step 9b:

   | Check | Severity |
   |---|---|
   | Pin number exists in symbol but not in datasheet | **Error** — extra pin |
   | Pin number exists in datasheet but not in symbol | **Error** if it's a signal/power pin; OK if NC |
   | Pin name mismatch for same pin number | **Error** if functional name differs; OK for minor formatting (`_`, `[]`, spaces) |
   | Thermal/exposed pad present in footprint but not in symbol | **Warning** — may need EP pin |

5. **Record findings** in `Datasheets/verification_report.yaml` (see `/verify-datasheets` for the report format).

### 9d. Batch verification for a whole library

To verify all ICs (or any library) with datasheets in one session:

```bash
python3 - <<'EOF'
import yaml
from pathlib import Path

TARGET_LIBRARY = "ICs"   # <-- change to target library name

for f in Path("Sources").glob("*.yaml"):
    data = yaml.safe_load(f.read_text()) or {}
    if data.get("library_name") != TARGET_LIBRARY:
        continue
    print(f"\n{'='*60}")
    print(f"Library: {TARGET_LIBRARY}")
    print(f"{'='*60}")
    for comp in data.get("components", []):
        name = comp["name"]
        base = comp.get("base_component", "?")
        ds = next((p["value"] for p in comp.get("properties", []) if p.get("key") == "Datasheet"), None)
        fp = next((p["value"] for p in comp.get("properties", []) if p.get("key") == "Footprint"), None)
        status = "✓ has datasheet" if ds and str(ds).startswith("http") else "✗ NO DATASHEET"
        print(f"  {name:<40} base={base:<30} fp={fp}  [{status}]")
EOF
```

Then work through the list top-to-bottom, running steps 9a–9c for each component that has a datasheet URL. Prioritize complex packages (BGA, QFN, LQFP) over simple 2-6 pin packages.

### 9e. Cleanup

Remove the temporary extracted text files when done:

```bash
rm -f _datasheet_*.txt
```

### Common pin verification issues

| Issue | What to look for |
|---|---|
| Multi-package datasheet | The pin table has columns per package — read the correct column only |
| Thermal/exposed pad | Often pad N+1 on an N-pin QFN/DFN. Check if symbol includes an EP pin |
| Alternate pin functions | `PA11[PA9]` or `TXD/GPIO` — the primary function is what matters |
| NC (no connect) pins | Acceptable to omit from symbol; note in verification report |
| Power supply grouping | Some symbols merge multiple VDD/VSS pins — intentional for clarity |
| Pulled-up/pulled-down pins | These still need to be in the symbol |
| Pin name minor formatting | `OSC32IN` vs `OSC32_IN` — cosmetic, not an error |

---

## Reading Automated Validator Output

```
Library Statistics:
  Libraries: 15
  Components: 250
  Base Symbols: 80
  Footprints: 300

Validation Results:
  ✓ Validations passed: True
  ✗ Errors: 0
  ⚠ Warnings: 3
```

Errors block generation. Warnings are informational.

## Common Errors and Fixes

| Error | Fix |
|---|---|
| Base component `X` not found | Add the symbol to `Symbols/base_library.kicad_sym` or import via LCSC |
| Missing required property `Footprint` | Add the `Footprint` key to the component's YAML properties |
| Footprint file not found for `7Sigma:X` | Place `X.kicad_mod` in `Footprints/7Sigma.pretty/` |
| Property `Value` doesn't match pattern | Adjust the value to match the regex in `validation_rules.property_patterns` |
| Template `{Key}` references undefined property | Add the referenced property to the component before the templated property |
| Drill hole < 0.3mm | Use `validation: ignore_min_pad_size` annotation in footprint if intentional |
| Footprint–symbol pin count mismatch | Re-import the footprint or the base symbol from EasyEDA |
| Missing `F.CrtYd` layer | Edit the footprint to add a courtyard outline |
| Duplicate LCSC Part across libraries | Remove duplicate, keep in the more appropriate library |
| Pin name mismatch vs. datasheet | Correct pin name in base symbol in `base_library.kicad_sym` |
| Extra/missing pins vs. datasheet | Re-import base symbol from EasyEDA or fix manually in base library |
