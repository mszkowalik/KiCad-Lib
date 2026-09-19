---
status: "accepted"
date: 2026-09-18
decision-makers: Mateusz Kowalik
---

# Rebuild the CE_Dongle_V2 device log from the facts instead of correcting it

## Context and Problem Statement

[0003](0003-orders-shipments-and-device-history.md) makes `device_events`
append-only: a delivery is undone by `unshipped`, a shipment by
`reverse_shipment`, and history is never deleted. That rule is what makes the
log evidence.

The CE_Dongle_V2 log stopped being evidence. Of its **4,427 deliveries, 4,326
were FIFO guesses** — `fifo_candidates` picked the oldest devices whenever a
shipment was given a quantity instead of serials ([0003](0003-orders-shipments-and-device-history.md) §6).
Only **101** were ever observed: the serials scanned out on 2026-09-17 and
2026-09-18. On top of the guesses sat their corrections — 147 `unshipped`
events, a shipment reversed and re-recorded as a duplicate, and 75 anonymous
units standing in for devices nobody could name.

A week of forensic work settled what actually happened
([dongle-stock-reconciliation.md](../reference/dongle-stock-reconciliation.md)):
every batch's real output from the flasher's own records, the 32 old-button
units that were never sent, the one scrapped unit, and which batch supplied
which order. The platform disagreed with all of it.

Appending corrections to 4,326 guesses does not produce a true history. It
produces a true *balance* on top of a record that still says a guess was an
observation, and every later reader has to know which rows to disbelieve.

## Decision Drivers

* A guess and an observation must not be indistinguishable. That is the failure
  this whole clean-up exists to remove, and preserving the guesses preserves it.
* The corrections would outnumber the facts. Roughly 4,400 reversals to express
  ~4,500 deliveries.
* The 101 scanned serials are real evidence and must survive untouched.
* Everything else in the log is derivable from records that DO exist — the
  flasher's device rows and the invoices.

## Considered Options

* Delete the CE_Dongle_V2 events and rewrite them from the agreed facts.
* Append `unshipped` reversals and re-ship everything correctly.
* Leave the log and correct only the quantities.

## Decision Outcome

Chosen option: "Delete and rewrite", via
`scripts/rebuild-dongle-device-history.py`, run once per database.

1. **This is an exception to [0003](0003-orders-shipments-and-device-history.md),
   not a repeal of it.** It applies to one project, once, because that project's
   log is inference rather than observation. Every future delivery names its
   serials ([0032](0032-a-shipment-names-its-devices.md)), so no log will be in
   this state again — and if one is, that is a bug to fix, not a precedent to
   cite.
2. **The 101 scanned deliveries are carried through unchanged**, on their own
   shipments, with a note recording that the serial was observed. They are the
   only rows in the whole history that were.
3. **Everything else is rebuilt from the cascade**: the pool of 4,326
   deliverable devices allocated oldest-programmed-first across the orders in
   the sequence they shipped. It reproduces the user's independent account of
   order 1 — 489 from Batch 1, then 11 from Batch 2 — without being told it,
   which is the strongest check available that the method is sound.
4. **85 records are created for deliveries that really happened and were never
   recorded**: 45 `PROTO-nnnn` prototypes (35 sold to orders 12 and 13, 10 on
   the shelf) and 40 `PH-nnnn` placeholders for the 2026-09-03 delivery, where
   191 units physically left and only 151 can be named. Each placeholder
   carries a note saying so, so it can be replaced if a real serial surfaces.
5. **The 32 old-button units become `in_stock` + `faulty`, not `disposed`.**
   They are on the shelf and will never be sold. Filing them as destroyed was
   the only way to keep a shipment from picking them before `condition` existed.
6. **Anonymous units are gone.** All 75 are replaced by named records, and
   [0031](0031-a-batch-that-records-its-devices-has-no-anonymous-units.md)
   stops anything writing a new one.
7. **The shared shipment headers are reused, not recreated.** Orders 2, 7, 8, 10
   and 13 carry CE_Aqua_V2 lines on the same delivery; only the dongle events
   and the dongle anonymous lines are touched.
8. **The script refuses to commit unless the invariant balances on every batch**
   — `programmed = at customer + in stock + scrapped` — and it verifies through
   the platform's own reads, not its own arithmetic.

### Consequences

* Good, because every delivery in the log is now either a fact or a clearly
  labelled placeholder, and the two are told apart by looking at the row.
* Good, because the stock figures finally close: 4,548 devices, 4,502 with
  customers, 35 faulty on the shelf, 10 prototypes, 1 scrapped, and every
  batch's invariant balancing.
* Good, because orders 17 and 19 now report what is genuinely owed — 8 and 500 —
  instead of being papered over by invented units.
* Bad, because roughly 9,200 event rows are deleted, and the reversals that
  recorded somebody's earlier corrections go with them. The audit log and the
  journal keep their own record of those writes; the device log does not.
* Bad, because the 4,326 rebuilt deliveries are still INFERENCE. They are
  better-founded inference, and the placeholders are honest about it, but a
  delivery before 2026-09-17 says which device left only on the balance of
  evidence.
* Neutral, because `production_run_id` on the rebuilt `produced` events comes
  from the device rows, which the flasher wrote, so batch attribution is
  unaffected by any of this.

### Confirmation

The script's own verification, which must pass before it commits: all seven
batches balance (521/489/32, 349, 406, 599, 568, 992, 1025/1024/0/1), the pool
divides with nothing left over, the total is 4,548, and every order except 17
and 19 reads delivered-in-full through `sales_order_lines`. Rehearsed against a
production copy on 2026-09-18, which caught two real defects before any write:
351 devices left reading `in_stock` because Batch 6 was still being programmed
after order 10 shipped, and the scrapped unit reading `in_stock` for the same
reason.

## Pros and Cons of the Options

### Delete and rewrite

* Good, because the result is a log you can read without a key to which rows lie.
* Bad, because it deletes history, which this codebase otherwise never does.

### Append reversals and re-ship

* Good, because it keeps [0003](0003-orders-shipments-and-device-history.md)
  intact.
* Bad, because ~4,400 reversals to express ~4,500 deliveries leaves a log whose
  every row needs interpreting, and the guesses stay in it looking like
  observations.

### Correct only the quantities

* Good, because it is the smallest change.
* Bad, because the quantities were never the problem. Which device went where is.

## More Information

* [dongle-stock-reconciliation.md](../reference/dongle-stock-reconciliation.md)
  — the facts this is built from, and how they were established.
* [0032](0032-a-shipment-names-its-devices.md) — why no future log can end up
  like this one.
* [0031](0031-a-batch-that-records-its-devices-has-no-anonymous-units.md) — why
  the 75 anonymous units cannot come back.
* Revisit this only if a second project's log turns out to be inference at this
  scale. One exception is a repair; two is a sign the write path is still wrong.
