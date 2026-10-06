---
status: "accepted"
date: 2026-10-06
decision-makers: Mateusz Kowalik
consulted: Claude (the user's question and answers of 2026-10-06)
---

# A supplier invoice keeps its tax data in the KSeF structure, beside its cost positions

## Context and Problem Statement

The user, 2026-10-06: "can we use the same structure for invoices as ksef
uses? would it be beneficial for the platform?"

A sales invoice already uses the KSeF structure (FA(3)): `SalesInvoice.body`
has the shape that `ksef/parse.py` reads and `invoicing/fa3.py` writes
([0066](0066-the-platform-issues-7sigmas-sales-invoices.md)). A supplier
document does not. Its model (`RunCostDocument` and `RunCostLine`) splits
money across batches, stock and overhead. A KSeF import kept the net, the VAT
and the positions, and dropped the rest: the VAT rate of each position went
into `notes` as text, and the gross, the sale date, the due date and the
payment were lost. The XML stayed attached.

The company books showed one error that this causes. They counted purchase
VAT from PLN documents only, by the document date. A Polish supplier's
invoice in EUR states its VAT in PLN (FA(3) `P_14_xW`), and that VAT was in no
month.

## Decision Drivers

* The books must count the purchase VAT that the invoice states, in the month
  the law gives.
* The cost model must not change. The stock guard, the lot ledger and the
  register identity depend on its line ids
  ([0040](0040-a-purchase-cannot-be-removed-from-under-its-draws.md),
  [0073](0073-a-draw-takes-the-cost-of-the-lots-it-is-bound-to.md)).
* Most supplier documents are not in KSeF (JLCPCB, foreign suppliers,
  receipts). On the local copy, 72 of 95 documents are in USD or EUR.
* One value has one column. A second copy of a figure drifts from the first.

## Considered Options

* Replace the supplier document model with the FA(3) structure.
* Add the FA(3) tax data beside the cost model.
* Keep the model, and fix only the books.

## Decision Outcome

Chosen option: "add the FA(3) tax data beside the cost model" (user,
2026-10-06: "agreed, build it"), because it gives both sides one structure
for the invoice without touching any money path.

1. **`run_cost_documents` gains five columns.** `body` (JSONB) is the invoice
   as printed, in the shape of `SalesInvoice.body`. `sale_date` (FA(3) P_6),
   `due_date` and `received_date` are ISO days, "" when not stated.
   `tax_amount_pln` is the VAT in PLN of a document in another currency.
2. **The existing columns keep their meaning.** `total_amount` is the net and
   `tax_amount` the VAT, in the document's currency. There is no second net
   or VAT column. A PLN document's VAT in PLN is `tax_amount`, so
   `tax_amount_pln` stays empty on it.
3. **A cost position gets no VAT rate or unit column.** Nothing reads them,
   and the printed positions in `body` hold both. A copy on the cost line
   would drift after a split or an edit.
4. **`body` is written by an import from the supplier's own data, never by a
   person.** A KSeF import writes it, and so does a link of a KSeF invoice to
   a document typed by hand (`ksef.sync.apply_fiscal`). The invoice in KSeF
   is the binding one, so its dates and VAT replace what was typed. The net
   and the positions are never touched.
5. **For a KSeF invoice, `received_date` is the Polish calendar day of KSeF's
   acquisition timestamp.** Art. 106na ust. 3 of the VAT act: an invoice is
   received through KSeF on the day KSeF gives it its number.
6. **The books count a purchase's VAT in PLN, in the first month the law
   allows the deduction** (`company_books.purchase_vat_day`). Art. 86 ust. 10
   and 10b pkt 1 of the VAT act: the period of the supplier's tax point, but
   not before the period the buyer received the invoice. The tax point is
   read as the sale date, else the issue date. The receipt is read as
   `received_date`, else the issue date. Art. 86 ust. 11 lets a deduction
   wait three more months, so the accountant's figure can be in a later
   month; her figure is the one that counts
   ([0068](0068-a-company-has-overhead-and-books.md)).
7. **The parser keeps `P_14_xW`** as `vat_pln`, per rate and in the totals.
8. **Documents imported before this change are filled by an admin job**,
   `POST /api/ksef/fill-documents`, dry run by default, from the XML each one
   stored. Documents that KSeF does not hold are filled from their own
   originals; that work is open in [docs/todo.md](../todo.md).
9. **The web form and the agent tool take the new fields.** Invoices → Edit
   this invoice has VAT, VAT in PLN (for another currency), sale date,
   received and due. `create_supplier_invoice` takes the same. The document
   view shows the printed invoice when `body` exists, with the columns the
   sales page uses (`components/PrintedInvoice.tsx`).

### Consequences

* Good, because purchase VAT in another currency reaches the books, and in
  the month the law gives.
* Good, because a KSeF import keeps the whole invoice, and a sales invoice
  and a supplier document have the same `body`.
* Good, because no money path changed: costs, stock, lots and the register
  read the same columns as before.
* Bad, because a document typed by hand has no `body`. Its tax data is the
  typed fields only.
* Bad, because the VAT month is the earliest month allowed. A deduction the
  accountant takes later shows as a difference between the estimate and her
  figure for those months.
* Neutral, because a purchase under reverse charge or an import of goods
  still adds no purchase VAT, as before: its VAT is not in `tax_amount`.

### Confirmation

Tests in `tests/costs/test_ksef.py` show that the parser keeps `P_14_xW`,
that the receipt day is the Polish day of KSeF's timestamp, that an import
keeps the dates, the VAT and the printed invoice, that a link to a hand-typed
document fills its tax data and keeps its net, and that the fill job fills a
document once. `tests/costs/test_company_books.py` shows that a EUR document
counts its VAT in PLN, in the month it was received, and that a sale date
after the issue date moves the VAT to the sale month.

## Pros and Cons of the Options

### Replace the model with the FA(3) structure

* Good, because there is one structure for everything.
* Bad, because FA(3) has no field for a split, a destination, a production
  step, a lot or a component, and every money path reads those.
* Bad, because most supplier documents are not KSeF invoices, and much of
  FA(3) does not apply to them.

### Add the FA(3) tax data beside the cost model

* Good, because the cost model and every rule built on it stay as they are.
* Good, because the books get the data they need.
* Bad, because two layers describe one document: the printed invoice and the
  cost positions. Rule 4 keeps the printed one read-only so they cannot
  compete.

### Fix only the books

* Good, because it is the smallest change.
* Bad, because the VAT in PLN of a foreign-currency invoice has nowhere to be
  stored, so the fix has nothing to read.

## More Information

Extends [0066](0066-the-platform-issues-7sigmas-sales-invoices.md),
[0067](0067-the-platform-reads-both-companies-from-ksef.md) and
[0068](0068-a-company-has-overhead-and-books.md). Sources for the VAT rules:
art. 86 ust. 10, 10b and 11 and art. 106na ust. 3 of the Polish VAT act
(ustawa o podatku od towarów i usług), as of 2026-02-01.
