---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# A position SAYS where its money goes, and how it gets there

## Context and Problem Statement

The Invoices line table offered one control, "Charge to", whose default read
**"— nobody —"**. The user put it plainly on 2026-09-19: *"if i dont assign the
position to anything and just select it as part then it will be automatically
assigned to pool (including the transport) is quite problematic and not
intuitive"*.

It is worse than the wording suggests. `— nobody —` is not one state. Leaving it
alone resolved to **five** different destinations, through
`run_actuals.line_destination`, from three things that were not on the screen:

| Line, with the box left empty | Where the money actually went |
|---|---|
| `kind: part` | the shared **pool** |
| `kind: freight` on a parts invoice | **unassigned** — nobody pays, a defect |
| `kind: freight`, `allocate: by_value` | the **pool**, as landed cost |
| any kind, document names a project | that **project** |
| any kind, document names a batch | that **batch** |

And the field that separates rows 2 and 3 **could not be set from the browser at
all**. `destPatch` only ever wrote `allocate: "excluded"`. The table *displayed*
"by value" on a line that already had it, but nothing in the UI could put it
there — so a transport line typed onto a parts invoice silently became money
nobody paid for. That is the origin of the register's standing `unassigned_usd
19.78`.

Two more fields were in the same condition. `basis` was hard-coded `per_run` in
`draftToLineIn`, so a per-board rate could not be entered. `exclude_reason` was
stored, and emitted by no endpoint, so the UI could neither show it nor ask for
it — which is why the deploy-day lint `legacy_unstated` had no way to be cleared.

Underneath all of it is one design fault: **one control was answering two
questions, and `kind` was secretly answering one of them.**

## Decision Drivers

* A default that is invisible is not a default, it is a trap. The operator
  cannot agree with a decision they were not shown.
* `unassigned` is the platform's money-disappearing detector. It must stay
  reachable as a state and unreachable as an accident.
* Nothing may move. 264 part lines rely on the current inference, and the
  register's figures are reconciled against real invoices.

## Considered Options

* Two columns — "Goes to" and "How" — and a stored value for stock.
* One column with explicit options and no empty value.
* Let the destination replace `kind` entirely.

## Decision Outcome

Chosen option: **"Two columns"** (user decision 2026-09-19), with `allocate`
gaining one value rather than a new column being added.

1. **`allocate` gains `pooled`** — "this position IS stock, and somebody said
   so". It behaves exactly like `none` in every money path; its entire job is to
   be the difference between the two things `none` used to mean. No new column,
   so no second source of truth to drift.
2. **`none` on a line naming nothing stays a DEFECT.** It still resolves to
   `unassigned` and the register still reports it. Now it is reachable only by a
   row that predates this change or by an operator who has not answered yet, and
   the row shows it in red.
3. **"Goes to" has no empty option that means something.** Its values are
   `not decided` · `from this document (…)` · `Stock — the shared pool` ·
   a batch · a project · `Nobody, on purpose`.
4. **"How" carries a different stored field per destination**, because "how"
   means a different thing for each — and all three were unreachable before:

   | Goes to | writes | choices |
   |---|---|---|
   | Stock | `allocate` | is stock · spread by value · spread by qty |
   | a batch or a project | `basis` | own amount · per device |
   | Nobody | `exclude_reason` | a short typed reason |

5. **`kind` SUGGESTS, and only into an empty box.** Choosing `part` fills in
   Stock; `freight` or `duty` fills in spread-by-value. It never overwrites an
   answer. This is what already happened invisibly — now it happens where it can
   be read and changed.
6. **Only a `part` may be marked `pooled`.** `_pool_events` treats only a part
   line as a purchase, so a `pooled` line of any other kind would sit in the
   register's `pool` bucket and never reach `pool.purchased_usd` — two pool
   figures, quietly disagreeing. The router refuses it with a 422 naming the
   alternative, and the UI does not offer it. Money that belongs on the stock
   without being stock rides there as landed cost: `by_value` / `by_qty`.
7. **A proforma is not special here.** `line_destination` does not look at
   `doc_type`; a proforma position reports `pool` like any other, and what makes
   a proforma different is that `_pool_events` skips the whole document. Gating
   the option made the Italtronic proforma read "not decided" beside a register
   row saying "pool: 1,651.00".
8. **The editor writes all four fields every time**, never a subset. The old one
   added `allocate: "excluded"` and never cleared it, and `line_destination`
   tests `excluded` before `run_id` — so moving an excluded position onto a batch
   left it charged to nobody while the screen showed the batch.
9. **The backfill marks every line that ALREADY resolves to the pool.** It
   mirrors `line_destination` including its order, so no figure moves: measured
   before and after, the register reads 86 documents, 155,749.3046 USD, gap
   0.0271, unassigned 19.78, identical.

### Consequences

* Good, because every position now states its destination on screen, and the two
  states that shared a spelling are told apart.
* Good, because landed cost, per-device rates and exclusion reasons became
  enterable at all.
* Good, because the one genuinely undecided position in the database — JLCPCB
  `Cancelled: XL-1005SURC`, USD 19.78 — is now visibly red instead of being a
  number on a summary line. It is still undecided, because only a human knows
  whether that charge was refunded, landed cost, or nobody's.
* Bad, because the line table now has nine columns. Position gave up 7 points
  and "Planned as" 3.
* Neutral, because `allocate: "none"` survives on non-part legacy rows. They read
  as undecided, which is what they are.

### Confirmation

`api/tests/costs/test_line_destination.py` covers: a `pooled` part reaching the
pool because it says so; `pooled` refused on every other kind; an undecided
non-part still reporting `unassigned`; a legacy
`part` line unchanged; the precedence order (`excluded` > a named run > `pooled` >
the document's own destination); `pooled` passing `pooled_part_lines` and
`pool_state`; and the register identity holding as a delta against the database's
own baseline. Round-tripped through the browser and the API: a position moved
Stock → Nobody (with a reason) → a batch clears `allocate` and charges the batch.

## Pros and Cons of the Options

### Two columns, and `allocate` gains `pooled`

* Good, because it matches the two questions that genuinely exist, and the
  second column earns its width by carrying three previously unreachable fields.
* Good, because one added enum value needs no new table column and cannot drift
  from a parallel one.
* Bad, because `allocate` is now read by two controls rather than one.

### One column, explicit options

* Good, because the table keeps eight columns.
* Bad, because `basis` and `exclude_reason` would stay unreachable — the empty
  default would be fixed and two of the three hidden fields would not.

### The destination replaces `kind`

* Good, because it is the fewest concepts on screen.
* Bad, because `kind` feeds `by_kind` totals, the plan-vs-actual step matching
  and `jlc_import`'s child kinds. A much wider change than it looks.

## More Information

Sits under [0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md): that
record stops a settled figure moving, this one stops it being wrong when it is
first entered. The `excluded` bucket and its reason come from
[0003](0003-orders-shipments-and-device-history.md)-era cost work and the
2026-07-27 decisions recorded in the production-run skill.

Revisit if `kind` is ever reduced to a label — item 5 is the only thing still
coupling it to where money goes.
