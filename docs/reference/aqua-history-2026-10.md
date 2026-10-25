# CE_Aqua_V2: the history recreated from the platform's sources

**Working file, 2026-10-25. Nothing is written to the platform.** The question:
can the sources on the platform recreate the history of CE_Aqua_V2 as one
timeline, from Columbus's orders through the boards, the parts and LIFTECH's
work to the deliveries?

## The answer

**Yes for the flow, with four breaks.** Every Columbus order has a JLC order
and a LIFTECH campaign behind it, and the dates line up: the order comes in,
the boards are ordered 4–17 days later, LIFTECH programs them 3–12 weeks
after the order, and the delivery follows. The board parts, the enclosures
and the panels close against LIFTECH's count of 2025-06-08. The breaks:

1. About 40 of the 165 "Aqua" units programmed in Nov–Dec 2024 are Dongle V2
   boards (section 5).
2. 453 long antennas are missing by 2025-06-08.
3. The finished stock on the platform is higher than both counts.
4. The prototype delivery is dated before its boards existed.

## 1. The sources

| Source | On the platform as | Gives |
|---|---|---|
| Columbus orders and sales invoices | 7 sales orders, advance and settlement invoices | quantity, price, order date |
| Deliveries | shipments and their device events | date, quantity |
| JLC orders and invoices | `jlc_imports`, supplier documents | boards per design, order date (in the SMT number), ship date (the invoice date), delivery place |
| Part purchases | supplier documents (Italtronic, TME, Mouser, DigiKey, PUDLO, JLC parts orders) | parts and dates |
| Board-part usage | draws per batch | the parts each JLC order took |
| LIFTECH's work | bench runs (operator Paweł Kajda, stations COM4–COM11), 2 LIFTECH invoices with counts | which board was programmed and tested, when |
| Fleet | the broker, since 2026-09-18 | which unit is alive at a customer |
| Counts | LIFTECH's e-mail "Stan magazynowy" of 2025-06-08 (Gmail only); the user's count of 2026-10-02/03 ([stock-count-2026-10.md](stock-count-2026-10.md)) | the shelf on two dates |

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
its campaign, so 84 came from older stock: the same number as the "boards
with antennas" LIFTECH counted on 2025-06-08.

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
| **2025-06-08** | **LIFTECH's count: 15 packed + 84 boards with antennas** | | | **99 counted** |
| 2026-01-18 | P30 reorder programmed, order 6 delivered | 989 | 888 | 101 |
| **2026-10-02** | **The user's count: 29 finished + 6 assembled spares + 2 programmed bare boards** | | | **37 counted** |

The boards balance per JLC order. Every board was programmed within weeks of
its arrival, except 3 of Batch 1 (2 of them programmed on 2025-03-19) and 65
of the P30 reorder (61 bare boards on the shelf, 2 disposed, 2 not known).
P20 is the exception: 165 programmed from 125 boards.

## 4. Component usage

### The board parts

| Batch | JLC order | Board parts supplied by | Drawn on the platform | JLC order date |
|---|---|---|---|---|
| 1 | P15, P16 | JLC (turnkey, in its invoice) | no draw needed | 2024-06-20, 07-15 |
| 2 | P19 | our stock, consigned | 2024-09-30 | 2024-09-17 |
| 3 | P20 | our stock, consigned | 2024-10-28 | 2024-10-14 |
| 4 | P30 | our stock, consigned | 2025-03-31 | 2025-03-18 |
| 5 | P30 reorder | our stock, consigned | 2025-11-05 | 2025-10-16 |

Each consigned order drew one ESP32-WROOM-32UE-N4 per board, together with
the Dongle boards of the same order. The module never ran out (JLC parts
orders 2024-07-24, 10-09, 10-17, 2025-03-19, 09-30). The draws are dated at
JLC's invoice date, 2–3 weeks after the order: recreatable as they are.

### The hand parts

| Part | Bought (dates) | Expected on 2025-06-08 | LIFTECH counted | Expected on 2026-10-03 | The user counted |
|---|---|---|---|---|---|
| Enclosure body 05.0502530 | 1,402 (2024-02-20 to 09-18) | 748 | 740 "enclosures" | 451 | 200 pairs |
| Front panel P05050201P.BL | 1,380 (2024-06-21 to 09-18) | 746 | (in the 740) | 451 | (in the 200 pairs) |
| Long antenna 146153-0150 | 1,425 (2024-02-20 to 10-17) | 687 loose + 84 on boards | 234 loose + 84 on boards | 29 | 48 |
| Carton 120x100x80 | 2,000 (1,000 of them a placeholder) | 1,361–1,491 | 1,250 | — | not counted |

"Expected" is purchases less one set per unit enclosed by that date. A unit
is enclosed when it is delivered or packed. The bodies and panels close in
June 2025. The antennas are 453 short in June 2025, but close afterwards
(29 expected, 48 counted). The bodies and panels are 251 sets short in
October 2026.

## 5. The breaks

1. **About 40 Dongle V2 boards are recorded as Aquas.** JLC order P20 + P21
   made 125 Aqua and 450 Dongle PCBs, and drew 575 ESP32 modules. The bench
   programmed 573 units from it: 165 as Aqua, 408 as Dongle. 125 Aqua PCBs
   cannot give 165 Aquas, so about 40 Dongle boards were programmed with the
   Aqua firmware in Nov–Dec 2024. One unit of that campaign reports Dongle
   firmware on the broker. Probably (not verified) they are among the 93
   units programmed on 2024-11-21 and 11-25 without the Aqua test. The data
   does not say which ones.
2. **The finished stock on the platform is too high.** On 2025-06-08 the
   platform holds 185 units where LIFTECH counted 99. Less the 40 Dongles,
   46 units are not explained. On 2026-10-02 it is 101 against 37, so 24
   units are not explained after the 40. Probably these are units scrapped,
   failed or lost without a record (not verified).
3. **453 long antennas are missing by 2025-06-08.** After that date the
   antennas close.
4. **251 enclosure sets are missing on 2026-10-03.** They close in June 2025.
   Maybe the user's count covered only the user's shelf, not LIFTECH's.
5. **The prototype delivery is dated 2024-02-16**, the date of invoice
   FV 01/02/2024. The 22 prototype boards were ordered on 2024-02-19 and
   shipped from JLC on 02-27.
6. **Which unit went to which order is partly guessed.** 221 delivered
   records have no MAC and never appeared on the broker. The quantities per
   order are right.
7. **76 units were taken out of their batches on 2026-09-10** for "never
   passed the function test". 19 of them are alive at customers. By their
   programming date they belong to Batches 1 (34), 2 (14), 3 (2), 4 (23)
   and 5 (2).

## 6. Can the platform recreate it?

| Area | Recreate | Confidence | What is missing |
|---|---|---|---|
| Columbus orders, prices, invoices | yes | high | — |
| Deliveries, quantity and date | yes | high | the prototype delivery date |
| Which unit went to which delivery | partly | low | 221 records nothing proves |
| Board orders and their dates | yes | high | the arrival date (the first programming is the proxy) |
| Board-part usage | yes | high | — |
| Hand-part purchases | yes | high | one carton invoice is a placeholder |
| Hand-part usage | yes, one set per enclosed unit | medium | 453 antennas before June 2025; 251 sets in October 2026 |
| Programming and tests per unit | yes | high | about 40 of the units are Dongle boards |
| Assembly work at LIFTECH | partly | low | the invoices state counts but not their periods |
| What happened to every unit | partly | medium | 46 units in June 2025, 24 in October 2026 |

## 7. Questions that close the breaks

1. Did LIFTECH program about 40 Dongle boards with the Aqua firmware in
   Nov–Dec 2024?
2. Where did about 450 long antennas go before June 2025? Were some kept in
   Kraków?
3. Did your count of 2026-10-03 cover LIFTECH's shelf too?
4. Were about 46 programmed units scrapped or kept somewhere between the end
   of 2024 and June 2025?
