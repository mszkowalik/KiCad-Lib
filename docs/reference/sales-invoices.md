# Sales invoices

The platform writes the sales invoices of a company marked `issues_invoices`
(7Sigma). The reasoning is in
[decision 0066](../decisions/0066-the-platform-issues-7sigmas-sales-invoices.md).
The code is `api/app/services/invoicing/` and `api/app/routers/sales_invoices.py`.
The page is Production → Sales invoices.

## Rules

* **Never write an invoice for 9SIGMA.** `service.issuing_company` refuses a
  company without `issues_invoices`. 9SIGMA invoices with its own system and is
  only read from KSeF.
* **An issued invoice never changes in place.** `service.update` takes a draft
  or a proforma only. A mistake on an issued invoice is a correction
  (`service.correct`), and a draft never sent is cancelled, which frees its
  number.
* **Amounts are `Decimal`, rounded half-up to the grosz, VAT per position**
  (`invoicing/amounts.py`). Never a float on this path.
* **Imported documents keep their printed figures.** `service.from_register`
  copies amounts, `amount_due` included, and never recomputes them. Their
  payment state is what the old register said, so the page shows "not
  recorded", not "overdue".
* **The series and the number** are in `invoicing/numbering.py`. A new
  document type gets a series there, never an ad-hoc number.
* **The XML must pass the schema before it is served.**
  `GET /api/sales-invoices/{id}/xml` refuses with the schema's errors. The
  schema files in `invoicing/schema/` are the Ministry's FA(3) 1-0E; replace
  all four together when the Ministry publishes a new version. The schema
  limits dates to 2050, so a test that needs an empty series uses 2049.
* **The QR code needs the official XML's hash**, not the draft's: KSeF stores
  its own copy, and the link verifies that file.
* **The bank account comes from the company record** (Admin → Companies) and
  is copied into each new document. It is never in a seed, a fixture, a test
  or a log.

## What the FA(3) writer covers

`invoicing/fa3.py` writes VAT, KOR and ZAL in PLN. It refuses ROZ (a
settlement invoice after advances), other currencies and the taxi rates 4 and
3. The rate codes map to the totals the schema documents in `RATE_FIELDS`.
Element ORDER matters: the schema is a sequence, and the writer follows it.

## Import

`POST /api/sales-invoices/import` (admin, dry run by default) takes the
script's `rejestr.json`, `klienci.json`, `cykliczne.json` and `produkty.json`
as uploads. A document already on the platform (same kind, number and date) is
skipped; a buyer is matched by NIP, then by name.
