---
status: "accepted"
date: 2026-11-07
decision-makers: Mateusz Kowalik
consulted: Claude
---

# A tagged route is an agent tool, called through the whole app

## Context and Problem Statement

The API has about 560 routes, and an agent has 86 tools. Decision
[0088](0088-an-agent-reaches-every-api-route-as-its-user.md) closed the gap with
`api_routes` and `api_request`. Each use takes two calls. The agent's tool list has
no typed arguments for that route, and the agent reads the raw API shape. Since the
server was renamed on 2026-11-01, the 17 `api_request` calls found in the session
logs named 9 routes, all reads: the JLC ledger, settings, parts stock, adjustments.

Decision 0088 says a route agents use often deserves a dedicated tool. A dedicated
tool is a Python function that calls the route function or the service. So the logic
of the answer and the access checks exist twice: `_caller_owns` in a tool is the
company gate written again, and a route that reads the actor from its `Request`
cannot be called from a tool at all.

The user asked for a way to fix this without rewriting much code and without
duplicates.

## Decision Drivers

* One implementation of each function, the route.
* No second permission model.
* A catalog small enough for an agent to choose from. The 82 written tools already
  take 76 kB.
* An installed MCP server is a downloaded copy, which changes only when a person runs
  the setup prompt again.

## Considered Options

* A tag on the route, and a call through the whole app in-process.
* A tag on the route, and tools generated inside `server.py` from the OpenAPI document.
* A hand-written tool for each route agents use.
* A generated tool for every route.

## Decision Outcome

Chosen option: "a tag on the route, and a call through the whole app in-process",
because one word on a route gives a typed tool, with no tool code, and installed
copies of the server get it with no new download.

1. `openapi_extra={"x-agent-tool": "<name>"}` on a route makes it a tool.
   `services/agent_routes.py` reads the name, the docstring and the arguments (path,
   query and JSON body) from the OpenAPI document.
2. `GET /api/agent/tools` lists these beside `agent_tools.TOOLS`, and
   `POST /api/agent/tools/{name}` runs them. An installed server needs no change.
3. The call goes through `httpx.ASGITransport(app=request.app)`, with the caller's
   `Authorization`, `Cookie` and `X-*` headers. The real gate runs on the real path, so
   the role, the company scope, the audit row and the `dry_run` default are the
   browser's. Decision 0088 rejected an in-process call because the gate would have to
   be reproduced for that path. A call through the whole app reproduces nothing.
4. A refusal comes back as JSON with `error` and `status`. An answer is cut at
   `max_chars`, 40,000 characters by default. A tagged DELETE needs `confirm`.
5. Only the routes agents use get a tag, 26 at first. `api_routes` and `api_request`
   stay as the fallback, so a new route is reachable at once.
6. A tool with a shaped answer stays a written tool. A thin written tool can become a
   tag later, and its Python then goes away. That is a separate change for each tool.

### Consequences

* Good, because a tool cannot drift from its route: it is the route.
* Good, because an agent gets typed arguments and one call, and the MCP client refuses
  a wrong argument before it reaches the platform.
* Good, because a route that reads its `Request` can be a tool.
* Bad, because a tagged route's answer is its raw shape. A large one needs a query
  argument on the route, or a written tool.
* Bad, because a write made through a route tool leaves two `request` rows: the tool
  call and the route. Both name the same person and the client `mcp`.
* Neutral, because the docstring of a tagged route is now also instructions for an
  agent. It must say what the route does, and a test fails on a tag with no docstring.

### Confirmation

`api/tests/auth/test_agent_route_tools.py` covers the catalog, the arguments, the role
gate on the inner call (a non-admin gets 403 from `get_settings`), the client header on
the inner request, and the cut. On 2026-11-07 the MCP server, unchanged, was run over
stdio against the local API: `tools/list` returned 112 tools with typed schemas, and
`list_exchange_rates`, `get_parts_stock`, `get_part_ledger` and `get_order` answered,
the last with a 404 as JSON.

## Pros and Cons of the Options

### Tools generated inside `server.py`

* Good, because the API does not call itself.
* Bad, because every installed copy must be downloaded again, and it fetches a 500 kB
  document when it connects.

### A hand-written tool for each route agents use

* Good, because the answer can be shaped.
* Bad, because the logic and the checks exist twice, which is the problem.

### A generated tool for every route

* Good, because no route is left out.
* Bad, because 560 tools take far more context than the 82 do, and an agent chooses
  badly from a list that long. Decision 0088 rejected this for the same reason.

## More Information

Decision 0088 stays in force for `api_routes` and `api_request`. This record replaces
its reason against an in-process call, and its advice that a route used often needs a
written tool.
