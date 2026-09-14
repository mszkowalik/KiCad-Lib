---
status: "accepted"
date: 2026-09-14
decision-makers: Mateusz Kowalik
consulted: Claude Code, which built and measured the change; KiCad's own DRC/ERC model
informed: anyone reviewing a part, and anyone adding a check
---

# A check has a severity, and a subject can carry a standing exception

## Context and Problem Statement

Two measurements, taken the same day, describe one problem from both ends.

**A check could only pass or fail.** A `failed` item drove the whole subject to
"issues", full stop. So four checks — `cmp.property_values`,
`cmp.base_symbol_allowed`, `sym.sim_link`, `cmp.sim_params` — shipped *switched
off*, not because they were wrong but because turning a live machine item on
re-opens the library: publishing `cmp.datasheet_text` had moved **418
components** from checked to partial in a single publish. "Off" was standing in
for "on, but not urgent", and there was no way to say the second thing.

**And a decision could not be kept.** The library held **zero** `na (waived)`
answers, while agents had invented **188 distinct `custom:` keys**, 150 of them
used exactly once, every one written by an agent and none by a human. Nobody was
refusing to record decisions. A waiver was an answer on ONE version, so a pad
move refused the carry and took it away, and nobody writes a waiver they will
have to write again next month. The `custom:` keys are what that pressure
produced: 150 unfiled requests for somewhere durable to put a finding.

The skills say the same thing from the other side. `conventions-footprints`
records that the SOT-23 pitch decision — 0.95 mm drawn at 1.00 mm, deliberately
— has been "re-discovered and filed as a defect" by **three separate
verification passes**.

## Decision Drivers

* A new check must be shippable without turning the library red.
* A decision recorded once must stay recorded, and must not silently cover an
  edit nobody reviewed.
* One control per decision. A switch beside a severity is two controls for one.
* Nothing already recorded may be rewritten.

## Considered Options

* **Copy KiCad's model**: a severity per rule, and exclusions as a list keyed on
  the finding.
* Keep pass/fail and manage the noise by leaving checks switched off.
* Make a waiver a per-version answer that the carry treats specially.

## Decision Outcome

Chosen: **copy KiCad's model.** Both halves are things it has shipped for years,
and the convergence is worth more than an invention.

### Severity

`severity` on a checklist item — `error` / `warning` / `ignore`, default
`error`. It is **one control with three values, not a switch beside a
severity**: `ignore` IS "off", which is what the retired `disabled: true` said.
`checklists.severity_of` still reads the old flag, because a checklist version
is immutable and rewriting one would change what a past verification was
measured against; `migrate_severities` converts stored rows, and the four
seeded-off checks became **warnings**, which is what "off" meant.

**The severity is stamped on the ANSWER when it is written**, not read back from
today's checklist — otherwise editing a checklist would silently rewrite what a
past record means. `state_from_record` counts warning-level failures separately:
they never make a subject `failed`.

### Standing exceptions

`review_exceptions` — append-only, `subject_id` is the **PART, never a
version**, `note` required.

`depends_on` is KiCad's idea exactly: an exclusion names the rule AND the items
it fired on, and survives every edit that does not touch them. Here it holds
`{fact: value}` captured from `checklists.subject_facts` at grant time, and the
exception is live while every one still holds:

- `{}` — this part, always. A decision about the part.
- `{"$material_sha": "…"}` — this drawing only. Dies when the copper moves.

**The scope is asked, never inferred.** A blanket waiver silently covering a
future edit is the failure this exists to prevent, so `grant` takes the facts to
pin rather than guessing, and pinning a fact the subject has not got is refused
rather than producing an exception that is stale the instant it is written.

Two rules that took a bug each to get right:

1. **Applied in ONE place** — `review.record_check`, after the tier merge. Every
   answer in the system arrives through that function, so the validator, the
   agent and the review card are covered by one rule and nothing can write an
   answer that bypasses a recorded decision. The finding it replaces is kept on
   `superseded`.
2. **An answer written by an exception dies with it, and must die BEFORE the
   incoming answers merge.** The exception writes at the human tier, so the tier
   rule blocks the machine from replacing it; dropping it afterwards left the
   item unanswered until some later pass, which made "revoke" look like a button
   that half worked. Dropped first, the machine re-answers on the same pass.

The item is left OPEN rather than restored to its old finding: the machine
re-answers its own keys immediately, and a judgment item genuinely needs
deciding again, because the decision that closed it was withdrawn.

### Consequences

* Good, because a check can now ship as a warning — the precondition for moving
  ~20 rules out of the convention skills without turning the library red.
* Good, because a decision survives the version. The SOT-23 case stops being
  re-discovered.
* Good, because "why is this closed" has an answer with a name, a date, a note
  and a scope on it, instead of being invisible or living in a private
  `custom:` key.
* Bad, because an exception scoped `always` is a real loaded gun: it covers
  every future version of that part. The note is mandatory and the scope is
  explicit, but nothing stops somebody choosing it carelessly.
* Neutral, because the retired `disabled` flag is still read. It is one function
  (`severity_of`) and it keeps every past record honest.

### Confirmation

Verified against the running platform, 2026-09-14:

* `state_from_record`: an error-level failure gives `failed`; a warning-level
  failure gives `checked` with `warnings: 1`; an answer carrying no severity —
  every row written before today — reads as `error`.
* The migration left **0** items carrying `disabled`, and the four formerly-off
  checks are warnings.
* Granting `cmp.datasheet` on `RH-5015` turned an agent's `flagged` into
  `na (waived)` with the flag kept in `superseded`, and the state moved from
  `failed` to `partial`.
* Revoking it brought the machine finding straight back — `failed`, with its
  real note — in the same request.
* `stale_reason` returns None while the pinned fact holds, names the change when
  it moves, and treats a fact that can no longer be READ as changed.
* Pinning a fact the subject has not got is refused 422.

## Pros and Cons of the Options

### Copy KiCad's model

* Good, because both halves have years of use behind them in a tool these users
  already know, including the identity rule for an exclusion.
* Good, because severity replaced a control rather than adding one.
* Bad, because it is two features at once, and the second only pays off if
  people actually use it — the thing the old waiver failed at.

### Keep pass/fail, leave new checks switched off

* Good, because it is free.
* Bad, because it is what produced the four off-by-default checks, where "off"
  meant "on, but not urgent" and nobody could tell the difference from "we
  decided against this".

### A waiver the carry treats specially

* Good, because it needs no new table.
* Bad, because it keeps the decision on a version, which is the whole problem.
  Special-casing the carry would make an already subtle rule subtler.

## More Information

* [0014](0014-a-check-carries-its-own-configuration.md) and
  [0015](0015-a-check-says-which-subjects-it-is-about.md) — a check's settings
  and its applicability; this adds what a failure MEANS and what one subject may
  be excused from.
* [docs/reference/review-axis.md](../reference/review-axis.md).
* `docs/todo.md` rows 4 and 5 are this record; rows 6-11 are the rest of the
  overhaul it unblocks.
