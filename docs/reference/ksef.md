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
  KSeF states a correction's DIFFERENCE. A linked correction that keeps its
  state before takes "before + difference" as its totals after, so the
  difference is counted once.
* **An invoice is in the inbox once per company that sees it.** `ksef_number`
  is unique per company (`uq_ksef_invoices_company_number`). An invoice from
  7Sigma to 9SIGMA is 7Sigma's sales row and 9SIGMA's purchase row.
* **A sync reads back `sync.LOOKBACK_DAYS` (60) days** before the newest issue
  date it holds. The query is by issue date, and an offline or emergency-mode
  invoice reaches KSeF after its date. The upsert is idempotent. A deeper
  re-read takes `since`.
* **A KSeF error keeps the sync's progress.** The client turns a network
  failure into a `KsefError`, and the route commits what was fetched and
  `last_error` before it answers 502.
* **The import never doubles a purchase.** `sync.import_purchase` links the row to a
  document that holds its KSeF number, or the same seller NIP and number, and
  keeps the link although it answers 409. A document typed by hand has no
  seller NIP, so `sync.possible_duplicates` also looks for a document with no
  seller tax id, of the same company or of none, whose number is the same
  (case, spaces and leading zeros ignored), and which has the same date or a
  word of the seller's name. Then the import answers 409 with the candidates
  and writes nothing. `document_id` links the purchase to one, and `force`
  imports it anyway.
* **An import keeps the invoice's tax data** (decision 0084,
  `sync.apply_fiscal`): the printed invoice as `body`, the sale and due
  dates, `received_date` (the Polish day of KSeF's `acquisitionDate`, art.
  106na ust. 3 of the VAT act) and, for another currency, the VAT in PLN
  (`P_14_xW`). A link to a hand-typed document writes the same, and fills
  `tax_amount` when it is empty; it never touches the net or the positions.
  Documents imported before the change are filled by
  `POST /api/ksef/fill-documents` (admin, dry run by default).
* **The skip takes only a purchase.** The numbering counts the numbers KSeF holds,
  so a skipped sales row would give its number out again. A sales row has no
  action at all: the KSeF page says instead whether it waits for its XML or
  another invoice holds its number.
* **A deleted document frees its purchase.** Deleting a supplier document
  sets its inbox row back to `new`, and an import heals a row that still
  points at a missing document.
* **The parser keeps what the invoice states.** A unit price keeps up to 8
  decimals. A position priced gross (P_9B, P_11A) has the net of its gross
  less its VAT.
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
