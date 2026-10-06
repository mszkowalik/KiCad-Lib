---
status: "accepted"
date: 2026-10-07
decision-makers: Mateusz Kowalik
consulted: Claude (the user's request of 2026-10-07)
---

# A printed invoice can be read from the document's own file

## Context and Problem Statement

Decision [0084](0084-a-supplier-invoice-keeps-its-tax-data-in-the-ksef-structure.md)
gave a supplier document its tax data (`body`, the sale, due and receipt
dates, the VAT in PLN) and let only KSeF write `body` (its item 4). The user,
2026-10-07: "just deploy and then properly backfill the data", after asking
the day before to "backfill all the invoices with proper data from them".

KSeF holds 199 of the 1,034 supplier documents on production. About 760
others have a PDF original, filed by the accounting import of 2026-10-05/06.
Nothing could store what those files print. Also, decision
[0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md) refuses
every in-place edit to a document that charges a closed batch, so the tax
fields of most production documents could not be written at all.

## Decision Drivers

* The data comes from the invoice itself, not from a guess or a second
  source.
* A transcription can be wrong. The platform must check it, and keep a
  difference visible instead of correcting anything silently.
* The tax layer moves no money: costs read the net and the positions only.
* No name typed by a client is stored as who did it
  ([0050](0050-every-change-names-the-person-who-made-it.md)).

## Considered Options

* A route that stores a checked transcription of one of the document's own
  files.
* Let the PATCH of a document write `body`.
* Fill only the typed fields (VAT, dates) and leave `body` to KSeF.

## Decision Outcome

Chosen option: "a route that stores a checked transcription of one of the
document's own files", because it keeps the page tied to the file it came
from, and every disagreement on record.

1. **`PUT /api/run-documents/{doc_id}/printed-invoice` stores a
   transcription of one file the document holds** (`attachment_id`): the
   number, the issue and sale dates, the currency, and the page in the shape
   of `body`. This amends item 4 of 0084: `body` is written by KSeF, or from
   the document's own file through this route. The UI still never edits it.
2. **The page is checked before it is stored** (`printed.problems`): the
   positions add up to the net, the rates add up to the net and the VAT, and
   the net plus the VAT is the gross, each within 0.05. It is also compared
   with the document's currency, number, date, net and VAT.
3. **A page with problems needs a reason.** Without one the answer is 409
   with the problems, and nothing is written. With one, the problems and the
   reason are kept with the page (`body.source`), and the document view shows
   them.
4. **The printed VAT replaces the typed `tax_amount`.** The net, the
   positions, the currency, the date and the pinned rate never change: a
   printed net that differs from the document's is a problem on record, not
   a correction.
5. **The route writes on the document of a closed batch.** The lock of 0044
   protects what a batch cost, and these columns are not part of it.
6. **A document KSeF holds refuses the route** (its XML is the invoice), and
   so does an in-house transfer (it has no invoice).
7. **`body.source` says where the page came from**: `{kind: "ksef",
   ksef_number}`, or `{kind: "file", attachment_id, filename, actor,
   read_on, problems, reason}`. `actor` is the signed-in user (0050).
8. **The receipt day is not read from a file.** A PDF does not print when it
   arrived, so a document KSeF does not hold keeps `received_date` empty, and
   the books read its issue date.

### Consequences

* Good, because every document with an original can carry the invoice it
  prints, and its VAT reaches the books.
* Good, because a disagreement between the page and the document stays on
  record with its reason.
* Bad, because a transcription is only as good as its reader. The checks
  catch a page that does not add up, or that disagrees with the document,
  but not a wrong figure that is consistent everywhere.
* Bad, because a closed batch's document now changes in one place after the
  close. The change is cost-neutral, and the audit log holds it.

### Confirmation

`tests/costs/test_printed_invoice.py` shows that a page is stored with its
source and leaves the net and the positions alone, that a page with problems
needs a reason and keeps it, that a page that does not add up is refused, that
a foreign page keeps its VAT in PLN, that the route writes where the closed
batch lock refuses a PATCH, and that a KSeF document and a file of another
document are refused.

## Pros and Cons of the Options

### A route for a checked transcription of the document's own file

* Good, because the page names its file and its problems.
* Bad, because it is a second writer of `body`.

### Let the PATCH write `body`

* Good, because no new route.
* Bad, because PATCH is refused on a closed batch's document, and it carries
  no file, no checks and no reason.

### Fill only the typed fields

* Good, because it is smaller.
* Bad, because the positions and their VAT rates, which the user asked for,
  stay on paper.

## More Information

Extends [0084](0084-a-supplier-invoice-keeps-its-tax-data-in-the-ksef-structure.md)
(amends its item 4) and narrows
[0044](0044-a-correction-is-an-event-not-an-edit-to-the-past.md) for the tax
layer only.
