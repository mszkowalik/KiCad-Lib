---
name: verify-datasheets
description: Verify KiCad library components against their PDF datasheets. Use when the user wants to check pinouts, footprints, and pin names against manufacturer datasheets. Works with extracted text files in Datasheets/ and the verification_report.yaml checklist.
argument-hint: "[component name, library name, or 'all']"
---

# Verify Components Against Datasheets

This skill checks that component symbols (pinout, pin names) and footprints match the manufacturer's datasheet. It uses pre-extracted text from PDF datasheets and a central verification report to track progress and findings.

---

## Prerequisites

### 1. Datasheets must be downloaded and extracted

Run the download script first (skip Resistor/Capacitor by default):

```bash
source .venv/bin/activate
python download_datasheets.py
```

This creates:
- `Datasheets/<Library>/<ComponentName>.pdf` — cached PDF
- `Datasheets/<Library>/<ComponentName>.txt` — searchable extracted text
- `Datasheets/verification_report.yaml` — checklist for agent findings

### 2. File layout

```
Datasheets/
  verification_report.yaml          ← agent reads & writes findings here
  ICs/
    STM32G031G8U6.txt               ← extracted datasheet text
    STM32G031G8U6.pdf
  LEDs/
    OSV50603C1E.txt
    OSV50603C1E.pdf
  ...
Symbols/
  base_library.kicad_sym            ← base symbols with pin definitions
Footprints/
  7Sigma.pretty/                    ← footprint files (.kicad_mod)
Sources/
  *.yaml                            ← component YAML definitions
```

---

## Verification Report Format

The file `Datasheets/verification_report.yaml` is the central tracking document. Each component has an entry like:

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
  notes: ""                # free-form findings
```

### Status values

| Status | Meaning |
|---|---|
| `pending` | Not yet checked |
| `verified` | Checked, everything matches |
| `error` | Checked, mismatches found (details in `notes`) |
| `skipped` | Cannot verify (PDF inaccessible, scanned image, etc.) |

### How to update the report

Edit `Datasheets/verification_report.yaml` directly. For each component you verify:

1. Set `status` to `verified` or `error`
2. Set `pinout_ok` to `true` or `false`
3. Set `footprint_ok` to `true` or `false`
4. Write findings in `notes` — be specific about pin numbers and names

Example of a verified component:

```yaml
- library: ICs
  name: STM32G031G8U6
  status: verified
  pinout_ok: true
  footprint_ok: true
  notes: "All 28 pins match datasheet DS12992 Rev 1. Pin names use simplified format (OSC32IN vs OSC32_IN) - cosmetic only."
```

Example of a component with errors:

```yaml
- library: ICs
  name: SomeChip
  status: error
  pinout_ok: false
  footprint_ok: true
  notes: "Pin 7 is labelled PA3 in symbol but datasheet shows PA4. Pin 12 missing from symbol entirely."
```

---

## How to Verify a Single Component

Follow these steps for each component:

### Step 1: Read the datasheet text

Open the extracted text file for the component. The path is in the `datasheet_txt` field of the report entry.

```
Datasheets/<Library>/<ComponentName>.txt
```

The text file is organized by page:

```
============================================================
PAGE 1
============================================================
(page text...)
============================================================
PAGE 2
============================================================
(page text...)
```

**What to search for in the text:**
- **Pin assignment table** — search for keywords: `pin assignment`, `pin description`, `pinout`, `pin configuration`, `pin function`
- **Package drawing** — search for the specific package name (e.g., `UFQFPN28`, `TSSOP20`, `SOT-23`)
- **Recommended footprint** — search for `footprint`, `land pattern`, `recommended`, `solder pad`

### Step 2: Identify the correct package

Components may come in multiple packages. Check the `footprint` field in the report to determine which package is used. Common mappings:

| Footprint pattern | Package family |
|---|---|
| `QFN-*` | QFN / UFQFPN / VQFN / DFN |
| `SOIC-*` | SOIC / SOP |
| `SOT-23-*` | SOT-23 variants |
| `TSSOP-*` | TSSOP |
| `LQFP-*` | LQFP |

When the datasheet has multiple package columns in the pin table, use only the column that matches the footprint.

### Step 3: Read the base symbol pinout

The base symbol is stored in `Symbols/base_library.kicad_sym`. Search for the symbol by name (the `base_symbol` field from the report).

**How to find a symbol's pins in base_library.kicad_sym:**

Search for the symbol definition:
```
(symbol "STM32G031G8U6"
```

Inside the symbol, pins are defined as:
```
(pin unspecified line
    (at -24.13 16.51 0)     ← position (x y rotation)
    (length 2.54)
    (name "PC14-OSC32IN"    ← pin name shown on schematic
        (effects ...)
    )
    (number "1"             ← pin number (matches footprint pad)
        (effects ...)
    )
)
```

**Extract all pins** by searching for `(number "` within the symbol block. Each pin has:
- **number** — the physical pin number (must match footprint pad number)
- **name** — the functional name shown on the schematic

### Step 4: Compare pinout

For each pin in the symbol, verify against the datasheet:

1. **Pin number → Pin name mapping** — The pin number in the symbol must correspond to the same function name in the datasheet for the correct package
2. **Pin name accuracy** — The name should match the datasheet. Minor formatting differences are acceptable (e.g., `OSC32IN` vs `OSC32_IN`, `PA11[PA9]` vs `PA11 [PA9]`)
3. **Missing pins** — Check that the symbol has all pins shown in the datasheet for that package. Pay special attention to:
   - Exposed/thermal pads (often pad 29 on a 28-pin QFN, etc.)
   - Power pins (VDD, VSS, VDDA, VSSA)
   - NC (no-connect) pins — it's acceptable to omit these
4. **Extra pins** — The symbol should not have pins that don't exist on the physical package

### Step 5: Verify footprint match

Check that the footprint referenced in the YAML matches the package described in the datasheet:

1. **Package dimensions** — The datasheet specifies body size (e.g., 4×4mm for UFQFPN28). The footprint name should reflect these dimensions.
2. **Pin count** — The number of pads in the footprint must match the package pin count (including exposed pad if present)
3. **Pin pitch** — The datasheet specifies pad pitch (e.g., 0.5mm). The footprint name should include this.

The footprint file is at:
```
Footprints/7Sigma.pretty/<footprint_name>.kicad_mod
```

Where `<footprint_name>` is the part after `7Sigma:` in the footprint property.

### Step 6: Record findings

Update the component entry in `Datasheets/verification_report.yaml` with your findings.

---

## Batch Verification Workflow

When verifying multiple components:

1. Open `Datasheets/verification_report.yaml`
2. Filter for entries where `status: pending`
3. Process them one at a time following the steps above
4. Save the report after each component (so progress isn't lost)
5. At the end, provide a summary of findings

### Priority order

Verify in this order (highest risk of errors first):
1. **ICs** — complex pinouts, multiple packages
2. **Connectors** — pin assignments matter for wiring
3. **Transistors** — pin order (GDS/GSD, BCE/BEC) is critical
4. **Diodes** — polarity (anode/cathode pin numbers)
5. **LEDs** — polarity
6. **Other** — remaining libraries

---

## Common Issues to Watch For

| Issue | What to check |
|---|---|
| Wrong pin on multi-package IC | Datasheet has columns per package — make sure you read the right column |
| Exposed pad missing from symbol | QFN/DFN packages often have a thermal pad — check if symbol includes it |
| Pin name formatting | Minor differences like underscores or brackets are cosmetic, not errors |
| Alternate pin functions | Some MCUs show alternate names like `PA11[PA9]` — both names should appear |
| NC pins omitted | It's OK to omit NC pins from the symbol, but note it |
| Power pin grouping | Some symbols group multiple VDD/VSS pins under one symbol pin — this is intentional for simpler packages |
| Reversed polarity | For diodes/LEDs, verify pin 1 = anode and pin 2 = cathode (or vice versa depending on convention) |

---

## Dealing with Problems

### PDF was inaccessible

If the `notes` field already says "PDF inaccessible", set `status: skipped`. The user can manually provide the datasheet later.

### Extracted text is garbled

Some PDFs are scanned images or have unusual encoding. If the `.txt` file is unreadable:
1. Set `status: skipped`
2. Write in notes: `"Extracted text unreadable (scanned PDF or bad encoding)"`

### Datasheet doesn't cover this exact part

Some datasheets cover a family (e.g., STM32G031x4/x6/x8). This is normal — the pinout table will have a column for the specific package used. Find the right column.

### Symbol has more/fewer pins than expected

If the symbol pin count doesn't match the datasheet for the given package, this is an error. Record it with the specific pin numbers that are wrong or missing.
