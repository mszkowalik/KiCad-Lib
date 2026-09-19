---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# Sync JLCPCB's own inventory ledger, and correct our books only from what it says

## Context and Problem Statement

Until now the platform compared its component pool against ONE number JLC
publishes: the balance in the private parts library. A balance can only say
THAT the two disagree. It cannot say why, which left every disagreement to be
chased through invoices — and closed by hand when the invoices did not explain
it.

Two disagreements could never have been closed that way, because no invoice
mentions them:

* **A cancelled purchase.** Lot 754166 settled 3,470 pieces of C965790 at
  $19.78 and was then cancelled (`orderStatus=40`) and refunded. The parts
  order still reports the lot with a non-zero `settlePresaleNumber`, so the
  importer booked 3,470 pieces of stock that never existed.
* **A warehouse pick.** On 2024-10-22 JLC moved 8 pieces of C965790 and 3 of
  C778132 under code `T241022013`, remark *"pick 3 pcs of C778132 & 8 pcs of
  C965790 up to complete SMT order"*. Seven such rows exist across the account.
  They are on no invoice and in no BOM, because no order consumed them.

Both were found by reading a page of JLC's inventory history pasted into a chat
and then corrected with hand-written rows. The user's rule, stated 2026-09-18:
**"i need you to not manually fix things. if we're using JLC to handle our
components, they have to agree to a single component."** A correction typed from
a screenshot is a guess with a source, and it does not survive a re-import.

JLC does publish the ledger. `myLibrary/selectComponentChanges` returns every
movement for one part with the balance before and after, the document that
caused it, and JLC's own wording. It is keyed by `customerPresaleStockKeyId`,
which appears only in the WEB stock list — not in the official OpenAPI library
the platform was already syncing, which is why it had not been found.

## Decision Drivers

* A correction must have a source that can be fetched again, not a source that
  was pasted once.
* The supplier holds the stock. Where our books and theirs differ, theirs is the
  observation and ours is the inference.
* A defect that only a human noticing an odd number can find will be found once
  and then not again.
* Every existing rule about not moving stock automatically still holds. Fetching
  evidence and acting on it are different actions.

## Considered Options

* Sync the ledger and reconcile against it, correcting only from its rows.
* Keep reading it by hand when a part looks wrong.
* Infer the cancellations from the parts orders alone.

## Decision Outcome

Chosen option: "Sync the ledger and reconcile against it".

1. **`jlc_stock_changes` holds JLC's ledger, UPSERTED, never replaced.** A row
   is immutable at JLC and keyed by `customerPresaleStockChangeKeyId`.
   `JlcStockItem` is still replaced wholesale, because a balance is not a
   history.
2. **`changeStatus=3` is a movement that DID NOT HAPPEN** — a ship-out request
   JLC cancelled. It still states a quantity and a before/after pair. Excluding
   it, all 67 parts replay to the balance JLC reports; including it, two do not.
   A part that does not replay is a FETCH problem and is named in the sync
   report, never read as a disagreement about stock.
3. **The ledger is fetched with the balance**, in `POST /api/jlc/stock/sync`,
   best effort — the balance comes from the OpenAPI and must not fail because
   the browser session lapsed. A sync that fetched one without the other is how
   a disagreement sits unexplained for a year.
4. **`jlc_ledger.unexplained` reports BOTH directions**, because they are
   different defects: a movement JLC recorded that no document of ours reports,
   and a purchase we booked that JLC's ledger never received. A pair of rows
   under one document code that nets to zero is netted out — JLC draws and
   returns parts on a cancelled order (44 such rows today).
5. **`jlc_apply.refresh_parts_document` re-states an ALREADY IMPORTED parts
   order** from what JLC says today, matched lot by lot on `presaleGoodsKeyId`.
   This is how the cancelled lot was corrected: `_lot_from_goods` learned to
   read `orderStatus=40`, and the refresh applied that reading to the document
   already in the database. It decides before it mutates, preserves anything a
   person appended to a line's note after " | ", and REFUSES rather than guesses
   when a lot has vanished or when shrinking a line would contradict draws bound
   to it.
6. **`jlc_ledger.book` writes a chosen ledger row as an UNCHARGED DRAW**, with
   JLC's quantity, JLC's date and JLC's wording, priced at the pool's average on
   that date. `basis='measured'`, because JLC measured it —
   `run_costs.set_used_qty` then refuses to retype it. `import_ref` is
   `jlcledger:<changeKeyId>`, so under `uq_consumption_import` re-booking is a
   no-op.
7. **Nothing books itself.** The caller names the rows; the Stock page asks
   before writing any. A row that names a document is not bookable AT ALL —
   importing that document is the right fix, and writing the draw from the
   ledger too would take the same stock out twice.

### Consequences

* Good, because the platform agrees with JLC on **every part, to the piece** —
  72 pool parts, 0 disagreements, from 28 parts and 33,246 pieces when this
  reconciliation began.
* Good, because both corrections that closed it came from JLC's own rows. Two
  hand-written corrections made earlier the same day were REVERSED (journal
  batch 24) and re-derived through these paths.
* Good, because the same reconciliation now runs on every sync, so the next
  cancelled lot or warehouse pick surfaces the day it happens.
* Bad, because the ledger needs the browser session, which is a cookie paste
  kept alive by `jlc_web.start_keepalive`. When it lapses the balance still
  syncs and the ledger silently does not — the sync report says so, and nothing
  else will.
* Bad, because `bussinessType` is an undocumented integer. 4, 5 and 10 are named
  from what the account contains; anything else is kept and reported as `other`,
  never guessed at.
* Neutral, because the OpenAPI stock sync is untouched. The ledger is an
  addition, not a replacement.

### Confirmation

`api/tests/costs/test_jlc_ledger.py`, sixteen tests. The load-bearing ones: a
cancelled movement is not a movement; a warehouse pick and a code-less row are
bookable while a documented row never is; a draw JLC gave back nets out;
booking writes one uncharged measured draw and twice is a no-op; booking refuses
more than the pool holds; and the refresh rewrites a cancelled lot as a fee,
keeps a hand-written annotation, and refuses both a vanished lot and a shrink
that contradicts bound draws.

## Pros and Cons of the Options

### Sync the ledger and reconcile

* Good, because every correction has a URL behind it and can be re-derived.
* Bad, because it is a new table, a new fetch and a second JLC surface to keep
  working.

### Keep reading it by hand

* Good, because it costs no code.
* Bad, because it found these two only after a day of chasing, and it cannot
  find the next one. A pasted page is also not evidence a later reader can
  check.

### Infer cancellations from the parts orders

* Good, because it needs no new endpoint, and it IS how `fee_only` now works.
* Bad, because it is only half. It catches a cancelled lot and can never catch a
  warehouse pick, which no order mentions at all.

## More Information

* [0034](0034-stock-moves-when-the-supplier-says-so.md) — the same principle one
  step earlier: what the supplier reports is written when they report it, and
  who pays is a separate fact. An uncharged draw exists because of that record.
* [0027](0027-a-stock-count-corrects-a-fifo-guess.md) — the supplier's count
  outranks our inference.
* [production-economics.md](../reference/production-economics.md) — the pool,
  the ledger, and how a disagreement is read.
* Revisit this if JLC changes the endpoint or the key. The ledger is an
  undocumented web API; `jlc_web.get_component_changes` is the single place that
  knows its shape.
