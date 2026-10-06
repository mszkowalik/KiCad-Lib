# Company books and overhead

The reasoning is in
[decision 0068](../decisions/0068-a-company-has-overhead-and-books.md). The
code is `api/app/services/company_books.py` (the page's figures) and the
`overhead` destination in `services/run_actuals.py`. The page is
Production → Company books.

## Overhead

* **`allocate="overhead"` with `overhead_category`** is a company cost of no
  product. `run_actuals.OVERHEAD_CATEGORIES` and the web's
  `components/costs.tsx` `OVERHEAD_CATEGORIES` are the same list; change both.
* **It names nothing else, on every write path.** `routers/run_costs`
  clears the batch, project and transformation and sets `basis="per_run"`
  when a position is created (`_overhead_whole`), patched or split
  (`_one_destination`). A patch that names a batch, a project or a
  transformation without `allocate` takes the position off the overhead.
  `_check_allocate` refuses an overhead on a stock step.
* **A batch never pays for it.** `run_actuals.run_actuals` skips an overhead
  position, even one that still names a batch, and `effective_qty` never
  multiplies it by units. An overhead logistics position is no
  `unspread_transport`.
* **It is a register bucket**: `document_json` reports `overhead`, the register
  sums `to_overhead_usd`, and `gap_usd` subtracts it. A new bucket must be
  added to all three, or the gap stops being zero.

## The page's figures

* **Every figure is an estimate.** The accountant's figures
  (`company_tax_entries`) are entered beside them and are the ones that count.
* **Revenue** is the net of issued sales invoices
  (`company_books._sales_effect`), in the month of `book_date`: the earlier
  of the sale date ("data wykonania usługi") and the issue date, as the tax
  point is. An April service invoiced on 5 May is April's. A correction keeps
  its issue date (decision 0077). An advance counts for VAT and not for
  income, at the advance (`invoicing.service.advance_amounts`), never at the
  order total. A correction counts its difference once
  (`invoicing.service.correction_difference`): a platform correction from its
  state before, a KSeF correction as it states it, and a script correction
  that changed text only as nothing. A correction of an advance is an advance.
* **A settlement invoice (ROZ) is the delivery.** It counts the whole order as
  revenue on its date: the net of its positions, which FA(3) states at full
  order value. Its VAT is the VAT it states, the part the advances did not
  carry. So the advances reach revenue at the settlement.
* **A final advance invoice ("zaliczkowa końcowa") is the delivery too.**
  When advances pay the whole order, no settlement follows, so the last
  advance counts the whole order as revenue on its date
  (`invoicing.service.is_final_advance`, `order_net`), with its own VAT.
  It is read from `body.final_advance`, or from the printed title of an
  imported document. Found 2026-10-06: Columbus Energy's ZAL 01/04/2024 and
  ZAL 01/06/2024 paid 500 dongles in full, and the KPiR books both as revenue.
* **Costs** are the supplier documents billed to the company, by document
  date, by destination. Excluded positions and transfers are no cost.
* **A record kept from the accountant is in no figure here**: not its
  revenue, cost, overhead or VAT (decision 0080). Her tax cannot include an
  invoice she never saw.
* **VAT on purchases** is read from `tax_amount` of PLN documents only.
* **The income tax is the company's legal form** (`companies.legal_form`,
  `company_books.income_tax`): a `sole_trader` pays PIT and may have
  `pit_linear`, `pit_scale` or `lump`; a `company` (sp. z o.o.) pays CIT and
  may have `cit_9` or `cit_19`. A form that does not fit is refused, and the
  page labels its columns PIT or CIT from it. The startup fill read the
  legal name; Admin → Companies changes it.
* **A company shows no ZUS column unless it has a ZUS figure.** It pays ZUS
  only as an employer; its sole shareholder pays his own contributions
  outside the company (art. 8 ust. 6 pkt 4 of the social insurance act). The
  entry form still offers ZUS, for the day it employs somebody.
* **Income tax** follows the form of each month's quarter
  (`company_tax_periods`, decision 0078), else `companies.tax_form`; with
  neither there is no estimate. Never guess a tax form. A period's `rate`
  replaces the statutory computation (of income; of revenue for `lump`). The
  scale follows the year: 17 % / 32 % up to 2021, 12 % / 32 % from 2022.
* **A tax figure carries its late-payment interest** (`interest`, decision
  0081): summed per month (`months[].interest`) and in `totals.interest`,
  and in nothing else. It is never a cost and never in a tax estimate (art.
  23 ust. 1 pkt 18 of the PIT act, art. 16 ust. 1 of the CIT act).
* **The kinds are `vat`, `pit`, `cit`, `zus` and `other`.** The health
  contribution is paid with ZUS and entered as `zus` (decision 0081); a
  `health` write is refused.
* **A tax figure keeps the accountant's notices** in `record_files`
  (`/api/companies/{company_id}/tax-entries/{entry_id}/files`, decision 0077).
  The books report a count per figure (`accountant[kind].files`).
* **Whether the accountant has a document** is `services/accountant.state`
  (decision 0079). A KSeF document has it without a row, also one typed by
  hand and later linked to a KSeF row (`ksef_invoices.document_id`); a proforma, a
  transfer and a draft or cancelled sales invoice are not to send.
  `GET /api/companies/{id}/accountant` lists the rest by month, due the
  10th of the next month; `POST` records or clears a send.
* **"Not for the accountant" is a send record with `via="not_sent"`**
  (decision 0080): the date is the decision, `ref` the reason, and a reason
  is required. It takes the record off the list and out of every figure on
  this page (`accountant.kept_from_accountant`); batch, project and stock
  costs do not read it. A KSeF document refuses it.
* **`excluded` does not decide sending.** It says who bears a cost. A
  document with every position excluded is still to send unless it is sent
  or marked: most fully excluded JLC orders reached the accountant
  (decision 0080 overrides item 3 of 0079).
