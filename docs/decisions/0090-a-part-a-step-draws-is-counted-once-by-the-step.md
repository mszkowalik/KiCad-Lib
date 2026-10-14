---
status: "accepted"
date: 2026-10-13  # accepted 2026-10-13
decision-makers: Mateusz Kowalik
consulted: Claude (the CE_Dongle_V3 batch 2164 investigation of 2026-10-13)
---

# Count a part that a process step draws once, through the step, and never as a board BOM line too

## Context and Problem Statement

[0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md)
made the process steps the only source of a project's materials beyond the
board. The extra-BOM items stopped counting. The board's schematic BOM did not
change. Some parts are on the schematic AND drawn by a step: the enclosure, the
antennas, the RF pigtails and the lightpipes. `project_bom.priced_bom` counted
these parts twice — once as a BOM line, once as the step's material. "Record
assembly" for a batch with no JLC order also offered every BOM line × boards,
so the parts the steps draw could be drawn twice.

The user reported it on 2026-10-13 while working on CE_Dongle_V3: "components
that are used in process and are present in bom, are used twice". The same
defect existed before, between extra items and schematic symbols (Aqua
components 324/325, [production-economics.md](../reference/production-economics.md)).
0060 moved the materials but did not carry that rule over.

Measured on production on 2026-10-13:

* CE_Dongle_V3 batch 2164 (hw-v3.3 BOM, process v2): ENC2, AE2 and W2 were
  counted twice. AE1 (AEWW031) and W1 (ACA-RFSMA) were also counted, but the
  process replaced them with BW2.4 and a second BWIPX1. Together this is $491.12
  on 60 boards: the planned cost per device was $53.04 and should be $44.86.
* CE_Dongle_V2: ENC1 was counted twice on all seven batches with a snapshot.
* No other project has a process.

## Decision Drivers

* A part is counted once. The step is what draws it, so the step's row is the
  one that counts.
* An OPTIONAL step must be able to leave its part off a device. A BOM line
  charges every device.
* The schematic stays as the designer drew it. Symbols for off-board parts are
  there on purpose ([0005](0005-off-board-parts.md)).
* A batch pinned to an older BOM than its process must also be counted
  correctly, without editing the batch.
* Nothing disappears from a cost without a visible reason.

## Considered Options

* **A. Match by part only.** A BOM line whose part a step on the main route
  draws is counted through the step.
* **B. A, plus: in a project with a process, an off-board BOM line is the
  process's.** It counts only through a step. When no step draws it, it is not
  counted and a warning says so.
* **C. Remove the symbols from the schematic.**
* **D. Remove the inputs from the steps** and let the BOM line count.
* **E. Let a step input name the designators it fits** (`refs: ["LP1", …]`),
  and match by designator.
* **F. Use the off-board flag of 0005 alone.**

## Decision Outcome

Chosen option: **B**, because it is the only option that reaches batch 2164 as
it is pinned, keeps the schematic and the process as they are, and shows every
line it takes out of the BOM total.

* A misses a part the process REPLACED. On batch 2164 the BOM names AEWW031
  and ACA-RFSMA, and the steps draw BW2.4 and BWIPX1. A alone left $100.45 of
  parts the batch does not use in its plan.
* C deletes design intent. D breaks the step draw: JLC does not fit these
  parts, so nothing else would draw them, and the optional lightpipes step
  would charge every device.
* E is the most exact match, but it changes the process document. Batch 2164
  pins process v2, so it would need a new version and a repin. It stays open
  as a later addition, if a replaced part ON the board recurs.
* F misses the parts that are on the board and fitted in-house: the
  lightpipes have a footprint.

The rule, in `process.bom_lines_owned`, which `priced_bom` and
`twins.assembly_draft` share:

1. **A BOM line whose part a step on the main route draws is counted through
   the step.** The match is any shared identity key — component, MPN or LCSC,
   as a draw finds its stock. A prepared part's recipe inputs count as drawn by
   the step that uses it.
2. **An off-board BOM line no step draws is not counted**, and
   `process_warnings` names it.
3. **When the BOM quantity and the step quantity differ, the step's is
   counted**, and `process_warnings` names the difference.
4. The line stays in the BOM with `process_steps` (`[]` for rule 2) and
   `excluded: true`. The BOM page marks it `step` or `no step`. The batch
   economics leave it out and carry the warnings to the Materials tab.
5. "Record assembly" does not offer the line.
6. A project without a process is not affected.

### Consequences

* Good, because the planned cost of every batch of a project with a process
  stops counting these parts twice. That includes closed batches: the plan is
  computed on read.
* Good, because a batch pinned to an older BOM than its process is counted
  from the process, which is what draws.
* Good, because every line taken out of the total stays visible, with the step
  that counts it.
* Bad, because a part ON the board that the process replaced is not reached.
  Batch 2164 still counts LP1–LP3 as FIX-LEMB2-4.8V0-F ($12.96), while its
  lightpipes step draws MENTOR 1293.0050. Its hw-v3.3.1 BOM matches the
  process in full. Repinning the batch to that snapshot, or a run override,
  settles it. Option E would settle it in general.
* Bad, because rule 2 can hide a part somebody forgot to add to a step. The
  warning is the only signal, so it is shown on the BOM page and on the
  batch's Materials tab.
* Neutral: draws already written are not touched. The only path that drew BOM
  lines for a crafted batch was "Record assembly" with no JLC order. Both
  crafted batches on production (CE_Dongle_V2 Batch 8 and CE_Dongle_V3 batch
  2164) have a JLC order, and Batch 8's assembly step holds no draw of a part
  a step draws (checked 2026-10-13).

### Confirmation

* `api/tests/costs/test_process_bom.py`: the five rules, a recipe input, an
  MPN-only input, a DNP line, a project with no process, "Record assembly" and
  the batch economics.
* Measured on production data on 2026-10-13. Batch 2164's hw-v3.3 BOM with
  process v2 gives ENC2, AE2 and W2 to their steps, AE1 and W1 as "no step",
  and one quantity warning for W2. The hw-v3.3.1 BOM matches all five lines,
  with no warnings.

## More Information

* [processes.md](../reference/processes.md), "The project's materials are the
  process inputs".
* [production-economics.md](../reference/production-economics.md), "A project
  with a process has no extra-BOM items that count".
* Revisit with option E when a replaced part ON the board recurs.
