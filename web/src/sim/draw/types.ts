/** The shape of the draw document `api/app/services/sch_draw.py` produces.
 *
 *  Library graphics stay in SYMBOL coordinates (y up); every placement carries
 *  the matrix that maps them onto the sheet (y down, millimetres). Sheet-level
 *  items are already in sheet coordinates.
 */

export type Pt = [number, number];
export type At = [number, number, number];
/** `matrix(a b c d e f)` — symbol space to sheet space. */
export type Matrix = [number, number, number, number, number, number];

export interface Stroked {
  unit: number;
  body: number;
  /** Millimetres. Zero means "the default", which is the renderer's business. */
  w: number;
  dash: string;
  fill: string;
}

export type LibShape =
  | (Stroked & { t: "rect"; a: Pt; b: Pt })
  | (Stroked & { t: "poly" | "bezier"; pts: Pt[] })
  | (Stroked & { t: "circle"; c: Pt; r: number })
  | (Stroked & { t: "arc"; a: Pt; m: Pt; b: Pt })
  | {
      t: "text"; unit: number; body: number; s: string; at: At;
      h: number; just: string[]; bold: boolean; italic: boolean;
    };

export interface LibPin {
  unit: number;
  body: number;
  /** Pin number, as printed. */
  n: string;
  name: string;
  type: string;
  shape: string;
  /** The CONNECTION point, and the angle from it towards the body. */
  at: At;
  len: number;
  hide: boolean;
  num_h: number;
  name_h: number;
}

export interface LibSymbol {
  shapes: LibShape[];
  pins: LibPin[];
  hide_names: boolean;
  hide_numbers: boolean;
  name_offset: number;
  power: boolean;
  /** How many units the part has. KiCad prints the unit letter after the
   *  reference only when there is more than one. */
  unit_count: number;
  /** Where the library puts Reference and Value, in SYMBOL space. A newly
   *  placed part has no field positions of its own; these are the ones KiCad
   *  would give it. */
  props: Field[];
}

export interface Field {
  k: string;
  v: string;
  at: At;
  h: number;
  just: string[];
  bold: boolean;
  italic: boolean;
  hide: boolean;
}

export interface DrawSymbol {
  index: number;
  lib_id: string;
  unit: number;
  body: number;
  at: At;
  mirror: string;
  xf: Matrix;
  dnp: boolean;
  fields: Field[];
}

export interface DrawLine {
  id: string;
  kind: "wire" | "bus";
  pts: Pt[];
  w: number;
  dash: string;
}

export interface DrawLabel {
  id: string;
  kind: "local" | "global" | "hier";
  text: string;
  at: At;
  h: number;
  just: string[];
  shape: string;
}

export interface DrawSheet {
  at: Pt;
  size: Pt;
  pins: { name: string; shape: string; at: At; h: number; just: string[] }[];
  fields: Field[];
  w: number;
  fill: string;
}

export interface DrawText {
  at: At;
  box?: Pt;
  h: number;
  just: string[];
  bold: boolean;
  italic: boolean;
  text: string;
  excluded: boolean;
}

export interface SheetDrawing {
  libs: Record<string, LibSymbol>;
  symbols: DrawSymbol[];
  wires: DrawLine[];
  buses: DrawLine[];
  bus_entries: { at: Pt; size: Pt }[];
  junctions: { at: Pt; d: number }[];
  no_connects: { at: Pt }[];
  labels: DrawLabel[];
  sheets: DrawSheet[];
  texts: DrawText[];
  shapes: LibShape[];
}

/** `schematic` block of a KiCad colour theme, straight from the same file
 *  kicad-cli renders with. Every value is already a CSS colour. */
export type SchTheme = Record<string, string>;

export const FALLBACK_THEME: SchTheme = {
  background: "rgb(30, 33, 37)",
  wire: "rgb(100, 170, 190)",
  bus: "rgb(38, 139, 210)",
  junction: "rgb(100, 170, 190)",
  component_outline: "rgb(27, 144, 179)",
  component_body: "rgb(26, 96, 110)",
  pin: "rgb(27, 144, 179)",
  pin_name: "rgb(200, 130, 75)",
  pin_number: "rgb(221, 130, 0)",
  reference: "rgb(160, 220, 110)",
  value: "rgb(160, 220, 110)",
  fields: "rgb(147, 161, 161)",
  label_local: "rgb(42, 161, 152)",
  label_global: "rgb(70, 135, 160)",
  label_hier: "rgb(27, 144, 179)",
  no_connect: "rgb(24, 212, 255)",
  note: "rgb(255, 153, 0)",
  sheet: "rgb(88, 110, 117)",
  sheet_background: "rgba(255, 255, 255, 0)",
  sheet_name: "rgb(177, 0, 109)",
  sheet_filename: "rgb(24, 161, 204)",
  sheet_label: "rgb(223, 82, 24)",
  sheet_fields: "rgb(132, 0, 132)",
  dnp_marker: "rgba(220, 9, 13, 0.851)",
  excluded_from_sim: "rgba(194, 194, 194, 0.949)",
};
