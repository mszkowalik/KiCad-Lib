---
status: "accepted"
date: 2026-09-11
decision-makers: Mateusz Kowalik
consulted: —
informed: —
---

# Treat a part as off-board when its base symbol declares it and it has no land pattern

## Context and Problem Statement

Some parts are bought, appear on a schematic and belong in the BOM, but never
reach the PCB: a cabled antenna, an RF pigtail, an enclosure with no drawn
outline. They have no footprint, because there is no land to draw.

`generator.set_build_exclusions` forced `on_board = True` for every part
outside the `Simulation` category, so a base symbol's own `(on_board no)` was
discarded. Measured on the live mirror on 2026-09-10: `Antenna_Cabled` and
`RF_Pigtail` were emitted `(on_board yes)` although both sources say `no`, and
the `Antenna_Cabled` v1 comment's claim that this flag is what stops KiCad
reporting a missing footprint was not in force for any of the six affected
parts.

The validator had the matching hole. It answers `na` for BOM-only
(`in_library=False`) parts and for simulation-only parts, but a part that is in
the library AND on a schematic AND has no land was the third case with no
branch, so `cmp.required_props` and `cmp.footprint_ref` failed **by
construction** on every one of them. Agents had been answering `na` by hand,
part by part, since at least 2026-08-25.

How should the platform decide that a part is off the board?

## Decision Drivers

* KiCad must be told, and told consistently by both writers: the generated
  `.kicad_sym` and the HTTP catalog record. KiCad places parts from the HTTP
  record, so patching only the mirror changes nothing in an existing schematic.
* The validator must not disagree with what KiCad is told.
* A footprint somebody simply FORGOT must still be caught. That is the whole
  job of `cmp.footprint_ref`.
* **No change may remove a footprint from a board that already exists.**
* The rule should be derived from state the library already holds, not a new
  field somebody has to remember to set.

## Considered Options

* **A. Honour the base symbol's `(on_board no)` alone.**
* **B. Derive it from the component having no footprint alone.**
* **C. Require both: the symbol declares `(on_board no)` AND the component has
  no footprint.**
* **D. Draw a 0-pad "invisible" footprint for each such part**, as
  `TerminalBlock_Plug_Invisible` already does for 17 terminal-block plugs.
* **E. Add an explicit per-component `off_board` flag.**

## Decision Outcome

Chosen option: **C**, because it is the only option that fixes the defect
without either forgiving a forgotten footprint or deleting a footprint from an
existing board.

Option A fails the last driver, and not theoretically. `TERMINAL_BLOCK_PLUG`
declares `(on_board no)` while every one of its 17 components carries the
deliberate `TerminalBlock_Plug_Invisible` land, which has been placed on real
boards for as long as the generator was overriding the declaration. Honouring
the declaration alone would make the next *Update PCB from Schematic* **delete
those footprints from boards that already exist**.

Option B fails the forgotten-footprint driver: an empty `Footprint` on a
resistor would silently drop it off the board, which is exactly the defect
`cmp.footprint_ref` exists to catch.

Option D was the standing recommendation from a 2026-08-25 review pass, and is
rejected for the cabled parts: an invisible footprint puts a phantom item on the
board, takes a reference designator, and rides in the position file, for a part
that is not on the board at all. The existing terminal-block lands stay as they
are — this decision deliberately preserves them rather than spreading the
pattern.

Option E was rejected because the information is already in the library twice
over, and a flag is one more thing to forget on the next part.

`in_bom` is deliberately **not** derived the same way. Several base symbols
carry an `(in_bom no)` this library does not mean — `RPi_CM5` is a Compute
Module 5, a real purchased part — so honouring that token would drop the most
expensive line on the board out of every BOM. Whether a part is bought stays
`Component.purchasable`.

### Consequences

* Good, because one predicate, `generator.off_board`, is shared by all three
  readers — the mirror, the HTTP catalog and the validator — so what the
  validator forgives and what KiCad is told cannot drift apart.
* Good, because nothing has to be authored per component: the answer is derived
  from the base drawing plus the presence of a footprint.
* Good, because it is reversible per part in the obvious direction. Draw the
  missing land, assign it, and the part goes back on the board automatically —
  which is how the open recommendation to give the three Italtronic enclosures
  real footprints stays compatible with this decision.
* Bad, because the rule needs a base symbol to be edited before a new class of
  off-board part works, and that edit is easy to forget. The symptom is mild:
  the part behaves exactly as it did before this decision.
* Bad, because `in_pos_files` is still authored per symbol and is not derived.
  kiutils does not model it (it survives as an unknown token), so it cannot be
  set the same way.
* Neutral: existing review records are NOT re-run. There is deliberately no
  bulk re-validate, so parts already carrying a `failed` machine record keep it
  until their next publish or until somebody answers it by hand.

### Confirmation

Measured against production after the deploy on 2026-09-11:

* `/files/Symbols/7Sigma_Base.kicad_sym` emits `Antenna_Cabled`, `RF_Pigtail`
  and `Enclosure` as `(on_board no)`, and `R` as `(on_board yes)`.
* `/files/Symbols/RF.kicad_sym` and `Mechanical_7S.kicad_sym` emit the six
  cabled parts and the three footprint-less Italtronic enclosures as
  `(on_board no)`; `Hammond_1556CGY` stays `(on_board yes)`.
* The KiCad HTTP catalog reports `exclude_from_board: true` for exactly 9 of
  441 parts, plus the 5 simulation parts. The 17 terminal-block plugs report
  `false`.
* `validate_component` answers `cmp.required_props` and `cmp.footprint_ref` as
  `na` for an off-board part, `checked` for the terminal-block plugs, and still
  `failed` for an ordinary part whose `Footprint` is empty.

A deploy does not rebuild the mirror. After any change to what the generator
emits, run `update_mirror_symbols(db, settings, None)` or the artifacts stay
stale while the HTTP catalog is already correct.

## More Information

* Implemented in commit `01542c4`: `services/generator.py` (`off_board`,
  `off_board_part`, `set_build_exclusions`, `base_declares_off_board`),
  `services/mirror.py`, `services/validator.py`, `routers/kicad_http.py`.
* `api/CLAUDE.md`, section on `in_bom` / `on_board`, holds the working detail.
* Revisit if a part ever needs to be off the board while carrying a footprint,
  or if `in_pos_files` needs deriving too — neither is possible under this rule.
