# KiCad Library Management System

KiCad component library generator — YAML definitions → KiCad symbol libraries with automated 3D model management.

## Architecture

Template-based generation model:

| Layer | Path | Role |
|---|---|---|
| Base symbols | `Symbols/base_library.kicad_sym` | Graphical templates (resistor, capacitor, IC shapes) |
| YAML definitions | `Sources/*.yaml` | Component variants with properties and footprints |
| Generated libraries | `Symbols/<Type>.kicad_sym` | Final KiCad symbol libraries (output) |
| Footprints | `Footprints/7Sigma.pretty/` | KiCad footprint files |
| 3D models | `3DModels/` | STEP/WRL files, auto-resolved from multiple sources |

## Module Map

| Module | Responsibility |
|---|---|
| `main.py` | Entry point — orchestrates full pipeline |
| `config.py` | Centralized paths and environment configuration |
| `symbol_generator.py` | Deep-copies base symbols, applies YAML properties, writes `.kicad_sym` |
| `yaml_parser.py` | Loads YAML, evaluates `{Property}` template expressions |
| `update_footprints_models.py` | Normalizes 3D model paths, copies missing models |
| `component_validator.py` | Validates YAML structure, base refs, footprints, property patterns |
| `easyeda_importer.py` | Auto-imports components from LCSC/EasyEDA API |

## Conventions (Always Apply)

- **Virtual environment**: Always use `.venv` — activate with `source .venv/bin/activate`
- **Footprint namespace**: Always prefix custom footprints with `7Sigma:`
- **3D model paths**: Use `${SEVENSIGMA_DIR}/3DModels/` in footprint files
- **Property visibility**: New custom properties default to hidden (`hide: True`)
- **Base components**: Must exist in `base_library.kicad_sym` before YAML can reference them
- **File naming**: YAML `library_name` field must match the filename (e.g., `Resistor.yaml` → `library_name: Resistor`)
- **Property templating**: Use `{PropertyKey}` in YAML values — evaluated as f-strings at generation time
- **Linting**: Ruff with line-length 120, target Python 3.10

## Environment Variables

| Variable | Purpose |
|---|---|
| `SEVENSIGMA_DIR` | Project root — used in 3D model path references |
| `KICAD9_3DMODEL_DIR` | KiCad installation 3D models directory |
| `EASYEDA2KICAD` | easyeda2kicad output directory (optional) |

## Dependencies

Managed via `pyproject.toml` — install with `pip install -e .` inside `.venv`:

- **kiutils** — custom fork: `git+https://github.com/Wittmann-MEE/kiutils.git`
- **pyyaml** / **ruamel.yaml** — YAML parsing
- **easyeda2kicad** — LCSC component importing

## Running the Pipeline

```bash
source .venv/bin/activate
python main.py
```

The pipeline runs in order: auto-import → fill metadata → validate → generate symbols → update 3D models.

## Available Commands

- `/add-component` — Add a new component to the library
- `/import-easyeda` — Import a component from LCSC/EasyEDA by part number
- `/validate-components` — Validate all YAML component definitions
- `/generate-libraries` — Run the full generation pipeline
- `/verify-datasheets` — Verify components against manufacturer datasheets
- `/project-setup` — Set up or troubleshoot the development environment
