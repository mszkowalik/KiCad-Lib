---
status: "accepted"
date: 2026-09-24
decision-makers: Mateusz Kowalik
---

# A JLC parts lot costs what JLC settled, and its draws move with it

## Context and Problem Statement

JLC sells a `buy` lot at an ADVANCE (`goodsPaidMoney`) and re-settles it
once the supplier quotes: it refunds the difference or charges a supplement.
It cancels some lots outright and refunds them. The platform booked the
advance. On 2026-07-28 the difference between the advance and the invoice was
read as a "$1,623.23 sourcing fee", and every JLC parts document was moved UP
to the advance.

On 2026-09-24 JLC's own fields showed otherwise. 18 lots carry a partial refund
(`partRefundMoney`, $1,250.76) with JLC's reason "the estimated price paid is
higher than the actual price quoted by the supplier". 4 cancelled lots
($376.96) were refunded in full. 3 lots were charged supplements ($65.02). The
parts invoice's `paidMoney` equals the settled sum on all 20 orders. Our 9
affected documents stood $1,571.60 above JLC's invoices. The detail is in
[../jlcpcb-web-api.md](../jlcpcb-web-api.md).

A draw keeps the unit cost it was written with. Correcting a lot's price
without its draws leaves the lot's value negative once they have used it, and
the batches that used it keep the old cost.

## Decision Drivers

* The number must match what left the bank. JLC's invoice is the check.
* A correction must be reversible and repeatable, not a one-off script. Two
  earlier corrections of these same lots went in opposite directions.
* A batch that closed its books ([0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md))
  must not change under it.

## Considered Options

* **Settled money, and move the bound draws.** A lot costs its sub-order's
  `settlePaidMoney / settlePresaleNumber`. A parts refresh re-prices the lot and
  every draw bound to it, in one journalled batch.
* **Settled money for new lots only.** Leaves $1,571.60 of cost that was never
  paid on the existing documents and 15 batches.
* **Correct the documents, leave the draws.** The pool then holds negative
  value on used-up lots, and batch costs stay wrong.
* **Book refunds as separate credit lines.** Keeps the advance visible, but no
  draw can bind to a credit, so every batch cost stays at the advance.

## Decision Outcome

Chosen option: "Settled money, and move the bound draws", because it is the
only one that makes the documents equal JLC's invoices AND the batch costs
equal what their parts cost.

* The importer costs a lot at the sub-order's `settlePaidMoney` (every
  sub-order holds exactly one lot, 285 of 285). A cancelled lot that settled at
  $0 is no line. One settled with money kept is a fee.
* A parts refresh re-prices a lot and moves each bound draw by the difference,
  so a draw's other slices keep their share. It voids the line of a refunded
  cancellation, matched by lot key, or by label and advance for a line written
  without one.
* A refresh REFUSES when a draw it would move charges a closed batch. That
  batch changes only through a correction document.
* The Parts orders list shows "changed at JLC — refresh" when a document's
  total differs from JLC's settled total.

### Consequences

* Good, because every JLC parts document equals JLC's `paidMoney`, and a later
  refund or supplement is one Refresh away.
* Good, because the correction is journalled and reversible per order.
* Bad, because a refresh changes the component cost of batches that shipped
  months ago. Orders that sold their units show a different cost the next time
  they are read. No batch was closed on 2026-09-24.
* Bad, because the refunds are evidenced by JLC's fields and invoices, not yet
  by a bank statement.

### Confirmation

* `api/tests/costs/test_jlc_ledger.py` covers a refund, a supplement, a refunded
  cancellation, the draw move and the closed-batch refusal.
* After the refresh, each POB document total equals JLC's `paidMoney`, the pool
  balances, and the register gap is 0.
