---
status: "accepted"
date: 2026-09-14
decision-makers: Mateusz Kowalik
consulted: Claude Code, which measured the two paths and built the change
informed: anyone reviewing a part, anyone writing an agent that records verifications
---

# "Does not apply" is a standing exception, not an answer

## Context and Problem Statement

Two controls said the same thing, and only one of them lasted.

`na` was an answer on ONE version. An exception was a decision about the PART.
Both meant "this check is not about this subject". Measured on 2026-09-14, on
current versions only:

```
na answers, live            314     (agent 312, human 2)
  of which with a reason      0
standing exceptions, live     0
```

Across all history the split is the same shape: 4,747 `na` answers, 7 of them
written by a human. So the throwaway control is used constantly and the durable
one is not used at all — because the throwaway one was the button on the row.

Every one of those 314 expires at the next version bump, whether or not the edit
had anything to do with the check. That is the same waste
[0016](0016-severity-and-standing-exceptions.md) measured from the other side:
the library held zero waivers while agents had invented 188 private `custom:`
keys to put findings somewhere that lasted.

**And the exception half was half-built.** Granting one on a judgment item
nobody had answered yet did nothing at all. Measured: `fp.model_fit` granted on
footprint 117, item still open, `0/6` answered. [0017](0017-conformance-is-computed-not-recorded.md)
moved the machine tier to a computed overlay and left judgment items on the old
write path in `record_check`, which only runs when somebody saves a
verification. Two mechanisms, one of them silently inert.

## Decision Drivers

* One decision, one control. A second, weaker way to say the same thing wins by
  being nearer the cursor.
* A decision must survive an edit that has nothing to do with it.
* Closing a check must never be mistakable for having verified it.
* Nothing already recorded may be rewritten.

## Considered Options

* **Delete `na` as an answer; "Does not apply" grants an exception.**
* Keep both, and make the exception easier to reach.
* Keep `na`, delete exceptions, and make the carry preserve `na` specially.

## Decision Outcome

Chosen: **`na` is no longer an answer.**

- **The review card sends no `na`.** "Does not apply…" grants an exception, and
  it is offered on ANY judgment item — answered or not — and on a machine
  FINDING. Saying a check is not about this part does not require running it
  first. Refusing it on an open item is exactly what kept `na` alive as the
  weaker second path.
- **The API still ACCEPTS `na`,** and converts it. `record_check` grants an
  exception instead of writing an answer, so no agent breaks. It now needs a
  **note** as well as a reason: the answer outlives its version, and the note is
  the only place the reason will ever live.
- **An agent can never grant "always".** `exceptions.DEFAULT_PIN` pins the
  drawing (`$material_sha`), or for a component its own fields
  (`$property_sha`) — a component's `$material_sha` is the symbol's and the
  footprint's joined together and says nothing about a Value or a datasheet. A
  blanket waiver covering every future version is a decision a person makes
  explicitly, in the card, where the scope is asked.
- **Excused items LEAVE the denominator.** `conformance.evaluate` computes them
  beside the machine answers, into `Conformance.excused`. They are reported as
  their own number, never folded into `answered`: an exception says the question
  is not about this part, never that somebody looked. A part whose whole
  checklist is excused must not read like a part that was judged.
- **Exceptions are applied in ONE place now**, `conformance.evaluate`. The write
  path in `record_check` is gone, and with it the rule that an answer written by
  an exception had to die BEFORE the incoming merge — there is no such answer.
- **No migration.** The 314 live `na` answers stay as history and keep counting
  as answered. They were written without a reason, and inventing one for them
  would be worse than letting them expire.

### Consequences

* Good, because a decision recorded once stays recorded, and the control that
  records it is the one on the row.
* Good, because granting an exception on an open item now works — the bug that
  made "exceptions" look like a feature that did nothing.
* Good, because the health tab can finally count why items are being closed:
  `na_reasons` reads live exceptions, where the reason is mandatory, instead of
  606 rows saying `unstated`.
* Bad, because "does not apply" is now a heavier gesture: three questions, and a
  mandatory note. That is the point, and it is also a reason people may answer
  `checked` instead. The provenance and the `excused` count are what make that
  visible.
* Bad, because agents now write durable decisions. They are pinned, never
  "always", they carry `actor_type: agent`, and a subject closed by them reads
  `checked (agent)` until a person confirms — but nothing stops an agent
  excusing something it should have verified.
* Neutral, because `na` stays readable everywhere as history.

### Confirmation

Verified against the running platform, 2026-09-14:

* Exception granted on the OPEN item `fp.model_fit`: closed immediately,
  denominator `6 → 5`, `excused: 1`. Before the change the same call left it
  open at `0/6`.
* `na` with no note is refused, with the reason:
  `fp.naming: na is a standing exception now, so it needs a note saying why — it
  outlives this version`.
* `na` with a note grants a pinned exception (`this drawing only`) and the
  denominator drops again, `excused: 2`.
* Through the UI, on an OPEN judgment item: three dialogs, then
  `cmp.value_field — EXCEPTION · THIS PART, ALWAYS` and
  `1 item(s) excused by a standing decision`.
* Revoking brings the item back to open on the next read.
* Health now reports machine failures from conformance —
  `fp.courtyard_grid 76`, `cmp.datasheet_text 47` — which record-only counting
  had made invisible since 0017.

## Pros and Cons of the Options

### Delete `na` as an answer

* Good, because it removes a control rather than adding one — the same move
  0016 made with severity.
* Good, because it forces the scope question, which is the safety question.
* Bad, because it is a breaking change for anything that posts `na` without a
  note.

### Keep both, make the exception easier to reach

* Good, because nothing breaks.
* Bad, because this is what shipped on 2026-09-14 and the measurement above is
  the result. Two ways to say one thing means the cheaper one wins, and the
  cheaper one forgets.

### Keep `na`, delete exceptions, special-case the carry

* Good, because it needs no new concepts.
* Bad, because the decision stays on a version, which is the whole problem, and
  it makes an already subtle carry subtler. Rejected once already in 0016.

## More Information

* [0016](0016-severity-and-standing-exceptions.md) — where exceptions came from,
  and KiCad's `drc_exclusions`.
* [0017](0017-conformance-is-computed-not-recorded.md) — the computed overlay
  this extends to judgment items.
* [docs/reference/review-axis.md](../reference/review-axis.md).
