---
status: "accepted"
date: 2026-10-06  # accepted 2026-10-05 (user, before the overnight import)
decision-makers: Mateusz Kowalik
consulted: Claude
---

# A record keeps its files, and a company keeps its issued history

## Context and Problem Statement

The user asked to move all accounting data from the Mac and Gmail into the
platform, with every PDF stored and reachable (2026-10-05). A supplier
document could hold its original PDF (`RunAttachment`). A sales invoice and an
accountant's tax figure could not hold any file. 9SIGMA's sales invoices from
before KSeF (10 documents, 2024-10 to 2026-04) had no place at all:
`service.issuing_company` refuses every invoice of a company that does not
issue on the platform, and decision
[0066](0066-the-platform-issues-7sigmas-sales-invoices.md) reads 9SIGMA from
KSeF only. The books also put each sales document in the month of its issue
date, so an April service invoiced on 5 May counted in May (user report,
2026-10-06).

## Decision Drivers

* A financial record keeps its evidence, and the evidence outlives any edit.
* A company's revenue history must be complete, also for the months before
  KSeF and for a company that issues with its own system.
* Recording a document that was issued elsewhere is not issuing it.
* The tax point of a sale is the day of the delivery or service, and no later
  than the invoice.

## Considered Options

For the files: owner columns on `run_attachments`; one table `record_files`
with an owner kind and an owner id.

For the history: a flag that lets 9SIGMA issue on the platform; a record that
is written as printed and is never issued.

For the books: the issue date; the earlier of the sale date and the issue date.

## Decision Outcome

1. **One table, `record_files`**, holds the files of a sales invoice and of a
   tax entry (`owner_kind`, `owner_id`, the owner's `company_id`). Bytes are in
   MinIO under `record-files/`. Routes:
   `/api/sales-invoices/{invoice_id}/files[/{file_id}]` and
   `/api/companies/{company_id}/tax-entries/{entry_id}/files[/{file_id}]`.
   A file is added and read. Nothing replaces or deletes one. The company gate
   resolves every new parameter.
2. **`POST /api/sales-invoices/history` (admin)** records a sales document a
   company issued elsewhere, as printed: status `issued`, source
   `import: document`, no KSeF, no number from the series. Any company may
   have history. An advance keeps the advance in `totals` and the order in
   `body.order`; a settlement keeps the whole order as positions and what is
   left to pay in `totals`, as FA(3) states both. A number is recorded once.
   The platform still never ISSUES an invoice for 9SIGMA.
3. **A sales document enters the books on the earlier of its sale date and its
   issue date** (`company_books.book_date`). A correction keeps its issue
   date, because its sale date is the corrected invoice's.
4. The web shows the files on the invoice panel ("Documents") and on a tax
   figure ("Notices") through one shared component, `RecordFiles`, which the
   supplier document's originals use too. A recorded document offers no
   "XML for KSeF" and no "Correction…".

### Consequences

* Good, because every sales invoice and tax figure can carry its PDF, and
  9SIGMA's revenue from 2024-10 is on the platform.
* Good, because the books follow the tax point, so April's service is April's.
* Bad, because a wrong file stays: there is no delete. A second, right file is
  added beside it.
* Bad, because the books' months for sales now differ from the issue-date
  months that the KSeF list shows.

### Confirmation

`api/tests/costs/test_record_history_and_files.py`: history for a company that
does not issue, the books' advance and settlement figures, a number recorded
once, a file never reached under another record, a tax entry file under its
own company only, and the service month. `tests/auth` lists the admin route and
classifies the new parameters.

## Pros and Cons of the Options

### Owner columns on `run_attachments`

* Good, because one table holds every file.
* Bad, because that table belongs to production runs and supplier documents;
  each new owner adds a column and a branch to "exactly one owner".

### A flag that lets 9SIGMA issue on the platform

* Good, because no new route is needed.
* Bad, because 9SIGMA issues with its own system: the platform would offer
  numbering and KSeF drafts for invoices it must never write.

### Books by issue date

* Good, because it matches the KSeF list.
* Bad, because the tax point is the service date, so a month's revenue and VAT
  were wrong whenever an invoice came after the month it bills.

## More Information

Extends [0066](0066-the-platform-issues-7sigmas-sales-invoices.md),
[0067](0067-the-platform-reads-both-companies-from-ksef.md) and
[0068](0068-a-company-has-overhead-and-books.md). Code:
`api/app/services/record_files.py`, `services/invoicing/service.py`
(`record_history`), `services/company_books.py` (`book_date`),
`web/src/components/RecordFiles.tsx`.
