---
status: "accepted"
date: 2026-10-03  # accepted 2026-10-03
decision-makers: Mateusz Kowalik
consulted: Claude (design discussion 2026-10-03, after the local build of 0059)
---

# Make the process the one source of a unit's history, materials and cost

## Context and Problem Statement

Claude built [0059](0059-every-unit-has-a-twin-and-programming-names-it.md) on a
local copy on 2026-10-03, and nobody deployed it. Several mechanisms still ran beside
the process:

* The board's own manufacture was one lump. The board and assembly invoices
  (setup, stencil, SMT placement, the parts JLC bought) and the parts JLC drew
  from our stock were all "origin batch cost", split equally and named by
  nothing.
* A batch made before twins had none, so its devices kept the batch average
  ([0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md)) and no
  history of steps.
* The deployments that describe programming, laser marking and label printing
  belonged to a project, but not to the process step they perform.
* A material could enter a batch outside any step: an extra BOM item on the
  project, a hand-typed draw on the batch, or a "used" quantity typed in the
  Materials tab.
* A person typed the board and assembly prices as cost items of the project.

The user asked for one mechanism (2026-10-03). The board's assembly becomes a
process step made from the JLC data. Old batches split into twins. Each
deployment links to its step. Materials come only from steps. A batch's
manufacturing cost comes from its steps.

## Decision Drivers

* One mechanism: processes, steps, the material use of steps and the invoices
  that paid for them.
* A twin's history starts where the board starts: its assembly at the
  supplier.
* Invent nothing. A fact on a twin is a supplier's statement, a bench
  reading, a person's statement or a record, and it says which.
* No money moves between batches. Stock and value stay on the single pool
  replay, and the register's gap stays zero.
* JLC sends its invoices when the order ships, so the data is there when the
  boards arrive (user, 2026-10-03).

## Considered Options

* The board's assembly as one step, with the supplier's fees as its cost
  lines.
* One step for each fee (setup, stencil, SMT placement, and so on).
* The assembly stays in the origin batch cost (0059 as built).
* The twins start when a person links the assembly order, before the boards
  arrive.

## Decision Outcome

Chosen option: "the board's assembly as one step, with the supplier's fees as
its cost lines" (user, 2026-10-03). A step is something done to a unit. The
stencil and the setup are prices of one job, not steps, so one step per fee
adds a row per fee to every unit and no new fact.

### The assembly step

1. **A process has exactly one `assembly` step**, done at the supplier. Every
   unit needs it. It needs nothing and lists no parts.
2. **Receiving the boards records it** from the batch's assembly order
   (`chosen = "supplier"`). A person still counts the boards at
   "receive", and that count makes the twins (0059 §6 stands). The step
   links the order's measured draws (our stock at JLC, each bound to its lot)
   and every board and assembly position charged to the batch (`fab:*`,
   `pcba:*`, including the parts JLC bought). A position that arrives later joins
   the same step, from the crafting screen or when the JLC order applies.
3. **The twin shows what the supplier fitted**: the supplier's own BOM for its
   order (`jlc_imports.bom_info`), position by position, with who supplied
   each part (our stock, the supplier, or both). The designators are the
   supplier's.

### Costs belong to steps

4. **An invoice position can say which step click it paid for**
   (`RunCostLine.step_run_id`). The money stays charged to its batch. The link
   only says which twins carry it, 1/N each. The position must go to the batch
   of the click. A closed batch refuses a new link, and a split keeps the
   link. A person links the final assembler's invoice, a print service or a
   packing service to its step on the crafting screen.
5. **A twin's price is its own parts, plus the invoices of its steps, plus its
   origin share.** The origin batch cost is the batch's total minus every step
   draw and every linked position, so it holds only what no step claims:
   freight, customs, discounts and payment fees. This amends 0059 §11.
6. **A batch's manufacturing cost comes from its steps.** The crafting
   screen shows the cost by step. The board and its assembly are the assembly
   step's figures. The rows add up to the batch's total in the register. The
   project's planned cost items stay, to estimate a batch that does not exist
   yet.

### Old batches get twins

7. **A batch made before twins gets its twins from its records**
   (`services/twin_rebuild.py`). This amends 0059 §13 for every batch rebuilt:
   * one named twin for each device the batch produced.
   * unnamed twins for spares a stock count found, when the count names their
     batch. They carry a share of their batch's cost, not zero. This amends
     0059 §15 for those units.
   * a step with parts goes on the twins only when the batch drew those
     parts. A step without parts goes on only when a person states it
     happened. Programming comes from each device's `produced` event. Every
     rebuilt click says `chosen = "rebuilt"`.
   * a twin's status comes from its device. A disposed device gives a
     scrapped twin, a faulty or incomplete one an active twin, any other a
     finished twin. A rebuilt finish names the required steps that have no
     record.
   * no money moves. The rebuild writes only the links, and it refuses to
     keep anything unless the twins' prices add up to the batch's total.
   * an undo takes it back while no live step sits on top.

   A device with no batch stays without a twin and keeps today's rule.

### Bench steps name their deployment

8. **A programming, laser marking or label step names the deployment that
   tells how to do it**: a `flash` deployment for programming, a `mark` deployment
   for marking and labels, of the same project. The deployment stays the
   project's. The process only points at it. The process map shows it and
   links to it.
9. **The programming bench starts on the version the process names** for a
   crafted batch. The marking bench records the step that names the run's
   deployment, or a step that names none. It warns when the unit has not done
   what the step needs (laser marking before the enclosure), and never blocks
   ([0037](0037-the-bench-says-what-it-already-knows.md)). The bench makes
   the mark, and the step goes on the twin once its needs are met.

### Materials come only from steps

10. **For a project with a process, a device's materials are the inputs of the
    steps on its main route** (a prepared part counts as its recipe's inputs).
    The project's BOM pricing reads them from the process. Its extra BOM items
    no longer price the device, and the platform refuses a new one.
11. **A crafted batch takes parts only through its steps.** The platform
    refuses a hand-typed draw and a typed "used" quantity, and it refuses to
    delete a step's draw on its own. A part lost in production is still a stock
    adjustment charged to the batch.

### Consequences

* Good, because one mechanism holds a unit's history, its materials and its
  cost, and every figure says which step it came from.
* Good, because a twin's history starts at the board's assembly, with the
  supplier's parts and fees on it.
* Good, because every old device gets its own price and history from the same
  rules as a new one, and the money of each batch stays the same.
* Good, because the bench knows which process step it performs, and says when
  a unit is not ready for it.
* Bad, because the rebuilt history is only as good as the old records. Three
  batches hold more units than their order made boards, most others hold
  fewer, and the rebuild reports this rather than resolving it.
* Bad, because device costs change where a batch's cost now spreads over its
  spares or its unfinished boards (Dongle Batch 8, Aqua Batch 5 on the local
  rehearsal), so the margin of the orders that shipped them changes.
* Bad, because an old project without a process keeps the extra BOM items and
  the hand-typed draws, so two material paths stay until every project has a
  process.
* Neutral, because the supplier's designators can differ from the schematic.
  substitutions ([0038](0038-a-substitution-belongs-to-the-batch.md)) still
  map them.

### Confirmation

Tests show that:

* receiving the boards records the assembly step with the order's measured
  draws and every board and assembly position, and freight stays in the
  origin batch cost.
* a position imported later, and twins received later, join the same
  assembly click.
* a person can link a position to the click it paid for, but not a position
  of another batch, a closed batch refuses, and the prices still add up to the
  batch's total.
* a process needs one assembly step without parts.
* an old batch is rebuilt into twins whose prices add up to its total, a
  rebuild takes spares, and it can be undone.
* a bench step names a deployment of its kind, marking records the step of the
  run's deployment, and the marking bench warns when the unit is not ready.
* a crafted batch refuses a hand-made draw, the project's materials are its
  process inputs, and the cost by step adds up to the batch.

## Pros and Cons of the Options

### The board's assembly as one step, with the fees as its cost lines

* Good, because the history has one readable row per supplier job, and the
  fees stay itemised on it.
* Bad, because the step has no parts list in the process. Its parts come from
  the order.

### One step for each fee

* Good, because each fee is a step of its own.
* Bad, because a fee is not done to a unit, and every unit gets a row per fee.

### The assembly stays in the origin batch cost

* Good, because it exists.
* Bad, because the largest part of a board's cost stays unnamed, and a twin's
  history starts at "receive".

### Twins that start when the order is linked

* Good, because the twin exists from the supplier's statement on.
* Bad, because JLC's panel count was wrong at least once (the Batch 8
  re-order), and the person's count at "receive" is the one that must count.

## More Information

This record amends 0059 §11 (the origin batch cost no longer holds the board
and assembly invoices or the assembler's draws), §13 (a rebuilt old batch's
devices take their twins' prices) and §15 (spares of a known batch enter with
a share of its cost). It applies the 0058 §4 pattern, a cost aimed at what it
paid for, to step clicks.

Claude rehearsed the rebuild on a local copy of production on 2026-10-03: 16
batches of CE_Dongle_V2 and CE_Aqua_V2, 5,640 named twins and 669 unnamed ones.
The register's gap stayed zero and the pool stayed balanced. It runs on
production only when the user confirms the two processes, the state of Batch
8's remaining boards and which unrecorded steps really happened.
