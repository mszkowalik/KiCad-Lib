---
status: "accepted"
date: 2026-10-05  # accepted 2026-10-05
decision-makers: Mateusz Kowalik
consulted: Claude
---

# The bench runs what the batch's process lists

## Context and Problem Statement

A batch's process lists the steps a bench does — Program and Test at the
programming stations, Laser mark and Label at the marking station — and each
step names the procedure (deployment) that says how
([0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md)).
The benches did not use that list. The programming page asked for a
procedure version by hand. The marking page was a second page with its own
procedure picker, a Mark button and a Print button, a link toggle between
them, an Automatic box under each, and a printer and a roll picker. The user
asked to redesign both "to properly use the processes" and to simplify
marking and label printing (2026-10-05).

## Decision Drivers

* The process is the one source of what is done to a unit (0060).
* An operator programs all day, or marks and labels all day.
* There is one laser: one device is marked at a time.
* The roll is part of how a label is made, so the procedure states it.

## Considered Options

For the pages: two pages, each showing its own kind of step; one page where
the process's bench steps are choices.

For marking: one button for every selected marking step; two simpler buttons.

For a batch with no process: a procedure picker in a fold; process only (the
older batches get processes retroactively).

For the label roll: from the procedure, status only; visible pickers.

## Decision Outcome

1. **One bench page.** The operator picks the project and the batch. The page
   shows the process's bench steps in route order, each with the procedure its
   process names (`GET /runs/{id}/bench-stacks` → `steps`), and the operator
   ticks the steps this bench does, remembered per project. A step whose
   process names no procedure is shown and cannot be ticked.
2. **A selection with a marking step uses one station**, laid out around the
   device's serial. Programming alone uses up to four stations.
3. **One button runs the ticked steps in order**, one run per procedure, and
   stops at the first that does not pass. Laser mark and Label that name one
   procedure are one run doing both. "Engrave again" and "Print again" redo
   one action. One Automatic switch for the page.
4. **A crafted batch runs only the procedures its process names**, at each
   procedure's current version; another version needs a reason, as an
   override did before. The run API refuses any other procedure for the batch.
5. **The label roll is the procedure's** (the `print_label` step's `roll`).
   The station shows it with "Change…" for the day another roll is loaded.
6. **A bench trial (no batch) keeps a procedure picker**, drafts included.
   Every batch is to have a process; the older batches get theirs
   retroactively (user, 2026-10-05).

### Consequences

* Good, because the bench offers what the process says and nothing else, so
  a unit cannot be programmed or marked under a procedure its batch does not
  name.
* Good, because marking is one press, with one switch for automatic work.
* Bad, because a batch without a process cannot use the bench until it has
  one, apart from a trial.
* Bad, because a procedure version other than the current one now needs a
  reason on a crafted batch, also where no batch pinned a version before.

### Confirmation

`api/tests/flasher/test_bench_process.py` shows the steps in route order, the
refusal of a procedure the process does not name, and the reason for another
version. The page was checked in a browser on the local copy: Batch 8 of
CE_Dongle_V2 offers Program, Laser mark and Label; marking alone gives one
station with "Mark + label"; CE_Aqua_V2 shows its Laser mark and Label as
having no procedure.

## Pros and Cons of the Options

### Two pages, each showing its own kind of step

* Good, because each page stays small.
* Bad, because an operator who does both, or a process with both on one
  device, needs two pages for one unit.

### Two simpler marking buttons

* Good, because each action stays one press.
* Bad, because the everyday case, mark and label, is two presses or a toggle.

### A procedure picker for a batch with no process

* Good, because old batches keep working on the bench.
* Bad, because the picker is how a unit was made under a procedure nobody
  chose; the older batches get processes instead.

## More Information

Extends [0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md)
and [0021](0021-a-device-is-judged-by-the-rule-it-was-made-under.md). Code:
`web/src/pages/Bench.tsx`, `web/src/components/flasher/BenchStation.tsx`,
`api/app/services/process.py` (`bench_steps`), `api/app/routers/flasher.py`
(`create_run`).
