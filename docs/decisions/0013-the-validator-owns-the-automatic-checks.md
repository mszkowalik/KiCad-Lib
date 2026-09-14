---
status: "accepted"
date: 2026-09-13
decision-makers: Mateusz Kowalik
consulted: Claude Code, which built and measured the change
informed: anyone editing a checklist, and anyone writing a verification by hand or through the agent tools
---

# The validator owns the automatic checks, and a checklist switches them on or off per category

## Context and Problem Statement

A checklist item carried `machine: true` to say "the validator answers this one
on publish". Two things followed from that, and both were wrong.

**The wording of an automatic check was typed by hand.** A machine item was an
ordinary row in the checklist editor: a free-text key, a free-text description,
and a checkbox. The checkbox was greyed out for a key `services/validator.py`
does not implement, which stopped the worst failure (an item nobody can ever
answer), but nothing kept the TEXT in step with the code. The editor showed a
sentence a person wrote about a check the validator performs, and a reviewer
reading a rule believes the sentence.

**A checklist could add a check, and could never remove one.**
`checklists.resolve` merges the base list for a kind with every category-scoped
list on the part's category path, most specific winning a key collision. The
merge is additive, so a category list could add an item and could reword one,
but it had no way to say "the base list asks for this and my parts have not got
the thing it asks about". The category editor also never showed what it
inherited, so an override meant retyping a base key exactly.

The result, reported by the owner on 2026-09-13: a great many components,
symbols and footprints each carry one or two standing exceptions to a rule, and
every one of them has to be reviewed again on every automatic verification.
There was no way to say a rule does not apply to a family of parts — only to
answer its finding, one part and one version at a time.

## Decision Drivers

* An automatic check's description must be a statement about the code, not a
  note somebody wrote next to it.
* A category list has to be able to MODIFY what it inherits, not only extend it,
  or a standing class-wide exception has no home.
* Switching a check off has to actually turn something off. A machine answer for
  a key the checklist does not carry is stored as a CUSTOM item, and a `failed`
  custom item pins the whole subject at "issues" — so a switch that only edits
  the list would change nothing at all.
* A checklist edit must never rewrite a verification that already happened
  (the `ReviewRecord.checklist_items` snapshot rule).

## Considered Options

* **The validator is the catalogue, and the checklist is a switchboard.**
* Keep machine items as free text, and add a validation step that compares the
  stored text to the code.
* Leave the checklist alone, and record a standing exception per part instead.

## Decision Outcome

Chosen option: **the validator is the catalogue, and the checklist is a
switchboard**, because it makes the one honest source of an automatic check's
meaning the module that performs it, and because the same `disabled` marker that
switches a check off for a category is what a class-wide exception needs.

Four parts:

1. **`validator.MACHINE_CHECKS` is the catalogue** — key, text and optional hint
   per subject kind. `MACHINE_KEYS` is derived from it, so every existing caller
   keeps working. `GET /api/checklists/meta` serves it, the editor renders it
   read-only with a switch, and `routers/reviews._validate_items` REWRITES a
   machine item's text and hint from it on every save. A checklist stores the
   key, the flag and whether the check is on.
2. **`disabled: true` on an item means OFF at this level and below.**
   `checklists.resolve` returns `items` (what the subject is measured against)
   and `disabled` (what a list on the path switched off). A more specific list
   wins either way, so a category item without the marker switches a base item
   back on.
3. **The resolved checklist is the validator's switchboard.**
   `review.machine_check_on_publish` resolves the list for the subject and
   passes the enabled machine keys to `validator.validate(..., only=)`. An
   answer for any other key is dropped rather than stored as a custom item.
   `record_check` additionally DROPS a switched-off key from the merged answers,
   because records are cumulative and a `failed` recorded before the switch
   would otherwise be copied forward for ever.
4. **`POST /api/reviews/{kind}/{id}/recheck` and `POST
   /api/checklists/{id}/apply` re-run the machine tier** outside a publish — one
   subject, or every subject a checklist governs. Until now
   `machine_check_on_publish` was the only caller of the validator and it runs
   inside the publish transaction, so the only way to refresh the automatic
   answers was to publish again, which drops every agent answer the new version
   cannot carry. A re-run writes at the machine tier only and closes no queued
   review request, so it is not a verification and cannot overwrite one.

### Consequences

* Good, because an automatic item's description can no longer disagree with the
  code that answers it, in either direction.
* Good, because a class-wide exception is now recorded once, on the category,
  instead of being re-answered on every part and every version.
* Good, because the review card and `get_review_checklist` report `switched_off`
  rather than hiding it — "why does this part not get that check" is answerable
  where the part is.
* Good, because the platform finally has a way to refresh the machine tier
  without publishing, which closes a gap recorded in
  [review-axis.md](../reference/review-axis.md) since 2026-08-25.
* Bad, because switching a check off DELETES the answers it already had on the
  next record for that subject, including an agent's or a human's answer on that
  key. That is the intended reading of "this check does not apply here", and the
  superseded chain plus the audit trail keep the history, but it is destructive
  and the editor says so before it runs.
* Bad, because `POST /api/checklists/{id}/apply` walks every subject of a kind
  and re-runs the validator on each. It is an explicit button, not a background
  job, and on the component base list that is ~420 validator runs.
* Neutral, because nothing already recorded is rewritten. A review record still
  snapshots the list it was measured against, so an old record keeps expecting a
  since-disabled key until a re-run replaces it.

### Confirmation

Verified against the running platform on 2026-09-13:

* `PUT /api/checklists/{id}` with a machine item carrying the text
  `"whatever the client says"` stored
  `"LCSC Part matches C<number>"` — the registry text, not the client's.
* A category list for `TestPoints` switching off `cmp.lcsc_format` (automatic)
  and `cmp.base_symbol` (judgment) produced `resolve` = 12 items + 2 disabled,
  and `GET /api/reviews/component/296` reported both under `switched_off` with
  `cmp.lcsc_format` gone from `items`.
* `POST /api/reviews/component/296/recheck` dropped both switched-off keys from
  the merged record and left all nine remaining agent answers intact, with the
  machine tier unable to overwrite any of them. The test record was revoked and
  the scratch checklist deleted; component 296 is back on record 3172.

## Pros and Cons of the Options

### The validator is the catalogue, and the checklist is a switchboard

* Good, because the description of an automatic check has exactly one home, and
  it is the module that performs it.
* Good, because `disabled` serves two needs with one mechanism: switching an
  automatic check off, and marking an inherited judgment check inapplicable.
* Neutral, because a category-scoped switch only reaches COMPONENT checks.
  Symbols and footprints carry no category, so `fp.*` and `sym.*` can be
  switched only on their base list, for every part at once.
* Bad, because adding an automatic check now means editing two places in the
  same module — the registry entry and the branch that answers it.

### Compare the stored text to the code

* Good, because it needs no change to the data model.
* Bad, because it reports a problem instead of preventing one, and the thing it
  reports is a sentence somebody has to fix by hand in a UI.
* Bad, because it leaves the switchboard problem entirely unsolved.

### A standing exception per part

* Good, because it also covers the case where one part alone is the exception —
  the rectangular pin-1 pad on a single footprint.
* Bad, because the owner's report was about a FAMILY of parts. Thirty identical
  waivers are thirty things to keep current, and nothing counts them, so nobody
  sees that the rule itself is too broad.
* Neutral, because the two are compatible and not exclusive. A per-part
  exception remains the obvious next step for the single-part case, and the
  `disabled` marker is deliberately shaped so a per-part record could reuse it.

## More Information

* [docs/reference/review-axis.md](../reference/review-axis.md) — the checklist,
  the validator and the record in full.
* [0011](0011-retire-the-skipped-verification-result.md) — the previous change
  to the answer vocabulary, and the reasoning about which answer CLOSES an item.
* This decision would be revisited if the per-part exception above is built: at
  that point `disabled` at the category level and a waiver at the part level
  should be read by one piece of code, not two.
