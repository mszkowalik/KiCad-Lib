"""Ensure every component has Supplier 1 and Supplier Part Number 1 properties.

Rule: every component in ``Sources/*.yaml`` must carry both keys. If the
component has an ``LCSC Part`` property, both are filled from it
(``Supplier 1: LCSC``, ``Supplier Part Number 1: <Cxxxx>``). Otherwise the
keys are added with empty values so downstream BOM tooling can rely on them.

Existing non-empty values are preserved; only missing keys or LCSC-derived
fields that disagree with the current ``LCSC Part`` value are touched.

When a component has an ``LCSC Part`` but ``Supplier 1`` already names a
*different* supplier (e.g. ``Mouser``), that supplier is not discarded: it is
relocated to the next free ``Supplier N`` / ``Supplier Part Number N`` slot so
that ``Supplier 1`` can become the authoritative LCSC entry.
"""

from __future__ import annotations

from pathlib import Path

from kicad_lib import config
from kicad_lib.colors import get_logger
from kicad_lib.yaml.rewriter import dq, load_roundtrip, save_roundtrip

log = get_logger(__name__)

SUPPLIER_KEY = "Supplier 1"
SUPPLIER_PN_KEY = "Supplier Part Number 1"
LCSC_KEY = "LCSC Part"


def _get_prop(comp: dict, key: str) -> tuple[dict | None, str | None]:
    for p in comp.get("properties", []) or []:
        if p.get("key") == key:
            v = p.get("value")
            return p, (None if v is None else str(v))
    return None, None


def _set_or_add(comp: dict, key: str, value: str) -> bool:
    prop, current = _get_prop(comp, key)
    if prop is None:
        comp.setdefault("properties", []).append({"key": key, "value": dq(value)})
        return True
    if (current or "") != value:
        prop["value"] = dq(value)
        return True
    return False


def _relocate_supplier(comp: dict, supplier: str, supplier_pn: str | None) -> None:
    """Move a non-LCSC supplier out of slot 1 into the next free Supplier slot.

    Finds the lowest ``Supplier N`` (N >= 2) that is missing or empty and writes
    the supplier name and part number there, inserting the pair right after the
    preceding ``Supplier Part Number`` entry to keep the block grouped. If the
    supplier already occupies a higher slot (idempotent re-run), nothing happens.
    """
    n = 2
    while True:
        _, existing = _get_prop(comp, f"Supplier {n}")
        _, existing_pn = _get_prop(comp, f"Supplier Part Number {n}")
        if existing == supplier and (existing_pn or "") == (supplier_pn or ""):
            return  # already relocated here
        if not existing:
            props = comp.setdefault("properties", [])
            anchor = f"Supplier Part Number {n - 1}"
            insert_at = len(props)
            for i, p in enumerate(props):
                if p.get("key") == anchor:
                    insert_at = i + 1
                    break
            props[insert_at:insert_at] = [
                {"key": f"Supplier {n}", "value": dq(supplier)},
                {"key": f"Supplier Part Number {n}", "value": dq(supplier_pn or "")},
            ]
            return
        n += 1


def ensure_supplier_fields(sources_dir: str | Path = config.SOURCES_DIR) -> int:
    """Ensure Supplier 1 and Supplier Part Number 1 exist on every component.

    Returns the number of components modified.
    """
    modified_count = 0

    for yml in sorted(Path(sources_dir).glob("*.yaml")):
        ryaml, data = load_roundtrip(yml)
        file_modified = False
        for comp in data.get("components", []) or []:
            _, lcsc = _get_prop(comp, LCSC_KEY)
            has_lcsc = bool(lcsc and lcsc.startswith("C"))

            supplier_prop, supplier = _get_prop(comp, SUPPLIER_KEY)
            supplier_pn_prop, supplier_pn = _get_prop(comp, SUPPLIER_PN_KEY)

            comp_modified = False
            if has_lcsc:
                # If a different supplier already holds slot 1, preserve it by
                # relocating to the next free slot before LCSC takes slot 1.
                if supplier and supplier != "LCSC":
                    _relocate_supplier(comp, supplier, supplier_pn)
                    comp_modified = True
                # Authoritative: derive both from LCSC Part
                if _set_or_add(comp, SUPPLIER_KEY, "LCSC"):
                    comp_modified = True
                if _set_or_add(comp, SUPPLIER_PN_KEY, lcsc):
                    comp_modified = True
            else:
                # No LCSC — just make sure the keys exist (empty if missing,
                # otherwise preserve whatever was entered manually). Test for
                # key *presence*, not value: an existing key with an empty value
                # must not be re-appended (that produced duplicate keys).
                if supplier_prop is None:
                    comp.setdefault("properties", []).append({"key": SUPPLIER_KEY, "value": dq("")})
                    comp_modified = True
                if supplier_pn_prop is None:
                    comp.setdefault("properties", []).append({"key": SUPPLIER_PN_KEY, "value": dq("")})
                    comp_modified = True

            if comp_modified:
                modified_count += 1
                file_modified = True

        if file_modified:
            save_roundtrip(ryaml, data, yml)
            log.debug(f"  supplier fields synced in {yml.name}")

    return modified_count
