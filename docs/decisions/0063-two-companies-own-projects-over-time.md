---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04 to the two-company plan)
---

# Keep the books of two companies in one platform, and let a project change owner on a date

## Context and Problem Statement

The user owns two companies. 7Sigma is a sole proprietorship (NIP 8513262910).
9SIGMA sp. z o.o. is a limited company (NIP 8513315635) that exists from
2024-07-22. Both buy parts, build devices and sell them, and both must keep
their own books. Until now the platform knew one company only.

The user's answers of 2026-10-04 set the requirements:

* Every Dongle and Aqua project belongs to 9Sigma. Every other project belongs
  to 7Sigma.
* A project can move to the other company. The move happens on a date, and the
  platform must still know who owned the project before it, for the accounts
  and the invoices.
* Batches and orders are assigned to a company one by one. The prototype
  batches of the Dongle V2 and the Aqua were 7Sigma's, because 9Sigma did not
  exist yet.
* The user's admin account sees every company. Other users see the companies
  they belong to. A small control at the top right selects one company, or
  "All".
* Customers are shared by both companies and are matched by NIP.

## Decision Drivers

* A past record keeps the company it had. A move never rewrites history.
* One fact is stored once. The owner on a date is read from one list of
  periods, never copied onto each record.
* Nothing is hidden from the admin, and nothing a user cannot see is shown to
  them.
* The work the platform already does (processes, twins, stock, invoices) keeps
  working while companies are added in steps.

## Considered Options

* One deployment per company.
* One platform; a project is shared by both companies.
* One platform; a project belongs to one company at a time, in dated periods.
* One platform; a project has one owner field that a move overwrites.
* A batch and an order always take their project's owner, or each names its
  own company.

## Decision Outcome

Chosen option: "one platform; a project belongs to one company at a time, in
dated periods", and "each batch and order names its own company". The user
rejected shared projects. Two deployments would split the shared customers,
the shared JLCPCB account and the stock moves between the companies over two
databases. One owner field forgets who owned the project before a move.

1. **A company is a record** (`companies`), identified by its NIP, with the
   data it prints as a seller. An admin edits it on Admin → Companies. The NIP
   does not change: a different NIP is a different company.
2. **A project belongs to one company over time** (`project_ownership`). Each
   row starts on a date, and the owner on a day is the row with the latest
   start on or before it. A move adds a row and never edits one. A move must
   start after the current period, and never before the new company existed.
   Moving a project is admin work.
3. **A batch, a sales order and a supplier document each name their company**
   (`company_id`). A new batch takes its project's owner on its date. A new
   order takes the company that the request names, else the user's only
   company, else the owner of its first product's project on its date. A
   person can change either, but not on a batch whose books are closed.
4. **A user sees the companies they belong to** (`user_companies`). An admin
   sees every company. Admin → Users sets the memberships.
5. **The header switcher selects the scope**: one company, or all the
   companies the user may see. It sends `X-Company` with every request, and
   the project, batch and order lists show only rows in that scope. A row with
   no company yet shows in every scope. Each of these lists has a Company
   column with a filter.
6. **The existing data is given companies by a backfill**, dry run by default.
   The Dongle V2 and the Aqua projects belong to 7Sigma until 2024-07-22 and to
   9Sigma from then. The Dongle V3 belongs to 9Sigma. Every other project
   belongs to 7Sigma. A batch takes the company that sold nine in ten or more
   of its shipped devices (each order invoice note starts with the seller),
   else its project's owner on its date. An order takes the seller its
   invoices name, else its project's owner. Every user starts as a member of
   both companies.

### Consequences

* Good, because a 2024 batch or invoice still reads as the company that made
  or sold it, after any later move.
* Good, because the admin sees both companies at once, or one of them, from
  every list.
* Bad, because the scope filters the lists only. A user who has the address
  of a batch, an order or a project of another company can still open it.
  This stays true until access is enforced on every route.
* Bad, because stock is still one pool for both companies. A batch of 9Sigma
  can draw a part that 7Sigma bought. Stock per company, and the in-house
  transfers between the companies, need their own decision.
* Neutral, because the supplier document's `company_id` exists but is not yet
  filled. The buyer of each past invoice is found from the invoice itself in a
  later step.

### Confirmation

Tests show that:

* the owner of a project on a date follows its periods, and a move refuses a
  date before the current period, a date before the company existed, and the
  same owner;
* a new batch takes its project's owner on its date;
* the scope never includes a company that the user may not see;
* the backfill reads an order's seller from its invoice notes.

A local run of the backfill gave 6 ownership periods, 20 batches, 18 orders
and 3 memberships. With 9Sigma selected the batch list shows 15 of 20 batches,
and with 7Sigma selected the EVSE project with its 5 batches and 6 orders.

## Pros and Cons of the Options

### One deployment per company

* Good, because the separation is complete.
* Bad, because the customers, the JLCPCB account and the stock moves between
  the companies are shared, and two databases would hold two copies of them.

### A project shared by both companies

* Good, because no move is ever needed.
* Bad, because the user requires every project to belong to one company.

### Dated ownership periods

* Good, because the owner on any past date is known.
* Bad, because every reader asks for a date, not a field.

### One owner field

* Good, because it is the smallest change.
* Bad, because a move loses who owned the project before it.

### A batch and an order always take the project's owner

* Good, because nothing is stored twice.
* Bad, because history does not follow one rule: the first Dongle V2 batches
  were made by 7Sigma, and an order belongs to the company that sold it.

## More Information

The rules are in [docs/reference/companies.md](../reference/companies.md).
Stock per company, the in-house transfers, the KSeF read-out, 7Sigma's sales
invoices and the company dashboard are later steps of the same plan. Each one
that is expensive to reverse gets its own record.
