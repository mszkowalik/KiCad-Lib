---
name: import-easyeda
description: Import components from LCSC/EasyEDA into the KiCad library. Use when the user wants to import a component by LCSC part number, download symbols/footprints/3D models from EasyEDA, or add an LCSC component with minimal YAML.
argument-hint: "[LCSC part number e.g. C2040]"
---

# Import Components from LCSC/EasyEDA

This skill handles importing electronic components from LCSC/EasyEDA, including downloading symbols, footprints, and 3D models, then integrating them into the KiCad library.

## Prerequisites

Activate the virtual environment:

```bash
source .venv/bin/activate
```

The `easyeda2kicad` package must be installed (it is listed in `pyproject.toml` dependencies).

## Methods of Importing

### Method 1: Minimal YAML Entry (Recommended)

Add a minimal entry to the appropriate `Sources/<Type>.yaml` file with just the LCSC Part number:

```yaml
  - name: STM32G031G8U6
    properties:
      - key: LCSC Part
        value: C432211
```

Then run `python main.py`. The auto-importer (`easyeda_importer.py`) will:

1. Detect that the component's `base_component` is missing or unresolved
2. Fetch metadata from LCSC API (manufacturer, MPN, description, datasheet, package info)
3. Call the EasyEDA API to download symbol, footprint, and 3D model (STEP)
4. Add the base symbol to `Symbols/base_library.kicad_sym`
5. Copy the footprint to `Footprints/7Sigma.pretty/` with normalized model paths
6. Copy the 3D model to `3DModels/easyeda2kicad.3dshapes/`
7. Update the YAML file with all resolved properties (base_component, Footprint, Manufacturer, Datasheet, etc.)

### Method 2: Using Defaults

Some YAML files have a `defaults:` section that provides automatic base component and footprint mapping:

```yaml
defaults:
  base_component: R
  footprint_map:
    "0402": "7Sigma:R_0402_1005Metric"
    "0805": "7Sigma:R_0805_2012Metric"
```

For these libraries, the importer uses the default base component and maps EasyEDA package names (e.g., "0402") to the correct `7Sigma:` footprint. The YAML entry only needs `name` + `LCSC Part`.

### Method 3: Standalone easyeda2kicad CLI

For manual one-off imports (outside the automated pipeline):

```bash
easyeda2kicad --full --lcsc_id=C2040
```

This downloads files to the easyeda2kicad output directory. You then need to manually move the footprint to `Footprints/7Sigma.pretty/` and add the base symbol to `base_library.kicad_sym`.

## Auto-Import Pipeline Details

The `easyeda_importer.py` module contains these key functions:

- **`auto_import_missing_components()`** — scans all YAML files, finds components with LCSC Part but missing/unresolved base_component, downloads and integrates them
- **`fill_missing_properties()`** — for already-imported components, fills missing metadata (manufacturer, datasheet, description) from LCSC API
- **`_download_and_import(lcsc_id, base_component_name)`** — core function that fetches CAD data and places all files

## What Gets Downloaded

| Artifact | Destination |
|---|---|
| Symbol | Added to `Symbols/base_library.kicad_sym` |
| Footprint | `Footprints/7Sigma.pretty/<name>.kicad_mod` |
| 3D Model (STEP) | `3DModels/easyeda2kicad.3dshapes/<name>.step` |

## LCSC API Metadata

The importer fetches these properties from `https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={LCSC_ID}`:

- Manufacturer name
- Manufacturer Part Number (MPN)
- Description
- Datasheet URL
- Package type (e.g., "0402", "QFP-48")
- Category

## After Importing

Run `python main.py` to regenerate all libraries. The new component will appear in the corresponding `.kicad_sym` output file.

## Troubleshooting

- **"Failed to fetch CAD data"** — the LCSC ID may be invalid or the EasyEDA API may be temporarily down
- **Footprint name collision** — if a footprint already exists in `7Sigma.pretty/`, the importer skips re-downloading
- **Missing 3D model** — some EasyEDA components don't have STEP models; this is non-fatal
- **Network errors** — the importer needs internet access for LCSC API and EasyEDA API calls
