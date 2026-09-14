# What I decided overnight, for you to confirm — 2026-09-14

Everything below was done on a **local copy of production**, restored from
`kicadlib-20260914-014453.dump`. Nothing reaches production until the copy is
uploaded back, so any row you reject can simply be undone before that.

**Two things to do together, in the morning:**

1. **Upload the local database to production.** Nothing below has reached
   production; it all lives in the local copy. Take a pre-restore dump of
   production first — I left one at
   `~/kicadlib-backups/kicadlib-PRERESTORE-20260914-020328.dump` on the server,
   but take a fresh one if any time has passed.
2. **Turn `datasheet_recheck_nightly` back ON.** I disabled it at 03:44 CEST so
   the nightly job could not write into the snapshot window, and confirmed the
   timer never armed. It is off until somebody sets it back.

`~/kicadlib-backups/worked-20260914.dump` on the server is an INTERMEDIATE
upload from partway through the night. Ignore it — it is not the finished
state.

## Legend

| Mark | Meaning |
|---|---|
| **RULE** | I already had the rule written down; I applied it. Low risk. |
| **JUDGED** | I decided something that was open. **Check this.** |
| **FOUND** | Measured and reported, nothing changed. |

---
## 1. `na` answers — machine first, exceptions last

You asked me to make the recorded `na`s fit the new system. Measured: **449 live
`na` answers, 447 written by an agent, 401 with no reason code.** The top keys
show most are not decisions at all:

```
sym.stacked       136   "No stacked pins."
sym.grouping       77
cmp.electrical     45   "No discrete electrical properties."
cmp.templates      38
cmp.datasheet_text 28   "No datasheet is attached."
```

Those are FACTS. So the machine now decides them, and the question stops being
asked of parts it is not about.

| | | |
|---|---|---|
| **RULE** | `sym.stacked` is asked only of a symbol that stacks pins | 22 of 207 do. The other **185 are now `inapplicable`**, which is what 136 hand-written answers were saying. |
| **JUDGED** | `cmp.electrical` is asked only of a part carrying electrical data | **109 of 442** carry none — a mounting hole, a logo, a test-point pad. Check my definition: a property is "electrical" unless it is `Value`, `Footprint`, `Datasheet`, `ki_description`, `ki_keywords`, `ki_fp_filters`, `comp_type`, `LCSC Part`, or starts `Manufacturer` / `Supplier` / `Sim.`. A category that REQUIRES a property still has `cmp.required_props`, so nothing is hidden. |
| **FOUND** | `cmp.datasheet_text` already answers `na` itself when there is no archived PDF | Those 28 answers were always redundant. Nothing changed. |

**Stacked pins are counted by POSITION, not by pin number.** My first attempt
counted repeated numbers and found zero across the library; stacking is two
different numbers shorted at one point. Worth knowing if you ever read that fact.

Stored `na` answers are NOT rewritten — they are what a past record said. The
change is what gets ASKED from now on.

## 2. Rules lifted out of the skills into checks

### Automatic, and all three already satisfied on every footprint

| Check | Rule | Finds |
|---|---|---|
| `fp.name_charset` | `A-Z a-z 0-9 _ . , + -` only, never a space | 0 |
| `fp.name_spellings` | `_HandSoldering`, and rotation never in a name | 0 |
| `fp.model_path` | a 3D reference starts `${SEVENSIGMA_DIR}/3DModels/` | 0 |
| `fp.smd_rratio` | roundrect corner ratio `0.25` | **37**, as a warning |

`fp.name_spellings` will fire on an adopted **Tier 0** footprint that legitimately
carries `_HandSolder` — excuse those rather than renaming stock.

### Judgment — rules a person verifies, now on the checklist instead of in prose

**JUDGED — these are new questions asked of every part of that kind.** If any
is not worth asking on every one, say so and I will narrow or drop it.

Footprints: `fp.one_land_per_package`, `fp.tier`, `fp.field_order`,
`fp.cathode_bar`, `fp.npth_mechanical`, `fp.thermal_vias`.

Symbols: `sym.ground_placement`, `sym.bus_sides`, `sym.drawing_family`,
`sym.hidden_names`.

## 3. The symbol pin grid — I did NOT change it, and here is why

You said 2.54 is the rule with obvious exceptions, and to leave it if unsure.
Looking at the 61 off-grid symbols, they are not exceptions — the rule as
written is impossible to satisfy.

```
Conn_01x06   pins at y = ±1.27, ±3.81, ±6.35   consecutive spacing exactly 2.54
Varistor     pins at y = ±3.81                 spacing 7.62 = 3 × 2.54
WS2812       pins at y = ±1.27                 spacing 2.54
BZX84Cxx     pins at x = -3.81, 1.27, 3.81     spacing 2.54 and 5.08
```

**Every one has correct 2.54 mm pin-to-pin spacing.** They sit off the absolute
2.54 grid only because the symbol is CENTRED on the origin with an even pin
count, which necessarily puts each pin on an odd multiple of 1.27. That is what
KiCad's own library does.

So the two statements reconcile: **pin-to-pin SPACING is 2.54 mm, and the
absolute grid is 1.27 mm.** Under that reading nothing in the library violates
anything, and `sym.pins_grid` at 1.27 mm is already correct.

**JUDGED — but not acted on.** I left `sym.pins_grid` at 1.27 and changed no
symbol. Confirm the reading and I will write it into the skill as one rule and
close row 25. If you want the absolute 2.54 instead, it means re-centring 61
symbols, including every even-pin part.

## 4. The 181 remaining `na` answers became standing exceptions

After the machine took the ones it could decide, **262 `na` answers sat on
questions the platform still asks**. They split cleanly:

- **81 on MACHINE keys** (`cmp.templates`, `cmp.datasheet_text`,
  `cmp.required_props`, `cmp.footprint_ref`). A person's `na` on a machine check
  means nothing now — conformance computes those. **Left alone as history.**
- **181 on JUDGMENT keys**, 178 with a substantive note. **180 became standing
  exceptions** (one skipped: `Enclosure_TAKACHI_SIM6-12-3W` / `fp.pad_numbering`
  whose whole note was "No pads.", too thin to be a decision).

The library now holds **186 live exceptions, 0 stale**:

| | |
|---|---|
| symbol | 123 |
| component | 42 |
| footprint | 21 |
| pinned to the drawing | 144 |
| pinned to the component's data | 36 |
| "this part, always" | **6** — only the documented Value deviations |

**None of the 180 was granted "always".** Every one is pinned, so it dies if the
drawing or the component data changes. That is decision 0018's default and I did
not override it.

### JUDGED — the reason codes I inferred

153 of the 181 carried no reason code, so I derived one from the note text:

| Reason | Count | Derived from |
|---|---|---|
| `feature_absent` | 91 | "none should exist", "none apply", "no datasheet exists", "has no", "only one pin" |
| `kind_exempt` | 36 | "house-defined", "generic", "not purchased", "convention", "exempt" |
| `other` | **59** | nothing matched — **these are the ones to spot-check** |

The 59 `other` are mostly `sym.grouping` (23), `sym.geometry` (10),
`sym.pinout` (5), `fp.pad_numbering` (5). Their notes read like real decisions
("No source catalogue to confirm against — no LCSC number, no datasheet row"),
they just did not match a keyword. Re-code them in the Exceptions register if
you want the health tab to aggregate them properly.

**43 notes were truncated to the 400-character limit**, cut at a sentence
boundary. The full text survives in the review record, which is not rewritten.

### Effect

```
before   checked 176 · failed 209 · partial 57
after    checked 182 · failed 207 · partial 53
```

## 5. New component types — you said this was allowed

`Inductors`, `RF` and `Circuit_Protection` carried no `comp_type`, so their
Value rules could not become per-type checks. **38 parts now carry one**, each
derived from that part's OWN `ki_description` template, not guessed from the
part number.

**JUDGED — confirm these ten type names and the parts under them.**

| Category | comp_type | Parts |
|---|---|---|
| Inductors | `INDUCTOR` | 13 |
| | `CHOKE` | 2 — `ACT45B-510-2P-TL003`, `DLW32MH201XK2L` |
| | `FERRITE` | 1 — `BLM18EG101TN1D` |
| | `TRANSFORMER` | 2 — `HX1188NLT`, `ETA17208` |
| RF | `ANTENNA` | 10 |
| | `PIGTAIL` | 2 — `BWIPX1-SMA-1.13L100`, `ACA-RFSMA-K_TO_IPEX1_001` |
| Circuit_Protection | `POLYFUSE` | 4 |
| | `FUSE` | 2 |
| | `FUSEHOLDER` | 1 — `PTF-77` |
| | `VARISTOR` | 1 — `B72650M0271K072` |

`comp_type` sits directly after `Value`, with the identity fields rather than
among the ratings.

One classification I got wrong first time and corrected: `ACA-RFSMA-K TO IPEX1
001` matched ANTENNA on its manufacturer name **MyAntenna**. It is a pigtail.
Worth knowing if you add more of that vendor's parts.

### And the Value rules those unlock

`cmp.value_field` now splits on `comp_type` in all three categories:
inductance for an inductor or choke, impedance-at-frequency for a ferrite bead,
the part number for a transformer or a pigtail, band for an antenna, hold
current for a polyfuse, rated current for a fuse, varistor voltage for a
varistor. A part with no `comp_type` still falls through to the human question.

**It found the two parts an agent had already flagged** — `146153-0050` and
`146153-0150` carry `2.4/5GHz 50mm` and `2.4/5GHz 150mm` where the rule says
band only. My first pattern allowed the trailing text and would have blessed
them; I tightened it, and the check now reproduces the human finding.

That also closes work-list row 23: `BLM18EG101TN1D` already carries
`100Ω@100MHz`, which is what the ferrite rule wants. There was nothing to
decide.

## 6. Rail marking — the pattern you asked for

Three judgment checks from `conventions-symbols` §5.3, scoped with a `when` to
the **116 symbols that draw supply pins** (91 do not and are not asked):

- `sym.rail_polarity` — + and − drawn outside the body, beside the right rail
- `sym.rail_negative_mark` — the negative rail is marked −, **even where that
  pin is a ground**
- `sym.rail_marks_not_names` — the rails show the marks, not their pin names

A machine can see the text but not which rail is negative, so these are
questions for a person — which is the point of a judgment check.

## 7. The 251 custom keys — what they were really asking

On live versions: **203 distinct `custom:` keys, 310 answers, 39 used more than
once.** Reading the recurring ones, they fall into three groups.

### Promoted to real checks — a finding recorded three times is a missing check

| Was | Uses | Is now |
|---|---|---|
| `custom:jlc-land-comparison-august-sweep` | 16 | `fp.jlc_land` |
| `custom:fp-filters` | 8 | `sym.fp_filters` |
| `custom:datasheet-archived-as-html` + `custom:archived-datasheet-is-an-html-page` | 8 | `cmp.datasheet_is_document` |
| `custom:easyeda-symbol-diff` | 5 | `sym.easyeda_diff` |
| `custom:topology-vs-datasheet` | 5 | `sym.topology` |

The two datasheet spellings are the clearest case for why this matters: one
finding, two private keys, and nothing could count them together.

### Already covered — the platform grew the check since

| Was | Uses | Covered by |
|---|---|---|
| `custom:pin-count-vs-pads` | 5 | `cmp.pins_to_pads` / `cmp.pads_to_pins` |
| `custom:body_vs_land` + `custom:footprint_land_match` | 7 | `fp.land_pattern` |
| `custom:footprint-missing-enclosure` | 3 | work-list row 1 |

### Not a check at all

`custom:empty-prop-cleanup` (27) records that blank `Supplier Part Number 1` and
`LCSC Part` rows were REMOVED. That is a fix somebody made, not a question
anybody should answer again, and `cmp.required_props` already refuses an empty
required property. Nothing to promote.

**Nothing was deleted.** A custom answer lives in a review record and this axis
does not rewrite history. What changes is that a later pass has a real key to
use, so the private vocabulary stops growing.

## 8. Manufacturer names — 59 parts down to 13

**JUDGED — 18 names added to `cmp.manufacturer_canonical`.** Each is the
company's own brand exactly as the library already stores it, used consistently:

```
Nexperia (10)   Littelfuse (6)   XKB Connection (4)   Italtronic (3)
Alpha & Omega Semiconductor (3)  Kingbright   Molex   Raspberry Pi
Quectel   Pulse Electronics   Microchip Technology   HGSEMI
Rubycon   Abracon   Keystone   ROHM   Sunlord   KNSCHA
```

`KNSCHA` was already decided — the skill lists it under the all-caps brand
exceptions — it had just never reached the table.

### The 13 I did NOT add, and why

**Unverifiable without a primary source, so the check keeps them visible:**

| Name | On | Note |
|---|---|---|
| `Torex Semicon` | `XC6206P332MR-G` | The company is Torex Semiconductor Ltd. This looks like an LCSC abbreviation, and the rule says never abbreviate — but I did not change it. |
| `HanRun` | `HR913550A` | The footprint token elsewhere is `Hanrun`, lower R. One of the two is wrong. |
| `YE`, `SOFNG`, `Megastar`, `Hong Cheng`, `Zhongkewei`, `Huashuo Semiconductor`, `Rainsun`, `JDTfuse` | one part each | No company material checked. Guessing a brand's own stylization is the one thing the skill forbids. |

**Already recorded as unresolved in the skill** — `TWGMC`, `Milliohm`,
`TECH PUBLIC`. Unchanged.

The check is a warning, so none of this fails a part. Settle a name and add it
to the check; that is the whole fix.


---

# Part 2 — the check system, 2026-09-14 (early morning)

Everything below is **local only**. Nothing has been restored to production.

## What to do first

1. **Upload the local database to production.** Take a fresh pre-restore dump first.
2. **Turn `datasheet_recheck_nightly` back ON.** It was disabled at 03:44 CEST.
3. Read section 9 below — the assumptions that need your eye.

## 9. The checks were split, scoped and measured

### The problem, in one number

Before tonight every judgment check was asked of every subject of its kind. A
two-pin ferrite bead was asked how its functional blocks were grouped. A
resistor was asked whether its NC pads were typed correctly. A power symbol was
asked whether it had been diffed against EasyEDA. The library carried roughly
**11,600 judgment questions**, and the answer to most of them was a sentence
saying the question did not apply.

Then 180 of those sentences were turned into standing exceptions, which made
the Exceptions tab read as if 186 real decisions had been made. **They were a
missing `when` predicate, written out 180 times.**

### What it is now

| | subjects | judgment questions | each | distinct checks |
|---|---|---|---|---|
| component | 442 | 3,184 | 7.2 | 15 |
| symbol | 207 | 2,003 | 9.7 | 28 |
| footprint | 213 | 2,603 | 12.2 | 18 |

**Live exceptions: 186 → 55.** 131 were revoked with a reason, because the
checks now say what they mean. Revoked, not deleted — `review_exceptions` is
append-only and the original notes stay readable as history.

### RULE — scopes added, each measured before it shipped

| Check | Was | Now | Scope |
|---|---|---|---|
| `sym.grouping` | 207 | 66 | an IC (`U*`) with ≥8 pins |
| `sym.pad_order_declared` | 207 | 66 | same |
| `sym.ground_placement` | 207 | 94 | an IC that draws rails |
| `sym.bus_sides` | 207 | 59 | a small IC, 5–16 pins |
| `sym.pin_types`, `sym.geometry` | 207 | 201 / 138 | draws ≥1 pin; and for geometry, has a rectangular body |
| `sym.nc_pads` | 207 | 40 | has an NC pin |
| `sym.topology` | 207 | 36 | D, Q, TR, K, RV, Y, L, F |
| `sym.hidden_names` | 207 | 22 | hides its pin names |
| `sym.easyeda_diff` | 207 | 166 | a purchased part is drawn on it |
| `sym.rail_polarity` + 2 siblings | 116 | 11 | the triangle families, by `comp_type` |
| `fp.jlc_land` | 213 | 176 | a purchased part sits on the land |
| `fp.silk_clear`, `fp.land_pattern`, `fp.pad_numbering` | 213 | 202 | has ≥1 numbered pad |
| `fp.npth_mechanical` | 213 | 68 | has a plated through-hole |
| `fp.model_fit` | 213 | 196 | references a model |
| `fp.cathode_bar` | 213 | 28 | a polarised family name |
| `fp.thermal_vias` | 213 | 15 | has a `pad_prop_heatsink` pad |
| `fp.mechanical_constraint` | name guess | 11 | **zero** numbered pads |
| `fp.rotation_offset` | 213 | 5 | actually carries an offset |
| `cmp.mpn`, `cmp.datasheet` | 442 | 431 | purchasable |
| `cmp.datasheet_is_document` | 442 | 413 | has an archive |

**Eleven judgment checks stay at 100% and should.** Every component has a
category and a base symbol; every footprint has an origin, a name, a tier, a
field order and a body outline.

### FOUND — two bugs the scoping exposed

- **`$electrical_props` counted `Reference` and `LCSC Part Class` as electrical
  data**, so every Hammond enclosure scored exactly 1 and was asked what its
  electrical values were. Nine exceptions existed only to answer that. Fixed.
- **`$electrical_props` EXCLUDED `Sim.Params`**, which is a claim about the
  part's electrical behaviour and can disagree with the datasheet like any
  other. Two parts had been flagged for exactly that — `TS24CA`'s `RON=50m`
  against its contact resistance, `UCC27538DBVR`'s `ROUTH=2.5` against its OUTH
  pull-up — and excluding `Sim.` put both out of reach. Fixed; the check now
  reaches 346 rather than 321.

### FOUND — two predicates I built, measured and threw away

Both looked right and would have created a silent gap. They are recorded in
`sym.pinout`'s own hint so nobody rebuilds them.

- **`$symbol_distinct_mpns = 1`** would have dropped `LE310X1` (94 pins) and
  `MAX3222E` (20 pins). They carry two part numbers only because two package
  variants share one drawing.
- **`$symbol_named_pins ≥ 1`** would have dropped `DF40C-100DS` (100 pins) and
  `FPC-05F-24PH20` (26 pins). A board-to-board connector is unnamed stubs and a
  very real datasheet numbering.

So `sym.pinout` keeps 25 exceptions. The check genuinely applies to every real
symbol; what varies is whether the answer is trivial. Same for `cmp.category` —
scoping it to "has an LCSC row" would have dropped 46 real parts, including
every Phoenix Contact connector.

### RULE — a pinless drawing now reports `0`, not nothing

`$symbol_pin_count` and `$footprint_pad_count` used to be **absent** both for a
drawing with no pins and for one that would not parse. A `when` cannot tell
those apart — an absent fact never matches — so scoping on it would have
silently stopped asking every judgment question of a **broken** file.

`parsed()` now separates them. A parsed drawing with no pins reports `"0"`;
only a broken one reports nothing. Six symbols and eleven footprints report
`0`, and `fp.mechanical_constraint` stopped guessing from the name.

## 10. JUDGED — `comp_type` on all 442 components

**364 had none.** They now carry one, across **94 distinct types**, and **385
still carry their verification** — see decision 0019 for why that was possible.

The classification is a reading of each part's own description, which came from
its datasheet title. The ones worth your eye:

- **ICs (107)** were classified individually: `LDO` ×13, `LOGIC` ×13, `DCDC` ×9,
  `DCDC_MODULE` ×4, `OPAMP` ×5, `MCU` ×5, `FLASH` ×4, `CELLULAR_MODULE` ×4,
  `BATTERY_CHARGER` ×3, `LED_DRIVER` ×3, `COMPARATOR` ×2, `FPGA` ×2, `SOC` ×2,
  and 30-odd singletons (`LNA`, `IMU`, `PMIC`, `VREF`, `FUEL_GAUGE`,
  `GATE_DRIVER`, `IO_EXPANDER`, `USB_SERIAL`, `ETHERNET_PHY`, …).
- **Everything else** was derived from the base symbol, which is mechanical:
  `R` → `RESISTOR`, `C` → `MLCC`, `CE`/`C_Polarized` → `ELECTROLYTIC`,
  `SW_Push*` → `TACTILE_SWITCH`, `Enclosure` → `ENCLOSURE`, and so on.
- **Connectors** needed the description as well, because one generic `Conn_*`
  symbol serves several kinds: "terminal block plug" → `TERMINAL_BLOCK_PLUG`,
  "terminal block" → `TERMINAL_BLOCK`, "pin header" → `HEADER`.

**One finding while classifying:** `M3535N1UVS8U12-365NM` is a 365 nm UV LED
filed under **ICs**. The skill records that UV emitters were moved to `LEDs` in
an earlier pass; this one was missed. I gave it `comp_type = LED` and left the
category alone — moving a category is a material edit and your call.

## 11. RULE — section 5 of `conventions-symbols` became nine checks

You asked why comparators and amplifiers were not checked. They were, in the
sense that **one** judgment item — `sym.drawing_family`, no scope, all 207
symbols — carried the whole of sections 5.1 to 5.7 in its hint. A reviewer
answering it for `TLV3201` was being asked seven independent questions at once.

It is now nine checks, each scoped through the new `$symbol_comp_types` fact:

| Check | Reaches | Asks |
|---|---|---|
| `sym.triangle_body` | 7 | the 15.24 mm triangle, to its coordinates |
| `sym.triangle_pins` | 7 | the five family pin positions, and the legal rail x |
| `sym.inverting_on_top` | 7 | the inverting input is the UPPER one |
| `sym.input_marks` | 7 | `−` and `+` graphic text, colour inside the font node |
| `sym.comparator_glyph` | 7 | a comparator has the step glyph, an amplifier nothing |
| `sym.gate_body` | 5 | the 10.16 mm gate triangle |
| `sym.qualifying_glyph` | 5 | the Schmitt marking drawn rising |
| `sym.angled_leader` | 11 | the leader slot for a spare pin |
| `sym.digital_block` | 7 | a flip-flop is a rectangle with visible names |

`sym.drawing_family` now asks only **which** family the part belongs in.

**`$symbol_comp_types` is the bridge.** `comp_type` lives on a component and a
drawing rule is about a symbol, so without it a rule could only be scoped by
geometry — which is how `TPD4E05U06`, an ESD array, was being asked about its
rail markers.

## 12. RULE — nine more custom keys became checks

| New check | Promoted from | Reaches | What it found |
|---|---|---|---|
| `sym.sourcing_defaults` | `custom:symbol_lcsc_part_risk` | 207 | **19 symbols** store an LCSC/Supplier/Manufacturer default the generator would inherit onto every component built from them. The custom key had found 2. |
| `sym.default_values` | `custom:visible-placeholder-value` | 201 | `R` draws `100R` and `L` draws `1mH`; KiCad stock draws `R` and `L`, values no real part can have |
| `cmp.exposed_pad_documented` | `custom:exposed-pad-not-in-the-datasheet` | 18 | two HGSEMI parts sit on a land with a 1.7 mm exposed pad their datasheet does not document |
| `cmp.range_end` | `custom:vbr-which-end-of-the-range` | 26 | the library stores min, typ and max of the same quantity on three different TVS parts |
| `cmp.no_footprint_deliberate` | `custom:footprint-missing-enclosure` | 14 | three Italtronic enclosures have a blank Footprint on purpose |
| `cmp.sim_numbers_read` | `conventions-simulation` | 94 | every `Sim.Params` number from THIS part's datasheet, with its condition |
| `cmp.sim_iq_per_channel` | | 94 | IQ per channel, not per package — four wrappers hold two blocks each |
| `cmp.sim_supply_current` | | 94 | the model actually draws from its rails |
| `cmp.sim_limitations` | | 94 | the header names what it leaves out; `;` not `$` |

## 13. The skills

| Skill | Was | Now |
|---|---|---|
| `conventions-footprints` | 1105 | **197** |
| `conventions-symbols` | 654 | **102** |
| `conventions-library` | 573 | **112** |

**4000 lines of skill across the library became 2079.** Each convention
document is now an index: how to publish, how to get the material, and a table
saying which check answers which question. The data — every number, decided
case, trap and worked example — moved into the check hints, where it is read at
the moment it is needed.

**Every cut was audited mechanically before publishing.** 127 distinctive
tokens from the footprint document, 94 from the symbol one, 173 from the
library one, each checked against the new text plus every check hint. That
found **16 pieces of evidence being dropped silently** and they went back.

## 14. FOUND — platform defects fixed on the way

- **A declarative check was throwing away its hint on save.** `_validate_items`
  generates the TEXT — correctly, so the sentence matches the comparison — but
  it dropped the author's hint too, which is where the reason lives. Six new
  checks had no explanation at all until this was fixed.
- **`docker compose exec api python /tmp/script.py` runs the WRONG CODE.**
  Python puts the *script's* directory on `sys.path`, not the working
  directory, so `app` resolves to a **stale copy installed in site-packages**
  — dated 3 September, with the pre-split datasheet model. It fails with
  `column datasheet_versions.content_type does not exist`, and the swallowed
  error poisons the transaction so every later call reports
  `InFailedSqlTransaction`. **Use `-e PYTHONPATH=/srv`.** This cost about an
  hour and produced ~330 published-but-unrecorded versions before it was found.
- **`machine_check_on_publish` still exists and still runs.** Decision 0017
  lists it as deleted. It is not. Worth a look — either the record or the code
  is wrong.

## 15. What needs your eye

**Assumptions I made that you should confirm:**

1. **The 94 `comp_type` values** — especially the 30-odd singleton IC types.
   The classification drives which rules a part is judged by.
2. **`M3535N1UVS8U12-365NM` is a UV LED filed under ICs.** Category unchanged.
3. **`Sim.Params` counts as electrical data** (`cmp.electrical` 321 → 346).
4. **Nine new judgment checks and nine new scopes** — the table in section 9.
5. **131 revoked exceptions.** Each carries a reason; none changed a review state.
6. **Decision 0019** — the carry rule now has a transition rule in it.

**Open, and NOT acted on:**

- **`cmp.range_end` has no house rule yet.** Three TVS parts store three
  different ends of the same published range. Each number is real. One decision
  settles the family.
- **`fp.shared_land_record` is asked of all 213 footprints** because nothing in
  the data says a land serves more than one designation. Dropped to a warning
  rather than given an invented scope.
- **A SIM MODEL is not a review subject.** 58 models exist and none can be
  verified directly; the four new sim checks attach to the 94 components that
  carry the parameters instead.
- **The pad-placement grid still has no check.** Measuring found the stated rule
  is wrong for **76 of the 150** coarse-pitch footprints: a 1.27 mm SOIC puts
  pads at ±0.635, a two-row 2.54 mm header puts rows at ±1.27. The honest check
  measures the across-edge axis only, and it does not exist yet.

## 16. RULE — two more skills, and one rule nothing was enforcing

`add-component`'s "Get these right BEFORE you publish" was a second copy of
eight machine checks. It now points at the checklist and keeps only the three
facts a check cannot tell you: mirror a sibling rather than guessing which
properties a category needs, template resolution is order-independent, and an
unresolved `{Footprint_Name}` is the DEFAULT outcome of pairing a new component
with a new footprint — not a rare mistake.

`conventions-simulation` gave up four sections to the checks and gained an
honest note about what is still unreachable.

**FOUND — the 200-character property limit was enforced by nothing.**
`add-component` has stated it since the beginning, and the old rule block
carried `max_property_length` in `_RULE_KEYS_UNUSED` — the list of keys the
retired engine held that no check consumes. `cmp.property_length` now consumes
it. Clean across all 442 components, so it is a guard on the next import.

**Skills, end to end:**

| Skill | Was | Now |
|---|---|---|
| `conventions-footprints` | 1105 | 197 |
| `conventions-symbols` | 654 | 102 |
| `conventions-library` | 573 | 112 |
| `conventions-simulation` | 490 | 417 |
| `add-component` | 354 | 354 |
| **total across all eight** | **4000** | **2006** |

`platform-workflow` (296) and `verify-datasheets` (145) were left alone: they
describe how the PLATFORM behaves, not what a part must satisfy, and there is
nothing in them for a check to hold.

## 17. Where the library stands

**306 machine failures** across 862 subjects, of which 216 are warnings. The
error-level ones worth a morning look:

```
 66  fp.courtyard_grid        coordinates off the 0.1 mm grid
 25  cmp.datasheet_text       archived datasheet has no text layer
 15  fp.model3d               no 3D model referenced
 14  cmp.property_values      value does not match the category pattern
 11  cmp.required_props       a required property is missing or empty
  5  fp.courtyard_present     no F.CrtYd at all
  5  cmp.description          description is not one of the category templates
```

**55 live standing exceptions**, each a real decision.

**7,790 judgment questions** across the library, down from roughly 11,600 —
and every one of them is now asked of a part the question is actually about.

# Part 3 — CE_Dongle_V3 as a test of the check system

57 distinct components, walked one by one. The point was not to produce
verifications — it was to find out where the checks are wrong, and they were
wrong in eight places.

## 18. FOUND — a startup migration was silently reverting checklist edits

The worst of the eight, and it would have quietly undone work indefinitely.

`checklists.migrate_rules_onto_items` re-stamps every CATEGORY checklist from
the retired `rules` table on **every startup**. The BASE checklist path passes
`only_missing=True` with a comment saying exactly why — "a base item that
already states its params keeps them: this has run before, or somebody has
edited one since" — and the category path passed `only_missing=False`.

Measured: removing a bad pattern from `cmp.property_values` on Inductors
published v4. The next uvicorn reload published **v5, with the pattern back and
the comment of v1.** Fixed to `only_missing=True`; the migration now publishes
nothing on a second run.

**A migration that undoes the thing it migrated to is worse than one that never
ran.** Anyone who edited a category checklist before today and found it
reverted was not imagining it.

## 19. FOUND — `Value` had two owners and only one knew what the part was

`cmp.value_field` splits by `comp_type`. `cmp.property_values` also carried a
`Value` pattern, per category, that did not. They disagreed on five parts and
`cmp.property_values` was wrong every time:

| Part | Stored | Failed against |
|---|---|---|
| `BLM18EG101TN1D` | `100Ω@100MHz` — the correct ferrite-bead impedance | an inductance pattern |
| `HX1188NLT`, `ETA17208` | the correct transformer MPN | the same |

`Value` is removed from `cmp.property_values` on all four categories that
carried it. One field, one owner.

Worth noting what this uncovered: `conventions-library` had recorded
`BLM18EG101TN1D` as an OPEN question — "`Value = 68nH` while its Impedance
reads `100Ω@100MHz`". Somebody had already fixed the part to the rule. The
check was the thing still wrong.

## 20. FOUND — checks demanding what a part cannot have

- **An addressable RGB LED has no single `Color`, `Forward Current` or
  `Forward Voltage`.** `cmp.required_props` on LEDs demanded all three, and
  `WS2812E-1313` and `WS2816C-1313` failed for it — while the skill's own
  "deliberately left as free text" list already said RGB multi-die parts have
  per-channel ratings and no single one. Split into three `comp_type` variants:
  single-die keeps all three, multi-die keeps `Color` and `Forward Current`, an
  addressable LED or 7-segment display keeps neither.
- **Five parts failed `cmp.description` against a template**, and all five are
  on that same free-text list: `PTF-77`, `SM712`, `NCP15XH103F03RC`,
  `XL-1615RGBC-RF`, `SX3M25.000M20F30TNN`. Four are discriminated by
  `comp_type` and became a `Free text` variant. The fifth, `SM712`, is not:
  nothing in the data separates an asymmetrical dual-channel TVS from the
  symmetric ones that DO take the template — `comp_type` is `TVS` for both. It
  took a standing exception, which is what an exception is for.

**Four fixed by rule, one recorded as a decision.** That split is the system
working as designed.

## 21. FOUND — my own sim checks were over-broad

`cmp.sim_iq_per_channel` and `cmp.sim_supply_current` were asked of all 94
components carrying `Sim.Params`. **57 of them have no supply pins at all** —
every diode, MOSFET, Zener, TVS, LED, relay, optocoupler and tactile switch.
`TS24CA`, whose entire model is `STATE=0 RON=50m`, was being asked about its
quiescent current per channel.

Scoped to `$symbol_power_pins ≥ 1` — 37 parts. `cmp.sim_numbers_read` and
`cmp.sim_limitations` still reach all 94, correctly: a diode's `IS` and `BV`
must still come from its own datasheet, and the model must still say what it
leaves out.

## 22. FOUND — a question asked 413 times that another check already asked

`cmp.datasheet_is_document` was a judgment on every component with an archive.
Measured: **all 416 archived documents are PDFs**, and the remaining three are
STEP and DXF drawings, which are legitimate. The HTML-page defect that spawned
it — recorded under THREE different `custom:` spellings — is extinct.

Its mechanical half is a content type, so it is now a machine check and a guard
on the next fetch. Its judgment half — *is this the right document for this
exact part* — is `cmp.datasheet`'s question and always was. **413 open judgment
questions removed without losing anything.**

## 23. RULE — `sym.should_stack`, the half `sym.stacked` could not ask

From an agent's flag on `KH-IPEX-K501-29`: `Conn_IPEX` draws a U.FL jack's
ground as two separate pins both named `Ext`, while the datasheet's own
schematic shows two connections and its bill of materials lists one signal
contact and one ground contact.

`sym.stacked` is scoped to a symbol that ALREADY stacks, so it asks whether the
stacking is right and never whether a part SHOULD have stacked.

Getting the fact honest took three passes, and each one is recorded in the hint:

| Counting | Finds | Why it is wrong |
|---|---|---|
| any same-named pins on different points | 40 symbols, 144 on one FPGA | a large IC's redundant GND/VDD pads are separate ON PURPOSE |
| ...excluding supply pins | 25 symbols, 69 on `LE910R1` | 70 pads named `RESERVED` are not one reserved net |
| ...excluding names that claim no net | **7 symbols** | — |

All seven are real questions: `HSBB6115` (`D` and `S` — a discrete's multi-pad
terminal, which the owner decision says IS stacked), `TPS6302X` (`L1`, `L2`),
`USB-B01` (`GND` three times, **and typed as a signal rather than `power_in`** —
two defects in one), `USB_C_Receptacle_USB2.0_16P` (`D+`/`D-`, which the
receptacle really does short across A6/B6), `Conn_IPEX`, `LED_CAA` and
`M3535N1` (a common-anode LED's two anode pads).

## 24. RULE — `TOGNJING` was `TONGJING`, and the evidence was in the archive

An agent had flagged `XTM32040000FT00351001`'s manufacturer as misspelled.
Verified directly: the archived XTM-Series(3225) datasheet prints
**`www.hftongjing.com`** in its own page footer. `TOGNJING` transposes G and N.

The skill had recorded that entry as LOWER CONFIDENCE with the words "no
manufacturer homepage was ever located — re-check if a better source turns up".
The archive was the better source the whole time.

`cmp.manufacturer_canonical` now holds `TONGJING`, and the part shows as a
warning until somebody corrects it — which is a MATERIAL edit and costs the
verification, so it is your call.

## 25. RULE — 33 verifications restored

Six Dongle components carried no review record. Tracing the history showed they
lost it to **last night's `comp_type` edits, made before decision 0019 existed**.
Today's 323 kept theirs.

`review.carry_component` re-checks `data_carries`, which now has the
classification rule, and refuses if a record already exists — so it was safe to
re-run across the library. **33 carried; 24 were blocked, and every block is a
real material change**: the `Zenner` → `Zener` property-key rename, a changed
`Manufacturer 1`, a removed `LCSC Part`, a changed `Value`.

**Components carrying a verification: 385 → 418 of 442.**

## 26. Where CE_Dongle_V3 stands

```
57 components   3 errors   3 warnings   4 flags   3 with no record
```

**The 3 errors are all `cmp.datasheet_text`** — `FTC404030S4R7MGCA` (61-page
scan), `CS3225X7R476K160NRL` (40-page scan) and `RC01812` (1-page scan). All
three are genuine image-only PDFs with zero text pages, so `read_datasheet`
returns nothing for them. Real, and they need a manufacturer text PDF.

**The 4 flags are open defects somebody found and could not fix:**

| Part | Flag |
|---|---|
| `KH-IPEX-K501-29` | `Conn_IPEX` has 4 distinct pins; the datasheet has 2 connections — now also caught by `sym.should_stack` |
| `XTM32040000FT00351001` | the manufacturer spelling, resolved above; also, the series datasheet never prints the orderable part number |
| `TS24CA` | `Sim.Params` `RON=50m` against the datasheet's published contact resistance |
| `CS3225X7R476K160NRL` | the datasheet itself |

**99 judgment items remain open across the 57**, most of them because a check
was added today (`cmp.range_end`, `cmp.exposed_pad_documented`, the four sim
checks) and nobody has answered it yet. Answering them is per-part datasheet
work and it is not done. The counts are `cmp.category` 14,
`cmp.base_symbol` 14, `cmp.electrical` 13, `cmp.mpn` 12, `cmp.datasheet` 11,
`cmp.sim_numbers_read` 11, `cmp.sim_limitations` 11, `cmp.description` 10,
`cmp.range_end` 4, `cmp.exposed_pad_documented` 3, and one each of the two
scoped sim checks.

**Library-wide machine state: 147 errors, 156 warnings** across 862 subjects.

## 27. Every CE_Dongle_V3 component is now answered

All 57 walked, every judgment item answered against the part's own
documentation. **41 read `checked`; 16 read `failed`, and every one of those is
a real defect somebody has to decide on.**

### Electrical values that do not match the datasheet

| Part | Stored | Datasheet |
|---|---|---|
| `SI2319A` | RDS(ON) **70mΩ**@10V | p2 table: max **50 mΩ** at VGS=-10V, 55 mΩ at -4.5V |
| `SI2308A` | RDS(ON) **82mΩ**@10V | p2 table: typ 65, max **80 mΩ** at VGS=10V |
| `AON7264E` | Power **27W** | p1: PD 27.5W at TC=25°C, 11W at TC=100°C, PDSM 5.0W at TA=25°C — 27 is none of them |

`AON7264E`'s description carries the same 27W, so it inherits the error. Its
`Sim.Params` is worse: `RDSON_ADJ=4m` against a published 9.5 mΩ at VGS=10V.

### The range-end question, answered on four parts

`cmp.range_end` was added this session because three TVS parts stored three
different ends of one published band. Walking this BOM found a fourth
convention and settled two more parts:

| Part | Stores | Which end |
|---|---|---|
| `SMAJ28A` | `Voltage - Breakdown` 34.4V | the **MAX** of VBR 31.10–34.40 — while its own `Sim.Params` carries `BV=32.7`, the **midpoint** |
| `TPD4E05U06DQAR` | `Voltage - Breakdown` 6.5V | the **MIN** of VBR 6.5–8.5, which is also how TI headlines it on p1 |
| `BZX384-C12`, `-C3V6` | `Zener Voltage` 12V / 3.6V | the **NOMINAL** series index — neither end of 11.40–12.70 |

So the library holds min, typ, max and nominal for the same kind of quantity.
`SMAJ28A` is the sharpest case: one part, one quantity, two different ends, in
two fields. **A single decision settles the family and nobody has made it.**

### Simulation models say nothing about what they leave out

`cmp.sim_limitations` is flagged on nine parts and it is the same finding every
time: the `Sim.Params` row carries numbers and no statement of scope. The ones
that matter:

- **`SMAJ28A`** — a TVS modelled as a static Zener. The p2 row's whole point is
  `IPP 8.8 A` at 10/1000 µs, and the model has no surge behaviour at all.
- **`TPS7B6950QDBVRQ1`** — a 40 V automotive LDO modelled as a voltage source
  with a series drop: no dropout below its 5.5 V minimum input, no thermal
  shutdown, no current-limit foldback, no PSRR.
- **`LTST-C281KRKT`** — a simulation of this part gives the current through it
  and nothing about whether it lights, which is the only reason it is fitted.

`TS24CA` is the counter-example and was answered `checked`: `STATE` plus `RON`
IS the complete behaviour a circuit simulation needs from a tactile switch.
**The check is not a demand for boilerplate.**

### What the walk confirmed rather than found

- **`PCF8574RGTR`'s exposed pad IS documented** — but in section 14.2, titled
  "WQFN-16-**EP**(3x3) Package Outline Dimensions", *not* in the pin table,
  which lists only pins 1 to 16. Reading the pin table alone would have called
  the 17th pad undocumented. That is exactly the trap the check exists for.
- **`ESP32-C6`** documents it properly, as a numbered pin: Table 2-1 ends
  `41 | GND | Power`, and the p14 diagram prints `41 GND` at the centre.
- **`TXS0104ERGYR`** labels "Thermal Pad" in its p6 RGY pin diagram.

### Two parts could not be verified from their archive

`FTC404030S4R7MGCA` (61-page scan) and `CS3225X7R476K160NRL` (40-page scan)
have zero text pages — `read_datasheet` returns nothing. Both were verified
against their **LCSC product page** instead, which this check's own text allows,
and both agree with what is stored. The datasheets still need replacing, which
is what `cmp.datasheet_text` reports.

### The 400-character note limit did its job twice

Two of my own notes were over it. `record_check` reported them in `blocked` and
wrote everything else — my recorder script printed only `refused`, so I nearly
shipped two items as answered when the platform had correctly declined them.
**The limit works; read the whole report.**

### Library-wide effect

Answering these did not touch any other part. What did: **418 of 442 components
now carry a verification** (was 385), and the CE_Dongle_V3 BOM has **no
component without a review record** for the first time.

## 28. The wrong values are fixed

Six corrections, each published as its own version with the datasheet evidence
in the version comment, then **re-verified from the same evidence** — a property
edit is material, so it strips the verification, and the rule is that whoever
changes the number answers the question again.

| Part | Field | Was | Now | Source |
|---|---|---|---|---|
| `SI2319A` | `Drain Source On Resistance` | 70mΩ@10V | **50mΩ@10V** | p2 table, max at VGS=−10V |
| `SI2308A` | `Drain Source On Resistance` | 82mΩ@10V | **80mΩ@10V** | p2 table, max at VGS=10V |
| `SI2308A` | `Sim.Params` `RDSON_ADJ` | 65m (the typ) | **80m** | so model and property agree |
| `AON7264E` | `Power` | 27W | **27.5W** | p1, PD at TC=25 °C |
| `AON7264E` | `ki_description` | …27W… | **…27.5W…** | inherited the same error |
| `AON7264E` | `Sim.Params` `RDSON_ADJ` | 4m | **13.3m** | p1, RDS(ON) at VGS=4.5V |
| `TS24CA` | `Sim.Params` `RON` | 50m | **100m** | CONTACT CIRCUIT, 100 mΩ max |
| `TS3625A` | `Sim.Params` `RON` | 50m | **100m** | same sheet, same defect |
| `XTM32040000FT00351001` | `Manufacturer 1` | TOGNJING | **TONGJING** | www.hftongjing.com, the datasheet's own footer |

### How the ambiguous ones were decided

**`AON7264E`'s power** had two candidates — 27.5 W at TC=25 °C and 5.0 W at
TA=25 °C — and the stored 27 W was neither. The library settled it rather than a
guess: `CSD17577Q3A` stores 53 W and `BSC0702LS` stores 83 W, both
case-referenced figures for the same package class. 27.5 W it is.

**The tactile switches.** `TS3625A` is not on this BOM, but it carries the
identical defect from the identical ShouHan sheet, and the XKB `TS-1102S`
siblings already store the correct 100m. Fixing only the Dongle part would have
left exactly the "a family-wide deviation defends itself" trap
`conventions-library` warns about, so both were corrected in one pass.

### One that could NOT be fixed on the component

**`SI2319A` cannot carry its on-resistance at all.** `sigma_pmos` declares
`VTO`, `KP`, `LAMBDA`, `CGS` and `CGD` and **no `RDSON_ADJ`**, where
`sigma_nmos` does declare one. So the simulated on-resistance of every P-channel
part in the library is whatever the generic block produces, and the datasheet's
50 mΩ cannot reach it. Adding the parameter to `sigma_pmos` is a MODEL change,
not a component one, and it is not done — recorded on the part's
`cmp.sim_numbers_read` flag.

### Where CE_Dongle_V3 stands now

```
57 components   42 checked   15 failed   0 open   0 without a record
3 errors (all cmp.datasheet_text)   2 warnings   14 flags
```

**Library-wide: 421 of 442 components carry a verification record**, and
component machine failures are down to 73, of which 26 are warnings.

The 14 remaining flags are no longer wrong values. They are:

- **`cmp.sim_limitations` ×8** — models that carry numbers and no statement of
  scope. Fixing these means editing model headers, not component data.
- **`cmp.sim_numbers_read` ×4** — fitted values not labelled as fitted.
- **`SMAJ28A` `cmp.range_end`** — waiting on the library-wide min/typ/max/nominal
  decision.
- **`KH-IPEX-K501-29` `cmp.base_symbol`** — `Conn_IPEX` needs redrawing.
- **`XTM32040000FT00351001` `cmp.mpn`** — the series sheet never prints the
  orderable number. Unverifiable from the manufacturer's own material.
- **`CS3225X7R476K160NRL`, `FTC404030S4R7MGCA` `cmp.datasheet`** — image-only
  scans that need a text PDF.

## 29. `Crystal_GND24_Small` — both ground pins stay visible

`sym.should_stack` fired on this symbol: pins 2 and 4 are the case shield, one
net inside the part, drawn as two separate pins. KiCad stock stacks them; the
three EasyEDA vendor symbols for parts on this drawing do not.

**Owner decision: both stay VISIBLE, for this symbol.** Drawing both means the
designer wires both and neither pad can be left floating. Recorded as a standing
exception on the symbol — **not** generalised into a rule, because whether a
passive ground pad should stack is a decision per part.

The check still asks. A shield or case pad is typed `passive` rather than
`power_in`, so the supply-type exclusion does not hide it, and that is
deliberate. `sym.should_stack` finds 7: `Conn_IPEX` (`Ext`), `HSBB6115`
(`D`, `S`), `TPS6302X` (`L1`, `L2`), `USB_C_Receptacle_USB2.0_16P` (`D+`, `D-`),
`USB-B01` (`GND`), `LED_CAA` and `M3535N1` (a common-anode LED's two anode pads).

### Two fixes on the way there

**`sym.pin_length` was failing a stock drawing.** It compared stub lengths
across the WHOLE symbol, and `Crystal_GND24_Small` is byte-identical to KiCad's
`Device:Crystal_GND24_Small`, which uses 1.27 mm on its left and right terminals
and 0.635 mm on its top and bottom grounds — because the glyph body is 1.5 mm
wide and 3.0 mm tall, so equal lengths would put the pin tips off the drawing.

The rule's own words are *"it puts the pin ends on two different vertical
lines"*, which is about pins on the SAME edge. The test is now **per edge**.
Library-wide failures: 1 → 0.

**The crystal's pins were named by their own numbers.** `"1"`, `"2"`, `"3"`,
`"4"` — where KiCad stock names the grounds `G` and three EasyEDA vendor symbols
for parts on this same drawing all name them `GND`. Renamed to `GND` (names
only; numbers, positions, count and types untouched, which is the line the
convention draws).

That rename is what let `sym.should_stack` see the duplicate at all. The blind
spot is worth knowing: **a pin named after its own number carries no net claim,
so no name-based check can reach it.** It is recorded on the check.

## 30. `TS24CA` — a pad named `MP` is not a missing pin

The task was to shorten the verification notes on all three subjects and clear
what was left open. Two of the three findings underneath were the review system
being wrong about its own conventions.

**`cmp.pads_to_pins` fired on its own fix.** The TS24CA's two frame tabs were
numbered `3` and `4`; the owner renamed them `MP` on 2026-09-13 so that no net
could ever reach them. The next read reported *"$pads_without_pins is 1"* — a
pad the symbol does not draw. The rename IS the fix, and the check counted it as
the defect.

`MP` (hold-down) and `SH` (shield) are KiCad's own names for a pad that is not a
net: the shipped library uses `MP` in six files and `SH` in 359 pads, and no
symbol pin may carry a name a pad number cannot be. `$pads_without_pins` now
subtracts them.

| | before | after |
|---|---|---|
| components failing `cmp.pads_to_pins` | 13 | 9 |

The four that left were `TS24CA`, `TC-6615-9.0-160G` (both `MP`) and the two
Phoenix Contact bus connectors (`SH`). The nine that stay are all NUMBERED pads
the symbol does not draw — an exposed pad, an NC lead, a second antenna
terminal — which is the question this check exists to ask.

**The package name still described the part before the rename.** `SMD-4P
4.7x3.5x2.25mm Right-Angle`: four electrical positions where the drawing gives
two terminals 3.35 mm apart and item 4 of the specification says *"Monople
loop"*, and right-angle where the part is top-actuated. Its TS3625A sibling —
also two terminals — reads `SMD-2P 6.1x3.7x2.5mm`. Corrected to **`SMD-2P
4.7x3.5x2.25mm`**. Unversioned: no footprint version, no copper, the Buttons
library rebuilt.

**The footprint was held at `failed` by a flag its own rename had answered.**
`custom:name-says-4P-but-two-pads-are-electrical` was raised while the name read
`-4P`; version 5 renamed it to `-2P-2MP` the same day and nobody closed the
flag. This is the shape worth remembering: **an off-checklist `custom:` key is
cumulative and nothing retires it.** A checklist item can be switched off and
`record_check` drops its answer; a `custom:` key is copied forward for ever.

Ten judgment items had never been answered and are now: `fp.one_land_per_package`,
`fp.tier`, `fp.field_order`, `fp.jlc_land`, `fp.shared_land_record`,
`fp.silk_clear`, `sym.drawing_family`, `sym.fp_filters`, `sym.easyeda_diff`,
`sym.pin_numbers_unchanged`.

Two are worth quoting because they are second opinions that disagreed with us
and lost:

- **`sym.easyeda_diff`** — `easyeda2kicad --lcsc_id=C393942` draws **four**
  pins. The datasheet gives two terminals and JLC's own land gives the tabs
  0.01 × 0.01 mm marker pads, i.e. no copper. EasyEDA's symbol contradicts
  EasyEDA's land. Pin numbers 1 and 2 agree, which is the part that matters.
- **`fp.field_order`** — the standard writes **one group per type regardless of
  physical count** (§289: stock has no `-2MP` anywhere), so the name should read
  `-2P-1MP`. **Not renamed.** The name describes the geometry correctly and a
  rename costs somebody a board update; this is exactly what `fp.naming` refuses
  to rename for. Recorded on the item instead.

### Notes rewritten, nothing re-decided

Every result is unchanged. The longest note in the library was
`fp.land_pattern` at **2,368 characters**; it is now 234, and the owner's
accepted-deviation decision, the three measurements and the "do not correct
this" instruction all survive. The finding it replaced is still on `superseded`,
in full, which is where history belongs.

| subject | before | after |
|---|---|---|
| `TS24CA` | checked, 1 warning | checked, 0 warnings |
| `SW_Push` | partial, 4 open | checked |
| `SW_Push-2P-2MP_…_TS24CA` | **failed**, 6 open | checked |

### Two things this could not do

- **A stored `na` answer's note cannot be shortened.** Re-answering `na` above
  the machine tier GRANTS A STANDING EXCEPTION rather than updating the record
  (`review.record_check`), so the old text stays. Three long `na` extras on
  `SW_Push` are untouched for that reason. A standing exception itself has no
  edit path either — `sym.pinout` had to be revoked and re-granted (#83 → #192)
  to shorten its note, which is honest but costs the original date.
- **The MCP server points at PRODUCTION** (`KICAD_API_URL` is
  `https://disfunction.cc/lib`). Every write in this pass went to the local
  database through the service layer. `read_datasheet` was used and is a read —
  but it does populate production's datasheet cache, so it is not free of
  effect.

## 31. RULE — a scope that says what it means

`cmp.sim_iq_per_channel` ("IQ is per CHANNEL, not per package, and the
arithmetic is written down") and its twin `cmp.sim_supply_current` were scoped
by:

```
when: {"Sim.Params": "^.+$", "$symbol_power_pins": "^[1-9]"}
```

That is a PROXY. It asks how a symbol happens to type a pin, and what the rule
means is "this part has a die that draws current from a rail". The two agree on
every one of the library's 442 components — the 37 the check reaches are all
LDOs, logic, op-amps, converters and the like, and not one transistor,
capacitor or diode is among them.

They will not keep agreeing. **`TPD4E05U06DQAR` is a TVS array whose symbol
draws two rails.** It carries no `Sim.Params` today; the day it gains one, the
check asks a passive protection array to divide its quiescent current by its
channel count. Nine parts in the library are in that position.

### The fact, not the regex

The first attempt said it with a negative lookahead on `comp_type`, which works
and is 265 characters long — and the review card prints an item's scope in its
tooltip, so every transistor would have carried that wall of text under "n/a
here". The second attempt is a fact:

```
when: {"Sim.Params": "^.+$", "$symbol_power_pins": "^[1-9]", "$powered_die": "^true$"}
```

`$powered_die` reads `checklists.NO_QUIESCENT_CURRENT`, where the 30 families
sit in five commented groups — discrete semiconductors, passives, emitters and
opto, contacts, and the house simulation stand-ins. **The list is of what is
EXCLUDED, and that direction is the whole point.** A new IC type keeps the check
by default; a positive list of active families would let it escape in silence.
Being wrong the other way costs one question that answers itself in a line.

Two calls inside it worth stating, because they are not obvious from the name:

- **`ADDRESSABLE_LED` is NOT excluded.** A WS2812 carries a controller die and a
  real supply current. `LED`, `RGB_LED` and `SEVEN_SEGMENT` are.
- **`VREF` and `OSCILLATOR` are NOT excluded.** A shunt reference draws
  60 µA–15 mA and a CMOS oscillator runs off VDD. Only `CRYSTAL`, the passive
  resonator, is out.

An unclassified part returns ABSENT rather than `true`, so the check skips it —
the right way round, because no `comp_type` is not evidence that a part has a
supply current.

### Not a skill change

The scope stayed out of `conventions-simulation`. Its section is already headed
"An IC draws its supply current. Make it.", and the machine-readable half
belongs on the check's own hint, which is where sections 9-24 of this report
spent the day moving such rules.

## 32. RULE — a triangle rule needs a triangle

The question was whether "The body is the 15.24 mm triangle" could be reaching
logic gates, which use a smaller one. It is not. Measured across every symbol in
the library, the two families are disjoint:

| Family | Body | `when` | Symbols |
|---|---|---|---|
| Analog triangle | 15.24 mm, `(-7.62, ±7.62)` → `(7.62, 0)` | `comp_type` = `COMPARATOR\|OPAMP` | 6 |
| Gate triangle | 10.16 mm, `(-5.08, ±5.08)` → `(5.08, 0)` | `comp_type` = `LOGIC`, no box | 5 |
| Digital block | rectangle, names visible | `comp_type` = `LOGIC`, box | 7 |

`74LVC1G17` — a Schmitt BUFFER, the case in the question — sits on `sym.gate_body`
at 10.16 mm, correctly. No logic part is asked for the 15.24 mm body and no
analog part for the 10.16 mm one.

### What the check DID find

The five analog checks — `sym.triangle_body`, `sym.triangle_pins`,
`sym.inverting_on_top`, `sym.input_marks`, `sym.comparator_glyph` — were scoped
by `comp_type` ALONE. Their gate-family counterparts have carried
`$symbol_has_box` from the start (`sym.gate_body` demands `false`,
`sym.digital_block` demands `true`). So an analog part drawn as a box still got
the full triangle geometry list.

**`ADA4945-1` is that part.** It is a fully-differential amplifier with 17 pins:

```
+IN -IN   VOCM   +OUT -OUT   +FB -FB   MODE  ~DISABLE
+Vclamp -Vclamp   +Vs ×2   -Vs ×3   DGND
```

Five triangle pins cannot draw that, and a box is the right answer — so it was
being asked five questions with no correct answer, none of which it could pass
by fixing anything. Its judgment list is 15 items → 10, and `sym.drawing_family`
stays open, which IS the question for it: is a box right here?

### The division the family checks rest on

`sym.drawing_family` decides WHICH family a part belongs in. The geometry checks
measure the family once chosen. Each one therefore needs both halves of its
scope — what the part is, AND what it is drawn as — or it asks a part to satisfy
a geometry its own family does not use. Only the analog five were missing the
second half.

### One gap left, deliberately

A symbol shared by components of two different types resolves
`$symbol_comp_types` to `"LOGIC,OPAMP"`, which matches neither `^(COMPARATOR|OPAMP)$`
nor `^LOGIC$`, so it would get no family geometry check at all. No such symbol
exists today. Worth knowing before somebody draws one.

### And the check that was actually on the transistor

`AO3400A` is a MOSFET, and the item on its symbol `Q_NMOS_GSD` was not a
triangle check at all — it was **`sym.drawing_family`**, whose hint is the one
that names the three sizes. That check carried **no `when` at all** and reached
**all 207 symbols**: every resistor, diode, crystal, connector, mounting hole
and logo was being asked which of the 15.24 mm triangle, the 10.16 mm gate
triangle and the box it belonged in.

None of the three is an answer for a MOSFET. Its drawing is the standard
pictogram, fixed by convention, and there is no family to pick.

New fact **`$symbol_family_choice`**, over `checklists.FIXED_PICTOGRAM` — 53
`comp_type` values in five commented groups:

| Group | Examples |
|---|---|
| discrete semiconductors and emitters | `NMOS` `DIODE` `ZENER` `LED` `OPTOCOUPLER` |
| passives | `RESISTOR` `MLCC` `INDUCTOR` `CRYSTAL` `FUSE` |
| contacts | `TACTILE_SWITCH` `SIGNAL_RELAY` `DIP_SWITCH` |
| connectors and pin rows | `HEADER` `TERMINAL_BLOCK` `RJ45` `USB_RECEPTACLE` |
| mechanical and non-electrical | `MOUNTING_HOLE` `ENCLOSURE` `LOGO` `TESTPOINT` |

```
sym.drawing_family:  207 symbols  ->  98
```

Everything left is an IC or a module, where box-versus-triangle is a real
decision. Two behaviours worth stating:

- **A symbol no component carries a `comp_type` for returns ABSENT**, so a power
  flag or a bare graphic is skipped as well — an absent fact never matches.
- **A shared symbol keeps the question if ANY of its components has a choice.**
  That is the safe direction on a drawing two families share.

`SW_Push` and `Crystal_GND24_Small` keep the answers recorded earlier today;
the key simply leaves their denominator and shows as an extra. Both still read
`checked`.

### Every other judgment check was surveyed for the same fault

`sym.drawing_family` was the only one. The remaining unscoped judgment items are
genuinely universal — `cmp.description`, `cmp.category`, `cmp.base_symbol`,
`cmp.value_field`, the seven `fp.*` naming and geometry items, and
`sym.pin_numbers_unchanged`. Every component has a category; every footprint has
a name and an origin; every symbol version either changed its pin numbers or did
not.
