# Naming parts the library does not have yet

Generated from the shipped KiCad 10.0.5 library — **every name in these tables was confirmed
to exist with a per-file `test -f`**. Combined backing: roughly 8,500 stock footprints.

Use this file when you are adding a footprint for a package the library does not contain.
Work top-down: find your family, find the row, take the name verbatim. If no row matches,
follow that family's *How to name a new part* procedure. If the package is absent from KiCad
stock entirely, the house grammar in `01-standard.md` §2 applies.

> Section order: passives → discretes → ICs → arrays & modules → connectors → electromechanical.

---


# SMD chip passives (two-terminal EIA chip packages): resistors, capacitors, inductors, diodes, LEDs, fuses — KiCad 9 stock libraries Resistor_SMD, Capacitor_SMD, Inductor_SMD, Diode_SMD, LED_SMD, Fuse

**Backed by:** 151 files, every one confirmed present by an individual per-file `test -f` (0 missing), and the typed list diffs identical against the directory listing.

Breakdown:
- 75 reflow (default) footprints = 75 shipping family x size combinations across 29 distinct imperial sizes: R 18, C 14, L 12, D 12, LED 10, Fuse 9.
- 75 matching `_Pad<W>x<H>mm_HandSolder` variants — every reflow chip footprint has exactly one, and every HandSolder file has exactly one reflow base. No orphans.
- 1 special-case variant: `LED_1206_3216Metric_ReverseMount_Hole1.8x2.4mm` (the only chip-pattern file in these six libraries carrying a suffix other than `_Pad…_HandSolder`).

Source paths (KiCad 9, macOS): /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/{Resistor_SMD,Capacitor_SMD,Inductor_SMD,Diode_SMD,LED_SMD,Fuse}.pretty

## Grammar

Library nicknames: `Resistor_SMD`, `Capacitor_SMD`, `Inductor_SMD`, `Diode_SMD`, `LED_SMD`, `Fuse` (note: the fuse library is `Fuse`, NOT `Fuse_SMD`).

Filename grammar (identical in all six libraries):

    <Prefix>_<ImperialCode>_<MetricCode>Metric[_Pad<W>x<H>mm_HandSolder]

`<Prefix>` — fixed per family, no exceptions in the chip set:
    R = resistor, C = capacitor, L = inductor, D = diode, LED = LED, Fuse = fuse.

`<ImperialCode>` — 4 digits: 2 digits of body length + 2 digits of body width, each in units of 0.01 inch. The FIRST field is the dimension along the terminal-to-terminal axis (the footprint's X), not necessarily the larger one. One exception: `01005` is 5 characters — a legacy industry code for the 0.4 x 0.2 mm part whose digits do not equal the real dimensions.

`<MetricCode>Metric` — the same two dimensions, same X-then-Y order, in units of 0.1 mm, normally 2 digits each (`1608` = 1.6 x 0.8 mm). Three digits are used for a field >= 10.0 mm (`10251` = 10.2 x 5.1 mm). The literal word `Metric` always follows, so **the number immediately before `Metric` is always the metric code and the number before that is always the imperial code** — that positional rule is what disambiguates the 0402/0603 collision. Two shipped files violate the numeric convention (see pitfalls): `D_2114_3652Metric` (metric field written Y x X) and `C_3640_9110Metric` (second field truncated).

`_Pad<W>x<H>mm_HandSolder` — optional hand-solder variant. `<W>` = pad size along the terminal axis (X), `<H>` = pad size across it (Y), both in mm, always exactly 2 decimal places (`0.30`, `1.75`, `10.45`).

Selection string in a component: `<LibraryNickname>:<Footprint>`, e.g. `Resistor_SMD:R_0603_1608Metric`, `Fuse:Fuse_1206_3216Metric_Pad1.42x1.75mm_HandSolder`.

No `_Reflow`, `_Hand`, `_HandSoldering` or `_Pad…` (without HandSolder) spellings exist in the chip set — the plain name IS the reflow/IPC-nominal footprint.

## Reference table

## Table 1 — Reflow (default, IPC-7351 nominal) footprints

Rows in ascending imperial-code order (`01005` first). Body = measured F.Fab outline of the shipped footprint, X x Y where **X is the terminal-to-terminal axis**. `-` = that family/size does not ship.

| Imperial code | Metric code | Body mm (L×W) | R name | C name | L name | D name | LED name | Fuse name |
|---|---|---|---|---|---|---|---|---|
| 01005 | 0402 | 0.40 × 0.20 | `R_01005_0402Metric` | `C_01005_0402Metric` | `L_01005_0402Metric` | `D_01005_0402Metric` | `LED_01005_0402Metric` | - |
| 0201 | 0603 | 0.60 × 0.30 | `R_0201_0603Metric` | `C_0201_0603Metric` | `L_0201_0603Metric` | `D_0201_0603Metric` | `LED_0201_0603Metric` | - |
| 0402 | 1005 | 1.00 × 0.50 ᵃ | `R_0402_1005Metric` | `C_0402_1005Metric` | `L_0402_1005Metric` | `D_0402_1005Metric` | `LED_0402_1005Metric` | `Fuse_0402_1005Metric` |
| 0504 | 1310 | 1.17 × 1.02 ᵉ | - | `C_0504_1310Metric` | - | - | - | - |
| 0508 † | 1220 | 1.25 × 2.00 | `R_0508_1220Metric` | - | - | - | - | - |
| 0603 | 1608 | 1.60 × 0.80 ᵇ | `R_0603_1608Metric` | `C_0603_1608Metric` | `L_0603_1608Metric` | `D_0603_1608Metric` | `LED_0603_1608Metric` | `Fuse_0603_1608Metric` |
| 0612 † | 1632 | 1.60 × 3.20 | `R_0612_1632Metric` | - | - | - | - | - |
| 0805 | 2012 | 2.00 × 1.25 ᶜ | `R_0805_2012Metric` | `C_0805_2012Metric` | `L_0805_2012Metric` | `D_0805_2012Metric` | `LED_0805_2012Metric` | `Fuse_0805_2012Metric` |
| 0815 † | 2038 | 2.00 × 3.75 | `R_0815_2038Metric` | - | - | - | - | - |
| 1008 | 2520 | 2.50 × 2.00 | - | - | `L_1008_2520Metric` | - | - | - |
| 1020 † | 2550 | 2.50 × 5.00 | `R_1020_2550Metric` | - | - | - | - | - |
| 1206 | 3216 | 3.20 × 1.60 | `R_1206_3216Metric` | `C_1206_3216Metric` | `L_1206_3216Metric` | `D_1206_3216Metric` | `LED_1206_3216Metric` | `Fuse_1206_3216Metric` |
| 1210 | 3225 | 3.20 × 2.50 ᵈ | `R_1210_3225Metric` | `C_1210_3225Metric` | `L_1210_3225Metric` | `D_1210_3225Metric` | `LED_1210_3225Metric` | `Fuse_1210_3225Metric` |
| 1218 † | 3246 | 3.20 × 4.60 | `R_1218_3246Metric` | - | - | - | - | - |
| 1225 † | 3264 | 3.10 × 6.30 ᵉ | `R_1225_3264Metric` | - | - | - | - | - |
| 1806 | 4516 | 4.50 × 1.60 | - | - | `L_1806_4516Metric` | - | - | - |
| 1808 | 4520 | 4.55 × 2.05 | - | `C_1808_4520Metric` | - | - | - | - |
| 1812 | 4532 | 4.50 × 3.20 | `R_1812_4532Metric` | `C_1812_4532Metric` | `L_1812_4532Metric` | `D_1812_4532Metric` | `LED_1812_4532Metric` | `Fuse_1812_4532Metric` |
| 1825 † | 4564 | 4.50 × 6.40 | - | `C_1825_4564Metric` | - | - | - | - |
| 2010 | 5025 | 5.00 × 2.50 | `R_2010_5025Metric` | - | `L_2010_5025Metric` | `D_2010_5025Metric` | `LED_2010_5025Metric` | `Fuse_2010_5025Metric` |
| 2114 | 3652 ‡ | 5.20 × 3.60 | - | - | - | `D_2114_3652Metric` | - | - |
| 2220 | 5750 | 5.70 × 5.00 | - | `C_2220_5750Metric` | - | - | - | - |
| 2225 † | 5664 | 5.72 × 6.35 ᵉ | - | `C_2225_5664Metric` | - | - | - | - |
| 2512 | 6332 | 6.30 × 3.20 | `R_2512_6332Metric` | - | `L_2512_6332Metric` | `D_2512_6332Metric` | `LED_2512_6332Metric` | `Fuse_2512_6332Metric` |
| 2816 | 7142 | 7.10 × 4.20 | `R_2816_7142Metric` | - | - | - | - | - |
| 2920 | 7451 | 7.36 × 5.12 | - | - | - | - | - | `Fuse_2920_7451Metric` |
| 3220 | 8050 | 8.00 × 5.00 | - | - | - | `D_3220_8050Metric` | - | - |
| 3640 † | 9110 ‡ | 9.14 × 10.20 | - | `C_3640_9110Metric` | - | - | - | - |
| 4020 | 10251 | 10.20 × 5.10 | `R_4020_10251Metric` | - | - | - | - | - |

**Legend**

† wide-terminal / reverse-geometry code: the second imperial field is larger, i.e. the terminals sit on the long sides. `0508` is a rotated `0805`, `0612` a rotated `1206`, `1020` a rotated `2010`, etc. — physically much bigger than their position in this sorted list suggests.
‡ metric code does not follow the plain 2+2 rule: `3652` for imperial 2114 is written Y×X (body really 5.2 × 3.6 mm); `9110` for imperial 3640 has a truncated second field (body really 9.14 × 10.2 mm).

Per-family body differences at the same code (measured F.Fab, verified):
ᵃ `R_0402_1005Metric` draws 1.05 × 0.54 mm; the other five families draw 1.00 × 0.50 mm.
ᵇ `R_0603_1608Metric` draws 1.60 × 0.825 mm; the other five draw 1.60 × 0.80 mm.
ᶜ 0805: R and C draw 2.00 × 1.25 mm, D/LED/Fuse draw 2.00 × 1.20 mm, **L draws 2.00 × 0.90 mm**.
ᵈ 1210: `R_1210_3225Metric` draws 3.20 × 2.49 mm, the other five 3.20 × 2.50 mm.
ᵉ drawn body deviates from the metric code by >0.1 mm: 0504 code says 1.3 × 1.0 but draws 1.17 × 1.02; 1225 code says 3.2 × 6.4 but draws 3.10 × 6.30; 2225 code says 5.6 × 6.4 but draws 5.72 × 6.35.

## Table 2 — `_HandSolder` variants (same rows, verbatim)

Every reflow footprint above has exactly one HandSolder counterpart. The `Pad<W>x<H>mm` numbers differ per family even at the same size — copy them, never compute them.

| Imperial code | Metric code | R name | C name | L name | D name | LED name | Fuse name |
|---|---|---|---|---|---|---|---|
| 01005 | 0402 | `R_01005_0402Metric_Pad0.57x0.30mm_HandSolder` | `C_01005_0402Metric_Pad0.57x0.30mm_HandSolder` | `L_01005_0402Metric_Pad0.57x0.30mm_HandSolder` | `D_01005_0402Metric_Pad0.57x0.30mm_HandSolder` | `LED_01005_0402Metric_Pad0.57x0.30mm_HandSolder` | - |
| 0201 | 0603 | `R_0201_0603Metric_Pad0.64x0.40mm_HandSolder` | `C_0201_0603Metric_Pad0.64x0.40mm_HandSolder` | `L_0201_0603Metric_Pad0.64x0.40mm_HandSolder` | `D_0201_0603Metric_Pad0.64x0.40mm_HandSolder` | `LED_0201_0603Metric_Pad0.64x0.40mm_HandSolder` | - |
| 0402 | 1005 | `R_0402_1005Metric_Pad0.72x0.64mm_HandSolder` | `C_0402_1005Metric_Pad0.74x0.62mm_HandSolder` | `L_0402_1005Metric_Pad0.77x0.64mm_HandSolder` | `D_0402_1005Metric_Pad0.77x0.64mm_HandSolder` | `LED_0402_1005Metric_Pad0.77x0.64mm_HandSolder` | `Fuse_0402_1005Metric_Pad0.77x0.64mm_HandSolder` |
| 0504 | 1310 | - | `C_0504_1310Metric_Pad0.83x1.28mm_HandSolder` | - | - | - | - |
| 0508 | 1220 | `R_0508_1220Metric_Pad1.12x2.15mm_HandSolder` | - | - | - | - | - |
| 0603 | 1608 | `R_0603_1608Metric_Pad0.98x0.95mm_HandSolder` | `C_0603_1608Metric_Pad1.08x0.95mm_HandSolder` | `L_0603_1608Metric_Pad1.05x0.95mm_HandSolder` | `D_0603_1608Metric_Pad1.05x0.95mm_HandSolder` | `LED_0603_1608Metric_Pad1.05x0.95mm_HandSolder` | `Fuse_0603_1608Metric_Pad1.05x0.95mm_HandSolder` |
| 0612 | 1632 | `R_0612_1632Metric_Pad1.18x3.40mm_HandSolder` | - | - | - | - | - |
| 0805 | 2012 | `R_0805_2012Metric_Pad1.20x1.40mm_HandSolder` | `C_0805_2012Metric_Pad1.18x1.45mm_HandSolder` | `L_0805_2012Metric_Pad1.05x1.20mm_HandSolder` | `D_0805_2012Metric_Pad1.15x1.40mm_HandSolder` | `LED_0805_2012Metric_Pad1.15x1.40mm_HandSolder` | `Fuse_0805_2012Metric_Pad1.15x1.40mm_HandSolder` |
| 0815 | 2038 | `R_0815_2038Metric_Pad1.20x4.05mm_HandSolder` | - | - | - | - | - |
| 1008 | 2520 | - | - | `L_1008_2520Metric_Pad1.43x2.20mm_HandSolder` | - | - | - |
| 1020 | 2550 | `R_1020_2550Metric_Pad1.33x5.20mm_HandSolder` | - | - | - | - | - |
| 1206 | 3216 | `R_1206_3216Metric_Pad1.30x1.75mm_HandSolder` | `C_1206_3216Metric_Pad1.33x1.80mm_HandSolder` | `L_1206_3216Metric_Pad1.22x1.90mm_HandSolder` | `D_1206_3216Metric_Pad1.42x1.75mm_HandSolder` | `LED_1206_3216Metric_Pad1.42x1.75mm_HandSolder` | `Fuse_1206_3216Metric_Pad1.42x1.75mm_HandSolder` |
| 1210 | 3225 | `R_1210_3225Metric_Pad1.30x2.65mm_HandSolder` | `C_1210_3225Metric_Pad1.33x2.70mm_HandSolder` | `L_1210_3225Metric_Pad1.42x2.65mm_HandSolder` | `D_1210_3225Metric_Pad1.42x2.65mm_HandSolder` | `LED_1210_3225Metric_Pad1.42x2.65mm_HandSolder` | `Fuse_1210_3225Metric_Pad1.42x2.65mm_HandSolder` |
| 1218 | 3246 | `R_1218_3246Metric_Pad1.22x4.75mm_HandSolder` | - | - | - | - | - |
| 1225 | 3264 | `R_1225_3264Metric_Pad1.47x6.45mm_HandSolder` | - | - | - | - | - |
| 1806 | 4516 | - | - | `L_1806_4516Metric_Pad1.45x1.90mm_HandSolder` | - | - | - |
| 1808 | 4520 | - | `C_1808_4520Metric_Pad1.72x2.30mm_HandSolder` | - | - | - | - |
| 1812 | 4532 | `R_1812_4532Metric_Pad1.30x3.40mm_HandSolder` | `C_1812_4532Metric_Pad1.57x3.40mm_HandSolder` | `L_1812_4532Metric_Pad1.30x3.40mm_HandSolder` | `D_1812_4532Metric_Pad1.30x3.40mm_HandSolder` | `LED_1812_4532Metric_Pad1.30x3.40mm_HandSolder` | `Fuse_1812_4532Metric_Pad1.30x3.40mm_HandSolder` |
| 1825 | 4564 | - | `C_1825_4564Metric_Pad1.57x6.80mm_HandSolder` | - | - | - | - |
| 2010 | 5025 | `R_2010_5025Metric_Pad1.40x2.65mm_HandSolder` | - | `L_2010_5025Metric_Pad1.52x2.65mm_HandSolder` | `D_2010_5025Metric_Pad1.52x2.65mm_HandSolder` | `LED_2010_5025Metric_Pad1.52x2.65mm_HandSolder` | `Fuse_2010_5025Metric_Pad1.52x2.65mm_HandSolder` |
| 2114 | 3652 | - | - | - | `D_2114_3652Metric_Pad1.85x3.75mm_HandSolder` | - | - |
| 2220 | 5750 | - | `C_2220_5750Metric_Pad1.97x5.40mm_HandSolder` | - | - | - | - |
| 2225 | 5664 | - | `C_2225_5664Metric_Pad1.80x6.60mm_HandSolder` | - | - | - | - |
| 2512 | 6332 | `R_2512_6332Metric_Pad1.40x3.35mm_HandSolder` | - | `L_2512_6332Metric_Pad1.52x3.35mm_HandSolder` | `D_2512_6332Metric_Pad1.52x3.35mm_HandSolder` | `LED_2512_6332Metric_Pad1.52x3.35mm_HandSolder` | `Fuse_2512_6332Metric_Pad1.52x3.35mm_HandSolder` |
| 2816 | 7142 | `R_2816_7142Metric_Pad3.20x4.45mm_HandSolder` | - | - | - | - | - |
| 2920 | 7451 | - | - | - | - | - | `Fuse_2920_7451Metric_Pad2.10x5.45mm_HandSolder` |
| 3220 | 8050 | - | - | - | `D_3220_8050Metric_Pad2.65x5.15mm_HandSolder` | - | - |
| 3640 | 9110 | - | `C_3640_9110Metric_Pad2.10x10.45mm_HandSolder` | - | - | - | - |
| 4020 | 10251 | `R_4020_10251Metric_Pad1.65x5.30mm_HandSolder` | - | - | - | - | - |

## Table 3 — the one special variant

| Footprint | Library | Notes |
|---|---|---|
| `LED_1206_3216Metric_ReverseMount_Hole1.8x2.4mm` | `LED_SMD` | Reverse-mount 1206 LED: SMD pads 0.95 × 1.75 mm plus an unnumbered NPTH oval `np_thru_hole` 1.8 × 2.4 mm so the LED shines through the board. Has **no** HandSolder counterpart. |

## The `_Pad<W>x<H>mm_HandSolder` convention

- Grammar: reflow name + `_Pad<W>x<H>mm_HandSolder`. `<W>` = pad size along the terminal axis (X), `<H>` = pad size across it (Y), mm, always 2 decimal places.
- Geometrically the HandSolder variant changes **one** thing: the pads are extended **outward** only. Verified on `R_0603_1608Metric` (pads 0.80 × 0.95 at X = ±0.825, inner edge 0.425, courtyard 2.96 × 1.46) vs `R_0603_1608Metric_Pad0.98x0.95mm_HandSolder` (pads 0.975 × 0.95 at X = ±0.9125, inner edge **0.425 — unchanged**, courtyard 3.30 × 1.46). Same again on `C_1206_3216Metric` → `C_1206_3216Metric_Pad1.33x1.80mm_HandSolder`: inner edge stays 0.9 mm, pad grows 0.175 mm outward per side, courtyard 4.60 → 4.96 mm in X only.
- Therefore: pad **Y** size, pad-to-pad inner gap and courtyard height are identical to the reflow variant. HandSolder buys you solder-iron access and fillet room, nothing else. It does not loosen the footprint or make a wrong size fit.
- `<H>` in the filename equals the real pad Y **exactly** in all 75 files.
- `<W>` equals the real pad X exactly in 27 of 75 files. In the other 48 the true pad X ends in `…5` at the third decimal and the name carries a 2-dp rounding that the generator applied **inconsistently**: 0.575 → `0.57`, but 0.635 → `0.64`; 1.125 → `1.12`, but 0.975 → `0.98`; 1.425 → `1.42`, but 1.325 → `1.33`. **You cannot reconstruct a HandSolder filename arithmetically — copy it from the library.**
- Use reflow (plain name) as the default for machine-assembled boards (JLCPCB etc.); reserve HandSolder for prototypes you will actually rework by hand.

## How to name a new part in this family

**Step 1 — get the real body size from the datasheet.** Read the dimensions table (L, W, and the recommended land pattern), in mm. Identify which axis the two terminals are on; call that dimension X. Do not infer the size from a marketing string like "0805 type".

**Step 2 — derive the two codes.**
- Imperial: X in inches x 100 (2 digits) followed by Y in inches x 100 (2 digits). 2.0 x 1.25 mm → 0.079" x 0.049" → `0805`. If Y > X you have a wide-terminal part and the code will look "reversed" (2.0 x 3.75 mm → `0815`) — that is correct, keep the terminal axis first.
- Metric: X in 0.1 mm followed by Y in 0.1 mm, 2 digits each, 3 digits if a field reaches 10.0 mm. 2.0 x 1.25 → `2012`. 10.2 x 5.1 → `10251`.
- The 0.4 x 0.2 mm part is `01005` imperial, not `0402`.

**Step 3 — look the row up in Table 1, then confirm on disk before you write the name anywhere.**
```
ls /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Resistor_SMD.pretty | grep '^R_0805_'
```
Copy the filename verbatim, minus `.kicad_mod`. Do this even when you are sure — the metric field is not always what you computed (`D_2114_3652Metric`, `C_3640_9110Metric`), and HandSolder pad digits are never derivable.

**Step 4 — sanity-check the land pattern.** Open the candidate and compare its pad size and pad centres against the datasheet's recommended land pattern. Stock chip footprints are IPC-7351 *nominal*; if the datasheet's recommended pattern differs by more than ~0.1 mm, the stock footprint is the wrong choice for that part even though the size code matches.

**Step 5 — pick reflow vs HandSolder.** Plain name for production/JLCPCB; `_Pad…_HandSolder` only for boards you will hand-assemble.

**Step 6 — the size ships, but not for your family.** Examples that bite: there is no `C_2010_5025Metric` and no `C_2512_6332Metric`; no `L_1225…`; no `Fuse_0201…`. Options, in order of preference:
1. Diff the land patterns of the sibling family and reuse it deliberately — e.g. a 2010 ceramic cap on `Resistor_SMD:R_2010_5025Metric` (verify both files' pad size and pitch first, and record why in the component's notes). Never rename or copy a stock file to fake the right prefix.
2. Author a house footprint in the `7Sigma:` namespace following `kicad-conventions-footprints`, named with exactly this grammar so it sorts alongside stock: `C_2010_5025Metric` (+ `C_2010_5025Metric_Pad<W>x<H>mm_HandSolder` if you also generate a hand-solder version, with W/H set to the pad sizes you actually drew, 2 dp).

**Step 7 — the package is genuinely absent from KiCad stock** (e.g. `008004` / metric 0201, `0303`, `0505`, `2917`, or anything above `4020`; confirmed absent — `grep` for `008004`, `_0303_`, `_0505_` across Resistor_SMD and Capacitor_SMD returns nothing):
1. Compute both codes per Step 2 from the datasheet.
2. Author the footprint in the `7Sigma:` library using the stock grammar unchanged: `<Prefix>_<Imperial>_<Metric>Metric`. Pads from the datasheet's recommended land pattern, or IPC-7351 nominal if the datasheet gives none. Keep pads on the 0.1 mm grid, F.Fab outline = true body, courtyard per the project footprint rules.
3. Only add a `_Pad<W>x<H>mm_HandSolder` sibling if you actually need it, and set W/H to the drawn pad X/Y to 2 dp — keeping inner pad edges and pad Y identical to the reflow version, extending outward only (that is what stock does).
4. Route it through a `propose_footprint_edit` draft proposal like any other library write — never publish directly.
5. Record the datasheet page you took the land pattern from, so the next person does not have to re-derive it.

## Pitfalls

**1. The 0603 trap (imperial vs metric, same four digits).** `0603` is simultaneously an imperial code (1.6 x 0.8 mm — the everyday 0603) and a metric code (0.6 x 0.3 mm — imperial 0201). Both strings ship in the same directory:
- `R_0603_1608Metric` = 1.6 x 0.8 mm (imperial 0603)
- `R_0201_0603Metric` = 0.6 x 0.3 mm (metric 0603 = imperial 0201)
Resolution rule: **the number directly before the word `Metric` is always the metric code; the number before that is always the imperial code.** A bare "0603" in a BOM, a supplier listing or a Value field is ambiguous — go back to the mm dimensions before you pick a footprint. Asian/JIS datasheets very often quote the metric code with no qualifier.

**2. Same trap for 0402 — and it is worse, because both readings ship in all five main families.**
- `R_0402_1005Metric` / `C_0402_1005Metric` / `L_0402_1005Metric` / `D_0402_1005Metric` / `LED_0402_1005Metric` / `Fuse_0402_1005Metric` = 1.0 x 0.5 mm (imperial 0402)
- `R_01005_0402Metric` / `C_01005_0402Metric` / `L_01005_0402Metric` / `D_01005_0402Metric` / `LED_01005_0402Metric` = 0.4 x 0.2 mm (metric 0402 = imperial 01005)
A "0402 metric" cap is a quarter the length of an "0402" cap.

**3. One-way collisions.** `1005` only ever appears as a metric code (= imperial 0402); there is no imperial 1005 in stock. Same for `1608` (= imperial 0603), `2012` (= imperial 0805), `3216` (= imperial 1206), `3225` (= imperial 1210). So `1206` in a filename is always imperial and `3216` always metric — but only because the metric-1206 part does not ship, not because the codes are safe.

**4. `1008` means two different bodies inside Inductor_SMD.** Verified F.Fab:
- `L_1008_2520Metric` — imperial 1008, body 2.50 x 2.00 mm
- `L_Coilcraft_0403HQ_1008Metric` — metric 1008, body 1.19 x 0.86 mm
Roughly a 6x area difference between two files whose names both contain `1008`.

**5. `D_2114_3652Metric` writes its metric field backwards.** Measured F.Fab body is 5.20 x 3.60 mm (X = terminal axis), i.e. the metric code should have read `5236`. Every other chip file in these six libraries puts X first. Do not use `3652` to conclude the part is 3.6 mm long.

**6. `C_3640_9110Metric` has a truncated metric field.** Measured body 9.14 x 10.20 mm. `9110` naively parses as 9.1 x 1.0 mm, which is wrong by 10x in Y. And `R_4020_10251Metric` uses a 5-digit metric field (`102` + `51`) — any regex assuming exactly 4 digits after the imperial code will miss it.

**7. Wide-terminal / reverse-geometry codes are easy to swap with their rotated twin.** All resistor-only in stock: `R_0508_1220Metric` (1.25 x 2.00) vs `R_0805_2012Metric` (2.00 x 1.25); `R_0612_1632Metric` (1.60 x 3.20) vs `R_1206_3216Metric` (3.20 x 1.60); `R_1020_2550Metric` vs `R_2010_5025Metric`; plus `R_0815_2038Metric`, `R_1218_3246Metric`, `R_1225_3264Metric`. Placing the twin gives a footprint that is mechanically the right area but rotated 90 degrees — pads will not reach the terminals. Also note these sort "small" by imperial code while being physically large: `0508` sits between `0402` and `0603` in the table but is bigger than an `0805`.

**8. Missing cells are real, not oversights.** No capacitor at 2010 or 2512. No resistor at 0504, 1808, 1825, 2220, 2225, 3640. No fuse below 0402 and none at 0201/01005/2010-adjacent oddities beyond the nine listed. Inductor is the only family with 1008 and 1806. Diode is the only family with 2114 and 3220. Fuse is the only family with 2920. If your cell shows `-`, do not assume you mistyped — the family genuinely does not ship that size.

**9. The `Pad<W>x<H>mm` digits are rounded, inconsistently.** 48 of the 75 HandSolder names quote a 2-dp rounding of a pad X that really ends in `…5`, and the rounding direction is not uniform: 0.575 → `0.57` but 0.635 → `0.64`; 1.125 → `1.12` but 0.975 → `0.98`; 1.425 → `1.42` but 1.325 → `1.33`. Never compute a HandSolder filename; copy it. Conversely, never trust the name as an exact pad dimension — open the file if the 0.005 mm matters.

**10. Same code, different bodies per family.** `L_0805_2012Metric` draws a 2.00 x 0.90 mm body; `R_0805_2012Metric` and `C_0805_2012Metric` draw 2.00 x 1.25 mm; `D/LED/Fuse_0805_2012Metric` draw 2.00 x 1.20 mm. Similarly `R_0402_1005Metric` is 1.05 x 0.54 mm while the other five are 1.00 x 0.50 mm. So the code fixes the land pattern family, not the silk/fab body — check F.Fab if you are tight on courtyard or silkscreen clearance.

**11. Codes that drift from the drawn body.** `C_0504_1310Metric` draws 1.17 x 1.02 mm (code implies 1.3 x 1.0); `R_1225_3264Metric` draws 3.10 x 6.30 (code 3.2 x 6.4); `C_2225_5664Metric` draws 5.72 x 6.35 (code 5.6 x 6.4); `C_1808_4520Metric` draws 4.55 x 2.05; `Fuse_2920_7451Metric` draws 7.36 x 5.12. Use the code to find the file, the file to know the geometry.

**12. Manufacturer-specific files whose names contain a chip code are NOT the generic footprint.** Do not let a `grep` hand you `L_Coilcraft_0805HQ_2012Metric`, `L_Coilcraft_0604HQ_1610Metric`, `L_Coilcraft_1008HQ_2520Metric`, `L_Coilcraft_1008HQ_2520Metric_LowProfile`, `L_Coilcraft_0403HQ_1008Metric`, or `L_Taiyo-Yuden_BK_Array_1206_3216Metric` when you asked for a generic chip inductor. Anchor your grep: `grep '^L_0805_'`.

**13. Different grammars for neighbouring families.** Resistor arrays use a bare imperial code and no `Metric` field: `R_Array_Convex_4x0603`, `R_Array_Convex_2x1206`. Tantalum capacitors live in `Capacitor_Tantalum_SMD` with an entirely different scheme — `CP_EIA-<metric>-<height>_<Mfr><CaseLetter>`, e.g. `CP_EIA-1608-08_AVX-J`, `CP_EIA-2012-12_Kemet-R`. The `2012` there is the tantalum EIA metric case code, not an 0805 chip, and the case letter matters. MELF resistors are cylindrical and named by their own code: `R_MELF_MMB-0207`, `R_MiniMELF_MMA-0204`, `R_MicroMELF_MMU-0102` — a MELF is not a chip and has no imperial/metric chip code.

**14. HandSolder is not a fudge factor.** Inner pad edges, pad Y and courtyard Y are byte-identical to the reflow variant. If the reflow footprint is the wrong size, the HandSolder one is equally wrong.

**15. Imperial/metric slippage in conversation.** The metric code is in units of 0.1 mm, the imperial code in units of 0.01 inch — the two field widths look identical (4 digits) but the scales differ by ~2.54x. `1608` (metric, 1.6 x 0.8 mm) and `1608` read as imperial (0.16" x 0.08" = 4.06 x 2.03 mm) differ by 2.5x. Always state units when quoting a size in mm, and never convert an imperial code to mm without noting you did so.


---


# Aluminium electrolytic & tantalum capacitors (SMD + THT) — KiCad 10 stock footprint libraries: Capacitor_SMD.pretty, Capacitor_Tantalum_SMD.pretty, Capacitor_THT.pretty

**Backed by:** Verified by per-file `test -f` against /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/ (all 180 names below confirmed present; 0 missing).

- **SMD aluminium electrolytic — 63 files** in `Capacitor_SMD.pretty` (51 × `CP_Elec_*` + 12 × `C_Elec_*`). Table 1 has **62 rows**: the 63rd file, `CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D`, is a 470 mF CAP-XX supercapacitor, not a can size.
- **SMD tantalum — 56 files**, the entire `Capacitor_Tantalum_SMD.pretty` library = **28 EIA cases × 2 variants** (nominal + `_HandSolder`). Table 2 has 28 rows quoting all 56 verbatim names.
- **THT electrolytic — 131 files** out of 384 total in `Capacitor_THT.pretty`: 42 × `CP_Radial_D*` (28 standard radial + 14 snap-in, of which 7 are `_3pin_SnapIn`), 16 × `CP_Radial_Tantal_*`, 55 × `CP_Axial_*`, 18 × `C_Radial_*`. The 28 × `C_Axial_*` files are film (Styroflex) per their `descr`, not electrolytic, so they are excluded.

## Grammar

SMD ALUMINIUM ELECTROLYTIC CAN — Capacitor_SMD.pretty
  <POL>_Elec_<D>x<H>[_<Manufacturer>]
    <POL>  = "CP" (polarised) | "C" (non-polar / bipolar)
    <D>    = CAN DIAMETER in mm, minimal decimals — strip a trailing ".0"
             stock values: 3  4  5  6.3  8  10  16  18
    <H>    = MAX SEATED HEIGHT in mm, minimal decimals — strip a trailing ".0"
             stock values run 3 .. 22, mostly one decimal place
    separator is a literal lowercase "x"
    NO "mm" suffix, NO "_H" token, NO pitch token, NO "D"/"H" letters
    [_<Manufacturer>] only to disambiguate two different land patterns for the
             same D x H (exactly one occurrence in stock)

SMD TANTALUM MOLDED CHIP — Capacitor_Tantalum_SMD.pretty
  CP_EIA-<LLWW>-<HH>_<Vendor>-<Letter>[_HandSolder]
    <LLWW>  = 4 digits: body LENGTH then WIDTH, each in units of 0.1 mm
              (3216 -> 3.2 x 1.6 mm)
    <HH>    = MAXIMUM body height in units of 0.1 mm (18 -> 1.8 mm max)
              [exactly one stock file carries 3 digits here: 438]
    <Vendor> = "Kemet" | "AVX"   (literal, capitalised exactly so)
    <Letter> = that vendor's own case letter, one uppercase character
    joined to <Vendor> by a HYPHEN, attached to <HH> by an UNDERSCORE
    [_HandSolder] = enlarged-pad hand-solder variant; every one of the 28 cases
              has exactly one, spelt "_HandSolder" (no underscore inside)
    note the prefix is CP_EIA- , NOT CP_Tantalum_EIA-

THT ELECTROLYTIC, RADIAL CAN — Capacitor_THT.pretty
  CP_Radial_D<d>mm_P<p>mm[_P<p2>mm][_3pin][_SnapIn]
    <d>   = can diameter, ALWAYS exactly ONE decimal place  -> D4.0mm D6.3mm D12.5mm D40.0mm
    <p>   = lead pitch,   ALWAYS exactly TWO decimal places -> P1.50mm P2.50mm P10.00mm
    NO height token anywhere (0 of 42 stock files carry one)
    _P<p2>mm = optional second, larger hole pair; the two P tokens ascend
    _3pin always precedes _SnapIn

THT TANTALUM, RADIAL — Capacitor_THT.pretty
  CP_Radial_Tantal_D<d>mm_P<p>mm
    literal token is "Tantal", NOT "Tantalum"
    same decimal rules: D one decimal, P two decimals

THT ELECTROLYTIC, AXIAL CAN — Capacitor_THT.pretty
  CP_Axial_L<l>mm_D<d>mm_P<p>mm_Horizontal
    <l> = body length, ONE decimal;  <d> = diameter, ONE decimal
    <p> = lead-hole pitch, TWO decimals
    _Horizontal is mandatory (all 55 stock files end with it; no vertical variant exists)

THT NON-POLAR ELECTROLYTIC, RADIAL — Capacitor_THT.pretty
  C_Radial_D<d>mm_H<h>mm_P<p>mm
    this family DOES carry a height token (18 of 18 stock files)
    <d> and <h> ONE decimal;  <p> TWO decimals

## Reference table

## Table 1 — Every stock SMD aluminium electrolytic can size (62 rows, 63 files)

**The token pair after `_Elec_` is `DIAMETER x HEIGHT`** — can diameter first, seated height second. It is *not* length × width. So `CP_Elec_10x10.5` is a Ø10.0 mm can that stands 10.5 mm tall.

**Heights carry decimals.** Most heights are non-integer (`10.5`, `12.6`, `14.3`, `5.4`, `6.9`, `11.9`) because they are real datasheet maxima. Integer values are written with **no** trailing `.0` (`CP_Elec_8x10`, `CP_Elec_4x3`, `CP_Elec_16x22`), and diameters follow the same rule (`8` not `8.0`, but `6.3` keeps its decimal). There is no `mm` suffix and no `H` letter anywhere in these names.

Sorted by diameter, then height. `CP_` = polarised, `C_` = non-polar. Vendor column is quoted from each file's own `(descr ...)`.

| # | Footprint name (verbatim) | Ø mm | Height mm | Polarised? | Vendor per `descr` |
|---:|---|---:|---:|:---:|---|
| 1 | `CP_Elec_3x5.3` | 3.0 | 5.3 | Yes | Cornell Dubilier Electronics |
| 2 | `CP_Elec_3x5.4` | 3.0 | 5.4 | Yes | Nichicon |
| 3 | `C_Elec_3x5.4` | 3.0 | 5.4 | **No** | (nonpolar, unattributed) |
| 4 | `CP_Elec_4x3` | 4.0 | 3.0 | Yes | Nichicon |
| 5 | `CP_Elec_4x3.9` | 4.0 | 3.9 | Yes | Nichicon |
| 6 | `CP_Elec_4x4.5` | 4.0 | 4.5 | Yes | Nichicon |
| 7 | `CP_Elec_4x5.3` | 4.0 | 5.3 | Yes | Vishay |
| 8 | `CP_Elec_4x5.4` | 4.0 | 5.4 | Yes | Panasonic A5 / Nichicon |
| 9 | `C_Elec_4x5.4` | 4.0 | 5.4 | **No** | (nonpolar, unattributed) |
| 10 | `CP_Elec_4x5.7` | 4.0 | 5.7 | Yes | United Chemi-Con |
| 11 | `CP_Elec_4x5.8` | 4.0 | 5.8 | Yes | Panasonic |
| 12 | `C_Elec_4x5.8` | 4.0 | 5.8 | **No** | (nonpolar, unattributed) |
| 13 | `CP_Elec_5x3` | 5.0 | 3.0 | Yes | Nichicon |
| 14 | `CP_Elec_5x3.9` | 5.0 | 3.9 | Yes | Nichicon |
| 15 | `CP_Elec_5x4.4` | 5.0 | 4.4 | Yes | Panasonic B45 |
| 16 | `CP_Elec_5x4.5` | 5.0 | 4.5 | Yes | Nichicon |
| 17 | `CP_Elec_5x5.3` | 5.0 | 5.3 | Yes | Nichicon |
| 18 | `CP_Elec_5x5.4` | 5.0 | 5.4 | Yes | Nichicon |
| 19 | `C_Elec_5x5.4` | 5.0 | 5.4 | **No** | (nonpolar, unattributed) |
| 20 | `CP_Elec_5x5.7` | 5.0 | 5.7 | Yes | United Chemi-Con |
| 21 | `CP_Elec_5x5.8` | 5.0 | 5.8 | Yes | Panasonic |
| 22 | `C_Elec_5x5.8` | 5.0 | 5.8 | **No** | (nonpolar, unattributed) |
| 23 | `CP_Elec_5x5.9` | 5.0 | 5.9 | Yes | Panasonic B6 |
| 24 | `CP_Elec_6.3x3` | 6.3 | 3.0 | Yes | Nichicon |
| 25 | `CP_Elec_6.3x3.9` | 6.3 | 3.9 | Yes | Nichicon |
| 26 | `CP_Elec_6.3x4.5` | 6.3 | 4.5 | Yes | Nichicon |
| 27 | `CP_Elec_6.3x4.9` | 6.3 | 4.9 | Yes | Panasonic C5 |
| 28 | `CP_Elec_6.3x5.2` | 6.3 | 5.2 | Yes | United Chemi-Con |
| 29 | `CP_Elec_6.3x5.3` | 6.3 | 5.3 | Yes | Cornell Dubilier |
| 30 | `CP_Elec_6.3x5.4` | 6.3 | 5.4 | Yes | Panasonic C55 |
| 31 | `CP_Elec_6.3x5.4_Nichicon` | 6.3 | 5.4 | Yes | Nichicon |
| 32 | `C_Elec_6.3x5.4` | 6.3 | 5.4 | **No** | (nonpolar, unattributed) |
| 33 | `CP_Elec_6.3x5.7` | 6.3 | 5.7 | Yes | United Chemi-Con |
| 34 | `CP_Elec_6.3x5.8` | 6.3 | 5.8 | Yes | Nichicon |
| 35 | `C_Elec_6.3x5.8` | 6.3 | 5.8 | **No** | (nonpolar, unattributed) |
| 36 | `CP_Elec_6.3x5.9` | 6.3 | 5.9 | Yes | Panasonic C6 |
| 37 | `CP_Elec_6.3x7.7` | 6.3 | 7.7 | Yes | Nichicon |
| 38 | `C_Elec_6.3x7.7` | 6.3 | 7.7 | **No** | (nonpolar, unattributed) |
| 39 | `CP_Elec_6.3x9.9` | 6.3 | 9.9 | Yes | Panasonic C10 |
| 40 | `CP_Elec_8x5.4` | 8.0 | 5.4 | Yes | Nichicon |
| 41 | `C_Elec_8x5.4` | 8.0 | 5.4 | **No** | (nonpolar, unattributed) |
| 42 | `CP_Elec_8x6.2` | 8.0 | 6.2 | Yes | Nichicon |
| 43 | `C_Elec_8x6.2` | 8.0 | 6.2 | **No** | (nonpolar, unattributed) |
| 44 | `CP_Elec_8x6.5` | 8.0 | 6.5 | Yes | Rubycon |
| 45 | `CP_Elec_8x6.7` | 8.0 | 6.7 | Yes | United Chemi-Con |
| 46 | `CP_Elec_8x6.9` | 8.0 | 6.9 | Yes | Panasonic E7 |
| 47 | `CP_Elec_8x10` | 8.0 | 10.0 | Yes | Nichicon |
| 48 | `C_Elec_8x10.2` | 8.0 | 10.2 | **No** | (nonpolar, unattributed) |
| 49 | `CP_Elec_8x10.5` | 8.0 | 10.5 | Yes | Vishay 0810 |
| 50 | `CP_Elec_8x11.9` | 8.0 | 11.9 | Yes | Panasonic E12 |
| 51 | `CP_Elec_10x7.7` | 10.0 | 7.7 | Yes | Nichicon |
| 52 | `CP_Elec_10x7.9` | 10.0 | 7.9 | Yes | Panasonic F8 |
| 53 | `CP_Elec_10x10` | 10.0 | 10.0 | Yes | Nichicon |
| 54 | `C_Elec_10x10.2` | 10.0 | 10.2 | **No** | (nonpolar, unattributed) |
| 55 | `CP_Elec_10x10.5` | 10.0 | 10.5 | Yes | Vishay 1010 |
| 56 | `CP_Elec_10x12.5` | 10.0 | 12.5 | Yes | Vishay 1012 |
| 57 | `CP_Elec_10x12.6` | 10.0 | 12.6 | Yes | Panasonic F12 |
| 58 | `CP_Elec_10x14.3` | 10.0 | 14.3 | Yes | Vishay 1014 |
| 59 | `CP_Elec_16x17.5` | 16.0 | 17.5 | Yes | Vishay 1616 |
| 60 | `CP_Elec_16x22` | 16.0 | 22.0 | Yes | Vishay 1621 |
| 61 | `CP_Elec_18x17.5` | 18.0 | 17.5 | Yes | Vishay 1816 |
| 62 | `CP_Elec_18x22` | 18.0 | 22.0 | Yes | Vishay 1821 |

Not a can size, but present in the same `CP_Elec_` namespace: `CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D` (470 mF / 5.5 V CAP-XX supercapacitor). Exclude it when enumerating cans.

Non-polar coverage is thin: `C_Elec_*` exists only at Ø3, 4, 5, 6.3, 8 and 10 — there is **no** non-polar equivalent at Ø16 or Ø18.

---

## Table 2 — Every stock SMD tantalum EIA case (28 cases, 56 files)

Body **L × W** is measured from each footprint's own `F.Fab` outline (the library's authoritative body rectangle). Body **H** and the imperial codes are cross-referenced to vendor primaries — see the confidence markers.

| Footprint (verbatim) | HandSolder twin (verbatim) | EIA metric | EIA imperial | Case letter | Body L×W×H nom. (mm) | Max H per code (mm) |
|---|---|---|---|---|---|---:|
| `CP_EIA-1608-08_AVX-J` | `CP_EIA-1608-08_AVX-J_HandSolder` | 1608-08 | 0603 † | J (AVX) | 1.60 × 0.85 × ≤0.80 | 0.80 |
| `CP_EIA-1608-10_AVX-L` | `CP_EIA-1608-10_AVX-L_HandSolder` | 1608-10 | 0603 † | L (AVX) | 1.60 × 0.85 × ≤1.00 | 1.00 |
| `CP_EIA-2012-12_Kemet-R` | `CP_EIA-2012-12_Kemet-R_HandSolder` | 2012-12 | 0805 ‡ | R (Kemet; AVX also R) | 2.00 × 1.25 × 1.20 | 1.20 |
| `CP_EIA-2012-15_AVX-P` | `CP_EIA-2012-15_AVX-P_HandSolder` | 2012-15 | 0805 ‡ | P (AVX) | 2.00 × 1.25 × 1.50 | 1.50 |
| `CP_EIA-3216-10_Kemet-I` | `CP_EIA-3216-10_Kemet-I_HandSolder` | 3216-10 | 1206 ‡ | I (Kemet) — **AVX calls this K** | 3.20 × 1.60 × 1.00 | 1.00 |
| `CP_EIA-3216-12_Kemet-S` | `CP_EIA-3216-12_Kemet-S_HandSolder` | 3216-12 | 1206 ‡ | S (Kemet; AVX also S) | 3.20 × 1.60 × 1.20 | 1.20 |
| `CP_EIA-3216-18_Kemet-A` | `CP_EIA-3216-18_Kemet-A_HandSolder` | 3216-18 | 1206 ‡ | A (universal) | 3.20 × 1.60 × 1.60 | 1.80 |
| `CP_EIA-3528-12_Kemet-T` | `CP_EIA-3528-12_Kemet-T_HandSolder` | 3528-12 | 1210 ‡ | T (Kemet; AVX also T) | 3.50 × 2.80 × 1.20 | 1.20 |
| `CP_EIA-3528-15_AVX-H` | `CP_EIA-3528-15_AVX-H_HandSolder` | 3528-15 | 1210 ‡ | H (AVX) | 3.50 × 2.80 × 1.50 | 1.50 |
| `CP_EIA-3528-21_Kemet-B` | `CP_EIA-3528-21_Kemet-B_HandSolder` | 3528-21 | 1210 ‡ | B (universal) | 3.50 × 2.80 × 1.90 | 2.10 |
| `CP_EIA-6032-15_Kemet-U` | `CP_EIA-6032-15_Kemet-U_HandSolder` | 6032-15 | 2312 ‡ | U (Kemet) — **AVX calls this W** | 6.00 × 3.20 × 1.50 | 1.50 |
| `CP_EIA-6032-20_AVX-F` | `CP_EIA-6032-20_AVX-F_HandSolder` | 6032-20 | 2312 ‡ | F (AVX) | 6.00 × 3.20 × 2.00 | 2.00 |
| `CP_EIA-6032-28_Kemet-C` | `CP_EIA-6032-28_Kemet-C_HandSolder` | 6032-28 | 2312 ‡ | C (universal) | 6.00 × 3.20 × 2.60 | 2.80 |
| `CP_EIA-7132-20_AVX-U` | `CP_EIA-7132-20_AVX-U_HandSolder` | 7132-20 | *(none published — unverified)* | U (AVX multianode) | 7.10 × 3.20 × ≤2.00 | 2.00 |
| `CP_EIA-7132-28_AVX-C` | `CP_EIA-7132-28_AVX-C_HandSolder` | 7132-28 | *(none published — unverified)* | C (AVX multianode) | 7.10 × 3.20 × ≤2.80 | 2.80 |
| `CP_EIA-7260-15_AVX-R` | `CP_EIA-7260-15_AVX-R_HandSolder` | 7260-15 | *(none published — unverified)* | R (AVX multianode) | 7.20 × 6.00 × ≤1.50 | 1.50 |
| `CP_EIA-7260-20_AVX-M` | `CP_EIA-7260-20_AVX-M_HandSolder` | 7260-20 | *(none published — unverified)* | M (AVX multianode) | 7.20 × 6.00 × ≤2.00 | 2.00 |
| `CP_EIA-7260-28_AVX-M` | `CP_EIA-7260-28_AVX-M_HandSolder` | 7260-28 | *(none published — unverified)* | M (AVX multianode) | 7.20 × 6.00 × ≤2.80 | 2.80 |
| `CP_EIA-7260-38_AVX-R` | `CP_EIA-7260-38_AVX-R_HandSolder` | 7260-38 | *(none published — unverified)* | R (AVX multianode) | 7.20 × 6.00 × ≤3.80 | 3.80 |
| `CP_EIA-7343-15_Kemet-W` | `CP_EIA-7343-15_Kemet-W_HandSolder` | 7343-15 | 2917 ‡ | W (Kemet) — **AVX calls this X** | 7.30 × 4.30 × 1.50 | 1.50 |
| `CP_EIA-7343-20_Kemet-V` | `CP_EIA-7343-20_Kemet-V_HandSolder` | 7343-20 | 2917 ‡ | V (Kemet) — **AVX calls this Y** | 7.30 × 4.30 × 2.00 | 2.00 |
| `CP_EIA-7343-30_AVX-N` | `CP_EIA-7343-30_AVX-N_HandSolder` | 7343-30 | 2917 ‡ | N (AVX) | 7.30 × 4.30 × ≤3.00 | 3.00 |
| `CP_EIA-7343-31_Kemet-D` | `CP_EIA-7343-31_Kemet-D_HandSolder` | 7343-31 | 2917 ‡ | D (universal) | 7.30 × 4.30 × 2.90 | 3.10 |
| `CP_EIA-7343-40_Kemet-Y` | `CP_EIA-7343-40_Kemet-Y_HandSolder` | 7343-40 | 2917 ‡ | Y (Kemet) | 7.30 × 4.30 × ≤4.00 | 4.00 |
| `CP_EIA-7343-43_Kemet-X` | `CP_EIA-7343-43_Kemet-X_HandSolder` | 7343-43 | 2917 ‡ | X (Kemet) — **AVX calls this E** | 7.30 × 4.30 × 4.10 | 4.30 |
| `CP_EIA-7360-38_Kemet-E` | `CP_EIA-7360-38_Kemet-E_HandSolder` | 7360-38 | 2924 *(unverified)* | E (Kemet) | 7.30 × 6.00 × ≤3.80 | 3.80 |
| `CP_EIA-7361-38_AVX-V` | `CP_EIA-7361-38_AVX-V_HandSolder` | 7361-38 | 2924 ‡ | V (AVX) | 7.30 × 6.10 × 3.55 | 3.75 (code says 38) |
| `CP_EIA-7361-438_AVX-U` | `CP_EIA-7361-438_AVX-U_HandSolder` | 7361-**438** | 2924 ‡ | U (AVX) | 7.30 × 6.10 × 4.10 | 4.30 — **AVX publishes this case as `7361-43`** |

**Vendor token used:** the field after the height code is always `Kemet` or `AVX` followed by a hyphen and that vendor's case letter. In stock: **13 cases use `Kemet-`** (R, I, S, A, T, B, U, C, W, V, D, Y, X, E — 14 letters across 14 files… counted as files: 2012-12, 3216-10, 3216-12, 3216-18, 3528-12, 3528-21, 6032-15, 6032-28, 7343-15, 7343-20, 7343-31, 7343-40, 7343-43, 7360-38 = 14) and **14 cases use `AVX-`** (J, L, P, H, F, U, C, R, M, M, R, N, V, U = 1608-08, 1608-10, 2012-15, 3528-15, 6032-20, 7132-20, 7132-28, 7260-15, 7260-20, 7260-28, 7260-38, 7343-30, 7361-38, 7361-438 = 14). Total 28.

Confidence markers:
- **‡** verified from the KYOCERA AVX **TAJ Series** datasheet (`TDS-PTNO-0024 Rev 3`), "STANDARD CASE DIMENSIONS" and "LOW PROFILE CASE DIMENSIONS" tables, which list EIA imperial code, EIA metric code, and L/W/H in mm side by side.
- **†** verified from Vishay `MS11188552-1903` ("EIA-717 Sets the Standard"), which states the **J (0603)** and **P (0805)** case sizes.
- ***(unverified)*** no primary source found in this pass. The 7132 / 7260 multianode cases have no imperial designation I could confirm; the 7360→2924 mapping is inferred from 7361→2924 and is **not** verified.
- Bodies with `≤` in the H column: the nominal height is not published in a source I read, so the value shown is the maximum implied by the height code.

---

## Table 3 — THT electrolytic grammar, with verbatim examples

### 3a. Polarised radial aluminium can — `CP_Radial_D<d>mm_P<p>mm` (42 files)

Diameter always one decimal, pitch always two decimals, **no height token**.

| Verbatim name | Ø mm | Pitch mm | Ref. height per `descr` | Notes |
|---|---:|---:|---:|---|
| `CP_Radial_D4.0mm_P1.50mm` | 4.0 | 1.50 | 7 | smallest; 1.2 mm pads |
| `CP_Radial_D4.0mm_P2.00mm` | 4.0 | 2.00 | 7 | |
| `CP_Radial_D5.0mm_P2.00mm` | 5.0 | 2.00 | 7 | |
| `CP_Radial_D5.0mm_P2.50mm` | 5.0 | 2.50 | 7 | |
| `CP_Radial_D6.3mm_P2.50mm` | 6.3 | 2.50 | 7 | only Ø6.3 pitch |
| `CP_Radial_D7.5mm_P2.50mm` | 7.5 | 2.50 | 8 | |
| `CP_Radial_D8.0mm_P2.50mm` | 8.0 | 2.50 | 10 | |
| `CP_Radial_D8.0mm_P3.50mm` | 8.0 | 3.50 | 12 | |
| `CP_Radial_D8.0mm_P3.80mm` | 8.0 | 3.80 | 14 | |
| `CP_Radial_D8.0mm_P5.00mm` | 8.0 | 5.00 | 16 | |
| `CP_Radial_D10.0mm_P2.50mm` | 10.0 | 2.50 | 12 | |
| `CP_Radial_D10.0mm_P2.50mm_P5.00mm` | 10.0 | 2.50 + 5.00 | 12 | dual hole pair |
| `CP_Radial_D10.0mm_P3.50mm` | 10.0 | 3.50 | 16 | |
| `CP_Radial_D10.0mm_P3.80mm` | 10.0 | 3.80 | 16 | |
| `CP_Radial_D10.0mm_P5.00mm` | 10.0 | 5.00 | 16 | 2.0 mm pads |
| `CP_Radial_D10.0mm_P5.00mm_P7.50mm` | 10.0 | 5.00 + 7.50 | 16 | dual hole pair |
| `CP_Radial_D10.0mm_P7.50mm` | 10.0 | 7.50 | 20 | |
| `CP_Radial_D12.5mm_P2.50mm` | 12.5 | 2.50 | 16 | |
| `CP_Radial_D12.5mm_P5.00mm` | 12.5 | 5.00 | 20 | |
| `CP_Radial_D12.5mm_P7.50mm` | 12.5 | 7.50 | 24 | |
| `CP_Radial_D13.0mm_P2.50mm` | 13.0 | 2.50 | 16 | |
| `CP_Radial_D13.0mm_P5.00mm` | 13.0 | 5.00 | 20 | |
| `CP_Radial_D13.0mm_P7.50mm` | 13.0 | 7.50 | 24 | |
| `CP_Radial_D14.0mm_P5.00mm` | 14.0 | 5.00 | 20 | |
| `CP_Radial_D14.0mm_P7.50mm` | 14.0 | 7.50 | 20 | |
| `CP_Radial_D16.0mm_P7.50mm` | 16.0 | 7.50 | 25 | |
| `CP_Radial_D17.0mm_P7.50mm` | 17.0 | 7.50 | 30 | |
| `CP_Radial_D18.0mm_P7.50mm` | 18.0 | 7.50 | 35 | largest non-snap-in |

Snap-in cans (14 files) — `_3pin` always **before** `_SnapIn`; all are `P10.00mm`; all cite Vishay `058059pll-si.pdf`; 4.0 mm holes:

| Ø mm | 2-pin (verbatim) | 3-pin (verbatim) |
|---:|---|---|
| 22.0 | `CP_Radial_D22.0mm_P10.00mm_SnapIn` | `CP_Radial_D22.0mm_P10.00mm_3pin_SnapIn` |
| 24.0 | `CP_Radial_D24.0mm_P10.00mm_SnapIn` | `CP_Radial_D24.0mm_P10.00mm_3pin_SnapIn` |
| 25.0 | `CP_Radial_D25.0mm_P10.00mm_SnapIn` | `CP_Radial_D25.0mm_P10.00mm_3pin_SnapIn` |
| 26.0 | `CP_Radial_D26.0mm_P10.00mm_SnapIn` | `CP_Radial_D26.0mm_P10.00mm_3pin_SnapIn` |
| 30.0 | `CP_Radial_D30.0mm_P10.00mm_SnapIn` | `CP_Radial_D30.0mm_P10.00mm_3pin_SnapIn` |
| 35.0 | `CP_Radial_D35.0mm_P10.00mm_SnapIn` | `CP_Radial_D35.0mm_P10.00mm_3pin_SnapIn` |
| 40.0 | `CP_Radial_D40.0mm_P10.00mm_SnapIn` | `CP_Radial_D40.0mm_P10.00mm_3pin_SnapIn` |

### 3b. Polarised radial tantalum (dipped/wet) — `CP_Radial_Tantal_D<d>mm_P<p>mm` (16 files)

Token is **`Tantal`**, not `Tantalum`. Diameters 4.5 / 5.0 / 5.5 / 6.0 / 7.0 / 8.0 / 9.0 / 10.5 mm × pitch 2.50 or 5.00 mm — a complete 8 × 2 grid. All cite the Reichelt `TANTAL-TB-Serie` datasheet.

| Verbatim, P2.50mm | Verbatim, P5.00mm |
|---|---|
| `CP_Radial_Tantal_D4.5mm_P2.50mm` | `CP_Radial_Tantal_D4.5mm_P5.00mm` |
| `CP_Radial_Tantal_D5.0mm_P2.50mm` | `CP_Radial_Tantal_D5.0mm_P5.00mm` |
| `CP_Radial_Tantal_D5.5mm_P2.50mm` | `CP_Radial_Tantal_D5.5mm_P5.00mm` |
| `CP_Radial_Tantal_D6.0mm_P2.50mm` | `CP_Radial_Tantal_D6.0mm_P5.00mm` |
| `CP_Radial_Tantal_D7.0mm_P2.50mm` | `CP_Radial_Tantal_D7.0mm_P5.00mm` |
| `CP_Radial_Tantal_D8.0mm_P2.50mm` | `CP_Radial_Tantal_D8.0mm_P5.00mm` |
| `CP_Radial_Tantal_D9.0mm_P2.50mm` | `CP_Radial_Tantal_D9.0mm_P5.00mm` |
| `CP_Radial_Tantal_D10.5mm_P2.50mm` | `CP_Radial_Tantal_D10.5mm_P5.00mm` |

### 3c. Polarised axial aluminium can — `CP_Axial_L<l>mm_D<d>mm_P<p>mm_Horizontal` (55 files)

`L` = body length, `D` = diameter (both one decimal), `P` = hole pitch (two decimals), `_Horizontal` mandatory. Body lengths in stock: 10.0, 11.0, 18.0, 20.0, 21.0, 25.0, 26.5, 29.0, 30.0, 34.5, 37.0, 38.0, 40.0, 42.0, 42.5, 46.0, 55.0, 67.0, 80.0, 93.0 mm. Representative verbatim examples:

| Verbatim name | L mm | Ø mm | Pitch mm |
|---|---:|---:|---:|
| `CP_Axial_L10.0mm_D4.5mm_P15.00mm_Horizontal` | 10.0 | 4.5 | 15.00 |
| `CP_Axial_L11.0mm_D5.0mm_P18.00mm_Horizontal` | 11.0 | 5.0 | 18.00 |
| `CP_Axial_L18.0mm_D10.0mm_P25.00mm_Horizontal` | 18.0 | 10.0 | 25.00 |
| `CP_Axial_L26.5mm_D20.0mm_P33.00mm_Horizontal` | 26.5 | 20.0 | 33.00 |
| `CP_Axial_L30.0mm_D12.5mm_P35.00mm_Horizontal` | 30.0 | 12.5 | 35.00 |
| `CP_Axial_L42.0mm_D35.0mm_P45.00mm_Horizontal` | 42.0 | 35.0 | 45.00 |
| `CP_Axial_L93.0mm_D35.0mm_P100.00mm_Horizontal` | 93.0 | 35.0 | 100.00 |

### 3d. Non-polar radial electrolytic — `C_Radial_D<d>mm_H<h>mm_P<p>mm` (18 files)

**This family carries a height token; `CP_Radial_*` does not.** Verified: 0 of 42 `CP_Radial_*` files contain `_H<digit>`; 18 of 18 `C_Radial_*` files do.

| Verbatim name | Ø mm | H mm | Pitch mm |
|---|---:|---:|---:|
| `C_Radial_D4.0mm_H5.0mm_P1.50mm` | 4.0 | 5.0 | 1.50 |
| `C_Radial_D4.0mm_H7.0mm_P1.50mm` | 4.0 | 7.0 | 1.50 |
| `C_Radial_D5.0mm_H5.0mm_P2.00mm` | 5.0 | 5.0 | 2.00 |
| `C_Radial_D5.0mm_H7.0mm_P2.00mm` | 5.0 | 7.0 | 2.00 |
| `C_Radial_D5.0mm_H11.0mm_P2.00mm` | 5.0 | 11.0 | 2.00 |
| `C_Radial_D6.3mm_H5.0mm_P2.50mm` | 6.3 | 5.0 | 2.50 |
| `C_Radial_D6.3mm_H7.0mm_P2.50mm` | 6.3 | 7.0 | 2.50 |
| `C_Radial_D6.3mm_H11.0mm_P2.50mm` | 6.3 | 11.0 | 2.50 |
| `C_Radial_D8.0mm_H7.0mm_P3.50mm` | 8.0 | 7.0 | 3.50 |
| `C_Radial_D8.0mm_H11.5mm_P3.50mm` | 8.0 | 11.5 | 3.50 |
| `C_Radial_D10.0mm_H12.5mm_P5.00mm` | 10.0 | 12.5 | 5.00 |
| `C_Radial_D10.0mm_H16.0mm_P5.00mm` | 10.0 | 16.0 | 5.00 |
| `C_Radial_D10.0mm_H20.0mm_P5.00mm` | 10.0 | 20.0 | 5.00 |
| `C_Radial_D12.5mm_H20.0mm_P5.00mm` | 12.5 | 20.0 | 5.00 |
| `C_Radial_D12.5mm_H25.0mm_P5.00mm` | 12.5 | 25.0 | 5.00 |
| `C_Radial_D16.0mm_H25.0mm_P7.50mm` | 16.0 | 25.0 | 7.50 |
| `C_Radial_D16.0mm_H31.5mm_P7.50mm` | 16.0 | 31.5 | 7.50 |
| `C_Radial_D18.0mm_H35.5mm_P7.50mm` | 18.0 | 35.5 | 7.50 |

The 28 `C_Axial_*` files (e.g. `C_Axial_L12.0mm_D10.5mm_P15.00mm_Horizontal`) are **film**, not electrolytic — their `descr` cites the Reichelt `STYROFLEX` datasheet. Do not use them as non-polar electrolytics.

## How to name a new part in this family

### A. SMD aluminium electrolytic can not in Table 1

1. From the datasheet, read the **can diameter D** and the **maximum seated height H** (top of can to PCB, including the base/seating washer), both in mm.
2. Format each number with **minimal decimals**: strip a trailing `.0` (10.0 → `10`, 3.0 → `3`) but keep a genuine decimal (6.3 → `6.3`, 10.5 → `10.5`).
3. Choose the prefix: `CP_Elec_` if polarised (virtually all), `C_Elec_` if the part is bipolar / non-polar.
4. Assemble `<prefix><D>x<H>` — literal lowercase `x`, no `mm`, no `D`/`H` letters, no pitch token. Example: a Ø6.3 mm / 7.7 mm-tall can → `CP_Elec_6.3x7.7`.
5. **Existence check before you commit to the name:**
   `test -f "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Capacitor_SMD.pretty/CP_Elec_6.3x7.7.kicad_mod"`
6. If that exact `D×H` already exists but the vendor's land pattern differs materially (pad size/spacing outside your tolerance), append `_<Manufacturer>` using the canonical manufacturer name. The only stock precedent is `CP_Elec_6.3x5.4_Nichicon` sitting beside `CP_Elec_6.3x5.4` (Panasonic C55).
7. If the height differs from a stock file by ≤0.1 mm, **do not reuse** the stock file — Ø6.3 alone ships 5.2 / 5.3 / 5.4 / 5.7 / 5.8 / 5.9. Those are real distinct land patterns.

### B. SMD tantalum case not in Table 2

1. From the datasheet get the **EIA metric code** (`LLWW`) and the **height code** (`HH`, maximum height in 0.1 mm), plus the manufacturer's **case letter** and which manufacturer it is.
2. Assemble `CP_EIA-<LLWW>-<HH>_<Vendor>-<Letter>`, with `<Vendor>` spelt exactly `Kemet` or `AVX`. Example: a Kemet 3216-18 A case → `CP_EIA-3216-18_Kemet-A`.
3. Add `_HandSolder` for the enlarged-pad variant. Every stock case has both, so if you author one, author both.
4. **Match on the metric code, never on the letter.** If `LLWW-HH` already exists under a *different* vendor/letter, use the existing file — the geometry is identical and the letter is only a label.
5. Existence check: `test -f ".../Capacitor_Tantalum_SMD.pretty/CP_EIA-3216-18_Kemet-A.kicad_mod"`.

### C. THT electrolytic not in Table 3

- Radial aluminium: `CP_Radial_D<d>mm_P<p>mm` — `<d>` formatted to **exactly one** decimal, `<p>` to **exactly two**. Ø9 mm on 3.5 mm pitch → `CP_Radial_D9.0mm_P3.50mm`. Do **not** add a height token; the footprint intentionally covers a whole height family.
- Radial tantalum: `CP_Radial_Tantal_D<d>mm_P<p>mm` (token `Tantal`).
- Axial: `CP_Axial_L<l>mm_D<d>mm_P<p>mm_Horizontal` — L and D one decimal, P two, `_Horizontal` mandatory.
- Snap-in: append `_SnapIn`, with `_3pin` immediately before it if the can has the third (dummy/neutral) lead.
- Non-polar radial: `C_Radial_D<d>mm_H<h>mm_P<p>mm` — this one **does** take the height token.

### D. When the package is genuinely absent from KiCad stock

1. Confirm absence, don't assume it. Run a per-file `test -f` for the exact candidate name **and** a directory listing filtered to the family, in all three libraries:
   `ls .../Capacitor_SMD.pretty | grep -E '^(CP|C)_Elec_'`, `ls .../Capacitor_Tantalum_SMD.pretty`, `ls .../Capacitor_THT.pretty | grep -E '^(CP|C)_(Radial|Axial)'`.
2. **Do not bend a near-miss stock name onto your part**, and do not edit KiCad's shipped `.pretty` directories.
3. Author a new footprint in this project's **`7Sigma:`** namespace, following the footprint-authoring rules in the `kicad-conventions-footprints` skill (pad/silk/fab/courtyard style, 0.1 mm pad grid) and submitting it as a **draft proposal** per `kicad-platform-workflow` — never publish directly.
4. **Keep the stock grammar byte-for-byte**, including the decimal conventions, so the new name sorts adjacent to the stock family and stays legible to anyone who knows the KiCad names. A new Ø7 mm / 5.4 mm can becomes `CP_Elec_7x5.4`; a new Kemet 4530-20 case becomes `CP_EIA-4530-20_Kemet-<letter>` plus its `_HandSolder` twin.
5. Record provenance in the footprint's `(descr ...)` exactly as the stock files do — vendor/series name, the `DxH` or `LxWxH` in mm, and the datasheet URL. Stock examples to copy the style from: `"SMD capacitor, aluminum electrolytic, Vishay 1010, 10.0x10.5mm, http://www.vishay.com/docs/28395/150crz.pdf"` and `"Tantalum Capacitor SMD Kemet-A (3216-18 Metric), IPC-7352 nominal, (Body size from: ...)"`.
6. Derive the land pattern from the datasheet's recommended pattern (or IPC-7351/7352 nominal, which is what the stock tantalum files declare), not by scaling a neighbouring stock footprint.

## Pitfalls

**SMD aluminium electrolytic**

1. **`D x H`, not `L x W`.** `CP_Elec_10x10.5` is a Ø10.0 mm can 10.5 mm tall. Reading it as a 10 × 10.5 mm rectangle will put the wrong keep-out and the wrong 3D model on the board.
2. **No `mm` suffix and no trailing `.0`,** even though the file's own `descr` writes `"10.0x10.5mm"`. `CP_Elec_8x10` exists; `CP_Elec_8.0x10.0`, `CP_Elec_8x10mm` and `CP_Elec_8x10.0` do not. Ø6.3 keeps its decimal because it is genuinely 6.3.
3. **`CP_` vs `C_` is polarity, not a typo.** `C_Elec_*` files say `"aluminum electrolytic nonpolar"`. Dropping the `P` silently swaps a polarised footprint for a bipolar one — and vice versa, which loses the polarity silkscreen.
4. **Near-identical names that are different parts:** `CP_Elec_6.3x5.4` (Panasonic C55) and `CP_Elec_6.3x5.4_Nichicon` (Nichicon). Same can, different land pattern. There is no way to tell them apart from the name alone — read the `descr`.
5. **0.1 mm height families.** Ø6.3 ships heights 3, 3.9, 4.5, 4.9, 5.2, 5.3, 5.4, 5.7, 5.8, 5.9, 7.7, 9.9. Ø5 ships 3, 3.9, 4.4, 4.5, 5.3, 5.4, 5.7, 5.8, 5.9. Pick from the datasheet height; "close enough" picks a different vendor's pad geometry.
6. **`CP_Elec_CAP-XX_DMF3Zxxxxxxxx3D` is not a can.** It lives in the `CP_Elec_` namespace but is a 470 mF / 5.5 V CAP-XX supercapacitor. Exclude it from can enumerations (this is why Table 1 has 62 rows from 63 files).
7. **Non-polar coverage stops at Ø10.** There is no `C_Elec_16x*` or `C_Elec_18x*`, and no non-polar equivalent for most polarised heights.

**SMD tantalum**

8. **The case letter is vendor-specific and vendors genuinely disagree.** Confirmed against the KYOCERA AVX TAJ case-dimensions table: KiCad's `Kemet-I` (3216-10) is AVX's **K**; `Kemet-U` (6032-15) is AVX's **W**; `Kemet-W` (7343-15) is AVX's **X**; `Kemet-V` (7343-20) is AVX's **Y**; `Kemet-X` (7343-43) is AVX's **E**. Never match a datasheet's letter to a KiCad footprint's letter — match on the four-digit metric code.
9. **The same letter appears at multiple sizes inside KiCad's own tantalum library.** `U` three times: `CP_EIA-6032-15_Kemet-U`, `CP_EIA-7132-20_AVX-U`, `CP_EIA-7361-438_AVX-U`. `C` twice: `CP_EIA-6032-28_Kemet-C`, `CP_EIA-7132-28_AVX-C`. `R` three times: `CP_EIA-2012-12_Kemet-R`, `CP_EIA-7260-15_AVX-R`, `CP_EIA-7260-38_AVX-R`. `M` twice: `CP_EIA-7260-20_AVX-M`, `CP_EIA-7260-28_AVX-M`. Autocompleting on the letter picks the wrong footprint.
10. **`CP_EIA-7361-438_AVX-U` has a three-digit height field — and it is an outlier.** KYOCERA AVX's own TAJ datasheet publishes this case as EIA **`7361-43`** (H = 4.10 mm nominal, 4.30 max). Quote KiCad's `438` verbatim because that is the real filename, but do **not** infer a general "three digits = hundredths of mm" rule — it occurs exactly once in 28 cases.
11. **The third EIA field is MAXIMUM height, not nominal.** Verified from the AVX TAJ table: 3216-**18** → nominal 1.60 (max 1.80); 3528-**21** → 1.90 (max 2.10); 6032-**28** → 2.60 (max 2.80); 7343-**31** → 2.90 (max 3.10); 7343-**43** → 4.10 (max 4.30); 7361-**38** → 3.55. Low-profile cases (`-10/-12/-15/-20`) quote H as a max, so there the code equals the nominal. Sizing a mechanical clearance from the code alone over-estimates by ~0.2 mm on the standard cases.
12. **The imperial code never appears in a KiCad footprint name,** so it cannot cause a naming error directly — but it is heavily ambiguous when you go the other way: **2917** covers 7343-15/-20/-30/-31/-40/-43 (six different heights), **1210** covers 3528-12/-15/-21, **2312** covers 6032-15/-20/-28, **1206** covers 3216-10/-12/-18, **0805** covers 2012-12/-15, **2924** covers 7361-38/-438. Never resolve a footprint from an imperial code alone.
13. **Imperial/metric confusion:** tantalum imperial codes are *legacy conventions*, not unit conversions. 3528 metric is **1210** imperial even though 3.5 × 2.8 mm converts to 0.138" × 0.110" (which would suggest 1411). Likewise 6032 → 2312 and 7343 → 2917 are not what rounding the inch dimensions gives. Do not compute an imperial code — look it up.
14. **`_HandSolder` is not optional detail.** Both variants exist for all 28 cases and have different pad geometry. Picking the nominal one for a hand-assembled prototype (or the HandSolder one for a reflow production panel) is a real assembly-yield decision, not cosmetic.
15. **6032-28 body length is quoted differently by vendors:** KiCad's `F.Fab` and KYOCERA AVX say 6.00 mm; Vishay's TMCH datasheet says 5.80 ± 0.2 mm. Table 2 follows the KiCad `F.Fab` outline, which is what the footprint actually draws.

**THT**

16. **`CP_Radial_*` has NO height token; `C_Radial_*` DOES.** Verified by count: 0 of 42 vs 18 of 18. `C_Radial_D10.0mm_H12.5mm_P5.00mm` and `CP_Radial_D10.0mm_P5.00mm` are the same diameter and pitch but obey different grammars. Adding `_H12.5mm` to a `CP_Radial` name produces a file that does not exist.
17. **THT decimal rules are the OPPOSITE of the SMD electrolytic rules.** THT keeps trailing zeros *and* appends `mm`: `D4.0mm` (exactly one decimal) and `P1.50mm` / `P10.00mm` (exactly two). `CP_Radial_D4mm_P1.5mm` does not exist. Meanwhile SMD strips them: `CP_Elec_4x3`. Switching families means switching formatting conventions.
18. **The THT tantalum token is `Tantal`, not `Tantalum`.** `CP_Radial_Tantal_D5.0mm_P2.50mm`. Also note the SMD tantalum family uses `CP_EIA-…` with no vendor-word `Tantalum` at all — the two tantalum families share no naming DNA.
19. **`_3pin` precedes `_SnapIn`:** `CP_Radial_D22.0mm_P10.00mm_3pin_SnapIn`. There is no `_SnapIn_3pin`.
20. **Dual-pitch names carry two `P` tokens in ascending order** and exist only at Ø10: `CP_Radial_D10.0mm_P2.50mm_P5.00mm` and `CP_Radial_D10.0mm_P5.00mm_P7.50mm`. Don't expect a `CP_Radial_D12.5mm_P2.50mm_P5.00mm`.
21. **A `CP_Radial` name does not pin the can height,** even though the file's `descr` states one (`"diameter=10mm, height=16mm"`). That height is the reference can used for the 3D model and courtyard; one footprint is meant to serve every height at that Ø/pitch. If your can is much taller, check the courtyard yourself.
22. **`C_Axial_*` (28 files) are FILM, not electrolytic** — their `descr` cites the Reichelt `STYROFLEX` datasheet. Reaching for `C_Axial_L12.0mm_D10.5mm_P15.00mm_Horizontal` as a non-polar electrolytic is wrong; the non-polar electrolytic family is `C_Radial_*`.
23. **All 55 `CP_Axial_*` files end in `_Horizontal`.** There is no vertical/standing axial variant in stock; if you need one you are authoring a new footprint, not finding one.

**Cross-cutting**

24. **The KiCad Library Convention page (`klc.kicad.org/footprint/f3/f3.3.html`) does not match the shipped library for these families.** An automated fetch of that page renders the examples as `CP_Elec_10x10.5mm_H6mm` and `CP_Tantalum_EIA-3126-18_Kemet-A_Pad1.53x1.40mm_HandSolder`. The shipped files are `CP_Elec_10x10.5` and `CP_EIA-3216-18_Kemet-A`. I could not rule out that the fetch garbled the page, so treat the exact KLC wording as *unverified* — but the shipped filenames are directly confirmed and are what KiCad actually resolves. **Always trust the filesystem over the convention prose.**
25. **Verify every name with a per-file test before you use it.** Every one of the 180 names quoted here was checked with `test -f`. Family listings (`ls | grep`) are for discovery; a `test -f` on the exact string is what proves the name.


---


# Discrete SMD packages — SOT-* / SOD-* / SC-* / SM* / TO-*-SMD / *PAK / MELF (KiCad `Package_TO_SOT_SMD.pretty` + `Diode_SMD.pretty`)

**Backed by:** **220 shipped `.kicad_mod` files back this table, and all 220 are listed in it.**

- `Package_TO_SOT_SMD.pretty` — **137** files (98 begin with `SOT`/`TSOT`/`SuperSOT`/`SC-`/`TO-`; 39 begin with a vendor prefix)
- `Diode_SMD.pretty` — **83** files (67 begin with `D_`; 16 do not)

Provenance: KiCad **10.0.5** (`/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints`), footprint file format `(version 20260206)`.

Verification performed: every name quoted was re-tested individually against an exact-case `os.listdir` set (not `test -f`, which is case-blind on APFS). Result: **220 names checked, 0 missing, 0 duplicated, 0 invented**; coverage check reported `Package_TO_SOT_SMD: on disk 137, quoted 137, uncovered [], phantom []` and `Diode_SMD: on disk 83, quoted 83, uncovered [], phantom []`.

## Grammar

## Token grammar

### Package_TO_SOT_SMD.pretty

```
NAME  := [ VENDOR "_" ] BASE [ "-" N ] { "_" QUAL }
BASE  := "SOT-" ddd | "SOT-" dddd | "SC-" nn[A-Z]* | "TSOT-23" | "SuperSOT"
       | "TO-" nnn[A-Z]* | <vendor package code>
N     := decimal pin/lead count  (see the -N rule below)
QUAL  := SIZE          e.g. "1.55x2.9mm"        (body W x H)
       | PITCH         e.g. "P0.95mm"
       | "TabPin" n                              (tab pad given number n)
       | "ThermalVias" | "ThermalVias2"
       | "Single" | "Dual"
       | "LongPad" | "ShortPad" | "NoHole" | "WithHole" | "Housing"
       | "ClockwisePinNumbering" | "Lead" n
       | HANDSOLDER                              (always the LAST token)
HANDSOLDER := "Handsoldering" | "HandSoldering"
```

Observed qualifier order (verbatim examples): `Texas_DDF0008A_SOT-8_1.6x2.9mm_P0.65mm` (vendor → drawing code → base-N → size → pitch), `TO-50-3_LongPad-WithHole_Housing`, `TO-252-5_TabPin6`, `Infineon_PG-HSOF-8-2_ThermalVias2`, `SOT-23-5_HandSoldering`. The hand-solder token is terminal in **all 16** such files in this library.

### Diode_SMD.pretty

```
NAME  := [ VENDOR "_" ] "D_" BODY { "_" QUAL }
       | [ VENDOR "_" ] <vendor package code> { "_" QUAL }     (16 files)
       | "Diode_Bridge_" VENDOR "_" CODE                        (8 files)
BODY  := "SOD-" nnn[A-Z]* | "SMA" | "SMB" | "SMC" | "SMF" | "SMP_DO-220AA"
       | "MELF" | "MiniMELF" | "MicroMELF" | "MicroSMP" | "Powermite"["2"|"3"]
       | "PowerDI-" n | "SC-80" | "TUMD2" | IMPERIAL "_" METRIC "Metric"
QUAL  := "Pad" WxHmm | "LargeAnode" | "LargeCathode" | "Modified"
       | "Universal" | "RM10" | HANDSOLDER
HANDSOLDER := "Handsoldering" | "HandSoldering" | "HandSolder"
```

---

## THE `-N` PIN-COUNT RULE (precise, with verbatim evidence)

**`-N` is not a KiCad-computed pad count. It is copied from the designation used by the standards body or the manufacturer, and KiCad appends it only when the BASE token is by itself ambiguous about lead count.** Four clauses:

### Clause 1 — Ambiguous base ⇒ `-N` on every member
A base is ambiguous when the same token is registered against more than one lead count. In stock, exactly these bases are ambiguous, and each member carries a count:

| Ambiguous base | Members present (verbatim) |
|---|---|
| `SOT-23` | `SOT-23-3`, `SOT-23-5`, `SOT-23-6`, `SOT-23-8` (plus legacy bare `SOT-23`) |
| `TSOT-23` | `TSOT-23-5`, `TSOT-23-6`, `TSOT-23-8` (plus legacy bare `TSOT-23`) |
| `SOT-89` | `SOT-89-3`, `SOT-89-5` — **no bare `SOT-89` exists** (verified absent) |
| `SOT-223` | `SOT-223-3_TabPin2`, `SOT-223-5`, `SOT-223-6`, `SOT-223-6_TabPin3`, `SOT-223-8` (plus legacy bare `SOT-223`) |
| `SC-70` | `SOT-343_SC-70-4`, `SOT-353_SC-70-5`, `SOT-363_SC-70-6`, `SC-70-8` — the 3-pin member is `SOT-323_SC-70`, unsuffixed |
| `SC-74` | `SC-74-6_1.55x2.9mm_P0.95mm`, `SC-74A-5_1.55x2.9mm_P0.95mm` |
| `TO-252` / `TO-263` / `TO-268` | always suffixed (see clause 4) |
| `TO-50` | `TO-50-3_*`, `TO-50-4_*` |

### Clause 2 — Unambiguous base ⇒ never a suffix
The NXP/Philips `SOT-<3 digits>` series encodes the lead count in its **last digit**, so KiCad never repeats it. Verified in stock (all pad counts measured from the files):

`SOT-323`=3, `SOT-343`=4, `SOT-353`=5, `SOT-363`=6 · `SOT-523`=3, `SOT-543`=4, `SOT-553`=5, `SOT-563`=6 · `SOT-665`=5, `SOT-666`=6 · `SOT-883`=3, `SOT-886`=6 · `SOT-416`=3, `SOT-723`=3, `SOT-963`=6, `SOT-1123`=3, `SOT-143`=4.

Consequently `SOT-563-6`, `SOT-553-5`, `SOT-723-3`, `SOT-323`, `SOT-353`, `SOT-363`, `SC-70`, `SC-70-5`, `SC-70-6` do **not** exist as filenames (each verified absent).

### Clause 3 — The bare legacy name is a DIFFERENT LAND, not an alias
Both `SOT-23` and `SOT-23-3` exist, both are 3-pin, and they are not interchangeable:

- `SOT-23.kicad_mod` → `(descr "SOT, 3 Pin (JEDEC TO-236 Var AB https://www.jedec.org/document_search?search_api_views_fulltext=TO-236)")`; F.Fab body **1.3 x 2.9 mm**; pad 1 `(at -0.9375 -0.95) (size 1.475 0.6)`
- `SOT-23-3.kicad_mod` → `(descr "SOT, 3 Pin (JEDEC MO-178 inferred 3-pin variant https://www.jedec.org/document_search?search_api_views_fulltext=MO-178)")`; F.Fab body **1.6 x 2.9 mm**; pad 1 `(at -1.1375 -0.95) (size 1.325 0.6)`

So the suffix switches the **JEDEC drawing**: bare `SOT-23` = TO-236 (narrow body), `SOT-23-N` = MO-178 (wide body). The MO-178 members are:
- `SOT-23-5` → `(descr "SOT, 5 Pin (JEDEC MO-178 Var AA ...)")`
- `SOT-23-6` → `(descr "SOT, 6 Pin (JEDEC MO-178 Var AB ...)")`
- `SOT-23-8` → `(descr "SOT, 8 Pin (JEDEC MO-178 Var BA ...)")`

Same pattern for TSOT-23: bare `TSOT-23` → `(descr "3-pin TSOT23 package, http://www.analog.com.tw/pdf/All_In_One.pdf")`, while `TSOT-23-5/-6/-8` → `(descr "TSOT, 5|6|8 Pin (https://www.jedec.org/sites/default/files/docs/MO-193D.pdf variant AB|AA|BA)")`.

### Clause 4 — For tab packages, what `-N` counts differs by family (measured, not inferred)

**`TO-252` / `TO-263` / `TO-268` / `ATPAK`: `-N` = number of LEAD pads; the tab silently takes the one remaining number in the middle of the sequence, giving N+1 distinct numbers.**
- `TO-252-2`: pads `1 (at -5.04 -2.28)`, `2 (at 1.26 0) (size 6.4 5.8)` ← the tab, `3 (at -5.04 2.28)` → 2 leads, tab = pin 2
- `TO-252-4`: leads 1, 2, 4, 5 at y = −2.28/−1.14/+1.14/+2.28 (1.14 mm grid) + `3 (at 1.26 0) (size 6.4 5.8)` ← tab
- `TO-263-6`: leads 1, 2, 3, 5, 6, 7 (1.27 mm grid) + `4 (at 1.5 0) (size 9.4 10.8)` ← tab
- `ATPAK-2`: `1`, `3` leads + `2 (at 1.2 0) (size 6.7 6.5)` ← tab

**`SOT-223`: `-N` = TOTAL numbered pins INCLUDING the tab, giving N numbers.**
- `SOT-223-5`: leads 1–4 (1.5 mm grid) + `5 (at 3.25 0) (size 1.8 3.4)` ← tab
- `SOT-223-6`: leads 1–5 (1.27 mm grid) + `6 (at 3.1625 0) (size 2.15 3.45)` ← tab
- `SOT-223-8`: 8 equal 2.8 x 0.95 pads, 4 per side — **no tab at all**

**`_TabPin<n>` is added only when the full lead row is populated and the tab therefore needs its own explicit number** — either shorted onto an existing lead (duplicate pad number) or as a brand-new number:
- `TO-252-3_TabPin2` → pads `1, 2, 2, 3` (3 leads on the 2.28 mm grid, tab **shorted** to pin 2)
- `TO-252-3_TabPin4` → pads `1, 2, 3, 4` (3 leads on the 2.28 mm grid, tab is a **new** pin 4)
- `TO-252-5_TabPin3` → pads `1, 2, 3, 3, 4, 5` (5 leads on the 1.14 mm grid, tab shorted to 3)
- `TO-252-5_TabPin6` → pads `1..6` (5 leads + new pin 6)

Note the trap this creates: `TO-252-3_TabPin4` and `TO-252-4` both end up with 4 numbers, but the first is the DPAK-3 land (2.28 mm lead grid) and the second is the DPAK-5 land (1.14 mm lead grid).

### Clause 5 — Trailing digits that are NOT pin counts
- **NXP issue numbers:** `SOT-1333-1` has **9** numbered pads; `SOT-1334-1` has **14**.
- **Vendor sub-variant indices:** `Infineon_PG-HSOF-8-1` (3 numbers), `Infineon_PG-HSOF-8-2` (4), `Infineon_PG-HSOF-8-3` (4), `Infineon_PG-TSFP-3-1` (3), `TDSON-8-1` (5 numbers).
- **Vendor generation numbers:** `D_Powermite2`, `D_Powermite3` (Microsemi Powermite / Powermite 2 / Powermite 3).
- **Vendor names that happen to embed a count:** `SOT-583-8` (TI TPS62933), `Texas_NDW-7_TabPin4`.

## Reference table

**Source:** KiCad 10.0.5 shipped libraries, footprint format `(version 20260206)`. `Package_TO_SOT_SMD.pretty` (137 files) + `Diode_SMD.pretty` (83 files) = **220 files, every one of which appears below**. All names are verbatim filenames with `.kicad_mod` omitted.

**Column meanings**
- **Pins** — number of *distinct* pad numbers (the electrical net count).
- **Numbered pads** — physical pad objects carrying a number. `(+n shorted)` = n extra pads reusing an already-used number (split tab / thermal fan-out). `+nu` = n additional pads with an empty number (solder-paste, via, mechanical).
- **Body from F.Fab (mm)** — bounding box measured off the shipped `F.Fab` layer, width x height in the footprint's own orientation. `n/a *` = that footprint's F.Fab carries only a partial marking, so no body box can be read from it.

### A. SOT-23 family (`Package_TO_SOT_SMD.pretty`) - the base name selects the JEDEC drawing, not just the count

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `SOT-23` | 3 | 3 | 1.3 x 2.9 | JEDEC **TO-236 Var AB** | bare name = 3 pins; narrow 1.3 mm body |
| `SOT-23_Handsoldering` | 3 | 3 | 1.4 x 3.04 | TO-236 Var AB | hand-solder pads; lowercase **s** |
| `SOT-23-3` | 3 | 3 | 1.6 x 2.9 | JEDEC **MO-178**, "inferred 3-pin variant" | wide 1.6 mm MO-178 body - NOT the same land as `SOT-23` |
| `SOT-23-5` | 5 | 5 | 1.6 x 2.9 | JEDEC **MO-178 Var AA** | 0.95 mm lead grid |
| `SOT-23-5_HandSoldering` | 5 | 5 | 1.8 x 3.1 | MO-178 Var AA | capital **S** in HandSoldering |
| `SOT-23-6` | 6 | 6 | 1.6 x 2.9 | JEDEC **MO-178 Var AB** | 0.95 mm lead grid |
| `SOT-23-6_Handsoldering` | 6 | 6 | 1.8 x 3.1 | MO-178 Var AB | lowercase **s** |
| `SOT-23-8` | 8 | 8 | 1.6 x 2.9 | JEDEC **MO-178 Var BA** | 0.65 mm lead grid |
| `SOT-23-8_Handsoldering` | 8 | 8 | 1.8 x 3.1 | MO-178 Var BA | lowercase **s** |
| `SOT-23W` | 3 | 3 | 1.91 x 2.98 | Allegro A112x wide SOT-23 | no count: only a 3-pin variant exists |
| `SOT-23W_Handsoldering` | 3 | 3 | 1.91 x 2.98 | Allegro A112x wide SOT-23 | lowercase **s** |
| `TSOT-23` | 3 | 3 | 1.76 x 2.9 | thin SOT-23, Analog Devices drawing | bare = 3 pins |
| `TSOT-23_HandSoldering` | 3 | 3 | 1.76 x 2.9 | thin SOT-23 | capital **S** |
| `TSOT-23-5` | 5 | 5 | 1.6 x 2.9 | JEDEC **MO-193D variant AB** |  |
| `TSOT-23-5_HandSoldering` | 5 | 5 | 1.76 x 2.9 | MO-193D AB | capital **S** |
| `TSOT-23-6` | 6 | 6 | 1.6 x 2.9 | JEDEC **MO-193D variant AA** | hand-solder twin's tags add `MK06A`, `TSOT-6` |
| `TSOT-23-6_HandSoldering` | 6 | 6 | 1.76 x 2.9 | MO-193D AA / **MK06A** / **TSOT-6** | capital **S** |
| `TSOT-23-8` | 8 | 8 | 1.6 x 2.9 | JEDEC **MO-193D variant BA** |  |
| `TSOT-23-8_HandSoldering` | 8 | 8 | 1.76 x 2.9 | MO-193D BA | capital **S** |
| `SuperSOT-3` | 3 | 3 | 1.4 x 2.9 | Fairchild SuperSOT-3 = **SSOT-3** (tags) | SOT-23 class, vendor name |
| `SuperSOT-6` | 6 | 6 | 1.7 x 2.9 | Fairchild SuperSOT-6 = **SSOT-6** (tags) |  |
| `SuperSOT-8` | 8 | 8 | 3.3 x 4.1 | Fairchild SuperSOT-8 = **SSOT-8** (tags) |  |

### B. NXP/Philips-style `SOT-<3 digits>` codes (`Package_TO_SOT_SMD.pretty`) - the code itself encodes the lead count, so no `-N` is appended

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `SOT-143` | 4 | 4 | 1.3 x 2.9 | NXP SOT143B | 4 leads, pin 1 is the wide one |
| `SOT-143_Handsoldering` | 4 | 4 | 1.3 x 2.9 | NXP SOT143B | lowercase **s** |
| `SOT-143R` | 4 | 4 | 2.9 x 1.3 | NXP SOT143R - **reverse pinning** | mirror of SOT-143; easy to mis-pick |
| `SOT-143R_Handsoldering` | 4 | 4 | 2.9 x 1.3 | NXP SOT143R reverse | lowercase **s** |
| `SOT-323_SC-70` | 3 | 3 | 1.25 x 2.0 | **SOT-323 = SC-70** (alias is inside the filename) | 3 pins |
| `SOT-343_SC-70-4` | 4 | 4 | 1.25 x 2.0 | **SOT-343 = SC-70-4** | 4 pins, 2 per side |
| `SOT-353_SC-70-5` | 5 | 5 | 1.25 x 2.0 | **SOT-353 = SC-70-5 = SC-88A**; JEDEC MO-203 Var AA | `SC-88A` is in the file's tags |
| `SOT-363_SC-70-6` | 6 | 6 | 1.25 x 2.0 | **SOT-363 = SC-70-6 = SC-88 = US6 = UMT6 = S-Mini6 = TSSOP6**; JEDEC MO-203 Var AB | every alias listed is in the file's own tags |
| `SOT-383F` | 9 | 9 | 1.7 x 2.0 | SOT-383F (CPDVR085V0C) | 9 numbered pads: 8 leads + centre pad **9**, although descr says "8-pin" |
| `SOT-383FL` | 8 | 8 | 1.7 x 2.0 | onsemi SOT-383FL | 8 leads, no centre pad |
| `SOT-416` | 3 | 3 | 0.9 x 1.8 | NXP SOT416 | 3 pins |
| `SOT-457T` | 6 | 6 | 1.65 x 2.9 | **SC-95 / TSMT6** (tags); ROHM QS6K21 | 6 pins |
| `SOT-523` | 3 | 3 | 0.8 x 1.6 | Diodes Inc SOT523 | 3 pins |
| `SOT-543` | 4 | 4 | 1.0 x 1.6 | **SOT-543 = SC-107A = EMD4** (tags) | 4 pins |
| `SOT-553` | 5 | 5 | 1.2 x 1.6 | JEDEC **MO-293 UAAD-1**; TI **DRL-5** (tags) | 5 pins |
| `SOT-563` | 6 | 6 | 1.2 x 1.6 | JEDEC **MO-293 UAAD**; TI **DRL-6** (tags) | 6 pins |
| `SOT-583-8` | 8 | 8 | 1.2 x 2.1 | TI TPS62933 drawing | the `-8` is part of the vendor's own name |
| `SOT-665` | 5 | 5 | 1.3 x 1.7 | SOT665 | 5 pins; pin 2 is a wide centre pad |
| `SOT-666` | 6 | 6 | 1.3 x 1.7 | SOT666 | 6 pins; pins 2 and 5 are wide centre pads |
| `SOT-723` | 3 | 3 | 0.8 x 1.2 | Toshiba RN1104MFV drawing | 3 pins |
| `SOT-883` | 3 | 3 | 1.02 x 0.62 | Nexperia SOT883 | 3 pins, leadless |
| `SOT-886` | 6 | 6 | 1.0 x 1.5 | SOT-886 | 6 pins, leadless |
| `SOT-963` | 6 | 6 | 0.8 x 1.0 | SOT 963, 1x0.8 mm, 0.35 mm pitch | 6 pins |
| `SOT-1123` | 3 | 3 | 0.8 x 0.6 | onsemi NST3906F3 | 3 pins |
| `SOT-1333-1` | 9 | 9 | 2.5 x 2.0 | NXP SOT-1333-1 | trailing `-1` is the NXP **issue number**, not a pin count |
| `SOT-1334-1` | 14 | 14 | 4.0 x 2.0 | NXP SOT-1334-1 | trailing `-1` is the issue number |

### C. Tab-bearing SOT packages (`Package_TO_SOT_SMD.pretty`)

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `SOT-89-3` | 3 | 3 | 2.5 x 4.5 | Microchip 3L SOT-89 | pin 2 = wide centre tab lead; there is **no bare `SOT-89`** |
| `SOT-89-3_Handsoldering` | 3 | 3 | 2.5 x 4.5 | 3L SOT-89 | lowercase **s** |
| `SOT-89-5` | 5 | 5 | 2.5 x 4.5 | Ricoh SOT-89-5 | pin 2 = centre tab pad |
| `SOT-89-5_Handsoldering` | 5 | 5 | 2.5 x 4.5 | SOT-89-5 | lowercase **s** |
| `SOT-223` | 4 | 4 | 3.7 x 6.7 | legacy SOT-223; descr "module CMS SOT223 4 pins" | 3 leads + tab as an independent **pin 4** (no `_TabPin4` suffix) |
| `SOT-223-3_TabPin2` | 3 | 4 (+1 shorted) | 3.7 x 6.7 | SOT-223, 3 leads | tab pad **shorted to pin 2** |
| `SOT-223-5` | 5 | 5 | 3.7 x 6.7 | Microchip SOT-223-5 | 4 leads + tab = pin 5, so `-5` counts the tab |
| `SOT-223-6` | 6 | 6 | 3.7 x 6.7 | TI TPS737 SOT-223-6 | 5 leads + tab = pin 6 |
| `SOT-223-6_TabPin3` | 5 | 6 (+1 shorted) | 3.7 x 6.7 | TI TPS737 SOT-223-6 | 5 leads, tab **shorted to pin 3** |
| `SOT-223-8` | 8 | 8 | 3.7 x 6.7 | Diodes ZXSBMR16PT8 | 8 equal leads, 4 per side, **no tab** |

### D. `SC-*` names that stand alone, plus the TI `R-PDSO-*` equivalents (`Package_TO_SOT_SMD.pretty`)

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `SC-59` | 3 | 3 | 1.7 x 3.1 | SC-59 (SOT-23 outline, wider land) | 3 pins |
| `SC-59_Handsoldering` | 3 | 3 | 1.7 x 3.1 | SC-59 | lowercase **s** |
| `SC-70-8` | 8 | 8 | 1.25 x 2.0 | JEDEC **MO-203 variant BA**; tags `SC8` | 8 pins - no `SOT-` code for it is in stock |
| `SC-74-6_1.55x2.9mm_P0.95mm` | 6 | 6 | 1.55 x 2.9 | JEITA ED-7500B **SC-74** | 6 pins; body+pitch encoded in the name |
| `SC-74A-5_1.55x2.9mm_P0.95mm` | 5 | 5 | 1.55 x 2.9 | JEITA ED-7500B **SC-74A** | 5 pins |
| `SC-82AA` | 4 | 4 | 1.35 x 2.2 | EIAJ SC-82AA | 4 pins, 2 per side |
| `SC-82AA_Handsoldering` | 4 | 4 | 1.35 x 2.2 | EIAJ SC-82AA | lowercase **s** |
| `SC-82AB` | 4 | 4 | 1.35 x 2.2 | EIAJ SC-82AB | 4 pins |
| `SC-82AB_Handsoldering` | 4 | 4 | 1.35 x 2.2 | EIAJ SC-82AB | lowercase **s** |
| `Analog_KS-4` | 4 | 4 | 1.35 x 2.2 | Analog Devices KS-4, "like EIAJ **SC-82**" (tags) | 4 pins |
| `ROHM_SOT-457_ClockwisePinNumbering` | 6 | 6 | 2.9 x 1.65 | ROHM SOT-457 = **SC-74** (descr) | clockwise numbering variant of `SOT-457T` |
| `Texas_R-PDSO-G5_DCK-5` | 5 | 5 | 1.35 x 2.0 | TI **DCK** / R-PDSO-G5; JEDEC **MO-203C Var AA** (SC-70-5 land) |  |
| `Texas_R-PDSO-G6` | 6 | 6 | 1.35 x 2.2 | TI R-PDSO-G6; tags `SC-70-6` |  |
| `Texas_R-PDSO-N5_DRL-5` | 5 | 5 | 1.2 x 1.6 | TI **DRL-5** / R-PDSO-N5; JEDEC **MO-293B Var UAAD-1** (SOT-553 land) |  |
| `Texas_R-PDSO-N6_DRL-6` | 6 | 6 | 1.2 x 1.6 | TI **DRL-6** / R-PDSO-N6; "similar to JEDEC MO-293B Var UAAD (but not the same)" | descr explicitly warns it is *not* SOT-563 |
| `Diodes_SOT-553` | 5 | 5 | 1.25 x 1.7 | Diodes Inc SOT553 drawing | vendor land, wider than generic `SOT-553` |
| `Vishay_PowerPAK_SC70-6L_Dual` | 6 | 8 (+2 shorted) | 2.05 x 2.05 | Vishay PowerPAK SC70-6L | 6 pins, dual transistor |
| `Vishay_PowerPAK_SC70-6L_Single` | 3 | 4 (+1 shorted) +2u | 2.05 x 2.05 | Vishay PowerPAK SC70-6L | pads numbered **1, 3, 4 only** |

### E. `TO-*` SMD tab packages and the *PAK aliases (`Package_TO_SOT_SMD.pretty`)

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `TO-252-2` | 3 | 3 +4u | 9.92 x 6.5 | **DPAK / DPAK-3 / TO-252-3 / SOT-428** (tags) | 2 leads (pins 1, 3) + tab numbered **2** |
| `TO-252-2_TabPin1` | 2 | 3 (+1 shorted) +4u | 10.11 x 6.7 | TO-252-2, diode variant | 2 leads + tab **shorted to pin 1** |
| `TO-252-3_TabPin2` | 3 | 4 (+1 shorted) +4u | 9.92 x 6.5 | DPAK / SOT-428 | 3 leads + tab shorted to pin 2 |
| `TO-252-3_TabPin4` | 4 | 4 +4u | 9.92 x 6.5 | DPAK / SOT-428 | 3 leads on the 2.28 mm grid + tab as extra pin 4 |
| `TO-252-4` | 5 | 5 +4u | 9.92 x 6.5 | **DPAK-5 / TO-252-5** (tags) | 4 leads on the 1.14 mm grid + tab numbered **3** |
| `TO-252-5_TabPin3` | 5 | 6 (+1 shorted) +4u | 9.92 x 6.5 | DPAK-5 / TO-252-5 | 5 leads + tab shorted to pin 3 |
| `TO-252-5_TabPin6` | 6 | 6 +4u | 9.92 x 6.5 | DPAK-5 / TO-252-5 | 5 leads + tab as extra pin 6 |
| `TO-263-2` | 3 | 3 +4u | 14.95 x 10.0 | **D2PAK / DDPAK / D2PAK-3 / TO-263-3 / SOT-404** (tags) | 2 leads + tab numbered 2 |
| `TO-263-2_TabPin1` | 2 | 3 (+1 shorted) +4u | 14.95 x 10.0 | D2PAK, diode variant | tab shorted to pin 1 |
| `TO-263-3_TabPin2` | 3 | 4 (+1 shorted) +4u | 14.95 x 10.0 | D2PAK / SOT-404 | 3 leads + tab shorted to pin 2 |
| `TO-263-3_TabPin4` | 4 | 4 +4u | 14.95 x 10.0 | D2PAK / SOT-404 | 3 leads + tab as extra pin 4 |
| `TO-263-4` | 5 | 5 +4u | 14.95 x 10.0 | **D2PAK-5 / TO-263-5 / SOT-426** (tags) | 4 leads + tab numbered 3 |
| `TO-263-5_TabPin3` | 5 | 6 (+1 shorted) +4u | 14.95 x 10.0 | D2PAK-5 / SOT-426 | 5 leads + tab shorted to pin 3 |
| `TO-263-5_TabPin6` | 6 | 6 +4u | 14.95 x 10.0 | D2PAK-5 / SOT-426 | 5 leads + tab as extra pin 6 |
| `TO-263-6` | 7 | 7 +4u | 14.95 x 10.0 | **D2PAK-7 / TO-263-7 / SOT-427** (tags) | 6 leads + tab numbered 4 |
| `TO-263-7_TabPin4` | 7 | 8 (+1 shorted) +4u | 14.95 x 10.0 | D2PAK-7 / SOT-427 | 7 leads + tab shorted to pin 4 |
| `TO-263-7_TabPin8` | 8 | 8 +4u | 14.95 x 10.0 | D2PAK-7 / SOT-427 | 7 leads + tab as extra pin 8 |
| `TO-263-9_TabPin5` | 9 | 10 (+1 shorted) +4u | 14.95 x 10.0 | **D2PAK-9 / TO-263-9** (tags) | 9 leads + tab shorted to pin 5 |
| `TO-263-9_TabPin10` | 10 | 10 +4u | 14.95 x 10.0 | D2PAK-9 / TO-263-9 | 9 leads + tab as extra pin 10 |
| `TO-268-2` | 3 | 3 +4u | 18.9 x 15.9 | **D3PAK / TO-268 / D3PAK-3 / TO-268-3** (tags) | 2 leads + tab numbered 2 |
| `TO-269AA` | 4 | 4 | 4.1 x 4.8 | **TO-269AA = MBS** (tags), Vishay diode bridge | 4 pins, no tab |
| `TO-277A` | 3 | 3 +9u | 4.3 x 6.1 | **TO-277A = SMPC** (tags), Vishay | 2 leads + tab numbered 3 |
| `TO-277B` | 3 | 3 +6u | 3.98 x 5.38 | TO-277B, Littelfuse DST2050S | 2 leads + tab numbered 3 |
| `TO-50-3_LongPad-NoHole_Housing` | 3 | 3 | n/a * | TO-50-3 Macro T, Package Style **M236** | 3 pins |
| `TO-50-3_LongPad-WithHole_Housing` | 3 | 3 +1u | n/a * | TO-50-3 Macro T / M236 | adds an unnumbered hole |
| `TO-50-3_ShortPad-NoHole_Housing` | 3 | 3 | n/a * | TO-50-3 Macro T / M236 |  |
| `TO-50-3_ShortPad-WithHole_Housing` | 3 | 3 +1u | n/a * | TO-50-3 Macro T / M236 | adds an unnumbered hole |
| `TO-50-4_LongPad-NoHole_Housing` | 4 | 4 | n/a * | TO-50-4 Macro X, Package Style **M238** | 4 pins |
| `TO-50-4_LongPad-WithHole_Housing` | 4 | 4 +1u | n/a * | TO-50-4 Macro X / M238 | adds an unnumbered hole |
| `TO-50-4_ShortPad-NoHole_Housing` | 4 | 4 | n/a * | TO-50-4 Macro X / M238 |  |
| `TO-50-4_ShortPad-WithHole_Housing` | 4 | 4 +1u | n/a * | TO-50-4 Macro X / M238 | adds an unnumbered hole |
| `PowerMacro_M234_NoHole` | 4 | 4 | n/a * | descr/tags: **TO-50-4** Power Macro, Package Style **M234** | a TO-50-4 land hiding under a non-`TO-` filename |
| `PowerMacro_M234_WithHole` | 4 | 4 +1u | n/a * | TO-50-4 Power Macro / M234 |  |
| `ATPAK-2` | 3 | 3 +4u | 9.5 x 6.5 | onsemi **ATPAK** | 2 leads + tab numbered 2 - same convention as `TO-252-2` |
| `LFPAK33` | 5 | 5 +12u | 2.6 x 3.3 | **LFPAK33 = SOT-1210** (descr/tags) | 4 leads + tab pin 5; no pin count in the name |
| `LFPAK56` | 5 | 5 +13u | 6.4 x 5.0 | **LFPAK56 = SOT-669 = Power-SO8** (tags) | 4 leads + tab pin 5 |
| `LFPAK88` | 5 | 19 (+14 shorted) | 8.0 x 8.0 | **LFPAK88 = PowerPAK 8x8L BWL Single = SOT-1235** (descr) | tab = pin 5, split into 15 pads |
| `Infineon_PG-HDSOP-10-1` | 10 | 10 | 20.96 x 6.5 | Infineon PG-HDSOP-10-1 = **DDPAK** (descr) | 10 pins, slug up |
| `Infineon_PG-TO-220-7Lead_TabPin8` | 8 | 8 +4u | 10.32 x 10.0 | Infineon PG-TO-220-7 | surface-mount TO-220-7, tab = pin 8 |

### F. Remaining `Package_TO_SOT_SMD.pretty` entries (vendor codes with no SOT/SOD/SC/TO name)

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `HVSOF5` | 5 | 5 | 1.2 x 1.6 | ROHM HVSOF5 | 5 pins |
| `HVSOF6` | 7 | 7 | 2.6 x 1.6 | ROHM HVSOF6 | **7** numbered pads despite the "6" in the name |
| `VSOF5` | 5 | 5 | 1.2 x 1.6 | ROHM VSOF5 | 5 pins |
| `Rohm_HRP7` | 7 | 65 (+58 shorted) +4u | 9.0 x 9.8 | ROHM HRP7 | 7 leads + thermal vias |
| `OnSemi_ECH8` | 8 | 8 | 2.3 x 2.9 | onsemi ECH8 = **SOT28-FL / SOT-28-FL** (tags) | 8 pins |
| `Infineon_PG-HSOF-8-1` | 3 | 3 +50u | 10.38 x 9.9 | Infineon PG-HSOF-8-1 = **TOLL** (descr) | 3 numbers, 53 pads total |
| `Infineon_PG-HSOF-8-1_ThermalVias` | 3 | 46 (+43 shorted) +50u | 10.38 x 9.9 | PG-HSOF-8-1 / TOLL | adds thermal vias |
| `Infineon_PG-HSOF-8-2` | 4 | 4 +8u | 10.38 x 9.9 | Infineon PG-HSOF-8-2 = TOLL | 4 numbers |
| `Infineon_PG-HSOF-8-2_ThermalVias` | 4 | 47 (+43 shorted) +50u | 10.38 x 9.9 | PG-HSOF-8-2 / TOLL |  |
| `Infineon_PG-HSOF-8-2_ThermalVias2` | 4 | 151 (+147 shorted) +8u | 10.38 x 9.9 | PG-HSOF-8-2 / TOLL | second, denser via pattern |
| `Infineon_PG-HSOF-8-3` | 4 | 4 +21u | 10.38 x 9.9 | Infineon PG-HSOF-8-3 |  |
| `Infineon_PG-HSOF-8-3_ThermalVias` | 4 | 43 (+39 shorted) +21u | 10.38 x 9.9 | PG-HSOF-8-3 |  |
| `Infineon_PG-TSFP-3-1` | 3 | 3 | 0.8 x 1.2 | Infineon PG-TSFP-3-1 | 3 pins |
| `Nexperia_CFP15_SOT-1289` | 3 | 3 +5u | 5.8 x 4.3 | **CFP15 = SOT-1289** (descr/tags) | 2 leads + tab |
| `PQFN_8x8` | 3 | 3 +6u | 8.0 x 8.0 | onsemi low-profile 8x8 mm PQFN, **Dual Cool 88** (descr) | 3 numbers |
| `TDSON-8-1` | 5 | 5 +9u | 5.9 x 5.15 | Infineon PG-TDSON-8-1 | 4 leads + tab pin 5 |
| `Texas_DDF0008A_SOT-8_1.6x2.9mm_P0.65mm` | 8 | 8 | 1.6 x 2.9 | TI DDF0008A, descr "SOT, 8 Pin" | SOT-23-8 land under a TI drawing code |
| `Texas_DRT-3` | 3 | 3 | 1.0 x 0.8 | TI DRT-3 | 3 pins, 0.7 mm pitch |
| `Texas_NDQ` | 6 | 6 | 14.01 x 10.16 | TI NDQ | descr says "5 pin" but there are **6** numbered pads (5 leads + tab 6) |
| `Texas_NDW-7_TabPin4` | 7 | 8 (+1 shorted) +4u | 13.77 x 10.16 | TI NDW0007A | 7 leads, tab shorted to pin 4 |
| `Texas_NDW-7_TabPin8` | 8 | 8 +4u | 13.77 x 10.16 | TI NDW0007A | 7 leads + tab as extra pin 8 |
| `Texas_NDY0011A` | 12 | 12 | 15.5 x 15.0 | TI **TO-PMOD-11** (descr) | 12 numbered pads |

### G. `SOD-*` - all live in `Diode_SMD.pretty`, all with the `D_` prefix

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `D_SOD-110` | 2 | 2 | 2.1 x 1.4 | SOD-110 | 2 terminals |
| `D_SOD-123` | 2 | 2 | 2.8 x 1.8 | SOD-123 |  |
| `D_SOD-123F` | 2 | 2 | 2.8 x 1.8 | SOD-123F (flat lead) |  |
| `D_SOD-128` | 2 | 2 | 3.8 x 2.5 | **SOD-128 = CFP5 = SlimSMAW** (descr) |  |
| `D_SOD-323` | 2 | 2 | 1.8 x 1.4 | SOD-323 |  |
| `D_SOD-323_HandSoldering` | 2 | 2 | 1.8 x 1.4 | SOD-323 | capital **S** |
| `D_SOD-323F` | 2 | 2 | 1.8 x 1.4 | SOD-323F (NXP flat lead) |  |
| `D_SOD-523` | 2 | 2 | 1.3 x 0.9 | SOD-523 (Diodes ap02001 p.144) |  |
| `D_SOD-882` | 2 | 2 +2u | 1.0 x 0.6 | **SOD-882 = DFN1006-2** (descr) | leadless, 0.65 mm pitch |
| `D_SOD-882D` | 2 | 2 +2u | 1.0 x 0.6 | **SOD-882D = DFN1006D-2** (descr) |  |
| `D_SOD-923` | 2 | 2 | 0.8 x 0.6 | SOD-923 (onsemi ESD9B) |  |
| `Nexperia_CFP3_SOD-123W` | 2 | 2 | 2.6 x 1.7 | **CFP3 = SOD-123W** (descr) | vendor-prefixed, so no `D_` |
| `Nexperia_DSN0603-2_0.6x0.3mm_P0.4mm` | 2 | 2 | 0.6 x 0.3 | **DSN0603-2 = SOD962-2** (descr) | SOD code appears only in descr |
| `Nexperia_DSN1608-2_1.6x0.8mm` | 2 | 2 | 1.6 x 0.8 | **DSN1608 = SOD964 / SOD-964** (descr+tags) |  |

### H. `SM*` bodies and their DO-214/219/220/221 equivalents (`Diode_SMD.pretty`)

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `D_SMA` | 2 | 2 | 4.6 x 3.0 | **SMA = DO-214AC** |  |
| `D_SMA_Handsoldering` | 2 | 2 | 4.6 x 3.0 | SMA = DO-214AC | lowercase **s** |
| `D_SMB` | 2 | 2 | 4.6 x 4.0 | **SMB = DO-214AA** |  |
| `D_SMB_Handsoldering` | 2 | 2 | 4.6 x 4.0 | SMB = DO-214AA | lowercase **s** |
| `D_SMB_Modified` | 3 | 3 | 4.6 x 4.0 | SMB = DO-214AA, Littelfuse SIDACtor "Modified DO-214" | **3** numbered pads |
| `D_SMC` | 2 | 2 | 7.1 x 6.2 | **SMC = DO-214AB** |  |
| `D_SMC_Handsoldering` | 2 | 2 | 7.1 x 6.2 | SMC = DO-214AB | lowercase **s** |
| `ST_D_SMC` | 2 | 2 | 6.88 x 5.9 | ST SMC = **JEDEC DO-214-D, variant AB** | vendor prefix *before* `D_` |
| `D_SMA-SMB_Universal_Handsoldering` | 2 | 2 | 4.6 x 4.0 | universal SMA (DO-214AC) **or** SMB (DO-214AA) | one land fits both |
| `D_SMB-SMC_Universal_Handsoldering` | 2 | 2 | 7.1 x 6.2 | universal SMB (DO-214AA) **or** SMC (DO-214AB) |  |
| `D_SMC-RM10_Universal_Handsoldering` | 2 | 2 | 7.1 x 6.2 | SMC (DO-214AB) on the **RM10** 10 mm grid, SMD + through-hole |  |
| `D_SMF` | 2 | 2 | 2.8 x 1.8 | **SMF = DO-219AB** (descr); the file's `tags` wrongly say DO-214AB | descr and tags disagree inside the file |
| `D_SMP_DO-220AA` | 2 | 2 | 4.0 x 2.18 | **SMP = DO-220AA** |  |
| `Vishay_SMPA` | 2 | 2 | 4.25 x 2.6 | **SMPA = DO-221BC** | vendor-prefixed, no `D_` |
| `D_MicroSMP_LargeAnode` | 2 | 2 | 2.2 x 1.3 | **MicroSMP = DO-219AD** | large pad is pad 2 = anode |
| `D_MicroSMP_LargeCathode` | 2 | 2 | 2.2 x 1.3 | MicroSMP = DO-219AD | large pad is pad 1 = cathode |

### I. MELF bodies (`Diode_SMD.pretty`)

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `D_MELF` | 2 | 2 | 5.2 x 2.6 | MELF | reflow land |
| `D_MELF_Handsoldering` | 2 | 2 | 5.2 x 2.6 | MELF | lowercase **s** |
| `D_MELF-RM10_Universal_Handsoldering` | 2 | 2 | 5.2 x 2.6 | MELF on the **RM10** 10 mm grid, SMD + through-hole |  |
| `D_MiniMELF` | 2 | 2 | 3.3 x 1.6 | **Mini-MELF = SOD-80 = LL-34** (descr); tags `LL34` |  |
| `D_MiniMELF_Handsoldering` | 2 | 2 | 3.3 x 1.6 | Mini-MELF = SOD-80 = LL-34 | lowercase **s** |
| `D_MicroMELF` | 2 | 2 | 1.9 x 1.15 | MicroMELF (Vishay BZM55) | descr says "Reflow Soldering" |
| `D_MicroMELF_Handsoldering` | 2 | 2 | 1.9 x 1.15 | MicroMELF | lowercase **s** |

**MELF cross-library note (verified in `Resistor_SMD.pretty`):** the same three bodies also ship as `R_MELF_MMB-0207`, `R_MiniMELF_MMA-0204`, `R_MicroMELF_MMU-0102`. They are *different lands* — `D_MELF` pads at x = ±2.4, size 1.5 x 2.7; `R_MELF_MMB-0207` pads at x = ±2.45, size 2.1 x 2.6.

### J. Other 2- and 3-terminal diode bodies, and the non-`D_` residue of `Diode_SMD.pretty`

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `D_SC-80` | 2 | 2 | 1.3 x 0.8 | **JEITA SC-80** (descr) | the only `SC-` name in Diode_SMD |
| `D_SC-80_HandSoldering` | 2 | 2 | 1.3 x 0.8 | JEITA SC-80 | capital **S** |
| `D_PowerDI-123` | 2 | 2 | 2.8 x 1.8 | Diodes Inc PowerDI-123 |  |
| `D_PowerDI-5` | 2 | 3 (+1 shorted) | 5.45 x 4.05 | Diodes Inc PowerDI5 | pad 2 split into two pads |
| `D_Powermite_LargeAnode` | 2 | 2 | 3.85 x 1.9 | Microsemi Powermite (onsemi 457-04) |  |
| `D_Powermite_LargeCathode` | 2 | 2 | 3.85 x 1.9 | Microsemi Powermite |  |
| `D_Powermite2_LargeAnode` | 2 | 2 | 6.42 x 4.06 | Microsemi Powermite 2 |  |
| `D_Powermite2_LargeCathode` | 2 | 2 | 6.42 x 4.06 | Microsemi Powermite 2 |  |
| `D_Powermite3` | 3 | 3 | 6.51 x 4.06 | Microsemi Powermite 3 | **3** numbered pads |
| `D_TUMD2` | 2 | 2 | 1.9 x 1.3 | ROHM TUMD2 |  |
| `D_QFN_3.3x3.3mm_P0.65mm` | 2 | 2 +1u | 3.3 x 3.3 | Wolfspeed C3D1P7060Q QFN diode | 2 numbers + 1 unnumbered pad |
| `Infineon_SG-WLL-2-3_0.58x0.28_P0.36mm` | 2 | 2 +2u | 0.58 x 0.28 | Infineon SG-WLL-2-3 |  |
| `ST_QFN-2L_1.6x1.0mm` | 2 | 2 | 1.6 x 1.0 | ST QFN-2L TVS |  |
| `Littelfuse_PolyZen-LS` | 3 | 3 | 4.0 x 4.0 | Littelfuse PolyZen LS | 3 numbered pads |
| `Diode_Bridge_Bourns_CD-DF4xxS` | 4 | 4 | 8.1 x 10.5 | Bourns CD-DF4xxSL | 4 pins |
| `Diode_Bridge_Diotec_ABS` | 4 | 4 | 4.4 x 5.0 | Diotec ABS; tags also say `MBLS` | 4 pins |
| `Diode_Bridge_Diotec_MicroDil_3.0x3.0x1.8mm` | 4 | 4 | 3.0 x 3.0 | Diotec MicroDil | 4 pins |
| `Diode_Bridge_Diotec_SO-DIL-Slim` | 4 | 4 | 6.4 x 8.4 | Diotec SO-DIL Slim; tags `DFS` | 4 pins |
| `Diode_Bridge_OnSemi_SDIP-4L` | 4 | 4 | 6.35 x 8.28 | onsemi SDIP-4L | 4 pins |
| `Diode_Bridge_Vishay_DFS` | 4 | 4 | 6.4 x 8.4 | Vishay DFS | 4 pins |
| `Diode_Bridge_Vishay_DFSFlat` | 4 | 4 | 6.4 x 8.4 | Vishay low-profile DFS | 4 pins |
| `Diode_Bridge_Vishay_MBLS` | 4 | 4 | 4.8 x 5.2 | Vishay MBLS | 4 pins |

### K. Chip (rectangular 2-terminal) diode bodies (`Diode_SMD.pretty`)

| Footprint (verbatim filename, `.kicad_mod` omitted) | Pins | Numbered pads | Body from F.Fab (mm) | Alias / JEDEC-JEITA cross-reference | Notes |
|---|---|---|---|---|---|
| `D_01005_0402Metric` | 2 | 2 +2u | 0.4 x 0.2 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_01005_0402Metric_Pad0.57x0.30mm_HandSolder` | 2 | 2 +2u | 0.4 x 0.2 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_0201_0603Metric` | 2 | 2 +2u | 0.6 x 0.3 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_0201_0603Metric_Pad0.64x0.40mm_HandSolder` | 2 | 2 +2u | 0.6 x 0.3 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_0402_1005Metric` | 2 | 2 | 1.0 x 0.5 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_0402_1005Metric_Pad0.77x0.64mm_HandSolder` | 2 | 2 | 1.0 x 0.5 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_0603_1608Metric` | 2 | 2 | 1.6 x 0.8 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_0603_1608Metric_Pad1.05x0.95mm_HandSolder` | 2 | 2 | 1.6 x 0.8 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_0805_2012Metric` | 2 | 2 | 2.0 x 1.2 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_0805_2012Metric_Pad1.15x1.40mm_HandSolder` | 2 | 2 | 2.0 x 1.2 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_1206_3216Metric` | 2 | 2 | 3.2 x 1.6 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_1206_3216Metric_Pad1.42x1.75mm_HandSolder` | 2 | 2 | 3.2 x 1.6 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_1210_3225Metric` | 2 | 2 | 3.2 x 2.5 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_1210_3225Metric_Pad1.42x2.65mm_HandSolder` | 2 | 2 | 3.2 x 2.5 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_1812_4532Metric` | 2 | 2 | 4.5 x 3.2 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_1812_4532Metric_Pad1.30x3.40mm_HandSolder` | 2 | 2 | 4.5 x 3.2 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_2010_5025Metric` | 2 | 2 | 5.0 x 2.5 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_2010_5025Metric_Pad1.52x2.65mm_HandSolder` | 2 | 2 | 5.0 x 2.5 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_2114_3652Metric` | 2 | 2 | 5.2 x 3.6 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_2114_3652Metric_Pad1.85x3.75mm_HandSolder` | 2 | 2 | 5.2 x 3.6 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_2512_6332Metric` | 2 | 2 | 6.3 x 3.2 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_2512_6332Metric_Pad1.52x3.35mm_HandSolder` | 2 | 2 | 6.3 x 3.2 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |
| `D_3220_8050Metric` | 2 | 2 | 8.0 x 5.0 | imperial code + `_<metric>Metric`, IPC-7351 nominal | reflow (nominal) land |
| `D_3220_8050Metric_Pad2.65x5.15mm_HandSolder` | 2 | 2 | 8.0 x 5.0 | imperial code + `_<metric>Metric`, IPC-7351 nominal | hand-solder form spelled `_Pad<W>x<H>mm_HandSolder` |

---

## The `D_` prefix rule for 2-terminal diode packages

**Rule.** Every generic surface-mount diode *body* in `Diode_SMD.pretty` is named `D_<body>` — 67 of the library's 83 files. The prefix is the schematic reference-designator letter, and it is a **land-pattern class marker, not decoration**: the same physical body ships once per designator, with a different land each time.

Verified proof (geometry read out of the shipped files):

| Body | Diode version | Resistor version (`Resistor_SMD.pretty`) |
|---|---|---|
| MELF | `D_MELF` — pads at x = ±2.4, size 1.5 x 2.7 | `R_MELF_MMB-0207` — pads at x = ±2.45, size 2.1 x 2.6 |
| Mini-MELF | `D_MiniMELF` — ±1.75, size 1.3 x 1.7 | `R_MiniMELF_MMA-0204` — ±1.5, size 1.5 x 1.8 |
| MicroMELF | `D_MicroMELF` — ±0.8, size 0.8 x 1.2 | `R_MicroMELF_MMU-0102` — ±0.95, size 1.2 x 1.5 |
| 0603 chip | `D_0603_1608Metric` — pad 1 at −0.7875, size 0.875 x 0.95 | `R_0603_1608Metric` — pad 1 at −0.825, size 0.8 x 0.95 |

**Why no pin count ever appears after `D_`.** The designator fixes the terminal count at 2 *and* fixes what the pad numbers mean, so a count would carry no information. The fixed mapping is **pad 1 = cathode, pad 2 = anode**, confirmed two independent ways:

1. **F.Fab polarity glyph.** Every `D_` footprint draws a diode symbol on `F.Fab` inside the body rectangle. In `D_SOD-123` the cathode bar is the segment at x = −0.35 (`(-0.35 0)→(-0.35 -0.55)` and `(-0.35 0)→(-0.35 0.55)`) and the triangle apex `(-0.35 0)` touches it, so the cathode is on the −x side — where pad 1 sits, at x = −1.65. (This glyph is also why `D_` footprints carry noticeably more `F.Fab` geometry than their `R_` twins: 7 objects vs 3 for 0603.)
2. **The `_LargeAnode` / `_LargeCathode` pairs.** `D_MicroSMP_LargeCathode` gives pad **1** the big pad (`(at -0.88 0) (size 2 1.1)`) while `D_MicroSMP_LargeAnode` gives it to pad **2** (`(at 0.88 0) (size 2 1.1)`). Identically for `D_Powermite_LargeCathode`/`_LargeAnode` and `D_Powermite2_LargeCathode`/`_LargeAnode`.

**Consequences.** A digit after a `D_` body is never a KiCad-appended pin count — it is always part of the vendor's own body name: `D_PowerDI-5`, `D_PowerDI-123`, `D_Powermite2`, `D_Powermite3` (Microsemi generation numbers — `D_Powermite2` has 2 pads and `D_Powermite3` has 3, which is coincidence, not a rule), `D_SOD-882D`, `D_SMP_DO-220AA`. When a "2-terminal" body genuinely gains a third pad, the count still is not appended: `D_SMB_Modified` (3 pads) and `D_Powermite3` (3 pads).

**Exceptions to `D_` (16 files, all verified).** A manufacturer prefix outranks it: `Nexperia_CFP3_SOD-123W`, `Nexperia_DSN0603-2_0.6x0.3mm_P0.4mm`, `Nexperia_DSN1608-2_1.6x0.8mm`, `Vishay_SMPA`, `Infineon_SG-WLL-2-3_0.58x0.28_P0.36mm`, `ST_QFN-2L_1.6x1.0mm`, `Littelfuse_PolyZen-LS`, the eight `Diode_Bridge_*` names, and one hybrid where the vendor prefix sits *in front of* `D_`: `ST_D_SMC`.

---

## `_Handsoldering` vs `_HandSoldering` vs `_HandSolder` — the actual situation in these two libraries

Three spellings coexist; **40 of the 220 files** carry a hand-solder token, and the token is always the last one in the name.

| Spelling | `Package_TO_SOT_SMD.pretty` | `Diode_SMD.pretty` | Total |
|---|---|---|---|
| `_Handsoldering` (lowercase **s**) | **11** | **10** | 21 |
| `_HandSoldering` (capital **S**) | **5** | **2** | 7 |
| `_HandSolder` (capital **S**, no `-ing`) | **0** | **12** | 12 |
| **any hand-solder token** | **16** | **24** | **40** |

**`Package_TO_SOT_SMD.pretty` — `_Handsoldering` (11):** `SC-59_Handsoldering`, `SC-82AA_Handsoldering`, `SC-82AB_Handsoldering`, `SOT-143R_Handsoldering`, `SOT-143_Handsoldering`, `SOT-23-6_Handsoldering`, `SOT-23-8_Handsoldering`, `SOT-23W_Handsoldering`, `SOT-23_Handsoldering`, `SOT-89-3_Handsoldering`, `SOT-89-5_Handsoldering`

**`Package_TO_SOT_SMD.pretty` — `_HandSoldering` (5):** `SOT-23-5_HandSoldering`, `TSOT-23-5_HandSoldering`, `TSOT-23-6_HandSoldering`, `TSOT-23-8_HandSoldering`, `TSOT-23_HandSoldering`

**`Diode_SMD.pretty` — `_Handsoldering` (10):** `D_MELF-RM10_Universal_Handsoldering`, `D_MELF_Handsoldering`, `D_MicroMELF_Handsoldering`, `D_MiniMELF_Handsoldering`, `D_SMA-SMB_Universal_Handsoldering`, `D_SMA_Handsoldering`, `D_SMB-SMC_Universal_Handsoldering`, `D_SMB_Handsoldering`, `D_SMC-RM10_Universal_Handsoldering`, `D_SMC_Handsoldering`

**`Diode_SMD.pretty` — `_HandSoldering` (2):** `D_SC-80_HandSoldering`, `D_SOD-323_HandSoldering`

**`Diode_SMD.pretty` — `_HandSolder` (12):** all twelve chip-size diodes, each preceded by a `_Pad<W>x<H>mm` token — `D_01005_0402Metric_Pad0.57x0.30mm_HandSolder` … `D_3220_8050Metric_Pad2.65x5.15mm_HandSolder`

**The split is not by library or by family — it is per file.** Inside the single SOT-23 family the spelling flips mid-sequence: `SOT-23_Handsoldering` (lowercase) and `SOT-23-6_Handsoldering` / `SOT-23-8_Handsoldering` (lowercase) but `SOT-23-5_HandSoldering` (capital). All five TSOT-23 files use the capital form. The reverse holds in `Diode_SMD.pretty`: the older named bodies (MELF, SMA/SMB/SMC) are lowercase, while the two newer ones (`D_SC-80_HandSoldering`, `D_SOD-323_HandSoldering`) are capital.

Directory-level check: no two names in either library differ **only** by case, so there are no true collisions — but see the case-insensitivity pitfall below.

## How to name a new part in this family

## Naming a part in this family that is not already in the table

**Step 1 — Search stock by every code on the datasheet, not just the headline one.** Package pages routinely print two or three codes (`SOT-363`, `SC-70-6`, `SC-88`, `US6`, `UMT6`, `TSSOP6` are all the same body). Grep names *and* the `descr`/`tags` fields, because half the aliases live only in metadata:
```bash
cd "/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints"
grep -ril "SOT-563\|MO-293\|DRL-6" Package_TO_SOT_SMD.pretty Diode_SMD.pretty
ls -1 Package_TO_SOT_SMD.pretty Diode_SMD.pretty | grep -i "563"
```
If a hit exists, reuse it and record the alias — do not add a synonym-named duplicate.

**Step 2 — Decide the base token, in this order of preference.**
1. A JEDEC / JEITA-EIAJ registered code, if the datasheet cites one: `SOT-…`, `SC-…`, `TO-…`.
2. Otherwise the NXP/Philips-style `SOT-<3–4 digits>` code if the vendor prints one (Nexperia and Toshiba usually do).
3. Otherwise `Vendor_<vendor drawing code>` with the vendor first, matching the 39 vendor-prefixed files in stock (`Texas_R-PDSO-N6_DRL-6`, `Infineon_PG-HSOF-8-2`, `Nexperia_CFP15_SOT-1289`, `Vishay_PowerPAK_SC70-6L_Single`). Vendor names in stock are spelled `Analog_`, `Diodes_`, `Infineon_`, `Littelfuse_`, `Nexperia_`, `OnSemi_`, `ROHM_`/`Rohm_`, `ST_`, `Texas_`, `Vishay_`.
4. If the JEDEC code and the vendor code are both meaningful, put the JEDEC code as a trailing alias token, exactly as stock does: `Texas_R-PDSO-N5_DRL-5`, `Nexperia_CFP3_SOD-123W`, `SOT-323_SC-70`.

**Step 3 — Decide whether to append `-N`.** Apply the clauses in the grammar field:
- Does the base token already imply exactly one lead count (NXP `SOT-xx3/xx4/xx5/xx6`, `SOT-143`, `SOT-416`, `SOT-723`, `SOT-883`)? → **no suffix**.
- Does your part share a base with an existing footprint of a *different* lead count? → **append `-N`**, and if the existing sibling is an unsuffixed legacy name, leave that name alone (as `SOT-23` and `SOT-23-3` coexist).
- Does the *vendor* print the count as part of the name (`SOT-583-8`, `SOT-223-5`, `SC-70-8`)? → **keep the vendor's digits verbatim**, including any count that duplicates the tab.
- Is the trailing digit an issue/revision/generation index (`SOT-1333-1`, `PG-HSOF-8-2`, `Powermite3`)? → keep it, but never treat it as a count and never "correct" it.

**Step 4 — Handle a thermal tab.** Two shapes only:
- Tab occupies a lead position that has no lead → give the tab that lead's number and put the **lead count** in `-N` (`TO-252-2`, `TO-252-4`, `TO-263-6`, `ATPAK-2`).
- Full lead row plus a tab → append `_TabPin<n>`: the same number as a lead if the datasheet shorts them (`TO-252-3_TabPin2`), or the next free number if the tab is its own net (`TO-252-3_TabPin4`, `Infineon_PG-TO-220-7Lead_TabPin8`).
- Thermal-via variants get a **separate file** suffixed `_ThermalVias` (or `_ThermalVias2` for a second pattern), as with `Infineon_PG-HSOF-8-2_ThermalVias`.

**Step 5 — Add disambiguating size/pitch only when needed.** When two lands share a base, stock appends `_<W>x<H>mm` then `_P<pitch>mm` in that order: `SC-74-6_1.55x2.9mm_P0.95mm`, `Texas_DDF0008A_SOT-8_1.6x2.9mm_P0.65mm`, `Nexperia_DSN0603-2_0.6x0.3mm_P0.4mm`. Do not add them "for information" if the base is already unique.

**Step 6 — Hand-solder twin, if you make one.** The token is always last. Pick the spelling by matching the family you are joining, not by preference: TSOT-23 uses `_HandSoldering`; SOT-23/SOT-89/SOT-143/SC-59/SC-82 use `_Handsoldering`; chip-size diode bodies use `_Pad<W>x<H>mm_HandSolder`. For an entirely new family, prefer `_HandSolder` — it is the spelling used by the generator-produced chip footprints and by the rest of the modern KiCad libraries.

**Step 7 — A 2-terminal diode body.** Use `D_<body>` in `Diode_SMD.pretty`, wire pad 1 = cathode / pad 2 = anode, draw the diode glyph on `F.Fab`, and append no count. If one terminal is enlarged, add `_LargeAnode` or `_LargeCathode` and ship both. If a manufacturer prefix is warranted, it goes ahead of everything (`ST_D_SMC` keeps `D_`; `Vishay_SMPA` drops it).

**Step 8 — When the package is genuinely absent from KiCad stock.** All 220 stock names are listed above, so absence is easy to establish. Then:
1. Re-check the two adjacent libraries before authoring — `Package_TO_SOT_THT.pretty` (`SOT-227`, `SOD-70_P2.54mm`, `SIPAK_Vertical`, `SIPAK-1EP_Horizontal_TabDown`), `Package_SO.pretty` (`Texas_DYY0016A_TSOT-23-16_2x4.2mm_P0.5mm`, `PowerPAK_SO-8_Single`, `PowerPAK_SO-8_Dual`, `PowerPAK_SO-8L_Single`, `Vishay_PowerPAK_1212-8_Single`, `Vishay_PowerPAK_1212-8_Dual`), `Package_DFN_QFN.pretty` (`Vishay_PowerPAK_MLP44-24L` and siblings), `Package_SON.pretty`, `Resistor_SMD.pretty` (the `R_*MELF*` twins). Several packages people assume are in `Package_TO_SOT_SMD` are actually in one of these.
2. Author it in the house `7Sigma:` namespace per `kicad-conventions-footprints`, but build the *name* with the grammar above so it reads as a sibling of stock. Concretely, for a hypothetical 4-pin SOT-457 variant: base `SOT-457` is already single-valued and taken by `SOT-457T`, so you would name a vendor-specific land `Vendor_SOT-457_<distinguisher>`, not `SOT-457-4`.
3. If the datasheet supplies a JEDEC/JEITA number, put it in `descr` in the same phrasing stock uses — `"SOT, 6 Pin (JEDEC MO-xxx Var AB <url>)"` — and put every alias you found in `tags`. That is what makes the next person's Step 1 grep succeed.
4. Never invent an alias equality. If you cannot show the alias in a datasheet or a standards document, write it in `descr` as unverified or leave it out.

## Pitfalls

## Traps

**1. `SOT-23` and `SOT-23-3` are both 3-pin and both exist — and they are different lands.** Bare `SOT-23` is JEDEC TO-236 Var AB, F.Fab body 1.3 x 2.9 mm, pad 1 at x = −0.9375 with size 1.475 x 0.6. `SOT-23-3` is the MO-178 body, 1.6 x 2.9 mm, pad 1 at x = −1.1375 with size 1.325 x 0.6. Picking "SOT-23" for an MO-178 5/6/8-pin-family 3-pin part gives you a land 0.4 mm shorter overall. The same split exists for `TSOT-23` (1.76 x 2.9 mm) vs `TSOT-23-5/-6/-8` (1.6 x 2.9 mm).

**2. macOS/Windows will silently accept the wrong hand-solder spelling; Linux will not.** APFS is case-insensitive, so `test -f D_SMA_HandSoldering.kicad_mod` returns *true* even though the real file is `D_SMA_Handsoldering.kicad_mod`. Any script that resolves footprint names via the filesystem will pass locally and fail in CI or on a Linux build host. Verify names against an exact-case directory listing, never `test -f`. Within the SOT-23 family alone the spelling flips: `SOT-23-5_HandSoldering` (capital S) but `SOT-23-6_Handsoldering` and `SOT-23-8_Handsoldering` (lowercase s).

**3. `DPAK`, `D2PAK`, `D3PAK` and `DDPAK` are not filenames — they are only `tags`.** Verified absent as files: `DPAK`, `DPAK-3`, `D2PAK`, `D2PAK-3`, `D3PAK`. The real names are `TO-252-*`, `TO-263-*`, `TO-268-2`. The only `*PAK` filenames in `Package_TO_SOT_SMD.pretty` are `ATPAK-2`, `LFPAK33`, `LFPAK56`, `LFPAK88`, `Vishay_PowerPAK_SC70-6L_Dual`, `Vishay_PowerPAK_SC70-6L_Single`; the two `Heatsink.pretty` hits (`Heatsink_Fischer_FK24413DPAK_23x13mm`, `Heatsink_Fischer_FK24413D2PAK_26x13mm`) are heatsinks, not packages.

**4. `-N` means LEAD count for TO-252/TO-263/TO-268/ATPAK but TOTAL pin count for SOT-223.** `TO-252-4` has five numbered pads (4 leads + tab as pin 3); `SOT-223-5` has five numbered pads *including* the tab (4 leads + tab as pin 5). Do not normalise either one.

**5. `TO-252-3_TabPin4` and `TO-252-4` both end up with 4 numbers but are different lands.** The first is the DPAK-3 land (2.28 mm lead grid, tab is an extra pin 4); the second is the DPAK-5 land (1.14 mm lead grid, tab is pin 3). Same trap for `TO-263-3_TabPin4` vs `TO-263-4` and `TO-263-7_TabPin8` vs `TO-263-6`.

**6. Names whose digits contradict their pad count.** `HVSOF6` has **7** numbered pads. `SOT-383F` has **9** (descr says "8-pin SOT-383F"). `Texas_NDQ` has **6** (descr says "5 pin"). `SOT-1333-1` has 9 and `SOT-1334-1` has 14 — the trailing `-1` is an NXP issue number. `Infineon_PG-HSOF-8-1/-2/-3` have 3, 4 and 4 numbers respectively, not 8. Always count pads; never trust the digits.

**7. Reverse-pinning and rotation twins.** `SOT-143` and `SOT-143R` are mirror-images (the file's own tags say "Reverse"), and `SOT-143` is drawn portrait (F.Fab 1.3 x 2.9) while `SOT-143R` is landscape (2.9 x 1.3). `ROHM_SOT-457_ClockwisePinNumbering` is `SOT-457T` with the numbering reversed. `SC-82AA` vs `SC-82AB` differ only in pad height (0.4 vs 0.5 mm). None of these will DRC-fail — they just wire up wrong.

**8. A footprint's `descr` and `tags` can disagree with each other.** `D_SMF` says `(descr "Diode SMF (DO-219AB) …")` but `(tags "Diode SMF (DO-214AB)")`. Trust `descr` (it carries the datasheet URL) and treat `tags` as search keywords only.

**9. "Similar to" is a warning, not an alias.** `Texas_R-PDSO-N6_DRL-6` says "similar to JEDEC MO-293B Var UAAD (**but not the same**)" — so it is *not* interchangeable with `SOT-563`, even though both are 6-pin 1.2 x 1.6 mm. Likewise `Diodes_SOT-553` (F.Fab 1.25 x 1.7) is a vendor land distinct from generic `SOT-553` (1.2 x 1.6), and `ST_D_SMC` (6.88 x 5.9) is wider than `D_SMC` (7.1 x 6.2 body but a different pad span, 6.65 vs 6.8 mm centre-to-centre).

**10. There is no bare `SOT-89`, `SC-70`, `SOT-323`, `SOT-353`, `SOT-363`, `SOD-123`, `SMA`, `SMB` or `SMC`.** All verified absent. SC-70 members are only reachable through the SOT alias filenames (`SOT-323_SC-70`, `SOT-343_SC-70-4`, `SOT-353_SC-70-5`, `SOT-363_SC-70-6`) plus `SC-70-8`; diode bodies are only reachable with the `D_` prefix. Searching for the plain code returns nothing and people conclude the package is missing.

**11. Family members hide in other libraries.** `TSOT-23-16` is `Texas_DYY0016A_TSOT-23-16_2x4.2mm_P0.5mm` in `Package_SO.pretty`. `SOT-227`, `SOD-70_P2.54mm`, `SOD-70_P5.08mm`, `SIPAK_Vertical`, `SIPAK-1EP_Horizontal_TabDown` are through-hole, in `Package_TO_SOT_THT.pretty`. PowerPAK SO-8 forms are in `Package_SO.pretty`; PowerPAK MLP forms in `Package_DFN_QFN.pretty`; MELF resistors in `Resistor_SMD.pretty`. `NXP_SOT1982-1_…` and `NXP_SOT2162-1_…` are BGAs in `Package_BGA.pretty`, and `NXP_SOT1444-5_…`, `NXP_SOT1450-2_…` are WLCSPs in `Package_CSP.pretty` — a `SOT-` prefix does not mean small-outline transistor.

**12. Imperial/metric confusion in the diode chip names.** `D_0603_1608Metric` is imperial 0603 = metric 1608. The metric-1608 *name* 0603 also exists as a different physical size in the metric world (metric 0603 = imperial 0201, which here is `D_0201_0603Metric`). Read the whole token pair; both numbers are always present, and the leading one is always imperial.

**13. Pad-count fields in this table are not pad-object counts.** `LFPAK88` has 5 pins but 19 numbered pad objects (the pin-5 drain is split into 15). `Infineon_PG-HSOF-8-2_ThermalVias2` has 4 pins and 151 numbered pads. `Rohm_HRP7` has 7 pins and 65 numbered pads. Netlist tools care about the pin count; DFM and paste tools care about the pad objects.

**14. `PowerMacro_M234_NoHole` / `_WithHole` are TO-50-4 lands.** Their own `descr` reads "TO-50-4 Power Macro Package Style M234". Searching `TO-50` by filename misses them.

**15. Ten footprints have an unusable `F.Fab` body box.** For all eight `TO-50-*_Housing` files and both `PowerMacro_M234_*` files, `F.Fab` holds only a partial marking (bbox ≈ 0.05 x 2.55 mm), so a body dimension cannot be read off that layer — shown as `n/a *` in the table. Get the body from the datasheet instead.


---


# Gull-wing IC packages — SOIC / SO / SOP / SSOP / TSSOP / MSOP / VSSOP / HTSSOP / HVSSOP / QSOP / TSOP / QFP / LQFP / TQFP (KiCad `Package_SO.pretty` + `Package_QFP.pretty`)

**Backed by:** **503 shipped footprint files**, all read and accounted for: **401** in `/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Package_SO.pretty` and **102** in `.../Package_QFP.pretty`.

The table below covers **all 503** in **410 rows**: 408 rows are plain names, 93 `_ThermalVias` duplicates are folded into the final column rather than given their own rows, and 2 rows are footprints that exist *only* in a `_ThermalVias` form. Coverage was asserted programmatically (503 of 503, no file counted twice), and every name in the table was individually re-tested with `test -f` before being printed.

## Grammar

# Universal skeleton

```
[<Vendor>_][<VendorPkgCode>_]<FAMILY>-<PINS>[<BodyCode>][-<FittedPins>][-1EP]
   _<W>x<L>mm _P<pitch>mm
   [_EP<w>x<l>mm] [_Mask<w>x<l>mm] [_TopEP<w>x<l>mm]
   [_SlugUp|_SlugDown] [_Clearance<n>mm] [_Reverse] [_ThermalVias]
```

Verified mechanically over all 503 shipped files — zero violations of any of these
ordering rules:

* `-1EP` is **always** glued to the pin count, before the first `_`.
* `_P<pitch>mm` **always** immediately follows the body size.
* `_EP…` **always** comes after `_P…`.
* `_Mask…` **always** comes after `_EP…`, and never appears without an `_EP…`.
* `_ThermalVias` is **always** the final token.

# Body size: WxL, and what W and L actually mean

The rule is positional in footprint coordinates, not semantic:

* **first number = X extent of the `F.Fab` body outline = the dimension ACROSS the
  lead rows** (JEDEC `E1`, body width).
* **second number = Y extent = the dimension ALONG the lead rows** (JEDEC `D`,
  body length).

Confirmed by comparing every name against its own `F.Fab` bounding box: 494 of the
503 files match to ±0.06 mm. So `SOIC-8_3.9x4.9mm_P1.27mm` = 3.9 mm across the two
4-pin rows, 4.9 mm along them. Leads are never included.

Consequences worth internalising:

* For **SOIC/SO/SOP/SSOP/TSSOP/MSOP/QSOP** (leads on the two long edges) the first
  number is the *smaller* one — `4.4x9.7mm`, `7.5x17.9mm`.
* For **TSOP-I** (leads on the two SHORT edges) the same X-then-Y rule makes the
  first number the *larger* one — `TSOP-I-32_18.4x8mm_P0.5mm` really is 18.4 mm
  across the rows, 8 mm along them. It is not a reversed name.
* For **QFP** both numbers are body edges, X then Y. Square parts are unambiguous
  (`10x10mm`); rectangular ones are X-then-Y (`PQFP-100_14x20mm_P0.65mm`,
  `LQFP-128_14x20mm_P0.5mm` — 14 mm horizontal, 20 mm vertical).
* One file carries a third number = body **height**:
  `SSOP-8_3.95x5.21x3.27mm_P1.27mm`.

# Where the pitch sits

Always the token straight after the body size: `_P<value>mm`, value in mm, decimal
point, no unit prefix, no trailing zeros. Distinct pitch tokens actually in stock:

`P0.4` (33) · `P0.5` (129) · `P0.55` (1) · `P0.635` (15) · `P0.65` (135) ·
`P0.75` (1) · `P0.762` (1) · `P0.8` (18) · `P0.95` (2) · `P1` (4) · `P1.00` (1) ·
`P1.27` (104) · `P2.54` (15) · `P4` (1)

Five files have a body size but **no** pitch token at all — all Infineon PG-DSO
(`Infineon_PG-DSO-8-24_4x5mm`, `Infineon_PG-DSO-8-59_7.5x6.3mm`,
`Infineon_PG-DSO-20-U03_7.5x12.8mm`,
`Infineon_PG-DSO-8-27_3.9x4.9mm_EP2.65x3mm` and its `_ThermalVias` twin).

# Per sub-family grammar

| Sub-family | Grammar | Body order | Pitch position | Notes from stock |
|---|---|---|---|---|
| `SOIC` | `SOIC-<pins>[W][-<fitted>][-1EP]_<W>x<L>mm_P1.27mm[_EP…][_Mask…][_ThermalVias]` | WxL (W = across rows) | after body | Narrow bodies 3.9 / 4.55 / 5.3 mm; wide body flagged `W`, 7.5 mm. Pitch is 1.27 mm on all but 3 files (`_P2.54mm` ×2, `_P1mm` ×1). |
| `SO` | `SO-<pins>[L|B|C|FL][-<fitted>][-1EP]_<W>x<L>mm_P<pitch>mm[…]` | WxL | after body | No `W` code exists for `SO-`; width is carried only by the number. |
| `SOP` / `PSOP` | `SOP-<pins>[-1EP]_<W>x<L>mm_P<pitch>mm[…]` | WxL | after body | All 1.27 or 2.54 mm pitch. `PSOP` = 1 file. |
| `SSOP` | `SSOP-<pins>[-1EP]_<W>x<L>mm_P<pitch>mm[…]` | WxL | after body | Pitch 0.5 / 0.635 / 0.65 / 0.8 / 1 / 1.27 mm. Widths 2.95→8.8 mm. |
| `QSOP` | `QSOP-<pins>_<W>x<L>mm_P0.635mm` | WxL | after body | Only 4 files, **all** 3.9 mm wide, **all** 0.635 mm pitch, no EP variants. |
| `TSSOP` | `TSSOP-<pins>[-1EP]_<W>x<L>mm_P<pitch>mm[_EP…][_Mask…][_ThermalVias]` | WxL | after body | Widths 3 / 4.4 / 6.1 / 8 mm; pitch 0.4 / 0.5 / 0.65 mm (+ one joke file `TSSOP-4_4.4x5mm_P4mm`). |
| `HTSSOP` / `ETSSOP` | `HTSSOP-<pins>[-1EP]_<W>x<L>mm_P<pitch>mm_EP<w>x<l>mm[_Mask…][_ThermalVias]` — or `_TopEP…` for a top-side slug | WxL | after body | The leading `H`/`E` *is* the "has a slug" marker; nearly all also carry `-1EP`. |
| `MSOP` | `MSOP-<pins>[-<fitted>][-1EP]_3x3mm|3x4.039mm_P0.5mm|0.65mm[_EP…][_Mask…][_ThermalVias]` | WxL | after body | Only two body sizes in stock: `3x3mm` (8/10 pin) and `3x4.039mm` (12/16 pin). |
| `VSSOP` | `VSSOP-<pins>[-1EP]_<W>x<L>mm_P<pitch>mm[_EP…][_Mask…]` | WxL | after body | Bare `VSSOP` = 2 files. All EP-bearing VSSOP names are TI-prefixed (`Texas_DGN0008x_…`). |
| `HVSSOP` | `HVSSOP-<pins>-1EP_3x3mm_P<pitch>mm_EP<w>x<l>mm[_ThermalVias]` | WxL | after body | 4 files only; slug always present. |
| `TSOP` | `TSOP-<pins>_<W>x<L>mm_P0.95mm` | WxL | after body | Only the SOT-23-ish 5/6-pin parts use the bare `TSOP-` form. |
| `TSOP-I` | `TSOP-I-<pins>_<W>x<L>mm_P<pitch>mm[_Reverse]` | WxL, first number is the LONG axis (leads on short edges) | after body | `_Reverse` = same part rotated 90°, so its name no longer matches XY. |
| `TSOP-II` | `TSOP-II-<pins>[-<fitted>]_<a>x<b>mm_P<pitch>mm` | **inconsistent** — see pitfalls | after body | 2 of 4 files are WxL, 2 are LxW. |
| `LQFP` / `TQFP` / `PQFP` / `EQFP` / `HTQFP` | `<PREFIX>QFP-<pins>[-1EP]_<X>x<Y>mm_P<pitch>mm[_EP<w>x<l>mm][_Mask…][_ThermalVias]` | X then Y (both are body edges) | after body | Prefix encodes height class, not lead form: L = low-profile 1.4 mm, T = thin 1.0 mm, P = plastic (tall, legacy), E = exposed-pad, HT = thermally enhanced. |

# Optional-token semantics

| Token | Meaning | Verified example |
|---|---|---|
| `W` after pin count | wide body variant (SOIC only) | `SOIC-20W_7.5x12.8mm_P1.27mm` |
| `L`, `B`, `C`, `FL` after pin count | vendor body-shape letters | `SO-6L_10x3.84mm_P1.27mm`, `PowerIntegrations_SO-8B`, `ONSemi_SO-8FL_488AA` |
| `-<N>` second number | **depopulated** land pattern: outline of an N₁-pin package with only N₂ pads | `SOIC-16W-12_7.5x10.3mm_P1.27mm` (16-pin body, 12 pads), `SOIC-14-16_3.9x9.9mm_P1.27mm` (14 pads in a 16-pin body), `Analog_MSOP-12-16_3x4.039mm_P0.5mm`, `Linear_HTSSOP-31-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm` |
| `-N7` | single named pin removed | `SOIC-8-N7_3.9x4.9mm_P1.27mm` (pin 7 depopulated) |
| `-1EP` | one exposed thermal pad, counted as pad "9"/"33"/… | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm` |
| `_EP<w>x<l>mm` | copper size of that pad | `TQFP-64-1EP_10x10mm_P0.5mm_EP5.305x5.305mm` |
| `_Mask<w>x<l>mm` | solder-mask/paste aperture *smaller* than the copper EP (TI-style split paste) | `HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3.4x6.5mm_Mask2.96x2.96mm` |
| `_TopEP<w>x<l>mm` | slug is on the **top** of the body — no copper pad needed, documentation only | `HTSSOP-44_6.1x14mm_P0.635mm_TopEP4.14x7.01mm` |
| `_SlugUp` / `_SlugDown` | which face the heat slug is on (PowerSO/HSOP style) | `HSOP-20-1EP_11.0x15.9mm_P1.27mm_SlugUp` / `…_SlugDown` |
| `_Clearance<n>mm` | creepage-rated variant, pad rows pushed apart (optocouplers) | `SSO-8_6.8x5.9mm_P1.27mm_Clearance8mm` |
| `_Reverse` | mirrored/rotated pin-1 orientation | `TSOP-I-32_18.4x8mm_P0.5mm_Reverse` |
| `_ThermalVias` | identical to the base footprint plus a via array in the EP | `LQFP-64-1EP_10x10mm_P0.5mm_EP5x5mm_ThermalVias` |

## Reference table

All names below are verbatim shipped filenames minus the `.kicad_mod` extension. The last column tells you whether appending `_ThermalVias` yields another real file.

### SOIC — narrow body and wide body (`W`) — 48 files

| Family | Pins | Body WxL (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| Infineon SOIC | 20W | 7.6x12.8 | 1.27mm | no | wide body `W` | `Infineon_SOIC-20W_7.6x12.8mm_P1.27mm` | no |
| JEITA SOIC | 16 | 3.9x9.9 | 1.27mm | no | JEITA/EIAJ land pattern | `JEITA_SOIC-16_3.9x9.9mm_P1.27mm` | no |
| JEITA SOIC | 8 | 3.9x4.9 | 1.27mm | no | JEITA/EIAJ land pattern | `JEITA_SOIC-8_3.9x4.9mm_P1.27mm` | no |
| onsemi SOIC (case 751EP) | 4 | 3.9x4.725 | 2.54mm | no | optocoupler | `OnSemi_751EP_SOIC-4_3.9x4.725mm_P2.54mm` | no |
| SOIC | 10 | 3.9x4.9 | 1mm | no | — | `SOIC-10_3.9x4.9mm_P1mm` | no |
| SOIC | 14-16 | 3.9x9.9 | 1.27mm | no | 16-pin body, pins 2 & 13 removed for clearance | `SOIC-14-16_3.9x9.9mm_P1.27mm` | no |
| SOIC | 14W | 7.5x9 | 1.27mm | no | wide `W`, JEDEC MS-013AF | `SOIC-14W_7.5x9mm_P1.27mm` | no |
| SOIC | 14 | 3.9x8.7 | 1.27mm | no | narrow, JEDEC MS-012AB | `SOIC-14_3.9x8.7mm_P1.27mm` | no |
| SOIC | 16W | 7.5x10.3 | 1.27mm | no | wide `W`, only 12 pads fitted | `SOIC-16W-12_7.5x10.3mm_P1.27mm` | no |
| SOIC | 16W | 5.3x10.2 | 1.27mm | no | `W` at only 5.3 mm — see pitfalls | `SOIC-16W_5.3x10.2mm_P1.27mm` | no |
| SOIC | 16W | 7.5x10.3 | 1.27mm | no | wide `W`, JEDEC MS-013AA | `SOIC-16W_7.5x10.3mm_P1.27mm` | no |
| SOIC | 16W | 7.5x12.8 | 1.27mm | no | wide `W` | `SOIC-16W_7.5x12.8mm_P1.27mm` | no |
| SOIC | 16 | 3.9x9.9 | 1.27mm | no | narrow | `SOIC-16_3.9x9.9mm_P1.27mm` | no |
| SOIC | 16 | 4.55x10.3 | 1.27mm | no | Toshiba TLP291-4 | `SOIC-16_4.55x10.3mm_P1.27mm` | no |
| SOIC | 18W | 7.5x11.6 | 1.27mm | no | wide `W`, JEDEC MS-013AB | `SOIC-18W_7.5x11.6mm_P1.27mm` | no |
| SOIC | 20W | 7.5x12.8 | 1.27mm | no | wide `W`, JEDEC MS-013AC | `SOIC-20W_7.5x12.8mm_P1.27mm` | no |
| SOIC | 20W | 7.5x15.4 | 1.27mm | no | wide `W` | `SOIC-20W_7.5x15.4mm_P1.27mm` | no |
| SOIC | 24W | 7.5x15.4 | 1.27mm | no | wide `W`, JEDEC MS-013AD | `SOIC-24W_7.5x15.4mm_P1.27mm` | no |
| SOIC | 28W | 7.5x17.9 | 1.27mm | no | wide `W`, JEDEC MS-013AE | `SOIC-28W_7.5x17.9mm_P1.27mm` | no |
| SOIC | 28W | 7.5x18.7 | 1.27mm | no | wide `W` | `SOIC-28W_7.5x18.7mm_P1.27mm` | no |
| SOIC | 32 | 7.518x20.777 | 1.27mm | no | JEDEC MO-119-B, 300 mil | `SOIC-32_7.518x20.777mm_P1.27mm` | no |
| SOIC | 4 | 4.55x2.6 | 1.27mm | no | — | `SOIC-4_4.55x2.6mm_P1.27mm` | no |
| SOIC | 4 | 4.55x3.7 | 2.54mm | no | — | `SOIC-4_4.55x3.7mm_P2.54mm` | no |
| SOIC | 5-6 | 4.4x3.6 | 1.27mm | no | 6-pin body, 5 pads, JEDEC MO-155 AA | `SOIC-5-6_4.4x3.6mm_P1.27mm` | no |
| SOIC | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.29x3mm | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.29x3mm` | yes |
| SOIC | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.41x3.3mm | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.3mm` | yes |
| SOIC | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.41x3.81mm | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.81mm` | yes |
| SOIC | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.514x3.2mm | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.514x3.2mm` | yes |
| SOIC | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.62x3.51mm | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.62x3.51mm` | yes |
| SOIC | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.71x3.7mm | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.71x3.7mm` | yes |
| SOIC | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.95x4.9mm; Mask 2.34x2.34mm | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.34x2.34mm` | yes |
| SOIC | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.95x4.9mm; Mask 2.71x3.4mm | `SOIC-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.71x3.4mm` | yes |
| SOIC | 8 | 3.9x4.9 | 1.27mm | no | **pin 7 depopulated** (`-N7`) | `SOIC-8-N7_3.9x4.9mm_P1.27mm` | no |
| SOIC | 8 | 3.81x9.347 | 2.54mm | no | Littelfuse CPC2014N | `SOIC-8_3.81x9.347mm_P2.54mm` | no |
| SOIC | 8 | 3.9x4.9 | 1.27mm | no | **the default narrow SOIC-8**, JEDEC MS-012AA | `SOIC-8_3.9x4.9mm_P1.27mm` | no |
| SOIC | 8 | 5.3x5.3 | 1.27mm | no | 208 mil, JEITA/EIAJ 08-001-BBA | `SOIC-8_5.3x5.3mm_P1.27mm` | no |
| SOIC | 8 | 5.3x6.2 | 1.27mm | no | 208 mil, TI msop001a | `SOIC-8_5.3x6.2mm_P1.27mm` | no |
| SOIC | 8 | 7.5x5.85 | 1.27mm | no | 7.5 mm body but **no `W`** — see pitfalls | `SOIC-8_7.5x5.85mm_P1.27mm` | no |
| Toshiba SOIC | 4-6 | 4.4x3.6 | 1.27mm | no | MFSOP6 body, 4 pads | `Toshiba_SOIC-4-6_4.4x3.6mm_P1.27mm` | no |
| Toshiba SOIC | 5-6 | 4.4x3.6 | 1.27mm | no | MFSOP6 body, 5 pads | `Toshiba_SOIC-5-6_4.4x3.6mm_P1.27mm` | no |

### SO / SOP / PSOP / SOJ / VSO / SSO / Infineon PG-DSO — 82 files

| Family | Pins | Body WxL (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| Diodes PSOP | 8 | not in name | not in name | **yes** | exposed die pad | `Diodes_PSOP-8` | no |
| Diodes SO | 8 | not in name | not in name | **yes** | `8EP` = exposed die pad | `Diodes_SO-8EP` | no |
| Infineon PG-DSO | 12 | not in name | not in name | **yes** | outline `-11` | `Infineon_PG-DSO-12-11` | yes |
| Infineon PG-DSO | 12 | not in name | not in name | **yes** | outline `-9`, EP 4.5x8.1mm | `Infineon_PG-DSO-12-9` | yes |
| Infineon PG-DSO | 20 | not in name | not in name | **yes** | outline `-30`, EP 4.5x7mm | `Infineon_PG-DSO-20-30` | yes |
| Infineon PG-DSO | 20 | not in name | not in name | no | outline `-32` | `Infineon_PG-DSO-20-32` | no |
| Infineon PG-DSO | 20 | not in name | not in name | **yes** | outline `-85` | `Infineon_PG-DSO-20-85` | yes |
| Infineon PG-DSO | 20 | not in name | not in name | no | outline `-87` | `Infineon_PG-DSO-20-87` | no |
| Infineon PG-DSO | 20 | 7.5x12.8 | **absent** | no | outline `-U03` | `Infineon_PG-DSO-20-U03_7.5x12.8mm` | no |
| Infineon PG-DSO | 8 | 4x5 | **absent** | no | outline `-24` | `Infineon_PG-DSO-8-24_4x5mm` | no |
| Infineon PG-DSO | 8 | 3.9x4.9 | **absent** | **yes** | EP 2.65x3mm, no `-1EP` marker | `Infineon_PG-DSO-8-27_3.9x4.9mm_EP2.65x3mm` | yes |
| Infineon PG-DSO | 8 | not in name | not in name | no | outline `-43` | `Infineon_PG-DSO-8-43` | no |
| Infineon PG-DSO | 8 | 7.5x6.3 | **absent** | no | outline `-59` | `Infineon_PG-DSO-8-59_7.5x6.3mm` | no |
| Infineon PG-TSDSO | 14 | not in name | not in name | no | outline `-22` | `Infineon_PG-TSDSO-14-22` | no |
| onsemi SO | 8FL | not in name | not in name | no | DFN5 5x6mm, case 488AA | `ONSemi_SO-8FL_488AA` | no |
| PSOP | 44 | 16.9x27.17 | 1.27mm | no | — | `PSOP-44_16.9x27.17mm_P1.27mm` | no |
| Power Integrations SO | 8 | not in name | not in name | no | 3.9 mm narrow SOIC variant | `PowerIntegrations_SO-8` | no |
| Power Integrations SO | 8B | not in name | not in name | no | body code `B` | `PowerIntegrations_SO-8B` | no |
| Power Integrations SO | 8C | not in name | not in name | no | body code `C` | `PowerIntegrations_SO-8C` | no |
| Power Integrations eSOP | 12B | not in name | not in name | **yes** | flat pack with heatsink tab | `PowerIntegrations_eSOP-12B` | no |
| Renesas SOP | 32 | 11.4x20.75 | 1.27mm | no | — | `Renesas_SOP-32_11.4x20.75mm_P1.27mm` | no |
| SO | 14 | 3.9x8.65 | 1.27mm | no | — | `SO-14_3.9x8.65mm_P1.27mm` | no |
| SO | 14 | 5.3x10.2 | 1.27mm | no | — | `SO-14_5.3x10.2mm_P1.27mm` | no |
| SO | 16 | 3.9x9.9 | 1.27mm | no | — | `SO-16_3.9x9.9mm_P1.27mm` | no |
| SO | 16 | 5.3x10.2 | 1.27mm | no | near-duplicate of `SOIC-16W_5.3x10.2mm_P1.27mm` | `SO-16_5.3x10.2mm_P1.27mm` | no |
| SO | 20 | 7.52x12.825 | 1.27mm | **yes** | EP 6.045x12.09mm; Mask 3.56x4.47mm | `SO-20-1EP_7.52x12.825mm_P1.27mm_EP6.045x12.09mm_Mask3.56x4.47mm` | yes |
| SO | 20 | 12.8x7.5 | 1.27mm | no | **reversed LxW** — see pitfalls | `SO-20_12.8x7.5mm_P1.27mm` | no |
| SO | 20 | 5.3x12.6 | 1.27mm | no | — | `SO-20_5.3x12.6mm_P1.27mm` | no |
| SO | 24 | 5.3x15 | 1.27mm | no | — | `SO-24_5.3x15mm_P1.27mm` | no |
| SO | 4 | 4.4x2.3 | 1.27mm | no | fab drawn 4.4x2.4 | `SO-4_4.4x2.3mm_P1.27mm` | no |
| SO | 4 | 4.4x3.6 | 2.54mm | no | — | `SO-4_4.4x3.6mm_P2.54mm` | no |
| SO | 4 | 4.4x3.9 | 2.54mm | no | — | `SO-4_4.4x3.9mm_P2.54mm` | no |
| SO | 4 | 4.4x4.3 | 2.54mm | no | — | `SO-4_4.4x4.3mm_P2.54mm` | no |
| SO | 4 | 7.6x3.6 | 2.54mm | no | — | `SO-4_7.6x3.6mm_P2.54mm` | no |
| SO | 5-6 | 4.55x3.7 | 1.27mm | no | 6-pin body, 5 pads | `SO-5-6_4.55x3.7mm_P1.27mm` | no |
| SO | 6L | 10x3.84 | 1.27mm | no | `10` is the **lead span**, fab body is 7.5 mm | `SO-6L_10x3.84mm_P1.27mm` | no |
| SO | 6 | 4.4x3.6 | 1.27mm | no | — | `SO-6_4.4x3.6mm_P1.27mm` | no |
| SO | 8 | 3.9x4.9 | 1.27mm | no | alias-shaped twin of `SOIC-8_3.9x4.9mm_P1.27mm` | `SO-8_3.9x4.9mm_P1.27mm` | no |
| SOJ | 24 | 7.62x15.875 | 1.27mm | no | J-lead, not gull-wing | `SOJ-24_7.62x15.875mm_P1.27mm` | no |
| SOJ | 28 | 10.16x18.415 | 1.27mm | no | J-lead | `SOJ-28_10.16x18.415mm_P1.27mm` | no |
| SOJ | 28 | 7.62x18.415 | 1.27mm | no | J-lead | `SOJ-28_7.62x18.415mm_P1.27mm` | no |
| SOJ | 32 | 10.16x20.955 | 1.27mm | no | J-lead | `SOJ-32_10.16x20.955mm_P1.27mm` | no |
| SOJ | 32 | 7.62x20.955 | 1.27mm | no | J-lead | `SOJ-32_7.62x20.955mm_P1.27mm` | no |
| SOJ | 36 | 10.16x23.495 | 1.27mm | no | J-lead | `SOJ-36_10.16x23.495mm_P1.27mm` | no |
| SOJ | 44 | 10.16x28.575 | 1.27mm | no | J-lead | `SOJ-44_10.16x28.575mm_P1.27mm` | no |
| SOP | 16 | 4.4x10.4 | 1.27mm | no | — | `SOP-16_4.4x10.4mm_P1.27mm` | no |
| SOP | 16 | 4.55x10.3 | 1.27mm | no | — | `SOP-16_4.55x10.3mm_P1.27mm` | no |
| SOP | 18 | 7.495x11.515 | 1.27mm | no | — | `SOP-18_7.495x11.515mm_P1.27mm` | no |
| SOP | 18 | 7x12.5 | 1.27mm | no | — | `SOP-18_7x12.5mm_P1.27mm` | no |
| SOP | 20 | 7.5x12.8 | 1.27mm | no | — | `SOP-20_7.5x12.8mm_P1.27mm` | no |
| SOP | 24 | 7.5x15.4 | 1.27mm | no | — | `SOP-24_7.5x15.4mm_P1.27mm` | no |
| SOP | 28 | 8.4x18.16 | 1.27mm | no | — | `SOP-28_8.4x18.16mm_P1.27mm` | no |
| SOP | 32 | 11.305x20.495 | 1.27mm | no | — | `SOP-32_11.305x20.495mm_P1.27mm` | no |
| SOP | 44 | 12.6x28.5 | 1.27mm | no | — | `SOP-44_12.6x28.5mm_P1.27mm` | no |
| SOP | 44 | 13.3x28.2 | 1.27mm | no | — | `SOP-44_13.3x28.2mm_P1.27mm` | no |
| SOP | 4 | 3.8x4.1 | 2.54mm | no | — | `SOP-4_3.8x4.1mm_P2.54mm` | no |
| SOP | 4 | 4.4x2.6 | 1.27mm | no | — | `SOP-4_4.4x2.6mm_P1.27mm` | no |
| SOP | 4 | 7.5x4.1 | 2.54mm | no | — | `SOP-4_7.5x4.1mm_P2.54mm` | no |
| SOP | 8 | 4.57x4.57 | 1.27mm | **yes** | EP 4.57x4.45mm | `SOP-8-1EP_4.57x4.57mm_P1.27mm_EP4.57x4.45mm` | yes |
| SOP | 8 | 3.76x4.96 | 1.27mm | no | — | `SOP-8_3.76x4.96mm_P1.27mm` | no |
| SOP | 8 | 6.605x9.655 | 2.54mm | no | — | `SOP-8_6.605x9.655mm_P2.54mm` | no |
| SOP | 8 | 6.62x9.15 | 2.54mm | no | — | `SOP-8_6.62x9.15mm_P2.54mm` | no |
| SSO | 4 | 6.7x5.1 | 2.54mm | no | Clearance 8mm | `SSO-4_6.7x5.1mm_P2.54mm_Clearance8mm` | no |
| SSO | 6 | 6.8x4.6 | 1.27mm | no | Clearance 7mm | `SSO-6_6.8x4.6mm_P1.27mm_Clearance7mm` | no |
| SSO | 6 | 6.8x4.6 | 1.27mm | no | Clearance 8mm | `SSO-6_6.8x4.6mm_P1.27mm_Clearance8mm` | no |
| SSO | 7-8 | 6.4x9.78 | 2.54mm | no | 8-pin body, 7 pads | `SSO-7-8_6.4x9.78mm_P2.54mm` | no |
| SSO | 8-7 | 6.4x9.7 | 2.54mm | no | **same idea, digits swapped** — see pitfalls | `SSO-8-7_6.4x9.7mm_P2.54mm` | no |
| SSO | 8 | 13.6x6.3 | 1.27mm | no | Clearance 14.2mm | `SSO-8_13.6x6.3mm_P1.27mm_Clearance14.2mm` | no |
| SSO | 8 | 6.7x9.8 | 2.54mm | no | Clearance 8mm | `SSO-8_6.7x9.8mm_P2.54mm_Clearance8mm` | no |
| SSO | 8 | 6.8x5.9 | 1.27mm | no | Clearance 7mm | `SSO-8_6.8x5.9mm_P1.27mm_Clearance7mm` | no |
| SSO | 8 | 6.8x5.9 | 1.27mm | no | Clearance 8mm | `SSO-8_6.8x5.9mm_P1.27mm_Clearance8mm` | no |
| SSO | 8 | 9.6x6.3 | 1.27mm | no | Clearance 10.5mm | `SSO-8_9.6x6.3mm_P1.27mm_Clearance10.5mm` | no |
| STC SOP | 16 | 3.9x9.9 | 1.27mm | no | — | `STC_SOP-16_3.9x9.9mm_P1.27mm` | no |
| VSO | 40 | 7.6x15.4 | 0.762mm | no | — | `VSO-40_7.6x15.4mm_P0.762mm` | no |
| VSO | 56 | 11.1x21.5 | 0.75mm | no | — | `VSO-56_11.1x21.5mm_P0.75mm` | no |

### SSOP + PowerSSO — 33 files

| Family | Pins | Body WxL (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| SSOP | 10 | 3.9x4.9 | 1mm | **yes** | EP 2.1x3.3mm | `SSOP-10-1EP_3.9x4.9mm_P1mm_EP2.1x3.3mm` | yes |
| SSOP | 10 | 3.9x4.9 | **1.00mm** | no | trailing-zero anomaly — see pitfalls | `SSOP-10_3.9x4.9mm_P1.00mm` | no |
| SSOP | 14 | 5.3x6.2 | 0.65mm | no | — | `SSOP-14_5.3x6.2mm_P0.65mm` | no |
| SSOP | 16 | 3.9x4.9 | 0.635mm | no | same geometry as `QSOP-16_3.9x4.9mm_P0.635mm` | `SSOP-16_3.9x4.9mm_P0.635mm` | no |
| SSOP | 16 | 4.4x5.2 | 0.65mm | no | — | `SSOP-16_4.4x5.2mm_P0.65mm` | no |
| SSOP | 16 | 5.3x6.2 | 0.65mm | no | — | `SSOP-16_5.3x6.2mm_P0.65mm` | no |
| SSOP | 18 | 4.4x6.5 | 0.65mm | no | — | `SSOP-18_4.4x6.5mm_P0.65mm` | no |
| SSOP | 20 | 3.9x8.7 | 0.635mm | no | — | `SSOP-20_3.9x8.7mm_P0.635mm` | no |
| SSOP | 20 | 4.4x6.5 | 0.65mm | no | — | `SSOP-20_4.4x6.5mm_P0.65mm` | no |
| SSOP | 20 | 5.3x7.2 | 0.65mm | no | — | `SSOP-20_5.3x7.2mm_P0.65mm` | no |
| SSOP | 24 | 3.9x8.7 | 0.635mm | no | — | `SSOP-24_3.9x8.7mm_P0.635mm` | no |
| SSOP | 24 | 5.3x8.2 | 0.65mm | no | — | `SSOP-24_5.3x8.2mm_P0.65mm` | no |
| SSOP | 28 | 3.9x9.9 | 0.635mm | no | — | `SSOP-28_3.9x9.9mm_P0.635mm` | no |
| SSOP | 28 | 5.3x10.2 | 0.65mm | no | — | `SSOP-28_5.3x10.2mm_P0.65mm` | no |
| SSOP | 40 | 8.8x17.5 | 0.8mm | no | — | `SSOP-40_8.8x17.5mm_P0.8mm` | no |
| SSOP | 44 | 5.3x12.8 | 0.5mm | no | — | `SSOP-44_5.3x12.8mm_P0.5mm` | no |
| SSOP | 48 | 5.3x12.8 | 0.5mm | no | — | `SSOP-48_5.3x12.8mm_P0.5mm` | no |
| SSOP | 48 | 7.5x15.9 | 0.635mm | no | — | `SSOP-48_7.5x15.9mm_P0.635mm` | no |
| SSOP | 4 | 4.4x2.6 | 1.27mm | no | — | `SSOP-4_4.4x2.6mm_P1.27mm` | no |
| SSOP | 56 | 7.5x18.5 | 0.635mm | no | — | `SSOP-56_7.5x18.5mm_P0.635mm` | no |
| SSOP | 8 | 2.95x2.8 | 0.65mm | no | — | `SSOP-8_2.95x2.8mm_P0.65mm` | no |
| SSOP | 8 | 3.95x5.21x**3.27** | 1.27mm | no | **three** numbers = WxLxH | `SSOP-8_3.95x5.21x3.27mm_P1.27mm` | no |
| SSOP | 8 | 3.9x5.05 | 1.27mm | no | — | `SSOP-8_3.9x5.05mm_P1.27mm` | no |
| SSOP | 8 | 5.3x3 | 0.65mm | no | — | `SSOP-8_5.3x3mm_P0.65mm` | no |
| PowerSSO | 16 | 3.9x4.9 | 0.5mm | **yes** | EP 2.5x3.61mm | `PowerSSO-16-1EP_3.9x4.9mm_P0.5mm_EP2.5x3.61mm` | yes |
| ST PowerSSO | 24 | not in name | not in name | **yes** | SlugDown | `ST_PowerSSO-24_SlugDown` | yes |
| ST PowerSSO | 24 | not in name | not in name | **yes** | SlugUp | `ST_PowerSSO-24_SlugUp` | no |
| ST PowerSSO | 36 | not in name | not in name | **yes** | SlugDown | `ST_PowerSSO-36_SlugDown` | yes |
| ST PowerSSO | 36 | not in name | not in name | **yes** | SlugUp | `ST_PowerSSO-36_SlugUp` | no |

### QSOP — 4 files (the whole sub-family)

| Family | Pins | Body WxL (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| QSOP | 16 | 3.9x4.9 | 0.635mm | no | — | `QSOP-16_3.9x4.9mm_P0.635mm` | no |
| QSOP | 20 | 3.9x8.7 | 0.635mm | no | — | `QSOP-20_3.9x8.7mm_P0.635mm` | no |
| QSOP | 24 | 3.9x8.7 | 0.635mm | no | — | `QSOP-24_3.9x8.7mm_P0.635mm` | no |
| QSOP | 28 | 3.9x9.9 | 0.635mm | no | — | `QSOP-28_3.9x9.9mm_P0.635mm` | no |

### MSOP / VSSOP / HVSSOP — 39 files

| Family | Pins | Body WxL (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| Analog Devices MSOP | 12-16 | 3x4.039 | 0.5mm | **yes** | EP 1.651x2.845mm; 16-pin body, 12 pads | `Analog_MSOP-12-16-1EP_3x4.039mm_P0.5mm_EP1.651x2.845mm` | yes |
| Analog Devices MSOP | 12-16 | 3x4.039 | 0.5mm | no | 16-pin body, 12 pads | `Analog_MSOP-12-16_3x4.039mm_P0.5mm` | no |
| MSOP | 10 | 3x3 | 0.5mm | **yes** | EP 1.68x1.88mm | `MSOP-10-1EP_3x3mm_P0.5mm_EP1.68x1.88mm` | yes |
| MSOP | 10 | 3x3 | 0.5mm | **yes** | EP 1.73x1.98mm | `MSOP-10-1EP_3x3mm_P0.5mm_EP1.73x1.98mm` | yes |
| MSOP | 10 | 3x3 | 0.5mm | **yes** | EP 2.2x3.1mm; Mask 1.83x1.89mm | `MSOP-10-1EP_3x3mm_P0.5mm_EP2.2x3.1mm_Mask1.83x1.89mm` | yes |
| MSOP | 10 | 3x3 | 0.5mm | no | **the default MSOP-10** | `MSOP-10_3x3mm_P0.5mm` | no |
| MSOP | 12 | 3x4.039 | 0.65mm | **yes** | EP 1.651x2.845mm | `MSOP-12-1EP_3x4.039mm_P0.65mm_EP1.651x2.845mm` | yes |
| MSOP | 12 | 3x4.039 | 0.65mm | no | — | `MSOP-12_3x4.039mm_P0.65mm` | no |
| MSOP | 16 | 3x4.039 | 0.5mm | **yes** | EP 1.651x2.845mm | `MSOP-16-1EP_3x4.039mm_P0.5mm_EP1.651x2.845mm` | yes |
| MSOP | 16 | 3x4.039 | 0.5mm | no | — | `MSOP-16_3x4.039mm_P0.5mm` | no |
| MSOP | 8 | 3x3 | 0.65mm | **yes** | EP 1.5x1.8mm | `MSOP-8-1EP_3x3mm_P0.65mm_EP1.5x1.8mm` | yes |
| MSOP | 8 | 3x3 | 0.65mm | **yes** | EP 1.68x1.88mm | `MSOP-8-1EP_3x3mm_P0.65mm_EP1.68x1.88mm` | yes |
| MSOP | 8 | 3x3 | 0.65mm | **yes** | EP 1.73x1.85mm | `MSOP-8-1EP_3x3mm_P0.65mm_EP1.73x1.85mm` | yes |
| MSOP | 8 | 3x3 | 0.65mm | **yes** | EP 1.95x2.15mm | `MSOP-8-1EP_3x3mm_P0.65mm_EP1.95x2.15mm` | yes |
| MSOP | 8 | 3x3 | 0.65mm | **yes** | EP 2.5x3mm; Mask 1.73x2.36mm | `MSOP-8-1EP_3x3mm_P0.65mm_EP2.5x3mm_Mask1.73x2.36mm` | yes |
| MSOP | 8 | 3x3 | 0.65mm | no | **the default MSOP-8**, JEDEC MO-187 AA | `MSOP-8_3x3mm_P0.65mm` | no |
| HVSSOP | 10 | 3x3 | 0.5mm | **yes** | EP 1.83x1.89mm | `HVSSOP-10-1EP_3x3mm_P0.5mm_EP1.83x1.89mm` | yes |
| HVSSOP | 8 | 3x3 | 0.65mm | **yes** | EP 1.57x1.89mm | `HVSSOP-8-1EP_3x3mm_P0.65mm_EP1.57x1.89mm` | yes |
| TI DGN0008B VSSOP | 8 | 3x3 | 0.65mm | **yes** | EP 2x3mm; Mask 1.88x1.98mm | `Texas_DGN0008B_VSSOP-8-1EP_3x3mm_P0.65mm_EP2x3mm_Mask1.88x1.98mm` | yes |
| TI DGN0008D VSSOP | 8 | 3x3 | 0.65mm | **yes** | EP 2x2.94mm; Mask 1.57x1.89mm | `Texas_DGN0008D_VSSOP-8-1EP_3x3mm_P0.65mm_EP2x2.94mm_Mask1.57x1.89mm` | yes |
| TI DGN0008G VSSOP | 8 | 3x3 | 0.65mm | **yes** | EP 2x2.94mm; Mask 1.846x2.15mm | `Texas_DGN0008G_VSSOP-8-1EP_3x3mm_P0.65mm_EP2x2.94mm_Mask1.846x2.15mm` | yes |
| VSSOP | 8 | 2.3x2 | 0.5mm | no | — | `VSSOP-8_2.3x2mm_P0.5mm` | no |
| VSSOP | 8 | 3x3 | 0.65mm | no | geometric twin of `MSOP-8_3x3mm_P0.65mm` | `VSSOP-8_3x3mm_P0.65mm` | no |

### TSSOP (no heat slug) — 77 files

| Family | Pins | Body WxL (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| TSSOP | 100 | 6.1x20.8 | 0.4mm | no | — | `TSSOP-100_6.1x20.8mm_P0.4mm` | no |
| TSSOP | 10 | 3x3 | 0.5mm | no | — | `TSSOP-10_3x3mm_P0.5mm` | no |
| TSSOP | 14 | 4.4x5 | 0.65mm | **yes** | `-1EP` with **no EP size in the name** | `TSSOP-14-1EP_4.4x5mm_P0.65mm` | no |
| TSSOP | 14 | 4.4x3.6 | 0.4mm | no | — | `TSSOP-14_4.4x3.6mm_P0.4mm` | no |
| TSSOP | 14 | 4.4x5 | 0.65mm | no | **the default TSSOP-14**, JEDEC MO-153 | `TSSOP-14_4.4x5mm_P0.65mm` | no |
| TSSOP | 16 | 4.4x5 | 0.65mm | **yes** | `-1EP`, no EP size in the name | `TSSOP-16-1EP_4.4x5mm_P0.65mm` | no |
| TSSOP | 16 | 4.4x5 | 0.65mm | **yes** | EP 3x3mm | `TSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm` | yes |
| TSSOP | 16 | 4.4x3.6 | 0.4mm | no | — | `TSSOP-16_4.4x3.6mm_P0.4mm` | no |
| TSSOP | 16 | 4.4x5 | 0.65mm | no | **the default TSSOP-16** | `TSSOP-16_4.4x5mm_P0.65mm` | no |
| TSSOP | 20 | 4.4x6.5 | 0.65mm | **yes** | EP 2.15x3.35mm | `TSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP2.15x3.35mm` | no |
| TSSOP | 20 | 4.4x5 | 0.4mm | no | — | `TSSOP-20_4.4x5mm_P0.4mm` | no |
| TSSOP | 20 | 4.4x5 | 0.5mm | no | — | `TSSOP-20_4.4x5mm_P0.5mm` | no |
| TSSOP | 20 | 4.4x6.5 | 0.65mm | no | **the default TSSOP-20**, JEDEC MO-153 AC | `TSSOP-20_4.4x6.5mm_P0.65mm` | no |
| TSSOP | 24 | 4.4x5 | 0.4mm | no | — | `TSSOP-24_4.4x5mm_P0.4mm` | no |
| TSSOP | 24 | 4.4x6.5 | 0.5mm | no | — | `TSSOP-24_4.4x6.5mm_P0.5mm` | no |
| TSSOP | 24 | 4.4x7.8 | 0.65mm | no | **the default TSSOP-24** | `TSSOP-24_4.4x7.8mm_P0.65mm` | no |
| TSSOP | 24 | 6.1x7.8 | 0.65mm | no | 6.1 mm wide body | `TSSOP-24_6.1x7.8mm_P0.65mm` | no |
| TSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 2.74x4.75mm | `TSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP2.74x4.75mm` | yes |
| TSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 2.85x6.7mm | `TSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP2.85x6.7mm` | no |
| TSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 3.05x7.56mm | `TSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP3.05x7.56mm` | yes |
| TSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 3.4x9.7mm; Mask 3.1x4.05mm | `TSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP3.4x9.7mm_Mask3.1x4.05mm` | yes |
| TSSOP | 28 | 4.4x7.8 | 0.5mm | no | — | `TSSOP-28_4.4x7.8mm_P0.5mm` | no |
| TSSOP | 28 | 4.4x9.7 | 0.65mm | no | **the default TSSOP-28** | `TSSOP-28_4.4x9.7mm_P0.65mm` | no |
| TSSOP | 28 | 6.1x7.8 | 0.5mm | no | — | `TSSOP-28_6.1x7.8mm_P0.5mm` | no |
| TSSOP | 28 | 6.1x9.7 | 0.65mm | no | — | `TSSOP-28_6.1x9.7mm_P0.65mm` | no |
| TSSOP | 28 | 8x9.7 | 0.65mm | no | 8 mm wide body | `TSSOP-28_8x9.7mm_P0.65mm` | no |
| TSSOP | 30 | 4.4x7.8 | 0.5mm | no | — | `TSSOP-30_4.4x7.8mm_P0.5mm` | no |
| TSSOP | 30 | 6.1x9.7 | 0.65mm | no | — | `TSSOP-30_6.1x9.7mm_P0.65mm` | no |
| TSSOP | 32 | 4.4x6.5 | 0.4mm | no | — | `TSSOP-32_4.4x6.5mm_P0.4mm` | no |
| TSSOP | 32 | 6.1x11 | 0.65mm | no | — | `TSSOP-32_6.1x11mm_P0.65mm` | no |
| TSSOP | 32 | 8x11 | 0.65mm | no | — | `TSSOP-32_8x11mm_P0.65mm` | no |
| TSSOP | 36 | 4.4x7.8 | 0.4mm | no | — | `TSSOP-36_4.4x7.8mm_P0.4mm` | no |
| TSSOP | 36 | 4.4x9.7 | 0.5mm | no | — | `TSSOP-36_4.4x9.7mm_P0.5mm` | no |
| TSSOP | 36 | 6.1x12.5 | 0.65mm | no | — | `TSSOP-36_6.1x12.5mm_P0.65mm` | no |
| TSSOP | 36 | 6.1x7.8 | 0.4mm | no | — | `TSSOP-36_6.1x7.8mm_P0.4mm` | no |
| TSSOP | 36 | 6.1x9.7 | 0.5mm | no | — | `TSSOP-36_6.1x9.7mm_P0.5mm` | no |
| TSSOP | 36 | 8x12.5 | 0.65mm | no | — | `TSSOP-36_8x12.5mm_P0.65mm` | no |
| TSSOP | 36 | 8x9.7 | 0.5mm | no | — | `TSSOP-36_8x9.7mm_P0.5mm` | no |
| TSSOP | 38 | 4.4x9.7 | 0.5mm | no | — | `TSSOP-38_4.4x9.7mm_P0.5mm` | no |
| TSSOP | 38 | 6.1x12.5 | 0.65mm | no | — | `TSSOP-38_6.1x12.5mm_P0.65mm` | no |
| TSSOP | 40 | 6.1x11 | 0.5mm | no | — | `TSSOP-40_6.1x11mm_P0.5mm` | no |
| TSSOP | 40 | 6.1x14 | 0.65mm | no | — | `TSSOP-40_6.1x14mm_P0.65mm` | no |
| TSSOP | 40 | 8x11 | 0.5mm | no | — | `TSSOP-40_8x11mm_P0.5mm` | no |
| TSSOP | 40 | 8x14 | 0.65mm | no | — | `TSSOP-40_8x14mm_P0.65mm` | no |
| TSSOP | 44 | 4.4x11.2 | 0.5mm | no | 0.2 mm from the next row — check twice | `TSSOP-44_4.4x11.2mm_P0.5mm` | no |
| TSSOP | 44 | 4.4x11 | 0.5mm | no | — | `TSSOP-44_4.4x11mm_P0.5mm` | no |
| TSSOP | 44 | 6.1x11 | 0.5mm | no | — | `TSSOP-44_6.1x11mm_P0.5mm` | no |
| TSSOP | 48 | 4.4x9.7 | 0.4mm | no | — | `TSSOP-48_4.4x9.7mm_P0.4mm` | no |
| TSSOP | 48 | 6.1x12.5 | 0.5mm | no | — | `TSSOP-48_6.1x12.5mm_P0.5mm` | no |
| TSSOP | 48 | 6.1x9.7 | 0.4mm | no | — | `TSSOP-48_6.1x9.7mm_P0.4mm` | no |
| TSSOP | 48 | 8x12.5 | 0.5mm | no | — | `TSSOP-48_8x12.5mm_P0.5mm` | no |
| TSSOP | 48 | 8x9.7 | 0.4mm | no | — | `TSSOP-48_8x9.7mm_P0.4mm` | no |
| TSSOP | 4 | 4.4x5 | 4mm | no | 2 pads per row at 4 mm pitch | `TSSOP-4_4.4x5mm_P4mm` | no |
| TSSOP | 50 | 4.4x12.5 | 0.5mm | no | — | `TSSOP-50_4.4x12.5mm_P0.5mm` | no |
| TSSOP | 52 | 6.1x11 | 0.4mm | no | — | `TSSOP-52_6.1x11mm_P0.4mm` | no |
| TSSOP | 52 | 8x11 | 0.4mm | no | — | `TSSOP-52_8x11mm_P0.4mm` | no |
| TSSOP | 56 | 4.4x11.3 | 0.4mm | no | — | `TSSOP-56_4.4x11.3mm_P0.4mm` | no |
| TSSOP | 56 | 6.1x12.5 | 0.4mm | no | — | `TSSOP-56_6.1x12.5mm_P0.4mm` | no |
| TSSOP | 56 | 6.1x14 | 0.5mm | no | — | `TSSOP-56_6.1x14mm_P0.5mm` | no |
| TSSOP | 56 | 8x12.5 | 0.4mm | no | — | `TSSOP-56_8x12.5mm_P0.4mm` | no |
| TSSOP | 56 | 8x14 | 0.5mm | no | — | `TSSOP-56_8x14mm_P0.5mm` | no |
| TSSOP | 60 | 8x12.5 | 0.4mm | no | — | `TSSOP-60_8x12.5mm_P0.4mm` | no |
| TSSOP | 64 | 6.1x14 | 0.4mm | no | — | `TSSOP-64_6.1x14mm_P0.4mm` | no |
| TSSOP | 64 | 6.1x17 | 0.5mm | no | — | `TSSOP-64_6.1x17mm_P0.5mm` | no |
| TSSOP | 64 | 8x14 | 0.4mm | no | — | `TSSOP-64_8x14mm_P0.4mm` | no |
| TSSOP | 68 | 8x14 | 0.4mm | no | — | `TSSOP-68_8x14mm_P0.4mm` | no |
| TSSOP | 80 | 6.1x17 | 0.4mm | no | — | `TSSOP-80_6.1x17mm_P0.4mm` | no |
| TSSOP | 8 | 3x3 | 0.65mm | no | **the default TSSOP-8** | `TSSOP-8_3x3mm_P0.65mm` | no |
| TSSOP | 8 | 4.4x3 | 0.65mm | no | 4.4 mm wide, 3 mm long | `TSSOP-8_4.4x3mm_P0.65mm` | no |
| TI DGS0020A TSSOP | 20 | 3x5.1 | 0.5mm | no | — | `Texas_DGS0020A_TSSOP-20_3x5.1mm_P0.5mm` | no |
| TI PW0020A TSSOP | 20 | 4.4x6.5 | 0.65mm | no | TI-coded twin of `TSSOP-20_4.4x6.5mm_P0.65mm` | `Texas_PW0020A_TSSOP-20_4.4x6.5mm_P0.65mm` | no |
| TI PWP0028V TSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 3.4x9.7mm; Mask 2.94x5.62mm | `Texas_PWP0028V_TSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP3.4x9.7mm_Mask2.94x5.62mm` | yes |

### HTSSOP / ETSSOP / HSOP / HTSOP / HSSOP (thermally enhanced) — 75 files

| Family | Pins | Body WxL (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| ETSSOP | 20 | 4.4x6.5 | 0.65mm | **yes** | EP 3x4.2mm (Microchip eTSSOP) | `ETSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3x4.2mm` | no |
| HTSSOP | 16 | 4.4x5 | 0.65mm | **yes** | EP 3.4x5mm | `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm` | no |
| HTSSOP | 16 | 4.4x5 | 0.65mm | **yes** | EP 3.4x5mm; Mask 2.46x2.31mm | `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask2.46x2.31mm` | yes |
| HTSSOP | 16 | 4.4x5 | 0.65mm | **yes** | EP 3.4x5mm; Mask 2.66x2.46mm | `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask2.66x2.46mm` | yes |
| HTSSOP | 16 | 4.4x5 | 0.65mm | **yes** | EP 3.4x5mm; Mask 2.78x3.37mm | `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask2.78x3.37mm` | yes |
| HTSSOP | 16 | 4.4x5 | 0.65mm | **yes** | EP 3x3mm | `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm` | no |
| HTSSOP | 20 | 4.4x6.5 | 0.65mm | **yes** | EP 2.74x3.86mm | `HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP2.74x3.86mm` | no |
| HTSSOP | 20 | 4.4x6.5 | 0.65mm | **yes** | EP 2.85x4mm | `HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP2.85x4mm` | no |
| HTSSOP | 20 | 4.4x6.5 | 0.65mm | **yes** | EP 3.4x6.5mm | `HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3.4x6.5mm` | yes |
| HTSSOP | 20 | 4.4x6.5 | 0.65mm | **yes** | EP 3.4x6.5mm; Mask 2.4x3.7mm | `HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3.4x6.5mm_Mask2.4x3.7mm` | no |
| HTSSOP | 20 | 4.4x6.5 | 0.65mm | **yes** | EP 3.4x6.5mm; Mask 2.75x3.43mm | `HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3.4x6.5mm_Mask2.75x3.43mm` | yes |
| HTSSOP | 20 | 4.4x6.5 | 0.65mm | **yes** | EP 3.4x6.5mm; Mask 2.96x2.96mm | `HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3.4x6.5mm_Mask2.96x2.96mm` | yes |
| HTSSOP | 24 | 4.4x7.8 | 0.65mm | **yes** | EP 3.2x5mm | `HTSSOP-24-1EP_4.4x7.8mm_P0.65mm_EP3.2x5mm` | no |
| HTSSOP | 24 | 4.4x7.8 | 0.65mm | **yes** | EP 3.4x7.8mm; Mask 2.44x3.42mm | `HTSSOP-24-1EP_4.4x7.8mm_P0.65mm_EP3.4x7.8mm_Mask2.44x3.42mm` | yes |
| HTSSOP | 24 | 4.4x7.8 | 0.65mm | **yes** | EP 3.4x7.8mm; Mask 2.4x2.98mm | `HTSSOP-24-1EP_4.4x7.8mm_P0.65mm_EP3.4x7.8mm_Mask2.4x2.98mm` | yes |
| HTSSOP | 24 | 4.4x7.8 | 0.65mm | **yes** | EP 3.4x7.8mm; Mask 2.4x4.68mm | `HTSSOP-24-1EP_4.4x7.8mm_P0.65mm_EP3.4x7.8mm_Mask2.4x4.68mm` | yes |
| HTSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 2.75x6.2mm | `HTSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP2.75x6.2mm` | yes |
| HTSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 2.85x5.4mm | `HTSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP2.85x5.4mm` | yes |
| HTSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 3.4x9.5mm | `HTSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP3.4x9.5mm` | yes |
| HTSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 3.4x9.5mm; Mask 2.4x6.17mm | `HTSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP3.4x9.5mm_Mask2.4x6.17mm` | yes |
| HTSSOP | 32 | 6.1x11 | 0.65mm | **yes** | EP 5.2x11mm; Mask 4.11x4.36mm | `HTSSOP-32-1EP_6.1x11mm_P0.65mm_EP5.2x11mm_Mask4.11x4.36mm` | yes |
| HTSSOP | 38 | 4.4x9.7 | 0.5mm | **yes** | EP 1.5x3.3mm | `HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP1.5x3.3mm` | yes |
| HTSSOP | 38 | 4.4x9.7 | 0.5mm | **yes** | EP 2.74x4.75mm | `HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm` | yes |
| HTSSOP | 38 | 4.4x9.7 | 0.5mm | **yes** | EP 3.05x6.65mm | `HTSSOP-38-1EP_4.4x9.7mm_P0.5mm_EP3.05x6.65mm` | yes |
| HTSSOP | 38 | 6.1x12.5 | 0.65mm | **yes** | EP 5.2x12.5mm; Mask 3.39x6.35mm | `HTSSOP-38-1EP_6.1x12.5mm_P0.65mm_EP5.2x12.5mm_Mask3.39x6.35mm` | yes |
| HTSSOP | 44 | 6.1x14 | 0.635mm | **yes** | EP 5.2x14mm; Mask 4.31x8.26mm | `HTSSOP-44-1EP_6.1x14mm_P0.635mm_EP5.2x14mm_Mask4.31x8.26mm` | yes |
| HTSSOP | 44 | 6.1x14 | 0.635mm | **top** | TopEP 4.14x7.01mm — no `-1EP`, no copper pad | `HTSSOP-44_6.1x14mm_P0.635mm_TopEP4.14x7.01mm` | no |
| HTSSOP | 56 | 6.1x14 | 0.5mm | **yes** | EP 3.61x6.35mm | `HTSSOP-56-1EP_6.1x14mm_P0.5mm_EP3.61x6.35mm` | no |
| Linear Tech HTSSOP | 31-38 | 4.4x9.7 | 0.5mm | **yes** | EP 2.74x4.75mm; 38-pin body, 31 pads | `Linear_HTSSOP-31-38-1EP_4.4x9.7mm_P0.5mm_EP2.74x4.75mm` | yes |
| NXP HTSSOP | 28 | 4.4x9.7 | 0.65mm | **yes** | EP 2.2x3.4mm | `NXP_HTSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP2.2x3.4mm` | yes |
| TI DAD0032A HTSSOP | 32 | 6.1x11 | 0.65mm | **top** | TopEP 3.71x3.81mm | `Texas_DAD0032A_HTSSOP-32_6.1x11mm_P0.65mm_TopEP3.71x3.81mm` | no |
| TI HTSSOP | 14 | 4.4x5 | 0.65mm | **yes** | EP 3.4x5mm; Mask 2.94x3.34mm | `Texas_HTSSOP-14-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask2.94x3.34mm` | yes |
| TI HTSSOP | 14 | 4.4x5 | 0.65mm | **yes** | EP 3.4x5mm; Mask 3.155x3.255mm | `Texas_HTSSOP-14-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask3.155x3.255mm` | yes |
| HSOP | 20 | 11.0x15.9 | 1.27mm | **yes** | SlugDown; PowerSO-20, JEDEC MO-166 | `HSOP-20-1EP_11.0x15.9mm_P1.27mm_SlugDown` | yes |
| HSOP | 20 | 11.0x15.9 | 1.27mm | **yes** | SlugUp; PowerSO-20 | `HSOP-20-1EP_11.0x15.9mm_P1.27mm_SlugUp` | no |
| HSOP | 32 | 7.5x11 | 0.65mm | **yes** | EP 4.7x4.7mm | `HSOP-32-1EP_7.5x11mm_P0.65mm_EP4.7x4.7mm` | no |
| HSOP | 36 | 11.0x15.9 | 0.65mm | **yes** | SlugDown | `HSOP-36-1EP_11.0x15.9mm_P0.65mm_SlugDown` | yes |
| HSOP | 36 | 11.0x15.9 | 0.65mm | **yes** | SlugUp | `HSOP-36-1EP_11.0x15.9mm_P0.65mm_SlugUp` | no |
| HSOP | 54 | 7.5x17.9 | 0.65mm | **yes** | EP 4.6x4.6mm | `HSOP-54-1EP_7.5x17.9mm_P0.65mm_EP4.6x4.6mm` | no |
| HSOP | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.3x2.3mm | `HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.3x2.3mm` | yes |
| HSOP | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.41x3.1mm | `HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.1mm` | yes |
| HTSOP | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.4x3.2mm | `HTSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.4x3.2mm` | yes |
| TI DKD0036A HSSOP | 36 | 11x15.9 | 0.65mm | **top** | TopEP 5.85x12.65mm | `Texas_DKD0036A_HSSOP-36_11x15.9mm_P0.65mm_TopEP5.85x12.65mm` | no |
| TI HSOP | 8 | 3.9x4.9 | 1.27mm | **yes** | `-1EP`, no EP size in the name | `Texas_HSOP-8-1EP_3.9x4.9mm_P1.27mm` | yes |
| HTSSOP | 16 | 4.4x5 | 0.65mm | **yes** | EP 3.4x5mm; Mask 3x3mm | `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask3x3mm_ThermalVias` | **only this form exists** |
| TI HTSOP | 8 | 3.9x4.9 | 1.27mm | **yes** | EP 2.95x4.9mm; Mask 2.4x3.1mm | `Texas_HTSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.4x3.1mm_ThermalVias` | **only this form exists** |

### TSOP / TSOP-I / TSOP-II — 28 files

| Family | Pins | Body (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| TSOP | 5 | 1.65x3.05 (WxL) | 0.95mm | no | SOT-23-5 class | `TSOP-5_1.65x3.05mm_P0.95mm` | no |
| TSOP | 6 | 1.65x3.05 (WxL) | 0.95mm | no | SOT-23-6 class | `TSOP-6_1.65x3.05mm_P0.95mm` | no |
| TSOP-I | 24 | 12.4x6 (long axis first) | 0.5mm | no | leads on short edges | `TSOP-I-24_12.4x6mm_P0.5mm` | no |
| TSOP-I | 24 | 14.4x6 | 0.5mm | no | — | `TSOP-I-24_14.4x6mm_P0.5mm` | no |
| TSOP-I | 24 | 16.4x6 | 0.5mm | no | — | `TSOP-I-24_16.4x6mm_P0.5mm` | no |
| TSOP-I | 24 | 18.4x6 | 0.5mm | no | — | `TSOP-I-24_18.4x6mm_P0.5mm` | no |
| TSOP-I | 28 | 11.8x8 | 0.55mm | no | only 0.55 mm pitch in the whole library | `TSOP-I-28_11.8x8mm_P0.55mm` | no |
| TSOP-I | 32 | 11.8x8 | 0.5mm | no | — | `TSOP-I-32_11.8x8mm_P0.5mm` | no |
| TSOP-I | 32 | 12.4x8 | 0.5mm | no | — | `TSOP-I-32_12.4x8mm_P0.5mm` | no |
| TSOP-I | 32 | 14.4x8 | 0.5mm | no | — | `TSOP-I-32_14.4x8mm_P0.5mm` | no |
| TSOP-I | 32 | 16.4x8 | 0.5mm | no | — | `TSOP-I-32_16.4x8mm_P0.5mm` | no |
| TSOP-I | 32 | 18.4x8 | 0.5mm | no | JEDEC MO-142-D var BD | `TSOP-I-32_18.4x8mm_P0.5mm` | no |
| TSOP-I | 32 | 18.4x8 | 0.5mm | no | `_Reverse`: rotated 90°, so name no longer matches XY | `TSOP-I-32_18.4x8mm_P0.5mm_Reverse` | no |
| TSOP-I | 40 | 12.4x10 | 0.5mm | no | — | `TSOP-I-40_12.4x10mm_P0.5mm` | no |
| TSOP-I | 40 | 14.4x10 | 0.5mm | no | — | `TSOP-I-40_14.4x10mm_P0.5mm` | no |
| TSOP-I | 40 | 16.4x10 | 0.5mm | no | — | `TSOP-I-40_16.4x10mm_P0.5mm` | no |
| TSOP-I | 40 | 18.4x10 | 0.5mm | no | — | `TSOP-I-40_18.4x10mm_P0.5mm` | no |
| TSOP-I | 48 | 12.4x12 | 0.5mm | no | — | `TSOP-I-48_12.4x12mm_P0.5mm` | no |
| TSOP-I | 48 | 14.4x12 | 0.5mm | no | — | `TSOP-I-48_14.4x12mm_P0.5mm` | no |
| TSOP-I | 48 | 16.4x12 | 0.5mm | no | — | `TSOP-I-48_16.4x12mm_P0.5mm` | no |
| TSOP-I | 48 | 18.4x12 | 0.5mm | no | — | `TSOP-I-48_18.4x12mm_P0.5mm` | no |
| TSOP-I | 56 | 14.4x14 | 0.5mm | no | — | `TSOP-I-56_14.4x14mm_P0.5mm` | no |
| TSOP-I | 56 | 16.4x14 | 0.5mm | no | — | `TSOP-I-56_16.4x14mm_P0.5mm` | no |
| TSOP-I | 56 | 18.4x14 | 0.5mm | no | — | `TSOP-I-56_18.4x14mm_P0.5mm` | no |
| TSOP-II | 32 | 21.0x10.2 — **LxW** | 1.27mm | no | fab is 10.1 wide x 20.4 long | `TSOP-II-32_21.0x10.2mm_P1.27mm` | no |
| TSOP-II | 40-44 | 10.16x18.37 — WxL | 0.8mm | no | 44-pin body, 40 pads | `TSOP-II-40-44_10.16x18.37mm_P0.8mm` | no |
| TSOP-II | 44 | 10.16x18.41 — WxL | 0.8mm | no | — | `TSOP-II-44_10.16x18.41mm_P0.8mm` | no |
| TSOP-II | 54 | 22.2x10.16 — **LxW** | 0.8mm | no | fab is 10.16 wide x 22.22 long | `TSOP-II-54_22.2x10.16mm_P0.8mm` | no |

### QFP — LQFP / TQFP / PQFP / EQFP / HTQFP — all 102 files of `Package_QFP.pretty`

| Family | Pins | Body XxY (mm) | Pitch | EP? | Extras | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|---|---|---|---|---|
| EQFP | 144 | 20x20 | 0.5mm | **yes** | EP 4x4mm | `EQFP-144-1EP_20x20mm_P0.5mm_EP4x4mm` | yes |
| EQFP | 144 | 20x20 | 0.5mm | **yes** | EP 5x5mm | `EQFP-144-1EP_20x20mm_P0.5mm_EP5x5mm` | yes |
| EQFP | 144 | 20x20 | 0.5mm | **yes** | EP 6.61x5.615mm | `EQFP-144-1EP_20x20mm_P0.5mm_EP6.61x5.615mm` | yes |
| EQFP | 144 | 20x20 | 0.5mm | **yes** | EP 7.2x6.35mm | `EQFP-144-1EP_20x20mm_P0.5mm_EP7.2x6.35mm` | yes |
| EQFP | 144 | 20x20 | 0.5mm | **yes** | EP 8.93x8.7mm | `EQFP-144-1EP_20x20mm_P0.5mm_EP8.93x8.7mm` | yes |
| Hitachi FP80B PQFP | 80 | 14x20 | 0.8mm | no | — | `Hitachi_FP80B_PQFP-80_14x20mm_P0.8mm` | no |
| LQFP | 100 | 14x14 | 0.5mm | **yes** | EP 6.9x6.9mm | `LQFP-100-1EP_14x14mm_P0.5mm_EP6.9x6.9mm` | yes |
| LQFP | 100 | 14x14 | 0.5mm | no | **the default LQFP-100** | `LQFP-100_14x14mm_P0.5mm` | no |
| LQFP | 128 | 14x14 | 0.4mm | no | — | `LQFP-128_14x14mm_P0.4mm` | no |
| LQFP | 128 | 14x20 | 0.5mm | no | rectangular | `LQFP-128_14x20mm_P0.5mm` | no |
| LQFP | 144 | 20x20 | 0.5mm | **yes** | EP 6.5x6.5mm | `LQFP-144-1EP_20x20mm_P0.5mm_EP6.5x6.5mm` | yes |
| LQFP | 144 | 20x20 | 0.5mm | no | — | `LQFP-144_20x20mm_P0.5mm` | no |
| LQFP | 160 | 24x24 | 0.5mm | no | — | `LQFP-160_24x24mm_P0.5mm` | no |
| LQFP | 176 | 24x24 | 0.5mm | **yes** | EP 6.6x6.6mm | `LQFP-176-1EP_24x24mm_P0.5mm_EP6.6x6.6mm` | yes |
| LQFP | 176 | 20x20 | 0.4mm | no | — | `LQFP-176_20x20mm_P0.4mm` | no |
| LQFP | 176 | 24x24 | 0.5mm | no | — | `LQFP-176_24x24mm_P0.5mm` | no |
| LQFP | 208 | 28x28 | 0.5mm | no | — | `LQFP-208_28x28mm_P0.5mm` | no |
| LQFP | 216 | 24x24 | 0.4mm | no | — | `LQFP-216_24x24mm_P0.4mm` | no |
| LQFP | 32 | 5x5 | 0.5mm | no | — | `LQFP-32_5x5mm_P0.5mm` | no |
| LQFP | 32 | 7x7 | 0.8mm | no | **the default LQFP-32** | `LQFP-32_7x7mm_P0.8mm` | no |
| LQFP | 36 | 7x7 | 0.65mm | no | — | `LQFP-36_7x7mm_P0.65mm` | no |
| LQFP | 44 | 10x10 | 0.8mm | no | **the default LQFP-44** | `LQFP-44_10x10mm_P0.8mm` | no |
| LQFP | 48 | 7x7 | 0.5mm | **yes** | EP 3.6x3.6mm | `LQFP-48-1EP_7x7mm_P0.5mm_EP3.6x3.6mm` | yes |
| LQFP | 48 | 7x7 | 0.5mm | no | **the default LQFP-48** | `LQFP-48_7x7mm_P0.5mm` | no |
| LQFP | 52 | 10x10 | 0.65mm | **yes** | EP 4.8x4.8mm | `LQFP-52-1EP_10x10mm_P0.65mm_EP4.8x4.8mm` | yes |
| LQFP | 52 | 10x10 | 0.65mm | no | — | `LQFP-52_10x10mm_P0.65mm` | no |
| LQFP | 52 | 14x14 | 1mm | no | — | `LQFP-52_14x14mm_P1mm` | no |
| LQFP | 64 | 10x10 | 0.5mm | **yes** | EP 5x5mm | `LQFP-64-1EP_10x10mm_P0.5mm_EP5x5mm` | yes |
| LQFP | 64 | 10x10 | 0.5mm | **yes** | EP 6.5x6.5mm | `LQFP-64-1EP_10x10mm_P0.5mm_EP6.5x6.5mm` | yes |
| LQFP | 64 | 10x10 | 0.5mm | no | **the default LQFP-64** (STM32 etc.) | `LQFP-64_10x10mm_P0.5mm` | no |
| LQFP | 64 | 14x14 | 0.8mm | no | — | `LQFP-64_14x14mm_P0.8mm` | no |
| LQFP | 64 | 7x7 | 0.4mm | no | — | `LQFP-64_7x7mm_P0.4mm` | no |
| LQFP | 80 | 10x10 | 0.4mm | no | — | `LQFP-80_10x10mm_P0.4mm` | no |
| LQFP | 80 | 12x12 | 0.5mm | no | — | `LQFP-80_12x12mm_P0.5mm` | no |
| LQFP | 80 | 14x14 | 0.65mm | no | — | `LQFP-80_14x14mm_P0.65mm` | no |
| JEDEC MO-112 AC1 PQFP | 52 | 10x10 | 0.65mm | no | — | `MO112AC1_PQFP-52_10x10mm_P0.65mm` | no |
| Microchip PQFP | 44 | 10x10 | 0.8mm | no | — | `Microchip_PQFP-44_10x10mm_P0.8mm` | no |
| PQFP | 100 | 14x20 | 0.65mm | no | rectangular | `PQFP-100_14x20mm_P0.65mm` | no |
| PQFP | 112 | 20x20 | 0.65mm | no | — | `PQFP-112_20x20mm_P0.65mm` | no |
| PQFP | 128 | 28x28 | 0.8mm | no | — | `PQFP-128_28x28mm_P0.8mm` | no |
| PQFP | 132 | 24x24 | 0.635mm | no | — | `PQFP-132_24x24mm_P0.635mm` | no |
| PQFP | 132 | 24x24 in the name | 0.635mm | no | `i386` = Intel 386EX variant; **fab drawn 28x28mm** | `PQFP-132_24x24mm_P0.635mm_i386` | no |
| PQFP | 144 | 28x28 | 0.65mm | no | — | `PQFP-144_28x28mm_P0.65mm` | no |
| PQFP | 160 | 28x28 | 0.65mm | no | — | `PQFP-160_28x28mm_P0.65mm` | no |
| PQFP | 168 | 28x28 | 0.65mm | no | — | `PQFP-168_28x28mm_P0.65mm` | no |
| PQFP | 208 | 28x28 | 0.5mm | no | — | `PQFP-208_28x28mm_P0.5mm` | no |
| PQFP | 240 | 32.1x32.1 | 0.5mm | no | — | `PQFP-240_32.1x32.1mm_P0.5mm` | no |
| PQFP | 256 | 28x28 | 0.4mm | no | — | `PQFP-256_28x28mm_P0.4mm` | no |
| PQFP | 44 | 10x10 | 0.8mm | no | — | `PQFP-44_10x10mm_P0.8mm` | no |
| PQFP | 64 | 14x14 | 0.8mm | no | — | `PQFP-64_14x14mm_P0.8mm` | no |
| PQFP | 80 | 14x14 | 0.65mm | no | — | `PQFP-80_14x14mm_P0.65mm` | no |
| PQFP | 80 | 14x20 | 0.8mm | no | — | `PQFP-80_14x20mm_P0.8mm` | no |
| TQFP | 100 | 14x14 | 0.5mm | **yes** | EP 5x5mm | `TQFP-100-1EP_14x14mm_P0.5mm_EP5x5mm` | yes |
| TQFP | 100 | 12x12 | 0.4mm | no | — | `TQFP-100_12x12mm_P0.4mm` | no |
| TQFP | 100 | 14x14 | 0.5mm | no | **the default TQFP-100** (ATmega etc.) | `TQFP-100_14x14mm_P0.5mm` | no |
| TQFP | 120 | 14x14 | 0.4mm | no | — | `TQFP-120_14x14mm_P0.4mm` | no |
| TQFP | 128 | 14x14 | 0.4mm | no | — | `TQFP-128_14x14mm_P0.4mm` | no |
| TQFP | 144 | 16x16 | 0.4mm | no | — | `TQFP-144_16x16mm_P0.4mm` | no |
| TQFP | 144 | 20x20 | 0.5mm | no | — | `TQFP-144_20x20mm_P0.5mm` | no |
| TQFP | 176 | 20x20 | 0.4mm | no | — | `TQFP-176_20x20mm_P0.4mm` | no |
| TQFP | 176 | 24x24 | 0.5mm | no | — | `TQFP-176_24x24mm_P0.5mm` | no |
| TQFP | 32 | 5x5 | 0.5mm | no | — | `TQFP-32_5x5mm_P0.5mm` | no |
| TQFP | 32 | 7x7 | 0.8mm | no | **the default TQFP-32** (ATmega328P) | `TQFP-32_7x7mm_P0.8mm` | no |
| TQFP | 44 | 10x10 | 0.8mm | **yes** | EP 4.5x4.5mm | `TQFP-44-1EP_10x10mm_P0.8mm_EP4.5x4.5mm` | yes |
| TQFP | 44 | 10x10 | 0.8mm | no | **the default TQFP-44** | `TQFP-44_10x10mm_P0.8mm` | no |
| TQFP | 48 | 7x7 | 0.5mm | **yes** | EP 3.5x3.5mm | `TQFP-48-1EP_7x7mm_P0.5mm_EP3.5x3.5mm` | yes |
| TQFP | 48 | 7x7 | 0.5mm | **yes** | EP 4.11x4.11mm | `TQFP-48-1EP_7x7mm_P0.5mm_EP4.11x4.11mm` | no |
| TQFP | 48 | 7x7 | 0.5mm | **yes** | EP 5x5mm | `TQFP-48-1EP_7x7mm_P0.5mm_EP5x5mm` | yes |
| TQFP | 48 | 7x7 | 0.5mm | no | **the default TQFP-48** | `TQFP-48_7x7mm_P0.5mm` | no |
| TQFP | 52 | 10x10 | 0.65mm | **yes** | EP 6.5x6.5mm | `TQFP-52-1EP_10x10mm_P0.65mm_EP6.5x6.5mm` | yes |
| TQFP | 64 | 10x10 | 0.5mm | **yes** | EP 5.305x5.305mm | `TQFP-64-1EP_10x10mm_P0.5mm_EP5.305x5.305mm` | yes |
| TQFP | 64 | 10x10 | 0.5mm | no | **the default TQFP-64** | `TQFP-64_10x10mm_P0.5mm` | no |
| TQFP | 64 | 14x14 | 0.8mm | no | — | `TQFP-64_14x14mm_P0.8mm` | no |
| TQFP | 64 | 7x7 | 0.4mm | no | — | `TQFP-64_7x7mm_P0.4mm` | no |
| TQFP | 80 | 14x14 | 0.65mm | **yes** | EP 9.5x9.5mm | `TQFP-80-1EP_14x14mm_P0.65mm_EP9.5x9.5mm` | yes |
| TQFP | 80 | 12x12 | 0.5mm | no | — | `TQFP-80_12x12mm_P0.5mm` | no |
| TQFP | 80 | 14x14 | 0.65mm | no | — | `TQFP-80_14x14mm_P0.65mm` | no |
| TI PHP0048E HTQFP | 48 | 7x7 | 0.5mm | **yes** | EP 6.5x6.5mm; Mask 3.62x3.62mm | `Texas_PHP0048E_HTQFP-48-1EP_7x7mm_P0.5mm_EP6.5x6.5mm_Mask3.62x3.62mm` | yes |
| TI TQFP | 64 | 10x10 | 0.5mm | **yes** | EP 8x8mm; Mask 4.44x4.44mm | `Texas_TQFP-64-1EP_10x10mm_P0.5mm_EP8x8mm_Mask4.44x4.44mm` | yes |
| TI TQFP | 64 | 10x10 | 0.5mm | **yes** | EP 8x8mm; Mask 5x5mm | `Texas_TQFP-64-1EP_10x10mm_P0.5mm_EP8x8mm_Mask5x5mm` | yes |

### Irregular vendor-only names inside `Package_SO.pretty` — 15 files

These carry no parsable size grammar; the description field inside the file is the only source of dimensions.

| What it is (from the file's own `descr`) | Verbatim footprint name | `_ThermalVias` twin? |
|---|---|---|
| onsemi Micro8, case 846A-02 | `OnSemi_Micro8` | no |
| Vishay PowerPAK SO-8L, single | `PowerPAK_SO-8L_Single` | no |
| Vishay PowerPAK SO-8, dual | `PowerPAK_SO-8_Dual` | no |
| Vishay PowerPAK SO-8, single | `PowerPAK_SO-8_Single` | no |
| ST MultiPowerSO-30, 3 EPs, 16.0x17.2mm, 1 mm pitch | `ST_MultiPowerSO-30` | no |
| TI PSOP-8 exposed die pad (DDA0008B) | `TI_SO-PowerPAD-8` | yes |
| TI DYY0016A, TSOT-23-16, 2x4.2mm, 0.5 mm pitch (filed under SO) | `Texas_DYY0016A_TSOT-23-16_2x4.2mm_P0.5mm` | no |
| TI PWP0020A = thermally enhanced TSSOP-20, body 4.4x6.5x1.1mm, pad 3.0x4.2mm | `Texas_PWP0020A` | no |
| TI R-PDSO-G8 = HSOIC-8, EP 2.95x4.9mm, Mask 2.4x3.1mm | `Texas_R-PDSO-G8_EP2.95x4.9mm_Mask2.4x3.1mm` | yes |
| TI S-PDSO-G8 plastic small outline, 3x3mm, 0.65 mm pitch | `Texas_S-PDSO-G8_3x3mm_P0.65mm` | no |
| Vishay PowerPAK 1212-8, dual | `Vishay_PowerPAK_1212-8_Dual` | no |
| Vishay PowerPAK 1212-8, single | `Vishay_PowerPAK_1212-8_Single` | no |
| Zetex SM8, 8-pin SMD | `Zetex_SM8` | no |

## How to name a new part in this family

## Answer to (3) first: how wide-body is distinguished

There are **two independent signals**, and you need both:

1. **The `W` letter glued to the pin count** — `SOIC-16W`, `SOIC-14W`, `SOIC-18W`,
   `SOIC-20W`, `SOIC-24W`, `SOIC-28W`. It appears in exactly one family: `SOIC`.
   There is no `SO-…W`, no `SOP-…W`, no `TSSOP-…W`.
2. **The first number of the body size** — 3.9 mm = narrow (150 mil, JEDEC MS-012);
   7.5 mm = wide (300 mil, JEDEC MS-013). Both facts were read out of the files'
   own `descr` strings.

So the canonical distinction between the narrow and wide SOIC-16 is:

| | narrow | wide |
|---|---|---|
| 16-pin SOIC | `SOIC-16_3.9x9.9mm_P1.27mm` | `SOIC-16W_7.5x10.3mm_P1.27mm` |
| JEDEC | MS-012 | MS-013AA |

But the `W` letter is **not reliable on its own** — the library is internally
inconsistent about it (see pitfalls). Two counterexamples, both real files:

* `SOIC-8_7.5x5.85mm_P1.27mm` — a 7.5 mm wide body with **no** `W`.
* `SOIC-16W_5.3x10.2mm_P1.27mm` — labelled `W` at only 5.3 mm, and it is a
  near-duplicate of `SO-16_5.3x10.2mm_P1.27mm` (both cite the same TI drawing
  `msop002a`).

**Practical rule: match on the body-size number, treat `W` as decoration.**
When you have a 300-mil datasheet, search for `7.5x` and the right pin count
rather than searching for `W`.

## Naming a NEW part from a datasheet

**Step 1 — decide the family token from the datasheet's own package name, not from
the dimensions.** Use the vendor's word verbatim if it is one of the stock tokens:
`SOIC`, `SO`, `SOP`, `SSOP`, `TSSOP`, `MSOP`, `VSSOP`, `QSOP`, `TSOP`, `TSOP-I`,
`TSOP-II`, `LQFP`, `TQFP`, `PQFP`. If the vendor's word is a thermally enhanced
variant, use the H/E form: `HTSSOP`, `HVSSOP`, `HSOP`, `HTSOP`, `HSSOP`, `ETSSOP`,
`EQFP`, `HTQFP`. Do **not** invent a new family token — for instance TI's "DGN"
maps onto stock `VSSOP`, and TI's "PWP" onto stock `HTSSOP`.

**Step 2 — pin count.** Total electrical leads, excluding the exposed pad. A 28-lead
TSSOP with a slug is `TSSOP-28-1EP`, never `TSSOP-29`.

**Step 3 — depopulated packages.** If the outline is an N-pin body with only M pads
fitted, write `<FAMILY>-<M>-<N>`, i.e. fitted count first, outline second:
`SOIC-14-16_3.9x9.9mm_P1.27mm`, `Analog_MSOP-12-16_3x4.039mm_P0.5mm`,
`TSOP-II-40-44_10.16x18.37mm_P0.8mm`. (One stock file,
`SSO-8-7_6.4x9.7mm_P2.54mm`, does it the other way round — do not copy that one.)

**Step 4 — exposed pad.** If a bottom-side thermal pad exists, append `-1EP` to the
pin count. If it is a **top**-side slug, do not use `-1EP`; use the `_TopEP…` token
at the end instead, as in `HTSSOP-44_6.1x14mm_P0.635mm_TopEP4.14x7.01mm`.

**Step 5 — body size, `_<W>x<L>mm`.** Take JEDEC `E1` (body width, excluding leads)
as W and `D` (body length) as L. Confirm the assignment by asking "which dimension
runs across the two lead rows?" — that one is W and goes first. Reproduce the
datasheet's nominal to the digits it prints; the library keeps 3 decimals when the
drawing does (`7.518x20.777mm`, `3x4.039mm`, `11.305x20.495mm`). Drop trailing
zeros on whole numbers: `3x3mm`, not `3.0x3.0mm`; `8x14mm`, not `8.0x14.0mm`.
For TSOP-I remember the leads are on the short edges, so the *long* dimension is W
and comes first.

**Step 6 — pitch, `_P<value>mm`.** Nominal lead pitch `e`, straight after the body
size. No trailing zeros: `P0.5mm`, `P0.65mm`, `P1.27mm`, `P1mm`. (Write `P1mm`;
the single `P1.00mm` file is an outlier, not the rule.)

**Step 7 — EP geometry.** `_EP<w>x<l>mm` = the **copper** pad size from the land
pattern, in the same W-then-L orientation as the body. If the recommended land
pattern gives a solder-mask/paste opening smaller than the copper (typical of TI's
split-paste PowerPAD drawings), add `_Mask<w>x<l>mm` after it.

**Step 8 — remaining flags, in this order:** `_SlugUp`/`_SlugDown` (which face the
heat slug is on), `_Clearance<n>mm` (creepage-rated optocoupler spacing),
`_Reverse` (mirrored pinout), and finally `_ThermalVias` if you also ship a
via-stitched flavour. `_ThermalVias` is always last.

**Step 9 — vendor prefix, only when you must.** Prefix `<Vendor>_` only when the
land pattern is vendor-specific and would otherwise collide with a generic name.
Canonical vendor spellings actually in stock: `Analog`, `Linear`, `NXP`, `Texas`,
`Infineon`, `ST`, `STC`, `Renesas`, `Diodes`, `Toshiba`, `JEITA`, `OnSemi`,
`ONSemi`, `Vishay`, `Zetex`, `TI`, `PowerIntegrations`, `Microchip`, `Hitachi`.
If the vendor also has a drawing code, it goes second:
`Texas_PWP0028V_TSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP3.4x9.7mm_Mask2.94x5.62mm`.
Note `OnSemi` and `ONSemi` both exist — pick whichever matches the neighbouring
files you are extending, and do not "fix" the other.

**Step 10 — worked example.** A datasheet for a 24-lead HTSSOP, body 4.4 mm x 7.8 mm,
pitch 0.65 mm, bottom exposed pad 3.4 x 7.8 mm copper with a 2.4 x 3.5 mm paste
opening, plus a via-stitched option:

```
HTSSOP-24-1EP_4.4x7.8mm_P0.65mm_EP3.4x7.8mm_Mask2.4x3.5mm
HTSSOP-24-1EP_4.4x7.8mm_P0.65mm_EP3.4x7.8mm_Mask2.4x3.5mm_ThermalVias
```

which sits cleanly beside the real
`HTSSOP-24-1EP_4.4x7.8mm_P0.65mm_EP3.4x7.8mm_Mask2.4x2.98mm`.

## When the package is genuinely absent from KiCad stock

**First, prove it is absent.** Grep the two `.pretty` directories for the pin count
and the body number separately, because your guess at the family token may be
wrong. These, for example, do **not** exist despite looking obvious — I tested each
one: `SOIC-18_3.9x11.55mm_P1.27mm`, `SOIC-20_3.9x12.8mm_P1.27mm`,
`TSSOP-8_3x3mm_P0.5mm`, `MSOP-10_3x3mm_P0.65mm`, `SOIC-8W_7.5x5.85mm_P1.27mm`,
`QSOP-16_3.9x4.9mm_P0.65mm`, `SSOP-10_3.9x4.9mm_P1mm`. Note in particular that
there is **no narrow `SOIC-18`, `SOIC-20`, `SOIC-24` or `SOIC-28` at all** — only
the `W` wide-body versions plus `SO-20_5.3x12.6mm_P1.27mm` and
`SO-24_5.3x15mm_P1.27mm` in the `SO-` family. Also check the geometric twin under a
different family token: `VSSOP-8_3x3mm_P0.65mm` and `MSOP-8_3x3mm_P0.65mm` are the
same land pattern, and `SSOP-16_3.9x4.9mm_P0.635mm` matches
`QSOP-16_3.9x4.9mm_P0.635mm`.

**Then, in this project**, author it in the `7Sigma:` namespace via a
`propose_footprint_edit` draft proposal — never edit the KiCad stock library, and
never publish directly. Load the `kicad-conventions-footprints` skill first: the
house rules (0.1 mm pad grid, silk/fab/courtyard style, thermal vias under exposed
pads) are validator-enforced and differ from upstream KiCad in places. Keep the
name built by steps 1-9 above so it sorts next to its stock neighbours.

**Do not** paper over a missing size by reusing a footprint one size up — a
`4.4x9.7mm` TSSOP-28 is not a `4.4x7.8mm` TSSOP-28, and both exist in stock
precisely because the difference matters.

## Pitfalls

## 1. Names whose numbers do NOT mean WxL

I compared every one of the 503 names against its own `F.Fab` bounding box. Nine
disagree; six of those are real traps:

| File | Name says | `F.Fab` actually is | Trap |
|---|---|---|---|
| `SO-20_12.8x7.5mm_P1.27mm` | 12.8x7.5 | 4.4 wide x 12.8 long | Name is **LxW, reversed**. Worse: the fab body is drawn 4.4 mm wide, contradicting the 7.5 mm in the name, though the pads at x=±4.75 mm are correct for a 7.5 mm body. Treat the drawn outline as unreliable here. |
| `SO-6L_10x3.84mm_P1.27mm` | 10x3.84 | 7.5 wide x 3.84 long | The `10` is the **lead span**, not the body. Pad bbox is 10.3 mm. |
| `TSOP-II-32_21.0x10.2mm_P1.27mm` | 21.0x10.2 | 10.1 wide x 20.4 long | LxW, reversed. Also note `21.0` keeps a trailing zero. |
| `TSOP-II-54_22.2x10.16mm_P0.8mm` | 22.2x10.16 | 10.16 wide x 22.22 long | LxW, reversed. |
| `TSOP-I-32_18.4x8mm_P0.5mm_Reverse` | 18.4x8 | 8 wide x 18.4 long | The `_Reverse` twin is rotated 90°, so the name matches the *non*-Reverse file's orientation, not its own. |
| `PQFP-132_24x24mm_P0.635mm_i386` | 24x24 | 28x28 | Name and outline flatly disagree. Its plain sibling `PQFP-132_24x24mm_P0.635mm` really is 24x24. |

Three more differ by only 0.1 mm (rounding in the fab drawing, harmless):
`SO-4_4.4x2.3mm_P1.27mm`, `SSO-8_13.6x6.3mm_P1.27mm_Clearance14.2mm`,
`SSO-8_9.6x6.3mm_P1.27mm_Clearance10.5mm`.

**And note `TSOP-II` is self-inconsistent**: 2 of its 4 files are WxL
(`TSOP-II-44_10.16x18.41mm_P0.8mm`, `TSOP-II-40-44_10.16x18.37mm_P0.8mm`) and 2 are
LxW. Always open a TSOP-II footprint before trusting its name.

## 2. Pitch spelling: trailing zeros

`_P1mm` appears in 4 files (`SOIC-10_3.9x4.9mm_P1mm`,
`SSOP-10-1EP_3.9x4.9mm_P1mm_EP2.1x3.3mm` and its `_ThermalVias` twin,
`LQFP-52_14x14mm_P1mm`) but `_P1.00mm` appears in exactly one:
`SSOP-10_3.9x4.9mm_P1.00mm`. So the 10-pin SSOP on a 3.9x4.9 mm body is spelled
**two different ways** depending on whether it has an exposed pad. `SSOP-10_3.9x4.9mm_P1mm`
does **not** exist — I tested it.

## 3. `_ThermalVias` twins are NOT universal

Do not assume the pair exists in both directions.

* 93 footprints have both a plain and a `_ThermalVias` form.
* Many `-1EP` footprints have **no** `_ThermalVias` form at all, e.g.
  `TSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP2.15x3.35mm`,
  `TSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP2.85x6.7mm`,
  `TQFP-48-1EP_7x7mm_P0.5mm_EP4.11x4.11mm`,
  `HTSSOP-20-1EP_4.4x6.5mm_P0.65mm_EP3.4x6.5mm_Mask2.4x3.7mm`,
  `HSOP-20-1EP_11.0x15.9mm_P1.27mm_SlugUp` (`_SlugDown` has one, `_SlugUp` does not).
* Two footprints exist **only** in `_ThermalVias` form — stripping the suffix gives
  a nonexistent file:
  `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask3x3mm_ThermalVias` and
  `Texas_HTSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.95x4.9mm_Mask2.4x3.1mm_ThermalVias`.
  I verified that `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3.4x5mm_Mask3x3mm` does not
  exist. Beware: `HTSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm` DOES exist and is a
  **different** footprint (3x3 copper EP vs a 3.4x5 copper EP with a 3x3 mask).

## 4. The `W` suffix is unreliable — see the "how to name" section

`SOIC-8_7.5x5.85mm_P1.27mm` is wide-body without `W`;
`SOIC-16W_5.3x10.2mm_P1.27mm` carries `W` at 5.3 mm. `SOIC-8_5.3x5.3mm_P1.27mm`
and `SOIC-8_5.3x6.2mm_P1.27mm` are the 208-mil JEITA/EIAJ bodies and carry no `W`
either. Match on the number, not the letter.

## 5. Pin-range names read in two different orders

The dominant convention is **fitted-first, outline-second**:
`SOIC-14-16` = 16-pin outline, 14 pads. Same for `SOIC-16W-12` (16-pin outline,
12 pads, per its own `descr`), `SOIC-5-6`, `SO-5-6`, `Toshiba_SOIC-4-6`,
`Analog_MSOP-12-16`, `Linear_HTSSOP-31-38-1EP`, `TSOP-II-40-44`, `SSO-7-8`.

But `SSO-8-7_6.4x9.7mm_P2.54mm` has a `descr` of "SSO, 7 Pin" — i.e. it is
**outline-first**, the reverse of `SSO-7-8_6.4x9.78mm_P2.54mm` which describes the
same 7-in-8 situation. Two files, same meaning, opposite digit order, 0.08 mm apart
in body length. Read the `descr` before picking.

Do not confuse a pin-range with Infineon's outline codes: in
`Infineon_PG-DSO-8-27` the `-27` is a package **drawing revision**, not a pad
count. Same for `Infineon_PG-DSO-12-9`, `Infineon_PG-DSO-20-30`,
`Infineon_PG-DSO-20-U03`.

## 6. Same land pattern, several names — near-duplicate pairs

Search all of these before authoring anything new:

* `SOIC-8_3.9x4.9mm_P1.27mm` vs `SO-8_3.9x4.9mm_P1.27mm` vs
  `JEITA_SOIC-8_3.9x4.9mm_P1.27mm` vs `PowerIntegrations_SO-8`
* `SOIC-16_3.9x9.9mm_P1.27mm` vs `SO-16_3.9x9.9mm_P1.27mm` vs
  `JEITA_SOIC-16_3.9x9.9mm_P1.27mm` vs `STC_SOP-16_3.9x9.9mm_P1.27mm`
* `SOIC-16W_5.3x10.2mm_P1.27mm` vs `SO-16_5.3x10.2mm_P1.27mm` (same TI drawing)
* `SOIC-16_4.55x10.3mm_P1.27mm` vs `SOP-16_4.55x10.3mm_P1.27mm`
* `MSOP-8_3x3mm_P0.65mm` vs `VSSOP-8_3x3mm_P0.65mm` vs
  `Texas_S-PDSO-G8_3x3mm_P0.65mm` — three names, one 3x3/0.65 body
* `QSOP-16_3.9x4.9mm_P0.635mm` vs `SSOP-16_3.9x4.9mm_P0.635mm` — QSOP *is* the
  0.635 mm-pitch SSOP; the two names coexist
* `TSSOP-20_4.4x6.5mm_P0.65mm` vs `Texas_PW0020A_TSSOP-20_4.4x6.5mm_P0.65mm`
* `SOIC-20W_7.5x12.8mm_P1.27mm` vs `SOP-20_7.5x12.8mm_P1.27mm` vs
  `Infineon_SOIC-20W_7.6x12.8mm_P1.27mm` (7.5 vs 7.6 — a real 0.1 mm difference)
* `SOIC-24W_7.5x15.4mm_P1.27mm` vs `SOP-24_7.5x15.4mm_P1.27mm`
* `HTSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.4x3.2mm` vs
  `HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.1mm` vs
  `Texas_HSOP-8-1EP_3.9x4.9mm_P1.27mm` vs `TI_SO-PowerPAD-8` vs `Diodes_SO-8EP`
  vs `Diodes_PSOP-8` — six spellings of "SO-8 with a thermal pad"

## 7. Body sizes that differ by less than the width of the character

Copy-paste, never retype:

* `TSSOP-44_4.4x11mm_P0.5mm` vs `TSSOP-44_4.4x11.2mm_P0.5mm`
* `SOIC-28W_7.5x17.9mm_P1.27mm` vs `SOIC-28W_7.5x18.7mm_P1.27mm`
* `SOP-44_12.6x28.5mm_P1.27mm` vs `SOP-44_13.3x28.2mm_P1.27mm`
* `SOP-18_7x12.5mm_P1.27mm` vs `SOP-18_7.495x11.515mm_P1.27mm`
* `TSOP-II-44_10.16x18.41mm_P0.8mm` vs `TSOP-II-40-44_10.16x18.37mm_P0.8mm`
* `HTSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP3.4x9.5mm` — note the EP is 9.5 while the
  body is 9.7; the 28-pin TSSOP twin `TSSOP-28-1EP_4.4x9.7mm_P0.65mm_EP3.4x9.7mm_Mask3.1x4.05mm`
  has EP 9.7. One digit, different part.
* `SOIC-4_4.55x2.6mm_P1.27mm` vs `SOP-4_4.4x2.6mm_P1.27mm` vs
  `SSOP-4_4.4x2.6mm_P1.27mm` — three families, one plausible-looking size

The MSOP 12/16-pin body is `3x4.039mm` — three decimal places, and it is easy to
mistype as `3x4.04mm`, which does not exist.

## 8. Imperial/metric

Nothing in these libraries is imperial, but the *descriptions* quote mils, and the
mapping is not always the tidy one:

* 150 mil narrow SOIC → **3.9 mm** (JEDEC MS-012)
* 208 mil JEITA/EIAJ → **5.3 mm** (`SOIC-8_5.3x5.3mm_P1.27mm`)
* 300 mil wide SOIC → **7.5 mm** (MS-013), but `SOIC-32_7.518x20.777mm_P1.27mm`
  spells the same 300 mil family as **7.518 mm** (MO-119-B), and Infineon's as
  **7.6 mm**. Three numbers, one nominal.
* 0.025 in pitch → **0.635 mm** (QSOP, some SSOP) which is *not* the same as
  **0.65 mm** (MSOP, TSSOP, most SSOP). `QSOP-16_3.9x4.9mm_P0.65mm` does not
  exist; only the `P0.635mm` spelling does. This is the single most common
  mis-selection in this family.
* 0.05 in pitch → **1.27 mm**; 0.1 in → **2.54 mm**; 0.03 in → **0.762 mm**
  (`VSO-40_7.6x15.4mm_P0.762mm`, sitting next to `VSO-56_11.1x21.5mm_P0.75mm`
  at a genuinely metric 0.75 mm).

## 9. QFP prefix letters encode HEIGHT, not lead form

`L` = low profile (1.4 mm), `T` = thin (1.0 mm), `P` = plastic/tall legacy,
`E` = exposed pad, `HT` = thermally enhanced. All are gull-wing on four sides.
Consequence: `LQFP-64_10x10mm_P0.5mm` and `TQFP-64_10x10mm_P0.5mm` have identical
land patterns and differ only in the 3D height class — the datasheet's stated body
thickness is the only way to choose. The same duplication exists for
32/44/48/100/144/176-pin sizes. Also both `PQFP-44_10x10mm_P0.8mm` and
`Microchip_PQFP-44_10x10mm_P0.8mm` exist, as do `LQFP-44_10x10mm_P0.8mm` and
`TQFP-44_10x10mm_P0.8mm` — four names for one nominal package.

## 10. `-1EP` without an EP size, and `EP` size without `-1EP`

Both anomalies are real:

* `-1EP` present, no `_EP…` token: `TSSOP-14-1EP_4.4x5mm_P0.65mm`,
  `TSSOP-16-1EP_4.4x5mm_P0.65mm`, `Texas_HSOP-8-1EP_3.9x4.9mm_P1.27mm`,
  `HSOP-20-1EP_11.0x15.9mm_P1.27mm_SlugDown`,
  `HSOP-36-1EP_11.0x15.9mm_P0.65mm_SlugUp`. You must open the file to learn the
  pad size. Note `TSSOP-16-1EP_4.4x5mm_P0.65mm` and
  `TSSOP-16-1EP_4.4x5mm_P0.65mm_EP3x3mm` are two different footprints.
* `_EP…` present, no `-1EP`: `Infineon_PG-DSO-8-27_3.9x4.9mm_EP2.65x3mm`,
  `Texas_R-PDSO-G8_EP2.95x4.9mm_Mask2.4x3.1mm`.

## 11. Filed in the "wrong" library

`Texas_DYY0016A_TSOT-23-16_2x4.2mm_P0.5mm` lives in `Package_SO.pretty` and its
`descr` calls it a TSSOP, while its name calls it TSOT-23-16. `Package_SO.pretty`
also holds `SOJ-*` (J-lead, not gull-wing) and the Vishay/onsemi `PowerPAK` and
`Micro8` parts, which are leadless DFN-class packages. Do not assume everything in
`Package_SO.pretty` is a gull-wing SO.

## 12. Vendor prefix spelling is not normalised

`OnSemi_751EP_SOIC-4_…` and `OnSemi_Micro8` use one capitalisation;
`ONSemi_SO-8FL_488AA` uses another. `TI_SO-PowerPAD-8` and the many `Texas_…`
files are the same company under two prefixes. `Analog_MSOP-12-16…` and
`Linear_HTSSOP-31-38-1EP…` are also the same company post-acquisition. Search all
spellings.


---


# QFN / DFN / SON / LGA no-lead IC packages — KiCad 10.0.5 stock libraries `Package_DFN_QFN.pretty`, `Package_SON.pretty`, `Package_LGA.pretty` (plus `Package_CSP.pretty` for the LFCSP spelling of the same land pattern)

**Backed by:** **930 stock footprints** back this reference, all read from `/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/` on KiCad **10.0.5**:

- `Package_DFN_QFN.pretty` — 776 files
- `Package_SON.pretty` — 113 files
- `Package_LGA.pretty` — 41 files

Of those 930, **377 are manufacturer-neutral canonical names** that match the strict grammar; every one of the 377 is a row in the table below and every one was individually confirmed to exist with a per-file test (377/377 present, 0 missing). **239 of the 377** additionally ship a verified `_ThermalVias` sibling; **7 files** in total (across 4 base names) use `_PullBack`.

A further **68 LFCSP footprints** live in `Package_CSP.pretty` (179 files total in that library) and use the identical grammar — LFCSP is Analog Devices' name for the same land pattern, so it is *not* in `Package_DFN_QFN.pretty`.

Verification beyond the table: 53 additional names quoted in the grammar/pitfalls sections were each re-tested individually with `test -f` — 53/53 confirmed present.

## Grammar

## Exact token grammar

```
[<Mfr>_][<MfrPkgCode>_]<FAMILY>-<PINS>[-<POPULATED>][-<n>EP]
    _<BX>x<BY>mm
    _P<PITCH>mm
    [_EP<EX>x<EY>mm]
    [_<k>xMask<MX>x<MY>]
    [_LayoutBorder<a>x<b>y] [_Layout<a>x<b>] [_ClockwisePinNumbering]
    [_H<h>mm]
    [_PullBack]
    [_ThermalVias]
    [_TopTented]
```

Separator is `_` between fields and `-` inside the `<FAMILY>-<PINS>-<n>EP` head. Everything is case-sensitive ASCII; `x` is a lowercase letter, never `×` or `X`.

### Head fields

| Token | Required | Rule | Verified example |
|---|---|---|---|
| `<Mfr>_` | no | Manufacturer scope prefix. Use only when the land pattern is manufacturer-specific and not derivable generically. | `NXP_VQFN-16-1EP_4x4mm_P0.65mm_EP2.1x2.1mm` |
| `<MfrPkgCode>_` | no | The manufacturer's own package drawing code, inserted after `<Mfr>_`. | `Texas_RGZ0048A_VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm` |
| `<FAMILY>` | **yes** | Family prefix, verbatim from the datasheet's own package name (see prefix table). | `VQFN` |
| `-<PINS>` | **yes** | Count of **numbered perimeter leads only**. Exposed pads are *excluded*. | `QFN-48-…` → pads 1–48 are leads |
| `-<POPULATED>` | no | Second integer for depopulated outlines: an N-position outline of which only M are populated. | `Microsemi_QFN-40-32-2EP_6x8mm_P0.5mm` (descr: "40-Lead (32-Lead Populated)") |
| `-<n>EP` | no | Number of exposed thermal pads. Omit entirely if there is none. Values in stock: `1EP` (806 files), `2EP` (5), `3EP` (1), `4EP` (2), `5EP` (1), `6EP` (1), `10EP` (1), `33EP` (1), `59EP` (1). | `WDFN-6-2EP_4.0x2.6mm_P0.65mm`, `EPC_QFN-13-3EP_3.5x5mm_P0.5mm` |

**Verified invariant:** highest pad number in the file `= <PINS> + n`. This holds in 810 files; every exception is a hand-authored manufacturer file with alphanumeric pad names (`Microchip_DRQFN-*`, `Nordic_AQFN-*`, `Linear_LGA-133_*`) or a known naming defect (listed in pitfalls). So `QFN-32-1EP` has 33 distinct pad numbers, EP = pad 33; `QFN-48-1EP` → EP = pad 49.

### Geometry fields

| Token | Rule |
|---|---|
| `_<BX>x<BY>mm` | Nominal **body** size, X (horizontal) then Y (vertical), in the footprint's own top view. Single trailing `mm` for the pair. Verified against F.Fab: `QFN-28-1EP_3x6mm_P0.5mm_EP1.7x4.75mm` has pad 1 at x = −1.4625 (left column, body X = 3 mm) and pad 28 at y = −2.975 (top edge, body Y = 6 mm). Orientation is pin 1 top-left, numbering counter-clockwise (pad 1 y = −0.75, pad 2 y = −0.25 → down the left column first). |
| `_P<PITCH>mm` | Lead pitch. Stock values, by frequency: `0.5` (490), `0.4` (160), `0.65` (105), `0.8` (24), `0.45` (19), `1.27` (18), `0.35` (8), `0.95` (4), `0.6` (4), `0.7` (3), `1.25` (3), `0.48` (2), `1.65` (2), and singletons `0.43 0.51 0.9 1 1.15 1.3 2.00 2.1 2.54 3.3 5.08`. |
| `_EP<EX>x<EY>mm` | **Exposed-pad land** size, X then Y. **Verified: this equals the EP pad's `(size w h)` in the file exactly in 799 of 807 EP-bearing files.** Only present when `-<n>EP` is present *and* the pad is a plain rectangle. |
| `_<k>xMask<MX>x<MY>` | `k` solder-mask openings of `MX`×`MY` mm over the EP (mask-defined segmented EP). Note: **no trailing `mm`** on this token. Only 2 files use it: `NXP_LQFN-48-1EP_7x7mm_P0.5mm_EP3.5x3.5mm_16xMask0.45x0.45` and its `_ThermalVias` sibling. |
| `_LayoutBorder<a>x<b>y` | Perimeter grid shape for LGA/array parts: `a` pads across the top/bottom rows, `b` down each side. `LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y`, `Bosch_LGA-16_4.5x3mm_P0.5mm_LayoutBorder7x1y_ClockwisePinNumbering`, `Renesas_UQFN-20_2x3mm_P0.4mm_LayoutBorder4x6y`. |
| `_Layout<a>x<b>` | Full (non-perimeter) array grid: `ublox_LGA-53_4.5x4.5mm_Layout9x9_P0.5mm`, `Linear_LGA-133_15.0x15.0mm_Layout12x12_P1.27mm`. |
| `_ClockwisePinNumbering` | Numbering runs clockwise instead of the default counter-clockwise: `Bosch_LGA-8_3x3mm_P0.8mm_ClockwisePinNumbering`. |
| `_H<h>mm` | Body height, only where two heights share one land pattern: `NXP_LGA-8_3x5mm_P1.25mm_H1.1mm` vs `NXP_LGA-8_3x5mm_P1.25mm_H1.2mm`. |

### Qualifier fields (order is fixed: `PullBack` → `ThermalVias` → `TopTented`)

| Token | What it changes in the file | Verified examples |
|---|---|---|
| `_PullBack` | Lead lands are **pulled back inside the body outline** instead of running to the package edge. Confirmed geometrically: `QFN-16-1EP_4x4mm_P0.65mm_EP2.7x2.7mm` has pad 1 at x = −1.9625, size 0.825×0.3; the `_PullBack` variant has pad 1 at x = −1.775, size 0.45×0.4 — shorter pad, moved inboard. All 4 base names: `QFN-16-1EP_4x4mm_P0.65mm_EP2.7x2.7mm_PullBack`, `TQFN-24-1EP_4x4mm_P0.5mm_EP2.8x2.8mm_PullBack`, `DFN-6-1EP_1.2x1.2mm_P0.4mm_EP0.3x0.94mm_PullBack`, `WSON-8-1EP_3x2.5mm_P0.5mm_EP1.2x1.5mm_PullBack`. |
| `_ThermalVias` | Adds a via array under the EP. Confirmed structure in `QFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm_ThermalVias`: 25 `thru_hole circle` pads, `(size 0.5 0.5) (drill 0.2) (property pad_prop_heatsink) (layers "*.Cu") (remove_unused_layers no)`, all carrying the EP's pad number (49); the top EP pad drops `F.Paste` and keeps `F.Cu F.Mask`; paste is replaced by a grid of separate `F.Paste`-only windows; one `B.Cu` land is added. **Scaling is (n+1)² vias against n² paste windows** — 9 vias/4 windows (EP 2.7×2.7), 25/16 (EP 5.15×5.15), 49/36 (EP 7.65×7.65). Drill is always 0.2 mm, via pad always 0.5 mm. |
| `_TopTented` | Top-side EP mask tented. Exactly 1 file: `QFN-56-1EP_8x8mm_P0.5mm_EP4.5x5.2mm_ThermalVias_TopTented`. |
| `_DapStencil` | TI-specific stencil variant (hyphenated, non-conforming): `Texas_WQFN-MR-100_ThermalVias_3x3-DapStencil`. |
| `_RoutingVia` | Signal (not thermal) via included: `Texas_X2SON-5_0.8x0.8mm_P0.48mm_RoutingVia`. |

### Number formatting rules (derived from the stock set)

1. Decimal point is `.`; no thousands separators; no leading `+`.
2. **Strip trailing zeros**: `4x4mm` not `4.0x4.0mm`; `P1mm` not `P1.0mm`; `EP2x2mm` not `EP2.00x2.00mm`. (10 legacy files violate this — see pitfalls.)
3. Integers are written bare: `3x3mm`, `10x10mm`, `12x12mm`, `P1mm`.
4. Unit `mm` appears **once, after** the pair: `2.5x4.5mm`, `EP1.65x2.38mm`. Never `2.5mmx4.5mm`.
5. Up to 3 decimals are legitimate when the datasheet gives them: `EP1.646x3.1mm`, `EP1.675x1.675mm`, `EP0.675x0.76mm`, `EP1.854x1.854mm`, `EP2.642x2.642mm`.
6. Do **not** round datasheet values to a grid. `EP1.646x3.1mm` and `EP1.65x2.38mm` coexist as separate footprints because the datasheets differ; `QFN-16-1EP_3x3mm_P0.5mm` alone has 5 distinct EP sizes (1.45, 1.675, 1.7, 1.75, 1.9), all separate files.
7. The name encodes **body, pitch and EP only**. Lead-pad length/width are IPC-7351 derived and deliberately absent from the name.

## Reference table

## Table 1 — every distinct family prefix in the three libraries, with counts

All 68 prefixes that appear immediately before a pin count, across the 930 files. "Generic uses" = how many filenames *start* with that prefix (i.e. it is usable as a manufacturer-neutral name); a 0 there means the prefix only ever appears behind a manufacturer scope.

| Prefix | Files | Generic uses | Origin / meaning |
|---|---:|---:|---|
| `QFN` | 270 | 249 | Quad Flat No-lead — the default |
| `VQFN` | 115 | 71 | Very-thin QFN (0.9 mm) — TI/JEDEC |
| `DFN` | 94 | 86 | Dual Flat No-lead — the default 2-sided part |
| `WQFN` | 67 | 32 | Very-very-thin QFN (0.8 mm) — TI |
| `WSON` | 43 | 35 | Very-very-thin SON — TI |
| `TQFN` | 40 | 39 | Thin QFN — Maxim/ADI |
| `UQFN` | 31 | 25 | Ultra-thin QFN (0.5–0.6 mm) |
| `LGA` | 28 | 12 | Land Grid Array |
| `TDFN` | 20 | 16 | Thin DFN |
| `HVQFN` | 12 | 12 | Heatsink Very-thin QFN — NXP |
| `VSON` | 12 | 11 | Very-thin SON |
| `WDFN` | 12 | 12 | Very-very-thin DFN |
| `USON` | 10 | 2 | Ultra-thin SON |
| `MLF` | 8 | 5 | Micro Lead Frame — Amkor/Microchip/Micrel |
| `PVQFN` | 8 | 0 | TI JEDEC mechanical code (`S-PVQFN-N…`) |
| `PWSON` | 6 | 0 | TI JEDEC mechanical code (`S-PWSON-N…`) |
| `UDFN` | 6 | 3 | Ultra-thin DFN |
| `X2SON` | 6 | 1 | TI extra-extra-small SON |
| `LQFN` | 5 | 3 | Low-profile QFN — NXP |
| `MLPQ` | 5 | 1 | Micro Lead Package Quad — Infineon |
| `DHVQFN` | 4 | 4 | Dual-row HVQFN — NXP |
| `DRQFN` | 4 | 0 | Dual-row QFN — Microchip |
| `HUSON` | 4 | 1 | Heatsink USON — Nexperia |
| `MLP55` | 4 | 0 | Vishay PowerPAK MLP 5×5 |
| `PVSON` | 4 | 0 | TI JEDEC mechanical code |
| `TISON` | 4 | 0 | Infineon `PG-TISON-8-x` |
| `CDFN` | 3 | 3 | Ceramic/clip DFN |
| `PQFN` | 3 | 1 | Power QFN |
| `PWQFN` | 3 | 0 | TI JEDEC mechanical code |
| `UFQFPN` | 3 | 2 | Ultra-thin Fine-pitch QFP No-lead — ST |
| `AQFN` | 2 | 0 | Aggregated QFN — Nordic |
| `B3QFN` | 2 | 0 | TI bump-3 QFN |
| `DHWQFN` | 2 | 2 | Dual-row WQFN — NXP |
| `HLGA` | 2 | 0 | Holed LGA — ST sensors |
| `HVSON` | 2 | 2 | Heatsink VSON — NXP |
| `HXQFN` | 2 | 2 | NXP heatsink extra-thin QFN |
| `LSON` | 2 | 0 | Low-profile SON — NXP/Infineon |
| `MLP44` | 2 | 0 | Vishay PowerPAK MLP 4×4 |
| `PowerDI3333` | 2 | 0 | Diodes Inc trade name |
| `PUQFN` | 2 | 0 | TI (`R-PUQFN-N…`) |
| `PUSON` | 2 | 0 | TI (`R-PUSON-N…`) |
| `SON` | 2 | 1 | Small Outline No-lead, plain |
| `TQFN66` | 2 | 0 | Qorvo 6×6 TQFN |
| `CCLGA` | 1 | 0 | ST ceramic-cavity LGA |
| `DFN0604` | 1 | 0 | ROHM metric size code |
| `DFN1006` | 1 | 0 | Diodes metric size code |
| `FC2QFN` | 1 | 0 | Maxim flip-chip QFN |
| `HQFN` | 1 | 0 | Panasonic heatsink QFN |
| `HSON` | 1 | 0 | Panasonic heatsink SON |
| `OLGA` | 1 | 0 | AMS organic LGA |
| `PDFN` | 1 | 0 | TI (`S-PDSO`-adjacent) |
| `PowerFLAT` | 1 | 0 | ST trade name |
| `PX2QFN` | 1 | 0 | TI (`S-PX2QFN-14`) |
| `SIP` | 1 | 0 | OnSemi system-in-package |
| `TDSON` | 1 | 0 | Infineon `PG-TDSON-8` |
| `TSNP` | 1 | 0 | Infineon `PG-TSNP-6-10` |
| `UDFN2020` | 1 | 0 | Diodes metric size code |
| `UDFN3810` | 1 | 0 | Diodes metric size code |
| `UFDFPN` | 1 | 0 | ST ultra-thin fine-pitch DFN |
| `VCT` | 1 | 0 | OnSemi `VCT-28` |
| `VDFN` | 1 | 1 | Very-thin DFN |
| `VLGA` | 1 | 1 | Very-thin LGA |
| `VSONP` | 1 | 1 | VSON with power tab |
| `WFDFPN` | 1 | 1 | ST very-very-thin fine-pitch DFN |
| `X2QFN` | 1 | 0 | TI extra-extra-small QFN |
| `XDFN` | 1 | 0 | OnSemi extra-thin DFN |
| `XDFN4` | 1 | 0 | OnSemi `XDFN4-1EP` |
| `XSON` | 1 | 0 | NXP extra-thin SON |

Plus, in `Package_CSP.pretty` (**not** in the three libraries above): `LFCSP` — 68 files, e.g. `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm`, `LFCSP-16-1EP_4x4mm_P0.65mm_EP2.6x2.6mm`, and the ADI sub-codes `LFCSP-WD-8-1EP_3x3mm_P0.65mm_EP1.6x2.44mm`, `LFCSP-VQ-24-1EP_4x4mm_P0.5mm_EP2.642x2.642mm`.

---

## Table 2 — all 377 canonical (manufacturer-neutral) stock footprints

Every name below is a verbatim filename minus `.kicad_mod`, individually confirmed present (377/377).
**TV** = a `_ThermalVias` sibling exists (append `_ThermalVias` to the name; 239 rows, each verified). **PB** = a `_PullBack` sibling exists. `.` = does not exist.

| Family | Pins | Body (mm) | Pitch (mm) | EP (mm) | TV | PB | Library | Verbatim footprint name |
|---|---:|---|---:|---|:-:|:-:|---|---|
| QFN | 8 | 6x5 | 1.27 | 3.4x4.2 | . | . | Package_DFN_QFN | `QFN-8-1EP_6x5mm_P1.27mm_EP3.4x4.2mm` |
| QFN | 12 | 3x3 | 0.5 | 1.45x1.45 | Y | . | Package_DFN_QFN | `QFN-12-1EP_3x3mm_P0.5mm_EP1.45x1.45mm` |
| QFN | 12 | 3x3 | 0.5 | 1.6x1.6 | Y | . | Package_DFN_QFN | `QFN-12-1EP_3x3mm_P0.5mm_EP1.6x1.6mm` |
| QFN | 12 | 3x3 | 0.5 | 1.65x1.65 | Y | . | Package_DFN_QFN | `QFN-12-1EP_3x3mm_P0.5mm_EP1.65x1.65mm` |
| QFN | 12 | 3x3 | 0.51 | 1.45x1.45 | . | . | Package_DFN_QFN | `QFN-12-1EP_3x3mm_P0.51mm_EP1.45x1.45mm` |
| QFN | 16 | 1.8x2.6 | 0.4 | 0.7x1.5 | Y | . | Package_DFN_QFN | `QFN-16-1EP_1.8x2.6mm_P0.4mm_EP0.7x1.5mm` |
| QFN | 16 | 3x3 | 0.5 | 1.45x1.45 | Y | . | Package_DFN_QFN | `QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm` |
| QFN | 16 | 3x3 | 0.5 | 1.675x1.675 | . | . | Package_DFN_QFN | `QFN-16-1EP_3x3mm_P0.5mm_EP1.675x1.675mm` |
| QFN | 16 | 3x3 | 0.5 | 1.7x1.7 | Y | . | Package_DFN_QFN | `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm` |
| QFN | 16 | 3x3 | 0.5 | 1.75x1.75 | Y | . | Package_DFN_QFN | `QFN-16-1EP_3x3mm_P0.5mm_EP1.75x1.75mm` |
| QFN | 16 | 3x3 | 0.5 | 1.9x1.9 | Y | . | Package_DFN_QFN | `QFN-16-1EP_3x3mm_P0.5mm_EP1.9x1.9mm` |
| QFN | 16 | 4x4 | 0.5 | 2.45x2.45 | Y | . | Package_DFN_QFN | `QFN-16-1EP_4x4mm_P0.5mm_EP2.45x2.45mm` |
| QFN | 16 | 4x4 | 0.65 | 2.1x2.1 | Y | . | Package_DFN_QFN | `QFN-16-1EP_4x4mm_P0.65mm_EP2.1x2.1mm` |
| QFN | 16 | 4x4 | 0.65 | 2.15x2.15 | Y | . | Package_DFN_QFN | `QFN-16-1EP_4x4mm_P0.65mm_EP2.15x2.15mm` |
| QFN | 16 | 4x4 | 0.65 | 2.5x2.5 | Y | . | Package_DFN_QFN | `QFN-16-1EP_4x4mm_P0.65mm_EP2.5x2.5mm` |
| QFN | 16 | 4x4 | 0.65 | 2.7x2.7 | Y | Y | Package_DFN_QFN | `QFN-16-1EP_4x4mm_P0.65mm_EP2.7x2.7mm` |
| QFN | 16 | 5x5 | 0.8 | 2.7x2.7 | Y | . | Package_DFN_QFN | `QFN-16-1EP_5x5mm_P0.8mm_EP2.7x2.7mm` |
| QFN | 20 | 3x3 | 0.4 | 1.65x1.65 | Y | . | Package_DFN_QFN | `QFN-20-1EP_3x3mm_P0.4mm_EP1.65x1.65mm` |
| QFN | 20 | 3x3 | 0.45 | 1.6x1.6 | Y | . | Package_DFN_QFN | `QFN-20-1EP_3x3mm_P0.45mm_EP1.6x1.6mm` |
| QFN | 20 | 3x4 | 0.5 | 1.65x2.65 | Y | . | Package_DFN_QFN | `QFN-20-1EP_3x4mm_P0.5mm_EP1.65x2.65mm` |
| QFN | 20 | 3.5x3.5 | 0.5 | 2x2 | Y | . | Package_DFN_QFN | `QFN-20-1EP_3.5x3.5mm_P0.5mm_EP2x2mm` |
| QFN | 20 | 4x4 | 0.5 | 2.5x2.5 | Y | . | Package_DFN_QFN | `QFN-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm` |
| QFN | 20 | 4x4 | 0.5 | 2.6x2.6 | Y | . | Package_DFN_QFN | `QFN-20-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` |
| QFN | 20 | 4x4 | 0.5 | 2.7x2.7 | Y | . | Package_DFN_QFN | `QFN-20-1EP_4x4mm_P0.5mm_EP2.7x2.7mm` |
| QFN | 20 | 4x5 | 0.5 | 2.65x3.65 | Y | . | Package_DFN_QFN | `QFN-20-1EP_4x5mm_P0.5mm_EP2.65x3.65mm` |
| QFN | 20 | 5x5 | 0.65 | 3.35x3.35 | Y | . | Package_DFN_QFN | `QFN-20-1EP_5x5mm_P0.65mm_EP3.35x3.35mm` |
| QFN | 24 | 3x3 | 0.4 | 1.75x1.6 | Y | . | Package_DFN_QFN | `QFN-24-1EP_3x3mm_P0.4mm_EP1.75x1.6mm` |
| QFN | 24 | 3x4 | 0.4 | 1.65x2.65 | Y | . | Package_DFN_QFN | `QFN-24-1EP_3x4mm_P0.4mm_EP1.65x2.65mm` |
| QFN | 24 | 4x4 | 0.5 | 2.15x2.15 | Y | . | Package_DFN_QFN | `QFN-24-1EP_4x4mm_P0.5mm_EP2.15x2.15mm` |
| QFN | 24 | 4x4 | 0.5 | 2.5x2.5 | . | . | Package_DFN_QFN | `QFN-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm` |
| QFN | 24 | 4x4 | 0.5 | 2.6x2.6 | Y | . | Package_DFN_QFN | `QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` |
| QFN | 24 | 4x4 | 0.5 | 2.65x2.65 | Y | . | Package_DFN_QFN | `QFN-24-1EP_4x4mm_P0.5mm_EP2.65x2.65mm` |
| QFN | 24 | 4x4 | 0.5 | 2.7x2.6 | Y | . | Package_DFN_QFN | `QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.6mm` |
| QFN | 24 | 4x4 | 0.5 | 2.7x2.7 | Y | . | Package_DFN_QFN | `QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm` |
| QFN | 24 | 4x4 | 0.5 | 2.75x2.75 | Y | . | Package_DFN_QFN | `QFN-24-1EP_4x4mm_P0.5mm_EP2.75x2.75mm` |
| QFN | 24 | 4x4 | 0.5 | 2.8x2.8 | Y | . | Package_DFN_QFN | `QFN-24-1EP_4x4mm_P0.5mm_EP2.8x2.8mm` |
| QFN | 24 | 4x5 | 0.5 | 2.65x3.65 | Y | . | Package_DFN_QFN | `QFN-24-1EP_4x5mm_P0.5mm_EP2.65x3.65mm` |
| QFN | 24 | 5x5 | 0.65 | 3.2x3.2 | Y | . | Package_DFN_QFN | `QFN-24-1EP_5x5mm_P0.65mm_EP3.2x3.2mm` |
| QFN | 24 | 5x5 | 0.65 | 3.25x3.25 | Y | . | Package_DFN_QFN | `QFN-24-1EP_5x5mm_P0.65mm_EP3.25x3.25mm` |
| QFN | 24 | 5x5 | 0.65 | 3.4x3.4 | Y | . | Package_DFN_QFN | `QFN-24-1EP_5x5mm_P0.65mm_EP3.4x3.4mm` |
| QFN | 24 | 5x5 | 0.65 | 3.6x3.6 | Y | . | Package_DFN_QFN | `QFN-24-1EP_5x5mm_P0.65mm_EP3.6x3.6mm` |
| QFN | 28 | 4x4 | 0.4 | 2.3x2.3 | Y | . | Package_DFN_QFN | `QFN-28-1EP_4x4mm_P0.4mm_EP2.3x2.3mm` |
| QFN | 28 | 4x4 | 0.4 | 2.4x2.4 | Y | . | Package_DFN_QFN | `QFN-28-1EP_4x4mm_P0.4mm_EP2.4x2.4mm` |
| QFN | 28 | 4x4 | 0.45 | 2.4x2.4 | Y | . | Package_DFN_QFN | `QFN-28-1EP_4x4mm_P0.45mm_EP2.4x2.4mm` |
| QFN | 28 | 4x4 | 0.45 | 2.6x2.6 | . | . | Package_DFN_QFN | `QFN-28-1EP_4x4mm_P0.45mm_EP2.6x2.6mm` |
| QFN | 28 | 4x4 | 0.5 | no EP | . | . | Package_DFN_QFN | `QFN-28_4x4mm_P0.5mm` |
| QFN | 28 | 3x6 | 0.5 | 1.7x4.75 | Y | . | Package_DFN_QFN | `QFN-28-1EP_3x6mm_P0.5mm_EP1.7x4.75mm` |
| QFN | 28 | 4x5 | 0.5 | 2.65x3.65 | Y | . | Package_DFN_QFN | `QFN-28-1EP_4x5mm_P0.5mm_EP2.65x3.65mm` |
| QFN | 28 | 5x5 | 0.5 | 2.7x2.7 | Y | . | Package_DFN_QFN | `QFN-28-1EP_5x5mm_P0.5mm_EP2.7x2.7mm` |
| QFN | 28 | 5x5 | 0.5 | 3.1x3.1 | Y | . | Package_DFN_QFN | `QFN-28-1EP_5x5mm_P0.5mm_EP3.1x3.1mm` |
| QFN | 28 | 5x5 | 0.5 | 3.25x3.25 | Y | . | Package_DFN_QFN | `QFN-28-1EP_5x5mm_P0.5mm_EP3.25x3.25mm` |
| QFN | 28 | 5x5 | 0.5 | 3.35x3.35 | Y | . | Package_DFN_QFN | `QFN-28-1EP_5x5mm_P0.5mm_EP3.35x3.35mm` |
| QFN | 28 | 5x5 | 0.5 | 3.75x3.75 | Y | . | Package_DFN_QFN | `QFN-28-1EP_5x5mm_P0.5mm_EP3.75x3.75mm` |
| QFN | 28 | 5x6 | 0.5 | 3.65x4.65 | Y | . | Package_DFN_QFN | `QFN-28-1EP_5x6mm_P0.5mm_EP3.65x4.65mm` |
| QFN | 28 | 6x6 | 0.65 | 4.25x4.25 | Y | . | Package_DFN_QFN | `QFN-28-1EP_6x6mm_P0.65mm_EP4.25x4.25mm` |
| QFN | 28 | 6x6 | 0.65 | 4.8x4.8 | Y | . | Package_DFN_QFN | `QFN-28-1EP_6x6mm_P0.65mm_EP4.8x4.8mm` |
| QFN | 32 | 4x4 | 0.4 | 2.65x2.65 | Y | . | Package_DFN_QFN | `QFN-32-1EP_4x4mm_P0.4mm_EP2.65x2.65mm` |
| QFN | 32 | 4x4 | 0.4 | 2.9x2.9 | Y | . | Package_DFN_QFN | `QFN-32-1EP_4x4mm_P0.4mm_EP2.9x2.9mm` |
| QFN | 32 | 5x5 | 0.5 | 3.1x3.1 | Y | . | Package_DFN_QFN | `QFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm` |
| QFN | 32 | 5x5 | 0.5 | 3.3x3.3 | Y | . | Package_DFN_QFN | `QFN-32-1EP_5x5mm_P0.5mm_EP3.3x3.3mm` |
| QFN | 32 | 5x5 | 0.5 | 3.45x3.45 | Y | . | Package_DFN_QFN | `QFN-32-1EP_5x5mm_P0.5mm_EP3.45x3.45mm` |
| QFN | 32 | 5x5 | 0.5 | 3.6x3.6 | Y | . | Package_DFN_QFN | `QFN-32-1EP_5x5mm_P0.5mm_EP3.6x3.6mm` |
| QFN | 32 | 5x5 | 0.5 | 3.65x3.65 | Y | . | Package_DFN_QFN | `QFN-32-1EP_5x5mm_P0.5mm_EP3.65x3.65mm` |
| QFN | 32 | 5x5 | 0.5 | 3.7x3.7 | Y | . | Package_DFN_QFN | `QFN-32-1EP_5x5mm_P0.5mm_EP3.7x3.7mm` |
| QFN | 32 | 7x7 | 0.65 | 4.65x4.65 | Y | . | Package_DFN_QFN | `QFN-32-1EP_7x7mm_P0.65mm_EP4.65x4.65mm` |
| QFN | 32 | 7x7 | 0.65 | 4.7x4.7 | Y | . | Package_DFN_QFN | `QFN-32-1EP_7x7mm_P0.65mm_EP4.7x4.7mm` |
| QFN | 32 | 7x7 | 0.65 | 5.4x5.4 | Y | . | Package_DFN_QFN | `QFN-32-1EP_7x7mm_P0.65mm_EP5.4x5.4mm` |
| QFN | 36 | 5x6 | 0.5 | 3.6x4.1 | Y | . | Package_DFN_QFN | `QFN-36-1EP_5x6mm_P0.5mm_EP3.6x4.1mm` |
| QFN | 36 | 5x6 | 0.5 | 3.6x4.6 | Y | . | Package_DFN_QFN | `QFN-36-1EP_5x6mm_P0.5mm_EP3.6x4.6mm` |
| QFN | 36 | 6x6 | 0.5 | 3.7x3.7 | Y | . | Package_DFN_QFN | `QFN-36-1EP_6x6mm_P0.5mm_EP3.7x3.7mm` |
| QFN | 36 | 6x6 | 0.5 | 4.1x4.1 | Y | . | Package_DFN_QFN | `QFN-36-1EP_6x6mm_P0.5mm_EP4.1x4.1mm` |
| QFN | 38 | 4x6 | 0.4 | 2.65x4.65 | Y | . | Package_DFN_QFN | `QFN-38-1EP_4x6mm_P0.4mm_EP2.65x4.65mm` |
| QFN | 40 | 5x5 | 0.4 | 3.6x3.6 | Y | . | Package_DFN_QFN | `QFN-40-1EP_5x5mm_P0.4mm_EP3.6x3.6mm` |
| QFN | 40 | 5x5 | 0.4 | 3.8x3.8 | Y | . | Package_DFN_QFN | `QFN-40-1EP_5x5mm_P0.4mm_EP3.8x3.8mm` |
| QFN | 40 | 6x6 | 0.5 | 4.6x4.6 | Y | . | Package_DFN_QFN | `QFN-40-1EP_6x6mm_P0.5mm_EP4.6x4.6mm` |
| QFN | 42 | 5x6 | 0.4 | 3.7x4.7 | Y | . | Package_DFN_QFN | `QFN-42-1EP_5x6mm_P0.4mm_EP3.7x4.7mm` |
| QFN | 44 | 7x7 | 0.5 | 5.15x5.15 | Y | . | Package_DFN_QFN | `QFN-44-1EP_7x7mm_P0.5mm_EP5.15x5.15mm` |
| QFN | 44 | 7x7 | 0.5 | 5.2x5.2 | Y | . | Package_DFN_QFN | `QFN-44-1EP_7x7mm_P0.5mm_EP5.2x5.2mm` |
| QFN | 44 | 8x8 | 0.65 | 6.45x6.45 | Y | . | Package_DFN_QFN | `QFN-44-1EP_8x8mm_P0.65mm_EP6.45x6.45mm` |
| QFN | 44 | 9x9 | 0.65 | 7.5x7.5 | Y | . | Package_DFN_QFN | `QFN-44-1EP_9x9mm_P0.65mm_EP7.5x7.5mm` |
| QFN | 48 | 5x5 | 0.35 | 3.7x3.7 | Y | . | Package_DFN_QFN | `QFN-48-1EP_5x5mm_P0.35mm_EP3.7x3.7mm` |
| QFN | 48 | 6x6 | 0.4 | 4.2x4.2 | Y | . | Package_DFN_QFN | `QFN-48-1EP_6x6mm_P0.4mm_EP4.2x4.2mm` |
| QFN | 48 | 6x6 | 0.4 | 4.3x4.3 | Y | . | Package_DFN_QFN | `QFN-48-1EP_6x6mm_P0.4mm_EP4.3x4.3mm` |
| QFN | 48 | 6x6 | 0.4 | 4.4x4.4 | Y | . | Package_DFN_QFN | `QFN-48-1EP_6x6mm_P0.4mm_EP4.4x4.4mm` |
| QFN | 48 | 6x6 | 0.4 | 4.6x4.6 | Y | . | Package_DFN_QFN | `QFN-48-1EP_6x6mm_P0.4mm_EP4.6x4.6mm` |
| QFN | 48 | 6x6 | 0.4 | 4.66x4.66 | Y | . | Package_DFN_QFN | `QFN-48-1EP_6x6mm_P0.4mm_EP4.66x4.66mm` |
| QFN | 48 | 7x7 | 0.5 | 3.5x3.5 | Y | . | Package_DFN_QFN | `QFN-48-1EP_7x7mm_P0.5mm_EP3.5x3.5mm` |
| QFN | 48 | 7x7 | 0.5 | 5.1x5.1 | Y | . | Package_DFN_QFN | `QFN-48-1EP_7x7mm_P0.5mm_EP5.1x5.1mm` |
| QFN | 48 | 7x7 | 0.5 | 5.15x5.15 | Y | . | Package_DFN_QFN | `QFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm` |
| QFN | 48 | 7x7 | 0.5 | 5.3x5.3 | Y | . | Package_DFN_QFN | `QFN-48-1EP_7x7mm_P0.5mm_EP5.3x5.3mm` |
| QFN | 48 | 7x7 | 0.5 | 5.45x5.45 | Y | . | Package_DFN_QFN | `QFN-48-1EP_7x7mm_P0.5mm_EP5.45x5.45mm` |
| QFN | 48 | 7x7 | 0.5 | 5.6x5.6 | Y | . | Package_DFN_QFN | `QFN-48-1EP_7x7mm_P0.5mm_EP5.6x5.6mm` |
| QFN | 48 | 7x7 | 0.5 | 5.7x5.7 | Y | . | Package_DFN_QFN | `QFN-48-1EP_7x7mm_P0.5mm_EP5.7x5.7mm` |
| QFN | 48 | 8x8 | 0.5 | 6.2x6.2 | Y | . | Package_DFN_QFN | `QFN-48-1EP_8x8mm_P0.5mm_EP6.2x6.2mm` |
| QFN | 52 | 7x8 | 0.5 | 5.41x6.45 | Y | . | Package_DFN_QFN | `QFN-52-1EP_7x8mm_P0.5mm_EP5.41x6.45mm` |
| QFN | 56 | 7x7 | 0.4 | 3.2x3.2 | Y | . | Package_DFN_QFN | `QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm` |
| QFN | 56 | 7x7 | 0.4 | 4x4 | Y | . | Package_DFN_QFN | `QFN-56-1EP_7x7mm_P0.4mm_EP4x4mm` |
| QFN | 56 | 7x7 | 0.4 | 5.6x5.6 | Y | . | Package_DFN_QFN | `QFN-56-1EP_7x7mm_P0.4mm_EP5.6x5.6mm` |
| QFN | 56 | 8x8 | 0.5 | 4.3x4.3 | Y | . | Package_DFN_QFN | `QFN-56-1EP_8x8mm_P0.5mm_EP4.3x4.3mm` |
| QFN | 56 | 8x8 | 0.5 | 4.5x5.2 | Y | . | Package_DFN_QFN | `QFN-56-1EP_8x8mm_P0.5mm_EP4.5x5.2mm` |
| QFN | 56 | 8x8 | 0.5 | 5.6x5.6 | Y | . | Package_DFN_QFN | `QFN-56-1EP_8x8mm_P0.5mm_EP5.6x5.6mm` |
| QFN | 56 | 8x8 | 0.5 | 5.9x5.9 | Y | . | Package_DFN_QFN | `QFN-56-1EP_8x8mm_P0.5mm_EP5.9x5.9mm` |
| QFN | 56 | 8x8 | 0.5 | 6.1x6.1 | Y | . | Package_DFN_QFN | `QFN-56-1EP_8x8mm_P0.5mm_EP6.1x6.1mm` |
| QFN | 60 | 7x7 | 0.4 | 3.4x3.4 | Y | . | Package_DFN_QFN | `QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm` |
| QFN | 64 | 8x8 | 0.4 | 6.5x6.5 | Y | . | Package_DFN_QFN | `QFN-64-1EP_8x8mm_P0.4mm_EP6.5x6.5mm` |
| QFN | 64 | 9x9 | 0.5 | 3.4x3.4 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP3.4x3.4mm` |
| QFN | 64 | 9x9 | 0.5 | 3.8x3.8 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP3.8x3.8mm` |
| QFN | 64 | 9x9 | 0.5 | 4.1x4.1 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP4.1x4.1mm` |
| QFN | 64 | 9x9 | 0.5 | 4.35x4.35 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP4.35x4.35mm` |
| QFN | 64 | 9x9 | 0.5 | 4.7x4.7 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP4.7x4.7mm` |
| QFN | 64 | 9x9 | 0.5 | 5.2x5.2 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP5.2x5.2mm` |
| QFN | 64 | 9x9 | 0.5 | 5.4x5.4 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP5.4x5.4mm` |
| QFN | 64 | 9x9 | 0.5 | 5.45x5.45 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP5.45x5.45mm` |
| QFN | 64 | 9x9 | 0.5 | 5.7x5.7 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP5.7x5.7mm` |
| QFN | 64 | 9x9 | 0.5 | 6x6 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP6x6mm` |
| QFN | 64 | 9x9 | 0.5 | 7.15x7.15 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP7.15x7.15mm` |
| QFN | 64 | 9x9 | 0.5 | 7.25x7.25 | . | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP7.25x7.25mm` |
| QFN | 64 | 9x9 | 0.5 | 7.3x7.3 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP7.3x7.3mm` |
| QFN | 64 | 9x9 | 0.5 | 7.35x7.35 | . | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP7.35x7.35mm` |
| QFN | 64 | 9x9 | 0.5 | 7.5x7.5 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP7.5x7.5mm` |
| QFN | 64 | 9x9 | 0.5 | 7.65x7.65 | Y | . | Package_DFN_QFN | `QFN-64-1EP_9x9mm_P0.5mm_EP7.65x7.65mm` |
| QFN | 68 | 8x8 | 0.4 | 5.2x5.2 | Y | . | Package_DFN_QFN | `QFN-68-1EP_8x8mm_P0.4mm_EP5.2x5.2mm` |
| QFN | 68 | 8x8 | 0.4 | 6.4x6.4 | Y | . | Package_DFN_QFN | `QFN-68-1EP_8x8mm_P0.4mm_EP6.4x6.4mm` |
| QFN | 72 | 10x10 | 0.5 | 6x6 | Y | . | Package_DFN_QFN | `QFN-72-1EP_10x10mm_P0.5mm_EP6x6mm` |
| QFN | 76 | 9x9 | 0.4 | 3.8x3.8 | Y | . | Package_DFN_QFN | `QFN-76-1EP_9x9mm_P0.4mm_EP3.8x3.8mm` |
| QFN | 76 | 9x9 | 0.4 | 5.81x6.31 | Y | . | Package_DFN_QFN | `QFN-76-1EP_9x9mm_P0.4mm_EP5.81x6.31mm` |
| QFN | 80 | 10x10 | 0.4 | 3.4x3.4 | Y | . | Package_DFN_QFN | `QFN-80-1EP_10x10mm_P0.4mm_EP3.4x3.4mm` |
| VQFN | 12 | 4x4 | 0.8 | 2.1x2.1 | Y | . | Package_DFN_QFN | `VQFN-12-1EP_4x4mm_P0.8mm_EP2.1x2.1mm` |
| VQFN | 16 | 3x3 | 0.5 | 1.1x1.1 | Y | . | Package_DFN_QFN | `VQFN-16-1EP_3x3mm_P0.5mm_EP1.1x1.1mm` |
| VQFN | 16 | 3x3 | 0.5 | 1.45x1.45 | Y | . | Package_DFN_QFN | `VQFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm` |
| VQFN | 16 | 3x3 | 0.5 | 1.6x1.6 | Y | . | Package_DFN_QFN | `VQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm` |
| VQFN | 16 | 3x3 | 0.5 | 1.68x1.68 | Y | . | Package_DFN_QFN | `VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm` |
| VQFN | 16 | 3x3 | 0.5 | 1.8x1.8 | Y | . | Package_DFN_QFN | `VQFN-16-1EP_3x3mm_P0.5mm_EP1.8x1.8mm` |
| VQFN | 20 | 3x3 | 0.4 | 1.7x1.7 | Y | . | Package_DFN_QFN | `VQFN-20-1EP_3x3mm_P0.4mm_EP1.7x1.7mm` |
| VQFN | 20 | 3x3 | 0.45 | 1.55x1.55 | Y | . | Package_DFN_QFN | `VQFN-20-1EP_3x3mm_P0.45mm_EP1.55x1.55mm` |
| VQFN | 24 | 4x4 | 0.5 | 2.45x2.45 | Y | . | Package_DFN_QFN | `VQFN-24-1EP_4x4mm_P0.5mm_EP2.45x2.45mm` |
| VQFN | 24 | 4x4 | 0.5 | 2.5x2.5 | Y | . | Package_DFN_QFN | `VQFN-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm` |
| VQFN | 28 | 4x4 | 0.45 | 2.4x2.4 | Y | . | Package_DFN_QFN | `VQFN-28-1EP_4x4mm_P0.45mm_EP2.4x2.4mm` |
| VQFN | 28 | 4x5 | 0.5 | 2.55x3.55 | Y | . | Package_DFN_QFN | `VQFN-28-1EP_4x5mm_P0.5mm_EP2.55x3.55mm` |
| VQFN | 28 | 5x5 | 0.5 | 3.25x3.25 | Y | . | Package_DFN_QFN | `VQFN-28-1EP_5x5mm_P0.5mm_EP3.25x3.25mm` |
| VQFN | 28 | 5x5 | 0.5 | 3.7x3.7 | Y | . | Package_DFN_QFN | `VQFN-28-1EP_5x5mm_P0.5mm_EP3.7x3.7mm` |
| VQFN | 32 | 4x4 | 0.4 | 2.8x2.8 | Y | . | Package_DFN_QFN | `VQFN-32-1EP_4x4mm_P0.4mm_EP2.8x2.8mm` |
| VQFN | 32 | 5x5 | 0.5 | 3.1x3.1 | Y | . | Package_DFN_QFN | `VQFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm` |
| VQFN | 32 | 5x5 | 0.5 | 3.15x3.15 | Y | . | Package_DFN_QFN | `VQFN-32-1EP_5x5mm_P0.5mm_EP3.15x3.15mm` |
| VQFN | 32 | 5x5 | 0.5 | 3.5x3.5 | Y | . | Package_DFN_QFN | `VQFN-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm` |
| VQFN | 40 | 5x5 | 0.4 | 3.3x3.3 | Y | . | Package_DFN_QFN | `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm` |
| VQFN | 40 | 5x5 | 0.4 | 3.5x3.5 | Y | . | Package_DFN_QFN | `VQFN-40-1EP_5x5mm_P0.4mm_EP3.5x3.5mm` |
| VQFN | 40 | 5x5 | 0.4 | 3.6x3.6 | Y | . | Package_DFN_QFN | `VQFN-40-1EP_5x5mm_P0.4mm_EP3.6x3.6mm` |
| VQFN | 40 | 5x5 | 0.4 | 3.7x3.7 | Y | . | Package_DFN_QFN | `VQFN-40-1EP_5x5mm_P0.4mm_EP3.7x3.7mm` |
| VQFN | 40 | 6x6 | 0.5 | 3.5x3.5 | Y | . | Package_DFN_QFN | `VQFN-40-1EP_6x6mm_P0.5mm_EP3.5x3.5mm` |
| VQFN | 46 | 5x6 | 0.4 | 2.8x3.8 | Y | . | Package_DFN_QFN | `VQFN-46-1EP_5x6mm_P0.4mm_EP2.8x3.8mm` |
| VQFN | 48 | 6x6 | 0.4 | 4.1x4.1 | Y | . | Package_DFN_QFN | `VQFN-48-1EP_6x6mm_P0.4mm_EP4.1x4.1mm` |
| VQFN | 48 | 7x7 | 0.5 | 2.6x2.6 | Y | . | Package_DFN_QFN | `VQFN-48-1EP_7x7mm_P0.5mm_EP2.6x2.6mm` |
| VQFN | 48 | 7x7 | 0.5 | 4.1x4.1 | Y | . | Package_DFN_QFN | `VQFN-48-1EP_7x7mm_P0.5mm_EP4.1x4.1mm` |
| VQFN | 48 | 7x7 | 0.5 | 4.2x4.2 | Y | . | Package_DFN_QFN | `VQFN-48-1EP_7x7mm_P0.5mm_EP4.2x4.2mm` |
| VQFN | 48 | 7x7 | 0.5 | 5.15x5.15 | Y | . | Package_DFN_QFN | `VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm` |
| VQFN | 52 | 6x6 | 0.4 | 4.7x4.7 | Y | . | Package_DFN_QFN | `VQFN-52-1EP_6x6mm_P0.4mm_EP4.7x4.7mm` |
| VQFN | 56 | 8x8 | 0.5 | 5.1x4.96 | Y | . | Package_DFN_QFN | `VQFN-56-1EP_8x8mm_P0.5mm_EP5.1x4.96mm` |
| VQFN | 56 | 8x8 | 0.5 | 5.5x5.06 | Y | . | Package_DFN_QFN | `VQFN-56-1EP_8x8mm_P0.5mm_EP5.5x5.06mm` |
| VQFN | 64 | 9x9 | 0.5 | 5.4x5.4 | Y | . | Package_DFN_QFN | `VQFN-64-1EP_9x9mm_P0.5mm_EP5.4x5.4mm` |
| VQFN | 64 | 9x9 | 0.5 | 7.15x7.15 | Y | . | Package_DFN_QFN | `VQFN-64-1EP_9x9mm_P0.5mm_EP7.15x7.15mm` |
| VQFN | 68 | 8x8 | 0.4 | 4.3x4.3 | . | . | Package_DFN_QFN | `VQFN-68-1EP_8x8mm_P0.4mm_EP4.3x4.3mm` |
| VQFN | 100 | 12x12 | 0.4 | 8x8 | Y | . | Package_DFN_QFN | `VQFN-100-1EP_12x12mm_P0.4mm_EP8x8mm` |
| WQFN | 14 | 2.5x2.5 | 0.5 | 1.45x1.45 | Y | . | Package_DFN_QFN | `WQFN-14-1EP_2.5x2.5mm_P0.5mm_EP1.45x1.45mm` |
| WQFN | 16 | 3x3 | 0.5 | 1.6x1.6 | Y | . | Package_DFN_QFN | `WQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm` |
| WQFN | 16 | 3x3 | 0.5 | 1.68x1.68 | Y | . | Package_DFN_QFN | `WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm` |
| WQFN | 16 | 3x3 | 0.5 | 1.75x1.75 | Y | . | Package_DFN_QFN | `WQFN-16-1EP_3x3mm_P0.5mm_EP1.75x1.75mm` |
| WQFN | 16 | 4x4 | 0.5 | 2.6x2.6 | Y | . | Package_DFN_QFN | `WQFN-16-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` |
| WQFN | 20 | 3x3 | 0.4 | 1.7x1.7 | Y | . | Package_DFN_QFN | `WQFN-20-1EP_3x3mm_P0.4mm_EP1.7x1.7mm` |
| WQFN | 20 | 2.5x4.5 | 0.5 | 1x2.9 | . | . | Package_DFN_QFN | `WQFN-20-1EP_2.5x4.5mm_P0.5mm_EP1x2.9mm` |
| WQFN | 20 | 4x4 | 0.5 | 2.7x2.7 | Y | . | Package_DFN_QFN | `WQFN-20-1EP_4x4mm_P0.5mm_EP2.7x2.7mm` |
| WQFN | 24 | 4x4 | 0.5 | 2.45x2.45 | Y | . | Package_DFN_QFN | `WQFN-24-1EP_4x4mm_P0.5mm_EP2.45x2.45mm` |
| WQFN | 24 | 4x4 | 0.5 | 2.6x2.6 | Y | . | Package_DFN_QFN | `WQFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` |
| WQFN | 28 | 4x4 | 0.4 | 2.7x2.7 | Y | . | Package_DFN_QFN | `WQFN-28-1EP_4x4mm_P0.4mm_EP2.7x2.7mm` |
| WQFN | 28 | 3.5x5.5 | 0.5 | 2.05x4.05 | Y | . | Package_DFN_QFN | `WQFN-28-1EP_3.5x5.5mm_P0.5mm_EP2.05x4.05mm` |
| WQFN | 32 | 5x5 | 0.5 | 3.1x3.1 | . | . | Package_DFN_QFN | `WQFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm` |
| WQFN | 38 | 5x7 | 0.5 | 2.7x4.7 | Y | . | Package_DFN_QFN | `WQFN-38-1EP_5x7mm_P0.5mm_EP2.7x4.7mm` |
| WQFN | 38 | 5x7 | 0.5 | 3.15x5.15 | Y | . | Package_DFN_QFN | `WQFN-38-1EP_5x7mm_P0.5mm_EP3.15x5.15mm` |
| WQFN | 38 | 5x7 | 0.5 | 3.65x5.65 | Y | . | Package_DFN_QFN | `WQFN-38-1EP_5x7mm_P0.5mm_EP3.65x5.65mm` |
| WQFN | 42 | 3.5x9 | 0.5 | 2.05x7.55 | Y | . | Package_DFN_QFN | `WQFN-42-1EP_3.5x9mm_P0.5mm_EP2.05x7.55mm` |
| TQFN | 16 | 3x3 | 0.5 | 1.23x1.23 | Y | . | Package_DFN_QFN | `TQFN-16-1EP_3x3mm_P0.5mm_EP1.23x1.23mm` |
| TQFN | 16 | 3x3 | 0.5 | 1.6x1.6 | . | . | Package_DFN_QFN | `TQFN-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm` |
| TQFN | 16 | 4x4 | 0.65 | 2.1x2.1 | Y | . | Package_DFN_QFN | `TQFN-16-1EP_4x4mm_P0.65mm_EP2.1x2.1mm` |
| TQFN | 16 | 5x5 | 0.8 | 2.29x2.29 | Y | . | Package_DFN_QFN | `TQFN-16-1EP_5x5mm_P0.8mm_EP2.29x2.29mm` |
| TQFN | 16 | 5x5 | 0.8 | 3.1x3.1 | Y | . | Package_DFN_QFN | `TQFN-16-1EP_5x5mm_P0.8mm_EP3.1x3.1mm` |
| TQFN | 20 | 4x4 | 0.5 | 2.1x2.1 | Y | . | Package_DFN_QFN | `TQFN-20-1EP_4x4mm_P0.5mm_EP2.1x2.1mm` |
| TQFN | 20 | 4x4 | 0.5 | 2.9x2.9 | Y | . | Package_DFN_QFN | `TQFN-20-1EP_4x4mm_P0.5mm_EP2.9x2.9mm` |
| TQFN | 20 | 5x5 | 0.65 | 3.1x3.1 | Y | . | Package_DFN_QFN | `TQFN-20-1EP_5x5mm_P0.65mm_EP3.1x3.1mm` |
| TQFN | 20 | 5x5 | 0.65 | 3.25x3.25 | Y | . | Package_DFN_QFN | `TQFN-20-1EP_5x5mm_P0.65mm_EP3.25x3.25mm` |
| TQFN | 24 | 4x4 | 0.5 | 2.1x2.1 | Y | . | Package_DFN_QFN | `TQFN-24-1EP_4x4mm_P0.5mm_EP2.1x2.1mm` |
| TQFN | 24 | 4x4 | 0.5 | 2.6x2.6 | Y | . | Package_DFN_QFN | `TQFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` |
| TQFN | 28 | 5x5 | 0.5 | 2.7x2.7 | Y | . | Package_DFN_QFN | `TQFN-28-1EP_5x5mm_P0.5mm_EP2.7x2.7mm` |
| TQFN | 28 | 5x5 | 0.5 | 3.25x3.25 | Y | . | Package_DFN_QFN | `TQFN-28-1EP_5x5mm_P0.5mm_EP3.25x3.25mm` |
| TQFN | 32 | 5x5 | 0.5 | 2.1x2.1 | Y | . | Package_DFN_QFN | `TQFN-32-1EP_5x5mm_P0.5mm_EP2.1x2.1mm` |
| TQFN | 32 | 5x5 | 0.5 | 3.1x3.1 | Y | . | Package_DFN_QFN | `TQFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm` |
| TQFN | 32 | 5x5 | 0.5 | 3.4x3.4 | Y | . | Package_DFN_QFN | `TQFN-32-1EP_5x5mm_P0.5mm_EP3.4x3.4mm` |
| TQFN | 40 | 5x5 | 0.4 | 3.5x3.5 | Y | . | Package_DFN_QFN | `TQFN-40-1EP_5x5mm_P0.4mm_EP3.5x3.5mm` |
| TQFN | 44 | 7x7 | 0.5 | 4.7x4.7 | Y | . | Package_DFN_QFN | `TQFN-44-1EP_7x7mm_P0.5mm_EP4.7x4.7mm` |
| TQFN | 48 | 7x7 | 0.5 | 5.1x5.1 | Y | . | Package_DFN_QFN | `TQFN-48-1EP_7x7mm_P0.5mm_EP5.1x5.1mm` |
| UQFN | 10 | 1.3x1.8 | 0.4 | no EP | . | . | Package_DFN_QFN | `UQFN-10_1.3x1.8mm_P0.4mm` |
| UQFN | 10 | 1.4x1.8 | 0.4 | no EP | . | . | Package_DFN_QFN | `UQFN-10_1.4x1.8mm_P0.4mm` |
| UQFN | 10 | 1.6x2.1 | 0.5 | no EP | . | . | Package_DFN_QFN | `UQFN-10_1.6x2.1mm_P0.5mm` |
| UQFN | 12 | 2x2 | 0.4 | 1.1x1.1 | . | . | Package_DFN_QFN | `UQFN-12-1EP_2x2mm_P0.4mm_EP1.1x1.1mm` |
| UQFN | 16 | 1.8x2.6 | 0.4 | no EP | . | . | Package_DFN_QFN | `UQFN-16_1.8x2.6mm_P0.4mm` |
| UQFN | 16 | 3x3 | 0.5 | 1.75x1.75 | . | . | Package_DFN_QFN | `UQFN-16-1EP_3x3mm_P0.5mm_EP1.75x1.75mm` |
| UQFN | 16 | 4x4 | 0.65 | 2.6x2.6 | Y | . | Package_DFN_QFN | `UQFN-16-1EP_4x4mm_P0.65mm_EP2.6x2.6mm` |
| UQFN | 16 | 4x4 | 0.65 | 2.7x2.7 | . | . | Package_DFN_QFN | `UQFN-16-1EP_4x4mm_P0.65mm_EP2.7x2.7mm` |
| UQFN | 20 | 3x3 | 0.4 | no EP | . | . | Package_DFN_QFN | `UQFN-20_3x3mm_P0.4mm` |
| UQFN | 20 | 3x3 | 0.4 | 1.7x1.7 | Y | . | Package_DFN_QFN | `UQFN-20-1EP_3x3mm_P0.4mm_EP1.7x1.7mm` |
| UQFN | 20 | 3x3 | 0.4 | 1.85x1.85 | Y | . | Package_DFN_QFN | `UQFN-20-1EP_3x3mm_P0.4mm_EP1.85x1.85mm` |
| UQFN | 20 | 4x4 | 0.5 | 2.8x2.8 | Y | . | Package_DFN_QFN | `UQFN-20-1EP_4x4mm_P0.5mm_EP2.8x2.8mm` |
| UQFN | 28 | 4x4 | 0.4 | 2.35x2.35 | Y | . | Package_DFN_QFN | `UQFN-28-1EP_4x4mm_P0.4mm_EP2.35x2.35mm` |
| UQFN | 32 | 5x5 | 0.5 | no EP | . | . | Package_DFN_QFN | `UQFN-32_5x5mm_P0.5mm` |
| UQFN | 40 | 5x5 | 0.4 | 3.8x3.8 | Y | . | Package_DFN_QFN | `UQFN-40-1EP_5x5mm_P0.4mm_EP3.8x3.8mm` |
| UQFN | 48 | 6x6 | 0.4 | 4.45x4.45 | Y | . | Package_DFN_QFN | `UQFN-48-1EP_6x6mm_P0.4mm_EP4.45x4.45mm` |
| UQFN | 48 | 6x6 | 0.4 | 4.62x4.62 | Y | . | Package_DFN_QFN | `UQFN-48-1EP_6x6mm_P0.4mm_EP4.62x4.62mm` |
| HVQFN | 16 | 3x3 | 0.5 | 1.5x1.5 | . | . | Package_DFN_QFN | `HVQFN-16-1EP_3x3mm_P0.5mm_EP1.5x1.5mm` |
| HVQFN | 24 | 4x4 | 0.5 | 2.1x2.1 | . | . | Package_DFN_QFN | `HVQFN-24-1EP_4x4mm_P0.5mm_EP2.1x2.1mm` |
| HVQFN | 24 | 4x4 | 0.5 | 2.5x2.5 | Y | . | Package_DFN_QFN | `HVQFN-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm` |
| HVQFN | 24 | 4x4 | 0.5 | 2.6x2.6 | Y | . | Package_DFN_QFN | `HVQFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` |
| HVQFN | 32 | 5x5 | 0.5 | 3.1x3.1 | Y | . | Package_DFN_QFN | `HVQFN-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm` |
| HVQFN | 36 | 6x6 | 0.5 | 3.9x3.9 | Y | . | Package_DFN_QFN | `HVQFN-36-1EP_6x6mm_P0.5mm_EP3.9x3.9mm` |
| HVQFN | 40 | 6x6 | 0.5 | 4.1x4.1 | Y | . | Package_DFN_QFN | `HVQFN-40-1EP_6x6mm_P0.5mm_EP4.1x4.1mm` |
| DHVQFN | 14 | 2.5x3 | 0.5 | 1x1.5 | Y | . | Package_DFN_QFN | `DHVQFN-14-1EP_2.5x3mm_P0.5mm_EP1x1.5mm` |
| DHVQFN | 16 | 2.5x3.5 | 0.5 | 1x2 | . | . | Package_DFN_QFN | `DHVQFN-16-1EP_2.5x3.5mm_P0.5mm_EP1x2mm` |
| DHVQFN | 20 | 2.5x4.5 | 0.5 | 1x3 | . | . | Package_DFN_QFN | `DHVQFN-20-1EP_2.5x4.5mm_P0.5mm_EP1x3mm` |
| DHWQFN | 14 | 2.5x3 | 0.5 | 1x1.5 | Y | . | Package_DFN_QFN | `DHWQFN-14-1EP_2.5x3mm_P0.5mm_EP1x1.5mm` |
| HXQFN | 16 | 3x3 | 0.5 | 1.85x1.85 | Y | . | Package_DFN_QFN | `HXQFN-16-1EP_3x3mm_P0.5mm_EP1.85x1.85mm` |
| LQFN | 10 | 2x2 | 0.5 | 0.7x0.7 | . | . | Package_DFN_QFN | `LQFN-10-1EP_2x2mm_P0.5mm_EP0.7x0.7mm` |
| LQFN | 12 | 2x2 | 0.5 | 0.7x0.7 | . | . | Package_DFN_QFN | `LQFN-12-1EP_2x2mm_P0.5mm_EP0.7x0.7mm` |
| LQFN | 16 | 3x3 | 0.5 | 1.7x1.7 | . | . | Package_DFN_QFN | `LQFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm` |
| MLF | 6 | 1.6x1.6 | 0.5 | 0.5x1.26 | . | . | Package_DFN_QFN | `MLF-6-1EP_1.6x1.6mm_P0.5mm_EP0.5x1.26mm` |
| MLF | 8 | 3x3 | 0.65 | 1.55x2.3 | Y | . | Package_DFN_QFN | `MLF-8-1EP_3x3mm_P0.65mm_EP1.55x2.3mm` |
| MLF | 20 | 4x4 | 0.5 | 2.6x2.6 | Y | . | Package_DFN_QFN | `MLF-20-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` |
| MLPQ | 16 | 4x4 | 0.65 | 2.8x2.8 | . | . | Package_DFN_QFN | `MLPQ-16-1EP_4x4mm_P0.65mm_EP2.8x2.8mm` |
| UFQFPN | 32 | 5x5 | 0.5 | 3.5x3.5 | Y | . | Package_DFN_QFN | `UFQFPN-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm` |
| DFN | 4 | 5x7 | 5.08 | no EP | . | . | Package_DFN_QFN | `DFN-4_5x7mm_P5.08mm` |
| DFN | 6 | 1.3x1.2 | 0.4 | no EP | . | . | Package_DFN_QFN | `DFN-6_1.3x1.2mm_P0.4mm` |
| DFN | 6 | 1.6x1.3 | 0.4 | no EP | . | . | Package_DFN_QFN | `DFN-6_1.6x1.3mm_P0.4mm` |
| DFN | 6 | 2x1.6 | 0.5 | 1.15x1.3 | . | . | Package_DFN_QFN | `DFN-6-1EP_2x1.6mm_P0.5mm_EP1.15x1.3mm` |
| DFN | 6 | 2x1.8 | 0.5 | 1.2x1.6 | . | . | Package_DFN_QFN | `DFN-6-1EP_2x1.8mm_P0.5mm_EP1.2x1.6mm` |
| DFN | 6 | 2x2 | 0.5 | 0.6x1.37 | . | . | Package_DFN_QFN | `DFN-6-1EP_2x2mm_P0.5mm_EP0.6x1.37mm` |
| DFN | 6 | 2x2 | 0.5 | 0.61x1.42 | . | . | Package_DFN_QFN | `DFN-6-1EP_2x2mm_P0.5mm_EP0.61x1.42mm` |
| DFN | 6 | 2x2 | 0.5 | 0.7x1.6 | . | . | Package_DFN_QFN | `DFN-6-1EP_2x2mm_P0.5mm_EP0.7x1.6mm` |
| DFN | 6 | 2x2 | 0.65 | 1x1.6 | . | . | Package_DFN_QFN | `DFN-6-1EP_2x2mm_P0.65mm_EP1x1.6mm` |
| DFN | 6 | 2x2 | 0.65 | 1.01x1.7 | . | . | Package_DFN_QFN | `DFN-6-1EP_2x2mm_P0.65mm_EP1.01x1.7mm` |
| DFN | 6 | 3x2 | 0.5 | 1.65x1.35 | . | . | Package_DFN_QFN | `DFN-6-1EP_3x2mm_P0.5mm_EP1.65x1.35mm` |
| DFN | 6 | 3x3 | 0.95 | 1.7x2.6 | . | . | Package_DFN_QFN | `DFN-6-1EP_3x3mm_P0.95mm_EP1.7x2.6mm` |
| DFN | 6 | 3x3 | 1 | 1.5x2.4 | . | . | Package_DFN_QFN | `DFN-6-1EP_3x3mm_P1mm_EP1.5x2.4mm` |
| DFN | 8 | 1.5x1.5 | 0.4 | 0.7x1.2 | . | . | Package_DFN_QFN | `DFN-8-1EP_1.5x1.5mm_P0.4mm_EP0.7x1.2mm` |
| DFN | 8 | 2x2 | 0.45 | 0.64x1.37 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.45mm_EP0.64x1.37mm` |
| DFN | 8 | 2x2 | 0.5 | no EP | . | . | Package_DFN_QFN | `DFN-8_2x2mm_P0.5mm` |
| DFN | 8 | 2x2 | 0.5 | 0.6x1.2 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.5mm_EP0.6x1.2mm` |
| DFN | 8 | 2x2 | 0.5 | 0.8x1.6 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.6mm` |
| DFN | 8 | 2x2 | 0.5 | 0.86x1.55 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.5mm_EP0.86x1.55mm` |
| DFN | 8 | 2x2 | 0.5 | 0.9x1.3 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.5mm_EP0.9x1.3mm` |
| DFN | 8 | 2x2 | 0.5 | 0.9x1.5 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.5mm_EP0.9x1.5mm` |
| DFN | 8 | 2x2 | 0.5 | 0.9x1.6 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.5mm_EP0.9x1.6mm` |
| DFN | 8 | 2x2 | 0.5 | 0.9x1.7 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.5mm_EP0.9x1.7mm` |
| DFN | 8 | 2x2 | 0.5 | 1.05x1.75 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x2mm_P0.5mm_EP1.05x1.75mm` |
| DFN | 8 | 2x3 | 0.5 | 0.61x2.2 | . | . | Package_DFN_QFN | `DFN-8-1EP_2x3mm_P0.5mm_EP0.61x2.2mm` |
| DFN | 8 | 3x2 | 0.45 | 1.66x1.36 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x2mm_P0.45mm_EP1.66x1.36mm` |
| DFN | 8 | 3x2 | 0.5 | 1.3x1.5 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x2mm_P0.5mm_EP1.3x1.5mm` |
| DFN | 8 | 3x2 | 0.5 | 1.36x1.46 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x2mm_P0.5mm_EP1.36x1.46mm` |
| DFN | 8 | 3x2 | 0.5 | 1.7x1.4 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x2mm_P0.5mm_EP1.7x1.4mm` |
| DFN | 8 | 3x2 | 0.5 | 1.7x1.6 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x2mm_P0.5mm_EP1.7x1.6mm` |
| DFN | 8 | 3x2 | 0.5 | 1.75x1.45 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x2mm_P0.5mm_EP1.75x1.45mm` |
| DFN | 8 | 3x3 | 0.5 | 1.65x2.38 | Y | . | Package_DFN_QFN | `DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm` |
| DFN | 8 | 3x3 | 0.5 | 1.66x2.38 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x3mm_P0.5mm_EP1.66x2.38mm` |
| DFN | 8 | 3x3 | 0.5 | 1.7x2.4 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x3mm_P0.5mm_EP1.7x2.4mm` |
| DFN | 8 | 3x3 | 0.65 | 1.2x2.15 | Y | . | Package_DFN_QFN | `DFN-8-1EP_3x3mm_P0.65mm_EP1.2x2.15mm` |
| DFN | 8 | 3x3 | 0.65 | 1.5x2.25 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x3mm_P0.65mm_EP1.5x2.25mm` |
| DFN | 8 | 3x3 | 0.65 | 1.55x2.4 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x3mm_P0.65mm_EP1.55x2.4mm` |
| DFN | 8 | 3x3 | 0.65 | 1.6x2.56 | Y | . | Package_DFN_QFN | `DFN-8-1EP_3x3mm_P0.65mm_EP1.6x2.56mm` |
| DFN | 8 | 3x3 | 0.65 | 1.7x2.05 | . | . | Package_DFN_QFN | `DFN-8-1EP_3x3mm_P0.65mm_EP1.7x2.05mm` |
| DFN | 8 | 4x4 | 0.8 | 2.3x3.24 | . | . | Package_DFN_QFN | `DFN-8-1EP_4x4mm_P0.8mm_EP2.3x3.24mm` |
| DFN | 8 | 4x4 | 0.8 | 2.39x2.21 | . | . | Package_DFN_QFN | `DFN-8-1EP_4x4mm_P0.8mm_EP2.39x2.21mm` |
| DFN | 8 | 4x4 | 0.8 | 2.5x3.6 | . | . | Package_DFN_QFN | `DFN-8-1EP_4x4mm_P0.8mm_EP2.5x3.6mm` |
| DFN | 8 | 6x5 | 1.27 | 2x2 | . | . | Package_DFN_QFN | `DFN-8-1EP_6x5mm_P1.27mm_EP2x2mm` |
| DFN | 8 | 6x5 | 1.27 | 4x4 | . | . | Package_DFN_QFN | `DFN-8-1EP_6x5mm_P1.27mm_EP4x4mm` |
| DFN | 10 | 2x2 | 0.4 | no EP | . | . | Package_DFN_QFN | `DFN-10_2x2mm_P0.4mm` |
| DFN | 10 | 2x3 | 0.5 | 0.64x2.4 | . | . | Package_DFN_QFN | `DFN-10-1EP_2x3mm_P0.5mm_EP0.64x2.4mm` |
| DFN | 10 | 2.6x2.6 | 0.5 | 1.3x2.2 | Y | . | Package_DFN_QFN | `DFN-10-1EP_2.6x2.6mm_P0.5mm_EP1.3x2.2mm` |
| DFN | 10 | 3x3 | 0.5 | 1.55x2.48 | . | . | Package_DFN_QFN | `DFN-10-1EP_3x3mm_P0.5mm_EP1.55x2.48mm` |
| DFN | 10 | 3x3 | 0.5 | 1.58x2.35 | Y | . | Package_DFN_QFN | `DFN-10-1EP_3x3mm_P0.5mm_EP1.58x2.35mm` |
| DFN | 10 | 3x3 | 0.5 | 1.646x3.1 | Y | . | Package_DFN_QFN | `DFN-10-1EP_3x3mm_P0.5mm_EP1.646x3.1mm` |
| DFN | 10 | 3x3 | 0.5 | 1.65x2.38 | Y | . | Package_DFN_QFN | `DFN-10-1EP_3x3mm_P0.5mm_EP1.65x2.38mm` |
| DFN | 10 | 3x3 | 0.5 | 1.7x2.5 | . | . | Package_DFN_QFN | `DFN-10-1EP_3x3mm_P0.5mm_EP1.7x2.5mm` |
| DFN | 10 | 3x3 | 0.5 | 1.75x2.7 | . | . | Package_DFN_QFN | `DFN-10-1EP_3x3mm_P0.5mm_EP1.75x2.7mm` |
| DFN | 12 | 2x3 | 0.45 | 0.64x2.4 | . | . | Package_DFN_QFN | `DFN-12-1EP_2x3mm_P0.45mm_EP0.64x2.4mm` |
| DFN | 12 | 3x3 | 0.45 | 1.65x2.38 | Y | . | Package_DFN_QFN | `DFN-12-1EP_3x3mm_P0.45mm_EP1.65x2.38mm` |
| DFN | 12 | 3x3 | 0.5 | 1.6x2.5 | Y | . | Package_DFN_QFN | `DFN-12-1EP_3x3mm_P0.5mm_EP1.6x2.5mm` |
| DFN | 12 | 3x3 | 0.5 | 2.05x2.86 | . | . | Package_DFN_QFN | `DFN-12-1EP_3x3mm_P0.5mm_EP2.05x2.86mm` |
| DFN | 12 | 3x4 | 0.5 | 1.7x3.3 | . | . | Package_DFN_QFN | `DFN-12-1EP_3x4mm_P0.5mm_EP1.7x3.3mm` |
| DFN | 12 | 4x4 | 0.5 | 2.66x3.38 | . | . | Package_DFN_QFN | `DFN-12-1EP_4x4mm_P0.5mm_EP2.66x3.38mm` |
| DFN | 12 | 4x4 | 0.65 | 2.64x3.54 | . | . | Package_DFN_QFN | `DFN-12-1EP_4x4mm_P0.65mm_EP2.64x3.54mm` |
| DFN | 14 | 1.35x3.5 | 0.5 | no EP | . | . | Package_DFN_QFN | `DFN-14_1.35x3.5mm_P0.5mm` |
| DFN | 14 | 3x3 | 0.4 | 1.78x2.35 | . | . | Package_DFN_QFN | `DFN-14-1EP_3x3mm_P0.4mm_EP1.78x2.35mm` |
| DFN | 14 | 3x4 | 0.5 | 1.7x3.3 | . | . | Package_DFN_QFN | `DFN-14-1EP_3x4mm_P0.5mm_EP1.7x3.3mm` |
| DFN | 14 | 3x4.5 | 0.65 | 1.65x4.25 | Y | . | Package_DFN_QFN | `DFN-14-1EP_3x4.5mm_P0.65mm_EP1.65x4.25mm` |
| DFN | 16 | 3x4 | 0.45 | 1.7x3.3 | . | . | Package_DFN_QFN | `DFN-16-1EP_3x4mm_P0.45mm_EP1.7x3.3mm` |
| DFN | 16 | 3x5 | 0.5 | 1.66x4.4 | . | . | Package_DFN_QFN | `DFN-16-1EP_3x5mm_P0.5mm_EP1.66x4.4mm` |
| DFN | 16 | 4x5 | 0.5 | 2.44x4.34 | . | . | Package_DFN_QFN | `DFN-16-1EP_4x5mm_P0.5mm_EP2.44x4.34mm` |
| DFN | 16 | 5x5 | 0.5 | 3.46x4 | . | . | Package_DFN_QFN | `DFN-16-1EP_5x5mm_P0.5mm_EP3.46x4mm` |
| DFN | 18 | 3x5 | 0.5 | 1.66x4.4 | . | . | Package_DFN_QFN | `DFN-18-1EP_3x5mm_P0.5mm_EP1.66x4.4mm` |
| DFN | 18 | 4x5 | 0.5 | 2.44x4.34 | . | . | Package_DFN_QFN | `DFN-18-1EP_4x5mm_P0.5mm_EP2.44x4.34mm` |
| DFN | 20 | 5x6 | 0.5 | 3.24x4.24 | . | . | Package_DFN_QFN | `DFN-20-1EP_5x6mm_P0.5mm_EP3.24x4.24mm` |
| DFN | 22 | 5x6 | 0.5 | 3.14x4.3 | . | . | Package_DFN_QFN | `DFN-22-1EP_5x6mm_P0.5mm_EP3.14x4.3mm` |
| DFN | 24 | 4x7 | 0.5 | 2.64x6.44 | . | . | Package_DFN_QFN | `DFN-24-1EP_4x7mm_P0.5mm_EP2.64x6.44mm` |
| DFN | 32 | 4x7 | 0.4 | 2.64x6.44 | . | . | Package_DFN_QFN | `DFN-32-1EP_4x7mm_P0.4mm_EP2.64x6.44mm` |
| DFN | 44 | 5x8.9 | 0.4 | 3.7x8.4 | . | . | Package_DFN_QFN | `DFN-44-1EP_5x8.9mm_P0.4mm_EP3.7x8.4mm` |
| TDFN | 6 | 1.2x1.2 | 0.4 | 0.3x0.94 | . | Y | Package_DFN_QFN | `TDFN-6-1EP_1.2x1.2mm_P0.4mm_EP0.3x0.94mm` |
| TDFN | 6 | 2.5x2.5 | 0.65 | 1.3x2 | Y | . | Package_DFN_QFN | `TDFN-6-1EP_2.5x2.5mm_P0.65mm_EP1.3x2mm` |
| TDFN | 8 | 1.4x1.6 | 0.4 | no EP | . | . | Package_DFN_QFN | `TDFN-8_1.4x1.6mm_P0.4mm` |
| TDFN | 8 | 2x2 | 0.5 | 0.8x1.2 | . | . | Package_DFN_QFN | `TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm` |
| TDFN | 8 | 3x2 | 0.5 | 1.3x1.4 | . | . | Package_DFN_QFN | `TDFN-8-1EP_3x2mm_P0.5mm_EP1.3x1.4mm` |
| TDFN | 8 | 3x2 | 0.5 | 1.4x1.4 | . | . | Package_DFN_QFN | `TDFN-8-1EP_3x2mm_P0.5mm_EP1.4x1.4mm` |
| TDFN | 8 | 3x2 | 0.5 | 1.80x1.65 | Y | . | Package_DFN_QFN | `TDFN-8-1EP_3x2mm_P0.5mm_EP1.80x1.65mm` |
| TDFN | 10 | 2x3 | 0.5 | 0.9x2 | Y | . | Package_DFN_QFN | `TDFN-10-1EP_2x3mm_P0.5mm_EP0.9x2mm` |
| TDFN | 12 | 2x3 | 0.5 | no EP | . | . | Package_DFN_QFN | `TDFN-12_2x3mm_P0.5mm` |
| TDFN | 12 | 3x3 | 0.4 | 1.7x2.45 | Y | . | Package_DFN_QFN | `TDFN-12-1EP_3x3mm_P0.4mm_EP1.7x2.45mm` |
| TDFN | 14 | 3x3 | 0.4 | 1.78x2.35 | Y | . | Package_DFN_QFN | `TDFN-14-1EP_3x3mm_P0.4mm_EP1.78x2.35mm` |
| WDFN | 6 | 4.0x2.6 | 0.65 | 2 EP, size omitted | . | . | Package_DFN_QFN | `WDFN-6-2EP_4.0x2.6mm_P0.65mm` |
| WDFN | 8 | 2x2 | 0.5 | 0.8x1.2 | . | . | Package_DFN_QFN | `WDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm` |
| WDFN | 8 | 3x2 | 0.5 | 1.3x1.4 | . | . | Package_DFN_QFN | `WDFN-8-1EP_3x2mm_P0.5mm_EP1.3x1.4mm` |
| WDFN | 8 | 4x3 | 0.65 | 2.4x1.8 | Y | . | Package_DFN_QFN | `WDFN-8-1EP_4x3mm_P0.65mm_EP2.4x1.8mm` |
| WDFN | 8 | 6x5 | 1.27 | 3.4x4 | . | . | Package_DFN_QFN | `WDFN-8-1EP_6x5mm_P1.27mm_EP3.4x4mm` |
| WDFN | 8 | 8x6 | 1.27 | 6x4.8 | Y | . | Package_DFN_QFN | `WDFN-8-1EP_8x6mm_P1.27mm_EP6x4.8mm` |
| WDFN | 10 | 3x3 | 0.5 | 1.8x2.5 | Y | . | Package_DFN_QFN | `WDFN-10-1EP_3x3mm_P0.5mm_EP1.8x2.5mm` |
| WDFN | 12 | 3x3 | 0.45 | 1.7x2.5 | . | . | Package_DFN_QFN | `WDFN-12-1EP_3x3mm_P0.45mm_EP1.7x2.5mm` |
| UDFN | 4 | 1x1 | 0.65 | 0.48x0.48 | . | . | Package_DFN_QFN | `UDFN-4-1EP_1x1mm_P0.65mm_EP0.48x0.48mm` |
| UDFN | 9 | 1.0x3.8 | 0.5 | no EP | . | . | Package_DFN_QFN | `UDFN-9_1.0x3.8mm_P0.5mm` |
| UDFN | 10 | 1.35x2.6 | 0.5 | no EP | . | . | Package_DFN_QFN | `UDFN-10_1.35x2.6mm_P0.5mm` |
| VDFN | 8 | 2x2 | 0.5 | 0.9x1.7 | . | . | Package_DFN_QFN | `VDFN-8-1EP_2x2mm_P0.5mm_EP0.9x1.7mm` |
| CDFN | 4 | 2x2.5 | 1.65 | no EP | . | . | Package_DFN_QFN | `CDFN-4_2x2.5mm_P1.65mm` |
| CDFN | 4 | 2.5x3.2 | 2.1 | no EP | . | . | Package_DFN_QFN | `CDFN-4_2.5x3.2mm_P2.1mm` |
| CDFN | 4 | 3.2x5 | 2.54 | no EP | . | . | Package_DFN_QFN | `CDFN-4_3.2x5mm_P2.54mm` |
| WFDFPN | 8 | 3x2 | 0.5 | 1.25x1.35 | . | . | Package_DFN_QFN | `WFDFPN-8-1EP_3x2mm_P0.5mm_EP1.25x1.35mm` |
| SON | 8 | 3x2 | 0.5 | 1.4x1.6 | . | . | Package_SON | `SON-8-1EP_3x2mm_P0.5mm_EP1.4x1.6mm` |
| WSON | 6 | 1.5x1.5 | 0.5 | no EP | . | . | Package_SON | `WSON-6_1.5x1.5mm_P0.5mm` |
| WSON | 6 | 2x2 | 0.65 | 1x1.6 | Y | . | Package_SON | `WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm` |
| WSON | 6 | 3x3 | 0.95 | 1 EP, size omitted | . | . | Package_SON | `WSON-6-1EP_3x3mm_P0.95mm` |
| WSON | 8 | 3x3 | 0.5 | 1.2x2 | Y | . | Package_SON | `WSON-8-1EP_3x3mm_P0.5mm_EP1.2x2mm` |
| WSON | 8 | 3x3 | 0.5 | 1.45x2.4 | Y | . | Package_SON | `WSON-8-1EP_3x3mm_P0.5mm_EP1.45x2.4mm` |
| WSON | 8 | 3x3 | 0.5 | 1.6x2.0 | . | . | Package_SON | `WSON-8-1EP_3x3mm_P0.5mm_EP1.6x2.0mm` |
| WSON | 8 | 4x4 | 0.8 | 1.98x3 | Y | . | Package_SON | `WSON-8-1EP_4x4mm_P0.8mm_EP1.98x3mm` |
| WSON | 8 | 4x4 | 0.8 | 2.2x3 | Y | . | Package_SON | `WSON-8-1EP_4x4mm_P0.8mm_EP2.2x3mm` |
| WSON | 8 | 4x4 | 0.8 | 2.6x3 | Y | . | Package_SON | `WSON-8-1EP_4x4mm_P0.8mm_EP2.6x3mm` |
| WSON | 8 | 6x5 | 1.27 | 3.4x4 | . | . | Package_SON | `WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4mm` |
| WSON | 8 | 6x5 | 1.27 | 3.4x4.3 | . | . | Package_SON | `WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm` |
| WSON | 8 | 8x6 | 1.27 | 3.4x4.3 | . | . | Package_SON | `WSON-8-1EP_8x6mm_P1.27mm_EP3.4x4.3mm` |
| WSON | 10 | 2x3 | 0.5 | 0.84x2.4 | Y | . | Package_SON | `WSON-10-1EP_2x3mm_P0.5mm_EP0.84x2.4mm` |
| WSON | 10 | 2.5x2.5 | 0.5 | 1.2x2 | Y | . | Package_SON | `WSON-10-1EP_2.5x2.5mm_P0.5mm_EP1.2x2mm` |
| WSON | 10 | 4x3 | 0.5 | 2.2x2 | . | . | Package_SON | `WSON-10-1EP_4x3mm_P0.5mm_EP2.2x2mm` |
| WSON | 10 | 4x4 | 0.8 | 2.6x3 | Y | . | Package_SON | `WSON-10-1EP_4x4mm_P0.8mm_EP2.6x3mm` |
| WSON | 12 | 3x3 | 0.5 | 1.5x2.5 | Y | . | Package_SON | `WSON-12-1EP_3x3mm_P0.5mm_EP1.5x2.5mm` |
| WSON | 12 | 4x4 | 0.5 | 2.6x3 | Y | . | Package_SON | `WSON-12-1EP_4x4mm_P0.5mm_EP2.6x3mm` |
| WSON | 14 | 4.0x4.0 | 0.5 | 2.6x2.6 | . | . | Package_SON | `WSON-14-1EP_4.0x4.0mm_P0.5mm_EP2.6x2.6mm` |
| VSON | 8 | 1.5x2 | 0.5 | no EP | . | . | Package_SON | `VSON-8_1.5x2mm_P0.5mm` |
| VSON | 8 | 3x3 | 0.65 | 1.6x2.4 | . | . | Package_SON | `VSON-8-1EP_3x3mm_P0.65mm_EP1.6x2.4mm` |
| VSON | 8 | 3x3 | 0.65 | 1.65x2.4 | Y | . | Package_SON | `VSON-8-1EP_3x3mm_P0.65mm_EP1.65x2.4mm` |
| VSON | 10 | 3x3 | 0.5 | 1.2x2 | Y | . | Package_SON | `VSON-10-1EP_3x3mm_P0.5mm_EP1.2x2mm` |
| VSON | 10 | 3x3 | 0.5 | 1.65x2.4 | Y | . | Package_SON | `VSON-10-1EP_3x3mm_P0.5mm_EP1.65x2.4mm` |
| VSON | 14 | 3x4.45 | 0.65 | 1.6x4.2 | Y | . | Package_SON | `VSON-14-1EP_3x4.45mm_P0.65mm_EP1.6x4.2mm` |
| USON | 10 | 2.5x1.0 | 0.5 | no EP | . | . | Package_SON | `USON-10_2.5x1.0mm_P0.5mm` |
| USON | 20 | 2x4 | 0.4 | no EP | . | . | Package_SON | `USON-20_2x4mm_P0.4mm` |
| HVSON | 8 | 3x3 | 0.65 | 1.6x2.4 | . | . | Package_SON | `HVSON-8-1EP_3x3mm_P0.65mm_EP1.6x2.4mm` |
| HVSON | 8 | 4x4 | 0.8 | 2.2x3.1 | . | . | Package_SON | `HVSON-8-1EP_4x4mm_P0.8mm_EP2.2x3.1mm` |
| HUSON | 3 | 2x2 | 1.3 | 1.1x1.6 | . | . | Package_SON | `HUSON-3-1EP_2x2mm_P1.3mm_EP1.1x1.6mm` |
| X2SON | 8 | 1.4x1 | 0.35 | no EP | . | . | Package_SON | `X2SON-8_1.4x1mm_P0.35mm` |
| LGA | 8 | 3x5 | 1.25 | no EP | . | . | Package_LGA | `LGA-8_3x5mm_P1.25mm` |
| LGA | 8 | 8x6 | 1.27 | no EP | . | . | Package_LGA | `LGA-8_8x6mm_P1.27mm` |
| LGA | 8 | 8x6.2 | 1.27 | no EP | . | . | Package_LGA | `LGA-8_8x6.2mm_P1.27mm` |
| LGA | 12 | 2x2 | 0.5 | no EP | . | . | Package_LGA | `LGA-12_2x2mm_P0.5mm` |
| LGA | 16 | 3x3 | 0.5 | no EP | . | . | Package_LGA | `LGA-16_3x3mm_P0.5mm` |
| LGA | 28 | 5.2x3.8 | 0.5 | no EP | . | . | Package_LGA | `LGA-28_5.2x3.8mm_P0.5mm` |
| VLGA | 4 | 2x2.5 | 1.65 | no EP | . | . | Package_LGA | `VLGA-4_2x2.5mm_P1.65mm` |

### Highest-traffic geometries at a glance

Where several EP sizes share one (pins, body, pitch), the geometry is a de-facto JEDEC standard and the EP is the only thing you need to match from the datasheet. Counts of distinct EP variants in stock:

| Geometry | EP variants |
|---|---:|
| `QFN-64-1EP_9x9mm_P0.5mm_EP…` | 16 |
| `DFN-8-1EP_2x2mm_P0.5mm_EP…` (+ 1 no-EP) | 8 + 1 |
| `QFN-24-1EP_4x4mm_P0.5mm_EP…` | 8 |
| `QFN-48-1EP_7x7mm_P0.5mm_EP…` | 7 |
| `QFN-32-1EP_5x5mm_P0.5mm_EP…`, `DFN-10-1EP_3x3mm_P0.5mm_EP…` | 6 each |
| `QFN-16-1EP_3x3mm_P0.5mm_EP…`, `QFN-28-1EP_5x5mm_P0.5mm_EP…`, `QFN-48-1EP_6x6mm_P0.4mm_EP…`, `QFN-56-1EP_8x8mm_P0.5mm_EP…`, `VQFN-16-1EP_3x3mm_P0.5mm_EP…`, `DFN-8-1EP_3x2mm_P0.5mm_EP…`, `DFN-8-1EP_3x3mm_P0.65mm_EP…` | 5 each |

## How to name a new part in this family

## Naming a new QFN/DFN/SON from a datasheet

**Do the lookup first.** Search Table 2 for `<pins>`, `<body>`, `<pitch>`. If a row exists with your exact EP, use that name — do not author a new footprint. 377 canonical names cover most of what you will meet.

### Step 1 — Read five numbers off the package mechanical drawing

| Datasheet item | Where it appears | Becomes |
|---|---|---|
| Package name as the vendor spells it (`VQFN`, `WSON`, `HVQFN`, `LFCSP`, `TQFN`, …) | Title of the mechanical drawing / ordering-info package column | `<FAMILY>` |
| Number of leads (perimeter terminals) | Drawing title ("48-lead"), or count the numbered terminals in the bottom view | `<PINS>` |
| Body length **and** width, nominal | The `D` / `E` (or `A`/`B`) dimension table rows, "NOM" column | `<BX>x<BY>mm` |
| Terminal pitch, `e` | Dimension table | `P<PITCH>mm` |
| Exposed-pad size, nominal — the two `D2`/`E2` (sometimes `D1`/`E1`, `L2`/`W2`) rows | Dimension table, "NOM" column, or the *recommended land pattern* drawing | `EP<EX>x<EY>mm` |

### Step 2 — Fix the orientation before you write the numbers down

Orient the **bottom-view/land-pattern drawing so that pin 1 is at the top-left and numbering runs counter-clockwise** — this is exactly how KiCad draws these footprints (verified: in `WSON-8-1EP_3x3mm_P0.5mm_EP1.2x2mm`, pad 1 is at x = −1.3875, y = −0.75 and pad 2 at y = −0.25, i.e. numbering descends the left column first).

- The **first** body number is the **horizontal (X)** dimension — the span across the left and right lead columns.
- The **second** is the **vertical (Y)** dimension — the span across the top and bottom rows.
- The EP pair uses the same X-then-Y order. (Verified: `QFN-28-1EP_3x6mm_P0.5mm_EP1.7x4.75mm` — X = 3 mm across the lead columns, Y = 6 mm; EP is 1.7 wide × 4.75 tall.)

For DFN/SON (leads on two sides only), X is still the dimension across the two lead rows: `DFN-8-1EP_3x2mm_P0.5mm_EP1.7x1.6mm` is 3 mm across the lead rows and 2 mm along them.

### Step 3 — Assemble, in this exact order

```
<FAMILY>-<PINS>[-<n>EP]_<BX>x<BY>mm_P<PITCH>mm[_EP<EX>x<EY>mm]
```

- No exposed pad → omit both `-<n>EP` and `_EP…mm`: `QFN-28_4x4mm_P0.5mm`, `UQFN-32_5x5mm_P0.5mm`, `DFN-10_2x2mm_P0.4mm`.
- One exposed pad → `-1EP` **and** the `_EP…mm` field. Both, always. `-1EP` without `_EP…` is a defect (only 2 legacy files do it).
- Two or more thermal pads → `-2EP`, `-4EP`, … and give the size of a **single** pad in `_EP…mm` if they are all identical: `UDC-QFN-20-4EP_3x4mm_P0.5mm_EP0.41x0.25mm`, `Winbond_USON-8-2EP_3x4mm_P0.8mm_EP0.2x0.8mm`.

### Step 4 — Format the numbers

1. Strip trailing zeros: `4x4mm`, not `4.0x4.0mm`. `P1mm`, not `P1.0mm`. `EP2x2mm`, not `EP2.00x2.00mm`.
2. Keep every significant digit the datasheet gives — up to 3 decimals is normal (`EP1.646x3.1mm`, `EP1.675x1.675mm`).
3. **Never round to "tidy" a name.** A 0.05 mm difference in EP is a different footprint, not the same one: `QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm` and `…_EP2.75x2.75mm` are separate stock files.
4. Lowercase `x` as the separator, single `mm` after the pair, `_` between fields.

### Step 5 — Pick the family prefix

Use the vendor's own prefix if it is one of the 68 in Table 1. If the datasheet uses a prefix that has **0 generic uses** in Table 1 (`PVQFN`, `PWSON`, `AQFN`, `DRQFN`, `TISON`, …), that spelling is a manufacturer mechanical code — scope it: `<Mfr>_<CODE>_<GENERIC-FAMILY>-…`, e.g. `Texas_RGZ0048A_VQFN-48-1EP_7x7mm_P0.5mm_EP5.15x5.15mm`. If the prefix is not in Table 1 at all, fall back to the plain generic (`QFN`, `DFN`, `SON`, `LGA`) and put the vendor spelling in the footprint's `descr`/`tags`, mirroring how the stock library writes `(descr "QFN, 48 Pin (<datasheet URL>)")` and `(tags "QFN NoLead")`.

### If the package is genuinely absent from KiCad stock

1. **Re-check with a substring search before concluding it is absent.** Search on the *EP token alone* (`_EP2.7x2.7mm`) and on the *geometry alone* (`-24-1EP_4x4mm_P0.5mm`) across `Package_DFN_QFN.pretty`, `Package_SON.pretty`, `Package_LGA.pretty` **and `Package_CSP.pretty`** — the same land pattern may already be there under `LFCSP` (68 files), or under a manufacturer prefix (`Texas_RGE0024H_VQFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm` is the *same* land pattern as `QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm`).
2. **Do not adopt a near-miss.** Different EP size = different footprint. A footprint with the right pins/body/pitch but the wrong EP will pass DRC and still fail thermally or bridge under the part.
3. **Author it into the 7Sigma namespace, not a KiCad library.** Name it with this grammar verbatim so it sorts alongside stock: `7Sigma:QFN-24-1EP_4x4mm_P0.5mm_EP2.72x2.72mm`. Keep the prefix generic unless the vendor land pattern is genuinely non-JEDEC.
4. **Nearest stock sibling is your geometry template.** Copy the row from Table 2 with the same pins/body/pitch and edit only the EP pad size, EP token and `descr`. The lead-pad size, courtyard and silk are IPC-derived and already correct for that pitch and body.
5. **Ship the plain footprint and, if the datasheet's land pattern shows vias, a `_ThermalVias` sibling too** — matching the stock convention (239 of 377 canonical names have one).
6. **Put the datasheet URL in `descr`.** Every stock file does: `(descr "QFN, 48 Pin (http://…/QFN_48_05-08-1704.pdf)")`. That URL is the audit trail for the EP number you chose.
7. Follow the 7Sigma footprint conventions skill for pad/silk/fab/courtyard style and the 0.1 mm pad grid, and submit it as a draft proposal — never publish directly.

## Pitfalls

## Traps

### 1. `-<n>EP` does NOT change the pin count
`QFN-48-1EP` has 48 leads and 49 pads. The EP is pad 49. Verified: highest pad number = `<PINS>` + `n` in 810 files. Symbols must therefore carry an extra pin for the EP or the netlist will not map.

### 2. `-1EP` in the name but no `_EP…mm` field
Two files do this, both legitimately — the EP is not a single rectangle. `WSON-6-1EP_3x3mm_P0.95mm` has four separate `pad "7" smd rect` entities making up a segmented EP, so no single `w×h` exists. `WDFN-6-2EP_4.0x2.6mm_P0.65mm` likewise. **Do not "fix" these by inventing an EP token, and do not assume "no `_EP`" means "no exposed pad" — check `-<n>EP` first.**

### 3. Conversely: an EP pad with nothing in the name at all
`WSON-16_3.3x1.35_P0.4mm` has 17 distinct pad numbers (pad 17 is an EP) but neither `-1EP` nor `_EP…`. Same defect in `Panasonic_HSON-8_8x8mm_P2.00mm` (9 pads) and `Texas_X2SON-4_1x1mm_P0.65mm` (5 pads). **Never infer pad count from the filename alone for these — open the file.**

### 4. `_ThermalVias` is not always geometrically identical to its plain sibling
It normally adds only vias and re-splits paste. But in **5 of 239** pairs the EP copper is different too:

| Base EP copper | `_ThermalVias` EP copper | Base name |
|---|---|---|
| 7.5×7.5 | **8.5×8.5** | `QFN-44-1EP_9x9mm_P0.65mm_EP7.5x7.5mm` |
| 1.8×1.8 | **2.8×2.8** | `SiliconLabs_QFN-20-1EP_3x3mm_P0.5mm_EP1.8x1.8mm` |
| 1.65×2.4 | **2.3×2.8** | `Texas_DSC0010J` |
| 1.65×2.4 | **2.3×2.8** | `Texas_S-PVSON-N10` |
| 1.7×2.15 | **2.3×2.3** | `Texas_S-PWSON-N10` |

So the `_EP…mm` token in a `_ThermalVias` name can disagree with the actual copper. Check the file if the EP is load-bearing.

### 5. `_ThermalVia` (singular) exists — one file only
`Texas_B3QFN-14-1EP_5x5.5mm_P0.65mm_ThermalVia`. A search for `_ThermalVias` misses it. 321 filenames contain `ThermalVias`; 319 *end* with it (the other two are `…_ThermalVias_TopTented` and `Texas_WQFN-MR-100_ThermalVias_3x3-DapStencil`).

### 6. The `Mask` token has no `mm` and no leading `_EP`-style symmetry
It is `_<k>xMask<MX>x<MY>` — count first, no unit: `NXP_LQFN-48-1EP_7x7mm_P0.5mm_EP3.5x3.5mm_16xMask0.45x0.45`. Writing `_Mask0.45x0.45mm` or `_16xMask0.45x0.45mm` would not match anything in stock. Only 2 files use it.

### 7. Family prefixes that look interchangeable but are separate footprints
`QFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm` and `VQFN-16-1EP_3x3mm_P0.5mm_EP1.45x1.45mm` both exist. Same land pattern, different body **height** class (V = 0.9 mm, W = 0.8 mm, U = 0.5–0.6 mm, T = thin, X2 = extra-extra-small, H = heatsink, L = low-profile, D = dual-row). The height is **not** in the name — only the prefix encodes it. Pick the prefix the datasheet uses, or the 3D model and assembly height check will be wrong.

Same trap across vendors for one physical package:
- `WSON-8-1EP_3x3mm_P0.5mm_EP1.45x2.4mm` (TI spelling) vs `VSON`/`HVSON`/`SON` variants at 3×3.
- `HVSON-8-1EP_3x3mm_P0.65mm_EP1.6x2.4mm` and `VSON-8-1EP_3x3mm_P0.65mm_EP1.6x2.4mm` are *byte-for-byte identical geometry parameters* under two prefixes.
- `LFCSP-16-1EP_4x4mm_P0.65mm_EP2.6x2.6mm` (in `Package_CSP.pretty`) vs `UQFN-16-1EP_4x4mm_P0.65mm_EP2.6x2.6mm` (in `Package_DFN_QFN.pretty`) — **searching only the DFN_QFN/SON/LGA libraries will make you think ADI parts are missing.**

### 8. Near-identical names differing by 0.01–0.05 mm
All of these are separate stock files, and picking the wrong one is silent:
- `DFN-8-1EP_3x3mm_P0.5mm_EP1.65x2.38mm` vs `…_EP1.66x2.38mm`
- `QFN-24-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` / `2.65x2.65` / `2.7x2.6` / `2.7x2.7` / `2.75x2.75` / `2.8x2.8`
- `QFN-64-1EP_9x9mm_P0.5mm_EP7.25x7.25mm` / `7.3x7.3` / `7.35x7.35` / `7.5x7.5` / `7.65x7.65`
- `WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4mm` vs `…_EP3.4x4.3mm`
- Asymmetric EPs where the order matters: `QFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.6mm` (X≠Y) — transposing gives a footprint that does not exist.

### 9. Trailing-zero inconsistency in legacy files
10 files break the strip-trailing-zeros rule and you must type them verbatim: `WSON-14-1EP_4.0x4.0mm_P0.5mm_EP2.6x2.6mm`, `WSON-8-1EP_3x3mm_P0.5mm_EP1.6x2.0mm`, `TDFN-8-1EP_3x2mm_P0.5mm_EP1.80x1.65mm`, `WDFN-6-2EP_4.0x2.6mm_P0.65mm`, `UDFN-9_1.0x3.8mm_P0.5mm`, `USON-10_2.5x1.0mm_P0.5mm`, `OnSemi_XDFN4-1EP_1.0x1.0mm_EP0.52x0.52mm`, `Fairchild_MicroPak-6_1.0x1.45mm_P0.5mm`, `Fairchild_MicroPak2-6_1.0x1.0mm_P0.35mm`, plus `Panasonic_HSON-8_8x8mm_P2.00mm`. **Autocompleting `4.0x4.0` to `4x4` produces a name that does not exist.** New footprints should still strip the zeros.

### 10. Missing `mm` suffixes
`WSON-12-1EP_3x2mm_P0.5mm_EP1x2.65` (EP has no `mm`), `WDFN-8-1EP_2x2.2mm_P0.5mm_EP0.80x0.54` (no `mm`), `WSON-16_3.3x1.35_P0.4mm` (body has no `mm`), `VSONP-8-1EP_5x6_P1.27mm` (body has no `mm`), `Texas_REF0038A_WQFN-38-2EP_6x4mm_P0.4` (pitch has no `mm`). Verbatim or nothing.

### 11. The second integer in `<FAMILY>-<A>-<B>-<n>EP` is not consistently ordered
Usually A = full outline lead positions, B = populated:
- `Microsemi_QFN-40-32-2EP_6x8mm_P0.5mm` — `descr` says "40-Lead (32-Lead Populated)"; 34 distinct pads = 32 leads + 2 EP. ✓
- `Texas_RNX0012C_VQFN-14-11-1EP_2x3mm_P0.5mm_EP0.25x1.825mm` — `descr` says "11 Pin"; 12 pads = 11 + 1 EP. ✓
- `Infineon_MLPQ-16-14-1EP_4x4mm_P0.5mm` — 15 pads = 14 + 1 EP. ✓

But `Analog_QFN-28-36-2EP_5x6mm_P0.5mm` **reverses it**: `descr` says "28 Pin", 30 distinct pad numbers (28 leads + 2 EP) spread over numbers 1–38 — so 28 is populated and 36 is the outline. And `Infineon_PQFN-44-31-5EP_7x7mm_P0.5mm` matches neither number (27 distinct pads). **Never derive pin count from a two-integer name — read the `descr` and count the pads.**

### 12. Hand-authored files that abandon the grammar entirely
Never pattern-match your way to these; look them up: `Texas_RDX0007A_QFN-FCMOD-7-3.3x4mm-P0.5mm_4EP` (hyphens where underscores belong, `4EP` at the end), `PQFN-8-EP_6x5mm_P1.27mm_Generic` (`-EP` with no count), `DFN-S-8-1EP_6x5mm_P1.27mm` (an `S` variant letter inside the head), `Texas_WQFN-MR-100_ThermalVias_3x3-DapStencil`, `Diodes_UDFN2020-6_Type-F`, `Diodes_UDFN3810-9_TYPE_B` (both a metric size code *and* an inconsistently-cased type suffix), `ST_UQFN-6L_1.5x1.7mm_P0.5mm` and `LGA-24L_3x3.5mm_P0.43mm` (an `L` suffix on the pin count), `Infineon_PG-TDSON-8_6.15x5.15mm` (no pitch field), `VSON-8_3.3x3.3mm_P0.65mm_NexFET` (trade-name qualifier), `Vishay_PowerPAK_MLP55-27L_R_ThermalVias`, `Texas_S-PVQFN-N14`, `Texas_RGY_R-PVQFN-N16_EP2.05x2.55mm` (JEDEC `-N<pins>` form instead of `-<pins>`). 46 of the 930 files have no parsable `<FAMILY>-<pincount>` at all.

### 13. Metric size codes are not body dimensions
`Diodes_DFN1006-3`, `ROHM_DFN0604-3`, `Diodes_UDFN2020-6_Type-F`, `Diodes_UDFN3810-9_TYPE_B`, `ROHM_VML0806`. `DFN1006` is 1.0 × 0.6 mm and the `-3` is the pin count — the digits look like a pin count but are a size in 0.1 mm units, exactly the imperial/metric-style confusion that bites on chip resistors. Never write a new footprint this way.

### 14. Imperial-derived pitches hide in plain sight
`P1.27mm` (18 files) is 0.050 in and `P2.54mm` / `P5.08mm` are 0.1 in / 0.2 in — these are the 6×5 and 8×6 power DFN/SON body styles. They are written in mm and must stay in mm. There is no imperial token anywhere in this family; if a datasheet gives inches, convert and ask before committing the rounded value.

### 15. LGA has extra mandatory fields that QFN does not
An LGA pad array is not implied by the pin count. `LGA-16_3x3mm_P0.5mm` and `LGA-16_3x3mm_P0.5mm_LayoutBorder3x5y` **both exist** with the same pins/body/pitch and different pad arrangements. Bosch parts additionally need `_ClockwisePinNumbering`, and NXP LGA-8 needs `_H1.1mm` vs `_H1.2mm` to disambiguate. Omitting `_LayoutBorder…` silently selects the wrong arrangement.

### 16. `_PullBack` changes the land pattern, not just the silk
Pads move inboard and get shorter (verified: 0.825×0.3 at x = −1.9625 becomes 0.45×0.4 at x = −1.775 on `QFN-16-1EP_4x4mm_P0.65mm_EP2.7x2.7mm`). Only 4 base names use it. Using the non-`PullBack` variant on a pull-back package puts copper outside the terminals; using `PullBack` on a normal package starves the fillet. Note the flag order is `_PullBack_ThermalVias`, never the reverse.


---


# BGA / CSP / LGA grid-array packages (geometric naming) and RF / GNSS / cellular / compute MODULES (product-name naming)

**Backed by:** 598 stock footprint files back these tables, counted with `ls *.kicad_mod | wc -l` in KiCad 10.0 (`/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints`), and every one of the 598 names was then re-tested individually with `test -f "<lib>.pretty/<name>.kicad_mod"` (598 verified, 0 missing).

Grid-array side — 454 files:
- `Package_BGA.pretty` — 234
- `Package_CSP.pretty` — 179
- `Package_LGA.pretty` — 41

Module side — 144 files:
- `RF_Module.pretty` — 69
- `RF_GPS.pretty` — 16
- `RF_GSM.pretty` — 11
- `RF_WiFi.pretty` — 1
- `Module.pretty` — 47

No basename is duplicated across the eight libraries (checked with `sort | uniq -d`), so 234+179+41+69+16+11+1+47 = 598 distinct names.

Supporting censuses (all machine-counted, not estimated):
- 190/234 BGA names carry a `_Layout…` token; 186 carry the plain `_LayoutCxR` form.
- 17/234 BGA + 1/179 CSP names carry the `_Ball<d>mm_Pad<d>mm_NSMD` trio. No file anywhere carries `NSMD` without that trio.
- 10/41 LGA names use `_LayoutBorderAxBy`; only 2/41 use `_LayoutCxR`; 10/41 carry an `…EP` count.
- Package_CSP is two unrelated families: 68 `LFCSP*` files (perimeter leadless, QFN-style, not a grid array) and 104 `WLCSP*` files, plus 7 others (`OnSemi_ODCSP*`, `pSemi_CSP-16*`, `Xilinx_CSG48*`).
- 40/179 CSP names are ST legacy `_Die###` names with no geometry at all.
- Of 144 module files, 138 are the bare product name; 6 carry any geometric or package token.

## Grammar

## A. Grid-array grammar (Package_BGA / Package_CSP / Package_LGA)

Canonical token order. Only `FAMILY-n` and the pitch are near-universal; everything else is optional, but tokens that appear must appear in this order:

```
[Vendor_][VendorPkgCode_]FAMILY-n[-mEP]_<X>x<Y>mm[_Layout<C>x<R> | _Layout<A>x<B>x<C> | _LayoutBorder<A>x<B>y]_P<pitch>mm[_Ball<d>mm_Pad<d>mm_NSMD][_EP<x>x<y>mm][_H<h>mm][_Stagger][_Offcenter][_ThermalVias][_ClockwisePinNumbering][_SMD|_HandSolder|_ManualAssembly][_LevelB|_LevelC]
```

### A1. `FAMILY-n` — family prefix and ball/land count
`n` is the **electrical ball/land count from the datasheet** (populated balls), never the grid extent.

Family vocabulary actually in stock (verbatim from filenames): `BGA`, `FBGA`, `TFBGA`, `LFBGA`, `UFBGA`, `VFBGA`, `XFBGA`, `XBGA`, `UCBGA` (and the lowercase variant `ucBGA`), `csBGA`, `caBGA`, `MAPBGA`, `FCPBGA`, `FB-BGA`, `DSBGA`, `WLP`, `WLCSP`, `CSP`, `LFCSP`, `ODCSP`, `LGA`, `HLGA`, `OLGA`, `VLGA`, `CCLGA`, `USON`, `TSNP`, `MicroSiP`, `uTFBGA`.

Verbatim:
- `BGA-1023_33.0x33.0mm_Layout32x32_P1.0mm`
- `TFBGA-644_19x19mm_Layout28x28_P0.65mm`
- `csBGA-64_5x5mm_Layout8x8_P0.5mm`
- `ucBGA-64_4x4mm_Layout8x8_P0.4mm` and `UCBGA-81_4x4mm_Layout9x9_P0.4mm` (case differs between files)
- `FB-BGA-484_23.0x23.0mm_Layout22x22_P1.0mm`
- `ST_uTFBGA-36_3.6x3.6mm_Layout6x6_P0.5mm`

### A2. Vendor prefix and vendor package code
An optional leading vendor token, and optionally the vendor's own package code before the generic family:
- `Alliance_TFBGA-54_8x8mm_Layout9x9_P0.8mm`
- `Micron_FBGA-96_9x14mm_Layout9x16_P0.8mm`
- `Microchip_FCVG484_BGA-484_19x19mm_Layout22x22_P0.8mm` (vendor code `FCVG484` + generic `BGA-484`)
- `NXP_SOT1982-1_VFBGA-98_7x7mm_Layout13x13_P0.5mm` (SOT code + generic)
- `Texas_YFP0020_DSBGA-20_1.588x1.988mm_Layout4x5_P0.4mm`
- `Rohm_MLGA010V020A_LGA-10_2x2mm_P0.45mm_LayoutBorder2x3y`
- `Lattice_iCE40_csBGA-132_8x8mm_Layout14x14_P0.5mm` (vendor + product family + generic)
- `Texas_MicroStar_Junior_BGA-113_7x7mm_Layout12x12_P0.5mm`
- `Texas_PicoStar_BGA-4_0.758x0.758mm_Layout2x2_P0.4mm`
- `DiodesInc_GEA20_WLCSP-20_1.7x2.1mm_Layout4x5_P0.4mm`

Vendor-code-only (no geometry at all) — the whole Xilinx set, 43 files: `Xilinx_FFG1156`, `Xilinx_CLG484_CLG485`, `Xilinx_FFG1926_FFG1927_FFG1928_FFG1930`, `Xilinx_CPG236`, `Xilinx_RF1930`. Geometry lives only in `(descr …)`, e.g. `Xilinx_FFG1156` → "35x35mm, 1156 Ball, 34x34 Layout, 1mm Pitch".

### A3. Body size `<X>x<Y>mm`
Package body, X (width) then Y (height), in mm. Both `11.0x11.0mm` and `11x11mm` styles are in stock — they are not normalised:
- `BGA-324_15.0x15.0mm_Layout18x18_P0.8mm_Ball0.5mm_Pad0.4mm_NSMD`
- `BGA-324_15x15mm_Layout18x18_P0.8mm`

Three numbers = X × Y × body height (exactly one file): `WLCSP-8_1.58x1.63x0.35mm_Layout3x5_P0.35x0.4mm_Ball0.25mm_Pad0.25mm_NSMD`.
Body height can instead be its own `_H<h>mm` token: `NXP_LGA-8_3x5mm_P1.25mm_H1.1mm`, `NXP_LGA-8_3x5mm_P1.25mm_H1.2mm`, `ST_CCLGA-7L_2.8x2.8mm_P1.15mm_H1.95mm`.
One file marks the body with a `B` prefix: `WLCSP-16_4x4_B2.17x2.32mm_P0.5mm`.

### A4. `_Layout<C>x<R>` — the grid extent (NOT the ball count)
`C` = number of grid **columns**, counted along the body's **X** dimension; `R` = number of **rows**, along Y. Confirmed from pad coordinates in `Analog_BGA-28_4x6.25mm_Layout4x7_P0.8mm`: 4 distinct X values (-1.2, -0.4, 0.4, 1.2) and 7 distinct Y values.

`n ≤ C×R` always. Machine-checked across all 186 BGA and 65 CSP files that carry `_LayoutCxR`: 101 BGA + 37 CSP have exactly `n = C×R` (fully populated), 85 BGA + 28 CSP have `n < C×R` (depopulated), and **zero** files have `n > C×R`.
- Fully populated: `BGA-1156_35.0x35.0mm_Layout34x34_P1.0mm` (34×34 = 1156)
- Depopulated: `BGA-63_9x11mm_Layout10x12_P0.8mm` (63 balls in a 10×12 = 120 grid)
- Depopulated: `Alliance_TFBGA-36_6x8mm_Layout6x8_P0.75mm`
- Depopulated: `BGA-24_8x8mm_Layout5x5_P1.0mm`

The grid extent follows the datasheet's row/column *labelling*, which can exceed the count of occupied coordinate lines. `BGA-200_10x14.5mm_Layout12x22_P0.8x0.65mm` says 12×22 but has only 10 distinct X and 20 distinct Y coordinates — two columns (6, 7) and two rows (L, M) are entirely empty and still count toward the label range.

### A5. Collapsed / banded grids `_Layout<A>x<B>x<C>` — two different conventions in stock
Six stock files use a three-number Layout, and the arithmetic differs by vendor. Read the pad names in the file; do not assume.
- **Product form** (memory-style split arrays): A banks × B columns per bank × C rows, product = ball count.
  - `BGA-90_8.0x13.0mm_Layout2x3x15_P0.8mm` → 2×3×15 = 90. Pads confirm: rows A…R (15), columns 1,2,3 and 7,8,9 (two banks of 3), centre columns 4–6 empty.
  - `BGA-96_9.0x13.0mm_Layout2x3x16_P0.8mm` → 2×3×16 = 96
  - `FBGA-78_7.5x11mm_Layout2x3x13_P0.8mm` → 2×3×13 = 78
- **Sum form** (TI DSBGA per-row bump counts): A + B + C = ball count.
  - `Texas_DSBGA-5_0.822x1.116mm_Layout2x1x2_P0.4mm` → 2+1+2 = 5. Pads confirm: A1, A3 (row 1), B2 (row 2), C1, C3 (row 3).

### A6. `_LayoutBorder<A>x<B>y` — perimeter-ring LGAs (10 LGA files)
`A` = lands per **horizontal** (top and bottom) row; `B` = lands per **vertical** (left and right) column. Total = 2A + 2B, which holds for all 10 stock files. Confirmed from coordinates in `LGA-14_3x5mm_P0.8mm_LayoutBorder1x6y`: 3 distinct X (-1.0, 0.0, 1.0 — one land centred top and bottom, plus the two side columns) and 6 distinct Y.
- `LGA-16_3x3mm_P0.5mm_LayoutBorder3x5y` (2·3 + 2·5 = 16)
- `LGA-16_4x4mm_P0.65mm_LayoutBorder4x4y` (16)
- `Bosch_LGA-16_4.5x3mm_P0.5mm_LayoutBorder7x1y_ClockwisePinNumbering` (2·7 + 2·1 = 16)
- `Kionix_LGA-12_2x2mm_P0.5mm_LayoutBorder2x4y` (12)
- `ST_HLGA-10_2x2mm_P0.5mm_LayoutBorder3x2y` (10)
- `LGA-14_2x2mm_P0.35mm_LayoutBorder3x4y` (14)

### A7. Pitch `_P…mm` — five distinct forms
1. Single isotropic pitch: `_P0.5mm`. Values in stock: 0.25, 0.35, 0.4, 0.43, 0.45, 0.5, 0.55, 0.6, 0.65, 0.75, 0.8, 1.0 (also written `1`), 1.15, 1.25, 1.26, 1.27, 1.65, 3.3.
2. Per-axis pitch `_P<Xpitch>x<Ypitch>mm` — X first. `BGA-200_10x14.5mm_Layout12x22_P0.8x0.65mm`: coordinates confirm 0.8 spacing in X, 0.65 in Y. Also `Dialog_WLCSP-34_4.54x1.66mm_Layout17x4_P0.25x0.34mm`, `WLCSP-8_1.58x1.63x0.35mm_Layout3x5_P0.35x0.4mm_Ball0.25mm_Pad0.25mm_NSMD`.
3. Two regions, concatenated `P…mmP…mm` — an outer ring at one pitch plus an inner sub-array at another. `ST_TFBGA-257_10x10mm_Layout19x19_P0.5mmP0.65mm` (the inner block's pads are named with a `1` prefix: `1A1`, `1A2`, … alongside the outer `A1`, `B1`, …); `ST_TFBGA-361_12x12mm_Layout23x23_P0.5mmP0.65mm`; `Nexperia_WLCSP-15_2.37x1.17mm_Layout6x3_P0.4mmP0.8mm`.
4. Mixed single + per-axis: `ST_VFBGA-424_14x14mm_Layout27x27_P0.5mmP0.5x0.5mm_Stagger`.
5. `P1mm` vs `P1.0mm` — both spellings are live and even collide (see pitfalls).

### A8. Ball diameter and land diameter: `_Ball<d>mm_Pad<d>mm_NSMD`
Ball Ø, then copper land Ø, then the solder-mask definition. This trio appears in exactly 18 of the 454 grid-array files, always all three together, and `NSMD` never appears without it:
- `BGA-100_11.0x11.0mm_Layout10x10_P1.0mm_Ball0.5mm_Pad0.4mm_NSMD`
- `BGA-36_3.396x3.466mm_Layout6x6_P0.4mm_Ball0.25mm_Pad0.2mm_NSMD`
- `BGA-672_27.0x27.0mm_Layout26x26_P1.0mm_Ball0.6mm_Pad0.5mm_NSMD`
- `Maxim_WLP-9_1.595x1.415_Layout3x3_P0.4mm_Ball0.27mm_Pad0.25mm_NSMD`

A land diameter can also appear alone, without a ball diameter, as a hand-solder/variant discriminator: `pSemi_CSP-16_1.64x2.04mm_P0.4mm_Pad0.18mm` versus `pSemi_CSP-16_1.64x2.04mm_P0.4mm`.

### A9. Exposed pads
Count goes in the pin field as `-<m>EP`; size goes in a trailing `_EP<x>x<y>mm`; `_ThermalVias` marks the variant with vias in the EP.
- Single EP with size: `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm` / `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias`
- `Texas_SIL0010A_MicroSiP-10-1EP_3.8x3mm_P0.6mm_EP0.7x2.9mm_ThermalVias`
- Multi-EP arrays, count only, no size: `Nordic_nRF9160-SIxx_LGA-102-59EP_16.0x10.5mm_P0.5mm`, `Nordic_nRF9151-LAxx_LGA-80-33EP_12.1x11.1mm_P0.5mm`, `MPS_LGA-18-10EP_12x12mm_P3.3mm`
- EP count with no size and no vias token: `AMS_LGA-10-1EP_2.7x4mm_P0.6mm`, `LFCSP-VQ-48-1EP_7x7mm_P0.5mm`

### A10. Array-geometry modifiers
- `_Stagger` — the balls occupy alternating cells of the stated grid, so `n ≈ C×R / 2`: `ST_WLCSP-12_1.7x1.42mm_Layout4x6_P0.35mm_Stagger` (12 balls in a 4×6 grid; pads A2, A4, B1, B3, C2, C4, D1, D3, E2, E4, F1, F3). 21 CSP files use it, plus `ST_VFBGA-424_14x14mm_Layout27x27_P0.5mmP0.5x0.5mm_Stagger`.
- `_Offcenter` — the ball array is not centred on the body outline: `ST_WLCSP-49_3.14x3.14mm_Layout7x7_P0.4mm_Offcenter`, `ST_WLCSP-100_4.4x4.38mm_Layout10x10_P0.4mm_Offcenter`.
- Both together: `ST_WLCSP-36_2.83x2.99mm_Layout7x13_P0.4mm_Stagger_Offcenter`, `ST_WLCSP-80_3.5x3.27mm_Layout10x16_P0.35mm_Stagger_Offcenter`.
- `_ClockwisePinNumbering` — pin 1 → n runs clockwise instead of the default: `Bosch_LGA-8_3x3mm_P0.8mm_ClockwisePinNumbering`.
- `_Die<id>` — ST's legacy WLCSP naming: the die ID replaces all geometry (40 files): `ST_WLCSP-100_Die446`, `ST_WLCSP-49_Die435`, `ST_WLCSP-64_Die435`.
- Assembly/process variants: `_ThermalVias`, `_SMD` (`Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm_SMD`, `Microchip_TFBGA-196_11x11mm_Layout14x14_P0.75mm_SMD`), `_ManualAssembly` (`OnSemi_ODCSP8_BGA-8_3.16x3.16mm_Layout3x3_P1.26mm_ManualAssembly`), `_LevelB` / `_LevelC` (`Texas_DSBGA-6_0.855x1.255mm_Layout2x3_P0.4mm_LevelB`).

### A11. LFCSP is a false friend inside Package_CSP
68 of the 179 `Package_CSP.pretty` files are Analog Devices `LFCSP*` — a **perimeter leadless** package built exactly like a QFN, with no grid array and therefore never a `_Layout` token. Its grammar is the QFN grammar: `LFCSP-<n>[-1EP]_<X>x<Y>mm_P<pitch>mm[_EP<x>x<y>mm][_ThermalVias]`, e.g. `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm_ThermalVias`, plus thermal-shape sub-variants `LFCSP-WD-…` (`LFCSP-WD-8-1EP_3x3mm_P0.65mm_EP1.6x2.44mm`), `LFCSP-VQ-…` (`LFCSP-VQ-24-1EP_4x4mm_P0.5mm_EP2.642x2.642mm`) and `Analog_LFCSP-UQ-10_1.3x1.6mm_P0.4mm`.

---

## B. Module naming reality — there is no geometric scheme

**Modules carry the vendor product name verbatim. Full stop.** No ball count, no body size, no pitch, no layout — the filename *is* the marketing part number, spelled the way the vendor spells it, including its hyphens, its suffix letters and its capitalisation.

Machine-counted: of the 144 stock module footprints in `RF_Module.pretty` (69), `RF_GPS.pretty` (16), `RF_GSM.pretty` (11), `RF_WiFi.pretty` (1) and `Module.pretty` (47), **138 are the bare product name** and only **6** carry any geometric or package token at all. Those 6 are, verbatim: `CYBLE-21Pin-10x10mm`, `Garmin_M8-35_9.8x14.0mm_Layout6x6_P1.5mm`, `ST-SiP-LGA-86-11x7.3mm`, `ublox_LENA-R8_LGA-100`, `ublox_SARA_LGA-96`, `Pololu_Breakout-16_15.2x20.3mm`.

The consequence: **you cannot derive a module footprint name. You look up the product name.** Two modules with an identical 96-land pattern get two different filenames; one module with two antenna options (`…-1` vs `…-1U`) gets two filenames that differ by one letter.

15+ verbatim examples across vendors (every one existence-tested):

| Vendor | Verbatim stock filename | Library |
|---|---|---|
| Espressif | `ESP32-WROOM-32` | `RF_Module.pretty` |
| Espressif | `ESP32-WROOM-32UE` | `RF_Module.pretty` |
| Espressif | `ESP32-S3-WROOM-1U` | `RF_Module.pretty` |
| Espressif | `ESP32-C6-MINI-1` | `RF_Module.pretty` |
| Espressif | `ESP-WROOM-02` | `RF_Module.pretty` |
| Espressif | `ESP-12E` | `RF_Module.pretty` |
| u-blox | `ublox_SARA_LGA-96` | `RF_GSM.pretty` |
| u-blox | `ublox_LENA-R8_LGA-100` | `RF_GSM.pretty` |
| u-blox | `ublox_ZOE_M8` | `RF_GPS.pretty` |
| u-blox | `ublox_SAM-M8Q` | `RF_GPS.pretty` |
| u-blox | `NINA-B111` | `RF_Module.pretty` |
| Quectel | `Quectel_BG96` | `RF_GSM.pretty` |
| Quectel | `Quectel_BC66` | `RF_GSM.pretty` |
| Quectel | `Quectel_L80-R` | `RF_GPS.pretty` |
| Telit | `Telit_xL865` | `RF_GSM.pretty` |
| Telit | `Telit_SE150A4` | `RF_GSM.pretty` |
| Sierra Wireless | `Sierra_XA11X0` | `RF_GPS.pretty` |
| Sierra Wireless | `Sierra_XM11X0` | `RF_GPS.pretty` |
| Raspberry Pi | `RaspberryPi_Pico_W_SMD` | `Module.pretty` |
| Raspberry Pi | `Raspberry_Pi_Zero_Socketed_THT_FaceDown_MountingHoles` | `Module.pretty` |
| Nordic | `Nordic_nRF9160-SIxx_LGA-102-59EP_16.0x10.5mm_P0.5mm` | `Package_LGA.pretty` |
| Nordic | `Nordic_nRF9151-LAxx_LGA-80-33EP_12.1x11.1mm_P0.5mm` | `Package_LGA.pretty` |
| Nordic-based (Raytac) | `Raytac_MDBT50Q` | `RF_Module.pretty` |
| Nordic-based (Laird) | `Laird_BL653` | `RF_Module.pretty` |
| Nordic-based (Taiyo Yuden) | `Taiyo-Yuden_EYSGJNZWY` | `RF_Module.pretty` |
| SIMCom | `SIMCom_SIM800C` | `RF_GSM.pretty` |
| STMicro | `ST-SiP-LGA-86-11x7.3mm` | `RF_Module.pretty` |
| Google | `Google_Coral_SMT_TPU_Module` | `Module.pretty` |
| Murata | **none — see below** | — |

**Murata, stated plainly and verified:** KiCad 10.0 ships **no Murata RF/wireless module footprint**. A `find` for `*Murata*` and for the Murata module part-code families (`LBEE*`, `LBAA*`, `Type1*`, `*1DX*`, `*1LD*`, `*1YM*`, `*1ZM*`) across the entire footprint tree returns only passives and power parts — e.g. `Filter.pretty/Filter_Murata_BNX025.kicad_mod`, `Inductor_SMD.pretty/L_Murata_DFE201610P.kicad_mod`, `Converter_DCDC.pretty/Converter_DCDC_muRata_MEJ1DxxxxSC_THT.kicad_mod` (note the lowercase `muRata` there). A Murata 1DX/1YM/1ZM Wi-Fi+BT module must be drawn locally; there is nothing to reuse.

Also worth knowing: the two Nordic rows above are the only "module-ish" parts KiCad names geometrically because they are molded SiPs, and they live in `Package_LGA.pretty`, not in an `RF_*` library. `RF_WiFi.pretty` contains exactly **one** footprint (`USR-C322`) — every Espressif Wi-Fi module is in `RF_Module.pretty`, not `RF_WiFi.pretty`.

## Reference table

### Table 1 — `Package_BGA.pretty` (234 footprints, complete)

"Pads in file" = distinct pad designators found in the `.kicad_mod`. "Layout" and "Pitch" are the tokens as they appear in the filename.

| Verbatim footprint name | Pads in file | Body mm | Layout | Pitch mm | Modifiers |
|---|---|---|---|---|---|
| `Alliance_TFBGA-36_6x8mm_Layout6x8_P0.75mm` | 36 | 6x8 | 6x8 | 0.75 | — |
| `Alliance_TFBGA-54_8x8mm_Layout9x9_P0.8mm` | 54 | 8x8 | 9x9 | 0.8 | — |
| `Analog_BGA-165_11.9x16mm_Layout11x15_P1.0mm` | 165 | 11.9x16 | 11x15 | 1.0 | — |
| `Analog_BGA-209_9.5x16mm_Layout11x19_P0.8mm` | 209 | 9.5x16 | 11x19 | 0.8 | — |
| `Analog_BGA-28_4x6.25mm_Layout4x7_P0.8mm` | 28 | 4x6.25 | 4x7 | 0.8 | — |
| `Analog_BGA-49_6.25x6.25mm_Layout7x7_P0.8mm` | 49 | 6.25x6.25 | 7x7 | 0.8 | — |
| `Analog_BGA-77_9x15mm_Layout7x11_P1.27mm` | 77 | 9x15 | 7x11 | 1.27 | — |
| `BGA-100_11.0x11.0mm_Layout10x10_P1.0mm_Ball0.5mm_Pad0.4mm_NSMD` | 100 | 11.0x11.0 | 10x10 | 1.0 | Ball0.5/Pad0.4, NSMD |
| `BGA-100_12x18mm_Layout10x17_P1mm` | 100 | 12x18 | 10x17 | 1 | — |
| `BGA-100_14x18mm_Layout10x17_P1mm` | 100 | 14x18 | 10x17 | 1 | — |
| `BGA-100_6.0x6.0mm_Layout11x11_P0.5mm_Ball0.3mm_Pad0.25mm_NSMD` | 100 | 6.0x6.0 | 11x11 | 0.5 | Ball0.3/Pad0.25, NSMD |
| `BGA-1023_33.0x33.0mm_Layout32x32_P1.0mm` | 1023 | 33.0x33.0 | 32x32 | 1.0 | — |
| `BGA-1156_35.0x35.0mm_Layout34x34_P1.0mm` | 1156 | 35.0x35.0 | 34x34 | 1.0 | — |
| `BGA-121_9.0x9.0mm_Layout11x11_P0.8mm_Ball0.4mm_Pad0.35mm_NSMD` | 121 | 9.0x9.0 | 11x11 | 0.8 | Ball0.4/Pad0.35, NSMD |
| `BGA-1295_37.5x37.5mm_Layout36x36_P1.0mm` | 1295 | 37.5x37.5 | 36x36 | 1.0 | — |
| `BGA-132_12x18mm_Layout11x17_P1.0mm` | 132 | 12x18 | 11x17 | 1.0 | — |
| `BGA-132_12x18mm_Layout11x17_P1mm` | 132 | 12x18 | 11x17 | 1 | — |
| `BGA-144_13.0x13.0mm_Layout12x12_P1.0mm` | 144 | 13.0x13.0 | 12x12 | 1.0 | — |
| `BGA-144_7.0x7.0mm_Layout13x13_P0.5mm_Ball0.3mm_Pad0.25mm_NSMD` | 144 | 7.0x7.0 | 13x13 | 0.5 | Ball0.3/Pad0.25, NSMD |
| `BGA-152_14x18mm_Layout13x17_P0.5mm` | 152 | 14x18 | 13x17 | 0.5 | — |
| `BGA-152_14x18mm_Layout13x17_P1mm` | 152 | 14x18 | 13x17 | 1 | — |
| `BGA-153_8.0x8.0mm_Layout15x15_P0.5mm_Ball0.3mm_Pad0.25mm_NSMD` | 153 | 8.0x8.0 | 15x15 | 0.5 | Ball0.3/Pad0.25, NSMD |
| `BGA-169_11.0x11.0mm_Layout13x13_P0.8mm_Ball0.5mm_Pad0.4mm_NSMD` | 169 | 11.0x11.0 | 13x13 | 0.8 | Ball0.5/Pad0.4, NSMD |
| `BGA-16_1.92x1.92mm_Layout4x4_P0.5mm` | 16 | 1.92x1.92 | 4x4 | 0.5 | — |
| `BGA-196_15x15mm_Layout14x14_P1.0mm` | 196 | 15x15 | 14x14 | 1.0 | — |
| `BGA-200_10x14.5mm_Layout12x22_P0.8x0.65mm` | 200 | 10x14.5 | 12x22 | 0.8x0.65 | — |
| `BGA-24_6x8mm_Layout5x5_P1.0mm` | 24 | 6x8 | 5x5 | 1.0 | — |
| `BGA-24_8x8mm_Layout5x5_P1.0mm` | 24 | 8x8 | 5x5 | 1.0 | — |
| `BGA-256_11.0x11.0mm_Layout20x20_P0.5mm_Ball0.3mm_Pad0.25mm_NSMD` | 256 | 11.0x11.0 | 20x20 | 0.5 | Ball0.3/Pad0.25, NSMD |
| `BGA-256_14.0x14.0mm_Layout16x16_P0.8mm_Ball0.45mm_Pad0.32mm_NSMD` | 256 | 14.0x14.0 | 16x16 | 0.8 | Ball0.45/Pad0.32, NSMD |
| `BGA-256_17.0x17.0mm_Layout16x16_P1.0mm_Ball0.5mm_Pad0.4mm_NSMD` | 256 | 17.0x17.0 | 16x16 | 1.0 | Ball0.5/Pad0.4, NSMD |
| `BGA-25_6.35x6.35mm_Layout5x5_P1.27mm` | 25 | 6.35x6.35 | 5x5 | 1.27 | — |
| `BGA-324_15.0x15.0mm_Layout18x18_P0.8mm_Ball0.5mm_Pad0.4mm_NSMD` | 324 | 15.0x15.0 | 18x18 | 0.8 | Ball0.5/Pad0.4, NSMD |
| `BGA-324_15x15mm_Layout18x18_P0.8mm` | 324 | 15x15 | 18x18 | 0.8 | — |
| `BGA-324_19.0x19.0mm_Layout18x18_P1.0mm_Ball0.5mm_Pad0.4mm_NSMD` | 324 | 19.0x19.0 | 18x18 | 1.0 | Ball0.5/Pad0.4, NSMD |
| `BGA-352_35.0x35.0mm_Layout26x26_P1.27mm` | 352 | 35.0x35.0 | 26x26 | 1.27 | — |
| `BGA-36_3.396x3.466mm_Layout6x6_P0.4mm_Ball0.25mm_Pad0.2mm_NSMD` | 36 | 3.396x3.466 | 6x6 | 0.4 | Ball0.25/Pad0.2, NSMD |
| `BGA-400_21.0x21.0mm_Layout20x20_P1.0mm` | 400 | 21.0x21.0 | 20x20 | 1.0 | — |
| `BGA-484_23.0x23.0mm_Layout22x22_P1.0mm` | 484 | 23.0x23.0 | 22x22 | 1.0 | — |
| `BGA-48_8.0x9.0mm_Layout6x8_P0.8mm` | 48 | 8.0x9.0 | 6x8 | 0.8 | — |
| `BGA-529_19x19mm_Layout23x23_P0.8mm` | 529 | 19x19 | 23x23 | 0.8 | — |
| `BGA-624_21x21mm_Layout25x25_P0.8mm` | 624 | 21x21 | 25x25 | 0.8 | — |
| `BGA-625_21.0x21.0mm_Layout25x25_P0.8mm` | 625 | 21.0x21.0 | 25x25 | 0.8 | — |
| `BGA-63_9x11mm_Layout10x12_P0.8mm` | 63 | 9x11 | 10x12 | 0.8 | — |
| `BGA-64_9.0x9.0mm_Layout10x10_P0.8mm` | 64 | 9.0x9.0 | 10x10 | 0.8 | — |
| `BGA-672_27.0x27.0mm_Layout26x26_P1.0mm_Ball0.6mm_Pad0.5mm_NSMD` | 672 | 27.0x27.0 | 26x26 | 1.0 | Ball0.6/Pad0.5, NSMD |
| `BGA-676_27.0x27.0mm_Layout26x26_P1.0mm_Ball0.6mm_Pad0.5mm_NSMD` | 676 | 27.0x27.0 | 26x26 | 1.0 | Ball0.6/Pad0.5, NSMD |
| `BGA-68_5.0x5.0mm_Layout9x9_P0.5mm_Ball0.3mm_Pad0.25mm_NSMD` | 68 | 5.0x5.0 | 9x9 | 0.5 | Ball0.3/Pad0.25, NSMD |
| `BGA-81_4.496x4.377mm_Layout9x9_P0.4mm_Ball0.25mm_Pad0.2mm_NSMD` | 81 | 4.496x4.377 | 9x9 | 0.4 | Ball0.25/Pad0.2, NSMD |
| `BGA-90_8.0x13.0mm_Layout2x3x15_P0.8mm` | 90 | 8.0x13.0 | 2x3x15 | 0.8 | banded grid |
| `BGA-96_9.0x13.0mm_Layout2x3x16_P0.8mm` | 96 | 9.0x13.0 | 2x3x16 | 0.8 | banded grid |
| `BGA-9_1.6x1.6mm_Layout3x3_P0.5mm` | 9 | 1.6x1.6 | 3x3 | 0.5 | — |
| `csBGA-64_5x5mm_Layout8x8_P0.5mm` | 64 | 5x5 | 8x8 | 0.5 | — |
| `EPC_BGA-4_0.9x0.9mm_Layout2x2_P0.45mm` | 4 | 0.9x0.9 | 2x2 | 0.45 | — |
| `FB-BGA-484_23.0x23.0mm_Layout22x22_P1.0mm` | 484 | 23.0x23.0 | 22x22 | 1.0 | — |
| `FBGA-78_7.5x10.5mm_Layout9x13_P0.8mm` | 78 | 7.5x10.5 | 9x13 | 0.8 | — |
| `FBGA-78_7.5x10.6mm_Layout9x13_P0.8mm` | 78 | 7.5x10.6 | 9x13 | 0.8 | — |
| `FBGA-78_7.5x11mm_Layout2x3x13_P0.8mm` | 78 | 7.5x11 | 2x3x13 | 0.8 | banded grid |
| `FBGA-78_8x10.5mm_Layout9x13_P0.8mm` | 78 | 8x10.5 | 9x13 | 0.8 | — |
| `FBGA-78_9x10.5mm_Layout9x13_P0.8mm` | 78 | 9x10.5 | 9x13 | 0.8 | — |
| `FBGA-78_9x10.6mm_Layout9x13_P0.8mm` | 78 | 9x10.6 | 9x13 | 0.8 | — |
| `FBGA-96_7.5x13.5mm_Layout9x16_P0.8mm` | 96 | 7.5x13.5 | 9x16 | 0.8 | — |
| `FBGA-96_7.5x13mm_Layout9x16_P0.8mm` | 96 | 7.5x13 | 9x16 | 0.8 | — |
| `FBGA-96_8x13mm_Layout9x16_P0.8mm` | 96 | 8x13 | 9x16 | 0.8 | — |
| `FBGA-96_8x14mm_Layout9x16_P0.8mm` | 96 | 8x14 | 9x16 | 0.8 | — |
| `FBGA-96_9x13mm_Layout9x16_P0.8mm` | 96 | 9x13 | 9x16 | 0.8 | — |
| `FBGA-96_9x14mm_Layout9x16_P0.8mm` | 96 | 9x14 | 9x16 | 0.8 | — |
| `FCPBGA-780_23x23mm_Layout28x28_P0.8mm` | 780 | 23x23 | 28x28 | 0.8 | — |
| `Fujitsu_WLP-15_2.28x3.092mm_Layout3x5_P0.4mm` | 8 | 2.28x3.092 | 3x5 | 0.4 | name says 15, file has 8 |
| `Infineon_LFBGA-292_17x17mm_Layout20x20_P0.8mm` | 292 | 17x17 | 20x20 | 0.8 | — |
| `Infineon_TFBGA-48_6x10mm_Layout6x8_P0.75mm` | 48 | 6x10 | 6x8 | 0.75 | — |
| `Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm` | 381 | 17x17 | 20x20 | 0.8 | — |
| `Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm_SMD` | 381 | 17x17 | 20x20 | 0.8 | SMD |
| `Lattice_caBGA-756_27x27mm_Layout32x32_P0.8mm` | 756 | 27x27 | 32x32 | 0.8 | — |
| `Lattice_iCE40_csBGA-132_8x8mm_Layout14x14_P0.5mm` | 132 | 8x8 | 14x14 | 0.5 | — |
| `LFBGA-100_10x10mm_Layout10x10_P0.8mm` | 100 | 10x10 | 10x10 | 0.8 | — |
| `LFBGA-144_10x10mm_Layout12x12_P0.8mm` | 144 | 10x10 | 12x12 | 0.8 | — |
| `LFBGA-153_11.5x13mm_Layout14x14_P0.5mm` | 153 | 11.5x13 | 14x14 | 0.5 | — |
| `LFBGA-169_12x16mm_Layout14x28_P0.5mm` | 169 | 12x16 | 14x28 | 0.5 | — |
| `LFBGA-169_12x18mm_Layout14x28_P0.5mm` | 169 | 12x18 | 14x28 | 0.5 | — |
| `LFBGA-169_14x18mm_Layout14x28_P0.5mm` | 169 | 14x18 | 14x28 | 0.5 | — |
| `LFBGA-289_14x14mm_Layout17x17_P0.8mm` | 289 | 14x14 | 17x17 | 0.8 | — |
| `LFBGA-400_16x16mm_Layout20x20_P0.8mm` | 400 | 16x16 | 20x20 | 0.8 | — |
| `LFBGA-484_18x18mm_Layout22x22_P0.8mm` | 484 | 18x18 | 22x22 | 0.8 | — |
| `Linear_BGA-133_15.0x15.0mm_Layout12x12_P1.27mm` | 134 | 15.0x15.0 | 12x12 | 1.27 | name says 133, file has 134 (extra `E8`) |
| `MAPBGA-272_9x9mm_Layout17x17_P0.5mm` | 272 | 9x9 | 17x17 | 0.5 | — |
| `MAPBGA-289_14x14mm_Layout17x17_P0.8mm` | 289 | 14x14 | 17x17 | 0.8 | — |
| `Maxim_WLP-12` | 12 | — | — | — | legacy: no geometry |
| `Maxim_WLP-12_2.008x1.608mm_Layout4x3_P0.4mm` | 12 | 2.008x1.608 | 4x3 | 0.4 | — |
| `Maxim_WLP-9_1.595x1.415_Layout3x3_P0.4mm_Ball0.27mm_Pad0.25mm_NSMD` | 9 | 1.595x1.415 (no `mm`) | 3x3 | 0.4 | Ball0.27/Pad0.25, NSMD |
| `Microchip_FCG1152_BGA-1152_35x35mm_Layout34x34_P1.0mm` | 1152 | 35x35 | 34x34 | 1.0 | — |
| `Microchip_FCSG325_BGA-325_11x11mm_Layout21x21_P0.5mm` | 325 | 11x11 | 21x21 | 0.5 | — |
| `Microchip_FCSG536_BGA-536_16x16mm_Layout30x30_P0.5mm` | 536 | 16x16 | 30x30 | 0.5 | — |
| `Microchip_FCVG484_BGA-484_19x19mm_Layout22x22_P0.8mm` | 484 | 19x19 | 22x22 | 0.8 | — |
| `Microchip_FCVG784_BGA-784_23x23mm_Layout28x28_P0.8mm` | 784 | 23x23 | 28x28 | 0.8 | — |
| `Microchip_TFBGA-196_11x11mm_Layout14x14_P0.75mm_SMD` | 196 | 11x11 | 14x14 | 0.75 | SMD |
| `Micron_FBGA-78_7.5x10.6mm_Layout9x13_P0.8mm` | 78 | 7.5x10.6 | 9x13 | 0.8 | — |
| `Micron_FBGA-78_8x10.5mm_Layout9x13_P0.8mm` | 78 | 8x10.5 | 9x13 | 0.8 | — |
| `Micron_FBGA-78_9x10.5mm_Layout9x13_P0.8mm` | 78 | 9x10.5 | 9x13 | 0.8 | — |
| `Micron_FBGA-96_7.5x13.5mm_Layout9x16_P0.8mm` | 96 | 7.5x13.5 | 9x16 | 0.8 | — |
| `Micron_FBGA-96_8x14mm_Layout9x16_P0.8mm` | 96 | 8x14 | 9x16 | 0.8 | — |
| `Micron_FBGA-96_9x14mm_Layout9x16_P0.8mm` | 96 | 9x14 | 9x16 | 0.8 | — |
| `NXP_SOT1982-1_VFBGA-98_7x7mm_Layout13x13_P0.5mm` | 98 | 7x7 | 13x13 | 0.5 | — |
| `NXP_SOT2162-1_VFBGA-59_4x4mm_Layout9x9_P0.4mm` | 59 | 4x4 | 9x9 | 0.4 | — |
| `NXP_TFBGA-50_5x5mm_Layout9x9_P0.5mm` | 50 | 5x5 | 9x9 | 0.5 | — |
| `NXP_VFBGA-42_2.6x3mm_Layout6x7_P0.4mm` | 42 | 2.6x3 | 6x7 | 0.4 | — |
| `ST_LFBGA-354_16x16mm_Layout19x19_P0.8mm` | 354 | 16x16 | 19x19 | 0.8 | — |
| `ST_LFBGA-448_18x18mm_Layout22x22_P0.8mm` | 448 | 18x18 | 22x22 | 0.8 | — |
| `ST_TFBGA-169_7x7mm_Layout13x13_P0.5mm` | 169 | 7x7 | 13x13 | 0.5 | — |
| `ST_TFBGA-225_13x13mm_Layout15x15_P0.8mm` | 225 | 13x13 | 15x15 | 0.8 | — |
| `ST_TFBGA-257_10x10mm_Layout19x19_P0.5mmP0.65mm` | 257 | 10x10 | 19x19 | 0.5 + 0.65 | dual-region pitch |
| `ST_TFBGA-320_11x11mm_Layout21x21_P0.5mm` | 320 | 11x11 | 21x21 | 0.5 | — |
| `ST_TFBGA-361_12x12mm_Layout23x23_P0.5mmP0.65mm` | 361 | 12x12 | 23x23 | 0.5 + 0.65 | dual-region pitch |
| `ST_TFBGA-436_18x18mm_Layout22x22_P0.8mm` | 436 | 18x18 | 22x22 | 0.8 | — |
| `ST_UFBGA-121_6x6mm_Layout11x11_P0.5mm` | 121 | 6x6 | 11x11 | 0.5 | — |
| `ST_UFBGA-129_7x7mm_Layout13x13_P0.5mm` | 129 | 7x7 | 13x13 | 0.5 | — |
| `ST_UFBGA-59_5x5mm_Layout8x8_P0.5mm` | 59 | 5x5 | 8x8 | 0.5 | — |
| `ST_UFBGA-73_5x5mm_Layout9x9_P0.5mm` | 73 | 5x5 | 9x9 | 0.5 | — |
| `ST_UFBGA-81_5x5mm_Layout9x9_P0.5mm` | 81 | 5x5 | 9x9 | 0.5 | — |
| `ST_uTFBGA-36_3.6x3.6mm_Layout6x6_P0.5mm` | 36 | 3.6x3.6 | 6x6 | 0.5 | — |
| `ST_VFBGA-361_10x10mm_Layout19x19_P0.5mm` | 361 | 10x10 | 19x19 | 0.5 | — |
| `ST_VFBGA-424_14x14mm_Layout27x27_P0.5mmP0.5x0.5mm_Stagger` | 424 | 14x14 | 27x27 | 0.5 + 0.5x0.5 | Stagger |
| `Texas_BGA-289_15x15mm_Layout17x17_P0.8mm` | 289 | 15x15 | 17x17 | 0.8 | — |
| `Texas_DSBGA-10_1.36x1.86mm_Layout3x4_P0.5mm` | 10 | 1.36x1.86 | 3x4 | 0.5 | — |
| `Texas_DSBGA-12_1.36x1.86mm_Layout3x4_P0.5mm` | 12 | 1.36x1.86 | 3x4 | 0.5 | — |
| `Texas_DSBGA-12_2.11x1.61mm_Layout4x3_P0.5mm` | 12 | 2.11x1.61 | 4x3 | 0.5 | — |
| `Texas_DSBGA-16_2.39x2.39mm_Layout4x4_P0.5mm` | 16 | 2.39x2.39 | 4x4 | 0.5 | — |
| `Texas_DSBGA-28_1.9x3mm_Layout4x7_P0.4mm` | 28 | 1.9x3 | 4x7 | 0.4 | — |
| `Texas_DSBGA-49_3.33x3.488mm_Layout7x7_P0.4mm` | 49 | 3.33x3.488 | 7x7 | 0.4 | — |
| `Texas_DSBGA-5_0.822x1.116mm_Layout2x1x2_P0.4mm` | 5 | 0.822x1.116 | 2x1x2 | 0.4 | sum-form banded grid |
| `Texas_DSBGA-5_0.8875x1.3875mm_Layout2x3_P0.5mm` | 5 | 0.8875x1.3875 | 2x3 | 0.5 | — |
| `Texas_DSBGA-5_1.5855x1.6365mm_Layout3x2_P0.5mm` | 5 | 1.5855x1.6365 | 3x2 | 0.5 | — |
| `Texas_DSBGA-64_3.415x3.535mm_Layout8x8_P0.4mm` | 64 | 3.415x3.535 | 8x8 | 0.4 | — |
| `Texas_DSBGA-6_0.704x1.054mm_Layout2x3_P0.35mm` | 6 | 0.704x1.054 | 2x3 | 0.35 | — |
| `Texas_DSBGA-6_0.757x1.01mm_Layout2x3_P0.35mm` | 6 | 0.757x1.01 | 2x3 | 0.35 | — |
| `Texas_DSBGA-6_0.76x1.16mm_Layout2x3_P0.4mm` | 6 | 0.76x1.16 | 2x3 | 0.4 | — |
| `Texas_DSBGA-6_0.855x1.255mm_Layout2x3_P0.4mm_LevelB` | 6 | 0.855x1.255 | 2x3 | 0.4 | LevelB |
| `Texas_DSBGA-6_0.855x1.255mm_Layout2x3_P0.4mm_LevelC` | 6 | 0.855x1.255 | 2x3 | 0.4 | LevelC |
| `Texas_DSBGA-6_0.95x1.488mm_Layout2x3_P0.4mm` | 6 | 0.95x1.488 | 2x3 | 0.4 | — |
| `Texas_DSBGA-6_0.9x1.4mm_Layout2x3_P0.5mm` | 6 | 0.9x1.4 | 2x3 | 0.5 | — |
| `Texas_DSBGA-8_0.705x1.468mm_Layout2x4_P0.4mm` | 8 | 0.705x1.468 | 2x4 | 0.4 | — |
| `Texas_DSBGA-8_0.9x1.9mm_Layout2x4_P0.5mm` | 8 | 0.9x1.9 | 2x4 | 0.5 | — |
| `Texas_DSBGA-8_1.43x1.41mm_Layout3x3_P0.5mm` | 8 | 1.43x1.41 | 3x3 | 0.5 | — |
| `Texas_DSBGA-8_1.5195x1.5195mm_Layout3x3_P0.5mm` | 8 | 1.5195x1.5195 | 3x3 | 0.5 | — |
| `Texas_DSBGA-9_1.4715x1.4715mm_Layout3x3_P0.5mm` | 9 | 1.4715x1.4715 | 3x3 | 0.5 | — |
| `Texas_DSBGA-9_1.62x1.58mm_Layout3x3_P0.5mm` | 9 | 1.62x1.58 | 3x3 | 0.5 | — |
| `Texas_MicroStar_Junior_BGA-113_7x7mm_Layout12x12_P0.5mm` | 113 | 7x7 | 12x12 | 0.5 | — |
| `Texas_MicroStar_Junior_BGA-12_2.0x2.5mm_Layout4x3_P0.5mm` | 12 | 2.0x2.5 | 4x3 | 0.5 | — |
| `Texas_MicroStar_Junior_BGA-80_5.0x5.0mm_Layout9x9_P0.5mm` | 80 | 5.0x5.0 | 9x9 | 0.5 | — |
| `Texas_PicoStar_BGA-4_0.758x0.758mm_Layout2x2_P0.4mm` | 4 | 0.758x0.758 | 2x2 | 0.4 | — |
| `Texas_YFP0020_DSBGA-20_1.588x1.988mm_Layout4x5_P0.4mm` | 20 | 1.588x1.988 | 4x5 | 0.4 | — |
| `TFBGA-100_5.5x5.5mm_Layout10x10_P0.5mm` | 100 | 5.5x5.5 | 10x10 | 0.5 | — |
| `TFBGA-100_8x8mm_Layout10x10_P0.8mm` | 100 | 8x8 | 10x10 | 0.8 | — |
| `TFBGA-100_9.0x9.0mm_Layout10x10_P0.8mm` | 100 | 9.0x9.0 | 10x10 | 0.8 | — |
| `TFBGA-121_10x10mm_Layout11x11_P0.8mm` | 121 | 10x10 | 11x11 | 0.8 | — |
| `TFBGA-169_9x9mm_Layout13x13_P0.65mm` | 169 | 9x9 | 13x13 | 0.65 | — |
| `TFBGA-216_13x13mm_Layout15x15_P0.8mm` | 216 | 13x13 | 15x15 | 0.8 | — |
| `TFBGA-225_10x10mm_Layout15x15_P0.65mm` | 225 | 10x10 | 15x15 | 0.65 | — |
| `TFBGA-256_13x13mm_Layout16x16_P0.8mm` | 256 | 13x13 | 16x16 | 0.8 | — |
| `TFBGA-265_14x14mm_Layout17x17_P0.8mm` | 265 | 14x14 | 17x17 | 0.8 | — |
| `TFBGA-289_9x9mm_Layout17x17_P0.5mm` | 289 | 9x9 | 17x17 | 0.5 | — |
| `TFBGA-324_12x12mm_Layout18x18_P0.65mm` | 324 | 12x12 | 18x18 | 0.65 | — |
| `TFBGA-361_13x13mm_Layout19x19_P0.65mm` | 361 | 13x13 | 19x19 | 0.65 | — |
| `TFBGA-48_6x10mm_Layout6x8_P0.75mm` | 48 | 6x10 | 6x8 | 0.75 | — |
| `TFBGA-49_3x3mm_Layout7x7_P0.4mm` | 49 | 3x3 | 7x7 | 0.4 | — |
| `TFBGA-576_16x16mm_Layout24x24_P0.65mm` | 576 | 16x16 | 24x24 | 0.65 | — |
| `TFBGA-644_19x19mm_Layout28x28_P0.65mm` | 644 | 19x19 | 28x28 | 0.65 | — |
| `TFBGA-64_5x5mm_Layout8x8_P0.5mm` | 64 | 5x5 | 8x8 | 0.5 | — |
| `TFBGA-81_5x5mm_Layout9x9_P0.5mm` | 81 | 5x5 | 9x9 | 0.5 | — |
| `UCBGA-36_2.5x2.5mm_Layout6x6_P0.4mm` | 36 | 2.5x2.5 | 6x6 | 0.4 | — |
| `UCBGA-49_3x3mm_Layout7x7_P0.4mm` | 49 | 3x3 | 7x7 | 0.4 | — |
| `ucBGA-64_4x4mm_Layout8x8_P0.4mm` | 64 | 4x4 | 8x8 | 0.4 | lowercase `ucBGA` |
| `UCBGA-81_4x4mm_Layout9x9_P0.4mm` | 81 | 4x4 | 9x9 | 0.4 | — |
| `UFBGA-100_7x7mm_Layout12x12_P0.5mm` | 100 | 7x7 | 12x12 | 0.5 | — |
| `UFBGA-132_7x7mm_Layout12x12_P0.5mm` | 132 | 7x7 | 12x12 | 0.5 | — |
| `UFBGA-132_7x7mm_P0.5mm` | 132 | 7x7 | — | 0.5 | legacy: no Layout |
| `UFBGA-144_10x10mm_Layout12x12_P0.8mm` | 144 | 10x10 | 12x12 | 0.8 | — |
| `UFBGA-144_7x7mm_Layout12x12_P0.5mm` | 144 | 7x7 | 12x12 | 0.5 | — |
| `UFBGA-15_3.0x3.0mm_Layout4x4_P0.65mm` | 15 | 3.0x3.0 | 4x4 | 0.65 | — |
| `UFBGA-169_7x7mm_Layout13x13_P0.5mm` | 169 | 7x7 | 13x13 | 0.5 | — |
| `UFBGA-201_10x10mm_Layout15x15_P0.65mm` | 201 | 10x10 | 15x15 | 0.65 | — |
| `UFBGA-32_4.0x4.0mm_Layout6x6_P0.5mm` | 32 | 4.0x4.0 | 6x6 | 0.5 | — |
| `UFBGA-64_5x5mm_Layout8x8_P0.5mm` | 64 | 5x5 | 8x8 | 0.5 | — |
| `VFBGA-100_7.0x7.0mm_Layout10x10_P0.65mm` | 100 | 7.0x7.0 | 10x10 | 0.65 | — |
| `VFBGA-49_5.0x5.0mm_Layout7x7_P0.65mm` | 49 | 5.0x5.0 | 7x7 | 0.65 | — |
| `VFBGA-86_6x6mm_Layout10x10_P0.55mm` | 86 | 6x6 | 10x10 | 0.55 | — |
| `WLP-4_0.728x0.728mm_Layout2x2_P0.35mm` | 4 | 0.728x0.728 | 2x2 | 0.35 | — |
| `WLP-4_0.83x0.83mm_P0.4mm` | 4 | 0.83x0.83 | — | 0.4 | legacy: no Layout |
| `WLP-4_0.86x0.86mm_P0.4mm` | 4 | 0.86x0.86 | — | 0.4 | legacy: no Layout |
| `WLP-9_1.468x1.448mm_Layout3x3_P0.4mm` | 9 | 1.468x1.448 | 3x3 | 0.4 | — |
| `XBGA-121_10x10mm_Layout11x11_P0.8mm` | 121 | 10x10 | 11x11 | 0.8 | — |
| `XFBGA-121_8x8mm_Layout11x11_P0.65mm` | 121 | 8x8 | 11x11 | 0.65 | — |
| `XFBGA-36_3.5x3.5mm_Layout6x6_P0.5mm` | 36 | 3.5x3.5 | 6x6 | 0.5 | — |
| `XFBGA-64_5.0x5.0mm_Layout8x8_P0.5mm` | 64 | 5.0x5.0 | 8x8 | 0.5 | — |
| `Xilinx_CLG225` | 225 | — | — | — | code-only; geometry in descr |
| `Xilinx_CLG400` | 400 | — | — | — | code-only |
| `Xilinx_CLG484_CLG485` | 484 | — | — | — | code-only, two codes |
| `Xilinx_CPG236` | 238 | — | — | — | code-only; 238 pads |
| `Xilinx_CPG238` | 238 | — | — | — | code-only |
| `Xilinx_CPGA196` | 196 | — | — | — | code-only |
| `Xilinx_CSG324` | 324 | — | — | — | code-only |
| `Xilinx_CSG325` | 324 | — | — | — | code-only; 324 pads |
| `Xilinx_CSGA225` | 225 | — | — | — | code-only |
| `Xilinx_CSGA324` | 324 | — | — | — | code-only |
| `Xilinx_FBG484` | 484 | — | — | — | code-only |
| `Xilinx_FBG676` | 676 | — | — | — | code-only |
| `Xilinx_FBG900` | 900 | — | — | — | code-only |
| `Xilinx_FFG1156` | 1156 | — | — | — | code-only |
| `Xilinx_FFG1157_FFG1158` | 1156 | — | — | — | code-only, two codes |
| `Xilinx_FFG1761` | 1760 | — | — | — | code-only; 1760 pads |
| `Xilinx_FFG1926_FFG1927_FFG1928_FFG1930` | 1924 | — | — | — | code-only, four codes |
| `Xilinx_FFG676` | 676 | — | — | — | code-only |
| `Xilinx_FFG900_FFG901` | 900 | — | — | — | code-only |
| `Xilinx_FFV1761` | 1760 | — | — | — | code-only |
| `Xilinx_FGG484` | 484 | — | — | — | code-only |
| `Xilinx_FGG676` | 676 | — | — | — | code-only |
| `Xilinx_FGGA484` | 484 | — | — | — | code-only |
| `Xilinx_FGGA676` | 676 | — | — | — | code-only |
| `Xilinx_FHG1761` | 1760 | — | — | — | code-only |
| `Xilinx_FLG1925_FLG1926_FLG1928_FLG1930` | 1924 | — | — | — | code-only, four codes |
| `Xilinx_FTG256` | 256 | — | — | — | code-only |
| `Xilinx_FTGB196` | 196 | — | — | — | code-only |
| `Xilinx_RB484` | 484 | — | — | — | code-only |
| `Xilinx_RB676` | 676 | — | — | — | code-only |
| `Xilinx_RF1156` | 1156 | — | — | — | code-only |
| `Xilinx_RF1157_RF1158` | 1156 | — | — | — | code-only, two codes |
| `Xilinx_RF1761` | 1760 | — | — | — | code-only |
| `Xilinx_RF1930` | 1924 | — | — | — | code-only; 1924 pads |
| `Xilinx_RF676` | 676 | — | — | — | code-only |
| `Xilinx_RF900` | 900 | — | — | — | code-only |
| `Xilinx_RFG676` | 676 | — | — | — | code-only |
| `Xilinx_RS484` | 484 | — | — | — | code-only |
| `Xilinx_SBG484` | 484 | — | — | — | code-only |
| `Xilinx_SBG485` | 484 | — | — | — | code-only; 484 pads |

### Table 2 — `Package_CSP.pretty` (179 footprints, complete)

Rows whose name starts `LFCSP` (68 files incl. `Analog_LFCSP*`) are **perimeter leadless, not grid arrays** — QFN grammar, no Layout token. "Pads in file" includes the exposed pad(s) and any thermal vias, which is why an `-1EP` part shows n+1.

| Verbatim footprint name | Pads in file | Body mm | Layout | Pitch mm | Modifiers |
|---|---|---|---|---|---|
| `Analog_LFCSP-16-1EP_4x4mm_P0.65mm_EP2.1x2.1mm` | 17 | 4x4 | — | 0.65 | EP2.1x2.1 |
| `Analog_LFCSP-16-1EP_4x4mm_P0.65mm_EP2.1x2.1mm_ThermalVias` | 17 | 4x4 | — | 0.65 | EP2.1x2.1, ThermalVias |
| `Analog_LFCSP-16-1EP_4x4mm_P0.65mm_EP2.35x2.35mm` | 17 | 4x4 | — | 0.65 | EP2.35x2.35 |
| `Analog_LFCSP-16-1EP_4x4mm_P0.65mm_EP2.35x2.35mm_ThermalVias` | 17 | 4x4 | — | 0.65 | EP2.35x2.35, ThermalVias |
| `Analog_LFCSP-8-1EP_3x3mm_P0.5mm_EP1.53x1.85mm` | 5 | 3x3 | — | 0.5 | EP1.53x1.85 |
| `Analog_LFCSP-UQ-10_1.3x1.6mm_P0.4mm` | 10 | 1.3x1.6 | — | 0.4 | UQ thermal variant |
| `Anpec_WLCSP-20_1.76x2.03mm_Layout4x5_P0.4mm` | 20 | 1.76x2.03 | 4x5 | 0.4 | — |
| `Dialog_WLCSP-34_4.54x1.66mm_Layout17x4_P0.25x0.34mm` | 34 | 4.54x1.66 | 17x4 | 0.25x0.34 | staggered array |
| `DiodesInc_GEA20_WLCSP-20_1.7x2.1mm_Layout4x5_P0.4mm` | 20 | 1.7x2.1 | 4x5 | 0.4 | — |
| `Efinix_WLCSP-64_3.5353x3.3753mm_Layout8x8_P0.4mm` | 64 | 3.5353x3.3753 | 8x8 | 0.4 | — |
| `Efinix_WLCSP-80_4.4567x3.5569mm_Layout10x8_P0.4mm` | 80 | 4.4567x3.5569 | 10x8 | 0.4 | — |
| `LFCSP-10_2x2mm_P0.5mm` | 10 | 2x2 | — | 0.5 | — |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.3x1.3mm` | 17 | 3x3 | — | 0.5 | EP1.3x1.3 |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.3x1.3mm_ThermalVias` | 17 | 3x3 | — | 0.5 | EP1.3x1.3, ThermalVias |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.5x1.5mm` | 17 | 3x3 | — | 0.5 | EP1.5x1.5 |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm` | 17 | 3x3 | — | 0.5 | EP1.6x1.6 |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias` | 17 | 3x3 | — | 0.5 | EP1.6x1.6, ThermalVias |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm` | 17 | 3x3 | — | 0.5 | EP1.7x1.7 |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm_ThermalVias` | 17 | 3x3 | — | 0.5 | EP1.7x1.7, ThermalVias |
| `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.854x1.854mm` | 17 | 3x3 | — | 0.5 | EP1.854x1.854 |
| `LFCSP-16-1EP_4x4mm_P0.65mm_EP2.1x2.1mm` | 17 | 4x4 | — | 0.65 | EP2.1x2.1 |
| `LFCSP-16-1EP_4x4mm_P0.65mm_EP2.4x2.4mm` | 17 | 4x4 | — | 0.65 | EP2.4x2.4 |
| `LFCSP-16-1EP_4x4mm_P0.65mm_EP2.4x2.4mm_ThermalVias` | 17 | 4x4 | — | 0.65 | EP2.4x2.4, ThermalVias |
| `LFCSP-16-1EP_4x4mm_P0.65mm_EP2.6x2.6mm` | 17 | 4x4 | — | 0.65 | EP2.6x2.6 |
| `LFCSP-16-1EP_4x4mm_P0.65mm_EP2.6x2.6mm_ThermalVias` | 17 | 4x4 | — | 0.65 | EP2.6x2.6, ThermalVias |
| `LFCSP-16_3x3mm_P0.5mm` | 16 | 3x3 | — | 0.5 | no EP |
| `LFCSP-20-1EP_4x4mm_P0.5mm_EP2.1x2.1mm` | 21 | 4x4 | — | 0.5 | EP2.1x2.1 |
| `LFCSP-20-1EP_4x4mm_P0.5mm_EP2.1x2.1mm_ThermalVias` | 21 | 4x4 | — | 0.5 | EP2.1x2.1, ThermalVias |
| `LFCSP-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm` | 21 | 4x4 | — | 0.5 | EP2.5x2.5 |
| `LFCSP-20-1EP_4x4mm_P0.5mm_EP2.5x2.5mm_ThermalVias` | 21 | 4x4 | — | 0.5 | EP2.5x2.5, ThermalVias |
| `LFCSP-20-1EP_4x4mm_P0.5mm_EP2.6x2.6mm` | 21 | 4x4 | — | 0.5 | EP2.6x2.6 |
| `LFCSP-20-1EP_4x4mm_P0.5mm_EP2.6x2.6mm_ThermalVias` | 21 | 4x4 | — | 0.5 | EP2.6x2.6, ThermalVias |
| `LFCSP-24-1EP_4x4mm_P0.5mm_EP0.5x0.5mm` | 25 | 4x4 | — | 0.5 | EP0.5x0.5 |
| `LFCSP-24-1EP_4x4mm_P0.5mm_EP2.3x2.3mm` | 25 | 4x4 | — | 0.5 | EP2.3x2.3 |
| `LFCSP-24-1EP_4x4mm_P0.5mm_EP2.3x2.3mm_ThermalVias` | 25 | 4x4 | — | 0.5 | EP2.3x2.3, ThermalVias |
| `LFCSP-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm` | 25 | 4x4 | — | 0.5 | EP2.5x2.5 |
| `LFCSP-24-1EP_4x4mm_P0.5mm_EP2.5x2.5mm_ThermalVias` | 25 | 4x4 | — | 0.5 | EP2.5x2.5, ThermalVias |
| `LFCSP-28-1EP_5x5mm_P0.5mm_EP3.14x3.14mm` | 29 | 5x5 | — | 0.5 | EP3.14x3.14 |
| `LFCSP-28-1EP_5x5mm_P0.5mm_EP3.14x3.14mm_ThermalVias` | 29 | 5x5 | — | 0.5 | EP3.14x3.14, ThermalVias |
| `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm` | 33 | 5x5 | — | 0.5 | EP3.1x3.1 |
| `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.1x3.1mm_ThermalVias` | 33 | 5x5 | — | 0.5 | EP3.1x3.1, ThermalVias |
| `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.25x3.25mm` | 33 | 5x5 | — | 0.5 | EP3.25x3.25 |
| `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm` | 33 | 5x5 | — | 0.5 | EP3.5x3.5 |
| `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm_ThermalVias` | 33 | 5x5 | — | 0.5 | EP3.5x3.5, ThermalVias |
| `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.6x3.6mm` | 33 | 5x5 | — | 0.5 | EP3.6x3.6 |
| `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.6x3.6mm_ThermalVias` | 33 | 5x5 | — | 0.5 | EP3.6x3.6, ThermalVias |
| `LFCSP-40-1EP_6x6mm_P0.5mm_EP3.9x3.9mm` | 41 | 6x6 | — | 0.5 | EP3.9x3.9 |
| `LFCSP-40-1EP_6x6mm_P0.5mm_EP3.9x3.9mm_ThermalVias` | 41 | 6x6 | — | 0.5 | EP3.9x3.9, ThermalVias |
| `LFCSP-40-1EP_6x6mm_P0.5mm_EP4.65x4.65mm` | 41 | 6x6 | — | 0.5 | EP4.65x4.65 |
| `LFCSP-40-1EP_6x6mm_P0.5mm_EP4.65x4.65mm_ThermalVias` | 41 | 6x6 | — | 0.5 | EP4.65x4.65, ThermalVias |
| `LFCSP-40-1EP_6x6mm_P0.5mm_EP4.6x4.6mm` | 41 | 6x6 | — | 0.5 | EP4.6x4.6 |
| `LFCSP-40-1EP_6x6mm_P0.5mm_EP4.6x4.6mm_ThermalVias` | 41 | 6x6 | — | 0.5 | EP4.6x4.6, ThermalVias |
| `LFCSP-48-1EP_7x7mm_P0.5mm_EP4.1x4.1mm` | 49 | 7x7 | — | 0.5 | EP4.1x4.1 |
| `LFCSP-48-1EP_7x7mm_P0.5mm_EP4.1x4.1mm_ThermalVias` | 49 | 7x7 | — | 0.5 | EP4.1x4.1, ThermalVias |
| `LFCSP-56-1EP_8x8mm_P0.5mm_EP6.6x6.6mm` | 57 | 8x8 | — | 0.5 | EP6.6x6.6 |
| `LFCSP-56-1EP_8x8mm_P0.5mm_EP6.6x6.6mm_ThermalVias` | 57 | 8x8 | — | 0.5 | EP6.6x6.6, ThermalVias |
| `LFCSP-6-1EP_2x2mm_P0.65mm_EP1x1.6mm` | 7 | 2x2 | — | 0.65 | EP1x1.6 |
| `LFCSP-64-1EP_9x9mm_P0.5mm_EP5.21x5.21mm` | 65 | 9x9 | — | 0.5 | EP5.21x5.21 |
| `LFCSP-64-1EP_9x9mm_P0.5mm_EP5.21x5.21mm_ThermalVias` | 65 | 9x9 | — | 0.5 | EP5.21x5.21, ThermalVias |
| `LFCSP-72-1EP_10x10mm_P0.5mm_EP5.3x5.3mm` | 73 | 10x10 | — | 0.5 | EP5.3x5.3 |
| `LFCSP-72-1EP_10x10mm_P0.5mm_EP5.3x5.3mm_ThermalVias` | 73 | 10x10 | — | 0.5 | EP5.3x5.3, ThermalVias |
| `LFCSP-72-1EP_10x10mm_P0.5mm_EP6.15x6.15mm` | 73 | 10x10 | — | 0.5 | EP6.15x6.15 |
| `LFCSP-8-1EP_3x2mm_P0.5mm_EP1.6x1.65mm` | 9 | 3x2 | — | 0.5 | EP1.6x1.65 |
| `LFCSP-8-1EP_3x3mm_P0.5mm_EP1.45x1.74mm` | 9 | 3x3 | — | 0.5 | EP1.45x1.74 |
| `LFCSP-8-1EP_3x3mm_P0.5mm_EP1.6x2.34mm` | 9 | 3x3 | — | 0.5 | EP1.6x2.34 |
| `LFCSP-8-1EP_3x3mm_P0.5mm_EP1.6x2.34mm_ThermalVias` | 9 | 3x3 | — | 0.5 | EP1.6x2.34, ThermalVias |
| `LFCSP-8_2x2mm_P0.5mm` | 8 | 2x2 | — | 0.5 | no EP |
| `LFCSP-VQ-24-1EP_4x4mm_P0.5mm_EP2.642x2.642mm` | 25 | 4x4 | — | 0.5 | VQ, EP2.642x2.642 |
| `LFCSP-VQ-48-1EP_7x7mm_P0.5mm` | 49 | 7x7 | — | 0.5 | VQ, EP size omitted |
| `LFCSP-WD-10-1EP_3x3mm_P0.5mm_EP1.64x2.38mm` | 11 | 3x3 | — | 0.5 | WD, EP1.64x2.38 |
| `LFCSP-WD-10-1EP_3x3mm_P0.5mm_EP1.64x2.38mm_ThermalVias` | 11 | 3x3 | — | 0.5 | WD, EP1.64x2.38, ThermalVias |
| `LFCSP-WD-8-1EP_3x3mm_P0.65mm_EP1.6x2.44mm` | 9 | 3x3 | — | 0.65 | WD, EP1.6x2.44 |
| `LFCSP-WD-8-1EP_3x3mm_P0.65mm_EP1.6x2.44mm_ThermalVias` | 9 | 3x3 | — | 0.65 | WD, EP1.6x2.44, ThermalVias |
| `Macronix_WLCSP-12_2.02x2.09mm_Layout4x4_P0.5mm` | 12 | 2.02x2.09 | 4x4 | 0.5 | — |
| `Maxim_WLCSP-35_2.998x2.168mm_Layout7x5_P0.4mm` | 35 | 2.998x2.168 | 7x5 | 0.4 | — |
| `Nexperia_WLCSP-15_2.37x1.17mm_Layout6x3_P0.4mmP0.8mm` | 15 | 2.37x1.17 | 6x3 | 0.4 + 0.8 | 6-3-6 bump rows |
| `NXP_SOT1444-5_WLCSP-49_3.44x3.44mm_Layout7x7_P0.4mm` | 49 | 3.44x3.44 | 7x7 | 0.4 | — |
| `NXP_SOT1450-2_WLCSP-100_5.07x5.07mm_Layout10x10_P0.5mm` | 100 | 5.07x5.07 | 10x10 | 0.5 | — |
| `OnSemi_ODCSP36_BGA-36_6.13x6.13mm_Layout6x6_P1.0mm` | 36 | 6.13x6.13 | 6x6 | 1.0 | — |
| `OnSemi_ODCSP36_BGA-36_6.13x6.13mm_Layout6x6_P1.0mm_ManualAssembly` | 36 | 6.13x6.13 | 6x6 | 1.0 | ManualAssembly |
| `OnSemi_ODCSP8_BGA-8_3.16x3.16mm_Layout3x3_P1.26mm` | 8 | 3.16x3.16 | 3x3 | 1.26 | — |
| `OnSemi_ODCSP8_BGA-8_3.16x3.16mm_Layout3x3_P1.26mm_ManualAssembly` | 8 | 3.16x3.16 | 3x3 | 1.26 | ManualAssembly |
| `pSemi_CSP-16_1.64x2.04mm_P0.4mm` | 16 | 1.64x2.04 | — | 0.4 | — |
| `pSemi_CSP-16_1.64x2.04mm_P0.4mm_Pad0.18mm` | 16 | 1.64x2.04 | — | 0.4 | Pad0.18 variant |
| `ST_WLCSP-100_4.437x4.456mm_Layout10x10_P0.4mm` | 100 | 4.437x4.456 | 10x10 | 0.4 | — |
| `ST_WLCSP-100_4.4x4.38mm_Layout10x10_P0.4mm_Offcenter` | 100 | 4.4x4.38 | 10x10 | 0.4 | Offcenter |
| `ST_WLCSP-100_Die422` | 100 | — | — | — | Die422 (legacy) |
| `ST_WLCSP-100_Die446` | 100 | — | — | — | Die446 (legacy) |
| `ST_WLCSP-100_Die452` | 100 | — | — | — | Die452 (legacy) |
| `ST_WLCSP-100_Die461` | 100 | — | — | — | Die461 (legacy) |
| `ST_WLCSP-101_3.86x3.79mm_Layout11x19_P0.35mm_Stagger` | 101 | 3.86x3.79 | 11x19 | 0.35 | Stagger |
| `ST_WLCSP-104_Die437` | 104 | — | — | — | Die437 (legacy) |
| `ST_WLCSP-115_3.73x4.15mm_Layout11x21_P0.35mm_Stagger` | 115 | 3.73x4.15 | 11x21 | 0.35 | Stagger |
| `ST_WLCSP-115_4.63x4.15mm_Layout21x11_P0.4mm_Stagger` | 115 | 4.63x4.15 | 21x11 | 0.4 | Stagger |
| `ST_WLCSP-12_1.7x1.42mm_Layout4x6_P0.35mm_Stagger` | 12 | 1.7x1.42 | 4x6 | 0.35 | Stagger |
| `ST_WLCSP-132_4.57x4.37mm_Layout12x11_P0.35mm` | 132 | 4.57x4.37 | 12x11 | 0.35 | — |
| `ST_WLCSP-143_Die419` | 143 | — | — | — | Die419 (legacy) |
| `ST_WLCSP-143_Die449` | 143 | — | — | — | Die449 (legacy) |
| `ST_WLCSP-144_Die470` | 144 | — | — | — | Die470 (legacy) |
| `ST_WLCSP-150_5.38x5.47mm_Layout13x23_P0.4mm_Stagger` | 150 | 5.38x5.47 | 13x23 | 0.4 | Stagger |
| `ST_WLCSP-156_4.96x4.64mm_Layout13x12_P0.35mm` | 156 | 4.96x4.64 | 13x12 | 0.35 | — |
| `ST_WLCSP-168_Die434` | 168 | — | — | — | Die434 (legacy) |
| `ST_WLCSP-180_Die451` | 180 | — | — | — | Die451 (legacy) |
| `ST_WLCSP-18_1.86x2.14mm_Layout7x5_P0.4mm_Stagger` | 18 | 1.86x2.14 | 7x5 | 0.4 | Stagger |
| `ST_WLCSP-19_1.643x2.492mm_Layout4x11_P0.35mm_Stagger` | 19 | 1.643x2.492 | 4x11 | 0.35 | Stagger |
| `ST_WLCSP-208_5.38x5.47mm_Layout26x16_P0.35mm_Stagger` | 208 | 5.38x5.47 | 26x16 | 0.35 | Stagger |
| `ST_WLCSP-208_5.8x5.6mm_Layout26x16_P0.35mm_Stagger` | 208 | 5.8x5.6 | 26x16 | 0.35 | Stagger |
| `ST_WLCSP-20_1.94x2.4mm_Layout4x5_P0.4mm` | 20 | 1.94x2.4 | 4x5 | 0.4 | — |
| `ST_WLCSP-25_2.33x2.24mm_Layout5x5_P0.4mm` | 25 | 2.33x2.24 | 5x5 | 0.4 | — |
| `ST_WLCSP-25_2.3x2.48mm_Layout5x5_P0.4mm` | 25 | 2.3x2.48 | 5x5 | 0.4 | — |
| `ST_WLCSP-25_Die425` | 25 | — | — | — | Die425 (legacy) |
| `ST_WLCSP-25_Die444` | 25 | — | — | — | Die444 (legacy) |
| `ST_WLCSP-25_Die457` | 25 | — | — | — | Die457 (legacy) |
| `ST_WLCSP-27_2.34x2.55mm_Layout9x6_P0.4mm_Stagger` | 27 | 2.34x2.55 | 9x6 | 0.4 | Stagger |
| `ST_WLCSP-36_2.58x3.07mm_Layout6x6_P0.4mm` | 36 | 2.58x3.07 | 6x6 | 0.4 | — |
| `ST_WLCSP-36_2.652x2.592mm_Layout7x12_P0.4mm_Stagger_Offcenter` | 36 | 2.652x2.592 | 7x12 | 0.4 | Stagger, Offcenter |
| `ST_WLCSP-36_2.83x2.99mm_Layout7x13_P0.4mm_Stagger_Offcenter` | 36 | 2.83x2.99 | 7x13 | 0.4 | Stagger, Offcenter |
| `ST_WLCSP-36_Die417` | 36 | — | — | — | Die417 (legacy) |
| `ST_WLCSP-36_Die440` | 36 | — | — | — | Die440 (legacy) |
| `ST_WLCSP-36_Die445` | 36 | — | — | — | Die445 (legacy) |
| `ST_WLCSP-36_Die458` | 36 | — | — | — | Die458 (legacy) |
| `ST_WLCSP-39_2.76x2.78mm_Layout11x7_P0.4mm_Stagger` | 39 | 2.76x2.78 | 11x7 | 0.4 | Stagger |
| `ST_WLCSP-41_2.98x2.76mm_Layout13x7_P0.4mm_Stagger` | 41 | 2.98x2.76 | 13x7 | 0.4 | Stagger |
| `ST_WLCSP-42_2.93x2.82mm_Layout12x7_P0.4mm_Stagger` | 42 | 2.93x2.82 | 12x7 | 0.4 | Stagger |
| `ST_WLCSP-49_3.14x3.14mm_Layout7x7_P0.4mm_Offcenter` | 49 | 3.14x3.14 | 7x7 | 0.4 | Offcenter |
| `ST_WLCSP-49_3.15x3.13mm_Layout7x7_P0.4mm` | 49 | 3.15x3.13 | 7x7 | 0.4 | — |
| `ST_WLCSP-49_3.3x3.38mm_Layout7x7_P0.4mm_Offcenter` | 49 | 3.3x3.38 | 7x7 | 0.4 | Offcenter |
| `ST_WLCSP-49_Die423` | 49 | — | — | — | Die423 (legacy) |
| `ST_WLCSP-49_Die431` | 49 | — | — | — | Die431 (legacy) |
| `ST_WLCSP-49_Die433` | 49 | — | — | — | Die433 (legacy) |
| `ST_WLCSP-49_Die435` | 49 | — | — | — | Die435 (legacy) |
| `ST_WLCSP-49_Die438` | 49 | — | — | — | Die438 (legacy) |
| `ST_WLCSP-49_Die439` | 49 | — | — | — | Die439 (legacy) |
| `ST_WLCSP-49_Die447` | 49 | — | — | — | Die447 (legacy) |
| `ST_WLCSP-49_Die448` | 49 | — | — | — | Die448 (legacy) |
| `ST_WLCSP-52_3.09x3.15mm_Layout13x8_P0.4mm_Stagger` | 52 | 3.09x3.15 | 13x8 | 0.4 | Stagger |
| `ST_WLCSP-56_3.38x3.38mm_Layout14x8_P0.4mm_Stagger` | 56 | 3.38x3.38 | 14x8 | 0.4 | Stagger |
| `ST_WLCSP-63_Die427` | 63 | — | — | — | Die427 (legacy) |
| `ST_WLCSP-64_3.56x3.52mm_Layout8x8_P0.4mm` | 64 | 3.56x3.52 | 8x8 | 0.4 | — |
| `ST_WLCSP-64_Die414` | 64 | — | — | — | Die414 (legacy) |
| `ST_WLCSP-64_Die427` | 64 | — | — | — | Die427 (legacy) |
| `ST_WLCSP-64_Die435` | 64 | — | — | — | Die435 (legacy) |
| `ST_WLCSP-64_Die436` | 64 | — | — | — | Die436 (legacy) |
| `ST_WLCSP-64_Die441` | 64 | — | — | — | Die441 (legacy) |
| `ST_WLCSP-64_Die442` | 64 | — | — | — | Die442 (legacy) |
| `ST_WLCSP-64_Die462` | 64 | — | — | — | Die462 (legacy) |
| `ST_WLCSP-66_Die411` | 66 | — | — | — | Die411 (legacy) |
| `ST_WLCSP-66_Die432` | 66 | — | — | — | Die432 (legacy) |
| `ST_WLCSP-72_3.38x3.38mm_Layout16x9_P0.35mm_Stagger` | 72 | 3.38x3.38 | 16x9 | 0.35 | Stagger |
| `ST_WLCSP-72_Die415` | 72 | — | — | — | Die415 (legacy) |
| `ST_WLCSP-80_3.5x3.27mm_Layout10x16_P0.35mm_Stagger_Offcenter` | 80 | 3.5x3.27 | 10x16 | 0.35 | Stagger, Offcenter |
| `ST_WLCSP-81_4.02x4.27mm_Layout9x9_P0.4mm` | 81 | 4.02x4.27 | 9x9 | 0.4 | — |
| `ST_WLCSP-81_4.36x4.07mm_Layout9x9_P0.4mm` | 81 | 4.36x4.07 | 9x9 | 0.4 | — |
| `ST_WLCSP-81_Die415` | 81 | — | — | — | Die415 (legacy) |
| `ST_WLCSP-81_Die421` | 81 | — | — | — | Die421 (legacy) |
| `ST_WLCSP-81_Die463` | 81 | — | — | — | Die463 (legacy) |
| `ST_WLCSP-90_4.2x3.95mm_Layout18x10_P0.4mm_Stagger` | 90 | 4.2x3.95 | 18x10 | 0.4 | Stagger |
| `ST_WLCSP-90_Die413` | 90 | — | — | — | Die413 (legacy) |
| `ST_WLCSP-99_4.42x3.77mm_Layout11x9_P0.35mm` | 99 | 4.42x3.77 | 11x9 | 0.35 | — |
| `WLCSP-12_1.403x1.555mm_Layout6x4_P0.4mm_Stagger` | 12 | 1.403x1.555 | 6x4 | 0.4 | Stagger |
| `WLCSP-12_1.56x1.56mm_P0.4mm` | 12 | 1.56x1.56 | — | 0.4 | legacy: no Layout |
| `WLCSP-16_1.409x1.409mm_Layout4x4_P0.35mm` | 16 | 1.409x1.409 | 4x4 | 0.35 | — |
| `WLCSP-16_2.225x2.17mm_Layout4x4_P0.5mm` | 16 | 2.225x2.17 | 4x4 | 0.5 | — |
| `WLCSP-16_4x4_B2.17x2.32mm_P0.5mm` | 16 | B2.17x2.32 | 4x4 (bare) | 0.5 | `B`-prefixed body |
| `WLCSP-20_1.934x2.434mm_Layout4x5_P0.4mm` | 20 | 1.934x2.434 | 4x5 | 0.4 | — |
| `WLCSP-20_1.994x1.609mm_Layout5x4_P0.4mm` | 20 | 1.994x1.609 | 5x4 | 0.4 | — |
| `WLCSP-20_1.994x1.94mm_Layout4x5_P0.4mm` | 20 | 1.994x1.94 | 4x5 | 0.4 | — |
| `WLCSP-36_2.374x2.459mm_Layout6x6_P0.35mm` | 36 | 2.374x2.459 | 6x6 | 0.35 | — |
| `WLCSP-36_2.82x2.67mm_Layout6x6_P0.4mm` | 36 | 2.82x2.67 | 6x6 | 0.4 | — |
| `WLCSP-4_0.64x0.64mm_Layout2x2_P0.35mm` | 4 | 0.64x0.64 | 2x2 | 0.35 | — |
| `WLCSP-4_0.89x0.89mm_Layout2x2_P0.5mm` | 4 | 0.89x0.89 | 2x2 | 0.5 | — |
| `WLCSP-56_3.170x3.444mm_Layout7x8_P0.4mm` | 56 | 3.170x3.444 | 7x8 | 0.4 | trailing-zero body |
| `WLCSP-6_1.46x1.1mm_Layout3x2_P0.4mm` | 6 | 1.46x1.1 | 3x2 | 0.4 | — |
| `WLCSP-6_1.4x1.0mm_P0.4mm` | 6 | 1.4x1.0 | — | 0.4 | legacy: no Layout |
| `WLCSP-81_4.41x3.76mm_P0.4mm` | 81 | 4.41x3.76 | — | 0.4 | legacy: no Layout |
| `WLCSP-8_1.551x2.284mm_Layout2x4_P0.5mm` | 8 | 1.551x2.284 | 2x4 | 0.5 | — |
| `WLCSP-8_1.58x1.63x0.35mm_Layout3x5_P0.35x0.4mm_Ball0.25mm_Pad0.25mm_NSMD` | 8 | 1.58x1.63x0.35 | 3x5 | 0.35x0.4 | 3-number body, Ball0.25/Pad0.25, NSMD |
| `WLCSP-9_1.21x1.22mm_Layout3x3_P0.4mm` | 9 | 1.21x1.22 | 3x3 | 0.4 | — |
| `Xilinx_CSG48_7.0x7.0mm_Layout7x7_P0.8mm` | 48 | 7.0x7.0 | 7x7 | 0.8 | only Xilinx part outside Package_BGA |

### Table 3 — `Package_LGA.pretty` (41 footprints, complete)

| Verbatim footprint name | Pads in file | Body mm | Layout | Pitch mm | Modifiers |
|---|---|---|---|---|---|
| `AMS_LGA-10-1EP_2.7x4mm_P0.6mm` | 11 | 2.7x4 | — | 0.6 | 1EP, size omitted |
| `AMS_LGA-20_4.7x4.5mm_P0.65mm` | 20 | 4.7x4.5 | — | 0.65 | — |
| `AMS_OLGA-8_2x3.1mm_P0.8mm` | 8 | 2x3.1 | — | 0.8 | OLGA |
| `Bosch_LGA-14_3x2.5mm_P0.5mm` | 14 | 3x2.5 | — | 0.5 | — |
| `Bosch_LGA-16_4.5x3mm_P0.5mm_LayoutBorder7x1y_ClockwisePinNumbering` | 16 | 4.5x3 | Border 7x1y | 0.5 | clockwise numbering |
| `Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering` | 8 | 2.5x2.5 | — | 0.65 | clockwise numbering |
| `Bosch_LGA-8_2x2.5mm_P0.65mm_ClockwisePinNumbering` | 8 | 2x2.5 | — | 0.65 | clockwise numbering |
| `Bosch_LGA-8_3x3mm_P0.8mm_ClockwisePinNumbering` | 8 | 3x3 | — | 0.8 | clockwise numbering |
| `Infineon_PG-TSNP-6-10_0.7x1.1mm_0.7x1.1mm_P0.4mm` | 6 | 0.7x1.1 (twice) | — | 0.4 | body size duplicated |
| `Kionix_LGA-12_2x2mm_P0.5mm_LayoutBorder2x4y` | 12 | 2x2 | Border 2x4y | 0.5 | — |
| `LGA-12_2x2mm_P0.5mm` | 12 | 2x2 | — | 0.5 | — |
| `LGA-14_2x2mm_P0.35mm_LayoutBorder3x4y` | 14 | 2x2 | Border 3x4y | 0.35 | — |
| `LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y` | 14 | 3x2.5 | Border 3x4y | 0.5 | — |
| `LGA-14_3x5mm_P0.8mm_LayoutBorder1x6y` | 14 | 3x5 | Border 1x6y | 0.8 | — |
| `LGA-16_3x3mm_P0.5mm` | 16 | 3x3 | — | 0.5 | near-twin of the row below |
| `LGA-16_3x3mm_P0.5mm_LayoutBorder3x5y` | 16 | 3x3 | Border 3x5y | 0.5 | near-twin of the row above |
| `LGA-16_4x4mm_P0.65mm_LayoutBorder4x4y` | 16 | 4x4 | Border 4x4y | 0.65 | — |
| `LGA-24L_3x3.5mm_P0.43mm` | 24 | 3x3.5 | — | 0.43 | `L` suffix on pin count |
| `LGA-28_5.2x3.8mm_P0.5mm` | 28 | 5.2x3.8 | — | 0.5 | — |
| `LGA-8_3x5mm_P1.25mm` | 8 | 3x5 | — | 1.25 | — |
| `LGA-8_8x6.2mm_P1.27mm` | 8 | 8x6.2 | — | 1.27 | — |
| `LGA-8_8x6mm_P1.27mm` | 8 | 8x6 | — | 1.27 | — |
| `Linear_LGA-133_15.0x15.0mm_Layout12x12_P1.27mm` | 133 | 15.0x15.0 | 12x12 | 1.27 | µModule; BGA twin has 134 pads |
| `MPS_LGA-18-10EP_12x12mm_P3.3mm` | 18 | 12x12 | — | 3.3 | 10EP |
| `Nordic_nRF9151-LAxx_LGA-80-33EP_12.1x11.1mm_P0.5mm` | 113 | 12.1x11.1 | — | 0.5 | 33EP; SiP named geometrically |
| `Nordic_nRF9160-SIxx_LGA-102-59EP_16.0x10.5mm_P0.5mm` | 127 | 16.0x10.5 | — | 0.5 | 59EP; SiP named geometrically |
| `NXP_LGA-8_3x5mm_P1.25mm_H1.1mm` | 8 | 3x5 | — | 1.25 | H1.1 |
| `NXP_LGA-8_3x5mm_P1.25mm_H1.2mm` | 8 | 3x5 | — | 1.25 | H1.2 |
| `NXP_USON-8_1x1.35mm_P0.35mm` | 8 | 1x1.35 | — | 0.35 | USON |
| `Rohm_MLGA010V020A_LGA-10_2x2mm_P0.45mm_LayoutBorder2x3y` | 10 | 2x2 | Border 2x3y | 0.45 | vendor code + generic |
| `ST_CCLGA-7L_2.8x2.8mm_P1.15mm_H1.95mm` | 7 | 2.8x2.8 | — | 1.15 | CCLGA, `7L`, H1.95 |
| `ST_HLGA-10_2.5x2.5mm_P0.6mm_LayoutBorder3x2y` | 10 | 2.5x2.5 | Border 3x2y | 0.6 | HLGA |
| `ST_HLGA-10_2x2mm_P0.5mm_LayoutBorder3x2y` | 10 | 2x2 | Border 3x2y | 0.5 | HLGA |
| `Texas_SIL0008C_MicroSiP-8-1EP_2.8x3mm_P0.65mm_EP1.1x1.9mm` | 9 | 2.8x3 | — | 0.65 | EP1.1x1.9 |
| `Texas_SIL0008C_MicroSiP-8-1EP_2.8x3mm_P0.65mm_EP1.1x1.9mm_ThermalVias` | 9 | 2.8x3 | — | 0.65 | EP1.1x1.9, ThermalVias |
| `Texas_SIL0008D_MicroSiP-8-1EP_2.8x3mm_P0.65mm_EP1.1x1.9mm` | 9 | 2.8x3 | — | 0.65 | EP1.1x1.9 |
| `Texas_SIL0008D_MicroSiP-8-1EP_2.8x3mm_P0.65mm_EP1.1x1.9mm_ThermalVias` | 9 | 2.8x3 | — | 0.65 | EP1.1x1.9, ThermalVias |
| `Texas_SIL0010A_MicroSiP-10-1EP_3.8x3mm_P0.6mm_EP0.7x2.9mm` | 11 | 3.8x3 | — | 0.6 | EP0.7x2.9 |
| `Texas_SIL0010A_MicroSiP-10-1EP_3.8x3mm_P0.6mm_EP0.7x2.9mm_ThermalVias` | 11 | 3.8x3 | — | 0.6 | EP0.7x2.9, ThermalVias |
| `ublox_LGA-53_4.5x4.5mm_Layout9x9_P0.5mm` | 53 | 4.5x4.5 | 9x9 | 0.5 | MIA-M10Q GNSS module, named geometrically |
| `VLGA-4_2x2.5mm_P1.65mm` | 4 | 2x2.5 | — | 1.65 | VLGA |

### Table 4 — modules: `RF_Module` + `RF_GPS` + `RF_GSM` + `RF_WiFi` + `Module` (144 footprints, complete)

Every row is a product name. "Sizes" = number of distinct pad sizes in the file; "NPTH" = non-plated mounting holes; "Geo?" = does the filename contain any geometric or package token (only 6 do).

| Verbatim footprint name | Library | Named pads | NPTH | Sizes | Geo? |
|---|---|---|---|---|---|
| `Ai-Thinker-Ra-01-LoRa` | RF_Module | 16 | 0 | 1 | no |
| `Astrocast_AST50147-00` | RF_Module | 38 | 0 | 1 | no |
| `Atmel_ATSAMR21G18-MR210UA_NoRFPads` | RF_Module | 42 | 0 | 2 | no |
| `BLE112-A` | RF_Module | 30 | 0 | 1 | no |
| `BM78SPPS5xC2` | RF_Module | 33 | 0 | 1 | no |
| `CMWX1ZZABZ` | RF_Module | 57 | 0 | 2 | no |
| `CYBLE-21Pin-10x10mm` | RF_Module | 21 | 0 | 2 | **yes** |
| `DecaWave_DWM1001` | RF_Module | 34 | 1 | 2 | no |
| `Digi_XBee_SMT` | RF_Module | 37 | 0 | 1 | no |
| `DWM1000` | RF_Module | 24 | 0 | 1 | no |
| `E18-MS1-PCB` | RF_Module | 24 | 0 | 1 | no |
| `E73-2G4M04S` | RF_Module | 44 | 0 | 2 | no |
| `ESP-01` | RF_Module | 8 | 0 | 1 | no |
| `ESP-07` | RF_Module | 16 | 0 | 1 | no |
| `ESP-12E` | RF_Module | 22 | 0 | 2 | no |
| `ESP-WROOM-02` | RF_Module | 19 | 0 | 2 | no |
| `ESP32-C3-DevKitM-1` | RF_Module | 30 | 0 | 1 | no |
| `ESP32-C3-WROOM-02` | RF_Module | 19 | 0 | 4 | no |
| `ESP32-C3-WROOM-02U` | RF_Module | 19 | 0 | 4 | no |
| `ESP32-C6-MINI-1` | RF_Module | 53 | 0 | 3 | no |
| `ESP32-S2-MINI-1` | RF_Module | 65 | 0 | 3 | no |
| `ESP32-S2-MINI-1U` | RF_Module | 65 | 0 | 3 | no |
| `ESP32-S2-WROVER` | RF_Module | 43 | 0 | 4 | no |
| `ESP32-S3-WROOM-1` | RF_Module | 41 | 0 | 4 | no |
| `ESP32-S3-WROOM-1U` | RF_Module | 41 | 0 | 4 | no |
| `ESP32-S3-WROOM-2` | RF_Module | 41 | 0 | 3 | no |
| `ESP32-WROOM-32` | RF_Module | 39 | 0 | 4 | no |
| `ESP32-WROOM-32D` | RF_Module | 39 | 0 | 4 | no |
| `ESP32-WROOM-32E` | RF_Module | 39 | 0 | 3 | no |
| `ESP32-WROOM-32U` | RF_Module | 39 | 0 | 4 | no |
| `ESP32-WROOM-32UE` | RF_Module | 39 | 0 | 4 | no |
| `Garmin_M8-35_9.8x14.0mm_Layout6x6_P1.5mm` | RF_Module | 35 | 0 | 1 | **yes** |
| `Heltec_HT-CT62` | RF_Module | 22 | 0 | 1 | no |
| `HOPERF_RFM69HW` | RF_Module | 16 | 0 | 1 | no |
| `HOPERF_RFM9XW_SMD` | RF_Module | 16 | 0 | 1 | no |
| `HOPERF_RFM9XW_THT` | RF_Module | 16 | 0 | 1 | no |
| `IQRF_TRx2D_KON-SIM-01` | RF_Module | 8 | 0 | 2 | no |
| `IQRF_TRx2DA_KON-SIM-01` | RF_Module | 8 | 0 | 2 | no |
| `Jadak_Thingmagic_M6e-Nano` | RF_Module | 41 | 0 | 9 | no |
| `Laird_BL652` | RF_Module | 39 | 0 | 1 | no |
| `Laird_BL653` | RF_Module | 73 | 0 | 1 | no |
| `MCU_Seeed_ESP32C3` | RF_Module | 23 | 0 | 5 | no |
| `Microchip_BM83` | RF_Module | 52 | 0 | 4 | no |
| `Microchip_RN4871` | RF_Module | 16 | 0 | 1 | no |
| `MOD-nRF8001` | RF_Module | 11 | 0 | 1 | no |
| `Modtronix_inAir9` | RF_Module | 14 | 0 | 1 | no |
| `MonoWireless_TWE-L-WX` | RF_Module | 32 | 1 | 3 | no |
| `NINA-B111` | RF_Module | 42 | 0 | 2 | no |
| `nRF24L01_Breakout` | RF_Module | 8 | 0 | 1 | no |
| `Particle_P1` | RF_Module | 75 | 0 | 3 | no |
| `RAK3172` | RF_Module | 32 | 0 | 1 | no |
| `RAK4200` | RF_Module | 20 | 0 | 1 | no |
| `RAK811` | RF_Module | 34 | 0 | 2 | no |
| `Raytac_MDBT42Q` | RF_Module | 41 | 0 | 3 | no |
| `Raytac_MDBT50Q` | RF_Module | 61 | 0 | 1 | no |
| `RFDigital_RFD77101` | RF_Module | 45 | 0 | 2 | no |
| `RMC20452T` | RF_Module | 21 | 0 | 1 | no |
| `RN2483` | RF_Module | 47 | 0 | 1 | no |
| `RN42` | RF_Module | 33 | 0 | 2 | no |
| `RN42N` | RF_Module | 36 | 0 | 2 | no |
| `ST-SiP-LGA-86-11x7.3mm` | RF_Module | 86 | 0 | 5 | **yes** |
| `ST_SPBTLE` | RF_Module | 11 | 0 | 1 | no |
| `Taiyo-Yuden_EYSGJNZWY` | RF_Module | 28 | 0 | 6 | no |
| `TD1205` | RF_Module | 9 | 0 | 1 | no |
| `TD1208` | RF_Module | 25 | 0 | 1 | no |
| `WEMOS_C3_mini` | RF_Module | 16 | 2 | 3 | no |
| `WEMOS_D1_mini_light` | RF_Module | 16 | 0 | 2 | no |
| `ZETA-433-SO_SMD` | RF_Module | 12 | 0 | 1 | no |
| `ZETA-433-SO_THT` | RF_Module | 12 | 0 | 1 | no |
| `Linx_RXM-GPS` | RF_GPS | 22 | 0 | 2 | no |
| `OriginGPS_ORG1510` | RF_GPS | 11 | 0 | 5 | no |
| `Quectel_L70-R` | RF_GPS | 18 | 0 | 1 | no |
| `Quectel_L76` | RF_GPS | 18 | 0 | 1 | no |
| `Quectel_L80-R` | RF_GPS | 12 | 0 | 1 | no |
| `Quectel_L96` | RF_GPS | 31 | 0 | 1 | no |
| `Sierra_XA11X0` | RF_GPS | 24 | 0 | 2 | no |
| `Sierra_XM11X0` | RF_GPS | 20 | 0 | 2 | no |
| `SIM28ML` | RF_GPS | 18 | 0 | 1 | no |
| `ublox_LEA` | RF_GPS | 28 | 0 | 1 | no |
| `ublox_MAX` | RF_GPS | 18 | 0 | 2 | no |
| `ublox_NEO` | RF_GPS | 24 | 0 | 1 | no |
| `ublox_SAM-M8Q` | RF_GPS | 20 | 0 | 4 | no |
| `ublox_SAM-M8Q_HandSolder` | RF_GPS | 20 | 0 | 2 | no |
| `ublox_ZED` | RF_GPS | 55 | 0 | 2 | no |
| `ublox_ZOE_M8` | RF_GPS | 51 | 0 | 1 | no |
| `Quectel_BC66` | RF_GSM | 58 | 0 | 4 | no |
| `Quectel_BC95` | RF_GSM | 94 | 0 | 5 | no |
| `Quectel_BG95` | RF_GSM | 102 | 0 | 3 | no |
| `Quectel_BG96` | RF_GSM | 102 | 0 | 5 | no |
| `Quectel_M95` | RF_GSM | 42 | 0 | 4 | no |
| `SIMCom_SIM800C` | RF_GSM | 42 | 0 | 3 | no |
| `SIMCom_SIM900` | RF_GSM | 68 | 0 | 2 | no |
| `Telit_SE150A4` | RF_GSM | 210 | 0 | 3 | no |
| `Telit_xL865` | RF_GSM | 48 | 0 | 2 | no |
| `ublox_LENA-R8_LGA-100` | RF_GSM | 100 | 0 | 4 | **yes** |
| `ublox_SARA_LGA-96` | RF_GSM | 96 | 0 | 4 | **yes** |
| `USR-C322` | RF_WiFi | 44 | 0 | 1 | no |
| `A20_OLINUXINO_LIME2` | Module | 180 | 10 | 2 | no |
| `Adafruit_Feather` | Module | 28 | 0 | 1 | no |
| `Adafruit_Feather_32u4_FONA` | Module | 28 | 0 | 1 | no |
| `Adafruit_Feather_32u4_FONA_WithMountingHoles` | Module | 28 | 3 | 3 | no |
| `Adafruit_Feather_32u4_RFM` | Module | 31 | 0 | 1 | no |
| `Adafruit_Feather_32u4_RFM_WithMountingHoles` | Module | 31 | 4 | 3 | no |
| `Adafruit_Feather_M0_RFM` | Module | 32 | 0 | 1 | no |
| `Adafruit_Feather_M0_RFM_WithMountingHoles` | Module | 32 | 4 | 3 | no |
| `Adafruit_Feather_M0_Wifi` | Module | 28 | 0 | 1 | no |
| `Adafruit_Feather_M0_Wifi_WithMountingHoles` | Module | 28 | 4 | 3 | no |
| `Adafruit_Feather_WICED` | Module | 29 | 0 | 2 | no |
| `Adafruit_Feather_WICED_WithMountingHoles` | Module | 29 | 4 | 4 | no |
| `Adafruit_Feather_WithMountingHoles` | Module | 28 | 4 | 3 | no |
| `Adafruit_HUZZAH_ESP8266_breakout` | Module | 20 | 0 | 1 | no |
| `Adafruit_HUZZAH_ESP8266_breakout_WithMountingHoles` | Module | 20 | 4 | 2 | no |
| `Arduino_Nano` | Module | 30 | 0 | 1 | no |
| `Arduino_Nano_WithMountingHoles` | Module | 30 | 4 | 2 | no |
| `Arduino_UNO_R2` | Module | 30 | 0 | 1 | no |
| `Arduino_UNO_R2_WithMountingHoles` | Module | 30 | 4 | 2 | no |
| `Arduino_UNO_R3` | Module | 32 | 0 | 1 | no |
| `Arduino_UNO_R3_WithMountingHoles` | Module | 32 | 4 | 2 | no |
| `BeagleBoard_PocketBeagle` | Module | 72 | 0 | 1 | no |
| `Carambola2` | Module | 52 | 0 | 2 | no |
| `Electrosmith_Daisy_Seed` | Module | 40 | 0 | 1 | no |
| `Flipper_Zero_Angled` | Module | 18 | 0 | 1 | no |
| `Flipper_Zero_Straight` | Module | 18 | 0 | 1 | no |
| `Google_Coral_SMT_TPU_Module` | Module | 120 | 0 | 3 | no |
| `Maple_Mini` | Module | 40 | 0 | 1 | no |
| `Olimex_MOD-WIFI-ESP8266-DEV` | Module | 22 | 0 | 1 | no |
| `Onion_Omega2+` | Module | 32 | 0 | 1 | no |
| `Onion_Omega2S` | Module | 64 | 1 | 5 | no |
| `Pololu_Breakout-16_15.2x20.3mm` | Module | 16 | 0 | 1 | **yes** |
| `Raspberry_Pi_Zero_Socketed_THT_FaceDown_MountingHoles` | Module | 40 | 4 | 2 | no |
| `RaspberryPi_Pico_Common_SMD` | Module | 40 | 4 | 5 | no |
| `RaspberryPi_Pico_Common_THT` | Module | 40 | 0 | 1 | no |
| `RaspberryPi_Pico_Common_Unspecified` | Module | 40 | 4 | 5 | no |
| `RaspberryPi_Pico_SMD` | Module | 49 | 0 | 8 | no |
| `RaspberryPi_Pico_SMD_HandSolder` | Module | 43 | 4 | 7 | no |
| `RaspberryPi_Pico_W_SMD` | Module | 49 | 0 | 7 | no |
| `RaspberryPi_Pico_W_SMD_HandSolder` | Module | 43 | 4 | 6 | no |
| `Sipeed-M1` | Module | 72 | 0 | 6 | no |
| `Sipeed-M1W` | Module | 72 | 0 | 6 | no |
| `ST_Morpho_Connector_144_STLink` | Module | 148 | 0 | 1 | no |
| `ST_Morpho_Connector_144_STLink_MountingHoles` | Module | 148 | 5 | 2 | no |
| `Texas_EUK_R-PDSS-T7_THT` | Module | 7 | 0 | 1 | no |
| `Texas_EUS_R-PDSS-T5_THT` | Module | 5 | 0 | 1 | no |
| `Texas_EUW_R-PDSS-T7_THT` | Module | 7 | 0 | 1 | no |

## How to name a new part in this family

## Step 0 — The module-vs-geometric decision rule (mechanical, no judgement)

Open the datasheet's **recommended PCB land-pattern drawing** and run these four tests in order. The first test that fires decides it. Every test is a yes/no you can read off the drawing.

**Test 1 — DESCRIBABILITY.** Can you reproduce every land in the drawing using only these parameters, and nothing else?
- (a) a land count `n`;
- (b) one body size X × Y;
- (c) one pitch, or one X pitch plus one Y pitch, or two named pitch regions;
- (d) one array form: a full/depopulated rectangular grid `C × R`, or a single perimeter ring `A × B`;
- (e) optionally one centred exposed pad of size x × y, **or** a uniform array of `m` identical exposed lands;
- (f) optionally one ball diameter and one land diameter, uniform across the array.

If YES → **geometric name**, go to Step 1. If NO → Test 2.

**Test 2 — DISQUALIFIERS.** Does the drawing contain any of these? Any single one forces a product name:
- two or more different *signal* land sizes (i.e. sizes that differ for reasons other than the exposed pad);
- lands that are not on the single stated pitch grid (grouped, offset or dog-legged rows);
- castellated / edge-wrap pads;
- an RF antenna keep-out or "no copper" region;
- a shield-can outline or shield ground ring;
- mounting holes, NPTH, or board-edge cut-outs;
- the drawing is titled with the product name and exists only for that one ordering code.

If any fire → **product name**, go to Step 2.

**Test 3 — DESIGNATOR.** (Only reached if Tests 1 and 2 both came out clean-but-ambiguous.) Does the datasheet give the body a package designator that is *not* the product name — `LGA-14`, `TFBGA-100`, `WLCSP-49`, `MicroSiP-8`, `USON-8`? If yes → geometric. If the only identity the datasheet offers is the product/ordering name → product name.

**Test 4 — LIBRARY.** Geometric names live in `Package_BGA.pretty`, `Package_CSP.pretty` or `Package_LGA.pretty`. Product names live in `RF_GPS.pretty` (GNSS), `RF_GSM.pretty` (cellular: 2G/3G/LTE/NB-IoT/LTE-M), `RF_Module.pretty` (all other radio: BLE, Wi-Fi, LoRa, UWB, sub-GHz, 802.15.4, Sigfox — and note that **Espressif Wi-Fi modules go here, not in `RF_WiFi.pretty`**), or `Module.pretty` (SBCs, dev-boards, compute/TPU modules, breakouts, form-factor headers).

**Why this is the right rule, evidenced from stock:** "is it marketed as a module?" is the WRONG question. `ublox_LGA-53_4.5x4.5mm_Layout9x9_P0.5mm` is a u-blox MIA-M10Q GNSS *module* and it is named geometrically, because its land pattern is 53 identical 0.27 mm lands on a plain 9×9 0.5 mm grid — Test 1 passes. `Linear_LGA-133_15.0x15.0mm_Layout12x12_P1.27mm` is an Analog µModule regulator, also geometric, also 133 identical 0.63 mm lands on one grid. Meanwhile `Quectel_BG96` fails Test 1 (102 lands in 5 different sizes across grouped rows), so it keeps its product name. And `Nordic_nRF9160-SIxx_LGA-102-59EP_16.0x10.5mm_P0.5mm` passes Test 1 via clause (e): 102 signal lands on one 0.5 mm pitch plus a uniform 59-land ground array, which the `-59EP` token captures exactly.

**Hybrid case (3 stock files).** If Test 2 fired but the datasheet nevertheless publishes a family-wide `LGA-n` designator that several products in the family share, append it to the product name: `ublox_SARA_LGA-96`, `ublox_LENA-R8_LGA-100`, `ST-SiP-LGA-86-11x7.3mm`. Use this only when the pattern is genuinely shared across a product family — it is what distinguishes `ublox_SARA_LGA-96` (one footprint for the whole SARA family) from `Quectel_BG96` (one footprint, one product).

---

## Step 1 — Building a geometric name

1. **Family prefix.** Take the datasheet's own family abbreviation and use it verbatim from the stock vocabulary: `BGA`, `FBGA`, `TFBGA`, `LFBGA`, `UFBGA`, `VFBGA`, `XFBGA`, `XBGA`, `UCBGA`, `csBGA`, `caBGA`, `MAPBGA`, `FCPBGA`, `DSBGA`, `WLP`, `WLCSP`, `CSP`, `LFCSP`, `LGA`, `HLGA`, `OLGA`, `VLGA`, `CCLGA`, `USON`, `TSNP`, `MicroSiP`. Do not invent a new abbreviation if one of these matches the datasheet.
2. **Vendor prefix.** Add `<Vendor>_` when the land pattern is vendor-specific (an ST/Micron/TI/Nordic drawing that other vendors' same-designator parts would not match): `Micron_FBGA-96_…`, `ST_UFBGA-81_…`. Leave it off for a genuinely generic JEDEC pattern: `TFBGA-100_8x8mm_Layout10x10_P0.8mm`.
3. **Vendor package code.** If the datasheet has a mechanical drawing number that people search by, insert it between vendor and family: `Microchip_FCVG484_BGA-484_…`, `NXP_SOT1982-1_VFBGA-98_…`, `Texas_SIL0010A_MicroSiP-10-1EP_…`.
4. **`-n`** = the datasheet's electrical ball/land count. **`-mEP`** immediately after, only if there is more than one exposed land: `LGA-102-59EP`.
5. **Body `_XxYmm`** — width then height, mm, decimals as the datasheet gives them. Add a third number only if you also want to encode body height, otherwise use `_H<h>mm` later.
6. **Array token.**
   - Rectangular grid → `_Layout<C>x<R>` with C = columns across X, R = rows down Y, taken from the datasheet's row/column *labelling* (so empty interior rows still count). Sanity check: `n ≤ C×R`. If your candidate name violates that, you have mixed up ball count and grid extent.
   - Perimeter ring → `_LayoutBorder<A>x<B>y` with A = lands per top/bottom row, B = lands per left/right column. Sanity check: `n = 2A + 2B`.
   - Non-rectangular banded array → `_Layout<A>x<B>x<C>` only if you also state in `(descr …)` which convention you used, because stock uses two (see pitfalls). Prefer writing it out in the description and using the plain `C×R` bounding grid in the name.
7. **Pitch** `_P<p>mm`. Anisotropic → `_P<px>x<py>mm` (X first). Two regions → `_P<outer>mmP<inner>mm`. Write `1.0` not `1` for a 1 mm pitch — the `P1mm` spellings are legacy.
8. **Ball/land** — add `_Ball<d>mm_Pad<d>mm_NSMD` only when you are documenting a solder-mask-defined decision, and then add all three tokens. Never `NSMD` alone.
9. **EP size** `_EP<x>x<y>mm`, then `_ThermalVias` for the vias variant (ship both variants, as stock does — 30+ CSP pairs follow exactly this).
10. **Modifiers, in stock order:** `_H<h>mm`, `_Stagger`, `_Offcenter`, `_ThermalVias`, `_ClockwisePinNumbering`, then the process variant `_SMD` / `_HandSolder` / `_ManualAssembly` / `_LevelB` / `_LevelC`.
11. Put the geometry in `(descr …)` too, in the stock phrasing — `"<Vendor> <FAMILY>-<n>, <X>x<Y>mm, <n> Ball, <C>x<R> Layout, <p>mm Pitch, <datasheet URL>#page=N"` — because that string is what the library search box actually matches on.

**Worked example.** A datasheet shows: TFBGA, 100 balls, 8.0 × 8.0 mm body, 12 × 12 ball grid labelled A–N / 1–12 with the four corners depopulated, 0.65 mm pitch, generic JEDEC pattern, no exposed pad. Result: `TFBGA-100_8x8mm_Layout12x12_P0.65mm`. Check: 100 ≤ 144 ✓; a stock neighbour `TFBGA-121_10x10mm_Layout11x11_P0.8mm` confirms the token order.

---

## Step 2 — Naming a module

Copy the vendor's product name character-for-character, including hyphens, trailing antenna-option letters and case. Add nothing geometric.
- Vendor prefix only where the stock library already does it — `Quectel_`, `Telit_`, `Sierra_`, `SIMCom_`, `ublox_` (lowercase, no hyphen — the stock spelling), `Laird_`, `Raytac_`, `Microchip_`, `RaspberryPi_`. Espressif parts carry no vendor prefix at all (`ESP32-S3-WROOM-1U`, not `Espressif_ESP32…`).
- Variants get a suffix, using the stock vocabulary: `_HandSolder` (`ublox_SAM-M8Q_HandSolder`), `_SMD` / `_THT` (`HOPERF_RFM9XW_SMD`, `HOPERF_RFM9XW_THT`), `_WithMountingHoles` (`Arduino_Nano_WithMountingHoles`), `_NoRFPads` (`Atmel_ATSAMR21G18-MR210UA_NoRFPads`).
- Do not normalise the vendor's own inconsistency. `ESP-WROOM-02` and `ESP32-C3-WROOM-02` differ in prefix because Espressif's product names do.

---

## Step 3 — When the package is genuinely absent from KiCad stock

Check before concluding it's absent, in this order:
1. `ls /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints/Package_{BGA,CSP,LGA}.pretty | grep -i '<family>-<n>'` — the count `n` is the reliable search key, not the body size.
2. Grep the descriptions, not just filenames: `grep -l "<n> Ball" Package_BGA.pretty/*.kicad_mod`. The whole Xilinx set (43 files) and all 40 ST `_Die###` files hide their geometry there.
3. Check the neighbouring family — a WLCSP may be filed under `Package_BGA.pretty` as `WLP-…`, and a "CSP" may be an LFCSP (QFN) rather than a grid array.
4. For a reuse candidate, an existing footprint is only substitutable if pad count, pitch, grid extent, land diameter **and** body outline all match; a `Layout12x12` file cannot serve a `Layout11x11` part even at the same ball count.

If it really is absent, author it locally rather than bending a stock name:
- Put it in this project's own footprint namespace (`7Sigma:`) per `kicad-conventions-footprints`, and go through a draft proposal — never publish directly.
- Keep the stock token order exactly as in Step 1 so the new name sorts next to its stock neighbours and a later upstream addition is obviously the same part.
- For a module with no derivable name: product name verbatim, plus the pad/keep-out/silk requirements from the vendor's land-pattern drawing, plus the antenna clearance annotated on a user layer (stock modules do this — `ESP32-WROOM-32`, `Raytac_MDBT50Q` and `Digi_XBee_SMT` all carry `Cmts.User` annotations).
- Record the datasheet URL with a `#page=` anchor in `(descr …)`; that is the stock convention and it is what makes the footprint auditable later.

## Pitfalls

All of the following were verified against the shipped files, not recalled.

**1. `Layout` is the grid extent, `-n` is the ball count. They are different numbers.**
`BGA-63_9x11mm_Layout10x12_P0.8mm` = 63 balls in a 10×12 (120-cell) grid. Machine-checked over all 186 BGA + 65 CSP files with a plain `_LayoutCxR`: 138 are fully populated, 113 are depopulated, and **zero** have more balls than cells. If you write a name where n > C×R, you have swapped the two.

**2. `LayoutCxR` is columns(X) × rows(Y), and it is easy to write backwards.**
Confirmed from pad coordinates: `Analog_BGA-28_4x6.25mm_Layout4x7_P0.8mm` has 4 distinct X and 7 distinct Y. Note also `Texas_DSBGA-12_1.36x1.86mm_Layout3x4_P0.5mm` versus `Texas_DSBGA-12_2.11x1.61mm_Layout4x3_P0.5mm` — same ball count, transposed body and transposed layout. Getting the order wrong silently produces a rotated footprint.

**3. `LayoutAxBxC` means two different things in stock. Never assume; read the pads.**
Product form, memory-style split arrays: `BGA-90_8.0x13.0mm_Layout2x3x15_P0.8mm` = 2 banks × 3 columns × 15 rows = 90. Sum form, TI DSBGA: `Texas_DSBGA-5_0.822x1.116mm_Layout2x1x2_P0.4mm` = 2+1+2 = 5 bumps. Same token shape, incompatible arithmetic.

**4. True duplicate pair — `P1mm` vs `P1.0mm`.**
Both `BGA-132_12x18mm_Layout11x17_P1.0mm` and `BGA-132_12x18mm_Layout11x17_P1mm` exist, same package. A BOM that stores footprint names as strings will treat these as different parts. Related legacy `P1mm` spellings: `BGA-100_12x18mm_Layout10x17_P1mm`, `BGA-100_14x18mm_Layout10x17_P1mm`, `BGA-152_14x18mm_Layout13x17_P1mm`.

**5. `BGA-152_14x18mm_Layout13x17_P0.5mm` and `BGA-152_14x18mm_Layout13x17_P1mm` differ only in pitch — 0.5 mm vs 1 mm — for the same 152 balls in the same 13×17 grid on the same body.** At least one of them is wrong, and you cannot tell which from the name. Open the file before using either.

**6. Filename pin counts that disagree with the file.**
- `Fujitsu_WLP-15_2.28x3.092mm_Layout3x5_P0.4mm` — the name says 15 but the file has **8** pads (A1, A3, B2, C1, C3, D2, E1, E3). Its `(descr …)` says "WLP-15, 3x5 raster", so `-15` is Fujitsu's package name (15 bump *sites*), not a ball count.
- `Linear_BGA-133_15.0x15.0mm_Layout12x12_P1.27mm` has **134** pads; the LGA twin `Linear_LGA-133_15.0x15.0mm_Layout12x12_P1.27mm` has 133. Diffing them shows the BGA file carries an extra pad `E8`.
- Xilinx codes count the ordering code's advertised balls, not the file's pads: `Xilinx_CPG236` → 238 pads, `Xilinx_CSG325` → 324, `Xilinx_SBG485` → 484, `Xilinx_FFG1761` → 1760, `Xilinx_RF1930` → 1924.

**7. Near-identical names that differ only by a package-code digit, for the same geometry.** `Xilinx_CPG236` and `Xilinx_CPG238` have byte-identical descriptions ("10x10mm, 238 Ball, 19x19 Layout, 0.5mm Pitch") and the same 238 pads. Likewise `Xilinx_CSG324`/`Xilinx_CSG325` and `Xilinx_SBG484`/`Xilinx_SBG485`. Pick by the ordering code printed on your part, not by geometry.

**8. `Package_CSP.pretty` is two unrelated families.** 68 of its 179 files are `LFCSP*` — Analog Devices' *perimeter leadless* package, mechanically a QFN with no grid array and no `_Layout` token at all. Searching `Package_CSP` for "a CSP" will surface `LFCSP-32-1EP_5x5mm_P0.5mm_EP3.5x3.5mm` alongside genuine grid arrays like `WLCSP-36_2.82x2.67mm_Layout6x6_P0.4mm`. The two are not substitutable in any way.

**9. `-1EP` inflates the pad count you see in a viewer.** `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm` has 17 pads (16 + EP); its `_ThermalVias` twin also reports 17 but adds via pads on `*.Cu`. `LFCSP-24-1EP_4x4mm_P0.5mm_EP0.5x0.5mm` shows 25. Don't read the viewer's pad total as the pin count.

**10. `_ThermalVias` variants come in pairs and are otherwise identical.** Roughly 30 CSP and 4 LGA pairs. Picking the wrong one is a manufacturing decision, not a cosmetic one, and the names differ by one token at the very end where it is easiest to overlook.

**11. Body-size spelling is not normalised, and creates lookup misses.** `BGA-324_15.0x15.0mm_Layout18x18_P0.8mm_Ball0.5mm_Pad0.4mm_NSMD` versus `BGA-324_15x15mm_Layout18x18_P0.8mm`; `WLCSP-56_3.170x3.444mm_Layout7x8_P0.4mm` keeps a trailing zero. Search on the ball count, never on the body string.

**12. Two files break the body-size format outright.** `Maxim_WLP-9_1.595x1.415_Layout3x3_P0.4mm_Ball0.27mm_Pad0.25mm_NSMD` omits the `mm`. `Infineon_PG-TSNP-6-10_0.7x1.1mm_0.7x1.1mm_P0.4mm` states the body size twice. `WLCSP-16_4x4_B2.17x2.32mm_P0.5mm` writes the layout bare (`4x4`) and prefixes the body with `B`. Copy these verbatim; do not "fix" them, or you break the link to the file.

**13. Three-number body sizes mean X × Y × height, not X × Y × something-else.** Only `WLCSP-8_1.58x1.63x0.35mm_Layout3x5_P0.35x0.4mm_Ball0.25mm_Pad0.25mm_NSMD` does this. Elsewhere height is a separate `_H` token: `NXP_LGA-8_3x5mm_P1.25mm_H1.1mm` vs `NXP_LGA-8_3x5mm_P1.25mm_H1.2mm` — two files that differ *only* in body height, i.e. the pattern is identical and the choice is purely mechanical clearance.

**14. `_Stagger` roughly halves the ball count relative to the stated grid.** `ST_WLCSP-12_1.7x1.42mm_Layout4x6_P0.35mm_Stagger` = 12 balls in a nominal 4×6 grid, alternating cells (pads A2, A4, B1, B3, …). If you read the Layout as the ball count you will over-order pads by 2×. 21 CSP files plus `ST_VFBGA-424_14x14mm_Layout27x27_P0.5mmP0.5x0.5mm_Stagger`.

**15. Dual pitch has two unrelated notations.** `_P0.8x0.65mm` = anisotropic, X pitch × Y pitch (verified from coordinates in `BGA-200_10x14.5mm_Layout12x22_P0.8x0.65mm`). `_P0.5mmP0.65mm` = two *regions* at different pitches (`ST_TFBGA-257_10x10mm_Layout19x19_P0.5mmP0.65mm`, whose inner sub-array pads are named `1A1`, `1A2`, … with a numeric prefix that most importers will not expect). `x` versus a repeated `P` is the whole difference.

**16. ST's `_Die###` legacy names carry no geometry and reuse die IDs across ball counts.** `ST_WLCSP-49_Die435` and `ST_WLCSP-64_Die435` both exist — same die, different package. So does `ST_WLCSP-63_Die427` / `ST_WLCSP-64_Die427`, and `ST_WLCSP-72_Die415` / `ST_WLCSP-81_Die415`. The die ID alone never identifies a footprint. 40 such files, all in `Package_CSP.pretty`.

**17. Perimeter-LGA `LayoutBorder` is optional, which produces near-twins.** `LGA-16_3x3mm_P0.5mm` and `LGA-16_3x3mm_P0.5mm_LayoutBorder3x5y` are both in stock: same family, count, body and pitch, one specifying its ring split and the other not. Read the pads before assuming they are the same land pattern.

**18. `LayoutBorderAxBy` is A per horizontal row and B per vertical column — not rows × columns.** `Bosch_LGA-16_4.5x3mm_P0.5mm_LayoutBorder7x1y` is 7 lands top, 7 bottom, 1 each side. If you read it as a 7×1 grid you get 7 pads instead of 16.

**19. `_ClockwisePinNumbering` is a real electrical difference hidden in a cosmetic-looking token.** Four Bosch LGA files carry it. Using the non-clockwise sibling mirrors your pinout.

**20. Metric/imperial confusion: none of these names use imperial units — but three pitches look like imperial in disguise.** `P1.27mm` is 0.050 in, `P1.26mm` (`OnSemi_ODCSP8_BGA-8_3.16x3.16mm_Layout3x3_P1.26mm`) is a genuinely different metric value, and `P1.25mm` (`LGA-8_3x5mm_P1.25mm`) is a third. 1.25, 1.26 and 1.27 mm all exist in stock and are not interchangeable.

**21. `_SMD`, `_HandSolder`, `_ManualAssembly` and `_LevelB` / `_LevelC` all mean "bigger pads", differently.** `Lattice_caBGA-381_17x17mm_Layout20x20_P0.8mm_SMD` versus the plain `…_P0.8mm`; `OnSemi_ODCSP36_BGA-36_6.13x6.13mm_Layout6x6_P1.0mm_ManualAssembly` versus plain. There is no consistent vocabulary across vendors, so the bare name is not the "default" in any meaningful sense — it is just the other variant.

**22. Description text sometimes contradicts the filename.** Both `Texas_DSBGA-6_0.855x1.255mm_Layout2x3_P0.4mm_LevelB` and `…_LevelC` carry a `(descr …)` saying "0.95x1.488mm", which is neither file's filename body size. Trust the pads, then the filename, then the description — in that order.

**23. On the module side, the trap is the opposite one: near-identical product names.** `ESP32-WROOM-32` / `-32D` / `-32E` / `-32U` / `-32UE` are five separate footprints; `ESP32-S3-WROOM-1` vs `-1U` and `ESP32-C3-WROOM-02` vs `-02U` differ by the `U` that means "external antenna". `ESP32-S2-MINI-1` vs `ESP32-S2-MINI-1U`. `Sipeed-M1` vs `Sipeed-M1W`. `RN42` vs `RN42N`. `HOPERF_RFM9XW_SMD` vs `HOPERF_RFM9XW_THT`. There is no geometric token to cross-check against, so the only defence is reading the ordering code off the part.

**24. `RF_WiFi.pretty` contains exactly one footprint (`USR-C322`).** Looking there for a Wi-Fi module wastes time; Espressif and Olimex Wi-Fi parts are in `RF_Module.pretty` and `Module.pretty`. Likewise `RF_GSM.pretty` holds NB-IoT and LTE-M parts (`Quectel_BC66`, `Quectel_BG95`) despite the "GSM" name.

**25. `ublox` is spelled without the hyphen in every stock filename** (`ublox_ZED`, `ublox_SARA_LGA-96`, `ublox_LGA-53_…`), while the company writes "u-blox". Searching for `u-blox` returns nothing.

**26. Modules do occasionally live in `Package_LGA.pretty`, so searching only the `RF_*` libraries will miss them.** `Nordic_nRF9160-SIxx_LGA-102-59EP_16.0x10.5mm_P0.5mm`, `Nordic_nRF9151-LAxx_LGA-80-33EP_12.1x11.1mm_P0.5mm`, `ublox_LGA-53_4.5x4.5mm_Layout9x9_P0.5mm` (MIA-M10Q) and `Linear_LGA-133_15.0x15.0mm_Layout12x12_P1.27mm` are all modules or SiPs with geometric names. Conversely `ST-SiP-LGA-86-11x7.3mm` — an STM32WB5MMG SiP — lives in `RF_Module.pretty` with a product-ish name. There is no library boundary you can rely on; search both sides.

**27. KiCad ships no Murata wireless-module footprint at all.** Verified by `find` over the whole footprint tree for `*Murata*` and for `LBEE*`, `LBAA*`, `Type1*`, `*1DX*`, `*1LD*`, `*1YM*`, `*1ZM*`: the only Murata hits are passives and power parts (`Filter_Murata_BNX025`, `L_Murata_DFE201610P`, `Converter_DCDC_muRata_MEJ1DxxxxSC_THT` — note that last one spells the vendor `muRata`, so even a case-insensitive vendor grep needs care). Budget time to draw any Murata module from scratch.

**28. `Onion_Omega2+` contains a `+` in the filename.** It is legal but will need escaping in shell globs, regexes and URLs.

**29. `RaspberryPi_Pico_Common_*` files are shared bases, not usable variants in the ordinary sense** — `RaspberryPi_Pico_Common_Unspecified` sits alongside `RaspberryPi_Pico_SMD`, `RaspberryPi_Pico_SMD_HandSolder`, `RaspberryPi_Pico_W_SMD` and `RaspberryPi_Pico_W_SMD_HandSolder`. Five near-identical names, and the `_W` ones are a different product (wireless) with a different pad set (49 vs 40 named pads). Also note the vendor is spelled two ways in the same library: `RaspberryPi_Pico_SMD` versus `Raspberry_Pi_Zero_Socketed_THT_FaceDown_MountingHoles`.


---


# Connectors (KiCad stock `Connector_*.pretty` + `TerminalBlock_*.pretty`)

**Backed by:** 4 865 footprint files read directly from `/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints`, out of 8 012 in the 70 `Connector_*` + `TerminalBlock_*` libraries and 15 447 in the whole shipped footprint tree.

Per sub-table:
- Pin headers & sockets — **2 070** files (8 libraries: PinHeader 1.00/1.27/2.00/2.54 mm = 278 each; PinSocket 1.00 mm = 156, 1.27 mm = 246, 2.00 mm = 278, 2.54 mm = 278). The task asked for three of these; I read all eight so the pitch matrix is complete.
- IDC — **182** files (`Connector_IDC.pretty`)
- JST — **558** files (`Connector_JST.pretty`), 22 series
- Molex — **812** files (`Connector_Molex.pretty`), 21 series
- FFC/FPC — **372** files (`Connector_FFC-FPC.pretty`), 21 vendor/series groups
- USB — **75** files (`Connector_USB.pretty`), every one listed verbatim
- RJ — **38** files (`Connector_RJ.pretty`), every one listed verbatim
- Coaxial — **37** files (`Connector_Coaxial.pretty`), every one listed verbatim
- Card sockets — **20** files (`Connector_Card.pretty`), every one listed verbatim
- Phoenix pluggable (MC/MSTB) — **360** files (180 + 180)
- Terminal blocks — **341** files in the three read (`TerminalBlock.pretty` 45, `TerminalBlock_Phoenix.pretty` 126, `TerminalBlock_WAGO.pretty` 170); 731 across all 14 `TerminalBlock_*` libraries.

Verification method: every name quoted below was re-checked with a per-file `[ -f ... ]` test after the tables were written — 170 (USB/RJ/coax/card) + 52 (header/socket) + 53 (JST) + 44 (Molex/FFC) + 47 (IDC/Phoenix/terminal block) = **366 individual file-existence assertions, all passing**. Two additional lookups confirmed non-existence of plausible-but-fake patterns.

## Grammar

Connectors are the one family where a single geometric grammar does NOT work. KiCad uses two tiers, plus per-sub-family token orders.

## TIER A — generic / geometric (no vendor in the name)

```
<Type>_<R>x<NN>[-1MP]_P<pitch>mm[_<Feature>]_<Orientation>[_<Pin1Side>]
```

| Token | Values actually in stock |
|---|---|
| `<Type>` | `PinHeader`, `PinSocket`, `IDC-Header` |
| `<R>x<NN>` | `1x01`…`1x40`, `2x01`…`2x50`. `NN` is **always zero-padded to 2 digits** |
| `-1MP` | optional; mechanical (non-electrical) pad count. Only ever `-1MP` |
| `P<pitch>mm` | `P1.00mm`, `P1.27mm`, `P2.00mm`, `P2.54mm` |
| `<Feature>` | IDC only: `Latch`, `Latch6.5mm`, `Latch9.5mm`, `Latch12.0mm` |
| `<Orientation>` | `Vertical`, `Horizontal`, `Vertical_SMD` |
| `<Pin1Side>` | `Pin1Left` / `Pin1Right` — **only** on `1xNN` + `Vertical_SMD` |

Hard facts (verified by attempted lookup): `PinHeader_1x05_P2.54mm_Vertical_SMD` does **not** exist (single-row SMD is always `_Pin1Left`/`_Pin1Right`). `PinHeader_1x05_P2.54mm_Horizontal_SMD` does **not** exist (no horizontal SMD at all). `PinHeader_2x05_P2.54mm_Vertical_SMD_Pin1Left` does **not** exist (double-row SMD never carries a Pin1 side).

## TIER B — vendor / series / MPN

```
[<Interface>_]<Vendor>[_<Series>]_<MPN>_<Geometry>[-1MP|-1SH]_P<pitch>mm_<Orientation>[_<Feature>]
```

The token order is stable **within** a library but the set of tokens differs **between** libraries. Seven distinct shapes exist:

| Sub-family | Shape |
|---|---|
| JST | `JST_<Series>_<MPN>_<R>x<NN>[-1MP]_P<pitch>mm_<Orientation>` |
| Molex | `Molex_<Series>_<MPN>_<R>x<NN>[-1MP]_P<pitch>mm_<Orientation>[_ThermalVias]` |
| FFC/FPC | `<Vendor>_<MPN>_<Geometry>[-1MP\|-1SH]_P<pitch>mm_<Orientation>` — **no** series token |
| USB | `USB[3]_<Type>_[Receptacle_\|Plug_]<Vendor>_<MPN>[_<Orientation>][_<Variant>]` — **no** pitch, **no** position count |
| RJ | `RJ<n>_[Plug_]<Vendor>_<MPN>[_<Orientation>]` — **no** pitch |
| Coaxial | `<Interface>_<Vendor>_<MPN>_<Mount>` — **no** pitch, **no** position count |
| Card | `<CardType>[_HC][_Hinged]_<Vendor>_<MPN>` — **no** pitch, **no** orientation |
| Phoenix pluggable | `PhoenixContact_<Series>_<WireSize>_<Pos>-<Style>[-<pitch>]_1x<NN>_P<pitch>mm_<Orientation>[_ThreadedFlange][_MountHole]` |
| Terminal block | `TerminalBlock_<Vendor>_<MPN>_<R>x<NN>_P<pitch>mm[_<Orientation>]` |

`<Geometry>` in FFC/FPC is one of three mutually exclusive dialects: `1xNN`, `2xNN`, or `2Rows-NNPins`.

## THE MECHANICAL TEST — which tier?

Not "does it have extra pads" (IDC-Header is Tier A and has `-1MP` latch pads). The decisive question is:

> **Is the recommended land pattern an industry-standard grid that any manufacturer's part in that class will drop into, or is it proprietary to one manufacturer's series?**

Apply in this order:

1. **Can you reproduce the whole land pattern from (rows, positions, pitch, THT/SMD) alone, with every electrical pad identical and on a uniform grid?** → Tier A candidate.
2. **Is that grid one of the four stocked standard pitches (1.00 / 1.27 / 2.00 / 2.54 mm) and is it cross-vendor interchangeable?** → Tier A. Use `PinHeader` / `PinSocket` / `IDC-Header`.
3. **Otherwise → Tier B, always.** Anything with a proprietary housing footprint, keying/polarisation, vendor-specific hold-down or shield tabs, a board cut-out, non-uniform pad sizes, a latch window, a card cavity, or a defined mating shell (USB / RJ / coax / SD) is named by Vendor + Series + MPN. No exceptions exist in stock.

**Evidence the test is real, not editorial:** 2 252 of the 8 012 connector-family footprints are Tier A, and every single one is in `Connector_PinHeader_*`, `Connector_PinSocket_*`, or `Connector_IDC.pretty`. Across all 14 `TerminalBlock_*.pretty` libraries (731 files) there are **zero** footprints whose name lacks a vendor token — a terminal-block body and its hold-down geometry are never cross-vendor, so terminal blocks are Tier B without exception. (The task premise "TerminalBlock generic" is wrong; corrected in the tables below.)

Tier A also covers three small non-mating families outside the three libraries above: `Connector_Wire.pretty` `SolderWire-*` (324), `Connector_Pin.pretty` `Pin_D*` (13), and 5 strays in `Connector.pretty` (`FanPinHeader_1x03_P2.54mm_Vertical`, `FanPinHeader_1x04_P2.54mm_Vertical`, `Banana_Jack_1Pin`, `Banana_Jack_2Pin`, `Banana_Jack_3Pin`).

## Reference table

## 0. Library index — where each sub-family lives

| Library | Files | Tier | Naming |
|---|---:|---|---|
| `Connector_PinHeader_1.00mm.pretty` | 278 | A | `PinHeader_…` |
| `Connector_PinHeader_1.27mm.pretty` | 278 | A | `PinHeader_…` |
| `Connector_PinHeader_2.00mm.pretty` | 278 | A | `PinHeader_…` |
| `Connector_PinHeader_2.54mm.pretty` | 278 | A | `PinHeader_…` |
| `Connector_PinSocket_1.00mm.pretty` | 156 | A | `PinSocket_…` |
| `Connector_PinSocket_1.27mm.pretty` | 246 | A | `PinSocket_…` |
| `Connector_PinSocket_2.00mm.pretty` | 278 | A | `PinSocket_…` |
| `Connector_PinSocket_2.54mm.pretty` | 278 | A | `PinSocket_…` |
| `Connector_IDC.pretty` | 182 | A | `IDC-Header_…` |
| `Connector_JST.pretty` | 558 | B | `JST_<Series>_<MPN>_…` |
| `Connector_Molex.pretty` | 812 | B | `Molex_<Series>_<MPN>_…` |
| `Connector_FFC-FPC.pretty` | 372 | B | `<Vendor>_<MPN>_…` |
| `Connector_USB.pretty` | 75 | B | `USB_<Type>_<Vendor>_<MPN>_…` |
| `Connector_RJ.pretty` | 38 | B | `RJ<n>_<Vendor>_<MPN>_…` |
| `Connector_Coaxial.pretty` | 37 | B | `<Interface>_<Vendor>_<MPN>_<Mount>` |
| `Connector_Card.pretty` | 20 | B | `<CardType>_<Vendor>_<MPN>` |
| `Connector_Phoenix_MC.pretty` | 180 | B | `PhoenixContact_MC…_…` |
| `Connector_Phoenix_MSTB.pretty` | 180 | B | `PhoenixContact_MSTB…_…` |
| `TerminalBlock.pretty` | 45 | B | `TerminalBlock_<Vendor>_…` |
| `TerminalBlock_Phoenix.pretty` | 126 | B | `TerminalBlock_Phoenix_…` |
| `TerminalBlock_WAGO.pretty` | 170 | B | `TerminalBlock_WAGO_…` |
| `TerminalBlock_RND.pretty` | 132 | B | vendor |
| `TerminalBlock_MetzConnect.pretty` | 61 | B | vendor |
| `TerminalBlock_Altech.pretty` | 46 | B | vendor |
| `TerminalBlock_Dinkle.pretty` | 29 | B | vendor |
| `TerminalBlock_4Ucon.pretty` | 28 | B | vendor |
| `TerminalBlock_CUI.pretty` | 23 | B | vendor |
| `TerminalBlock_Degson.pretty` | 22 | B | vendor |
| `TerminalBlock_Ningbo-Kagnex.pretty` | 22 | B | vendor |
| `TerminalBlock_Wuerth.pretty` | 14 | B | vendor |
| `TerminalBlock_TE-Connectivity.pretty` | 11 | B | vendor |
| `TerminalBlock_Philmore.pretty` | 2 | B | vendor |

---

## 1. Pin headers & sockets — the full 1xNN / 2xNN × pitch × orientation matrix

`NN` is a placeholder; every "Example" cell is a real file confirmed on disk. 2 070 files, 52 rows — this is the complete matrix, there are no other patterns.

| Type | Pitch | Rows | Orientation | Filename template | NN range | Files | Confirmed example |
|---|---|---|---|---|---|---:|---|
| `PinHeader` | 1.00mm | 1xNN | Vertical | `PinHeader_1xNN_P1.00mm_Vertical` | 1x01 – 1x40 | 40 | `PinHeader_1x03_P1.00mm_Vertical` |
| `PinHeader` | 1.00mm | 2xNN | Vertical | `PinHeader_2xNN_P1.00mm_Vertical` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P1.00mm_Vertical` |
| `PinHeader` | 1.00mm | 1xNN | Horizontal | `PinHeader_1xNN_P1.00mm_Horizontal` | 1x01 – 1x40 | 40 | `PinHeader_1x03_P1.00mm_Horizontal` |
| `PinHeader` | 1.00mm | 2xNN | Horizontal | `PinHeader_2xNN_P1.00mm_Horizontal` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P1.00mm_Horizontal` |
| `PinHeader` | 1.00mm | 2xNN | Vertical_SMD | `PinHeader_2xNN_P1.00mm_Vertical_SMD` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P1.00mm_Vertical_SMD` |
| `PinHeader` | 1.00mm | 1xNN | Vertical_SMD_Pin1Left | `PinHeader_1xNN_P1.00mm_Vertical_SMD_Pin1Left` | 1x02 – 1x40 | 39 | `PinHeader_1x04_P1.00mm_Vertical_SMD_Pin1Left` |
| `PinHeader` | 1.00mm | 1xNN | Vertical_SMD_Pin1Right | `PinHeader_1xNN_P1.00mm_Vertical_SMD_Pin1Right` | 1x02 – 1x40 | 39 | `PinHeader_1x04_P1.00mm_Vertical_SMD_Pin1Right` |
| `PinHeader` | 1.27mm | 1xNN | Vertical | `PinHeader_1xNN_P1.27mm_Vertical` | 1x01 – 1x40 | 40 | `PinHeader_1x03_P1.27mm_Vertical` |
| `PinHeader` | 1.27mm | 2xNN | Vertical | `PinHeader_2xNN_P1.27mm_Vertical` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P1.27mm_Vertical` |
| `PinHeader` | 1.27mm | 1xNN | Horizontal | `PinHeader_1xNN_P1.27mm_Horizontal` | 1x01 – 1x40 | 40 | `PinHeader_1x03_P1.27mm_Horizontal` |
| `PinHeader` | 1.27mm | 2xNN | Horizontal | `PinHeader_2xNN_P1.27mm_Horizontal` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P1.27mm_Horizontal` |
| `PinHeader` | 1.27mm | 2xNN | Vertical_SMD | `PinHeader_2xNN_P1.27mm_Vertical_SMD` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P1.27mm_Vertical_SMD` |
| `PinHeader` | 1.27mm | 1xNN | Vertical_SMD_Pin1Left | `PinHeader_1xNN_P1.27mm_Vertical_SMD_Pin1Left` | 1x02 – 1x40 | 39 | `PinHeader_1x04_P1.27mm_Vertical_SMD_Pin1Left` |
| `PinHeader` | 1.27mm | 1xNN | Vertical_SMD_Pin1Right | `PinHeader_1xNN_P1.27mm_Vertical_SMD_Pin1Right` | 1x02 – 1x40 | 39 | `PinHeader_1x04_P1.27mm_Vertical_SMD_Pin1Right` |
| `PinHeader` | 2.00mm | 1xNN | Vertical | `PinHeader_1xNN_P2.00mm_Vertical` | 1x01 – 1x40 | 40 | `PinHeader_1x03_P2.00mm_Vertical` |
| `PinHeader` | 2.00mm | 2xNN | Vertical | `PinHeader_2xNN_P2.00mm_Vertical` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P2.00mm_Vertical` |
| `PinHeader` | 2.00mm | 1xNN | Horizontal | `PinHeader_1xNN_P2.00mm_Horizontal` | 1x01 – 1x40 | 40 | `PinHeader_1x03_P2.00mm_Horizontal` |
| `PinHeader` | 2.00mm | 2xNN | Horizontal | `PinHeader_2xNN_P2.00mm_Horizontal` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P2.00mm_Horizontal` |
| `PinHeader` | 2.00mm | 2xNN | Vertical_SMD | `PinHeader_2xNN_P2.00mm_Vertical_SMD` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P2.00mm_Vertical_SMD` |
| `PinHeader` | 2.00mm | 1xNN | Vertical_SMD_Pin1Left | `PinHeader_1xNN_P2.00mm_Vertical_SMD_Pin1Left` | 1x02 – 1x40 | 39 | `PinHeader_1x04_P2.00mm_Vertical_SMD_Pin1Left` |
| `PinHeader` | 2.00mm | 1xNN | Vertical_SMD_Pin1Right | `PinHeader_1xNN_P2.00mm_Vertical_SMD_Pin1Right` | 1x02 – 1x40 | 39 | `PinHeader_1x04_P2.00mm_Vertical_SMD_Pin1Right` |
| `PinHeader` | 2.54mm | 1xNN | Vertical | `PinHeader_1xNN_P2.54mm_Vertical` | 1x01 – 1x40 | 40 | `PinHeader_1x03_P2.54mm_Vertical` |
| `PinHeader` | 2.54mm | 2xNN | Vertical | `PinHeader_2xNN_P2.54mm_Vertical` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P2.54mm_Vertical` |
| `PinHeader` | 2.54mm | 1xNN | Horizontal | `PinHeader_1xNN_P2.54mm_Horizontal` | 1x01 – 1x40 | 40 | `PinHeader_1x03_P2.54mm_Horizontal` |
| `PinHeader` | 2.54mm | 2xNN | Horizontal | `PinHeader_2xNN_P2.54mm_Horizontal` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P2.54mm_Horizontal` |
| `PinHeader` | 2.54mm | 2xNN | Vertical_SMD | `PinHeader_2xNN_P2.54mm_Vertical_SMD` | 2x01 – 2x40 | 40 | `PinHeader_2x03_P2.54mm_Vertical_SMD` |
| `PinHeader` | 2.54mm | 1xNN | Vertical_SMD_Pin1Left | `PinHeader_1xNN_P2.54mm_Vertical_SMD_Pin1Left` | 1x02 – 1x40 | 39 | `PinHeader_1x04_P2.54mm_Vertical_SMD_Pin1Left` |
| `PinHeader` | 2.54mm | 1xNN | Vertical_SMD_Pin1Right | `PinHeader_1xNN_P2.54mm_Vertical_SMD_Pin1Right` | 1x02 – 1x40 | 39 | `PinHeader_1x04_P2.54mm_Vertical_SMD_Pin1Right` |
| `PinSocket` | 1.00mm | 1xNN | Vertical | `PinSocket_1xNN_P1.00mm_Vertical` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P1.00mm_Vertical` |
| `PinSocket` | 1.00mm | 2xNN | Vertical_SMD | `PinSocket_2xNN_P1.00mm_Vertical_SMD` | 2x02 – 2x40 | 39 | `PinSocket_2x04_P1.00mm_Vertical_SMD` |
| `PinSocket` | 1.00mm | 1xNN | Vertical_SMD_Pin1Left | `PinSocket_1xNN_P1.00mm_Vertical_SMD_Pin1Left` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P1.00mm_Vertical_SMD_Pin1Left` |
| `PinSocket` | 1.00mm | 1xNN | Vertical_SMD_Pin1Right | `PinSocket_1xNN_P1.00mm_Vertical_SMD_Pin1Right` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P1.00mm_Vertical_SMD_Pin1Right` |
| `PinSocket` | 1.27mm | 1xNN | Vertical | `PinSocket_1xNN_P1.27mm_Vertical` | 1x01 – 1x40 | 40 | `PinSocket_1x03_P1.27mm_Vertical` |
| `PinSocket` | 1.27mm | 2xNN | Vertical | `PinSocket_2xNN_P1.27mm_Vertical` | 2x01 – 2x40 | 40 | `PinSocket_2x03_P1.27mm_Vertical` |
| `PinSocket` | 1.27mm | 2xNN | Horizontal | `PinSocket_2xNN_P1.27mm_Horizontal` | **2x03 – 2x50** | 48 | `PinSocket_2x05_P1.27mm_Horizontal` |
| `PinSocket` | 1.27mm | 2xNN | Vertical_SMD | `PinSocket_2xNN_P1.27mm_Vertical_SMD` | 2x01 – 2x40 | 40 | `PinSocket_2x03_P1.27mm_Vertical_SMD` |
| `PinSocket` | 1.27mm | 1xNN | Vertical_SMD_Pin1Left | `PinSocket_1xNN_P1.27mm_Vertical_SMD_Pin1Left` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P1.27mm_Vertical_SMD_Pin1Left` |
| `PinSocket` | 1.27mm | 1xNN | Vertical_SMD_Pin1Right | `PinSocket_1xNN_P1.27mm_Vertical_SMD_Pin1Right` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P1.27mm_Vertical_SMD_Pin1Right` |
| `PinSocket` | 2.00mm | 1xNN | Vertical | `PinSocket_1xNN_P2.00mm_Vertical` | 1x01 – 1x40 | 40 | `PinSocket_1x03_P2.00mm_Vertical` |
| `PinSocket` | 2.00mm | 2xNN | Vertical | `PinSocket_2xNN_P2.00mm_Vertical` | 2x01 – 2x40 | 40 | `PinSocket_2x03_P2.00mm_Vertical` |
| `PinSocket` | 2.00mm | 1xNN | Horizontal | `PinSocket_1xNN_P2.00mm_Horizontal` | 1x01 – 1x40 | 40 | `PinSocket_1x03_P2.00mm_Horizontal` |
| `PinSocket` | 2.00mm | 2xNN | Horizontal | `PinSocket_2xNN_P2.00mm_Horizontal` | 2x01 – 2x40 | 40 | `PinSocket_2x03_P2.00mm_Horizontal` |
| `PinSocket` | 2.00mm | 2xNN | Vertical_SMD | `PinSocket_2xNN_P2.00mm_Vertical_SMD` | 2x01 – 2x40 | 40 | `PinSocket_2x03_P2.00mm_Vertical_SMD` |
| `PinSocket` | 2.00mm | 1xNN | Vertical_SMD_Pin1Left | `PinSocket_1xNN_P2.00mm_Vertical_SMD_Pin1Left` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P2.00mm_Vertical_SMD_Pin1Left` |
| `PinSocket` | 2.00mm | 1xNN | Vertical_SMD_Pin1Right | `PinSocket_1xNN_P2.00mm_Vertical_SMD_Pin1Right` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P2.00mm_Vertical_SMD_Pin1Right` |
| `PinSocket` | 2.54mm | 1xNN | Vertical | `PinSocket_1xNN_P2.54mm_Vertical` | 1x01 – 1x40 | 40 | `PinSocket_1x03_P2.54mm_Vertical` |
| `PinSocket` | 2.54mm | 2xNN | Vertical | `PinSocket_2xNN_P2.54mm_Vertical` | 2x01 – 2x40 | 40 | `PinSocket_2x03_P2.54mm_Vertical` |
| `PinSocket` | 2.54mm | 1xNN | Horizontal | `PinSocket_1xNN_P2.54mm_Horizontal` | 1x01 – 1x40 | 40 | `PinSocket_1x03_P2.54mm_Horizontal` |
| `PinSocket` | 2.54mm | 2xNN | Horizontal | `PinSocket_2xNN_P2.54mm_Horizontal` | 2x01 – 2x40 | 40 | `PinSocket_2x03_P2.54mm_Horizontal` |
| `PinSocket` | 2.54mm | 2xNN | Vertical_SMD | `PinSocket_2xNN_P2.54mm_Vertical_SMD` | 2x01 – 2x40 | 40 | `PinSocket_2x03_P2.54mm_Vertical_SMD` |
| `PinSocket` | 2.54mm | 1xNN | Vertical_SMD_Pin1Left | `PinSocket_1xNN_P2.54mm_Vertical_SMD_Pin1Left` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P2.54mm_Vertical_SMD_Pin1Left` |
| `PinSocket` | 2.54mm | 1xNN | Vertical_SMD_Pin1Right | `PinSocket_1xNN_P2.54mm_Vertical_SMD_Pin1Right` | 1x02 – 1x40 | 39 | `PinSocket_1x04_P2.54mm_Vertical_SMD_Pin1Right` |

**Holes in the matrix (do not exist — do not assume symmetry):**
- `PinSocket_1.00mm` has **no** `Horizontal` at any row count, and **no** plain `2xNN_Vertical` (only `2xNN_Vertical_SMD`). 156 files, not 278.
- `PinSocket_1.27mm` has **no** `1xNN_Horizontal`; its `2xNN_Horizontal` runs to **2x50**, the only place in the family that exceeds 40.
- `1xNN` + `Vertical_SMD` always starts at `1x02` (39 files), never `1x01`.
- There is no `1xNN_Vertical_SMD` without a `Pin1Left`/`Pin1Right` suffix, and no `Horizontal_SMD` anywhere.

---

## 2. IDC-Header — Tier A, `Connector_IDC.pretty`, 182 files

All at `P2.54mm`, all `2xNN`. Position counts are **sparse** — do not interpolate.

| Filename template | Position counts present (verbatim tokens) | Files | Confirmed example |
|---|---|---:|---|
| `IDC-Header_2xNN_P2.54mm_Vertical` | 2x03 2x04 2x05 2x06 2x07 2x08 2x09 2x10 2x11 2x12 2x13 2x15 2x17 2x20 2x22 2x25 2x30 2x32 | 18 | `IDC-Header_2x03_P2.54mm_Vertical` |
| `IDC-Header_2xNN_P2.54mm_Horizontal` | 2x03 2x04 2x05 2x06 2x07 2x08 2x09 2x10 2x11 2x12 2x13 2x15 2x17 2x20 2x22 2x25 2x30 2x32 | 18 | `IDC-Header_2x32_P2.54mm_Horizontal` |
| `IDC-Header_2xNN_P2.54mm_Vertical_SMD` | 2x03 2x04 2x05 2x06 2x07 2x08 2x09 2x10 2x11 2x12 2x13 2x20 2x22 2x25 2x30 | 15 | `IDC-Header_2x30_P2.54mm_Vertical_SMD` |
| `IDC-Header_2xNN_P2.54mm_Latch_Vertical` | 2x05 2x06 2x07 2x08 2x10 2x12 2x13 2x15 2x17 2x20 2x25 2x30 2x32 | 13 | `IDC-Header_2x05_P2.54mm_Latch_Vertical` |
| `IDC-Header_2xNN_P2.54mm_Latch_Horizontal` | same 13 as above | 13 | `IDC-Header_2x05_P2.54mm_Latch_Horizontal` |
| `IDC-Header_2xNN_P2.54mm_Latch6.5mm_Vertical` | same 13 | 13 | `IDC-Header_2x05_P2.54mm_Latch6.5mm_Vertical` |
| `IDC-Header_2xNN_P2.54mm_Latch9.5mm_Vertical` | same 13 | 13 | `IDC-Header_2x05_P2.54mm_Latch9.5mm_Vertical` |
| `IDC-Header_2xNN_P2.54mm_Latch12.0mm_Vertical` | same 13 | 13 | `IDC-Header_2x05_P2.54mm_Latch12.0mm_Vertical` |
| `IDC-Header_2xNN-1MP_P2.54mm_Latch_Vertical` | same 13 (`-1MP` suffixed) | 13 | `IDC-Header_2x05-1MP_P2.54mm_Latch_Vertical` |
| `IDC-Header_2xNN-1MP_P2.54mm_Latch_Horizontal` | same 13 | 13 | `IDC-Header_2x05-1MP_P2.54mm_Latch_Horizontal` |
| `IDC-Header_2xNN-1MP_P2.54mm_Latch6.5mm_Vertical` | same 13 | 13 | `IDC-Header_2x05-1MP_P2.54mm_Latch6.5mm_Vertical` |
| `IDC-Header_2xNN-1MP_P2.54mm_Latch9.5mm_Vertical` | same 13 | 13 | `IDC-Header_2x05-1MP_P2.54mm_Latch9.5mm_Vertical` |
| `IDC-Header_2xNN-1MP_P2.54mm_Latch12.0mm_Vertical` | same 13 | 13 | `IDC-Header_2x32-1MP_P2.54mm_Latch12.0mm_Vertical` |
| `IDC-Header_2x07_P2.54mm_Horizontal_Lock` | 2x07 only | 1 | `IDC-Header_2x07_P2.54mm_Horizontal_Lock` |

Note the `-1MP` sets exist **only** for the 5 `Latch*` variants — there is no `IDC-Header_2x05-1MP_P2.54mm_Vertical`.

---

## 3. JST — `Connector_JST.pretty`, 558 files, 22 series

Grammar: `JST_<Series>_<MPN>_<R>x<NN>[-1MP]_P<pitch>mm_<Orientation>`. In the template column `NN` inside the MPN stands for the vendor's own position digits — **which are NOT padded the same way as the geometry token** (see Pitfalls).

| Series | MPN template | Pitch | Orient. | Files | Geometry range | Confirmed example |
|---|---|---|---|---:|---|---|
| `ACH` | `JST_ACH_BM<n>B-ACHSS-A-GAN-ETF` | 1.20mm | Vertical | 3 | 1x01-1MP – 1x05-1MP | `JST_ACH_BM01B-ACHSS-A-GAN-ETF_1x01-1MP_P1.20mm_Vertical` |
| `ACH` | `JST_ACH_BM<n>B-ACHSS-GAN-ETF` | 1.20mm | Vertical | 2 | 1x02-1MP – 1x03-1MP | `JST_ACH_BM02B-ACHSS-GAN-ETF_1x02-1MP_P1.20mm_Vertical` |
| `AUH` | `JST_AUH_BM<n>B-AUHKS-GA-TB` | 1.50mm | Vertical | 2 | 1x03-1MP – 1x05-1MP | `JST_AUH_BM03B-AUHKS-GA-TB_1x03-1MP_P1.50mm_Vertical` |
| `EH` | `JST_EH_B<n>B-EH-A` | 2.50mm | Vertical | 14 | 1x02 – 1x15 | `JST_EH_B2B-EH-A_1x02_P2.50mm_Vertical` |
| `EH` | `JST_EH_S<n>B-EH` | 2.50mm | Horizontal | 14 | 1x02 – 1x15 | `JST_EH_S2B-EH_1x02_P2.50mm_Horizontal` |
| `GH` | `JST_GH_BM<n>B-GHS-TBT` | 1.25mm | Vertical | 14 | 1x02-1MP – 1x15-1MP | `JST_GH_BM02B-GHS-TBT_1x02-1MP_P1.25mm_Vertical` |
| `GH` | `JST_GH_SM<n>B-GHS-TB` | 1.25mm | Horizontal | 14 | 1x02-1MP – 1x15-1MP | `JST_GH_SM02B-GHS-TB_1x02-1MP_P1.25mm_Horizontal` |
| `J2100` | `JST_J2100_B<n>B-J21DK-GGXR` | **2.50x4.00mm** | Vertical | 6 | 2x03 – 2x10 | `JST_J2100_B06B-J21DK-GGXR_2x03_P2.50x4.00mm_Vertical` |
| `J2100` | `JST_J2100_S<n>B-J21DK-GGXR` | 2.50mm | Horizontal | 6 | 2x03 – 2x10 | `JST_J2100_S06B-J21DK-GGXR_2x03_P2.50mm_Horizontal` |
| `JWPF` | `JST_JWPF_B<n>B-JWPF-SK-R` | 2.00mm | Vertical | 5 | 1x02 – 2x04 | `JST_JWPF_B02B-JWPF-SK-R_1x02_P2.00mm_Vertical` |
| `LEA` | `JST_LEA_SM<n>B-LEASS-TF` | 4.20mm | Horizontal | 1 | 1x02-1MP | `JST_LEA_SM02B-LEASS-TF_1x02-1MP_P4.20mm_Horizontal` |
| `NV` | `JST_NV_B<n>P-NV` | 5.00mm | Vertical | 3 | 1x02 – 1x04 | `JST_NV_B02P-NV_1x02_P5.00mm_Vertical` |
| `PH` | `JST_PH_B<n>B-PH-K` | 2.00mm | Vertical | 15 | 1x02 – 1x16 | `JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical` |
| `PH` | `JST_PH_B<n>B-PH-SM4-TB` | 2.00mm | Vertical | 15 | 1x02-1MP – 1x16-1MP | `JST_PH_B2B-PH-SM4-TB_1x02-1MP_P2.00mm_Vertical` |
| `PH` | `JST_PH_S<n>B-PH-K` | 2.00mm | Horizontal | 15 | 1x02 – 1x16 | `JST_PH_S2B-PH-K_1x02_P2.00mm_Horizontal` |
| `PH` | `JST_PH_S<n>B-PH-SM4-TB` | 2.00mm | Horizontal | 14 | 1x02-1MP – 1x15-1MP | `JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal` |
| `PHD` | `JST_PHD_B<n>B-PHDSS` | 2.00mm | Vertical | 14 | 2x04 – 2x17 | `JST_PHD_B8B-PHDSS_2x04_P2.00mm_Vertical` |
| `PHD` | `JST_PHD_S<n>B-PHDSS` | 2.00mm | Horizontal | 14 | 2x04 – 2x17 | `JST_PHD_S8B-PHDSS_2x04_P2.00mm_Horizontal` |
| `PUD` | `JST_PUD_B<n>B-PUDSS` | 2.00mm | Vertical | 17 | 2x04 – 2x20 | `JST_PUD_B08B-PUDSS_2x04_P2.00mm_Vertical` |
| `PUD` | `JST_PUD_S<n>B-PUDSS-1` | 2.00mm | Horizontal | 17 | 2x04 – 2x20 | `JST_PUD_S08B-PUDSS-1_2x04_P2.00mm_Horizontal` |
| `SFH` | `JST_SFH_SM<n>B-SFHRS-TF` | 4.20mm | Horizontal | 1 | 1x02-1MP | `JST_SFH_SM02B-SFHRS-TF_1x02-1MP_P4.20mm_Horizontal` |
| `SH` | `JST_SH_BM<n>B-SRSS-TB` | 1.00mm | Vertical | 14 | 1x02-1MP – 1x15-1MP | `JST_SH_BM02B-SRSS-TB_1x02-1MP_P1.00mm_Vertical` |
| `SH` | `JST_SH_SM<n>B-SRSS-TB` | 1.00mm | Horizontal | 15 | 1x02-1MP – 1x20-1MP | `JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal` |
| `SHD` | `JST_SHD_BM<n>B-SRDS-A-G-TF` | **1.0mm** | Vertical | 4 | 2x10-1MP – 2x25-1MP | `JST_SHD_BM20B-SRDS-A-G-TF_2x10-1MP_P1.0mm_Vertical` |
| `SHD` | `JST_SHD_BM<n>B-SRDS-G-TF` | **1.0mm** | Vertical | 4 | 2x10-1MP – 2x25-1MP | `JST_SHD_BM20B-SRDS-G-TF_2x10-1MP_P1.0mm_Vertical` |
| `SHD` | `JST_SHD_SM<n>B-SRDS-G-TF` | **1.0mm** | Horizontal | 4 | 2x10-1MP – 2x25-1MP | `JST_SHD_SM20B-SRDS-G-TF_2x10-1MP_P1.0mm_Horizontal` |
| `SHL` | `JST_SHL_SM<n>B-SHLS-TF` | 1.00mm | Horizontal | 14 | 1x02-1MP – 1x30-1MP | `JST_SHL_SM02B-SHLS-TF_1x02-1MP_P1.00mm_Horizontal` |
| `SUR` | `JST_SUR_BM<n>B-SURS-TF` | 0.80mm | Vertical | 13 | 1x02-1MP – 1x20-1MP | `JST_SUR_BM02B-SURS-TF_1x02-1MP_P0.80mm_Vertical` |
| `SUR` | `JST_SUR_SM<n>B-SURS-TF` | 0.80mm | Horizontal | 14 | 1x02-1MP – 1x22-1MP | `JST_SUR_SM02B-SURS-TF_1x02-1MP_P0.80mm_Horizontal` |
| `VH` | `JST_VH_B<n>P-VH` | 3.96mm | Vertical | 9 | 1x02 – 1x10 | `JST_VH_B2P-VH_1x02_P3.96mm_Vertical` |
| `VH` | `JST_VH_B<n>P-VH-B` | 3.96mm | Vertical | 10 | 1x02 – 1x11 | `JST_VH_B2P-VH-B_1x02_P3.96mm_Vertical` |
| `VH` | `JST_VH_B<n>P-VH-FB-B` | 3.96mm | Vertical | 9 | 1x02 – 1x10 | `JST_VH_B2P-VH-FB-B_1x02_P3.96mm_Vertical` |
| `VH` | `JST_VH_B<n>P3-VH` | **7.92mm** | Vertical | 1 | 1x02 | `JST_VH_B2P3-VH_1x02_P7.92mm_Vertical` |
| `VH` | `JST_VH_B<n>PS-VH` | 3.96mm | Horizontal | 9 | 1x02 – 1x10 | `JST_VH_B2PS-VH_1x02_P3.96mm_Horizontal` |
| `VH` | `JST_VH_S<n>P-VH` | 3.96mm | Horizontal | 6 | 1x02 – 1x07 | `JST_VH_S2P-VH_1x02_P3.96mm_Horizontal` |
| `XA` | `JST_XA_B<n>B-XASK-1` | 2.50mm | Vertical | 16 | 1x02 – 1x20 | `JST_XA_B02B-XASK-1_1x02_P2.50mm_Vertical` |
| `XA` | `JST_XA_B<n>B-XASK-1-A` | 2.50mm | Vertical | 15 | 1x02 – 1x20 | `JST_XA_B02B-XASK-1-A_1x02_P2.50mm_Vertical` |
| `XA` | `JST_XA_S<n>B-XASK-1` | 2.50mm | Horizontal | 13 | 1x02 – 1x14 | `JST_XA_S02B-XASK-1_1x02_P2.50mm_Horizontal` |
| `XA` | `JST_XA_S<n>B-XASK-1N-BN` | 2.50mm | Horizontal | 13 | 1x02 – 1x14 | `JST_XA_S02B-XASK-1N-BN_1x02_P2.50mm_Horizontal` |
| `XAG` | `JST_XAG_SM<n>B-XAGKS-BN-TB` | 2.50mm | Horizontal | 1 | 1x05-1MP | `JST_XAG_SM05B-XAGKS-BN-TB_1x05-1MP_P2.50mm_Horizontal` |
| `XH` | `JST_XH_B<n>B-XH-A` | 2.50mm | Vertical | 16 | 1x02 – 1x20 | `JST_XH_B2B-XH-A_1x02_P2.50mm_Vertical` |
| `XH` | `JST_XH_B<n>B-XH-AM` | 2.50mm | Vertical | 11 | 1x01 – 1x12 | `JST_XH_B1B-XH-AM_1x01_P2.50mm_Vertical` |
| `XH` | `JST_XH_S<n>B-XH-A` | 2.50mm | Horizontal | 15 | 1x02 – 1x16 | `JST_XH_S2B-XH-A_1x02_P2.50mm_Horizontal` |
| `XH` | `JST_XH_S<n>B-XH-A-1` | 2.50mm | Horizontal | 14 | 1x02 – 1x15 | `JST_XH_S2B-XH-A-1_1x02_P2.50mm_Horizontal` |
| `XH` | `JST_XH_S<n>B-XH-SM4-TB` | 2.50mm | Horizontal | 3 | 1x03-1MP – 1x06-1MP | `JST_XH_S3B-XH-SM4-TB_1x03-1MP_P2.50mm_Horizontal` |
| `ZE` | `JST_ZE_BM<n>B-ZESS-TBT` | 1.50mm | Vertical | 15 | 1x02-1MP – 1x16-1MP | `JST_ZE_BM02B-ZESS-TBT_1x02-1MP_P1.50mm_Vertical` |
| `ZE` | `JST_ZE_B<n>B-ZESK-1D` | 1.50mm | Vertical | 15 | 1x02 – 1x16 | `JST_ZE_B02B-ZESK-1D_1x02_P1.50mm_Vertical` |
| `ZE` | `JST_ZE_B<n>B-ZESK-D` | 1.50mm | Vertical | 14 | 1x03 – 1x16 | `JST_ZE_B03B-ZESK-D_1x03_P1.50mm_Vertical` |
| `ZE` | `JST_ZE_SM<n>B-ZESS-TB` | 1.50mm | Horizontal | 15 | 1x02-1MP – 1x16-1MP | `JST_ZE_SM02B-ZESS-TB_1x02-1MP_P1.50mm_Horizontal` |
| `ZE` | `JST_ZE_S<n>B-ZESK-2D` | 1.50mm | Horizontal | 15 | 1x02 – 1x16 | `JST_ZE_S02B-ZESK-2D_1x02_P1.50mm_Horizontal` |
| `ZH` | `JST_ZH_B<n>B-ZR` | 1.50mm | Vertical | 11 | 1x02 – 1x12 | `JST_ZH_B2B-ZR_1x02_P1.50mm_Vertical` |
| `ZH` | `JST_ZH_B<n>B-ZR-SM4-TF` | 1.50mm | Vertical | 12 | 1x02-1MP – 1x13-1MP | `JST_ZH_B2B-ZR-SM4-TF_1x02-1MP_P1.50mm_Vertical` |
| `ZH` | `JST_ZH_S<n>B-ZR-SM4A-TF` | 1.50mm | Horizontal | 12 | 1x02-1MP – 1x13-1MP | `JST_ZH_S2B-ZR-SM4A-TF_1x02-1MP_P1.50mm_Horizontal` |

**JST prefix decoder (read the vendor MPN, don't guess the footprint):** `B…` = top entry / vertical; `S…` = side entry / horizontal; `BM…`/`SM…` = SMD (these always get `-1MP`); trailing `-A`/`-K`/`-D` etc. are vendor housing variants that must be reproduced literally.

---

## 4. FFC / FPC — `Connector_FFC-FPC.pretty`, 372 files

Three mutually incompatible geometry dialects coexist here: `1xNN`, `2xNN`, and `2Rows-NNPins`. There is no series token — vendor goes straight to MPN.

| Vendor + series | Files | Geometry range | Confirmed example |
|---|---:|---|---|
| `Amphenol_F32Q` | 57 | 1x04 – 1x60 | `Amphenol_F32Q-1A7x1-11004_1x04-1MP_P0.5mm_Horizontal` |
| `Amphenol_F32R` | 57 | 1x04 – 1x60 | `Amphenol_F32R-1A7x1-11004_1x04-1MP_P0.5mm_Horizontal` |
| `Hirose_FH12` | 28 | 1x06 – 1x53 | `Hirose_FH12-6S-0.5SH_1x06-1MP_P0.50mm_Horizontal` |
| `Hirose_FH26` | 21 | 2Rows-13Pins – 2Rows-71Pins | `Hirose_FH26-13S-0.3SHW_2Rows-13Pins-1MP_P0.60mm_Horizontal` |
| `Hirose_FH41` | 1 | 1x30 | `Hirose_FH41-30S-0.5SH_1x30_1MP_1SH_P0.5mm_Horizontal` |
| `JAE_FF08xxSA1` | 6 | 2Rows-25Pins – 2Rows-81Pins | `JAE_FF0825SA1_2Rows-25Pins_P0.40mm_Horizontal` |
| `JUSHUO_AFA07` | 26 | 1x4 – 1x29 | `JUSHUO_AFA07-S04FCA-00_1x4-1MP_P1.0mm_Horizontal` |
| `Jushuo_AFC07` | 2 | 1x6 – 1x24 | `Jushuo_AFC07-S06FCA-00_1x6-1MP_P0.50_Horizontal` |
| `Molex_200528` | 27 | 1x04 – 1x30 | `Molex_200528-0040_1x04-1MP_P1.00mm_Horizontal` |
| `Molex_502231` | 3 | 1x15 – 1x33 | `Molex_502231-1500_1x15-1SH_P0.5mm_Vertical` |
| `Molex_502244` | 3 | 1x15 – 1x33 | `Molex_502244-1530_1x15-1MP_P0.5mm_Horizontal` |
| `Molex_502250` | 9 | 2Rows-17Pins – 2Rows-51Pins | `Molex_502250-1791_2Rows-17Pins-1MP_P0.60mm_Horizontal` |
| `Molex_52559` | 1 | 2x18 | `Molex_52559-3652_2x18-1MP_P0.5mm_Vertical` |
| `Molex_54132` | 1 | 1x50 | `Molex_54132-5033_1x50-1MP_P0.5mm_Horizontal` |
| `Molex_54548` | 1 | 1x10 | `Molex_54548-1071_1x10-1MP_P0.5mm_Horizontal` |
| `Omron_XF2M` | 1 | 1x40 | `Omron_XF2M-4015-1A_1x40-1MP_P0.5mm_Horizontal` |
| `TE_1734839` | 46 | 1x05 – 1x50 | `TE_0-1734839-5_1x05-1MP_P0.5mm_Horizontal` |
| `TE_84952` | 27 | 1x04 – 1x30 | `TE_84952-4_1x04-1MP_P1.0mm_Horizontal` |
| `TE_84953` | 27 | 1x04 – 1x30 | `TE_84953-4_1x04-1MP_P1.0mm_Horizontal` |
| `TE_84982` | 27 | 2Rows-04Pins – 2Rows-30Pins | `TE_84982-4_2Rows-04Pins-P1.0mm_Vertical` |
| `Wuerth_68611214422` | 1 | 1x12 | `Wuerth_68611214422_1x12-1MP_P1.0mm_Horizontal` |

---

## 5. USB — `Connector_USB.pretty`, all 75 files verbatim

No pitch, no position count. Shape: `USB[3]_<Type>_[Receptacle_|Plug_]<Vendor>_<MPN>[_<Orientation>][_<Variant>]`.

| Type | Verbatim footprint name |
|---|---|
| A (14) | `USB_A_CNCTech_1001-011-01101_Horizontal` |
| | `USB_A_Connfly_DS1095` |
| | `USB_A_Connfly_DS1098_Horizontal` |
| | `USB_A_CUI_UJ2-ADH-TH_Horizontal_Stacked` |
| | `USB_A_Kycon_KUSBX-AS1N-B_Horizontal` |
| | `USB_A_Molex_105057_Vertical` |
| | `USB_A_Molex_48037-2200_Horizontal` |
| | `USB_A_Molex_67643_Horizontal` |
| | `USB_A_Receptacle_GCT_USB1046` |
| | `USB_A_Receptacle_XKB_U231-091N-4BLRA00-S` |
| | `USB_A_Stewart_SS-52100-001_Horizontal` |
| | `USB_A_TE_292303-7_Horizontal` |
| | `USB_A_Wuerth_614004134726_Horizontal` |
| | `USB_A_Wuerth_61400826021_Horizontal_Stacked` |
| B (4) | `USB_B_Amphenol_MUSB-D511_Vertical_Rugged` |
| | `USB_B_Lumberg_2411_02_Horizontal` |
| | `USB_B_OST_USB-B1HSxx_Horizontal` |
| | `USB_B_TE_5787834_Vertical` |
| **C — plug (3)** | `USB_C_Plug_JAE_DX07P024AJ1` |
| | `USB_C_Plug_Molex_105444` |
| | `USB_C_Plug_ShenzhenJingTuoJin_918-118A2021Y40002_Vertical` |
| **C — receptacle (26)** | `USB_C_Receptacle_Amphenol_12401548E4-2A` |
| | `USB_C_Receptacle_Amphenol_12401548E4-2A_CircularHoles` |
| | `USB_C_Receptacle_Amphenol_12401610E4-2A` |
| | `USB_C_Receptacle_Amphenol_12401610E4-2A_CircularHoles` |
| | `USB_C_Receptacle_Amphenol_12401948E412A` |
| | `USB_C_Receptacle_Amphenol_124019772112A` |
| | `USB_C_Receptacle_CNCTech_C-ARA1-AK51X` |
| | `USB_C_Receptacle_G-Switch_GT-USB-7010ASV` |
| | `USB_C_Receptacle_G-Switch_GT-USB-7025` |
| | `USB_C_Receptacle_G-Switch_GT-USB-7051x` |
| | `USB_C_Receptacle_GCT_USB4085` |
| | `USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal` |
| | `USB_C_Receptacle_GCT_USB4110` |
| | `USB_C_Receptacle_GCT_USB4115-03-C` |
| | `USB_C_Receptacle_GCT_USB4125-xx-x_6P_TopMnt_Horizontal` |
| | `USB_C_Receptacle_GCT_USB4125-xx-x-0190_6P_TopMnt_Horizontal` |
| | `USB_C_Receptacle_GCT_USB4135-GF-A_6P_TopMnt_Horizontal` |
| | `USB_C_Receptacle_HCTL_HC-TYPE-C-16P-01A` |
| | `USB_C_Receptacle_HRO_TYPE-C-31-M-12` |
| | `USB_C_Receptacle_HRO_TYPE-C-31-M-17` |
| | `USB_C_Receptacle_JAE_DX07S016JA1R1500` |
| | `USB_C_Receptacle_JAE_DX07S024WJ1R350` |
| | `USB_C_Receptacle_JAE_DX07S024WJ3R400` |
| | `USB_C_Receptacle_Molex_105450-0101` |
| | `USB_C_Receptacle_Palconn_UTC16-G` |
| | `USB_C_Receptacle_XKB_U262-16XN-4BVC11` |
| Micro-AB (1) | `USB_Micro-AB_Molex_47590-0001` |
| Micro-B (17) | `USB_Micro-B_Amphenol_10103594-0001LF_Horizontal` |
| | `USB_Micro-B_Amphenol_10104110_Horizontal` |
| | `USB_Micro-B_Amphenol_10118193-0001LF_Horizontal` |
| | `USB_Micro-B_Amphenol_10118193-0002LF_Horizontal` |
| | `USB_Micro-B_Amphenol_10118194_Horizontal` |
| | `USB_Micro-B_Amphenol_10118194-0001LF_Horizontal` |
| | `USB_Micro-B_GCT_USB3076-30-A` |
| | `USB_Micro-B_Molex_47346-0001` |
| | `USB_Micro-B_Molex-105017-0001` |
| | `USB_Micro-B_Molex-105133-0001` |
| | `USB_Micro-B_Molex-105133-0031` |
| | `USB_Micro-B_Technik_TWP-4002D-H3` |
| | `USB_Micro-B_Wuerth_614105150721_Vertical` |
| | `USB_Micro-B_Wuerth_614105150721_Vertical_CircularHoles` |
| | `USB_Micro-B_Wuerth_629105150521` |
| | `USB_Micro-B_Wuerth_629105150521_CircularHoles` |
| | `USB_Micro-B_XKB_U254-051T-4BH83-F1S` |
| Mini-B (5) | `USB_Mini-B_AdamTech_MUSB-B5-S-VT-TSMT-1_SMD_Vertical` |
| | `USB_Mini-B_Lumberg_2486_01_Horizontal` |
| | `USB_Mini-B_Tensility_54-00023_Vertical` |
| | `USB_Mini-B_Tensility_54-00023_Vertical_CircularHoles` |
| | `USB_Mini-B_Wuerth_65100516121_Horizontal` |
| USB 3 (5) | `USB3_A_Molex_48393-001` |
| | `USB3_A_Molex_48406-0001_Horizontal_Stacked` |
| | `USB3_A_Plug_Wuerth_692112030100_Horizontal` |
| | `USB3_A_Receptacle_Wuerth_692122030100` |
| | `USB3_Micro-B_Connfly_DS1104-01` |

---

## 6. RJ (modular jacks) — `Connector_RJ.pretty`, all 38 files verbatim

| Family | Verbatim footprint name |
|---|---|
| RJ9 | `RJ9_Evercom_5301-440xxx_Horizontal` |
| RJ12 | `RJ12_Amphenol_54601-x06_Horizontal` |
| RJ14 | `RJ14_Connfly_DS1133-S4_Horizontal` |
| RJ25 | `RJ25_Wayconn_MJEA-660X1_Horizontal` |
| **RJ45 (34)** | `RJ45_Abracon_ARJP11A-MA_Horizontal` |
| | `RJ45_Amphenol_54602-x08_Horizontal` |
| | `RJ45_Amphenol_RJHSE5380` |
| | `RJ45_Amphenol_RJHSE5380-08` |
| | `RJ45_Amphenol_RJHSE538X` |
| | `RJ45_Amphenol_RJHSE538X-02` |
| | `RJ45_Amphenol_RJHSE538X-04` |
| | `RJ45_Amphenol_RJMG1BD3B8K1ANR` |
| | `RJ45_Bel_SI-60062-F` |
| | `RJ45_BEL_SS74301-00x_Vertical` |
| | `RJ45_Bel_V895-1001-AW_Vertical` |
| | `RJ45_Cetus_J1B1211CCD_Horizontal` |
| | `RJ45_Connfly_DS1128-09-S8xx-S_Horizontal` |
| | `RJ45_HALO_HFJ11-x2450E-LxxRL_Horizontal` |
| | `RJ45_HALO_HFJ11-x2450ERL_Horizontal` |
| | `RJ45_HALO_HFJ11-x2450HRL_Horizontal` |
| | `RJ45_Hanrun_HR911105A_Horizontal` |
| | `RJ45_Kycon_G7LX-A88S7-BP-xx_Horizontal` |
| | `RJ45_Molex_0855135013_Vertical` |
| | `RJ45_Molex_9346520x_Horizontal` |
| | `RJ45_Ninigi_GE` |
| | `RJ45_OST_PJ012-8P8CX_Vertical` |
| | `RJ45_Plug_Metz_AJP92A8813` |
| | `RJ45_Pulse_JK00177NL_Horizontal` |
| | `RJ45_Pulse_JK0654219NL_Horizontal` |
| | `RJ45_Pulse_JXD6-0001NL_Horizontal` |
| | `RJ45_RCH_RC01937` |
| | `RJ45_UDE_RB1-125B8G1A` |
| | `RJ45_Wuerth_74980111211_Horizontal` |
| | `RJ45_Wuerth_7499010001A_Horizontal` |
| | `RJ45_Wuerth_7499010121A_Horizontal` |
| | `RJ45_Wuerth_7499010211A_Horizontal` |
| | `RJ45_Wuerth_7499111446_Horizontal` |
| | `RJ45_Wuerth_7499151120_Horizontal` |

---

## 7. Coaxial (U.FL / SMA / MMCX / BNC / …) — `Connector_Coaxial.pretty`, all 37 files verbatim

Shape: `<Interface>_<Vendor>_<MPN>_<Mount>`. Mount vocabulary here is `Vertical`, `Horizontal`, `EdgeMount` — never `SMD`/`THT`.

| Interface | Verbatim footprint name |
|---|---|
| **U.FL (2)** | `U.FL_Hirose_U.FL-R-SMT-1_Vertical` |
| | `U.FL_Molex_MCRF_73412-0110_Vertical` |
| **SMA (18)** | `SMA_Amphenol_132134_Vertical` |
| | `SMA_Amphenol_132134-10_Vertical` |
| | `SMA_Amphenol_132134-11_Vertical` |
| | `SMA_Amphenol_132134-14_Vertical` |
| | `SMA_Amphenol_132134-16_Vertical` |
| | `SMA_Amphenol_132203-12_Horizontal` |
| | `SMA_Amphenol_132289_EdgeMount` |
| | `SMA_Amphenol_132291_Vertical` |
| | `SMA_Amphenol_132291-12_Vertical` |
| | `SMA_Amphenol_901-143_Horizontal` |
| | `SMA_Amphenol_901-144_Vertical` |
| | `SMA_BAT_Wireless_BWSMA-KWE-Z001` |
| | `SMA_Molex_73251-1153_EdgeMount_Horizontal` |
| | `SMA_Molex_73251-2120_EdgeMount_Horizontal` |
| | `SMA_Molex_73251-2200_Horizontal` |
| | `SMA_Samtec_SMA-J-P-H-ST-EM1_EdgeMount` |
| | `SMA_Wurth_60312002114503_Vertical` |
| | `SMA_Wurth_60312102114405_Vertical` |
| **MMCX (4)** | `MMCX_Molex_73415-0961_Horizontal_0.8mm-PCB` |
| | `MMCX_Molex_73415-0961_Horizontal_1.0mm-PCB` |
| | `MMCX_Molex_73415-0961_Horizontal_1.6mm-PCB` |
| | `MMCX_Molex_73415-1471_Vertical` |
| | `WR-MMCX_Wuerth_66011102111302_Horizontal` |
| | `WR-MMCX_Wuerth_66012102111404_Vertical` |
| **BNC (7)** | `BNC_Amphenol_031-5539_Vertical` |
| | `BNC_Amphenol_031-6575_Horizontal` |
| | `BNC_Amphenol_B6252HB-NPP3G-50_Horizontal` |
| | `BNC_PanelMountable_Vertical` |
| | `BNC_TEConnectivity_1478035_Horizontal` |
| | `BNC_TEConnectivity_1478204_Vertical` |
| | `BNC_Win_364A2x95_Horizontal` |
| **SMB (1)** | `SMB_Jack_Vertical` |
| **Switch / other (3)** | `CoaxialSwitch_Hirose_MS-156C3_Horizontal` |
| | `LEMO-EPG.00.302.NLN` |
| | `LEMO-EPL.00.250.NTN` |

---

## 8. Card sockets (microSD / SIM / nanoSIM / SD / CF) — `Connector_Card.pretty`, all 20 files verbatim

No pitch, no position count, no orientation.

| Card type | Verbatim footprint name |
|---|---|
| microSD (6) | `microSD_HC_Hirose_DM3AT-SF-PEJM5` |
| | `microSD_HC_Hirose_DM3BT-DSF-PEJS` |
| | `microSD_HC_Hirose_DM3D-SF` |
| | `microSD_HC_Molex_104031-0811` |
| | `microSD_HC_Molex_47219-2001` |
| | `microSD_HC_Wuerth_693072010801` |
| microSIM (1) | `microSIM_JAE_SF53S006VCBR2000` |
| nanoSIM (3) | `nanoSIM_GCT_SIM8060-6-0-14-00` |
| | `nanoSIM_GCT_SIM8060-6-1-14-00` |
| | `nanoSIM_Hinged_CUI_NSIM-2-C` |
| SD full-size (7) | `SD_Card_Device_16mm_SlotDepth` |
| | `SD_Hirose_DM1AA_SF_PEJ82` |
| | `SD_Kyocera_145638009211859+` |
| | `SD_Kyocera_145638009511859+` |
| | `SD_Kyocera_145638109211859+` |
| | `SD_Kyocera_145638109511859+` |
| | `SD_TE_2041021` |
| Combo (1) | `SD-SIM_microSD-microSIM_Molex_104168-1620` |
| CompactFlash (2) | `CF-Card_3M_N7E50-A516xx-30` |
| | `CF-Card_3M_N7E50-E516xx-30` |

---

## 9. Terminal blocks — Tier B without exception

**Corrected premise:** there is no generic terminal-block naming. Across all 14 `TerminalBlock_*.pretty` libraries (731 files) **zero** footprints omit the vendor token; a query for `TerminalBlock_<geometry>…` returns 0 hits.

### 9a. `TerminalBlock.pretty` — 45 files (still vendor-named)

| Vendor series | Files | Range | Orientation token | Confirmed example |
|---|---:|---|---|---|
| `TerminalBlock_MaiXu_MX126-5.0-<n>P` | 24 | 1x02 – 1x24 | *(none — omitted)* | `TerminalBlock_MaiXu_MX126-5.0-24P_1x24_P5.00mm` |
| `TerminalBlock_Xinya_XY308-2.54-<n>P` | 21 | 1x02 – 1x23 | `Horizontal` | `TerminalBlock_Xinya_XY308-2.54-2P_1x02_P2.54mm_Horizontal` |

### 9b. `TerminalBlock_Phoenix.pretty` — 126 files

| Filename template (`NN` = vendor position digits, unpadded) | Files | Geometry range | Confirmed example |
|---|---:|---|---|
| `TerminalBlock_Phoenix_MKDS-1-NN-3.81_1xNN_P3.81mm_Horizontal` | 12 | 1x02 – 1x13 | `TerminalBlock_Phoenix_MKDS-1-2-3.81_1x02_P3.81mm_Horizontal` |
| `TerminalBlock_Phoenix_MKDS-1,5-NN_1xNN_P5.00mm_Horizontal` | 15 | 1x02 – 1x16 | `TerminalBlock_Phoenix_MKDS-1,5-2_1x02_P5.00mm_Horizontal` |
| `TerminalBlock_Phoenix_MKDS-1,5-NN-5.08_1xNN_P5.08mm_Horizontal` | 15 | 1x02 – 1x16 | `TerminalBlock_Phoenix_MKDS-1,5-2-5.08_1x02_P5.08mm_Horizontal` |
| `TerminalBlock_Phoenix_MKDS-3-NN-5.08_1xNN_P5.08mm_Horizontal` | 15 | 1x02 – 1x16 | `TerminalBlock_Phoenix_MKDS-3-2-5.08_1x02_P5.08mm_Horizontal` |
| `TerminalBlock_Phoenix_MPT-0,5-NN-2.54_1xNN_P2.54mm_Horizontal` | 11 | 1x02 – 1x12 | `TerminalBlock_Phoenix_MPT-0,5-2-2.54_1x02_P2.54mm_Horizontal` |
| `TerminalBlock_Phoenix_PT-1,5-NN-3.5-H_1xNN_P3.50mm_Horizontal` | 15 | 1x02 – 1x16 | `TerminalBlock_Phoenix_PT-1,5-2-3.5-H_1x02_P3.50mm_Horizontal` |
| `TerminalBlock_Phoenix_PT-1,5-NN-5.0-H_1xNN_P5.00mm_Horizontal` | 15 | 1x02 – 1x16 | `TerminalBlock_Phoenix_PT-1,5-2-5.0-H_1x02_P5.00mm_Horizontal` |
| `TerminalBlock_Phoenix_PTSM-0,5-NN-2.5-H-THR_1xNN_P2.50mm_Horizontal` | 7 | 1x02 – 1x08 | `TerminalBlock_Phoenix_PTSM-0,5-2-2.5-H-THR_1x02_P2.50mm_Horizontal` |
| `TerminalBlock_Phoenix_PTSM-0,5-NN-2.5-V-THR_1xNN_P2.50mm_Vertical` | 7 | 1x02 – 1x08 | `TerminalBlock_Phoenix_PTSM-0,5-2-2.5-V-THR_1x02_P2.50mm_Vertical` |
| `TerminalBlock_Phoenix_PTSM-0,5-NN-2,5-V-SMD_1xNN-1MP_P2.50mm_Vertical` | 7 | 1x02 – 1x08 | `TerminalBlock_Phoenix_PTSM-0,5-2-2,5-V-SMD_1x02-1MP_P2.50mm_Vertical` |
| `TerminalBlock_Phoenix_PTSM-0,5-NN-HV-2.5-SMD_1xNN-1MP_P2.50mm_Vertical` | 7 | 1x02 – 1x08 | `TerminalBlock_Phoenix_PTSM-0,5-2-HV-2.5-SMD_1x02-1MP_P2.50mm_Vertical` |

### 9c. `TerminalBlock_WAGO.pretty` — 170 files

| Series template | Files | Geometry range | Orientation token | Confirmed example |
|---|---:|---|---|---|
| `TerminalBlock_WAGO_233-<nnn>` | 10 | 2x02 – 2x12 | *(none)* | `TerminalBlock_WAGO_233-502_2x02_P2.54mm` |
| `TerminalBlock_WAGO_236-1xx / 236-4xx` | 38 | 1x01 – 1x48 | `45Degree` @ P5.00mm | `TerminalBlock_WAGO_236-101_1x01_P5.00mm_45Degree` |
| `TerminalBlock_WAGO_236-2xx / 236-5xx` | 34 | 1x01 – 1x24 | `45Degree` @ P7.50mm | `TerminalBlock_WAGO_236-201_1x01_P7.50mm_45Degree` |
| `TerminalBlock_WAGO_236-3xx / 236-6xx` | 34 | 1x01 – 1x24 | `45Degree` @ P10.00mm | `TerminalBlock_WAGO_236-601_1x01_P10.00mm_45Degree` |
| `TerminalBlock_WAGO_2601-11xx` | 10 | 1x02 – 1x12 | `Horizontal` @ P3.50mm | `TerminalBlock_WAGO_2601-1102_1x02_P3.50mm_Horizontal` |
| `TerminalBlock_WAGO_2601-31xx` | 13 | 1x02 – 1x24 | `Vertical` @ P3.50mm | `TerminalBlock_WAGO_2601-3102_1x02_P3.50mm_Vertical` |
| `TerminalBlock_WAGO_804-1xx` | 17 | 1x01 – 1x24 | `45Degree` @ P5.00mm | `TerminalBlock_WAGO_804-101_1x01_P5.00mm_45Degree` |
| `TerminalBlock_WAGO_804-3xx` | 14 | 1x01 – 1x24 | `45Degree` @ P7.50mm | `TerminalBlock_WAGO_804-301_1x01_P7.50mm_45Degree` |

---

## 10. Phoenix pluggable headers (MC / MSTB) — 360 files

Vendor prefix is `PhoenixContact_` (not `Phoenix_`, which is the terminal-block prefix). The wire-size token uses a **comma** decimal (`1,5`), while the pitch token in the same name uses a **dot** (`3.81`) — and the MSTB pitch-in-MPN uses a comma (`5,08`) while the pitch token uses a dot (`P5.08mm`).

| Series template | Files | Geometry range | Confirmed example |
|---|---:|---|---|
| `PhoenixContact_MC_1,5_NN-G-3.5_1xNN_P3.50mm_Horizontal` | 15 | 1x02 – 1x16 | `PhoenixContact_MC_1,5_2-G-3.5_1x02_P3.50mm_Horizontal` |
| `PhoenixContact_MC_1,5_NN-G-3.81_1xNN_P3.81mm_Horizontal` | 15 | 1x02 – 1x16 | `PhoenixContact_MC_1,5_16-G-3.81_1x16_P3.81mm_Horizontal` |
| `PhoenixContact_MC_1,5_NN-GF-3.5_1xNN_P3.50mm_Horizontal_ThreadedFlange` | 15 | 1x02 – 1x16 | `PhoenixContact_MC_1,5_2-GF-3.5_1x02_P3.50mm_Horizontal_ThreadedFlange` |
| `…_Horizontal_ThreadedFlange_MountHole` | 15 | 1x02 – 1x16 | `PhoenixContact_MC_1,5_2-GF-3.5_1x02_P3.50mm_Horizontal_ThreadedFlange_MountHole` |
| `PhoenixContact_MC_1,5_NN-GF-3.81_…` (both flange forms) | 30 | 1x02 – 1x16 | `PhoenixContact_MC_1,5_2-GF-3.81_1x02_P3.81mm_Horizontal_ThreadedFlange` |
| `PhoenixContact_MCV_1,5_NN-G-3.5_1xNN_P3.50mm_Vertical` | 15 | 1x02 – 1x16 | `PhoenixContact_MCV_1,5_2-G-3.5_1x02_P3.50mm_Vertical` |
| `PhoenixContact_MCV_1,5_NN-G-3.81 / -GF-3.5 / -GF-3.81 (+MountHole)` | 75 | 1x02 – 1x16 | `PhoenixContact_MCV_1,5_16-GF-3.81_1x16_P3.81mm_Vertical_ThreadedFlange_MountHole` |
| `PhoenixContact_MSTBA_2,5_NN-G_1xNN_P5.00mm_Horizontal` | 15 | 1x02 – 1x16 | `PhoenixContact_MSTBA_2,5_2-G_1x02_P5.00mm_Horizontal` |
| `PhoenixContact_MSTBA_2,5_NN-G-5,08_1xNN_P5.08mm_Horizontal` | 15 | 1x02 – 1x16 | `PhoenixContact_MSTBA_2,5_16-G-5,08_1x16_P5.08mm_Horizontal` |
| `PhoenixContact_MSTB_2,5_NN-GF[-5,08]_1xNN_P5.0Xmm_Horizontal_ThreadedFlange[_MountHole]` | 60 | 1x02 – 1x16 | `PhoenixContact_MSTB_2,5_2-GF_1x02_P5.00mm_Horizontal_ThreadedFlange` |
| `PhoenixContact_MSTBVA_2,5_NN-G[-5,08]_1xNN_P5.0Xmm_Vertical` | 30 | 1x02 – 1x16 | `PhoenixContact_MSTBVA_2,5_2-G_1x02_P5.00mm_Vertical` |
| `PhoenixContact_MSTBV_2,5_NN-GF[-5,08]_1xNN_P5.0Xmm_Vertical_ThreadedFlange[_MountHole]` | 60 | 1x02 – 1x16 | `PhoenixContact_MSTBV_2,5_16-GF-5,08_1x16_P5.08mm_Vertical_ThreadedFlange_MountHole` |

---

## 11. Molex — `Connector_Molex.pretty`, 812 files, 21 series

Molex is the one vendor library that **does** carry a series token (`Molex_<Series>_<MPN>_…`), same as JST.

| Series token | Files | Confirmed example |
|---|---:|---|
| `Micro-Fit` | 149 | `Molex_Micro-Fit_3.0_43045-0200_2x01_P3.00mm_Horizontal` |
| `Mini-Fit` | 78 | `Molex_Mini-Fit_Jr_5566-02A_2x01_P4.20mm_Vertical` |
| `CLIK-Mate` | 78 | `Molex_CLIK-Mate_502382-0270_1x02-1MP_P1.25mm_Vertical` |
| `SlimStack` | 66 | `Molex_SlimStack_501920-3001_2x15_P0.50mm_Vertical` |
| `PicoBlade` | 57 | `Molex_PicoBlade_53047-0210_1x02_P1.25mm_Vertical` |
| `MicroClasp` | 56 | `Molex_MicroClasp_55932-0210_1x02_P2.00mm_Vertical` |
| `KK-396` | 45 | `Molex_KK-396_5273-02A_1x02_P3.96mm_Vertical` |
| `Sabre` | 40 | `Molex_Sabre_43160-0102_1x02_P7.49mm_Vertical_ThermalVias` |
| `SPOX` | 28 | `Molex_SPOX_5267-02A_1x02_P2.50mm_Vertical` |
| `Pico-Clasp` | 28 | `Molex_Pico-Clasp_202396-0207_1x02-1MP_P1.00mm_Horizontal` |
| `Nano-Fit` | 28 | `Molex_Nano-Fit_105309-xx02_1x02_P2.50mm_Vertical` |
| `Micro-Latch` | 28 | `Molex_Micro-Latch_53253-0270_1x02_P2.00mm_Vertical` |
| `SL` | 24 | `Molex_SL_171971-0002_1x02_P2.54mm_Vertical` |
| `Picoflex` | 24 | `Molex_Picoflex_90325-0004_2x02_P1.27mm_Vertical` |
| `Mega-Fit` | 18 | `Molex_Mega-Fit_76825-0002_2x01_P5.70mm_Horizontal` |
| `Pico-Lock` | 16 | `Molex_Pico-Lock_205338-0002_1x02-1MP_P2.00mm_Horizontal` |
| `KK-254` | 15 | `Molex_KK-254_AE-6410-02A_1x02_P2.54mm_Vertical` |
| `Panelmate` | 14 | `Molex_Panelmate_53780-0270_1x02-1MP_P1.25mm_Horizontal` |
| `DuraClik` | 14 | `Molex_DuraClik_502352-0200_1x02-1MP_P2.00mm_Horizontal` |
| `Pico-EZmate` | 5 | `Molex_Pico-EZmate_78171-0002_1x02-1MP_P1.20mm_Vertical` |
| `Pico-SPOX` | 1 | `Molex_Pico-SPOX_87437-1443_1x14-P1.5mm_Vertical` |

---

## 12. `-1MP` / `-1SH` census (whole 15 447-file tree)

| Token | Occurrences | Where |
|---|---:|---|
| `-1MP` | **1 102** | FFC-FPC 335, Molex 264, JST 206, Samtec_MicroMate 76, Hirose 70, IDC 65, Hirose_DF40 25, JAE_WP7B 20, Samtec_MicroPower 18, TerminalBlock_Phoenix 14, Zhaoxing 9 |
| `-2MP`…`-9MP` | **0** | never used |
| `-1SH` | **9** | `Molex_502231-*` (3), `Samtec_LSHM-*` (6, in `Connector_Samtec.pretty`) |
| `_1SH_` | **1** | `Hirose_FH41-30S-0.5SH_1x30_1MP_1SH_P0.5mm_Horizontal` — sole underscore-delimited case |
| `-2SH`+ | **0** | never used |

## How to name a new part in this family

## Naming a brand-new connector from a vendor drawing

### Step 0 — Duplicate check first
`ls` the candidate library and grep the vendor MPN before anything else. Vendors reuse land patterns across MPNs (e.g. one `MMCX_Molex_73415-0961` land pattern ships as three footprints differing only by `_0.8mm-PCB` / `_1.0mm-PCB` / `_1.6mm-PCB`), so an existing file may already cover your part.

### Step 1 — Apply the tier test (from the Grammar section)
Ask: **is this land pattern an industry-standard grid, or proprietary to one manufacturer's series?**

- Uniform grid of identical pads/holes at 1.00 / 1.27 / 2.00 / 2.54 mm, cross-vendor interchangeable → **Tier A**. Go to Step 2.
- Anything else — housing outline, keying, hold-down pads, board cut-out, shield tabs, latch windows, card cavity, defined mating shell → **Tier B**. Go to Step 3.

If you cannot decide, it is Tier B. Tier A is a closed set of three types in stock (`PinHeader`, `PinSocket`, `IDC-Header`); do not invent a fourth generic type.

### Step 2 — Tier A construction
1. Type: `PinHeader` (male pins), `PinSocket` (female receptacle), `IDC-Header` (2.54 mm ribbon-cable box header).
2. Geometry: `<rows>x<NN>`, `NN` **zero-padded to exactly 2 digits** (`1x04`, not `1x4`).
3. Mechanical pads: append `-1MP` to the geometry token **only** if the land pattern has exactly one non-electrical pad. (IDC latch headers: `IDC-Header_2x05-1MP_…`.)
4. Pitch: `P<x.xx>mm` with **two decimal places** (`P2.54mm`, `P1.00mm`).
5. IDC feature token, if any: `Latch`, `Latch6.5mm`, `Latch9.5mm`, `Latch12.0mm` — goes **after** the pitch.
6. Orientation: `Vertical`, `Horizontal`, or `Vertical_SMD`.
7. If `1xNN` **and** `Vertical_SMD`, you must add `_Pin1Left` or `_Pin1Right` (there is no bare single-row SMD name).
8. Verify the file does not already exist; then write into the pitch-specific library (`Connector_PinHeader_<pitch>.pretty`).

### Step 3 — Tier B construction
1. **Interface prefix** — add one only if the sub-family uses it: `USB` / `USB3`, `RJ<n>`, `SMA` / `U.FL` / `MMCX` / `BNC` / `SMB`, `microSD_HC` / `microSIM` / `nanoSIM` / `SD` / `CF-Card`, `TerminalBlock`. JST, Molex, FFC/FPC and Phoenix pluggable headers have **no** interface prefix.
2. **Gender/role** — USB and RJ insert `Receptacle_` or `Plug_` here when the library distinguishes them (`USB_C_Receptacle_GCT_USB4110`, `RJ45_Plug_Metz_AJP92A8813`). Elsewhere gender is encoded in the vendor MPN, not the name.
3. **Vendor** — one token, house-canonical spelling. Copy the spelling already used in that library, do not re-canonicalise: `Wuerth` in `Connector_USB` / `Connector_RJ`, `Wurth` in `Connector_Coaxial`, `PhoenixContact` in `Connector_Phoenix_*`, `Phoenix` in `TerminalBlock_Phoenix`, `TEConnectivity` for coax but `TE` for FFC/FPC.
4. **Series** — include it if and only if the library does. JST and Molex always do (`JST_ZH_…`, `Molex_Micro-Fit_…`). FFC/FPC, USB, RJ, coaxial and card sockets never do.
5. **MPN — copy the datasheet part number character-for-character.** Keep hyphens, commas, plus signs, dots, and the vendor's own (un)padded position digits. `JST_PH_B2B-PH-K` keeps `B2B`; `JST_XA_B02B-XASK-1` keeps `B02B`. Replace only genuinely variable option digits with `x` (`RJ12_Amphenol_54601-x06`, `Molex_Nano-Fit_105309-xx02`).
6. **Geometry token** — pick the dialect the library already uses:
   - `1xNN` / `2xNN`, zero-padded to 2 digits — JST, Molex, terminal blocks, Phoenix, most FFC/FPC.
   - `2Rows-NNPins` — dual-row FFC/FPC only (Hirose FH26, JAE FF08xx, Molex 502250, TE 84982).
   - **Omit entirely** — USB, RJ, coaxial, card sockets.
7. **Mechanical / shield pads** — append `-1MP` per non-electrical mounting pad group (only `-1MP` exists) and/or `-1SH` per shield-pad group (only `-1SH` exists). Both together is the FH41 pattern only.
8. **Pitch** — `P<x.xx>mm`, two decimals. Omit for USB / RJ / coax / card. Dual-pitch parts use `P<a>x<b>mm` (`P2.50x4.00mm`).
9. **Orientation** — `Vertical` (top entry) or `Horizontal` (side entry) for wire-to-board; `Vertical` / `Horizontal` / `EdgeMount` for coax; `45Degree` for WAGO angled blocks. **Never** `SMD` / `THT` as an orientation in Tier B — mount technology is carried by `-1MP` and by the vendor MPN suffix.
10. **Feature suffixes**, in the order the library uses them: `_ThreadedFlange`, `_MountHole`, `_ThermalVias`, `_CircularHoles`, `_Stacked`, `_Rugged`, `_Lock`, `_TopMnt`.

### Step 4 — If the package is genuinely absent from KiCad stock
1. Confirm absence properly: grep the vendor MPN and its land-pattern dimensions across **all 70** `Connector_*` / `TerminalBlock_*` libraries, not just the obvious one — Samtec LSHM lives in `Connector_Samtec.pretty`, not `Connector_Samtec_HLE_SMD.pretty`; Molex FFC parts live in `Connector_FFC-FPC.pretty`, not `Connector_Molex.pretty`.
2. Find the **nearest stocked sibling in the same library** and copy its exact token order and separator style, even if that style is inconsistent with other libraries. The library-local convention wins over any global rule.
3. If no sibling exists (a brand-new vendor or series), copy the shape of the library's dominant pattern and place the new footprint in the 7Sigma namespace rather than editing a stock library. Record the datasheet page number and figure reference for the recommended land pattern in the footprint description.
4. Write the vendor's exact MPN into the footprint's `Value`/description so it stays greppable even if the filename abbreviates option digits to `x`.
5. Re-verify with a literal per-file existence test after writing. Every name in this reference was validated that way; do the same for yours.
6. Route it through a draft proposal — never publish straight into the library.

## Pitfalls

## Traps

### 1. Zero-padding is the rule — with 22 documented exceptions
The geometry token is padded to 2 digits everywhere (`1x04`, `2x07`) **except** 22 files across the whole 15 447-file tree. Seven are in FFC/FPC and you will hit them:
`JUSHUO_AFA07-S04FCA-00_1x4-1MP_P1.0mm_Horizontal` … `JUSHUO_AFA07-S09FCA-00_1x9-1MP_P1.0mm_Horizontal` (6 files) and `Jushuo_AFC07-S06FCA-00_1x6-1MP_P0.50_Horizontal`. The rest are `Connector_DIN.pretty` (`DIN41612_B3_2x5_…`, 6 files) and `Connector_Stocko.pretty` (`Stocko_MKS_1651-6-0-202_1x2_…`, 9 files). Padding your `1x4` to `1x04` in the Jushuo library produces a name that does not exist.

### 2. The MPN's position digits are NOT the geometry token's
JST pads inconsistently in its own part numbers and the footprint copies the MPN literally:
- `JST_PH_B2B-PH-K_1x02_P2.00mm_Vertical` — MPN `B2B` unpadded, geometry `1x02` padded.
- `JST_XA_B02B-XASK-1_1x02_P2.50mm_Vertical` — MPN `B02B` padded, geometry `1x02` padded.
Same for `JST_EH_S2B-EH` vs `JST_ZE_S02B-ZESK-2D`, `JST_VH_B2P-VH` vs `JST_SUR_BM02B-SURS-TF`. Never normalise the MPN half.

### 3. `SH` means two different things
In `Hirose_FH12-6S-0.5SH_1x06-1MP_P0.50mm_Horizontal` the `0.5SH` is part of Hirose's **own MPN** (0.5 mm pitch, shielded) — it is not a shield-pad token. There are 28 `FH12-*-0.5SH` files and **none** of them has a shield-pad token.
The real shield-pad token appears in exactly 10 files tree-wide: `Molex_502231-1500_1x15-1SH_P0.5mm_Vertical` (3), `Samtec_LSHM-105-xx.x-x-DV-S_2x05-1SH_P0.50mm_Vertical` (6), and `Hirose_FH41-30S-0.5SH_1x30_1MP_1SH_P0.5mm_Horizontal` (1 — the only file with both `1MP` and `1SH`, and the only one where the tokens are **underscore**-delimited instead of hyphen-delimited).

### 4. `-1MP` is the only mechanical-pad count that exists
1 102 occurrences of `-1MP`, zero of `-2MP` through `-9MP`. A connector with four hold-down pads still gets `-1MP` (one *group*, not one pad). Do not write `-4MP`.

### 5. Pitch decimal places are not normalised
All of these are real, in the same family: `P0.5mm`, `P0.50mm`, `P1.0mm`, `P1.00mm`, `P1.20mm`, `P1.5mm`. Within JST, `JST_SHD_BM20B-SRDS-A-G-TF_2x10-1MP_P1.0mm_Vertical` uses one decimal while `JST_SH_BM02B-SRSS-TB_1x02-1MP_P1.00mm_Vertical` uses two — same library, different series. Copy the sibling; do not standardise.

### 6. `mm` is sometimes missing
`Jushuo_AFC07-S06FCA-00_1x6-1MP_P0.50_Horizontal` has `P0.50` with no unit. So do the two `Jushuo_AFC07` files and nothing else.

### 7. Underscore vs hyphen before the pitch
`TE_84982-4_2Rows-04Pins-P1.0mm_Vertical` — the separator before `P1.0mm` is a **hyphen** (27 files). Its siblings `TE_84952-4_1x04-1MP_P1.0mm_Horizontal` use an **underscore**. Same vendor, same library.
Likewise `Molex_Pico-SPOX_87437-1443_1x14-P1.5mm_Vertical` hyphenates before the pitch while all 811 other Molex files use an underscore.

### 8. Case-inconsistent vendor tokens inside one library
- `Connector_FFC-FPC.pretty`: `JUSHUO_AFA07-…` (26 files, all-caps) vs `Jushuo_AFC07-…` (2 files, title case).
- `Connector_RJ.pretty`: `RJ45_Bel_SI-60062-F` and `RJ45_Bel_V895-1001-AW_Vertical` vs `RJ45_BEL_SS74301-00x_Vertical`.
Grep case-insensitively when searching; write case-exactly when naming.

### 9. Vendor spellings differ between libraries — deliberately
`Wuerth` in `Connector_USB` / `Connector_RJ` / `Connector_FFC-FPC` / `Connector_Card`, but `Wurth` in `Connector_Coaxial` (`SMA_Wurth_60312002114503_Vertical`) and `WR-MMCX_Wuerth_…` in the *same* library. `TEConnectivity` for coax (`BNC_TEConnectivity_1478035_Horizontal`) but `TE` for FFC/FPC and RJ. `PhoenixContact_` for pluggable headers, `Phoenix_` for terminal blocks.

### 10. Decimal comma vs decimal dot inside one filename
`PhoenixContact_MSTBA_2,5_16-G-5,08_1x16_P5.08mm_Horizontal` — wire size `2,5` comma, MPN pitch `5,08` comma, geometry pitch `P5.08mm` dot. `TerminalBlock_Phoenix_PTSM-0,5-2-2,5-V-SMD_1x02-1MP_P2.50mm_Vertical` mixes them too — and its THR sibling uses a dot in the same slot: `TerminalBlock_Phoenix_PTSM-0,5-2-2.5-H-THR_1x02_P2.50mm_Horizontal` (`2.5` dot). These two are one character apart and mean different mount technologies.

### 11. Near-identical names that differ only by an invisible token
- `RJ45_Amphenol_RJHSE5380` / `RJ45_Amphenol_RJHSE5380-08` / `RJ45_Amphenol_RJHSE538X` / `RJ45_Amphenol_RJHSE538X-02` / `RJ45_Amphenol_RJHSE538X-04` — five distinct files.
- `SMA_Amphenol_132134_Vertical` / `-10` / `-11` / `-14` / `-16`, and `SMA_Amphenol_132291_Vertical` / `132291-12`.
- `USB_Micro-B_Wuerth_629105150521` vs `USB_Micro-B_Wuerth_629105150521_CircularHoles` (round vs slotted mounting holes — mechanically different, one token apart).
- `USB_C_Receptacle_GCT_USB4125-xx-x_6P_TopMnt_Horizontal` vs `USB_C_Receptacle_GCT_USB4125-xx-x-0190_6P_TopMnt_Horizontal`.
- `Molex_Sabre_43160-0102_1x02_P7.49mm_Vertical` vs `…_Vertical_ThermalVias`.

### 12. Underscore-vs-hyphen in USB vendor separators
`USB_Micro-B_Molex_47346-0001` (underscore after vendor) sits next to `USB_Micro-B_Molex-105017-0001`, `USB_Micro-B_Molex-105133-0001`, `USB_Micro-B_Molex-105133-0031` (hyphen after vendor). Four files, two conventions, one library.

### 13. Imperial/metric: the 2.54/1.27 mm pitches are the imperial grid in disguise
0.1″ = 2.54 mm and 0.05″ = 1.27 mm, but KiCad names them metrically only — there is **no** `P0.1inch` or `P100mil` token anywhere in the tree. A datasheet quoting "0.100 in" maps to `P2.54mm`; "0.050 in" to `P1.27mm`; "0.079 in" to `P2.00mm`. Do not convert the other way and do not create an imperial token. Related: `JST_VH_B2P3-VH_1x02_P7.92mm_Vertical` is 2 × 3.96 mm (a doubled 0.156″ pitch), not a typo.

### 14. Row-count semantics differ between the geometry dialects
`2x10` means 20 positions in 2 rows of 10. `2Rows-13Pins` means **13 total** positions staggered across 2 rows — an odd number, impossible in `2xNN`. `Hirose_FH26-13S-0.3SHW_2Rows-13Pins-1MP_P0.60mm_Horizontal` is a 13-contact part; do not read it as 26.
Also watch JST J2100/PHD/PUD/JWPF: the MPN digit is the **total** contact count while the geometry token is per-row — `JST_J2100_B06B-J21DK-GGXR_2x03_…` (6 total, 2×3), `JST_PUD_B40B-PUDSS_2x20_…` (40 total, 2×20), and `JST_JWPF_B04B-JWPF-SK-R_1x04` vs `JST_JWPF_B06B-JWPF-SK-R_2x03` — same series, the row split changes at 6 positions.

### 15. Matrix holes: do not assume a pattern exists because its siblings do
`PinSocket_1.00mm` has no `Horizontal` at all and no plain `2xNN_Vertical`. `PinSocket_1.27mm` has no `1xNN_Horizontal` but its `2xNN_Horizontal` uniquely runs to `2x50`. `PinHeader_1x05_P2.54mm_Vertical_SMD` and `PinHeader_1x05_P2.54mm_Horizontal_SMD` do not exist; `PinHeader_2x05_P2.54mm_Vertical_SMD_Pin1Left` does not exist. IDC position counts are sparse (no `2x14`, no `2x16`, no `2x18`) and `Vertical_SMD` additionally drops `2x15`, `2x17` and `2x32`. `-1MP` IDC variants exist only for the five `Latch*` forms.

### 16. "Generic terminal block" does not exist
Verified: 0 of the 731 files across 14 `TerminalBlock_*.pretty` libraries lack a vendor token. `TerminalBlock.pretty` sounds generic but contains only `TerminalBlock_MaiXu_MX126-…` (24) and `TerminalBlock_Xinya_XY308-…` (21). If you are looking for a vendor-agnostic screw-terminal footprint, there isn't one — pick a vendor series or author your own.

### 17. Orientation vocabulary is not universal
`Vertical` / `Horizontal` dominate, but: coax adds `EdgeMount` (`SMA_Amphenol_132289_EdgeMount`) and sometimes doubles up (`SMA_Molex_73251-1153_EdgeMount_Horizontal`); WAGO angled blocks use `45Degree` (`TerminalBlock_WAGO_236-101_1x01_P5.00mm_45Degree`) while `TerminalBlock_Altech_AK300_1x04_P5.00mm_45-Degree` hyphenates it; card sockets and several RJ/USB parts omit orientation entirely (`RJ45_Ninigi_GE`, `microSD_HC_Hirose_DM3D-SF`). `SMD` appears as an orientation modifier in Tier A (`Vertical_SMD`) but in Tier B it is a bare token only in `USB_Mini-B_AdamTech_MUSB-B5-S-VT-TSMT-1_SMD_Vertical`.

### 18. Literal `+` and `.` in filenames
`SD_Kyocera_145638009211859+` (4 files) end in a plus sign. `U.FL_Hirose_U.FL-R-SMT-1_Vertical`, `LEMO-EPG.00.302.NLN` and `Connector_FFC-FPC.pretty/Hirose_FH12-…-0.5SH…` contain dots inside the stem. Any script that splits on `.` to strip the extension, or that sanitises `+`, will corrupt these.


---


# Crystals & Oscillators, Switches & Buttons, Relays, and Mechanical / Board Features (KiCad 9 stock footprints)

**Backed by:** 1125 stock .kicad_mod files back these four tables, counted per library on 2026-07-26 from /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints:

GROUP 1 - Crystals & Oscillators = 262 files: Crystal.pretty 192 (167 Crystal_*, 25 Resonator*; of the 167: 103 Crystal_SMD_*, 64 THT; 42 end in _HandSoldering, 1 in _RotB) + Oscillator.pretty 70 (62 Oscillator_SMD*, 4 Oscillator_DIP-*, 19 _HandSoldering).

GROUP 2 - Switches & Buttons = 284 files: Button_Switch_SMD.pretty 171 (86 SW_DIP_, 50 SW_SPST_, 19 SW_Push_, 4 SW_SPDT_, 1 each SW_DPDT_/SW_SP3T_/SW_MEC_/SW_Tactile_, plus 8 with NO SW_ prefix) + Button_Switch_THT.pretty 113 (47 SW_DIP_, 13 SW_PUSH_, 12 SW_Push_, 7 SW_TH_, 7 SW_Tactile_, plus 3 with NO SW_ prefix).

GROUP 3 - Relays = 138 files: Relay_THT.pretty 117 (39 SPDT, 35 SPST, 24 DPDT, 4 DPST, 4 Relay_Socket_, 2 3PST, 3 x 1-Form-x, 3 Relay_StandexMeder_, 1 SPST-NO, 1 Relay_NCR_, 1 Relay_Tyco_) + Relay_SMD.pretty 21 (17 DPDT, 2 SPDT, 1 2P2T, 1 Relay_Fujitsu_).

GROUP 4 - Mechanical / board features = 441 files: MountingHole.pretty 167 (166 MountingHole_* + 1 ToolingHole_*) + TestPoint.pretty 57 + Fiducial.pretty 10 + Symbol.pretty 207 (61 LayerMarker_, 31 Symbol_, 14 KiCad-Logo, 14 KiCad-Logo2, 12 each OSHW-Logo / OSHW-Logo2 / OSHW-Symbol / Polarity_, 6 each CE- / ESD- / FCC- / RoHS- / UKCA- / WEEE-Logo, 1 each EasterEgg_ / Screw_ / Smolhaj_).

Cross-referenced but not tabulated in full: Battery.pretty 53, Sensor.pretty 15.

Coverage of the tables below: MountingHole 166/166 (matrix, exhaustive), TestPoint 57/57 (exhaustive), Fiducial 10/10 (exhaustive), Crystal_SMD generic-code family 15/15 (exhaustive), Crystal THT case styles all 20 distinct cases represented, Symbol.pretty every size ladder listed. 639 individual names were verified one-by-one, exact-case, against os.listdir string sets - zero failures. (`test -f` is unreliable here: APFS is case-insensitive, so `test -f SW_Push_6mm.kicad_mod` wrongly succeeds against `SW_PUSH_6mm.kicad_mod`. Every name below survived exact-string verification.)

## Grammar

========================================================================
GROUP 1 - CRYSTALS, RESONATORS & OSCILLATORS
========================================================================

A. SMD crystal, generic dimension-coded:
   Crystal_SMD_<code>-<n>Pin_<L>x<W>mm[_RotB][_HandSoldering]

B. SMD crystal, manufacturer series:
   Crystal_SMD_<Manufacturer>_<Series>-<n>Pin_<L>x<W>mm[_HandSoldering]

C. THT crystal, HC-case:
   Crystal_<HCcase>[-<n>Pin]_<Horizontal|Vertical>[_1EP_style1|_1EP_style2]

D. THT crystal, cylindrical / dimensioned case:
   Crystal_<Case>_D<dia>mm_L<len>mm_<Horizontal|Vertical>[_1EP_style1|_1EP_style2]
   Crystal_Round_D<dia>mm_Vertical

E. Resonator:
   Resonator-<n>Pin_W<width>mm_H<height>mm                     (THT generic)
   Resonator_<Manufacturer>_<Series>-<n>Pin_W<w>mm_H<h>mm      (THT series)
   Resonator_SMD-<n>Pin_<L>x<W>mm[_HandSoldering]              (SMD generic)
   Resonator_SMD_<Manufacturer>_<Series>-<n>Pin_<L>x<W>mm[_HandSoldering]

F. Oscillator:
   Oscillator_SMD_<Manufacturer>_<Series>-<n>Pin_<L>x<W>mm[_RotB][_HandSoldering]
   Oscillator_SMD_<Manufacturer>_<Series>_<L>x<W>mm[_P<pitch>mm]
   Oscillator_SMD_<OCXO|TCXO>_<Manufacturer>_<Series>
   Oscillator_OCXO_<Manufacturer>_<Series>
   Oscillator_DIP-<n>[_LargePads]

Token semantics:
  <code>        4 digits = L then W in units of 0.1 mm. METRIC TENTHS, NOT
                hundredths. 3225 -> 3.2 x 2.5 mm; 2016 -> 2.0 x 1.6 mm;
                5032 -> 5.0 x 3.2 mm; 7050 -> 7.0 x 5.0 mm; 2012 -> 2.0 x 1.2;
                3215 -> 3.2 x 1.5; 2520 -> 2.5 x 2.0; 1210 -> 1.2 x 1.0.
                (Hundredths would make 3225 a 0.32 x 0.25 mm part - absurd.)
                ONE EXCEPTION: 0603 is a legacy vendor series code, not a
                dimension - Crystal_SMD_0603-2Pin_6.0x3.5mm is a 6.0 x 3.5 mm
                case (descr cites Petermann "SMD0603-2"). Never decode 0603 as
                0.6 x 0.3 mm and never as the imperial 0603 chip size.
  -<n>Pin       land count. 2Pin = two signal lands only. 4Pin = four numbered
                lands; the two extra are the grounded-case tabs (confirm the
                actual pin assignment against the datasheet pin table).
  <L>x<W>mm     case length x width. ALWAYS AUTHORITATIVE - the code is a
                nickname, this suffix is the real geometry.
  _HandSoldering  same case, elongated lands for iron soldering.
  _RotB         alternate pad rotation/numbering (rare: 1 crystal, 3 oscillators).
  _1EP_style1   THT crystal + one large SMD ground pad under the can (pad "3").
  _1EP_style2   same, plus thru_hole rect pads on the same pad number 3.
  _LargePads    DIP oscillator with enlarged annular rings.

========================================================================
GROUP 2 - SWITCHES & BUTTONS
========================================================================

Master shape:
   SW_<FUNCTION>[_<CONTACT-MODE>][_<ORIENTATION>][_<Manufacturer>]_<Series>[_<geometry/option>]

<FUNCTION> is the second token and is one of:
   Contact designation ..... SPST | SPDT | DPDT | DPST | SP3T | 1P1T | 1P2T |
                             2P1T | 2P2T | SPSTx<nn> (DIP banks)
   Word form ............... Push | PUSH | Tactile | Slide | Lever | DIP | MEC | TH
   Manufacturer (legacy) ... CK | CW | NKK | XKB | E-Switch

<CONTACT-MODE> ...... NO | NC        (normally-open / normally-closed)
<ORIENTATION> ....... Straight | Angled | Horizontal | Vertical
<geometry/option> ... _H<height>mm | _<L>x<W>mm | _<L>x<W>x<H>mm | _W<span>mm |
                      _P<pitch>mm | _LowProfile | _JPin | _WithStem |
                      _WithoutStem | _SocketPins | _ShortPushTravel |
                      _MiddlePushTravel | _Slide | _Piano | _LED

Sub-grammars actually in use (all four coexist upstream):

 S1  SW_SPST_<Series>[_<option>]
       Dominant style for SMD tactile buttons (50 files).
       SW_SPST_TL3305A, SW_SPST_B3U-1000P, SW_SPST_SKQG_WithStem

 S2  SW_Push_<poles>P<throws>T[-MP|-SH]_<NO|NC>[_<Orientation>]_<Mfr>_<Series>
       The current upstream direction for new tactile parts (19 files).
       SW_Push_1P1T_NO_CK_KMR2, SW_Push_1P1T_NO_Vertical_Wuerth_434133025816

 S3  SW_PUSH_<size>mm[_H<height>mm]   /  SW_PUSH-<size>mm
       Legacy generic THT tactile. NOTE: PUSH is UPPERCASE here.
       SW_PUSH_6mm_H5mm, SW_PUSH-12mm

 S4  SW_Tactile_<...>  /  SW_TH_Tactile_<Mfr>_<Series>
       SW_Tactile_SPST_Angled_PTS645Vx31-2LFS, SW_TH_Tactile_Omron_B3F-100x

DIP switch banks (133 of the 284 files) have their own fixed shape:
   SW_DIP_SPSTx<nn>_<Slide|Piano>_[<Mfr>_<Series>_]<bodyL>x<bodyW>mm_W<span>mm_P<pitch>mm[_LowProfile][_JPin]
   x<nn> is zero-padded 01..12. W<span> is the row-to-row pin span, P is the
   in-row pitch. THT banks use W7.62mm; SMD banks use W8.61mm / W6.73mm.

========================================================================
GROUP 3 - RELAYS
========================================================================

Master shape:
   Relay_<CONTACTS>_<Manufacturer>[-|_]<Series>[_<variant>][_<pitch>]

Alternate shapes:
   Relay_Socket_<CONTACTS>_<Manufacturer>_<Series>
   Relay_<n>-Form-<A|B|C>_<Manufacturer>-<Series>_RM<pitch>mm
   Relay_<Manufacturer>_<Series>                 (contacts omitted, 5 files)

<CONTACTS>  SPST | SPDT | DPST | DPDT | 3PST | 2P2T | SPST-NO |
            1-Form-A | 1-Form-B | 1-Form-C | (3PDT / 4PDT only on sockets)
<pitch>     _RM<p>mm    Schrack / TE-German convention (RM = Rastermass)
            _Pitch<p>mm AXICOM convention
            Both spellings are verbatim stock; match the family, never convert.
<variant>   _FormA | _FormB | _FormC | _Form1A | _Form1B | _Form1C | _Form1AB |
            _Form_A | _Form_C | _DoubleCoil | -Dual-Coil | -1coil |
            _CircularHoles | _Horizontal | _Vertical | _SMD | _JLeg |
            _HighProfile | _LowProfile | _Sealed | _50ohms | _75ohms |
            _<voltage><current> (e.g. _12V30A)
Series wildcards: xx / XX / x for the coil-voltage digits
            (Relay_SPDT_Hongfa_HF3F-L-xx-1ZL1T, Relay_SPST_Hongfa_JQC-3FF_0XX-1H).

========================================================================
GROUP 4 - MECHANICAL / BOARD FEATURES
========================================================================

4a. MOUNTING HOLES - exact token order (this is the one to get right):

   MountingHole_<drill>mm[x<slotlen>mm][_M<thread>][_<HeadStd>][_Pad][_TopOnly|_TopBottom|_Via]

   Order is strictly: DRILL -> THREAD -> HEAD-STANDARD -> Pad -> QUALIFIER.
   * <drill>       hole diameter with unit, trailing zeros stripped:
                   2mm, 2.1mm, 2.2mm, 2.5mm, 2.7mm, 3mm, 3.2mm, 3.5mm, 3.7mm,
                   4mm, 4.3mm, 4.5mm, 5mm, 5.3mm, 5.5mm, 6mm, 6.4mm, 6.5mm,
                   8.4mm.  "3mm" NOT "3.0mm"; "2.5mm" keeps its decimal.
   * x<slotlen>mm  slot form, one instance only: MountingHole_4.3x6.2mm_M4_Pad
   * _M<thread>    screw thread the drill clears: M2 M2.5 M3 M4 M5 M6 M8.
                   Bound pairs (never mix): M2/2.2mm, M2.5/2.7mm, M3/3.2mm,
                   M4/4.3mm, M5/5.3mm, M6/6.4mm, M8/8.4mm.
   * _<HeadStd>    DIN965 (countersunk cross-recess) | ISO7380 (button head) |
                   ISO14580 (hex-socket cheese head). Sets the head-clearance
                   keep-out circle on Cmts.User and the pad OD.
   * _Pad          BARE TOKEN, NO DIAMETER. Turns the NPTH into a plated
                   thru_hole with an annular ring.
                   Pad OD without a head standard = exactly 2 x drill
                   (verified for every stock _Pad file: 2.5mm -> 5.0mm pad,
                   3.2mm -> 6.4mm pad, 6.4mm -> 12.8mm pad).
                   Pad OD with a head standard = the screw head OD, e.g. M3:
                   DIN965 5.6mm, ISO7380 5.7mm, ISO14580 5.5mm.
   * qualifier     _Via        adds 8 stitching vias (0.8mm pad / 0.5mm drill)
                               ringing the hole
                   _TopOnly    2.9mm thru pad + a `connect` pad on F.Cu/F.Mask
                   _TopBottom  as _TopOnly plus the same on B.Cu/B.Mask
                   The three are mutually exclusive and always follow _Pad.
   * bare name (no _Pad) = np_thru_hole, no copper, no net.
   Also in MountingHole.pretty, different prefix:
   ToolingHole_<dia>mm   (only ToolingHole_1.152mm - JLCPCB assembly tooling hole)

   THERE IS NO PAD-DIAMETER TOKEN IN KICAD'S GRAMMAR. `_Pad<dia>mm`,
   `_Pad_<dia>mm` and `_Pad_4mm` do not occur in any of the 166 stock files.

4b. TEST POINTS - six sub-forms:

   TestPoint_Pad_D<dia>mm                            SMD round land
   TestPoint_Pad_<W>x<H>mm                           SMD square land
   TestPoint_THTPad_D<dia>mm_Drill<d>mm              THT round land
   TestPoint_THTPad_<W>x<H>mm_Drill<d>mm             THT square land
   TestPoint_Plated_Hole_D<dia>mm                    plated hole, no land spec
   TestPoint_Bridge_Pitch<p>mm_Drill<d>mm            2-hole solder bridge
   TestPoint_2Pads_Pitch<p>mm_Drill<d>mm             2 separate THT pads
   TestPoint_Loop_D<dia>mm_Drill<d>mm[_Beaded|_LowProfile]   wire test loop
   TestPoint_Keystone_<partno-range>_<KeystoneName>  vendor turret/test jack

   Dimensions in the Pad / THTPad / Plated_Hole forms carry ONE decimal always:
   D1.0mm, D2.0mm, 1.0x1.0mm - never D1mm, never 1x1mm.
   Loop diameters carry TWO decimals: D2.50mm, D2.54mm, D3.80mm.

4c. FIDUCIALS:

   Fiducial_<copper_dia>mm_Mask<opening_dia>mm
   Fiducial_Cross_<copper_dia>mm_Mask<opening_dia>mm

   Trailing zeros stripped: 1mm / 2mm / 3mm, but 0.5mm, 0.75mm, 1.5mm, 2.25mm,
   4.5mm keep their decimals. Never Fiducial_1.0mm_Mask2.0mm.
   Pads are unnumbered: (pad "" smd circle).
   Convention: mask opening = 2x the copper (IPC "Level A"); the
   Mask3mm-on-1mm and Mask4.5mm-on-1.5mm rows are the 3x variants.

4d. NON-ELECTRICAL ARTWORK (Symbol.pretty) - graphics only, no pads:

   <Mark>-Logo_<W>x<H>mm_<Copper|SilkScreen>     CE ESD FCC OSHW OSHW2 UKCA WEEE
   <Mark>-Logo_<size>mm_<Copper|SilkScreen>      single-dimension: KiCad RoHS
   OSHW-Symbol_<W>x<H>mm_<Copper|SilkScreen>
   Symbol_<Hazard>[_Triangle|_NoTriangle]_<W>x<H>mm_Copper
   Symbol_<License>_<CopperTop|SilkScreenTop>[_Type<n>][_Big|_Small]  (older style)
   Polarity_Center_<Positive|Negative>_<size>mm_SilkScreen
   LayerMarker_<layers>_<W>x<H>mm_TextH1mm_P1.27mm[_AlNum|_Named][_LowerMirrored|_BottomMirrored]
   Screw_Generic_<W>x<H>mm_SilkScreen

   Layer suffix availability is NOT uniform:
     Copper + SilkScreen both: KiCad-Logo, KiCad-Logo2, OSHW-Logo, OSHW-Logo2,
                               OSHW-Symbol
     SilkScreen only:          CE-Logo, ESD-Logo, FCC-Logo, RoHS-Logo,
                               UKCA-Logo, WEEE-Logo, Polarity_*, Screw_Generic
     Copper only:              Symbol_HighVoltage_*, Symbol_Danger_*,
                               Symbol_Attention_*

4e. ENCLOSURES, LIGHTPIPES, STANDOFFS - KiCad ships NOTHING:
   There is no Enclosure.pretty, Mechanical.pretty, LightPipe.pretty or
   Standoff.pretty in the KiCad 9 footprint set (only Heatsink.pretty covers
   any bolt-on hardware). These are house parts. 7Sigma precedent, verbatim:
     Enclosures: HAMMOND_1551RFLGY, HAMMOND_1551TFLGY, HAMMOND_1551XFLGY,
                 HAMMOND_1556CGY, TAKACHI_SIM6-12-3W
                 -> <MANUFACTURER_UPPERCASE>_<ExactPartNumber>
     Lightpipes: FIX-LEMB2-4.8V0-F, FIX-LEMB2-7V0-F, FIX-LEMB3-8V0-F
                 -> bare manufacturer part number
     House logo: 7Sigma_Logo

## Reference table

## Group 1 - Crystals, Resonators & Oscillators

Backed by 262 stock files (Crystal.pretty 192 + Oscillator.pretty 70).

### 1a. SMD crystals, generic dimension-coded - EXHAUSTIVE (all 15 files)

| Verbatim name | Code decodes to | Lands | Hand-solder twin |
|---|---|---|---|
| `Crystal_SMD_1210-4Pin_1.2x1.0mm` | 1.2 x 1.0 mm | 4 | none (see `_RotB` below) |
| `Crystal_SMD_1210-4Pin_1.2x1.0mm_RotB` | 1.2 x 1.0 mm | 4 | rotated variant, not hand-solder |
| `Crystal_SMD_2012-2Pin_2.0x1.2mm` | 2.0 x 1.2 mm | 2 | `Crystal_SMD_2012-2Pin_2.0x1.2mm_HandSoldering` |
| `Crystal_SMD_2016-4Pin_2.0x1.6mm` | 2.0 x 1.6 mm | 4 | none |
| `Crystal_SMD_2520-4Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 4 | none |
| `Crystal_SMD_3215-2Pin_3.2x1.5mm` | 3.2 x 1.5 mm | 2 | none |
| `Crystal_SMD_3225-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 | `Crystal_SMD_3225-4Pin_3.2x2.5mm_HandSoldering` |
| `Crystal_SMD_5032-2Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 2 | `Crystal_SMD_5032-2Pin_5.0x3.2mm_HandSoldering` |
| `Crystal_SMD_5032-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 | none |
| `Crystal_SMD_7050-2Pin_7.0x5.0mm` | 7.0 x 5.0 mm | 2 | `Crystal_SMD_7050-2Pin_7.0x5.0mm_HandSoldering` |
| `Crystal_SMD_7050-4Pin_7.0x5.0mm` | 7.0 x 5.0 mm | 4 | none |
| `Crystal_SMD_0603-2Pin_6.0x3.5mm` | **NOT a code** - 6.0 x 3.5 mm case | 2 | `Crystal_SMD_0603-2Pin_6.0x3.5mm_HandSoldering` |
| `Crystal_SMD_0603-4Pin_6.0x3.5mm` | **NOT a code** - 6.0 x 3.5 mm case | 4 | `Crystal_SMD_0603-4Pin_6.0x3.5mm_HandSoldering` |
| `Crystal_SMD_G8-2Pin_3.2x1.5mm` | series code G8, 3.2 x 1.5 mm | 2 | `Crystal_SMD_G8-2Pin_3.2x1.5mm_HandSoldering` |
| `Crystal_SMD_HC49-SD` | HC49 SMD case, no size in name | 2 | `Crystal_SMD_HC49-SD_HandSoldering` |

Code decode rule: the 4 digits are **L then W in tenths of a millimetre (0.1 mm units)** - metric, NOT hundredths. `3225` -> 3.2 x 2.5 mm.

### 1b. SMD crystals, manufacturer-series (representative; 103 `Crystal_SMD_*` exist)

| Verbatim name | Case | Lands |
|---|---|---|
| `Crystal_SMD_Abracon_ABM10-4Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 4 |
| `Crystal_SMD_Abracon_ABM3-2Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 2 |
| `Crystal_SMD_Abracon_ABM3B-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 |
| `Crystal_SMD_Abracon_ABM8G-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Crystal_SMD_Abracon_ABM8AIG-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Crystal_SMD_Abracon_ABS25-4Pin_8.0x3.8mm` | 8.0 x 3.8 mm | 4 |
| `Crystal_SMD_Citizen_CS325S-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Crystal_SMD_ECS_CSM3X-2Pin_7.6x4.1mm` | 7.6 x 4.1 mm | 2 |
| `Crystal_SMD_EuroQuartz_EQ161-2Pin_3.2x1.5mm` | 3.2 x 1.5 mm | 2 |
| `Crystal_SMD_EuroQuartz_MJ-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 |
| `Crystal_SMD_FOX_FQ7050-4Pin_7.0x5.0mm` | 7.0 x 5.0 mm | 4 |
| `Crystal_SMD_FrontierElectronics_FM206` | no size token | 2 |
| `Crystal_SMD_MicroCrystal_CC7V-T1A-2Pin_3.2x1.5mm` | 3.2 x 1.5 mm | 2 |
| `Crystal_SMD_MicroCrystal_CM9V-T1A-2Pin_1.6x1.0mm` | 1.6 x 1.0 mm | 2 |
| `Crystal_SMD_MicroCrystal_MS1V-T1K` | no size token | 2 |
| `Crystal_SMD_Qantek_QC5CB-2Pin_5x3.2mm` | 5 x 3.2 mm (**no trailing .0**) | 2 |
| `Crystal_SMD_SeikoEpson_FA128-4Pin_2.0x1.6mm` | 2.0 x 1.6 mm | 4 |
| `Crystal_SMD_SeikoEpson_FA238-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Crystal_SMD_SeikoEpson_MC306-4Pin_8.0x3.2mm` | 8.0 x 3.2 mm | 4 |
| `Crystal_SMD_SeikoEpson_TSX3225-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Crystal_SMD_TXC_7A-2Pin_5x3.2mm` | 5 x 3.2 mm (**no trailing .0**) | 2 |
| `Crystal_SMD_TXC_7M-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Crystal_SMD_TXC_9HT11-2Pin_2.0x1.2mm` | 2.0 x 1.2 mm | 2 |
| `Crystal_SMD_TXC_AX_8045-2Pin_8.0x4.5mm` | 8.0 x 4.5 mm | 2 |
| `Crystal_SMD_WE_CFPX-104-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 |
| `Crystal_SMD_WE_IQXC-240-4Pin_1.2x1.0mm` | 1.2 x 1.0 mm | 4 |
| `Crystal_SMD_WE_12SMX-4Pin_7.0x5.0mm` | 7.0 x 5.0 mm | 4 |

### 1c. THT crystals - every distinct case style in stock

| Verbatim name | Case | Orientation |
|---|---|---|
| `Crystal_HC18-U_Vertical` | HC18-U | vertical |
| `Crystal_HC33-U_Vertical` | HC33-U | vertical |
| `Crystal_HC35-U` | HC35-U | **no orientation token at all** |
| `Crystal_HC49-U_Vertical` | HC49-U | vertical |
| `Crystal_HC49-U_Horizontal` | HC49-U | horizontal |
| `Crystal_HC49-U_Horizontal_1EP_style1` | HC49-U | horizontal + SMD case-ground pad |
| `Crystal_HC49-U_Horizontal_1EP_style2` | HC49-U | horizontal + SMD/THT case-ground pads |
| `Crystal_HC49-U-3Pin_Vertical` | HC49-U, 3 leads | vertical only |
| `Crystal_HC49-4H_Vertical` | HC49-4H | vertical only |
| `Crystal_HC50_Vertical` | HC50 | vertical |
| `Crystal_HC51_Horizontal` | HC51 (**no -U**) | horizontal |
| `Crystal_HC51-U_Vertical` | HC51-**U** | vertical |
| `Crystal_HC52-6mm_Vertical` | HC52, 6 mm can | vertical |
| `Crystal_HC52-8mm_Vertical` | HC52, 8 mm can | vertical |
| `Crystal_HC52-U_Vertical` | HC52-U | vertical |
| `Crystal_HC52-U-3Pin_Vertical` | HC52-U, 3 leads | vertical |
| `Crystal_AT310_D3.0mm_L10.0mm_Vertical` | AT310 cylinder | vertical |
| `Crystal_AT310_D3.0mm_L10.0mm_Horizontal` | AT310 cylinder | horizontal |
| `Crystal_C26-LF_D2.1mm_L6.5mm_Vertical` | C26-LF cylinder | vertical |
| `Crystal_C38-LF_D3.0mm_L8.0mm_Horizontal` | C38-LF cylinder | horizontal |
| `Crystal_DS10_D1.0mm_L4.3mm_Horizontal` | DS10 cylinder | horizontal |
| `Crystal_DS15_D1.5mm_L5.0mm_Vertical` | DS15 cylinder | vertical |
| `Crystal_DS26_D2.0mm_L6.0mm_Vertical` | DS26 cylinder | vertical |
| `Crystal_Round_D1.0mm_Vertical` | generic round | vertical |
| `Crystal_Round_D2.0mm_Vertical` | generic round | vertical |
| `Crystal_Round_D3.0mm_Vertical` | generic round | vertical |

Every `_D..mm_L..mm_Horizontal` and every `_HCxx-U_Horizontal` also ships `_1EP_style1` and `_1EP_style2` twins.

### 1d. Resonators (25 files in Crystal.pretty)

| Verbatim name | Type |
|---|---|
| `Resonator-2Pin_W7.0mm_H2.5mm` | THT generic 2-lead |
| `Resonator-3Pin_W7.0mm_H2.5mm` | THT generic 3-lead |
| `Resonator-3Pin_W10.0mm_H5.0mm` | THT generic 3-lead, larger |
| `Resonator_Murata_CSTLSxxxG-3Pin_W8.0mm_H3.0mm` | THT Murata series |
| `Resonator_Murata_DSN6-3Pin_W7.0mm_H2.5mm` | THT Murata series |
| `Resonator_SMD-3Pin_7.2x3.0mm` | SMD generic 3-land |
| `Resonator_SMD_Murata_CDSCB-2Pin_4.5x2.0mm` | SMD Murata 2-land |
| `Resonator_SMD_Murata_CSTxExxV-3Pin_3.0x1.1mm` | SMD Murata 3-land |
| `Resonator_SMD_Murata_CSTCR_4.5x2x1.15mm` | SMD Murata, **3 dimensions, no -nPin** |

### 1e. Oscillators (70 files)

| Verbatim name | Case | Lands |
|---|---|---|
| `Oscillator_DIP-8` | DIP-8 | 8 |
| `Oscillator_DIP-8_LargePads` | DIP-8 | 8 |
| `Oscillator_DIP-14` | DIP-14 | 14 |
| `Oscillator_DIP-14_LargePads` | DIP-14 | 14 |
| `Oscillator_SMD_Abracon_ASCO-4Pin_1.6x1.2mm` | 1.6 x 1.2 mm | 4 |
| `Oscillator_SMD_Abracon_ASDMB-4Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 4 |
| `Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Oscillator_SMD_Abracon_ASE-4Pin_3.2x2.5mm_HandSoldering` | 3.2 x 2.5 mm | 4 |
| `Oscillator_SMD_Abracon_ASV-4Pin_7.0x5.1mm` | 7.0 x 5.1 mm | 4 |
| `Oscillator_SMD_Abracon_ABLNO` | no size token | - |
| `Oscillator_SMD_SiT_PQFN-4Pin_2.0x1.6mm` | 2.0 x 1.6 mm | 4 |
| `Oscillator_SMD_SiT_PQFN-4Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 4 |
| `Oscillator_SMD_SiT_PQFN-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Oscillator_SMD_SiT_PQFN-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 |
| `Oscillator_SMD_SiT_PQFN-4Pin_7.0x5.0mm` | 7.0 x 5.0 mm | 4 |
| `Oscillator_SMD_SiTime_SiT9121-6Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 6 |
| `Oscillator_SMD_SiTime_PQFD-6L_3.2x2.5mm` | 3.2 x 2.5 mm | 6 (**-6L not -6Pin**) |
| `Oscillator_SMD_SeikoEpson_SG210-4Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 4 |
| `Oscillator_SMD_SeikoEpson_SG8002CA-4Pin_7.0x5.0mm` | 7.0 x 5.0 mm | 4 |
| `Oscillator_SMD_SeikoEpson_SG8002CE-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Oscillator_SMD_SeikoEpson_SG8002LB-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 |
| `Oscillator_SMD_SeikoEpson_SG3030CM` | no size token | - |
| `Oscillator_SeikoEpson_SG-8002DB` | THT, **no `_SMD`** | - |
| `Oscillator_SeikoEpson_SG-8002DC` | THT, **no `_SMD`** | - |
| `Oscillator_SMD_SeikoEpson_TG2520SMN-xxx-xxxxxx-4Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 4 |
| `Oscillator_SMD_EuroQuartz_XO32-4Pin_3.2x2.5mm` | 3.2 x 2.5 mm | 4 |
| `Oscillator_SMD_EuroQuartz_XO32-4Pin_3.2x2.5mm_RotB` | 3.2 x 2.5 mm | 4 |
| `Oscillator_SMD_EuroQuartz_XO32-4Pin_3.2x2.5mm_RotB_HandSoldering` | 3.2 x 2.5 mm | 4 |
| `Oscillator_SMD_EuroQuartz_XO53-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 |
| `Oscillator_SMD_EuroQuartz_XO91-4Pin_7.0x5.0mm` | 7.0 x 5.0 mm | 4 |
| `Oscillator_SMD_TXC_7C-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 |
| `Oscillator_SMD_Fox_FT5H_5.0x3.2mm` | 5.0 x 3.2 mm | - |
| `Oscillator_SMD_Kyocera_KC2520Z-4Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 4 |
| `Oscillator_SMD_Kyocera_2520-6Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 6 |
| `Oscillator_SMD_IDT_JS6-6_5.0x3.2mm_P1.27mm` | 5.0 x 3.2 mm | 6 |
| `Oscillator_SMD_IDT_JU6-6_7.0x5.0mm_P2.54mm` | 7.0 x 5.0 mm | 6 |
| `Oscillator_SMD_Silicon_Labs_LGA-6_2.5x3.2mm_P1.25mm` | 2.5 x 3.2 mm | 6 |
| `Oscillator_SMD_ECS_2520MV-xxx-xx-4Pin_2.5x2.0mm` | 2.5 x 2.0 mm | 4 |
| `Oscillator_SMD_Diodes_FN-4Pin_7.0x5.0mm` | 7.0 x 5.0 mm | 4 |
| `Oscillator_SMD_IQD_IQXO70-4Pin_7.5x5.0mm` | 7.5 x 5.0 mm | 4 |
| `Oscillator_SMD_Fordahl_DFAS15-4Pin_5.0x3.2mm` | 5.0 x 3.2 mm | 4 |
| `Oscillator_SMD_Fordahl_DFAS1-6Pin_14.8x9.1mm` | 14.8 x 9.1 mm | 6 |
| `Oscillator_OCXO_Morion_MV267` | OCXO, **no `_SMD`** | - |
| `Oscillator_OCXO_Morion_MV317` | OCXO, **no `_SMD`** | - |
| `Oscillator_SMD_OCXO_ConnorWinfield_OH300` | OCXO, `_SMD` before `_OCXO` | - |
| `Oscillator_SMD_TCXO_G158` | TCXO | - |
| `Oscillator_SMD_SI570_SI571_Standard` | Si570/Si571 | - |
| `Oscillator_SMD_SI570_SI571_HandSoldering` | Si570/Si571 | - |

---

## Group 2 - Switches & Buttons

Backed by 284 stock files (Button_Switch_SMD.pretty 171 + Button_Switch_THT.pretty 113).

### 2a. Tactile SMD buttons - style S1 `SW_SPST_<Series>` (50 files; verbatim sample)

| Verbatim name | Vendor / series |
|---|---|
| `SW_SPST_B3S-1000` | Omron B3S |
| `SW_SPST_B3S-1100` | Omron B3S |
| `SW_SPST_B3SL-1002P` | Omron B3SL |
| `SW_SPST_B3U-1000P` | Omron B3U |
| `SW_SPST_B3U-1000P-B` | Omron B3U, bracket variant |
| `SW_SPST_B3U-3100P` | Omron B3U |
| `SW_SPST_Omron_B3FS-100xP` | Omron B3FS (**vendor token present here**) |
| `SW_SPST_Omron_B3FS-101xP` | Omron B3FS |
| `SW_SPST_EVQP0` | Panasonic EVQP0 |
| `SW_SPST_EVQQ2` | Panasonic EVQQ2 |
| `SW_SPST_EVQPE1` | Panasonic EVQPE1 |
| `SW_SPST_EVQP7A` | Panasonic EVQP7A |
| `SW_SPST_EVQP2_ShortPushTravel_H2.1mm` | Panasonic EVQP2 |
| `SW_SPST_EVQP2_ShortPushTravel_H2.5mm` | Panasonic EVQP2 |
| `SW_SPST_EVQP2_MiddlePushTravel_H2.5mm` | Panasonic EVQP2 |
| `SW_SPST_EVPBF` | Panasonic EVPBF |
| `SW_SPST_Panasonic_EVQPL_3PL_5PL_PT_A08` | Panasonic EVQPL |
| `SW_SPST_Panasonic_EVQPL_3PL_5PL_PT_A15` | Panasonic EVQPL |
| `SW_SPST_FSMSM` | TE FSMSM |
| `SW_SPST_GT-TC155X` | Switronic GT-TC155X |
| `SW_SPST_PTS645Sx43SMTR92` | C&K PTS645 |
| `SW_SPST_PTS647_Sx38` | C&K PTS647 |
| `SW_SPST_PTS810` | C&K PTS810 |
| `SW_SPST_CK_KMS2xxG` | C&K KMS2 |
| `SW_SPST_CK_KMS2xxGP` | C&K KMS2 |
| `SW_SPST_CK_KXT3` | C&K KXT3 |
| `SW_SPST_CK_RS282G05A3` | C&K RS282 |
| `SW_SPST_SKQG_WithStem` | Alps SKQG |
| `SW_SPST_SKQG_WithoutStem` | Alps SKQG |
| `SW_SPST_TL3305A` | E-Switch TL3305 |
| `SW_SPST_TL3342` | E-Switch TL3342 |
| `SW_SPST_TS-1088-xR020` | XKB TS-1088 |
| `SW_SPST_TS-1088-xR025` | XKB TS-1088 |
| `SW_SPST_REED_CT05-XXXX-G1` | Coto reed, not tactile |
| `SW_SPST_REED_CT10-XXXX-G4` | Coto reed, not tactile |

### 2b. Tactile buttons - style S2 `SW_Push_...` (the current upstream form, 19 SMD + 12 THT)

| Verbatim name | Library | Decode |
|---|---|---|
| `SW_Push_1P1T_NO_CK_KMR2` | SMD | 1 pole 1 throw, normally open, C&K KMR2 |
| `SW_Push_1P1T_NO_CK_KSC6xxG` | SMD | C&K KSC6xx, G stem |
| `SW_Push_1P1T_NO_CK_KSC7xxJ` | SMD | C&K KSC7xx, J stem |
| `SW_Push_1P1T_NO_CK_PTS125Sx43SMTR` | SMD | C&K PTS125 |
| `SW_Push_1P1T_NO_CK_PTS125Sx43PSMTR` | SMD | C&K PTS125, P variant |
| `SW_Push_1P1T_NO_E-Switch_TL3301NxxxxxG` | SMD | E-Switch TL3301 |
| `SW_Push_1P1T_NO_Vertical_Wuerth_434133025816` | SMD | orientation token before vendor |
| `SW_Push_1P1T-MP_NO_Horizontal_Alps_SKRTLAE010` | SMD | `-MP` = mounting-post suffix on the contact token |
| `SW_Push_1P1T-SH_NO_CK_KMR2xxG` | SMD | `-SH` = shielded/side-hold suffix |
| `SW_Push_1P1T_XKB_TS-1187A` | SMD | contact-mode token omitted |
| `SW_Push_1TS009xxxx-xxxx-xxxx_6x6x5mm` | SMD | `1TS009...` is the series, body 6x6x5 mm |
| `SW_Push_SPST_NO_Alps_SKRK` | SMD | **SPST used inside a `SW_Push_` name** |
| `SW_Push_1P1T_NO_LED_E-Switch_TL1250` | THT | illuminated |
| `SW_Push_1P2T_Vertical_E-Switch_800UDP8P1A1M6` | THT | 1 pole 2 throw |
| `SW_Push_2P1T_Toggle_CK_PVA1xxH1xxxxxxV2` | THT | latching |
| `SW_Push_2P2T_Toggle_CK_PVA2xxH1xxxxxxV2` | THT | latching |
| `SW_Push_2P2T_Toggle_CK_PVA2OAH5xxxxxxV2` | THT | latching |
| `SW_Push_2P2T_Vertical_E-Switch_800UDP8P1A1M6` | THT | same part as 1P2T row, other wiring |

### 2c. Tactile THT buttons - styles S3 and S4

| Verbatim name | Decode |
|---|---|
| `SW_PUSH_6mm` | **PUSH uppercase**, generic 6 mm THT tact |
| `SW_PUSH_6mm_H4.3mm` | 4.3 mm stem |
| `SW_PUSH_6mm_H5mm` | 5 mm stem (**`H5mm`, not `H5.0mm`**) |
| `SW_PUSH_6mm_H7.3mm` | 7.3 mm stem |
| `SW_PUSH_6mm_H8mm` | 8 mm stem |
| `SW_PUSH_6mm_H8.5mm` | 8.5 mm stem |
| `SW_PUSH_6mm_H9.5mm` | 9.5 mm stem |
| `SW_PUSH_6mm_H13mm` | 13 mm stem |
| `SW_PUSH-12mm` | **hyphen before the size**, 12 mm tact |
| `SW_PUSH-12mm_Wuerth-430476085716` | Wuerth 12 mm |
| `SW_PUSH_1P1T_6x3.5mm_H4.3_APEM_MJTP1243` | **`H4.3` with no `mm`** |
| `SW_PUSH_1P1T_6x3.5mm_H5.0_APEM_MJTP1250` | **`H5.0` with no `mm`** |
| `SW_PUSH_E-Switch_FS5700DP_DPDT` | contacts trail the series |
| `SW_PUSH_LCD_E3_SAxxxx` | LCD-window push |
| `SW_PUSH_LCD_E3_SAxxxx_SocketPins` | same, socket pins |
| `SW_Tactile_SPST_Angled_PTS645Vx31-2LFS` | C&K PTS645, right-angle |
| `SW_Tactile_SPST_Angled_PTS645Vx83-2LFS` | C&K PTS645, right-angle |
| `SW_Tactile_SKHH_Angled` | Alps SKHH |
| `SW_Tactile_Straight_KSA0Axx1LFTR` | C&K KSA, **no contact token** |
| `SW_Tactile_Straight_KSL0Axx1LFTR` | C&K KSL, **no contact token** |
| `SW_Tactile_SPST_NO_Straight_CK_PTS636Sx25SMTRLFS` | in **Button_Switch_SMD**, fullest form |
| `SW_TH_Tactile_Omron_B3F-100x` | `SW_TH_` prefix variant |
| `SW_TH_Tactile_Omron_B3F-1110` | `SW_TH_` prefix variant |
| `SW_SPST_Omron_B3F-40xx` | THT tact under the S1 style |
| `SW_SPST_Omron_B3F-50xx` | THT tact under the S1 style |
| `SW_SPST_Omron_B3F-315x_Angled` | THT tact, right-angle |
| `KSA_Tactile_SPST` | **no `SW_` prefix at all** |
| `Push_E-Switch_KS01Q01` | **no `SW_` prefix at all** |
| `Nidec_Copal_SH-7010C` | **no `SW_` prefix at all** |

### 2d. Slide / toggle / rotary / reed - SPST, SPDT, DPDT, SP3T

| Verbatim name | Library | Contacts |
|---|---|---|
| `SW_SPDT_CK_JS102011SAQN` | SMD | SPDT |
| `SW_SPDT_PCM12` | SMD | SPDT |
| `SW_SPDT_Shouhan_MSK12C02` | SMD | SPDT |
| `SW_SPDT_REED_MSDM-DT` | SMD | SPDT reed |
| `SW_SP3T_PCM13` | SMD | SP3T |
| `SW_DPDT_CK_JS202011JCQN` | SMD | DPDT |
| `SW_MEC_5GSH9` | SMD | MEC 5G series |
| `SW_MEC_5GTH9` | THT | MEC 5G series |
| `SW_CK_JS202011AQN_DPDT_Angled` | THT | **contacts AFTER the series** |
| `SW_CK_JS202011CQN_DPDT_Straight` | THT | **contacts AFTER the series** |
| `SW_E-Switch_EG1224_SPDT_Angled` | THT | **contacts AFTER the series** |
| `SW_E-Switch_EG1271_SPDT` | THT | **contacts AFTER the series** |
| `SW_E-Switch_EG2219_DPDT_Angled` | THT | **contacts AFTER the series** |
| `SW_Slide_SPDT_Angled_CK_OS102011MA1Q` | THT | contacts after `Slide` |
| `SW_Slide_SPDT_Straight_CK_OS102011MS2Q` | THT | contacts after `Slide` |
| `SW_Slide_SP3T_Straight_CK_OS103012MU1QP1` | THT | contacts after `Slide` |
| `SW_Slide-03_Wuerth-WS-SLTV_10x2.5x6.4_P2.54mm` | THT | 3-position, 3-dim body |
| `SW_Lever_1P2T_NKK_GW12LxH` | THT | lever |
| `SW_CW_GPTS203211B` | THT | CW Industries, no contacts |
| `SW_NKK_BB15AH` | THT | NKK, no contacts |
| `SW_NKK_G1xJP` | THT | NKK, no contacts |
| `SW_NKK_GW12LJP` | THT | NKK, no contacts |
| `SW_NKK_NR01` | THT | NKK, no contacts |
| `SW_XKB_DM1-16UC-1` | THT | XKB, no contacts |
| `Panasonic_EVQPUJ_EVQPUA` | SMD | **no `SW_` prefix**, encoder |
| `Panasonic_EVQPUM_EVQPUD` | SMD | **no `SW_` prefix**, encoder |
| `Nidec_Copal_CAS-120A` | SMD | **no `SW_` prefix** |
| `Nidec_Copal_SH-7010A` | SMD | **no `SW_` prefix** |

### 2e. DIP switch banks (133 files - grammar is fully regular)

| Verbatim name | Library | Decode |
|---|---|---|
| `SW_DIP_SPSTx01_Slide_9.78x4.72mm_W7.62mm_P2.54mm` | THT | 1 way, 9.78 x 4.72 body, 7.62 span, 2.54 pitch |
| `SW_DIP_SPSTx04_Slide_9.78x12.34mm_W7.62mm_P2.54mm` | THT | 4 way |
| `SW_DIP_SPSTx04_Slide_6.7x11.72mm_W7.62mm_P2.54mm_LowProfile` | THT | 4 way, low profile |
| `SW_DIP_SPSTx01_Piano_10.8x4.1mm_W7.62mm_P2.54mm` | THT | piano (rocker) actuator |
| `SW_DIP_SPSTx04_Piano_10.8x11.72mm_W7.62mm_P2.54mm` | THT | piano |
| `SW_DIP_SPSTx04_Piano_CTS_Series194-4MSTN_W7.62mm_P2.54mm` | THT | vendor series replaces body dims |
| `SW_DIP_SPSTx01_Slide_9.78x4.72mm_W8.61mm_P2.54mm` | SMD | **W8.61mm = SMD gull-wing span** |
| `SW_DIP_SPSTx04_Slide_9.78x12.34mm_W8.61mm_P2.54mm` | SMD | 4 way |
| `SW_DIP_SPSTx04_Slide_6.7x11.72mm_W8.61mm_P2.54mm_LowProfile` | SMD | low profile |
| `SW_DIP_SPSTx04_Slide_6.7x11.72mm_W6.73mm_P2.54mm_LowProfile_JPin` | SMD | J-lead |
| `SW_DIP_SPSTx04_Slide_Copal_CHS-04B_W7.62mm_P1.27mm` | SMD | 1.27 mm pitch |
| `SW_DIP_SPSTx04_Slide_Copal_CHS-04A_W5.08mm_P1.27mm_JPin` | SMD | J-lead |
| `SW_DIP_SPSTx04_Slide_Copal_CVS-04xB_W5.9mm_P1mm` | SMD | **`P1mm`, not `P1.0mm`** |
| `SW_DIP_SPSTx04_Slide_KingTek_DSHP04TS_W7.62mm_P1.27mm` | SMD | KingTek |
| `SW_DIP_SPSTx04_Slide_Omron_A6S-410x_W8.9mm_P2.54mm` | SMD | Omron A6S |
| `SW_DIP_SPSTx04_Slide_Omron_A6H-4101_W6.15mm_P1.27mm` | SMD | Omron A6H |
| `SW_DIP_SPSTx12_Slide_9.78x32.66mm_W8.61mm_P2.54mm` | SMD | largest bank (12 way) |

---

## Group 3 - Relays

Backed by 138 stock files (Relay_THT.pretty 117 + Relay_SMD.pretty 21).

### 3a. Relay_THT - by contact designation (representative of all 117)

| Verbatim name | Contacts | Notes |
|---|---|---|
| `Relay_SPST_Omron_G2RL-1A` | SPST | |
| `Relay_SPST_Omron_G2RL-1A-E` | SPST | `-E` series variant |
| `Relay_SPST_Omron_G5NB` | SPST | |
| `Relay_SPST_Omron_G5PZ` | SPST | |
| `Relay_SPST_Omron-G5Q-1A` | SPST | **HYPHEN after Omron** |
| `Relay_SPDT_Omron_G2RL-1` | SPDT | |
| `Relay_SPDT_Omron_G2RL-1-E` | SPDT | |
| `Relay_SPDT_Omron_G5V-1` | SPDT | |
| `Relay_SPDT_Omron_G6E` | SPDT | |
| `Relay_SPDT_Omron_G6EK` | SPDT | |
| `Relay_SPDT_Omron-G5LE-1` | SPDT | **HYPHEN after Omron** |
| `Relay_SPDT_Omron-G5Q-1` | SPDT | **HYPHEN after Omron** |
| `Relay_DPDT_Omron_G2RL-2` | DPDT | |
| `Relay_DPDT_Omron_G5V-2` | DPDT | |
| `Relay_DPDT_Omron_G6A` | DPDT | |
| `Relay_DPDT_Omron_G6AK` | DPDT | |
| `Relay_DPDT_Omron_G6H-2` | DPDT | |
| `Relay_DPDT_Omron_G6K-2P` | DPDT | THT `-2P` |
| `Relay_DPDT_Omron_G6K-2P-Y` | DPDT | |
| `Relay_DPDT_Omron_G6S-2` | DPDT | |
| `Relay_DPDT_Omron_G6SK-2` | DPDT | |
| `Relay_DPST_Omron_G2RL-2A` | DPST | |
| `Relay_DPDT_Kemet_EC2_NJ` | DPDT | |
| `Relay_DPDT_Kemet_EC2_NJ_DoubleCoil` | DPDT | **`_DoubleCoil`** |
| `Relay_DPDT_Kemet_EC2_NU` | DPDT | |
| `Relay_DPDT_Kemet_EC2_NU_DoubleCoil` | DPDT | |
| `Relay_SPST_Hongfa_JQC-3FF_0XX-1H` | SPST | `0XX` coil wildcard |
| `Relay_SPDT_Hongfa_JQC-3FF_0XX-1Z` | SPDT | |
| `Relay_SPST_Hongfa_HF3F-L-xx-1HL1T` | SPST | `xx` coil wildcard |
| `Relay_SPDT_Hongfa_HF3F-L-xx-1ZL1T` | SPDT | |
| `Relay_SPDT_Hongfa_HF3F-L-xx-1ZL2T-R` | SPDT | `-R` reversed coil |
| `Relay_DPDT_Hongfa_HF115F-2Z-x4` | DPDT | |
| `Relay_SPDT_Finder_40.51` | SPDT | dotted Finder series numbers |
| `Relay_SPDT_Finder_40.11` | SPDT | |
| `Relay_SPDT_Finder_34.51_Horizontal` | SPDT | orientation suffix |
| `Relay_SPDT_Finder_34.51_Vertical` | SPDT | orientation suffix |
| `Relay_SPDT_Finder_32.21-x000` | SPDT | order-code wildcard |
| `Relay_SPST_Finder_32.21-x300` | SPST | order-code wildcard |
| `Relay_DPDT_Finder_40.52` | DPDT | |
| `Relay_DPDT_Finder_30.22` | DPDT | |
| `Relay_SPST-NO_Fujitsu_FTR-LYAA005x_FormA_Vertical` | SPST-NO | **`SPST-NO` + redundant `_FormA`** |
| `Relay_SPDT_Fujitsu_FTR-LYCA005x_FormC_Vertical` | SPDT | + redundant `_FormC` |
| `Relay_DPST_Fujitsu_FTR-F1A` | DPST | |
| `Relay_DPDT_Fujitsu_FTR-F1C` | DPDT | |
| `Relay_SPST_Panasonic_ADW11` | SPST | |
| `Relay_SPST_Panasonic_JW1_FormA` | SPST | |
| `Relay_SPDT_Panasonic_JW1_FormC` | SPDT | |
| `Relay_DPDT_Panasonic_JW2` | DPDT | |
| `Relay_SPDT_Panasonic_DR` | SPDT | |
| `Relay_SPDT_Panasonic_DR-L` | SPDT | |
| `Relay_SPST_Panasonic_ALFG_FormA` | SPST | |
| `Relay_SPST_Panasonic_ALFG_FormA_CircularHoles` | SPST | round instead of oval holes |
| `Relay_SPST_Schrack-RT1-FormA_RM5mm` | SPST | **`_RM<pitch>mm`** |
| `Relay_SPST_Schrack-RT1-FormA_RM3.5mm` | SPST | |
| `Relay_SPST_Schrack-RT1-16A-FormA_RM5mm` | SPST | current rating in series token |
| `Relay_SPDT_Schrack-RT1-FormC_RM5mm` | SPDT | |
| `Relay_DPDT_Schrack-RT2-FormC_RM5mm` | DPDT | |
| `Relay_DPDT_Schrack-RT2-FormC-Dual-Coil_RM5mm` | DPDT | **`-Dual-Coil`** |
| `Relay_DPST_Schrack-RT2-FormA_RM5mm` | DPST | |
| `Relay_SPST_Schrack-RP-II-1-FormA_RM5mm` | SPST | |
| `Relay_SPST_Schrack-RP3SL_RM5mm` | SPST | |
| `Relay_SPST_Schrack-RP3SL-1coil_RM5mm` | SPST | **`-1coil`** lowercase |
| `Relay_1-Form-A_Schrack-RYII_RM5mm` | 1 Form A | **`<n>-Form-<X>` form** |
| `Relay_1-Form-B_Schrack-RYII_RM5mm` | 1 Form B | |
| `Relay_1-Form-C_Schrack-RYII_RM3.2mm` | 1 Form C | |
| `Relay_DPDT_AXICOM_IMSeries_Pitch3.2mm` | DPDT | **`_Pitch<p>mm`, not `_RM`** |
| `Relay_DPDT_AXICOM_IMSeries_Pitch5.08mm` | DPDT | |
| `Relay_3PST_COTO_3650` | 3PST | |
| `Relay_DPST_COTO_3602` | DPST | |
| `Relay_SPST_StandexMeder_SIL_Form1A` | SPST | `_Form1A` numbered |
| `Relay_SPST_StandexMeder_MS_Form1AB` | SPST | `_Form1AB` |
| `Relay_SPDT_StandexMeder_SIL_Form1C` | SPDT | |
| `Relay_StandexMeder_DIP_HighProfile` | - | **contacts omitted entirely** |
| `Relay_StandexMeder_DIP_LowProfile` | - | contacts omitted |
| `Relay_StandexMeder_UMS` | - | contacts omitted |
| `Relay_SPST_TE_PCH-1xxx2M` | SPST | |
| `Relay_SPST_TE_PCN-1xxD3MHZ` | SPST | |
| `Relay_SPST_Zettler-AZSR131` | SPST | hyphen after vendor |
| `Relay_SPDT_SANYOU_SRD_Series_Form_C` | SPDT | **`_Form_C` with underscores** |
| `Relay_SPST_SANYOU_SRD_Series_Form_A` | SPST | |
| `Relay_SPST_SANYOU_SRD_Series_Form_B` | SPST | |
| `Relay_SPDT_HsinDa_Y14` | SPDT | |
| `Relay_SPDT_HJR-4102` | SPDT | no vendor token |
| `Relay_SPDT_CUI_SR5` | SPDT | |
| `Relay_SPDT_RAYEX-L90` | SPDT | hyphen after vendor |
| `Relay_SPST_RAYEX-L90A` | SPST | |
| `Relay_SPST_PotterBrumfield_T9AP1D52_12V30A` | SPST | rating suffix |
| `Relay_SPDT_PotterBrumfield_T9AP5D52_12V30A` | SPDT | rating suffix |
| `Relay_DPDT_FRT5` | DPDT | no vendor token |
| `Relay_NCR_HHG1D-1` | - | contacts omitted |
| `Relay_Tyco_V23072_Sealed` | - | contacts omitted |
| `Relay_Socket_DPDT_Omron_PLE08-0` | DPDT socket | **`Relay_Socket_` prefix** |
| `Relay_Socket_3PDT_Omron_PLE11-0` | 3PDT socket | |
| `Relay_Socket_4PDT_Omron_PY14-02` | 4PDT socket | |
| `Relay_Socket_DPDT_Finder_96.12` | DPDT socket | |

### 3b. Relay_SMD - EXHAUSTIVE (all 21 files)

| Verbatim name | Contacts |
|---|---|
| `Relay_DPDT_Omron_G6K-2F` | DPDT |
| `Relay_DPDT_Omron_G6K-2F-Y` | DPDT |
| `Relay_DPDT_Omron_G6K-2G` | DPDT |
| `Relay_DPDT_Omron_G6K-2G-Y` | DPDT |
| `Relay_DPDT_Omron_G6H-2F` | DPDT |
| `Relay_DPDT_Omron_G6S-2F` | DPDT |
| `Relay_DPDT_Omron_G6S-2G` | DPDT |
| `Relay_DPDT_Omron_G6SK-2F` | DPDT |
| `Relay_DPDT_Omron_G6SK-2G` | DPDT |
| `Relay_DPDT_Kemet_EE2_NU` | DPDT |
| `Relay_DPDT_Kemet_EE2_NU_DoubleCoil` | DPDT |
| `Relay_DPDT_Kemet_EE2_NUH` | DPDT |
| `Relay_DPDT_Kemet_EE2_NUH_DoubleCoil` | DPDT |
| `Relay_DPDT_Kemet_EE2_NUX_DoubleCoil` | DPDT |
| `Relay_DPDT_Kemet_EE2_NUX_NKX` | DPDT |
| `Relay_DPDT_AXICOM_IMSeries_JLeg` | DPDT |
| `Relay_DPDT_FRT5_SMD` | DPDT (**`_SMD` suffix, redundant with the library**) |
| `Relay_SPDT_AXICOM_HF3Series_50ohms_Pitch1.27mm` | SPDT RF |
| `Relay_SPDT_AXICOM_HF3Series_75ohms_Pitch1.27mm` | SPDT RF |
| `Relay_2P2T_10x6mm_TE_IMxxG` | 2P2T (**`2P2T` not `DPDT`; body size before vendor**) |
| `Relay_Fujitsu_FTR-B3S` | contacts omitted |

---

## Group 4 - Mechanical / Board Features

Backed by 441 stock files (MountingHole 167 + TestPoint 57 + Fiducial 10 + Symbol 207).

### 4a. MountingHole.pretty - EXHAUSTIVE variant matrix (all 166 `MountingHole_*` files)

Build a name as `MountingHole_` + drill + thread + head-standard + qualifier, in that order. A tick means the file exists.

| Drill | Thread | Head std | bare | `_Pad` | `_Pad_Via` | `_Pad_TopOnly` | `_Pad_TopBottom` |
|---|---|---|---|---|---|---|---|
| `2mm` | - | - | yes | - | - | - | - |
| `2.1mm` | - | - | yes | - | - | - | - |
| `2.2mm` | `M2` | - | yes | yes | yes | yes | yes |
| `2.2mm` | `M2` | `DIN965` | yes | yes | - | yes | yes |
| `2.2mm` | `M2` | `ISO7380` | yes | yes | - | yes | yes |
| `2.2mm` | `M2` | `ISO14580` | yes | yes | - | yes | yes |
| `2.5mm` | - | - | yes | yes | yes | yes | yes |
| `2.7mm` | - | - | yes | yes | yes | yes | yes |
| `2.7mm` | `M2.5` | - | yes | yes | yes | yes | yes |
| `2.7mm` | `M2.5` | `DIN965` | yes | yes | - | yes | yes |
| `2.7mm` | `M2.5` | `ISO7380` | yes | yes | - | yes | yes |
| `2.7mm` | `M2.5` | `ISO14580` | yes | yes | - | yes | yes |
| `3mm` | - | - | yes | yes | yes | yes | yes |
| `3.2mm` | `M3` | - | yes | yes | yes | yes | yes |
| `3.2mm` | `M3` | `DIN965` | yes | yes | - | yes | yes |
| `3.2mm` | `M3` | `ISO7380` | yes | yes | - | yes | yes |
| `3.2mm` | `M3` | `ISO14580` | yes | yes | - | yes | yes |
| `3.5mm` | - | - | yes | yes | yes | yes | yes |
| `3.7mm` | - | - | yes | yes | yes | yes | yes |
| `4mm` | - | - | yes | yes | yes | yes | yes |
| `4.3mm` | `M4` | - | yes | yes | yes | yes | yes |
| `4.3mm` | `M4` | `DIN965` | yes | yes | - | yes | yes |
| `4.3mm` | `M4` | `ISO7380` | yes | yes | - | yes | yes |
| `4.3mm` | `M4` | `ISO14580` | yes | yes | - | yes | yes |
| `4.3x6.2mm` | `M4` | - | - | yes | yes | - | - |
| `4.5mm` | - | - | yes | yes | yes | yes | yes |
| `5mm` | - | - | yes | yes | yes | yes | yes |
| `5.3mm` | `M5` | - | yes | yes | yes | yes | yes |
| `5.3mm` | `M5` | `DIN965` | yes | yes | - | yes | yes |
| `5.3mm` | `M5` | `ISO7380` | yes | yes | - | yes | yes |
| `5.3mm` | `M5` | `ISO14580` | yes | yes | - | yes | yes |
| `5.5mm` | - | - | yes | yes | yes | yes | yes |
| `6mm` | - | - | yes | yes | yes | yes | yes |
| `6.4mm` | `M6` | - | yes | yes | yes | yes | yes |
| `6.4mm` | `M6` | `DIN965` | yes | yes | - | yes | yes |
| `6.4mm` | `M6` | `ISO7380` | yes | yes | - | yes | yes |
| `6.4mm` | `M6` | `ISO14580` | yes | yes | - | yes | yes |
| `6.5mm` | - | - | yes | yes | yes | yes | yes |
| `8.4mm` | `M8` | - | yes | yes | yes | yes | yes |

Worked examples, verbatim: `MountingHole_2mm`, `MountingHole_2.1mm`, `MountingHole_2.5mm`, `MountingHole_2.5mm_Pad`, `MountingHole_2.5mm_Pad_Via`, `MountingHole_2.5mm_Pad_TopOnly`, `MountingHole_2.5mm_Pad_TopBottom`, `MountingHole_2.2mm_M2`, `MountingHole_2.2mm_M2_Pad`, `MountingHole_2.2mm_M2_Pad_Via`, `MountingHole_2.2mm_M2_DIN965_Pad`, `MountingHole_2.2mm_M2_ISO7380_Pad`, `MountingHole_2.2mm_M2_ISO14580_Pad`, `MountingHole_2.7mm_M2.5`, `MountingHole_2.7mm_M2.5_Pad`, `MountingHole_2.7mm_M2.5_ISO7380_Pad`, `MountingHole_3mm_Pad`, `MountingHole_3.2mm_M3`, `MountingHole_3.2mm_M3_Pad`, `MountingHole_3.2mm_M3_Pad_Via`, `MountingHole_3.2mm_M3_Pad_TopOnly`, `MountingHole_3.2mm_M3_Pad_TopBottom`, `MountingHole_3.2mm_M3_DIN965`, `MountingHole_3.2mm_M3_DIN965_Pad`, `MountingHole_3.2mm_M3_ISO7380_Pad`, `MountingHole_3.2mm_M3_ISO14580_Pad`, `MountingHole_4.3mm_M4_Pad`, `MountingHole_4.3x6.2mm_M4_Pad`, `MountingHole_4.3x6.2mm_M4_Pad_Via`, `MountingHole_5.3mm_M5_Pad`, `MountingHole_6.4mm_M6_Pad`, `MountingHole_8.4mm_M8_Pad`, `MountingHole_8.4mm_M8_Pad_Via`.

Plus the one non-`MountingHole_` file in that library: `ToolingHole_1.152mm` (JLCPCB assembly tooling hole, 1.152 mm NPTH, 1.3 mm mask).

Pad diameters (measured, not guessed):

| Family | Pad OD rule | Example |
|---|---|---|
| `_Pad` without head standard | exactly 2 x drill | `MountingHole_2.5mm_Pad` -> 5.0 mm pad on 2.5 mm drill; `MountingHole_3.2mm_M3_Pad` -> 6.4 mm |
| `_Pad` with `DIN965` | screw head OD | `MountingHole_3.2mm_M3_DIN965_Pad` -> 5.6 mm |
| `_Pad` with `ISO7380` | screw head OD | `MountingHole_3.2mm_M3_ISO7380_Pad` -> 5.7 mm |
| `_Pad` with `ISO14580` | screw head OD | `MountingHole_3.2mm_M3_ISO14580_Pad` -> 5.5 mm |
| `_Pad_TopOnly` / `_Pad_TopBottom` | 2.9 mm thru pad + full-size `connect` pad on the named side(s) | `MountingHole_2.5mm_Pad_TopOnly` -> 2.9 mm thru + 5.0 mm F.Cu connect |
| `_Pad_Via` | main pad as `_Pad`, plus 8 stitch vias 0.8 mm pad / 0.5 mm drill | `MountingHole_2.5mm_Pad_Via` |
| bare (no `_Pad`) | `np_thru_hole`, no copper | `MountingHole_2.5mm` |

### 4b. TestPoint.pretty - EXHAUSTIVE (all 57 files)

| Verbatim name | Form |
|---|---|
| `TestPoint_Pad_D1.0mm` | SMD round land |
| `TestPoint_Pad_D1.5mm` | SMD round land |
| `TestPoint_Pad_D2.0mm` | SMD round land |
| `TestPoint_Pad_D2.5mm` | SMD round land |
| `TestPoint_Pad_D3.0mm` | SMD round land |
| `TestPoint_Pad_D4.0mm` | SMD round land |
| `TestPoint_Pad_1.0x1.0mm` | SMD square land |
| `TestPoint_Pad_1.5x1.5mm` | SMD square land |
| `TestPoint_Pad_2.0x2.0mm` | SMD square land |
| `TestPoint_Pad_2.5x2.5mm` | SMD square land |
| `TestPoint_Pad_3.0x3.0mm` | SMD square land |
| `TestPoint_Pad_4.0x4.0mm` | SMD square land |
| `TestPoint_THTPad_D1.0mm_Drill0.5mm` | THT round land |
| `TestPoint_THTPad_D1.5mm_Drill0.7mm` | THT round land |
| `TestPoint_THTPad_D2.0mm_Drill1.0mm` | THT round land |
| `TestPoint_THTPad_D2.5mm_Drill1.2mm` | THT round land |
| `TestPoint_THTPad_D3.0mm_Drill1.5mm` | THT round land |
| `TestPoint_THTPad_D4.0mm_Drill2.0mm` | THT round land |
| `TestPoint_THTPad_1.0x1.0mm_Drill0.5mm` | THT square land |
| `TestPoint_THTPad_1.5x1.5mm_Drill0.7mm` | THT square land |
| `TestPoint_THTPad_2.0x2.0mm_Drill1.0mm` | THT square land |
| `TestPoint_THTPad_2.5x2.5mm_Drill1.2mm` | THT square land |
| `TestPoint_THTPad_3.0x3.0mm_Drill1.5mm` | THT square land |
| `TestPoint_THTPad_4.0x4.0mm_Drill2.0mm` | THT square land |
| `TestPoint_Plated_Hole_D2.0mm` | plated hole |
| `TestPoint_Plated_Hole_D3.0mm` | plated hole |
| `TestPoint_Plated_Hole_D4.0mm` | plated hole |
| `TestPoint_Plated_Hole_D5.0mm` | plated hole |
| `TestPoint_Bridge_Pitch2.0mm_Drill0.7mm` | solder bridge |
| `TestPoint_Bridge_Pitch2.54mm_Drill0.7mm` | solder bridge |
| `TestPoint_Bridge_Pitch2.54mm_Drill1.0mm` | solder bridge |
| `TestPoint_Bridge_Pitch2.54mm_Drill1.3mm` | solder bridge |
| `TestPoint_Bridge_Pitch3.81mm_Drill1.3mm` | solder bridge |
| `TestPoint_Bridge_Pitch5.08mm_Drill0.7mm` | solder bridge |
| `TestPoint_Bridge_Pitch5.08mm_Drill1.3mm` | solder bridge |
| `TestPoint_Bridge_Pitch6.35mm_Drill1.3mm` | solder bridge |
| `TestPoint_Bridge_Pitch7.62mm_Drill1.3mm` | solder bridge |
| `TestPoint_2Pads_Pitch2.54mm_Drill0.8mm` | two separate THT pads |
| `TestPoint_2Pads_Pitch5.08mm_Drill1.3mm` | two separate THT pads |
| `TestPoint_Loop_D1.80mm_Drill1.0mm_Beaded` | wire loop |
| `TestPoint_Loop_D2.50mm_Drill1.0mm` | wire loop |
| `TestPoint_Loop_D2.50mm_Drill1.0mm_LowProfile` | wire loop |
| `TestPoint_Loop_D2.50mm_Drill1.85mm` | wire loop |
| `TestPoint_Loop_D2.54mm_Drill1.5mm_Beaded` | wire loop |
| `TestPoint_Loop_D2.60mm_Drill0.9mm_Beaded` | wire loop |
| `TestPoint_Loop_D2.60mm_Drill1.4mm_Beaded` | wire loop |
| `TestPoint_Loop_D2.60mm_Drill1.6mm_Beaded` | wire loop |
| `TestPoint_Loop_D3.50mm_Drill0.9mm_Beaded` | wire loop |
| `TestPoint_Loop_D3.50mm_Drill1.4mm_Beaded` | wire loop |
| `TestPoint_Loop_D3.80mm_Drill2.0mm` | wire loop |
| `TestPoint_Loop_D3.80mm_Drill2.5mm` | wire loop |
| `TestPoint_Loop_D3.80mm_Drill2.8mm` | wire loop |
| `TestPoint_Keystone_5000-5004_Miniature` | vendor turret |
| `TestPoint_Keystone_5005-5009_Compact` | vendor turret |
| `TestPoint_Keystone_5010-5014_Multipurpose` | vendor turret |
| `TestPoint_Keystone_5015_Micro_Mini` | vendor turret |
| `TestPoint_Keystone_5019_Miniature` | vendor turret |

### 4c. Fiducial.pretty - EXHAUSTIVE (all 10 files)

| Verbatim name | Copper dia | Mask opening | Ratio |
|---|---|---|---|
| `Fiducial_0.5mm_Mask1mm` | 0.5 mm | 1 mm | 2x (Level A) |
| `Fiducial_0.5mm_Mask1.5mm` | 0.5 mm | 1.5 mm | 3x |
| `Fiducial_0.5mm_Mask2mm` | 0.5 mm | 2 mm | 4x |
| `Fiducial_0.75mm_Mask1.5mm` | 0.75 mm | 1.5 mm | 2x |
| `Fiducial_0.75mm_Mask2.25mm` | 0.75 mm | 2.25 mm | 3x |
| `Fiducial_1mm_Mask2mm` | 1 mm | 2 mm | 2x |
| `Fiducial_1mm_Mask3mm` | 1 mm | 3 mm | 3x |
| `Fiducial_1.5mm_Mask3mm` | 1.5 mm | 3 mm | 2x |
| `Fiducial_1.5mm_Mask4.5mm` | 1.5 mm | 4.5 mm | 3x |
| `Fiducial_Cross_1.5mm_Mask2mm` | 1.5 mm cross | 2 mm | cross variant |

### 4d. Symbol.pretty (207 files) - non-electrical artwork, complete size ladders

| Family | Verbatim names (every size in stock) | Layers available |
|---|---|---|
| CE mark | `CE-Logo_8.5x6mm_SilkScreen`, `CE-Logo_11.2x8mm_SilkScreen`, `CE-Logo_16.8x12mm_SilkScreen`, `CE-Logo_28x20mm_SilkScreen`, `CE-Logo_42x30mm_SilkScreen`, `CE-Logo_56.1x40mm_SilkScreen` | SilkScreen only |
| ESD mark | `ESD-Logo_6.6x6mm_SilkScreen`, `ESD-Logo_8.9x8mm_SilkScreen`, `ESD-Logo_13.2x12mm_SilkScreen`, `ESD-Logo_22x20mm_SilkScreen`, `ESD-Logo_33x30mm_SilkScreen`, `ESD-Logo_44.1x40mm_SilkScreen` | SilkScreen only |
| FCC mark | `FCC-Logo_7.3x6mm_SilkScreen`, `FCC-Logo_9.6x8mm_SilkScreen`, `FCC-Logo_14.6x12mm_SilkScreen`, `FCC-Logo_24.2x20mm_SilkScreen`, `FCC-Logo_36.3x30mm_SilkScreen`, `FCC-Logo_48.3x40mm_SilkScreen` | SilkScreen only |
| UKCA mark | `UKCA-Logo_6x6mm_SilkScreen`, `UKCA-Logo_8x8mm_SilkScreen`, `UKCA-Logo_12x12mm_SilkScreen`, `UKCA-Logo_20x20mm_SilkScreen`, `UKCA-Logo_30x30mm_SilkScreen`, `UKCA-Logo_40x40mm_SilkScreen` | SilkScreen only |
| WEEE mark | `WEEE-Logo_4.2x6mm_SilkScreen`, `WEEE-Logo_5.6x8mm_SilkScreen`, `WEEE-Logo_8.4x12mm_SilkScreen`, `WEEE-Logo_14x20mm_SilkScreen`, `WEEE-Logo_21x30mm_SilkScreen`, `WEEE-Logo_28.1x40mm_SilkScreen` | SilkScreen only |
| RoHS mark | `RoHS-Logo_6mm_SilkScreen`, `RoHS-Logo_8mm_SilkScreen`, `RoHS-Logo_12mm_SilkScreen`, `RoHS-Logo_20mm_SilkScreen`, `RoHS-Logo_30mm_SilkScreen`, `RoHS-Logo_40mm_SilkScreen` | SilkScreen only (single dimension) |
| KiCad logo | `KiCad-Logo_5mm_SilkScreen` .. `_6mm_`, `_8mm_`, `_12mm_`, `_20mm_`, `_30mm_`, `_40mm_SilkScreen`; and `KiCad-Logo_5mm_Copper` .. `KiCad-Logo_40mm_Copper` | Copper + SilkScreen |
| KiCad logo alt | `KiCad-Logo2_5mm_SilkScreen` .. `KiCad-Logo2_40mm_SilkScreen`; `KiCad-Logo2_5mm_Copper` .. `KiCad-Logo2_40mm_Copper` | Copper + SilkScreen |
| OSHW logo | `OSHW-Logo_5.7x6mm_SilkScreen`, `OSHW-Logo_7.5x8mm_SilkScreen`, `OSHW-Logo_11.4x12mm_SilkScreen`, `OSHW-Logo_19x20mm_SilkScreen`, `OSHW-Logo_28.5x30mm_SilkScreen`, `OSHW-Logo_38.1x40mm_SilkScreen` (+ `_Copper` twin of each, e.g. `OSHW-Logo_11.4x12mm_Copper`) | Copper + SilkScreen |
| OSHW logo alt | `OSHW-Logo2_7.3x6mm_SilkScreen`, `OSHW-Logo2_9.8x8mm_SilkScreen`, `OSHW-Logo2_14.6x12mm_SilkScreen`, `OSHW-Logo2_24.3x20mm_SilkScreen`, `OSHW-Logo2_36.5x30mm_SilkScreen`, `OSHW-Logo2_48.7x40mm_SilkScreen` (+ `_Copper` twins) | Copper + SilkScreen |
| OSHW symbol | `OSHW-Symbol_6.7x6mm_SilkScreen`, `OSHW-Symbol_8.9x8mm_SilkScreen`, `OSHW-Symbol_13.4x12mm_SilkScreen`, `OSHW-Symbol_22.3x20mm_SilkScreen`, `OSHW-Symbol_33.5x30mm_SilkScreen`, `OSHW-Symbol_44.5x40mm_SilkScreen` (+ `_Copper` twins) | Copper + SilkScreen |
| High voltage | `Symbol_HighVoltage_Triangle_6x6mm_Copper`, `Symbol_HighVoltage_Triangle_8x7mm_Copper`, `Symbol_HighVoltage_Triangle_17x15mm_Copper`, `Symbol_HighVoltage_NoTriangle_2x5mm_Copper`, `Symbol_HighVoltage_NoTriangle_6x15mm_Copper` | Copper only |
| Attention / danger | `Symbol_Attention_Triangle_8x7mm_Copper`, `Symbol_Attention_Triangle_17x15mm_Copper`, `Symbol_Danger_8x8mm_Copper`, `Symbol_Danger_18x16mm_Copper` | Copper only |
| ESD (old style) | `Symbol_ESD-Logo_CopperTop`, `Symbol_ESD-Logo-Text_CopperTop` | CopperTop only |
| Licence marks | `Symbol_GNU-GPL_CopperTop_Big`, `Symbol_GNU-GPL_CopperTop_Small`, `Symbol_GNU-Logo_CopperTop`, `Symbol_GNU-Logo_SilkscreenTop`, `Symbol_CC-Attribution_CopperTop_Small`, `Symbol_CC-Noncommercial_CopperTop_Small`, `Symbol_CC-ShareAlike_CopperTop_Big`, `Symbol_CC-PublicDomain_CopperTop_Small`, `Symbol_CC-PublicDomain_SilkScreenTop_Big`, `Symbol_CreativeCommons_CopperTop_Type1_Big`, `Symbol_CreativeCommons_CopperTop_Type2_Big`, `Symbol_CreativeCommons_SilkScreenTop_Type2_Big`, `Symbol_CreativeCommonsPublicDomain_SilkScreenTop_Small` | old `CopperTop` / `SilkScreenTop` style |
| Polarity | `Polarity_Center_Positive_6mm_SilkScreen`, `_8mm_`, `_12mm_`, `_20mm_`, `_30mm_`, `_40mm_SilkScreen`; and `Polarity_Center_Negative_6mm_SilkScreen` .. `Polarity_Center_Negative_40mm_SilkScreen`; plus `Symbol_Barrel_Polarity` | SilkScreen only |
| Layer markers | `LayerMarker_2_3.81x2.54mm_TextH1mm_P1.27mm`, `LayerMarker_2_3.81x2.54mm_TextH1mm_P1.27mm_BottomMirrored`, `LayerMarker_2_3.81x2.54mm_TextH1mm_P1.27mm_Named_BottomMirrored`, `LayerMarker_4_6.35x2.54mm_TextH1mm_P1.27mm_Named`, `LayerMarker_4_6.35x2.54mm_TextH1mm_P1.27mm_LowerMirrored`, `LayerMarker_10_14x2.54mm_TextH1mm_P1.27mm_AlNum_BottomMirrored`, `LayerMarker_10_14x2.54mm_TextH1mm_P1.27mm_Named_LowerMirrored`, `LayerMarker_32_41.9x2.54mm_TextH1mm_P1.27mm_AlNum` (61 files, layer counts 2..32 even) | copper stack marker |
| Misc | `Screw_Generic_2.0x3.0mm_SilkScreen`, `EasterEgg_EWG1308-2013_ClassA`, `Smolhaj_Scale_0.1` | - |

### 4e. Enclosures, lightpipes, standoffs - no KiCad stock; 7Sigma precedent (verbatim, from `7Sigma.pretty`)

| Verbatim 7Sigma name | Kind | Naming pattern used |
|---|---|---|
| `HAMMOND_1551RFLGY` | enclosure | `<MANUFACTURER_UPPERCASE>_<ExactPartNumber>` |
| `HAMMOND_1551TFLGY` | enclosure | same |
| `HAMMOND_1551XFLGY` | enclosure | same |
| `HAMMOND_1556CGY` | enclosure | same |
| `TAKACHI_SIM6-12-3W` | enclosure | same |
| `FIX-LEMB2-4.8V0-F` | lightpipe | bare manufacturer part number |
| `FIX-LEMB2-7V0-F` | lightpipe | bare manufacturer part number |
| `FIX-LEMB3-8V0-F` | lightpipe | bare manufacturer part number |
| `7Sigma_Logo` | house logo | `<Org>_Logo` |

### 4f. 7Sigma names in these four families that deviate from stock (verified)

| 7Sigma name | Stock equivalent | Difference |
|---|---|---|
| `MountingHole_2.5mm_Pad_4mm` | `MountingHole_2.5mm_Pad` | **`_4mm` is not KiCad grammar**; 7Sigma pad is 4.0 mm, stock is 5.0 mm; 7Sigma `descr` says "no annular, 4mm pad" which contradicts itself |
| `MountingHole_3.2mm_M3_Pad_6mm` | `MountingHole_3.2mm_M3_Pad` | `_6mm` not KiCad grammar; 7Sigma pad 6.0 mm vs stock 6.4 mm |
| `TestPoint_Pad_D1.5mm` | `TestPoint_Pad_D1.5mm` | matches stock exactly |
| `TestPoint_Pad_1.5x1.5mm` | `TestPoint_Pad_1.5x1.5mm` | matches stock exactly |
| `Crystal_SMD_3225-4Pin_3.2x2.5mm` | `Crystal_SMD_3225-4Pin_3.2x2.5mm` | matches stock exactly |
| `Relay_SPDT_Omron_G2RL-1` | `Relay_SPDT_Omron_G2RL-1` | matches stock exactly |
| `OSC-SMD_4P-L3.2-W2.5-BL` | `Oscillator_SMD_SiT_PQFN-4Pin_3.2x2.5mm` | generator style, LCSC import |
| `RELAY-SMD_G6K-2F-X-XX` | `Relay_DPDT_Omron_G6K-2F` | generator style, LCSC import |
| `SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0-H4.3` | `SW_PUSH_6mm_H4.3mm` | generator style, LCSC import |
| `SW-TH_4P-L6.0-W6.0-P4.50-LS6.5-H9.0` | (no stock twin) | generator style, LCSC import |

## How to name a new part in this family

========================================================================
GROUP 1 - A NEW CRYSTAL, RESONATOR OR OSCILLATOR
========================================================================

1. Read the case dimensions off the datasheet's outline drawing: L x W in mm,
   one decimal place. Read the land count off the recommended land pattern
   (2 or 4 for crystals, 4 or 6 for oscillators).
2. Decide SMD vs THT. SMD crystals get `Crystal_SMD_`, THT get `Crystal_`.
   Oscillators always get `Oscillator_SMD_` for surface mount, plain
   `Oscillator_` for DIP/THT.
3. Compute the dimension code as L and W in tenths of a millimetre, two digits
   each, L first: 3.2 x 2.5 mm -> `3225`. If that code already exists in the
   table above with the same pin count, YOU ARE DONE - reuse the stock name.
4. If the code is new, choose between the two legal shapes:
   * The part is a commodity case shared by many vendors:
     `Crystal_SMD_<code>-<n>Pin_<L>x<W>mm`
     e.g. a new 4-pad 1.6 x 1.2 mm crystal -> `Crystal_SMD_1612-4Pin_1.6x1.2mm`
   * The land pattern is vendor-specific (asymmetric pads, unusual keep-out):
     `Crystal_SMD_<Manufacturer>_<Series>-<n>Pin_<L>x<W>mm`
     Manufacturer token: use the form already in the library for that vendor -
     `Abracon`, `SeikoEpson`, `MicroCrystal`, `TXC`, `WE`, `EuroQuartz`,
     `Citizen`, `Qantek`, `ECS`, `FOX` (crystals) / `Fox` (oscillators),
     `FrontierElectronics`. Add a new vendor token in CamelCase, no spaces.
5. THT crystal: `Crystal_<Case>_<Horizontal|Vertical>` if the case has a
   standard HC number; `Crystal_<Case>_D<dia>mm_L<len>mm_<Horizontal|Vertical>`
   for a cylinder. Add `_1EP_style1` only if you also add the SMD case-ground
   pad numbered 3.
6. Hand-solder twin: append `_HandSoldering` to the otherwise-identical name.
   Never invent any other elongated-pad suffix.
7. Resonator, not crystal: swap the leading token to `Resonator` /
   `Resonator_SMD` and keep the same tail grammar.
8. Oscillator with 6 lands: `-6Pin` is the norm; `-6L` exists only for
   `Oscillator_SMD_SiTime_PQFD-6L_3.2x2.5mm`, do not copy it for new parts.
9. If KiCad ships nothing for this case, the footprint is a house part in the
   `7Sigma:` namespace. Match whichever style the 7Sigma family already uses
   (see footprint-conventions skill s1): if the part came from LCSC/EasyEDA and
   sits beside `OSC-SMD_4P-L3.2-W2.5-BL`, keep the generator style
   `OSC-SMD_<n>P-L<len>-W<wid>[-BL]`; if you hand-authored it from the
   datasheet, use the KiCad-stock style above so it reads the same as
   `Crystal_SMD_3225-4Pin_3.2x2.5mm`, which 7Sigma already mirrors verbatim.

========================================================================
GROUP 2 - A NEW SWITCH OR BUTTON
========================================================================

1. Classify the switch electrically from the datasheet's contact table, not
   from its marketing name: poles and throws, and whether it is momentary
   normally-open (`NO`) or normally-closed (`NC`).
2. Pick the family shape from what already exists nearby:
   * Tactile SMD button, generic: `SW_SPST_<Series>` - e.g. a new E-Switch
     TL3306 SMD tact -> `SW_SPST_TL3306A`. This is the majority style.
   * Tactile button, full modern form (preferred for anything new upstream):
     `SW_Push_1P1T_NO_<Mfr>_<Series>` - e.g. a new C&K KSC8xx
     -> `SW_Push_1P1T_NO_CK_KSC8xxG`.
   * Generic unbranded THT tact: `SW_PUSH_<size>mm_H<height>mm` - note PUSH is
     uppercase in this legacy family only. A new 7 mm / 6 mm-stem generic
     -> `SW_PUSH_7mm_H6mm` (drop the trailing `.0`: `H6mm` not `H6.0mm`).
   * Right-angle tact: add `_Angled`; upright: `_Straight`. These sit before
     the vendor token in `SW_Tactile_...` names and after `NO` in
     `SW_Push_...` names.
   * Slide / toggle / rotary: `SW_<contacts>_<Mfr>_<Series>`, e.g. a new
     Shouhan SPDT slide -> `SW_SPDT_Shouhan_MSK22D18`.
   * DIP bank: `SW_DIP_SPSTx<nn>_<Slide|Piano>_<bodyL>x<bodyW>mm_W<span>mm_P<pitch>mm`
     with `x<nn>` zero-padded. THT span is `W7.62mm`, SMD gull-wing `W8.61mm`,
     J-pin `W6.73mm` + `_JPin`.
3. Append geometry only when it disambiguates two otherwise-identical names:
   `_H<h>mm` for stem height, `_WithStem` / `_WithoutStem`,
   `_ShortPushTravel` / `_MiddlePushTravel`, `_LowProfile`, `_SocketPins`.
4. Do NOT add `_SMD` or `_THT` - the library name already carries that. The
   only stock exceptions (`SW_TH_Tactile_...`, `Relay_DPDT_FRT5_SMD`) are
   legacy, not a pattern to copy.
5. If nothing in KiCad matches, it is a house footprint. 7Sigma's existing
   switch precedent is generator style from LCSC imports -
   `SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0-H4.3`, `SW-TH_4P-RA-L6.0-W6.0-H9.0`
   (`RA` = right-angle, `LS` = lead span) - so keep that style for an
   EasyEDA/LCSC import and the `SW_Push_...` style for a hand-authored one.

========================================================================
GROUP 3 - A NEW RELAY
========================================================================

1. Read the contact arrangement from the datasheet's contact-form line, then
   convert to KiCad's token:
     1 Form A -> `SPST` (or `SPST-NO` if you want the mode explicit)
     1 Form B -> `SPST` (normally closed; note stock uses plain SPST here)
     1 Form C -> `SPDT`
     2 Form A -> `DPST`
     2 Form C -> `DPDT`
     3 Form A -> `3PST`
   For a latching or bistable coil, add `_DoubleCoil` (Kemet-style, preferred
   for new parts) - do not invent a fourth spelling.
2. Name it `Relay_<CONTACTS>_<Manufacturer>_<Series>`.
   Manufacturer tokens already in stock, verbatim: `Omron`, `Kemet`, `Hongfa`,
   `Finder`, `Fujitsu`, `Panasonic`, `AXICOM`, `COTO`, `StandexMeder`, `TE`,
   `HsinDa`, `CUI`, `PotterBrumfield`, `SANYOU`, `NCR`, `Tyco`, `Zettler`,
   `Schrack`, `RAYEX`. Use an underscore after the vendor
   (`Relay_SPDT_Omron_G2RL-1`); the hyphenated forms
   (`Relay_SPDT_Omron-G5LE-1`, `Relay_SPST_Zettler-AZSR131`,
   `Relay_SPDT_RAYEX-L90`) are historical - do not copy them for new parts.
3. Add the coil-pin pitch only if the same series ships in more than one pitch,
   and match the family's existing spelling: `_RM<p>mm` for Schrack/TE-German
   parts, `_Pitch<p>mm` for AXICOM parts.
4. Add orientation (`_Horizontal` / `_Vertical`) only if the series has both.
   Add `_CircularHoles` only if you are supplying a round-drill alternative to
   an existing oval-hole footprint.
5. Wildcard the coil-voltage digits in the series token if one land pattern
   covers the whole voltage range - use lowercase `xx` for new parts
   (`HF3F-L-xx-1ZL1T`), not `XX`.
6. SMD relay: identical grammar, file goes in Relay_SMD; do NOT append `_SMD`.
7. Socket, not relay: `Relay_Socket_<CONTACTS>_<Manufacturer>_<Series>`.

========================================================================
GROUP 4 - A NEW MECHANICAL / BOARD FEATURE
========================================================================

MOUNTING HOLE
1. Get the finished hole diameter. For a screw, use the standard clearance
   drill: M2 -> 2.2, M2.5 -> 2.7, M3 -> 3.2, M4 -> 4.3, M5 -> 5.3, M6 -> 6.4,
   M8 -> 8.4 mm. For a bare pin/standoff hole, use the actual diameter.
2. Assemble strictly in this order:
   `MountingHole_` + `<drill>mm` + [`_M<thread>`] + [`_<HeadStd>`] + [`_Pad`] +
   [`_Via` | `_TopOnly` | `_TopBottom`]
   * Strip trailing zeros in the drill: `3mm`, `4mm`, `5mm`, `6mm`; keep the
     decimal where real: `2.5mm`, `3.2mm`, `4.3mm`.
   * Include `_M<thread>` ONLY when the drill is the clearance size for that
     thread AND the thread/drill pair is one of the seven bound pairs above.
     A 2.5 mm hole is NOT an M2.5 clearance hole (M2.5 needs 2.7 mm), which is
     why no `MountingHole_2.5mm_M2.5` exists.
   * Include `_<HeadStd>` (`DIN965`, `ISO7380`, `ISO14580`) only when you draw
     the matching head keep-out circle. With no head standard, the pad OD is
     2 x drill; with one, the pad OD is that standard's head OD.
   * `_Pad` is a BARE token. There is NO diameter after it. If you need a
     non-standard pad OD, the name must NOT look like a stock name - see below.
   * Only one of `_Via` / `_TopOnly` / `_TopBottom`, always last.
3. Check the matrix in the table first - the odds are the exact name already
   exists. 166 combinations ship.
4. When the geometry you need genuinely is not in stock (this is the
   `MountingHole_2.5mm_Pad_4mm` case): the KiCad grammar has NO pad-diameter
   token, so any name carrying one is a house extension. Two clean options,
   pick one and apply it to BOTH existing 7Sigma files:
   (a) Preferred if the pad size is not a hard requirement - delete the house
       footprints and use stock `MountingHole_2.5mm_Pad` (5.0 mm pad) and
       `MountingHole_3.2mm_M3_Pad` (6.4 mm pad). This is the lowest-surprise
       outcome: 7Sigma already mirrors several stock mechanical names verbatim
       (`TestPoint_Pad_D1.5mm`, `TestPoint_Pad_1.5x1.5mm`).
   (b) If the smaller pad is required (tight keep-out under a standoff), keep
       the house footprint but make the deviation unmistakable by fusing the
       diameter onto the token so it cannot be read as stock `_Pad` plus a
       stray size: `MountingHole_2.5mm_Pad4mm` and
       `MountingHole_3.2mm_M3_Pad6mm`. Then fix the `descr`: the current
       "Mounting Hole 2.5mm, no annular, 4mm pad" is self-contradictory - the
       part DOES have a 4 mm annular ring.
   Either way, file it as a `propose_footprint_edit` draft; the current
   `_Pad_4mm` / `_Pad_6mm` spelling should not survive, because it reads as a
   stock KiCad name and is not one.
5. Tooling/panelisation hole, not a screw hole: `ToolingHole_<dia>mm`.

TEST POINT
1. Pick the physical form: SMD land, THT land, plated hole, solder bridge,
   two-pad, wire loop, or a Keystone turret.
2. Name it with the matching sub-grammar, ALWAYS one decimal on Pad/THTPad/
   Plated_Hole dimensions: a new 5 mm round SMD land -> `TestPoint_Pad_D5.0mm`;
   a new 3 mm square THT land on a 1.4 mm drill ->
   `TestPoint_THTPad_3.0x3.0mm_Drill1.4mm`. Loop diameters take two decimals.
3. Round land uses `D<dia>mm`; square land uses `<W>x<H>mm` with no `D`.
4. Order is always land geometry then `_Drill<d>mm`, never the reverse.

FIDUCIAL
1. Name it `Fiducial_<copper>mm_Mask<opening>mm`. Strip trailing zeros:
   a 2 mm copper dot with a 4 mm opening -> `Fiducial_2mm_Mask4mm`.
2. Default the opening to 2x the copper (IPC Level A) unless the assembler
   specifies otherwise; 3x variants exist for the same copper size.
3. Cross-hair artwork instead of a solid dot: insert `Cross` after `Fiducial`
   -> `Fiducial_Cross_<copper>mm_Mask<opening>mm`.
4. Leave the pad number empty, matching stock: `(pad "" smd circle ...)`.

LOGOS, MARKS, LAYER MARKERS (non-electrical artwork)
1. Regulatory / open-hardware marks live in Symbol.pretty and are pure
   graphics - no pads, no net, no courtyard.
2. New mark at an existing size: `<Mark>-Logo_<W>x<H>mm_<Copper|SilkScreen>`.
   Use the single-dimension form (`<size>mm`) only for square-ish marks whose
   family already does that (KiCad-Logo, RoHS-Logo).
3. Do not offer a `_Copper` variant for a mark that is silkscreen-only
   upstream (CE, ESD, FCC, RoHS, UKCA, WEEE) unless you are deliberately
   extending the family - `RoHS-Logo_12mm_Copper` and
   `CE-Logo_8.5x6mm_Copper` do not exist.
4. Hazard pictograms use the `Symbol_` prefix and are Copper-only:
   `Symbol_<Hazard>[_Triangle|_NoTriangle]_<W>x<H>mm_Copper`.
5. A house logo follows the 7Sigma precedent `7Sigma_Logo`; add a size and
   layer if you ever ship more than one: `7Sigma_Logo_12mm_SilkScreen`.

ENCLOSURES, LIGHTPIPES, STANDOFFS
1. KiCad ships NO enclosure, lightpipe or standoff library, so there is no
   stock name to copy - these are always house parts.
2. Enclosure: follow the 7Sigma precedent exactly -
   `<MANUFACTURER_UPPERCASE>_<ExactPartNumber>`, e.g. a new Hammond 1551KFLGY
   -> `HAMMOND_1551KFLGY`; a new Takachi -> `TAKACHI_<partno>`.
   Manufacturer token in caps, part number exactly as the datasheet prints it
   including hyphens.
3. Lightpipe: bare manufacturer part number, matching
   `FIX-LEMB2-4.8V0-F` / `FIX-LEMB3-8V0-F`. Then apply the house lightpipe
   rules from the footprint-conventions skill s7: omit `F.CrtYd` entirely,
   omit the mounting through-hole pad, document the >=1 mm under-pipe
   clearance with a `Cmts.User` note plus a dashed `Dwgs.User` circle at the
   head OD, build the STEP with the post bottom at z = 1.0 mm, and add the
   base component to `footprint_style.exempt_base_components` so the validator
   skips the courtyard checks.
4. Standoff / spacer: no precedent exists. Use the enclosure pattern
   (`<MANUFACTURER>_<PartNumber>`) rather than inventing a generic
   `Standoff_...` grammar, so it matches the neighbouring house parts.
5. All of these are non-electrical: they still must satisfy the pad-shape,
   silkscreen-width and no-`easyeda2kicad:`-prefix rules, and they must NOT be
   renamed with a `MountingHole_` prefix just because they include a hole -
   put the NPTH in as `np_thru_hole` per skill s5 and keep the part name.

## Pitfalls

VERIFICATION TRAP THAT AFFECTS ANYONE REDOING THIS WORK
* macOS APFS is case-insensitive. `test -f .../SW_Push_6mm.kicad_mod` SUCCEEDS
  even though the real file is `SW_PUSH_6mm.kicad_mod`. Any "I checked it
  exists" claim made with `test -f`, `[ -f ]`, `ls <name>` or `os.path.exists`
  on macOS is worthless for case. Verify against a `set(os.listdir(...))`
  string membership test. Every name in these tables was verified that way.

GROUP 1 - CRYSTALS & OSCILLATORS
* The 4-digit code is METRIC TENTHS (0.1 mm units), not hundredths and not
  imperial. 3225 = 3.2 x 2.5 mm. Hundredths would give 0.32 x 0.25 mm.
* `0603` is the single exception and it is a booby trap two ways over:
  `Crystal_SMD_0603-2Pin_6.0x3.5mm` is a 6.0 x 3.5 mm case (legacy Petermann
  "SMD0603" series code). It is NOT 0.6 x 0.3 mm, and it is NOT the imperial
  0603 chip package (1.6 x 0.8 mm). Always trust the `<L>x<W>mm` suffix.
* Trailing-zero inconsistency in the mm suffix:
  `Crystal_SMD_Qantek_QC5CB-2Pin_5x3.2mm` and
  `Crystal_SMD_TXC_7A-2Pin_5x3.2mm` write `5x3.2mm`, while everything else
  writes `5.0x3.2mm`. Copy the exact string; do not normalise.
* Not every code/pin-count/hand-solder combination exists. Verified ABSENT:
  `Crystal_SMD_3225-2Pin_3.2x2.5mm`, `Crystal_SMD_2016-2Pin_2.0x1.6mm`,
  `Crystal_SMD_2520-2Pin_2.5x2.0mm`, `Crystal_SMD_5032-4Pin_5.0x3.2mm_HandSoldering`,
  `Crystal_SMD_3225-4Pin_3.2x2.5mm_RotB`.
* Same vendor, different capitalisation across the two libraries:
  `Crystal_SMD_FOX_FQ7050-4Pin_7.0x5.0mm` (FOX) vs
  `Oscillator_SMD_Fox_FT5H_5.0x3.2mm` (Fox). Both verified; neither
  alternative spelling exists.
* THT HC-case names are irregular. `Crystal_HC51_Horizontal` has NO `-U`, but
  `Crystal_HC51-U_Vertical` does. `Crystal_HC49_Vertical` and
  `Crystal_HC51_Vertical` do not exist. `Crystal_HC35-U` has no orientation
  token at all. `Crystal_HC49-U-3Pin_Horizontal` does not exist (vertical only).
* KiCad's own `descr` fields are unreliable:
  `Crystal_SMD_5032-2Pin_5.0x3.2mm` carries `descr "SMD2520/2, ..."` - an
  upstream copy-paste error. The filename is the authority, never the descr.
* `_RotB` means rotated pad layout, NOT "revision B" and NOT hand-soldering.
  Only 1 crystal and 3 oscillator files use it.
* `Oscillator_SeikoEpson_SG-8002DB` and `-DC` have NO `_SMD` token, while
  `Oscillator_SMD_SeikoEpson_SG8002CA-4Pin_7.0x5.0mm` does - and note the
  hyphen appears in `SG-8002DB` but not in `SG8002CA`.
* `_OCXO` appears in two positions: `Oscillator_OCXO_Morion_MV267` (before the
  vendor, no `_SMD`) and `Oscillator_SMD_OCXO_ConnorWinfield_OH300` (after
  `_SMD`).
* 4-land SMD crystals: all four lands are numbered `1`..`4`. Two of them are
  the grounded case tabs, but the actual pin-to-function mapping must come
  from the datasheet pin table - do not assume 1/3 signal, 2/4 ground.
* `_1EP_style1` vs `_style2` differ physically, not cosmetically: style1 adds
  ONE large SMD ground pad (11 x 13.5 mm, pad 3); style2 adds that pad PLUS two
  `thru_hole rect` pads sharing pad number 3.

GROUP 2 - SWITCHES & BUTTONS
* Case matters and is inconsistent within the same library.
  `SW_PUSH_6mm` (uppercase) vs `SW_Push_1P1T_NO_CK_KMR2` (mixed). Verified:
  `SW_Push_6mm` and `SW_PUSH_1P1T_NO_CK_KMR2` do NOT exist.
* Separator matters: `SW_PUSH_6mm` uses an underscore before the size,
  `SW_PUSH-12mm` uses a HYPHEN. `SW_PUSH_12mm` does not exist.
* Height token spelling varies wildly:
  `SW_PUSH_6mm_H5mm` (no decimal, has `mm`),
  `SW_PUSH_6mm_H4.3mm` (decimal, has `mm`),
  `SW_PUSH_1P1T_6x3.5mm_H5.0_APEM_MJTP1250` (decimal, NO `mm`).
* Eleven files in these two libraries have NO `SW_` prefix at all and will be
  missed by any `SW_*` search: `Nidec_Copal_CAS-120A`, `Nidec_Copal_SH-7010A`,
  `Nidec_Copal_SH-7010B`, `Nidec_Copal_SH-7040B`, `Panasonic_EVQPUJ_EVQPUA`,
  `Panasonic_EVQPUK_EVQPUB`, `Panasonic_EVQPUL_EVQPUC`,
  `Panasonic_EVQPUM_EVQPUD` (SMD); `KSA_Tactile_SPST`,
  `Nidec_Copal_SH-7010C`, `Push_E-Switch_KS01Q01` (THT).
* Contact designation is sometimes the SECOND token and sometimes the LAST:
  `SW_DPDT_CK_JS202011JCQN` vs `SW_CK_JS202011AQN_DPDT_Angled` vs
  `SW_E-Switch_EG2219_DPDT_Angled` vs `SW_PUSH_E-Switch_FS5700DP_DPDT`.
* SPST and 1P1T mean the same thing and both appear, including mixed inside one
  name: `SW_Push_SPST_NO_Alps_SKRK` sits next to
  `SW_Push_1P1T_NO_CK_KMR2`. There is no rule; match the family.
* `SW_Tactile_Straight_KSA0Axx1LFTR` has no contact token, but
  `SW_Tactile_SPST_Angled_PTS645Vx31-2LFS` does. Verified:
  `SW_Tactile_SPST_Straight_KSA0Axx1LFTR` does not exist.
* `SW_Tactile_SPST_NO_Straight_CK_PTS636Sx25SMTRLFS` lives in
  Button_Switch_**SMD**, despite the `SW_Tactile_` prefix that is otherwise
  the THT house style. Never infer the library from the prefix.
* DIP-switch pin-span is the discriminator between the THT and SMD versions of
  the same bank: `W7.62mm` = THT, `W8.61mm` = SMD gull-wing,
  `W6.73mm` + `_JPin` = SMD J-lead, `W5.08mm`/`W5.9mm`/`W5.25mm`/`W6.15mm` =
  vendor-specific SMD. `SW_DIP_SPSTx04_Slide_9.78x12.34mm_W7.62mm_P2.54mm`
  and `...W8.61mm_P2.54mm` are different files in different libraries.
* Pitch trailing zeros: `_P1mm` (Copal CVS) not `_P1.0mm`; but `_P1.27mm` and
  `_P2.54mm` keep theirs.
* `_MP` and `_SH` are hyphen-attached to the contact token, not underscore-
  separated: `SW_Push_1P1T-MP_NO_...`, `SW_Push_1P1T-SH_NO_...`.
* Reed switches sit in the button libraries under `SW_SPST_REED_...` and
  `SW_SPDT_REED_MSDM-DT` - do not look for them in a sensor or relay library.

GROUP 3 - RELAYS
* Vendor separator flips between underscore and hyphen for the SAME vendor.
  Verified EXISTS: `Relay_SPDT_Omron-G5LE-1`, `Relay_SPST_Omron-G5Q-1A`,
  `Relay_SPDT_Omron-G5Q-1`. Verified ABSENT: `Relay_SPDT_Omron_G5LE-1`,
  `Relay_SPST_Omron_G5Q-1A`. Meanwhile `Relay_SPDT_Omron_G2RL-1` and
  `Relay_DPDT_Omron_G6K-2P` use underscores. There is no rule - look it up.
* Four different spellings for a second coil, all in stock:
  `_DoubleCoil` (Kemet), `-Dual-Coil` (Schrack RT2), `-1coil` (Schrack RP3SL),
  and `_DoubleCoil` on the SMD Kemet EE2 family. Do not normalise.
* Contact form is stated twice, redundantly, on several families:
  `Relay_SPST-NO_Fujitsu_FTR-LYAA005x_FormA_Vertical` carries both `SPST-NO`
  and `_FormA`. Also `_Form_A` with underscores (SANYOU),
  `_Form1A` / `_Form1AB` (StandexMeder), `_FormA` (Schrack/Panasonic).
* Two pitch spellings: `_RM5mm` (Schrack) and `_Pitch5.08mm` (AXICOM). They
  are not interchangeable and both are correct in their own family.
* Five relay files omit the contact designation entirely and so will be missed
  by any `Relay_<contacts>_` pattern match: `Relay_NCR_HHG1D-1`,
  `Relay_Tyco_V23072_Sealed`, `Relay_StandexMeder_DIP_HighProfile`,
  `Relay_StandexMeder_DIP_LowProfile`, `Relay_StandexMeder_UMS`, plus
  `Relay_Fujitsu_FTR-B3S` in Relay_SMD.
* `Relay_2P2T_10x6mm_TE_IMxxG` uses `2P2T` where the rest of the library uses
  `DPDT` - same arrangement, different token - and puts the body size BEFORE
  the vendor.
* `Relay_DPDT_FRT5_SMD` carries a redundant `_SMD` suffix while already living
  in Relay_SMD; its THT sibling is `Relay_DPDT_FRT5`. Do not copy the suffix.
* Omron THT vs SMD variant letters are the real discriminator and they are one
  character apart: `Relay_DPDT_Omron_G6K-2P` (THT, P) vs
  `Relay_DPDT_Omron_G6K-2F` / `-2G` (SMD, F/G). Picking the wrong letter gives
  a footprint with the wrong lead form and it will pass every name check.
* Coil-voltage wildcards use three different cases: `xx` (Hongfa HF3F),
  `XX` (Hongfa JQC-3FF `0XX`), `x` (Finder `32.21-x000`,
  Fujitsu `FTR-LYAA005x`). Copy exactly.

GROUP 4 - MECHANICAL / BOARD FEATURES
* `_Pad` CARRIES NO DIAMETER. Verified across all 166 stock MountingHole
  files: there is no `_Pad<dia>mm`, no `_Pad_<dia>mm`, no `_Pad_4mm`. The
  7Sigma names `MountingHole_2.5mm_Pad_4mm` and
  `MountingHole_3.2mm_M3_Pad_6mm` are house inventions that LOOK like stock
  KiCad names but are not - and their geometry differs too (4.0 mm vs stock
  5.0 mm pad; 6.0 mm vs stock 6.4 mm pad). The 2.5 mm one also has a
  self-contradictory descr: "Mounting Hole 2.5mm, no annular, 4mm pad" -
  it does have an annular ring.
* Token order is fixed and easy to get wrong. It is drill, thread, head
  standard, `Pad`, qualifier. `MountingHole_2.5mm_Pad_Via` is right;
  `MountingHole_2.5mm_Via_Pad` and `MountingHole_2.5mm_Via` do not exist.
* `_Pad_Via` exists ONLY on variants with no head standard. Verified ABSENT:
  `MountingHole_3.2mm_M3_ISO7380_Pad_Via` and every other
  `<HeadStd>_Pad_Via` combination. Head-standard variants ship only bare,
  `_Pad`, `_Pad_TopOnly`, `_Pad_TopBottom`.
* M8 has NO head-standard variants at all: `MountingHole_8.4mm_M8_ISO7380`
  does not exist.
* Thread and drill are bound. `MountingHole_2.5mm_M2.5` does NOT exist - M2.5
  clearance is 2.7 mm, so the file is `MountingHole_2.7mm_M2.5`. Likewise
  `MountingHole_3.2mm_Pad` and `MountingHole_2.2mm_Pad` do not exist: those
  drills only ship with their `_M3` / `_M2` token attached.
* Drill trailing zeros are stripped for whole millimetres and kept otherwise.
  Verified EXISTS: `MountingHole_2mm`, `MountingHole_3mm`, `MountingHole_4mm`.
  Verified ABSENT: `MountingHole_2.0mm`, `MountingHole_3.0mm`,
  `MountingHole_4.0mm`. But `MountingHole_2.5mm` keeps its decimal.
* `MountingHole_2mm` and `MountingHole_2.1mm` are NPTH-only - no `_Pad`
  variant of either exists.
* The head standard changes real geometry, not just the name: for M3 the pad
  and head keep-out are DIN965 5.6 mm, ISO7380 5.7 mm, ISO14580 5.5 mm,
  vs 6.4 mm (= 2 x drill) with no head standard. Picking the wrong one silently
  changes the copper.
* `ToolingHole_1.152mm` lives in MountingHole.pretty but does NOT start with
  `MountingHole_` - a `MountingHole_*` glob misses it.
* TestPoint decimals are mandatory and differ by sub-family. Verified ABSENT:
  `TestPoint_Pad_D1mm`, `TestPoint_Pad_1.5mm`,
  `TestPoint_THTPad_D2.0mm_Drill1mm`, `TestPoint_Loop_D2.5mm_Drill1.0mm`.
  Pad/THTPad/Plated_Hole use ONE decimal (`D1.0mm`, `2.0x2.0mm`,
  `Drill1.0mm`); Loop uses TWO (`D2.50mm`, `D3.80mm`).
* Fiducial trailing zeros go the OTHER way from TestPoint - they are stripped.
  Verified ABSENT: `Fiducial_1.0mm_Mask2.0mm`. Correct: `Fiducial_1mm_Mask2mm`.
  Also `Fiducial_Cross_1.5mm_Mask3mm` does not exist - the only cross is
  `Fiducial_Cross_1.5mm_Mask2mm`.
* `Symbol_` is a prefix on SOME artwork and not others. `CE-Logo_...`,
  `RoHS-Logo_...`, `OSHW-Logo_...`, `Polarity_...`, `LayerMarker_...` have no
  `Symbol_` prefix even though they live in Symbol.pretty. Verified ABSENT:
  `Symbol_CE-Logo_8.5x6mm_SilkScreen`.
* Layer suffix availability is not uniform. Verified ABSENT:
  `CE-Logo_8.5x6mm_Copper`, `RoHS-Logo_12mm_Copper`. The regulatory marks
  (CE, ESD, FCC, RoHS, UKCA, WEEE) ship SilkScreen only; only KiCad-Logo,
  KiCad-Logo2, OSHW-Logo, OSHW-Logo2 and OSHW-Symbol ship both layers; the
  hazard pictograms ship Copper only.
* `SilkScreen` vs `Silkscreen` - both capitalisations exist in Symbol.pretty.
  Verified EXISTS: `Symbol_GNU-Logo_SilkscreenTop` (lowercase s) AND
  `Symbol_CC-PublicDomain_SilkScreenTop_Big` (uppercase S). Verified ABSENT:
  `Symbol_GNU-Logo_SilkScreenTop`.
* ESD appears twice with different grammars: modern
  `ESD-Logo_13.2x12mm_SilkScreen` and legacy `Symbol_ESD-Logo_CopperTop`.
* KiCad ships NO enclosure, lightpipe, standoff or "mechanical" library. Only
  Heatsink.pretty exists for bolt-on hardware. Do not go looking for a stock
  name for those - there is none, and any name someone "remembers" for one is
  fabricated.
* Lightpipes are deliberately non-conforming house parts: they omit `F.CrtYd`
  and omit the mounting through-hole pad, and the base component has to be in
  `footprint_style.exempt_base_components` or the validator will flag them.
  "Fix the missing courtyard" is the wrong instinct for these three files.


---
