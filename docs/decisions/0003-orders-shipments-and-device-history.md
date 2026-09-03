# 3. Sales orders, shipments and a per-device history replace the sale fields on a run

Date: 2026-09-03

## Status

Accepted

## Context

A production run carries its own sale: `customer`, `order_ref`, `order_date`,
`sale_unit_price`, `sale_currency` and `qty_sold` live on `ProductionRun`, and
revenue is price × `qty_sold` (decision of 2026-07-27 in
[production-costs/design.md](../production-costs/design.md), "Income: price per
device on the run"). That model assumes one run is one sale, which is no longer
true:

- A run builds more devices than the customer ordered. An order for 500 becomes
  a build of 550, and the 50 spares are kept as stock against returns and future
  orders. Today those 50 units are invisible: they are cost with no revenue, and
  nobody knows they exist.
- An order is shipped in parts. A first lot goes out from stock at once, the rest
  when the run is finished. One `qty_sold` cannot record two dates, two sources
  or two delivery notes.
- An order holds several products (an Aqua and a dongle in one order), which
  today are two projects and therefore two runs.
- A returned device is repaired, disposed of, or replaced by a device from another
  batch. The replacement's cost belongs to the order that received it, and nothing
  records that.
- Invoicing is not one document. An order is closed by one sales invoice, or by
  one or more advance invoices (normally 60 % of the net total, 14 days to pay)
  and a final invoice.

The platform already has the right identity for a device: `DeviceUnit`, keyed by
the MAC the flasher reads, linked to its production run through `ProgrammingRun`.
What is missing is what happens to a device after it passes test.

## Decision

1. **A `Customer` is a table, not a string.** Name, tax id, address, default
   payment terms (14 days). `ProductionRun.customer` is migrated into it.

2. **A `SalesOrder` sits above the project.** Customer, order ref, order date,
   currency, status (`open | partial | fulfilled | cancelled`, derived, never set
   by hand), notes. Its **lines** each name a project, an optional board and
   variant, `qty_ordered` and a net unit price. **All money on the sale side is
   net.** Every product carries 23 % VAT; the rate is a column on the order so a
   gross figure can be printed, but nothing in the platform computes with it.

3. **An `OrderInvoice` records each document issued against an order.** Kind
   (`proforma | advance | final | correction`), number, issue date, due date
   (default issue + the customer's terms), net amount, currency, `paid_at`,
   attachment. Rules:
   - The sum of `advance` and `final` (and `correction`) net amounts is expected
     to equal the order's net total. The UI shows the difference as a warning;
     nothing is blocked, because an advance percentage is a business decision.
   - A `proforma` does not count towards that sum.
   - **Revenue for the register converts per invoice at the invoice date**, the
     NBP rate the accounting uses. An order with no invoices yet converts its
     line totals at the order date, which is today's behaviour.

4. **A `Shipment` is a header, and its content is a set of devices.** Order,
   date, delivery note, tracking, kind (`delivery | return`). The quantity per
   line is derived from the device events attached to it, plus a
   `qty_unserialized` per line for legacy stock only (see 8).

5. **`DeviceEvent` is the append-only history of a device.** Device, kind,
   time, actor, note, and the references the kind needs. Kinds:

   | kind | references | meaning |
   |---|---|---|
   | `produced` | production run | passed test, in stock at that run's per-device cost |
   | `allocated` | order line | reserved, not shipped |
   | `shipped` | order line, shipment, optional `replaces_device_id` | leaves stock |
   | `returned` | order line, shipment (kind return), reason | back in the building |
   | `repaired` | zero or more repair cost lines | fit for use again |
   | `disposed` | reason | end of life |

   `DeviceUnit.state` (`in_stock | allocated | shipped | returned | disposed`)
   caches the last event. The log is the truth and `state` is rebuilt from it.
   A `produced` event is written by the flasher on the first `pass` of a device
   in a run, so no operator has to record production by hand. `RunDevice`, the
   hand-typed serial list, is retired once every open run has events.

6. **A shipment without serials draws devices FIFO from batches the user
   selects.** The dialog lists the runs of the line's project that hold devices
   in stock, the user ticks the eligible ones, and the platform assigns the
   oldest `produced` devices first. Board and variant are a filter the user may
   apply, not a constraint. When a customer later returns a device that FIFO
   never assigned to that order, the platform swaps: the returned device takes
   the place of one FIFO-guessed device on the same shipment and the guessed
   device goes back to stock. Both moves are events, so the guess and its
   correction stay visible.

7. **A return ends in one of three events.** `repaired` and back to stock,
   `repaired` and `shipped` back to the same order (`replaces_device_id` empty,
   the device is its own replacement), or `disposed`. A replacement device
   shipped from stock carries `replaces_device_id` and is charged to the old
   order. A `repaired` event may carry **repair cost lines** of kind
   `labour | material`, each with a net amount and a currency, and a material
   line may draw a component from the parts pool. Labour is not recorded for
   now, but the line kind exists so it can be.

8. **Legacy runs keep a quantity.** Runs from before the flasher recorded MACs
   have no devices to move. A shipment line therefore also carries
   `qty_unserialized`, and stock per run is `produced devices in stock +
   (qty_good − devices ever produced − unserialized shipped)`. New runs never
   use it. Placeholder devices were rejected because a fake identity would
   collide with a real MAC when an old device comes back for repair.

9. **What the numbers become.**
   - **Stock** is the count of devices in `in_stock`, per project, run, board
     and variant, valued at each device's run cost. No opening balance, no
     adjustment table.
   - **Order fulfilment** is `shipped` events without `replaces_device_id` (plus
     unserialized quantity) against `qty_ordered`, per line.
   - **Order cost** is the run cost of every device ever shipped to the order,
     replacements included, plus its repair cost lines. Revenue is the invoiced
     net total, so an order with three warranty replacements shows the cost of
     503 devices against the revenue of 500.
   - **Run margin** stays as today for the register. `ProductionRun.qty_sold`
     becomes a derived figure: devices shipped from that run. The other sale
     columns on the run are migrated (10) and then dropped.

10. **Migration.** Each run with a `sale_unit_price` becomes one `SalesOrder`
    with one line (`qty_ordered = qty_sold`, the run's price and currency), one
    `delivery` shipment dated `order_date` with `qty_unserialized = qty_sold`,
    and no invoices. Distinct `customer` strings become `Customer` rows. The
    register's figures must not change by a cent after the migration.

## Consequences

- Five tables (`customers`, `sales_orders`, `sales_order_lines`,
  `order_invoices`, `shipments`), plus `device_events` and `repair_cost_lines`,
  and a `state` column on `device_units`. A new **Orders** page and a
  **Stock** view; the Invoices view's run table gains an order column and the
  order editor moves off the run.
- The flasher writes a `produced` event, so the flasher engine and this model
  are coupled at one line. A device that fails programming never enters stock.
- The register's revenue changes meaning: invoiced net total at invoice-date
  rates, instead of order price at the order-date rate. For migrated orders
  without invoices the figure is unchanged.
- The FIFO guess is a guess. Until a return corrects it, "which device is at
  which customer" is only right if the operator ticked the right batches.
- Unserialized quantity is a second counting path that has to stay correct in
  every stock and fulfilment query until the last legacy order closes.

## Confirmation

- Migration: `GET /api/runs/register` before and after returns identical
  `revenue`, `margin` and `margin_pct` per run.
- A test builds 550, ships 500 in two shipments (100 unserialized, 400 FIFO),
  returns one device, disposes of it, ships a replacement, and checks: stock 49,
  order fulfilment 500 of 500, order cost = 501 device costs, run `qty_sold` =
  401.
- A device's history page lists the events in order and every event resolves
  its references.
