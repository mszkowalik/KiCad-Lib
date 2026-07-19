# Add Component — platform procedure

How to add a new component to the 7Sigma library (web UI or Jaravis). Written for the
platform: no shell, no scripts — everything happens through the web app and Jaravis tools.

## Inputs
Preferred: an LCSC part number (Cxxxxx). Otherwise: manufacturer part number + datasheet.

## Procedure
1. **Check for duplicates** — search by LCSC id AND by manufacturer part number.
   If found, stop and report the existing component instead of adding a duplicate.
2. **Look up metadata** (lcsc_lookup for LCSC parts): manufacturer, MPN, description,
   datasheet URL, package (encapStandard).
3. **Pick the category** — match where similar parts live (chip resistors -> Resistor,
   MLCC -> Capacitor, TVS -> Circuit_Protection or Diodes per the user's placement).
   When genuinely unclear, ask the user instead of guessing.
4. **Pick the base symbol** — must already exist (list_base_symbols): R for resistors,
   C for MLCC, CE for polarized caps, L for inductors, D_* for diodes, Q_* for
   transistors, part-specific symbols for ICs. Never invent a base symbol name.
5. **Pick the footprint** — 7Sigma: namespace only, must already exist (list_footprints).
   Map from the package: 0402 resistor -> 7Sigma:R_0402_1005Metric, 0402 MLCC ->
   7Sigma:C_0402_1005Metric, etc. If the right footprint does not exist, STOP and tell
   the user — importing new footprints is not yet available on the platform.
6. **Build the properties** in the conventional order for the category — copy the shape
   from a similar existing component (get_component on one). Typical order: Value,
   category parameters (Power / Tolerance / Voltage / Dielectric / ...), Footprint,
   Footprint_Name, ki_description (template, e.g. "{Value} {Power} {Tolerance}
   {Footprint_Name}"), Manufacturer 1, Manufacturer Part Number 1, Supplier 1 = LCSC,
   Supplier Part Number 1, LCSC Part.
7. **Never set**: any Price key (prices are auto-managed and refreshed from LCSC), or
   Datasheet as a property (datasheets are managed separately; pass datasheet_url —
   locally stored copies are linked into the library automatically).
8. **Propose** — the new component is created as a DRAFT; the user reviews and approves
   it in the Proposals view. Component name = manufacturer part number, globally unique.

## Conventions
Naming, symbol pin rules and footprint style rules live in the conventions-library,
conventions-symbols and conventions-footprints skills — follow them. ki_description
uses {Property} templates resolved at generation time against sibling properties.
