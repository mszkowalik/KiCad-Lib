# Change tracking — who did what

Every change made through the API or the UI is traced to the signed-in person
who made it. The code is `api/app/services/tracking.py`, bound in
`api/app/authgate.py`. The reasoning, and the options that were rejected, are
in [decision 0050](../decisions/0050-every-change-names-the-person-who-made-it.md).

## One log, three kinds of row

Everything goes into `audit_log`. `request_id` groups the rows one request
wrote, and `user_id` names the person.

| `action` | One row per | `entity_type` / `entity_id` | Written by |
|---|---|---|---|
| `request` | POST, PUT, PATCH or DELETE under `/api/` | `http` / the path | `AuthGate`, after the response |
| `row.insert`, `row.update`, `row.delete` | ORM row changed during a request | the table / the primary key | the flush hooks |
| anything else | `audit()` call | what the call site says | the endpoint. The hook stamps the person |

Admin → Activity reads it through `GET /api/activity` and
`GET /api/activity/requests/{request_id}`. Both routes are admin-only.

## The Write log is a second record, on purpose

A write batch (`services/journal.py`, Production → Write log) holds what is
needed to UNDO a money movement: each row's full prior state and a hash
guard. The log cannot, because it redacts and hashes values. The two are
joined by `request_id`, which `journal.batch` stamps along with `user_id`
and the signed-in person as `actor`. The request detail lists the batch, and
an admin sees a link from the batch to the request. `write_batches` and
`write_batch_rows` are in `tracking.SKIP_TABLES`, so the journal is not
copied into the log a second time.

## Rules for new code

1. **A new reader of `audit_log` must decide about the tracker's rows.** One
   save writes a dozen `row.*` rows. Filter them out with
   `tracking.REQUEST_ACTION` and `tracking.ROW_ACTION_PREFIX`, as
   `get_audit_log` does, unless the reader is about tracking.
2. **Do not pass a name you got from the client.** To store a person in a
   who-column, call `routers/util.py::acting_name(claimed)`. It returns the
   signed-in person, and uses the claim only when nobody is signed in.
3. **Leave `audit(..., actor=...)` at its default** for work a person does. A
   robot label (`"jaravis"`, `"review"`) is correct for work a robot does, and
   `user_id` still names the person who started it.
4. **A thread you start from a route loses the context.** A bare
   `threading.Thread` starts with an empty context, so its writes have no
   person and no `row.*` rows. Start it as
   `threading.Thread(target=contextvars.copy_context().run, args=(fn, ...))`,
   as `services/jaravis.py::start_session_run` does.
5. **A Core statement is not captured.** `db.execute(update(...))`,
   `text("UPDATE ...")` and `query(...).update()` skip the ORM, so only the
   `request` row records them. Use ORM objects when the write matters to
   anybody.
6. **A new column that holds a secret must be redacted.** Names ending in
   `_enc` or `_hash`, or containing `password`, are redacted by name. Any
   other secret needs a line in `tracking._is_secret`, and a test in
   `api/tests/auth/test_tracking.py`.
7. **A new table whose rows ARE a credential** goes in
   `tracking.SKIP_TABLES`. `user_sessions` is there because its id is the
   browser cookie.

## What the hooks change for you

- An `actor` of `"user"` becomes the person's display name.
- A who-column (`author`, `created_by`, `signed_by`, and the others in
  `tracking.WHO_COLUMNS`) that is `"user"` on insert becomes the person's
  display name. On an update, it changes only when the update itself writes
  `"user"`. An old row keeps what it says.
- A value longer than 1000 characters is stored in a `row.*` row as
  `{"len", "sha256"}`. The versioned tables hold the full text.

With `AUTH_ENABLED=false` (dev) there is no person. The `request` and `row.*`
rows are still written, with `user_id` NULL, and `"user"` stays.
