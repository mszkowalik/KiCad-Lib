---
status: accepted
date: 2026-11-09
decision-makers: Mateusz Kowalik
---

# Plan a contract with drafts the plan owns, and give every planned date a fixed value or an anchor

## Context and Problem Statement

The 2027 plan for Columbus Energy (CE) covers 5,600 units: 3,000 `CE_DONGLE_V3` in 10
orders and 2,600 CE Dongle V3 AC in 15 orders. It lives in two places outside Henry:
`CE_Dongle_v3_board/docs/reference/production-plan-2027.md` and the Google sheet
"CE Dongle V3 i V3 AC: harmonogram zamówień, dostaw i płatności" (six tabs). Henry holds
the facts the plan is built from (orders, invoices, batches, stock, the JLC inventories),
but nothing that lies ahead of today. Three days after the plan was written, it no longer
matched the facts. By its own statement, the JLCPCB order COB202611051831177 of 2026-11-05
and the Takachi enclosure delay are not in its calendar.

The user wants the plan to be a function of Henry. The user stated these facts on
2026-11-09:

* CE has not placed V3-1 or V3-2. A schedule must go into Henry before the customer orders.
* When an order date moves, the schedule moves with it. It keeps the absolute dates and the
  lead times that a manufacturer confirmed. Some waits are fixed in time. Some always count
  from the start of production.
* Enclosure machining is four process steps, done at one time. The plan treats it as one
  block, scheduled as machining lots of given durations.
* A planned order is a draft of the real order, so the plan needs no tables of its own for
  order data.
* Purchase drafts are made automatically or semi-automatically while planning. They are
  removed, or marked out of date, when the plan changes or is deleted. No leftovers.
* The plan chooses the design snapshot of each project. CE_Dongle_V3 stays on `hw-v3.3.1`.
  CE_Dongle_V3_AC follows `main`, because its design is in progress.
* Some JLC parts orders are already placed for this plan. The plan must be able to say how
  much of the stock was bought for it.
* Scope: this contract only, the cash of this contract only. The V3 AC milestones are part of
  the plan. Phase 1 has no export. Home shows overdue payments of existing orders and
  shortages.

## Decision Drivers

* One source of truth: the plan reads live facts (a paid advance, a JLC stock figure, a
  confirmed date), never copies of them.
* A draft changes no existing figure: demand, revenue, Home, the invoice register, the
  company books, the accountant's list.
* A figure the server can compute is never typed: invoice amounts, due dates, totals,
  shortages.
* Planning leaves nothing behind.
* A date that a supplier or the customer confirmed never moves by itself.
* A shortage is found for any part by the same rule. No code names one part.

## Considered Options

* Drafts of real records that a plan owns, planned dates as fixed or anchored nodes, a
  balance over time for every part, and purchase proposals that are computed and not stored
* Separate plan tables with versions (plan orders, plan batches, plan purchases), linked to
  the real records later
* The same drafts, but every purchase proposal stored as a draft row
* Keep the sheet and import it
* Planned batches only (`production_runs.status = planned`)

## Decision Outcome

Chosen option: drafts of real records that a plan owns, because a draft travels the pages a
real order already has, and confirming it is one edit, not a copy.

### The plan and its customer side

1. **A plan is a group.** A new table `plans` holds a name, the customer, the company and the
   contract parameters: the advance share, the final-invoice terms, the minimum months from
   the advance due date to the first delivery, the advance limit per due date (net), the
   delivery weekday, the build lead (a unit leaves the line this many days before its
   delivery, 7 for CE 2027) and the attrition percentage. A record joins a plan with
   `plan_id`.
2. **A planned order is a draft sales order.** `sales_orders.draft` sits next to
   `cancelled`. A draft stays out of the open quantity of `project_demand`, out of the Home
   line "orders are not fully shipped", out of order economics and out of revenue. It takes
   no shipment, allocation or invoice. When the customer places the order, the flag goes off,
   the order reference goes in, and the order-date node becomes fixed. Five modules read
   `SalesOrder` today: `services/orders.py`, `routers/orders.py`, `services/access.py`,
   `services/companies.py` and `services/flasher/bench_checks.py`.
3. **An order line has a delivery schedule.** A new table `sales_order_deliveries` holds a
   line, a date node and a quantity. A confirmed order keeps it too, and its shipments are
   compared with it.
4. **An invoice is computed until it exists.** The advance is the advance share of the order's
   net value, on the order date, due by the customer's terms. The final invoice is the rest,
   dated on the last delivery, due by the final-invoice terms. A real invoice of the order
   replaces the computed one. Its paid date moves every node that follows the advance.

### Dates

5. **Every planned date is a node.** A new table `plan_nodes` holds the subject (order,
   advance, delivery, batch order, batch arrival, purchase, purchase arrival, machining lot,
   milestone), a mode and a source. Mode `fixed` holds a date. Mode `after` holds one or more
   predecessors, a lag and its unit (days, working days, weeks, months), and an optional snap
   to a weekday. Source is `estimate`, `measured` or `confirmed`, with a text. The server
   computes the dates in a forward pass: an `after` node takes its latest predecessor plus the
   lag. A `fixed` node never moves. A fixed node that falls before a predecessor is a
   conflict, shown on the plan and on Home. A fact turns its node fixed: the order date when
   the customer orders, the arrival when the goods come.
6. **A late task of ours counts from today.** An open node of ours whose date has passed
   takes today's date, and the nodes after it move. A customer date in the past is a blocker.
   The plan does not move it.
7. **A milestone is a node with a label and no record**: PCB layout, prototype order,
   bring-up, the safety and EMC test.
8. **The calendar is computed.** Polish public holidays come from a function, with 24 December
   from 2025. A supplier closure, for example Chinese New Year, is a fixed node.

### Batches, designs and work

9. **A planned batch is a production run with status `planned`** and a `plan_id`, with nodes
   for its order and its arrival.
10. **The plan chooses the design of each project.** For each project the plan names a snapshot
    source: one fixed snapshot, or "follow a branch" (the newest ingested snapshot of that
    branch). CE 2027 starts with CE_Dongle_V3 fixed on snapshot 1080 (`hw-v3.3.1`) and
    CE_Dongle_V3_AC following `main`. A planned batch takes the plan's snapshot and the
    project's current published process version. A draft process version changes nothing.
11. **An ordered batch is frozen.** When a planned batch is ordered, its snapshot and process
    version are pinned, as on every batch today. A later design reaches it only through a move
    with a preview: `twins.repin` for the process, the batch's snapshot field for the BOM.
12. **A change of inputs is shown, not only applied.** The plan stores the inputs a person last
    reviewed: the snapshot and the process version of each project. When a current input
    differs, the plan shows the BOM and recipe difference and its effect (new shortages,
    drafts out of date, ordered surplus with its value, cost per unit) with a "Reviewed"
    button.
13. **Work has a rate.** A prepared-part recipe (decision
    [0058](0058-a-process-is-versioned-stages-over-the-pool.md)) may state `rate_per_day`, in
    units per working day. The plan schedules machining lots: a recipe, a quantity, a start
    node, and a duration from the lot's own rate, else the recipe's, or a fixed number of
    working days. The line rate, in units per week, is set per project in the plan
    (`plan_projects.line_rate_week`), because it is the plan's capacity, not the process's.
    Enclosure cutting is the recipe `cut_enclosure` of the CE_Dongle_V3 process.

### Parts, sources and purchases

14. **Every part has a balance over time, computed on read.** The need is each planned batch's
    BOM times its quantity plus attrition, on the batch order date, and each process step
    input on the build date (delivery less the build lead). The supply, in this order: stock
    reserved for the plan (item 18), own free stock (the pool, which already holds the parts
    at JLC, less the reservations of other plans and the remaining step inputs of the batches
    in work), purchases that are drafted or ordered, on their arrival nodes, and machining
    lots. JLC public stock is a
    separate tier, marked as not ours. A prepared part expands through its recipe: a need for
    part 577 becomes machining lots that need part 233 and working days at the recipe rate. A
    part whose balance falls below zero before its need date is a blocker with a chart on the
    plan. The full chart is on the part's page.
15. **A supply source has a lead time and a quantity at once.** `component_suppliers` gains a
    lead time in days, the quantity the supplier can deliver at once, a source text and an
    as-of date. A JLCPCB part with no typed lead time takes the measured one: the last receipt in
    JLC's own inventory ledger less the order day that the parts order's number carries. A
    PCBA lead time is not measured: a planned batch's arrival lag is typed (20 days by
    default, source "estimate"). A part with no source that has
    a lead time reads "no source with a lead time": the shortage shows, the arrival does not.
16. **A purchase proposal is computed and never stored.** Each shortfall becomes proposals:
    first the source with quantity at once, then the source with the long lead time (for the
    enclosures: LC Elektronik 1,100 at once, then Takachi at 4 months). The earliest order
    date is the later of today and the day the advances received cover it. The earliest
    arrival adds the lead time. A proposal's key is the plan, the supplier, the part and the
    batch it serves.
17. **A person accepts a proposal into a draft purchase order**, one proposal or every
    proposal of a week in one click. New tables `purchase_orders` and `purchase_order_lines`
    hold the status (`draft`, `ordered`, `received`), the `plan_id`, the proposal key and a
    copy of the proposal as it was accepted. A draft counts as supply, so a proposal still open
    for its part is what is missing beside it, and an end balance above the free stock is what
    it brings too much of. Either makes the draft read "out of date" with the quantity the plan
    needs now. It offers "take the new quantity" and "delete". The engine never rewrites or deletes a draft by itself. An
    ordered purchase is never changed by the plan. A quantity the need no longer uses is a
    surplus, shown with its value.
18. **Stock can be reserved for a plan.** A new table `plan_reservations` holds the plan, the
    company, the part, a quantity, an optional source (a purchase position or a JLC lot) and
    a note. A purchase order of the plan reserves its quantity when it arrives. A person can
    reserve an earlier purchase, for example the JLC parts orders of 5 and 6 November 2026, or
    stock already on the shelf. A reservation moves no stock and no money: a draw keeps the
    moving average (decision [0105](0105-a-draw-takes-the-moving-average.md)). What is left of
    it is the reserved quantity less what the plan's batches drew, computed. Other demand sees
    only the free remainder. A draw the supplier reported (decision
    [0034](0034-stock-moves-when-the-supplier-says-so.md)) may take reserved stock. Henry does
    not refuse the supplier's fact, and the plan shows the reservation that fell short as a
    blocker.

### Deleting, checks and screens

19. **Deleting a plan deletes what it owns**: the draft sales orders, the planned batches with no
    units, the draft purchase orders, the reservations and the nodes. One write batch does it,
    after a confirmation that lists them, and History → Write batches undoes it (decision
    [0089](0089-every-change-is-recorded-and-can-be-undone.md)). Ordered and real records stay,
    and their `plan_id` is cleared. Stock stays where it is.
20. **The checks.** The first delivery is not earlier than the advance due date plus the
    minimum months. The advances due on one date are within the limit. An order is delivered
    in one calendar month. The purchases, added up over time, stay within the advances
    received. No batch is in production over a supplier closure. The boards and every part
    cover each build. Parts that the customer supplies (the SIM cards) arrive before the units
    need them. No node is in conflict. A check that passes draws nothing.
21. **Home shows** the sales invoices past their due date, the orders shipped but not invoiced,
    the purchases to place this week, the late advances and the deliveries they move, the node
    conflicts, the projected shortages, the broken reservations and the JLC public stock under
    the need.
22. **The screens.** The plan page is a tab, Sales → Plans: the blockers, the timeline, the
    weekly deliveries, the parts short, the cash, the week-by-week agenda. A draft order is a
    row on Sales → Orders with a draft mark. A planned batch is a row on Production → Batches.
    Purchase orders get a tab, Stock → Purchase orders. A part's balance over time is on
    the plan's Parts tab. A JLC parts order on Stock → JLCPCB can be reserved for a plan,
    whole or position by position. No new top-bar section.

The other options:

* **Separate plan tables with versions** keep every order twice, and someone must keep the link
  to the real record. The user refused new tables of order data on 2026-11-09. Versions would
  repeat what the change log already holds.
* **Stored proposals** write and delete rows on every re-plan. The change log fills with machine
  noise, and a stored proposal that nobody looked at is the leftover the user does not want.
* **The sheet** stays a second source of truth. A server read of it needs a Google credential on
  the deployment, as in decision
  [0104](0104-an-organizer-box-says-where-the-ledger-says-what-it-cost.md).
* **Planned batches only** give no dates ahead, no purchases and no cash. `/api/demand` already
  counts planned batches, with no date.
* **A production-snapshot pointer on the project** was proposed and refused by the user on
  2026-11-09: the plan chooses its own snapshot.

### Consequences

* Good, because a moved order date moves only what follows it. Confirmed dates stay, and a
  conflict shows instead of a silent slip.
* Good, because a late advance, a new JLC stock figure, an arrival, a new snapshot or a new
  process version changes the plan on the next read, with no edit, and the change is shown.
* Good, because a shortage of any part is found the same way. The Takachi enclosures need no
  code of their own.
* Good, because planning leaves nothing behind. A proposal is not stored. A draft and a
  reservation are owned by their plan and leave with it, and the delete can be undone.
* Bad, because every reader of sales orders must leave drafts out. A missed reader counts a draft
  as demand or revenue. A test guards the readers.
* Bad, because the forward pass does not level resources. Capacity and funding are checks, not
  scheduling, so the person moves the nodes.
* Bad, because the proposals depend on lead times, and most of them are estimates today.
* Bad, because a reservation cannot stop JLC from taking the stock for another order. It can only
  show that it happened.
* Neutral, because the plan has no versions. A "sent to the customer" baseline can freeze the
  computed dates later, as `plan_frozen_at` does on a batch.

### Confirmation

* A draft order changes no figure of `/api/demand`, the order economics, Home, the invoice
  register or the company books (one test per reader).
* Forward-pass tests: a fixed node never moves, an `after` node follows its latest predecessor,
  a fixed node before its predecessor is reported as a conflict, a working-day lag skips the
  holidays, a late open node of ours counts from today.
* Balance tests: a prepared part expands through its recipe, a reservation is served before free
  stock, a draw that takes reserved stock reports a broken reservation, a new snapshot changes
  the need of a planned batch and not of an ordered one.
* Deleting a plan removes its drafts and reservations in one write batch, and the undo restores
  them.
* A draft whose proposal changed reads "out of date" and keeps its own values.

## More Information

Phases, as agreed on 2026-11-09:

1. Plan group, draft orders with deliveries, nodes with milestones, computed invoices and
   payments, the weekly views, the contract checks, overdue sales invoices on Home.
2. Planned batches with the plan's snapshot choice, recipe and line rates, machining lots, the
   balance of every part, supply sources with lead times, proposals, draft purchase orders,
   reservations, the funding check, the input-change card.
3. Built against planned, shipped against planned, customer-supplied parts, the rest of the Home
   lines.

A mockup of the plan page on the CE 2027 data was reviewed on 2026-11-09. The user
accepted this record on 2026-11-09 and asked for all three phases at once.

Open before phase 2: the CE_Dongle_V3 process version 8 has the recipe `cut_enclosure` (internal
part 577 "SIM6-12-3W cut"), but no step uses it. Its check warns about this. The route takes the
raw enclosure (part 233) after "Receive PCBA" and cuts it in four steps, so the cutting of
enclosures before the boards arrive cannot be recorded. A machining lot needs a route that takes
part 577.

Revisit this decision if one contract needs two schedules at once (a scenario). Versions then
have a case that the change log does not cover.
