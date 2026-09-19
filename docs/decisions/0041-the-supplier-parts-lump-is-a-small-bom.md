---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# Itemise the parts a supplier sourced, keep them out of the pool, and check coverage against the supplier's own BOM

## Context and Problem Statement

An assembly invoice bills ONE figure for the components the factory sourced
itself — JLC's `materialMoney`, printed as "Components sourced by JLC",
USD 2,097.28 on batch 8 alone and USD 8,453.19 across the account. The platform
recorded it as a single line, so it could not say which parts it bought.

Three consequences, all real:

* **A BOM position met by the supplier looked identical to a forgotten one.**
  Decision [0038](0038-a-substitution-belongs-to-the-batch.md) was written after
  exactly that: batch 8 drew no `T491D107K016AT`, and only JLC's own BOM
  explained why.
* **The double charge had to be undone by hand.** `void_shop_draws` exists to
  void pool draws for parts the supplier supplied, because otherwise the run
  pays twice. Nine consumptions have been voided that way.
* **`_child_kind` forced these lines to `assembly`** to stop a run-less `part`
  leaf claiming the pool, which made components read as labour on every
  Materials view.

## Decision Drivers

* The supplier states the facts; we should not derive them. Same rule as
  [0037](0037-the-supplier-keeps-the-receipts.md).
* A hand-written invoice must be a first-class citizen. The supplier list is not
  going to stay one vendor, and a JLC-shaped table would make every other one a
  second-class case forever.
* A guard that has to be run by hand after the fact is not a guard.

## Considered Options

* Itemise into ordinary cost-line children, charged to the run, never pooled.
* Itemise into the shared cost pool and draw from it normally.
* Leave the lump and keep voiding draws by hand.

## Decision Outcome

Chosen option: "Itemise into ordinary children, charged to the run, never
pooled".

1. **The lump becomes a header and each part a child**, through the SAME split
   path a hand-typed breakdown uses. No new table, nothing JLC-shaped, and no
   second endpoint that writes positions: `services/supplier_parts.py` only
   reads the cached BOM and returns a plan, and `split` applies it. One button
   on the position fills it; the children then edit IN PLACE in the document's
   own edit mode, because the columns a part needs are already in that table and
   a second editor would be a copy of it. A part share names a library component
   and carries a quantity at a price — the pool keys on the component and
   coverage counts pieces, so a typed label with no quantity can meet neither.
2. **They never enter the shared pool.** The children keep the parent's
   `run_id`, so they are charged to the batch directly. These parts were never
   in our stock, were never available to another batch, and carry a price
   specific to one order — pooling them would invent inventory and pollute the
   moving average.
3. **Coverage is checked against the supplier's BOM**, not against a figure we
   derived: per part, what the supplier says came from OUR stock must equal what
   we drew. `drawn_but_supplier_supplied` is the double charge `void_shop_draws`
   undid by hand; `no_draw` is its mirror.
4. **`_child_kind` takes the run.** A JLC-sourced line that names its batch is
   `part`; only the run-less case falls back to `assembly`.

### What the data actually says

Measured across all 46 cached BOMs on 2026-09-19, because two of these were
assumed wrongly first:

| Fact | Evidence |
|---|---|
| **`extPrice == unitPrice x shopStock`** | 1021 of 1021 priced rows. The money is billed on the supplier's portion only. |
| **`componentSource` has THREE values** | `shop`, `preSale` and `preSaleAndShop`. On SMT026090162303 the mixed rows carry 1,796.16 of the 2,097.28 lump, so "shop only" misses six sevenths of it. |
| **`componentNum` is per PANEL** | A 1-per-board part on a 200-panel order reads 200 while `componentRealCount` reads 800. Never a piece count — the same trap as JLC's order quantity. |
| **`presaleStock` + `shopStock` splits a mixed position** | Holds on 1,223 of 1,326 rows. |

### Consequences

* Good, because a batch's parts are now traceable to the part number, and the
  double charge is reported by the platform instead of found by a person.
* Good, because a hand-written invoice produces identical rows — the itemisation
  is cost lines, not a supplier feed.
* Bad, because 103 rows across 8 orders have supplier numbers that do not add
  up (`presaleStock + shopStock != componentRealCount`, and `freeStock` does not
  close it). Their MONEY is exact — rule 1 holds on every one — so they are
  flagged `supplier_mismatch` and their coverage is reported as unverified
  rather than guessed.
* Bad, because `void_shop_draws` is now the wrong instrument for a position the
  supplier only part-filled: it voids the whole draw where only the supplier's
  share should go. Coverage reports this as `over_drawn`; the tool is not
  changed here.

### The open question, and the assumption taken

**Leftovers are not settled.** The supplier bills a loss allowance — 45 pieces
for a board that used 40 — and whether the remainder is shipped to our consigned
stock or kept is unknown. Until the supplier answers, this records the billed
quantity on the run and pools nothing, which cannot invent inventory. If the
remainder does arrive, it is a pool purchase recorded separately, and no row
written under this decision needs changing.

### Confirmation

`api/tests/costs/test_supplier_parts.py` — twelve cases, including the mixed
source, the panel trap, the flagged mismatch and the double charge. Against the
live register: line 1144 itemised into 20 children totalling 2,097.2801 against
a printed 2,097.28, run 19's direct cost unchanged at 3,150.58, document 139
still reconciling, and `GET /api/runs/19/supply-coverage` reporting 22 of 22
positions `ok` with no unexpected draws.

## Pros and Cons of the Options

### Children charged to the run, never pooled

* Good, because the money lands where it was spent and the pool stays a record
  of stock we actually owned.
* Bad, because a leftover that IS shipped to us later has to be recorded as its
  own purchase.

### Into the pool, then drawn

* Good, because one mechanism would cover every part.
* Bad, because it books stock that was never ours and prices the pool average at
  a one-off order rate; every other batch would then draw at that average.

### Keep the lump

* Good, because nothing changes.
* Bad, because it is the state that lost USD 585.29 on a superseded part and
  needed nine draws voided by hand.

## More Information

Builds on [0037](0037-the-supplier-keeps-the-receipts.md) (the supplier's own
records are the authority) and [0038](0038-a-substitution-belongs-to-the-batch.md)
(`RunSubstitution.supplied_by` already names which side a position is expected
from). Revisit when the leftovers question is answered, or if a supplier stops
publishing a per-part breakdown — the hand-typed path is then the only one.
