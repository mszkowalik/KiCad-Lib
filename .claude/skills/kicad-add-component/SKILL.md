---
name: kicad-add-component
description: "Full procedure for adding a part to the 7Sigma library: duplicate check, LCSC metadata lookup, category/base-symbol/footprint selection, property construction, and the per-category validation rules a draft must satisfy. Use when adding, drafting, editing or proposing any component."
---
<!-- platform-skill: add-component v8 — source of truth is the platform; check with list_skills, refresh with get_skill -->

# Add a component

End-to-end procedure for adding a part to the 7Sigma library. Everything lands
as a **draft proposal** — nothing is published until it is approved
([[platform-workflow]]).

**Inputs.** Preferred: an LCSC part number (`Cxxxxx`). Otherwise: manufacturer
part number + datasheet URL.

## Procedure

1. **Check for duplicates.** `search_components` by LCSC id **and** by
   manufacturer part number. If it already exists, stop and report the existing
   component instead of adding a second one.

2. **Look up metadata.** For an LCSC part, `lcsc_lookup(Cxxxxx)` returns
   manufacturer, MPN, description, datasheet URL, LCSC's own category, and the
   package string. Use it — don't retype values from a web page.
   `search_jlc_parts` / `get_jlc_details` cover the JLCPCB assembly catalogue.

   Metadata lookup is all that is automated. There is **no** automated symbol,
   footprint or 3D-model download from EasyEDA/LCSC — geometry is authored, not
   imported (§4, §5).

3. **Pick the category.** Match where similar parts already live (chip resistors
   → `Resistor`, MLCC → `Capacitor`, TVS → `Circuit_Protection` or `Diodes` per
   existing placement). Check LCSC's own category field from step 2 rather than
   inferring from the part-number shape — see the category-placement section of
   [[conventions-library]] for the miscategorisations that keep recurring. When
   genuinely unclear, ask rather than guess.

4. **Pick the base symbol.** `list_base_symbols`: `R` for resistors, `C` for
   MLCC, `CE` for polarized caps, `L` for inductors, `D_*` for diodes, `Q_*` for
   transistors, part-specific symbols for ICs. Never invent a name — the
   proposal is rejected if it doesn't exist. If nothing fits, author one
   ([[conventions-symbols]]).

5. **Pick the footprint.** `list_footprints`, referenced as `7Sigma:<name>`.
   Map from the package in step 2: an 0402 resistor → `7Sigma:R_0402_1005Metric`,
   an 0402 MLCC → `7Sigma:C_0402_1005Metric`. Pad count must match the symbol's
   pin count. If nothing matches the package, author one
   ([[conventions-footprints]]) — don't force the part onto a near-miss.

6. **Build the properties** in the conventional order for the category. The
   reliable way to get this right is to mirror a sibling: `get_component` on an
   existing part in the same category and copy its shape. Typical order:

   `Value`, category parameters (`Power` / `Tolerance` / `Voltage` /
   `Dielectric` / …), `Footprint`, `ki_description`, `Manufacturer 1`,
   `Manufacturer Part Number 1`, `Supplier 1` = `LCSC`,
   `Supplier Part Number 1`, `LCSC Part`.

   **Do not set `Footprint_Name`.** It is the footprint's short package name
   ("0402", "SOT-23-6") and lives on the footprint itself — the generator
   injects it, so `{Footprint_Name}` resolves in `ki_description` without the
   component carrying a copy. If it is missing or wrong, fix it on the
   footprint ([[conventions-footprints]]), not here.

   Naming and description style are in [[conventions-library]] — the
   manufacturer name goes in canonical form (never the raw ALL-CAPS feed value),
   and `ki_description` is a `{Key}` template, not free text.

7. **Never set**: any `Price` key (prices are auto-managed — refreshed from the
   JLCPCB assembly ladder, with LCSC retail as fallback for parts JLC doesn't
   carry), or `Datasheet` as a property. Pass `datasheet_url` to the proposal
   tool instead; archived copies are linked into the library automatically
   ([[verify-datasheets]]).

8. **Propose.** `propose_new_component(name, category, base_component,
   properties_json, datasheet_url, comment)`. The component name is the
   manufacturer part number and must be globally unique. It is created as a
   DRAFT for review in the Proposals view.

   A component draft can reference only **approved** geometry: the tool rejects
   a `base_component` or `Footprint` that exists only as a draft. When new
   geometry was authored for the part (§4, §5), file those proposals first, let
   the user approve them, then file the component proposal. (Verified
   2026-08-12 on STM32H573IIT3Q: `propose_new_component` returned "base
   component not found" while the new symbol was still a draft.)

For an existing part, `propose_component_edit` follows the same property rules.
Before editing a part that may already be placed on a board, check
`component_where_used` to confirm the change is property-only and safe.

## Draft so validation passes

Validation runs server-side against the platform's rule set; you don't run it,
but a draft that breaks these rules comes back with warnings.

- **Required, non-empty properties** — per category. Globally: `Footprint` and
  `ki_description`. Resistors additionally: `Value`, `Power`, `Tolerance`.
  Mirror a sibling with `get_component` rather than guessing which apply.
- **Manufacturer/supplier set** — `Manufacturer 1`, `Manufacturer Part Number 1`,
  `Supplier 1`, `Supplier Part Number 1` are the tracked identity properties.
- **Property patterns** — values must match the category's format:
  - `Value` → `5K1`, `100R`, `4M7` (digits + `R`/`K`/`M` multiplier)
  - `Power` → `63mW`, `0.25W`
  - `Tolerance` → `1%`, `0.1%`
  - `Footprint` → must start `7Sigma:` and the footprint must exist
  - `LCSC Part` → `C` followed by digits
- **Property length** — 200 characters max.
- **Template expressions** — every `{Key}` inside a value (typically in
  `ki_description`) must resolve to another property **on the same component**.
  Resolution is order-independent: a `{Key}` may reference a property defined
  anywhere in the list. An unresolved `{Key}` surfaces as a mirror warning at
  approval time and means the property genuinely isn't there — add it, or for
  `{Footprint_Name}` give the footprint a package name.

When unsure what a category needs, copy the shape from an existing component in
it — never invent a property key.

## Related

[[conventions-library]] — naming, descriptions, category placement.
[[conventions-symbols]] / [[conventions-footprints]] — choosing and authoring geometry.
[[verify-datasheets]] — checking the part against its documentation.
[[platform-workflow]] — what approval does.
