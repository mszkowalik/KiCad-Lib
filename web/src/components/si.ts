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

export type Quantity = "length" | "frequency";

/** Multipliers onto the base unit — mm for a length, Hz for a frequency. */
const UNITS: Record<Quantity, { base: string; units: Record<string, number>; steps: [number, string][] }> = {
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
    // Printed unit by magnitude, largest first. The switch is at 50 um rather than at
    // 1 mm because of how the figures are actually quoted: a fab publishes laminates
    // in millimetres (prepreg 3313 is 0.0994 mm, not 99.4 um) and foils and coatings
    // in micrometres (copper 35 um, mask 30.5 um). Printing everything in the unit
    // the datasheet uses is what removes the mental conversion; a unit-carrying box
    // still accepts either one on the way in.
    steps: [
      [0.05, "mm"],
      [1e-3, "um"],
      [0, "nm"],
    ],
  },
  frequency: {
    base: "Hz",
    units: { hz: 1, khz: 1e3, mhz: 1e6, ghz: 1e9, thz: 1e12, k: 1e3, m: 1e6, g: 1e9 },
    steps: [
      [1e9, "GHz"],
      [1e6, "MHz"],
      [1e3, "kHz"],
      [0, "Hz"],
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
  const m = /^([+-]?(?:\d+\.?\d*|\.\d+))(.*)$/.exec(t);
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

/** Print a base-unit value in the prefix that suits its magnitude. */
export function formatSi(v: number | null, q: Quantity, fixedUnit?: string): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return "";
  const spec = UNITS[q];
  if (fixedUnit) {
    const mult = spec.units[fixedUnit] ?? spec.units[fixedUnit.toLowerCase()] ?? 1;
    return `${tidy(v / mult)} ${fixedUnit}`;
  }
  if (v === 0) return `0 ${spec.base}`;
  const abs = Math.abs(v);
  for (const [threshold, unit] of spec.steps) {
    if (abs >= threshold) {
      const mult = spec.units[unit] ?? spec.units[unit.toLowerCase()] ?? 1;
      return `${tidy(v / mult)} ${unit}`;
    }
  }
  return `${tidy(v)} ${spec.base}`;
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
