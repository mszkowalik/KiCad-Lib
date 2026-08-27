---
name: kicad-conventions-footprints
description: "Choosing AND authoring footprints, and the naming standard: the KLC tier rule (Tier 0 stock names are frozen), the twelve-slot field order, decided spellings (_HandSoldering, vendor tokens, no rotation in names), the 7Sigma: namespace, validator-enforced pad/silk/fab/courtyard style, the 0.1mm grid, NPTH mechanical holes, thermal vias, non-electrical parts, and why connector pad numbering always follows the datasheet. Use when naming, picking or authoring any footprint."
---
<!-- platform-skill: conventions-footprints v25 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Footprint conventions

Footprints live in the `7Sigma:` namespace and are always referenced as
`7Sigma:<name>`. You can both *choose* an existing footprint and *author* a new
or revised one: `propose_footprint_edit(name, source_text, comment)` takes a
complete `.kicad_mod` text and **publishes it immediately** (existing name =
edit, new name = creation). There is no draft gate and no Proposals view: the
mirror and the KiCad libraries update on the call, a machine validation record
is written, and the version starts UNREVIEWED on the review axis. Render it and
check it BEFORE you call, not after.

Never hand-write a footprint from scratch when something close exists: call
`get_footprint` first, take its `source`, and edit that.

**Publishing a footprint version also repoints every component on it.** A
component pins the footprint *version* it was drawn against, so the platform
publishes a new component version for every name in `used_by_components`, pinned
to the new drawing with properties unchanged. That happens automatically — the
response's `repointed` block lists what moved. See [[platform-workflow]].

## 1. Choosing a footprint

### Two different jobs: creating a footprint, and checking one that exists

**Creating a new footprint → import it from JLCPCB/EasyEDA.** Pull the exact LCSC
part with `easyeda2kicad --lcsc_id=C<number> --full --output ./easyeda_tmp`, then
run it through the import checklist in §10 and name it per §2. `--full` also
fetches the 3D model, and **for a new footprint you take EasyEDA's model too** —
it is drawn to the same land, so it aligns. (Still measure its bounding box before
setting the offset: §10 and the EasyEDA meshes are frequently z-centred.)

**A footprint that already exists → COMPARE, do not replace.** Pull the JLC land
anyway and diff it, but record what you find in the verification notes rather than
redrawing. Two reasons: a lot of this library is deliberately hand-drawn (see
"House-prepared footprints" below), and silently republishing geometry under
someone's feet repoints every component on it.

Escalate to the user, do not fix, when the diff shows:
- **different pad numbering or pad ordering** — this one changes netlists
- a different pad count, or an exposed pad present in one and absent in the other
- the body on a different side of the pins, or a different pitch
- anything you cannot explain from the datasheet

Note in the record and move on when the diff is only: pad size within a few tenths,
silk or courtyard width, fillet style, or text placement. Those are house style and
§4 already governs them.

The only exception is an explicit instruction from the user to replace a specific
footprint — as with `Converter_DCDC_YLPTEC_B2415S-1WR3_THT` on 2026-08-24, whose
body was mirrored about the pin row.

### Reusing a land for a NEW part — annotate, never re-cut

When a new component reuses a footprint that already exists, **do not edit that
footprint to match the new part's datasheet.** Not by a tenth of a millimetre, not
to add its exposed pad, not to widen a pad for its lead. The land was drawn and
verified for the parts already on it, and re-cutting it to suit an arrival silently
changes every board that uses the others.

Instead, record a verification item on the NEW component saying what you compared
and what still needs confirming — that a human has to decide whether this part can
actually sit on this land. Give them the numbers: the new part's lead pitch, lead
span and body against the drawn pads, and the JLC land for the new part's own LCSC
code if one exists.

If the land genuinely does not fit the new part, that is a **new footprint**, not an
edit to the old one.

These boards are assembled by JLCPCB. The land JLC publishes for a part is the
one their pick-and-place and reflow process is built around, and it is derived
from the manufacturer's own recommended land rather than from a generic family
rule. Starting there removes a whole class of defect at the source.

**A KiCad stock or generic JEDEC footprint is the exception, and it requires
certainty — not resemblance.** Use one only when you have diffed its pad
positions, pad sizes, pitch, exposed pad and pad NUMBERING against the
manufacturer's own recommended land drawing, and they agree. Say in the proposal
comment which drawing you compared and on which page.

"It has the right package name" is not certainty. The names collide constantly:

- `SOIC-16` and `SOIC-16W` share a pin count and differ by 3.6 mm of body width,
  so the wrong one leaves pads that never reach the leads.
- `SOT-23-6`, `TSOT-23-6` and `SOT-363` are three different bodies.
- A generic `QFN-16` says nothing about whether the part has an exposed pad, how
  big it is, or whether it is pin 17 or unnumbered.
- `USON`, `WSON`, `XSON` and `DFN` are used interchangeably by different vendors
  for lands that are not interchangeable.

Picking a plausible generic and moving on is how a wrong footprint reaches a
fabricated board. It has happened repeatedly in this library and each instance
costs a rework or a respin — which is the whole reason this rule exists.

### House-prepared footprints — ours on purpose, not drift

Some families were drawn in house and are correct as they stand. A difference from
KiCad stock or from JLC on these is **not** evidence of a defect, and they must not
be "corrected" toward either. Keep this list current as more are confirmed:

| Family | Status |
|---|---|
| `R_0402_1005Metric`, `R_0805_2012Metric`, `R_1206_3216Metric` | Hand-drawn by Mateusz Kowalik. Confirmed 2026-08-24: "those are made manually by me". Their tens-of-micrometres differences from KiCad stock are deliberate. |
| SOIC family | Prepared in house. |

When a house-prepared land disagrees with JLC, say so in the verification note and
leave it alone unless the user asks.

### Then check the mechanics

- Find existing candidates with `list_footprints` (it shows each one's pad count)
  before importing a duplicate — if the library already holds the right land for
  this exact package, reuse it rather than creating a second copy.
- Pad count must match the base symbol's pin count ([[conventions-symbols]]),
  **counting the exposed pad**. A symbol with 64 pins on a footprint with 65 pads
  leaves the thermal pad with no net and nothing warns.
- Reference it as `7Sigma:<name>` with no other prefix. A reference to a
  footprint that does not exist is rejected by the proposal tools.

### Reading footprint names

Two naming styles coexist; both are fine, match whichever the family already uses.

- **Generator style** — `FAMILY-PINS_L<len>-W<wid>-P<pitch>-…-EP`
  (e.g. `VQFN-14_L3.5-W3.5-P0.50-BL-EP`)
- **EasyEDA / KiCad-stock style** —
  `FAMILY-PINS-1EP_<L>x<W>mm_P<pitch>mm_EP<a>x<b>mm`
  (e.g. `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm`)

Don't rename an existing footprint just to harmonise style — only when the name
no longer describes the geometry (e.g. after adding thermal vias).

A `_ThermalVias` / `-ThermalVias` suffix means the footprint stitches thermal
vias under the exposed pad: more board area, different paste pattern. Pick the
variant the design calls for.

## 2. Naming — the tier rule

**Adopted standard: the KiCad Library Convention (KLC), in the dialect the shipped KiCad 10
library actually uses.** Where the KLC pages and the shipped library disagree, the shipped
library wins. IPC-7351 is metadata only, never the name. EasyEDA/LCSC generator strings
(`..._L3.0-W1.7-P0.95-LS2.8-BL`) are stripped on import, never kept — they name the
component body, not the land pattern.

Full standard, per-footprint migration table and the catalogue of canonical names for
packages not yet in the library: `docs/footprint-naming/` in the platform repo.

**The tier test names a footprint. It does not choose one.** Run it on copper you
have already sourced and verified per §1. Question 1 asks whether stock happens to
match the land you already have — it is never a reason to adopt a stock land
pattern you have not checked against the manufacturer's drawing. Tier 0 is a claim
that our copper matches stock, not a licence to make our copper *be* stock.

### Run this test in order, stop at the first Yes

| # | Question | Result |
|---|---|---|
| 1 | Does KiCad stock ship a footprint whose land pattern **and pad numbering** match ours? | **Tier 0** — adopt its filename byte-for-byte. Stop. |
| 2 | Does it have **zero electrical lands**? | **Tier 4** — mechanical form, `Mechanical` token mandatory. |
| 3 | Is there a published package designation (JEDEC / EIAJ / EIA case / IEC) whose parameters fully determine the land? | **Tier 1** if our copper is the generic pattern; **Tier 2** (vendor-prefixed, KLC F2.3) if it deviates or the outline is proprietary. |
| 4 | Otherwise | **Tier 3** — vendor + MPN, family word first. |

```
Tier 0  SOIC-8_3.9x4.9mm_P1.27mm            (verbatim stock — never edit)
Tier 1  QFN-28_4x4mm_P0.5mm  ·  R_0603_1608Metric
Tier 2  Winbond_USON-8-1EP_2x3mm_P0.5mm_EP0.3x1.7mm
Tier 3  TerminalBlock_Dorabo_DB301V-3.5-2P_1x02_P3.50mm_Vertical
Tier 4  Enclosure_Hammond_1551RFLGY
```

**Tier 0 names are frozen.** 91 of the library's 173 footprints are Tier 0 today. Never
rename one, never "tidy" its spelling — byte-identity with the 15,447 stock names is what
makes autocomplete, review and drop-in replacement work.

### Before claiming Tier 0, verify the copper

A Tier 0 adoption is a claim about copper, not a resemblance of names. **Diff pad numbers,
positions, sizes and drills against the stock file before proposing the name.** Three
candidate adoptions failed exactly this check — one of them (`TDSON-8`) had different pad
*numbering*, which would have silently broken the symbol's pin mapping.

Never mint a name equal to a stock filename unless the copper matches. If it differs, change
a real field — add the vendor prefix, or record the true measured value. Never disambiguate
with a counter (`_2`, `ThermalVias2`).

### Field order — twelve slots, never reordered

```
[<Family>[_<Function>]_] [<Vendor>_] [<Series>_] <Package|MPN>
   [-<pins>[-<n>EP|-<n>MP|-<n>SH]] | [_<rows>x<pos>] | [-<n>Pin]
   [_<X>x<Y>[x<Z>]mm] [_Layout<c>x<r>] [_P<pitch>mm]
   [_<Modifier>…] [_LayoutBorder<a>x<b>y] [_<Orientation>] [_<Option>…]
```

- `_` separates independent fields; `-` joins sub-attributes **inside** the package/pin field.
- Pin count glued to a package designation is never zero-padded (`QFN-16`, `SOT-23-5`).
  Connector positions-per-row **are** zero-padded to 2 (`1x02`, `2x50`) and count electrical
  positions per row, not total pads.
- Pitch is always `_P<value>mm`. Body size is `<X>x<Y>mm`, lowercase `x`, unit once.
- Options are last: `_ThermalVias`, `_HandSoldering`.

### Global spellings — decided, do not re-litigate

| Rule | Decision |
|---|---|
| Hand-solder variants | **`_HandSoldering`** (matches KLC F2.1 #10). Never `_HandSolder`/`_Handsoldering` for house-minted names. Tier 0 stock names keep their own spelling, so `_HandSolder` will legitimately appear on adopted stock footprints — that is correct, not drift. |
| Vendor token | Canonical manufacturer name from the library conventions table, **spaces and dots removed, casing kept, never abbreviated or truncated**: `MEAN WELL`→`MEANWELL`, `Texas Instruments`→`TexasInstruments`, `Diodes Incorporated`→`DiodesIncorporated`, `OSRAM`→`OSRAM`. Tier 0 exempt. |
| Rotation / origin | **Never encoded in a name.** A rotated or mis-origined import is a *geometry* defect to fix, not a fact to record in the string. |
| Character set | `A-Z a-z 0-9 _ . , + -` only. No spaces ever. Commas only to reproduce a vendor's own comma-decimal MPN (`MC_1,5`). |

### One family, two family words — verify against the stock filenames

A family prefix is not always one word per family. Some families split by
**mount technology into two different family words**, with no `_SMD`/`_THT`
token anywhere. Section 3.9 of the full standard covers the token; it does not
cover this, and the section 4 per-family table has no varistor row at all.

**Varistors split. Fuses do not.**

| Part | Prefix | Applies to | Stock evidence |
|---|---|---|---|
| Varistor, through-hole disc | `RV_Disc_…` | THT only | 101 of the 102 files in `Varistor.pretty`, every one `(attr through_hole)` |
| Varistor, SMD | `Varistor_<Vendor>_<Series>…` | SMD only | `Varistor_Panasonic_VF`, the only `(attr smd)` file in that library |
| Fuse, any mount | `Fuse_…` | chip, SMD cartridge **and** THT | `Fuse_0402_1005Metric`, `Fuse_Littelfuse-NANO2-451_453` (smd), `Fuse_Littelfuse_372_D8.50mm` (tht) |
| Fuse holder | `Fuseholder_…` | separate family, never `Fuse_` | `Fuseholder_Cylinder-5x20mm_XFCN_PTF-77_P22.6mm_Horizontal` |

`RV` is the varistor's **reference designator**, not a filename prefix. Taking
it for one is the specific error this section exists to stop — it produced
`RV_TDK_CU3225_8x6.3mm` for an SMD part on 2026-08-14, corrected to
`Varistor_TDK_CU3225_8x6.3mm`. KiCad states both spellings itself: the stock
`Device:Varistor` symbol carries `ki_fp_filters "RV_* Varistor*"`.

**Never `MOV`.** The token appears in zero stock footprint filenames and zero
stock symbol names. KiCad says `Varistor` (and `VDR` in keywords), and
"varistor" is the broader class anyway — metal-oxide is one construction among
several. Put `mov` in the footprint's `tags` and the symbol's `ki_keywords` so a
search for it still lands, never in the name.

**The check, before you mint any family prefix**, is two commands against the
shipped library — not recall:

```
ls <Family>.pretty                       # which family words actually exist
grep -o 'attr [a-z_]*' <candidate>       # which mount each one is for
```

If the family word you were about to use exists but every file carrying it is
the other mount technology, you have the wrong prefix.

### Connector pad numbering is never a house choice

A pad number claims *this copper is the contact the manufacturer calls N*. Follow the
datasheet always — the mating plug's contact 7 touches receptacle contact 7. A footprint
whose numbering disagrees with its datasheet is a **bug**, not a convention.

Standardise **symbols** instead: generic and keyed on `(rows, positions, scheme)` —
`Conn_02x50_Odd_Even`, `Conn_01x24` — reused across every vendor. A per-MPN symbol needs a
justification (fixed pin semantics like USB-C or 8P8C), not convenience. Symbol *layout* is
house-standard and scheme-independent.

Fast check for a part with differential pairs: in the real numbering, P and N of a pair sit
on **same-parity pins exactly 2 apart**. If your footprint puts a foreign signal between
them, the numbering is wrong.

### Quad packages are always counter-clockwise — a mirrored one is always a bug

**QFN, QFP, TQFP, LQFP, VQFN, DFN and SOIC number counter-clockwise when seen
from the TOP, starting at the pin nearest the pin-1 mark.** There is no
clockwise variant and no mirrored variant. Every datasheet pinout figure is a
TOP view unless it says BOTTOM. KiCad stock uses the same direction, so a
house footprint that disagrees with stock on *direction* is wrong — stock is
not the odd one out.

In KiCad coordinates **Y points DOWN**, so on a square quad package pin 1 sits
at **negative Y** (top) on the left edge:

| Pins | Edge | Runs |
|---|---|---|
| first quarter | left, `x` negative | top to bottom, `y` increasing |
| second quarter | bottom, `y` positive | left to right, `x` increasing |
| third quarter | right, `x` positive | bottom to top, `y` decreasing |
| last quarter | top, `y` negative | right to left, `x` decreasing |

**This is the trap.** Reading a datasheet figure with Y-up in your head and
writing it out with KiCad's Y-down flips the part about the X axis. The pad
grid of a quad package is symmetric, so nothing looks wrong — the outline, the
pitch, the courtyard and the pad count all still check out, and the pin-1
silk arrow moves along with the error, so the drawing stays internally
consistent. Only the numbers are mirrored. On the board every signal lands on
the wrong pin.

**Run this check before proposing any quad footprint. It is two lines and it
is not optional:**

```
# pin 1 must be top-left: x negative AND y negative
# pin (N/4 + 1) must be on the BOTTOM edge: y positive
grep -A1 '(pad "1"' <file>          # expect (at -X -Y)
grep -A1 '(pad "17"' <file>         # 64-pin: expect (at -X +Y)
```

If pin 1 sits at positive Y, the footprint is mirrored. Fix it by negating Y
on every pad, on the `F.SilkS` pin-1 marker and corner brackets, on the
`F.Fab` body chamfer and on the `Cmts.User` pin-1 circle — not by renumbering
the pads in place, which moves the error into the silkscreen instead.

Cross-check against a second source whenever the part is on LCSC: the JLCPCB
land pattern (`easyeda2kicad --lcsc_id=C…`) and the nearest KiCad stock
footprint of the same body and pitch. Both use the same direction. If your
drawing disagrees with both, your drawing is wrong.

**Never write "stock numbering runs the opposite direction" in a proposal
comment.** It never does. That exact sentence shipped as the justification for
the mirrored `Microchip_QFN-64-1EP_8x8mm_P0.4mm_EP3.7x3.7mm_ThermalVias` v1
(KSZ8864CNXI-TR) on 2026-08-23 — the claim was the mirror error rationalised,
and it survived review because it sounded like a considered finding. A real
reason to skip Tier 0 is measurable copper: a different pad size, a different
pad centre, a different EP. Direction never is.

## 3. The package name (`{Footprint_Name}`)

Every footprint carries a short human package name — `0402`, `SOT-23-6`,
`VQFN-HR-9` — which the generator injects at build time wherever a component's
`ki_description` references `{Footprint_Name}`.

**A brand-new footprint has none, so NAME IT IN THE SAME BREATH as publishing
it.** Skip that step and the first component to reference the footprint
publishes with an `unresolved template {Footprint_Name}` mirror warning and a
description with a hole in it. Two doors write the same field:

- `set_footprint_package_name(name, package_name)` — the agent's door, over
  MCP. `name` is the footprint name WITHOUT the `7Sigma:` prefix. Added
  2026-08-27; it reaches an agent only once the api image carrying it is
  deployed, so if the tool is not in your catalog yet, use the HTTP door below.
- `PATCH /api/footprints/<id>` with `{"display_name": "<package name>"}` — the
  raw door, for a script or for an agent whose catalog predates the tool. Get
  the id from `GET /api/footprints`.
- The footprint's page in the Templates browser — the human's door.

Either way it is **unversioned**: no footprint version is minted and the
`.kicad_mod` is untouched, but the symbol libraries of every affected category
rebuild at once.

It belongs to the **footprint**, not to the components that use it: never add a
`Footprint_Name` property to a component ([[add-component]]). Set it once and
every component using that footprint follows; changing it rebuilds the symbol
libraries of every affected category automatically.

A footprint with no package name contributes nothing, so a component whose
description references `{Footprint_Name}` reports an unresolved template. The
fix is to name the footprint, not to patch the component.

## 4. Style rules (the validator enforces these)

These are the machine-checked rules in the platform's `footprint_style` rule
block — a footprint that breaks them raises validator warnings.

| Property | Rule |
|---|---|
| SMD pad type | `roundrect` |
| `roundrect_rratio` | `0.25` |
| SMD pad layers | `"F.Cu" "F.Paste" "F.Mask"` (all three) |
| Through-hole pad type | `thru_hole circle` or `thru_hole oval` |
| `F.Fab` outline | required, line width `0.1 mm` |
| `F.SilkS` line width | `0.1 mm` |
| `F.CrtYd` courtyard | required, closed, line width `0.05 mm` |
| Header prefix | no `easyeda2kicad:` prefix — the internal `(footprint "NAME")` must equal the filename, unprefixed |

### The one decided exception: a polarity mark may be 0.2 mm

**A cathode bar, or the equivalent orientation mark on any part that needs
one, is drawn at 0.2 mm on purpose.** Decided by Mateusz Kowalik on
2026-08-25, on `D_SOD-123FL` v5: some marks have to stay readable beside the
pads, and 0.1 mm does not.

`fp.silk_width` still FAILS on such a footprint. **That failure is expected,
not a defect to fix.** Accept the item on the footprint's checklist with a
note naming the mark, and move on.

**Never narrow a 0.2 mm polarity mark to 0.1 mm.** That is exactly what
`D_SOD-123FL` v4 did — an agent read the 0.2 mm bar the user had drawn in v3
as house-style drift and "corrected" it, citing this very section. Everything
else on `F.SilkS` — body outlines, corner brackets, pin-1 indicators — stays
at 0.1 mm, so a footprint drawn wholly at 0.2 mm is still wrong.

Plus the conventions the validator can't check:

- **Pad names map exactly to the symbol's pin numbers.** Net assignment fails
  *silently* when they don't.
- Integer pad names stored as integers: `"1"`, never `"1.0"`.
- `F.Fab` carries the **component body** outline as a closed polygon, with a
  0.1 mm radius pin-1 circle inside it.
- `F.SilkS` carries a partial outline that never overlaps pad copper, plus a
  pin-1 indicator. Silkscreen may be omitted on very fine pitch (≤ 0.4 mm) where
  it cannot be drawn clear of the pads; `F.Fab` is still required.
- **`Cmts.User` carries a pin-1 mark — always.** Every footprint that has a
  pad `1` (or `A1`) gets a 0.1 mm radius circle (`fp_circle`, 0.2 mm stroke,
  no fill) on `Cmts.User` at pin 1: centred on the pad for 2-pad chip
  passives, placed just outside the pad — offset away from the footprint
  centre, on the 0.1 mm grid — for everything else. It complements the
  `F.Fab` and `F.SilkS` indicators, never replaces them, and it must stay
  within 2 mm of the pad-1 centre so verification sweeps can find it.
- Courtyard clears the outermost pad/body feature, snapped to the **0.1 mm
  grid**. The grid figure is not a preference: the machine item
  `fp.courtyard_grid` FAILS a footprint whose `F.CrtYd` coordinates sit on
  0.05 mm steps. This document said 0.05 mm until 2026-08-27, and
  `R_Shunt_WalterElectronic_MSH2512_6332Metric` v1 was published with a
  courtyard at ±3.95 × ±2.05 and failed validation for exactly that reason.
- **Clearance is 0.25 mm** from the outermost pad or body feature, then snapped
  outward to the 0.1 mm grid. Decided by Mateusz Kowalik on 2026-08-27, closing
  the question this section raised the same day. It matches KLC F5.3 and it
  matches the library, which has never used the 0.5 mm this document used to
  claim: every QFN measures 0.25 mm, `HVSSOP-10-1EP_3x3mm_P0.5mm_EP1.57x1.88mm_ThermalVias`
  0.225 mm and `R_1206_3216Metric` 0.29 mm. **0.5 mm was never real** — do not
  re-derive it, and do not "correct" an existing 0.25 mm courtyard toward it.
  On a 2 mm part the difference is not cosmetic: 0.5 mm draws a 3.6 × 3.5 mm
  keep-out around a package chosen for its solution size.

  A LARGER courtyard is still legitimate when the part needs one — a tall
  component beside a connector, a hand-soldering variant, a documented
  clearance like the lightpipes in §8. Say why in the proposal comment; the
  0.25 mm figure is the default, not a ceiling.
- Global dimension floors: pad ≥ 0.6 mm, drill ≥ 0.3 mm, via ≥ 0.3 mm.

**Fix every validator warning by default** — including ones that were already
there before you touched the footprint. Only stop to ask if the fix is
non-obvious (would need the symbol's pin layout changed, or a body outline
redrawn by hand) or could break correctness. The standing exception is the
0.2 mm polarity mark above: leave it alone and record why.

### 3D model path

```
(model "${SEVENSIGMA_DIR}/3DModels/<folder>/<NAME>.step"
  (offset (xyz 0 0 0))
  (scale (xyz 1 1 1))
  (rotate (xyz 0 0 0))
)
```

Always the `${SEVENSIGMA_DIR}` variable — never a hardcoded path, never
`${KIPRJMOD}`, never a folder in your home directory. A footprint that names a
path outside `${SEVENSIGMA_DIR}/3DModels/` is REFUSED, so the file must be in
the library before the footprint points at it.

**Every footprint carries a model — no exceptions.** A footprint proposed with
no `(model ...)` line is incomplete, even when nothing suitable is stored yet,
and the machine check fails its `fp.model3d` item until a human or agent marks
the item `na`. Check what exists with `list_models3d`.

**Three doors put a file in the library, and they write the same store.**

1. **The KiCad *Push 7Sigma changes* button does it for you.** Point the
   footprint at the file wherever it actually is — `~/Downloads`, KiCad's own
   `3dmodels/` tree, the installed 7Sigma models tree, a folder beside the
   project — save, and push. Push checks every reference against the model
   store, shows you the target path for each file the library does not hold
   **or holds with different bytes** (editable), uploads them, rewrites the
   footprint to `${SEVENSIGMA_DIR}/3DModels/…` and repoints your local copy at
   the stored model. Nothing has to be moved by hand first.

   **This is also how a wrong model is corrected.** Edit the STEP in place, at
   the path the footprint already names, and push: the digest no longer matches
   the store, so push replaces that `rel_path` and announces it as
   "Replacing …". A replacement is not private to one footprint — every
   footprint pointing at that path gets the new solid, which is the same reason
   `upload_model3d` to an existing path is the documented fix rather than a
   second path.

   **This needs plugin 1.4.0 or newer.** Before that, a file dropped into the
   INSTALLED library's own `3dmodels/` tree was the one case push skipped:
   that path rewrites into a `${SEVENSIGMA_DIR}` reference, so it read as
   already stored. The push filed a footprint pointing at bytes the platform
   had never seen, and `fp.model3d` failed after publishing — `D_SOD-123FL`
   v5, 2026-08-25. Check the version in the Plugin and Content Manager when a
   model goes missing after a push.
2. **`upload_model3d(file_path, rel_path)`** — the agent's door, over MCP. It
   reads the file off the machine running the MCP server and returns the
   `(model ...)` node to paste. `rel_path` is optional; see the folder rule
   below.
3. **Raw HTTP**, for a script:

```
POST /api/models3d/upload?rel_path=<folder>/<NAME>.step
     multipart/form-data, field "file"
```

An upload is live immediately — models carry no draft gate — and re-uploading
the same `rel_path` REPLACES the file. That is how a wrong model is corrected:
same path, new bytes, never a second path.

**Which folder.** Three rules, first match wins:

1. The folder the footprint's CURRENT model uses. Replacing a model must not
   move it.
2. The source file's own folder when that is a `*.3dshapes` directory — a model
   taken from KiCad's tree keeps KiCad's category (`Package_SO.3dshapes`,
   `Capacitor_SMD.3dshapes`, …), which is what every adopted Tier 0 footprint
   in the library already does.
3. Otherwise `7Sigma.3dshapes/` — models we drew or obtained from a vendor for
   a 7Sigma part. Do not drop new files loose at the root of `3DModels/`; the
   nineteen that sit there predate this rule.

KiCad's own `3dmodels/` tree, beside the stock footprints, is the first place
to look. A Tier 0 adoption inherits its stock model: keep the stock filename,
and point a `_ThermalVias` variant at the plain STEP, which is the only one
KiCad ships.

**A borrowed model must say so.** Reusing another vendor's solid for a shared
outline beats shipping none, but the proposal comment has to name the source
part, every dimension that differs, and any `offset` used to correct the
difference. A model is a visual aid, never fabrication data — an undisclosed
mismatch reads as vendor geometry to the next person.

## 5. Pad placement grid

Pad centres and sizes belong on the **0.1 mm grid**. Two exceptions:

- **The pitch axis of a fine-pitch package**, where lead positions don't divide
  by 0.1 mm. A 0.5 mm-pitch package with two leads per side has them at
  y = ±0.75 mm; snapping to ±0.7/±0.8 misaligns pad and lead. Leave the pitch
  axis on whatever grid the datasheet dictates.
- **When snapping would move a pad more than 0.1 mm** from its datasheet
  position. Never trade land-pattern correctness for grid tidiness.

When snapping, round pad sizes to `0.1 x n` too. If the across-edge dimension
shifts, move the pad **outward** (away from the body) so the lead toe stays
covered.

## 6. Mechanical holes must be NPTH

Mounting holes, locating pegs and body-clearance holes are mechanical, not
electrical: use `np_thru_hole`, never `thru_hole`.

The common defect from EasyEDA/LCSC-sourced footprints is an unnamed plated pad
whose copper size equals its drill:

```
(pad "" thru_hole circle (at ...) (size 1 1) (drill 1) (layers "*.Cu" "*.Mask") ...)
```

That is a 0 mm annular ring → KiCad DRC raises a minimum-annular-width violation
on every such hole. Fix by changing the type to `np_thru_hole` and leaving the
rest alone (NPTH pads are exempt from annular-ring DRC, and unnamed pads carry
no net, so nothing electrical is lost).

Rule of thumb: any pad where `(size - drill) / 2 <= 0` must be `np_thru_hole`.
If a hole genuinely should be plated and netted, give it a real ring
(size ≥ drill + 0.3 mm) and a pad number instead.

## 7. Thermal vias under exposed pads

KiCad has no via primitive inside a footprint — thermal vias are **thru-hole
pads sharing the exposed pad's number**, so they inherit its net.

```
(pad "<EP_NUMBER>" thru_hole circle
    (at <x> <y>)
    (size 0.6 0.6)
    (drill 0.3)
    (property pad_prop_heatsink)
    (layers "*.Cu")
    (remove_unused_layers no)
)
```

| Attribute | Value | Why |
|---|---|---|
| Pad number | same as the EP land | net inheritance |
| `size 0.6` / `drill 0.3` | 0.15 mm annular ring | standard stitching geometry |
| `property pad_prop_heatsink` | required | flags the pad as heat-spreader for DRC/BOM |
| `layers "*.Cu"` | all copper | top-to-bottom heat path |
| `remove_unused_layers no` | required | keeps the ring on inner layers |

Companion changes that must go with them:

1. **Strip `F.Paste` from the EP land** — paste over an open via barrel wicks
   down the hole and starves the joint. EP uses `(layers "F.Cu" "F.Mask")` only.
2. **Add windowed paste apertures** — unnamed
   `(pad "" smd roundrect ... (layers "F.Paste"))` blocks covering ~50–70 % of
   the EP, positioned to miss the barrels. 4–9 apertures depending on EP size.
3. **Add a back-side land** — duplicate the EP on `B.Cu` with `(zone_connect 2)`
   so the vias stitch into a back-side pour.
4. **Set `(zone_connect 2)` on the EP `F.Cu` pad** — the default thermal relief
   defeats the purpose.
5. **Rename with the `_ThermalVias` suffix** (§1).

**The EP land is `smd rect`, never `roundrect`.** On a large EP the §4 corner
radius becomes big (0.25 x 3.3 mm = 0.825 mm) and rounds the corners back far
enough to clip the corner vias, leaving them outside the EP copper → DRC
annular-ring / isolated-copper errors. The validator exempts pads carrying
`pad_prop_heatsink` from the roundrect rule, so a `rect` EP raises no warning.
Normal signal pads still follow §4.

Via grid: aim for ~1 mm pitch inside the EP with ≥ 0.2 mm clearance from the EP
edge to the via copper. 2x2 suits EPs up to ~2.5 mm; 4x4 suits ~3 mm and larger.

## 8. Non-electrical parts (lightpipes, standoffs, enclosures)

Some `Mechanical_7S` parts are not soldered at all, and forcing the standard
rules onto them produces a wrong footprint.

**Lightpipes (FIX-LEMB family)** need at least **1 mm of clearance** between the
bottom of the pipe body and anything on the PCB below it — the illuminating LED
sits under the pipe, and without that gap the pipe crushes the LED or loses its
entry-face air gap. That clearance is a **layout constraint, documented on the
footprint**, not something baked into the part:

- **3D model** — build the STEP with the post bottom at z = 1.0 mm so the 3D
  viewer shows the required gap.
- **Footprint** — omit `F.CrtYd` entirely, and omit the mounting through-hole
  pad. The PCB designer drills the hole separately from the documented OD.
  The base component must be in the rule block's
  `footprint_style.exempt_base_components` list so the validator skips the
  `F.CrtYd` presence and width checks.
- **Document the constraint** — a `Cmts.User` text note ("Min 1mm clearance
  below") plus a dashed `Dwgs.User` circle at the head OD, so PCB designers see
  it without it being enforced as a courtyard.

The pad-shape, silkscreen-width and no-`easyeda2kicad:`-prefix rules still apply
to exempted parts.

## 9. JLC pick-and-place rotation offsets

A part's orientation in its tape (EIA-481, set by whoever packaged it) and the
IPC/KLC land pattern KiCad draws are unrelated standards. Where they disagree,
every placement of that package is off by a constant. That constant is a fab
fact, not a drawing defect. Record it ON THE FOOTPRINT as a hidden property:

```
(property "FT Rotation Offset" "180" (at 0 0 0) (layer "F.Fab") (hide yes) ...)
```

**How the number reaches JLC.** The Fabrication Toolkit builds each CPL row as:

```
rotation = the footprint's orientation on the board
if bottom layer:      rotation = 180 - rotation
if AUTO TRANSLATE on: rotation += transformations.csv   (regex on the footprint NAME)
rotation = (rotation + "FT Rotation Offset") % 360
```

Use the primary field name `FT Rotation Offset`; the toolkit's `Rotation Offset`
and `RotOffset` fallbacks must not appear in the library.

- **Degrees are counter-clockwise positive**, KiCad's convention. Three clicks of
  the JLC preview's CCW rotate button is `270`. A part that lands exactly 180
  degrees out means the direction was read backwards.
- **The value ADDS to `transformations.csv`**, which ships inside the plugin and
  matches the footprint name with the library nickname stripped, first hit wins.
  `^QFN-` already contributes 90 and `^SOT-23` already contributes 180. What we
  store is therefore the REMAINDER measured on top of that, never an absolute
  angle — and it is only valid while AUTO TRANSLATE stays on (it is on by
  default; the setting lives in `fabrication-toolkit-options.json` beside the
  board file). A plugin update that edits those rules silently invalidates every
  offset recorded here.
- **It belongs on the FOOTPRINT, not the component.** Verified 2026-08-04: some
  boards carry library component fields on their placed footprints and some
  carry none at all, so a component-level field is not reliably present in the
  CPL. A footprint property arrives with Update Footprints from Library.
- **NEVER rotate correct geometry** to match a fab's tape, and never encode
  rotation in a footprint name (§2).

**Only a reviewed export verifies an offset.** "The board shipped and worked"
proves nothing: rotations corrected by hand in the JLC order preview never reach
the CPL, so a shipped board can hide a wrong file indefinitely. The one sound
evidence is: this export's preview was reviewed and this part needed no change.

**Never generalise an offset across a package family.** Refuted empirically on
2026-08-04: `SOT-23-5` and `SOT-23-6` each need +90, while `SOT-23-3` needs
NOTHING — same family, same pin-1 bearing of 138 degrees, same CCW numbering.
Tape orientation can differ per part, so an offset on a shared land pattern
moves every component using it. Name the witness part in the proposal comment
and check the siblings on the next order.

Verified offsets (each measured on a reviewed JLC preview):

| Footprint | Offset | Witness part |
|---|---|---|
| `U.FL_Kinghelm_KH-IPEX-K501-29_Vertical` | 180 | KH-IPEX-K501-29 (C411563) |
| `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm_ThermalVias` | 270 | PCF8574RGTR |
| `UQFN-16_1.8x2.6mm_P0.4mm` | 270 | TMUX1208RSVR |
| `SOT-23-5` | 90 | TPS7B6950QDBVRQ1 |
| `SOT-23-6` | 90 | TPS54302DDCR |

Confirmed needing NO offset: `SOT-23-3`, `SOIC-8` (both variants),
`DFN-8-1EP_3x3mm`, `USON-10`, `VQFN-14`, `VQFN-40`, and every no-rule footprint
on the reviewed Dongle V3 export.

## 10. Imported footprints

An EasyEDA/LCSC import is the normal path into this library, not a fallback —
see §1. Origin doesn't change the rules, though: everything lives in the
`7Sigma:` namespace and follows §4. The import gives you the right *land*; this
checklist makes it conform to the house drawing style. Work through it before
proposing:

- [ ] Header prefix stripped (`"easyeda2kicad:NAME"` → `"NAME"`)
- [ ] Pads `oval`/`rect` → `roundrect` with `(roundrect_rratio 0.25)`
- [ ] Pad names have no `.0` suffix
- [ ] `F.Fab` body outline present at 0.1 mm
- [ ] `F.CrtYd` closed courtyard present, line width 0.05 mm, coordinates on
      the 0.1 mm grid (two different figures — the width is 0.05, the grid is
      0.1; reading the width as the grid is what failed `fp.courtyard_grid` on
      two footprints in 2026-08)
- [ ] Mechanical holes converted to `np_thru_hole` (§6)
- [ ] 3D model offset/rotation verified, not taken on trust — imported offsets
      are frequently wrong. Check that the mesh's pin/lead centres land on the
      pad coordinates rather than keeping whatever offset the exporter emitted.

See [[add-component]] for where footprint choice fits in the full part-creation
procedure, and [[platform-workflow]] for what a publish sets in motion.
