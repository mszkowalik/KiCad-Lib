# 7Sigma Footprint Naming Standard — Proposal

> ### Decisions taken 2026-07-26 — these override the body of this document
>
> Three blockers were resolved by the maintainer. Where the text below disagrees with the
> rules in this box, **this box wins**, and `02-migration-173.md` already reflects it.
>
> **D1 — Vendor-token derivation (adopted).** The footprint vendor token is a deterministic
> function of the canonical manufacturer name in the `conventions-library` table:
> take the canonical value, remove spaces and dots, **keep the casing**, never abbreviate or
> truncate. `MEAN WELL` → `MEANWELL`, `Texas Instruments` → `TexasInstruments`,
> `STMicroelectronics` → `STMicroelectronics`, `Diodes Incorporated` → `DiodesIncorporated`,
> `Pulse Electronics` → `PulseElectronics`, `OSRAM` → `OSRAM`.
> **Tier 0 names are exempt** — a stock filename keeps its own spelling forever, so
> `Omron` in the stock `Relay_SPDT_Omron_G2RL-1` stays `Omron`.
> *Applied: 6 proposed names corrected.* Note the full canonical name also removes the
> `Diodes` vendor/category ambiguity, so no family-word prefix is needed.
>
> **D2 — `HandSoldering` (adopted).** House-minted variants use `_HandSoldering`, matching
> KLC F2.1 rule #10 verbatim. `_HandSolder` and `_Handsoldering` are never minted here.
> Consequence, stated so nobody "fixes" it later: the shipped library uses `HandSolder` on
> 108 files (chip passives and tantalum) against `HandSoldering` on 86. Those are Tier 0 and
> **keep their own spelling**. So a hand-solder chip passive adopted from stock will read
> `_HandSolder` while a house-authored variant reads `_HandSoldering`. That is correct and
> intended. The library currently contains **0** footprints with either spelling, so nothing
> needs changing today.
>
> **D3 — Rotation is never encoded in a name (adopted).** §3.6 is overridden. Names come from
> the datasheet nominal; a rotated or mis-origined import is a **geometry defect** for the
> validator to flag, not a fact to record in the string. This removes the double-rename
> (Wave 4 then Wave 5) that previously hit four footprints.
> Consequently the three renames that adopt a stock name whose copper differs from ours are
> **deferred to Wave 5** — fix the copper, then adopt the stock name in one step:
> `TDSON-8_6.15x5.15mm` (pad numbering differs — electrically significant),
> `RELAY-SMD_G6K-2F-X-XX` (rotated 90°), `BAT-TH_KEYS2466` (origin and drill).
> **After this change, no Wave 3 or Wave 4 rename adopts a stock name.**
>
> **Also rejected: §9 Q13** — `Lightpipe_..._Drill1.98mm` names a drill the footprint
> deliberately omits, contradicting this document's own objection to names that claim things
> the copper does not do.
>
> Coverage and collisions check out: all 173 footprints decided exactly once, no proposed
> name collides with another, and the only duplicate is the intended merge. Full evidence in
> `04-verification.md`.


**Status:** proposal, awaiting decisions in §9. **Scope:** the footprint `name` field (and the separate short `display_name`/package field). Symbol, component, 3D-model and library naming are out of scope. **Supersedes:** the nine per-family drafts; where a draft's field order or spelling conflicts with this document, **this document wins** (the affected rename rows are listed in §7).

---

## 1. Decision summary

**Adopted spine: the KiCad Library Convention (KLC), in the dialect the shipping KiCad 10 library actually uses — not the dialect printed on klc.kicad.org.**

Four decisions carry the whole standard:

1. **KLC is the spine.** IPC-7351 is stored as searchable metadata only. EasyEDA/LCSC generator strings are stripped on import, never kept.
2. **Stock is the reference implementation, and stock names are immune.** Where KiCad ships a footprint whose land pattern and pad numbering match ours, we take its filename byte-for-byte and no house rule may edit it. 91 of the current 173 names qualify today.
3. **One tier rule decides geometric vs vendor-MPN naming** (§2), applied by a four-question test, not by judgement.
4. **Where KLC is silent or self-contradictory, the house pins one answer globally** — decimal formatting, `HandSolder` spelling, mount tokens, axis order, vendor spelling, count padding. These are the four places two engineers provably produce different names today.

### What we are giving up, stated plainly

| Given up | Consequence | Mitigation |
|---|---|---|
| Machine-guaranteed uniqueness | Two different land patterns can share a name if every named field matches | Anti-shadowing rule (§3.8) + mandatory distinguishing token; never an ad-hoc counter (`ThermalVias2`) |
| IPC density levels (M/N/L) | No way to name "same package, looser land" | `_HandSolder` is the only variant token; it is not dimensionally defined |
| Body height in most SMD names | Two parts differing only in Z share a name | Height is named only where it changes the land or the 3D fit: electrolytics, tantalums, switches, some LGAs |
| Cross-vendor lookup from the name | A SnapEDA/Ultra Librarian/JLCPCB `RESC1608X55N` string does not resolve by search | Add an `ipc_name` alias field (§9, Q12) |
| Internal tidiness inside Tier 0 | The library will visibly contain `P3.50mm` next to `P3.5mm`, `Fuseholder_` next to `MountingHole_`, `HandSoldering`, `ublox_ZED`, wildcard MPNs | Deliberate. Byte-identity with 15,447 stock names is worth more than uniformity, because it is what makes review, diffing and autocomplete cheap |

### Why not IPC-7351 (verified, not preferred)

- **0 of 15,447** installed stock footprints match IPC-7351 grammar (regex-scanned). Adopting it means house parts never sort, autocomplete or diff alongside the library every engineer here already has open.
- **It cannot name half our BOM.** IPC-7351B's own scope is land patterns derived from JEDEC/EIA/IEC *package outlines*. Connectors, switches, relays, modules, antennas, enclosures, battery/fuse holders, SIM sockets and mechanical hardware are excluded — and IPC's own published escape hatch for them is literally `ManufacturerAbbreviation_ManufacturerPartNumber`, i.e. what KLC already does but without KLC's readable positional fields. That is **~80 of our 173 footprints**.
- **It cannot express what this library varies by.** No exposed-pad dimensions (its authors, PCB Libraries, publish this as defect (c)), no thermal-via concept at all. Six of our IC footprints differ from a sibling *only* by EP size or vias — under IPC they collide.
- **Active footgun.** IPC chip codes are metric: `RESC0603` is the imperial **0201**. KLC's `R_0603_1608Metric` carries both codes and kills the ambiguity.
- **Human cost.** `QFN50P300X300X80-17N` hides the pin count at character 17, encodes 16 leads as "17", and sorts by lead-span digit string. Nobody types it into the picker.

### Why not EasyEDA (the source of 47 current names)

It names the **component body, not the land pattern** — proven in this library: `SOT-23-5_L3.0-W1.7-P0.95-LS2.8-BL` declares a 2.8 mm span over pads that actually reach 3.46 mm. It has no manufacturer slot, no thermal-via token (which is why we already had to bolt on `-ThermalVias` with the wrong separator), an `H` that collides with its own documented `H`=Horizontal, and literal wildcards (`G6K-2F-X-XX` for a part that is actually G6K-2F-**Y**). Its own spec is unenforced: 2 of our 8 switch names violate its published production.

---

## 2. The one grammar, and the tier rule

### 2.1 Tier test — run in order, stop at the first Yes

| # | Question | Result |
|---|---|---|
| 1 | Does KiCad stock ship a footprint whose **land pattern and pad numbering** match ours? | **Tier 0** — adopt its filename byte-for-byte. Stop. |
| 2 | Does the footprint have **zero electrical lands**? | **Tier 4** — mechanical form. |
| 3 | Is there a **published package designation** (JEDEC / EIAJ / EIA case code / IEC / industry standard) whose parameter set fully determines the land? | **Tier 1** if our copper is the generic pattern. **Tier 2** if our copper deviates from generic, or the outline itself is vendor-proprietary. |
| 4 | Otherwise | **Tier 3** — vendor + MPN. |

**Anti-shadowing (binds every tier):** never mint a name equal to a stock name unless the copper is identical to stock's. If the copper differs, change a real field — add the vendor prefix, or record the true measured value.

| Tier | Shape | Example |
|---|---|---|
| 0 | stock filename, verbatim | `SOIC-8_3.9x4.9mm_P1.27mm` · `PhoenixContact_MC_1,5_6-GF-3.81_1x06_P3.81mm_Horizontal_ThreadedFlange` · `Xilinx_FGG484` |
| 1 | geometric, no vendor | `R_0603_1608Metric` · `QFN-28_4x4mm_P0.5mm` · `PinHeader_2x05_P2.54mm_Vertical_SMD` · `CP_EIA-7343-31_Kemet-D` |
| 2 | geometric + vendor (KLC F2.3) | `ST_LGA-12_2x2mm_P0.5mm_LayoutBorder4x2y` · `Winbond_USON-8-1EP_2x3mm_P0.5mm_EP0.3x1.7mm` · `Infineon_PG-TDSON-8_6.15x5.15mm` |
| 3 | vendor + MPN, family word first | `TerminalBlock_Dorabo_DB301V-3.5-2P_1x02_P3.50mm_Vertical` · `Quectel_EG915U_LGA-126_19.9x23.6mm_P1.1mm` · `Lightpipe_FIX-LEMB2-4.8V0-F` |
| 4 | mechanical, `Mechanical` token mandatory | `RaspberryPi_CM5_Mechanical_40x55mm_4xMountingHole2.7mm` · `Enclosure_Hammond_1551RFLGY` |

### 2.2 The grammar

```
[<Family>[_<Function|Config>][_<Actuation|Type>]_] [<Vendor>_] [<Series>_] <Package|MPN>
    [-<pins>[-<n>EP|-<n>MP|-<n>SH]]  |  [_<rows>x<pos>[-<n>MP|-<n>SH]]  |  [-<n>Pin]
    [_<X>x<Y>[x<Z>]mm]
    [_Layout<c>x<r>]
    [_P<pitch>mm]
    [_<Modifier>…]                     (EP, Mask, Pad, Drill, D, L, W, H, T, O)
    [_LayoutBorder<a>x<b>y]
    [_<Orientation>]                   (Vertical | Horizontal [| TabUp | TabDown])
    [_<Option>…]                       (ThermalVias, HandSolder, SMD/THT, …)
```

**Twelve slots, fixed order. Omit any slot freely; never reorder.** Two positional quirks are inherited from stock and preserved so the Tier 0 names stay legal under this grammar: `_Layout<c>x<r>` goes **before** the pitch, `_LayoutBorder<a>x<b>y` goes **after** it.

**Count field, three legal forms:**
- `-<pins>` glued to a package designation — `QFN-16`, `SOT-23-5`, `LGA-126`. Never zero-padded.
- `_<rows>x<pos>` as its own field for grid connectors — positions-per-row **always zero-padded to 2** (`1x02`, `2x05`, `2x50`), rows unpadded. Counts **electrical positions per row**, never total pads, never the circuit count in the MPN (a 100-contact dual-row part is `2x50`).
- `-<n>Pin` glued to a **series or product** token where no package designation exists — `Crystal_SMD_Abracon_ABM8G-4Pin`, `Quectel_LC76G-28Pin`. **Never glued to a verbatim MPN**, and bare EasyEDA-style `<n>P` counts are banned everywhere.

**Vendor and MPN always precede geometry.** This is a global override of the switch draft. Stock's dominant Tier 3 shape is `Family_Vendor_MPN_geometry_orientation_options` (JST, Molex, Hirose, TerminalBlock, BatteryHolder, Relay, Lightpipe, Heatsink, Fuseholder), so switches conform:

> `SW-SMD_4P-L6.0-W6.0-P4.50-LS9.0-H4.3` → **`SW_Push_SPST_Kinghelm_KH-6X6X4.3H-STM_6x6mm_H4.3mm_SMD`**
> `SW-TH_4P-RA-L6.0-W6.0-H9.0` → **`SW_Push_SPST_HCTL_TC-6615-9.0-160G_6x6mm_Horizontal_THT`**

---

## 3. Global mechanics — stated once

### 3.1 Character set and separators
`^[A-Za-z0-9_.,+-]+$`. **Never a space.** `_` separates fields; `-` binds tokens **inside** one field and is preserved verbatim inside MPNs. Comma and `+` are legal **only inside a verbatim manufacturer designation** (`PhoenixContact_MSTBV_2,5_...`, `DIN41612_M_3x14+6_...`) and may never appear in a house-minted token. Parentheses and slashes are forbidden even where stock uses them: spaces in a vendor MPN become hyphens (`HX JN1.27-2x5 TP H4.9` → `JN1.27-2x5-TP-H4.9`).

### 3.2 Capitalisation (KLC G1.6)
Acronyms all-caps (`EP`, `MP`, `SH`, `NSMD`, `LGA`). Package designations all-caps verbatim (`SOIC`, `HTSSOP`, `V-DFN3020-13-A`). Everything else CamelCase within a token — `ThermalVias`, `HandSolder`, `ThreadedFlange`, `PullBack`, `LayoutBorder`, `MountingHole`. **No internal underscores inside a word, no ALL-CAPS family or vendor tokens:**

> `ANT_3PIN_1206_3216Metric` → `PulseElectronics_W3011_3.2x1.6mm`
> `HAMMOND_1551RFLGY` → `Enclosure_Hammond_1551RFLGY`
> `RELAY-SMD_G6K-2F-X-XX` → `Relay_DPDT_Omron_G6K-2F-Y`

### 3.3 Family tokens are taken verbatim from the shipping library's majority spelling — even when it violates G1.6
The family token is the sort key, and clustering with stock is the point. Verified counts: `Fuseholder_` 45 files vs `FuseHolder_` 1 → **`Fuseholder_`** (this overrides the misc-family draft, which used KLC's printed `FuseHolder_`). Same rule gives **`Lightpipe`**, not `LightPipe`, despite the house base symbol being `LightPipe`.

### 3.4 Vendor tokens
1. If stock ships that manufacturer with an **unambiguous** spelling, stock wins: `MeanWell`, `ublox`, `Wuerth`, `PhoenixContact`, `Texas`, `Analog`, `Winbond`, `Diodes`, `Nexperia`, `InvenSense`, `Osram`, `Murata`, `Omron`, `BAT_Wireless`, **`Shouhan`** (overriding the draft's `ShouHan`).
2. If stock is **ambiguous** (`Jushuo` 2 files vs `JUSHUO` 26) or silent, the house canonical manufacturer wins, with spaces and illegal characters removed, geographic prefixes and legal-form/locality words dropped, and the manufacturer's own capitalisation preserved: `Jushuo`, `Ckmtw`, `Dorabo`, `Xinlaiya`, `Xunpu`, `Hanxia`, `Kinghelm`, `Hammond`, `TAKACHI`, `G-Switch`, `ST`, `Telit`, `Xilinx`, `RaspberryPi`, `Quectel`.
3. **Wildcards are banned in house-minted names** — no `X`, `xx`, `-XX` standing in for variant digits (`RELAY-SMD_G6K-2F-X-XX`, `_AP6335X` both fail). Tier 0 immunity covers stock's own wildcards.
4. A vendor's **package outline name** goes in the Package slot (`Infineon_PG-TDSON-8`, `Diodes_V-DFN3020-13-A`). A vendor's **drawing code** does not (TI `DSJ`, `RGY`) — it belongs in the description.

### 3.5 Numbers and units
Millimetres only. Decimal **point**, never comma. `mm` written **once**, after the last number of a dimension group. Lowercase `x` between axes.

**Minimum digits that represent the value exactly. No trailing-zero padding.** `3x3mm` not `3.0x3.0mm`; `P0.5mm` not `P0.50mm`; `H7mm` not `H7.0mm`; `2.2x2mm` not `2.2x2.0mm`.

Two narrow exceptions:
- **E1 — Tier 0.** A stock name keeps stock's formatting (`PhoenixContact_MCV_1,5_12-GF-3.5_1x12_P3.50mm_...`).
- **E2 — stock-sibling consistency.** A house footprint that is a variant of a stock family already in the library copies **that family's decimal padding** (only the padding — never a missing unit, a missing field, or a wildcard). Worked examples:
  - Terminal blocks: stock sibling `TerminalBlock_Degson_DG250-3.5-02P_1x02_P3.50mm_45Degree` → house `TerminalBlock_Dorabo_DB301V-3.5-2P_1x02_**P3.50mm**_Vertical`.
  - FFC: stock sibling `Jushuo_AFC07-S24FCA-00_1x24-1MP_P0.50_Horizontal` → house `Jushuo_AFC01-S22FCC-00_1x22-1MP_**P0.50mm**_Horizontal` (padding copied, missing `mm` **not** copied).
  - Board-to-board: stock sibling `Hirose_DF40C-100DS-0.4V_2x50_P0.4mm` → house `Hirose_DF40C-100DS-0.4V-51_2x50_**P0.4mm**` (this overrides the connector draft's `P0.40mm`).

### 3.6 Body size axis order
`<X>x<Y>mm` is **X then Y as drawn in this footprint's own coordinate frame**, not datasheet-long-side-first. Source of truth: the F.Fab body outline; if F.Fab was drawn at courtyard size, the silkscreen body rectangle; if neither is trustworthy, **omit the field**. This makes a 90°-rotated import visible instead of hidden, and it is what stock does (`BGA-200_10x14.5mm_Layout12x22` writes the shorter drawn-X first).

> `WSON-8_L6.0-W5.0-P1.27-BL-EP` → `WSON-8-1EP_5x6mm_P1.27mm_EP4.3x3.4mm` (stock's `6x5mm` land, rotated 90° — so it cannot shadow stock)

### 3.7 Exposed pads, vias, masks
- `-<n>EP` on the count field when *n* exposed pads carry their own pad numbers. The count is always written, even for 1. **Not** written when the tab shares a signal pin number (`Infineon_PG-TDSON-8_6.15x5.15mm`, tab = pin 8).
- `_EP<x>x<y>mm` after the pitch when the EP is a **single rectangle**. **Omit** when the EP copper is a segmented/custom polygon — a bounding box is not a pad size (KLC precedent: `WDFN-6-2EP_4.0x2.6mm_P0.65mm`).
- `_ThermalVias` is **mandatory** whenever plated vias carry the EP's pad number, and is always the last geometric token. Three current footprints violate this silently and are fixed in Wave 3. Tier 0 is exempt (`ESP32-WROOM-32U` ships 12 such vias with no token; upstream's omission, not ours).
- `_Mask<w>x<h>mm` after the EP token = reduced solder-mask window over the EP.

### 3.8 Options — closed vocabulary, always last, chained with `_`
`ThermalVias`, `HandSolder`, `PullBack`, `NexFET`, `ReverseMount`, `Hole<w>x<h>mm`, `Polarized`, `ThreadedFlange`, `MountHole`, `MountingPegs`, `Latch<len>mm`, `CircularHoles`, `Pin1Left`/`Pin1Right`, `TopOnly`/`TopBottom`/`Via`, `SilkScreen`/`Copper`, `Invisible`, `Mechanical`, `SMD`/`THT`. **Minting a new option token is a change to this document, not an ad-hoc decision.**

**`HandSolder` is the house spelling** — never `HandSoldering`, never `Handsoldering`. Verified stock split: 108 / 86 / 28. KLC F2.1 rule 10 says `HandSoldering`; KLC F3.3's own example says `HandSolder`; the chip-passive and tantalum libraries (this library's densest neighbours) use `HandSolder`. Tier 0 names keep whatever stock wrote, so **all matching must be case-insensitive**.

### 3.9 Mount technology is a disambiguator, not a field
Write `_SMD` / `_THT` only when the family contains **both** technologies and the other fields would not tell you which. Never `_TH` (`_THT` 268 files vs `_TH_` 7), never `RA`/`RightAngle`/`Straight`/`Angled`.

Two legal positions, fixed per family (§4):
- **Trailing option (default):** `PinHeader_2x05_P1.27mm_Vertical_SMD`, `SW_Push_SPST_..._6x6mm_H4.3mm_SMD`
- **Glued to the family word (three families only, because stock does):** `Crystal_SMD_...`, `Oscillator_SMD_...`, and the house `Antenna_SMD_...` / `Antenna_THT_...`

Everything else drops it, and the SMD/THT cue lives in `display_name`:

> `CONN-TH_DB301V-3.5-2P-GN` → `TerminalBlock_Dorabo_DB301V-3.5-2P_1x02_P3.50mm_Vertical`
> `SMA-SMD_BWSMA-KE-P001` → `SMA_BAT_Wireless_BWSMA-KE-P001` (display: "SMA SMD")
> `RJ45-TH_RC01812` → `RJ45_RCH_RC01812` (the `TH` was also **false** — it is a 12-pad SMD jack)

### 3.10 Orientation
`_Vertical` = mates/actuates perpendicular to the PCB. `_Horizontal` = parallel to the PCB (what datasheets call right-angle). **Include only when confirmed** from the datasheet or the land itself; omit rather than guess. `_TabUp`/`_TabDown` follow for TO packages; `_StaggerOdd`/`_StaggerEven` after that.

### 3.11 Banned tokens (EasyEDA import residue)
Stripped on import, never carried: leading `SMD_`/`TH_`/`CONN-TH_`/`FPC-SMD_`/`RJ45-TH_`/`SMA-SMD_`/`ANT-`/`BAT-`/`FUSE-`/`IND-`/`LED-`/`MIC-`/`OSC-`/`RELAY-`/`SIM-`/`XCVR_`; `L<n>-W<n>`; `LS<n>`; `-BL`/`-TL`/`-BR`/`-TR`; `-RD`/`-FD`/`-BI`; `-C`/`-R`; bare `-EP`; bare `<n>P`; `-RA`; `-H<n>` used for height in a field where `H` means Horizontal.

Every one of these either restates a value the package designation already fixes, describes the component body rather than the copper, or is recoverable from the file (pin-1 quadrant is pad 1's coordinates).

> `LGA-SMD_L23.6-W19.9-P1.10_EG915U-EC` → `Quectel_EG915U_LGA-126_19.9x23.6mm_P1.1mm`
> `XCVR_LE910R1-EU` → `Telit_LE910R1_LGA-181_28.2x28.2mm_Layout15x15_P1.8mm`

---

## 4. Per-family reference table

| Family | Tier(s) | Shape | Mount token | Count form | Representative |
|---|---|---|---|---|---|
| Chip passives R/C/CP/L/D/LED/Fuse | 0,1,2 | `<Fam>[_<Vendor>[_<MPN>]]_<Imperial>_<Metric>Metric[_Pad<w>x<h>mm][_HandSolder]` | none | none (2 lands) | `R_0603_1608Metric` · `LED_0805_2012Metric` |
| SMD tantalum | 0,1 | `CP_EIA-<LLWW>-<HH>_<Vendor>-<Letter>[_Pad…][_HandSolder]` | none | none | `CP_EIA-7343-31_Kemet-D` |
| SMD alu electrolytic | 0,1 | `{CP\|C}_Elec_<D>x<H>[_<Vendor>]` — **no unit suffix, ever** | none | none | `CP_Elec_6.3x7.7` |
| THT capacitor | 1 | `{C\|CP}_{Rect\|Disc\|Radial\|Axial}[_L…][_D…][_W…]_P<p>mm[_Horizontal]` | none | none | `CP_Radial_D10.0mm_P2.50mm` |
| Discrete SOT/SOD/SC/SMx | 0,1,2 | `[D_]<Designator>[-<pins>][_<Alias>-<pins>][_TabPin<n>][_<Opt>]` | none | `-<pins>` only when designator spans counts | `D_SOD-123` · `SOT-353_SC-70-5` · `SOT-223-3_TabPin2` |
| SO / SOP / SSOP / TSSOP / MSOP | 0,1,2 | `[<Vendor>_]<FAM>-<pins>[-<n>EP]_<X>x<Y>mm_P<p>mm[_EP…][_Mask…][_ThermalVias]` | none | `-<pins>` always | `SOIC-8_3.9x4.9mm_P1.27mm` |
| QFN / DFN / SON / LFCSP | 0,1,2 | as above | none | `-<pins>` always | `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm_ThermalVias` |
| LGA | 0,2,3 | `[<Vendor>_][<Series>_]LGA-<pads>[-<n>EP]_<X>x<Y>mm[_Layout<c>x<r>]_P<p>mm[_LayoutBorder<a>x<b>y]` | none | `-<pads>` | `ST_LGA-12_2x2mm_P0.5mm_LayoutBorder4x2y` |
| BGA / CSP | 0,2 | `[<Vendor>_]<FAM>-<balls>_<X>x<Y>mm_Layout<c>x<r>_P<p>mm[_Ball…_Pad…_NSMD]` | none | `-<balls>` at front of count field | `Xilinx_FGG484` |
| Modules / SiP | 0,3 | `[<Vendor>_]<Series>_<PKG>-<pads>_<X>x<Y>mm[_Layout…]_P<p>mm` · fallback `[<Vendor>_]<Product>-<n>Pin_P<p>mm` | none | `-<pads>` / `-<n>Pin` | `Telit_xE310_LGA-94_15x18mm_P0.6mm` |
| Generic grid connectors | 0,1 | `{PinHeader\|PinSocket\|IDC-Header}_<r>x<pp>[-<n>MP]_P<p>mm[_<Orient>][_SMD][_Pin1…]` | trailing | `<r>x<pp>` padded | `PinHeader_2x05_P1.27mm_Vertical_SMD` |
| Vendor grid connectors / FFC | 0,3 | `<Vendor>[_<Series>]_<MPN>_<r>x<pp>[-<n>MP][-<n>SH]_P<p>mm[_<Orient>][_<Opt>]` | none | `<r>x<pp>` padded | `Jushuo_AFC01-S22FCC-00_1x22-1MP_P0.50mm_Horizontal` |
| Terminal blocks | 0,3 | `TerminalBlock_<Vendor>[_<MPN>]_<r>x<pp>_P<p>mm[_<Orient>]` | none | `<r>x<pp>` padded | `TerminalBlock_Xinlaiya_XY302V-3.5-2P_1x02_P3.50mm_Vertical` |
| Standardised interfaces (USB/RJ/SMA/BNC/U.FL/microSD/nanoSIM/DSUB) | 0,3 | `<Standard>_<Type>[_Receptacle\|_Plug]_<Vendor>_<MPN>[_<Orient>][_<Opt>]` — **no positions, no pitch** | none | none | `USB_C_Receptacle_XKB_U262-161N-4BVC11` · `U.FL_Kinghelm_KH-IPEX-K501-29_Vertical` |
| Crystals / oscillators | 0,3 | `{Crystal\|Oscillator}_SMD_[<Vendor>_<Series>-]<Case>-<n>Pin_<X>x<Y>mm[_HandSolder]` | **family-glued** | `-<n>Pin` | `Crystal_SMD_3225-4Pin_3.2x2.5mm` |
| Antennas | 0,3 | `Antenna_{SMD\|THT}_<Vendor>_<MPN>[_<band>]` | **family-glued** | none | `Antenna_SMD_Rainsun_GPS1003` |
| Relays | 0,3 | `Relay_<Config>_<Vendor>_<Series>[_<Opt>]` | none | none | `Relay_SPDT_Omron_G2RL-1` |
| Switches / buttons | 3 | `SW_<Actuation>_<Config>[_NC]_<Vendor>_<MPN>_<X>x<Y>mm[_H<h>mm][_<Orient>][_<Mount>]` | trailing | none | `SW_Push_SPST_Shouhan_TS24CA_4.7x3.5mm_H2.25mm_SMD` |
| Fuse holders | 3 | `Fuseholder_<FuseType>_<Vendor>_<MPN>_P<p>mm[_<Orient>][_Open\|_Closed]` | none | none | `Fuseholder_Cylinder-5x20mm_XFCN_PTF-77_P22.6mm_Horizontal` |
| Battery holders | 0,3 | `BatteryHolder_<Vendor>_<MPN>_1x<Cell>` | none | `1x<Cell>` | `BatteryHolder_Keystone_2466_1xAAA` |
| Microphones / discrete sensors | 3 | `Microphone_<Vendor>_<MPN>_<X>x<Y>mm[_P<p>mm]` | none | none | `Microphone_ST_MP34DT05-A_3x4mm_P0.85mm` |
| Mounting holes / tooling | 0,1 | `MountingHole_<drill>mm[_M<thread>][_<HeadStd>][_Pad<d>mm][_TopOnly\|_TopBottom\|_Via]` | none | none | `MountingHole_3.2mm_M3_Pad6mm` |
| Test points | 0,1,3 | `TestPoint_<Style>_(<x>x<y>mm\|D<d>mm)[_Drill<d>mm][_<Opt>]` · `TestPoint_<Vendor>_<MPN>[_SMD]` | trailing | none | `TestPoint_Pad_D1.5mm` · `TestPoint_Ronghe_RH-5015_SMD` |
| Lightpipes / heatsinks / standoffs / nuts | 3 | `{Lightpipe\|Heatsink\|Mounting}_[<Vendor>_]<MPN>[_<dims>]` | none | none | `Lightpipe_FIX-LEMB2-4.8V0-F` · `Mounting_Sinhoo_SMTSO2515CTJ` |
| Enclosures | 3 | `Enclosure_<Vendor>_<MPN>` | none | none | `Enclosure_Hammond_1551RFLGY` |
| Mechanical outlines (no lands) | 4 | `[<Vendor>_]<Product>_Mechanical_<X>x<Y>mm[_<n>x<Feature><val>mm]` | none | none | `RaspberryPi_CM5_Mechanical_40x55mm_4xMountingHole2.7mm` |
| Logos / board markers | 0,4 | `<Name>-Logo_<size>mm_{SilkScreen\|Copper}` | none | none | `7Sigma-Logo_3mm_SilkScreen` |

---

## 5. The four families called out

### 5.1 Aluminium electrolytic + tantalum — the overhaul

The problem is not the names; it is that **`x` means two different things and nothing in the name says which**, and that the `display_name` field is currently speaking tantalum vocabulary at aluminium parts.

**The unit-suffix invariant — the single rule to remember:**

> **No `mm` suffix ⇒ the pair is can Diameter × Height. `mm` suffix present ⇒ the pair is body Length × Width.**

`CP_Elec_10x10.5` is a 10 mm can, 10.5 mm tall. `QFN-16-1EP_4x4mm` is a 4 × 4 mm body. That asymmetry is inherited from stock (47 `CP_Elec_*` files, none carrying a unit) and is now *load-bearing* rather than sloppy — so it must not be "tidied".

This matters because the height token **selects different copper**: stock `CP_Elec_10x10` has 4.0 × 2.5 mm pads at ±4.0 mm, while `CP_Elec_10x10.5` has 4.4 × 2.5 mm at ±4.2 mm. A "harmless" height rounding silently picks the wrong land.

**Rules:**

| Sub-form | Grammar | Notes |
|---|---|---|
| SMD tantalum | `CP_EIA-<LLWW>-<HH>_<Vendor>-<Letter>[_Pad<w>x<h>mm][_HandSolder]` | `<LLWW>` = body L,W in 0.1 mm, each 2 digits, no separator (`7343` = 7.3 × 4.3 mm). `<HH>` = height in 0.1 mm (2 digits); a 3-digit form means 0.01 mm and is used **only where stock already does** (`7361-438` = 4.38 mm) — never invented. **`_<Vendor>-<Letter>` is mandatory**: one EIA size maps to several heights and vendors letter them differently (`AVX-U` appears on both 7132-20 and 7361-438). **Never `CP_Tantalum_`** — KLC's page prints it, but 56 of 56 shipped files use `CP_EIA-` and a corpus search for `CP_Tantalum_` returns 0. Follow the files, not the page. |
| SMD alu electrolytic | `CP_Elec_<D>x<H>[_<Vendor>]` polarised · `C_Elec_<D>x<H>` non-polarised | Plain decimals, **no unit**, no trailing zeros (`10`, not `10.0`). `_<Vendor>` only to separate a second land for the same can size (stock: `CP_Elec_6.3x5.4_Nichicon`). |
| THT electrolytic | `CP_Radial_D<d>mm_P<p>mm[_P<p2>mm]` · `CP_Axial_L<l>mm_D<d>mm_P<p>mm_Horizontal` | Here the unit **is** written on every value, and pitch carries 2 decimals per E2. Dual-pitch parts list both `P` tokens ascending. |

**`display_name` is where the overhaul lands** (all three current members keep their Tier 0 names; only the display field changes):

| Footprint | display_name now | → | Why |
|---|---|---|---|
| `CP_EIA-7343-31_Kemet-D` | `CASE-D-7343` | `EIA-7343-31 Kemet-D` | Current form reverses the token order and **drops the height**, so it cannot distinguish this from 7343-20 Kemet-V or 7343-43 Kemet-X |
| `CP_Elec_10x10` | `D10` | `D10xH10mm` | `D10` alone collides with 10x7.7 / 10x10.5 / 10x12.5 / 10x14.3 — all genuinely different lands |
| `CP_Elec_6.3x7.7` | `CASE-D-6377` | `D6.3xH7.7mm` | Wrong on three counts: `CASE-D` is tantalum vocabulary on an aluminium part; `6377` reads as an EIA metric **body** code; and it makes the part look like a sibling of the Kemet-D tantalum |

**Hard rule: `CASE-<letter>` vocabulary is tantalum-only and may never appear on an aluminium electrolytic.**

Two geometry follow-ups (not naming) are in §9 Q8: both `CP_Elec_10x10` components are Panasonic 10 × 10.2 mm cans on the Nichicon 10.0 land, and `CP_Elec_6.3x7.7` carries a Rubycon part whose own case designation reads `6.3X8`.

### 5.2 Connectors

Three entry forms, chosen by one test:

1. **Standardised interface** (USB, RJ, SMA/BNC/MMCX/U.FL, microSD, SIM, DSUB, HDMI) — the standard fixes the pinout, so **no positions and no pitch**: `<Standard>_<Type>[_Receptacle|_Plug]_<Vendor>_<MPN>[_<Orient>][_<Opt>]`.
2. **Vendor grid connector** (board-to-board, FFC/FPC, vendor headers, pluggable terminal blocks) — layout **and** pitch mandatory.
3. **Generic grid connector** — no vendor token at all; pitch + positions fully specify it.

Key rules and the defects they fix:

- **Positions count electrical positions per row, zero-padded to 2.** `PhoenixContact_DMCV_..._1x12_...` had **24 pads in two rows** — the highest-confidence defect in the library. Its stock single-level sibling `MCV_1,5_12-GF-3.5_1x12` has exactly 12 pads, which *proves* the token counts contacts. → `PhoenixContact_DMCV_1,5_12-G1F-3.5_2x12_P3.50mm_Vertical_ThreadedFlange` (the flange code is also corrected: the MPN is `-G1F`, not the `GF` copied from the MCV template).
- **Non-electrical pads append to the position field:** `-1MP` (hold-down / board lock) or `-1SH` (shield). **One group per type regardless of physical count** — stock has no `-2MP` anywhere. Shield posts that are part of the interface standard (USB-B shell) get **no** token.
- **Mounting technology is not a field** (§3.9). This is the biggest deliberate deviation and it is what restores sort order: `CONN-TH_`, `FPC-SMD_`, `RJ45-TH_`, `SMA-SMD_`, `USB-3.1-SMD_` all scatter the family across the alphabet.
- **The MPN is the uniqueness tiebreaker.** Two lands for the same nominal part differ by MPN, never by a formatting variant. Three Bat Wireless SMA connectors are distinguished by MPN alone, and the vendor token is frozen to `BAT_Wireless` because one of the three is a verbatim stock name.
- **Colour/clamp order-code suffixes are dropped** when they do not change the land (`DB301V-3.5-2P-GN-S` → `DB301V-3.5-2P`), matching stock `TerminalBlock_Degson_DG250-3.5-02P`.
- `_Invisible` is the sanctioned house option for a zero-land placeholder that must appear in the BOM (`TerminalBlock_Plug_Invisible`, 16 references).

> `USB-3.1-SMD_U262-161N-4BVC11` → `USB_C_Receptacle_XKB_U262-161N-4BVC11` — the "3.1" was **false** (16-pin, no SuperSpeed pairs; even its own 3D model says `16P`)
> `IDC-SMD_10P-P1.27-3220-10-0300-00` → `Hanxia_JN1.27-2x5-TP-H4.9_2x05_P1.27mm_Vertical_SMD` — not IDC, and the embedded MPN belonged to a **different manufacturer**

### 5.3 Modules and grid arrays

Modules are the family with the least geometric determinism, so the rule is explicit about **what not to invent**:

- **Package designation only if it is documented.** Never inferred from how the pads look. If no designation is recorded in the datasheet, the component, or the file's `descr`, use `[<Vendor>_]<Product>-<n>Pin_P<p>mm` — the stock `-<n>Pin` form — rather than guessing LGA vs LCC. `XCVR_LC76G` → `Quectel_LC76G-28Pin_P1.1mm`, *not* an invented `LGA-28`.
- **Series token = MPN with region/variant suffixes stripped**, because the land is shared: `EG915UEUAC-N05-SNNSA` → `EG915U`; `LE910R1-EU` → `LE910R1`; `xE310` where the vendor's own family designation is documented. The old `_EG915U-EC` was actively wrong — the part fitted is an `-EU`.
- **`Layout` only for one uniform grid** (depopulation allowed); **`LayoutBorder<a>x<b>y` only for a perimeter ring**; **omit both for staggered, multi-region or irregular maps** — the *absence* of a Layout token is itself the signal that the map is vendor-specific, and Vendor+Series then carry the identity. Stock does exactly this (`Nordic_nRF9160-SIxx_LGA-102-59EP_16.0x10.5mm_P0.5mm`). Do not invent a token for irregular arrays.
- **Pitch for an irregular array** = the manufacturer's stated land-pattern pitch; absent a drawing, the finest spacing that repeats over ≥3 equally spaced adjacent lands in one row or column. Omit only when no two lands share a row or column.
- **Body size omitted rather than guessed** when F.Fab was drawn at courtyard size and the silk runs between pad columns (this is why `Quectel_LC76G-28Pin_P1.1mm` carries no body).

> `LGA-SMD_L23.6-W19.9-P1.10_EG915U-EC` → `Quectel_EG915U_LGA-126_19.9x23.6mm_P1.1mm` — `LGA-SMD` spent the pad-count slot on a mounting technology that "LGA" already implies, hiding **126 lands**
> `XCVR_LE910R1-EU` → `Telit_LE910R1_LGA-181_28.2x28.2mm_Layout15x15_P1.8mm` — `XCVR` is a schematic role, not a package

### 5.4 Mechanical and non-electrical

Function word first, then one of two branches. The function token is the only string a browsing engineer knows before they search, and it clusters the family in a flat namespace.

- **Geometric branch** (mounting holes, test-point pads): reuse the stock name byte-for-byte when the geometry is stock's; the moment a copper dimension deviates, **that value must appear as an explicit token**. This is the family's one correctness fix: `_Pad` in stock grammar is a standalone flag meaning "has copper", and the next field is the copper-side option (`_Via`/`_TopOnly`/`_TopBottom`). So `MountingHole_2.5mm_Pad_4mm` parses as stock's `MountingHole_2.5mm_Pad` (which has a **5 mm** pad) plus an unparseable option "4mm", while our copper is 4 mm.
  > `MountingHole_2.5mm_Pad_4mm` → `MountingHole_2.5mm_Pad4mm`
  > `MountingHole_3.2mm_M3_Pad_6mm` → `MountingHole_3.2mm_M3_Pad6mm` (stock's is 6.4 mm — close enough to be mistaken for stock, far enough to matter for screw-head clearance)
- **Vendor branch** (enclosures, lightpipes, vendor test points, standoffs, SMT nuts): `<Function>_<Vendor>_<MPN verbatim>[_<dims>][_SMD|_THT]`. Omit the vendor token when the MPN already starts with the brand (`Lightpipe_FIX-LEMB2-4.8V0-F` — and here the canonical manufacturer "FIX&fasten" contains an illegal `&`).
- **`Mechanical` is a mandatory warning token** for any footprint with zero electrical lands. `Raspberry-Pi-5-Compute-Module` contains only four Ø2.7 mm NPTH holes and reads today like a full CM5 land pattern — the most dangerous name in the library.
  > → `RaspberryPi_CM5_Mechanical_40x55mm_4xMountingHole2.7mm`
- **`SMD_` is never a family token.** `SMD_RH-5015` is a Ronghe test-point loop sitting in TestPoints, invisible to anyone searching "TestPoint" → `TestPoint_Ronghe_RH-5015_SMD`. `SMD_BD5.6-D4.1` / `SMD_BD5.6-L5.6-W5.6-D3.6` are two sizes of one Sinhoo SMT nut product line described with two different token sets, where the `D` value is the *part's* hole, not the footprint's NPTH → `Mounting_Sinhoo_SMTSO2515CTJ` / `Mounting_Sinhoo_SMTSO2010CTJ`.
- **Logos keep stock's name-first form** so a stock CE/RoHS/UKCA logo drops in unrenamed: `7Sigma_Logo` → `7Sigma-Logo_3mm_SilkScreen`.

---

## 6. `display_name` — the second namespace

`display_name` is **not** the footprint name. It is the short package string a human reads in `ki_description`, and it is the one field allowed to carry the SMD/THT cue that §3.9 removes from the name.

**Grammar: `<PackageOrStyle>[ <distinguishing dimensions>]`** — metric only, never mil, no vendor, no family prefix redundancy, same axis order as the footprint name.

| Family | Form | Examples |
|---|---|---|
| Chip passives | bare imperial code | `0402`, `1206`, `2920` |
| Tantalum | `EIA-<LLWW>-<HH> <Vendor>-<Letter>` | `EIA-7343-31 Kemet-D` |
| Alu electrolytic | `D<d>xH<h>mm` | `D10xH10mm` |
| IC packages | `<FAM>-<pins>` + disambiguator only when two variants coexist | `SOIC-8`, `SOIC-8 EP`, `SOIC-8 5.3x5.3mm`, `DFN-8 3x2mm` |
| Grid arrays / modules | `<PKG>-<pads> <X>x<Y>mm` | `LGA-126 19.9x23.6mm`, `BGA-484 23x23mm` |
| Connectors | `<Interface>-<pos>P[ <pitch>mm]` or the industry short form | `USB-C 16P`, `RJ45 8P8C`, `FPC-24P 0.5mm`, `TB-2P 3.5mm`, `2x05 1.27mm` |
| Switches | `<SMD\|THT>-<n>P <L>x<W>x<H>mm[ Right-Angle]` | `SMD-4P 6x6x4.3mm`, `THT-4P 6x6mm Right-Angle` |
| Mechanical | function + defining size | `TestPoint 1.5x1.5mm`, `MountingHole 3.2mm M3, pad 6mm`, `Mechanical 40x55mm` |

**Two display names may never be identical** where the footprints differ — today `SOIC-8-1EP_..._ThermalVias` and `SOIC-8_3.9x4.9mm_P1.27mm` both display `SOIC-8`, so `{Footprint_Name}` cannot tell them apart.

---

## 7. Cross-family contradictions, and how they are resolved

This is where the nine drafts disagreed with each other. Each row is a decision, not a compromise.

| Conflict | Drafts said | **Resolution** |
|---|---|---|
| Pitch decimals | connectors: always 2dp · ICs/misc/modules: minimal digits | **Minimal digits globally**, with E1 (Tier 0) and E2 (stock-sibling padding). E2 happens to give 2dp for every connector family, so both drafts' outcomes survive under one rule |
| `HandSolder` vs `HandSoldering` | chip/tantalum: HandSolder · discrete: stock wins byte-for-byte | **House-minted = `HandSolder`; Tier 0 keeps stock's spelling; all matching case-insensitive** |
| Mount token | connectors: never a field · switches: mandatory · chip: never · misc: only where stock does | **Disambiguator only, per §3.9, with the position fixed per family in §4** (three family-glued exceptions, everything else trailing) |
| Vendor vs geometry order | switches put geometry first; every other family vendor first | **Vendor and MPN always precede geometry.** Regenerates all 8 switch rows |
| Family-first vs vendor-first | misc prepends `Antenna_`/`Microphone_` · modules keeps stock vendor-first | **Tier 0 immunity wins.** `Osram_BPW34S-SMD` and `Texas_SWRA117D_2.4GHz_Left` stay vendor-first; house-authored antennas become `Antenna_*`. The Antenna family will not fully sort together — accepted price of stock identity |
| `FuseHolder` vs `Fuseholder` | misc: `FuseHolder_` (KLC text + G1.6) | **`Fuseholder_`** — §3.3, verified 45 files vs 1. Family tokens follow the shipping majority even against G1.6 |
| `ShouHan` vs `Shouhan` | switches/misc: `ShouHan` (house canonical) | **`Shouhan`** — stock ships it unambiguously (§3.4 step 1) |
| `Jushuo` vs `JUSHUO` | connectors: Title-case | **`Jushuo`** — stock is ambiguous (2 vs 26), so house canonical wins (§3.4 step 2) |
| Bare `<n>P` counts | switches: keep `-4P` · connectors/misc: banned | **Banned.** Tier 3 uses `-<n>Pin` glued to a *series/product* token only; pad-count cross-checking lives in the platform's pad-count field, not the name |
| `-<n>EP` when the tab shares a pin number | ICs: omit · elsewhere unspecified | **Omit** — `Infineon_PG-TDSON-8_6.15x5.15mm` |
| Body axis order | ICs/modules: X-then-Y as drawn · EasyEDA legacy: long side first | **X-then-Y as drawn, from F.Fab** (§3.6) |
| Stock names that violate house rules | discrete/modules: keep · chip/ICs: anti-shadow | **Both: Tier 0 is immune, and anti-shadowing forbids minting a stock name over different copper.** No contradiction once tiers are explicit |

**≈12 rename rows must be regenerated** after these overrides: 8 switches (field order + dropped count), 1 fuse holder (`Fuseholder_`), 2 Shouhan vendor tokens, 1 Hirose pitch (`P0.40mm` → `P0.4mm`).

---

## 8. Migration plan — six waves, 173 footprints

Every write goes through a draft proposal; approval regenerates the KiCad libraries and file mirror automatically. **Renaming a footprint does not update already-laid-out `.kicad_pcb` files** — they keep the old string and need *Update Footprints from Library*. Waves are ordered so that the highest-traffic footprints are never renamed: `R_0402_1005Metric` (35 refs), `C_0402_1005Metric` (19), `TerminalBlock_Plug_Invisible` (16), `SOT-23-3` (11) are all Tier 0 keeps.

| Wave | Content | Footprints | Risk | Value |
|---|---|---|---|---|
| **0** | Publish this standard into `kicad-conventions-footprints`; add the manufacturer→footprint-token table to `kicad-conventions-library`; mark the **91 conformant names frozen**; add the §10 validator rules | 0 renamed (91 frozen) | none | unblocks everything; stops new drift |
| **1** | **`display_name` pass.** Fill ~113 empty fields; correct ~10 factually wrong ones (`CASE-D-6377`, `0806` on a PCB trace antenna, `MWU`, `4020`, `SOIC-8 208mil`, `VQFN-20-EP 3.7x4.7mm` transposed, the duplicate `SOIC-8`, `SMD,12.6x13.5mm`, `LGA XCVR_LE910R1-EU`, `VDFN-13`) | 173 records touched, **0 names changed** | none — separate field, no board impact | highest value/risk ratio in the plan: every unresolved `{Footprint_Name}` template resolves |
| **2** | **Deletions + the one blocker.** Delete 5 zero-reference footprints: `SOT-23-5_L3.0-W1.7-P0.95-LS2.8-BL` (rect pads, no courtyard), `SOT-563_L1.6-W1.2-P0.50-LS1.6-BL`, `CONN-TH_DB2ERM-3.81-6P-GN` (still carries the forbidden `easyeda2kicad:` prefix, pre-2022 format, no courtyard), `OSC-SMD_4P-L3.2-W2.5-BL` (0.03 mm duplicate of the stock crystal land), `LED-SMD_4P-L3.2-W2.7-TL` (unidentifiable). **Resolve the Hirose DF40C-100DS pin numbering** (§9 Q1) | **5 deleted, 1 investigated** | none (`used_by = 0`) | removes the 5 worst-quality files and the only naming blocker |
| **3** | **Correctness renames** — every name that states something false: wrong pitch, wrong EP dimensions, wrong pin/position count, undeclared thermal vias, false mounting technology, false `-EP`, wildcard MPN, stock-name shadowing | **30 renamed** | low — all ≤3 references each | these are the renames that prevent a wrong board |
| **4** | **Grammar migration**, batched per family so each is one reviewable proposal: **4a** connectors (11) · **4b** mechanical + modules (15) · **4c** misc sensors/timing/power (12) · **4d** switches (6) · **4e** IC remainder (2) | **46 renamed** | low | one namespace, one sort order, EasyEDA residue gone |
| **5** | **Geometry follow-ups — not naming.** ≈20 items: `easyeda2kicad.3dshapes` → `<category>.3dshapes` model paths; missing courtyards; drill float noise (`1.5000224`, `1.100023`, `0.999998`); plated holes that should be `np_thru_hole`; the four Hammond outlines each on a different layer and TAKACHI with none; EP-polygon questions on SON-12/VSON-14; stock-geometry adoption decisions from §9 | 0 renamed | medium | closes the gap between what names now promise and what the copper does |

**Totals: 91 keep · 76 rename (30 correctness + 46 grammar) · 5 delete · 1 investigate = 173.**

---

## 9. Open questions — decide these; recommendations included

**Q1. Hirose DF40C-100DS pin numbering — the only hard blocker.** Our import numbers pads 1–50 along the top row then 51–100 along the bottom, rows at y = ±1.6 mm. Stock `Hirose_DF40C-100DS-0.4V_2x50_P0.4mm` interleaves (pad 1 top, pad 2 directly below) with rows at ±1.54 mm. One contradicts the Hirose drawing.
**Recommendation:** read the drawing before Wave 3. If stock is right, repoint the component at the stock footprint and delete the import — no rename needed. If ours is right, `Hirose_DF40C-100DS-0.4V-51_2x50_P0.4mm`.

**Q2. Bless the manufacturer→footprint-token table into `kicad-conventions-library`.** The canonical values `STMicroelectronics`, `Telit Cinterion`, `AMD/Xilinx`, `Raspberry Pi`, `MEAN WELL`, `Shou Han`, `Hammond Manufacturing`, `FIX&fasten` contain spaces or characters KLC G1.1 forbids.
**Recommendation:** yes — add a *footprint-token* column, seeded per §3.4 (`ST`, `Telit`, `Xilinx`, `RaspberryPi`, `MeanWell`, `Shouhan`, `Hammond`, `TAKACHI`, `Jushuo`, `Ckmtw`, `G-Switch`, `Kinghelm`). Recording it is what stops the next import inventing a sixth spelling of Würth.

**Q3. Are `Antenna_`, `Microphone_`, `Enclosure_` acceptable house family tokens?** KiCad ships none of the three (it files antennas and mics vendor-first, and has no enclosure class at all).
**Recommendation:** adopt all three. The 7Sigma namespace is flat with no `.pretty` to carry the family, and each token makes the house name a strict superset of the stock shape, so nothing is lost.

**Q4. Do Tier 0 names stay exempt from mandatory `_ThermalVias`?** `ESP32-WROOM-32U` ships a 3.8 × 3.8 mm thermal land with 12 plated vias and no token.
**Recommendation:** yes, exempt, and note the deviation in the description. Byte-identity with upstream is worth more than token purity, and the alternative is a house-authored name for an otherwise-perfect stock footprint.

**Q5. Switch terminal count in the name?** No stock switch footprint (all 270) carries one; the drafts wanted `-4P`.
**Recommendation:** drop it, per §3.10/§7. Vendor+MPN already makes the name unique, the picker shows pad count next to every name, and gluing a count to a hyphen-bearing MPN is unparseable. *Separate finding worth a ticket:* `TS24CA` and `GT-TC025D-H0065-L1` use base symbol `SW_Push` while their footprints have 4 numbered pads — if `SW_Push` is 2-pin, pads 3–4 get no net.

**Q6. Two 16-pin USB-C receptacles, one land.** `XKB U262-161N-4BVC11` and `G-Switch GT-USB-7010ASV` have the same 22-pad set, the same numbering, and reference the same STEP file; the copper differs by 0.05–0.2 mm.
**Recommendation:** keep both — two purchasable SKUs, both named properly. Consolidation changes a component's copper and belongs in Wave 5.

**Q7. `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm_ThermalVias` vs `WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm_ThermalVias`** — 0.01–0.02 mm apart, i.e. one land, two names, three components.
**Recommendation:** keep both. QFN and WQFN are distinct JEDEC body-height classes and each name is datasheet-correct for its part; merging forces one component to carry the wrong package name.

**Q8. Electrolytic land vs the parts fitted.** Both components on `CP_Elec_10x10` (the Nichicon 10.0 land, pads at ±4.0) are Panasonic 10 × 10.2 mm cans; stock also ships `C_Elec_10x10.2` (pads at ±4.4). `CP_Elec_6.3x7.7` carries a Rubycon part whose case designation reads `6.3X8`.
**Recommendation:** repoint both at height-correct stock lands in Wave 5 after checking the Panasonic FK/ZK and Rubycon TZV drawings. The current *names* correctly describe the current copper — this is a selection defect, not a naming one.

**Q9. Stock-geometry adoption for three near-stock footprints.** `Relay_DPDT_Omron_G6K-2F-Y` (our copper is stock's rotated 90°, 2.1 × 1.0 mm pads vs 1.8 × 0.8), `BatteryHolder_Keystone_2466_1xAAA` (identical 44.7 mm span, drill 1.2/pad 1.6 vs stock 1.02/2.0), and the rotated `USON-8`/`WSON-8` Winbond pair.
**Recommendation:** adopt stock geometry and the exact stock names in Wave 5. That is four fewer house footprints and four names that match every other engineer's library. Until then the proposed house names avoid shadowing, so nothing is unsafe.

**Q10. Vendor drawing codes in names?** I keep vendor *outline* names (`Diodes_V-DFN3020-13-A`, `Infineon_PG-TDSON-8`) and drop vendor *drawing* codes (TI `DSJ`, `RGY`); stock does both.
**Recommendation:** as proposed — an outline name identifies the land, a drawing code identifies TI's PDF. Drawing codes go in the description, where they are still searchable.

**Q11. Body-size tie-breaker: datasheet nominal or F.Fab as drawn?** `VQFN-20` says 4.6 × 3.6 mm in its name and 3D model, but F.Fab draws 4.66 × 3.66 mm.
**Recommendation:** **datasheet nominal wins for the name; F.Fab is the cross-check.** If they disagree by more than 0.1 mm, fix the geometry rather than the name. This sets §3.6's tie-breaker library-wide.

**Q12. Store the IPC-7351 string as a searchable alias field?** e.g. `CAPMP7343X310N` for the Kemet-D tantalum, `RESC1608X55N` for the 0603 resistor.
**Recommendation:** yes — add an `ipc_name` metadata field. It buys SnapEDA / Ultra Librarian / JLCPCB / Altium cross-lookup for free while paying none of the browsing cost of IPC-style primary names. Note the constructed strings need verification before they are stored.

**Q13. Lightpipe drill warning token.** House lightpipes deliberately omit the NPTH that every stock lightpipe includes (clearance is documented on Dwgs.User/Cmts.User instead).
**Recommendation:** add it — `Lightpipe_FIX-LEMB2-4.8V0-F_Drill1.98mm`. It is KLC-legal (`TestPoint_Loop_D2.50mm_Drill1.0mm`) and it is the single most decision-relevant number for a stock-trained engineer who will otherwise assume the hole is in the footprint.

---

## 10. Enforcement — validator rules to add in Wave 0

Eight mechanically checkable rules, so the standard holds without review discipline:

1. `^[A-Za-z0-9_.,+-]+$`; reject any space. Reject `,` and `+` outside a token flagged as a verbatim vendor designation.
2. Reject the §3.11 banned-token list on any non-Tier-0 name.
3. Reject `HandSoldering` / `Handsoldering` on any house-authored name.
4. Reject a trailing-zero decimal (`P0.50mm`, `3.0x`) unless the footprint is Tier 0 or declares an E2 stock sibling.
5. **Anti-shadowing:** if the name matches a stock filename, diff the pad table against stock and fail on any mismatch.
6. If any pad shares the exposed pad's number and is a plated `thru_hole`, require `_ThermalVias`.
7. If pad count > numbered-signal-pin count, require the surplus to be explained by `-<n>EP`, `-<n>MP`, `-<n>SH`, paste-only apertures, or `np_thru_hole`.
8. Reject a literal `X`/`xx`/`XX` wildcard inside an MPN token on any house-authored name.