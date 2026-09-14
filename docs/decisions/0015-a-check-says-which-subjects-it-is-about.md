---
status: "accepted"
date: 2026-09-14
decision-makers: Mateusz Kowalik
consulted: Claude Code, which built and measured the change
informed: anyone editing a checklist, and anyone reading a review card
---

# A check says which subjects it is about

## Context and Problem Statement

[0014](0014-a-check-carries-its-own-configuration.md) put a check's settings on
its own checklist item. What it could not express is **which parts a check is
about**. Scope was one thing only: the category path, through a category-scoped
checklist.

That is too coarse for the library as it stands. `Diodes` holds three families
that want different rules, and the YAML blocks had always known it —
`conditional_required_properties`, keyed on a `comp_type` property, has sat in
the `Diodes` and `Transistors` rule rows since the original import and **no
check has ever implemented it**. Measured 2026-09-14:

```
Diodes       DIODE 5   TVS 15   ZENNER 6
Transistors  NMOS 7    PMOS 4   NPN 3
```

The concrete case: the `conventions-library` skill says a TVS carries its
reverse stand-off voltage as `Value`, naming `SMAJ24A` and `SMAJ24CA` as both
`24V`. Seven parts carry their MPN instead. A check that could say "this applies
to TVS parts" would catch it; a category-scoped one cannot, because Schottkys
and Zeners share the category.

## Decision Drivers

* A check's applicability belongs with the check, next to its settings — the
  same argument 0014 made about its numbers.
* The resolved list must keep exactly one item per key. Every downstream
  index — `checklists.resolve`, `record_check`, `state_from_record` — is keyed
  by it.
* "Not switched off, just not about parts like this one" must be a statement the
  UI can make, distinct from "the owner turned it off".
* A predicate must not quietly stop applying.

## Considered Options

* **A `when` predicate that NARROWS an already-resolved item.**
* A predicate that SELECTS the item, replacing category scoping entirely.
* Subcategories (`Diodes / TVS`), and no predicates at all.

## Decision Outcome

Chosen option: **`when` narrows**. An item may carry
`when: {field: pattern, …}`; resolution is unchanged, and the predicate only
decides whether the resolved item applies to the subject in hand.

The distinction matters because a SELECTING predicate lets two items claim one
key, and predicates have no natural order to break the tie the way a category
path does. Narrowing sidesteps it: the merge still produces one item per key,
and `when` only removes it.

**That left one case unserved, and NAMED VARIANTS close it — see the section
below.** `when` alone cannot vary a check's settings by sub-type, because
`Transistors` would need two `cmp.required_props`, which `_validate_items`
refuses. Variants allow exactly that, under a constraint that keeps the tie
impossible rather than resolving it by order.

- `checklists.resolve(db, kind, category_id, facts)` returns a third bucket,
  `inapplicable`. It must never be folded into `disabled`.
- `checklists.subject_facts` builds the facts. A bare name is a component
  PROPERTY; a `$` name is one of `WHEN_FACTS` — `$category`, `$category_path`,
  `$base_symbol`, `$footprint`, `$in_library`, `$purchasable`, `$lifecycle`.
- **A fact that is absent never matches.** `{"comp_type": "^TVS$"}` excludes a
  part carrying no `comp_type`, which is what "apply this to TVS parts" means.
- **`facts=None` means every item applies** — the editor resolving a category is
  describing the rule, not judging one part.
- **A pattern that does not compile matches NOTHING.** A check quietly not
  applying is recoverable; a check quietly applying to the whole library is not.
  The save path refuses these, so it only guards rows written before it.
- `_clean_when` validates `$` names against the whitelist and compiles every
  pattern.

### Consequences

* Good, because `conditional_required_properties` finally has a mechanism, after
  sitting unimplemented since the YAML import.
* Good, because one item per key still holds, so nothing downstream changes.
* Good, because the review card can say "n/a here" with the predicate in its
  title, instead of a check silently missing from a part's list.
* **Bad, and this is the one to remember: a predicate over a PROPERTY is only as
  stable as that property.** A category is a row; `comp_type` is free text
  somebody typed. The library already carries `comp_type=ZENNER` with an extra
  "n" — flagged in the `conventions-library` skill as a deliberate spelling
  match to the `Zenner Voltage` key. Key a rule on a string like that and an
  edit silently removes the check: no failure, no warning, the part stops being
  asked. Predicates over `$` facts do not have this problem; predicates over
  properties do, and that is the price of not moving parts.
* Neutral, because this does not settle whether `Diodes` and `Transistors`
  should become subcategories. It competes with that: predicates cost nothing
  now and entrench `comp_type`; subcategories cost 41 published versions with
  their verifications stripped, and retire `comp_type` — which nothing in the
  platform reads, yet which is emitted to KiCad on 26 symbols in
  `Diodes.kicad_sym`. If subcategories are built, the predicates for those two
  collapse into the tree and are deleted.

### Confirmation

Verified against the running platform on 2026-09-14:

* `subject_facts` on `SMAJ24A` gives `comp_type='TVS'`, `$category='Diodes'`,
  `$base_symbol='SMAJxxA'`; `^TVS$` matches, `^ZENNER$` and `^DIODE$` do not.
* An absent fact never matches; no facts in hand means the item applies; two
  entries are ANDed.
* A trial `cmp.tvs_standoff_value` on the `Diodes` list with
  `when {comp_type: ^TVS$}` reached `SMAJ24A` and was reported `inapplicable`
  for `BZT52C3V3` (Zener) and `SS34` (Schottky). The trial item was then
  removed; `Diodes rules` is back to its two real items at v4.
* A mistyped `$fact` and a non-compiling pattern are each refused 422.

## Pros and Cons of the Options

### `when` narrows an already-resolved item

* Good, because there is no tie to break: the merge still yields one item per key.
* Good, because it is additive — an item with no `when` behaves exactly as before.
* Bad, because two mechanisms now express scope (the category path and the
  predicate), and a reader has to look in both places to see who a check reaches.

### A predicate that selects, replacing category scoping

* Good, because it would be ONE mechanism, which is what was asked for.
* Bad, because of the key collision above, which has no good resolution.
* Bad, because it loses the per-category wording override — a category
  rewording a judgment check — with nowhere to put it.

### Subcategories instead

* Good, because a subcategory is a ROW: it cannot be misspelled, it is visible
  in the resolver, and moving a part is a deliberate publish.
* Good, because it also retires `comp_type`, which nothing reads and which
  leaks into every emitted symbol.
* Bad, because it costs 41 published component versions and their verifications,
  and it needs a category-management screen, which does not exist (the
  endpoints do — `routers/categories.py` has POST, PATCH and DELETE, and
  `Category.parent_id` has always been there; the tree is simply flat today).

## Named variants, and why they need no ordering

Added the same day, once the limit above showed itself on `Transistors`: NMOS
wants `Drain Source Voltage`, NPN wants `Collector-Emitter Voltage`, and both are
`cmp.required_props`.

**Several items may share a key, as distinct NAMED variants** — `variant:
"NMOS"`. The name is the identity (stable under reordering, which a list index
is not) and the label: the editor's Scope column reads `Transistors.NMOS` from
it, so a two-tier presentation needs no value parsed back out of a predicate.

The tie is made impossible rather than resolved. **A key with several variants
must discriminate on ONE field, with distinct literal values, plus at most one
variant with no `when` — the fallback** (`_check_variant_groups`). Then at most
one literal can match, the fallback is last by rule rather than by position, and
`checklists.pick` never consults order at all.

Three things follow, and each one was a defect avoided:

* **A sorted table cannot lie.** With positional first-match-wins, the editor
  sorts by key and would show variants in an order that contradicts the
  effective one — a screen misreporting which rule a part gets. With no
  positional semantics there is nothing to contradict.
* **Unreachable detection becomes complete** for the shape that is allowed:
  distinct literals cannot shadow, a duplicate literal is refused, a total
  pattern is refused, two fallbacks are refused. Best-effort shadow detection
  over arbitrary regexes is undecidable; this is decidable because the shape is
  constrained.
* **A compound predicate stays legal on a SINGLE-item key**, where no ordering
  question exists. A genuinely special case is a separate key — now enforced
  rather than advised.

Two more rules, both user decisions:

* **A more specific list REPLACES a key's whole variant group.** A category
  states the complete set, not an addition. To add a special case while keeping
  the general rule, switch the general one off and add a new KEY.
* **A DISABLED variant falls through to the next**, rather than switching the
  whole check off. Disabling every variant is what switches it off.

`inapplicable` reports a key only when NOTHING in its group matched. The other
variants are never mentioned: they are alternatives for one check, not checks,
and listing them would put two "n/a here" rows on every card for every varied
key.

### The hazard is now countable

`GET /api/checklists/coverage` runs a key's discriminator over the live parts in
scope and returns the split, shown under the open row:

```
14 part(s) in scope · NMOS 7 · NPN 3 · other 4
```

**A non-zero "no match" on a settled category means the discriminator is not
reliable** — which is the honest signal that the category wants a subcategory
rather than a predicate. It does not fix the fragility of keying on free text; it
makes it visible, which was the objection.

Measured 2026-09-14: a trial split of `Transistors.cmp.required_props` into
NMOS / NPN / fallback resolved `AO3400A` to the NMOS variant and
`BC817-40-7-F` to the NPN one, each validated against its own
`required_properties`, with coverage 7 / 3 / 4 and no match 0. The trial was then
removed.

## Declarative checks: one fact, one assertion

The same fact vocabulary that powers `when` also answers checks. An item may
carry an `assert` block, and `validator.evaluate_assert` answers it whatever its
key:

```jsonc
{ "key": "cmp.symbol_reference", "machine": true,
  "assert": { "fact": "$symbol_reference", "one_of": ["J"] } }
```

Facts split in two. The cheap ones are built eagerly by `subject_facts`
(properties, `$category`, `$base_symbol`, `$purchasable`, …). The DERIVED ones —
`$symbol_reference`, `$symbol_pin_count`, `$symbol_unit_count`,
`$symbol_on_board`, `$symbol_sim_link`, `$footprint_pad_count`,
`$footprint_has_model3d` — are computed only when something reads one
(`_LazyFacts`). That is not a micro-optimisation: `subject_facts` runs per
subject per resolve, and the coverage endpoint resolves once per component, so
parsing every symbol there would make the page unusable. `_LazyFacts` overrides
`get` as well as `__missing__`, because every reader uses `.get()` and
`dict.get` does not call `__missing__` — the bug that would have caused reads as
"this check applies to nothing" rather than as a failure.

Assertions: `one_of`, `matches`, `equals`, `at_least`, `at_most`, `present`.
**Exactly one per check**, refused on save otherwise.

Four consequences worth stating:

* **`machine: true` gets a second door.** A declarative check's key is
  author-chosen and therefore not in `validator.MACHINE_KEYS`, so
  `_validate_items` accepts the flag when the key is registered OR the item
  carries a valid `assert`. The guarantee is unchanged: something answers it.
* **The text is GENERATED** by `describe_assert`, for the reason a parameterised
  check's is (0014): a sentence typed beside a rule can disagree with it.
* **A missing fact answers `na`, never `failed`.** "This part has no symbol
  reference" and "its reference is wrong" are different statements, and
  conflating them sends somebody to fix the wrong thing.
* **`when` reads ALL_FACTS, not just the cheap half.** Restricting the predicate
  to eager facts would have made `$symbol_on_board` unusable exactly where it is
  most useful — narrowing a symbol check to board parts.

### The ceiling, and the tripwire

It expresses ONE fact and ONE assertion. It cannot express `any_of`/`all_of`,
arithmetic between two facts, or a comparison across two subjects, and it is not
meant to: the land pattern against the datasheet, pin names against the pinout,
"is 100nF the right value" are judgment items and stay that way.

**The first time this needs two assertions joined by a boolean, stop.** At that
point it has become a rules language, which is what `models.Rule` was and what
[0014](0014-a-check-carries-its-own-configuration.md) deleted. What keeps this
from being that mistake: it sits on the checklist item where its switch and its
scope already live, its vocabulary is closed and refused on save, its wording is
generated, and each instance is still a keyed item carrying a review answer. The
old table had none of those.

### Measured

Two declarative checks on `Connectors`, 2026-09-14:

```
cmp.symbol_reference   $symbol_reference one_of [J]        58 checked, 6 failed
cmp.symbol_has_pins    $symbol_pin_count at_least 1        47 checked, 17 n/a
   when $symbol_on_board ^true$
```

The six are `USB-B01` (USB), `DB2ERM-3.81-6P-GN` and `DF40C-100DS-0.4V-51` (CN),
`HU2032-LF` and `KEYS2466` (BAT), `FPC-05F-24PH20` (FPC) — real inconsistencies
nothing had ever reported. The seventeen are the `TERMINAL_BLOCK_PLUG` mating
plugs from [0005](0005-off-board-parts.md), correctly excluded by the predicate
rather than failed. Both trials were then removed; `Connectors rules` is back to
its one real item.

**Follow-up, not done:** `cmp.base_symbol_allowed` is now subsumed —
`{fact: "$base_symbol", one_of: [...]}` — and should be retired. It is left in
place because removing a seeded machine key needs a migration to drop the item
from the stored base list, and a half-applied one would leave an item claiming
`machine: true` for a key the registry no longer knows, which `_validate_items`
refuses on the next save.

## More Information

* [0014](0014-a-check-carries-its-own-configuration.md) — a check carries its
  own configuration, which this completes.
* [docs/reference/review-axis.md](../reference/review-axis.md).
* Revisit when the subcategory question is settled: if `Diodes` and
  `Transistors` gain a tree, the `comp_type` predicates should be deleted rather
  than left beside it.
