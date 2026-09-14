---
status: "accepted"
date: 2026-09-14
decision-makers: Mateusz Kowalik
consulted: Claude Code, which built and measured the change
informed: anyone adding a property key, and anyone reading a carry
---

# A classification carries the first time it is set

## Context and Problem Statement

`comp_type` is the discriminator a checklist rule scopes on: "ask this of an
op-amp", "use this Value format for a Zener". On 2026-09-14, **364 of 442
components carried none at all** — only the five categories somebody had
touched by hand had it.

Setting it is a property edit, and `services/signoff.py` treats every property
key as MATERIAL unless it is on the small `NON_MATERIAL_KEYS` allow-list.
Measured before the change:

```
components with no comp_type            364
  of which carry verification items     360
  of which carry a production sign-off   112
```

So classifying the library would have stripped verification from 360 components
and sign-off from 112 — **the whole library's review state** — to record a fact
that changes nothing about the part on the bench.

## Decision Drivers

* A classification must be addable without destroying the review axis.
* A classification must not become a back door: changing which rules a part is
  judged by is a real change and must still cost the carry.
* Nothing already recorded may be rewritten.
* The allow-list direction must stay: a key nobody has classified is material.

## Considered Options

* **A transition rule: absent → set carries, everything else does not.**
* Add `comp_type` to `NON_MATERIAL_KEYS`.
* Accept the loss and re-verify 360 components.
* Store `comp_type` outside the property list, on the component row.

## Decision Outcome

Chosen: **a transition rule**, as `signoff.CLASSIFICATION_KEYS`.

A key in that set does not cost the carry when it goes from **absent or blank**
to **set**. Every other transition — changing the value, blanking it, removing
the row — costs the carry exactly as before, and so does a classification
bundled into a version that also changes something real.

The reasoning is that a verification measures the PART against its
documentation. Nothing was ever measured against a value that did not exist, so
filling one in cannot invalidate what was measured. **Changing** one can, and
directly: moving a part from `LDO` to `DCDC` changes the `cmp.value_field`
variant it must satisfy, and a verification made under the old rule must not
silently survive that.

This is deliberately **not** `NON_MATERIAL_KEYS`. That list says a key is
unimportant; this one says one TRANSITION is safe. Keeping them separate is what
stops the next person reading "comp_type is non-material" and editing one freely.

### Consequences

* Good, because the library could be classified at all. **Measured:** 442 of 442
  now carry `comp_type` across 94 distinct types, and **385 still carry their
  verification.**
* Good, because a drawing rule can now reach the right parts. `$symbol_comp_types`
  carries the classification from the component axis to the symbol axis, which is
  what let the op-amp triangle rules be scoped to seven symbols instead of asked
  of all 207.
* Bad, because it is a second rule in a place that had one, and a reader now has
  to know both. The narrowness is the mitigation: one frozen set, one transition.
* Neutral, because the 57 components that did NOT keep their verification lost it
  to a real material change made in the same session, not to this rule.

### Confirmation

Verified against the running platform, 2026-09-14, on all four transitions:

```
add comp_type where absent : (True,  '')
change LDO -> DCDC         : (False, 'properties changed comp_type')
remove comp_type           : (False, 'properties removed comp_type')
comp_type PLUS a real edit : (False, 'properties changed Value')
```

and end to end on `XC6206P332MR-G`: v11 carried 6 review items, v12 carries the
same 6 with `kind=carry`.

## Pros and Cons of the Options

### A transition rule

* Good, because it is true to what a verification measures.
* Good, because it leaves every other direction as strict as it was.
* Bad, because "material" is now a property of the CHANGE rather than of the key.

### Add `comp_type` to `NON_MATERIAL_KEYS`

* Good, because it needs no new concept.
* Bad, because it would let a later edit move a part between rule sets while
  carrying a verification made under the old one — the exact failure the
  allow-list exists to prevent.

### Accept the loss and re-verify

* Good, because it needs no code at all.
* Bad, because it costs 360 verifications and 112 sign-offs to record a fact
  that changes nothing physical. Nobody would have run it.

### Store `comp_type` on the component row

* Good, because it sidesteps the carry entirely.
* Bad, because it would not version with the part, and `when` predicates read
  properties — it would need its own path through `subject_facts` for no gain.

## More Information

* `api/app/services/signoff.py` — `CLASSIFICATION_KEYS` and `data_carries`.
* [0016](0016-severity-and-standing-exceptions.md), [0017](0017-conformance-is-computed-not-recorded.md)
  — severity, exceptions and the computed machine tier.
* [docs/reference/what-a-check-can-hold.md](../reference/what-a-check-can-hold.md)
  — what belongs in a check, and what a scope may be built on.
