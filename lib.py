import os
import yaml
import copy
from kiutils.symbol import SymbolLib, Symbol
from kiutils.items.common import Property, Position, Effects, Font

def load_yaml_files(directory):
    yaml_files = [f for f in os.listdir(directory) if f.endswith('.yaml') or f.endswith('.yml')]
    data = []
    for yaml_file in yaml_files:
        with open(os.path.join(directory, yaml_file), 'r') as f:
            data.append(yaml.safe_load(f))
    return data

def evaluate_property_expression(expression, component):
    local_vars = {prop.key: prop.value for prop in component.properties}
    return eval(f"f'{expression}'", {}, local_vars)

def update_component(base_component, components_data):
    properties = components_data["properties"]
    remove_properties = components_data.get("remove_properties", [])
    for prop in properties:
        key = prop.get('key')
        value = prop.get('value', '')

        # Check if value is a string before evaluating the expression
        if isinstance(value, str) and '{' in value and '}' in value:
            value = evaluate_property_expression(value, base_component)

        found = False
        for p in base_component.properties:
            if p.key == key:
                p.value = value
                if 'position' in prop:
                    p.position = Position(**prop['position'])
                if 'effects' in prop:
                    if p.effects is None:
                        p.effects = Effects()
                    effects_dict = prop['effects']
                    if 'font' in effects_dict:
                        if p.effects.font is None:
                            p.effects.font = Font()
                        p.effects.font = Font(**effects_dict['font'])
                    if 'hide' in effects_dict:
                        p.effects.hide = effects_dict['hide']
                if 'showName' in prop:
                    p.showName = prop['showName']
                found = True
                break

        if not found:
            effects_dict = prop.get('effects', {})
            default_effects = Effects(
                hide = True if not key in ["Value", "Reference"] else False
            )
            new_property = Property(
                key=key,
                value=value,
                position=Position(**prop.get('position', {"X": 0.0, "Y": 0.0, "angle": 0.0})),
                effects=Effects(
                    font=Font(**effects_dict.get('font', {})),
                    hide=effects_dict.get('hide', True)
                ) if effects_dict else default_effects,
                showName=prop.get('showName', False)
            )
            base_component.properties.append(new_property)

    base_component.properties = [p for p in base_component.properties if p.key not in remove_properties]

    return base_component

def rename_symbol_units(symbol):
    for unit in symbol.units:
        unit.entryName = f"{symbol.entryName}"

def create_or_update_library(yaml_data, directory):
    for lib_data in yaml_data:
        base_lib_path = os.path.join(directory, 'base_library.kicad_sym')
        output_lib_path = os.path.join(directory, f"{lib_data['library_name']}.kicad_sym")

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
            new_component = update_component(new_component, component_data)

            new_lib.symbols.append(new_component)

        new_lib.to_file(output_lib_path)

def main():
    directory = './components'
    yaml_data = load_yaml_files(directory)
    create_or_update_library(yaml_data, directory)

if __name__ == "__main__":
    main()