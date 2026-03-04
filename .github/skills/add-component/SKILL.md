---
name: add-component
description: Add a new component to the KiCad library by editing YAML source files. Use when the user wants to add a resistor, capacitor, IC, LED, connector, or any other component to an existing or new library.
argument-hint: "[component type] [part number or values]"
---

# Add a New Component

This skill guides the process of adding new components to the KiCad library by editing the appropriate YAML source file under `Sources/`.

## Prerequisites

- Activate the virtual environment: `source .venv/bin/activate`
- The base symbol for the component **must** exist in `Symbols/base_library.kicad_sym`

## YAML Component Structure

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

## Step-by-Step Procedure

### 1. Identify the Target YAML File

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

### 2. Check the Base Component

Verify that the `base_component` exists in `Symbols/base_library.kicad_sym`. Common base components:

- **R** — Standard resistor
- **C** — Standard capacitor
- **LED** — Standard LED
- **D** — Standard diode

If the base component doesn't exist, it must be added first (manually or via EasyEDA import).

### 3. Add the Component Entry

Append a new component block to the `components:` list in the YAML file. Follow the existing patterns in that file for consistency.

### 4. Footprint Conventions

- Always use the `7Sigma:` namespace prefix for footprints
- Footprint files must exist in `Footprints/7Sigma.pretty/`
- For new footprints: place the `.kicad_mod` file in `Footprints/7Sigma.pretty/`

### 5. Property Templating

Use `{PropertyKey}` syntax in values (especially `ki_description`) to reference other properties:

```yaml
- key: ki_description
  value: "{Value} {Power} {Tolerance} {Footprint_Name}"
```

Properties are resolved at generation time via f-string evaluation.

### 6. LCSC-Sourced Components (Shortcut)

For components from LCSC, you can provide a minimal YAML entry with just the LCSC part number, and the auto-importer will fill in the rest:

```yaml
  - name: STM32G031G8U6
    properties:
      - key: LCSC Part
        value: C432211
```

The importer automatically resolves the base component, footprint, manufacturer info, and datasheet.

### 7. Validation Rules

Some YAML files define `validation_rules` that enforce constraints:

```yaml
validation_rules:
  required_properties: ["Value", "Power", "Tolerance", "Footprint"]
  non_empty_properties: ["Value", "Power", "Tolerance"]
  property_patterns:
    "Value": "^[0-9]+(\\.[0-9]+)?[RKMkm][0-9]*$"
```

Ensure new components satisfy these rules.

### 8. Regenerate

After editing the YAML, regenerate the libraries:

```bash
python main.py
```

### 9. Defaults Section

Some YAML files have a `defaults:` block that provides default `base_component` and `footprint_map` for imported components:

```yaml
defaults:
  base_component: R
  footprint_map:
    "0402": "7Sigma:R_0402_1005Metric"
    "0805": "7Sigma:R_0805_2012Metric"
```

When the auto-importer creates entries for these libraries, it uses these defaults so you only need the component name and LCSC Part number.
