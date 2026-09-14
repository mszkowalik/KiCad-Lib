---
name: kicad-conventions-library
description: "Component DATA conventions: the index of every rule with the check that holds it, plus the manufacturer names nobody has been able to resolve. The rules themselves live in the component checklist — read them with get_review_checklist('component'). Use when setting Value, ki_description, Manufacturer 1 or a category."
---
<!-- platform-skill: conventions-library v41 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Library conventions

**The rules are checks now, not prose.** Every convention this document used to
state is a checklist item on the component checklist, and the item carries the
data: the canonical manufacturer spellings and the evidence behind each one, the
Value formats per category, the description templates per sub-family, the power
spellings, the category-placement rule. Read them with
`get_review_checklist("component")` — once, before you author or verify.

What is left here is what a check cannot hold: the names nobody has resolved,
and where to look when a rule does not fit.

## Where each rule lives

| Question | Check |
|---|---|
| Is `Manufacturer 1` the company's own brand spelling? Every stylization exception, with its evidence | `cmp.manufacturer_canonical` |
| Is `Value` the shortest string that identifies this part on a sheet? Per-category formats | `cmp.value_field` (one variant per category shape) |
| Is `Value` empty, `~`, `N/A`, `-`, an unresolved template, or a copy of the description? | `cmp.value_placeholder` |
| Does `ki_description` follow the family template? The seven parametric categories, and the sub-families deliberately left as free text | `cmp.description` |
| Is every `{Key}` in a description resolvable? | `cmp.templates` |
| Is the `Power` rating spelled the one decided way? (1/16 W is always `63mW`) | `cmp.power_format` |
| Is the part in the right category, checked against the source catalogue? | `cmp.category` |
| Is the MPN and manufacturer confirmed in the datasheet rather than in a distributor feed? | `cmp.mpn` |
| Is the archived datasheet the right document, and a document rather than a web page? | `cmp.datasheet`, `cmp.datasheet_is_document`, `cmp.datasheet_text` |
| Do the part's electrical values match the datasheet? | `cmp.electrical` |
| Is the `VSWR` key spelled without stops? | `cmp.vswr_key` (RF) |
| Required properties, LCSC format, footprint namespace, pin/pad agreement | `cmp.required_props`, `cmp.lcsc_format`, `cmp.footprint_ref`, `cmp.pins_to_pads`, `cmp.pads_to_pins` |

## `comp_type` — what the part IS

Every component carries `comp_type`, an ALL-CAPS single token naming what the
part is: `LDO`, `DCDC`, `OPAMP`, `COMPARATOR`, `LOGIC`, `MCU`, `MLCC`,
`RESISTOR`, `TERMINAL_BLOCK`, `TACTILE_SWITCH`, `ENCLOSURE`, and 80-odd more.
Backfilled across all 442 components on 2026-09-14.

**It is a classification, not a specification**, and that is why it has its own
rule in the carry: setting one where there was none does NOT cost a
verification (`signoff.CLASSIFICATION_KEYS`), because nothing was ever measured
against a value that did not exist. **Changing or removing one DOES**, because
`comp_type` decides which checklist variants a part is judged by.

It is also what lets a DRAWING rule reach a part: `$symbol_comp_types` is the
comp_type of the components on a base symbol, and it is how the op-amp triangle
rules reach `OPA991XDBV` and not a resistor. Add a new token when a genuinely
new kind of part arrives; reuse the existing one when it fits.

## Manufacturer names nobody has resolved — ask, do not guess

The canonical spellings and every stylization exception live in
`cmp.manufacturer_canonical`. These four do not, because no primary source
settles them:

- **`TWGMC`** (on `SS34`) — still unresolved after a second research attempt.
  Only a weak, unquotable claim links it to "Taiwan Dijia Electronics Co., Ltd."
- **`Milliohm`** (on `HoYH0805-3/4W-50mR-1%`, LCSC C42389461) — Shenzhen 毫欧
  电子, whose datasheet and own site (moolee.com.cn) name the company ONLY in
  Chinese. No English brand form exists in the company's own material, so the
  test cannot be applied at all. `Milliohm` is LCSC's brand-page form and a
  literal reading of 毫欧, and it is what the component carries.
- **`TECH PUBLIC`** (on `PESD5V0S1BA`) — consistently ALL-CAPS across every
  distributor, possibly Taizhou Electronics, but no company homepage was found.
  Left as-is; do **not** promote it to a confirmed all-caps brand.
- **`Kinghelm` vs `Shenzhen Kinghelm Elec`** — two sessions used two canonical
  forms for one company. The abbreviated form is on 4 Buttons/RF components; a
  later session normalized a different component to bare `Kinghelm`. **Do not
  silently pick one** — this needs a maintainer decision, then one pass.

Thirteen further names are off the canonical list and visible as warnings on
`cmp.manufacturer_canonical`. Two of those are probably wrong and were left
visible rather than guessed: `Torex Semicon` looks like an LCSC abbreviation of
Torex Semiconductor, and `HanRun` disagrees with the footprint token `Hanrun`.

## Two property keys that are wrong and were not renamed

- **Transistors / BJTs** (`BC817-40-7-F`, `BC847CLT1G`, `MMBT3904,215`) use
  `Continuous Drain Current` for what is actually COLLECTOR current — a
  copy-paste leftover from the NMOS/PMOS base template. The values are correct.
- Renaming a property key is a **material** edit: it strips the verification
  and the sign-off carry. Do it as one dedicated base-symbol-wide pass across
  every affected sibling at once, never piecemeal, and check first whether any
  `ki_description` references the key. `cmp.vswr_key` carries the worked example
  of when such a rename is cheap.

## Open work

- **Connectors terminal-block family** — unify the ~36-member Phoenix-Contact
  style family (plugs, bases, screw terminals, cage-clamp) onto one discrete
  `{Pitch}` template instead of the current three-way free-text convention.
- **Buttons** — backfill verified Length/Width/Height/Force properties across
  the category, then template.
- **`BLM18EG101TN1D`** — `Value = 68nH` against a `100Ω@100MHz` impedance; both
  are real published specs and the rule says impedance. Needs a decision.

## Audit history — check before starting a "first pass"

- **Full-library `Value` audit: 2026-07-25** — 317 components checked, 68 had no
  `Value` at all and were backfilled.
- **Full-library standardization pass: 2026-07-21** — every category audited at
  least once, 308 components checked.
- **`comp_type` backfill: 2026-09-14** — all 442 components classified.

If you are about to start a "first pass" over a category, it has very likely
already been done. Read the checks first.

See [[add-component]] for the full part-creation procedure and
[[platform-workflow]] for what a publish sets in motion.
