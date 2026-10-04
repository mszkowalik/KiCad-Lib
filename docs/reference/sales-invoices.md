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
* **The platform gives out a number once.** The partial unique index
  `uq_sales_invoices_number` (company, kind, number) refuses a second writer.
  The service then takes an automatic number again and refuses a typed one
  (409). The imported history is outside the index, because it keeps the
  numbers it printed, two duplicate proformas included.
* **A new issue date in another month renumbers a draft.** The number names
  the month. A VAT draft whose sale date was its issue date keeps the two
  together. A correction keeps the sale date of the invoice it corrects, and
  an advance keeps the day the money came.
* **`generate` writes a recurring invoice once per month.** It locks the
  template and refuses a second draft for a month that has one. The month a
  document was written for (`body.template_month`) decides. So a draft
  written for April and re-dated into May is April's, and May stays free. A
  document without that month, such as the imported history, counts for the
  month of its issue date.
* **`issue` checks what it records.** The KSeF number must start with the
  seller's NIP. The official XML must carry the invoice's number (P_2) and the
  seller's NIP, and the hash KSeF stated when it has one. A recorded KSeF
  number never changes to another one (409).
* **A recorded payment stays.** `mark_paid` sets `paid` on the record and
  leaves the document alone. It refuses an invoice already paid (409), and it
  keeps the amount due of an imported document as printed. A later edit
  changes `paid` only when it sends `payment`.
* **A next correction starts from the last one.** `service.correct` takes as
  the state before the invoice's totals plus the difference of every issued
  correction of it, and the positions (or the order) of the latest one. It
  refuses while a draft correction of the invoice is open, and when the
  latest correction states only a difference or a text, because the
  positions after it are not known. A correction read from KSeF points at
  the invoice it corrects (`corrects_id`, by KSeF number or number).
* **A company in a body or a query is the caller's.** `company_id` of a new
  invoice, a template or the next number answers 404 for a company the caller
  cannot see (decision 0065). An admin sees every company.
* **What a correction and an advance amount to is read in one place each.**
  `service.correction_difference` gives after minus before, whoever wrote the
  correction. `service.advance_amounts` gives the advance, never the order:
  an advance imported from the script printed the order, and the import keeps
  its advance, the amount to pay, as `body.advance_gross`. The books and the
  amount due read only these two.
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

`invoicing/fa3.py` writes VAT, KOR, KOR_ZAL and ZAL in PLN. It refuses ROZ (a
settlement invoice after advances), other currencies and the taxi rates 4 and
3. The rate codes map to the totals the schema documents in `RATE_FIELDS`.
Element ORDER matters: the schema is a sequence, and the writer follows it.

* **A correction of an advance is KOR_ZAL.** It has no positions. The order
  before (`StanPrzedZ`) and after goes in `Zamowienie`, and it changes with
  `order_lines` and `advance_gross`, as the advance does.
* **The annotations follow the rates.** An exempt position (`zw`) writes
  `P_19` and `P_19A` with `body.exemption.basis`. The writer refuses the
  invoice without a basis (`exemption_basis` on create or update). A domestic
  reverse charge (`oo`) and a service taxed where the buyer is (`np II`) write
  `P_18` = 1, "odwrotne obciążenie".
* **An EU buyer keeps its VAT number.** `service.party_ids` keeps the number
  without its country prefix (`NrVatUE`), and the prefix goes in `KodUE`
  (`EL` for Greece). A buyer outside the EU keeps its tax number as written
  (`NrID`).
* **A unit price keeps up to 8 decimals** (`amounts.price`), as P_9A allows.
  The net is computed from that price, and the PDF and the XML print it whole.

## Import

`POST /api/sales-invoices/import` (admin, dry run by default) takes the
script's `rejestr.json`, `klienci.json`, `cykliczne.json` and `produkty.json`
as uploads. A document already on the platform (same kind, number and date) is
skipped; a buyer is matched by NIP, then by name.
