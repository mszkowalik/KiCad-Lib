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
| `Supplier 1` / `Supplier Part Number 1` | See supplier rule below. |
| `LCSC Part` | The `Cxxxxx` number when known. |

Numbered keys (`Manufacturer 2`, `Supplier 2`, …) add further manufacturers or
suppliers when a part has them.

### Description templating

`{Key}` inside a value is replaced by that property's value when the symbol is
generated. Compose `ki_description` from other properties instead of repeating
literals — e.g. `ki_description = "{Value} {Footprint_Name} Capacitor"` renders
as `100nF 0402 Capacitor`. Only reference keys that exist on the same component.

### Supplier rule

When you know the part's `LCSC Part` (a `Cxxxxx`), set `Supplier 1` to `LCSC`
and `Supplier Part Number 1` to that `Cxxxxx`. If a part is primarily sourced
from a different supplier (e.g. Mouser), put that one in `Supplier 1` and let
LCSC fall to `Supplier 2`. The platform normalizes suppliers on save, but set
them correctly so the draft reads right.

## What you must NOT set as properties

- **Prices** — `Price @1 USD`, `Price @100 USD`, `Price @Bulk USD`,
  `Price Bulk Qty`, `Price Source`, `Price Updated` are auto-managed (refreshed
  into their own table from the JLCPCB assembly ladder by default, with the
  LCSC retail ladder as fallback for parts JLC doesn't carry). Never include
  them; the proposal tools reject them.
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
