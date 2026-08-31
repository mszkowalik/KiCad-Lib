/** Coordinate and text helpers shared by the schematic renderer and editor. */
import type { At, LibPin, Matrix, Pt } from "./types";

/** KiCad's own "0 means default" widths, millimetres. */
export const DEFAULT_LINE = 0.1524;
export const WIRE_WIDTH = 0.1524;
export const BUS_WIDTH = 0.3048;
export const JUNCTION_DIAM = 0.9144;
/** Half the arm of the no-connect cross. */
export const NO_CONNECT_ARM = 0.635;

export function apply(m: Matrix, p: Pt | number[]): Pt {
  return [m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5]];
}

/** Only the rotation/reflection part — for directions, which carry no origin. */
export function applyDir(m: Matrix, p: Pt): Pt {
  return [m[0] * p[0] + m[2] * p[1], m[1] * p[0] + m[3] * p[1]];
}

export function matrixOf(at: At, mirror: string): Matrix {
  // Must stay identical to sch_draw.placement_matrix: the overlay puts a
  // reading on a pin whose position the server computed, and the renderer
  // draws that pin from here.
  const [x, y, rot] = at;
  const sx = mirror.includes("y") ? -1 : 1;
  const sy = mirror.includes("x") ? 1 : -1;
  const c = Math.cos((rot * Math.PI) / 180);
  const s = -Math.sin((rot * Math.PI) / 180);
  return [c * sx, s * sx, -s * sy, c * sy, x, y];
}

export function matrixString(m: Matrix): string {
  return `matrix(${m.map((v) => round(v)).join(" ")})`;
}

export function round(v: number): number {
  return Math.round(v * 10000) / 10000;
}

/** An SVG arc through three points. KiCad stores start, a point ON the arc,
 *  and end; SVG wants a radius and two flags, so the centre has to be solved
 *  for. Three collinear points have no centre — then it is a line, and saying
 *  so beats emitting a path the browser silently drops. */
export function arcPath(a: Pt, m: Pt, b: Pt): string {
  const d = 2 * (a[0] * (m[1] - b[1]) + m[0] * (b[1] - a[1]) + b[0] * (a[1] - m[1]));
  if (Math.abs(d) < 1e-9) return `M ${a[0]} ${a[1]} L ${b[0]} ${b[1]}`;
  const ua = a[0] * a[0] + a[1] * a[1];
  const um = m[0] * m[0] + m[1] * m[1];
  const ub = b[0] * b[0] + b[1] * b[1];
  const cx = (ua * (m[1] - b[1]) + um * (b[1] - a[1]) + ub * (a[1] - m[1])) / d;
  const cy = (ua * (b[0] - m[0]) + um * (a[0] - b[0]) + ub * (m[0] - a[0])) / d;
  const r = Math.hypot(a[0] - cx, a[1] - cy);
  const TAU = 2 * Math.PI;
  const angle = (p: Pt) => Math.atan2(p[1] - cy, p[0] - cx);
  const turn = (from: number, to: number) => ((to - from) % TAU + TAU) % TAU;
  // The mid point decides the direction: if it is reached before the end when
  // walking anticlockwise, the arc runs anticlockwise. `atan2` is taken in the
  // same y-down frame the path is drawn in, so increasing angle IS SVG's
  // positive sweep.
  const toEnd = turn(angle(a), angle(b));
  const toMid = turn(angle(a), angle(m));
  const sweep = toMid < toEnd ? 1 : 0;
  const span = sweep ? toEnd : TAU - toEnd;
  const large = span > Math.PI ? 1 : 0;
  return `M ${a[0]} ${a[1]} A ${round(r)} ${round(r)} 0 ${large} ${sweep} ${b[0]} ${b[1]}`;
}

/** A cubic through however many control points KiCad wrote. */
export function bezierPath(pts: Pt[]): string {
  if (pts.length < 4) return polyPath(pts);
  return `M ${pts[0][0]} ${pts[0][1]} C ${pts.slice(1, 4).map((p) => `${p[0]} ${p[1]}`).join(" ")}`;
}

export function polyPath(pts: Pt[]): string {
  return pts.map((p, i) => `${i ? "L" : "M"} ${p[0]} ${p[1]}`).join(" ");
}

// ----------------------------------------------------------------- text

export interface TextPlace {
  x: number;
  y: number;
  /** Degrees, clockwise, ready for an SVG rotate(). Only 0 or -90 ever. */
  rotate: number;
  anchor: "start" | "middle" | "end";
  baseline: "hanging" | "middle" | "auto";
}

/** Where a piece of KiCad text goes, in SVG terms.
 *
 *  KiCad never draws text upside down, and it does not leave the caller to
 *  work that out: the justification in the file is the one for the text AS
 *  DRAWN, with the half-turn already folded in. Checked, not assumed — on a
 *  real sheet every hierarchical label with `(at .. 180)` carries
 *  `(justify right)` and sits on a wire that leaves to the RIGHT, so its text
 *  runs left. Flipping the justification for the half-turn a second time
 *  would lay every one of them across its own wire.
 *
 *  So the angle only chooses horizontal or vertical, and the justification is
 *  used exactly as written.
 */
export function placeText(at: At, just: string[], mirrored = false): TextPlace {
  const angle = ((at[2] % 180) + 180) % 180;
  let h = just.includes("left") ? "left" : just.includes("right") ? "right" : "center";
  const v = just.includes("top") ? "top" : just.includes("bottom") ? "bottom" : "center";
  if (mirrored || just.includes("mirror")) {
    h = h === "left" ? "right" : h === "right" ? "left" : "center";
  }
  return {
    x: at[0],
    y: at[1],
    // The sheet's y grows downward, so a counter-clockwise KiCad angle is a
    // clockwise SVG one; vertical text therefore reads bottom to top.
    rotate: -angle,
    anchor: h === "left" ? "start" : h === "right" ? "end" : "middle",
    // KiCad's vertical justification names where the ANCHOR sits, not where
    // the text sits: `top` puts the anchor at the top of the glyphs.
    baseline: v === "top" ? "hanging" : v === "bottom" ? "auto" : "middle",
  };
}

/** Rough width of a run of KiCad stroke-font text, in millimetres.
 *  Only used to size the flags drawn around labels — a few percent out moves
 *  a box edge, not a connection. */
export function textWidth(text: string, h: number): number {
  return text.length * h * 0.68;
}

// ------------------------------------------------------------------ pins

export interface PlacedPin {
  /** The connection point on the sheet. */
  at: Pt;
  /** Where the stub meets the symbol body. */
  root: Pt;
  /** Unit vector from the connection point towards the body. */
  dir: Pt;
}

export function placePin(pin: LibPin, m: Matrix): PlacedPin {
  const [x, y, a] = pin.at;
  const rad = (a * Math.PI) / 180;
  const bx = x + pin.len * Math.cos(rad);
  const by = y + pin.len * Math.sin(rad);
  const at = apply(m, [x, y]);
  const root = apply(m, [bx, by]);
  const dx = root[0] - at[0];
  const dy = root[1] - at[1];
  const len = Math.hypot(dx, dy) || 1;
  return { at, root, dir: [dx / len, dy / len] };
}
