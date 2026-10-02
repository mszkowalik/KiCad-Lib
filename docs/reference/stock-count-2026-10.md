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

- The 2 MAC-less prototypes in stock (run 10733) were not on the shelf
  readout. A MAC-less record cannot be matched, and the user does not know
  whether they exist (2026-10-02). They stay in stock, held as `prototype`.
- The spare boards: rule 5 of the 2026-09-18 stock model
  ([dongle-stock-reconciliation.md](dongle-stock-reconciliation.md)) says a
  board never programmed is a pool quantity, not a device. The recommended
  alternative is a device row by MAC with a new condition `unprogrammed`, set
  only from a bench observation. Not decided; either way it needs a decision
  record.

## CE_Dongle_V2

Not worked yet.

| On the shelf | Units | Platform says |
|---|---|---|
| Programmed (`dongles_v2.json`) | 34 | 32 = the held Batch 1 old-button units · 1 shipped (Batch 5) · 1 not on the platform |
| Unprogrammed, going to production (`dongles_v2.json` + `dongles_v2_1.json`) | 10 | none on the platform |

In stock on the platform but not seen: 3 faulty units with no batch, and 12
MAC-less prototypes. `d4:e9:f4:f5:8c:a4`, among the 10 unprogrammed, is the
unit [dongle-stock-reconciliation.md](dongle-stock-reconciliation.md) lists as
never passed.

## CE_Dongle_V3

Not worked yet. 12 desk units read (`dongles_v3_1/2/3.json`): 5 run Tasmota, 7
have an empty flash. 3 are recorded shipped (Run #2, prototypes V3.3), 9 are not
on the platform. In stock on the platform but not seen: 10 MAC-less V3.2
prototypes and `ac:eb:e6:d3:46:98` (Batch 1). Two units carry the default
`tasmota_<MAC>` topic, so they were probably never configured by the
production procedure. The C6 USB serial number equalled the MAC on all 12.

## Packaging and enclosures

Stated by the user, not verified against the platform yet.

| Item | Quantity | Note |
|---|---|---|
| Shipping carton 100x50x40 fala E (Dongle) | 434 | Batch 8 should use all of them (to verify against its size) |
| Aqua enclosure | 4 cartons x 50 = 200 | unused; CE_Aqua_V2 is closing, so likely never used |
| Molex 146153-0150 antenna (150 mm, Aqua) | 48 | enough for 48 of the 63 bare PCBs |
| Italtronic 35.0207000.BL (Dongle V2 enclosure), last delivery | 400 loose + 200 fitted to units in production | "stock from that delivery should be 600" |
| Loose small enclosures, marking-calibration rejects | not counted | attrition: to be disposed of, not sellable |

Questions still open: is Batch 8 a CE_Dongle_V2 batch of 434 units, leaving 166
enclosures after it? Is 600 the quantity received, or the quantity expected on
hand? How many loose enclosures go to disposal? Is one Aqua enclosure the pair
ENC1 + ENC2? Do the Aqua spares stay in stock at cost, or are any written off?

## Found on the way

- **The bench agent may record a C6's EUI-64 as its MAC.** esptool 4.8.1 prints
  the 8-byte EUI-64 as `MAC:` and the 6-byte MAC as `BASE MAC:` on a C6;
  `EspRun.run` (op `connect`) reads only `MAC:`. Found by reading the code, not
  checked against production. `DeviceUnit.mac` holds 20 characters; an EUI-64
  is 23.
- **Some bare Aqua boards have DTR not wired to IO0**: they reach the ROM only
  with BOOT held. Measured on one board; others read with auto-reset.
