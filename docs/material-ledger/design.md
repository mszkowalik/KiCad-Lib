# Material ledger: one model for stock, work and units

**Status: accepted on 2026-10-23. Phase 1 is deployed (37424e3, 2026-10-23); phases 2, 3 and 5 are one cut-over (decision 0098), deployed on 2026-10-24 (aa80e2f).** This
document is the detail behind decision
[0097](../decisions/0097-keep-stock-work-and-units-in-one-material-ledger.md).
Phase 1 is described as built in
[docs/reference/material-ledger.md](../reference/material-ledger.md). Claude
wrote this document on 2026-10-23 from the design
discussion of 2026-10-22/23 and the user's answers of 2026-10-23. Claude read
each fact about the platform from the code or the live API on 2026-10-23,
unless the text says "unverified".

## 1. The goal

The user, 2026-10-23:

> build some very flexible system that would generalise a lot the processes,
> recipes and how the stock is kept track of. I want to be sure that once we
> build a system, we'll be safe from any kind of changes, even if it means
> keeping every item that ever was bought as separate row in the database.

The user's answers of 2026-10-23:

1. Write the documents first. Then build the new model beside the old one, and
   prove that both give the same stock and cost before the switch.
2. Keep lots that split on demand, down to a quantity of 1. Do not make one row
   for each bought item.
3. Keep process v6 of CE_Dongle_V3 as it is until the new model is ready. The
   user plans no new V3 batch before that.

The user's statements of 2026-10-22/23, as the previous session recorded them:

* An item stays the same item when work changes it. The work adds a property
  (a tag). A step that needs the change filters by that property. The user
  does not want a new item for each state.
* Each enclosure has its own record, with the work done to it and the exact
  artwork.
* The platform tracks antenna lots. When two orders are open, the operator says which
  lot.
* Light pipes put into an enclosure make a BUNDLE: a parent with children. They
  do not make a new item "enclosure with light pipes".
* A finished device shows which parts are inside it, not only their cost.
* A cut pattern for each client is a future case. The model must permit it.

## 2. What exists today

| Mechanism | What it holds | Code | Decisions |
|---|---|---|---|
| The pool | Purchases (a stock-step invoice line with no batch), draws (`component_consumptions`) and adjustments (`component_stock_adjustments`), replayed in date order by `run_actuals._pool_events`, the one event list | `run_actuals.py` | 0034, 0040, 0047 |
| Lots | A purchase line (`L<id>`) or a positive adjustment (`A<id>`). A draw is bound to lots by `component_consumption_lots`, with a `source` (reported, fifo, manual, unallocated, legacy_average) | `lots.py` | 0073 |
| Stock per company | One pool for both companies, or one per company | `companies.py`, `transfers.py` | 0063, 0064 |
| Prepared parts | An internal component for each state, a recipe in `ProcessVersion.graph["prepared"]`, and a transformation: input draws plus one positive adjustment as the output lot | `process.py` | 0058 |
| Twins | One record per unit (`twins`), a click (`step_runs`), the units in a click (`twin_steps`), the stack key, the invoice positions linked to steps | `twins.py`, `twin_rebuild.py` | 0059, 0060, 0061, 0074 |
| Devices | A unit with a MAC (`device_units`), its history (`device_events`), its programming runs, each pinned to a deployment version that pins its file sets | `flasher/`, `orders.py` | 0003, 0029, 0032 |

Live state on 2026-10-23:

* `lot_pricing` is OFF. A draw takes the moving average.
* `stock_per_company` is OFF. Both companies share one pool.
* One transformation exists: #1, 40 × "SIM6-12-3W cut" (component 577), made
  2026-10-22.

## 3. What the current model cannot hold

1. **A state is a new item.** Component 577 "SIM6-12-3W cut" exists only to
   say that component 233 has holes. A UV print or a paint finish would add one
   more item for each combination.
2. **"Cut here, or bought cut" cannot be a requirement.** A step belongs to at
   most one choice group. `needs` is an AND of step keys or groups
   (`twins.needs_met`). "Install PCBA in enclosure" cannot say "top holes cut
   here or by the supplier, and bottom holes cut here or by the supplier".
3. **Process v6 refuses a new V3 batch at "Take enclosure".** The step draws
   component 233, and 233 has 0 on hand. The cut enclosures are component 577,
   and no step draws 577. The version check says so: "prepared part
   'SIM6-12-3W cut' is made by a recipe but no step uses it".
4. **A recipe has inputs and one output, and nothing more.** It has no file
   set, no parameters and no steps. A cut pattern for each client has no place
   to go.
5. **A twin owns 1/N of each click's draws.** The platform cannot say which
   antenna lot went into which unit, even when the floor knows it.
6. **A draw has no place inside a unit.** Light pipes in an enclosure, and the
   enclosure in a device, are one flat list of draws on the twin.
7. **Nothing selects between parts that are not interchangeable.** Decision 0058 §5
   says "different parts, picked by the device's BOM variant". Nothing
   implements that selection.
8. **Each new need added a mechanism**: transformations, twins, stacks, step
   clicks, step cost links, transfers. Each has its own replay, undo rules and
   guards. The rules for one mechanism do not apply to the next.

## 4. The model

Seven records. All are append-only. The platform calculates the state from them: what is
on hand, what each lot is worth, what is inside each unit, and which work each
lot got.

### 4.1 Item: what a thing is

| Column | Meaning |
|---|---|
| `kind` | `part` or `product` |
| `component_id`, `mpn` | A part, by the identity the pool uses today (`resolve_pool_identity`) |
| `project_id` | A product: the unit of a project, for example CE_Dongle_V3 |
| `uom` | The unit of measure. Only `pcs` now |
| `tracking` | `count`, `lot` or `serial` (see section 7) |
| `identifier_kind` | What the floor reads off the object: `mac`, `engraved`, `label`, or none |

Rules:

1. Work never changes an item. A cut enclosure is still item SIM6-12-3W.
2. The tracking level can go up for new lots. Nothing can recover precision that
   nobody recorded.

### 4.2 Lot: a quantity of one item that nobody can tell apart

| Column | Meaning |
|---|---|
| `item_id`, `company_id` | Fixed for the life of the lot |
| `identifier` | Only on a lot of 1, and only when the floor can read it off the object. Unique for each item |
| `device_unit_id` | The device, for a programmed product unit |
| `split_from_lot_id` | The lot that this lot was split from |
| `created_event_id` | The event that made the lot |
| `label` | A name a person can use: the supplier's lot reference, `A675` |

A purchase lot has no row: it is its invoice line (`L<line id>`), the one
truth of what was bought (decision 0073). A stored lot (`A<lot id>`) is made
by a positive adjustment: a count, found units, a make's output.

Rules:

1. **The members of a lot are identical in the record.** When some members
   become different (a step on some, a property on some, a move of some), the
   lot splits first. The split moves those members to a new lot. The new lot
   keeps the history of its parent up to the split.
2. **A lot's quantity is never stored.** It is the sum of its moves.
3. **The platform never invents an identifier.** A lot of 1 carries one only
   when the floor can read it off the object: a MAC, an engraved code, a label. This
   keeps the rule of 0032, 0058 and 0059.
4. **A product unit is a lot of 1 from its first step** (user, 2026-10-23:
   one lot for each unit, not one for each pile). This is the twin of 0059
   with all of its rules. It has no identifier until programming, a
   person reaches it through its stack, and nothing addresses it by its id.
5. **A transfer to the other company is a move to a new lot.** The item and
   the company of a lot never change.

### 4.3 Move: every change of a quantity

| Column | Meaning |
|---|---|
| `event_id`, `item_id` | The operation and the item. A move is a `draw` or an `adjust` |
| `qty` | Signed: positive into stock, negative out of it |
| `unit_cost_usd` | Frozen at the move. Null on an adjustment: the moving average at the replay |
| `company_id`, `run_id` | Whose stock moved, and the batch the move is charged to |
| `lot_id` | On a positive adjustment: the stored lot it made |

A move's LOTS are its move lots (`material_move_lots`): which lot it took
from (a purchase line or a stored lot), how many, at the lot's own price, and
how that is known (`reported`, `fifo`, `fifo_history`, `manual`,
`unallocated`, `legacy_average`). What its move lots do not cover changed a
lot nobody recorded. A purchase is not a move: it is its invoice line.

Rules:

1. **Only a move changes a quantity.** A split is a move out of the old lot
   and a move into a new stored lot, in one event.
2. **A move freezes its value** (0044, 0073). A purchase reads its value from
   its invoice line, with its freight share, on every read
   (`run_actuals._buy_usd`).
3. **A move of a part can name no lot** (`unallocated`). History has such
   draws, and `lot_pricing` is off. The item's balance still counts the move.
4. **Value on hand = value in − value out**, for each lot and each item. This
   is the identity of `pool_state` (`value_bought + value_adj − value_used =
   value_usd`), kept.

### 4.4 Link: a lot inside another lot

| Column | Meaning |
|---|---|
| `parent_lot_id`, `child_lot_id`, `qty` | What is inside what, and how many |
| `role` | The child's place in the parent: `enclosure`, `lightpipe`, `antenna_lte` |
| `kind` | `permanent` (glued, soldered, pressed) or `transient` (a device in a carton) |
| `attached_event_id`, `detached_event_id` | When it went in and when it came out |

Rules:

1. **Attaching never changes the child's item.** Light pipes in an enclosure
   stay light pipes. The enclosure in a device stays an enclosure.
2. **An attached child is not on hand.** The attach first splits the needed
   quantity off its source lot. The link then holds that new lot.
3. **A unit's as-built record is its links, recursively.** Each child shows its
   lot, how the lot is known, and its own work.
4. **A detach is an event** (rework, repair, a return).

### 4.5 Property: a fact about a lot

| Column | Meaning |
|---|---|
| `lot_id`, `event_id` | The lot, and the event that stated the fact |
| `name`, `value` | `cut_top` = `"Top v3"`. The value is JSON |
| `cleared` | True when the event removed the property |

Rules:

1. **A state is a property, not an item.** An enclosure lot with `cut_top`,
   `cut_bottom`, `cut_side` and `cut_front` is a cut enclosure.
2. **A lot reads its own properties, and its parent's properties from before
   its split.**
3. **The event says where the fact came from**: a step, a supplier at receipt
   (an enclosure bought cut), a person's statement, a bench reading.

### 4.6 Event: one operation

| Column | Meaning |
|---|---|
| `kind` | `receive`, `step`, `attach`, `detach`, `split`, `merge`, `transfer`, `consume`, `scrap`, `count`, `ship`, `return` |
| `at` | The date that orders the replay. `created_at` is the server time |
| `actor`, `company_id`, `run_id` | Who, which company, which batch |
| `process_version_id`, `step_key`, `step_label` | The rule it ran under, and the step's name as it read then |
| `chosen` | How the lots were chosen: `stack`, `scanned`, `list`, `bench`, `supplier`, `stated`, `fifo`, `rebuilt` |
| `station`, `programming_run_id` | Where, and which bench run |
| `deployment_version_id`, `file_set_id` | The procedure and the files it used: the artwork of a cut or a mark |
| `params` | The resolved parameter values that are not secret. A bench step names its run, which keeps the rest (0094) |
| `reverses_event_id` | A correction of an earlier event (0044) |

An event's lots without a quantity change (the lots a step acted on) are rows
of `event_lots` (`event_id`, `lot_id`, `programming_run_id`,
`deployment_version_id`). They replace `twin_steps`.

A new kind of work needs no new kind of event. A step with its moves, links
and properties holds it.

### 4.7 Cost aim: an invoice position aimed at work

| Column | Meaning |
|---|---|
| `line_id` | The invoice position |
| `event_id`, or `run_id` + `step_key` | One event, or every event of one step in one batch |

This record replaces three: `RunCostLine.transformation_id` (0058 §4),
`cost_line_steps` (0060, 0061) and `cost_line_step_keys` (0074). The money adds
to the value of the event's lots, in equal shares for each member.

## 5. Processes and recipes

A process version keeps its document and its lifecycle: draft, check, publish.
A prepared-part recipe becomes an ordinary step whose subject is a part. A
step gets these fields. Old versions keep the old fields and their meaning.

| Field | Meaning |
|---|---|
| `subject` | The item the step works on. The default is the project's product. "Cut top holes" works on SIM6-12-3W |
| `requires` | A condition on the subject: its properties, its children's properties, the steps it got. `all`, `any` and `not` combine conditions. It replaces `needs`, `needs_not` and choice groups in new versions |
| `sets` | The properties the step writes, on the subject or on a child by its role |
| `inputs[].attach` | `child:<role>` links the input as a child. `consume` uses it up, and its value goes into the subject |
| `inputs[].requires` | A condition on the input lot: an enclosure with `cut_top` |
| `deployment_id`, `params` | The deployment whose version pins the files, as bench steps do today. Where each parameter comes from: the version, the batch, the order or the unit |

Illustration only, not a proposed version:

```json
{"key": "cut_top", "label": "Cut top holes",
 "subject": {"component_id": 233},
 "requires": {"not": {"prop": "cut_top"}},
 "sets": {"cut_top": "{artwork}"},
 "deployment_id": "<the top cut pattern>"}

{"key": "enclosure", "label": "Take enclosure",
 "inputs": [{"component_id": 233, "qty": 1, "attach": "child:enclosure"}]}

{"key": "enclose", "label": "Install PCBA in enclosure",
 "requires": {"all": [{"child": "enclosure", "prop": "cut_top"},
                      {"child": "enclosure", "prop": "cut_bottom"},
                      {"child": "enclosure", "prop": "cut_side"}]}}
```

What this gives:

1. **"Cut here, or bought cut" is one condition.** The step "Cut top holes"
   runs on a free enclosure lot on the shelf, or on the enclosure inside a
   unit. A supplier lot bought cut gets the property at receipt. "Install PCBA
   in enclosure" asks only for the property. No choice group is necessary.
2. **No item for each state.** The stock view groups each item by its
   properties: "SIM6-12-3W: 40 cut, 0 not cut".
3. **Interchangeable parts** (form, fit and function): an input accepts several
   items when the user states that they are interchangeable. Parts that are not
   interchangeable are different items. A condition on a batch or order
   parameter selects them.
4. **Artwork, in three cases**:
   1. Artwork replaced for every unit: a new deployment version. Each event
      names the version it used.
   2. Several artworks valid at the same time (one for each client): the
      parameter comes from the batch or the order. The property keeps the
      value. A later step compares the property with the batch or order value.
   3. Data for each unit (serial, QR code, MAC): a value of the bench run, as
      today. No version.
5. **A stack is a view.** Units of one batch with the same item, properties,
   children and steps are one stack. A person takes "N from this stack". This
   is the stack key of 0059, calculated from the records.

## 6. Money

1. The platform calculates value on read from moves, invoice lines and cost
   aims.
   Nothing stores the value of a lot.
2. A receipt's value is its purchase line, landed, read on every read. A found
   lot enters at zero or at a stated value, with a note (0058, More
   Information).
3. A move out of a lot freezes its value. It takes the lot's cost when the move
   is bound to a lot (0073). It takes the moving average while `lot_pricing`
   is off.
4. A step adds value to its lots: what it consumed or attached, plus the
   invoice positions aimed at it, in equal shares for each member.
5. A split carries value in proportion to quantity, because the members are
   identical.
6. A unit's price keeps the rules of 0059, 0060 and 0074: its own parts, its
   step invoices, its origin share, scrapped units carried by the good units of
   their origin batch, and the share frozen when a batch closes. One pricing
   function calculates it from the ledger.
7. The register keeps its identities: each position has one destination, and
   the gap is zero.
8. The moving average stays for planning a batch that does not exist yet
   (0073).

## 7. Tracking levels: what the floor states

| Level | The lot of a use is | Decided by | Proposal (not decided) |
|---|---|---|---|
| `serial` | the unit, by its identifier | a scan (an observation), or a pick from a list (a statement) | PCBA (MAC). An enclosure, if it gets an engraved code |
| `lot` | one lot | the operator, once, when parts are staged for a batch. The platform asks only when two or more lots are open | WiFi and LTE antennas, SMA pigtails |
| `count` | the oldest lots first (FIFO) | the platform. Nobody is asked (0073) | screws, light pipes, IPA wipes, foam pads, cartons, labels |

1. A use that the operator cannot state is recorded as `fifo`, never as a
   statement.
2. Decision 0073 rejected "lots chosen by hand at each draw", because nobody at
   the bench can answer that question. The `lot` level asks once for each batch
   and part, and only when two lots are open. That changes 0073 §3 for
   lot-level parts, so the user must decide it (question 4).

## 8. Build beside, prove equal

Each phase starts only when the user says so.

### Phase 1: the shadow ledger (read only)

1. Create the ledger tables. The tables that a rebuild empties carry no
   journal trigger (0089), because they hold no fact of their own. The items
   and the state maps carry it. The shadow gets the trigger in phase 2.
2. Write a projector that builds the whole ledger from today's rows. It drops
   the shadow and builds it again, so a second run gives the same result.

   | Today | Ledger |
   |---|---|
   | A pooled purchase line | A `receive` event, a lot, a move from outside |
   | A positive adjustment | A `count` or `receive` event, a lot, a move from outside |
   | A negative adjustment | A `scrap` or `count` event, a move to outside |
   | A draw, and its lot bindings | A move from each bound lot (or `unallocated`), to outside or into a unit |
   | A transformation | A `step` event on its input lots. When the output part is a STATE of another item, a property. Otherwise a new lot |
   | A twin | A product lot of 1 |
   | A step click and its twins | A `step` event and its `event_lots` |
   | An invoice position linked to a click, a step or a transformation | A cost aim |
   | A transfer between companies | A `transfer` event: moves from the sender's lots to new lots of the receiver |
   | A device | The identifier and `device_unit_id` of its lot |

3. A mapping table says which internal part is a state of another item. For
   example: 577 = 233 with `cut_top`, `cut_bottom`, `cut_side` and `cut_front`.
   The user confirms each row.
4. Parity checks, as a test and as an admin endpoint:
   1. Each item and company: the quantity on hand equals `pool_state`, exactly.
   2. Each item and company: the value on hand equals `pool_state`, to 0.01 USD.
   3. Each item: the lowest balance and the first short date equal
      `pool_state`.
   4. Each lot: the remaining quantity and value equal `lots.lot_state`.
   5. Each batch: the cost equals the register's figure for the batch, and the
      cost by step equals `cost_by_step`.
   6. Each unit: the price equals `twins.prices`.
   7. Each shipped device: the cost equals what `order_economics` charges.
   8. The register's gap stays the same.

   The check lists each difference with its rows. A phase ends only
   when someone fixes or explains each difference.
5. The old model stays the truth. No writer changes.

The first run on production (2026-10-23, after the deploy of 37424e3) found
no difference: 207 parts in the one pool, 146 in 7Sigma's stock, 105 in
9Sigma's, 495 lots and 860 units.

### Phase 2: the ledger takes the writes

One service function for each operation writes the ledger event and the old
rows in one transaction. The order: prepared parts, then process and bench
steps, then purchases and JLC draws, then transfers and adjustments. The
parity checks run after each switch.

### Phase 3: the readers move

`pool_state`, `lots.lot_state`, `check_shortages`, the register and the unit
prices read the ledger. Each new reader must give the same answer as the old
one before the old one goes.

### Phase 4: what the old model cannot hold

States as properties, conditions on properties, bundles, serial parts, lots
bound when parts are staged, artwork and parameter sources on steps, and stock
grouped by properties. The V3 enclosure path (section 3, item 3) is the first
use.

### Phase 5: the old tables retire

They become read only. Then a migration removes them. This needs its own decision
record.

## 9. What the ledger cannot protect against

1. **Lost precision stays lost.** A draw recorded without a lot can only be
   bound by inference (`fifo`), always.
2. **New physics needs code.** Units of measure other than pieces (reels,
   metres, grams), conversions between them, and a part cut to length.
3. **A new bench, identifier reader or supplier data source needs code.**
4. **A new pricing rule needs code**: standard cost, or freight by weight. The
   ledger keeps the facts, so a new rule can price the past again on read.
5. **The projector and the parity checks are now the riskiest code**, as the
   pool replay was (0058). While the old model is the truth, a mistake shows as
   a parity difference, not as wrong books.
6. **A record is as true as the statement behind it.** A stack is as true as
   the pile the operator took it from (0059).

## 10. Questions for the user

The numbers stay fixed because decision 0097 cites them. Question 1 is
answered: section 4.2, rule 4.

2. The tracking level for each part. Section 7 has a proposal.
3. Do you engrave an identifier on each enclosure? Only then can an enclosure
   be a `serial` part.
4. Lot-level parts: one statement for each batch and part, asked only when two
   lots are open. This changes 0073 §3 for those parts.
5. Location: do you need to know where a lot is (our shelf, JLC consignment,
   the final assembler)? Proposal: a property, in phase 4.
6. Interchangeable or not: light pipes FIX-LEMB2-4.8V0-F and MENTOR 1293.0050.
   Enclosures cut here and the LC Elektronik "Enclosure modification". The
   carton kit with and without the IPA wipe and the foam pad.
7. Do the DC_* projects or EVSE_20_CTRL have partly made items that wait on a
   shelf? This sets the scope of phase 2.
8. How long must the parity checks pass on production before phase 2 starts?

## 11. Sources

The previous session gave these industry sources. This document did not read
them again (unverified here):

* ISA-95 material model: OPC 10030 §8.4.1, §8.4.3, §8.4.3.4, §8.4.3.5
  (reference.opcfoundation.org): material lots and sublots with properties,
  assembly relations (physical or logical, permanent or transient).
* SAP batch classification, batch determination and production versions
  (help.sap.com, learning.sap.com).
* Odoo kit and manufacture bills of material (cybrosys.com).
* Backflush against lot and serial control (andea.com, racklify.com,
  rootstock.com).
* Form, fit and function interchangeability (beyondplm.com,
  vista-industrial.com, technia.co.uk, manual.firstresonance.io).
