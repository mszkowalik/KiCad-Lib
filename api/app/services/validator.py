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
from .templates import TEMPLATE_RE

MIN_DRILL = 0.3
MIN_VIA_SIZE = 0.3
MIN_VIA_DRILL = 0.3
MIN_TH_PAD = 0.6
FAB_WIDTH = 0.1
SILK_WIDTH = 0.1
CRTYD_WIDTH = 0.05
PIN_GRID = 1.27

MANUFACTURER_PROPS = ("Manufacturer 1", "Manufacturer Part Number 1",
                      "Supplier 1", "Supplier Part Number 1")

# Every checklist key THIS module answers, per subject kind. A checklist item
# marked `machine: true` whose key is not here is answered by nobody: it stays
# unanswered for ever and holds the subject at "partial". The checklist editor
# reads this list to refuse exactly that, so keep it in step when you add or
# remove a check below — `GET /api/checklists/meta` serves it verbatim.
MACHINE_KEYS: dict[str, tuple[str, ...]] = {
    "footprint": (
        "fp.parse", "fp.courtyard_present", "fp.courtyard_width", "fp.fab_outline",
        "fp.fab_width", "fp.silk_width", "fp.smd_pad_shape", "fp.min_drill",
        "fp.min_th_pad", "fp.via_dims", "fp.model3d",
    ),
    "symbol": ("sym.parse", "sym.fields", "sym.pins_grid"),
    "component": (
        "cmp.required_props", "cmp.footprint_ref", "cmp.lcsc_format",
        "cmp.manufacturer", "cmp.templates",
    ),
}


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
            })
        i = j + 1
    return results


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


def _width_items(entries: list[dict], layer: str, want: float, key: str) -> dict:
    ours = [e for e in entries if e["layer"] == layer and e["width"] is not None]
    if not ours:
        return _item(key, "na", f"no {layer} graphics with a width")
    bad = sorted({e["width"] for e in ours if abs(e["width"] - want) > 0.001})
    if bad:
        return _item(key, "failed", f"{layer} line width {bad} — should be {want} mm")
    return _item(key, "checked")


# ------------------------------------------------------------------ footprint
def validate_footprint(db: Session, version: M.FootprintVersion) -> list[dict]:
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
    items.append(_width_items(graphics, "F.CrtYd", CRTYD_WIDTH, "fp.courtyard_width"))

    fab = [e for e in graphics if e["layer"] == "F.Fab"]
    items.append(_item("fp.fab_outline", "checked" if fab else "failed",
                       "" if fab else "no F.Fab body outline"))
    items.append(_width_items(graphics, "F.Fab", FAB_WIDTH, "fp.fab_width"))
    items.append(_width_items(graphics, "F.SilkS", SILK_WIDTH, "fp.silk_width"))

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
    small_drills = [d for d in drills if d < MIN_DRILL]
    if not drills:
        items.append(_item("fp.min_drill", "na", "no drilled pads"))
    elif small_drills:
        items.append(_item("fp.min_drill", "failed",
                           f"{len(small_drills)} drill(s) below {MIN_DRILL} mm "
                           f"(smallest {min(small_drills)} mm)"))
    else:
        items.append(_item("fp.min_drill", "checked"))

    ignore_pad_size = "validation: ignore_min_pad_size" in content.lower()
    th_sizes = [min(p["size"]) for p in pads
                if p.get("type") == "thru_hole" and isinstance(p.get("size"), list) and p["size"]]
    small_pads = [s for s in th_sizes if s < MIN_TH_PAD]
    if ignore_pad_size or not th_sizes:
        items.append(_item("fp.min_th_pad", "na",
                           "suppressed in the footprint" if ignore_pad_size else "no through-hole pads"))
    elif small_pads:
        items.append(_item("fp.min_th_pad", "failed",
                           f"{len(small_pads)} through-hole pad(s) below {MIN_TH_PAD} mm "
                           f"(smallest {min(small_pads)} mm)"))
    else:
        items.append(_item("fp.min_th_pad", "checked"))

    vias = re.findall(r"\(via\s+\([^)]*\)\s+\(size\s+([\d.]+)\)\s+\(drill\s+([\d.]+)\)", content)
    is_thermal = "thermalvias" in (version.footprint.name if version.footprint else "").lower() \
        or "thermal" in content.lower()
    bad_vias = [(float(s), float(d)) for s, d in vias
                if float(s) < MIN_VIA_SIZE or float(d) < MIN_VIA_DRILL]
    if not vias:
        items.append(_item("fp.via_dims", "na", "no vias"))
    elif bad_vias and not is_thermal:
        items.append(_item("fp.via_dims", "failed",
                           f"{len(bad_vias)} via(s) below {MIN_VIA_SIZE}/{MIN_VIA_DRILL} mm"))
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
def validate_symbol(db: Session, version: M.SymbolVersion) -> list[dict]:
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
    off_grid = []
    ats = re.findall(r"\(pin\s+\w+\s+\w+\s*\n?\s*\(at\s+([-\d.]+)\s+([-\d.]+)", content)
    for x, y in ats:
        for coord in (float(x), float(y)):
            if abs(coord / PIN_GRID - round(coord / PIN_GRID)) > 1e-4:
                off_grid.append((x, y))
                break
    if not ats:
        items.append(_item("sym.pins_grid", "na", "no pins found"))
    elif off_grid:
        items.append(_item("sym.pins_grid", "failed",
                           f"{len(off_grid)} pin(s) off the {PIN_GRID} mm grid, e.g. at {off_grid[0]}"))
    else:
        items.append(_item("sym.pins_grid", "checked"))
    return items


# ------------------------------------------------------------------ component
def _global_rules(db: Session) -> dict:
    row = db.query(M.Rule).filter_by(scope="global", enabled=True).first()
    if row is not None and row.block:
        return row.block
    from .importer import VALIDATOR_GLOBAL_DEFAULTS

    return VALIDATOR_GLOBAL_DEFAULTS


def validate_component(db: Session, cv: M.ComponentVersion, comp: M.Component) -> list[dict]:
    rules = _global_rules(db)
    props: dict[str, str | None] = {}
    for p in cv.properties:
        props[p.key] = None if p.is_null else p.value
    items: list[dict] = []

    if not comp.in_library:
        # BOM-only part: no symbol, no footprint, no KiCad emission.
        items.append(_item("cmp.required_props", "na", "BOM-only part"))
        items.append(_item("cmp.footprint_ref", "na", "BOM-only part"))
    else:
        required = rules.get("required_properties", ["Footprint", "ki_description"])
        missing = [k for k in required if k not in props]
        empty = [k for k in rules.get("non_empty_properties", [])
                 if k in props and props[k] is not None and not str(props[k]).strip()]
        if missing or empty:
            note = "; ".join(filter(None, [
                "missing: " + ", ".join(missing) if missing else "",
                "empty: " + ", ".join(empty) if empty else "",
            ]))
            items.append(_item("cmp.required_props", "failed", note))
        else:
            items.append(_item("cmp.required_props", "checked"))

        fp_value = (props.get("Footprint") or "").strip()
        if not fp_value:
            items.append(_item("cmp.footprint_ref", "failed", "no Footprint property"))
        elif not fp_value.startswith("7Sigma:"):
            items.append(_item("cmp.footprint_ref", "failed",
                               f"{fp_value!r} is not in the 7Sigma: namespace"))
        else:
            fp = db.query(M.Footprint).filter_by(name=fp_value.split(":", 1)[1]).first()
            if fp is None or fp.current_version_id is None:
                items.append(_item("cmp.footprint_ref", "failed",
                                   f"{fp_value!r} has no published footprint"))
            else:
                items.append(_item("cmp.footprint_ref", "checked"))

    lcsc = props.get("LCSC Part")
    pattern = (rules.get("property_patterns") or {}).get("LCSC Part", r"^C\d+$")
    if lcsc is None or "LCSC Part" not in props:
        items.append(_item("cmp.lcsc_format", "na", "no LCSC Part"))
    elif re.match(pattern, str(lcsc)):
        items.append(_item("cmp.lcsc_format", "checked"))
    else:
        items.append(_item("cmp.lcsc_format", "failed",
                           f"LCSC Part {lcsc!r} does not match {pattern}"))

    if not comp.purchasable:
        items.append(_item("cmp.manufacturer", "na", "virtual part — never bought"))
    else:
        mfr_props = rules.get("manufacturer_properties", list(MANUFACTURER_PROPS))
        has_info = any(str(props.get(k) or "").strip() for k in mfr_props)
        any_defined = any(k in props for k in mfr_props)
        if has_info:
            items.append(_item("cmp.manufacturer", "checked"))
        elif any_defined:
            items.append(_item("cmp.manufacturer", "na", "manufacturer fields explicitly null"))
        else:
            items.append(_item("cmp.manufacturer", "failed", "no manufacturer information"))

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
    return items


def validate(db: Session, kind: str, version, comp: M.Component | None = None) -> list[dict]:
    if kind == "footprint":
        return validate_footprint(db, version)
    if kind == "symbol":
        return validate_symbol(db, version)
    return validate_component(db, version, comp)
