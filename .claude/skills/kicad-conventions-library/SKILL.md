---
name: kicad-conventions-library
description: "House style for component data: how a manufacturer name, a ki_description template, a Value and a Power rating are decided, and when NOT to template at all. The lists themselves live in the checks (cmp.manufacturer_canonical, cmp.description, cmp.value_field, cmp.power_format) - this says why each was decided and what a check cannot judge. Read before proposing a new component or editing an existing one's properties."
---
<!-- platform-skill: conventions-library v37 — source of truth is the platform; check with list_skills, refresh with get_skill -->

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

### Use the company's own stylization

Title Case for most brand names — **except** where the company's own
stylization is genuinely different. Do not "fix" a real stylization into Title
Case, and do not copy a distributor's shout-casing into one.

The check carries the decided spelling for all 81, so you rarely have to judge.
The classes, if you meet a new one:

- **lowercase**: `u-blox`, `onsemi`, `8devices` — the company's own trade name.
- **all-caps**: `KEMET`, `OSRAM`, `TDK`, `BHFUSE`, `CJIANG`, `KNSCHA`,
  `TDSEMIC`, `SCTF`, `XFCN`, `RESI`, `YXC`, `TOGNJING` — genuine brand
  stylization, not a feed shouting.
- **other**: `FIX&fasten`, `Worldsemi`, `MaxLinear`, `G-Switch`.
- **parenthetical**: where the short brand alone would not identify the company
  — `FH (Guangdong Fenghua Advanced Tech)`, `UMW (Youtai Semiconductor Co.,
  Ltd.)`, `MDD (Microdiode Semiconductor)`.

**Three all-caps entries rest on distributor evidence only** — `RCH`, `SCTF`
and `TOGNJING` — because no manufacturer homepage was ever found. Re-check any
of them if a primary source turns up.


### The list lives in the check, not here

**`cmp.manufacturer_canonical` holds the 81 canonical spellings** and compares
`Manufacturer 1` against them on every purchasable part. Open the check to read
or extend the list: Reviews → Checks → `cmp.manufacturer_canonical`. It was a
table in this document until 2026-09-14, which meant a list nobody could query
and a rule nobody ran.

It is a **warning**, because a name that is not on the list usually means the
LIST is short, not that the part is wrong. Adding the canonical spelling to the
check clears it — and that is the whole fix.

Measured the day it shipped: 59 parts carry 31 names the list does not have.
Most are ordinary company names nobody has got round to adding — `Nexperia` on
10 parts, `Littelfuse` on 6, `Molex`, `ROHM`, `Kingbright`, `Keystone`,
`Raspberry Pi`. A few are genuinely unresolved and are recorded below.

### The thirteen that were decided, and why

Most of the 81 are simply a spelling. These are not — each cost a judgment, and
re-litigating one wastes the session that already made it:

- **CJIANG** — decided 2026-09-13. The letterhead on all 61 pages of the FTC
  datasheet. `Changjiang` and `Changjiang Microelectronics Technology` were both
  earlier house guesses and are wrong; the footprint vendor token is `CJIANG`.
- **BHFUSE**, **CJIANG** — genuine all-caps brands, like KEMET and OSRAM. Do not
  Title-Case them.
- **ECS Inc.** — the company's own materials disagree with themselves ("ECS Inc.
  International" in press releases, "ECS International" on an About page). The
  house form matches its site `<title>` and DigiKey's listing.
- **Diodes Incorporated** — the full legal name, not the feed's shouted
  "DIODES" nor the earlier house form "Diodes Inc". Vendor token
  `DiodesIncorporated`.
- **Infineon Technologies**, **Murata**, **Vishay Semiconductors**,
  **OMRON**, **YXC**, **RESI**, **UMW (Youtai Semiconductor Co., Ltd.)**,
  **8devices**, **MyAntenna**, **Walter Electronic** — each resolved against the
  company's own material rather than a distributor feed. The check carries the
  spelling; do not re-derive it from LCSC.

### Still unresolved — ask, do not guess

- **`TWGMC`** (on SS34) — only a weak, unquotable link to "Taiwan Dijia
  Electronics"; no primary source.
- **`Milliohm`** (on `HoYH0805-3/4W-50mR-1%`) — 深圳市毫欧电子, whose datasheet and
  site name the company only in Chinese. `Milliohm` is LCSC's brand-page form
  and a literal reading of 毫欧. No manufacturer-published English name exists,
  so the brand test cannot be applied at all.
- **`TECH PUBLIC`** (on PESD5V0S1BA) — consistently ALL-CAPS everywhere, but no
  company homepage confirms it is the brand's own stylization.
- **`Kinghelm` vs `Shenzhen Kinghelm Elec`** — two sessions picked two forms for
  one company, and BOTH are in the check's list. Four Buttons/RF parts use the
  long form, one Connector uses the short one. **Do not silently reconcile** —
  the user picks the house form, then every affected part moves in one pass.


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

### Property-key spellings

**Renaming a property key is a MATERIAL edit.** A key is not in
`NON_MATERIAL_KEYS`, so the rename blocks the verification and sign-off carry
and the part comes back unreviewed. Before renaming one on a signed part, check
whether it is verified and whether any `ki_description` references it. On an
unreviewed part with no template reference the pass is free — that is how the
`V.S.W.R` → **`VSWR`** rename ran on four RF parts in 2026-09-11, and why the
Zener pass on 2026-09-14 cost six verifications.

- **Zener, with ONE "n"** — `Zener Voltage`, `comp_type=ZENER`, "Zener Diode".
  The double "n" propagated as a typo and this document used to record it as a
  deliberate choice; the owner reversed that: *"from now on we should use
  'Zener' with one n, previously it was a mistake."* All six parts were
  backfilled on 2026-09-14, key and `comp_type` and template word together —
  they have to move together, or `cmp.templates` fails on the dangling
  `{Zenner Voltage}`. No `Zenner` remains on a live version. Do not
  re-introduce it, and do not "correct" a new part back to match an old sibling.
- **BJTs still use `Continuous Drain Current` for collector current**
  (`BC817-40-7-F`, `BC847CLT1G`, `MMBT3904,215`) — a leftover from the
  MOSFET base template. The values are right, the key is wrong. Open; rename it
  as one pass across every sibling, never piecemeal.


### The templates live in the checks, not here

**`cmp.description` on each parametric category holds the templates that
category allows** — Capacitor 1, Resistor 2, Timing_Components 1, LEDs 3,
Circuit_Protection 3, Inductors 5, Diodes 9. Read or extend the list at
Reviews → Checks, filtered to that category.

`ki_description` is STORED as the template; the generator expands it at mirror
time, so the check compares template against template. Adding a sub-family
template is a deliberate edit to the check — a new shape is a decision, a typo
is not.

Connectors, ICs, Transistors, Buttons, Mechanical_7S and RF describe each part
individually (66 distinct descriptions across 107 ICs), so there is nothing to
compare against and `cmp.description` stays a judgment check there.

### Four templates carry a literal a person writes

- **SMAJ-series TVS** — `{Unidirectional|Bidirectional}`, read off the part
  number: the datasheets break the code as `SMAJ` | `XXX` | `C` | `A` with `C`
  labelled BI-DIRECTIONAL, so an A-suffix part without `C` is unidirectional.
  **Not optional.** Without it `SMAJ24A` and `SMAJ24CA` render a byte-identical
  BOM line, and a unidirectional part fitted where a bidirectional one belongs
  conducts like a forward diode on the negative half cycle — invisible on the
  schematic and in the BOM.
- **ESD arrays** — the channel count. Count the protected I/O pins in the pin
  table; the digit in the part name usually agrees, the pin table decides.
- **Transistors** — `{N-MOS|P-MOS|NPN|PNP}`, and MOSFETs and BJTs use different
  rating keys, so one placeholder string cannot cover the category.
- **TI single-gate logic** — `{Function}`, hand-composed from the datasheet
  title. Keep whatever distinguishes the part ("with Preset and Clear" on the
  '74; the level shifting on an LV1T, which otherwise matches
  `SN74LVC1G125DCKR` exactly). `Output Current` is the drive figure at the
  part's HIGHEST specified VCC, not the headline 3.3 V number. `Input Voltage`
  holds the VCC supply range, not the input range — the key name is misleading
  and every sibling uses it that way.


### Power ratings — one spelling per rating

**`cmp.power_format` enforces the shape**: whole milliwatts below 1 W, a decimal
above it. `63mW`, never `62.5mW`, never `0.0625W`.

Two things the pattern cannot say:

- **It overrides the datasheet's own wording.** Yageo spells 1/16 W as
  "0.0625W" and the RT series says 1/16 W; both mean 62.5 mW and the house form
  rounds. Do not "correct" a `63mW` back — put the exact figure in the
  verification note, which is where evidence belongs. Decided 2026-08-28, after
  one part shipped as `62.5mW` beside sixty `63mW` siblings on the same land.
- **Not every sub-63 mW figure is a rounded 1/16 W.** `PTFR0402B1K21N9` is
  correctly `60mW` — the RESI datasheet rates that size 0.03 / **0.06** /
  0.13 W as manufacturer power grades. Confirm in the datasheet before
  normalising anything to `63mW`.

1/32 W (31.25 mW) has no decided spelling and no library part carries it. Ask.


### Do not template a sub-family of one

**A template needs siblings to validate against.** With one or two members you
cannot tell a shared property set from a coincidence, and forcing a template
either drops real distinguishing information or invents fields. The rule is
clean, verified free text until the family grows, then template both at once and
backfill the properties.

Deliberately free text today, each for that reason: the SM712 asymmetric TVS,
the multi-die RGB LED, the oscillator, the fuse holder, every Buttons sub-type,
the enclosures, mounting-hole pads, the logo, the shunt voltage reference, both
Relays, all three TestPoints, the FFC/header/coax/one-off Connectors, and the
ICs whose siblings differ by architecture or protocol (modules, MCUs,
transceivers, gate drivers, op-amps, fuel gauges).

`cmp.description` stays a judgment check in those categories, so nothing here is
being skipped — it is being asked of a person instead of a pattern.


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

> **The platform checks this**, per category. `cmp.value_placeholder` refuses an
> empty Value, `~`, `N/A`, `-`, an unresolved `{Template}` or a copy of
> `ki_description`. `cmp.value_field` then applies one variant per category
> shape: the RKM code for Resistors, the unit format for Capacitors and
> Timing_Components, the manufacturer part number verbatim for ICs, Transistors,
> Buttons, LEDs, Relays and Connectors, and the component's own name for
> Mechanical_7S and TestPoints. A category no variant covers falls through to the
> same human question as before.
> The deviations listed below are recorded as standing exceptions on those six
> parts, so they are not re-discovered — do not re-litigate them and do not
> re-file them.

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

### The per-category formats live in the check

`cmp.value_field` carries one variant per category shape — the RKM code for
Resistors, the unit format for Capacitors and Timing_Components, the part number
verbatim for ICs, Transistors, Buttons, LEDs, Relays and Connectors, the
component's own name for Mechanical_7S and TestPoints, and inside Diodes a split
on `comp_type` (stand-off voltage for a TVS, an RKM V code for a Zener, the part
number for a rectifier). A category no variant covers falls through to a
judgment item.

Why the split: a parametric part's rating is what the reader needs and the part
number is noise; for everything else the part number IS the shortest unique
identity, and inventing a nickname only creates drift between the schematic, the
BOM and the supplier.


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

A full-library `Value` audit ran 2026-07-25: 317 components checked, 68 with no
`Value` at all, all drafted against the rule above. `cmp.value_placeholder` now
refuses an empty or placeholder Value on publish, so that audit cannot be needed
again.


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
