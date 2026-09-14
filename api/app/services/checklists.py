"""Review checklists: the seed content, and resolution for a given subject.

A checklist item is ``{key, text, hint?, machine?, severity?, …}``. ``key`` is the
stable identity (check records reference items by key across checklist
revisions). ``machine: true`` items are answered automatically by
``services/validator.py`` on every publish; the rest are judgment calls for an
agent or a human.

**The validator owns the automatic checks, the checklist owns whether they
run.** ``validator.machine_checks(db)`` is the catalogue — key, text and hint —
so an automatic item's wording is never typed into a checklist and cannot drift
from the code. A checklist carries the machine item only to say ON or OFF. The
wording is built from the item's OWN ``params``, so the sentence a reviewer
reads and the comparison the code makes are the same fact.

``params`` is the other half: the numbers, lists and patterns a check measures
against, stored on the item that uses them. For a component they inherit
through category-scoped checklists, which is what gives a category its own
property rules with no second merge engine behind it.

``severity`` (``error`` / ``warning`` / ``ignore``) says what a FAILURE of this
check means, and ``ignore`` is also how a scope switches the check off — one
control with three values rather than a switch beside a severity. It applies at
this level **and below**: the merge is otherwise additive, so without it a
category-scoped list could add and reword items but never say "this base check
does not apply to my parts". An ignored item is dropped from
``resolve()["items"]`` and reported separately in ``resolve()["disabled"]``, so
nothing measures it, the validator is not asked for it
(`services/conformance.py`), and the editor can still show what was switched
off and where.

``disabled: true`` is the retired spelling of ``severity: "ignore"``. It is
still READ (`severity_of`) because a checklist version is immutable and
rewriting one would change what a past verification was measured against;
nothing writes it any more.

Resolution (`resolve`) merges the base checklist for the subject kind with any
category-scoped checklists on the component's category path. Seeds land once,
on startup, and only for kinds that have no base checklist yet — edits made in
the UI are never overwritten.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .. import models as M

BASE_NAMES = {
    "component": "Component base checklist",
    "symbol": "Symbol base checklist",
    "footprint": "Footprint base checklist",
}

#: Automatic checks a FRESH install starts as WARNINGS rather than errors.
#: They used to be seeded switched off, which was "off" standing in for "on, but
#: not urgent" — the honest spelling of that is a warning (2026-09-14).
#: The two simulation checks answer `na` for anything with no sim model, and
#: whether a library wants them at error level was deliberately left to its
#: owner (validator.py note, 2026-08-25). The two category checks
#: (`cmp.property_values`, `cmp.base_symbol_allowed`) carry an empty set at the
#: base, so they have nothing to say until a CATEGORY fills one in.
#: What a failing check MEANS. One control with three values, not a switch
#: beside a severity: KiCad carries one on all 101 of its DRC and ERC rules, and
#: `ignore` is the same statement our `disabled` flag used to make.
#:
#: `error`   — a failure is a defect; it drives the subject's state.
#: `warning` — a failure is worth seeing and does NOT make the subject failed.
#: `ignore`  — the check does not run here at all (the old `disabled: true`).
#:
#: The middle value is what lets a new check ship at all. Four checks were
#: seeded switched OFF purely because turning a live machine item on re-opens
#: the whole library — `cmp.datasheet_text` moved 418 components to partial in
#: one publish. "Off" was standing in for "on, but not urgent", which is what
#: `warning` actually says.
SEVERITIES = ("error", "warning", "ignore")
DEFAULT_SEVERITY = "error"


def severity_of(item: dict) -> str:
    """An item's severity, reading the retired `disabled: true` as `ignore`.

    Rows written before 2026-09-14 carry the flag; nothing writes it any more
    and `_validate_items` converts it on the next save. Read compatibility is
    kept rather than migrated in place, because a checklist version is immutable
    and rewriting one would change what a past verification was measured
    against."""
    sev = str(item.get("severity") or "").strip()
    if sev in SEVERITIES:
        return sev
    return "ignore" if item.get("disabled") else DEFAULT_SEVERITY


SEED_AS_WARNING = {"sym.sim_link", "cmp.sim_params", "cmp.property_values",
                   "cmp.base_symbol_allowed"}

#: The JUDGMENT items only — what a person or an agent has to decide. The
#: automatic ones are composed from `validator.machine_checks` by `_seed_items`,
#: so there is one place where an automatic check's wording lives.
SEED_ITEMS: dict[str, list[dict]] = {
    "footprint": [
        {"key": "fp.land_pattern",
         "text": "Pad sizes, pitch and positions match the datasheet land-pattern drawing",
         "hint": "Compare against the recommended land pattern page, not the package outline."},
        {"key": "fp.pad_numbering", "text": "Pad numbering follows the datasheet pin numbering",
         "hint": "Connector pad numbering always follows the datasheet, never the housing."},
        {"key": "fp.body_outline", "text": "Fab body outline matches the package dimensions"},
        {"key": "fp.origin", "text": "Origin placement follows the convention (centred on the body)"},
        {"key": "fp.naming", "text": "Name follows the footprint naming standard (twelve-slot order)"},
        {"key": "fp.model_fit", "text": "The 3D model aligns with the drawn footprint"},
    ],
    "symbol": [
        {"key": "sym.pinout", "text": "Pin numbers and names match the datasheet pinout",
         "hint": "Check every pin against the datasheet pinout table, including NC pins."},
        {"key": "sym.pin_types",
         "text": "Pin electrical types are correct from the component's own viewpoint"},
        {"key": "sym.grouping", "text": "Pins are grouped by functional block with 2.54 mm gaps"},
        {"key": "sym.geometry", "text": "Box size, pin pitch and stub length follow the geometry rules",
         "hint": "Stub length is 2.54 mm unless a pin number runs to three or more characters, "
                 "which needs 5.08 mm to fit the number on the stub."},
        {"key": "sym.stacked", "text": "Shorted pins are stacked per the convention (where applicable)"},
    ],
    "component": [
        {"key": "cmp.mpn", "text": "MPN and manufacturer match the datasheet / product page",
         "hint": "EasyEDA and distributor data are leads, not facts — confirm in the datasheet."},
        {"key": "cmp.electrical", "text": "Electrical property values match the datasheet"},
        {"key": "cmp.description", "text": "ki_description follows the category template and is correct"},
        {"key": "cmp.value_field", "text": "The Value field follows the Value rule for the category"},
        {"key": "cmp.category", "text": "The component sits in the correct category"},
        {"key": "cmp.datasheet", "text": "The attached datasheet is the right document for this exact part"},
        {"key": "cmp.base_symbol", "text": "The chosen base symbol fits the part (pin count, roles)"},
    ],
}


def machine_item(db: Session, kind: str, key: str, *,
                 severity: str = DEFAULT_SEVERITY) -> dict | None:
    """One automatic item, worded by the validator's live catalogue.

    The checklist never authors this text — it stores the key, the machine flag
    and whether the check is on.
    """
    from . import validator

    entry = validator.machine_check(db, kind, key)
    if entry is None:
        return None
    item = {"key": entry["key"], "text": entry["text"], "machine": True}
    if entry.get("hint"):
        item["hint"] = entry["hint"]
    if entry.get("params"):
        # The numbers this check compares against live on the ITEM, so they
        # version with the checklist and the review record's snapshot records
        # what a past verification was measured against.
        item["params"] = dict(entry["params"])
    if severity != DEFAULT_SEVERITY:
        item["severity"] = severity
    return item


def _seed_items(db: Session, kind: str) -> list[dict]:
    """Every automatic check for the kind, then the judgment items."""
    from . import validator

    machine = [machine_item(db, kind, key,
                            severity="warning" if key in SEED_AS_WARNING else DEFAULT_SEVERITY)
               for key in validator.MACHINE_KEYS.get(kind, ())]
    return [m for m in machine if m is not None] + list(SEED_ITEMS[kind])


def seed_checklists(db: Session) -> list[str]:
    """Create the base checklist per kind where none exists. Idempotent."""
    created: list[str] = []
    for kind, name in BASE_NAMES.items():
        exists = (
            db.query(M.Checklist)
            .filter_by(subject_kind=kind, category_id=None)
            .first()
        )
        if exists is not None:
            continue
        cl = M.Checklist(name=name, subject_kind=kind, category_id=None,
                         description=f"Base verification checklist for every {kind}")
        db.add(cl)
        db.flush()
        cv = M.ChecklistVersion(checklist_id=cl.id, version_no=1,
                                items=_seed_items(db, kind), status="published",
                                created_by="seed", comment="Initial seed")
        db.add(cv)
        db.flush()
        cl.current_version_id = cv.id
        created.append(name)
    if created:
        db.commit()
    return created


def _current_items(cl: M.Checklist) -> tuple[int | None, list[dict]]:
    cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
    if cv is None:
        return None, []
    return cv.id, list(cv.items or [])


#: Every fact a `when` predicate or an `assert` may name, besides a component
#: property. A property is written bare (`comp_type`); these carry a `$` so a
#: category named "category" can never be confused with the category itself,
#: and so a misspelled fact is REFUSED at save time rather than silently
#: matching nothing. Properties cannot be validated that way — any string is a
#: legal property name — which is the asymmetry to keep in mind when writing
#: one.
#:
#: `kinds` is which SUBJECTS carry the fact. A predicate naming a fact the
#: subject has not got never matches, which is the honest outcome, but the
#: editor uses this to say so before anybody saves a rule that can match
#: nothing.
#:
#: `noun` is the phrase the generated sentence of an `assert` uses as its
#: subject. Without one the name is de-`$`-ed and de-underscored, which yields
#: "The footprint zero annulus pads is at most 0" — correct, and not a sentence
#: anybody wants on a review card.
#:
#: `lazy` marks a fact computed only when something asks for it. Parsing every
#: symbol and footprint on the coverage endpoint would turn a page into a
#: minute; `_LazyFacts` memoises each on first read, so a checklist that
#: mentions none costs nothing at all.
FACTS: tuple[dict, ...] = (
    # ------------------------------------------------------------ structural
    {"name": "$kind", "kinds": ("component", "symbol", "footprint"),
     "what": "component, symbol or footprint"},
    {"name": "$name", "kinds": ("component", "symbol", "footprint"),
     "what": "the subject's own name"},
    {"name": "$category", "kinds": ("component",),
     "what": "top-level category name"},
    {"name": "$category_path", "kinds": ("component",),
     "what": "full category path, slash separated"},
    {"name": "$base_symbol", "kinds": ("component",),
     "what": "the base symbol this component is drawn as"},
    {"name": "$footprint", "kinds": ("component",),
     "what": "the Footprint property, library prefix included"},
    {"name": "$in_library", "kinds": ("component",),
     "claim": "KiCad is served this part",
     "what": "true when KiCad is served this part"},
    {"name": "$purchasable", "kinds": ("component",),
     "claim": "The part is purchased rather than generic",
     "what": "true when the part is bought rather than generic"},
    {"name": "$lifecycle", "kinds": ("component",),
     "what": "in design / released / deprecated / obsolete"},
    # ------------------------------------------------------- fingerprints
    #: What a standing exception pins when it is scoped to the DRAWING rather
    #: than to the part (`services/exceptions.py`). `$material_sha` covers what
    #: reaches the board — pads, courtyard, pin set — and deliberately not
    #: silkscreen or a description, so a cosmetic edit never kills a waiver.
    #: `$property_sha` is the component's own data, for a waiver about a VALUE
    #: rather than about a drawing.
    {"name": "$material_sha", "kinds": ("component", "symbol", "footprint"),
     "what": "fingerprint of what reaches the board"},
    {"name": "$property_sha", "kinds": ("component",),
     "what": "fingerprint of the component's own fields"},
    # ------------------------------------------------------------- symbol
    {"name": "$symbol_reference", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "symbol reference prefix",
     "what": "the Reference prefix drawn on the symbol (R, C, U…)"},
    {"name": "$symbol_pin_count", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "symbol pin count",
     "what": "how many pins the symbol draws"},
    {"name": "$symbol_pin_numbers", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of distinct pin numbers",
     "what": "how many DISTINCT pin numbers — fewer than the pin count when pins are stacked"},
    {"name": "$symbol_unit_count", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "symbol unit count",
     "what": "how many units (gates) the symbol has"},
    {"name": "$symbol_on_board", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "symbol's on-board flag",
     "claim": "The symbol is placed on the board",
     "what": "false for a symbol excluded from the board"},
    {"name": "$symbol_sim_link", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "simulation link",
     "claim": "A simulation model is linked",
     "what": "true when a simulation model is linked"},
    {"name": "$symbol_pin_types", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "set of pin types",
     "what": "the distinct electrical pin types present, comma separated and sorted"},
    #: `conventions-symbols` §3 — nothing electrical on the top edge, with one
    #: documented exception (§5.6 digital blocks, where the top and bottom
    #: edges carry the asynchronous controls). A COUNT, so the exception lives
    #: in the checklist as a `when` rather than inside Python.
    {"name": "$symbol_top_edge_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of signal or supply pins on the top edge",
     "what": "signal or supply pins on the TOP edge"},
    {"name": "$symbol_bottom_edge_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of signal or supply pins on the bottom edge",
     "what": "signal or supply pins on the BOTTOM edge"},
    #: Stacking shows two pin NUMBERS shorted at one point, so it is counted by
    #: POSITION. 185 of 207 symbols have none, and the question was being asked
    #: of every one of them — 136 carried a hand-written `na` saying so.
    {"name": "$symbol_power_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of supply pins", "what": "pins typed power_in or power_out"},
    {"name": "$symbol_pin_names_hidden", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "the symbol's hidden-pin-names flag",
     "claim": "The symbol hides its pin names",
     "what": "true when (pin_names (hide yes)) is set on the symbol"},
    {"name": "$symbol_stacked_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of stacked pins",
     "what": "pins sharing a position with another pin in the same unit"},
    {"name": "$symbol_unstacked_duplicate_signals", "kinds": ("component", "symbol"),
     "lazy": True, "noun": "count of same-named SIGNAL pins drawn at different points",
     "what": "same-named pins on different points, supply pins excluded — the half a large "
             "IC's deliberately separate GND and VDD pads cannot explain"},
    {"name": "$symbol_unstacked_duplicates", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of same-named pins drawn at different points",
     "what": "pins sharing a NAME but not a position — either a deliberate large-IC drawing "
             "or a part that should have stacked"},
    {"name": "$symbol_stub_lengths", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of different pin stub lengths",
     "what": "how many DISTINCT pin stub lengths the drawing mixes — more than one is the defect"},
    #: `conventions-symbols` §4 — the stub is the space KiCad has to print the
    #: pin NUMBER along, so the number's WIDTH is what drives the 5.08 mm
    #: exception. An earlier rule said "very high pin count" and was wrong:
    #: a 3-pin regulator and a 4-pin LDO both legitimately carry 5.08 mm.
    {"name": "$symbol_value_default_is_name", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "drawn Value default against the symbol name",
     "claim": "The drawn Value default is the symbol's own name",
     "what": "true when the Value a sheet shows is the symbol's own name rather than one "
             "particular part's rating or part number"},
    {"name": "$symbol_visible_value_default", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "the Value default the symbol draws",
     "what": "the Value string a sheet shows until a component overrides it — absent when "
             "Value is hidden"},
    {"name": "$symbol_sourcing_defaults", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of sourcing defaults stored on the drawing",
     "what": "LCSC/Supplier/Manufacturer property defaults on the base symbol, which the "
             "generator would inherit onto every component built from it"},
    {"name": "$symbol_named_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of pins carrying a name",
     "what": "pins with a real name rather than a bare numbered stub — what makes a "
             "pinout TABLE checkable"},
    {"name": "$symbol_has_box", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "rectangular body",
     "claim": "The symbol draws a rectangular body",
     "what": "true when the drawing has a (rectangle) body — false for a glyph"},
    #: How many DIFFERENT parts are drawn on this base symbol. A generic
    #: template (R, C, Q_NMOS_GSD, 8P8C) serves many MPNs and has no single
    #: datasheet pinout to check against; a part-specific drawing serves one.
    #: The bridge from the component axis to the drawing axis. Without it a
    #: symbol rule can only be scoped by geometry, and geometry cannot tell an
    #: op-amp from an ESD array that also hides its pin names.
    {"name": "$symbol_family_choice", "kinds": ("symbol",), "lazy": True,
     "noun": "drawing-family choice",
     "claim": "The drawing family is a choice for this part",
     "what": "false when every component on this symbol is drawn to a fixed "
             "pictogram — a transistor, diode, passive, connector or mechanical "
             "part; see FIXED_PICTOGRAM"},
    #: The one thing in a drawing that cannot be corrected later. A pin NUMBER
    #: is what maps a schematic pin to a footprint pad, so changing one rewires
    #: every board already laid out with the symbol, silently. Names, electrical
    #: types and positions are all fixable toward the datasheet; this is not.
    #: ABSENT on a first version — there is nothing to compare against, and the
    #: check then answers `na` rather than claiming the drawing is unchanged.
    #: Six glyph checks were one table of numbers. The amplifier and gate
    #: families are drawn to fixed coordinates, quoted to the 0.01 mm in the
    #: hints, and asking a person to compare them by eye produced ZERO answers
    #: in the library's history. ABSENT unless the symbol is drawn as a
    #: triangle — `sym.drawing_family` still owns whether it should be.
    {"name": "$symbol_family_drawing_off", "kinds": ("symbol",), "lazy": True,
     "noun": "count of family drawing elements off the house coordinates",
     "what": "body vertices, pin positions and polarity marks that do not sit where "
             "the triangle family puts them"},
    {"name": "$symbol_pins_changed", "kinds": ("symbol",), "lazy": True,
     "noun": "count of pin numbers changed since the previous version",
     "what": "pin numbers added, removed, or moved to a different unit since the "
             "previous version of this drawing"},
    {"name": "$symbol_comp_types", "kinds": ("symbol",), "lazy": True,
     "noun": "component types drawn on this symbol",
     "what": "the comp_type values of the components using this base symbol, "
             "sorted and comma separated"},
    {"name": "$symbol_lcsc_parts", "kinds": ("symbol",), "lazy": True,
     "noun": "count of LCSC codes drawn on this symbol",
     "what": "distinct LCSC codes among the components using this base symbol"},
    {"name": "$footprint_lcsc_parts", "kinds": ("footprint",), "lazy": True,
     "noun": "count of LCSC codes on this land",
     "what": "distinct LCSC codes among the components using this footprint"},
    {"name": "$symbol_distinct_mpns", "kinds": ("symbol",), "lazy": True,
     "noun": "count of distinct part numbers drawn on this symbol",
     "what": "how many different manufacturer part numbers use this base symbol"},
    {"name": "$symbol_nc_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of NC pins",
     "what": "pins typed no_connect or free, or named NC — what the NC-pad rule is about"},
    {"name": "$symbol_fp_filters", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "ki_fp_filters", "what": "the symbol's ki_fp_filters glob list"},
    {"name": "$symbol_pin_number_len", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "longest pin number, in characters",
     "what": "how many characters the longest pin NUMBER has"},
    {"name": "$symbol_stub_length", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "pin stub length in mm",
     "what": "the one stub length the drawing uses — absent when it mixes them"},
    {"name": "$symbol_overbar_line_pins", "kinds": ("component", "symbol"), "lazy": True,
     "noun": "count of active-low pins drawn without a bubble",
     "what": "pins whose name carries an overbar but whose graphic style is not inverted"},
    # ---------------------------------------------------------- footprint
    {"name": "$footprint_pad_count", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "numbered pad count",
     "what": "how many DISTINCT numbered pads — paste apertures and thermal vias excluded"},
    {"name": "$footprint_has_model3d", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "3D model reference",
     "claim": "A 3D model is referenced",
     "what": "true when a 3D model is referenced"},
    {"name": "$footprint_smd_pads", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "surface-mount pad count",
     "what": "how many pad nodes are surface mount"},
    {"name": "$footprint_th_pads", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "plated through-hole pad count",
     "what": "how many pad nodes are plated through-hole"},
    {"name": "$footprint_npth_pads", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "non-plated hole count",
     "what": "how many pad nodes are non-plated (mechanical) holes"},
    #: The zero-annulus defect `conventions-footprints` §6 describes: an
    #: unnamed plated hole whose copper equals its drill, which KiCad DRC
    #: raises a minimum-annular-width violation on. Counted rather than
    #: asserted here so a check can say `at_most 0` and a part can carry an
    #: exception for a hole that is genuinely plated and netted.
    {"name": "$footprint_zero_annulus_pads", "kinds": ("component", "footprint"),
     "lazy": True,
     "noun": "count of plated holes whose copper is no wider than the drill",
     "what": "plated holes whose copper equals their drill — each is a DRC violation"},
    #: `conventions-footprints` §5. The fine-pitch exception is real, so this
    #: is a COUNT and the rule lives in the check's threshold, not here.
    {"name": "$footprint_off_grid_pads", "kinds": ("component", "footprint"),
     "lazy": True,
     "noun": "count of pads off the 0.1 mm grid",
     "what": "pad centres off the 0.1 mm grid"},
    #: `conventions-footprints` §4. The internal name must equal the library
    #: name and must never keep an importer's namespace — `easyeda2kicad:NAME`
    #: is the defect, and the colon is what makes KiCad report a library id
    #: that does not exist.
    {"name": "$footprint_heatsink_pads", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "count of heatsink pads",
     "what": "pads flagged pad_prop_heatsink — an exposed pad or a thermal via"},
    {"name": "$footprint_rotation_offset", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "FT Rotation Offset",
     "what": "the JLC pick-and-place rotation offset recorded on this footprint"},
    {"name": "$footprint_internal_name", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "name inside the .kicad_mod",
     "what": "the name in (footprint \"...\"), which must equal the library name"},
    #: The §10 import checklist asked for this by hand on every import.
    {"name": "$footprint_pad_name_decimals", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "count of pad numbers written as a decimal",
     "what": "pad numbers stored as \"1.0\" where KiCad wants \"1\""},
    #: `conventions-footprints` §9. The Fabrication Toolkit takes the FIRST
    #: rotation field it finds, so a fallback spelling beside the primary one
    #: is a silent disagreement about a fab number.
    {"name": "$footprint_rotation_alt_fields", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "count of deprecated rotation-offset field names",
     "what": "properties named \"Rotation Offset\" or \"RotOffset\" instead of "
             "\"FT Rotation Offset\""},
    #: `conventions-footprints` §4, decided 2026-08-27: 0.25 mm from the
    #: outermost pad or body feature, snapped outward to the 0.1 mm grid. The
    #: check asserts a FLOOR, because a larger courtyard is legitimate when the
    #: part needs one.
    {"name": "$footprint_courtyard_clearance", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "courtyard clearance in mm",
     "what": "narrowest gap between the courtyard and the outermost pad or "
             "F.Fab feature, in mm"},
    #: §4 requires a `Cmts.User` pin-1 circle on every footprint that has a
    #: pad 1, within 2 mm of it so a sweep can find it. The 2 mm is inside the
    #: fact because the rule fixes it.
    {"name": "$footprint_silk_over_pads", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "count of silk lines crossing pad copper",
     "what": "F.SilkS straight edges that cross a pad's copper. Arcs and "
             "circles are not tested, so 0 means no STRAIGHT silk crosses"},
    {"name": "$footprint_thermal_vias", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "count of thermal vias",
     "what": "through-hole pads carrying an smd pad's number — what a thermal "
             "via IS in a footprint, read from the geometry rather than from a "
             "pad_prop_heatsink somebody may have left off"},
    {"name": "$footprint_vias_outside_ep", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "count of thermal vias outside their own pad",
     "what": "through-hole pads carrying an smd pad's number whose copper is "
             "not wholly inside that pad"},
    {"name": "$footprint_pin1_marks", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "count of Cmts.User pin-1 marks",
     "what": "Cmts.User circles within 2 mm of pad 1 — absent when there is no pad 1"},
    #: The human package name (`0402`, `SOT-23-6`) the generator injects
    #: wherever a description references {Footprint_Name}. Unversioned, so it
    #: lives on the footprint row rather than in the drawing.
    {"name": "$footprint_package_name", "kinds": ("component", "footprint"),
     "lazy": True, "noun": "package name",
     "what": "the short human package name shown wherever {Footprint_Name} is used"},
    {"name": "$footprint_min_pitch", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "lead pitch in mm",
     "what": "nearest centre-to-centre distance between two numbered pads, in mm"},
    #: The grid exception is available BELOW 1 mm and not above — the threshold
    #: `conventions-footprints` §5 states outright, with a decided case on each
    #: side. Kept as its own fact so the rule that reads it lives in the
    #: checklist, where it can be seen, rather than inside a Python count.
    {"name": "$footprint_fine_pitch", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "fine-pitch flag",
     "claim": "The lead pitch is below 1 mm",
     "what": "true when the lead pitch is below 1 mm, where the 0.1 mm grid exception applies"},
    #: `conventions-footprints` §2. A mirrored quad passes every other check —
    #: outline, pitch, courtyard and pad count all still agree — and only the
    #: numbers are wrong, which is why one shipped. Reported as a CORNER rather
    #: than a boolean so the rule that reads it stays in the checklist.
    {"name": "$footprint_models_offpath", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "count of 3D references outside the library path",
     "what": "model paths that do not start ${SEVENSIGMA_DIR}/3DModels/"},
    {"name": "$footprint_smd_rratio_off", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "count of roundrect pads off the house corner ratio",
     "what": "roundrect SMD pads whose rratio is not 0.25"},
    {"name": "$footprint_pin1_corner", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "corner pad 1 sits in",
     "what": "where pad 1 sits: top-left, top-right, bottom-left, bottom-right, "
             "or left/right/top/bottom for a pad on an axis, or center"},
    {"name": "$footprint_numbering", "kinds": ("component", "footprint"), "lazy": True,
     "noun": "pad numbering direction",
     "what": "ccw or cw for a package with pads on four edges, empty otherwise"},
    # --------------------------------------------------------- cross-fact
    #: `assert` is deliberately one fact against one literal, so a comparison
    #: between two facts belongs HERE, in Python, and never in a boolean
    #: assertion language. The fact vocabulary is the extension point; the
    #: assertion vocabulary stays closed.
    {"name": "$longest_property", "kinds": ("component",), "lazy": True,
     "noun": "longest property value, in characters",
     "what": "how long the longest stored property value is"},
    {"name": "$electrical_props", "kinds": ("component",), "lazy": True,
     "noun": "count of the part's own electrical properties",
     "what": "properties that are not identity, sourcing, KiCad fields or simulation"},
    {"name": "$pins_match_pads", "kinds": ("component",), "lazy": True,
     "noun": "pin set against the pad set",
     "claim": "The symbol's pin numbers and the footprint's pad numbers are the same set",
     "what": "true when the symbol's pin numbers and the footprint's pad numbers are the same set"},
    #: Split in two on purpose. A pin with no pad is a signal with nowhere to
    #: go; a pad with no pin is usually an exposed thermal pad or an NC lead.
    #: One mismatch number would make the second drown the first.
    {"name": "$pins_without_pads", "kinds": ("component",), "lazy": True,
     "noun": "count of symbol pins the footprint has no pad for",
     "what": "symbol pins whose number has no pad — a signal with nowhere to land"},
    {"name": "$pads_without_pins", "kinds": ("component",), "lazy": True,
     "noun": "count of pads the symbol does not draw",
     "what": "numbered pads the symbol does not draw — often an exposed pad or an "
             "NC lead. Pads named MP or SH are excluded: that name IS the "
             "statement that no pin lands there"},
    {"name": "$datasheet_web_pages", "kinds": ("component",), "lazy": True,
     "noun": "count of archived datasheets that are a web page",
     "what": "archived documents whose content type is HTML or text rather than a document"},
    {"name": "$datasheet_archived", "kinds": ("component",), "lazy": True,
     "noun": "archived datasheet",
     "claim": "A datasheet document is archived for this version",
     "what": "true when this version has an archived datasheet document"},
    {"name": "$value_is_mpn", "kinds": ("component",), "lazy": True,
     "noun": "Value against the manufacturer part number",
     "claim": "Value is Manufacturer Part Number 1, verbatim",
     "what": "true when Value is Manufacturer Part Number 1 verbatim"},
    {"name": "$value_is_name", "kinds": ("component",), "lazy": True,
     "noun": "Value against the component name",
     "claim": "Value is the component's own name",
     "what": "true when Value is the component's own name"},
    {"name": "$powered_die", "kinds": ("component",), "lazy": True,
     "noun": "powered die",
     "claim": "The part contains a die that draws current from a supply rail",
     "what": "false for a transistor, diode, passive, plain LED, crystal, relay "
             "or switch — see NO_QUIESCENT_CURRENT for the full list"},
    {"name": "$value_placeholder", "kinds": ("component",), "lazy": True,
     "noun": "Value placeholder flag",
     "claim": "Value is empty or a placeholder",
     "what": "true when Value is empty, ~, N/A, -, an unresolved {Template} or a copy of ki_description"},
)

FACTS_BY_NAME = {f["name"]: f for f in FACTS}

#: Facts available without parsing anything. Kept as a name because the save
#: path and the editor both ask "may a predicate read this cheaply".
WHEN_FACTS = tuple(f["name"] for f in FACTS if not f.get("lazy"))

#: Facts DERIVED from a drawing, computed on demand.
DERIVED_FACTS = tuple(f["name"] for f in FACTS if f.get("lazy"))

#: Everything a `when` predicate or an `assert` may name, besides a property.
ALL_FACTS = tuple(f["name"] for f in FACTS)


def facts_for_kind(kind: str) -> list[dict]:
    """The vocabulary one subject kind actually carries, for the editor."""
    return [dict(f) for f in FACTS if kind in f["kinds"]]


class _LazyFacts(dict):
    """The facts of one subject, with the expensive ones computed on demand.

    `get` is overridden as well as `__missing__` because every reader uses
    `.get()` — and `dict.get` does NOT call `__missing__`, which would have made
    every derived fact silently absent. An absent fact never matches a
    predicate, so the bug would have read as "this check applies to nothing"
    rather than as a failure.
    """

    def __init__(self, base: dict, providers: dict):
        super().__init__(base)
        self._providers = providers

    def _compute(self, key):
        fn = self._providers.pop(key, None)
        if fn is None:
            return None
        try:
            value = fn()
        except Exception:  # noqa: BLE001 — a fact that cannot be read is absent
            value = None
        self[key] = value
        return value

    def get(self, key, default=None):  # type: ignore[override]
        if key in self:
            return dict.get(self, key, default)
        value = self._compute(key)
        return default if value is None else value

    def __missing__(self, key):
        value = self._compute(key)
        if value is None:
            raise KeyError(key)
        return value


#: The house coordinates for the two triangle families, quoted from the hints
#: on `sym.triangle_pins`, `sym.gate_body` and `sym.input_marks`. They are the
#: reason six glyph checks could become one measurement: the drawing is not a
#: matter of taste, it is a table of numbers.
#:
#: The rail x on the amplifier is NOT free — a vertical pin on a sloped edge
#: has to satisfy the 2.54 grid AND land on the edge, which on a 15.24 mm body
#: allows only -7.62, -2.54, +2.54, +7.62. That is also why 12.70 mm is not a
#: usable body size: it allows none.
AMPLIFIER_PINS = frozenset({
    (-10.16, 2.54),   # inverting input
    (-10.16, -2.54),  # non-inverting input
    (10.16, 0.0),     # output
    (-2.54, 7.62),    # positive rail
    (-2.54, -7.62),   # negative rail
    (2.54, 5.08),     # a spare pin (NC, SHDN)
    (2.54, -5.08),
})
AMPLIFIER_MARKS = frozenset({
    (-6.35, 2.54),    # the inverting input's -
    (-6.35, -2.54),   # the non-inverting input's +
    (-1.27, 6.35),    # the positive rail's +
    (-1.27, -6.35),   # the negative rail's -
})
GATE_PINS = frozenset({
    (-7.62, 0.0),     # input
    (7.62, 0.0),      # output
    (0.0, 5.08),      # positive rail
    (0.0, -5.08),     # negative rail
    # The angled-leader slot: a spare pin (an output enable, an NC) that has
    # nowhere on-grid to enter, so it enters off the sloped edge with a short
    # leader drawn to it — `sym.angled_leader`. 74LVC1G125 puts ~{OE} here and
    # 74LVC1G17 puts NC here, and both were reported as defects until this was
    # added (dry run 2026-09-14).
    (5.08, 5.08),
    (5.08, -5.08),
})
#: A gate's rails and its angled-leader slot. Anything else on a gate is a
#: signal pin, and the count of those is what says whether the 10.16 mm
#: one-input geometry applies at all.
GATE_NON_SIGNAL = frozenset({(0.0, 5.08), (0.0, -5.08), (5.08, 5.08), (5.08, -5.08)})
GATE_MARKS = frozenset({(1.27, 3.81), (1.27, -3.81)})


def subject_facts(db: Session, kind: str, parent, version_id: int | None) -> dict:
    """What a `when` predicate is matched against, as strings.

    Only a COMPONENT has properties and a category, so a symbol or a footprint
    gets the structural facts alone — a predicate over `comp_type` on a
    footprint checklist matches nothing, which is the honest outcome.
    """
    facts: dict[str, str] = {"$kind": kind}
    if kind != "component":
        facts["$name"] = getattr(parent, "name", "") or ""
        version = db.get(M.SymbolVersion if kind == "symbol" else M.FootprintVersion,
                         version_id) if version_id else None
        # An EMPTY material_sha means "could not tell" and must never compare
        # equal to another empty one — the rule `services/signoff.py` states for
        # the carry, and an exception pinned to one would be worse: it would
        # stay live across exactly the changes nobody could fingerprint.
        if version is not None and version.material_sha:
            facts["$material_sha"] = version.material_sha
        if version is None:
            return facts
        # A symbol and a footprint carry their own drawing facts. Until
        # 2026-09-14 they carried NONE — `$kind`, `$name` and a fingerprint —
        # so a footprint checklist could not say "this rule is about quad
        # packages" and every geometry rule had to be prose in a skill for an
        # agent to read.
        def src(v=version) -> str:
            return v.source_text or ""

        providers = (_symbol_providers(src, lambda p=parent: p.name) if kind == "symbol"
                     else _footprint_providers(src))
        if kind == "symbol":
            providers["$symbol_sim_link"] = lambda v=version: (
                "true" if db.query(M.SymbolSimLink).filter_by(
                    symbol_id=v.symbol_id).first() else "false")

            def _pins_changed(v=version):
                """Pin numbers added, removed, or moved between units, against
                the PREVIOUS version of this drawing.

                Lives here rather than in `_symbol_providers` because it is the
                one symbol fact that needs more than the source text: the
                predecessor has to be fetched. It is also the one fact that is
                about a CHANGE rather than a state, which is why it has no
                meaning on the component page — a component's drawing facts
                describe the drawing it points at, not its history.

                None on a first version. An absent fact answers `na`, which is
                the honest reading: nothing has been compared, as against
                "nothing changed".
                """
                from . import material

                prev = (db.query(M.SymbolVersion)
                        .filter(M.SymbolVersion.symbol_id == v.symbol_id,
                                M.SymbolVersion.version_no < v.version_no)
                        .order_by(M.SymbolVersion.version_no.desc()).first())
                if prev is None:
                    return None

                def by_number(src: str) -> dict[str, frozenset]:
                    # A number may appear more than once: stacked power pins
                    # share one. Comparing the SET of units each number sits in
                    # catches a move without calling a duplicate a change.
                    out: dict[str, set] = {}
                    for pin in material.symbol_material(src or "")["pins"]:
                        num = str(pin.get("number") or "").strip()
                        if not num:
                            continue
                        unit = pin.get("unit") or [0, 0]
                        out.setdefault(num, set()).add(unit[0])
                    return {k: frozenset(s) for k, s in out.items()}

                try:
                    now, was = by_number(v.source_text), by_number(prev.source_text)
                except Exception:  # noqa: BLE001 — an unparseable drawing is not a finding
                    return None
                moved = sum(1 for n in now.keys() & was.keys() if now[n] != was[n])
                return str(len(now.keys() ^ was.keys()) + moved)

            providers["$symbol_pins_changed"] = _pins_changed

            def _distinct_mpns(name=parent.name):
                """Different part numbers drawn on this base symbol.

                A component names its base symbol by NAME, not by id, so this
                counts the distinct `Manufacturer Part Number 1` across every
                component whose current version is drawn on it. A part with no
                MPN counts once under its own name, so a house part is not
                invisible here.
                """
                seen = set()
                q = (db.query(M.ComponentVersion, M.Component)
                     .join(M.Component,
                           M.Component.current_version_id == M.ComponentVersion.id)
                     .filter(M.ComponentVersion.base_component == name))
                for cv, comp in q.all():
                    mpn = next((p.value for p in cv.properties
                                if p.key == "Manufacturer Part Number 1"
                                and not p.is_null and p.value), None)
                    seen.add(mpn or f"#{comp.name}")
                return str(len(seen))

            providers["$symbol_distinct_mpns"] = _distinct_mpns

            def _family_drawing_off(v=version, types=None):
                """How far a triangle-family drawing is from the house
                coordinates, counted in wrong elements.

                The amplifier and gate families are drawn to FIXED numbers —
                the hints on `sym.triangle_body`, `sym.triangle_pins`,
                `sym.gate_body` and `sym.input_marks` all quote them to the
                0.01 mm. Six separate judgment checks were asking a person to
                compare coordinates by eye, and between them they had been
                answered ZERO times in the library's history (audit
                2026-09-14). A coordinate comparison is not a judgement.

                Absent unless the symbol is drawn as a triangle — no rectangle
                body, and every component on it an OPAMP/COMPARATOR (the
                15.24 mm family) or LOGIC (10.16 mm). `sym.drawing_family`
                still owns the question of whether a part BELONGS in the
                family; this only measures a drawing that already claims to.

                What it cannot see stays on judgment items: which rail is
                actually the negative one, which input the datasheet calls
                inverting, and whether a part is a comparator or an amplifier.
                Those need the datasheet, not the file.
                """
                src = v.source_text or ""
                if re.search(r"\(rectangle\s", src):
                    return None
                kinds = {t for t in (types or "").split(",") if t}
                if kinds and kinds <= {"OPAMP", "COMPARATOR"}:
                    body, pins_ok, marks = 7.62, AMPLIFIER_PINS, AMPLIFIER_MARKS
                elif kinds == {"LOGIC"}:
                    body, pins_ok, marks = 5.08, GATE_PINS, GATE_MARKS
                else:
                    return None

                try:
                    from . import material
                    all_pins = material.symbol_material(src)["pins"]
                except Exception:  # noqa: BLE001 — an unparseable drawing is not a finding
                    return None

                def _xy(pin):
                    at = pin.get("at") or []
                    return ((round(float(at[0]), 2), round(float(at[1]), 2))
                            if len(at) >= 2 else None)

                # ONLY THE ONE-INPUT GATE HAS DOCUMENTED COORDINATES. The
                # hints give the 10.16 mm triangle for an inverter or buffer;
                # a multi-input gate is drawn as the IEC body with an "&" and
                # the house has never written its numbers down. SN74HC21, a
                # dual 4-input AND, was reported 15 elements off against the
                # one-input table (dry run 2026-09-14) — which would have been
                # this check inventing a rule rather than measuring one. Absent
                # there; `sym.drawing_family` owns the undocumented case.
                if kinds == {"LOGIC"}:
                    per_unit: dict = {}
                    for pin in all_pins:
                        pos = _xy(pin)
                        if pos is None or pos in GATE_NON_SIGNAL:
                            continue
                        per_unit.setdefault((pin.get("unit") or [0, 0])[0], set()).add(pos)
                    if any(len(s) > 2 for s in per_unit.values()):
                        return None

                off = 0
                # 1. the body. Vertices as a SET: KiCad may write the polyline
                #    in either direction and may repeat the first point.
                want = {(-body, body), (body, 0.0), (-body, -body)}
                drawn = []
                for poly in re.finditer(r"\(polyline\s*\(pts((?:\s*\(xy\s+-?[\d.]+\s+-?[\d.]+\s*\))+)",
                                        re.sub(r"\s+", " ", src)):
                    pts = {(round(float(x), 2), round(float(y), 2)) for x, y in
                           re.findall(r"\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\)", poly.group(1))}
                    drawn.append(pts)
                if not any(want <= pts for pts in drawn):
                    off += 1

                # 2. the pins. Every family position is allowed in every unit;
                #    a pin anywhere else is one element off.
                for pin in all_pins:
                    pos = _xy(pin)
                    if pos is not None and pos not in pins_ok:
                        off += 1

                # 3. the polarity marks — graphic text at the family
                #    positions. Compared as NUMBERS: KiCad writes 0 for one
                #    symbol and 0.0 for the next, and a regex over the spelling
                #    would report a missing mark that is right there.
                flat = re.sub(r"\s+", " ", src)
                drawn_text = {(round(float(x), 2), round(float(y), 2)) for x, y in
                              re.findall(r'\(text "[^"]*" \(at (-?[\d.]+) (-?[\d.]+)', flat)}
                off += sum(1 for pos in marks if pos not in drawn_text)
                return str(off)

            providers["$symbol_family_drawing_off"] = lambda: _family_drawing_off(
                types=_sym_comp_types())

            def _sym_lcsc(name=parent.name):
                """Distinct LCSC codes among the components drawn on this symbol.

                `sym.easyeda_diff` pulls the EasyEDA symbol for an exact LCSC
                part. A base symbol no purchased part uses has nothing to diff.
                """
                seen = set()
                q = (db.query(M.ComponentVersion)
                     .join(M.Component,
                           M.Component.current_version_id == M.ComponentVersion.id)
                     .filter(M.ComponentVersion.base_component == name))
                for cv in q.all():
                    code = next((pr.value for pr in cv.properties
                                 if pr.key == "LCSC Part" and not pr.is_null and pr.value),
                                None)
                    if code:
                        seen.add(code)
                return str(len(seen))

            providers["$symbol_lcsc_parts"] = _sym_lcsc

            def _sym_comp_types(name=parent.name):
                """The comp_type values of the components drawn on this symbol.

                THE BRIDGE between the two axes. `comp_type` lives on a
                COMPONENT, and a drawing rule is about a SYMBOL — so without
                this, a rule like "an op-amp puts its inverting input on top"
                could only be scoped by pin count and pin-name visibility,
                which is how an ESD array ended up being asked about its rail
                markers. Sorted and comma-joined, so a `when` matches it with
                an ordinary regular expression.
                """
                seen = set()
                q = (db.query(M.ComponentVersion)
                     .join(M.Component,
                           M.Component.current_version_id == M.ComponentVersion.id)
                     .filter(M.ComponentVersion.base_component == name))
                for cv in q.all():
                    t = next((pr.value for pr in cv.properties
                              if pr.key == "comp_type" and not pr.is_null and pr.value), None)
                    if t:
                        seen.add(t)
                return ",".join(sorted(seen)) or None

            providers["$symbol_comp_types"] = _sym_comp_types

            def _sym_family_choice(types=_sym_comp_types):
                """Is the drawing family a choice on this symbol?

                TRUE when ANY component on it has a choice, which is the safe
                direction on a shared drawing: the question stays asked. Absent
                when no component carries a `comp_type` — a power flag or a
                bare graphic has no family question either.
                """
                got = types()
                if not got:
                    return None
                return "false" if all(t in FIXED_PICTOGRAM
                                      for t in got.split(",")) else "true"

            providers["$symbol_family_choice"] = _sym_family_choice
        else:
            providers["$footprint_has_model3d"] = lambda v=version: (
                "true" if (v.models or []) else "false")
            # Unversioned, so it comes off the footprint ROW rather than the
            # drawing — the same value the mirror injects for
            # {Footprint_Name}. Set as a plain fact, not a provider, because
            # reading one column is not worth a lazy call.
            if getattr(parent, "display_name", ""):
                facts["$footprint_package_name"] = parent.display_name
            providers["$footprint_models_offpath"] = lambda v=version: _models_offpath(v)

            def _fp_lcsc(name=parent.name):
                """Distinct LCSC codes among the components drawn on this land.

                `fp.jlc_land` asks whether the copper was diffed against the
                JLCPCB land for the same LCSC part. A footprint carries no LCSC
                code of its own — its COMPONENTS do — and a land no purchased
                part sits on has no JLC drawing to diff against at all.
                """
                ref = f"7Sigma:{name}"
                seen = set()
                q = (db.query(M.ComponentVersion)
                     .join(M.Component,
                           M.Component.current_version_id == M.ComponentVersion.id))
                for cv in q.all():
                    props = {pr.key: pr.value for pr in cv.properties
                             if not pr.is_null and pr.value}
                    if props.get("Footprint") != ref:
                        continue
                    code = props.get("LCSC Part")
                    if code:
                        seen.add(code)
                return str(len(seen))

            providers["$footprint_lcsc_parts"] = _fp_lcsc
        return _LazyFacts(facts, providers)
    cv = db.get(M.ComponentVersion, version_id) if version_id else None
    if cv is None:
        return facts
    from ..routers.util import category_path
    from .mirror import top_level_of

    for prop in cv.properties:
        if not prop.is_null and prop.value is not None:
            facts[prop.key] = str(prop.value)
    facts["$name"] = parent.name or ""
    facts["$base_symbol"] = cv.base_component or ""
    facts["$footprint"] = facts.get("Footprint", "")
    facts["$lifecycle"] = getattr(parent, "lifecycle_state", "") or ""
    facts["$in_library"] = "true" if parent.in_library else "false"
    facts["$purchasable"] = "true" if parent.purchasable else "false"
    if cv.category is not None:
        facts["$category"] = top_level_of(cv.category).name
        facts["$category_path"] = category_path(cv.category)
    # The two drawings this component pins, as one value. A component has no
    # fingerprint of its own; what reaches the board is its symbol and its
    # footprint, so a drawing-scoped exception on a component pins both.
    shas = [getattr(cv.symbol_version, "material_sha", None),
            getattr(cv.footprint_version, "material_sha", None)]
    if all(shas):
        facts["$material_sha"] = "+".join(shas)
    facts["$property_sha"] = _property_sha(cv)
    return _LazyFacts(facts, _derived_providers(db, cv))


def _property_sha(cv: M.ComponentVersion) -> str:
    """A digest of the component's own data — the same triple
    `signoff.data_carries` compares, so an exception pinned to it dies on
    exactly the edits that would have stripped a verification."""
    import hashlib

    payload = ";".join(
        f"{p.key}={'' if p.is_null else (p.value or '')}"
        for p in sorted(cv.properties, key=lambda x: x.key))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _derived_providers(db: Session, cv: M.ComponentVersion) -> dict:
    """How to compute each derived fact of a COMPONENT, if anything asks.

    Every value is a STRING, so one predicate language covers them all; the
    assertion evaluator coerces where it needs a number.

    A component's drawing facts are the SAME functions a symbol or footprint
    subject uses — one definition, so `$footprint_pad_count` cannot mean one
    thing on the footprint page and another on the component page.
    """
    def symbol_src() -> str:
        return (cv.symbol_version.source_text or "") if cv.symbol_version else ""

    def footprint_src() -> str:
        return (cv.footprint_version.source_text or "") if cv.footprint_version else ""

    out = {**_symbol_providers(symbol_src, lambda: cv.base_component or None),
           **_footprint_providers(footprint_src)}

    def package_name():
        """The footprint's own unversioned package name, seen from a component.

        Lazy here and eager on the footprint subject, because a component only
        reaches the row through two relationships.
        """
        fv = cv.footprint_version
        fp = getattr(fv, "footprint", None) if fv is not None else None
        return getattr(fp, "display_name", "") or None

    out["$footprint_package_name"] = package_name

    def datasheet_web_pages():
        """Archived datasheets that are a WEB PAGE rather than a document.

        The defect `custom:datasheet-archived-as-html` recorded under three
        different spellings: a stored URL that answered with an HTML page, so
        the archive held a page of navigation rather than the datasheet. All
        416 archived documents are PDFs today and 3 more are STEP or DXF
        drawings, which are legitimate supporting documents - so this is a
        guard on the next fetch, and it replaces a judgment question that was
        being asked of 413 parts and duplicated `cmp.datasheet`.
        """
        n = 0
        for link in db.query(M.ComponentVersionDatasheet).filter_by(
                component_version_id=cv.id).all():
            d = db.get(M.Datasheet, link.datasheet_id)
            if d is None or d.archived:
                continue
            dv = next((v for v in d.versions if v.id == d.current_version_id), None)
            if dv is None:
                continue
            doc = db.get(M.Document, dv.document_id)
            ct = (getattr(doc, "content_type", "") or "").lower()
            if "html" in ct or "xml" in ct or ct.startswith("text/"):
                n += 1
        return str(n)

    def datasheet_archived():
        """Whether this version has an archived datasheet document.

        What the datasheet judgment checks are about. Asking a part with no
        archive whether its archive is a real document is asking about a thing
        that is not there, and `cmp.datasheet_text` already reports the absence.
        """
        return "true" if db.query(M.ComponentVersionDatasheet).filter_by(
            component_version_id=cv.id).first() else "false"

    out["$datasheet_archived"] = datasheet_archived
    out["$datasheet_web_pages"] = datasheet_web_pages

    def sim_link():
        sv = cv.symbol_version
        if sv is None:
            return None
        return "true" if db.query(M.SymbolSimLink).filter_by(
            symbol_id=sv.symbol_id).first() else "false"

    def has_model():
        fv = cv.footprint_version
        return None if fv is None else ("true" if (fv.models or []) else "false")

    out["$symbol_sim_link"] = sim_link
    out["$footprint_has_model3d"] = has_model
    out["$footprint_models_offpath"] = lambda: _models_offpath(cv.footprint_version)

    # ---------------------------------------------------------- cross-fact
    # A comparison between two facts, in Python. `assert` is deliberately one
    # fact against one literal: the moment an assertion can name two facts it
    # has become a rules language, and the whole point of the declarative form
    # is that it is configuration a person can read.
    from . import material

    def props() -> dict:
        return {p.key: ("" if p.is_null else str(p.value or ""))
                for p in cv.properties}

    def _number_sets():
        """The symbol's pin numbers and the footprint's pad numbers, as SETS.

        Sets, never counts. Stacked pins share one number, a thermal via
        repeats the exposed pad's number, and a mechanical hole has none at
        all — so counting nodes answers a different question and answers it
        wrongly on most real parts.
        """
        if cv.symbol_version is None or cv.footprint_version is None:
            return None, None
        try:
            pin_nums = {str(p.get("number") or "").strip()
                        for p in material.symbol_material(symbol_src())["pins"]}
            pad_nums = {str(p.get("number") or "").strip()
                        for p in material.footprint_material(footprint_src())["pads"]}
        except Exception:  # noqa: BLE001 — an unparseable drawing answers nothing
            return None, None
        pin_nums.discard("")
        pad_nums.discard("")
        pad_nums -= NON_ELECTRICAL_PADS
        if not pin_nums or not pad_nums:
            return None, None
        return pin_nums, pad_nums

    #: Keys every component carries as housekeeping — identity, sourcing, the
    #: KiCad fields and the simulation block. What is left is the part's own
    #: electrical data, which is what `cmp.electrical` is about.
    #: Properties that are NOT the part's own electrical data. `Reference` and
    #: `LCSC Part Class` were missing until 2026-09-14, and each one alone made
    #: `$electrical_props` report 1 for a part that has no electrical data at
    #: all — so `cmp.electrical` kept asking five Hammond enclosures, a logo and
    #: a mounting hole what their electrical values were, and each of them
    #: carried a hand-written exception answering "none, and none apply".
    HOUSEKEEPING = {"Reference", "Value", "Footprint", "Datasheet",
                    "ki_description", "ki_keywords", "ki_fp_filters",
                    "comp_type", "LCSC Part"}
    #: `Sim.` is deliberately NOT here. A simulation parameter is a CLAIM ABOUT
    #: THE PART's electrical behaviour and can disagree with the datasheet like
    #: any other — measured 2026-09-14, two parts were flagged for exactly that
    #: (TS24CA's RON=50m against the datasheet's contact resistance,
    #: UCC27538DBVR's ROUTH=2.5 against its OUTH pull-up) and excluding `Sim.`
    #: put both out of the question's reach. `Sim.Device` and `Sim.Type` are
    #: wiring, not values, so they are named individually instead.
    HOUSEKEEPING_PREFIXES = ("Manufacturer", "Supplier", "LCSC")
    HOUSEKEEPING = HOUSEKEEPING | {"Sim.Device", "Sim.Type", "Sim.Pins", "Sim.Library"}

    def longest_property():
        """The longest property VALUE on this component, in characters.

        `conventions-library` and `add-component` both stated a 200-character
        limit and `_RULE_KEYS_UNUSED` records that the old rule block carried
        `max_property_length` and nothing consumed it. A description that runs
        past the limit is not a cosmetic problem: it is what a BOM line and a
        KiCad field render, and it is usually a supplier blurb pasted in whole
        rather than a template.
        """
        longest = 0
        for prop in cv.properties:
            if prop.is_null or not prop.value:
                continue
            longest = max(longest, len(str(prop.value)))
        return str(longest)

    def electrical_props():
        """How many properties are the part's OWN data rather than housekeeping.

        `cmp.electrical` asks whether the electrical values match the datasheet,
        and 109 components carry no such value at all — a mounting hole, a logo,
        a test-point pad. The question is not about them, and 45 of them carried
        a hand-written "no discrete electrical properties" answer saying so.
        A category that REQUIRES a property still has `cmp.required_props`, so
        nothing is hidden by this: the two compose.
        """
        n = 0
        for prop in cv.properties:
            if prop.is_null or prop.value in (None, ""):
                continue
            if prop.key in HOUSEKEEPING or prop.key.startswith(HOUSEKEEPING_PREFIXES):
                continue
            n += 1
        return str(n)

    def pins_match_pads():
        pin_nums, pad_nums = _number_sets()
        if pin_nums is None:
            return None
        return "true" if pin_nums == pad_nums else "false"

    def pins_without_pads():
        """Symbol pins with no pad to land on. Almost always a real defect —
        the signal has nowhere to go on the board."""
        pin_nums, pad_nums = _number_sets()
        return None if pin_nums is None else str(len(pin_nums - pad_nums))

    def pads_without_pins():
        """Pads the symbol does not draw. Usually legitimate — an exposed
        thermal pad, or a package NC lead the symbol leaves off — which is why
        it is counted SEPARATELY from the defect above rather than summed into
        one mismatch number. A pad named `MP` or `SH` is not counted at all;
        see `NON_ELECTRICAL_PADS`."""
        pin_nums, pad_nums = _number_sets()
        return None if pin_nums is None else str(len(pad_nums - pin_nums))

    def value_is_mpn():
        p = props()
        value, mpn = p.get("Value", ""), p.get("Manufacturer Part Number 1", "")
        if not value or not mpn:
            return None
        return "true" if value.strip() == mpn.strip() else "false"

    def value_is_name():
        value = props().get("Value", "")
        if not value:
            return None
        # Component names are sanitised for KiCad — spaces and commas become
        # underscores — so `MCV_1,5/_2-GF-3,5-LR` and its Value differ by
        # exactly that substitution and must still count as the same.
        name = (getattr(cv, "component", None).name if getattr(cv, "component", None)
                else "") or ""
        if not name:
            return None
        norm = re.compile(r"[ ,_]+")
        return "true" if norm.sub("_", value.strip()) == norm.sub("_", name.strip()) \
            else "false"

    #: Values that are present but say nothing. `conventions-library` §3 lists
    #: them, and every one has been seen in this library.
    junk = {"", "~", "n/a", "na", "-", "--", "?"}

    def powered_die():
        """Does this part contain a die that draws current from a rail?

        Absent when the part carries no `comp_type` at all — which makes the
        two rail checks skip it, and that is the right way round: an
        unclassified part is not evidence that it has a supply current.
        """
        t = props().get("comp_type", "").strip()
        if not t:
            return None
        return "false" if t in NO_QUIESCENT_CURRENT else "true"

    def value_placeholder():
        p = props()
        value = p.get("Value", "").strip()
        if value.lower() in junk:
            return "true"
        if re.search(r"\{[^}]+\}", value):
            return "true"  # an unresolved template reference
        if value and value == p.get("ki_description", "").strip():
            return "true"
        return "false"

    out["$longest_property"] = longest_property

    out["$electrical_props"] = electrical_props
    out["$pins_match_pads"] = pins_match_pads
    out["$pins_without_pads"] = pins_without_pads
    out["$pads_without_pins"] = pads_without_pins
    out["$powered_die"] = powered_die
    out["$value_is_mpn"] = value_is_mpn
    out["$value_is_name"] = value_is_name
    out["$value_placeholder"] = value_placeholder
    return out


# ------------------------------------------------------------------ drawings
# Facts read off a symbol or a footprint. Every one is computed from
# `source_text` through `services/material.py`, NOT from
# `FootprintVersion.parsed` — `parsed` is an older, narrower structure that
# carries no pad position and no drill, so a fact built on it silently reports
# nothing about geometry. (It also counts paste apertures as pads: a
# QFN-16-1EP parses as 26 "pads", which is what `$footprint_pad_count` used to
# report.)

#: Pad names that DECLARE the pad is not a net. KiCad's own libraries use both
#: — `MP` for a hold-down or board lock, `SH` for a shield can — and no symbol
#: pin may carry a name a number cannot be, so naming a pad this way is what
#: guarantees nothing lands on it.
#:
#: They are removed from the pad set before `$pads_without_pins` counts it,
#: because otherwise the check fires on its own fix: TS24CA's two frame tabs
#: were numbered 3 and 4, the owner renamed them MP on 2026-09-13 so no net
#: could reach them, and the next read reported a pad the symbol does not draw.
#: Measured 2026-09-14: 4 of the library's 13 findings were exactly this, and
#: the other 9 — an exposed pad, an NC lead, a second antenna terminal — are
#: real questions that stay.
NON_ELECTRICAL_PADS = frozenset({"MP", "SH"})


#: `comp_type` values whose schematic symbol is FIXED by convention, so there is
#: no drawing family to choose. A MOSFET, a diode, a resistor, a crystal, a
#: relay, a connector pin row and a mounting hole are each drawn one way, and
#: "is this the right family — triangle, gate or box?" has no answer for them.
#:
#: `sym.drawing_family` carried no `when` at all until 2026-09-14 and reached all
#: 207 symbols, so a MOSFET was asked which of the 15.24 mm triangle, the
#: 10.16 mm gate triangle and the box it belonged in (user report). Excluding
#: rather than including, for the same reason as `NO_QUIESCENT_CURRENT`: a new
#: IC type keeps the question, and being wrong the other way costs one trivial
#: "yes, a box".
FIXED_PICTOGRAM = frozenset({
    # discrete semiconductors and emitters
    "NMOS", "PMOS", "NPN", "DIODE", "ZENER", "TVS", "PHOTODIODE",
    "LED", "RGB_LED", "SEVEN_SEGMENT", "OPTOCOUPLER",
    # passives
    "MLCC", "ELECTROLYTIC", "RESISTOR", "INDUCTOR", "CHOKE", "FERRITE",
    "NTC", "VARISTOR", "POLYFUSE", "FUSE", "FUSEHOLDER", "TRANSFORMER",
    "CRYSTAL",
    # contacts
    "TACTILE_SWITCH", "DIP_SWITCH", "SIGNAL_RELAY", "POWER_RELAY",
    # connectors and pin rows — a box by definition, never a triangle
    "HEADER", "TERMINAL_BLOCK", "TERMINAL_BLOCK_PLUG", "RJ45", "RJ45_MAGJACK",
    "USB_RECEPTACLE", "FFC", "COAX", "PIGTAIL", "DIN_RAIL_CONNECTOR",
    "BOARD_TO_BOARD", "BOARD_EDGE", "SIM_SOCKET", "SOLDER_PIN", "BATTERY_HOLDER",
    # mechanical and non-electrical
    "MOUNTING_HOLE", "STANDOFF", "ENCLOSURE", "LIGHTPIPE", "LOGO", "TESTPOINT",
    "ANTENNA",
    # house simulation stand-ins
    "SWITCH_SIM", "RTD_SIM", "EV_LOAD_SIM",
})


#: `comp_type` values with NO powered die, so no quiescent current and no rail
#: to draw one from. Written as a list of what is EXCLUDED rather than of what
#: is included, and that direction is the whole point: a new IC type keeps the
#: check by default, where a positive list would let it escape silently. The
#: cost of being wrong the other way is one question that answers itself.
#:
#: Until 2026-09-14 the two rail checks were scoped by `$symbol_power_pins`
#: alone, which asks how a SYMBOL happens to type a pin rather than what the
#: part IS. It agreed with this list on all 442 components, but a TVS array
#: draws two rails (`TPD4E05U06DQAR`), so the day one gained a `Sim.Params` row
#: it would have been asked for its per-channel quiescent current.
NO_QUIESCENT_CURRENT = frozenset({
    # discrete semiconductors
    "NMOS", "PMOS", "NPN", "DIODE", "ZENER", "TVS", "PHOTODIODE",
    # passives
    "MLCC", "ELECTROLYTIC", "RESISTOR", "INDUCTOR", "CHOKE", "FERRITE",
    "NTC", "VARISTOR", "POLYFUSE", "FUSE", "TRANSFORMER", "CRYSTAL",
    # emitters and opto with no controller of their own. An ADDRESSABLE_LED is
    # NOT here: it carries a controller die and a real supply current.
    "LED", "RGB_LED", "SEVEN_SEGMENT", "OPTOCOUPLER",
    # contacts
    "TACTILE_SWITCH", "DIP_SWITCH", "SIGNAL_RELAY", "POWER_RELAY",
    # house simulation stand-ins — a resistive load, not a part
    "SWITCH_SIM", "RTD_SIM", "EV_LOAD_SIM",
})


#: Pad numbers that are not a pin: an unnamed mechanical hole, and the empty
#: number a paste-only aperture carries.
def _numbered(pads: list[dict]) -> list[dict]:
    return [p for p in pads if str(p.get("number") or "").strip()]


def _grid_off(value: float, grid: float = 0.1) -> bool:
    """Is this coordinate off the grid? Tolerant to one part in 10,000 — the
    parser rounds to six places and 1.2999999 is 1.3, not a defect."""
    return abs(round(value / grid) * grid - value) > 1e-4


def _corner_of(at: list | None, tol: float = 1e-4) -> str:
    """Which corner (or edge, or centre) a pad sits in.

    A two-pad chip has both pads ON the X axis, so "bottom-left" would be a
    lie invented by a `y < 0` test — it reports `left`. The same for a pad on
    the Y axis. Only a pad genuinely off both axes gets a corner.

    KiCad Y points DOWN, so negative y is the TOP of the drawing. Getting that
    backwards is the exact mistake `conventions-footprints` §2 is about.
    """
    if not at or len(at) < 2:
        return ""
    x, y = float(at[0]), float(at[1])
    across = "" if abs(x) < tol else ("left" if x < 0 else "right")
    down = "" if abs(y) < tol else ("top" if y < 0 else "bottom")
    if not across and not down:
        return "center"
    return f"{down}-{across}" if (across and down) else (down or across)


#: Every drawn coordinate pair a footprint graphic can carry. The same shapes
#: `validator._COORD_RE` reads, kept here so a fact never imports the validator
#: — the validator imports the facts.
_COORDS_RE = re.compile(r"\((?:start|end|mid|center|xy)\s+(-?[\d.]+)\s+(-?[\d.]+)\)")


def _block_at(content: str, start: int) -> str:
    """The balanced s-expression beginning at `start`."""
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return content[start:i + 1]
    return content[start:]


def _pad_box(pad: dict) -> tuple[float, float, float, float] | None:
    """A pad's copper as an axis-aligned box.

    Rotation is read, but only a quarter turn swaps the sides: KiCad writes the
    angle as the third number of `(at x y a)`, and every pad in this library is
    at 0, 90, 180 or 270. An arbitrary angle is treated as unrotated, which
    OVER-states nothing and under-states a little — the honest direction for a
    check that reports a defect.
    """
    at, size = pad.get("at"), pad.get("size")
    if not at or len(at) < 2 or not size or len(size) < 2:
        return None
    try:
        x, y = float(at[0]), float(at[1])
        w, h = float(size[0]), float(size[1])
        angle = float(at[2]) % 180 if len(at) > 2 else 0.0
    except (TypeError, ValueError):
        return None
    if abs(angle - 90) < 1e-6:
        w, h = h, w
    return x - w / 2, y - h / 2, x + w / 2, y + h / 2


def _seg_hits_box(x1: float, y1: float, x2: float, y2: float,
                  box: tuple[float, float, float, float]) -> bool:
    """Does a line segment touch an axis-aligned box? Liang-Barsky."""
    bx0, by0, bx1, by1 = box
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - bx0), (dx, bx1 - x1), (-dy, y1 - by0), (dy, by1 - y1)):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _footprint_providers(source_of) -> dict:
    """Facts of one footprint. `source_of` is called at most once per read."""
    from . import material

    cache: dict = {}

    def pads() -> list[dict]:
        if "pads" not in cache:
            try:
                cache["pads"] = material.footprint_material(source_of() or "")["pads"]
                cache["parsed"] = True
            except Exception:  # noqa: BLE001 — an unparseable drawing has no facts
                cache["pads"] = []
                cache["parsed"] = False
        return cache["pads"]

    def parsed() -> bool:
        """Did the drawing PARSE — as distinct from having no pads.

        Same distinction the symbol side makes, and for the same reason: an
        absent fact never matches a `when`, so folding "no pads" into "could
        not read this file" would let a scope silently stop asking about a
        broken footprint. Three footprints legitimately have no pads at all —
        an enclosure, a lightpipe and a silkscreen logo — and they now report
        "0" where a broken file reports nothing.
        """
        pads()
        return bool(cache.get("parsed"))

    def pad_count():
        if not parsed():
            return None
        return str(len({p["number"] for p in _numbered(pads())}))

    def of_type(*types):
        def fn():
            if not parsed():
                return None
            return str(sum(1 for p in pads() if p.get("type") in types))
        return fn

    def zero_annulus():
        """A plated hole whose copper does not exceed its drill. The rule of
        thumb `conventions-footprints` §6 states: `(size - drill) / 2 <= 0`."""
        if not parsed():
            return None
        n = 0
        for p in pads():
            if p.get("type") != "thru_hole":
                continue
            size, drill = p.get("size"), p.get("drill")
            if not size or not drill:
                continue
            d = drill[0] if isinstance(drill, list) else drill
            try:
                if min(float(size[0]), float(size[1])) - float(d) <= 0:
                    n += 1
            except (TypeError, ValueError, IndexError):
                continue
        return str(n)

    def off_grid():
        if not parsed():
            return None
        n = 0
        for p in _numbered(pads()):
            at = p.get("at")
            if not at or len(at) < 2:
                continue
            if _grid_off(float(at[0])) or _grid_off(float(at[1])):
                n += 1
        return str(n)

    def rratio_off():
        """Roundrect SMD pads whose corner ratio is not the house 0.25.

        `conventions-footprints` §4 listed this under "the validator enforces
        these" and nothing did — measured 2026-09-14, 36 of 212 footprints
        carry another value.
        """
        if not parsed():
            return None
        n = 0
        for pad in pads():
            if pad.get("type") != "smd" or pad.get("shape") != "roundrect":
                continue
            # A PASTE-ONLY aperture is a stencil opening, not copper. The house
            # corner ratio is a rule about pads; KiCad writes whatever radius it
            # computed for a paste sliver, and counting those made this check
            # fail on 19 footprints for their own exposed-pad paste pattern
            # (user report 2026-09-14).
            if not any(".Cu" in str(layer) for layer in pad.get("layers") or []):
                continue
            got = pad.get("roundrect_rratio")
            try:
                value = float(got[0][0]) if got else None
            except (TypeError, ValueError, IndexError):
                value = None
            if value is None or abs(value - 0.25) > 1e-6:
                n += 1
        return str(n)

    def pin1_corner():
        one = next((p for p in pads() if str(p.get("number")) == "1"), None)
        return _corner_of(one.get("at") if one else None) or None

    def numbering():
        """ccw or cw, for a package whose numbered pads sit on four edges.

        Empty for anything else: a two-row SOIC or a two-pad chip has no
        direction to be wrong about, and reporting one would invite a rule that
        fires on parts it was never written for.
        """
        pts = []
        for p in _numbered(pads()):
            at = p.get("at")
            if not at or len(at) < 2:
                continue
            try:
                pts.append((int(p["number"]), float(at[0]), float(at[1])))
            except (TypeError, ValueError):
                continue
        if len(pts) < 8:
            return None
        pts.sort()
        corners = {_corner_of([x, y]) for _, x, y in pts}
        if len({c for c in corners if c and c != "center"}) < 4:
            return None
        # The signed area of the polygon the pads trace in number order.
        #
        # KiCad Y points DOWN, which INVERTS the usual shoelace sign: the
        # correct counter-clockwise-on-screen trace — down the left edge, right
        # along the bottom, up the right, left along the top — sums NEGATIVE.
        # Verified against `QFN-16-1EP_3x3mm_P0.5mm`, whose pads run
        # 1..4 at x=-1.4625 with y increasing, then 5,6 at y=+1.4625 with x
        # increasing: that is the layout `conventions-footprints` §2 requires,
        # and it gives a negative area.
        area = 0.0
        for i, (_, x, y) in enumerate(pts):
            _, nx, ny = pts[(i + 1) % len(pts)]
            area += x * ny - nx * y
        return "ccw" if area < 0 else "cw"

    def one_per_number() -> list[dict]:
        """One pad per distinct number, with a position.

        Thermal vias repeat the exposed pad's number and sit a via-pitch apart,
        so counting every node would report a 0.6 mm package pitch on a 0.5 mm
        QFN with vias under it.
        """
        seen: dict[str, dict] = {}
        for pad in _numbered(pads()):
            at = pad.get("at")
            if at and len(at) >= 2:
                seen.setdefault(str(pad["number"]), pad)
        return list(seen.values())

    def min_pitch():
        """Nearest centre-to-centre distance between two numbered pads, in mm.

        A proxy for the lead pitch, and a good one: on every package the
        closest two pads are adjacent leads on one edge.
        """
        pts = [(float(p["at"][0]), float(p["at"][1])) for p in one_per_number()]
        if len(pts) < 2:
            return None
        best = None
        for i, (x1, y1) in enumerate(pts):
            for x2, y2 in pts[i + 1:]:
                d = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
                if d > 1e-6 and (best is None or d < best):
                    best = d
        return None if best is None else f"{round(best, 4):g}"

    def fine_pitch():
        """Is the pitch-axis grid exception available to this footprint?

        `conventions-footprints` §5 states the threshold outright: "below 1 mm
        it may apply, above it does not". Two decided cases sit on each side —
        a 0.5 mm QFN keeps its datasheet pitch, a 4.5 mm tact switch and the
        0.95 mm SOT-23 are snapped — so the boundary is the fact, and the rule
        that reads it stays in the checklist where it can be seen.
        """
        p = min_pitch()
        return None if p is None else ("true" if float(p) < 1.0 else "false")

    def internal_name():
        """The name INSIDE the file, which must equal the library name and must
        never keep an importer's namespace.

        `conventions-footprints` §4 stated this and nothing enforced it. An
        EasyEDA import arrives as `(footprint "easyeda2kicad:NAME")`, and the
        colon is the whole defect — KiCad then reports a library id that does
        not exist.
        """
        m = re.search(r'\(footprint\s+"([^"]*)"', source_of() or "")
        return m.group(1) if m else None

    def package_decimals():
        """Pad numbers written as a float — `"1.0"` where KiCad wants `"1"`.

        The §10 import checklist asks for it by hand on every import. It is one
        regular expression.
        """
        if not parsed():
            return None
        return str(sum(1 for p in pads()
                       if re.fullmatch(r"\d+\.0+", str(p.get("number") or ""))))

    #: The rotation-offset field names the Fabrication Toolkit falls back to.
    #: `conventions-footprints` §9 requires the primary name and forbids these,
    #: because the toolkit takes the first it finds and two spellings on one
    #: part is a silent disagreement.
    _ALT_ROTATION_FIELDS = ("Rotation Offset", "RotOffset")

    def rotation_alt_fields():
        src = source_of() or ""
        return str(sum(1 for name in _ALT_ROTATION_FIELDS
                       if re.search(r'\(property\s+"%s"' % re.escape(name), src)))

    def silk_over_pads():
        """F.SilkS segments that cross pad copper.

        Silk printed on a pad is not just untidy: the ink sits between the pad
        and the solder, and the assembler's optical inspection reads a
        contaminated joint. KiCad's own DRC has a silk-over-pad rule, which is
        the point — this catches it before the board file does.

        Straight edges only: `fp_line`, and the four sides of an `fp_rect`. An
        `fp_arc` or a rounded `fp_circle` is NOT tested, so a zero here means
        "no straight silk crosses copper", not "no silk does". Reported rather
        than hidden, because a partial mechanical check that says what it covers
        beats a judgment item nobody runs.
        """
        if not parsed():
            return None
        boxes = [b for b in (_pad_box(p) for p in pads()
                             if any(".Cu" in str(l) for l in p.get("layers") or []))
                 if b is not None]
        if not boxes:
            return "0"
        src = source_of() or ""
        hits = 0
        for m in re.finditer(r"\(fp_(line|rect)\b", src):
            block = _block_at(src, m.start())
            if "F.SilkS" not in block:
                continue
            pts = [(float(a), float(b)) for a, b in _COORDS_RE.findall(block)]
            if len(pts) < 2:
                continue
            if m.group(1) == "rect":
                (x0, y0), (x1, y1) = pts[0], pts[1]
                edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)),
                         ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]
            else:
                edges = [(pts[0], pts[1])]
            for (ax, ay), (bx, by) in edges:
                if any(_seg_hits_box(ax, ay, bx, by, box) for box in boxes):
                    hits += 1
                    break
        return str(hits)

    def _stitch_vias():
        """Through-hole pads that carry an smd pad's number, and that pad's box.

        This IS the definition of a thermal via in a footprint: the shared
        number is what puts the hole on the land's net.
        """
        ep: dict[str, list] = {}
        for pad in pads():
            number = str(pad.get("number") or "").strip()
            if not number or pad.get("type") != "smd":
                continue
            box = _pad_box(pad)
            if box is not None:
                ep.setdefault(number, []).append(box)
        vias = [p for p in pads()
                if p.get("type") == "thru_hole"
                and str(p.get("number") or "").strip() in ep]
        return vias, ep

    def thermal_vias():
        """How many thermal vias this footprint has.

        The SCOPE fact for `fp.thermal_vias`, and it deliberately does not read
        `pad_prop_heatsink`: scoping on that property missed the two footprints
        in the library whose vias sit outside their land, because whoever drew
        them left the property off as well (measured 2026-09-14). A check must
        not need the thing it is looking for to be declared correctly.
        """
        if not parsed():
            return None
        return str(len(_stitch_vias()[0]))

    def vias_outside_ep():
        """Thermal vias that are NOT inside the pad whose number they carry.

        A footprint has no via primitive, so a thermal via is a through-hole pad
        sharing the exposed pad's number — that number IS what puts it on the
        net. One drawn outside that copper is stitching the heat path to
        nothing, and nothing else in the file says so.
        """
        if not parsed():
            return None
        vias, ep_boxes = _stitch_vias()
        stray = 0
        for pad in vias:
            number = str(pad.get("number") or "").strip()
            box = _pad_box(pad)
            if box is None:
                continue
            # Inside means the via's whole copper sits within one land of the
            # same number. A via on the EP edge is a real defect: the ring needs
            # copper all round it.
            if not any(b[0] <= box[0] and b[1] <= box[1]
                       and box[2] <= b[2] and box[3] <= b[3]
                       for b in ep_boxes[number]):
                stray += 1
        return str(stray)

    def _graphic_box(layer_token: str):
        """The bounding box of every graphic on one layer, or None.

        A `fp_circle` is `(center …) (end …)` where the END is a point ON the
        circle, not a corner — reading both as bbox points collapses the box to
        a line through the centre and reports a NEGATIVE clearance on every
        round courtyard. Measured on `MountingHole_3.2mm_M3_Pad6mm`, whose
        3.5 mm radius courtyard read as 3.5 x 0.
        """
        src = source_of() or ""
        xs: list[float] = []
        ys: list[float] = []
        for m in re.finditer(r"\(fp_(line|rect|poly|circle|arc)\b", src):
            block = _block_at(src, m.start())
            if layer_token not in block:
                continue
            if m.group(1) == "circle":
                c = re.search(r"\(center\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
                e = re.search(r"\(end\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
                if c is None or e is None:
                    continue
                cx, cy = float(c.group(1)), float(c.group(2))
                r = ((float(e.group(1)) - cx) ** 2 + (float(e.group(2)) - cy) ** 2) ** 0.5
                xs += [cx - r, cx + r]
                ys += [cy - r, cy + r]
                continue
            for px, py in _COORDS_RE.findall(block):
                xs.append(float(px))
                ys.append(float(py))
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _extent():
        """The outermost PAD, as (x0, y0, x1, y1).

        Pads only, deliberately. The body is drawn on `F.Fab` and on a
        `Mechanical_7S` part it legitimately overhangs the courtyard — an
        enclosure's case outline is 21 mm outside the copper it clamps to.
        Folding that into one number would report every such part as a
        clearance defect and hide the real question, which is how close the
        courtyard sits to the COPPER other parts are placed against.
        """
        xs: list[float] = []
        ys: list[float] = []
        for pad in pads():
            at, size = pad.get("at"), pad.get("size")
            if not at or len(at) < 2 or not size or len(size) < 2:
                continue
            try:
                x, y = float(at[0]), float(at[1])
                w, h = float(size[0]), float(size[1])
                angle = float(at[2]) if len(at) > 2 else 0.0
            except (TypeError, ValueError):
                continue
            # A pad rotated a quarter turn swaps its own axes. Anything else is
            # rare enough that the circumscribed square is the honest bound.
            if abs((angle % 180) - 90) < 1:
                w, h = h, w
            elif angle % 90 > 1:
                w = h = max(w, h)
            xs += [x - w / 2, x + w / 2]
            ys += [y - h / 2, y + h / 2]
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    def _courtyard_box():
        return _graphic_box(".CrtYd")

    def courtyard_clearance():
        """The narrowest gap between the courtyard and the copper it encloses.

        `conventions-footprints` §4 decided 0.25 mm on 2026-08-27, snapped
        outward to the 0.1 mm grid, and recorded that the 0.5 mm this library
        never used must not be re-derived. A LARGER courtyard stays legitimate
        — a tall part beside a connector, a hand-soldering variant — so the
        check that reads this asserts a FLOOR, never a value.
        """
        inner, outer = _extent(), _courtyard_box()
        if inner is None or outer is None:
            return None
        gap = min(inner[0] - outer[0], inner[1] - outer[1],
                  outer[2] - inner[2], outer[3] - inner[3])
        return f"{round(gap, 4):g}"

    def pin1_marks():
        """`Cmts.User` pin-1 circles within 2 mm of pad 1.

        §4 requires one on every footprint that has a pad 1, and fixes the 2 mm
        so a verification sweep can find it — so the distance is part of the
        fact, not a threshold somebody can quietly widen. Absent when there is
        no pad 1 at all, which is `na` rather than a failure.
        """
        one = next((p for p in pads()
                    if str(p.get("number")) in ("1", "A1")), None)
        at = (one or {}).get("at")
        if not at or len(at) < 2:
            return None
        px, py = float(at[0]), float(at[1])
        n = 0
        src = source_of() or ""
        for m in re.finditer(r"\(fp_circle\b", src):
            block = _block_at(src, m.start())
            if "Cmts.User" not in block:
                continue
            c = re.search(r"\(center\s+(-?[\d.]+)\s+(-?[\d.]+)\)", block)
            if c is None:
                continue
            if ((float(c.group(1)) - px) ** 2 + (float(c.group(2)) - py) ** 2) ** 0.5 <= 2.0:
                n += 1
        return str(n)

    def heatsink_pads():
        """Pads flagged `pad_prop_heatsink` — an exposed pad or a thermal via.

        What the thermal-via rule is about. Asking every footprint about via
        stitching is asking a 2-pad chip resistor about a heat path it does not
        have.
        """
        if not parsed():
            return None
        return str(sum(1 for p in pads()
                       if any("heatsink" in str(v) for v in (p.get("property") or []))))

    def rotation_offset():
        m = re.search(r'\(property\s+"FT Rotation Offset"\s+"([^"]*)"', source_of() or "")
        return (m.group(1).strip() or None) if m else None

    return {
        "$footprint_heatsink_pads": heatsink_pads,
        "$footprint_rotation_offset": rotation_offset,
        "$footprint_internal_name": internal_name,
        "$footprint_pad_name_decimals": package_decimals,
        "$footprint_rotation_alt_fields": rotation_alt_fields,
        "$footprint_courtyard_clearance": courtyard_clearance,
        "$footprint_pin1_marks": pin1_marks,
        "$footprint_silk_over_pads": silk_over_pads,
        "$footprint_thermal_vias": thermal_vias,
        "$footprint_vias_outside_ep": vias_outside_ep,
        "$footprint_pad_count": pad_count,
        "$footprint_min_pitch": min_pitch,
        "$footprint_fine_pitch": fine_pitch,
        "$footprint_smd_pads": of_type("smd"),
        "$footprint_th_pads": of_type("thru_hole"),
        "$footprint_npth_pads": of_type("np_thru_hole"),
        "$footprint_zero_annulus_pads": zero_annulus,
        "$footprint_off_grid_pads": off_grid,
        "$footprint_smd_rratio_off": rratio_off,
        "$footprint_pin1_corner": pin1_corner,
        "$footprint_numbering": numbering,
    }


def _symbol_providers(source_of, name_of=lambda: None) -> dict:
    """Facts of one symbol. `source_of` is called at most once per read.

    `name_of` is the symbol's own library name, for the facts that compare a
    stored default against it. It defaults to None so a caller that has no
    parent in hand still works — the facts that need it then read as absent,
    which is the honest outcome.
    """
    from . import material

    cache: dict = {}

    def pins() -> list[dict]:
        if "pins" not in cache:
            try:
                cache["pins"] = material.symbol_material(source_of() or "")["pins"]
                cache["parsed"] = True
            except Exception:  # noqa: BLE001
                cache["pins"] = []
                cache["parsed"] = False
        return cache["pins"]

    def parsed() -> bool:
        """Did the drawing PARSE — as distinct from having no pins.

        The two used to be one value: every count fact returned None for an
        empty pin list, so "this symbol draws no pins" and "this file is
        broken" were the same answer. A `when` predicate cannot tell them
        apart, and an absent fact never matches — so scoping a check on the pin
        count would have silently stopped asking it of an UNPARSEABLE symbol,
        which is the one that most needs asking. Six symbols draw no pins (a
        logo, an enclosure, a lightpipe, a cabled antenna, an RF pigtail, a
        terminal-block plug) and they now report "0", while a broken file still
        reports nothing at all.
        """
        pins()
        return bool(cache.get("parsed"))

    def count(fn):
        """A count that is 0 on a parsed drawing and absent on a broken one."""
        def wrapped():
            return str(fn()) if parsed() else None
        return wrapped

    def reference():
        m = re.search(r'\(property\s+"Reference"\s+"([^"]*)"', source_of() or "")
        return m.group(1) if m else None

    #: Which edge a pin sits on, from its ANGLE. In a `.kicad_sym` the pin's
    #: `at` is its connection point and the angle is the direction its body
    #: runs toward the box — so angle 0 is the LEFT edge, 180 the right, 270
    #: the top and 90 the bottom.
    #:
    #: Symbol Y points UP, the opposite of a footprint. Both live in this file.
    _EDGE = {0: "left", 90: "bottom", 180: "right", 270: "top"}

    def edge_of(pin: dict) -> str:
        at = pin.get("at") or []
        if len(at) < 3:
            return ""
        return _EDGE.get(int(round(float(at[2]))) % 360, "")

    #: Pin types that carry a signal or a supply. `conventions-symbols` §3
    #: forbids these on the top edge; an unconnected or free pin is not what
    #: that rule is about.
    _ELECTRICAL = {"input", "output", "bidirectional", "tri_state",
                   "power_in", "power_out", "open_collector", "open_emitter"}

    def on_edge(edge: str):
        def fn():
            if not parsed():
                return None
            return str(sum(1 for p in pins()
                           if edge_of(p) == edge and p.get("type") in _ELECTRICAL))
        return fn

    #: Pin types that carry a supply rail. `power_out` is included: a regulator's
    #: output is a rail on the symbol that draws it.
    _RAILS = {"power_in", "power_out"}

    def power_pins():
        """How many supply pins the symbol draws.

        What the rail-marking rules are about: a symbol with no rails cannot
        have a rail drawn the wrong way round.
        """
        if not parsed():
            return None
        return str(sum(1 for p in pins() if p.get("type") in _RAILS))

    def pin_names_hidden():
        """Whether the symbol hides its pin names.

        `(pin_names (hide yes))` is set on the SYMBOL — KiCad silently drops a
        per-pin `(hide yes)` inside a name, so this is the only place the flag
        can live, and it is the flag the triangle families depend on.
        """
        src = source_of() or ""
        if "(pin_names" not in src:
            return "false"
        return "true" if re.search(r"\(pin_names[^)]*\(?hide\s+yes", src) else "false"

    def stacked_pins():
        """Pins sharing a position with another pin in the same unit.

        Stacking is how a symbol shows two pin NUMBERS shorted at one point, so
        it is detected by POSITION, never by number — the numbers differ, which
        is the whole point of it. Counting shared numbers instead reports zero
        on this library while 22 symbols really do stack.
        """
        if not parsed():
            return None
        seen: dict = {}
        for pin in pins():
            at = pin.get("at") or []
            if len(at) < 2:
                continue
            spot = (round(float(at[0]), 4), round(float(at[1]), 4),
                    (pin.get("unit") or [0])[0])
            seen[spot] = seen.get(spot, 0) + 1
        return str(sum(c - 1 for c in seen.values() if c > 1))

    #: Pin names that claim NO net. A module with 70 pads named RESERVED is not
    #: claiming one reserved net — each pad is its own, and the name is a
    #: category. Same for NC and its spellings. Without this the duplicate
    #: count reports 69 on LE910R1 and 35 on EG915U and means nothing.
    _NO_NET_NAMES = {"NC", "N.C.", "N/C", "NC/DNU", "DNU", "DNC", "RESERVED",
                     "RES", "RSVD", "NOT_CONNECTED", "NOCONNECT"}


    def _dup_names(rows, exclude_types):
        spots: dict = {}
        for pin in rows:
            if exclude_types and pin.get("type") in exclude_types:
                continue
            name = str(pin.get("name") or "").strip()
            if not name or name == "~":
                continue
            if re.sub(r"\d+$", "", name).upper().rstrip("_") in _NO_NET_NAMES:
                continue
            at = pin.get("at") or []
            if len(at) < 2:
                continue
            spots.setdefault(name, set()).add(
                (round(float(at[0]), 4), round(float(at[1]), 4)))
        return sum(len(v) - 1 for v in spots.values() if len(v) > 1)

    def unstacked_duplicates():
        """Pins sharing a NAME that are NOT drawn at the same point.

        The half `sym.stacked` could never ask. That check is scoped to a
        symbol that already stacks, so it asks whether the stacking is right
        and never whether a part SHOULD have stacked. Two pins with the same
        name on different points are two nodes in the netlist with one name,
        which is either a deliberate drawing decision (a large IC showing how
        many supply pads it physically has, per the 2026-09-13 owner decision)
        or a defect. `Conn_IPEX` draws a U.FL jack's ground as two separate
        pins both named "Ext"; the datasheet's own schematic shows two
        connections.

        Counted per NAME, so a name on n separate points contributes n - 1.
        Unnamed and `~` pins are skipped: they carry no claim to be one net.
        """
        if not parsed():
            return None
        return str(_dup_names(pins(), None))

    def unstacked_duplicate_signals():
        """The same, counting SIGNAL pins only.

        This is the unambiguous half. A large IC's redundant GND and VDD pads
        are drawn separately ON PURPOSE (owner decision 2026-09-13: the
        schematic should show how many supply pads the part physically has, and
        a reader may want a decoupling capacitor against a particular one), so
        counting those reports 144 duplicates on an FPGA and says nothing. Two
        SIGNAL pins sharing a name on two points have no such defence: they are
        one name over two netlist nodes.
        """
        if not parsed():
            return None
        return str(_dup_names(pins(), _RAILS))

    def stub_lengths():
        """How many DISTINCT stub lengths the drawing mixes.

        The absolute length is a judgment call on the geometry; what is
        mechanical is mixing them inside one symbol, which is what
        `sym.pin_length` was written for.
        """
        lens = {p.get("length") for p in pins() if p.get("length") is not None}
        return str(len(lens)) if lens else None

    def pin_number_len():
        """The longest pin NUMBER, in characters.

        `conventions-symbols` §4 measured this against the house font: `B1` is
        0.14 mm over a 2.54 mm stub and accepted, `A12` is 1.17 mm over and
        prints into the body. Three characters is where the 5.08 mm stub
        becomes mandatory, so the WIDTH is the fact and the rule that reads it
        stays in the checklist.
        """
        nums = [str(p.get("number") or "") for p in pins()]
        return str(max((len(n) for n in nums), default=0)) if nums else None

    def stub_length():
        """The one stub length this drawing uses, or absent when it mixes them.

        Absent rather than a list: a mixed drawing is what `sym.pin_length`
        already fails, and a rule about the LENGTH cannot be judged until that
        is fixed.
        """
        lens = {p.get("length") for p in pins() if p.get("length") is not None}
        if len(lens) != 1:
            return None
        return f"{round(float(next(iter(lens))), 4):g}"

    #: KiCad draws an overbar as `~{NAME}`. It is invisible at sheet zoom, which
    #: is the whole reason `conventions-symbols` §5.6 requires the bubble too.
    def overbar_line_pins():
        """Active-low pins drawn without the inverted (bubble) graphic style.

        `SN74LVC1G74` had `PRE`, `CLR` and `Q` overbarred and drawn `line`, and
        read as fully active-high until you zoomed in. The name carries the
        claim; the bubble is what a reader actually sees.
        """
        if not parsed():
            return None
        return str(sum(1 for p in pins()
                       if "~{" in str(p.get("name") or "")
                       and "inverted" not in str(p.get("style") or "")))

    #: Property keys a BASE SYMBOL must never carry a default for. The
    #: generator seeds a component's property map from its base symbol, so a
    #: sourcing code stored on the drawing silently inherits onto the next
    #: component built from it. Correct today on a symbol with one component;
    #: a latent wrong part number the moment the drawing is reused.
    _SOURCING_KEYS = ("LCSC Part", "Supplier 1", "Supplier Part Number 1",
                      "Manufacturer 1", "Manufacturer Part Number 1")

    def visible_value_default():
        """The Value string the symbol DRAWS, or absent when Value is hidden.

        What `sym.default_values` is about, and it has to be the VALUE node
        specifically: every symbol draws its Reference, and `R` or `C` there is
        correct. A drawn Value default is the one a reader can mistake for a
        real rating - `R` stores "100R" and `L` stores "1mH", while KiCad stock
        stores "R" and "L", strings no real part can have.
        """
        src = source_of() or ""
        m = re.search(r'\(property\s+"Value"\s+"([^"]*)"', src)
        if m is None:
            return None
        block = _block_at(src, m.start())
        if re.search(r"\(hide\s+yes\)", block):
            return None
        return m.group(1) or None

    def value_default_is_name():
        """Does the drawn Value default equal the symbol's own name?

        The precise form of "a drawn default must not look like real part
        data". Almost every symbol draws its own name, which reads as a
        template at a glance. The defect is a GENERIC drawing whose stored
        default is one particular part's rating or part number — `SMAJxxA`
        drawing "12V", `Conn_01x06` drawing "DB2ERM-3.81-6P-GN", `MAX3222E`
        drawing "MAX3222EIPWR". A sheet then shows a real-looking value for a
        part nobody has chosen yet. Absent when Value is hidden, which is not
        this rule's business.
        """
        got = visible_value_default()
        if got is None:
            return None
        return "true" if got == name_of() else "false"

    def sourcing_defaults():
        src = source_of() or ""
        return str(sum(1 for k in _SOURCING_KEYS
                       if re.search(r'\(property\s+"%s"\s+"[^"]+"' % re.escape(k), src)))

    def named_pins():
        """Pins carrying a real NAME, as against a bare stub.

        What decides whether there is a pinout TABLE to check against. A
        connector drawn as eight unnamed passive stubs has pin NUMBERS and
        nothing else - "all 9 pins are unnamed passive stubs" is what three
        separate exceptions on the 8P8C family say in words. KiCad writes an
        unnamed pin as "~", and a name equal to the pin's own number carries
        nothing either.
        """
        if not parsed():
            return None
        n = 0
        for pin in pins():
            name = str(pin.get("name") or "").strip()
            if not name or name == "~" or name == str(pin.get("number") or ""):
                continue
            n += 1
        return str(n)

    def has_box():
        """Does the drawing have a rectangular BODY?

        The discriminator `conventions-symbols` section 4 always meant: the box
        half-height, the margins and the label offsets all describe a
        rectangle. A battery cell, a crystal, a fuse, a transistor, a diode and
        a varistor are GLYPHS - they have no box, and fourteen of them each
        carried a hand-written exception saying exactly that in words.
        """
        if not parsed():
            return None
        return "true" if re.search(r"\(rectangle\s", source_of() or "") else "false"

    def nc_pins():
        """Pins the datasheet calls NC — typed no_connect or free, or named NC.

        What the NC-pad rule is about. 2026-09-14: asking every symbol whether
        its NC pads are typed correctly is asking most of the library about a
        pad it has not got.
        """
        if not parsed():
            return None
        return str(sum(1 for p in pins()
                       if p.get("type") in ("no_connect", "free")
                       or re.fullmatch(r"NC\d*|N/?C", str(p.get("name") or ""), re.I)))

    def fp_filters():
        m = re.search(r'\(property\s+"ki_fp_filters"\s+"([^"]*)"', source_of() or "")
        return (m.group(1).strip() or None) if m else None

    return {
        "$symbol_has_box": has_box,
        "$symbol_sourcing_defaults": sourcing_defaults,
        "$symbol_visible_value_default": visible_value_default,
        "$symbol_value_default_is_name": value_default_is_name,
        "$symbol_named_pins": named_pins,
        "$symbol_nc_pins": nc_pins,
        "$symbol_fp_filters": fp_filters,
        "$symbol_pin_number_len": pin_number_len,
        "$symbol_stub_length": stub_length,
        "$symbol_overbar_line_pins": overbar_line_pins,
        "$symbol_reference": reference,
        "$symbol_top_edge_pins": on_edge("top"),
        "$symbol_bottom_edge_pins": on_edge("bottom"),
        "$symbol_power_pins": power_pins,
        "$symbol_pin_names_hidden": pin_names_hidden,
        "$symbol_stacked_pins": stacked_pins,
        "$symbol_stub_lengths": stub_lengths,
        "$symbol_unstacked_duplicates": unstacked_duplicates,
        "$symbol_unstacked_duplicate_signals": unstacked_duplicate_signals,
        "$symbol_pin_count": count(lambda: len(pins())),
        # DISTINCT numbers, which is what compares against a pad set: stacked
        # (shorted) pins share one number and must not count twice.
        "$symbol_pin_numbers": count(lambda: len({p.get("number") for p in pins()})),
        # `unit` is [unit, style] — a LIST, so a naive set of them raises and
        # the fact reads as absent, which is the quietest way for a declared
        # fact to never work.
        "$symbol_unit_count": count(lambda: len({(p.get("unit") or [0])[0] for p in pins()})),
        "$symbol_pin_types": lambda: ",".join(sorted({str(p.get("type") or "")
                                                      for p in pins()})) or None,
        "$symbol_on_board": lambda: "false" if re.search(
            r"\(on_board\s+no\)", source_of() or "") else "true",
    }


#: Where a 3D model reference has to point. The path is KiCad's own variable
#: form, so it resolves for every user without a per-machine setting.
MODEL_PREFIX = "${SEVENSIGMA_DIR}/3DModels/"


def _models_offpath(version) -> str | None:
    """How many of this footprint's 3D references sit outside the library path."""
    if version is None:
        return None
    models = version.models or []
    if not models:
        return None
    n = 0
    for entry in models:
        path = entry if isinstance(entry, str) else (entry or {}).get("path") or ""
        if path and not str(path).startswith(MODEL_PREFIX):
            n += 1
    return str(n)


def when_matches(when: dict | None, facts: dict | None) -> bool:
    """Does this item apply to the subject these facts describe?

    Every entry must match (AND), each value read as a regular expression. A
    fact that is ABSENT never matches: `{"comp_type": "^TVS$"}` excludes a part
    carrying no `comp_type` at all, which is what "apply this to TVS parts"
    means. `facts=None` is "no subject in hand" — the editor resolving a
    category to show it — and then every item applies, because the screen is
    describing the rule rather than judging one part.
    """
    if not when:
        return True
    if facts is None:
        return True
    for field, pattern in when.items():
        value = facts.get(field)
        if value is None:
            return False
        try:
            if re.match(str(pattern), value) is None:
                return False
        except re.error:
            # A pattern that does not compile matches NOTHING rather than
            # everything: the check quietly not applying is recoverable, a
            # check quietly applying to the whole library is not. The save
            # path refuses these, so this only guards rows written before it.
            return False
    return True


def _group(items: list[dict]) -> dict[str, list[dict]]:
    """Items by key, order preserved. A key may hold several VARIANTS."""
    out: dict[str, list[dict]] = {}
    for item in items:
        out.setdefault(item["key"], []).append(item)
    return out


def discriminator_of(group: list[dict]) -> str | None:
    """The one field a multi-variant key splits on, or None for a single item.

    A key with several variants must discriminate on ONE field with distinct
    literal values (`routers/reviews._validate_items` enforces it), which is
    what lets `pick` avoid an ordering rule entirely: at most one literal can
    match, and the variant with no `when` is the explicit fallback. Order is
    therefore never consulted, so a sorted table can never contradict the
    effective precedence — the failure that positional first-match-wins would
    have introduced.
    """
    if len(group) < 2:
        return None
    for item in group:
        when = item.get("when") or {}
        if len(when) == 1:
            return next(iter(when))
    return None


def pick(group: list[dict], facts: dict | None) -> tuple[dict | None, str]:
    """The one item of a key group that applies, and why.

    Returns ``(item, reason)`` where reason is ``ok``, ``disabled`` (every
    variant is switched off here) or ``no_match`` (nothing in the group is about
    a subject like this one). ``facts=None`` means no subject is in hand — the
    editor describing a rule rather than judging a part — and the first live
    variant stands in for the group.

    A variant set to `ignore` falls through to the next one rather than
    switching the whole check off (user decision 2026-09-14): ignoring the NMOS
    variant lets an NMOS part reach the fallback, which is what "this split does
    not apply here" means. Ignoring every variant is what switches the check
    off.
    """
    live = [i for i in group if severity_of(i) != "ignore"]
    if not live:
        return None, "disabled"
    if facts is None:
        return live[0], "ok"
    fallback = None
    for item in live:
        when = item.get("when")
        if not when:
            fallback = fallback or item
            continue
        if when_matches(when, facts):
            return item, "ok"
    if fallback is not None:
        return fallback, "ok"
    return None, "no_match"


def resolve(db: Session, kind: str, category_id: int | None = None,
            facts: dict | None = None) -> dict:
    """The merged checklist for one subject.

    Base checklist for the kind, plus every category-scoped checklist whose
    category sits on the subject's category path (components only — symbols
    and footprints have no category). Later (more specific) items win on a
    key collision.

    **A more specific list REPLACES a key's whole variant group** (user
    decision 2026-09-14). A category states the complete set for that key, not
    an addition to the one above it — the same rule its `required_properties`
    has always followed. To add one special case while keeping the general
    rule, switch the general one off and add a new KEY for the exception;
    restating a group you meant to extend is the mistake this prevents.

    Returns ``items`` (one per key — the variant that applies), ``disabled``
    (a key every variant of which is switched off here) and ``inapplicable``
    (a key with variants, none of them about a subject like this one). Those
    three are different statements about different people's decisions and must
    never be folded together: "the owner turned it off" and "this is not about
    parts like this one" are not the same thing, and a card that prints one
    where it means the other is lying about who decided.

    ``facts=None`` skips the judging entirely and returns every live variant,
    which is what a screen describing a category needs.
    """
    base = db.query(M.Checklist).filter_by(subject_kind=kind, category_id=None).first()
    version_id, items = _current_items(base) if base is not None else (None, [])
    merged: dict[str, list[dict]] = _group(items)

    if category_id is not None:
        path_ids: list[int] = []
        cat = db.get(M.Category, category_id)
        while cat is not None:
            path_ids.append(cat.id)
            cat = cat.parent
        scoped = (
            db.query(M.Checklist)
            .filter(M.Checklist.subject_kind == kind, M.Checklist.category_id.in_(path_ids))
            .all()
            if path_ids else []
        )
        # apply from the top of the tree down, so the most specific wins
        for cl in sorted(scoped, key=lambda c: path_ids.index(c.category_id), reverse=True):
            _vid, extra = _current_items(cl)
            for key, group in _group(extra).items():
                merged[key] = group

    out: list[dict] = []
    off: list[dict] = []
    none_match: list[dict] = []
    for key, group in merged.items():
        if facts is None:
            live = [i for i in group if severity_of(i) != "ignore"]
            out.extend(live)
            if not live:
                off.append(group[0])
            continue
        item, why = pick(group, facts)
        if why == "ok" and item is not None:
            out.append(item)
        elif why == "disabled":
            off.append(group[0])
        else:
            none_match.append(group[0])

    return {
        "checklist_version_id": version_id,
        "items": out,
        "disabled": off,
        "inapplicable": none_match,
    }



#: `rules.block` key -> (check key, parameter name). What the old engine held
#: and which check now owns it. `footprint_style` / `footprint_dimensions` /
#: `symbol_style` are flattened first, since their names were already unique.
_RULE_KEY_TO_PARAM = {
    "min_drill_diameter": ("fp.min_drill", "min_drill_diameter"),
    "min_pad_size": ("fp.min_th_pad", "min_pad_size"),
    "min_via_size": ("fp.via_dims", "min_via_size"),
    "min_via_drill": ("fp.via_dims", "min_via_drill"),
    "thermal_via_warning_only": ("fp.via_dims", "thermal_via_warning_only"),
    "crtyd_line_width_mm": ("fp.courtyard_width", "crtyd_line_width_mm"),
    "fab_line_width_mm": ("fp.fab_width", "fab_line_width_mm"),
    "silk_line_width_mm": ("fp.silk_width", "silk_line_width_mm"),
    "coordinate_grid_mm": ("fp.courtyard_grid", "coordinate_grid_mm"),
    "pin_grid_mm": ("sym.pins_grid", "pin_grid_mm"),
    "required_properties": ("cmp.required_props", "required_properties"),
    "non_empty_properties": ("cmp.required_props", "non_empty_properties"),
    "manufacturer_properties": ("cmp.manufacturer", "manufacturer_properties"),
}

#: Keys the old blocks carried that no check consumes. Named so the migration
#: can report them rather than drop them silently: `conditional_required_properties`
#: is a real per-category rule nobody has implemented, and the rest were only
#: ever restatements of what the code does anyway.
_RULE_KEYS_UNUSED = ("footprint_required", "max_property_length", "pad_shape",
                     "pad_roundrect_rratio", "require_crtyd", "require_fab_outline",
                     "no_easyeda_prefix", "exempt_base_components",
                     "conditional_required_properties")


def _flatten_block(block: dict | None) -> tuple[dict, dict, list[str]]:
    """One `rules.block` as (parameter values, property patterns, unused keys)."""
    flat: dict = {}
    for key, value in (block or {}).items():
        if key in ("footprint_dimensions", "footprint_style", "symbol_style") \
                and isinstance(value, dict):
            flat.update(value)
        else:
            flat[key] = value
    values = {k: v for k, v in flat.items() if k in _RULE_KEY_TO_PARAM}
    patterns = flat.get("property_patterns") or {}
    unused = sorted(k for k in flat if k not in _RULE_KEY_TO_PARAM
                    and k != "property_patterns")
    return values, patterns, unused


def _stamp(db: Session, kind: str, items: list[dict], values: dict,
           patterns: dict, only_missing: bool) -> bool:
    """Write `params` onto the machine items of one checklist. Returns whether
    anything moved."""
    from . import validator

    by_key = {i.get("key"): i for i in items}
    touched = False
    for spec in validator._CHECK_SPECS.get(kind, ()):
        wanted = dict(spec.get("params") or {})
        if not wanted:
            continue
        item = by_key.get(spec["key"])
        if item is None or (only_missing and item.get("params")):
            continue
        for name in wanted:
            src = next((k for k, (ck, pn) in _RULE_KEY_TO_PARAM.items()
                        if ck == spec["key"] and pn == name), None)
            if src is not None and src in values:
                wanted[name] = values[src]
            elif name == "patterns" and patterns:
                wanted[name] = dict(patterns)
            elif name == "pattern" and "LCSC Part" in patterns:
                wanted[name] = patterns["LCSC Part"]
        if item.get("params") == wanted:
            continue
        item["params"] = wanted
        entry = validator.machine_check(db, kind, spec["key"],
                                        {spec["key"]: {"params": wanted}})
        if entry is not None:
            item["text"] = entry["text"]
            if entry.get("hint"):
                item["hint"] = entry["hint"]
        touched = True
    return touched


def _publish(db: Session, cl: M.Checklist, items: list[dict], comment: str) -> str:
    # `cl.versions` is not appended to by `db.add` under `expire_on_commit=False`,
    # so number from the query, not the relationship — the trap
    # `services/repoint.py` documents.
    numbers = [n for (n,) in db.query(M.ChecklistVersion.version_no)
               .filter_by(checklist_id=cl.id)]
    new = M.ChecklistVersion(checklist_id=cl.id, version_no=max(numbers, default=0) + 1,
                             items=items, status="published", created_by="migration",
                             comment=comment)
    db.add(new)
    db.flush()
    cl.current_version_id = new.id
    return f"{cl.name} v{new.version_no}"


def migrate_rules_onto_items(db: Session) -> dict:
    """Fold the `rules` table into the checklists. Idempotent (2026-09-14).

    Validation rules used to be JSON blocks in a `rules` table: one `global` row
    holding the numbers for eleven different checks, and 15 `library` rows — one
    per top-level category, seeded by the YAML import — that **nothing ever
    read**. A category could state that a Capacitor carries Value and Voltage
    and no part was ever measured against it.

    They are now `params` on the checklist item of the check that uses them. The
    move buys four things at once and costs no new machinery: a parameter sits
    beside the switch that turns its check on, it versions with the checklist and
    carries the comment saying why it changed, it lands in
    `ReviewRecord.checklist_items` so a past verification says what it was
    measured against, and a CATEGORY states its own by putting the item on a
    category-scoped component checklist — which `resolve` already merges.

    The `rules` rows are left in place, inert. Deleting data that took a
    migration to read is not this function's job, and `_RULE_KEYS_UNUSED` names
    what nothing consumes so the report says what was NOT carried over.
    """
    from . import validator

    report: dict = {"published": [], "unused": {}}

    # --- the global row: the base checklist of every kind ---
    row = db.query(M.Rule).filter_by(scope="global", enabled=True).first()
    values, patterns, unused = _flatten_block(row.block if row else None)
    if unused:
        report["unused"]["global"] = unused
    for kind in BASE_NAMES:
        cl = db.query(M.Checklist).filter_by(subject_kind=kind, category_id=None).first()
        if cl is None:
            continue
        cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
        if cv is None:
            continue
        items = [dict(i) for i in (cv.items or [])]
        # An automatic check the base list has never carried is added SWITCHED
        # OFF. `cmp.property_values` is new here, and adding a machine item to a
        # live base checklist un-answers it on every existing subject with no
        # backfill — that is what moved all 418 components to partial on
        # 2026-08-25. Off, it is visible in the editor and costs nothing; the
        # category lists below turn it on where there are patterns to apply.
        have = {i.get("key") for i in items}
        added = False
        for key in validator.MACHINE_KEYS.get(kind, ()):
            if key in have:
                continue
            item = machine_item(db, kind, key, severity="warning")
            if item is not None:
                items.append(item)
                added = True
        # A base item that already states its params keeps them: this has run
        # before, or somebody has edited one since.
        if _stamp(db, kind, items, values, patterns, only_missing=True) or added:
            report["published"].append(
                _publish(db, cl, items,
                         "Validation rules moved from the rules table onto the checks "
                         "that use them"))

    # --- one category row -> one category-scoped COMPONENT checklist ---
    for rule in db.query(M.Rule).filter_by(scope="library", enabled=True).all():
        if rule.category_id is None:
            continue
        cat = db.get(M.Category, rule.category_id)
        if cat is None:
            continue
        values, patterns, unused = _flatten_block(rule.block)
        if unused:
            report["unused"][cat.name] = unused
        if not values and not patterns:
            continue
        cl = (db.query(M.Checklist)
              .filter_by(subject_kind="component", category_id=rule.category_id).first())
        if cl is None:
            cl = M.Checklist(name=f"{cat.name} rules", subject_kind="component",
                             category_id=rule.category_id,
                             description=f"Property rules for {cat.name}")
            db.add(cl)
            db.flush()
            items: list[dict] = []
        else:
            cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
            items = [dict(i) for i in ((cv.items if cv else None) or [])]
        # Only the items this row has something to say about — a category
        # checklist that restated every check would look like a category that
        # means every one of them, and could never stop stating one.
        wanted_keys = {ck for k, (ck, _) in _RULE_KEY_TO_PARAM.items() if k in values}
        if patterns:
            wanted_keys.add("cmp.property_values")
            if "LCSC Part" in patterns:
                wanted_keys.add("cmp.lcsc_format")
        by_key = {i.get("key") for i in items}
        for key in wanted_keys:
            if key in by_key:
                continue
            item = machine_item(db, "component", key)
            if item is not None:
                items.append(item)
        # `only_missing=True`, for the same reason the base checklist above gives:
        # an item that already states its params has been written before, or
        # somebody has edited it since. This path passed False until 2026-09-14
        # and therefore RE-STAMPED every category checklist from the retired
        # rules table on EVERY startup — silently reverting edits. Measured:
        # removing the competing `Value` pattern from `cmp.property_values` on
        # Inductors published v4, and the next uvicorn reload published v5 with
        # the pattern back and the comment of v1. A migration that undoes the
        # thing it migrated TO is worse than one that never ran.
        if _stamp(db, "component", items, values, patterns, only_missing=True):
            report["published"].append(
                _publish(db, cl, items,
                         f"Property rules for {cat.name}, moved off the rules table"))

    if report["published"]:
        db.commit()
    return report


def migrate_severities(db: Session) -> list[str]:
    """Convert the retired ``disabled: true`` flag to ``severity``. Idempotent.

    Severity replaced the on/off switch on 2026-09-14: `ignore` IS "off", so a
    switch beside a severity was two controls for one decision. `severity_of`
    reads the old flag, which keeps every PAST record honest — but a stored item
    that still carries it cannot be told apart from one somebody deliberately
    set to `ignore`, and the four checks seeded off were never meant to be off.

    They were seeded off because turning a live machine item on re-opens the
    whole library (`cmp.datasheet_text` moved 418 components in one publish).
    "Off" was standing in for "on, but not urgent", and the honest spelling of
    that is `warning` — so those four are converted to warnings here and
    everything else to `ignore`.
    """
    published: list[str] = []
    for cl in db.query(M.Checklist).all():
        cv = next((v for v in cl.versions if v.id == cl.current_version_id), None)
        if cv is None:
            continue
        items = [dict(i) for i in (cv.items or [])]
        touched = False
        for item in items:
            if "severity" in item or not item.get("disabled"):
                continue
            item.pop("disabled", None)
            sev = "warning" if item.get("key") in SEED_AS_WARNING else "ignore"
            if sev != DEFAULT_SEVERITY:
                item["severity"] = sev
            touched = True
        if not touched:
            continue
        numbers = [n for (n,) in db.query(M.ChecklistVersion.version_no)
                   .filter_by(checklist_id=cl.id)]
        new = M.ChecklistVersion(
            checklist_id=cl.id, version_no=max(numbers, default=0) + 1, items=items,
            status="published", created_by="migration",
            comment="Severity replaces the on/off switch; the four checks seeded off "
                    "become warnings, which is what 'off' was standing in for")
        db.add(new)
        db.flush()
        cl.current_version_id = new.id
        published.append(f"{cl.name} v{new.version_no}")
    if published:
        db.commit()
    return published
