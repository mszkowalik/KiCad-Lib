---
name: kicad-conventions-library
description: "Component DATA conventions: the index of every rule with the check that holds it, plus the manufacturer names decided without a company source. The rules themselves live in the component checklist — read them with get_review_checklist('component'). Use when setting Value, ki_description, Manufacturer 1 or a category."
---
<!-- platform-skill: conventions-library v49 — source of truth is the platform; check with list_skills, refresh with get_skill -->
# Library conventions

**The rules are checks now, not prose.** Every convention this document used to
state is a checklist item on the component checklist, and the item carries the
data: the canonical manufacturer spellings and the evidence behind each one, the
Value formats per category, the description templates per sub-family, the power
spellings, the category-placement rule. Read them with
`get_review_checklist("component")` — once, before you author or verify.

What is left here is what a check cannot hold: the names decided without a
source, and where to look when a rule does not fit.

## Where each rule lives

| Question | Check |
|---|---|
| Is `Manufacturer 1` the company's own brand spelling? Every stylization exception, with its evidence | `cmp.manufacturer_canonical` |
| Is `Value` the shortest string that identifies this part on a sheet? Per-category formats | `cmp.value_field` (one variant per category shape) |
| Is `Value` empty, `~`, `N/A`, `-`, an unresolved template, or a copy of the description? | `cmp.value_placeholder` |
| Does `ki_description` follow the family template? The seven parametric categories, the sub-family templates with their keys and traps (LDO, DC-DC, logic, MCU, FFC and the rest), and the sub-families deliberately left as free text | `cmp.description` |
| Is every `{Key}` in a description resolvable? | `cmp.templates` |
| Is the `Power` rating spelled the one decided way? (1/16 W is always `63mW`) | `cmp.power_format` |
| Is the part in the right category, checked against the source catalogue? | `cmp.category` |
| Is the MPN and manufacturer confirmed in the datasheet rather than in a distributor feed? | `cmp.mpn` |
| Is the archived datasheet the right document, and a document rather than a web page? | `cmp.datasheet`, `cmp.datasheet_is_document`, `cmp.datasheet_text` |
| Do the part's electrical values match the datasheet? | `cmp.electrical` |
| Is the `VSWR` key spelled without stops? | `cmp.vswr_key` (RF) |
| Required properties, LCSC format, footprint namespace, pin/pad agreement | `cmp.required_props`, `cmp.lcsc_format`, `cmp.footprint_ref`, `cmp.pins_to_pads`, `cmp.pads_to_pins` |

## Where the part is bought — a link, not a property

`Supplier N` and `Supplier Part Number N` are NOT properties (decision 0055,
2026-09-29). The proposal tools and the component editor refuse them, and the
generator never emits them to KiCad. `LCSC Part` stays a property: the KiCad
BOM export reads it, and the JLCPCB and LCSC links follow it. Any other source
is a supplier link: `link_supplier(component, supplier, part_number)`, with the
supplier's own order code. `list_suppliers` is the register in library order;
an admin adds a supplier. The first supplier in a part's order that has prices
prices the BOM.

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

**`comp_type` is THE discriminator inside a category, and the platform uses no
subcategories** (user decision 2026-11-09, decision 0109). A category whose
parts follow different rules (Inductors: inductor, ferrite, choke,
transformer) splits its checks into variants on `comp_type`; it never grows a
child category. `Category.parent_id` exists in the schema and stays unused.

## Manufacturer names decided without a company source

The canonical spellings and every stylization exception live in
`cmp.manufacturer_canonical`. Four names had no primary source and were decided
by the user on 2026-11-09, so they are no longer open:

- **`Kinghelm`** is the one name for Shenzhen Kinghelm Electronics. The four
  Buttons parts that carried `Shenzhen Kinghelm Elec` were renamed, and that
  form is off the list.
- **`TWGMC`** (on `SS34`), **`Milliohm`** (Shenzhen 毫欧电子, which names itself
  only in Chinese) and **`TECH PUBLIC`** (on `PESD5V0S1BA`) are kept exactly as
  written and are on the list.

Renaming `Manufacturer 1` is a material edit: the four Kinghelm parts lost their
component verification and need it again.

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
