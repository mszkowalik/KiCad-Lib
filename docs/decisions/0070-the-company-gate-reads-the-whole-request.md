---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (a code review of decision 0065 on 2026-10-04)
---

# Gate the query, the JSON body and the WebSocket as well as the path

## Context and Problem Statement

[0065](0065-a-record-of-another-company-does-not-exist-for-the-caller.md) gated
a record named in a route's PATH. A review on 2026-10-04 found six ways past
the gate or through it:

* `/api/runs/15371.0` reached the route as run 15371, while the gate could not
  read the id and skipped the parameter;
* every WebSocket route failed, because the gate asked for a `Request`;
* `run_id` under `/api/flasher/runs/` is a programming attempt, and the gate
  resolved it as a batch;
* `GET /api/flasher/mosquitto?project_id=` returned the broker passwords of
  any project, and with no project those of every project;
* a batch or a project named in a JSON body (`lines[].run_id`, the agent
  tools' arguments) was never checked, so a user of one company could charge
  the other company's batch;
* the legacy shared MCP token was nobody, and nobody saw every company;
* the agent tools that take a project NAME (`get_project`,
  `get_production_run`) answered for any company's project.

The write journal (`/api/ledger/batches`) was also listed as shared data,
though a batch can reverse writes to one company's books.

## Decision Drivers

* A record of another company does not exist for the caller (0065), however
  the request names it.
* A skipped parameter is an open door, so a value the gate cannot read is
  refused, never skipped.
* A new parameter cannot stay unclassified, in the path or anywhere else.

## Considered Options

* A check in each route that reads a body id.
* The one app-wide gate reads the query and the JSON body too.

## Decision Outcome

Chosen option: "the app-wide gate reads the whole request", for the reason
0065 chose one gate: about 25 body models and the agent tools would each need
a check to remember, and the first one forgotten is the hole.

1. **An id is parsed the way FastAPI parses it** (`"15371.0"` is 15371), and a
   value that is no id at all is refused with 404.
2. **The gate takes an `HTTPConnection`**, so it runs on a WebSocket as well
   and refuses one with close code 1008.
3. **Query parameters and body keys are resolved like path parameters**,
   three levels into a JSON body, each item of a list of ids (`device_ids`,
   `serials`, `codes`), and the fields of a form (`FIELD_RESOLVERS`). A body
   that is not a form is read as JSON whatever its Content-Type says, and the
   agent route takes only `application/json`. A JSON `true` is the id 1, as
   FastAPI reads it. A key that means something
   else on one route is resolved per route: `run_id` on
   `/api/flasher/checks/recompute` and under `/api/flasher/runs/` is a
   programming attempt, whose companies are its batch's, else its version's
   project's, else its device's. An in-house transfer names both companies,
   so its author must belong to both. Every `*_id` query parameter, body key
   and agent-tool argument is classified under a test, like the path.
4. **A legacy shared token sees no company's records**: the gate refuses
   them and the agent tools list none. A request with no signed-in user is
   otherwise only the dev posture with auth off, which sees everything.
5. **A write-journal batch belongs to the companies of the rows it touched**,
   read from the live row or from its `before` image. A batch that touched no
   company's row is everybody's. Reversing a batch needs every company it
   touched.
6. **The broker password export follows the gate's device rule**: a device
   is its batch's company's, else its project's companies'. A project moved to
   the other company keeps its old batches' devices with the old company.
   A JLC order's decision is the batch it links, so voiding, applying or
   clearing it needs that batch's company. The live simulator checks the
   snapshot named in its first message.
7. **The gate touches the database only when the request names company data
   and the caller is limited**: an admin, a token user with no company id in
   the request and a library read pay nothing. On a WebSocket it gives its
   database connection back as soon as it has decided.
8. **An agent tool that names a project or a batch by NAME asks the gate's
   question itself** (`agent_tools._visible`): `list_projects`, `get_project`,
   `get_project_bom`, `get_production_run` and `component_where_used` leave
   out what the caller's companies do not own.

### Consequences

* Good, because a body id, a query id and a WebSocket are gated with no code
  in the route, and a new key cannot stay unclassified.
* Good, because an agent working with a personal token is limited to its
  user's companies on every tool that takes an id.
* Bad, because the gate reads and parses each JSON body of a write a second
  time. A body of a few megabytes (a large agent upload) costs a few
  milliseconds more.
* Bad, because the gate cannot read a NAME. A new agent tool that takes a
  project or batch name must call `agent_tools._visible`, and no test finds
  one that does not.

### Confirmation

Tests in `api/tests/auth/test_company_access.py` show that every query and
body id is classified, that `15371.0`, ` 15371 ` and `+15371` resolve and an
unreadable id is refused, that a body batch and a query project are gated,
that a flasher run resolves as a programming attempt, that a legacy token sees
no company and an admin every one, that the gate refuses a WebSocket of the
other company and that FastAPI serves a WebSocket through such a gate, and
that a journal batch belongs to the companies it touched, and that a tool's
project and batch lookup follows the same rule.

## Pros and Cons of the Options

### A check in each route

* Good, because each route says what it checks.
* Bad, because about 25 places must remember it, and the agent tools too.

### The gate reads the whole request

* Good, because one place decides, and a test lists every key.
* Bad, because the body is parsed twice.

## More Information

Refines [0065](0065-a-record-of-another-company-does-not-exist-for-the-caller.md).
The rules are in `api/app/services/access.py` and in
[docs/reference/companies.md](../reference/companies.md).
