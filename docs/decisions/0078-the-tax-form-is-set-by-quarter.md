---
status: "accepted"
date: 2026-10-06  # accepted 2026-10-06 (user)
decision-makers: Mateusz Kowalik
consulted: Claude
---

# The income-tax form is set by quarter

## Context and Problem Statement

A company had one income-tax form (`companies.tax_form`), so the books
estimated every year with it. 7Sigma used the scale (zasady ogólne, PIT-36)
for 2021–2023 and linear tax (PIT-36L) from 2024, according to its returns.
The user asked to set the form so that it can change "once per quarter"
(2026-10-06). The scale rule in the code also held only the 2022 rates
(12 % / 32 %), so 2021 was computed wrongly.

## Decision Drivers

* The estimate must follow the form each period was really taxed under.
* A past year's return states the real tax, which the statutory computation
  cannot know (IP BOX at 5 %, deductions, joint filing).
* By law (art. 9a ustawy o PIT) the form is chosen for a whole year, by the
  20th of the month after the year's first revenue. The user wants a finer
  setting.

## Considered Options

* One form per year.
* One form per quarter, applied until the next row.
* An effective rate per month, typed by hand.

## Decision Outcome

Chosen option: one form per quarter, because it is what the user asked for and
it covers a yearly change.

1. `company_tax_periods` holds `(company, from_quarter, form, rate, note)`. A
   month takes the last row that starts at or before its quarter, else the
   company's one `tax_form` (`company_books.tax_setting`).
2. `rate` (percent, optional) replaces the statutory computation: of income,
   or of revenue for `lump`. It is for a year whose return shows the tax.
3. The scale follows the year: 2021 and before at 17 % / 32 % with the falling
   reducing amount, 2022 on at 12 % / 32 % with the 30 000 free amount.
4. Routes: `GET`, `PUT` (admin) and `DELETE` (admin)
   `/api/companies/{company_id}/tax-periods`. Company books shows the rows and,
   to an admin, the form to add one.

### Consequences

* Good, because each month's estimate uses its own form, and a year with a
  return can carry its real rate.
* Bad, because the setting allows a change the law does not, so the page
  states the yearly rule beside it.

### Confirmation

`api/tests/costs/test_tax_periods.py`: a month's form by quarter, the
replacement of a quarter's row, the refusal of a bad quarter or form, the 2021
and 2023 scale figures, and an effective rate on income and on revenue.

## Pros and Cons of the Options

### One form per year

* Good, because it is the legal rule.
* Bad, because the user asked for a quarter.

### An effective rate per month

* Good, because every month can match the accountant.
* Bad, because the accountant's monthly figures are already entered beside the
  estimate; a typed rate per month would only copy them.

## More Information

Extends [0068](0068-a-company-has-overhead-and-books.md). Code:
`api/app/services/company_books.py`, `api/app/routers/companies.py`,
`web/src/pages/CompanyBooks.tsx`.
