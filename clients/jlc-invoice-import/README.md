# JLCPCB component-invoice importer (prototype)

Turns JLCPCB component invoices into structured purchase lines. Destined for
`api/app/services/jlc_invoice.py` once wired to a router; kept standalone until
then. Model and rationale: `docs/production-costs/design.md`.

```bash
.venv/bin/python clients/jlc-invoice-import/parse_jlc.py <folder-with-pdfs>
```

## What the real invoices look like (13 samples, 2024-07 → 2026-04)

- **Image-only PDFs.** One JPEG per page (2400 px wide), **zero text layer** —
  `get_text()` returns nothing, so OCR is mandatory. A tall invoice is one
  image referenced by several PDF pages **by the same xref**, so images must be
  de-duplicated or every line and total doubles.
- **Columns**: `Mfr. Part # | Description | QTY | Unit Price | Ext. Price(USD)`.
  **There is no LCSC code** — matching to the library has to go through the
  manufacturer part number.
- **Totals block**: `Subtotal`, then optional charges (`Others` seen at $0.50),
  then `Grand Total`. Those charges are real money that is **not** in the item
  table — miss them and the invoice under-reports.
- **The date appears three times**: as `DD/MM/YYYY`, and embedded in both the
  invoice number and the batch number (`POB0`**`20250210`**`2244558`). Digits OCR
  far more reliably than a slashed date, so the embedded date wins and the
  printed one is used as a cross-check.
- `Batch No` is JLC's parts-order id (`POB0…`) — the natural idempotency key.

## How it stays trustworthy

Naive OCR reads this table **column-by-column** and destroys row alignment. So
instead: tesseract in TSV mode (word + coordinates), money cells clustered into
the two right-aligned columns, rows grouped by y, and the **quantity column
located by arithmetic voting** — the x-bucket whose integers equal
`round(ext / unit)` on their row. That is what stops `0805` in a description
from being read as a quantity.

Then three independent checks, so a misread digit shows up as arithmetic that
does not close rather than as silently wrong money:

1. per row: `qty × unit_price == ext_price`, with tolerance scaled from the
   4-decimal unit price (`0.00005 × qty`)
2. `Σ ext_price == Subtotal`
3. `Σ ext_price + Σ charges == Grand Total`

**Measured: 13/13 invoices reconcile, 0 needing review** (238 line items). The
only initial failure was a real `Others $0.50` charge the parser was ignoring,
not an OCR error.

## Deployment note

The api image has no `tesseract` — add `tesseract-ocr` to the apt install in
`api/Dockerfile` before wiring this up (the host has it at
`/opt/homebrew/bin/tesseract`, which is the default in `TESSERACT`).
