---
status: "accepted"
date: 2026-10-03  # accepted 2026-10-03
decision-makers: Mateusz Kowalik
consulted: Claude (design discussion 2026-10-03, after phase 1 of 0058 was built locally)
---

# Give every unit a twin from its first step, craft every batch, and price each device

## Context and Problem Statement

Phase 1 of [0058](0058-a-process-is-versioned-stages-over-the-pool.md) was
built on a local copy on 2026-10-03 and not deployed
([processes.md](../reference/processes.md)). It holds unfinished work as
hand-named stages in a chain that ends at programming. A device keeps only
the batch it was built in, and its cost is its batch's average
([0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md)).

The user needs more than that. For each device, the user must be able to say
which components and steps went into it and which options it got: a sticker
or a UV print, an instruction leaflet or none, a carton. The order of the
steps varies: programming and the label can come before the enclosure, while
laser marking needs it. A device continued in a later batch must keep the
cost of the batch its board came from. A chain that ends at programming, and
a cost averaged per batch, cannot hold that.

## Decision Drivers

* Every device carries its own history of components, steps and options, and
  that history does not change when the process changes later.
* Steps can happen in any order. A step states what a unit needs before it.
* No invented identity. A physical unit is never matched to a record by a
  guess ([0032](0032-a-shipment-names-its-devices.md)).
* Every batch is crafted step by step, even one built in one sitting. Nothing
  is assumed and nothing is automatic (user, 2026-10-03). This replaces the
  "zero ceremony" driver of 0058.
* Each device has its own price, made of what it got and the batch its board
  came from (user, 2026-10-03).
* One counting path. Stock and value stay on the single pool replay.

## Considered Options

* A twin per unit from its first step, named at programming, priced per twin.
* Anonymous piles with a contents list. A device copies the list at
  programming.
* Several processes per project, one per order of steps.
* 0058 as built: hand-named stages, a chain that ends at programming, and a
  batch-average cost.
* A twin named at its first step through a code printed on every unit.

## Decision Outcome

Chosen option: "a twin per unit, named at programming, priced per twin". It
gives every device a complete history and an exact price, it lets the steps
happen in any order, and it invents no identity: the twins of one stack are
identical until programming names one.

### Twins

1. **A twin is the record of one unit from the first step that touches it.**
   It holds an internal id, its origin batch, its components (part,
   quantity, source lot, price at the draw), its steps (what, when, under
   which process version, at which station, and how the unit was chosen) and
   its price. **The internal id is never printed, never shown as the
   identity of a physical unit, and never asked of a person.**
2. **A STACK is the unnamed twins of one batch that have the same steps done
   and used the same lots.** A stack is therefore one physical pile. Anything
   that happens to "one unit" before programming (a scrap, a write-off) is
   recorded as "one from this stack", and the platform picks which twin. The
   twins of a stack stay identical, so naming any one of them is not a guess.
3. **Only device units are twins.** A prepared part, such as an enclosure
   that is drilled and UV printed before it meets a device, stays a stock lot
   made by a transformation (0058 §3). When a step adds it to twins, each
   twin records the lot, and so the lot's history.

### The process

4. **A process version is a library of steps plus a main route.** Each step
   states what a unit needs (components present, steps done, steps not
   done), what the step adds (components drawn from stock, marks such as
   "laser marked"), where it is done, and whether it is REQUIRED or
   OPTIONAL. A required step can be a choice of alternatives, where one of
   them must be done (a sticker or a UV print). The main route is the usual
   order: the map draws it, and the batch page offers it as the next steps.
   **Any step whose needs are met can be called on a stack or on selected
   devices, in any order.** Published versions stay immutable
   ([0058](0058-a-process-is-versioned-stages-over-the-pool.md) §2).
5. **Each step names where it is done.** Programming and marking go to their
   benches, which read the device. Every other step is done on the batch's
   process screen. Before naming, the step takes a quantity from a stack.
   After naming, it takes devices, chosen by scanning each label or MAC, or
   by picking MACs from a list. **Each fact records how the device was
   chosen.** A scan is an observation. A pick from a list is a person's
   statement, and the device page shows the difference.

### Crafting a batch

6. **Every batch is crafted. There is no straight-through mode.** A batch
   starts empty, and a person clicks each step through on the batch's process
   screen. The first step receives the boards that the batch's assembly order
   delivered and creates one twin per board. **A twin's board contents are
   its origin batch's design BOM with that batch's substitutions applied**
   ([0038](0038-a-substitution-belongs-to-the-batch.md)). The twin READS
   them from its origin batch and does not copy them, because a substitution
   is often recorded after the boards arrive, and the contents are one fact
   for every board of the batch. **A batch with a process holds exactly ONE
   assembly order** for one board (for JLC, one SMT order code), so its
   substitutions and its origin batch cost belong to that order alone (user,
   2026-10-03). The platform refuses to link a second assembly order to such
   a batch. A re-order to complete a lot is a new batch. On 2026-10-03, 15 of
   the 17 batches already held one order. The batch page shows how many
   units are at each point of the process, and the steps that the units in a
   selected stack, or the selected devices, can take next.
7. **Programming names a twin.** The bench works from a selected stack, and
   each programmed board takes one twin from it and gives it the MAC. From
   then on, the device record IS that twin. **When the stack is used up, the
   bench asks which stack comes next before it programs the next board.** The
   answer can be "no stack", so the bench never blocks
   ([0037](0037-the-bench-says-what-it-already-knows.md)). A device programmed
   with no stack is recorded, and the batch shows it as a GAP. The bench
   never invents a twin.
8. **A gap is closed by a merge.** On the batch page, a person selects the
   gap devices (by name, MAC or barcode) and the stack they came from, and
   each device takes a twin from that stack. This also covers a board
   programmed outside the process, and a returned device that is reflashed.
9. **"Finished" is the last step, done by a person, never computed.** A person
   selects devices by name, MAC or barcode and marks them finished. The
   finish step needs every required step of the process version. A device
   that lacks one is refused, and the refusal names the missing step. Only a
   finished device can go on a shipment. A device without a twin (made before
   this decision) ships as today.

### Materials and costs

10. **A step draws the parts it adds.** Clicking a step on N units is one
    stock draw of N × the quantity of each input, linked to that click and
    priced the usual way: the stock's moving average, or the landed price of
    the lot it is bound to. The draw is charged to the batch where the step
    is done. For a project with a process, the BOM draw (`consume_from_bom`)
    is not used, or the same parts would be drawn twice. Optional parts are
    choices in the process, not BOM extras.
11. **Each twin has its own price, in two parts** (user, 2026-10-03):
    * **its own parts:** every draw its steps made, at the draw price. This
      part is exact per twin, wherever the step was done.
    * **its origin batch cost:** everything charged to the batch it was
      received in that no step on a twin drew. This includes the board and
      assembly invoices, labour, freight, tooling, and the part draws the
      assembler reports for the whole board order. It is split equally over
      the twins of that batch that are not scrapped, and it is listed on
      every twin under that name.
    * **Scrapped twins are carried by the others** (user, 2026-10-03). A
      scrapped twin's price (its origin share and its own parts) is spread
      over the twins of its origin batch that are not scrapped, so the yield
      loss is inside the product's price. The batch shows the scrap money on
      its own line. Once the origin batch is closed, its shares no longer
      move: a later scrap is a loss shown on the batch.
12. **A twin moved to another batch keeps its origin.** When a twin of Batch 1
    is programmed in Batch 8, its history keeps Batch 1, its origin batch
    cost stays Batch 1's share, and only its own parts are added from the
    steps done in Batch 8. It takes no share of Batch 8's origin batch cost
    (user, 2026-10-03).
13. **A device's cost is its twin's price.** Orders add up the prices of the
    devices they shipped. A device without a twin keeps the batch average of
    [0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md). An
    origin batch cost can change until the batch is closed, and closing it
    freezes every share ([0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md)).
14. **The pool and the register need nothing new.** A step draw carries the
    batch where it was done, so run figures and the register see it like any
    draw. Prepared parts keep the 0058 money rules: inputs at their draw
    prices, and conversion costs as invoice positions aimed at their
    transformation.
15. **Found units enter as twins at zero value** in the batch that continues
    them. Each fact names the closed batch that holds their cost, the rule
    0058 set for found work.

### Consequences

* Good, because every device shows what it got, when, and for what price, in
  the words of the process version it was built under.
* Good, because steps can happen in any order that their needs allow, and a
  new step or a new order costs one process version, not a new process.
* Good, because a device continued in a later batch carries its own board's
  cost. A batch no longer spreads its cost over fewer devices, and a later
  batch no longer gets boards it never paid for.
* Good, because nothing is assumed. Every fact on a twin was entered by a
  person or read by a bench, and the finish step checks the required steps.
* Bad, because every batch costs clicks, even one built in one sitting. The
  user accepts this in exchange for a complete record.
* Bad, because there are many more rows: one twin per unit, with its steps
  and its price.
* Bad, because two cost rules live side by side: the twin's price, and the
  batch average for devices made before twins.
* Bad, because phase 1 of 0058 must be reworked. Hand-named stages become a
  step library, the lot pin becomes the stack, and banking creates twins.
* Bad, because the internal id is a temptation. One screen that asks "which
  twin is this unit?" before programming would bring back pretend serials.
  Tests guard against it.
* Neutral, because pile discipline is unchanged: the record is as true as the
  stack the operator chose, and a pick from a list is as true as the person
  who made it.

### Confirmation

Tests show that:

* The twins of one stack stay identical until named, and naming takes any
  twin of the selected stack.
* A step whose needs are not met is refused, and a step on devices records
  how each one was chosen.
* An empty stack makes the bench ask for the next one, "no stack" records a
  gap, and a merge closes it.
* The finish step is refused while a required step is missing, and a
  shipment refuses an unfinished device that has a twin.
* A twin's price is its own draws plus its share of its origin batch cost,
  the shares of one batch add up to that batch's origin batch cost plus the
  own parts of its scrapped twins, and a moved twin keeps its origin share.
* The pool's value identity and the register's gap still hold.

No endpoint and no screen may address an unnamed twin by its id.

## Pros and Cons of the Options

### A twin per unit, named at programming, priced per twin

* Good, because each device gets a full history and an exact price, and the
  order of the steps is free.
* Bad, because of the row count, the two cost rules, and the rework of
  phase 1.

### Anonymous piles with a contents list

* Good, because it has fewer rows, and the history is identical in content.
* Bad, because it has no record per unit, so it cannot carry a price per
  device, and every view must rebuild a device's history from pile chains.

### Several processes per project, one per order of steps

* Good, because each process is a simple chain.
* Bad, because a step shared by several orders is copied into each process
  and the copies drift, and a batch must choose its order before the work
  shows what the order is.

### 0058 as built

* Good, because it exists and its tests pass.
* Bad, because the chain ends at programming, it records nothing after it,
  it keeps no history per device, and it averages cost per batch.

### A twin named at its first step through a printed code

* Good, because each unit is exact from the first step.
* Bad, because it costs one scan per unit per step and a code on every
  board. The chosen option can add it later for one product without a change
  of design.

## More Information

When this decision is accepted, it supersedes 0058 §1 (stages named by
hand), §2 as far as the chain closing on one programmable form, §6 as far as
the batch pinning a lot (the stack replaces the pin), and 0058's "zero
ceremony" driver. It keeps 0058 §3 and §4 for prepared parts, §5
(alternatives), §7 (stocktake) and §8 (the Process tab). It narrows
[0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md): a device
with a twin is priced by its twin, not by its batch's average. It
reconsiders the option 0058 rejected, "serialize WIP as devices with platform
ids", and accepts it only because the id stays internal and the twins of a
stack stay interchangeable until programming names one.

All open points were answered by the user on 2026-10-03, and the user
accepted this decision the same day.
