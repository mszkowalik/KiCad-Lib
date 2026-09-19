---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# Record a fitted-instead-of part on the BATCH, keyed by designator, and make the design's silence a finding

## Context and Problem Statement

On 2026-09-19, chasing why batch 8 of CE_Dongle_V2 drew no `T491D107K016AT`,
JLC's own BOM answered: designator `C1` carries `C7223`, not `C110548`, on
batches 7 and 8, with `matchType: "update"` where every earlier order says
`"auto"`. `"update"` is JLC saying a human changed the line. The change was
intended. It was never copied into the schematic.

Nothing in the platform knew. The consequences, all real:

* **The wrong part was bought again.** On 2026-08-06, three months after the
  substitution, a purchase of 476 more `C110548` went through at **$1.2296/pc**
  against a historic $0.225–$0.336 — $585.29. 500 pieces sit at JLC with no
  consumer. Purchasing read the design, and the design still asked for it.
* **A BOM line with no draw is indistinguishable from a forgotten one.** On
  batch 8 the substitute came from JLC's shop, so there is no draw at all.
* **Traceability is lost.** "What is actually on the board I shipped" has no
  answer.

A mechanism already existed and could not do the job. `ProductionRun.overrides`
is a JSON blob whose documented shapes include `{"component_id": 319}` —
"replaced by another part". It has never been used for that, only for `drop`,
and three things stop it working:

1. **It is read only on the BOM-estimate path.** Batches 7 and 8 have
   `basis='measured'` draws written from JLC's invoice, so the override code
   never runs — the mechanism is blind exactly where real substitutions appear,
   because a real substitution is something the supplier reports.
2. **Its key dies on the next snapshot.** `b<SnapshotBomLine.id>` belongs to one
   snapshot. Re-export the BOM and every override silently stops matching.
3. **No evidence, no author, no undo, no UI.** It is not a `JOURNALLED` table
   and nothing in `web/src` reads or writes it.

## Decision Drivers

* The design records what was SPECIFIED; it must never be rewritten to match
  what a factory did afterwards. Same split as
  [0034](0034-stock-moves-when-the-supplier-says-so.md).
* The fact is per batch: a device belongs to a batch, so what the batch fitted
  is what is in the device.
* A finding nobody is shown is not a finding. The money was lost to silence,
  not to the substitution.
* The supplier states this in data we already cache. Nothing needs typing.

## Considered Options

* A `RunSubstitution` row, keyed by batch and designator.
* Keep `overrides`, fix its key, and teach the measured path to read it.
* Update the snapshot BOM when the factory changes a part.

## Decision Outcome

Chosen option: "A `RunSubstitution` row".

1. **`run_substitutions`: (run, board, variant, designator) -> specified part,
   fitted part, qty/device, source, evidence, who, when.** Journalled and
   unique per position. `supplier_designator` keeps THEIR reference separately,
   because JLC's stored BOM for an old board carries its pre-KiCad numbering —
   `C1` where the schematic says `C2`, `USB2` for `J1`, `L1` for `L2`.
2. **Keyed by DESIGNATOR, never by BOM line id.** A designator survives a
   re-export; a snapshot row id does not.
3. **Detection compares JLC's BOM against JLC's OWN PREVIOUS BOM**, per BOARD,
   never against our snapshot and never globally. Their designators need no
   mapping to ours that way, and the DESIGN's designator is then recovered by
   looking the superseded part up in the snapshot — reliable precisely because
   the design still names it. Keyed globally instead of per board, `U3` on the
   dongle was compared with `U3` on the Aqua and every board reported a dozen
   substitutions it never made.
4. **Every later batch that keeps the substitute is reported too.** A
   substitution is per batch; reporting only the transition left batch 8, built
   exactly like batch 7, looking as though it followed the design.
5. **Two codes for one library component are not a substitution.**
   `XL-1005SURC` is both `C25503345` and `C965790`, and reporting the switch
   between them put three false rows at the top of a list whose entire value is
   that every row is real. A code nothing has resolved is NOT treated as the
   same — unknown must not silence a real change.
6. **Detection proposes; a person records.** Same rule as
   [0037](0037-the-supplier-keeps-the-receipts.md). JLC changing a line is
   evidence, not a decision.
7. **`design_updated` is the standing finding.** While false and the snapshot
   still names the superseded part, the Stock page says so and reports how many
   of the dead part are still held. That, not the substitution row, is what
   stops the re-order.
8. **A BOM draw takes the fitted part**, noting what it stands in for. The
   `component_id` branch of `run.overrides` is REMOVED; `drop` and `qty_total`
   stay.
9. **WHO DECIDED and WHO SUPPLIED are two fields.** `source` is the first,
   `supplied_by` the second, read from JLC's `componentSource`. The supply side
   decides whether a draw can exist at all, and inferring it from a missing
   draw is wrong in both directions — a part we supplied and never drew is a
   missing draw, and reading that as supplier-supplied would hide it.
10. **Quantity ZERO with nothing named is "left empty".** The same row answers
    the same question — why the design's part is not on this board — and
    silences the same flag. It gives the `drop` override's case an author, a
    reason and an undo.
11. **A planned part in neither the supplier's BOM nor any draw is flagged on
    its row.** Only with the supplier's BOM cached, matched by LCSC code and by
    the component behind it, and never for a part that was drawn — which is
    what keeps cartons out of it.
12. **The UI is the Materials ROW, not a panel beside it.** Substituting is an
   act on a part, so it belongs where the part is. The fold carries the
   control, scoped to one designator or to every position the part sits at
   (a BOM row already groups them, so either is one row), and the folded row
   carries a pill — which is what makes a substitution visible without
   unfolding forty rows to find it.

### Consequences

* Good, because "what was fitted" and "what was specified" are now two facts
  with two sources, and the gap between them is visible instead of costing $585
  in silence.
* Good, because detection is free: the evidence was already cached in
  `jlc_imports.bom_info` and used for `componentSource` alone.
* Good, because a BOM line with no draw is now explainable rather than
  suspicious.
* Bad, because a substitution recorded and then left with `design_updated`
  false forever becomes a banner people learn to ignore. It is a prompt to fix
  the schematic, not a place to file the problem.
* Bad, because detection depends on the supplier's BOM being fetched. An order
  whose BOM was never cached contributes nothing and says nothing about it.
* Neutral, because a batch that split mid-run would need finer grain than this.
  None has, and the row can carry it when one does.

### Confirmation

`api/tests/costs/test_substitutions.py`, fourteen tests. The load-bearing ones:
a changed position is detected and the design's own designator recovered; a
later batch keeping the substitute is detected too; a designator on another
board is never compared; two codes for one component are not a substitution;
drift reports only while the design still names the old part, and says how much
of it is still held; and a BOM draw takes the fitted part.

Against the live database: 3 candidates, all real — two are batches 7 and 8 of
the dongle, the third an `R7` resistor on a prototype run. Before the per-board
scoping it reported 22, almost all nonsense.

## Pros and Cons of the Options

### A `RunSubstitution` row

* Good, because it is readable by anything, journalled, and survives a
  re-export.
* Bad, because it is a new table and a new screen for a case that arises a few
  times a year.

### Fix `overrides`

* Good, because it adds no schema.
* Bad, because every real fix it needs — a stable key, evidence, an author, an
  undo, a reader outside one function — is what makes it a table. Keeping it a
  blob would mean writing all of that into JSON by hand.

### Update the snapshot

* Good, because there is then one BOM and nothing to reconcile.
* Bad, because a snapshot is a record of a moment, like an invoice. Editing it
  to match what a factory did afterwards destroys the only evidence that the
  two ever differed — which is exactly the evidence that was missing here.

## More Information

* [0037](0037-the-supplier-keeps-the-receipts.md) — the supplier's own records
  as the thing our books are checked against; same detect-then-confirm shape.
* [0034](0034-stock-moves-when-the-supplier-says-so.md) — what the supplier
  reports and what we conclude are separate facts, written at different times.
* [production-economics.md](../reference/production-economics.md) — the pool,
  the draw path, and how a substitution reaches it.
* Revisit this if substitutions become routine rather than exceptional. A
  standing list of approved alternates per position is a different design, and
  this record is not it.
