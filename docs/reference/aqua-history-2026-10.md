# CE_Aqua_V2: the history recreated from the platform's sources

**Working file, 2026-10-25. Nothing is written to the platform.** The question:
can the sources on the platform recreate the history of CE_Aqua_V2 as one
timeline, from Columbus's orders through the boards, the parts and LIFTECH's
work to the deliveries?

## The answer

**Yes for the flow, with three breaks.** Every Columbus order has a JLC order
and a LIFTECH campaign behind it, and the dates line up: the order comes in,
the boards are ordered 4–17 days later, LIFTECH programs them 3–12 weeks
after the order, and the delivery follows. Every board and every part
purchase has its document. The breaks:

1. **65 programmed units are on no delivery and not in the office.** About 40
   of them are probably Dongle V2 boards recorded as Aquas (section 6).
2. **Against the Kraków count, about 200 enclosure sets and about 390 long
   antennas are missing** (section 5).
3. The prototype delivery is dated before its boards existed.

## 1. The sources

| Source | On the platform as | Gives |
|---|---|---|
| Columbus orders and sales invoices | 7 sales orders, advance and settlement invoices | quantity, price, order date |
| Deliveries | shipments and their device events | date, quantity |
| JLC orders and invoices | `jlc_imports`, supplier documents | boards per design, order date (in the SMT number), ship date (the invoice date), delivery place |
| Part purchases | supplier documents, each with its PDF | parts and dates |
| Board-part usage | draws per batch | the parts each JLC order took |
| LIFTECH's work | bench runs (operator Paweł Kajda, stations COM4–COM11), 2 LIFTECH invoices with counts | which board was programmed and tested, when |
| Fleet | the broker, since 2026-09-18 | which unit is alive at a customer |
| **The Kraków office, 2026-10-02/03** | the MAC scan in `reports/stock-count-2026-10-02/readouts/`, the parts count in [stock-count-2026-10.md](stock-count-2026-10.md) | **the reference stock** (user, 2026-10-25) |
| LIFTECH's e-mail "Stan magazynowy", 2025-06-08 | Gmail only | a count the user does not trust (user, 2026-10-25) |

## 2. The order cycles

| # | Columbus order (date) | Aqua | Price (PLN) | Boards: JLC order, ordered → shipped | LIFTECH programmed | Delivered | Days, order → delivery |
|---|---|---|---|---|---|---|---|
| 0 | FV 01/02/2024 (2024-02-16) | 20 | 550 | Y29, 22 prototypes, 2024-02-19 → 02-27, to Kraków | not on the bench | recorded 2024-02-16, the invoice date | — |
| 1 | FV 01/07/2024 (2024-06-10) | 110 | 340 | P15, 125, 06-20 → 06-30 | 07-09 – 07-11: 122 | 2024-07-16: 110 | 36 |
| — | none (stock) | — | — | P16, 190, 07-15 → 07-29 | 08-05 – 08-07: 190, tested 08-16 – 08-21 | — | — |
| 2 | FV 1/10/2024 (2024-09-13) | 150 | 340 | P19, 200 (with Dongle P18), 09-17 → 09-30 | 10-02 – 10-04: 200 | 2024-10-16: 152 | 33 |
| 3 | FV 3/10/2024 (2024-10-30) | 157 | 343.95 | from stock | — | 2024-10-30: 157 | 0 |
| 4 | ZAL 00001/10/2024 (2024-10-04) | 100 | 320 | P20, 125 (with Dongle P21, 450), 10-14 → 10-28 | 11-21 – 12-14: 165 | 2024-11-30: 100 | 57 |
| 5 | ZAL 00001/03/2025 (2025-03-11) | 100 | 320 | P30, 125 (with Dongle P29, 600), 03-18 → 03-31 | 04-24 – 04-28: 125 (and 2 on 03-19) | 2025-04-30: 100 | 50 |
| 6 | ZAL 00001/09/2025 (2025-09-29) | 250 | 320 | P30 reorder, 250 (with Dongle P29, 1000), 10-16 → 11-05 | 2025-12-10 – 2026-01-18: 185 | 2025-12-30: 250; 2026-01-18: 19 more (correction at the 2026-10-02 count) | 92 |

Columbus ordered 887 Aquas, the platform shows 908 delivered. The 21 extra
are order 2 (152 for 150) and order 6 (269 for 250). Every production order
went to LIFTECH in Olkusz. Cycle 6 delivered 269 units from 185 programmed in
its campaign, so 84 came from older stock.

## 3. The units over time

"Programmed" counts each board once, on its first passing flash.
"Delivered" counts production units only (the 20 prototypes are separate).

| Date | Event | Programmed, total | Delivered, total | Programmed, not delivered |
|---|---|---|---|---|
| 2024-07-11 | P15 programmed | 122 | 0 | 122 |
| 2024-07-16 | Order 1 delivered | 122 | 110 | 12 |
| 2024-08-07 | P16 programmed | 312 | 110 | 202 |
| 2024-10-04 | P19 programmed | 512 | 110 | 402 |
| 2024-10-16 | Order 2 delivered | 512 | 262 | 250 |
| 2024-10-30 | Order 3 delivered | 512 | 419 | 93 |
| 2024-11-25 | P20, first 93 | 605 | 419 | 186 |
| 2024-11-30 | Order 4 delivered | 605 | 519 | 86 |
| 2024-12-14 | P20, 72 more | 677 | 519 | 158 |
| 2025-03-19 | 2 more (old boards) | 679 | 519 | 160 |
| 2025-04-28 | P30 programmed | 804 | 519 | 285 |
| 2025-04-30 | Order 5 delivered | 804 | 619 | 185 |
| 2026-01-18 | P30 reorder programmed, order 6 delivered | 989 | 888 | 101 |
| **2026-10-02** | **The Kraków office, by MAC (section 4)** | | | **36 in the office** |

The boards balance per JLC order. Every board was programmed within weeks of
its arrival, except 3 of Batch 1 (2 of them programmed on 2025-03-19) and 65
of the P30 reorder (61 bare boards in the office, 2 disposed, 2 not known).
P20 is the exception: 165 programmed from 125 boards.

## 4. The Kraków office on 2026-10-02, by MAC

| In the office | Units | Programmed in | Matched to the platform by |
|---|---|---|---|
| Finished Aquas | 29 | Batch 1: 3, Batch 4: 18, Batch 5: 8 | full MAC 12, 6-hex ID 17 |
| Spares with a record | 8 | 7 programmed (Batches 4 and 5), 1 never flashed | full MAC 6, 6-hex ID 2 |
| Bare boards | 61 | none: no record at all | their MACs are in Batch 5's ranges (841fe835, 8813bfa9, f024f910) |

So 36 programmed units are in the office, and 953 programmed units left it.
Columbus invoiced 867 production units, the platform records 888 delivered,
and **65 programmed units are on no delivery**. 17 of the finished units in
the office once had a "shipped" event, which the 2026-10-02 correction took
back.

## 5. Component usage

### The board parts

| Batch | JLC order | Board parts supplied by | Drawn on the platform | JLC order date |
|---|---|---|---|---|
| 1 | P15, P16 | JLC (turnkey, in its invoice) | no draw needed | 2024-06-20, 07-15 |
| 2 | P19 | our stock, consigned | 2024-09-30 | 2024-09-17 |
| 3 | P20 | our stock, consigned | 2024-10-28 | 2024-10-14 |
| 4 | P30 | our stock, consigned | 2025-03-31 | 2025-03-18 |
| 5 | P30 reorder | our stock, consigned | 2025-11-05 | 2025-10-16 |

Each consigned order drew one ESP32-WROOM-32UE-N4 per board, together with
the Dongle boards of the same order. The module never ran out. The draws are
dated at JLC's invoice date, 2–3 weeks after the order: recreatable as they
are.

### The hand parts, against the Kraków count

"Expected" is the purchases less one set per Aqua enclosed: the 20
prototypes (no front panel), the units that left the office, and the 35
enclosed units in it. The range is with and without the 40 suspected Dongle
boards.

| Part | Bought | Documents | Expected on 2026-10-03 | Kraków count | Missing |
|---|---|---|---|---|---|
| Enclosure body 05.0502530 | 1,402 | TME ×2, Italtronic ×2 (one with 2 orders, 550 + 500) | 394–434 | 200 pairs | 194–234 |
| Front panel P05050201P.BL | 1,380 | TME, Italtronic ×2 | 392–432 | (in the 200 pairs) | 192–232 |
| Long antenna 146153-0150 | 1,425 | TME ×3, Mouser, DigiKey 107855766 | 417–457 | 48 | 369–409 |
| Carton 120x100x80 | 2,000 | PUDLO FA 1483/24, and a placeholder for 1,000 | — | not counted | — |

Every long antenna has an invoice with its PDF. DigiKey 107855766 really
holds two lines, 500 short (WM17084) and 500 long (WM17566), in one box. The
invoice that is missing is for the **short** Dongle antenna 146153-0050:
PLACEHOLDER-ANT0050-2024 books 1,235 of them, because the Dongle batches used
4,325 while only 3,195 were invoiced. Probably (not verified) LIFTECH fitted
long antennas on Dongles when the short ones ran out: that would explain
both the missing long antennas and part of the short-antenna placeholder.

## 6. The breaks

1. **About 40 Dongle V2 boards are probably recorded as Aquas** (the user:
   "it's possible"). JLC order P20 + P21 made 125 Aqua and 450 Dongle PCBs,
   and drew 575 ESP32 modules. The bench programmed 573 units from it: 165
   as Aqua, 408 as Dongle. One unit of that campaign reports Dongle firmware
   on the broker. The data does not say which units they are.
2. **65 programmed units are on no delivery and not in the office.** Less the
   40, 25 units are not explained. The broker shows 22 units at customers
   whose records are not "shipped": the 19 alive of the 76 units taken out of
   their batches on 2026-09-10, and 3 "missing" units of Batch 4.
3. **Against the Kraków count, about 200 enclosure sets and about 390 long
   antennas are missing.** Possible causes: sets fitted to boards that
   failed, long antennas fitted to Dongles, parts left at LIFTECH.
4. **The prototype delivery is dated 2024-02-16**, the date of invoice
   FV 01/02/2024. The 22 prototype boards were ordered on 2024-02-19 and
   shipped from JLC on 02-27.
5. **Which unit went to which order is partly guessed.** 221 delivered
   records have no MAC and never appeared on the broker. The quantities per
   order are right.

## 7. Can the platform recreate it?

| Area | Recreate | Confidence | What is missing |
|---|---|---|---|
| Columbus orders, prices, invoices | yes | high | — |
| Deliveries, quantity and date | yes | high | the prototype delivery date |
| Which unit went to which delivery | partly | low | 221 records nothing proves |
| Board orders and their dates | yes | high | the arrival date (the first programming is the proxy) |
| Board-part usage | yes | high | — |
| Hand-part purchases | yes | high | one carton invoice is a placeholder |
| Hand-part usage | yes, one set per enclosed unit | medium | about 200 sets and 390 antennas against the Kraków count |
| Programming and tests per unit | yes | high | about 40 of the units are probably Dongle boards |
| The stock in the office | yes, by MAC | high | — |
| What happened to every unit | partly | medium | 25 units after the 40 |

## 8. The user's answers (2026-10-25) and what is still open

| Question | Answer |
|---|---|
| About 40 Dongle boards programmed as Aqua in Nov–Dec 2024? | "It's possible." |
| An invoice for the long antennas? | All 5 are on the platform with their PDFs. The missing one is the short antennas' (above). |
| Which count is the reference? | The Kraków office's. LIFTECH's counts may be wrong. |
| The unexplained units? | The office was scanned by MAC (section 4). |
| The antennas? | Both: LIFTECH fitted some long antennas, and about 1,000 or more short antennas were bought with no invoice (the placeholder of 1,235 stands). |
| Write the books down to the Kraków count? | Yes, after the user asks LIFTECH. If LIFTECH holds nothing, the parts are gone. |
| Mark the 22 units alive at customers as delivered? | Yes. Done 2026-10-25 (below). |
| The 40 suspected Dongle boards? | They stay Aquas until a unit proves otherwise. |

**Done on 2026-10-25.** The 19 units with no batch were linked to their
batches by their programming date (`POST /runs/{id}/produced`): Batch 1: 9,
Batch 2: 5, Batch 3: 2 (unit 2514, programmed 2025-03-19 before P30 shipped,
on a P20 reel), Batch 4: 3. Then the 22 units went on a correction delivery
of the first Columbus delivery after their programming:

| Shipment | Order | Date | Units | The order now |
|---|---|---|---|---|
| 2328 | FV 1/10/2024 | 2024-10-16 | 14 (Batches 1 and 2) | 166 Aquas for 150 ordered |
| 2329 | ZAL 00001/03/2025 | 2025-04-30 | 8 (Batches 3 and 4, with the 3 "missing" units) | 108 Aquas for 100 ordered |

The register's gap stayed 0.

LIFTECH holds no Aqua parts and no Aqua devices (user, 2026-10-25). The
write-down to the Kraków count goes after the rebuild, because the
prototypes' 22 enclosure sets must be drawn first.

## 9. The process, as the evidence shows it

| # | Step | Who | Parts per unit | Evidence |
|---|---|---|---|---|
| 1 | Columbus orders, 7Sigma invoices an advance | 7Sigma | — | sales orders, ZAL invoices |
| 2 | Order the PCBAs from JLC, in one order with the Dongle boards; ship to LIFTECH, Olkusz | 7Sigma, JLC | Batch 1 turnkey; later the BOM consigned from our JLC parts stock, one ESP32 per board | JLC orders, draws |
| 3 | Buy the hand parts, deliver them to LIFTECH | 7Sigma | — | Italtronic, TME, Mouser, DigiKey, PUDLO |
| 4 | Receive the PCBA | LIFTECH | — | — |
| 5 | Add the antenna to the PCBA | LIFTECH | 146153-0150 | the user (2026-10-26); purchases one per unit |
| 6 | Program (Aqua_V2 config) | LIFTECH, Paweł Kajda, 4–6 stations | — | bench runs |
| 7 | Function test (Aqua_V2 test), optional | LIFTECH | — | tests in Aug 2024, Oct 2024, Dec 2024, Apr 2025; none on the P30 reorder |
| 8 | Insert the PCBA into the enclosure, connect the antenna | LIFTECH | 05.0502530 | the user |
| 9 | Fit the front panel | LIFTECH | P05050201P.BL | the user; the prototypes had no panel |
| 10 | Laser mark (needs a programmed PCBA with its antenna), barcode label | LIFTECH, its own labels | — | the user; no bench record |
| 11 | Pack into the carton; a leaflet since 2025-04-15 | LIFTECH | KARTON-120x100x80-B | carton purchases; the user |
| 12 | Deliver to Columbus, bill per unit delivered | LIFTECH | — | section 10 |
| 13 | Settlement invoice to Columbus | 7Sigma | — | FV invoices |

The user confirmed this order on 2026-10-26: it is the Dongle V2 route with
the test and the front panel added. It fits LIFTECH's count of 2025-06-08
(84 "Aqua boards with antennas", programmed but not enclosed).

## 10. What LIFTECH's invoices cover

LIFTECH bills each unit when it is delivered:

| Invoice | Amount (PLN) | States | Columbus delivery | Per unit (PLN) |
|---|---|---|---|---|
| 1/08/24, 2024-08-27 | 5,052 | a lump | 2024-07-21: 500 Dongle; 2024-07-16: 110 Aqua | 7.05 (inferred: 717 units) |
| 3/04/25, 2025-04-30 | 10,665 | 1,239 Dongle, 400 Aqua | Oct 2024 – Apr 2025: 1,233 Dongle, 507 Aqua | 6.51 |
| 2/09/25, 2025-09-24 | 3,240 | 455 Dongle | 2025-09-29: 456 Dongle | 7.12 |
| 1/12/25, 2025-12-29 | 8,765 | 1,000 Dongle, 250 Aqua | 2025-12-30: 1,000 Dongle, 250 Aqua | 7.01 |
| 1/7/2026, 2026-07-08 | 7,035 | 1,000 Dongle | 2026-07-09: 1,000 Dongle | 7.04 |

1/08/24 states no count. 3/04/25 bills 400 Aquas against 507 delivered in its
period, so 107 were billed before: on 1/08/24, with the 110 of July. That
makes 1/08/24 = 500 Dongle + 217 Aqua = 717 units at 7.05 PLN, in line with
the later rates. Then 3/04/25's 400 Aquas are the period's deliveries less
those 107: 402 by the delivery records.

"2024-09-30-LIFTECH-assembly" (1,750 PLN, "5 PLN × 350", on Dongle Batch 2)
has no PDF and no invoice number. It was typed in on 2026-07-27. The 300
Dongles delivered on 2024-10-16 are already inside 3/04/25's 1,239: this is
probably a double count.

Proposed LIFTECH cost per Aqua batch (each delivered unit at the rate of the
invoice that billed it):

| Batch | Today (PLN) | Proposed (PLN) | From |
|---|---|---|---|
| 1 (P15 + P16) | 1,071.60 | 1,937 | 1/08/24: 217; 3/04/25: 63 |
| 2 (P19) | 680.38 | 1,204 | 3/04/25: 185 |
| 3 (P20) | 425.24 | 1,067 | 3/04/25: 152; 1/12/25: 11 |
| 4 (P30) | 425.23 | 603 | 1/12/25: 86 |
| 5 (P30 reorder) | 1,753.00 | 1,073 | 1/12/25: 153 |
| Aqua total | 4,355.45 | 5,884 | |
| Dongle Batch 1 | 5,052.00 | 3,523 | 1/08/24: 500 |

## 11. Batches are JLC's PCBA orders

LIFTECH did not keep our batches: it programmed boards as they came. A unit
belongs to the PCBA order whose boards were at LIFTECH when it was first
programmed.

| PCBA order | Boards | Units programmed | Delivered | In stock | Missing | No state (never passed the test; 10 of them are in the office) | Balance |
|---|---|---|---|---|---|---|---|
| Y29 (prototypes) | 22 | 22 (not on the bench) | 20 | — | 2 | — | exact |
| P15 (Batch 1) | 125 | 122 | 122 | — | — | — | 3 boards: 2 programmed 2025-03-19, 1 not known |
| P16 (Batch 1) | 190 | 190 | 163 | 2 | — | 25 | exact |
| P19 (Batch 2) | 200 | 200 | 191 | — | — | 9 | exact |
| P20 (Batch 3) | 125 | 165 | 164 | — | — | 1 | 40 units more than boards |
| P30 (Batch 4) | 125 | 125 | 80 | 17 | 9 | 19 | exact |
| P30 reorder (Batch 5) | 250 | 185 | 164 | 8 | 11 | 2 | 61 bare boards in the office, 2 disposed, 2 not known |

The accounting rules that close it:

1. **P20's 40 extra units were built on boards of Dongle order P21**, from
   the same JLC shipment, which has 42 boards with no Dongle unit. They stay
   Aquas (the user), and their board cost comes from Dongle Batch 3.
2. **P30 reorder's 61 bare boards are units of Batch 5** that stopped at
   "received" (a pile).
3. **The units neither delivered nor in the office are lost**: they stay in
   their batch's cost as a loss. LIFTECH holds none of them.
