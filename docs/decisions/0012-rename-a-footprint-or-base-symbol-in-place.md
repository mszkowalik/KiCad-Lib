---
status: "accepted"
date: 2026-09-13
decision-makers: Mateusz Kowalik
consulted: Jaravis (agent), who surveyed the reference paths
informed: anyone who names a footprint or a base symbol, and anyone whose board carries one
---

# Rename a footprint or a base symbol in place, and rewrite every reference with it

## Context and Problem Statement

The platform can create a footprint and a base symbol, publish new versions of
each, and delete one. It cannot rename either. The name is set when the row is
created and no code path changes it.

The workaround does not exist either. `DELETE /api/footprints/{id}` refuses
while ANY component version pins ANY version of the row, which is the normal
state of a footprint in use. Creating a replacement row under the correct name
and deleting the old one would also discard the version history, the machine
validation records, the review record and the production sign-off — none of
which a new row can inherit.

The case that raised it: `L_Changjiang_FTC404030S` carries the vendor token
`Changjiang`. The canonical manufacturer name was decided as `CJIANG` on
2026-09-13, from the datasheet letterhead and the LCSC brand field. The
footprint must become `L_CJIANG_FTC404030S`. A second fact makes the rename
more than cosmetic: `L_Changjiang_FTC404030S.kicad_mod` is a KiCad **stock**
filename, and our copper is not the stock copper. Stock pads sit at ±1.35 mm
and ours at ±1.4 mm. Holding a stock filename over a different land pattern is
the exact claim the footprint conventions forbid.

## Decision Drivers

* A wrong name is a data defect, and every other data defect in the platform
  is fixable in place, with history kept.
* A name is a REFERENCE, not only a label. `ComponentVersion.base_component`
  holds a symbol name as a string. A component's `Footprint` property holds
  `7Sigma:<footprint name>`. Both are copied, not joined.
* A verification says "the data matches the documentation". A rename changes
  no datum that a verification measured, so it must not cost one.
* Version rows are immutable. A rename must not rewrite history.
* The library has 212 footprints and 206 base symbols. One base symbol serves
  95 current components, so a symbol rename is a bulk operation.
* Renaming is rare and outward-facing. Other people's boards carry the old
  name inside their `.kicad_pcb` and `.kicad_sch` files.

## Considered Options

* Leave renaming out. Live with a wrong name, or create a new row and orphan
  the old one.
* Rewrite the name across all historical version rows and all component
  property rows in place, with no new version.
* Replace the name references with foreign keys, so a rename is one `UPDATE`.
* Rename the row, publish ONE new geometry version carrying the new name, and
  publish ONE new component version for each affected component.

## Decision Outcome

Chosen option: **rename the row, publish one new geometry version, and publish
one new component version per affected component**, because it is the only
option that moves the name without rewriting history and without discarding
the review record.

A rename does all of the following in one transaction:

1. Publishes one new footprint or symbol version whose text carries the new
   name. `services/material.py` fingerprints pads, drills, layers and the
   courtyard for a footprint, and pin numbers and electrical types for a
   symbol. A name is in neither, so the material fingerprint does not move and
   `review.carry_geometry` carries the verification.
2. Sets `footprints.name` or `symbols.name`.
3. Publishes one new component version for each component whose CURRENT
   version references the old name, with only that reference rewritten. The
   pinned `symbol_version_id` and `footprint_version_id` do not move.
4. Rewrites the stale name in `categories.defaults`.
5. Rebuilds the mirror. A footprint rename also unlinks the old
   `.kicad_mod` from `Footprints/7Sigma.pretty/`.
6. Writes one `footprint.rename` or `symbol.rename` audit row naming both
   names and every component touched.

**A rename carries the verification and the production sign-off.**
`signoff.data_carries` treats `base_component` and the `Footprint` property as
MATERIAL, and that stays true for every other caller. The rename passes the
one rename pair it is performing, and the comparison maps the old name to the
new one before it compares. The part, the land pattern, the pin map and the
drawing are identical, so the verification that was recorded against them is
still true.

**History keeps the old name.** Superseded geometry versions keep the old
header, and superseded component versions keep the old reference string. Both
are correct: those rows record what was published at the time.

### Consequences

* Good, because a wrong name is now a fixable defect instead of a permanent
  one, and the fix keeps the version history, the review record and the
  sign-off.
* Good, because it removes the reason to abuse delete-and-recreate, which
  would silently discard all three.
* Good, because the audit row plus the superseded versions are a complete
  revert path. Renaming back is the same operation.
* Bad, because a base-symbol rename on a popular symbol publishes up to 95
  component versions in one transaction. It is slow and it fills the change
  feed. Accepted: a rename is rare and the alternative is a wrong name.
* Bad, because it adds the first exemption to the material-property allow-list
  in `services/signoff.py`. The allow-list's value comes from being narrow.
  The exemption is confined to one caller and to the exact pair being renamed,
  and it is compared as a mapping, never as a wildcard.
* Bad, because a schematic or a board already placed carries the old name. The
  geometry is embedded in the board file, so nothing breaks, but KiCad reports
  the old library id as missing until the project is updated from the
  schematic. Two boards carry the first case, `CE_Dongle_V3` and
  `EVSE_20_CTRL`.
* Neutral, because the KiCad HTTP library and the PCM packages read the live
  name, so a user who presses Sync gets the new name with no extra step.

### Confirmation

* After renaming `L_Changjiang_FTC404030S` to `L_CJIANG_FTC404030S`:
  `get_footprint("L_CJIANG_FTC404030S")` answers, the old name 404s, the
  version history still shows five earlier versions plus the rename version,
  and the review record on `FTC404030S4R7MGCA` is still live.
* `Footprints/7Sigma.pretty/` holds `L_CJIANG_FTC404030S.kicad_mod` and no
  file under the old name, and `manifest.json` agrees.
* `component_properties` holds no `Footprint` value equal to
  `7Sigma:L_Changjiang_FTC404030S` on any CURRENT component version. Nine
  superseded rows still hold it, which is the intended outcome.
* `categories.defaults` for `Inductors` maps `SMD,4.1x4.1mm` to the new name.
* Renaming a base symbol used by one component carries that component's
  sign-off, and changing its base symbol to a DIFFERENT symbol still costs
  it — the exemption did not widen.

## Pros and Cons of the Options

### Leave renaming out

* Good, because it costs nothing and adds no exemption.
* Bad, because the library keeps names it knows are wrong, and one of them
  claims a KiCad stock filename over copper that is not stock.
* Bad, because it pushes people toward delete-and-recreate, which loses
  history and is refused anyway while the row is in use.

### Rewrite the name in place across every version and property row

* Good, because it is a handful of `UPDATE` statements and it is fast.
* Good, because no component version is minted, so nothing can strip a
  verification.
* Bad, because it rewrites immutable rows. A superseded version would claim a
  name it never published under, and the mirror history and the git archive
  would disagree with the database.
* Bad, because it leaves no audit trail that reads as an event.

### Replace the name references with foreign keys

* Good, because a rename becomes one `UPDATE` and the class of bug disappears.
* Good, because it removes the possibility of a component version pointing at
  a base symbol that does not exist.
* Bad, because `base_component` and the `Footprint` property are also the
  KiCad-facing strings. They are written into `7Sigma_Base.kicad_sym`, into
  `symbolIdStr` in the HTTP catalog, and into every generated symbol. A
  foreign key does not remove the string, it adds a second source of truth
  beside it.
* Bad, because it is a migration of every component version in the library to
  earn a capability used a few times a year.

### Rename in place with a new version on each side (chosen)

* Good, because it uses the publish path every other write uses, so the
  carries, the machine validation and the audit trail all happen for free.
* Good, because history stays immutable and readable.
* Bad, because it is a bulk publish on a popular base symbol.
* Bad, because it needs the material-property exemption described above.

## More Information

* `api/app/services/rename.py` — the operation.
* `api/app/services/signoff.py` — `NON_MATERIAL_KEYS` and `data_carries`, and
  why the exemption is a mapping rather than a new allow-list entry.
* [../reference/review-axis.md](../reference/review-axis.md) — what a carry
  means.
* The footprint conventions skill, section on the KLC tier rule — Tier 0 stock
  names are frozen, and a name equal to a stock filename must not be minted
  unless the copper matches.
* Revisit if renaming becomes common. At that point the foreign-key option is
  worth its migration, because the bulk publish is the cost that scales.
