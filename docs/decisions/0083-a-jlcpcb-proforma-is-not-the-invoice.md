---
status: "accepted"
date: 2026-10-06  # accepted 2026-10-06 (user: "ok, go ahead")
decision-makers: Mateusz Kowalik
consulted: Claude
---

# A JLCPCB proforma is not the invoice: the final one is drawn when JLCPCB issues it

## Context and Problem Statement

The first backfill under
[0082](0082-a-jlcpcb-parts-invoice-is-drawn-from-its-data.md) attached a
PDF to nine parts orders on 2026-10-06. Three of them (3196, 3197, 3201) are
proformas: JLCPCB prints "Proforma Invoice" while any lot of the order is
still being sourced, and the final invoice exists only once every lot is
completed or cancelled. Item 3 of 0082 skips a document that already has a
PDF, so these three would never get their final invoice. The proformas were
also saved under the final invoice's file name, `componentInovice`.

## Decision Drivers

* The accountant must not get a proforma as the invoice.
* The final invoice should appear without a manual step.
* No file is ever replaced: the proforma stays as a record of the order.

## Considered Options

* A proforma does not count as the document's invoice; the final one is
  drawn when JLCPCB issues it.
* Attach nothing while JLCPCB issues a proforma.
* Keep 0082 as it is and draw the final invoice with `force` by hand.

## Decision Outcome

Chosen option: a proforma does not count, because the order still gets a
document at once, and the final invoice follows by itself.

1. **A proforma is named as JLCPCB's button names it**: `…-JLCPCB-Proforma-
   Invoice-POB….pdf`.
2. **A proforma does not stop the final invoice** (overrides item 3 of 0082).
   Without `force`, a document with a PDF that is not a proforma is skipped.
   A document with a proforma gets nothing while JLCPCB still issues a
   proforma, and gets the final invoice once JLCPCB does. The final invoice
   becomes the headline file; the proforma stays in the list.
3. **A parts-order refresh draws it.** `POST /api/jlc/import/parts/{pob}/refresh`
   attaches the PDF after a refresh, also when the refresh had nothing to
   change, because a lot can complete at the price already booked.
4. **The result says so**: a proforma carries the warning "proforma: JLCPCB
   is still sourcing N lot(s); not the final invoice", in the API result and
   the audit row.

### Consequences

* Good, because the final invoice reaches the document on the refresh the
  user already does when JLCPCB completes a lot.
* Bad, because a document carries two PDFs for one order, the proforma and
  the invoice. The file names tell them apart.

### Confirmation

`api/tests/costs/test_jlc_invoice_pdf.py`: a proforma is named so and
carries the warning, a second proforma is not attached, the final invoice is
attached beside it and becomes the headline file, and nothing more is
attached after that.

## Pros and Cons of the Options

### Attach nothing while JLCPCB issues a proforma

* Good, because the accountant can never receive a proforma by mistake.
* Bad, because an order JLCPCB sources for weeks has no document at all, and
  the proforma is the only record of what JLCPCB quoted.

### Draw the final invoice with `force` by hand

* Good, because no code.
* Bad, because somebody has to remember it for every sourced order.

## More Information

Overrides item 3 of [0082](0082-a-jlcpcb-parts-invoice-is-drawn-from-its-data.md).
Code: `api/app/services/jlc_invoice_pdf.py` (`attach`, `filename`),
`api/app/routers/jlc_import.py` (`refresh_parts`, `_attach_invoice_pdf`).
