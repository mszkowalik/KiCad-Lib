# Component Validation System

This directory contains the comprehensive validation system for the KiCad Library Management System. The validation ensures component definitions are correct, complete, and consistent before library generation.

## Overview

The validation system provides two ways to run tests:

1. **Integrated Validation**: Automatically runs before library generation in `main.py`
2. **Standalone Validation**: Can be run independently for testing and debugging

## Files

- `test_components.py` - Pytest-based comprehensive test suite
- `component_validator.py` - Standalone validator (no pytest dependency)
- `test_config.yaml` - Configuration file for validation rules
- `README.md` - This documentation

## Quick Start

### Run Validation Only
```bash
# Standalone validator (recommended for CI/CD)
python component_validator.py

# With custom paths
python component_validator.py --sources ./Sources --footprints ./Footprints/7Sigma.pretty

# Pytest version (more detailed output)
python -m pytest tests/test_components.py -v
```

### Run Full Library Generation with Validation
```bash
# This automatically runs validation first
python main.py
```

## Validation Rules

The validation system checks for:

### 1. YAML Structure
- ✅ Valid YAML syntax
- ✅ `library_name` matches filename
- ✅ Required top-level keys (`components`)
- ✅ Proper data types

### 2. Component References
- ✅ All `base_component` references exist in `base_library.kicad_sym`
- ✅ Unique component names across all libraries
- ✅ Required component fields (`name`, `base_component`)

### 3. Component Properties
- ✅ Required properties are present
- ✅ Property values are not empty (where required)
- ✅ Property values match expected patterns
- ✅ Property values don't exceed length limits
- ✅ Template expressions `{PropertyName}` reference valid properties

### 4. Footprint Validation
- ✅ Footprint files exist in `Footprints/7Sigma.pretty/`
- ✅ Footprint names use valid prefixes (e.g., `7Sigma:`)
- ✅ Components that require footprints have them defined

### 5. Component Type-Specific Rules
- ✅ **Resistors**: Must have `Value`, `Power`, `Tolerance`
- ✅ **Capacitors**: Must have `Value`, `Voltage`
- ✅ **ICs**: Must have manufacturer information
- ✅ **LEDs**: Must have `Color`

### 6. Manufacturer Information
- ✅ At least one manufacturer property present:
  - `Manufacturer 1`
  - `Manufacturer Part Number 1`
  - `Supplier 1`
  - `Supplier Part Number 1`

## Configuration

Edit `test_config.yaml` to customize validation rules:

```yaml
# Add required properties for all components
required_properties:
  - "Footprint"
  - "ki_description"

# Define component-specific rules
component_type_rules:
  "Resistor":
    required_properties:
      - "Value"
      - "Power"
      - "Tolerance"
```

## Exit Codes

The validator uses standard exit codes:

- `0` - All validations passed
- `1` - Validation errors found (library generation will be blocked)

## Integration with CI/CD

Add to your CI pipeline:

```yaml
- name: Validate Components
  run: python component_validator.py
- name: Generate Libraries
  run: python main.py
```

## Example Output

```
Running KiCad Library Component Validation...
============================================================

Library Statistics:
  Libraries: 15
  Components: 1,234
  Base Symbols: 45
  Footprints: 156

Validation Results:
  ✓ Validations passed: True
  ✗ Errors: 0
  ⚠ Warnings: 3

Components per Library:
  Resistor: 357
  Capacitor: 234
  ICs: 123
  ...
```

## Adding New Validation Rules

### 1. Edit Configuration
Add new rules to `test_config.yaml`:

```yaml
property_patterns:
  "Custom_Property": "^CUSTOM_.*"  # Must start with CUSTOM_
```

### 2. Add Component Type Rules
```yaml
component_type_rules:
  "NewComponentType":
    required_properties:
      - "Special_Property"
    property_patterns:
      "Value": "^[0-9]+$"
```

### 3. Test Your Rules
```bash
python component_validator.py
```

## Troubleshooting

### Common Issues

1. **"Base component not found"**
   - Check that the `base_component` name exists in `Symbols/base_library.kicad_sym`
   - Verify spelling and case sensitivity

2. **"Footprint file not found"**
   - Ensure `.kicad_mod` file exists in `Footprints/7Sigma.pretty/`
   - Check footprint name spelling (without `7Sigma:` prefix)

3. **"Template variable not found"**
   - Verify that `{PropertyName}` references exist as component properties
   - Check for typos in template expressions

4. **"Property pattern mismatch"**
   - Check that property values match the expected format
   - Review regex patterns in `test_config.yaml`

### Debug Mode

For detailed debugging, use pytest with verbose output:

```bash
python -m pytest tests/test_components.py -v -s --tb=long
```

### Skipping Validation

To temporarily skip validation during development:

```bash
# Set environment variable
export SKIP_VALIDATION=1
python main.py
```

## Performance

- **Typical validation time**: 2-5 seconds for 1000+ components
- **Memory usage**: Low (validates incrementally)
- **Large libraries**: Handles 10,000+ components efficiently

## Contributing

When adding new validation rules:

1. Update `test_config.yaml` with new rules
2. Add corresponding validation logic to `component_validator.py`
3. Test with sample components
4. Update this README

## Future Enhancements

Planned improvements:

- [ ] Visual diff for component changes
- [ ] JSON/XML output formats
- [ ] Integration with KiCad ERC
- [ ] Automated fix suggestions
- [ ] Performance optimization for very large libraries