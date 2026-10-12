---
status: "accepted"
date: 2026-10-12  # accepted 2026-10-12
decision-makers: Mateusz Kowalik
consulted: Claude
---

# An agent reaches every API route as its user, through two general MCP tools

## Context and Problem Statement

On 2026-10-12 the API had 549 operations, and the MCP server exposed 65
tools: 63 from the catalog (`GET /api/agent/tools`) and 2 local file
uploads. Whole areas had no tool at all: crafting a batch, process versions,
shipments and orders, stock, devices and the flasher. On 2026-10-08 an agent
recorded steps on 300 units, moved a batch to a new process version, and
unpacked and repacked 75 devices of a shipment. It could do that only because
it also had a shell and called the API with the user's token. An agent with
MCP alone could not.

The user asked on 2026-10-12 that an agent with MCP access reach every route,
or at least the routes that are hard to give a dedicated tool.

## Decision Drivers

* The capability policy in
  [mcp_server/CLAUDE.md](../../api/app/services/mcp_server/CLAUDE.md): an
  agent must never be blind to data the platform holds.
* An agent must not get more power than its user has in the browser, and the
  platform must not get a second permission model.
* The token stays out of the agent's view. The Account page's setup keeps it
  in a file only the MCP server reads.
* A dedicated tool, with typed arguments and a description that states the
  rules, is still the better path for work an agent does often.

## Considered Options

* Two general local tools in the MCP server: `api_routes` and `api_request`.
* A dedicated catalog tool for every route.
* A general tool in the catalog that calls the app inside the API process.
* No change: an agent with a shell calls the API with the token.
* A read-only general tool (GET only).

## Decision Outcome

Chosen option: "two general local tools in the MCP server", because it closes
the gap for every route at once, and the platform's existing gate decides
what each call may do.

1. **`api_routes`** reads the API's own OpenAPI document (`/openapi.json`,
   behind the auth gate) and keeps it for 10 minutes. With `filter`, it lists
   the matching routes, at most 150. With `path` and `method`, it returns the
   route's parameters, its request body schema with the references resolved,
   and its docstring.
2. **`api_request`** sends one request to a path under `/api/`, with the
   token the server already holds. A path outside `/api/`, or with `..`, is
   refused. A DELETE is refused unless `confirm` is true, and the description
   tells the agent to ask the user first. Other methods are not restricted:
   the routes' own `dry_run` defaults and guards apply. The answer is the
   HTTP status and the body, cut at `max_chars` (default 40,000 characters),
   or the body written to `save_to` for a file.
3. Both run in `server.py`, beside the two upload tools, and not in the
   catalog. The server holds the token and speaks HTTP. In the catalog, the
   API would have to call itself.
4. A workflow agents use often still gets a dedicated tool. The general tools
   are the fallback, not the main path. The first such set ships with this
   record: 13 production tools for batch crafting, process versions,
   shipments, devices and stock, which call the same route functions as the
   batch screen.

### Consequences

* Good, because an agent with MCP alone can now do any work its user can do
  in the browser, and nothing more: role gates and the company scope are
  applied by the server, as for the browser.
* Good, because no new route, permission or token is added.
* Bad, because an agent can now make writes that have no dry run (a cost line
  edit, packing a shipment). The audit log names the token's user for each of
  them, as it does for the browser.
* Bad, because an agent reads raw API shapes. A large answer costs context,
  which is why it is cut and why `api_routes` exists.
* Neutral, because an agent that runs with an administrator's token can reach
  the administrator's routes. Give an agent a non-admin account unless it
  needs them.
* Neutral, because a user who installed the server from the Account page runs
  a downloaded copy, and gets the two tools only after downloading it again.
  This repository has no project entry for it, so a developer installs it
  the same way.

### Confirmation

On 2026-10-12, against the local API and against production (read-only):
`list_tools` returned the catalog plus the four local tools; `api_routes`
listed and described `POST /api/runs/{run_id}/craft/step` with its body;
`api_request` answered a GET, a dry-run POST and a 404; a DELETE without
`confirm`, a path outside `/api/` and a path with `..` were refused; a long
answer was cut with a note; `save_to` wrote a file. The production tools are
covered by `api/tests/costs/test_production_tools.py`, and each was called
through the MCP server against the local API.

## Pros and Cons of the Options

### A dedicated catalog tool for every route

* Good, because each tool has typed arguments and its own description.
* Bad, because 549 tools make the catalog too large for an agent to choose
  from well, and every new route needs a new tool before an agent can use it.

### A general tool in the catalog that calls the app in-process

* Good, because it would work for any client of `/api/agent/tools`.
* Bad, because the API would call itself, and the gate, the identity binding
  and the company scope would have to be reproduced for that path.

### No change

* Good, because nothing is built.
* Bad, because an agent with MCP alone stays limited to a tenth of the API,
  and an agent with a shell needs the token in its own view.

### A read-only general tool

* Good, because it cannot change anything.
* Bad, because the gap that started this was writes: batch steps, process
  versions and shipments.

## More Information

[0062](0062-the-platform-runs-no-agent-of-its-own.md) made MCP the only way
an agent reaches the platform. Implementation:
`api/app/services/mcp_server/server.py` (`API_ROUTES`, `API_REQUEST`).
Revisit if the audit log must tell an agent's write from a person's: today
both are written under the token's user.
