---
status: "accepted"
date: 2026-10-15  # accepted 2026-10-15
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-15)
---

# Keep the overhead categories in a table that an administrator edits

## Context and Problem Statement

Decision [0068](0068-a-company-has-overhead-and-books.md) made company overhead
a destination with a category, and its item 1 fixed the categories as a list in
code: `run_actuals.OVERHEAD_CATEGORIES` and a copy in the web's `costs.tsx`. A
new category, for example `tools`, needed a code change and a deployment.

The user asked on 2026-10-15 for categories that are edited on the platform,
with a screen to add them, and set one rule: a category that positions use can
be removed only after all those positions go to another category.

## Decision Drivers

* A category is added without a code change.
* No overhead position may name a category that does not exist.
* Every company's books are summed by these categories, so a change affects
  both companies.

## Considered Options

* A table, edited by an administrator only.
* A table, edited by any signed-in user.
* Keep the list in code.

## Decision Outcome

Chosen option: "a table, edited by an administrator only" (the user's answer of
2026-10-15). The list is shared reference data, like the supplier register
([0055](0055-a-component-links-to-suppliers-in-a-register.md)).

1. **`overhead_categories` holds the list** (`key`, `label`). The startup fills
   an EMPTY table with the 13 categories of 0068, and never adds to a list an
   administrator has changed. `services/overhead.py` owns the rules.
2. **A position stores the key, so the key never changes.** The label can
   change. A new key is 1-40 characters of `a-z`, `0-9` and `_`, made from the
   label when none is given. A key and a label are each used once.
3. **A category is removed only when no live position names it** (`allocate`
   is `overhead`, not voided). The refusal (409) names the documents. Nothing
   moves positions for the user. `other`, where a position with no category
   counts, is never removed.
4. **Every write path refuses a key that is not on the list** (`_check_line`
   in `routers/run_costs.py`).
5. **Reading is open, writing is admin-only.** `GET /api/overhead-categories`
   and `GET /api/overhead-categories/{key}/documents` (in the header's company
   scope) are open, because every invoice editor offers the list. `POST`,
   `PATCH /{key}` and `DELETE /{key}` are in `tests/auth/test_role_gates.py`.
6. **The editor is a tab on Production → Company books** (`?tab=overhead`),
   not a new card on the books tab (the user's answer of 2026-10-15: the page
   had too many boxes). The tab also shows the year's overhead by category,
   which was a card on the books tab before.
7. **An agent has the same over MCP** (the user's request of 2026-10-15):
   `list_overhead_categories`, `edit_overhead_category` (it asks the admin
   question first, as `require_admin` does), and `assign_invoice_line` with
   `allocate="overhead"` and `overhead_category`.

### Consequences

* Good, because a category is added in a few seconds, and the books and every
  invoice editor offer it at once.
* Good, because a category cannot vanish from under the positions that use it.
* Bad, because an undo (decision
  [0089](0089-every-change-is-recorded-and-can-be-undone.md)) can put a position
  back on a category removed since. The list then shows that key as "not on
  the list", the books show the key instead of a label, and an administrator
  adds the category again with that key.
* Neutral, because a position stores a string, not a foreign key: an empty
  category is legal and means `other`.

### Confirmation

`tests/costs/test_overhead_categories.py`: the seed fills an empty list only, a
key is made from the label, a new category takes positions and reaches the
books, an unknown category is refused, a used category is removed only after
its positions move, a voided position does not hold one, `other` is never
removed, a key or a label is never taken twice, a new label keeps the key, and
a key in use but not on the list is listed. `tests/auth/test_role_gates.py`
holds the three gated routes. The same test file calls the three agent tools
as an agent calls them: a caller who is no admin is refused. Checked in a browser against the local stack on
2026-10-15.

## Pros and Cons of the Options

### A table, edited by an administrator only

* Good, because one change to the shared list is made deliberately.
* Bad, because a user who assigns positions asks an administrator for a new
  category.

### A table, edited by any signed-in user

* Good, because the person entering the invoice adds what they need.
* Bad, because both companies' books change with no gate.

### Keep the list in code

* Good, because nothing changes.
* Bad, because each new category is a deployment.

## More Information

Amends item 1 of [0068](0068-a-company-has-overhead-and-books.md). The rules
are in [docs/reference/company-books.md](../reference/company-books.md).
