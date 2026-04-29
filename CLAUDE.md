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

## Notes & Gotchas

### Footprints must always live under `7Sigma:` — never KiCad stock

Every component entry must reference a footprint from `Footprints/7Sigma.pretty/` with the `7Sigma:` namespace prefix. Never reference KiCad stock footprints (e.g. `Package_BGA:Xilinx_FTG256`, `Package_DFN_QFN:QFN-28_4x4mm_P0.5mm`) in YAML — the validator enforces `^7Sigma:` on every Footprint property.

If a needed footprint exists only in KiCad's standard library:
1. Copy the `.kicad_mod` file from `/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/<Lib>.pretty/<Name>.kicad_mod` into `Footprints/7Sigma.pretty/<Name>.kicad_mod`
2. Reference it as `7Sigma:<Name>` in the YAML
3. Resolve the 3D model (often missing from KiCad's default libs — fetch from EasyEDA)

Mixing in KiCad stock footprints creates external dependencies and breaks reproducibility. Localize everything, even if the symbol came from KiCad stock.

### EasyEDA API blocks the `easyeda2kicad` User-Agent

The `https://easyeda.com/api/products/{lcsc_id}/components` endpoint returns HTTP 403 when the `User-Agent` header contains "easyeda2kicad" or "python-requests". Both the auto-importer and the `easyeda2kicad` CLI then fail with `JSONDecodeError: Expecting value: line 1 column 1 (char 0)` because the 403 HTML is not JSON.

**Fix:** patch `.venv/lib/python3.14/site-packages/easyeda2kicad/easyeda/easyeda_api.py` to set `"User-Agent": "curl/8.1"` (or any non-blocked value — `curl/*`, `kiutils/*`, and empty UA all work). The patch lives in the venv, so it is lost on `pip install -e .` reinstalls. A proper fix would be a PR to the vendored fork.

### QA checklist for EasyEDA-imported footprints

EasyEDA-imported `.kicad_mod` files have two recurring defects that must be fixed before the import is considered done:

1. **Pad names stored as floats** — e.g. `(pad "1.0" …)` instead of `(pad "1" …)`. The symbol pins are integers, so schematic-to-PCB net mapping silently fails. Fix with `re.sub(r'\(pad "(\d+)\.0"', r'(pad "\1"', content)`.
2. **Wrong internal library prefix** — header reads `(footprint "easyeda2kicad:NAME"` but the repo convention is `(footprint "NAME"` with no prefix (the `7Sigma:` prefix comes from the `.pretty` folder name, not the file).

Both issues only appear on the EasyEDA fallback path — i.e. when no match exists in the YAML file's `defaults.footprint_map`. Inspect every new `.kicad_mod` for both before declaring the import complete.
