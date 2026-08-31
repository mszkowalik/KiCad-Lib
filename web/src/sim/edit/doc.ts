/** The document the browser edits, and the geometry the editor needs of it.
 *
 *  It is deliberately close to a `.kicad_sch`: same items, same millimetres,
 *  same 1.27 mm grid. The server turns it into the file (`sch_write.py`) and
 *  nothing is translated on the way, so what is drawn is what KiCad opens.
 *
 *  The document is the ONLY state the editor mutates. Everything drawn comes
 *  from `docToDrawing`, so there is no second copy of the circuit to keep in
 *  step with the first.
 */
import { matrixOf, placePin } from "../draw/geom";
import type { At, LibSymbol, Pt, SchTheme, SheetDrawing } from "../draw/types";
import type { ParamForm } from "./params";

/** KiCad's schematic grid. Anything off it will not connect, and a schematic
 *  whose wires nearly touch is the most expensive kind of drawing there is. */
export const GRID = 1.27;

export interface DocSymbol {
  id: string;
  lib_id: string;
  at: At;
  mirror: string;
  unit: number;
  fields: Record<string, string>;
}

export interface DocWire {
  id: string;
  pts: Pt[];
}

export interface DocLabel {
  id: string;
  text: string;
  at: At;
  kind: "local" | "global";
}

export interface DocText {
  id: string;
  at: At;
  text: string;
  h: number;
}

export interface SchDoc {
  name: string;
  uuid: string;
  paper: string;
  symbols: DocSymbol[];
  wires: DocWire[];
  labels: DocLabel[];
  texts: DocText[];
  junctions: Pt[];
}

export interface PaletteEntry {
  lib_id: string;
  label: string;
  key: string;
  prefix: string;
  value: string;
  unit: string;
  sim: "passive" | "source" | "switch" | "power" | "device";
  draw: LibSymbol | null;
  /** What this part is ASKED for — see `sch_lib.PARAM_FORMS`. */
  forms: ParamForm[];
}

/** The name `alter` has to be given for a placed part.
 *
 *  Usually the reference. But `Sim.Device` overrides the element type and
 *  KiCad PREFIXES the reference rather than replacing it, so a switch drawn
 *  `SW1` is `rsw1` in the netlist — and `alter sw1` is accepted and does
 *  nothing, which is the worse of the two failures. */
export function spiceName(sym: DocSymbol, libs: Record<string, LibSymbol>): string {
  const ref = (sym.fields.Reference ?? "").trim();
  if (!ref) return "";
  const device = (
    sym.fields["Sim.Device"]
    ?? libs[sym.lib_id]?.props.find((f) => f.k === "Sim.Device")?.v
    ?? ""
  ).trim().toUpperCase();
  if (device.length === 1 && !ref.toUpperCase().startsWith(device)) {
    return (device + ref).toLowerCase();
  }
  return ref.toLowerCase();
}

export function newId(): string {
  return crypto.randomUUID();
}

export function emptyDoc(name = "sketch"): SchDoc {
  return {
    name,
    uuid: newId(),
    paper: "A4",
    symbols: [],
    wires: [],
    labels: [],
    texts: [],
    junctions: [],
  };
}

export function snap(v: number): number {
  return Math.round(v / GRID) * GRID;
}

export function snapPt(p: Pt): Pt {
  return [snap(p[0]), snap(p[1])];
}

const key = (p: Pt | number[]): string => `${Math.round(p[0] * 1000)},${Math.round(p[1] * 1000)}`;

/** Where a placed symbol's pins land on the sheet. */
export function symbolPins(sym: DocSymbol, libs: Record<string, LibSymbol>): { n: string; at: Pt }[] {
  const lib = libs[sym.lib_id];
  if (!lib) return [];
  const m = matrixOf(sym.at, sym.mirror);
  return lib.pins
    .filter((p) => (p.unit === 0 || p.unit === sym.unit) && !p.hide)
    .map((p) => ({ n: p.n, at: placePin(p, m).at }));
}

/** The next free reference for a prefix — R1, R2, ... Power symbols get their
 *  own run, because `#PWR03` is a reference too and KiCad counts it. */
export function nextRef(doc: SchDoc, prefix: string): string {
  let n = 0;
  for (const s of doc.symbols) {
    const ref = s.fields.Reference ?? "";
    if (!ref.startsWith(prefix)) continue;
    const num = Number.parseInt(ref.slice(prefix.length), 10);
    if (Number.isFinite(num) && num > n) n = num;
  }
  const next = n + 1;
  return prefix.startsWith("#") ? `${prefix}${String(next).padStart(2, "0")}` : `${prefix}${next}`;
}

/** Points where KiCad would draw a junction dot: three or more wire ends, or a
 *  wire end landing in the MIDDLE of another wire. Two wires that merely cross
 *  are NOT connected — that is the rule this has to get right, because a dot
 *  drawn where there is none is a short nobody can see. */
export function autoJunctions(doc: SchDoc, libs: Record<string, LibSymbol>): Pt[] {
  const ends = new Map<string, { at: Pt; n: number }>();
  const segments: [Pt, Pt][] = [];
  for (const w of doc.wires) {
    for (let i = 0; i + 1 < w.pts.length; i += 1) {
      const a = w.pts[i];
      const b = w.pts[i + 1];
      segments.push([a, b]);
      for (const p of [a, b]) {
        const k = key(p);
        const got = ends.get(k);
        if (got) got.n += 1;
        else ends.set(k, { at: p, n: 1 });
      }
    }
  }
  const pinAt = new Set<string>();
  for (const s of doc.symbols) for (const p of symbolPins(s, libs)) pinAt.add(key(p.at));

  const out: Pt[] = [];
  for (const [k, e] of ends) {
    if (e.n >= 3) {
      out.push(e.at);
      continue;
    }
    // A T: this end sits strictly inside some other segment.
    const inside = segments.some(([a, b]) => {
      if (key(a) === k || key(b) === k) return false;
      const cross = (e.at[0] - a[0]) * (b[1] - a[1]) - (e.at[1] - a[1]) * (b[0] - a[0]);
      if (Math.abs(cross) > 1e-6) return false;
      const dot = (e.at[0] - a[0]) * (b[0] - a[0]) + (e.at[1] - a[1]) * (b[1] - a[1]);
      const len2 = (b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2;
      return dot > 1e-9 && dot < len2 - 1e-9;
    });
    if (inside && !pinAt.has(k)) out.push(e.at);
  }
  return out;
}

// ------------------------------------------------------------- for drawing

/** The document as the renderer's draw document, so the editor and the
 *  simulator draw through exactly the same code. */
export function docToDrawing(doc: SchDoc, libs: Record<string, LibSymbol>): SheetDrawing {
  return {
    libs,
    symbols: doc.symbols.map((s, index) => {
      const lib = libs[s.lib_id];
      const fields = (lib?.props ?? []).map((p) => {
        const at = matrixOf(s.at, s.mirror);
        const x = at[0] * p.at[0] + at[2] * p.at[1] + at[4];
        const y = at[1] * p.at[0] + at[3] * p.at[1] + at[5];
        return {
          ...p,
          v: s.fields[p.k] ?? p.v,
          at: [x, y, p.at[2] + s.at[2]] as At,
        };
      });
      return {
        index,
        lib_id: s.lib_id,
        unit: s.unit,
        body: 1,
        at: s.at,
        mirror: s.mirror,
        xf: matrixOf(s.at, s.mirror),
        dnp: false,
        fields,
      };
    }),
    wires: doc.wires.map((w) => ({ id: w.id, kind: "wire" as const, pts: w.pts, w: 0, dash: "default" })),
    buses: [],
    bus_entries: [],
    junctions: doc.junctions.map((at) => ({ at, d: 0 })),
    no_connects: [],
    labels: doc.labels.map((l) => ({
      id: l.id,
      kind: l.kind,
      text: l.text,
      at: l.at,
      h: 1.27,
      // KiCad stores the justification of the text as drawn: a label pointing
      // left is right-justified, so its name runs back along its own wire.
      just: l.at[2] > 90 && l.at[2] < 270 ? ["right"] : ["left"],
      shape: "input",
    })),
    sheets: [],
    texts: doc.texts.map((t) => ({
      at: t.at,
      h: t.h,
      just: ["left", "top"],
      bold: false,
      italic: false,
      text: t.text,
      excluded: false,
    })),
    shapes: [],
  };
}

/** Bounding box of a placed symbol on the sheet, for hit testing. */
export function symbolBox(sym: DocSymbol, libs: Record<string, LibSymbol>): [number, number, number, number] | null {
  const lib = libs[sym.lib_id];
  if (!lib) return null;
  const m = matrixOf(sym.at, sym.mirror);
  const xs: number[] = [];
  const ys: number[] = [];
  const add = (p: Pt) => {
    xs.push(m[0] * p[0] + m[2] * p[1] + m[4]);
    ys.push(m[1] * p[0] + m[3] * p[1] + m[5]);
  };
  for (const s of lib.shapes) {
    if (s.t === "rect") { add(s.a); add(s.b); }
    else if (s.t === "circle") { add([s.c[0] - s.r, s.c[1] - s.r]); add([s.c[0] + s.r, s.c[1] + s.r]); }
    else if (s.t === "arc") { add(s.a); add(s.m); add(s.b); }
    else if (s.t === "poly" || s.t === "bezier") for (const p of s.pts) add(p);
  }
  for (const p of symbolPins(sym, libs)) { xs.push(p.at[0]); ys.push(p.at[1]); }
  if (!xs.length) return null;
  const pad = 0.6;
  return [Math.min(...xs) - pad, Math.min(...ys) - pad, Math.max(...xs) + pad, Math.max(...ys) + pad];
}

export function pointInBox(p: Pt, box: [number, number, number, number]): boolean {
  return p[0] >= box[0] && p[0] <= box[2] && p[1] >= box[1] && p[1] <= box[3];
}

/** Distance from a point to a wire, for picking one. */
export function distanceToWire(p: Pt, pts: Pt[]): number {
  let best = Infinity;
  for (let i = 0; i + 1 < pts.length; i += 1) {
    const [ax, ay] = pts[i];
    const [bx, by] = pts[i + 1];
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const t = len2 ? Math.max(0, Math.min(1, ((p[0] - ax) * dx + (p[1] - ay) * dy) / len2)) : 0;
    best = Math.min(best, Math.hypot(p[0] - (ax + dx * t), p[1] - (ay + dy * t)));
  }
  return best;
}

/** An orthogonal run between two points, the way KiCad draws one: along x
 *  first when the move is mostly sideways, along y first when it is not. */
export function orthoRun(from: Pt, to: Pt): Pt[] {
  const a = snapPt(from);
  const b = snapPt(to);
  if (a[0] === b[0] || a[1] === b[1]) return [a, b];
  return Math.abs(b[0] - a[0]) >= Math.abs(b[1] - a[1])
    ? [a, [b[0], a[1]], b]
    : [a, [a[0], b[1]], b];
}

export const themeFor = (t: SchTheme): SchTheme => t;
