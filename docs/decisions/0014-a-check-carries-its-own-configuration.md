---
status: "accepted"
date: 2026-09-14
decision-makers: Mateusz Kowalik
consulted: Claude Code, which built and measured the change
informed: anyone editing a checklist, and anyone reading a machine finding
---

# A check carries its own configuration, and the rules table is retired

## Context and Problem Statement

[0013](0013-the-validator-owns-the-automatic-checks.md) made the checklist a
switchboard: it says which automatic checks run. It said nothing about what they
run AGAINST. That lived somewhere else entirely — a `rules` table of JSON
blocks:

- one `scope="global"` row holding, in three nested sections, the numbers for
  eleven different checks (`min_drill_diameter`, `crtyd_line_width_mm`,
  `pin_grid_mm`, `required_properties`, `property_patterns`, …);
- fifteen `scope="library"` rows, one per top-level category, seeded from each
  YAML library's `validation_rules` at the original import.

Three things were wrong with it.

**Half of it was not read.** `validate_component` consumed the global row;
`validate_footprint` and `validate_symbol` compared against constants compiled
into the module, so `footprint_dimensions` in the database had been dead data
since the beginning and could disagree with the code with nobody noticing. And
`resolve_rules` filtered on `scope="global"`, so **not one of the fifteen
category rows had ever been read**. `Capacitor rules` had stated since day one
that a capacitor carries Value and Voltage, and no part was ever measured
against it.

**A number had no address.** A reviewer reading "F.Fab line width is 0.1 mm" had
to know that the 0.1 came from `rules.block.footprint_style.fab_line_width_mm`.
The sentence was typed into the checklist by hand, so it could also simply be
wrong.

**The scoping did not fit the subjects.** A per-category threshold cannot be
applied to a footprint or a symbol: neither carries a category, one footprint is
shared across categories, and a footprint nothing uses yet resolves to no
category at all. So the category rows could only ever have meant something for
component checks — the half of the table that existed for footprints was
unscopeable by construction.

## Decision Drivers

* A setting and the check that uses it should be one thing, in one place.
* The document that says whether a check runs should say what it runs against.
* A category must be able to state a rule that is actually applied.
* Nothing already recorded may be rewritten (`ReviewRecord.checklist_items`).
* Fewer engines. There was a checklist resolver AND a rule resolver, with
  different merge rules, doing the same shape of job.

## Considered Options

* **Put a check's configuration on its checklist item (`params`).**
* Keep the `rules` table and wire up the half nothing read.
* Keep the table and add `category_id` so category rows resolve by path.

## Decision Outcome

Chosen option: **a check carries its own configuration**, because it collapses
two resolvers into one and gives every setting an address a reader already
knows — the check it belongs to.

1. **`validator._CHECK_SPECS` declares each check's parameters and their
   defaults.** The default's TYPE is the parameter's type, and
   `routers/reviews._clean_params` validates against it: a threshold is a
   positive number, a switch is a switch, a property set is a list of names, a
   pattern map is property → regular expression (compiled on save — a pattern
   that does not compile would fail every part carrying the property and name no
   cause anybody could act on).
2. **A checklist item may carry `params`.** `check_params(kind, items)` resolves
   them over the spec defaults, and every check reads its own. A check's TEXT is
   written from the very parameters it will run with, by the API on save, so the
   sentence a reviewer reads and the comparison the code makes cannot disagree.
3. **A category states its own by putting the item on a category-scoped
   component checklist.** `checklists.resolve` already merges those, most
   specific last — so per-category rules cost no new machinery at all. Only
   components have this, and that is now a property of the subject rather than a
   limitation of a separate engine.
4. **Thresholds stay library-wide** (user decision), because they belong to
   footprint and symbol checks, which have no category to scope by.
5. **`checklists.migrate_rules_onto_items` folds the table into the
   checklists** at startup, idempotently: the global block onto the three base
   lists, each category row onto a category-scoped component checklist it
   creates if needed. `models.Rule` stays as dormant history. The migration
   REPORTS the keys nothing consumes rather than dropping them silently.
6. **A new check, `cmp.property_values`**, applies the per-category patterns —
   the rule those fifteen rows mostly carried and nothing enforced. It is seeded
   into the base component list **switched off** with an empty pattern map,
   because adding a live machine item to a base checklist un-answers it on every
   existing subject with no backfill; the category lists turn it on where there
   are patterns.

### Consequences

* Good, because every setting now sits beside the switch of the check it
  configures, versions with the checklist, carries the comment saying why it
  changed, and lands in the review record's snapshot — so a past verification
  says what it was measured against.
* Good, because the fifteen category rows finally do something. Measured on
  2026-09-14 over 439 components: **189 now have their property values checked
  where nothing checked them before**, 13 fail `cmp.property_values` and 11 fail
  `cmp.required_props` on rules their category had always stated.
* Good, because one resolver does the work of two.
* Bad, because a setting is now spread across as many items as state it. Reading
  "what is the drill minimum everywhere" means reading the base footprint list
  rather than one row — acceptable, since there is exactly one base list per
  kind and thresholds are not category-scoped.
* Bad, because `conditional_required_properties` (Diodes and Transistors, keyed
  on `comp_type`) still has no check that implements it. It is named in the
  migration report rather than carried over, so it is visible instead of lost.
* Neutral, because nothing already recorded moves. The new rules reach a part on
  its next publish or its next "Re-run auto checks".

### Confirmation

Verified against the running platform on 2026-09-14:

* The migration published `Component base checklist v4`, `Symbol base checklist
  v3`, kept `Footprint base checklist v3`, and created fifteen category
  checklists; a second run published nothing.
* `Capacitor rules` carries `cmp.required_props` with `{required_properties:
  [Value, Voltage, Footprint]}` and `cmp.property_values` with the four patterns
  from the old YAML block, and words itself from them.
* `POST /api/reviews/component/42/recheck` on a capacitor answered
  `cmp.property_values checked — 4 value(s) against 4 pattern(s)`, which no
  component had ever been asked before.
* A non-compiling pattern, a non-numeric threshold and an unknown parameter name
  are each refused 422.

## Pros and Cons of the Options

### A check carries its own configuration

* Good, because a setting's address is the check it belongs to.
* Good, because per-category rules fall out of the checklist merge that already
  existed, rather than needing a second one.
* Neutral, because it needs a migration, which is one function that runs once.
* Bad, because a threshold that genuinely IS library-wide now lives on an item
  in a base list rather than in a single settings row.

### Wire up the half of the rules table nothing read

* Good, because it is the smallest change.
* Bad, because it keeps two resolvers with different merge rules, and keeps the
  number and the sentence describing it in different documents.
* Bad, because it does not make per-category rules applicable to footprint and
  symbol checks either — that is a property of the subjects, not of the engine.

### Add `category_id` to `rules` and resolve by path

* Good, because it fixes the "a name is not a reference" problem (this WAS
  built, on the way to the decision above, and the backfill matched all fifteen
  rows).
* Bad, because it is a second path-walking merge engine sitting next to
  `checklists.resolve`, which already does exactly that job on documents the
  user edits.

## A symbol rule scoped to a component category

Added on the same day, and it follows from the same reasoning. A `sym.*` check
is answered on the SYMBOL's record, and a symbol carries no category, is shared
across categories, and may be pinned by nothing at all — so a per-category
symbol rule has nothing to resolve against when the check runs.

It is therefore answered on the COMPONENT, as a `cmp.*` check that examines the
symbol the component pins. The category is then the component's own and is
exact, it costs no new scoping rules, and the component's state already
aggregates its symbol's. `cmp.base_symbol_allowed` is the first of them:
`allowed_base_symbols` on a category's item, empty everywhere else.

Rejected: resolving a symbol's category from the components that pin it. It
needs a tie-break, and both are wrong — strictest-wins can only tighten, which
is the opposite of an exception, and loosest-wins lets one permissive category
weaken a symbol another category depends on.

## More Information

* [0013](0013-the-validator-owns-the-automatic-checks.md) — the checklist as the
  switchboard, which this completes.
* [docs/reference/review-axis.md](../reference/review-axis.md) — the checklist,
  the validator and the record in full.
* Revisit if `conditional_required_properties` is implemented: it is a rule
  ABOUT a check's applicability rather than a parameter of one, and may not fit
  `params` as it stands.
