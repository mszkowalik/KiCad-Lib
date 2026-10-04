# Companies

The platform keeps the books of two companies: 7Sigma and 9SIGMA. The
reasoning is in [decision 0063](../decisions/0063-two-companies-own-projects-over-time.md).
The code is `api/app/services/companies.py` and `api/app/routers/companies.py`.

## What belongs to a company

| Record | How it names its company |
|---|---|
| Project | `project_ownership`: dated periods. The owner on a day is the period with the latest `from_date` on or before it (`owner_on`). Before the first period, the first owner answers. |
| Batch (`production_runs.company_id`) | Set when the batch is created: the request's `company_id`, else the project's owner on the batch date (`default_run_company`). Frozen while the books are closed. |
| Sales order (`sales_orders.company_id`) | The request's `company_id`, else the user's only company, else the owner of the first product's project on the order date (`routers/orders._seller`). |
| Supplier document (`run_cost_documents.company_id`, `company_source`) | Not filled yet. The buyer of each invoice will be read from the invoice. |

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
  are `GET /api/projects` (by the current owner), `GET /api/runs` and
  `GET /api/orders`.
* The scope is a filter, not access control. A detail route answers for any
  company.

Changing the switcher reloads the page, because every list on it was fetched
for the old scope.

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
