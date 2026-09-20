---
status: "accepted"
date: 2026-09-20
decision-makers: Mateusz Kowalik
---

# `gap_usd` measures the platform's arithmetic, not the supplier's rounding

## Context and Problem Statement

`invoice_register` has always carried a `gap_usd`, documented as *"Everything
above is one identity: total == runs + projects + pool + unassigned + residual.
A non-zero gap means a bug here, not bad data."*

It read **0.0271** on every measurement, for months. By its own docstring that
is a standing bug report that nobody ever acted on. Two reasons nobody did:

1. **It was measured against the wrong number.** `total` is the PRINTED total —
   what the supplier put on the page — while every bucket is derived from our
   LINES. The difference between the two is a transcription fact, not an
   arithmetic one, and five documents carry it: JLC prints a rounded total while
   our unit prices keep more decimals. It cannot be fixed by editing a line
   without inventing money.
2. **The screen rounded away its own alarm.** The production overview printed a
   green `0` for `Math.abs(gap) < 0.05`. The number nobody could fix was also
   the number nobody could see.

Underneath those, a third thing was real and hiding: with the printed/lines
difference removed, `lines == buckets` still missed by **0.0005** on four JLCPCB
documents. `document_json` computes a header's `residual` as
`max(parent - children, 0.0)`, and `split_line` permits children to exceed their
parent by up to half a cent. When they do, the leaves carry the overshoot and the
clamped residual does not, so the identity cannot close.

## Decision Drivers

* A check that can never read zero is not a check.
* A tolerance in a display is a tolerance in the check, whatever the docstring
  says.
* Three different facts were sharing one number, and only one of them was a bug.

## Considered Options

* Split the number into the invariant and the facts it was hiding.
* Fix the five documents so their lines match the printed totals.
* Widen the tolerance and document it.

## Decision Outcome

Chosen option: **"Split the number"**.

1. **`gap_usd` is the invariant** and is measured on `lines`, not `printed`:
   `lines - runs - projects - pool - excluded - unassigned - residual +
   overallocated`. It is **exactly 0.0**, and anything else is a bug in
   `run_actuals`.
2. **`untranscribed_usd` is `printed - lines`** — money that left the company and
   sits on no line. **0.0276** across five documents, each inside the 5-cent
   `reconciled` tolerance so none of them is named by `issues.unreconciled`.
   `issues.untranscribed` names them all, at any size.
3. **`overallocated_usd` is the twin of `residual`**: children claiming more than
   the header they split. Sub-cent by construction, because `split_line` refuses
   more, but it must be in the identity or the identity cannot close. **0.0005.**
4. **The totals accumulate EXACT values**, not the per-document figures rounded
   to 4dp for display. Adding 86 rounded numbers introduced error into the very
   figure whose job is to prove the arithmetic.
5. **The overview cell has no tolerance.** Zero is green, anything else is red.
6. **`excluded_by_reason_usd` and `excluded_unstated_usd` are reported.**
   `excluded` is a legal bucket in the identity, so an exclusion is invisible to
   every other check — which is how $14,443 of manufacturing once sat charged to
   nobody while the register read clean. Measured today: **56,002.43 excluded, of
   which 51,234.12 gives no reason.**

### Consequences

* Good, because the invariant can now be trusted: it reads zero, so a future
  non-zero value means something.
* Good, because two real figures that were hiding inside it have names, sizes
  and named documents.
* Good, because the excluded bucket stopped being a place where money goes
  quiet.
* Neutral on money: nothing moved. Every bucket total is unchanged; only the
  reporting changed.
* Bad, because there is more to read on the overview. That is the point.

### Confirmation

`test_the_register_identity_closes_exactly` asserts `gap_usd == 0`, and
`test_over_allocated_children_are_reported_not_clamped` builds a header whose
child claims 100.02 of 100.00 and checks the overshoot is named rather than
clamped. Measured on the real database: gap 0.0, untranscribed 0.0276 over five
documents, overallocated 0.0005 over four, excluded 56,002.43 of which
51,234.12 unstated. 180 tests pass.

## More Information

The `excluded_unstated_usd` figure is a FINDING, not a fix: 51,234.12 is
recorded as charged to nobody with no reason given, and roughly 11,496 of it is
`assembly`, `fab` and `freight` — real manufacturing work. Deciding what that
money is belongs to whoever knows the orders, not to this record.
