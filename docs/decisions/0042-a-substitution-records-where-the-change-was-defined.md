---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# A substitution's `source` records WHERE the change was defined, not who decided it

## Context and Problem Statement

[0038](0038-a-substitution-belongs-to-the-batch.md) item 9 says "**WHO DECIDED**
and WHO SUPPLIED are two fields", and `RunSubstitution.source` was documented as
"`supplier` — the factory changed it". The Materials tab printed that reading
back as a pill: **"factory decided"**.

It is wrong, and the user said so on 2026-09-19: *"i decided about change in
their web page when i selected components"*. The common case is us picking a
different part on the supplier's site while placing the order. Our decision —
made outside the schematic.

The two axes 0038 separated are still right and still needed. Only the name of
the first one was wrong, and a wrong name propagates: it reached the model
docstring, the decision record and the screen, and it told a reader to take the
question to the factory when the answer was in our own order.

## Decision Drivers

* `matchType: "update"` is JLC saying *a human changed this line*. It does not
  say WHICH human, and the platform cannot know.
* The distinction that is real and checkable is where the change LIVES: in the
  supplier's order, or recorded here. That is what the platform observed.
* A field whose name asserts more than the evidence supports will be believed.

## Considered Options

* Re-describe `source` as where the change was defined, keeping its values.
* Rename the values to `order` / `recorded`.
* Add a third value for "we chose it on their site".

## Decision Outcome

Chosen option: "Re-describe it, keep the values".

1. **`source` answers WHERE, not WHO.** `supplier` — the change lives in the
   supplier's own order and was read from their BOM. `us` — somebody recorded it
   here by hand.
2. **The stored values do not change.** They are already correct AS VALUES; only
   their description was wrong. Renaming would need a migration and would buy
   nothing — and `supplier` still names where the evidence came from.
3. **The screen says what was observed**: "chosen in the order" and "recorded
   here", never "factory decided".
4. **`supplied_by` is untouched.** Whose parts went on the board is a genuinely
   separate question, and 0038 is right about that. The two cross: a part chosen
   on the supplier's order can still come out of our own stock.

### Consequences

* Good, because the pill no longer sends a question to the factory that only our
  own purchasing can answer.
* Good, because no data moves: this is a correction to what existing rows MEAN.
* Neutral, because "who decided" is now unrecorded. Nothing ever recorded it —
  the field only ever held where the change was seen — so nothing is lost. If it
  is worth knowing, it needs a new field and a person to fill it in.

### Confirmation

`RunSubstitution.source`'s docstring states WHERE and names the correction. The
Materials tab reads "chosen in the order" / "recorded here" with a tooltip that
says the part was usually picked by us while placing the order. No stored value
changed: batch 8's C2 is still `source="supplier"`.

## Pros and Cons of the Options

### Re-describe, keep the values

* Good, because it is a documentation fix for a documentation error.
* Bad, because `supplier` reads like "the supplier did it" until you read the
  docstring — which is how this happened.

### Rename the values to `order` / `recorded`

* Good, because the value would say what it means.
* Bad, because it needs a migration, and every reader of a historical row would
  have to know both spellings.

### Add a third value

* Bad, because the platform cannot observe who decided. It would be a field only
  a person could fill in, and nobody asked for one.

## More Information

Corrects item 9 of [0038](0038-a-substitution-belongs-to-the-batch.md), which
remains accepted: the two-field split it introduced is unchanged, and only the
name of the first axis is restated here. Revisit if a supplier ever publishes
who made a BOM change — JLC does not.
