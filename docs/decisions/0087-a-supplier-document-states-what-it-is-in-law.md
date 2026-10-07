---
status: "accepted"
date: 2026-10-07
decision-makers: Mateusz Kowalik
consulted: Claude (the user's questions and answers of 2026-10-07; the statute texts listed under "More Information")
---

# A supplier document states what it is in law, and the books deduct only the VAT the law allows

## Context and Problem Statement

The user, 2026-10-07: "some documents are not only invoices - car leasing can
send me a document that is still a cost, but is not an invoice, for example
insurance for car or the company. please verify how does this stack up against
polish law and possible document types. make sure we're going to cover
documents that we already have in the database (like LN_ documents from PKO
leasing for my car etc.)". After the findings: "1. its 50/50 mixed use, so
50% VAT 2. build all".

`RunCostDocument.doc_type` says how the platform counts the money: a proforma
is not stock, a transfer moves stock between the companies, a correction
corrects a closed batch ([0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md)).
It is not a legal classification. The company books
([0068](0068-a-company-has-overhead-and-books.md),
[0084](0084-a-supplier-invoice-keeps-its-tax-data-in-the-ksef-structure.md))
counted the VAT of EVERY document as deductible.

The statute texts say otherwise:

* Input VAT comes from an invoice (art. 86 ust. 2 pkt 1 of the VAT act) and,
  for an import, from the customs document the importer received (art. 86
  ust. 2 pkt 2 lit. a), no earlier than the month it was received (art. 86
  ust. 10b pkt 1).
* A receipt with the buyer's NIP up to 450 PLN is a simplified invoice (art.
  106e ust. 5 pkt 3). Without the NIP it is not (art. 106e ust. 6). A single
  ticket is an invoice with reduced data (§ 3 pkt 4 of the invoicing
  regulation, Dz.U. 2021 poz. 1979).
* A debit note, an interest note, an insurance policy and a bank statement
  are KPiR proofs (§ 7 of the KPiR regulation, Dz.U. 2025 poz. 1299) but no
  invoice, so they give no input VAT. A lessor re-charges insurance with a
  note because the supply is exempt (art. 43 ust. 1 pkt 37, art. 106b ust. 2).
* A passenger car in mixed use gives 50 % of the VAT on its costs, leasing
  included (art. 86a ust. 1 and 2). The full deduction needs exclusive
  business use, shown by the rules of use and a mileage log (art. 86a ust. 3
  pkt 1 lit. a, ust. 4).
* Accommodation and catering give no input VAT (art. 88 ust. 1 pkt 4).

The platform held 1034 supplier documents: 861 invoices by their printed
title, PKO Leasing debit notes (LN), interest notes (IM), a note correction
(LO), internal vouchers (DOW), receipts and placeholders. It held no customs
document at all, so the import VAT of every JLCPCB and LCSC parcel was in no
month.

## Decision Drivers

* The books must deduct the VAT the law allows, not every figure typed.
* No money path may change. Costs, stock, lots and the register read the
  same columns as before.
* An unclassified document must not hide VAT the company can deduct.
* Import VAT is deducted from the customs document, and the goods' money is
  already on the supplier's invoice. It must count once.

## Considered Options

* Add the legal kinds to `doc_type`.
* A separate `kind`, plus a VAT limit for what was bought.
* Leave the estimate as it is, and rely on the accountant's figures.

## Decision Outcome

Chosen option: "a separate `kind`, plus a VAT limit" (user, 2026-10-07:
"build all"), because the paper and the money treatment are two different
facts: a debit note and an invoice count their money the same way and differ
only in their VAT.

1. **`run_cost_documents` gains `kind` and `vat_rule`.** `kind` is what the
   paper is in law, from the closed list in `services/doc_kinds.KINDS`, each
   with a flag "the VAT on it can be deducted". `vat_rule` is a limit set by
   what was bought: `car_mixed` (50 %) or `accommodation_catering` (0 %).
   "" means not decided, and an undecided document counts its VAT in full, as
   before, so a gap never hides VAT.
2. **`doc_type` keeps its meaning.** It still decides how the money counts.
   `kind` decides only the share of the VAT that is deductible
   (`doc_kinds.deductible_share`).
3. **The books count `tax × share` as purchase VAT**, in the month of
   [0084](0084-a-supplier-invoice-keeps-its-tax-data-in-the-ksef-structure.md),
   and the rest as `purchase_vat_excluded`, per month and in the totals.
4. **`PUT /api/run-documents/{doc_id}/kind` writes the two fields alone.**
   It moves no money, so it works on a closed batch's document, like the
   printed invoice of [0085](0085-a-printed-invoice-can-be-read-from-the-document-s-own-file.md).
   The create, the patch and the batch edit take them too, and
   `GET /api/document-kinds` lists both vocabularies. An in-house transfer
   takes no kind but `transfer`.
5. **A KSeF import sets `kind` from KSeF's invoice type** (`RodzajFaktury`:
   `Vat`, `Kor`, `Zal`, `Roz`, `Upr`, ...) when nobody set one. A person's
   choice stays.
6. **A customs document enters as the courier's certified declaration.**
   `POST /api/customs-documents` takes the PZC XML in any of its three
   formats (`ZC299`, `ZC299H7`, `ZC429`; `services/customs.py`). It files a
   document of kind `customs_document` for the importer's company, with the
   MRN as its number and external id, the acceptance date as its date and
   tax point (art. 19a ust. 9), the day it reached the importer as
   `received_date`, the payable import VAT (B00) as `tax_amount`, a total of
   0, and the XML as its evidence. The debt notice (ZC291, ZCX91) and the
   release notice (PW229, PW429) are refused: they are not the declaration.
   The same MRN twice returns the first document.
7. **The import VAT counts once.** The goods stay on the supplier's invoice.
   JLCPCB's prepaid import tax position stays `excluded` with the reason
   `reclaimable_vat`, as before, so it is no cost, and the customs document
   gives its deduction.
8. **Both leased cars are `car_mixed`.** The user stated mixed use. PKO
   Leasing contract 22/003970 is a Tesla Model 3 and 22/019405 a Volkswagen
   SUV, registration ZS091PR (PKO Leasing's own mails, 2022). Art. 86a ust. 3
   and 4 make 50 % the rule for a car without a mileage log, so the flag
   leaves a car only when the user states exclusive business use.
9. **Every existing document is classified once, and the mailbox's customs
   declarations are filed.** The PKO Leasing series, the KSeF type and
   `doc_type` decide where they can. Readers decide the rest from each
   document's text, and a second reading checks every answer that moves VAT.
10. **The web form and the agent tool take both fields.** Invoices → Edit
    this invoice has "Legal kind" and "VAT limit", the document view prints
    the kind and the deductible share, the books print the VAT that is not
    deductible, and the Invoices toolbar files a customs XML.
    `create_supplier_invoice` takes `kind` and `vat_rule`.

### Consequences

* Good, because the VAT estimate follows the law: notes, policies and
  receipts without the NIP stop adding VAT, the cars add half, hotels and
  restaurants none.
* Good, because the import VAT of the courier parcels reaches the books, in
  the month each declaration arrived.
* Good, because no money path changed.
* Bad, because the estimate drops for every month with a car invoice. That is
  the correct figure, but it differs from the earlier one.
* Bad, because the income-tax side of a car (75 % of its costs in mixed use,
  art. 23 ust. 1 pkt 46a of the PIT act, and the limit on the car's value)
  is not modelled. The income-tax estimate still counts the cars' costs in
  full.
* Bad, because the duty (A00) of a declaration is in no cost: JLCPCB charged
  it inside the excluded import tax position. One parcel of 2026 carried
  137 PLN.
* Neutral, because a document nobody classifies counts as before.

### Confirmation

`tests/costs/test_doc_kinds.py` shows the share of each kind and limit, the
books' deductible and excluded VAT, the kind written on a closed batch's
document, the refusal of an unknown kind and of a transfer's other kind, the
KSeF type filling an empty kind and keeping a chosen one, the three
declaration formats read to the same facts, the debt and release notices
refused, a declaration filed once with its VAT in the month it arrived, and a
foreign importer refused.

## Pros and Cons of the Options

### Add the legal kinds to `doc_type`

* Good, because one field.
* Bad, because `doc_type` already drives money (`proforma` is skipped by the
  pool, `transfer` by the books, `correction` by the lock). A debit note that
  is a cost would need a new money rule for each new kind.

### A separate `kind`, plus a VAT limit

* Good, because each field says one thing, and no money path reads `kind`.
* Good, because a limit set by what was bought (a car, a hotel) works on any
  paper, an invoice or a correction.
* Bad, because two more fields to keep right.

### Leave the estimate as it is

* Good, because nothing to build.
* Bad, because the estimate overstates the deduction by every note and every
  car invoice, and shows no import VAT.

## More Information

Statute texts read for this decision, 2026-10-07: the VAT act, consolidated
text Dz.U. 2026 poz. 1263 (art. 19a ust. 9, art. 43 ust. 1 pkt 37, art. 86
ust. 2 and 10b, art. 86a, art. 88 ust. 1 pkt 4 and ust. 3a, art. 106b, art.
106e ust. 5 and 6, art. 106k repealed, art. 145n); the KPiR regulation
Dz.U. 2025 poz. 1299 (§ 6 to § 8); the invoicing regulation Dz.U. 2021 poz.
1979 (§ 3); the KSeF exemptions regulation Dz.U. 2025 poz. 1740. The rules
the code applies are in [company-books.md](../reference/company-books.md).
