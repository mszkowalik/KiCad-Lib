---
status: "accepted"
date: 2026-09-14
decision-makers: Mateusz Kowalik
consulted: Claude Code, which built and measured the change
informed: anyone reading a review state, and anyone adding a check
---

# Conformance is computed on read, not recorded on publish

## Context and Problem Statement

Machine answers were written into `ReviewRecord` like any other verification.
Measured on 2026-09-14, that one choice caused most of the review axis's
awkwardness:

```
answers stored on current versions   6,819
  of which machine                   2,442  (36%)
review records                       3,774
  of which carries                     675
```

Four consequences, all of them familiar:

- **Adding a check re-opened the library.** Publishing `cmp.datasheet_text`
  moved **418 components** from checked to partial in one go, because a stored
  answer cannot backfill. It had to be answered by hand from the very column the
  validator reads.
- **675 carry records** existed largely to move machine answers across version
  boundaries that had not affected them.
- **`recheck_machine_tier`, `POST /reviews/{kind}/{id}/recheck` and
  `POST /checklists/{id}/apply`** were all built to un-stale stored answers, and
  each needed its own button.
- **A check could not be shipped**, which is why four of them sat switched off
  until [0016](0016-severity-and-standing-exceptions.md) gave them a warning
  level.

None of it is a verification. Nobody looked at anything — the code did, and it
will say the same thing again in 20 ms.

## Decision Drivers

* Adding a check must not re-open the library.
* A recomputable answer should not be stored as evidence of a human act.
* A list surface must stay fast: evaluating 439 components at 20 ms each is nine
  seconds.
* Nothing already recorded may be rewritten.

## Considered Options

* **Compute on read, cache against a digest of the inputs.**
* Compute on read with no cache.
* Keep storing, and add a job that refreshes stale answers.

## Decision Outcome

Chosen: **compute on read, cached in `models.Conformance` against a digest.**

- **The row is a CACHE**, in exactly the sense `FootprintVersion.material_sha`
  already is: safe to be missing, safe to delete, never carried, never migrated.
- **`digest` covers everything the answers depend on** — the resolved checklist
  (items, severities, params, `assert`, `when`), the facts those actually read,
  and the live exception ids. Edit a check and every digest in the library
  changes, so the next read recomputes. **Nothing has to remember to invalidate
  anything.**
- **The digest reads facts through their own keys**, never by iterating the
  mapping: `subject_facts` is lazy, and iterating it would compute every derived
  fact on every digest — turning a cache key into the expensive thing it exists
  to avoid.
- **Exceptions are an OVERLAY here, not a write.** Revoking one takes effect on
  the next read, which retires the "an answer written by an exception has to die
  with it before the merge" rule 0016 needed.
- **`state_from_record` ignores machine answers stored in records** and measures
  completeness over JUDGMENT items only. The 2,442 stored answers are not
  deleted — they are what a past record said, and this axis does not rewrite
  history — but they are read as history.
- **A one-click human confirmation no longer hides a machine failure.** It
  vouches for the judgment; a person cannot confirm away something the code can
  still see.
- **List surfaces read the cache without validating the digest**
  (`conformance.cached`), because a stale answer beats no answer on a list and
  the detail view recomputes. A missing row yields `conforms: None`, which reads
  as "not evaluated" and never as "conforms".
- **A background warm-up at startup** fills the cache, for the same reason the
  `material_sha` backfill does. Nothing depends on it finishing.

Deleted with this: `machine_check_on_publish`, `recheck_machine_tier`, the
`/recheck` endpoint, `POST /checklists/{id}/apply`, and both of their buttons.

### Consequences

* Good, because adding a check now re-evaluates the whole library instantly.
  **Measured:** tightening `fp.min_drill` from 0.3 mm to 0.45 mm immediately
  reported **19 failing footprints** across all 212 — no republish, no backfill,
  no button.
* Good, because the carry has 2,442 fewer answers to move, and phase 10 (claims
  with their own dependency) gets much simpler.
* Good, because a new check can never again move 418 subjects at once.
* Bad, because there is now a cache, and a cache is a thing that can be wrong.
  The digest is the mitigation, and `evaluate` is always available to prove it.
* Bad, because a cold row on a list surface reads "not evaluated" until the
  warm-up reaches it. Honest, but it is a state the UI has to handle.
* Neutral, because stored machine answers remain in the records. They cost
  nothing and they are the only evidence of what a past record claimed.

### Confirmation

Verified against the running platform, 2026-09-14:

* `evaluate` takes **20 ms**; the cached read takes **0 ms**. That ratio is the
  entire argument for the cache — 439 components would be nine seconds.
* The warm-up populated **857 rows** (439 components, 206 symbols, 212
  footprints) and the review queue answers in **0.46 s**.
* Tightening a threshold changed the digest and re-evaluated every footprint on
  the next read, finding 19 failures; restoring it put them back.
* `GET /api/reviews/component/296` reports `conforms: false` with judgment
  answered 10/11 — the two tiers counted separately, from two sources.

## Pros and Cons of the Options

### Compute on read, cached against a digest

* Good, because the cache invalidates itself from its own inputs.
* Good, because it removes three pieces of machinery and two buttons.
* Bad, because "computed, but cached" is a sentence that has to be explained to
  every future reader — hence this record and the module docstring.

### Compute on read with no cache

* Good, because there is nothing to be stale.
* Bad, because the review queue would take nine seconds, and the browse page
  and the project review read the same states.

### Keep storing, add a refresh job

* Good, because it needs no new concepts.
* Bad, because it keeps every problem above and adds a job to run. It is what
  `recheck_machine_tier` already was, one level larger.

## More Information

* [0016](0016-severity-and-standing-exceptions.md) — severity and exceptions;
  this changes where an exception is applied.
* [docs/reference/review-axis.md](../reference/review-axis.md).
* `docs/todo.md` rows 7-11 are the rest of the overhaul. Row 10 — claims with
  their own dependency — is the one this most directly unblocks, because the
  carry now moves only judgment.
