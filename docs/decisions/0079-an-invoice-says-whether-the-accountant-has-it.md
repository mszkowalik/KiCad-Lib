---
status: "accepted"
date: 2026-10-06  # accepted 2026-10-06 (user)
decision-makers: Mateusz Kowalik
consulted: Claude
---

# An invoice says whether the accountant has it

## Context and Problem Statement

The user sends the invoices KSeF does not carry to the accountant every month,
by the 10th of the next month: to Bogumiła Tomana (7Sigma) and KSBR (9SIGMA).
Nothing recorded which documents had gone, so a missing one was found only
when the accountant asked. The user asked to note "sent to accountant" on each
invoice, to treat KSeF invoices as sent, and to keep a monthly list of what is
missing (2026-10-06).

## Decision Drivers

* The accountant reads KSeF: a KSeF invoice needs no sending.
* A document nobody pays for needs no sending.
* The evidence of a send differs: a mail to the accountant, an entry she
  booked, a click.

## Considered Options

* Three columns on the supplier document and the sales invoice.
* One generic table of sends.
* Compute "sent" from the mailbox each time.

## Decision Outcome

Chosen option: three columns on each record, because the list must filter and
sort them, and one send per document is the rule.

1. `accountant_sent_at`, `accountant_sent_via` (`kpir`, `mail`, `manual`,
   `history`) and `accountant_sent_ref` on `run_cost_documents` and
   `sales_invoices`.
2. **A KSeF document is sent without a row** (`services/accountant.state`): a
   purchase imported from KSeF, a sales invoice with a KSeF number.
3. **A document nobody pays for is not to send**: a proforma, an in-house
   transfer, a supplier document whose positions are all charged to nobody,
   a draft or cancelled sales invoice.
4. `GET /api/companies/{company_id}/accountant` lists what is left, by month,
   with the deadline (the 10th of the next month) and whether it passed.
   `POST` records a send for a list of documents, or clears it with an empty
   date. Any member of the company may do both.
5. The pages show the state on each document and sales invoice, and Company
   books has a "For the accountant" card to tick and record.

### Consequences

* Good, because the monthly list shows exactly what the accountant lacks.
* Bad, because a send outside the mailbox the import read must be recorded by
  hand.

### Confirmation

`api/tests/costs/test_accountant.py`: KSeF counts as sent, an excluded or
proforma document is not to send, the month's deadline and lateness, a send
recorded and cleared, `ksef` refused as a typed channel, a document of another
company refused.

## Pros and Cons of the Options

### One generic table of sends

* Good, because a document could carry several sends.
* Bad, because the list then joins a second table for every document, and a
  second send changes nothing the user needs.

### Compute "sent" from the mailbox each time

* Good, because nothing is stored twice.
* Bad, because the mailbox is not reachable from the platform, and a send by
  hand or in person has no mail.

## More Information

Extends [0068](0068-a-company-has-overhead-and-books.md) and
[0077](0077-a-record-keeps-its-files-and-a-company-its-issued-history.md).
Code: `api/app/services/accountant.py`, `api/app/routers/companies.py`,
`web/src/components/AccountantMark.tsx`, `web/src/pages/CompanyBooks.tsx`.
