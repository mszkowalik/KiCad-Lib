Run the full library generation pipeline that transforms YAML component definitions into KiCad symbol libraries with automated 3D model management.

---

## Prerequisites

```bash
source .venv/bin/activate
```

If `.venv` doesn't exist yet:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Run

```bash
python main.py
```

This single command performs the full pipeline:

1. **Auto-import** — checks for missing base components and auto-imports from EasyEDA/LCSC
2. **Fill metadata** — fills missing properties from LCSC API for components with an LCSC Part number
3. **Validate** — runs `ComponentValidator` checks on all YAML definitions
4. **Generate symbols** — reads every `Sources/*.yaml`, deep-copies base symbols from `Symbols/base_library.kicad_sym`, applies YAML properties, writes output to `Symbols/<library_name>.kicad_sym`
5. **Update 3D models** — rewrites footprint model paths to use `${SEVENSIGMA_DIR}/3DModels/` and copies missing models from KiCad or EasyEDA sources

## Pipeline Details

### Symbol Generation Flow

`main.py` → `symbol_generator.generate_symbol_libraries()` → `yaml_parser.load_yaml_files()` + `create_or_update_library()`

- Each YAML file under `Sources/` maps to one output `.kicad_sym` file
- `library_name` in YAML **must** match the filename (e.g., `Resistor.yaml` → `library_name: Resistor`)
- Each component references a `base_component` from `Symbols/base_library.kicad_sym`
- Properties and template expressions like `{Value} {Power}` are evaluated via f-string substitution

### 3D Model Resolution

`update_footprints_models.py` scans all `.kicad_mod` files in `Footprints/7Sigma.pretty/` and:

- Normalizes model paths to `${SEVENSIGMA_DIR}/3DModels/<Category>.3dshapes/<Model>`
- Resolves source files in priority order:
  1. `${KICAD9_3DMODEL_DIR}/` — KiCad installation 3D models
  2. `${EASYEDA2KICAD}/` — easyeda2kicad output
  3. Local `3DModels/` cache
- Copies missing models into the local `3DModels/` directory

## Expected Output

```
📦 Component libraries created: 15
🔧 Total components generated: 250
👠 Footprints in library: 300
```

## Troubleshooting

- **Validation failures**: Run `python component_validator.py` standalone for detailed error info
- **KiCad version mismatch**: If KiCad can't open generated files, check `KIUTILS_CREATE_NEW_VERSION_STR` in `.venv/lib/python3.*/site-packages/kiutils/misc/config.py` — it must match the version string in `Symbols/base_library.kicad_sym`
- **Missing base component**: Ensure it exists in `Symbols/base_library.kicad_sym` before referencing it in YAML
