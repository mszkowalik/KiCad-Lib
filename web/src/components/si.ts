/** Reading and writing numbers that carry a unit.
 *
 *  A board stackup is typed in two units at once: a fab publishes prepreg in mm
 *  (0.2104) and copper in um (35), and a person thinks in whichever one the figure
 *  came in. Forcing one of them means typing 0.000035 or 210.4 and getting a decimal
 *  point wrong, which is a defect nobody sees until the board is quoted.
 *
 *  So a value is STORED in one base unit and TYPED in any prefix: "35um", "0.035",
 *  "35 µm", "1.4mil" all mean the same copper foil. What comes back out is printed in
 *  the prefix that suits the magnitude, so 0.0152 mm reads as "15.2 um" and 0.2104 mm
 *  as "0.2104 mm".
 */

export type Quantity = "length" | "frequency" | "resistance" | "percent";

/** Multipliers onto the base unit — mm for a length, Hz for a frequency. */
const UNITS: Record<
  Quantity,
  {
    base: string;
    units: Record<string, number>;
    /** The prefixes AUTO-PRINTING may choose, largest first. Deliberately a
     *  subset of `units`: `cm`, `mil` and `in` are accepted on the way IN and
     *  never printed, because nobody quotes a board in centimetres. */
    ladder: [string, number][];
    /** Accept RKM notation (`4k7`). See `parseSi`. Only where it is a real
     *  convention — a resistor is printed `4k7`, a board dimension never is. */
    rkm?: boolean;
  }
> = {
  length: {
    base: "mm",
    units: {
      m: 1000,
      cm: 10,
      mm: 1,
      um: 1e-3,
      "µm": 1e-3,
      "μm": 1e-3, // U+03BC, what most keyboards actually produce
      nm: 1e-6,
      mil: 0.0254,
      thou: 0.0254,
      in: 25.4,
      '"': 25.4,
    },
    // ONE rule for every quantity (user decision 2026-09-12): print in the
    // prefix that puts 1-999 before the decimal point. This REPLACED a
    // length-only rule that switched to um below 50 um, so that a fab's own
    // spelling was preserved — prepreg 3313 read as 0.0994 mm rather than
    // 99.4 um. That reading is gone on purpose; consistency across every
    // unit-carrying field was judged worth more than matching one datasheet's
    // spelling, and a value the user TYPED keeps the unit they typed anyway.
    ladder: [
      ["m", 1000],
      ["mm", 1],
      ["um", 1e-3],
      ["nm", 1e-6],
    ],
  },
  /* Impedance. Only PREFIXES are accepted, never a spelled-out unit: the symbol
     is hard to type on most keyboards and nobody writes "ohm" into a target
     field. A bare number is ohms, so the box keeps behaving exactly as the
     plain number field it replaced.

     `M` and `m` are the one case where CASE MATTERS, and `parseSi` tries the
     exact spelling before the lowercase one specifically so this works: on a
     resistance, `10M` is ten megohms (what every schematic in the world means)
     while `10m` is ten milliohms. Getting that backwards would silently move a
     target by a factor of a billion. */
  resistance: {
    base: "Ω",
    units: {
      "": 1, R: 1, r: 1, "Ω": 1, ohm: 1, ohms: 1,
      k: 1e3, K: 1e3, kohm: 1e3, "kΩ": 1e3,
      M: 1e6, meg: 1e6, mohm: 1e6, "MΩ": 1e6,
      G: 1e9, "GΩ": 1e9,
      m: 1e-3, "mΩ": 1e-3,
      u: 1e-6, "µ": 1e-6, "μ": 1e-6,
    },
    rkm: true,
    ladder: [
      ["GΩ", 1e9],
      ["MΩ", 1e6],
      ["kΩ", 1e3],
      ["Ω", 1],
      ["mΩ", 1e-3],
      ["µΩ", 1e-6],
    ],
  },
  /* A ratio in percent. It takes no prefixes — "3 milli-percent" is not a
     thing anyone writes — but it is here so that a tolerance box is the same
     control as the impedance box beside it: same frame, same ⓘ, same rounding
     rule. A bare number is percent, and typing the sign is optional. */
  percent: {
    base: "%",
    units: { "": 1, "%": 1, pct: 1, percent: 1 },
    ladder: [["%", 1]],
  },
  frequency: {
    base: "Hz",
    units: { hz: 1, khz: 1e3, mhz: 1e6, ghz: 1e9, thz: 1e12, k: 1e3, m: 1e6, g: 1e9 },
    // "2G4" for 2.4 GHz is ordinary in RF part naming.
    rkm: true,
    ladder: [
      ["GHz", 1e9],
      ["MHz", 1e6],
      ["kHz", 1e3],
      ["Hz", 1],
    ],
  },
};

/** Parse text into the base unit, or null when it says nothing usable.
 *
 *  A bare number is taken as `assume` (or the base unit), which is what makes typing
 *  "0.2" into a millimetre field keep working exactly as it did. */
export function parseSi(text: string, q: Quantity, assume?: string): number | null {
  const t = text.trim().replace(",", ".").replace(/\s+/g, "");
  if (!t) return null;

  /* RKM / R-notation (IEC 60062): the PREFIX STANDS IN FOR THE DECIMAL POINT,
     so 4k7 is 4.7 k and 2G4 is 2.4 G. It is how values are printed on parts and
     in most schematic Value fields, which is where the figure being typed here
     usually comes from — and a decimal point is the character most often lost
     to a bad photocopy or a small silkscreen, which is why the notation exists.

     Tried FIRST, and only for <digits><letters><digits>: every other spelling
     has either no trailing digits ("100R", "35um", "4mil") or a real decimal
     point ("2.4e9"), so nothing already accepted changes meaning. Case is
     preserved on the way through, which keeps 1M5 megohms and 1m5 milliohms.

     NOT enabled for LENGTH, and that is the point of the flag rather than a
     blanket rule: a length is based on mm, so `1m5` would read as 1.5 METRES —
     1500 mm — in a box that expects a fraction of one. Nobody writes a board
     dimension that way, so the notation buys nothing there and costs a silent
     factor of a thousand. */
  const rkm = UNITS[q].rkm ? /^([+-]?\d+)([A-Za-zΩµμ]+)(\d+)$/.exec(t) : null;
  if (rkm) {
    const mult = UNITS[q].units[rkm[2]] ?? UNITS[q].units[rkm[2].toLowerCase()];
    if (mult !== undefined) {
      const n = Number(`${rkm[1]}.${rkm[3]}`);
      if (Number.isFinite(n)) return n * mult;
    }
  }
  // The exponent is part of the NUMBER. Without it "2.4e9" split into 2.4 and
  // a suffix "e9" that matches no unit, so the field refused a spelling its own
  // help text advertises ("Type any unit: 2.4GHz, 2400MHz, 2.4e9"). No unit in
  // any table begins with `e`, so taking it greedily is unambiguous.
  const m = /^([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)(.*)$/.exec(t);
  if (!m) return null;
  const n = Number(m[1]);
  if (!Number.isFinite(n)) return null;
  const suffix = m[2].trim();
  const table = UNITS[q].units;
  if (!suffix) {
    const a = assume ? table[assume] ?? table[assume.toLowerCase()] : undefined;
    return n * (a ?? 1);
  }
  const mult = table[suffix] ?? table[suffix.toLowerCase()];
  return mult === undefined ? null : n * mult;
}

/** Trim floating-point noise without throwing away a real digit: 0.2104 stays
 *  0.2104, and 15.200000000000001 becomes 15.2. */
const tidy = (v: number): string => {
  const s = v.toPrecision(12).replace(/0+$/, "").replace(/\.$/, "");
  return String(Number(s));
};

/** How many digits a printed value keeps after the point.
 *
 *  Three, with the prefix ladder guaranteeing at most three BEFORE it — so a
 *  field is never wider than "999.999 MΩ" however large the number behind it.
 *  1 560 432 Ω prints as "1.56 MΩ" and says so. */
const MAX_DECIMALS = 3;

export interface SiParts {
  /** What the box shows. */
  text: string;
  /** Every digit, in the same unit — for the tooltip. */
  exact: string;
  /** True when digits were dropped, so the caller can say so. */
  rounded: boolean;
  /** The unit chosen, so a caller can remember it. */
  unit: string;
}

/** Pick the prefix that puts 1-999 before the decimal point. */
function pickUnit(v: number, q: Quantity, fixedUnit?: string): [string, number] {
  const spec = UNITS[q];
  if (fixedUnit) {
    return [fixedUnit, spec.units[fixedUnit] ?? spec.units[fixedUnit.toLowerCase()] ?? 1];
  }
  const abs = Math.abs(v);
  if (abs === 0) return [spec.base, 1];
  for (const [unit, mult] of spec.ladder) {
    if (abs >= mult) return [unit, mult];
  }
  // Smaller than the smallest prefix: use it anyway rather than printing a
  // string of leading zeros in the base unit.
  const last = spec.ladder[spec.ladder.length - 1];
  return last ?? [spec.base, 1];
}

/** Print a base-unit value, and say whether printing it lost anything. */
export function formatSiParts(v: number | null, q: Quantity, fixedUnit?: string): SiParts {
  if (v === null || v === undefined || !Number.isFinite(v)) {
    return { text: "", exact: "", rounded: false, unit: UNITS[q].base };
  }
  let [unit, mult] = pickUnit(v, q, fixedUnit);
  let scaled = v / mult;
  // ROUND FIRST, THEN RE-PICK. 999 999 999 Hz lands on MHz (it is below 1 GHz),
  // rounds to 1000.000 and printed "1000 MHz" — four digits before the point,
  // which is the one thing the ladder exists to prevent. Rounding can only ever
  // push a value UP across one step, so one re-pick is enough.
  if (!fixedUnit && Math.abs(Number(scaled.toFixed(MAX_DECIMALS))) >= 1000) {
    const spec = UNITS[q];
    const i = spec.ladder.findIndex(([u]) => u === unit);
    if (i > 0) {
      [unit, mult] = spec.ladder[i - 1];
      scaled = v / mult;
    }
  }
  const exact = tidy(scaled);
  const shown = tidy(Number(scaled.toFixed(MAX_DECIMALS)));
  return {
    text: `${shown} ${unit}`,
    exact: `${exact} ${unit}`,
    rounded: shown !== exact,
    unit,
  };
}

/** Print a base-unit value in the prefix that suits its magnitude. */
export function formatSi(v: number | null, q: Quantity, fixedUnit?: string): string {
  return formatSiParts(v, q, fixedUnit).text;
}


/** The units a field will accept, for a tooltip. */
export function unitsOf(q: Quantity): string {
  return Object.keys(UNITS[q].units)
    .filter((u) => !/^[μ]/.test(u) && u !== '"')
    .join(", ");
}

// ------------------------------------------------------------------- copper
/** Copper foil thicknesses that actually occur on a board, in mm.
 *
 *  Both a NOMINAL weight and what a fab publishes as built are listed, because they
 *  are not the same number and only one of them is on any given datasheet. Half an
 *  ounce is 17.5 um nominal; JLCPCB publishes its inner layers as 0.0152 mm — the
 *  etched thickness — and marking the fab's own figure as a mistake would be wrong.
 */
export const COPPER_WEIGHTS: { mm: number; label: string; note: string }[] = [
  { mm: 0.0152, label: "½ oz", note: "half ounce as etched (JLCPCB inner layer)" },
  { mm: 0.0175, label: "½ oz", note: "half ounce, nominal" },
  { mm: 0.035, label: "1 oz", note: "one ounce" },
  { mm: 0.0348, label: "1 oz", note: "one ounce, nominal" },
  { mm: 0.07, label: "2 oz", note: "two ounce" },
  { mm: 0.105, label: "3 oz", note: "three ounce" },
];

const COPPER_TOL = 0.0006; // 0.6 um: tight enough to reject a typo, loose enough for rounding

/** The weight a copper thickness corresponds to, or null when it is not a standard
 *  foil. Never guessed by division — 0.0152 divided by 0.0348 rounds to the wrong
 *  weight, which is why the table above is explicit. */
export function copperWeight(mm: number | null): { label: string; note: string } | null {
  if (mm === null || mm === undefined) return null;
  const hit = COPPER_WEIGHTS.find((w) => Math.abs(w.mm - mm) <= COPPER_TOL);
  return hit ? { label: hit.label, note: hit.note } : null;
}

/** The distinct thicknesses a copper layer may take, for a message. */
export const COPPER_CHOICES = COPPER_WEIGHTS.map((w) => `${formatSi(w.mm, "length")} (${w.label})`).join(", ");

// -------------------------------------------------------------- solder mask
/** The coating over a trace, derived from the coating over bare substrate.
 *
 *  HALF, not "minus the copper thickness". Subtracting the copper assumes the mask's
 *  top surface ends up flat, and JLCPCB's own figures rule that out: it publishes
 *  30.5 um over substrate against 35 um of outer copper, so a flat surface would put
 *  -4.5 um of ink over the trace. What it actually publishes is 1.2 mil over the
 *  substrate and 0.6 mil over the trace — exactly half — which is what a conformal
 *  coating does: it thins over a raised feature rather than levelling across it.
 *
 *  One fab's ratio is not a law of physics, so this is a DEFAULT that keeps the two
 *  numbers consistent while somebody types, not a claim about every fab.
 */
export const MASK_OVER_TRACE_RATIO = 0.5;

export const maskOverTrace = (aboveSubstrateMm: number): number =>
  Math.round(aboveSubstrateMm * MASK_OVER_TRACE_RATIO * 1e6) / 1e6;
