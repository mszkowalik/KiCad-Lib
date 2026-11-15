---
status: accepted
date: 2026-11-15
decision-makers: Mateusz Kowalik
---

# Let a remote agent upload a file with a one-use ticket that its own shell sends

## Context and Problem Statement

Two agent tools send a file from the user's computer: `upload_model3d` (a STEP
or WRL model) and `attach_invoice_file` (an invoice original). The stdio server
reads the file itself. The remote endpoint of decision
[0111](0111-a-remote-mcp-endpoint-signs-in-with-google.md) runs in henry-api
and cannot read the agent's disk, so it left both tools out. Production shows
both in use (36 model uploads and 1035 invoice attachments by `python-httpx`
up to 2026-11-13). The local server could not be removed while they existed
only there.

## Decision Drivers

* A file of several megabytes does not belong in a tool argument.
* The upload must meet the same route, gate, company scope and audit as any
  other write by the user.
* A credential that reaches the chat transcript must be worth little.

## Considered Options

* A: the tool returns a one-use upload ticket and the `curl` command that
  sends the file with it.
* B: the file goes in the tool call as base64.
* C: keep the two tools stdio-only.

## Decision Outcome

Chosen option: A, because the file goes straight from the agent's disk to the
existing route, and the ticket is narrow enough to be shown in a chat.

1. The remote `upload_model3d` takes `filename` and `rel_path`, and the remote
   `attach_invoice_file` takes `document_id`. Each returns the exact `curl`
   command, with the file path left for the agent to fill in.
2. **A ticket is a credential with four limits**: it starts with `7u_`, it is
   good for ONE request, to ONE method and path, for ten minutes, as the user
   who asked for it. It is a row in `oauth_tokens` (kind `upload`), stored as
   SHA-256, spent the moment it matches, and accepted only in the
   `Authorization` header (`auth.resolve_upload_ticket`, called by the gate).
3. The upload goes to the existing route (`/api/models3d/upload`,
   `/api/run-documents/{id}/attachment`). The route's own checks and the
   company gate apply. The request row records `auth_via: upload-ticket`.
4. An agent with no shell (Claude on a phone) cannot use either tool. The
   tool says so, and points to the web app.

### Consequences

* Good, because the local server is no longer needed for any tool.
* Good, because a leaked ticket uploads at most one file, to the place the
  user's agent asked for, within ten minutes.
* Bad, because the ticket appears in the chat transcript, which the agent's
  vendor stores. Its limits are what make that acceptable.
* Bad, because the upload needs a shell. The stdio tool did not.

### Confirmation

* `api/tests/auth/test_mcp_oauth.py` covers one use, the method and path
  scope, expiry, an inactive user, and that a ticket is not a general
  credential.
* On dev, a remote `upload_model3d` ticket uploaded a file (HTTP 200) and the
  same command sent again got 401.

## Pros and Cons of the Options

### B: base64 in the tool call

* Good, because it needs no shell.
* Bad, because a model of several megabytes becomes several megabytes of
  context, and an agent cannot reliably produce it.

### C: keep the tools stdio-only

* Good, because nothing changes.
* Bad, because the local server then stays on every computer that uploads.

## More Information

* The rules for both servers: [docs/reference/remote-mcp.md](../reference/remote-mcp.md).
