# KSeF

The platform READS both companies' invoices from KSeF. It never sends one.
The reasoning is in
[decision 0067](../decisions/0067-the-platform-reads-both-companies-from-ksef.md).
The code is `api/app/services/ksef/` and `api/app/routers/ksef.py`. The pages
are Admin → Companies (tokens, "Sync now") and Production → KSeF (the inbox).

## Rules

* **A token is a credential.** `ksef_credentials.token_enc` is encrypted with
  `services/crypto.py`; every token and sync route is admin-only and listed in
  `tests/auth/test_role_gates.py`; no response ever carries the token. Never put
  one in an environment variable, a knob, a fixture or a log.
* **Fetching writes only the inbox.** `sync.sync` writes `ksef_invoices`, the
  XML in MinIO, and the sales links. A purchase changes no money until
  `sync.import_purchase` runs, which a person or an agent starts.
* **The invoice in KSeF is the binding one.** A linked sales record takes
  KSeF's figures (`sync._apply_ksef`), and notes a difference from the draft.
* **The QR hash comes from the metadata** (`invoiceHash`, base64, turned into
  base64url by `sync.b64_to_b64url`), so a linked draft prints its QR code even
  before its XML is downloaded.
* **A rate limit is recorded, never slept through.** `client.RateLimited`
  carries the wait; `sync` stores `rate_limited_until` and refuses until then.
  At most `DOWNLOADS_PER_SYNC` XML files are downloaded per sync; the next sync
  continues.
* **The numbering counts KSeF's numbers** from the inbox
  (`invoicing/numbering._all_numbers`), so a number written directly in KSeF is
  never given out by the platform.

## Agent tools

`services/agent_tools.py` has the invoice group: `list_supplier_invoices`,
`get_supplier_invoice`, `create_supplier_invoice`, `assign_invoice_line`,
`list_ksef_inbox`, `import_ksef_invoice`, `list_sales_invoices`,
`create_sales_invoice_draft`. The writes call the route functions
(`_route`), so every website guard applies, and every tool limits itself to the
token user's companies (`_caller_companies`). The MCP server's local
`attach_invoice_file` files an original from the user's disk.
