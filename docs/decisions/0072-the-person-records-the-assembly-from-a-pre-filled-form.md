---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04 to the semi-automatic assembly proposal)
---

# The person records the assembly step from a form the JLC data pre-fills

## Context and Problem Statement

[0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md)
§2 made receiving the boards record the assembly step, and applying the JLC
order extend it. Each time, the step took every board and assembly position
and every part JLC drew. The previews did not show it, and there was no form.
The user, 2026-10-04: "instead of everything happening without users
knowledge, i want the step to be filled with data from invoices / jlc import
and then applied by the user", and the step must also work by hand "in case
of doing something with different assembly house".

The answers of the same day: receive first, then the assembly; JLC stock
still leaves the pool at invoice import; another house may use our stock or
buy its parts, and may hold our stock as JLC does.

## Decision Drivers

* Nothing about a batch's cost happens without the person seeing it
  (0059: "Nothing is assumed and nothing is automatic").
* The same step for JLC and for any other assembly house.
* A recorded step can be corrected.

## Considered Options

* Keep the automatic step, and show it in the previews.
* A pending step the person confirms, stored as a draft row.
* A form pre-filled on read, applied in one reversible write.

## Decision Outcome

Chosen option: "a form pre-filled on read, applied in one reversible write",
because a draft row would have to be filtered out of every replay (the
journal's own design rejected draft rows for that reason), and a preview of
an automatic step still decides for the person.

1. **Nothing records the assembly step on its own** (supersedes 0060 §2).
   Receiving the boards counts them and makes the twins: the person's count
   decides (0059 §6 stands), and the form starts from JLC's board count.
   Applying a JLC order moves its positions and draws onto the batch, as
   before.
2. **"Record assembly" on Batch → Process opens the step pre-filled**: the
   assembler, the order or invoice reference, the date, and four lists with a
   tick box per row — the board and assembly positions, the parts JLC drew
   from our stock with their lots, the parts the assembler bought (a parts
   total split into them from JLC's BOM, or typed), and the replacements
   JLC's BOM shows. For a batch with no JLC order the parts from our stock
   start from the design BOM × boards.
3. **Apply writes only the ticked rows**, in one journal batch: the step
   joins every received twin not in it, links the positions and draws, draws
   our parts another house used from the batch company's stock (refused when
   short), splits a parts total into the bought parts, and records the
   replacements with the step. A preview runs the same write and undoes it.
4. **A row that arrives later waits** until the person adds it with the same
   form. **"Undo assembly" reverses the write as a whole** through the Ledger.
5. **JLC stock still leaves the pool when the invoice is imported** (0034
   stands), and the import preview shows the stock it moves.

### Consequences

* Good, because the step's cost is what the person ticked, and every source
  of a row is named in the form.
* Good, because another assembly house uses the same step, with our stock or
  with its own parts.
* Bad, because a batch's boards carry no assembly cost until somebody records
  the step. The card says what is waiting.
* Neutral, because stock held at another assembly house is not tracked by
  place yet. The step records who assembled the boards; a stock location is a
  later decision.

### Confirmation

Tests in `api/tests/costs/test_twins.py` show that receiving no longer
records the step, that the step records only the ticked rows, that it waits
for the boards, that a dry run writes nothing and a real write is undone
whole, that another house draws our parts through the step and is refused
when short, that a parts total splits into the bought parts linked to the
step, that a replacement is recorded with the step, and that a row not
offered is refused. On the local copy Batch 8 was received (800 boards),
recorded (32 positions, 21 draws) and undone through the Ledger.

## Pros and Cons of the Options

### Keep the automatic step

* Good, because nobody has to record anything.
* Bad, because the person learns what was decided only after it was.

### A pending step stored as a draft

* Good, because a half-filled form survives a reload.
* Bad, because every replay must leave the draft out.

### A pre-filled form, one reversible write

* Good, because the data is read fresh each time and nothing is stored until
  Apply.
* Bad, because the form must be filled in again after a reload.

## More Information

Supersedes item 2 of
[0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md)
and its Confirmation bullet about receiving. The rules are in
[docs/reference/processes.md](../reference/processes.md).
