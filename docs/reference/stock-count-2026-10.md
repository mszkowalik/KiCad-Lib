# Stock count of 2026-10-02 — working file

The shelf was read out unit by unit on 2026-10-02 and compared with the device
records on production. This page holds what was found, what the user stated,
what was decided, and what is still open. Delete it when the clean-up lands,
the same as [dongle-stock-reconciliation.md](dongle-stock-reconciliation.md).

**This page records facts and decisions.** Where the platform disagrees with a
fact here, the fact wins and the platform is what needs changing.

## How the shelf was read

`clients/device-id-reader/read_ids.py` watches for a unit on USB, resets it,
reads its boot output and records it in a JSON file keyed by MAC. Its docstring
holds the method. What a reading proves:

| `firmware_seen` | Evidence |
|---|---|
| `tasmota` | the unit answered `Status 0`: MAC and topic from the firmware |
| `none (no app in flash)` | the ROM printed `invalid header: 0xffffffff`: the flash is empty |
| `esp-at (factory)` | the module's factory ESP-AT firmware: not programmed by us |
| `not checked (BOOT held)` | MAC from the ROM only. Says NOTHING about the firmware |

The raw files and the platform state before any change are in
`reports/stock-count-2026-10-02/` (gitignored): `readouts/` holds the eight
readout files, `platform-before/` the device, order, shipment and stock
snapshots and the broker presence of every Aqua in question.

## What the user stated

These outrank every computed figure.

| Fact | Consequence |
|---|---|
| No Aqua has ever come back from a customer. No recalls, no replacements | A "shipped" unit on the shelf never left |
| Deliveries before Batch 8, and part of Batch 7, were not tracked by serial | Every older `shipped` record is a guess, and late deliveries are possible |
| Columbus keeps finding devices our books do not show | Log files were lost. Placeholders in deliveries are expected, and the broker fills them |
| More units may have been sent than invoiced | A delivery may exceed its order (the platform allows it) |
| The 29 finished Aquas are programmed, enclosed and shippable | — |
| The 6 Tasmota spare Aquas have an enclosure and an antenna: fully assembled. The other 63 spare Aquas are bare PCBs | — |
| Units whose newest run failed stay failed on the platform | 3 finished Aquas and 6 Tasmota spares do not count as built (decision 0007), on purpose |
| Batch 5's 2 unaccounted boards were disposed of | Batch 5 closes exactly |
| All 34 programmed Dongle V2 on the shelf are in stock; some are noted not for sale for faulty buttons | — |
| The 10 unprogrammed Dongle V2 go to production | The bench records them by MAC |
| Dongle V3 on the desk: 5 v3.3 (some may be faulty), 6 v3.2, 4 v3.1 (almost all dead) | 3 dead v3.1 could not be read |
| The readout is complete: 29 finished Aquas and 69 spares, nothing else on the shelf (2026-10-02) | the absent units are really absent |
| No device is powered or online at the user's place | a unit online on the broker is at the customer |
| `f8:b3:b7:42:ba:1c` must not be sellable | it becomes condition `incomplete` in the correction |

## CE_Aqua_V2

### Shelf against records

| On the shelf | Units | Platform said |
|---|---|---|
| Finished, shippable (`finished_aquas.json`) | 29 | 9 in stock · 17 shipped · 3 newest run failed |
| Spare, Tasmota, assembled | 6 | all 6 newest run failed |
| Spare, bare PCB | 63 | 61 not on the platform · 1 shipped (`f8:b3:b7:42:ba:1c`) · 1 newest run failed |

The platform held 41 Aquas in stock that were not on the shelf: 39 production
units and 2 MAC-less prototypes (run 10733).

### JLC against programming

| Batch | JLC assembled | Passed | Failed records | Unbuilt on the shelf | Balance |
|---|---|---|---|---|---|
| Batch 4 | 125 | 103 | 22 | — | exact |
| Batch 5 | 250 | 184 | 3 assembled spares | 61 bare + 2 disposed | exact |

All Aqua production: 915 units passed, 27 are on the shelf, so 888 left our
hands against 867 production units invoiced (887 minus 20 prototypes): 21
passed units left without an invoice. Batches 1-3 carry about 37 more records
than JLC boards; some "failed Aqua" records have Dongle V2 MAC prefixes
(`fc:e8:c0`, `a0:dd:6c`) and are probably misfiled. Not investigated.

### The broker

Of the 39 absent units, 18 are online on the fleet broker since 2026-09-18, 11
of them reporting an inverter serial: they are at the customer. None of the 18
shelf units recorded as shipped has ever come online. A topic with retained
messages only proves nothing: 3 shelf units have them too.

11 of the 18 live units are Batch 5, programmed on 2026-01-18 between 20:30
and 20:44, after the last recorded Aqua delivery date (shipment #24,
2025-12-30). So order ZAL 00001/09/2025's Aquas left later than recorded, which
the user confirms is possible.

### Agreed correction — APPLIED 2026-10-03

Agreed with the user on 2026-10-02 and applied to production on 2026-10-03 by
`scripts/stock-count-aqua-2026-10-02.py` (decision
[0057](../decisions/0057-a-device-the-count-cannot-find-is-missing.md)). The
correction delivery is shipment #2305, the placeholders are devices #28528 and
#28529, and the audit row is `stock.count` on the project. Figures after:
29 in stock (26 sellable, 1 `incomplete`, 2 `prototype`), 887 shipped,
23 missing.

1. **Unship the 18 shelf units** from their deliveries, back to stock:
   #745 `dongle_1F456C` and #822 `dongle_1F4A60` from shipment #19; from
   shipment #24: #2258 `42A9F8`, #2261 `42AE5C`, #2273 `f8:b3:b7:42:ba:1c`,
   #2285 `42CE28`, #2286 `42CF80`, #2293 `42D464`, #2294 `42D7F4`, #2303
   `42E2A0`, #2317 `435AC0`, #2323 `4366CC`, #2333 `437D00`, #2346
   `f8:b3:b7:43:9a:18`, #2358 `f8:b3:b7:44:52:88`, #2368 `f8:b3:b7:44:6b:a8`,
   #2380 `4493E0`, #2383 `4497A0`.
2. **Ship the 19 units proven at the customer** on a correction delivery of
   order ZAL 00001/09/2025 (16 take #24's freed places, 3 replace #24 members
   never heard on the broker): #2319, #2347, #2359, #2364, #2375, #2384, #2387
   (Batch 4, `f8:b3:b7`), #4453, #4457, #4459, #4465, #4467, #4468, #4469,
   #4473, #4484, #4485, #4496 (Batch 5), and #28523 `84:1f:e8:35:0d:a4`
   (reported by the user, 2026-10-01).
3. **The 3 replaced #24 members** are the three lowest device ids among
   #24's CE_Aqua_V2 members with no broker presence at all: #2263
   `f8:b3:b7:42:b1:60`, #2278 `f8:b3:b7:42:bf:00` and #2290 `dongle_42D2BC`
   (the prod dry run of 2026-10-02).
4. **2 `unidentified` placeholders** take the 2 places on shipment #19 (FV
   1/10/2024) that no known unit can fill. They carry Batch 1, the batch of the
   units they stand in for.
5. **Mark 23 units `missing`**: the 3 replaced #24 members and these 20 absent
   units nobody can place — #2264, #2275, #2310, #2335, #2344, #2371, #2381,
   #2388, #2389 (Batch 4) and #4452, #4454, #4456, #4458, #4460, #4462, #4464,
   #4466, #4472, #4474, #4483 (Batch 5). A later broker sighting ships one from
   the UI.
6. **Device #2273 `f8:b3:b7:42:ba:1c` becomes condition `incomplete`** after
   its unship: a programmed bare PCB with no enclosure and no antenna. The
   condition axis already refuses any non-`ok` unit on a shipment, so no code
   carries this — only the UI word maps name the new value.

Result: every order keeps its invoiced quantity (887), every shelf unit is in
stock, and every proven unit is shipped. The platform shelf becomes 29 in
stock: 26 finished sellable, 1 bare PCB held `incomplete`, 2 prototypes held —
against 29 finished on the shelf. The 3 failed-run finished units and the 6
failed-run spares stay uncounted, on purpose (decision 0007, user 2026-10-02).

**Still open for CE_Aqua_V2:**

- The spare boards: rule 5 of the 2026-09-18 stock model
  ([dongle-stock-reconciliation.md](dongle-stock-reconciliation.md)) says a
  board never programmed is a pool quantity, not a device. The recommended
  alternative is a device row by MAC with a new condition `unprogrammed`, set
  only from a bench observation. Not decided; either way it needs a decision
  record.

## CE_Dongle_V2

Worked 2026-10-03 against a fresh production snapshot
(`reports/stock-count-2026-10-02/platform-v2/`), the bench reports in
`reports/manifest.csv` and the broker. Correction not agreed yet.

| Unit | Shelf | Platform | Evidence |
|---|---|---|---|
| 32 Batch 1 old-button units (#118, #394–#641) | read, programmed | in stock, `faulty` | 31 matched by topic, #451 by MAC. Broker: retained messages only, never online. Correct as it is |
| #3008 `dongle_4D8694` (Batch 5) | read, programmed | shipped, shipment #23 (order 9, ZAL 00001/07/2025, 2025-09-29, oldest-first pick) | no presence row on the broker; it has an account. Bench report OK 2025-08-23 |
| `20:43:a8:4d:81:74` `dongle_2043A84D8174` | read, programmed | no record, no broker account | bench: an attempt on 2025-08-23 whose report failed to save (`1755970684`), then OK on 2026-09-10 in a Batch 7 session. The account derived with the fleet salt equals the bench report's line (checked locally, not printed) |
| #1607 `dongle_84FA58`, #1768 `dongle_84FD94` (no batch) | not read | in stock, `faulty`, newest run `fail` | ONLINE on the broker with inverters (DEYE_LP3 `2407072366`, SOFAR `SH1051006KE254230090`): at customers. The `fail` is an import artifact: the `_test` report has no `test_result` field. Config and test reports both say OK (2024-11-17/18). Every bench neighbour is Batch 3 on shipment #20 (order 7, ZAL 00001/10/2024, 2024-11-30). Only these 2 devices on the platform carry this artifact (prod query, 2026-10-03) |
| #3221 `dongle_4D90A8` (no batch) | not read | in stock, `faulty` | its only report failed to save (`WriteFile failed`), so the result is unknown. Has an account, never on the broker |
| 12 MAC-less prototypes: #6593–#6602, #28318–#28319 | cannot be matched | in stock, `prototype` | #6593–#6602 are the "10 unsold" the 2026-09-18 reconstruction computed (45 assembled − 35 sold), not observed. #28318–#28319 are placeholders the user added for unprogrammed prototypes |
| 10 unprogrammed boards (`dongles_v2.json` + `dongles_v2_1.json`) | read, BOOT held | no record | correct (rule 5). MAC prefixes: 7 Batch 7, 2 Batch 5, 1 Batch 4 (prefix only, not proof). `d4:e9:f4:f5:8c:a4` failed every attempt (2026-07-07/08, 2026-09-10) |

This closes the gap that
[dongle-stock-reconciliation.md](dongle-stock-reconciliation.md) left between
devices in the platform and devices in the reports: Batch 3's +2 are #1607 and
#1768, Batch 5's +1 is `2043A84D8174`.

### Part A — APPLIED 2026-10-03

User answers 2026-10-03, applied by `scripts/stock-count-dongle-v2-2026-10-03.py`
(decision [0057](../decisions/0057-a-device-the-count-cannot-find-is-missing.md)):

1. #1607 and #1768: condition `ok`, moved to Batch 3 (0029), shipped on
   correction delivery #2311 of ZAL 00001/10/2024, dated 2024-11-30.
   **Option B**: the order keeps its invoiced 420, so the two lowest-id Batch 3
   members of shipment #20 with no broker presence came off it and are
   `missing`: #1053 `dongle_1F32A0` and #1061 `dongle_1F32C0`.
2. #3221 `dongle_4D90A8`: `missing`.
3. The 12 MAC-less dongle prototypes (#6593–#6602, #28318, #28319): `missing`
   (user: no prototype dongle on hand).
4. The 2 MAC-less Aqua prototypes (#28316, #28317): `missing`. CE_Aqua_V2 is
   now 27 in stock (26 sellable, 1 `incomplete`) and 25 missing.

CE_Dongle_V2 after part A: 32 in stock (all 32 held `faulty`, Batch 1), 15
missing, 0 sellable.

### Part B — APPLIED 2026-10-03

#3008 `dongle_4D8694` and `dongle_2043A84D8174` were read at 20:36:59 and
20:39:05, in the middle of the boards held as unprogrammed (readout positions
35 and 38 of 43). Both are fully assembled with an enclosure (user,
2026-10-03): condition `ok`. Applied by
`scripts/stock-count-dongle-v2-partB-2026-10-03.py`:

1. #3008 came off shipment #23, back to stock.
2. Placeholder #28532 (`unidentified`, Batch 5) takes its place on shipment
   #23, so ZAL 00001/07/2025 keeps its invoiced 455.
3. `dongle_2043A84D8174` is device #28533: Batch 5, produced 2026-09-10
   16:12:56, in stock, with its broker account (derived, equal to the bench
   report's). **The broker password file must be regenerated before this unit
   ships** (`GET /api/flasher/mosquitto`, hashed with `mosquitto_passwd -U`),
   or it cannot connect.

CE_Dongle_V2 after both parts: 34 in stock (32 held `faulty`, 2 sellable), 15
missing. The 10 unprogrammed boards get their records when the bench programs
them.

## CE_Dongle_V3

Reconciled on 2026-10-03, read-only. **The desk readout is NOT a full
inventory** — unlike the Aqua and V2 shelf counts, it covered only the desk —
so absence from it proves nothing, and no unit was marked missing.

The platform holds 26 V3 devices: 5 MAC-less V3.1 prototypes shipped
(order #5, 2025-11-03), 10 MAC-less V3.2 prototypes in stock (Run #1, held
`prototype`), 10 Run #2 V3.3 units shipped (order #6, 2026-08-03: 7 with MACs
+ 3 placeholders), and `ac:eb:e6:d3:46:98` in stock (Batch 1 — 50 pcs, the
order RA 00001/09/2026 batch, not on the desk).

The 12 desk units against that:

| Desk units | Records |
|---|---|
| `d2:59:90` (Tasmota), `2f:74:74` (Tasmota), `2e:9c:ac` (Tasmota) | **recorded shipped** on order #6 — never left (user, 2026-10-03) |
| 4 erased v3.3 (`d3:d1:9c`, `d3:8e:68`, `d3:36:ac`, `d2:79:08`) | no records. Which build they are from is open |
| 3 erased v3.2 (`2e:a4:54`, `30:af:ac`, `2f:78:8c`) + `30:af:b0` (Tasmota, default topic) | Run #1 builds (user, 2026-10-03). **FILLED placeholders #11476-79** by MAC on 2026-10-03 (`scripts/fill-v3-placeholders-2026-10-03.py`, the 0054 pattern); 6 Run #1 placeholders stay unnamed |
| `40:4c:ca:5e:e8:4c` v3.1 (Tasmota 15.1.0.3, default topic) | no records |

**User facts 2026-10-03:** the 3 desk units
(`d2:59:90`, `2f:74:74`, `2e:9c:ac`) ARE on the desk and were never sent,
although order #6 lists them; all three are V3.3 (the readout sorted two as
v3.2 by mistake). **Columbus
received V3.2 prototypes, not V3.3 — "5, I think".** Order #6 (2026-08-03,
10 x 450 PLN, no invoice, no reference) was generated from Run #2 (V3.3)'s
typed sale fields by the removed startup migration, so its delivery of 10
Run #2 units is wrong as a whole. Run #1 (V3.2, 10 records) shows all 10 in
stock, of which 4 are now named desk units — so at most 6 Run #1 records can
be the delivered ones.

**User facts 2026-10-03, the full V3 prototype story:** Columbus placed NO
V3 order before the 50-piece one (RA 00001/09/2026). Orders #5 (5 x V3.1,
2025-11-03) and #6 (10 x V3.3, 2026-08-03) are artifacts the removed
startup migration made from typed run sale fields — not orders. Every V3.1,
V3.2 and V3.3 prototype was originally STOCKED. What really left: **5 x V3.2
sent to Columbus, and 1 x V3.3 given to Columbus.** Everything else is a
prototype in stock, not sellable. Planned correction: reverse shipments #5
and #6 and cancel both orders (an order with device history cannot be
deleted); record the 6 real deliveries on one new non-invoiced order, on
unnamed placeholders (which exact units went is unknown); set every other
prototype record to condition `prototype`.

**APPLIED 2026-10-03** by `scripts/v3-prototypes-cleanup-2026-10-03.py`:
orders #5 and #6 cancelled with their shipments reversed; new order #1556
(Columbus, 0 PLN — no order or invoice existed) with shipment #2308 (5 x V3.2,
2026-09-03, date approximate, records #11480-84) and #2309 (1 x V3.3,
2026-09-26, record #11493). CE_Dongle_V3 after: 20 in stock (19 `prototype`
+ Batch 1's `ac:eb:e6:d3:46:98`), 6 shipped. The cancelled orders still
DISPLAY their old order values (2,250 and 4,500 PLN); demand ignores them,
and no invoice ever backed them, so no revenue figure moved.

The 4 erased v3.3 units (`d3:d1:9c`, `d3:8e:68`, `d3:36:ac`, `d2:79:08`)
remain without a known build. It only matters for the cost note when they
are banked as pool WIP under 0058 — like the 63 bare Aquas, they get no
device records now. The 3 dead v3.1 desk units could not be read and have
no MACs recorded anywhere.

## Packaging and enclosures

Stated by the user, not verified against the platform yet.

| Item | Quantity | Note |
|---|---|---|
| Shipping carton 100x50x40 fala E (Dongle) | 434 | NOT enough for Batch 8 (800 boards): the rest of the batch still builds, and more boxes must be bought (user, 2026-10-03) |
| Aqua enclosure, the ENC1 + ENC2 PAIR (user, 2026-10-03) | 4 cartons x 50 = 200 pairs | unused; CE_Aqua_V2 is closing, so likely never used |
| Molex 146153-0150 antenna (150 mm, Aqua) | 48 | enough for 48 of the 63 bare PCBs |
| Italtronic 35.0207000.BL (Dongle V2 enclosure), last delivery | 400 loose + 200 fitted to units in production = 600 from that delivery | as the user stated it: 400 enter the pool as raw parts, 200 sit inside unprogrammed WIP devices |
| Loose small enclosures, marking-calibration rejects | count them when disposing (user, 2026-10-03) | attrition: to be disposed of, not sellable |

Still open: whether any Aqua spares are written off rather than kept. The
packaging rows above enter the pool in phase 1 of decision
[0058](../decisions/0058-a-process-is-versioned-stages-over-the-pool.md), at
zero value where their cost sits in closed books.

## Found on the way

- **The bench agent may record a C6's EUI-64 as its MAC.** esptool 4.8.1 prints
  the 8-byte EUI-64 as `MAC:` and the 6-byte MAC as `BASE MAC:` on a C6;
  `EspRun.run` (op `connect`) reads only `MAC:`. Found by reading the code, not
  checked against production. `DeviceUnit.mac` holds 20 characters; an EUI-64
  is 23.
- **Some bare Aqua boards have DTR not wired to IO0**: they reach the ROM only
  with BOOT held. Measured on one board; others read with auto-reset.
