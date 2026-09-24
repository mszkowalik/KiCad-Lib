---
status: "accepted"
date: 2026-09-24
decision-makers: Mateusz Kowalik
---

# No endpoint accepts a name from the client

## Context and Problem Statement

[0050](0050-every-change-names-the-person-who-made-it.md) item 6 made about 25
endpoints store the signed-in person instead of a name the client sent. It
kept the parameters: `?actor=` on about 15 routes, and the body or form fields
`author`, `actor`, `created_by`, `approved_by`, `updated_by` and
`uploaded_by`. Inside a request they were silently overridden. With nobody
signed in (dev) they were still used.

The user asked the same day: "why did you keep the ?actor? is it necessary?"
It was not.

## Decision Drivers

* A parameter that looks as if it sets the name, and is silently overridden,
  misleads whoever reads the API or writes a client.
* Removing a parameter must not break a client that still sends it.

## Considered Options

* Keep the parameters, ignored when somebody is signed in (0050 item 6).
* Remove them from every route.

## Decision Outcome

Chosen option: "remove them from every route".

1. No route takes a who-name as a query parameter, a form field or a field of
   its JSON body. `routers/util.py::acting_name()` takes no argument: it
   returns the signed-in person behind the session cookie or the personal
   token, or `"user"` when nobody is signed in.
2. `api/tests/auth/test_tracking.py::test_no_route_accepts_a_name_from_the_client`
   walks every mounted route and fails if one of those names appears. The one
   exception is `GET /api/changes`, where `actor` is a filter over the log.
3. The internal `actor=` argument of `audit()` and `journal.batch()` stays. The
   client never sets it. Code that runs with no request needs it for a robot
   label (`"system"`, a script's name); inside a request the signed-in person
   overrides it.

This supersedes item 6 of 0050 and nothing else in it.

### Consequences

* Good, because there is no parameter left to spoof or to misread.
* Good, because no client breaks. FastAPI drops an unknown query parameter,
  and pydantic drops an unknown body field. None of the affected models uses
  `extra="forbid"`.
* Bad, because a dev box with `AUTH_ENABLED=false` now records `"user"` for
  everything. That is the truth: nobody signed in.

### Confirmation

* The route test above, which also asserts it reached more than 200 routes
  and read fields inside body models, so it cannot pass vacuously.
* The web client no longer sends `actor`, `created_by` or `uploaded_by`
  (`web/src/api.ts`), and `tsc --noEmit` passes.
