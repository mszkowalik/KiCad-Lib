#!/usr/bin/env python3
"""
KiCad Library Management System

Main entry point for generating KiCad symbol libraries and updating 3D model paths.
Processes YAML component definitions and creates KiCad symbol libraries with
automated 3D model management.
"""

import os
from symbol_generator import generate_symbol_libraries
from update_footprints_models import update_footprints_models


def count_footprints(footprints_dir="./Footprints/7Sigma.pretty"):
    """Count the number of footprint files in the library."""
    if not os.path.exists(footprints_dir):
        return 0
    
    footprint_files = [f for f in os.listdir(footprints_dir) if f.endswith('.kicad_mod')]
    return len(footprint_files)


def main():
    """Main entry point for the KiCad library management system."""
    print("KiCad Library Management System")
    print("=" * 50)

    # Initialize counters
    total_components = 0
    library_count = 0
    footprint_count = 0

    print("Generating symbol libraries from YAML definitions...")
    try:
        total_components, library_count = generate_symbol_libraries()
        print("✓ Symbol libraries updated successfully.")
    except Exception as e:
        print(f"✗ Error updating symbol libraries: {e}")
        return 1

    print("\nUpdating 3D models for footprints...")
    try:
        update_footprints_models()
        print("✓ 3D model paths updated successfully.")
    except Exception as e:
        print(f"✗ Error updating 3D models: {e}")
        return 1

    # Count footprints
    footprint_count = count_footprints()

    # Display summary
    print("\n" + "=" * 50)
    print("LIBRARY SUMMARY")
    print("=" * 50)
    print(f"📦 Component libraries created: {library_count}")
    print(f"🔧 Total components generated: {total_components}")
    print(f"👠 Footprints in library: {footprint_count}")
    print("=" * 50)

    print("\n✓ Library update complete!")
    return 0


if __name__ == "__main__":
    exit(main())
