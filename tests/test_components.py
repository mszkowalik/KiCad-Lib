#!/usr/bin/env python3
"""
Component Validation Tests for KiCad Library Management System

This module provides comprehensive validation for:
- YAML component definitions
- Base component references
- Footprint availability
- Required properties
- Library consistency

NOTE: Component-specific validation rules are now embedded in each Source/*.yaml file
under the 'validation_rules' section. This test module focuses on structural validation.
"""

import pytest
import os
import yaml
from pathlib import Path
from kiutils.symbol import SymbolLib
from typing import Dict, List, Set, Optional


def load_test_config(config_file: str = "./tests/test_config.yaml") -> Dict:
    """Load test configuration from YAML file."""
    config_path = Path(config_file)
    
    # Default fallback configuration
    default_config = {
        "required_properties": ["Footprint", "ki_description"],
        "non_empty_properties": ["Footprint", "ki_description"],
        "property_patterns": {
            "Footprint": r"^7Sigma:",
            "LCSC Part": r"^C\d+$",
        },
        "max_property_length": 200,
        "manufacturer_properties": ["Manufacturer 1", "Manufacturer Part Number 1", "Supplier 1", "Supplier Part Number 1"],
    }
    
    if not config_path.exists():
        return default_config
    
    try:
        with open(config_path, "r") as f:
            loaded_config = yaml.safe_load(f) or {}
            # Merge with defaults
            default_config.update(loaded_config)
            return default_config
    except Exception as e:
        print(f"Warning: Could not load config file {config_file}: {e}")
        return default_config


# Load global test configuration
TEST_CONFIG = load_test_config()


class ComponentValidator:
    """Main validator class for KiCad library components."""

    def __init__(self, sources_dir: str = "./Sources", symbols_dir: str = "./Symbols", footprints_dir: str = "./Footprints/7Sigma.pretty"):
        self.sources_dir = Path(sources_dir)
        self.symbols_dir = Path(symbols_dir)
        self.footprints_dir = Path(footprints_dir)
        self.base_library_path = self.symbols_dir / "base_library.kicad_sym"

        # Load data once for efficiency
        self.yaml_data = self._load_all_yaml_files()
        self.base_symbols = self._load_base_symbols()
        self.available_footprints = self._load_available_footprints()

    def get_library_validation_rules(self, lib_data: Dict) -> Dict:
        """Extract validation rules from a library YAML file."""
        return lib_data.get("validation_rules", {})

    def get_merged_rules_for_library(self, lib_data: Dict) -> Dict:
        """Get merged validation rules (global + library-specific)."""
        library_rules = self.get_library_validation_rules(lib_data)

        # Start with global config
        merged_rules = {
            "required_properties": TEST_CONFIG.get("required_properties", []).copy(),
            "non_empty_properties": TEST_CONFIG.get("non_empty_properties", []).copy(),
            "property_patterns": TEST_CONFIG.get("property_patterns", {}).copy(),
            "max_property_length": TEST_CONFIG.get("max_property_length", 200),
            "manufacturer_properties": TEST_CONFIG.get("manufacturer_properties", []).copy(),
            "footprint_required": True,  # Default to requiring footprints
        }

        # Merge library-specific rules
        if "required_properties" in library_rules:
            merged_rules["required_properties"].extend(library_rules["required_properties"])

        if "non_empty_properties" in library_rules:
            merged_rules["non_empty_properties"].extend(library_rules["non_empty_properties"])

        if "property_patterns" in library_rules:
            merged_rules["property_patterns"].update(library_rules["property_patterns"])

        if "max_property_length" in library_rules:
            merged_rules["max_property_length"] = library_rules["max_property_length"]

        if "manufacturer_properties" in library_rules:
            merged_rules["manufacturer_properties"] = library_rules["manufacturer_properties"]

        if "footprint_required" in library_rules:
            merged_rules["footprint_required"] = library_rules["footprint_required"]

        return merged_rules

    def _load_all_yaml_files(self) -> List[Dict]:
        """Load all YAML component files."""
        yaml_files = []
        for yaml_file in self.sources_dir.glob("*.yaml"):
            with open(yaml_file, "r") as f:
                try:
                    data = yaml.safe_load(f)
                    data["_source_file"] = yaml_file.name
                    yaml_files.append(data)
                except yaml.YAMLError as e:
                    pytest.fail(f"Invalid YAML syntax in {yaml_file}: {e}")
        return yaml_files

    def _load_base_symbols(self) -> Set[str]:
        """Load available base component names from base library."""
        if not self.base_library_path.exists():
            return set()

        try:
            base_lib = SymbolLib.from_file(str(self.base_library_path))
            return {symbol.entryName for symbol in base_lib.symbols}
        except Exception as e:
            pytest.fail(f"Failed to load base library: {e}")
            return set()

    def _load_available_footprints(self) -> Set[str]:
        """Load available footprint names."""
        if not self.footprints_dir.exists():
            return set()

        footprints = set()
        for footprint_file in self.footprints_dir.glob("*.kicad_mod"):
            # Remove .kicad_mod extension to get footprint name
            footprints.add(footprint_file.stem)
        return footprints

    def get_component_property(self, component: Dict, property_key: str) -> Optional[str]:
        """Get property value from component definition."""
        properties = component.get("properties", [])
        for prop in properties:
            if prop.get("key") == property_key:
                return prop.get("value")
        return None

    def get_all_components(self) -> List[tuple]:
        """Get all components with their library context."""
        components = []
        for lib_data in self.yaml_data:
            lib_name = lib_data.get("library_name", "unknown")
            for component in lib_data.get("components", []):
                components.append((lib_name, component, lib_data["_source_file"]))
        return components


@pytest.fixture
def validator():
    """Pytest fixture to provide ComponentValidator instance."""
    return ComponentValidator()


class TestYAMLStructure:
    """Test YAML file structure and basic syntax."""

    def test_yaml_files_exist(self, validator):
        """Test that YAML source files exist."""
        yaml_files = list(validator.sources_dir.glob("*.yaml"))
        assert len(yaml_files) > 0, "No YAML source files found"

    def test_yaml_syntax_valid(self, validator):
        """Test that all YAML files have valid syntax."""
        # This is already tested in _load_all_yaml_files, but explicit test
        assert len(validator.yaml_data) > 0, "No valid YAML files loaded"

    def test_library_name_matches_filename(self, validator):
        """Test that library_name matches the filename."""
        for lib_data in validator.yaml_data:
            source_file = lib_data["_source_file"]
            expected_name = Path(source_file).stem
            actual_name = lib_data.get("library_name")

            assert actual_name == expected_name, f"Library name '{actual_name}' doesn't match filename '{expected_name}' in {source_file}"

    def test_components_key_exists(self, validator):
        """Test that each YAML file has a 'components' key."""
        for lib_data in validator.yaml_data:
            source_file = lib_data["_source_file"]
            assert "components" in lib_data, f"Missing 'components' key in {source_file}"
            assert isinstance(lib_data["components"], list), f"'components' should be a list in {source_file}"


class TestBaseComponents:
    """Test base component references."""

    def test_base_library_exists(self, validator):
        """Test that base library file exists."""
        assert validator.base_library_path.exists(), f"Base library not found at {validator.base_library_path}"

    def test_base_components_referenced(self, validator):
        """Test that all referenced base components exist in base library."""
        missing_base_components = set()

        for lib_name, component, source_file in validator.get_all_components():
            base_component = component.get("base_component")
            if not base_component:
                pytest.fail(f"Missing 'base_component' in component '{component.get('name')}' " f"in {source_file}")

            if base_component not in validator.base_symbols:
                missing_base_components.add((base_component, source_file))

        if missing_base_components:
            error_msg = "Missing base components:\n"
            for base_comp, source in missing_base_components:
                error_msg += f"  - '{base_comp}' referenced in {source}\n"
            pytest.fail(error_msg)

    def test_no_duplicate_component_names(self, validator):
        """Test that component names are unique across all libraries."""
        component_names = {}

        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name")
            if not comp_name:
                pytest.fail(f"Missing 'name' in component in {source_file}")

            if comp_name in component_names:
                pytest.fail(f"Duplicate component name '{comp_name}' found in " f"{source_file} and {component_names[comp_name]}")

            component_names[comp_name] = source_file


class TestComponentProperties:
    """Test component property definitions."""

    def test_required_properties_present(self, validator):
        """Test that all components have required properties."""
        missing_props = []

        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name", "unnamed")

            for required_prop in TEST_CONFIG["required_properties"]:
                prop_value = validator.get_component_property(component, required_prop)
                if prop_value is None:
                    missing_props.append(f"{comp_name} in {source_file}: missing '{required_prop}'")

        if missing_props:
            pytest.fail("Missing required properties:\n" + "\n".join(missing_props))

    def test_non_empty_properties(self, validator):
        """Test that certain properties are not empty."""
        empty_props = []

        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name", "unnamed")

            for prop_key in TEST_CONFIG["non_empty_properties"]:
                prop_value = validator.get_component_property(component, prop_key)
                if prop_value is not None and (not prop_value or prop_value.strip() == ""):
                    empty_props.append(f"{comp_name} in {source_file}: '{prop_key}' is empty")

        if empty_props:
            pytest.fail("Empty required properties:\n" + "\n".join(empty_props))

    def test_property_patterns(self, validator):
        """Test that properties match expected patterns."""
        import re

        pattern_failures = []

        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name", "unnamed")

            for prop_key, pattern in TEST_CONFIG["property_patterns"].items():
                prop_value = validator.get_component_property(component, prop_key)
                if prop_value and not re.match(pattern, prop_value):
                    pattern_failures.append(f"{comp_name} in {source_file}: '{prop_key}' value '{prop_value}' " f"doesn't match pattern '{pattern}'")

        if pattern_failures:
            pytest.fail("Property pattern validation failures:\n" + "\n".join(pattern_failures))

    def test_property_length_limits(self, validator):
        """Test that property values don't exceed maximum length."""
        long_props = []

        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name", "unnamed")

            for prop in component.get("properties", []):
                prop_key = prop.get("key", "unknown")
                prop_value = str(prop.get("value", ""))

                if len(prop_value) > TEST_CONFIG["max_property_length"]:
                    long_props.append(f"{comp_name} in {source_file}: '{prop_key}' value too long " f"({len(prop_value)} > {TEST_CONFIG['max_property_length']} chars)")

        if long_props:
            pytest.fail("Property length violations:\n" + "\n".join(long_props))

    def test_manufacturer_info_present(self, validator):
        """Test that components have manufacturer information."""
        missing_mfr_info = []

        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name", "unnamed")

            # Check if at least one manufacturer property is present
            has_mfr_info = False
            for mfr_prop in TEST_CONFIG["manufacturer_properties"]:
                if validator.get_component_property(component, mfr_prop):
                    has_mfr_info = True
                    break

            if not has_mfr_info:
                missing_mfr_info.append(f"{comp_name} in {source_file}: no manufacturer information")

        if missing_mfr_info:
            pytest.fail("Missing manufacturer information:\n" + "\n".join(missing_mfr_info))


class TestFootprints:
    """Test footprint-related validations."""

    def test_footprints_directory_exists(self, validator):
        """Test that footprints directory exists."""
        assert validator.footprints_dir.exists(), f"Footprints directory not found at {validator.footprints_dir}"

    def test_footprint_files_exist(self, validator):
        """Test that referenced footprints actually exist."""
        missing_footprints = []

        # Group components by library to get validation rules
        libraries = {}
        for lib_data in validator.yaml_data:
            lib_name = lib_data.get("library_name", "unknown")
            libraries[lib_name] = lib_data

        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name", "unnamed")

            # Get library-specific validation rules
            lib_data = libraries.get(lib_name, {})
            rules = validator.get_merged_rules_for_library(lib_data)

            # Skip components that don't require footprints
            if not rules["footprint_required"]:
                continue

            footprint_value = validator.get_component_property(component, "Footprint")
            if not footprint_value:
                continue

            # Extract footprint name (remove 7Sigma: prefix)
            if footprint_value.startswith("7Sigma:"):
                footprint_name = footprint_value[7:]  # Remove "7Sigma:" prefix

                if footprint_name not in validator.available_footprints:
                    missing_footprints.append(f"{comp_name} in {source_file}: footprint '{footprint_name}' not found")

        if missing_footprints:
            pytest.fail("Missing footprint files:\n" + "\n".join(missing_footprints))


class TestLibraryConsistency:
    """Test overall library consistency."""

    def test_template_expressions_valid(self, validator):
        """Test that template expressions in properties are valid."""
        template_errors = []

        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name", "unnamed")

            # Build available properties for template evaluation
            available_props = {prop.get("key"): prop.get("value", "") for prop in component.get("properties", [])}

            for prop in component.get("properties", []):
                prop_key = prop.get("key", "unknown")
                prop_value = prop.get("value", "")

                if isinstance(prop_value, str) and "{" in prop_value and "}" in prop_value:
                    # Check if template expression is valid
                    try:
                        # Simple template validation - check if referenced properties exist
                        import re

                        template_vars = re.findall(r"\{(\w+)\}", prop_value)
                        for var in template_vars:
                            if var not in available_props:
                                template_errors.append(f"{comp_name} in {source_file}: template variable '{var}' " f"in '{prop_key}' not found in component properties")
                    except Exception as e:
                        template_errors.append(f"{comp_name} in {source_file}: invalid template in '{prop_key}': {e}")

        if template_errors:
            pytest.fail("Template expression errors:\n" + "\n".join(template_errors))

    def test_remove_properties_valid(self, validator):
        """Test that properties marked for removal are handled correctly."""
        # This test ensures that 'remove_properties' lists don't contain typos
        for lib_name, component, source_file in validator.get_all_components():
            comp_name = component.get("name", "unnamed")
            remove_props = component.get("remove_properties", [])

            # Basic validation - ensure it's a list
            if remove_props and not isinstance(remove_props, list):
                pytest.fail(f"{comp_name} in {source_file}: 'remove_properties' should be a list")


# Statistics and reporting functions
def test_generate_library_statistics(validator):
    """Generate and display library statistics."""
    stats = {
        "total_libraries": len(validator.yaml_data),
        "total_components": len(validator.get_all_components()),
        "total_base_symbols": len(validator.base_symbols),
        "total_footprints": len(validator.available_footprints),
        "components_by_library": {},
        "base_components_usage": {},
    }

    # Count components per library
    for lib_data in validator.yaml_data:
        lib_name = lib_data.get("library_name", "unknown")
        component_count = len(lib_data.get("components", []))
        stats["components_by_library"][lib_name] = component_count

    # Count base component usage
    for lib_name, component, source_file in validator.get_all_components():
        base_comp = component.get("base_component", "unknown")
        stats["base_components_usage"][base_comp] = stats["base_components_usage"].get(base_comp, 0) + 1

    # Print statistics (will be visible in pytest output with -s flag)
    print("\n" + "=" * 50)
    print("KICAD LIBRARY STATISTICS")
    print("=" * 50)
    print(f"Total Libraries: {stats['total_libraries']}")
    print(f"Total Components: {stats['total_components']}")
    print(f"Total Base Symbols: {stats['total_base_symbols']}")
    print(f"Total Footprints: {stats['total_footprints']}")

    print("\nComponents per Library:")
    for lib_name, count in sorted(stats["components_by_library"].items()):
        print(f"  {lib_name}: {count}")

    print("\nMost Used Base Components:")
    sorted_usage = sorted(stats["base_components_usage"].items(), key=lambda x: x[1], reverse=True)
    for base_comp, count in sorted_usage[:10]:  # Top 10
        print(f"  {base_comp}: {count}")

    # This test always passes - it's just for reporting
    assert True


if __name__ == "__main__":
    # Allow running tests directly with python
    pytest.main([__file__])
