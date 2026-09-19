---
status: "accepted"
date: 2026-09-19
decision-makers: Mateusz Kowalik
---

# A correction is a dated EVENT, not an edit to the past

## Context and Problem Statement

The user asked on 2026-09-19 what happens when an old invoice has to be fixed,
because a price change "would change a lot of prices like finished unit price".

Reading the code gives two different answers depending on which line you touch,
and only one of them was designed:

| What you edit on a 2024 document | Reaches back? | Why |
|---|---|---|
| A `part` line feeding the pool | **No**, for runs that already drew | `component_consumptions.unit_cost_usd` is snapshotted at draw time; the lot bindings are frozen too |
| The pool average and on-hand value | Yes, from that event date | `pool_state` replays on every read. This is correct and is the point of the fix |
| A `fab` / `assembly` / `freight` / `tooling` line charged to a run | **Yes, immediately and silently** | `run_actuals._run_money` recomputes `qty x unit_price x fx` on every read. Nothing is snapshotted anywhere |
| `currency` or `doc_date` | Yes | The NBP rate is re-pinned, then the row above applies |
| Attrition charged to a run with `unit_cost_usd IS NULL` | Yes | It resolves against **today's** pool average, not the average at the write-off date |

So the component half of the model was built around the principle that history
does not move, and the direct-cost half was never given the same protection. A
typo corrected on a 2024 assembly invoice changes that batch's total, therefore
its per-device cost, therefore the cost of every order that shipped those
devices — with nothing recording that the figure ever changed.

Nothing downstream is stored either: `orders.per_device_cost_usd` is computed on
read and no device carries a cost of its own, so the movement propagates all the
way to an order's economics.

## Decision Drivers

* A per-device cost lands on real customer invoices ([0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md)).
  A figure that has been quoted must not move without a trace.
* Corrections are legitimate and must stay possible. A model that can only be
  right by being unfixable is worse than the problem.
* The platform already computes everything on read, deliberately
  (`run_actuals` module docstring). Freezing totals wholesale would fight the
  architecture.
* Every established practice outside this codebase answers this the same way,
  and the answer is not "recalculate quietly".

## Considered Options

* Close a batch, lock the documents that charge it, and post a dated correction.
* Snapshot every run's cost permanently on first read.
* Refuse to edit any document older than N days.
* Leave it, and rely on the operator remembering.

## Decision Outcome

Chosen option: **"Close a batch, lock the documents that charge it, and post a
dated correction"** — the standard accounting treatment, reduced to the three
pieces this platform actually needs.

### What other systems do, and what is borrowed

Two families exist. **Freeze and post the difference** is the dominant one:
closed accounting periods (a document in a closed period cannot be edited, and
the fix is a credit note dated today), a document date separate from a posting
date, Purchase Price Variance in standard-costing systems, and item-charge or
landed-cost documents that attach money to a receipt after the fact. **Recalculate
retroactively** exists too — Dynamics BC's "Adjust Cost — Item Entries" walks the
consumption chain forward — but always as an explicit batch job, precisely
because the recalculation is dangerous enough to need its own button.

This platform already implements the first family for components. The decision
extends it to the rest:

1. **A batch can be CLOSED.** `production_runs.closed_at` and `closed_by`. Closing
   also records what the batch cost at that moment — `closed_cost_usd` and
   `closed_units` — so a later movement is a visible variance rather than a
   number that was always this way.
2. **A document that charges a closed batch is LOCKED**, and only if it existed
   before the batch closed (`created_at < closed_at`). Every write path refuses
   it: header patch, line add, batch line edit, line patch, void, split and
   document delete. The refusal names the batch and points at the correction.
3. **The lock covers direct costs only, never the pool.** A `part` line feeding
   the pool cannot change a closed batch's cost, because its draws are already
   snapshotted. Locking pool invoices would block legitimate stock corrections
   for no gain.
4. **A correction is a NEW document**, `doc_type="correction"`, dated when the
   correction is made, carrying `corrects_document_id` back to the original. It
   is an ordinary document in every other respect — it reconciles, it assigns, it
   feeds the pool or a run exactly as any other — so no money path needed a
   special case. A credit is a negative line.
5. **The original keeps its printed figures forever.** This is the same rule the
   split mechanism already follows: "the parent keeps the printed amount,
   untouched — a split never rewrites what the invoice said".
6. **Charged attrition pins its unit cost at write time**, from the pool average
   **at the adjustment date**. It used to resolve against the final average on
   every read, so a 2024 write-off was priced at a 2026 average and moved again
   with every later purchase.
7. **Closing is reversible** by an explicit reopen, which clears the snapshot and
   says so in the audit log. A lock nobody can undo becomes a reason to work
   around the platform.
8. **Every one of these has a UI control** (user instruction 2026-09-19): close
   and reopen on the batch page with the variance beside them, the lock state and
   a `Create correction` button on the Invoices view, and `correction` in the
   document-type list.

### Consequences

* Good, because a quoted per-device cost stops moving silently. After a batch is
  closed, the only thing that can change its cost is a dated document somebody
  wrote on purpose.
* Good, because the fix is recorded as its own event with its own date, which is
  what an audit needs and what a `notes` string was standing in for.
* Good, because charged attrition stops being re-priced by every later purchase.
* Bad, because correcting a closed batch is now two steps rather than one. That
  is the intended cost.
* Neutral, because nothing is locked until somebody closes a batch. Every
  existing batch stays open, and the behaviour on deploy day is unchanged.

### Confirmation

`api/tests/costs/test_closed_batch.py` covers: a closed batch refuses each of the
seven write paths with 409; a pool invoice stays editable while the batch that
drew from it is closed; a correction document written after the close is
editable and lands on the batch; reopening restores editing; and a charged
adjustment written after this change carries a pinned `unit_cost_usd` that a
later purchase does not move.

## Pros and Cons of the Options

### Close the batch, lock its documents, post a correction

* Good, because it matches both the outside world and the half of this model
  that already worked.
* Good, because the lock is opt-in per batch, so nothing changes until somebody
  decides a batch is finished.
* Bad, because "which documents does this batch's close lock" is a rule a reader
  has to learn. It is stated on `closed_at` and enforced in one function.

### Snapshot every run's cost on first read

* Good, because nothing could ever move.
* Bad, because a snapshot taken by a READ is taken at an arbitrary moment — the
  first person to open the page decides what the batch cost forever.
* Bad, because it fights the compute-on-read design the whole module rests on.

### Refuse to edit anything older than N days

* Good, because it needs no new state.
* Bad, because age is not the question. A batch finished last week is as settled
  as one from 2024, and a 2024 batch still being reconstructed is not settled at
  all.

### Leave it

* Bad, because it is how a figure already on a customer's invoice moves without
  anybody knowing. That is the whole finding.

## More Information

Completes the protection [0040](0040-a-purchase-cannot-be-removed-from-under-its-draws.md)
gave the component half: that record stops a purchase being removed from under
its draws, this one stops a direct cost being rewritten under a batch that is
finished. Protects the per-device cost [0043](0043-a-batch-costs-an-order-earns-and-a-unit-joins-them.md)
put on the order side.

Revisit if a closed batch ever needs a correction that must NOT change its cost —
a presentation-only fix. Today the answer is to edit nothing and write a comment.
