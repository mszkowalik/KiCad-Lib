---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# The bench says what it already knows, and only blocks what would be false

## Context and Problem Statement

The MAC read is the one moment the platform holds both facts at once: what is on
the fixture, and what it already believes about that unit. Until now
`_register_device` said nothing. It found the row or created one, in silence.

Every disagreement therefore had to be discovered months later by counting
stock. On 2026-09-17 the bench had **Batch 8** selected — a batch whose boards
had not been delivered, whose status is still `planned`, and which has built
nothing — and 31 units were filed against it before anyone noticed. The repair
took a `rebatch` call, a decision record
([0029](0029-the-batch-on-a-produced-event-is-correctable.md)), a one-off SQL
statement for the 50 programming attempts left behind, and this week.

The platform knew at unit one. It knew Batch 8 had never taken a device. It
said nothing, because nothing was ever asked.

## Decision Drivers

* A check that fires on the ordinary case is worse than no check. **5,369 of
  5,538 devices read `shipped`** — a rule that stopped on "this unit is not in
  stock" would stop on almost every reflash, and operators would learn to
  defeat it.
* The bench must not become a gate. A refusal costs a production line more than
  a wrong row costs the books, unless the row is false.
* The facts differ in kind. "This unit is at a customer" is a question for a
  person. "This unit belongs to another project" is not a question at all.
* `DevicePresence` may inform but never decide — its own docstring says nothing
  in it may gate a business decision.

## Considered Options

* Two levels: block only what would be false, acknowledge the rest.
* Block on the batch's `status` as well, so a `planned` batch cannot be
  programmed against.
* Report everything afterwards, on a page.

## Decision Outcome

Chosen option: "Two levels", in `services/flasher/bench_checks.py`, called from
`_register_device` and from `_store_identity`.

1. **Exactly one check blocks: `wrong_project`.** The device row names a
   project the run is not filed under, so continuing writes a unit into a
   project it does not belong to. Nothing else is reported once it fires — past
   that point it is the wrong device and the rest is noise.
2. **Everything else is a notice the operator takes**, with their name against
   it. `not_in_stock`, `condition_not_ok`, `built_in_another_batch`,
   `online_elsewhere`, `first_unit_of_batch`, `batch_full`, `settled_batch`,
   `duplicate_imei`, `duplicate_iccid`.
3. **The reason box is offered and never required** (user decision
   2026-09-19). A rule that demands a sentence to get past a dialog produces
   sentences like ".", not reasons.
4. **Every notice is an audit row** — `flasher.check.<code>` on the
   `programming_run`, carrying the text, the data and, for a warning, whether
   it was taken and why — and a line in the run log, so it is in the history
   the run already keeps.
5. **`first_unit_of_batch` is the one that answers 2026-09-17.** It fires once
   per batch, on the first device ever filed against it, and says so. It does
   not fire on a batch that is already running, which is every other press of
   the button.
6. **`settled_batch` protects the money.** `good_units` is DERIVED from the
   device records ([0030](0030-good-units-are-counted-not-typed.md)) and
   `ProductionRun.frozen` is a dead legacy column, so a late pass silently
   re-divides a closed batch's whole cost pool. Thirty days without a new unit
   is the line.
7. **The ordinary case is silent.** A new board, in a batch that is already
   running, in the right project, produces no notice at all. That is the test
   the check set has to keep passing.

### Consequences

* Good, because the platform now says what it knows at the moment it can still
  matter, instead of leaving it to a stock count.
* Good, because an acknowledgement is evidence: who continued, past what, and
  when. There was no such record before.
* Bad, because a notice interrupts a bench that is running units back to back,
  and the acknowledgement is a click that can become reflex. That is why the
  ordinary case must stay silent and the list must not grow without cause.
* Bad, because `online_elsewhere` reads a cache that is allowed to be wrong. It
  is a warning for exactly that reason and must never become a block.
* Neutral, because the headless side needs nothing: the bench agent is a local
  HTTP appliance driven by the browser, not a socket client, so the browser is
  the only consumer of `{t:"notice"}`.

### Confirmation

`api/tests/orders/test_bench_checks.py`, eleven tests. The load-bearing ones:
the ordinary case reports nothing; a wrong-project device blocks and suppresses
everything after it; the first unit of an empty batch is flagged; and a unit at
a customer, a faulty unit and a reflash of an older batch's unit are all
warnings and never blocks.

## Pros and Cons of the Options

### Two levels

* Good, because the one refusal is the one case where continuing writes
  something false, and everything else stays the operator's call.
* Bad, because two levels is a judgement per check, and a later check added to
  the wrong level is not obvious from the code.

### Also block on batch `status`

* Good, because `planned` is literally what Batch 8 was on the day.
* Bad, and REJECTED on the data: `status` is free text with no enum, set by
  hand, and **every batch in this platform that has devices is `completed` or
  `done` — none was advanced before its first unit was programmed**. Blocking
  on `planned` would refuse the first real session of every new batch. The
  signal that actually distinguishes the two cases is "this batch has never
  taken a device", which is `first_unit_of_batch`.

### Report afterwards

* Good, because it interrupts nobody.
* Bad, because it is what the platform already did. The stranded decision in
  [0034](0034-stock-moves-when-the-supplier-says-so.md) and the 31 units of
  2026-09-17 were both visible on a page nobody was looking at.

## More Information

* [0029](0029-the-batch-on-a-produced-event-is-correctable.md) — the correction
  path this exists to stop needing.
* [0030](0030-good-units-are-counted-not-typed.md) — why `settled_batch` is a
  money check.
* [0033](0033-the-broker-observes-devices-it-never-commands.md) — why
  `online_elsewhere` informs and never decides.
* Revisit this if the acknowledgement rate on any one code approaches 100%.
  A notice everybody always continues past is not a check, it is a delay.
