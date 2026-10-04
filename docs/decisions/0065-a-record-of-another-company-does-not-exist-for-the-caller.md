---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04 to the two-company plan)
---

# Answer 404 when a user opens a record of a company they do not belong to

## Context and Problem Statement

[0063](0063-two-companies-own-projects-over-time.md) let a user see the
companies they belong to, and an admin every company. It filtered the project,
batch and order lists by the header switcher, and it recorded as a bad
consequence that any user could still open any record by its address. The user
requires that projects are not shared: each belongs to a company, the admin
sees all of them, and a project's processes follow the project's visibility
(user, 2026-10-04).

The API has 494 routes. Their path parameters name 66 kinds of record, and the
same parameter name can mean two records (`device_id` is a device on one route
and a planned serial on another). The agent tool `get_audit_log` read the
activity log, which `/api/activity` keeps for admins only.

## Decision Drivers

* A new route cannot forget the check.
* A record of another company does not exist for the caller: the answer gives
  away nothing, not even that the id is taken.
* A company's history stays readable to that company after a project moves.
* An admin sees everything, and the dev posture (auth off) keeps working.

## Considered Options

* A check in each route, through the helper that loads its record.
* One app-wide dependency that reads the matched route's path parameters.
* A filter on every database query (SQLAlchemy `do_orm_execute` with loader
  criteria).

## Decision Outcome

Chosen option: "one app-wide dependency". A per-route check is about 200
places to remember, and it is how `/api/settings` once sat ungated beside a
gated `/api/users` ([0045](0045-configuration-is-an-administrators-surface.md)).
A filter on every query hides rows from the aggregates as well, so the pool
and the register would report wrong figures with no error, and a missed
identity lookup would create a duplicate. Those were the two risks the plan
named for it.

1. **`access.require_company_access` runs on every route**, registered on the
   app. It reads the matched route's path, resolves each company parameter to
   the companies the record belongs to, and answers 404 unless the caller
   belongs to one of them for EVERY such parameter. An admin passes, and so
   does a request with no signed-in user.
2. **A record's companies**: a project's are every company that ever owned
   it, so a company keeps its past batches readable after a move. A batch's,
   an order's and a supplier document's are their own (a transfer has two).
   A document that names no company yet is everybody's, so the money stays
   visible. A record under a project, batch or order takes its parent's.
3. **Every path parameter is classified**, keyed by its prefix and name:
   company data with a resolver, or data both companies share on purpose (the
   library, users, suppliers, customers, the JLC account, stackups, the file
   pool). A test fails when a route adds a parameter in neither table.
4. **The lists and aggregates follow the header scope**: projects, batches,
   orders, transfers, shipments, devices and the invoice register show the
   selected company's rows, and rows no company is named on yet. The stock
   pages follow it once each company keeps its own stock
   ([0064](0064-each-company-draws-from-its-own-stock.md)).
5. **`get_audit_log` is admin-only**, like `/api/activity`.

### Consequences

* Good, because a new route with a company record is gated without anybody
  writing a check, and a new parameter cannot stay unclassified.
* Good, because the aggregates are never filtered by accident: each one
  filters on purpose, by the scope it was given.
* Bad, because every request with a company parameter makes one or two extra
  queries to resolve it.
* Bad, because an aggregate that does not take the scope yet (the production
  overview's demand and finished-stock cards, the JLC pages, the write log)
  still shows both companies to a user of one. Today every user belongs to
  both companies, so nothing is shown that was hidden before.
* Neutral, because the agent tools open their own sessions and read the
  library and the projects as their token's user could before this record:
  the gate covers the HTTP routes, not the tools' internal reads.

### Confirmation

Tests show that every path parameter of every mounted route is classified,
that the gate is an app dependency and that FastAPI runs an app dependency on
an included route, that a user of one company cannot open the other company's
project, batch or document, that an admin opens everything, that a project's
former company still opens it, and that a missing id is left to the route's
own 404. On the local copy a user of 9Sigma only received 200 for the three
9Sigma projects and 404 for the 7Sigma one, and the project list showed the
three.

## Pros and Cons of the Options

### A check in each route

* Good, because each route says what it guards.
* Bad, because about 200 routes must each remember it.

### One app-wide dependency

* Good, because a route cannot forget it, and the classification test catches
  a new parameter.
* Bad, because the path parameter names must be classified by prefix, since
  one name can mean two records.

### A filter on every query

* Good, because even internal reads are filtered.
* Bad, because aggregates shrink silently and identity lookups miss, which
  gives wrong figures and duplicates with no error.

## More Information

The rules are in [docs/reference/companies.md](../reference/companies.md),
and the gate in `api/app/services/access.py`.
