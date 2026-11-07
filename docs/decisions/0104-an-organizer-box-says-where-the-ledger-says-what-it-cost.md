---
status: accepted
date: 2026-11-07
decision-makers: Mateusz Kowalik
---

# Keep the office organizers in their own tables, and let a take write a draw

## Context and Problem Statement

The parts in the office organizers were listed in a Google sheet ("Stany
Magazynowe"): 128 positions, 115 parts, 4,091 pieces. Henry did not know them.
The Stock page compared the whole pool remainder with JLC's count, so a piece in
the office read as a piece JLC had lost (work list row 54: 170 pieces on 3 parts).

The user wants Henry to hold these quantities and to keep them apart from JLC's.
The user also stated three facts on 2026-11-07. Most of these parts go to R&D, and
that use is a stock movement and a cost that no batch pays. Some go to a batch. The
organizers are shared, but the pieces in them belong to a company, and a take asks
which company only when both hold the part.

Rules and traps are in [organizers.md](../reference/organizers.md).

## Decision Drivers

* A take must be a cost, so a box cannot stand apart from the ledger.
* 74 of the 115 parts have no purchase outside JLC in Henry, so they have no price.
* A move between boxes is not a stock event, and it must not touch the money.
* A lot's remainder does not say where the pieces are: draws take the moving average
  and most bind no lot.

## Considered Options

* Two new tables, `organizer_boxes` and `organizer_moves`, where a take and a count
  also write a draw or an adjustment in the material ledger
* A plain inventory with no link to the ledger
* Location as a property of a lot, as the question in
  [the ledger design](../material-ledger/design.md) section 10 proposed
* Keep the sheet and read it from Henry

## Decision Outcome

Chosen option: two new tables, because they give the box and the money one write
each and keep every money path unchanged.

* A balance is keyed by box, item and company, and is the sum of its moves.
* A take for R&D writes a draw with `basis="research"` and no batch. A take for a
  batch charges that batch. A take for a crafted batch moves the box only, because
  the process steps draw the parts (decision 0060).
* A count is absolute. Pieces it finds come from what the pool holds outside JLC
  and outside the boxes. The rest enters at zero value. Pieces it loses are written
  off as `miscount`.
* The Stock page compares with JLC the pool remainder less the boxes.

The other options:

* **A plain inventory** was the first proposal. The user refused it: a take must be
  a stock movement and a cost.
* **Location on a lot** needs a row a purchase lot does not have (a purchase lot is
  its invoice line, decision 0097). A move between boxes would then write to the
  money tables. Pieces no purchase covers would still need a home.
* **The sheet** would stay a second source of truth, and a server read of it needs a
  Google credential on the deployment.

### Consequences

* Good, because row 54 closes with no stock adjustment, and a real loss at JLC still
  shows.
* Good, because R&D use has a date, a reason, a company and a value, and it does not
  read as an order that waits for a batch.
* Bad, because a piece with no purchase costs 0, so R&D cost is a floor for those parts.
* Bad, because a batch's draw that was not made from a box leaves the box as it was.
  Somebody must take from the box as well, or the two drift. A count corrects it.
* Bad, because a count looks for free pieces across both companies. With
  `stock_per_company` on, a box can claim pieces of the other company's pool, and
  a take then refuses until the count or a transfer corrects it.
* Neutral, because stock is a cost when bought in the company's books (decision
  0068), so R&D use adds nothing to them.

### Confirmation

`api/tests/costs/test_organizers.py`. `test_pieces_in_a_box_are_not_missing_from_jlc`
is row 54. `test_research_does_not_read_as_waiting_for_a_batch` and
`test_a_crafted_batch_is_drawn_by_its_steps_not_twice` hold the two ways a take could
count money wrongly.
