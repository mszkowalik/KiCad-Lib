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


def main():
    """Main entry point for the KiCad library management system."""
    print("KiCad Library Management System")
    print("=" * 50)

    print("Generating symbol libraries from YAML definitions...")
    try:
        generate_symbol_libraries()
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

    print("\n✓ Library update complete!")
    return 0


if __name__ == "__main__":
    exit(main())
