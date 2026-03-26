Set up or troubleshoot the KiCad Library Management System development environment.

---

## Quick Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Virtual Environment

The project uses a Python `.venv` in the project root. **Always activate it** before running any project command:

```bash
source .venv/bin/activate
```

The venv is **not** committed to version control. If it doesn't exist, create it using the steps above.

## pyproject.toml

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

## Linting

```bash
ruff check .     # check
ruff format .    # format
```

Configuration in `pyproject.toml`: line-length 120, Python 3.10, rules include pycodestyle, pyflakes, isort, pyupgrade, flake8-bugbear, flake8-simplify.

## Environment Variables

| Variable | Purpose | Example |
|---|---|---|
| `SEVENSIGMA_DIR` | Project root for 3D model paths | `/Users/you/Projects/KiCad Lib` |
| `KICAD9_3DMODEL_DIR` | KiCad installation 3D models | `/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels` |
| `EASYEDA2KICAD` | easyeda2kicad output directory | (optional, for manual imports) |

The `config.py` file has `USER_KICAD9_3DMODEL_DIR` hardcoded for macOS. Update it if KiCad is installed elsewhere.

## Running the Project

```bash
python main.py    # full pipeline (recommended)
kicad-lib         # via installed entry point
```

## Troubleshooting

### pip install fails on kiutils
Ensure `git` is available: `git --version`

### KiCad version compatibility
If KiCad can't open generated `.kicad_sym` files:
1. Check your KiCad's version: `head -5 Symbols/base_library.kicad_sym`
2. Edit `.venv/lib/python3.*/site-packages/kiutils/misc/config.py`
3. Set `KIUTILS_CREATE_NEW_VERSION_STR` to match your KiCad version (e.g., `'20241209'`)
4. Re-run `python main.py`

### Missing easyeda2kicad
```bash
pip install -e .
which easyeda2kicad  # should point to .venv/bin/
```

### macOS KiCad path
Default path in `config.py`:
```
/Applications/KiCad/KiCad.app/Contents/SharedSupport/3dmodels
```
Update `USER_KICAD9_3DMODEL_DIR` in `config.py` if KiCad is installed elsewhere.
