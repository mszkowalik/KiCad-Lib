# What a check can hold, and what has to stay prose

The convention skills are read by an agent on every library task, so every line
that a check could enforce instead is a line being re-read for nothing. But the
reverse mistake is worse: a rule cut from a skill and not enforced anywhere has
simply been deleted.

This page is the mapping, and the method. It was written on 2026-09-14 after a
thinning pass removed 42 KB from `conventions-library` on the assumption the
checks held that data. They did not: the `VSWR` key rule had no check at all,
and a decision rule — *"a family-wide deviation defends itself"* — was deleted
outright. The pass was reverted.

## The method

**Build the check, measure it, then cut. Never the other way round.**

1. For each rule, find the check that holds it, or build one.
2. Run it against the library and record what it finds.
3. Cut only what the check demonstrably holds.
4. Keep every reason, every unresolved question and every decision rule — a
   check can enforce a rule but it cannot say why the rule exists, and the why
   is what stops the next person re-litigating it.

## What a check can hold

| Shape | Mechanism |
|---|---|
| A value must match a pattern | `assert.matches` |
| A value must be one of a list | `assert.one_of` — the list lives on the check |
| A count must not exceed a threshold | `assert.at_most` over a derived fact |
| A key must NOT exist | `assert.absent` |
| A comparison between two facts | a derived fact in `checklists.FACTS`, never a boolean assertion |
| A rule that applies to some parts | `when`, or a named variant per discriminator |

## What it cannot

- **Why a decision went the way it did.** The canonical spelling of a
  manufacturer is in `cmp.manufacturer_canonical`; that `ECS Inc.` was chosen
  because the company's own materials disagree with themselves is not.
- **An unresolved question.** `TWGMC`, `Milliohm` and `TECH PUBLIC` have no
  confirmed canonical form. A check cannot hold "ask rather than guess".
- **A decision rule.** *"Check a new part against the RULE, not against what its
  neighbours do"* is the reasoning that explains how five SMAJ parts stayed
  off-rule for months, each justified by the other four.
- **Authoring guidance for a sub-family of one.** A template with two siblings
  cannot be told from a coincidence. `conventions-library` lists 15 such
  templates — every ICs sub-family, both Connectors terminal blocks, the
  LightPipe, the RF pigtail — and they belong in prose precisely because
  `cmp.description` stays a judgment check in those categories.

## What blocks a check today

A per-category rule needs a discriminator to split on. **`Inductors`, `RF` and
`Circuit_Protection` carry no `comp_type` at all**, so their Value rules cannot
become variants the way the Diodes rule did: a fixed inductor, a ferrite bead
and a LAN transformer are three different rules sharing one category, with
nothing in the data to tell them apart.

`Connectors` has the same problem in a different shape: `Pluggable terminal
block; {Pitch}` and `Pluggable terminal block; 3.5mm` coexist in one family —
half templated, half with the pitch written in — so there is no single correct
value to compare against yet.

## What a SCOPE may be built on

Added 2026-09-14, after nine scopes were measured and two were thrown away.

**Build the predicate, measure who it drops, then ship it.** The question is
never "does this cover the exceptions" — it is "which subject stops being asked
that should not". A check that wrongly stops being asked is an invisible gap;
an exception that survives is merely untidy.

Two predicates failed exactly that test on `sym.pinout`:

| Predicate | Covered | Would have dropped |
|---|---|---|
| `$symbol_distinct_mpns = 1` | 16 of 25 | `LE310X1` (94 pins), `MAX3222E` (20) — two package variants sharing one drawing |
| `$symbol_named_pins ≥ 1` | 12 of 25 | `DF40C-100DS` (100 pins), `FPC-05F-24PH20` (26) — unnamed stubs and a real datasheet numbering |

So `sym.pinout` stays library-wide with 25 exceptions. **When no predicate
separates the cases, the exception IS the right instrument** — that is what it
is for.

### Absent and zero are not the same fact

An absent fact never matches a `when`. So a count that returns nothing for both
"there are none" and "the file would not parse" cannot be scoped on: the
predicate would silently stop asking every question of a broken drawing. Split
them first — `parsed()` in `services/checklists.py` is the pattern, and it is
why a pinless symbol now reports `"0"` while a broken one still reports nothing.

### A scope may reach across axes

`comp_type` lives on a COMPONENT and a drawing rule is about a SYMBOL.
`$symbol_comp_types` carries the classification over, which is what lets the
op-amp triangle rules reach seven symbols instead of all 207. Without it a
drawing rule can only be scoped by geometry, and geometry cannot tell an op-amp
from an ESD array that also hides its pin names.

## Related

* [review-axis.md](review-axis.md) — checks, facts, severities and exceptions.
* [decisions 0013-0018](../decisions/index.md) — why checks are configuration.
