# Companies

The platform keeps the books of two companies: 7Sigma and 9SIGMA. The
reasoning is in [decision 0063](../decisions/0063-two-companies-own-projects-over-time.md)
(companies and ownership) and [decision 0064](../decisions/0064-each-company-draws-from-its-own-stock.md)
(stock and transfers). The code is `services/companies.py`,
`services/company_backfill.py`, `services/transfers.py` and the routers
`companies.py` and `transfers.py`.

## What belongs to a company

| Record | How it names its company |
|---|---|
| Project | `project_ownership`: dated periods. The owner on a day is the period with the latest `from_date` on or before it (`owner_on`). Before the first period, the first owner answers. |
| Batch (`production_runs.company_id`) | Set when the batch is created: the request's `company_id`, else the project's owner on the batch date (`default_run_company`). Frozen while the books are closed. |
| Sales order (`sales_orders.company_id`) | The request's `company_id`, else the user's only company, else the owner of the first product's project on the order date (`routers/orders._seller`). |
| Supplier document (`run_cost_documents.company_id`, `company_source`) | The BILLED company. A JLC import reads it from `taxVatBilling`. A typed document takes the request's company, else the user's only one. The backfill below fills the past. A person changes it on the invoice. |
| Draw, adjustment (`company_id`) | Stamped on insert from the batch, the step, the transformation or the project's owner on the day (`companies.stamp_stock`). An uncharged JLC draw takes its assembly invoice's buyer. |

Never derive a batch's or an order's company from its project's CURRENT owner.
A project can move, and a record keeps the company it had.

## Moving a project

`move_project` adds a period and edits none. It refuses:

* a date that is not after the start of the current period;
* a date before the new company's `started_on`;
* a move to the company that already owns the project.

Only an admin can move a project (`POST /api/projects/{id}/ownership`), from the
project's Settings tab. No route edits or deletes a period.

## Who sees what

* `visible_ids(db, user)`: the user's memberships (`user_companies`). An admin,
  and the dev posture with no user, see every company.
* `scope_ids(db, request)`: the companies a view shows. The web header switcher
  stores the selection in `localStorage["company.scope"]`, and `api.ts` sends
  it as `X-Company` on every request (`<id>` or `all`). A company the user may
  not see is never in the scope, whatever the header says.
* A list route that respects the scope filters `company_id IN scope OR
  company_id IS NULL`, so a row nobody assigned yet stays visible. Today these
  are `GET /api/projects` (by the current owner), `/api/runs`, `/api/orders`,
  `/api/transfers`, `/api/shipments` (by the order's seller),
  `/api/flasher/devices` (by the batch's company, else the project's owner) and
  `/api/invoices` (the documents billed to the company, the transfers it sent,
  and the ones naming no company). `companies.narrows` skips the filter when
  the scope holds every company.
* The scope filters a LIST. Opening ONE record is gated separately, below.

Changing the switcher reloads the page, because every list on it was fetched
for the old scope.

## Opening one record

`access.require_company_access` is an app dependency (decision 0065). It reads
the matched route's path parameters and answers 404 to a user of no company the
record belongs to. An admin, and a request with no user, pass.

* **Every path parameter is classified** in `access.RESOLVERS` (company data,
  keyed by prefix and name, because `device_id` names two different records)
  or `access.NOT_COMPANY_DATA` (shared on purpose). The test fails on a new one
  in neither.
* **A project belongs to every company that ever owned it**, so a company still
  opens its own past batches after a move. A document no company is named on
  yet belongs to everybody.
* **The agent tools are not behind this gate**: they open their own sessions.
  `get_audit_log` checks the admin role itself.

## The backfill

`POST /api/companies/backfill` (admin, `dry_run` true by default) gives the
existing data its companies. It touches only rows that have none, so it can
run twice. The rules it applies are item 6 of decision 0063. It reads an
order's seller from the first word of each invoice note (`7Sigma;` or
`9Sigma;`), and a batch's seller from the orders that shipped its devices.

## Seller data

A company's legal name, address, bank account and payment terms are edited on
Admin → Companies. `GET /api/companies` returns them to an admin only. The
audit row of an edit names a changed bank account but does not hold the number.
Do not put a bank account in a seed, a fixture or a test.

## Stock per company

`stock_per_company` (Admin → Configuration) is the one switch. While it is off
there is one pool, as before. `appconfig.validate` refuses to turn it on while
`companies.stock_without_company` counts any live document with parts, draw or
adjustment that names no company.

* **Every caller that prices or guards a draw goes through
  `run_actuals.stock_scope`** (or `run_scope` for a batch, `project_scope` for
  a project's owner on a day). It returns the company while the switch is on
  and None while it is off, and the replay functions take it as
  `company_id`: `pool_state`, `component_ledger`, `check_shortages` (also per
  candidate), `resolve_pool_identity`, `parts_stock`, `process.prepared_lots`.
  A new caller that passes nothing reads both companies as one pool, which is
  wrong once the switch is on.
* **A purchase loss is the buyer's.** `purchase_loss_of` and
  `batch_purchase_losses` key the loss by the document's company. A new buyer
  on a document is a total loss to the old buyer
  (`routers/run_costs._guard_buyer_change`, on both the header PATCH and the
  batch edit).
* **The register reports each company's pool** under `pool.by_company`, and
  `negative_stock` names the company that went short.
* **The stock pages follow the header scope**: `parts-stock` and
  `parts-ledger` read one company's stock when the switch is on and one
  company is selected. JLC's side is always the whole shelf.

## Transfers

A transfer is an in-house document (`doc_type="transfer"`, `MM nnnn/yyyy`)
billed to the receiver, naming the sender in `counterparty_company_id`, plus
one sender draw per position (`transfer_line_id`, basis `transfer`, no batch).

* **Price**: the lot's landed cost when the units' lot is named, else the
  sender's moving average on the date.
* **Never edited.** `_guard_closed` refuses every write path on a transfer
  document. `transfers.reverse` voids it whole, and is refused while the
  receiver used what it got.
* **Out of the money totals.** `invoice_register` skips transfer documents in
  every total and reports `transfers_usd` and `transferred_out_usd`. The
  sender's draw is neither uncharged nor a batch cost.
* **Transfers ignore the switch.** They replay each company on its own,
  because they are what makes the switch possible.

`GET /api/transfers/history` plans the past's transfers.
`POST /api/transfers/history` (admin) writes them and checks each again. A
draw bound to the other company's lot moves that lot and its binding. Any
other shortfall comes from the other company's stock on the draw's date, at
its average.

## Order of work on a deployment

1. `POST /api/companies/backfill` (decision 0063): ownership, batches, orders,
   memberships.
2. `POST /api/companies/stock-backfill` with `fetch_jlc`: buyers, draws,
   adjustments. Set the remaining buyers by hand on the invoices.
3. `POST /api/transfers/history`: the past's transfers.
4. Turn on `stock_per_company`.

Admin → Companies runs steps 2 and 3 with a dry run first.
