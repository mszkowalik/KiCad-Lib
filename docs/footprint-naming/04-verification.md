# Verification and corrections

Everything in this file was checked **mechanically against the database and the shipped
KiCad library**, not accepted from the proposal drafts. Where a check contradicts the
standard in `01-standard.md`, this file wins and the affected row is called out.

Reproduce any of it with the commands in `05-sources.md` §4.

> ## Resolution status — 2026-07-26
>
> | Finding | Status |
> |---|---|
> | §1 Coverage — 173/173 decided exactly once | ✅ passes, no action |
> | §2 Collisions — one, the intended merge | ✅ passes, no action |
> | §3 Stock overlap — 88 verbatim + 3 justified house keeps = 91 frozen | ✅ passes, no action |
> | §4 Three renames adopt a stock name with differing copper | **Resolved by D3** — all three deferred to Wave 5 (fix copper, then adopt name in one step). No Wave 3/4 rename adopts a stock name; re-verified mechanically |
> | §5 Seven vendor tokens conflict with the canonical table | **Resolved by D1** — derivation rule adopted; 6 names corrected. `Diodes Incorporated` → `DiodesIncorporated` also dissolves the vendor/category ambiguity, so §5.3 rule 5 (family-word prefix) is unused |
> | §6.1 Double renames from rotation-in-name | **Resolved by D3** — rotation is a geometry defect, never a naming fact |
> | §6.2 `CONN-SMD_DF40C-100DS-0.4V-51` disposition | **Still open** — §9 Q1. One of the 173 has an undefined final state until answered |
> | §6.3 Reject Q13 (`_Drill1.98mm`) | **Resolved** — rejected |
> | §7 73 of 76 renames not geometry-verified | **Still true** — spot-check before applying Wave 3 |
> | §8 Manufacturer attributions | ✅ 12/12 correct |
>
> One deliberate consequence of D1: `Relay_DPDT_Omron_G6K-2F-Y` keeps the lowercase-ish
> `Omron` rather than the canonical `OMRON`, because it is a **verbatim stock filename**
> (confirmed present in `Relay_SMD.pretty`) and Tier 0 names are exempt. That is the rule
> working, not an oversight.

---

## 1. Coverage — passes

Extracted every rename row from all nine family tables and cross-joined against the
173 footprints in the database.

| Check | Result |
|---|---|
| Footprints in the library | 173 |
| Covered by exactly one rename row | **173** |
| Missing (no decision) | **0** |
| Appearing in two family tables | **0** |
| Phantom rows (a name not in the library) | **0** |

Action split: **91 keep · 76 rename · 4 delete-unused · 1 merge-duplicate · 1 investigate**.

## 2. Name collisions — one, and it is deliberate

Only one proposed name is claimed twice:

```
Crystal_SMD_3225-4Pin_3.2x2.5mm
   <- Crystal_SMD_3225-4Pin_3.2x2.5mm   [keep]
   <- OSC-SMD_4P-L3.2-W2.5-BL           [merge-duplicate]
```

That is the intended merge — an unused oscillator footprint whose land is a 0.03 mm
duplicate of the crystal land. Not a defect.

**No proposed name shadows a *different* footprint already in our library.**

## 3. Stock overlap — the number that reframes the whole job

```
our footprints        : 173
verbatim KiCad stock  : 88   (50%)
not in stock          : 85
```

The standard marks **91** names frozen, three more than the 88 verbatim matches. Those
three are house-authored names kept deliberately, and each is justified:

| Name | Why kept although not stock |
|---|---|
| `Kinghelm_KH5220-A36` | Already matches KLC's `Vendor_MPN` RF-antenna form (cf. stock `Johanson_2450AT…`) |
| `TerminalBlock_Plug_Invisible` | Intentional zero-pad placeholder for mating plugs that must appear in the BOM but have no land. 16 references — the most-used footprint in its family |
| `HVSSOP-10-1EP_3x3mm_P0.5mm_EP1.57x1.88mm_ThermalVias` | House-authored but already fully on-grammar; verified 10 leads at x=±2.15 on 0.5 mm pitch, EP pad 11 = 1.57×1.88 mm, four 0.6/0.3 mm vias |

Correcting an earlier assumption of mine: `ublox_ZED`, `Xilinx_FGG484`, `Xilinx_FTG256`,
`ESP32-WROOM-32U`, `Osram_BPW34S-SMD` and `Texas_SWRA117D_2.4GHz_Left` look ad-hoc but are
**verbatim stock names**. They are Tier 0 and must not be touched.

## 4. Three renames adopt a stock name whose copper differs — DO NOT APPLY AS WRITTEN

The standard's own anti-shadowing rule (§3.8) says: never mint a name equal to a stock
name unless the copper is identical. Three proposed renames break it. I compared pad
number + position sets between our footprint and the stock file directly.

### 4.1 `TDSON-8_6.15x5.15mm` → `Infineon_PG-TDSON-8_6.15x5.15mm` — **electrically wrong**

```
our pads  : 21   numbers = ['', 1, 2, 3, 4, 5, 6, 7, 8]
stock pads: 21   numbers = ['', 1, 2, 3, 4, 5]
only ours : ('6', 2.925, 0.665) ('7', 2.925, -0.665) ('8', 0.675, 0.0) ('8', 2.925, -1.995)
only stock: ('5', 0.675, 0.0)   ('5', 2.925, -1.995) ('5', 2.925, -0.665) ('5', 2.925, 0.665)
```

Same copper geometry, **different pad numbering**: we number the source pads 6/7/8
individually; stock stacks all of them as pad 5. Adopting the stock name would silently
promise a pin mapping our symbol does not use.

The adversarial critic recorded this one as *"claimed pad-identical — legitimate"*. That
is wrong — it accepted the drafting agent's claim. The geometry above is the evidence.

**Correction:** keep a house name. Do not adopt `Infineon_PG-TDSON-8_6.15x5.15mm` unless
the pad numbering is first reconciled with stock (a geometry change, i.e. Wave 5, not a
rename).

### 4.2 `RELAY-SMD_G6K-2F-X-XX` → `Relay_DPDT_Omron_G6K-2F-Y` — rotated 90°

```
only ours : ('1', -3.8, 3.5) ('2', -0.6, 3.5) ('3', 1.6, 3.5) ('4', 3.8, 3.5) …
only stock: ('1', -3.5, -3.8) ('2', -3.5, -0.6) ('3', -3.5, 1.6) ('4', -3.5, 3.8) …
```

Our pads run along y = ±3.5 varying x; stock runs along x = ±3.5 varying y. The critic
additionally found pad sizes differ (ours 2.1×1.0, stock 1.8×0.8).

**Correction:** either adopt stock geometry *and* the name in one step (Wave 5), or rename
to a house form. Doing the rename in Wave 4 and the geometry in Wave 5 renames twice.

### 4.3 `BAT-TH_KEYS2466` → `BatteryHolder_Keystone_2466_1xAAA` — origin and drill differ

```
only ours : ('1', -22.35, 0.0) ('2',  22.35, 0.0)     # origin centred
only stock: ('1',   0.00, 0.0) ('2',  44.70, 0.0)     # origin at pad 1
```

Pad *spacing* is identical (44.7 mm) — only the origin differs. The critic also found
drill 1.2 / pad 1.6 versus stock 1.02 / 2.0.

**Correction:** same as 4.2 — one combined step, or a house name.

> **The general lesson, and it belongs in the standard:** a Tier 0 adoption is a claim
> about copper, so it must be *verified* before the rename is proposed, not asserted.
> Add this to the Wave 0 validator rules: reject any proposed name equal to a stock
> filename unless pad numbers, positions, sizes and drills all match.

## 5. Vendor tokens conflict with the canonical manufacturer table

Parsed the 122 canonical manufacturer values out of the `conventions-library` skill and
compared them against every vendor token in a proposed name.

### 5.1 Casing conflicts

| Proposed name | Token | Canonical value |
|---|---|---|
| `LED_Osram_SFH4725AS_3.8x3.8mm` | `Osram` | **OSRAM** |
| `Relay_DPDT_Omron_G6K-2F-Y` | `Omron` | **OMRON** |
| `Converter_DCDC_MeanWell_NID65_Vertical` | `MeanWell` | **MEAN WELL** |
| `Converter_DCDC_MeanWell_NID65_Horizontal` | `MeanWell` | **MEAN WELL** |

This is not a set of typos — it is a **structural clash with no rule to resolve it**:

- KLC G1.1 forbids spaces in footprint names, so `MEAN WELL` *cannot* be used literally.
- KLC G1.6 says capitalise manufacturer names as the manufacturer does — which gives
  `OSRAM` and `OMRON`, not `Osram`/`Omron`.
- But stock KiCad ships `Relay_SPDT_Omron_G2RL-1`, which we **keep** as Tier 0. So the
  library will legitimately contain `Omron` (frozen stock) and would contain `OMRON`
  (house-minted) side by side.

### 5.2 Ambiguous or truncated vendor tokens

| Proposed name | Problem |
|---|---|
| `Texas_VSON-14-1EP_4x3mm_P0.5mm_ThermalVias` | Canonical is **Texas Instruments**; `Texas` alone is a truncation |
| `ST_LGA-12_2x2mm_P0.5mm_LayoutBorder4x2y` | Canonical is **STMicroelectronics**; `ST` is an unregistered abbreviation |
| `Diodes_V-DFN3020-13-A_3x2mm_P0.45mm` | Vendor token `Diodes` is indistinguishable from the **Diodes category** |

### 5.3 Required rule — decide this before any Wave 3/4 rename

There must be one deterministic function from *canonical manufacturer* to
*footprint vendor token*. Proposed:

1. Take the canonical value from the `conventions-library` table.
2. Remove spaces and dots; keep everything else, **including casing**.
   `MEAN WELL` → `MEANWELL`, `Pulse Electronics` → `PulseElectronics`,
   `Texas Instruments` → `TexasInstruments`, `STMicroelectronics` → `STMicroelectronics`.
3. Never abbreviate, never truncate.
4. **Tier 0 names are exempt** — a stock filename keeps its own spelling forever, so
   `Omron` in `Relay_SPDT_Omron_G2RL-1` stays.
5. Where the derived token collides with a category word (`Diodes`), prefix the family
   word so the vendor is unambiguous in position: `DFN_Diodes_V-DFN3020-13-A_…`.

Applying it changes the four rows in §5.1 and the three in §5.2.

## 6. Structural problems the adversarial critic found, carried forward

| # | Finding | Status |
|---|---|---|
| 1 | **Double renames.** §3.6 makes the name a function of the file's rotation, so `WSON-8-1EP_5x6mm`, the Winbond USON-8/WSON-8 pair, Omron G6K and Keystone 2466 get renamed in Wave 4 and again in Wave 5 for zero net change | **Must fix.** Name from datasheet nominal; let the validator flag rotation as a geometry defect instead of encoding it in the string |
| 2 | **`CONN-SMD_DF40C-100DS-0.4V-51` has no decided disposition** — §9 Q1 offers two branches (delete-and-repoint vs rename), so one of the 173 has an undefined final state | **Open.** The "91 keep + 76 rename + 5 delete" total is only exact once Q1 is answered |
| 3 | **Reject Q13** — `Lightpipe_FIX-LEMB2-4.8V0-F_Drill1.98mm` names a drill the footprint deliberately does not contain | **Agreed, reject.** It contradicts the document's own objection to names that state things the copper does not do |

## 7. What is *not* verified

Stated plainly so nothing here is over-trusted:

- **Only 3 of the 76 renames had their geometry checked** (the three stock-name
  collisions in §4). The other 73 proposed names are internally consistent with the
  grammar but their dimensional claims — EP sizes, pitches, body sizes — were taken from
  the drafting agents, which read the footprint sources but whose arithmetic I did not
  re-derive.
- **Five of the nine family agents ran with the safety classifier unavailable.** Their
  output is structurally sound and their manufacturer attributions verified (§8), but
  treat individual dimensional claims as needing a spot-check before you apply Wave 3.
- **No 3D-model, courtyard or drill claim** in the Wave 5 list was independently checked.

## 8. Manufacturer attributions — spot-checked, all correct

Twelve proposed names hard-code a manufacturer. Every one matches the database:

| Component | Proposed vendor token | `Manufacturer 1` in DB |
|---|---|---|
| HU2032-LF | Renata | Renata |
| KEYS2466 | Keystone | Keystone |
| BSC0702LS | Infineon | Infineon |
| SFH4725AS-DBEB-1113REEL | Osram → **OSRAM** | OSRAM |
| NID65-12 | MeanWell → **MEANWELL** | MEAN WELL |
| SRP4020TA-1R0M | Bourns | Bourns |
| GPS1003 | Rainsun | Rainsun |
| ACS0301U | Abracon | Abracon |
| W3011 | PulseElectronics | Pulse Electronics |
| DB301V-3.5-2P-GN-S | Dorabo | Dorabo |
| AFC01-S22FCC-00 | Jushuo | Jushuo |
| W25Q16JVUXIQ | Winbond | Winbond |

12 of 12 correct — the drafting agents worked from the real database, not from guesses.
