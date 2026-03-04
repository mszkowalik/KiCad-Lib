import copy
import os

from kiutils.symbol import SymbolLib

from kicad_lib import config
from kicad_lib.yaml.helpers import load_yaml_sources, validate_library_names
from kicad_lib.yaml.parser import update_component_properties


def rename_symbol_units(symbol):
    """Rename symbol units to match the symbol entry name."""
    for unit in symbol.units:
        unit.entryName = f"{symbol.entryName}"


def create_or_update_library(yaml_data, symbols_dir):
    """Create or update KiCad symbol libraries based on YAML data."""
    total_components = 0
    library_count = 0

    for lib_data in yaml_data:
        base_lib_path = os.path.join(symbols_dir, "base_library.kicad_sym")
        output_lib_path = os.path.join(symbols_dir, f"{lib_data['library_name']}.kicad_sym")

        # Load the base symbol library
        base_lib = SymbolLib.from_file(base_lib_path)
        new_lib = SymbolLib()

        # Copy version and generator information from base library
        new_lib.version = base_lib.version
        new_lib.generator = base_lib.generator
        new_lib.generator_version = base_lib.generator_version
        new_lib.embedded_fonts = base_lib.embedded_fonts

        for component_data in lib_data["components"]:
            # Find the base component
            base_component = None
            for symbol in base_lib.symbols:
                if symbol.entryName == component_data["base_component"]:
                    base_component = symbol
                    break

            if base_component is None:
                raise ValueError(f"Base component {component_data['base_component']} not found in library")

            # Create a new symbol instance by deep copying the base component
            new_component = copy.deepcopy(base_component)
            new_component.entryName = component_data["name"]
            rename_symbol_units(new_component)
            new_component = update_component_properties(new_component, component_data)

            new_lib.symbols.append(new_component)
            total_components += 1

        new_lib.to_file(output_lib_path)
        library_count += 1

    return total_components, library_count


def generate_symbol_libraries(sources_dir=config.SOURCES_DIR, symbols_dir=config.SYMBOLS_DIR):
    """Generate all symbol libraries from YAML definitions."""
    # Ensure sources directory exists (safe no-op if it already exists)
    os.makedirs(sources_dir, exist_ok=True)

    yaml_data = load_yaml_sources(sources_dir)
    errors = validate_library_names(yaml_data)
    if errors:
        raise ValueError(errors[0])

    total_components, library_count = create_or_update_library(yaml_data, symbols_dir)

    return total_components, library_count
