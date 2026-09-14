# What I decided overnight, for you to confirm — 2026-09-14

Everything below was done on a **local copy of production**, restored from
`kicadlib-20260914-014453.dump`. Nothing reaches production until the copy is
uploaded back, so any row you reject can simply be undone before that.

**Two things to do regardless of what you decide here:**

1. `datasheet_recheck_nightly` is **OFF** on production, disabled at 03:44 CEST
   so the nightly job could not write during the snapshot window. It must go
   back on.
2. Restore this copy to production, or discard it.

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

