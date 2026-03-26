Import a component from LCSC/EasyEDA into the KiCad library, including downloading symbols, footprints, and 3D models.

**Argument:** `$ARGUMENTS` (LCSC part number, e.g. C2040)

---

## Prerequisites

```bash
source .venv/bin/activate
```

The `easyeda2kicad` package must be installed (listed in `pyproject.toml` dependencies).

## Method 1: Minimal YAML Entry (Recommended)

Add a minimal entry to the appropriate `Sources/<Type>.yaml` file:

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

## Method 2: Using Defaults

Some YAML files have a `defaults:` section that provides automatic base component and footprint mapping:

```yaml
defaults:
  base_component: R
  footprint_map:
    "0402": "7Sigma:R_0402_1005Metric"
    "0805": "7Sigma:R_0805_2012Metric"
```

For these libraries, only `name` + `LCSC Part` are needed in the YAML entry.

## Method 3: Standalone easyeda2kicad CLI

For manual one-off imports outside the automated pipeline:

```bash
easyeda2kicad --full --lcsc_id=C2040
```

Downloads files to the easyeda2kicad output directory. You then need to manually:
- Move the footprint to `Footprints/7Sigma.pretty/`
- Add the base symbol to `base_library.kicad_sym`

## What Gets Downloaded

| Artifact | Destination |
|---|---|
| Symbol | Added to `Symbols/base_library.kicad_sym` |
| Footprint | `Footprints/7Sigma.pretty/<name>.kicad_mod` |
| 3D Model (STEP) | `3DModels/easyeda2kicad.3dshapes/<name>.step` |

## LCSC API Metadata

The importer fetches these properties from `https://wmsc.lcsc.com/ftps/wm/product/detail?productCode={LCSC_ID}`:

- Manufacturer name, MPN, Description, Datasheet URL, Package type, Category

## Key Functions in easyeda_importer.py

- **`auto_import_missing_components()`** — scans all YAML files, finds components with LCSC Part but missing base_component, downloads and integrates them
- **`fill_missing_properties()`** — for already-imported components, fills missing metadata from LCSC API
- **`_download_and_import(lcsc_id, base_component_name)`** — core function that fetches CAD data and places all files

## After Importing

Run `python main.py` to regenerate all libraries.

## Troubleshooting

- **"Failed to fetch CAD data"** — the LCSC ID may be invalid or the EasyEDA API may be temporarily down
- **Footprint name collision** — if a footprint already exists in `7Sigma.pretty/`, the importer skips re-downloading
- **Missing 3D model** — some EasyEDA components don't have STEP models; this is non-fatal
- **Network errors** — the importer needs internet access for LCSC API and EasyEDA API calls
