---
name: kicad-conventions-footprints
description: "Choosing AND authoring footprints: where to get the copper, how to publish it, and the index of every footprint rule with the check that now holds it. The rules themselves live in the footprint checklist — read them with get_review_checklist('footprint'). Use when naming, picking or authoring any footprint."
---
<!-- platform-skill: conventions-footprints v56 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Footprint conventions

**The rules are checks now, not prose.** Every convention this document used to
state is a checklist item on the footprint base checklist, and the item carries
the data: the numbers, the decided cases, the traps and the worked examples.
Read them with `get_review_checklist("footprint")` — once, before you author or
verify — and answer them when you publish.

What is left here is what a check cannot hold: how to get the copper, how to
publish it, and which check to open for which question.

Footprints live in the `7Sigma:` namespace and are always referenced as
`7Sigma:<name>`.

## Publishing

`propose_footprint_edit(name, source_text, comment)` takes a complete
`.kicad_mod` and **publishes it immediately** (existing name = edit, new name =
creation). There is no draft gate. The mirror and the KiCad libraries update on
the call, a machine validation record is written, and the version starts
UNREVIEWED. **Render it and check it BEFORE you call, not after.**

Never hand-write a footprint when something close exists: `get_footprint` first,
take its `source`, edit that.

**Publishing also repoints every component on the footprint.** A component pins
the footprint *version* it was drawn against, so the platform publishes a new
component version for every name in `used_by_components`, pinned to the new
drawing with properties unchanged. The response's `repointed` block lists what
moved. See [[platform-workflow]].

**Renaming** is `rename_footprint(name, new_name, comment)` — one call publishes
one version carrying the new name, republishes every component that references
it with the reference rewritten, and moves the `.kicad_mod` in the mirror
([decision 0012](https://github.com/mszkowalik/KiCad-Lib/blob/main/docs/decisions/0012-rename-a-footprint-or-base-symbol-in-place.md)).
Four things to know: it is **not** a way to correct a drawing (use
`propose_footprint_edit`, as a separate version); verification and sign-off
**carry**, because nothing a verification measured moved — the exception, not
the rule, since a `Footprint` reference, a `base_component` and a
`Manufacturer 1` value are all otherwise MATERIAL; history keeps the old name,
correctly; and boards already laid out keep the old library id until their owner
updates from the schematic, so say so when you report a rename. What justifies
one at all is on **`fp.naming`**.

**Naming the package.** A brand-new footprint has no package name, so set it in
the same breath: `set_footprint_package_name(name, package_name)` over MCP,
`PATCH /api/footprints/<id>` with `{"display_name": "…"}` for a script, or the
Templates browser for a human. Unversioned — no footprint version is minted and
the `.kicad_mod` is untouched, but the symbol libraries of every affected
category rebuild at once. **`fp.package_name`** fails until it is set.

**3D models.** Three doors write the same store — the KiCad *Push 7Sigma
changes* button, `upload_model3d(file_path, rel_path)` over MCP, and
`POST /api/models3d/upload?rel_path=<folder>/<NAME>.step`. An upload is live
immediately and re-uploading the same `rel_path` REPLACES the file. The rules
about which folder, which path prefix and how to correct a wrong model are on
**`fp.model3d`**; measuring one is on **`fp.model_fit`**.

## Getting the copper

**Creating a footprint → import the JLC land.**

```
easyeda2kicad --lcsc_id=C<number> --full --output ./easyeda_tmp
```

`--full` also fetches the 3D model, and for a NEW footprint you take EasyEDA's
model too — it is drawn to the same land. Measure its bounding box first; the
meshes are frequently z-centred.

**A footprint that already exists → COMPARE, do not replace.**

```
easyeda2kicad --lcsc_id=C<number> --footprint --output ./easyeda_tmp
```

What to escalate, what to note and move on, which families are house-prepared on
purpose, and why JLC beats a dimension read off a drawing are all on
**`fp.jlc_land`**.

Find candidates first with `list_footprints(query)` — it matches the name, the
`tags` and the `descr`, and a hit carries `matched_on`. It shows each
footprint's pad count.

**A footprint records its alternative package names in `tags` and `descr`, and
nowhere else.** Those are the only two fields KiCad's own footprint chooser
searches. A hidden `Equivalent Packages` property carried the same names plus
the evidence for each until 2026-09-14; it was dropped because no consumer read
a custom property, so writing one cost a footprint version and a repoint of
every component on the land to store something only `list_footprints` could
see. Do not reintroduce it — **`fp.shared_land_record`**.

Two useful scripts:

```
export KICAD_API_URL=https://disfunction.cc/lib KICAD_MCP_TOKEN=<your personal token>
python3 scripts/model-bbox.py <folder>/<NAME>.step      # measure a 3D model
python3 scripts/footprint-render.py <footprint name>    # front, right, isometric
python3 scripts/footprint-render.py <file.kicad_mod>    # the same, BEFORE you publish
```

**`footprint-render.py` takes a name or a file.** A name renders the PUBLISHED
version from the platform, so a land published a minute ago renders and a
stale local copy cannot hide a change; the installed library is only the
fallback. A `.kicad_mod` path renders a draft, with its STEP taken from the
same directory by file name. Each model is taken from beside the file, then
the platform, then the installed library, and the script says which.

Pass the model path as it appears after `3DModels/` in the `(model ...)` line.

## Where each rule lives

| Question | Check |
|---|---|
| Do the pads match the datasheet land drawing? Is a generic stock land really this package? | `fp.land_pattern` |
| Was it diffed against the JLC land for this LCSC code? When does JLC lose? (a published min or max; a house-prepared family) | `fp.jlc_land` |
| Does a standard package have exactly one land, and is a reuse annotated rather than re-cut? | `fp.one_land_per_package` |
| Does this land also fit other vendor package names, and are they in `tags` and `descr`? | `fp.shared_land_record` |
| Which of the four naming rules applies to this package? | `fp.tier` |
| Is a name copied from KiCad's own library really on KiCad's copper? (a house-prepared land answers n/a — measured diffs below) | `fp.stock_name_diffed` |
| Does anything justify a rename? | `fp.naming` |
| Are the twelve name slots in order? | `fp.field_order` |
| Is the family word right for this mount technology? (varistors split, fuses do not) | `fp.family_prefix` |
| Character set, vendor token, no rotation in the name | `fp.name_charset`, `fp.name_spellings` |
| Is the package name set? | `fp.package_name` |
| Does the internal `(footprint "NAME")` match, with no importer prefix? | `fp.internal_name` |
| Are pad names integers (`"1"`, never `"1.0"`)? | `fp.pad_name_format` |
| Do the pad numbers follow the datasheet's own contact numbers? Which number does an exposed pad take? | `fp.pad_numbering` |
| Does a quad package number counter-clockwise? | `fp.quad_numbering` |
| Pad shape, corner ratio, silk/fab/courtyard widths, courtyard grid, drill and pad floors | `fp.smd_pad_shape`, `fp.smd_rratio`, `fp.silk_width`, `fp.fab_width`, `fp.fab_outline`, `fp.courtyard_present`, `fp.courtyard_width`, `fp.courtyard_grid`, `fp.min_drill`, `fp.min_th_pad`, `fp.via_dims` |
| How far is the courtyard from the copper? | `fp.courtyard_clearance` |
| Does this footprint need a courtyard at all? (an `Enclosure_*` and a `Lightpipe_*` do not) | `fp.mechanical_constraint` |
| Is the silkscreen clear of pad copper? Does the pin-1 mark point at the datasheet's pin 1? | `fp.silk_clear`, `fp.pin1_placed` |
| Is there a `Cmts.User` pin-1 mark? | `fp.pin1_mark` |
| Is the polarity mark one straight line, the right way round? | `fp.cathode_bar` |
| Where does the origin go on a connector whose body overhangs its pads? | `fp.origin` |
| Does the `F.Fab` outline match the real package? | `fp.body_outline` |
| Should a plated hole have been mechanical? | `fp.npth_mechanical`, `fp.zero_annulus` |
| Thermal vias and the five companion changes that go with them | `fp.thermal_vias` |
| A lightpipe or standoff — and why an ENCLOSURE and a LIGHTPIPE carry no courtyard at all | `fp.mechanical_constraint` |
| Is there a 3D model, on the right path, in the right folder? | `fp.model3d`, `fp.model_path` |
| Does the model actually fit, measured? | `fp.model_fit` |
| Is a JLC rotation offset real (a reviewed export, or an exact JLC land), and named correctly? | `fp.rotation_offset`, `fp.rotation_field_name` |
| What does the exposed-pad pin connect to, and what is it named? | `cmp.exposed_pad_documented` |

Full naming standard, the per-footprint migration table and the catalogue of
canonical names for packages not yet in the library: `docs/footprint-naming/`.

## An enclosure and a lightpipe carry no courtyard

**An `Enclosure_*` footprint draws `F.Fab` and puts nothing on `F.CrtYd`.**
Mateusz Kowalik, 2026-09-22: a courtyard on a case outline makes the layout
harder, because the keep-out covers the whole board area the case encloses.

`fp.courtyard_present`, `fp.courtyard_width` and `fp.courtyard_grid` each carry
`when {"$name": "^(?!Enclosure_|Lightpipe_)"}` on the footprint base checklist
(v32), so none of the three runs on an enclosure or a lightpipe.
`fp.mechanical_constraint` states what each draws instead.
`fp.courtyard_clearance` measures from pads and never reaches a part that has
none.

**THE EXEMPTION IS READ OFF THE NAME.** `validate_footprint` is not passed the
component, so it cannot know what a footprint belongs to. A mechanical case not
named `Enclosure_<Vendor>_<MPN>` is not exempt, and the fix is the name
(`fp.tier` rule 2), never a standing exception.

**A LIGHTPIPE CARRIES NO COURTYARD EITHER.** Mateusz Kowalik, 2026-09-28,
when `Lightpipe_MENTOR_1293.0050` was added. The LED sits under the pipe, so a
courtyard at the head OD overlaps the LED's courtyard and KiCad reports a
courtyard overlap on every board. A lightpipe draws `F.Fab` at the head OD, a
`Cmts.User` "Min 1mm clearance below" note and a dashed `Dwgs.User` circle at
the head OD, and puts nothing on `F.CrtYd`. Its STEP puts the inject face at
z = 1.0 mm. The three FIX-LEMB lightpipes carry the note and the circle, and
no courtyard, but no `F.Fab` yet, so they fail `fp.fab_outline`.

**NOTHING ELSE IS EXEMPT.** A standoff and a logo still carry `F.CrtYd` at the
body outline plus the standard 0.25 mm.

**IT IS ON THE ITEM, NOT ON A CATEGORY, AND IT HAS TO BE.** A FOOTPRINT CARRIES
NO CATEGORY, so the "`<Category>` rules" lists in the Checklists view cannot
hold a footprint check at all — `PUT /api/checklists/scope` refuses a
`category_id` for any kind but `component`. There is no
`exempt_base_components` control either; a review pass grepped for one on
2026-09-12 and recorded a custom item saying so. The per-item `when` predicate
IS the scoping mechanism for a footprint check, and `fp.family_prefix` and
`fp.mechanical_constraint` already use it. Do not go looking for a rules table:
`models.Rule` has been dormant since 2026-09-14 and its own docstring says
"Do not add a reader; put the setting on the check."

Cleared the same day: `Enclosure_Hammond_1551RFLGY` v3 and
`Enclosure_TAKACHI_SIM6-12-3W` v7 lost the outlines they carried. The other
three enclosures never had one.

## A JLC quad land can arrive rotated — turn the copper, then the model

**Read the pin-1 corner off the EasyEDA name before you import a quad land.**
The name ends in it: `-BL` is pin 1 bottom-left, `-TL` is top-left. A `-BL`
land puts pin 1 on the BOTTOM edge, 90° away from what `fp.quad_numbering`
requires (pin 1 at (−X, −Y), on the left edge). First met on
`LQFP-100_L14.0-W14.0-P0.50-LS16.0-BL` for STM32H743VIT6 (C114409),
2026-10-07. ST's own recommended-footprint figure for that package is drawn
the same way, so a rotated drawing is not proof of an error in the source.

**Turn the copper, never the numbers.**

1. Map every pad (x, y) to (−y, x) and swap its width and height. That turns
   the land 90° clockwise as drawn.
2. Check that pad 1 is at (−X, −Y) and pad N/4 + 1 is on the bottom edge (+Y).
3. Compare every pad by script against the JLC file after the same mapping.
   A difference means step 1 is wrong.

**Then turn the 3D model the same way.** The EasyEDA STEP is modelled for
JLC's orientation, so after step 1 the `(model ...)` line needs
`(rotate (xyz 0 0 90))`. The sign is easy to get wrong: −90 put the pin-1
dimple in the opposite corner on the first try. Render the draft with
`footprint-render.py <file.kicad_mod>` and confirm that the dimple sits next to
the silk pin-1 mark before you publish. Record the non-identity rotation in
`fp.model_fit`.

**The exact-match shortcut for the rotation offset does not apply.** The turned
land is no longer the same pair as JLC's (see `fp.rotation_offset`). Leave
`FT Rotation Offset` unset and measure it on the first reviewed JLC export. A
vendor-prefixed name such as `STMicroelectronics_LQFP-100_…` also matches no
plugin rule keyed on a package prefix (`^QFN-`, `^SOT-23`).

## A house land is not diffed against KiCad

**The rule is on `fp.stock_name_diffed` and `fp.jlc_land`** (decided
2026-09-18): a house-prepared land under a stock name answers
`fp.stock_name_diffed` n/a with reason `kind_exempt`, and keeps its name and
its copper. What the checks do not hold is the measured difference, for the
note.

The generic chip-passive families are house copper under a stock name, on
purpose. Every one of them differs from the shipped file, because the whole
library was snapped to the 0.1 mm grid and KiCad's generator was not:

| Land | Ours vs KiCad, pad 1 x and size |
|---|---|
| `C_0402_1005Metric` | −0.50 vs −0.48, 0.54×0.64 vs 0.56×0.62 |
| `C_0805_2012Metric` | −0.90 vs −0.95 |
| `C_1210_3225Metric` | −1.45 vs −1.475, 1.20 vs 1.15 wide |
| `R_0402_1005Metric` | −0.50 vs −0.51 |
| `R_0805_2012Metric` | −0.90 vs −0.9125, 1.00×1.45 vs 1.025×1.40 |
| `L_0402_1005Metric` | −0.50 vs −0.485, 0.54 vs 0.59 wide |
| `L_0603_1608Metric` | −0.80 vs −0.7875, 0.90 vs 0.875 wide |
| `Fuse_1206_3216Metric` | −1.45 vs −1.40, 1.20×1.80 vs 1.25×1.75 |

## easyeda2kicad can write the 3D offset with the wrong sign

**Render an imported model before you believe its offset.** Measured on
C2856812 (FPC-05F-40PH20), 2026-10-12: easyeda2kicad 0.8.0 wrote
`(offset (xyz 0 -1.61 0))`. In KiCad that puts the body about 2 mm in front
of the land, with every lead off its pad. The 24-pin sibling
`Xunpu_FPC-05F-24PH20_1x24-1MP_P0.50mm_Horizontal` carries `-1.2`, and its
render shows the same fault. It is not corrected yet.

KiCad places a model point at board y = −(model y + offset y). Do this:

1. Find the lead feet in the STEP: the vertices at z ≈ 0.
2. Choose the offset that puts the feet inside the pad copper and the body
   under the JLC silk outline.
3. Render from the REAR (`kicad-cli pcb render --side top --rotate
   "-60,0,210"`). The default isometric view of `footprint-render.py` looks at
   the front of a right-angle connector and hides its leads.
4. Record the measured offset and the original value in `fp.model_fit`.

A z-centred mesh is a different fault with the same cure: measure, then set
the offset. See the 3D-model paragraph under Getting the copper.

## Pad placement grid — still prose, because no check holds it

Pad centres and sizes belong on the **0.1 mm grid**, with two exceptions:

- **The pitch axis of a fine-pitch package**, where lead positions do not divide
  by 0.1 mm. A 0.5 mm-pitch package with two leads per side has them at
  y = ±0.75 mm; snapping to ±0.7/±0.8 misaligns pad and lead.
- **When snapping would move a pad more than 0.1 mm** from its datasheet
  position. Never trade land-pattern correctness for grid tidiness.

When snapping, round pad sizes to `0.1 × n` too, and if the across-edge
dimension shifts, move the pad **outward** so the lead toe stays covered.

**The pitch decides whether the exception is available, and the overlap decides
whether to use it.** Below 1 mm it may apply; above it does not. Ask what
fraction of the pad-to-lead overlap a 0.05 mm shift costs: on a 0.5 mm-pitch
0.3 mm lead it is a sixth and the exception holds; on a SOT-23, or on a 0.7 mm
tact-switch foot sitting on a 1.4 mm pad, there is 0.1 mm or more spare each
side and the drawing gets snapped. Two
decided cases, both of which reached the user as a flag first:

- **The 6x6 mm SMD tactile family** was published at y = ±2.25 on 2026-09-06
  citing the pitch-axis exception — `SW_Push-4P_SPST_SMD_6x6mm_H7mm_…` had sat
  at ±2.30 while its siblings sat at ±2.25 until then. That was a misreading of a 4.5 mm pitch, and
  Mateusz Kowalik corrected it to ±2.30 on 2026-09-10, outward per the rule.
- **The SOT-23 family is decided: 0.95 mm pitch is drawn at 1.00 mm, on
  purpose. Do not flag it.** `SOT-23-3`, `SOT-23-5` and `SOT-23-6` place pads at
  y = ±1.00 where the datasheets and JEDEC MO-178 give 0.95, so each outer lead
  sits 0.05 mm off its pad centre — a 0.6 mm pad against a 0.3–0.5 mm lead
  absorbs it. "i moved it to 1mm to match 0.1mm snap grid. its intentional"
  (2026-09-13). **Three separate verification passes have re-discovered these
  numbers and filed them as a defect.** The same decision closes the Tier 0
  naming question on all three: house copper under a stock name.

When the answer is not obvious, ask rather than assume.

**Why there is no check yet.** `$footprint_off_grid_pads` measures absolute
off-grid pads, and measured 2026-09-14 that is not the rule: **76 of the 150
coarse-pitch footprints have off-grid pads**, and they are right to. A 1.27 mm
SOIC puts its pads at ±0.635 and ±1.905; a two-row 2.54 mm header puts its rows
at ±1.27. The same **spacing versus absolute grid** distinction the symbol side
already recorded applies here, and the honest check would measure the
across-edge axis only. Until it exists, this stays prose.

## Two rules this document used to state, which are wrong

Both were audited against the running checks on 2026-09-14 and neither survived.
They are kept here so nobody re-adds them.

- **"SMD pads carry `F.Cu`, `F.Paste` and `F.Mask`, all three."** They do not. 25
  footprints differ and every one is an exposed pad, which legitimately carries
  no paste or a separate paste aperture.
- **"Through-hole pads are `circle` or `oval`."** They are not. 25 footprints
  differ and every one is a pin-1 pad, rectangular by KiCad convention so the
  first pin is identifiable on the board.

**Fix every validator warning by default**, including ones that were already
there. Only stop to ask if the fix is non-obvious — it would need the symbol's
pin layout changed, or a body outline redrawn by hand — or could break
correctness.

See [[add-component]] for where footprint choice fits in the full part-creation
procedure, and [[platform-workflow]] for what a publish sets in motion.
