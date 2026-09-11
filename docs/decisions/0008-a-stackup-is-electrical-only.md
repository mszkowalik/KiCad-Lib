# 8. A stackup describes conduction only; appearance and impedance work are project data

Date: 2026-09-11

## Status

Accepted

Extends [0002](0002-field-solver-in-the-platform.md), which put the solver in the
platform and made a board's stackup assignment project data. It does not reverse
anything there.

## Context

[0002](0002-field-solver-in-the-platform.md) settled where a stackup lives — a shared
library, written by administrators, assigned to a board per commit. It did not settle
what a stackup *is*, and three pressures arrived at once that the original shape could
not take.

**Colour.** A board is ordered in a colour, and the colour belongs on screen: a green
board and a red one should not be drawn identically. The obvious place to put it is the
stackup, and that is the trap. `JLC06121H-3313A` in seven mask colours and two legend
colours is fourteen library entries that the solver cannot tell apart — every one of
them conducts identically, so every impedance result is the same, and a person choosing
a stackup has to read past thirteen irrelevant rows to find the one that differs
electrically.

**Faces.** A board is not symmetric. It carries legend on one side or both, and the two
faces can take different finishes. The stackup held one `soldermask`, one `finish` and
no silkscreen at all, so none of that could be said.

**Names.** Copper layers were typed. So a stackup could claim its third copper layer
was called `L5`, and a dielectric could be labelled anything at all — while the only
facts a reader needs are which position a copper layer occupies and what a dielectric
is made of.

At the same time the solver page kept its impedance profiles in browser state, so the
work evaporated on a refresh, and a profile built against a six-layer board could be
saved onto a two-layer one, where its per-layer geometry described nothing.

## Decision

1. **A stackup carries only what changes a field.** Layer order, thickness, material,
   the coating geometry, the surface finish, the legend's presence. It carries no
   colour, and the editor has no colour control. Appearance is drawn from the project.

2. **Board colour is project data, versioned with the assignment.** `mask_color` and
   `silk_color` on `ProjectFieldRevision`, effective from the commit they are set at
   and carried forward, the same copy-on-write rule as the stackup key and the cost
   plan. Choosing a colour writes nothing to the library. The choices are JLCPCB's
   own — green, purple, red, yellow, blue, white, black — and the legend follows the
   mask the way the fab sells it (white on everything but a white mask), overridable.
   The hex values are representative swatches for drawing: JLCPCB publishes colour
   names and no values.

3. **The outer layers are per face.** `faces: {top, bottom}` for silkscreen, solder
   mask and finish. A bare value still means "both faces", so every stackup written
   before this reads without migration, and `soldermask` / `finish` / `silkscreen` at
   the top level keep meaning THE TOP FACE — which is the only face the solver coats
   (`templates.py` guards every mask region with `outer_top`). Changing what those
   three mean would have silently changed every solved geometry.

4. **A stackup is normalised on save, and an unbuildable one is refused.** Copper is
   named `L1`…`Ln` by position, never typed. A dielectric's label is generated from its
   material and the copper pair it lies between, because the type and the position are
   the whole of what a reader needs and KiCad only wants *a* name. Copper may never
   touch copper — there is no insulation between two adjacent copper layers, so the
   board cannot be built and the solver would model a different one without
   complaining. Several dielectrics in a row are explicitly allowed: a fab lists each
   prepreg sheet, and `JLC06121H-3313A` has three in one gap.

5. **Impedance profiles are banked per stackup, in the database.** One row per person
   (`field_workspaces`), holding the solver page's own state keyed by the stackup each
   set was built against. A profile's cells are keyed by copper layer name, so
   switching stackups parks the open set and picks up whatever was left on the one
   being opened rather than carrying geometry onto layers that do not exist.

6. **Saving profiles to a board is all-or-nothing and refuses a stackup mismatch.**
   One batch endpoint, because the revision is copy-on-write and a half-failed sequence
   would leave some profiles saved. A geometry means nothing against a stackup it was
   not solved on, so saving onto a board assigned something else writes nothing and
   says so — enforced server-side, since the agent tools use the same path.

## Consequences

**Good.** The library stays the size of the set of physically distinct builds. A
stackup cannot be saved in a state no fab can build. Work in the solver survives a
refresh and cannot be silently attached to the wrong board. A board's two faces can
differ, which is how boards are actually ordered.

**The cost.** `soldermask`, `finish` and `silkscreen` now mean the top face where they
used to mean the board, which is a subtlety anything reading a stackup has to know —
it is why they are documented in `api/CLAUDE.md` and why `faces` exists beside them
rather than replacing them. And the per-face finish is not yet used by the solver: it
still coats only the top, so a signal on the bottom layer is solved without a mask, as
it was before.

**Not decided here.** The board colour is used for drawing the stackup; it is not fed
to the field solver's cross-section, which still draws the mask in the palette's
generic green. That was deliberate — the colour of the ink does not change the field —
and can be revisited if the picture is wanted in the board's own colours.
