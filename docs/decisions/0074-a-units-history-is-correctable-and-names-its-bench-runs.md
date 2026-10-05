---
status: "accepted"
date: 2026-10-05  # accepted 2026-10-05
decision-makers: Mateusz Kowalik
consulted: Claude (the architecture review of 2026-10-04, holes 1–3 and 10–15)
---

# A unit's history is correctable, names its bench runs, and its batch's version is chosen

## Context and Problem Statement

Before the twins go to production, the user asked: "do you see any holes in
the whole process and twin architecture?" The review of 2026-10-04 found 18.
The user chose to fix holes 1–15 before the deploy (2026-10-05), with the
deployment version recorded "per device on its step". Holes 4–9, the rebuild
of old batches, are in [0075](0075-a-rebuild-takes-each-devices-own-records.md).
Holes 16–18 are rows in `docs/todo.md`.

The holes in this record share one cause: a fact entered wrongly, or a fact
that changes later, had no correct way back. A published process version
became current by its number. A wrong click could not be undone. A device
named from the wrong pile, a bench run filed against the wrong device, and a
device disposed of after its finish could not be put right without SQL.

## Decision Drivers

* The production rework creates many process versions for old devices, out
  of date order.
* Every correction is an event a person makes and can undo
  ([0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md)).
* The bench is never blocked ([0037](0037-the-bench-says-what-it-already-knows.md)).
* A device ships only when its history says it is finished (0059 §9).

## Considered Options

For the current version: the highest published number (as before); a
"historical" status that the current-version query skips; a pointer on the
project.

For undo: draft rows that a person approves; one journal batch per click; a
journal batch for bench clicks too.

For a gap device: refuse the rebatch that makes it; let it ship at the batch
average (as before); refuse its shipment until a merge.

For an invoice linked to a whole step: resolve the clicks when the price is
read; store the link and give each new click its row.

For a batch whose units all came from elsewhere: decide now who carries its
origin cost; show the money and refuse the close.

## Decision Outcome

1. **Each bench step on a twin names its bench run and that run's deployment
   version** (`TwinStep.programming_run_id`, `deployment_version_id`). The
   twin card shows the version beside the step, and every later passing
   programming run on the unit as a reflash. The batch does not record a
   version: the units of one batch can differ (user, 2026-10-05).
2. **The current process version is a pointer**
   (`Project.current_process_version_id`). Publish moves it. "Publish as
   history" does not, so a version written for older devices is never
   current. "Make current" moves it to any published version. A batch is
   priced from the version it pinned, not from the current one.
3. **A batch can move to another published version** ("Change process
   version", dry run first). It is refused on a closed batch, and when a twin
   of the batch has done a step the target lacks. The clicks keep the
   version they ran under. The audit row names the previous version, and
   undo is a move back.
4. **Every crafting click is one journal batch**: receive, a step, scrap,
   finish, merge, found, reopen, swap, relink and a cost link. The batch
   screen has "Undo…" on each click that can still be undone. An undo is
   refused while a later click, a bench step or a link stands on what the
   click made, and on a closed batch. Bench clicks are not journalled: the
   bench is never slowed (the register snapshot costs about 0.65 s, twice)
   and its own runs are the evidence.
5. **A gap does not ship.** A device of a crafted batch with no twin is
   refused at shipping until a merge names it, counts as held ("gap") on the
   shelf, and is uncosted on an order: the twins of its batch carry the
   whole batch total already.
6. **A bench step can be stated.** A person can record a test, laser mark or
   label step on named devices with the reason, when no platform bench run
   recorded it. The click reads "stated". A required test, mark or label step
   is refused at publish when the project has no deployment of that kind.
   A crafted batch takes its test rule from its process: a required test
   step, and not `requires_test`.
7. **A wrong bench fact is corrected by a click.** "Swap twin" gives a device
   a board of the right stack, with its programming click, and returns its
   old twin to its own stack, unnamed. "Relink run" moves a bench run to
   the right device with the steps it recorded. The bench warns once when a
   batch programs another batch's boards.
8. **The twin follows the device.** A scrap of a named unit on the batch
   screen disposes of the device. Disposing of a device scraps its twin,
   finished or not. "Reopen for rework" sets a finished unit active again,
   and it ships only after a new finish. A unit in `ok` condition whose twin
   is active or scrapped is held, not available.
9. **A link to a whole step covers later clicks.** The link is stored
   (`CostLineStepKey`), and each new click of that step in that batch gets
   its link when it is written.
10. **Origin cost that no device carries is shown and stops the close.** A
    batch with no alive twin of its own shows the amount, and closing it is
    refused while the amount is not zero. Who carries such money is not
    decided here.

### Consequences

* Good, because the rework can publish versions in any order, and a wrong
  version or a wrong click is put right on the screen.
* Good, because the shelf, the order margin and the device history agree on
  what a unit is.
* Bad, because a manual click now takes about 1.3 s longer, for the two
  register snapshots of its journal batch.
* Bad, because a project needs a mark or test deployment before its process
  can require that step. Until then, the step is optional or stated.
* Neutral, because bench clicks are still corrected by "Swap twin", "Relink
  run" or a later click, not by undo.

### Confirmation

Tests in `api/tests/costs/test_twins.py` (section "decision 0074") show each
rule above: the pointer and history publish, pricing from the pinned version,
the move and its refusals, undo of every click kind and its refusals, the gap
at shipping and on the shelf, the stated step, the publish check, scrap and
disposal in step, reopen, swap, relink, the bench warning, the close refusal,
and a whole-step link reaching later clicks.

## Pros and Cons of the Options

### A "historical" status instead of a pointer

* Good, because no new column.
* Bad, because "current" stays implicit, and an older version can never
  become current again.

### Journalling the batch row for the version move

* Good, because the move would undo like a click.
* Bad, because a batch row changes for many reasons, so every later edit of
  the batch would block an unrelated undo.

### Refusing the rebatch that makes a gap

* Good, because no gap is ever made by a rebatch.
* Bad, because it blocks the fix for a device programmed under the wrong
  batch. The gap it makes is visible, and it cannot ship until a merge.

### Resolving whole-step links when the price is read

* Good, because nothing is written per click.
* Bad, because every reader of a click's links — prices, the unlinked list,
  the twin card, the undo gates — would need to know about key links.

## More Information

Extends [0058](0058-a-process-is-versioned-stages-over-the-pool.md),
[0059](0059-every-unit-has-a-twin-and-programming-names-it.md),
[0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md),
[0061](0061-an-invoice-can-pay-for-several-steps-and-the-benches-record-theirs.md) and
[0072](0072-the-person-records-the-assembly-from-a-pre-filled-form.md).
The rules are in [docs/reference/processes.md](../reference/processes.md).
