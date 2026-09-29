# Library conventions

How components are named and described in the 7Sigma library. These are the
rules to follow when you draft a new component or edit an existing one. You
apply them through `propose_new_component` / `propose_component_edit`, which
create drafts for the user to approve — you never publish.

## Component identity

- **Name** — globally unique, and is normally the **manufacturer part number**
  (e.g. `STM32G031G8U6`, `GRM155R71C104KA88D`). Check it is free with
  `search_components` / `get_component` before proposing a new one.
- **Category** — which library the part belongs to (e.g. `Resistor`,
  `Capacitor`, `Diodes`, `ICs`, `Connectors`). See the live list with
  `list_categories`. Each top-level category becomes one generated
  `.kicad_sym` file, so the category decides where the part shows up in KiCad.
- **Base symbol** — the graphical template the part is built on. Pick an
  existing one whose pin count and function fit the part
  ([[conventions-symbols]]). You cannot create base symbols.

## Properties

A component is a `base_component` plus an ordered list of `{key, value}`
properties. Keep the keys and their **display order** consistent with the other
parts already in the same category — the reliable way to get this right is to
open a similar sibling with `get_component`, copy its property list, and change
the values. Standard keys, in usual order:

| Key | Notes |
|---|---|
| `Value` | The electrical value where it applies (`100nF`, `5K1`, `10µH`). Omit for parts that have no single value (most ICs, connectors). |
| `Footprint` | Always `7Sigma:<name>`, and the footprint must already exist ([[conventions-footprints]]). |
| `Footprint_Name` | Short package tag used in descriptions (`0402`, `SOT-23-5`, `QFN-28`). |
| `ki_description` | Human description. Supports templating — see below. |
| `Manufacturer 1` | Manufacturer name. |
| `Manufacturer Part Number 1` | The MPN (usually equals the component name). |
| `LCSC Part` | The `Cxxxxx` number when known. |

Numbered keys (`Manufacturer 2`, …) add further manufacturers when a part has
them.

### Description templating

`{Key}` inside a value is replaced by that property's value when the symbol is
generated. Compose `ki_description` from other properties instead of repeating
literals — e.g. `ki_description = "{Value} {Footprint_Name} Capacitor"` renders
as `100nF 0402 Capacitor`. Only reference keys that exist on the same component.

### Where the part is bought

Where a part is bought is a supplier LINK, not a property (decision 0055).
`LCSC Part` stays a property, and the JLCPCB and LCSC links follow it. For any
other supplier, call `link_supplier(component, supplier, part_number)` with
that supplier's own order code (Mouser `595-OPA354AIDBVR`, TME `MR-1293.0050`).
The supplier must be in the register (`list_suppliers`); an admin adds new ones.

## What you must NOT set as properties

- **Prices** — `Price @1 USD`, `Price @100 USD`, `Price @Bulk USD`,
  `Price Bulk Qty`, `Price Source`, `Price Updated` live in their own table.
  JLCPCB and LCSC ladders are refreshed by the platform, other suppliers' are
  typed on the component page, and the supplier order picks which one prices
  the part. Never include them; the proposal tools reject them.
- **Suppliers** — `Supplier N` / `Supplier Part Number N`. Use `link_supplier`;
  the proposal tools reject these keys.
- **Datasheets** — do not add a `Datasheet` (or `Datasheet 2`, …) property.
  Pass the URL through the `datasheet_url` argument of `propose_new_component`
  instead; datasheets live in their own table and can have a stored copy.

## Adding from an LCSC number

1. `lcsc_lookup(Cxxxx)` for real manufacturer, MPN, description, package and
   datasheet URL — never guess these.
2. Choose the category, an existing base symbol and an existing footprint that
   match the package and pin count.
3. `get_component` on a similar sibling in the same category and mirror its
   property set and order.
4. `propose_new_component(...)`, then tell the user the draft is awaiting their
   approval in the Proposals view.

If a needed footprint or base symbol does not exist yet, you cannot create it —
tell the user what is missing and stop, rather than inventing a name.
