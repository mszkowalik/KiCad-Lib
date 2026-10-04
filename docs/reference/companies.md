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

`access.require_company_access` is an app dependency (decisions 0065 and
0070). It reads the matched route's path parameters, its query parameters and
its body, on HTTP and on WebSockets, and answers 404 (a WebSocket: close code
1008) to a user of no company the record belongs to. A body is read as JSON
whatever its Content-Type says, three levels down and each item of a list of
ids, unless it is a form, whose fields are read. The agent route takes only
`application/json`. An
admin passes, and so does a request with no user while auth is off.

* **An id is parsed as FastAPI parses it** (`as_id`: `"15371.0"` is 15371, a
  JSON `true` is 1). A value that is no id is refused, never skipped. A
  resolver marked `_raw` takes text instead: a scanned device code
  (`serials`, `codes`) or a JLC order code (its decision's batch).
* **Every path parameter is classified** in `access.RESOLVERS` (company data,
  keyed by prefix and name, because `device_id` names two different records)
  or `access.NOT_COMPANY_DATA` (shared on purpose). **Every `*_id` query
  parameter, body key and agent-tool argument** is classified in
  `access.FIELD_RESOLVERS` (keyed by key, or by route path and key where one
  key means two records), `access.NOT_COMPANY_FIELDS` or, for a list of ids
  or text, `access.NOT_COMPANY_LISTS`. The tests fail on a new one in none.
* **A route that meets a record where the gate cannot read it checks it
  itself**: the live simulator's first message (`access.hides_project`), the
  broker password export (`access.visible_device_ids`, the gate's device rule:
  the batch's company, else the project's).
* **`run_id` under `/api/flasher/runs/`, `/api/flasher/ws/` and on
  `/api/flasher/checks/recompute` is a programming attempt**, not a batch.
* **A project belongs to every company that ever owned it**, so a company still
  opens its own past batches after a move. A document no company is named on
  yet belongs to everybody. A write-journal batch belongs to the companies of
  the rows it touched (`write_batch_companies`), and only a caller who sees
  all of them reverses it.
* **A legacy shared token is nobody** (`auth_via == "legacy"`): it sees no
  company's records, through the gate or the agent tools.
* **`access.allowed_companies(db)`** is the caller's companies, or None for no
  limit (an admin, auth off, an internal call with no request). Use it where a
  route filters by hand: the broker password export, the write journal list,
  the agent tools.
* **The agent tools arrive as a JSON body**, so their id arguments pass the
  gate. A tool that names a project or a batch by NAME calls
  `agent_tools._visible` itself, and a new one must. `get_audit_log` checks
  the admin role itself.

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
* **"All companies" on the Stock page is a combined total on purpose** (user
  decision 2026-10-04): quantities and value summed, one average. It is a
  display, never the stock a draw, a price or a guard reads — those always take
  one company once the switch is on. The switch itself goes once production is
  migrated (`docs/todo.md` row 39): the companies' stock must never mix.

## Transfers

A transfer is an in-house document (`doc_type="transfer"`, `MM nnnn/yyyy`)
billed to the receiver, naming the sender in `counterparty_company_id`, plus
one sender draw per position (`transfer_line_id`, basis `transfer`, no batch).

* **Price**: the lot's landed cost when the units' lot is named, else the
  sender's moving average on the date.
* **A lot transfer takes the receiver's draws bound to that lot** (decision
  0069): oldest first, dated on or after the transfer, up to the moved
  quantity, a binding split when only part of it moves. A caller may name the
  bindings itself (`rebind_ids`, or `rebind` with a quantity). The lot's
  capacity is checked net of the moved bindings, by the lot's own key, so an
  adjustment lot moves like a purchase.
* **Never edited.** `_guard_closed` refuses every write path on a transfer
  document, `DELETE /api/consumption/{id}` refuses its sender draw, and no
  document may be TYPED `transfer` (`run_costs.DOC_TYPES`).
  `transfers.reverse` voids it whole, and is refused while the receiver used
  what it got (a moved binding counts as used).
* **Out of the money totals.** `invoice_register` skips transfer documents in
  every total and reports `transfers_usd` and `transferred_out_usd`. The
  sender's draw is neither uncharged nor a batch cost.
* **Out of the one pool.** With no company, `run_actuals._pool_events` leaves
  out both sides, or the replay would re-price the part. The lot ledger asks
  `with_transfers=True`, because a transfer's position is a lot.
* **Transfers ignore the switch.** They replay each company on its own,
  because they are what makes the switch possible.

### Transfers written for a draw (`transfers.cover_draws`)

Units bound to another company's lot move by transfer: a transfer already
written into the receiver for the part, on or before the draw, with room no
draw is bound to (`free_positions`, same lot first, then no lot — a transfer
that named no lot takes the lot), else a new one at the lot's cost and dated
with the draw. The rest must be in the receiving company's stock
(`check_shortages(..., exclude_draw_ids=)` leaves the moving draws out of the
replay). Then the draws are stamped. Three callers, each only stamping while
the switch is off:

* `jlc_apply.charge_draws` — charging a JLC order to a batch. An order with no
  draws yet is drawn uncharged first, then charged
  (`routers/jlc_import._charge_or_draw`).
* `transfers.move_batch_stock` — a batch moved to the other company
  (`PATCH /api/runs/{id}` with `company_id`). Its draws, its steps' draws and
  its charged losses go with it; a found unit charged to it must not strand
  the old company's draws. The move's journal batch (`run.company`) is not
  reversed from the Ledger: move the batch back.
* `PATCH /api/consumption/{id}/company` — the company of an uncharged draw
  (a JLC warehouse pick, an external order), from Admin → Companies.

A correction takes its original's buyer, and a loss charged to a batch is its
company's (`add_adjustment` refuses another).

`GET /api/transfers/history` plans the past's transfers.
`POST /api/transfers/history` (admin) writes them and checks each again. A
draw bound to the other company's lot moves that lot and its binding; a
written transfer of the same lot that no draw is bound to yet counts as moved.
Any other shortfall comes from the other company's stock on the draw's date,
at its average. The replay counts a lot move once: a purchase of the receiver
and a draw of the sender, with the draw itself whole.

## Order of work on a deployment

1. `POST /api/companies/backfill` (decision 0063): ownership, batches, orders,
   memberships.
2. `POST /api/companies/stock-backfill` with `fetch_jlc`: buyers, draws
   (an uncharged draw from the one company whose lots it is bound to),
   adjustments. Set the remaining buyers by hand on the invoices, and the
   remaining draws' companies on Admin → Companies.
3. `POST /api/transfers/history`: the past's transfers.
4. Turn on `stock_per_company`.

Admin → Companies runs steps 2 and 3 with a dry run first.
