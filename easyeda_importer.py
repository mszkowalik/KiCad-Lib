#!/usr/bin/env python3
"""
EasyEDA Auto-Importer for KiCad Library Management System

Automatically downloads and imports components from LCSC/EasyEDA when a YAML
component has an LCSC Part number but is missing a base symbol, footprint,
or metadata properties.

Minimal YAML entry required:
    - name: STM32G031G8U6
      properties:
        - key: LCSC Part
          value: C432211

The importer will automatically:
  1. Fetch component metadata from LCSC API (manufacturer, description, datasheet)
  2. Run easyeda2kicad to download symbol, footprint, and 3D model
  3. Copy footprint into 7Sigma.pretty
  4. Add base symbol to base_library.kicad_sym
  5. Update the YAML file with all resolved properties
"""

import copy
import json
import os
import tempfile
import urllib.request
from pathlib import Path

import yaml
from easyeda2kicad.easyeda.easyeda_api import EasyedaApi
from easyeda2kicad.easyeda.easyeda_importer import (
    Easyeda3dModelImporter,
    EasyedaFootprintImporter,
    EasyedaSymbolImporter,
)
from easyeda2kicad.helpers import add_component_in_symbol_lib_file
from easyeda2kicad.kicad.export_kicad_footprint import ExporterFootprintKicad
from easyeda2kicad.kicad.export_kicad_symbol import ExporterSymbolKicad
from easyeda2kicad.kicad.parameters_kicad_symbol import KicadVersion
from kiutils.symbol import SymbolLib
from ruamel.yaml import YAML as RuamelYAML
from ruamel.yaml.comments import CommentedMap
from ruamel.yaml.scalarstring import DoubleQuotedScalarString as DQ

import config
from colors import get_logger
from update_footprints_models import process_footprint

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_base_component_names() -> set[str]:
    """Get the set of all base component entry names."""
    base_lib = SymbolLib.from_file(config.BASE_LIB_PATH)
    return {s.entryName for s in base_lib.symbols}


def _get_prop(component: dict, key: str) -> str | None:
    """Get a property value from a YAML component dict. Returns None if missing or empty."""
    for prop in component.get("properties", []):
        if prop.get("key") == key:
            val = prop.get("value")
            if val is None or (isinstance(val, str) and not val.strip()):
                return None
            return str(val)
    return None


def _needs_import(component: dict, existing_bases: set[str], defaults: dict | None = None) -> bool:
    """Check whether a component still needs to be imported.

    A component needs import when it has an LCSC Part number AND its base
    component is unresolved (missing, empty, or not present in base_library).
    The optional *defaults* dict (from the YAML ``defaults:`` section) is
    consulted as a fallback for base_component.
    """
    lcsc = _get_prop(component, "LCSC Part")
    if not lcsc:
        return False

    base = component.get("base_component")
    if not base and defaults:
        base = defaults.get("base_component")

    # Needs import when base_component is missing/empty OR the referenced base
    # doesn't exist in base_library.
    return bool(not base or base not in existing_bases)


# ---------------------------------------------------------------------------
# LCSC metadata
# ---------------------------------------------------------------------------

_lcsc_metadata_cache: dict[str, dict[str, str] | None] = {}


def _fetch_lcsc_metadata(lcsc_id: str) -> dict[str, str] | None:
    """Fetch component metadata from the LCSC API (with per-run cache)."""
    if lcsc_id in _lcsc_metadata_cache:
        return _lcsc_metadata_cache[lcsc_id]

    url = config.LCSC_API_URL.format(lcsc_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        result = data.get("result")
        if not result or not isinstance(result, dict):
            _lcsc_metadata_cache[lcsc_id] = None
            return None
        meta = {
            "manufacturer": result.get("brandNameEn", ""),
            "mpn": result.get("productModel", ""),
            "description": result.get("productIntroEn") or result.get("productNameEn") or "",
            "datasheet": result.get("pdfUrl", ""),
            "category": result.get("catalogName", ""),
            "package": result.get("encapStandard", ""),
        }
        _lcsc_metadata_cache[lcsc_id] = meta
        return meta
    except Exception as e:
        log.warning(f"Could not fetch LCSC metadata for {lcsc_id}: {e}")
        _lcsc_metadata_cache[lcsc_id] = None
        return None


# ---------------------------------------------------------------------------
# easyeda2kicad API
# ---------------------------------------------------------------------------

_easyeda_api = EasyedaApi()


def _get_easyeda_footprint_name(lcsc_id: str) -> str | None:
    """Fetch just the EasyEDA footprint name for a component (no file export)."""
    try:
        cad_data = _easyeda_api.get_cad_data_of_component(lcsc_id=lcsc_id)
        if not cad_data:
            return None
        fp_importer = EasyedaFootprintImporter(easyeda_cp_cad_data=cad_data)
        return fp_importer.get_footprint().info.name
    except Exception:
        return None


def _download_and_import(
    lcsc_id: str,
    base_component_name: str | None = None,
) -> dict[str, str] | None:
    """
    Download symbol, footprint, and 3D model for a given LCSC ID and import
    them directly into the project:
      - Symbol → base_library.kicad_sym (via temp file + kiutils)
      - 3D model → ./3DModels/easyeda2kicad.3dshapes/  (STEP only)
      - Footprint → 7Sigma.pretty/  (with normalised model path)

    Returns dict with keys: symbol_name, footprint_name, base_component_name
    or None on failure.
    """
    cad_data = _easyeda_api.get_cad_data_of_component(lcsc_id=lcsc_id)
    if not cad_data:
        log.error(f"Failed to fetch CAD data from EasyEDA API for {lcsc_id}")
        return None

    kicad_version = KicadVersion.v6
    symbol_name = None
    footprint_name = None

    # ---- Symbol → base_library.kicad_sym ----
    try:
        sym_importer = EasyedaSymbolImporter(easyeda_cp_cad_data=cad_data)
        easyeda_symbol = sym_importer.get_symbol()
        symbol_name = easyeda_symbol.info.name

        if not base_component_name:
            base_component_name = symbol_name

        # Export to a temp .kicad_sym, read with kiutils, add to base_library
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_sym = os.path.join(tmpdir, "tmp.kicad_sym")

            # Seed with a valid .kicad_sym skeleton (add_component expects an existing file)
            with open(tmp_sym, "w", encoding="utf-8") as f:
                f.write("(kicad_symbol_lib (version 20211014) (generator kicad_symbol_editor)\n)")

            exporter = ExporterSymbolKicad(symbol=easyeda_symbol, kicad_version=kicad_version)
            kicad_symbol_lib = exporter.export(footprint_lib_name="easyeda2kicad")

            add_component_in_symbol_lib_file(
                lib_path=tmp_sym,
                component_content=kicad_symbol_lib,
                kicad_version=kicad_version,
            )

            tmp_lib = SymbolLib.from_file(tmp_sym)
            src_symbol = next((s for s in tmp_lib.symbols if s.entryName == symbol_name), None)

        if src_symbol is None:
            log.error(f"Symbol '{symbol_name}' not found after export")
            return None

        base_lib = SymbolLib.from_file(config.BASE_LIB_PATH)
        if not any(s.entryName == base_component_name for s in base_lib.symbols):
            new_symbol = copy.deepcopy(src_symbol)
            if new_symbol.entryName != base_component_name:
                new_symbol.entryName = base_component_name
                for unit in new_symbol.units:
                    unit.entryName = base_component_name
            for prop in new_symbol.properties:
                if prop.key in ("Footprint", "Datasheet"):
                    prop.value = ""
            base_lib.symbols.append(new_symbol)
            base_lib.to_file(config.BASE_LIB_PATH)
    except Exception as e:
        log.error(f"Symbol import failed for {lcsc_id}: {e}")
        return None

    # ---- 3D Model → ./3DModels/easyeda2kicad.3dshapes/ (must run before footprint) ----
    try:
        model_importer = Easyeda3dModelImporter(easyeda_cp_cad_data=cad_data, download_raw_3d_model=True)
        if model_importer.output and model_importer.output.step:
            model_dir = os.path.join(config.TARGET_3DMODELS_ROOT, "easyeda2kicad.3dshapes")
            os.makedirs(model_dir, exist_ok=True)
            step_path = os.path.join(model_dir, f"{model_importer.output.name}.step")
            with open(step_path, "wb") as f:
                f.write(model_importer.output.step)
    except Exception as e:
        log.warning(f"3D model export failed for {lcsc_id}: {e}")

    # ---- Footprint → 7Sigma.pretty/ (with ${SEVENSIGMA_DIR} model path) ----
    try:
        fp_importer = EasyedaFootprintImporter(easyeda_cp_cad_data=cad_data)
        easyeda_footprint = fp_importer.get_footprint()
        footprint_name = easyeda_footprint.info.name

        dst = os.path.join(config.FOOTPRINTS_DIR, f"{footprint_name}.kicad_mod")
        if not os.path.isfile(dst):
            # Footprint exporter hardcodes .wrl; process_footprint will fix to .step
            model_3d_path = f"{config.SEVENSIGMA_MODELS_BASE}easyeda2kicad.3dshapes"
            ki_footprint = ExporterFootprintKicad(footprint=easyeda_footprint)
            ki_footprint.export(footprint_full_path=dst, model_3d_path=model_3d_path)
            # Normalise model references (WRL→STEP, verify paths)
            process_footprint(dst)
    except Exception as e:
        log.warning(f"Footprint import failed for {lcsc_id}: {e}")

    if not symbol_name:
        return None

    return {
        "symbol_name": symbol_name,
        "footprint_name": footprint_name,
        "base_component_name": base_component_name,
    }


# ---------------------------------------------------------------------------
# YAML rewriting
# ---------------------------------------------------------------------------


def _rewrite_yaml_component(filepath: str, component_name: str, updates: dict):
    """
    Rewrite a component block in a YAML file with updated/new properties.
    Uses ruamel.yaml for round-trip editing that preserves comments,
    indentation, and quoting style.

    `updates` is a dict like:
        {
            "base_component": "STM32G031G8U6",
            "properties": {
                "Footprint": "7Sigma:UFQFPN-28_L4.0-W4.0-P0.50-BL",
                "ki_description": "ARM Cortex-M0+ ...",
                ...
            }
        }
    """
    ryaml = RuamelYAML()
    ryaml.preserve_quotes = True
    ryaml.indent(mapping=2, sequence=4, offset=2)
    ryaml.width = 4096  # prevent line wrapping of long strings

    with open(filepath) as f:
        data = ryaml.load(f)

    modified = False
    for comp in data.get("components", []):
        if comp.get("name") != component_name:
            continue

        # Update base_component if provided
        if "base_component" in updates and (not comp.get("base_component")):
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

        # Enforce canonical key order: name → base_component → properties → rest
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

        break

    if modified:
        with open(filepath, "w") as f:
            ryaml.dump(data, f)


# ---------------------------------------------------------------------------
# LCSC metadata → YAML property mapping
# ---------------------------------------------------------------------------

# Maps LCSC API metadata keys → YAML property keys
_LCSC_PROPERTY_MAP = {
    "description": "ki_description",
    "manufacturer": "Manufacturer 1",
    "mpn": "Manufacturer Part Number 1",
    "datasheet": "Datasheet",
}

# Properties that are always set for LCSC-sourced components
_LCSC_STATIC_PROPS = {
    "Supplier 1": "LCSC",
}


def _build_property_updates(meta: dict[str, str], lcsc_id: str) -> dict[str, str]:
    """Build a YAML property dict from LCSC metadata."""
    props: dict[str, str] = {}
    for meta_key, yaml_key in _LCSC_PROPERTY_MAP.items():
        val = meta.get(meta_key, "")
        if val:
            props[yaml_key] = val

    props.update(_LCSC_STATIC_PROPS)
    props["Supplier Part Number 1"] = lcsc_id
    return props


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def auto_import_missing_components(
    sources_dir: str = config.SOURCES_DIR,
) -> int:
    """
    Scan YAML definitions for components that need importing (missing base
    component in base_library and have an LCSC Part number).

    For each such component:
      1. Resolve base_component and footprint from YAML ``defaults:`` section
         (base_component fallback, footprint_map keyed by LCSC package size)
      2. Fetch metadata from LCSC API
      3. Only download from EasyEDA when the defaults cannot satisfy the need
      4. Update the YAML file with all resolved fields

    Returns the number of components successfully imported.
    """
    existing_bases = _get_base_component_names()
    yaml_files = sorted(Path(sources_dir).glob("*.yaml"))
    imported_count = 0

    for yaml_path in yaml_files:
        with open(yaml_path) as f:
            yaml_data = yaml.safe_load(f)

        if not yaml_data or "components" not in yaml_data:
            continue

        defaults = yaml_data.get("defaults") or {}

        for component in yaml_data["components"]:
            comp_name = component.get("name", "?")

            if not _needs_import(component, existing_bases, defaults):
                continue

            lcsc_id = _get_prop(component, "LCSC Part")
            log.info(f"Auto-importing '{comp_name}' (LCSC: {lcsc_id})...")

            # 1. Fetch LCSC metadata
            meta = _fetch_lcsc_metadata(lcsc_id) or {}

            # 2. Resolve base_component: component → defaults → easyeda
            effective_base = component.get("base_component") or defaults.get("base_component")
            base_resolved_from_defaults = bool(
                not component.get("base_component") and effective_base
            )

            # 3. Resolve footprint: component → footprint_map[encapStandard] → footprint_map[easyeda_name] → easyeda
            existing_footprint = _get_prop(component, "Footprint")
            footprint_from_defaults = None
            if not existing_footprint:
                footprint_map = defaults.get("footprint_map") or {}
                lcsc_package = meta.get("package", "")
                footprint_from_defaults = footprint_map.get(lcsc_package)

                # Fallback: try EasyEDA footprint name as a key in the map
                if not footprint_from_defaults and footprint_map:
                    easyeda_fp_name = _get_easyeda_footprint_name(lcsc_id)
                    if easyeda_fp_name:
                        footprint_from_defaults = footprint_map.get(easyeda_fp_name)
                        if not footprint_from_defaults:
                            log.info(f"No footprint_map match for encapStandard='{lcsc_package}' "
                                     f"or easyeda_fp='{easyeda_fp_name}'")

            effective_footprint = existing_footprint or footprint_from_defaults

            # 4. Decide whether EasyEDA download is needed
            need_easyeda_symbol = not effective_base or effective_base not in existing_bases
            need_easyeda_footprint = not effective_footprint

            if need_easyeda_symbol or need_easyeda_footprint:
                # Download and import from EasyEDA
                dl = _download_and_import(
                    lcsc_id,
                    component.get("base_component") or None,
                )
                if dl is None:
                    log.error(f"Download failed - skipping '{comp_name}'")
                    continue

                base_component_name = dl["base_component_name"]
                fp_name = dl.get("footprint_name")

                if need_easyeda_symbol:
                    log.success(f"  Base symbol '{base_component_name}' added from EasyEDA")
                    existing_bases.add(base_component_name)
                else:
                    base_component_name = effective_base

                if need_easyeda_footprint and fp_name:
                    log.success(f"  Footprint '{fp_name}' imported from EasyEDA")
                    effective_footprint = f"7Sigma:{fp_name}"
            else:
                # Everything resolved from defaults — no EasyEDA download needed
                base_component_name = effective_base
                if base_resolved_from_defaults:
                    log.success(f"  Using default base symbol '{base_component_name}'")
                if footprint_from_defaults:
                    log.success(f"  Using default footprint '{footprint_from_defaults}' (package: {meta.get('package', '?')})")

            if existing_footprint:
                log.success(f"  Using user-specified footprint '{existing_footprint}'")

            # 5. Build property updates
            props = _build_property_updates(meta, lcsc_id)
            if effective_footprint and not existing_footprint:
                props["Footprint"] = effective_footprint

            # 6. Rewrite YAML
            updates = {
                "base_component": base_component_name,
                "properties": props,
            }
            _rewrite_yaml_component(str(yaml_path), comp_name, updates)
            log.debug("  YAML updated with metadata")

            imported_count += 1
            log.success(f"  Successfully imported '{comp_name}'")

    return imported_count


def fill_missing_properties(
    sources_dir: str = config.SOURCES_DIR,
) -> int:
    """
    Scan all YAML components that have an LCSC Part number and fill in any
    missing metadata properties (Datasheet, Manufacturer, MPN, etc.) from
    the LCSC API.

    Only empty/missing properties are overwritten — existing values are kept.

    Returns the number of components updated.
    """
    yaml_files = sorted(Path(sources_dir).glob("*.yaml"))
    updated_count = 0

    for yaml_path in yaml_files:
        with open(yaml_path) as f:
            yaml_data = yaml.safe_load(f)

        if not yaml_data or "components" not in yaml_data:
            continue

        for component in yaml_data["components"]:
            comp_name = component.get("name", "?")
            lcsc_id = _get_prop(component, "LCSC Part")
            if not lcsc_id:
                continue

            # Check if any fillable property is missing
            fillable_keys = (
                set(_LCSC_PROPERTY_MAP.values()) | set(_LCSC_STATIC_PROPS.keys()) | {"Supplier Part Number 1"}
            )
            has_gap = any(_get_prop(component, k) is None for k in fillable_keys)
            if not has_gap:
                continue

            meta = _fetch_lcsc_metadata(lcsc_id)
            if not meta:
                continue

            props = _build_property_updates(meta, lcsc_id)

            # Only include properties that are actually missing
            existing_props = {p["key"] for p in component.get("properties", [])}
            props_to_fill = {}
            for key, value in props.items():
                current = _get_prop(component, key)
                if current is None and value:
                    props_to_fill[key] = value

            if not props_to_fill:
                continue

            _rewrite_yaml_component(str(yaml_path), comp_name, {"properties": props_to_fill})
            filled = ", ".join(props_to_fill.keys())
            log.success(f"  Filled '{comp_name}': {filled}")
            updated_count += 1

    return updated_count


# ---------------------------------------------------------------------------
# Auto-learn default footprint mappings
# ---------------------------------------------------------------------------


def update_default_mappings(
    sources_dir: str = config.SOURCES_DIR,
) -> int:
    """
    Auto-expand ``defaults.footprint_map`` in each YAML file by learning
    encapStandard → Footprint associations from existing fully-specified
    components.

    For each YAML file:
      1. Collect components that have both an LCSC Part and a Footprint set.
      2. Fetch ``encapStandard`` from the LCSC API (cache avoids duplicate calls).
      3. If all components sharing the same ``encapStandard`` agree on one
         footprint, add the mapping automatically.
      4. If they disagree (conflict), add the package to ``ignore_packages``
         so the warning does not recur.

    If a YAML file has no ``defaults:`` section yet, one is created
    automatically when learnable mappings are found.

    Packages already in ``footprint_map`` or ``ignore_packages`` are skipped.

    Returns the number of new mappings added.
    """
    ryaml = RuamelYAML()
    ryaml.preserve_quotes = True
    ryaml.indent(mapping=2, sequence=4, offset=2)
    ryaml.width = 4096

    yaml_files = sorted(Path(sources_dir).glob("*.yaml"))
    total_added = 0

    for yaml_path in yaml_files:
        with open(yaml_path) as f:
            data = ryaml.load(f)

        if not data or "components" not in data:
            continue

        defaults = data.get("defaults")
        if defaults is None:
            defaults = CommentedMap()
            # Will only be inserted into data if we find learnable mappings
            created_defaults = True
        else:
            created_defaults = False

        footprint_map = defaults.get("footprint_map")
        if footprint_map is None:
            footprint_map = {}
            defaults["footprint_map"] = footprint_map

        ignore_packages = defaults.get("ignore_packages") or []
        ignore_set = set(ignore_packages)

        # Collect components with both LCSC Part and Footprint
        candidates: list[tuple[str, str]] = []
        for comp in data["components"]:
            lcsc_id = _get_prop(comp, "LCSC Part")
            footprint = _get_prop(comp, "Footprint")
            if lcsc_id and footprint:
                candidates.append((lcsc_id, footprint))

        if not candidates:
            continue

        # Smart filtering: only query LCSC for components whose footprint
        # isn't already reachable as a value in the existing map.
        mapped_footprints = set(footprint_map.values())
        to_query = [(lid, fp) for lid, fp in candidates if fp not in mapped_footprints]

        if not to_query:
            continue

        # Fetch encapStandard and group by package
        package_to_footprints: dict[str, set[str]] = {}
        for lcsc_id, footprint in to_query:
            meta = _fetch_lcsc_metadata(lcsc_id)
            if not meta:
                continue
            package = meta.get("package", "").strip()
            if not package or package in footprint_map or package in ignore_set:
                continue
            package_to_footprints.setdefault(package, set()).add(footprint)

        # Add consistent mappings; flag conflicts
        added = 0
        new_ignores: list[str] = []
        for package, footprints in sorted(package_to_footprints.items()):
            if len(footprints) == 1:
                fp = next(iter(footprints))
                footprint_map[DQ(package)] = DQ(fp)
                added += 1
                log.success(f"  Learned: '{package}' \u2192 '{fp}' ({yaml_path.name})")
            else:
                log.warning(
                    f"Conflict: '{package}' maps to {sorted(footprints)} "
                    f"in {yaml_path.name} — added to ignore_packages"
                )
                new_ignores.append(package)

        # Persist ignore_packages for conflicts
        if new_ignores:
            for pkg in new_ignores:
                if pkg not in ignore_set:
                    ignore_packages.append(pkg)
                    ignore_set.add(pkg)
            defaults["ignore_packages"] = ignore_packages

        if added or new_ignores:
            # Rebuild footprint_map as a fresh CommentedMap with all entries
            # quoted.  This avoids ruamel.yaml attaching stale trailing
            # comments from the original last-key to the mapping, which
            # causes new entries to appear after unrelated comment lines.
            fresh_map = CommentedMap()
            for k, v in footprint_map.items():
                fresh_map[DQ(str(k))] = DQ(str(v))
            defaults["footprint_map"] = fresh_map

            # Insert defaults into data if it was newly created
            if created_defaults:
                # Place defaults before validation_rules or components
                insert_pos = 1  # after library_name
                for i, key in enumerate(data.keys()):
                    if key in ("validation_rules", "components"):
                        insert_pos = i
                        break
                data.insert(insert_pos, "defaults", defaults)

            with open(yaml_path, "w") as f:
                ryaml.dump(data, f)
            total_added += added

    return total_added


def main():
    """Standalone entry point."""
    from colors import setup_logging
    setup_logging()
    log.info("EasyEDA Auto-Importer")
    log.debug("=" * 50)
    count = auto_import_missing_components()
    if count > 0:
        log.success(f"Imported {count} component(s) from EasyEDA.")
    else:
        log.info("No missing components to import.")


if __name__ == "__main__":
    main()
