# Changelog

## 2026-09-24 (a parts order JLC has not finished is not stock, and devices are boards assembled)

**Correction: importing a JLC parts order put its money in "unassigned" and
added nothing to the pool.** The parts importer wrote no production step, and
since 2026-09-19 the step alone says a line is stock. No parts order was
imported in that window, so no data is wrong. Each lot now imports as
`parts:pool` / `pooled`, and a cancelled lot as `other:cancelled` / `excluded`.

**A paid lot that JLC is still sourcing now imports as money awaiting delivery,
not as stock.** Before this, JLC's settled quantity was booked as stock on hand
the moment the order was paid, at JLC's advance price. The importer now makes
such a lot one line with the new step **Paid, awaiting delivery**, charged to
nobody. It can not be charged to a batch.

- **Production → JLC → Parts orders** shows "(n awaiting)" on an order with
  such lots, and keeps an imported order in the list while its document still
  holds one.
- A new **Refresh** button re-reads an imported parts order from JLC. A lot
  that has arrived becomes pool stock at the price JLC settled.
- A refresh changes where a line's money goes only when the lot changed what it
  is (arrived or cancelled). A destination somebody chose by hand stays.
- A refresh no longer takes a lot out of the pool. It used to compare the step
  against a field the parts planner never set.

**Correction: a JLC order's device count now counts the boards JLC
assembled, not the boards it fabricated.** The importer read `pasteNumber`
(bare boards) where JLC's `allPatchNum` holds the assembled count. The two
differ on the 17 orders where only part of the boards was populated.
`allPatchNum` equals the billed quantity on all 46 assembly orders.

- SMT026092263197 reads 60, not 75. CE_Dongle_V2 Batch 1 reads 250 + 275 =
  525, not 550, and CE_Aqua_V2 Batch 1 reads 125 + 190 = 315, not 325. Both
  now equal their run quantity.
- The next **Sync** on Production → JLC re-reads each cached count once. A row
  still marked "(old reading)" has not been re-read yet.
- The queue shows "n assembled" and, where it differs, "n fabricated".
- Only the queue's run matching and the run-fill check read this count. No
  money and no stock moved.

**Correction: the Stock page no longer counts a JLC library entry that holds
0 pieces as a missing invoice.** Nothing is held, so nothing is missing.

**Correction: a JLC assembly line now closes exactly on its fee breakdown when
the gap is under a cent.** JLC prints a line as quantity × a unit price rounded
to 4 decimals, so the line can sit a fraction of a cent under its own fees. The
importer only added a balancing child from $0.01 up, and the fees then read as
over-allocated. It now adds a "Rounding in JLC's printed unit price" child for
any gap. Document 3199 (W2026092300301215) got its $-0.0025 child by hand.

**Correction: the JLC repair routine would have added a correct purchase a
second time.** `reprice_from_jlc` treated a lot whose line needed no change as
missing. It now also writes a missing lot the way the importer does. Nothing
calls it yet, so no data is affected.

## 2026-09-24 (every change names the person who made it)

**Each write through the API or the UI now records the signed-in person.**
Before this, 73 of 147 audit call sites wrote `actor: "user"`, and about 25
endpoints stored a name that the client sent. Mateusz Kowalik, 2026-09-24.
Decision [0050](docs/decisions/0050-every-change-names-the-person-who-made-it.md).

- The audit log stays the only log. It has two new columns, `user_id` and
  `request_id`, and two new kinds of row:
  - `request`: one for each POST, PUT, PATCH and DELETE, with the method,
    path, status, duration, IP and user agent. It does not store the body or a
    `t=` token.
  - `row.insert`, `row.update`, `row.delete`: one for each database row that a
    request changes, with the old and new values. Passwords, token hashes and
    encrypted secrets are redacted. A value longer than 1000 characters is
    stored as its length and SHA-256.
- An actor of `"user"` is now the person's display name. A robot actor such
  as `jaravis` stays, and `user_id` shows who started it.
- No endpoint accepts a name from the client any more. The `?actor=` query
  parameter and the `author`, `actor`, `created_by`, `approved_by`,
  `updated_by` and `uploaded_by` body and form fields are removed. The name
  always comes from the session or the personal token. A client that still
  sends one is not refused; the value is dropped. Decision
  [0051](docs/decisions/0051-no-endpoint-accepts-a-name-from-the-client.md).
- The Jaravis chat now records the person who sent the message on the
  agent's writes.
- New tab **Admin → Activity** (admin only). It lists requests and events,
  newest first, with a filter for who and one for what. Unfolding a row shows
  everything its request wrote. A chip adds the row changes to the list.
- The agent's `get_audit_log` leaves the `request` and `row.*` rows out,
  unless it is called with `include_tracking`.
- **Production → Write log** has a new **by** column. A batch now records the
  signed-in person, and ignores the `?actor=` the caller sent. Before this, a
  batch said whatever the caller typed: `user`, `claude`, `claude-local`,
  `reconciliation`. Those old values stay.
- A write batch and its request link to each other. Unfolding a request in
  Admin → Activity names its batch and links to the Write log. Unfolding a
  batch shows an admin a link to everything its request wrote.
- Rows written before this change still say `"user"`. Nothing can recover who
  wrote them.

**Correction: Italtronic invoice FV CEE 300452.** Document 864 was the order
confirmation OV CEE 263969, entered as a proforma for 1651.00 EUR. The invoice
arrived on 2026-09-21. The document is now invoice FV CEE 300452, dated
2026-09-21, for 1738.00 EUR: 500 enclosures at 3.302 EUR, plus 87.00 EUR
transport on `logistics:inbound`. The NBP rate was fetched again for the new
date. Both PDFs stay attached.

## 2026-09-23 (the broker password file, from the Devices page)

**Production → Devices has a "Mosquitto passwords" button.** It downloads
`mosquitto_passwords.txt` in PLAINTEXT, one `user:password` line per device.
This is the format the old production tool wrote. The developer who deploys
the broker hashes the file with `mosquitto_passwd -U`. Mateusz Kowalik,
2026-09-23.

- The file follows the project selector and ignores the other filters, because
  the broker needs every device of a project. "All projects" gives the whole
  fleet.
- The file lists every name a device was ever programmed with. 78 units (77
  CE_Aqua_V2, 1 CE_Dongle_V2) were first programmed with a 6-hex name and
  later with a 12-hex name, and both names are in the file. On 2026-09-23 the
  file has 5534 lines for 5456 devices. It contains all 4445 users of the old
  tool's file, with the same passwords.
- 237 older CE_Dongle_V2 units had no stored plaintext password. The export
  derives it again from the username and the fleet salt.
- The export checks each password against the hash the programming run
  stored. If a password does not match, the export fails and names the
  device. It does not write that line.
- A device appears only if a run derived its credentials. CE_Dongle_V3 has no
  lines yet.
- New endpoint `GET /api/flasher/mosquitto?project_id=` (the project is
  optional). The per-project route gives the same file.

## 2026-09-22 (a batch you can edit, and an order you can link to any batch)

**Three screens refused work the API had always accepted.** Each was a control
that rendered only in the case the platform had already solved, or did not
exist at all. Mateusz Kowalik, 2026-09-22.

- **A batch's own figures are editable, on the batch page.** `label`, `qty`,
  `run_date` and `qty_good` are on `PATCH /api/runs/{id}` and had no control
  anywhere in the app, while the page's own docstring said every field was
  editable there — so a batch opened for 50 could not be corrected to the 60
  that were actually built. They are a Batch card at the top of Overview.
- **That card is deliberately stiff to use.** It reads as a list of facts and
  becomes a form only on "Edit…"; nothing is sent until Save, Save stays
  disabled until something differs, and Cancel discards. `qty` and `qty_good`
  are the denominators every per-device cost is divided by and that cost has
  already gone out on orders, so a figure that changes while you tab past it is
  the wrong control. The patch carries only the fields that DIFFER. Both
  quantities stay read-only while the books are closed, which is the rule the
  API already enforced.

- **A batch's design commit is now attachable, re-pointable and detachable.**
  The selector on a batch page was rendered only when the batch already had a
  snapshot, on the assumption that a snapshot-less batch had chosen to be one.
  A batch is routinely opened before its design is committed — CE_Dongle_V3
  Batch 1 was created on 2026-09-19 with its notes saying "no snapshot yet" —
  and nothing on any screen could then give it one. The selector now carries
  "— no snapshot (costs only) —" as a real option, so a turnkey batch can also
  be detached back.
- `PATCH /api/runs/{id}` reads `snapshot_id` out of the fields actually SENT, so
  an explicit `null` detaches while an omitted field still means "leave alone".
  It makes the two checks `create_run` makes and did not: the snapshot must be
  `ready`, and it must build the run's board. Attaching to a batch with no file
  set also imports the repo's `production/` dir at that snapshot, as creating
  the batch with one always did. A closed batch still refuses all of it.
- **The JLC assembly-order row offers every batch, not the matcher's
  shortlist.** The quantity matcher scores only runs within the yield tolerance
  of what JLC says it built, so an order for a batch that was deliberately
  over-built — a batch for 50, with 60 populated — scored nothing, and
  the row then showed `External project` as its ONLY button. That is not a
  smaller version of the right answer: it takes the order's consigned stock out
  of batch costing, $1,218.98 on SMT026092263197. The decision endpoint always
  accepted any run; only this control narrowed it.
- **The same row printed arithmetic that does not hold.** "JLC says 60 boards
  × 1 per panel = 75 devices" multiplied the BILLED quantity by the panel factor
  and printed a total derived from JLC's `pasteNumber`. It also said the factor
  was "derived from the BOM" where JLC had stated it. And the 75 is itself
  wrong for this order: 75 bare PCBs were made and 60 populated, and the order
  drew exactly 60 of each 1-per-board part. The two counts differ on 16 of 46
  orders, so the row now warns whenever they do. The backend still derives
  devices from `pasteNumber`; changing that is an open question.
- **The JLC page is readable.** Each assembly order is now a boxed card: the
  order row and the session strip used `meta-card` alone, a class with no
  appearance, so they drew no box and ran into each other. An order's
  quantities are separate labelled chips — assembled, billed, panel, devices —
  instead of one sentence, and a disagreement between the assembled and billed
  counts is a warning banner that says how to settle it from the evidence. The
  session strip puts its facts and its buttons on two rows. Four two-sentence
  `.card-subtitle` paragraphs, which render as uppercase mono, are now a short
  label with the explanation in plain text under it.

## 2026-09-21 (the shelf, by product — and 13 devices nothing was counting)

The Orders page is cleaned up with it:

- **Four card descriptions were rendering as walls of upper-case mono.**
  `.card-subtitle` is an 11px letter-spaced LABEL style; a paragraph in it
  shouts. The label now carries a few words and the explanation sits in ordinary
  muted prose under it.
- **Over-built batches mark the two cells that disagree**, Recorded and Built,
  instead of painting the whole row red. A red date and a red unit cost said
  those figures were wrong too, so a deliberate flag read as a broken row.
- **"Sellable now" is no longer cut to "SELLABLE N…"**, and the orders table's
  Date column takes a fixed width so it cannot be cut to `2026-09-0…` on a
  narrow screen.
- **A batch with nothing on the shelf shows — for its value**, not `$0`.
- The shelf card says how many devices it cannot see, so its total and the
  Stock page's no longer differ with nothing to explain it.

Production → Stock now opens with **Finished devices we hold**: one row per
product, not per device. Open a row to see why a unit is not sellable, and click
a condition to land on that project's Devices tab showing those exact serials.

- **The platform was reporting 93 devices on the shelf while holding 106.**
  Every finished-stock figure counted per BATCH, so a device that names no batch
  was invisible to all of them. Thirteen were real: 3 faulty and 10 prototype
  CE_Dongle_V2 units. `GET /api/finished-products` counts the device records
  instead, and the card names the unbatched ones in a banner — they are stock,
  and nothing values them, because per-device cost belongs to a batch.
- **"On the shelf" on the Orders demand card is now "Sellable now"**, and counts
  condition `ok` only. A faulty or prototype unit may never ship (decision
  0032), so counting it as supply said an order could be filled by devices that
  cannot leave the building — it read 34 dongles of supply against 0 sellable.
- **A project's Devices tab takes `?state=` and `?condition=`**, and says so on
  screen with a "Show every device" button. The API had supported both filters
  since it was written; nothing passed them, so a link could name the project
  but not the devices.
- **A project's tab is in the URL** (`?tab=Devices`), like every other tabbed
  page here. The remembered tab is now the fallback for a bare visit.

## 2026-09-21 (every production list opens newest first)

Invoices, Orders, Overview and Batches all default to their date column,
descending. Two were already there; two were not, and one of those had no date
column at all.

- **Batches** states its sort instead of relying on the order the API happened
  to return.
- **Devices on the shelf** (on Orders) gains a **Date** column — the batch's own
  date — and sorts newest batch first. It had no date at all, so it could not be
  ordered by one.
- A sort you set yourself is still remembered per table and still wins: this is
  the default, not an override.

## 2026-09-21 (a Batches tab, and invoices you can sort)

- **Production → Batches** lists every production batch across every project
  (`/production/runs`). The project's own Batches tab answers "what has this
  product built"; this answers "what is in production anywhere", which had no
  home — the only cross-project list was the Overview's cost table, built from
  the invoice register, so a batch nobody had billed yet was invisible. Status,
  quantity, devices recorded and whether the books are closed; what each batch
  COST stays on Overview.
- **The Invoices document list sorts and filters like every other list.** It was
  the last hand-rolled table on a main page: 88 rows with no sort, no filter row,
  and a Lines button as the only way to open one. It is a `DataTable` now.
- **Clicking anywhere on an invoice row opens its positions**, the way a row
  opens everywhere else. The open document is still remembered across
  navigation.
- Nineteen dead width rules removed with it — `.invoices-table` was stranded by
  the conversion, and `.invoice-runs-table` had been stranded long enough to
  grow two contradictory definitions, neither applying to anything.

## 2026-09-21 (every exclusion says what for)

`excluded` money is charged to nobody on purpose, and it passes every other
check the register has — the gap still closes, nothing reads as unassigned. The
reason is the only thing that makes it auditable, and **44 positions worth USD
37,656.66 said nothing at all**.

- **All 44 are labelled**, and `excluded_unstated_usd` reads **0.00**. No money
  moved: every other figure on the register is unchanged to four decimals.
  14 lines of import VAT (11,975.90) are `reclaimable_vat`, 12 lines of JLC
  prepaid components (25,680.76) are `prepaid_components`, and 18 are split
  headers whose money is on their children.
- **The API now refuses an exclusion with no reason** (422), on the line editor
  and on the split.
- **The split dialog can state one at all.** It could mark a share excluded and
  had no field for the reason, which is why every prepaid component share from
  a JLC populated-board invoice arrived unlabelled. A reason box appears under
  the destination when a share is charged to nobody, with the reasons already in
  use offered as suggestions.
- The vocabulary is in the production-run skill (v7), which also drops the last
  references to the removed `kind` field.

## 2026-09-21 (production data comes down with one command)

`scripts/sync-prod-to-local.sh` copies the production database, and optionally
the MinIO objects, into the local dev stack. It only ever runs one way and only
ever reads production.

- **`--check` compares the two without changing anything**, with EXACT row
  counts. It is the part that matters: a local copy missing
  `jlc_order_decisions` had been showing 45 undecided JLC orders that
  production decided months ago, and four more tables were empty for the same
  reason. A partial restore is worse than no restore, because it looks like a
  bug in the code.
- Rules and traps in
  [docs/reference/deployment.md](docs/reference/deployment.md).

## 2026-09-21 (what each batch cost, newest first)

The last column of **Production → What each batch cost** was an empty column
headed "cost", beside a column headed "Cost USD".

- **The empty column is gone.** It held a bar drawing each batch's cost on a
  shared scale, which had not drawn anything since the page moved to a
  `DataTable`: the only rule giving the bar's `<span>` a box lived under
  `.prod-runs-table`, a class the migration dropped. An inline span has no
  height and no background, so the column rendered nothing, with no error
  anywhere. The bar is not worth the width, so the column and its styling were
  removed rather than repaired.
- **The table has a Date column and sorts newest batch first.** The date was
  already deciding the row order and was not on screen — a default order nothing
  explains reads as no order at all.
- **Batch names no longer clip at 1280px.** Measured: the longest needs 26.8% of
  the table, and the freed width went to it.
- **Eleven dead width rules removed**, plus seven unused dashboard rules.

## 2026-09-20 (a delivery names its devices, and nothing else)

`qty_unserialized` is gone from the platform. Decision 0032 made a shipment a
set of serials and called this field "the exact artefact rules 1 and 2 forbid" —
but it only removed the AUTOMATIC path. The API still accepted a quantity with a
batch behind it, and an endpoint existed purely to curate one.

- **`shipment_lines` is dropped.** Its whole content was a quantity and the batch
  behind it; a shipment's real content is the `shipped` events pointing at it.
- **Three survivors, 35 units, every one a prototype batch** — and every one
  double-counted against its own placeholders: run 18 held 5 units `in_stock`
  *and* a line claiming 5 had shipped from run 18. `run_stock` netted the two to
  zero, so nothing looked wrong. They were replaced by the serials they stood
  for, on the same deliveries.
- **They were all prototypes for one reason**: a `prototype` placeholder cannot
  ship, so a prototype delivery had nowhere to go but the anonymous count. A
  prototype that really shipped now carries `condition = ok`, and `prototype`
  means a unit that never left the building.
- **A batch with no device records holds nothing, and is built 0.** It used to
  hold its typed quantity as a pool the anonymous path drew from —
  `legacy_stock`, `overdrawn` and `unserialized_shipped` are all gone. The
  pool's last survivor was **"Devices on the shelf"**, whose *Built* column fell
  back to the typed quantity and whose **"No serial"** column showed the
  difference. Both are gone: every unit on that card is a named device. Record
  the devices, even as placeholders, and they count like any other. *Recorded*
  stays beside *Built* and now says what it is — boards ordered or assembled,
  not units.
- **There is no quantity field on a shipment line at all.** Not
  `qty_unserialized`, and not `qty`: the schema forbids unknown keys, so the API
  refuses either and names it, and the published OpenAPI carries neither. The
  sentence decision 0032 chose is still there, on the one guard that states the
  real rule — a line that moves no device is refused with "the shipment moves
  nothing — name the devices that left".
- **Fixed: the finished-stock endpoint would have answered 500.** It went on
  summing `overdrawn` after the service stopped reporting it. A test now reads
  the route's whole payload and fails on any key from the old counting path.
- **Fixed: `/api/health/schema` was red for ever.** Five migration statements
  read `run_cost_lines.kind`, which the previous release drops, so they failed on
  every boot afterwards. They are `skipped` now — a health page people are meant
  to read must not become one they learn to ignore.

Order 13 now counts **40 named devices** where it counted 20 named and 20
anonymous, with nothing uncosted. No money moved, and no batch in production has
zero device records, so nothing on the shelf card moves either. Reasoning in
[decision 0049](docs/decisions/0049-a-delivery-names-its-devices-and-nothing-else.md).

## 2026-09-20 (the register's gap is an invariant, and it reads zero)

`gap_usd` was documented as "a non-zero gap means a bug here, not bad data" and
read **0.0271** on every measurement for months. Nobody acted on it because it
was measured against the wrong number and the screen hid it: the production
overview printed a green `0` for anything under 0.05.

- **`gap_usd` is now the invariant** — our LINES against every bucket derived
  from them — and reads **exactly 0.0**. The overview has no tolerance: zero is
  green, anything else is red.
- **`untranscribed_usd`** is what it was really measuring: `printed - lines`,
  the money a supplier put on the page that sits on no line of ours. **0.0276**
  across five documents. It is not fixable by editing a line — JLC prints a
  rounded total while our unit prices keep more decimals — so it is reported,
  and `issues.untranscribed` names every document at any size. The existing
  `unreconciled` check tolerates 5 cents, so it had never named one of them.
- **`overallocated_usd`** is the twin of `residual`: children claiming more than
  the header they split. `residual` clamps at zero, so the overshoot lived in
  the leaves and outside the identity. Four JLCPCB documents overshoot by
  0.0001-0.0002 and were the last thing keeping the gap from closing.
- **The totals now accumulate exact values**, not the per-document figures
  rounded for display. Adding 86 rounded numbers put error into the figure whose
  job is to prove the arithmetic.
- **The excluded bucket now says why.** `excluded_by_reason_usd` and
  `excluded_unstated_usd` are on the register, and the overview marks the
  unstated part. `excluded` is legal in the identity, so an exclusion is
  invisible to every other check — which is how $14,443 of manufacturing once
  sat charged to nobody while the page read clean.

No money moved: every bucket total is unchanged. Reasoning in
[decision 0048](docs/decisions/0048-the-gap-is-an-invariant-not-a-tolerance.md).

## 2026-09-19 (one field says what an invoice position is)

Every position carried two labels for the same thing: a coarse **Kind**
(`part`, `fab`, `assembly`, ...) and a precise **production step** ("SMT
placement", "Bare PCB fabrication"). They are the same fact at two resolutions,
and the step catalog had always declared which bucket each step belongs to —
nothing kept the two in step, so they drifted apart on 12 rows.

- **Kind is gone.** The step is the only field, and the bucket is derived from
  it. The column moved to the front of the line table and is named **What it
  is** — "Planned as" was a poor name for it, because a step is not a plan.
- **Reading the 12 disagreements showed the catalog was too coarse**, not that
  anyone had mis-typed. `pcba:general` ("PCB assembly, unsplit") was also
  carrying JLC's **populated board** price, which includes the bare PCB and is
  different money; `final:enclosure_print` was carrying both Italtronic's
  per-unit print and its one-off set-up. Both now have their own step.
- **Four new steps**: `pcba:populated`, `final:enclosure_print_setup`,
  `other:cancelled` and `other:payment_fee`. The last two are for positions that
  had no step at all and nothing in the catalog that fitted.
- **260 positions had no step**; every one now has the step it already was.
  Where a part's money goes decided which: excluded means prepaid components,
  charged to a batch means the assembler sourced it, the rest is ordinary stock.
- **The line table is back to eight columns**, paying back the ninth that the
  Goes to / How split added. Column widths moved onto the header cells after
  `nth-child` rules got them wrong for the fifth time.

- **A cancelled line has no destination.** The supplier printed it, nothing was
  delivered, nobody pays. Four of the five `Cancelled: <mpn>` positions were
  already excluded and the fifth was not — which was the whole of the register's
  standing `unassigned_usd 19.78`. All five now carry the reason
  `cancelled_by_supplier`, the two payment fees carry `payment_fee`, and
  **`unassigned` reads 0.00 for the first time.**

No figure moved except that one: 86 documents, 155,749.3046 USD and gap 0.0271
before and after, with 19.78 moving from `unassigned` into `excluded`. `by_kind`
shifts by the 11 rows whose bucket was wrong.
Reasoning in
[decision 0047](docs/decisions/0047-the-step-says-what-a-position-is.md).

## 2026-09-19 (the broker names devices the platform had only counted)

The fleet MQTT broker carried **69 topics that matched no device**. They were not
one thing, and most of them were never missing.

- **28 are devices the platform already holds**, under a different spelling of
  the topic: the broker says `dongle_449430`, programming recorded
  `dongle_F8B3B7449430`. Linking compares the two strings exactly, so every
  disagreement surfaces as "unknown". 12 of the 28 are confirmed by the device's
  own `tasmota/discovery` MAC, byte for byte against the MAC esptool read at
  programming. **Nothing was rewritten** - the programmed topic stays as the
  record of what was programmed.
- **14 were prototype-era dongles** that the 2026-09-18 reconciliation had
  already counted, shipped and invoiced as anonymous `PROTO-xxxx` rows, because
  no serial was kept at the time. Those rows now carry the MAC and topic the
  broker reports. Both prototype order lines still read 15/15 and 20/20 -
  filling a row that already existed moves no count.
- **Those 14 also got real serials.** `PROTO-0001` is now `86A438`, named from
  the device's own topic. The platform's naming rule
  `tasmota_id = 'dongle_' || serial` now holds for **4,575 of 4,575** units that
  carry a MAC, where it previously held for 4,561. The old placeholder number
  stays in the device's notes.
- **Two prototype runs now exist as cost pools**, one per prototype order, with
  `PROTO-0001..0035` pointing at them. They hold the money, not a delivery. They
  carry no cost documents yet.
- **15 more were identified the same way**: 7 `CE_Dongle_V3_2` into the blank
  prototype rows of the V3.3 run, and 8 `CE_Dongle_v2` on Tasmota 14.x into
  `PH-0001..0008`, the placeholders for the 2026-09-03 delivery. That delivery
  still reads 292 shipped, measured before and after. Their `condition` was left
  as `unidentified` on purpose: the device's identity is its own word, but which
  placeholder it belongs to is a judgement, and a stock check may disagree.
- Unlinked topics: **69 -> 40**.

Devices were NOT assigned to a batch by MAC proximity. The rule is real - 96.4%
correct on 4,510 units with a known batch, median address gap 4-8 inside a batch
- but 39 of the 40 unidentified devices have no neighbour at any distance, and
the single device it placed confidently turned out to be an `ESP32-DevKit`.
Reasoning in
[docs/decisions/0046](docs/decisions/0046-the-broker-names-a-device-the-platform-already-counted.md).

## 2026-09-19 (an invoice position says where its money goes)

The line table's **Charge to** column offered one default, worded `- nobody -`,
that resolved to **five** different destinations depending on the line's `kind`,
its `allocate` and the document's own destination - none of which were on the
screen. A `part` line left alone went to the shared pool. A `freight` line left
alone became money nobody paid for.

- **Two columns now, "Goes to" and "How".** Goes to names the destination
  outright: *Stock - the shared pool*, a batch, a project, *Nobody, on purpose*,
  or *from this document* when the document names one. There is no empty option
  that means something; a position nobody has decided reads a red
  `not decided`.
- **"How" carries the second question** - for stock: is stock, or spread over
  this invoice's parts by value or by quantity; for a batch: as its own amount,
  or per device x units; for nobody: a typed reason. **All three of those fields
  were previously unreachable from the browser.** `basis` was hard-coded
  `per_run`, `allocate` was only ever written as `excluded`, and
  `exclude_reason` was stored but returned by no endpoint. A transport line
  typed onto a parts invoice could not be marked as landed cost at all.
- **Choosing a kind fills the box in rather than deciding silently.** `part`
  suggests Stock, `freight` and `duty` suggest spread-by-value, and neither ever
  overwrites an answer you have already given.
- **Fixed: moving an excluded position onto a batch left it excluded.** The
  editor only ever added `allocate: "excluded"` and never cleared it, while
  `line_destination` tests `excluded` before `run_id` - so the screen showed the
  batch and the money stayed charged to nobody.
- **264 existing part lines were marked `pooled`**, which is what they already
  resolved to. No figure moved: the register reads 86 documents,
  155,749.3046 USD, gap 0.0271 and unassigned 19.78 before and after.

The one genuinely undecided position in the database - JLCPCB `Cancelled:
XL-1005SURC`, USD 19.78 - is now red on its row instead of a number on a summary
line. Reasoning in
[decision 0045](docs/decisions/0045-a-position-says-where-its-money-goes.md).

## 2026-09-19 (configuration is an administrator's surface)

An audit of the role model found 16 of about 440 API routes gated on the
administrator role, and `/api/settings` was not one of them. Any signed-in user
could write the deployment's own configuration, and a write lands on the next
request rather than at the next restart — so an ordinary account could rotate
the KiCad library token and break every installed `.kicad_httplib`, move the
public base URL out from under every generated link, or repoint the render
service. Nothing had gone wrong. The gap was that nothing would have said so.

- **The Configuration tab is admin-only**, and so are all three of its routes.
  A non-admin now lands on Datasheets and does not see the tab. Secrets were
  never returned by the API and still are not — it reports only whether one is
  set.
- **Field-solver rule sets are admin-only**, matching stackups. Both are the
  fab's shared facts and are edited from adjacent controls, but only one of
  them was gated.
- **Editing an exchange rate is admin-only.** Every document in the register
  converts through these, so one hand-typed rate moves every batch cost and
  every order margin at once. The TABLE stays readable by everybody — an
  "unknown FX rate" warning on an order or a run has to lead somewhere — but
  Refresh and Override are gone for a non-admin.
- **The archive-wide datasheet jobs are admin-only**: fetch-all, classify, the
  page index, the broken purge, the restamp collapse and the storage reclaim.
  Each walks every document and several bump component versions. Fetching or
  uploading ONE part's datasheet is unchanged and open — that is ordinary
  library work. The status readout stays visible to everybody.
- **The admin-only set is now a test** (`api/tests/auth/test_role_gates.py`).
  It fails when a gate is dropped AND when one is added without being written
  down. Before this there was no test of the role model at all.

Unchanged on purpose: the library, reviews, production, orders, invoices,
projects, the flasher and the agent stay open to every signed-in user. The
admin role is for the deployment, for other people's credentials, and for the
shared reference data every project reads — not for deciding who may do their
job on one part, one batch or one board. Reasoning, and the options rejected,
in [decision 0045](docs/decisions/0045-configuration-is-an-administrators-surface.md).

## 2026-09-19 (the Admin page is six tabs, and a setting is one line)

Admin stacked six panels on one scroll, and Configuration alone is 24
settings — each one about 100 px tall, because its help text sat under the
label and its buttons under the field. The schema readout at the bottom was
four screens below the tab you arrived for.

- **One tab per subject**: Configuration, Users, Datasheets, Exchange rates,
  Fleet broker, System. The tab is in the URL (`/admin?tab=users`), so a link
  can point at one panel, and the two admin-only tabs are hidden from a
  non-admin rather than shown as controls that can only fail. Links elsewhere
  in the app that said "Admin → Exchange rates" now land on that tab.
- **A setting is one row**: name, value, and the buttons beside the field. The
  help text is the ⓘ beside the name, which shows more of it than the old
  two-line block did. The whole card is about a third of its former height.
- **Save appears only when something differs from what is stored.** A secret
  used to carry a standing Save button, because its field always reads empty;
  pressing it wrote the empty string, which is not how a stored secret is
  cleared. Revert is.
- Schema health and the pointer to your personal KiCad links share the System
  tab.

## 2026-09-19 (a batch can close its books, and a correction is a document)

Correcting an old invoice used to change history with nothing to show for it.
A batch's **direct** costs — assembly, fab, freight, tooling — are recomputed
from the invoice lines on every read, so fixing a typo on a two-year-old
assembly invoice moved that batch's total, its per-device cost, and the cost of
every order that shipped one of its units. Silently, and with no record that the
figure had ever been different. The component half of the model was never
exposed to this: a draw snapshots what it paid at the moment it is made.

- **Close the books on a batch** from its page. Every supplier document that
  charges it — and that was written before the close — becomes read-only, on all
  seven write paths. What the batch cost is recorded with it, so a later
  correction shows as a variance against the figure that was quoted instead of
  as a number that reads as though it was always this way. Reversible: reopen it
  and the documents are editable again.
- **A correction is a new document.** `Create correction` on a settled invoice
  writes one dated today, pointed back at the original, inheriting the
  supplier, currency, batch and the FX rate the original was pinned at — so a
  correction in EUR nets against it exactly. A credit is a negative line. The
  original keeps its printed figures forever. Both documents link to each other.
- **A write-off charged to a batch pins its unit cost when it is written.** An
  unpinned one resolved against the pool average *as it stands on every read*,
  so a 2024 attrition row was priced at a 2026 average and moved again with
  every later purchase. Existing rows are frozen at what they currently read, so
  no figure moves on deploy day.
- **A closed batch refuses `qty`, `qty_good` and `snapshot_id`**, because a
  per-device invoice line is charged on those. It can still be renamed, re-dated
  and annotated.
- **Every change to a batch is now audited with its previous value.** The audit
  row carried `before` for the seven sale fields and `null` for everything else,
  so a label, a date, a quantity or the notes could be overwritten with no record
  of what had been there.

Nothing is locked until somebody closes a batch, so every existing batch is
unaffected. Reasoning, and what other systems do about the same problem, in
[decision 0044](docs/decisions/0044-a-correction-is-an-event-not-an-edit-to-the-past.md).

## 2026-09-19 (an invoice line can be pointed at a library part by hand)

The **Component** column on the Invoices line tree links a part position to the
library component it bought. Until now the link had two sources only: the
`Resolve parts` matcher, which needs a unique MPN hit, and an API client setting
`component_id` itself — which the manual line form never sent. A position the
matcher could not place stayed unlinked forever, and an unlinked part line keys
the cost pool by its MPN string rather than by component, so it can never meet a
BOM draw and the part silently costs nothing.

- Click the cell on any `part` leaf to search the library by MPN, name or
  manufacturer, then link or unlink. Unlinking splits that part's pool entry in
  two, which the control says before you do it.
- Linking fills an EMPTY `mpn` from the chosen part. It never overwrites one the
  invoice printed.
- **The parts a supplier sourced itself are itemised, and coverage is checked.**
  "Components sourced by JLC" was one figure; it is now a child per part, priced
  exactly as the supplier priced it, charged to the batch and never pooled.
  `GET /api/runs/{id}/supply-coverage` answers whether every position the batch
  used is covered exactly once — a part the supplier supplied that was ALSO
  drawn from our pool is the double charge that previously had to be found and
  voided by hand. Both are now in the UI: a **supplier** button on the parts
  position fills it in place, one row per part, and the position folds to
  `▸ 20 parts` so a breakdown is not in the way until you want it. A **Supply
  coverage** panel at the top of a batch's Materials tab lists only the
  positions that do not reconcile. A part share now names a library component
  and carries a quantity at a price rather than a typed label and a percentage,
  so a hand-made breakdown and a supplier-read one produce the same rows.
  Reasoning in
  [0041](docs/decisions/0041-the-supplier-parts-lump-is-a-small-bom.md).
- **A part bought for a batch AND drawn from the pool is now caught.** That is a
  double charge, and it was only detectable on batches whose supplier BOM the
  importer had cached — a hand-entered invoice had no guard at all. The check
  compares our own rows, so it needs no supplier feed and runs on every batch.
- **Fixed:** a substituted row was indistinguishable from an ordinary one. The
  marker was a worded pill in a fixed-width cell, and a pill cannot be
  ellipsised — it was simply cut off. It is now a glyph, `⇄` on the design's row
  and `↳` on the row standing in, with the detail on hover. The two redundant
  supply pills are merged into one.
- **Corrected:** a substitution's `source` was described, and labelled, as *who
  decided* the change — "factory decided". It never recorded that. It records
  WHERE the change was defined: on the supplier's order, or here by hand. The
  common case is us choosing a different part on the supplier's site while
  placing the order, which is our decision made outside the schematic. The pills
  now read **"chosen in the order"** and **"recorded here"**. No stored value
  changed. Reasoning in
  [0042](docs/decisions/0042-a-substitution-records-where-the-change-was-defined.md).
- **A fully substituted position is now two rows on the Materials tab.** The
  design's part shows `used = 0` and the part that actually went on sits
  directly beneath it with its own quantity and cost, instead of the two being
  summed into one row where neither could be read. The design's row shows no
  delta — its zero is deliberate, not a shortfall.
- **A batch's own parts now show on its Materials tab.** Parts bought straight
  for one batch never enter the shared pool, so no draw reported them and the
  Materials tab could not see them at all — a position met that way showed an
  empty Used column while the batch was paying for it. They are matched through
  the substitution, because the row is keyed by what the design specifies and
  the batch bought what was fitted. Batch 8's substituted C2 now reads 301.12
  used against 239.41 planned: a 61.71 overspend that was invisible before.
- The invoice line table is down to eight columns: **Position holds the
  component picker** on a part line, and the MPN and Component columns are gone
  — all three said the same thing.
- **Fixed:** the Stock page reported "17,647 pieces we booked as bought that JLC
  never received" once a supplier-parts position was itemised. The ledger
  reconciliation counted every `part` line as a claim on JLC's warehouse,
  including parts the factory supplied itself and `excluded` carve-outs, neither
  of which ever entered our consigned stock.
- **JLC-sourced component lines are `part`, not `assembly`.** They read as
  labour on every Materials view because a guard against a run-less part line
  claiming the pool was applied to lines that always name their run.
- **A purchase can no longer be edited out from under its draws.** Deleting a
  document, cutting a part line's quantity, voiding one, splitting one, or
  changing its component link is refused when the change would leave
  consumptions with no purchase behind them — the refusal names the short parts
  and quantities. A change that keeps every part covered still goes through, and
  `force=true` no longer waives it. Reasoning in
  [0040](docs/decisions/0040-a-purchase-cannot-be-removed-from-under-its-draws.md).
- **One line table now serves both entering an invoice and editing a saved one.**
  The New invoice card gained the MPN, Component, Charge to and exact Planned-as
  columns it never had, so a hand-typed position no longer has to be finished by
  reopening the document. **A saved invoice can now be corrected at all**: one
  "Edit this invoice" checkbox opens its header — supplier, number, supplier
  order id, date, currency, printed total, type and notes — together with every
  position, and Save changes writes the lot as ONE transaction. That is what
  makes swapping the component mapping of two positions possible. Cancel
  discards everything staged, and changing the currency or date re-resolves the
  pinned NBP rate.
- Prototype batches can now be counted without being named — see
  [0039](docs/decisions/0039-a-prototype-is-counted-without-being-named.md).

## 2026-09-19 (a batch records the part it really fitted)

CE_Dongle_V2 batches 7 and 8 were built with **C7223** where the schematic says
**C110548**. The change was intended and was never copied into the design, and
nothing in the platform knew — so on 2026-08-06, three months later, **476 more
of the superseded part were bought for $585.29** at $1.2296 each against a
historic $0.34. 500 now sit at JLC with no consumer. Reasoning in
[0038](docs/decisions/0038-a-substitution-belongs-to-the-batch.md).

- **A substitution is a row on the BATCH**, keyed by designator so it survives a
  BOM re-export — `run_substitutions`, journalled, one per position. The
  snapshot is never rewritten: it records what was specified, the row records
  what went on the board.
- **The supplier's own BOM is the detector.** JLC states it: `matchType:
  "update"` at a designator whose part changed. Comparing their orders to each
  other, per board, needs no mapping between their reference numbering and ours
  — which matters, because for this board they differ (`C1` against the
  schematic's `C2`). Nothing is written on its own.
- **It lives in the Materials row, not beside it.** Unfold a part and the fold
  offers **Substitute this part**, scoped either to one designator or to every
  position the part sits at — a BOM row already groups them, so "all of them"
  is one row either way. What the supplier already reported is offered there
  with a **Record** button. A folded row then carries a small pill: `→ C7223`
  on the part the design asks for, `stands in for C110548` on the part that
  actually went on, and `supplier changed it` where JLC reports a change nobody
  has recorded.
- **A substituted part is ONE row on Materials, not two.** Left apart, the
  design's part read `not drawn` and the part actually fitted read `not
  planned`, so a batch built correctly showed two faults. The planned side
  stays the design's — that is what was specified and budgeted — and the used
  side comes from the draws of the part really fitted, which on batch 7 makes
  the row read `1,000 / 1,000, Δ 0` and prices the substitution at **+$74.54**.
  Only when the substitution covers every position on the line: replacing one
  LED of six means both parts were genuinely used. Nothing is written — the
  draw stays on the part that really left the pool.
- **WHO SUPPLIED the part is recorded, not inferred.** `supplied_by` is read
  from JLC's own `componentSource` — `shop` is theirs, `preSale` is our
  consigned stock, `preSaleAndShop` is both — and shown on the row: batch 8
  reads `supplier-supplied`, batch 7 `partly supplier-supplied`. It was briefly
  inferred from the absence of a draw, which is wrong in both directions: a
  part WE supplied and never drew is a missing draw, and reading that as
  supplier-supplied would have hidden it.
- **The part fitted is chosen with the library's own component picker**
  (`ComponentLinkDialog`, now general enough to serve something that is not an
  invoice line). Positions are picked with checkboxes, all ticked by default —
  the usual answer is "everywhere", the next is "everywhere but one", and
  neither fits a single-choice control.
- **A part the supplier provided can be named without being in the library.**
  The picker offers *Use "…" as typed* only when the supply side says the
  supplier provided it: a part off OUR shelf was bought, so it has an invoice
  line and a pool entry, and naming it by string alone would split it in two.
- **A design part that never went on the board is flagged.** When JLCPCB's own
  BOM for a batch is cached, a planned position whose part appears in neither
  that BOM nor any draw gets **⚠ not on the board** at the end of its Materials
  row. Matched on the LCSC code, never the designator — JLC's numbering is not
  ours — and through the library component, so one part under two codes is not
  reported as missing. A part that WAS drawn is never flagged, which is what
  keeps cartons and enclosures out of it.
- **A substituted row's Used quantity follows from the substitution and cannot
  be typed.** It was left blank and editable, which invited a number that would
  have written a draw against the part the design names — the one that did NOT
  go on the board — and taken it out of stock. Batch 8 now reads `800 / 800,
  Δ 0` with the used MONEY blank, because the supplier's part is billed inside
  the assembly fee and cannot be split out. A position recorded as empty reads
  `0 / 0` and plans nothing, exactly as a dropped line does.
- **Recording a substitution clears the flag**, and so does recording that
  nothing was fitted: a substitution with **quantity 0 and no part named** means
  the position was left empty. That is what the early batches did with cartons —
  history, not an error — and it now has a row with an author and an undo
  instead of a JSON `drop` nobody could see.
- **There is one component picker, and it is now where a shared component
  belongs.** `ComponentLinkDialog` under `invoices/` became
  `components/ComponentPickDialog.tsx`: it takes a `PickSubject` rather than an
  invoice line, so an invoice line and a BOM position both satisfy it, and it
  gained `allowFreeText`, `title` and `confirmLabel`. Its old path said it
  belonged to one screen, which is the reliable way to get a second picker
  written.
- **A design that has not caught up is a standing finding on Stock**, naming the
  batch, the position and how many of the superseded part are still held. That
  is the part that stops the re-order.
- **Later batches keeping the substitute get their own row.** Reporting only the
  moment it changed left batch 8, built identically, looking as though it
  followed the design.
- **BOM draws take the fitted part**, noting what it stands in for. The unused
  `component_id` branch of `ProductionRun.overrides` is gone — it keyed on a
  snapshot-scoped BOM line id and could never have carried into the next batch.

## 2026-09-19 (the Stock page answers one question, and keeps the rest behind the row)

The parts table went from **thirteen columns to six** — part, LCSC, projects,
ours, Δ qty, at cost. Every figure that is an *operand* of the comparison rather
than the comparison itself moved into the row's fold, where there is room to
read it. JLC's own count went with them: it is `ours + Δ qty`, and printing all
three spent a column on arithmetic.

- **Unfolding a part gives three boxes of equal height**: where it is used, what
  moved it, and what the balance has done over time. The movements box carries
  both ledgers behind one control — ours and JLCPCB's — because a disagreement
  is settled by reading one against the other, most recent first.
- **A part now knows its own projects.** `parts_stock` joins each part to every
  project's latest ready snapshot BY IDENTITY, so a part matched only by MPN or
  only by `component_id` is still found. The table shows them as chips and the
  fold as a table with boards, quantities per device and reference designators.
- **"Held parts used in projects" is gone**, and so is `GET /api/jlc/stock/usage`
  behind it. It listed only parts JLC holds — an enclosure, which no supplier
  consigns and whose usage nothing else reports, appeared nowhere. The 7 parts
  the platform buys itself now show their stock like any other.
- **"All" is the default filter.** The page is read to look a part up at least as
  often as to chase a disagreement, and now that the two sides agree the old
  default opened on an empty table.
- **A stylesheet block that styled nothing was removed.** `.stock-table` carried
  thirteen hand-maintained column widths and no table ever had that class —
  `DataTable` builds its `<colgroup>` from the column definitions. Recorded as
  rule 9 in `web/src/components/CLAUDE.md`.

## 2026-09-19 (the bench speaks up before it writes)

The bench now checks what the platform already knows about the board in front
of it, at the moment the MAC is read, and says so. Reasoning in
[0037](docs/decisions/0037-the-bench-says-what-it-already-knows.md).

**Exactly one check stops a run:** the device belongs to a different project,
which means the wrong fixture or the wrong project selected, and continuing
would file a unit where it does not belong. Everything else is a notice the
operator takes, with their name on it and a reason box that is offered but
never required.

| Notice | Fires when |
|---|---|
| `first_unit_of_batch` | this is the first device ever filed against the batch — the check that would have caught 2026-09-17 at unit one instead of unit 31 |
| `not_in_stock` | the unit reads shipped, allocated or disposed. Programming it does not book it back in |
| `built_in_another_batch` | an ordinary reflash. The unit keeps its original batch for cost, this batch keeps the attempt |
| `online_elsewhere` | the broker says this device is online now, so it cannot also be on your bench |
| `condition_not_ok` | a faulty or prototype unit — probably a repair, and it stays unsellable until the condition is cleared |
| `batch_full` | the batch already holds as many units as were planned |
| `settled_batch` | the batch has taken no unit for 30 days. Adding one re-divides its whole cost pool |
| `duplicate_imei` / `duplicate_iccid` | that modem or SIM identity is already recorded on another unit |

**A new board, in a running batch, in the right project, produces no notice at
all.** Every notice is an audit row on the run (`flasher.check.<code>`) and a
line in the run log, so what somebody continued past is in the history.

## 2026-09-18 (a batch shows the devices it really built)

The batch **Devices** tab now draws the project's own device list scoped to the
batch, instead of a serial list somebody had to paste in by hand. `run_devices`
held nothing in the whole database, so the tab was empty for every batch while
`DeviceUnit.production_run_id` knew all 4,548 of them. The tab gained a
**Condition** column and a per-device **Attempts** count, and its totals are
counted over the batch rather than the project.

- **A batch correction now moves both copies of the batch.**
  [0029](docs/decisions/0029-the-batch-on-a-produced-event-is-correctable.md)
  made the batch on a `produced` event correctable, but the bench also writes
  that same choice onto every programming attempt, and the correction never
  reached those. Fifty of the fifty-four filled rows still named Batch 8 — a
  batch that has built nothing — while their devices had been corrected to
  Batch 7 on 2026-09-17. `rebatch_devices` now moves the attempts that named
  the old batch, reports how many, and records the count in the audit row. An
  attempt naming some other batch, or naming none, is left alone.
- **A one-off repair corrects the fifty rows already written**, pinned to that
  batch and that date. It is not a standing rule: a programming run naming a
  batch its device was not built in is NORMAL, because a unit reflashed while a
  later batch was on the bench belongs to that session too, and the run row is
  the only record of it.
- **A batch's DEVICES are reached through the device.** The batch filter on the
  devices list asked the bench's copy, which is NULL on 6,139 of 6,443 rows
  because a retro import never guesses a batch. Built and programmed are now
  kept apart as two questions: `good_units`, and so every per-device cost,
  counts only what a batch built.
- **Coverage figures need a planned list to mean anything.** Without one, a
  batch used to report every device it really built as `extra`.

## 2026-09-18 (the dongle stock finally closes)

Every CE_Dongle_V2 device is now accounted for, and the numbers balance on every
batch. The device log was rebuilt from the facts established over the past week
rather than corrected in place — 4,326 of its 4,427 deliveries were FIFO guesses
and only 101 had ever been observed. Reasoning in
[0036](docs/decisions/0036-the-dongle-device-log-is-rebuilt-from-the-facts.md),
the facts in
[dongle-stock-reconciliation.md](docs/reference/dongle-stock-reconciliation.md).

| | Devices |
|---|---|
| With customers | 4,502 |
| On the shelf, faulty | 35 |
| On the shelf, prototypes | 10 |
| Scrapped | 1 |
| **Total** | **4,548** |

- **The 32 old-button units are stock again, not scrap.** They were filed
  `disposed` because that was the only way to stop a shipment picking them.
  They now read `in_stock` + `faulty`: present, visible, and unsellable.
- **Every anonymous unit is gone.** All 75 became named records — 45 `PROTO-nnnn`
  prototypes from before any batch existed, and 40 `PH-nnnn` placeholders for the
  2026-09-03 delivery, where 191 units left and only 151 can be named. Each
  placeholder says so in its note.
- **Orders 17 and 19 now report what is really owed** — 8 and 500. Every other
  order reads delivered in full.
- **The 101 scanned serials survive untouched**, on their own deliveries, marked
  as observed rather than inferred. They are the only rows in the whole history
  that ever were.
- **Batch 1 reads 521 built, 489 shipped, 32 held faulty**, and the invariant
  `programmed = at customer + in stock + scrapped` balances on all seven batches.

CE_Aqua_V2 and CE_Dongle_V3 are untouched; the shipment headers they share with
dongle orders were reused, not rebuilt.

## 2026-09-18 (stock moves when JLC says so, not when we agree)

Consigned stock no longer waits for a decision about money. JLC itemises, on
every manufacturing invoice, which of your lots each assembly order consumed —
so that draw is now written when the invoice is imported, charged to nobody, and
a later decision only says which batch pays. Reasoning in
[0034](docs/decisions/0034-stock-moves-when-the-supplier-says-so.md).

- **A decision that was never applied is no longer counted as settled.** One had
  been sitting since 2026-08-25 with 441 consigned pieces still on our books:
  the queue counted it as decided, and the "only undecided" filter hid it. The
  filter now means *undecided or unapplied*, and the queue reports `stranded`
  with the stock value behind it.
- **The Stock page compared two different moments.** `delta_qty` subtracted a
  pool that runs to today from JLC's count frozen weeks earlier, so every draw
  made since read as stock JLC held and we never paid for — **33,246 pieces** of
  phantom gap on 2026-09-18, hiding a real one of 3,866. Both sides are now read
  at the moment JLC counted. The table gained an **Ours then** column and says
  how many stock events have happened since.
- **That comparison is made in JLC's calendar, not UTC.** A parts order placed
  at 03:18 China time and a stock count fetched 4m44s later read as two
  different days, so 13 parts came out wrong by exactly their last purchase.
- **Assembly-order BOMs are fetched automatically on sync.** It was a manual,
  per-order button, which left 31 of 45 orders without one — and the BOM is the
  only source of which parts JLC supplied itself. The queue now says how many
  orders have none and what they are worth. Fetching writes evidence, never
  money, so a sync still cannot move the ledger.
- **`invoice_register` reports `pool.uncharged_drawn_usd`** — stock that has
  left with no run charged. A balance here that stops being transient means
  orders are not being decided.

Nothing about what a run has already been charged changes. An order imported
before this keeps the old write path.

### The platform reads JLCPCB's own inventory ledger

**Every part now agrees with JLC to the piece** — 72 parts in the pool, 0
disagreements, down from 28 parts and 33,246 pieces when this reconciliation
began. The last two gaps were closed from JLC's own records rather than by hand.

JLC keeps a per-part movement ledger behind the private-library page, with the
balance before and after every movement and their own wording for it. The
platform now syncs it with the stock count and reconciles both directions:
a movement JLC recorded that no document of ours reports, and a purchase we
booked that JLC's ledger never received. Reasoning in
[0037](docs/decisions/0037-the-supplier-keeps-the-receipts.md).

- **A cancelled lot is a fee, never stock.** The single largest disagreement —
  **3,478 LEDs** — was a purchase that never arrived. JLC settled lot `754166`
  with `orderStatus=40` (cancelled, refunded) and still reported
  `settlePresaleNumber: 3470`, so the importer, which tested only for a zero
  settled quantity, booked 3,470 pieces. `_lot_from_goods` now tests
  `cancelled`, which it was already computing and using for nothing but a
  display count. It is the only `orderStatus=40` lot in the account, across 17
  parts orders and 228 lots.
- **An imported parts order can take a correction.**
  `POST /api/jlc/import/parts/{pob}/refresh` re-states a document already in the
  platform from what JLC says today, lot by lot. It decides before it writes,
  keeps anything a person appended to a line's note, and refuses rather than
  guesses when a lot has vanished or when shrinking a line would contradict
  draws bound to it. Without it the cancelled lot could only have been corrected
  by hand.
- **Seven movements no invoice can report are now recorded.** JLC tops an order
  up from the shelf and says so only in the ledger: *"pick 3 pcs of C778132 & 8
  pcs of C965790 up to complete SMT order"*, and *"used 20pcs in 2nd Process"* —
  the whole of one part's gap, sitting unexplained since 2023. Each is written
  as an uncharged draw with JLC's quantity, date and wording, and the Stock page
  asks before writing any.
- **A movement JLC cancelled is not a movement.** `changeStatus=3` states a
  quantity and moves nothing. Excluding it, all 67 parts replay to the balance
  JLC reports; including it, two do not.
- **The ledger comes with the balance**, not on a second button. A balance alone
  can only say THAT the two disagree.

### The 27 legacy adjustments are now draws

`POST /api/jlc/import/adjustments/to-draws` rewrites the pre-0034
`external_project` adjustments as uncharged draws — dry-run by default,
journalled, reversible, and refused unless every row reproduces from its order
plan. Run on 2026-09-18: 27 rows across 7 orders, 1,094 pieces, $21.87.

- **No stock moved.** All 72 part balances are identical before and after; only
  the shape changed. The pieces now carry lot bindings like every other draw —
  27 of 27 bound to the purchase they came from, none unresolved.
- **Attrition and "other projects" both read zero** because neither exists any
  more: `reason='external_project'` has no rows and no writer, and the platform's
  recorded attrition was always genuinely nil.
- `pool.adjustments_usd` is now **0.00**, and the same $21.87 appears as
  `uncharged_drawn_usd`.
- The **Other projects** column is gone from the Stock table — permanently empty
  once nothing writes that shape. Its presence had pushed the table to fourteen
  columns against twelve declared widths, and `table-layout: fixed` silently
  squeezed the rest until a four-digit delta rendered as `-3,478…`. The widths
  now name all thirteen. `pool_state` still counts `external` apart from
  attrition, so a restored backup cannot quietly read as loss.

### An external order's stock is a draw, not an adjustment

The last writer of `reason='external_project'` is gone. When JLC builds
something this platform does not track, the stock now leaves as an **uncharged
draw** like everything else — `external_stock_movements` and
`apply_external_movements` are removed, and the answer to "what does a new JLC
usage become" is now unconditional.

- **Before**, `external` fell back to writing adjustments whenever the stock had
  not already been booked, so the old shape could still appear on new data.
- **A legacy adjustment now counts as already booked.** Without that, reversing
  and re-applying one of the seven affected orders would have written uncharged
  draws on top of its adjustments and removed the same stock twice.
- The 27 historical rows stay readable and stay on their own axis until they are
  migrated; nothing writes another.

### A cancelled JLC batch stops looking like work

JLC states a batch's status in the order listing the sync already fetches —
`shipped | inProduction | cancelled | waitPay | waitReview` — and `sync_stage`
was keeping only the batch number. Three batches therefore sat in **not
imported** indefinitely: a cancelled order is never invoiced, and neither is one
still in production, so an empty payload could not tell them apart.

- **`jlc_imports.jlc_status` records JLC's own word**, refreshed on every sync,
  kept apart from our `staged -> imported` lifecycle. A cancelled batch is shown
  as cancelled, excluded from the pending count, and no longer re-fetched every
  sync for an invoice that will never exist.
- **Found `W2026061105482196`**, a third cancelled batch nobody had identified —
  it carries a decision that was recorded and never applied, which is now
  explained rather than outstanding.

### A batch's material usage is typed in

The Materials tab's **Used** column is now editable, one row per BOM line. At
the end of production you type what was actually consumed and the batch is done.
The figure is absolute and idempotent, so correcting it later is the same
action — no compensating adjustment, which is what attrition was being used for.

- **Only for parts no supplier reports.** Enclosures, antennas and cartons —
  seven parts, half the pool by value, and every draw against them was BOM
  quantity x batch size, an estimate. A part JLC reported on its own invoice
  stays read-only: that is a measurement, not something to retype.
- **A draw is now priced by identity overlap.** Found while testing this: a draw
  entered by MPN alone priced at **$0.00** against a real $3.55 average, because
  the purchases were filed under a component id and the lookup keyed on the MPN
  — which would also have split the part into a second pool entry. The stock
  guard passed, so only the money was wrong. Both write paths go through
  `resolve_pool_identity` now.

### A supplier bills what was ordered

Also today: `effective_qty` multiplied a supplier's per-board rate by the
devices that PASSED, so LIFTECH's "5 PLN/board x 350" reconciled to 349 boards.
Because the conservation check reads the register absolutely, that $1.31
difference **refused every JLC import** from the moment
[0030](docs/decisions/0030-good-units-are-counted-not-typed.md) landed this
morning. Reasoning in
[0035](docs/decisions/0035-a-supplier-bills-what-was-ordered.md).

- **`planned_units` bills, `good_units` costs.** An assembler is paid for the
  boards they assembled; the yield loss is ours. Per-device cost still divides
  by the devices that passed — 0030 is unchanged on that point.
- **A merged assembler invoice is split, not guessed.** One printed position
  becomes a child per batch, each scaled by its own batch; that mechanism
  already existed and is now the documented answer.
- **"Written off" means attrition again.** Stock consumed by another project's
  assembly order is counted on its own axis. The two together read 1,094
  written-off pieces when the real attrition was zero, and attrition is a defect
  signal here. The Stock table gained an **Other projects** column.


## 2026-09-18 (the platform can see the fleet)

The platform now knows what its devices are doing after they leave the bench.
A read-only watcher subscribes to the fleet's MQTT broker and keeps each
device's live state current — `api/app/services/mqtt_monitor.py`, with the
reasoning in
[0033](docs/decisions/0033-the-broker-observes-devices-it-never-commands.md)
and the topic map in [mqtt-presence.md](docs/reference/mqtt-presence.md).

- **A device page shows a Broker card**: online or offline, when it was last
  heard, its ESP32 temperature, its WiFi ping, and the inverter model, inverter
  serial and dongle firmware the device reports about itself. "Never seen" is a
  THIRD state and is kept apart from "offline" — a device that was never
  deployed has nothing to report, and that is not a fault.
- **A project has a Devices tab**, beside Orders: every device built for it,
  with a live online/offline/never-seen count and filters. Orders is the demand
  side; this is the supply side.
- **The broker is watched read-only and never commanded.** Four leaf topics,
  never a subtree — `tele/#` would carry about 2,500 Modbus messages a second
  across the fleet. Nothing is ever published, so no command reaches a
  customer's device. `_assert_leaf_topics` refuses to start on a subtree.
- **Devices the platform does not know about are surfaced**, not hidden: 68
  were live on the broker on the first run. The presence table is keyed by MQTT
  topic, so an unrecognised device still gets a row and adopts its history if it
  is imported later.
- **The broker may FILL a missing MAC and may never CHANGE one.** Most V2-era
  devices were imported from reports that never carried a MAC, and those now get
  one. A device whose programmed MAC disagrees with the broker is reported to an
  admin and left untouched — a mismatch means a swapped board or a cloned
  configuration, and picking a side would destroy the evidence.
- **Broker settings are admin-only and encrypted at rest**, on the Admin page.
  Deliberately not an environment variable and not a Setup knob: the credential
  reads every customer device on the fleet. No endpoint ever returns the
  password.

## 2026-09-18 (four silent writers, found by an audit)

An audit of every write in the backend, prompted by the stock work, looked for
code that changes stored data as a side effect of something else. Four cases
were decided and changed:

- **A supplier's PDF edit no longer publishes a component version.** The
  nightly re-check used to file a PUBLISHED version stamped `approved_by=auto`
  whenever a datasheet changed. A publish re-runs the carry, so a part could
  lose its verification and sign-off overnight because a manufacturer re-issued
  a document. Now a RE-STAMP — same text, new cover date or scan — still
  publishes, and a real content change files a review request and leaves the
  current version alone. When the page diff cannot be produced, the change
  counts as real.
- **A re-flash records an identity change instead of overwriting it.** The
  bench wrote whatever IMEI, ICCID, IMSI and modem model it read back over
  whatever was stored, so a swapped SIM erased the only trace of the previous
  one. A changed value is now noted on the device and audited; filling an empty
  column is not a change and is not noted.
- **Reading a project no longer writes to it.** Fetching a snapshot could
  materialise a git checkout, classify its board kinds and commit the result.
  Ingest already does that classification; an older snapshot is now classified
  in memory on each read.
- **A deployment is no longer classified by its name.** A startup statement set
  `kind='test'` on any deployment whose name ended in "test", and another marked
  everything else active. It ran on every boot, so a deployment created tomorrow
  would have been reclassified by a text match. Both are removed; the rows they
  already filled keep their values.

## 2026-09-18 (a shipment names its devices)

- **A shipment is a set of serials, not a quantity.** `create_shipment` refuses
  a number with no devices behind it. The automatic oldest-first pick is gone,
  and the Ship card has no quantity box and no batch picker — the batch table is
  read-only, there to show the shelf while you scan. Measured before the change:
  **4326 of 4427 deliveries were machine guesses; 101 had ever been named by a
  person.**
- **A device now has a CONDITION as well as a location.** `ok`, `faulty`,
  `prototype`, `unidentified` — and only `ok` may ship. A unit that is here but
  unsellable stays visible, stays counted and stays put. Until now the only way
  to stop one shipping was to file it `disposed`, which said it had been
  destroyed: 32 working units sat that way while stock reported zero.
  `devices_available` and `devices_held` are reported beside
  `devices_in_stock`, which is their sum.
- **Nothing corrects stock automatically any more.** `reconcile_shelf` and
  `POST /api/stock/reconcile` are removed, and so is the return-swap that let a
  return against the wrong order line silently un-ship whichever device had been
  guessed into that place. A return against a line the device was never
  delivered on is now a 409 that names the lines it WAS delivered on. Correcting
  a wrong delivery is a deliberate act — `POST /api/shipments/{id}/reverse` —
  not a side effect of recording something else.
- **The platform no longer invents sales history at startup.** A migration ran
  on every boot and turned any production run carrying a sale price into a
  customer, a sales order and a delivery of units "without a serial" — silently,
  with no audit row and nothing asking for it. It was not one-shot: a run priced
  tomorrow would have become an order and a shipment at the next restart, and it
  bypassed both new rules above. Removed. See
  [decision 0032](docs/decisions/0032-a-shipment-names-its-devices.md).

## 2026-09-18 (two register rows were describing work already shipped)

- **The manufacturer `one_of` is live** as `cmp.manufacturer_canonical`: a
  99-name list, warning severity by design, because an off-list name usually
  means the list is short rather than the data wrong. It carries the names the
  work list recorded as missing and resolves the `Murata` and `Infineon`
  duplicates. Two loose ends remain and stay on the register: the list holds
  both `Kinghelm` and `Shenzhen Kinghelm Elec`, and four names still need a
  maintainer decision.
- **"There must be no X" is expressible and authorable**, so the `disallow`
  half of its row is closed. It ships as `at_most 0` and `absent`, both offered
  in the checklist editor, and the sentence generator prints them forwards —
  "No plated holes whose copper is no wider than the drill" — instead of
  backwards. No assertion named `disallow` was added, and none is needed. Live
  on `fp.zero_annulus`, `fp.model_path`, `cmp.pins_to_pads` and others.

## 2026-09-18 (the datasheet clean-up is finished on production)

- **The byte-rule history is collapsed and the storage rewrite has run.** The
  work `docs/todo.md` row 2 tracked is complete: production reports 487
  documents over 619 versions and **571 MB**, down from 704 versions over 557
  files and 1079 MB. The local rehearsal had predicted 602 MB, so the outcome
  landed slightly better than the estimate. `GET /api/datasheets/restamps`
  returns nothing, and `POST /api/datasheets/restamps/collapse` now finds
  nothing left to remove. See
  [decision 0004](docs/decisions/0004-datasheet-identity-and-storage.md) for the
  identity and storage rules this was applying.

## 2026-09-18 (no serial, no production)

- **A batch that records its devices can no longer supply a unit "without a
  serial".** `run_stock` already said so in arithmetic — such a batch has a
  legacy pool of zero — but only after the fact, as an `overdrawn` flag that
  reads as a warning about the batch when it is really a contradiction in the
  shipment. Nothing enforced it where the unit was written, so a stock count
  wrote 40 of them on 2026-09-17 against batches holding 521 and 1025 device
  records. Every path that can write one now refuses with 409 naming the batch.
- **The "keep the invoiced quantity" option is gone.** It could only ever draw
  from the freed device's own batch, which records that device by definition,
  so it can never be honoured. A slot nothing can refill now lowers what its
  order counts as delivered — either a real device fills it or the quantity
  falls. See
  [decision 0031](docs/decisions/0031-a-batch-that-records-its-devices-has-no-anonymous-units.md).

## 2026-09-18 (money charged to nobody stops looking settled)

- **A document whose money is wholly excluded is badged `excluded`, not
  `assigned`.** `excluded` means "recorded so the document reconciles, charged
  to NOBODY on purpose" — reclaimable import tax, or the prepaid-component
  share of a populated-board price. It counts as fully assigned, so such a
  document showed a green `assigned` pill beside an empty destination and the
  "only unfinished" filter hid it. Three whole JLCPCB board invoices sat that
  way from 2023 until somebody went looking: `2014632A202310101833996`
  ($991.93), `2014632A202312121800359` ($2,054.51) and
  `2014632A202402200414673` ($902.04). The destination column now names the
  excluded amount too.
- **`PATCH /api/shipment-lines/{id}` names the batch behind a shipment's units
  without a serial.** Such a unit is costed from the batch its line names
  (decision 0003 §8); a line naming none is delivered but uncosted, and the
  batch goes on counting those units as stock it still holds. There was no way
  to fill it in afterwards, which is exactly what a prototype batch
  reconstructed from its invoices needs — the batch is created long after the
  delivery was recorded.

## 2026-09-18 (per-device cost divides by the devices that passed)

- **Every per-device figure now counts the device records instead of reading a
  typed quantity.** `qty_good` is documented as "units that actually passed,
  actual per-device cost divides by THIS" and was NULL on every production run
  in the platform — so was `plan_qty` — so every figure fell through to `qty`,
  the boards **ordered from JLC**. Decision
  [0007](docs/decisions/0007-built-means-finished-and-passed.md) settled this
  for stock two years ago; the register never followed.
  **Twelve batches change unit cost**, and order margins move with them:
  CE_Aqua_V2 Batch 5 $19.81 → $27.06 (250 boards ordered, 183 passed),
  CE_Aqua_V2 Batch 3 $19.80 → $15.09, CE_Dongle_V2 Batch 5 $16.33 → $13.08
  (455 ordered, 568 passed). The new figures are the correct ones. See
  [decision 0030](docs/decisions/0030-good-units-are-counted-not-typed.md).
- **The run editor no longer offers to type "Units good"** for a batch the
  flasher recorded, and the run page says when a figure fell back to a typed
  quantity instead of counting devices.
- **A glossary**, because two words in this platform each name two unrelated
  things: "run" is a manufacturing batch AND one attempt at programming one
  device; "order" is a customer order AND a purchase from JLC. It also sets out
  what `qty`, `plan_qty`, `qty_good` and `qty_sold` each mean, and why
  `Batch 7 — 1000 pcs` is a purchase order rather than a count of what exists.
  [docs/reference/glossary.md](docs/reference/glossary.md).

## 2026-09-18 (a device can be moved to the batch it was really built in)

- **`POST /api/runs/{id}/rebatch` moves devices out of the batch the bench
  picked by mistake.** The batch on a `produced` event is chosen from a list
  before the first device of a shift passes, and `mark_produced` refused to say
  otherwise ever again — so a shift programmed with the wrong batch selected
  filed every one of its devices against it permanently. That is not cosmetic:
  a batch's device count is its `built` figure, its stock, and the per-device
  cost every shipped device carries onto its order. `dry_run` is the default
  and the plan names each device with the batch it would leave. The event is
  not replaced: its batch moves, its note keeps where it came from, and the
  audit row names who moved it. See
  [decision 0029](docs/decisions/0029-the-batch-on-a-produced-event-is-correctable.md),
  which also says why this is the only field in the log that works this way.

## 2026-09-18 (who answered is a glyph, not a word)

- **A verification pill names the actor with one glyph.** `checked (agent)`
  and `failed (machine)` — uppercased by the pill style into `CHECKED (AGENT)`
  — were the widest things a review column printed, and narrow cells clipped
  them. The pill now reads `checked 🤖` (an agent run) or `checked ⚙` (the
  validator on publish); a human answer carries no mark. The full word is still
  in the pill's tooltip. One map, `actorMark` in `Ui.tsx`, serves both the
  aggregate pill and the per-item pills on the verification card.

## 2026-09-18 (a pin-1 mark that exists is not a pin-1 mark that reads)

- **New derived fact `$footprint_pin1_marks_offspec`.** `fp.pin1_mark` only
  ever asked that at least one `Cmts.User` circle sits within 2 mm of pad 1.
  It never asked what the circle looks like, so a wrong-sized mark — and, worse,
  an unrelated `Cmts.User` circle that merely happens to sit near pad 1 —
  passed it. The new fact counts the circles that are NOT the house mark, a
  0.1 mm radius with a 0.2 mm stroke. A circle whose width the file does not
  state counts as off-spec, because a mark nobody can measure is not one
  anybody can rely on.
- **Measured across the whole library on 2026-09-18: 40 of the 199 footprints
  that have a pad 1 carry an off-spec mark**, and the sizes cluster — 17 at
  r 0.15 / w 0.3, 6 at r 0.25 / w 0.5, 5 at r 0.06 / w 0.25, which is the
  EasyEDA import writing its own size. Five more are not pin-1 marks at all
  (r 0.9 to 3.25); those were passing `fp.pin1_mark` on a circle that means
  something else entirely.

## 2026-09-18 (a verification note has a ceiling, and it is silent)

- **`record_verification` drops any item whose note is over 400 characters,
  and reports success.** The call returns `ok: true`, the other items land,
  and the long one stays unanswered — nothing says so. Found while closing the
  CE_Dongle_V3 footprints, after one call lost 4 of 7 items. Measured: 358
  characters landed, 405 did not. Written up, with the one-line guard that
  makes the loss visible, in
  [what-a-check-can-hold.md](docs/reference/what-a-check-can-hold.md).

## 2026-09-18 (a release is one thing)

- **Production → Files lists releases, not file versions.** A berryware
  release is one row: its files, its size, which deployment versions pin it,
  and per file whether it is the same as the newest older release that
  carried that name. The per-file pool with a version number on every script
  is gone, and so are the bundles beside it — a release IS the set
  ([decision 0029](docs/decisions/0029-a-release-is-a-file-set.md)).
  Releases are platform wide: the same folder imported for two projects is
  one row, and the same driver JSON is stored once.
- **Derive… makes a release from a release.** Replace or add files by
  upload, borrow files from any other release, leave some out, name the
  result. The base is untouched. This replaces both "upload a new version of
  one file" and "name a set of stored files".
- **Artwork has its own tab.** One LightBurn file is one drawing; a marking
  step picks a drawing or uploads one, and the version pins it the same way
  it pins a release.
- **A version card shows one pill per set** — the release and the drawing —
  each linking to its row on the Files page. The device URL is now
  `/api/flasher/files/{set}/{filename}`; every stored procedure uses the
  default template, so nothing had to be re-published.
- **Old links keep working**: `?tab=bundles` and `?tab=files` open the
  releases tab.

## 2026-09-18 (a shield tab is not a missing pin)

- **Six shielded connectors stop reading `failed`.** `cmp.pins_to_pads` dropped
  the non-electrical pad names `MP` and `SH` from the footprint's pads but not
  from the symbol's pins, so every connector drawing the house `SH` shield pin
  reported one pin with nowhere to land — `GT-USB-7010ASV`, `HR913550A`,
  `NANO_SIM_TL6P_H1.35`, `R-RJ45S08P-B000`, `RC01812` and
  `U262-161N-4BVC11`. Their raw pin and pad numbers matched exactly in every
  case. The names now leave both sets.

## 2026-09-17 (the stock count has a screen)

- **Production → Orders can count the shelf.** Paste what a scanner read —
  a plain list, or the CSV a scanner exports, header and timestamps included —
  and the card shows the plan: how many recorded deliveries would be taken
  back, how many refilled from stock, how many left empty, and every order line
  whose delivered quantity would move. Nothing is written until you press again.
  A code that is not a device is named and dropped with one button, which is
  what the two stray EAN barcodes on the 2026-09-17 sheet needed.
- **A shipment row has a "Take back" button** for a delivery recorded in error,
  and shows how many of its deliveries were already taken back. The delete `×`
  now follows whether the API would actually allow a delete: a reversed
  shipment carries no device but still carries events, so it offered a delete
  that answered 409.
- **The Ship card takes scanned serials.** It accepted only device row ids,
  which no scan sheet carries — its own hint told you to go and look each one
  up. Serials and ids now go in the same box, and a serial nothing carries is
  named instead of quietly shipping a shorter list.

## 2026-09-17 (a boxed device stops asking to be built)

- **Demand counts a device allocated to an open line as supply.** An
  `allocated` device is on the shelf, reserved for one order line, and
  `run_stock` leaves it out of stock by design (decision 0003 §9) — but the
  line it is held for still shows its open quantity. `GET /api/demand`
  therefore counted a boxed device as one to build and not as one already
  there: 32 dongles packed for order 17 read as 32 to make. Supply is now shelf
  stock, plus devices allocated to the lines whose open quantity the same
  figure is measuring, plus planned batches. An allocation to a line that is
  already fulfilled counts as neither.

## 2026-09-17 (a shipment can be taken back)

- **A device the stock count put back on the shelf now counts when it ships
  again.** `create_shipment` marks a device as its own replacement when it
  finds an earlier `shipped` event on the same line — the rule that stops a
  repaired device counting twice — and it read the raw event log. A delivery
  that an `unshipped` event had REVERSED still looked like a previous delivery,
  so re-shipping such a device recorded a replacement and added nothing to the
  order. It reads `live_shipped_of` now. A device that really was delivered,
  came back and went out again is still its own replacement.
- **`POST /api/shipments/{id}/reverse` takes back a shipment recorded in
  error.** Every delivery on it is reversed, its anonymous units go to zero and
  the devices return to stock. `dry_run` is the default. The header and its
  events stay — device history is not deleted, and a shipment the customer
  actually received still comes back through `POST /api/devices/{id}/return`.
  See [decision 0028](docs/decisions/0028-a-shipment-recorded-in-error-is-reversed-not-deleted.md).

## 2026-09-17 (a stock count can correct the record)

- **A shelf count now reverses the FIFO guesses it contradicts.** A shipment
  without serials draws devices FIFO (decision 0003 §6), and that pick is a
  guess. Until now a customer return was the only thing that could correct one,
  so a count that found a device sitting on the shelf while the platform said
  it was at a customer had nowhere to go: `create_shipment` refuses a device
  that is not in stock, `delete_shipment` refuses a shipment that carries
  device events, and the device PATCH writes notes. `POST /api/stock/reconcile`
  takes the devices a count found — by id or by the serial a scanner read —
  reverses each `auto` FIFO pick that contradicts it, and refills the slot from
  stock, oldest produced first. `dry_run` is the default, so the first answer is
  always the plan. See
  [decision 0027](docs/decisions/0027-a-stock-count-corrects-a-fifo-guess.md).
- **A `shipped` event somebody typed is never reversed by a count.** The call
  fails and names those devices. A count says where a device is, not who is
  wrong about it.
- **Reversing a delivery no longer reads as a second one.** `DeviceEvent` is
  append-only, so an `unshipped` event lands after the `shipped` event it
  reverses without removing it, and every fulfilment and cost figure counted
  raw `shipped` rows. `live_shipped_events` now pairs the two, and
  `line_shipped`, the order line counts and `order_economics` all read it. This
  also fixes the swap in `_swap_into_line`, which had been inflating a line's
  `qty_shipped` by one for each correction it made — no production order had a
  return yet, so no recorded figure changes.

## 2026-09-17 (the marking bench survives its second device)

- **The agent no longer wedges after one mark.** A bench marked one unit and
  then refused every following one with "the agent is already marking" until it
  was restarted, which cost a restart per device. The agent's health poll and a
  mark each bind the same UDP reply port, and `SO_REUSEADDR` does not let two
  sockets share a UDP port on macOS — the second bind gets errno 48. The
  marking thread built its LightBurn client outside the `try` whose `finally`
  clears the "busy" flag, so the losing thread died before that line, the flag
  stayed set for good and nothing was written to any log. The two now take one
  lock, a poll that finds a mark running answers without binding, and the
  client is built inside the `try`. `_run` and `_print` also gained the
  catch-all `except` that `_esp` already had, so a thread that dies says so in
  the job and in the agent's log. Reproduced and fixed against the bench:
  unpatched, 1 mark passed and the next 19 were refused; patched, 20 of 20
  passed under continuous health polling, then three full sessions on real
  hardware.
- **A quiet device no longer reports a false agent timeout.** The console long
  poll is held by the agent for 10 s and the page aborted at exactly 10 s, so
  any 10 s silence was a coin flip that produced "the bench agent did not
  answer within 10s" from a poll that was working. The page now allows the
  hold plus 5 s.
- **`mark.py` runs again.** The command-line marking tool called `time.time()`
  without importing `time`, so it raised `NameError` on its first line. The
  agent itself was unaffected.
- **A finished mark is machine-proven.** With the laser attached, LightBurn
  answers `STATUS` with `!` for every poll while a job runs and `OK` when it
  ends, measured twice at 9.7 s on the dongle side artwork. The code carried a
  "NOT YET VERIFIED" note saying to treat a mark as operator-confirmed until
  someone checked this on the bench; that note is now the measurement.

**Benches must download the agent again** from the Flasher page. The fix is in
`agent.py`, and an installed copy carries the old one. `PROTOCOL_VERSION` is
unchanged at 4 because no route changed, so nothing will warn you.

## 2026-09-17 (device files know what they are, and the procedure editor grows up)

- **A device file is berryware or artwork, and every screen says which.** The
  pool held the LightBurn `.lbrn2` a mark version engraves beside the `.be`
  scripts a device downloads, and the version card, the diff, the timeline
  line, the bench summary and the pool all called both "berryware". A `kind`
  column on the file now drives the label: a mark version's card reads
  **Artwork**, its change summary reads "artwork (1 changed)", and the pool
  shows a kind pill per row. Backfilled from the extension
  ([decision 0026](docs/decisions/0026-a-device-file-carries-its-kind-and-enters-by-upload.md)).
- **Files are uploaded, not pasted.** The paste-the-text editor on the
  Individual files tab is gone. **Upload a file…** takes one or many files and
  publishes them; an artwork row has its own **Upload** for a new version
  under the same name; berryware rows have none, because the Bundles tab's
  folder import is how berryware is updated. A file that is not UTF-8 text is
  stored and served as bytes instead of being refused.
- **The marking step owns its artwork.** `Engrave the serial` shows the pinned
  drawing's own LightBurn thumbnail, a picker over the project's artwork, and
  **Upload a new .lbrn2…** — the upload publishes into the pool and re-pins
  the draft in the same action. The server refuses a non-LightBurn file there.
  The engine now hands the laser only artwork and the device only berryware,
  and the publish gate says "pins no artwork (.lbrn2)" instead of "no template
  file".
- **The pool says what is in use, previews any file, and deletes one version
  at a time.** A **Used** column reads "in use" or "not used" from the same
  join the delete guard uses; the eye button opens a popup with the LightBurn
  thumbnail and the full text (or, for a binary, its size and a Download);
  the row's × removes the newest version and the server still refuses a
  pinned one. Every version row shows who pins it.
- **A finished device's verdict no longer greets the next one.** PASS, FAIL and
  ABORTED survived a device swap on both benches, so a unit arrived under the
  previous one's result. The verdict, the step label, the progress bar, the
  engraved and printed readouts and the run link now clear when the next device
  arrives — not when the finished one is removed, so the operator still reads
  PASS with the part in their hand. The log is kept, with a line marking where
  one device ends and the next begins.
- **The benches open ready.** Picking a project on the flashing bench now
  selects its latest batch (newest run date) as well as its config version;
  the marking bench selects the project's marking procedure. Clearing the
  batch to "bench trial" sticks until the project is picked again. This
  reverses the 2026-09-16 rule that left the batch empty on purpose.
- **The label is drawn before it is printed.** A `print_label` step now shows
  the label as the bench agent will lay it out — the Code 128 symbol and the
  value under it, at the roll's true proportions, turned when the step says
  so — for a sample serial the author can change, and prints the agent's own
  refusal in red when the value does not fit ("needs 47.5 mm, this roll prints
  22.9 mm across") before the printer ever sees it. On the bench machine the
  roll is picked from the printer's own list and the printable area is the
  printer's; anywhere else the label is drawn at its nominal size and the
  caption says so. `web/src/flasher/label.ts` mirrors the agent's encoder
  and layout, checked module-for-module against it.
- **The procedure has an edit mode.** A draft opens read-only and **Edit
  procedure** turns it into a form; a published version offers **Edit as new
  version**, which mints the draft and opens it editing (so does **New
  version**). Every field is a typed control: a duration is a unit box (type
  `500ms`), a count a number box, a flag a checkbox, a value a
  value/parameter toggle; command, capture and image lists are numbered rows
  that move up and down; a step can be duplicated. Typing is saved after a
  pause instead of on every keystroke, and flushed before a publish.

## 2026-09-17 (the bench agent stops hanging)

- **The 7Sigma agent no longer freezes.** Its window, its status page and the
  bench's `/ready` call each asked CUPS for the printer picture on their own
  and at once, and one of those calls (`lpinfo -l -v`) takes 5.5 s on a Mac
  with nothing plugged in — the window ran it on its own main thread every
  second. Measured before: `/ready` 25 s, the status page 31 s. After: both
  under 0.1 s. One watcher now takes the picture every 10 s and everything else
  reads it. **Benches have to download the agent again** — nothing updates it
  in place, and `/hello` reports the same protocol as before because no route
  changed.
- **A printer button waits for its own result.** "Set up" and "Remove" refresh
  the picture before the page reloads, so the queue they made is on it.

## 2026-09-17 (a device fetches from its own address)

- **Berryware downloads work on production.** Step 16 of `Dongle_V2 config` had
  never run there before, and it failed every retry with `TLS connection error
  296`: the device was sent `https://disfunction.cc/lib`, and a Dongle V2
  completes **0 of about 12** HTTPS attempts against the Cloudflare edge. Over
  plain HTTP by name it succeeds every time.
- **`DEVICE_BASE_URL` is a new setting**, ranked above `PUBLIC_BASE_URL` when the
  engine picks the address a device fetches from. Empty by default, which means
  "the same address browsers use". Production sets it to
  `http://disfunction.cc/lib`. No deployment version changed and none needed
  re-publishing — no step overrides the download URL.
- **Stated rather than buried**: the scripts now cross the internet in the clear,
  and the download step still verifies the byte count rather than the sha256 it
  already holds. Tasmota validated no certificate before this change, so HTTPS
  was buying the device encryption to an unverified peer and nothing else. Full
  reasoning and the measurements in
  [decision 0025](docs/decisions/0025-a-device-fetches-from-its-own-address.md).

## 2026-09-17 (settings that touch hardware live on the platform)

- **The transport profiles left the browser.** The baud a device is flashed at,
  whether a reset re-enumerates USB, and whether the console may touch DTR/RTS
  were TypeScript constants in `station.ts` — so changing any of them needed a
  web deploy and moved every deployment on that profile at once. They are in
  `services/flasher/transports.py` now, `/meta` serves them, and the engine
  sends the resolved profile with each run.
- **A step states its own serial baud.** `esp_connect`, `erase` and `flash` take
  a `baud`, editable in the step editor, blank = the profile's default, and
  refused at publish if the bench cannot speak it. Measured on a Dongle V2:
  **460800 = 45.4 s, 750000 = 32.5 s**, while 576000 and 921600 corrupt the
  transfer — the CH340's 12 MHz clock divides exactly into 750000 and not into
  the others.
- **Three more constants followed**: what a marking template says where the
  serial goes (the browser decided what got engraved), the label rolls (its own
  comment said "add a row here when a roll is bought"), and the serial length
  bounds. All now come from the platform or the printer's own PPD.

## 2026-09-17 (light or dark, and the platform remembers which)

- **The platform can be set to light or dark, on Account → Appearance.** Three
  choices — System, Light, Dark. System is the default and follows the operating
  system, including a change made while the page is open.
- **The choice is stored on the ACCOUNT, not in the browser.** Signing in on the
  bench machine gets the same platform as the laptop, with nothing to set twice.
  The browser still caches it, because the theme has to be applied before the
  page paints and the sign-in request has not answered by then.
- **Kuba Remian's account was set to dark** on the production platform.

## 2026-09-17 (an out-of-date bench agent says so)

- **The flashing bench refuses to start a run against an agent that cannot
  program**, and says which it is. The agent is DOWNLOADED, not deployed, so a
  bench can be weeks behind and look healthy: one was, and the run failed
  part-way with the agent's own 404 — `no such path` — after a device was
  already in the socket. The page now asks at `hello` and shows a banner, and
  the relay refuses before it touches the device, because a banner can be
  scrolled off.
- **It tests the capability, not the version.** `/hello` reports the esptool the
  agent carries, and that is the question. `PROTOCOL_VERSION` had been left at 3
  through the change that added programming, so the number could not tell the
  two apart — it is 4 now, but nothing depends on it for this.

## 2026-09-17 (a version says which parameters it needs)

**Editing a project's parameters can no longer break a version published months
ago without telling you** ([decision 0024](docs/decisions/0024-a-version-declares-the-parameters-it-needs.md)).

- **A deployment is linked to a parameter set, and says so under its
  description.** The link used to exist only on each version, picked inside the
  composer — so a new deployment was wired to nothing and you found out when a
  publish was refused for an unresolved `{MqttHost}`. A new deployment in a
  project with one set now takes it, its first version inherits that, and later
  versions inherit from the version they were composed from. A published version
  keeps the set it was made with whatever the deployment does later, and its
  card says **deployment now defaults elsewhere** when the two differ.
- **A new version is edited where it is read, not in a popup.** `New version`
  creates the draft, selects it, and the card on the right becomes the editor —
  note, procedure, transport, monitor baud and parameter set, each saving as you
  change it. The `Composer` modal is deleted: it rendered the same four sections
  a second time over the top of the read-only ones, so a procedure had two
  renderings and they had already drifted on which controls a section carries.
- **A version can be removed.** `Delete this version` on any draft or rejected
  version takes it out entirely rather than leaving a rejected row behind. It is
  refused for a published version — that is what a device was given — and for
  any version a programming run records, which keeps the old reject-as-history
  behaviour where it belongs.
- **The kind dropdown is three words.** `flash · test · mark`, with what each
  one does on the ⓘ instead of inside every option.
- **A new deployment is an empty card, not two prompts.** The + tile creates
  the row, selects it and puts the caret in the name — the two `prompt` dialogs
  asked for the same fields the card already holds, so the answers were typed
  twice. Pressing + twice gives "New deployment 2" rather than a unique-key
  error.
- **Chip is a dropdown everywhere.** The platform knows which parts it supports,
  and the validator refuses a version whose transport does not match its chip,
  so a free-text box could only ever produce a typo that fails at publish. A
  blank option stays — a mark or test procedure legitimately has no chip.
- **Parameters have their own page**, `Production → Parameters`. They were a
  fourth tab under Files, beside firmware images and berryware bundles — but a
  parameter is not an artefact a version pins, it is what a version depends on
  and does not contain.
- **Each key says which published versions need it.** `Dongle_V2 config` v10
  needs seven keys and v18 needs four, both pointing at the same set; removing
  the three v18 stopped using breaks v10, and nothing said so until a run was
  attempted with a device in the socket. Removing such a key is now **refused**,
  naming the versions. Deleting a set in use is refused too.
- **A history of what moved.** Every save appends a revision with a note: which
  keys arrived, which left, and which changed value. A key whose NAME survives
  and whose MEANING changes — a broker repointed, a salt rotated — used to pass
  every check the platform had. Each programming run now records which revision
  it used, so a unit can be traced back to the values it was given even though
  the secrets themselves are never stored twice.
- **A draft run is validated like a published one.** It was exempt, and that is
  where it mattered most: an unresolved `{MqttHost}` is left as literal text,
  the step that writes it compares what it sent against what it read back, and
  the device shipped configured against a broker called `{MqttHost}` with the
  run reporting **pass**.
- **The history can be reverted to.** "Revert to this" on any earlier revision
  puts those values back — including the secrets — and **appends** rather than
  rewinds: reverting r5 to r2 writes r6, so the record still says r3-r5 happened
  and that somebody undid them. The same refusal applies, since an old revision
  can be missing a key a version published since then needs.
- **Editing is in place.** The Parameters page IS the editor: type in the row,
  and Save, Cancel and the note appear only once something differs from what is
  stored. No dialog, and values are shown in the clear — a parameter is a bench
  setting you came to the page to read, and it is already behind the sign-in
  gate. Storage is unchanged: the set is encrypted at rest either way.
- **A key nothing reads is marked `unused`.** Which versions DO need it is on
  the × and in the refusal — a parameter set belongs to one project, so listing
  them was a wide column naming siblings of the project already selected.
- **The deployment page lost what it did not need.** The tagline is gone, the
  deployment list is tiles with a **+** to add and a **×** to remove, and the
  `→ production` / `→ bench` buttons are gone from every version row — they
  pointed a channel a batch could follow, and no batch in the database follows
  one. Version rows went from 96 px to 78 px, so all seven fit on one screen.
- **`creds_salt` is counted.** `derive_credentials` reads it directly instead of
  interpolating it, so the one key whose loss cannot be recovered from at the
  bench read as "needed by nobody". A version missing it now fails to publish
  rather than failing mid-run, after the erase.

## 2026-09-17 (the bench sets its own printer up)

**A new bench no longer needs anyone to know how CUPS works.** The agent's
status page now says what is missing and gives you the button that fixes it.

- **The printer is found, matched and set up by the agent.** It names the
  printer that is plugged in, matches its driver exactly, builds the queue, and
  repairs a queue that is on the wrong driver. None of it needs a password.
- **It refuses to guess.** CUPS offers five DYMO drivers that look plausible for
  a LabelWriter 550 and only one that works; a queue on any of the others
  accepts jobs, reports success and prints nothing. Measured, on a powered
  printer, which is why the match is exact rather than "close enough".
- **The one step it cannot do is named plainly**: install DYMO Connect for
  Desktop once, with the brew command offered for copying. The application can
  be deleted afterwards — the bench uses only the driver it leaves behind.
- **The queue is built without being asked.** A printer that has a driver and
  no queue gets one within ten seconds of being plugged in. A queue on the
  wrong driver is still repaired by the button, not silently.
- **A console nobody is using gives its port back.** Closing the tab used to
  leave the serial port held until the agent was quit, and anything else
  wanting that port was refused. After two idle minutes the agent closes it —
  never during a mark, a print or a flash.
- **LightBurn gets a button too**: not installed offers the download, installed
  but silent offers to open it.
- Everything the page shows is also served at `GET /ready`, so the bench page
  and the status page cannot end up giving different advice.

## 2026-09-17 (a deployment card you can read)

- **The version's note is prose, under a label.** It was drawn in the caption
  style — 11px uppercase mono — run together with the author and the date, so a
  five-line paragraph looked like a heading nobody could place. It now says
  **Note on this version** and reads as a sentence. The caption keeps the short
  facts: who, when, and what changed.
- **The description box fits what is in it.** Two fixed rows hid the second half
  of every description behind an inner scrollbar with nothing to show it was
  there. It grows to its content and stops at 14 rows.
- **Name and Chip share a line**, the three permanent hint lines are ⓘ markers
  on the labels, and **New version** moved down to the versions bar where it
  acts. The card lost 68 px while showing 67 px more description.
- **The page is two columns, and the wide one is the procedure.** The left
  column used to be a picker for three deployments; they are tiles across the
  top now, keeping the pills that say which version each channel runs. The
  detail column went from 660 px to 864 px at a 1500 px window, which is the
  difference between `Write factory image …` and the whole step with its
  command and value. **The procedure also moved above firmware and berryware**,
  which are one table row and one pill and were pushing 28 steps off-screen.
- **A version row no longer repeats the note.** Seven versions of one deployment
  open with the same sentence, so a clipped copy per row told them apart not at
  all. The row keeps what changed; the note is on its hover and in full on the
  card.

## 2026-09-17 (find the socket by plugging the device in)

- **Assign socket… is a live list.** It opens even when nothing is plugged in,
  watches the agent's ports while it is open, and marks anything that appears
  as **new**, at the top. Plug the device in with the dialog open and take the
  row that appeared — the same trick Chrome's port picker used, now against
  the agent's real `/dev/cu.*` names. Both benches use it.

## 2026-09-17 (the bench asks one question about a batch)

- **One dropdown, not two.** The flashing bench had a `batch run` / `bench
  trial` select beside the batch select, so "batch run" with nothing picked
  was a state it had to warn about and which disabled Automatic. Now the batch
  dropdown starts with **no batch — bench trial**: picking a batch makes the
  run production, leaving it makes it a trial that may run a draft.
- **The Test button is gone from a station.** A test is an ordinary deployment
  with `kind: "test"` — pick its version and press Program. The button ran a
  different version than the one on screen.

## 2026-09-17 (a deployment is configured on its own page)

- **The WiFi, MQTT and the other placeholder values are editable from the
  deployment.** *Edit values…* on a published version's Parameters card and in
  the composer's Parameters section open the same editor the files page uses
  (`ParamSetEditor`); secrets are masked with a show toggle. Both say plainly
  that a param set is shared and not versioned: a change reaches the next run
  of every version that points at it.
- **The deployment's own fields are boxes, not prompts.** Name, description
  (stored on every deployment and never shown until now), kind, chip and the
  test default for new batches are plain fields on the deployment's card;
  **Save** and **Cancel** appear only once something differs from what is
  stored, and one Save writes the whole row. *New version* sits alone beside
  the name and Delete alone at the far end. It used to be six buttons in one
  wrapping line, each opening a popup.

## 2026-09-17 (the bench is browser-independent)

**The bench agent does every byte of serial work, and Web Serial is gone**
([decision 0023](docs/decisions/0023-the-agent-programs-the-device.md)).
Connect, erase, flash, reset and the device console all run in the agent on the
bench machine, against the socket a station owns. The page names the socket and
relays the log; it opens no port.

- **`Assign socket…` is a list of real port names** — the agent's own
  `/dev/cu.*` nodes, with who holds each — instead of Chrome's port picker.
  A station keeps its socket across replugs and reloads.
- **Nothing to grant and nothing to lose.** No serial permission, no per-unit
  picker on a CH340 that has no serial number, no
  `SerialAllowUsbDevicesForUrls`, no secure-context requirement. A deploy can
  no longer break a bench tab that is open, because nothing in the flashing
  path is lazily loaded any more.
- **The agent download carries `vendor.zip`** (esptool 4.8.1 + pyserial, pure
  Python, 634 KB), extracted once on first start. The agent window and
  `/hello` report which esptool it has.
- **A bench with no agent cannot program**, by design — one implementation, no
  fallback. Both benches say so plainly, and the flashing bench keeps a
  heartbeat so the message is current.
- **Confirmed on hardware, then the browser's flashing dependencies were
  deleted.** Runs 6383, 6384 and 6385 all passed through the agent at 460800
  baud on the first rung, and 6385 joined WiFi and pulled its 18 configuration
  files — so `esptool-js`, `js-md5` and the Web Serial types left
  `web/package.json`. The bundle no longer carries a chip module at all.

## 2026-09-17 (a deploy no longer breaks an open bench tab)

- **A bench tab opened before a deploy failed every connect as "BOOT was not
  held"** (prod run 6329). esptool's chip module is a lazily loaded, hashed
  chunk; the deploy replaced it; the browser could not fetch it; and the
  connect ladder treated that as a device that would not answer. The page now
  reloads itself once when a chunk is missing, and the ladder stops at once
  with "this page is out of date — reload" instead of walking its rungs.
- **A mark is now machine-checked.** The first production mark showed
  LightBurn's `STATUS` reporting busy for the whole 10.5 s job, so a job that
  reports idle immediately did not run. Recorded in
  [docs/reference/laser-marking.md](docs/reference/laser-marking.md).

## 2026-09-17 (deployments can be published and re-kinded from the page)

- **A draft version has a Publish button on the timeline.** Publishing lived
  only inside the editor, so a draft finished anywhere else — the API, another
  machine — had no status control at all. Same server gate: no comment or a
  validation error still refuses, and says which.
- **A deployment's kind is a button next to its chip** — flash, test or
  mark. The bench reads the kind, never the name, and it could not be changed
  after creation.
- **The version editor scrolls.** A procedure with 28 steps made the card
  taller than the window, the page behind it is locked while a modal is up,
  and the Publish button sat below the fold with nothing able to scroll to
  it. Every modal's backdrop now scrolls, and a wide card starts near the top.
- **The flashing bench keeps a heartbeat to the agent** and says whether it
  is running, so the agent's own window no longer reports that no bench page
  has ever connected.

## 2026-09-17 (the laser marks)

**The AtomStack M4 marks from the platform for the first time.** Since the
marking bench was built it had traced every job with the pointer and engraved
nothing; a clean LightBurn install had the board in fibre mode with no analog
power output, and "Require framing before start" turned every `START` into a
framing pass. The machine's whole configuration — laser mode, the analog power
line, the port map for the pointer and the second source, how a layer picks
the 1064 nm or the 450 nm source — is now measured and written down in
[docs/reference/laser-marking.md](docs/reference/laser-marking.md).

- **A `mark_laser` step's `device` names a LightBurn PROFILE, not a source.**
  The doc and the field's hint said the agent's `LASER:` command chose which
  laser fired. It does not: the artwork's layers do, and the profile only
  carries the calibration for one of them. The profiles are now named
  `M4 IR 1064nm` and `M4 Diode 450nm`.
- **`AQUA_DONGLE_Side_Info.lbrn2` v3**: the serial layer at 100 % and
  600 mm/s, measured on white ABS, and `DeviceName` set to the IR profile. The
  marking draft (Dongle_V2 marking v2) pins it and names the IR profile; it is
  still a draft.
- **The agent window shows its five facts, and has a status page.** The
  window was blank because the Tk that macOS's own Python carries draws no
  text in any widget except native buttons and the title bar (measured with
  screenshots). It is now five flat buttons — Listening, LightBurn, Printer,
  Chrome, Bench page — with the verdict in the title, and each opens
  `http://127.0.0.1:19842/`, a self-refreshing page with the full text and
  the log. "Open the log" opens the log file itself.
- **The agent reports whether the laser is actually there.** `GET /health`
  carries `laser_usb` — the controller board seen on the bench machine's USB
  bus, or not — because LightBurn's `STATUS` answers `OK` with the board
  unplugged. The agent window has a Laser row for it, and the marking
  station's Laser box says **no laser on USB** and disables Mark when the
  board is missing, instead of "ready".
- **The flashing bench offers the agent, not the setup profile.** The agent
  grants the Chrome serial and loopback policies itself on first start, so the
  `.mobileconfig` link on the bench is gone; the endpoint stays for machines
  with managed Chrome settings, where only an administrator can install it.
- **The agent's Chrome row knows about managed profiles.** A profile in
  `/Library/Managed Preferences` overrides the agent's own grant, so the row
  now says *granted by a managed profile* when one carries the grants, and
  names what a managed profile lacks when it does not — instead of reporting
  the agent's own write as if Chrome were reading it.
- **The two LightBurn profiles live in the repo** —
  `docs/reference/laser-marking/`, with the vendor calibration files and a
  script that writes them into a fresh LightBurn.
- **The agent refuses to switch LightBurn profiles mid-session.** LightBurn
  only connects the profile it started with; a switch answers `OK`, shows
  "Disconnected", and `STATUS` keeps saying `OK`, so the job would report
  success and mark nothing. The first `device` a job names is the session's
  profile; a job naming another fails before anything is loaded, with the
  instruction to restart LightBurn on that profile.

## 2026-09-17 (the marking bench prints labels)

**A device gets its barcode label from the same bench that engraves it**, off
the same reading of its serial, with no DYMO software on the machine. The
printer is a DYMO LabelWriter 550 on the bench agent's own machine, driven
through CUPS.

- **The marking station is now one box with two columns.** Left is the device:
  its serial, its port, and what the station is doing. Right is one box per
  machine — Laser and Printer — each with its own status above its own button.
  A laser that is not answering and a printer with no roll are fixed in
  different places, and one status pill sent the operator to the wrong one.
- **A chain between the two boxes links them.** With it on, one press of Mark
  engraves and then prints the label, so a bench that does both keeps the
  trigger instead of switching on two automatic passes. It refuses to start
  while the printer is not ready, rather than engraving a part it cannot label.
- **Automatic is two checkboxes, one per machine.** A bench can engrave all day
  and print nothing, or print while the laser is down. Each arms only when its
  own machine is ready.
- **Both buttons run the same procedure.** One marking version reads the device
  once and then engraves, prints, or both; which one a press asked for travels
  with the run. The engine allows that for those two actions only, so a bench
  cannot change what a unit was made under.
- **A `print_label` step IS the label definition** — a Code 128 barcode of the
  value with the value under it. Nothing is pinned to the version for it,
  because a generated label has no artwork. The roll is a station setting: the
  printer cannot report what is loaded in it.
- **A print is proven, not assumed, and it finishes when the label is out.**
  The bench waits for the printer to report that it printed the page and the
  backend to finish sending, with no fault standing. It deliberately does not
  wait for CUPS to retire the job, which takes a further seven seconds during
  which the printer does nothing — that turned a two-second step into nine. The
  printer's own progress now appears in the run log, and a failed print cancels
  its own job rather than leaving one queued: a waiting job resumes the moment
  the roll goes back in, which would print a stale serial onto the next unit.
- **The bench reads the device when you plug it in**, not when you press a
  button. The serial appears in the box straight away, so it can be checked
  against the part first, and the run leaves out the step whose only job was to
  wait for the firmware — 0.7-1.1 s off every press. The run still reads the
  identity itself, so nothing is taken on trust. Both buttons stay disabled
  until the device has answered, and the box says what it is waiting for.
- **A serial is checked before anything is put on a part**: 8 to 12 characters,
  no spaces, whether it was typed by hand or read off the device. The bench says
  which rule a value broke, and the engine refuses it too — a capture that went
  wrong used to reach the laser as whatever string it happened to produce.
- **A typed mark is no longer recorded**, and a typed label is not either. It
  names no run and proves nothing about a unit.
- The bench agent is at protocol 3. An older one has no printer routes, and the
  bench says to download it again.

Decision: [0022](docs/decisions/0022-labels-are-generated-by-the-bench-agent.md).
Measurements: [docs/reference/label-printing.md](docs/reference/label-printing.md).

## 2026-09-16 (marking is a run, and the laser is not ours to drive yet)

**The marking bench exists.** Plug a device into the laser machine and it is
read, patched into the artwork and engraved, with a run record and a log like
any flash. It is a separate page from the flashing bench: one laser, one
station, and it starts itself when a part arrives.

- **A marking procedure is an ordinary deployment version** with kind `mark` —
  its own steps, its own pinned artwork, the same publish gate. The `.lbrn2` is
  pinned as a device file exactly like berryware, so the run record answers
  which drawing a unit got. The new step is `mark_laser`.
- **The laser is reached through LightBurn and a small local agent**
  (`api/app/services/bench_agent/agent.py`), not a direct USB driver. The direct path
  was probed on the hardware and rejected on evidence: the BSL controller
  (`04b4:1004`) answers every EZCAD2 opcode with the same idle frame, so the
  open-source LMC drivers do not apply, and decoding its own protocol needs a
  USB capture that no machine here can take. Decision
  [0020](docs/decisions/0020-marking-goes-through-lightburn.md), measurements in
  [docs/reference/laser-marking.md](docs/reference/laser-marking.md).
- **The agent holds no token and never reads the artwork.** It receives a
  finished job and points LightBurn at it. It listens on loopback only and
  checks the Origin of every connection, because Chrome's local-network prompt
  is asked once and after that any page could reach it.
- **The bench profile now carries the loopback grant too**, so a configured
  bench never prompts for the agent connection.
- **A mark is operator-confirmed, not machine-proven.** LightBurn answers `OK`
  to `STATUS` and `START` with no laser attached, so neither proves a part was
  engraved. That stands until `STATUS` is seen reporting busy during a real job.
- **A deployment's kind can finally be SET.** It became readable when the bench
  learned to offer the right button, but nothing could write it — a marking
  deployment could not be created at all. `POST`/`PATCH` take it now, and the
  PATCH leaves it alone when omitted, so an edit form that does not send it
  cannot silently turn a test deployment back into a flashing one.
- **`mark.serial` is a named check**, in its own "marking" category: a unit can
  be fully working and unmarked, so it does not belong under hardware.
- **A bench station is bound to a USB socket at last.** Assign a socket once and
  the station takes that cable and no other, across replugs and reloads, with
  the real port name (`/dev/cu.usbserial-110`) on the card. Nothing is adopted
  automatically any more: an unassigned station stays empty however many devices
  are plugged in. Arrival order is gone — it handed station 1 whatever turned
  up, so moving a cable silently moved the station and nothing said so. The
  flashing bench now wants the agent running too; without it, assignment still
  works for the session but the station cannot remember its socket.
- **The agent can see the serial ports, which is what made that possible.**
  `GET /serial-ports` lists every USB serial node and, from `lsof`, which
  process holds each one. macOS names a node after the USB location, so the name
  IS the socket — and "who holds it" is the correlation a page cannot make on
  its own: open one port, ask the agent which node Chrome just took. Binding a
  station to a socket was documented as impossible from the page alone, and that
  is still true; what changed is that a process outside the page now exists. The
  bench does not use this yet — see `docs/todo.md`.
- **The download sets the browser up too, with no administrator rights.** On
  first start the agent grants this bench's origin the USB serial adapters and
  the loopback connection, merging with anything already there, and asks for
  Chrome to be restarted once. Chrome reads policy from the user's own defaults
  domain as well as from managed preferences, and only the second needs root —
  so one download now covers the whole setup. `--no-browser-setup` turns it off,
  and a machine carrying the bench profile is unaffected: a system profile
  outranks it.
- **A marking step names its laser SOURCE.** This marker carries two, a fibre
  and a blue, and LightBurn holds them as separate devices. `mark_laser` takes
  `device:`, and the agent sends `LASER:<name>` BEFORE loading the job, so a job
  cannot be fired from the other source. The agent also reports what the machine
  has, so nobody guesses the spelling — a wrong name is refused, not ignored.
  Needs LightBurn 2.0+; it answered `!` on 1.7.03.
- **The agent is a macOS app called 7Sigma Agent**, and it starts LightBurn for
  you. It ships as an app rather than a terminal
  command: a small window with the log, the laser's state and a Quit button.
  It is named for the bench, not for marking, because it will pick up the jobs
  a browser cannot do as they arrive — label printing next. On start it opens LightBurn if LightBurn is
  silent, waits for it to answer, and says plainly when it does not — naming the
  two causes that look identical, a dialog waiting for a click and a Core
  licence. The window is tkinter, so it still installs nothing; when no
  available Python has tkinter it says so and runs without a window instead of
  failing.
- **The marking agent is a download.** The bench offers a zip; expand it,
  double-click *7Sigma Agent*, done. The launcher carries that bench's
  own address, so there are no flags to type, and it is an archive rather than
  a bare file because a download loses the execute bit while a zip keeps it.
  Its source moved to `api/app/services/bench_agent/` for the same reason the
  KiCad plugin lives in the api package: the platform serves it, and `clients/`
  is not in the image.
- **The marking agent needs nothing installed.** It speaks plain HTTP from the
  standard library, so whatever Python 3 is already on the laser machine runs
  the file as it stands — verified on macOS's own 3.9.6 with no venv and no pip.
  It was a WebSocket for an afternoon; the one dependency that required was the
  only thing standing between an operator and a working bench.
- **If LightBurn stops answering, check its tier.** LightBurn *Core* cannot
  drive a galvo — EZCad2 and BSL controllers are Pro — and the symptom is not an
  error but silence: the UDP port stays open and every command is ignored. An
  upgrade put this bench on Core and cost an hour before the title bar was read.
- **A mark can be run by hand.** Type a serial, press Mark: no device in the
  loop, for a unit that is dead, uncased, or whose label was spoiled. Same
  template, same placeholder, same agent as a run — only the source of the
  string differs. It lands in the device's history like an erase does, but only
  when what was typed is an identity: 12 hex characters become the MAC, and
  anything else is engraved with the card saying plainly that it will not be
  recorded.
- **The marking station uses the width it has.** One laser means one station,
  so it is laid out in two columns across the page instead of reusing the
  narrow card that exists to fit four side by side, and it shows what was
  engraved in large mono — the operator checks that against the part, not
  against the log. Renaming it no longer renames flashing Station 1.

## 2026-09-16 (a device is proven by its newest run, not by its best one)

**"What this device is proven to do" counted the best result ever recorded per
check, so a unit whose newest attempt failed, aborted or was still running kept
a full green grid from an earlier pass.** That grid is the answer to "is this
unit programmed", and it said yes about units that were not.

- **The device grid now shows the NEWEST run only.** A green cell means that
  run measured it and it passed. Nothing survives a later attempt. The lifetime
  tally stays on the cell hover (`attempts: 3× pass`), so earlier evidence is
  not lost, only demoted.
- **The card states the verdict**: `programmed` or `not programmed`, with the
  run that decided it. A run that is still going, a run that failed or aborted,
  and an erase all read `not programmed` — an erase records `pass`, because the
  erase worked, and that is not the same as a programmed device.
- **The Devices list agrees** wherever it reports a check, because it counts
  the same newest run.
- **PASS and FAIL are no longer the same grey.** The Result column took its
  colour from `STATUS_TONES`, which had no entry for a run's own words, so the
  one column you scan down a 5427-row list said nothing at a glance. Pass is
  green, fail is red, aborted is amber, everywhere a run status is printed.
- **One device is one row, and nothing in it is cut.** The device list carried
  twelve columns in a table that is 1050 px wide on a laptop, so most of them
  were ellipses. Four are gone: **Name** (the serial with a `dongle_` prefix,
  and the search box still matches it), **Project** (the selector above the
  table), **IMEI** (blank on every unit without a modem) and **Checks** (it
  said `4/4` beside a Result that already said PASS — what a run proved lives
  on the device page). What is left — serial, MAC, chip, batch, where it is,
  runs, result, last seen — prints whole from 1100 px up. Column widths on the
  device list and the programming history were re-cut from measured content.
- **A run's duration reads in minutes** above a minute: `3m 24s`, not
  `204.3 s`.
- **"Programmed" now means what the batch asked for** — see
  [decision 0021](docs/decisions/0021-a-device-is-judged-by-the-rule-it-was-made-under.md).
  A device's history holds programming runs, test sweeps, marking jobs and
  erases, and they do not all say the same thing about the unit. The verdict
  reads: the newest **config** run passed, any **test** that started after it
  passed, and no **erase** since. **Marking never changes it.** A test that ran
  and failed always counts, even when the batch asked for none; a test that did
  not run counts only where it was required.
- **A batch carries the test requirement, and every run keeps a copy.** "Units
  of this batch must pass the test" sits on the batch (Devices tab of a
  production run) and is copied onto each programming run when it starts, so
  changing it affects work still to be made and never re-judges a device on the
  shelf. A test deployment's flag in the Deployments tab is now only the
  default ticked on a new batch. **The migration lands with no test required
  anywhere** — every existing batch and run says false, and every test
  deployment starts off, so a deploy changes nothing about devices already
  made. Turn a product's test on when its flow is ready: the Deployments tab
  for new batches, the batch's own Devices tab for one batch. Measured with
  nothing required: of 990 Aqua devices 914 read programmed, and the 76 that do
  not are the ones whose newest test actually failed.
- **The device page fits on one screen.** "Where it is" took half the right
  column whatever it held — four event rows and a button — so the programming
  history started below the fold. It now takes what it needs and the history
  gets the rest. The history's own columns were re-measured at the same time:
  the start time can no longer be cut, and `By` (which now carries a real
  account name) truncates with the full name on hover.
- **A device page no longer prints fields the product does not have.** A
  Dongle_V2 has no modem, so IMEI, ICCID, IMSI, Modem and Modem firmware were
  five dashes on every one of 4400 units. A row is drawn when the device
  carries the value, when one of the project's procedures captures it, or when
  any sibling device in the project has it — so a Dongle_V3 still shows its SIM
  rows before the first unit is programmed, and imported history stays readable
  after the procedure that produced it is gone. The page holds no list of
  fields at all: the server sends the rows with their labels, so a new
  identity field appears without touching the frontend.
- **The configuration card shows what is on the device now**, written by the
  last run to configure it, instead of every value it ever carried — one device
  printed twelve rows of the same three keys. Earlier values are kept and stay
  reachable through their own run.
- **The flash bench can program on plug-in.** "Program automatically when a
  device is plugged in" arms every station: the run starts the moment a device
  appears on that station's port, so a tray of dongles is plug, wait, unplug.
  It is **off by default and remembered per browser once you turn it on**,
  because a programming run erases the device before it writes — the marking
  bench, which does nothing destructive, keeps arriving armed. Each station
  arms ONCE per device: a unit left plugged in after its run is not programmed
  again, and a unit that failed does not retry in a loop — pull it out and the
  station re-arms. The box is disabled until a batch is picked, so auto-start
  can never turn a batch run into a bench trial.
- **The bench opens ready to work, and never on a batch you did not pick.**
  Choosing a project now fills the version box with that project's config
  procedure (its `kind: "flash"` deployment, current version), which is what a
  batch is programmed with all day and was a click at the start of every
  session. The batch dropdown is the opposite: it starts empty every time,
  is never remembered across a reload, and until it is picked the stations
  refuse to start — a batch run with no batch used to be recorded as a bench
  trial. The override-reason box now appears only when the chosen version
  really differs from the one the batch is assigned.
- **The bench asks only for what the procedure uses.** The SIM PIN box appears
  only for a procedure that has an `lte_sim_pin` step — Dongle_V3 today. A
  Dongle_V2 and an Aqua have no modem, and the box was asking for a secret
  that had nowhere to go. A hidden box also stops sending its value.
- **The operator text box is gone; a run is stamped with the signed-in
  account.** `operator` was never device configuration — no procedure in the
  library uses it — it is the record of who was at the bench: the By column in
  a device's history, the actor on the `produced` stock event, and the audit
  line when somebody overrides a batch's assigned version. A name somebody
  types is not that record. The API no longer accepts an `operator` field on a
  run or an erase.
- **A serial is never cut.** It is the MAC without separators — always 12
  characters — and a truncated serial is not an identity. That column, and the
  last-seen timestamp beside it, are now sized in pixels rather than as a share
  of the window, so they hold their full value at any window width. Checked
  from 900 to 1920 px.

## 2026-09-16 (a board that cannot reset itself can still be programmed)

**One V2 dongle would neither erase nor program from the bench, and chasing it
found three separate faults — two of them ours.** Unit `20:e7:c8:92:b6:10`
resets but never enters download mode: EN responds, IO0 does not. Five reset
sequences driven by hand all ended in flash boot, and `esptool.py` from a
terminal failed identically, which ruled the bench out early.

- **Connecting is now a ladder that escalates by itself**: `default_reset` at
  the profile's baud, then at 115200, then `no_reset` after the bench pulses EN
  with the operator holding BOOT. A healthy unit still connects on the first
  rung in two seconds; a faulty one is asked for instead of failed. The third
  rung exists because esptool-js runs 7 resets per connect, and on a board whose
  IO0 is not driven every one of those undoes the download mode the operator
  just established — **more attempts made it worse**.
- **The rung that worked is recorded** as `connect_mode` in the run's results.
  A unit that only answers with BOOT held has a hardware fault, and quietly
  rescuing it on every run is how that stays invisible until a batch fails.
- **The fast baud is now a preference, not a requirement.** esptool-js changes
  speed by closing and reopening the serial port, which toggles DTR/RTS; on a
  board that resets from that, the stub dies and the next command reads
  `Invalid head of packet`. Any failure at 460800 now retries at 115200, where
  esptool-js skips the baud change completely. Erase uses 115200 outright.
- **Holding BOOT no longer costs the fast baud.** The BOOT rung ran at 115200,
  which turned a 2.3 MB image into minutes for every unit that needed a hand.
  Needing BOOT held and refusing 460800 are two different faults; the rung now
  starts at the profile's baud and drops to 115200 only when esptool reached
  `Changing baudrate` — the one failure that holding BOOT cannot fix.
- **An erase now enters the device's history once it has read a MAC.** A
  `programming_runs` row with `action = "erase"` and no deployment version,
  plus its log. A failed erase used to leave nothing behind, which is how a
  troublesome unit stays invisible until the next batch.
- **An open log no longer drags the page.** Each new line scrolled every
  ancestor, so reading anything else on the bench was impossible while a run
  was talking. The log box scrolls on its own now, and only while the operator
  is already at the bottom of it.
- **Errors carry advice.** A connect failure suggests holding BOOT and says what
  it would prove; a mid-operation timeout points at the cable or socket.

## 2026-09-16 (a replugged device needs no new port grant)

**Swapping one device for the next broke the bench.** After a successful run,
unplugging the device and plugging it back in made the next run fail with
"Failed to execute 'open' on 'SerialPort': Failed to open serial port", and the
only way out was re-picking the port in Chrome's popup.

- **The cause is that the PERMISSION does not survive the unplug**, not just
  the handle. Measured from the run log: after a replug `getPorts()` returns
  **zero** ports and `port.connected` on the held handle is `false`. A CH340
  reports no USB serial number, so Chrome cannot durably identify the device
  and drops the grant with it. Nothing in the page can recover that — there is
  no port to re-acquire, and only a fresh `requestPort()` popup would bring one
  back.
- **The bench now asks for the port inside the Start click**, and only when it
  has no live one. That is the baseline everywhere the platform is not the
  machine's owner: one pick per unit, which Web Serial gives no way around for a
  device with no serial number. `ensurePort()` runs before the run row is
  created, because `requestPort()` needs a user gesture and a gesture does not
  survive a fetch.
- **The bench page now offers a one-time setup file.** `GET
  /api/flasher/bench-policy.mobileconfig` builds a macOS configuration profile
  for the origin the browser reports, and a link at the bottom of the bench
  offers it. The operator downloads and opens it once per machine; after that
  the picker is gone. It grants only the listed USB bridges, never "any serial
  port" — this file goes to people on machines nobody here administers. macOS
  only so far.
- **The same policy can be set by hand on a bench somebody owns, and on a
  dev Mac it needs no root** —
  the user-level `com.google.Chrome` domain is honoured. This machine already
  had `SerialAllowAllPortsForUrls` live for `http://127.0.0.1:5174` from an
  older setup, which is what proved the mechanism. It never covered the bench,
  because policy origins are exact: `localhost` and `127.0.0.1` differ, and so
  do two ports. `scripts/bench-serial-policy.plist` documents both that route
  and the narrower `SerialAllowUsbDevicesForUrls` form for a provisioned bench.
  A device that DOES report a serial number, such as the C6's native USB, never
  had this problem — which is why V3 benches never saw it.
- **`Station.resolvePort()` then picks the port up automatically.** Liveness
  comes from `port.connected`; membership of `getPorts()` is not a liveness
  signal, because the spec hands back the same instance for a device across a
  disconnect. Every open path calls it first, including each retry.
- **`settlePort()` closes a half-open port before opening it.** Chrome can be
  left believing a port is open while the OS descriptor is already gone.
- **A failed `port.close()` is no longer silent.** It leaves the port open, and
  the next open then fails with a message that explains nothing.
- **A station never takes a port another station holds.** Re-acquiring by USB
  ids alone is not safe on this bench: every V2 dongle is the same CH340 and
  every C6 the same native USB device, so one slot could have matched, and then
  tried to open, the port another slot was mid-run on. A claim registry makes a
  station skip a port that is spoken for — which also closes the same hole in
  `awaitReenumerate()`, where it predates this change.
- **The transport profiles are untouched.** Which one applies is still pinned by
  the deployment version, and the C6 rule that the monitor phase never drives
  DTR/RTS is unchanged.

## 2026-09-16 (the bench tells the platform its own address)

**`{base_url}` now resolves from the bench, so a step never needs to know where
the platform runs.** Step 18 of every V2 procedure makes the DEVICE fetch its
berryware over HTTP, and the address it fetched from was a single global,
`public_base_url`. That value is correct on the server and wrong on every
development machine, where it is `localhost` — an address a device on WiFi can
never reach. The engine refused the run and told the operator to edit a setting.

- **The browser reports the two addresses it is provably reaching the platform
  by** (`api_base`, the API origin it calls, and `page_base`, the mount point
  the bench page itself was opened by) in its `hello`. The engine takes the
  first usable candidate in this order: the `base_url` param, `public_base_url`,
  the bench API origin, the bench page origin. The run log records which source
  won and why each skipped candidate was rejected.
- **Configuration outranks the bench, deliberately.** The winner is an address
  the engine then tells a device to fetch from, so a value the browser merely
  asserts is used only where the platform has no usable one of its own. **In
  production `public_base_url` is reachable, wins, and the bench candidates are
  never weighed** — the behaviour there is exactly what it was. Every candidate
  is vetted the same way: http(s), a host, no embedded credentials, not
  loopback.
- **On a development machine, opening the bench by the machine's LAN address is
  now the whole configuration.** `compose.yaml` drops `VITE_API_URL` and sets
  `VITE_API_PROXY`, so dev is same-origin through the Vite proxy the way the
  deployed image is through nginx — no CORS entry, no second origin — and
  publishes port 5173 on every interface, because a device being programmed
  fetches its berryware from it over WiFi.
- **Any op that makes the device fetch something takes a `url` template.**
  `download_files` is the first: leave it empty for the default,
  `{base_url}/api/flasher/files/{file_version_id}/{filename}`. The template goes
  through one resolver (`RunEngine._url`), so `{base_url}` means the same thing
  in every op, and the procedure editor shows the field on the step.
**`flash_config.size: "detect"` could never flash from the browser bench, and
every V2 deployment version carries it.** Found on the first V2 hardware run,
which erased the device and then refused the image with "File 1 doesn't fit in
the available flash".

- **esptool-js accepts `"detect"` in one place only** — the image-header
  rewrite, which detects the size itself. Its fit check passes the literal
  string to `flashSizeBytes()`, which looks for "KB" or "MB", finds neither,
  returns -1, and refuses every image. The V2 procedures were reconstructed
  from a Python esptool, where `--flash_size detect` is valid. `Station.espFlash`
  now resolves the value before esptool-js sees it, so the chip's real size
  reaches both the fit check and the header.
- **The erase runs first, so the failure left the device blank.** That is why
  this is gated at publish now: `validate.check()` refuses a flash size, mode or
  frequency outside the values esptool-js declares, rather than letting the run
  die in the browser with the device already wiped.

- **Publishing refuses a template that hardcodes a loopback host.** It is not a
  value that might work — it is one that cannot, so it is an error rather than a
  warning. Every existing published version validates unchanged.

## 2026-09-14 (`_HandSoldering` and `_Soldering` are retired)

**The house mints no hand-solder token** (user decision 2026-09-14). Not
`_HandSoldering`, not `_HandSolder`, not `_Soldering`.

- **One footprint carried one**, and it is renamed:
  `Pin_D0.7mm_Pad1.4mm_Soldering` → **`Pin_D0.7mm_Pad1.4mm`**. The token said
  nothing the name did not — it is a single thru-hole pad and `Pad1.4mm` was
  already in the name. Renamed through `services/rename.py`, so the one
  component on it (`Pin_0.7mm_Soldering_Pin`) was republished with its
  verification carried, the `.kicad_mod` moved in the mirror and the Connectors
  library rebuilt.
- **`fp.name_spellings` no longer looks for the token.** Its pattern drops the
  `_HandSolder` / `_Handsoldering` clauses and keeps the rotation ban, which is
  the rest of what it always did. All 213 footprints pass.
- **Nothing BANS the token, and that is deliberate.** KiCad ships **194**
  footprints whose filename ends in `_HandSolder`, and a Tier 0 adoption keeps a
  stock filename character for character. A ban would collide with that freeze
  the moment one of those lands is adopted. What changed is that the house does
  not mint one — a tier question, not a spelling rule.

**The naming standard contradicted itself on this, which is the best argument
for dropping it.** `docs/footprint-naming/01-standard.md` pinned `HandSolder` as
"the house spelling — never `HandSoldering`" in §3.8, while D2 in the same
document pinned `_HandSoldering` and said `_HandSolder` is "never minted here".
The stock library splits 108 / 86 / 28 across three spellings, and KLC F2.1
rule 10 disagrees with KLC F3.3's own example. D2 is superseded, §3.8 drops
`HandSolder` from the option vocabulary, and the claim that the house "pins one
answer" no longer lists it.

Footprint checklist **v29**; `conventions-footprints` **v45**. Also updated:
`docs/footprint-naming/README.md` and `05-sources.md`.

## 2026-09-14 (the checklist audit, and a sanitizer on publish)

An audit of every judgment check — asked of how many subjects, answered how
many times — drove three changes. Machine checks were excluded from the count:
conformance is computed, not recorded, so a zero there means nothing.

**`sym.fp_filters` is retired** (severity `ignore`). Asked of 194 symbols,
answered **2** times. `ki_fp_filters` filters the footprint chooser and nothing
else, and every curated path already carries the footprint: the HTTP catalog
does not send the field at all, and a generated component symbol has `Footprint`
set. Not one of its 16 findings could reach a board.

**`fp.naming` asks the rename decision and nothing else.** Its text claimed the
twelve-slot order, which is `fp.field_order`'s job, so the name was covered
twice and a reviewer could not tell the two rows apart. The name is already
fully covered by `fp.tier`, `fp.field_order`, `fp.name_charset` and
`fp.name_spellings`; what is left here is the two reasons that justify a rename
and the rule that "ugly" is not one. The 292 existing `checked` answers are
kept: the hint they were read against was already the rename policy — the text
was the part that disagreed with it.

**Six glyph checks became one measurement — `sym.family_drawing`.**
`sym.triangle_body`, `sym.gate_body`, `sym.triangle_pins`, `sym.input_marks`,
`sym.rail_polarity` and `sym.rail_marks_not_names` all compared a drawing
against coordinates the hints quote to the 0.01 mm, and between them had been
answered **zero times in the library's history**. A coordinate comparison is not
a judgement. The new fact `$symbol_family_drawing_off` counts body vertices, pin
positions and polarity marks that are off the house table. Result: **10 checked,
1 na**, no findings — it is a regression guard, and the ten are exactly the
parts the hints name as precedent.

Two false positives the dry run caught before it shipped, both mine:

- **The angled-leader slot was missing from the gate table.** `74LVC1G125`
  (`~{OE}`) and `74LVC1G17` (`NC`) put a spare pin at (5.08, −5.08) with a short
  leader drawn to it — which is what `sym.angled_leader` describes. Both read as
  defects until the slot was added.
- **A multi-input gate has no documented geometry.** `SN74HC21`, a dual 4-input
  AND, measured **15 elements off** against the one-input table. It is drawn as
  the IEC body with an `&`, and the house has never written its numbers down. So
  the fact is now ABSENT there rather than inventing a rule — `sym.drawing_family`
  owns the undocumented case.

What needs the datasheet stays judgment: which rail is actually negative
(`sym.rail_negative_mark`), which input the datasheet calls inverting
(`sym.inverting_on_top`), and comparator vs amplifier (`sym.comparator_glyph`).

### A publish sanitizes before it parses

`sanitize_footprint` / `sanitize_symbol` correct derivable metadata on every
publish, through every door. Full rules in `api/app/services/CLAUDE.md`; the
short form is that a rule may only touch what the material fingerprint excludes,
and only where the correct value is derivable rather than guessed.

| Rule | Corrects today |
|---|---|
| A footprint's hidden `Value` takes the footprint's own name | **74** of 213 |
| `ki_fp_filters` is removed from a symbol | **149** of 207 |
| A `Footprint` default that is not `7Sigma:` is emptied | 9 |

- **Idempotent, and verified across all 420 drawings.** It runs before the
  `force=False` no-op comparison — sanitize afterwards and every KiCad re-save
  would mint a version. A re-publish of sanitized text still returns
  `unchanged: True`.
- **Non-material, and verified across all 420 drawings**: not one material
  fingerprint changes and not one drawing stops parsing.
- **Reported** on every return path, in `sanitized`.
- `ki_fp_filters` is deleted outright because **no component carries its own**.
  A `Footprint` default is **emptied, not deleted** — that one is displayed, and
  every component inherits its position and effects from the base symbol. Same
  trap `LCSC Part` taught this morning.

Checklists: symbol **v33**, footprint **v28**. `conventions-symbols` **v22**,
`conventions-footprints` **v44**. Conformance recomputed across 862 subjects, no
validator errors; symbol findings 77 → 62.

## 2026-09-14 (`sym.pin_numbers_unchanged` is automatic)

**"No pin numbers changed since the previous version"** is now a machine check.
The new fact `$symbol_pins_changed` diffs this version's pins against the
previous version's and counts numbers **added, removed, or moved to a different
unit**.

As a human question it was not working: answered **twice** in the whole library,
and asked of **71 symbols that have no previous version**, where the only honest
answer is "does not apply" and the hint never said so. Comparing two sets of
`(number, unit)` pairs is what a machine does better than a person reading a
diff.

- **A first version answers `na`.** The fact is ABSENT rather than `0` — "nothing
  has been compared" is not the statement "nothing changed".
- **Unit 0 is not a unit**, it means "common to every unit". Moving a shared
  power pin out of it makes that pin appear on unit A alone, so it counts.
- **A duplicated number is not a change.** Stacked power pins share one number,
  so the fact compares the SET of units each number sits in.
- The fact lives beside `$symbol_sim_link` rather than in `_symbol_providers`,
  because it is the one symbol fact that needs more than the source text — the
  predecessor has to be fetched — and the one that is about a CHANGE rather than
  a state, which is why it has no meaning on the component page.

Result across 207 symbols: **71 na, 132 checked, 4 findings.** No validator
errors. Every finding is a real unit reassignment, hand-checked:

| Symbol | | What moved |
|---|---|---|
| `KSZ8864CNX` v2 | 40 pins | Deliberate: split into 5 units, one per block |
| `TLV7022` v3 | 3 pins | Deliberate: one 8-pin box → two comparator units |
| `74LVC2G34` v3 | 2 pins | Deliberate: one 6-pin box → two buffer units |
| `SN74HC21` v4 | 2 pins | **Pins 7 and 14 moved out of unit 0 into unit 1** — the shared power pins now appear on unit A alone. The version comment reads "Edited in the KiCad footprint editor" and says nothing about it. |

The three deliberate re-splits need an answer or a standing exception; the
`SN74HC21` one looks unintended and is worth a look. The hint says what to do in
either case.

- `conventions-symbols` **v21**; symbol checklist **v31**.

## 2026-09-14 (19 base symbols stop carrying a part number)

**`sym.sourcing_defaults` passes on all 207 symbols.** Every base symbol that
stored an `LCSC Part` value now stores an empty one.

- **The value is emptied, the key is kept** — and the key is not decoration.
  `generator.schematic_field_visibility` reads the base symbol for each field's
  POSITION and EFFECTS, and every component that has its own value inherits
  them. Deleting the property drops each component's own field to `(at 0 0 0)`
  with the default font: a diff on every generated symbol for no gain. Emptying
  the value changes **nothing** — proven by generating each affected component's
  symbol both ways and diffing: **0 of 19 differ**.
- **This is already the house pattern.** 16 base symbols carried an empty
  `LCSC Part` before today; these 19 now match them.
- **Published as minor changes, so verification carried** — 19 `carry` records,
  "nothing that reaches the board changed", none lost. Mirror rebuilt: 16 symbol
  libraries, 442 components, 213 footprints, 0 warnings.

| | |
|---|---|
| Symbols fixed | `AP6335XQ` `BSC0702LS` `CH340B` `Conn_01x06` `Conn_01x22` `DF40C-100DS` `ESP32-C6` `FPC-05F-24PH20` `HU2032-LF` `LM2594M-XX` `NCP115ASN` `STM32C071G8U6` `STM32G031G8U6` `TLV62585DRLR` `TPS62826DMQR` `TPS6302X` `USB-B01` `WS2816C-1313/4P` `ZED-F9P` |
| Components affected | 0 — each already carried its own identical code |

- **The hint gave the wrong fix and is rewritten.** It said "Fix by REMOVING the
  property from the symbol", which is the change that moves every component's
  field. It now says to empty the value, shows the edit, and explains why the
  key stays. Symbol checklist **v30**.

## 2026-09-14 (a warning says warning)

- **A warning-level failure said `failed (machine)` and `warning only` on the
  same row**, which reads as a contradiction and was reported as a broken check
  (user report 2026-09-14). The row now says **`warning`**.
- `result` and `severity` are two axes
  ([decision 0016](docs/decisions/0016-severity-and-standing-exceptions.md)):
  the rule IS broken, and the breakage does not fail the part —
  `state_from_record` gives such a subject `checked` with `warnings: 1`. Only
  the word shown changes. The stored `result` is untouched, and the row's
  `title` still names it, so nothing is hidden from somebody who looks.
- The now-redundant "warning only" badge is gone.

## 2026-09-14 (a check that must find none says so)

- **"The count of sourcing defaults stored on the drawing is at most 0" reads
  as a broken rule, not a rule** (user report 2026-09-14). `at_most 0` is not a
  threshold — it is "there must be none", and it is the shape **14 of the 15**
  `at_most` checks take. Every counting fact's `noun` starts "count of", so
  dropping those two words leaves the sentence already written:

  | was | now |
  |---|---|
  | The count of silk lines crossing pad copper is at most 0 | No silk lines crossing pad copper |
  | The count of thermal vias outside their own pad is at most 0 | No thermal vias outside their own pad |
  | The count of sourcing defaults stored on the drawing is at most 0 | No sourcing defaults stored on the drawing |

- **The failure note was worse than the rule**, because it named the fact:
  `$symbol_sourcing_defaults is 1, not at most 0`. Notes now use the same noun
  the rule does — `_fact_noun` is shared by `describe_assert` and
  `evaluate_assert`, so the two can never name one quantity two ways. A
  must-find-none failure reports what was found: **"1 found: sourcing defaults
  stored on the drawing"**.
- **Two facts carried their own negative**, which the new phrasing doubled up.
  `$footprint_zero_annulus_pads` is now "plated holes whose copper is no wider
  than the drill" and `$pins_without_pads` is "symbol pins the footprint has no
  pad for" — read as "No plated holes with no annular ring" before.
- **A stale text on `cmp.value_field` surfaced and is corrected.** All six
  variants stored *"Value is the component's own name"*, which is the rule for
  exactly one of them: a TVS showed that sentence while the check tested
  `^[0-9]+(\.[0-9]+)?V…$`. Regenerating from each variant's own `assert` fixed
  it — the drift [decision 0014](docs/decisions/0014-a-check-carries-its-own-configuration.md)
  exists to prevent.
- Checklists: component **v27**, symbol **v29**, footprint **v27**. Machine
  answers recomputed across 862 subjects, no validator errors.

### `sym.sourcing_defaults` is correct, and 19 symbols trip it

Verified against the ESP32-C6 base symbol behind
`VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias`: the drawing carries
`(property "LCSC Part" "C5364646")`. `generator.apply_properties` starts from
`{p.key: p.value for p in symbol.properties}` and lets the component override,
so a base-symbol default that a component does not override ships to KiCad on
that component.

**Nothing is broken today** — each of the 18 symbols with a component is
overridden by that component's own identical code, and `WS2816C-1313/4P` has no
component yet. It is a latent defect, which is what `warning` says. The ones
that will actually be reused are the templates: `Conn_01x06`, `Conn_01x22`,
`DF40C-100DS`, `FPC-05F-24PH20`, `LM2594M-XX` and `TPS6302X` — the last two are
named for families, and the next part built on either inherits one specific
orderable code.

## 2026-09-14 (a standing decision sits on the check it excuses)

- **The exception moved onto its item's row** (user request 2026-09-14). It used
  to render in a block of its own above the checklist, so the reason a check was
  quiet — and the only button that withdraws it — sat several rows from the
  check, under a bare key (`fp.npth_mechanical`) that reads as nothing. The row
  now carries the `exception · this part, always` pill beside its state, the
  reason beneath it, and `Revoke exception` in the row's own button row.
- **Linked by `answered.exception_id`, not by key**, because an exception
  carries a `variant` and a waiver on the NMOS rule must not excuse the PNP one.
- **An exception with no row keeps a block of its own.** Its check can be scoped
  out, switched off, or dropped from the checklist since the decision was made,
  and a stale one has stopped closing its item — without that fallback it would
  become impossible to withdraw.

## 2026-09-14 (the third place is gone)

**A shared land records its other package names in `tags` and `descr`, and
nowhere else.** The hidden `Equivalent Packages` property is removed (user
decision 2026-09-14, after asking why only 1 of 213 footprints carried one).

Why it never earned its place:

- **Nothing read it.** KiCad's footprint chooser searches the name, `descr` and
  `tags` — not arbitrary properties. In the shipped KiCad 10.0.5 library, 15,462
  footprints use five property names between them (`Reference`, `Value`,
  `KiLib_Generator`, `Description`, `Datasheet`); a custom one appears **twice**.
- **One reader in the whole platform**: `jaravis._footprint_aliases`, feeding
  `list_footprints`. Nothing in the web UI or the mirror touched it.
- **Writing one was expensive.** The property lives in `source_text`, so editing
  it mints a footprint version and publishes a new component version for every
  part on that land — for a metadata note. (Verification and sign-off do carry:
  `services/material.py` excludes `descr`, `tags` and `property` fields from the
  material fingerprint.)

What changed:

- `fp.shared_land_record` is now **"Other vendor names for this same land are
  listed in tags and descr"**, and the hint says why those two and no third:
  they are the only fields KiCad itself searches. It also says not to
  reintroduce a property for this.
- `list_footprints(query)` matches the name, `tags` and `descr`. `matched_on`
  still says which field answered.
- `QFN-16-1EP_3x3mm_P0.5mm_EP1.7x1.7mm_ThermalVias` — the only footprint that
  had one — lost the property. Every designation and vendor code it carried is
  in `tags` and `descr`; its `descr` now reads "…QFN, VQFN, WQFN (TI RGT and
  RTE), LFCSP (ADI CP-16-22), JEDEC MO-220 VGGD." Published as a minor change,
  so the five components on the land (`PCF8574RGTR`, `ADA4945-1ACPZ-R7`,
  `74HC123LQ/TR`, `74HC138LQ/TR`, `TPS65135RTER`) were repointed with their
  verification intact.
- **Two retired lands lost a dangling pointer.** `LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm_ThermalVias` and
  `WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm_ThermalVias` both said "see its
  Equivalent Packages property" in their `descr`. They now point at the
  survivor's `tags` and `descr`. No components on either, so nothing moved.
- Footprint base checklist **v26**; `conventions-footprints` **v43**.

The measured deltas the property carried are preserved here, because this is
now their only record:

> VQFN-16 3x3 P0.5 (TI RGT, PCF8574RGTR on this land since import) ; WQFN-16
> 3x3 P0.5 (TI RTE, TPS65135RTER on this land since import; KiCad stock
> WQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm from ti.com tlv9064 p.44 draws pads
> 0.835x0.25 at +/-1.4575 and EP 1.68: 0.005 mm centre, 0.01 mm length, 0.02 mm
> EP from this land) ; LFCSP-16 3x3 P0.5 (ADI CP-16-22, ADA4945-1ACPZ-R7
> repointed 2026-09-07; KiCad stock LFCSP-16-1EP_3x3mm_P0.5mm_EP1.6x1.6mm from
> analog.com CP_16_22.pdf draws pads 0.875x0.25 at +/-1.4375 and EP 1.6:
> 0.025 mm centre, 0.05 mm length, 0.1 mm EP from this land) ; JEDEC MO-220 VGGD

## 2026-09-14 (`fp.tier` says one thing, and the second thing got its own check)

- **"The name follows the right rule for this package, and a KiCad name means
  identical copper" asked two questions in one**, so CHECKED could not mean one
  thing (user report 2026-09-14). The naming half keeps the key: *"The name
  follows the first of the four naming rules that applies"*.
- **The anti-shadowing half became `fp.stock_name_diffed`** — *"A name copied
  from KiCad's own library sits on copper identical to KiCad's"*. DOES NOT APPLY
  on any footprint whose name is not a stock filename, which the hint says
  outright, and which is **110 of 213** footprints.
- **The hint is written for somebody VERIFYING a name, not authoring one.** The
  old one was a naming procedure, so a reader holding a finished footprint had
  to invert every step. It now says: work the four questions yourself, see which
  rule you land on, then ask whether the name came from that rule. It names the
  common miss — question 3 answered with a bare package designation while our
  copper deviates from generic, which needs the vendor in front.
- **`fp.stock_name_diffed` carries the command that answers it.** The shipped
  library is on disk, so the hint gives the `find` over
  `KiCad.app/Contents/SharedSupport/footprints`. No hit means the name is not a
  stock name, which is DOES NOT APPLY.
- Footprint base checklist **v25**; `conventions-footprints` **v42**.

### What the new check is worth: 103 of 213 names ARE stock filenames

Diffed against the KiCad 10.0.5 library installed on this machine — pad numbers,
positions and sizes. **43 of the 103 differ from stock.** Most are the
house-prepared families the skill already declares deliberate (the chip
passives, the SOIC and SOT lands), where the difference is the point. Four are
not, and are the case this check exists for:

| Footprint | Ours | KiCad stock |
|---|---|---|
| `ublox_ZED` | 102 numbered pads | **55** |
| `VSON-8_3.3x3.3mm_P0.65mm_NexFET` | numbers 1–10 | 6 distinct, no 6–9 |
| `DFN-8-1EP_3x2mm_P0.5mm_EP1.36x1.46mm` | no pad numbered 9 | exposed pad **is** 9 |
| `Osram_BPW34S-SMD` | 2 pads | 3, one unnumbered |

A name that matches KiCad's while the numbering does not is the silent failure:
the symbol's pins map to the wrong pads and nothing warns. These are reported,
not changed — a rename repoints every component on the footprint.

## 2026-09-14 (`fp.shared_land_record` says what it means)

- **"Every package designation this land serves is recorded in all three
  places" never said which three places.** The reader had to open the hint to
  learn what the item even asked. The text now names them: *"Other vendor names
  for this same land are listed in tags, descr and Equivalent Packages"* (user
  report 2026-09-14).
- **The hint states when the answer is DOES NOT APPLY**, which it is for most
  footprints. The old hint said a land serving one package "is trivially yes",
  so the same fact could be recorded as `checked` or as `na` depending on who
  read it. The rule is now explicit: one name = does not apply, several names
  all written down = checked, a name missing = flagged, and say which name and
  which field.
- **It also explains WHY the item exists**, with the case that motivates it:
  one 3x3 mm 16-lead land is QFN-16, VQFN-16, LFCSP-16 and RTE to four vendors.
  KiCad has no footprint alias, so a name nobody wrote down is a name the next
  person cannot search — and they draw a second copy of copper we already have.
- **Still asked of every footprint, still a warning.** Nothing in the file says
  whether a land serves more than one name, so the question cannot be scoped
  away — the same reason `fp.thermal_vias` is not scoped on `pad_prop_heatsink`.
- **The procedure for retiring a duplicate land moved to
  `fp.one_land_per_package`**, which is the item about duplicates. Its hint
  already said "the two have to be merged deliberately" and stopped there; it
  now carries the merge steps, because a delete is refused while any historical
  component version still pins the loser.
- Footprint base checklist **v24**; `conventions-footprints` **v41**, where two
  index rows had fallen behind the checks they point at.
- **A long hint no longer runs off the bottom of the window.** The ⓘ tip asked
  whether 160 px fitted below the marker, which is true almost everywhere, so a
  45-line hint opened downwards and lost two thirds of itself past the edge with
  no scrollbar to get it back. It now opens to whichever side has more room, is
  capped to that room, and scrolls.

## 2026-09-14 (two checks became automatic)

- **`fp.thermal_vias` is a machine check.** "Thermal vias share the exposed
  pad's number and sit inside it" is geometry, and the new fact
  `$footprint_vias_outside_ep` measures it: a through-hole pad carrying an smd
  pad's number whose copper is not wholly inside that land. **Two footprints
  fail** — `TexasInstruments_VSON-14-1EP_4x3mm_P0.5mm_ThermalVias` and
  `SON-12-1EP_2.5x4mm_P0.4mm_ThermalVias`, four vias each. On the SON-12 the
  land is 1.0 x 1.0 mm and four vias reach y = ±1.2: they stitch the heat path
  to nothing. `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias` passes and is
  the reference.
  - **Scoped on the vias, not on `pad_prop_heatsink`.** Both failing footprints
    have no heatsink property either, so scoping on it made the check blind to
    exactly the parts that got the construction wrong. A check must not need
    the thing it is looking for to be declared correctly.
  - The five companion changes — paste stripped from the EP, windowed
    apertures, the back-side land, `zone_connect 2`, the name suffix — stay in
    the hint and are NOT measured. The hint says so.
- **`fp.silk_clear` split in two.** The silk-over-copper half is now automatic
  (`$footprint_silk_over_pads`) and finds **3 footprints**: a fuse holder, an
  RJ45 and a nanoSIM socket, where a silk line runs straight through pad
  copper. Ink between a pad and its solder is a contaminated joint and the
  assembler's optical inspection reads it as one.
  - **What it does not see is stated in the hint**: straight edges only, so 0
    means no STRAIGHT silk crosses copper. An arc is not tested.
  - The other half became **`fp.pin1_placed`** — is the mark against the pad
    the DATASHEET calls pin 1, and can somebody placing the part see it. That
    is the part no machine can judge; `fp.pin1_mark` already counts the
    Cmts.User circle mechanically.

## 2026-09-14 (navigation) — a reload puts you back where you were

- **Scroll position survives a reload and back/forward, on every page.** The
  browser cannot do it here: `history.scrollRestoration` restores the window,
  and this app scrolls a pane inside a full-height shell. Positions are stored
  per URL and re-applied until they stick.
  - **The scrollers are discovered, not listed** — `.main` on browse,
    `.main-solo` on the review queue, `.detail-left` on a component, and the
    component page scrolls two columns independently.
- **An expanded verification row is remembered too.** Restoring the offset
  alone puts a reader at the same pixel with the section they had opened closed
  again, which is somewhere else entirely.

## 2026-09-14 (review card) — no edit mode, work on top, hints you can read

- **`fp.tier` no longer opens with the word "tier".** "The tier test was run in
  order, and a Tier 0 claim was verified against the stock copper" told a reader
  nothing unless they already knew the standard. It is now **"The name follows
  the right rule for this package, and a KiCad name means identical copper"**,
  with the hint as four numbered questions, one example each, and the reason the
  copper diff matters stated as the consequence: a name matching KiCad's over
  different copper can map the symbol's pins to the wrong pads with nothing to
  warn you.
- **`fp.one_land_per_package` asks a question now**, not gives an instruction.
  "Reuse the footprint the library already has" cannot be answered yes or no —
  a VQFN-40 with a land nothing else uses had no obvious answer, and the
  reviewer was left choosing between `checked` and `does not apply` on a coin
  toss. It reads **"No other footprint in the library draws this same
  package"**, and the hint states outright that a package unique to one part
  answers CHECKED: one land exists and it is this one. There is no case for
  `na`, because every footprint draws some package.
- **`fp.one_land_per_package` is rewritten in plain language**, 1,996 → 1,181
  characters. It was six dense paragraphs that mixed the rule, one family's pad
  coordinates and a 3D-modelling instruction. Now: the rule with a worked
  example a resistor or a push button fits, three numbered steps to reuse a
  land, when it is a different package, when never to adjust one, and what to
  record. Nothing was dropped except the 6x6 tactile family's eight
  measurements — the footprint itself is that specification, and the hint names
  which one to copy.

- **The "Verify…" button is gone.** Every checklist row is answerable straight
  away, and **Save / Cancel appear at the top the moment an answer is staged**.
  Entering an edit mode was a click that carried no decision and hid every
  control behind it.
- **Items sort by how much attention they need**: findings, then warnings, then
  open, then excused by a standing decision, then checked. The rank is read off
  the SAVED answer, never a staged one, so answering a row does not make it jump
  out from under the cursor — it re-sorts on the next load.
- **The state sentence and the buttons that act on it share one line.**
  "Partially verified — 8 item(s) still open." and `Mark checked` /
  `Revoke verification` were stacked, and so were the note box and `Save` /
  `Cancel`; that is two rows of chrome above every checklist. The sentence
  gives way first when the line is tight, because it is the half a reader can
  finish from the pills above it.
- **A hint is behind an ⓘ, shown the moment the pointer is over it.** It used to
  be a `title` attribute: a one-second wait, no sign it existed, and the
  browser's own box with no line breaks — for text that is the only explanation
  of what a check means. New shared `components/InfoTip.tsx`; the item's key
  stays in `title`.

## 2026-09-14 (footprint machine checks) — two checks that could not see

- **`fp.via_dims` looked for a primitive that does not exist in a footprint.**
  It matched `(via ...)`, which lives only in a `.kicad_pcb`; a `.kicad_mod` has
  no via element at all. The regex matched **0 of 213 footprints**, so the check
  answered `na — no vias` on every one, including **19 with a real thermal-via
  field** — `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias` has 16.
  KiCad draws a thermal via as a `thru_hole` PAD carrying the exposed pad's own
  number, and the check now reads those: a through-hole pad is a via when its
  number also appears on an smd pad, or when it has no number. Result:
  **19 checked, 194 na**, all at 0.6/0.3 mm.
- **`fp.smd_rratio` counted paste-only apertures.** The four pads it failed the
  VQFN on are `(layers "F.Paste")` stencil openings at `rratio 0.174825`, not
  copper. The house corner ratio is a rule about pads, and KiCad writes whatever
  radius it computed for a paste sliver. Pads with no copper layer are skipped;
  library failures **36 → 33**, and the 33 are real.
- **The conformance digest now includes a hash of `validator.py`.** It covered
  the resolved checklist, the facts and the exceptions — enough for a
  declarative check, because editing one changes the item, and NOT enough for a
  check written in Python. After the `fp.via_dims` fix, 15 footprints kept
  serving `na — no vias` from cache because no fact and no item had moved.
  Editing the validator now invalidates the library once and the warm-up
  refills it, which is what decision 0017 promised.

## 2026-09-14 (states) — a row and its card said different things

- **A list row is measured against TODAY's checklist, not the record's own
  snapshot.** `VQFN-40-1EP_5x5mm_P0.4mm_EP3.3x3.3mm_ThermalVias` read
  `CHECKED (AGENT)` on its row and `PARTIAL — 8 items still open` the moment you
  opened it. Its record was written against an 18-item checklist with 6 judgment
  items; today's has 38 with 14. **Row and card now agree on all 862 subjects.**
  - The snapshot stays correct for HISTORY — what a past record was measured
    against — which is the history list, not a live state.
  - Resolving a checklist per subject costs 33 ms, so a list page cannot pay for
    it: 862 subjects is 28 seconds. The judgment list is cached on
    `conformance.judgment`, which already rides the digest covering the resolved
    checklist, so it invalidates itself when a check changes. List pages are
    unchanged at **0.48 s** for 442 components.
- **A subject with NO review record read `checked`.** With no record there was
  no snapshot, so the denominator was empty and an unreviewed footprint passed.
  **42 components** were being carried by one. They now read `unreviewed`.
- **The judged fraction counted off-checklist answers.** `SMAJ24CA` read
  "JUDGED 13/13" beside `partial` with four checklist items open, because four
  `custom:` answers filled the places of four unanswered ones. `answered` and
  `total` now count the checklist only; `custom:` answers are still shown, in
  their own list.
- **What this does to the numbers.** Components reading `checked` end to end:
  **174 → 1**. Nothing was un-verified — the old figure measured each part
  against whatever checklist existed when somebody last looked at it, and the
  library gained checks all day. 205 of the 862 individual subjects are checked.

## 2026-09-14 (plain words) — a check nobody understands is not a check

- **The five simulation checks are rewritten in plain language.** The old
  wording assumed the reader already knew the vocabulary. "The model header
  names every behaviour it leaves out, and why" is now **"The model says which
  real behaviours it does NOT reproduce"**, and every hint follows the same
  shape: what the check asks, why it matters with a worked example, then
  numbered steps.
  - The worked example on `cmp.sim_limitations` is a real one. `sigma_npn`
    holds the current gain at `BF=400`; a BC817-40 falls to 170 at 300 mA. Size
    a base resistor from that simulation and you give the transistor 0.75 mA
    where it needs 1.8 mA. The plot shows it saturated. The board does not.
  - `cmp.sim_params` is automatic, so its wording lives in
    `validator._CHECK_SPECS`, not the checklist. Changed there.
  - No scope, severity or result changed.
- **Nine findings that opened "No statement of what the model omits" are
  reworded.** Same flags, same models, nothing re-decided — they now lead with
  what is missing and what it costs.
- **`sigma_npn` v2 has the header comment it never had**, naming what the block
  ignores (beta roll-off, quasi-saturation, self-heating, breakdown, charge
  storage, leakage) and what it is good for. `BC817-40-7-F` goes to **checked**;
  `BC847CLT1G` and `MMBT3904,215` share the model.
- **`BC817-40-7-F`'s `cmp.sim_numbers_read` is answered.** `BF=400` sits inside
  the -40 grade's published hFE band, 250 to 600 at `VCE=1.0V, IC=100mA` (p4).
  The sheet prints no typical, so it is a mid-band choice, not a quotation, and
  `IS`, `VAF`, `RB` and `RC` are fitted block defaults. No value changed.

## 2026-09-14 (families) — a triangle rule needs a triangle

- **A review card folds the checks that are NOT about the part.** "Not about
  parts like this one" and "switched off here" now sit behind a count
  (`5 checks not about parts like this one`) instead of printing inline. A
  MOSFET was showing "IQ is per CHANNEL…" and "the exposed pad is documented"
  in the middle of its checklist, where they read as open work even though the
  scope was correct. Kept rather than dropped — reading them is how somebody
  finds out a scope is wrong.

- **The five analog-triangle geometry checks now require a triangle body**, the
  way the gate-family ones already did. `sym.triangle_body`, `sym.triangle_pins`,
  `sym.inverting_on_top`, `sym.input_marks` and `sym.comparator_glyph` were
  scoped by `comp_type` alone; `sym.gate_body` and `sym.digital_block` had
  carried `$symbol_has_box` from the start.
- **`ADA4945-1` was the part it caught.** A 17-pin fully-differential amplifier —
  differential in, differential out, two feedback pins, VOCM, MODE, DISABLE, two
  clamps and four supplies — correctly drawn as a BOX, and asked for 15.24 mm
  triangle coordinates it can never have. Its judgment list drops 15 → 10 and
  `sym.drawing_family`, which is the right question for it, stays open.
- **The two triangle sizes were verified against every symbol.** They do not
  overlap: 15.24 mm is `COMPARATOR|OPAMP`, 10.16 mm is `LOGIC` without a box.
  A logic buffer (`74LVC1G17`) is on the 10.16 rule, as it should be.
- **`sym.drawing_family` had no scope at all** and reached all 207 symbols, so a
  MOSFET (`Q_NMOS_GSD`, behind `AO3400A`) was asked which of the three IC
  families it belonged in. New fact **`$symbol_family_choice`** reads
  `checklists.FIXED_PICTOGRAM` — 53 families drawn one way by convention:
  transistors, diodes, passives, crystals, relays, connectors and mechanical
  parts. Reach 207 → **98**, all ICs and modules.
  - A symbol with no `comp_type` on any component (a power flag, a bare
    graphic) returns ABSENT and is skipped too.
  - A shared symbol keeps the question if ANY of its components has a choice.
- **Every other judgment check was surveyed for the same fault.** The remaining
  unscoped ones — `cmp.description`, `cmp.category`, `cmp.base_symbol`,
  `cmp.value_field`, the seven `fp.*` naming and geometry items,
  `sym.pin_numbers_unchanged` — are genuinely universal. `sym.drawing_family`
  was the only outlier.

## 2026-09-14 (scope) — a rule that says what it means

- **The two rail checks are scoped by what a part IS, not by how its symbol is
  typed.** `cmp.sim_iq_per_channel` ("IQ is per CHANNEL…") and
  `cmp.sim_supply_current` were reached through `$symbol_power_pins`, which asks
  whether a SYMBOL happens to type a pin as power. New fact **`$powered_die`**
  answers the real question, reading `checklists.NO_QUIESCENT_CURRENT` — 30
  families with no powered die: transistors, diodes, passives, plain LEDs,
  crystals, relays, switches and the house simulation stand-ins.
  - The list is of what is EXCLUDED, on purpose: a new IC type keeps the check
    by default, where a positive list would let it escape silently.
  - **No component changed scope** — all 442 already agreed. The gap it closes
    is the next one: `TPD4E05U06DQAR` is a TVS array that draws two rails, so
    the day it gained a `Sim.Params` row it would have been asked for its
    per-channel quiescent current.
  - The scope now also READS on the card. It was briefly a 265-character
    negative lookahead; a fact puts the family list in `checklists.py`, where it
    carries its reasoning, and leaves `$powered_die matches ^true$` on screen.

## 2026-09-14 (TS24CA) — a pad named MP is not a missing pin

- **`cmp.pads_to_pins` fired on its own fix.** TS24CA's two frame tabs were
  numbered 3 and 4; the owner renamed them `MP` on 2026-09-13 so no net could
  reach them, and the next read reported a pad the symbol does not draw.
  `$pads_without_pins` now ignores pads named `MP` or `SH` — KiCad's own
  libraries use both, and the name IS the statement that no pin lands there.
  Library findings 13 → 9; the nine that remain are numbered pads (an exposed
  pad, an NC lead, a second antenna terminal) and are real questions.
- **The TS24CA package name said `SMD-4P … Right-Angle`.** It has two terminals
  plus two `MP` pads, and the switch is top-actuated. Now `SMD-2P
  4.7x3.5x2.25mm`, matching its TS3625A sibling. Unversioned, so no footprint
  version and no copper change; the Buttons library rebuilt.
- **TS24CA now reads `checked` on all three subjects.** The footprint had been
  held at `failed` by a `custom:` flag saying the name claimed 4P — resolved by
  the v5 rename a day earlier and never closed. Ten open judgment items were
  answered (`fp.one_land_per_package`, `fp.tier`, `fp.field_order`,
  `fp.jlc_land`, `fp.shared_land_record`, `fp.silk_clear`,
  `sym.drawing_family`, `sym.fp_filters`, `sym.easyeda_diff`,
  `sym.pin_numbers_unchanged`).
- **Verification notes rewritten short.** Nothing was re-decided: every result
  is unchanged. The longest was `fp.land_pattern` at 2,368 characters, now 234,
  with the owner's accepted-deviation decision intact and the original finding
  still on `superseded`.

## 2026-09-14 (later) — the CE_Dongle_V3 BOM found eight wrong checks

Walking 57 components one by one was a test of the check system, and it failed
in eight places. All eight are fixed.

- **A startup migration was reverting checklist edits.**
  `migrate_rules_onto_items` re-stamped every CATEGORY checklist from the
  retired rules table on every restart, where the BASE path had been given
  `only_missing=True` for exactly that reason. Removing a bad pattern published
  v4; the next reload published v5 with it back.
- **`Value` had two owners.** `cmp.value_field` splits by `comp_type`;
  `cmp.property_values` carried a competing per-category pattern that did not.
  They disagreed on a ferrite bead and two LAN transformers, and the
  category-wide one was wrong every time. Removed from all four categories.
- **Checks demanded what a part cannot have.** An addressable RGB LED was
  required to have one `Color` and one `Forward Voltage`; five parts on the
  skill's own "deliberately free text" list were failed against a template.
  Split by `comp_type` — four became rules, one became a standing exception.
- **The new simulation checks were over-broad**: 57 of 94 parts carrying
  `Sim.Params` have no supply pins, and a tactile switch was being asked about
  its quiescent current. Scoped to parts with rails.
- **`cmp.datasheet_is_document` was a judgment asked 413 times** that duplicated
  `cmp.datasheet`. All 416 archived documents are PDFs, so its mechanical half
  is now a machine guard and its judgment half goes where it belonged.
- **New `sym.should_stack`** — the half `sym.stacked` could never ask, because
  that one only reaches a symbol that already stacks. Seven real findings,
  including a U.FL jack drawing its ground as two separate pins.
- **`TOGNJING` is `TONGJING`** — the archived datasheet prints
  `www.hftongjing.com` in its own footer, which is the primary source the
  skill's own low-confidence note had asked for.
- **33 verifications restored.** Components that lost their record to a
  `comp_type` edit made before [decision 0019](docs/decisions/0019-a-classification-carries-the-first-time-it-is-set.md)
  existed now carry it again; 24 others stayed blocked on real material
  changes. **418 of 442 components carry a verification, up from 385.**

## 2026-09-14 — every check says which parts it is about

**The convention skills became checks.** `conventions-footprints` (1105 lines),
`conventions-symbols` (654) and `conventions-library` (573) are now 197, 102 and
112 — an index of which check answers which question. Every number, decided case
and trap moved into the check hints, where it is read at the moment it is
needed. Each cut was audited token by token against the new text plus every
hint before publishing; 16 pieces of evidence that were being dropped went back.

**Judgment checks are scoped.** They used to be asked of every subject of their
kind — a two-pin ferrite bead was asked how its functional blocks were grouped.
Nineteen scopes were added, each measured against the whole library first, and
two were built and thrown away for hiding a 94-pin module and a 100-pin
connector. Live standing exceptions fell from **186 to 55**: 131 were revoked
because the checks now say what they mean.

**`comp_type` on all 442 components**, across 94 types, with 385 keeping their
verification — see [decision 0019](docs/decisions/0019-a-classification-carries-the-first-time-it-is-set.md).
`$symbol_comp_types` carries it to the drawing axis, which is what let section 5
of the symbol conventions become nine specific checks (the 15.24 mm triangle,
the inverting input on top, the comparator glyph, the gate body, the digital
block) instead of one yes/no asked of all 207 symbols.

**Eighteen new checks**, nine of them promoted from recurring `custom:` keys.
`sym.sourcing_defaults` found 19 symbols storing an LCSC or Manufacturer default
the generator would inherit onto every component built from them; the custom key
had found 2.

**Fixes.** A declarative check was throwing away its author-written hint on
save. `$electrical_props` counted `Reference` and `LCSC Part Class` as
electrical data and excluded `Sim.Params`, which is one. A pinless drawing and
an unparseable one both reported no pin count, so no scope could tell them
apart.

## 2026-09-14 — Two convention documents audited against what actually runs

Neither footprint nor symbol conventions turned out to be compressible: they are
almost entirely authoring instructions — how to draw a cathode bar, how to size
a box, how to measure a 3D model — and 44 and 31 table rows between them. There
was no data to move into a check. What the audit found instead was worse than
bulk.

**The footprint style section claimed the validator enforced eight rules. It
enforced four.** Auditing the other four found that two of them are wrong:

- "SMD pads carry F.Cu, F.Paste and F.Mask, all three" — 25 footprints differ
  and every one is an exposed pad, which legitimately has no paste or a
  separate aperture.
- "Through-hole pads are circle or oval" — 25 differ and every one is a pin-1
  pad, rectangular by KiCad convention.

The third, the roundrect corner ratio 0.25, is real: 36 of 212 footprints carry
another value. `fp.smd_rratio` checks it now, as a warning, because most of the
36 are stock lands the tier rule freezes. The fourth — the internal footprint
name matching the filename — is satisfied on all 212.

The section now names the check that holds each rule and says plainly which two
were wrong. A document that claims the machine checks something it does not is
worse than one that stays silent: the reader stops checking it too.

**The symbol grid law does not match the library.** It states 2.54 mm in both
axes as absolute; the check enforces 1.27 mm and nothing violates it, while 61
of 206 symbols are off 2.54 — `RPi_CM5` with 200 pins, `ZED-F9P` with 102, every
large STM32. Dense parts do not fit on 2.54 mm. The claim that an off-grid pin
"cannot be wired on a default sheet" is also not so; KiCad's default grid
includes 50 mil. Recorded as an open decision rather than resolved either way.

## 2026-09-14 — A rule leaves a skill only when a check has it

An earlier pass today removed 42 KB from the component-conventions document on
the assumption the new checks held that data. Audited line by line, they did
not: the rule that an RF part spells the key `VSWR` and never `V.S.W.R` had no
check at all, 15 of 31 description templates were in no check, and a decision
rule - "a family-wide deviation defends itself" - was deleted outright. That
pass was reverted.

Redone against a mechanical test: a row leaves only when a check holds its data
AND the row carries nothing else. That removed **60 of 81** manufacturer rows
(a spelling plus a list of feed misspellings, and the check holds the spelling)
and **9 of 31** template rows. The other 21 and 22 stayed, because each carries
a decision, a reason, or has no check.

51 KB to 47 KB. That is the compression actually available: the bulk of that
document is reasoning, and reasoning is what a check cannot hold.

### New

**`absent`** - the assertion for a rule that says there must be no X. Every
other assertion reads a value, so a subject without one is answered "does not
apply" before the assertion runs, which made "this key must not exist"
inexpressible. `cmp.vswr_key` is the first to use it.

[what-a-check-can-hold.md](docs/reference/what-a-check-can-hold.md) records the
mapping and the order - build the check, measure it, then cut.

### Found, not fixed

`Inductors`, `RF` and `Circuit_Protection` carry no `comp_type`, so their Value
and description rules cannot become checks: a fixed inductor, a ferrite bead and
a LAN transformer are three rules sharing one category with nothing in the data
to tell them apart. `Connectors` has the same problem differently - `Pluggable
terminal block; {Pitch}` and `Pluggable terminal block; 3.5mm` coexist in one
family. Work list row 24.

## 2026-09-14 — The conventions point at the checks, and Zener has one n

**Four skill documents were republished** so an agent stops hand-verifying what
the platform already decides. `platform-workflow` v11 was the urgent one: it
still told agents to answer `skipped`, retired in September, and still described
the automatic checks as something recorded on publish. It now says what the
platform does — checks are worked out on read, "does not apply" is a standing
exception that outlives the version and needs a note, notes are capped, a
warning does not fail a part, and a switched-off check is not the same as one
that is not about this part.

The three convention skills now mark the rules the platform enforces —
`fp.quad_numbering`, `fp.zero_annulus`, `sym.top_edge`, `sym.pin_length`,
`cmp.value_placeholder` and `cmp.value_field` — and keep the prose, which says
why the mistake happens and what to do when a check fires. A check cannot
explain itself.

**Zener is spelled with one n, everywhere.** All six Zener diodes were
republished: the property key `Zenner Voltage`, `comp_type=ZENNER` and the
template word "Zenner Diode" all moved together, because they have to — a
dangling `{Zenner Voltage}` fails the template check. No `Zenner` remains on any
live version. The six lost their verification, as a property edit always does.

**The Diodes Value rule is now three rules.** The base list splits on category
and cannot reach inside one, so the Diodes category carries its own variants
split on `comp_type`: the reverse stand-off voltage for a TVS, an RKM V code for
a Zener, the part number for a rectifier.

It found two parts carrying their MPN where the stand-off voltage belongs —
`SMF28A` and `SMF6V0A-E3-08`, now `28V` and `6V`. Both were read off each part's
own **Reverse Stand-Off Voltage** property, not decoded from the part number.
The work list had recorded seven such parts; there were two.

## 2026-09-14 — Changing a check changes the lists, without a restart

Editing a checklist re-fingerprints every subject it reaches, but nothing acted
on that: list surfaces read the cache without re-checking the fingerprint, and a
detail page worked out the new answer and then threw it away. So a check edited
on the platform changed nothing anybody could see until the API happened to
restart. Found by shipping the new checks to production and watching the
numbers not move.

Saving a checklist now re-evaluates that kind in the background, and the pages
that recompute keep what they worked out. Revoke a standing decision and the
list of parts failing that check reports it on the next request.

## 2026-09-14 — Fix: an empty table took the page down

Any list with a default sort crashed when it had no rows. The sort asks the
first row what type it holds to decide between numeric and text ordering, and
on an empty list there is no first row, so the question threw and the whole
page went blank.

It surfaced on Reviews -> Exceptions, which is the first list that is
legitimately empty on a library with no standing decisions recorded yet. It
worked in testing because the test library had six.

## 2026-09-14 — An explanation has a length now

Every field that holds a written reason is capped, and an over-long one is
refused rather than quietly cut.

| Field | Limit |
|---|---|
| a note on a checklist item | 400 |
| a custom check's own wording | 200 |
| the note on a verification pass | 300 |
| an exception's note | 400 |
| an exception's evidence | 600 |
| a revoke reason | 300 |
| a version's change comment | 600 |

The numbers come from what was already stored. A person writes **31**
characters in a note. An agent's median is **367**, and the longest in the
library is **3,316** - about 500 words on one checklist item. Nobody reads that,
so the finding inside it is lost as surely as if it had never been written.
Version comments were worse: symbol edits ran to a median of 876 and a maximum
of 4,087.

Refused, not truncated. A cut-off sentence teaches nobody; the refusal names the
length, the limit and what to write instead - "say what is wrong and how you
know, in a few sentences". A refused item comes back on the blocked list and the
rest of the save goes through.

In the web UI the box simply stops accepting text, with a counter that appears
in the last quarter, so nobody writes three paragraphs and then loses them.

Nothing already stored was changed. The limits apply to what is written from
now on.

## 2026-09-14 — Standing decisions have a register, and a failing check has a worklist

**Reviews → Exceptions** lists every standing decision in the library: the
subject, the check, why, how long it holds, who made it, and whether it still
applies. An exception was visible only on its own component's card before this,
so nothing could answer "what have we excused". A decision that pins nothing
holds for every future version of a part, and now somebody can see which ones
those are.

A **stale** row is the point of the screen. An exception dies when a fact it
named changes, and one that has quietly stopped applying means the check it
excused is failing again somewhere nobody is looking.

**A failing check opens.** The library-health panel already grouped failures by
check rather than by part, because "fp.courtyard_grid on 76 footprints" is one
job and "218 failed parts" is a wall. The numbers were dead text. Click one and
it lists every part it fails on, with each part's own note and a link to it.

**The review state is three facts, not one word.** A card now reads
`ISSUES · FAILS · JUDGED 10/11` instead of `ISSUES` alone. "Partial" used to
mean "nobody has looked", "a question was added last week" and "one item is
still open" all at once, and a footprint could read "unreviewed" straight after
somebody decided every check on it. The queue keeps the single word, because a
list has to sort by something, and carries the facts in the tooltip.

### Fixed

A verification saved after **Mark checked** discarded every answer underneath
it. The one-click confirmation is stored with no item breakdown by design, and
the next save was seeded from it, so a part went from twelve recorded answers to
one. Found 2026-08-25, fixed today. Answers now survive the sequence.

The library-health panel counted some failures twice — once from the agent's
flag and once from the machine's finding — reporting `cmp.datasheet_text` on 47
components where 27 carry it.

## 2026-09-14 — Eight convention rules are checks now, not prose

Rules that lived as paragraphs in the skill documents, for an agent to read and
re-read on every part, are checks the platform runs itself:

| Check | From | Finds today |
|---|---|---|
| `fp.zero_annulus` | footprints section 6 | 0 |
| `fp.quad_numbering` | footprints section 2 | 0 |
| `sym.top_edge` | symbols section 3 | 24 (warning) |
| `sym.pin_length` | symbols section 4 | 2 |
| `cmp.value_placeholder` | library section 3 | 0 |
| `cmp.pins_to_pads` | - | 0 |
| `cmp.pads_to_pins` | - | 13 (warning) |
| `cmp.value_field` | library section 3 | 0 |

Across all 857 subjects the eight add **two** error-level failures, both in
`sym.pin_length`: `Crystal_GND24_Small` mixes 0.635 mm and 1.27 mm stubs,
`LSM6DS3` mixes 2.54 mm and 3.81 mm. Nothing else turned red. That is what
severity and computed conformance were built for.

**The Value rule is now seven rules under one key.** A resistor's Value is
checked against the RKM code, a capacitor's against the unit format, an IC's
against its part number verbatim, a test point's against its own name. A
category no rule covers yet falls through to the same human question as before,
so nothing was lost. The Checks page shows them as `BASE.Resistance`,
`BASE.MPN`, `BASE.Component name` and so on, each with the condition it applies
under.

`fp.quad_numbering` catches the mirrored-footprint defect the skill records as
having shipped once. It reads the direction the pads trace in number order:
every one of the 48 IC packages in the library runs counter-clockwise, and the
seven parts that run the other way are all connectors, whose numbering follows
the datasheet and which the check deliberately does not cover.

**Six parts carry a standing exception instead of a recurring finding.** The
four `15EDGKNM` connectors, `KEYS2466` and `RPi_CM5` are the deviations the
library conventions already document. Each now holds a recorded decision with
the reason on it, so the rule stands for everything else and nobody re-discovers
them.

## 2026-09-14 — A check can read the drawing

Checks could only ask about a component: its category, its base symbol, its
fields. A symbol or a footprint carried three facts - its kind, its name and a
fingerprint - so every geometry rule stayed prose in a skill document for an
agent to read and re-read.

They now carry their own. A footprint check can ask for the pad count, the lead
pitch, how many pads sit off the 0.1 mm grid, which corner pad 1 is in, and
whether a quad package numbers counter-clockwise. A symbol check can ask for the
pin count, the distinct pin numbers, the unit count and which electrical pin
types are present.

Three facts compare two things, which no single assertion can do:

- **`$pins_without_pads`** - symbol pins whose number has no pad. A signal with
  nowhere to land.
- **`$pads_without_pins`** - pads the symbol does not draw. Usually an exposed
  thermal pad or an NC lead.
- **`$value_is_mpn` / `$value_is_name` / `$value_placeholder`** - the three
  shapes the Value rule takes.

Measured over all 439 components: **13 parts** have a gap between symbol and
footprint, and **every one of them is a pad the symbol does not draw** - an
exposed pad or an NC lead. Not one part has a pin with nowhere to go. Splitting
the one "mismatch" number in two is what made that readable.

Two counting errors are fixed with it. The pad count used to include paste
apertures and thermal vias, so a QFN-16 with an exposed pad reported 26 pads
instead of 17. And a two-pad chip resistor was reported as having pad 1 in the
"bottom-left" corner; it has no corner, and now reads "left".

The Checks page reads the fact list from the platform instead of holding its
own copy, so a footprint rule is never offered a component fact.

## 2026-09-14 — "Does not apply" is one decision, and it lasts

N/A is gone as an answer. The button on a check now reads **Does not apply...**
and it records a standing decision instead of a note on one version.

The two used to say the same thing, and only the throwaway one got used: 314
live N/A answers, 312 of them written by agents, not one with a reason on it,
every one due to expire at the next version bump - against zero rows in the
table built to hold such decisions. The reason was simple. N/A was the button on
the row.

Three things change for you:

- **You can say it about a check nobody has run.** Every judgment item offers
  it, not only a failing one. A check that is not about this part does not need
  running first.
- **It asks three questions**: which way it does not apply, why in your own
  words, and how long the decision holds. The note is required, because it is
  the only place the reason will ever live.
- **Excused items leave the count.** A card reads "judged 3 of 9" with "2
  item(s) excused by a standing decision" beside it. An exception says the
  question is not about this part. It never says somebody looked.

An earlier bug is fixed with it: granting an exception on an item nobody had
answered yet did nothing at all until an unrelated save happened to run. It now
takes effect on the response.

The library health panel also reports automatic failures again - `fp.courtyard_grid`
on 76 footprints, `cmp.datasheet_text` on 47 components. Those went invisible
when automatic checks stopped being written into records.

Agents keep working. The API still accepts "na" and turns it into a pinned
exception, so an agent cannot record a blanket waiver over every future version
of a part - only a person can, in the review card. An agent's decision must now
carry a note.

Decision record
[0018](docs/decisions/0018-does-not-apply-is-an-exception-not-an-answer.md).

## 2026-09-14 — Excusing a check takes one button

A standing exception was already in the platform, but nothing said so. The only
way in was Verify... then N/A then "keep this decision?", and that chain sat
under three folds: the verification row, the checklist, and verify mode. A
failing check in front of you looked like something you could only fix or
ignore.

Now a failing row carries an **Excuse...** button. It asks three things - why,
a note, and how long the decision holds - and it needs no verify mode, because
an exception is not an answer and stages nothing.

Four smaller changes in the same place:

- A part with a failing check opens on that check. The row and its checklist
  are unfolded for you.
- Clicking the row LABEL opens it. Before, only the small triangle worked.
- Standing decisions list above the checklist, so one you grant can be found
  again. Each has its own **Revoke exception**.
- The card's own Revoke is now **Revoke verification**. Two identical red
  buttons a few pixels apart withdrew very different things.

A component can now pin an exception to its own fields - "while this
component's own data is unchanged". Its `$material_sha` is the symbol's and the
footprint's joined together, so the drawing scope said nothing about a Value or
a datasheet. The scope label reads what was actually pinned.

## 2026-09-14 — Automatic checks are worked out, not remembered

Change a check and the whole library re-reads itself. There is no "Re-run auto
checks" button and no "Apply to existing parts" button, because there is nothing
left to re-run: the automatic answers are computed when something asks for them,
and cached against a fingerprint of the checklist, the part and its exceptions.
Edit any of those and the fingerprint changes, so the next read works it out
again.

Measured: tightening the drill minimum from 0.3 mm to 0.45 mm reported 19
failing footprints across all 212 immediately — no republish, no backfill.
Publishing a check used to do the opposite: adding one moved 418 components to
"partial" in a single publish, and the only ways out were a mass republish or
answering them by hand.

Two smaller effects worth knowing. Completeness is now measured over the
judgment items only, so a machine check can never sit "unanswered". And "Mark
checked" no longer hides a failing automatic check — it vouches for the
judgment, not for what the code can still see.

Decision record
[0017](docs/decisions/0017-conformance-is-computed-not-recorded.md).

## 2026-09-14 — Warnings, and decisions that last

**A check now has a severity** — error, warning or ignore. A warning-level
failure is shown and counted but never makes a part read as failed, which is
what lets a new check ship at all: publishing one used to re-open the whole
library, and four checks were seeded *switched off* to avoid it. Those four are
now warnings, which is what "off" always meant. The severity is recorded on the
answer, so editing a checklist never rewrites what a past review meant.

`Ignore` replaces the old on/off switch: one control with three values instead
of a switch beside a severity.

**And a decision can be kept.** Answer a check N/A on the review card and it now
asks whether to keep it — for this drawing, or for this part always. A standing
exception outlives the version, so a pad move no longer takes it with it. The
part lists its exceptions with who granted each one, why, and what it is pinned
to; revoking one brings the check straight back.

This is the fix for something the numbers made plain: the library held **zero**
waivers, while agents had invented **188 different `custom:` check names**, 150
used exactly once. Nobody was refusing to record decisions — a waiver died with
the version, so nobody wrote one.

An exception scoped to the drawing dies the moment the copper moves, and one
pinned to a fact the part has not got is refused rather than being quietly
stale. Both halves are copied from KiCad's own DRC model, which has carried a
severity per rule and a list of excluded findings for years. Decision record
[0016](docs/decisions/0016-severity-and-standing-exceptions.md).

## 2026-09-14 — Checks you write instead of code

A check can now be **declarative**: pick a fact about the part, pick one
assertion, and the validator answers it. No new code per rule.

```
$symbol_reference   is one of    J
$symbol_pin_count   is at least  1        when $symbol_on_board ^true$
$footprint_pad_count is at least 2
```

Facts are the same vocabulary `when` reads — properties, `$category`,
`$base_symbol`, `$purchasable` — plus new ones derived from the drawings a
component pins: `$symbol_reference`, `$symbol_pin_count`, `$symbol_unit_count`,
`$symbol_on_board`, `$symbol_sim_link`, `$footprint_pad_count`,
`$footprint_has_model3d`. They are computed only when a check reads one, so a
checklist mentioning none costs nothing.

Assertions: is one of · matches · is exactly · is at least · is at most · is
present. Exactly one per check — the wording is written from it, so the sentence
a reviewer reads cannot disagree with the rule.

This is what makes symbol rules per component category possible: a symbol has no
category, but the component pinning it does, so the check lives on the
component. Trialled on Connectors: `$symbol_reference is one of J` found six
parts drawn as USB, CN, CN, BAT, BAT and FPC, and `$symbol_pin_count is at least
1`, narrowed to board parts, correctly passed over the seventeen off-board
terminal-block plugs instead of failing them.

## 2026-09-14 — One check, several variants

A check can now be stated more than once for one scope, as named **variants**:
`Transistors.NMOS` requires `Drain Source Voltage`, `Transistors.NPN` requires
`Collector-Emitter Voltage`, and both are `cmp.required_props`. That was the one
thing a `when` predicate alone could not do, and it is what
`conditional_required_properties` has been asking for since the original YAML
import.

The Scope column reads `Category.VARIANT`, so filtering `Scope` for
`Transistors.` gives you every sub-type rule at once.

**No ordering to remember.** A key with several variants must split on ONE field
with distinct values, plus at most one variant with no condition — the fallback.
At most one can match, so nothing depends on the order they are written in, and
a sorted table cannot contradict the effective rule. The save path refuses a
variant nothing can reach: a condition matching everything, a duplicate
condition, a second fallback, or a split across two fields.

A disabled variant falls through to the next one; disabling every variant is
what switches the check off. A category restating a key replaces its whole
group.

**And the fragility is now countable.** Open a varied check and it prints how
the live parts fall: `14 part(s) in scope · NMOS 7 · NPN 3 · other 4`. A
non-zero "no match" means the field you are splitting on is not reliable — which
is the honest signal that the category wants a subcategory instead of a
predicate.

## 2026-09-14 — Every check in one table

Reviews → Checklists is now a single `DataTable` of every check in the
platform — one row per scope and check, with a filter on every column. Filter
**Scope** to see what one category does differently, **Applies when** to find
the conditional ones, **Runs** for what is switched off; sort by **Key** and a
check lines up with every override of it, so `cmp.required_props` across
fifteen categories reads as fifteen adjacent rows.

A new check is added in the first row of the table: pick its scope, type its
key and what it asks, press Add. There is no separate form.

Rows are what a scope STATES, not the cross product — a category contributes
only what it changes, which is the same question answered from the other side.
Open a row to edit its settings, its `when` predicate, or a judgment check's
wording.

Publishing is per scope and the button says how many: a checklist version
belongs to one scope, so editing rows from three scopes publishes three
versions, and both the toolbar and the confirmation name them.

## 2026-09-14 — A check says which parts it is about

A checklist item can now carry a **`when` predicate**: "apply this check to
components where `comp_type` matches `^TVS$`", or `$category`, `$base_symbol`,
`$purchasable` — a bare name is a property, a `$` name is a structural fact the
API validates. Every condition must match. Edit it under the caret on any
check; a row that has one is badged `when`. Decision record
[0015](docs/decisions/0015-a-check-says-which-subjects-it-is-about.md).

This is what `conditional_required_properties` has been waiting for since the
original YAML import — it has sat in the Diodes and Transistors rule blocks
since the beginning with no check implementing it.

A check whose predicate a part does not satisfy is reported as **n/a here**, not
as switched off. Those are different statements — one says the check is not
about parts like this one, the other says the owner turned it off — and the
review card prints them separately.

One caution, recorded in the decision: a predicate over a PROPERTY is only as
stable as the property. A category is a row; `comp_type` is free text, and the
library already carries the `ZENNER` spelling the conventions skill flags. An
edit there silently stops the check running.

## 2026-09-14 — A check carries its own settings, and the rules table is gone

**Reviews → Checklists is one tab per kind now**, not one entry per checklist.
Components, Symbols, Footprints in the sidebar; the scope is a dropdown in the
header, with a dot against each category that already states something. A
category's list is created the first time you save one and removed when it
states nothing, so the sidebar cannot fill with empty lists.

**Every check is one row, folded.** Key, what it checks, where it comes from,
whether it runs — and the caret opens the rest: the thresholds, the property
lists, the patterns, the wording of a judgment check. Filter by Stated here /
Automatic / Judgment / Switched off, or search by key.

Every number, list and pattern the validator measures against now lives on the
checklist item of the check that uses it, under the sentence it produces.
Reviews → Checklists → any list, **Automatic checks**: the drill minimum sits
under "No drill hole below 0.3 mm", the courtyard width under its own check, and
a component's required properties under `cmp.required_props`. Decision record
[0014](docs/decisions/0014-a-check-carries-its-own-configuration.md).

**Fifteen per-category rule sets started working.** They were seeded from the
YAML libraries at the original import and **nothing had ever read them**, so
"a Capacitor carries Value and Voltage" had never been enforced on a single
part. Each one is now a category-scoped component checklist you can edit, and
the merge that was already there does the scoping. Measured over 439
components: **189 now have their property values checked where nothing checked
them before**; 13 fail the new `cmp.property_values` and 11 fail
`cmp.required_props` on rules their own category had always stated. Nothing
already recorded moved — a part picks the rules up on its next publish or its
next "Re-run auto checks".

**Two new checks, both per-category.** `cmp.property_values` applies a
category's value patterns. `cmp.base_symbol_allowed` is the first SYMBOL rule
scoped to a component category: a symbol carries no category, one base symbol
is shared across categories, and a symbol nothing uses yet has none at all — so
the check is answered on the COMPONENT, where the category is exact. List the
base symbols a category allows and a part pointing at the wrong one fails
mechanically instead of waiting for somebody to notice. Both are switched OFF
on the base list with an empty set, so no part gained an unanswered item; fill a
set in on a category to turn one on. (Dry run: allowing only `R` for Resistor
flags `NCP15XH103F03RC`, which is drawn as `Thermistor_NTC`.)

The `rules` table is dormant; a startup migration folded it into the
checklists and reports the keys nothing consumes rather than dropping them
(`conditional_required_properties` on Diodes and Transistors is the one real
rule still unimplemented).

Two fixes fell out of it. An empty manufacturer list now means the check does
not apply, which is what `Mechanical_7S` and `TestPoints` were saying — read as
"none of these is filled in" it failed all 14 of those parts. And a parameter
is refused on save unless it fits its type: a threshold above zero, a pattern
that compiles.

## 2026-09-13 — An automatic check is switched on or off, not typed out

The checklist editor no longer asks anybody to write down what an automatic
check does. `services/validator.py` now carries the catalogue — key, text and
hint for every check it answers — and the editor renders that catalogue
read-only with one switch per row. Saving rewrites a machine item's wording from
the code, so an automatic item can no longer describe a rule the validator does
not apply. Decision record
[0013](docs/decisions/0013-the-validator-owns-the-automatic-checks.md).

**A category checklist can now modify what it inherits.** It always merged on
top of the base list, but additively: it could add a check and reword one, and
it could never say "the base list asks for this and my parts have not got the
thing it asks about". The category editor now lists every inherited item with
three choices — inherit it, override its wording here, or switch it off for this
category. `Reviews → Checklists → New category checklist` creates one.

**Switching a check off turns it off, and the card says so.** The resolved
checklist is now the validator's switchboard: a switched-off key is not run into
the record, an answer it already had is dropped from the next record for that
subject, and the review card and the agent's `get_review_checklist` report it
under `switched_off` rather than leaving the question unexplained. Both kinds of
switch only reach COMPONENT checks per category — symbols and footprints have no
category, so their checks switch on their base list, for every part at once.

**Two new ways to re-run the automatic checks without publishing.** "Re-run auto
checks" on a review card does one subject; "Apply to existing parts" on a
checklist does every subject that list governs. Until now the validator ran only
inside a publish, so refreshing the machine answers meant publishing again —
which drops every agent answer the new version cannot carry. A re-run writes at
the machine tier only: it cannot overwrite a human or agent answer, and it
closes no queued review request.

Two automatic checks that were built but never seeded — `sym.sim_link` and
`cmp.sim_params` — now appear in the editor switched off, so the deferred
decision is one click away instead of invisible.

## 2026-09-13 — `LSM6DS3` redrawn to the house geometry

The symbol put VDDIO and VDD on the top edge and both GND pads on the bottom
edge, which §3 of `conventions-symbols` forbids on anything that is not one of
the §5.6 digital blocks. It was also the first symbol the new `sym.pin_length`
check failed. Published as v5; `LSM6DS3TR-C` was repointed automatically and
starts unreviewed.

No pin number, name, electrical type or count changed — only positions, stub
lengths and visibility. Five defects:

- **Supplies and grounds moved to the left edge**, supplies in the top two
  slots and GND 6 and 7 in the bottom two, so a ground symbol drops straight
  into them instead of turning back under the box.
- **Pins 10 and 11 were 3.81 mm stubs** against 2.54 mm on the other twelve.
- **Pins 10 and 11 also ended 3.81 mm INSIDE the body.** Their connection
  points sat at x = 12.7, which is the body outline itself, so the stub ran
  inward. §4 requires the tip to land on the outline.
- **GND 6 and 7 were a coincident stacked pair with neither hidden** — the
  open finding from v3. They are now two separate visible pins.
- **NC 10 and 11 were hidden.** They are not a stack, so nothing justified it,
  and a hidden `no_connect` pin cannot be given the X marker §2 requires.

Grouping follows the §3 right-side order and was checked against ST
DocID030071 Rev 3 Table 2 (p.20): host serial interface (CS, SCL, SDA,
SDO/SA0), then the sensor-hub master I²C that Table 2 gives as MSCL/MSDA
(SCX, SDX), then the interrupts. One blank slot between groups. Still one unit.

**The NC pads sit on the LEFT edge, above the grounds** (owner instruction).
They carry no net, so they cost nothing there, and moving them off the right
edge drops it from 13 slots to 10. Both edges now span the same height and the
body is 27.94 mm instead of 33.02 mm.

`CS` keeps the plain `line` pin style on purpose. The inverted-bubble rule is
scoped to §5.6 digital blocks, and Table 2 gives CS as an I²C/SPI **mode
select** (1 = I²C enabled, 0 = SPI), not a plain active-low strobe.

`Crystal_GND24_Small` (0.635 mm and 1.27 mm stubs) is the remaining
`sym.pin_length` failure and is untouched.

## 2026-09-13 — A dead pad is stacked, not drawn twice

Three hours after the section above was written, the library owner drew the part
a better way, and the rule it stated is reversed.

- **A straight-through routing pad is now STACKED hidden on the pin it faces.**
  The symbol draws one pin per channel, and the netlist carries BOTH pads on
  that channel's net, so pcbnew raises the ratsnest and DRC does not pass until
  the straight-through trace is drawn. The earlier rule drew the dead pads as
  separate visible pins and trusted the designer to remember the wire across the
  body. `conventions-symbols` v17 states the new rule in section 2.1.
- **`no_connect` on a stacked pin is worse than wrong, it is silent.** Measured
  on KiCad 10.0.5 with a netlist export: KiCad DROPS a hidden `no_connect` pin
  out of the stack, gives its pad a private `unconnected-…` net and warns
  `no_connect_connected`. A drawing that looks like it carries the signal
  across the package carries nothing. `free` carries the pad and stays quiet
  when a design leaves the pads open.
- **Small parts may hide a duplicate power pad again.** The "redundant GND/VDD
  pads are NOT stacked" rule was written for large ICs and was being enforced on
  four-pin parts. It now says what it meant: a symbol split into units never
  hides a power pin; a small part may, with a REASON written in the version
  comment and the `sym.stacked` note; and on the boundary the author asks the
  user, while a reviewer records `custom:stacked-power-pad` so the question
  reaches the Reviews queue.
- **The symbol is published and verified.** `TPD4E05U06` v6 carries the owner's
  drawing — four TVS glyphs on a common ground rail, the straight-through pads
  stacked hidden and typed `free`, GND pad 8 hidden on pad 3 — and every
  checklist item on it is answered. `TPD4E05U06DQAR` was verified against the
  section 6.6 table of SLVSBO7L Rev. L at the same time: `5.5V` stand-off,
  `6.5V` breakdown minimum and `10nA` leakage maximum all hold. Note for later
  passes, recorded on the part: the PROSE in section 7.3.5 contradicts that
  table, quoting 6 V and 5 V. The table is the authority.
- **Three corrections to the description templates**, `conventions-library`
  v33. The multi-channel ESD array row hard-coded "4-Channel" — right for the
  one part on the row, and a false channel count on the first 6-channel
  sibling; the count is now a literal written per part, the way the SMAJ row
  already treats the direction word, checked against the datasheet's pin table.
  The simple 2-pin TVS clamp row now says why it carries no direction word
  where the SMAJ row below calls that word mandatory: the row is scoped to the
  `D_TVS_Bi` symbol, so every part on it is bidirectional. And the Transistors
  alternation gained `PNP`, which it had never offered; no PNP part is in the
  library yet, so nothing was mis-described.
- **The synced KiCad library is a working copy.** A symbol drawn in the PCM
  package on disk is replaced by the next **Sync 7Sigma Library**, and nothing
  said so. [docs/reference/kicad-integration.md](docs/reference/kicad-integration.md)
  now does.
- **"A cathode bar is never a C" is a footprint rule.** It lives in a
  validator-enforced section with no domain stated, and a symbol's zener glyph
  is a C on purpose. `conventions-footprints` v36 says which layer it governs.
- **Cite an artifact, not a memory.** The skill had named `TPD4E05U06` as the
  precedent for a stacked `NC` pad; a pass that could not find the stack in any
  published version struck it out as fiction. The platform drawing had never
  carried it and the intent had. A precedent now has to name the symbol AND the
  version it was checked against.

## 2026-09-13 — Pin stub length follows the pin NUMBER, not the pin count

`USB_C_Receptacle_USB2.0_16P` kept failing its `sym.geometry` check. It is a
verbatim stock KiCad `Connector:` drawing with 5.08 mm pin stubs, and the
`conventions-symbols` rule said 2.54 mm with one exception, "very high pin
count", recorded against `STM32H573IITxQ` (176 pins). A 17-pin connector did
not qualify, so every verification pass flagged a symbol that was correct.

The rule was keyed on the wrong thing. KiCad draws the pin NUMBER along the
stub, so the stub is the space the number has. Measured with
`kicad-cli sym export svg`, which reports each string's plotted width, at the
1.27 mm house font:

| Pin number | Width | Against a 2.54 mm stub |
|---|---|---|
| `A` | 1.29 mm | fits |
| `B1` | 2.68 mm | 0.14 mm over — accepted |
| `A12` | 3.71 mm | 1.17 mm over — prints into the body |

A survey of all 198 base symbols confirmed pin count was never the driver: 58
carry a length other than 2.54 mm, including `XC6206PxxxMR` (3 pins) and
`LD1117S` (4 pins) at 5.08 mm, and every `Conn_*` symbol at 3.81 mm.

- **`conventions-symbols` v16** replaces the pin-count exception with a
  pin-number-width one: 2.54 mm by default, 5.08 mm when any pin number runs
  to three or more characters — alphanumeric connector designators (`A12`,
  `B12`), BGA coordinates, three-digit numbers. `USB_C_Receptacle_USB2.0_16P`
  is now correct as drawn and no longer needs a geometry finding.
- **New machine check `sym.pin_length`**: every pin in a symbol uses the same
  stub length. The absolute value stays a judgment call on `sym.geometry`,
  where the new three-character rule is now a hint; mixing lengths inside one
  drawing is purely mechanical, and it is what actually goes wrong. Across the
  library it finds two: `LSM6DS3` (2.54 mm on 12 pins, 3.81 mm on 2) and
  `Crystal_GND24_Small` (0.635 mm and 1.27 mm). Neither is changed here.
- **The `sym.pins_grid` check was reading past pins.** Both symbol checks now
  split the source into pin blocks instead of matching `(at …)` straight after
  the `(pin …)` header. The child tokens are not in a fixed order — `LAN8671`
  carries `(hide yes)` before `(at …)`, and that pin was skipped silently, so
  an off-grid hidden pin could have passed. The block scanner is also anchored
  to the start of a line, because `A_S-1WR3` has the text "5-pin SIP (pin 3
  absent)" in its Description and the old shape matched it.

`sym.pin_length` is seeded for new installations. Adding it to the live base
checklist is a manual step in the Skills → Checklists view, and it un-answers
the item on every existing symbol with no backfill, exactly as
`cmp.datasheet_text` did on 2026-08-25.

## 2026-09-13 — A straight-through routing pad is not a `no_connect`

`TPD4E05U06` reported an ERC error as soon as the schematic wired its right-hand
pads. TI builds the TPD family for flow-through routing: pads 6, 7, 9 and 10 of
the DQA package carry no internal connection and sit directly opposite the pin
whose trace they continue, so the board runs one straight trace onto the signal
pad and off the dead pad facing it (1-10, 2-9, 4-7, 5-6). The datasheet says so
in the description column of the pin table, not in the `NC` name alone —
"Not connected; Used for optional straight-through routing. Can be left floating
or grounded" (SLVSBO7L Rev. L p.5) — and draws it in the layout example on p.16.

- **The four pads are now electrical type `free`, not `no_connect`.**
  `no_connect` tells KiCad the pad must never be connected, so the designer's
  pass-through wire raises `no_connect_connected`. Measured on KiCad 10.0.5:
  `no_connect` errors when a wire lands on it, `passive` errors with
  `pin_not_connected` when the design leaves the pads open, and `free` is clean
  both ways. The pass-through is optional per design, so both cases happen and
  `free` is the only correct type. Pin numbers, names, positions and count are
  unchanged. The symbol now verifies `checked` on every item.
- **The rule is written up as `conventions-symbols` v15, section 2.1.** The
  same reading applies to the rest of the TPD family and to any package a
  datasheet calls flow-through. **Superseded the same day** — v15 asked for the
  dead pads to be drawn as separate visible pins, and v17 stacks them instead;
  see the section above.
- **The pin-1 circle came off the symbol.** A symbol carries no pin-1 marker
  since the house rule of 2026-09-13. Pin 1 is named by its printed number, and
  the orientation marker is a footprint job.

## 2026-09-13 — The SMAJ TVS family reads one way

Verifying `SMAJ28A` turned up four things the family had been carrying, none
of them a defect in the part in front of us.

- **Four SMAJ parts printed a part number where the rule asks for a rating.**
  `Value` plus the reference designator is the only part identity printed next
  to a symbol on a schematic sheet, and the house rule sends a TVS to its
  reverse stand-off voltage. `SMAJ28A` had been moved to `28V` on 2026-09-13;
  `SMAJ12A`, `SMAJ24A`, `SMAJ24CA` and `SMAJ28CA` still read as their MPN.
  They now read `12V`, `24V`, `24V` and `28V`. The MPN is untouched on
  `Manufacturer Part Number 1`, which is what the BOM draws from.
  **`SMAJ24CA` is fitted on CE_Aqua_V2 at D12, D13 and D19**, so those three
  refs will print `24V` after the next library sync. Same symbol, same land,
  same netlist, same part ordered.
- **Two TVS base symbols offered through-hole footprints.** `SMAJxxA` and
  `D_TVS_Bi` both carried `ki_fp_filters "TO-???* *_Diode_* *SingleDiode* D_*"`
  on twelve components that are surface-mount without exception. The filter is
  what narrows the footprint chooser, so naming a package the part is not made
  in turns the one control meant to prevent a wrong land into a source of them.
  Both now read `D_*`, which covers every land actually in use — `D_SMA`,
  `D_SOD-123FL`, `D_SOD-323`, `D_0402_1005Metric` — and every stock KiCad
  diode footprint. No pin, graphic or geometry change, so every verification
  carried.
- **`SMAJ12A` simulated a clamp 21% above the part's guaranteed maximum.** Its
  `Sim.Params` carried `RS=0.5`, where the datasheet clamping point (19.9 V at
  20.1 A, breakdown 14.0 V) gives 0.29 Ω — so the model clamped at 24.05 V
  against a guaranteed 19.9 V. `RS=0.3` now puts it at 20.03 V, 0.7% high, and
  back in line with how its siblings were derived (`SMAJ24A` derives 1.05 and
  stores 1.2; `SMAJ28A` derives 1.44 and stores 1.5 — round up, so the model
  errs pessimistic). `CJ` is deliberately untouched on all three: the SMAJ
  datasheet states no junction capacitance, so there is nothing to check the
  existing estimate against and a replacement would be a guess.
- **Both TVS symbols are now findable by what they do.** `D_TVS_Bi` still
  carried `ki_keywords "diode TVS thyrector"` — no unabbreviated
  "transient voltage suppressor", no direction, and no "ESD" or "clamp" even
  though five of its seven components are ESD protection diodes. It now reads
  `diode TVS transient voltage suppressor bidirectional bipolar ESD clamp
  thyrector`, matching the widening `SMAJxxA` got in 2026-08. Direction is the
  word that most needs indexing here: the library holds both kinds on lookalike
  SMAJ part numbers.

`conventions-library` v31 records the direction word as part of the SMAJ
`ki_description` template — all five parts had carried `Unidirectional` /
`Bidirectional` since 2026-08, but the skill's table still showed the row
without it, so the next standardization pass would have stripped it back out.
It also closes the `Value` question with the reason it went unfixed for so
long: a family-wide deviation defends itself, because when every sibling is
wrong the same way, consistency reads as evidence.

## 2026-09-13 — A flagged machine item can be answered

An `auto` checklist item that an agent flagged as wrong rendered read-only in
the verification card. There was no way to accept it, waive it or re-check it
by hand, so the finding sat on the part for ever.

- **The Checked / N/A / Flag buttons now appear on any machine item that
  carries a finding**, `failed` or `flagged`. Before, the card offered them on
  `failed` alone. A machine item that PASSED still offers none — the validator
  owns those.
- **`cmp.datasheet_text` is the item this shows up on.** An agent flags it when
  the archived PDF is only partly searchable, which is a judgement a person has
  to close, not a rule the validator can re-run.
- **Nothing changed in the API.** A human answer has always outranked an
  agent's on any key, and the answer it replaces is still kept as `superseded`,
  so accepting a flag does not erase the description of what was found.
- **A machine item nobody has answered yet is still read-only.** Backfilling
  one still needs the API.
- **The lifecycle pill is drawn the same size as the pills beside it.** It sat
  in a button row, which stretched it to the height of the select next to it
  and pushed the pair out of line. The component detail header also wraps now
  instead of letting a long part number push the pills on top of each other.

## 2026-09-13 — The nano-SIM socket is drawn the size it really is

`7Sigma:nanoSIM_ShouHan_TL6P-H1.35` published an outline of 11.18 x 12.82 mm
for a part that measures 11.00 x 12.30, sitting 0.06 mm off centre. Version 7
redraws it. No copper moved.

- **`F.Fab` and `F.SilkS` now trace the part.** Body 10.0 x 10.4 mm with the
  top-left corner chamfered, four corner legs out to y +/-6.15, two shell tabs
  out to x +/-5.5. The silk used to stand visibly outside the connector in a
  3D render; it no longer does.
- **Two sources agree on the size to a hundredth of a millimetre.** The STEP
  model's own vertices, and the vendor drawing measured at 600 dpi with the
  scale taken from the two mounting-hole centres. The old outline's own commit
  message quoted 11.0 x 12.3 and then published 11.18 x 12.82.
- **The courtyard is symmetric again**, x +/-6.1 by y +/-6.9, and never larger
  than before in any direction, so it cannot raise a new clearance violation on
  a board already laid out.
- **The `F.Fab` pin-1 circle moved inside the outline**, from (2.5, 6.0) to
  (2.5, 4.9).
- **Boards keep their own copy until they are updated from the schematic.**
  CE_Dongle_V3 carries this part; nothing breaks, and the board shows the old
  silkscreen until its owner refreshes it.
- **The land pattern was verified, not changed.** Pad sizes match the drawing
  exactly; every pad and hole position is within 0.10 mm of it, which is the
  0.1 mm grid the house convention asks for. The part's own leads sit inside
  their pads with at least 0.16 mm to spare.
- **`conventions-footprints` v35 drops this footprint from its origin-offset
  list.** The +0.060 recorded there was the centre of the wrong outline, not
  the centre of the part.

## 2026-09-13 — A footprint preview looks like the footprint editor

The pad numbers landed earlier today on a plot: every layer visible, mask and
paste washing the copper mauve, and the numbers in whatever colour was spare.
A preview is meant to be recognisable as the thing KiCad shows, so the render
now matches the footprint editor's own palette and layer visibility.

- **Mask, paste and adhesive are no longer drawn.** They are translucent
  washes over the copper and they turned KiCad's red pads into mauve ones.
  The visible set is the editor's default, passed to `kicad-cli --layers`.
- **Pad numbers are white, holes are the editor's cyan, and the canvas is the
  board background.** A footprint preview now sits on navy, not on the
  schematic grey a symbol uses.
- **Both renderers are told the same thing.** The layer list is decided by the
  api and travels in the render request, so the container obeys and decides
  nothing.
- **`footprint_theme` is `Skyline-7S` instead of empty.** With no theme named,
  kicad-cli falls back to "footprint editor settings" — whatever KiCad config
  the renderer happens to carry — and the hole colour really did differ
  between a developer's Mac and the server.
- **Editing a theme file now re-renders.** The preview cache keyed on the
  theme's NAME, so a colour change left every cached picture showing the old
  palette with no way to ask for a new one. The key carries a digest of the
  theme file.
- **Trap worth knowing: KiCad discards a pure-white layer colour.** A layer
  set to `rgb(255,255,255)` plots in a fallback grey instead. The label layer
  is `rgb(254,254,254)`.

`services/pad_labels.py` is now `services/preview_style.py`: it owns the pad
numbers, the layer list and the re-stacking together.

## 2026-09-13 — A footprint preview prints its pad numbers

Every 2D footprint preview — the footprint page, the component page, the
paste box, both panes of a geometry diff — now carries the pad number on each
pad, the way KiCad's own footprint editor draws it. Reading a pinout off a
preview no longer means counting pins from the pin-1 mark.

- **The numbers are drawn, not guessed.** `kicad-cli` plots no pad numbers, so
  the render path writes one `fp_text` per pad into a COPY of the source and
  renders that. Nothing is stored: the `.kicad_mod` in the mirror, the file
  KiCad downloads and the version history are untouched. A preview is
  therefore no longer a byte-faithful plot of the stored source — read
  `api/app/services/pad_labels.py` before comparing one against it.
- **One number per land.** An exposed pad and its thermal vias share a number
  and are labelled once. Two numbers on one land (USB-C A1/B12) are spread
  along the pad rather than written over each other.
- **Through-hole numbers sit on top of the hole.** KiCad plots drill holes
  last, over everything, so the finished SVG is re-stacked to put the labels
  above them.
- **Existing previews re-render once.** The cache key includes the labels, so
  the first view of each footprint after the update costs one kicad-cli run.

## 2026-09-13 — A footprint or a base symbol can be renamed

Until now a name chosen wrongly was permanent. There was no rename, and
delete-and-recreate was refused while any component version referenced the row
— and would have discarded the version history, the review record and the
production sign-off anyway.

- **Rename moves the name AND every reference to it, in one transaction.** One
  new geometry version carrying the new name, one republished component
  version per component that references it, the `.kicad_mod` moved in the
  mirror, and the stale entries in `categories.defaults` rewritten. On the
  footprint page, under "Rename this footprint"; as the agent tools
  `rename_footprint` and `rename_base_symbol`; over HTTP as
  `POST /api/{footprints,symbols}/{id}/rename`.
- **A rename costs no verification and no sign-off.** The land pattern, the pin
  map, the pinned geometry and the part are unchanged, so both carry. The
  `Footprint` property and `base_component` stay material for every other kind
  of edit — the exemption is a mapping on the one pair being renamed, and it
  has one caller.
- **History keeps the old name.** Superseded versions are immutable and go on
  saying what they published under.
- **A board already laid out keeps the old library id** until its owner updates
  the project from the schematic. The geometry lives in the board file, so
  nothing breaks, but KiCad reports the old id as missing until then.
- **`L_Changjiang_FTC404030S` is now `L_CJIANG_FTC404030S`.** `CJIANG` is the
  canonical manufacturer name decided on 2026-09-13. The old name was also a
  KiCad **stock** filename while our land is not the stock land — stock pads sit
  at ±1.35 mm and ours at ±1.4 mm — so it claimed a Tier 0 identity the copper
  does not support. Affects `CE_Dongle_V3` (L4, L5) and `EVSE_20_CTRL` (L8, L9)
  at their next update from the schematic.
- Reasoning, and the three rejected alternatives:
  [docs/decisions/0012](docs/decisions/0012-rename-a-footprint-or-base-symbol-in-place.md).

## 2026-09-13 — A cathode bar is one straight line, and the validator decides its width

- **The 0.2 mm polarity mark is no longer an accepted FAILURE.** It was a rule
  an agent had to remember, and one had already broken it by narrowing
  `D_SOD-123FL`'s bar. `fp.silk_width` now passes exactly **one** `F.SilkS` line
  at 0.2 mm and fails the rest, so a footprint drawn wholly at 0.2 mm is still
  caught. Both 0.1 mm and 0.2 mm are legal for the mark itself.
- **A cathode bar is a single straight line** — never a C-shaped bracket — with
  both endpoints on the 0.1 mm grid, on or within the courtyard, and at least
  0.1 mm clear of pad copper. Its stroke may overhang the courtyard outline,
  which is thinner; only the line's position matters.
- **Nine footprints corrected.** `D_0402`, `LED_0402`, `LED_0603` and
  `LED_Silverlight_M3535N1` were C-shaped, and the Silverlight bar was two
  overlapping segments. `D_SOD-323` sat off-grid at x = −1.61. `D_SOD-323`,
  `D_SOD-123FL`, `LED_OSRAM_SFH4725AS` and `LED_Silverlight` had bars hanging
  outside the courtyard. `D_0402` and `LED_0402` had endpoints at y = ±0.45.
  Widths were left as drawn.

## 2026-09-13 — Verifying a land: JLC beats a dimension read off a drawing

- **`conventions-footprints` §1 now covers CHECKING a footprint, not only
  creating one.** A pass read "0.60 x 1.40" off a scanned XKB drawing and
  changed `USB_C_Receptacle_XKB`'s rear shield slot to a 1.4 mm drill. The JLC
  land for the same LCSC code uses 1.2999974 — what the footprint already had.
  Reverted. One `easyeda2kicad --lcsc_id=` call answers the whole question, and
  when a scan and JLC disagree, JLC wins.
- **The origin follows the vendor land, not the body centre**, for a connector
  or switch whose body overhangs its pads. Six footprints on this BOM anchor
  that way, from −4.495 mm on the RJ45 to +0.060 mm on the nanoSIM. The
  `fp.origin` checklist item still says "centred on the body" and is what made a
  pass flag a correct footprint.
- **The platform copy and the installed copy use different variables.**
  `${SEVENSIGMA_DIR}/3DModels/…` on the platform is rewritten at PCM package
  time to `${KICAD10_3RD_PARTY}/3dmodels/com_sevensigma_models3d/…`. Converting
  between them is expected in both directions — it is not KiCad corrupting the
  path on save.
- **`CJIANG` is the canonical manufacturer**, added to the table in
  `conventions-library`. `L_Changjiang_FTC404030S` was renamed in place to
  `L_CJIANG_FTC404030S`, carrying its verification across.
- **Accepted deviations recorded rather than "corrected":** the SOT-23 family's
  1.00 mm pitch, the `Crystal_SMD_3225` pads at y = ±0.90, the house chip lands
  under Tier 0 names, and `TS24CA`'s contact placement — all deliberate, all
  now carrying the numbers that prove a later pass does not need to re-derive
  them.

## 2026-09-13 — Every footprint on CE_Dongle_V3 is verified, and a 3D model can finally be measured

All 38 distinct footprints on the CE_Dongle_V3 BOM were checked against their
documentation. Twenty had never been verified at all. Machine-item failures on
that BOM went from nine to zero.

- **`fp.model_fit` is no longer unverifiable.** Every pass before today recorded
  it `skipped`, for want of a tool. `scripts/model-bbox.py` measures a STEP
  model from its own coordinates, and `scripts/footprint-render.py` renders a
  footprint in 3D with `kicad-cli` so a model can be judged by eye. Both are
  now required by `conventions-footprints` v31.
- **Measure vertices, not every point.** A bounding box over every
  `CARTESIAN_POINT` is invalid: a STEP `LINE` carries a reference point that can
  sit far out along its own infinite line. That error produced four false model
  defects in this sweep — a −3578 mm enclosure, an 80 % oversize switch, a 58 mm
  RJ45 and a lightpipe said to have no clearance. All four were withdrawn.
- **Thermal vias were eating their exposed pads.** `VQFN-40` (ESP32-C6) had
  0.00 mm of EP copper outside the via ring, against the 0.2 mm minimum;
  `QFN-16`, both `QFN-56` variants and `QFN-68` were 0.05 mm or less. Cause: the
  via was enlarged to the house 0.6 mm on a 0.3 mm drill while keeping the via
  centres KiCad stock drew for its smaller 0.5/0.2 vias. Rings pulled inward;
  `VQFN-40` also gained the back-side `B.Cu` land that stock carries.
- **Mechanical pads no longer carry pin numbers.** The support tabs on
  `SW_Push…TS24CA` and the steel bracket feet on `SW_Push…TC-6615` are now named
  `MP` instead of `3` and `4`. The bracket numbering is what made SW2 on
  CE_Dongle_V3 electrically dead. No net changes on any existing board.
- **`RJ45_RCH_RC01812`'s model** sat 4.1 mm inside the board. Z offset set to 0.
- **The SOT-23 1.00 mm pitch is a decided house choice**, not the defect three
  separate passes filed it as. Recorded in `conventions-footprints` v31.
- **Section 8 of the footprint conventions was wrong.** It told agents to omit
  `F.CrtYd` on non-electrical parts, relying on a
  `footprint_style.exempt_base_components` list that does not exist in the code.
  `validate_footprint` fails `fp.courtyard_present` unconditionally and never
  reads the rule block. Two agents followed the old text and published
  footprints that failed validation. Corrected in v29.
- **The validator had never run on most of these footprints.** Their versions
  predate the 2026-08-24 validation subsystem, so their twelve machine items
  read as unanswered, which is easy to mistake for passed. Backfilled by
  republishing identical drawings with `force`. Library-wide, 89 of 213
  footprints would fail a machine item today; 76 of those on
  `fp.courtyard_grid`.

## 2026-09-13 — A verification has four answers, and "skipped" is not one

- **`skipped` is retired** (decision
  [0011](docs/decisions/0011-retire-the-skipped-verification-result.md)). It
  meant "this item applies, but I could not verify it". Everybody read it as
  "does not apply" — the job `na` already does — so agents used it to mean "I
  did not re-open the datasheet on this pass", even on items a previous pass had
  verified and that had not changed since.
- **An item nobody can verify is now LEFT UNANSWERED**, which produces the same
  `partial` state `skipped` always did. The verification vocabulary is
  `checked` | `na` | `failed` | `flagged`.
- **What it was costing:** 138 stored skips, every single one carrying reason
  `unstated` because the agent tool never had a reason argument; 45 subjects
  held at `partial` by one; **38 of those with nothing else open**. Most notes
  said only that a datasheet was out of scope for that pass, and several added
  that a prior datasheet-backed check had already confirmed the item.
- **`na` now requires a reason code** — `feature_absent`, `kind_exempt`,
  `waived` or `other` — from an agent or a human. `na` is the answer that closes
  an item, so it is the one that has to justify itself. The machine tier is
  exempt: the validator answers `na` in a dozen places ("no SMD pads", "no
  vias") with a note and no code.
- **Nothing was migrated and no subject changed state.** Stored `skipped` rows
  keep the value, are read as unanswered, and are reported separately on the
  health panel as "Left over from the retired skipped answer", so the open work
  stays visible instead of disappearing.
- The review card drops its Skip button; the health panel's "why items are
  skipped" becomes "why items do not apply".

## 2026-09-13 — A symbol shows every unit, one at a time

- **A multi-unit symbol drew only its first unit, everywhere.** A dual op-amp
  looked like a single one and a 10-bank STM32 showed one bank, on the
  component page, the template page, the review workbench, the change feed and
  the paste box. `kicad-cli sym export svg` plots ONE FILE PER UNIT and has no
  switch to write one file, and every preview took the first of those files.
- **Every symbol preview now carries a ‹ A · 1/10 › pager.** The renderer takes
  `?unit=N` and answers with an `X-Unit-Count` header; one control, shared by
  the preview and the before/after diff panes, reads it. The letter is KiCad's
  own — unit 1 is A, the suffix it prints after the reference as `U7A`.
- **The paste box pages too**, by re-rendering the unsaved text. A `blob:` URL
  carries no headers, so there is nothing else it could read the count from.
- **A single-unit symbol and every footprint are untouched**, URL included:
  `?unit=` is only added past the first unit, so their renders keep their place
  in the browser cache and the server's `immutable` promise.
- **Previews were answering 401 on a dev server.** Only `request()` in `api.ts`
  asked for the session cookie, so the big preview's own `fetch` — and the
  thumbnails, and the paste-box render, and the STEP/IGES viewer — were sent
  cross-origin without it and refused by the default-deny gate. The deployed
  app is same-origin and never showed this.
- **The geometry review workbench drew nothing at all.** Its preview pane sat
  directly in a flex COLUMN, where `.preview-fill`'s `flex: 1` (basis 0) beat
  the `height: 420px` beside it, so the box collapsed to its own 10px of
  padding and border. A symbol or footprint review had no drawing to review.

## 2026-09-13 — Counts stop stacking one digit per line

- **Library health reads again.** Every three-digit count on Reviews → Library
  health wrapped vertically — `162` came out as `1`, `6`, `2` on three lines.
  The cards sit in a `.field-grid`, whose tracks are 200px wide at their
  narrowest, and `dl.kv` pinned its label column at a fixed 150px. That left
  the value column about one character wide, and `overflow-wrap: break-word`
  on `.kv dd` did the rest.
- **The label track gives way now, the value track does not.** `dl.kv` is
  `minmax(0, 150px) minmax(min-content, 1fr)`, so the label shrinks first and a
  number keeps its width. Long prose values still wrap, because `break-word`
  keeps their min-content small. `.num` is `white-space: nowrap` as well — a
  number is one token and must never break.

## 2026-09-13 — A gain gets its prefixes too

- **An op-amp's open-loop gain reads and writes `100k`, `1M`, `10M`.** It has
  no unit, so nothing is printed after the prefix and there is no space before
  it — the way a gain is written on a datasheet. Its form allows 1e2 to 1e7 and
  its own default was already the string `100k`, which nothing parsed.
- **The rule is the form's own, not a list of field names.** A unitless value
  gets prefixes when its scale is LOGARITHMIC, because a form asks for a log
  slider exactly when its value spans decades. Anything linear stays a plain
  box: a dielectric constant of 4.3, an emission coefficient of 1.9, a
  threshold at 0.5 of the rail, twenty points per decade. A future parameter
  opts in by declaring `scale="log"` with no unit, with no frontend edit.
- **Loss tangent is deliberately left alone.** `0.002` could print as `2m`, but
  every fab and every datasheet publishes `Df = 0.02`. The same reasoning keeps
  RKM notation off length fields: a box should not fight the convention the
  number is copied from.

## 2026-09-13 — The simulator's numbers carry their units

- **Capacitance, inductance, voltage, current and time are unit-aware fields
  now.** Every ngspice parameter used to be a plain box with its unit printed
  beside it in grey. A diode's saturation current defaults to `2.5n` and its
  form allows down to 1e-18; a capacitance goes to 1e-15 and a PULSE edge to
  1e-12. Typing those as decimals is the defect the length field was built to
  stop. Nine quantities exist in `si.ts` now, up from four.
- **Three places changed, and no form definition did.**
  `sch_lib.PARAM_FORMS`, `sim_scenario.ANALYSIS_FORMS` and `LiveControl`
  already declared a unit per field, so the part inspector, the run bar and the
  live knobs are driven from what the server already sends. A new parameter
  becomes unit-aware with no frontend edit.
- **ngspice spells mega `MEG`, and a field that ignored that would be wrong by
  a factor of a billion.** To ngspice, `M` is MILLI. Our boxes read `M` as
  mega, because that is what a schematic means and what the resistance box
  beside them already did (user decision). So the two directions use different
  tables: what is already stored is read with ngspice's rule, and what we write
  back always spells mega `MEG`. Verified end to end — typing `1M` into a
  resistor puts `1MEG` in the downloaded `.kicad_sch`.
- **A field with no unit stays a plain box.** An op-amp's open-loop gain is
  `V/V`, an inverter's threshold is `x rail`, a sweep is a point count. A
  prefix on a dimensionless number is nonsense, so `quantityForUnit` returns
  nothing for them and the old control renders.
- **Audited every input in the app first**: 379 controls across 73 files, 228
  of them value fields. The simulator was the whole gap. Copper weight is
  deliberately untouched — it is a preset list mapping an ounce label to
  millimetres, not a typed value — and no temperature or mass input exists.

## 2026-09-12 — The agent instructions moved next to the code they govern

- **`api/CLAUDE.md` was 2764 lines and `web/CLAUDE.md` was 1688.** A `CLAUDE.md`
  in a subdirectory is read when an agent opens a file in that directory, so
  every backend task paid for the frontend rules and every frontend task paid
  for the whole backend. Two files carried the rules for about 70 services, 17
  routers, the simulator, the field solver, the flasher and the sync plugin.
- **There are 17 `CLAUDE.md` files now, and the largest is 510 lines.** Each one
  holds what applies to its own directory: `api/app/services/`,
  `api/app/routers/`, `api/app/services/fieldsolver|flasher|pcm_plugin/`,
  `mcp/`, `web/src/components/`, `web/src/pages/`, `web/src/sim/` and its three
  sub-directories. The root file merged its layout and
  routing tables into one that sends a task to the right file.
- **Long-form topics moved to [docs/reference/](docs/reference/)** — datasheets,
  production economics, the review axis, the projects module, SPICE runs,
  simulation models, PCM packaging, KiCad integration, deployment, the Jaravis
  implementation and two past simulator audits. The nearest `CLAUDE.md` links to
  each page, so a rule is written once and read where it applies.
- **The rules that keep this working are written down and checked.**
  [docs/reference/writing-instruction-files.md](docs/reference/writing-instruction-files.md)
  states the six: a 200-line budget per file, the derivability test, link never
  summarise, put a rule in the narrowest file that covers it, never use `@path`
  imports (they load at launch and defeat the split), and state the current fact
  with no narration of what the file used to say. `scripts/check-docs.py`
  enforces the three a machine can decide — line budget, broken relative links,
  and `@path` imports — and reports 0 errors today.
- **No rule was dropped.** Every line of the three original files is either in a
  new file or is a heading level, a table row or a cross-reference that the move
  itself changed. A link check over all 29 files reports no broken relative
  link.

## 2026-09-12 — The programming log paid for an index nobody used

- **`programming_logs` carried two indexes of 52 MB and only ever read one.**
  The table holds 2,444,307 rows across 6321 runs, the largest row count in the
  database, and it only grows because every line of every run is kept on
  purpose. It had a surrogate `id` primary key beside a unique constraint on
  `(run_id, seq)`. `pg_stat_user_indexes` reported **zero scans, ever**, on the
  `id` index: nothing addresses a log line by anything but its run and its
  sequence, no foreign key pointed at it, and the writer never supplied one.
- **`(run_id, seq)` is the primary key now**, and the table went from 375 MB to
  304 MB — 53 MB of index and 18 MB of row overhead. Nothing was deleted: the
  row count and the run count are unchanged.
- **A startup migration applies it once**, guarded by the presence of the `id`
  column, and reports itself at `GET /api/health/schema` as
  `programming_logs.pk`. It ends in a `VACUUM FULL`, because `DROP COLUMN` only
  marks a column dead in Postgres and the bytes stay until the table is
  rewritten. Measured on the full 2.44 M rows: 0.54 s of DDL and 1.7 s of
  rewrite, which is why it runs at startup rather than in the background.

## 2026-09-12 — The git mirror is the source archive

- **Ingest no longer stores a `source.tar.gz` per snapshot.** It wrote one for
  every commit and nothing ever read it back. The key appeared twice in the
  whole codebase: the write, and a line in a docstring.
- **The mirrors already held the same content, four times smaller.** Measured on
  the server: 16 stored tarballs came to about 950 MB, which was 68% of the
  bucket, while the bare mirrors that hold EVERY commit of EVERY project come to
  214 MB. One project shows the shape of it — 117 MB of mirror against 533 MB of
  tarballs for 8 commits.
- **The first start after this deploy removes the stored tarballs**, in the
  background and behind the marker `maintenance/snapshot-archives-dropped.v1`,
  the same way the schematic render purge works. The bucket should fall to about
  450 MB.
- **`gitrepo.archive_tgz` rebuilds any tree on demand** from the local mirror,
  with no network call. It is now the only way back to a byte-exact tree.
- **`DATA_DIR/git` must be in the backup set.** After the purge the mirror and
  the upstream remote are the only copies of project source. See
  [decision 0009](docs/decisions/0009-the-git-mirror-is-the-source-archive.md).

## 2026-09-12 — One control, one unit rule, and a tooltip that stays on screen

- **Three input designs became one.** Only `.text` ever declared a border,
  background and focus ring; `.row-input` was used bare 83 times and fell through
  to the browser's NATIVE widget, so the Admin page, the table filters and the
  field solver rendered three different-looking forms. One rule now draws every
  text control, and the size classes carry size only — three heights, 34 / 26 /
  22 px, and nothing else varies.
- **Every unit now prints the same way**: the prefix that puts 1-999 before the
  decimal point, at most three decimals. `0.05 Ω` reads `50 mΩ`, `1 560 432 Ω`
  reads `1.56 MΩ` with a warm ⓘ carrying the exact value. Impedance and
  percentage joined length and frequency, so Target Z and tolerance are the same
  control as design frequency. On a resistance `10M` is megohms and `10m` is
  milliohms.
  - Length changed with it: prepreg 3313 now reads `99.4 um` rather than
    `0.0994 mm`. One rule everywhere was judged worth more than matching a
    single datasheet's spelling.
- **`2.4e9` never parsed**, in any unit field, despite the frequency field's own
  help text advertising it — the exponent was read as a unit suffix.
- **The ⓘ moved inside the box, and its tooltip stays on screen.** Beside the
  box the marker took 18 px of the field's width and cut `500 um` to `500 u`;
  the tip itself was anchored `right: 0` and ran off the LEFT edge of the window
  on every field in the solver, measured at x = −132.
- **`4k7` now parses.** RKM notation — the prefix standing in for the decimal
  point — is how values are printed on parts and in schematic Value fields, so
  `4k7`, `4R7`, `1M5` and `2G4` all read correctly. Enabled for impedance and
  frequency only: a length is based on mm, so `1m5` there would mean 1.5 metres
  in a box expecting a fraction of one.
- **Rounding could break its own rule.** 999 999 999 Hz sits below 1 GHz, so it
  was printed in MHz, rounded to three decimals, and came out as `1000 MHz` —
  four digits before the point, which is the one thing the prefix ladder exists
  to prevent. The prefix is now re-picked AFTER rounding: it reads `1 GHz`.
- **Field solver**: coplanar is a segmented Off/On beside Signal rather than a
  checkbox, target Z, tolerance and design frequency share one row (the property
  panel widened to fit the widest legitimate value, `999.999 kHz` at 121 px,
  three across), the structure
  box lost its redundant `mm` column, and the cross-section view is remembered
  PER PROFILE — it used to reuse the previous profile's zoom and centre, which
  "lock view" then made permanent.
- **Stock's held parts are grouped by component**: 120 project-rows became 46
  part-rows, folded to 15, with the boards and reference designators behind each
  row grouped by project.
- **Library health folds its long lists** to two rows plus a count.
- **Admin**: the display currency is a dropdown of the currencies that actually
  have an exchange rate, and its fields fill their column instead of sitting at
  the browser's default 176 px with the placeholder cut off.

## 2026-09-12 — One way to label a field, and Setup becomes Admin

- **Setup is now Admin, and it is the same width as every other page.** It
  carried a 860px cap and was the only page in the app narrower than the rest,
  so the same card rendered at two sizes depending on how you reached it. The
  name follows what the page is: administration of the DEPLOYMENT, now that
  everything belonging to the signed-in person has moved to Account. `/setup`
  redirects to `/admin`.
- **Four competing form styles became one.** `edit-grid`, `user-form`,
  `cred-form` and the field solver's `fs-field` all existed at once, and their
  labels were mono UPPERCASE 11px in one and sans sentence-case 12px in another
  — so a form looked different depending on the page it was on. The field
  solver's shape won, promoted to a shared `<Field>` / `<FieldRow>` /
  `<FieldSet>` and a `.field` CSS family. Every form in the app now labels the
  same way.
- **The two input sizes stay, and are now written down.** `.text` for a standard
  field, `.row-input` for the compact one inside table rows and toolbars. A
  duplicate `select.sel` style was folded into the shared one.

## 2026-09-12 — Git tokens belong to an account, not to each project

- **One revoked token was hiding behind three good copies.** Every project kept
  its own encrypted git token, so four projects on one GitHub account held four
  independent copies of one secret. Three were live and the fourth had been
  revoked, and nothing in the platform compared them — the only symptom was one
  project failing to fetch with `could not read Username`, which reads like a
  terminal bug rather than a refused credential. Decision 0010.
- **Credentials are now named accounts.** Add a token once on the new **Account**
  page — click your name in the top bar — and pick it by name on any project.
  Rotating it is one edit in one place, and two projects on one account can no
  longer disagree about the secret.
- **A project can still carry its own token** for a one-off repository. When both
  are set the account wins, and the project page says which is in force rather
  than only "stored (encrypted)" — that wording is how the stale copy hid.
- **Check tells you whether a credential still works**, before somebody needs it.
  It runs the same `git ls-remote` a real fetch uses, once per project on that
  account, and stores the verdict with its date. A credential nobody has checked
  reads "not checked", never "ok". The refusal message is translated where it is
  shown: "the remote refused this token (expired, revoked, or no access to this
  repository)".
- **The Account page holds everything that is yours, not the deployment's.**
  Your password, your API tokens (create, revoke, and read the value back), your
  git credentials, and the four boxes that used to sit on Setup — Effective
  URLs, the KiCad plugin install, the `.kicad_httplib` download and the Claude
  Code / MCP settings. Every one of those carries YOUR token, so two people must
  see two different strings; Setup keeps the deployment's shared configuration
  and a pointer here.
- **Existing tokens migrate themselves** on first start. Distinct token values
  become one credential each, named after the host and numbered when one host has
  several accounts; rename them to whatever you recognise.

## 2026-09-12 — The snapshot-archive purge checks before it deletes

- **The purge would have destroyed the only copy of one project's source.**
  Decision 0009 stops storing a `source.tar.gz` per snapshot because the git
  mirror holds the same commits for a quarter of the space, and a startup purge
  removes the ones already stored. That is right for three of the four projects
  on the server. Project 3 had no mirror directory, an empty checkout, and a
  remote the platform holds no credential for, so its 102.9 MiB archive was the
  only copy of that tree — and that snapshot is the project's current one and is
  pinned by a production run.
- **The purge now verifies the premise per archive.** `gitrepo.can_rebuild`
  asks whether the commit is still an object in that project's mirror — the
  directory existing is not enough, because a re-clone of a rewritten remote can
  lose a commit. What cannot be rebuilt is kept and logged by key, and the
  completion marker is withheld, so fetching the missing mirror and restarting
  finishes the job. Dry-run against production: 743.9 MiB deleted, 102.9 MiB
  kept.
- **A missing mirror is no longer invisible.** The Projects page announced it
  only for a project with no snapshot, so one that was ingested and later lost
  its mirror looked healthy. It now shows a red `no mirror` pill either way —
  without the mirror nothing can rebuild that tree, and backing up `DATA_DIR/git`
  does not cover it.
- **A failed checkout no longer leaves an empty directory behind.**
  `materialize` created the destination before extracting into it, so a missing
  mirror left a directory that answers `.exists()` and holds nothing; an audit
  counted one as a checkout on disk. It now names the missing mirror instead of
  dying on its `cwd` with a bare `FileNotFoundError`, and removes a half-made
  checkout.

## 2026-09-12 — One symbol viewer, one footprint viewer, one canvas

- **The review workbench drew symbols and footprints on a white card.** Its
  preview asked for `background: var(--paper, #fff)` and `--paper` is defined
  nowhere in the stylesheet, so the fallback always won — in dark theme and in
  light. kicad-cli renders light strokes on a transparent background, so the
  picture needs a dark ground under it, which the other previews supplied and
  this one did not.
- **Every preview now goes through one component**, `GeometryPreview`. There
  were six near-identical `<img>` shells across the component page, the template
  page, the templates list, the review workbench and the paste box, with four
  different missing/error stories and three different canvas colours. The canvas
  is now a single palette entry, `--kicad-canvas`, and a caller's class carries
  the size only.
- **The 2D/3D footprint switch was written twice** — component page and template
  page — and the copies had drifted on which state they remembered. One
  `FootprintPreview` owns it now.
- **A preview that has nothing to show says what is missing.** The templates
  list used to render an em dash, and the review workbench a broken-image icon;
  both now carry the server's own explanation where it sends one.

## 2026-09-12 — Table columns that cut their own pills

- **Every sign-off and review pill in the component browser was cut in half.**
  The columns were 4% wide each, which is 55 px — a pill is `inline-block`, so
  the column's ellipsis cannot shorten it and the word is simply clipped:
  "NOT S…", "CHECK…", "UNREV…". The widths the browser needs were written down
  once, in `styles.css`, with a comment saying 9% fits "not signed"; when the
  page moved to the shared `DataTable` the numbers were re-typed as 4 and the
  CSS was left behind as dead rules. Restored, with the reasoning now next to
  the numbers.
- **The bulk sign-off checkbox had an ellipsis stuck to it.** A checkbox is
  13 px of replaced content in a 3%-wide column with 12 px of padding either
  side, so it overflowed and `text-overflow: ellipsis` drew a "…" beside every
  one. Action columns now clip instead of ellipsising, and take 6 px of padding.
- **Centred columns now have centred headers.** `SIGN-OFF` and `REVIEW` sat
  left of the pills they name. `DataTable` copies `ctr` onto the header cell.
- **Nine more tables re-measured.** Reviews (lifecycle, used-in), Orders (net
  total, invoiced, status), Devices (MAC, project, last seen — and its widths
  summed to 103%), the project BOM (tier, qty/dev), Stock (written off, paid
  unit, market unit), the production overview (cost/dev, margin, sale) and the
  project orders tab (its widths summed to 93%). Every header now fits its
  column, and the only cells that still truncate are free text — manufacturer
  names, reference designator lists, repository URLs — where the full value is
  on hover.
- **Filtering the browser's review column for "issues" found nothing.** The
  pill prints "issues" for a failed check; the filter text said "checks fail".

## 2026-09-12 — Every IC in the library now draws its supply current

- **The amplifiers, comparators and logic gates delivered current to their
  loads and took none from their rails.** A behavioural output stage is a
  controlled source, and a controlled source referenced to node 0 manufactures
  its current out of the ground node; the supply pins were only read, by ideal
  sensors that draw nothing. Measured with an ammeter in every supply leg:
  `sigma_opamp` put 5.00 mA into a 1k load and drew 14 pA from its rail,
  `sigma_rail_buf` put out 3.22 mA and drew exactly zero, and `sigma_ldo`
  delivered 100 mA while drawing only its own 3 mA. Every rail-current,
  decoupling, regulator-loading and efficiency answer from those models was
  wrong. Signal-path answers were not, which is why it lasted: the verdict
  harnesses check signals.
- **Eighteen models corrected, plus one new shared block.** `sigma_supply`
  does the two jobs that belong to whichever block owns the rails: it draws a
  quiescent current from rail to rail, and it moves the stage's output current
  off node 0 and onto the supplies. It carries an RC lag because the
  correction closes a real loop — rail to clamp to output to current — and an
  algebraic one aborts the operating point.
- **Models built from a real switch were always right.** `sigma_ucc27538` and
  `sigma_hss` measured 117 mA and 2.38 A from their supplies, correctly; they
  only needed a quiescent current. The split between the two kinds is
  structural and now recorded in the simulation skill.
- **`IQ` is per channel, not per package.** A composed wrapper shares one
  parameter across every block it holds, so a dual part would charge a package
  figure twice. Divide by the channel count and show the arithmetic in the
  component's `Sim.Params` comment.
- **Nothing in the signal path moved.** Against the old models a corrected
  op-amp matched the closed-loop output and the saturated swing to seven
  digits. All six `EVSE_20_CTRL` harnesses still pass every check — 102 of
  102 — with no convergence trouble. The verdict numbers shift in the fourth
  decimal, in the direction of a rail that now sags under real load.
- **All 34 affected components now carry their own number**, each with the
  datasheet page in its version comment. Five regulators held values that were
  already wrong, one of them by a factor of ten. Three parts are marked
  `placeholder` and say what would confirm them: the negative 12 V regulator,
  whose datasheet publishes no typical at all; the gate driver, whose only
  tabulated bias current is measured below its own turn-on threshold; and the
  buck's efficiency, whose curve in the datasheet is drawn for a sibling
  variant's board.
- **The buck converter conflated two states.** It drew its SHUTDOWN current
  whether enabled or not, and those differ by about an order of magnitude. It
  now follows the enable pin.
- **A component edit does not reach a board that already exists.**
  `Sim.Params` is baked into the project's own schematic, which is a git
  checkout, so a board picks these numbers up only after Tools → Update
  Symbols from Library and a commit. A model edit is different: it reaches
  every snapshot at once. The two halves of this change therefore land at
  different times.

## 2026-09-12 — A run that says how far it has got, and a scope you can zoom

- **The Run button reports real progress, not just "Running…".** ngspice says
  where it is: during a transient it prints the simulated time it has reached.
  The process that owns the solver records that against the transient's own
  stop time, and the browser polls it once a second. The bar names its phase
  too, because reading the schematic through kicad-cli is several seconds
  before the solver starts and a bar frozen at zero reads as a stall.
- **A verdict harness solves its transient TWICE**, which the progress bar
  made visible. The deck's own `.tran` writes the rawfile the scope plots, and
  the `tran` inside `.control` is the run the `meas` verdicts read. Every
  `_sim` project in EVSE_20_CTRL is built that way, so a 720 ms scenario costs
  about 27 s instead of 14 s. The bar counts the sweeps and names which one is
  running, so it stays monotonic instead of reaching 98% and starting again.
- **The scope zooms and pans.** Drag selects a window, as it always did but
  nothing said so. The wheel now zooms about the pointer, shift-wheel and a
  trackpad's horizontal scroll pan, and Reset zoom appears once the view is
  not the whole run. Every pane moves together, because they share one time
  axis and a zoom that moved one of them would break the reading that stacking
  them is for. A new run resets the window.
- **Taller doubles the pane height**, and gives the scope more of the window
  so two tall panes still fit without scrolling. The setting is remembered per
  sheet.

## 2026-09-12 — A mirrored part on its side is placed the way KiCad places it

- **The schematic transform applied `(mirror x|y)` before the rotation. KiCad
  applies it after, in sheet axes.** At 0 degrees the two orders agree, so
  every sheet but one looked right. At 90 or 270 degrees the mirror flipped
  the symbol's own axis, which is the OTHER sheet axis: a mirrored resistor
  lying on its side had pin 1 drawn and connected at pin 2's end, and a
  mirrored zener the wrong way round. CP_PWM carries eight such parts and
  the Simulator reported nine "group touches more than one net" conflicts
  for it. The overlay's `_place`, the server drawing's `placement_matrix`
  and the browser's `matrixOf` all moved together; on the EVSE_20_CTRL
  snapshot every one of 1511 placed pins now sits on the net the kicad-cli
  netlist gives it, and the conflicts are gone. The netlist and the
  simulation were never affected — they come from kicad-cli, not from this
  transform.
- **The "No charge is drawn on N nets" notice counts nets, not wire groups.**
  A power net drawn in several places was listed once per place, so GND
  appeared twice in a list of 19.

## 2026-09-11 — The Board dropdown lists boards, not simulation harnesses

- **A project's Board selector no longer offers its `_sim` projects.**
  `EVSE_20_CTRL` carries six simulation harnesses beside the design, each a
  real `.kicad_pro`, so the project view listed seven "boards" and a project
  with one board and six harnesses showed a dropdown at all. The ingest now
  classifies every discovered project as a `board` or a `harness` from its
  root sheet: a sheet carrying a SPICE directive is a harness. The project
  view, the project list and the BOM/board/schematic tabs show boards only;
  the Simulator keeps listing the harnesses as before. The name suffix is not
  the rule, so a schematic-only design stays a board and a harness is one
  whatever it is called.
- **The Schematic tab gained a Simulation picker.** It lists the design and
  every harness of the snapshot, so a harness sheet is still readable in the
  project view. Simulate and Play live open the harness that is picked. With
  the design picked, they let the Simulator open its first harness instead of
  the design and a "carries no directives" notice.
- **Old snapshots are classified on first read** and the answer is stored, so
  no re-fetch is needed.

## 2026-09-11 — A part with no land pattern stays off the board

- **A cabled antenna, an RF pigtail or an enclosure with no drawn outline is no
  longer pushed onto the PCB.** The generator forced `on_board yes` on every
  part outside the `Simulation` category, so a base symbol's own
  `(on_board no)` was thrown away — `Antenna_Cabled` and `RF_Pigtail` were
  emitted as on-board although both drawings say otherwise, and the note on
  `Antenna_Cabled` claiming this flag prevents a missing-footprint report had
  not been true for any of six parts. A part is now off-board when **the base
  symbol declares `(on_board no)` AND the component has no footprint**. See
  [decision 0005](docs/decisions/0005-off-board-parts.md).
- **Both halves of that rule are load-bearing.** Without the declaration, a
  `Footprint` somebody merely forgot would drop the part off the board in
  silence. Without the footprint test, the 17 terminal-block plugs would drop
  off too: `TERMINAL_BLOCK_PLUG` declares `(on_board no)` while every component
  on it carries the deliberate `TerminalBlock_Plug_Invisible` land, so the next
  *Update PCB from Schematic* would have **deleted those footprints from boards
  that already exist**.
- **One predicate, three readers.** `generator.off_board` is called by the
  mirror, by the KiCad HTTP catalog record (which is what KiCad actually places
  from) and by the validator, so what the validator forgives and what KiCad is
  told cannot drift. `in_bom` is deliberately not derived the same way —
  `RPi_CM5` carries an `(in_bom no)` this library does not mean, and honouring
  it would drop the most expensive line on the board out of every BOM.
- **The validator gained its third footprint-less branch.** It already answered
  `na` for BOM-only and simulation-only parts; an off-board part was the case
  with no branch, so `cmp.required_props` and `cmp.footprint_ref` failed by
  construction on every cabled antenna and pigtail and had to be answered by
  hand. An ordinary part with an empty `Footprint` still fails.
- **Two RF pigtails and a shared symbol.** `BWIPX1-SMA-1.13L100` (C784403,
  I-PEX Gen 1 to SMA female) and `ACA-RFSMA-K TO IPEX1 001` (C22467635, to
  RP-SMA female), on a new 0-pin `RF_Pigtail` base symbol with reference `W`.
  Both are bulkhead types and both mate with an antenna already in the library.
  Gender was confirmed from each manufacturer's own drawing: the Chinese
  `外螺内孔` reads like RP-SMA to an English eye and is a standard SMA jack,
  because the jack carries the external thread and the plug carries the nut.
- **`Enclosure` now declares itself off-board.** This moves only the three
  Italtronic enclosures, which have no footprint; the four Hammond and the
  Takachi parts carry real lands and are untouched. Whether the Italtronic
  three should get their own mechanical footprints is still open
  ([docs/todo.md](docs/todo.md)).
- **RF uses one spelling for VSWR.** The category carried both `V.S.W.R` (four
  on-board antennas) and `VSWR` (four cabled parts) for one quantity, which
  splits any template or parametric filter. All four were renamed; none was
  reviewed or signed, so the rename cost no verification.

## 2026-09-11 — JLC06121H-3313A, and a board file checked against its stackup layer by layer

- **`JLC06121H-3313A` joins the stackup library.** JLCPCB's published 6-layer
  1.2 mm controlled-impedance build, outer 1 oz and inner 0.5 oz: prepreg 3313
  0.0994 mm under each outer layer, a 0.1 mm core under each of those, and
  **three 7628 sheets — 0.2104, 0.218 and 0.2104 mm — in the middle gap**.
  Copper and dielectric sum to 1.1684 mm. The Dk of every sheet was already in
  the material library, so nothing was assumed that the fab does not publish.
  JLCPCB renders the 1.2 mm tables only after a click, which is why the code
  appears nowhere in the page source; the figures were read from the rendered
  page on 11 September 2026.
- **The project Stackup tab now says WHERE the board file and the assigned
  stackup disagree**, not only that they do. Both sides are reduced to the same
  normal form — the ordered copper layers, and the dielectric GAP between each
  neighbouring pair — and every copper thickness, gap thickness, sheet
  thickness, Dk and loss tangent is compared, each with its own verdict.
  Inside tolerance counts as the same: copper 0.005 mm, dielectric 0.02 mm, Dk
  0.05, loss tangent 0.002.
- **Why the gap and not the layer.** KiCad allows only `copper - 1` dielectric
  layers, so a fab gap built from three prepreg sheets becomes one KiCad
  dielectric carrying three sub-layers, written with the bare `addsublayer`
  token. Counting `(layer …)` nodes could therefore never agree with the fab's
  own table, and the old reader returned the first sheet of such a layer and
  silently lost the rest. What a field sees is the gap.
- **"No stackup in the file" and "the checkout is gone" no longer look the
  same.** The board file was read inside a bare `except`, so a pruned mirror
  reported the board as declaring no stackup of its own. The page now states
  which of the two happened, and what to do about it.
- `total_mm` of a board file is now the copper-plus-dielectric build, the way a
  fab states a stackup; the solder mask is reported separately as `mask_mm`.
  The two sides describe a mask differently and are not compared on it.
- The agent tool `fieldsolver_board` returns the same table as `comparison`.

## 2026-09-11 — One stackup table everywhere, a stackup that is electrical only, and a board that has a colour

- **`JLC06121H-3313A` joins the stackup library** — JLCPCB's published 6-layer
  1.2 mm build, with **three 7628 sheets in the middle gap** (0.2104, 0.218,
  0.2104 mm). 1.1684 mm of copper and dielectric. JLCPCB renders its 1.2 mm
  tables only after a click, which is why the code appears nowhere in the page
  source; the figures were read from the rendered page.
- **EVSE_20_CTRL is built to it.** The board file carried a placeholder — FR4 at
  Er 4.5 everywhere, prepreg 0.1 mm, core 0.35 mm — that no fab states, so no
  width solved against it would have been the width the board gets.
- **One stackup table, everywhere** (`web/src/components/StackupTable.tsx`):
  the project comparison, the field solver and the stackup editor all draw the
  same colour-coded, top-to-bottom rows, aligned by one backend function so the
  picture cannot disagree with the verdict.
- **The board-file check is layer by layer.** It compared two things — copper
  count and total thickness — so a board could carry the wrong laminate in every
  gap and read as agreeing. Now every copper thickness, dielectric gap, sheet,
  Dk and loss tangent has its own verdict, plus solder mask ink thickness and Dk
  and the presence of a legend, each against a published figure.
- **KiCad sub-layers are read.** A fab gap of three prepreg sheets is one KiCad
  dielectric carrying `addsublayer` groups; the old reader took the first
  `(thickness)` and silently lost the rest. `total_mm` also counted the solder
  mask, which a fab stackup does not, so every comparison was 0.02 mm out.
- **"No stackup in the file" and "the checkout is gone" no longer look the
  same** — the board file was read inside a bare `except`.
- **A stackup is electrical only**
  ([decision 0008](docs/decisions/0008-a-stackup-is-electrical-only.md)). Board
  **colour is project data**, versioned like the assignment, chosen from
  JLCPCB's own list with the legend following the mask; picking one writes
  nothing to the library. Outer layers are **per face**, so a board can carry
  legend or a different finish on one side. Copper is named `L1`…`Ln` by
  position and dielectric labels are generated — neither is typed — and a save
  that would put **copper against copper is refused**.
- **Impedance profiles survive a refresh** (`field_workspaces`, one row per
  person) and are banked **per stackup**: switching parks the open set and picks
  up the other, because a profile's cells are keyed by copper layer name.
  Saving to a board is **all-or-nothing** and refuses a stackup mismatch,
  server-side. Removing a profile, a stackup or a rule set now asks first.
- **The solder mask is drawn as one object.** It arrives as several overlapping
  rectangles and each was filled with a translucent green, so every overlap
  doubled the alpha — three different greens, darkest where two met, and a
  coplanar ground that looked mis-drawn.
- **Numbers carry their unit** (`SiInput`): type `35um`, `0.035`, `1.4mil`,
  `2.4GHz`. Copper thickness is checked against the foils that exist and the
  weight is read off it. The mask over a trace is derived as half the figure
  over the substrate — subtracting the copper gives −4.5 µm on JLCPCB's own
  published pair.
- **Every modal locks the page behind it, closes on Escape and on a click
  outside** (`web/src/components/modal.ts`). Escape is bound on the document:
  on the backdrop it only fires once focus is inside, which is why dialogs had
  to focus themselves to be dismissable at all.

## 2026-09-10 — Datasheets stored once, versioned by text; re-signed PDFs no longer bump parts

- **One stored file per distinct content.** Datasheet bytes moved from
  `datasheet_versions` into a content-addressed `documents` table; a version
  is now a history row that points at a document, and two components that
  link the same PDF share one copy (24 files were shared between parts, the
  TPS7A20 variants among them). The page index follows the document, so a
  shared file is indexed once. The move ran at startup in SQL and rewrote the
  tables, which handed the disk back
  ([decision 0004](docs/decisions/0004-datasheet-identity-and-storage.md)).
- **A new version means the text changed.** TI re-signs every PDF about every
  two days and generates the whole tail of the document at download time, so
  one TPS61023 datasheet had 37 stored copies, each of which bumped the
  component to a new version and dropped its verification. The identity is
  now a hash of the page text with a role per page: the body in order, the
  orderable-part table reduced to its part-number and lifecycle pairs, the
  drawings as an unordered set, the live tape-and-reel tables excluded. On a
  copy of the production library that took 704 versions down to 616 and 557
  stored files down to 484, and every difference left is real. A re-signed
  file answers `restamped` and stores nothing. The revision label parsed from
  the document ("Rev. B", "SLVSF14B") shows on the datasheet card and in the
  history.
- **A real revision is a review event.** The automatic bump now runs through
  the shared publish path; the review record does not carry across a
  datasheet whose text changed (the sign-off does), and a review request is
  opened with the revision labels, the pages that are new or edited, how many
  drawings were removed, and whether the orderable-part table moved.
- **A stored web page is no longer counted as an unsearchable datasheet.**
  LCSC serves its "document not available" page as `C10425.pdf` with
  `Content-Type: text/html`; the leading bytes now decide what a file is, so
  186 such pages moved from `scan` to `none`. One of them is a current copy
  and needs a real datasheet.
- **The fetcher learns which user agent a host accepts.** Infineon and
  Nexperia refuse `curl` and serve a browser string; onsemi does the reverse.
  A refusal retries with the other string and the answer is remembered per
  host. The 11 empty Infineon downloads in the audit log were this.
- **A saved URL is fetched at once**, not at the nightly run.
- **Clean-up endpoints.** `GET /api/datasheets/restamps` lists the history
  the byte rule wrote; `POST /api/datasheets/restamps/collapse` folds it into
  the surviving version and drops the orphaned files.

## 2026-09-10 — Sync plugin 1.5.0 owns library updates; HTTP catalog every 2 minutes

- **Sync plugin 1.5.0 records what it installed in the Plugin and Content
  Manager.** The PCM decides "update available" from its own record,
  `installed_packages.json`, and only its dialog writes it — so a library the
  Sync button had already refreshed still showed a badge on every start, and
  Update All re-downloaded the 259 MB models zip the delta had delivered.
  After a successful sync the library and 3D-model packages are recorded at
  the served version and pinned, KiCad's own switch for "updated elsewhere":
  no badge, no Update All, a manual Update still in the menu. The plugin
  package is left alone and still updates through the PCM. KiCad reads the
  record at start-up and writes its in-memory copy back when the PCM dialog
  closes, so a dialog closed later in the same session can restore the old
  versions; the next sync corrects them. The closing notification now also
  says that placed parts are copies (Tools → Update Footprints / Symbols from
  Library).
- **KiCad re-fetches the part catalog every 2 minutes instead of every hour.**
  The `.kicad_httplib` now carries `timeout_categories_seconds` and
  `timeout_parts_seconds` of 120. KiCad 10 refreshes the catalog in a
  background thread every `max` of the two, and no menu action, IPC command or
  plugin can force it, so the interval is the only lever. A published
  footprint or field change reaches the symbol chooser within two minutes;
  one refresh costs 17 requests and about 44 kB on the wire. The values are
  embedded in the file: download `7Sigma.kicad_httplib` again from Setup and
  replace the installed copy.

## 2026-09-10 — Built means finished and passed; the Aqua history, again

- **The shelf no longer holds units nobody can pick up.** Stock per batch used
  to add the quantity typed on the production run to the devices recorded in
  it, which claimed 118 units that exist in no record and $1,700 at cost —
  four on Dongle Batch 1 against 521 real devices, 44 on Batch 3, 67 on Aqua
  Batch 5 — while two other batches read as 113 and 47 units "overdrawn". A
  batch that has any device record is now counted from its devices and from
  nothing else; the typed quantity rides along as `qty_recorded` so a wrong
  run quantity stays visible. Only a batch with **no** device records at all,
  which is the V3 prototype runs, is still counted from its quantity, and that
  is the one remaining source of an unserialized unit. See
  [decision 0007](docs/decisions/0007-built-means-finished-and-passed.md),
  which overrides item 8 of [decision 0003](docs/decisions/0003-orders-shipments-and-device-history.md).
- **A board that never passed is not stock.** The retro import had written a
  `produced` event for every imported device, failed ones included, so 82
  boards whose newest programming or test run failed sat on the shelf and
  could be picked for a shipment. They are unbuilt until a later run passes.
  Production after the pass: dongles 4,429 passed, 4,366 shipped, 63 on the
  shelf; Aqua 914, 867, 47.
- **Every built batch stays on the shelf card.** The card selected rows by what
  was left on them, so the moment `built` started counting passed devices, six
  of seven dongle batches vanished — everything they held had shipped. The
  filter now drops planned batches and keeps the rest, and **Recorded sits next
  to Built**: a row is marked when built is above recorded, which is impossible
  rather than merely unlucky. Dongle Batch 5 is recorded as 455 boards and has
  568 devices, Batch 6 as 945 against 992. Under-building is ordinary attrition
  and is not marked.
- **347 more Aqua units were filed under the dongle.** The July re-attribution
  used the functional test and the pushed GPIO template and called an untested
  Aqua indistinguishable. It is not: every config report carries the device's
  own `INFO1` line, `"Module":"CE_Aqua"` or `"Module":"CE_Dongle_v2"`. The
  signal agrees with the test everywhere the two overlap — none of the 4,121
  Module=Dongle devices ever ran the Aqua test, and all 584 Aqua-tested devices
  are Module=Aqua.
- **77 boards had two records each.** The 2025-11-05 firmware names a device by
  its full MAC where earlier builds used the last three bytes, so a board
  re-flashed after that date appeared as both `dongle_<6 hex>` and
  `dongle_<12 hex>`. They are merged into the older record. One pair survived
  the merge: `8BD26C` and `78:42:1C:8B:D2:6C` are a genuine three-byte
  collision between two products.
- **Two Aqua batches had been sold twice.** The run migration turned the build
  quantity of runs 12 and 13 into orders of 315 and 200 units that no invoice
  covers, on top of the real Aqua sales. Both orders are gone and the runs'
  sale columns are blank, so the idempotent migration cannot recreate them.
- Scripts: `docs/flasher/fix_aqua_attribution_2.py` and
  `docs/flasher/fix_built_is_passed.py`, both dry-run by default. The reasoning
  and the numbers are in `docs/flasher/design.md`.

## 2026-09-07 — Order page layout, device list sorting, sort hints

- **Sync plugin 1.4.1 quarantines the duplicates iCloud makes at install.**
  A PCM install into an iCloud folder can leave a `7Sigma_Base 2.kicad_sym`
  (the previous library) beside the real one. KiCad registers it as a second
  symbol library and the sync plugin, which has no baseline for it, listed
  every symbol in it as "only here — never sent" (153 rows on 2026-09-06).
  The sweep that runs at the start of every sync now handles duplicate
  files as well as folders: empty folders are deleted, anything with content
  is moved to `strays/<timestamp>/` inside the plugin folder, and the dead
  `sym-lib-table` / `fp-lib-table` rows go with it. Nothing is deleted. The
  sweep itself, from 2026-08-27, never reached installed plugins because that
  change did not bump `PLUGIN_VERSION`; this one does.
- **`list_footprints` finds a shared land by any package name it serves.**
  The agent tool matches the query against a footprint's `tags`, `descr`
  and hidden `Equivalent Packages` property as well as its name, and a hit
  made that way says which field matched and quotes it. Searching "WQFN-16"
  or "LFCSP-16" now returns the QFN-16 3x3 mm land those packages share
  (conventions-footprints v27, §1), instead of nothing.
- **Order page**: the products, invoices and shipments tables size their
  columns to the content and scroll inside the card instead of clipping;
  under 1700 px the tables take the full width with the two short cards
  beneath. Notes is a full-width row of the order form.
- **Devices list**: Project, Batch and Runs sort and filter on the server,
  and a Where column shows the device state (in stock, shipped, …). The
  batch shown is the one the orders side linked to the device.
- **Every sortable header** shows a faint sort glyph and the whole header
  cell is the click target — before, the title alone was the button and
  nothing marked it as one.

## 2026-09-06 — Orders in the project window, demand, decided JLC orders

- **Orders tab** on every project, next to Batches: one row per order line
  for that project's products, with the order's status and a link to it.
- **Demand card** on the Orders page and at the top of the Orders tab: open
  order quantity against devices on the shelf and the quantity of planned
  batches, with the shortfall or the surplus. `GET /api/demand`.
- **A JLC import decision now overrides JLC's cached panel count.** Before,
  an order decided as 4-up kept showing JLC's 1-up count in the queue and in
  the run-fill check (Batch 8: 200 devices and "short" against 800). The
  queue shows a decided order as decided, keeps JLC's own factor for
  reference, and names the parts JLC sourced from its own stock, which the
  BOM vote cannot see.

## 2026-09-03 — Sales orders, shipments and a per-device history

Decision record [0003](docs/decisions/0003-orders-shipments-and-device-history.md).
A sale is no longer a set of columns on a production run.

- **Customers and orders** are tables: an order holds one line per product,
  so an Aqua and a dongle sit on one order. Status (open / partial /
  fulfilled) follows the shipments and is never set by hand.
- **Invoices per order**: proforma, advance, final, correction. Advance +
  final + correction should equal the net total; the page warns, nothing
  blocks. Due date defaults to issue + the customer's terms. Revenue converts
  per invoice at the invoice date.
- **Every device has a history**: produced in a batch, shipped on an order,
  returned, repaired, replaced, disposed of. The flasher writes the first
  event on the first pass in a batch. Finished-device stock is a count of
  devices on the shelf per batch, valued at the batch's actual per-device
  cost; batches from before device records are counted from the batch
  quantity ("without a serial").
- **Shipping draws oldest-first** from the batches the user ticks, or takes
  pasted device IDs. A return against a device FIFO never picked swaps it in
  and puts the guessed device back. A warranty replacement is charged to the
  original order, so an order with three replacements shows the cost of
  503 devices against the revenue of 500.
- **Migration at startup**: each run with a price became an order line and
  one unserialized delivery; runs sharing an order reference share the order.
  The run's own sale columns stay for the register, whose figures do not move.
- New: Production → Orders, an order page, "Where it is" on every device page.

## 2026-08-31 — Field solver

Controlled-impedance geometry moved from the standalone prototype into the
platform, as **Simulator → Field solver**. A 2D quasi-TEM FEM solver for
microstrip, stripline, coplanar and differential lines with via fences, checked
against closed forms (microstrip Hammerstad-Jensen 0.6 %, stripline Wheeler
0.1 %, CPWG conformal 2.5 %) and against JLCPCB's own calculator.

- Stackups and production rules are library data in Postgres. Stackups are
  written by administrators only; anybody may assign one to a board.
- A board's stackup and its impedance profiles are commit-versioned like the
  cost plan: assigned at a commit, carried forward until changed. Changing the
  stackup keeps every profile and result and marks the results outdated.
- The board file and the assigned stackup may disagree; the difference is
  reported, nothing is blocked.
- The sweep is floored at 1 MHz — below that a perfect conductor stops
  describing a real board.
- `triangle`, the mesher, is licensed for personal and research use only and
  must be replaced before any commercial release.
- The solver runs on both architectures. amd64 installs the mesher's wheel;
  arm64 has no wheel published, so the image builds the same version from the
  upstream git tag. The two builds agree on Z0 to 0.0013 % and produce meshes
  that differ by about 3 % in node count.
- The server VM went from 2 cores and 8 GB to 8 cores and 16 GB, and from a
  `x86-64-v2-AES` CPU model, which has no AVX at all, to `host`. A geometry
  search that took 21.1 s takes 8.2 s. The api container's memory ceiling rose
  from 1500 MB to 6 GB to hold six solver workers.

This file starts on 2026-08-28. For earlier work, read the git history.

Each entry says what changed and why. Put a note here when a change alters how
the platform behaves in production, not for every commit.

## 2026-08-29

### Added

- **A package simulation wrapper is now built from blocks, not written.** KiCad
  netlists one element per reference designator, so the subcircuit `Sim.Name`
  points at is always package-level. Those wrappers were typed by hand, one per
  part, and nine of the sixty-five models in the library held no behaviour at
  all — two instance lines and a parameter pass-through. Two of them,
  `sigma_74hc21` and `sigma_buf2`, were written, linked to nothing, and never
  noticed. A symbol's link now stores a block design and the platform generates
  the `.subckt` from it. See
  [decision 0001](docs/decisions/0001-generate-package-sim-wrappers-from-blocks.md).

  The rule that shapes it is one wrapper port per unique symbol pin, never
  fewer. Two pins are never merged onto one port, because the schematic may put
  them on different nets and one port carries one node. The result is that the
  port list is `p1 p2 p4 …` by construction, so **`Sim.Pins` is derived and can
  no longer be mis-authored** — the swapped pair that `validate_pin_map` admits
  it cannot catch is not expressible in this mode.

### Changed

- **Eleven symbols moved to composed models and thirteen hand-written wrappers
  were deleted.** The conversion preserved every wrapper's interface, so no
  component's `Sim.Params` row moved: `cli/simrecompose.py apply --verify`
  reported 0 lost parameters and 0 moved defaults. Checked under ngspice
  against the deployed library, the composed wrapper beside the hand-written
  one on the same stimulus: `v(y1) = v(o1) = 3.283582 V`, `v(y2) = v(o2) = 0 V`.

- **Nine superseded simulation primitives were deleted**: `sigma_and4`,
  `sigma_buf`, `sigma_buf_3st`, `sigma_dff`, `sigma_dff_r`, `sigma_dff_sr`,
  `sigma_inv`, `sigma_monostable` and `sigma_iso7721`. Each has a
  `sigma_rail_*` equivalent that reads its own supply pins at run time, and
  every one of those is in use. The library holds 54 models, from 65.

### Fixed

- **The rail check no longer reports correctly wired supplies as miswired.** It
  failed sixteen links, and all sixteen were right. Its list of rail port names
  held eleven entries, so `vdd1`, `gnd2`, `vcc1`, `vinp`, `vinn` and `vs` were
  not rails as far as it knew; rail ports are matched by shape now.

  The second half of the check is deleted rather than widened. "A `power_in`
  pin on a port that is not rail-shaped" cannot tell an LDO's `in` from an
  op-amp's `in+`, because the difference lives in the model and not in the
  name. It reported ten LDOs, three DC/DC bricks, an isolator, a high-side
  switch and a flip-flop whose `pren` is tied high because it has no preset —
  and not one real fault. Nothing is lost: each port takes exactly one pin, so
  a supply pin landing on a signal port displaces another pin onto the real
  rail port, and that pin is not a power pin, which is what the surviving half
  tests. All 62 simulation links now validate clean.

- **Generated text is emitted in a fixed order.** `SimModelVersion.parsed` and
  `SymbolSimLink.composition` are JSONB, and Postgres reorders an object's
  keys, so a dict iterated in the session that wrote it gives one order and the
  same dict read back gives another. A wrapper therefore differed from itself
  across a round trip, and the mirror withheld the `Sim.*` fields of
  `74LVC1G175GW,125` over a moved word in a comment. Any list the composer
  derives from a dict is now ordered explicitly.

## 2026-08-28

### Fixed

- **The API no longer exhausts the server.** The `kicadlib-api` container held
  4.8 GB of memory (1.8 GB resident and 3.0 GB in swap) on an 8 GB host, and it
  peaked at 6.0 GB. The kernel killed it four times in August (18 August, and
  three times on 23 August), each time at 6.9 GB to 7.5 GB. The kill was a
  global out-of-memory event, so it also damaged the unrelated stacks on the
  same machine. Four defects caused this:

  1. `datasheet_pages.index_one` started one thread for each stored datasheet
     version and limited nothing. One `pymupdf4llm` extraction uses 400 MB to
     450 MB at peak, even for a document of 10 pages. The nightly re-check
     walks all 678 datasheets, so many extractions ran together. A
     `BoundedSemaphore(1)` now permits one extraction at a time. Extraction is
     CPU-bound and the host has 2 cores, so the threads never ran in parallel.
     They only held memory together.
  2. glibc kept the freed memory. The process held 67 malloc heaps of 64 MB,
     which is 4.2 GB of arena, for approximately 48 MB of live objects. The
     image now sets `MALLOC_ARENA_MAX=2`, and the new `services/memory.py`
     calls `malloc_trim(0)` after each large document. Both halves are
     necessary. A measurement on the real corpus shows 16 documents plateau at
     636 MB with 2 arenas, instead of a continuous climb.
  3. No container had a memory limit, so a fault in one container became a
     fault of the whole host. The api service now sets `mem_limit: 1500m` and
     `memswap_limit: 1500m`. A regression now restarts one container instead
     of stopping the machine.
  4. Datasheet versions 367 and 368 failed to index on every boot, for ever.
     `pymupdf4llm` returns lone UTF-16 surrogates for some malformed CID fonts.
     Postgres refuses them, and the error arrived after the guard that stamps
     `pages_indexed_at`. The two documents therefore repeated approximately
     900 MB of extraction at each start. `_drop_surrogates` now removes these
     characters. A lone surrogate carries no text, so this loses nothing.

### Changed

- `mirror.write_manifest` hashes each file in blocks of 1 MB. Before, it read
  each file complete. This is a small improvement, and it is not the cause of
  the memory fault above.
