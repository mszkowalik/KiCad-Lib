---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04 on the local rebuild of 0060)
---

# Let one invoice pay for several steps, and let the benches record their steps with their parts

## Context and Problem Statement

Claude built [0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md)
on a local copy on 2026-10-03 and rehearsed it on 16 old batches. The user's
answers of 2026-10-04 showed four gaps:

* LIFTECH did programming, enclosure fitting, laser marking and labelling
  (and the function test on the Aqua), and each of its invoices covers all of
  them. One LIFTECH invoice also often covers several batches. 0060 §4 let a
  position pay for one step click only.
* Every Dongle and every Aqua got a laser mark and a barcode label. The Aqua
  also has a function test, a step kind the process did not have.
* A label is stock: the label step uses one, and the platform must know how
  many are left (at least 500 on the shelf, user). LIFTECH bought and billed
  its own labels ("naklejki, instrukcje i wysyłka" in its emails). 7Sigma
  bought DYMO Durable 25 × 54 mm labels from EMMA in 2024.
* The marking procedure reads only the device's Tasmota topic, never its MAC.
  None of the 259 live marking runs was linked to a device, so the marking
  bench recorded no step on any twin.

## Decision Drivers

* A cost that paid for several steps is shared by the units of those steps,
  and is never split by a guess.
* A bench records what it did, with the parts it used, and never blocks
  ([0037](0037-the-bench-says-what-it-already-knows.md)).
* Nothing is invented: a stated step and a stated part use say so.
* The stock replay stays the one count, and the register's gap stays zero.

## Considered Options

* One position links to several step clicks through a link table.
* One position stays on one click, and a person splits it into one child per
  step.
* The unit of a marking run is found by its topic, or the marking procedure
  gets a MAC read.

## Decision Outcome

Chosen options: "a link table" and "the unit is found by its topic". A split
per step needs an amount per step that no invoice states, so it would be a
guess. A MAC read adds a serial step to every marking run to learn what the
run already knows from the topic.

1. **A position can pay for several step clicks** (`cost_line_steps`). The
   twins of all its clicks share it equally. The cost by step shows one row
   for each invoice that paid for several steps, and never splits it. This
   replaces the single link of 0060 §4 (`RunCostLine.step_run_id`, never
   deployed). A split child keeps its parent's clicks, and so does a JLC fee
   child.
2. **A process can have a `test` step**, done at the programming bench. It
   names a `test` deployment. A passing run of a test deployment records it
   on the unit's twin.
3. **A run that reads no MAC finds its unit by the Tasmota topic it
   captures**: the exact topic first, then the serial after the last
   underscore. It takes only an existing device of the run's project, and
   only when exactly one matches. Then the bench checks run, and marking and
   tests are recorded. **Only a pass of a `flash` deployment writes the
   `produced` event**, so a test or a mark never makes or names a unit.
4. **A step the bench records draws what it adds**, a label for the label
   step, from the pool. When the pool holds none, the bench still records the
   step, because it happened, and the click's note names the part it did not
   draw.
5. **A label is a stock part.** The label step's input is the DYMO Durable
   25 × 54 mm label (DYMO code 2112283, 160 labels per roll), keyed by that
   code in the pool, as the shipping cartons are.
6. **In a rebuild, a stated step draws its parts only when a person says the
   parts came from our stock** (`draw`). The draws are priced from the pool on
   the batch's date, and the rebuild is refused when the pool did not hold
   them then. A stated step whose parts came from someone else, such as
   LIFTECH's labels inside its invoice, draws nothing. This amends 0060 §7
   ("no money moves"): the batch's total may grow by these draws, and by
   nothing else.

### Consequences

* Good, because LIFTECH's invoice is carried by exactly the units it paid for,
  and the cost by step shows it as one figure.
* Good, because the marking bench now records the laser mark and the label on
  each twin, with the label it used.
* Good, because the label stock follows every label the bench prints.
* Bad, because a reprint, or a label typed by hand on the marking bench, is
  still not recorded, so the label stock is too high by those labels until a
  stocktake corrects it.
* Bad, because LIFTECH's invoices state unit counts that do not match the
  batches (1,239 Dongles against 1,007 devices in Batches 3 and 4), and this
  decision does not resolve that.
* Neutral, because a topic that matches no device, or two, leaves the run
  unlinked, as before.

### Confirmation

Tests show that:

* one position paid for several clicks is shared by the units of all of them,
  the prices still add up to the batch's total, and the cost by step shows
  one row for it;
* a rebuild links one invoice to several steps, draws a stated step's parts
  only when told they were ours, refuses when the pool did not hold them on
  the batch's date, and its undo takes the draws back;
* a passing test records the test step once, and the batch screen refuses it;
* the label step draws a label, and records the step with a note when the
  pool holds none;
* a run with no MAC finds its unit by the topic, only within its project.

## Pros and Cons of the Options

### A link table

* Good, because one fact (this invoice paid for these steps) is one set of
  rows.
* Bad, because the cost by step needs a row of its own for a shared invoice.

### One click per position, split by a person

* Good, because each position stays on one click.
* Bad, because the split amounts are a guess.

### The unit found by its topic

* Good, because the marking and test procedures stay as they are.
* Bad, because a topic changed by hand on a device no longer finds it.

### A MAC read in every marking procedure

* Good, because the MAC is the identity the platform trusts most.
* Bad, because it adds a serial step to every run, and every published
  marking version must change.

## More Information

This record amends 0060 §4 (the link moves to a table and can name several
clicks) and §7 (a rebuild may add the draws of a stated step whose parts were
ours).

The 2026-10-04 local rehearsal rebuilt the 16 Dongle and Aqua batches again.
LIFTECH's shares pay for programming, the enclosure, the laser mark and the
label (and the test on the Aqua). Batch 8, labelled in-house, drew its 200
labels from the one label invoice booked on the local copy (EMMA FS
14806/2024, 480 labels). The register's gap stayed zero and the pool stayed
balanced. The label invoices are not on production yet.
