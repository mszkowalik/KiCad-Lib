---
name: kicad-conventions-symbols
description: "Choosing AND authoring base symbols: how to publish one, and the index of every symbol rule with the check that now holds it. The rules themselves live in the symbol checklist — read them with get_review_checklist('symbol'). Use when picking a base symbol or writing a propose_symbol_edit."
---
<!-- platform-skill: conventions-symbols v22 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Symbol conventions

**The rules are checks now, not prose.** Every convention this document used to
state is a checklist item on the symbol base checklist, and the item carries the
data: the pin-type table, the grouping lists, the geometry figures, the three
drawing families with their coordinates, and the stacking decisions. Read them
with `get_review_checklist("symbol")` — once, before you author or verify — and
answer them when you publish.

What is left here is what a check cannot hold: how to publish, and which check
to open for which question.

## Publishing

Every component is built on a **base symbol** — a graphical template with pins.
`propose_symbol_edit(name, source_text, comment)` takes a complete `.kicad_sym`
library text and **publishes it immediately** (existing name = edit, new name =
creation). There is no draft gate. Get it right before you call it.

Never hand-write a symbol when a similar one exists: `get_symbol` first, take
its `source`, edit that.

**Render it before you believe it.** `kicad-cli sym export svg -s <name> -o
<dir> <lib>` draws exactly what KiCad will draw, and `kicad-cli sym upgrade`
proves the file parses. Both have caught real defects that reading the
s-expression did not.

**Publishing files the component repoints.** A component pins the symbol
*version* it was drawn against, so the platform opens a new component version
for every part on this base symbol, pinned to the new drawing with properties
unchanged. See [[platform-workflow]].

**`minor_change` is a waiver, not a convenience.** It carries verifications and
production sign-offs across the changed drawing with your name on it. A moved
pin, a changed unit count and a changed electrical type are all material — pass
`False`. Reserve `True` for cosmetic cleanup that could not alter what a
reviewer checked.

**Renaming** is `rename_base_symbol(name, new_name, comment)`, the same call
shape and the same four consequences as a footprint rename — see
[[conventions-footprints]].

## Choosing one

- `list_base_symbols` lists candidates with each one's pin count.
- Pick the template whose **pin count and function** match the part.
- The pin count should match the chosen footprint's pad count
  ([[conventions-footprints]]). A mismatch means the wrong template or the wrong
  footprint — resolve it before proposing anything.
- Prefer reusing a template over creating one. A part forced onto a symbol that
  does not fit produces a wrong netlist, not a cosmetic problem.

## Where each rule lives

| Question | Check |
|---|---|
| Do the pin numbers and names match the datasheet? | `sym.pinout` |
| Is every pin the most specific correct type, from the part's own viewpoint? Including V.24 UART and SPI roles | `sym.pin_types` |
| Is a datasheet `NC` pad `free` or `no_connect` — and what about straight-through routing? | `sym.nc_pads` |
| Functional grouping or pad order, and did the comment say which? | `sym.pad_order_declared` |
| Are the groups in the right order, with 2.54 mm gaps? | `sym.grouping` |
| Supplies at the top of the left side, grounds at the bottom | `sym.ground_placement` |
| Host logic left, bus pair right, on a two-sided transceiver | `sym.bus_sides` |
| Anything electrical on the top edge? | `sym.top_edge` |
| Box height, margins, label offsets, and the grid law | `sym.geometry` |
| Are all pins on the grid? Do they mix stub lengths? | `sym.pins_grid`, `sym.pin_length` |
| Does a three-character pin number get its 5.08 mm stub? | `sym.stub_length` |
| Is the drawing its family — the 15.24 mm triangle, the 10.16 mm gate, or the box? Glyphs, grid constraints, the angled leader, digital blocks | `sym.drawing_family` |
| Are pin names hidden where the family says so? | `sym.hidden_names` |
| Is the family drawn to the house coordinates — body, pin positions, polarity marks? (automatic) | `sym.family_drawing` |
| Is the `−` on the rail that is actually negative? | `sym.rail_negative_mark` |
| Is an active-low pin drawn with the bubble, not just an overbar? | `sym.inverted_style` |
| Are shorted pins stacked correctly, and does a hidden supply pad have a written reason? | `sym.stacked` |
| Does the drawn topology and polarity match the datasheet? | `sym.topology` |
| Checked against the EasyEDA symbol for the exact LCSC part? | `sym.easyeda_diff` |
| Did a pin number, the pin count or a unit assignment change since the previous version? (automatic) | `sym.pin_numbers_unchanged` |
| Does the simulation pin map still fit? | `sym.sim_link` |

**The triangle families are a table of numbers, and it is measured.**
`sym.family_drawing` compares the body vertices, the pin positions and the
polarity-mark positions against the house coordinates for the 15.24 mm
amplifier and the 10.16 mm one-input gate. It replaced six judgment checks that
asked a reader to compare coordinates by eye and had been answered zero times
between them (audit 2026-09-14). A **multi-input** gate is absent from it: the
house has written down the one-input geometry only, so it refuses to judge
rather than invent a rule. What needs the datasheet stays judgment —
`sym.rail_negative_mark`, `sym.inverting_on_top`, `sym.comparator_glyph`.

**`ki_fp_filters` is retired.** It filtered the footprint chooser, and every
curated path already carries the footprint — the HTTP catalog does not send the
field and a generated component symbol has `Footprint` set. The publish
sanitizer removes it.

## The line runs through the pin

**Never change a pin number.** The number is the netlist. Pin names and
electrical types are fixable toward the datasheet; numbers, count and unit
assignment are not. This is the one rule that stays here as well as on
`sym.pin_numbers_unchanged`, because it governs what you do before any check
runs.

**The check is automatic since 2026-09-14** — it diffs this version's pin
numbers and unit assignments against the previous version's, so a change you
did not intend is a finding rather than something a reviewer has to notice. A
deliberate change, such as splitting one box into gate units, still has to be
answered: say which pins moved and why, or grant a standing exception. Unit 0
means "common to every unit", so moving a shared power pin out of it is a
real change and is counted.

## Simulation

A symbol is what a simulation model attaches to, and the link is keyed on the
symbol rather than the component, so one link covers every part built from this
drawing. **Creating a symbol, or editing one with no link: ask the user whether
to add simulation capability — do not add one unasked.** Everything else about
staleness is on `sym.sim_link`; the standard for the model itself is in
[[conventions-simulation]].

See [[add-component]] for where symbol choice fits in the full part-creation
procedure, and [[platform-workflow]] for what happens after publishing.
