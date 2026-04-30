# 7Sigma Symbol Design Rules

All base symbols live in `Symbols/base_library.kicad_sym`. Generated libraries under `Symbols/*.kicad_sym` are pipeline output — never edit them directly.

---

## 1. Pin Types (Directionality)

KiCad pin types communicate signal direction **from the perspective of this component** (what the IC drives or receives). Use the most specific type that is correct — it enables ERC to catch wiring mistakes.

| Type | When to use |
|---|---|
| `power_in` | Pins that consume power: VDD, VCC supply inputs, GND |
| `power_out` | Pins that supply power to other devices: voltage regulator outputs, module-generated VCC for external ICs (e.g. SIM_VCC driven by a cellular module to power the SIM card) |
| `input` | Digital signal this component receives and does not drive |
| `output` | Digital signal this component drives unidirectionally |
| `bidirectional` | Pins that can be either driven or received depending on configuration: GPIO, I2C (open-drain), SPI when master/slave is configurable, USB data lines |
| `passive` | Pins with no defined direction: RF/antenna connections, crystal pins, resistor/capacitor pads |
| `no_connect` | Pins that must not be connected: reserved pads, future-use pads marked NC in the datasheet |
| `open_collector` | Open-drain/open-collector outputs (rare — use `output` if unsure) |
| `open_emitter` | Open-emitter outputs (rare) |

### Direction is always from this component's viewpoint

- A cellular module's `SIM_VCC` is `power_out` because the module drives VCC to the SIM card.
- A microcontroller's `VDDA` pin is `power_in` because the MCU consumes it.
- A USB transceiver's `D+`/`D-` are `bidirectional` because USB alternates direction.
- A UART `TXD` on a module (DCE) is `output` (module transmits); the host `TXD` that connects to it is `input` on the module side.

### V.24 / DCE UART naming convention

Telit (and other cellular module vendors) use ITU-T V.24 circuit designations on UART pins:
- **C103** = "Transmitted Data" from DTE perspective → arrives at module (DCE) → `input`
- **C104** = "Received Data" from DTE perspective → sent by module (DCE) → `output`
- **C105** = "Request to Send" from DTE → received by module → `input`
- **C106** = "Clear to Send" from DCE (module) → driven by module → `output`

### SPI direction policy

When a module's SPI role (master vs. slave) is configurable or unknown, use `bidirectional` for all four SPI pins. If the datasheet guarantees a fixed role, use `input`/`output`:
- SPI slave: MOSI=`input`, MISO=`output`, CLK=`input`, CS=`input`
- SPI master: MOSI=`output`, MISO=`input`, CLK=`output`, CS=`output`

---

## 2. Pin Grouping

Group pins by **functional block**, not by physical pad order or alphabetical name. Within each group, pins are ordered by signal role (e.g., clock before data, enable before data lines).

Standard group order (top to bottom on each side):

**Left side** — power and slow/simple interfaces:
1. Main power supply (VBATT, VCC)
2. Ground (GND) — all GND pins together
3. SIM / external slow interfaces
4. Reserved / NC

**Right side** — host interfaces and control:
1. RF / Antenna
2. USB
3. UART (primary, then auxiliary)
4. SPI
5. I2C
6. GPIO / Analog (ADC)
7. Control & Status (power on/off, shutdown, status outputs)
8. Miscellaneous outputs (LED, VDD_IO)
9. Antenna Tuning Controller (ATC)
10. Reserved / NC

Separate groups with a blank pin-slot gap (one 2.54 mm pitch step).

---

## 3. Box and Layout Geometry

- **Pin pitch**: 2.54 mm
- **Group separator**: one extra 2.54 mm slot (so consecutive group spacing = 5.08 mm)
- **Box margin**: 1.27 mm above the topmost pin and below the bottommost pin
- **Reference label**: 1.27 mm above the box top edge
- **Value label**: 1.27 mm below the box bottom edge
- **Pin indicator circle**: 0.38 mm radius, placed at the pin-1-corner inside the box (typically near VBATT/VCC on left side top)
- **Box width**: set so pin labels don't overlap — ±15.24 mm is standard for multi-peripheral modules

To compute box height:
```
n_slots = total pins on longer side (counting gap slots)
box_half_height = ceil(n_slots / 2) × 2.54 + 1.27 (margin)
first_pin_y = box_half_height - 1.27
```

---

## 4. ERC-Relevant Notes

- **Never leave `passive` on a pin that has a defined direction** — ERC cannot catch misconnections.
- **GND is `power_in`** even though it is often thought of as a return path. KiCad treats GND nets as power and expects them to connect to `power_in` pins on ICs and `power_out` on power symbols (PWR_FLAG, VCC symbols).
- **VDD_IO** (a module-generated IO supply) is `power_out` — it drives other devices' VCC pins.
- `no_connect` pins must have an X marker placed on them in schematics; ERC will warn otherwise.
