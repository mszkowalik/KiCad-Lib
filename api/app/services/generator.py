"""Symbol generation core.

Faithful port of kicad_lib/kicad/symbols.py + kicad_lib/yaml/parser.py:
deep-copy a base symbol template, rename it (and its units) to the component
name, then apply the component's ordered properties. The only deliberate
behavior change: template expressions resolve through a safe substitution
instead of raw f-string eval().
"""
from __future__ import annotations

import copy
import re
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


# Property-hidden maps per base-symbol VERSION. In-process and advisory, keyed
# on the version id (observable state): an approved base symbol gets a new id,
# so a stale entry can never be served.
_BASE_HIDDEN_BY_SYMBOL_VERSION: dict[int, dict[str, bool]] = {}


def _hidden_props_in_lib_text(source_text: str, entry_name: str) -> dict[str, bool]:
    """{property key: drawn hidden} for `entry_name` in a .kicad_sym text.
    Reads the modern `(hide yes)` node at property or effects level and the
    legacy bare `hide` atom; an unparseable or absent symbol yields {}."""
    from ..util.sexpr import _norm, find_node, iter_nodes, parse_sexpr, sanitize_symbol_text, walk_nodes

    try:
        tree = parse_sexpr(sanitize_symbol_text(source_text))
    except Exception:
        return {}
    for sym in walk_nodes(tree, "symbol"):
        if len(sym) < 2 or _norm(sym[1]) != entry_name:
            continue
        out: dict[str, bool] = {}
        for prop in iter_nodes(sym, "property"):
            if len(prop) < 2:
                continue
            hidden = False
            for hide in walk_nodes(prop, "hide"):
                if len(hide) < 2 or _norm(hide[1]).lower() in ("yes", "true"):
                    hidden = True
                    break
            if not hidden:
                eff = find_node(prop, "effects") or []
                atoms = [a for a in list(prop) + list(eff) if not isinstance(a, list)]
                hidden = any(_norm(a) == "hide" for a in atoms)
            out[_norm(prop[1])] = hidden
        return out
    return {}


def base_hidden_maps(db, names) -> dict[str, dict[str, bool]]:
    """`{base_component: {property key: drawn hidden}}` for many templates at once.

    Same answer `schematic_field_visibility` needs per component, resolved for a
    whole catalog page in two queries instead of two per row. The KiCad symbol
    chooser asks for every part of a category in one response, so a per-row
    Symbol lookup here is a per-part query on that critical path.
    """
    from .. import models as M

    names = {n for n in names if n}
    if not names:
        return {}
    by_name = {
        name: svid
        for name, svid in db.query(M.Symbol.name, M.Symbol.current_version_id)
        .filter(M.Symbol.name.in_(names))
        .all()
        if svid
    }
    missing = {svid for svid in by_name.values() if svid not in _BASE_HIDDEN_BY_SYMBOL_VERSION}
    if missing:
        by_id = {svid: name for name, svid in by_name.items()}
        for svid, text in (
            db.query(M.SymbolVersion.id, M.SymbolVersion.source_text)
            .filter(M.SymbolVersion.id.in_(missing))
            .all()
        ):
            _BASE_HIDDEN_BY_SYMBOL_VERSION[svid] = _hidden_props_in_lib_text(text, by_id[svid])
        for svid in missing:  # a dangling current_version_id must not be re-queried
            _BASE_HIDDEN_BY_SYMBOL_VERSION.setdefault(svid, {})
    return {name: _BASE_HIDDEN_BY_SYMBOL_VERSION[svid] for name, svid in by_name.items()}


def schematic_field_visibility(db, cv, base: dict[str, bool] | None = None) -> dict[str, bool]:
    """{key: visible-on-schematic} for a component version's properties.

    The rule `apply_properties` bakes into the generated mirror symbols: a key
    the base symbol carries inherits the base effects, any other key is added
    hidden, and the row's `layout` effects override either. Visibility is
    curated ON THE BASE SYMBOL; the component only holds values.
    `ComponentProperty.hide` is NOT part of the rule — the generator never
    reads that column (it is True on almost every imported row), so any
    consumer that wants to agree with the mirror must not either.

    Pass `base` (one entry of `base_hidden_maps`) when resolving many versions
    that share templates — it skips this row's own template lookup.
    """
    if base is None:
        base = base_hidden_maps(db, {cv.base_component}).get(cv.base_component) or {}
    if not base:
        # unknown or unparseable template: KiCad's own default is a visible Value
        base = {"Value": False}

    out: dict[str, bool] = {}
    for p in cv.properties:
        hidden = base.get(p.key, True)
        eff = (p.layout or {}).get("effects") or {}
        if "hide" in eff:
            hidden = bool(eff["hide"])
        out[p.key] = not hidden
    return out


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


# Canonical Sim.Library value in mirror files. Server-side only (the render
# containers define SEVENSIGMA_DIR); the two egress points rewrite it to the
# PCM-installed path the user's KiCad can resolve — kicad_http.py at serve
# time, pcm.py at package time — exactly as both already rewrite 3D model
# paths. Emitting the installed path here instead would bake a version-pinned
# KICAD10_3RD_PARTY into the mirror, which server-side tooling cannot resolve.
SIM_LIB_MIRROR_PATH = "${SEVENSIGMA_DIR}/Symbols/7Sigma_sim.sp"


def sim_props(link: dict | None) -> list[dict]:
    """The four link-derived `Sim.*` fields for one component symbol.

    `link` is mirror.py's resolved view of the symbol's `SymbolSimLink`:
    `{"model": subckt name, "sim_pins": "1=out 2=vee ...", "stale": bool}`,
    or None when the symbol has no link. A stale link (either fingerprint
    moved since the map was authored) emits NOTHING — a possibly mis-wired
    map must not reach a netlist, and the mirror warns about it instead.

    `Sim.Params` is deliberately not emitted: datasheet numbers are the
    component's own property row, and a component without one simply gets
    the subcircuit's declared defaults. Like `footprint_name_props`, this is
    prepended, so a component carrying its own `Sim.*` rows (the per-part
    override, and today's hand-written pilot) still wins.
    """
    if not link or link.get("stale") or not link.get("model"):
        return []
    return [
        {"key": "Sim.Device", "value": "SUBCKT"},
        {"key": "Sim.Name", "value": link["model"]},
        {"key": "Sim.Library", "value": SIM_LIB_MIRROR_PATH},
        {"key": "Sim.Pins", "value": link["sim_pins"]},
    ]


# SPICE's own primitive letters. A symbol whose reference prefix is one of
# these needs NO model: `R116 /SAFETY/SI1 Net-_D15-C_ 100k` is complete SPICE,
# built by KiCad from the reference prefix and the Value field. `#PWR` items
# are not devices at all — they are how GND and 3V3 get their net names.
# Every OTHER symbol with no sim link emits `U47 __U47`, an element with an
# undefined model, and ngspice stops the run.
SIM_NATIVE_PREFIXES = {"R", "C", "L", "#PWR"}


def set_exclude_from_sim(symbol, linked: bool) -> None:
    """Force `exclude_from_sim` from the link set. DERIVED state, not authored.

    Forced in both directions on purpose: a symbol that gains a model must stop
    being excluded, or it would stay silently absent from every netlist.

    What this must NOT exclude, and why:

    - Native primitives and power symbols (above). Excluding a resistor deletes
      94 of the 132 elements in the SAFETY deck.
    - Two-pin SERIES parts — fuse, polyfuse, ferrite bead, NTC. Those are
      modelled (`sigma_fuse`, `sigma_ferrite`, `sigma_ntc`) rather than
      excluded, because dropping a series element turns a live rail into an
      open circuit with NO error, which is worse than the loud failure a
      missing model gives.
    - A STALE link, which still counts as linked here. Its `Sim.*` fields are
      withheld by `sim_props`, so the netlist fails loudly — excluding the part
      instead would mute exactly the alarm the staleness warning exists to
      raise.
    """
    ref = next((p.value for p in (symbol.properties or []) if p.key == "Reference"), "")
    symbol.exclude_from_sim = sim_excluded(ref, linked)


def sim_excluded(reference_prefix: str, linked: bool) -> bool:
    """The same rule for callers holding a prefix string, not a kiutils Symbol.

    The HTTP library is the one that matters for an existing schematic: KiCad
    places parts by their HTTP `lib_id`, and `Update Symbols from Library`
    rewrites the instance from THAT record, not from the base .kicad_sym. The
    HTTP part record carries its own `exclude_from_sim` and KiCad treats an
    ABSENT flag as "not excluded", so the payload must state it explicitly or
    every symbol update silently re-includes parts that have no model.
    """
    return not (linked or reference_prefix in SIM_NATIVE_PREFIXES)


_BASE_REF_BY_SYMBOL_VERSION: dict[int, str] = {}


def base_reference_prefixes(db, names) -> dict[str, str]:
    """`{base_component: reference prefix}` for many templates at once.

    Same batching contract as `base_hidden_maps` — the symbol chooser asks for
    a whole category in one response, so a per-row Symbol lookup here would sit
    on that critical path."""
    from .. import models as M

    names = {n for n in names if n}
    if not names:
        return {}
    by_name = {
        name: svid
        for name, svid in db.query(M.Symbol.name, M.Symbol.current_version_id)
        .filter(M.Symbol.name.in_(names))
        .all()
        if svid
    }
    missing = {svid for svid in by_name.values() if svid not in _BASE_REF_BY_SYMBOL_VERSION}
    if missing:
        for svid, text in (
            db.query(M.SymbolVersion.id, M.SymbolVersion.source_text)
            .filter(M.SymbolVersion.id.in_(missing))
            .all()
        ):
            m = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', text or "")
            _BASE_REF_BY_SYMBOL_VERSION[svid] = m.group(1) if m else ""
        for svid in missing:
            _BASE_REF_BY_SYMBOL_VERSION.setdefault(svid, "")
    return {name: _BASE_REF_BY_SYMBOL_VERSION[svid] for name, svid in by_name.items()}


def injected_props(datasheets) -> list[dict]:
    """Datasheets live in their own table, but are injected back into
    generated symbols (and the KiCad HTTP library). First datasheet ->
    native Datasheet field; extras -> hidden custom fields named after their
    own label, so a part with several attached documents (reference
    schematics, an eval-board datasheet, ...) shows what each one actually is
    from inside KiCad's Symbol Fields table, not just an index. Falls back to
    "Datasheet N" when a label is blank, the generic default, or would
    collide with an already-used field name.

    When a datasheet has a locally stored copy, the injected link points at
    the platform's local file instead of the internet URL.

    Prices are deliberately NOT injected — pricing lives on the platform
    (BOMs, ladders, run economics), not in KiCad symbols. PRICE_PROP_ORDER
    stays: the importer uses it to strip legacy price keys from YAML.
    """
    from ..config import settings

    out: list[dict] = []
    seen: set[str] = set()
    for i, ds in enumerate(datasheets or []):
        if i == 0:
            key = "Datasheet"
        else:
            label = (ds.label or "").strip()
            key = label if label and label != "Datasheet" else f"Datasheet {i + 1}"
            if key in seen:
                key = f"{key} ({i + 1})"
        seen.add(key)
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


VERSION_PROP_KEY = "7S Version"


def version_prop(cv_no: int | None, sym_no: int | None, fp_no: int | None) -> list[dict]:
    """The merged library-version field baked into every emitted symbol.

    ``"c5 s3 f7"`` = component version 5, pinned symbol version 3, pinned
    footprint version 7. It lands (hidden) on every placed symbol, so a
    project committed to git records exactly which library versions the board
    was drawn with — the BOM extractor reads it back into
    ``SnapshotBomLine.lib_version``. Missing legs are simply omitted.
    """
    parts = [f"{tag}{no}" for tag, no in (("c", cv_no), ("s", sym_no), ("f", fp_no)) if no]
    if not parts:
        return []
    return [{"key": VERSION_PROP_KEY, "value": " ".join(parts)}]
