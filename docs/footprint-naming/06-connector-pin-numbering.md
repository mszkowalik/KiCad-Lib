# Connector pin numbering — policy

Answers two things: what to do about the Hirose DF40C, and whether the library should
standardise on a single pin-numbering scheme.

---

## 1. The DF40C-100DS is a correctness bug, not a naming problem

`CONN-SMD_DF40C-100DS-0.4V-51` numbers its pads **1–50 along the top row, 51–100 along the
bottom**. The real Hirose part numbers **odd contacts in one row, even contacts in the
other**. Every net on that connector currently lands on the wrong physical contact.

### The proof

The Raspberry Pi Compute Module 4 uses this exact connector — the CM4 datasheet names it
(`DF40C-100DS-0.4v`, §675). Its published pinout assigns differential pairs like this:

```
 1  GND                 2  GND
 3  Ethernet_Pair3_P    4  Ethernet_Pair1_P
 5  Ethernet_Pair3_N    6  Ethernet_Pair1_N
 7  GND                 8  GND
 9  Ethernet_Pair2_N   10  Ethernet_Pair0_N
11  Ethernet_Pair2_P   12  Ethernet_Pair0_P
```

Machine-checked across the whole table: **32 differential pairs, every single one on
same-parity pins exactly 2 apart. Zero exceptions.**

A differential pair only routes if P and N are physically adjacent. Pins 3 and 5 are
adjacent **only when same-parity contacts are consecutive in a row** — i.e. odd/even rows.
Under our numbering, pin 4 (`Ethernet_Pair1_P`, a *different* pair) sits physically between
pin 3 and pin 5. Nobody lays out gigabit Ethernet with a foreign signal inside the pair.

Confirmed independently: our copper matches **0 of 100** pads against the stock
`Hirose_DF40C-100DS-0.4V_2x50_P0.4mm`, which uses odd/even (pad 1 and pad 2 share an x
coordinate on opposite rows).

### Disposition

| Step | Action |
|---|---|
| 1 | **Delete** `CONN-SMD_DF40C-100DS-0.4V-51` (0 board references — nothing to break) |
| 2 | **Adopt** the verbatim stock footprint `Hirose_DF40C-100DS-0.4V_2x50_P0.4mm` |
| 3 | **Renumber** the `DF40C-100DS` base symbol to odd/even so symbol pin N = contact N |
| 4 | Repoint the `DF40C-100DS-0.4V-51` component |

Moved to **Wave 2** and reclassified as a correctness bug. It was the last undecided
footprint — **all 173 are now decided.**

> This is also why the naming standard's Tier 0 rule demands that copper be *verified*
> before a stock name is adopted. Here the check found a wrong footprint, not a wrong name.

---

## 2. Should the library standardise on one numbering scheme?

**No — and your own data shows the saving isn't there. But the goal behind the question is
right, and there is a better lever.**

### 2.1 Why footprint pad numbers cannot be a house choice

A pad number is not a label we own. It is a claim that *this copper is the contact the
manufacturer calls N*. Three things depend on it:

- **The mating part.** The plug's contact 7 touches the receptacle's contact 7. If we
  renumber, the netlist is silently wrong — exactly the DF40C bug above.
- **The datasheet.** Every review, debug session and assembly query reads the vendor's
  numbers. A house renumbering means every conversation needs a translation table.
- **Drop-in replacement.** Renumbered footprints can never be swapped for a stock KiCad or
  vendor-supplied footprint, because theirs use manufacturer numbering.

Real parts genuinely use different schemes, which is why KiCad ships three generic dual-row
variants rather than one:

| Scheme | Pattern | Typical parts |
|---|---|---|
| `Odd_Even` | odd one row, even the other | ribbon/IDC headers, board-to-board (DF40) |
| `Top_Bottom` | 1..n one row, n+1..2n the other | many FPC/FFC and mezzanine parts |
| `Counter_Clockwise` | continuous around the perimeter | card edge, some D-sub |

Forcing one scheme onto a part that physically uses another does not simplify anything — it
just moves the complexity into a wrong netlist.

### 2.2 What your library actually looks like

Re-measured against production on 2026-07-30. **26 base symbols serve 58 connector
components.** The earlier count of 27 with "12 per-MPN" was too pessimistic — most of those
12 are stock KiCad symbols that are already generic across vendors.

| Kind | Count | Symbols |
|---|--:|---|
| **Stock `Connector_Generic`** — pure `(rows × positions × scheme)` | 12 | `Conn_01x01_Socket`, `Conn_01x02` (9 comps), `Conn_01x04` (4), `Conn_01x06`, `Conn_01x08` (3), `Conn_01x10`, `Conn_01x12` (2), `Conn_01x22`, `Conn_02x05_Odd_Even`, `Conn_02x07_Odd_Even`, `Conn_02x12_Top_Bottom`, `Conn_02x15_Odd_Even` |
| **Stock `Connector`** — fixed standardised pinout, still vendor-neutral | 6 | `8P8C`, `8P8C_Shielded`, `8P8C_LED_Shielded`, `Conn_ARM_JTAG_SWD_10`, `Conn_Coaxial` (3 comps), `USB_C_Receptacle_USB2.0_16P` (2) |
| **House, generic name, fixed semantics — keep** | 4 | `Conn_IPEX`, `Battery_Holder`, `SIM_NANO_Socket`, `TERMINAL_BLOCK_PLUG` (16 comps) |
| **Genuinely per-MPN** | 4 | `DF40C-100DS`, `FPC-05F-24PH20`, `HU2032-LF`, `USB-B01` |

Verified pin-by-pin: a symbol counts as "fixed semantics" only when its pins carry real
names. `SIM_NANO_Socket` has `CLK/GND/I-O/RST/VCC/VPP`, `USB-B01` has `VBUS/D+/D-/GND`,
`Conn_ARM_JTAG_SWD_10` has `SWDIO/TMS`, `VTref` and the rest. The four per-MPN symbols name
their pins with bare numbers, which is what makes them convertible.

The decisive number for the numbering question is unchanged: **only 4 of the 26 are dual-row
at all** — three `Odd_Even` and one `Top_Bottom`. So standardising the numbering scheme would
eliminate **at most one symbol**, while breaking datasheet correspondence on every part not
natively odd/even.

### 2.3 The lever that actually works

Standardise the **symbol**, not the numbering.

1. **One generic symbol per `(rows × positions × scheme)`, reused across all vendors.**
   `Conn_02x50_Odd_Even` serves *every* 2×50 odd/even connector — Hirose, JST, Molex alike.
   You already do this for 18 symbols. Only four remain per-MPN:

   | Per-MPN symbol | Pins | Generic replacement | Blocker |
   |---|--:|---|---|
   | `DF40C-100DS` | 100 | `Conn_02x50_Odd_Even` | none — proposed 2026-07-30 |
   | `FPC-05F-24PH20` | 26 | `Conn_01x24_MountingPin` (stock, 25 pins) | footprint numbers its two shell tabs `25`/`26`; stock numbers both `MP` (one net) |
   | `HU2032-LF` | 3 | none — needs pin names, not a generic | pins named `1`/`2`/`3`; polarity is not recorded |
   | `USB-B01` | 6 | keep the symbol, rename it | semantics are real (`VBUS`/`D+`/`D-`/`GND`); only the MPN-shaped *name* is wrong |

   The same shell-tab mismatch applies to `Jushuo_AFC01-S22FCC-00_1x22-1MP`, whose pads `23`
   and `24` face stock `Conn_01x22_MountingPin`'s single `MP`. Its symbol `Conn_01x22` is the
   stock 22-pin generic, so the two mounting pins are currently unconnected in the symbol.

   Keep a dedicated symbol only where the pins have **fixed standardised meaning** and a
   generic one would lose information: `USB_C_Receptacle_*`, `8P8C*`, `SIM_NANO_Socket`,
   `Conn_Coaxial`, `Conn_IPEX`, `Battery_Holder`, `TERMINAL_BLOCK_PLUG`.

   > **The `MP` question is a footprint decision, not a symbol one.** KLC's `-1MP` token
   > counts mounting *nets*, not pads: stock `Hirose_FH12-10S-0.5SH_1x10-1MP` has two
   > physical pads, both numbered `"MP"`. No shipped footprint uses `-2MP` (0 of 15,447).
   > Our two FPC footprints therefore carry the right name but the wrong pad numbers.
   > Renumbering merges two nets into one, so it changes the netlist — but both parts have
   > **zero usage in the latest snapshot of all three tracked projects**, so the change is
   > free today.

2. **Standardise the symbol *layout*, which is genuinely free.** Pin numbers follow the
   manufacturer; pin *positions* follow the house rule. This is where your "left odd, right
   even, top to bottom" instinct belongs, and it costs nothing:
   - dual-row `Odd_Even`: odd pins down the left in ascending order, even pins down the
     right in ascending order, pin 1 top-left
   - single row: ascending top to bottom on the left
   - geometry per [`conventions-symbols`](../../.claude/skills/kicad-conventions-symbols/SKILL.md):
     2.54 mm pitch, 1.27 mm box margin, group gaps

   Applied consistently, every connector symbol in the library *looks* the same and reads
   the same, while every pad number still matches its datasheet. That gets you the
   readability you were after without the netlist risk.

3. **Let the scheme live in the symbol name**, as KiCad does. `Conn_02x50_Odd_Even` versus
   `Conn_02x50_Top_Bottom` is self-documenting: the reader knows which physical part it
   fits, and picking the wrong one is visible rather than silent.

### 2.4 Policy

- **Footprint pad numbering always follows the manufacturer.** Never renumber to fit a house
  scheme. If a footprint's numbering disagrees with the datasheet, that is a bug to fix, not
  a convention to keep.
- **Symbols are generic and keyed on `(rows, positions, scheme)`**, named
  `Conn_<rows>x<pos>[_<Scheme>]`. A per-MPN symbol needs a justification: fixed pin
  semantics, not convenience.
- **Symbol layout is house-standard** (§2.3 item 2) and independent of the numbering scheme.
- **Verify numbering against the datasheet before publishing any connector**, using the
  differential-pair parity test above where the part carries diff pairs — it is a fast,
  decisive check.

### 2.5 Expected result

Converting `DF40C-100DS` and `FPC-05F-24PH20` and keeping the rest gives **24 symbols
instead of 26**, with every one datasheet-correct. Forcing a single numbering scheme would
give 25 and introduce a class of silent netlist bug — of which you already had one live
example.

---

## 3. Symbol layout — applied 2026-07-30

The house layout rule from §2.3 item 2 is now checked against every dual-row connector
symbol in the library:

| Symbol | Left column, top to bottom | Right column | Verdict |
|---|---|---|---|
| `Conn_02x05_Odd_Even` | 1, 3, 5, 7, 9 | 2, 4, 6, 8, 10 | correct |
| `Conn_02x07_Odd_Even` | 1, 3 … 13 | 2, 4 … 14 | correct |
| `Conn_02x15_Odd_Even` | 1, 3 … 29 | 2, 4 … 30 | correct |
| `Conn_02x12_Top_Bottom` | 1 … 12 | 13 … 24 | correct — this *is* the odd/even layout for a top/bottom part |
| `DF40C-100DS` | 1 … 50 | **100 … 51 (descending)** | wrong — the right column ran upside down |

So only one symbol needed the fix. It gets it by being replaced with the generic
`Conn_02x50_Odd_Even` rather than edited, which closes the layout gap and the per-MPN gap in
one change.

### 3.1 How `Conn_02x50_Odd_Even` was built

KiCad ships `Odd_Even` generics only from `02x02` to `02x40`, so `02x50` had to be authored
here. It was not drawn by hand. KiCad's own `kicad-library-utils` autogen geometry was
re-implemented, and the re-implementation was required to reproduce the **shipped** `02x02`,
`02x05`, `02x07`, `02x15`, `02x25` and `02x40` symbols **byte-for-byte** before it was
allowed to emit `02x50`. All six matched.

The derived generator rule, for `n` rows at 2.54 mm pitch:

```
top_y   = floor((n - 1) / 2) * 2.54
pin i   left  at (-5.08, top_y - i*2.54, 0)    number 2i+1
        right at ( 7.62, top_y - i*2.54, 180)  number 2i+2
box     (-1.27, top_y + 1.27) .. (3.81, top_y - (n-1)*2.54 - 1.27)
```

For `n = 50` that gives pin 1 at y = 60.96 and pin 100 at y = −63.5.

Pin *numbers* are unchanged in meaning — pin N is still contact N — so no netlist moves.

> **Known limitation, inherited from stock.** The symbol keeps stock's
> `ki_fp_filters` value `Connector*:*_2x??_*`, which does not match the `7Sigma:` namespace.
> The filter only narrows KiCad's footprint chooser, and every stock generic already adopted
> here has the same gap. Changing it would break byte-identity with stock for no real gain.

---

## Sources

- Raspberry Pi Ltd, *Compute Module 4 Datasheet* — https://datasheets.raspberrypi.com/cm4/cm4-datasheet.pdf (connector named §675; pinout table used for the parity proof)
- Hirose Electric, DF40C-100DS-0.4V(51) product page — https://www.hirose.com/product/p/CL0684-4033-4-51
- Hirose Electric, DF40 series — https://www.hirose.com/en/product/pr/df40/
- KiCad 10.0.5 stock footprint `Connector_Hirose_DF40.pretty/Hirose_DF40C-100DS-0.4V_2x50_P0.4mm.kicad_mod`
- KiCad generic connector symbols (`Connector_Generic`) for the three dual-row scheme variants
