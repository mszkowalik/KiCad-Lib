---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# A batch costs, an order earns, and a UNIT is the only thing that joins them

## Context and Problem Statement

[0003](0003-orders-shipments-and-device-history.md) is titled "Sales orders,
shipments and a per-device history **replace** the sale fields on a run", and was
accepted 2026-09-03. The fields were never removed. A batch still carried
`customer`, `order_ref`, `order_date`, `sale_unit_price`, `sale_currency` and
`qty_sold`, still priced its own revenue and margin from them, and still offered
an editable "Order & sale" card.

So the same sale existed twice. Measured 2026-09-19 — **15 runs carry a sale and
22 order lines cover the same sales**, and the two disagree on every project:

| Project | Run side | Order side | Difference |
|---|---:|---:|---:|
| CE_Dongle_V3 | 38,900 | 29,250 | −9,650 |
| CE_Dongle_V2 | 1,110,500 | 1,124,500 | +14,000 |
| CE_Aqua_V2 | 144,000 | 297,400 | +153,400 |

Every difference has a cause, and none is arithmetic:

* **One batch, two orders.** Batch 7's `order_ref` literally reads
  `"ZAL 00001/03/2026 + ZAL 00001/04/2026"`. A single `qty_sold` cannot hold it.
* **A batch with no order yet.** Batch 8 carried a typed forecast of 176,000 PLN
  against nothing ordered.
* **Net against gross.** Run 2164 read 553 where its order reads 450 net at 23 %
  VAT — 450 x 1.23 = 553.50. The same sale, on two bases.
* **Ten order lines linked to no run at all**, worth 475,900 PLN.

These are exactly the cases 0003 listed. The run side cannot express any of them.

## Decision Drivers

* A number that exists twice will disagree, and nothing reconciles these two.
* The platform already joins production to sales the right way and has since
  `order_economics` was written: it sums a per-unit cost over the devices an
  order shipped.
* A per-device cost is carried onto real invoices. It must not be an estimate.

## Considered Options

* A batch reports cost only; a unit carries its cost to the order.
* Keep both and reconcile them on a report.
* Keep the run sale and drop the order side.

## Decision Outcome

Chosen option: "A batch reports cost only".

1. **A batch has no revenue and no margin.** `run_actuals` and the register's
   `by_run_usd` return cost, `produced` and `unit_cost_usd`. The run page and the
   production overview show costs; the "Order & sale" card is gone.
2. **The UNIT is the join** (user decision 2026-09-19). A batch computes what one
   device cost; a device carries it; an order's cost is the sum over the devices
   it shipped. `orders.per_device_cost_usd` already fed `order_economics` this
   way — nothing new was needed on the order side.
3. **The denominator is devices PRODUCED**, counted from `produced` events.
   `per_device_cost_usd` divided by the run's typed `qty` — the boards ordered
   from JLC — while its own docstring claimed "per GOOD device". A batch
   routinely yields a different number (Batch 5: 455 ordered, 568 produced), so
   the figure was wrong by the yield on every batch.
4. **A batch with no device records has NO unit cost.** It is absent from the map
   and null in the API, and an order shipping such a device reports it as
   `uncosted`. A cost divided by a planned quantity is an estimate, and this
   figure lands on invoices.
5. **Prices and currencies come from the order.** Nothing reads the run's sale
   columns. They stay in the database as history and are no longer written.
6. **Billing denominators split**: a batch divides by units produced, an order
   bills the units it billed. They are different questions and were sharing one
   field.

### Consequences

* Good, because there is one revenue figure and it sits where the invoice does.
* Good, because per-device cost stopped being wrong by the yield. Batch 5 moves
  from cost/455 to cost/568.
* Bad, because two batches (8 and V3 Batch 1) now show no unit cost at all —
  they have no device records. That is the true state; the old number was a
  planned-quantity estimate.
* Neutral, because the stored sale columns are untouched. Nothing reads them, so
  they can be dropped in a later migration once nobody misses them.

### Confirmation

`per_device_cost_usd` returns 15 runs, and runs 19 and 2164 are correctly
absent. The run page shows cost tiles only; the production overview totals read
production cost, boards ordered, devices produced and average cost per device
produced. No endpoint returns `revenue` or `margin` for a run.

## Pros and Cons of the Options

### Batch costs, order earns, unit joins

* Good, because it matches what the platform already does on the order side.
* Good, because every case 0003 listed is expressible.
* Bad, because a batch that has not reached the bench reports no unit cost.

### Keep both and reconcile

* Good, because no screen changes.
* Bad, because the reconciliation would have to be written and then maintained
  forever, for two numbers that should never have been two.

### Keep the run sale, drop orders

* Bad, because it cannot express one batch serving two orders, a part shipment,
  or an order holding two products — which is the whole of 0003.

## More Information

Completes [0003](0003-orders-shipments-and-device-history.md), which decided
this and was never finished. Narrows
[0030](0030-good-units-are-counted-not-typed.md): good units remain counted, and
the per-device COST now divides by them rather than by the boards ordered.

Revisit to drop the six sale columns from `production_runs` once it is clear
nobody reads them for history.
