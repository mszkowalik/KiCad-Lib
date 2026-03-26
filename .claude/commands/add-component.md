Add a new component to the KiCad library. Supports adding via LCSC part number, manufacturer part number, or description. Performs automatic data retrieval from LCSC/EasyEDA and end-to-end verification.

**Argument:** `$ARGUMENTS` (component type, part number, LCSC ID, or description)

---

## Method 1: Agent-Assisted Component Addition (Preferred)

The agent performs these steps in sequence:

1. **Identify the component** — resolve what the user wants (part number, LCSC ID, or description)
2. **Retrieve component data** — fetch metadata from LCSC API and/or EasyEDA
3. **Determine the target YAML file** — match component category to the correct `Sources/*.yaml`
4. **Check for existing entry** — avoid duplicates
5. **Add the YAML entry** — either minimal (LCSC auto-import) or fully specified
6. **Download assets if needed** — footprint, 3D model, base symbol
7. **Run the full pipeline** — `python main.py` to generate and validate
8. **Verify the result** — confirm zero errors and component appears in output

### Step 1: Identify the Component

The user may provide any of:
- An **LCSC part number** (e.g., `C2040`, `C432211`)
- A **manufacturer part number** (e.g., `STM32G031G8U6`, `GRM155R71C104KA88D`)
- A **description** (e.g., "100nF 0402 capacitor", "USB-C connector with ESD")

If the user provides a description or MPN without an LCSC number, search LCSC for the component:
```
https://www.lcsc.com/search?q=PART_NUMBER
```
Confirm the LCSC part number with the user if ambiguous, then proceed.

### Step 2: Retrieve Component Data

#### LCSC API (primary metadata source)

```bash
curl -s "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C432211" | python3 -m json.tool
```

Key fields from the JSON `result`:

| JSON Field | Maps To | Description |
|---|---|---|
| `brandNameEn` | Manufacturer 1 | Manufacturer name |
| `productModel` | Manufacturer Part Number 1 | MPN |
| `productIntroEn` | ki_description | Component description |
| `pdfUrl` | Datasheet | Datasheet URL |
| `catalogName` | — | Category (helps pick the right YAML file) |
| `encapStandard` | Footprint_Name / package | Package type (e.g., "0402", "QFP-48") |
| `productCode` | LCSC Part | LCSC part number |

Quick extraction:
```bash
curl -s "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C2040" \
  | python3 -c "import sys,json; r=json.load(sys.stdin).get('result',{}); print(f'MPN: {r.get(\"productModel\")}\nPkg: {r.get(\"encapStandard\")}\nCat: {r.get(\"catalogName\")}\nDesc: {r.get(\"productIntroEn\")}')"
```

#### EasyEDA CLI (download footprint, symbol, 3D model)

```bash
source .venv/bin/activate
easyeda2kicad --full --lcsc_id=C432211
```

Or download specific assets only:
```bash
easyeda2kicad --lcsc_id=C432211 --output ./easyeda_tmp --3d
easyeda2kicad --lcsc_id=C432211 --output ./easyeda_tmp --footprint
easyeda2kicad --lcsc_id=C432211 --output ./easyeda_tmp --symbol
```

Downloaded files appear in:
- `./easyeda_tmp.3dshapes/` — STEP and WRL 3D models
- `./easyeda_tmp.pretty/` — KiCad footprint files
- `./easyeda_tmp.kicad_sym` — KiCad symbol library

**Always clean up temp files** after copying assets:
```bash
rm -rf ./easyeda_tmp.3dshapes ./easyeda_tmp.pretty ./easyeda_tmp.kicad_sym
```

### Step 3: Determine the Target YAML File

| Component Type | YAML File | Common LCSC Categories |
|---|---|---|
| Resistors | `Sources/Resistor.yaml` | Chip Resistor, Resistors |
| Capacitors | `Sources/Capacitor.yaml` | Multilayer Ceramic Capacitors |
| ICs / Microcontrollers | `Sources/ICs.yaml` | Microcontrollers, IC, Embedded Processors |
| LEDs | `Sources/LEDs.yaml` | Light Emitting Diodes |
| Diodes | `Sources/Diodes.yaml` | Diodes, Schottky, Zener |
| Connectors | `Sources/Connectors.yaml` | Connectors, Headers & Wire Housings |
| Inductors | `Sources/Inductors.yaml` | Inductors, Power Inductors |
| Transistors | `Sources/Transistors.yaml` | MOSFETs, Transistors, BJT |
| Buttons / Switches | `Sources/Buttons.yaml` | Tactile Switches, DIP Switches |
| Relays | `Sources/Relays.yaml` | Relays, Signal Relays |
| Circuit Protection | `Sources/Circuit_Protection.yaml` | TVS Diodes, ESD Protection, Fuses |
| RF Components | `Sources/RF.yaml` | RF Modules, Antennas |
| Timing | `Sources/Timing_Components.yaml` | Crystals, Oscillators |
| Test Points | `Sources/TestPoints.yaml` | Test Points |
| Mechanical | `Sources/Mechanical_7S.yaml` | Enclosures, Hardware |

### Step 4: Check for Duplicates

```bash
grep -r "COMPONENT_NAME_OR_LCSC_ID" Sources/*.yaml
```

### Step 5: Add the YAML Entry

#### Option A: Minimal Entry (Recommended for LCSC components)

```yaml
  - name: STM32G031G8U6
    properties:
      - key: LCSC Part
        value: "C432211"
```

The auto-importer handles everything: base symbol, footprint, 3D model, manufacturer info, datasheet.

#### Option B: Fully Specified Entry

```yaml
  - name: SpecificPartNumber
    base_component: GenericBaseName
    properties:
      - key: Value
        value: "100nF"
      - key: Footprint
        value: "7Sigma:C_0402_1005Metric"
      - key: Footprint_Name
        value: "0402"
      - key: ki_description
        value: "{Value} {Footprint_Name} Capacitor"
      - key: Manufacturer 1
        value: "Murata"
      - key: Manufacturer Part Number 1
        value: "GRM155R71C104KA88D"
      - key: Supplier 1
        value: "LCSC"
      - key: Supplier Part Number 1
        value: "C307331"
      - key: LCSC Part
        value: "C307331"
      - key: Datasheet
        value: "https://datasheet.example.com/..."
```

#### Option C: Manual 3D Model Handling

If the pipeline reports a missing 3D model after import:
```bash
easyeda2kicad --lcsc_id=CXXXXXX --output ./easyeda_tmp --3d
grep "model" Footprints/7Sigma.pretty/FOOTPRINT_NAME.kicad_mod
cp ./easyeda_tmp.3dshapes/DOWNLOADED_NAME.step ./3DModels/CATEGORY.3dshapes/EXPECTED_NAME.step
cp ./easyeda_tmp.3dshapes/DOWNLOADED_NAME.wrl  ./3DModels/CATEGORY.3dshapes/EXPECTED_NAME.wrl
rm -rf ./easyeda_tmp.3dshapes ./easyeda_tmp.pretty ./easyeda_tmp.kicad_sym
```

### Step 6: Run the Full Pipeline

```bash
source .venv/bin/activate
python main.py
```

### Step 7: Mandatory Post-Addition Verification

#### 7a. Pipeline must exit with code 0

#### 7b. Zero validation errors
Check for:
```
✓ Component validation passed.
```

#### 7c. Component appears in output
```bash
grep "COMPONENT_NAME" Symbols/LIBRARY_NAME.kicad_sym
```

#### 7d. No 3D model warnings
```bash
python main.py 2>&1 | grep -i "could not resolve\|warning.*model"
```

#### 7e. Footprint exists
```bash
ls Footprints/7Sigma.pretty/FOOTPRINT_NAME.kicad_mod
```

#### 7f. Summary count matches expectation (previous count + new components added)

### Rules

1. **Always use LCSC Part numbers** when available
2. **Never guess property values** — always retrieve from LCSC API or datasheet
3. **Always use the `7Sigma:` namespace** for footprints
4. **Match existing patterns** — read 2-3 existing entries in the target YAML before adding
5. **Validate before declaring done** — confirm zero errors and zero relevant warnings
6. **Clean up temporary files** — remove `easyeda_tmp.*` artifacts after use
7. **Check for duplicates first**
8. **Prefer minimal YAML entries** — let the auto-importer fill properties when possible
9. **Report the final summary** — component name, library, and total component count
10. **Handle missing 3D models** — download from EasyEDA and place in correct `3DModels/` subdirectory

### Example End-to-End

User asks: "Add STM32G031G8U6 to the library"

1. Fetch LCSC data: `curl -s "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C432211"` → MCU, UFQFPN-28
2. Target file: `Sources/ICs.yaml`
3. Check duplicates: `grep "STM32G031G8U6\|C432211" Sources/*.yaml` → not found
4. Read existing entries in `Sources/ICs.yaml` to match formatting
5. Add minimal entry with `LCSC Part: C432211`
6. Run `python main.py` → auto-imports symbol + footprint, fills metadata
7. Verify: exit 0, validation passes, check for model warnings
8. Handle 3D model if warned: `easyeda2kicad --3d`, copy to `3DModels/`
9. Report: "Added STM32G031G8U6 to ICs library. 248 total components."

---

## Method 2: Manual YAML Editing

### YAML Component Structure

```yaml
library_name: ComponentType  # Must match filename without extension

components:
  - name: SpecificPartNumber
    base_component: GenericBaseName  # Must exist in base_library.kicad_sym
    properties:
      - key: Value
        value: "5K1"
      - key: Power
        value: "63mW"
      - key: Tolerance
        value: "1%"
      - key: Footprint
        value: "7Sigma:R_0402_1005Metric"
      - key: Footprint_Name
        value: "0402"
      - key: ki_description
        value: "{Value} {Power} {Tolerance} {Footprint_Name}"
      - key: Manufacturer 1
        value: "Manufacturer Name"
      - key: Manufacturer Part Number 1
        value: "MPN"
      - key: Supplier 1
        value: "LCSC"
      - key: Supplier Part Number 1
        value: "C123456"
      - key: LCSC Part
        value: "C123456"
      - key: Datasheet
        value: "https://..."
    remove_properties: []  # Optional: properties to remove from base
```

Key rules:
- `base_component` must exist in `Symbols/base_library.kicad_sym`
- Footprints always use `7Sigma:` namespace, file must exist in `Footprints/7Sigma.pretty/`
- Use `{PropertyKey}` syntax in values for template expressions
- After editing, run `python main.py` to regenerate
