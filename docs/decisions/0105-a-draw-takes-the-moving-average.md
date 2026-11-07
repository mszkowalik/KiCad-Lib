---
status: accepted
date: 2026-11-07
decision-makers: Mateusz Kowalik
---

# Price every draw at the moving average, and remove FIFO

## Context and Problem Statement

Decision [0073](0073-a-draw-takes-the-cost-of-the-lots-it-is-bound-to.md) added a
picker that binds a draw to the oldest lots and a switch, `lot_pricing`, to turn it
on. The switch never went on in production, so every draw since took the moving
average, and the picker stayed as code and as an open question. The user decided on
2026-11-07 that FIFO goes for good.

The office organizers made the cost of keeping it plain. The oldest lot of a part
says nothing about the place of its pieces, so FIFO could charge a JLC assembly with
pieces from an office box, or a hand build with pieces at JLC.

## Decision Drivers

* Nobody states which lot a counted part came from, so a FIFO binding is a guess
  written down as a fact.
* A switch that never goes on doubles every test and every sentence of the rules.
* A draw must not be refused because a lot record is missing while the pool and the
  shelf hold the part.

## Considered Options

* Remove the picker, the switch and the history job
* Keep the switch off and leave the code
* Turn the switch on and teach the picker about places

## Decision Outcome

Chosen option: remove them, because the moving average is what production has always
used, and nothing can pick the wrong lot once nothing picks.

* Every draw takes the pool's moving average as of its date. `check_shortages` stays
  the one refusal.
* **Bindings stay.** JLC names the lots of what it drew, a transfer may name a lot, a
  prepared part always takes a named lot, and the history job of 2026-10 bound the
  older draws. Their prices stay as written, and the guards that protect a bound lot
  stay (`lots.bound_problems`, `check_lot_capacity`, the undo's stock check).
* A draw that shrinks gives back its newest bindings. A draw that grows binds nothing.
* `POST /api/companies/lot-history`, its Admin card and the `lot_pricing` setting are
  gone. A value stored for that setting is ignored.

The other options:

* **Keeping the switch off** leaves a second pricing rule that nothing exercises in
  production, and a question that returns.
* **A picker that knows places** still guesses, and it needs a place on every lot,
  which [0104](0104-an-organizer-box-says-where-the-ledger-says-what-it-cost.md)
  decided against.

### Consequences

* Good, because one rule prices every new draw, and a missing lot record cannot stop
  the bench.
* Good, because this removes about 400 lines and a whole class of refusal.
* Bad, because a part's real price differences between purchases are averaged. The
  landed cost of each purchase stays on its invoice line.
* Neutral, because draws already priced at their lots keep that price.

### Confirmation

`api/tests/costs/test_lot_bindings.py` holds the guards on draws that keep their lots
and `test_a_step_draw_takes_the_average_and_holds_no_lot`.
`grep -rn "lot_pricing\|FifoPicker" api/app web/src` finds nothing.
