# Footprint naming

**Status: APPLIED to the live library** (`http://192.168.200.28/lib`) on 2026-07-30.
**77 footprints renamed, all 171 carry a package name, zero EasyEDA/LCSC-style names remain.**
See `07-applied-state.md` for the as-built record read back from production.

> The tables in `02-migration-173.md` are the *proposal* as drafted against the dev database
> (173 footprints, before the work ran). Where they disagree with `07-applied-state.md`, the
> applied-state file is the truth.

> **Renaming does not update boards already laid out.** They keep the old footprint string
> until *Update Footprints from Library* is run in KiCad. One connector
> (`DF40C-100DS-0.4V-51`) additionally had **wrong pin numbering** and its pads physically
> move — any board using it must be re-routed and re-checked.

| File | What it is |
|---|---|
| `07-applied-state.md` | **What is actually live** — every rename, every package name, read back from production |
| `01-standard.md` | The naming standard: tier rule, the one grammar, global mechanics, per-family rules, `display_name`, migration waves, open questions, validator rules |
| `02-migration-173.md` | **Every existing footprint, decided.** 173 rows — current name → action → proposed name → wave → reason |
| `03-new-parts-catalogue.md` | **Naming parts you don't own yet.** ~8,500 stock footprints distilled into reference tables per family, plus a derivation procedure for anything not in a table |
| `04-verification.md` | What I checked mechanically, what I found wrong in the proposal, and what remains unverified |
| `05-sources.md` | Every standard cited, with URLs, plus commands to reproduce the checks |
| `06-connector-pin-numbering.md` | The Hirose DF40C resolution, and the policy on pin-numbering schemes vs symbol count |

---

## The decision, in one paragraph

**Adopt the KiCad Library Convention (KLC) as the spine — specifically the dialect the
shipped KiCad 10 library actually uses, not the one printed on klc.kicad.org, because the
two differ.** Keep IPC-7351 as a searchable alias field only. Strip EasyEDA/LCSC generator
strings on import. Where KiCad ships a footprint whose *copper* matches ours, take its
filename byte-for-byte and freeze it.

You said you lean toward IPC naming. I went looking for evidence to support that and found
the opposite, so here is the honest case against it:

1. **0 of 15,447** shipped KiCad footprints use IPC-7351 grammar. House parts named that
   way would never sort, autocomplete or diff alongside the libraries every engineer here
   already has open.
2. **It cannot name about 80 of your 173 footprints.** IPC-7351B's scope is land patterns
   derived from JEDEC/EIA/IEC package outlines — connectors, switches, relays, modules,
   antennas, enclosures, battery and fuse holders, SIM sockets and mechanical hardware are
   all out of scope. IPC's own escape hatch for them is literally
   `ManufacturerAbbreviation_ManufacturerPartNumber`.
3. **It can't express what this library actually varies by** — it encodes no exposed-pad
   dimensions (its own authors publish that as a defect) and has no thermal-via concept.
   Six of your IC footprints differ from a sibling *only* by EP size or vias; under IPC
   they'd collide.
4. **`RESC0603` means the imperial 0201.** IPC chip codes are metric. KLC's
   `R_0603_1608Metric` carries both codes and kills that ambiguity outright.

Where IPC genuinely fits — standard SMD IC packages — KLC already gives an equally precise
name that is also readable. So IPC survives as metadata, not as the name.

## The number that reframes the job

**88 of your 173 footprints are byte-identical to KiCad 10 stock names.** Another 3
house-authored names are already on-grammar. So **91 are already correct and get frozen** —
including every high-traffic one (`R_0402_1005Metric` 35 refs, `C_0402_1005Metric` 19,
`TerminalBlock_Plug_Invisible` 16, `SOT-23-3` 11).

This is not a library that needs rebuilding. It needs 76 renames, 5 deletions and one
decision.

| Action | Count |
|--:|---|
| **91** | keep — frozen, no rename ever |
| **76** | rename (32 correctness + 41 grammar + 3 after geometry) |
| **5** | delete — all zero-reference, including one **wrong-pin-numbering bug** |
| **1** | merge duplicate |
| **173** | total — verified: each appears exactly once, **all decided** |

> **One of the deletions is a live bug, not tidying.** `CONN-SMD_DF40C-100DS-0.4V-51`
> numbers its pads 1–50/51–100 by row; the real Hirose part numbers odd/even by row, so
> every net on that connector lands on the wrong contact. Proven from the Raspberry Pi CM4
> pinout — 32 of 32 differential pairs sit on same-parity pins exactly 2 apart, which is
> only physically adjacent under odd/even. See `06-connector-pin-numbering.md`.

## Your electrolytics: already correct

You flagged these as needing an overhaul. They don't — all three are **verbatim stock
names**:

- `CP_Elec_6.3x7.7` ✓ · `CP_Elec_10x10` ✓ · `CP_EIA-7343-31_Kemet-D` ✓

The KiCad convention is `CP_Elec_<diameter>x<height>` (not L×W), and `CP_EIA-<LLWW>-<HH>_<Vendor>-<Case>`
for tantalum. What *is* broken is their **display names** — `CASE-D-6377`, `D10`,
`CASE-D-7343` are two invented schemes, and `CASE-D-6377` misapplies an EIA *tantalum* case
letter to an *aluminium* can. That's a Wave 1 fix with zero board impact.

## Naming a new part — the decision procedure

Run in order, stop at the first match. This terminates in a name for every input.

1. **Does KiCad stock ship a footprint whose land pattern *and pad numbering* match yours?**
   → Take its filename byte-for-byte. Stop.
   Check with: `grep -i '<fragment>' /tmp/kicad_stock_names.txt` (see `05-sources.md` §4).
   **Verify the copper before you claim this** — pad numbers, positions, sizes, drills. Three
   proposed renames failed exactly here (`04-verification.md` §4).
2. **Does it have zero electrical lands?** (logo, enclosure outline, lightpipe, invisible plug)
   → Mechanical form, `Mechanical` token mandatory. Stop.
3. **Is there a published package designation** — JEDEC, EIAJ, EIA case code, IEC — whose
   parameter set fully determines the land?
   - Our copper *is* the generic pattern → **geometric name, no vendor**
     (`QFN-28_4x4mm_P0.5mm`, `R_0603_1608Metric`).
   - Our copper deviates, or the outline is vendor-proprietary → **geometric + vendor**
     (`Winbond_USON-8-1EP_2x3mm_P0.5mm_EP0.3x1.7mm`), per KLC F2.3.
4. **Otherwise** → **vendor + MPN, family word first**
   (`TerminalBlock_Dorabo_DB301V-3.5-2P_1x02_P3.50mm_Vertical`).

Then look up the exact token order for your family in `03-new-parts-catalogue.md` — it has
the tables and a per-family derivation procedure for ICs, all standard passive sizes,
connectors, crystals, switches and mechanical features.

**Never** mint a name equal to a stock filename unless the copper matches. If it differs,
change a real field — add the vendor prefix or record the true measured value. Never
disambiguate with a counter (`_2`, `ThermalVias2`).

## The three blockers — decided 2026-07-26

All three are resolved and already applied to `02-migration-173.md`.

**D1 — Vendor-token derivation.** Canonical manufacturer name, spaces and dots removed,
**casing kept**, never abbreviated or truncated. Tier 0 stock names are exempt and keep
their own spelling.

| Canonical value | Footprint token |
|---|---|
| `OSRAM` | `OSRAM` |
| `MEAN WELL` | `MEANWELL` |
| `Texas Instruments` | `TexasInstruments` |
| `STMicroelectronics` | `STMicroelectronics` |
| `Diodes Incorporated` | `DiodesIncorporated` |
| `Pulse Electronics` | `PulseElectronics` |

Six proposed names corrected. Using the *full* canonical name also dissolves the
`Diodes` vendor-vs-category ambiguity, so no family-word prefix is needed.

**D2 — `_HandSoldering`.** Matches KLC F2.1 #10 verbatim. `_HandSolder` and
`_Handsoldering` are never minted here. The library has **0** footprints with either
spelling today, so nothing changes now. Going forward: stock footprints adopted at Tier 0
keep `_HandSolder` (108 shipped files use it, against 86 for `_HandSoldering`), while
house-authored variants use `_HandSoldering`. Both will legitimately coexist — that is
intended, not drift.

**D3 — Rotation is never encoded in a name.** Names come from datasheet nominal; a rotated
or mis-origined import is a geometry defect for the validator, not a fact for the string.
This kills the double-rename that previously hit four footprints. The three renames that
adopt a stock name whose copper differs are **deferred to Wave 5** — fix copper, then adopt
the name in one step. **No Wave 3 or Wave 4 rename now adopts a stock name.**

Also rejected: §9 Q13 (`Lightpipe_..._Drill1.98mm` named a drill the footprint omits).

## What was done, in order

| Wave | What | Status |
|---|---|---|
| **0** | Standard published into the `conventions-footprints` skill (v7); Tier 0 names frozen | done |
| **1** | `display_name` pass — every footprint now carries a package name | done (171/171) |
| **2** | 5 zero-reference footprints deleted (source archived in the audit row) | done |
| **2b** | DF40C wrong pin numbering — stock footprint imported, component repointed to v4, old one deprecated | done |
| **3–4** | 75 correctness + grammar renames | done |
| **5** | The 2 that could not take a stock name — true measured values recorded instead | done |

Verified after each step: 0 dangling references, 0 header/filename mismatches, 0 mirror
warnings on a full rebuild.

## Still open

- **Symbol layout for connectors — in progress.** Every dual-row connector symbol was
  checked; only `DF40C-100DS` was wrong (its right column ran 100 down to 51). The fix is a
  new generic `Conn_02x50_Odd_Even`, **filed as draft proposal 154 and awaiting approval in
  the Proposals view**. Approving it also removes one per-MPN symbol. See
  `06-connector-pin-numbering.md` §3.
- **`Kinghelm` vs `Shenzhen Kinghelm Elec`.** The new switch footprint uses `Kinghelm` to
  match its two siblings, but the component's canonical manufacturer is
  `Shenzhen Kinghelm Elec`. `conventions-library` records this as an unresolved open item —
  it needs one house decision, then a sweep.
- **Generic connector symbols.** Re-measured: **4 of 26** connector symbols are per-MPN, not
  12 of 27. `DF40C-100DS` is handled above. `FPC-05F-24PH20` needs a footprint pad
  renumber first (`25`/`26` → `MP`, one net, as KLC does). `HU2032-LF` needs pin names, not
  a generic. `USB-B01` needs only a rename. See `06-connector-pin-numbering.md` §2.2–2.3.
