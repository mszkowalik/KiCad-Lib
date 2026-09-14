"""Machine-tier verification: the automatic checks recorded on every publish.

Port of the retired YAML pipeline's ``kicad_lib/kicad/validator.py`` checks
(archive/yaml-library branch), reshaped to run on ONE version's source text and
to answer checklist items instead of printing a report. The item keys match
``services/checklists.py``'s seeds; ``services/review.py`` stores the answers
as a machine ``ReviewRecord`` so agents and humans start their verification
with the mechanical part already answered.

Results per item: ``checked`` (rule holds), ``failed`` (concrete violation,
named in the note), ``na`` (the rule has nothing to apply to). Machine checks
never emit ``skipped`` — that word is reserved for a judgment call somebody
could not make.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from .. import models as M
from .generator import build_excluded, off_board
from .mirror import top_level_of
from .templates import TEMPLATE_RE

MANUFACTURER_PROPS = ("Manufacturer 1", "Manufacturer Part Number 1",
                      "Supplier 1", "Supplier Part Number 1")

# ------------------------------------------------------------- the parameters
# EVERY NUMBER, LIST AND PATTERN THIS MODULE MEASURES AGAINST LIVES ON THE
# CHECKLIST ITEM OF THE CHECK THAT USES IT (`params`), and the spec below is the
# fallback for an item that states none.
#
# It used to live in a `rules` row — one library-wide JSON block holding the
# numbers for eleven different checks, plus 15 category rows that NOTHING read.
# Three things were wrong with that and all three are fixed by the move:
# a reader of "F.Fab line width is 0.1 mm" had to know which block key produced
# it; the document that says whether a check runs said nothing about what it
# runs against; and a category could state a rule that was never applied. On the
# item the parameters version with the checklist, carry the comment saying why
# they changed, land in `ReviewRecord.checklist_items` so a past verification
# says what it was measured against, and — for components — inherit through
# category-scoped checklists with no second merge engine (user decision
# 2026-09-14). `models.Rule` is dormant history; nothing reads it.


def check_params(kind: str, items: dict | None = None) -> dict:
    """The parameters each automatic check of this kind runs with.

    ``items`` is the RESOLVED checklist, keyed by item key. A check's numbers
    are stored on its own checklist item — so they are versioned with the
    checklist, they appear next to the switch that turns the check on, and the
    review record's `checklist_items` snapshot says what a past verification was
    measured against. An item that states none, or is absent, falls back to the
    spec default below.

    Returns ``{check key: {param: value}}``.
    """
    out: dict[str, dict] = {}
    for spec in _CHECK_SPECS.get(kind, ()):
        params = dict(spec.get("params") or {})
        if not params:
            continue
        stated = ((items or {}).get(spec["key"]) or {}).get("params") or {}
        for name, value in stated.items():
            if name in params:
                params[name] = value
        out[spec["key"]] = params
    return out

# ------------------------------------------------------- the check registry
# THE CATALOGUE OF AUTOMATIC CHECKS. This module — not the checklist document —
# owns which automatic checks exist, and what each one says.
#
# A checklist item marked `machine: true` whose key is not here is answered by
# nobody: it stays unanswered for ever and holds the subject at "partial". That
# used to be preventable only by the editor greying a checkbox out, which meant
# the WORDING of an automatic item was typed by hand into the checklist and
# could drift from what the code actually does. Now the checklist stores only
# whether each of these runs, the editor renders them read-only from here, and
# `routers/reviews._validate_items` rewrites their text and hint from this table
# on every save. To add an automatic check, add the entry here AND the branch
# below; `GET /api/checklists/meta` serves this verbatim.
_CHECK_SPECS: dict[str, tuple[dict, ...]] = {
    "footprint": (
        {"key": "fp.parse", "text": "Footprint source parses as a valid .kicad_mod"},
        {"key": "fp.courtyard_present", "text": "F.CrtYd courtyard outline is present"},
        {"key": "fp.courtyard_width",
         "text": "Courtyard line width is {crtyd_line_width_mm} mm",
         "params": {"crtyd_line_width_mm": 0.05}},
        {"key": "fp.courtyard_grid",
         "text": "Courtyard coordinates sit on the {coordinate_grid_mm} mm grid",
         "params": {"coordinate_grid_mm": 0.1}},
        {"key": "fp.fab_outline", "text": "F.Fab body outline is present"},
        {"key": "fp.fab_width", "text": "F.Fab line width is {fab_line_width_mm} mm",
         "params": {"fab_line_width_mm": 0.1}},
        {"key": "fp.silk_width", "text": "F.SilkS line width is {silk_line_width_mm} mm",
         "hint": "One polarity mark may be {silk_polarity_mark_width_mm} mm instead.",
         "params": {"silk_line_width_mm": 0.1, "silk_polarity_mark_width_mm": 0.2}},
        {"key": "fp.smd_pad_shape",
         "text": "SMD pads are roundrect (exposed/heatsink pads exempt)"},
        {"key": "fp.min_drill", "text": "No drill hole below {min_drill_diameter} mm",
         "params": {"min_drill_diameter": 0.3}},
        {"key": "fp.min_th_pad", "text": "No through-hole pad below {min_pad_size} mm",
         "hint": "A footprint carrying the text 'validation: ignore_min_pad_size' "
                 "suppresses this on itself.",
         "params": {"min_pad_size": 0.6}},
        {"key": "fp.via_dims",
         "text": "Via size and drill at or above {min_via_size}/{min_via_drill} mm",
         "hint": "A thermal via field may go below it while "
                 "thermal_via_warning_only is on.",
         "params": {"min_via_size": 0.3, "min_via_drill": 0.3,
                    "thermal_via_warning_only": True}},
        {"key": "fp.model3d",
         "text": "A 3D model is referenced and present in the library",
         "hint": "Fails until a human or agent marks it n/a for a part that "
                 "genuinely needs no model."},
    ),
    "symbol": (
        {"key": "sym.parse", "text": "Symbol source parses as a valid .kicad_sym library"},
        {"key": "sym.fields", "text": "Reference and Value fields are present"},
        {"key": "sym.pins_grid", "text": "All pins sit on the {pin_grid_mm} mm grid",
         "params": {"pin_grid_mm": 1.27}},
        {"key": "sym.pin_length", "text": "Every pin uses the same stub length",
         "hint": "The absolute length is a judgment call on sym.geometry. What is "
                 "mechanical is MIXING lengths inside one drawing."},
        {"key": "sym.sim_link",
         "text": "The simulation pin map still fits this version's pins",
         "hint": "n/a when no sim model is linked."},
    ),
    "component": (
        {"key": "cmp.required_props",
         "text": "The properties this category requires are present and filled in",
         "hint": "required: {required_properties} · must not be empty: "
                 "{non_empty_properties}",
         "params": {"required_properties": ["Footprint", "ki_description"],
                    "non_empty_properties": ["Footprint", "ki_description"]}},
        {"key": "cmp.footprint_ref",
         "text": "Footprint uses the {namespace} namespace and exists in the library",
         "params": {"namespace": "7Sigma:"}},
        {"key": "cmp.lcsc_format", "text": "LCSC Part matches {pattern}",
         "params": {"pattern": r"^C\d+$"}},
        {"key": "cmp.manufacturer", "text": "Manufacturer information is filled in",
         "hint": "Any ONE of {manufacturer_properties} carrying a value passes. "
                 "An empty list exempts the category.",
         "params": {"manufacturer_properties": list(MANUFACTURER_PROPS)}},
        # A check ON THE COMPONENT that examines the SYMBOL it pins. A symbol's
        # own checks cannot be scoped to a category — it carries none, one base
        # symbol is shared across categories, and a symbol nothing uses yet
        # resolves to nothing — so a per-category symbol rule is answered here,
        # where the category is the component's own and is exact (user decision
        # 2026-09-14).
        {"key": "cmp.base_symbol_allowed",
         "text": "The base symbol is one this category allows",
         "hint": "Allowed: {allowed_base_symbols}. n/a when the category allows any.",
         "params": {"allowed_base_symbols": []}},
        {"key": "cmp.property_values",
         "text": "Property values match the patterns this category sets",
         "hint": "One regular expression per property: {patterns}. "
                 "n/a when the category sets none.",
         "params": {"patterns": {}}},
        {"key": "cmp.templates", "text": "Every {Key} template reference resolves"},
        {"key": "cmp.datasheet_text",
         "text": "The archived datasheet is a searchable PDF, not a scan",
         "hint": "A document with no text layer cannot be searched, and read_datasheet "
                 "returns empty pages for it. Replace it with the manufacturer's text PDF."},
        {"key": "cmp.sim_params",
         "text": "Every Sim.Params key is declared by the linked simulation model",
         "hint": "n/a when the component carries no Sim.Params."},
    ),
}

#: Just the keys, per kind — the shape most callers want, and the one thing
#: about the catalogue that does not depend on the rule block.
MACHINE_KEYS: dict[str, tuple[str, ...]] = {
    kind: tuple(c["key"] for c in checks) for kind, checks in _CHECK_SPECS.items()
}

#: A `{name}` a threshold can fill. Anything else — `{Key}` in cmp.templates —
#: is left exactly as written, which is why this is a targeted substitution and
#: not `str.format`.
_PLACEHOLDER_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def _fill(text: str, numbers: dict) -> str:
    return _PLACEHOLDER_RE.sub(
        lambda m: _fmt(numbers[m.group(1)]) if m.group(1) in numbers else m.group(0), text)


def _fmt(value) -> str:
    """A parameter as a person writes it, not as Python repr()s it: `0.3` rather
    than `0.30000000000000004`, `Value, Voltage` rather than
    `['Value', 'Voltage']`, and a pattern map by the properties it covers."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:g}"
    if isinstance(value, dict):
        return ", ".join(value) or "none"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value) or "none"
    return str(value)


def machine_checks(db: Session, items: dict | None = None,
                   kind: str | None = None) -> dict[str, list[dict]]:
    """THE CATALOGUE OF AUTOMATIC CHECKS, worded with the LIVE thresholds.

    This module — not the checklist document — owns which automatic checks exist
    and what each one says. A checklist item marked `machine: true` whose key is
    not here is answered by nobody: it stays unanswered for ever and holds the
    subject at "partial". The checklist stores only the key, the flag and
    whether the check runs; `routers/reviews._validate_items` rewrites its text
    from here on every save, and `GET /api/checklists/meta` serves this verbatim.

    A check's TEXT is built from the parameters that check will actually run
    with — `items` is the resolved checklist, so the sentence a reviewer reads
    and the number the code compares against cannot disagree. Pass no `items`
    and every check is worded with its spec default.

    `params` rides along on each row so the editor can draw a box per number
    without a second call, and `defaults` so it can mark one as changed.

    To add an automatic check: add the entry to `_CHECK_SPECS` AND the branch
    that answers it.
    """
    out: dict[str, list[dict]] = {}
    for this_kind, checks in _CHECK_SPECS.items():
        if kind is not None and this_kind != kind:
            continue
        resolved = check_params(this_kind, items if kind is None or this_kind == kind else None)
        rows = []
        for c in checks:
            params = resolved.get(c["key"], {})
            row = {"key": c["key"], "text": _fill(c["text"], params)}
            if c.get("hint"):
                row["hint"] = _fill(c["hint"], params)
            if c.get("params"):
                row["params"] = params
                row["defaults"] = dict(c["params"])
            rows.append(row)
        out[this_kind] = rows
    return out


def machine_check(db: Session, kind: str, key: str, items: dict | None = None) -> dict | None:
    """The registry entry for one automatic check, or None if this module does
    not answer that key."""
    return next((c for c in machine_checks(db, items, kind).get(kind, ())
                 if c["key"] == key), None)


def _item(key: str, result: str, note: str = "") -> dict:
    out = {"key": key, "result": result}
    if note:
        out["note"] = note
    return out


# --------------------------------------------------------------- fp graphics
_GRAPHIC_TYPES = ("(fp_line", "(fp_rect", "(fp_poly", "(fp_arc", "(fp_circle")


def _parse_fp_graphics(content: str) -> list[dict]:
    """All fp graphic entries as {type, layer, width}. Handles legacy and
    KiCad 9/10 stroke-nested widths (same walk the old validator used)."""
    results = []
    i = 0
    while i < len(content):
        next_pos, found_type = len(content), None
        for gtype in _GRAPHIC_TYPES:
            pos = content.find(gtype, i)
            if pos != -1 and pos < next_pos:
                next_pos, found_type = pos, gtype
        if found_type is None:
            break
        start = next_pos
        depth, j = 0, start
        while j < len(content):
            if content[j] == "(":
                depth += 1
            elif content[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        block = content[start:j + 1]
        layer_m = re.search(r'\(layer\s+"?([FB]\.[^"\s)]+)"?\)', block)
        width_m = re.search(r"\(width\s+([\d.]+)\)", block)
        if layer_m:
            results.append({
                "type": found_type.lstrip("("),
                "layer": layer_m.group(1),
                "width": float(width_m.group(1)) if width_m else None,
                "block": block,  # for coordinate checks (courtyard grid)
            })
        i = j + 1
    return results


# every drawn coordinate pair a graphic block can carry
_COORD_RE = re.compile(r"\((?:start|end|mid|center|xy)\s+(-?[\d.]+)\s+(-?[\d.]+)\)")


def _off_grid(value: float, grid: float = 0.1) -> bool:
    """True when `value` does not sit on the grid. The comparison is scaled to
    grid units first — 1.05 is off a 0.1 grid, 0.30000000000000004 is not."""
    scaled = value / grid
    return abs(scaled - round(scaled)) > 1e-3


def _courtyard_grid_item(entries: list[dict], grid: float) -> dict:
    """`fp.courtyard_grid`: every courtyard coordinate on the configured grid.

    The courtyard is the clearance envelope other footprints are placed
    against, so an off-grid corner quietly poisons every board-level spacing
    decision made from it (user request 2026-08-24). Checks every coordinate a
    CrtYd graphic carries — line ends, arc mids, circle centers, polygon
    points — on both F.CrtYd and B.CrtYd.
    """
    coords: list[tuple[float, float]] = []
    for e in entries:
        if e["layer"].endswith(".CrtYd"):
            coords += [(float(x), float(y)) for x, y in _COORD_RE.findall(e.get("block", ""))]
    if not coords:
        return _item("fp.courtyard_grid", "na", "no courtyard graphics")
    bad = sorted({v for xy in coords for v in xy if _off_grid(v)})
    if bad:
        shown = ", ".join(f"{v:g}" for v in bad[:8]) + ("…" if len(bad) > 8 else "")
        return _item("fp.courtyard_grid", "failed",
                     f"courtyard coordinates off the 0.1 mm grid: {shown}")
    return _item("fp.courtyard_grid", "checked")


def _iter_pad_blocks(content: str):
    for m in re.finditer(r"\(pad\b", content):
        start = m.start()
        depth, i = 0, start
        while i < len(content):
            if content[i] == "(":
                depth += 1
            elif content[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        yield content[start:i + 1]


def _width_items(entries: list[dict], layer: str, want: float, key: str,
                 allow_one: float | None = None) -> dict:
    """Every line on `layer` is `want` mm wide.

    `allow_one` permits a SINGLE line at a second width. That is the cathode
    bar: `F.SilkS` is 0.1 mm, and one polarity mark may be 0.2 mm because a
    thin bar does not read beside the pads (Mateusz Kowalik, 2026-09-13). One,
    not many — a footprint drawn wholly at 0.2 mm is still wrong, which is what
    this count catches.
    """
    ours = [e for e in entries if e["layer"] == layer and e["width"] is not None]
    if not ours:
        return _item(key, "na", f"no {layer} graphics with a width")
    off = [e for e in ours if abs(e["width"] - want) > 0.001]
    if allow_one is not None:
        marks = [e for e in off if abs(e["width"] - allow_one) > 0.001]
        if not marks and len(off) <= 1:
            note = (f"one {allow_one} mm polarity mark, the rest {want} mm"
                    if off else "")
            return _item(key, "checked", note)
        if not marks:
            return _item(key, "failed",
                         f"{len(off)} lines at {allow_one} mm on {layer} — only ONE "
                         f"polarity mark may be {allow_one} mm, the rest must be {want} mm")
    bad = sorted({e["width"] for e in off})
    if bad:
        return _item(key, "failed", f"{layer} line width {bad} — should be {want} mm")
    return _item(key, "checked")


# ------------------------------------------------------------------ footprint
def validate_footprint(db: Session, version: M.FootprintVersion,
                       items: dict | None = None) -> list[dict]:
    p = check_params("footprint", items)
    content = version.source_text or ""
    items: list[dict] = []

    parsed_ok = bool(version.parsed)
    items.append(_item("fp.parse", "checked" if parsed_ok else "failed",
                       "" if parsed_ok else "source did not parse"))
    if not parsed_ok:
        return items

    graphics = _parse_fp_graphics(content)

    has_crtyd = bool(re.search(r"F\.CrtYd", content))
    items.append(_item("fp.courtyard_present", "checked" if has_crtyd else "failed",
                       "" if has_crtyd else "no F.CrtYd courtyard outline"))
    items.append(_width_items(graphics, "F.CrtYd",
                              p["fp.courtyard_width"]["crtyd_line_width_mm"],
                              "fp.courtyard_width"))

    items.append(_courtyard_grid_item(
        graphics, p["fp.courtyard_grid"]["coordinate_grid_mm"]))

    fab = [e for e in graphics if e["layer"] == "F.Fab"]
    items.append(_item("fp.fab_outline", "checked" if fab else "failed",
                       "" if fab else "no F.Fab body outline"))
    items.append(_width_items(graphics, "F.Fab", p["fp.fab_width"]["fab_line_width_mm"],
                              "fp.fab_width"))
    items.append(_width_items(graphics, "F.SilkS",
                              p["fp.silk_width"]["silk_line_width_mm"], "fp.silk_width",
                              allow_one=p["fp.silk_width"]["silk_polarity_mark_width_mm"]))

    # SMD pad shape: roundrect, exposed/heatsink pads exempt (stock EPs are
    # rect, and a roundrect EP clips corner thermal vias).
    non_roundrect = []
    smd_seen = False
    for pad in _iter_pad_blocks(content):
        m = re.match(r'\(pad\s+(?:"[^"]*"|\S+)\s+smd\s+(\w+)', pad)
        if not m:
            continue
        smd_seen = True
        if m.group(1) in ("rect", "oval") and "pad_prop_heatsink" not in pad:
            non_roundrect.append(m.group(1))
    if not smd_seen:
        items.append(_item("fp.smd_pad_shape", "na", "no SMD pads"))
    elif non_roundrect:
        items.append(_item("fp.smd_pad_shape", "failed",
                           f"{len(non_roundrect)} SMD pad(s) with shape {sorted(set(non_roundrect))} "
                           "— use roundrect (rratio 0.25)"))
    else:
        items.append(_item("fp.smd_pad_shape", "checked"))

    # Drills and through-hole pad sizes, from the parsed pad cache.
    pads = (version.parsed or {}).get("pads") or []
    drills = [p["drill"] for p in pads if isinstance(p.get("drill"), (int, float))]
    min_drill = p["fp.min_drill"]["min_drill_diameter"]
    small_drills = [d for d in drills if d < min_drill]
    if not drills:
        items.append(_item("fp.min_drill", "na", "no drilled pads"))
    elif small_drills:
        items.append(_item("fp.min_drill", "failed",
                           f"{len(small_drills)} drill(s) below {_fmt(min_drill)} mm "
                           f"(smallest {min(small_drills)} mm)"))
    else:
        items.append(_item("fp.min_drill", "checked"))

    ignore_pad_size = "validation: ignore_min_pad_size" in content.lower()
    th_sizes = [min(p["size"]) for p in pads
                if p.get("type") == "thru_hole" and isinstance(p.get("size"), list) and p["size"]]
    min_th_pad = p["fp.min_th_pad"]["min_pad_size"]
    small_pads = [s for s in th_sizes if s < min_th_pad]
    if ignore_pad_size or not th_sizes:
        items.append(_item("fp.min_th_pad", "na",
                           "suppressed in the footprint" if ignore_pad_size else "no through-hole pads"))
    elif small_pads:
        items.append(_item("fp.min_th_pad", "failed",
                           f"{len(small_pads)} through-hole pad(s) below "
                           f"{_fmt(min_th_pad)} mm "
                           f"(smallest {min(small_pads)} mm)"))
    else:
        items.append(_item("fp.min_th_pad", "checked"))

    vias = re.findall(r"\(via\s+\([^)]*\)\s+\(size\s+([\d.]+)\)\s+\(drill\s+([\d.]+)\)", content)
    is_thermal = "thermalvias" in (version.footprint.name if version.footprint else "").lower() \
        or "thermal" in content.lower()
    via = p["fp.via_dims"]
    bad_vias = [(float(s), float(d)) for s, d in vias
                if float(s) < via["min_via_size"] or float(d) < via["min_via_drill"]]
    # A thermal-via field is a deliberate array of small vias under a pad, so
    # the fab minimum does not apply to it — unless the checklist item says it does.
    thermal_warn_only = bool(via.get("thermal_via_warning_only", True))
    if not vias:
        items.append(_item("fp.via_dims", "na", "no vias"))
    elif bad_vias and not (is_thermal and thermal_warn_only):
        items.append(_item("fp.via_dims", "failed",
                           f"{len(bad_vias)} via(s) below "
                           f"{_fmt(via['min_via_size'])}/{_fmt(via['min_via_drill'])} mm"))
    else:
        note = f"{len(bad_vias)} small thermal via(s) — allowed" if bad_vias else ""
        items.append(_item("fp.via_dims", "checked", note))

    # 3D model: required by default; deferrable only by a human/agent marking
    # the item n/a in a follow-up verification.
    models = version.models or []
    if not models:
        items.append(_item("fp.model3d", "failed",
                           "no 3D model referenced — mark n/a in a follow-up if this part needs none"))
    else:
        missing = []
        for m in models:
            rel = m.split("/3DModels/", 1)[-1]
            if db.query(M.Model3D).filter_by(rel_path=rel).first() is None:
                missing.append(rel)
        if missing:
            items.append(_item("fp.model3d", "failed",
                               "referenced model(s) not in the library: " + ", ".join(missing)))
        else:
            items.append(_item("fp.model3d", "checked"))
    return items


# --------------------------------------------------------------------- symbol
def validate_symbol(db: Session, version: M.SymbolVersion,
                    items: dict | None = None) -> list[dict]:
    p = check_params("symbol", items)
    content = version.source_text or ""
    items: list[dict] = []

    parsed_ok = bool(version.parsed)
    items.append(_item("sym.parse", "checked" if parsed_ok else "failed",
                       "" if parsed_ok else "source did not parse"))
    if not parsed_ok:
        return items

    has_ref = '"Reference"' in content
    has_val = '"Value"' in content
    if has_ref and has_val:
        items.append(_item("sym.fields", "checked"))
    else:
        missing = [n for n, ok in (("Reference", has_ref), ("Value", has_val)) if not ok]
        items.append(_item("sym.fields", "failed", "missing field(s): " + ", ".join(missing)))

    # Pin positions from (pin ... (at x y angle) ...) blocks.
    blocks = _symbol_pin_blocks(content)
    off_grid = []
    ats = []
    for block in blocks:
        m = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)", block)
        if m is None:
            continue
        x, y = m.group(1), m.group(2)
        ats.append((x, y))
        for coord in (float(x), float(y)):
            grid = p["sym.pins_grid"]["pin_grid_mm"]
            if abs(coord / grid - round(coord / grid)) > 1e-4:
                off_grid.append((x, y))
                break
    if not ats:
        items.append(_item("sym.pins_grid", "na", "no pins found"))
    elif off_grid:
        items.append(_item("sym.pins_grid", "failed",
                           f"{len(off_grid)} pin(s) off the "
                           f"{_fmt(p['sym.pins_grid']['pin_grid_mm'])} mm grid, "
                           f"e.g. at {off_grid[0]}"))
    else:
        items.append(_item("sym.pins_grid", "checked"))

    items.append(_pin_length_item(blocks))
    items.append(_sim_link_item(db, version))
    return items


#: Start of one `(pin <type> <shape> ...)` block. Anchored to the start of a
#: line, because `(pin` also occurs mid-line inside property text — `A_S-1WR3`
#: has "5-pin SIP (pin 3 absent)" in its Description and it matched the
#: unanchored form. The child tokens are NOT in a fixed order: `LAN8671`
#: carries `(hide yes)` BEFORE `(at ...)`, which an `(at ...)`-then-`(length
#: ...)` regex skips silently, so split into blocks first and search each one.
_PIN_BLOCK_RE = re.compile(r"^[\t ]*\(pin\s+\w+\s+\w+", re.M)


def _symbol_pin_blocks(content: str) -> list[str]:
    """The source text of every pin, one string each."""
    starts = [m.start() for m in _PIN_BLOCK_RE.finditer(content)]
    return [content[a:b] for a, b in zip(starts, starts[1:] + [len(content)])]


def _pin_length_item(blocks: list[str]) -> dict:
    """`sym.pin_length` — one stub length across the whole symbol.

    The ABSOLUTE length is a judgment call and stays on `sym.geometry`: the
    house default is 2.54 mm, but a symbol whose pin numbers run to three or
    more characters needs 5.08 mm for the number to sit on its stub, and a
    drawing may legitimately carry another length. What is mechanical, and
    what actually goes wrong, is MIXING lengths inside one drawing — it puts
    the pin ends on two different vertical lines and no wire grid can hide it.
    """
    lengths = []
    for block in blocks:
        m = re.search(r"\(length\s+([\d.]+)\)", block)
        if m is not None:
            lengths.append(float(m.group(1)))
    if not lengths:
        return _item("sym.pin_length", "na", "no pins found")
    distinct = sorted(set(lengths))
    if len(distinct) > 1:
        counts = ", ".join(f"{v:g} mm on {lengths.count(v)} pin(s)" for v in distinct)
        return _item("sym.pin_length", "failed", f"mixed pin stub lengths: {counts}")
    return _item("sym.pin_length", "checked", f"all pins {distinct[0]:g} mm")


def _sim_link_item(db: Session, version: M.SymbolVersion) -> dict:
    """`sym.sim_link` — is the symbol's sim link still valid against THIS
    version's pins?

    Every failure here was a SILENT wrong answer in the simulation spike:
    KiCad emits whatever `Sim.Pins` says, so a swapped pair once tied an
    op-amp's in+ to ground with no diagnostic anywhere. The mirror already
    withholds Sim fields from a stale link; this item is the reviewer-facing
    twin, so the publish that broke a map fails validation instead of only
    warning in the mirror log. Pin types matter too: `power_in` rails are
    what lets ERC catch an unconnected supply (the floating-vcc case that
    silently clamped an output at half scale), so the rail/signal heuristic
    findings are reported here as well.
    """
    from . import material
    from .simcompose import COMPOSED_KIND, validate_composition
    from .simmodel import link_material_sha, validate_pin_map

    sym = db.get(M.Symbol, version.symbol_id)
    link = db.query(M.SymbolSimLink).filter_by(symbol_id=version.symbol_id).first() if sym else None
    if link is None:
        return _item("sym.sim_link", "na", "no sim model linked")
    model = link.sim_model
    mv = next((v for v in model.versions if v.id == model.current_version_id), None)
    if mv is None:
        return _item("sym.sim_link", "failed", f"linked model {model.name!r} has no published version")
    try:
        pins = material.symbol_material(version.source_text)["pins"]
    except Exception as e:  # noqa: BLE001
        return _item("sym.sim_link", "failed", f"cannot read pins to check the map: {e}")
    if link.mode == COMPOSED_KIND:
        # The composed twin of everything below. The design is checked against
        # THIS version's pins, which is the whole point of the item: a symbol
        # publish that renumbers a pin must fail here, not surface later as a
        # netlist wired to a pin that no longer exists.
        from .sim_store import block_catalog, composed_stale_reasons
        catalog = block_catalog(db)
        broken = composed_stale_reasons(sym.name, link.composition or {}, pins,
                                        mv.source_text, catalog)
        if broken:
            return _item("sym.sim_link", "failed",
                         f"composed model {model.name} does not build against this "
                         "version: " + "; ".join(broken))
        soft = [f["text"] for f in
                validate_composition(link.composition or {}, pins, catalog)
                if f["severity"] == "warning"]
        if soft:
            return _item("sym.sim_link", "failed",
                         f"{model.name} looks miswired: " + "; ".join(soft))
        blocks = len((link.composition or {}).get("blocks") or [])
        return _item("sym.sim_link", "checked",
                     f"composed as {model.name} from {blocks} block(s)")

    findings = validate_pin_map(link.pin_map, pins, (mv.parsed or {}).get("ports", []))
    errors = [f["text"] for f in findings if f["severity"] == "error"]
    warns = [f["text"] for f in findings if f["severity"] == "warning"]
    if errors:
        return _item("sym.sim_link", "failed",
                     f"pin map to {model.name} no longer fits: " + "; ".join(errors))
    if link_material_sha(pins) != link.symbol_material_sha:
        return _item("sym.sim_link", "failed",
                     f"pins changed since the map to {model.name} was authored — "
                     "re-confirm the map (set_symbol_sim_link) to publish Sim fields again")
    if warns:
        return _item("sym.sim_link", "failed",
                     f"map to {model.name} looks miswired: " + "; ".join(warns))
    return _item("sym.sim_link", "checked", f"mapped to {model.name}")


# ------------------------------------------------------------------ component
def validate_component(db: Session, cv: M.ComponentVersion, comp: M.Component,
                       checklist: dict | None = None) -> list[dict]:
    cp = check_params("component", checklist)
    props: dict[str, str | None] = {}
    for p in cv.properties:
        props[p.key] = None if p.is_null else p.value
    items: list[dict] = []

    # A part in the Simulation category is never placed on a board, so it has
    # no footprint to name and none to check — the same reasoning the BOM-only
    # branch already uses. Everything else about it IS checked: it still needs
    # a description, and it still goes through the review axis.
    sim_only = build_excluded(top_level_of(cv.category).name) if cv.category else False

    # An OFF-BOARD part: it is in the library and it does sit on a schematic,
    # but it has no land pattern — a cabled antenna, an RF pigtail, an
    # enclosure. It was the third class of footprint-less part and the only one
    # with no branch here, so `cmp.required_props` and `cmp.footprint_ref` both
    # failed by construction on every one of them, and a human had to answer
    # `na` by hand on each. Same predicate the generator uses, so what the
    # validator forgives and what KiCad is told cannot drift apart: the base
    # symbol must DECLARE `(on_board no)` — an empty Footprint alone still
    # fails, which is what keeps this from forgiving a forgotten one.
    sv = cv.symbol_version
    off_board_part = off_board(
        bool(sv is not None and re.search(r"\(on_board\s+no\)", sv.source_text or "")),
        bool((props.get("Footprint") or "").strip()),
    )

    if not comp.in_library:
        # BOM-only part: no symbol, no footprint, no KiCad emission.
        items.append(_item("cmp.required_props", "na", "BOM-only part"))
        items.append(_item("cmp.footprint_ref", "na", "BOM-only part"))
    elif sim_only or off_board_part:
        why = ("simulation-only part — excluded from the board" if sim_only
               else "off-board part — no land pattern, base symbol declares on_board no")
        required = [k for k in cp["cmp.required_props"]["required_properties"]
                    if k != "Footprint"]
        missing = [k for k in required if k not in props]
        if missing:
            items.append(_item("cmp.required_props", "failed", "missing: " + ", ".join(missing)))
        else:
            items.append(_item("cmp.required_props", "checked"))
        items.append(_item("cmp.footprint_ref", "na", why))
    else:
        required = cp["cmp.required_props"]["required_properties"]
        missing = [k for k in required if k not in props]
        empty = [k for k in cp["cmp.required_props"]["non_empty_properties"]
                 if k in props and props[k] is not None and not str(props[k]).strip()]
        if missing or empty:
            note = "; ".join(filter(None, [
                "missing: " + ", ".join(missing) if missing else "",
                "empty: " + ", ".join(empty) if empty else "",
            ]))
            items.append(_item("cmp.required_props", "failed", note))
        else:
            items.append(_item("cmp.required_props", "checked"))

        namespace = str(cp["cmp.footprint_ref"]["namespace"])
        fp_value = (props.get("Footprint") or "").strip()
        if not fp_value:
            items.append(_item("cmp.footprint_ref", "failed", "no Footprint property"))
        elif not fp_value.startswith(namespace):
            items.append(_item("cmp.footprint_ref", "failed",
                               f"{fp_value!r} is not in the {namespace} namespace"))
        else:
            fp = db.query(M.Footprint).filter_by(name=fp_value.split(":", 1)[1]).first()
            if fp is None or fp.current_version_id is None:
                items.append(_item("cmp.footprint_ref", "failed",
                                   f"{fp_value!r} has no published footprint"))
            else:
                items.append(_item("cmp.footprint_ref", "checked"))

    lcsc = props.get("LCSC Part")
    pattern = str(cp["cmp.lcsc_format"]["pattern"])
    if lcsc is None or "LCSC Part" not in props:
        items.append(_item("cmp.lcsc_format", "na", "no LCSC Part"))
    elif re.match(pattern, str(lcsc)):
        items.append(_item("cmp.lcsc_format", "checked"))
    else:
        items.append(_item("cmp.lcsc_format", "failed",
                           f"LCSC Part {lcsc!r} does not match {pattern}"))

    mfr_props = cp["cmp.manufacturer"]["manufacturer_properties"]
    if not comp.purchasable:
        items.append(_item("cmp.manufacturer", "na", "virtual part — never bought"))
    elif not mfr_props:
        # An EMPTY list is the category saying the check does not apply — it is
        # how `Mechanical_7S` and `TestPoints` exempt themselves. Read as "none
        # of these properties is filled in" it fails every part in those
        # categories instead, which is the opposite of what the list says (14 of
        # them, measured 2026-09-14 when the category rules were first wired in).
        items.append(_item("cmp.manufacturer", "na",
                           "the category asks for no manufacturer properties"))
    else:
        has_info = any(str(props.get(k) or "").strip() for k in mfr_props)
        any_defined = any(k in props for k in mfr_props)
        if has_info:
            items.append(_item("cmp.manufacturer", "checked"))
        elif any_defined:
            items.append(_item("cmp.manufacturer", "na", "manufacturer fields explicitly null"))
        else:
            items.append(_item("cmp.manufacturer", "failed", "no manufacturer information"))

    # The base symbol this component pins, against the set its category allows.
    # `cv.base_component` is a NAME, not a foreign key (see services/rename.py),
    # so this compares strings — which is also what the allow-list is written in.
    allowed = cp["cmp.base_symbol_allowed"]["allowed_base_symbols"]
    base_name = (cv.base_component or "").strip()
    if not allowed:
        items.append(_item("cmp.base_symbol_allowed", "na",
                           "this category allows any base symbol"))
    elif not base_name:
        items.append(_item("cmp.base_symbol_allowed", "na", "no base symbol"))
    elif base_name in allowed:
        items.append(_item("cmp.base_symbol_allowed", "checked", base_name))
    else:
        items.append(_item("cmp.base_symbol_allowed", "failed",
                           f"base symbol {base_name!r} is not one this category allows: "
                           + ", ".join(allowed)))

    # Property VALUES against the patterns the category sets. Category-scoped
    # checklists are what make this per-category: `Capacitor` states a Value and
    # a Voltage pattern on its own copy of this item, everything else inherits
    # an empty map and answers `na`.
    patterns = cp["cmp.property_values"]["patterns"] or {}
    bad: list[str] = []
    tested = 0
    for prop, expr in patterns.items():
        value = props.get(prop)
        if prop not in props or value is None or not str(value).strip():
            continue  # absent or null is `cmp.required_props`' business, not this one
        tested += 1
        try:
            ok = re.match(str(expr), str(value)) is not None
        except re.error as e:
            bad.append(f"{prop}: the pattern does not compile ({e})")
            continue
        if not ok:
            bad.append(f"{prop} = {value!r} does not match {expr}")
    if not patterns:
        items.append(_item("cmp.property_values", "na",
                           "this category sets no value patterns"))
    elif bad:
        items.append(_item("cmp.property_values", "failed", "; ".join(bad)))
    elif tested:
        items.append(_item("cmp.property_values", "checked",
                           f"{tested} value(s) against {len(patterns)} pattern(s)"))
    else:
        items.append(_item("cmp.property_values", "na",
                           "none of the patterned properties is filled in"))

    # Is the archived datasheet searchable? A document with no text layer is
    # not a cosmetic problem: text search misses it, and the agent's
    # `read_datasheet` hands back EMPTY text for every page of it — so a
    # verification that looks like it read the datasheet in fact rested on the
    # rendered page images alone. Classified once at store time, so this check
    # is a column read (see services/datasheet_store.classify_text_layer).
    unsearchable: list[str] = []
    partial: list[str] = []
    searchable = 0
    unclassified = False
    for d in (db.query(M.Datasheet)
              .filter_by(component_id=comp.id, archived=False)
              .order_by(M.Datasheet.position).all()):
        cur = next((v for v in d.versions if v.id == d.current_version_id), None)
        if cur is None:
            continue
        layer = cur.text_layer or ""
        if layer == "none":
            continue  # a DXF, a STEP file or an archived web page: nothing to search
        if layer == "":
            unclassified = True
        elif layer == "error":
            unsearchable.append(f"{d.label!r} does not open as a PDF")
        elif layer == "scan":
            unsearchable.append(
                f"{d.label!r} has no text layer ({cur.page_count or '?'} pages)")
        else:
            searchable += 1
            # `mixed` still passes — a TI datasheet whose last pages are image
            # plates is searchable. The note says which pages are not.
            if layer == "mixed":
                partial.append(f"{d.label!r} {cur.text_pages}/{cur.page_count} pages")
    if unsearchable:
        items.append(_item("cmp.datasheet_text", "failed", "; ".join(unsearchable)))
    elif searchable:
        items.append(_item("cmp.datasheet_text", "checked",
                           "part scan: " + "; ".join(partial) if partial else ""))
    elif unclassified:
        items.append(_item("cmp.datasheet_text", "na", "not classified yet"))
    else:
        items.append(_item("cmp.datasheet_text", "na", "no archived PDF"))

    # {Key} templates must resolve against the final property set. The
    # generator injects Footprint_Name from the footprint row, so it counts
    # as available even when the component does not carry its own copy.
    available = set(props) | {"Footprint_Name"}
    unresolved = []
    for key, value in props.items():
        if value is None or "{" not in str(value):
            continue
        for var in TEMPLATE_RE.findall(str(value)):
            if var not in available:
                unresolved.append(f"{{{var}}} in {key}")
    if any("{" in str(v) for v in props.values() if v is not None):
        if unresolved:
            items.append(_item("cmp.templates", "failed", "unresolved: " + "; ".join(unresolved)))
        else:
            items.append(_item("cmp.templates", "checked"))
    else:
        items.append(_item("cmp.templates", "na", "no templates used"))

    items.append(_sim_params_item(db, cv, props))
    return items


def _sim_params_item(db: Session, cv: M.ComponentVersion, props: dict) -> dict:
    """`cmp.sim_params` — do the component's Sim.Params keys exist on the
    linked model?

    Purely mechanical, and exists because the failure is silent twice over:
    ngspice rejects an undeclared parameter at parse time (the user sees a
    cryptic simulator error, not a library one), and a TYPO'd key means the
    intended datasheet value silently never applies — the model runs on its
    placeholder default instead. The values themselves are datasheet numbers
    and stay a human review item, not a machine one.
    """
    raw = props.get("Sim.Params") or ""
    sv = cv.symbol_version
    link = (db.query(M.SymbolSimLink).filter_by(symbol_id=sv.symbol_id).first()
            if sv is not None else None)
    if not raw.strip():
        return _item("cmp.sim_params", "na",
                     "no Sim.Params" + ("" if link is None else " — model defaults apply"))
    if link is None:
        return _item("cmp.sim_params", "failed",
                     "component carries Sim.Params but its symbol has no sim model link")
    model = link.sim_model
    mv = next((v for v in model.versions if v.id == model.current_version_id), None)
    declared = set(((mv.parsed or {}).get("params") or {})) if mv else set()
    given = re.findall(r"([A-Za-z_][\w]*)\s*=", raw)
    unknown = sorted(set(given) - declared)
    if unknown:
        return _item("cmp.sim_params", "failed",
                     f"{model.name} does not declare: " + ", ".join(unknown)
                     + " (declares: " + ", ".join(sorted(declared)) + ")")
    return _item("cmp.sim_params", "checked", f"{len(given)} parameter(s) against {model.name}")


# ------------------------------------------------------- declarative checks
#: The assertions an `assert` block may make about one fact. Closed on purpose:
#: this expresses ONE fact and ONE assertion, and that ceiling is the design.
#: The first time it needs two assertions joined by a boolean, or arithmetic
#: between two facts, it has stopped being a check and become a rules language —
#: which is what `models.Rule` was, and what this platform spent 2026-09-14
#: deleting. Reconsider at that point rather than adding `any_of`.
ASSERTIONS = ("one_of", "matches", "equals", "at_least", "at_most", "present")


#: Turning a claim into its opposite. Deliberately tiny: a claim is authored
#: beside its fact, so the only shapes that reach here are the ones written
#: there, and a general negator would be a grammar engine.
def _negate(claim: str) -> str:
    for verb in (" is ", " are ", " has "):
        if verb in claim:
            return claim.replace(verb, verb.rstrip() + " not ", 1)
    return f"not: {claim}"


def describe_assert(spec: dict) -> str:
    """The sentence a declarative check prints, built from what it will do.

    Generated rather than authored for the same reason a parameterised check's
    text is (decision 0014): a sentence typed beside a rule can disagree with
    it, and the reviewer believes the sentence.
    """
    from . import checklists

    #: A fact may carry a `noun` — the phrase that reads as the subject of a
    #: sentence. Without it the name is de-`$`-ed and de-underscored, which
    #: gives "The footprint zero annulus pads is at most 0": correct, and not a
    #: sentence anybody wants to read on a review card.
    entry = checklists.FACTS_BY_NAME.get(str(spec.get("fact", "")), {})
    fact = entry.get("noun") or str(spec.get("fact", "?")).lstrip("$").replace("_", " ")
    #: A boolean fact carries a `claim` — the sentence it asserts when true.
    #: Without it `equals: "true"` prints "The Value against the manufacturer
    #: part number is true", which is a description of the comparison rather
    #: than of the rule.
    claim = entry.get("claim")
    if claim and "equals" in spec and str(spec["equals"]).lower() in ("true", "false"):
        return claim if str(spec["equals"]).lower() == "true" else _negate(claim)
    if "one_of" in spec:
        values = spec["one_of"] or []
        if not values:
            return f"The {fact} is one of: nothing"
        # A long list is DATA, not a sentence. The canonical manufacturer list
        # is 81 names, and printing them all made a review card unreadable and
        # a checklist row 900 characters wide. The list itself is on the item,
        # one click away, and the editor shows it in full.
        if len(values) > 6:
            return f"The {fact} is one of the {len(values)} values this check lists"
        return f"The {fact} is one of: {', '.join(map(str, values))}"
    if "matches" in spec:
        return f"The {fact} matches {spec['matches']}"
    if "equals" in spec:
        return f"The {fact} is {spec['equals']}"
    if "at_least" in spec:
        return f"The {fact} is at least {_fmt(spec['at_least'])}"
    if "at_most" in spec:
        return f"The {fact} is at most {_fmt(spec['at_most'])}"
    return f"The {fact} is present"


def evaluate_assert(key: str, spec: dict, facts: dict | None) -> dict:
    """Answer one declarative check.

    A fact the subject has not got answers `na`, never `failed`: "this part has
    no symbol reference" is not the same statement as "its reference is wrong",
    and a checklist that conflates them sends somebody to fix the wrong thing.
    """
    fact = str(spec.get("fact", ""))
    value = (facts or {}).get(fact)
    if value is None or str(value) == "":
        return _item(key, "na", f"this subject has no {fact}")
    value = str(value)

    if "one_of" in spec:
        allowed = [str(v) for v in (spec["one_of"] or [])]
        if not allowed:
            return _item(key, "na", "no values are listed, so nothing is required")
        return (_item(key, "checked", value) if value in allowed else
                _item(key, "failed", f"{fact} is {value!r}, not one of: " + ", ".join(allowed)))
    if "matches" in spec:
        try:
            ok = re.match(str(spec["matches"]), value) is not None
        except re.error as e:
            return _item(key, "failed", f"the pattern does not compile ({e})")
        return (_item(key, "checked", value) if ok else
                _item(key, "failed", f"{fact} is {value!r}, which does not match "
                                     f"{spec['matches']}"))
    if "equals" in spec:
        want = str(spec["equals"])
        return (_item(key, "checked", value) if value == want else
                _item(key, "failed", f"{fact} is {value!r}, not {want!r}"))
    for name, ok in (("at_least", lambda a, b: a >= b), ("at_most", lambda a, b: a <= b)):
        if name in spec:
            try:
                got, want = float(value), float(spec[name])
            except (TypeError, ValueError):
                return _item(key, "na", f"{fact} is {value!r}, which is not a number")
            word = "at least" if name == "at_least" else "at most"
            return (_item(key, "checked", value) if ok(got, want) else
                    _item(key, "failed", f"{fact} is {_fmt(got)}, not {word} {_fmt(want)}"))
    return _item(key, "checked", value)


def validate(db: Session, kind: str, version, comp: M.Component | None = None,
             checklist: dict | None = None, only: set[str] | None = None,
             facts: dict | None = None) -> list[dict]:
    """Answer this module's checks for one version.

    ``checklist`` is the RESOLVED checklist keyed by item key. It carries both
    halves of an automatic check's configuration: whether it runs, and the
    numbers it runs with (`params` on the item). Pass none and every check runs
    with its spec default.

    ``only`` is the set of keys the checklist has switched ON — pass it and an
    answer for any other key is dropped. Dropped, not skipped: the branch still
    executes, and the filter is about what gets RECORDED. That is what makes
    switching a check off real, because a machine answer for a key the checklist
    does not carry is stored as a CUSTOM item and a `failed` one still holds the
    whole subject at "issues".
    """
    if kind == "footprint":
        answers = validate_footprint(db, version, checklist)
    elif kind == "symbol":
        answers = validate_symbol(db, version, checklist)
    else:
        answers = validate_component(db, version, comp, checklist)
    # Declarative checks: any item carrying an `assert` block, whatever its key.
    # Their keys are author-chosen, so they cannot be in `MACHINE_KEYS` — the
    # second door to `machine: true`, guaranteeing the same thing (something
    # answers this) by a different route.
    for item in (checklist or {}).values():
        spec = item.get("assert")
        if spec:
            answers.append(evaluate_assert(item["key"], spec, facts))

    if only is None:
        return answers
    return [i for i in answers if i["key"] in only]
