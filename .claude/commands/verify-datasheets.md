Verify KiCad library components against their PDF datasheets — checking pinouts, footprints, and pin names against manufacturer datasheets.

**Argument:** `$ARGUMENTS` (component name, library name, or 'all')

---

## Prerequisites

### 1. Download and extract datasheets

```bash
source .venv/bin/activate
python download_datasheets.py
```

This creates:
- `Datasheets/<Library>/<ComponentName>.pdf` — cached PDF
- `Datasheets/<Library>/<ComponentName>.txt` — searchable extracted text
- `Datasheets/verification_report.yaml` — checklist for findings

### 2. File layout

```
Datasheets/
  verification_report.yaml
  ICs/
    STM32G031G8U6.txt
    STM32G031G8U6.pdf
  LEDs/
    OSV50603C1E.txt
    ...
Symbols/
  base_library.kicad_sym
Footprints/
  7Sigma.pretty/
Sources/
  *.yaml
```

---

## Verification Report Format

`Datasheets/verification_report.yaml` tracks all findings:

```yaml
- library: ICs
  name: STM32G031G8U6
  manufacturer: ST
  mpn: STM32G031G8U6
  base_symbol: STM32G031G8U6
  footprint: "7Sigma:QFN-28_4x4mm_P0.5mm"
  datasheet_txt: Datasheets/ICs/STM32G031G8U6.txt
  datasheet_url: https://datasheet.lcsc.com/...
  status: pending          # pending | verified | error | skipped
  pinout_ok: null          # true | false | null
  footprint_ok: null       # true | false | null
  notes: ""
```

| Status | Meaning |
|---|---|
| `pending` | Not yet checked |
| `verified` | Checked, everything matches |
| `error` | Checked, mismatches found (details in `notes`) |
| `skipped` | Cannot verify (PDF inaccessible, scanned image, etc.) |

---

## How to Verify a Single Component

### Step 1: Read the datasheet text

Open `Datasheets/<Library>/<ComponentName>.txt`. Search for:
- **Pin assignment table** — keywords: `pin assignment`, `pin description`, `pinout`, `pin configuration`
- **Package drawing** — search for the specific package name (e.g., `UFQFPN28`, `TSSOP20`)
- **Recommended footprint** — search for `footprint`, `land pattern`, `recommended`

### Step 2: Identify the correct package

Check the `footprint` field to determine which package is used. When the datasheet has multiple package columns, use only the column matching the footprint.

| Footprint pattern | Package family |
|---|---|
| `QFN-*` | QFN / UFQFPN / VQFN / DFN |
| `SOIC-*` | SOIC / SOP |
| `SOT-23-*` | SOT-23 variants |
| `TSSOP-*` | TSSOP |
| `LQFP-*` | LQFP |

### Step 3: Read the base symbol pinout

Search `Symbols/base_library.kicad_sym` for the symbol definition:
```
(symbol "STM32G031G8U6"
```

Pins are defined as:
```
(pin unspecified line
    (at -24.13 16.51 0)
    (length 2.54)
    (name "PC14-OSC32IN"
        (effects ...)
    )
    (number "1"
        (effects ...)
    )
)
```

Extract all pins by searching for `(number "` within the symbol block. Each pin has a **number** (physical pad) and **name** (schematic label).

### Step 4: Compare pinout

For each pin in the symbol:
1. **Pin number → Pin name mapping** must correspond to the datasheet for the correct package
2. **Pin name accuracy** — minor formatting differences are acceptable (e.g., `OSC32IN` vs `OSC32_IN`)
3. **Missing pins** — check for exposed/thermal pads, power pins (VDD, VSS); NC pins may be omitted
4. **Extra pins** — symbol should not have pins that don't exist on the physical package

### Step 5: Verify footprint match

1. **Package dimensions** — body size should match footprint name (e.g., 4×4mm for UFQFPN28)
2. **Pin count** — number of pads must match package pin count (including exposed pad)
3. **Pin pitch** — must match datasheet specification

Footprint file: `Footprints/7Sigma.pretty/<footprint_name>.kicad_mod`

### Step 6: Record findings

Update the component entry in `Datasheets/verification_report.yaml`:
- Set `status` to `verified` or `error`
- Set `pinout_ok` and `footprint_ok` to `true` or `false`
- Write specific findings in `notes` (pin numbers and names)

---

## Batch Verification

1. Open `Datasheets/verification_report.yaml`
2. Filter for `status: pending`
3. Process one at a time, save after each
4. Provide a summary of findings at the end

**Priority order** (highest risk of errors first):
1. ICs — complex pinouts, multiple packages
2. Connectors — pin assignments matter for wiring
3. Transistors — pin order (GDS/GSD, BCE/BEC) is critical
4. Diodes — polarity (anode/cathode)
5. LEDs — polarity
6. Other

---

## Common Issues

| Issue | What to check |
|---|---|
| Wrong pin on multi-package IC | Read only the column matching the footprint package |
| Exposed pad missing | QFN/DFN packages often have a thermal pad — check if symbol includes it |
| Pin name formatting | Underscores or brackets are cosmetic, not errors |
| Alternate pin functions | `PA11[PA9]` — both names should appear |
| NC pins omitted | Acceptable to omit, but note it |
| Power pin grouping | Multiple VDD/VSS pins under one symbol pin is intentional |
| Reversed polarity | For diodes/LEDs, verify pin 1 = anode, pin 2 = cathode (or vice versa per convention) |

## Dealing with Problems

- **PDF inaccessible**: Set `status: skipped`
- **Extracted text garbled** (scanned PDF): Set `status: skipped`, note `"Extracted text unreadable (scanned PDF or bad encoding)"`
- **Datasheet covers a family** (e.g., STM32G031x4/x6/x8): Find the column for the specific package used
- **Symbol pin count mismatch**: Record as error with specific pin numbers that are wrong or missing
