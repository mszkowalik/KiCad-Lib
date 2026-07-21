# Symbol conventions

You **choose** a base symbol for a component; you do not draw or edit symbols.
Every component you draft is built on an existing `base_component` (a graphical
template). You cannot create base symbols or change their pins — that is done
outside the platform.

## Choosing a base symbol

- Find existing base symbols with `list_base_symbols` (it shows each one's pin
  count).
- Pick the template whose **pin count and function** match the part: a two-pin
  passive for a resistor/capacitor, the right pin count for an IC or connector,
  and so on.
- The base symbol's pin count should match the chosen footprint's pad count
  ([[conventions-footprints]]). A mismatch means the wrong template or the wrong
  footprint.

If no suitable base symbol exists, you cannot create one — tell the user what is
missing and stop, rather than forcing a part onto a template that does not fit.

## Pin semantics (reference — for choosing, not editing)

You cannot change pin types, but understanding them helps you judge whether a
template fits. KiCad pin types describe signal direction **from the component's
own point of view**:

- `power_in` — supply/ground the part consumes (VDD, VCC, GND).
- `power_out` — supply the part drives to others (regulator output, a module's
  `SIM_VCC` or `VDD_IO`).
- `input` / `output` — a signal the part only receives / only drives.
- `bidirectional` — GPIO, I²C, USB data, configurable SPI.
- `passive` — no defined direction: RF/antenna, crystal pins, R/C pads.
- `no_connect` — pins the datasheet marks NC / must-not-connect.

A base symbol that already models these correctly for the part's family is the
right one to reuse. If an existing symbol has the wrong directionality for the
part, note it for the user rather than trying to work around it.
