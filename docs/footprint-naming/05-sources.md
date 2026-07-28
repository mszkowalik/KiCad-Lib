# Sources

Every rule in `01-standard.md` traces to one of these. All were fetched or read during the
research pass; nothing here is from recollection. Where a source contradicts another, the
resolution is recorded in `01-standard.md` §7 and `04-verification.md`.

---

## 1. KiCad Library Convention (KLC) — the adopted spine

The normative text. Fetched page by page 2026-07-25.

| Rule | URL | Used for |
|---|---|---|
| F2 index | https://klc.kicad.org/footprint/f2/ | index of F2.1–F2.5 |
| **F2.1** | https://klc.kicad.org/footprint/f2/f2.1/ | *General footprint naming conventions* — the master 10-point rule and the field order |
| **F2.2** | https://klc.kicad.org/footprint/f2/f2.2.html | *Footprint naming field prefixes* — the B / D / H / L / O / W / EP / P / T table |
| **F2.3** | https://klc.kicad.org/footprint/f2/f2.3/ | *Manufacturer specific version of generic footprints* — the Tier 2 rule |
| F2.4 | https://klc.kicad.org/footprint/f2/f2.4/ | naming for non-standard pin numbering |
| F2.5 | https://klc.kicad.org/footprint/f2/f2.5.html | pointer to the F3.x per-family schemes |
| F3 index | https://klc.kicad.org/footprint/f3/ | F3.1 SMD chip · F3.2 Resistor · F3.3 Capacitor · F3.4 SMD IC · F3.5 THT IC · F3.6 Connector · F3.7 Fuse |
| F3.1–F3.7 | `https://klc.kicad.org/footprint/f3/f3.{1..7}/` | the per-family grammars |
| **G1.1** | https://klc.kicad.org/general/g1/g1.1/ | allowed character set — the rule that forbids spaces |
| **G1.6** | https://klc.kicad.org/general/g1/g1.6.html | capitalisation, incl. "manufacturer names capitalised as the manufacturer does" |
| Contributing | https://gitlab.com/kicad/libraries/kicad-footprints/-/raw/master/CONTRIBUTING.md | contains no naming rules of its own; defers to KLC. (The GitLab fetches returned mostly the SPA shell — this is the limit of what was confirmed there.) |

**Known defects in KLC itself**, found by comparing the text against the shipped library:

- **`HandSolder` vs `HandSoldering` is unresolved in the standard.** F2.1 rule #10 lists
  `_HandSoldering`; F3.3's own example uses `_HandSolder`. The shipped library uses both —
  108 files end in `HandSolder`, 86 in `HandSoldering`, plus lowercase `_Handsoldering`.
  KLC picks no winner, so the house must (`01-standard.md` §3).
- **F3.1 lists only C, CP, R, D as chip prefixes.** `L_` and `LED_` are used pervasively in
  the shipped library by analogy, with no rule sanctioning them.
- **F3.4's format string omits the exposed-pad-size field the library actually uses.** The
  documented grammar has no EP-dimension slot, yet ~1000 shipped names carry
  `_EP<x>x<y>mm` between pitch and options.

## 2. The shipped KiCad library — the tie-breaker

Where KLC is silent or self-contradictory, the shipped library decides. This is the single
most useful source in the whole exercise.

```
/Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints
155 *.pretty directories, 15,447 .kicad_mod files   (KiCad 10.0.5)
```

Per-library counts actually read (not sampled) for the reference tables:

| Library | Files | Library | Files |
|---|--:|---|--:|
| `Package_DFN_QFN` | 776 | `Capacitor_THT` | 384 |
| `Inductor_SMD` | 692 | `Package_CSP` | 179 |
| `Package_SO` | 401 | `Crystal` | 192 |
| `Package_BGA` | 234 | `Capacitor_SMD` | 103 |
| `Fuse` | 123 | `Package_QFP` | 102 |
| `Package_SON` | 113 | `LED_SMD` | 99 |
| `Package_TO_SOT_SMD` | 137 | `Diode_SMD` | 83 |
| `Capacitor_Tantalum_SMD` | 56 | `Oscillator` | 70 |
| `Resistor_SMD` | 67 | `Package_LGA` | 41 |

Token meanings were confirmed by reading the `(descr …)` field and the actual pad geometry
inside individual files, not inferred from the filename. Example:

```
Capacitor_SMD.pretty/CP_Elec_10x10.5.kicad_mod
  descr "SMD capacitor, aluminum electrolytic, Vishay 1010, 10.0x10.5mm"
```

— which is what establishes that the `CP_Elec_<a>x<b>` token pair is **diameter × height**,
not L×W.

## 3. Standards considered and rejected, with the evidence

### 3.1 IPC-7351B / IPC-7352 — rejected as the primary name, kept as metadata

Four independent published copies of the naming convention were downloaded and
text-extracted with `pdftotext` (WebFetch could not parse them):

| # | Document | URL |
|---|---|---|
| 1 | PCB Libraries, *IPC-7351B & IPC-7352 Footprint Naming Convention*, rev. 2024-12-03 — the fullest published family table | https://www.cskl.de/fileadmin/csk/dokumente/produkte/pcbl/IPC-7351B_Footprint_Naming_Convention.pdf |
| 2 | PCB Matrix Corp., *IPC-7x51 & PCBM Land Pattern Naming Convention*, 2009-09-13 — original table + the non-standard-package fallback | http://ohm.bu.edu/~pbohn/__Engineering_Reference/pcb_layout/pcbmatrix/IPC-7x51%20&%20PCBM%20Land%20Pattern%20Naming%20Convention.pdf |
| 3 | PCB Libraries, *Library Expert Land Pattern Naming Convention* (2012–2017) — the proposed 7351C-style grammar with lead and thermal-tab fields | https://www.cskl.de/fileadmin/csk/dokumente/produkte/pcbl/ipc_standard_pcb_library_expert_Land_Pattern_Naming_Convention.pdf |
| 4 | *IPC-7351B Naming Convention for Standard SMT Land Patterns* (2003–2007 IPC & PCB Libraries copy) | https://cxem.net/comp/files/comp149_Footprint-Naming-Convention_-Surface-Mount-Components.pdf |

Why it is not the spine — all verified, not asserted:

1. **0 of 15,447** shipped KiCad footprints match IPC-7351 grammar (regex-scanned).
2. **Its scope excludes half our BOM.** IPC-7351B covers land patterns derived from
   JEDEC/EIA/IEC *package outlines*. Connectors, switches, relays, modules, antennas,
   enclosures, battery and fuse holders, SIM sockets and mechanical hardware are out of
   scope — about 80 of our 173 footprints. IPC's own published escape hatch for these is
   literally `ManufacturerAbbreviation_ManufacturerPartNumber`.
3. **It cannot express what this library varies by.** No exposed-pad dimensions — its own
   authors publish that as a defect — and no thermal-via concept at all. Six of our IC
   footprints differ from a sibling *only* by EP size or vias, so under IPC they collide.
4. **Active footgun.** IPC chip codes are metric: `RESC0603` is the imperial **0201**.
   KLC's `R_0603_1608Metric` carries both codes and removes the ambiguity.
5. **Two different numeric encodings** — chip bodies at 0.1 mm, leaded packages at
   0.01 mm — which is the most commonly botched rule in the standard.

Retained as an **`ipc_name` alias field** so SnapEDA / Ultra Librarian / JLCPCB strings
remain searchable (`01-standard.md` §9 Q12).

### 3.2 EasyEDA / LCSC — rejected, and stripped on import

Primary source, authoritative and verbatim: *EasyEDA Footprint Naming Rule Reference*,
v1 2019-02-21 / last updated 2019-12-27, 83 pages, MIT-licensed, by Guodong Xiao et al.

- https://image.easyeda.com/files/EasyEDA+Footprint+Naming+Rule+Reference.pdf
- Doc pages that only point at the PDF:
  https://docs.easyeda.com/en/PCBLib/PCBLib-Naming-Rule/ ·
  https://prodocs.easyeda.com/en/footprint/footprint-naming-rule/

Token grammar decoded from pages 1–3: `L` body length · `W` body width · `P` pitch
(2 dp) · `LS` lead span · `BD` body diameter · `D` pin diameter · `[Q]P` pin quantity ·
`TL/TR/BL/BR` pin-1 quadrant · `BI/FD/RD` polarity direction · `-EP` exposed pad.

Why it is rejected — **it names the component body, not the land pattern**, proven inside
this library:

- `SOT-23-5_L3.0-W1.7-P0.95-LS2.8-BL` declares a 2.8 mm lead span over pads that actually
  reach **3.46 mm**. No token in the name predicts any of the five real pad numbers.
- No manufacturer slot, and no density-level concept, so a hand-solder and a high-density
  variant of one package are indistinguishable.
- No thermal-via token — which is why the library already had to bolt on `-ThermalVias`
  with the wrong separator.
- Its `H` (height) collides with its own documented `H` (Horizontal).
- Literal wildcards: `G6K-2F-X-XX` for a part that is actually G6K-2F-**Y**.
- The spec is not even self-enforced — 2 of our 8 switch names violate its own production.

**LCSC's catalogue "Package" string is a third, separate system.** Verified live:
`C154926` (TXS0104ERGYR) shows package `VQFN-14-EP(3.5x3.5)` on
https://www.lcsc.com/product-detail/C154926.html, while its EasyEDA footprint is
`VQFN-14_L3.5-W3.5-P0.50-BL-EP`. Same company, two different naming systems — do not treat
the catalogue string as a footprint name.

## 4. Reproducing the checks in `04-verification.md`

Index the stock library:

```bash
cd /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints
find . -name '*.kicad_mod' -exec basename {} .kicad_mod \; | sort -u > /tmp/kicad_stock_names.txt
wc -l < /tmp/kicad_stock_names.txt        # 15447
```

List our footprints and compare:

```bash
docker compose exec -T db psql -U kicadlib -d kicadlib -tAc \
  "SELECT name FROM footprints ORDER BY name;" > /tmp/ours.txt
comm -12 <(sort /tmp/ours.txt) <(sort /tmp/kicad_stock_names.txt) | wc -l   # 88 verbatim
```

Before adopting any stock name, diff the copper (this is the check that caught the three
unsafe renames):

```bash
# our source
docker compose exec -T db psql -U kicadlib -d kicadlib -tAc \
  "SELECT fv.source_text FROM footprints f
     JOIN footprint_versions fv ON fv.id = f.current_version_id
    WHERE f.name = '<OUR_NAME>';" > /tmp/ours.kicad_mod
# stock source
find /Applications/KiCad/KiCad.app/Contents/SharedSupport/footprints \
     -name '<STOCK_NAME>.kicad_mod'
# then compare the (pad <number> … (at x y)) sets — numbers AND positions AND sizes AND drills
```

Search for a canonical name before inventing one:

```bash
grep -i '<fragment>' /tmp/kicad_stock_names.txt
```
