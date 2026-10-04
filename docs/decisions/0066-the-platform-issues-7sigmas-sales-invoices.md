---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04 to the two-company plan)
---

# Issue 7Sigma's sales invoices on the platform, which numbers them from 2026-10-04

## Context and Problem Statement

7Sigma issued its sales documents with its own script (`7sigma.py`). The script
kept every document since 2021 in `rejestr.json` (158 documents: VAT invoices,
proformas, corrections and advance invoices), its buyers in `klienci.json`, a
monthly invoice in `cykliczne.json` and a price list in `produkty.json`. Once a
month an agent wrote a draft, and the user uploaded its FA(3) XML in the KSeF
Taxpayer Application by hand.

The user's answers of 2026-10-04:

* 7Sigma needs VAT invoices, corrections, proformas and advance invoices,
  written and generated from the website much as the script did.
* The platform is the numbering authority from today.
* All buyers in the script's data are added.
* 9SIGMA has its own invoicing system. The platform never creates a 9SIGMA
  invoice; 9SIGMA is only read from KSeF.
* KSeF is read-only for now.

## Decision Drivers

* An issued invoice is a legal document: its amounts are exact and stay as
  issued, and it changes only by a correction.
* A number is never given out twice, including a number written directly in
  KSeF.
* An XML that KSeF would refuse is caught before anybody uploads it.
* History comes in as it was printed, arithmetic errors included.

## Considered Options

* Extend the order invoice (`OrderInvoice`), which holds a header only.
* A sales invoice table whose document is kept whole, with typed columns for
  what lists and the books need.
* A table per part (positions, payments, corrections).
* A PDF from a browser engine (the script used Chrome) or from PyMuPDF's HTML
  engine, already in the api image.

## Decision Outcome

Chosen options: "a sales invoice table whose document is kept whole" and
"PyMuPDF's HTML engine". An order invoice must belong to an order and a
project, and the monthly invoices belong to neither. A table per part would
split one printed page into rows that imported history cannot always fill.
A browser engine would add a second runtime to the image.

1. **`sales_invoices` holds a company's sales documents**: VAT, proforma,
   correction and advance. `body` is the document as printed (seller, buyer,
   positions, totals per rate, payment, bank account, extra lines, the
   correction and advance blocks). The typed columns (number, dates, buyer,
   totals, due date, paid, KSeF number) serve lists and the books. Amounts are
   exact decimals rounded half-up to the grosz, VAT computed per position.
2. **Only a company marked `issues_invoices` gets invoices written.** 7Sigma
   is; 9SIGMA is not, and the platform refuses one for it.
3. **Four series restart every month**: `NN/MM/RRRR`, `PROF NN/MM/RRRR`,
   `KOR NN/MM/RRRR`, `ZAL NN/MM/RRRR`. The next number is one above the
   highest number of the series in that month, read from every document that
   is not a cancelled draft: the imported history, and the invoices KSeF
   holds once they are read in.
4. **A VAT, correction or advance invoice starts as a draft.** Its FA(3) XML
   is written on download and refused unless the Ministry's schema accepts
   it (vendored in the api). A person uploads it to KSeF on the invoice's
   date, then records the KSeF number; with the official XML its hash puts
   the KSeF verification QR code on the PDF. A proforma is issued when written
   and never goes to KSeF. An issued invoice changes only by a correction.
5. **The FA(3) writer covers VAT, KOR and ZAL in PLN** with the rate codes the
   schema documents. A correction states the difference after minus before and
   marks the positions before it; an advance takes its VAT from the gross
   received, and names the order. A settlement invoice after advances (ROZ),
   a foreign currency and the taxi rates are refused until their figures are
   checked.
6. **Recurring invoices** are templates; "Draft for a month" writes the draft
   dated the template's day, once per month.
7. **The script's files are imported once** (admin): buyers matched to the
   shared customers by NIP, the price list, the templates and every document
   as printed. Customers are matched by NIP everywhere.
8. **Two dependencies are added to the api**: `segno` draws the QR code and
   `xmlschema` checks the XML. Both are pure Python with permissive licences.

### Consequences

* Good, because the platform holds 7Sigma's whole register and numbers new
  documents from it, so the monthly invoice is one click and one upload.
* Good, because an XML the schema refuses never reaches KSeF.
* Bad, because the upload to KSeF stays manual: the token is read-only, and
  sending invoices to KSeF needs its own decision.
* Bad, because the old register rarely recorded payments, so imported
  documents show "payment not recorded", not paid or overdue.
* Bad, because a settlement invoice after advances still has to be written in
  the KSeF application.
* Neutral, because a sales invoice does not yet feed an order's revenue; the
  order invoice stays the revenue record (decision 0043).

### Confirmation

Tests show the exact amounts and VAT per position, the amount in words, each
series counting on its own and restarting monthly, the refusal of a number in
use (leading zero ignored) and of an invoice for a company with its own system,
VAT, correction and advance XML that the schema accepts, the schema catching a
broken document, the correction's difference, the advance's VAT from the gross,
a recurring draft dated the last day and written once, the QR code once KSeF has
the invoice, and the import of a register document as printed. On the local copy
the import wrote 157 of the 158 documents (the register lists ZAL 01/06/2024 of
2024-04-30 twice), 6 new buyers and 1 matched by NIP, 2 templates and 4 prices;
the next VAT number of October 2026 was 02/10/2026, after 01/10/2026 in KSeF.

## Pros and Cons of the Options

### Extend the order invoice

* Good, because revenue already lives there.
* Bad, because it needs an order and a project, and has no positions.

### A table with the document kept whole

* Good, because history imports as printed, and one invoice is one row.
* Bad, because a question about positions reads the JSON.

### A table per part

* Good, because every field is a column.
* Bad, because imported documents cannot always fill the parts.

### PyMuPDF's HTML engine

* Good, because it is in the image and prints Polish text and images.
* Bad, because the layout is tables only, not flex boxes.

## More Information

The rules are in [docs/reference/sales-invoices.md](../reference/sales-invoices.md).
