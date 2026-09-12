# The schematic renderer (`web/src/sim/draw`)

## ONE schematic renderer, everywhere (`src/sim/draw/`)

**Every view that shows a schematic goes through `SchematicView`** — the
project's schematic tab, the simulator overlay and the editor. Do not add a
fourth way to draw a sheet, and do not put a schematic behind an `<img>` again.
One renderer is why those three pages cannot disagree about where a part is or
what colour a wire has.

| File | What it is |
|---|---|
| `draw/types.ts` | the draw document `api/app/services/sch_draw.py` emits |
| `draw/geom.ts` | the placement matrix, arcs, text placement, pin geometry |
| `draw/KicadSheet.tsx` | the sheet as SVG — symbols, wires, labels, sheets, notes |
| `draw/SchematicView.tsx` | fit box, wheel zoom, drag pan, layer slots |

`SchematicView` owns the viewport and nothing else. Callers add what is theirs:
SVG `children` are drawn in the sheet's millimetres, `underlay` goes beneath
the drawing (the editor's grid), and `layers` gets the live viewport for
anything that cannot live inside an SVG — which is the simulator's charge
canvas, and only that.

**The viewport resets on `resetKey`, never on a content change.** An editor
that re-fits the page every time a part is placed moves the circuit out from
under the pointer between two clicks.

**A live run re-renders this page thirty times a second. Two rules follow.**
Both were found by a field that could not be typed into while a run streamed:

- **A text field in the inspector is UNCONTROLLED.** React rewrites a
  controlled input's DOM value on every render, and one of those rewrites
  lands between the keystroke and the change event — the character appears and
  is silently taken back. The field owns its text; the outside value reclaims
  it only when it changes and the field is not focused.
- **Never call `.focus()` from a ref callback.** A ref callback runs on every
  render, so a knob that focused itself took the cursor back off whatever the
  user had moved it to, continuously. Focus follows a CHANGE, once.

**Colours come from `/api/sim/theme`** — the same KiCad theme file kicad-cli
renders with (`api/app/services/themes/`, mirrored byte-identical into
`render/themes/`). Never hard-code a schematic colour, and never add a second
palette for one view. `FALLBACK_THEME` in `draw/types.ts` is that theme's own
values, so a failed fetch looks the same, not different.

The renderer was checked against `kicad-cli sch export svg` side by side on a
real 87-part sheet before it replaced it. Three things it had to be told,
because reasoning about them gave the wrong answer:

- **A field is drawn at its own angle PLUS the symbol's.** R157 (symbol 90,
  field 90) comes out horizontal and D29 (symbol 90, field 0) vertical.
- **A label's justification is already the one for the text AS DRAWN.** Do not
  flip it again for a 180-degree label — that lays every one across its wire.
- **Body lettering is drawn after the fills.** The `&` inside a gate is a
  library text item, and the filled body would cover it.

