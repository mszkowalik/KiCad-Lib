
# KiCad Library Management System

This is a KiCad component library generator that transforms YAML component definitions into KiCad symbol libraries with automated 3D model management.

## Quick Start

To download components from LCSC:

```bash
easyeda2kicad --full --lcsc_id=C2040
```

## Troubleshooting

### KiCad Version Compatibility Issues

If KiCad cannot open the generated symbol libraries or shows version-related errors, the issue may be caused by kiutils using a version string that's too new for your KiCad installation.

**Symptoms:**
- KiCad fails to open generated `.kicad_sym` files
- Error messages about unsupported file format versions
- Libraries appear corrupted or unreadable

**Solution:**
1. Check your existing KiCad files for the version string:
   ```bash
   head -5 Symbols/base_library.kicad_sym
   ```
   Look for a line like `(version 20241209)`

2. Update the kiutils configuration to match:
   ```bash
   # Edit the kiutils config file
   nano .venv/lib/python3.13/site-packages/kiutils/misc/config.py
   ```

3. Change `KIUTILS_CREATE_NEW_VERSION_STR` to match your KiCad version:
   ```python
   # Before (too new):
   KIUTILS_CREATE_NEW_VERSION_STR = '20250526'
   
   # After (compatible):
   KIUTILS_CREATE_NEW_VERSION_STR = '20241209'  # Use your KiCad's version
   ```

4. Regenerate the libraries:
   ```bash
   python main.py
   ```

**Note:** The Wittmann-MEE kiutils fork sometimes uses future version strings that aren't yet supported by stable KiCad releases. Always match the version string to your KiCad installation.