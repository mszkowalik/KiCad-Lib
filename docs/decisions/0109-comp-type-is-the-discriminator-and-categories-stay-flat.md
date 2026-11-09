---
status: "accepted"
date: 2026-11-09
decision-makers: Mateusz Kowalik
consulted: Claude
---

# Keep `comp_type` as the discriminator inside a category, and keep the category tree flat

## Context and Problem Statement

Some categories hold parts that follow different rules: Diodes holds TVS, Zener
and plain diodes, Inductors holds inductors, ferrite beads, chokes and
transformers. Two mechanisms could separate them. `comp_type` is a property on
every component (backfilled 2026-09-14), and checks already split into variants
on it ([0015](0015-a-check-says-which-subjects-it-is-about.md)); since `316cea0`
a symbol rule reaches a part through `$symbol_comp_types`. The schema also has
`Category.parent_id`, with routes and no screen, and the tree is flat.

Todo row 17 asked which one the library uses, because retiring `comp_type` grew
more expensive with every rule built on it.

## Decision Drivers

* One mechanism for one question.
* No re-verification of parts for a change in classification alone.
* A rule must reach a symbol through the parts drawn on it.

## Considered Options

* `comp_type` stays the discriminator; categories stay flat.
* Subcategories replace `comp_type`.

## Decision Outcome

Chosen option: "`comp_type` stays the discriminator", because it already carries
the variants and the symbol bridge, and moving about 41 components into child
categories would publish 41 versions and repeat their verification for no new
check.

1. A category whose parts follow different rules splits its checks into
   variants on `comp_type`. It does not grow a child category.
2. `Category.parent_id` stays in the schema, unused, with no screen.
3. A category that lacks a `comp_type` split today (Inductors, RF,
   Circuit_Protection, todo row 24) gets one the way Diodes has it.

### Consequences

* Good, because no part changes and no verification is lost.
* Good, because todo row 24 has a single way to proceed.
* Bad, because the browse tree cannot fold a big category into its kinds; the
  `comp_type` column and filter do that job.

### Confirmation

The skill `conventions-library` (v49) states the rule. A new category split is
reviewed against it.

## Pros and Cons of the Options

### `comp_type` stays the discriminator

* Good, because the variants and `$symbol_comp_types` already use it.
* Bad, because a classification lives in a property, which a person can type
  wrongly; `signoff.CLASSIFICATION_KEYS` makes a first setting free and a change
  costly, which is the right price.

### Subcategories replace `comp_type`

* Good, because a tree is a familiar way to browse.
* Bad, because it needs a screen, a migration of about 41 components, their
  re-verification, and a rewrite of every variant and of the symbol bridge.

## More Information

* [0015](0015-a-check-says-which-subjects-it-is-about.md) — variants on one
  discriminator.
* [0019](0019-a-classification-carries-the-first-time-it-is-set.md) — why setting
  `comp_type` costs no verification.
