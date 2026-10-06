---
status: "accepted"
date: 2026-10-06  # accepted 2026-10-06 (user)
decision-makers: Mateusz Kowalik
consulted: Claude
---

# An invoice can be kept from the accountant, and that is a separate switch from "excluded"

## Context and Problem Statement

The import of 2026-10-05/06 put every invoice from the Mac and Gmail on the
platform. Many of them never reached the accountant: the user did not send
them, or lost them, and the years they belong to are closed (7Sigma's PIT for
2025 is filed). Decision
[0079](0079-an-invoice-says-whether-the-accountant-has-it.md) lists them as
"late" for ever: 102 documents for 7Sigma and 45 for 9SIGMA on 2026-10-06.
The user asked for a way to say "this one will never be sent", keeping the
invoice on the platform (2026-10-06).

0079 already took one kind of document off the list: a supplier document
whose positions are all `excluded`. But `excluded` answers a different
question, who bears the cost. Of the 32 documents with every position
excluded on 2026-10-06, 18 had reached the accountant: JLC orders for
external projects that she booked in the KPiR or got by mail. A second
"ignore" control beside that rule would give two ways off the list with
different side effects.

## Decision Drivers

* Who bears a cost and whether the accountant has the invoice are separate
  facts. One switch per fact.
* An invoice the accountant never got is not in her tax figures, so the
  platform's tax estimate must leave it out too.
* It is still money spent: batch, project and stock costs keep it (user
  2026-10-06).
* Nothing is hidden: the invoice stays, with the reason.

## Considered Options

* A per-invoice mark "not for the accountant", independent of `excluded`.
* A "closed through" year per company that drops every unsent document of a
  closed year.
* A "closed through" month per company.
* Keep the 0079 rule and exclude every position of an invoice that will not
  be sent.

## Decision Outcome

Chosen option: a per-invoice mark, because a year can still change after it
is closed, and a per-invoice decision with a reason says exactly what
happened (user 2026-10-06).

1. **`via = "not_sent"`** on the three 0079 columns: `accountant_sent_at`
   holds the day of the decision and `accountant_sent_ref` the reason (lost,
   private, too late, or any text). A reason is required. Clearing the date
   undoes it, as for a send.
2. **A KSeF document cannot be marked**: the accountant reads it in KSeF
   whatever the platform says.
3. **The 0079 rule "every position excluded means nothing to send" is
   removed** (overrides item 3 of 0079). Excluded positions decide costing
   only. A proforma, an in-house transfer, and a draft or cancelled sales
   invoice still need no sending.
4. **Company books skip a marked record**: its costs, overhead and purchase
   VAT, or for a sales invoice its revenue and sales VAT. Batch, project and
   stock costs do not read the mark.
5. The document and sales-invoice panels offer "Not for the accountant…"
   beside "Mark sent…", and the "For the accountant" card does the same for
   the ticked rows.

### Consequences

* Good, because the monthly list ends: every row is sent, to send, or kept
  from the accountant with a reason.
* Good, because the books estimate tax from what the accountant can know.
* Bad, because 14 documents with every position excluded and no send record
  return to the list on deploy, and each needs a decision.
* Bad, because an old invoice found later lands on the list again until it
  is marked. That is the reminder the user wants, but it is a click.

### Confirmation

`api/tests/costs/test_accountant.py`: a marked document leaves the list and
the books and comes back when cleared; a reason is required; a KSeF document
refuses the mark; a document with every position excluded is to send again;
a marked sales invoice leaves the revenue.

## Pros and Cons of the Options

### A "closed through" year per company

* Good, because no clicks for a whole closed year.
* Bad, because a closed year still takes corrections, and a document added
  later would vanish from the list without anybody deciding about it.

### A "closed through" month per company

* Good, because it follows the VAT rhythm.
* Bad, because a month is not final for the user: corrections land later
  (user 2026-10-06).

### Exclude every position of an unsent invoice

* Good, because no new control.
* Bad, because it removes a real cost from batches and stock, and it mixes
  the two questions this record separates.

## More Information

Extends [0079](0079-an-invoice-says-whether-the-accountant-has-it.md) and
overrides its item 3. Code: `api/app/services/accountant.py`,
`api/app/services/company_books.py`, `web/src/components/AccountantMark.tsx`,
`web/src/pages/CompanyBooks.tsx`.
