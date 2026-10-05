---
status: "accepted"
date: 2026-10-05  # accepted 2026-10-05
decision-makers: Mateusz Kowalik
consulted: Claude (the architecture review of 2026-10-04, holes 4–9)
---

# A rebuild takes each device's own records, and can be corrected

## Context and Problem Statement

The production rework gives every batch made before twins its twins
([0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md)
§7), and then fills in each produced device's process history. The review of
2026-10-04 found that the rebuild could not do that truthfully (holes 4–9).
On the local copy it put the test step on every Aqua device, although most
had no passing test. It gave laser and label to all 1025 devices of Dongle
Batch 7, of which about 48 were marked in-house. It made every in-stock unit
finished, also in a batch still being programmed. It linked a whole BOM draw
to a step whatever its quantity (800 cartons for 200 Batch 8 devices). It
dated every step with the batch's date. And after the first live click on a
rebuilt twin, the rebuild could not be undone, extended or corrected.

The user chose to fix holes 1–15 before the deploy (2026-10-05).
[0074](0074-a-units-history-is-correctable-and-names-its-bench-runs.md)
holds holes 1–3 and 10–15.

## Decision Drivers

* Nothing is invented (0060, rebuild rule 1): a step on a unit needs evidence
  about that unit, or a person's statement.
* A bench record that says a step was NOT done is evidence too.
* The batches' money moves only by what the rebuild draws or returns.
* The rework runs in iterations, so a rebuild must be undone, extended and
  re-run without SQL.

## Considered Options

For bench steps: an evidence flag per step, set by the person; the device's
own bench runs, always.

For a draw that does not match units × quantity: link it as it is (as
before); refuse until each difference is stated; split and settle per click.

For the undo: rebuild the old state from notes and audit rows; reverse one
journal batch.

For units built on another batch's boards: leave their origin as the
programming batch (as before); name the source batch in the rebuild.

## Decision Outcome

1. **Old bench runs are linked to their devices first**, by the topic each
   run captured, only where it names exactly one device of the project
   (`POST /projects/{id}/bench-runs/link-by-topic`, dry run first). The job
   links runs and records no step.
2. **A test, laser mark or label step comes from the device's own run**: a
   passing test, or a marking run that says `marked` or `printed`. There is
   one click per day and deployment version, and each twin's step names its
   run. A failed test, or a marking run that had the op and did nothing, is a
   record that the step was not done, and a statement does not override it.
3. **An invoice position is money, never proof.** A position whose steps have
   no evidence stays in the origin batch cost. A position linked to steps is
   stored as a whole-step link, so live clicks recorded later share it.
4. **A statement covers only devices with no bench record of the step**, and
   names all devices, a device list, codes or a date range.
5. **A unit still in work stays active** (`active`), so it takes its later
   bench and batch steps live.
6. **Each step is dated by the device**: before programming, the earlier of
   the batch date and the first programming day; after programming, the bench
   run's date, else the programming day; a scrap, the disposal's date.
7. **Drawn parts are compared with units × quantity per step and part.** A
   difference above `tolerance` is refused until it is stated: `draw` or
   `short` for a deficit, `return` or `loss` for a surplus. A draw that feeds
   several clicks is split at the same unit cost, with its lot bindings.
8. **A rebuild is one journal batch.** "Undo rebuild" takes back the live
   clicks on its twins first, then reverses that batch, lot bindings
   included. The Ledger refuses to reverse it alone, because the batch's
   pinned version is no journalled row.
9. **`append` gives devices that joined a rebuilt batch later their twins**,
   and **`origins` gives devices built on another batch's boards that batch as
   their origin**, with the money check over both. An unknown source is
   stated, and written on the twin's note.
10. **A rebatch refuses a device whose twin was rebuilt**, and found units are
    refused while their origin batch holds unnamed units of its own: counted
    spares enter by `spares` only.
11. **The dry run is the review**: a per-device plan, the parts table, what
    is unsettled, the money check and every refusal. The production rework
    order per batch is in [processes.md](../reference/processes.md).

### Consequences

* Good, because a rebuilt history says only what a record or a person says.
* Good, because a rebuild can be undone, extended and corrected while the
  bench keeps working on the same batch.
* Bad, because a rebuild now needs more input: the bench-run link job first,
  statements for every difference in parts, and the rework order kept.
* Bad, because the plan of a large batch is big (about 650 KB for Dongle
  Batch 7 on the local copy).

### Confirmation

`api/tests/costs/test_twin_rebuild_evidence.py` shows each rule above, and the
rebuild tests in `api/tests/costs/test_twins.py` still pass. Local dry runs:
Aqua Batch 4 records the test on the 31 devices with a pass and lists the 72
with only failed tests; Dongle Batch 7, after the link job, records laser and
label only on the devices with marking runs.

## Pros and Cons of the Options

### An evidence flag per step

* Good, because the person decides what counts.
* Bad, because a draw or an invoice could prove a bench step again.

### A statement that overrides a failed run

* Good, because a test redone off-platform could be recorded.
* Bad, because the failed run is evidence that the step was not done. A
  stated step on the batch screen (0074) covers a step done later.

### An undo rebuilt from notes and audit rows

* Good, because no journal is needed.
* Bad, because it cannot restore split draws and lot bindings exactly.

### New draws per click, with the old BOM draw voided

* Good, because each click gets clean draws.
* Bad, because the new draws are priced again, so money moves.

### Origins from a batch that is not rebuilt

* Good, because the batches can be rebuilt in any order.
* Bad, because the source batch's other devices keep its average, so orders
  would count its cost twice.

## More Information

Extends [0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md),
[0073](0073-a-draw-takes-the-cost-of-the-lots-it-is-bound-to.md) and
[0074](0074-a-units-history-is-correctable-and-names-its-bench-runs.md).
Code: `api/app/services/twin_rebuild.py`, `api/app/services/bench_links.py`.
