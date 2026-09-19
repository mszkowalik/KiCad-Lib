# CE_Dongle_V2 stock reconciliation — working file

**Applied 2026-09-18.** What was assembled, what was programmed, what was
shipped and what is still here.

These figures are no longer a proposal: `scripts/rebuild-dongle-device-history.py`
wrote them into the platform, and the reasoning is in
[0036](../decisions/0036-the-dongle-device-log-is-rebuilt-from-the-facts.md).
The page is kept because it is the only record of HOW the facts were
established — the bench search, the cascade, the cross-check against the
reports — and the "Open" questions at the bottom are still open.

Figures read from production on **2026-09-18**.

**This page records FACTS about devices and orders.** It deliberately does not
describe how the platform stores or corrects them. Where the platform disagrees
with a fact here, the fact wins and the platform is what needs changing.

## Ground truth

Stated by the person who ran the production. These outrank every computed
figure.

| Fact | Consequence |
|---|---|
| Only PROGRAMMING DATA is trustworthy. JLC counts and platform quantities are not | A batch's real output is its device records |
| Batch 1: JLC assembled 525, 521 were programmed | 4 boards never programmed |
| The 32 old-button units were kept back and NEVER SENT. They are still on the shelf | They are stock, not scrap, and never reached a customer. The decision not to ship them was taken 2026-09-17 |
| Order 1 went out as TWO deliveries: 489 from Batch 1, then 11 more once Batch 2 arrived | Order 1 is whole at 500 |
| 191 devices left in one delivery on 2026-09-03 | The quantity is fact. WHICH devices is unknown and must not be invented |
| Every order up to 17 was delivered in full; 17 and 19 remain open | Shortfalls are gaps in the records, not in deliveries |

## Batches

`Assembled` is what JLC invoiced and is context only — it can count bare boards
(see Traps). `Programmed` counts device records and is the number to trust.

| Batch | JLC invoice | Assembled | Programmed | Shipped | Held | Scrapped | Never programmed | Programming window |
|---|---|---|---|---|---|---|---|---|
| Batch 1 | 2024-05-18 | 525 | 521 | 489 | **32** | 0 | 4 | 2024-06-10 .. 07-09 |
| Batch 2 | 2024-09-30 | 350 | 349 | 349 | 0 | 0 | 1 | 2024-10-05 .. 10-09 |
| Batch 3 | 2024-10-28 | 450 | 406 | 406 | 0 | 0 | **44** | 2024-11-16 .. 12-15 |
| Batch 4 | 2025-03-31 | 600 | 599 | 599 | 0 | 0 | 1 | 2025-04-09 .. 04-26 |
| Batch 5 | 2025-08-11 | 600 | 568 | 568 | 0 | 0 | **32** | 2025-08-22 .. 08-29 |
| Batch 6 | 2025-11-05 | 1000 | 992 | 992 | 0 | 0 | 8 | 2025-12-22 .. 2026-01-07 |
| Batch 7 | 2026-05-28 | 1000 | 1025 | 1024 | 0 | 1 | **−25** | 2026-04-17 .. 09-17 |
| **TOTAL** | | **4525** | **4460** | **4427** | **32** | **1** | **65** |

Three further devices failed and belong to no batch.

**Batch 8 is excluded on purpose.** Its 800 boards were invoiced 2026-09-03 and
none is programmed, so it adds a large number that answers nothing. Bring it
back when the clean-up is done.

**Batch 7's −25 is not overproduction.** Boards left over from earlier batches
were programmed under its label, 28 of them on 2026-09-17.

### Every programmed device, accounted for

| | Devices |
|---|---|
| Shipped to customers | 4427 |
| **Held in stock** — old-button Batch 1 units | **32** |
| Scrapped — one Batch 7 unit, dead USB port | 1 |
| Failed, never assigned to a batch | 3 |
| **Total device records** | **4463** |

4463 = the 4460 in Batches 1–7 plus 3 unbatched failures. **Stock today is 32**,
none of it sellable.

### The 32 held units are named

They are individually identified, so nothing about order 1 needs an unnamed
unit. All 32 were programmed in Batch 1 and are on the shelf today:

```
846DE8  846DF4  846E44  846F70  846FE4  9E4E50  9E4ECC  9E4EF4
9E4F24  9E4FE0  9E5018  9E5044  9E50F0  9E510C  9E5118  9E516C
9E5174  9E5184  9E51E8  9E524C  9E5298  9E52AC  9E52B0  9E52C8
9E52D4  9E52FC  9E5300  9E5318  9E53AC  9E5604  9E5628  9E6DCC
```

The arithmetic closes exactly, which is what makes this certain:

| | Devices |
|---|---|
| Batch 1 programmed | 521 |
| Shipped to order 1 on 2024-07-21 | 489 |
| Held back, never shipped | 32 |
| **489 + 32** | **521** |

## Orders

Sourced by the cascade below. Order 1's composition is the user's own account,
which the cascade reproduces independently.

| Order | Reference | Invoiced | Named devices | Unidentified | Delivered | Owed |
|---|---|---|---|---|---|---|
| 12 | PROFORMA 1/11/2023 | 15 | 0 | 15 | 15 | 0 |
| 13 | FV 01/02/2024 | 20 | 0 | 20 | 20 | 0 |
| 1 | ZAL 01/04/2024 | 500 | 500 (489 B1 + 11 B2) | 0 | 500 | 0 |
| 2 | FV 1/10/2024 | 300 | 300 (B2) | 0 | 300 | 0 |
| 7 | ZAL 00001/10/2024 | 420 | 420 (38 B2 + 382 B3) | 0 | 420 | 0 |
| 8 | ZAL 00001/03/2025 | 500 | 500 (24 B3 + 476 B4) | 0 | 500 | 0 |
| 9 | ZAL 00001/07/2025 | 455 | 455 (123 B4 + 332 B5) | 0 | 455 | 0 |
| 10 | ZAL 00001/09/2025 | 1000 | 1000 (236 B5 + 764 B6) | 0 | 1000 | 0 |
| 11 | ZAL 00001/03/2026 | 500 | 500 (228 B6 + 272 B7) | 0 | 500 | 0 |
| 16 | ZAL 00001/04/2026 | 500 | 500 (B7) | 0 | 500 | 0 |
| 17 | ZAL 00001/08/2026 | 300 | **252** | **40** | 292 | **8** |
| 19 | ZAL 00001/09/2026 | 500 | 0 | 0 | 0 | 500 |
| | **TOTAL** | **5010** | **4427** | **75** | **4502** | **508** |

Invoices carry amounts, not quantities, and every closed order is invoiced to
the last złoty, so the invoiced quantity IS the order quantity.

### The 75 unidentified units are two different things

| Where | Units | What it is |
|---|---|---|
| Orders 12 and 13 | 35 | prototypes from before any batch existed. Real deliveries; no records were ever kept. **Legitimate** |
| Order 17, 2026-09-03 | 40 | 191 physically left, only 151 can be named. **A real gap in the records** |

## Deliveries

| Date | Order | Units | What is known |
|---|---|---|---|
| 2023-11-30 | 12 | 15 | prototypes, no serials recorded |
| 2024-02-16 | 13 | 20 | prototypes, no serials recorded |
| 2024-07-21 | 1 | 489 | Batch 1, all named |
| after 2024-10-05 | 1 | 11 | Batch 2, once it arrived — the remainder of order 1 |
| 2024-10-16 | 2 | 300 | Batch 2 |
| 2024-11-30 | 7 | 420 | Batch 2 and 3 |
| 2025-04-30 | 8 | 500 | Batch 3 and 4 |
| 2025-09-29 | 9 | 455 | Batch 4 and 5 |
| 2025-12-30 | 10 | 1000 | Batch 5 and 6 |
| 2026-07-09 | 11 | 500 | Batch 6 and 7 |
| 2026-07-09 | 16 | 500 | Batch 7 |
| **2026-09-03** | 17 | **191** | Batch 7. 151 can be named, **40 cannot** |
| 2026-09-17 | 17 | 67 | serials scanned, certain |
| 2026-09-18 | 17 | 34 | serials scanned, certain |

Only the last two deliveries had their contents scanned. Every earlier
attribution of a device to an order is inference, not observation.

## Which batch supplied which order

Derived from programming dates alone, oldest first, with the 101 scanned serials
pinned to order 17 and the 33 never-delivered units excluded — the 32 held plus
the one scrapped. The pool is the 4326 devices that were available to ship.

**This reproduces the user's account of order 1 — 489 from Batch 1 and 11 from
Batch 2 — without being told it.** That is the strongest available check that
the method is sound.

| Order | Qty | Sourced from |
|---|---|---|
| 1 | 500 | Batch 1: 489, Batch 2: 11 |
| 2 | 300 | Batch 2: 300 |
| 7 | 420 | Batch 2: 38, Batch 3: 382 |
| 8 | 500 | Batch 3: 24, Batch 4: 476 |
| 9 | 455 | Batch 4: 123, Batch 5: 332 |
| 10 | 1000 | Batch 5: 236, Batch 6: 764 |
| 11 | 500 | Batch 6: 228, Batch 7: 272 |
| 16 | 500 | Batch 7: 500 |
| 17, 2026-09-03 | 151 | Batch 7 |
| 17, 2026-09-17/18 | 101 | Batch 7, scanned and certain |

The pool divides exactly, nothing left over.

## Boards assembled but never programmed

They accumulate across sessions; they do not belong to one batch. Measured at
the end of each programming session:

| Session ends | Batch | Assembled | Programmed | Left | Running pile |
|---|---|---|---|---|---|
| 2024-07-09 | Batch 1 | 525 | 521 | 4 | 4 |
| 2024-10-09 | Batch 2 | 350 | 349 | 1 | 5 |
| 2024-12-15 | Batch 3 | 450 | 408 | 42 | 47 |
| 2025-04-26 | Batch 4 | 600 | 599 | 1 | 48 |
| 2025-08-29 | Batch 5 | 600 | 569 | 31 | 79 |
| 2026-04-17 | Batch 6 | 1000 | 1013 | −13 | 66 |
| 2026-07-08 | Batch 7 | 1000 | 976 | 24 | 90 |
| 2026-09-17 | leftovers | — | 28 | −28 | **62** |

Batch 6 programmed 13 MORE than it received, which is only possible by drawing
on the pile. That is the proof the carry-forward is real.

**Batch 3 and Batch 5 account for most of it, and neither shows failed attempts
behind its shortfall** — those boards were never put on the bench, so this is
not a yield problem. Batch 1, by contrast, has 126 failed attempts behind only 4
missing boards, which is ordinary test scrap.

The 65 in the batch table counts by batch label; the 62 here counts by session
and nets off the 28 leftovers. Both are right; they answer different questions.

## Do the never-programmed counts agree with the reports?

**Yes.** Cross-check: take every dated report from BOTH sources — the Mac
repository the platform imported from, and the Windows bench machine — reduce
each identity to its last three MAC bytes, and count distinct devices whose
first report falls inside each batch's programming window.

| Batch | Assembled | Devices in platform | Devices in reports | Agreement | Never programmed |
|---|---|---|---|---|---|
| Batch 1 | 525 | 521 | 521 | exact | 4 |
| Batch 2 | 350 | 349 | 349 | exact | 1 |
| Batch 3 | 450 | 406 | 408 | +2 | **44** |
| Batch 4 | 600 | 598 | 599 | +1 | 2 |
| Batch 5 | 600 | 568 | 569 | +1 | **32** |
| Batch 6 | 1000 | 992 | 991 | −1 | 8 |
| Batch 7 | 1000 | 1025 | 1024 | −1 | −25 |

The two sources agree within ±2 on every batch, and the residue is boundary
effects — a device whose first report sits a day either side of the window.
**The reports independently confirm the programmed counts**, so the
never-programmed figures are real and not an artifact of missing records.

Across both sources only 18 identities have no record in any project, and 15 of
those are manufacturer prefixes or router addresses my extraction mistook for
devices. The real ones are the three already known: `4D8410` and `4D8174`, both
lost when the bench failed to save a report, and `D4E9F4F58CA4`, which never
passed.

### The bench was running two products at once

The same sessions that programmed dongles were also programming CE_Aqua_V2:

| Window | Dongles | Aqua | Aqua batch |
|---|---|---|---|
| Batch 3, 2024-11-16 .. 12-15 | 406 | **93** | Aqua Batch 3 — 125 pcs |
| Batch 6, 2025-12-22 .. 2026-01-07 | 991 | **151** | Aqua Batch 5 — 250 pcs |

This matters for reading the gaps. Batch 3 and Batch 5 left the most boards
unprogrammed, and the bench was not idle — it was working through Aqua units in
the same period. The dongle boards were not rejected, they were simply not
reached.

## The agreed stock model

Decided 2026-09-18. Two independent axes replace the single `state` column.

| Axis | Values | Meaning |
|---|---|---|
| **Location** | `in_stock`, `at_customer`, `returned`, `scrapped` | where the device is now |
| **Condition** | `ok`, `faulty`, `prototype`, `unidentified` | what the device is |

A shipment refuses any device whose condition is not `ok`, which is how the 32
old-button units are blocked from being sent without pretending they were
destroyed.

**A delivery is its own permanent record** — one row per device per shipment,
written when it goes out, never deleted and never edited. Current location
changes; that row does not. An order therefore reports four numbers, not one:

| Figure | Counted from |
|---|---|
| Ordered | the invoice |
| Shipped | delivery rows against this order — a replacement IS +1 |
| Returned | devices that came back |
| With customer | shipped − returned |

Fulfilled means *with customer ≥ ordered*, never *shipped ≥ ordered*. An order
of 500 needing 3 replacements reads `500 ordered · 503 shipped · 3 returned ·
500 with customer`, so the extra deliveries are visible and explained.

**Rules that make miscounting impossible:**

1. A device exists only if the flasher made it. No anonymous units.
2. Quantity is never stored. A shipment's quantity IS its device count.
3. A device is in exactly one location, always.
4. A shipment names its serials. No automatic pick, so an unknown or
   out-of-stock serial is refused rather than guessed.
5. Boards assembled but never programmed are a POOL quantity, not devices. They
   never enter this system.

**The invariant**, checked per batch on every write:

```
devices_programmed = in_stock + at_customer + returned + scrapped
```

## Verified target state

Computed against a copy of the production database on 2026-09-18. **The
invariant balances on every batch and the device pool divides with nothing left
over.**

| Batch | Programmed | At customer | In stock | Scrapped | Balances |
|---|---|---|---|---|---|
| Batch 1 | 521 | 489 | 32 | 0 | yes |
| Batch 2 | 349 | 349 | 0 | 0 | yes |
| Batch 3 | 406 | 406 | 0 | 0 | yes |
| Batch 4 | 599 | 599 | 0 | 0 | yes |
| Batch 5 | 568 | 568 | 0 | 0 | yes |
| Batch 6 | 992 | 992 | 0 | 0 | yes |
| Batch 7 | 1025 | 1024 | 0 | 1 | yes |
| no batch | 3 | 0 | 3 | 0 | yes |

### Records to create — 85 in total

| Purpose | Count | Condition | Destination |
|---|---|---|---|
| Prototypes sold | 35 | `prototype` | 15 to order 12, 20 to order 13 |
| Prototypes unsold | 10 | `prototype` | stock |
| Placeholders for 2026-09-03 | 40 | `unidentified` | that delivery, each with a note |

Every LCSC-assembled prototype board counts as programmed with a fake serial.
The 40 placeholders carry a note recording that the devices were delivered but
never identified, so they can be reconciled if the real serials ever surface.

### The result

| | Devices |
|---|---|
| Device records | 4463 existing + 85 new = **4548** |
| At customer | 4427 + 75 = **4502** |
| In stock, faulty | 32 |
| In stock, prototype | 10 |
| Scrapped | 1 |
| Failed, never batched | 3 |
| **Total** | **4548** |

### Deliveries the reconstruction writes

| Order | Delivery | Devices | Sourced from |
|---|---|---|---|
| 1 | 2024-07-21 | 489 | Batch 1 |
| 1 | after 2024-10-05 | 11 | Batch 2 |
| 2 | 2024-10-16 | 300 | Batch 2 |
| 7 | 2024-11-30 | 420 | Batch 2: 38, Batch 3: 382 |
| 8 | 2025-04-30 | 500 | Batch 3: 24, Batch 4: 476 |
| 9 | 2025-09-29 | 455 | Batch 4: 123, Batch 5: 332 |
| 10 | 2025-12-30 | 1000 | Batch 5: 236, Batch 6: 764 |
| 11 | 2026-07-09 | 500 | Batch 6: 228, Batch 7: 272 |
| 16 | 2026-07-09 | 500 | Batch 7 |
| 17 | 2026-09-03 | 151 + 40 placeholders = **191** | Batch 7 |
| 17 | 2026-09-17/18 | 101 | scanned, certain |

### The event log starts fresh

The existing log is rebuilt rather than corrected. 4326 of its 4427 deliveries
are FIFO guesses and the rest carry reversals of those guesses, so layering
corrections on top would preserve the guesses as if they were observations. The
reconstruction writes one clean history from the facts above.

## What the bench records contain

A full search of the Windows production machine on 2026-09-18 — 19,362 files
across the live folder, four archives and the Recycle Bin, plus a whole-disk
census finding 6,109 report files — returned **one** device the platform does
not hold, `2043A84D8174`, programmed 2026-09-10. A second, `D4E9F4F58CA4`,
failed every attempt.

Ruled out as explanations for missing serials:

| Cause | Devices it explains |
|---|---|
| Reports deleted by the `CE_Dongle_production` git cleanup (994 files, commit `ecc0d58`) | 0 — all 804 serials are in the platform |
| 6-hex serial collisions merging two devices | 0 — one collision exists, `A99AF8`, and both records survive |
| Reports lost to `WriteFile failed (PermissionError 13)` | 2 |
| Reports never imported | 0 |

Copies are in `reports/` at the repository root, split `identified/` and
`unidentified/`, with `manifest.csv`. ~713 MB, gitignored.

**The 6-to-12 digit serial change happened on 2025-12-23.** Device
`F8:B3:B7:42:AD:24` was programmed at 18:41 as `dongle_42AD24` and again at
18:48 as `dongle_F8B3B742AD24`.

## Traps

- **A JLC assembled count can be BARE boards.** On `SMT02404271716797` the
  invoice shows 300 bare boards ordered and 275 assembled. Row 26 of
  [../todo.md](../todo.md).
- **A 6-hex serial is only the last 3 MAC bytes**, so it collides across
  manufacturer prefixes. Match on the tail; never assume it is unique.
- **Serial logs drop characters.** `dongle-D4EF4F58CA4` is `D4E9F4F58CA4` with a
  `9` lost. Recover by unique near-match only.
- **Windows Recycle Bin `$I` files are binary metadata, not JSON**, despite the
  extension. The filename starts at byte 28 in a version-2 record.

## Open

| Question | Status |
|---|---|
| Which 40 devices left on 2026-09-03 | **Open.** 191 is fact; only 151 can be named. Do not invent the rest |
| Where the 62 never-programmed boards are | **Open.** Scrap, or bare boards somewhere. The records cannot say |
| Order 1's composition | **Settled** — 489 from Batch 1, 11 from Batch 2 |
| The 32 held units | **Settled** — named, on the shelf, never delivered |
| Batch quantities | **Settled** — programming data is the only count to trust |
