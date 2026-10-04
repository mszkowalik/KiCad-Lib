---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (a code review of decision 0064 on 2026-10-04)
---

# Write the in-house transfer when a batch takes the other company's stock

## Context and Problem Statement

[0064](0064-each-company-draws-from-its-own-stock.md) item 5 refused to charge
a JLC order to a batch while a draw of the order had taken the other
company's stock, until a person wrote a transfer. A review on 2026-10-04 found
that this could never end: a transfer did not change the company stamped on
the draw, so the charge stayed refused after the transfer existed. It found
five more defects of the same kind:

* a transfer named a lot but left the receiver's draws bound to that lot, so
  the history plan moved the lot a second time;
* the history plan counted a lot move twice in the receiver's balance;
* a lot that is a stock adjustment was always refused as a transfer source;
* in the one shared pool (switch off) a transfer re-priced the part;
* a batch moved to the other company kept the old company's stamp on its
  draws and losses.

## Decision Drivers

* A batch draws its own company's stock, and the record says so
  (0064 items 1 and 5).
* JLC names the lot each assembly order consumed. That evidence decides which
  company's stock left, and the books must agree with it.
* No stock is counted twice, in a quantity or in a lot.
* While the companies share one pool, a transfer changes no figure.

## Considered Options

* Keep the refusal, and re-stamp a draw when a person writes the transfer.
* Write the transfer as part of the charge or the move that needs it.

## Decision Outcome

Chosen option: "write the transfer as part of the charge or the move",
because the lot binding already says which company's stock left and which
company must receive it. Asking a person to type that again adds work and
adds a way to get it wrong. The first option also needs a rule for which
draws a transfer re-stamps, which is the same rule as the chosen one.

1. **`transfers.cover_draws` makes draws a company's.** A unit bound to the
   other company's lot moves by in-house transfer first. A transfer already
   written into that company for the part, on or before the draw, with room
   no draw is bound to, is used first: the binding moves onto it, and a
   transfer that named no lot takes the lot. Otherwise a new transfer moves
   it, at the lot's cost and dated with the draw. Every other unit, and every
   unit a written transfer gave, must be in the receiving company's stock on
   the draw's date. Then each draw is stamped with that company. Refused (409)
   when either company does not hold the stock, naming each short part and
   whose stock it is.
2. **Three writes end in it.** Charging a JLC order to a batch
   (`jlc_apply.charge_draws`, and an order with no draws yet is drawn first,
   then charged), moving a batch to the other company (its draws, its steps'
   draws and the losses charged to it go with it), and naming the company of
   an uncharged draw by hand (`PATCH /api/consumption/{id}/company`). While
   the switch is off, each one only stamps the company.
3. **A transfer that names a lot takes the receiver's draws bound to it**,
   oldest first, from the transfer date on, up to the moved quantity. A
   binding is split when only part of it moves. The capacity check of the lot
   counts the moved bindings by the lot's own key, so a lot that is a
   positive adjustment moves like a purchase.
4. **The history plan counts each move once.** A lot move is a purchase of
   the receiver and a draw of the sender in the replay, and the draw itself
   stays whole. A transfer already written that moved the part to the same
   company, with the same lot or no lot, and with room no draw is bound to,
   counts as moved: writing the history moves the binding onto it.
5. **The one pool leaves transfers out on both sides.** With no company
   named, `run_actuals._pool_events` drops the transfer's positions and the
   sender's draws. The lot ledger still reads them, because a transfer's
   position is a lot.
6. **A transfer stays a whole.** Deleting the sender's draw alone is refused,
   a transfer cannot be corrected, a transfer names each lot once, and
   `transfer` is no document type a person or an import may write.
7. **A correction has its original's buyer**, at creation and after, and a
   loss charged to a batch is its company's.

### Consequences

* Good, because a charge, a batch move and a hand-named draw leave the books
  consistent in one write, and the journal can reverse each of them.
* Good, because the lot ledger and the quantity replay agree: no lot is drawn
  twice after a transfer.
* Bad, because a charge can now write documents a person did not type. Each
  one is numbered, says which charge wrote it, and can be reversed on the
  Transfers page.
* Bad, because a transfer that took the receiver's draws cannot be reversed
  until those draws are reversed. The journal batch of the charge that wrote
  it puts both back. A batch move is not reversed from the journal, because
  the batch's own company is not a journalled row: the batch is moved back on
  its page, which runs the same checks the other way.

### Confirmation

Tests in `api/tests/costs/test_company_stock.py` show that a manual lot
transfer takes the receiver's draws and the history plan then proposes
nothing more, that a partial transfer splits the binding, that a lot move and
a later unbound draw give one lot transfer and one balance transfer, that an
adjustment lot moves, that the one pool keeps its average, that a charge
writes the transfer and stamps the draws, that a moved batch takes its draws
and losses and is refused when the new company does not hold them, that an
uncharged draw gets its company, that the backfill reads a pick's company
from its lot, and that a transfer document cannot be typed by hand.

## Pros and Cons of the Options

### Keep the refusal

* Good, because nothing is written that a person did not type.
* Bad, because the person types what the lot binding already says.

### Write the transfer for the charge or the move

* Good, because the evidence decides, once.
* Bad, because a charge writes documents of its own.

## More Information

Refines items 5 and 8 of
[0064](0064-each-company-draws-from-its-own-stock.md). The rules are in
[docs/reference/companies.md](../reference/companies.md).
