---
status: "accepted"
date: 2026-09-24
decision-makers: Mateusz Kowalik
---

# Every change names the person who made it

## Context and Problem Statement

On 2026-09-24 a PDF was attached to invoice document 864 on prod. The audit
row said `actor: "user"`. Nobody could tell which person had uploaded it.

This was the normal case, not an exception. The API has had a session or a
personal token on every request since the gate landed, but most write paths
never read it:

* `audit()` defaults `actor` to `"user"`, and 73 of its 147 call sites
  keep that default or pass `"user"`. Services such as `datasheet_store.py`
  and `importer.py` hard-code it.
* 11 who-columns (`author`, `created_by`, `signed_by` …) declare the
  default `"user"`.
* About 25 endpoints took the name from the CLIENT: a body field (`author`,
  `actor`, `created_by`, `approved_by`, `updated_by`) or a query parameter
  (`?actor=`). Anybody could type somebody else's name.
* Many writes have no audit row at all.

The user asked for full tracking of every change made through the API or the
UI, to the exact user.

## Decision Drivers

* A new endpoint must be tracked without its author remembering to do it.
* One question, "who did this", must have ONE place to look.
* A name sent by the client is a claim, not an identity.
* Secrets must never be copied into the record.
* Tracking must never refuse a write.

## Considered Options

* Fix each endpoint's `actor` by hand.
* Postgres triggers on every table, with the user in a session variable.
* A request context set by the gate, read by ORM hooks, writing into
  `audit_log`.
* The same, but with two new tables beside `audit_log`: `request_log` and
  `change_log`.
* Also store each request body.

## Decision Outcome

Chosen option: "a request context set by the gate, read by ORM hooks, writing
into `audit_log`". It is the only option that covers an endpoint nobody has
written yet, and it keeps one log.

1. **`AuthGate` binds a `ContextVar`** with the user, a request id and how
   the caller signed in (`session`, `token`, `legacy`, `none`), for every
   HTTP and WebSocket request.
2. **`audit_log` is the only log.** It gets `user_id` and `request_id`, and
   `request_id` groups every row one request wrote. Three kinds of row, told
   apart by `action`:
   * `request`: one for each POST, PUT, PATCH and DELETE under `/api/`.
     `entity_type` is `http`, `entity_id` is the path, and `details` holds
     method, path, query without `t=`, status, duration, client IP, user agent
     and how the caller signed in. It has no body.
   * `row.insert`, `row.update`, `row.delete`: see item 5.
   * Every other action: the event the endpoint wrote itself, as before.
3. **The endpoint's own audit rows are stamped** on insert. An actor of
   `"user"` becomes the person's name. A robot label (`jaravis`, `review`,
   `import`) stays, and `user_id` records who started the robot.
4. **Who-columns**: on insert, the placeholder `"user"` becomes the person's
   name. The same applies when an update WRITES `"user"`. An old row that
   already says `"user"` keeps it.
5. **A `row.*` row** is written for each ORM row inserted, updated or deleted
   during a request. `entity_type` is the table and `entity_id` the primary
   key. For an update, `details` holds `[old, new]` for each changed column.
   For an insert or a delete, it holds the loaded values.
   * Columns that hold a secret are stored as `<redacted>`: `*_enc`,
     `*_hash`, `*password*`, a secret `device_config_values.value` and a
     secret `app_settings.value`. The tables `user_sessions` (the id IS the
     cookie) and `login_attempts` are not copied.
   * A value longer than 1000 characters is stored as its length and SHA-256.
6. **Endpoints that took a name from the client now use `acting_name()`**,
   which returns the signed-in person. The claim is used only when nobody is
   signed in (dev, `AUTH_ENABLED=false`).
7. **The Jaravis chat thread runs in a copy of the request context**, so the
   agent's writes are attributed to the person who sent the message.
8. **Admin → Activity reads the log**, through `GET /api/activity` and
   `GET /api/activity/requests/{request_id}`. Both are admin-only, because the
   `row.*` rows show the work of every user at once. The list shows requests
   and events by default. Unfolding a row shows everything its request wrote.
9. **The Write log stays separate, and names the same person.** A write
   batch (`write_batches`, Production → Write log) exists to UNDO a money
   movement: it keeps each row's full prior state and a hash guard. The log
   cannot do that, because it redacts secrets and reduces long values to a
   hash. `journal.batch` now takes `actor`, `user_id` and `request_id` from
   the request context, and ignores the `?actor=` the caller passed when
   somebody is signed in. `request_id` links a batch to its log rows, and
   each view links to the other. The journal's own tables are not copied
   into the log.
10. **The human-scale readers leave the tracker's rows out.** The Changes feed
   already filters by action prefix. The agent's `get_audit_log` excludes
   `request` and `row.*` unless it is asked for them (`include_tracking`).

### Consequences

* Good, because a new endpoint is tracked with no extra code.
* Good, because one table answers "who did this". One write call shows who
  made it, what it answered, which events it wrote and which rows it changed.
* Good, because a spoofed `author` or `?actor=` is ignored when a person is
  signed in.
* Bad, because `audit_log` now grows with every write, and a large import
  writes one row per inserted row. There is no pruning. Revisit when the
  table passes a size somebody minds.
* Bad, because every reader of `audit_log` must decide whether it wants the
  tracker's rows. A new reader that forgets gets flooded with `row.*` rows.
* Bad, because these writes get NO `row.*` rows, and only their `request` row
  records them:
  * Core statements (`db.execute(update(...))`, `text("UPDATE ...")`,
    `query(...).update()`). A search found about 12 in `routers/` and
    `services/`. The search is not complete.
  * Rows written through a `secondary` association table.
  * Work in a thread a route starts itself, other than the Jaravis chat.
    Examples: the material backfill in `signoff.py` and the conformance run.
  * Background jobs with no request: the nightly datasheet fetch and the
    MQTT watcher. They have no person behind them.
* Bad, because the names in who-columns and `actor` are display names, and a
  display name can change. `user_id` is the stable key.
* Neutral, because rows written before 2026-09-24 still say `"user"`, and
  nothing can recover who wrote them. The same applies to write batches
  before that date, whose actor is whatever the caller typed (`user`,
  `claude`, `claude-local`, `reconciliation`).

### Confirmation

* `api/tests/auth/test_tracking.py` covers the audit stamp, the robot label,
  the who-column placeholder and its history rule, `acting_name`,
  insert/update/delete capture, redaction, digests, no capture outside a
  request, the `request` row, the gate's context in a sync route and its
  reset, and the Activity list and request detail.
* `api/tests/auth/test_role_gates.py` lists the two `/api/activity` routes.
* Checked on the local stack on 2026-09-24: a comment posted with
  `"author": "mallory"` was stored with the signed-in user's name. Its
  `request`, `row.insert` and `comment.add` rows all carried the same
  `user_id` and `request_id`. Admin → Activity showed the request and, when
  unfolded, the two rows it wrote.

## Pros and Cons of the Options

### Fix each endpoint's `actor` by hand

* Good, because each audit row could carry a precise, hand-written name.
* Bad, because 147 call sites must change, and the next endpoint
  forgets. That is how the platform got here.
* Bad, because a write with no audit row stays untracked.

### Postgres triggers on every table

* Good, because they also record raw SQL and bulk statements.
* Bad, because about 100 tables need a trigger each, and a new table needs
  one too.
* Bad, because every transaction must `SET LOCAL` the user first. A
  transaction that misses it records nobody, and that failure is silent.
* Bad, because redaction rules would live in PL/pgSQL, apart from the models
  that define the secrets.

### Fold the Write log into `audit_log` too

* Good, because it would leave one table for every write.
* Bad, because an undo needs the full prior value of every column. The log
  redacts secrets and hashes long values on purpose, so it cannot restore a
  row. Storing full values would put secrets in a table every admin reads.
* Bad, because a write batch is one business operation with a register check
  before and after, not one HTTP request.

### Two new tables beside `audit_log`

The first version built this. `request_log` held the calls and `change_log`
held the row values.

* Good, because the human-scale `audit_log` stays small, and no reader has to
  filter.
* Bad, because there are then three logs, and "who did this" has three
  answers to join. The user rejected it on 2026-09-24: "shouldnt we have only
  one log?"
* Bad, because `audit_log` already had every column needed: actor, action,
  entity type, entity id and a JSON body.

### Also store each request body

* Good, because a request could be replayed.
* Bad, because bodies carry passwords, tokens, git credentials and whole
  files. The record would need its own access control.

## More Information

* How it works, and what to do when you add a table or a thread:
  [docs/reference/change-tracking.md](../reference/change-tracking.md).
* The role model this follows: [0045](0045-configuration-is-an-administrators-surface.md).
