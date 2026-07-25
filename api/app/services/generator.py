"""Symbol generation core.

Faithful port of kicad_lib/kicad/symbols.py + kicad_lib/yaml/parser.py:
deep-copy a base symbol template, rename it (and its units) to the component
name, then apply the component's ordered properties. The only deliberate
behavior change: template expressions resolve through a safe substitution
instead of raw f-string eval().
"""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

from kiutils.items.common import Effects, Font, Position, Property
from kiutils.symbol import SymbolLib

from .templates import has_template, resolve_templates


def load_symbol_lib_from_text(source_text: str) -> SymbolLib:
    """Parse a .kicad_sym library from text.

    Uses the RAW text (no sanitizing): the vendored kiutils carries the
    KiCad-10 patch and preserves unknown tokens via _unknown_fields, so
    generated output keeps full fidelity with the legacy pipeline."""
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "lib.kicad_sym"
        path.write_text(source_text, encoding="utf-8")
        return SymbolLib.from_file(str(path))


def symbol_lib_to_text(lib: SymbolLib) -> str:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "lib.kicad_sym"
        lib.to_file(str(path))
        return path.read_text(encoding="utf-8")


def rename_symbol_units(symbol) -> None:
    """Rename symbol units to match the symbol entry name (exact port)."""
    for unit in symbol.units:
        unit.entryName = f"{symbol.entryName}"


def apply_properties(
    symbol,
    properties: list[dict],
    remove_properties: list[str] | None,
    warnings: list[str] | None = None,
    context: str = "",
):
    """Port of update_component_properties(). `properties` uses the YAML dict
    shape: {key, value, position?, effects?, showName?} with value None for
    explicit nulls."""
    # Templates resolve against the FINAL property set, not the properties
    # applied so far. Resolving incrementally made `{Key}` depend on where its
    # target happened to sit in the property order — a component whose
    # ki_description came before the property it referenced emitted an
    # "unresolved template" warning even though the property was right there.
    # Later entries win, which preserves injection semantics: an injected
    # default (see footprint_name_props) is overridden by the component's own
    # row. Safe against nesting only because no property value in this library
    # references another property that is itself a template.
    final = {p.key: p.value for p in symbol.properties}
    for prop in properties:
        v = prop.get("value", "")
        final[prop.get("key")] = "" if v is None else v

    for prop in properties:
        key = prop.get("key")
        value = prop.get("value", "")
        if value is None:
            value = ""
        if isinstance(value, str) and has_template(value):
            value = resolve_templates(value, final, warnings, context or str(key))
        value = str(value)

        found = False
        for p in symbol.properties:
            if p.key == key:
                p.value = value
                if "position" in prop:
                    p.position = Position(**prop["position"])
                if "effects" in prop:
                    if p.effects is None:
                        p.effects = Effects()
                    effects_dict = prop["effects"]
                    if "font" in effects_dict:
                        p.effects.font = Font(**effects_dict["font"])
                    if "hide" in effects_dict:
                        p.effects.hide = effects_dict["hide"]
                if "showName" in prop:
                    p.showName = prop["showName"]
                found = True
                break

        if not found:
            effects_dict = prop.get("effects", {})
            new_property = Property(
                key=key,
                value=value,
                position=Position(**prop.get("position", {"X": 0.0, "Y": 0.0, "angle": 0.0})),
                # All new properties hidden by default unless explicitly set
                effects=Effects(font=Font(**effects_dict.get("font", {})), hide=effects_dict.get("hide", True)),
                showName=prop.get("showName", False),
            )
            symbol.properties.append(new_property)

    removed = remove_properties or []
    symbol.properties = [p for p in symbol.properties if p.key not in removed]
    return symbol


class BaseSymbolProvider:
    """Parses each pinned base-symbol source once; hands out the template."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple] = {}

    def get(self, base_name: str, source_text: str, cache_key: str):
        if cache_key not in self._cache:
            lib = load_symbol_lib_from_text(source_text)
            sym = next((s for s in lib.symbols if s.entryName == base_name), None)
            if sym is None and lib.symbols:
                sym = lib.symbols[0]
            if sym is None:
                raise ValueError(f"No symbol found in source for base component {base_name!r}")
            self._cache[cache_key] = (sym, lib)
        return self._cache[cache_key][0]


def build_component_symbol(
    template_symbol,
    component_name: str,
    properties: list[dict],
    remove_properties: list[str] | None,
    warnings: list[str] | None = None,
):
    new_component = copy.deepcopy(template_symbol)
    new_component.entryName = component_name
    rename_symbol_units(new_component)
    return apply_properties(new_component, properties, remove_properties, warnings, component_name)


def build_library_text(meta_lib: SymbolLib, symbols: list) -> str:
    """Assemble a .kicad_sym library, copying version/generator metadata from
    a sample base library (exact port of create_or_update_library)."""
    new_lib = SymbolLib()
    for attr in ("version", "generator", "generator_version", "embedded_fonts"):
        if hasattr(meta_lib, attr) and hasattr(new_lib, attr):
            setattr(new_lib, attr, getattr(meta_lib, attr))
    new_lib.symbols = symbols
    return symbol_lib_to_text(new_lib)


def property_row_to_dict(prop) -> dict:
    """Convert a ComponentProperty DB row back to the YAML dict shape the
    generator consumes (single code path for import and DB-driven writes)."""
    d: dict = {"key": prop.key, "value": None if prop.is_null else prop.value}
    if prop.layout:
        d.update(prop.layout)
    return d


# Legacy YAML property keys ↔ ComponentPrice columns, in emission order.
PRICE_PROP_ORDER = (
    ("Price @1 USD", "price_1"),
    ("Price @100 USD", "price_100"),
    ("Price @Bulk USD", "price_bulk"),
    ("Price Bulk Qty", "bulk_qty"),
    ("Price Source", "source"),
    ("Price Updated", "updated"),
)
PRICE_KEY_TO_COL = dict(PRICE_PROP_ORDER)


def footprint_display_names(db) -> dict[str, str]:
    """`{"7Sigma:<name>": display_name}` for every footprint that has one.

    Built once per generation pass — the map is small (one row per footprint)
    and saves a lookup per component.
    """
    from .. import models as M

    return {
        f"7Sigma:{name}": display
        for name, display in db.query(M.Footprint.name, M.Footprint.display_name).all()
        if display
    }


def footprint_name_props(footprint_ref: str | None, display_names: dict[str, str]) -> list[dict]:
    """The `Footprint_Name` property, derived from the referenced footprint.

    `Footprint_Name` describes the *package* ("0402", "VQFN-14-EP 3.5x3.5mm"),
    so it belongs to the footprint rather than being copy-pasted onto every
    component that uses it. `ki_description` templates reference it as
    `{Footprint_Name}`.

    This is deliberately **prepended** to the component's own properties, not
    appended like `injected_props`: `apply_properties` resolves each template
    against the properties applied *so far*, so a `{Footprint_Name}` inside
    `ki_description` only resolves if the name is already there. Injecting it
    first makes resolution independent of where the component happens to order
    its properties. A component that still carries its own `Footprint_Name`
    comes later in the list and therefore still wins.
    """
    display = display_names.get((footprint_ref or "").strip())
    if not display:
        return []
    return [{"key": "Footprint_Name", "value": display}]


def injected_props(datasheets) -> list[dict]:
    """Datasheets live in their own table, but are injected back into
    generated symbols (and the KiCad HTTP library). First datasheet ->
    native Datasheet field; extras -> hidden custom fields "Datasheet 2", ...

    When a datasheet has a locally stored copy, the injected link points at
    the platform's local file instead of the internet URL.

    Prices are deliberately NOT injected — pricing lives on the platform
    (BOMs, ladders, run economics), not in KiCad symbols. PRICE_PROP_ORDER
    stays: the importer uses it to strip legacy price keys from YAML.
    """
    from ..config import settings

    out: list[dict] = []
    for i, ds in enumerate(datasheets or []):
        key = "Datasheet" if i == 0 else f"Datasheet {i + 1}"
        # Link the local copy only when it's an actual PDF — a stored HTML
        # product page is worse than the live link.
        cur = next(
            (v for v in getattr(ds, "versions", []) if v.id == getattr(ds, "current_version_id", None)),
            None,
        )
        cur_is_pdf = cur is not None and (
            cur.content_type == "application/pdf" or (cur.filename or "").lower().endswith(".pdf")
        )
        # Uploaded files have no source URL at all — the local copy is the
        # only address they have, whatever the format.
        if cur_is_pdf or (cur is not None and not ds.source_url):
            value = f"{settings.public_base_url}/api/datasheets/{ds.id}/file"
        else:
            value = ds.source_url or ""
        out.append({"key": key, "value": value})
    return out
