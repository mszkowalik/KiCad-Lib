---
name: add-component
description: Add a new component to the KiCad library by editing YAML source files. Use when the user wants to add a resistor, capacitor, IC, LED, connector, or any other component to an existing or new library. Supports adding via chat/agent interaction with automatic data retrieval from LCSC/EasyEDA.
argument-hint: "[component type] [part number, LCSC ID, or description]"
---

# Add a New Component

This skill guides the process of adding new components to the KiCad library. Components can be added either by manually editing YAML source files, or interactively via agent/chat by researching the component, retrieving data from LCSC/EasyEDA, and automating the entire workflow.

---

## Method 1: Agent-Assisted Component Addition (via Chat)

Use this method when an agent (e.g., Copilot) is adding a component on behalf of the user. The agent researches the component, retrieves metadata, edits the YAML, downloads assets, and verifies everything end-to-end.

### Overview

The agent performs these steps in sequence:

1. **Identify the component** — resolve what the user wants (part number, LCSC ID, or description)
2. **Retrieve component data** — fetch metadata from LCSC API and/or EasyEDA
3. **Determine the target YAML file** — match component category to the correct `Sources/*.yaml`
4. **Check for existing entry** — avoid duplicates
5. **Add the YAML entry** — either minimal (LCSC auto-import) or fully specified
6. **Download assets if needed** — footprint, 3D model, base symbol
7. **Run the full pipeline** — `python main.py` to generate and validate
8. **Verify the result** — confirm zero errors and the component appears in output

### Step 1: Identify the Component

The user may provide any of:
- An **LCSC part number** (e.g., `C2040`, `C432211`)
- A **manufacturer part number** (e.g., `STM32G031G8U6`, `GRM155R71C104KA88D`)
- A **description** (e.g., "100nF 0402 capacitor", "USB-C connector with ESD")

If the user provides a description or MPN without an LCSC number, the agent should:
1. Search LCSC for the component using the `fetch_webpage` tool (see Data Retrieval Commands below)
2. Confirm the LCSC part number with the user if ambiguous
3. Proceed with the resolved LCSC ID

### Step 2: Retrieve Component Data

#### LCSC API (primary metadata source)

Fetch component metadata using the LCSC API in a terminal:

```bash
curl -s "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C432211" | python3 -m json.tool
```

This returns a JSON object under `result` with these useful fields:

| JSON Field | Maps To | Description |
|---|---|---|
| `brandNameEn` | Manufacturer 1 | Manufacturer name |
| `productModel` | Manufacturer Part Number 1 | MPN |
| `productIntroEn` | ki_description | Component description |
| `pdfUrl` | Datasheet | Datasheet URL |
| `catalogName` | — | Category (helps pick the right YAML file) |
| `encapStandard` | Footprint_Name / package | Package type (e.g., "0402", "QFP-48", "SOT-23-3") |
| `productCode` | LCSC Part | LCSC part number |

Example with quick extraction:

```bash
curl -s "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C2040" \
  | python3 -c "import sys,json; r=json.load(sys.stdin).get('result',{}); print(f'MPN: {r.get(\"productModel\")}\nPkg: {r.get(\"encapStandard\")}\nCat: {r.get(\"catalogName\")}\nDesc: {r.get(\"productIntroEn\")}')"
```

#### LCSC Web Search (when user provides MPN or description, not LCSC ID)

Use `fetch_webpage` to search LCSC:

```
https://www.lcsc.com/search?q=STM32G031G8U6
```

Parse the results to find the correct LCSC part number, then use the API above.

#### EasyEDA CLI (download footprint, symbol, 3D model)

```bash
source .venv/bin/activate
easyeda2kicad --full --lcsc_id=C432211
```

Or download only specific assets:

```bash
# 3D model only
easyeda2kicad --lcsc_id=C432211 --output ./easyeda_tmp --3d

# Footprint only
easyeda2kicad --lcsc_id=C432211 --output ./easyeda_tmp --footprint

# Symbol only
easyeda2kicad --lcsc_id=C432211 --output ./easyeda_tmp --symbol
```

Downloaded files appear in:
- `./easyeda_tmp.3dshapes/` — STEP and WRL 3D models
- `./easyeda_tmp.pretty/` — KiCad footprint files
- `./easyeda_tmp.kicad_sym` — KiCad symbol library

**Always clean up temp files** after copying assets to their final locations:
```bash
rm -rf ./easyeda_tmp.3dshapes ./easyeda_tmp.pretty ./easyeda_tmp.kicad_sym
```

### Step 3: Determine the Target YAML File

Match the component category to the correct source file:

| Component Type | YAML File | Common Categories from LCSC |
|---|---|---|
| Resistors | `Sources/Resistor.yaml` | Chip Resistor, Resistors |
| Capacitors | `Sources/Capacitor.yaml` | Multilayer Ceramic Capacitors, Capacitors |
| ICs / Microcontrollers | `Sources/ICs.yaml` | Microcontrollers, IC, Embedded Processors |
| LEDs | `Sources/LEDs.yaml` | Light Emitting Diodes, LED |
| Diodes | `Sources/Diodes.yaml` | Diodes, Schottky, Zener |
| Connectors | `Sources/Connectors.yaml` | Connectors, Headers & Wire Housings |
| Inductors | `Sources/Inductors.yaml` | Inductors, Power Inductors |
| Transistors | `Sources/Transistors.yaml` | MOSFETs, Transistors, BJT |
| Buttons / Switches | `Sources/Buttons.yaml` | Tactile Switches, DIP Switches |
| Relays | `Sources/Relays.yaml` | Relays, Signal Relays |
| Circuit Protection | `Sources/Circuit_Protection.yaml` | TVS Diodes, ESD Protection, Fuses |
| RF Components | `Sources/RF.yaml` | RF Modules, Antennas |
| Timing (crystals, oscillators) | `Sources/Timing_Components.yaml` | Crystals, Oscillators |
| Test Points | `Sources/TestPoints.yaml` | Test Points |
| Mechanical | `Sources/Mechanical_7S.yaml` | Enclosures, Hardware |

### Step 4: Check for Duplicates

Before adding, verify the component doesn't already exist:

```bash
grep -r "COMPONENT_NAME_OR_LCSC_ID" Sources/*.yaml
```

### Step 5: Add the YAML Entry

#### Option A: Minimal Entry (LCSC auto-import) — Preferred

For components with an LCSC Part number, add a minimal entry. The pipeline's `auto_import_missing_components()` and `fill_missing_properties()` will automatically resolve everything:

```yaml
  - name: STM32G031G8U6
    properties:
      - key: LCSC Part
        value: "C432211"
```

This is the **preferred method** because the auto-importer handles:
- Downloading and adding the base symbol to `base_library.kicad_sym`
- Downloading the footprint to `Footprints/7Sigma.pretty/`
- Downloading the 3D model
- Filling manufacturer, MPN, datasheet, description, and footprint properties
- Using the `defaults` section (if present) for base_component and footprint mapping

#### Option B: Fully Specified Entry

When the component needs custom properties or the LCSC auto-import doesn't cover everything:

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

If the pipeline reports a missing 3D model after import, download it separately:

```bash
easyeda2kicad --lcsc_id=CXXXXXX --output ./easyeda_tmp --3d
```

Then copy the model to the correct 3D models subdirectory:

```bash
# Determine the target path from the footprint's model reference
grep "model" Footprints/7Sigma.pretty/FOOTPRINT_NAME.kicad_mod

# Copy to the expected location (rename to match footprint expectation)
cp ./easyeda_tmp.3dshapes/DOWNLOADED_NAME.step ./3DModels/CATEGORY.3dshapes/EXPECTED_NAME.step
cp ./easyeda_tmp.3dshapes/DOWNLOADED_NAME.wrl  ./3DModels/CATEGORY.3dshapes/EXPECTED_NAME.wrl

# Clean up
rm -rf ./easyeda_tmp.3dshapes ./easyeda_tmp.pretty ./easyeda_tmp.kicad_sym
```

### Step 6: Run the Full Pipeline

```bash
source .venv/bin/activate
python main.py
```

The pipeline performs (in order):
1. Auto-import — downloads missing base components from EasyEDA
2. Fill metadata — fills missing properties from LCSC API
3. Learn mappings — auto-learns footprint default mappings
4. Validate — runs `ComponentValidator` on all YAML definitions
5. Generate symbols — creates `.kicad_sym` output files
6. Update 3D models — normalizes model paths and copies missing models

### Step 7: Mandatory Post-Addition Verification

After running the pipeline, the agent **must** verify all of the following:

#### 7a. Pipeline Exit Code

The `python main.py` command must exit with code 0. Any non-zero exit code means errors occurred.

#### 7b. Zero Validation Errors

Check the pipeline output for:
```
✓ Component validation passed.
```

If validation fails, read the error messages and fix the YAML before proceeding.

#### 7c. Component Appears in Output

Verify the component is in the generated library:

```bash
grep "COMPONENT_NAME" Symbols/LIBRARY_NAME.kicad_sym
```

#### 7d. No 3D Model Warnings

Check for 3D model warnings in pipeline output:

```bash
python main.py 2>&1 | grep -i "could not resolve\|warning.*model"
```

If warnings appear for the new component's footprint, use the manual 3D model handling flow (Option C above).

#### 7e. Footprint Exists

Verify the footprint file is present:

```bash
ls Footprints/7Sigma.pretty/FOOTPRINT_NAME.kicad_mod
```

#### 7f. Summary Counts

Confirm the library summary shows the expected component count (previous count + number of new components added).

### Data Retrieval Commands Reference

| Purpose | Command |
|---|---|
| Fetch LCSC metadata | `curl -s "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=CXXXXXX"` |
| Search LCSC by MPN | Use `fetch_webpage` on `https://www.lcsc.com/search?q=PART_NUMBER` |
| Download full component | `easyeda2kicad --full --lcsc_id=CXXXXXX` |
| Download 3D model only | `easyeda2kicad --lcsc_id=CXXXXXX --output ./easyeda_tmp --3d` |
| Download footprint only | `easyeda2kicad --lcsc_id=CXXXXXX --output ./easyeda_tmp --footprint` |
| Check existing components | `grep -r "SEARCH_TERM" Sources/*.yaml` |
| Check existing footprints | `ls Footprints/7Sigma.pretty/ \| grep PATTERN` |
| Check existing 3D models | `find 3DModels/ -iname "*PATTERN*"` |
| Check base symbols | `grep "SYMBOL_NAME" Symbols/base_library.kicad_sym` |
| Validate standalone | `python component_validator.py` |
| Run full pipeline | `python main.py` |

### Rules for Agent-Driven Component Addition

1. **Always use LCSC Part numbers** when available — the auto-import pipeline handles most of the work
2. **Never guess property values** — always retrieve from LCSC API or datasheet
3. **Always use the `7Sigma:` namespace** for footprints
4. **Match existing patterns** — read 2-3 existing entries in the target YAML file before adding a new one to match formatting, property order, and naming conventions
5. **Validate before declaring done** — run `python main.py` and confirm zero errors and zero relevant warnings
6. **Clean up temporary files** — remove `easyeda_tmp.*` artifacts after use
7. **Check for duplicates first** — grep the YAML sources before adding
8. **Prefer minimal YAML entries** — let the auto-importer fill properties when possible; only add explicit properties when needed for overrides or custom values
9. **Report the final summary** — after successful addition, tell the user the component name, library, and total component count
10. **Handle missing 3D models** — if the pipeline warns about a missing model, download it from EasyEDA and place it in the correct `3DModels/` subdirectory

### Example: Agent Adding a Component End-to-End

User asks: "Add STM32G031G8U6 to the library"

1. **Search for LCSC ID**: `curl -s "https://wmsc.lcsc.com/ftps/wm/product/detail?productCode=C432211"` → confirms it's an MCU, UFQFPN-28 package
2. **Target file**: ICs → `Sources/ICs.yaml`
3. **Check duplicates**: `grep "STM32G031G8U6\|C432211" Sources/*.yaml` → not found
4. **Read existing entries**: Read `Sources/ICs.yaml` to match formatting
5. **Add minimal entry**:
   ```yaml
     - name: STM32G031G8U6
       properties:
         - key: LCSC Part
           value: "C432211"
   ```
6. **Run pipeline**: `python main.py` → auto-imports symbol + footprint, fills all metadata
7. **Verify**: Pipeline exits 0, validation passes, check for model warnings
8. **Handle 3D model** (if warning): Download via `easyeda2kicad --3d`, copy to `3DModels/`
9. **Report**: "Added STM32G031G8U6 to ICs library. 248 total components."

---

## Method 2: Manual YAML Editing

Use this method for manual component addition without agent assistance.

### Prerequisites

- Activate the virtual environment: `source .venv/bin/activate`
- The base symbol for the component **must** exist in `Symbols/base_library.kicad_sym`

### YAML Component Structure

Each component is defined in the matching `Sources/<Type>.yaml` file. The YAML structure is:

```yaml
library_name: ComponentType  # Must match filename without extension

components:
  - name: SpecificPartNumber        # Unique component name
    base_component: GenericBaseName  # Must exist in base_library.kicad_sym
    properties:
      - key: Value
        value: "5K1"
      - key: Power
        value: "63mW"
      - key: Tolerance
        value: "1%"
      - key: Footprint
        value: "7Sigma:R_0402_1005Metric"  # Always use 7Sigma: namespace
      - key: Footprint_Name
        value: "0402"
      - key: ki_description
        value: "{Value} {Power} {Tolerance} {Footprint_Name}"  # Template syntax
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
    remove_properties: []  # Optional list of properties to remove from base
```

### Step-by-Step Procedure

#### 1. Identify the Target YAML File

Match the component type to the existing source file:

| Component Type | YAML File |
|---|---|
| Resistors | `Sources/Resistor.yaml` |
| Capacitors | `Sources/Capacitor.yaml` |
| ICs / Microcontrollers | `Sources/ICs.yaml` |
| LEDs | `Sources/LEDs.yaml` |
| Diodes | `Sources/Diodes.yaml` |
| Connectors | `Sources/Connectors.yaml` |
| Inductors | `Sources/Inductors.yaml` |
| Transistors | `Sources/Transistors.yaml` |
| Buttons / Switches | `Sources/Buttons.yaml` |
| Relays | `Sources/Relays.yaml` |
| Circuit Protection | `Sources/Circuit_Protection.yaml` |
| RF Components | `Sources/RF.yaml` |
| Timing (crystals, oscillators) | `Sources/Timing_Components.yaml` |
| Test Points | `Sources/TestPoints.yaml` |
| Mechanical | `Sources/Mechanical_7S.yaml` |

#### 2. Check the Base Component

Verify that the `base_component` exists in `Symbols/base_library.kicad_sym`. Common base components:

- **R** — Standard resistor
- **C** — Standard capacitor
- **LED** — Standard LED
- **D** — Standard diode

If the base component doesn't exist, it must be added first (manually or via EasyEDA import).

#### 3. Add the Component Entry

Append a new component block to the `components:` list in the YAML file. Follow the existing patterns in that file for consistency.

#### 4. Footprint Conventions

- Always use the `7Sigma:` namespace prefix for footprints
- Footprint files must exist in `Footprints/7Sigma.pretty/`
- For new footprints: place the `.kicad_mod` file in `Footprints/7Sigma.pretty/`

#### 5. Property Templating

Use `{PropertyKey}` syntax in values (especially `ki_description`) to reference other properties:

```yaml
- key: ki_description
  value: "{Value} {Power} {Tolerance} {Footprint_Name}"
```

Properties are resolved at generation time via f-string evaluation.

#### 6. LCSC-Sourced Components (Shortcut)

For components from LCSC, you can provide a minimal YAML entry with just the LCSC part number, and the auto-importer will fill in the rest:

```yaml
  - name: STM32G031G8U6
    properties:
      - key: LCSC Part
        value: C432211
```

The importer automatically resolves the base component, footprint, manufacturer info, and datasheet.

#### 7. Validation Rules

Some YAML files define `validation_rules` that enforce constraints:

```yaml
validation_rules:
  required_properties: ["Value", "Power", "Tolerance", "Footprint"]
  non_empty_properties: ["Value", "Power", "Tolerance"]
  property_patterns:
    "Value": "^[0-9]+(\\.[0-9]+)?[RKMkm][0-9]*$"
```

Ensure new components satisfy these rules.

#### 8. Regenerate

After editing the YAML, regenerate the libraries:

```bash
python main.py
```

#### 9. Defaults Section

Some YAML files have a `defaults:` block that provides default `base_component` and `footprint_map` for imported components:

```yaml
defaults:
  base_component: R
  footprint_map:
    "0402": "7Sigma:R_0402_1005Metric"
    "0805": "7Sigma:R_0805_2012Metric"
```

When the auto-importer creates entries for these libraries, it uses these defaults so you only need the component name and LCSC Part number.
