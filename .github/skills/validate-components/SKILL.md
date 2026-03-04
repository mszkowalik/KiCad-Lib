---
name: validate-components
description: Validate KiCad library component definitions. Use when the user wants to check YAML components for errors, verify footprints exist, check property patterns, or debug validation failures.
---

# Validate Component Definitions

This skill runs comprehensive validation on all YAML component definitions, base symbols, footprints, and property patterns.

## Prerequisites

Activate the virtual environment before running:

```bash
source .venv/bin/activate
```

## How to Run

### As part of the full pipeline

Validation runs automatically as step 3 of `python main.py`. If validation fails, generation is aborted.

### Standalone

```bash
python component_validator.py
```

This gives detailed error and warning output without running the rest of the pipeline.

## What Gets Validated

The `ComponentValidator` class runs these checks in order:

1. **YAML structure** — valid syntax, `library_name` matches filename, `components` list present
2. **Base components** — every `base_component` reference exists in `Symbols/base_library.kicad_sym`
3. **Component properties** — required properties present, non-empty checks, regex pattern matching per library-specific `validation_rules`
4. **Footprints** — every referenced `7Sigma:` footprint has a matching `.kicad_mod` file in `Footprints/7Sigma.pretty/`
5. **Footprint dimensions** — pad sizes, drill diameters, via sizes within acceptable ranges
6. **Template expressions** — `{PropertyKey}` references in values resolve to existing properties

## Validation Rules

Each YAML source file can define per-library validation rules:

```yaml
validation_rules:
  required_properties:
    - "Value"
    - "Power"
    - "Tolerance"
    - "Footprint"
  non_empty_properties:
    - "Value"
    - "Power"
    - "Tolerance"
  property_patterns:
    "Value": "^[0-9]+(\\.[0-9]+)?[RKMkm][0-9]*$"
    "Power": "^[0-9]+(\\.[0-9]+)?[mµnpkMGT]?W?$"
    "Tolerance": "^[0-9]+(\\.[0-9]+)?%$"
```

Global defaults (applied to all libraries) are defined in `component_validator.py`:

- `Footprint` must match `^7Sigma:`
- `LCSC Part` must match `^C\d+$`
- `Footprint` and `ki_description` are always required

## Configuration

The validator loads additional configuration from `tests/test_config.yaml` if it exists. Config keys:

- `required_properties` — properties every component must have
- `non_empty_properties` — properties that must not be empty
- `property_patterns` — regex patterns properties must match
- `max_property_length` — maximum character count for any property value (default: 200)
- `manufacturer_properties` — expected manufacturer/supplier property keys
- `footprint_dimensions` — min pad/drill/via size thresholds

## Reading Output

The validator prints a summary:

```
Library Statistics:
  Libraries: 15
  Components: 250
  Base Symbols: 80
  Footprints: 300

Validation Results:
  ✓ Validations passed: True
  ✗ Errors: 0
  ⚠ Warnings: 3
```

Errors block generation. Warnings are informational.

## Common Errors and Fixes

| Error | Fix |
|---|---|
| Base component `X` not found | Add the symbol to `Symbols/base_library.kicad_sym` or import via LCSC |
| Missing required property `Footprint` | Add the `Footprint` key to the component's YAML properties |
| Footprint file not found for `7Sigma:X` | Place `X.kicad_mod` in `Footprints/7Sigma.pretty/` |
| Property `Value` doesn't match pattern | Adjust the value to match the regex in `validation_rules.property_patterns` |
| Template `{Key}` references undefined property | Add the referenced property to the component before the templated property |
