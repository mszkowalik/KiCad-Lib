# KiCad Library Management System

This is a KiCad component library generator that transforms YAML component definitions into KiCad symbol libraries with automated 3D model management.

## Architecture Overview

The system operates on a **template-based generation model**:
- **Base symbols** (`Symbols/base_library.kicad_sym`) contain the graphical representations (resistor, capacitor, IC shapes)
- **YAML definitions** (`Sources/*.yaml`) specify component variants with specific properties and footprints
- **Generated libraries** (`Symbols/<ComponentType>.kicad_sym`) are the final KiCad symbol libraries
- **3D model pipeline** automatically resolves and copies 3D models from multiple sources

## Core Components

### Main Entry Point (`main.py`)
- **Unified workflow**: Single command `python main.py` generates both symbol libraries and updates 3D model paths
- **Error handling**: Graceful error reporting for each processing stage
- **Status feedback**: Clear progress indicators for each operation

### Symbol Generation (`symbol_generator.py`)
- **Primary workflow**: `generate_symbol_libraries()` → `create_or_update_library()` → `update_component_properties()`
- **Base component inheritance**: Each YAML component references a `base_component` from `base_library.kicad_sym`
- **Symbol unit management**: Automatically renames symbol units to match component names

### YAML Processing (`yaml_parser.py`)
- **Property templating**: Use `{PropertyKey}` syntax in YAML values (e.g., `ki_description: "{Value} {Power} {Tolerance} {Footprint_Name}"`)
- **Property management**: New properties are hidden by default (`hide: True`), existing properties can be modified or removed
- **Template evaluation**: Dynamic property value generation using f-string evaluation

### 3D Model Management (`update_footprints_models.py`)
- **Integrated workflow**: Automatically called by `main.py`
- **Source mapping**: Resolves 3D models from KiCad standard library, easyeda2kicad output, or local cache
- **Path normalization**: All footprint models rewritten to use `${SEVENSIGMA_DIR}/3DModels/` prefix
- **Auto-copy**: Missing models automatically copied to local `3DModels/` directory preserving `.3dshapes` structure
- **Source priority**: `${KICAD9_3DMODEL_DIR}/` → `${EASYEDA2KICAD}/` → local cache

### YAML Component Structure
```yaml
library_name: ComponentType  # Output filename
components:
  - name: SpecificPartNumber
    base_component: GenericBaseName  # From base_library.kicad_sym
    properties:
      - key: Value
        value: "5K1"  # Can use {Property} templating
      - key: Footprint
        value: "7Sigma:R_0402_1005Metric"  # Always use 7Sigma namespace
    remove_properties: [PropertyToRemove]  # Optional
```

## Key Workflows

### Complete Library Update
**Single command**: `python main.py` - Updates both symbol libraries and 3D model paths

### Adding New Components
1. Define in appropriate `Sources/<Type>.yaml` file using existing base component
2. Run `python main.py` to regenerate symbol libraries and update 3D models
3. For new footprints: place in `Footprints/7Sigma.pretty/`

### Importing from LCSC/EasyEDA
Use the command pattern from `README.MD`: `easyeda2kicad --full --lcsc_id=C2040`

### Dependencies
- **kiutils**: KiCad file format manipulation (custom fork from Wittmann-MEE)
- **pyyaml**: YAML parsing for component definitions

## Critical Conventions

- **Footprint namespace**: Always use `7Sigma:` prefix for custom footprints
- **3D model paths**: Use `${SEVENSIGMA_DIR}/3DModels/` for environment-agnostic references  
- **Property visibility**: Custom properties default to hidden, use `hide: False` to show
- **Base components**: Must exist in `base_library.kicad_sym` before referencing in YAML
- **File naming**: YAML `library_name` determines output `.kicad_sym` filename

## Environment Variables
- `SEVENSIGMA_DIR`: Points to this library root for 3D model path resolution
- `KICAD9_3DMODEL_DIR`: KiCad installation 3D models directory
- `EASYEDA2KICAD`: Path to easyeda2kicad output directory