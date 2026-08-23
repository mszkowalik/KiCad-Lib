"""Review checklists: the seed content, and resolution for a given subject.

A checklist item is ``{key, text, hint?, machine?}``. ``key`` is the stable
identity (check records reference items by key across checklist revisions).
``machine: true`` items are answered automatically by ``services/validator.py``
on every publish; the rest are judgment calls for an agent or a human.

Resolution (`resolve`) merges the base checklist for the subject kind with any
category-scoped checklists on the component's category path. Seeds land once,
on startup, and only for kinds that have no base checklist yet — edits made in
the UI are never overwritten.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models as M

BASE_NAMES = {
    "component": "Component base checklist",
    "symbol": "Symbol base checklist",
    "footprint": "Footprint base checklist",
}

SEED_ITEMS: dict[str, list[dict]] = {
    "footprint": [
        {"key": "fp.parse", "text": "Footprint source parses as a valid .kicad_mod", "machine": True},
        {"key": "fp.courtyard_present", "text": "F.CrtYd courtyard outline is present", "machine": True},
        {"key": "fp.courtyard_width", "text": "Courtyard line width is 0.05 mm", "machine": True},
        {"key": "fp.courtyard_grid", "text": "Courtyard coordinates sit on the 0.1 mm grid",
         "machine": True},
        {"key": "fp.fab_outline", "text": "F.Fab body outline is present", "machine": True},
        {"key": "fp.fab_width", "text": "F.Fab line width is 0.1 mm", "machine": True},
        {"key": "fp.silk_width", "text": "F.SilkS line width is 0.1 mm", "machine": True},
        {"key": "fp.smd_pad_shape", "text": "SMD pads are roundrect (exposed/heatsink pads exempt)",
         "machine": True},
        {"key": "fp.min_drill", "text": "No drill hole below 0.3 mm", "machine": True},
        {"key": "fp.min_th_pad", "text": "No through-hole pad below 0.6 mm", "machine": True},
        {"key": "fp.via_dims", "text": "Via size and drill at or above 0.3 mm (thermal vias warn only)",
         "machine": True},
        {"key": "fp.model3d", "text": "A 3D model is referenced and present in the library "
                                      "(mark n/a only for parts that genuinely need none)",
         "machine": True},
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
        {"key": "sym.parse", "text": "Symbol source parses as a valid .kicad_sym library", "machine": True},
        {"key": "sym.fields", "text": "Reference and Value fields are present", "machine": True},
        {"key": "sym.pins_grid", "text": "All pins sit on the 1.27 mm grid", "machine": True},
        {"key": "sym.pinout", "text": "Pin numbers and names match the datasheet pinout",
         "hint": "Check every pin against the datasheet pinout table, including NC pins."},
        {"key": "sym.pin_types",
         "text": "Pin electrical types are correct from the component's own viewpoint"},
        {"key": "sym.grouping", "text": "Pins are grouped by functional block with 2.54 mm gaps"},
        {"key": "sym.geometry", "text": "Box size and pin pitch follow the geometry formulas"},
        {"key": "sym.stacked", "text": "Shorted pins are stacked per the convention (where applicable)"},
    ],
    "component": [
        {"key": "cmp.required_props", "text": "Footprint and ki_description properties are present",
         "machine": True},
        {"key": "cmp.footprint_ref",
         "text": "Footprint uses the 7Sigma: namespace and exists in the library", "machine": True},
        {"key": "cmp.lcsc_format", "text": "LCSC Part matches C<number>", "machine": True},
        {"key": "cmp.manufacturer", "text": "Manufacturer information is filled in", "machine": True},
        {"key": "cmp.templates", "text": "Every {Key} template reference resolves", "machine": True},
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
                                items=SEED_ITEMS[kind], status="published",
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


def resolve(db: Session, kind: str, category_id: int | None = None) -> dict:
    """The merged checklist for one subject.

    Base checklist for the kind, plus every category-scoped checklist whose
    category sits on the subject's category path (components only — symbols
    and footprints have no category). Later (more specific) items win on a
    key collision.
    """
    base = db.query(M.Checklist).filter_by(subject_kind=kind, category_id=None).first()
    version_id, items = _current_items(base) if base is not None else (None, [])
    merged: dict[str, dict] = {i["key"]: i for i in items}

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
            for item in extra:
                merged[item["key"]] = item

    return {"checklist_version_id": version_id, "items": list(merged.values())}
