---
name: kicad-conventions-symbols
description: "Choosing AND authoring base symbols: pin-type directionality from the component's own viewpoint, V.24 UART and SPI role policy, functional pin grouping, box/pitch geometry formulas, and stacked (shorted) pins. Use when picking a base symbol or writing a propose_symbol_edit."
---
<!-- platform-skill: conventions-symbols v6 — source of truth is the platform; check with list_skills, refresh with get_skill -->

# Symbol conventions

Every component is built on a **base symbol** — a graphical template with pins.
You can both *choose* an existing one and *author* a new or revised one:
`propose_symbol_edit(name, source_text, comment)` takes a complete `.kicad_sym`
library text and files it as a draft (existing name = edit, new name = creation),
reviewed with a visual before/after in the Proposals view.

Never hand-write a symbol from scratch when a similar one exists: call
`get_symbol` first, take its `source`, and edit that.

## 1. Choosing a base symbol

- List candidates with `list_base_symbols` (it shows each one's pin count).
- Pick the template whose **pin count and function** match the part: a two-pin
  passive for a resistor/capacitor, the right pin count for an IC or connector.
- The base symbol's pin count should match the chosen footprint's pad count
  ([[conventions-footprints]]). A mismatch means the wrong template or the wrong
  footprint — resolve it before proposing anything.
- Prefer reusing a template over creating one. Create a new base symbol only
  when no existing template has the right pin set; a part forced onto a symbol
  that does not fit produces a wrong netlist, not a cosmetic problem.

## 2. Pin types (directionality)

KiCad pin types describe signal direction **from this component's own point of
view** — what the part drives or receives, not what the board around it does.
Use the most specific type that is correct: it is what lets ERC catch wiring
mistakes.

| Type | When to use |
|---|---|
| `power_in` | Pins that consume power: VDD, VCC supply inputs, **GND** |
| `power_out` | Pins that supply power to other devices: regulator outputs, module-generated rails (a cellular module's `SIM_VCC`, a `VDD_IO`) |
| `input` | A digital signal this component receives and never drives |
| `output` | A digital signal this component drives unidirectionally |
| `bidirectional` | Driven or received depending on configuration: GPIO, I²C (open-drain), USB data lines, SPI when the master/slave role is configurable |
| `passive` | No defined direction: RF/antenna connections, crystal pins, resistor/capacitor pads |
| `no_connect` | Pins that must not be connected: reserved pads, future-use pads marked NC in the datasheet |
| `open_collector` | Open-drain / open-collector outputs (rare — use `output` if unsure) |
| `open_emitter` | Open-emitter outputs (rare) |

Worked examples of "from this component's viewpoint":

- A cellular module's `SIM_VCC` is `power_out` — the module drives VCC into the
  SIM card. It is **not** `passive`.
- An MCU's `VDDA` is `power_in` — the MCU consumes it.
- A USB transceiver's `D+`/`D-` are `bidirectional`.
- A UART `TXD` **on a module** is `output` (the module transmits); the host
  `TXD` arriving at that module is `input` on the module side.

### V.24 / DCE UART naming

Telit and other cellular-module vendors label UART pins with ITU-T V.24 circuit
designations, which are written from the *DTE* (host) perspective — so they
invert when applied to the module symbol:

- **C103** "Transmitted Data" (from DTE) → arrives at the module → `input`
- **C104** "Received Data" (from DTE) → sent by the module → `output`
- **C105** "Request to Send" (from DTE) → received by the module → `input`
- **C106** "Clear to Send" (from DCE) → driven by the module → `output`

### SPI role policy

When a part's SPI role is configurable or the datasheet does not fix it, make
all four SPI pins `bidirectional`. Only when the role is guaranteed:

- SPI slave: MOSI=`input`, MISO=`output`, CLK=`input`, CS=`input`
- SPI master: MOSI=`output`, MISO=`input`, CLK=`output`, CS=`output`

### ERC notes

- **Never leave `passive` on a pin that has a defined direction.** `passive`
  silently defeats ERC — it is the single most common way a symbol looks fine
  and catches nothing.
- **GND is `power_in`**, even though it reads as a return path. KiCad treats
  ground as a power net and expects `power_in` on ICs, `power_out` on power
  symbols (PWR_FLAG, VCC).
- `no_connect` pins need an X marker in the schematic or ERC warns.

## 3. Pin grouping

Group pins by **functional block**, never by pad order or alphabetically.
Within a group, order by signal role (clock before data, enable before data).

**Left side** — power and slow/simple interfaces:
1. Main power supply (VBATT, VCC)
2. Ground — all GND pins together
3. SIM / other slow external interfaces
4. Reserved / NC

**Right side** — host interfaces and control:
1. RF / antenna
2. USB
3. UART (primary, then auxiliary)
4. SPI
5. I²C
6. GPIO / analog (ADC)
7. Control & status (power on/off, shutdown, status outputs)
8. Miscellaneous outputs (LED, VDD_IO)
9. Antenna Tuning Controller (ATC)
10. Reserved / NC

Separate consecutive groups with one blank pin slot (one 2.54 mm step).

## 4. Box and layout geometry

- **Pin pitch**: 2.54 mm
- **Pin stub length**: 2.54 mm (100 mil) by default. This matches KiCad's own
  native default, and every base symbol in the library uses it except the one
  exception below.
- **Exception — very high pin count**: 5.08 mm (200 mil) is permitted only when
  the pin count is large enough that pin-name labels need the extra room to
  stay legible without crowding. Verified precedent: `STM32H573IITxQ` (176
  pins), kept from its original stock drawing, uniform across every pin. Do
  not reach for 200 mil below that scale — `KSZ8864CNX` (64 pins) and
  `RED-BEET-2.0` (40 pins) both hold 100 mil pins cleanly, so pin count alone
  is not the trigger; it takes both a high pin count and long pin-name labels
  before 200 mil is justified.
- **Group separator**: one extra 2.54 mm slot, so spacing across a group
  boundary is 5.08 mm
- **Box margin**: 1.27 mm above the topmost pin and below the bottommost pin
- **Reference label**: 1.27 mm above the box top edge
- **Value label**: 1.27 mm below the box bottom edge
- **Pin-1 indicator**: 0.38 mm radius circle at the pin-1 corner inside the box
  (typically near VBATT/VCC, top of the left side)
- **Box width**: wide enough that pin labels never overlap — ±15.24 mm is the
  house standard for multi-peripheral modules

Box height:

```
n_slots        = pin count on the longer side, counting gap slots
box_half_height = ceil(n_slots / 2) x 2.54 + 1.27   # margin
first_pin_y     = box_half_height - 1.27
```

## 5. Stacked (shorted) pins

KiCad shorts pads **inside the symbol** by stacking pins: two or more pins at
the *identical* `(at x y angle)` with the *same name* form one electrical node.
Make one visible and mark every other `(hide yes)` — the symbol draws one pin,
and the netlist ties all of their pad numbers to the same net.

Two legitimate uses:

1. **Pads that are one net internally** — a MOSFET with several source/drain
   pads, an IC with redundant GND/VDD pads. Draw one visible pin per net and
   stack the duplicates hidden on top. Examples in this library: `CSD17577Q3A`
   (source pads 1/2/3, drain pads 5–9), `LM78L05_SO8`, `ESP32-S3`.
2. **Tying a signal pad to an adjacent datasheet `NC` pad** for a better copper
   shape. An `NC` pad has no internal connection, so shorting it to a signal net
   is electrically safe and gives the layout extra copper. This is a
   **layout-driven decision**: only do it when the board designer asks for that
   specific short, and confirm the pad really is `NC` in the datasheet first.
   Example: `TPD4E05U06`, where pad 10 (datasheet `NC`) is stacked hidden onto
   pad 1 (`D1+`).

Rules for a stacked pin:

- Same `(at …)` coordinates and orientation as the visible pin it stacks onto.
- Same `name` as the visible pin — mismatched names on coincident pins raise an
  ERC warning.
- A pin type compatible with the visible one (usually `passive`). An `NC` pad
  that gets shorted stops being `no_connect` and becomes whatever the net is.
- `(hide yes)` on every pin except the one visible one.

**Approving a symbol version also files the component repoints.** A component
pins the symbol *version* it was drawn against, so the platform opens a draft
component version for every part using this base symbol, pinned to the new
drawing with properties unchanged. Approve those drafts too — the symbol change
is not finished until they land. See [[platform-workflow]].

## 6. Before you propose

- `get_symbol` → edit its `source` → `propose_symbol_edit`. The proposal renders
  a visual before/after; check that the drawing is what you intended.
- Pin count still matches the footprint's pad count ([[conventions-footprints]]).
- Every pin has the most specific correct type from §2 — no lazy `passive`.
- Groups follow §3 and the geometry follows §4.

See [[add-component]] for where symbol choice fits in the full part-creation
procedure, and [[platform-workflow]] for what happens after approval.
