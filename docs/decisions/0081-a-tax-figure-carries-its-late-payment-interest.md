---
status: "accepted"
date: 2026-10-06  # accepted 2026-10-06 (user)
decision-makers: Mateusz Kowalik
consulted: Claude
---

# A tax figure carries its late-payment interest, and the health contribution is part of ZUS

## Context and Problem Statement

KSBR's export of 9SIGMA's taxes (2026-10-06) lists, beside each tax, the
amount actually paid. Nine payments were late, and the difference is
interest: 3,209 PLN in total, from 14 PLN to 1,192 PLN. The user expects
7Sigma has some too. A `CompanyTaxEntry` held the tax only, so the interest
could live only in the note, where nothing sums it.

The same review showed the `health` kind is not a separate payment. The
health contribution has gone to ZUS in the same transfer as the social
contributions since 2018. BOTO's mails give one ZUS total from 2022-03, and
the six `health` rows of 7Sigma (2021-08 to 2022-02) are the months of "ulga
na start", when the health contribution was the whole ZUS payment. The user
asked to drop the kind (2026-10-06).

## Decision Drivers

* Interest is money paid, and the user wants to see what lateness cost.
* Interest on tax arrears is not a deductible cost: art. 23 ust. 1 pkt 18 of
  the PIT act, art. 16 ust. 1 of the CIT act.
* One kind per payment the user actually makes.

## Considered Options

* An `interest` amount on the tax entry.
* An `amount paid` on the tax entry, interest derived as paid minus tax.
* Interest as its own entry kind.

## Decision Outcome

Chosen option: an `interest` amount on the entry, because it is the number
the user asks about, it sums cleanly, and a bank transfer or a ZUS statement
usually states it directly. The Taxxo export's paid amount converts to it on
import (paid minus tax).

1. **`company_tax_entries.interest`**, PLN, default 0, refused when
   negative. The entry form has an "Interest" box.
2. **Company books report it and count it nowhere else**: per month (the sum
   over the month's figures), in the year's totals, and on each figure. It is
   not a cost, not in the income, and not in a tax estimate.
3. **`health` is no longer a kind.** A startup statement turns each `health`
   row into the month's `zus` row when the month has none, and the note says
   so. A write with `health` is refused. The Books table shows "Interest"
   where it showed "Health".

### Consequences

* Good, because the cost of paying late is a figure, by month and by year.
* Good, because the ZUS column is the one transfer the user makes.
* Bad, because the split between social and health contributions is no
  longer a field. Nothing computed from it, and the accountant's notice keeps
  it.

### Confirmation

`api/tests/costs/test_tax_periods.py`: interest is reported on the figure,
the month and the year, and leaves costs, income and the tax estimate
unchanged; a negative interest is refused; `health` is not an entry kind.

## Pros and Cons of the Options

### An amount paid, interest derived

* Good, because it is what the Taxxo export and a bank statement show.
* Bad, because a partial payment makes "paid minus tax" a remainder, not
  interest, and the user would still have to read the interest off it.

### Interest as its own entry kind

* Good, because no new column.
* Bad, because one entry per month and kind is the rule: VAT interest and
  CIT interest of the same month would collide.

## More Information

Extends [0068](0068-a-company-has-overhead-and-books.md). Code:
`api/app/services/company_books.py` (`set_entry`, `year`),
`api/app/main.py` (the column and the `health` statement),
`web/src/pages/CompanyBooks.tsx`.
