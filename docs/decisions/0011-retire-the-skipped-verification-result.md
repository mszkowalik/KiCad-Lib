---
status: "accepted"
date: 2026-09-13
decision-makers: Mateusz Kowalik
consulted: Jaravis (agent), who surfaced the usage numbers
informed: anyone writing a verification, by hand or through the agent tools
---

# Retire the `skipped` verification result, and make `na` carry a reason

## Context and Problem Statement

A checklist item could be answered `checked`, `na`, `skipped`, `failed` or
`flagged`. `skipped` meant "this item applies, but I could not verify it", and
`na` meant "this item does not apply". Nobody read them that way — including the
person who designed the axis, who expected `skipped` to mean "does not apply"
and unchecked work to be simply unmarked.

The consequence was not cosmetic. Agents reached for `skipped` to mean *"I did
not re-open the datasheet on this pass"*, even when the item was already
verified and provably unchanged, because the word invited it. Measured on the
running platform on 2026-09-13: **138 `skipped` answers, every one carrying
reason `unstated`**, and **45 subjects sitting at `partial` because of one**, of
which **38 had nothing else open**. Reading all 54 skip notes on those subjects,
~36 said some version of "no datasheet in scope for this structural sweep" and
many added that a prior datasheet-backed check had already confirmed the item.

Two subjects were genuinely unverifiable (`LE310X1`, `LE910R1` — Telit puts the
hardware design guide behind a registration gate). Four were a class exemption
(the `8P8C` family, whose pin names are deliberately blank because the base
symbol is shared across RJ31–RJ61 variants).

The reason codes built to explain skips (`html_datasheet`, `no_land_pattern`, …)
were reachable only from the review card. `record_verification` never had a
`reason` argument at all, so every agent-written skip — which is nearly all of
them — landed unexplained, and the health panel's "why items are skipped"
analysis showed a single bucket of 138.

## Decision Drivers

* The vocabulary has to mean what a reader thinks it means without a lookup.
* An item nobody has answered and an item somebody could not answer produce the
  same state (`partial`) and the same next action (go and answer it).
* "Which way does this not apply" is worth aggregating; "somebody typed a word"
  is not.
* History must stay readable. 138 rows carry the retired value.

## Considered Options

* Rename `skipped` to "cannot verify" and keep both results.
* Relabel in the UI only, leaving the stored value and the model alone.
* Retire `skipped`, and move the reason requirement onto `na`.

## Decision Outcome

Chosen option: **retire `skipped`, and move the reason requirement onto `na`**,
because the state it produced was already identical to leaving the item
unanswered, so the result carried no information the absence of an answer does
not — while costing the ambiguity that parked 38 subjects at `partial`.

The vocabulary is now `checked` | `na` | `failed` | `flagged`, and an item
nobody can verify is LEFT UNANSWERED.

`na` requires a `reason` from `feature_absent` | `kind_exempt` | `waived` |
`other` — **above the machine tier only**. `services/validator.py` answers `na`
in a dozen places ("no SMD pads", "no vias", "no courtyard graphics") with a
free-text note and no code, and requiring one there would fail every publish.

### Consequences

* Good, because an agent has nowhere left to park an unanswered question: it
  must answer on the evidence it has, mark `na` and say which way, or leave the
  item open and visible.
* Good, because `na` is the result that CLOSES an item, so it is the one that
  earns a mandatory justification.
* Good, because no subject changed state: `skipped` and unanswered both read
  `partial`, before and after.
* Bad, because the library loses the ability to record "I investigated this and
  the document does not answer it" as a distinct fact. The two genuinely
  unverifiable symbols now look the same as ones nobody has opened. Accepted:
  the note on the record still says so in prose, and the case is rare.
* Bad, because 138 stored rows now carry a value the write path rejects. They
  are read as unanswered and reported separately (`legacy_skipped_items` on the
  health endpoint) rather than migrated, so the open work stays visible.

### Confirmation

* `review.RESULTS` no longer contains `skipped`; `record_check` refuses it.
* `state_from_record` counts a stored `skipped` as unanswered, so a subject
  carrying one still reads `partial` — verified against the 45 subjects that
  hold one.
* `record_check` refuses `na` from an agent or a human without a reason from
  `NA_REASONS`, and accepts it from the machine tier without one. A publish
  running the full validator still succeeds.
* The health endpoint reports `top_na_items`, `na_reasons` and
  `legacy_skipped_items`; the review card offers Checked / N/A / Flag and no
  Skip button.

## Pros and Cons of the Options

### Rename `skipped` to "cannot verify"

* Good, because it keeps the "I looked and the document is silent" signal,
  which stops the next agent re-reading the same dead end.
* Bad, because it keeps two results whose STATE is identical, so the
  distinction has to be taught rather than being obvious.
* Bad, because it needs a migration of 138 rows to earn a word change.

### Relabel in the UI only

* Good, because it is free and reversible.
* Bad, because the database keeps a word that reads wrong to anyone querying it,
  and the agent tool surface is where most of the misuse happened.

### Retire `skipped` (chosen)

* Good, because the vocabulary shrinks to four results that each mean one thing.
* Good, because "unmarked" already carried the meaning, at no cost.
* Bad, because the distinction between "unexamined" and "examined, undocumented"
  survives only in prose.

## More Information

* [../reference/review-axis.md](../reference/review-axis.md) — the axis itself.
* `api/app/services/review.py` — `RESULTS`, `LEGACY_RESULTS`, `NA_REASONS`.
* Revisit if the "examined, and the document does not answer it" case becomes
  common enough to want its own result again. The honest signal for it today is
  a `custom:` item recording what was looked for and not found.
