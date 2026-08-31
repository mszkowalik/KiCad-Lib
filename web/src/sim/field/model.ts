/** Field-solver page state: profiles, cells and the helpers that turn them into
 *  solver parameters.
 *
 *  A PROFILE is an impedance requirement — "100 Ω differential at 2.4 GHz". A CELL
 *  is that profile applied to one copper layer of the stackup, and it carries the
 *  geometry: trace width, spacing, references, mask, via fence. The stackup grid is
 *  profiles across, layers down, so one board can carry several controlled lines.
 */
import type { FsLayer, FsRuleSet, FsStackup } from "../../api";

export type LineType = "single" | "diff" | "cpw" | "diff_cpw";
export type MaskMode = "on" | "off" | "both";

export interface ViaRow {
  mode: "rel" | "range";
  pitch: number;
}

export interface Cell {
  enabled: boolean;
  top_ref: string;
  bottom_ref: string;
  w: number;
  s: number;
  gap: number;
  t?: number | null;
  roughness_um: number;
  mask_mode: MaskMode;
  via_fence: boolean;
  fence_mode: "exact" | "range";
  fence_distance: number;
  via_hole: number;
  via_pad: number;
  via_plating_um: number;
  via_drill_oversize: number;
  via_size: string;
  via_rows: ViaRow[];
  etch_um: number | null;
  use_w2: boolean;
  use_rough: boolean;
  cutout_mode: "auto" | "fence" | "coplanar" | "width" | "remove";
  cutout: number;
  lock: "w" | "gap";
  result?: Record<string, unknown> | null;
}

export interface Profile {
  id: number;
  name: string;
  autoName: boolean;
  type: LineType;
  target: number;
  tolerance: number;
  /** Design frequency in Hz. */
  f: number;
  frange: "auto" | "custom";
  fr0: number;
  fr1: number;
  ppd: number;
  step: number | null;
  ranges: Record<string, [number, number]>;
  cells: Record<string, Cell>;
}

export const isPair = (p: Profile): boolean => p.type.startsWith("diff");
export const isCpw = (p: Profile): boolean => p.type.includes("cpw");
export const zKey = (p: Profile): string => (isPair(p) ? "Zdiff" : "Z0");

export const TYPE_LABEL: Record<LineType, string> = {
  single: "single",
  diff: "differential",
  cpw: "coplanar",
  diff_cpw: "differential coplanar",
};

const NAME_PREFIX: Record<LineType, string> = {
  single: "SE",
  cpw: "CPWG",
  diff: "Diff",
  diff_cpw: "DiffCPWG",
};

export const autoName = (p: Pick<Profile, "type" | "target">): string =>
  `${NAME_PREFIX[p.type] ?? "Z"}${p.target}`;

/** The name follows type and target until the user types one of their own. */
export function refreshName(p: Profile): void {
  if (p.autoName) p.name = autoName(p);
}

export function lineType(mode: "single" | "diff", coplanar: boolean): LineType {
  if (mode === "diff") return coplanar ? "diff_cpw" : "diff";
  return coplanar ? "cpw" : "single";
}

// ------------------------------------------------------------------ frequency

/** "2.4G", "868M", "100k", "2400M", "1e6", "50 MHz" -> hertz; null when unreadable. */
export function parseFreq(txt: string): number | null {
  const m = String(txt).trim().replace(",", ".").match(/^([0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)\s*([kKmMgGtT]?)\s*(?:hz)?$/i);
  if (!m) return null;
  const v = parseFloat(m[1]);
  if (!(v > 0)) return null;
  const mult: Record<string, number> = { k: 1e3, m: 1e6, g: 1e9, t: 1e12 };
  return v * (mult[m[2].toLowerCase()] ?? 1);
}

export function fmtHz(v: number): string {
  const trim = (x: number) => Number(x.toPrecision(3));
  if (v >= 1e9) return `${trim(v / 1e9)} GHz`;
  if (v >= 1e6) return `${trim(v / 1e6)} MHz`;
  if (v >= 1e3) return `${trim(v / 1e3)} kHz`;
  return `${trim(v)} Hz`;
}

/** The solver is quasi-TEM: below 1 MHz the perfect-conductor assumption stops
 *  describing a real board, so no sweep is allowed to go there. */
export const F_FLOOR = 1e6;
export const F_CEIL = 1e10;

/** Auto range: two decades below the design frequency, one above, on decade
 *  boundaries, clipped to the model's range. */
export function sweepRange(p: Profile): [number, number] {
  if (p.frange === "custom" && p.fr0 > 0 && p.fr1 > p.fr0) {
    return [Math.max(F_FLOOR, p.fr0), Math.min(F_CEIL, p.fr1)];
  }
  const lo = Math.pow(10, Math.floor(Math.log10(p.f)) - 2);
  const hi = Math.pow(10, Math.ceil(Math.log10(p.f)) + 1);
  const l = Math.max(F_FLOOR, lo);
  return [l, Math.min(F_CEIL, Math.max(hi, l * 10))];
}

export const perDecade = (p: Profile): number => Math.max(2, Math.min(20, Math.round(p.ppd) || 10));

export function sweepPoints(p: Profile): number {
  const [lo, hi] = sweepRange(p);
  return Math.max(2, Math.min(120, Math.round(perDecade(p) * Math.log10(hi / lo)) + 1));
}

// ------------------------------------------------------------------- defaults

export const copperLayers = (st: FsStackup): FsLayer[] => st.layers.filter((l) => l.type === "copper");

export function defaultCell(st: FsStackup, layerName: string): Cell {
  const cu = copperLayers(st);
  const i = cu.findIndex((l) => l.name === layerName);
  const outer = i === 0;
  return {
    enabled: false,
    top_ref: i > 0 ? (cu[i - 1].name as string) : "none",
    bottom_ref: i < cu.length - 1 ? (cu[i + 1].name as string) : "none",
    w: 0.3,
    s: 0.2,
    gap: 0.3,
    t: null,
    roughness_um: 0,
    mask_mode: outer && st.soldermask ? "on" : "off",
    via_fence: false,
    fence_mode: "range",
    fence_distance: 0.5,
    via_hole: 0.3,
    via_pad: 0.6,
    via_plating_um: 18,
    via_drill_oversize: 0.1,
    via_size: "0",
    via_rows: [],
    etch_um: null,
    use_w2: false,
    use_rough: false,
    cutout_mode: "auto",
    cutout: 1,
    lock: "gap",
    result: null,
  };
}

let nextProfileId = 1;

export function newProfile(existing: number): Profile {
  const type: LineType = existing ? "diff" : "single";
  const target = existing ? 100 : 50;
  return {
    id: nextProfileId++,
    name: autoName({ type, target }),
    autoName: true,
    type,
    target,
    tolerance: 3,
    f: 2.4e9,
    frange: "auto",
    fr0: 1e7,
    fr1: 1e10,
    ppd: 10,
    step: 0.05,
    ranges: { w: [0.1, 1.5], s: [0.1, 0.5], gap: [0.15, 0.5], fence: [0.2, 0.6], rowpitch: [0.8, 1.6] },
    cells: {},
  };
}

export const cellOf = (p: Profile, st: FsStackup, layer: string): Cell => {
  if (!p.cells[layer]) p.cells[layer] = defaultCell(st, layer);
  return p.cells[layer];
};

export const maskOn = (c: Cell): boolean => c.mask_mode !== "off";

/** Minimum centre distance between two fence vias: pad plus the fab's drill-to-copper. */
export function minPitch(c: Cell, rules: FsRuleSet | undefined): number {
  const d2c = Number((rules?.drill_to_copper as number) ?? 0.2);
  return +(c.via_pad + d2c).toFixed(3);
}

/** A reference has to be on the correct side of the signal layer. */
export function refOptions(st: FsStackup, layer: string): { above: FsLayer[]; below: FsLayer[] } {
  const cu = copperLayers(st);
  const i = cu.findIndex((l) => l.name === layer);
  return { above: cu.slice(0, i), below: cu.slice(i + 1) };
}

/** Cells to solver parameters. `forSearch` leaves the searched dimensions open. */
export function cellParams(
  p: Profile,
  st: FsStackup,
  layer: string,
  forSearch = false,
): Record<string, unknown> {
  const c = cellOf(p, st, layer);
  const refs = [c.top_ref, c.bottom_ref].filter((r) => r && r !== "none");
  const rows = (c.via_rows || []).map((r) => (r.mode === "range" && forSearch ? null : r.pitch));
  return {
    // the solver's single-ended template is called "microstrip"; the page calls the
    // same thing "single" because that is what it is next to "differential"
    template: p.type === "single" ? "microstrip" : p.type,
    stackup: st.id,
    signal_layer: layer,
    reference_layers: refs,
    w: c.w,
    s: c.s,
    gap: c.gap,
    copper_thickness: c.t ?? null,
    soldermask: maskOn(c),
    via_fence: c.via_fence,
    fence_distance: forSearch && c.fence_mode === "range" ? null : c.fence_distance,
    via_hole: c.via_hole,
    via_pad: c.via_pad,
    via_plating_um: c.via_plating_um,
    via_drill_oversize: c.via_drill_oversize,
    via_rows: rows,
    roughness_um: c.use_rough ? c.roughness_um : 0,
    etch: c.use_w2 && c.etch_um != null ? c.etch_um / 1000 : 0,
    cutout_mode: c.cutout_mode,
    cutout: c.cutout,
  };
}

export const fmt = (v: number | null | undefined, d = 2): string =>
  v == null || Number.isNaN(v) ? "–" : Number(v).toFixed(d);
