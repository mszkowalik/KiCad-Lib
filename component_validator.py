#!/usr/bin/env python3
"""
Component Validator for KiCad Library Management System

Standalone validator that can be run independently or integrated into the main workflow.
Provides comprehensive validation of YAML components, base symbols, and footprints.
"""

import os
import sys
import yaml
import re
from pathlib import Path
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Container for validation results."""

    passed: bool
    message: str
    component_name: str = ""
    library_name: str = ""
    source_file: str = ""


class ComponentValidator:
    """Standalone component validator that doesn't require pytest."""

    def __init__(self, sources_dir: str = "./Sources", symbols_dir: str = "./Symbols", footprints_dir: str = "./Footprints/7Sigma.pretty", config_file: str = None):
        self.sources_dir = Path(sources_dir)
        self.symbols_dir = Path(symbols_dir)
        self.footprints_dir = Path(footprints_dir)
        self.base_library_path = self.symbols_dir / "base_library.kicad_sym"

        # Load configuration
        self.config = self._load_config(config_file)

        # Results storage
        self.errors: List[ValidationResult] = []
        self.warnings: List[ValidationResult] = []
        self.stats = {}

        # Load data
        self.yaml_data = self._load_all_yaml_files()
        self.base_symbols = self._load_base_symbols()
        self.available_footprints = self._load_available_footprints()

    def _load_config(self, config_file: str = None) -> Dict:
        """Load global validation configuration from YAML file."""
        # Default global configuration
        default_config = {
            "required_properties": ["Footprint", "ki_description"],
            "non_empty_properties": ["Footprint", "ki_description"],
            "property_patterns": {"Footprint": "^7Sigma:", "LCSC Part": "^C\\d+$"},
            "max_property_length": 200,
            "manufacturer_properties": ["Manufacturer 1", "Manufacturer Part Number 1", "Supplier 1", "Supplier Part Number 1"],
            "footprint_dimensions": {"min_drill_diameter": 0.3, "min_via_size": 0.3, "min_via_drill": 0.3, "min_pad_size": 0.6, "thermal_via_warning_only": True},
        }

        # If no config file specified, try the default location
        if config_file is None:
            config_file = "./tests/test_config.yaml"

        config_path = Path(config_file)
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

    def _load_all_yaml_files(self) -> List[Dict]:
        """Load all YAML component files."""
        yaml_files = []
        for yaml_file in self.sources_dir.glob("*.yaml"):
            try:
                with open(yaml_file, "r") as f:
                    data = yaml.safe_load(f)
                    data["_source_file"] = yaml_file.name
                    yaml_files.append(data)
            except yaml.YAMLError as e:
                self.errors.append(ValidationResult(passed=False, message=f"Invalid YAML syntax: {e}", source_file=yaml_file.name))
        return yaml_files

    def _load_base_symbols(self) -> Set[str]:
        """Load available base component names from base library."""
        if not self.base_library_path.exists():
            self.errors.append(ValidationResult(passed=False, message=f"Base library not found at {self.base_library_path}"))
            return set()

        try:
            # Try to import kiutils, fall back to text parsing if not available
            try:
                from kiutils.symbol import SymbolLib

                base_lib = SymbolLib.from_file(str(self.base_library_path))
                return {symbol.entryName for symbol in base_lib.symbols}
            except ImportError:
                # Fall back to text parsing
                return self._parse_base_symbols_from_text()
        except Exception as e:
            self.errors.append(ValidationResult(passed=False, message=f"Failed to load base library: {e}"))
            return set()

    def _parse_base_symbols_from_text(self) -> Set[str]:
        """Parse base symbols from text file when kiutils is not available."""
        symbols = set()
        try:
            with open(self.base_library_path, "r") as f:
                content = f.read()
                # Look for symbol definitions: (symbol "SymbolName"
                matches = re.findall(r'\\(symbol\\s+"([^"]+)"', content)
                symbols.update(matches)
        except Exception as e:
            self.errors.append(ValidationResult(passed=False, message=f"Failed to parse base library: {e}"))
        return symbols

    def _load_available_footprints(self) -> Set[str]:
        """Load available footprint names."""
        if not self.footprints_dir.exists():
            self.warnings.append(ValidationResult(passed=True, message=f"Footprints directory not found at {self.footprints_dir}"))
            return set()

        footprints = set()
        for footprint_file in self.footprints_dir.glob("*.kicad_mod"):
            footprints.add(footprint_file.stem)
        return footprints

    def get_component_property(self, component: Dict, property_key: str) -> Optional[str]:
        """Get property value from component definition."""
        properties = component.get("properties", [])
        for prop in properties:
            if prop.get("key") == property_key:
                return prop.get("value")
        return None

    def has_component_property(self, component: Dict, property_key: str) -> bool:
        """Check if component has a property defined (regardless of value)."""
        properties = component.get("properties", [])
        for prop in properties:
            if prop.get("key") == property_key:
                return True
        return False

    def get_all_components(self) -> List[Tuple[str, Dict, str]]:
        """Get all components with their library context."""
        components = []
        for lib_data in self.yaml_data:
            lib_name = lib_data.get("library_name", "unknown")
            for component in lib_data.get("components", []):
                components.append((lib_name, component, lib_data["_source_file"]))
        return components

    def get_library_validation_rules(self, lib_data: Dict) -> Dict:
        """Extract validation rules from a library YAML file."""
        return lib_data.get("validation_rules", {})

    def get_merged_rules_for_library(self, lib_data: Dict) -> Dict:
        """Get merged validation rules (global + library-specific)."""
        library_rules = self.get_library_validation_rules(lib_data)

        # Start with global config
        merged_rules = {
            "required_properties": self.config.get("required_properties", []).copy(),
            "non_empty_properties": self.config.get("non_empty_properties", []).copy(),
            "property_patterns": self.config.get("property_patterns", {}).copy(),
            "max_property_length": self.config.get("max_property_length", 200),
            "manufacturer_properties": self.config.get("manufacturer_properties", []).copy(),
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

        if "conditional_required_properties" in library_rules:
            merged_rules["conditional_required_properties"] = library_rules["conditional_required_properties"]

        return merged_rules

    def validate_yaml_structure(self):
        """Validate YAML file structure."""
        for lib_data in self.yaml_data:
            source_file = lib_data["_source_file"]

            # Check library_name matches filename
            expected_name = Path(source_file).stem
            actual_name = lib_data.get("library_name")

            if actual_name != expected_name:
                self.errors.append(ValidationResult(passed=False, message=f"Library name '{actual_name}' doesn't match filename '{expected_name}'", source_file=source_file))

            # Check components key exists
            if "components" not in lib_data:
                self.errors.append(ValidationResult(passed=False, message="Missing 'components' key", source_file=source_file))
            elif not isinstance(lib_data["components"], list):
                self.errors.append(ValidationResult(passed=False, message="'components' should be a list", source_file=source_file))

    def validate_base_components(self):
        """Validate base component references."""
        component_names = set()

        for lib_name, component, source_file in self.get_all_components():
            comp_name = component.get("name")

            # Check component name exists and is unique
            if not comp_name:
                self.errors.append(ValidationResult(passed=False, message="Missing 'name' field", library_name=lib_name, source_file=source_file))
                continue

            if comp_name in component_names:
                self.errors.append(
                    ValidationResult(passed=False, message=f"Duplicate component name '{comp_name}'", component_name=comp_name, library_name=lib_name, source_file=source_file)
                )
            component_names.add(comp_name)

            # Check base component exists
            base_component = component.get("base_component")
            if not base_component:
                self.errors.append(
                    ValidationResult(passed=False, message="Missing 'base_component' field", component_name=comp_name, library_name=lib_name, source_file=source_file)
                )
            elif base_component not in self.base_symbols:
                self.errors.append(
                    ValidationResult(
                        passed=False,
                        message=f"Base component '{base_component}' not found in base library",
                        component_name=comp_name,
                        library_name=lib_name,
                        source_file=source_file,
                    )
                )

    def validate_component_properties(self):
        """Validate component properties using library-specific rules."""
        # Group components by library for rule application
        libraries = {}
        for lib_data in self.yaml_data:
            lib_name = lib_data.get("library_name", "unknown")
            libraries[lib_name] = lib_data

        for lib_name, component, source_file in self.get_all_components():
            comp_name = component.get("name", "unnamed")

            # Get library-specific validation rules
            lib_data = libraries.get(lib_name, {})
            rules = self.get_merged_rules_for_library(lib_data)

            # Check required properties (must be defined, but can be null)
            for required_prop in rules["required_properties"]:
                if not self.has_component_property(component, required_prop):
                    self.errors.append(
                        ValidationResult(
                            passed=False,
                            message=f"Missing required property '{required_prop}' (use null if not applicable)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

            # Check conditional required properties based on component properties
            conditional_rules = rules.get("conditional_required_properties", [])
            # Handle both old dict format and new list format
            if isinstance(conditional_rules, dict):
                # Convert old format to new format for backward compatibility
                converted_rules = []
                for condition_key, condition_requirements in conditional_rules.items():
                    if condition_key == "base_component":
                        for base_pattern, required_props in condition_requirements.items():
                            converted_rules.append({"base_component": base_pattern, "requirements": required_props})
                    elif condition_key == "property_based":
                        for prop_condition, required_props in condition_requirements.items():
                            condition_prop, expected_value = prop_condition.split("=")
                            converted_rules.append({"properties": {condition_prop: expected_value}, "requirements": required_props})
                conditional_rules = converted_rules

            # Process list-based conditional rules
            for rule in conditional_rules:
                rule_matches = True

                # Check base_component condition (backward compatibility)
                if "base_component" in rule:
                    base_comp = component.get("base_component", "")
                    base_pattern = rule["base_component"]
                    if not (base_pattern in base_comp or base_comp.startswith(base_pattern)):
                        rule_matches = False

                # Check properties conditions (new format)
                if "properties" in rule and rule_matches:
                    for prop_name, pattern in rule["properties"].items():
                        actual_value = self.get_component_property(component, prop_name)
                        if actual_value is None:
                            rule_matches = False
                            break
                        # Use regex matching for flexible pattern support
                        if not re.match(pattern, str(actual_value)):
                            rule_matches = False
                            break

                # If rule matches, check all required properties
                if rule_matches:
                    required_props = rule.get("requirements", [])
                    for required_prop in required_props:
                        if not self.has_component_property(component, required_prop):
                            self.errors.append(
                                ValidationResult(
                                    passed=False,
                                    message=f"Missing required property '{required_prop}' for conditional rule",
                                    component_name=comp_name,
                                    library_name=lib_name,
                                    source_file=source_file,
                                )
                            )

            # Check non-empty properties (null values are ignored, empty strings are errors)
            for prop_key in rules["non_empty_properties"]:
                prop_value = self.get_component_property(component, prop_key)

                # Skip validation if property is null (explicitly set to null means "not applicable")
                if prop_value is None:
                    continue

                # Check for empty strings (which are considered errors)
                if not prop_value or str(prop_value).strip() == "":
                    self.errors.append(
                        ValidationResult(
                            passed=False,
                            message=f"Property '{prop_key}' is empty (use null to skip validation)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

            # Check property patterns (skip null values)
            for prop_key, pattern in rules["property_patterns"].items():
                prop_value = self.get_component_property(component, prop_key)

                # Skip validation if property is null or empty
                if prop_value is None or not prop_value:
                    continue

                if not re.match(pattern, str(prop_value)):
                    self.errors.append(
                        ValidationResult(
                            passed=False,
                            message=f"Property '{prop_key}' value '{prop_value}' doesn't match pattern '{pattern}'",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

            # Check property length
            max_length = rules["max_property_length"]
            for prop in component.get("properties", []):
                prop_key = prop.get("key", "unknown")
                prop_value = str(prop.get("value", ""))
                if len(prop_value) > max_length:
                    self.warnings.append(
                        ValidationResult(
                            passed=True,
                            message=f"Property '{prop_key}' value is very long ({len(prop_value)} chars)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

            # Check manufacturer information
            mfr_props = rules["manufacturer_properties"]
            # Skip manufacturer validation if manufacturer_properties is empty (disabled for this library)
            if mfr_props:
                # Check if ANY manufacturer property has a non-null value
                has_manufacturer_info = False
                for prop in mfr_props:
                    if self.has_component_property(component, prop):
                        prop_value = self.get_component_property(component, prop)
                        # Consider it valid if property is defined and not None/empty
                        if prop_value is not None and str(prop_value).strip():
                            has_manufacturer_info = True
                            break

                # Only warn if no manufacturer properties are defined OR all are empty (not null)
                if not has_manufacturer_info:
                    # Check if at least one manufacturer property is explicitly defined (even if null)
                    any_defined = any(self.has_component_property(component, prop) for prop in mfr_props)
                    if not any_defined:
                        # No manufacturer properties defined at all
                        self.warnings.append(
                            ValidationResult(passed=True, message="No manufacturer information found", component_name=comp_name, library_name=lib_name, source_file=source_file)
                        )

    def validate_footprints(self):
        """Validate footprint references using library-specific rules."""
        # Group components by library for rule application
        libraries = {}
        for lib_data in self.yaml_data:
            lib_name = lib_data.get("library_name", "unknown")
            libraries[lib_name] = lib_data

        for lib_name, component, source_file in self.get_all_components():
            comp_name = component.get("name", "unnamed")

            # Get library-specific validation rules
            lib_data = libraries.get(lib_name, {})
            rules = self.get_merged_rules_for_library(lib_data)

            # Skip if footprint not required for this library
            if not rules["footprint_required"]:
                continue

            footprint_value = self.get_component_property(component, "Footprint")
            if not footprint_value:
                continue

            # Check footprint file exists (assuming 7Sigma: prefix from property_patterns validation)
            if footprint_value.startswith("7Sigma:"):
                footprint_name = footprint_value[7:]  # Remove prefix
                if footprint_name not in self.available_footprints:
                    self.errors.append(
                        ValidationResult(
                            passed=False, message=f"Footprint file '{footprint_name}.kicad_mod' not found", component_name=comp_name, library_name=lib_name, source_file=source_file
                        )
                    )

    def validate_footprint_dimensions(self):
        """Validate footprint pad and via dimensions using configurable requirements."""
        # Get dimension requirements from config
        dim_config = self.config.get("footprint_dimensions", {})
        MIN_DRILL_DIAMETER = dim_config.get("min_drill_diameter", 0.3)
        MIN_VIA_SIZE = dim_config.get("min_via_size", 0.3)
        MIN_VIA_DRILL = dim_config.get("min_via_drill", 0.3)
        MIN_PAD_SIZE = dim_config.get("min_pad_size", 0.6)
        THERMAL_VIA_WARNING_ONLY = dim_config.get("thermal_via_warning_only", True)

        # Group components by library for rule application
        libraries = {}
        for lib_data in self.yaml_data:
            lib_name = lib_data.get("library_name", "unknown")
            libraries[lib_name] = lib_data

        for lib_name, component, source_file in self.get_all_components():
            comp_name = component.get("name", "unnamed")

            # Get library-specific validation rules
            lib_data = libraries.get(lib_name, {})
            rules = self.get_merged_rules_for_library(lib_data)

            # Skip if footprint not required for this library
            if not rules["footprint_required"]:
                continue

            footprint_value = self.get_component_property(component, "Footprint")
            if not footprint_value or not footprint_value.startswith("7Sigma:"):
                continue

            footprint_name = footprint_value[7:]  # Remove prefix
            if footprint_name not in self.available_footprints:
                continue  # Skip if footprint file doesn't exist (caught by other validation)

            # Check footprint file for pad and via dimensions
            footprint_path = self.footprints_dir / f"{footprint_name}.kicad_mod"
            try:
                with open(footprint_path, "r") as f:
                    content = f.read()

                import re

                # Track issues per footprint to aggregate them
                footprint_issues = {
                    "drill_too_small": [],
                    "pad_too_small": [],
                    "via_size_too_small": [],
                    "via_drill_too_small": [],
                    "thermal_via_size_warning": [],
                    "thermal_via_drill_warning": [],
                }

                # Check pad drill holes
                drill_matches = re.findall(r"\(drill\s+([0-9]*\.?[0-9]+)(?:\s+[0-9]*\.?[0-9]+)?\)", content)
                for drill_size_str in drill_matches:
                    try:
                        drill_size = float(drill_size_str)
                        if drill_size < MIN_DRILL_DIAMETER:
                            footprint_issues["drill_too_small"].append(drill_size)
                    except ValueError:
                        continue

                # Check through-hole pad sizes (only for through-hole pads, not SMD)
                th_pad_size_matches = re.findall(r'\(pad\s+"[^"]*"\s+thru_hole\s+\w+\s+\([^)]*\)\s+\(size\s+([0-9]*\.?[0-9]+)(?:\s+[0-9]*\.?[0-9]+)?\)', content)
                for pad_size_str in th_pad_size_matches:
                    try:
                        pad_size = float(pad_size_str)
                        if pad_size < MIN_PAD_SIZE:
                            footprint_issues["pad_too_small"].append(pad_size)
                    except ValueError:
                        continue

                # Check via definitions
                via_matches = re.findall(r"\(via\s+\([^)]*\)\s+\(size\s+([0-9]*\.?[0-9]+)\)\s+\(drill\s+([0-9]*\.?[0-9]+)\)", content)
                for via_size_str, via_drill_str in via_matches:
                    try:
                        via_size = float(via_size_str)
                        via_drill = float(via_drill_str)

                        # Determine if this is a thermal via
                        is_thermal_via = "ThermalVias" in footprint_name or "thermal" in footprint_name.lower()

                        if via_size < MIN_VIA_SIZE:
                            if is_thermal_via and THERMAL_VIA_WARNING_ONLY:
                                footprint_issues["thermal_via_size_warning"].append(via_size)
                            else:
                                footprint_issues["via_size_too_small"].append(via_size)

                        if via_drill < MIN_VIA_DRILL:
                            if is_thermal_via and THERMAL_VIA_WARNING_ONLY:
                                footprint_issues["thermal_via_drill_warning"].append(via_drill)
                            else:
                                footprint_issues["via_drill_too_small"].append(via_drill)
                    except ValueError:
                        continue

                # Generate aggregated error/warning messages
                if footprint_issues["drill_too_small"]:
                    min_drill = min(footprint_issues["drill_too_small"])
                    count = len(footprint_issues["drill_too_small"])
                    self.errors.append(
                        ValidationResult(
                            passed=False,
                            message=f"Footprint '{footprint_name}' has {count} drill hole(s) < {MIN_DRILL_DIAMETER}mm (smallest: {min_drill}mm)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

                if footprint_issues["pad_too_small"]:
                    min_pad = min(footprint_issues["pad_too_small"])
                    count = len(footprint_issues["pad_too_small"])
                    self.errors.append(
                        ValidationResult(
                            passed=False,
                            message=f"Footprint '{footprint_name}' has {count} through-hole pad(s) < {MIN_PAD_SIZE}mm (smallest: {min_pad}mm)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

                if footprint_issues["via_size_too_small"]:
                    min_via = min(footprint_issues["via_size_too_small"])
                    count = len(footprint_issues["via_size_too_small"])
                    self.errors.append(
                        ValidationResult(
                            passed=False,
                            message=f"Footprint '{footprint_name}' has {count} via(s) with size < {MIN_VIA_SIZE}mm (smallest: {min_via}mm)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

                if footprint_issues["via_drill_too_small"]:
                    min_via_drill = min(footprint_issues["via_drill_too_small"])
                    count = len(footprint_issues["via_drill_too_small"])
                    self.errors.append(
                        ValidationResult(
                            passed=False,
                            message=f"Footprint '{footprint_name}' has {count} via(s) with drill < {MIN_VIA_DRILL}mm (smallest: {min_via_drill}mm)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

                if footprint_issues["thermal_via_size_warning"]:
                    min_thermal_via = min(footprint_issues["thermal_via_size_warning"])
                    count = len(footprint_issues["thermal_via_size_warning"])
                    self.warnings.append(
                        ValidationResult(
                            passed=True,
                            message=f"Footprint '{footprint_name}' has {count} thermal via(s) with size < {MIN_VIA_SIZE}mm (smallest: {min_thermal_via}mm)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

                if footprint_issues["thermal_via_drill_warning"]:
                    min_thermal_drill = min(footprint_issues["thermal_via_drill_warning"])
                    count = len(footprint_issues["thermal_via_drill_warning"])
                    self.warnings.append(
                        ValidationResult(
                            passed=True,
                            message=f"Footprint '{footprint_name}' has {count} thermal via(s) with drill < {MIN_VIA_DRILL}mm (smallest: {min_thermal_drill}mm)",
                            component_name=comp_name,
                            library_name=lib_name,
                            source_file=source_file,
                        )
                    )

            except Exception as e:
                self.warnings.append(
                    ValidationResult(
                        passed=True,
                        message=f"Could not validate footprint dimensions for '{footprint_name}': {e}",
                        component_name=comp_name,
                        library_name=lib_name,
                        source_file=source_file,
                    )
                )

    def validate_template_expressions(self):
        """Validate template expressions in properties."""
        for lib_name, component, source_file in self.get_all_components():
            comp_name = component.get("name", "unnamed")

            # Build available properties for template evaluation
            available_props = {prop.get("key"): prop.get("value", "") for prop in component.get("properties", [])}

            for prop in component.get("properties", []):
                prop_key = prop.get("key", "unknown")
                prop_value = prop.get("value", "")

                if isinstance(prop_value, str) and "{" in prop_value and "}" in prop_value:
                    # Check if template variables are available
                    template_vars = re.findall(r"\\{(\\w+)\\}", prop_value)
                    for var in template_vars:
                        if var not in available_props:
                            self.errors.append(
                                ValidationResult(
                                    passed=False,
                                    message=f"Template variable '{var}' in '{prop_key}' not found in component properties",
                                    component_name=comp_name,
                                    library_name=lib_name,
                                    source_file=source_file,
                                )
                            )

    def generate_statistics(self):
        """Generate library statistics."""
        self.stats = {
            "total_libraries": len(self.yaml_data),
            "total_components": len(self.get_all_components()),
            "total_base_symbols": len(self.base_symbols),
            "total_footprints": len(self.available_footprints),
            "components_by_library": {},
            "base_components_usage": {},
            "validation_summary": {"errors": len(self.errors), "warnings": len(self.warnings), "passed": len(self.errors) == 0},
        }

        # Count components per library
        for lib_data in self.yaml_data:
            lib_name = lib_data.get("library_name", "unknown")
            component_count = len(lib_data.get("components", []))
            self.stats["components_by_library"][lib_name] = component_count

        # Count base component usage
        for lib_name, component, source_file in self.get_all_components():
            base_comp = component.get("base_component", "unknown")
            self.stats["base_components_usage"][base_comp] = self.stats["base_components_usage"].get(base_comp, 0) + 1

    def run_all_validations(self) -> bool:
        """Run all validation checks and return success status."""
        print("Running KiCad Library Component Validation...")
        print("=" * 60)

        # Run validations
        self.validate_yaml_structure()
        self.validate_base_components()
        self.validate_component_properties()
        self.validate_footprints()
        self.validate_footprint_dimensions()
        self.validate_template_expressions()

        # Generate statistics
        self.generate_statistics()

        # Report results
        self.print_results()

        return len(self.errors) == 0

    def print_results(self):
        """Print validation results."""
        # Print statistics
        print(f"\\nLibrary Statistics:")
        print(f"  Libraries: {self.stats['total_libraries']}")
        print(f"  Components: {self.stats['total_components']}")
        print(f"  Base Symbols: {self.stats['total_base_symbols']}")
        print(f"  Footprints: {self.stats['total_footprints']}")

        # Print validation summary
        print(f"\\nValidation Results:")
        print(f"  ✓ Validations passed: {len(self.errors) == 0}")
        print(f"  ✗ Errors: {len(self.errors)}")
        print(f"  ⚠ Warnings: {len(self.warnings)}")

        # Print errors
        if self.errors:
            print(f"\\n{'='*60}")
            print("ERRORS:")
            print("=" * 60)
            for error in self.errors:
                location = []
                if error.component_name:
                    location.append(f"Component: {error.component_name}")
                if error.library_name:
                    location.append(f"Library: {error.library_name}")
                if error.source_file:
                    location.append(f"File: {error.source_file}")

                location_str = " | ".join(location)
                print(f"✗ {error.message}")
                if location_str:
                    print(f"  └─ {location_str}")
                print()

        # Print warnings
        if self.warnings:
            print(f"\\n{'='*60}")
            print("WARNINGS:")
            print("=" * 60)
            for warning in self.warnings:
                location = []
                if warning.component_name:
                    location.append(f"Component: {warning.component_name}")
                if warning.library_name:
                    location.append(f"Library: {warning.library_name}")
                if warning.source_file:
                    location.append(f"File: {warning.source_file}")

                location_str = " | ".join(location)
                print(f"⚠ {warning.message}")
                if location_str:
                    print(f"  └─ {location_str}")
                print()

        # Print component distribution
        if self.stats["components_by_library"]:
            print(f"\\nComponents per Library:")
            for lib_name, count in sorted(self.stats["components_by_library"].items()):
                print(f"  {lib_name}: {count}")

        print("\\n" + "=" * 60)


def main():
    """Main entry point for standalone validation."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate KiCad Library Components")
    parser.add_argument("--sources", default="./Sources", help="Sources directory")
    parser.add_argument("--symbols", default="./Symbols", help="Symbols directory")
    parser.add_argument("--footprints", default="./Footprints/7Sigma.pretty", help="Footprints directory")
    parser.add_argument("--config", default="./tests/test_config.yaml", help="Configuration file")
    parser.add_argument("--quiet", action="store_true", help="Only show errors")

    args = parser.parse_args()

    validator = ComponentValidator(sources_dir=args.sources, symbols_dir=args.symbols, footprints_dir=args.footprints, config_file=args.config)

    success = validator.run_all_validations()

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
