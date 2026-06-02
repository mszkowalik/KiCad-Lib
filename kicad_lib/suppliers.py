"""Ensure every component has Supplier 1 and Supplier Part Number 1 properties.

Rule: every component in ``Sources/*.yaml`` must carry both keys. If the
component has an ``LCSC Part`` property, both are filled from it
(``Supplier 1: LCSC``, ``Supplier Part Number 1: <Cxxxx>``). Otherwise the
keys are added with empty values so downstream BOM tooling can rely on them.

Existing non-empty values are preserved; only missing keys or LCSC-derived
fields that disagree with the current ``LCSC Part`` value are touched.
"""

from __future__ import annotations

from pathlib import Path

from kicad_lib import config
from kicad_lib.colors import get_logger
from kicad_lib.yaml.rewriter import load_roundtrip, save_roundtrip

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
        comp.setdefault("properties", []).append({"key": key, "value": value})
        return True
    if (current or "") != value:
        prop["value"] = value
        return True
    return False


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

            _, supplier = _get_prop(comp, SUPPLIER_KEY)
            _, supplier_pn = _get_prop(comp, SUPPLIER_PN_KEY)

            comp_modified = False
            if has_lcsc:
                # Authoritative: derive both from LCSC Part
                if _set_or_add(comp, SUPPLIER_KEY, "LCSC"):
                    comp_modified = True
                if _set_or_add(comp, SUPPLIER_PN_KEY, lcsc):
                    comp_modified = True
            else:
                # No LCSC — just make sure the keys exist (empty if missing,
                # otherwise preserve whatever was entered manually).
                if supplier is None:
                    comp.setdefault("properties", []).append({"key": SUPPLIER_KEY, "value": ""})
                    comp_modified = True
                if supplier_pn is None:
                    comp.setdefault("properties", []).append({"key": SUPPLIER_PN_KEY, "value": ""})
                    comp_modified = True

            if comp_modified:
                modified_count += 1
                file_modified = True

        if file_modified:
            save_roundtrip(ryaml, data, yml)
            log.debug(f"  supplier fields synced in {yml.name}")

    return modified_count
