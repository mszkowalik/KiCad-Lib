---
status: "accepted"
date: 2026-10-07
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-07)
---

# A JLCPCB assembly invoice is drawn from its data

## Context and Problem Statement

The fill of [0084](0084-a-supplier-invoice-keeps-its-tax-data-in-the-ksef-structure.md)
and [0085](0085-a-printed-invoice-can-be-read-from-the-document-s-own-file.md)
found 14 JLCPCB assembly orders (`W…`) with no file to read. Two of them, both
9SIGMA's, are not with the accountant yet (W202506081910676 and
W2026092300301215), and without a file they cannot be sent. The user,
2026-10-07: "where are the jlc assembly invoices? aren't they available over
jlc api?", and after the options were laid out: "generate those files once you
deploy".

JLCPCB keeps no file for an assembly order. The assembly invoices its DOWNLOAD
button saved for this account are jsPDF 2.5.1 files holding one JPEG of the
page, the html2canvas screenshot that
[0082](0082-a-jlcpcb-parts-invoice-is-drawn-from-its-data.md) found for a
parts order. JLCPCB's web API returns the invoice as data
(`orderCenter/invoiceOrder`), the call the JLC import already makes.

## Decision Drivers

* Each assembly order needs a file the accountant can be sent and the
  platform can read.
* Every figure comes from JLCPCB; nothing is computed.
* A drawn invoice must not claim to be JLCPCB's own page where it differs.

## Considered Options

* Draw the invoice from `invoiceOrder`, one row per order.
* Draw it to match JLCPCB's page row for row.
* Leave the orders without a file.

## Decision Outcome

Chosen option: "draw the invoice from `invoiceOrder`, one row per order"
(user, 2026-10-07), because it gives every order a file from JLCPCB's own
figures with what is available today.

1. **`services/jlc_mfg_invoice_pdf.py` draws the invoice** in the layout of
   JLCPCB's page, measured on W202404272006430: the seller block, a box with
   the invoice number, date, reference (the DHL number), batch, ship-via and
   type of trade, Ship To and Billing To, the order table, and the totals
   Merchandise Total, Shipping, Discount, Subtotal, Import Taxes, Service
   Charge and Grand Total, each only when JLCPCB states it.
2. **The rows are JLCPCB's data, one per order.** JLCPCB's page prints the
   board fabrication inside an assembly order as a row of its own and merges
   it with a bare-board order of the same design, from data `invoiceOrder`
   does not carry. The amounts and every total are the same, because
   `productMoney` is the sum of the order totals (verified on all 35
   invoices by the import). A footer line on the page says the invoice was
   drawn from the data, one row per order.
3. **The buyer fields are decrypted with the key of the call**
   (`get_manufacturing_invoice(..., reveal=True)`), as for a parts invoice. A
   field that cannot be decrypted refuses the drawing.
4. **One route draws both kinds**: `POST /api/jlc/web/invoice-pdfs` picks the
   drawer by the document's order number, POB or W (case ignored; some
   imports stored a lower-case `w`). The file is added, never put in place of
   one, and becomes the headline file; a document with a PDF is left alone
   unless `force`.
5. **The file is named `<date>-JLCPCB-invoice-<W…>.pdf`.** A total or an
   invoice number that disagrees with the document is a warning, never a
   refusal.

### Consequences

* Good, because every assembly order can have a file, so the two unsent
  9SIGMA invoices can go to the accountant.
* Good, because the fill of 0085 can read the drawn file like any other.
* Bad, because the rows differ from JLCPCB's own page. The footer says so,
  and the totals agree.
* Bad, because the drawing depends on an undocumented web API and a live
  JLCPCB session.

### Confirmation

`tests/costs/test_jlc_mfg_invoice_pdf.py` shows that the PDF prints JLCPCB's
figures and the footer, prints a discount and a service charge only when
there, continues on a second page, is filed once and again with `force`,
warns on a disagreeing total, refuses another order's or an undecrypted
response, and that the route picks the drawer by the order number.

## Pros and Cons of the Options

### Draw from `invoiceOrder`, one row per order

* Good, because all the data is in one call the platform already makes.
* Bad, because the rows are not the page's rows.

### Match JLCPCB's page row for row

* Good, because the file would equal the page.
* Bad, because the split of an assembly order's board fabrication needs data
  from further calls that nobody has mapped yet.

### Leave the orders without a file

* Good, because nothing new to build.
* Bad, because two 9SIGMA invoices cannot be sent to the accountant.

## More Information

Extends [0082](0082-a-jlcpcb-parts-invoice-is-drawn-from-its-data.md). The
fill of the 14 drawn files follows
[0085](0085-a-printed-invoice-can-be-read-from-the-document-s-own-file.md).
