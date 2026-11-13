---
status: accepted
date: 2026-11-13
decision-makers: Mateusz Kowalik
consulted: Claude (research and JLC preview test, 2026-11-12/13)
---

# Store the JLC rotation on the component, as the full correction, and keep the footprints as they are

## Context and Problem Statement

JLCPCB places a part with its own land and model for the LCSC part number. Its 0
degrees is that part's own orientation, defined per part number, not KiCad's. Boards
came back from the export with parts turned, and the rotations had to be fixed by hand
in JLC's online editor. Where should the correction live so that every export comes
out right?

What was measured (227 of the 250 project parts, against the EasyEDA land of each
LCSC code, and checked in JLC's placement preview on EVSE_20_CTRL, 2026-11-13):

* 52 of 132 polar or multi-pad parts need a correction (26 by 90 degrees, 26 by 180).
* The correction belongs to the PART, not the footprint. On one `SOT-23-5`, parts
  whose JLC land is `-BL` need 270 and parts whose JLC land is `-BR` need 180. The
  same holds on SOT-353, QFN-16, DFN-8 and LED_0402.
* The 12 offsets stored in footprint files gave a wrong rotation to 5 other parts on
  the same land.
* The Fabrication Toolkit ADDS its own name-keyed table to the field when "Auto
  Translate" is on. Every project had it on. That table is wrong for 27 of our parts,
  and the GUI (default on) and the CLI (default off) give two different files.
* The EasyEDA land predicts JLC's 0 degrees well but not always: U.FL C411563 and
  DSHP08TS C3293147 are known misses.

## Decision Drivers

* A board already laid out must not change.
* Two parts on one land can need different corrections.
* Writing a correction must not cost the part its sign-off or its verification.
* The export must not depend on a plugin option on somebody's desktop.

## Considered Options

* A. Draw the footprints in JLC's orientation.
* B1. Keep the footprints; store the correction on the footprint (the old way).
* B2. Keep the footprints; store the correction on the component, as the full value,
  with Auto Translate off.
* B3. As B2, but in a separate unversioned table.

## Decision Outcome

Chosen option: "B2", because it is the only option that handles two parts on one land,
it changes no copper and no board, and the property already reaches KiCad as a symbol
field with no new code. The owner chose a property over a table (B3) and asked that it
keep the sign-off and the verification.

1. A component carries `FT Rotation Offset` (degrees, counter-clockwise, the FULL
   correction) and, when its origin differs from JLC's, `FT Position Offset` ("x,y" mm,
   footprint frame, y up).
2. Both keys are in `signoff.NON_MATERIAL_KEYS`: writing or changing one keeps the
   production sign-off and the review record.
3. The Fabrication Toolkit runs with "Auto Translate" OFF in every project, so only
   our value applies. The 12 footprint-file offsets are removed, so there is one source.
4. The platform writes its own JLC BOM and CPL into a generated production set
   (`services/jlc_placement.py`), from the board file and the live component values,
   with `top = angle + offset` and `bottom = 180 - angle + offset`.
5. A batch's production page compares the CPL of its current set with what a correct
   export says, and warns on every wrong rotation. It never blocks.
6. A value is measured from JLC's land (`measure_jlc_placement`), and is confirmed in
   JLC's placement preview before it is trusted. The platform does not fetch EasyEDA
   data itself.

### Consequences

* Good, because no board and no copper changes, and a part keeps its sign-off.
* Good, because the platform's own export is right whatever the plugin is set to.
* Bad, because a board must get "Update Symbols from Library" and "Update PCB from
  Schematic" before a Fabrication Toolkit export carries the new fields. The batch
  page's rotation check says when that did not happen.
* Bad, because a measured value is a proposal until a JLC preview confirms it.
* Neutral, because an approved alternate with another LCSC code keeps the main part's
  value; JLC's land for the alternate may differ (not handled here).

### Confirmation

* `api/tests/library/test_jlc_placement.py` holds the rotations confirmed in the JLC
  preview, top and bottom, and the carry of the two keys.
* The batch page's rotation check finds a wrong CPL before an order.
* A second JLC preview of EVSE_20_CTRL and CE_Dongle_V3 with the generated files.

## Pros and Cons of the Options

### A. Draw the footprints in JLC's orientation

* Good, because any generator then works with no field.
* Bad, because 32 footprints would be redrawn and 5 need a rotated copy, and every
  placed instance on every existing board must be turned back by hand: a library
  update turns the pads under the placed part.
* Bad, because it breaks the IPC zero orientation (pin 1 top left) and the in-house
  lands, and it still cannot fix a part like the U.FL.

### B1. Correction on the footprint

* Good, because it was already supported.
* Bad, because a value verified on one part silently applies to every part on the land;
  5 parts were wrong this way.

### B3. A separate table

* Good, because it needs no version and could key on the LCSC code of an alternate.
* Bad, because KiCad needs the value in a symbol field anyway, and the owner chose one
  place that the library already shows.

## More Information

* The research report, the measurement table and the JLC preview result were kept in
  the owner's copy of the 2026-11-12/13 verification work.
* Related: [0108](0108-an-approved-alternate-stands-in-for-a-part-and-the-schematic-stays.md)
  (approved alternates).
* Revisit if JLC publishes its part orientation, or if an alternate with another land
  is placed often enough to need its own value.
