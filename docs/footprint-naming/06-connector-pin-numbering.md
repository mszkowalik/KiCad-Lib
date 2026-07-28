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

27 base symbols serve the Connectors category:

| Kind | Count | Examples |
|---|--:|---|
| **Generic, already reusable** | 15 | `Conn_01x02` (9 components), `Conn_01x04` (4), `Conn_01x08` (3), `Conn_02x05_Odd_Even`, `Conn_Coaxial` (3) |
| **Per-MPN, one symbol per part** | 12 | `DF40C-100DS`, `FPC-05F-24PH20`, `USB-B01`, `HU2032-LF`, `SIM_NANO_Socket`, `8P8C` ×3, `TERMINAL_BLOCK_PLUG` |

The decisive number: **only 4 of the 27 are dual-row at all** — three `Odd_Even` and one
`Top_Bottom`. So standardising the numbering scheme would eliminate **at most one symbol**,
while breaking datasheet correspondence on every part not natively odd/even.

Your symbol count is not driven by numbering schemes. It is driven by **12 per-MPN symbols**.

### 2.3 The lever that actually works

Standardise the **symbol**, not the numbering.

1. **One generic symbol per `(rows × positions × scheme)`, reused across all vendors.**
   `Conn_02x50_Odd_Even` serves *every* 2×50 odd/even connector — Hirose, JST, Molex alike.
   You already do this for 15 symbols; extend it to the per-MPN ones that carry no special
   semantics:

   | Per-MPN symbol today | Generic replacement |
   |---|---|
   | `DF40C-100DS` | `Conn_02x50_Odd_Even` |
   | `FPC-05F-24PH20` | `Conn_01x24` |
   | `Conn_01x22` / `AFC01-S22FCC-00` | `Conn_01x22` (already generic) |

   Keep a dedicated symbol only where the pins have **fixed standardised meaning** and a
   generic one would lose information: `USB_C_Receptacle_*`, `8P8C*`, `SIM_NANO_Socket`,
   `Conn_Coaxial`, `Battery_Holder`, `TERMINAL_BLOCK_PLUG`.

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

Converting the two clearly-generic per-MPN symbols and keeping the rest gives roughly
**25 symbols instead of 27**, with every one datasheet-correct. Forcing a single numbering
scheme would give **26** and introduce a class of silent netlist bug — of which you already
have one live example.

---

## Sources

- Raspberry Pi Ltd, *Compute Module 4 Datasheet* — https://datasheets.raspberrypi.com/cm4/cm4-datasheet.pdf (connector named §675; pinout table used for the parity proof)
- Hirose Electric, DF40C-100DS-0.4V(51) product page — https://www.hirose.com/product/p/CL0684-4033-4-51
- Hirose Electric, DF40 series — https://www.hirose.com/en/product/pr/df40/
- KiCad 10.0.5 stock footprint `Connector_Hirose_DF40.pretty/Hirose_DF40C-100DS-0.4V_2x50_P0.4mm.kicad_mod`
- KiCad generic connector symbols (`Connector_Generic`) for the three dual-row scheme variants
