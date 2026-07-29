---
name: kicad-production-run-from-invoices
description: "How to recreate what a production batch really cost from supplier invoices: the cost-pool model, shared vs run documents, splitting one invoice position across runs and into a supplier's own sub-fees, NBP FX at the invoice date, OCR import of JLC component invoices, MPN->component resolution, BOM draws, attrition, and the invoice register that proves no money is unassigned. Use when creating or backfilling a production run, or entering or splitting any supplier invoice."
---
<!-- platform-skill: production-run-from-invoices v5 — source of truth is the platform; check with list_skills, refresh with get_skill -->

# Creating a production run from supplier invoices

Procedure for recreating what a production batch really cost, from the invoices
that arrive after it. Everything below was derived from doing it for
CE_Dongle_V2 batch 1 (350 pcs, 2024-09-30) with real JLCPCB / LIFTECH documents;
the pitfalls are all mistakes that actually happened.

Design background: `docs/production-costs/design.md`. Code:
`api/app/services/run_actuals.py`, `api/app/routers/run_costs.py`,
`api/app/services/nbp.py`, importer in `clients/jlc-invoice-import/`.

## The model in one paragraph

**Purchases go into a company-wide cost pool; a run pays for what it drew from
the pool.** Component invoices are stockpile replenishment, so a parts purchase
is NEVER booked onto a batch. A `run_cost_lines` row with `kind="part"` and no
`run_id` IS the pool. Every other kind (`fab`, `assembly`, `tooling`, `freight`,
`duty`, `tax`, `rework`, `packaging`, `service`, `other`) is a direct cost of its
run. Components reach a run through `component_consumptions`, valued at the
pool's moving weighted average and snapshotted at that moment. Attrition is
expected: write it off with `component_stock_adjustments`, optionally charged to
a run. Quantities exist to split money — they are NOT expected to match JLCPCB's
stock. Everything is computed on read from append-only rows.

## Order of operations (do not reorder — the pool replays by event date)

1. **Project + snapshot.** The run needs `snapshot_id` + `board` for a BOM draw.
   Check with `GET /api/projects/{id}/snapshots` — the project payload does NOT
   contain a `snapshots` key, so an empty `p["snapshots"]` proves nothing.
2. **Import component invoices FIRST, dated before the run.** The pool replays in
   event-date order, so a run cannot draw from an invoice dated after it: the
   average would be 0 and the components would cost nothing.
3. **Resolve parts to library components** (`POST /api/cost-lines/resolve-parts`).
4. **Create the run**, then add its direct-cost documents (assembly, freight…).
5. **Draw the BOM** (`POST /api/runs/{id}/consumption/from-bom`).
6. **Record attrition** if boards were scrapped.
7. **Verify** with the checklist at the bottom.

## 1. Create the run

```
POST /api/projects/{project_id}/runs
{ "label": "Batch 1 — 350 pcs", "qty": 350, "run_date": "2024-09-30",
  "snapshot_id": 6, "board": "CE_Dongle_V2", "variant": "", "status": "done",
  "notes": "what this batch was, and which invoice proves it" }
```

- `run_date` drives **all** historical pricing (`run_pricing_date`) — set it to
  the batch's real date, never today.
- `qty` = planned units. Set **`qty_good`** when known: actual per-device cost
  divides by good units, not planned ones.
- A run with `snapshot_id: null` is legal (costs only, no BOM) — fine for a batch
  whose design was never ingested.

## 2. Enter the documents

Two kinds, and the distinction matters:

| | shared (pool) | run document |
|---|---|---|
| endpoint | `POST /api/documents` | `POST /api/projects/{id}/documents` |
| `project_id` | NULL | the project |
| `run_id` | NULL | the run |
| use for | component invoices, stock bought for later | assembly, fab, tooling, freight, labour |

```
POST /api/documents            # shared: components -> pool
{ "supplier": "JLCPCB", "doc_number": "<invoice no>",
  "external_id": "<JLC Batch No, POB0…>",   # idempotency key
  "doc_date": "2024-07-24", "currency": "USD", "total_amount": 6927.33,
  "lines": [ { "kind": "part", "mpn": "CH340B", "qty": 1051,
               "unit_price": 0.3356041 } ] }
```

Rules:

- **`total_amount` = the printed total.** The response's `reconciled: false` is
  the tripwire that the lines do not add up to the document.
- **Unit price from the printed EXTENDED price**, i.e. `ext / qty`, not the
  invoice's rounded 4-decimal unit price. Summing rounded unit prices drifts by
  cents and breaks reconciliation. The importer emits `unit_price_exact` for this.
- **Non-USD needs no manual rate.** Creating a non-USD document resolves NBP
  table A at `doc_date` automatically, pins `fx_rate_usd`, and appends the rate to
  `exchange_rate_history` — which also fixes the *planned* side of historical runs.
  NBP publishes nothing on weekends/holidays: the lookup walks back and reports
  the date actually used. Check a rate first with
  `GET /api/fx/nbp?currency=PLN&date=2024-09-30`.
- **`basis`**: `per_run` for a batch total (`qty: 1, unit_price: 246.34`),
  `per_device` for a rate per board (`qty: 1, unit_price: 5.0` → charged
  ×`qty_good or plan_qty or qty`). Prefer stating the invoice literally
  (`qty: 350, unit_price: 5.0, basis: per_run`) when the invoice does.
- **One invoice covering two products** → split the POSITION, do not retype the
  invoice (see section 2b). Piece-count split is the default:
  `468.67 × 350/550 = 298.24` for the Dongle, `170.43` left for the Aqua. The
  unallocated part is reported as a `residual` — it is no longer something a
  `notes` string has to remember.
- **A split invoice keeps `document.run_id` NULL** and allocates per line. A
  document assigned to run A whose line points at run B would otherwise be
  charged to both.
- **A `part` line WITH a `run_id`** is charged directly to that run and stays out
  of the pool (that is how JLC-supplied parts on an assembly invoice are booked).

## 2b. Split a position instead of retyping the invoice

Enter the document exactly as printed, then divide the positions. The **Invoices**
view (`/invoices` in the web UI) is the place for this; the API is
`POST /api/run-cost-lines/{line_id}/split`.

```
POST /api/run-cost-lines/512/split
{ "children": [
    { "label": "Dongle share", "amount": 298.24, "run_id": 5 },
    { "label": "Aqua share",   "amount": 170.43, "project_id": 3 } ] }
```

Two uses, one mechanism:

1. **Shares across runs / projects.** Each child names a `run_id` or a
   `project_id`. `project_id` without a run is for money that belongs to a product
   whose batch does not exist yet — that is what stops a remainder from vanishing.
2. **Sub-positions.** JLC prints one `SMT Assembly $101.04`; stencil, manual
   assembly, hand-soldering and the surcharges only appear on their website. Split
   the printed figure into them. Children may be split again (depth 4).

Rules the API enforces:

- **A line with live children is a HEADER worth zero** — the children carry the
  money. Enforced once, in `run_actuals.header_ids`; every money path filters on
  it. Never "fix" a double count by editing a header's amount.
- **Children may not exceed the parent** (409). Under-allocation is legal and
  surfaces as `residual`; over-allocation is always a mistake.
- **The parent keeps the printed figure.** Reconciliation compares the printed
  total against TOP-LEVEL lines only, so splitting can never make a document read
  unreconciled.
- **Children inherit the parent's currency**, so the residual is arithmetic on one
  unit.
- **Percentages are a UI calculator, never storage.** The browser converts a
  percentage to an absolute amount before sending it; only absolutes are stored, so
  nothing is re-derived against a base that has since changed. Use "Balance last
  row" so rounding lands in one place instead of leaking a cent.
- **Splitting a `part` line takes `allow_parts: true`** and is almost always
  wrong: parts feed the pool, which already splits them by consumption. Only use it
  for parts bought for one specific batch.
- **Voiding a line voids its subtree** — orphaned shares would charge runs for a
  position that no longer exists.

Link a position to the planned cost it is the actual for with
`plan_kind: "cost"`, `plan_key: <cost item id>`, `plan_ref: <label>` (the
Invoices view's "Planned as" column does this, and can create the cost item from
the line). `plan_ref` is the anchor that survives a cost-list revision, since
cost items are copy-on-write per commit.

## 3. Import a JLC component invoice from its PDF

The PDFs are image-only, so this is OCR:

```bash
.venv/bin/python clients/jlc-invoice-import/parse_jlc.py <folder>   # verify first
```

**One invoice can be filed twice under different filenames.** `2025-10-28-DIGIKEY.pdf`
and `2025-11-28-DIGIKEY-DK_INVOICE_118535162.pdf` are the SAME purchase — same invoice
number, sales-order number, web order id, tracking number and document date — with
different bytes, because it was downloaded twice. The MRP counted both and
double-booked 1050 antennas. Identity is the invoice number plus the supplier's own
order/tracking ids, never the filename date. The platform's duplicate guard catches
this on `doc_number`; the MRP has no such guard, so treat its quantities as suspect
wherever two files could be the same document.

**Distributors punctuate MPNs differently.** Mouser prints Molex `146153-0050`,
DigiKey and the MRP print `1461530050`. The cost pool normalises MPN keys to
alphanumerics (`run_actuals._key` via `_strip`) so both spellings are ONE pool entry
with one moving average; without that a part splits in two and neither half matches a
BOM draw.

Every invoice must report `RECONCILED`. Three independent checks run per
invoice: per-row `qty × unit == ext`, `Σ ext == Subtotal`, and
`Σ ext + charges == Grand Total`. Known real cases: a tall invoice is ONE image
referenced by several PDF pages (de-duplicate or every total doubles), and an
`Others` line between Subtotal and Grand Total is real money outside the item
table — book it as `freight`/`other`.

Then POST the parsed lines as a shared document (see above) and check the
response's `resolved_parts`.

## 4. Resolve MPNs to library components — never skip this

JLC invoices carry **no LCSC code**, only the manufacturer part number, while
BOM lines carry LCSC + `component_id`. Unresolved lines key as `m<MPN>` and can
never match a BOM draw, so every component silently costs 0.

```
POST /api/run-documents/{doc_id}/resolve-parts     # one document
POST /api/cost-lines/resolve-parts                 # everything unresolved
```

Matching is OCR-tolerant in three tiers, each requiring a unique hit: exact,
then folded (`0/O`, `1/I`, `5/S`, `8/B`, `2/Z` — real invoices produce
`O805W8F1200TSE` for `0805W8F1200T5E`), then prefix (a wrapped cell truncates
`ESP32-WROOM-32UE-N4` to `ESP32-WROOM-32UE-`). Non-exact matches are written
into the line's notes for audit. **Read the `unresolved` list** — those parts
will cost nothing until fixed by hand.

## 5. Draw the BOM

```
POST /api/runs/{run_id}/consumption/from-bom
```

Uses `BOM qty × (qty_good or plan_qty or qty)` at the pool's moving average,
skipping DNP and no-BOM lines. The response's **`unpriced`** array lists parts
with nothing in the pool — they cost 0 until their invoice is imported. Manual
draws: `POST /api/runs/{id}/consumption` with `basis` = `measured` | `bom` |
`allocated` | `manual` (the label is how a reader knows whether a figure was
measured or estimated; historical backfill is `allocated`).

## 6. Attrition

```
POST /api/projects/{id}/stock-adjustments
{ "mpn": "...", "qty_delta": -7, "reason": "attrition",
  "charge_run_id": 5, "adjusted_at": "2024-10-02" }
```

`charge_run_id` set → the loss lands on that run's cost. `reason` ∈ `attrition`,
`scrap`, `miscount`, `opening_balance` (use this to reconcile the pool against
today's JLC stock when backfilling), `correction`.

## 7. Plan vs actual

Cost items (`POST /api/projects/{id}/cost-items`) are the **estimate**; invoice
lines are the **fact**. Both are needed or the Δ is meaningless — a run with only
`PCB Production` planned shows +748% against a full invoice. Mirror the house
labels: `PCB Production`, `PCB Assembly - <fee>`, `PCB Shipping`,
`Device Assembly`, `Enclosure modification`, with `company` set. Order-level fees
are `per_run`; anything scaling with boards is `per_device` (fee ÷ batch size).

## 2b-bis. Read the invoice by LOOKING at it, then check the MRP

Text extraction returns cells in reading order, not column order, so an invoice's
numbers can be genuinely ambiguous. A real case: a bare `35` between the line total
and the item code fit two readings equally — 500 pieces at EUR 4.80 less a **35**
discount, or 325 pieces at EUR 4.80 flat, both giving the printed `1.560,00`.
Arithmetic cannot choose.

```python
import fitz
page = fitz.open(pdf)[0]
page.get_pixmap(dpi=190, clip=<the item-table rect>).save("look.png")   # then READ the image
```

Do this whenever a line does not reconcile on the first try, instead of inferring a
discount, a quantity or a rate. Rendering the page settled it immediately: `35` is
the DISCOUNT column.

**Then cross-check `~/Projects/7S_MRP/data/invoices.json`.** It is keyed by
`<date>-<VENDOR>-<invoice file stem>` and holds the per-item quantity, EUR unit
price and PLN unit price with the exchange rate used — the authoritative record of
how a purchase was understood at the time, and the way to catch a structural
mistake rather than an arithmetic one.

**A per-unit surcharge printed as its own position is NOT stock.** Italtronic bills
the digital print on an enclosure, and its one-off print set-up, as separate lines;
the MRP correctly folds both into the enclosure's unit cost. Importing them as
`part` lines creates a phantom pool item and leaves the set-up looking like
unallocated cost. Mark them `allocate: "by_qty"` (per-unit) or `"by_value"`
(one-off) so they spread onto that document's part lines. `allocate` is NOT gated on
`kind` — the operator's explicit choice is the signal. Spreading is per-document, so
an order placed without the surcharge simply carries none.

Do NOT derive a display label by splitting a formatted number
(`note.split(",")[0]` on `"500 x EUR 3.029 = 1,514.50"` yields `"500 x EUR 3.029 =
1"`). Label from the invoice's own description text.

## 2c. Money you must record but must NOT charge: `allocate="excluded"`

Some printed amounts are real on the page and wrong to charge to a product:

- **Reclaimable VAT**, including JLC's 23% "Import Taxes". Everything here is
  recorded NET, so import VAT gets the same treatment (user decision 2026-07-27).
- **The `PrePaid Amount` on a JLC populated-board invoice.** JLC bills boards
  ASSEMBLED, so the board price contains components the customer pre-ordered —
  the very components already in the pool from the matching `componentInvoice`.
  Booking the grand total pays for them twice (USD ~22,845 of double count on the
  six real invoices).

Do not simply leave them out: the document would then fail to reconcile against
its printed grand total, and the discrepancy would look like a transcription
error forever. Enter them and set `allocate: "excluded"` — recorded, auditable,
charged to nobody. `"excluded"` is NOT `unassigned`; unassigned means nobody has
noticed yet and is a defect.

Booking a populated-board invoice, per position:

```
POST /api/run-cost-lines/{board_line_id}/split
{ "allow_parts": true, "children": [
    { "label": "... — fab + assembly", "amount": <ext - prepaid_share>,
      "kind": "fab", "run_id": 7 },
    { "label": "... — components prepaid (already pooled)", "amount": <prepaid_share>,
      "kind": "part", "allocate": "excluded" } ] }
```

The prepaid lump is not broken down per product on the invoice, so apportion it
**pro rata by extended price** across the board positions and say so in the notes.
Charged total per invoice = `subtotal - prepaid`; check it against the printed
`Invoice Amount - Import Taxes`.

**Derive shipping as `subtotal - merchandise`.** On two of the six real invoices
the OCR'd shipping figure contradicts the printed subtotal, while
subtotal/tax/grand are internally consistent — so the derived value is the
trustworthy one, and 23% x subtotal does NOT reproduce the printed tax either.

For freight on a PARTS invoice, use `allocate: "by_value"` instead: the money is
spread over that document's part lines as landed cost, raising the moving average
to what the stock really cost to arrive. It only works when the document has
poolable part lines — otherwise the line stays unassigned and is reported.

## 2d. File the supplier's original

```
POST /api/run-documents/{doc_id}/attachment      # multipart, field name "file"
GET  /api/run-documents/{doc_id}/attachments
GET  /api/run-attachments/{id}                   # download, shared with run attachments
```

Always do this. The scan is stored under `documents/<id>/` in MinIO, never the
run's prefix, so it survives `delete_run`. Most of these PDFs are real text PDFs
(pymupdf reads them directly); only JLCPCB's are image-only and need OCR.

## The invoice register — check this before calling anything done

`GET /api/invoices` (the top of the Invoices view) is the company-wide
"money is not disappearing anywhere" check. Three independent questions:

1. **Does each document add up?** `issues.unreconciled` lists any whose lines
   miss the printed total.
2. **Does every position have a destination?** `summary.unassigned_usd` +
   `summary.residual_usd` must be 0. Unassigned = a non-part position on a shared
   document naming neither run nor project — money nobody pays for.
3. **Does the pool balance?** `pool.purchased + adjustments - drawn == on_hand`.

`summary.gap_usd` must be 0: invoiced == runs + projects + pool + excluded +
unassigned + residual, by construction. A non-zero gap is a bug in the platform, not bad data —
report it rather than working around it. `by_run_usd` is the same arithmetic as
each run's own actuals, so the two must agree.

## Verification checklist

Run all of it before calling a batch done:

1. `GET /api/runs/{id}/actuals` — `components` non-zero when the run has a BOM;
   `unknown_rates` empty; `delta` explainable line by line.
2. Every document `reconciled: true`.
3. `GET /api/projects/{id}/cost-pool` — `total_value_usd` equals the sum of
   imported part lines minus what has been drawn/written off. A part with
   `on_hand` far below 0 means draws exist without their purchase (import the
   earlier invoice).
4. `resolve-parts` reports `unresolved: []`, or every remainder is understood.
5. The freight/shared split's remainder is recorded for the other product.
6. Compare per-device cost against the MRP's `average_price_per_item` for that
   product; a large gap means a missing document, not a rounding issue.

## Pitfalls that actually bit

- **Claiming something is done without re-reading it.** A run "deleted" that was
  still there; a project reported as having no snapshots because the payload has
  no such key. Verify after every mutation.
- **Booking a components invoice onto a run.** It inflates that batch and starves
  the pool. Parts go to the pool; the run draws.
- **Importing an invoice dated after the run**, then wondering why components are
  free.
- **Trusting a rounded unit price** — reconcile against the printed extended
  price.
- **Forgetting `qty_good`** — per-device cost then divides by planned units and
  reads too low.
- **Deleting a run with financial rows** — it is refused (409) by design; remove
  or reassign the documents, draws and adjustments first.

