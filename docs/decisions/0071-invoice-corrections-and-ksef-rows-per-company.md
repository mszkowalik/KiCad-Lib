---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (a code review of decisions 0066 to 0068 on 2026-10-04)
---

# Correct an advance as KOR_ZAL, number once, and keep one KSeF row per company

## Context and Problem Statement

A review on 2026-10-04 of
[0066](0066-the-platform-issues-7sigmas-sales-invoices.md),
[0067](0067-the-platform-reads-both-companies-from-ksef.md) and
[0068](0068-a-company-has-overhead-and-books.md) found defects that cannot be
fixed inside what those records state:

* a correction of an advance invoice was written as KOR, which FA(3) does not
  allow for an advance, and the books counted it as revenue;
* an exempt (`zw`) position wrote no legal basis, and a reverse-charge position
  did not say so;
* two writers could take the same number, because nothing in the database
  prevented it;
* an invoice from one of our companies to the other was stored for one company
  only, because a KSeF number was unique across the table;
* the sync read back one week, and an invoice that reaches KSeF later than
  that was never read;
* a purchase typed in by hand before its KSeF record arrived was imported a
  second time, because a hand-typed document has no seller NIP to match.

## Decision Drivers

* The FA(3) XML the platform writes must be one the Ministry's schema accepts
  and one the tax office reads as meant.
* One number, one document.
* A purchase is never in the register twice, and an invoice between our two
  companies is in both companies' inboxes.

## Considered Options

* Refuse a correction of an advance, and keep the unique KSeF number.
* Write KOR_ZAL, give each company its own KSeF row, and widen the read-back.

## Decision Outcome

Chosen option: "write KOR_ZAL, give each company its own KSeF row, and widen
the read-back", because each refusal in the other option leaves a real
document the platform cannot hold.

1. **A correction of an advance is KOR_ZAL** (refines 0066 item 5). It copies
   the order and the advance of the corrected invoice, writes the order before
   (`StanPrzedZ`) and after in `Zamowienie`, and prints both on the PDF. The
   books count it as an advance, not as revenue. **A second correction starts
   from the invoice as already corrected**: the totals before are the
   invoice's plus every issued correction's difference, and the positions are
   the latest issued correction's. A new correction is refused while a draft
   correction of the same invoice is open, or when the latest correction
   states only a difference or a text (one read from KSeF, one from the old
   script).
2. **An exempt position needs its legal basis** (`exemption_basis`, written as
   P_19 with P_19A, B or C), and the writer refuses `zw` without one. A
   reverse-charge position (`oo`, `np II`) writes P_18=1. An EU buyer is
   written with KodUE and NrVatUE. A unit price keeps up to 8 decimals in the
   XML and on the PDF, and the net is computed from that price.
3. **A payment is recorded once.** Marking an invoice paid that is paid
   already is refused, and it never changes an imported invoice's printed
   amount. An imported advance keeps its printed advance in the document.
4. **A number is unique per company and series** (refines 0066 item 3): a
   partial unique index on (company, kind, number) for every document that is
   not cancelled and not imported history. The imported history is outside
   the index, because it holds one printed duplicate. An automatic number is
   taken again on a conflict; a typed number already in use answers 409. A
   draft re-dated into another month takes that month's next number.
5. **A KSeF row is unique per company** (refines 0067 items 4 and 5). An
   invoice between our two companies is a sales row of the seller and a
   purchase row of the buyer.
6. **The sync reads back 60 days** before the newest issue date it read
   (refines 0067 item 3). The upsert is idempotent, so reading again costs
   only time.
7. **A purchase that may already be typed in asks first** (refines 0067 item
   5). A document of the same company or of none, with no seller NIP, the same
   number (case, spaces and leading zeros ignored), and the same date or a
   shared word of the seller's name, is a candidate. The import answers 409
   with the candidates. The person links one or imports anyway.
8. **The books count each document once, as printed** (refines 0068 item 2): a
   correction its difference only, an imported advance its advance amount, a
   correction with no amounts nothing, a settlement (ROZ) read from KSeF the
   whole order on its date. An overhead position is never charged to a batch
   on any write path.

### Consequences

* Good, because every document the platform writes or reads can be held, and
  each is counted once.
* Good, because the database itself refuses a second document with the same
  number.
* Bad, because a sync reads about two months again each time, which takes
  longer against KSeF's hourly limit.
* Bad, because an invoice between our two companies is still a purchase of the
  buyer when imported: imported with its parts in the pool, it adds stock the
  seller's books never released. An in-house transfer
  ([0064](0064-each-company-draws-from-its-own-stock.md)) and an imported
  invoice for the same goods must not both exist. This record does not decide
  which one wins.

### Confirmation

Tests in `api/tests/costs/test_sales_invoices.py`,
`api/tests/costs/test_company_books.py` and `api/tests/costs/test_ksef.py`
show each rule above: KOR_ZAL passes the schema check, the annotations follow
the rates, an EU buyer keeps its VAT number, two writers never get the same
number, an invoice between our companies is in both inboxes, the sync reads
back far enough, a hand-typed purchase is not doubled, and the books count a
linked correction once, an imported advance at its amount and a settlement as
the whole order.

## Pros and Cons of the Options

### Refuse, and keep the unique KSeF number

* Good, because nothing new is written.
* Bad, because a real correction of an advance, and the buyer's side of an
  invoice between our companies, could not be held at all.

### KOR_ZAL, a row per company, a wider read-back

* Good, because the platform holds what KSeF holds.
* Bad, because the sync is slower and the import asks one more question.

## More Information

The rules are in [docs/reference/sales-invoices.md](../reference/sales-invoices.md),
[docs/reference/ksef.md](../reference/ksef.md) and
[docs/reference/company-books.md](../reference/company-books.md).
