---
status: "accepted"
date: 2026-11-09
decision-makers: Mateusz Kowalik
consulted: Claude
---

# Approve an alternate on the part once, and let planning and buying follow it while the schematic stays

## Context and Problem Statement

[0038](0038-a-substitution-belongs-to-the-batch.md) records what a batch fitted
in place of the part the design specifies, and item 7 makes the substitution a
standing finding until `design_updated` says the schematic caught up. That
finding was meant to stop a second purchase of the superseded part: on
2026-08-06, 476 pieces of `C110548` were bought at $1.2296 because purchasing
read the CE_Dongle_V2 schematic, which still names `C110548` at C2 while every
batch since Batch 7 fitted `C7223`.

The user will not change the schematic for every substitution (2026-11-09):
parts change at the supplier more often than a board is redrawn. So the finding
never clears, and the plan keeps planning and pricing the part nobody fits. The
same happened on CE_Dongle_V3 at U7–U10 (TMUX1208, `C2673274` specified,
`C2876797` fitted on Batch 1).

Todo rows 30 (does a substitution steer the plan?) and 31 (nothing detects a
substitution on a batch the supplier does not BOM) asked for this decision.

## Decision Drivers

* The schematic is not edited to follow a supplier.
* A person approves an alternate once, for the part, not once per batch.
* An alternate that is wrong for one circuit (the ESR of a tantalum at an LDO
  output) can be refused in that project.
* Nothing changes the plan without a person's approval.
* The stock of an approved alternate is stock for the part: 500 pieces of
  `C110548` must not read as dead stock while V2 is built with `C7223`.

## Considered Options

* An approved alternate on the library component, one direction, with an
  exception per project.
* An override on the project's BOM position ("C2: use C7223").
* The plan follows the latest substitution of a batch with no approval.
* No change: the finding stays until the schematic is edited.

## Decision Outcome

Chosen option: "An approved alternate on the library component", because it is
one approval per part, it needs no schematic edit, and the per-project
exception keeps the one case where a circuit cares.

1. **`component_alternates`: part → alternate, one direction.** "`C110548` may
   be replaced by `C7223`" says nothing about the reverse; that is a second
   row. Both are library components. The row carries who, when and why, and an
   optional `buy` flag.
2. **Unversioned, like a supplier link** ([0055](0055-a-component-links-to-suppliers-in-a-register.md)).
   Approving an alternate does not change which part a component IS, so it
   costs no verification and mints no version. Removing the row is the undo.
3. **At most one alternate per part carries `buy`.** A purchase proposal for a
   short part names that alternate. Without the flag it names the part the
   design specifies.
4. **`project_alternate_blocks`: the exception.** A project, optionally limited
   to designators, refuses an approved alternate. A blocked alternate is
   treated as not approved in that project, everywhere this record applies.
5. **An approved alternate ends the standing finding of 0038 item 7.** A
   substitution whose fitted part is an approved, unblocked alternate of the
   specified part is not drift. This overrides item 7 of 0038 for that case;
   `design_updated` keeps its meaning for every other one.
6. **The plan counts an approved alternate as the part.** Its free stock and
   its open purchase lines count toward the part the plan needs, unless the
   plan needs the alternate itself (then it keeps its own balance and is not
   counted twice).
7. **A batch draw still takes the fitted part** (0038 item 8). This record
   changes what is planned and bought, never what a batch drew.
8. **Detection stays JLC-only.** A batch the supplier does not BOM (LIFTECH)
   records a substitution by hand on its Materials row, and the Materials tab
   says that the platform did not look. This answers todo row 31.

### Consequences

* Good, because the V2 C2 and V3 U7–U10 findings close with no schematic edit,
  and the 500 pieces of `C110548` count as stock for V2.
* Good, because one approval covers every project and every future batch.
* Bad, because an approval made without looking at one circuit applies to it
  until someone blocks it there. The block exists for exactly that.
* Bad, because the BOM sent to the factory still names the specified part. The
  factory picks the alternate the way it did before: the platform does not
  rewrite the BOM.
* Neutral, because a sale of the alternate, or its price, is still read from
  the alternate's own records.

### Confirmation

`api/tests/costs/test_alternates.py`: an approved alternate ends the drift
finding; a project block brings it back; the reverse direction is not
approved; the plan counts the alternate's stock toward the part and not twice;
the purchase proposal names the `buy` alternate.

## Pros and Cons of the Options

### An approved alternate on the library component

* Good, because one row covers every project.
* Good, because the library is where a person decides what a part may be.
* Bad, because a circuit-specific limit needs a second row (the block).

### An override on the project's BOM position

* Good, because it is exact for one circuit.
* Bad, because every project and every position needs its own click, and the
  same part on V2 and Aqua would be approved twice.
* Bad, because it is a second BOM beside the snapshot, which 0038 rejected for
  good reason: the snapshot records what was specified.

### The plan follows the latest substitution

* Good, because nobody has to click.
* Bad, because a batch-scoped fact silently changes the plan, which is the
  objection todo row 30 raised.

### No change

* Bad, because the finding never clears while the schematic stays, and a
  warning nobody can act on stops being read.

## More Information

* [0038](0038-a-substitution-belongs-to-the-batch.md) — the substitution row;
  item 7 is overridden for an approved alternate.
* [0107](0107-a-plan-owns-its-drafts-and-a-date-is-fixed-or-follows-its-anchor.md) —
  the plan's part balance and purchase proposals.
* Revisit if the factory BOM export should name the `buy` alternate.
