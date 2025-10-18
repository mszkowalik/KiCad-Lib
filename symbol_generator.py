import os
import copy
from kiutils.symbol import SymbolLib, Symbol
from yaml_parser import update_component_properties


def rename_symbol_units(symbol):
    """Rename symbol units to match the symbol entry name."""
    for unit in symbol.units:
        unit.entryName = f"{symbol.entryName}"


def create_or_update_library(yaml_data, symbols_dir):
    """Create or update KiCad symbol libraries based on YAML data."""
    for lib_data in yaml_data:
        base_lib_path = os.path.join(symbols_dir, "base_library.kicad_sym")
        output_lib_path = os.path.join(symbols_dir, f"{lib_data['library_name']}.kicad_sym")

        # Load the base symbol library
        base_lib = SymbolLib.from_file(base_lib_path)
        new_lib = SymbolLib()

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

        new_lib.to_file(output_lib_path)


def generate_symbol_libraries(sources_dir="./Sources", symbols_dir="./Symbols"):
    """Generate all symbol libraries from YAML definitions."""
    from yaml_parser import load_yaml_files

    # Ensure sources directory exists (safe no-op if it already exists)
    os.makedirs(sources_dir, exist_ok=True)

    yaml_data = load_yaml_files(sources_dir)
    create_or_update_library(yaml_data, symbols_dir)
