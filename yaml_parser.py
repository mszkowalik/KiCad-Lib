import os
import yaml
from kiutils.items.common import Property, Position, Effects, Font


def load_yaml_files(directory):
    """Load all YAML files from the specified directory."""
    yaml_files = [f for f in os.listdir(directory) if f.endswith(".yaml") or f.endswith(".yml")]
    data = []
    for yaml_file in yaml_files:
        with open(os.path.join(directory, yaml_file), "r") as f:
            data.append(yaml.safe_load(f))
    return data


def evaluate_property_expression(expression, component):
    """Evaluate property templating expressions like {Value} {Power} etc."""
    local_vars = {prop.key: prop.value for prop in component.properties}
    return eval(f"f'{expression}'", {}, local_vars)


def update_component_properties(base_component, components_data):
    """Update component properties based on YAML component data."""
    properties = components_data["properties"]
    remove_properties = components_data.get("remove_properties", [])

    for prop in properties:
        key = prop.get("key")
        value = prop.get("value", "")

        # Check if value is a string before evaluating the expression
        if isinstance(value, str) and "{" in value and "}" in value:
            value = evaluate_property_expression(value, base_component)

        found = False
        for p in base_component.properties:
            if p.key == key:
                p.value = value
                if "position" in prop:
                    p.position = Position(**prop["position"])
                if "effects" in prop:
                    if p.effects is None:
                        p.effects = Effects()
                    effects_dict = prop["effects"]
                    if "font" in effects_dict:
                        if p.effects.font is None:
                            p.effects.font = Font()
                        p.effects.font = Font(**effects_dict["font"])
                    if "hide" in effects_dict:
                        p.effects.hide = effects_dict["hide"]
                if "showName" in prop:
                    p.showName = prop["showName"]
                found = True
                break

        if not found:
            effects_dict = prop.get("effects", {})
            # All properties hidden by default
            new_property = Property(
                key=key,
                value=value,
                position=Position(**prop.get("position", {"X": 0.0, "Y": 0.0, "angle": 0.0})),
                effects=Effects(font=Font(**effects_dict.get("font", {})), hide=effects_dict.get("hide", True)),  # Default to hidden unless explicitly set
                showName=prop.get("showName", False),
            )
            base_component.properties.append(new_property)

    base_component.properties = [p for p in base_component.properties if p.key not in remove_properties]

    return base_component
