---
status: "accepted"
date: 2026-10-12  # accepted 2026-10-12
decision-makers: Mateusz Kowalik
consulted: Claude
---

# Record every row change in the database, and let any request be undone

## Context and Problem Statement

The user decided on 2026-10-12 that an agent may remove data, on one
condition: every removal must be reversible, and the same must hold for every
misclick a person makes.

Two records existed, and neither could do this. `audit_log` gets a `row.*` row
for each ORM change, but it redacts and hashes values, so it cannot put
anything back (decision [0050](0050-every-change-names-the-person-who-made-it.md)).
The Write log (`services/journal.py`) can undo, but only for about 15 money
tables and only for the endpoints that open a batch. Both work in the ORM, so
neither sees a cascade Postgres runs itself (13 foreign keys delete with their
parent), a bulk `UPDATE` or `DELETE`, raw SQL or a script.

## Decision Drivers

* Every change must be recoverable, whatever code path made it.
* An undo must not silently overwrite a later change, and must keep the stock
  and closed-batch rules the Write log keeps.
* A credential must never come back.
* The record must not copy machine state that is rewritten all day: one table
  had 95.8 million updates, another 2.8 million log lines (2026-10-12).

## Considered Options

* A Postgres trigger on every table writes `row_changes`, and an undo engine
  puts back one request.
* A "deleted" flag on every table.
* ORM listeners on every table, the Write log's mechanism made general.
* Database backups only.

## Decision Outcome

Chosen option: "a trigger on every table, and an undo per request", because
the database sees every change, and the existing Write log rules can be reused
for the undo.

1. **Capture.** `row_change_capture` runs after every insert, update and
   delete on every table except those in `row_changes.SKIP`: the record and
   the logs, machine state (`device_presence`, `programming_logs`,
   `component_price_points`, `fetch_hosts`, `conformance`) and the
   credential tables (`user_sessions`, `login_attempts`, `jlc_web_sessions`,
   `api_tokens`). A delete keeps the whole old row. An update keeps the old and
   the new values of the columns it changed. An insert keeps the new row. A
   long value in a NEW image is kept as a hash, because it is only compared.
   Secret columns, by the names `tracking.py` already redacts, are never stored.
   The startup installs the trigger on every table, so a new table gets it
   without a change here.
2. **Grouping.** Each ORM transaction is tagged with the request's id, the
   person and the client (`browser`, `token`, `mcp`, `job`). The MCP server
   says it is MCP in an `X-Kicad-Client` header. Work that no request started
   is grouped by its transaction.
3. **Undo.** An undo puts back one request as one new request. It writes the
   prior state of every row the request touched: a deleted row with its id,
   the old values of an updated row, and the removal of an inserted row. It
   writes in an order the foreign keys accept. It refuses when:
   * a row no longer reads as the request left it, and it names the later
     request to undo first;
   * a row would need a credential that was never stored;
   * the stock would go below zero (`journal.stock_blockers`);
   * it touches a closed batch.

   An undo is itself recorded, so a redo is the undo of the undo.
4. **Who.** A person sees and undoes their own requests. An administrator
   sees and undoes anybody's. There is no UI. The API is under `/api/undo/`,
   and agents have `list_changes`, `get_change`, `undo_change` and
   `row_history`.
5. **Files.** Deleting a run, an attachment, a production file set or a
   firmware file no longer deletes its file from storage, because an undo can
   put the row back. Renders, which are rebuilt from git, are still deleted.
6. **Retention.** Every change is kept. No sweep exists yet.

### Consequences

* Good, because every change through any path can be put back, an agent's
  included, and an agent's changes can be listed apart by their client.
* Good, because no table needs a flag, and no query needs a filter.
* Bad, because every write now also writes a `row_changes` row, and the table
  grows without limit until a retention rule is decided.
* Bad, because files of deleted rows stay in storage until a sweep is written.
* Neutral, because `audit_log`'s `row.*` rows and the Write log stay as they
  are. Folding them into this record is later work.
* Neutral, because an undo cannot recall an effect outside the platform:
  firmware already flashed, a label printed, a library a user already synced.

### Confirmation

`api/tests/auth/test_row_changes.py` checks that every table but the listed
ones carries the trigger. It also checks the undo of a delete, an update with a
later change, an insert and its redo, a database cascade, a refused account, the
ownership rule and the stock refusal. Against the local API, an agent deleted a
comment over MCP, found it with `list_changes` (client `mcp`) and put it back
with `undo_change`.

## Pros and Cons of the Options

### A "deleted" flag on every table

* Good, because nothing is ever removed.
* Bad, because every query on 122 tables must filter the flag, and one missed
  filter silently counts deleted money. The Write log rejected draft rows for
  the same reason (`journal.py` docstring).
* Bad, because it covers deletes only, not a misclicked update.

### ORM listeners on every table

* Good, because the Write log already works this way.
* Bad, because it misses the 13 database cascades, bulk statements, raw SQL
  and scripts.

### Database backups only

* Good, because nothing is built.
* Bad, because a restore brings back the whole database, not one misclick.

## More Information

Extends [0050](0050-every-change-names-the-person-who-made-it.md) and the Write
log of [0074](0074-a-units-history-is-correctable-and-names-its-bench-runs.md).
Implementation: `api/app/services/row_changes.py`, `api/app/routers/undo.py`.
Revisit when the table size needs a retention rule, and when the Write log and
the `row.*` rows are folded into this record.
