---
status: "accepted"
date: 2026-10-24  # accepted 2026-10-24
decision-makers: Mateusz Kowalik
consulted: Claude (after phase 1 of 0097 found no difference on production)
---

# Switch to the material ledger in one cut-over

## Context and Problem Statement

Decision [0097](0097-keep-stock-work-and-units-in-one-material-ledger.md)
accepted the material ledger and five phases to reach it: a shadow with
parity checks, then the writes, then the readers, then the new abilities,
then the old tables retire. Phase 1 was deployed on 2026-10-23 (37424e3) and
its first parity run on production found no difference: 207 parts, 495 lots,
860 units.

The user asked on 2026-10-23 for a full rewrite that uses only the new
system, and on 2026-10-24 chose to rewrite all the code in the new model's
terms rather than keep the working code behind typed views of the old names.

## Decision Drivers

* One storage for stock, work and units: no shadow, no double writing.
* Phase 1 already proved that the ledger holds all of production's data.
* The figures before and after the switch must be the same, answer by answer.
* A failed switch must leave production on the old code and untouched data.

## Considered Options

* One cut-over: rewrite every reader and writer, migrate once at startup.
* The phases of 0097: the ledger takes the writes beside the old tables,
  then the readers move.
* Keep the working code and point its old class names at the new tables.

## Decision Outcome

Chosen option: "one cut-over" (user, 2026-10-23 and 2026-10-24). This
amends item 9 of 0097: phases 2, 3 and 5 become one switch. Phase 4, the new
abilities, follows on the new tables.

1. **The ledger's tables are the only storage** of draws, adjustments, lot
   bindings, makes (transformations), clicks, units (twins), the units a
   click acted on, and the positions aimed at clicks or steps. The
   `run_cost_lines` and `run_substitutions` columns that name a make or a
   click keep their names.
2. **One migration at startup, in one transaction** (`services/material_ledger
   /cutover.py`). It copies the nine old tables, keeps every id that does not
   collide, and renames them `legacy_<name>`. A failure stops the start; the
   old image then runs on untouched tables.
3. **The legacy tables are read only** and carry no journal trigger. A
   Write-log undo, a request undo or a rebuild undo of a write made before the
   switch is refused, and says why.
4. **The API keeps every field name.** `lot_adjustment_id`, `step_run_id`,
   `twin_id`, `consumption_id`, `transformation_id` now name a stored lot, a
   click, a unit, a draw, a make. The web does not change.
5. **The proof is the answers.** `scripts/ledger-golden.py` captures 13,777
   read answers before the switch and again after it; they must be equal, on
   a copy of production first and on production at the deploy.

### Consequences

* Good, because the platform has one model for stock, work and units, and
  the abilities of 0097 phase 4 are built on it directly.
* Good, because nothing is written twice and nothing has to stay in step.
* Bad, because one deploy changes every stock and unit path at once. The
  golden answers and the full test suite are the guard; a restore of the
  backup taken before the deploy is the way back, and loses what was written
  since.
* Bad, because no write made before the switch can be undone any more.
* Neutral, because the legacy tables stay until a later decision removes
  them.

### Confirmation

On the production copy and then on production: the golden answers after the
switch equal those before it, the test suite passes, and the startup reports
`ledger.cutover: ok` on `GET /api/health/schema`.

## Pros and Cons of the Options

### One cut-over

* Good, because there is one system after one deploy.
* Bad, because of the size of the one deploy.

### The phases of 0097

* Good, because each step is small and can be undone.
* Bad, because every writer is written twice for weeks, and phase 1 already
  gave the proof the phases were meant to give.

### Typed views of the old names

* Good, because the working code and its tests stay unchanged.
* Bad, because the code would keep the old model's words over the new
  model's tables. The user chose the rewrite.

## More Information

The plan and the conventions of the rewrite are in
[docs/material-ledger/cutover.md](../material-ledger/cutover.md).
