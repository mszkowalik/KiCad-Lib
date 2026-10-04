---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude
---

# The platform runs no agent of its own; agents reach it over MCP

## Context and Problem Statement

The platform had two ways for an agent to use its tools: an in-app chat
(Jaravis) that ran the Anthropic tool runner on the server, and the MCP
server that Claude Code and other agents use. Both used the same tool list.
The chat cost API tokens, held its own session tables and background
threads, and its web page had already gone. Every agent the user runs now
works through MCP.

The user decided on 2026-10-04: remove the chat; use only MCP for agents.

## Decision Drivers

* One way for an agent to reach the platform.
* No server-side model calls, API keys or background agent threads to keep.
* The tools themselves stay: they are the agents' only access.

## Considered Options

* Remove the chat and keep the tools for MCP.
* Keep the chat beside MCP (as before).

## Decision Outcome

Chosen option: "remove the chat and keep the tools for MCP".

1. The chat routes (`/api/jaravis/*`), its session worker and its model loop
   are removed. The tool module is renamed `services/agent_tools.py`; its
   `TOOLS` list is unchanged, and `routers/agent.py` still serves it to the
   MCP server.
2. The settings that only the chat used (`anthropic_api_key`,
   `jaravis_model`) are removed. The `anthropic` package stays, only for the
   `beta_tool` decorator that derives each tool's JSON schema.
3. The tables `jaravis_sessions` and `jaravis_messages` stay in the database
   with their history. No code reads or writes them.

### Consequences

* Good, because there is one path for agents and no API-key cost on the
  server.
* Good, because the transcripts every user could read are no longer served.
* Bad, because there is no way to talk to an agent from the web page; an
  agent runs on the user's own machine.
* Neutral, because the old chat tables remain until someone decides to drop
  them.

### Confirmation

The test suite passes with the chat routes gone, `GET /api/agent/tools` still
lists the 55 tools, and the MCP server keeps working against it.

## More Information

Supersedes the "in-app Jaravis" half of the agent surface described in
`mcp/CLAUDE.md` before this change.
