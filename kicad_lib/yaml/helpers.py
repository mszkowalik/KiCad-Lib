"""
Shared YAML data access utilities for the KiCad Library Management System.

Provides unified functions for loading YAML source files, accessing component
properties, and loading base library symbol names.  Used across the symbol
generator, component validator, and EasyEDA importer to avoid duplication.
"""

from collections.abc import Iterator
from pathlib import Path

import yaml
from kiutils.symbol import SymbolLib

from kicad_lib import config
from kicad_lib.colors import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# YAML source loading
# ---------------------------------------------------------------------------


def load_yaml_sources(directory: str | Path = config.SOURCES_DIR) -> list[dict]:
    """Load all YAML source files from a directory.

    Each returned dict includes a ``_source_file`` key with the filename.
    Files with YAML syntax errors are skipped with a warning logged.
    Does **not** validate that ``library_name`` matches the filename — use
    :func:`validate_library_names` for that.
    """
    directory = Path(directory)
    yaml_paths = sorted(directory.glob("*.yaml")) + sorted(directory.glob("*.yml"))
    data: list[dict] = []

    for yaml_path in yaml_paths:
        try:
            with open(yaml_path) as f:
                yaml_data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            log.warning(f"Skipping {yaml_path.name}: invalid YAML syntax: {e}")
            continue

        if yaml_data is None:
            continue

        yaml_data["_source_file"] = yaml_path.name
        data.append(yaml_data)

    return data


def validate_library_names(yaml_data: list[dict]) -> list[str]:
    """Validate that each ``library_name`` field matches its source filename.

    Returns a list of error messages (empty list when all names are valid).
    """
    errors: list[str] = []
    for lib_data in yaml_data:
        source_file = lib_data.get("_source_file", "")
        expected_name = Path(source_file).stem if source_file else ""
        actual_name = lib_data.get("library_name")

        if not actual_name:
            errors.append(f"Missing 'library_name' field in file: {source_file}")
        elif actual_name != expected_name:
            errors.append(
                f"Library name mismatch in '{source_file}': "
                f"library_name is '{actual_name}' but should be '{expected_name}'"
            )

    return errors


# ---------------------------------------------------------------------------
# Component property accessors
# ---------------------------------------------------------------------------


def get_property(component: dict, key: str):
    """Get the raw property value from a YAML component dict.

    Returns the value as-is (could be ``None``, ``""``, or any scalar) when
    the property key is found.  Returns ``None`` when the key is not present.
    """
    for prop in component.get("properties", []):
        if prop.get("key") == key:
            return prop.get("value")
    return None


def get_property_value(component: dict, key: str) -> str | None:
    """Get a non-empty string property value.

    Returns ``None`` if the property is missing, has a ``None`` value, or is
    an empty / whitespace-only string.
    """
    for prop in component.get("properties", []):
        if prop.get("key") == key:
            val = prop.get("value")
            if val is None or (isinstance(val, str) and not val.strip()):
                return None
            return str(val)
    return None


def has_property(component: dict, key: str) -> bool:
    """Check if a component has a property key defined (regardless of value)."""
    return any(prop.get("key") == key for prop in component.get("properties", []))


# ---------------------------------------------------------------------------
# Component iteration
# ---------------------------------------------------------------------------


def iter_all_components(yaml_data: list[dict]) -> Iterator[tuple[str, dict, str]]:
    """Yield ``(library_name, component, source_file)`` for every component."""
    for lib_data in yaml_data:
        lib_name = lib_data.get("library_name", "unknown")
        source_file = lib_data.get("_source_file", "")
        for component in lib_data.get("components", []):
            yield lib_name, component, source_file


# ---------------------------------------------------------------------------
# Base library access
# ---------------------------------------------------------------------------


def load_base_symbol_names(base_lib_path: str | Path | None = None) -> set[str]:
    """Load base component entry names from the base symbol library.

    Returns an empty set if the base library file does not exist.
    """
    if base_lib_path is None:
        base_lib_path = config.BASE_LIB_PATH

    path = Path(base_lib_path)
    if not path.exists():
        return set()

    base_lib = SymbolLib.from_file(str(path))
    return {s.entryName for s in base_lib.symbols}
