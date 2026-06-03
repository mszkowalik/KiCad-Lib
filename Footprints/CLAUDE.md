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
- [ ] Mechanical holes (unnamed plated pads with `size == drill`, 0 ring) → `np_thru_hole` (see §12)

---

## 9. Footprint Naming

The filename and internal `(footprint "...")` name must match exactly (without `.kicad_mod`). Two conventions live in this library:

- **kicad-footprint-generator style**: `FAMILY-PINS_L<W>-W<W>-P<pitch>-...-EP`
  (e.g. `VQFN-14_L3.5-W3.5-P0.50-BL-EP`)
- **easyeda / KiCad-stock style**: `FAMILY-PINS-1EP_<L>x<W>mm_P<pitch>mm_EP<a>x<b>mm`
  (e.g. `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm`)

Either is acceptable — match the convention already used for the family. Don't rename existing footprints just to harmonise; only adjust when the filename no longer reflects the geometry (e.g. after adding thermal vias).

### Thermal-via suffix

If the footprint includes thermal stitching vias under the exposed pad, the name **must end with `_ThermalVias`** (or `-ThermalVias` if hyphens are already in use as separators in the rest of the name). Examples:

- `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm_ThermalVias`
- `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias`
- `VQFN-14_L3.5-W3.5-P0.50-BL-EP-ThermalVias`

This signals to the schematic author that the footprint will solder-mask differently and consume more board real estate.

---

## 10. Thermal Vias Under Exposed Pads

KiCad has no separate "via" primitive inside footprints — thermal vias are modelled as **thru-hole pads sharing the EP's pad number**. Net inheritance is by pad number (enforced by `(duplicate_pad_numbers_are_jumpers no)`), so the via is automatically on the same net as the exposed-pad land.

### Required pattern

For every thermal via:

```
(pad "<EP_NUMBER>" thru_hole circle
    (at <x> <y>)
    (size 0.6 0.6)
    (drill 0.3)
    (property pad_prop_heatsink)
    (layers "*.Cu")
    (remove_unused_layers no)
)
```

| Attribute | Value | Why |
|---|---|---|
| Pad number | Same as the EP land pad | Net inheritance |
| Annular ring | `size 0.6`, `drill 0.3` (0.15 mm annular ring) | Standard thermal-via stitching geometry |
| `property pad_prop_heatsink` | Required | Flags pad as heat-spreader for DRC and BOM tools |
| `layers "*.Cu"` | All copper layers | Heat dissipation path top-to-bottom |
| `remove_unused_layers no` | Required | Forces annular ring on inner/outer layers even if not used as a signal pad |

### Required companion changes when adding thermal vias

1. **Strip `F.Paste` from the EP land pad** — solder paste over an open via barrel wicks down the hole and starves the joint. The EP pad must use `(layers "F.Cu" "F.Mask")` only.
2. **Add windowed paste apertures** — define unnamed `(pad "" smd roundrect ... (layers "F.Paste"))` blocks that cover ~50–70 % of the EP area, positioned to avoid via barrels. Target 4–9 apertures depending on EP size.
3. **Add back-side land** — duplicate the EP pad on `B.Cu` with `(layers "B.Cu")` and `(zone_connect 2)`, so the via stitches into a back-side copper pour.
4. **Set `(zone_connect 2)` on the EP F.Cu pad** — solid connection to surrounding fill (default would be thermal relief, which defeats the point).
5. **Rename the footprint** with the `_ThermalVias` suffix per §9.
6. **Update all YAML references** in `Sources/*.yaml`.

### Exposed-pad land shape: use `rect`, never `roundrect`

The EP copper land (and its `B.Cu` back-side twin) must be a plain `smd rect`, matching KiCad's stock QFN/DFN exposed pads. **Do not** apply the §2 `roundrect_rratio 0.25` convention to an exposed pad: on a large EP the corner radius becomes large (e.g. 0.25 × 3.3 mm = 0.825 mm) and rounds the EP corners back far enough to **clip the corner thermal vias**, leaving them poking outside the EP copper → DRC annular-ring / isolated-copper errors. Thermal vias sit flush (tangent) to the EP edges by design, so any corner rounding eats into them.

The validator exempts pads carrying `(property pad_prop_heatsink)` from the roundrect rule, so a `rect` EP does not raise a warning. The §2 roundrect rule still applies to every normal signal pad.

### Via grid sizing

Aim for ~1 mm via pitch inside the EP, with at least 0.2 mm clearance from the EP edge to the via copper. A 2 × 2 grid suits EPs up to ~2.5 mm; a 4 × 4 grid suits EPs ~3 mm and larger.

---

## 11. Pad Placement Grid

All pad centers and sizes should be on the **0.1 mm grid**. This makes routing predictable and keeps the BOM/CAM output clean.

Two exceptions:

- **Pitch axis of a fine-pitch package**, where lead positions don't divide evenly by 0.1 mm. Example: a 0.5 mm-pitch package with only 2 leads per side has leads centered at y = ±0.75 mm — snapping to ±0.7 or ±0.8 would misalign the pad with the actual lead. Leave the pitch axis on whatever grid the datasheet dictates.
- **When snapping would move a pad more than 0.1 mm** from its datasheet-correct position. Never sacrifice land-pattern correctness for grid tidiness.

When pad centers are snapped to grid, also round pad sizes to `0.1 × n`. If the across-edge dimension (perpendicular to the package edge) is shifted, prefer moving the pad **outward** (away from body) so the toe of the lead stays fully covered.

For thermal vias (§10), the 1 mm grid spacing falls naturally on 0.1 mm — no exception needed.

---

## 12. Mechanical Holes Must Be NPTH (no zero-ring plated pads)

Mounting holes, locating-peg holes, and body/clearance holes are **mechanical**, not electrical. They must use `np_thru_hole` (non-plated), never `thru_hole`.

A common defect from EasyEDA/LCSC imports: an unnamed plated pad whose copper size equals its drill, e.g.

```
(pad "" thru_hole circle (at ...) (size 1 1) (drill 1) (layers "*.Cu" "*.Mask") ...)
```

This has a **0 mm annular ring** → KiCad DRC raises an "annular ring" / "minimum annular width" violation on every such hole. Plated holes need copper around the barrel; a mechanical hole has none.

**Fix:** change the pad type `thru_hole` → `np_thru_hole`. NPTH pads are exempt from annular-ring DRC (there is no plating to ring). Keep the rest of the pad (size = drill, `(layers "*.Cu" "*.Mask")`) as-is — that matches KiCad's own NPTH mounting-hole footprints. Unnamed pads carry no net, so converting loses nothing electrically.

Rule of thumb: any pad where `(size − drill)/2 ≤ 0` must be `np_thru_hole`. If a hole is genuinely meant to be plated and netted, give it a real annular ring instead (size ≥ drill + 0.3 mm) and a pad number.

Affected footprints fixed under this rule: `SIM-SMD_NANO-SIM-TL6P-H1.35`, `MIC-SMD_5P-L3.5-W2.7-TL_MMICT390200012`, `SMD_BD5.6-D4.1`, `SMD_BD5.6-L5.6-W5.6-D3.6`.

---

## 13. Native vs Imported Footprints

All footprints are stored in `7Sigma.pretty/` regardless of origin. The style rules apply uniformly. After importing from any source, apply all QA fixes above before committing.

---

## Validation

The component validator (`kicad_lib/kicad/validator.py`) checks:

- `F.CrtYd` present in each referenced footprint file
- `F.Fab` fp_line present in each referenced footprint file
- No `easyeda2kicad:` prefix in the footprint header
- Pad shape is `roundrect` (warned on `oval` or `rect`; exposed-pad/heatsink pads with `pad_prop_heatsink` are exempt and must be `rect` — see §10)
- F.Fab line width is `0.1 mm`
- F.CrtYd line width is `0.05 mm`
- F.SilkS line width is `0.1 mm`

Rules are also documented in the `validation_rules.footprint_style` section of each `Sources/*.yaml`.

### Per-library exemptions

A library YAML may opt specific base components out of the F.Fab and F.CrtYd presence and width rules via `validation_rules.footprint_style.exempt_base_components`. Used for mechanical placeholders (e.g. enclosures) where a body outline and courtyard are not meaningful. Pad-shape, silkscreen-width, and `easyeda2kicad:` prefix rules still apply.
