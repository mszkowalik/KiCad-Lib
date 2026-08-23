---
name: kicad-conventions-library
description: "House style for component data: canonical manufacturer names (with the full raw-to-canonical lookup table), ki_description {Key} templating per category, the Value field rule, and category-placement rules. Read before proposing a new component or editing an existing one's properties."
---

<!-- platform-skill: conventions-library v22 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Library conventions

This is the house style for component **data**: manufacturer naming,
description (`ki_description`) standardization, the `Value` field rule, and
category placement. Read it before proposing any new component or editing an
existing one's properties.

Scope: this document covers property values. Geometry conventions live in
[[conventions-symbols]] and [[conventions-footprints]]; the step-by-step
procedure and the validation rules a draft must satisfy are in
[[add-component]]; what happens after approval is [[platform-workflow]]. A full standardization pass across **every**
category was completed 2026-07-21 (308 components checked, 198 edit proposals
drafted) — see the closing note at the end of this document.

## 1. Manufacturer names (`Manufacturer 1`)

Raw data from LCSC/JLC feeds is unreliable for casing: it is frequently
ALL-CAPS (distributor-shout), inconsistently cased, or a bare/cryptic code.
Never copy it verbatim into `Manufacturer 1` — resolve it to the canonical
form below.

### Canonical form rule
Use the manufacturer's own official brand capitalization — normal Title Case
for most legal/brand names, **except** where the company's own stylization is
genuinely different. Do not "fix" a company's real stylization into Title Case.

Known deliberate exceptions to normal Title Case (verified against the
company's own branding — keep EXACTLY as shown):

**Lowercase brand exceptions:**
- `u-blox` — lowercase u, hyphen, lowercase blox, even at sentence start;
  confirmed via the company's own site/Wikipedia. Do not write "Ublox" or
  "U-Blox".
- `onsemi` — ON Semiconductor officially rebranded to this lowercase trade
  name in 2021 (investor.onsemi.com, press coverage). Same exception class as
  u-blox. Do not write "Onsemi" or "ON Semiconductor".
- `8devices` — UAB "8devices" (Lithuania); lowercase "d", confirmed via the
  company's own site footer copyright line ("© 2012-2026 UAB \"8devices\"")
  and its logo/header casing throughout 8devices.com. Do not write "8Devices"
  or "8 Devices".

**All-caps brand exceptions** (genuine manufacturer stylization, not
distributor shout-casing):
- `KEMET`
- `OSRAM`
- `KNSCHA`
- `TDK` — Tokyo Denki Kagaku; all-caps is TDK Corporation's own brand/logo
  usage, not a spelled-out Title Case name. Distinct from `TDK InvenSense`
  below (a joint-venture brand).
- `TDSEMIC` — all-caps on the company's own datasheet letterhead logo and in
  the footer URL printed on every page of it (tdsemic.net). Same evidence
  class as the KEMET/OSRAM entries: the manufacturer's own material, not a
  distributor listing. No fuller company name was found on any primary
  source, so none is recorded here — do not expand the acronym on a guess.
- `XR` — Dongguan Xiangru Electronics Co., Ltd.; branded and listed everywhere
  simply as "XR", including its own LCSC brand page (titled literally "XR").
- `YLPTEC` — Zhongshan Yichuan Electronic Technology (中山市易川电子科技);
  all-caps on the company's own datasheet letterhead logo, in the
  WWW.YLPTEC.COM footer printed on every datasheet page, and silkscreened on
  the module body in its own outline drawings. Same evidence class as the
  KEMET/OSRAM entries: the manufacturer's own material, not a distributor
  listing. Do not Title-Case to "Ylptec".
- `YXC` — Shenzhen Yangxing Technology Co., Ltd.'s self-owned brand.
- `XINGLIGHT` — confirmed via the manufacturer's own site (xinglight.cn) and
  DigiKey's supplier page.
- `TAKACHI` — confirmed via the manufacturer's own site
  (takachi-enclosure.com), including its copyright line.
- `OMRON` — confirmed via Omron's own domains (ia.omron.com, omron.com) and a
  2024 press release citing "OMRON" as a registered trademark. Do not use
  "Omron Electronics" (a distributor/subsidiary name seen in the raw feed).
- `MEAN WELL` — confirmed via the company's own brand-story pages
  (meanwell.com, meanwellusa.com, meanwell.eu); two words, both all-caps.
- `DEGSON` — confirmed via degson.com's own running body copy and footer
  copyright text.
- `BHFUSE` — Shenzhen BHFUSE Industrial Co., Ltd.; stylizes its own legal name
  all-caps, confirmed via LCSC's own blog post.
- `XFCN` — XFCN Connectors Co., Ltd.; confirmed via the company's own LCSC
  brand-page About text ("hereinafter referred to as 'XFCN'"). Resolves the
  skill's former open item.
- `ISSI` — Integrated Silicon Solution, Inc.'s own all-caps acronym; confirmed
  via issi.com and its own datasheet cover pages.
- `HCTL` — Shenzhen Huacan Tianlu Electronics Co., Ltd.; consistent all-caps
  acronym across the company's own LCSC brand page and product listings.
- `RCH` — Wenzhou RuiChuan Electronics Co., Ltd.; consistent all-caps brand
  code. (Confirmed via distributor listings, not a formal press kit —
  slightly lower certainty than the others in this list.)
- `RESI` — C&B Electronics (Shenzhen) Co., Ltd.'s precision-resistor brand;
  the company's own English site en.resistor.today prints "Brand: RESI" in
  body text and titles its series pages "Precision RESI Resistor". LCSC also
  lists the brand as "RESI" and sometimes as "Resistor Today" in URLs — use
  `RESI`. Same evidence class as the KEMET/OSRAM entries: the manufacturer's
  own material.
- `SOFNG` — sofng.com's own copyright notice ("SOFNG All Rights Reserved").
  (Same lower-certainty caveat as RCH.)
- `SCTF` — sctfcrystal.com self-titles as "SCTF | Crystal Oscillator
  Manufacturer...". Resolves the skill's former open item.
- `TOGNJING` — consistent all-caps across LCSC and Chipmall with no fuller
  company name found anywhere. **Lower confidence** than the rest of this
  list — no manufacturer homepage was ever located; re-check if a better
  source turns up.

**Other special stylizations** (not plain Title Case, not all-caps, not
lowercase):
- `FIX&fasten` — bold "FIX" + stylized "&" + lowercase cursive "fasten", per
  the manufacturer's own FIX-LEMB datasheet letterhead. Do not "correct" to
  the distributor's shout-case form `FIX&FASTEN` seen on TME/X-ON/FindIC.
- `Worldsemi` — only the leading W is capitalized (not "WorldSemi", not
  "WORLDSEMI", not "World Semi"). Confirmed via world-semi.com and LCSC's own
  brand-page heading.
- `MaxLinear` — internal capital on the L (not "Maxlinear"). Confirmed via
  `lcsc_lookup` matching the company's own brand spelling.
- `G-Switch` — Title Case with a hyphen; confirmed consistent across LCSC,
  HQonline, SemiKey, X-ON for the GT-TC/GT-USB product lines.

**Parenthetical / expanded brand forms** (distributor-catalog form that names
the parent company in parentheses — use exactly as shown, including
spacing/punctuation):
- `MDD (Microdiode Semiconductor)` — LCSC's own brand page is titled exactly
  this way.
- `UNI-ROYAL(Uniroyal Elec)` — no space before the parenthesis; matches
  LCSC's brand page and the part's own datasheet filename.
- `WCH(Jiangsu Qin Heng)` — no space before the parenthesis; consistent
  across the whole CH340 family on LCSC.
- `UMW (Youtai Semiconductor Co., Ltd.)` — space before the parenthesis;
  confirmed via umw-ic.com and multiple distributors.
- `FH (Guangdong Fenghua Advanced Tech)` — space before the parenthesis;
  applied to the 0402CG101J500NT thick-film chip resistor family.

Everything else defaults to normal Title Case / proper legal-name casing
(e.g. `STMicroelectronics`, `Texas Instruments`, `Espressif Systems`,
`Analog Devices`, `Winbond`, `AMD/Xilinx`, `Hammond Manufacturing`,
`Samsung Electro-Mechanics`).

### Canonical manufacturer table
(Raw/messy forms seen in feeds -> canonical value to use. Sorted
alphabetically by canonical value.)

| Canonical value | Messy forms seen |
|---|---|
| 8devices | 8Devices, 8 DEVICES, 8-Devices (distributor/catalog re-casing; the module is sold through CODICO, whose own datasheet cover never states a manufacturer name — verified against 8devices.com directly) |
| AMD/Xilinx | Xilinx, AMD/XILINX, XILINX |
| Analog Devices | ANALOG DEVICES, ADI |
| Bat Wireless | BAT WIRELESS |
| BHFUSE | (none — all-caps genuine brand, see exceptions above) |
| Bourns | BOURNS |
| Ckmtw | (none; full form "Ckmtw(Shenzhen Cankemeng)" also seen) |
| DEGSON | Degson |
| Diodes Incorporated | Diodes Inc, DIODES — the LCSC/JLC feed shouts "DIODES"; "Diodes Inc" was an earlier house form, already normalized to the full legal name on AP63357QZV-7 and the Diodes transistors. The footprint vendor token is `DiodesIncorporated` |
| Dorabo | DORABO |
| ECS Inc. | ECS — note: ECS's own materials are internally inconsistent ("ECS Inc. International" in press releases, "ECS International" on an About page); "ECS Inc." was picked as house standard because it matches both the company's own site `<title>` and DigiKey's distributor listing |
| Espressif Systems | Espressif, ESPRESSIF, Espresiff (typo) |
| FH (Guangdong Fenghua Advanced Tech) | FH |
| FIX&fasten | FIX&FASTEN (distributor shout-case seen on TME/X-ON/FindIC) |
| G-Switch | (none) |
| Guangdong Hottech | GUANGDONG HOTTECH, Hottech |
| Hammond Manufacturing | missing entirely on some sibling components; also seen corrupted/garbled, e.g. "FIX&Hammond Mfg" |
| Hanxia | hanxia |
| Hirose | HRS, HRS (Hirose) — HRS is only Hirose's part-number abbreviation/trademark code, not a display brand form |
| HCTL | (none — all-caps genuine brand, see exceptions above) |
| Infineon Technologies | Infineon (LCSC's short feed form) — the company's own datasheet legal text uses "Infineon Technologies" in running prose and "Infineon Technologies AG" as the publisher; the AG is the legal-entity suffix and is dropped, as with other Co./Ltd. suffixes in this table |
| ISSI | (none — all-caps genuine brand, see exceptions above) |
| Jushuo | JUSHUO |
| Kangnex | KANGNEX |
| KEMET | (none — all-caps is the genuine brand form; do not Title-Case to "Kemet") |
| Kinghelm | kinghelm — ⚠ conflicts with "Shenzhen Kinghelm Elec" below, see Open items |
| Kongshen | kangshen (LCSC's own romanization of 康深; the company writes "Kongshen" itself) |
| Linekey | (none — Shanghai Linekey Technology Co., Ltd.; confirmed via the company's own English-language site, en.linekey.cn) |
| Lite-On | LITEON, LITE-ON |
| MaxLinear | (none — internal capital, see exceptions above) |
| MDD (Microdiode Semiconductor) | MDD, Microdiode, Microdiode Semiconductor |
| MEAN WELL | Mean Well |
| Murata | muRata, MURATA, Murata Electronics (a regional-subsidiary name mistakenly applied library-wide by a prior pass — always normalize back to plain "Murata") |
| OMRON | Omron Electronics, OMRON (raw feed value — previously misjudged as distributor-shout and wrongly Title-Cased when it was actually already correct) |
| onsemi | ON Semiconductor, ONSEMI, On Semiconductor |
| OptoSupply | OPTOSUPPLY, Optosupply (wrong casing applied by an earlier automated pass — re-fix if seen again) |
| OSRAM | (none — all-caps is the genuine brand form; do not Title-Case to "Osram") |
| Panasonic | PANASONIC |
| Phoenix Contact | PhoenixContact (no space, in footprint names only — component Manufacturer 1 should still read "Phoenix Contact") |
| RCH | (none — all-caps genuine brand, see exceptions above) |
| Renata | RENATA |
| RESI | (none — all-caps genuine brand, see exceptions above; "Resistor Today" appears in LCSC product URLs but is not the brand form) |
| Ronghe | ronghe |
| Samsung Electro-Mechanics | Samsung |
| Samwha Capacitor | SAMWHA |
| SCTF | (none — all-caps genuine brand; resolves former open item) |
| Semtech | SEMTECH |
| Shenzhen Kinghelm Elec | kinghelm, KINGHELM — ⚠ conflicts with "Kinghelm" above, see Open items |
| Shikues | (none seen; already correct as stored) |
| Shou Han | SHOU HAN |
| Silverlight | (none) |
| Sinhoo | (none) |
| Slkor | SLKOR, Slkor Microelectronics, Shenzhen Slkor Micro Semicon |
| STMicroelectronics | ST, STMICROELECTRONICS, STM |
| TAKACHI | Takachi |
| TDK | (none — all-caps genuine brand, see exceptions above; distinct from "TDK InvenSense" below) |
| TDK InvenSense | (none — joint TDK/InvenSense brand, distinct from plain "TDK" above) |
| TDSEMIC | (none — all-caps genuine brand, see exceptions above) |
| Telit Cinterion | (none — standard capitalization, two words, no hyphen; official name since the Feb 2023 rebrand) |
| Texas Instruments | TI, TEXAS INSTRUMENTS |
| TOGNJING | (none — all-caps, lower confidence, see exceptions above) |
| u-blox | ublox, U-BLOX, U-Blox |
| UMW (Youtai Semiconductor Co., Ltd.) | UMW — the UMW PCF8574 datasheet footer instead reads "UTD Semiconductor Co.,Limited", same umw-ic.com site. Raised 2026-08-20 and DECIDED: keep this form. Do not re-open on the strength of that footer. |
| UNI-ROYAL(Uniroyal Elec) | Uni-Royal, UNI-ROYAL, UNIROYAL |
| Vishay | VISHAY, Vishay Intertechnology |
| Vishay Semiconductors | (none — distinct business-unit brand from plain "Vishay", used for Vishay's optoelectronics/photodiode parts; don't collapse to plain "Vishay") |
| WCH(Jiangsu Qin Heng) | WCH |
| Winbond | WINBOND |
| Worldsemi | WORLDSEMI, WorldSemi, World Semi |
| XFCN | (none — all-caps genuine brand; resolves former open item) |
| XINGLIGHT | (none — all-caps genuine brand, see exceptions above) |
| Xinlaiya | XINLAIYA |
| XR | (none — all-caps genuine brand, see exceptions above) |
| Xunpu | XUNPU |
| Yageo | YAGEO |
| Yajingxin | TAE |
| YLPTEC | (none — all-caps genuine brand, see exceptions above) |
| YXC | YXC Crystal Oscillators — the "Crystal Oscillators" suffix is LCSC brand-page title padding, not part of the brand name (same pattern as Vishay Intertechnology -> Vishay) |

### Open items — could not confidently resolve, do not guess
- `TWGMC` (seen on SS34) — still unresolved after a second research attempt.
  Only a weak, unquotable claim links it to "Taiwan Dijia Electronics Co.,
  Ltd."; no authoritative primary source found. Ask the user or research
  further before normalizing components using this code.
- `TECH PUBLIC` (seen on PESD5V0S1BA) — consistently ALL-CAPS across
  LCSC/JLCPCB/HQonline, possibly = Taizhou Electronics Co., Ltd., but no
  official company homepage was found to confirm the brand's own
  stylization (unlike the KEMET/OSRAM-class exceptions, which are anchored
  to the company's own material). Left as-is since it matches every
  distributor form seen, but do not add it to the exceptions list above as a
  confirmed all-caps brand yet.
- **`Kinghelm` vs. `Shenzhen Kinghelm Elec` naming conflict** — two different
  sessions used two different canonical forms for the same company
  (Shenzhen Kinghelm Electronics Co., Ltd. / kinghelm.net): the abbreviated
  `Shenzhen Kinghelm Elec` is used consistently on 4 existing Buttons/RF
  components, while a later Connectors-chunk session normalized a different
  component to bare `Kinghelm`, citing the company's own site. Both forms are
  recorded in the table above for traceability. **Do not silently pick one
  and reconcile** — surface this to the user/maintainer to decide the single
  house form, then normalize every affected component to match in one pass.

### Procedure when you meet a new/unclear manufacturer name
1. Check this table first.
2. If not listed, check `lcsc_lookup` and/or a quick web search for the
   company's own stylization (their homepage, Wikipedia infobox, or press
   material) — do not just guess a "nicer-looking" casing.
3. Use that verified form in `Manufacturer 1`.
4. If it's a new company not yet in the table above, **add it** the next time
   you touch this skill (`propose_skill_update`), so future look-ups are
   instant instead of re-researched every time.
5. If several sibling components already use a manufacturer name inconsistently,
   standardize all of them to one form in the same edit pass (mirror whichever
   form is verified correct, don't just pick the majority).
6. If you discover the library already uses **two different canonical forms**
   for what looks like the same manufacturer, do not silently pick one — add
   both forms to Open items above and surface the conflict for a maintainer
   decision (see the Kinghelm example).

## 2. Descriptions (`ki_description`)

Never hand-type a free-text description copied from a supplier catalog blurb.
Use a `{Key}`-based template so descriptions stay consistent, are generated
from real filterable/searchable properties, and update automatically if a
property changes.

### Method for standardizing a category/sub-family
1. Pull every component currently in the category/sub-family
   (`search_components` by category, then `get_component` on each).
2. Identify the handful of properties that actually distinguish parts in that
   family (electrical + package), verifying real values against the
   datasheet where the existing description looks copy-pasted or suspect
   (e.g. confirm fixed vs. adjustable output before templating "Output
   Voltage").
3. Define one template string using only properties that exist (or that you
   add) on every sibling, e.g. `"{Value} {Power} {Tolerance} {Footprint_Name}"`.
4. Add any missing discrete properties, then set `ki_description` to the
   template on every sibling in the same pass so the whole family reads
   uniformly.
5. Check `component_where_used` before editing any part that might be placed
   on a board, to make sure the edit is a safe property-only change.
6. If a sub-family only has one member, or its members are genuinely
   heterogeneous with no safe shared property set, **do not force a
   template** — leave it as clean, verified free text and record the
   decision + reason (see "Deliberately left as free text" below) so the
   next session doesn't re-litigate it.

### Known property-key quirks (flagged, not fixed — needs maintainer sign-off)
Two base-symbol-wide property-naming issues were found this pass. Both are
internally consistent across every affected sibling and don't cause wrong
data — renaming a property key is a bigger, base-symbol-wide change than a
description-templating pass, so they were left alone and are recorded here
instead of being silently changed:
- **Diodes / Zener sub-family** uses the property key `Zenner Voltage` and
  `comp_type=ZENNER` (extra "n") on every BZT52Cxx/BZX84Cxx sibling. The
  Zener-family `ki_description` template intentionally keeps the same
  spelling to match the key name — this is a deliberate consistency choice,
  not an uncaught typo.
- **Transistors / BJTs** (`BC817-40-7-F`, `BC847CLT1G`, `MMBT3904,215`) use
  the property key `Continuous Drain Current` for what is actually collector
  current — a copy-paste leftover from the NMOS/PMOS base template. The
  values themselves are correct.

If a maintainer wants either renamed, do it as one dedicated base-symbol pass
across every affected sibling at once, not piecemeal.

### Templates already standardized

| Category / sub-family | Template |
|---|---|
| Resistor (general purpose, thick film) | `{Value} {Power} {Tolerance} {Footprint_Name}` |
| Resistor (precision thin film, tempco specified) | `{Value} {Power} {Tolerance} {Tempco} {Footprint_Name}` — adds the `Tempco` property (format `10ppm/°C`, `25ppm/°C`). Use this variant only when the part is bought FOR its temperature coefficient. Without it a 10ppm and a 25ppm part of the same value, size and tolerance describe identically, and the library already holds both: `RT0402BRB071KL` (1K, 0.1%, 10ppm) sits beside the thick-film 1% `0402WGF1001TCE`, both `Value = 1K` |
| Capacitor (ceramic MLCC/general) | `{Value} {Voltage} {Dielectric} {Tolerance} {Footprint_Name}` |
| Capacitor (polarized: Aluminum Electrolytic / Tantalum) | same template as above, extending the `{Dielectric}` slot: `Al Elec` for aluminum electrolytics, `Tantalum` for tantalum caps |
| Diodes / Schottky | `Schottky Diode {Maximum Reverse Voltage} {Forward Voltage} {Continuous Current} {Footprint_Name}` |
| Diodes / Zener (BZT52Cxx, BZX84Cxx) | `Zenner Diode {Zenner Voltage} {Power} {Footprint_Name}` — spelling "Zenner" is intentional, see property-key quirks above |
| Diodes / TVS simple 2-pin clamp (D_TVS_Bi) | `TVS Diode {Reverse Stand-Off Voltage} {Footprint_Name}` |
| Diodes / TVS surge-rated SMAJ series | `TVS Diode {Reverse Stand-Off Voltage}WM {Clamping Voltage}C {Footprint_Name}` |
| Diodes / General Purpose rectifier | `General Purpose Diode {Maximum Reverse Voltage} {Continuous Current} {Footprint_Name}` |
| Diodes / Multi-channel ESD protection array | `4-Channel ESD Protection Array {Reverse Stand-Off Voltage}WM {Footprint_Name}` |
| Diodes / Photodiode PIN (moved here from ICs) | `Photodiode PIN {Peak Wavelength} {Footprint_Name}` |
| Transistors | `{N-MOS\|P-MOS\|NPN} {Vds or Vce} {Id or Ic} {Power} {ShortFootprintName}` — hand-composed per subtype (MOSFETs and BJTs use different property key names, so one literal placeholder string can't cover the whole category); verified word-for-word conformant across the entire category |
| Inductors (fixed/power) | `{Value} {Rated_Current} {Tolerance} {Footprint_Name}` — the real property key is `Rated_Current`, not `Current` |
| Inductors / Ferrite Bead | `Ferrite Bead {Impedance} {Rated_Current} {Footprint_Name}` — its own sub-family template, uses `Impedance` (the electrically meaningful ferrite-bead rating) instead of `Value`/`Tolerance` |
| LEDs / single-die indicator (colored/UV/IR) | `{Color} LED {Wavelength} {Forward Current} {Forward Voltage} {Footprint_Name}` |
| LEDs / Addressable RGB LED, integrated driver (Worldsemi WS2812/WS2816, moved here from ICs) | `{PWM Resolution} Addressable RGB LED {Voltage Range} {Footprint_Name}` |
| Timing_Components / Crystal | `Crystal {Value} {Tolerance} {Load Capacitance} {Footprint_Name}` |
| Circuit_Protection / Polyfuse | `Resettable Fuse {Value} {Voltage_Max} {Footprint_Name}` |
| Mechanical_7S / LightPipe (FIX&fasten FIX-LEMB series) | `Transparent PC light pipe, L={Length}, head ⌀{Head Diameter}, post ⌀{Post Diameter} in ⌀{Mounting Hole Diameter} mounting hole, 60° conical lens ({Manufacturer 1} {Manufacturer Part Number 1})` |
| Connectors / Terminal block plug (generic invisible footprint) | `Pluggable terminal block plug; {Pitch}` |
| Connectors / Terminal block base/header (real threaded-flange footprint) | `Pluggable terminal block; {Pitch}` |
| ICs / LDO | `LDO {Output Voltage} {Output Current} {Footprint_Name}` (`Dual LDO ...` for dual-channel parts) |
| ICs / DC-DC converter IC (switching regulator) | `{Topology} {Output Voltage} {Input Voltage} {Output Current} {Footprint_Name}` (`Output Voltage` = `Adj` for adjustable parts — verify against the datasheet, do not assume fixed-output) |
| ICs / DC-DC converter module | `{Topology} {Output Voltage} {Input Voltage} {Output Current} {Footprint_Name}`, `Topology` = `Isolated`/`Non-Isolated` |
| ICs / Battery Charger (linear, single-cell) | `{Interface} Battery Charger {Charge Current} {Footprint_Name}` (`Interface` = `Standalone` or `I2C`) |
| ICs / single-gate logic (TI single-gate logic — `74LVC1Gxx` / `SN74LVC1Gxx` and `SN74LV1Txx`, ANY package) | `{Function} {Output Current} {Input Voltage} {Footprint_Name}` — first written for the SC-70-5 Schmitt-trigger inverters and buffers, but the family outgrew that scope and the template held. It now also carries `SN74LVC1G123DCTR` (retriggerable monostable, SSOP-8), `SN74LVC1G74DCUR` (D flip-flop with preset and clear, VSSOP-8) and `SN74LV1T125DCKR` (level-shifting 3-state buffer, SC-70-5 — a **different TI logic family**, LV1T, whose pinout and property set fit this row without strain). Do not restrict this row to inverters, to one package, or to one TI logic family again. `Function` is hand-composed from the datasheet title, shortened enough to read on a schematic sheet but keeping whatever distinguishes the part — for the '74 that means keeping "with Preset and Clear", because both inputs are asynchronous and both must be tied high to run; for the LV1T it means keeping the level shifting, because `SN74LVC1G125DCKR` sits in the same library with the same function, the same package and the same pinout, and the reduced input thresholds are the whole reason both parts exist. Two property keys need care. `Output Current` is the drive figure at the part's highest specified VCC (the 4.5 V or 5 V spec point), chosen so siblings stay comparable — do not quote the headline number from the Features list, which is usually the 3.3 V figure. `Input Voltage` holds the **VCC supply range** from Recommended Operating Conditions, not the VI input range: the key name is misleading, but every sibling uses it that way, so keep it consistent instead of fixing one part in isolation |
| ICs / Analog switches — multiplexers (TMUX1208 family) | `{Channels} Analog Multiplexer {Footprint_Name}` |
| ICs / Voltage-level translators (TI TXSxxxxE) | `{Bit Width} Bidirectional Level Translator {VCCA Range}/{VCCB Range} {Footprint_Name}` |
| ICs / Winbond serial NOR flash memory (W25Qxx) | `{Capacity} {Voltage Range} {Max Frequency} SPI {Footprint_Name}` |

### Deliberately left as free text (documented — don't re-litigate)

| Category / sub-family | Reason |
|---|---|
| Diodes / Asymmetrical dual-channel TVS (SM712) | Only one of its kind; compound "12V / -7V"-style ratings across every property — appending `{Footprint_Name}` to the application-descriptive sentence reads worse than the current accurate free text |
| LEDs / RGB (multi-die) LED | Only one in the library; no single meaningful Wavelength/Forward Voltage — per-channel R/G/B ratings differ. Revisit once more RGB/multi-die LEDs are added |
| Timing_Components / Oscillator | Only one oscillator exists in the category — no siblings yet to validate a shared template against |
| Circuit_Protection / Fuse Holder (PTF-77) | Only fuse-holder type in the category, no siblings |
| Buttons (all sub-types) | No discrete body-dimension/actuation-force properties (Length/Width/Height/Force) exist yet on any Buttons component to back a template, and the category is genuinely heterogeneous (SMD top-push / TH top-push / TH right-angle-lever with a force spec the others don't have). Backfilling verified properties is a bigger data-modeling task — recommend as a dedicated follow-up |
| Mechanical_7S / Enclosure (Hammond/Takachi) | Two manufacturers, three materials/finishes, wildly different form factors (small flanged box to wall-mount enclosure) — forcing one template across 5 siblings would drop meaningful wording or need several one-off properties for marginal benefit |
| Mechanical_7S / MountingHole_Pad | Generic KiCad placeholders, not manufactured parts — no Manufacturer 1; dimensions already fully encoded in the name + footprint |
| Mechanical_7S / 7Sigma_Logo | One-off internal schematic graphic asset, not a manufactured/purchased component |
| ICs / Voltage reference, shunt (LM4040D25FTA) | The library's first voltage reference, so there is no sibling to validate a shared property set against, and the rule for a sub-family of one is to leave clean verified free text. Its description carries the output voltage, the grade tolerance and the 60uA~15mA operating current range, the last because a shunt reference is only in regulation inside that band and the bias resistor has to hold it there across the whole supply and load range. When a SECOND reference lands, template both on `{Output Voltage} {Tolerance} {Operating Current} {Footprint_Name}` and backfill the discrete properties — do not template at n=1 |
| Relays (whole category) | Only 2 components, two unrelated sub-families (12A THT power relay vs. 1A SMD signal relay) with n=1 each — no shared property set to template against yet. Revisit once more Relays (especially more of one sub-family) are added |
| TestPoints (whole category) | Only 3 components, genuinely heterogeneous: 1 sourced manufacturer part vs. 2 generic user-defined pad footprints with no shared discrete property |
| Connectors / FFC-FPC, pin/debug headers, SMA-RF coax, one-off connectors (USB-C receptacle, board-to-board, RJ45 jacks, USB receptacles, battery holders, singleton types) | Each sub-type has only 2-3 siblings or is a singleton, and the distinguishing attributes (position count, pitch, shielding, mount style) aren't yet captured as discrete properties. Templating off 2 data points felt forced; copy-paste description bugs were fixed instead |
| Connectors / broader terminal-block family (Phoenix Contact-style MCV/MSTBVA/WJ*/DB2E*/15EDG*/DMCV/XY302V/DB301V, ~36 members) | Already has its own internally-consistent free-text convention predating this pass ("Pluggable terminal block plug; {pitch}mm" / "Pluggable terminal block; {pitch}mm" / "Screw Terminal Block; {pitch}mm" / descriptive cage-clamp sentences). Only the smaller plug/base sub-set above (with a real footprint) got literal `{Pitch}`-property templates this pass. Reconciling the WHOLE family onto one discrete `Pitch` property is a recommended future full-family pass (needs both Connectors chunks reviewed together) — don't fragment the family's current uniformity by templating only part of it again |
| ICs / Fuel Gauge, MCU-SoC & wireless modules (ESP32/cellular/GNSS/UWB), Op-amp + high-side-switch + LED-driver singletons, Cellular/LTE modules, Magnetometers, Op-Amps, Microphones, MCU (RP2040), MCU (STM32 family), RS232/RS485 transceivers, SIMO multi-rail regulator, Single-channel gate driver, LED driver IC (WS2811N), GNSS receiver module (u-blox ZED-F9P) | Each has only 1-3 siblings that are structurally different from each other (different core architecture, different protocol, different topology) with no safe shared property set — forcing a template would either drop real distinguishing info or fabricate fields. Garbled/copy-pasted descriptions were cleaned up to accurate free text where found instead. Revisit each once the sub-family has enough genuine siblings |

### Remaining work (targeted follow-ups, not a from-scratch sweep)
Every category in the library has now been audited at least once (see the
closing note). What's left is specific, not a fresh first pass:
1. **Connectors terminal-block family** — unify the ~36-member
   Phoenix-Contact-style family (plugs, bases, screw terminals, cage-clamp)
   onto one discrete `{Pitch}`-based template instead of the current
   three-way free-text convention. Needs both Connectors chunks reviewed
   together.
2. **Buttons** — backfill verified Length/Width/Height/Force properties
   across the whole category, then template.
3. **Kinghelm manufacturer conflict** — see Open items in §1; needs a
   maintainer decision before either form is normalized library-wide.
4. Individual ICs/LEDs/Timing_Components/Relays/TestPoints sub-families with
   only 1-2 siblings today (listed under "Deliberately left as free text"
   above) — revisit each once the library grows enough real siblings to
   template safely; don't force a template onto n=1.

## 3. The `Value` property — mandatory on every component

`Value` is the KiCad Value field: together with the reference designator it is
the **only** part identity printed next to the symbol on a schematic sheet.

**It must never be empty and must never be missing.** The HTTP library
(`kicad_http.py`) only emits a `value` field when the component actually has a
`Value` property; when it is absent KiCad falls back to the **base symbol's own
name**, so the sheet reads `Conn_01x04` or `TestPoint` instead of the part. A
missing `Value` is a defect, not a cosmetic gap.

Also never acceptable: `~`, `N/A`, `-`, an unresolved `{Template}` placeholder,
or a copy of `ki_description` (the description is a separate, longer field).

### The rule

> `Value` is the **shortest string that identifies this part on a schematic
> sheet**.

Decide in this order:

1. **Is the component a member of a parametric family?** — many library parts
   sharing one base symbol and differing only in a single primary rating
   (resistance, capacitance, inductance, Zener voltage, frequency…). If yes,
   `Value` = **that rating**, formatted per the table below. Nobody reads
   `0402WGF4701TCE` off a schematic; they read `4K7`.
2. **Otherwise it is a specific purchased part** → `Value` =
   **`Manufacturer Part Number 1`, verbatim**. Use the MPN, not the component
   name: component names are sanitized for KiCad (`_` substituted for spaces
   and commas), so e.g. component `MCV_1,5/_2-GF-3,5-LR` gets
   `Value = "MCV 1,5/ 2-GF-3,5-LR"`.
3. **Exception to 2 — the MPN alone does not identify the part** (it is a bare
   series number, or there is no MPN because the part is generic and not
   purchased) → `Value` = **the component name**. This covers test-point pads,
   mounting holes, generic solder pins, and manufacturers whose MPN is a bare
   code.

### Per-category formats

| Category / sub-family | `Value` is | Format | Examples |
|---|---|---|---|
| Resistor | Resistance | RKM code — the multiplier letter replaces the decimal point, no `Ω`: `m` / `R` / `K` / `M` | `0R`, `10R`, `24R9`, `4K7`, `10K`, `768K`, `10m` |
| Capacitor (all dielectrics) | Capacitance | number + `pF`/`nF`/`uF`, decimal point kept | `1.2pF`, `100nF`, `4.7uF`, `470uF` |
| Inductors (fixed/power) | Inductance | number + `nH`/`uH` | `2.2nH`, `470nH`, `10uH` |
| Inductors / Ferrite Bead | Impedance at its test frequency (the `Impedance` property) | `<Z>@<f>` | `100Ω@100MHz` |
| Diodes / Zener | Zener voltage | RKM-style `V` code | `3V3`, `5V1`, `8V2`, `12V` |
| Diodes / TVS + ESD clamp | Reverse stand-off voltage | same | `5V`, `12V`, `5.5V`, `12V / -7V` (asymmetric parts) |
| Diodes / Schottky, general-purpose rectifier, photodiode | MPN | verbatim | `SS34`, `1N5819WS`, `VBPW34FAS` |
| Timing_Components / Crystal, Oscillator | Nominal frequency | number + `MHz`/`kHz` | `12MHz`, `25MHz`, `40MHz` |
| Circuit_Protection / Polyfuse | Hold current | number + `mA`/`A` | `50mA`, `500mA`, `1.1A` |
| Circuit_Protection / Fuse holder | Short descriptive label (not a parametric family, no useful rating) | — | `Fuse Holder` |
| RF / Antenna | Operating band or centre frequency | frequency, or a range for wideband parts | `2.4GHz`, `1575 MHz`, `6GHz ~ 8.2GHz` |
| Transistors, ICs, LEDs, Connectors, Buttons, Relays, sourced Mechanical_7S, sourced TestPoints | MPN | verbatim | `AO3400A`, `STM32G031G8U6`, `HU2032-LF`, `WS2816C-1313/4P` |
| Generic / not purchased (no MPN) | Component name, or a short human label | — | `TestPoint_Pad_D1.5mm`, `MH_M3_3.2mm_6mm_OD`, `Pin_0.7mm_Soldering_Pin`, `7Sigma Logo` |

Why the split: a parametric part's rating is what the reader needs and the MPN
is noise; for everything else the MPN *is* the shortest unique identity, and
inventing a nickname just creates drift between the schematic, the BOM and the
supplier.

### Documented deviations from "MPN verbatim" (don't re-litigate)

| Component(s) | `Value` | Why |
|---|---|---|
| `15EDGKNM-3.5-{02,04,05,08}P-14-00A(H)` | `15EDGKNM-3.5-02P` etc. | The `-14-00A(H)` tail is packaging/colour ordering code, not part identity |
| `Hammond_1551RFLGY`, `1551TFLGY`, `1551XFLGY`, `1556CGY` | component name | Bare MPN `1551RFLGY` doesn't say Hammond; the component name carries the manufacturer prefix |
| `Takachi_SIM6-12-3W` | component name | Same reason |
| `KEYS2466` | component name | MPN is the bare series number `2466` |
| `RPi_CM5` | component name | MPN is the bare `CM5` |

### Placement in the property list

Insert `Value` **first** (position 0) on new components and when backfilling —
this matches the majority of the library and KiCad's own field order
(Reference, Value, Footprint, Datasheet, then custom fields). `Value` is stored
with `hide=true` like every other property; the HTTP library router is what
marks it visible on the sheet, so don't try to change `hide` to make it show.

### Backfill status

A full-library `Value` audit was run **2026-07-25**: 317 components checked,
**68 had no `Value` property at all** (36 Connectors, 25 ICs, 3 TestPoints,
2 LEDs, 2 Mechanical_7S). All 68 were drafted with the rule above; every other
component already had a non-empty, on-rule `Value`. Known follow-ups left
open deliberately:

- `BLM18EG101TN1D` (ferrite bead) still has `Value = 68nH` while its
  `Impedance` property reads `100Ω@100MHz`. Per the table above a ferrite
  bead's `Value` should be the impedance — flagged for a maintainer decision
  rather than changed, because 68nH is also a real published spec for the part.
- `Pin_0.7mm_Soldering_Pin` carried **duplicate empty** `Manufacturer 1` and
  `Manufacturer Part Number 1` rows. The duplicates were dropped in its
  backfill draft. If duplicate keys show up elsewhere, drop them the same way —
  `propose_component_edit` rejects duplicate keys outright.

## 4. Category placement — check the source catalog's own category field

When importing or reassigning a component's `category`, don't infer it purely
from part-number shape or which chunk you happened to be auditing — check
LCSC's own catalog category field (via `lcsc_lookup`) or the datasheet before
finalizing. Recurring miscategorization patterns found and fixed this pass:

- **LEDs and photodiodes filed under `ICs`.** Integrated-driver/addressable
  RGB LEDs (Worldsemi `WS2812E-1313`, `WS2816C-1313` — LCSC category "LED
  Addressable, Specialty"), a UV LED emitter (`M3535N1UVS8U12-365NM` — LCSC
  "LED Emitters"), and a silicon PIN photodiode (`VBPW34FAS` — a 2-terminal
  diode per its own Vishay datasheet, not an IC) had all been imported into
  `ICs`. Moved the LEDs/emitter to `LEDs` and the photodiode to `Diodes`.
- **Mechanical hardware filed under `Connectors`.** SMD round nuts/standoffs
  (`SMTSO2010CTJ`, `SMTSO2515CTJ` — LCSC category "Board Spacers, Standoffs")
  are mounting hardware, not electrical connectors. Moved to `Mechanical_7S`.
- Before moving anything, check `component_where_used` to confirm the move is
  a safe property-only change on any board the part might already be placed
  on.

---
**Last full-library `Value` audit:** 2026-07-25 — 317 components checked, 68
backfilled as drafts (see §3).

**Last full-library standardization pass:** 2026-07-21 — every category
audited at least once, 308 components checked, 198 component-level edit
proposals drafted (all left as drafts pending user approval, nothing changed
live). If you're about to start a "first pass" over a category, check the
tables above first — it's very likely already been done.
