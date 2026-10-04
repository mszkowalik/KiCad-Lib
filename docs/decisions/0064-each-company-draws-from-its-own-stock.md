---
status: "accepted"
date: 2026-10-04  # accepted 2026-10-04
decision-makers: Mateusz Kowalik
consulted: Claude (the user's answers of 2026-10-04 to the two-company plan)
---

# Let each company draw only from its own stock, and move stock between them with in-house transfers

## Context and Problem Statement

[0063](0063-two-companies-own-projects-over-time.md) gave every project, batch
and order a company. Stock stayed one pool for both companies: a 9Sigma batch
could draw a part that 7Sigma bought, and neither company's books could say
what it holds. The user requires separate stocks for 7Sigma and 9Sigma, and
in-house stock moves between them. The moves were never filed with any office,
and the platform still has to record them (user, 2026-10-04).

The facts that shaped the decision:

* One JLCPCB account serves both companies. Each JLC invoice states the billed
  company's VAT number (`taxVatBilling`). The ship-to (`taxVat`) can differ:
  one invoice bills 9Sigma and ships to 7Sigma.
* On the local copy, the billed company of 72 of 95 supplier documents can be
  read from their own evidence: the JLC billing VAT number (32), a NIP in the
  PDF text (32), a company name in the PDF text (1), and the date, before
  9Sigma existed (7). Most of the other 23 are JLC parts orders with no stored
  payload. JLC's parts-invoice endpoint returns their billing data, and the
  user allowed reading it through the stored session (2026-10-04, answer 6).
* JLC names the purchase lot each assembly order consumed. A batch draw bound
  to a lot that the other company bought is direct evidence of a move.
* The user did not follow the question about the transfer price (answer 5),
  so this record takes the default proposed in the plan: the sender's cost.

## Decision Drivers

* Each company's stock answers what that company bought, used and holds.
* Nothing changes for anybody until every record names its company.
* A transfer moves value, not profit: both companies' totals together stay
  what they were.
* Evidence decides a buyer. A guess never does, and the folder a file sits in
  is not evidence.
* The stock replay stays the one source of stock events, and the register's
  gap stays zero.

## Considered Options

* A separate pool per company, filtered from the one event list, with an
  admin switch.
* A company tag on each pool entry, with one shared quantity.
* Stock per company from the day of deployment, with history left in one pool.
* A transfer as a pair of stock adjustments.
* A transfer as an in-house document (the receiver's purchase) plus the
  sender's draw.
* A transfer price at the sender's moving average, or at a set price with a
  margin.

## Decision Outcome

Chosen options: "a separate pool per company with an admin switch", "a
transfer as an in-house document plus the sender's draw", and "the sender's
moving average". A shared quantity cannot tell a company what it holds.
Leaving history in one pool would make the first batch after the switch draw
stock that, in its company's books, was never bought. A pair of adjustments
would put a transfer among the losses and stocktake corrections, and would
make no lot the receiver can draw from.

1. **Every purchase, draw and adjustment names a company.** A purchase is its
   document's BUYER (`run_cost_documents.company_id`, with the source of the
   evidence in `company_source`). A draw takes its batch's company, or its
   step's, or its process transformation's. An adjustment takes its charged
   batch's company, or its transformation's, or its project's owner on the
   day. New rows are stamped as they are written (`companies.stamp_stock`).
   A writer that knows better states the company itself: an uncharged JLC
   draw takes the company its assembly invoice billed.
2. **A new JLC import records its buyer** from the billing VAT number, never
   from the ship-to.
3. **A backfill names the companies of the past**, dry run first, from the
   evidence in this order: the JLC billing VAT number, the JLC parts invoice
   asked through the stored session (opt-in), one of our NIPs in the PDF
   text, the buyer block when both NIPs are printed, one company name in the
   text, and the date before 9Sigma existed. A document the sources disagree
   on, or that no source decides, waits for a person, who sets its buyer on
   the invoice.
4. **`stock_per_company` is an admin switch**, off by default. While it is
   off, nothing changes: one pool, as before. It cannot be turned on while any
   live stock record names no company. While it is on, every draw, every
   shortage check, every price and every purchase-loss guard reads the stock
   of the company concerned: a batch's draws read its company's stock, a
   purchase loss reads its buyer's stock, a project view reads its owner's.
5. **A batch draws only from its own company's stock.** A JLC draw that took
   the other company's stock cannot be charged to the batch until a transfer
   covers it, and a prepared-part lot of one company cannot be written off
   against the other company's batch.
6. **A transfer is an in-house document and a draw.** The document
   (`doc_type="transfer"`, numbered `MM nnnn/yyyy`) is billed to the receiver
   and names the sender (`counterparty_company_id`). Its stock positions are
   purchases in the receiver's stock, so each is a lot. One draw per position
   leaves the sender's stock, charged to no batch (`transfer_line_id`). The
   register keeps transfers out of every money total and reports them on their
   own (`transfers_usd`, `transferred_out_usd`). A transfer changes only as a
   whole: every edit path refuses it, and a wrong one is reversed and written
   again. A reversal is refused while the receiver uses what it got.
7. **The price is the sender's cost**: the landed cost of the lot the units
   came from when that is known, else the sender's moving average on the
   transfer date.
8. **The history's transfers are planned, then written.** Each company's stock
   is replayed on its own. A batch draw bound to the other company's lot moves
   that lot, and the draw's binding moves onto the new position. A batch draw
   its company could not cover otherwise comes from the other company's stock,
   when it held the part on that day. One transfer per receiving batch and
   date. A shortfall neither company covers stays short, as it was in the one
   pool. Writing the history is admin work. Each transfer is checked again as
   it is written.
9. **A buyer can change only when the old buyer keeps its draws covered.** A
   new buyer moves every pooled position to the other company's stock, so it
   is guarded as a purchase loss of the old buyer (the rule of
   [0040](0040-a-purchase-cannot-be-removed-from-under-its-draws.md)).

### Consequences

* Good, because each company's stock and value can be read on its own, and
  the transfers say which stock crossed between the companies, when, and at
  what cost.
* Good, because turning the switch on changes no figure that is already
  covered: a transfer carries the sender's cost, so the companies' totals
  together are what the one pool said.
* Bad, because the history's draws keep the unit costs they were priced at
  in the one pool. A company's on-hand value can be a little off its own
  average until its stock turns over. The quantities balance exactly.
* Bad, because on the local copy 18 documents with parts still have no buyer
  after the evidence pass, and until they have one the history plan leaves
  330 shortfalls unexplained. Production must be read again, with the JLC
  session, before the switch is turned on.
* Bad, because finished devices that one company made and the other sold are
  not yet moved by a transfer. That needs a device transfer, which this
  record does not define.
* Neutral, because JLC holds one shelf for one account: the parts-stock page
  compares JLC's count with the selected company's stock, or with both.

### Confirmation

Tests show that:

* a draw takes its batch's company, and an adjustment its project's owner on
  the day;
* with the switch off there is one pool; with it on, a company cannot draw the
  other company's stock, each company replays its own pool, and a purchase
  loss is checked against its buyer's stock;
* the switch cannot be turned on while a document with parts has no buyer;
* a transfer moves stock at the sender's average, needs the sender to hold
  it, keeps the register's gap at zero, and reports its value on its own;
* a used transfer cannot be reversed, and a reversal gives the stock back;
* the history moves what a batch drew from the other company, and a draw
  bound to the other company's lot moves with that lot, its binding moved and
  the lot capacity intact.

## Pros and Cons of the Options

### A separate pool per company, with a switch

* Good, because the one event list stays the one source, filtered per company.
* Good, because the switch lets the code ship before the history is ready.
* Bad, because every caller must say whose stock it reads.

### A company tag on each pool entry

* Good, because the replay barely changes.
* Bad, because one quantity cannot say what each company holds.

### Stock per company from the deployment day

* Good, because no history needs moving.
* Bad, because each company's opening stock would be unknown.

### A transfer as a pair of adjustments

* Good, because no new document type is needed.
* Bad, because a transfer would read as a loss and a found stock, and the
  receiver would get no lot to draw from.

### A transfer as an in-house document plus a draw

* Good, because the receiver's stock gets an ordinary lot and the sender's an
  ordinary draw, which every replay already understands.
* Bad, because the register must keep these documents out of its money totals.

### The sender's average, or a set price

* Good (average), because no margin appears between our own companies.
* Bad (set price), because it needs a price list nobody keeps, and would put
  an internal margin into both companies' figures.

## More Information

The rules are in [docs/reference/companies.md](../reference/companies.md).
The order of work on production: deploy, run the stock backfill with the JLC
lookup, set the remaining buyers by hand, plan and write the history's
transfers, and turn on `stock_per_company`.
