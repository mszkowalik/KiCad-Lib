---
name: project-setup
description: Set up or troubleshoot the KiCad Library Management System development environment. Use when the user needs to install dependencies, create the virtual environment, configure environment variables, or fix setup issues.
---

# Project Setup

This skill covers setting up and maintaining the development environment for the KiCad Library Management System.

## Quick Setup

```bash
# 1. Create virtual environment
python3 -m venv .venv

# 2. Activate it
source .venv/bin/activate

# 3. Install the project in editable mode (installs all dependencies)
pip install -e .
```

## Virtual Environment

The project uses a Python `.venv` in the project root. **Always activate it** before running any project command:

```bash
source .venv/bin/activate
```

The venv is **not** committed to version control. If it doesn't exist, create it using the steps above.

## pyproject.toml

The project is configured via `pyproject.toml` with:

- **Python**: >= 3.10
- **Build system**: setuptools >= 68.0
- **Entry point**: `kicad-lib` CLI command maps to `main:main`

### Dependencies

| Package | Purpose |
|---|---|
| `pyyaml` | YAML parsing for component definitions |
| `ruamel.yaml` | Round-trip YAML editing (preserves formatting) |
| `kiutils` | KiCad file format manipulation (custom fork from `Wittmann-MEE/kiutils`) |
| `easyeda2kicad` | LCSC/EasyEDA component downloading and conversion |

The `kiutils` dependency is installed from a **custom Git fork**:
```
kiutils @ git+https://github.com/Wittmann-MEE/kiutils.git
```

### Linting

The project uses **Ruff** for linting and formatting:

```bash
# Check
ruff check .

# Format
ruff format .
```

Configuration in `pyproject.toml`:
- Line length: 120
- Target: Python 3.10
- Rules: pycodestyle, pyflakes, isort, pyupgrade, flake8-bugbear, flake8-simplify

## Environment Variables

These environment variables are used at runtime for 3D model resolution. They are configured in `config.py` and in KiCad:

| Variable | Purpose | Example |
|---|---|---|
| `SEVENSIGMA_DIR` | Project root for 3D model paths | `/Users/you/Projects/KiCad Lib` |
| `KICAD9_3DMODEL_DIR` | KiCad installation 3D models | `/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels` |
| `EASYEDA2KICAD` | easyeda2kicad output directory | (optional, for manual imports) |

The `config.py` file has `USER_KICAD9_3DMODEL_DIR` hardcoded for macOS. Update it if your KiCad is installed elsewhere.

## Project Structure

```
.
├── main.py                    # Entry point — runs full pipeline
├── config.py                  # Centralized path configuration
├── symbol_generator.py        # Generates .kicad_sym from YAML + base symbols
├── yaml_parser.py             # Loads YAML, evaluates property templates
├── update_footprints_models.py # 3D model path normalization and copying
├── component_validator.py     # Standalone + integrated validation
├── easyeda_importer.py        # Auto-import from LCSC/EasyEDA
├── pyproject.toml             # Project metadata and dependencies
├── Sources/                   # YAML component definitions (input)
├── Symbols/                   # KiCad symbol libraries (output)
│   └── base_library.kicad_sym # Base symbols (graphical templates)
├── Footprints/
│   └── 7Sigma.pretty/         # KiCad footprint files
└── 3DModels/                  # 3D model files (.step/.wrl)
```

## Running the Project

```bash
# Full pipeline (recommended)
python main.py

# Or via the installed entry point
kicad-lib
```

## Troubleshooting

### pip install fails on kiutils

The `kiutils` fork requires Git. Ensure `git` is available in your PATH:
```bash
git --version
```

### KiCad version compatibility

If KiCad can't open generated `.kicad_sym` files, the kiutils version string may be too new. Fix:

1. Check your KiCad's version: `head -5 Symbols/base_library.kicad_sym`
2. Edit `.venv/lib/python3.*/site-packages/kiutils/misc/config.py`
3. Set `KIUTILS_CREATE_NEW_VERSION_STR` to match your KiCad version (e.g., `'20241209'`)
4. Re-run `python main.py`

### Missing easyeda2kicad

If `easyeda2kicad` commands fail:
```bash
pip install -e .   # reinstall all deps
which easyeda2kicad  # should point to .venv/bin/
```

### macOS KiCad path

The default 3D model path in `config.py` assumes the standard macOS KiCad installation:
```
/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels
```
Update `USER_KICAD9_3DMODEL_DIR` in `config.py` if KiCad is installed elsewhere.
