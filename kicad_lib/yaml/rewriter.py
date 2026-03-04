"""
Round-trip YAML editor for the KiCad Library Management System.

Uses ruamel.yaml to modify YAML component files while preserving comments,
formatting, quoting style, and key ordering.
"""

from pathlib import Path

from ruamel.yaml import YAML as RuamelYAML

from kicad_lib.colors import get_logger

log = get_logger(__name__)


def _create_yaml_handler() -> RuamelYAML:
    """Create a configured ruamel.yaml handler for round-trip editing."""
    ryaml = RuamelYAML()
    ryaml.preserve_quotes = True
    ryaml.indent(mapping=2, sequence=4, offset=2)
    ryaml.width = 4096  # prevent line wrapping of long strings
    return ryaml


def load_roundtrip(filepath: str | Path) -> tuple[RuamelYAML, dict]:
    """Load a YAML file for round-trip editing (preserves comments/formatting).

    Returns ``(yaml_handler, data)`` — pass both to :func:`save_roundtrip`.
    """
    ryaml = _create_yaml_handler()
    with open(filepath) as f:
        data = ryaml.load(f)
    return ryaml, data


def save_roundtrip(ryaml: RuamelYAML, data, filepath: str | Path) -> None:
    """Save a YAML data structure back to file (preserves formatting)."""
    with open(filepath, "w") as f:
        ryaml.dump(data, f)


def rewrite_component(filepath: str | Path, component_name: str, updates: dict) -> bool:
    """Rewrite a component block in a YAML file with updated/new properties.

    ``updates`` is a dict like::

        {
            "base_component": "STM32G031G8U6",
            "properties": {
                "Footprint": "7Sigma:UFQFPN-28_L4.0-W4.0-P0.50-BL",
                "ki_description": "ARM Cortex-M0+ ...",
            }
        }

    Only empty/missing values are overwritten — existing values are preserved.
    Returns ``True`` if the file was modified.
    """
    ryaml, data = load_roundtrip(filepath)

    modified = False
    for comp in data.get("components", []):
        if comp.get("name") != component_name:
            continue

        # Update base_component if provided and currently empty
        if "base_component" in updates and not comp.get("base_component"):
            comp["base_component"] = updates["base_component"]
            modified = True

        # Update / add properties
        existing_keys = {p["key"] for p in comp.get("properties", [])}
        for key, value in updates.get("properties", {}).items():
            if key in existing_keys:
                # Only overwrite if currently empty
                for p in comp["properties"]:
                    if p["key"] == key:
                        if p.get("value") is None or (isinstance(p.get("value"), str) and not p["value"].strip()):
                            p["value"] = value
                            modified = True
                        break
            else:
                comp.setdefault("properties", []).append({"key": key, "value": value})
                modified = True

        # Enforce canonical key order
        _reorder_keys(comp)
        break

    if modified:
        save_roundtrip(ryaml, data, filepath)

    return modified


def _reorder_keys(comp: dict) -> None:
    """Reorder component dict keys to canonical order: name → base_component → properties → rest."""
    canonical_order = ["name", "base_component", "properties"]
    ordered = {}
    for k in canonical_order:
        if k in comp:
            ordered[k] = comp[k]
    for k, v in comp.items():
        if k not in ordered:
            ordered[k] = v
    comp.clear()
    comp.update(ordered)
