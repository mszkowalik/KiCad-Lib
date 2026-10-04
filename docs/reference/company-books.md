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
* **It names nothing else.** `routers/run_costs._one_destination` clears the
  batch, project and transformation and sets `basis="per_run"`;
  `_check_allocate` refuses it on a stock step.
* **It is a register bucket**: `document_json` reports `overhead`, the register
  sums `to_overhead_usd`, and `gap_usd` subtracts it. A new bucket must be
  added to all three, or the gap stops being zero.

## The page's figures

* **Every figure is an estimate.** The accountant's figures
  (`company_tax_entries`) are entered beside them and are the ones that count.
* **Revenue** is the net of issued sales invoices by issue date. An advance
  counts for VAT and not for income. A platform correction counts its
  difference from `body.correction.before_totals`; a correction read from KSeF
  already states the difference.
* **Costs** are the supplier documents billed to the company, by document
  date, by destination. Excluded positions and transfers are no cost.
* **VAT on purchases** is read from `tax_amount` of PLN documents only.
* **Income tax** follows `companies.tax_form`; with none stated there is no
  estimate. Never guess a tax form.
