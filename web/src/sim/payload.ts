/** The 7SIM payload, and the arithmetic the overlay needs on top of it.
 *
 *  Wire format (services/sim_spice.py `encode_payload`):
 *      "7SIM" | uint32 header length | UTF-8 JSON header | float32 blob
 *  Every vector in the header carries a byte offset and a length into the
 *  blob, so decoding is a set of typed-array views over one buffer — nothing
 *  is copied and nothing is parsed per sample.
 */

export interface SimVector {
  name: string;
  unit: string;
  /** "v" = node voltage, "i" = a current through a device or a source. */
  kind: "v" | "i";
  /** Net name (voltages) or component reference (currents), both lower case. */
  key: string;
  offset: number;
  len: number;
}

export interface SimPlotHeader {
  name: string;
  complex: boolean;
  decimated: boolean;
  n: number;
  scale: { name: string; type: string; offset: number; len: number };
  vectors: SimVector[];
}

export interface SimHeader {
  version: number;
  plots: SimPlotHeader[];
  /** Refs dropped from the netlist because they carry no simulation model. */
  unmodelled: string[];
  control: string;
  log: string;
}

export interface SimPlot {
  name: string;
  complex: boolean;
  decimated: boolean;
  /** The sweep axis — seconds for a transient, hertz for an AC run. */
  scale: Float32Array;
  scaleName: string;
  scaleType: string;
  /** By vector name, e.g. `v(/lowpass)`. */
  byName: Map<string, Float32Array>;
  /** Node voltages by net name (the SPICE spelling, lower case). */
  voltages: Map<string, Float32Array>;
  /** Device currents by reference (lower case). */
  currents: Map<string, Float32Array>;
  vectors: SimVector[];
}

export interface SimRun {
  header: SimHeader;
  plots: SimPlot[];
}

const MAGIC = "7SIM";

function magnitude(pairs: Float32Array): Float32Array {
  const out = new Float32Array(pairs.length >> 1);
  for (let i = 0; i < out.length; i += 1) {
    out[i] = Math.hypot(pairs[2 * i], pairs[2 * i + 1]);
  }
  return out;
}

export function decodeSimPayload(buffer: ArrayBuffer): SimRun {
  const bytes = new Uint8Array(buffer);
  const magic = String.fromCharCode(bytes[0], bytes[1], bytes[2], bytes[3]);
  if (magic !== MAGIC) throw new Error("not a simulation payload");
  const headerLength = new DataView(buffer).getUint32(4, true);
  const header = JSON.parse(
    new TextDecoder().decode(bytes.subarray(8, 8 + headerLength)),
  ) as SimHeader;
  const base = 8 + headerLength;
  // The server pads the header so `base` is 4-byte aligned, which is what a
  // Float32Array view over the same buffer requires. If anything ever hands
  // us an unaligned payload, copy rather than throw.
  const blob =
    base % 4 === 0 ? buffer : buffer.slice(base);
  const origin = base % 4 === 0 ? base : 0;

  const plots = header.plots.map((plot): SimPlot => {
    const view = (offset: number, len: number) =>
      new Float32Array(blob, origin + offset, len);
    const byName = new Map<string, Float32Array>();
    const voltages = new Map<string, Float32Array>();
    const currents = new Map<string, Float32Array>();
    for (const vec of plot.vectors) {
      const raw = view(vec.offset, vec.len);
      // An AC sweep returns complex numbers, stored real/imaginary in pairs.
      // What a scope shows, and what colours a wire, is the magnitude.
      const data = plot.complex ? magnitude(raw) : raw;
      byName.set(vec.name, data);
      (vec.kind === "v" ? voltages : currents).set(vec.key, data);
    }
    return {
      name: plot.name,
      complex: plot.complex,
      decimated: plot.decimated,
      scale: view(plot.scale.offset, plot.scale.len),
      scaleName: plot.scale.name,
      scaleType: plot.scale.type,
      byName,
      voltages,
      currents,
      vectors: plot.vectors,
    };
  });
  return { header, plots };
}

/** Value of a vector at a sample index, safely. */
export function at(data: Float32Array | undefined, index: number): number {
  if (!data || data.length === 0) return 0;
  return data[Math.max(0, Math.min(data.length - 1, index))];
}

/** Voltage on a net at one sample. Ground has no vector — ngspice aliases it
 *  to node 0 — so it is 0 V by definition rather than unknown. */
export function netVoltage(
  plot: SimPlot,
  spice: string | undefined,
  ground: boolean | undefined,
  index: number,
): number | null {
  if (ground) return 0;
  if (!spice) return null;
  const data = plot.voltages.get(spice);
  return data ? at(data, index) : null;
}

// ------------------------------------------------------------------ reading

/** What the overlay needs from a run, whichever kind of run it is.
 *
 *  A finished scenario is an array you index; a live session is the latest
 *  frame off a socket. The overlay should not care, so both are read through
 *  this and the drawing code was never written twice. */
export interface SampleReader {
  /** Seconds (transient) or hertz (AC sweep) at the point being shown. */
  position: number;
  scaleType: string;
  voltage(spice: string | undefined, ground: boolean | undefined): number | null;
  current(ref: string): number | null;
}

export function plotReader(plot: SimPlot, sample: number): SampleReader {
  return {
    position: at(plot.scale, sample),
    scaleType: plot.scaleType,
    voltage: (spice, ground) => netVoltage(plot, spice, ground, sample),
    current: (ref) => {
      const data = plot.currents.get(ref.toLowerCase());
      return data ? at(data, sample) : null;
    },
  };
}

/** A live frame. `index` maps a vector name to its slot in the frame. */
export function liveReader(
  position: number,
  values: Float32Array,
  index: Map<string, number>,
): SampleReader {
  const read = (name: string): number | null => {
    const i = index.get(name);
    return i === undefined ? null : values[i];
  };
  return {
    position,
    scaleType: "time",
    voltage: (spice, ground) => (ground ? 0 : spice ? read(`v(${spice})`) : null),
    current: (ref) => read(`i(@${ref.toLowerCase()}[i])`),
  };
}

// ------------------------------------------------------------------- ranges

export interface Range {
  min: number;
  max: number;
}

export function vectorRange(vectors: Iterable<Float32Array>): Range {
  let min = Infinity;
  let max = -Infinity;
  for (const data of vectors) {
    for (let i = 0; i < data.length; i += 1) {
      const v = data[i];
      if (v < min) min = v;
      if (v > max) max = v;
    }
  }
  if (!Number.isFinite(min) || !Number.isFinite(max)) return { min: 0, max: 1 };
  if (min === max) return { min: min - 1, max: max + 1 };
  return { min, max };
}

/** The vector that MOVES the most, by peak-to-peak swing.
 *
 *  The first vector in a run is whichever node ngspice happened to number
 *  first — on a real board that is usually a supply rail, and a scope opening
 *  on a flat 24 V line looks like the simulation did nothing. */
export function liveliest(plot: SimPlot, kind: "v" | "i" = "v"): SimVector | null {
  let best: SimVector | null = null;
  let bestSwing = -1;
  for (const vec of plot.vectors) {
    if (vec.kind !== kind) continue;
    const data = plot.byName.get(vec.name);
    if (!data || data.length === 0) continue;
    const { min, max } = vectorRange([data]);
    const swing = max - min;
    if (swing > bestSwing) {
      bestSwing = swing;
      best = vec;
    }
  }
  return best;
}

/** Largest absolute value across the currents, for scaling the animation. */
export function peakMagnitude(vectors: Iterable<Float32Array>): number {
  let peak = 0;
  for (const data of vectors) {
    for (let i = 0; i < data.length; i += 1) {
      const v = Math.abs(data[i]);
      if (v > peak) peak = v;
    }
  }
  return peak;
}

// ------------------------------------------------------------------ formats

const PREFIXES: [number, string][] = [
  [1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"],
  [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"], [1e-15, "f"],
];

/** Engineering notation, the way an instrument prints it. */
export function eng(value: number, unit = "", digits = 3): string {
  if (!Number.isFinite(value)) return "—";
  const abs = Math.abs(value);
  if (abs < 1e-15) return `0 ${unit}`.trim();
  const [scale, prefix] = PREFIXES.find(([s]) => abs >= s) ?? [1e-15, "f"];
  const scaled = value / scale;
  const precision = Math.abs(scaled) >= 100 ? 0 : Math.abs(scaled) >= 10 ? 1 : digits - 1;
  return `${scaled.toFixed(precision)} ${prefix}${unit}`.trim();
}
