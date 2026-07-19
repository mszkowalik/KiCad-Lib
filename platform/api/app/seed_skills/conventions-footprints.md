# Footprint conventions

You **choose** footprints; you do not draw them. Your tools let you reference a
footprint that already exists in the library, not create or edit one. Footprint
geometry (pads, courtyard, silkscreen, thermal vias, 3D models) is authored
outside the platform and is not something you can change.

## Choosing a footprint

- Always reference footprints as `7Sigma:<name>`. The `7Sigma:` namespace is
  required, and the `<name>` must already exist — find candidates with
  `list_footprints` (it also shows each footprint's pad count).
- Match the part's **physical package**. Use the package from `lcsc_lookup`
  (e.g. `0402`, `SOT-23-5`, `QFN-28`) to pick the footprint whose name and pad
  count correspond to it.
- The footprint's pad count should match the base symbol's pin count. If they
  disagree, you have the wrong footprint or the wrong base symbol.

## Reading footprint names

Two naming styles coexist; both are fine, just interpret them to pick correctly:

- **Generator style** — `FAMILY-PINS_L<len>-W<wid>-P<pitch>-…-EP`
  (e.g. `VQFN-14_L3.5-W3.5-P0.50-BL-EP`).
- **EasyEDA / KiCad-stock style** —
  `FAMILY-PINS-1EP_<L>x<W>mm_P<pitch>mm_EP<a>x<b>mm`
  (e.g. `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm`).

A `_ThermalVias` (or `-ThermalVias`) suffix means the footprint stitches thermal
vias under the exposed pad — it needs more board area and a different paste
pattern. Pick the variant that matches what the design calls for.

## When nothing fits

If no existing footprint matches the part's package, you cannot add one. Tell
the user which footprint is missing and stop — do not invent a name or reference
one that `list_footprints` does not return (the proposal tools reject references
to footprints that do not exist).
