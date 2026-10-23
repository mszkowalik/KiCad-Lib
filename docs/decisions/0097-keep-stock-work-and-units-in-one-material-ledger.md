---
status: "accepted"
date: 2026-10-23  # accepted 2026-10-23
decision-makers: Mateusz Kowalik
consulted: Claude (design discussion 2026-10-22/23, after the V3 enclosures were laser cut)
---

# Keep stock, work and units in one material ledger

## Context and Problem Statement

On 2026-10-22 the user laser cut the 49 remaining Takachi SIM6-12-3W
enclosures: 9 on units of batch 2164, and 40 for the next CE_Dongle_V3 batch.
The platform could hold the 40 only as a new internal part, "SIM6-12-3W cut"
(component 577), made by a prepared-part transformation (decision
[0058](0058-a-process-is-versioned-stages-over-the-pool.md)). Process v6 still
draws the uncut part at "Take enclosure", so a new V3 batch stops there.

The user asked for one flexible model of processes, recipes and stock, safe
from later changes (2026-10-23). The design, what the current model cannot
hold, and the build plan are in
[docs/material-ledger/design.md](../material-ledger/design.md).

## Decision Drivers

* Work never makes a new item. A state is a property of the item (user,
  2026-10-22).
* Each unit shows what is inside it, as a parent with children, and the work
  each child got, with its exact artwork (user, 2026-10-22).
* No invented identity. A lot is as fine as the floor can tell items apart
  ([0032](0032-a-shipment-names-its-devices.md), 0058,
  [0059](0059-every-unit-has-a-twin-and-programming-names-it.md)).
* Lots split on demand down to a quantity of 1. No row for each bought item
  (user, 2026-10-23).
* One event list for stock and value (0058). Closed books do not move
  ([0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md)).
* The old model stays the truth until the new one gives the same stock and
  cost (user, 2026-10-23).

## Considered Options

* One material ledger (items, lots, moves, links, properties, events, cost
  aims), built beside the old model and proven equal before it takes over.
* One row for each bought item.
* Extend the current mechanisms: more internal parts, more choice groups.
* Replace the old tables in one cut-over.
* An external ERP or MRP system for stock (not discussed with the user).

## Decision Outcome

Chosen option: "one material ledger, built beside the old model" (user,
2026-10-23). It holds
every case of the design document with seven records and no new mechanism for
each new need. Its proof is a set of parity checks against today's figures.

1. **An item is what a thing is.** Work never changes it. Each item has a
   tracking level (`count`, `lot`, `serial`) and a unit of measure (`pcs`
   only, for now).
2. **A lot is a quantity of one item whose members are identical in the
   record.** When some members become different, the lot splits first. A lot
   of 1 carries an identifier only when the floor can read it off the object.
   A product unit is a lot of 1 from its first step, with every rule of 0059.
3. **Only a move changes a quantity**: from a lot or from outside, to a lot or
   to outside. A move between lots freezes its value. A receipt reads its
   value from its invoice line.
4. **A link puts a lot inside another lot.** Attaching never changes the
   child's item. A unit's as-built record is its links, recursively.
5. **A property states a fact about a lot.** A cut enclosure is the enclosure
   item with `cut_*` properties. A step's requirement is a condition on the
   properties of its subject and of the subject's children.
6. **An event is one operation**, with who, when, which batch, which process
   version and step, how the lots were chosen, which bench run, and which
   deployment version and files.
7. **A cost aim points an invoice position at an event or a whole step.** It
   replaces `transformation_id`, `cost_line_steps` and `cost_line_step_keys`.
8. **The platform calculates money on read.** The price rules of 0059, 0060, 0073 and
   [0074](0074-a-units-history-is-correctable-and-names-its-bench-runs.md)
   stay as they are.
9. **Five phases**, each started by the user: a shadow ledger with parity
   checks, then the writes, then the readers, then what the old model cannot
   hold, then the old tables retire.

### Consequences

* Good, because a new state, a new bundle or a new alternative is data in a
  process version, not a new mechanism.
* Good, because "cut here or bought cut" is one condition, and the V3
  enclosure path needs no choice group.
* Good, because one rule set (moves, links, properties) replaces the rules of
  transformations, twins, stacks, step links and transfers.
* Bad, because the projector and the parity checks become the riskiest code,
  as the pool replay is today.
* Bad, because the old and the new model run side by side for months, and
  phase 2 writes each operation into both models.
* Bad, because history keeps its precision. A draw with no lot is bound only
  by inference, always.
* Neutral, because new physics (reels, metres), new benches and new pricing
  rules still need code.

### Confirmation

The parity checks of the design document, section 8, pass on production:
quantity and value on hand for each item and company, the lowest balance,
each lot's remainder, each batch's cost and cost by step, each unit's price,
each shipped device's cost, and the register's gap.

## Pros and Cons of the Options

### One material ledger, built beside

* Good, because every need in the design document fits seven records.
* Good, because nothing changes for the operators until the ledger is proven.
* Bad, because of the double running and the projector.

### One row for each bought item

* Good, because nothing could be finer.
* Bad, because 61,571 resistors (0402WGF5101TCE) on JLC reels can never be
  told apart, so the rows hold no more than one lot. There are about 654,000
  bought units over 207 part lines. Both figures are from the previous
  session's `GET /api/parts-stock` of 2026-10-23. The user chose lots that
  split instead.

### Extend the current mechanisms

* Good, because it is small for each case.
* Bad, because each state needs a new item, which the user rejected, and
  `needs` and choice groups cannot express "cut here or bought cut".

### Replace the old tables in one cut-over

* Good, because there is no double running.
* Bad, because a mistake in the replay corrupts every stock figure at once,
  and nothing shows it (0058, Consequences).

### An external ERP or MRP system

* Good, because lot, serial and genealogy models exist there.
* Bad, because the twins, the benches, the deployments and the invoice
  register would need a link to a second source of stock truth. The user did
  not ask for it. This record lists it for completeness.

## More Information

This record amends 0058 §1 (a stage is an internal part) and §3 (a
transformation's output is a new lot), and 0059 §3 (only device units are
records for each unit). Each amendment takes effect when its phase lands.
Until then those sections stay in force. It amends 0073 §3 only if the user
accepts lot binding at staging (question 4 of the design document). It keeps
0044, 0059's twins and stacks, 0060, 0064 and
[0089](0089-every-change-is-recorded-and-can-be-undone.md).

The open questions for the user are in section 10 of the design document.
