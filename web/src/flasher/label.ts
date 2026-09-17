/** The label, laid out the way the bench agent lays it out.
 *
 *  This is a MIRROR of `label_pdf` in `api/app/services/bench_agent/agent.py`
 *  — the same Code 128 table, the same quiet zone, the same padding, text
 *  size and gap — so the preview in the step editor and on the bench shows the
 *  label the printer will produce, and says a value does not fit BEFORE the
 *  agent refuses the job. The agent stays the authority: it prints, this only
 *  draws. Change one and change the other in the same commit.
 *
 *  Everything here is in millimetres, origin top-left, y down (SVG's frame).
 *  The agent works in PDF points with y up; the picture is the same.
 */

/* Code 128, values 0..106 — the published table, copied from the agent. */
const CODE128 = [
  "11011001100", "11001101100", "11001100110", "10010011000", "10010001100",
  "10001001100", "10011001000", "10011000100", "10001100100", "11001001000",
  "11001000100", "11000100100", "10110011100", "10011011100", "10011001110",
  "10111001100", "10011101100", "10011100110", "11001110010", "11001011100",
  "11001001110", "11011100100", "11001110100", "11101101110", "11101001100",
  "11100101100", "11100100110", "11101100100", "11100110100", "11100110010",
  "11011011000", "11011000110", "11000110110", "10100011000", "10001011000",
  "10001000110", "10110001000", "10001101000", "10001100010", "11010001000",
  "11000101000", "11000100010", "10110111000", "10110001110", "10001101110",
  "10111011000", "10111000110", "10001110110", "11101110110", "11010001110",
  "11000101110", "11011101000", "11011100010", "11011101110", "11101011000",
  "11101000110", "11100010110", "11101101000", "11101100010", "11100011010",
  "11101111010", "11001000010", "11110001010", "10100110000", "10100001100",
  "10010110000", "10010000110", "10000101100", "10000100110", "10110010000",
  "10110000100", "10011010000", "10011000010", "10000110100", "10000110010",
  "11000010010", "11001010000", "11110111010", "11000010100", "10001111010",
  "10100111100", "10010111100", "10010011110", "10111100100", "10011110100",
  "10011110010", "11110100100", "11110010100", "11110010010", "11011011110",
  "11011110110", "11110110110", "10101111000", "10100011110", "10001011110",
  "10111101000", "10111100010", "11110101000", "11110100010", "10111011110",
  "10111101110", "11101011110", "11110101110", "11010000100", "11010010000",
  "11010011100", "11000111010",
];
const START_B = 104;
const STOP_13 = "1100011101011";   // the stop symbol plus its final bar
const QUIET = 10;                   // modules of clear space each side
const DPI = 300;                    // the LabelWriter 550's only resolution
const MM_PER_PT = 25.4 / 72;

/** The value as modules: "1" is a bar, "0" a space. Throws on a character
 *  Code 128 B cannot carry, with the same words the agent uses. */
export function code128(text: string): string {
  const bad = [...text].filter((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) > 126);
  if (bad.length) throw new Error(`a Code 128 label cannot carry ${JSON.stringify(bad.join(""))}`);
  const values = [...text].map((c) => c.charCodeAt(0) - 32);
  const check = (START_B + values.reduce((acc, v, i) => acc + (i + 1) * v, 0)) % 103;
  return [START_B, ...values, check].map((v) => CODE128[v]).join("") + STOP_13;
}

/** One roll's geometry, in mm. `printable` is null when only the label's
 *  nominal size is known — away from the bench, where the printer's PPD is. */
export interface RollGeometry {
  size: string;
  name: string;
  label: [number, number];
  printable: [number, number] | null;
}

/** What a roll's PPD name says about it: `w72h154` is 72 × 154 points. The
 *  printable area is NOT in the name — it is the printer's own statement, in
 *  its PPD on the bench — so this answers only the label's nominal size. */
export function rollFromName(size: string): RollGeometry | null {
  const m = /^w(\d+(?:\.\d+)?)h(\d+(?:\.\d+)?)/i.exec(size.trim());
  if (!m) return null;
  return {
    size, name: size,
    label: [Number(m[1]) * MM_PER_PT, Number(m[2]) * MM_PER_PT],
    printable: null,
  };
}

export interface LabelLayout {
  /** the roll drawn, and whether its printable area was known */
  roll: RollGeometry;
  approximate: boolean;
  /** the content box the bars and text are laid out in — printable, turned when rotated */
  across: number;
  down: number;
  rotate: boolean;
  /** millimetres the symbol needs, quiet zones included */
  width: number;
  /** null when it fits, else the agent's own refusal */
  problem: string | null;
  bars: { x: number; w: number }[];
  barsY: number;
  barsH: number;
  /** the human-readable line: centre x, baseline y, font size — all mm */
  text: { x: number; y: number; size: number };
}

/** Lay one label out. Mirrors `label_pdf` step for step. */
export function layoutLabel(
  value: string,
  roll: RollGeometry,
  dots: number,
  rotate: boolean,
): LabelLayout {
  const d = Math.max(2, Math.min(8, Math.round(dots || 3)));
  const modules = code128(value);
  const unit = d * 25.4 / DPI;
  const width = (modules.length + 2 * QUIET) * unit;
  const printable = roll.printable ?? roll.label;
  let [across, down] = printable;
  if (rotate) [across, down] = [down, across];
  let problem: string | null = null;
  if (width > across) {
    problem = `${value} needs ${width.toFixed(1)} mm of barcode and this roll prints `
      + `${across.toFixed(1)} mm across — turn the label, or pick a longer roll`;
  }
  const pad = 1.0;                                  // 1 mm of air, as the agent leaves
  const textPt = Math.min(10.0, (down - 2 * pad) / MM_PER_PT * 0.22);
  const textMm = textPt * MM_PER_PT;
  const gap = textMm * 0.35;
  const barsH = down - 2 * pad - textMm - gap;
  if (barsH <= 0 && !problem) problem = "this roll is too narrow to carry a barcode and its text";

  // Start the quiet zone on a whole dot, so every bar edge lands on one too.
  const dot = 25.4 / DPI;
  const x0 = Math.round((across - width) / 2 / dot) * dot + QUIET * unit;
  const bars: { x: number; w: number }[] = [];
  let x = x0;
  for (let i = 0; i < modules.length;) {
    let j = i;
    while (j < modules.length && modules[j] === modules[i]) j += 1;
    if (modules[i] === "1") bars.push({ x, w: (j - i) * unit });
    x += (j - i) * unit;
    i = j;
  }
  return {
    roll, approximate: roll.printable === null, across, down, rotate, width, problem,
    bars, barsY: pad, barsH: Math.max(0, barsH),
    text: { x: x0 - QUIET * unit + width / 2, y: down - pad - textMm * 0.18, size: textMm },
  };
}
