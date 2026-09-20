# Glossary — which "run", which "order"

Two words in this platform each name two unrelated things. The names are not
being changed (user decision 2026-09-18: a rename touches every module that
reads `production_runs` and buys nothing functional), so the disambiguation
lives here instead. **Say which one you mean.**

## The collisions

| Word | Could be | Tell them apart by |
|---|---|---|
| **run** | a **production run** — one manufacturing batch | it has a `label` like `Batch 7 — 1000 pcs`, a `run_date`, a BOM and cost documents |
| | a **programming run** — ONE attempt at programming ONE device | it has a station, an operator, a pass/fail and a log; there are thousands per batch |
| **order** | a **sales order** — what a customer asked us for | it has a customer, invoices and shipments |
| | a **JLC order** — a purchase from JLCPCB | it arrives as a fetched payload, is decided, and becomes cost on a production run |

## Every entity, once

| Thing | Table | What it is | Its page | What people call it |
|---|---|---|---|---|
| Production run | `production_runs` | One physical manufacturing batch of one project: board, quantity, date, the firmware it is programmed with, and every cost charged to it | `/runs/:id` | **"batch"** in the UI (the `label` and the column header both say Batch), "run" in the URL, the code and the register |
| Programming run | `programming_runs` | One attempt at programming one device, pass or fail, always kept | `/production/flash-runs/:id` | "run", "flash run", "attempt" |
| Sales order | `sales_orders` | One customer order, closed by invoices, fulfilled by shipments (decision [0003](../decisions/0003-orders-shipments-and-device-history.md)) | `/production/orders/:id` | "order" |
| Shipment | `shipments` | One delivery against a sales order. Its content is a set of devices | on the order's page | "delivery", "shipment" |
| JLC order | `jlc_imports` | A purchase from JLCPCB, staged before its money is assigned to a run | `/production/jlc` | "order", "JLC invoice" |
| Device | `device_units` | One physical unit, identified by the MAC read out of its chip | `/production/devices/:id` | "device", "unit", "serial", "dongle" |
| Project | `projects` | A KiCad design tracked from a git repository | `/projects/:id` | "project", "product" |

## The quantities on a production run, and what each one means

Four numbers on one row, and they are not interchangeable. This is where the
word "batch" does the most damage, because `Batch 7 — 1000 pcs` reads like a
statement of how many exist and is nothing of the kind.

| Field | Means | Filled? |
|---|---|---|
| `qty` | boards **ORDERED from JLC**. This is the number in the label | always |
| `plan_qty` | the quantity pinned into the cost baseline when the plan was frozen | rarely |
| `qty_good` | units that passed. **Legacy** — derived now for any batch that has device records, see below | never, on any dongle run |
| `qty_sold` | units billed to a customer. Revenue uses this first | on migrated runs |

**A batch routinely holds more units than were ordered.** JLC ships panel
overage, so a 455-board order can yield 568 passing devices — measured on
CE_Dongle_V2 Batch 5. Reading `qty` as "how many exist" is what made 32
delivered units look impossible on 2026-09-17.

**Good units are DERIVED, never typed** (user decision 2026-09-18). A batch
with device records knows what passed — the flasher writes a `produced` event
on the first pass, so counting those records IS the answer, and it stays right
when a device is added or moved between batches. `qty_good` survives only for
legacy batches that have no device records at all. See
[production-economics.md](production-economics.md) for which figures divide by
it.

## Words that mean something narrower than they sound

| Word | Here it means |
|---|---|
| **planned units** | what was ORDERED (`plan_qty or qty`) — the multiplier for a supplier's per-board rate. NOT `good_units`, which is what passed and divides COST (decision [0035](../decisions/0035-a-supplier-bills-what-was-ordered.md)) |
| **written off** | genuine attrition, and a defect signal. Stock consumed by ANOTHER project's assembly order is counted on `external` instead — it is not a loss |
| **built** | finished AND passed (decision [0007](../decisions/0007-built-means-finished-and-passed.md)) — not assembled, not shipped |
| **stock** | devices whose newest event leaves them `in_stock`. An `allocated` device is on the shelf but is NOT stock |
| **delivered** | `shipped` events that no `unshipped` event reversed. Nothing else: a delivery names devices, and there is no quantity field on a shipment line (decision [0049](../decisions/0049-a-delivery-names-its-devices-and-nothing-else.md)) |
| **without a serial** | RETIRED. It meant a unit on a shipment that named no device. There is no such thing any more — `shipment_lines` is dropped, a quantity is refused with 422, and a batch with no device records is built 0 rather than holding a pool (decisions [0032](../decisions/0032-a-shipment-names-its-devices.md), [0049](../decisions/0049-a-delivery-names-its-devices-and-nothing-else.md)) |
| **overbuilt** | more devices passed programming than the batch is recorded to hold — the run quantity is wrong, or devices were filed under the wrong batch. It replaced **overdrawn**, which counted units shipped against a pool that no longer exists |
| **uncharged draw** | consigned stock that has LEFT the pool with no run charged: `ComponentConsumption` with `run_id` NULL. JLC reported it on an invoice; who pays has not been decided yet, or never will be because the order builds a project this platform does not track (decision [0034](../decisions/0034-stock-moves-when-the-supplier-says-so.md)) |
| **stranded decision** | an assembly order that was decided and never applied. Nothing was written for it — no stock moved, no run was charged — so it is NOT a kind of "decided" |
