# Plans: a contract's schedule, parts and cash

A plan schedules one customer contract ahead of today: draft orders and their
deliveries, planned batches, machining lots, purchases, reservations,
milestones and closures. The reasoning is in decision
[0107](../decisions/0107-a-plan-owns-its-drafts-and-a-date-is-fixed-or-follows-its-anchor.md).
`services/planning.py` computes, `services/plans.py` writes, `routers/plans.py`
serves. The page is Sales → Plans; purchase orders are Stock → Purchase orders.

## What a plan owns

| Record | Table | Owned through |
|---|---|---|
| The plan and its contract parameters | `plans` | — |
| The design of each project | `plan_projects` | `plan_id` |
| A draft order | `sales_orders` with `draft = true` | `plan_id`, `plan_key` |
| A delivery of an order line | `sales_order_deliveries` | its line, and its date node |
| A planned batch | `production_runs` with `status = planned` | `plan_id` |
| A machining lot of a recipe | `plan_lots` | `plan_id` |
| A purchase before its invoice | `purchase_orders`, `purchase_order_lines` | `plan_id` (empty outside a plan) |
| Stock set aside | `plan_reservations` | `plan_id` |
| A part the customer supplies | `plan_customer_parts` | `plan_id` |
| Every planned date | `plan_nodes` | `plan_id`, `kind` + `subject_id` |

Nothing a plan shows is stored: dates, invoices, balances, proposals, cash,
checks and blockers are computed on every read of `GET /api/plans/{id}`.

## A draft order is outside every figure

`sales_orders.draft` keeps a planned order out of `project_demand`, out of the
Home line "orders are not fully shipped" (its status is `draft`), and out of
shipments, allocations and order invoices, which answer 409.
`POST /api/orders/{id}/confirm` turns it into a real order. **A new reader of
`sales_orders` must leave drafts out**, and needs a test that says so
(`api/tests/plans/test_planning.py`).

## Dates

- A node is `fixed` (`day`) or `after`: the latest of its references plus `lag`
  in `days`, `workdays`, `weeks` or `months`, then moved forward to
  `snap_weekday` (0 = Monday). References: `n:<node id>`, `order:<order id>`
  (the order date), `advance:<order id>`.
- `advance:` is the day the advance was paid; else its due day (the order's
  `advance_due`, else order date + `plans.advance_days`); and **today, when the
  due day has passed unpaid on a confirmed order**. So a late payment moves
  every delivery that follows the advance. A real invoice of the order
  (`sales_invoices.order_id`, or `order_invoices`) replaces the computed one.
- `done_on` is the fact. A node with it is that day and nothing moves it.
- **An open node of ours or of a supplier dated before today counts from
  today**, and what follows it moves. A customer date in the past is not moved:
  the plan reports it as a blocker.
- A `fixed` node earlier than what it lists in `after` is a conflict. A node
  that would close a circle is refused when it is written.
- Polish public holidays come from `planning.holidays` (24 December from 2025).
  A supplier closure is a `closure` node with `day` and `end_day`.

## Designs and batches

- `plan_projects` names a fixed snapshot, or `branch` mode: the newest ready
  snapshot of that branch that is not a tag.
- A planned batch reads the plan's snapshot and the project's current
  published process version. A process draft changes nothing.
- `POST /api/plans/{id}/batches/{run_id}/ordered` takes the batch out of
  `planned`, pins its snapshot and process version, and marks its order node
  done. From then on a new design reaches it only through a repin.
- `POST /api/plans/{id}/reviewed` records the inputs a person read
  (`plans.reviewed`) and moves the planned batches to them. Until then the plan
  shows the BOM difference as a blocker of severity "decide".
- A planned batch's `run_date` is written from its order node whenever the plan
  is written, so the batch lists agree with the plan. A read never writes it.
- Planning a batch asks the same design-review warning as a new batch (409
  with `review_warning`, then `ack_review`).

## The balance of a part

| Side | What | When |
|---|---|---|
| Need | BOM line × boards × (1 + attrition) of each PLANNED batch | the batch's order day |
| Need | step input × units × (1 + attrition), for every delivered unit | delivery day − `build_lead_days` |
| Need | recipe input × lot quantity | the lot's start day |
| Supply | reserved for this plan, less what the plan's batches drew | today |
| Supply | free stock: the pool (which includes the parts held at JLC) less every reservation and the remaining step inputs of the batches in work outside the plan | today |
| Supply | the plan's draft and ordered purchase lines | their arrival day |
| Supply | a lot's output, at its rate | each working day of the lot |

Status `short` is a blocker. Status `public` means only JLC's public stock
(`component_supply.jlc_stock`) covers a BOM need, and nothing reserves it. A
prepared part is never proposed for purchase: its shortage asks for a lot.
A reservation whose quantity is above the stock on hand is broken: JLC can
take reserved stock for another order, and Henry reports it instead of
refusing the supplier's fact.

## Lead times and proposals

- A source is a `component_suppliers` link with `lead_days`, `qty_at_once`,
  `lead_source` and `lead_as_of`. A JLCPCB part with no typed lead takes the
  **measured** one: a receipt in `jlc_stock_changes` (business type 5) minus
  the order day that the parts order's number carries
  (`planning.jlc_measured_leads`). When JLC's public stock covers the shortfall
  the fastest receipt counts, else the slowest: a part JLC must buy in comes as
  a presale lot, and the last receipt can be an in-stock one of 0 days. A part
  JLC must buy in whose receipts were all in-stock ones (2 days or less) has no
  measured lead time. PCBA lead time is not measured: a batch's
  arrival lag is typed (default 20 days, source estimate).
- A proposal is computed, never stored. It takes the sources with quantity at
  once first, then the first source with a lead time. Its order day is the
  later of today and the need day less the lead time; it is `late` when it
  arrives after the need day, and `no_lead` when no source has a lead time.
- Accepting writes one draft purchase order per proposal, with a copy of it.
  A draft counts as supply, so a proposal still open for its part is what is
  missing beside it: the draft reads "out of date" with `suggested_qty`, and
  `take_proposal` writes it. The plan never changes an ordered purchase; an
  ordered quantity the need does not use is reported as surplus with its value.

## Cash

The funding check sets the advances (net) on the day they were paid, else due,
against the purchases on their order day (PLN through `fx.convert`) and against
`plan_nodes.amount`, the one typed money figure: an estimate such as a batch's
PCBA fees. The lowest margin under 5,000 is a risk; below 0 it is a blocker.

## Deleting a plan

`POST /api/plans/{id}/delete` with `dry_run` lists what goes and what stays.
It deletes the draft orders, the planned batches with no units, the draft and
cancelled purchase orders, the lots, the reservations, the customer parts and
the nodes, in one request, so History → Write batches undoes it. A confirmed
order, a batch with units and an ordered purchase stay and lose `plan_id`; a
kept order's deliveries keep the days the plan computed, as fixed dates.
