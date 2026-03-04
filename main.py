#!/usr/bin/env python3
"""
KiCad Library Management System

Main entry point for generating KiCad symbol libraries and updating 3D model paths.
Processes YAML component definitions and creates KiCad symbol libraries with
automated 3D model management.
"""

import os

import config
from colors import get_logger, setup_logging
from component_validator import ComponentValidator
from easyeda_importer import auto_import_missing_components, fill_missing_properties, update_default_mappings
from symbol_generator import generate_symbol_libraries
from update_footprints_models import update_footprints_models

log = get_logger(__name__)


def count_footprints(footprints_dir=config.FOOTPRINTS_DIR):
    """Count the number of footprint files in the library."""
    if not os.path.exists(footprints_dir):
        return 0

    footprint_files = [f for f in os.listdir(footprints_dir) if f.endswith(".kicad_mod")]
    return len(footprint_files)


def main():
    """Main entry point for the KiCad library management system."""
    setup_logging()

    log.info("KiCad Library Management System")
    log.debug("=" * 50)

    # Initialize counters
    total_components = 0
    library_count = 0
    footprint_count = 0

    # Auto-import missing components from EasyEDA/LCSC
    log.info("Checking for missing base components to auto-import...")
    try:
        imported = auto_import_missing_components()
        if imported > 0:
            log.success(f"✓ Auto-imported {imported} component(s) from EasyEDA.")
        else:
            log.success("✓ No missing components to import.")
    except Exception as e:
        log.error(f"✗ Error during auto-import: {e}")
        log.debug("  Continuing with library generation...")

    # Fill missing metadata from LCSC API for existing components
    log.info("Filling missing properties from LCSC API...")
    try:
        filled = fill_missing_properties()
        if filled > 0:
            log.success(f"✓ Filled properties for {filled} component(s).")
        else:
            log.success("✓ All LCSC-sourced components have complete metadata.")
    except Exception as e:
        log.error(f"✗ Error filling properties: {e}")
        log.debug("  Continuing with library generation...")

    # Auto-learn default footprint mappings from existing components
    log.info("Learning default footprint mappings...")
    try:
        learned = update_default_mappings()
        if learned > 0:
            log.success(f"✓ Learned {learned} new footprint mapping(s).")
        else:
            log.success("✓ Footprint mappings are up to date.")
    except Exception as e:
        log.error(f"✗ Error learning mappings: {e}")
        log.debug("  Continuing with library generation...")

    # Run component validation
    log.info("Validating component definitions...")
    try:
        validator = ComponentValidator()
        validation_passed = validator.run_all_validations()

        if not validation_passed:
            log.error("✗ Component validation failed. Please fix errors before proceeding.")
            log.debug("  Run 'python component_validator.py' for detailed error information.")
            return 1

        log.success("✓ Component validation passed.")
    except Exception as e:
        log.error(f"✗ Error during component validation: {e}")
        log.debug("  Continuing with library generation (validation module may not be fully configured)...")

    log.info("Generating symbol libraries from YAML definitions...")
    try:
        total_components, library_count = generate_symbol_libraries()
        log.success("✓ Symbol libraries updated successfully.")
    except Exception as e:
        log.error(f"✗ Error updating symbol libraries: {e}")
        return 1

    log.info("Updating 3D models for footprints...")
    try:
        update_footprints_models()
        log.success("✓ 3D model paths updated successfully.")
    except Exception as e:
        log.error(f"✗ Error updating 3D models: {e}")
        return 1

    # Count footprints
    footprint_count = count_footprints()

    # Display summary
    log.debug("=" * 50)
    log.info("LIBRARY SUMMARY")
    log.debug("=" * 50)
    log.info(f"📦 Component libraries created: {library_count}")
    log.info(f"🔧 Total components generated: {total_components}")
    log.info(f"👠 Footprints in library: {footprint_count}")
    log.debug("=" * 50)

    log.success("\n✓ Library update complete!")
    return 0


if __name__ == "__main__":
    exit(main())
