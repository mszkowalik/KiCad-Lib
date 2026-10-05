---
status: "accepted"
date: 2026-10-05  # accepted 2026-10-05
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04/05 on tracing device costs to invoices)
---

# A draw takes the cost of the lots it is bound to, oldest first

## Context and Problem Statement

The user, 2026-10-04: "we can have assigned positions from stock to them,
those positions could be somehow linked to original invoices they were from
creating a proper chain link to the costs of the batch. this way we can
properly track costs across runs."

Today only part of a device's cost has that chain. A JLC draw is bound to the
lot JLC named, and a lot is a purchase invoice line
([0034](0034-stock-moves-when-the-supplier-says-so.md)). An invoice position
can be linked to a step ([0060](0060-the-process-is-the-one-source-of-history-materials-and-cost.md)).
Every other draw — a step's enclosure, antenna, carton, leaflet or label, a
prepared part's inputs, a BOM draw — is priced at the company's moving average
on the day, and nothing says which purchase it came from. On the local copy
that is 42 draws worth $29,290, none bound.

The user's answers of 2026-10-05: the device carries the lots' own cost (FIFO),
not the average; the history is bound too, closed batches included, each as a
correction event; a draw the lots cannot cover is refused; and nothing is
deployed until this is built.

## Decision Drivers

* Every unit of a device's cost leads to the invoice line that paid for it.
* The lot ledger and the stock replay agree on what is left
  ([0040](0040-a-purchase-cannot-be-removed-from-under-its-draws.md): the pool
  is guarded on both sides).
* A retroactive recalculation is an explicit job, never a side effect
  ([0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md)).

## Considered Options

* Lot links for tracing only, the price staying the moving average.
* The draw takes the bound lots' cost (FIFO).
* Specific lots chosen by a person at each draw.

## Decision Outcome

Chosen option: "the draw takes the bound lots' cost (FIFO)" (user,
2026-10-05), because the chain is only worth having if the number at its end
is the number the device carries. Choosing lots by hand at each draw would
put a bookkeeping question in front of every bench click.

1. **A draw is bound to lots, oldest first.** The lots are the purchase lines,
   positive adjustments and in-house transfer positions of the stock the draw
   takes from — the batch company's while each company keeps its own
   ([0064](0064-each-company-draws-from-its-own-stock.md)) — dated on or
   before the draw, with room left. A binding is split across lots when one
   does not hold enough. A JLC draw keeps the lots JLC named.
2. **The draw's unit cost is the bound lots' landed cost**, weighted by the
   quantity taken from each.
3. **One picker for every writer**: process steps and bench steps, prepared
   parts' inputs, "Record assembly" for another house, BOM and hand draws,
   JLC warehouse picks, and in-house transfers (a transfer that names no lot
   moves the sender's lots oldest first, so both companies' lots stay right).
4. **A draw the lots cannot cover in full is refused** (409), naming each part
   and how much no lot holds, while `lot_pricing` is on.
5. **The history is bound once, by an explicit job** (admin, dry run first,
   one journal batch): each company's draws in date order are bound oldest
   first and re-priced at lot cost. A closed batch is re-priced too: the job
   is its correction event, the change reads as a variance against its
   `closed_cost_usd`, and its frozen twin share is computed again. Every draw
   no lot covers is listed.
6. **`lot_pricing` is an admin switch, off by default**, and it cannot be
   turned on while any live draw is unbound. Until then nothing changes.

### Consequences

* Good, because a device's own parts lead to their invoices, and a batch's
  cost is the cost of the stock it really took.
* Good, because a missing purchase stops the draw that needs it, instead of
  surfacing months later as negative stock.
* Bad, because every batch's cost and every order's margin moves once, when
  the history is bound — closed batches included.
* Bad, because production can stop at the bench when a purchase is not
  entered yet. That is the point of the refusal, and the message names what
  to enter.
* Neutral, because the moving average stays for planning a batch that does
  not exist yet.

### Confirmation

Tests show that a step draw is bound oldest first and split across lots,
priced at the lots' cost; that a draw the lots cannot cover is refused while
the switch is on; that the history job binds and re-prices draws in date
order, closed batches as a variance, and lists what no lot covers; that the
switch refuses to turn on while a draw is unbound; that a transfer moves the
sender's lots oldest first; and that the register's identities hold before
and after.

## Pros and Cons of the Options

### Lot links for tracing only

* Good, because no cost moves.
* Bad, because the traced cost and the carried cost differ, and the user wants
  the carried one to be the traced one.

### FIFO lot cost

* Good, because one rule prices and traces.
* Bad, because the history must be bound before the rule can apply.

### Lots chosen by hand

* Good, because a person can follow the physical bin.
* Bad, because every draw asks a question nobody can answer at the bench.

## More Information

Extends [0034](0034-stock-moves-when-the-supplier-says-so.md),
[0058](0058-a-process-is-versioned-stages-over-the-pool.md) and
[0064](0064-each-company-draws-from-its-own-stock.md). The lot ledger is
`api/app/services/lots.py`.
