# 7Sigma Footprint Styling Rules

All footprints in `Footprints/7Sigma.pretty/` must follow these rules.
The component validator enforces the machine-checkable ones; the rest are convention.

---

## 1. File Header

```
(footprint "FOOTPRINT_NAME"
```

- The internal name **must match the filename** (without `.kicad_mod`).
- **Never** use the `easyeda2kicad:` prefix — KiCad's footprint namespace comes from the `.pretty` folder name (`7Sigma:`), not the file header.
- All property keys and layer names must be **quoted strings** (modern KiCad s-expression format).

---

## 2. Pad Style

| Property | Rule |
|---|---|
| SMD pad type | `roundrect` |
| `roundrect_rratio` | `0.25` |
| Layers | `"F.Cu" "F.Paste" "F.Mask"` (all three) |
| Through-hole pad type | `thru_hole circle` or `thru_hole oval` as appropriate |

Rationale: `roundrect` 0.25 is the IPC-recommended land pattern shape and matches the KiCad standard library. Distinct pad shapes (`oval`, `rect`) are only acceptable when specifically required by the component datasheet land pattern (e.g., fiducials).

### Pad name format

- Integer pads must be stored as integers, not floats: `"1"` not `"1.0"`.

---

## 3. Copper Layers (F.Cu)

- Pad names must map exactly to the KiCad symbol pin numbers — net assignment fails silently when they don't match.

---

## 4. Fab Layer (F.Fab)

| Property | Rule |
|---|---|
| Line width | `0.1 mm` |
| Content | Outline of the **component body** as a closed polygon or rectangle |
| Pin 1 indicator | Small circle (`radius 0.1 mm`) at pin 1 corner, inside the body outline |

Every footprint must have at least one `fp_line` on `F.Fab`. The body outline defines the placement area visible in the PCB editor's fabrication view.

For very dense arrays (≥ 50 pads at ≤ 0.6 mm pitch) a silkscreen outline may be omitted, but `F.Fab` must still be present.

---

## 5. Silkscreen (F.SilkS)

| Property | Rule |
|---|---|
| Line width | `0.1 mm` (uniform for all footprints) |
| Content | Partial body outline that does not overlap pads; pin 1 indicator |
| Pad clearance | Silkscreen must not overlap any pad copper area |

Silkscreen is optional for very fine-pitch packages (≤ 0.4 mm pitch) where it cannot be drawn without pad overlap.

---

## 6. Courtyard (F.CrtYd)

| Property | Rule |
|---|---|
| Line width | `0.05 mm` |
| Clearance | `0.5 mm` from the outermost point of any pad or body feature |
| Grid snap | Round to `0.05 mm` grid |

Every footprint **must** have a complete closed courtyard rectangle. The courtyard prevents component overlap during placement.

---

## 7. 3D Model Path

```
(model "${SEVENSIGMA_DIR}/3DModels/<category>.3dshapes/<NAME>.step"
  (offset (xyz 0 0 0))
  (scale (xyz 1 1 1))
  (rotate (xyz 0 0 0))
)
```

- Always use the `${SEVENSIGMA_DIR}` environment variable — never hardcode paths.
- 3D model files live under `3DModels/` organised by source subdirectory.

---

## 8. EasyEDA Import QA Checklist

When importing from EasyEDA / LCSC (`easyeda2kicad`), verify all of the following before declaring the import complete:

- [ ] Header: `"easyeda2kicad:NAME"` → `"NAME"` (remove prefix)
- [ ] Pads: `oval` or `rect` → `roundrect` with `(roundrect_rratio 0.25)`
- [ ] Pad names: no `.0` suffix (`"1.0"` → `"1"`)
- [ ] `F.Fab` fp_lines present (body outline)
- [ ] `F.CrtYd` fp_lines present (courtyard rectangle)
- [ ] 3D model offset/rotation is correct (easyeda offsets are often wrong)

---

## 9. Native vs Imported Footprints

All footprints are stored in `7Sigma.pretty/` regardless of origin. The style rules apply uniformly. After importing from any source, apply all QA fixes above before committing.

---

## Validation

The component validator (`kicad_lib/kicad/validator.py`) checks:

- `F.CrtYd` present in each referenced footprint file
- `F.Fab` fp_line present in each referenced footprint file
- No `easyeda2kicad:` prefix in the footprint header
- Pad shape is `roundrect` (warned on `oval` or `rect`)
- F.Fab line width is `0.1 mm`
- F.CrtYd line width is `0.05 mm`
- F.SilkS line width is `0.1 mm`

Rules are also documented in the `validation_rules.footprint_style` section of each `Sources/*.yaml`.

### Per-library exemptions

A library YAML may opt specific base components out of the F.Fab and F.CrtYd presence and width rules via `validation_rules.footprint_style.exempt_base_components`. Used for mechanical placeholders (e.g. enclosures) where a body outline and courtyard are not meaningful. Pad-shape, silkscreen-width, and `easyeda2kicad:` prefix rules still apply.
