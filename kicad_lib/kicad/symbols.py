import copy
import os

from kiutils.symbol import SymbolLib

from kicad_lib import config
from kicad_lib.yaml.helpers import load_base_symbols, load_yaml_sources, validate_library_names
from kicad_lib.yaml.parser import update_component_properties


def rename_symbol_units(symbol):
    """Rename symbol units to match the symbol entry name."""
    for unit in symbol.units:
        unit.entryName = f"{symbol.entryName}"


def create_or_update_library(yaml_data, symbols_dir):
    """Create or update KiCad symbol libraries based on YAML data."""
    total_components = 0
    library_count = 0

    base_lib_dir = os.path.join(symbols_dir, "base_library.kicad_symdir")
    base_symbols = load_base_symbols(base_lib_dir)

    # Read version/generator metadata from any symbol file in the directory
    _sample_lib = SymbolLib.from_file(next(iter(
        f for f in sorted(os.scandir(base_lib_dir), key=lambda e: e.name)
        if f.name.endswith(".kicad_sym")
    )).path)

    for lib_data in yaml_data:
        output_lib_path = os.path.join(symbols_dir, f"{lib_data['library_name']}.kicad_sym")

        new_lib = SymbolLib()
        new_lib.version = _sample_lib.version
        new_lib.generator = _sample_lib.generator
        new_lib.generator_version = _sample_lib.generator_version
        new_lib.embedded_fonts = _sample_lib.embedded_fonts

        for component_data in lib_data["components"]:
            base_component = base_symbols.get(component_data["base_component"])

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
