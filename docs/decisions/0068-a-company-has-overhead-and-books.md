---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04 to the two-company plan)
---

# Charge overhead to the company by category, and keep the company's books beside the accountant's

## Context and Problem Statement

Every supplier position went to a batch, a project, the stock or nobody. A
leasing instalment, a telephone bill or the accountant's own invoice belongs
to none of these: it is a cost of the company. Such positions were left
unassigned, which the register reports as a defect, or charged to a project
they have nothing to do with.

The user's answer of 2026-10-04 (answer 7): overhead is kept as categories
assigned to companies, not projects. The user also asked for a company page
with basic calculations (KPIR, estimated VAT and PIT), and a way to enter the
accountant's computed taxes (PIT, VAT, ZUS) as estimated or final, the way a
batch has an estimated and a final cost.

## Decision Drivers

* A position says where its money goes, outright
  ([0045](0045-a-position-says-where-its-money-goes.md)), and the register's
  gap stays zero ([0048](0048-the-gap-is-an-invariant-not-a-tolerance.md)).
* An estimate never passes for the accountant's figure.
* Nothing about the company's tax position is guessed.

## Considered Options

* An overhead position charged to a dummy project per company.
* A fifth destination, `overhead`, with a category; the document's buyer is
  the company.
* Company books computed on the page, or a ledger the platform keeps.

## Decision Outcome

Chosen options: "a fifth destination" and "books computed on the page". A dummy
project would put overhead into project cost figures and into the project
list. A ledger would make the platform a second accounting system beside the
accountant's.

1. **`allocate="overhead"` is a destination** with `overhead_category` (leasing,
   phone and internet, software, accounting, office, travel, car, insurance,
   bank fees, rent, marketing, training, other). It names no batch, project or
   transformation, never sits on a stock step, and comes right after
   `excluded` in `line_destination`. The register gets an `overhead` bucket in
   each document's assignment and in its identity, and `to_overhead_usd`.
2. **The company page computes each month of a year**, in PLN: revenue from
   the issued sales invoices (an advance counts for VAT, not income), costs
   from the supplier documents billed to the company split by destination
   (excluded positions and in-house transfers are no cost), VAT as sales VAT
   minus purchase VAT, and income tax year-to-date by the company's stated tax
   form (linear, scale, lump sum, CIT 9 % or 19 %). With no tax form stated,
   no tax is estimated.
3. **The accountant's figures are entered per month and per kind** (VAT, PIT,
   CIT, ZUS, health, other), as estimated or final, with due and paid dates
   (`company_tax_entries`). The page shows them beside the estimate.
4. **The company record carries the tax form** (admin), and the page is the
   company's data under the company gate
   ([0065](0065-a-record-of-another-company-does-not-exist-for-the-caller.md)).

### Consequences

* Good, because overhead stops reading as unassigned money, and each company's
  overhead is visible by category.
* Good, because the month's estimate and the accountant's figure sit in one
  row, so a difference is seen.
* Bad, because the estimate is rough: ZUS and the health contribution are not
  deducted, stock is a cost when bought with no year-end count, a foreign
  invoice's VAT is left out, and the exchange rate is the platform's at the
  document date, not the NBP rate of the day before.
* Neutral, because the estimate can only be as complete as the documents: a
  month without its supplier documents shows too little cost.

### Confirmation

Tests show that an overhead position is the company's and keeps the register's
gap at zero, that the books count revenue without the advance, costs by bucket
with overhead by category, VAT with the advance's VAT, a linear tax on the
year-to-date income and nothing new in a month that added nothing, that a
correction counts its difference, that the accountant's figure replaces the
last one and refuses a bad period or kind, and that the scale and the lump sum
compute as stated.

## Pros and Cons of the Options

### A dummy project per company

* Good, because no new destination is needed.
* Bad, because overhead would appear as project cost.

### A fifth destination

* Good, because the position says what it is, and the buyer says whose it is.
* Bad, because the register's identity and every editor learn a new bucket.

### Books computed on the page

* Good, because the accountant's books stay the only books.
* Bad, because the figures are estimates.

## More Information

The rules are in [docs/reference/company-books.md](../reference/company-books.md).
