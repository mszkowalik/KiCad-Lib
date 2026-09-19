---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# The production STEP says what a position is; `kind` is gone

## Context and Problem Statement

Every invoice position carried two labels for the same thing:

* **`kind`** — a coarse bucket: `part`, `fab`, `assembly`, `tooling`, `freight`,
  `duty`, `tax`, `rework`, `packaging`, `service`, `other`.
* **`plan_key`** — the production step: "Bare PCB fabrication", "SMT placement",
  "Assembly setup", …

The user put it plainly on 2026-09-19: *"if theres a field that says kind, then
perhaps it could be linked with 'planned as' somehow"*.

They are the same fact at two resolutions, and the catalog had **always said so**
— every entry in `cost_steps.STEPS` carries a `default_kind`, `/api/cost-steps`
sends it to the browser, and `jlc_import._child_kind` already derived one from
the other. Nothing used it to keep the two in step, so they drifted: **12 live
rows** had a `kind` that disagreed with the step beside it.

Reading those 12 showed the disagreement was not operator error. It was the
catalog being too coarse — one step key standing in for two different real
things:

| rows | kind | step | what it really is |
|---:|---|---|---|
| 9 | `fab` | `pcba:general` | JLC billing a **populated board**: one price with the bare PCB inside it |
| 2 | `service` | `final:enclosure_print` | Italtronic's **per-unit** digital print |
| 1 | `tooling` | `final:enclosure_print` | its **one-off** print set-up |

`pcba:general` means "PCB assembly, unsplit" and was also carrying "board,
unsplit, PCB included" — genuinely different money. If `kind` had been derived
from the step all along, both would have forced the catalog to be right instead
of being absorbed silently.

260 of 596 live leaf positions had no step at all, so the coarse field was the
only thing classifying them.

## Decision Drivers

* Two fields for one fact will disagree, and these did.
* The finer field should win: a step can always produce the bucket, a bucket can
  never produce the step.
* Nothing may move. These rows are reconciled against real invoices.

## Considered Options

* The step is the only field; derive the bucket and drop the column.
* Keep `kind` as a projection written on every save.
* Keep both and warn on a mismatch.

## Decision Outcome

Chosen option: **"The step is the only field"** (user decision 2026-09-19),
including dropping the column rather than keeping a derived copy of it.

1. **`run_cost_lines.kind` is DROPPED.** The API no longer accepts it, no writer
   sets it, and the schema no longer has it.
2. **The bucket is derived** with `cost_steps.kind_of(plan_key)`, which reads the
   `default_kind` the catalog has always declared. `line_json` still emits
   `kind` so a reader can recognise "this is assembly money" and `by_kind` still
   reports — those are computed now, not stored.
3. **"Is this stock?" is asked on the step**, through `cost_steps.PART_STEPS` and
   `run_actuals.IS_STOCK` / `is_stock()`. That is ONE definition, used by the six
   modules that ask — `run_actuals`, `jlc_ledger`, `jlc_import`, `jlc_apply`,
   `supplier_parts` and the router. The rejected risk of this option was "a list
   spread across four modules"; it is a single frozenset and a single SQL
   expression instead.
4. **Two new steps, because one key was doing two jobs**: `pcba:populated`
   ("Populated board — fab + assembly, unsplit", user decision after reading the
   invoices) and `final:enclosure_print_setup` ("Enclosure printing — one-off
   set-up"). `final:enclosure_print` is re-declared `service`, which is what the
   per-unit print is.
5. **Two more for the positions that had no step and no catalog entry that
   fitted**: `other:cancelled` ("Cancelled order line") and `other:payment_fee`.
   **Both are excluded by definition** (user decision 2026-09-19): a cancelled
   line was printed, nothing was delivered, and nobody pays for it; a payment fee
   is real money attributable to no product. Four of the five cancelled rows were
   already excluded and the fifth was not — it was the whole of the register's
   standing `unassigned_usd 19.78`, which now reads 0.00. Choosing either step in
   the UI fills the destination in with its reason.
6. **The backfill is SQL in the phase-1 list, in order**, not a Python module.
   Every leaf must have a step before the column that classifies it is dropped,
   and these statements read `kind` to decide — keeping them in one ordered
   sequence is what stops a later edit separating the fill from the drop. Each
   is idempotent and skips headers.
7. **Where a part's money goes already answers which stock step it is**
   (decision 0045): excluded → `parts:prepaid`, charged to a batch →
   `pcba:parts`, otherwise → `parts:pool`.
8. **The UI asks once.** The Kind column is gone, the step column moved to the
   front and is named "What it is" — "Planned as" was a poor name for it even
   with two columns, because the step is not a plan. Choosing a step suggests
   where the money goes, into an empty box only. The table is back to eight
   columns, which pays back the ninth that [0045](0045-a-position-says-where-its-money-goes.md)
   added.

### Consequences

* Good, because the two fields can no longer disagree: there is one.
* Good, because the catalog's `default_kind` stopped being decoration and became
  the definition — which immediately exposed two keys that meant two things.
* Good, because the drift it caused is fixed rather than papered over: the 9
  populated-board lines and the enclosure print/set-up pair now say what they
  are.
* Bad, because `kind` cannot be typed any more, so a position that does not fit
  a step needs a step added to the catalog. That is the intended pressure.
* Neutral on money: 11 rows' derived bucket differs from the old stored one
  (9 `fab`→`assembly`, 2 `other`→`service`). `by_kind` shifts by those amounts
  and nothing else moves.

### Confirmation

Migrated from a restored pre-migration table so the SQL path ran exactly as
production will: 260 leaves filled, 25 headers skipped, 9 re-stepped to
`pcba:populated`, 1 to `final:enclosure_print_setup`, 0 unplaced, column
dropped. Every register figure identical before and after — 86 documents,
155,749.3046 USD, runs 31,085.3758, projects 2,053.37, pool 66,608.0991,
residual 0.0, gap 0.0271 — and run 19 still totals 6,288.5292 USD. The one
intended move is 19.78 from `unassigned` into `excluded` (55,982.6526 →
56,002.4326), leaving `unassigned` at 0.00. 176 tests pass.

## Pros and Cons of the Options

### The step is the only field

* Good, because the finer fact survives and the coarse one is always available
  from it.
* Good, because the schema stops carrying a value nobody may be trusted to type.
* Bad, because dropping a column is irreversible, and six modules had to be
  converted before it was safe.

### Keep `kind` as a projection written on every save

* Good, because the SQL filters stay as they are.
* Bad, because a stored copy of a derived value is the thing this codebase keeps
  removing. One writer today is two writers after the next change.

### Keep both and warn on a mismatch

* Bad, because all 12 mismatches were defensible and 3 were more accurate than
  the catalog. It would have been a warning to learn to ignore.

## More Information

Completes [0045](0045-a-position-says-where-its-money-goes.md), which made a
position state where its money goes; this one makes it state what it is. The
`pcba:parts` step being a `part` position is [0041](0041-the-supplier-parts-lump-is-a-small-bom.md) —
the assembler's own components — and is why "no `pcba` step can be a part" would
have been wrong.

Revisit when a supplier bills something no step describes: the answer is a new
step, and the catalog is the only place to add one.
